"""Reading the numbered display equations of stored PDFs, in the background and before an answer or a table cell.

Marker, the optional local reader of D52, was removed (D113). A PDF whose current text is an earlier Marker reading keeps
it and its state is `read`; nothing reads it again by itself.

Every route writes a new extraction under D45's rule, so older passages stay resolvable, and places only numbered display
equations found from the PDF's text layer (`documents/equation_regions.py`):

- the arXiv source route (D104): with `DEIXIS_ARXIV_SOURCE=auto` and on POSIX, a PDF that is an arXiv version gets the
  numbered display equations of the authors' LaTeX source of that version, matched to the page by their numbers;
- Mathpix (D40): with its switch on and its key pair saved, each equation's page crop is read by Mathpix;
- the answer model (D113): with its switch on (the default) and a default answer model in Settings whose connection
  accepts images, each crop is read by that model (`documents/equation_model.py`). A connection without image input
  turns the route off and the state says why; no other model or connection is asked.

Mathpix and the answer model read the crop's image only; a reading is placed only when it passes the gate against the
PDF's text layer, and its passages carry `text_source = 'equation_ocr'`.

Precedence per PDF, first match wins: the current text an earlier Marker reading, a Mathpix reading, a model reading or
a source reading (kept: a later route does not replace it in v1); the arXiv route active and its state for the PDF
transient (the crop reader waits); Mathpix ready; the answer model ready; otherwise `off` with the reason. No outcome
of these routes pauses a run.
"""

from __future__ import annotations

import asyncio
import json
import logging
import os
import re
from collections import Counter
from contextlib import nullcontext
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Any

from deixis.keys import credentials, key_verification
from deixis.documents import arxiv_source, equation_model, equation_regions, math_reader, mathpix, pdf
from deixis.storage.db import new_id, now, transaction
from deixis.workflow.read import file_restore, recovery, text_retry
from deixis.workflow.run import spend
from deixis.workflow.run.store import NotFound, RunInProgress, Store

log = logging.getLogger("deixis.workflow.equations")  # the name before the folders; log names stay
NO_MATH = "no pages with mathematics"  # an earlier Marker reading's "nothing to read" (D52)
RETRY_SECONDS = 60
MAX_ATTEMPTS = 3  # a failed read is tried again in the background until this many attempts
RETRY_AFTER = timedelta(minutes=10)
OCR_SUFFIX = re.compile(r"\+ocr-.+?-v\d+(?=\+marker-|\+arxiv-latex-|\+mathpix-|\+model-eq-|$)")
SOURCE_SUFFIX = "+" + arxiv_source.SOURCE_VERSION
MATHPIX_SUFFIX = "+" + mathpix.VERSION
MODEL_SUFFIX = "+" + equation_model.VERSION
CROP_ROUTES = (mathpix.ENGINE, equation_model.ENGINE)  # the routes that read page crops
NO_CANDIDATES = "no_candidates"  # Mathpix: the detector found no numbered display equation (terminal, like NO_MATH)
NONE_PLACED = "none_placed"  # Mathpix: candidates found, every one refused (terminal, reasons kept)
MATHPIX_SWITCH = "mathpix_equations"  # app setting, "on" or "off" (default off); read before every request
MATHPIX_BUDGET = "mathpix_monthly_budget"
DEFAULT_MONTHLY_BUDGET = 500
MAX_ASSET_REQUESTS = 60  # requests one PDF may send across all its attempts (each crop route counts its own)
MODEL_SWITCH = "model_equations"  # app setting, "on" (the default when unset) or "off"; read before every request
MODEL_BUDGET = "model_equations_monthly_budget"
DEFAULT_MODEL_MONTHLY_BUDGET = 1000
NOTHING_PLACED = "nothing_placed"
OFFSETS_UNRESOLVED = "offsets_unresolved"
RECORD_VERSION_CHANGED = "record_version_changed"
EXTRACTION_FAILED = "extraction_failed"  # the PDF's text layer could not be extracted again with the placements


def _reading(store: Store) -> dict[str, Any] | None:
    """The PDF the store's equation service is reading now, for views: {"asset_id", "title", "pages", "started_at"}
    and "route". A store with no service reads nothing."""
    return getattr(getattr(store, "equation_route", None), "reading", None)


def target_version(current: str | None = None) -> str:
    """The version an earlier Marker reading of a PDF has: its text layer, its OCR reading if any, then Marker (D52).
    Nothing writes it any more (D113); it names the readings PDFs keep."""
    ocr = OCR_SUFFIX.search(recovery.profile_of(current or ""))
    return recovery.text_base(current) + (ocr.group(0) if ocr else "") + "+" + math_reader.MATH_VERSION


def source_target_version(current: str | None) -> str:
    """The version a source reading of a PDF gets: its text layer, its OCR reading if any, then the arXiv source."""
    ocr = OCR_SUFFIX.search(recovery.profile_of(current or ""))
    return recovery.text_base(current) + (ocr.group(0) if ocr else "") + SOURCE_SUFFIX


def mathpix_target_version(current: str | None) -> str:
    """The version a Mathpix reading of a PDF gets: its text layer, its OCR reading if any, then Mathpix."""
    ocr = OCR_SUFFIX.search(recovery.profile_of(current or ""))
    return recovery.text_base(current) + (ocr.group(0) if ocr else "") + MATHPIX_SUFFIX


def model_target_version(current: str | None) -> str:
    """The version a model reading of a PDF gets: its text layer, its OCR reading if any, then the model (D113)."""
    ocr = OCR_SUFFIX.search(recovery.profile_of(current or ""))
    return recovery.text_base(current) + (ocr.group(0) if ocr else "") + MODEL_SUFFIX


def crop_target_version(route: str, current: str | None) -> str:
    return mathpix_target_version(current) if route == mathpix.ENGINE else model_target_version(current)


def model_switch(store: Store) -> bool:
    return store.setting(MODEL_SWITCH) != "off"  # on unless turned off (D113)


