"""Reading the equations of stored PDFs with Marker, in the background and before an answer or a table cell (D52).

A PDF is read once per text extraction and Marker version. The result is a new extraction written under D45's rule, so
older passages stay resolvable. Pages without mathematics are not sent to Marker. A PDF whose current text has OCR pages
(D51) keeps them: its OCR text is rebuilt from the stored passages, and every OCR page is read by Marker too, since OCR
text cannot show whether a page has equations. A PDF without such pages, and a failed read, are recorded as a rejected extraction without passages. A
failed read is tried again automatically up to MAX_ATTEMPTS times, or again on request.

Without Marker (D104, slice 22): with `DEIXIS_ARXIV_SOURCE=auto` and on POSIX, a PDF that is an arXiv version gets the
numbered display equations of the authors' LaTeX source of that version, matched to the page by their numbers
(`documents/arxiv_source.py`). Target and state follow four precedence rules, first match wins: (1) Marker installed or
installing: today's code, unchanged; (2) no Marker and the current text is a source reading: `read`; (3) no Marker, the
flag `auto`, POSIX and a current text not read by Marker: the source route's states, all from stored rows; (4) otherwise
today's code. No outcome of the route pauses a run.

Mathpix (D40): with its switch on and its key pair saved, a PDF that neither Marker nor the arXiv source reads gets its
numbered display equations read from crops of the page image (`documents/equation_regions.py`, `documents/mathpix.py`)
and labelled `equation_ocr`. Its place in the precedence, first match wins: Marker installed or installing; the current
text a Marker reading; the current text a Mathpix reading (kept: a later arXiv source does not replace it in v1); the
current text a source reading; the arXiv route active and its state for the PDF transient (Mathpix waits); the arXiv
route settled for good, or not active: Mathpix; otherwise today's code. No outcome of Mathpix pauses a run.
"""

from __future__ import annotations

import asyncio
import json
import logging
import os
import re
import shutil
import subprocess
from collections import Counter
from contextlib import nullcontext
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Any

from deixis import library_lock
from deixis.documents import arxiv_source, equation_regions, math_reader, mathpix, pdf
from deixis.storage.db import new_id, now, transaction
from deixis.workflow import file_restore, recovery, text_retry
from deixis.workflow.store import NotFound, RunInProgress, Store

log = logging.getLogger(__name__)
NO_MATH = "no pages with mathematics"
RETRY_SECONDS = 60
MAX_ATTEMPTS = 3  # a failed read is tried again in the background until this many attempts
RETRY_AFTER = timedelta(minutes=10)
INSTALL_TIMEOUT_SECONDS = 60 * 60  # the models are about 3.3 GB
OUTPUT_TAIL_CHARS = 4000
OCR_SUFFIX = re.compile(r"\+ocr-.+?-v\d+(?=\+marker-|\+arxiv-latex-|\+mathpix-|$)")
SOURCE_SUFFIX = "+" + arxiv_source.SOURCE_VERSION
MATHPIX_SUFFIX = "+" + mathpix.VERSION
NO_CANDIDATES = "no_candidates"  # Mathpix: the detector found no numbered display equation (terminal, like NO_MATH)
NONE_PLACED = "none_placed"  # Mathpix: candidates found, every one refused (terminal, reasons kept)
MATHPIX_SWITCH = "mathpix_equations"  # app setting, "on" or "off" (default off); read before every request
MATHPIX_BUDGET = "mathpix_monthly_budget"
DEFAULT_MONTHLY_BUDGET = 500
MAX_ASSET_REQUESTS = 60  # requests one PDF may send across all its attempts
NOTHING_PLACED = "nothing_placed"
OFFSETS_UNRESOLVED = "offsets_unresolved"
RECORD_VERSION_CHANGED = "record_version_changed"
EXTRACTION_FAILED = "extraction_failed"  # the PDF's text layer could not be extracted again with the placements
# The PDF Marker is reading now, for views: {"asset_id", "title", "pages", "started_at"}. One reader serves the process.
reading: dict[str, Any] | None = None


def target_version(current: str | None = None) -> str:
    """The version an equation reading of a PDF gets: the current text layer version, its OCR reading if any, then Marker."""
    ocr = OCR_SUFFIX.search(recovery.profile_of(current or ""))
    return math_reader.target_version(recovery.text_base(current) + (ocr.group(0) if ocr else ""))


def source_target_version(current: str | None) -> str:
    """The version a source reading of a PDF gets: its text layer, its OCR reading if any, then the arXiv source."""
    ocr = OCR_SUFFIX.search(recovery.profile_of(current or ""))
    return recovery.text_base(current) + (ocr.group(0) if ocr else "") + SOURCE_SUFFIX


def mathpix_target_version(current: str | None) -> str:
    """The version a Mathpix reading of a PDF gets: its text layer, its OCR reading if any, then Mathpix."""
    ocr = OCR_SUFFIX.search(recovery.profile_of(current or ""))
    return recovery.text_base(current) + (ocr.group(0) if ocr else "") + MATHPIX_SUFFIX


def mathpix_switch(store: Store) -> bool:
    return store.setting(MATHPIX_SWITCH) == "on"


def mathpix_budget(store: Store) -> int:
    value = store.setting(MATHPIX_BUDGET)
    return value if isinstance(value, int) and not isinstance(value, bool) and value >= 0 else DEFAULT_MONTHLY_BUDGET


# A row counts against the budgets once a request may have reached Mathpix: reserved (sent or about to be), answered,
# unknown (a timeout or a lost connection), or an error Mathpix answered.
COUNTED = "(status IN ('reserved', 'answered', 'unknown') OR (status = 'error' AND http_status IS NOT NULL))"


def mathpix_counts(store: Store, asset_id: str | None = None) -> dict[str, int]:
    """This calendar month's requests (UTC) against the monthly budget, and one PDF's requests over all its attempts."""
    month = now()[:7]
    used = store.conn.execute(f"SELECT COUNT(*) FROM mathpix_requests WHERE substr(reserved_at, 1, 7) = ? AND {COUNTED}",
                              (month,)).fetchone()[0]
    out = {"month": used, "budget": mathpix_budget(store)}
    if asset_id is not None:
        out["asset"] = store.conn.execute(f"SELECT COUNT(*) FROM mathpix_requests WHERE asset_id = ? AND {COUNTED}",
                                          (asset_id,)).fetchone()[0]
    return out


def mathpix_answered(store: Store, asset_id: str) -> bool:
    """Mathpix has answered at least one crop of this PDF: a read that needs no new request can still place something."""
    return store.conn.execute("SELECT 1 FROM mathpix_requests WHERE asset_id = ? AND status = 'answered' LIMIT 1",
                              (asset_id,)).fetchone() is not None


def mathpix_keys_rejected(store: Store, pair: Any = None) -> bool:
    """Mathpix refused the saved pair (401/403) on a request sent with it. Saving the pair again gives a new revision."""
    pair = mathpix.read_pair() if pair is None else pair
    return isinstance(pair, mathpix.Pair) and store.conn.execute(
        "SELECT 1 FROM mathpix_requests WHERE http_status IN (401, 403) AND credential_revision = ? LIMIT 1",
        (pair.revision,)).fetchone() is not None


