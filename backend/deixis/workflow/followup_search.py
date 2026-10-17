"""A search for new works that a follow-up question starts on the person's click (D92).

A follow-up turn reads only passages the research holds (`followup.py`). When the person asks for works the research
does not hold, a `followup_search` run searches the scholarly providers again under the turn's question revision; no
question revision is opened (D67). The run:

1. freezes a context card: the research question, the turn's open aspects and claim texts, the queries the research's
   search sent and the included works by title (`followup_search:context`);
2. asks the research's search model for setting and task terms (`followup_search_query`, the kill-search shape: no
   count probes, no backup substitution), compiles them per eligible provider and freezes the request list before
   anything is sent (`followup_search:plan`);
3. sends each request once through the bounded transport kill search uses (`flow._bounded_search_request`): the whole
   possible attempt is reserved before the send, a result whose delivery is unknown is never sent again, and an
   OpenAlex daily budget that is spent stops OpenAlex requests with no other provider put in its place. The outcome
   and the records it kept are stored on the send step before any gate (`followup_search:search:{n}`);
4. admits each answered request in its own code step after the gate (`followup_search:admit:{n}`): a `search_runs`
   row of this run and its records join the research as pending search records, never moving a candidate of the same
   question revision (`keep_candidate`). A cancel, a revised question or a changed criterion admits nothing;
5. freezes which works were new, already here or removed before (`followup_search:found`), screens the new ones with
   the abstract stage against the research's own criterion (`followup_search:screen_plan`, at most `SCREEN_MAX`), and
   writes a summary (`followup_search:summary`).

Nothing is included: a found work enters an answer only when the person includes it (`fast_answer.input_plan`).
"""

from __future__ import annotations

import json
from dataclasses import asdict
from typing import Any

from deixis.domain import canonical
from deixis.domain.rules import ABSTRACT_BATCH, ABSTRACT_RUNS, RevisionConflict, check_expected_version
from deixis.providers import openalex
from deixis.providers.common import OtherVersion, ProviderRecord, SearchOutcome
from deixis.providers.registry import CONNECTORS
from deixis.storage.db import dumps, now, transaction
from deixis.workflow import abstract_stage
from deixis.workflow.decisions import DecisionStore

KIND = "followup_search"
TASK = "followup_search_query"
MAX_ATTEMPTS = 2  # runs per turn: a second only after the first failed or was cancelled
SCREEN_MAX = 40  # new works the run screens; the person decides the rest in Sources
RECORDS_PER_REQUEST = 50  # result records kept (stored and admitted) per request
MAX_KEYWORD_QUERIES = 6
MAX_INCLUDED_TITLES = 80
MAX_SEARCHED_QUERIES = 12
OFFERED_STATUSES = ("answered", "partly_answered", "not_answered", "no_passages")
ACTIVE = ("queued", "running", "pause_requested")
CONTEXT_KEY = "followup_search:context"
QUERY_KEY = "followup_search:query"
PLAN_KEY = "followup_search:plan"
FOUND_KEY = "followup_search:found"
SCREEN_PLAN_KEY = "followup_search:screen_plan"
SUMMARY_KEY = "followup_search:summary"
BATCH_KEY = "followup_search"


def search_key(position: int) -> str:
    return f"followup_search:search:{position}"


def admit_key(position: int) -> str:
    return f"followup_search:admit:{position}"


class SearchRefused(Exception):
    """A follow-up search that cannot be queued as asked; `code` says why (the API answers 422)."""

    def __init__(self, code: str, detail: str):
        super().__init__(detail)
        self.code, self.detail = code, detail


class CriterionChanged(Exception):
    """The research's criterion is no longer the one the run froze; raised inside a batch close so nothing is written."""


# ---- queueing ---------------------------------------------------------------------------------------------------

def turn_runs(store: Any, turn_id: str) -> list[dict[str, Any]]:
    """This turn's follow-up search runs, oldest first, found by kind and target (never by key prefix)."""
    return [store.run(r[0]) for r in store.conn.execute(
        "SELECT id FROM runs WHERE kind = ? AND json_extract(target_json, '$.turn_id') = ? ORDER BY created_at, rowid",
        (KIND, turn_id))]


def _discovery(store: Any, rid: str, revision: int) -> tuple[dict[str, Any], dict[str, Any]] | None:
    """(discovery run, its approved protocol) of the latest completed discovery of the revision that has one."""
    for row in store.conn.execute(
            "SELECT id FROM runs WHERE research_id = ? AND scope_revision = ? AND kind = 'discovery'"
            " AND status = 'completed' ORDER BY created_at DESC, id DESC", (rid, revision)):
        step = store.existing_step(row["id"], "protocol_approval")
        if step is not None and step["status"] == "succeeded" and step["output"]:
            return store.run(row["id"]), step["output"]["approved"]
    return None