def model_budget(store: Store) -> int:
    value = store.setting(MODEL_BUDGET)
    return value if isinstance(value, int) and not isinstance(value, bool) and value >= 0 else DEFAULT_MODEL_MONTHLY_BUDGET


# A model request counts once it may have reached the provider: reserved, answered, unknown, or an error the adapter says
# was sent. An error before sending (no key, a refused connection) costs nothing and does not count.
MODEL_COUNTED = "(status IN ('reserved', 'answered', 'unknown') OR (status = 'error' AND IFNULL(delivery_class, '') != 'before_send'))"


def model_counts(store: Store, asset_id: str | None = None) -> dict[str, int]:
    """This calendar month's model requests (UTC) against the monthly budget, and one PDF's requests over all attempts."""
    month = now()[:7]
    used = store.conn.execute(f"SELECT COUNT(*) FROM equation_model_requests WHERE substr(reserved_at, 1, 7) = ? AND {MODEL_COUNTED}",
                              (month,)).fetchone()[0]
    out = {"month": used, "budget": model_budget(store)}
    if asset_id is not None:
        out["asset"] = store.conn.execute(f"SELECT COUNT(*) FROM equation_model_requests WHERE asset_id = ? AND {MODEL_COUNTED}",
                                          (asset_id,)).fetchone()[0]
    return out


def model_answered(store: Store, asset_id: str) -> bool:
    return store.conn.execute("SELECT 1 FROM equation_model_requests WHERE asset_id = ? AND status = 'answered' LIMIT 1",
                              (asset_id,)).fetchone() is not None


def crop_answered(store: Store, asset_id: str, route: str | None) -> bool:
    """The crop route has answered at least one crop of this PDF: a read without a new request can still place something."""
    if route == mathpix.ENGINE:
        return mathpix_answered(store, asset_id)
    return route == equation_model.ENGINE and model_answered(store, asset_id)


def model_refused(store: Store, revision: str | None) -> bool:
    """The provider refused the key on a request sent for this model revision; a new key or default model clears it."""
    return revision is not None and store.conn.execute(
        "SELECT 1 FROM equation_model_requests WHERE reason = 'model_refused' AND model_revision = ? LIMIT 1",
        (revision,)).fetchone() is not None


def model_month_cost(store: Store) -> dict[str, Any]:
    """This calendar month's model requests priced in the spend ledger (D115, the one place their dollars are kept):
    dollars for calls that completed with usage, and how many counted calls have no known cost (reserved or unknown,
    even with partial usage; an error without usage; a model the list does not price)."""
    month = now()[:7]
    counted = store.conn.execute(f"SELECT COUNT(*) FROM equation_model_requests WHERE substr(reserved_at, 1, 7) = ? AND {MODEL_COUNTED}",
                                 (month,)).fetchone()[0]
    priced = store.conn.execute(
        "SELECT COUNT(l.cost_usd) AS n, COALESCE(SUM(l.cost_usd), 0) AS usd FROM spend_ledger l"
        f" JOIN equation_model_requests e ON e.id = l.session_id WHERE substr(e.reserved_at, 1, 7) = ? AND {MODEL_COUNTED}",
        (month,)).fetchone()
    return {"usd": round(priced["usd"], 4), "calls_without_cost": counted - priced["n"]}


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
    """The placed equations of a source, Mathpix or model reading, each with page, n, start and end."""
    version = extraction_version or ""
    if not asset_id or not version.endswith((SOURCE_SUFFIX, MATHPIX_SUFFIX, MODEL_SUFFIX)):
        return []
    row = store.conn.execute("SELECT math_json FROM asset_extractions WHERE asset_id = ? AND extraction_version = ?",
                             (asset_id, extraction_version)).fetchone()
    math = json.loads(row["math_json"] or "{}") if row else {}
    return (math.get("source") or {}).get("placed", []) if version.endswith(SOURCE_SUFFIX) else math.get("placed", [])


def latex_numbers(store: Store, asset_id: str | None, extraction_version: str | None) -> dict[int, list[tuple[int, int, str]]]:
    """Per page of a source, Mathpix or model reading, its placed equations as (start, end, number) in the chunk offset space."""
    found: dict[int, list[tuple[int, int, str]]] = {}
    for item in _placed(store, asset_id, extraction_version):
        found.setdefault(item["page"], []).append((item["start"], item["end"], item["n"]))
    return found


def equation_fallbacks(store: Store, passage: dict[str, Any]) -> list[dict[str, str]] | None:
    """For an `equation_ocr` passage, the PDF's own text-layer lines of each equation read from the page image, for comparison in
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


def crop_provenance(store: Store, asset_id: str, extraction_version: str, page: int, n: str) -> dict[str, Any] | None:
    """A placed Mathpix or model equation's provenance (crop recipe and hash included), from its reading."""
    if not extraction_version.endswith((MATHPIX_SUFFIX, MODEL_SUFFIX)):
        return None
    return next((item for item in _placed(store, asset_id, extraction_version) if item["page"] == page and item["n"] == n), None)


