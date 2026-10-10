"""PyInstaller entry point (absolute import works outside a package)."""
from qa_narrator.__main__ import main

if __name__ == "__main__":
    raise SystemExit(main())

