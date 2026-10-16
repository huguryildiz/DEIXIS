"""Where the library lives (D32): a pointer file in the platform default folder names the folder chosen in Settings.

A change takes effect at the next start; the open SQLite library is never moved while DEIXIS runs. When the pointer
carries `move_from`, `apply_pending_move` moves the old folder's entries into the new one before anything opens them,
holding both folders' exclusive locks (`library_lock`, E1). The pointer records the move's phase before each step that
changes a folder (E22), so a start after an interruption finishes the step that was cut short.
"""

from __future__ import annotations

import errno
import json
import ntpath
import os
import re
import shutil
import subprocess
import sys
import uuid
from dataclasses import dataclass
from pathlib import Path

from deixis import config, library_lock

POINTER_NAME = "location.json"
# Entries of the old folder that stay where they are: the pointer itself (it lives in the platform default folder), the
# worker lock of the process that last ran there and the folder lock.
NOT_MOVED = {POINTER_NAME, "worker.lock", library_lock.LOCK_NAME}
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


class PointerDamaged(Exception):
    """The pointer exists but names no folder (E23): DEIXIS stops instead of opening an empty default library."""


def _damaged(text: str, why: str) -> PointerDamaged:
    named = re.search(r'"path"\s*:\s*"((?:[^"\\]|\\.)*)', text)
    last = (f"It last named {named.group(1)}." if named and named.group(1)
            else f"Its contents: {text[:200]!r}." if text.strip() else "It is empty.")
    return PointerDamaged(f"The file {pointer_file()} that records where your library is {why}, so DEIXIS did not open an "
                          f"empty library in its place. {last} Correct that file, or delete it to use "
                          f"{config.platform_data_dir()}, then start DEIXIS again.")


def read_pointer() -> dict | None:
    """The pointer, or None when there is none; raises PointerDamaged when it cannot be read or names no folder."""
    try:
        text = pointer_file().read_text(encoding="utf-8")
    except FileNotFoundError:
        return None
    except (OSError, ValueError) as exc:
        raise _damaged("", f"cannot be read ({type(exc).__name__})") from exc
    try:
        data = json.loads(text)
    except ValueError:
        data = None
    if not isinstance(data, dict) or not isinstance(data.get("path"), str) or not os.path.isabs(data["path"]):
        raise _damaged(text, "is damaged")
    return data


def pointer_path() -> Path | None:
    data = read_pointer()
    return Path(data["path"]) if data else None


def write_pointer(path: Path, move_from: Path | None, moved: list[str] | None = None, phase: str | None = None,
                  placing: str | None = None) -> None:
    target = pointer_file()
    if path == config.platform_data_dir() and move_from is None:
        target.unlink(missing_ok=True)
        return
    target.parent.mkdir(parents=True, exist_ok=True)
    data = ({"path": str(path)} | ({"move_from": str(move_from)} if move_from is not None else {}) | ({"moved": moved} if moved else {})
            | ({"phase": phase} if phase else {}) | ({"placing": placing} if placing else {}))
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


# Filesystem types of network drives (macOS `mount`, Linux /proc/self/mounts): SQLite's WAL mode, which the library
# uses, needs shared memory between processes on one machine and does not work on them.
NETWORK_FILESYSTEMS = {"smbfs", "afpfs", "nfs", "nfs4", "cifs", "smb3", "smb2", "webdav", "davfs", "fuse.sshfs",
                       "sshfs", "osxfuse_sshfs", "9p", "ncpfs", "afs", "ceph", "glusterfs", "fuse.glusterfs", "fuse.rclone"}
SPACE_MARGIN = 256 * 1024 * 1024  # room left on the target disk after a copy


def _existing(path: Path) -> Path:
    while not path.exists() and path != path.parent:
        path = path.parent
    return path


def _mounts() -> list[tuple[str, str]]:
    """(mount point, filesystem type) of every mounted filesystem; empty when the table cannot be read."""
    try:
        if sys.platform == "darwin":
            out = subprocess.run(["/sbin/mount"], capture_output=True, text=True, timeout=10).stdout
            return [(m.group(1), m.group(2)) for line in out.splitlines() if (m := re.match(r"^.+? on (.+) \(([^,)]+)", line))]
        with open("/proc/self/mounts", encoding="utf-8") as table:
            return [(fields[1].replace("\\040", " "), fields[2]) for line in table if len(fields := line.split()) >= 3]
    except (OSError, subprocess.SubprocessError):
        return []


