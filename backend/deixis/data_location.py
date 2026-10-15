"""Where the library lives (D32): a pointer file in the platform default folder names the folder chosen in Settings.

A change takes effect at the next start; the open SQLite library is never moved while DEIXIS runs. When the pointer
carries `move_from`, `apply_pending_move` moves the old folder's entries into the new one before anything opens them.
"""

from __future__ import annotations

import errno
import json
import os
import shutil
from pathlib import Path

from deixis import config

POINTER_NAME = "location.json"
# Entries of the old folder that stay where they are: the pointer itself (it lives in the platform default folder) and
# the worker lock of the process that last ran there.
NOT_MOVED = {POINTER_NAME, "worker.lock"}
DATABASE_FILES = ("library.sqlite-wal", "library.sqlite-shm", "library.sqlite")  # moved last, the database itself at the end
MOVING_PREFIX = ".deixis-moving-"
BREAKDOWN = (
    ("database", "Library database", {"library.sqlite", "library.sqlite-wal", "library.sqlite-shm"}),
    ("pdfs", "PDFs", {"papers"}),
    ("payloads", "Provider responses", {"provider-payloads"}),
    ("tools", "Tools", {"tools", "codex-home", "codex-workspace", "claude-workspace"}),
)


def set_outside_app() -> bool:
    return bool(os.environ.get("DEIXIS_DATA_DIR"))


def pointer_file() -> Path:
    return config.platform_data_dir() / POINTER_NAME


