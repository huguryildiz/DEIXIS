"""Model-free lineage snapshots, selection and frozen run plans.

Fingerprints select work; they establish neither semantic support nor novelty.
No flow import: real StepInputs and message sizing are injected by the caller.
"""

from __future__ import annotations

import hashlib
import json
from dataclasses import dataclass, replace
from typing import Any, Callable

from deixis.domain import contracts
from deixis.domain.rules import MAX_RATE_LIMIT_MODEL_RETRIES, RevisionConflict, schema_repairs, step_model
from deixis.storage.db import transaction
from deixis.workflow.lineage.candidates import (
    MAX_CANDIDATES_PER_CHUNK, MAX_CHARS_PER_CHUNK, MAX_CHUNKS_PER_TARGET,
    MAX_PASSAGES_PER_CHUNK, Candidate, LineageWork, find_candidates, pack_candidates,
)
from deixis.workflow.lineage.edges import EdgeFrom, EdgeTo, derive_edges, unassessed_edges
from deixis.workflow.lineage.mentions import NORMALIZATION_VERSION, PassageText, mention_rules
from deixis.workflow.lineage.store import InvalidLineageInput, LIVE_ENDPOINT_SQL, LineageStore
from deixis.workflow.store import EVIDENCE_STATUS_SQL, NotFound, Store
from deixis.workflow.tables import TableStore

PLAN_VERSION = 1
MAX_LINEAGE_TARGETS = 25
PLAN_MODEL_CALL_BOUND = MAX_LINEAGE_TARGETS * MAX_CHUNKS_PER_TARGET * (
    1 + schema_repairs("lineage_links")) * (1 + MAX_RATE_LIMIT_MODEL_RETRIES)
ROLES = ("problem", "change", "uncertainty")
FLAGS = ("stale_column", "pdf_removed", "pdf_replaced", "text_superseded", "not_verified")
SOURCE_FIELDS = ("source_id", "work_id", "title", "year", "version_label", "access_level")
NODE_CELL_FIELDS = ("role", "cell_revision_id", "column_revision", "instruction_revision", "instruction", "state", "flags")


def fingerprint(value: Any) -> str:
    return hashlib.sha256(json.dumps(value, sort_keys=True, separators=(",", ":"),
                                     ensure_ascii=False).encode("utf-8")).hexdigest()


def text_sha256(text: str) -> str:
    return hashlib.sha256(text.encode("utf-8")).hexdigest()


def node_snapshot(node: dict[str, Any]) -> dict[str, Any]:
    return {"source_id": node["source_id"], "year": node["year"],
            "cells": [{k: cell[k] for k in NODE_CELL_FIELDS} for cell in node["cells"]]}


def pair_fp(payload: dict[str, Any], selection_revision: int, from_svid: str,
            reasoning_effort: str | None = None) -> str:
    """Pure over the actual StepInput, plus selection revision and model effort.

    The closed StepInput model record has no effort field; callers supply that
    third member of step_model explicitly. Other candidates, envelope ids,
    timestamps and unrelated shown passages never enter this reuse key.
    """
    target = payload["lineage_target"]
    candidate = next(c for c in target["candidates"] if c["from"]["source_id"] == from_svid)
    sources = {s["source_id"]: s for s in payload["sources"]}
    passages = {p["passage_id"]: p for p in payload["passages"]}
    return fingerprint({
        "plan_version": PLAN_VERSION, "table_id": target["table_id"],
        "scope_revision": payload["scope_revision"], "selection_revision": selection_revision,
        "skill_package_hash": payload["skill_package_hash"],
        "schema_version": payload["output_schema_versions"][0],
        "model": [payload["model"]["connection"], payload["model"]["requested_model"], reasoning_effort],
        "mention_rules_version": NORMALIZATION_VERSION,
        "to": target["to"], "from": candidate["from"],
        "sources": [{k: sources[sid][k] for k in SOURCE_FIELDS}
                    for sid in (target["to"]["source_id"], from_svid)],
        "edge_state": candidate["edge_state"], "year_order_warning": candidate["year_order_warning"],
        "mention_passage_ids": candidate["mention_passage_ids"],
        "mention_text_sha256": [text_sha256(passages[pid]["text"]) for pid in candidate["mention_passage_ids"]],
    })


