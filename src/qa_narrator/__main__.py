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
        help="Use relative screenshot paths instead of embedded images",
    )
    args = parser.parse_args()
    if args.download_model:
        from .transcription import download_model

        print(download_model(args.download_model))
    elif args.process:
        from .storage import Session
        from .transcription import process_session

        session = Session.load(args.process)
        session.recover()
        if not (session.folder / "audio.wav").exists():
            session.finalize_audio()
        print(process_session(session, args.model, print, embed_images=args.embed_images))
    elif args.export:
        from .export import export_markdown
        from .storage import Session

        print(export_markdown(Session.load(args.export), embed_images=args.embed_images))
    elif sys.platform != "win32":
        parser.error(
            "The capture UI requires Windows 10/11. Export and transcription can run independently."
        )
    else:
        from .ui import run

        return run()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