def offer(store: Any, turn: dict[str, Any]) -> dict[str, Any]:
    """Whether the turn offers a search now, and if not why: the rules `request` applies, read without writing."""
    rid = turn["research_id"]
    research = store.research(rid)
    runs = turn_runs(store, turn["id"])
    reason = None
    if turn["scope_revision"] != research["current_scope_revision"]:
        reason = "not_current_revision"
    elif turn["status"] not in OFFERED_STATUSES:
        reason = "turn_not_published"
    elif any(r["status"] in ACTIVE + ("paused", "completed") for r in runs):
        reason = "searched"
    elif len(runs) >= MAX_ATTEMPTS:
        reason = "attempts_used"
    elif _discovery(store, rid, turn["scope_revision"]) is None:
        reason = "no_completed_discovery"
    return {"offered": reason is None, "not_offered_reason": reason, "attempt": len(runs) + 1}


def _eligible(scope: dict[str, Any]) -> list[str]:
    from deixis.workflow.candidates import run as candidates
    return candidates.eligible_providers(scope)


def budget(providers: list[str]) -> dict[str, Any]:
    """The run's frozen allowance. Provider requests: one keyword reservation per eligible provider and one OpenAlex
    semantic reservation, an upper bound that does not depend on the query not yet written. Model calls: the query's
    own ceiling and the abstract screening of at most `SCREEN_MAX` works, read twice per batch and held twice so a
    call a crash left unknown can be sent again (as `screen_more.budget`)."""
    from deixis.workflow.candidates import run as candidates
    transport = candidates.transport_plan(providers)
    per_query = {row["provider"]: row["per_query"] for row in transport["providers"]}
    requests = transport["max_provider_requests"] + per_query.get("openalex", 0)
    query_calls = candidates.attempts(TASK)
    screening = 2 * abstract_stage.model_calls(SCREEN_MAX, ABSTRACT_BATCH, ABSTRACT_RUNS)
    return {"max_model_calls": query_calls + screening, "max_provider_requests": requests,
            "followup_search": {"query_calls": query_calls, "screen_max": SCREEN_MAX,
                                "records_per_request": RECORDS_PER_REQUEST}}, transport


def request(store: Any, rid: str, turn_id: str, expected_scope_revision: int, idempotency_key: str | None) -> dict[str, Any]:
    """Queue the turn's follow-up search. A stored run under the same key comes back first, whatever happened to it
    since; then, in one transaction, the turn must offer a search (`offer`) and no run of the research may be active."""
    from deixis.workflow.store import ACTIVE_RUN_STATUSES, NotFound
    key = f"followup:search:{turn_id}:{idempotency_key}" if idempotency_key else None
    with transaction(store.conn):
        store.research(rid)
        if key:
            row = store.conn.execute("SELECT id, kind, target_json FROM runs WHERE idempotency_key = ?", (key,)).fetchone()
            if row is not None:
                if row["kind"] != KIND or json.loads(row["target_json"] or "{}").get("turn_id") != turn_id:
                    raise RevisionConflict("This idempotency key was used for another request")
                return store.run(row["id"])
        turn = store.conn.execute("SELECT * FROM followup_turns WHERE id = ? AND research_id = ?", (turn_id, rid)).fetchone()
        if turn is None:
            raise NotFound(turn_id)
        turn = dict(turn)
        check_expected_version(expected_scope_revision, store.research(rid)["current_scope_revision"])
        active = store.conn.execute(
            f"SELECT id FROM runs WHERE research_id = ? AND status IN ({','.join('?' * len(ACTIVE_RUN_STATUSES))}) LIMIT 1",
            (rid, *ACTIVE_RUN_STATUSES)).fetchone()
        if active:
            raise RevisionConflict(f"run {active['id']} is still active")
        offered = offer(store, turn)
        if not offered["offered"]:
            raise SearchRefused(offered["not_offered_reason"], "This follow-up cannot start a search now")
        discovery, approved = _discovery(store, rid, turn["scope_revision"])
        scope = store.scope(rid, turn["scope_revision"])
        providers = _eligible(scope)
        if not providers:
            raise SearchRefused("no_search_provider", "No search provider is set up")
        allowance, transport = budget(providers)
        target = {"turn_id": turn_id, "attempt": offered["attempt"], "question": turn["question"],
                  "discovery_run_id": discovery["id"], "criterion_hash": DecisionStore(store).staleness_key(rid)[1],
                  "providers": providers, "transport": transport}
        return store.create_run(rid, KIND, allowance, key, target, expected_scope_revision=turn["scope_revision"])


# ---- the run -----------------------------------------------------------------------------------------------------

def _gate(flow: Any, run: dict[str, Any]) -> None:
    """Every send's last look: a pause, a cancel or a revised question stops the run (`_checkpoint`), and so does a
    criterion other than the one the run froze (the run's own gate, also read at every checkpoint)."""
    flow._checkpoint(run["id"], run["scope_revision"])


