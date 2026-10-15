"""Package an already-built, versioned Windows release and verify its contents."""

import hashlib
import shutil
import zipfile
from pathlib import Path

from PyInstaller.archive.readers import CArchiveReader

from qa_narrator import __version__


def main():
    root = Path(__file__).resolve().parents[1]
    release = root / "dist" / f"v{__version__}"
    app = release / "QANarrator"
    exe = app / "QANarrator.exe"
    archive = release / f"QANarrator-v{__version__}-windows-x64.zip"
    if not exe.is_file() or not (app / "_internal").is_dir():
        raise FileNotFoundError(f"Build the complete application in {release} first")
    namespace = {}
    code = CArchiveReader(str(exe)).open_embedded_archive("PYZ.pyz").extract("qa_narrator")
    exec(code, namespace)
    if namespace.get("__version__") != __version__:
        raise ValueError("The built executable version does not match the source version")
    for name in ("README.md", "CHANGELOG.md", "LICENSE", "VALIDATION.md"):
        shutil.copyfile(root / name, app / name)
    shutil.copytree(root / "docs" / "screenshots", app / "docs" / "screenshots", dirs_exist_ok=True)
    files = sorted(path for path in app.rglob("*") if path.is_file())
    expected = {path.relative_to(release).as_posix() for path in files}
    if not any("license" in name.lower() and "/_internal/" in name for name in expected):
        raise ValueError("Bundled dependency licenses are missing")
    # Never silently replace an existing release archive.
    with zipfile.ZipFile(archive, "x", zipfile.ZIP_DEFLATED, compresslevel=6) as output:
        for path in files:
            output.write(path, path.relative_to(release).as_posix())
    with zipfile.ZipFile(archive) as output:
        if set(output.namelist()) != expected or output.testzip() is not None:
            raise ValueError("Release ZIP failed its content or CRC check")
    with archive.open("rb") as source:
        checksum = hashlib.file_digest(source, "sha256").hexdigest()
    (release / "SHA256SUMS.txt").write_text(f"{checksum}  {archive.name}\n", encoding="ascii")
    print(f"Validated {len(files)} files; ZIP size: {archive.stat().st_size:,} bytes")
    print(f"SHA256: {checksum}")
    print(archive)


if __name__ == "__main__":
    main()