def source_summary(math: dict[str, Any] | None) -> dict[str, Any] | None:
    """What the equation state says of a source reading: the version and how many equations were placed on which pages."""
    source = (math or {}).get("source")
    if not source:
        return None
    return {"arxiv_id": source.get("arxiv_id"), "version": source.get("version"), "version_from": source.get("version_from"),
            "record_label": source.get("record_label"), "placed": len(source.get("placed", [])),
            "pages": sorted({p["page"] for p in source.get("placed", [])}), "not_placed": source.get("not_placed", {})}


def _placed(store: Store, asset_id: str | None, extraction_version: str | None) -> list[dict[str, Any]]:
    """The placed equations of a source or Mathpix reading, each with page, n, start and end."""
    version = extraction_version or ""
    if not asset_id or not (version.endswith(SOURCE_SUFFIX) or version.endswith(MATHPIX_SUFFIX)):
        return []
    row = store.conn.execute("SELECT math_json FROM asset_extractions WHERE asset_id = ? AND extraction_version = ?",
                             (asset_id, extraction_version)).fetchone()
    math = json.loads(row["math_json"] or "{}") if row else {}
    return (math.get("source") or {}).get("placed", []) if version.endswith(SOURCE_SUFFIX) else math.get("placed", [])


def latex_numbers(store: Store, asset_id: str | None, extraction_version: str | None) -> dict[int, list[tuple[int, int, str]]]:
    """Per page of a source or Mathpix reading, its placed equations as (start, end, number) in the chunk offset space."""
    found: dict[int, list[tuple[int, int, str]]] = {}
    for item in _placed(store, asset_id, extraction_version):
        found.setdefault(item["page"], []).append((item["start"], item["end"], item["n"]))
    return found


def equation_fallbacks(store: Store, passage: dict[str, Any]) -> list[dict[str, str]] | None:
    """For an `equation_ocr` passage, the PDF's own text-layer lines of each Mathpix equation it holds, for comparison in
    model input (never citable); None for every other passage."""
    if passage.get("text_source") != "equation_ocr":
        return None
    m = re.fullmatch(r"chars:(\d+)-(\d+)", passage.get("payload_ref") or "")
    if not m:
        return []
    start, end = int(m.group(1)), int(m.group(2))
    return [{"n": item["n"], "text_layer": item.get("text_layer", "")}
            for item in _placed(store, passage.get("asset_id"), passage.get("extraction_version"))
            if item["page"] == passage.get("physical_page") and start <= item["start"] and item["end"] <= end]


def equation_fallback_field(store: Store, passage: dict[str, Any]) -> dict[str, Any]:
    """The step-input field `equation_fallbacks`, present only on an `equation_ocr` passage."""
    found = equation_fallbacks(store, passage)
    return {} if found is None else {"equation_fallbacks": found}


def mathpix_crop(store: Store, asset_id: str, extraction_version: str, page: int, n: str) -> dict[str, Any] | None:
    """A placed Mathpix equation's provenance (crop recipe and hash included), from its reading."""
    if not extraction_version.endswith(MATHPIX_SUFFIX):
        return None
    return next((item for item in _placed(store, asset_id, extraction_version) if item["page"] == page and item["n"] == n), None)


def chunk_numbers(placed: dict[int, list[tuple[int, int, str]]], page: int | None, payload_ref: str | None) -> list[str]:
    """The source equation numbers a chunk holds: a block lies in the chunk when start ≤ block.start and block.end ≤ end."""
    m = re.fullmatch(r"chars:(\d+)-(\d+)", payload_ref or "")
    if not m or page not in placed:
        return []
    start, end = int(m.group(1)), int(m.group(2))
    return [n for s, e, n in placed[page] if start <= s and e <= end]


def source_chunker(text: str) -> list[tuple[int, int, str]]:
    return pdf.chunk_page(text, keep_display_math=True)


def equation_state(store: Store, asset_id: str) -> dict[str, Any]:
    """read, no_math, failed (with reason and attempts), reading or pending (not read yet); without Marker and with the
    arXiv source route on also no_source (with reason) and source_waiting (D104); on the Mathpix route (D40) also
    no_candidates, none_placed, keys_rejected and budget_reached."""
    asset = store.asset(asset_id)
    service = getattr(store, "equation_route", None)
    current = asset["extraction_version"] or ""
    if service is not None and not service.marker_present():
        if current.endswith(SOURCE_SUFFIX):  # rule 2, whatever the flag says
            row = store.conn.execute("SELECT math_json FROM asset_extractions WHERE asset_id = ? AND outcome = 'current'",
                                     (asset_id,)).fetchone()
            return {"state": "read", "to_check": [], "equations_to_check": 0, "route": arxiv_source.ENGINE,
                    "source": source_summary(json.loads(row["math_json"] or "{}") if row else None)}
        if current.endswith(MATHPIX_SUFFIX):  # kept whatever the switch says; Marker alone supersedes it
            return _mathpix_read(store, asset)
        if "+marker-" not in current:
            mathpix_on = service.mathpix_ready()
            if service.route_flag() and arxiv_source.posix_available():
                source = _source_state(store, asset)  # rule 3
                return _mathpix_state(store, asset) if mathpix_on and _source_settled(source) else source
            if mathpix_on:  # the arXiv route is off, or cannot run here
                return _mathpix_state(store, asset)
            if service.route_flag():
                return {"state": "no_source", "reason": "not_available_on_this_system", "route": arxiv_source.ENGINE}
    return _marker_state(store, asset)  # rules 1 and 4: today's code


def _source_settled(state: dict[str, Any]) -> bool:
    """The arXiv route's state for a PDF is final: it places nothing more without the person's retry. Pending, reading,
    waiting for the source, a failed extraction with attempts left and a stored source being repaired are not final."""
    if state["state"] == "no_source":
        return state.get("reason") != "cache_corrupt"
    if state["state"] == "failed":
        return not (state.get("reason") == EXTRACTION_FAILED and state.get("attempts", MAX_ATTEMPTS) < MAX_ATTEMPTS)
    return False


def _mathpix_read(store: Store, asset: dict[str, Any]) -> dict[str, Any]:
    row = store.conn.execute("SELECT math_json FROM asset_extractions WHERE asset_id = ? AND outcome = 'current'", (asset["id"],)).fetchone()
    math = json.loads(row["math_json"] or "{}") if row else {}
    placed = math.get("placed", [])
    return {"state": "read", "to_check": [], "equations_to_check": 0, "route": mathpix.ENGINE,
            "mathpix": {"placed": len(placed), "pages": sorted({p["page"] for p in placed}),
                        "refused": dict(Counter(r["reason"] for r in math.get("refused", [])))}}


