"""Reverse citation search, slice R1: the statement check's frozen list, its passage pool, the item step and its
verdict, recovery, the counters and the export, with a FakeAdapter. Records, PDFs, the cutoff and model answers are
SYNTHETIC and scripted; nothing here calls a real model or the network, so these tests show what the workflow does with
an answer, not how well any model answers."""

import asyncio
import copy
import csv
import io
import json
from types import SimpleNamespace

import pytest

from deixis.config import Settings
from deixis.domain import contracts, skill
from deixis.domain.rules import TEST_EFFORT_BUDGETS
from deixis.models.adapter import ModelStepResult
from deixis.storage.db import new_id, now, transaction
from deixis.workflow import fast_answer, fast_path, small_batch, statement_check
from deixis.workflow.decisions import DecisionStore
from deixis.workflow.flow import FlowDeps, ResearchFlow
from fakes import FakeAdapter, envelope, valid_response
from test_contracts import STEP_INPUTS
from test_criterion_passage_flow import TOPIC_PAGE, library, page_source
from test_fast_path_answer import candidate, inspected_pdf

SENTENCE = "Supervised exercise lowered cancer related fatigue after chemotherapy."
ABSTRACT = "SYNTHETIC supervised exercise lowered fatigue in one trial."
MODEL = {"connection": "fake", "model": "fake-model"}


# ---------------------------------------------------------------------------------------------------- the library

def build(tmp_path, n=1, codes=("runs_agree_candidate",), pdf=False, responder=valid_response, fail=None):
    """A statement research whose discovery listed `n` abstract works (and a PDF work), as `test_fast_path_answer.setup`
    builds one, with a flow whose FakeAdapter answers through `responder`."""
    store, rid = library(tmp_path, question=SENTENCE)
    store.conn.execute("UPDATE researches SET intent = 'statement' WHERE id = ?", (rid,))
    sources = [candidate(store, rid, str(i), ABSTRACT, *codes) for i in range(n)]
    if pdf:
        sources += [page_source(store, rid, "pdf", [TOPIC_PAGE] * 3, ABSTRACT, included=False)]
        DecisionStore(store).record(rid, sources[-1], "runs_agree_candidate")
    budget = small_batch.freeze_budget(TEST_EFFORT_BUDGETS["quick"].__dict__, "quick", "off")
    budget["fast_path"] = fast_path.freeze_budget(budget, "quick")
    discovery = store.create_run(rid, "discovery", budget, None)
    store.update_run(discovery["id"], status="running")
    listing = {"policy": small_batch.POLICY, "order": sources, "order_hash": "synthetic", "manifest_hash": "synthetic",
               "manifest": {"scope_revision": 1, "versions": {svid: store.source(svid) for svid in sources}},
               "items": [{"work_id": store.source(svid)["work_id"], "head": svid, "position": i + 1, "versions": [svid],
                          "user_priority": False} for i, svid in enumerate(sources)]}
    step = store.step(discovery["id"], small_batch.LIST_KEY, "code:small_batch_list")
    store.finish_step(step["id"], "succeeded", output=listing)
    adapter = FakeAdapter(responder, fail=fail)
    flow = ResearchFlow(FlowDeps(Settings(data_dir=tmp_path / "data", port=8879), store, {"fake": adapter},
                                 skill.load_skill_package(), None))
    return SimpleNamespace(store=store, rid=rid, sources=sources, discovery=store.run(discovery["id"]), listing=listing,
                           flow=flow, adapter=adapter)


def cutoff(lib, read_window=None):
    """Freeze the read cutoff and complete the discovery; `read_window` narrows the works the reading reached."""
    run = copy.deepcopy(lib.discovery)
    if read_window is not None:
        run["budget"]["fast_path"]["N"] = read_window
    with transaction(lib.store.conn):
        frozen = fast_answer.freeze_cutoff(lib.flow, run, lib.listing, {
            "read_cutoff_at": fast_path.timestamp(lib.store.clock), "not_screened_at_cutoff": []})
    lib.store.update_run(lib.discovery["id"], status="completed")
    return frozen


def user(lib, svid, state):
    version = lib.store.conn.execute("SELECT version FROM selections WHERE research_id = ? AND source_version_id = ?",
                                     (lib.rid, svid)).fetchone()[0]
    lib.store.set_user_selection(lib.rid, svid, state, version, "SYNTHETIC person's reason")


def create(lib, request_id="req-1"):
    return statement_check.create_check(lib.flow, lib.rid, lib.discovery["id"], MODEL, request_id)


def execute(lib, check):
    run_id = statement_check.check_row(lib.store, check["id"])["run_id"]
    if lib.store.run(run_id)["status"] == "queued":
        lib.store.update_run(run_id, status="running")
    asyncio.run(lib.flow.execute(run_id))
    return lib.store.run(run_id)


def items(lib, check):
    return statement_check.items_of(lib.store, check["id"])


