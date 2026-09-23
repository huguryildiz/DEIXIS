"""Full-text reading: the plan, the passage list, quote verification and the rule table (slice 12, D85).

Pure tests plus the migration's neighbours that do not start a reading run: the budget, the two new reason codes,
and a legacy research refusing the run. Records are SYNTHETIC and from two fields (greenhouse tomato, a small-town
bakery). Passing shows the rules behave as the slice says. It does not show that a model labels parts correctly,
or that a quote which verifies also supports the label.
"""

import random

import pytest
from fastapi.testclient import TestClient

from deixis.api.app import create_app
from deixis.config import Settings
from deixis.domain.reason_codes import reason
from deixis.providers.registry import CONNECTORS
from deixis.storage import db
from deixis.workflow import adjudication
from deixis.workflow.decisions import DecisionStore
from deixis.workflow.flow import CAPABILITIES
from deixis.workflow.store import Store
from fakes import FakeAdapter, valid_response
from test_stage_decisions import one_record, record, research, search

# Two fields, so a plan that keeps one and drops the other is not a single-topic accident.
ON = "SYNTHETIC greenhouse tomato"
OFF = "SYNTHETIC bakery delivery"


def decision(code, decided_by="code", stale=False):
    return {"reason_code": code, "decided_by": decided_by, "stale": stale}


def work(head, *, abstract=None, fulltext=None, selection=None, has_text=True):
    return {"work_id": f"wrk_{head}", "head": head, "selection": selection,
            "versions": [{"id": head, "has_text": has_text, "abstract": abstract, "fulltext": fulltext}]}


CANDIDATE = decision("runs_agree_candidate", "model_agreement")
UNRESOLVED = decision("abstract_not_found")
USER_INCLUDED = {"state": "included", "origin": "user"}
USER_EXCLUDED = {"state": "excluded", "origin": "user"}

PAGE = ("SYNTHETIC the greenhouse tomato crop used drip irrigation every morning of the trial period inside"
        " the glasshouse.")
FUZZY = PAGE.replace("morning", "evening")
NORMALIZED = PAGE.replace("greenhouse tomato", "greenhouse, tomato")


def passage(pid, page, text, kind="pdf_page"):
    return {"id": pid, "kind": kind, "physical_page": page, "text": text}


def criterion():
    return {
        "parts": [
            {"name": "irrigation", "definition": f"{ON} drip irrigation"},
            {"name": "yield", "definition": f"{ON} marketable yield"},
            {"name": "rounds", "definition": f"{OFF} rounds"},
        ],
        "cue_phrases": [
            {"phrase": "drip irrigation", "part": "irrigation"},
            {"phrase": "marketable yield", "part": "yield"},
            {"phrase": "bakery rounds", "part": "rounds"},
        ],
    }


@pytest.fixture
def library(tmp_path):
    connection = db.connect(tmp_path / "library.sqlite")
    db.migrate(connection)
    yield Store(connection)
    connection.close()


# ---- task 1 -----------------------------------------------------------------------------------
@pytest.mark.parametrize(("effort", "calls", "works_n"), [
    ("quick", 80, 40), ("standard", 100, 50), ("detailed", 300, 150),
])
def test_the_read_budget_is_two_calls_for_each_work_the_limit_reaches(effort, calls, works_n):
    assert adjudication.read_budget(effort) == {
        "max_model_calls": calls, "max_provider_requests": 0, "max_fulltext_reads": works_n,
    }


def test_the_reason_code_column_is_plain_text_so_the_new_codes_need_no_migration(library):
    column = next(row for row in library.conn.execute("PRAGMA table_info(stage_decisions)")
                  if row["name"] == "reason_code")
    assert column["type"].upper() == "TEXT"


@pytest.mark.parametrize("code", ["fulltext_runs_agree_unresolved", "pdf_identity_unconfirmed"])
def test_a_new_unresolved_code_derives_a_pending_selection(library, code):
    row = reason(code)
    assert (row.stage, row.outcome, row.decided_by, row.next_step) == ("fulltext", "unresolved", "code", "human_queue")
    rid, run_id = research(library)
    svid, work_id = one_record(library, rid, run_id)
    decisions = DecisionStore(library)
    decisions.record(rid, svid, code)
    assert decisions.derive_selection(rid, work_id) == "pending"
    selection = library.conn.execute(
        "SELECT state, origin FROM selections WHERE source_version_id = ?", (svid,)).fetchone()
    assert (selection["state"], selection["origin"]) == ("pending", "code_rule")


