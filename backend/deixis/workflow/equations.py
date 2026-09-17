"""Reading the equations of stored PDFs with Marker, in the background and before an answer or a table cell (D52).

A PDF is read once per text extraction and Marker version. The result is a new extraction written under D45's rule, so
older passages stay resolvable. Pages without mathematics are not sent to Marker. A PDF whose current text has OCR pages
(D51) keeps them: its OCR text is rebuilt from the stored passages, and every OCR page is read by Marker too, since OCR
text cannot show whether a page has equations. A PDF without such pages, and a failed read, are recorded as a rejected extraction without passages. A
failed read is tried again automatically up to MAX_ATTEMPTS times, or again on request.
"""

from __future__ import annotations

import asyncio
import json
import logging
import os
import re
import shutil
import subprocess
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Any

from deixis.documents import math_reader, pdf
from deixis.storage.db import new_id, now, transaction
from deixis.workflow.store import RunInProgress, Store

log = logging.getLogger(__name__)
NO_MATH = "no pages with mathematics"
RETRY_SECONDS = 60
MAX_ATTEMPTS = 3  # a failed read is tried again in the background until this many attempts
RETRY_AFTER = timedelta(minutes=10)
INSTALL_TIMEOUT_SECONDS = 60 * 60  # the models are about 3.3 GB
OUTPUT_TAIL_CHARS = 4000
OCR_SUFFIX = re.compile(r"\+ocr-.+?-v\d+(?=\+marker-|$)")
# The PDF Marker is reading now, for views: {"asset_id", "title", "pages", "started_at"}. One reader serves the process.
reading: dict[str, Any] | None = None


def target_version(current: str | None = None) -> str:
    """The version an equation reading of a PDF gets: the current text layer version, its OCR reading if any, then Marker."""
    ocr = OCR_SUFFIX.search(current or "")
    return math_reader.target_version(pdf.EXTRACTION_VERSION + (ocr.group(0) if ocr else ""))


def equation_state(store: Store, asset_id: str) -> dict[str, Any]:
    """read, no_math, failed (with reason and attempts), reading or pending (not read yet)."""
    asset = store.asset(asset_id)
    version = target_version(asset["extraction_version"])
    if asset["extraction_version"] == version:
        row = store.conn.execute("SELECT math_json FROM asset_extractions WHERE asset_id = ? AND outcome = 'current'", (asset_id,)).fetchone()
        to_check = json.loads(row["math_json"] or "{}").get("equations_to_check", []) if row else []
        return {"state": "read", "to_check": sorted({e["page"] for e in to_check}), "equations_to_check": len(to_check)}
    if reading and reading["asset_id"] == asset_id:
        return {"state": "reading", "pages": reading["pages"], "started_at": reading["started_at"]}
    row = store.conn.execute(
        "SELECT rejection_reason, math_json, created_at FROM asset_extractions WHERE asset_id = ? AND extraction_version = ?",
        (asset_id, version)).fetchone()
    if row is None:
        return {"state": "pending"}
    if row["rejection_reason"] == NO_MATH:
        return {"state": "no_math"}
    # A read whose text was not used under D45's rule has no attempt count and is not tried again automatically.
    attempts = json.loads(row["math_json"] or "{}").get("attempts", MAX_ATTEMPTS)
    return {"state": "failed", "reason": row["rejection_reason"], "attempts": attempts, "at": row["created_at"]}


def equations_to_check(store: Store, asset_id: str | None, extraction_version: str | None) -> dict[int, int]:
    """Per page of an extraction, how many display equations did not match the PDF's text layer."""
    row = store.conn.execute("SELECT math_json FROM asset_extractions WHERE asset_id = ? AND extraction_version = ?",
                             (asset_id, extraction_version)).fetchone() if asset_id else None
    counts: dict[int, int] = {}
    for equation in json.loads(row["math_json"] or "{}").get("equations_to_check", []) if row else []:
        counts[equation["page"]] = counts.get(equation["page"], 0) + 1
    return counts