def by_source(lib, check):
    return {item["source_version_id"]: item for item in items(lib, check)}


def answer(si, parts, covers=True):
    return json.dumps(envelope(si, "deixis.citation_check.v1") | {"parts": parts, "covers_whole_sentence": covers})


def scripted(for_item, others=valid_response):
    """`for_item(si, attempt)` answers every statement-check step; every other step gets the valid default."""
    attempts = {}

    def respond(si):
        if si["task_type"] != "statement_check":
            return others(si)
        key = si["statement_check_target"]["item_id"]
        attempts[key] = attempts.get(key, 0) + 1
        return for_item(si, attempts[key])
    respond.attempts = attempts
    return respond


def replace_passage(store, passage_id, text):
    """A passage's text changed: passages are immutable, so the old row goes and a new one takes its place."""
    row = store.passage(passage_id)
    store.conn.execute("DELETE FROM passages WHERE id = ?", (passage_id,))
    row |= {"id": new_id("psg"), "text": text}
    store.conn.execute(f"INSERT INTO passages ({', '.join(row)}) VALUES ({', '.join('?' * len(row))})", tuple(row.values()))


def statement_calls(lib):
    return [si for si in lib.adapter.calls if si["task_type"] == "statement_check"]


def counter_identities(counters):
    """The plan's equalities: listed = the four statuses; candidates = listed + out of cap + reason; completed = the
    three results; could not check is in no result."""
    by_status = counters["by_status"]
    assert counters["listed"] == sum(by_status.values())
    assert counters["candidates"] == counters["listed"] + counters["out_of_cap"] + counters["excluded_reason"]
    assert counters["completed"] == sum(counters["results"].values()) == by_status["done"]
    assert sum(sum(row.values()) for row in counters["results_by_depth"].values()) == counters["completed"]
    assert counters["excluded_reason"] == sum(counters["excluded_reasons"].values())


# ------------------------------------------------------------------------------------- the target and its handles

def test_handles_go_and_come_back_and_the_target_needs_no_citation_pair():
    si = STEP_INPUTS["V_statement_check"]
    assert contracts.check_step_input(si) == []
    shown = contracts.with_citation_handles(si)
    source_handle = shown["sources"][0]["source_id"]
    assert source_handle.startswith("srv_S") and shown["statement_check_target"]["assessed_source_id"] == source_handle
    assert si["statement_check_target"]["assessed_source_id"] == "srv_SYNTHCIT001"  # the stored StepInput keeps its ids
    first = shown["passages"][0]["passage_id"]
    assert first.startswith("psg_P")
    raw = json.dumps(envelope(si, "deixis.citation_check.v1") | {"covers_whole_sentence": True, "parts": [
        {"text": "Depth based routing raises packet delivery in sparse networks", "assessment": "stated",
         "evidence": [{"passage_id": first, "quote": "depth based routing raises packet delivery in sparse networks"}]},
        {"text": "reduces energy use", "assessment": "not_stated", "evidence": []}]})
    resolved = contracts.resolve_citation_handles(si, raw)
    assert resolved["parts"][0]["evidence"][0]["passage_id"] == "psg_SYNTHCIT001"
    report = contracts.validate_model_output(si, resolved)
    assert report.ok, [vars(i) for i in report.issues]
    view = contracts.citation_check_view(si)
    assert view["citation_check_target"]["pair_id"] == "sci_SYNTHSTC001" and "statement_check_target" not in view
    anchors = contracts.citation_check_anchors(view, report.result)
    assert anchors[0][0]["located"] and anchors[0][0]["passage_id"] == "psg_SYNTHCIT001"
    assert anchors[0][0]["anchor_text"] in si["passages"][0]["text"]


def test_a_statement_check_takes_its_own_target_and_only_it():
    si = STEP_INPUTS["V_statement_check"]
    both = copy.deepcopy(si) | {"citation_check_target": STEP_INPUTS["V_citation_check"]["citation_check_target"]}
    assert "statement_check_target_mismatch" in {i.code for i in contracts.check_step_input(both)}
    missing = {k: v for k, v in copy.deepcopy(si).items() if k != "statement_check_target"}
    assert {"statement_check_target_mismatch", "citation_check_target_mismatch"} <= {
        i.code for i in contracts.check_step_input(missing)}
    on_citation = copy.deepcopy(STEP_INPUTS["V_citation_check"]) | {"statement_check_target": si["statement_check_target"]}
    assert "statement_check_target_mismatch" in {i.code for i in contracts.check_step_input(on_citation)}
    assert contracts.check_step_input(STEP_INPUTS["V_citation_check"]) == []


def _parts(first, second):
    return [{"text": "Depth based routing raises packet delivery in sparse networks", "assessment": "stated",
             "evidence": [first]}, second]


