"""Size-limited copies of embedded-image Markdown; source files stay untouched."""

import base64
import binascii
import io
import re
from concurrent.futures import CancelledError
from contextlib import contextmanager
from pathlib import Path

from PIL import Image

from .storage import atomic_bytes

COMPACT_TARGET_BYTES = 24_000_000
UPLOAD_LIMIT_BYTES = 25_000_000
LARGE_EXPORT_BYTES = 20_000_000
# Never shrink below 1920 on the longest edge or JPEG quality 80.
PROFILES = ((2560, 90), (2560, 80), (1920, 85), (1920, 80))
DATA_IMAGE = re.compile(rb"data:image/(png|jpeg);base64,([A-Za-z0-9+/=]+)")


class ExportSizeError(ValueError):
    pass


def check_cancelled(cancelled):
    if cancelled():
        raise CancelledError("Shrinking cancelled; original Markdown kept.")


def size_notice(size):
    label = f"{size / 1_000_000:.2f} MB"
    if size >= UPLOAD_LIMIT_BYTES:
        return f"{label} — exceeds the 25 MB sharing target. Use compact export or Shrink Markdown."
    if size >= LARGE_EXPORT_BYTES:
        return f"{label} — approaching the 25 MB sharing target."
    return label


@contextmanager
def _embedded_image(source):
    try:
        raw = base64.b64decode(source.group(2), validate=True)
        with Image.open(io.BytesIO(raw)) as image:
            expected = "PNG" if source.group(1) == b"png" else "JPEG"
            if image.format != expected:
                raise ValueError("Image format does not match its data URL")
            yield image
    except (OSError, ValueError, SyntaxError, binascii.Error) as exc:
        raise ValueError("Cannot shrink an invalid embedded PNG/JPEG image.") from exc


def _smaller_image(source, max_edge, quality, cancelled=lambda: False):
    """Keep PNG when smaller; JPEG uses full chroma resolution for colored text."""
    check_cancelled(cancelled)
    with _embedded_image(source) as image:
        image.load()
        check_cancelled(cancelled)
        image.thumbnail((max_edge, max_edge), Image.Resampling.LANCZOS)
        check_cancelled(cancelled)
        transparent = "A" in image.getbands() or "transparency" in image.info
        image = image.convert("RGBA" if transparent else "RGB")
        png = io.BytesIO()
        image.save(png, format="PNG", optimize=True)
        check_cancelled(cancelled)
        candidates = [(b"png", png.getvalue())]
        if not transparent:
            jpeg = io.BytesIO()
            # Optimized Huffman coding can exhaust Pillow's buffer on noisy 4:4:4 images.
            image.save(jpeg, format="JPEG", quality=quality, subsampling=0)
            check_cancelled(cancelled)
            candidates.append((b"jpeg", jpeg.getvalue()))
    urls = [source.group(0)] + [
        b"data:image/" + kind + b";base64," + base64.b64encode(data) for kind, data in candidates
    ]
    return min(urls, key=len)


def compact_markdown(
    content, target_bytes=COMPACT_TARGET_BYTES, progress=lambda _: None, cancelled=lambda: False
):
    """Replace only data URLs, preserving all other bytes, including manual notes.

    Each pass starts from original images, avoiding accumulated JPEG artifacts.
    Within a pass, the largest screenshots are compressed first and work stops as
    soon as the report fits, so screenshots that are not needed to meet the target
    keep their original bytes, format, and resolution.
    The exact UTF-8 file size (including base64 overhead and text) must fit.
    """
    check_cancelled(cancelled)
    if target_bytes <= 0:
        raise ValueError("The Markdown size target must be positive")
    progress("Scanning Markdown for embedded screenshots…")
    matches = list(DATA_IMAGE.finditer(content))
    check_cancelled(cancelled)
    if len(content) <= target_bytes:
        # Validate existing embedded images without resizing or re-encoding them.
        for match in matches:
            check_cancelled(cancelled)
            with _embedded_image(match) as image:
                image.verify()
        progress("Report already fits the size target; images kept unchanged.")
        check_cancelled(cancelled)
        return content
    best = [match.group(0) for match in matches]
    text_size = len(content) - sum(map(len, best))
    if text_size > target_bytes:
        raise ExportSizeError(
            "Markdown text alone exceeds the compact size target. Split the report."
        )
    size = len(content)
    for pass_number, (max_edge, quality) in enumerate(PROFILES, 1):
        # Largest current image first; ties keep document order for determinism.
        for index in sorted(range(len(matches)), key=lambda i: (-len(best[i]), i)):
            check_cancelled(cancelled)
            progress(
                f"Optimizing screenshot {index + 1} of {len(matches)} "
                f"— pass {pass_number} of up to {len(PROFILES)}…"
            )
            candidate = _smaller_image(matches[index], max_edge, quality, cancelled)
            check_cancelled(cancelled)
            if len(candidate) < len(best[index]):
                size -= len(best[index]) - len(candidate)
                best[index] = candidate
            if size <= target_bytes:
                return _assemble(content, best, target_bytes, progress, cancelled)
        progress(
            f"Pass {pass_number} finished: {size / 1_000_000:.2f} MB "
            f"(target {target_bytes / 1_000_000:g} MB). "
            + (
                "Trying more compression…"
                if pass_number < len(PROFILES)
                else "Checking size limit…"
            )
        )
    raise ExportSizeError(
        f"Cannot fit this report under {target_bytes / 1_000_000:g} MB while keeping "
        f"screenshots at the quality floor (smallest result: {size / 1_000_000:.2f} MB). "
        "Split the report, use linked images, or choose raw export. Existing files were kept."
    )


def _assemble(content, best, target_bytes, progress, cancelled):
    progress("Assembling compact Markdown…")
    check_cancelled(cancelled)
    # Early success can leave images that never went through _smaller_image.
    # Validate those originals without re-encoding or changing their bytes.
    for match, replacement in zip(DATA_IMAGE.finditer(content), best):
        check_cancelled(cancelled)
        if replacement == match.group(0):
            with _embedded_image(match) as image:
                image.verify()
    replacements = iter(best)
    result = DATA_IMAGE.sub(lambda _: next(replacements), content)
    check_cancelled(cancelled)
    if len(result) > target_bytes:
        raise ExportSizeError("Assembled Markdown exceeds the compact size target.")
    return result


def shrink_markdown(path, progress=lambda _: None, cancelled=lambda: False):
    """Create a sibling copy without needing a session, transcript, or original PNGs."""
    path = Path(path)
    progress("Reading Markdown…")
    check_cancelled(cancelled)
    content = compact_markdown(
        path.read_bytes(), target_bytes=COMPACT_TARGET_BYTES, progress=progress, cancelled=cancelled
    )
    output = path.with_name(path.stem + ".compact.md")
    number = 2
    while output.exists():
        check_cancelled(cancelled)
        output = path.with_name(f"{path.stem}.compact-{number}.md")
        number += 1
    progress("Saving compact Markdown copy…")
    check_cancelled(cancelled)
    # Check once more after writing the temporary file, before publishing the copy.
    atomic_bytes(output, content, before_replace=lambda: check_cancelled(cancelled))
    return output
