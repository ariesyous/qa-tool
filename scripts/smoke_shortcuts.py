"""Check native bindings, recording lifecycle, and settings UI without recording audio.

Uses posted hotkey messages and mouse callback fixtures, not physical input.
Settings and previews stay in .validation/multiple-shortcuts.
"""

import ctypes
import time
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import patch

from PySide6.QtCore import QSettings
from PySide6.QtWidgets import QApplication

from qa_narrator.shortcut import AdditionalShortcutsDialog
from qa_narrator.ui import MainWindow
from qa_narrator.windows import MouseEvent, ScreenshotShortcuts, enable_dpi_awareness, user32

root = Path(".validation/multiple-shortcuts").resolve()
root.mkdir(parents=True, exist_ok=True)
shortcuts = [
    "Ctrl+Alt+Shift+F10", "`", "Scroll Lock",
    "Middle Mouse", "Mouse Button 4", "Mouse Button 5",
]
enable_dpi_awareness()
app = QApplication([])
app.setStyle("Fusion")
received = []


def settle(window):
    deadline = time.monotonic() + 5
    while window.busy and time.monotonic() < deadline:
        app.processEvents()
        time.sleep(0.01)
    app.processEvents()
    assert not window.busy, window.message.text()


class SmokeEngine:
    """Exercise the UI's Start/Stop path without opening a microphone."""

    def __init__(self, root, device, name, notify):
        self.session = SimpleNamespace(folder=root, screenshots=lambda: [])
        self.timeline = SimpleNamespace(state="recording", elapsed=lambda: 0.0)

    def start(self):
        return self

    def check_error(self):
        return None

    def pause_resume(self):
        self.timeline.state = "paused" if self.timeline.state == "recording" else "recording"

    def stop(self):
        return self.session


def check_recording_lifecycle(window):
    assert window.hotkey is None and window._shortcuts_ready, window.message.text()
    # A second native owner can claim every keyboard shortcut while the UI is idle.
    probe = ScreenshotShortcuts(app, lambda: None, window._shortcuts())
    probe.close()
    with (
        patch("qa_narrator.ui.CaptureEngine", SmokeEngine),
        patch.object(window, "_process"),
        patch.object(window, "_sessions"),
    ):
        try:
            window._start()
            settle(window)
            assert window.engine is not None, window.message.text()
            bindings = list(window.hotkey.bindings.values())
            assert len(bindings) == len(window._shortcuts())
            assert all(b.registered or b.mouse_hook is not None for b in bindings)
            # Windows must reject a competing owner while recording (and paused).
            for paused in (False, True):
                if paused:
                    window._pause()
                    assert window.engine.timeline.state == "paused"
                try:
                    probe = ScreenshotShortcuts(app, lambda: None, window._shortcuts()[:1])
                except OSError:
                    pass
                else:
                    probe.close()
                    raise AssertionError("Recording did not reserve the keyboard shortcut")
            window._stop()
            settle(window)
            assert window.engine is None and window.hotkey is None
            assert window._shortcuts_ready and window.start.isEnabled()
            assert all(not b.registered and b.mouse_hook is None for b in bindings)
            probe = ScreenshotShortcuts(app, lambda: None, window._shortcuts())
            probe.close()
        finally:
            if window.engine is not None:
                window._stop()
            settle(window)


group = ScreenshotShortcuts(app, lambda: received.append(True), shortcuts)
try:
    for binding in group.bindings.values():
        if binding.registered:
            assert user32.PostThreadMessageW(
                ctypes.windll.kernel32.GetCurrentThreadId(), 0x0312, binding.key_id, 0
            )
        else:
            event = MouseEvent()
            key = next(key for key, value in group.bindings.items() if value is binding)
            button = key[-1]
            message = 0x207 if button == "MIDDLE MOUSE" else 0x20B
            event.mouseData = {"MIDDLE MOUSE": 0, "MOUSE BUTTON 4": 1, "MOUSE BUTTON 5": 2}[button] << 16
            binding.mouse_hook.procedure(0, message, ctypes.addressof(event))
    deadline = time.monotonic() + 3
    while len(received) < 6 and time.monotonic() < deadline:
        app.processEvents()
        time.sleep(0.01)
    assert len(received) == 6, received
    group.configure(shortcuts[:1])
    assert len(group.bindings) == 1
finally:
    group.close()

settings = QSettings(str(root / "settings.ini"), QSettings.IniFormat)
settings.clear()
settings.setValue("output", str(root / "sessions"))
settings.setValue("shortcut", shortcuts[0])
with patch("qa_narrator.ui.QSettings", return_value=settings):
    window = MainWindow()
    try:
        window.show()
        app.processEvents()
        assert window.hotkey is None and window._shortcuts_ready, window.message.text()
        assert window.grab().save(str(root / "single-shortcut.png"))
        window._save_shortcuts(shortcuts)
        assert window._apply(), window.message.text()
        assert window.hotkey is None
        check_recording_lifecycle(window)
        dialog = AdditionalShortcutsDialog(window)
        dialog.show()
        app.processEvents()
        assert not dialog.add.isEnabled()
        assert window.grab().save(str(root / "six-shortcuts.png"))
        assert dialog.grab().save(str(root / "additional-shortcuts.png"))
        dialog.close()
    finally:
        window.close()
    reopened = MainWindow()
    try:
        assert reopened._shortcuts() == shortcuts
        check_recording_lifecycle(reopened)
    finally:
        reopened.close()
print("PASS: native dispatch, idle release, Start/Pause/Stop reservation, reload, and UI previews.")
