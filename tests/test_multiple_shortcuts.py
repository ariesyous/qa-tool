import ctypes
import os
from contextlib import nullcontext
from ctypes import wintypes
from types import SimpleNamespace

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

import pytest
from PySide6.QtCore import QSettings
from PySide6.QtWidgets import QApplication

from qa_narrator import windows
from qa_narrator.shortcut import AdditionalShortcutsDialog
from qa_narrator.ui import MainWindow


@pytest.fixture(scope="module")
def app():
    return QApplication.instance() or QApplication([])


@pytest.fixture
def native(monkeypatch):
    registered, hooks = {}, []
    blocked = set()

    def register(hwnd, key_id, modifiers, key):
        assert key_id not in registered
        if key in blocked or (modifiers, key) in registered.values():
            return False
        registered[key_id] = (modifiers, key)
        return True

    class Hook:
        def __init__(self, modifiers, button, notify):
            self.notify = notify
            self.closed = False
            hooks.append(self)

        def close(self):
            self.closed = True

    monkeypatch.setattr(windows, "user32", SimpleNamespace(
        RegisterHotKey=register,
        UnregisterHotKey=lambda hwnd, key_id: registered.pop(key_id),
    ), raising=False)
    monkeypatch.setattr(windows, "MouseHook", Hook)
    return SimpleNamespace(registered=registered, hooks=hooks, blocked=blocked)


def fire_keyboard(binding):
    msg = wintypes.MSG()
    msg.message, msg.wParam = 0x0312, binding.key_id
    assert binding.nativeEventFilter(None, ctypes.addressof(msg)) == (True, 0)


def test_six_keyboard_shortcuts_dispatch_once_and_release(app, native):
    calls = []
    group = windows.ScreenshotShortcuts(app, lambda: calls.append(True), [
        f"Ctrl+Alt+F{i}" for i in range(1, 7)
    ])
    try:
        assert len(native.registered) == 6
        for binding in group.bindings.values():
            msg = wintypes.MSG()
            msg.message, msg.wParam = 0x0312, binding.key_id
            for listener in group.bindings.values():
                listener.nativeEventFilter(None, ctypes.addressof(msg))
        assert len(calls) == 6
    finally:
        group.close()
    assert not native.registered
    assert not windows._hotkey_ids


def test_mixed_shortcuts_remove_reconfigure_and_cleanup(app, native):
    calls = []
    group = windows.ScreenshotShortcuts(app, lambda: calls.append(True), [
        "Ctrl+F9", "Middle Mouse", "Ctrl+Mouse Button 4", "Mouse Button 5"
    ])
    try:
        keyboard = next(iter(group.bindings.values()))
        fire_keyboard(keyboard)
        for hook in native.hooks:
            hook.notify()
        app.processEvents()
        assert len(calls) == 4
        group.configure(["Alt+F10", "Mouse Button 5"])
        assert len(native.registered) == 1
        assert [hook.closed for hook in native.hooks] == [True, True, False]
        assert keyboard.nativeEventFilter(None, ctypes.addressof(wintypes.MSG())) == (False, 0)
    finally:
        group.close()
    assert not native.registered and all(h.closed for h in native.hooks)


def test_failed_add_rolls_back_partial_registrations(app, native):
    group = windows.ScreenshotShortcuts(app, lambda: None, ["Ctrl+F9", "Middle Mouse"])
    original = dict(group.bindings)
    native.blocked.add(windows.parse_hotkey("Ctrl+F11")[1])
    try:
        with pytest.raises(OSError):
            group.configure(["Ctrl+F9", "Middle Mouse", "Mouse Button 4", "Ctrl+F10", "Ctrl+F11"])
        assert group.bindings == original
        assert len(native.registered) == 1
        assert not native.hooks[0].closed and native.hooks[1].closed
    finally:
        group.close()
    with pytest.raises(OSError):
        windows.ScreenshotShortcuts(app, lambda: None, ["Ctrl+F9", "Ctrl+F11"])
    assert not native.registered and not windows._hotkey_ids


@pytest.mark.parametrize("shortcuts", [
    [],
    [f"Ctrl+F{i}" for i in range(1, 8)],
    ["Ctrl+Alt+F9", "alt + ctrl + f9"],
    ["Ctrl+Alt+Mouse Button 4", "alt+ctrl+mouse button 4"],
])
def test_invalid_sets_rejected_before_registering(app, native, shortcuts):
    with pytest.raises(ValueError):
        windows.ScreenshotShortcuts(app, lambda: None, shortcuts)
    assert not native.registered and not native.hooks


def test_single_binding_switch_releases_id_for_other_bindings(app, native):
    first = windows.install_hotkey(app, lambda: None, "Ctrl+F9")
    second = windows.install_hotkey(app, lambda: None, "Ctrl+F10")
    try:
        first.configure("Middle Mouse")
        second.configure("Ctrl+F8")
        first.configure("Ctrl+F9")
        assert len(native.registered) == len(windows._hotkey_ids) == 2
        assert first.key_id != second.key_id
    finally:
        first.close()
        second.close()
    assert not windows._hotkey_ids


