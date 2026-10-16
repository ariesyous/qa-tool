import base64
import io
import random

import pytest
from PIL import Image

from qa_narrator import compact
from qa_narrator.compact import DATA_IMAGE, ExportSizeError, compact_markdown, shrink_markdown
from qa_narrator.export import export_markdown
from qa_narrator.storage import Session, atomic_json


def data_url(image):
    output = io.BytesIO()
    image.save(output, format="PNG")
    return b"data:image/png;base64," + base64.b64encode(output.getvalue())


def noisy_image(width, height):
    return Image.frombytes("RGB", (width, height), random.Random(42).randbytes(width * height * 3))


def decode_at(content, index):
    match = list(DATA_IMAGE.finditer(content))[index]
    image = Image.open(io.BytesIO(base64.b64decode(match.group(2), validate=True)))
    image.load()
    return image


def decode(content):
    match = DATA_IMAGE.search(content)
    image = Image.open(io.BytesIO(base64.b64decode(match.group(2), validate=True)))
    image.load()
    return image


def test_4k_report_over_30_mb_fits_without_losing_notes_or_source(tmp_path):
    # High-entropy fixture is harder to compress than a typical application screenshot.
    original = b"# Notes\r\nCaf\xc3\xa9\r\n![Screenshot 001](" + data_url(noisy_image(3840, 2160))
    original += b")\r\nManual **feedback** stays here.\r\n"
    assert len(original) > 30_000_000
    source = tmp_path / "feedback.md"
    source.write_bytes(original)
    output = shrink_markdown(source)
    result = output.read_bytes()
    assert len(result) <= compact.COMPACT_TARGET_BYTES < 25_000_000
    assert DATA_IMAGE.sub(b"IMAGE", result) == DATA_IMAGE.sub(b"IMAGE", original)
    assert source.read_bytes() == original
    image = decode(result)
    assert image.format == "JPEG" and image.size == (2560, 1440)
    assert output.name == "feedback.compact.md"


def test_shrink_never_overwrites_previous_copy(tmp_path):
    source = tmp_path / "feedback.md"
    source.write_bytes(b"Notes\n![shot](" + data_url(Image.new("RGB", (10, 10))) + b")")
    existing = tmp_path / "feedback.compact.md"
    existing.write_bytes(b"Keep my previous copy")
    assert shrink_markdown(source).name == "feedback.compact-2.md"
    assert existing.read_bytes() == b"Keep my previous copy"


def test_progressively_compresses_to_exact_budget(monkeypatch):
    url = data_url(noisy_image(800, 450))
    content = b"Notes\n![first](" + url + b")\nMore feedback\n![second](" + url + b")"
    matches = list(DATA_IMAGE.finditer(content))
    # Size with both images at the first profile: one byte over forces a second pass.
    both_first_pass = len(content) - sum(
        len(m.group(0)) - len(compact._smaller_image(m, 800, 90)) for m in matches
    )
    monkeypatch.setattr(compact, "PROFILES", ((800, 90), (400, 80)))
    updates = []
    result = compact_markdown(content, target_bytes=both_first_pass - 1, progress=updates.append)
    assert [message for message in updates if message.startswith("Optimizing")] == [
        "Optimizing screenshot 1 of 2 — pass 1 of up to 2…",
        "Optimizing screenshot 2 of 2 — pass 1 of up to 2…",
        "Optimizing screenshot 1 of 2 — pass 2 of up to 2…",
    ]
    assert "Trying more compression" in " ".join(updates)
    assert updates[-1] == "Assembling compact Markdown…"
    assert len(result) <= both_first_pass - 1
    assert len(DATA_IMAGE.findall(result)) == 2
    assert DATA_IMAGE.sub(b"IMAGE", result) == DATA_IMAGE.sub(b"IMAGE", content)
    sizes = [decode_at(result, i).size for i in range(2)]
    assert sizes == [(400, 225), (800, 450)]  # stopped once the budget was met
    # Exactly at the target still fits, after the first pass alone.
    assert len(compact_markdown(content, target_bytes=both_first_pass)) == both_first_pass


def test_just_over_target_compresses_only_the_largest_screenshots(monkeypatch):
    small, large, medium = noisy_image(300, 169), noisy_image(1200, 675), noisy_image(600, 338)
    urls = [data_url(image) for image in (small, large, medium)]
    content = b"# Notes\n" + b"\n".join(b"![shot](" + url + b")" for url in urls) + b"\n"
    updates = []
    result = compact_markdown(content, target_bytes=len(content) - 1, progress=updates.append)
    assert len(result) <= len(content) - 1
    assert [message for message in updates if message.startswith("Optimizing")] == [
        "Optimizing screenshot 2 of 3 — pass 1 of up to 4…"
    ]
    kept = [m.group(0) for m in DATA_IMAGE.finditer(result)]
    assert kept[0] == urls[0] and kept[2] == urls[2]  # untouched PNG bytes
    assert decode_at(result, 1).format == "JPEG" and decode_at(result, 1).size == (1200, 675)