def _criterion_gate(flow: Any, run: dict[str, Any]) -> None:
    if DecisionStore(flow.store).staleness_key(run["research_id"])[1] != run["target"]["criterion_hash"]:
        flow._fail(run["id"], "criterion_changed")


def _code(flow: Any, run: dict[str, Any], key: str, build: Any) -> dict[str, Any]:
    """A frozen code step: the gate first, then the step's output written once; a resumed run reads it back."""
    step = flow.store.step(run["id"], key, "code:" + key.replace(":", "_"))
    if step["status"] == "succeeded":
        return step["output"]
    _gate(flow, run)
    with transaction(flow.store.conn):
        output = build()
        flow.store.start_step(step["id"])
        flow.store.finish_step(step["id"], "succeeded", output=output)
    return output


def context_card(store: Any, run: dict[str, Any], scope: dict[str, Any]) -> dict[str, Any]:
    """What the query step reads about the research (`followup_search_context`). Context only: no record, no passage."""
    rid, target = run["research_id"], run["target"]
    turn = dict(store.conn.execute("SELECT * FROM followup_turns WHERE id = ?", (target["turn_id"],)).fetchone())
    draft = json.loads(turn["draft_json"] or "{}") if turn["status"] in OFFERED_STATUSES else {}
    approval = store.existing_step(target["discovery_run_id"], "protocol_approval")
    queries = [q["query_text"] for q in approval["output"]["approved"]["queries"] if q.get("query_text")]
    heads = set(store.work_heads(rid).values())
    included = [f"{r['title']} ({r['year']})" if r["year"] else r["title"] for r in store.conn.execute(
        "SELECT v.id, v.title, v.year FROM selections s JOIN source_versions v ON v.id = s.source_version_id"
        " WHERE s.research_id = ? AND s.state = 'included' ORDER BY s.updated_at DESC, s.rowid DESC", (rid,))
        if r["id"] in heads]
    card = {"research_question": scope["question"],
            "unanswered_aspects": [a for a in draft.get("unanswered_aspects", []) if isinstance(a, str)][:5],
            "answer_claims": [c["text"] for c in draft.get("claims", [])
                              if isinstance(c, dict) and isinstance(c.get("text"), str)][:8],
            "searched_queries": list(dict.fromkeys(queries))[:MAX_SEARCHED_QUERIES],
            "included_works": included[:MAX_INCLUDED_TITLES], "included_works_total": len(included)}
    return {"card": card, "characters": len(json.dumps(card, ensure_ascii=False))}


async def _query(flow: Any, run: dict[str, Any], scope: dict[str, Any], card: dict[str, Any]) -> dict[str, Any]:
    """The model's setting and task terms, under the query's own call ceiling (checked before every send, the
    adapter's rate-limit resends included); its one schema repair holds across restarts (`STORED_REPAIR_TASKS`)."""
    from deixis.workflow.flow import OptionalStepFailed, step_model
    store, run_id = flow.store, run["id"]
    ceiling = run["budget"]["followup_search"]["query_calls"]

    def within() -> bool:
        return store.run(run_id)["usage"].get("model_calls", 0) < ceiling

    def send_gate() -> None:
        _gate(flow, run)
        if not within():
            flow._fail(run_id, "followup_query_budget")

    def step_input(step_id: str) -> dict[str, Any]:
        return flow._step_input(run, scope, step_id, TASK, [], [], [], [], step_model(scope, TASK)) | {
            "followup_search_context": card}
    try:
        output = await flow._model_step(run, scope, QUERY_KEY, TASK, source_ids=[], passage_rows=[], optional=True,
                                        send_gate=send_gate, resend_guard=within, step_input_builder=step_input)
    except OptionalStepFailed as exc:
        flow._fail(run_id, exc.reason, exc.detail)
    if output.get("invalid"):
        flow._fail(run_id, "followup_query_invalid", {"issues": output.get("issues")})
    return output


def request_plan(question: str, blocks: dict[str, Any], providers: list[str]) -> dict[str, Any]:
    """The requests the run may send, in order, frozen before any is sent: OpenAlex's semantic search with the
    follow-up question as written, then the compiled keyword queries. Raises `terms.InvalidTerms`."""
    from deixis.workflow.candidates import terms
    vocabulary = terms.block_vocabulary([t["term"] for t in blocks["setting"]], [t["term"] for t in blocks["task"]])
    vocabulary["block_assignment"] = KIND
    for term in vocabulary["terms"]:
        term["origin"] = KIND
    requests = []
    if "openalex" in providers and question.strip():
        requests.append({"provider_id": "openalex", "endpoint": "semantic", "query_text": openalex.semantic_text(question),
                         "limit": RECORDS_PER_REQUEST, "origin": "semantic"})
    for query in terms.compile_queries(vocabulary, providers, MAX_KEYWORD_QUERIES):
        requests.append({k: query[k] for k in ("provider_id", "query_text") if k in query}
                        | {k: query[k] for k in ("endpoint", "sort") if query.get(k) is not None}
                        | {"limit": RECORDS_PER_REQUEST, "origin": "keyword"})
    return {"blocks": {k: blocks[k] for k in ("setting", "task", "setting_backup", "task_backup")},
            "vocabulary": vocabulary, "requests": requests}


