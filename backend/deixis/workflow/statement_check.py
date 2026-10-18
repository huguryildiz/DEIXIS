"""Reverse citation search, slice R1 (plan `.local/plans/reverse-citation-search-plan.md`): the statement check.

A statement research (`researches.intent = 'statement'`) asks one sentence the person pasted; its question is that
sentence. After its search and reading, each work the reading reached (and each work the person included) is checked
against the sentence with Verify Citations V3's output schema, rules and verdict (D99), unchanged: `found_whole`,
`found_partial` or `not_found_in_given`, or `could_not_check`. Nothing says a work disagrees with the sentence, and a
sentence no work supports is not shown to be unsupported in the literature.

A check revision is frozen once, from the discovery's read cutoff (`fast_answer.CUTOFF`) and the person's choices as
they stand: every work becomes one item, first with its eligibility (`listed`, `out_of_cap`, `excluded_reason`,
`person_excluded`), then, listed only, with its execution status (`planned`, `done`, `could_not_check`, `no_text`). A
listed work's passages are drawn from a pool that follows the person's route (a PDF marked wrong is never read) and the
cutoff's file only, ranked as V3 ranks them (`citation_check.rank_pool`); the first `PASSAGES_PER_ITEM` are frozen
with their text hashes. Each item is sent once through `flow._model_step`, keyed by item and revision; before each send
and before its result is stored, the frozen inputs are checked again, and an item whose inputs changed is
`could_not_check` (`frozen_input_changed`), never sent.

R1 has no HTTP route: `create_check` is called by code only (slice R2 adds the request, the hook and the UI).
"""

from __future__ import annotations

import hashlib
import json
from collections import Counter
from typing import Any

from deixis.domain import canonical, contracts
from deixis.domain.citation_check import DEPTHS, RESULTS, PartAssessment, check_outcome
from deixis.domain.rules import MAX_SCHEMA_REPAIRS
from deixis.storage.db import dumps, new_id, now, transaction
from deixis.workflow import citation_check, fast_answer, small_batch
from deixis.workflow.store import NotFound, Store

KIND = TASK = "statement_check"
PASSAGES_PER_ITEM = citation_check.PASSAGES_PER_PAIR  # K: the passages one work is given, as a V3 pair is
WORK_CAPS = {"quick": 12, "standard": 24, "detailed": 40}  # works sent to the model, by the research's effort
PLAN_VERSION = 1
# The research question every item's StepInput carries; the sentence itself is in `statement_check_target`.
QUESTION = "Which parts of the sentence in statement_check_target do the given passages of the found work state?"
ELIGIBILITY = ("listed", "out_of_cap", "excluded_reason", "person_excluded")
STATUSES = ("planned", "done", "could_not_check", "no_text")
FROZEN_INPUT_CHANGED = "frozen_input_changed"


class Refused(Exception):
    """A check the research's state does not allow; `code` names why."""

    def __init__(self, code: str, detail: str):
        super().__init__(detail)
        self.code, self.detail = code, detail


class FrozenInputChanged(Exception):
    """Raised by the send gate when a frozen input of the item no longer holds: the step is closed unsent."""

    def __init__(self, reason: str):
        super().__init__(reason)
        self.reason = reason


def item_key(item_id: str, revision: int) -> str:
    return f"{TASK}:{item_id}:r{revision}"


def check_row(store: Store, check_id: str) -> dict[str, Any]:
    row = store.conn.execute("SELECT * FROM statement_checks WHERE id = ?", (check_id,)).fetchone()
    if row is None:
        raise NotFound(check_id)
    return dict(row)


def items_of(store: Store, check_id: str) -> list[dict[str, Any]]:
    return [dict(r) for r in store.conn.execute(
        "SELECT * FROM statement_check_items WHERE check_id = ? ORDER BY ordinal", (check_id,))]


# ------------------------------------------------------------------------------------------------- the frozen list

