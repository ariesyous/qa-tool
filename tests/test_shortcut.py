import os
from types import SimpleNamespace

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

import pytest
from PySide6.QtCore import QEvent, QPointF, Qt
from PySide6.QtGui import QKeyEvent, QMouseEvent
from PySide6.QtWidgets import QApplication, QDialog

from qa_narrator.shortcut import ShortcutDialog
from qa_narrator.windows import (
    mouse_message_matches,
    parse_hotkey,
    parse_mouse_shortcut,
    shortcut_label,
)


@pytest.fixture(scope="module")
def app():
    return QApplication.instance() or QApplication([])


@pytest.mark.parametrize(
    "button,name",
    [
        (Qt.MiddleButton, "Middle Mouse"),
        (Qt.BackButton, "Mouse Button 4"),
        (Qt.ForwardButton, "Mouse Button 5"),
    ],
)
def test_picker_records_mouse_button_with_optional_modifiers(app, button, name):
    dialog = ShortcutDialog()
    dialog.show()
    event = QMouseEvent(
        QEvent.MouseButtonPress, QPointF(5, 5), QPointF(5, 5), button, button, Qt.ControlModifier
    )
    assert dialog.eventFilter(dialog, event)
    assert dialog.shortcut == "Ctrl+" + name
    assert dialog.result() == QDialog.Accepted


def test_picker_records_key_combination(app):
    dialog = ShortcutDialog()
    dialog.show()
    event = QKeyEvent(QEvent.KeyPress, Qt.Key_F9, Qt.ControlModifier | Qt.AltModifier)
    assert dialog.eventFilter(dialog, event)
    assert dialog.shortcut == "Ctrl+Alt+F9"


@pytest.mark.parametrize("key,native,text,modifiers,label", [
    (Qt.Key_QuoteLeft, 0xDF, "`", Qt.NoModifier, "`"),
    (Qt.Key_AsciiTilde, 0xC0, "~", Qt.ShiftModifier, "Shift+~"),
    (Qt.Key_Odiaeresis, 0xC0, "ö", Qt.NoModifier, "ö"),
    (Qt.Key_QuoteLeft, 0x37, "`", Qt.ControlModifier | Qt.AltModifier, "Ctrl+Alt+`"),
    (Qt.Key_A, 0x51, "a", Qt.ControlModifier, "Ctrl+A"),
])
def test_picker_preserves_native_key_instead_of_reconstructing_from_character(
    app, key, native, text, modifiers, label
):
    dialog = ShortcutDialog()
    dialog.show()
    event = QKeyEvent(QEvent.KeyPress, key, modifiers, 0, native, 0, text)
    assert dialog.eventFilter(dialog, event)
    assert dialog.shortcut == f"{label} [VK:0x{native:02X}]"
    assert parse_hotkey(dialog.shortcut)[1] == native
    assert shortcut_label(dialog.shortcut) == label
    assert dialog.result() == QDialog.Accepted


def test_native_shortcuts_validate_duplicates_and_reject_reserved_keys():
    from qa_narrator.windows import validate_shortcuts

    with pytest.raises(ValueError, match="already configured"):
        validate_shortcuts(["`", "ö [VK:0xC0]"])
    with pytest.raises(ValueError):
        parse_hotkey("Ctrl+F12 [VK:0x7B]")


@pytest.mark.parametrize("key,name", [(Qt.Key_QuoteLeft, "`"), (Qt.Key_ScrollLock, "Scroll Lock")])
@pytest.mark.parametrize("modifiers,prefix", [(Qt.NoModifier, ""), (Qt.ControlModifier, "Ctrl+")])
def test_picker_records_backtick_and_scroll_lock(app, key, name, modifiers, prefix):
    dialog = ShortcutDialog()
    dialog.show()
    assert dialog.eventFilter(dialog, QKeyEvent(QEvent.KeyPress, key, modifiers))
    assert dialog.shortcut == prefix + name
    assert dialog.result() == QDialog.Accepted


@pytest.mark.parametrize("key", [Qt.Key_QuoteLeft, Qt.Key_ScrollLock])
def test_picker_ignores_repeated_standalone_key(app, key):
    dialog = ShortcutDialog()
    dialog.show()
    assert dialog.eventFilter(dialog, QKeyEvent(QEvent.KeyPress, key, Qt.NoModifier, "", True))
    assert dialog.shortcut is None
    dialog.close()


