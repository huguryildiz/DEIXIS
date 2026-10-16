"""Figure and equation reads of a stored PDF in the bounded child process text extraction uses (`pdf._run_watched`).

These reads (figure regions and their pictures, the pages worth reading for equations, the equation regions, the arXiv
stamp) call MuPDF over up to 400 pages of a downloaded PDF. In the server process one such C call holds the interpreter
lock for as long as it runs, so the API stalls, and nothing stops it growing: a 938-byte PDF with one 5000 pt page and a
captioned rectangle took 6.6 s and 655 MB to render as a figure. Each read now runs in a child limited in time and memory
like `extract_pdf`'s, watched from the parent; a child that passes a limit, crashes or fails raises `ChildFailed`, which
callers treat as they treat a PDF MuPDF cannot read.

Only the reads named in `CALLS` run here. Arguments go as JSON in a temporary file (a page-keyed equation list can be
longer than a command line may be), results as JSON on stdout; bytes (a rendered picture) as base64.
At most `MAX_CHILDREN` of these children run at once in the process (each may hold up to 1 GiB); a further read waits for
one to end. `extract_pdf`, OCR and the arXiv source child are not counted.
"""

from __future__ import annotations

import base64
import importlib
import json
import logging
import subprocess
import sys
import tempfile
import threading
from pathlib import Path
from typing import Any

from deixis.child_env import child_env
from deixis.documents import child_guard, pdf

log = logging.getLogger("deixis.pdf")
TIMEOUT_SECONDS = pdf.TIMEOUT_SECONDS
MAX_MEMORY_BYTES = pdf.MAX_MEMORY_BYTES
# name -> (module, in-process function); the child runs nothing else.
CALLS = {
    "find_figures": ("deixis.documents.figures", "_find_figures"),
    "find_algorithms": ("deixis.documents.figures", "_find_algorithms"),
    "render_figure": ("deixis.documents.figures", "_render_figure"),
    "math_pages": ("deixis.documents.math_reader", "_math_pages"),
    "table_pages": ("deixis.documents.math_reader", "_table_pages"),
    "check_equations": ("deixis.documents.math_reader", "_check_equations"),
    "inline_math_marks": ("deixis.documents.math_reader", "_inline_math_marks"),
    "render_crop": ("deixis.documents.equation_regions", "_render_crop"),
    "detect": ("deixis.documents.equation_regions", "_detect"),
    "stamp_key": ("deixis.documents.arxiv_source", "_stamp_key"),
}
BYTES = "__bytes__"
MAX_CHILDREN = 2
_slots = threading.BoundedSemaphore(MAX_CHILDREN)  # callers run in worker threads (asyncio.to_thread), not on the loop


class ChildFailed(Exception):
    """The read did not finish in its child: a limit was passed, the child crashed, or MuPDF failed on the PDF."""


def _encode(value: Any) -> Any:
    if isinstance(value, bytes):
        return {BYTES: base64.b64encode(value).decode("ascii")}
    raise TypeError(f"{type(value).__name__} is not JSON serializable")


def _decode(item: dict) -> Any:
    return base64.b64decode(item[BYTES]) if item.keys() == {BYTES} else item


def run(name: str, *args: Any) -> Any:
    """`CALLS[name]` on `args` in a bounded child; its result, or ChildFailed."""
    request = tempfile.NamedTemporaryFile("w", suffix=".json", delete=False, encoding="utf-8")
    argv = [sys.executable, "-m", "deixis.documents.pdf_child", name, request.name, str(MAX_MEMORY_BYTES)]
    try:
        with request:
            json.dump(args, request)
        with _slots:
            completed = pdf._run_watched(argv, child_env({"PYTHONPATH": str(Path(__file__).resolve().parents[2])}, bundled=True),
                                         TIMEOUT_SECONDS, MAX_MEMORY_BYTES)
    except subprocess.TimeoutExpired:
        raise ChildFailed(f"{name} timed out") from None
    except pdf.MemoryWatchLost:
        raise ChildFailed(f"{name} memory limit could not be watched") from None
    finally:
        Path(request.name).unlink(missing_ok=True)
    if completed.returncode == pdf.MEMORY_EXIT_CODE:
        raise ChildFailed(f"{name} exceeded the memory limit")
    if completed.returncode == child_guard.GUARD_EXIT_CODE:
        raise ChildFailed(f"{name} memory limit could not be watched")
    if completed.returncode != 0:
        log.warning("PDF child %s exited %s: %s", name, completed.returncode, completed.stderr.decode(errors="replace")[-400:])
        raise ChildFailed(f"{name} child exited {completed.returncode}")
    try:
        out = json.loads(completed.stdout, object_hook=_decode)
    except ValueError:
        raise ChildFailed(f"{name} child output was not JSON") from None
    if "error" in out:
        raise ChildFailed(f"{name}: {out['error']}")
    return out["result"]


if __name__ == "__main__":
    import pymupdf

    # A malformed file must not flood the parent with MuPDF messages.
    pymupdf.TOOLS.mupdf_display_errors(False)
    pymupdf.TOOLS.mupdf_display_warnings(False)
    pdf._watch_memory(int(sys.argv[3]))
    module, function = CALLS[sys.argv[1]]
    try:
        out = {"result": getattr(importlib.import_module(module), function)(*json.loads(Path(sys.argv[2]).read_text(encoding="utf-8")))}
    except MemoryError:
        sys.exit(pdf.MEMORY_EXIT_CODE)
    except Exception as exc:  # noqa: BLE001 - untrusted input: any failure is an unreadable PDF, reported to the parent
        out = {"error": type(exc).__name__}
    json.dump(out, sys.stdout, default=_encode)
