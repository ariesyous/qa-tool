"""Exercise the hook message loop without injecting system-wide mouse input."""

import ctypes
import os
import queue
import threading
from types import SimpleNamespace

import pytest

from qa_narrator import windows


@pytest.fixture
def native_mouse(monkeypatch):
    messages = queue.Queue()
    installed, removed = [], []
    state = SimpleNamespace(fail=False)

    def install(kind, procedure, module, thread_id):
        installed.append(threading.get_ident())
        return 0 if state.fail else 123

    def get_message(*args):
        item = messages.get(timeout=5)
        if item is None:
            return 0
        message, data, processed = item
        try:
            windows._mouse_worker.procedure(0, message, ctypes.addressof(data))
        finally:
            processed.set()
        return 1

    def post(*args):
        messages.put(None)
        return True

    monkeypatch.setattr(windows, "MouseProc", lambda function: function, raising=False)
    monkeypatch.setattr(windows, "user32", SimpleNamespace(
        SetWindowsHookExW=install,
        UnhookWindowsHookEx=lambda handle: removed.append((handle, threading.get_ident())),
        PeekMessageW=lambda *args: 0,
        GetMessageW=get_message,
        PostThreadMessageW=post,
        GetAsyncKeyState=lambda key: 0,
        CallNextHookEx=lambda *args: 42,
    ), raising=False)
    monkeypatch.setattr(windows, "kernel32", SimpleNamespace(
        GetCurrentThreadId=threading.get_ident,
        GetModuleHandleW=lambda _: 1,
    ), raising=False)
    assert windows._mouse_worker is None
    yield SimpleNamespace(messages=messages, installed=installed, removed=removed, state=state)
    if windows._mouse_worker is not None:
        windows._mouse_worker.close()
        windows._mouse_worker = None


def test_single_hook_dispatches_off_gui_thread_and_lasts_until_last_binding_closes(native_mouse):
    calls = []
    owner = threading.get_ident()
    first = windows.MouseHook(0, "MIDDLE MOUSE", lambda: calls.append(("middle", threading.get_ident())))
    second = windows.MouseHook(0, "MOUSE BUTTON 5", lambda: calls.append(("side", threading.get_ident())))
    worker = first.worker
    try:
        assert worker is second.worker
        assert len(native_mouse.installed) == 1 and native_mouse.installed[0] != owner
        event = windows.MouseEvent()
        processed = threading.Event()
        native_mouse.messages.put((0x207, event, processed))
        # Waiting blocks the owner; the independent message loop must still dispatch.
        assert processed.wait(2)
        assert calls == [("middle", native_mouse.installed[0])]
        first.close()
        first.close()  # Removing a subscription twice must leave others working.
        assert worker.thread.is_alive() and not native_mouse.removed
        event.mouseData = 2 << 16
        processed.clear()
        native_mouse.messages.put((0x20B, event, processed))
        assert processed.wait(2)
        assert calls[-1] == ("side", native_mouse.installed[0])
        assert second.procedure(-1, 0x207, ctypes.addressof(event)) == 42
    finally:
        first.close()
        second.close()
    assert not worker.thread.is_alive() and windows._mouse_worker is None
    assert native_mouse.removed == [(123, native_mouse.installed[0])]


def test_failed_native_registration_surfaces_and_can_be_retried(native_mouse):
    native_mouse.state.fail = True
    with pytest.raises(OSError, match="Cannot register mouse shortcut"):
        windows.MouseHook(0, "Middle Mouse", lambda: None)
    assert windows._mouse_worker is None and not native_mouse.removed
    native_mouse.state.fail = False
    binding = windows.MouseHook(0, "Middle Mouse", lambda: None)
    worker = binding.worker
    binding.close()
    assert not worker.thread.is_alive() and windows._mouse_worker is None


def test_hook_thread_queues_qt_dispatch_and_closed_bindings_ignore_queued_events(native_mouse):
    os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
    from PySide6.QtWidgets import QApplication

    app = QApplication.instance() or QApplication([])
    calls = []
    binding = windows.install_hotkey(app, lambda: calls.append(threading.get_ident()), "Middle Mouse")
    try:
        processed = threading.Event()
        event = windows.MouseEvent()
        native_mouse.messages.put((0x207, event, processed))
        assert processed.wait(2) and not calls
        app.processEvents()
        assert calls == [threading.get_ident()]
        processed.clear()
        native_mouse.messages.put((0x207, event, processed))
        assert processed.wait(2)
        binding.close()
        app.processEvents()
        assert len(calls) == 1
    finally:
        binding.close()