def build_node(store: Store, table_id: str, svid: str) -> dict[str, Any]:
    """Read only current cell revisions; a pending-only row is still missing."""
    columns = {c["lineage_role"]: c for c in TableStore(store)._columns(table_id) if c["lineage_role"]}
    cells = []
    for role in ROLES:
        column = columns.get(role)
        row = store.conn.execute(
            "SELECT c.id AS cell_id, r.* FROM evidence_cells c JOIN cell_revisions r ON r.id = c.current_revision_id"
            " WHERE c.table_id = ? AND c.column_id = ? AND c.source_version_id = ?",
            (table_id, column["id"], svid),
        ).fetchone() if column else None
        cell = dict.fromkeys(("cell_id", "cell_revision_id", "column_revision", "value", "reading_depth", "output_status"))
        cell |= {"role": role, "instruction_revision": column["current_revision"] if column else None,
                 "instruction": column["instruction"] if column else None, "state": "missing",
                 "flags": dict.fromkeys(FLAGS, False), "evidence_quotes": []}
        if row:
            evidence = store.conn.execute(
                f"SELECT l.anchor_text, {EVIDENCE_STATUS_SQL} AS evidence_status FROM cell_evidence_links l"
                " JOIN passages p ON p.id = l.passage_id LEFT JOIN source_assets a ON a.id = p.asset_id"
                " WHERE l.cell_revision_id = ? ORDER BY l.rowid", (row["id"],),
            ).fetchall()
            value = json.loads(row["value_json"]) if row["value_json"] else None
            cell |= {"cell_id": row["cell_id"], "cell_revision_id": row["id"], "column_revision": row["column_revision"],
                     "state": row["state"], "value": value["text"][:500] if isinstance(value, dict)
                     and isinstance(value.get("text"), str) else None,
                     "reading_depth": row["reading_depth"], "output_status": row["output_status"],
                     "evidence_quotes": [e["anchor_text"] for e in evidence if e["anchor_text"] is not None]}
            statuses = {e["evidence_status"] for e in evidence}
            cell["flags"] = {"stale_column": row["column_revision"] != column["current_revision"],
                             **{flag: flag in statuses for flag in ("pdf_removed", "pdf_replaced", "text_superseded")},
                             "not_verified": row["state"] == "not_verified" or row["output_status"] == "unverified_draft"}
        cells.append(cell)
    return {"source_id": svid, "year": store.source(svid)["year"], "cells": cells}


@dataclass(frozen=True)
class SnapshotRow:
    work: LineageWork
    source_json: str
    node_json: str
    passage_versions: tuple[tuple[str, str | None], ...]
    eligible: bool


@dataclass(frozen=True)
class Snapshot:
    table_id: str
    research_id: str
    scope_revision: int
    selection_revision: int
    rows: tuple[SnapshotRow, ...]
    human_pairs: frozenset[tuple[str, str]]


def build_snapshot(store: Store, table_id: str) -> Snapshot:
    """One synchronous snapshot; passage texts are loaded only after selection.

    Project passage metadata with precisely passages_for's currency predicate.
    This avoids loading every live work's PDF text just to classify targets.
    JSON strings keep the nested source and node data frozen too.
    """
    with transaction(store.conn):
        table = store.conn.execute("SELECT research_id FROM evidence_tables WHERE id = ?", (table_id,)).fetchone()
        if table is None:
            raise NotFound(table_id)
        rid = table["research_id"]
        tables = TableStore(store)
        tables._table(rid, table_id)
        research = store.research(rid)
        rows = []
        live = [sid for sid in tables.active_rows(table_id)
                if store.conn.execute(LIVE_ENDPOINT_SQL, (table_id, sid)).fetchone()]
        for position, svid in enumerate(live):
            source = store.source(svid)
            metadata = store.conn.execute(
                "SELECT p.id, p.kind, p.extraction_version FROM passages p WHERE p.source_version_id = ?"
                " AND (p.asset_id IS NULL OR EXISTS (SELECT 1 FROM source_assets a WHERE a.id = p.asset_id"
                " AND a.removed_at IS NULL AND a.extraction_version IS p.extraction_version))"
                " ORDER BY p.kind, p.physical_page, p.rowid", (svid,),
            ).fetchall()
            kinds = {p["kind"] for p in metadata}
            shown = {"source_id": svid, **{k: source[k] for k in ("work_id", "title", "year", "version_label")},
                     "access_level": "pdf_available" if "pdf_page" in kinds else "abstract" if "abstract" in kinds else "metadata"}
            work = LineageWork(
                svid, source["work_id"], position, source["title"], tuple(source["authors"]), source["year"],
                tuple(r[0] for r in store.conn.execute(
                    "SELECT DISTINCT year FROM source_versions WHERE work_id = ? AND id <> ? AND year IS NOT NULL ORDER BY year",
                    (source["work_id"], svid))), bool(source["references_read"]),
                frozenset(r[0] for r in store.conn.execute(
                    "SELECT referenced_id FROM record_references WHERE source_version_id = ?", (svid,))),
                frozenset(r[0] for r in store.conn.execute(
                    "SELECT value FROM identifier_mappings WHERE source_version_id = ? AND scheme = 'openalex'", (svid,))), (),
            )
            rows.append(SnapshotRow(work, json.dumps(shown, ensure_ascii=False),
                                    json.dumps(build_node(store, table_id, svid), ensure_ascii=False),
                                    tuple((p["id"], p["extraction_version"]) for p in metadata), "pdf_page" in kinds))
        return Snapshot(table_id, rid, research["current_scope_revision"], research["selection_revision"],
                        tuple(rows), frozenset(LineageStore(store).human_decided_pairs(table_id)))