def _records_of(stored: list[dict[str, Any]]) -> list[ProviderRecord]:
    """Records stored on a send step, read back for admission."""
    out = []
    for item in stored:
        item = dict(item)
        item["other_versions"] = [OtherVersion(**o) for o in item.get("other_versions") or []]
        if isinstance(item.get("references"), list):
            item["references"] = tuple(item["references"])
        out.append(ProviderRecord(**item))
    return out


def _named(request_: dict[str, Any]) -> dict[str, Any]:
    """What the send step keeps of its frozen request, so an export reads the query without the summary step."""
    return {"provider_id": request_["provider_id"], "endpoint": request_.get("endpoint"), "query_text": request_["query_text"]}


async def _send(flow: Any, run: dict[str, Any], position: int, request_: dict[str, Any]) -> dict[str, Any]:
    """Send one request at most once and store its outcome and kept records on its step, before any gate runs."""
    from deixis.documents import acquisition
    from deixis.providers import facade
    store, run_id = flow.store, run["id"]
    provider = CONNECTORS[request_["provider_id"]].provider_id
    step = store.step(run_id, search_key(position), f"provider_search:{provider}")
    if step["status"] in ("succeeded", "failed", "outcome_unknown", "cancelled"):
        return step
    if step["status"] == "running":
        # A send whose worker died before its outcome was stored: its delivery is unknown and it is never sent again.
        store.finish_step(step["id"], "outcome_unknown", output={"status": "outcome_unknown", "result_count": 0, **_named(request_)},
                          error_code="outcome_unknown", delivery_class="after_send_unknown")
        return store.step(run_id, search_key(position), f"provider_search:{provider}")
    _gate(flow, run)
    # bioRxiv is searched through OpenAlex (its lineage), so the same daily budget closes and records it.
    on_openalex = provider == "openalex" or CONNECTORS[request_["provider_id"]].lineage == "openalex"
    if on_openalex and flow._openalex_budget_of(run_id).exhausted:
        store.start_step(step["id"])
        store.finish_step(step["id"], "failed", output={"status": "openalex_budget_exhausted", "result_count": 0, **_named(request_)},
                          error_code="openalex_budget_exhausted", delivery_class="before_send")
        return store.step(run_id, search_key(position), f"provider_search:{provider}")
    from deixis.workflow.flow import RunStopped
    store.start_step(step["id"])
    try:
        outcome, transport = await flow._bounded_search_request(run, request_, lambda: _gate(flow, run), request_["limit"])
    except RunStopped:
        # The transport stops only at its gate, before an attempt is sent (a retried attempt follows one that was not
        # delivered), so nothing went out: the request is sent on resume.
        store.conn.execute("UPDATE run_steps SET status = 'pending', started_at = NULL WHERE id = ? AND status = 'running'",
                           (step["id"],))
        raise
    dispatched = outcome if isinstance(outcome, facade.Dispatched) else None
    outcome = dispatched.outcome if dispatched else outcome
    ok = outcome.status in ("completed", "zero_results")
    status = "succeeded" if ok else "outcome_unknown" if outcome.delivery_class == "after_send_unknown" else "failed"
    kept = outcome.records[:request_["limit"]] if ok else []
    path = digest = None
    if outcome.raw_payload is not None:
        flow.deps.settings.payloads_dir.mkdir(parents=True, exist_ok=True)
        path = f"{step['id']}.json"
        (flow.deps.settings.payloads_dir / path).write_text(json.dumps(outcome.raw_payload), encoding="utf-8")
        digest = canonical.sha256_hex(outcome.raw_payload)
    output = {"status": outcome.status, "result_count": len(kept), **_named(request_),
              "dropped_over_limit": max(0, len(outcome.records) - len(kept)) if ok else 0,
              "request_description": outcome.request_description, "access_mode": outcome.access_mode,
              "provider_total": outcome.provider_total, "raw_payload_path": path, "payload_sha256": digest,
              "records": [asdict(r) for r in kept]}
    if transport and transport.get("dispatches"):
        output["transport"] = transport
    if dispatched is not None:
        output["connector"] = dispatched.connector
        if dispatched.dropped_records:
            output["dropped_records"] = dispatched.dropped_records
    with transaction(store.conn):
        if on_openalex and outcome.error_kind == "quota_exhausted":
            store.note_openalex_budget(run["research_id"], run_id, acquisition.budget_reset_at(outcome.rate_limit),
                                       skipped=outcome.http_status is None)
        store.finish_step(step["id"], status, output=output, error_code=None if ok else outcome.status,
                          delivery_class=outcome.delivery_class,
                          error=None if ok else {"error": outcome.error, "http_status": outcome.http_status,
                                                 "error_kind": outcome.error_kind})
    return store.step(run_id, search_key(position), f"provider_search:{provider}")


