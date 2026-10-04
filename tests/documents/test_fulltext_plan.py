"""The retrieval plan, the result table and the identity check of the full-text stage (slice 10, SW10, D83).

Pure tests: no database, no network, no model. What is checked here is the rule — which works a retrieval run
fetches and in which order, what one attempt settles on, and whether a downloaded file names the work it was asked
for. The records are SYNTHETIC and from two fields; passing shows the rule behaves as the slice says, not that a
retrieval run finds many papers.
"""

import pytest

from deixis.documents import identity
from deixis.workflow import fulltext

# Two fields: a greenhouse-irrigation question, and a bakery-logistics record that answers nothing.
ON_TITLE = "SYNTHETIC irrigation scheduling in greenhouse tomato production"
OFF_TITLE = "SYNTHETIC bakery delivery rounds of a small town"


def decision(code, decided_by="code", stale=False):
    return {"reason_code": code, "decided_by": decided_by, "stale": stale}


def work(head, *, abstract=None, fulltext_code=None, selection=None, has_text=False, others=(), work_id=None):
    """One work of the plan: its head, whatever other versions it has, and the decisions they carry."""
    versions = [{"id": head, "has_text": has_text, "abstract": abstract, "fulltext": fulltext_code}]
    versions += [dict(other) for other in others]
    return {"work_id": work_id or f"wrk_{head}", "head": head, "versions": versions, "selection": selection}


CANDIDATE = decision("runs_agree_candidate", "model_agreement")
UNRESOLVED_HERE = decision("abstract_not_found")           # next step: fulltext_fetch
UNRESOLVED_MODEL = decision("abstract_not_read")           # next step: abstract_model
OUT_OF_SCOPE = decision("both_blocks_missing")
USER_INCLUDED = {"state": "included", "origin": "user"}
USER_EXCLUDED = {"state": "excluded", "origin": "user"}


def test_the_three_groups_are_fetched_in_order_and_ranked_inside_each_group():
    """The user's own works first, then code's candidates, then the unresolved works routed here (SW10.1)."""
    works = [
        work("u1", abstract=OUT_OF_SCOPE, selection=USER_INCLUDED),
        work("c1", abstract=CANDIDATE),
        work("c2", abstract=CANDIDATE),
        work("r1", abstract=UNRESOLVED_HERE),
    ]
    # The ranking put c2 in front of c1; the groups still come before the order inside them.
    plan = fulltext.fetch_plan(works, ["r1", "c2", "c1", "u1"], limit=10)
    assert plan["works"] == ["u1", "c2", "c1", "r1"]
    assert plan["not_reached"] == [] and plan["already_text"] == []


def test_a_work_the_ranking_did_not_place_goes_last_in_its_own_group_by_identifier():
    works = [work("c9", abstract=CANDIDATE), work("c1", abstract=CANDIDATE), work("c5", abstract=CANDIDATE)]
    assert fulltext.fetch_plan(works, ["c5"], limit=10)["works"] == ["c5", "c1", "c9"]


@pytest.mark.parametrize("skipped", [
    work("m1", abstract=UNRESOLVED_MODEL),                      # the model has not read this abstract yet
    work("l1", abstract=decision("no_abstract")),               # slice 05 routed it to the abstract lookup
    work("s1", abstract=decision("survey_title_word")),         # routed to the seed pool
    work("o1", abstract=OUT_OF_SCOPE),                          # closed on its abstract
    work("n1"),                                                 # no abstract decision at all
    work("x1", abstract=CANDIDATE, selection=USER_EXCLUDED),    # the user excluded it
    work("h1", abstract=CANDIDATE, fulltext_code=decision("human_pdf_wrong", "human")),
])
def test_a_work_outside_the_three_groups_is_not_fetched(skipped):
    assert fulltext.fetch_plan([skipped], [], limit=10) == {"works": [], "not_reached": [], "already_text": []}


def test_a_work_whose_abstract_was_read_by_the_model_and_left_open_is_fetched():
    """`runs_agree_unresolved` says only the full text can decide it, so this run is where it goes (SW11.4)."""
    open_work = work("q1", abstract=decision("runs_agree_unresolved", "model_agreement"))
    assert fulltext.fetch_plan([open_work], [], limit=10)["works"] == ["q1"]


def test_a_work_with_text_on_any_version_is_not_fetched_but_gets_its_code():
    """A user's upload, or a PDF an earlier run retrieved, is already text; nothing is requested for it."""
    preprint = {"id": "p1", "has_text": True, "abstract": None, "fulltext": None}
    plan = fulltext.fetch_plan([work("w1", abstract=CANDIDATE, others=[preprint])], [], limit=10)
    assert plan["already_text"] == ["w1"] and plan["works"] == []


def test_a_fresh_code_of_this_stage_is_not_planned_again_but_a_stale_one_is():
    """"The next run continues where the first stopped": the same links are not requested a second time."""
    for code in fulltext.OWNED_CODES:
        fresh = work("f1", abstract=CANDIDATE, fulltext_code=decision(code))
        stale = work("s1", abstract=CANDIDATE, fulltext_code=decision(code, stale=True))
        assert fulltext.fetch_plan([fresh], [], limit=10)["works"] == []
        assert fulltext.fetch_plan([stale], [], limit=10)["works"] == ["s1"]


