"""D253: cutoff-owned evidence, breadth-first answers and separate assessments."""

from __future__ import annotations

import json
from collections import Counter
from typing import Any

from deixis.domain.reason_codes import reason as reason_code
from deixis.domain.rules import TEST_EFFORT_BUDGETS
from deixis.workflow.search import english_question, small_batch
from deixis.workflow.run import fast_path
from deixis.workflow.answer import formula_passages, result_passages, criterion_passages
from deixis.workflow.read import fulltext
from deixis.workflow.screen.decisions import DecisionStore
from deixis.workflow.run.flow import MAX_PASSAGES_PER_SOURCE, fuse_rankings

CUTOFF = "fast_path:v1:cutoff"
INPUT = "fast_path:v1:answer_input"
VERSION_FIELDS = ("work_id", "title", "abstract", "doi", "version_label", "year")
# A screened work whose abstract stage left it to its full text, and no reading of that text by the cutoff (D60).
UNRESOLVED_WITHOUT_FULLTEXT = "unresolved_without_fulltext"
# A work a code rule set aside from screening (the survey-title rule, `seed_pool`): decided, not unscreened (D69).
CODE_DECIDED = "code_decided"
# One review call plus one bounded schema repair.
ANSWER_REVIEW_MODEL_CALLS = 2
# A work whose file a reading read and that did not meet the whole criterion is still the nearest evidence a question
# like "has this been done?" has (D137): the answer reads it as a `closest` work, never as an included one. A person's
# own decision, an unread or unconfirmed file and versions that disagree are not readings it may stand on.
CLOSEST_CODES = frozenset({"criterion_absent", "part_without_evidence", "fulltext_runs_agree_unresolved",
                           "fulltext_runs_disagree", "include_quote_unverified", "comparator_exclusion_withheld",
                           "protocol_title", "abstract_promise_absent"})
# How many closest works an answer reads, by its passage budget (quick 16, standard 48, detailed 80), and how many of
# each one's pages. Included works keep MAX_PASSAGES_PER_SOURCE; an abstract-only work gives its abstract.
CLOSEST_WORKS = {16: 3, 48: 5, 80: 8}
CLOSEST_PAGES = 4
ROLES = ("included", "closest", "abstract")


def human_choice(human: dict[str, Any]) -> dict[str, Any]:
    # A wrong file says nothing against the screened abstract of its version.
    state = ("pdf_wrong" if human["reason_code"] == "human_pdf_wrong" else
             {"include": "included", "candidate": "included", "out_of_scope": "excluded",
              "criterion_not_met": "excluded"}.get(human["outcome"], "pending"))
    return {"state": state, "user_reason": human["note"]}


def user_choices(store: Any, rid: str) -> tuple[dict[str, Any], dict[str, Any]]:
    selections = {r["source_version_id"]: dict(r) for r in store.conn.execute(
        "SELECT * FROM selections WHERE research_id = ? AND origin = 'user'"
        " AND state IN ('included', 'excluded')", (rid,))}
    humans = {}
    for row in store.conn.execute(
            "SELECT d.*, v.work_id FROM stage_decisions d JOIN source_versions v ON v.id = d.source_version_id"
            " WHERE d.research_id = ? AND d.decided_by = 'human' AND d.superseded_at IS NULL"
            " ORDER BY d.created_at, d.rowid", (rid,)):
        humans[row["work_id"]] = human_choice(dict(row))
    return selections, humans


def formula_request(store: Any, scope: dict[str, Any], patterns: list[tuple[str, Any]] | None) -> dict[str, Any]:
    """Whether full-text sources bring their most formula-dense passage forward, and why (D56)."""
    if english_question.is_english(scope["question"], scope.get("language_hint")):
        question = scope["question"]
    else:
        question = (store.english_question(scope["research_id"], scope["revision"]) or {}).get("text")
    on = formula_passages.asks_for_formulas([question or "", *(phrase for phrase, _ in patterns or [])])
    reason = "asked" if on else "no_english_question" if question is None else "not_asked"
    return {"on": on, "reason": reason, **formula_passages.THRESHOLDS}


def result_request(store: Any, scope: dict[str, Any]) -> dict[str, Any]:
    """The research's outcome terms that put a full-text source's most result-dense passage first (D84)."""
    vocabulary = (store.latest_step_output(scope["research_id"], "vocabulary", scope["revision"]) or {}).get("vocabulary") or {}
    terms = [phrase for phrase, _ in result_passages.compile_terms(vocabulary.get("outcome_terms") or [])]
    return {"on": bool(terms), "outcome_terms": terms, **result_passages.THRESHOLDS}


def current_members(store: Any, rid: str) -> dict[str, dict[str, Any]]:
    """Source versions currently in the research's corpus, by ID."""
    return {r["id"]: dict(r) for r in store.conn.execute(
        "SELECT v.* FROM source_versions v JOIN corpus_memberships m ON m.source_version_id = v.id"
        " WHERE m.research_id = ? AND m.removed_at IS NULL", (rid,))}


def current_pools(store: Any, rid: str) -> dict[str, list[dict[str, Any]]]:
    pools: dict[str, list[dict[str, Any]]] = {}
    for row in store.conn.execute(
            "SELECT p.id, p.source_version_id, p.kind, p.asset_id FROM passages p"
            " JOIN corpus_memberships m ON m.source_version_id = p.source_version_id"
            " WHERE m.research_id = ? AND m.removed_at IS NULL AND (p.asset_id IS NULL OR EXISTS"
            " (SELECT 1 FROM source_assets a WHERE a.id = p.asset_id AND a.removed_at IS NULL"
            " AND a.extraction_version IS p.extraction_version)) ORDER BY p.kind, p.physical_page, p.rowid", (rid,)):
        pools.setdefault(row["source_version_id"], []).append(dict(row))
    return pools