def _app(tmp_path, monkeypatch, workflow):
    for connector in CONNECTORS.values():
        if connector.key_env:
            monkeypatch.delenv(connector.key_env, raising=False)
    monkeypatch.delenv("GEMINI_API_KEY", raising=False)
    return create_app(Settings(data_dir=tmp_path / "data", port=8765, search_workflow=workflow, search_query="code",
                               fulltext_fetch="off", fulltext_adjudication="off"),
                      adapters={"fake": FakeAdapter()}, extra_hosts=("testserver",),
                      trusted_clients=("testclient",), start_worker=False)


def test_a_legacy_research_refuses_a_fulltext_reading_run(tmp_path, monkeypatch):
    app = _app(tmp_path, monkeypatch, "legacy")
    with TestClient(app) as client:
        client.headers["x-deixis-csrf"] = client.get("/api/session").json()["csrf_token"]
        created = client.post("/api/researches", json={
            "question": "SYNTHETIC: how does drip irrigation change greenhouse tomato yield, and what of a bakery?",
            "model_connection": "fake", "requested_model": "fake-model",
        })
        assert created.status_code == 201, created.text
        rid = created.json()["research"]["id"]
        refused = client.post(f"/api/researches/{rid}/runs", json={"kind": "fulltext_adjudication"})
    assert refused.status_code == 422
    assert refused.json()["detail"] == "Full-text reading runs belong to the search workflow"


def test_an_sw_research_queues_a_reading_run_on_the_inspection_stage_with_the_read_budget(tmp_path, monkeypatch):
    """The route stores the budget. The worker is not started, so nothing is read and no decision is written."""
    app = _app(tmp_path, monkeypatch, "sw")
    with TestClient(app) as client:
        client.headers["x-deixis-csrf"] = client.get("/api/session").json()["csrf_token"]
        created = client.post("/api/researches", json={
            "question": "SYNTHETIC: drip irrigation and marketable yield of greenhouse tomato, beside a bakery.",
            "model_connection": "fake", "requested_model": "fake-model", "effort": "quick",
        })
        assert created.status_code == 201, created.text
        rid = created.json()["research"]["id"]
        started = client.post(f"/api/researches/{rid}/runs", json={"kind": "fulltext_adjudication"})
    assert started.status_code == 202, started.text
    run = started.json()
    assert run["kind"] == "fulltext_adjudication" and run["stage"] == "inspection" and run["status"] == "queued"
    assert run["budget"] == adjudication.read_budget("quick")


def test_the_advertised_capabilities_do_not_gain_the_reading_task():
    assert "fulltext_adjudication" not in CAPABILITIES["supported_tasks"]


# ---- task 2 -----------------------------------------------------------------------------------
def test_the_three_groups_are_read_in_order_inside_the_ranking():
    works = [
        work("u1", abstract=decision("both_blocks_missing"), selection=USER_INCLUDED),
        work("c1", abstract=CANDIDATE),
        work("r1", abstract=UNRESOLVED),
    ]
    plan = adjudication.read_plan(works, ["r1", "c1", "u1"], limit=10)
    assert plan == {"works": ["u1", "c1", "r1"], "not_reached": []}


def test_chained_works_are_read_after_the_keyword_order():
    """D95: the chain's works are read in the chain's own order, after every keyword work; the limit is the same."""
    works = [work("c1", abstract=CANDIDATE), work("r1", abstract=UNRESOLVED),
             work("x1", abstract=CANDIDATE) | {"chained": True}, work("x2", abstract=UNRESOLVED) | {"chained": True}]
    plan = adjudication.read_plan(works, ["r1", "c1"] + ["x2", "x1"], limit=3)
    assert plan == {"works": ["c1", "r1", "x2"], "not_reached": ["x1"]}


def test_a_fresh_model_decision_stays_out_and_a_stale_one_reenters():
    """`not_read_yet` is not a model decision of this stage: the work is still read."""
    fresh = work("f1", abstract=CANDIDATE, fulltext=decision("all_parts_verified"))
    stale = work("s1", abstract=CANDIDATE, fulltext=decision("criterion_absent", stale=True))
    waiting = work("n1", abstract=CANDIDATE, fulltext=decision("not_read_yet"))
    plan = adjudication.read_plan([fresh, stale, waiting], ["f1", "s1", "n1"], limit=10)
    assert plan["works"] == ["s1", "n1"]
    assert "f1" not in plan["works"] and "f1" not in plan["not_reached"]


def test_a_human_fulltext_decision_and_a_user_exclusion_are_not_read():
    human = work("h1", abstract=CANDIDATE, fulltext=decision("human_include", "human"))
    excluded = work("x1", abstract=CANDIDATE, selection=USER_EXCLUDED)
    assert adjudication.read_plan([human, excluded], ["h1", "x1"], limit=10) == {"works": [], "not_reached": []}


