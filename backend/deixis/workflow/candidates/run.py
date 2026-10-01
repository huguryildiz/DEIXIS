"""Candidate inputs, bounded frozen plans and candidate-scoped evidence reads.

No flow import, model execution, retrieval or corpus-membership dependency.
Message sizing is injected and measures the actual handle-converted message.
"""
from __future__ import annotations

import hashlib
import json
from collections.abc import Callable

from deixis.domain.rules import MAX_RATE_LIMIT_MODEL_RETRIES, MAX_TRANSIENT_NETWORK_RETRIES, RevisionConflict, schema_repairs, step_model
from deixis.providers.common import MAX_RATE_LIMIT_RETRIES
from deixis.providers.registry import CONNECTORS, search_providers
from deixis.storage.db import transaction
from deixis.workflow.candidates.store import CandidateStore, InvalidCandidateInput
from deixis.workflow.store import NotFound, Store

KILL_QUERIES = 6
KILL_RECORDS = 20
KILL_KEEP = 8
MAX_MESSAGE_CHARS = 48_000
BASIS_ITEMS = 24
BASIS_TEXT_CHARS = 1_500
ABSTRACT_CHARS = 2_500
PAGE_PASSAGES = 6
PAGE_TEXT_CHARS = 4_000
PLAN_VERSION = 1


class CandidateRunInput(InvalidCandidateInput):
    """A preview/start refusal; Part B maps this code to a 422 response."""

    def __init__(self, code: str):
        self.code = code
        super().__init__(code)


class FrozenPassagesUnavailable(Exception):
    """The complete frozen shown set no longer resolves before a send."""


def fingerprint(value) -> str:
    return hashlib.sha256(json.dumps(value, sort_keys=True, separators=(",", ":"),
                                     ensure_ascii=False).encode("utf-8")).hexdigest()


def text_sha256(text: str) -> str:
    return hashlib.sha256(text.encode("utf-8")).hexdigest()


def attempts(task: str) -> int:
    return (1 + schema_repairs(task)) * (1 + MAX_RATE_LIMIT_MODEL_RETRIES)


def decompose_budget() -> dict:
    return {"max_model_calls": attempts("claim_decomposition"), "max_provider_requests": 0}


def transport_plan(providers: list[str]) -> dict:
    rows = [{"provider": pid, "requests_per_search": CONNECTORS[pid].requests_per_search,
             "rate_limit_retries": MAX_RATE_LIMIT_RETRIES,
             "transient_attempts": 1 + MAX_TRANSIENT_NETWORK_RETRIES,
             "per_query": CONNECTORS[pid].requests_per_search * (1 + MAX_RATE_LIMIT_RETRIES)
             * (1 + MAX_TRANSIENT_NETWORK_RETRIES)} for pid in providers]
    return {"providers": rows, "max_provider_requests": sum(r["per_query"] for r in rows)}


def eligible_providers(scope: dict) -> list[str]:
    return [pid for pid in search_providers(scope["providers"], scope.get("search_workflow"))
            if CONNECTORS[pid].access_mode() != "not_configured"
            and isinstance(CONNECTORS[pid].requests_per_search, int)
            and not isinstance(CONNECTORS[pid].requests_per_search, bool)
            and CONNECTORS[pid].requests_per_search > 0][:KILL_QUERIES]


def version_target(version: dict) -> dict:
    return {"version": version["version"],
            **{k: version[k] for k in ("claim_statement", "nearest_simple_explanation", "critical_assumption", "validation_plan")},
            "conditions": json.loads(version["conditions_json"]),
            "elements": [{"element_id": e["id"], **{k: e[k] for k in ("position", "text", "kind")}}
                         for e in version["elements"]]}


def candidate_target(candidate: dict, version: dict | None = None, assessed_source_id: str | None = None) -> dict:
    return {"candidate_id": candidate["id"], "origin": candidate["origin"], "gap_kind": candidate["gap_kind"],
            "origin_text": candidate["origin_text"] if version is None else None, "basis": [],
            "version": version_target(version) if version else None, "assessed_source_id": assessed_source_id}


def decomposition_input(candidate: dict, current_passages: dict[str, list[dict]]) -> dict:
    """Pure over the frozen origin view and a supplied snapshot of current passages."""
    target = candidate_target(candidate)
    omitted = dict.fromkeys(("missing", "non_current", "blank", "basis_limit", "message_size"), 0)
    passages = {}
    view = json.loads(candidate["origin_basis_view_json"]) if candidate["origin"] != "owner_text" else {}
    for key, kind in (("basis_cell_ids", "cell"), ("basis_passage_ids", "passage"), ("basis_claim_keys", "claim")):
        for item in view.get(key, []):
            if item.get("missing"):
                omitted["missing"] += 1
                continue
            row = None
            if kind == "passage":
                row = next((p for p in current_passages.get(item["source_version_id"], []) if p["id"] == item["id"]), None)
                if row is None:
                    omitted["non_current"] += 1
                    continue
            text = row["text"][:BASIS_TEXT_CHARS] if row else item["text"]
            if not text.strip():
                omitted["blank"] += 1
                continue
            if len(target["basis"]) >= BASIS_ITEMS:
                omitted["basis_limit"] += 1
                continue
            target["basis"].append({"kind": kind, "text": text, "passage_id": row["id"] if row else None})
            if row:
                passages[row["id"]] = dict(row, text=text)
    return {"target": target, "passages": list(passages.values()), "omitted": omitted}


