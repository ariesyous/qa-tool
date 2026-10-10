"""Record an actual keyboard combination or middle/side mouse press in a modal picker."""

from PySide6.QtCore import QEvent, Qt
from PySide6.QtWidgets import QApplication, QDialog, QHBoxLayout, QLabel, QPushButton, QVBoxLayout

from .windows import MAX_ADDITIONAL_SHORTCUTS, parse_hotkey, parse_mouse_shortcut


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


class AdditionalShortcutsDialog(QDialog):
    def __init__(self, parent):
        super().__init__(parent)
        self.owner = parent
        self.setWindowTitle("Additional screenshot shortcuts")
        self.setMinimumWidth(440)
        layout = QVBoxLayout(self)
        hint = QLabel(
            f"Add up to {MAX_ADDITIONAL_SHORTCUTS} more keyboard or mouse shortcuts.\n"
            "All shortcuts capture the same way. Changes save immediately."
        )
        hint.setWordWrap(True)
        layout.addWidget(hint)
        self.rows = []
        for index in range(MAX_ADDITIONAL_SHORTCUTS):
            row = QHBoxLayout()
            change = QPushButton()
            remove = QPushButton("Remove")
            change.clicked.connect(lambda checked=False, i=index: self._choose(i + 1))
            remove.clicked.connect(lambda checked=False, i=index: self._remove(i + 1))
            row.addWidget(change, 1)
            row.addWidget(remove)
            layout.addLayout(row)
            self.rows.append((change, remove))
        self.add = QPushButton("Add shortcut…")
        self.add.clicked.connect(lambda: self._choose(None))
        layout.addWidget(self.add)
        self.message = QLabel()
        self.message.setWordWrap(True)
        layout.addWidget(self.message)
        done = QPushButton("Done")
        done.clicked.connect(self.accept)
        layout.addWidget(done)
        self.refresh()

    def refresh(self):
        shortcuts = self.owner.additional_shortcuts
        for index, (change, remove) in enumerate(self.rows):
            present = index < len(shortcuts)
            change.setVisible(present)
            remove.setVisible(present)
            if present:
                change.setText(f"{shortcuts[index]}  ·  Change…")
        self.add.setEnabled(len(shortcuts) < MAX_ADDITIONAL_SHORTCUTS)
        self.add.setText(f"Add shortcut… ({len(shortcuts)}/{MAX_ADDITIONAL_SHORTCUTS})")

    def _choose(self, index):
        self.message.setText(self.owner._choose_shortcut(index, self) or "")
        self.refresh()

    def _remove(self, index):
        self.message.setText(self.owner._remove_shortcut(index) or "")
        self.refresh()


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
            "Backtick (`) and Scroll Lock also work without modifiers.\n"
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
            elif key == Qt.Key_QuoteLeft:
                name = "`"
            elif key == Qt.Key_ScrollLock:
                name = "Scroll Lock"
            else:
                self.prompt.setText(
                    "Use Ctrl, Alt, or Win with F1–F11, A–Z, or 0–9; "
                    "backtick (`) / Scroll Lock with optional modifiers; "
                    "or a middle/side mouse button."
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
