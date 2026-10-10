"""Atomic session metadata and recoverable headerless PCM audio."""

import json
import os
import threading
import uuid
import wave
from datetime import datetime
from pathlib import Path


def atomic_bytes(path, data):
    path = Path(path)
    tmp = path.with_name(path.name + ".tmp-" + uuid.uuid4().hex)
    try:
        with tmp.open("wb") as handle:
            handle.write(data)
            handle.flush()
            os.fsync(handle.fileno())
        os.replace(tmp, path)
    finally:
        tmp.unlink(missing_ok=True)


def atomic_json(path, data):
    atomic_bytes(path, (json.dumps(data, ensure_ascii=False, indent=2) + "\n").encode("utf-8"))


class Session:
    def __init__(self, folder, data):
        self.folder, self.data = Path(folder), data
        self.lock = threading.RLock()

    @classmethod
    def create(cls, root, rate, microphone):
        now = datetime.now().astimezone()
        folder = Path(root) / (now.strftime("%Y-%m-%d_%H%M%S") + "_" + uuid.uuid4().hex[:8])
        (folder / "screenshots").mkdir(parents=True)
        session = cls(
            folder,
            {
                "version": 1,
                "created": now.isoformat(),
                "status": "recording",
                "sample_rate": rate,
                "channels": 1,
                "sample_width": 2,
                "microphone": microphone,
                "duration": 0,
                "events": [],
                "transcription_status": "pending",
                "export_status": "pending",
            },
        )
        session.save()
        return session

    @classmethod
    def load(cls, folder):
        folder = Path(folder)
        data = json.loads((folder / "session.json").read_text(encoding="utf-8"))
        if data.get("version") != 1:
            raise ValueError("Unsupported session format")
        required = {
            "created",
            "status",
            "sample_rate",
            "duration",
            "events",
            "transcription_status",
            "export_status",
        }
        if not required.issubset(data) or not isinstance(data["events"], list):
            raise ValueError("Session metadata is incomplete")
        if not isinstance(data["sample_rate"], int) or data["sample_rate"] <= 0:
            raise ValueError("Session sample rate is invalid")
        return cls(folder, data)

    def save(self):
        with self.lock:
            atomic_json(self.folder / "session.json", self.data)

    def update(self, **fields):
        with self.lock:
            self.data.update(fields)
            self.save()

    def event(self, event):
        with self.lock:
            event = dict(event, sequence=len(self.data["events"]))
            self.data["events"].append(event)
            self.save()

    def screenshots(self):
        with self.lock:
            return [dict(e) for e in self.data["events"] if e["kind"] == "screenshot"]

    def finalize_audio(self, duration=None):
        pcm = self.folder / "audio.pcm"
        if not pcm.exists():
            raise ValueError("This session has no recoverable audio.pcm")
        rate = int(self.data["sample_rate"])
        frame_count = pcm.stat().st_size // 2
        # Never synthesize a long unrecorded tail on crash recovery.
        target_frames = max(frame_count, round((duration or 0) * rate))
        if target_frames == 0:
            raise ValueError("No audio samples were recorded; screenshots remain available")
        if target_frames * 2 > 0xFFFFFFFF - 36:
            raise ValueError("Audio exceeds WAV's 4 GB limit; preserve audio.pcm for recovery")
        tmp = self.folder / "audio.wav.tmp"
        with wave.open(str(tmp), "wb") as output:
            output.setparams((1, 2, rate, 0, "NONE", "not compressed"))
            with pcm.open("rb") as source:
                remaining = frame_count * 2
                while remaining:
                    block = source.read(min(1024 * 1024, remaining))
                    if not block:
                        raise OSError("PCM audio was truncated during finalization")
                    output.writeframesraw(block)
                    remaining -= len(block)
            padding = (target_frames - frame_count) * 2
            while padding:
                size = min(padding, 1024 * 1024)
                output.writeframesraw(b"\0" * size)
                padding -= size
        with tmp.open("rb+") as handle:
            os.fsync(handle.fileno())
        os.replace(tmp, self.folder / "audio.wav")
        self.update(duration=target_frames / rate)

    def recover(self):
        if self.data["status"] in ("recording", "paused", "stopping", "capture_error"):
            self.finalize_audio()
            self.update(
                status="recovered",
                recovery_note="Recovered persisted PCM; final buffers may be missing.",
            )
        # A PNG sidecar is committed before session.json, so a crash cannot orphan its timing.
        known = {e["path"] for e in self.screenshots()}
        for sidecar in sorted((self.folder / "screenshots").glob("*.json")):
            event = json.loads(sidecar.read_text(encoding="utf-8"))
            if event["path"] not in known and (self.folder / event["path"]).is_file():
                self.event(event)
                known.add(event["path"])
        if self.data.get("transcription_status") == "processing":
            self.update(transcription_status="interrupted")


def list_sessions(root):
    root = Path(root)
    if not root.exists():
        return []
    result = []
    for path in root.glob("*/session.json"):
        try:
            result.append(Session.load(path.parent))
        except (ValueError, OSError):
            continue
    return sorted(result, key=lambda s: s.data["created"], reverse=True)
