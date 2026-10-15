import argparse
import sys


def main():
    parser = argparse.ArgumentParser(description="Local QA Narrator")
    parser.add_argument("--download-model", choices=("tiny.en", "base.en", "small.en"))
    parser.add_argument(
        "--process", metavar="SESSION_FOLDER", help="Recover and transcribe saved audio"
    )
    parser.add_argument(
        "--export", metavar="SESSION_FOLDER", help="Regenerate Markdown from saved transcription"
    )
    parser.add_argument(
        "--shrink-markdown",
        metavar="FILE",
        help="Save a compact copy under 25 MB; keep the original",
    )
    parser.add_argument(
        "--image-quality",
        choices=("compact", "raw"),
        help="Compact targets 24 MB; raw preserves original PNG bytes (embedded exports only)",
    )
    parser.add_argument("--model", default="base.en", choices=("tiny.en", "base.en", "small.en"))
    images = parser.add_mutually_exclusive_group()
    images.add_argument(
        "--embed-images",
        dest="embed_images",
        action="store_true",
        default=None,
        help="Embed PNGs as base64 data URLs for a single-file Markdown report",
    )
    images.add_argument(
        "--linked-images",
        dest="embed_images",
        action="store_false",
        help="Use relative screenshot paths (recommended for coding agents; share screenshots/ too)",
    )
    args = parser.parse_args()
    quality_options = {"image_quality": args.image_quality} if args.image_quality else {}
    if args.shrink_markdown:
        from .compact import shrink_markdown, size_notice

        path = shrink_markdown(args.shrink_markdown)
        print(f"{path} ({size_notice(path.stat().st_size)})")
    elif args.download_model:
        from .transcription import download_model

        print(download_model(args.download_model))
    elif args.process:
        from .storage import Session
        from .transcription import process_session

        session = Session.load(args.process)
        session.recover()
        if not (session.folder / "audio.wav").exists():
            session.finalize_audio()
        path = process_session(
            session, args.model, print, embed_images=args.embed_images, **quality_options
        )
        _print_export(path)
    elif args.export:
        from .export import export_markdown
        from .storage import Session

        path = export_markdown(
            Session.load(args.export), embed_images=args.embed_images, **quality_options
        )
        _print_export(path)
    elif sys.platform != "win32":
        parser.error(
            "The capture UI requires Windows 10/11. Export and transcription can run independently."
        )
    else:
        from .ui import run

        return run()
    return 0


def _print_export(path):
    from .compact import size_notice

    if path is not None:
        print(path)
        print(size_notice(path.stat().st_size))


if __name__ == "__main__":
    raise SystemExit(main())
