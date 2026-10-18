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

Starting (slice R2). A check revision opens in three ways, all through `create_check`, each with its own budget (one
call and one repair per planned work) and the model frozen at the request, before any pricing: the person's request
(`POST /api/researches/{id}/runs` with kind `statement_check`, `request`), which is also how they check again (a new
request id, a new revision from the same cutoff with their choices and the records as they are now, no new search),
and the end of a statement research's discovery (`after_discovery`, with the literature model in Settings at that
moment, keyed so it opens one revision). A paused run is resumed through the run resume path, on its own revision and
frozen model. A research whose scope is its attached files has no discovery: its list is frozen when its run starts,
from the attached files, once none of them is still being extracted (`attachment_snapshot_json`).

A revision is `stale` (`refresh_currency`), never rewritten or deleted, once the question moved on, the person's
choices changed after its freeze, or the text of a work it lists did. Its results stay, marked as not current.
"""

from __future__ import annotations

import hashlib
import json
from collections import Counter
from typing import Any

from deixis.domain import canonical, contracts, statement
from deixis.domain.citation_check import DEPTHS, RESULTS, PartAssessment, check_outcome
from deixis.domain.rules import MAX_SCHEMA_REPAIRS
from deixis.domain.rules import RevisionConflict
from deixis.storage.db import dumps, new_id, now, rollback_savepoint, transaction
from deixis.workflow import citation_check, fast_answer, small_batch
from deixis.workflow.store import NotFound, Store

KIND = TASK = "statement_check"
PASSAGES_PER_ITEM = citation_check.PASSAGES_PER_PAIR  # K: the passages one work is given, as a V3 pair is
MAX_SENTENCE_CHARS = statement.MAX_SENTENCE_CHARS  # one sentence, as Home takes it (`domain.statement`)
WORK_CAPS = {"quick": 12, "standard": 24, "detailed": 40}  # works sent to the model, by the research's effort
PLAN_VERSION = 1
# The research question every item's StepInput carries; the sentence itself is in `statement_check_target`.
QUESTION = "Which parts of the sentence in statement_check_target do the given passages of the found work state?"
ELIGIBILITY = ("listed", "out_of_cap", "excluded_reason", "person_excluded")
STATUSES = ("planned", "done", "could_not_check", "no_text")
FROZEN_INPUT_CHANGED = "frozen_input_changed"
EXTRACTING = "attachments_extracting"  # the pause reason of an attached-scope check whose files are still read
WAITING = {"status": "waiting"}  # an attached-scope revision before its list is frozen


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
    return _items(store, rows, fast_answer.current_members(store, rid), sentence, cap, ts)


def _items(store: Store, rows: list[dict[str, Any]], members: dict[str, Any], sentence: str, cap: int,
           ts: str) -> list[dict[str, Any]]:
    """One item per row, in order: its eligibility, and for a listed work its plan, or `no_text` with none."""
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


def settings_model(store: Store) -> dict[str, Any] | None:
    """The literature model in Settings now, as a check stores it; None when Settings names none."""
    default = store.setting("literature") or {}
    if not default.get("model_connection") or not default.get("model"):
        return None
    return {"connection": default["model_connection"], "model": default["model"],
            "reasoning_effort": default.get("reasoning_effort") or None}


def latest_discovery(store: Store, research_id: str, scope_revision: int) -> str | None:
    row = store.conn.execute(
        "SELECT id FROM runs WHERE research_id = ? AND kind = 'discovery' AND status = 'completed' AND scope_revision = ?"
        " ORDER BY created_at DESC, rowid DESC LIMIT 1", (research_id, scope_revision)).fetchone()
    return row["id"] if row else None


def request(flow: Any, research_id: str, request_id: str, model: dict[str, Any] | None = None,
            expected_scope_revision: int | None = None) -> dict[str, Any]:
    """The person's request for a check, or for a new check of the same sentence (a new request id): a new revision
    frozen from the latest completed discovery of the current question (no new search), or, in an attached-scope
    research, from its attached files when its run starts. The model is the one named, else the literature model in
    Settings now; either is stored with the revision before it is priced."""
    store = flow.store
    model = model if model and model.get("model") else settings_model(store)
    with transaction(store.conn):
        research = store.research(research_id)
        discovery = latest_discovery(store, research_id, research["current_scope_revision"])
        return create_check(flow, research_id, discovery, model, request_id, expected_scope_revision)


def create_check(flow: Any, research_id: str, discovery_run_id: str | None, model: dict[str, Any] | None,
                 request_id: str, expected_scope_revision: int | None = None) -> dict[str, Any]:
    """Open a check revision of a statement research and queue its run, in one transaction. The model (`connection`,
    `model`, `reasoning_effort`) is frozen into the revision and the run with the method package and a budget of one
    call and one repair per planned work. A request id already used by this research returns that revision; used by
    another research, it is refused (`request_conflict`), never answered with that check. Refused without a model, for
    another intent, when `expected_scope_revision` is not the current question revision, unless the discovery is the
    completed one of the current question with its read cutoff stored (an attached-scope research has none), and while
    any run of the research is active (`run_active`, read in this transaction)."""
    store = flow.store
    with transaction(store.conn):
        existing = store.conn.execute("SELECT id, research_id FROM statement_checks WHERE request_id = ?",
                                      (request_id,)).fetchone()
        if existing and existing["research_id"] != research_id:
            raise Refused("request_conflict", "This request id belongs to another research's check")
        if existing:
            return check_row(store, existing["id"])
        if not model or not model.get("connection") or not model.get("model"):
            raise Refused("no_model", "A statement check needs a model connection and a model")
        frozen = {"connection": model["connection"], "model": model["model"],
                  "reasoning_effort": model.get("reasoning_effort") or None}
        research = store.research(research_id)
        if research["intent"] != "statement":
            raise Refused("not_statement", "Only a statement research has a statement check")
        try:
            statement.check_sentence(store.scope(research_id)["question"])
        except statement.StatementTooLong as exc:  # a sentence stored before the limit applied everywhere
            raise Refused("sentence_too_long", str(exc)) from exc
        if expected_scope_revision is not None and expected_scope_revision != research["current_scope_revision"]:
            raise Refused("revision_mismatch", f"The research is at question revision"
                                               f" {research['current_scope_revision']}, not {expected_scope_revision}")
        scope = store.scope(research_id)
        cutoff, items, snapshot = None, [], None
        if scope["source_scope"] == "attached":
            snapshot = WAITING  # frozen from the attached files when the run starts (`_freeze_attached`)
        else:
            discovery = store.run(discovery_run_id) if discovery_run_id else None
            if (discovery is None or (discovery["research_id"], discovery["kind"], discovery["status"])
                    != (research_id, "discovery", "completed")
                    or discovery["scope_revision"] != research["current_scope_revision"]):
                raise Refused("discovery_mismatch", "The run is not the completed discovery of the current question")
            cutoff = store.existing_step(discovery_run_id, fast_answer.CUTOFF)
            if cutoff is None or cutoff["status"] != "succeeded":
                raise Refused("cutoff_missing", "The discovery stored no read cutoff")
        if citation_check._active_run(store, research_id):
            raise Refused("run_active", "A run of this research is still active")
        sentence, cap, ts = scope["question"], WORK_CAPS[scope["effort"]], now()
        if cutoff is not None:
            items = _freeze_items(flow, research_id, cutoff, sentence, cap, ts)
        revision = 1 + store.conn.execute("SELECT COALESCE(MAX(revision), 0) FROM statement_checks WHERE research_id = ?",
                                          (research_id,)).fetchone()[0]
        check_id, package_hash = new_id("stc"), flow.deps.package.package_hash
        store.conn.execute(
            "INSERT INTO statement_checks (id, research_id, revision, request_id, sentence, sentence_sha256, scope_revision,"
            " discovery_run_id, cutoff_step_id, attachment_snapshot_json, user_signature, effort, work_cap, model_json,"
            " skill_package_hash, created_at) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)",
            (check_id, research_id, revision, request_id, sentence, hashlib.sha256(sentence.encode("utf-8")).hexdigest(),
             scope["revision"], discovery_run_id if cutoff else None, cutoff["id"] if cutoff else None,
             dumps(snapshot) if snapshot else None, small_batch.user_signature(store, research_id), scope["effort"],
             cap, dumps(frozen), package_hash, ts))
        _insert_items(store, check_id, items)
        planned = sum(item["status"] == "planned" for item in items)
        run = store.create_run(research_id, KIND, _budget(planned), f"{KIND}:{check_id}",
                               target={"statement_check_id": check_id, "revision": revision, "model": frozen,
                                       "skill_package_hash": package_hash})
        store.conn.execute("UPDATE statement_checks SET run_id = ?, status = ? WHERE id = ?",
                           (run["id"], "open" if planned or snapshot else "finished", check_id))
    return check_row(store, check_id)


def _budget(planned: int) -> dict[str, Any]:
    return {"max_model_calls": planned * (1 + MAX_SCHEMA_REPAIRS), "max_provider_requests": 0}


def _insert_items(store: Store, check_id: str, items: list[dict[str, Any]]) -> None:
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


def after_discovery(flow: Any, run: dict[str, Any]) -> None:
    """Open the first check of a statement research's completed discovery, in the transaction that completes it, on
    the literature model in Settings at that moment (stored with the revision). Keyed by research, question revision
    and cutoff step, so a replayed completion opens no second revision. No model in Settings, or any other refusal,
    writes a `statement_check_skipped` event and starts nothing; no other model is used."""
    if (run["budget"].get("fast_path") or {}).get("after_discovery") != "statement_check":
        return
    store, rid = flow.store, run["research_id"]
    cutoff = store.existing_step(run["id"], fast_answer.CUTOFF)
    reason, savepoint = None, new_id("statement_auto")
    store.conn.execute(f"SAVEPOINT {savepoint}")
    try:
        if cutoff is None or cutoff["status"] != "succeeded":
            raise Refused("cutoff_missing", "The discovery stored no read cutoff")
        create_check(flow, rid, run["id"], settings_model(store),
                     f"{KIND}:auto:{rid}:{run['scope_revision']}:{cutoff['id']}")
    except Refused as exc:
        rollback_savepoint(store.conn, savepoint)
        reason = exc.code
    except RevisionConflict:
        rollback_savepoint(store.conn, savepoint)
        reason = "run_active"
    else:
        store.conn.execute(f"RELEASE {savepoint}")
    if reason:
        store._event(rid, "statement_check_skipped", {"reason": reason}, run["id"])


# ------------------------------------------------------------------------------------------------ attached scope

def _attached_assets(store: Store, research_id: str) -> list[tuple[str, dict[str, Any] | None]]:
    """Each attached record of the research, in the order the research holds them, with its file in use (or None)."""
    members = [*store.included_sources(research_id), *sorted(set(fast_answer.current_members(store, research_id))
                                                             - set(store.included_sources(research_id)))]
    out = []
    for svid in members:
        asset = store.conn.execute(
            "SELECT id, extraction_status, extraction_version FROM source_assets WHERE source_version_id = ?"
            " AND removed_at IS NULL", (svid,)).fetchone()
        out.append((svid, dict(asset) if asset else None))
    return out


def _asset_in_use(store: Store, svid: str) -> str | None:
    row = store.conn.execute("SELECT id FROM source_assets WHERE source_version_id = ? AND removed_at IS NULL",
                             (svid,)).fetchone()
    return row["id"] if row else None


def _extracting(store: Store, research_id: str) -> list[str]:
    return [svid for svid, asset in _attached_assets(store, research_id)
            if asset is not None and asset["extraction_status"] == "pending"]


def _asset_text_sha256(store: Store, asset_id: str, extraction_version: str | None) -> str:
    texts = [r["text"] for r in store.conn.execute(
        "SELECT text FROM passages WHERE asset_id = ? AND extraction_version IS ? ORDER BY physical_page, rowid",
        (asset_id, extraction_version))]
    return hashlib.sha256("\n".join(texts).encode("utf-8")).hexdigest()


def _freeze_attached(store: Store, check_id: str) -> None:
    """Freeze an attached-scope revision's list from the attached files as they are now, with the snapshot of each
    file (asset, extraction version, text hash), the person's choices and the run's budget, in one write. Every attached
    work is the person's; one they excluded is `person_excluded`, a PDF they marked wrong is read from its abstract, and
    a file whose extraction failed gives no pages, so a work with no other text is `no_text`. One write: a second
    caller (the run and a preview) finds the list frozen and writes nothing."""
    with transaction(store.conn):
        check = check_row(store, check_id)
        if waiting(check):
            _freeze_attached_now(store, check)


def _freeze_attached_now(store: Store, check: dict[str, Any]) -> None:
    rid = check["research_id"]
    selections, humans = fast_answer.user_choices(store, rid)
    members = fast_answer.current_members(store, rid)
    rows, snapshot, seen = [], [], set()
    for svid, asset in _attached_assets(store, rid):
        work_id = members[svid]["work_id"]
        if work_id in seen:
            continue  # one item per work
        seen.add(work_id)
        row = {"work_id": work_id, "source_version_id": svid, "route": "fulltext" if asset else "abstract",
               "asset_id": asset["id"] if asset else None, "user_priority": True,
               "reason": "user_excluded" if (selections.get(svid) or {}).get("state") == "excluded" else None}
        _pdf_admissible(row, humans)
        rows.append(row)
        if asset:
            snapshot.append({"source_version_id": svid, "asset_id": asset["id"],
                             "extraction_status": asset["extraction_status"],
                             "extraction_version": asset["extraction_version"],
                             "text_sha256": _asset_text_sha256(store, asset["id"], asset["extraction_version"])})
    items = _items(store, rows, members, check["sentence"], check["work_cap"], now())
    _insert_items(store, check["id"], items)
    planned = sum(item["status"] == "planned" for item in items)
    store.conn.execute(
        "UPDATE statement_checks SET attachment_snapshot_json = ?, user_signature = ?, status = ? WHERE id = ?",
        (dumps({"status": "frozen", "assets": snapshot}), small_batch.user_signature(store, rid),
         "open" if planned else "finished", check["id"]))
    store.conn.execute("UPDATE runs SET budget_json = ? WHERE id = ?", (dumps(_budget(planned)), check["run_id"]))


def waiting(check: dict[str, Any]) -> bool:
    return bool(check["attachment_snapshot_json"]) and json.loads(check["attachment_snapshot_json"]) == WAITING


# --------------------------------------------------------------------------------------------------- currency

def stale_reason(store: Store, check: dict[str, Any]) -> str | None:
    """Why a revision no longer stands for the research as it is, or None: the question moved on
    (`question_changed`), the person included, excluded or judged a work or file since its freeze
    (`person_choice_changed`, `small_batch.user_signature`), a work it froze left the research (`source_removed`: a
    removal keeps the record, its files and passages, so no text check sees it), or the text of a work it lists
    changed: a file, an extraction or a passage of a planned or checked work's pool, or an attached file of its
    snapshot (`source_changed`)."""
    research = store.conn.execute("SELECT current_scope_revision FROM researches WHERE id = ?",
                                  (check["research_id"],)).fetchone()
    if research is None or research["current_scope_revision"] != check["scope_revision"]:
        return "question_changed"
    if waiting(check):
        return None  # nothing is frozen yet
    if check["user_signature"] != small_batch.user_signature(store, check["research_id"]):
        return "person_choice_changed"
    frozen = items_of(store, check["id"])
    members = fast_answer.current_members(store, check["research_id"])
    if any(item["source_version_id"] not in members for item in frozen
           if item["excluded_reason"] != "removed_after_cutoff"):  # one already gone at the freeze stays out
        return "source_removed"
    for item in frozen:
        if item["plan_json"]:
            plan = json.loads(item["plan_json"])
            pool = passage_pool(store, plan["source_version_id"], plan["route"], plan["asset_id"])
            if citation_check.text_fingerprint(pool) != plan["fingerprint"]:
                return "source_changed"
        elif item["status"] == "no_text" and item["route"]:
            # A listed work that had nothing to read and now has text on its route (a new file, a new extraction).
            asset = _asset_in_use(store, item["source_version_id"]) if item["route"] == "fulltext" else None
            if passage_pool(store, item["source_version_id"], item["route"], asset):
                return "source_changed"
    snapshot = json.loads(check["attachment_snapshot_json"] or "null") or {}
    for entry in snapshot.get("assets", []):
        asset = store.conn.execute("SELECT id, extraction_version FROM source_assets WHERE source_version_id = ?"
                                   " AND removed_at IS NULL", (entry["source_version_id"],)).fetchone()
        if (asset is None or asset["id"] != entry["asset_id"] or asset["extraction_version"] != entry["extraction_version"]
                or _asset_text_sha256(store, asset["id"], asset["extraction_version"]) != entry["text_sha256"]):
            return "source_changed"
    return None


def refresh_currency(store: Store, check: dict[str, Any]) -> dict[str, Any]:
    """Mark the revision `stale` with its reason when it no longer stands (`stale_reason`); a stale one stays stale."""
    if check["currency"] == "current" and (reason := stale_reason(store, check)) is not None:
        with transaction(store.conn):
            store.conn.execute("UPDATE statement_checks SET currency = 'stale', stale_reason = ? WHERE id = ?"
                               " AND currency = 'current'", (reason, check["id"]))
        return check_row(store, check["id"])
    return check


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
    if waiting(check):
        # An attached file still being read pauses the run before anything is frozen; its resume looks again.
        if pending := _extracting(store, check["research_id"]):
            flow._pause(run_id, EXTRACTING, {"source_version_ids": pending})
        _freeze_attached(store, check["id"])
        run, check = store.run(run_id), check_row(store, check["id"])
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
        check = refresh_currency(store, check)  # a stale revision's result is stored, never shown as current
        _publish(store, run, check, item, output or {}, changed)
    flow._checkpoint(run_id)


# ---------------------------------------------------------------------------------------------- view and preview

def _run_brief(store: Store, run_id: str | None) -> dict[str, Any] | None:
    if not run_id:
        return None
    run = store.conn.execute("SELECT id, status, pause_reason FROM runs WHERE id = ?", (run_id,)).fetchone()
    return dict(run) if run else None


def latest_check_id(store: Store, research_id: str) -> str | None:
    """The revision with the highest number: the one a screen shows, whatever the currency of the others."""
    row = store.conn.execute("SELECT id FROM statement_checks WHERE research_id = ? ORDER BY revision DESC LIMIT 1",
                             (research_id,)).fetchone()
    return row["id"] if row else None


def _brief(store: Store, check: dict[str, Any], latest: str | None) -> dict[str, Any]:
    check = refresh_currency(store, check)
    return {"is_latest": check["id"] == latest, "id": check["id"], "research_id": check["research_id"], "revision": check["revision"],
            "request_id": check["request_id"], "sentence": check["sentence"], "scope_revision": check["scope_revision"],
            "discovery_run_id": check["discovery_run_id"], "cutoff_step_id": check["cutoff_step_id"],
            "attachment_snapshot": json.loads(check["attachment_snapshot_json"] or "null"),
            "effort": check["effort"], "work_cap": check["work_cap"], "model": json.loads(check["model_json"]),
            "currency": check["currency"], "stale_reason": check["stale_reason"], "status": check["status"],
            "run": _run_brief(store, check["run_id"]), "created_at": check["created_at"]}


def list_checks(store: Store, research_id: str) -> dict[str, Any]:
    """Every revision of the research's check, newest first, each with its currency as it stands now, and the latest
    revision's id (the highest number; a screen picks by it, never by the first current row)."""
    latest = latest_check_id(store, research_id)
    return {"latest_check_id": latest, "checks": [_brief(store, dict(row), latest) for row in store.conn.execute(
        "SELECT * FROM statement_checks WHERE research_id = ? ORDER BY revision DESC", (research_id,))]}