def _drive_type(root: str) -> int:
    import ctypes

    return ctypes.windll.kernel32.GetDriveTypeW(root)  # type: ignore[attr-defined]


def network_drive(path: Path) -> str | None:
    """What kind of network drive holds `path`, or None for a local disk (or when it cannot be told)."""
    if sys.platform == "win32":
        text = str(path)
        if text.startswith(("\\\\", "//")):
            return "network share"
        drive = ntpath.splitdrive(text)[0]
        return "mapped network drive" if drive and _drive_type(drive + "\\") == 4 else None  # 4: DRIVE_REMOTE
    resolved = _existing(path).resolve()
    best = None
    for mount, fstype in _mounts():
        point = Path(mount)
        if (point == resolved or point in resolved.parents) and (best is None or len(mount) > len(best[0])):
            best = (mount, fstype)
    return best[1] if best and best[1].lower() in NETWORK_FILESYSTEMS else None


def _sync_roots() -> list[tuple[Path, str]]:
    home = Path.home()
    roots = [(home / "Library" / "Mobile Documents", "iCloud Drive"), (home / "iCloudDrive", "iCloud Drive"),
             (home / "Dropbox", "Dropbox"), (home / "Google Drive", "Google Drive")]
    roots += [(Path(os.environ[name]), "OneDrive") for name in ("OneDrive", "OneDriveConsumer", "OneDriveCommercial")
              if os.environ.get(name)]
    try:
        roots += [(entry, "OneDrive") for entry in home.iterdir() if entry.name.startswith("OneDrive")]
        cloud = home / "Library" / "CloudStorage"  # macOS File Provider folders: OneDrive-…, Dropbox, GoogleDrive-…, Box-…
        if cloud.is_dir():
            names = {"OneDrive": "OneDrive", "Dropbox": "Dropbox", "GoogleDrive": "Google Drive", "Box": "Box", "iCloud": "iCloud Drive"}
            roots += [(entry, next((v for k, v in names.items() if entry.name.startswith(k)), entry.name.split("-")[0]))
                      for entry in cloud.iterdir()]
    except OSError:
        pass
    return roots


def sync_service(path: Path) -> str | None:
    """The cloud sync service whose known local folder holds `path`, or None. A warning only: a folder not found here
    may still be synced, and one found here is no promise that the library is safe there."""
    absolute = Path(os.path.abspath(path))
    for root, name in _sync_roots():
        if absolute == root or root in absolute.parents:
            return name
    return None


def _bytes(n: int) -> str:
    return f"{n / 1e9:.1f} GB" if n >= 1e9 else f"{max(1, round(n / 1e6))} MB"


def _same_disk(a: Path, b: Path) -> bool:
    return os.stat(a).st_dev == os.stat(b).st_dev


def target_problem(path: Path, current: Path) -> str | None:
    """Why `path` cannot receive the library now in `current`, or None (E21). Writes and deletes one probe file in the
    folder (or the nearest existing folder above it); creates nothing else."""
    if problem := data_dir_problem(path):
        return problem
    existing = _existing(path)
    if kind := network_drive(path):
        return f"is on a network drive ({kind}); the library database does not work on network drives"
    probe = existing / f".deixis-probe-{uuid.uuid4().hex}"
    try:
        probe.write_bytes(b"DEIXIS")
        probe.unlink()
    except OSError:
        return "is not writable" if existing == path else f"cannot be created because {existing} is not writable"
    try:
        if not _same_disk(existing, current):  # another disk: the library is copied, not renamed
            needed = sum(_size(str(e)) for e in current.iterdir() if e.name not in NOT_MOVED) + SPACE_MARGIN
            if (free := shutil.disk_usage(existing).free) < needed:
                return f"has {_bytes(free)} free; the library needs about {_bytes(needed)}"
    except OSError:
        pass
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


