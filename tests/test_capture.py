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
    engine.input_latency = 0.0
    engine.last_audio_end = None
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


def callback_engine(tmp_path, monkeypatch):
    import sounddevice as sd

    engine = bare_engine(tmp_path)
    clock = [100_000_000_000]
    engine.timeline = Timeline(lambda: clock[0])
    engine.stream_anchor, engine.clock_anchor = 10.0, clock[0]
    engine.sd = sd
    engine.input_latency = 0.2
    engine.use_adc = None
    engine.sample_anchor = None
    engine.captured_frames = 0
    engine.timing_fallback_reported = False
    monkeypatch.setattr("qa_narrator.capture.time.perf_counter_ns", lambda: clock[0])
    return engine, clock, sd


@pytest.mark.parametrize("adc", [True, False])
def test_overflow_continues_with_silence_for_gap_and_persists_warning(tmp_path, monkeypatch, adc):
    engine, clock, sd = callback_engine(tmp_path, monkeypatch)
    clock[0] += 200_000_000
    engine._callback(b"\1\2" * 100, 100, SimpleNamespace(
        inputBufferAdcTime=10.0 if adc else 0, currentTime=10.2
    ), sd.CallbackFlags())
    clock[0] += 400_000_000
    status = sd.CallbackFlags()
    status.input_overflow = True
    engine._callback(b"\3\4" * 100, 100, SimpleNamespace(
        inputBufferAdcTime=10.4 if adc else 0, currentTime=10.6
    ), status)
    assert engine.accepting and engine.errors.empty() and status.input_overflow
    # The next buffer remains contiguous despite a late callback.
    clock[0] += 150_000_000
    engine._callback(b"\5\6" * 100, 100, SimpleNamespace(
        inputBufferAdcTime=10.5 if adc else 0, currentTime=10.75
    ), sd.CallbackFlags())
    engine.audio_queue.put(None)
    engine._write_audio()
    assert (engine.session.folder / "audio.pcm").read_bytes() == (
        b"\1\2" * 100 + b"\0\0" * 300 + b"\3\4" * 100 + b"\5\6" * 100
    )
    warnings = [e for e in Session.load(engine.session.folder).data["events"]
                if e.get("message", "").startswith("Microphone input overflow")]
    assert len(warnings) == 1
    assert warnings[0]["audio_gap_seconds"] == pytest.approx(0.3)
    assert warnings[0]["timing_estimated"] is not adc


@pytest.mark.parametrize("latency,expected", [(0.2, 0), (0.05, 100), (0, 100)])
def test_fallback_compensates_input_latency_without_counting_buffer_twice(
    tmp_path, monkeypatch, latency, expected
):
    engine, clock, sd = callback_engine(tmp_path, monkeypatch)
    engine.input_latency = latency
    clock[0] += 200_000_000
    engine._callback(b"\1\2" * 100, 100, SimpleNamespace(
        inputBufferAdcTime=0, currentTime=0
    ), sd.CallbackFlags())
    assert engine.audio_queue.get_nowait()[0] == expected


def test_overflow_with_other_status_still_aborts_and_disconnect_remains_fatal(tmp_path, monkeypatch):
    engine, clock, sd = callback_engine(tmp_path, monkeypatch)
    status = sd.CallbackFlags()
    status.input_overflow = status.input_underflow = True
    with pytest.raises(sd.CallbackAbort):
        engine._callback(b"\0\0" * 100, 100, SimpleNamespace(), status)
    assert not engine.accepting and "Microphone stream error" in engine.check_error()
    engine.accepting = True
    engine.stream = SimpleNamespace(active=False)
    assert "Microphone stopped responding" in engine.check_error()


def test_overflow_does_not_hide_a_full_audio_writer_queue(tmp_path, monkeypatch):
    engine, clock, sd = callback_engine(tmp_path, monkeypatch)
    engine.audio_queue = queue.Queue(maxsize=1)
    engine.audio_queue.put((0, b"\0\0"))
    clock[0] += 200_000_000
    status = sd.CallbackFlags()
    status.input_overflow = True
    with pytest.raises(sd.CallbackAbort):
        engine._callback(b"\1\2" * 100, 100, SimpleNamespace(
            inputBufferAdcTime=10.0, currentTime=10.2
        ), status)
    assert not engine.accepting and "could not keep up" in engine.check_error()


def test_overflow_during_pause_does_not_pad_paused_time(tmp_path, monkeypatch):
    engine, clock, sd = callback_engine(tmp_path, monkeypatch)
    engine.input_latency = 0.1
    clock[0] += 100_000_000
    timing = SimpleNamespace(inputBufferAdcTime=0, currentTime=0)
    engine._callback(b"\1\2" * 100, 100, timing, sd.CallbackFlags())
    engine.pause_resume()  # Pause at 0.1 seconds.
    clock[0] += 1_000_000_000
    status = sd.CallbackFlags()
    status.input_overflow = True
    engine._callback(b"\3\4" * 100, 100, timing, status)
    engine.pause_resume()  # Resume at 1.1 seconds.
    clock[0] += 100_000_000
    engine._callback(b"\5\6" * 100, 100, timing, sd.CallbackFlags())
    engine.audio_queue.put(None)
    engine._write_audio()
    assert (engine.session.folder / "audio.pcm").read_bytes() == b"\1\2" * 100 + b"\5\6" * 100
    overflow_event = next(e for e in engine.session.data["events"] if "audio_gap_seconds" in e)
    assert overflow_event["audio_gap_seconds"] == 0


def test_repeated_overflow_never_rewinds_the_sample_clock(tmp_path, monkeypatch):
    engine, clock, sd = callback_engine(tmp_path, monkeypatch)
    clock[0] += 200_000_000
    timing = SimpleNamespace(inputBufferAdcTime=0, currentTime=0)
    status = sd.CallbackFlags()
    status.input_overflow = True
    for _ in range(3):
        engine._callback(b"\1\2" * 100, 100, timing, status)
    assert [engine.audio_queue.get_nowait()[0] for _ in range(3)] == [0, 100, 200]
    assert engine.accepting and engine.errors.empty()


@pytest.mark.parametrize("state", ["paused", "stopped"])
@pytest.mark.parametrize("during_setup", [True, False])
def test_queued_screenshot_reports_skip_and_releases_slot(
    tmp_path, monkeypatch, state, during_setup
):
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
            engine.timeline.transition(state)
            return self

        def __exit__(self, *args):
            pass

        def grab(self, rect):
            pytest.fail("Skipped screenshots must not grab pixels")

    monkeypatch.setitem(sys.modules, "mss", SimpleNamespace(mss=Screen))
    monkeypatch.setattr("qa_narrator.windows.foreground", lambda: (1, 0))
    if not during_setup:
        engine.timeline.transition(state)
    engine._screenshot({"hwnd": 1, "mode": "monitor", "monitor": 1}, engine.timeline.origin)
    assert notices == [("warning", f"Screenshot skipped: recording {state}.")]
    assert engine.screen_pending.acquire(blocking=False)
    assert engine.accepting and not engine.session.screenshots()


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
