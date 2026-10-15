"""Platform-free tests for capture failure paths and sample placement."""

import queue
import threading
from concurrent.futures import ThreadPoolExecutor
from types import SimpleNamespace

import pytest

from qa_narrator.capture import CaptureEngine
from qa_narrator.storage import Session
from qa_narrator.timeline import Timeline


def bare_engine(tmp_path):
    engine = CaptureEngine.__new__(CaptureEngine)
    engine.session = Session.create(tmp_path, 1000, "Mock microphone")
    engine.rate = 1000
    engine.audio_queue = queue.Queue()
    engine.errors = queue.SimpleQueue()
    engine.warnings = queue.SimpleQueue()
    engine.writer_error = None
    engine.metadata_pending = threading.Event()
    engine.metadata_error = None
    engine.notify = lambda *_: None
    engine.accepting = True
    return engine


def test_pcm_writer_pads_gaps_trims_only_overlap_and_flushes(tmp_path):
    engine = bare_engine(tmp_path)
    engine.audio_queue.put((2, b"\x01\x02" * 3))
    engine.audio_queue.put((4, b"\x03\x04" * 3))
    engine.audio_queue.put(None)
    engine._write_audio()
    assert (
        engine.session.folder / "audio.pcm"
    ).read_bytes() == b"\0" * 4 + b"\x01\x02" * 3 + b"\x03\x04" * 2
    assert engine.writer_error is None


def test_disk_write_failure_stops_accepting_audio(tmp_path, monkeypatch):
    engine = bare_engine(tmp_path)

    def fail(*args, **kwargs):
        raise OSError("Disk is full")

    monkeypatch.setattr("pathlib.Path.open", fail)
    engine._write_audio()
    assert not engine.accepting
    assert "Disk is full" in engine.errors.get_nowait()


def test_device_stop_failure_still_closes_and_saves_audio(tmp_path):
    engine = bare_engine(tmp_path)
    engine.timeline = Timeline()
    (engine.session.folder / "audio.pcm").write_bytes(b"\0\0" * 100)
    closed = []

    def fail():
        raise OSError("Device disconnected")

    engine.stream = SimpleNamespace(stop=fail, close=lambda: closed.append(True))
    engine.screens = ThreadPoolExecutor(max_workers=1)
    engine.writer = threading.Thread(target=lambda: None)
    with pytest.raises(OSError, match="Device disconnected"):
        engine.stop()
    assert closed and not engine.accepting
    assert (engine.session.folder / "audio.wav").exists()


def test_missing_adc_timing_uses_contiguous_samples_despite_callback_jitter(tmp_path, monkeypatch):
    engine = bare_engine(tmp_path)
    clock = [100_000_000_000]
    engine.timeline = Timeline(lambda: clock[0])
    engine.timeline.origin -= 1_000_000_000
    engine.timeline.intervals[0][0] = engine.timeline.origin
    engine.use_adc = None
    engine.sample_anchor = None
    engine.captured_frames = 0
    engine.timing_fallback_reported = False
    notices = []
    engine.notify = lambda *args: notices.append(args)
    monkeypatch.setattr("qa_narrator.capture.time.perf_counter_ns", lambda: clock[0])
    timing = SimpleNamespace(inputBufferAdcTime=0, currentTime=0)
    engine._callback(b"\1\2" * 100, 100, timing, False)
    clock[0] += 150_000_000  # 50 ms scheduling jitter must not cut or pad spoken samples.
    engine._callback(b"\3\4" * 100, 100, timing, False)
    first, second = engine.audio_queue.get_nowait(), engine.audio_queue.get_nowait()
    assert second[0] == first[0] + 100
    assert len(notices) == 1


def test_no_screenshots_outside_active_recording(tmp_path):
    engine = bare_engine(tmp_path)
    engine.timeline = Timeline()
    engine.timeline.transition("paused")
    engine.capture({})  # No executor needed: must return before accessing platform state.
    engine.timeline.transition("stopped")
    engine.capture({})
    assert not engine.session.screenshots()


def test_timing_warning_persists_without_a_ui(tmp_path):
    engine = bare_engine(tmp_path)
    engine.warnings.put({"kind": "warning", "t": 0, "message": "Estimated microphone clock"})
    engine.audio_queue.put((0, b"\0\0" * 100))
    engine.audio_queue.put(None)
    engine._write_audio()
    assert (
        Session.load(engine.session.folder).data["events"][0]["message"]
        == "Estimated microphone clock"
    )