def passage_pool(store: Store, svid: str, route: str | None, asset_id: str | None) -> list[dict[str, Any]]:
    """The passages one work may be checked on, before any ranking: its first abstract passage and, when the person's
    route leaves the work on its full text, the pages of the file the read cutoff names (`asset_id`) at that file's
    current extraction. No other file or older extraction of the record is read, and a PDF the person marked wrong
    never is (`fast_answer.apply_user` turns such a work to its abstract)."""
    readable = store.passages_for(svid)
    pool = [p for p in readable if p["kind"] == "abstract"][:1]
    if route == "fulltext" and asset_id:
        pool += [p for p in readable if p["kind"] != "abstract" and p["asset_id"] == asset_id]
    return pool


def _plan(store: Store, svid: str, route: str, asset_id: str | None, sentence: str, ts: str) -> dict[str, Any] | None:
    """The frozen passage plan of one work, V3's shape (`citation_check._plan_for`) over its pool, with the file and
    extraction it read; None when the pool is empty. `full_text` also needs the file's extraction to have succeeded in
    full (`extraction_status = 'succeeded'`); a partial one reads as `selected_passages`."""
    pool = passage_pool(store, svid, route, asset_id)
    if not pool:
        return None
    ranked, terms = citation_check.rank_pool(store, svid, pool, sentence)
    pages = [p for p in pool if p["kind"] != "abstract"]
    given = ranked[:PASSAGES_PER_ITEM] if pages else ranked[:1]
    complete = None
    if pages:
        status = store.conn.execute("SELECT extraction_status FROM source_assets WHERE id = ?", (asset_id,)).fetchone()
        complete = status is not None and status["extraction_status"] == "succeeded"
    depth = "abstract" if not pages else "full_text" if len(given) == len(ranked) and complete else "selected_passages"
    ids = [p["id"] for p in given]
    return {"version": PLAN_VERSION, "frozen_at": ts, "source_version_id": svid, "route": route,
            "asset_id": asset_id if route == "fulltext" else None,
            "extraction_version": pages[0]["extraction_version"] if pages else None, "extraction_complete": complete,
            "depth": depth, "ranking": citation_check.RANKING, "terms": terms, "passages_per_item": PASSAGES_PER_ITEM,
            "passage_ids": ids,
            "passage_sha256": [hashlib.sha256(p["text"].encode("utf-8")).hexdigest() for p in given],
            "passage_chars": sum(len(p["text"]) for p in given),
            # `flow._step_input` sends each given passage whole: nothing is cut from the text sent.
            "passages_total": len(ranked), "passages_not_given": len(ranked) - len(given), "passages_cut": 0,
            "fingerprint": citation_check.text_fingerprint(pool),
            "selection_signature": canonical.sha256_hex({"passages_per_item": PASSAGES_PER_ITEM, "plan_version": PLAN_VERSION,
                                                         "ranking": citation_check.RANKING, "passage_ids": ids})}


def _text_version(store: Store, svid: str, asset_id: str | None) -> str | None:
    if asset_id and store.conn.execute("SELECT 1 FROM source_assets WHERE id = ? AND origin = 'user_upload'",
                                       (asset_id,)).fetchone():
        return "upload"
    return citation_check.text_version(store.source(svid))


def _pdf_admissible(row: dict[str, Any], humans: dict[str, Any]) -> None:
    """A PDF the person marked wrong (their current decision on the work) never enters the pool: the work's route
    turns to its abstract, whatever its inclusion says."""
    if (humans.get(row["work_id"]) or {}).get("state") == "pdf_wrong" and row["route"] == "fulltext":
        row["route"] = "abstract"


