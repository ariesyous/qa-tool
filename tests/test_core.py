import json
import threading
import wave
from types import SimpleNamespace

import pytest

from qa_narrator.export import export_markdown, render, text_units
from qa_narrator.storage import Session, atomic_json, list_sessions
from qa_narrator.timeline import Timeline
from qa_narrator.transcription import process_session


class Clock:
    def __init__(self):
        self.now = 100_000_000_000

    def __call__(self):
        return self.now

    def advance(self, seconds):
        self.now += int(seconds * 1e9)


def make_session(tmp_path):
    session = Session.create(tmp_path, 16000, "Test microphone")
    session.update(duration=50, status="stopped")
    return session


def shot(session, number, when):
    from PIL import Image

    path = f"screenshots/{number:03d}.png"
    Image.new("RGB", (8, 8), "white").save(session.folder / path)
    session.event({"kind": "screenshot", "number": number, "path": path, "t": when})


def transcript():
    words = [
        (10, " I"),
        (12, " think"),
        (16, " this"),
        (19, " Save"),
        (22, " button"),
        (26, " should"),
        (30, " say"),
        (36, " Create."),
    ]
    return {
        "segments": [
            {
                "start": 10,
                "end": 40,
                "text": "".join(word for _, word in words),
                "words": [
                    {"word": word, "start": start, "end": start + 1} for start, word in words
                ],
            }
        ]
    }


def test_pause_resume_timeline_and_buffer_boundaries():
    clock = Clock()
    timeline = Timeline(clock)
    clock.advance(10)
    assert timeline.transition("paused")["t"] == 10
    clock.advance(50)
    assert timeline.elapsed() == 10
    timeline.transition("recording")
    clock.advance(5)
    assert timeline.transition("stopped")["t"] == 15
    assert timeline.slices(timeline.origin + 9_500_000_000, 1000, 1000) == [(9500, 0, 500)]
    assert timeline.slices(timeline.origin + 59_500_000_000, 1000, 1000) == [(10000, 500, 1000)]
    clock.advance(20)
    assert timeline.elapsed() == 15
    with pytest.raises(ValueError):
        timeline.transition("recording")


def test_multiple_pause_intervals_in_one_audio_buffer():
    clock = Clock()
    timeline = Timeline(clock)
    clock.advance(1)
    timeline.transition("paused")
    clock.advance(1)
    timeline.transition("recording")
    clock.advance(1)
    timeline.transition("stopped")
    assert timeline.slices(timeline.origin, 4000, 1000) == [(0, 0, 1000), (1000, 2000, 3000)]


def test_interleave_five_screenshots_and_keep_exact_word_order(tmp_path):
    session = make_session(tmp_path)
    for number, when in enumerate((0, 17, 21, 25, 45), 1):
        shot(session, number, when)
    result = render(session, transcript())
    expected = [
        "001.png",
        "I think this",
        "002.png",
        "Save",
        "003.png",
        "button",
        "004.png",
        "should say Create.",
        "005.png",
    ]
    indices = [result.index(value) for value in expected]
    assert indices == sorted(indices)
    assert (
        "".join(value for _, value, _ in text_units(transcript()))
        == transcript()["segments"][0]["text"]
    )
    for number in range(1, 6):
        assert f"(screenshots/{number:03d}.png)" in result


def test_equal_timestamp_screenshots_have_stable_event_order(tmp_path):
    session = make_session(tmp_path)
    shot(session, 1, 19)
    shot(session, 2, 19)
    text = render(session, transcript())
    assert text.index("001.png") < text.index("002.png") < text.index("Save")


@pytest.mark.parametrize(
    "words",
    [
        None,
        [],
        [{"word": "different text", "start": 0, "end": 1}],
        [{"word": "  Original,\ttext!\n", "start": 9, "end": 2}],
    ],
)
def test_fallback_never_loses_or_substitutes_text(words):
    data = {"segments": [{"text": "  Original,\ttext!\n", "start": 1, "end": 3, "words": words}]}
    units = list(text_units(data))
    assert "".join(unit[1] for unit in units) == data["segments"][0]["text"]
    assert all(unit[2] == "estimated" for unit in units)
    assert [u[0] for u in units] == sorted(u[0] for u in units)


def test_out_of_order_screenshot_completion_sorted_by_capture_time(tmp_path):
    session = make_session(tmp_path)
    shot(session, 1, 35)
    shot(session, 2, 17)
    result = render(session, transcript())
    assert result.index("002.png") < result.index("001.png")


