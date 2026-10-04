"""Model-free D141 corpus description, byte manifests and guarded copies.

Only stored SQLite records are read. No API, adapter, model or provider is called.
Evidence counts are distinct works, unless explicitly named `records`. Missing
positive evidence is `bilinmiyor`; zeros in a complete current-state partition
mean an observed empty set. No rates or cross-corpus totals are produced.
"""

from __future__ import annotations

import argparse
from collections import Counter
from contextlib import contextmanager
import hashlib
import json
import os
from pathlib import Path
import re
import sqlite3
import stat
import subprocess
import sys
from typing import Any, Iterator
import unicodedata

# Direct invocation uses the same checkout-local import path as the tests.
if __package__ in (None, ""):
    sys.path.insert(0, str(Path(__file__).resolve().parents[2] / "backend"))

# Frozen priority, using the SAME derivations as the product view (not just
# stage_decisions.next_step, which misses staleness and version disagreements).
# `not tried` means no recorded download attempt, not proof no request occurred.
# PDF lookups alone (pdf_discovery_runs) are not download attempts.
PRIMARY_CATEGORY_FIELDS = {
    "in review queue": "queue.queue_rows(Store, research_id)['rows'][*].work_id",
    "PDF waiting, fetch tried": "waiting.for_context(queue.context(...))[1] AND recorded fetch work_id",
    "PDF waiting, not tried": "waiting.for_context(queue.context(...))[1] AND no recorded fetch work_id",
    "other": "pending head selection AND none of the preceding predicates",
}
# Fetch evidence: run_steps.kind='fetch_pdf', operation_key='fetch:<version>',
# started_at/attempt; pdf_candidates.attempted_at joined through
# pdf_discovery_runs.research_id. The latter stores the LAST attempt only.
# Head selection: Store.work_heads -> selections.state, NOT a winning decision
# recomputed and written back. Queue and waiting functions only SELECT records.
UNKNOWN = "bilinmiyor"
UNMEASURED = "ölçülemedi"


class MeasurementRefused(ValueError):
    """Input cannot be used under the frozen read/copy rules."""


def canonical(value: Any) -> bytes:
    return json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(",", ":")).encode("utf-8")


def checked_dir(path: Path) -> Path:
    path = Path(path).absolute()
    if path.is_symlink():
        raise MeasurementRefused(f"symlink directory: {path}")
    if not path.is_dir():
        raise MeasurementRefused(f"not a directory: {path}")
    return path.resolve()


def manifest(src: Path) -> dict[str, Any]:
    """Hash regular files without following links; include WAL/SHM like any file.

    Directories have no stable byte hash/size/nlink across copies and are not
    manifest entries. Special files are refused, including sockets and FIFOs.
    An fstat before/after hashing also refuses a file replaced/changed mid-read.
    """
    root = checked_dir(src)
    files = []
    def fail_walk(exc: OSError) -> None:
        raise exc

    for folder, dirs, names in os.walk(root, followlinks=False, onerror=fail_walk):
        for name in sorted(dirs + names):
            path = Path(folder) / name
            meta = path.lstat()
            if stat.S_ISLNK(meta.st_mode) or not path.resolve().is_relative_to(root):
                raise MeasurementRefused(f"symlink or escaping path: {path}")
            if stat.S_ISDIR(meta.st_mode):
                continue
            if not stat.S_ISREG(meta.st_mode):
                raise MeasurementRefused(f"non-regular file: {path}")
            if meta.st_nlink > 1:
                raise MeasurementRefused(f"hard link (nlink={meta.st_nlink}): {path}")
            digest = hashlib.sha256()
            fd = os.open(path, os.O_RDONLY | os.O_NOFOLLOW)
            with os.fdopen(fd, "rb") as stream:
                before = os.fstat(stream.fileno())
                if (before.st_dev, before.st_ino) != (meta.st_dev, meta.st_ino):
                    raise MeasurementRefused(f"file replaced: {path}")
                while chunk := stream.read(1024 * 1024):
                    digest.update(chunk)
                after = os.fstat(stream.fileno())
            keys = ("st_dev", "st_ino", "st_size", "st_mtime_ns", "st_ctime_ns", "st_nlink")
            if before.st_nlink > 1 or any(getattr(before, k) != getattr(after, k) for k in keys):
                raise MeasurementRefused(f"file changed while hashing: {path}")
            files.append({"path": path.relative_to(root).as_posix(), "byte_size": after.st_size,
                          "sha256": digest.hexdigest(), "nlink": after.st_nlink, "type": "file"})
    body = {"version": 1, "files": sorted(files, key=lambda row: row["path"])}
    return body | {"sha256": hashlib.sha256(canonical(body)).hexdigest()}