def _freeze_items(flow: Any, rid: str, cutoff: dict[str, Any], sentence: str, cap: int, ts: str) -> list[dict[str, Any]]:
    """One item per work: the cutoff's rows with the person's choices as they stand now (`fast_answer.apply_user`, the
    order an answer gives them), and each work the person included that the cutoff holds no row for. A work the person
    included is listed whatever screening said of it and goes first; one they excluded is `person_excluded`; any other
    row that carries a reason stays out with it. The first `cap` listed works with text are `planned`, later ones
    `out_of_cap`; a listed work with no passage to read is `no_text` and takes no place under the cap. Inclusion and
    the PDF's admissibility are read apart: a work whose PDF the person marked wrong is read from its abstract even
    when they also included it (`apply_user` would keep an included work on its full text)."""
    store = flow.store
    rows = json.loads(json.dumps(cutoff["output"]["items"]))
    selections, humans = fast_answer.user_choices(store, rid)
    for row in rows:
        fast_answer.apply_user(row, selections.get(row["head"]) or humans.get(row["work_id"]))
        _pdf_admissible(row, humans)
        if not row["reason"] and not (row["fulltext_ids"] if row["route"] == "fulltext" else row["abstract_ids"]):
            row["reason"] = "no_text_at_cutoff"
    held = {row["work_id"] for row in rows} | set(store.work_ids(
        list({svid for row in rows for svid in (row["head"], row["source_version_id"])})).values())
    works = {wid: head for wid, head in fast_answer.included_heads(store, rid).items() if wid not in held}
    added, missing = fast_answer.after_cutoff_rows(store, flow, rid, works) if works else ([], [])
    for row in added:
        _pdf_admissible(row, humans)
    rows += added + [row | {"route": None, "asset_id": None, "user_priority": True} for row in missing]
    rows.sort(key=lambda row: not row["user_priority"])  # stable: the reading order stays within each group
    members = fast_answer.current_members(store, rid)
    items, planned = [], 0
    for ordinal, row in enumerate(rows, start=1):
        svid = row["source_version_id"]
        item = {"id": new_id("sci"), "ordinal": ordinal, "work_id": row["work_id"], "source_version_id": svid,
                "route": row.get("route"), "entry": "person_included" if row["user_priority"] else "reading",
                "excluded_reason": None, "status": None, "plan": None,
                "text_version": _text_version(store, svid, row.get("asset_id"))}
        if row["reason"] == "user_excluded":
            item["eligibility"] = "person_excluded"
        elif row["reason"] and not row["user_priority"]:
            item |= {"eligibility": "excluded_reason", "excluded_reason": row["reason"]}
        elif svid not in members:
            item |= {"eligibility": "excluded_reason", "excluded_reason": "removed_after_cutoff"}
        elif (plan := _plan(store, svid, row["route"], row.get("asset_id"), sentence, ts) if row.get("route") else None) is None:
            item |= {"eligibility": "listed", "status": "no_text"}
        elif planned >= cap:
            item["eligibility"] = "out_of_cap"
        else:
            planned += 1
            item |= {"eligibility": "listed", "status": "planned", "plan": plan}
        items.append(item)
    return items