def build_lineage_target(snapshot: Snapshot, chunk: tuple[Candidate, ...]) -> dict[str, Any]:
    nodes = {r.work.source_version_id: json.loads(r.node_json) for r in snapshot.rows}
    return {"table_id": snapshot.table_id, "to": nodes[chunk[0].to_source_version_id],
            "candidates": [{"from": nodes[c.from_source_version_id], "origin": "mention",
                            "mention_passage_ids": list(c.mention_passage_ids), "edge_state": c.edge_state,
                            "year_order_warning": c.year_order_warning} for c in chunk]}


def target_fp(snapshot: Snapshot, row: SnapshotRow, skill_hash: str, model: tuple) -> str:
    return fingerprint({
        "plan_version": PLAN_VERSION, "mention_rules": mention_rules(), "scope_revision": snapshot.scope_revision,
        "selection_revision": snapshot.selection_revision, "skill_package_hash": skill_hash,
        "schema_version": contracts.SCHEMA_VERSIONS["LineageLinksDraft"], "model": model,
        "source_version_id": row.work.source_version_id, "references_read": row.work.references_read,
        "referenced_ids": sorted(row.work.referenced_ids), "passage_versions": row.passage_versions,
        "other_works": [{"source_version_id": r.work.source_version_id, "work_id": r.work.work_id,
                         "title": r.work.title, "authors": r.work.authors, "year": r.work.year, "years": r.work.years,
                         "openalex_ids": sorted(r.work.openalex_ids)} for r in snapshot.rows if r is not row],
        "sources": [json.loads(r.source_json) for r in snapshot.rows],
        "nodes": [node_snapshot(json.loads(r.node_json)) for r in snapshot.rows],
        "human_pairs": sorted(pair for pair in snapshot.human_pairs if pair[1] == row.work.source_version_id),
    })


