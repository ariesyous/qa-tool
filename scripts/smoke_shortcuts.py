"""Check six native bindings and preview the real settings UI without recording.

Uses posted hotkey messages and mouse callback fixtures, not physical input.
Settings and previews stay in .validation/multiple-shortcuts.
"""

import ctypes
import time
from pathlib import Path
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
        assert window.hotkey is not None, window.message.text()
        assert window.grab().save(str(root / "single-shortcut.png"))
        window.hotkey.configure(shortcuts)
        window._save_shortcuts(shortcuts)
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
        assert len(reopened.hotkey.bindings) == 6
    finally:
        reopened.close()
print("PASS: six native bindings, posted keyboard/mouse fixture dispatch, removal, reload, and UI previews.")