def equation_reader(extraction_version: str | None, store: Store | None = None, asset_id: str | None = None) -> dict[str, Any] | None:
    """Who read the `equation_ocr` equations of an extraction, for labels: Mathpix, or the model (connection and model as
    the reading recorded them)."""
    version = extraction_version or ""
    if version.endswith(MATHPIX_SUFFIX):
        return {"engine": mathpix.ENGINE}
    if not version.endswith(MODEL_SUFFIX):
        return None
    reader = {"engine": equation_model.ENGINE, "connection": None, "model": None}
    if store is not None and asset_id:
        placed = _placed(store, asset_id, extraction_version)
        if placed and isinstance(placed[0].get("reader"), dict):
            reader |= {k: placed[0]["reader"].get(k) for k in ("connection", "model")}
    return reader


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
    """The PDF's equation state and route (see the module's precedence). read; on the arXiv route also no_source (with
    reason), source_waiting, pending, reading and failed; on a crop route (Mathpix, the model) pending, reading, failed,
    no_candidates, none_placed, budget_reached and keys_rejected (Mathpix) or model_refused (the model); `off` with a
    reason when no route reads the PDF."""
    asset = store.asset(asset_id)
    service = getattr(store, "equation_route", None)
    current = asset["extraction_version"] or ""
    if "+marker-" in current:  # an earlier Marker reading, kept (D113)
        return _marker_read(store, asset)
    if current.endswith(SOURCE_SUFFIX):
        row = store.conn.execute("SELECT math_json FROM asset_extractions WHERE asset_id = ? AND outcome = 'current'",
                                 (asset_id,)).fetchone()
        return {"state": "read", "to_check": [], "equations_to_check": 0, "route": arxiv_source.ENGINE,
                "source": source_summary(json.loads(row["math_json"] or "{}") if row else None)}
    if current.endswith(MATHPIX_SUFFIX):  # kept whatever the switch says
        return _crop_read(store, asset, mathpix.ENGINE)
    if current.endswith(MODEL_SUFFIX):
        return _crop_read(store, asset, equation_model.ENGINE)
    if service is None:
        return {"state": "off", "reason": "no_reader"}
    crop = None
    if service.mathpix_ready():
        crop = _mathpix_state
    elif service.model_ready()[0]:
        crop = _model_state
    if service.route_flag() and arxiv_source.posix_available():
        source = _source_state(store, asset)
        return crop(store, asset) if crop is not None and _source_settled(source) else source
    if crop is not None:
        return crop(store, asset)
    if service.route_flag():  # the arXiv route is asked for but cannot run here, and no crop route reads instead
        return {"state": "no_source", "reason": "not_available_on_this_system", "route": arxiv_source.ENGINE}
    return {"state": "off", "reason": service.model_ready()[1], "route": equation_model.ENGINE}


def _source_settled(state: dict[str, Any]) -> bool:
    """The arXiv route's state for a PDF is final: it places nothing more without the person's retry. Pending, reading,
    waiting for the source, a failed extraction with attempts left and a stored source being repaired are not final."""
    if state["state"] == "no_source":
        return state.get("reason") != "cache_corrupt"
    if state["state"] == "failed":
        return not (state.get("reason") == EXTRACTION_FAILED and state.get("attempts", MAX_ATTEMPTS) < MAX_ATTEMPTS)
    return False


def _crop_read(store: Store, asset: dict[str, Any], route: str) -> dict[str, Any]:
    row = store.conn.execute("SELECT math_json FROM asset_extractions WHERE asset_id = ? AND outcome = 'current'", (asset["id"],)).fetchone()
    math = json.loads(row["math_json"] or "{}") if row else {}
    placed = math.get("placed", [])
    summary = {"placed": len(placed), "pages": sorted({p["page"] for p in placed}),
               "refused": dict(Counter(r["reason"] for r in math.get("refused", [])))}
    if route == equation_model.ENGINE:
        summary["reader"] = math.get("reader")
    return {"state": "read", "to_check": [], "equations_to_check": 0, "route": route, route: summary}


def _model_state(store: Store, asset: dict[str, Any]) -> dict[str, Any]:
    """The model route's states, from stored rows only (no PDF is opened)."""
    service = store.equation_route
    choice = equation_model.choice(store)
    route = {"route": equation_model.ENGINE, "reader": {"connection": choice["connection"], "model": choice["model"]} if choice else None}
    reading = _reading(store)
    if reading and reading["asset_id"] == asset["id"] and reading.get("route") == equation_model.ENGINE:
        return {"state": "reading", "pages": reading["pages"], "started_at": reading["started_at"]} | route
    row = store.conn.execute(
        "SELECT rejection_reason, math_json, created_at FROM asset_extractions WHERE asset_id = ? AND extraction_version = ?",
        (asset["id"], model_target_version(asset["extraction_version"]))).fetchone()
    if row is not None:
        math = json.loads(row["math_json"] or "{}")
        if row["rejection_reason"] == NO_CANDIDATES:
            return {"state": "no_candidates"} | route
        if row["rejection_reason"] == NONE_PLACED:
            return {"state": "none_placed", "refused": dict(Counter(r["reason"] for r in math.get("refused", [])))} | route
        return {"state": "failed", "reason": math.get("reason") or row["rejection_reason"],
                "attempts": math.get("attempts", MAX_ATTEMPTS), "at": row["created_at"]} | route
    if model_refused(store, service.model_revision()):
        return {"state": "model_refused"} | route
    counts = model_counts(store, asset["id"])
    if counts["month"] >= counts["budget"] or counts["asset"] >= MAX_ASSET_REQUESTS:
        return {"state": "budget_reached", "month": counts["month"], "budget": counts["budget"], "asset": counts["asset"],
                "stored_answers": model_answered(store, asset["id"])} | route
    return {"state": "pending"} | route


def _mathpix_state(store: Store, asset: dict[str, Any]) -> dict[str, Any]:
    """The Mathpix route's states, from stored rows only (no PDF is opened)."""
    route = {"route": mathpix.ENGINE}
    reading = _reading(store)
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
    reading = _reading(store)
    if reading and reading["asset_id"] == asset["id"] and reading.get("route") not in CROP_ROUTES:
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


def _marker_read(store: Store, asset: dict[str, Any]) -> dict[str, Any]:
    """An earlier Marker reading (D52), kept after Marker was removed (D113): its equations to check against the page."""
    row = store.conn.execute("SELECT math_json FROM asset_extractions WHERE asset_id = ? AND outcome = 'current'", (asset["id"],)).fetchone()
    to_check = json.loads(row["math_json"] or "{}").get("equations_to_check", []) if row else []
    return {"state": "read", "to_check": sorted({e["page"] for e in to_check}), "equations_to_check": len(to_check), "route": "marker"}


QUEUED_STATES = ("pending", "reading", "source_waiting")