NOT_STATED = {"text": "reduces energy use", "assessment": "not_stated", "evidence": []}
V3_CASES = {
    "wrong_passage": (_parts({"passage_id": "psg_SYNTHCIT002",
                              "quote": "depth based routing raises packet delivery in sparse networks"}, NOT_STATED),
                      ["anchor_not_in_passage"]),
    "other_works_passage": (_parts({"passage_id": "psg_SYNTHOTHER01", "quote": "depth based routing"}, NOT_STATED),
                            ["unknown_passage_id"]),
    "negation_window": (_parts({"passage_id": "psg_SYNTHCIT001",
                                "quote": "depth based routing raises packet delivery in sparse networks"},
                               {"text": "reduces energy use", "assessment": "stated", "evidence": [
                                   {"passage_id": "psg_SYNTHCIT002", "quote": "significantly reduce energy use"}]}),
                        ["quote_meaning_differs"]),
    "number_cut": (_parts({"passage_id": "psg_SYNTHCIT001", "quote": "packet delivery in sparse networks by 1"},
                          NOT_STATED), ["quote_meaning_differs"]),
    "number_unit": (_parts({"passage_id": "psg_SYNTHCIT001", "quote": "packet delivery in sparse networks by 12"},
                           NOT_STATED), ["quote_meaning_differs"]),
    "coverage": (_parts({"passage_id": "psg_SYNTHCIT001",
                         "quote": "depth based routing raises packet delivery in sparse networks"}, NOT_STATED)[:1],
                 ["parts_leave_out_words", "sentence_not_covered"]),
}


@pytest.mark.parametrize("case", sorted(V3_CASES))
def test_v3_examples_give_the_same_result_on_a_statement_check(case):
    parts, expected = V3_CASES[case]
    codes = []
    for name in ("V_citation_check", "V_statement_check"):
        si = STEP_INPUTS[name]
        output = envelope(si, "deixis.citation_check.v1") | {"parts": copy.deepcopy(parts),
                                                             "covers_whole_sentence": case != "coverage"}
        codes.append(contracts.validate_model_output(si, output).codes())
    assert codes[0] == codes[1] == sorted(expected)


# -------------------------------------------------------------------------------------------- the passage pool

def test_a_pdf_the_person_marked_wrong_never_enters_the_pool_and_the_work_is_checked_on_its_abstract(tmp_path):
    lib = build(tmp_path, pdf=True)
    svid, item = inspected_pdf(lib)
    frozen = cutoff(lib)
    assert frozen["items"][-1]["route"] == "fulltext" and frozen["items"][-1]["asset_id"] == item["asset_id"]
    DecisionStore(lib.store).record(lib.rid, svid, "human_pdf_wrong")
    check = create(lib)
    pdf_item = by_source(lib, check)[svid]
    plan = json.loads(pdf_item["plan_json"])
    assert (pdf_item["route"], pdf_item["depth"], pdf_item["asset_id"]) == ("abstract", "abstract", None)
    assert [lib.store.passage(pid)["kind"] for pid in plan["passage_ids"]] == ["abstract"]
    assert plan["passages_total"] == 1 and plan["passages_not_given"] == 0
    execute(lib, check)
    sent = next(si for si in statement_calls(lib) if si["statement_check_target"]["item_id"] == pdf_item["id"])
    assert [p["locator"]["kind"] for p in sent["passages"]] == ["abstract"]


def test_pages_of_another_file_of_the_same_record_never_enter_the_pool(tmp_path):
    """The pool holds the cutoff's file and no other: once the person replaced it by a new file (never read at the
    cutoff), neither the old file's pages nor the new one's are read, and the work is checked on its abstract."""
    lib = build(tmp_path, pdf=True)
    svid, item = inspected_pdf(lib)
    cutoff(lib)
    store = lib.store
    check = create(lib)
    plan = json.loads(by_source(lib, check)[svid]["plan_json"])
    assert all(store.passage(pid)["asset_id"] in (None, item["asset_id"]) for pid in plan["passage_ids"])
    # Three pages and the abstract, all given, from a complete extraction: the whole text.
    assert (plan["passages_total"], plan["depth"], plan["extraction_complete"]) == (4, "full_text", True)
    newer = "ast_" + new_id("x")[4:]
    with transaction(store.conn):
        store.conn.execute("UPDATE source_assets SET removed_at = ?, removal_reason = 'replaced' WHERE id = ?",
                           (now(), item["asset_id"]))
        store.conn.execute(
            "INSERT INTO source_assets (id, source_version_id, sha256, byte_size, media_type, storage_path, retrieved_at,"
            " origin, extraction_status, extraction_version) VALUES (?, ?, 'sha-newer', 1, 'application/pdf', 'newer.pdf',"
            " ?, 'user_upload', 'succeeded', 'test')", (newer, svid, now()))
        store.conn.execute(
            "INSERT INTO passages (id, source_version_id, asset_id, kind, physical_page, extraction_version, text,"
            " text_sha256, retrieved_at, created_at) VALUES (?, ?, ?, 'pdf_page', 1, 'test', ?, 'h', ?, ?)",
            (new_id("psg"), svid, newer, "SYNTHETIC supervised exercise lowered cancer related fatigue, newer file.",
             now(), now()))
    store.update_run(check["run_id"], status="cancelled")
    assert newer in {p["asset_id"] for p in store.passages_for(svid)}
    assert statement_check.passage_pool(store, svid, "fulltext", item["asset_id"]) == [
        p for p in store.passages_for(svid) if p["kind"] == "abstract"]
    again = statement_check.create_check(lib.flow, lib.rid, lib.discovery["id"], MODEL, "req-2")
    replaced = by_source(lib, again)[svid]
    plan = json.loads(replaced["plan_json"])
    assert (replaced["route"], replaced["depth"], again["revision"]) == ("fulltext", "abstract", 2)
    assert [store.passage(pid)["kind"] for pid in plan["passage_ids"]] == ["abstract"]