def view(store: Store, check_id: str) -> dict[str, Any]:
    """One revision: its currency read now (a stale one says so and why; its results are never current), its
    counters and its items in list order, with titles from the stored records."""
    check = check_row(store, check_id)
    latest = latest_check_id(store, check["research_id"])
    brief = _brief(store, check, latest) | {"latest_check_id": latest}
    items = []
    for item in items_of(store, check_id):
        source = store.source(item["source_version_id"])
        plan = json.loads(item["plan_json"]) if item["plan_json"] else {}
        output = json.loads(item["output_json"]) if item["output_json"] else None
        anchors = json.loads(item["located_anchors_json"] or "null")
        items.append({
            # The model's parts as stored, each with the backend's own located words (V3's `check_view` shape), and
            # the frozen plan's passage counts: the screen labels parts as the model's and marks only located words.
            "parts": None if output is None else [
                {"text": part["text"], "assessment": part["assessment"], "evidence": located}
                for part, located in zip(output["parts"], anchors or [[] for _ in output["parts"]])],
            "passages_given": len(plan["passage_ids"]) if plan else None, "passages_total": plan.get("passages_total"),
            "passages_not_given": plan.get("passages_not_given"), "passages_cut": plan.get("passages_cut"),
            "extraction_complete": None if item["extraction_complete"] is None else bool(item["extraction_complete"]),
            "id": item["id"], "ordinal": item["ordinal"], "work_id": item["work_id"],
            "source_version_id": item["source_version_id"], "title": source.get("title"), "year": source.get("year"),
            "doi": source.get("doi"), "text_version": item["text_version"], "route": item["route"],
            "entry": item["entry"], "eligibility": item["eligibility"], "excluded_reason": item["excluded_reason"],
            "status": item["status"], "result": item["result"], "depth": item["depth"],
            "error": json.loads(item["error_json"] or "null"),
            "located_anchors": json.loads(item["located_anchors_json"] or "null"),
            "located_passage_kinds": json.loads(item["located_passage_kinds_json"] or "null"),
            "step_input_id": item["step_input_id"], "checked_at": item["checked_at"]})
    return brief | {"counters": counters(store, check_row(store, check_id)), "items": items}