def test_metadata_failure_keeps_audio_and_retries_without_duplicate_warning(tmp_path, monkeypatch):
    engine = bare_engine(tmp_path)
    engine.warnings.put({"kind": "warning", "t": 0, "message": "Estimated clock"})
    for dest in (0, 100):
        engine.audio_queue.put((dest, b"\1\2" * 100))
    engine.audio_queue.put(None)
    save = engine.session.save
    notices = []
    engine.notify = lambda *args: notices.append(args)

    def fail():
        raise PermissionError("session.json locked")

    monkeypatch.setattr(engine.session, "save", fail)
    clock = iter(range(0, 100, 2))
    monkeypatch.setattr("qa_narrator.capture.time.monotonic", lambda: next(clock))
    engine._write_audio()
    engine._persist_metadata()
    assert engine.accepting and engine.writer_error is None and engine.errors.empty()
    assert (engine.session.folder / "audio.pcm").read_bytes() == b"\1\2" * 200
    assert len(notices) == 1 and "metadata" in notices[0][1]
    assert engine.metadata_pending.is_set()
    monkeypatch.setattr(engine.session, "save", save)
    engine._persist_metadata()
    assert not engine.metadata_pending.is_set() and engine.metadata_error is None
    assert [e["message"] for e in Session.load(engine.session.folder).data["events"]] == [
        "Estimated clock"
    ]


def test_pause_metadata_is_deferred_and_failed_save_does_not_stop_recording(tmp_path, monkeypatch):
    engine = bare_engine(tmp_path)
    engine.timeline = Timeline()
    save = engine.session.save

    def fail():
        raise PermissionError("session.json locked")

    monkeypatch.setattr(engine.session, "save", fail)
    engine.pause_resume()
    assert engine.timeline.state == engine.session.data["status"] == "paused"
    engine._persist_metadata()
    engine.pause_resume()
    assert engine.accepting and engine.timeline.state == "recording"
    monkeypatch.setattr(engine.session, "save", save)
    engine._persist_metadata()
    loaded = Session.load(engine.session.folder)
    assert loaded.data["status"] == "recording"
    assert [e["kind"] for e in loaded.data["events"]] == ["paused", "recording"]


def test_paused_writer_retries_metadata_without_new_audio(tmp_path):
    engine = bare_engine(tmp_path)
    engine.timeline = Timeline()
    engine.pause_resume()
    saved = threading.Event()
    save = engine.session.save

    def tracked_save():
        save()
        saved.set()

    engine.session.save = tracked_save
    writer = threading.Thread(target=engine._write_audio)
    writer.start()
    try:
        assert saved.wait(3)
        assert Session.load(engine.session.folder).data["status"] == "paused"
    finally:
        engine.audio_queue.put(None)
        writer.join(timeout=3)
    assert not writer.is_alive()


def test_stop_finalizes_wav_even_when_metadata_remains_locked(tmp_path, monkeypatch):
    engine = bare_engine(tmp_path)
    engine.timeline = Timeline()
    (engine.session.folder / "audio.pcm").write_bytes(b"\1\2" * 100)
    engine.stream = SimpleNamespace(stop=lambda: None, close=lambda: None)
    engine.screens = ThreadPoolExecutor(max_workers=1)
    engine.writer = threading.Thread(target=lambda: None)

    def fail():
        raise PermissionError("session.json locked")

    monkeypatch.setattr(engine.session, "save", fail)
    with pytest.raises(OSError, match="Audio saved, but session metadata"):
        engine.stop()
    assert (engine.session.folder / "audio.wav").exists()
    assert engine.writer_error is None and not engine.accepting


def test_screenshot_failure_does_not_interrupt_audio(tmp_path, monkeypatch):
    import sys

    engine = bare_engine(tmp_path)
    engine.timeline = Timeline()
    engine.screen_pending = threading.BoundedSemaphore(1)
    engine.screen_pending.acquire()
    notices = []
    engine.notify = lambda *args: notices.append(args)

    def fail():
        raise OSError("Display unavailable")

    monkeypatch.setitem(sys.modules, "mss", SimpleNamespace(mss=fail))
    engine._screenshot({}, engine.timeline.origin)
    assert engine.accepting
    assert engine.screen_pending.acquire(blocking=False)
    assert "Display unavailable" in notices[0][1]
    assert not engine.session.screenshots()


def test_queued_capture_rejects_a_changed_foreground_window(tmp_path, monkeypatch):
    import sys

    engine = bare_engine(tmp_path)
    engine.timeline = Timeline()
    engine.screen_pending = threading.BoundedSemaphore(1)
    engine.screen_pending.acquire()
    notices = []
    engine.notify = lambda *args: notices.append(args)

    class Screen:
        monitors = [{"left": 0, "top": 0, "width": 100, "height": 100}] * 2

        def __enter__(self):
            return self

        def __exit__(self, *args):
            pass

        def grab(self, _):
            pytest.fail("Must not grab pixels after focus changes")

    monkeypatch.setitem(sys.modules, "mss", SimpleNamespace(mss=Screen))
    monkeypatch.setattr("qa_narrator.windows.foreground", lambda: (999, 0))
    engine._screenshot({"hwnd": 1, "mode": "monitor", "monitor": 1}, engine.timeline.origin)
    assert "Active window changed" in notices[0][1]
    assert engine.accepting and not engine.session.screenshots()