def test_atomic_persistence_and_unique_session_folders(tmp_path):
    session = make_session(tmp_path)
    other = make_session(tmp_path)
    assert session.folder != other.folder
    workers = [
        threading.Thread(target=session.event, args=({"kind": "test", "t": i},)) for i in range(20)
    ]
    for worker in workers:
        worker.start()
    for worker in workers:
        worker.join()
    loaded = Session.load(session.folder)
    assert [e["sequence"] for e in loaded.data["events"]] == list(range(20))
    assert len(list_sessions(tmp_path)) == 2
    assert not list(session.folder.glob("*.tmp-*"))


def test_recovery_of_pcm_partial_sample_orphan_png_and_processing(tmp_path):
    session = make_session(tmp_path)
    session.update(status="paused", transcription_status="processing")
    (session.folder / "audio.pcm").write_bytes(b"\x01\x02" * 16000 + b"\xff")
    shot(session, 1, 0.5)
    event = session.screenshots()[0]
    atomic_json(session.folder / "screenshots/001.json", event)
    session.data["events"].clear()
    session.save()
    recovered = Session.load(session.folder)
    recovered.recover()
    assert recovered.data["status"] == "recovered"
    assert recovered.data["transcription_status"] == "interrupted"
    assert len(recovered.screenshots()) == 1
    with wave.open(str(session.folder / "audio.wav")) as audio:
        assert audio.getnframes() == 16000
        assert audio.readframes(1) == b"\x01\x02"
    recovered.recover()
    assert len(recovered.screenshots()) == 1


def test_markdown_protects_manual_changes_and_can_regenerate(tmp_path):
    session = make_session(tmp_path)
    atomic_json(session.folder / "transcription.json", transcript())
    path = export_markdown(session)
    original = path.read_text(encoding="utf-8")
    assert export_markdown(session) == path
    path.write_text(original + "\nMy manual notes", encoding="utf-8")
    with pytest.raises(FileExistsError):
        export_markdown(session)
    assert "My manual notes" in path.read_text(encoding="utf-8")
    export_markdown(session, overwrite=True)
    assert path.read_text(encoding="utf-8") == original


@pytest.mark.parametrize(
    "path",
    [
        "../outside.png",
        "C:/secret.png",
        "screenshots/../../secret.png",
        "screenshots/missing.png",
        "screenshots/001.png",
    ],
)
def test_export_rejects_missing_or_unsafe_paths(tmp_path, path):
    session = make_session(tmp_path)
    session.event({"kind": "screenshot", "path": path, "number": 1, "t": 0})
    with pytest.raises(ValueError):
        render(session, transcript())


def test_transcription_failure_in_lazy_generator_then_retry(tmp_path):
    session = make_session(tmp_path)
    (session.folder / "audio.wav").write_bytes(b"test audio retained")

    class Model:
        fail = True

        def transcribe(self, path, **kwargs):
            assert kwargs["word_timestamps"]

            def segments():
                yield SimpleNamespace(
                    start=0,
                    end=1,
                    text=" Hello.",
                    words=[SimpleNamespace(start=0, end=1, word=" Hello.", probability=0.9)],
                )
                if self.fail:
                    raise RuntimeError("Inference failed")

            return segments(), SimpleNamespace(language="en")

    model = Model()
    with pytest.raises(RuntimeError, match="Inference failed"):
        process_session(session, factory=lambda _: model)
    assert session.data["transcription_status"] == "failed"
    assert not (session.folder / "transcription.json").exists()
    assert (session.folder / "audio.wav").read_bytes() == b"test audio retained"
    model.fail = False
    result = process_session(session, factory=lambda _: model)
    assert "Hello." in result.read_text(encoding="utf-8")
    assert session.data["transcription_status"] == "complete"
    assert session.data["export_status"] == "complete"


def test_failed_retry_keeps_previous_transcript(tmp_path):
    session = make_session(tmp_path)
    atomic_json(session.folder / "transcription.json", transcript())

    def fail(_):
        raise OSError("No model")

    with pytest.raises(OSError):
        process_session(session, factory=fail)
    assert json.loads((session.folder / "transcription.json").read_text()) == transcript()


def test_hotkey_validation():
    from qa_narrator.windows import parse_hotkey

    assert parse_hotkey("Ctrl+Alt+F9") == (0x4003, 0x78)
    for invalid in ("F9", "Ctrl+F12", "Ctrl+Ctrl+F9", "Shift+A", "Ctrl+Banana"):
        with pytest.raises(ValueError):
            parse_hotkey(invalid)