class LineagePlanner:
    def __init__(self, store: Store, build_input: Callable[..., dict[str, Any]],
                 message_chars: Callable[[dict[str, Any]], int], skill_hash: str):
        self.store, self.conn = store, store.conn
        self.build_input, self.message_chars, self.skill_hash = build_input, message_chars, skill_hash
        self.lineage = LineageStore(store)

    def _history(self, snapshot: Snapshot) -> tuple[dict, list]:
        latest, failures = {}, []
        for row in self.conn.execute(
            "SELECT id FROM runs WHERE research_id = ? AND kind = 'lineage_links' AND scope_revision = ?"
            " AND json_extract(target_json, '$.table_id') = ? ORDER BY created_at, rowid",
            (snapshot.research_id, snapshot.scope_revision, snapshot.table_id),
        ):
            run = self.store.run(row["id"])
            step = self.store.existing_step(run["id"], "lineage_publication")
            output = self.store.step_output(step["id"]) if step and step["status"] == "succeeded" else {}
            outcomes = {t["to"]: t["outcome"] for t in (output or {}).get("targets", [])}
            for selected in run["target"].get("selected", []):
                carried = {(f["from"], f["pair_fp"]) for f in run["target"].get("failed_unchanged", [])
                           if f["to"] == selected["to"]}
                latest[selected["to"]] = (selected["target_fp"], outcomes.get(selected["to"], "incomplete"), run["id"], carried)
            for failed in (output or {}).get("failed_pairs", []):
                failures.append(failed | {"run_id": run["id"], "recorded_at": step["finished_at"] or step["created_at"]})
        return latest, failures

    def _latest_revision(self, table_id: str, frm: str, to: str) -> dict | None:
        row = self.conn.execute(
            "SELECT r.* FROM lineage_link_revisions r JOIN lineage_links l ON l.id = r.link_id"
            " WHERE l.table_id = ? AND l.from_source_version_id = ? AND l.to_source_version_id = ?"
            " AND r.kind = 'model_propose' ORDER BY r.created_at DESC, r.id DESC LIMIT 1", (table_id, frm, to),
        ).fetchone()
        return dict(row) if row else None

    @staticmethod
    def _assessed(revision: dict | None, fp: str) -> bool:
        return bool(revision and json.loads(revision["inputs_json"] or "{}").get("fingerprint") == fp
                    and (revision["disposition"] == "accepted" or revision["rejection_code"] in
                         ("anchor_not_found", "same_work", "cycle")))

    @staticmethod
    def _known_failed(failures: list, revision: dict | None, frm: str, to: str, fp: str | None = None) -> bool:
        return any(f["from"] == frm and f["to"] == to and (fp is None or f["pair_fp"] == fp)
                   and (revision is None or revision["created_at"] <= f["recorded_at"]) for f in failures)

    def build_plan(self, research_id: str, table_id: str, retry_failed: bool = False) -> dict[str, Any]:
        # A preview and all its injected StepInput reads share one synchronous DB transaction.
        with transaction(self.conn):
            TableStore(self.store)._table(research_id, table_id)
            snapshot = build_snapshot(self.store, table_id)
            scope = self.store.scope(research_id, snapshot.scope_revision)
            model = step_model(scope, "lineage_links")
            history, failures = self._history(snapshot)
            classified, not_selected = [], []
            for row in snapshot.rows:
                if not row.eligible:
                    continue
                to = row.work.source_version_id
                fp = target_fp(snapshot, row, self.skill_hash, model)
                old = history.get(to)
                # The latest selection confirms its own failures and those carried in its
                # plan. Keep the original failure timestamp for the later-revision check.
                retry = retry_failed and old is not None and old[0] == fp and any(
                    (f["run_id"] == old[2] or (f["from"], f["pair_fp"]) in old[3]) and
                    f["to"] == to and (f["from"], to) not in snapshot.human_pairs and
                    self._known_failed([f], self._latest_revision(table_id, f["from"], to), f["from"], to)
                    for f in failures)
                category = "new" if old is None else "changed" if fp != old[0] else "retry" if old[1] == "incomplete" or retry else "settled"
                entry = {"to": to, "class": category, "target_fp": fp, "position": row.work.position}
                if category == "settled":
                    not_selected.append(entry | {"reason": "settled"})
                else:
                    classified.append((row, entry))
            classified.sort(key=lambda item: (("new", "changed", "retry").index(item[1]["class"]), item[1]["position"]))
            selected_rows = classified[:MAX_LINEAGE_TARGETS]
            not_selected += [entry | {"reason": "beyond_work_limit"} for _, entry in classified[MAX_LINEAGE_TARGETS:]]
            selected_ids = {r.work.source_version_id for r, _ in selected_rows}
            passage_rows = {sid: self.store.passages_for(sid) for sid in selected_ids}
            works = tuple(replace(r.work, passages=tuple(PassageText(p["id"], p["kind"], p["text"], p["physical_page"])
                                                       for p in passage_rows[r.work.source_version_id]))
                          if r.work.source_version_id in selected_ids else r.work for r in snapshot.rows)
            found = find_candidates(works, targets=(w for w in works if w.source_version_id in selected_ids),
                                    excluded_pairs=snapshot.human_pairs)
            by_target = {sid: [] for sid in selected_ids}
            for candidate in found.candidates:
                by_target[candidate.to_source_version_id].append(candidate)
            selected, chunks, not_sent, failed_unchanged = [], [], [], []
            for row, entry in selected_rows:
                to = row.work.source_version_id
                def payload(chunk: tuple[Candidate, ...]) -> dict:
                    ids = {pid for c in chunk for pid in c.mention_passage_ids}
                    shown = [p for p in passage_rows[to] if p["id"] in ids]
                    return self.build_input(research_id, snapshot.scope_revision,
                                            build_lineage_target(snapshot, chunk), shown, PLAN_MODEL_CALL_BOUND)

                def measure(chunk: tuple[Candidate, ...]) -> int:
                    return self.message_chars(payload(chunk))

                def fits(chunk: tuple[Candidate, ...]) -> bool:
                    return (len(chunk) <= MAX_CANDIDATES_PER_CHUNK and
                            len({pid for c in chunk for pid in c.mention_passage_ids}) <= MAX_PASSAGES_PER_CHUNK
                            and measure(chunk) <= MAX_CHARS_PER_CHUNK)

                pending, records = [], []
                for c in by_target[to]:
                    frm = c.from_source_version_id
                    fp = pair_fp(payload((c,)), snapshot.selection_revision, frm, model[2])
                    pair = self.lineage.link(table_id, frm, to)
                    record = {"from": frm, "pair_fp": fp, "edge_state": c.edge_state,
                              "year_order_warning": c.year_order_warning, "basis": list(c.basis),
                              "mention_passage_ids": list(c.mention_passage_ids), "total_matches": c.total_matches,
                              "link_version": pair["version"] if pair else None,
                              "current_revision_id": pair["current_revision_id"] if pair else None}
                    revision = self._latest_revision(table_id, frm, to)
                    if self._assessed(revision, fp):
                        continue
                    if self._known_failed(failures, revision, frm, to, fp) and not retry_failed:
                        failed_unchanged.append({"to": to, "from": frm, "pair_fp": fp})
                        continue
                    # Classify oversized single pairs before packing: even after a full
                    # third call they must be recorded as oversized, never as retryable.
                    if not fits((c,)):
                        not_sent.append({"to": to, "from": frm, "reason": "too_large_for_one_call", "pair_fingerprint": fp})
                        records.append(record)
                        continue
                    pending.append(c)
                    records.append(record)
                packed = pack_candidates(pending, fits=fits)
                fps = {r["from"]: r["pair_fp"] for r in records}
                for ns in packed.not_sent:
                    not_sent.append({"to": to, "from": ns.candidate.from_source_version_id,
                                     "reason": ns.reason, "pair_fingerprint": fps[ns.candidate.from_source_version_id]})
                for index, chunk in enumerate(packed.chunks):
                    shown_ids = [p["id"] for p in passage_rows[to]
                                 if p["id"] in {pid for c in chunk for pid in c.mention_passage_ids}]
                    chunk_fp = fingerprint({"to": to, "pairs": [fps[c.from_source_version_id] for c in chunk],
                                            "shown_passage_ids": shown_ids})
                    chunks.append({"key": f"lineage_links:{to}:{index}:{chunk_fp[:16]}", "to": to, "index": index,
                                   "from": [c.from_source_version_id for c in chunk], "chunk_fp": chunk_fp,
                                   "shown_passage_ids": shown_ids, "message_chars": measure(chunk)})
                selected.append(entry | {"candidates": records, "no_candidate": to in found.no_candidate_targets,
                                         "outcome": "incomplete" if packed.not_sent else "settled"})
            edges = derive_edges((EdgeTo(w.source_version_id, w.work_id, w.references_read, w.referenced_ids) for w in works),
                                 (EdgeFrom(w.source_version_id, w.work_id, w.openalex_ids) for w in works))
            missing = sum(c["state"] == "missing" for r in snapshot.rows for c in json.loads(r.node_json)["cells"])
            columns = TableStore(self.store)._columns(table_id)
            rules = mention_rules() | {
                "max_candidates_per_chunk": MAX_CANDIDATES_PER_CHUNK, "max_chunks_per_target": MAX_CHUNKS_PER_TARGET,
                "max_passages_per_chunk": MAX_PASSAGES_PER_CHUNK, "max_message_chars": MAX_CHARS_PER_CHUNK,
                "max_lineage_targets": MAX_LINEAGE_TARGETS, "max_schema_repairs": schema_repairs("lineage_links"),
                "max_rate_limit_model_retries": MAX_RATE_LIMIT_MODEL_RETRIES}
            plan = {"table_id": table_id, "plan_version": PLAN_VERSION, "scope_revision": snapshot.scope_revision,
                    "selection_revision": snapshot.selection_revision, "model": list(model),
                    "skill_package_hash": self.skill_hash, "schema_version": contracts.SCHEMA_VERSIONS["LineageLinksDraft"],
                    "rules": rules, "selected": selected, "no_candidate": list(found.no_candidate_targets),
                    "scanned_targets": list(found.scanned_targets), "chunks": chunks, "not_selected": not_selected,
                    "not_sent_budget": not_sent, "failed_unchanged": failed_unchanged, "retry_failed": retry_failed,
                    "unassessed_edges": len(unassessed_edges(edges, frozenset((c.from_source_version_id, c.to_source_version_id)
                                                                             for c in found.candidates),
                                                            frozenset(found.scanned_targets), snapshot.human_pairs)),
                    "max_model_calls": len(chunks) * (1 + schema_repairs("lineage_links")) * (1 + MAX_RATE_LIMIT_MODEL_RETRIES),
                    "max_provider_requests": 0,
                    "counts": {"live_rows": len(snapshot.rows), "eligible_targets": sum(r.eligible for r in snapshot.rows),
                               "selected": len(selected), "not_selected": len(not_selected), "calls": len(chunks),
                               "candidates": sum(len(s["candidates"]) for s in selected), "no_candidate": len(found.no_candidate_targets),
                               "not_sent_budget": len(not_sent), "failed_unchanged": len(failed_unchanged),
                               "development_columns": sum(c["lineage_role"] is not None for c in columns),
                               "missing_cells": missing}}
            plan["preview_fingerprint"] = fingerprint(plan)
            return plan

    def preview(self, research_id: str, table_id: str, retry_failed: bool = False) -> dict[str, Any]:
        plan = self.build_plan(research_id, table_id, retry_failed)
        return {k: plan[k] for k in ("table_id", "plan_version", "counts", "max_model_calls", "max_provider_requests",
                                    "not_selected", "not_sent_budget", "failed_unchanged", "preview_fingerprint", "retry_failed")} | {
            "calls": len(plan["chunks"]),
            "selected": [{k: s[k] for k in ("to", "class", "position", "target_fp", "no_candidate", "outcome")} |
                         {"candidate_count": len(s["candidates"]), "chunk_count": sum(c["to"] == s["to"] for c in plan["chunks"])}
                         for s in plan["selected"]]}

    def request_run(self, research_id: str, table_id: str, preview_fingerprint: str, retry_failed: bool = False,
                    idempotency_key: str | None = None) -> dict[str, Any]:
        key = f"lineage:{research_id}:{idempotency_key}" if idempotency_key else None
        with transaction(self.conn):
            existing = self.conn.execute("SELECT id FROM runs WHERE idempotency_key = ?", (key,)).fetchone() if key else None
            if existing:
                replay = self.store.run(existing["id"])
                if replay["research_id"] != research_id or replay["kind"] != "lineage_links" or (replay["target"] or {}).get("table_id") != table_id:
                    raise RevisionConflict("This idempotency key belongs to another lineage request")
                return replay
            paused = self.conn.execute(
                "SELECT id FROM runs WHERE research_id = ? AND kind = 'lineage_links' AND status = 'paused'"
                " AND json_extract(target_json, '$.table_id') = ?", (research_id, table_id),
            ).fetchone()
            if paused:
                raise RevisionConflict(f"Resume or cancel paused lineage run {paused['id']} first")
            plan = self.build_plan(research_id, table_id, retry_failed)
            if plan["preview_fingerprint"] != preview_fingerprint:
                raise RevisionConflict("The lineage plan changed; request a new preview")
            if not plan["selected"]:
                raise InvalidLineageInput("nothing to assess")
            return self.store.create_run(research_id, "lineage_links",
                                         {k: plan[k] for k in ("max_model_calls", "max_provider_requests")}, key, plan)

    def stale_link_revisions(self, table_id: str) -> dict[str, str]:
        return stale_link_revisions(self.store, table_id)


