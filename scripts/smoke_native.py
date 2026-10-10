"""Explicit opt-in microphone smoke test. No network; screenshots only the test window.

Run: python scripts/smoke_native.py --record-microphone
This is not proof of the human narrated browser acceptance scenario.
"""
import argparse
import ctypes
import json
import time
import wave
from pathlib import Path

from PySide6.QtCore import QTimer, Qt
from PySide6.QtWidgets import QApplication, QLabel

from qa_narrator.capture import CaptureEngine
from qa_narrator.windows import enable_dpi_awareness, install_hotkey, parse_hotkey, user32

parser = argparse.ArgumentParser()
parser.add_argument("--record-microphone", action="store_true", required=True)
parser.parse_args()
enable_dpi_awareness()
app = QApplication([])
window = QLabel("QA Narrator native capture test\n\nFive screenshots · pause / resume\nLocal test fixture")
window.setWindowTitle("QA Narrator validation fixture")
window.setStyleSheet("background: #e9f2ff; color: #20324a; padding: 30px; font-size: 24px")
window.setAlignment(Qt.AlignCenter)
window.resize(650, 300)
window.show()
app.processEvents()
notices = []
root = Path(".validation/native").resolve()
engine = CaptureEngine(root, None, "System default (native smoke test)", lambda *args: notices.append(args))
engine.start()
target = {"hwnd": int(window.winId()), "mode": "window", "monitor": 1}
called = []
hotkey = install_hotkey(app, lambda: called.append(True), "Ctrl+Alt+F9")
modifiers, key = parse_hotkey("Ctrl+Alt+F9")
assert not user32.RegisterHotKey(None, 0x5143, modifiers, key), "Conflict detection failed"
# Test the actual Qt native event filter with a Windows message. Physical keypress remains manual.
user32.PostThreadMessageW.argtypes = [ctypes.c_ulong, ctypes.c_uint, ctypes.c_size_t, ctypes.c_ssize_t]
user32.PostThreadMessageW(ctypes.windll.kernel32.GetCurrentThreadId(), 0x0312, hotkey.key_id, 0)
for delay in (400, 900, 1400, 3300, 3900):
    QTimer.singleShot(delay, lambda: engine.capture(target))
QTimer.singleShot(1800, engine.pause_resume)
QTimer.singleShot(2800, engine.pause_resume)
QTimer.singleShot(4700, app.quit)
start = time.perf_counter()
app.exec()
elapsed = time.perf_counter() - start
session = engine.stop()
hotkey.close()
window.close()
with wave.open(str(session.folder / "audio.wav")) as audio:
    duration = audio.getnframes() / audio.getframerate()
assert called, "WM_HOTKEY was not routed by Qt"
assert engine.check_error() is None
assert len(session.screenshots()) == 5, notices
assert abs(duration - (elapsed - 1)) < 0.4, (duration, elapsed)
assert [e["t"] for e in session.screenshots()] == sorted(e["t"] for e in session.screenshots())
result = {"session": str(session.folder), "duration": duration, "wall_elapsed": elapsed,
          "screenshots": len(session.screenshots()), "hotkey_registration_conflict_and_message": "passed",
          "notices": notices}
(root / "result.json").write_text(json.dumps(result, indent=2), encoding="utf-8")
print(json.dumps(result, indent=2))