def background_read_waiting(store: Store, asset_id: str) -> dict[str, Any] | None:
    """The equation state of a PDF the background reader is reading now or will still read by itself, else None
    (D105: a frozen citation-check plan would go stale when that reading lands). Read as `run_forever` and
    `next_asset` read it: a reader that can run (the arXiv source route, Mathpix or the answer model active), a PDF with
    a successful text extraction not read by Marker earlier, and a state that is pending,
    reading, waiting for its source, or failed with attempts left. A PDF a run is using now still counts: it is read
    once that run ends."""
    service = getattr(store, "equation_route", None)
    if service is None or not (service.route_active() or service.crop_active()):
        return None
    asset = store.conn.execute("SELECT removed_at, extraction_status, extraction_version FROM source_assets WHERE id = ?",
                               (asset_id,)).fetchone()
    if (asset is None or asset["removed_at"] is not None or asset["extraction_status"] not in ("succeeded", "partial")
            or "+marker-" in (asset["extraction_version"] or "")):
        return None
    state = equation_state(store, asset_id)
    if state["state"] in QUEUED_STATES or (state["state"] == "failed" and state.get("attempts", MAX_ATTEMPTS) < MAX_ATTEMPTS):
        return state
    return None


def next_try_at(state: dict[str, Any]) -> str | None:
    """When the background reader tries a waiting PDF next, when the state says: the source route's next attempt, or a
    failed read's time plus `RETRY_AFTER`; None for a PDF pending or being read now."""
    if state["state"] == "source_waiting":
        return state.get("next_at")
    if state["state"] == "failed" and state.get("at"):
        return (datetime.fromisoformat(state["at"]) + RETRY_AFTER).isoformat(timespec="milliseconds")
    return None


def equations_to_check(store: Store, asset_id: str | None, extraction_version: str | None) -> dict[int, int]:
    """Per page of an extraction, how many display equations did not match the PDF's text layer."""
    row = store.conn.execute("SELECT math_json FROM asset_extractions WHERE asset_id = ? AND extraction_version = ?",
                             (asset_id, extraction_version)).fetchone() if asset_id else None
    counts: dict[int, int] = {}
    for equation in json.loads(row["math_json"] or "{}").get("equations_to_check", []) if row else []:
        counts[equation["page"]] = counts.get(equation["page"], 0) + 1
    return counts