def outside(path: Path, *roots: Path, directory: bool = False) -> Path:
    target = path.absolute()
    if target.is_symlink() or any(target.resolve().is_relative_to(root.resolve()) for root in roots):
        raise MeasurementRefused(f"output must be outside input directories and not a symlink: {path}")
    if target.exists():
        meta = target.lstat()
        if directory and stat.S_ISDIR(meta.st_mode):
            return target
        if not stat.S_ISREG(meta.st_mode) or meta.st_nlink > 1:
            raise MeasurementRefused(f"output must be an unlinked regular file: {path}")
    return target


def write_json(path: Path, value: Any) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(value, ensure_ascii=False, indent=2, sort_keys=True) + "\n", encoding="utf-8")


def library_idle(src: Path) -> dict[str, Any]:
    """Fail closed on an unavailable/ambiguous lsof check; no holders is exit 1."""
    paths = []
    for path in sorted(src.glob("library.sqlite*")):
        meta = path.lstat()
        if not stat.S_ISREG(meta.st_mode) or meta.st_nlink > 1:
            raise MeasurementRefused(f"unsafe lsof target: {path}")
        paths.append(str(path))
    if not paths:
        raise MeasurementRefused("no library.sqlite* files for lsof check")
    result = subprocess.run(["lsof", "-nP", "-F", "p", *paths], capture_output=True, text=True, check=False)
    record = {"returncode": result.returncode, "stdout": result.stdout, "stderr": result.stderr,
              "files": paths}
    if result.returncode != 1 or result.stdout.strip() or result.stderr.strip():
        raise MeasurementRefused(f"lsof did not establish no holders: {record}")
    return record


def copy_record_path(dst: Path) -> Path:
    return dst.with_name(dst.name + ".copy-record.json")


def normalized_manifest_files(value: Any) -> dict[str, dict[str, Any]]:
    """Compare kit and H9b entries without wrapper metadata or file type."""
    rows = value.get("files") if isinstance(value, dict) else value
    if not isinstance(rows, list):
        raise MeasurementRefused("manifest must contain a file list")
    files = {}
    for row in rows:
        if not isinstance(row, dict):
            raise MeasurementRefused("manifest file must be an object")
        path = row.get("path")
        size = row.get("byte_size", row.get("size"))
        sha256, nlink = row.get("sha256"), row.get("nlink")
        if (not isinstance(path, str) or not path or path in files
                or type(size) is not int or size < 0
                or not isinstance(sha256, str) or re.fullmatch(r"[0-9a-f]{64}", sha256) is None
                or type(nlink) is not int or nlink < 1
                or ("byte_size" in row and "size" in row and row["size"] != size)):
            raise MeasurementRefused("invalid or duplicate manifest file entry")
        files[path] = {"path": path, "size": size, "sha256": sha256, "nlink": nlink}
    return files


