"""Full-text reading: the plan, the passage list, quote verification and the rule table (slice 12, D85).

Pure tests plus the migration's neighbours that do not start a reading run: the budget, the two new reason codes,
and a legacy research refusing the run. Records are SYNTHETIC and from two fields (greenhouse tomato, a small-town
bakery). Passing shows the rules behave as the slice says. It does not show that a model labels parts correctly,
or that a quote which verifies also supports the label.
"""


import pytest

from deixis.domain.reason_codes import reason
from deixis.storage import db
from deixis.workflow import adjudication
from deixis.workflow.decisions import DecisionStore
from deixis.workflow.store import Store
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
    ("quick", 80, 40),
])
def test_the_read_budget_is_two_calls_for_each_work_the_limit_reaches(effort, calls, works_n):
    assert adjudication.read_budget(effort) == {
        "max_model_calls": calls, "max_provider_requests": 0, "max_fulltext_reads": works_n, "read_rule": "split_v1",
    }


# ---- task 2 -----------------------------------------------------------------------------------


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


@pytest.mark.parametrize("code", ["pdf_identity_unconfirmed"])
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


def test_the_limit_cuts_the_plan_and_drops_nothing():
    works = [work(f"c{i}", abstract=CANDIDATE) for i in range(5)]
    works.append(work("x1", abstract=CANDIDATE, selection=USER_EXCLUDED))
    plan = adjudication.read_plan(works, [f"c{i}" for i in range(5)] + ["x1"], limit=2)
    assert plan["works"] == ["c0", "c1"]
    assert plan["not_reached"] == ["c2", "c3", "c4"]
    assert "x1" not in plan["works"] and "x1" not in plan["not_reached"]


def test_the_call_is_never_shown_more_passages_than_per_call():
    pages = [passage(f"p{i}", i, f"{ON} drip irrigation page {i}") for i in range(1, 21)]
    listed = adjudication.reading_list(pages, criterion(), [f"p{i}" for i in range(20, 0, -1)],
                                      per_call=12, criterion_share=8)
    assert len(listed["passages"]) == 12 and listed["whole_text"] is False


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


@pytest.mark.parametrize("aspect", ["unclear"])
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


@pytest.mark.parametrize(("label", "verified"), [("absent", False), ("present", False)])
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


@pytest.mark.parametrize("code", ["criterion_absent"])
def test_a_protocol_title_withholds_both_an_include_and_an_exclusion(code):
    title, words = PROTOCOL_TITLES[0]
    assert adjudication.with_title(code, title) == ("protocol_title", f"protocol_title:{code}:{words}")
    for plain in PLAIN_TITLES:
        assert adjudication.with_title(code, plain) == (code, None)


# ---- slice 28: the comparator marker and the exclusion guard (D109) --------------------------------------------------

ELEMENTS = [{"role": "comparator", "words": "usual watering", "part": "SYNTHETIC usual watering arm"},
            {"role": "population", "words": "tomato plots", "part": "SYNTHETIC evening watering"}]


def _run(**labels):
    return adjudication.run_view({name: {"label": label, "quote_verified": label == "present"}
                                  for name, label in labels.items()})


@pytest.mark.parametrize("runs", [
    # the comparator the only `absent` part, the others `unclear`
    (_run(a="unclear", comparator="absent"), _run(a="unclear", comparator="absent")),
])
def test_the_guard_withholds_every_all_negative_reading_on_a_comparator_criterion(runs):
    code = adjudication.combine(*runs)
    assert code == "criterion_absent"
    assert adjudication.with_comparator(code, "comparator") == (
        "comparator_exclusion_withheld", "comparator_exclusion_withheld:criterion_absent:comparator")
    assert adjudication.with_comparator(code, None) == ("criterion_absent", None)


# ---- what a reading showed of the extracted text (audit item 3) -----------------------------------