def answer_run_budget(store: Any, rid: str, scope: dict[str, Any], *, discovery_id: str | None = None) -> dict[str, Any]:
    budget = TEST_EFFORT_BUDGETS[scope["effort"]].__dict__
    if discovery_id is None:
        budget = small_batch.answer_budget(store, rid, scope["revision"], budget)
    else:
        discovery = store.run(discovery_id)
        if (discovery["research_id"], discovery["scope_revision"], discovery["status"]) != (rid, scope["revision"], "completed"):
            raise ValueError(f"answer_discovery_mismatch: run {discovery_id} is not a completed discovery of this "
                             f"research's scope revision {scope['revision']}")
        listing = store.existing_step(discovery_id, small_batch.LIST_KEY)
        binding = {"policy": small_batch.POLICY, "list_run_id": discovery_id,
                   "answer_allocation_version": small_batch.ANSWER_ALLOCATION_VERSION}
        binding |= ({"manifest_hash": listing["output"]["manifest_hash"]} if listing and listing["status"] == "succeeded"
                    else {"binding_error": "answer_frozen_list_missing"})
        budget = budget | {"inspection": binding}
    return fast_path.answer_budget(store, rid, scope["revision"], budget)


def reading_records(store: Any, rid: str) -> dict[str, Any]:
    steps, paired, plans, inputs, assets, history = {}, {}, {}, {}, {}, {}
    for row in store.conn.execute(
            "SELECT s.* FROM run_steps s JOIN runs r ON r.id = s.run_id WHERE r.research_id = ?"
            " AND s.kind IN ('model:fulltext_adjudication', 'code:adjudication_plan')", (rid,)):
        step = dict(row)
        steps[step["id"]] = step
        paired[(step["run_id"], step["operation_key"])] = step
        if step["kind"] == "code:adjudication_plan" and step["status"] == "succeeded":
            for item in json.loads(step["output_json"]).get("works", []):
                plans.setdefault((step["run_id"], item["read_version"]), []).append(item)
    for row in store.conn.execute(
            "SELECT i.step_id, i.payload_json FROM step_inputs i JOIN run_steps s ON s.id = i.step_id"
            " JOIN runs r ON r.id = s.run_id WHERE r.research_id = ? AND s.kind = 'model:fulltext_adjudication'"
            " ORDER BY i.attempt, i.rowid", (rid,)):
        inputs[row["step_id"]] = row["payload_json"]
    for row in store.conn.execute(
            "SELECT p.id, p.asset_id FROM passages p JOIN corpus_memberships m ON m.source_version_id = p.source_version_id"
            " WHERE m.research_id = ? AND m.removed_at IS NULL", (rid,)):
        assets[row["id"]] = row["asset_id"]
    for row in store.conn.execute(
            "SELECT * FROM stage_decisions WHERE research_id = ? AND stage = 'fulltext'"
            " ORDER BY created_at, rowid", (rid,)):
        history.setdefault(row["source_version_id"], []).append(dict(row))
    return {"steps": steps, "paired": paired, "plans": plans, "inputs": inputs,
            "assets": assets, "history": history}


def read_file(flow: Any, decision: dict[str, Any] | None, svid: str, records: dict[str, Any]) -> str | None:
    """A successful reading's own frozen plan must name the file still in use."""
    if not decision or not decision.get("step_id"):
        return None
    step = records["steps"].get(decision["step_id"])
    if not step or step["kind"] != "model:fulltext_adjudication" or step["status"] != "succeeded":
        return None
    prefix = step["operation_key"].rsplit(":", 1)[0]
    inspected_assets = set()
    for number in (1, 2):
        paired = records["paired"].get((step["run_id"], f"{prefix}:{number}"))
        if not paired or paired["status"] != "succeeded":
            return None
        sent = records["inputs"].get(paired["id"])
        if not sent:
            return None
        pages = json.loads(sent)["passages"]
        if not pages or any(p["source_id"] != svid for p in pages):
            return None
        if any(p["passage_id"] not in records["assets"] for p in pages):
            return None
        inspected_assets.update(records["assets"][p["passage_id"]] for p in pages)
    for item in records["plans"].get((step["run_id"], svid), []):
        if (item.get("asset_id") and inspected_assets == {item["asset_id"]} and flow._file_holds(item)):
            return item["asset_id"]
    return None


def version_text(flow: Any, decisions: Any, facts: dict[str, Any], readings: dict[str, Any],
                 pools: dict[str, list[dict[str, Any]]], wid: str, svid: str) -> dict[str, Any]:
    """What one version of a work can give an answer: its first abstract passage, and the pages of the file a current
    reading read (`read_file`), with the decisions they stand on. Without a flow no reading can be checked against the
    file in use, so no page is given."""
    fresh = [d for d in facts["decisions"].get(wid, []) if not decisions.is_stale(d, facts["stale_key"])]
    full = next((d for d in reversed(fresh) if d["stage"] == "fulltext"
                 and d["source_version_id"] == svid), None)
    inspected = full
    asset = read_file(flow, inspected, svid, readings) if flow is not None else None
    if flow is not None and not asset and full and full["decided_by"] == "human":
        for previous in reversed(readings["history"].get(svid, [])):
            if previous["stage"] == "fulltext" and not decisions.is_stale(previous, facts["stale_key"]):
                asset = read_file(flow, previous, svid, readings)
                if asset:
                    inspected = previous
                    break
    # Only a screened version supplies its abstract. Another version is not corroboration.
    abstract = next((d for d in reversed(fresh) if d["stage"] == "abstract"
                     and d["source_version_id"] == svid and d["outcome"] == "candidate"), None)
    passages = pools.get(svid, [])
    return {"fresh": fresh, "full": full, "inspected": inspected, "asset": asset, "abstract": abstract,
            "abstract_ids": [p["id"] for p in passages if p["kind"] == "abstract"][:1],
            "fulltext_ids": [p["id"] for p in passages if p["kind"] == "pdf_page" and p["asset_id"] == asset] if asset else []}


