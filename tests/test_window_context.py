import ctypes
import json
import sys
import threading
from ctypes import wintypes
from types import SimpleNamespace

import pytest

from qa_narrator import windows
from qa_narrator.capture import CaptureEngine
from qa_narrator.export import render, screenshot_context
from qa_narrator.storage import Session
from qa_narrator.timeline import Timeline


@pytest.mark.parametrize("failure", [None, "title", "open", "query", "query_error"])
def test_native_context_omits_unavailable_fields_and_closes_process(monkeypatch, failure):
    closed = []

    def title(hwnd, buffer, size):
        assert hwnd == 42
        if failure == "title":
            raise OSError("Window closed")
        buffer.value = "Settings — MyApp"
        return len(buffer.value)

    def pid(hwnd, output):
        ctypes.cast(output, ctypes.POINTER(wintypes.DWORD)).contents.value = 123
        return 1

    def open_process(access, inherit, process_id):
        assert (access, inherit, process_id) == (0x1000, False, 123)
        return None if failure == "open" else 99

    def query(process, flags, buffer, size):
        assert process == 99 and flags == 0
        if failure == "query_error":
            raise OSError("Process exited")
        buffer.value = r"C:\Users\private-user\Apps\myapp.exe"
        return failure != "query"

    monkeypatch.setattr(windows, "user32", SimpleNamespace(
        GetWindowTextW=title, GetWindowThreadProcessId=pid,
    ), raising=False)
    monkeypatch.setattr(windows, "kernel32", SimpleNamespace(
        OpenProcess=open_process, QueryFullProcessImageNameW=query, CloseHandle=closed.append,
    ), raising=False)
    expected = {}
    if failure != "title":
        expected["title"] = "Settings — MyApp"
    if failure not in ("open", "query", "query_error"):
        expected["app"] = "myapp.exe"
    assert windows.window_context(42) == expected
    assert closed == ([] if failure == "open" else [99])


@pytest.mark.parametrize("enabled", [False, True])
@pytest.mark.parametrize("context", [{}, {"title": "Settings", "app": "myapp.exe"}])
def test_capture_context_is_opt_in_and_survives_sidecar_recovery(
    tmp_path, monkeypatch, enabled, context
):
    engine = CaptureEngine.__new__(CaptureEngine)
    engine.session = Session.create(tmp_path, 16000, "Fixture")
    engine.session.update(status="stopped")
    engine.timeline = Timeline()
    engine.accepting = True
    engine.metadata_pending = threading.Event()
    engine.screen_pending = threading.BoundedSemaphore(1)
    engine.screen_pending.acquire()
    notices = []
    engine.notify = lambda *args: notices.append(args)
    calls = []

    class Screen:
        monitors = [{"left": 0, "top": 0, "width": 8, "height": 8}] * 2

        def __enter__(self):
            return self

        def __exit__(self, *args):
            pass

        def grab(self, rect):
            return SimpleNamespace(size=(8, 8), rgb=b"\xff" * (8 * 8 * 3))

    def read_context(hwnd):
        calls.append(hwnd)
        return context

    monkeypatch.setitem(sys.modules, "mss", SimpleNamespace(mss=Screen))
    monkeypatch.setattr(windows, "foreground", lambda: (42, 0))
    monkeypatch.setattr(windows, "window_context", read_context)
    target = windows.capture_target("monitor", 1, enabled)
    engine._screenshot(target, engine.timeline.origin)
    assert calls == ([42] if enabled else [])
    assert engine.screen_pending.acquire(blocking=False)
    assert len(engine.session.screenshots()) == 1, notices
    assert [kind for kind, _ in notices] == ["screenshot"]
    event = engine.session.screenshots()[0]
    expected = context if enabled and context else None
    assert event.get("window_context") == expected
    sidecar = engine.session.folder / "screenshots/001.json"
    assert json.loads(sidecar.read_text(encoding="utf-8")).get("window_context") == expected
    # Simulate interruption after the sidecar/PNG commit but before the session index.
    engine.session.update(events=[])
    reopened = Session.load(engine.session.folder)
    reopened.recover()
    assert reopened.screenshots()[0].get("window_context") == expected
    report = render(reopened, {"segments": []})
    assert ("Focused window: myapp\\.exe — Settings" in report) == bool(expected)


@pytest.mark.parametrize("mode,fallback,focused", [
    ("window", None, False), ("window", "Unavailable", True),
    ("monitor", None, True), ("desktop", None, True),
])
def test_export_escapes_titles_and_labels_monitor_context(mode, fallback, focused):
    event = {
        "mode": mode, "fallback": fallback,
        "window_context": {"app": "my_app.exe", "title": "A ] **title**\n<script>& `code`"},
    }
    label = screenshot_context(event)
    assert ("Focused window: " in label) == focused
    assert r"my\_app\.exe" in label
    assert r"A \] \*\*title\*\* &lt;script&gt;&amp; \`code\`" in label
    assert "\n" not in label and "<script>" not in label
    assert screenshot_context({}) == ""
    assert screenshot_context({"window_context": {"title": " \n\t "}}) == ""


def test_old_sessions_keep_original_screenshot_heading(tmp_path):
    from PIL import Image

    session = Session.create(tmp_path, 16000, "Fixture")
    Image.new("RGB", (8, 8), "white").save(session.folder / "screenshots/001.png")
    session.event({"kind": "screenshot", "number": 1, "path": "screenshots/001.png", "t": 0})
    report = render(session, {"segments": []})
    assert "**[00:00 — Screenshot]**" in report
    assert "Focused window:" not in report