def _memberships(store: Any, rid: str) -> set[str]:
    return {r[0] for r in store.conn.execute("SELECT source_version_id FROM corpus_memberships WHERE research_id = ?", (rid,))}


def _admit(flow: Any, run: dict[str, Any], position: int, request_: dict[str, Any], sent: dict[str, Any]) -> dict[str, Any]:
    """Write one answered request into the research after the gate, in one transaction: its `search_runs` row, its
    records as pending search records, and which memberships this admission created (by source version)."""
    store, run_id, rid = flow.store, run["id"], run["research_id"]
    step = store.step(run_id, admit_key(position), "code:followup_search_admit")
    if step["status"] == "succeeded":
        return step["output"]
    _gate(flow, run)
    out = sent["output"]
    provider = CONNECTORS[request_["provider_id"]].provider_id
    records = _records_of(out["records"])
    fields = dict(research_id=rid, run_id=run_id, step_id=step["id"], scope_revision=run["scope_revision"],
                  provider=provider, query_text=request_["query_text"],
                  request_description=out["request_description"], access_mode=out["access_mode"],
                  status=out["status"], delivery_class=None, result_count=len(records),
                  provider_total=out.get("provider_total"), page_limit=request_["limit"], error_json=None,
                  raw_payload_path=out.get("raw_payload_path"), payload_sha256=out.get("payload_sha256"),
                  connector_json=dumps(out["connector"]) if out.get("connector") else None)
    with transaction(store.conn):
        before = _memberships(store, rid)
        # What the research held when this run first admitted (R3.2): later admissions and the found step classify
        # against it, so versions another run added while this one was paused never count as held before.
        held = _held_before(store.conn, run_id)
        output: dict[str, Any] = {"position": position, "held_before": sorted(before) if held is None else None}
        store.start_step(step["id"])
        store.record_search(fields, provider, records, out.get("raw_payload_path"), step["id"], "succeeded",
                            step_output=output, keep_found=True, keep_candidate=True)
        created = sorted(_memberships(store, rid) - before)
        _keep_removed(store, run, plan_positions=position, created=created)
        final = store.step(run_id, admit_key(position), "code:followup_search_admit")["output"]
        store.set_step_output(step["id"], final | {"created_memberships": created})  # read by the classification below
        # The classification so far, frozen while this run is the research's only active run: a run that stops before
        # its found step shows this, never one recomputed after later runs added versions of the same works.
        store.set_step_output(step["id"], final | {"created_memberships": created,
                                                   "found_so_far": _classify(store.conn, rid, run_id)})
    return store.step(run_id, admit_key(position), "code:followup_search_admit")["output"]


def _held_before(conn: Any, run_id: str) -> set[str] | None:
    """The memberships the research held when this run's first admission began, stored on that admission; None
    before any admission succeeded."""
    for row in conn.execute("SELECT output_json FROM run_steps WHERE run_id = ? AND operation_key LIKE 'followup_search:admit:%'"
                            " AND status = 'succeeded' AND output_json IS NOT NULL", (run_id,)):
        held = json.loads(row["output_json"]).get("held_before")
        if held is not None:
            return set(held)
    return None


def _keep_removed(store: Any, run: dict[str, Any], plan_positions: int, created: list[str]) -> None:
    """A version this run added that the record links joined to a work the person removed stays removed (R3.2): when
    every membership of its work that this run did not create is removed, the new one takes the same removal. Run after
    each admission, over every membership this run created so far, since a later admission's links can join an earlier
    new version to a removed work."""
    rid, run_id = run["research_id"], run["id"]
    mine = set(created)
    for position in range(1, plan_positions):
        step = store.existing_step(run_id, admit_key(position))
        if step is not None and step["status"] == "succeeded":
            mine |= set(step["output"].get("created_memberships", []))
    if not mine:
        return
    work_of = store.work_ids(sorted(mine))
    for work_id in set(work_of.values()):
        rows = store.conn.execute(
            "SELECT m.source_version_id, m.removed_at, m.removal_note FROM corpus_memberships m"
            " JOIN source_versions v ON v.id = m.source_version_id WHERE m.research_id = ? AND v.work_id = ?",
            (rid, work_id)).fetchall()
        held_before = _held_before(store.conn, run_id) or set()
        held = [r for r in rows if r["source_version_id"] not in mine and r["source_version_id"] in held_before]
        if not held or any(r["removed_at"] is None for r in held):
            continue
        last = max(held, key=lambda r: r["removed_at"])
        store.conn.executemany(
            "UPDATE corpus_memberships SET removed_at = ?, removal_note = ? WHERE research_id = ? AND source_version_id = ?"
            " AND removed_at IS NULL",
            [(last["removed_at"], last["removal_note"], rid, r["source_version_id"]) for r in rows if r["source_version_id"] in mine])


