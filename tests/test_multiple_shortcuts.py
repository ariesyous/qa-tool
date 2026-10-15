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


def test_export_quality_defaults_persists_and_follows_embedding(window, monkeypatch):
    assert window.image_quality.currentData() == "compact"
    assert not window.image_quality.isEnabled()
    window.embed_images.setChecked(True)
    assert window.image_quality.isEnabled()
    window.image_quality.setCurrentIndex(window.image_quality.findData("raw"))
    assert window.settings.value("image_quality") == "raw"
    window.close()
    reopened = MainWindow()
    try:
        assert reopened.embed_images.isChecked()
        assert reopened.image_quality.currentData() == "raw"
        reopened.embed_images.setChecked(False)
        assert not reopened.image_quality.isEnabled()
        assert reopened.shrink.isEnabled()
    finally:
        reopened.close()


def test_ui_exports_selected_quality_and_shrinks_without_session(window, monkeypatch, tmp_path):
    from qa_narrator.storage import Session, atomic_json

    session = Session.create(tmp_path / "exports", 16000, "Test")
    atomic_json(session.folder / "transcription.json", {"segments": []})
    window.session = session
    window.embed_images.setChecked(True)
    monkeypatch.setattr(window, "_run", lambda work, done, *args, **kw: done(work()))
    monkeypatch.setattr(window, "_sessions", lambda *args: None)
    window._export()
    assert session.data["export_image_quality"] == "compact"
    assert "MB" in window.message.text()
    window.image_quality.setCurrentIndex(window.image_quality.findData("raw"))
    window._export()
    assert session.data["export_image_quality"] == "raw"
    source = session.folder / "feedback.md"
    original = source.read_bytes()
    window.session = None
    monkeypatch.setattr("qa_narrator.ui.QFileDialog.getOpenFileName", lambda *a: (str(source), ""))
    window._shrink_markdown()
    assert source.read_bytes() == original
    assert source.with_name("feedback.compact.md").exists()
    assert "Compact copy saved" in window.processing.text()


@pytest.mark.parametrize("outcome", ["success", "failure", "cancel"])
def test_shrink_worker_shows_live_progress_and_clears_activity(
    window, app, monkeypatch, tmp_path, outcome
):
    import base64
    import io
    import threading
    import time

    from PIL import Image

    from qa_narrator import compact

    png = io.BytesIO()
    Image.new("RGB", (12, 8)).save(png, format="PNG")
    source = tmp_path / "feedback.md"
    source.write_bytes(b"![shot](data:image/png;base64," + base64.b64encode(png.getvalue()) + b")")
    monkeypatch.setattr("qa_narrator.ui.QFileDialog.getOpenFileName", lambda *a: (str(source), ""))
    released = threading.Event()
    original = compact._smaller_image

    def slow_image(*args):
        if not released.wait(5):
            raise TimeoutError("Test did not release worker")
        if outcome == "failure":
            raise ValueError("Invalid image fixture")
        return original(*args)

    monkeypatch.setattr(compact, "_smaller_image", slow_image)
    try:
        window._shrink_markdown()
        deadline = time.monotonic() + 3
        while "Optimizing screenshot" not in window.processing.text() and time.monotonic() < deadline:
            app.processEvents()
            time.sleep(0.01)
        assert "Optimizing screenshot 1 of 1 — pass 1" in window.processing.text()
        assert window.busy and not window.activity.isHidden()
        assert not window.shrink.isEnabled()
        assert not window.cancel_shrink.isHidden() and window.cancel_shrink.isEnabled()
        if outcome == "cancel":
            window.cancel_shrink.click()
            assert window._cancel_event.is_set()
            assert not window.cancel_shrink.isEnabled()
            window._progress("Saving compact Markdown copy…")
            assert window.processing.text().startswith("Cancelling…")
    finally:
        released.set()
        deadline = time.monotonic() + 5
        while window.busy and time.monotonic() < deadline:
            app.processEvents()
            time.sleep(0.01)
    assert not window.busy and window.activity.isHidden()
    assert window.cancel_shrink.isHidden() and window._cancel_event is None
    assert window.shrink.isEnabled()
    if outcome == "failure":
        assert "Shrink failed" in window.processing.text()
        assert "Invalid image fixture" in window.message.text()
        assert not source.with_name("feedback.compact.md").exists()
    elif outcome == "cancel":
        assert "Shrinking cancelled" in window.processing.text()
        assert not source.with_name("feedback.compact.md").exists()
        assert not list(tmp_path.glob("*.tmp-*"))
        # A second run gets a fresh cancellation event and can complete normally.
        window._shrink_markdown()
        deadline = time.monotonic() + 5
        while window.busy and time.monotonic() < deadline:
            app.processEvents()
            time.sleep(0.01)
        assert not window.busy
        assert "Compact copy saved" in window.processing.text()
        assert source.with_name("feedback.compact.md").exists()
    else:
        assert "Compact copy saved" in window.processing.text()
        assert source.with_name("feedback.compact.md").exists()