def create_check(flow: Any, research_id: str, discovery_run_id: str, model: dict[str, Any] | None,
                 request_id: str) -> dict[str, Any]:
    """Open a check revision of a statement research and queue its run, in one transaction (private in R1: no route
    calls it). The model (`connection`, `model`, `reasoning_effort`) is frozen into the run with the method package
    and a budget of one call and one repair per planned work. A request id already used returns that revision. Refused
    without a model, for another intent, and unless the discovery is the completed one of the current question with its
    read cutoff stored; `store.create_run` refuses it while another run of the research is active. A request id is
    one research's: used by another research, it is refused (`request_conflict`), never answered with that check."""
    store = flow.store
    if not model or not model.get("connection") or not model.get("model"):
        raise Refused("no_model", "A statement check needs a model connection and a model")
    frozen = {"connection": model["connection"], "model": model["model"],
              "reasoning_effort": model.get("reasoning_effort") or None}
    with transaction(store.conn):
        existing = store.conn.execute("SELECT id, research_id FROM statement_checks WHERE request_id = ?",
                                      (request_id,)).fetchone()
        if existing and existing["research_id"] != research_id:
            raise Refused("request_conflict", "This request id belongs to another research's check")
        if existing:
            return check_row(store, existing["id"])
        research = store.research(research_id)
        if research["intent"] != "statement":
            raise Refused("not_statement", "Only a statement research has a statement check")
        discovery = store.run(discovery_run_id)
        if ((discovery["research_id"], discovery["kind"], discovery["status"]) != (research_id, "discovery", "completed")
                or discovery["scope_revision"] != research["current_scope_revision"]):
            raise Refused("discovery_mismatch", "The run is not the completed discovery of the current question")
        cutoff = store.existing_step(discovery_run_id, fast_answer.CUTOFF)
        if cutoff is None or cutoff["status"] != "succeeded":
            raise Refused("cutoff_missing", "The discovery stored no read cutoff")
        scope = store.scope(research_id, discovery["scope_revision"])
        sentence, cap, ts = scope["question"], WORK_CAPS[scope["effort"]], now()
        items = _freeze_items(flow, research_id, cutoff, sentence, cap, ts)
        revision = 1 + store.conn.execute("SELECT COALESCE(MAX(revision), 0) FROM statement_checks WHERE research_id = ?",
                                          (research_id,)).fetchone()[0]
        check_id, package_hash = new_id("stc"), flow.deps.package.package_hash
        store.conn.execute(
            "INSERT INTO statement_checks (id, research_id, revision, request_id, sentence, sentence_sha256, scope_revision,"
            " discovery_run_id, cutoff_step_id, user_signature, effort, work_cap, model_json, skill_package_hash,"
            " created_at) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)",
            (check_id, research_id, revision, request_id, sentence, hashlib.sha256(sentence.encode("utf-8")).hexdigest(),
             discovery["scope_revision"], discovery_run_id, cutoff["id"], small_batch.user_signature(store, research_id),
             scope["effort"], cap, dumps(frozen), package_hash, ts))
        for item in items:
            plan = item["plan"] or {}
            store.conn.execute(
                "INSERT INTO statement_check_items (id, check_id, ordinal, work_id, source_version_id, text_version, route,"
                " entry, eligibility, excluded_reason, status, depth, asset_id, extraction_version, extraction_complete,"
                " plan_json) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)",
                (item["id"], check_id, item["ordinal"], item["work_id"], item["source_version_id"], item["text_version"],
                 item["route"], item["entry"], item["eligibility"], item["excluded_reason"], item["status"],
                 plan.get("depth"), plan.get("asset_id"), plan.get("extraction_version"),
                 None if plan.get("extraction_complete") is None else int(plan["extraction_complete"]),
                 dumps(item["plan"]) if item["plan"] else None))
        planned = sum(item["status"] == "planned" for item in items)
        run = store.create_run(
            research_id, KIND, {"max_model_calls": planned * (1 + MAX_SCHEMA_REPAIRS), "max_provider_requests": 0},
            f"{KIND}:{check_id}", target={"statement_check_id": check_id, "revision": revision, "model": frozen,
                                          "skill_package_hash": package_hash})
        store.conn.execute("UPDATE statement_checks SET run_id = ?, status = ? WHERE id = ?",
                           (run["id"], "open" if planned else "finished", check_id))
    return check_row(store, check_id)


# ---------------------------------------------------------------------------------------------------- the check

def binding_changed(store: Store, check: dict[str, Any], item: dict[str, Any]) -> str | None:
    """Why a planned item's frozen inputs no longer hold, or None: the question moved on, the record left the research,
    or its pool changed (a passage, a file, an extraction; `text_fingerprint`) or a given passage's text did."""
    plan = json.loads(item["plan_json"])
    research = store.conn.execute("SELECT current_scope_revision FROM researches WHERE id = ?",
                                  (check["research_id"],)).fetchone()
    if research is None or research["current_scope_revision"] != check["scope_revision"]:
        return "scope_revision_changed"
    svid = plan["source_version_id"]
    if not store.conn.execute("SELECT 1 FROM corpus_memberships WHERE research_id = ? AND source_version_id = ?"
                              " AND removed_at IS NULL", (check["research_id"], svid)).fetchone():
        return "source_removed"
    if citation_check.text_fingerprint(passage_pool(store, svid, plan["route"], plan["asset_id"])) != plan["fingerprint"]:
        return "passages_changed"
    for passage_id, sha in zip(plan["passage_ids"], plan["passage_sha256"]):
        row = store.conn.execute("SELECT text FROM passages WHERE id = ?", (passage_id,)).fetchone()
        if row is None or hashlib.sha256(row["text"].encode("utf-8")).hexdigest() != sha:
            return "passages_changed"
    return None