def found(store: Any, run: dict[str, Any], plan: dict[str, Any]) -> dict[str, Any]:
    """Which works this run found and what the research held of each before the run, by the works as they stand now
    that every admission's links are settled. A work is `already_here` when a version of it this run did not add is a
    membership not removed, else `removed_before` when such a membership is removed, else `new`. A membership this run
    created never counts as held before; a new version that joined a removed work stays removed (`add_to_corpus`)."""
    return _classify(store.conn, run["research_id"], run["id"])


def found_from(conn: Any, rid: str, run_id: str) -> dict[str, Any]:
    """What a run that stopped before its found step admitted (its records are in the research already): the
    classification its last succeeded admission froze, so later runs' versions of the same works never change it."""
    latest, frozen = 0, None
    for row in conn.execute("SELECT operation_key, output_json FROM run_steps WHERE run_id = ?"
                            " AND operation_key LIKE 'followup_search:admit:%' AND status = 'succeeded'"
                            " AND output_json IS NOT NULL", (run_id,)):
        position = int(row["operation_key"].rsplit(":", 1)[1])
        output = json.loads(row["output_json"])
        if position > latest and "found_so_far" in output:
            latest, frozen = position, output["found_so_far"]
    return frozen or {"works": [], "counts": {"records": 0, "new": 0, "already_here": 0, "removed_before": 0}}


def _classify(conn: Any, rid: str, run_id: str) -> dict[str, Any]:
    """`found` over the run's succeeded admissions, by the research's memberships now."""
    created: set[str] = set()
    hits: dict[str, int] = {}  # svid -> best rank in this run
    records = 0
    for row in conn.execute("SELECT output_json FROM run_steps WHERE run_id = ? AND operation_key LIKE 'followup_search:admit:%'"
                            " AND status = 'succeeded' AND output_json IS NOT NULL ORDER BY operation_key", (run_id,)):
        output = json.loads(row["output_json"])
        created |= set(output.get("created_memberships", []))
        accepted = output.get("accepted_source_version_ids", [])
        records += len(accepted)
        for rank, svid in enumerate(accepted):
            hits[svid] = min(rank, hits.get(svid, rank))
    if not hits:
        return {"works": [], "counts": {"records": 0, "new": 0, "already_here": 0, "removed_before": 0}}
    held_before = _held_before(conn, run_id) or set()
    work_of = {r[0]: r[1] for r in conn.execute(
        f"SELECT id, work_id FROM source_versions WHERE id IN ({','.join('?' * len(hits))})", tuple(hits))}
    memberships: dict[str, list[tuple[str, bool]]] = {}
    for row in conn.execute(
            "SELECT m.source_version_id, m.removed_at IS NOT NULL AS removed, v.work_id FROM corpus_memberships m"
            " JOIN source_versions v ON v.id = m.source_version_id WHERE m.research_id = ?"
            f" AND v.work_id IN ({','.join('?' * len(set(work_of.values())))})", (rid, *set(work_of.values()))):
        memberships.setdefault(row["work_id"], []).append((row["source_version_id"], bool(row["removed"])))
    works: dict[str, dict[str, Any]] = {}
    for svid, rank in hits.items():
        work_id = work_of[svid]
        entry = works.setdefault(work_id, {"work_id": work_id, "versions": [], "best_rank": rank})
        entry["versions"].append(svid)
        entry["best_rank"] = min(entry["best_rank"], rank)
    counts = {"records": records, "new": 0, "already_here": 0, "removed_before": 0}
    for work_id, entry in works.items():
        held = [removed for svid, removed in memberships.get(work_id, []) if svid not in created and svid in held_before]
        removed_now = all(removed for _, removed in memberships.get(work_id, [])) and memberships.get(work_id)
        entry["state"] = ("already_here" if any(not r for r in held) else
                          "removed_before" if held or removed_now else "new")
        entry["versions"] = sorted(entry["versions"])
        counts[entry["state"]] += 1
    ordered = sorted(works.values(), key=lambda w: (w["best_rank"], w["work_id"]))
    return {"works": ordered, "counts": counts}


