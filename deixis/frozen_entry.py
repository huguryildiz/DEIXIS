"""Entry point of the packaged (PyInstaller) backend (P10 M1).

A frozen build has no Python interpreter that understands `-m`: `sys.executable` is this program. The PDF, OCR, JATS
and arXiv extraction children and the child guard are started as `[sys.executable, "-m", "deixis.documents.X", ...]`,
so this entry runs exactly those modules as `__main__` with the arguments the child expects (`sys.argv[1]` is the first
real argument, as under `python -m`). Any other `-m` module is refused. Everything else is the normal `deixis` command
line (`serve`, `hold-folder`, `--check-resources`, ...).

Imports stay minimal before routing: `runpy` would warn about, and run a second copy of, a module already imported.
"""

from __future__ import annotations

import sys

CHILD_MODULES = frozenset({
    "deixis.documents.pdf",
    "deixis.documents.pdf_child",
    "deixis.documents.jats",
    "deixis.documents.ocr",
    "deixis.documents.arxiv_source",
    "deixis.documents.child_guard",
})
EXIT_REFUSED = 2


def run_child(module: str, args: list[str]) -> int:
    """Run one allowed child module as `__main__`; refuse any other with exit 2."""
    if module not in CHILD_MODULES:
        print(f"deixis-backend: module {module!r} cannot be run in the packaged app", file=sys.stderr)
        return EXIT_REFUSED
    import runpy
    sys.argv = [module, *args]  # run_module(alter_sys=True) replaces argv[0] with the module's file
    runpy.run_module(module, run_name="__main__", alter_sys=True)
    return 0


def main(argv: list[str] | None = None) -> int:
    argv = sys.argv[1:] if argv is None else argv
    if len(argv) >= 2 and argv[0] == "-m":
        return run_child(argv[1], argv[2:])
    from deixis.__main__ import main as deixis_main
    return deixis_main(argv)


if __name__ == "__main__":
    raise SystemExit(main())
