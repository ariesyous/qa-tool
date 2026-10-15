import json
from types import SimpleNamespace

import pytest

from qa_narrator.storage import Session
from qa_narrator.transcription import process_session


def session_with_audio(tmp_path):
    session = Session.create(tmp_path / "sessions", 16000, "Fixture")
    session.update(status="stopped", duration=1)
    (session.folder / "audio.wav").write_bytes(b"Audio fixture")
    return session


def model_with_options(options):
    def transcribe(path, **kwargs):
        options.append(kwargs)
        return [], SimpleNamespace(language="en")

    return SimpleNamespace(transcribe=transcribe)


@pytest.mark.parametrize("vocabulary,expected", [
    (None, ""), ("", ""), ("  \t\n ", ""),
    (" AcmeUI,  QANarrator\nSave As, café ", "AcmeUI, QANarrator Save As, café"),
])
def test_vocabulary_reaches_hotwords_and_is_saved_with_transcript(tmp_path, vocabulary, expected):
    session = session_with_audio(tmp_path)
    options = []
    model = model_with_options(options)
    process_session(session, vocabulary=vocabulary, factory=lambda _: model)
    assert options[0]["hotwords"] == (expected or None)
    assert options[0]["condition_on_previous_text"] is False
    assert "initial_prompt" not in options[0] and "prefix" not in options[0]
    reopened = Session.load(session.folder)
    transcript = json.loads((session.folder / "transcription.json").read_text(encoding="utf-8"))
    assert reopened.data["transcription_vocabulary"] == transcript["vocabulary"] == expected


def test_failed_transcription_keeps_hints_for_retry_and_empty_override_clears_them(tmp_path):
    session = session_with_audio(tmp_path)

    def fail(_):
        raise OSError("Model unavailable")

    with pytest.raises(OSError, match="Model unavailable"):
        process_session(session, vocabulary="AcmeUI, Save As", factory=fail)
    assert session.data["transcription_status"] == "failed"
    options = []
    model = model_with_options(options)
    reopened = Session.load(session.folder)
    process_session(reopened, factory=lambda _: model)
    assert options[-1]["hotwords"] == "AcmeUI, Save As"
    process_session(reopened, vocabulary="", factory=lambda _: model)
    assert options[-1]["hotwords"] is None
    assert Session.load(session.folder).data["transcription_vocabulary"] == ""


@pytest.mark.parametrize("arguments,expected", [
    ([], "Saved product"), (["--vocabulary", "New product, Save As"], "New product, Save As"),
    (["--vocabulary="], ""),
])
def test_cli_vocabulary_reuses_overrides_and_clears_saved_hints(tmp_path, monkeypatch, arguments, expected):
    from qa_narrator.__main__ import main

    session = session_with_audio(tmp_path)
    session.update(transcription_vocabulary="Saved product")
    options = []
    model = model_with_options(options)
    monkeypatch.setattr("qa_narrator.transcription.process_session", lambda *args, **kwargs:
                        process_session(*args, factory=lambda _: model, **kwargs))
    monkeypatch.setattr("sys.argv", ["qa-narrator", "--process", str(session.folder), *arguments])
    assert main() == 0
    assert options[-1]["hotwords"] == (expected or None)
    assert Session.load(session.folder).data["transcription_vocabulary"] == expected


def test_cli_rejects_vocabulary_without_processing(monkeypatch, capsys):
    from qa_narrator.__main__ import main

    monkeypatch.setattr("sys.argv", ["qa-narrator", "--vocabulary", "AcmeUI"])
    with pytest.raises(SystemExit) as error:
        main()
    assert error.value.code == 2
    assert "--vocabulary requires --process" in capsys.readouterr().err
