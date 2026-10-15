"""Offline inference and export using a local, synthetic speech fixture."""
import argparse
import json
import os
import shutil
import socket
import wave
from pathlib import Path

from PIL import Image

from qa_narrator.storage import Session
from qa_narrator.transcription import process_session

parser = argparse.ArgumentParser()
parser.add_argument("--vocabulary", default=None)
args = parser.parse_args()

os.environ["HF_HUB_OFFLINE"] = "1"
os.environ["HF_HUB_DISABLE_TELEMETRY"] = "1"


def deny_network(*args, **kwargs):
    raise AssertionError("Network access is forbidden during local transcription")


socket.socket.connect = deny_network
socket.create_connection = deny_network
root = Path(".validation").resolve()
speech = root / "speech.wav"
with wave.open(str(speech)) as audio:
    duration = audio.getnframes() / audio.getframerate()
    rate = audio.getframerate()
session = Session.create(root / "offline", rate, "Synthetic Windows SAPI speech fixture")
shutil.copyfile(speech, session.folder / "audio.wav")
session.update(status="stopped", duration=duration)
for number, fraction in enumerate((0.1, 0.3, 0.5, 0.7, 0.9), 1):
    path = f"screenshots/{number:03d}.png"
    Image.new("RGB", (200, 100), (number * 40, 70, 140)).save(session.folder / path)
    session.event({"kind": "screenshot", "number": number, "path": path, "t": duration * fraction})
result = process_session(session, progress=print, vocabulary=args.vocabulary)
data = json.loads((session.folder / "transcription.json").read_text(encoding="utf-8"))
text = "".join(segment["text"] for segment in data["segments"])
assert "button" in text.lower() and "confirmation" in text.lower(), text
assert all(segment["words"] for segment in data["segments"])
assert data["vocabulary"] == " ".join((args.vocabulary or "").split())
markdown = result.read_text(encoding="utf-8")
assert markdown.count("](screenshots/") == 5
assert Session.load(session.folder).data["export_status"] == "complete"
(root / "offline-result.json").write_text(json.dumps({"session": str(session.folder), "text": text,
                                                     "network": "blocked by socket guard"}, indent=2), encoding="utf-8")
print("OFFLINE INFERENCE / EXPORT PASSED:", result)