def abstract_sibling(store: Any, rid: str, decisions: Any, facts: dict[str, Any], pools: dict[str, list[dict[str, Any]]],
                     wid: str, head: str, svid: str) -> tuple[str, dict[str, Any]] | None:
    """Another version of the work whose own screened abstract can stand in for `svid`, the answer version, which
    holds a PDF nobody has read and so no abstract decision of its own (D112). The abstract is still that version's
    own: it is never mixed with the PDF's pages."""
    for other in [head, *store.work_versions(rid, head)]:
        if other == svid:
            continue
        text = version_text(None, decisions, facts, {}, pools, wid, other)
        if text["abstract"] is not None and text["abstract_ids"]:
            return other, text
    return None


def is_closest(full: dict[str, Any] | None, asset: str | None) -> bool:
    """A model reading of the file in use that did not include the work (D137): a `closest` work for the answer."""
    return bool(asset and full and full["decided_by"] != "human" and full["reason_code"] in CLOSEST_CODES)


def role_of(row: dict[str, Any]) -> str:
    """A row's answer role; a row frozen before D137 has none, and its route says what it was."""
    return row.get("answer_role") or ("included" if row["route"] == "fulltext" else "abstract")


def text_row(store: Any, item: dict[str, Any], svid: str, text: dict[str, Any], route: str,
             reason: str | None) -> dict[str, Any]:
    """An answer input row for one work read from `svid`, before the person's choice is applied (`apply_user`)."""
    full, abstract, asset = text["full"], text["abstract"], text["asset"]
    source = store.source(svid)
    return {"work_id": item["work_id"], "head": item["head"], "position": item["position"], "source_version_id": svid,
            "route": route, "decision_id": (full if route == "fulltext" else abstract or {}).get("id"),
            "abstract_decision_id": (abstract or {}).get("id"),
            "fulltext_decision_id": text["inspected"]["id"] if asset else None,
            "asset_id": asset, "abstract_ids": text["abstract_ids"], "fulltext_ids": text["fulltext_ids"],
            "reason": reason, "base_reason": reason, "base_route": route,
            "file_unverified": bool(full and not asset),
            "version": {k: source.get(k) for k in VERSION_FIELDS}}


def cutoff_snapshot(flow: Any, run: dict[str, Any], listing: dict[str, Any], closure: dict[str, Any]) -> dict[str, Any]:
    store, rid = flow.store, run["research_id"]
    decisions = DecisionStore(store)
    facts = decisions.facts(rid)
    versions = store.answer_versions(rid)
    selections, humans = user_choices(store, rid)
    pools = current_pools(store, rid)
    readings = reading_records(store, rid)
    unread = set(closure["not_screened_at_cutoff"])
    items = list(listing["items"])
    present = {item["work_id"] for item in items[:run["budget"]["fast_path"]["N"]]}
    listed = {item["work_id"] for item in items}
    items += [{"work_id": wid, "head": head, "position": None, "user_priority": False}
              for wid, head in facts["heads"].items() if wid not in listed]
    rows, excluded = [], Counter()
    for item in items:
        wid, head = item["work_id"], item["head"]
        user = selections.get(head) or humans.get(wid)
        outcome = decisions.work_outcome(rid, wid, facts)
        svid = versions.get(head) or head
        text = version_text(flow, decisions, facts, readings, pools, wid, svid)
        # The PDF's version was never abstract-screened and its reading did not happen: the work would drop out as
        # unscreened although another version of it was screened a candidate (D112).
        sibling = (abstract_sibling(store, rid, decisions, facts, pools, wid, head, svid)
                   if not text["asset"] and text["abstract"] is None else None)
        pdf_version = svid if sibling else None
        if sibling:
            svid, text = sibling
        fresh, full, asset, abstract = text["fresh"], text["full"], text["asset"], text["abstract"]
        closest = is_closest(full, asset)
        route = "fulltext" if asset and (full["outcome"] == "include" or closest) else "abstract"
        # A PDF the person attached and the model read stays in the answer whatever the new ranking says.
        uploaded = bool(asset) and store.conn.execute(
            "SELECT 1 FROM source_assets WHERE id = ? AND origin = 'user_upload'", (asset,)).fetchone() is not None
        reason = None
        if wid not in present and not uploaded:
            reason = "outside_read_window"
        elif wid in unread:
            reason = "not_screened_at_cutoff"
        elif outcome.get("reason_code") == "versions_disagree":
            reason = "versions_disagree"
        elif outcome.get("outcome") in ("criterion_not_met", "out_of_scope") and not closest:
            reason = outcome["outcome"]
        elif route == "abstract" and abstract is None:
            # A work the abstract stage screened and routed to its full text (`abstract_not_found`,
            # `runs_agree_unresolved`) whose text was not read by the cutoff is not an unscreened work: it waits for
            # its full text, which the late read may still bring (D60).
            routed = any(d["stage"] == "abstract" and d["source_version_id"] == svid and d["outcome"] == "unresolved"
                         and reason_code(d["reason_code"]).next_step == "fulltext_fetch" for d in fresh)
            unread_text = not full or full["reason_code"] in fulltext.OWNED_CODES
            set_aside = any(d["stage"] == "abstract" and d["source_version_id"] == svid
                            and reason_code(d["reason_code"]).next_step == "seed_pool" for d in fresh)
            reason = (UNRESOLVED_WITHOUT_FULLTEXT if routed and unread_text else
                      CODE_DECIDED if set_aside else "not_screened_at_cutoff")
        row = text_row(store, item, svid, text, route, reason)
        row["answer_role"] = row["base_role"] = "closest" if closest else "included" if route == "fulltext" else "abstract"
        if pdf_version:
            row["abstract_of_unread_pdf_version"] = pdf_version
        apply_user(row, user)
        if not row["reason"] and not (row["fulltext_ids"] if row["route"] == "fulltext" else row["abstract_ids"]):
            row["reason"] = "no_text_at_cutoff"
        if row["reason"]:
            excluded[row["reason"]] += 1
        rows.append(row)
    # The works this read asks the person about, at most two, frozen once per scope revision (D137).
    from deixis.workflow.screen import queue as human_queue
    asked = human_queue.frozen_asked(store, rid, run["scope_revision"])
    return {
        "asked": asked if asked is not None else human_queue.first_asked(store, rid),
        "cutoff_at": closure["read_cutoff_at"], "scope_revision": run["scope_revision"],
        "criterion_hash": facts["stale_key"][1], "selection_revision": store.selection_revision(rid),
        "user_signature": small_batch.user_signature(store, rid), "manifest_hash": listing["manifest_hash"],
        "items": rows, "excluded_reasons": dict(excluded)}


