"""Check packaged compact/raw exports and standalone shrinking without a microphone."""

import argparse
import base64
import hashlib
import json
import random
import subprocess
from pathlib import Path

from PIL import Image

from qa_narrator import __version__
from qa_narrator.compact import COMPACT_TARGET_BYTES, DATA_IMAGE
from qa_narrator.storage import Session, atomic_json


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--exe", default=f"dist/v{__version__}/QANarrator/QANarrator.exe")
    args = parser.parse_args()
    exe = Path(args.exe).resolve()
    root = Path(f".validation/release-v{__version__}/exports").resolve()

    def run(*arguments):
        result = subprocess.run(
            [str(exe), *arguments], timeout=120, capture_output=True,
            creationflags=subprocess.CREATE_NO_WINDOW,
        )
        if result.returncode:
            raise RuntimeError(f"Packaged operation failed: {arguments}; {result.stderr!r}")

    sizes = {}
    for label, image in (
        ("small", Image.new("RGB", (3840, 2160), (100, 150, 200))),
        ("large", Image.frombytes("RGB", (3840, 2160), random.Random(42).randbytes(3840 * 2160 * 3))),
    ):
        session = Session.create(root / label, 16000, "Synthetic export fixture")
        session.update(status="stopped", duration=1)
        image.save(session.folder / "screenshots/001.png")
        session.event({"kind": "screenshot", "number": 1, "path": "screenshots/001.png", "t": 0})
        atomic_json(session.folder / "transcription.json", {"segments": []})
        run("--export", str(session.folder), "--embed-images", "--image-quality", "raw")
        report = session.folder / "feedback.md"
        raw = report.read_bytes()
        original_png = (session.folder / "screenshots/001.png").read_bytes()
        if base64.b64decode(DATA_IMAGE.search(raw).group(2)) != original_png:
            raise AssertionError("Raw export changed the PNG")
        run("--export", str(session.folder), "--embed-images", "--image-quality", "compact")
        compact = report.read_bytes()
        if len(compact) > COMPACT_TARGET_BYTES:
            raise AssertionError("Compact export exceeded its target")
        if label == "small":
            if base64.b64decode(DATA_IMAGE.search(compact).group(2)) != original_png:
                raise AssertionError("Within-budget compact export changed the PNG")
        elif len(raw) <= COMPACT_TARGET_BYTES or len(compact) >= len(raw):
            raise AssertionError("Oversized fixture did not exercise compression")
        source = session.folder / "standalone.md"
        original = raw + b"\nManual **feedback** stays here.\n"
        source.write_bytes(original)
        run("--shrink-markdown", str(source))
        shrunk = source.with_name("standalone.compact.md").read_bytes()
        if source.read_bytes() != original or len(shrunk) > COMPACT_TARGET_BYTES:
            raise AssertionError("Standalone shrink changed its source or exceeded its target")
        if label == "small" and shrunk != original:
            raise AssertionError("Within-budget standalone copy changed")
        if DATA_IMAGE.sub(b"IMAGE", shrunk) != DATA_IMAGE.sub(b"IMAGE", original):
            raise AssertionError("Standalone shrink changed manual notes")
        run("--export", str(session.folder), "--linked-images")
        if "](screenshots/001.png)" not in report.read_text(encoding="utf-8"):
            raise AssertionError("Linked export did not retain its relative path")
        sizes[label] = {"raw": len(raw), "compact": len(compact), "standalone": len(shrunk)}
        print(f"PASS: {label} packaged raw/compact/linked export and standalone shrink")
    summary = {"version": __version__, "sizes": sizes,
               "executable_sha256": hashlib.sha256(exe.read_bytes()).hexdigest()}
    root.mkdir(parents=True, exist_ok=True)
    (root / "result.json").write_text(json.dumps(summary, indent=2), encoding="utf-8")
    print(json.dumps(summary, indent=2))


if __name__ == "__main__":
    main()