class EquationService:
    def __init__(self, store: Store, reader: math_reader.MathReader, papers_dir: Path):
        self.store, self.reader, self.papers_dir = store, reader, papers_dir
        self._task: asyncio.Task | None = None
        self._lock = asyncio.Lock()
        self._retries: set[asyncio.Task] = set()
        self.job: dict[str, Any] | None = None  # the install job shown in Settings
        self._install: asyncio.Task | None = None
        self._install_proc: asyncio.subprocess.Process | None = None
        self._waiting = 0  # runs and requests waiting for a read; the background reader gives way to them
        self._background_reading = False
        self._preempted = False

    def available(self) -> bool:
        return self.reader.available()

    async def read_asset(self, asset_id: str, run_id: str | None = None, retry: bool = False, background: bool = False) -> dict[str, Any]:
        """Read one PDF's equations and apply them; returns its state. One PDF is read at a time; a caller waits for the
        PDF being read, then finds its own already read if that was the same one. A failed read is read again when asked
        (`retry`) or while it has attempts left. A run or request stops a background read of another PDF, which stays
        pending and is read later. RunInProgress and MathReaderUnavailable propagate."""
        if background:
            return await self._read(asset_id, run_id, retry, background)
        self._waiting += 1
        try:
            if self._background_reading and not (reading and reading["asset_id"] == asset_id):
                self._preempted = True
                await self.reader.close()
            return await self._read(asset_id, run_id, retry, background)
        finally:
            self._waiting -= 1

    async def _read(self, asset_id: str, run_id: str | None, retry: bool, background: bool) -> dict[str, Any]:
        global reading
        async with self._lock:
            state = equation_state(self.store, asset_id)
            attempts = 0
            if state["state"] == "failed" and (retry or state["attempts"] < MAX_ATTEMPTS):
                attempts = state["attempts"]
            elif state["state"] != "pending":
                return state
            if not self.available():
                raise math_reader.MathReaderUnavailable("the equation reader (Marker) is not installed")
            asset = self.store.asset(asset_id)
            version = target_version(asset["extraction_version"])
            path = self.papers_dir / asset["storage_path"]
            base = await asyncio.to_thread(pdf.extract_pdf, path)
            ocr_pages = self._ocr_pages(asset) if OCR_SUFFIX.search(asset["extraction_version"] or "") else {}
            if ocr_pages:
                base.pages = sorted(base.pages + [pdf.PageText(n, None, text, "ocr") for n, text in ocr_pages.items()
                                                  if n not in {p.physical_page for p in base.pages}], key=lambda p: p.physical_page)
                base.status = "succeeded" if len(base.pages) == base.page_count else "partial"
            base.extraction_version = version.removesuffix("+" + math_reader.MATH_VERSION)
            selected = sorted(set(await asyncio.to_thread(math_reader.math_pages, path)) | set(await asyncio.to_thread(math_reader.table_pages, path))
                              | {number - 1 for number in ocr_pages})
            self._forget_failure(asset_id, version)
            if not selected:
                self._record_without_passages(asset, version, NO_MATH, attempts + 1)
                return equation_state(self.store, asset_id)
            title = self.store.conn.execute("SELECT title FROM source_versions WHERE id = ?", (asset["source_version_id"],)).fetchone()
            reading = {"asset_id": asset_id, "title": title[0] if title else None, "pages": len(selected), "started_at": now()}
            self._background_reading, self._preempted = background, False
            try:
                read = await self.reader.read(path, selected)
            except RuntimeError as exc:
                read = None
                if not (background and self._preempted):  # a stopped background read is not a failure
                    self._record_without_passages(asset, version, f"equation reading failed: {exc}"[:400], attempts + 1)
            finally:
                reading, self._background_reading, self._preempted = None, False, False
            if read is None:
                return equation_state(self.store, asset_id)
            # OCR pages have no text layer to check an equation against.
            text_layer = {i: found for i, found in read.equations.items() if i + 1 not in ocr_pages}
            unchecked = await asyncio.to_thread(math_reader.check_equations, path, text_layer)
            extraction = math_reader.merge(base, read.pages, selected, unchecked)
            self.store.reextract_asset(asset_id, extraction, extraction.extraction_version, pdf.chunk_page, allow_run_id=run_id)
            return equation_state(self.store, asset_id)

    def _ocr_pages(self, asset: dict[str, Any]) -> dict[int, str]:
        """The current OCR text of each page, rebuilt from its passages (chunks of one page follow each other)."""
        pages: dict[int, list[str]] = {}
        for row in self.store.conn.execute(
            "SELECT physical_page, text FROM passages WHERE asset_id = ? AND extraction_version = ? AND text_source = 'ocr'"
            " ORDER BY physical_page, rowid", (asset["id"], asset["extraction_version"])):
            pages.setdefault(row[0], []).append(row[1])
        return {number: "\n\n".join(chunks) for number, chunks in pages.items()}

    def _forget_failure(self, asset_id: str, version: str) -> None:
        """A failed attempt has no passages; the next attempt's row takes its place and carries the attempt count."""
        with transaction(self.store.conn):
            self.store.conn.execute("DELETE FROM asset_extractions WHERE asset_id = ? AND extraction_version = ?"
                                    " AND outcome = 'rejected' AND passage_count = 0", (asset_id, version))

    def _record_without_passages(self, asset: dict[str, Any], version: str, reason: str, attempts: int) -> None:
        researches = [r[0] for r in self.store.conn.execute(
            "SELECT research_id FROM corpus_memberships WHERE source_version_id = ?", (asset["source_version_id"],))]
        with transaction(self.store.conn):
            self.store.conn.execute(
                "INSERT OR IGNORE INTO asset_extractions (id, asset_id, extraction_version, status, error, page_count, text_pages,"
                " passage_count, outcome, rejection_reason, created_at, math_json) VALUES (?, ?, ?, ?, NULL, ?, 0, 0, 'rejected', ?, ?, ?)",
                (new_id("ext"), asset["id"], version, asset["extraction_status"], asset["page_count"], reason, now(),
                 json.dumps({"engine": "marker", "attempts": attempts})),
            )
            if reason != NO_MATH:
                for research_id in researches:
                    self.store._event(research_id, "equations_failed", {"asset_id": asset["id"], "source_version_id": asset["source_version_id"],
                                                                        "reason": reason, "attempts": attempts})

    def retry(self, asset_id: str) -> None:
        """Read a PDF's equations again in the background, now."""
        task = asyncio.create_task(self._retry(asset_id))
        self._retries.add(task)
        task.add_done_callback(self._retries.discard)

    async def _retry(self, asset_id: str) -> None:
        try:
            await self.read_asset(asset_id, retry=True)
        except RunInProgress:
            pass  # the background reader applies it once the run ends
        except Exception:  # noqa: BLE001 - reported through the asset's state
            log.exception("equation reading failed for %s", asset_id)

    def next_asset(self) -> str | None:
        """A PDF in use still to read, or whose failed read may be tried again: those of included sources first, then the
        most recently stored. A PDF used by a research with a run in progress waits; its reading could not be applied."""
        retry_before = (datetime.now(timezone.utc) - RETRY_AFTER).isoformat(timespec="milliseconds")
        for row in self.store.conn.execute(
            "SELECT a.id FROM source_assets a WHERE a.removed_at IS NULL AND a.extraction_status IN ('succeeded', 'partial')"
            " AND IFNULL(a.extraction_version, '') NOT LIKE ?"
            " AND NOT EXISTS (SELECT 1 FROM corpus_memberships m JOIN runs r ON r.research_id = m.research_id"
            "  WHERE m.source_version_id = a.source_version_id AND r.status IN ('queued', 'running', 'pause_requested'))"
            " ORDER BY EXISTS (SELECT 1 FROM selections s WHERE s.source_version_id = a.source_version_id AND s.state = 'included') DESC,"
            " a.retrieved_at DESC", ("%+" + math_reader.MATH_VERSION,)
        ):
            state = equation_state(self.store, row[0])
            if state["state"] == "pending" or (state["state"] == "failed" and state["attempts"] < MAX_ATTEMPTS and state["at"] < retry_before):
                return row[0]
        return None

    async def run_forever(self) -> None:
        while True:
            if self._waiting:
                await asyncio.sleep(1)  # a run or request goes first
                continue
            asset_id = self.next_asset() if self.available() and not self.installing() else None
            if asset_id is None:
                await asyncio.sleep(RETRY_SECONDS)
                continue
            try:
                await self.read_asset(asset_id, background=True)
            except RunInProgress:
                await asyncio.sleep(RETRY_SECONDS)  # applied after the run that uses the source ends
            except math_reader.MathReaderUnavailable as exc:
                log.warning("equation reader unavailable: %s", exc)
                await asyncio.sleep(RETRY_SECONDS * 10)
            except Exception:  # noqa: BLE001 - the background reader must keep serving other PDFs
                log.exception("equation reading failed for %s", asset_id)
                await asyncio.sleep(RETRY_SECONDS)

    def start(self) -> None:
        if self._task is None:
            self._task = asyncio.create_task(self.run_forever())

    async def stop(self) -> None:
        if self._task:
            self._task.cancel()
            self._task = None
        for task in (*self._retries, *([self._install] if self._install else [])):
            task.cancel()
        if self._install_proc and self._install_proc.returncode is None:
            self._install_proc.kill()
        await self.reader.close()

    # ---- installing the reader from Settings ---------------------------------------------------
    def installing(self) -> bool:
        return bool(self.job and self.job["status"] == "running")

    async def status(self) -> dict[str, Any]:
        paths = self.reader.paths
        env_size, models_size = await asyncio.gather(asyncio.to_thread(_size, paths.env), asyncio.to_thread(_size, paths.models))
        states: dict[str, int] = {}
        for row in self.store.conn.execute("SELECT id FROM source_assets WHERE removed_at IS NULL AND extraction_status IN ('succeeded', 'partial')"):
            state = equation_state(self.store, row[0])["state"]
            states[state] = states.get(state, 0) + 1
        uv = shutil.which("uv")
        return {"installed": self.available(), "package": math_reader.MARKER_PACKAGE, "path": str(paths.env),
                "size_bytes": env_size + models_size, "models_downloaded": models_size > 0,"disk_free_gb": round(shutil.disk_usage(Path.home()).free / 2**30),
                "install": {"available": bool(uv), "unavailable_reason": None if uv else "uv was not found on this computer's PATH",
                            "url": "https://docs.astral.sh/uv/getting-started/installation/"},
                "job": self.job, "reading": reading, "pdfs": states}

    def install(self) -> dict[str, Any]:
        """Create the Marker environment, then start the reader once so its models download; runs in the background."""
        if self.installing():
            raise ValueError("The equation reader is already being installed")
        if self.available() and _size(self.reader.paths.models) > 0:
            raise ValueError("The equation reader is already installed")
        uv = shutil.which("uv")
        if uv is None:
            raise ValueError("uv was not found on this computer's PATH")
        paths = self.reader.paths
        paths.root.mkdir(parents=True, exist_ok=True)
        steps = [[uv, "venv", "--allow-existing", "--python", math_reader.PYTHON_VERSION, str(paths.env)],
                 [uv, "pip", "install", "--python", str(paths.python), math_reader.MARKER_PACKAGE],
                 [str(paths.python), str(math_reader.RUNNER)]]  # loads (downloads) the models, then exits: stdin is empty
        self.job = {"status": "running", "step": 0, "steps": len(steps), "started_at": now(), "finished_at": None, "output": ""}
        self._install = asyncio.create_task(self._run_install(self.job, steps))
        return self.job

    async def _run_install(self, job: dict[str, Any], steps: list[list[str]]) -> None:
        output = bytearray()
        env = {**os.environ, "MODEL_CACHE_DIR": str(self.reader.paths.models), "PYTHONUNBUFFERED": "1"}
        try:
            async with asyncio.timeout(INSTALL_TIMEOUT_SECONDS):
                for index, argv in enumerate(steps):
                    job["step"] = index + 1
                    self._install_proc = proc = await asyncio.create_subprocess_exec(
                        *argv, stdin=subprocess.DEVNULL, stdout=subprocess.PIPE, stderr=subprocess.STDOUT, env=env)
                    assert proc.stdout is not None
                    async for chunk in proc.stdout:
                        output.extend(chunk)
                        job["output"] = output[-OUTPUT_TAIL_CHARS:].decode("utf-8", "replace")
                    if await proc.wait() != 0:
                        job.update(status="failed", finished_at=now())
                        return
            job.update(status="succeeded", finished_at=now())
        except TimeoutError:
            if self._install_proc:
                self._install_proc.kill()
            job.update(status="failed", finished_at=now(), output=job["output"] + "\nStopped after 60 minutes.")
        except OSError as exc:
            job.update(status="failed", finished_at=now(), output=job["output"] + f"\n{type(exc).__name__}: {exc}")
        finally:
            self._install_proc = None

    def cancel_install(self) -> dict[str, Any]:
        if not self.installing():
            raise ValueError("The equation reader is not being installed")
        if self._install_proc and self._install_proc.returncode is None:
            self._install_proc.kill()
        if self._install:
            self._install.cancel()
        self.job.update(status="cancelled", finished_at=now())
        return self.job

    async def remove(self) -> None:
        """Delete the Marker environment and models. Equations already read stay in the stored text."""
        if self.installing() or reading:
            raise ValueError("The equation reader is busy; remove it when it has finished")
        async with self._lock:
            await self.reader.close()
            await asyncio.to_thread(math_reader.remove_runtime, self.reader.paths)
        self.job = None


def _size(root: Path) -> int:
    total = 0
    for folder, _, files in os.walk(root):
        for name in files:
            try:
                total += os.lstat(os.path.join(folder, name)).st_size
            except OSError:
                pass
    return total