async def _send(flow: Any, run: dict[str, Any], model: tuple[str, str, str | None], check: dict[str, Any],
                item: dict[str, Any], key: str) -> dict[str, Any]:
    """One item's model step. The last look before each send (the first and the repair): a stop or a changed method
    package stops the run; a frozen input that no longer holds closes this item unsent (`FrozenInputChanged`). The
    StepInput is built from the frozen passage ids, read again for each attempt."""
    store, run_id = flow.store, run["id"]
    plan = json.loads(item["plan_json"])
    scope = {"question": QUESTION, "language_hint": None, "steering": None, "providers": [],
             "model_connection": model[0], "requested_model": model[1], "reasoning_effort": model[2]}

    def gate() -> None:
        flow._checkpoint(run_id)
        if run["target"]["skill_package_hash"] != flow.deps.package.package_hash:
            flow._fail(run_id, "skill_package_changed")
        if (reason := binding_changed(store, check, item)) is not None:
            raise FrozenInputChanged(reason)

    def build(step_id: str) -> dict[str, Any]:
        rows = [store.passage(passage_id) for passage_id in plan["passage_ids"]]
        payload = flow._step_input(run, scope, step_id, TASK, [], [plan["source_version_id"]], rows, [], model)
        return payload | {"statement_check_target": {
            "item_id": item["id"], "sentence": check["sentence"], "assessed_source_id": plan["source_version_id"],
            "depth": item["depth"], "passages_not_given": plan["passages_not_given"]}}

    return await flow.deps.limiter.run(f"{run_id}:{key}", lambda: flow._model_step(
        run, scope, key, TASK, model=model, limiter=flow.deps.limiter, send_gate=gate, step_input_builder=build))


def _publish(store: Store, run: dict[str, Any], check: dict[str, Any], item: dict[str, Any],
             output: dict[str, Any], changed: str | None) -> dict[str, Any]:
    """The code's verdict on one ended item, stored with its validation record in one write, V3's way
    (`citation_check._store_check`): a valid output is `done` only when `derive_result` reads a result from the
    backend's own located quotes and the coverage the parts' positions give; an output still invalid after its repair,
    or one whose frozen inputs changed, is `could_not_check` with no result. Either keeps the raw output and the run
    and model of the step that answered."""
    step_input_id = output.get("step_input_id")
    anchors, result_doc, covers = None, None, None
    if changed is not None:
        outcome = {"status": "could_not_check", "result": None, "error": {"code": FROZEN_INPUT_CHANGED, "reason": changed}}
    elif output.get("invalid"):
        code = "message_too_large" if output.get("message_too_large") else "invalid_model_output"
        outcome = {"status": "could_not_check", "result": None,
                   "error": {"code": code, "issues": output.get("issues") or []}}
    else:
        result_doc = output["result"]
        view = contracts.citation_check_view(store.step_input_payload(step_input_id))
        anchors = contracts.citation_check_anchors(view, result_doc)
        parts = [PartAssessment(part["assessment"], tuple(a["located"] for a in located))
                 for part, located in zip(result_doc["parts"], anchors)]
        covers = result_doc["covers_whole_sentence"] is True and contracts.citation_check_covers(
            view["citation_check_target"]["sentence"], result_doc["parts"])
        outcome = check_outcome(parts, covers)
        if outcome["error"] is not None:
            outcome["error"] = {"code": outcome["error"], "issues": []}
    kinds = sorted({a["passage_kind"] for part in anchors or [] for a in part if a["located"] and a["passage_kind"]})
    validation = {"ok": outcome["status"] == "done", "covers_whole_sentence": covers,
                  "error": (outcome["error"] or {}).get("code"), "issues": (outcome["error"] or {}).get("issues", [])}
    raw = citation_check._raw_output(store, step_input_id)
    record = citation_check._provenance(store, step_input_id)
    sent_by = record.pop("run_id") or run["id"]
    with transaction(store.conn):
        store.conn.execute(
            "UPDATE statement_check_items SET status = ?, result = ?, error_json = ?, output_json = ?,"
            " located_anchors_json = ?, located_passage_kinds_json = ?, validation_json = ?, raw_output = ?,"
            " model_json = ?, run_id = ?, step_input_id = ?, checked_at = ? WHERE id = ? AND status = 'planned'",
            (outcome["status"], outcome["result"], dumps(outcome["error"]) if outcome["error"] is not None else None,
             dumps(result_doc) if result_doc is not None else None, dumps(anchors) if anchors is not None else None,
             dumps(kinds), dumps(validation), raw, dumps(record), sent_by, step_input_id, now(), item["id"]))
        store.conn.execute(
            "UPDATE statement_checks SET status = 'finished' WHERE id = ? AND NOT EXISTS (SELECT 1 FROM"
            " statement_check_items WHERE check_id = ? AND status = 'planned')", (check["id"], check["id"]))
    return outcome