@pytest.fixture
def window(app, native, monkeypatch, tmp_path):
    settings = QSettings(str(tmp_path / "settings.ini"), QSettings.IniFormat)
    settings.setValue("output", str(tmp_path / "sessions"))
    settings.setValue("shortcut", "Ctrl+F9")
    monkeypatch.setattr("qa_narrator.ui.QSettings", lambda *args: settings)
    monkeypatch.setattr(MainWindow, "_devices", lambda self: self.mics.addItem("Test mic", 0))
    monkeypatch.setattr(MainWindow, "_sessions", lambda self: None)
    monkeypatch.setattr("mss.mss", lambda: nullcontext(SimpleNamespace(monitors=[])))
    instance = MainWindow()
    yield instance
    instance.close()


def choose(monkeypatch, window, text, index=None):
    monkeypatch.setattr("qa_narrator.ui.ShortcutDialog", lambda parent: SimpleNamespace(
        shortcut=text, exec=lambda: bool(text)
    ))
    return window._choose_shortcut(index)


def test_legacy_settings_add_change_remove_and_reopen(window, monkeypatch, native):
    assert window._shortcuts() == ["Ctrl+F9"]
    assert choose(monkeypatch, window, "Middle Mouse") is None
    assert choose(monkeypatch, window, "Ctrl+F10") is None
    assert choose(monkeypatch, window, "Mouse Button 5", 1) is None
    assert window._shortcuts() == ["Ctrl+F9", "Mouse Button 5", "Ctrl+F10"]
    assert window._remove_shortcut(1) is None
    assert window.settings.value("additional_shortcuts", type=list) == ["Ctrl+F10"]
    assert "Ctrl+F9 or Ctrl+F10" in window.hint.text()
    assert "1/5" in window.additional_shortcuts_button.text()
    window.close()
    settings_path = window.settings.fileName()
    monkeypatch.setattr("qa_narrator.ui.QSettings", lambda *args: QSettings(
        settings_path, QSettings.IniFormat
    ))
    reopened = MainWindow()
    try:
        assert reopened._shortcuts() == ["Ctrl+F9", "Ctrl+F10"]
        assert len(native.registered) == 2
        assert reopened._remove_shortcut(1) is None
        assert reopened.settings.value("additional_shortcuts", type=list) == []
        assert reopened._remove_shortcut(0) is not None
        assert reopened.shortcut == "Ctrl+F9"
    finally:
        reopened.close()


def test_cancel_duplicate_and_conflict_preserve_all_bindings(window, monkeypatch, native):
    choose(monkeypatch, window, "Middle Mouse")
    for index in (None, 0, 1):
        assert choose(monkeypatch, window, None, index) is None
        assert window._shortcuts() == ["Ctrl+F9", "Middle Mouse"]
    assert "already configured" in choose(monkeypatch, window, "ctrl+f9")
    assert "already configured" in choose(monkeypatch, window, "Middle Mouse", 0)
    native.blocked.add(windows.parse_hotkey("Ctrl+F10")[1])
    assert "Cannot register" in choose(monkeypatch, window, "Ctrl+F10")
    assert window._shortcuts() == ["Ctrl+F9", "Middle Mouse"]
    assert window.settings.value("additional_shortcuts", type=list) == ["Middle Mouse"]
    assert len(window.hotkey.bindings) == 2 and window.start.isEnabled()


def test_standalone_shortcuts_register_save_and_reload(window, monkeypatch, native):
    assert choose(monkeypatch, window, "`") is None
    assert choose(monkeypatch, window, "Scroll Lock") is None
    assert set(native.registered.values()) == {(0x4002, 0x78), (0x4000, 0xC0), (0x4000, 0x91)}
    assert "already configured" in choose(monkeypatch, window, "scroll lock")
    assert "already configured" in choose(monkeypatch, window, "`")
    settings_path = window.settings.fileName()
    window.close()
    monkeypatch.setattr("qa_narrator.ui.QSettings", lambda *args: QSettings(
        settings_path, QSettings.IniFormat
    ))
    reopened = MainWindow()
    try:
        assert reopened._shortcuts() == ["Ctrl+F9", "`", "Scroll Lock"]
        assert len(native.registered) == 3
    finally:
        reopened.close()


def test_additional_dialog_limit_and_remove_enable_add(window, monkeypatch):
    dialog = AdditionalShortcutsDialog(window)
    dialog.show()
    for key in range(1, 6):
        monkeypatch.setattr("qa_narrator.ui.ShortcutDialog", lambda parent, k=key: SimpleNamespace(
            shortcut=f"Ctrl+F{k}", exec=lambda: True
        ))
        dialog.add.click()
    assert len(window.additional_shortcuts) == 5
    assert not dialog.add.isEnabled()
    assert all(change.isVisible() and remove.isVisible() for change, remove in dialog.rows)
    assert "up to 5" in window._choose_shortcut(None)
    dialog.rows[2][1].click()
    assert dialog.add.isEnabled() and len(window.additional_shortcuts) == 4
    assert "Ctrl+F3" not in window._shortcuts()
    # A duplicate error is visible inside the modal dialog.
    dialog.add.click()
    assert "already configured" in dialog.message.text()
    dialog.close()


def test_restore_failure_preserves_settings_and_disables_start(window, monkeypatch, native):
    native.blocked.add(windows.parse_hotkey("Ctrl+F9")[1])
    error = choose(monkeypatch, window, None)
    assert "could not be restored" in error
    assert window.hotkey is None and not window.start.isEnabled()
    assert window.settings.value("shortcut") == "Ctrl+F9"
    native.blocked.clear()
    assert window._apply()
    assert window.hotkey is not None and window.start.isEnabled()