class EquationService:
    def __init__(self, store: Store, papers_dir: Path, arxiv_mode: str = "off", data_dir: Path | None = None,
                 fetch_file: Any = None, http_client: Any = None, adapters: dict[str, Any] | None = None):
        self.store, self.papers_dir = store, papers_dir
        # The arXiv source route (D104): its flag, and the stored sources under the data directory.
        self.arxiv_mode = arxiv_mode
        self.sources = arxiv_source.SourceStore(store, data_dir or papers_dir.parent, fetch_file=fetch_file, client=http_client)
        store.equation_route = self  # equation_state reads the route's rules from the store it is given
        # Mathpix (D40): the data directory its request lock lives in and the client its requests go through.
        self.data_dir = data_dir or papers_dir.parent
        self.mathpix_client = http_client
        # The answer model (D113): the app's model connections, by name.
        self.adapters: dict[str, Any] = adapters or {}
        self._task: asyncio.Task | None = None
        self._lock = asyncio.Lock()
        self._retries: set[asyncio.Task] = set()
        self._waiting = 0  # runs and requests waiting for a read; the background reader gives way to them
        self.reading: dict[str, Any] | None = None  # the PDF this service reads now (`_reading`)

    def configure_arxiv_source(self, mode: str, data_dir: Path, fetch_file: Any = None) -> None:
        self.arxiv_mode = mode
        self.sources = arxiv_source.SourceStore(self.store, data_dir, fetch_file=fetch_file or self.sources.fetch_file,
                                                client=self.sources.client)

    def configure_mathpix(self, data_dir: Path, client: Any) -> None:
        self.data_dir, self.mathpix_client = data_dir, client

    def configure_model(self, adapters: dict[str, Any]) -> None:
        self.adapters = adapters

    def mathpix_ready(self) -> bool:
        """The switch is on and a readable key pair is saved: the Mathpix rows of the route table apply."""
        return mathpix_switch(self.store) and isinstance(mathpix.read_pair(), mathpix.Pair)

    def mathpix_active(self) -> bool:
        """Whether PDFs may be read with Mathpix now."""
        return self.mathpix_ready() and self.mathpix_client is not None

    def model_adapter(self) -> tuple[Any, dict[str, Any] | None]:
        choice = equation_model.choice(self.store)
        return (self.adapters.get(choice["connection"]) if choice else None), choice

    def model_ready(self) -> tuple[bool, str | None]:
        """Whether the answer model's rows of the route table apply, else why not: switch_off, no_answer_model,
        connection_unavailable, or model_no_images (the connection has no image input; nothing else is asked)."""
        if not model_switch(self.store):
            return False, "switch_off"
        adapter, choice = self.model_adapter()
        if choice is None:
            return False, "no_answer_model"
        if adapter is None:
            return False, "connection_unavailable"
        if not getattr(adapter, "accepts_images", False):
            return False, "model_no_images"
        return True, None

    def model_revision(self) -> str | None:
        """Connection, model, effort and a fingerprint prefix of the connection's key: a refused key is not asked again
        until one of them changes. Never the key itself."""
        adapter, choice = self.model_adapter()
        if choice is None:
            return None
        key = os.environ.get(getattr(adapter, "key_env", "") or "", "") if adapter is not None else ""
        return "/".join((choice["connection"], choice["model"], choice["reasoning_effort"] or "",
                         key_verification.fingerprint(key)[:12] if key else "nokey"))

    def crop_active(self) -> bool:
        """Whether PDFs may be read from page crops now, by Mathpix or by the answer model."""
        return self.mathpix_active() or self.model_ready()[0]

    def route_flag(self) -> bool:
        return self.arxiv_mode == "auto"

    def route_active(self) -> bool:
        """Whether PDFs may be read from their arXiv source now."""
        return self.route_flag() and arxiv_source.posix_available()

    def route_target(self, asset_id: str) -> bool:
        asset = self.store.asset(asset_id)
        return self.route_active() and "+marker-" not in (asset["extraction_version"] or "")

    async def read_asset(self, asset_id: str, run_id: str | None = None, retry: bool = False, background: bool = False) -> dict[str, Any]:
        """Read one PDF's equations and apply them; returns its state. One PDF is read at a time; a caller waits for the
        PDF being read, then finds its own already read if that was the same one. A failed read is read again when asked
        (`retry`) or while it has attempts left. A run or request stops a background crop read of another PDF between
        two crops; that PDF stays pending and is read later. RunInProgress propagates."""
        if background:
            return await self._read(asset_id, run_id, retry, background)
        self._waiting += 1
        try:
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
                except (KeyboardInterrupt, SystemExit):
                    raise
                except BaseException:
                    break
            try:
                task.result()
            except asyncio.CancelledError:
                pass
            except (KeyboardInterrupt, SystemExit):
                raise
            except BaseException:
                log.exception("Equation read failed while draining cancellation")
            raise

    async def _read(self, asset_id: str, run_id: str | None, retry: bool, background: bool) -> dict[str, Any]:
        async with self._lock:
            state = equation_state(self.store, asset_id)
            if state.get("route") == arxiv_source.ENGINE:
                return await self._read_source(asset_id, run_id, retry, state)
            if state.get("route") in CROP_ROUTES and state["state"] != "off":
                return await self._read_crops(asset_id, run_id, retry, background, state)
            return state

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
                self.reading = {"asset_id": asset_id, "title": title[0] if title else None, "pages": asset["page_count"], "started_at": now(),
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
                    self.reading = None
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
                    if not self.route_flag():
                        return "route_off"
                    return None

                try:
                    report = self.store.reextract_asset(asset_id, base, target, source_chunker, allow_run_id=run_id, guard=guard)
                except NotFound:  # removed before the write began; the guard covers a removal racing the write itself
                    return equation_state(self.store, asset_id) | {"outcome": "asset_removed"}
                return equation_state(self.store, asset_id) | {"outcome": report.get("reason") or report["outcome"]}

        except text_retry.FileBusy:
            return equation_state(self.store, asset_id) | {"outcome": "file_busy"}

    # ---- the crop routes: Mathpix (D40) and the answer model (D113) ------------------------------------------------
    def _send_refusal(self, route: str, asset_id: str, start_version: str | None, start_id: str | None, ctx: Any) -> str | None:
        """The pre-send check, inside the reservation's transaction: why no request may be sent now, or None. `ctx` is the
        Mathpix pair or the model revision the read started with."""
        if route == mathpix.ENGINE:
            if not mathpix_switch(self.store):
                return "switch_off"
            saved = mathpix.read_pair()
            if not isinstance(saved, mathpix.Pair) or saved.revision != ctx.revision:
                return "keys_changed"
        else:
            if not self.model_ready()[0]:
                return "switch_off"
            if self.model_revision() != ctx:
                return "keys_changed"  # the default model, its effort or its key changed since the read started
        asset = self.store.conn.execute("SELECT removed_at, extraction_version FROM source_assets WHERE id = ?", (asset_id,)).fetchone()
        current = self.store.conn.execute("SELECT id FROM asset_extractions WHERE asset_id = ? AND outcome = 'current'", (asset_id,)).fetchone()
        if asset is None or asset["removed_at"] is not None or asset["extraction_version"] != start_version or (current[0] if current else None) != start_id:
            return "extraction_changed"
        if route == mathpix.ENGINE and mathpix_keys_rejected(self.store, ctx):
            return "keys_rejected"
        if route == equation_model.ENGINE and model_refused(self.store, ctx):
            return "model_refused"
        if equation_state(self.store, asset_id).get("route") != route:
            return "route_changed"
        counts = mathpix_counts(self.store, asset_id) if route == mathpix.ENGINE else model_counts(self.store, asset_id)
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
            if refusal := self._send_refusal(mathpix.ENGINE, asset_id, start_version, start_id, pair):
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

    async def _mathpix_answer(self, asset_id: str, start_version: str | None, start_id: str | None, file_sha: str, pair: Any,
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

    def _reserve_model(self, asset_id: str, start_version: str | None, start_id: str | None, file_sha: str, revision: str,
                       choice: dict[str, Any], crop: dict[str, Any]) -> dict[str, Any]:
        """As `_reserve`, for the model: an accepted answer for the same crop, connection, model, effort and prompt
        version is reused; otherwise the pre-send check, then a reserved row."""
        with transaction(self.store.conn):
            row = self.store.conn.execute(
                "SELECT * FROM equation_model_requests WHERE crop_sha256 = ? AND status = 'answered' AND connection = ?"
                " AND requested_model = ? AND IFNULL(reasoning_effort, '') = ? AND prompt_version = ?"
                " ORDER BY answered_at, rowid LIMIT 1",
                (crop["crop_sha256"], choice["connection"], choice["model"], choice["reasoning_effort"] or "",
                 equation_model.PROMPT_VERSION)).fetchone()
            if row is not None:
                return {"outcome": "reused", "row": dict(row)}
            if refusal := self._send_refusal(equation_model.ENGINE, asset_id, start_version, start_id, revision):
                return {"outcome": "stop", "reason": refusal}
            row_id = new_id("eqm")
            attempt = 1 + self.store.conn.execute("SELECT COUNT(*) FROM equation_model_requests WHERE crop_sha256 = ?",
                                                  (crop["crop_sha256"],)).fetchone()[0]
            self.store.conn.execute(
                "INSERT INTO equation_model_requests (id, crop_sha256, asset_id, file_sha256, page, n, attempt, status, connection,"
                " requested_model, reasoning_effort, prompt_version, model_revision, reserved_at)"
                " VALUES (?, ?, ?, ?, ?, ?, ?, 'reserved', ?, ?, ?, ?, ?, ?)",
                (row_id, crop["crop_sha256"], asset_id, file_sha, crop["page"], crop["n"], attempt, choice["connection"],
                 choice["model"], choice["reasoning_effort"], equation_model.PROMPT_VERSION, revision, now()))
        return {"outcome": "send", "row_id": row_id}

    def _finish_model(self, row_id: str, status: str, result: Any = None, latex: str | None = None,
                      reason: str | None = None) -> None:
        with transaction(self.store.conn):
            self.store.conn.execute(
                "UPDATE equation_model_requests SET status = ?, resolved_model = ?, latex = ?, http_status = ?, delivery_class = ?,"
                " error_kind = ?, reason = ?, token_usage_json = ?, answered_at = ? WHERE id = ?",
                (status, getattr(result, "resolved_model", None), latex, getattr(result, "http_status", None),
                 getattr(result, "delivery_class", None), getattr(result, "error_kind", None), reason,
                 json.dumps(result.token_usage) if getattr(result, "token_usage", None) else None, now(), row_id))
            spend.record_equation_request(self.store.conn, row_id)  # the day's spend counts it too (D115)

    async def _model_answer(self, asset_id: str, start_version: str | None, start_id: str | None, file_sha: str, ctx: Any,
                            crop: dict[str, Any]) -> dict[str, Any]:
        """One crop through the answer model: a stored accepted answer, or one request with the crop's PNG and the fixed
        instruction. A completed answer that is not accepted refuses that crop; a failure that stops the read is
        `rate_limited`, `network`, `server_error` or `model_refused` (the key was refused: nothing more is sent)."""
        revision, choice, adapter = ctx
        try:
            async with mathpix.request_lock(self.data_dir, folder="equation-model"):
                reserved = self._reserve_model(asset_id, start_version, start_id, file_sha, revision, choice, crop)
                if reserved["outcome"] != "send":
                    return reserved
                try:
                    result = await adapter.run_step(equation_model.INSTRUCTION, "", equation_model.MESSAGE, equation_model.SCHEMA,
                                                    choice["model"], choice["reasoning_effort"], image_png=crop["png"])
                except Exception:  # noqa: BLE001 - an adapter error after the call left: it may have been processed
                    self._finish_model(reserved["row_id"], "unknown", reason="network")
                    return {"outcome": "stop", "reason": "network"}  # a failed attempt, bounded by MAX_ATTEMPTS
                except BaseException:
                    self._finish_model(reserved["row_id"], "unknown", reason="network")  # cancelled mid-request
                    raise
                if result.status in ("completed", "isolation_violation"):
                    latex, refused = equation_model.accept(result, choice["model"])
                    self._finish_model(reserved["row_id"], "answered" if latex is not None else "error", result, latex, refused)
                    outcome = {"outcome": "answered"} if latex is not None else {"outcome": "refused", "reason": refused}
                else:
                    kind = result.error_kind or "unknown"
                    stop = ("model_refused" if kind in ("auth_failed", "needs_key") else "rate_limited" if kind == "rate_limited"
                            else "network" if result.delivery_class in ("before_send", "after_send_unknown") else "server_error")
                    unsent = result.delivery_class == "before_send"
                    self._finish_model(reserved["row_id"], "unknown" if result.delivery_class == "after_send_unknown" and not unsent
                                       else "error", result, reason=stop)
                    outcome = {"outcome": "stop", "reason": stop}
        except TimeoutError:
            return {"outcome": "stop", "reason": "busy"}  # another DEIXIS process held the request lock too long
        row = dict(self.store.conn.execute("SELECT * FROM equation_model_requests WHERE id = ?", (reserved["row_id"],)).fetchone())
        return outcome | {"row": row}

    def _record_crop(self, route: str, asset: dict[str, Any], version: str, reason: str, math: dict[str, Any]) -> None:
        """A crop reading that writes no text: no candidates, none placed, or a failed attempt (with its count)."""
        self._record_source_rejection(asset, version, reason, None, math, engine=route)
        if "attempts" in math:
            self._events(asset, "equations_failed", {"reason": math.get("reason", reason), "attempts": math["attempts"],
                                                     "route": route})

    def _crop_context(self, route: str) -> Any:
        """What a crop read starts with: the Mathpix pair, or (revision, choice, adapter) for the model; None when the
        route cannot send now."""
        if route == mathpix.ENGINE:
            pair = mathpix.read_pair()
            return pair if isinstance(pair, mathpix.Pair) and self.mathpix_active() else None
        adapter, choice = self.model_adapter()
        return (self.model_revision(), choice, adapter) if self.model_ready()[0] else None

    async def _read_crops(self, asset_id: str, run_id: str | None, retry: bool, background: bool,
                          state: dict[str, Any]) -> dict[str, Any]:
        """One PDF through its crop route (Mathpix or the model). Answers already received are kept and reused by the next
        read. A budget that stops sending does not throw away what was answered: the read places those, and the crops
        left unsent are refused `budget_reached`; a PDF at its budget is read again from stored answers alone. Any other
        stop writes nothing. Every outcome returns the PDF's state; RunInProgress propagates."""
        route = state["route"]
        asset = self.store.asset(asset_id)
        attempts = state.get("attempts", MAX_ATTEMPTS) if state["state"] == "failed" else 0
        cached = state["state"] == "budget_reached" and crop_answered(self.store, asset_id, route)
        if state["state"] not in ("pending", "failed") and not cached \
                or (state["state"] == "failed" and not retry and attempts >= MAX_ATTEMPTS):
            return state
        ctx = self._crop_context(route)
        if ctx is None:
            return state
        answer = self._mathpix_answer if route == mathpix.ENGINE else self._model_answer
        try:
            with self._reader_lock(asset):
                start_version = asset["extraction_version"]
                current = self.store.conn.execute("SELECT id FROM asset_extractions WHERE asset_id = ? AND outcome = 'current'",
                                                  (asset_id,)).fetchone()
                start_id = current[0] if current else None
                target = crop_target_version(route, start_version)
                path = self.papers_dir / asset["storage_path"]
                file_sha = await text_retry.drained_thread(_file_sha256, path)
                if text_retry.HASH.fullmatch(asset["sha256"]) and file_sha != asset["sha256"]:
                    return equation_state(self.store, asset_id) | {"outcome": "file_changed"}
                ocr_pages = self._ocr_pages(asset) if OCR_SUFFIX.search(start_version or "") else {}
                self._forget_failure(asset_id, target)
                title = self.store.conn.execute("SELECT title FROM source_versions WHERE id = ?", (asset["source_version_id"],)).fetchone()
                self.reading = {"asset_id": asset_id, "title": title[0] if title else None, "pages": asset["page_count"],
                                "started_at": now(), "route": route}
                answers: dict[tuple[int, str], dict[str, Any]] = {}
                unsent: list[dict[str, Any]] = []  # crops a budget kept from being sent; stored answers still count
                refused_answers: list[dict[str, Any]] = []  # model answers that were not accepted (D113)
                stop: dict[str, Any] | None = None
                try:
                    found = await text_retry.drained_thread(equation_regions.detect, path, set(ocr_pages))
                    for crop in (c for c in found if "png" in c):
                        if (background and self._waiting) or (run_id and self.store.equation_skip_requested(run_id)):
                            stop = {"reason": "preempted" if background else "skipped"}
                            break
                        result = await answer(asset_id, start_version, start_id, file_sha, ctx, crop)
                        if result["outcome"] == "stop" and result["reason"] == "budget_reached":
                            unsent.append({"page": crop["page"], "n": crop["n"], "reason": "budget_reached"})
                            continue
                        if result["outcome"] == "stop":
                            stop = result
                            break
                        if result["outcome"] == "refused":
                            refused_answers.append({"page": crop["page"], "n": crop["n"], "reason": result["reason"]})
                            continue
                        answers[(crop["page"], crop["n"])] = result
                finally:
                    self.reading = None
                if stop is not None:
                    if stop["reason"] in ("rate_limited", "network", "server_error"):
                        self._record_crop(route, asset, target, f"{route}_failed", {"reason": stop["reason"], "attempts": attempts + 1})
                    return equation_state(self.store, asset_id) | {"outcome": stop["reason"]}
                if not found:
                    self._record_crop(route, asset, target, NO_CANDIDATES, {"candidates": 0})
                    return equation_state(self.store, asset_id)
                if unsent and not answers:
                    return equation_state(self.store, asset_id) | {"outcome": "budget_reached"}
                return await self._place_crops(route, asset, run_id, found, answers, start_version, start_id, target, attempts,
                                               ocr_pages, unsent + refused_answers, ctx)
        except text_retry.FileBusy:
            return equation_state(self.store, asset_id) | {"outcome": "file_busy"}

    def _checked(self, route: str, crop: dict[str, Any], answer: dict[str, Any]) -> tuple[dict[str, Any], dict[str, Any]]:
        """The gate's verdict on one answered crop and the provenance a placed equation keeps."""
        row = answer["row"]
        base = {"box": crop["box"], "crop": crop["crop"], "crop_sha256": crop["crop_sha256"], "request_row_id": row["id"],
                "text_layer": crop["text_layer"]}
        if route == mathpix.ENGINE:
            body = json.loads(row["response_json"] or "null")
            checked = equation_regions.gate(crop, body)
            version = (body or {}).get("version")
            return checked, base | {"request_id": row["request_id"], "provider_version": version if isinstance(version, str) else None,
                                    "confidence": (body or {}).get("confidence"),
                                    "confidence_rate": (body or {}).get("confidence_rate"), "checks": checked["checks"]}
        checked = equation_regions.gate(crop, {"latex_styled": row["latex"]}, require_confidence=False)
        return checked, base | {"checks": checked["checks"],
                                "reader": {"connection": row["connection"], "model": row["requested_model"],
                                           "resolved_model": row["resolved_model"], "reasoning_effort": row["reasoning_effort"],
                                           "prompt_version": row["prompt_version"]}}

    async def _place_crops(self, route: str, asset: dict[str, Any], run_id: str | None, found: list[dict[str, Any]],
                           answers: dict[tuple[int, str], dict[str, Any]], start_version: str | None, start_id: str | None,
                           target: str, attempts: int, ocr_pages: dict[int, str],
                           unsent: list[dict[str, Any]] | None = None, ctx: Any = None) -> dict[str, Any]:
        asset_id = asset["id"]
        unsent = unsent or []
        budget_unsent = [u for u in unsent if u["reason"] == "budget_reached"]
        refused = [{"page": c["page"], "n": c["n"], "reason": c["refused"]} for c in found if "refused" in c] + unsent
        placements, details = [], {}
        requests = sum(1 for a in answers.values() if a["outcome"] == "answered")
        reused = len(answers) - requests
        for crop in (c for c in found if "png" in c and (c["page"], c["n"]) in answers):
            checked, detail = self._checked(route, crop, answers[(crop["page"], crop["n"])])
            if checked["reason"]:
                refused.append({"page": crop["page"], "n": crop["n"], "reason": checked["reason"]})
                continue
            placements.append({"page": crop["page"], "n": crop["n"], "latex": checked["latex"], "number": crop["number"], "lines": crop["lines"]})
            details[(crop["page"], crop["n"])] = detail
        summary = {"candidates": len(found), "requests": requests, "reused": reused}
        if not placements and budget_unsent:  # nothing placeable yet; the crops left unsent may still be read under a new budget
            return equation_state(self.store, asset_id) | {"outcome": "budget_reached"}
        if not placements:
            self._record_crop(route, asset, target, NONE_PLACED, summary | {"refused": refused})
            return equation_state(self.store, asset_id)
        path = self.papers_dir / asset["storage_path"]
        base = await text_retry.drained_thread(lambda: pdf.extract_pdf(path, placements=placements))
        if base.status == "failed":  # a time or memory limit: tried again like a failed read
            self._record_crop(route, asset, target, f"{route}_failed", {"reason": EXTRACTION_FAILED, "attempts": attempts + 1,
                                                                       "error": (base.error or "")[:400]})
            return equation_state(self.store, asset_id)
        placement = base.placement or {"placed": [], "refused": []}
        refused += placement["refused"]
        placed = [{"page": p["page"], "n": p["n"], "start": p["start"], "end": p["end"]} | details[(p["page"], p["n"])]
                  for p in placement["placed"]]
        if not placed and budget_unsent and not placement["refused"]:
            return equation_state(self.store, asset_id) | {"outcome": "budget_reached"}
        if not placed or any(r["reason"] == OFFSETS_UNRESOLVED for r in placement["refused"]):
            self._record_crop(route, asset, target, NONE_PLACED, summary | {"refused": refused})
            return equation_state(self.store, asset_id)
        for page in base.pages:
            page.placement_label = "equation_ocr"
        if ocr_pages:
            base.pages = sorted(base.pages + [pdf.PageText(n, None, text, "ocr") for n, text in ocr_pages.items()
                                              if n not in {p.physical_page for p in base.pages}], key=lambda p: p.physical_page)
            base.status = "succeeded" if len(base.pages) == base.page_count else "partial"
        base.extraction_version = target
        base.math = {"engine": route, "placed": placed, "refused": refused} | summary
        if route == equation_model.ENGINE:
            base.math["reader"] = {"connection": ctx[1]["connection"], "model": ctx[1]["model"],
                                   "reasoning_effort": ctx[1]["reasoning_effort"], "prompt_version": equation_model.PROMPT_VERSION}

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
            if not (self.mathpix_ready() if route == mathpix.ENGINE else self.model_ready()[0]):
                return "switch_off"
            if equation_state(self.store, asset_id).get("route") != route:
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
        return {"pair": {"configured": isinstance(pair, mathpix.Pair), "unreadable": pair == "unreadable" or credentials.status(mathpix.ENV)["broken"],  # the second: skipped at startup (E2)
                         "keychain_unavailable": credentials.status(mathpix.ENV)["keychain_unavailable"],
                         "keychain_pending": credentials.status(mathpix.ENV)["keychain_pending"],
                         "app_id": pair.app_id if isinstance(pair, mathpix.Pair) else None},
                "keys_rejected": mathpix_keys_rejected(self.store, pair), "switch": "on" if mathpix_switch(self.store) else "off",
                "monthly_budget": counts["budget"], "month_requests": counts["month"], "per_pdf_limit": MAX_ASSET_REQUESTS,
                "pdfs": states,
                "reading": self.reading if self.reading and self.reading.get("route") == mathpix.ENGINE else None}

    def model_status(self) -> dict[str, Any]:
        """The Settings tile of the answer model's equation reading (D113): the switch, the model it uses or why it is
        off, this month's requests against the budget with their estimated cost, and the library's PDFs by state."""
        ready, reason = self.model_ready()
        choice = equation_model.choice(self.store)
        states: dict[str, int] = {}
        for row in self.store.conn.execute("SELECT id FROM source_assets WHERE removed_at IS NULL AND extraction_status IN ('succeeded', 'partial')"):
            state = equation_state(self.store, row[0])
            if state.get("route") == equation_model.ENGINE:
                states[state["state"]] = states.get(state["state"], 0) + 1
        counts = model_counts(self.store)
        return {"switch": "on" if model_switch(self.store) else "off", "ready": ready, "reason": reason,
                "model": {"connection": choice["connection"], "model": choice["model"],
                          "reasoning_effort": choice["reasoning_effort"]} if choice else None,
                "model_refused": model_refused(self.store, self.model_revision()), "mathpix_first": self.mathpix_ready(),
                "monthly_budget": counts["budget"], "month_requests": counts["month"], "per_pdf_limit": MAX_ASSET_REQUESTS,
                "month_cost": model_month_cost(self.store), "pdfs": states,
                "reading": self.reading if self.reading and self.reading.get("route") == equation_model.ENGINE else None}

    async def mathpix_estimate(self) -> dict[str, Any]:
        """Before the switch is turned on: how many PDFs Mathpix would read and an upper bound of requests (the detector's
        count, capped per PDF and by what is left of the month's budget). Nothing is sent."""
        pdfs, crops = 0, 0
        for row in self.store.conn.execute("SELECT * FROM source_assets WHERE removed_at IS NULL AND extraction_status IN ('succeeded', 'partial')"):
            asset = dict(row)
            current = asset["extraction_version"] or ""
            if "+marker-" in current or current.endswith((SOURCE_SUFFIX, MATHPIX_SUFFIX, MODEL_SUFFIX)):
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
            " AND IFNULL(a.extraction_version, '') NOT LIKE '%+marker-%'"
            " AND NOT EXISTS (SELECT 1 FROM corpus_memberships m JOIN runs r ON r.research_id = m.research_id"
            "  WHERE m.source_version_id = a.source_version_id AND r.status IN ('queued', 'running', 'pause_requested'))"
            " ORDER BY EXISTS (SELECT 1 FROM selections s WHERE s.source_version_id = a.source_version_id AND s.state = 'included') DESC,"
            " a.retrieved_at DESC"
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
            # The arXiv source route when its flag is on (D104), Mathpix or the answer model when they can send.
            asset_id = self.next_asset() if self.route_active() or self.crop_active() else None
            if asset_id is None:
                await asyncio.sleep(RETRY_SECONDS)
                continue
            try:
                state = await self.read_asset(asset_id, background=True)
                if state.get("outcome") == "file_busy" or (state.get("route") and state["state"] == "pending"):
                    await asyncio.sleep(RETRY_SECONDS)  # the rate gate was busy: give way before trying again
            except RunInProgress:
                await asyncio.sleep(RETRY_SECONDS)  # applied after the run that uses the source ends
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
        tasks = tuple(t for t in (self._task, *self._retries) if t is not None)
        self._task = None
        for task in tasks:
            task.cancel()
        for task in tasks:
            try:
                await self._drain(task)
            except asyncio.CancelledError:
                pass
            except Exception:
                log.exception("Equation task failed during shutdown")


def _file_sha256(path: Path) -> str:
    import hashlib

    digest = hashlib.sha256()
    with open(path, "rb") as handle:
        for chunk in iter(lambda: handle.read(1 << 20), b""):
            digest.update(chunk)
    return digest.hexdigest()
