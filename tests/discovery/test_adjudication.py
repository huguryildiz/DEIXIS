"""Full-text reading: the plan, the passage list, quote verification and the rule table (slice 12, D85).

Pure tests plus the migration's neighbours that do not start a reading run: the budget, the two new reason codes,
and a legacy research refusing the run. Records are SYNTHETIC and from two fields (greenhouse tomato, a small-town
bakery). Passing shows the rules behave as the slice says. It does not show that a model labels parts correctly,
or that a quote which verifies also supports the label.
"""

import random

import pytest

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
    return create_app(Settings(data_dir=tmp_path / "data", port=8765, search_query="code",
                               fulltext_fetch="off", fulltext_adjudication="off"),
                      adapters={"fake": FakeAdapter()}, extra_hosts=("testserver",),
                      trusted_clients=("testclient",), start_worker=False)


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

    step_input = json.loads((Path(__file__).parent.parent / "fixtures/research/step-inputs.json").read_text())[
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


@pytest.mark.parametrize("aspect", ["absent", "unclear", "present"])
def test_aspects_do_not_gate_inclusion_even_with_unverified_aspect_quotes(aspect):
    parts = [{"name": "central concept", "inclusion_role": "core"},
             {"name": "cost", "inclusion_role": "aspect"}]
    proposals = {"central concept": {"label": "present", "quote_verified": True},
                 "cost": {"label": aspect, "quote_verified": False}}
    view = adjudication.run_view(proposals, parts)
    assert adjudication.combine(view, view) == "all_parts_verified"
    # Historical criteria have no roles and retain the all-parts AND.
    legacy = [{"name": p["name"]} for p in parts]
    assert adjudication.combine(adjudication.run_view(proposals, legacy),
                                adjudication.run_view(proposals, legacy)) != "all_parts_verified"


@pytest.mark.parametrize(("label", "verified"), [("absent", False), ("unclear", False), ("present", False)])
def test_each_core_still_requires_two_present_verified_readings(label, verified):
    parts = [{"name": "family A", "inclusion_role": "core"},
             {"name": "family B", "inclusion_role": "core"},
             {"name": "cost", "inclusion_role": "aspect"}]
    proposals = {p["name"]: {"label": "present", "quote_verified": True} for p in parts}
    first = adjudication.run_view(proposals, parts)
    proposals["family B"] = {"label": label, "quote_verified": verified}
    second = adjudication.run_view(proposals, parts)
    assert adjudication.combine(first, second) != "all_parts_verified"
    assert adjudication.combine(second, second) != "all_parts_verified"


def test_no_core_cannot_include_and_comparator_marker_preserves_inclusion_role():
    assert adjudication.run_view({"cost": {"label": "present", "quote_verified": True}},
                                 [{"name": "cost", "inclusion_role": "aspect"}])["verdict"] == "unclear"
    parts = [{"name": "control", "definition": "SYNTHETIC control", "inclusion_role": "core"}]
    marked = adjudication.mark_comparator(parts, [{"role": "comparator", "part": "control"}], ["comparator"])
    assert marked[0]["inclusion_role"] == "core" and marked[0]["role"] == "comparator"


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


# ---- a study-protocol title (slice 26, SW26) ------------------------------------------------------------------------

# SYNTHETIC titles of the shapes the slice 26 plan measured, from more than one field.
PROTOCOL_TITLES = [
    ("Effects of SYNTHETIC evening irrigation on greenhouse tomato yield: a study protocol", "study protocol"),
    ("SYNTHETIC delivery rounds for small-town bakeries: A randomized controlled trial study protocol",
     "study protocol"),
    ("SYNTHETIC drip timing in open fields: protocol for the DRIPS randomized controlled trial",
     "protocol for the DRIPS randomized controlled trial"),
    ("Rationale and design of a SYNTHETIC bakery staffing study", "Rationale and design"),
]
PLAIN_TITLES = [
    "SYNTHETIC evening irrigation and fruit set: per-protocol analysis of a randomized trial",
    "A SYNTHETIC Time-Restricted Watering Protocol for Improving Tomato Yield: A Randomized Controlled Trial",
    "SYNTHETIC entanglement swapping protocol for the quantum Internet",
    "An Energy-Efficient Link Layer Protocol for SYNTHETIC sensor networks",
    "SYNTHETIC bakery opening hours (16/8 protocol) and daily sales",
    "",
    None,
]


@pytest.mark.parametrize(("title", "words"), PROTOCOL_TITLES)
def test_a_title_that_names_a_study_protocol_is_found_with_its_words(title, words):
    assert adjudication.protocol_title(title) == words


@pytest.mark.parametrize("title", PLAIN_TITLES)
def test_a_results_title_or_a_technical_protocol_is_not_a_study_protocol(title):
    assert adjudication.protocol_title(title) is None


@pytest.mark.parametrize("code", ["all_parts_verified", "criterion_absent"])
def test_a_protocol_title_withholds_both_an_include_and_an_exclusion(code):
    title, words = PROTOCOL_TITLES[0]
    assert adjudication.with_title(code, title) == ("protocol_title", f"protocol_title:{code}:{words}")
    for plain in PLAIN_TITLES:
        assert adjudication.with_title(code, plain) == (code, None)


@pytest.mark.parametrize("code", ["part_without_evidence", "fulltext_runs_disagree", "include_quote_unverified",
                                  "fulltext_runs_agree_unresolved", "pdf_identity_unconfirmed", None])
def test_every_other_code_passes_a_protocol_title_through(code):
    for title, _ in PROTOCOL_TITLES:
        assert adjudication.with_title(code, title) == (code, None)


def test_a_single_result_part_absent_in_both_runs_on_a_protocol_title_goes_to_the_queue():
    """Sol r1: with one part, a result part, two `absent` runs would exclude; a protocol title stops that."""
    run = adjudication.run_view({"measured outcome": {"label": "absent", "quote_verified": False}})
    code = adjudication.combine(run, run)
    assert code == "criterion_absent"
    assert adjudication.with_title(code, PROTOCOL_TITLES[1][0])[0] == "protocol_title"
    assert adjudication.with_title(code, PLAIN_TITLES[0]) == ("criterion_absent", None)


def test_the_protocol_title_code_is_a_fresh_queue_code_and_never_an_exclusion(library):
    row = reason("protocol_title")
    assert (row.stage, row.outcome, row.decided_by, row.next_step) == ("fulltext", "unresolved", "code", "human_queue")
    assert "protocol_title" in adjudication.FRESH_MODEL_CODES and "protocol_title" in adjudication.OWNED_CODES
    rid, run_id = research(library)
    svid, work_id = one_record(library, rid, run_id)
    decisions = DecisionStore(library)
    decisions.record(rid, svid, "protocol_title", note="protocol_title:all_parts_verified:study protocol")
    assert decisions.derive_selection(rid, work_id) == "pending"
    assert not adjudication.should_write(decisions.current(rid, svid, "fulltext"), "protocol_title")


# ---- slice 28: the comparator marker and the exclusion guard (D109) --------------------------------------------------

SENT = [{"name": "SYNTHETIC evening watering", "definition": "The plots are watered in the evening."},
        {"name": "SYNTHETIC usual watering arm", "definition": "The comparison plots are watered as usual."},
        {"name": "SYNTHETIC fruit set", "definition": "Fruit set is reported."}]
ELEMENTS = [{"role": "comparator", "words": "usual watering", "part": "SYNTHETIC usual watering arm"},
            {"role": "population", "words": "tomato plots", "part": "SYNTHETIC evening watering"}]


def test_the_marker_marks_exactly_the_part_the_comparator_element_names():
    marked = adjudication.mark_comparator(SENT, ELEMENTS, ["comparator", "population"])
    assert marked == [SENT[0], SENT[1] | {"role": "comparator"}, SENT[2]]
    assert SENT[1] == {"name": "SYNTHETIC usual watering arm", "definition": "The comparison plots are watered as usual."}
    assert adjudication.comparator_part(marked) == "SYNTHETIC usual watering arm"


@pytest.mark.parametrize(("elements", "required"), [
    (ELEMENTS, ["population"]),  # the role is not required
    (ELEMENTS, []),
    ([], ["comparator"]),  # no elements
    ([{"role": "comparator", "words": "usual watering", "part": "SYNTHETIC not sent"}], ["comparator"]),
])
def test_the_marker_leaves_every_part_as_it_was_otherwise(elements, required):
    marked = adjudication.mark_comparator(SENT, elements, required)
    assert marked == SENT
    assert adjudication.comparator_part(marked) is None


def _run(**labels):
    return adjudication.run_view({name: {"label": label, "quote_verified": label == "present"}
                                  for name, label in labels.items()})


@pytest.mark.parametrize("runs", [
    # the comparator the only `absent` part, the others `unclear`
    (_run(a="unclear", comparator="absent"), _run(a="unclear", comparator="absent")),
    # Sol r1: another part `absent` in both runs, and the comparator too
    (_run(a="absent", comparator="absent"), _run(a="absent", comparator="absent")),
    # the comparator `unclear` in both runs while another part is `absent`
    (_run(a="absent", comparator="unclear"), _run(a="absent", comparator="unclear")),
])
def test_the_guard_withholds_every_all_negative_reading_on_a_comparator_criterion(runs):
    code = adjudication.combine(*runs)
    assert code == "criterion_absent"
    assert adjudication.with_comparator(code, "comparator") == (
        "comparator_exclusion_withheld", "comparator_exclusion_withheld:criterion_absent:comparator")
    assert adjudication.with_comparator(code, None) == ("criterion_absent", None)


@pytest.mark.parametrize("code", ["all_parts_verified", "part_without_evidence", "fulltext_runs_disagree",
                                  "include_quote_unverified", "fulltext_runs_agree_unresolved",
                                  "pdf_identity_unconfirmed", None])
def test_the_guard_passes_every_other_code_through(code):
    assert adjudication.with_comparator(code, "comparator") == (code, None)
    assert adjudication.with_comparator(code, None) == (code, None)


def test_a_protocol_title_does_not_undo_the_guard_and_still_withholds_an_include():
    title = PROTOCOL_TITLES[0][0]
    code, note = adjudication.with_comparator("criterion_absent", "comparator")
    assert adjudication.with_title(code, title) == ("comparator_exclusion_withheld", None)
    assert note == "comparator_exclusion_withheld:criterion_absent:comparator"
    code, note = adjudication.with_comparator("all_parts_verified", "comparator")
    assert (code, note) == ("all_parts_verified", None)
    assert adjudication.with_title(code, title)[0] == "protocol_title"


def test_the_withheld_exclusion_is_a_fresh_queue_code_and_never_an_exclusion(library):
    row = reason("comparator_exclusion_withheld")
    assert (row.stage, row.outcome, row.decided_by, row.next_step) == ("fulltext", "unresolved", "code", "human_queue")
    assert "comparator_exclusion_withheld" in adjudication.FRESH_MODEL_CODES
    assert "comparator_exclusion_withheld" in adjudication.OWNED_CODES
    rid, run_id = research(library)
    svid, work_id = one_record(library, rid, run_id)
    decisions = DecisionStore(library)
    decisions.record(rid, svid, "comparator_exclusion_withheld",
                     note="comparator_exclusion_withheld:criterion_absent:comparator")
    assert decisions.derive_selection(rid, work_id) == "pending"
    assert not adjudication.should_write(decisions.current(rid, svid, "fulltext"), "comparator_exclusion_withheld")


@pytest.mark.parametrize("named", ["synthetic usual watering arm", "SYNTHETIC  Usual Watering Arm.", "(synthetic usual watering arm)"])
def test_the_marker_compares_part_names_as_the_criterion_check_does(named):
    """Sol code r1: the criterion check accepts an element whose part differs by case, spacing or edge punctuation, so
    the marker must find that part too, or its criterion would keep D85's automatic exclusion."""
    elements = [{"role": "comparator", "words": "usual watering", "part": named}]
    marked = adjudication.mark_comparator(SENT, elements, ["comparator"])
    assert marked == [SENT[0], SENT[1] | {"role": "comparator"}, SENT[2]]