def test_a_partial_extraction_is_never_full_text(tmp_path):
    lib = build(tmp_path, pdf=True)
    svid, item = inspected_pdf(lib)
    cutoff(lib)
    lib.store.conn.execute("UPDATE source_assets SET extraction_status = 'partial' WHERE id = ?", (item["asset_id"],))
    check = create(lib)
    pdf_item = by_source(lib, check)[svid]
    plan = json.loads(pdf_item["plan_json"])
    assert plan["passages_not_given"] == 0 and len(plan["passage_ids"]) == 4
    assert (pdf_item["depth"], pdf_item["extraction_complete"]) == ("selected_passages", 0)


def test_an_abstract_only_work_is_given_one_passage_at_depth_abstract(tmp_path):
    lib = build(tmp_path)
    cutoff(lib)
    check = create(lib)
    (item,) = items(lib, check)
    plan = json.loads(item["plan_json"])
    assert (item["eligibility"], item["status"], item["depth"], item["extraction_complete"]) == (
        "listed", "planned", "abstract", None)
    assert len(plan["passage_ids"]) == 1 and lib.store.passage(plan["passage_ids"][0])["kind"] == "abstract"


# ------------------------------------------------------------------------------------------------- the frozen list

def test_eligibility_reasons_choices_and_the_cap_order(tmp_path):
    """Quick allows 12 works. Of 16 abstract works the first is outside the read window (14 read, the 15th and 16th
    out), one is person-excluded, one failed screening and is person-included; the included one goes first, then
    the reading order, and what passes the cap is listed and counted as out of cap."""
    lib = build(tmp_path, n=16)
    store = lib.store
    out_of_scope = lib.sources[5]
    DecisionStore(store).record(lib.rid, out_of_scope, "runs_agree_out_of_scope")
    DecisionStore(store).derive_selection(lib.rid, store.source(out_of_scope)["work_id"])
    frozen = cutoff(lib, read_window=14)
    reasons = {row["source_version_id"]: row["reason"] for row in frozen["items"]}
    assert reasons[lib.sources[14]] == reasons[lib.sources[15]] == "outside_read_window"
    assert reasons[out_of_scope] == "out_of_scope"
    user(lib, out_of_scope, "included")
    user(lib, lib.sources[2], "excluded")
    check = create(lib)
    rows = items(lib, check)
    assert rows[0]["source_version_id"] == out_of_scope and rows[0]["entry"] == "person_included"
    found = by_source(lib, check)
    assert (found[out_of_scope]["eligibility"], found[out_of_scope]["status"]) == ("listed", "planned")
    assert found[lib.sources[2]]["eligibility"] == "person_excluded" and found[lib.sources[2]]["status"] is None
    for svid in lib.sources[14:]:
        assert (found[svid]["eligibility"], found[svid]["excluded_reason"]) == ("excluded_reason", "outside_read_window")
    planned = [r["source_version_id"] for r in rows if r["status"] == "planned"]
    capped = [r["source_version_id"] for r in rows if r["eligibility"] == "out_of_cap"]
    reading = [s for s in lib.sources[:14] if s not in (out_of_scope, lib.sources[2])]
    assert planned == [out_of_scope] + reading[:11] and capped == reading[11:]
    counters = statement_check.counters(store, statement_check.check_row(store, check["id"]))
    assert (counters["listed"], counters["out_of_cap"], counters["excluded_reason"], counters["person_excluded"],
            counters["candidates"]) == (12, 1, 2, 1, 15)
    assert counters["excluded_reasons"] == {"outside_read_window": 2}
    counter_identities(counters)
    assert store.run(check["run_id"])["budget"]["max_model_calls"] == 24  # one call and one repair per planned work