@dataclass(frozen=True)
class Postponed:
    """A move that did not start because another process holds one of the two folders (E1); nothing moved."""

    old: Path
    new: Path
    busy: Path

    def message(self) -> str:
        return (f"The library was not moved to {self.new}: another DEIXIS, a tool install or an equation reading is using "
                f"{self.busy}. DEIXIS opens {self.old} for now; close the other one and start DEIXIS again to finish the move.")


def apply_pending_move(data_dir: Path) -> str | Postponed | None:
    """Finish a change of location recorded in Settings; returns one sentence when DEIXIS must not start, or Postponed
    when the move waits for another process to let go of a folder.

    A new folder that already holds a library is opened as it is and the old folder is left untouched (never merged).
    Otherwise every entry moves, the database last: a rename on the same disk, else a copy under a temporary name that
    is renamed into place. The pointer says the move started (`phase`), which entry is being put in place (`placing`)
    and which copies are in place (`moved`) before each of those steps, then that only the tool links are left; a
    failure leaves the pointer in place and the next start finishes the move."""
    if set_outside_app() or (data := read_pointer()) is None or not data.get("move_from"):
        return None
    if Path(data["path"]) != data_dir:
        return None
    old, phase = Path(data["move_from"]), data.get("phase")
    if old == data_dir or not old.is_dir():
        if phase and (data_dir / "tools").is_dir():
            _relink(data_dir / "tools", old, data_dir)
        write_pointer(data_dir, None)
        return None
    if problem := (data_dir_problem(data_dir) if phase else target_problem(data_dir, old)):
        return f"Cannot move the library to {data_dir}: it {problem}. Choose another folder in Settings from the old location."
    data_dir.mkdir(parents=True, exist_ok=True)
    try:
        with library_lock.exclusive(old, data_dir):  # source first, then target; neither waits
            return _move(data, old, data_dir)
    except library_lock.Busy as busy:
        if phase:  # half moved: neither folder can be opened on its own
            return (f"Moving the library from {old} to {data_dir} is half done, and another DEIXIS, a tool install or an "
                    f"equation reading is using {busy.folder}. Close it, then start DEIXIS again to finish the move.")
        return Postponed(old, data_dir, busy.folder)


def _move(data: dict, old: Path, data_dir: Path) -> str | None:
    phase = data.get("phase")
    if phase is None and (data_dir / "library.sqlite").exists():
        write_pointer(data_dir, None)
        return None
    moved = [name for name in data.get("moved", []) if isinstance(name, str)]
    try:
        if phase != "relinking":
            placing = data.get("placing")
            if (isinstance(placing, str) and placing not in moved and not (data_dir / (MOVING_PREFIX + placing)).exists()
                    and ((data_dir / placing).exists() or (data_dir / placing).is_symlink())):
                moved.append(placing)  # put in place before the interruption; only the deletion of the original was left
            for leftover in data_dir.glob(MOVING_PREFIX + "*"):  # a copy an interrupted move left half done; the original is still in `old`
                _remove(leftover)
            for name in moved:  # copied in full before the interruption; only the deletion of the original was left
                if (old / name).exists() or (old / name).is_symlink():
                    _remove(old / name)
            entries = [e for e in old.iterdir() if e.name not in NOT_MOVED and e.name not in moved]
            entries.sort(key=lambda e: (DATABASE_FILES.index(e.name) + 1 if e.name in DATABASE_FILES else 0, e.name))
            if clash := next((e.name for e in entries if (data_dir / e.name).exists() or (data_dir / e.name).is_symlink()), None):
                return f"Cannot move the library to {data_dir}: that folder already has {clash}. Move or rename it, then start DEIXIS again."
            if phase is None:
                write_pointer(data_dir, old, moved, phase="moving")  # before the first entry moves (E22)
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
                write_pointer(data_dir, old, moved, phase="moving", placing=entry.name)  # before the copy takes its name
                os.replace(staged, final)
                moved.append(entry.name)
                write_pointer(data_dir, old, moved, phase="moving")  # recorded before the original is deleted, so a retry never deletes the copy
                _remove(entry)
            write_pointer(data_dir, old, moved, phase="relinking")
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