def _mathpix_state(store: Store, asset: dict[str, Any]) -> dict[str, Any]:
    """The Mathpix route's states, from stored rows only (no PDF is opened)."""
    route = {"route": mathpix.ENGINE}
    if reading and reading["asset_id"] == asset["id"] and reading.get("route") == mathpix.ENGINE:
        return {"state": "reading", "pages": reading["pages"], "started_at": reading["started_at"]} | route
    row = store.conn.execute(
        "SELECT rejection_reason, math_json, created_at FROM asset_extractions WHERE asset_id = ? AND extraction_version = ?",
        (asset["id"], mathpix_target_version(asset["extraction_version"]))).fetchone()
    if row is not None:
        math = json.loads(row["math_json"] or "{}")
        if row["rejection_reason"] == NO_CANDIDATES:
            return {"state": "no_candidates"} | route
        if row["rejection_reason"] == NONE_PLACED:
            return {"state": "none_placed", "refused": dict(Counter(r["reason"] for r in math.get("refused", [])))} | route
        # A failed read carries its attempt count; a reading D45 did not take has none and is not tried again by itself.
        return {"state": "failed", "reason": math.get("reason") or row["rejection_reason"],
                "attempts": math.get("attempts", MAX_ATTEMPTS), "at": row["created_at"]} | route
    if mathpix_keys_rejected(store):
        return {"state": "keys_rejected"} | route
    counts = mathpix_counts(store, asset["id"])
    if counts["month"] >= counts["budget"] or counts["asset"] >= MAX_ASSET_REQUESTS:
        # `stored_answers`: a read again would place from Mathpix's saved answers alone, sending nothing (the UI's retry).
        return {"state": "budget_reached", "month": counts["month"], "budget": counts["budget"], "asset": counts["asset"],
                "stored_answers": mathpix_answered(store, asset["id"])} | route
    return {"state": "pending"} | route


def _source_state(store: Store, asset: dict[str, Any]) -> dict[str, Any]:
    """Rule 3's table, from stored rows only (no PDF is opened)."""
    route = {"route": arxiv_source.ENGINE}
    if reading and reading["asset_id"] == asset["id"] and reading.get("route") != mathpix.ENGINE:
        return {"state": "reading", "pages": reading["pages"], "started_at": reading["started_at"]} | route
    target = source_target_version(asset["extraction_version"])
    version = store.conn.execute("SELECT * FROM asset_arxiv_versions WHERE asset_id = ?", (asset["id"],)).fetchone()
    if version is None:
        return {"state": "pending"} | route
    if version["eligibility"] != "eligible":
        return {"state": "no_source", "reason": version["eligibility"]} | route
    extraction = store.conn.execute(
        "SELECT outcome, rejection_reason, created_at, math_json FROM asset_extractions WHERE asset_id = ? AND extraction_version = ?",
        (asset["id"], target)).fetchone()
    if extraction is not None and extraction["rejection_reason"] != RECORD_VERSION_CHANGED:
        if extraction["rejection_reason"] == NOTHING_PLACED:
            return {"state": "no_source", "reason": NOTHING_PLACED} | route
        if extraction["rejection_reason"] == EXTRACTION_FAILED:  # a time or memory limit: tried again like a failed Marker read
            attempts = json.loads(extraction["math_json"] or "{}").get("attempts", MAX_ATTEMPTS)
            return {"state": "failed", "reason": EXTRACTION_FAILED, "attempts": attempts, "at": extraction["created_at"]} | route
        if extraction["outcome"] == "rejected":
            return {"state": "failed", "reason": extraction["rejection_reason"], "at": extraction["created_at"]} | route
        return {"state": "no_source", "reason": "withdrawn"} | route
    row = store.conn.execute("SELECT * FROM arxiv_sources WHERE arxiv_key = ?", (version["arxiv_key"],)).fetchone()
    if row is None:
        return {"state": "pending"} | route
    row = dict(row)
    if row["status"] == "not_settled":
        if arxiv_source.SourceStore.exhausted(row):
            return {"state": "no_source", "reason": "not_settled", "attempts": row["attempts"]} | route
        if (until := arxiv_source.SourceStore.waiting_until(row)) is not None:
            return {"state": "source_waiting", "attempts": row["attempts"], "next_at": arxiv_source.iso(until)} | route
        return {"state": "pending"} | route
    if row["status"] == "downloaded":
        if row["content"] in (None, "tex"):
            return {"state": "pending"} | route  # not inspected yet, or inspected and not written (a crash in between)
        return {"state": "no_source", "reason": row["content"]} | route
    return {"state": "no_source", "reason": row["error"] if row["error"] == "cache_corrupt" else row["status"]} | route