def test_no_text_from_both_paths_and_every_work_counted_once(tmp_path):
    """A work the cutoff left out for want of text that the person then included, and a listed work whose abstract
    went before the freeze: both are listed with `no_text`, never sent, and each work is one item."""
    lib = build(tmp_path, n=3)
    store = lib.store
    no_text, gone, kept = lib.sources
    store.conn.execute("DELETE FROM passages WHERE source_version_id = ?", (no_text,))
    frozen = cutoff(lib)
    assert {r["source_version_id"]: r["reason"] for r in frozen["items"]}[no_text] == "no_text_at_cutoff"
    store.conn.execute("DELETE FROM passages WHERE source_version_id = ?", (gone,))
    user(lib, no_text, "included")
    user(lib, kept, "excluded")
    user(lib, kept, "included")  # excluded, then included again: one item, listed
    check = create(lib)
    found = by_source(lib, check)
    assert len(items(lib, check)) == 3
    assert (found[no_text]["eligibility"], found[no_text]["status"], found[no_text]["entry"]) == (
        "listed", "no_text", "person_included")
    assert (found[gone]["eligibility"], found[gone]["status"]) == ("listed", "no_text")
    assert (found[kept]["eligibility"], found[kept]["status"]) == ("listed", "planned")
    execute(lib, check)
    assert [si["statement_check_target"]["item_id"] for si in statement_calls(lib)] == [found[kept]["id"]]
    counters = statement_check.counters(store, statement_check.check_row(store, check["id"]))
    assert counters["by_status"] == {"planned": 0, "done": 1, "could_not_check": 0, "no_text": 2}
    assert counters["sent_to_model"] == 1 and counters["candidates"] == 3
    counter_identities(counters)


def test_a_work_the_person_included_after_the_cutoff_is_listed_first(tmp_path):
    lib = build(tmp_path, n=2)
    cutoff(lib)
    later = candidate(lib.store, lib.rid, "later", ABSTRACT, "runs_agree_out_of_scope")
    user(lib, later, "included")
    check = create(lib)
    rows = items(lib, check)
    assert [r["source_version_id"] for r in rows] == [later, *lib.sources]
    assert (rows[0]["entry"], rows[0]["eligibility"], rows[0]["status"], rows[0]["depth"]) == (
        "person_included", "listed", "planned", "abstract")


def test_only_a_statement_research_with_its_completed_discovery_is_checked(tmp_path):
    lib = build(tmp_path)
    with pytest.raises(statement_check.Refused) as refused:
        create(lib)
    assert refused.value.code == "discovery_mismatch"  # still running
    cutoff(lib)
    with pytest.raises(statement_check.Refused) as refused:
        statement_check.create_check(lib.flow, lib.rid, lib.discovery["id"], None, "req-0")
    assert refused.value.code == "no_model"
    lib.store.conn.execute("UPDATE researches SET intent = 'report' WHERE id = ?", (lib.rid,))
    with pytest.raises(statement_check.Refused) as refused:
        create(lib)
    assert refused.value.code == "not_statement"
    lib.store.conn.execute("UPDATE researches SET intent = 'statement' WHERE id = ?", (lib.rid,))
    check = create(lib)
    assert create(lib)["id"] == check["id"]  # the same request opens no second revision
    run = lib.store.run(check["run_id"])
    assert (run["kind"], run["status"], run["stage"]) == ("statement_check", "queued", "claim_check")
    assert run["target"]["model"] == {"connection": "fake", "model": "fake-model", "reasoning_effort": None}
    assert check["sentence"] == SENTENCE and check["revision"] == 1 and check["currency"] == "current"


# -------------------------------------------------------------------------------------------- the item check

def test_every_planned_work_is_checked_on_the_frozen_model_and_found_whole_needs_located_quotes(tmp_path):
    lib = build(tmp_path, n=2, pdf=True)
    inspected_pdf(lib)
    cutoff(lib)
    check = create(lib)
    run = execute(lib, check)
    assert run["status"] == "completed"
    rows = items(lib, check)
    assert [(r["status"], r["result"]) for r in rows] == [("done", "found_whole")] * 3
    calls = statement_calls(lib)
    assert [si["statement_check_target"]["item_id"] for si in calls] == [r["id"] for r in rows]
    assert {sent[1] for sent in lib.adapter.sent if sent[0] == "statement_check"} == {"fake-model"}
    for si in calls:
        assert len(si["sources"]) == 1 and si["statement_check_target"]["sentence"] == SENTENCE
        assert {p["source_id"] for p in si["passages"]} == {si["statement_check_target"]["assessed_source_id"]}
    row = rows[-1]
    anchors = json.loads(row["located_anchors_json"])
    assert anchors[0][0]["located"] and anchors[0][0]["anchor_text"] in lib.store.passage(anchors[0][0]["passage_id"])["text"]
    model = json.loads(row["model_json"])
    assert (model["requested_model"], model["resolved_model"], model["sent"]) == ("fake-model", "fake-model", True)
    assert json.loads(row["validation_json"])["ok"] is True and row["raw_output"]
    assert statement_check.check_row(lib.store, check["id"])["status"] == "finished"
    counters = statement_check.counters(lib.store, statement_check.check_row(lib.store, check["id"]))
    assert counters["results"] == {"found_whole": 3, "found_partial": 0, "not_found_in_given": 0}
    assert counters["results_by_depth"]["found_whole"] == {"selected_passages": 0, "abstract": 2, "full_text": 1}
    assert counters["sent_to_model"] == 3
    counter_identities(counters)


