"""Construct the real UI without recording; save an offscreen preview and exit."""
import os
import time
from pathlib import Path

os.environ["QT_QPA_PLATFORM"] = "offscreen"

from PySide6.QtCore import QSettings
from PySide6.QtGui import QFont, QFontDatabase
from PySide6.QtWidgets import QApplication

from qa_narrator.ui import MainWindow

root = Path(".validation").resolve()
root.mkdir(exist_ok=True)
QSettings.setDefaultFormat(QSettings.IniFormat)
QSettings.setPath(QSettings.IniFormat, QSettings.UserScope, str(root / "settings"))
settings = QSettings("LocalQANarrator", "QANarrator")
settings.setValue("output", str(root / "sessions"))
settings.setValue("shortcut", "Ctrl+Alt+Shift+F10")
app = QApplication([])
# The offscreen Qt platform cannot discover Windows fonts automatically.
QFontDatabase.addApplicationFont('C:/Windows/Fonts/segoeui.ttf')
app.setFont(QFont('Segoe UI', 10))
window = MainWindow()
window.show()
app.processEvents()
assert window.hotkey is not None, window.message.text()
assert window.mics.count() > 0
assert window.start.isEnabled()
assert not window.stop.isEnabled()
completed = []
window._run(lambda: 'worker-complete', completed.append)
deadline = time.monotonic() + 5
while window.busy and time.monotonic() < deadline:
    app.processEvents()
    time.sleep(0.01)
assert completed == ['worker-complete'] and not window.busy
previous_embed = window.embed_images.isChecked()
window.embed_images.setChecked(not previous_embed)
assert QSettings("LocalQANarrator", "QANarrator").value("embed_images", type=bool) == (not previous_embed)
window.embed_images.setChecked(previous_embed)
assert window.grab().save(str(root / "ui-preview.png"))
window.close()
app.processEvents()
print("Qt UI constructed; native hotkey registered; idle button state verified; preview saved.")