def test_unreachable_budget_keeps_previous_export_and_preferences(tmp_path, monkeypatch):
    session = make_session(tmp_path)
    original = export_markdown(session, embed_images=True, image_quality="raw").read_bytes()
    old_data = dict(session.data)
    monkeypatch.setattr(
        "qa_narrator.export.compact_markdown", lambda content, **kw: compact_markdown(content, 1)
    )
    with pytest.raises(ExportSizeError, match="text alone"):
        export_markdown(session, embed_images=True, image_quality="compact")
    assert (session.folder / "feedback.md").read_bytes() == original
    assert session.data == old_data


def test_quality_floor_fails_without_writing_shrunken_file(tmp_path, monkeypatch):
    source = tmp_path / "report.md"
    original = b"![shot](" + data_url(noisy_image(80, 45)) + b")"
    source.write_bytes(original)
    with pytest.raises(ExportSizeError, match="quality floor"):
        compact_markdown(original, target_bytes=100)
    monkeypatch.setattr(
        compact,
        "compact_markdown",
        lambda content, **kw: (_ for _ in ()).throw(ExportSizeError("too big")),
    )
    with pytest.raises(ExportSizeError):
        shrink_markdown(source)
    assert list(tmp_path.iterdir()) == [source]
    assert source.read_bytes() == original


def test_transparent_png_stays_transparent_and_small_image_not_upscaled():
    source = b"![shot](" + data_url(Image.new("RGBA", (20, 10), (255, 0, 0, 50))) + b")"
    result = compact_markdown(source)
    image = decode(result)
    assert image.size == (20, 10) and image.format == "PNG"
    assert image.getpixel((0, 0)) == (255, 0, 0, 50)
    assert len(result) <= len(source)


@pytest.mark.parametrize("payload", [b"bad", base64.b64encode(b"not an image")])
def test_bad_image_does_not_create_copy(tmp_path, payload):
    source = tmp_path / "bad.md"
    original = b"![shot](data:image/png;base64," + payload + b")"
    source.write_bytes(original)
    with pytest.raises(ValueError, match="invalid embedded"):
        shrink_markdown(source)
    assert list(tmp_path.iterdir()) == [source]
    assert source.read_bytes() == original


def make_session(tmp_path):
    session = Session.create(tmp_path / "sessions", 16000, "fixture")
    session.update(status="stopped", duration=1)
    noisy_image(800, 450).save(session.folder / "screenshots/001.png")
    session.event({"kind": "screenshot", "number": 1, "path": "screenshots/001.png", "t": 0})
    atomic_json(session.folder / "transcription.json", {"segments": []})
    return session


def test_compact_preference_persists_and_small_report_keeps_exact_png(tmp_path):
    session = make_session(tmp_path)
    source = (session.folder / "screenshots/001.png").read_bytes()
    result = export_markdown(session, embed_images=True, image_quality="compact").read_bytes()
    assert decode(result).format == "PNG"
    assert base64.b64decode(DATA_IMAGE.search(result).group(2)) == source
    reopened = Session.load(session.folder)
    assert reopened.data["export_image_quality"] == "compact"
    assert reopened.data["export_size_bytes"] == len(result)
    assert export_markdown(reopened).read_bytes() == result
    raw = export_markdown(reopened, image_quality="raw").read_bytes()
    assert base64.b64decode(DATA_IMAGE.search(raw).group(2)) == source
    assert (session.folder / "screenshots/001.png").read_bytes() == source


def test_cli_compact_export_and_standalone_shrink(tmp_path, monkeypatch, capsys):
    from qa_narrator.__main__ import main

    session = make_session(tmp_path)
    monkeypatch.setattr(
        "sys.argv",
        [
            "qa-narrator",
            "--export",
            str(session.folder),
            "--embed-images",
            "--image-quality",
            "compact",
        ],
    )
    assert main() == 0
    assert Session.load(session.folder).data["export_image_quality"] == "compact"
    monkeypatch.setattr(
        "sys.argv",
        [
            "qa-narrator",
            "--shrink-markdown",
            str(session.folder / "feedback.md"),
        ],
    )
    assert main() == 0
    assert (session.folder / "feedback.compact.md").exists()
    assert "MB" in capsys.readouterr().out


@pytest.mark.parametrize(
    "size,expected",
    [
        (19_999_999, "20.00 MB"),
        (20_000_000, "approaching"),
        (25_000_000, "exceeds"),
    ],
)
def test_size_warning_boundaries(size, expected):
    assert expected in compact.size_notice(size)