def screen_plan(store: Any, run: dict[str, Any], found_: dict[str, Any]) -> dict[str, Any]:
    """The new works the abstract stage reads, frozen the first time: each work's current head when it is a search
    candidate of this revision with an abstract and no decision of the person, by best rank, at most `SCREEN_MAX`."""
    rid = run["research_id"]
    heads = store.work_heads(rid)
    candidates = {c["source_version_id"]: c for c in store.candidates(rid, run["scope_revision"])}
    with_abstract = {r[0] for r in store.conn.execute(
        "SELECT DISTINCT source_version_id FROM passages WHERE kind = 'abstract' AND length(trim(text)) > 0"
        f" AND source_version_id IN ({','.join('?' * len(candidates))})", tuple(candidates))} if candidates else set()
    person = {r[0] for r in store.conn.execute(
        "SELECT v.work_id FROM selections s JOIN source_versions v ON v.id = s.source_version_id"
        " WHERE s.research_id = ? AND s.origin = 'user'", (rid,))}
    planned, left_out = [], []
    for work in found_["works"]:
        if work["state"] != "new":
            continue
        head = heads.get(work["work_id"])
        reason = ("not_in_research" if head is None else
                  "decided_by_person" if work["work_id"] in person else
                  "not_a_candidate" if head not in candidates or candidates[head]["origin"] == "user" else
                  "no_abstract" if head not in with_abstract else
                  "over_cap" if len(planned) >= SCREEN_MAX else None)
        if reason:
            left_out.append({"work_id": work["work_id"], "reason": reason})
        else:
            planned.append({"work_id": work["work_id"], "head": head, "best_rank": work["best_rank"]})
    return {"planned": planned, "left_out": left_out}


async def _screen(flow: Any, run: dict[str, Any], scope: dict[str, Any], plan: dict[str, Any]) -> None:
    """The abstract stage over the frozen list, against the research's own criterion. A changed criterion found when
    a batch closes rolls that batch's writes back and fails the run outside the transaction."""
    from deixis.workflow import search_query as search_query_rules
    heads = [w["head"] for w in plan["planned"]]
    if not heads:
        return
    approval = flow.store.existing_step(run["target"]["discovery_run_id"], "protocol_approval")
    approved = approval["output"]["approved"]
    vocabulary = search_query_rules.settled(approved["vocabulary"], approved["queries"])

    def close_hook() -> None:
        if DecisionStore(flow.store).staleness_key(run["research_id"])[1] != run["target"]["criterion_hash"]:
            raise CriterionChanged
    flow._abstract_close_hooks[run["id"]] = close_hook
    try:
        await flow._abstract_stage(run, scope, vocabulary, order=heads, batch_key=BATCH_KEY, read_limit=len(heads))
    except CriterionChanged:
        flow._fail(run["id"], "criterion_changed")
    finally:
        flow._abstract_close_hooks.pop(run["id"], None)


def summary(store: Any, run: dict[str, Any], plan: dict[str, Any] | None, found_: dict[str, Any] | None,
            screening: dict[str, Any] | None) -> dict[str, Any]:
    """What the run did, from its stored steps: each request with its status and the records it kept, the found
    counts, and the screening's counts (code decided, sent to the model, a model result, candidates)."""
    run_id = run["id"]
    requests = []
    for position, item in enumerate((plan or {}).get("requests", []), start=1):
        step = store.existing_step(run_id, search_key(position))
        admitted = store.existing_step(run_id, admit_key(position))
        out = (step or {}).get("output") or {}
        requests.append({"position": position, "provider_id": item["provider_id"], "endpoint": item.get("endpoint"),
                         "origin": item.get("origin"), "query_text": item["query_text"],
                         "status": step["status"] if step else "not_sent", "provider_status": out.get("status"),
                         # Sent means a request may have reached the provider: a refusal closed before sending was not.
                         "sent": bool(step) and step["status"] in ("succeeded", "failed", "outcome_unknown")
                                 and step["delivery_class"] not in ("before_send", "rejected_not_executed"),
                         "records": out.get("result_count", 0),
                         "admitted": bool(admitted and admitted["status"] == "succeeded"),
                         "reason": None if step is None or step["status"] == "succeeded" else (step["error_code"] or step["status"])})
    counts = dict((found_ or {}).get("counts") or {"records": 0, "new": 0, "already_here": 0, "removed_before": 0})
    planned = [w["work_id"] for w in (screening or {}).get("planned", [])]
    decisions: dict[str, set[str]] = {"code": set(), "model": set(), "candidate": set()}
    sent: set[str] = set()
    if planned:
        rows = store.conn.execute(
            "SELECT v.work_id, d.decided_by, d.outcome FROM stage_decisions d JOIN run_steps s ON s.id = d.step_id"
            " JOIN source_versions v ON v.id = d.source_version_id WHERE s.run_id = ? AND d.stage = 'abstract'"
            " AND d.superseded_at IS NULL", (run_id,)).fetchall()
        for row in rows:
            if row["work_id"] not in planned:
                continue
            if row["decided_by"] == "model_agreement":
                decisions["model"].add(row["work_id"])
                if row["outcome"] == "candidate":
                    decisions["candidate"].add(row["work_id"])
            elif row["decided_by"] != "human":
                decisions["code"].add(row["work_id"])
        sent = {row[0] for row in store.conn.execute(
            "SELECT DISTINCT v.work_id FROM model_proposals p JOIN run_steps s ON s.id = p.step_id"
            " JOIN source_versions v ON v.id = p.source_version_id WHERE s.run_id = ? AND p.stage = 'abstract'",
            (run_id,)) if row[0] in planned}
    counts |= {"screen_planned": len(planned), "code_decided": len(decisions["code"]), "sent_to_model": len(sent),
               "model_result": len(decisions["model"]), "candidates": len(decisions["candidate"]),
               "not_screened": len(set(planned) - decisions["code"] - decisions["model"])}
    return {"requests": requests, "counts": counts, "not_screened": list((screening or {}).get("left_out", []))}