def test_a_work_with_no_text_is_not_read():
    plain = work("t1", abstract=CANDIDATE, has_text=False)
    unreadable = work("t2", abstract=CANDIDATE, has_text=False, fulltext=decision("text_unreadable"))
    missing = work("t3", abstract=CANDIDATE, has_text=False, fulltext=decision("no_fulltext"))
    assert adjudication.read_plan([plain, unreadable, missing], ["t1", "t2", "t3"], limit=10) == {
        "works": [], "not_reached": [],
    }


def test_the_limit_cuts_the_plan_and_drops_nothing():
    works = [work(f"c{i}", abstract=CANDIDATE) for i in range(5)]
    works.append(work("x1", abstract=CANDIDATE, selection=USER_EXCLUDED))
    plan = adjudication.read_plan(works, [f"c{i}" for i in range(5)] + ["x1"], limit=2)
    assert plan["works"] == ["c0", "c1"]
    assert plan["not_reached"] == ["c2", "c3", "c4"]
    assert "x1" not in plan["works"] and "x1" not in plan["not_reached"]


def test_a_short_text_is_given_whole_and_an_abstract_is_not():
    pages = [passage(f"p{i}", i, f"{ON} page {i} of the trial") for i in range(1, 4)]
    abstract = passage("abs", None, f"{ON} abstract of the same trial", kind="abstract")
    listed = adjudication.reading_list([abstract, *pages], criterion(), [], per_call=12, criterion_share=8)
    assert listed["whole_text"] is True
    assert [p["id"] for p in listed["passages"]] == ["p1", "p2", "p3"]


def test_a_text_as_long_as_the_call_is_a_selection():
    pages = [passage(f"p{i}", i, f"{ON} page {i}") for i in range(1, 13)]
    listed = adjudication.reading_list(pages, criterion(), [], per_call=12, criterion_share=8)
    assert listed["whole_text"] is False and len(listed["passages"]) == 12


def test_rounds_give_each_part_a_place():
    pages = [
        passage("a", 1, f"{ON} under drip irrigation through the season"),
        passage("b", 2, f"{ON} under drip irrigation on a second page"),
        passage("c", 3, f"{ON} marketable yield at the end of the season"),
        passage("d", 4, f"{OFF} bakery rounds across the town"),
    ]
    listed = adjudication.reading_list(pages, criterion(), [], per_call=3, criterion_share=3)
    assert [p["id"] for p in listed["passages"]] == ["a", "c", "d"]
    assert listed["whole_text"] is False


def test_a_passage_already_taken_yields_that_parts_next_unchosen_one():
    """One page states two parts. The second part takes its next page, and the filler page stays out."""
    pages = [
        passage("a", 1, f"{ON} drip irrigation raised the marketable yield"),
        passage("b", 2, f"{ON} marketable yield counted at harvest"),
        passage("c", 3, f"{OFF} the glasshouse frame alone"),
    ]
    listed = adjudication.reading_list(pages, {
        "parts": criterion()["parts"][:2],
        "cue_phrases": criterion()["cue_phrases"][:2],
    }, [], per_call=2, criterion_share=2)
    assert [p["id"] for p in listed["passages"]] == ["a", "b"]


def test_no_phrases_means_topic_order_then_page_order():
    pages = [passage(f"p{i}", i, f"{ON} or {OFF} page {i}") for i in range(1, 16)]
    bare = {"parts": [{"name": "irrigation", "definition": ON}], "cue_phrases": []}
    topic = adjudication.reading_list(pages, bare, ["p9", "p8"], per_call=2, criterion_share=8)
    assert [p["id"] for p in topic["passages"]] == ["p8", "p9"]
    by_page = adjudication.reading_list(pages, bare, [], per_call=2, criterion_share=8)
    assert [p["id"] for p in by_page["passages"]] == ["p1", "p2"]


def test_the_call_is_never_shown_more_passages_than_per_call():
    pages = [passage(f"p{i}", i, f"{ON} drip irrigation page {i}") for i in range(1, 21)]
    listed = adjudication.reading_list(pages, criterion(), [f"p{i}" for i in range(20, 0, -1)],
                                      per_call=12, criterion_share=8)
    assert len(listed["passages"]) == 12 and listed["whole_text"] is False