def test_a_fresh_code_this_stage_does_not_own_leaves_the_work_to_its_own_stage():
    """A work slice 12 has read, or the user has judged, is not re-planned by the code that only fetches."""
    read = work("v1", abstract=CANDIDATE, fulltext_code=decision("all_parts_verified", "model_agreement"))
    assert fulltext.fetch_plan([read], [], limit=10)["works"] == ["v1"]  # it has no text, so it is fetched again


def test_the_limit_cuts_the_list_and_drops_no_work():
    works = [work(f"c{n}", abstract=CANDIDATE) for n in range(6)] + [work("t1", abstract=CANDIDATE, has_text=True)]
    plan = fulltext.fetch_plan(works, [f"c{n}" for n in range(6)], limit=2)
    assert plan["works"] == ["c0", "c1"]
    assert plan["not_reached"] == ["c2", "c3", "c4", "c5"]
    assert set(plan["works"]) | set(plan["not_reached"]) | set(plan["already_text"]) == {w["head"] for w in works}
    assert not set(plan["works"]) & set(plan["not_reached"])


def test_a_later_run_takes_the_works_the_first_one_did_not_reach():
    works = [work(f"c{n}", abstract=CANDIDATE) for n in range(4)]
    order = [f"c{n}" for n in range(4)]
    first = fulltext.fetch_plan(works, order, limit=2)
    # What the first run fetched carries a fresh code now; what it did not reach carries none.
    after = [work(head, abstract=CANDIDATE, fulltext_code=decision("no_fulltext") if head in first["works"] else None)
             for head in order]
    assert fulltext.fetch_plan(after, order, limit=2)["works"] == first["not_reached"]


def test_a_work_is_a_candidate_when_any_of_its_versions_is_one():
    """`work_outcome`'s rule: an abstract decision on one version never drops a work another version keeps open."""
    other = {"id": "b2", "has_text": False, "abstract": OUT_OF_SCOPE, "fulltext": None}
    assert fulltext.fetch_plan([work("b1", abstract=CANDIDATE, others=[other])], [], limit=10)["works"] == ["b1"]
    closed = {"id": "d2", "has_text": False, "abstract": OUT_OF_SCOPE, "fulltext": None}
    assert fulltext.fetch_plan([work("d1", abstract=OUT_OF_SCOPE, others=[closed])], [], limit=10)["works"] == []


@pytest.mark.parametrize("attempt,code", [
    ({"has_text": True, "has_asset": True, "unanswered": 0}, "not_read_yet"),
    ({"has_text": True, "has_asset": True, "unanswered": 3}, "not_read_yet"),
    ({"has_text": False, "has_asset": True, "unanswered": 0}, "text_unreadable"),
    ({"has_text": False, "has_asset": False, "unanswered": 0}, "no_fulltext"),
    ({"has_text": False, "has_asset": False, "unanswered": 1}, None),
])
def test_the_result_table_of_one_attempt(attempt, code):
    assert fulltext.settled_code(attempt) == code


def test_every_code_this_stage_writes_leaves_the_work_unresolved():
    """Nothing is included or excluded by a retrieval run (SW1.2): all three codes derive to `pending`."""
    from deixis.domain.reason_codes import reason
    from deixis.workflow.decisions import SELECTION_STATE

    for code in fulltext.OWNED_CODES:
        assert reason(code).stage == "fulltext" and reason(code).outcome == "unresolved"
        assert SELECTION_STATE[reason(code).outcome] == "pending"


def test_the_budget_of_a_retrieval_run_calls_no_model_and_sends_no_search():
    from deixis.domain.rules import FULLTEXT_WORK_LIMIT

    from deixis.domain.rules import CHAIN_PLAN_ROOM

    for effort, limit in FULLTEXT_WORK_LIMIT.items():
        assert fulltext.fetch_budget(effort) == {"max_model_calls": 0, "max_provider_requests": 0,
                                                 "max_fulltext_works": limit, "chain_room": CHAIN_PLAN_ROOM[effort]}
    assert [FULLTEXT_WORK_LIMIT[e] for e in ("quick", "standard", "detailed")] == [80, 100, 300]  # quick was 40 before D94
    # The chain's own room sits on top of the keyword limit (D95): 80 + 20, 100 + 25, 300 + 25.
    assert [fulltext.fetch_budget(e)["max_fulltext_works"] + fulltext.fetch_budget(e)["chain_room"]
            for e in ("quick", "standard", "detailed")] == [92, 112, 312]


# ---- the chain group (slice 15, D95) --------------------------------------------------------------

def chained(head, **fields):
    return work(head, **fields) | {"chained": True}