def pages_of(n, per_page=1):
    return [{"id": f"psg_{i}", "kind": "pdf_page", "physical_page": 1 + i // per_page} for i in range(n)]


# ---- split_v1: the second call reads what the first did not see (D76) ---------------------------

def _ids(rows):
    return [p["id"] for p in rows]


def _long(n, cue_every=None):
    """`n` SYNTHETIC pages; with `cue_every`, every such page names drip irrigation (a criterion phrase)."""
    return [passage(f"p{i:02d}", i, f"{ON} {'drip irrigation ' if cue_every and i % cue_every == 0 else ''}page {i}")
            for i in range(1, n + 1)]


def test_forty_parts_give_two_disjoint_lists_and_the_second_takes_the_unseen_criterion_passages_first():
    pages = _long(40, cue_every=3)  # 13 pages name a criterion phrase; the first call takes 8 of them
    lists = adjudication.split_lists(pages, criterion(), [], per_call=12, criterion_share=8)
    first, second = set(_ids(lists["first"])), set(_ids(lists["second"]))
    assert len(first) == len(second) == 12 and not first & second
    cued = {p["id"] for p in pages if "drip irrigation" in p["text"]}
    assert len(cued & first) == 8 and cued - first <= second


def _texts(*rows):
    return {pid: {"text": text, "physical_page": page} for pid, page, text in rows}


A = "SYNTHETIC the greenhouse tomato crop used drip irrigation every morning."
B = "SYNTHETIC the marketable yield was weighed at the packing house each week."
C = "SYNTHETIC the bakery rounds were driven before dawn across the town."


def test_a_splice_across_an_omitted_part_does_not_verify():
    shown = {"a": {"physical_page": 4}, "c": {"physical_page": 4}}
    splice = A[-30:] + " " + C[:30]
    records = [{"part": "irrigation", "label": "present", "quote": splice, "passage_id": "a"}]
    found = adjudication.proposals_of(criterion()["parts"][:1], records, shown, {}, 12,
                                      _texts(("a", 4, A), ("c", 4, C)))
    assert found["irrigation"]["quote_verified"] is False and found["irrigation"]["label"] == "present"


PARTS = [{"name": "irrigation", "definition": "x"}, {"name": "yield", "definition": "y"}]


def _row(label, quote="", verified=False, pid=None, page=None):
    return {"label": label, "quote": quote, "quote_verified": verified, "passage_id": pid, "page": page}


# Call 1 was shown passage a (page 1) and b (page 2); call 2 was shown b and c (page 3).
SHOWN = {1: _texts(("a", 1, A), ("b", 2, B)), 2: _texts(("b", 2, B), ("c", 3, C))}


def test_combine_split_writes_nothing_while_either_call_is_missing():
    rows = {"irrigation": _row("present", A, True, "a", 1), "yield": _row("present", B, True, "b", 2)}
    assert adjudication.combine_split({1: rows, 2: None}, SHOWN, PARTS) is None
    assert adjudication.combine_split({1: None, 2: rows}, SHOWN, PARTS) is None
    assert adjudication.combine_split({1: rows}, SHOWN, PARTS) is None


@pytest.mark.parametrize(("labels", "code"), [
    ((("absent", "absent"), ("absent", "absent")), "criterion_absent"),
    # Per part: absent in one call and unclear in the other is unclear, not absent (legacy read this as two verdicts).
    ((("absent", "absent"), ("unclear", "unclear")), "fulltext_runs_agree_unresolved"),
])
def test_neither_call_present_is_absent_only_when_both_said_absent(labels, code):
    first = {name: _row(label) for name, label in zip(("irrigation", "yield"), labels[0])}
    second = {name: _row(label) for name, label in zip(("irrigation", "yield"), labels[1])}
    assert adjudication.combine_split({1: first, 2: second}, SHOWN, PARTS) == code


def test_a_present_part_with_an_unverified_quote_is_include_quote_unverified():
    first = {"irrigation": _row("present", A, True, "a", 1), "yield": _row("unclear")}
    second = {"irrigation": _row("unclear"), "yield": _row("present", "SYNTHETIC not on any page at all", False, "c")}
    assert adjudication.combine_split({1: first, 2: second}, SHOWN, PARTS) == "include_quote_unverified"