def test_two_hash_seeds_build_the_same_plan_and_the_same_list():
    works = [work(f"c{i}", abstract=CANDIDATE) for i in range(6)]
    order = [f"c{i}" for i in range(6)]
    first = adjudication.read_plan(random.Random(1).sample(works, len(works)), order, limit=4)
    second = adjudication.read_plan(random.Random(2).sample(works, len(works)), order, limit=4)
    assert first == second
    pages = [passage(f"p{i}", i, f"{ON} drip irrigation and marketable yield, page {i}") for i in range(1, 21)]
    topic = [f"p{i}" for i in range(20, 10, -1)]
    listed = [adjudication.reading_list(random.Random(seed).sample(pages, len(pages)), criterion(), topic,
                                        per_call=12, criterion_share=8) for seed in (1, 2)]
    assert listed[0] == listed[1]


# ---- task 3, the fake response (the fixture cases live in test_contracts) --------------------
def test_the_fake_response_marks_every_part_present_with_the_first_passages_opening():
    import json
    from pathlib import Path

    from deixis.domain import contracts

    step_input = json.loads((Path(__file__).parent / "fixtures/research/step-inputs.json").read_text())[
        "H_fulltext_adjudication"]
    output = json.loads(valid_response(step_input))
    report = contracts.validate_model_output(step_input, output)
    assert report.ok, [vars(issue) for issue in report.issues]
    opening = step_input["passages"][0]
    assert all(part["label"] == "present" and part["quote"] == opening["text"][:60]
               and part["passage_id"] == opening["passage_id"] for part in output["parts"])
    assert [part["part"] for part in output["parts"]] == [part["name"]
                                                         for part in step_input["adjudication_target"]["parts"]]


# ---- task 4 -----------------------------------------------------------------------------------
def _view(verdict, quotes_verified=True):
    return {"verdict": verdict, "quotes_verified": quotes_verified}


def test_every_combine_row_of_the_rule_table():
    """Identity is not a row `combine` returns. It is written at plan time, without a call (task 5)."""
    include, missed = _view("include"), _view("include", quotes_verified=False)
    assert adjudication.combine(None, include) is None
    assert adjudication.combine(include, None) is None
    assert adjudication.combine(include, _view("not_met")) == "fulltext_runs_disagree"
    assert adjudication.combine(include, include) == "all_parts_verified"
    assert adjudication.combine(include, missed) == "include_quote_unverified"
    assert adjudication.combine(_view("not_met"), _view("not_met")) == "criterion_absent"
    assert adjudication.combine(_view("partial"), _view("partial")) == "part_without_evidence"
    assert adjudication.combine(_view("unclear"), _view("unclear")) == "fulltext_runs_agree_unresolved"
    views = [_view(verdict, flag) for verdict in ("include", "not_met", "partial", "unclear") for flag in (True, False)]
    assert all(adjudication.combine(left, right) != "pdf_identity_unconfirmed" for left in views for right in views)


def test_verdict_reads_the_parts():
    assert adjudication.verdict(["present", "present"]) == "include"
    assert adjudication.verdict(["absent", "unclear"]) == "not_met"
    assert adjudication.verdict(["present", "absent"]) == "partial"
    assert adjudication.verdict(["unclear", "unclear"]) == "unclear"


def test_an_exact_or_normalized_quote_verifies_and_a_fuzzy_one_does_not():
    pages = {1: PAGE}
    assert adjudication.verify(PAGE, pages, 1, 12) == {"verified": True, "page": 1, "kind": "exact"}
    normalized = adjudication.verify(NORMALIZED, pages, 1, 12)
    assert normalized["verified"] is True and normalized["page"] == 1 and normalized["kind"] == "normalized"
    assert adjudication.verify(FUZZY, pages, 1, 12)["verified"] is False


def test_a_quote_shorter_than_the_floor_does_not_verify_even_when_the_page_contains_it():
    page = "SYNTHETIC x is the greenhouse sentence that contains the short quote."
    assert adjudication.verify("SYNTHETIC x", {1: page}, 1, 12)["verified"] is False
    assert len("SYNTHETIC x") == 11


def test_a_quote_on_an_unshown_page_does_not_verify_and_a_shown_other_page_does():
    shown = {1: PAGE}
    other = "SYNTHETIC bakery rounds were counted on a page the model was not shown at all."
    assert adjudication.verify(other, shown, 2, 12)["verified"] is False
    both = {1: PAGE, 3: other}
    found = adjudication.verify(other, both, 1, 12)
    assert found["verified"] is True and found["page"] == 3