def test_fast_worker_completion_follows_queued_progress(window, app, monkeypatch):
    import threading
    from concurrent.futures import Future

    def already_completed(operation):
        future = Future()

        def worker():
            window.signals.progress.emit("Saving Markdown…")
            future.set_result(operation())

        thread = threading.Thread(target=worker)
        thread.start()
        thread.join()
        return future

    monkeypatch.setattr(window.pool, "submit", already_completed)
    window._run(lambda: "Complete", window.processing.setText)
    assert window.cancel_shrink.isHidden()
    app.processEvents()
    assert window.processing.text() == "Complete"
    assert not window.busy and window.activity.isHidden()


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
        assert not native.registered and reopened.start.isEnabled()
        assert reopened._apply(arm=True) and len(native.registered) == 2
        reopened._disarm_shortcuts()
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
    assert window.hotkey is None and not native.registered and window.start.isEnabled()


def test_standalone_shortcuts_register_save_and_reload(app, window, monkeypatch, native):
    assert choose(monkeypatch, window, "`") is None
    assert choose(monkeypatch, window, "Scroll Lock") is None
    assert not native.registered  # nothing is reserved while idle
    armed = windows.ScreenshotShortcuts(app, lambda: None, window._shortcuts())
    assert set(native.registered.values()) == {(0x4002, 0x78), (0x4000, 0xC0), (0x4000, 0x91)}
    armed.close()
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
        assert not native.registered and reopened.start.isEnabled()
        assert reopened._apply(arm=True) and len(native.registered) == 3
        reopened._disarm_shortcuts()
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
    assert window.hotkey is None and window.start.isEnabled()


class FakeEngine:
    fail = False

    def __init__(self, root, device, name, notify):
        self.session = SimpleNamespace(folder=root, screenshots=lambda: [], data={})
        self.timeline = SimpleNamespace(state="recording", elapsed=lambda: 0.0)

    def start(self):
        if FakeEngine.fail:
            raise OSError("Microphone unavailable")
        return self

    def pause_resume(self):
        self.timeline.state = "paused" if self.timeline.state == "recording" else "recording"

    def check_error(self):
        return None

    def stop(self):
        return self.session


def settle(app, window):
    import time

    deadline = time.monotonic() + 5
    while window.busy and time.monotonic() < deadline:
        app.processEvents()
        time.sleep(0.01)
    app.processEvents()
    assert not window.busy


@pytest.fixture
def recorder(window, monkeypatch):
    FakeEngine.fail = False
    monkeypatch.setattr("qa_narrator.ui.CaptureEngine", FakeEngine)
    monkeypatch.setattr(window, "_process", lambda: None)
    monkeypatch.setattr(window, "_sessions", lambda *args: None)
    return window


def test_shortcuts_are_reserved_only_while_recording(app, recorder, native):
    window = recorder
    assert not native.registered and window.start.isEnabled()
    window._start()
    settle(app, window)
    assert window.engine is not None
    assert set(native.registered.values()) == {(0x4002, 0x78)}
    window._pause()  # paused presses are ignored, but the shortcut stays reserved
    assert window.engine.timeline.state == "paused" and native.registered
    window._stop()
    settle(app, window)
    assert window.engine is None and not native.registered
    assert window.start.isEnabled()


def test_failed_start_releases_shortcuts(app, recorder, native):
    FakeEngine.fail = True
    recorder._start()
    settle(app, recorder)
    assert recorder.engine is None and not native.registered
    assert "Microphone unavailable" in recorder.message.text()
    assert recorder.start.isEnabled()


def test_conflict_at_start_keeps_microphone_closed(app, recorder, native, monkeypatch):
    opened = []
    monkeypatch.setattr(
        "qa_narrator.ui.CaptureEngine", lambda *args: opened.append(args) or FakeEngine(*args)
    )
    native.blocked.add(windows.parse_hotkey("Ctrl+F9")[1])  # another app claimed it while idle
    recorder._start()
    settle(app, recorder)
    assert not opened and recorder.engine is None and not native.registered
    assert "Cannot register" in recorder.message.text() and not recorder.start.isEnabled()
    native.blocked.clear()
    assert recorder._apply()
    assert recorder.start.isEnabled() and not native.registered


def test_remove_is_saved_even_if_another_app_took_a_remaining_key(window, monkeypatch, native):
    assert choose(monkeypatch, window, "Ctrl+F10") is None
    native.blocked.add(windows.parse_hotkey("Ctrl+F9")[1])  # claimed by another app while idle
    # Removing can't create a conflict, so it is saved; the remaining conflict is reported.
    assert "Cannot register" in window._remove_shortcut(1)
    assert window._shortcuts() == ["Ctrl+F9"] and not window.start.isEnabled()
    assert window.settings.value("additional_shortcuts", type=list) == []


def test_apply_button_validates_then_releases(window, native):
    from PySide6.QtWidgets import QPushButton

    apply = next(b for b in window.findChildren(QPushButton) if b.text() == "Apply Settings")
    apply.click()
    assert window.hotkey is None and not native.registered and window.start.isEnabled()