def _last_input(store: Store, run_id: str, key: str) -> str | None:
    row = store.conn.execute(
        "SELECT i.id FROM step_inputs i JOIN run_steps s ON s.id = i.step_id WHERE s.run_id = ? AND s.operation_key = ?"
        " ORDER BY i.rowid DESC LIMIT 1", (run_id, key)).fetchone()
    return row["id"] if row else None


async def execute(flow: Any, run: dict[str, Any], scope: dict[str, Any]) -> None:
    """Check every planned item of the run's revision, in list order, on the model the run froze. A step that already
    ended for good in any statement-check run of the research (succeeded, or its repair ran out) is read back, never
    sent again. A provider failure or a person's stop pauses the run with the item still `planned`, and the run's
    resume goes on from there."""
    store, run_id = flow.store, run["id"]
    check = check_row(store, run["target"]["statement_check_id"])
    if run["target"]["skill_package_hash"] != flow.deps.package.package_hash:
        flow._fail(run_id, "skill_package_changed")
    frozen = run["target"]["model"]
    model = (frozen["connection"], frozen["model"], frozen.get("reasoning_effort") or None)
    planned = [dict(r) for r in store.conn.execute(
        "SELECT * FROM statement_check_items WHERE check_id = ? AND status = 'planned' ORDER BY ordinal", (check["id"],))]
    for item in planned:
        flow._checkpoint(run_id)
        key = item_key(item["id"], check["revision"])
        output = citation_check._recorded(store, run["research_id"], key, KIND)
        changed = None
        if output is None:
            changed = binding_changed(store, check, item)
            if changed is None:
                try:
                    output = await _send(flow, run, model, check, item, key)
                except FrozenInputChanged as exc:
                    changed = exc.reason
                    step = store.existing_step(run_id, key)
                    store.finish_step(step["id"], "cancelled", error_code=FROZEN_INPUT_CHANGED, error={"reason": changed})
                    output = {"step_input_id": _last_input(store, run_id, key)}
        if changed is None:
            changed = binding_changed(store, check, item)  # the last look before the result is stored
        _publish(store, run, check, item, output or {}, changed)
    flow._checkpoint(run_id)


# ------------------------------------------------------------------------------------------- counters and export

def counters(store: Store, check: dict[str, Any]) -> dict[str, Any]:
    """The statement-check box of one revision, apart from the search box (`flow_counts.funnel`), which this mode never
    redefines. Each work counts once. Candidates are the listed, out-of-cap and reason-excluded works; the person's
    exclusions are counted apart. Listed = the sum of the four statuses. Sent: items whose step reached the model at
    least once (a repair is not a second one). A call counts as sent unless it is known never to have left: no token
    usage and an `unavailable` result, or its step's last attempt closed `before_send`. A call whose delivery is
    unknown (a process that stopped, `after_send_unknown`) or that the provider refused counts as sent. Completed = the three results; `could_not_check` is none of them. Each
    result is split by the work's one depth, and the passage kinds the located quotes came from are counted apart."""
    items = items_of(store, check["id"])
    eligibility = Counter(item["eligibility"] for item in items)
    status = Counter(item["status"] for item in items if item["eligibility"] == "listed")
    done = [item for item in items if item["status"] == "done"]
    keys = [item_key(item["id"], check["revision"]) for item in items if item["eligibility"] == "listed"]
    sent = store.conn.execute(
        f"SELECT COUNT(DISTINCT s.operation_key) FROM run_steps s JOIN runs r ON r.id = s.run_id WHERE r.research_id = ?"
        f" AND r.kind = ? AND s.operation_key IN ({','.join('?' * len(keys))})"
        f" AND EXISTS (SELECT 1 FROM model_sessions m WHERE m.step_id = s.id AND NOT (m.token_usage_json IS NULL"
        f" AND (m.status = 'unavailable' OR (s.delivery_class IS 'before_send'"
        f" AND m.rowid = (SELECT MAX(rowid) FROM model_sessions WHERE step_id = s.id)))))",
        (check["research_id"], KIND, *keys)).fetchone()[0] if keys else 0
    kinds = Counter(kind for item in done for kind in json.loads(item["located_passage_kinds_json"] or "[]"))
    return {
        "candidates": eligibility["listed"] + eligibility["out_of_cap"] + eligibility["excluded_reason"],
        **{name: eligibility[name] for name in ELIGIBILITY},
        "excluded_reasons": dict(Counter(item["excluded_reason"] for item in items if item["excluded_reason"])),
        "by_status": {name: status[name] for name in STATUSES},
        "sent_to_model": sent,
        "completed": len(done),
        "results": {result: sum(item["result"] == result for item in done) for result in RESULTS},
        "results_by_depth": {result: {depth: sum(item["result"] == result and item["depth"] == depth for item in done)
                                      for depth in DEPTHS} for result in RESULTS},
        "works_with_located_quotes_from": {"abstract": kinds["abstract"], "pages": sum(n for k, n in kinds.items()
                                                                                      if k != "abstract")},
    }