def freeze_cutoff(flow: Any, run: dict[str, Any], listing: dict[str, Any], closure: dict[str, Any],
                  *, snapshot: dict[str, Any] | None = None) -> dict[str, Any]:
    frozen = snapshot if snapshot is not None else cutoff_snapshot(flow, run, listing, closure)
    return small_batch.save_code(flow, run, CUTOFF, "code:fast_path_cutoff", lambda: frozen)


def apply_user(row: dict[str, Any], user: dict[str, Any] | None) -> None:
    row["reason"], row["route"] = row["base_reason"], row["base_route"]
    if "base_role" in row:
        row["answer_role"] = row["base_role"]
    row["user_priority"] = bool(user and user["state"] == "included")
    row["override_reason"] = user.get("user_reason") if user else None
    if not user:
        return
    if user["state"] == "excluded":
        row["reason"] = "user_excluded"
    elif user["state"] == "pending":
        row["reason"] = "user_pending"
    elif user["state"] == "pdf_wrong":
        row["route"] = "abstract"
        if "base_role" in row:
            row["answer_role"] = "abstract"
        if row["base_route"] == "fulltext":
            row["reason"] = (row["base_reason"] if row.get("abstract_decision_id")
                             else "not_screened_at_cutoff")
    elif user["state"] == "included":
        row["route"] = "fulltext" if row["fulltext_ids"] else "abstract"
        if "base_role" in row:
            row["answer_role"] = "included"
        row["reason"] = None if row["fulltext_ids"] or row["abstract_ids"] else "user_included_no_text"
    if row["route"] == "abstract" and row["base_route"] == "fulltext":
        row["decision_id"] = row.get("abstract_decision_id")


def included_heads(store: Any, rid: str) -> dict[str, str]:
    """Each work whose current head carries the person's own selection `included`, by work: only that selection row
    counts. Another state of it, a choice on another version or a queue decision alone adds nothing."""
    selections, _ = user_choices(store, rid)
    return {wid: head for wid, head in store.work_heads(rid).items()
            if (selections.get(head) or {}).get("state") == "included"}


def after_cutoff_rows(store: Any, flow: Any, rid: str,
                      works: dict[str, str]) -> tuple[list[dict[str, Any]], list[dict[str, Any]]]:
    """Answer input rows for works the person included that the read cutoff holds no row for (a work a follow-up
    search found, or one added by hand): one row per work, read from the head's answer version (D48), its full text
    when a current reading read the file in use, else its abstract, then the person's choice. A work with no text
    version gives no row and is listed as `no_text_version`. Without a flow no page is given (`version_text`)."""
    decisions = DecisionStore(store)
    facts = decisions.facts(rid)
    selections, _ = user_choices(store, rid)
    pools = current_pools(store, rid)
    readings = reading_records(store, rid)
    rows, missing = [], []
    for wid, head in works.items():
        svid = store.answer_version(rid, head)
        if svid is None:
            missing.append({"work_id": wid, "source_version_id": head, "reason": "no_text_version"})
            continue
        text = version_text(flow, decisions, facts, readings, pools, wid, svid)
        row = text_row(store, {"work_id": wid, "head": head, "position": None}, svid, text,
                       "fulltext" if text["asset"] else "abstract", None)
        row["answer_role"] = row["base_role"] = "included" if text["asset"] else "abstract"
        apply_user(row, selections.get(head))
        rows.append(row | {"added_after_cutoff": True, "head_after_cutoff": head})
    return rows, missing


