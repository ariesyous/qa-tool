"""Deterministic interleaving without paraphrasing or dropping transcript characters."""

import base64
import hashlib
import html
import io
import json
import re
import unicodedata
from pathlib import PurePosixPath

from .compact import compact_markdown
from .storage import atomic_bytes


class EditedMarkdownError(FileExistsError):
    """An existing report has manual edits that need explicit replacement."""


def timestamp(seconds):
    seconds = max(0, int(seconds))
    hours, rest = divmod(seconds, 3600)
    minutes, seconds = divmod(rest, 60)
    return f"{hours:02}:{minutes:02}:{seconds:02}" if hours else f"{minutes:02}:{seconds:02}"


def text_units(transcript):
    """Use exact segment text, validating word alignment before trusting word boundaries.

    If words do not match segment text (or timing is invalid), distribute the original
    whitespace-preserving tokens over the segment. No transcript content is substituted.
    """
    previous = 0.0
    for segment in transcript.get("segments", []):
        text = segment["text"]
        start = max(previous, float(segment["start"]))
        end = max(start, float(segment["end"]))
        words = segment.get("words") or []
        valid = bool(words) and "".join(w["word"] for w in words) == text
        last = start
        for word in words:
            when = float(word["start"])
            if not (last <= when <= float(word["end"]) <= end):
                valid = False
            last = when
        if valid:
            for word in words:
                yield float(word["start"]), word["word"], "word"
        else:
            tokens = re.findall(r"\s*\S+|\s+$", text)
            for index, token in enumerate(tokens):
                yield start + (end - start) * index / max(1, len(tokens)), token, "estimated"
        previous = end


def relative_image(session, event):
    raw = event["path"]
    path = PurePosixPath(raw)
    if (
        path.is_absolute()
        or ".." in path.parts
        or len(path.parts) != 2
        or path.parts[0] != "screenshots"
        or not re.fullmatch(r"\d+\.png", path.name)
    ):
        raise ValueError(f"Invalid screenshot path: {raw}")
    resolved = (session.folder / raw).resolve()
    if not resolved.is_relative_to(session.folder.resolve()) or not resolved.is_file():
        raise ValueError(f"Missing or unsafe screenshot: {raw}")
    return path.as_posix()


def image_source(session, event, embed_images):
    path = relative_image(session, event)
    if not embed_images:
        return path
    from PIL import Image

    png = (session.folder / path).read_bytes()
    try:
        with Image.open(io.BytesIO(png)) as image:
            if image.format != "PNG":
                raise ValueError("Image is not PNG")
            image.verify()
    except (OSError, ValueError, SyntaxError) as exc:
        raise ValueError(f"Cannot embed invalid PNG screenshot: {path}") from exc
    return "data:image/png;base64," + base64.b64encode(png).decode("ascii")


# Window titles can be up to 32K characters; a heading only needs the gist.
CONTEXT_FIELD_LIMIT = 200


def screenshot_context(event):
    context = event.get("window_context", {})

    def escape(value):
        text = " ".join(value.split())
        # Drop control characters (Cc, including C1 such as U+009B) and invisible format
        # characters (Cf: bidi overrides such as U+202E, zero-width spaces), which can
        # reorder or disguise the label. Joiners in emoji sequences go too; acceptable
        # for a heading.
        text = "".join(c for c in text if unicodedata.category(c) not in ("Cc", "Cf"))
        if len(text) > CONTEXT_FIELD_LIMIT:
            text = text[: CONTEXT_FIELD_LIMIT - 1].rstrip() + "…"
        return re.sub(r"([\\`*_{}\[\]()#+.!|~\-])", r"\\\1", html.escape(text, quote=False))

    fields = [escape(context.get(key, "")) for key in ("app", "title")]
    details = " — ".join(field for field in fields if field)
    if not details:
        return ""
    label = "Focused window: " if event.get("mode") != "window" or event.get("fallback") else ""
    return " · " + label + details