def pack_decomposition(built: dict, measure: Callable[[dict, list[dict]], int], limit=MAX_MESSAGE_CHARS) -> dict:
    target = dict(built["target"], basis=list(built["target"]["basis"]))
    omitted = dict(built["omitted"])
    passages = list(built["passages"])
    while measure(target, passages) > limit and target["basis"]:
        target["basis"].pop()
        omitted["message_size"] += 1
        ids = {b["passage_id"] for b in target["basis"]}
        passages = [p for p in passages if p["id"] in ids]
    return {"target": target, "passages": passages, "omitted": omitted}


def shown_passages(rows: list[dict], measure: Callable[[list[dict]], int] | None = None,
                   limit=MAX_MESSAGE_CHARS) -> dict:
    abstracts = [dict(p, text=p["text"][:ABSTRACT_CHARS]) for p in rows
                 if p["kind"] == "abstract" and p["text"].strip()][:1]
    pages = sorted((p for p in rows if p["kind"] == "pdf_page" and p["text"].strip()),
                   key=lambda p: (p["physical_page"] or 0, p["id"]))
    shown = abstracts + [dict(p, text=p["text"][:PAGE_TEXT_CHARS]) for p in pages[:PAGE_PASSAGES]]
    omitted = {"page_limit": max(0, len(pages) - PAGE_PASSAGES), "message_size": 0}
    while measure and measure(shown) > limit and any(p["kind"] == "pdf_page" for p in shown):
        shown.pop()
        omitted["message_size"] += 1
    depth = "stored_passages" if any(p["kind"] == "pdf_page" for p in shown) else "abstract" if abstracts else "metadata_only"
    return {"passages": shown, "reading_depth": depth, "omitted": omitted,
            "message_too_large": bool(measure and shown and measure(shown) > limit)}


def frozen_passages(plan_hit: dict, rows: list[dict]) -> list[dict] | None:
    """A missing/changed member invalidates the whole frozen set, including its depth."""
    current = {p["id"]: p for p in rows}
    shown = []
    for entry in plan_hit["passages"]:
        row = current.get(entry["passage_id"])
        if row is None:
            return None
        text = row["text"][:ABSTRACT_CHARS if row["kind"] == "abstract" else PAGE_TEXT_CHARS]
        if text_sha256(text) != entry["text_sha256"]:
            return None
        shown.append(dict(row, text=text))
    return shown


def request_decomposition(store: Store, research_id: str, candidate_id: str, idempotency_key: str | None = None,
                          *, skill_package_hash: str) -> dict:
    key = f"decompose:{research_id}:{candidate_id}:{idempotency_key}" if idempotency_key else None
    with transaction(store.conn):
        replay = _replay(store, key, research_id, candidate_id, "claim_decomposition")
        if replay:
            return replay
        candidate = CandidateStore(store)._pair(research_id, candidate_id)
        if candidate["trashed_at"] is not None or candidate["current_version"] != 0:
            raise RevisionConflict("Decompose only an available candidate without a version; use human edit for revisions")
        return store.create_run(research_id, "claim_decomposition", decompose_budget(), key,
                                {"candidate_id": candidate_id, "expected_version": 0,
                                 "skill_package_hash": skill_package_hash})


def _replay(store, key, research_id, candidate_id, kind):
    row = store.conn.execute("SELECT id FROM runs WHERE idempotency_key = ?", (key,)).fetchone() if key else None
    if not row:
        return None
    run = store.run(row["id"])
    if run["research_id"] != research_id or run["kind"] != kind or (run["target"] or {}).get("candidate_id") != candidate_id:
        raise RevisionConflict("This idempotency key belongs to another candidate request")
    return run