def input_plan(flow: Any, run: dict[str, Any], scope: dict[str, Any]) -> dict[str, Any]:
    store, rid = flow.store, run["research_id"]
    saved = store.existing_step(run["id"], INPUT)
    if saved and saved["status"] == "succeeded":
        return saved["output"]
    cutoff = store.existing_step(run["budget"]["inspection"]["list_run_id"], CUTOFF)
    if not cutoff or cutoff["status"] != "succeeded":
        flow._fail(run["id"], "answer_cutoff_missing")
    frozen = cutoff["output"]
    rows = json.loads(json.dumps(frozen["items"]))
    selections, humans = user_choices(store, rid)
    changed = frozen["user_signature"] != small_batch.user_signature(store, rid)
    if changed:
        for row in rows:
            apply_user(row, selections.get(row["head"]) or humans.get(row["work_id"]))
    # UI parity S20: an answer the person starts (no `trigger`: not the automatic answer after a discovery, not a late
    # revision) also reads a work the read stage did not reach that a "Screen more" run (F13) has since made a
    # candidate from its abstract, unless the person or a later stage excluded it (`screen_more.answer_admissions`,
    # fail-closed). The work is matched, not the record: the version both runs read may not be the cutoff row's, so
    # the row is rebuilt for that version (its metadata, abstract and decision) and stays one row per work. It is
    # abstract-based evidence and is marked as such.
    if run["budget"].get("trigger") is None:
        from deixis.workflow.screen import screen_more
        later = screen_more.admissions_by_work(screen_more.answer_admissions(store, rid, run["scope_revision"]))
        for row in rows:
            found = later.get(row["work_id"])
            if found and row["route"] == "abstract" and row["reason"] in ("outside_read_window", "not_screened_at_cutoff", CODE_DECIDED):
                read = found["source_version_id"]
                if read != row["source_version_id"]:
                    source = store.source(read)
                    row.update(cutoff_source_version_id=row["source_version_id"], source_version_id=read,
                               version={k: source.get(k) for k in VERSION_FIELDS}, fulltext_ids=[], asset_id=None,
                               fulltext_decision_id=None, file_unverified=False)
                row.update(reason=None, decision_id=found["decision_id"], abstract_decision_id=found["decision_id"],
                           abstract_ids=found["abstract_ids"], screened_after_cutoff=found["run_id"],
                           evidence_basis="abstract_screening",
                           **({"head_after_cutoff": found["current_head"]} if found["current_head"] != row["head"] else {}))
        # A snowball round's candidate is a work the discovery never listed, so it has no cutoff row to update. It
        # joins the answer as abstract-based evidence only once the person included the work's head (plan
        # notes/plans/snowballing-plan.md): two model reads that agree propose it, the person decides.
        present = {row["work_id"] for row in rows}
        position = max((row["position"] for row in rows), default=0)
        for work_id, found in sorted(later.items()):
            screened_by = store.run(found["run_id"])
            # A round's own screening, or Screen more reading on from a round's list.
            if work_id in present or not (screened_by["kind"] == "snowball"
                                          or (screened_by["target"] or {}).get("source_run_id")):
                continue
            head = found["current_head"]
            user = selections.get(head)
            if not user or user["state"] != "included":
                continue
            read = found["source_version_id"]
            source = store.source(read)
            position += 1
            row = {"work_id": work_id, "head": head, "position": position, "source_version_id": read,
                   "route": "abstract", "decision_id": found["decision_id"], "abstract_decision_id": found["decision_id"],
                   "fulltext_decision_id": None, "asset_id": None, "abstract_ids": found["abstract_ids"],
                   "fulltext_ids": [], "reason": None, "base_reason": None, "base_route": "abstract",
                   "file_unverified": False, "version": {k: source.get(k) for k in VERSION_FIELDS},
                   "screened_after_cutoff": found["run_id"], "evidence_basis": "abstract_screening"}
            apply_user(row, user)
            rows.append(row)
    # A work the person included that the cutoff holds no row for (a follow-up search found it, or it was added by
    # hand) is read too, one row per work: the cutoff's works are matched by the work each of their records belongs to
    # now, so a record that has since merged into another work never gives that work a second row.
    no_text = []
    if run["budget"].get("trigger") is None and not run["budget"].get("late_revision_id"):
        held = {row["work_id"] for row in rows} | set(store.work_ids(
            list({svid for row in rows for svid in (row["head"], row["source_version_id"])})).values())
        works = {wid: head for wid, head in included_heads(store, rid).items() if wid not in held}
        if works:
            added, no_text = after_cutoff_rows(store, flow, rid, works)
            rows += added
    # Late full text that excluded a work (D255) outranks the abstract screening that admitted it at the cutoff.
    late_excluded = None
    if not run["budget"].get("late_revision_id"):
        from deixis.workflow.answer import late_revision
        late_excluded = late_revision.excluded_works(store, rid, run["scope_revision"])
        for row in rows:
            if row["work_id"] in late_excluded and not row["reason"] and not row["user_priority"]:
                row["reason"] = "fulltext_excluded_after_cutoff"
        # A late reading that did not include the work but read its file makes it a closest work, read from that file
        # (D137), instead of the abstract the cutoff admitted it on.
        if late_excluded is not None:
            late_closest = late_revision.closest_works(store, rid, run["scope_revision"])
            for row in rows:
                if row["work_id"] in late_closest and not row["reason"] and not row["user_priority"] \
                        and role_of(row) == "abstract":
                    found = late_closest[row["work_id"]]
                    # Any choice of the person (a wrong PDF above all) and a later decision on the work keep the row
                    # what it is: only the late reading itself, still current, reads the file.
                    current = store.conn.execute("SELECT 1 FROM stage_decisions WHERE id = ? AND superseded_at IS NULL",
                                                 (found["late_decision_id"],)).fetchone()
                    if (found["source_version_id"] != row["source_version_id"] or current is None
                            or selections.get(row["head"]) or humans.get(row["work_id"])):
                        continue
                    ids = [p["id"] for p in current_pools(store, rid).get(row["source_version_id"], [])
                           if p["kind"] == "pdf_page" and p["asset_id"] == found["late_asset_id"]]
                    if ids:
                        row.update(route="fulltext", answer_role="closest", asset_id=found["late_asset_id"],
                                   fulltext_ids=ids, fulltext_decision_id=found["late_decision_id"],
                                   decision_id=found["late_decision_id"], closest_after_cutoff=True)
    members = current_members(store, rid)
    pools = current_pools(store, rid)
    for row in rows:
        svid = row["source_version_id"]
        if svid not in members:
            row["reason"] = "removed_after_cutoff"
        elif any(members[svid].get(k) != v for k, v in row["version"].items()):
            # Keep source metadata and screened text bound to the same cutoff record.
            row["reason"] = "source_changed_after_cutoff"
        else:
            current = {p["id"] for p in pools.get(svid, [])}
            for key in ("abstract_ids", "fulltext_ids"):
                row[key] = [pid for pid in row[key] if pid in current]
            if row["route"] == "fulltext" and not row["fulltext_ids"]:
                row["route"] = "abstract"
                if "answer_role" in row:
                    row["answer_role"] = "abstract"
                row["decision_id"] = row.get("abstract_decision_id")
                if not row["decision_id"] and not row["user_priority"]:
                    row["abstract_ids"] = []
            if not row["reason"] and not (row["fulltext_ids"] if row["route"] == "fulltext" else row["abstract_ids"]):
                row["reason"] = "no_text_at_cutoff"
    # The closest works past the budget's count stay out, the nearest by the frozen list first (D137).
    cap = CLOSEST_WORKS.get(run["budget"]["max_answer_passages"], CLOSEST_WORKS[48])
    closest = [row for row in rows if not row["reason"] and role_of(row) == "closest"]
    for row in closest[cap:]:
        row["reason"] = "closest_over_cap"
    excluded = [{"work_id": r["work_id"], "source_version_id": r["source_version_id"], "reason": r["reason"]}
                for r in rows if r["reason"]] + no_text
    rows = [row for row in rows if not row["reason"]]
    rows.sort(key=lambda row: not row["user_priority"])
    patterns = flow._criterion_phrases(run, scope)
    fts = " OR ".join(f'"{term}"' for term in flow._topic_terms(rid, scope))
    formulas = formula_request(store, scope, patterns)
    results = result_request(store, scope)
    outcome_patterns = result_passages.compile_terms(results["outcome_terms"])
    moved = 0
    queues = []
    for row in rows:
        ids = row["fulltext_ids"] if row["route"] == "fulltext" else row["abstract_ids"]
        pages = [store.passage(pid) for pid in ids]
        if row["route"] == "fulltext" and role_of(row) == "closest":
            row["criterion_parts"], quoted = closest_parts(store, row)
            pages = closest_pages(store, row, pages, quoted, fts, patterns)
        elif row["route"] == "fulltext":
            topic = [p for p in store.search_passages([row["source_version_id"]], fts, len(ids)) if p["id"] in ids]
            criterion = criterion_passages.criterion_order(pages, patterns or [])
            ranked = fuse_rankings(topic, criterion) if criterion else topic
            pages = list({p["id"]: p for p in [*ranked, *pages]}.values())
            pages, first = result_passages.order(pages, outcome_patterns, formulas["on"])
            moved += first
            pages = pages[:MAX_PASSAGES_PER_SOURCE]
        queues.append(pages)
    limit = run["budget"]["max_answer_passages"]
    passages = allocate_by_role(rows, queues, limit)
    given = {p["id"] for p in passages}
    # A work the budget left without a page is not given to the model, and is listed with why (D137).
    for row in rows:
        if not given & set(row["abstract_ids"] + row["fulltext_ids"]):
            row["reason"] = "passage_budget"
            excluded.append({"work_id": row["work_id"], "source_version_id": row["source_version_id"],
                             "reason": "passage_budget"})
    rows = [row for row in rows if not row["reason"]]
    breadth = len(rows)
    return small_batch.save_code(flow, run, INPUT, "code:fast_path_answer_input", lambda: {
        "policy_hash": run["budget"]["fast_path"]["policy_hash"], "cutoff_step_id": cutoff["id"],
        "cutoff_at": frozen["cutoff_at"], "scope_revision": run["scope_revision"],
        "cutoff_selection_revision": frozen["selection_revision"], "selection_revision": store.selection_revision(rid),
        "user_signature": small_batch.user_signature(store, rid), "items": rows,
        "excluded": excluded, "excluded_reasons": dict(Counter(r["reason"] for r in excluded)),
        "passage_ids": [p["id"] for p in passages], "limit": limit, "breadth": breadth,
        "semantic_retrieval": "skipped: fast_path_lexical", "formula_passages": formulas,
        "result_passages": {**results, "moved": moved}})