def stale_link_revisions(store: Store, table_id: str) -> dict[str, str]:
    """Name stale active revisions for L4's cycle graph; never rewrite decisions."""
    with transaction(store.conn):
        snapshot = build_snapshot(store, table_id)
        nodes = {r.work.source_version_id: node_snapshot(json.loads(r.node_json)) for r in snapshot.rows}
        lineage = LineageStore(store)
        stale = {}
        for link in lineage.active_links(table_id):
            revision = lineage._current(link)
            evidence = lineage.evidence(revision["id"])
            current = {p["id"] for p in store.passages_for(link["to_source_version_id"])}
            bad = any(e["passage_id"] not in current for e in evidence)
            if revision["author"] == "model":
                inputs = json.loads(revision["inputs_json"] or "{}").get("inputs", {})
                # Exclusion changes endpoint eligibility, not the node's stored content.
                # L4 handles non-live ends; still compare their actual snapshots here.
                for sid in (link["to_source_version_id"], link["from_source_version_id"]):
                    if sid not in nodes:
                        nodes[sid] = node_snapshot(build_node(store, table_id, sid))
                bad |= (revision["scope_revision"] != snapshot.scope_revision or
                        inputs.get("to") != nodes.get(link["to_source_version_id"]) or
                        inputs.get("from") != nodes.get(link["from_source_version_id"]))
            if bad:
                stale[link["id"]] = revision["id"]
        return stale


