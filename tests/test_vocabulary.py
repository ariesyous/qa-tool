import json
from types import SimpleNamespace

import pytest

from qa_narrator.storage import Session
from qa_narrator.transcription import fit_vocabulary, process_session


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


class WordTokenizer:
    """One token per whitespace-separated word, like a crude BPE stand-in."""

    def encode(self, text, add_special_tokens=False):
        assert add_special_tokens is False
        return SimpleNamespace(ids=text.split())


def tokenized_model(options, max_length):
    model = model_with_options(options)
    model.hf_tokenizer = WordTokenizer()
    model.max_length = max_length
    return model


def test_hints_within_budget_reach_hotwords_unchanged(tmp_path):
    session = session_with_audio(tmp_path)
    options = []
    # max_length 448 -> 223-token budget, the faster-whisper limit; 223 words fit exactly.
    vocabulary = " ".join(f"term{i}" for i in range(223))
    process_session(session, vocabulary=vocabulary, factory=lambda _: tokenized_model(options, 448))
    assert options[0]["hotwords"] == vocabulary
    assert session.data["transcription_vocabulary_unused"] == ""


def test_long_hints_keep_whole_terms_and_report_the_rest(tmp_path):
    session = session_with_audio(tmp_path)
    options, updates = [], []
    vocabulary = "Acme UI, Save As, Order History Page, OAuth"
    # Budget of 5 words: "Acme UI, Save As," fits; "Order History Page" would exceed it.
    process_session(
        session, vocabulary=vocabulary, progress=updates.append,
        factory=lambda _: tokenized_model(options, 12),
    )
    assert options[0]["hotwords"] == "Acme UI, Save As"
    assert session.data["transcription_vocabulary"] == vocabulary
    assert session.data["transcription_vocabulary_unused"] == "Order History Page, OAuth"
    transcript = json.loads((session.folder / "transcription.json").read_text(encoding="utf-8"))
    assert transcript["vocabulary_unused"] == "Order History Page, OAuth"
    assert any("not used: Order History Page, OAuth" in message for message in updates)


def test_long_hints_without_commas_are_kept_word_by_word(tmp_path):
    session = session_with_audio(tmp_path)
    options = []
    process_session(
        session, vocabulary="alpha beta gamma delta", factory=lambda _: tokenized_model(options, 6)
    )
    assert options[0]["hotwords"] == "alpha beta"
    assert session.data["transcription_vocabulary_unused"] == "gamma delta"


def test_one_long_comma_free_run_falls_back_to_words_and_repeats_are_dropped(tmp_path):
    session = session_with_audio(tmp_path)
    options = []
    vocabulary = "alpha beta gamma delta epsilon, OAuth, OAuth"
    process_session(session, vocabulary=vocabulary, factory=lambda _: tokenized_model(options, 8))
    # Budget 3 words; the first comma-separated chunk alone is 5 words.
    assert options[0]["hotwords"] == "alpha beta gamma"
    assert session.data["transcription_vocabulary_unused"] == "delta epsilon, OAuth, OAuth"
    # Over budget (4 words > 3), so repeats are dropped before fitting.
    model = tokenized_model([], 8)
    assert fit_vocabulary("OAuth, OAuth, SSO, Kubernetes", model) == ("OAuth, SSO, Kubernetes", "")


def test_unused_hints_are_cleared_when_a_retry_fails_before_transcribing(tmp_path):
    session = session_with_audio(tmp_path)
    process_session(
        session, vocabulary="a b c d", factory=lambda _: tokenized_model([], 6)
    )
    assert session.data["transcription_vocabulary_unused"] == "c d"

    def fail(_):
        raise OSError("Model unavailable")

    with pytest.raises(OSError):
        process_session(session, vocabulary="a", factory=fail)
    assert session.data["transcription_vocabulary_unused"] == ""


def test_unexpected_tokenizer_never_blocks_transcription(tmp_path):
    session = session_with_audio(tmp_path)
    options = []
    model = model_with_options(options)
    model.hf_tokenizer = SimpleNamespace(encode=lambda *a, **k: 1 / 0)
    process_session(session, vocabulary="AcmeUI, Save As", factory=lambda _: model)
    assert options[0]["hotwords"] == "AcmeUI, Save As"