PART_STATUS = {"present": "found", "disputed": "disputed", "absent": "not_found", "unclear": "unclear"}


def closest_parts(store: Any, row: dict[str, Any]) -> tuple[list[dict[str, str]], list[str]]:
    """What the reading behind a closest work found of each criterion part, and the passages its verified quotes stand
    on (D137). The two calls are merged as the queue merges them (`adjudication.merge_parts`): a part one call quoted
    and the other, shown the same text, did not find is `disputed`. A status is a pointer for the answer model, never
    evidence; no rationale the reading model wrote is passed on."""
    from deixis.workflow.read import adjudication

    found = store.conn.execute("SELECT s.run_id, s.operation_key FROM stage_decisions d JOIN run_steps s ON s.id = d.step_id"
                               " WHERE d.id = ?", (row["fulltext_decision_id"],)).fetchone()
    if found is None:
        return [], []
    prefix = found["operation_key"].rsplit(":", 1)[0]
    rows_by_run: dict[int, dict[str, dict[str, Any]]] = {}
    shown: dict[int, dict[str, dict[str, Any]]] = {}
    for number in (1, 2):
        step = store.conn.execute("SELECT id FROM run_steps WHERE run_id = ? AND operation_key = ?",
                                  (found["run_id"], f"{prefix}:{number}")).fetchone()
        if step is None:
            continue
        rows_by_run[number] = {p["criterion_part"]: {
            "label": p["label"], "quote": p["quote"] or "", "quote_verified": bool(p["quote_verified"]),
            "passage_id": p["quote_passage_id"], "page": p["quote_page"]} for p in store.conn.execute(
                "SELECT * FROM model_proposals WHERE step_id = ? AND source_version_id = ? AND stage = 'fulltext'"
                " ORDER BY rowid", (step["id"], row["source_version_id"]))}
        sent = store.conn.execute("SELECT payload_json FROM step_inputs WHERE step_id = ? ORDER BY attempt DESC,"
                                  " rowid DESC LIMIT 1", (step["id"],)).fetchone()
        shown[number] = {p["passage_id"]: {"text": p.get("text") or "",
                                           "physical_page": (p.get("locator") or {}).get("physical_page")}
                         for p in (json.loads(sent[0]).get("passages") or [] if sent else [])}
    merged = adjudication.merge_parts(rows_by_run, shown)
    parts = [{"part": name, "status": "found_unverified" if m["label"] == "present" and not m["quote_verified"]
              else PART_STATUS[m["label"]]} for name, m in merged.items() if name]
    quoted = list(dict.fromkeys(r["passage_id"] for runs in rows_by_run.values() for r in runs.values()
                                if r["label"] == "present" and r["quote_verified"] and r["passage_id"]))
    return parts, quoted


def closest_pages(store: Any, row: dict[str, Any], pages: list[dict[str, Any]], quoted: list[str], fts: str,
                  patterns: list[Any]) -> list[dict[str, Any]]:
    """A closest work's pages for the answer (D137): its abstract, the pages its reading quoted, then the pages the
    research's topic and criterion rank first, at most CLOSEST_PAGES."""
    ids = row["fulltext_ids"]
    abstract = [store.passage(pid) for pid in row["abstract_ids"][:1]]
    cited = [store.passage(pid) for pid in quoted if pid in ids]
    topic = [p for p in store.search_passages([row["source_version_id"]], fts, len(ids)) if p["id"] in ids] if fts else []
    criterion = criterion_passages.criterion_order(pages, patterns or [])
    ranked = fuse_rankings(topic, criterion) if criterion else topic
    return list({p["id"]: p for p in [*abstract, *cited, *ranked, *pages]}.values())[:CLOSEST_PAGES]