def copy_library(src: Path, dst: Path, *, trusted_manifest: Path | None = None) -> dict[str, Any]:
    """Only lsof metadata, manifest hashing and cp -Rp access the source.

    The sidecar record is outside both directories, so it cannot invalidate the
    copied manifest. An unusable destination is retained for diagnosis.
    """
    src = checked_dir(src)
    dst = outside(dst, src, directory=True)
    record_path = outside(copy_record_path(dst), src, dst)
    record: dict[str, Any] = {"source": str(src), "destination": str(dst.resolve()), "usable": False,
                              "status": UNMEASURED, "model_sessions": 0, "provider_requests": 0}
    try:
        if dst.exists():
            raise MeasurementRefused("destination must not exist")
        record["lsof"] = library_idle(src)
        record["source_manifest"] = manifest(src)
        if trusted_manifest is not None:
            trusted = json.loads(outside(trusted_manifest, src, dst).read_text(encoding="utf-8"))
            record["trusted_manifest"] = trusted
            trusted_files = normalized_manifest_files(trusted)
            source_files = normalized_manifest_files(record["source_manifest"])
            record["trusted_manifest_equal"] = trusted_files == source_files
            record["trusted_manifest_differences"] = [
                {"path": path,
                 "change": "added" if path not in trusted_files else "removed" if path not in source_files else "changed",
                 "trusted": trusted_files.get(path), "source": source_files.get(path)}
                for path in sorted(trusted_files.keys() | source_files.keys())
                if trusted_files.get(path) != source_files.get(path)
            ]
        dst.parent.mkdir(parents=True, exist_ok=True)
        result = subprocess.run(["cp", "-Rp", str(src), str(dst)], capture_output=True, text=True, check=False)
        record["cp"] = {"returncode": result.returncode, "stderr": result.stderr}
        if result.returncode:
            raise MeasurementRefused("cp -Rp failed")
        record["source_after_manifest"] = manifest(src)
        record["copy_manifest"] = manifest(dst)
        record["manifests_equal"] = (
            record["source_manifest"] == record["source_after_manifest"] == record["copy_manifest"])
        if not record["manifests_equal"]:
            raise MeasurementRefused("source-before, source-after and copy manifests differ; copy unusable")
        record.update(usable=True, status="measured")
    except (OSError, ValueError, KeyError, TypeError) as exc:
        record["reason"] = str(exc)
    write_json(record_path, record)
    return record


@contextmanager
def open_readonly(data_dir: Path) -> Iterator[sqlite3.Connection]:
    """Single read transaction; never use storage.db.connect or migrate.

    immutable=1 prevents SQLite creating/updating journal/SHM files. It can
    ignore committed WAL frames, so ANY nonempty WAL is refused first. The
    standard Python connection has no read-only SHM VFS; do not weaken the
    no-write rule or silently checkpoint to make that corpus measurable.
    The caller must supply a quiescent byte copy, not a live database.
    """
    root = checked_dir(data_dir)
    for name in ("library.sqlite", "library.sqlite-wal", "library.sqlite-shm"):
        path = root / name
        if path.is_symlink():
            raise MeasurementRefused(f"symlink SQLite file: {name}")
        if path.exists() and (not path.is_file() or path.stat().st_nlink > 1):
            raise MeasurementRefused(f"unsafe SQLite file: {name}")
    wal = root / "library.sqlite-wal"
    if wal.exists() and wal.stat().st_size:
        raise MeasurementRefused("nonempty WAL: cannot guarantee read-only SHM handling; no writable fallback")
    if not (root / "library.sqlite").is_file():
        raise MeasurementRefused("library.sqlite is missing")
    conn = sqlite3.connect((root / "library.sqlite").as_uri() + "?mode=ro&immutable=1", uri=True,
                           isolation_level=None)
    conn.row_factory = sqlite3.Row
    try:
        conn.execute("BEGIN")
        conn.execute("SELECT name FROM sqlite_master LIMIT 1").fetchall()
        yield conn
    finally:
        if conn.in_transaction:
            conn.execute("ROLLBACK")
        conn.close()


def _tokens(value: str) -> tuple[str, ...]:
    folded = unicodedata.normalize("NFKD", value).encode("ascii", "ignore").decode().casefold()
    return tuple(re.findall(r"[^\W_]+", folded))


