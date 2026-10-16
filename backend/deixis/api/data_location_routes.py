"""Settings → This computer → Data location (D32): where the library lives, its size, and a change for the next start.

Nothing here moves a file. A change writes the pointer file; `deixis serve` moves the library at its next start.
"""

from __future__ import annotations

import asyncio
import os
import subprocess
import sys
from pathlib import Path
from typing import Any

from fastapi import HTTPException, Request
from pydantic import BaseModel, Field

from deixis import config
from deixis.storage import data_location
from deixis.tools.child_env import child_env
from deixis.config import Settings
from deixis.storage import backup

LAST_BACKUP_SETTING = "last_backup"

ACTIVE_RUN_STATUSES = ("queued", "running", "pause_requested")
CHOOSE_PROMPT = "Choose where DEIXIS keeps its library"


class LeftoverDelete(BaseModel):
    path: str = Field(min_length=1, max_length=4096)  # one of the folders the list offered, never an arbitrary path


class LocationChange(BaseModel):
    path: str = Field(min_length=1, max_length=4096)
    check: bool = False  # validate and say whether the folder already holds a library; write nothing


def _inside(child: Path, parent: Path) -> bool:
    return child == parent or parent in child.parents


def register_data_location_routes(app, settings: Settings) -> None:
    current = settings.data_dir

    def running_runs(request: Request) -> int:
        marks = ",".join("?" * len(ACTIVE_RUN_STATUSES))
        return request.app.state.store.conn.execute(
            f"SELECT COUNT(*) FROM runs WHERE status IN ({marks})", ACTIVE_RUN_STATUSES).fetchone()[0]

    async def view(request: Request) -> dict[str, Any]:
        outside = data_location.set_outside_app()
        try:
            pointer = None if outside else data_location.pointer_path()
        except data_location.PointerDamaged:  # damaged while running; the next start stops and names it (E23)
            pointer = None
        pending = pointer if pointer is not None and pointer != current else None
        sizes = await asyncio.to_thread(data_location.usage, current)
        return {"path": str(current), "is_default": current == config.platform_data_dir(), "set_outside_app": outside,
                "pending_path": str(pending) if pending else None,
                "pending_has_library": bool(pending and (pending / "library.sqlite").exists()),
                # The move this start postponed because another process held a folder (E1): {path, busy}, else None.
                "move_postponed": postponed if (postponed := getattr(request.app.state, "move_postponed", None))
                and pending and postponed["path"] == str(pending) else None,
                # Windows: old folders whose copies a move left on disk (never deleted by DEIXIS on its own): [{path, size_bytes}].
                "leftovers": [r for r in await asyncio.to_thread(data_location.leftovers) if Path(r["path"]) != current],
                **sizes, "running_runs": running_runs(request), "last_backup": request.app.state.store.setting(LAST_BACKUP_SETTING),
                "cache_bytes": await asyncio.to_thread(data_location.cache_size, current)}

    def installing(request: Request) -> bool:
        state = request.app.state
        builtin, equations = getattr(state, "builtin", None), getattr(state, "equations", None)
        job = getattr(builtin, "job", None) if builtin is not None else None
        return bool(job and job.get("status") == "running") or bool(equations and equations.installing())

    @app.get("/api/settings/data-location")
    async def get_data_location(request: Request) -> dict[str, Any]:
        return await view(request)

    @app.post("/api/settings/data-location")
    async def change_data_location(body: LocationChange, request: Request) -> dict[str, Any]:
        if data_location.set_outside_app():
            raise HTTPException(409, "This location is set outside the app.")
        raw = os.path.expanduser(body.path.strip())
        if not os.path.isabs(raw):
            raise HTTPException(422, "Give the full path of a folder.")
        target = Path(os.path.normpath(raw))
        if target == current:
            if not body.check:
                data_location.write_pointer(current, None)  # cancels a pending change
            return {"path": str(target), "has_library": True} if body.check else await view(request)
        if (count := running_runs(request)):
            raise HTTPException(409, f"{count} research run(s) still running. Finish or stop them before changing location.")
        resolved_target, resolved_current = target.resolve(), current.resolve()
        if _inside(resolved_target, resolved_current) or _inside(resolved_current, resolved_target):
            raise HTTPException(422, "Choose a folder that is neither inside the current location nor contains it.")
        if problem := await asyncio.to_thread(data_location.target_problem, target, current):
            raise HTTPException(422, f"That folder {problem}.")
        has_library = (target / "library.sqlite").exists()
        if body.check:
            return {"path": str(target), "has_library": has_library, "sync_service": data_location.sync_service(target),
                    # True when this computer could not tell whether the folder is on a network drive (the library does not work on one)
                    "network_unchecked": await asyncio.to_thread(data_location.network_unchecked, target)}
        data_location.write_pointer(target, current)
        return await view(request)

    @app.post("/api/settings/data-location/delete-old-copy")
    async def delete_old_copy(body: LeftoverDelete, request: Request) -> dict[str, Any]:
        """Deletes an old copy a move left behind, only when nothing uses its folder and every file is still the one that was copied."""
        if reason := await asyncio.to_thread(data_location.delete_leftover, body.path, current):
            raise HTTPException(409, f"The old copy was kept. {reason}")
        return await view(request)

    @app.post("/api/settings/data/backup")
    async def back_up(request: Request) -> dict[str, Any]:
        """A consistent copy of the library and the files it references (`deixis backup`), in Documents/DEIXIS backups."""
        destination = data_location.backup_dir()
        try:
            await asyncio.to_thread(destination.mkdir, parents=True, exist_ok=True)
            target = await asyncio.to_thread(backup.create_backup, settings, destination)
        except (backup.BackupError, OSError) as exc:
            raise HTTPException(409, f"The backup was not written: {exc}") from exc
        request.app.state.store.set_setting(LAST_BACKUP_SETTING, {"path": str(target), "at": data_location.now_iso()})
        return await view(request)

    @app.post("/api/settings/data/backup/reveal")
    async def reveal_backup(request: Request) -> dict[str, Any]:
        """Shows the last backup in Finder; only that folder, never a path the page names."""
        last = request.app.state.store.setting(LAST_BACKUP_SETTING)
        if sys.platform != "darwin":
            raise HTTPException(501, "No file browser to open on this system")
        if not last or not Path(last["path"]).exists():
            raise HTTPException(404, "The last backup is no longer there")
        await asyncio.to_thread(subprocess.run, ["open", "-R", last["path"]], capture_output=True, env=child_env())
        return {"path": last["path"]}

    @app.post("/api/settings/data/clear-cache")
    async def clear_cache(request: Request) -> dict[str, Any]:
        """Removes the download cache of the tool installs; an install downloads what it needs again."""
        if installing(request):
            raise HTTPException(409, "A tool is being installed. Clear the cache after it finishes.")
        await asyncio.to_thread(data_location.clear_cache, current)
        return await view(request)

    @app.post("/api/settings/data-location/choose")
    async def choose_data_location() -> dict[str, Any]:
        """The macOS folder chooser; elsewhere 501 and the page shows a path field instead."""
        if sys.platform != "darwin":
            raise HTTPException(501, "No folder chooser on this system")
        script = f'POSIX path of (choose folder with prompt "{CHOOSE_PROMPT}")'
        result = await asyncio.to_thread(subprocess.run, ["osascript", "-e", script], capture_output=True, text=True,
                                       env=child_env())
        if result.returncode != 0:  # 1 with error -128: the person cancelled
            if "-128" in result.stderr or result.returncode == 1:
                return {"path": None}
            raise HTTPException(502, "The folder chooser did not open")
        path = result.stdout.strip()
        return {"path": path.rstrip("/") or "/" if path else None}