class ChunkSkipped(Exception):
    """A frozen chunk cannot be sent from its planned current passages."""


@dataclass(frozen=True)
class LineageJob:
    key: str
    chunk: dict[str, Any]
    candidates: tuple[dict[str, Any], ...]


def lineage_jobs(plan: dict[str, Any]):
    selected = {s["to"]: s for s in plan["selected"]}
    for chunk in plan["chunks"]:
        records = {c["from"]: c for c in selected[chunk["to"]]["candidates"]}
        yield LineageJob(chunk["key"], chunk, tuple(records[sid] for sid in chunk["from"]))


def refresh_job(store: Store, table_id: str, job: LineageJob) -> tuple[dict, list]:
    """No filtering of from-ends: publication records exclusions/human decisions."""
    to = job.chunk["to"]
    if not store.conn.execute(LIVE_ENDPOINT_SQL, (table_id, to)).fetchone():
        raise ChunkSkipped("endpoint_not_included")
    current = {p["id"]: p for p in store.passages_for(to)}
    if not current:
        raise ChunkSkipped("no_current_text")
    if any(pid not in current for pid in job.chunk["shown_passage_ids"]):
        raise ChunkSkipped("passage_not_current")
    target = {"table_id": table_id, "to": build_node(store, table_id, to), "candidates": [
        {"from": build_node(store, table_id, c["from"]), "origin": "mention",
         **{k: c[k] for k in ("mention_passage_ids", "edge_state", "year_order_warning")}}
        for c in job.candidates]}
    return target, [current[pid] for pid in job.chunk["shown_passage_ids"]]