def read_chain(path: Path) -> dict[str, Any]:
    """Only the frozen version-2 NLP G; identity rules follow measure_lineage."""
    chain = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(chain, dict):
        raise MeasurementRefused("chain file is not a JSON object defining frozen G")
    expected = {
        "elmo": ("deep contextualized word representations", "peters", [2018]),
        "bert": ("bert pre training of deep bidirectional transformers for language understanding", "devlin", [2018, 2019]),
        "roberta": ("roberta a robustly optimized bert pretraining approach", "liu", [2019, 2020]),
        "albert": ("albert a lite bert for self supervised learning of language representations", "lan", [2019, 2020]),
    }
    works = chain.get("works", [])
    pairs = chain.get("pairs", [])
    if (chain.get("version") != 2 or len(works) != 4 or {w["key"] for w in works} != set(expected)
            or {tuple(pair) for pair in pairs} != {("elmo", "bert"), ("bert", "roberta"), ("bert", "albert")}
            or len(pairs) != 3
            or any((_tokens(w.get("match", "")), w.get("first_author"), w.get("years"))
                   != (_tokens(expected[w["key"]][0]), *expected[w["key"]][1:]) for w in works)):
        raise MeasurementRefused("chain file does not define the frozen four-work NLP G")
    return chain


def chain_status(chain: dict[str, Any], versions: list[dict[str, Any]], states: dict[str, str]) -> dict[str, Any]:
    found = []
    for work in chain["works"]:
        tokens = _tokens(work["match"])
        title_hits = [v for v in versions if _tokens(v["title"])[:len(tokens)] == tokens]
        matches = [v for v in title_hits if v["year"] in work["years"]
                   and work["first_author"].casefold() in _tokens(" ".join(json.loads(v["authors_json"])[:1]))]
        ids = sorted({v["work_id"] for v in matches})
        found.append({"key": work["key"], "found": bool(ids), "status": "found" if ids else "not found",
                      "final_status": states.get(ids[0], UNKNOWN) if len(ids) == 1 else UNKNOWN if ids else "not found",
                      "works": [{"work_id": wid, "final_status": states.get(wid, UNKNOWN)} for wid in ids],
                      "identity_rejected_version_ids": sorted(v["id"] for v in title_hits if v not in matches)})
    return {"status": "measured", "works": found}


