"""Writing a downloaded PDF into the papers folder without ever leaving a torn file under its final name (P9 H2, F02).

A file named `<sha256>.pdf` is trusted by its name: the next run finds it, skips the download's write and reads it. A write
that a crash cuts must therefore never happen on that name. The bytes go to a unique temporary file in the same folder
and `os.replace` moves it into place, so the final name holds either the whole file or nothing. Uploads do the same with
a `.partial` file (`api/app.py::store_upload`)."""

from __future__ import annotations

import hashlib
import os
import tempfile
from pathlib import Path


def _file_sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        while block := handle.read(1024 * 1024):
            digest.update(block)
    return digest.hexdigest()


def file_is_whole(path: Path, sha256: str, size: int) -> bool:
    """True when the file under its hash name really is the file the hash names (a torn one, left by an older version, is not)."""
    return path.is_file() and path.stat().st_size == size and _file_sha256(path) == sha256


def store_pdf_file(papers_dir: Path, sha256: str, data: bytes) -> Path:
    path = papers_dir / f"{sha256}.pdf"
    if file_is_whole(path, sha256, len(data)):
        return path
    fd, name = tempfile.mkstemp(dir=papers_dir, suffix=".part")  # unique: two processes on one data directory never share it
    os.close(fd)
    temporary = Path(name)
    try:
        temporary.write_bytes(data)
        os.replace(temporary, path)  # a wrong file already under the final name is replaced
    except BaseException:
        temporary.unlink(missing_ok=True)
        raise
    return path
