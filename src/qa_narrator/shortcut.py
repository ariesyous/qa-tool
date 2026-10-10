"""Record an actual keyboard combination or middle/side mouse press in a modal picker."""

from PySide6.QtCore import QEvent, Qt
from PySide6.QtWidgets import QApplication, QDialog, QLabel, QPushButton, QVBoxLayout

from .windows import parse_hotkey, parse_mouse_shortcut


def modifier_names(modifiers):
    return [
        name
        for flag, name in (
            (Qt.ControlModifier, "Ctrl"),
            (Qt.AltModifier, "Alt"),
            (Qt.ShiftModifier, "Shift"),
            (Qt.MetaModifier, "Win"),
        )
        if modifiers & flag
    ]


class ShortcutDialog(QDialog):
    def __init__(self, parent=None):
        super().__init__(parent)
        self.setWindowTitle("Record screenshot shortcut")
        self.setMinimumWidth(440)
        self.shortcut = None
        layout = QVBoxLayout(self)
        self.prompt = QLabel(
            "Press your keyboard shortcut, or click the middle / side mouse button here."
        )
        self.prompt.setWordWrap(True)
        layout.addWidget(self.prompt)
        hint = QLabel(
            "Keyboard: Ctrl, Alt, or Win + F1–F11, A–Z, or 0–9.\n"
            "Mouse: middle, button 4, or button 5; modifiers are optional.\n"
            "Mouse buttons keep their normal behavior in other apps.\n"
            "Press Esc to cancel. Left and right click are not assigned."
        )
        hint.setWordWrap(True)
        layout.addWidget(hint)
        self.cancel = QPushButton("Cancel")
        self.cancel.setAutoDefault(False)
        self.cancel.clicked.connect(self.reject)
        layout.addWidget(self.cancel)

    def exec(self):
        app = QApplication.instance()
        app.installEventFilter(self)
        try:
            return super().exec()
        finally:
            app.removeEventFilter(self)

    def eventFilter(self, target, event):
        if not self.isVisible():
            return False
        if event.type() == QEvent.ShortcutOverride:
            event.accept()
            return True
        if event.type() == QEvent.KeyPress:
            if event.key() == Qt.Key_Escape:
                self.reject()
                return True
            if event.isAutoRepeat() or event.key() in (
                Qt.Key_Control,
                Qt.Key_Alt,
                Qt.Key_Shift,
                Qt.Key_Meta,
            ):
                return True
            key = event.key()
            if Qt.Key_F1 <= key <= Qt.Key_F11:
                name = f"F{key - Qt.Key_F1 + 1}"
            elif Qt.Key_A <= key <= Qt.Key_Z or Qt.Key_0 <= key <= Qt.Key_9:
                name = chr(key)
            else:
                self.prompt.setText(
                    "Use Ctrl, Alt, or Win with F1–F11, A–Z, or 0–9; or a middle/side mouse button."
                )
                return True
            self._select("+".join(modifier_names(event.modifiers()) + [name]))
            return True
        if event.type() in (QEvent.MouseButtonPress, QEvent.MouseButtonDblClick):
            name = {
                Qt.MiddleButton: "Middle Mouse",
                Qt.BackButton: "Mouse Button 4",
                Qt.ForwardButton: "Mouse Button 5",
            }.get(event.button())
            if name:
                self._select("+".join(modifier_names(event.modifiers()) + [name]))
                return True
        return False

    def _select(self, shortcut):
        try:
            if parse_mouse_shortcut(shortcut) is None:
                parse_hotkey(shortcut)
        except ValueError as exc:
            self.prompt.setText(str(exc))
            return
        self.shortcut = shortcut
        self.accept()