def render(session, transcript, embed_images=False, image_quality="raw", progress=lambda _: None):
    shots = sorted(session.screenshots(), key=lambda e: (e["t"], e["sequence"]))
    units = list(text_units(transcript))
    events = [(t, 1, i, (value, accuracy)) for i, (t, value, accuracy) in enumerate(units)]
    events += [(e["t"], 0, e["sequence"], e) for e in shots]
    events.sort(key=lambda item: item[:3])
    data = session.data
    lines = [
        "# QA Walkthrough",
        "",
        f"Date: {data['created']}",
        f"Duration: {timestamp(data['duration'])}",
        f"Screenshots: {len(shots)}",
        "",
        "Timing: screenshots use the recorded active-session timeline. Speech timestamps "
        "are model estimates; a screenshot inside a word appears before that word's successor.",
        "For coding agents, use linked images: share feedback.md together with the screenshots/ "
        "folder, or zip the session folder. Embedded images can exceed agent text-reading limits "
        "even with compact export.",
    ]
    if embed_images:
        lines += [
            "Images: screenshots are embedded in this file as PNG/JPEG base64 data URLs; "
            "no screenshot folder is needed to share this report. Some Markdown viewers "
            "do not display data URLs. For coding agents, regenerate with embedding off. "
            "If only this embedded file is available, "
            "decode each data:image/png;base64 or data:image/jpeg;base64 URL to an image file."
        ]
        if image_quality == "compact":
            lines += [
                "Compact export: images are preserved when the report fits the size target. "
                "Oversized reports may be resized or compressed; original captures are retained."
            ]
    if any(accuracy == "estimated" for _, _, accuracy in units):
        lines += [
            "Some word boundaries were unavailable; those segment tokens use evenly spaced "
            "estimated timestamps. Original transcript text is preserved."
        ]
    if data.get("recovery_note"):
        lines += [f"Recovery: {data['recovery_note']}"]
    warnings = [e for e in data["events"] if e["kind"] == "warning"]
    if warnings:
        lines += ["", "Capture warnings:"]
        lines += [f"- [{timestamp(e['t'])}] {e['message']}" for e in warnings]
    lines += ["", "---", "", "## Walkthrough", ""]
    pending, pending_time = [], 0

    def flush():
        if pending:
            # Preserve content; only the whitespace at the Markdown paragraph edges is trimmed.
            lines.extend([f"**[{timestamp(pending_time)}]**", "", "".join(pending).strip(), ""])
            pending.clear()

    shot_number = 0
    for when, kind, _, payload in events:
        if kind == 0:
            flush()
            shot_number += 1
            progress(f"Preparing screenshot {shot_number} of {len(shots)}…")
            path = image_source(session, payload, embed_images)
            lines += [
                f"**[{timestamp(when)} — Screenshot{screenshot_context(payload)}]**",
                "",
                f"![Screenshot {payload['number']:03d}]({path})",
                "",
            ]
        else:
            value, _ = payload
            if pending and when - pending_time >= 30:
                flush()
            if not pending:
                pending_time = when
            pending.append(value)
    flush()
    if not units:
        lines += ["No speech was transcribed.", ""]
    return "\n".join(lines)


def export_markdown(
    session, overwrite=False, embed_images=None, image_quality=None, progress=lambda _: None
):
    progress("Preparing Markdown…")
    if embed_images is None:
        embed_images = session.data.get("export_embed_images", False)
    if image_quality is None:
        image_quality = session.data.get("export_image_quality", "raw")
    if image_quality not in ("raw", "compact"):
        raise ValueError("Image quality must be raw or compact")
    transcript = json.loads((session.folder / "transcription.json").read_text(encoding="utf-8"))
    output = session.folder / "feedback.md"
    if output.exists() and not overwrite:
        saved_hash = session.data.get("export_sha256")
        current_hash = hashlib.sha256(output.read_bytes()).hexdigest()
        if current_hash != saved_hash:
            raise EditedMarkdownError("feedback.md has manual edits. Confirm replacement or keep it.")
    content = render(
        session,
        transcript,
        embed_images=embed_images,
        image_quality=image_quality,
        progress=progress,
    ).encode("utf-8")
    if embed_images and image_quality == "compact":
        content = compact_markdown(content, progress=progress)
    progress("Saving Markdown…")
    atomic_bytes(output, content)
    session.update(
        export_status="complete",
        export_sha256=hashlib.sha256(content).hexdigest(),
        export_embed_images=bool(embed_images),
        export_image_quality=image_quality,
        export_size_bytes=len(content),
        export_error=None,
    )
    return output