def test_repair_that_runs_out_is_could_not_check_never_not_found(tmp_path):
    def respond(si, attempt):
        return answer(si, [{"text": SENTENCE.rstrip("."), "assessment": "stated", "evidence": []}])
    responder = scripted(respond)
    lib = build(tmp_path, n=2, responder=responder)
    cutoff(lib)
    check = create(lib)
    execute(lib, check)
    rows = items(lib, check)
    assert [(r["status"], r["result"]) for r in rows] == [("could_not_check", None)] * 2
    error = json.loads(rows[0]["error_json"])
    assert error["code"] == "invalid_model_output"
    assert {i["code"] for i in error["issues"]} == {"positive_part_without_quote"}
    assert json.loads(rows[0]["raw_output"])["parts"][0]["evidence"] == []
    assert list(responder.attempts.values()) == [2, 2]  # the first answer and its one repair
    counters = statement_check.counters(lib.store, statement_check.check_row(lib.store, check["id"]))
    assert counters["by_status"]["could_not_check"] == 2 and counters["completed"] == 0
    assert counters["results"]["not_found_in_given"] == 0 and counters["sent_to_model"] == 2
    counter_identities(counters)


def test_all_parts_not_stated_with_the_sentence_covered_is_not_found_in_given(tmp_path):
    def respond(si, attempt):
        return answer(si, [{"text": "Supervised exercise lowered cancer related fatigue", "assessment": "not_stated",
                            "evidence": []},
                           {"text": "after chemotherapy", "assessment": "not_stated", "evidence": []}])
    lib = build(tmp_path, responder=scripted(respond))
    cutoff(lib)
    check = create(lib)
    execute(lib, check)
    (row,) = items(lib, check)
    assert (row["status"], row["result"]) == ("done", "not_found_in_given")
    counters = statement_check.counters(lib.store, statement_check.check_row(lib.store, check["id"]))
    assert counters["results_by_depth"]["not_found_in_given"]["abstract"] == 1
    counter_identities(counters)


def test_a_provider_failure_leaves_the_work_planned_and_the_resume_never_resends_a_checked_one(tmp_path):
    failing = {"on": True}

    def fail(si):
        if failing["on"] and si["task_type"] == "statement_check" and si["statement_check_target"]["item_id"] == second["id"]:
            return ModelStepResult("failed", error="SYNTHETIC provider error")
        return None
    lib = build(tmp_path, n=2, fail=fail)
    cutoff(lib)
    check = create(lib)
    first, second = items(lib, check)
    run = execute(lib, check)
    assert (run["status"], run["pause_reason"]) == ("paused", "model_call_failed")
    rows = items(lib, check)
    assert [(r["status"], r["result"]) for r in rows] == [("done", "found_whole"), ("planned", None)]
    counters = statement_check.counters(lib.store, statement_check.check_row(lib.store, check["id"]))
    assert counters["by_status"]["planned"] == 1 and counters["by_status"]["could_not_check"] == 0
    assert counters["sent_to_model"] == 2
    before = len(statement_calls(lib))
    failing["on"] = False
    lib.store.resume_run(run["id"])
    assert execute(lib, check)["status"] == "completed"
    assert [si["statement_check_target"]["item_id"] for si in statement_calls(lib)[before:]] == [second["id"]]
    assert [(r["status"], r["result"]) for r in items(lib, check)] == [("done", "found_whole")] * 2


def test_a_succeeded_step_whose_result_was_not_stored_is_read_back_after_a_restart(tmp_path):
    """A crash between the step's end and the item's write: the restarted run reads the step's output, sends
    nothing, and keeps the model and run that answered."""
    lib = build(tmp_path, n=2)
    cutoff(lib)
    check = create(lib)
    run = execute(lib, check)
    first = items(lib, check)[0]
    store = lib.store
    with store.conn:
        store.conn.execute(
            "UPDATE statement_check_items SET status = 'planned', result = NULL, output_json = NULL, run_id = NULL,"
            " located_anchors_json = NULL, validation_json = NULL, model_json = NULL, checked_at = NULL WHERE id = ?",
            (first["id"],))
        store.conn.execute("UPDATE statement_checks SET status = 'open' WHERE id = ?", (check["id"],))
        store.conn.execute("UPDATE runs SET status = 'paused', pause_reason = 'backend_restarted' WHERE id = ?",
                           (run["id"],))
    calls = len(statement_calls(lib))
    store.resume_run(run["id"])
    assert execute(lib, check)["status"] == "completed"
    assert len(statement_calls(lib)) == calls
    restored = items(lib, check)[0]
    assert (restored["status"], restored["result"]) == ("done", "found_whole")
    assert json.loads(restored["model_json"])["requested_model"] == "fake-model" and restored["run_id"] == run["id"]
    assert statement_check.check_row(store, check["id"])["status"] == "finished"