def test_a_quote_split_across_two_fragments_of_a_shown_page_verifies(library):
    rid, run_id = research(library)
    svid, _ = one_record(library, rid, run_id)
    asset = db.new_id("ast")
    version = "pymupdf-synthetic"
    hidden = "SYNTHETIC this unshown bakery page is not given to the model at all."
    with db.transaction(library.conn):
        library.conn.execute(
            "INSERT INTO source_assets (id, source_version_id, sha256, byte_size, media_type, storage_path,"
            " retrieved_at, origin, extraction_status, extraction_version, page_count)"
            " VALUES (?, ?, ?, 20, 'application/pdf', 'synthetic.pdf', ?, 'download', 'succeeded', ?, 2)",
            (asset, svid, "a" * 64, db.now(), version),
        )
        library._insert_passage(svid, asset, "pdf_page", 1, None, None, None, version, "SYNTHETIC alpha beta")
        library._insert_passage(svid, asset, "pdf_page", 1, None, None, None, version, "gamma delta bakery")
        library._insert_passage(svid, asset, "pdf_page", 2, None, None, None, version, hidden)
    pages = library.page_texts(svid)
    assert pages[1] == "SYNTHETIC alpha beta gamma delta bakery"
    quote = "alpha beta gamma delta"
    assert len(quote) >= 12
    assert adjudication.verify(quote, {1: pages[1]}, 1, 12)["verified"] is True
    assert adjudication.verify(hidden, {1: pages[1]}, 2, 12)["verified"] is False


def test_a_defective_part_is_read_as_unclear_and_an_unverified_quote_keeps_present():
    parts = [{"name": "irrigation", "definition": ON}, {"name": "yield", "definition": ON}]
    shown = {"psg_SYNTHH0001": {"physical_page": 1, "text": PAGE}}
    pages = {1: PAGE}
    unclear = {"label": "unclear", "quote": "", "quote_verified": False, "passage_id": None, "page": None}

    missing = adjudication.proposals_of(parts, [], shown, pages, 12)
    assert missing["irrigation"] == unclear and missing["yield"] == unclear

    quoteless = adjudication.proposals_of(
        parts, [{"part": "irrigation", "label": "present", "quote": "", "passage_id": "psg_SYNTHH0001"}],
        shown, pages, 12)
    assert quoteless["irrigation"] == unclear

    unseen = adjudication.proposals_of(
        parts, [{"part": "irrigation", "label": "present", "quote": PAGE[:60], "passage_id": "psg_NOTSHOWN1"}],
        shown, pages, 12)
    assert unseen["irrigation"] == unclear

    duplicated = adjudication.proposals_of(parts, [
        {"part": "irrigation", "label": "absent", "quote": "", "passage_id": None},
        {"part": "irrigation", "label": "present", "quote": PAGE[:60], "passage_id": "psg_SYNTHH0001"},
    ], shown, pages, 12)
    assert duplicated["irrigation"] == unclear

    kept = adjudication.proposals_of(
        parts, [{"part": "irrigation", "label": "present", "quote": FUZZY, "passage_id": "psg_SYNTHH0001"}],
        shown, pages, 12)
    assert kept["irrigation"]["label"] == "present" and kept["irrigation"]["quote_verified"] is False
    assert kept["yield"] == unclear
    view = adjudication.run_view(kept)
    assert view["verdict"] == "partial" and view["quotes_verified"] is False


def test_a_stale_code_decision_no_longer_speaks_and_a_stale_human_decision_still_does(library):
    rid, run_id = research(library)
    svid, work_id = one_record(library, rid, run_id)
    decisions = DecisionStore(library)
    decisions.record(rid, svid, "not_read_yet")
    library.revise_scope(rid, library.research(rid)["version"], f"{OFF} under a revised question?", None)
    assert decisions.is_stale(decisions.current(rid, svid, "fulltext"))
    decisions.record(rid, svid, "both_blocks_missing")
    outcome = decisions.work_outcome(rid, work_id)
    assert outcome["stage"] == "abstract" and outcome["reason_code"] == "both_blocks_missing"

    rid_h, run_h = research(library)
    search(library, rid_h, run_h, 0, "openalex", [record(
        "W9", doi="10.1109/synth.bakery.9", title="SYNTHETIC bakery delivery rounds of a small town")])
    svid_h = library.find_source_by_identifier("openalex", "W9")
    work_h = library.source(svid_h)["work_id"]
    decisions.record(rid_h, svid_h, "human_include")
    library.revise_scope(rid_h, library.research(rid_h)["version"], f"{ON} under a revised question?", None)
    assert decisions.is_stale(decisions.current(rid_h, svid_h, "fulltext"))
    decisions.record(rid_h, svid_h, "both_blocks_missing")
    human = decisions.work_outcome(rid_h, work_h)
    assert human["reason_code"] == "human_include" and human["decided_by"] == "human"
