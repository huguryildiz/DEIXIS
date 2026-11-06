"""Entry point of the packaged (PyInstaller) backend (P10 M1).

A frozen build has no Python interpreter that understands `-m`: `sys.executable` is this program. The PDF, OCR, JATS
and arXiv extraction children and the child guard are started as `[sys.executable, "-m", "deixis.documents.X", ...]`,
so this entry runs exactly those modules as `__main__` with the arguments the child expects (`sys.argv[1]` is the first
real argument, as under `python -m`). Any other `-m` module is refused. Everything else is the normal `deixis` command
line (`serve`, `hold-folder`, `--check-resources`, ...).

Imports stay minimal before routing: `runpy` would warn about, and run a second copy of, a module already imported.

Windows (P10 W3): the macOS process layer (`desktop_reaper`, `session_launcher`) is refused; there each child's Job
Object owns it (`tools/win_job.py`). PyInstaller's bootloader calls `SetDllDirectoryW(_internal)`, which every child
process inherits, so an outside program (Tesseract, node, a model CLI) would load the bundle's copy of a DLL that shares
a name with its own. First thing, before any thread or child exists, `SetDllDirectoryW(NULL)` undoes it, and the bundle's
folders are registered with `os.add_dll_directory`, which children do not inherit.
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
    "deixis.desktop_reaper",  # the packaged app's watchdog (P10 M2), started by the shell
    "deixis.session_launcher",  # leads each recorded session (P10 M2), see tools/child_record.py
})
EXIT_REFUSED = 2
POSIX_ONLY_MODULES = frozenset({"deixis.desktop_reaper", "deixis.session_launcher"})
_DLL_DIRECTORIES: list = []  # kept: closing one removes its folder from the search


def run_child(module: str, args: list[str]) -> int:
    """Run one allowed child module as `__main__`; refuse any other with exit 2."""
    if module not in CHILD_MODULES or (sys.platform == "win32" and module in POSIX_ONLY_MODULES):
        print(f"deixis-backend: module {module!r} cannot be run in the packaged app", file=sys.stderr)
        return EXIT_REFUSED
    import runpy
    sys.argv = [module, *args]  # run_module(alter_sys=True) replaces argv[0] with the module's file
    runpy.run_module(module, run_name="__main__", alter_sys=True)
    return 0


def reset_dll_search() -> None:
    """Windows, frozen: no DLL directory a child would inherit; the bundle's own folders through add_dll_directory."""
    import ctypes
    import os

    kernel32 = ctypes.WinDLL("kernel32", use_last_error=True)
    kernel32.SetDllDirectoryW.argtypes = (ctypes.c_wchar_p,)
    if not kernel32.SetDllDirectoryW(None):
        raise OSError(f"SetDllDirectoryW(NULL) failed (Windows error {ctypes.get_last_error()})")
    root = sys._MEIPASS
    folders = [root] + sorted(entry.path for entry in os.scandir(root) if entry.is_dir() and any(
        name.lower().endswith(".dll") for name in os.listdir(entry.path)))
    _DLL_DIRECTORIES.extend(os.add_dll_directory(folder) for folder in folders)


def main(argv: list[str] | None = None) -> int:
    argv = sys.argv[1:] if argv is None else argv
    if sys.platform == "win32" and getattr(sys, "frozen", False) and not _DLL_DIRECTORIES:
        reset_dll_search()
    if argv[:1] == ["--check-runtime"]:  # the Windows release smoke's in-process checks (scripts/p10/sidecar_smoke.py)
        from deixis import resource_check
        return resource_check.runtime_main(argv[1:])
    if len(argv) >= 2 and argv[0] == "-m":
        return run_child(argv[1], argv[2:])
    from deixis.__main__ import main as deixis_main
    return deixis_main(argv)


if __name__ == "__main__":
    raise SystemExit(main())
