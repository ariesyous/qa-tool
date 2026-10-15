"""Local CPU inference; downloading is a separate, explicit setup operation."""

import os
from pathlib import Path

from .export import EditedMarkdownError, export_markdown
from .storage import atomic_json

MODELS = ("base.en", "tiny.en", "small.en")
os.environ["HF_HUB_DISABLE_TELEMETRY"] = "1"


def model_root():
    if os.environ.get("QA_NARRATOR_MODEL_DIR"):
        return Path(os.environ["QA_NARRATOR_MODEL_DIR"])
    return Path(os.environ.get("LOCALAPPDATA", str(Path.home()))) / "QANarrator" / "models"


def download_model(name, root=None):
    if name not in MODELS:
        raise ValueError("Unsupported model")
    from faster_whisper.utils import download_model as fetch

    target = Path(root or model_root()) / name
    fetch(name, output_dir=str(target))
    return target


def local_model(name, root=None):
    path = Path(root or model_root()) / name
    if not all(
        (path / file).is_file()
        for file in ("model.bin", "config.json", "tokenizer.json", "vocabulary.txt")
    ):
        raise FileNotFoundError(
            f"Model {name} is not installed. Use Download Model in Settings "
            "while online, or copy a complete faster-whisper model to " + str(path)
        )
    from faster_whisper import WhisperModel

    return WhisperModel(
        str(path),
        device="cpu",
        compute_type="int8",
        local_files_only=True,
        cpu_threads=max(1, min(4, (os.cpu_count() or 2) - 1)),
    )


def process_session(
    session,
    model_name="base.en",
    progress=lambda _: None,
    factory=local_model,
    embed_images=None,
    image_quality=None,
):
    """Save the transcript and export, returning None when edited Markdown is kept."""
    session.update(transcription_status="processing", transcription_error=None)
    try:
        progress("Loading local model…")
        model = factory(model_name)
        progress("Transcribing locally on CPU…")
        segments, info = model.transcribe(
            str(session.folder / "audio.wav"),
            language="en",
            word_timestamps=True,
            beam_size=5,
            vad_filter=True,
            condition_on_previous_text=False,
        )
        result = []
        for segment in segments:
            result.append(
                {
                    "start": segment.start,
                    "end": segment.end,
                    "text": segment.text,
                    "words": [
                        {
                            "start": w.start,
                            "end": w.end,
                            "word": w.word,
                            "probability": w.probability,
                        }
                        for w in (segment.words or [])
                    ],
                }
            )
            progress(f"Transcribing… {segment.end:.0f} / {session.data['duration']:.0f} seconds")
        atomic_json(
            session.folder / "transcription.json",
            {"version": 1, "model": model_name, "language": info.language, "segments": result},
        )
        session.update(transcription_status="complete")
    except Exception as exc:
        session.update(transcription_status="failed", transcription_error=str(exc))
        raise
    progress("Writing Markdown…")
    try:
        return export_markdown(
            session, embed_images=embed_images, image_quality=image_quality, progress=progress
        )
    except EditedMarkdownError:
        session.update(export_status="manual_edits_kept", export_error=None)
        progress("Transcript updated; use Regenerate Markdown to replace your edited feedback.md.")
        return None
    except Exception as exc:
        session.update(export_status="needs_attention", export_error=str(exc))
        raise