def test_a_passage_changed_before_the_send_is_could_not_check_and_never_sent(tmp_path):
    lib = build(tmp_path, n=2)
    cutoff(lib)
    check = create(lib)
    first, second = items(lib, check)
    passage_id = json.loads(first["plan_json"])["passage_ids"][0]
    replace_passage(lib.store, passage_id, ABSTRACT + " SYNTHETIC changed.")
    assert execute(lib, check)["status"] == "completed"
    assert [si["statement_check_target"]["item_id"] for si in statement_calls(lib)] == [second["id"]]
    changed = items(lib, check)[0]
    assert (changed["status"], changed["result"]) == ("could_not_check", None)
    assert json.loads(changed["error_json"]) == {"code": "frozen_input_changed", "reason": "passages_changed"}
    counters = statement_check.counters(lib.store, statement_check.check_row(lib.store, check["id"]))
    assert counters["sent_to_model"] == 1 and counters["by_status"]["could_not_check"] == 1
    counter_identities(counters)


def test_a_passage_changed_between_the_first_answer_and_its_repair_is_never_repaired(tmp_path):
    state = {}

    def respond(si, attempt):
        # The first answer is invalid; before its repair goes out the given passage changes.
        replace_passage(state["store"], state["passage"], ABSTRACT + " SYNTHETIC changed.")
        return answer(si, [{"text": SENTENCE.rstrip("."), "assessment": "stated", "evidence": []}])
    responder = scripted(respond)
    lib = build(tmp_path, responder=responder)
    cutoff(lib)
    check = create(lib)
    (item,) = items(lib, check)
    state |= {"store": lib.store, "passage": json.loads(item["plan_json"])["passage_ids"][0]}
    execute(lib, check)
    (row,) = items(lib, check)
    assert list(responder.attempts.values()) == [1]
    assert (row["status"], json.loads(row["error_json"])["code"]) == ("could_not_check", "frozen_input_changed")
    assert row["raw_output"]  # the first answer is kept
    step = lib.store.existing_step(check["run_id"], statement_check.item_key(item["id"], check["revision"]))
    assert (step["status"], step["error_code"]) == ("cancelled", "frozen_input_changed")


def test_the_export_writes_every_work_with_status_result_and_depth_apart(tmp_path):
    def respond(si, attempt):
        return answer(si, [{"text": SENTENCE.rstrip("."), "assessment": "stated", "evidence": []}])
    lib = build(tmp_path, n=2, pdf=True, responder=scripted(respond, valid_response))
    inspected_pdf(lib)
    cutoff(lib)
    user(lib, lib.sources[1], "excluded")
    check = create(lib)
    execute(lib, check)
    rows = list(csv.DictReader(io.StringIO(statement_check.export(lib.store, check["id"], "csv"))))
    assert [(r["eligibility"], r["status"], r["result"], r["error"]) for r in rows] == [
        ("listed", "could_not_check", "", "invalid_model_output"), ("person_excluded", "", "", ""),
        ("listed", "could_not_check", "", "invalid_model_output")]
    assert rows[2]["depth"] == "full_text" and rows[2]["extraction_complete"] == "True"
    assert rows[2]["passages_given"] == "4" and rows[2]["passages_not_given"] == "0" and rows[2]["passages_cut"] == "0"
    assert rows[2]["text_version"] == "upload" and rows[0]["depth"] == "abstract"
    assert {r["currency"] for r in rows} == {"current"} and {r["revision"] for r in rows} == {"1"}
    markdown = statement_check.export(lib.store, check["id"], "md")
    assert markdown.count("\n") == 5 and "| could_not_check |" in markdown


def test_located_quotes_are_exported_with_their_page(tmp_path):
    lib = build(tmp_path, pdf=True)
    inspected_pdf(lib)
    cutoff(lib)
    check = create(lib)
    execute(lib, check)
    rows = statement_check.export_rows(lib.store, check["id"])
    assert rows[0]["located_quotes"][0].startswith("abstract: ")
    assert rows[1]["located_quotes"][0].startswith(("p. ", "abstract: "))
    assert rows[1]["result"] == "found_whole" and rows[1]["located_passage_kinds"]