def test_process_passes_compact_preference(tmp_path):
    from types import SimpleNamespace

    from qa_narrator.transcription import process_session

    session = make_session(tmp_path)
    model = SimpleNamespace(transcribe=lambda *a, **kw: ([], SimpleNamespace(language="en")))
    updates = []
    path = process_session(
        session,
        factory=lambda _: model,
        embed_images=True,
        image_quality="compact",
        progress=updates.append,
    )
    assert decode(path.read_bytes()).format == "PNG"
    assert session.data["export_image_quality"] == "compact"
    assert "Preparing screenshot 1 of 1…" in updates
    assert any("already fits" in message for message in updates)
    assert not any(message.startswith("Optimizing") for message in updates)
    assert updates[-1] == "Saving Markdown…"


@pytest.mark.parametrize("stage", ["Reading", "Scanning", "Optimizing", "Assembling", "Saving"])
def test_cancel_keeps_original_and_previous_copy_at_each_stage(tmp_path, monkeypatch, stage):
    from concurrent.futures import CancelledError
    from threading import Event

    source = tmp_path / "feedback.md"
    original = b"Manual notes\n![shot](" + data_url(noisy_image(80, 45)) + b")"
    monkeypatch.setattr(compact, "COMPACT_TARGET_BYTES", 10_000)
    source.write_bytes(original)
    previous = tmp_path / "feedback.compact.md"
    previous.write_bytes(b"Existing copy with my edits")
    cancelled = Event()

    def progress(message):
        if message.startswith(stage):
            cancelled.set()

    with pytest.raises(CancelledError):
        shrink_markdown(source, progress=progress, cancelled=cancelled.is_set)
    assert source.read_bytes() == original
    assert previous.read_bytes() == b"Existing copy with my edits"
    assert set(tmp_path.iterdir()) == {source, previous}


def test_cancellation_during_image_encode_is_not_reported_as_invalid_image(monkeypatch):
    from concurrent.futures import CancelledError
    from threading import Event

    content = b"![shot](" + data_url(noisy_image(80, 45)) + b")"
    cancelled = Event()
    save = Image.Image.save

    def cancel_after_encode(*args, **kwargs):
        save(*args, **kwargs)
        cancelled.set()

    monkeypatch.setattr(Image.Image, "save", cancel_after_encode)
    with pytest.raises(CancelledError):
        compact_markdown(content, target_bytes=10_000, cancelled=cancelled.is_set)


@pytest.mark.parametrize("image_format", ["PNG", "JPEG"])
@pytest.mark.parametrize("headroom", [0, 100])
def test_report_that_fits_keeps_large_images_and_all_bytes_without_encoding(
    monkeypatch, image_format, headroom
):
    image = Image.new("RGB", (3840, 2160), (100, 150, 200))
    buffer = io.BytesIO()
    image.save(buffer, format=image_format)
    url = b"data:image/" + image_format.lower().encode() + b";base64,"
    original = b"# Notes\r\nManual feedback\n![shot](" + url + base64.b64encode(buffer.getvalue()) + b")\n"

    def fail(*args, **kwargs):
        pytest.fail("Images in reports that fit must not be re-encoded")

    monkeypatch.setattr(Image.Image, "save", fail)
    result = compact_markdown(original, target_bytes=len(original) + headroom)
    assert result == original
    assert decode(result).size == (3840, 2160) and decode(result).format == image_format


def test_size_check_after_assembly_is_explicit(monkeypatch):
    from types import SimpleNamespace

    content = b"![shot](" + data_url(noisy_image(80, 45)) + b")"
    finditer = DATA_IMAGE.finditer
    monkeypatch.setattr(compact, "DATA_IMAGE", SimpleNamespace(
        finditer=finditer, sub=lambda *args: b"x" * 10_001
    ))
    with pytest.raises(ExportSizeError, match="Assembled Markdown"):
        compact_markdown(content, target_bytes=10_000)


def test_cancellation_after_preserving_small_report_does_not_publish_copy(tmp_path):
    from concurrent.futures import CancelledError
    from threading import Event

    source = tmp_path / "feedback.md"
    original = b"![shot](" + data_url(Image.new("RGB", (12, 8))) + b")"
    source.write_bytes(original)
    cancelled = Event()

    def progress(message):
        if "already fits" in message:
            cancelled.set()

    with pytest.raises(CancelledError):
        shrink_markdown(source, progress=progress, cancelled=cancelled.is_set)
    assert source.read_bytes() == original and list(tmp_path.iterdir()) == [source]


def test_cancel_during_save_removes_temporary_file(tmp_path, monkeypatch):
    from concurrent.futures import CancelledError
    from threading import Event

    from qa_narrator import storage

    source = tmp_path / "feedback.md"
    source.write_bytes(b"Feedback with no images")
    cancelled = Event()
    fsync = storage.os.fsync

    def cancel_after_flush(fd):
        fsync(fd)
        cancelled.set()

    monkeypatch.setattr(storage.os, "fsync", cancel_after_flush)
    with pytest.raises(CancelledError):
        shrink_markdown(source, cancelled=cancelled.is_set)
    assert source.read_bytes() == b"Feedback with no images"
    assert list(tmp_path.iterdir()) == [source]