def _marker_state(store: Store, asset: dict[str, Any]) -> dict[str, Any]:
    asset_id = asset["id"]
    version = target_version(asset["extraction_version"])
    # A Marker reading over an older text layer stays read (D48): `next_asset` does not pick it again, so it is not pending.
    if asset["extraction_version"] == version or (asset["extraction_version"] or "").endswith("+" + math_reader.MATH_VERSION):
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
    def __init__(self, store: Store, reader: math_reader.MathReader, papers_dir: Path, arxiv_mode: str = "off",
                 data_dir: Path | None = None, fetch_file: Any = None, http_client: Any = None):
        self.store, self.reader, self.papers_dir = store, reader, papers_dir
        # The arXiv source route (D104): its flag, and the stored sources under the data directory.
        self.arxiv_mode = arxiv_mode
        self.sources = arxiv_source.SourceStore(store, data_dir or papers_dir.parent, fetch_file=fetch_file, client=http_client)
        store.equation_route = self  # equation_state reads the route's rules from the store it is given
        # Mathpix (D40): the data directory its request lock lives in and the client its requests go through.
        self.data_dir = data_dir or papers_dir.parent
        self.mathpix_client = http_client
        self._task: asyncio.Task | None = None
        self._lock = asyncio.Lock()
        self._retries: set[asyncio.Task] = set()
        self.job: dict[str, Any] | None = None  # the install job shown in Settings
        self._install: asyncio.Task | None = None
        self._install_proc: asyncio.subprocess.Process | None = None
        self._waiting = 0  # runs and requests waiting for a read; the background reader gives way to them
        self._background_reading = False
        self._preempted = False

    def configure_arxiv_source(self, mode: str, data_dir: Path, fetch_file: Any = None) -> None:
        self.arxiv_mode = mode
        self.sources = arxiv_source.SourceStore(self.store, data_dir, fetch_file=fetch_file or self.sources.fetch_file,
                                                client=self.sources.client)

    def configure_mathpix(self, data_dir: Path, client: Any) -> None:
        self.data_dir, self.mathpix_client = data_dir, client

    def available(self) -> bool:
        return self.reader.available()

    def mathpix_ready(self) -> bool:
        """The switch is on and a readable key pair is saved: the Mathpix rows of the route table apply."""
        return mathpix_switch(self.store) and isinstance(mathpix.read_pair(), mathpix.Pair)

    def mathpix_active(self) -> bool:
        """Whether PDFs may be read with Mathpix now."""
        return self.mathpix_ready() and not self.marker_present() and self.mathpix_client is not None

    def marker_present(self) -> bool:
        """Marker installed or being installed: the route never runs then (D3)."""
        return self.available() or self.installing()

    def route_flag(self) -> bool:
        return self.arxiv_mode == "auto"

    def route_active(self) -> bool:
        """Whether PDFs without Marker's reading may be read from their arXiv source now."""
        return self.route_flag() and arxiv_source.posix_available() and not self.marker_present()

    def route_target(self, asset_id: str) -> bool:
        asset = self.store.asset(asset_id)
        return self.route_active() and "+marker-" not in (asset["extraction_version"] or "")

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

    def _reader_lock(self, asset):
        # Legacy synthetic identifiers cannot name a writer/retry lock or a repair target.
        if not text_retry.HASH.fullmatch(asset["sha256"]):
            return nullcontext()
        return text_retry.file_lock(file_restore.resolve_recovery_dir(self.store, self.papers_dir), asset["sha256"])

    async def _drain(self, awaitable):
        """Do not forward cancellation to a child-owning read or shared reader close."""
        task = asyncio.ensure_future(awaitable)
        try:
            return await asyncio.shield(task)
        except asyncio.CancelledError:
            while not task.done():
                try:
                    await asyncio.shield(task)
                except asyncio.CancelledError:
                    continue
                except BaseException:
                    break
            try:
                task.result()
            except asyncio.CancelledError:
                pass
            except BaseException:
                log.exception("Equation read failed while draining cancellation")
            raise

    async def _read(self, asset_id: str, run_id: str | None, retry: bool, background: bool) -> dict[str, Any]:
        global reading
        async with self._lock:
            state = equation_state(self.store, asset_id)
            if state.get("route") == arxiv_source.ENGINE:
                return await self._read_source(asset_id, run_id, retry, state)
            if state.get("route") == mathpix.ENGINE:
                return await self._read_mathpix(asset_id, run_id, retry, background, state)
            attempts = 0
            if state["state"] == "failed" and (retry or state["attempts"] < MAX_ATTEMPTS):
                attempts = state["attempts"]
            elif state["state"] != "pending":
                return state
            if not self.available():
                raise math_reader.MathReaderUnavailable("the equation reader (Marker) is not installed")
            asset = self.store.asset(asset_id)
            try:
                with self._reader_lock(asset):
                    version = target_version(asset["extraction_version"])
                    path = self.papers_dir / asset["storage_path"]
                    base = await text_retry.drained_thread(pdf.extract_pdf, path)
                    ocr_pages = self._ocr_pages(asset) if OCR_SUFFIX.search(asset["extraction_version"] or "") else {}
                    if ocr_pages:
                        base.pages = sorted(base.pages + [pdf.PageText(n, None, text, "ocr") for n, text in ocr_pages.items()
                                                          if n not in {p.physical_page for p in base.pages}], key=lambda p: p.physical_page)
                        base.status = "succeeded" if len(base.pages) == base.page_count else "partial"
                    base.extraction_version = version.removesuffix("+" + math_reader.MATH_VERSION)
                    selected = sorted(set(await text_retry.drained_thread(math_reader.math_pages, path)) | set(await text_retry.drained_thread(math_reader.table_pages, path))
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
                    except Exception:
                        raise
                    except BaseException:
                        # A cancelled reader request may still be touching the PDF; drain it before unlocking.
                        try:
                            await self._drain(self.reader.close())
                        except asyncio.CancelledError:
                            pass
                        except BaseException:
                            log.exception("Could not close the equation reader while unwinding")
                        raise
                    finally:
                        reading, self._background_reading, self._preempted = None, False, False
                    if read is None:
                        return equation_state(self.store, asset_id)
                    # OCR pages have no text layer to check an equation against.
                    text_layer = {i: found for i, found in read.equations.items() if i + 1 not in ocr_pages}
                    unchecked = await text_retry.drained_thread(math_reader.check_equations, path, text_layer)
                    extraction = math_reader.merge(base, read.pages, selected, unchecked)
                    self.store.reextract_asset(asset_id, extraction, extraction.extraction_version, pdf.chunk_page, allow_run_id=run_id)
                    return equation_state(self.store, asset_id)
            except text_retry.FileBusy:
                return equation_state(self.store, asset_id) | {"outcome": "file_busy"}

    # ---- the arXiv source route (D104) -------------------------------------------------------------------------------
    async def _eligibility(self, asset: dict[str, Any]) -> dict[str, Any]:
        """Decision 1, decided once per PDF and stored, so the view never opens a PDF to show the state. The PDF's first
        pages are read for the stamp in a worker thread; the row is written on the event loop."""
        row = self.store.conn.execute("SELECT * FROM asset_arxiv_versions WHERE asset_id = ?", (asset["id"],)).fetchone()
        if row is not None:
            return dict(row)
        try:
            stamp = await text_retry.drained_thread(arxiv_source.stamp_key, self.papers_dir / asset["storage_path"])
        except Exception:  # noqa: BLE001 - an unreadable PDF has no stamp
            stamp = None
        # The row check, the record read, the decision and the insert are one BEGIN IMMEDIATE transaction: no other process
        # can enrich the record between the read and the insert, and an enrichment committed before it is read here. One
        # committed after it finds this row and re-checks it (`store._recheck_arxiv_eligibility`).
        with transaction(self.store.conn):
            row = self.store.conn.execute("SELECT * FROM asset_arxiv_versions WHERE asset_id = ?", (asset["id"],)).fetchone()
            if row is None:
                record = dict(self.store.conn.execute(
                    "SELECT doi, landing_url, oa_pdf_url, version_label FROM source_versions WHERE id = ?",
                    (asset["source_version_id"],)).fetchone())
                found = arxiv_source.eligibility(arxiv_source.url_key(asset["retrieved_from"]), stamp, record)
                self.store.conn.execute(
                    "INSERT INTO asset_arxiv_versions (asset_id, eligibility, arxiv_key, version_from, record_label, checked_at)"
                    " VALUES (?, ?, ?, ?, ?, ?)", (asset["id"], found["eligibility"], found["arxiv_key"], found["version_from"],
                                                   found["record_label"], now()))
        return dict(self.store.conn.execute("SELECT * FROM asset_arxiv_versions WHERE asset_id = ?", (asset["id"],)).fetchone())

    def _events(self, asset: dict[str, Any], kind: str, payload: dict[str, Any]) -> None:
        researches = [r[0] for r in self.store.conn.execute(
            "SELECT research_id FROM corpus_memberships WHERE source_version_id = ?", (asset["source_version_id"],))]
        with transaction(self.store.conn):
            for research_id in researches:
                self.store._event(research_id, kind, {"asset_id": asset["id"], "source_version_id": asset["source_version_id"]} | payload)

    def _record_source_rejection(self, asset: dict[str, Any], version: str, reason: str, source: dict[str, Any] | None,
                                 extra: dict[str, Any] | None = None, engine: str = arxiv_source.ENGINE) -> None:
        """A source or Mathpix reading that writes no text (nothing placed, offsets unresolved, the extraction failed): a
        rejected row without passages; `extra` carries a failed attempt's count and error."""
        with transaction(self.store.conn):
            self.store.conn.execute(
                "INSERT INTO asset_extractions (id, asset_id, extraction_version, status, error, page_count, text_pages,"
                " passage_count, outcome, rejection_reason, created_at, math_json, extractor_profile, baseline_extraction_id)"
                " SELECT ?, ?, ?, ?, NULL, ?, 0, 0, 'rejected', ?, ?, ?, ?,"
                " (SELECT id FROM asset_extractions WHERE asset_id = ? AND outcome = 'current')"
                " WHERE NOT EXISTS (SELECT 1 FROM asset_extractions WHERE asset_id = ? AND extraction_version = ?)",
                (new_id("ext"), asset["id"], version, asset["extraction_status"], asset["page_count"], reason, now(),
                 json.dumps({"engine": engine} | ({"source": source} if source else {}) | (extra or {})),
                 recovery.profile_of(version), asset["id"], asset["id"], version),
            )

    async def _read_source(self, asset_id: str, run_id: str | None, retry: bool, state: dict[str, Any]) -> dict[str, Any]:
        """One PDF through the route. Every outcome returns the PDF's state; RunInProgress propagates."""
        global reading
        asset = self.store.asset(asset_id)
        if not self.route_active():
            return state
        try:
            with self._reader_lock(asset):
                version = await self._eligibility(asset) if state["state"] in ("pending", "no_source", "failed") else None
                # A failed extraction keeps its attempt count across the next attempt (as a failed Marker read does).
                attempts = state.get("attempts", 0) if state.get("reason") == EXTRACTION_FAILED else 0
                if retry and version and version["arxiv_key"] and state["state"] in ("no_source", "failed"):
                    self.sources.reset(version["arxiv_key"])  # the person's retry
                    self._forget_failure(asset_id, source_target_version(asset["extraction_version"]))
                    state = equation_state(self.store, asset_id)
                elif state["state"] == "failed" and state.get("reason") == EXTRACTION_FAILED and attempts < MAX_ATTEMPTS:
                    self._forget_failure(asset_id, source_target_version(asset["extraction_version"]))
                    state = equation_state(self.store, asset_id)
                if state["state"] != "pending" or version is None or version["eligibility"] != "eligible":
                    return equation_state(self.store, asset_id)
                start_version = asset["extraction_version"]
                target = source_target_version(start_version)
                key = version["arxiv_key"]
                self._forget_failure(asset_id, target)  # a record_version_changed row whose record is eligible again
                row = await self.sources.ensure(key)
                if row.get("outcome") == "rate_gate_busy":
                    return equation_state(self.store, asset_id) | {"outcome": "rate_gate_busy"}
                if row["status"] != "downloaded":
                    return equation_state(self.store, asset_id)
                data, problem = await self.sources.read(key)
                if problem == "busy":
                    return equation_state(self.store, asset_id) | {"outcome": "rate_gate_busy"}
                if problem == "repair":
                    self._events(asset, "arxiv_source_corrupt", {"arxiv_key": key, "repair": True})
                    row = await self.sources.ensure(key)
                    if row.get("outcome") == "rate_gate_busy" or row["status"] != "downloaded":
                        return equation_state(self.store, asset_id) | ({"outcome": row["outcome"]} if row.get("outcome") else {})
                    data, problem = await self.sources.read(key)
                if problem == "busy":
                    return equation_state(self.store, asset_id) | {"outcome": "rate_gate_busy"}
                if problem:
                    self._events(asset, "arxiv_source_corrupt", {"arxiv_key": key, "repair": False})
                    return equation_state(self.store, asset_id)
                path = self.papers_dir / asset["storage_path"]
                ocr_pages = self._ocr_pages(asset) if OCR_SUFFIX.search(start_version or "") else {}
                title = self.store.conn.execute("SELECT title FROM source_versions WHERE id = ?", (asset["source_version_id"],)).fetchone()
                reading = {"asset_id": asset_id, "title": title[0] if title else None, "pages": asset["page_count"], "started_at": now(),
                           "route": arxiv_source.ENGINE}
                base = None
                try:
                    found = await self._drain(arxiv_source.read_source(data, path, set(ocr_pages)))
                    with transaction(self.store.conn):
                        self.store.conn.execute("UPDATE arxiv_sources SET content = ?, inspected_at = ?, error = ? WHERE arxiv_key = ?",
                                                (found["content"], now(), found.get("error"), key))
                    if found["content"] == "tex" and found["placements"]:
                        base = await text_retry.drained_thread(lambda: pdf.extract_pdf(path, placements=found["placements"]))
                finally:
                    reading = None
                if found["content"] != "tex":
                    return equation_state(self.store, asset_id)
                arxiv_id, number = arxiv_source.split_key(key)
                summary = {"arxiv_id": arxiv_id, "version": number, "version_from": version["version_from"],
                           "record_label": version["record_label"], "status": row["status"], "content": "tex", "sha256": row["sha256"],
                           "params": arxiv_source.PARAMS, "number_lines": found["number_lines"], "candidates": found["candidates"],
                           "child_seconds": found.get("child_seconds")}
                not_placed = Counter(found["not_placed"])
                if base is not None and base.status == "failed":  # a time or memory limit, not an absence of matches
                    self._record_source_rejection(asset, target, EXTRACTION_FAILED, summary | {"placed": [], "not_placed": dict(not_placed)},
                                                  {"attempts": attempts + 1, "error": (base.error or "")[:400]})
                    self._events(asset, "equations_failed", {"reason": EXTRACTION_FAILED, "attempts": attempts + 1, "route": arxiv_source.ENGINE})
                    return equation_state(self.store, asset_id)
                if base is None:
                    self._record_source_rejection(asset, target, NOTHING_PLACED, summary | {"placed": [], "not_placed": dict(not_placed)})
                    return equation_state(self.store, asset_id)
                placement = base.placement or {"placed": [], "refused": []}
                not_placed.update(r["reason"] for r in placement["refused"])
                details = {(p["page"], p["n"]): p for p in found["placements"]}
                placed = [{"page": p["page"], "n": p["n"], "start": p["start"], "end": p["end"]}
                          | {k: details[(p["page"], p["n"])][k] for k in ("group", "recall", "f1", "window_margin", "paper_margin")}
                          for p in placement["placed"]]
                summary |= {"placed": placed, "not_placed": dict(not_placed)}
                if any(r["reason"] == OFFSETS_UNRESOLVED for r in placement["refused"]):
                    self._record_source_rejection(asset, target, OFFSETS_UNRESOLVED, summary)
                    return equation_state(self.store, asset_id)
                if not placed:
                    self._record_source_rejection(asset, target, NOTHING_PLACED, summary)
                    return equation_state(self.store, asset_id)
                if ocr_pages:
                    base.pages = sorted(base.pages + [pdf.PageText(n, None, text, "ocr") for n, text in ocr_pages.items()
                                                      if n not in {p.physical_page for p in base.pages}], key=lambda p: p.physical_page)
                    base.status = "succeeded" if len(base.pages) == base.page_count else "partial"
                base.extraction_version, base.math = target, {"engine": arxiv_source.ENGINE, "source": summary}

                def guard(conn: Any) -> str | None:
                    """Decision 6's last-write check, inside the write's BEGIN IMMEDIATE transaction, before its first write."""
                    now_asset = conn.execute("SELECT removed_at, extraction_version FROM source_assets WHERE id = ?", (asset_id,)).fetchone()
                    if now_asset["removed_at"] is not None:
                        return "asset_removed"
                    record = dict(conn.execute("SELECT doi, landing_url, oa_pdf_url, version_label FROM source_versions WHERE id = ?",
                                               (asset["source_version_id"],)).fetchone())
                    if (result := arxiv_source.record_eligibility(key, record)) != "eligible":
                        conn.execute("UPDATE asset_arxiv_versions SET eligibility = ?, record_label = ?, checked_at = ? WHERE asset_id = ?",
                                     (result, record["version_label"], now(), asset_id))
                        conn.execute(
                            "INSERT INTO asset_extractions (id, asset_id, extraction_version, status, error, page_count, text_pages,"
                            " passage_count, outcome, rejection_reason, created_at, math_json, extractor_profile, baseline_extraction_id)"
                            " SELECT ?, ?, ?, ?, NULL, ?, 0, 0, 'rejected', ?, ?, ?, ?,"
                            " (SELECT id FROM asset_extractions WHERE asset_id = ? AND outcome = 'current')"
                            " WHERE NOT EXISTS (SELECT 1 FROM asset_extractions WHERE asset_id = ? AND extraction_version = ?)",
                            (new_id("ext"), asset_id, target, asset["extraction_status"], asset["page_count"], RECORD_VERSION_CHANGED, now(),
                             json.dumps({"engine": arxiv_source.ENGINE, "eligibility": result}), recovery.profile_of(target),
                             asset_id, asset_id, target))
                        for research_id in [r[0] for r in conn.execute("SELECT research_id FROM corpus_memberships WHERE source_version_id = ?",
                                                                        (asset["source_version_id"],))]:
                            self.store._event(research_id, "arxiv_source_refused", {"asset_id": asset_id, "reason": RECORD_VERSION_CHANGED,
                                                                                    "eligibility": result})
                        return RECORD_VERSION_CHANGED
                    if now_asset["extraction_version"] != start_version or "+marker-" in (now_asset["extraction_version"] or ""):
                        return "superseded"
                    if not self.route_flag() or self.marker_present():
                        return "superseded_by_marker"
                    return None

                try:
                    report = self.store.reextract_asset(asset_id, base, target, source_chunker, allow_run_id=run_id, guard=guard)
                except NotFound:  # removed before the write began; the guard covers a removal racing the write itself
                    return equation_state(self.store, asset_id) | {"outcome": "asset_removed"}
                return equation_state(self.store, asset_id) | {"outcome": report.get("reason") or report["outcome"]}

        except text_retry.FileBusy:
            return equation_state(self.store, asset_id) | {"outcome": "file_busy"}

    # ---- Mathpix (D40) ------------------------------------------------------------------------------------------------
    def _send_refusal(self, asset_id: str, start_version: str | None, start_id: str | None, pair: Any) -> str | None:
        """The pre-send check, inside the reservation's transaction: why no request may be sent now, or None."""
        if not mathpix_switch(self.store):
            return "switch_off"
        saved = mathpix.read_pair()
        if not isinstance(saved, mathpix.Pair) or saved.revision != pair.revision:
            return "keys_changed"
        if self.marker_present():
            return "marker"
        asset = self.store.conn.execute("SELECT removed_at, extraction_version FROM source_assets WHERE id = ?", (asset_id,)).fetchone()
        current = self.store.conn.execute("SELECT id FROM asset_extractions WHERE asset_id = ? AND outcome = 'current'", (asset_id,)).fetchone()
        if asset is None or asset["removed_at"] is not None or asset["extraction_version"] != start_version or (current[0] if current else None) != start_id:
            return "extraction_changed"
        if mathpix_keys_rejected(self.store, pair):
            return "keys_rejected"
        if equation_state(self.store, asset_id).get("route") != mathpix.ENGINE:
            return "route_changed"
        counts = mathpix_counts(self.store, asset_id)
        if counts["month"] >= counts["budget"] or counts["asset"] >= MAX_ASSET_REQUESTS:
            return "budget_reached"
        return None

    def _reserve(self, asset_id: str, start_version: str | None, start_id: str | None, file_sha: str, pair: Any,
                 crop: dict[str, Any]) -> dict[str, Any]:
        """One BEGIN IMMEDIATE transaction: reuse an answer for the same crop, else check and reserve a request row."""
        with transaction(self.store.conn):
            row = self.store.conn.execute("SELECT * FROM mathpix_requests WHERE crop_sha256 = ? AND status = 'answered'"
                                          " ORDER BY answered_at, rowid LIMIT 1", (crop["crop_sha256"],)).fetchone()
            if row is not None:
                return {"outcome": "reused", "row": dict(row)}
            if refusal := self._send_refusal(asset_id, start_version, start_id, pair):
                return {"outcome": "stop", "reason": refusal}
            row_id = new_id("mpx")
            attempt = 1 + self.store.conn.execute("SELECT COUNT(*) FROM mathpix_requests WHERE crop_sha256 = ?",
                                                  (crop["crop_sha256"],)).fetchone()[0]
            self.store.conn.execute(
                "INSERT INTO mathpix_requests (id, crop_sha256, asset_id, file_sha256, page, n, attempt, status, credential_revision,"
                " reserved_at) VALUES (?, ?, ?, ?, ?, ?, ?, 'reserved', ?, ?)",
                (row_id, crop["crop_sha256"], asset_id, file_sha, crop["page"], crop["n"], attempt, pair.revision, now()))
        return {"outcome": "send", "row_id": row_id}

    def _finish_request(self, row_id: str, outcome: mathpix.Outcome) -> None:
        with transaction(self.store.conn):
            self.store.conn.execute(
                "UPDATE mathpix_requests SET status = ?, http_status = ?, request_id = ?, response_json = ?, reason = ?, answered_at = ?"
                " WHERE id = ?", (outcome.status, outcome.http_status if outcome.sent else None, outcome.request_id,
                                  json.dumps(outcome.body) if outcome.body is not None else None, outcome.reason, now(), row_id))

    async def _crop_answer(self, asset_id: str, start_version: str | None, start_id: str | None, file_sha: str, pair: Any,
                           crop: dict[str, Any]) -> dict[str, Any]:
        """The answer for one crop: a stored one for the same image, or one request. Returns the outcome with its row."""
        try:
            async with mathpix.request_lock(self.data_dir):
                reserved = self._reserve(asset_id, start_version, start_id, file_sha, pair, crop)
                if reserved["outcome"] != "send":
                    return reserved
                try:
                    outcome = await mathpix.send(self.mathpix_client, pair, equation_regions.data_url(crop["png"]))
                except BaseException:
                    # Cancelled mid-request (shutdown): Mathpix may have processed it, so it stays counted.
                    self._finish_request(reserved["row_id"], mathpix.Outcome("unknown", reason="network"))
                    raise
                self._finish_request(reserved["row_id"], outcome)
        except TimeoutError:
            return {"outcome": "stop", "reason": "busy"}  # another DEIXIS process held the request lock too long
        row = dict(self.store.conn.execute("SELECT * FROM mathpix_requests WHERE id = ?", (reserved["row_id"],)).fetchone())
        if outcome.status == "answered":
            return {"outcome": "answered", "row": row}
        return {"outcome": "stop", "reason": outcome.reason or "network", "row": row}

    def _record_mathpix(self, asset: dict[str, Any], version: str, reason: str, math: dict[str, Any]) -> None:
        """A Mathpix reading that writes no text: no candidates, none placed, or a failed attempt (with its count)."""
        self._record_source_rejection(asset, version, reason, None, math, engine=mathpix.ENGINE)
        if "attempts" in math:
            self._events(asset, "equations_failed", {"reason": math.get("reason", reason), "attempts": math["attempts"],
                                                     "route": mathpix.ENGINE})

    async def _read_mathpix(self, asset_id: str, run_id: str | None, retry: bool, background: bool,
                            state: dict[str, Any]) -> dict[str, Any]:
        """One PDF through Mathpix. Answers already received are kept and reused by the next read. A budget that stops
        sending does not throw away what was answered: the read places those, and the crops left unsent are refused
        `budget_reached`; a PDF at its budget is read again from stored answers alone. Any other stop writes nothing.
        Every outcome returns the PDF's state; RunInProgress propagates."""
        global reading
        asset = self.store.asset(asset_id)
        attempts = state.get("attempts", MAX_ATTEMPTS) if state["state"] == "failed" else 0
        cached = state["state"] == "budget_reached" and mathpix_answered(self.store, asset_id)
        if state["state"] not in ("pending", "failed") and not cached \
                or (state["state"] == "failed" and not retry and attempts >= MAX_ATTEMPTS):
            return state
        pair = mathpix.read_pair()
        if not isinstance(pair, mathpix.Pair) or not self.mathpix_active():
            return state
        try:
            with self._reader_lock(asset):
                start_version = asset["extraction_version"]
                current = self.store.conn.execute("SELECT id FROM asset_extractions WHERE asset_id = ? AND outcome = 'current'",
                                                  (asset_id,)).fetchone()
                start_id = current[0] if current else None
                target = mathpix_target_version(start_version)
                path = self.papers_dir / asset["storage_path"]
                file_sha = await text_retry.drained_thread(_file_sha256, path)
                if text_retry.HASH.fullmatch(asset["sha256"]) and file_sha != asset["sha256"]:
                    return equation_state(self.store, asset_id) | {"outcome": "file_changed"}
                ocr_pages = self._ocr_pages(asset) if OCR_SUFFIX.search(start_version or "") else {}
                self._forget_failure(asset_id, target)
                title = self.store.conn.execute("SELECT title FROM source_versions WHERE id = ?", (asset["source_version_id"],)).fetchone()
                reading = {"asset_id": asset_id, "title": title[0] if title else None, "pages": asset["page_count"], "started_at": now(),
                           "route": mathpix.ENGINE}
                answers: dict[tuple[int, str], dict[str, Any]] = {}
                unsent: list[dict[str, Any]] = []  # crops a budget kept from being sent; stored answers still count
                stop: dict[str, Any] | None = None
                try:
                    found = await text_retry.drained_thread(equation_regions.detect, path, set(ocr_pages))
                    for crop in (c for c in found if "png" in c):
                        if (background and self._waiting) or (run_id and self.store.equation_skip_requested(run_id)):
                            stop = {"reason": "preempted" if background else "skipped"}
                            break
                        result = await self._crop_answer(asset_id, start_version, start_id, file_sha, pair, crop)
                        if result["outcome"] == "stop" and result["reason"] == "budget_reached":
                            unsent.append({"page": crop["page"], "n": crop["n"], "reason": "budget_reached"})
                            continue
                        if result["outcome"] == "stop":
                            stop = result
                            break
                        answers[(crop["page"], crop["n"])] = result
                finally:
                    reading = None
                if stop is not None:
                    if stop["reason"] in ("rate_limited", "network", "server_error"):
                        self._record_mathpix(asset, target, "mathpix_failed", {"reason": stop["reason"], "attempts": attempts + 1})
                    return equation_state(self.store, asset_id) | {"outcome": stop["reason"]}
                if not found:
                    self._record_mathpix(asset, target, NO_CANDIDATES, {"candidates": 0})
                    return equation_state(self.store, asset_id)
                if unsent and not answers:
                    return equation_state(self.store, asset_id) | {"outcome": "budget_reached"}
                return await self._place_mathpix(asset, run_id, found, answers, start_version, start_id, target, attempts, ocr_pages,
                                                 unsent)
        except text_retry.FileBusy:
            return equation_state(self.store, asset_id) | {"outcome": "file_busy"}

    async def _place_mathpix(self, asset: dict[str, Any], run_id: str | None, found: list[dict[str, Any]],
                             answers: dict[tuple[int, str], dict[str, Any]], start_version: str | None, start_id: str | None,
                             target: str, attempts: int, ocr_pages: dict[int, str],
                             unsent: list[dict[str, Any]] | None = None) -> dict[str, Any]:
        asset_id = asset["id"]
        unsent = unsent or []
        refused = [{"page": c["page"], "n": c["n"], "reason": c["refused"]} for c in found if "refused" in c] + unsent
        placements, details = [], {}
        requests = sum(1 for a in answers.values() if a["outcome"] == "answered")
        reused = len(answers) - requests
        for crop in (c for c in found if "png" in c and (c["page"], c["n"]) in answers):
            answer = answers[(crop["page"], crop["n"])]
            body = json.loads(answer["row"]["response_json"] or "null")
            checked = equation_regions.gate(crop, body)
            if checked["reason"]:
                refused.append({"page": crop["page"], "n": crop["n"], "reason": checked["reason"]})
                continue
            placements.append({"page": crop["page"], "n": crop["n"], "latex": checked["latex"], "number": crop["number"], "lines": crop["lines"]})
            version = body.get("version")
            details[(crop["page"], crop["n"])] = {
                "box": crop["box"], "crop": crop["crop"], "crop_sha256": crop["crop_sha256"], "request_row_id": answer["row"]["id"],
                "request_id": answer["row"]["request_id"], "provider_version": version if isinstance(version, str) else None,
                "confidence": body.get("confidence"), "confidence_rate": body.get("confidence_rate"), "checks": checked["checks"],
                "text_layer": crop["text_layer"]}
        summary = {"candidates": len(found), "requests": requests, "reused": reused}
        if not placements and unsent:  # nothing placeable yet; the crops left unsent may still be read under a new budget
            return equation_state(self.store, asset_id) | {"outcome": "budget_reached"}
        if not placements:
            self._record_mathpix(asset, target, NONE_PLACED, summary | {"refused": refused})
            return equation_state(self.store, asset_id)
        path = self.papers_dir / asset["storage_path"]
        base = await text_retry.drained_thread(lambda: pdf.extract_pdf(path, placements=placements))
        if base.status == "failed":  # a time or memory limit: tried again like a failed read
            self._record_mathpix(asset, target, "mathpix_failed", {"reason": EXTRACTION_FAILED, "attempts": attempts + 1,
                                                                  "error": (base.error or "")[:400]})
            return equation_state(self.store, asset_id)
        placement = base.placement or {"placed": [], "refused": []}
        refused += placement["refused"]
        placed = [{"page": p["page"], "n": p["n"], "start": p["start"], "end": p["end"]} | details[(p["page"], p["n"])]
                  for p in placement["placed"]]
        if not placed and unsent and not placement["refused"]:
            return equation_state(self.store, asset_id) | {"outcome": "budget_reached"}
        if not placed or any(r["reason"] == OFFSETS_UNRESOLVED for r in placement["refused"]):
            self._record_mathpix(asset, target, NONE_PLACED, summary | {"refused": refused})
            return equation_state(self.store, asset_id)
        for page in base.pages:
            page.placement_label = "equation_ocr"
        if ocr_pages:
            base.pages = sorted(base.pages + [pdf.PageText(n, None, text, "ocr") for n, text in ocr_pages.items()
                                              if n not in {p.physical_page for p in base.pages}], key=lambda p: p.physical_page)
            base.status = "succeeded" if len(base.pages) == base.page_count else "partial"
        base.extraction_version = target
        base.math = {"engine": mathpix.ENGINE, "placed": placed, "refused": refused} | summary

        def guard(conn: Any) -> str | None:
            """The last-write check, inside the write's BEGIN IMMEDIATE transaction, before its first write."""
            now_asset = conn.execute("SELECT removed_at, extraction_version, sha256 FROM source_assets WHERE id = ?", (asset_id,)).fetchone()
            if now_asset["removed_at"] is not None:
                return "asset_removed"
            current = conn.execute("SELECT id FROM asset_extractions WHERE asset_id = ? AND outcome = 'current'", (asset_id,)).fetchone()
            if now_asset["extraction_version"] != start_version or (current[0] if current else None) != start_id:
                return "superseded"
            if now_asset["sha256"] != asset["sha256"]:
                return "file_changed"
            if self.marker_present():
                return "superseded_by_marker"
            if not self.mathpix_ready():
                return "switch_off"
            if equation_state(self.store, asset_id).get("route") != mathpix.ENGINE:
                return "route_changed"
            return None

        try:
            report = self.store.reextract_asset(asset_id, base, target, source_chunker, allow_run_id=run_id, guard=guard)
        except NotFound:
            return equation_state(self.store, asset_id) | {"outcome": "asset_removed"}
        return equation_state(self.store, asset_id) | {"outcome": report.get("reason") or report["outcome"]}

    def mathpix_status(self) -> dict[str, Any]:
        """The Settings tile: the pair, the switch, this month's count against the budget and the library's PDFs by state."""
        pair = mathpix.read_pair()
        states: dict[str, int] = {}
        for row in self.store.conn.execute("SELECT id FROM source_assets WHERE removed_at IS NULL AND extraction_status IN ('succeeded', 'partial')"):
            state = equation_state(self.store, row[0])
            if state.get("route") == mathpix.ENGINE:
                states[state["state"]] = states.get(state["state"], 0) + 1
        counts = mathpix_counts(self.store)
        return {"pair": {"configured": isinstance(pair, mathpix.Pair), "unreadable": pair == "unreadable",
                         "app_id": pair.app_id if isinstance(pair, mathpix.Pair) else None},
                "keys_rejected": mathpix_keys_rejected(self.store, pair), "switch": "on" if mathpix_switch(self.store) else "off",
                "monthly_budget": counts["budget"], "month_requests": counts["month"], "per_pdf_limit": MAX_ASSET_REQUESTS,
                "marker_present": self.marker_present(), "pdfs": states,
                "reading": reading if reading and reading.get("route") == mathpix.ENGINE else None}

    async def mathpix_estimate(self) -> dict[str, Any]:
        """Before the switch is turned on: how many PDFs Mathpix would read and an upper bound of requests (the detector's
        count, capped per PDF and by what is left of the month's budget). Nothing is sent."""
        pdfs, crops = 0, 0
        for row in self.store.conn.execute("SELECT * FROM source_assets WHERE removed_at IS NULL AND extraction_status IN ('succeeded', 'partial')"):
            asset = dict(row)
            current = asset["extraction_version"] or ""
            if "+marker-" in current or current.endswith(SOURCE_SUFFIX) or current.endswith(MATHPIX_SUFFIX):
                continue
            if self.route_flag() and arxiv_source.posix_available() and not _source_settled(_source_state(self.store, asset)):
                continue
            ocr = set(self._ocr_pages(asset)) if OCR_SUFFIX.search(current) else set()
            try:
                found = await text_retry.drained_thread(equation_regions.detect, self.papers_dir / asset["storage_path"], ocr, False)
            except Exception:  # noqa: BLE001 - an unreadable PDF adds nothing to the estimate
                continue
            count = sum(1 for c in found if "crop" in c and "refused" not in c)
            if count:
                pdfs += 1
                crops += min(count, MAX_ASSET_REQUESTS)
        counts = mathpix_counts(self.store)
        return {"pdfs": pdfs, "upper_bound": min(crops, max(0, counts["budget"] - counts["month"])), "crops": crops}

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
                                    " AND outcome = 'rejected' AND passage_count = 0 AND recovery_operation_id IS NULL", (asset_id, version))

    def _record_without_passages(self, asset: dict[str, Any], version: str, reason: str, attempts: int) -> None:
        researches = [r[0] for r in self.store.conn.execute(
            "SELECT research_id FROM corpus_memberships WHERE source_version_id = ?", (asset["source_version_id"],))]
        with transaction(self.store.conn):
            self.store.conn.execute(
                "INSERT INTO asset_extractions (id, asset_id, extraction_version, status, error, page_count, text_pages,"
                " passage_count, outcome, rejection_reason, created_at, math_json, extractor_profile, baseline_extraction_id)"
                " SELECT ?, ?, ?, ?, NULL, ?, 0, 0, 'rejected', ?, ?, ?, ?,"
                " (SELECT id FROM asset_extractions WHERE asset_id = ? AND outcome = 'current')"
                " WHERE NOT EXISTS (SELECT 1 FROM asset_extractions WHERE asset_id = ? AND extraction_version = ?)",
                (new_id("ext"), asset["id"], version, asset["extraction_status"], asset["page_count"], reason, now(),
                 json.dumps({"engine": "marker", "attempts": attempts}), recovery.profile_of(version),
                 asset["id"], asset["id"], version),
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
            if state["state"] == "pending" or (state["state"] == "failed" and state.get("attempts", MAX_ATTEMPTS) < MAX_ATTEMPTS
                                               and state["at"] < retry_before):
                return row[0]
        return None

    async def run_forever(self) -> None:
        while True:
            if self._waiting:
                await asyncio.sleep(1)  # a run or request goes first
                continue
            # Marker's reader when it is installed; else the arXiv source route when its flag is on (D104).
            asset_id = (self.next_asset() if (self.available() and not self.installing()) or self.route_active() or self.mathpix_active()
                        else None)
            if asset_id is None:
                await asyncio.sleep(RETRY_SECONDS)
                continue
            try:
                state = await self.read_asset(asset_id, background=True)
                if state.get("outcome") == "file_busy" or (state.get("route") and state["state"] == "pending"):
                    await asyncio.sleep(RETRY_SECONDS)  # the rate gate was busy: give way before trying again
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
            if self.route_flag() and arxiv_source.posix_available():
                self.sources.remove_stale_parts()
            elif self.route_flag():
                log.warning("DEIXIS_ARXIV_SOURCE=auto: the arXiv source route needs file locks (POSIX) and is off on this system")
            self._task = asyncio.create_task(self.run_forever())

    async def stop(self) -> None:
        tasks = tuple(t for t in (self._task, *self._retries, self._install) if t is not None)
        self._task = None
        for task in tasks:
            task.cancel()
        if self._install_proc and self._install_proc.returncode is None:
            self._install_proc.kill()
        try:
            await self._drain(self.reader.close())
        finally:
            for task in tasks:
                try:
                    await self._drain(task)
                except asyncio.CancelledError:
                    pass
                except Exception:
                    log.exception("Equation task failed during shutdown")

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
                    child = library_lock.guard(argv)  # keeps the data folder busy while it runs (E1)
                    try:
                        self._install_proc = proc = await asyncio.create_subprocess_exec(
                            *child.argv, stdin=subprocess.DEVNULL, stdout=subprocess.PIPE, stderr=subprocess.STDOUT, env=child.env(env),
                            **child.kwargs)
                        await asyncio.to_thread(child.wait_ready)
                    except library_lock.ChildLockFailed:
                        proc.kill()
                        raise
                    finally:
                        child.done()
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


def _file_sha256(path: Path) -> str:
    import hashlib

    digest = hashlib.sha256()
    with open(path, "rb") as handle:
        for chunk in iter(lambda: handle.read(1 << 20), b""):
            digest.update(chunk)
    return digest.hexdigest()


def _size(root: Path) -> int:
    total = 0
    for folder, _, files in os.walk(root):
        for name in files:
            try:
                total += os.lstat(os.path.join(folder, name)).st_size
            except OSError:
                pass
    return total