def preview(store: Store, check_id: str) -> dict[str, Any]:
    """What the revision's run sends, on the model stored with it at the request (Settings changed later do not
    count): the listed, out-of-cap and excluded works, the cap and the cost range of one call and one repair per
    planned work, the way Verify Citations prices its pairs (`citation_check.cost_range`). An attached-scope revision
    whose list is not frozen yet is frozen here once no attached file is still being extracted, so the preview prices
    the list the run checks; while one is, its estimate is pending, with no number."""
    check = check_row(store, check_id)
    if waiting(check) and not _extracting(store, check["research_id"]):
        _freeze_attached(store, check_id)
        check = check_row(store, check_id)
    items = items_of(store, check_id)
    planned = [item for item in items if item["plan_json"]]
    model = json.loads(check["model_json"])
    return {"id": check_id, "revision": check["revision"], "work_cap": check["work_cap"], "waiting": waiting(check),
            "listed": sum(item["eligibility"] == "listed" for item in items),
            "planned": sum(item["status"] == "planned" for item in items),
            "out_of_cap": sum(item["eligibility"] == "out_of_cap" for item in items),
            "no_text": sum(item["status"] == "no_text" for item in items),
            "excluded": sum(item["eligibility"] in ("excluded_reason", "person_excluded") for item in items),
            "passages_per_item": PASSAGES_PER_ITEM, "sentence_chars": len(check["sentence"]), "model": model,
            "cost": {"pairs": None, "connection": model["connection"], "model": model["model"],
                     "reasoning_effort": model.get("reasoning_effort"), "kind": None, "applies": None, "calls": None,
                     "usd": "unknown", "reason": "attachments_extracting"} if waiting(check) else
            citation_check.cost_range([(json.loads(item["plan_json"]), check["sentence"]) for item in planned], model)}


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
    check = refresh_currency(store, check_row(store, check_id))
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