async def execute(flow: Any, run: dict[str, Any], scope: dict[str, Any]) -> None:
    store, run_id = flow.store, run["id"]
    flow._run_gates[run_id] = lambda: _criterion_gate(flow, run)
    try:
        _gate(flow, run)
        context = _code(flow, run, CONTEXT_KEY, lambda: context_card(store, run, scope))
        plan_step = store.existing_step(run_id, PLAN_KEY)
        if plan_step is not None and plan_step["status"] == "succeeded":
            plan = plan_step["output"]
        else:
            output = await _query(flow, run, scope, context["card"])
            from deixis.workflow.candidates import terms
            try:
                built = request_plan(run["target"]["question"], output["result"], run["target"]["providers"])
            except terms.InvalidTerms as exc:
                flow._fail(run_id, "followup_query_invalid", {"detail": str(exc)})
            plan = _code(flow, run, PLAN_KEY, lambda: built)
        if not plan["requests"]:
            flow._fail(run_id, "followup_no_query")
        for position, item in enumerate(plan["requests"], start=1):
            sent = await _send(flow, run, position, item)
            if sent["status"] == "succeeded":
                _admit(flow, run, position, item, sent)
        found_ = _code(flow, run, FOUND_KEY, lambda: found(store, run, plan))
        if not any((store.existing_step(run_id, admit_key(p)) or {}).get("status") == "succeeded"
                   for p in range(1, len(plan["requests"]) + 1)):
            _code(flow, run, SUMMARY_KEY, lambda: summary(store, run, plan, found_, None))
            flow._fail(run_id, "followup_search_failed")
        screening = _code(flow, run, SCREEN_PLAN_KEY, lambda: screen_plan(store, run, found_))
        await _screen(flow, run, scope, screening)
        _code(flow, run, SUMMARY_KEY, lambda: summary(store, run, plan, found_, screening))
    finally:
        flow._run_gates.pop(run_id, None)


# ---- the turn's view -----------------------------------------------------------------------------------------------

def view(store: Any, turn: dict[str, Any], new_works_requested: bool | None) -> dict[str, Any]:
    """The turn's search: whether it is offered (and with what emphasis), and each of its runs with progress and,
    once written, the summary. Progress reads the stored steps, never an estimate."""
    offered = offer(store, turn)
    runs = []
    for run in turn_runs(store, turn["id"]):
        steps = {s["operation_key"]: s for s in store.run_steps(run["id"])}

        def done(key: str, run_id: str = run["id"]) -> Any:
            # The step's own stored output: `run_steps` carries only a view of it.
            step = store.existing_step(run_id, key) if key in steps else None
            return step["output"] if step is not None and step["status"] == "succeeded" else None
        plan, saved = done(PLAN_KEY), done(SUMMARY_KEY)
        screening = done(SCREEN_PLAN_KEY)
        # A run stopped after some admissions and before its found step still shows what it added to the research.
        result = saved if saved is not None else summary(store, run, plan, done(FOUND_KEY) or found_from(store.conn, run["research_id"], run["id"]), screening)
        sent = sum(1 for r in result["requests"] if r.get("sent"))  # a refusal closed before sending was not sent
        runs.append({"run_id": run["id"], "attempt": run["target"].get("attempt", 1), "status": run["status"],
                     "stage": run["stage"], "pause_reason": run["pause_reason"], "error": run["error"],
                     "progress": {"query": (steps.get(QUERY_KEY) or {}).get("status"),
                                  "requests_planned": len(plan["requests"]) if plan else None,
                                  "requests_sent": sent if plan else None,
                                  "found": done(FOUND_KEY) is not None,
                                  "screen_planned": len(screening["planned"]) if screening else None,
                                  "summary": saved is not None},
                     "summary": result})
    return {"emphasis": "suggested" if new_works_requested else "quiet", **offered, "runs": runs}