class KillSearchPlanner:
    def __init__(self, store: Store, skill_package_hash: str):
        self.store, self.skill_package_hash = store, skill_package_hash

    def preview(self, research_id: str, candidate_id: str) -> dict:
        with transaction(self.store.conn):
            cs = CandidateStore(self.store)
            candidate = cs._pair(research_id, candidate_id)
            if candidate["trashed_at"] is not None:
                raise RevisionConflict("The candidate is trashed")
            if not candidate["current_version"]:
                raise CandidateRunInput("candidate_not_decomposed")
            version = cs.versions(candidate_id)[-1]
            revision = self.store.research(research_id)["current_scope_revision"]
            scope = self.store.scope(research_id, revision)
            providers = eligible_providers(scope)
            if not providers:
                raise CandidateRunInput("no_searchable_provider")
            transport = transport_plan(providers)
            budget = {"max_model_calls": attempts("kill_search_query") + KILL_KEEP * attempts("claim_assessment"),
                      "max_provider_requests": transport["max_provider_requests"],
                      "steps": {"kill_search_query": attempts("kill_search_query"),
                                "claim_assessment": attempts("claim_assessment"), "assessment_works": KILL_KEEP}}
            plan = {"candidate_id": candidate_id, "candidate_version_id": version["id"], "version": version["version"],
                    "scope_revision": revision, "providers": providers,
                    "model": {t: list(step_model(scope, t)) for t in ("kill_search_query", "claim_assessment")},
                    "budget": budget, "transport": transport,
                    "limits": {"queries": KILL_QUERIES, "records": KILL_RECORDS, "keep": KILL_KEEP,
                               "max_message_chars": MAX_MESSAGE_CHARS, "basis_items": BASIS_ITEMS,
                               "basis_text_chars": BASIS_TEXT_CHARS, "abstract_chars": ABSTRACT_CHARS,
                               "page_passages": PAGE_PASSAGES, "page_text_chars": PAGE_TEXT_CHARS},
                    "skill_package_hash": self.skill_package_hash, "plan_version": PLAN_VERSION}
            plan["preview_fingerprint"] = fingerprint(plan)
            return plan

    def request_run(self, research_id: str, candidate_id: str, preview_fingerprint: str,
                    idempotency_key: str | None = None) -> dict:
        key = f"killsearch:{research_id}:{candidate_id}:{idempotency_key}" if idempotency_key else None
        with transaction(self.store.conn):
            replay = _replay(self.store, key, research_id, candidate_id, "kill_search")
            if replay:
                if replay["target"].get("preview_fingerprint") != preview_fingerprint:
                    raise RevisionConflict("Kill-search replay fingerprint mismatch")
                return replay
            paused = self.store.conn.execute(
                "SELECT id FROM runs WHERE research_id = ? AND status = 'paused'"
                " AND kind IN ('claim_decomposition', 'kill_search') AND json_extract(target_json, '$.candidate_id') = ?",
                (research_id, candidate_id)).fetchone()
            if paused:
                raise RevisionConflict(f"Resume or cancel paused candidate run {paused['id']} first")
            plan = self.preview(research_id, candidate_id)
            if plan["preview_fingerprint"] != preview_fingerprint:
                raise RevisionConflict("The kill-search plan changed; request a new preview")
            return self.store.create_run(research_id, "kill_search", plan["budget"], key, plan)


def search_summary(store: Store, kill_search_id: str, outcomes: dict | None = None, failure_code=None) -> dict:
    """Read stored counts and audit outcomes; never derive a candidate status here."""
    cs = CandidateStore(store)
    search = cs.kill_search(kill_search_id)
    run = store.run(search["run_id"])
    plan = store.existing_step(run["id"], "kill_search_plan")
    planned = {p["source_version_id"]: p for p in (plan["output"] or {}).get("hits", [])} if plan else {}
    hit_outcomes = []
    for hit in cs.hits(kill_search_id):
        if not hit["kept"]:
            continue
        sid = hit["source_version_id"]
        supplied = (outcomes or {}).get(sid)
        reason = supplied.get("reason") if isinstance(supplied, dict) else None
        outcome = supplied.get("outcome") if isinstance(supplied, dict) else supplied
        if outcome is None:
            outcome = hit["assessment_state"]
            if outcome == "pending":
                step = store.existing_step(run["id"], f"assess:{sid}")
                outcome = {"invalid_model_output": "invalid_output", "message_too_large": "message_too_large"}.get(
                    step["error_code"] if step else None, "not_reached_budget")
        hit_outcomes.append({"source_version_id": sid, "reading_depth": hit["reading_depth"],
                             "outcome": outcome, "reason": reason, "omitted": planned.get(sid, {}).get("omitted", {})})
    return {"failure_code": failure_code,
            "counts": {k: search[k] for k in ("found", "kept", "rank_cut", "duplicates")},
            "queries": [{k: q[k] for k in ("position", "provider", "status", "record_count", "error_code")}
                        for q in cs.queries(kill_search_id)],
            "hits": hit_outcomes, "usage": run["usage"], "budget": run["budget"], "frozen_reading_depth": True}


def candidate_evidence(store: Store, research_id: str, candidate_id: str, kill_search_id: str,
                       source_version_id: str) -> dict:
    cs = CandidateStore(store)
    cs._pair(research_id, candidate_id)
    search = cs.kill_search(kill_search_id)
    if cs.version(search["candidate_version_id"])["candidate_id"] != candidate_id:
        raise NotFound(kill_search_id)
    hit = next((h for h in cs.hits(kill_search_id) if h["kept"] and h["source_version_id"] == source_version_id), None)
    if hit is None:
        raise NotFound(source_version_id)
    source = store.source(source_version_id)
    passages = store.step_input_payload(hit["step_input_id"])["passages"] if hit["assessment_state"] == "assessed" else []
    return {"source": {"source_version_id": source_version_id,
                       **{k: source[k] for k in ("title", "year", "venue", "doi", "version_label")}},
            "passages": passages, "quotes": [e for e in cs.evidence(kill_search_id) if e["source_version_id"] == source_version_id]}
