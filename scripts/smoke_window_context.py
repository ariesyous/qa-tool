"""Read real Windows metadata and export a test widget; no microphone or desktop capture."""

import json
from pathlib import Path

from PySide6.QtWidgets import QApplication, QLabel

from qa_narrator.export import export_markdown
from qa_narrator.storage import Session, atomic_json
from qa_narrator.windows import enable_dpi_awareness, window_context


def main():
    enable_dpi_awareness()
    app = QApplication([])
    title = "QA context fixture — Settings [test] *preview*"
    window = QLabel("Screenshot context smoke test\nNo microphone or desktop capture.")
    window.setWindowTitle(title)
    window.resize(550, 150)
    window.show()
    try:
        app.processEvents()
        context = window_context(int(window.winId()))
        assert context["title"] == title, context
        assert context["app"].lower() == "python.exe", context
        root = Path(".validation/window-context-native").resolve()
        session = Session.create(root, 16000, "Metadata fixture (no audio)")
        session.update(status="stopped", duration=0)
        assert window.grab().save(str(session.folder / "screenshots/001.png"))
        session.event({
            "kind": "screenshot", "number": 1, "path": "screenshots/001.png", "t": 0,
            "mode": "monitor", "window_context": context,
        })
        atomic_json(session.folder / "transcription.json", {"segments": []})
        for embedded in (False, True):
            path = export_markdown(session, embed_images=embedded)
            text = path.read_text(encoding="utf-8")
            assert "Focused window: python\\.exe" in text
            assert r"Settings \[test\] \*preview\*" in text
        print(json.dumps({"native_window_context": context, "export": str(path)}))
    finally:
        window.close()
        app.processEvents()


if __name__ == "__main__":
    main()