EXPORT_COLUMNS = ("ordinal", "title", "year", "doi", "source_version_id", "text_version", "entry", "eligibility",
                  "excluded_reason", "status", "result", "depth", "passages_given", "passages_not_given",
                  "passages_cut", "extraction_complete", "located_passage_kinds", "error", "located_quotes",
                  "revision", "currency")


def export_rows(store: Store, check_id: str) -> list[dict[str, Any]]:
    """One row per work in list order: the record's own title, year and DOI, eligibility, status and result kept apart
    (a `could_not_check` work has no result), the depth with the given, not-given and cut passage counts, whether the
    extraction was complete, the error, the backend's located words with their page, and the revision's currency."""
    check = check_row(store, check_id)
    rows = []
    for item in items_of(store, check_id):
        source = store.source(item["source_version_id"]) if item["source_version_id"] else {}
        plan = json.loads(item["plan_json"]) if item["plan_json"] else {}
        quotes = []
        for part in json.loads(item["located_anchors_json"] or "[]"):
            for anchor in part:
                if anchor["located"]:
                    page = store.passage(anchor["passage_id"])["physical_page"]
                    quotes.append(f"{'abstract' if page is None else f'p. {page}'}: {anchor['anchor_text']}")
        rows.append({"ordinal": item["ordinal"], "title": source.get("title"), "year": source.get("year"),
                     "doi": source.get("doi"), "source_version_id": item["source_version_id"],
                     "text_version": item["text_version"], "entry": item["entry"], "eligibility": item["eligibility"],
                     "excluded_reason": item["excluded_reason"], "status": item["status"], "result": item["result"],
                     "depth": item["depth"], "passages_given": len(plan["passage_ids"]) if plan else None,
                     "passages_not_given": plan.get("passages_not_given"), "passages_cut": plan.get("passages_cut"),
                     "extraction_complete": None if item["extraction_complete"] is None else bool(item["extraction_complete"]),
                     "located_passage_kinds": json.loads(item["located_passage_kinds_json"] or "[]"),
                     "error": (json.loads(item["error_json"]) if item["error_json"] else {}).get("code"),
                     "located_quotes": quotes, "revision": check["revision"], "currency": check["currency"]})
    return rows


def export(store: Store, check_id: str, fmt: str) -> str:
    """The rows as CSV or Markdown, as Verify Citations writes them (`citation_check.export`)."""
    import csv
    import io
    rows = export_rows(store, check_id)

    def cell(value: Any) -> str:
        if isinstance(value, list):
            return " | ".join(str(v) for v in value)
        return "" if value is None else str(value)

    if fmt == "csv":
        out = io.StringIO()
        writer = csv.writer(out)
        writer.writerow(EXPORT_COLUMNS)
        for row in rows:
            writer.writerow([cell(row[c]) for c in EXPORT_COLUMNS])
        return out.getvalue()
    lines = ["| " + " | ".join(EXPORT_COLUMNS) + " |", "|" + "---|" * len(EXPORT_COLUMNS)]
    for row in rows:
        lines.append("| " + " | ".join(cell(row[c]).replace("|", "\\|").replace("\n", " ") for c in EXPORT_COLUMNS) + " |")
    return "\n".join(lines) + "\n"