def allocate_by_role(rows: list[dict[str, Any]], queues: list[list[dict[str, Any]]],
                     limit: int) -> list[dict[str, Any]]:
    """Fill the passage budget by role (D137), breadth first and in row order within each pass: the first page of every
    included and closest work, then the other pages of the closest works (up to CLOSEST_PAGES each), then one abstract
    per abstract-only work, then the deeper pages of the included works (up to MAX_PASSAGES_PER_SOURCE each). Without
    closest works this is the earlier breadth-first order; the budget is no longer widened to fit every work. A work
    the person included, or that a Screen more run the person started admitted, always gets its first page, even past
    the budget."""
    forced = [bool(row["user_priority"] or row.get("screened_after_cutoff")) for row in rows]
    selected = [queue[0] for queue, first in zip(queues, forced) if first and queue]
    entries = list(zip([role_of(row) for row in rows], queues, forced))
    passes = [(("included", "closest"), range(0, 1)), (("closest",), range(1, CLOSEST_PAGES)),
              (("abstract",), range(0, 1)), (("included",), range(1, MAX_PASSAGES_PER_SOURCE))]
    for roles, depths in passes:
        for depth in depths:
            for role, queue, first in entries:
                if role not in roles or depth >= len(queue) or depth == 0 and first:
                    continue
                if len(selected) >= limit:
                    return in_row_order(selected, queues)
                selected.append(queue[depth])
    return in_row_order(selected, queues)


def in_row_order(selected: list[dict[str, Any]], queues: list[list[dict[str, Any]]]) -> list[dict[str, Any]]:
    """The chosen passages as the model reads them: by work in row order, each work's in its own order."""
    place = {p["id"]: (i, depth) for i, queue in enumerate(queues) for depth, p in enumerate(queue)}
    return sorted(selected, key=lambda p: place[p["id"]])


def check_input(flow: Any, run_id: str, plan: dict[str, Any]) -> None:
    store = flow.store
    rid = store.run(run_id)["research_id"]
    members = current_members(store, rid)
    pools = current_pools(store, rid)
    selected = set(plan["passage_ids"])
    late = store.run(run_id)["budget"].get("late_revision_id")
    added = any(row.get("added_after_cutoff") for row in plan["items"])
    versions = store.answer_versions(rid) if late or added else {}
    heads = store.work_heads(rid) if late or added else {}
    for row in plan["items"]:
        svid = row["source_version_id"]
        if row.get("added_after_cutoff"):
            # A row the person's inclusion added after the cutoff is held, in every answer that reads it, to the head
            # it was added under, that head's answer version and, read in full, the file still in use.
            if (heads.get(row["work_id"]) != row["head_after_cutoff"] or versions.get(row["head_after_cutoff"]) != svid
                    or row["route"] == "fulltext" and flow._current_asset(svid) != row["asset_id"]):
                flow._pause(run_id, "source_changed")
        elif late and row.get("screened_after_cutoff"):
            # UI parity S20: a row admitted after the cutoff reads the version Screen more read, which need not be the
            # work's answer version; it is held to the head it was admitted under. Membership, metadata and passage
            # checks below still apply to the version it reads.
            if heads.get(row["work_id"]) != row.get("head_after_cutoff", row["head"]) or row["route"] != "abstract":
                flow._pause(run_id, "source_changed")
        elif late and (heads.get(row["work_id"]) != row["head"]
                       or (versions.get(row["head"], row["head"]) != svid and not row.get("abstract_of_unread_pdf_version"))
                       or row["route"] == "fulltext" and flow._current_asset(svid) != row["asset_id"]):
            flow._pause(run_id, "source_changed")
        if svid not in members or any(members[svid].get(k) != v for k, v in row["version"].items()):
            flow._pause(run_id, "source_changed")
        current = {p["id"] for p in pools.get(svid, [])}
        owned = set(row["abstract_ids"]) | set(row["fulltext_ids"])
        if (selected & owned) - current:
            flow._pause(run_id, "source_changed")


def added_after_cutoff_view(store: Any, answer_run_id: str | None) -> list[dict[str, Any]]:
    """The works an answer read because the person included them after the read cutoff, for the answer view to label
    "Included by you after the search"."""
    from deixis.workflow.answer.late_revision import REVISION_INPUT

    if answer_run_id is None:
        return []
    step = store.existing_step(answer_run_id, REVISION_INPUT) or store.existing_step(answer_run_id, INPUT)
    if step is None or step["status"] != "succeeded" or not step["output"]:
        return []
    return [{"work_id": row["work_id"], "source_version_id": row["source_version_id"],
             "head_after_cutoff": row["head_after_cutoff"], "route": row["route"]}
            for row in step["output"].get("items", []) if row.get("added_after_cutoff")]


def roles_view(store: Any, answer_run_id: str | None) -> dict[str, Any] | None:
    """What each work the answer was given stood as (D137), read from the frozen plan of its run and never recomputed:
    the role per work, the work counts per role, what the plan left out for the budget, and the criterion parts of each
    closest work. A plan frozen before D137 has no roles, and `role_of` reads its routes."""
    from deixis.workflow.answer.late_revision import REVISION_INPUT

    if answer_run_id is None:
        return None
    step = store.existing_step(answer_run_id, REVISION_INPUT) or store.existing_step(answer_run_id, INPUT)
    if step is None or step["status"] != "succeeded" or not step["output"]:
        return None
    items = step["output"].get("items", [])
    works = {row["work_id"]: role_of(row) for row in items}
    sources = {row["source_version_id"]: role_of(row) for row in items}
    left = step["output"].get("excluded_reasons") or {}
    return {"works": works, "sources": sources, "counts": {role: sum(r == role for r in works.values()) for role in ROLES},
            "left_out": {k: left[k] for k in ("passage_budget", "closest_over_cap") if left.get(k)},
            "closest_parts": {row["work_id"]: row["criterion_parts"] for row in items
                              if role_of(row) == "closest" and row.get("criterion_parts")}}