def test_picker_ignores_primary_click_and_modifier_only_then_cancels(app):
    dialog = ShortcutDialog()
    dialog.show()
    event = QMouseEvent(
        QEvent.MouseButtonPress,
        QPointF(5, 5),
        QPointF(5, 5),
        Qt.LeftButton,
        Qt.LeftButton,
        Qt.NoModifier,
    )
    assert not dialog.eventFilter(dialog, event)
    dialog.eventFilter(dialog, QKeyEvent(QEvent.KeyPress, Qt.Key_Control, Qt.ControlModifier))
    assert dialog.shortcut is None and dialog.isVisible()
    dialog.eventFilter(dialog, QKeyEvent(QEvent.KeyPress, Qt.Key_Escape, Qt.NoModifier))
    assert dialog.shortcut is None and dialog.result() == QDialog.Rejected


def test_picker_rejects_reserved_keyboard_shortcut(app):
    dialog = ShortcutDialog()
    dialog.show()
    dialog.eventFilter(dialog, QKeyEvent(QEvent.KeyPress, Qt.Key_F12, Qt.ControlModifier))
    assert dialog.shortcut is None and dialog.isVisible()
    dialog.close()


def test_mouse_binding_parse_and_press_only_matching():
    assert parse_mouse_shortcut("Middle Mouse") == (0, "MIDDLE MOUSE")
    assert parse_mouse_shortcut("Ctrl+Alt+Mouse Button 5") == (3, "MOUSE BUTTON 5")
    assert parse_mouse_shortcut("Ctrl+Alt+F9") is None
    with pytest.raises(ValueError):
        parse_mouse_shortcut("Ctrl+Ctrl+Middle Mouse")
    assert mouse_message_matches("MIDDLE MOUSE", 0x207, 0)
    assert not mouse_message_matches("MIDDLE MOUSE", 0x208, 0)
    assert mouse_message_matches("MOUSE BUTTON 4", 0x20B, 1 << 16)
    assert not mouse_message_matches("MOUSE BUTTON 4", 0x20B, 2 << 16)
    assert mouse_message_matches("MOUSE BUTTON 5", 0x20B, 2 << 16)
    assert not mouse_message_matches("MOUSE BUTTON 5", 0x20C, 2 << 16)


@pytest.mark.parametrize(
    "choice,fail", [("Middle Mouse", False), (None, False), ("Mouse Button 5", True)]
)
def test_picker_saves_immediately_and_restores_previous_on_cancel_or_failure(
    app, monkeypatch, choice, fail
):
    from qa_narrator.ui import MainWindow

    saved, attempts, closed, errors = {}, [], [], []
    old = SimpleNamespace(close=lambda: closed.append(True))
    widget = SimpleNamespace(setText=lambda _: None)
    owner = SimpleNamespace(
        shortcut="Ctrl+Alt+F9",
        additional_shortcuts=["Ctrl+F8"],
        hotkey=old,
        engine=None,
        _shortcuts_ready=False,
        _capture=lambda: None,
        _controls=lambda: None,
        _notice=lambda *args: errors.append(args),
        shortcut_button=widget,
        additional_shortcuts_button=widget,
        hint=widget,
        settings=SimpleNamespace(setValue=saved.__setitem__, sync=lambda: None),
    )
    for name in (
        "_shortcuts",
        "_save_shortcuts",
        "_refresh_shortcuts",
        "_release_shortcuts",
        "_disarm_shortcuts",
    ):
        setattr(owner, name, getattr(MainWindow, name).__get__(owner))
    monkeypatch.setattr(
        "qa_narrator.ui.ShortcutDialog",
        lambda _: SimpleNamespace(shortcut=choice, exec=lambda: bool(choice)),
    )

    def install(_app, _callback, binding):
        attempts.append(binding)
        if fail and binding[0] == choice:
            raise OSError("Registration failed")
        return SimpleNamespace(close=lambda: None)

    monkeypatch.setattr("qa_narrator.ui.ScreenshotShortcuts", install)
    MainWindow._choose_shortcut(owner)
    expected = choice if choice and not fail else "Ctrl+Alt+F9"
    # Validated, then released again because no recording is active.
    assert closed and owner.hotkey is None and owner._shortcuts_ready
    assert owner.shortcut == saved["shortcut"] == expected
    assert attempts[-1] == [expected, "Ctrl+F8"]
    assert saved["additional_shortcuts"] == ["Ctrl+F8"]
    assert bool(errors) == fail