def test_purging_the_research_removes_its_checks(tmp_path):
    lib = build(tmp_path)
    cutoff(lib)
    execute(lib, create(lib))
    lib.store.trash_research(lib.rid)
    lib.store.purge_research(lib.rid)
    for table in ("statement_checks", "statement_check_items"):
        assert lib.store.conn.execute(f"SELECT COUNT(*) FROM {table}").fetchone()[0] == 0


# ------------------------------------------------------------------------------------------- review fixes (Sol)

def test_an_included_work_whose_pdf_the_person_marked_wrong_is_read_from_its_abstract(tmp_path):
    """Inclusion and the PDF's admissibility are two choices: the person's include keeps the work on the list, and the
    PDF they marked wrong still never enters its pool."""
    lib = build(tmp_path, pdf=True)
    svid, _ = inspected_pdf(lib)
    cutoff(lib)
    user(lib, svid, "included")
    DecisionStore(lib.store).record(lib.rid, svid, "human_pdf_wrong")
    check = create(lib)
    item = by_source(lib, check)[svid]
    plan = json.loads(item["plan_json"])
    assert (item["entry"], item["route"], item["depth"], item["asset_id"]) == ("person_included", "abstract", "abstract", None)
    assert [lib.store.passage(pid)["kind"] for pid in plan["passage_ids"]] == ["abstract"]
    execute(lib, check)
    sent = next(si for si in statement_calls(lib) if si["statement_check_target"]["item_id"] == item["id"])
    assert [p["locator"]["kind"] for p in sent["passages"]] == ["abstract"]


def test_a_work_included_after_the_cutoff_whose_pdf_was_marked_wrong_is_read_from_its_abstract(tmp_path):
    lib = build(tmp_path)
    with transaction(lib.store.conn):  # the cutoff is frozen before the PDF work joins the research
        fast_answer.freeze_cutoff(lib.flow, lib.discovery, lib.listing, {
            "read_cutoff_at": fast_path.timestamp(lib.store.clock), "not_screened_at_cutoff": []})
    svid = page_source(lib.store, lib.rid, "later-pdf", [TOPIC_PAGE] * 3, ABSTRACT, included=False)
    DecisionStore(lib.store).record(lib.rid, svid, "runs_agree_candidate")
    lib.sources.append(svid)
    inspected_pdf(lib)
    lib.store.update_run(lib.discovery["id"], status="completed")
    user(lib, svid, "included")
    readable = fast_answer.after_cutoff_rows(lib.store, lib.flow, lib.rid, {lib.store.source(svid)["work_id"]: svid})[0]
    assert readable[0]["route"] == "fulltext"  # read in full, until the person says the PDF is wrong
    DecisionStore(lib.store).record(lib.rid, svid, "human_pdf_wrong")
    check = create(lib)
    item = by_source(lib, check)[svid]
    assert (item["entry"], item["eligibility"], item["route"], item["depth"]) == (
        "person_included", "listed", "abstract", "abstract")
    assert [lib.store.passage(pid)["kind"] for pid in json.loads(item["plan_json"])["passage_ids"]] == ["abstract"]


def test_a_call_that_never_left_is_not_counted_as_sent(tmp_path):
    """A connection that refuses before sending opens a model session; the work stays planned and is not sent. The
    resume that sends it counts it once."""
    failing = {"on": True}

    def fail(si):
        if failing["on"] and si["task_type"] == "statement_check":
            return ModelStepResult("unavailable", error="SYNTHETIC no connection", delivery_class="before_send")
        return None
    lib = build(tmp_path, fail=fail)
    cutoff(lib)
    check = create(lib)
    run = execute(lib, check)
    assert run["status"] == "paused"
    row = statement_check.check_row(lib.store, check["id"])
    assert items(lib, check)[0]["status"] == "planned"
    assert lib.store.conn.execute("SELECT COUNT(*) FROM model_sessions WHERE status = 'unavailable'").fetchone()[0] == 1
    assert statement_check.counters(lib.store, row)["sent_to_model"] == 0
    failing["on"] = False
    lib.store.resume_run(run["id"])
    assert execute(lib, check)["status"] == "completed"
    counters = statement_check.counters(lib.store, row)
    assert counters["sent_to_model"] == 1 and counters["by_status"]["done"] == 1


def test_a_request_id_belongs_to_one_research(tmp_path):
    first = build(tmp_path / "a")
    cutoff(first)
    check = create(first, "shared-request")
    store = first.store  # another statement research of the same library
    rid = store.create_research(SENTENCE, "academic", "quick", ["openalex"], "fake", "fake-model", None,
                                search_workflow="sw")
    store.conn.execute("UPDATE researches SET intent = 'statement' WHERE id = ?", (rid,))
    with pytest.raises(statement_check.Refused) as refused:
        statement_check.create_check(first.flow, rid, first.discovery["id"], MODEL, "shared-request")
    assert refused.value.code == "request_conflict"
    assert create(first, "shared-request")["id"] == check["id"]  # the same research's retry stays idempotent