async def answer(flow: Any, run: dict[str, Any], scope: dict[str, Any]) -> None:
    if run["budget"].get("late_revision_id"):
        from deixis.workflow.answer import late_revision
        late = late_revision.row_for_run(flow.store, run)
        if late and late["status"] in ("published", "failed") and flow.store.conn.execute(
                "SELECT 1 FROM answers WHERE run_id = ?", (run["id"],)).fetchone():
            # Publication survived a crash before run completion; finish and enqueue its review without regenerating.
            return
        plan = late_revision.revision_plan(flow, run, scope)
    else:
        plan = input_plan(flow, run, scope)
    # Where the flow stood as this answer started (slice 20), apart from what the plan gives the model. No await since
    # the included set and selection revision were read, so the snapshot is the state they describe.
    rid = run["research_id"]
    flow._answer_start_snapshot(run, flow.store.included_works(rid), flow.store.selection_revision(rid))
    # A person's selection change no longer stops a first answer (D126): it is written from the plan's selection and
    # published as out of date, and `after_answer` starts the next one. A late revision keeps its own stop rule.
    flow._small_batch_guard = {"run_id": run["id"], "rid": run["research_id"], "fast_answer": True, "input": plan}
    if run["budget"].get("late_revision_id"):
        flow._small_batch_guard |= {"late_revision": True, "user_signature": plan["user_signature"]}
    try:
        flow._checkpoint(run["id"], run["scope_revision"])
        flow.store.update_run(run["id"], stage="answer")
        if not plan["passage_ids"]:
            flow.store.save_answer(run["research_id"], run["id"], None, None, run["scope_revision"],
                "no_evidence", None, {"ok": True, "issues": [], "reason": "no_evidence_at_cutoff"},
                selection_revision=plan["selection_revision"])
            return
        await flow._generate_answer(run, scope, [flow.store.passage(pid) for pid in plan["passage_ids"]],
                                    plan["selection_revision"])
    finally:
        flow._small_batch_guard = None


def auto_answer(store: Any, run: dict[str, Any]) -> None:
    if not run["budget"]["fast_path"].get("auto_answer"):
        return
    ledger = store.conn.execute("SELECT * FROM fast_path_ledgers WHERE ledger_run_id = ?", (run["id"],)).fetchone()
    reason = "scope_revised" if store.research(run["research_id"])["current_scope_revision"] != run["scope_revision"] else None
    if ledger["answer_run_id"]:
        reason = "answer_already_started"
    if store.conn.execute("SELECT 1 FROM runs WHERE research_id = ? AND kind = 'answer'"
                          " AND status IN ('queued', 'running', 'pause_requested')", (run["research_id"],)).fetchone():
        reason = "answer_already_active"
    if reason:
        store._event(run["research_id"], "auto_answer_skipped", {"reason": reason}, run["id"])
        return
    scope = store.scope(run["research_id"], run["scope_revision"])
    budget = answer_run_budget(store, run["research_id"], scope, discovery_id=run["id"]) | {"trigger": "auto_after_discovery"}
    store.create_run(run["research_id"], "answer", budget, f"fast_path:auto_answer:{run['id']}")


def rerun_for_selection(store: Any, run: dict[str, Any]) -> bool:
    """D126: when the person changed the selection while an answer was written, queue one answer from the current
    selection. The finished answer stays, marked out of date by its selection revision, and is not reviewed; each
    rerun needs a new change by the person, so the chain ends once the selection holds still."""
    from deixis.workflow.run.store import ACTIVE_RUN_STATUSES

    rid = run["research_id"]
    plan = store.existing_step(run["id"], INPUT)
    if (run["budget"].get("late_revision_id") or plan is None or plan["status"] != "succeeded"
            or plan["output"]["user_signature"] == small_batch.user_signature(store, rid)
            or store.research(rid)["current_scope_revision"] != run["scope_revision"]
            or store.conn.execute(f"SELECT 1 FROM runs WHERE research_id = ? AND id != ? AND status IN"
                                  f" ({','.join('?' * len(ACTIVE_RUN_STATUSES))})",
                                  (rid, run["id"], *ACTIVE_RUN_STATUSES)).fetchone()):
        return False
    scope = store.scope(rid, run["scope_revision"])
    store.create_run(rid, "answer", answer_run_budget(store, rid, scope) | {"rerun_of": run["id"]},
                     f"answer:selection_rerun:{run['id']}")
    return True


def after_answer(flow: Any, run: dict[str, Any]) -> None:
    store = flow.store
    from deixis.workflow.answer import late_revision
    if rerun_for_selection(store, run):
        return
    late_revision.schedule(flow, run)
    row = store.conn.execute("SELECT id FROM answers WHERE run_id = ? AND status = 'structurally_valid'", (run["id"],)).fetchone()
    if not row:
        return
    store.create_run(run["research_id"], "answer_review", {"max_model_calls": ANSWER_REVIEW_MODEL_CALLS, "max_provider_requests": 0},
                     f"answer_review:{row['id']}", target={"answer_id": row["id"], "answer_run_id": run["id"]})


async def review(flow: Any, run: dict[str, Any], scope: dict[str, Any]) -> None:
    flow._checkpoint(run["id"], run["scope_revision"])
    row = flow.store.conn.execute("SELECT * FROM answers WHERE id = ? AND research_id = ? AND status = 'structurally_valid'",
                                 (run["target"]["answer_id"], run["research_id"])).fetchone()
    if not row:
        flow._fail(run["id"], "answer_unavailable")
    await flow._review(run, scope, row["id"], json.loads(row["draft_json"]))