def send_record(store: Store, payload: dict[str, Any], reasoning_effort: str | None) -> dict[str, Any]:
    """Fingerprint the real payload; read versions/currency in the same sync turn."""
    target = payload["lineage_target"]
    selection = store.research(payload["research_id"])["selection_revision"]
    pairs = []
    for c in target["candidates"]:
        frm, to = c["from"]["source_id"], target["to"]["source_id"]
        link = LineageStore(store).link(target["table_id"], frm, to)
        pairs.append({"from": frm, "to": to, "pair_fp": pair_fp(payload, selection, frm, reasoning_effort),
                      "link_version": link["version"] if link else None,
                      "inputs": {"to": node_snapshot(target["to"]), "from": node_snapshot(c["from"]),
                                 **{k: c[k] for k in ("mention_passage_ids", "edge_state", "year_order_warning")}}})
    current = {p["id"]: p for p in store.passages_for(target["to"]["source_id"])}
    passages = [{"id": p["passage_id"], "text_sha256": text_sha256(p["text"]),
                 "current": p["passage_id"] in current,
                 "extraction_version": current[p["passage_id"]]["extraction_version"]
                 if p["passage_id"] in current else None} for p in payload["passages"]]
    return {"send_record": {"selection_revision": selection, "pairs": pairs, "passages": passages}}