def test_the_chain_group_comes_last_with_its_own_room():
    works = [work("c1", abstract=CANDIDATE), work("c2", abstract=CANDIDATE), work("r1", abstract=UNRESOLVED_HERE),
             chained("x1", abstract=CANDIDATE), chained("x2", abstract=UNRESOLVED_HERE), chained("x3", abstract=CANDIDATE),
             chained("x4", abstract=UNRESOLVED_MODEL),                  # not read yet: not fetched, as a keyword work
             chained("x5", abstract=OUT_OF_SCOPE, selection=USER_INCLUDED)]  # the user's own stays the user's
    plan = fulltext.fetch_plan(works, ["r1", "c2", "c1"], limit=2, chain_order=["x3", "x2", "x1"], chain_room=2)
    assert plan["works"] == ["x5", "c2", "x3", "x2"]
    assert plan["not_reached"] == ["c1", "r1", "x1"]
    assert [fulltext.group_of(w) for w in works] == ["candidate", "candidate", "unresolved", "chain", "chain", "chain",
                                                     None, "user"]
    # Room the chain leaves unused is not given to a keyword work, and a keyword work never takes the chain's.
    alone = fulltext.fetch_plan(works[:3], ["r1", "c2", "c1"], limit=2, chain_order=[], chain_room=20)
    assert alone["works"] == ["c2", "c1"] and alone["not_reached"] == ["r1"]
    # Without room the chain group plans nothing, which is what a run queued before D95 gets.
    assert fulltext.fetch_plan(works, ["r1", "c2", "c1"], limit=2)["works"] == ["x5", "c2"]


def test_the_first_three_groups_are_the_same_with_and_without_chained_works():
    keyword = [work(f"c{n}", abstract=CANDIDATE) for n in range(6)] + [work("r1", abstract=UNRESOLVED_HERE),
                                                                       work("u1", selection=USER_INCLUDED)]
    extra = [chained(f"x{n}", abstract=CANDIDATE if n % 2 else UNRESOLVED_HERE) for n in range(5)]
    order = ["c3", "r1", "c1", "c5", "c0"]
    for limit in (2, 4, 20):
        without = fulltext.fetch_plan(keyword, order, limit)
        with_chain = fulltext.fetch_plan(keyword + extra, order, limit, [f"x{n}" for n in range(5)], 3)
        kept = {w["head"] for w in keyword}
        assert [h for h in with_chain["works"] if h in kept] == without["works"]
        assert [h for h in with_chain["not_reached"] if h in kept] == without["not_reached"]
        assert with_chain["works"][len(without["works"]):] == ["x0", "x1", "x2"]


def test_a_user_started_retrieval_run_gets_the_same_chain_room(tmp_path, monkeypatch):
    from fastapi.testclient import TestClient
    from test_adjudication import _app

    app = _app(tmp_path, monkeypatch, "sw")
    with TestClient(app) as client:
        client.headers["x-deixis-csrf"] = client.get("/api/session").json()["csrf_token"]
        created = client.post("/api/researches", json={
            "question": "SYNTHETIC: drip irrigation and marketable yield of greenhouse tomato, beside a bakery.",
            "model_connection": "fake", "requested_model": "fake-model", "effort": "standard"})
        rid = created.json()["research"]["id"]
        started = client.post(f"/api/researches/{rid}/runs", json={"kind": "fulltext_fetch"})
    assert started.status_code == 202, started.text
    assert started.json()["budget"] == fulltext.fetch_budget("standard") and started.json()["budget"]["chain_room"] == 12


# ---- the identity check (Task 3) ---------------------------------------------------------------

VERSIONS = [{"doi": "10.1/synth.42", "title": ON_TITLE}, {"doi": "10.48550/arxiv.2601.00042", "title": ON_TITLE}]


@pytest.mark.parametrize("text,result", [
    ("SYNTHETIC preprint\nhttps://doi.org/10.1/synth.42\nbody", "doi"),
    ("SYNTHETIC preprint\narXiv:2601.00042v2\nbody", "doi"),
    (f"{ON_TITLE}\nby two SYNTHETIC authors", "title"),
    (f"{OFF_TITLE}\n10.9/other.1", "unconfirmed"),
    ("", "unconfirmed"),
])
def test_the_identity_check_reads_the_head_of_the_text(text, result):
    assert identity.check(text, VERSIONS) == result


def test_a_sibling_version_confirms_the_work():
    """A published record's file may carry only the preprint's identifier, and the other way round (D46, D48)."""
    published = [{"doi": "10.1/synth.42", "title": ON_TITLE}]
    assert identity.check("arXiv:2601.00042", published) == "unconfirmed"
    assert identity.check("arXiv:2601.00042", VERSIONS) == "doi"


def test_a_title_shorter_than_four_words_does_not_confirm_anything():
    assert identity.check("SYNTHETIC drip lines\nbody", [{"doi": None, "title": "SYNTHETIC drip lines"}]) == "unconfirmed"


def test_the_identity_check_reads_no_further_than_the_first_pages():
    """A DOI quoted in a reference list is not this paper naming itself."""
    buried = "x " * identity.MATCH_TEXT_CHARS + "10.1/synth.42"
    assert identity.check(buried, VERSIONS) == "unconfirmed"
