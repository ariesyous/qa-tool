import base64
import io
import re
import shutil

import pytest
from PIL import Image

from qa_narrator.export import export_markdown, render
from qa_narrator.storage import Session, atomic_json
from qa_narrator.transcription import process_session


@pytest.fixture
def session(tmp_path):
    session = Session.create(tmp_path / "sessions", 16000, "fixture")
    session.update(status="stopped", duration=4)
    for number in range(1, 4):
        path = f"screenshots/{number:03d}.png"
        Image.new("RGB", (12, 8), (number * 60, 20, 80)).save(session.folder / path)
        session.event({"kind": "screenshot", "number": number, "path": path, "t": number})
    atomic_json(
        session.folder / "transcription.json",
        {
            "segments": [
                {
                    "start": 0,
                    "end": 4,
                    "text": " One two three four.",
                    "words": [
                        {"word": text, "start": when, "end": when + 0.8}
                        for when, text in enumerate((" One", " two", " three", " four."))
                    ],
                }
            ]
        },
    )
    return session


def test_portable_file_alone_contains_exact_png_bytes_and_original_sequence(session, tmp_path):
    expected = [(session.folder / e["path"]).read_bytes() for e in session.screenshots()]
    path = export_markdown(session, embed_images=True)
    standalone = tmp_path / "portable-findings.md"
    shutil.copyfile(path, standalone)
    text = standalone.read_text(encoding="utf-8")
    images = re.findall(r"!\[Screenshot (\d+)\]\(data:image/png;base64,([A-Za-z0-9+/=]+)\)", text)
    assert [number for number, _ in images] == ["001", "002", "003"]
    assert [base64.b64decode(payload, validate=True) for _, payload in images] == expected
    for _, payload in images:
        with Image.open(io.BytesIO(base64.b64decode(payload))) as image:
            assert image.format == "PNG" and image.size == (12, 8)
            image.verify()
    assert "](screenshots/" not in text
    assert text.index("One") < text.index("Screenshot 001]") < text.index("two")
    assert text.index("two") < text.index("Screenshot 002]") < text.index("three")
    assert all((session.folder / e["path"]).exists() for e in session.screenshots())


def test_export_mode_survives_reopen_and_can_switch_back_to_links(session):
    export_markdown(session, embed_images=True)
    reopened = Session.load(session.folder)
    assert reopened.data["export_embed_images"] is True
    assert "data:image/png;base64," in export_markdown(reopened).read_text()
    path = export_markdown(reopened, embed_images=False)
    assert "](screenshots/001.png)" in path.read_text()
    assert "data:image/png;base64," not in path.read_text()
    assert Session.load(session.folder).data["export_embed_images"] is False


def test_portable_export_refuses_to_overwrite_manual_edits(session):
    path = export_markdown(session)
    path.write_text("My notes", encoding="utf-8")
    with pytest.raises(FileExistsError):
        export_markdown(session, embed_images=True)
    assert path.read_text() == "My notes"
    assert not session.data["export_embed_images"]
    export_markdown(session, overwrite=True, embed_images=True)
    assert "data:image/png;base64," in path.read_text()


@pytest.mark.parametrize("bad_path", ["screenshots/099.png", "../outside.png"])
def test_embedded_export_validates_paths(session, bad_path):
    session.data["events"][0]["path"] = bad_path
    with pytest.raises(ValueError):
        export_markdown(session, embed_images=True)


def test_invalid_png_leaves_previous_export_intact(session):
    original = export_markdown(session).read_bytes()
    (session.folder / "screenshots/002.png").write_bytes(b"Not a PNG")
    with pytest.raises(ValueError, match="invalid PNG"):
        export_markdown(session, embed_images=True)
    assert (session.folder / "feedback.md").read_bytes() == original
    assert not session.data["export_embed_images"]


def test_empty_portable_session_exports_without_images(session):
    session.data["events"].clear()
    text = render(session, {"segments": []}, embed_images=True)
    assert "Screenshots: 0" in text and "No speech was transcribed." in text
    assert "![Screenshot" not in text


def test_processing_passes_portable_preference_to_export(session):
    from types import SimpleNamespace

    model = SimpleNamespace(transcribe=lambda *args, **kwargs: ([], SimpleNamespace(language="en")))
    path = process_session(session, factory=lambda _: model, embed_images=True)
    assert "data:image/png;base64," in path.read_text()
    assert session.data["export_embed_images"] is True


@pytest.mark.parametrize(
    "flag,value", [([], None), (["--embed-images"], True), (["--linked-images"], False)]
)
def test_cli_export_mode_selection(session, monkeypatch, flag, value):
    from qa_narrator.__main__ import main

    received = []
    monkeypatch.setattr("sys.argv", ["qa-narrator", "--export", str(session.folder), *flag])
    monkeypatch.setattr(
        "qa_narrator.export.export_markdown", lambda session, **kw: received.append(kw)
    )
    assert main() == 0
    assert received == [{"embed_images": value}]
