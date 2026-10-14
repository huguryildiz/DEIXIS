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

from deixis import config, data_location
from deixis.config import Settings

ACTIVE_RUN_STATUSES = ("queued", "running", "pause_requested")
CHOOSE_PROMPT = "Choose where DEIXIS keeps its library"


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
        pointer = None if outside else data_location.pointer_path()
        pending = pointer if pointer is not None and pointer != current else None
        sizes = await asyncio.to_thread(data_location.usage, current)
        return {"path": str(current), "is_default": current == config.platform_data_dir(), "set_outside_app": outside,
                "pending_path": str(pending) if pending else None,
                "pending_has_library": bool(pending and (pending / "library.sqlite").exists()),
                **sizes, "running_runs": running_runs(request)}

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
        if problem := data_location.data_dir_problem(target):
            raise HTTPException(422, f"That folder {problem}.")
        has_library = (target / "library.sqlite").exists()
        if body.check:
            return {"path": str(target), "has_library": has_library}
        data_location.write_pointer(target, current)
        return await view(request)

    @app.post("/api/settings/data-location/choose")
    async def choose_data_location() -> dict[str, Any]:
        """The macOS folder chooser; elsewhere 501 and the page shows a path field instead."""
        if sys.platform != "darwin":
            raise HTTPException(501, "No folder chooser on this system")
        script = f'POSIX path of (choose folder with prompt "{CHOOSE_PROMPT}")'
        result = await asyncio.to_thread(subprocess.run, ["osascript", "-e", script], capture_output=True, text=True)
        if result.returncode != 0:  # 1 with error -128: the person cancelled
            if "-128" in result.stderr or result.returncode == 1:
                return {"path": None}
            raise HTTPException(502, "The folder chooser did not open")
        path = result.stdout.strip()
        return {"path": path.rstrip("/") or "/" if path else None}