def research_counts(conn: sqlite3.Connection, research: dict[str, Any], chain: dict[str, Any] | None) -> dict[str, Any]:
    # Imported here so manifest/copy do not load any product modules.
    from deixis.workflow import queue, waiting
    from deixis.workflow.store import Store

    rid = research["id"]
    missing: list[dict[str, str]] = []

    def unknown(quantity: str, reason: str = "no stored record") -> str:
        entry = {"quantity": quantity, "reason": reason}
        if entry not in missing:
            missing.append(entry)
        return UNKNOWN

    def evidence_count(quantity: str, ids: Any) -> int | str:
        return len(set(ids)) if ids else unknown(quantity)

    def rows(query: str, args: tuple[Any, ...] = (rid,), *, optional: bool = True) -> list[dict[str, Any]]:
        try:
            return [dict(row) for row in conn.execute(query, args)]
        except sqlite3.OperationalError as exc:
            if not optional or not str(exc).startswith(("no such table:", "no such column:")):
                raise
            unknown("stored_schema", str(exc))
            return []

    versions = rows("SELECT v.*, m.removed_at AS membership_removed_at FROM corpus_memberships m"
                    " JOIN source_versions v ON v.id=m.source_version_id WHERE m.research_id=?", optional=False)
    work_of = {v["id"]: v["work_id"] for v in versions}
    active = [v for v in versions if v["membership_removed_at"] is None]
    store = Store(conn)
    heads = store.work_heads(rid)
    selections = {row["source_version_id"]: row for row in rows("SELECT * FROM selections WHERE research_id=?")}
    states = {wid: selections[head]["state"] if head in selections else unknown("final_membership", f"no selection: {head}")
              for wid, head in heads.items()}
    for wid in {v["work_id"] for v in active} - states.keys():
        states[wid] = unknown("final_membership", f"no product head for active work: {wid}")
    for wid in set(work_of.values()) - states.keys():
        states[wid] = "removed"
    final = dict(Counter(states.values()))
    # Complete enumeration supports zero current members of a state.
    final = {state: final.get(state, 0) for state in ("included", "excluded", "pending", "removed", UNKNOWN)}
    decisions = rows("SELECT * FROM stage_decisions WHERE research_id=? ORDER BY created_at, rowid")
    selection_changes = rows("SELECT * FROM selection_history WHERE research_id=? ORDER BY created_at, id")
    automatic = {}
    for actor in ("model_agreement", "code"):
        automatic[actor] = {}
        for kind, outcomes in (("included", {"include"}), ("excluded", {"out_of_scope", "criterion_not_met"})):
            found = [d for d in decisions if d["decided_by"] == actor and d["outcome"] in outcomes]
            key = f"automatic_decisions.{actor}.{kind}"
            automatic[actor][kind] = {"records": len(found) if found else unknown(key + ".records"),
                                      "works": evidence_count(key + ".works", [work_of[d["source_version_id"]] for d in found])}
    try:
        origins = queue.decision_origins(store, rid)
    except sqlite3.OperationalError as exc:
        if not str(exc).startswith(("no such table:", "no such column:")):
            raise
        origins = {}
        unknown("k03_queue_origin", str(exc))
    k03 = [d for d in decisions if origins.get(d["id"]) == queue.QUEUE]
    unlocated = [d["id"] for d in decisions if d["decided_by"] == "human"
                 and origins.get(d["id"], queue.UNKNOWN) == queue.UNKNOWN]
    if unlocated:
        unknown("k03_queue_origin", f"no unambiguous queue event: {', '.join(unlocated)}")
    k03_links = rows("SELECT * FROM human_selection_links WHERE research_id=?")
    k03_ids = {d["id"] for d in k03}
    k03_effect = [link for link in k03_links if link["decision_id"] in k03_ids]
    queue_decisions = {"records": len(k03) if k03 else unknown("k03_queue_decisions.records"),
                       "by_reason": dict(Counter(d["reason_code"] for d in k03)) if k03 else UNKNOWN,
                       "selection_effect_records": len(k03_effect) if k03_effect else unknown("k03_selection_effect.records"),
                       "selection_effect_works": evidence_count("k03_selection_effect.works", [work_of[l["head"]] for l in k03_effect]),
                       "unknown_origin_decision_ids": unlocated}
    steps = rows("SELECT s.*, r.kind AS run_kind FROM run_steps s JOIN runs r ON r.id=s.run_id WHERE r.research_id=?")
    direct = [s for s in steps if s["kind"] == "fetch_pdf" and s["operation_key"].startswith("fetch:")
              and (s["started_at"] is not None or s["attempt"] > 0)]
    for step in direct:
        if step["operation_key"][6:] not in work_of:
            unknown("fetch_work_identity", f"version not in corpus: {step['operation_key']}")
    candidates = rows("SELECT c.* FROM pdf_candidates c JOIN pdf_discovery_runs d ON d.id=c.discovery_run_id"
                      " WHERE d.research_id=?")
    tried_candidates = [c for c in candidates if c["attempted_at"] is not None]
    attempted = {work_of[s["operation_key"][6:]] for s in direct if s["operation_key"][6:] in work_of}
    attempted |= {work_of[c["source_version_id"]] for c in tried_candidates if c["source_version_id"] in work_of}
    if tried_candidates:
        unknown("pdf_candidate_attempt_history", "pdf_candidates retains only the last attempt; no exact historical request total")
    # Candidate ownership is the most recent discovery run; historical research
    # attribution cannot be recovered if another research refreshed that row.
    unknown("pdf_candidate_historical_research_attribution", "pdf_candidates.discovery_run_id can be replaced")
    failures = Counter(s["error_code"] or UNKNOWN for s in direct if s["status"] == "failed")
    candidate_failures = Counter(c["error_code"] or UNKNOWN for c in tried_candidates
                                 if c["access_status"] != "downloaded")
    if UNKNOWN in failures or UNKNOWN in candidate_failures:
        unknown("fetch_failure_code", "stored failed attempt has null error_code")
    assets = rows("SELECT a.* FROM source_assets a JOIN corpus_memberships m ON m.source_version_id=a.source_version_id"
                  " WHERE m.research_id=?")
    downloads = {work_of[a["source_version_id"]] for a in assets if a["origin"] == "download" and a["media_type"] == "application/pdf"}
    downloads |= {work_of[c["source_version_id"]] for c in tried_candidates
                  if c["access_status"] == "downloaded" and c["source_version_id"] in work_of}
    extracts = rows("SELECT e.*, a.source_version_id FROM asset_extractions e JOIN source_assets a ON a.id=e.asset_id"
                    " JOIN corpus_memberships m ON m.source_version_id=a.source_version_id WHERE m.research_id=?")
    extracted = {work_of[e["source_version_id"]] for e in extracts if e["text_pages"] > 0 and e["passage_count"] > 0
                 and e["status"] in ("succeeded", "partial") and e["outcome"] != "rejected"}
    sent = rows("SELECT DISTINCT i.id, i.payload_json FROM step_inputs i JOIN model_sessions s ON s.step_input_id=i.id"
                " WHERE i.research_id=? AND s.research_id=i.research_id AND s.run_id=i.run_id AND s.step_id=i.step_id"
                " AND (s.status='completed' OR length(s.raw_output)>0)")
    uncertain_sessions = rows("SELECT s.id FROM model_sessions s WHERE s.research_id=? AND s.status!='completed'"
                              " AND (s.raw_output IS NULL OR length(s.raw_output)=0)")
    if uncertain_sessions:
        unknown("model_delivery", "sessions without a recorded response cannot establish text delivery")
    candidate_work = {c["id"]: c["work_id"] for c in rows(
        "SELECT c.id,v.work_id FROM candidates c JOIN source_versions v ON v.id=c.source_version_id WHERE c.research_id=?")}
    abstracts: set[str] = set()
    pdf_text: set[str] = set()
    passage_records = {p["id"]: p for p in rows(
        "SELECT p.*, a.media_type FROM passages p LEFT JOIN source_assets a ON a.id=p.asset_id"
        " JOIN corpus_memberships m ON m.source_version_id=p.source_version_id WHERE m.research_id=?")}
    for item in sent:
        payload = json.loads(item["payload_json"])
        for candidate in payload.get("candidates", []):
            if candidate.get("abstract"):
                wid = candidate_work.get(candidate["candidate_id"])
                if wid is None:
                    unknown("abstract_input_identity", f"unresolved candidate: {candidate['candidate_id']}")
                else:
                    abstracts.add(wid)
        for passage in payload.get("passages", []):
            if not passage.get("text"):
                continue
            stored = passage_records.get(passage.get("passage_id"))
            if stored is None or stored["source_version_id"] != passage.get("source_id"):
                unknown("model_passage_identity", f"unresolved or mismatched passage: {passage.get('passage_id')}")
                continue
            wid = work_of[stored["source_version_id"]]
            kind = stored["kind"]
            if kind == "abstract":
                abstracts.add(wid)
            elif kind in ("pdf_page", "section") and stored["media_type"] == "application/pdf":
                pdf_text.add(wid)
    queue_ids: set[str] | None = None
    waiting_ids: set[str] | None = None
    try:
        ctx = queue.context(store, rid)
        queue_ids = {row["work_id"] for row in queue.queue_rows(store, rid)["rows"]}
        waiting_ids = waiting.for_context(ctx)[1]
    except queue.QueueUnavailable:
        unknown("queue_membership", "legacy workflow has no product queue")
        unknown("pdf_waiting", "legacy workflow has no product PDF waiting list")
    except sqlite3.OperationalError as exc:
        if not str(exc).startswith(("no such table:", "no such column:")):
            raise
        queue_ids = waiting_ids = None
        unknown("queue_membership", str(exc))
        unknown("pdf_waiting", str(exc))
    pending = {wid for wid, state in states.items() if state == "pending"}
    primary: dict[str, list[str]] = {key: [] for key in PRIMARY_CATEGORY_FIELDS}
    for wid in sorted(pending):
        if queue_ids is None or waiting_ids is None:
            break
        category = ("in review queue" if wid in queue_ids else
                    "PDF waiting, fetch tried" if wid in waiting_ids and wid in attempted else
                    "PDF waiting, not tried" if wid in waiting_ids else "other")
        primary[category].append(wid)
    primary_counts = {key: len(ids) for key, ids in primary.items()} if queue_ids is not None else unknown("pending_primary_categories")
    runs = rows("SELECT id, scope_revision, kind, status, pause_reason, error_json, created_at, updated_at"
                " FROM runs WHERE research_id=? ORDER BY created_at, id")
    result = {"research": research, "runs": runs, "denominator": len(set(work_of.values())),
              "source_versions": len(versions), "active_unique_works": len({v["work_id"] for v in active}),
              "active_source_versions": len(active), "abstract_read_by_model": evidence_count("abstract_read_by_model", abstracts),
              "automatic_decisions_history": automatic, "final_membership": final,
              "selection_changes_history": {"records": len(selection_changes) if selection_changes else unknown("selection_changes_history"),
                  "by_origin_and_new_state": dict(sorted(Counter(f"{s['origin']}:{s['new_state']}" for s in selection_changes).items()))},
              "final_status_by_work": dict(sorted(states.items())), "k03_queue_decisions": queue_decisions,
              "pending_primary_counts": primary_counts, "pending_primary_work_ids": primary if queue_ids is not None else UNKNOWN,
              "overlapping_dimensions": {"queue_work_ids": sorted(queue_ids) if queue_ids is not None else UNKNOWN,
                  "queue_works": len(queue_ids) if queue_ids is not None else UNKNOWN,
                  "pending_queue_works": len(pending & queue_ids) if queue_ids is not None else UNKNOWN,
                  "pdf_waiting_work_ids": sorted(waiting_ids) if waiting_ids is not None else UNKNOWN,
                  "pdf_waiting_works": len(waiting_ids) if waiting_ids is not None else UNKNOWN,
                  "pending_pdf_waiting_works": len(pending & waiting_ids) if waiting_ids is not None else UNKNOWN,
                  "recorded_fetch_works": evidence_count("recorded_fetch_works", attempted),
                  "recorded_fetch_work_ids": sorted(attempted) if attempted else unknown("recorded_fetch_work_ids")},
              "fulltext": {"attempted": evidence_count("fulltext.attempted", attempted),
                  "successful_download": evidence_count("fulltext.successful_download", downloads),
                  "extracted_pdf_text": evidence_count("fulltext.extracted_pdf_text", extracted),
                  "text_given_to_model": evidence_count("fulltext.text_given_to_model", pdf_text),
                  "direct_fetch_records": len(direct) if direct else unknown("direct_fetch_records"),
                  "last_candidate_attempt_records": len(tried_candidates) if tried_candidates else unknown("last_candidate_attempt_records"),
                  "direct_fetch_failures_by_stored_code": dict(sorted(failures.items())) if failures else unknown("direct_fetch_failures"),
                  "last_candidate_failures_by_stored_code": dict(sorted(candidate_failures.items())) if candidate_failures else unknown("candidate_fetch_failures")},
              "missing": missing}
    if chain is not None:
        result["frozen_G"] = chain_status(chain, versions, states)
        for work in result["frozen_G"]["works"]:
            if work["final_status"] == UNKNOWN:
                unknown("frozen_G.final_status", f"missing or ambiguous work identity/status for {work['key']}")
    return result