def read_pointer() -> dict | None:
    try:
        data = json.loads(pointer_file().read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return None
    if not isinstance(data, dict) or not isinstance(data.get("path"), str) or not os.path.isabs(data["path"]):
        return None
    return data


def pointer_path() -> Path | None:
    data = read_pointer()
    return Path(data["path"]) if data else None


def write_pointer(path: Path, move_from: Path | None, moved: list[str] | None = None) -> None:
    target = pointer_file()
    if path == config.platform_data_dir() and move_from is None:
        target.unlink(missing_ok=True)
        return
    target.parent.mkdir(parents=True, exist_ok=True)
    data = {"path": str(path)} | ({"move_from": str(move_from)} if move_from is not None else {}) | ({"moved": moved} if moved else {})
    temporary = target.with_name(POINTER_NAME + ".tmp")
    temporary.write_text(json.dumps(data), encoding="utf-8")
    os.replace(temporary, target)


def data_dir_problem(path: Path) -> str | None:
    """Why `path` cannot hold the library, or None. Looks only; creates and writes nothing."""
    existing = path
    try:
        while not existing.exists() and existing != existing.parent:
            existing = existing.parent
    except PermissionError:  # a parent that cannot be searched hides whether the path exists
        return "is not writable"
    if not existing.is_dir():
        return "is not a folder"
    if not os.access(existing, os.W_OK | os.X_OK):
        return "is not writable" if existing == path else f"cannot be created because {existing} is not writable"
    return None


def _relink(root: Path, old: Path, new: Path) -> None:
    """Point symlinks and `pyvenv.cfg` files under `root` that named the old folder at the new one (the tool envs)."""
    before, after = str(old) + os.sep, str(new) + os.sep
    for folder, dirs, files in os.walk(root):
        for name in dirs + files:
            path = os.path.join(folder, name)
            if os.path.islink(path) and (target := os.readlink(path)).startswith(before):
                os.unlink(path)
                os.symlink(after + target[len(before):], path)
            elif name == "pyvenv.cfg" and not os.path.islink(path):
                text = Path(path).read_text(encoding="utf-8")
                if before in text:
                    Path(path).write_text(text.replace(before, after), encoding="utf-8")


def _remove(path: Path) -> None:
    shutil.rmtree(path) if path.is_dir() and not path.is_symlink() else path.unlink()


def apply_pending_move(data_dir: Path) -> str | None:
    """Finish a change of location recorded in Settings; returns one sentence when DEIXIS must not start.

    A new folder that already holds a library is opened as it is and the old folder is left untouched (never merged).
    Otherwise every entry moves, the database last: a rename on the same disk, else a copy under a temporary name that
    is renamed into place and recorded in the pointer before the original is deleted. A failure leaves the pointer in
    place and the next start finishes the move."""
    if set_outside_app() or (data := read_pointer()) is None or not data.get("move_from"):
        return None
    if Path(data["path"]) != data_dir:
        return None
    old = Path(data["move_from"])
    if old == data_dir or not old.is_dir():
        write_pointer(data_dir, None)
        return None
    if problem := data_dir_problem(data_dir):
        return f"Cannot move the library to {data_dir}: it {problem}. Choose another folder in Settings from the old location."
    data_dir.mkdir(parents=True, exist_ok=True)
    if (data_dir / "library.sqlite").exists():
        write_pointer(data_dir, None)
        return None
    moved = [name for name in data.get("moved", []) if isinstance(name, str)]
    try:
        for leftover in data_dir.glob(MOVING_PREFIX + "*"):  # a copy an interrupted move left half done; the original is still in `old`
            _remove(leftover)
        for name in moved:  # copied in full before the interruption; only the deletion of the original was left
            if (old / name).exists() or (old / name).is_symlink():
                _remove(old / name)
        entries = [e for e in old.iterdir() if e.name not in NOT_MOVED and e.name not in moved]
        entries.sort(key=lambda e: (DATABASE_FILES.index(e.name) + 1 if e.name in DATABASE_FILES else 0, e.name))
        if clash := next((e.name for e in entries if (data_dir / e.name).exists() or (data_dir / e.name).is_symlink()), None):
            return f"Cannot move the library to {data_dir}: that folder already has {clash}. Move or rename it, then start DEIXIS again."
        for entry in entries:
            final = data_dir / entry.name
            try:
                os.rename(entry, final)  # same disk: one atomic rename
                continue
            except OSError as exc:
                if exc.errno != errno.EXDEV:
                    raise
            staged = data_dir / (MOVING_PREFIX + entry.name)
            if entry.is_dir() and not entry.is_symlink():
                shutil.copytree(entry, staged, symlinks=True)
            else:
                shutil.copy2(entry, staged, follow_symlinks=False)
            os.replace(staged, final)
            moved.append(entry.name)
            write_pointer(data_dir, old, moved)  # recorded before the original is deleted, so a retry never deletes the copy
            _remove(entry)
        if (data_dir / "tools").is_dir():
            _relink(data_dir / "tools", old, data_dir)
    except OSError as exc:
        return (f"Could not finish moving the library from {old} to {data_dir} ({type(exc).__name__}: {exc}). "
                "Every file is still in one of the two folders; start DEIXIS again to finish the move.")
    write_pointer(data_dir, None)
    return None


def _size(path: str) -> int:
    try:
        if not os.path.isdir(path) or os.path.islink(path):
            return os.lstat(path).st_size
        total = 0
        with os.scandir(path) as it:
            for entry in it:
                total += _size(entry.path) if entry.is_dir(follow_symlinks=False) else entry.stat(follow_symlinks=False).st_size
        return total
    except OSError:
        return 0


def usage(data_dir: Path) -> dict:
    """Bytes per part of the data folder and the free space of its disk. Reads only; run it in a thread."""
    sizes = {key: 0 for key, _, _ in BREAKDOWN} | {"other": 0}
    try:
        names = os.listdir(data_dir)
    except OSError:
        names = []
    for name in names:
        key = next((k for k, _, members in BREAKDOWN if name in members), "other")
        sizes[key] += _size(os.path.join(data_dir, name))
    existing = data_dir
    while not existing.exists() and existing != existing.parent:
        existing = existing.parent
    try:
        free = shutil.disk_usage(existing).free
    except OSError:
        free = None
    labels = {key: label for key, label, _ in BREAKDOWN} | {"other": "Other"}
    return {"size_bytes": sum(sizes.values()), "free_bytes": free,
            "breakdown": [{"key": key, "label": labels[key], "bytes": sizes[key]} for key in labels]}


# The download cache of the tool installs (uv's packages and wheels). Installed tools keep working without it.
CACHE_PARTS = (("tools", "uv-cache"),)


def cache_size(data_dir: Path) -> int:
    return sum(_size(str(data_dir.joinpath(*parts))) for parts in CACHE_PARTS if data_dir.joinpath(*parts).exists())


def clear_cache(data_dir: Path) -> None:
    for parts in CACHE_PARTS:
        folder = data_dir.joinpath(*parts)
        if folder.is_dir() and not folder.is_symlink():
            shutil.rmtree(folder)


def backup_dir() -> Path:
    return Path.home() / "Documents" / "DEIXIS backups"


def now_iso() -> str:
    from datetime import datetime, timezone

    return datetime.now(timezone.utc).isoformat(timespec="seconds")