def publication_proposals(store: Store, run: dict, outputs: list[tuple[dict, LineageJob]],
                          build_input: Callable[..., dict]) -> list[dict]:
    proposals = []
    for output, job in outputs:
        if output.get("invalid") or output.get("skipped"):
            continue
        payload = store.step_input_payload(output["step_input_id"])
        sent = output["send_record"]
        records = {r["from"]: r for r in sent["pairs"]}
        shown = {p["id"]: p for p in sent["passages"]}
        target = payload["lineage_target"]
        to, table_id = target["to"]["source_id"], target["table_id"]
        current = {p["id"]: p for p in store.passages_for(to)}
        for decision in output["result"]["decisions"]:
            frm = decision["from_source_id"]
            record = records[frm]
            inputs = record["inputs"]
            mention_ids = inputs["mention_passage_ids"]
            evidence_ids = {e["passage_id"] for e in decision["evidence"]} | set(mention_ids)
            stale = any(pid not in current or pid not in shown or not shown[pid]["current"] or
                        text_sha256(current[pid]["text"]) != shown[pid]["text_sha256"]
                        for pid in evidence_ids)
            if not stale:
                live_target = {"table_id": table_id, "to": build_node(store, table_id, to), "candidates": [
                    {"from": build_node(store, table_id, frm), "origin": "mention",
                     **{k: inputs[k] for k in ("mention_passage_ids", "edge_state", "year_order_warning")}}]}
                live = build_input(run["research_id"], run["scope_revision"], live_target,
                                   [current[pid] for pid in mention_ids], run["budget"]["max_model_calls"])
                stale = pair_fp(live, store.research(run["research_id"])["selection_revision"], frm,
                                run["target"]["model"][2]) != record["pair_fp"]
            proposals.append({"research_id": run["research_id"], "table_id": table_id,
                              "from_svid": frm, "to_svid": to, "decision": decision,
                              "edge_state": inputs["edge_state"], "run_id": run["id"], "step_id": payload["step_id"],
                              "step_input_id": payload["step_input_id"], "scope_revision": payload["scope_revision"],
                              "link_version_at_request": record["link_version"], "inputs": inputs,
                              "input_fingerprint": record["pair_fp"], "output_status": "structurally_valid",
                              "idempotency_key": f"lineage:{payload['step_input_id']}:{frm}", "input_stale": stale})
    return proposals


def publication_record(plan: dict, outputs: list[tuple[dict, LineageJob]], proposals: list[dict],
                       results: list[dict]) -> dict:
    published = [{"to": p["to_svid"], "from": p["from_svid"],
                  **{k: r[k] for k in ("revision_id", "disposition", "rejection_code", "current")}}
                 for p, r in zip(sorted(proposals, key=lambda p: (p["to_svid"], p["from_svid"])), results)]
    failed, pairs, skipped = [], [], []
    incomplete = set()
    for output, job in outputs:
        # Assessing another input cannot settle the target's planned fingerprint,
        # even when that assessment succeeds or records a terminal failure.
        planned = {c["from"]: c["pair_fp"] for c in job.candidates}
        sent_pairs = output.get("send_record", {}).get("pairs", [])
        if not sent_pairs or any(r["pair_fp"] != planned[r["from"]] for r in sent_pairs):
            incomplete.add(job.chunk["to"])
        if output.get("skipped"):
            skipped.append({"key": job.key, "to": job.chunk["to"], "reason": output["skipped"]})
        elif output.get("invalid"):
            reason = "message_too_large" if output.get("message_too_large") else "invalid_model_output"
            failed.append({"key": job.key, "to": job.chunk["to"], "reason": reason,
                           "issue_count": len(output.get("issues", []))})
            pairs.extend({"to": r["to"], "from": r["from"], "pair_fp": r["pair_fp"], "reason": reason}
                         for r in sent_pairs)
    incomplete |= {s["to"] for s in skipped} | {p["to"] for p in plan["not_sent_budget"]
                                               if p["reason"] == "beyond_call_limit"}
    incomplete |= {p["to"] for p in published if p["disposition"] == "rejected" and
                   p["rejection_code"] in ("stale_input", "endpoint_not_included", "superseded_by_human")}
    targets = [{"to": s["to"], "target_fp": s["target_fp"],
                "outcome": "incomplete" if s["to"] in incomplete else "settled", "no_candidate": s["no_candidate"]}
               for s in plan["selected"]]
    return {"published": published, "step_failed": failed, "failed_pairs": pairs, "targets": targets,
            "not_sent_budget": plan["not_sent_budget"], "skipped": skipped,
            "counts": {"published": len(published), "accepted": sum(p["disposition"] == "accepted" for p in published),
                       "rejected": sum(p["disposition"] == "rejected" for p in published), "step_failed": len(failed),
                       "failed_pairs": len(pairs), "skipped": len(skipped), "targets": len(targets),
                       "incomplete": len(incomplete), "not_sent_budget": len(plan["not_sent_budget"])}}