def count(data_dir: Path, *, label: str, product_commit: str, prep_rule: str,
          chain_file: Path | None = None) -> dict[str, Any]:
    result: dict[str, Any] = {"version": 1, "label": label, "product_commit": product_commit, "prep_rule": prep_rule,
                              "model_sessions": 0, "provider_requests": 0, "status": UNMEASURED,
                              "primary_category_fields": PRIMARY_CATEGORY_FIELDS,
                              "notes": ["Descriptive counts per research; no rates or cross-corpus totals.",
                                  "Denominator includes retained memberships, including removed works; active counts are separate.",
                                  "Abstract read means text in an input with a recorded model response, not verified cognitive reading.",
                                  "PDF assets and extractions are library history for member versions, not research-specific acquisition causality.",
                                  "Fetch counts describe stored direct steps and last candidate attempts, not exact HTTP request totals.",
                                  "Selection-change history overlaps stage decisions; code_rule origin does not identify a model/code decider.",
                                  "not tried means no recorded download attempt; unknown absence is not proof of zero requests."],
                              "missing": []}
    chain = None
    if chain_file is not None:
        try:
            chain = read_chain(chain_file)
        except (OSError, ValueError, KeyError, TypeError) as exc:
            result["frozen_G"] = {"status": UNMEASURED, "reason": str(exc)}
            result["missing"].append({"quantity": "frozen_G", "reason": str(exc)})
    try:
        root = checked_dir(data_dir)
        record_path = outside(copy_record_path(root), root)
        if not record_path.is_file():
            raise MeasurementRefused("copy record is missing; original libraries cannot be counted")
        record = json.loads(record_path.read_text(encoding="utf-8"))
        if (not isinstance(record, dict) or record.get("usable") is not True
                or record.get("destination") != str(root)
                or record.get("source") == str(root)
                or record.get("source_manifest") != record.get("copy_manifest")
                or "source_after_manifest" not in record
                or record["source_after_manifest"] != record.get("copy_manifest")
                or manifest(root) != record.get("copy_manifest")):
            raise MeasurementRefused("copy record/manifest does not establish a usable copy")
        with open_readonly(root) as conn:
            researches = [dict(row) for row in conn.execute("SELECT * FROM researches ORDER BY created_at, id")]
            result["researches"] = [research_counts(conn, research, chain) for research in researches]
        result["status"] = "measured"
    except (OSError, ValueError, sqlite3.DatabaseError, KeyError, TypeError) as exc:
        result.pop("researches", None)
        result["reason"] = str(exc)
    return result


def markdown(result: dict[str, Any]) -> str:
    # JSON inside Markdown retains all history/dimensions/unknowns without a
    # second summary that could collapse provenance or silently drop categories.
    return "# D141 funnel counts\n\nDescriptive stored evidence.\n\n```json\n" + json.dumps(
        result, ensure_ascii=False, indent=2, sort_keys=True) + "\n```\n"


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    commands = parser.add_subparsers(dest="command", required=True)
    p = commands.add_parser("manifest")
    p.add_argument("src_dir", type=Path)
    p.add_argument("out", type=Path)
    p = commands.add_parser("copy")
    p.add_argument("src_dir", type=Path)
    p.add_argument("dst_dir", type=Path)
    p.add_argument("--trusted-manifest", type=Path)
    p = commands.add_parser("count")
    p.add_argument("data_dir", type=Path)
    p.add_argument("--label", required=True)
    p.add_argument("--product-commit", required=True)
    p.add_argument("--prep-rule", required=True)
    p.add_argument("--out", required=True, type=Path)
    p.add_argument("--md", type=Path)
    p.add_argument("--chain-file", type=Path)
    args = parser.parse_args(argv)
    try:
        if args.command == "manifest":
            out = outside(args.out, args.src_dir)
            write_json(out, manifest(args.src_dir))
            return 0
        if args.command == "copy":
            return 0 if copy_library(args.src_dir, args.dst_dir, trusted_manifest=args.trusted_manifest)["usable"] else 1
        out = outside(args.out, args.data_dir)
        md = outside(args.md, args.data_dir) if args.md else None
        if md is not None and md.resolve() == out.resolve():
            raise MeasurementRefused("JSON and Markdown outputs must be different files")
        result = count(args.data_dir, label=args.label, product_commit=args.product_commit, prep_rule=args.prep_rule,
                       chain_file=args.chain_file)
        write_json(out, result)
        if md:
            md.parent.mkdir(parents=True, exist_ok=True)
            md.write_text(markdown(result), encoding="utf-8")
        return 0 if result["status"] == "measured" else 1
    except (OSError, ValueError) as exc:
        print(f"{UNMEASURED}: {exc}", file=sys.stderr)
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
