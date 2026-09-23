"""The criterion quota of an `sw` answer run: where its phrases come from and which passages they order (slice 11).

Two halves. The first drives real runs through `create_app` and checks the run's own record: which protocol row an
answer run reads, what a resumed run reads instead, and which run kinds open the step at all. The second calls
`flow._retrieve` on a store built here, because the two quotas are about many sources at once and the arithmetic is
clearer than a whole run would make it.

Questions, records, phrases and PDF text are SYNTHETIC and from two fields. What passes here is workflow behavior:
that the approved phrases reach the passage order and that a `legacy` research keeps the selection it had. It says
nothing about whether those phrases find a passage worth reading — the one measurement behind that covers one topic
and is in D84's limits.
"""

import json
import time
from types import SimpleNamespace

import httpx
from fastapi.testclient import TestClient

from deixis.api.app import create_app
from deixis.config import Settings
from deixis.documents.fetch import FetchResult
from deixis.providers.common import ProviderRecord
from deixis.providers.registry import CONNECTORS
from deixis.storage import db
from deixis.workflow import criterion_passages
from deixis.workflow.flow import MAX_PASSAGES_PER_SOURCE, PDF_PAGES_PER_SOURCE, ResearchFlow
from deixis.workflow.store import Store
from deixis.workflow.views import research_view
from fakes import FakeAdapter
from helpers import make_pdf

QUESTION = "What is the effect of supervised exercise on cancer related fatigue after chemotherapy?"
OTHER_QUESTION = "How does canopy cover affect seedling survival in temperate forests?"
# SYNTHETIC cue phrases of a clinical criterion. None of them is a word of the question, and none of them is in the
# hand-written `FORMULATION_TERMS` list, so what the two quotas each earn stays separable.
PHRASES = ["intention to treat", "randomised controlled trial"]
# A page that carries the approved phrases and no question word, and one that carries the question words instead.
CRITERION_PAGE = "SYNTHETIC an intention to treat analysis of a randomised controlled trial with 120 adults."
TOPIC_PAGE = "SYNTHETIC supervised exercise lowered cancer related fatigue after chemotherapy in this cohort."
# A page from another field, written in the words of the hand-written legacy list, which no approved phrase covers.
FORMULATION_PAGE = "SYNTHETIC we minimize the objective function of the mixed-integer linear program: x <= c."
OFF_PAGE = "SYNTHETIC the bakery delivers bread to the market every morning."
ABSTRACT = "SYNTHETIC supervised exercise after chemotherapy: an abstract."


def body_with(question, phrases, steering=None, criterion="SYNTHETIC the paper must state a model."):
    """A protocol body holding the fields `store.frozen_criterion` reads; the rest of a real body is not needed here."""
    return {"schema": "deixis.protocol.v1", "search_workflow": "sw", "question": question, "steering": steering,
            "inclusion_criterion": criterion,
            "criterion_parts": [{"name": "model", "definition": "SYNTHETIC the paper states its model."}],
            "cue_phrases": None if criterion is None else [{"phrase": p, "part": "model", "runs": [1, 2]} for p in phrases],
            "exclusion_title_words": None if criterion is None else ["survey"],
            "criterion_origin": {"origin": "user", "base_run": 1, "runs_ok": [1, 2],
                                 "dropped_exclusion_title_words": [], "sought_term_in_criterion": True}}


# ---- the run's record: which phrases an answer run reads ----------------------------------------------------

async def fake_fetch(url):
    return FetchResult("ok", data=make_pdf([TOPIC_PAGE]), final_url=url, http_status=200)


def app_for(tmp_path, monkeypatch, workflow="sw", adapter=None):
    for connector in CONNECTORS.values():
        if connector.key_env:
            monkeypatch.delenv(connector.key_env, raising=False)
    monkeypatch.delenv("GEMINI_API_KEY", raising=False)
    monkeypatch.setenv("DEIXIS_SEARCH_WORKFLOW", workflow)
    settings = Settings(data_dir=tmp_path / "data", port=8765, search_workflow=workflow, search_query="code", fulltext_fetch="off")
    return create_app(settings, adapters={"fake": adapter or FakeAdapter()},
                      http_client=httpx.AsyncClient(transport=httpx.MockTransport(lambda r: httpx.Response(404))),
                      fetcher=fake_fetch, extra_hosts=("testserver",), trusted_clients=("testclient",))


def client_of(app):
    client = TestClient(app)
    client.__enter__()
    client.headers["x-deixis-csrf"] = client.get("/api/session").json()["csrf_token"]
    return client


def research_with_pdf(client, question=QUESTION, pages=(CRITERION_PAGE, TOPIC_PAGE)):
    body = {"question": question, "model_connection": "fake", "requested_model": "fake-model", "effort": "quick",
            "source_scope": "attached"}
    rid = client.post("/api/researches", json=body).json()["research"]["id"]
    client.post(f"/api/researches/{rid}/uploads",
                files={"file": ("a.pdf", make_pdf(list(pages)), "application/pdf")})
    return rid


def wait_run(client, rid, run_id, timeout=20):
    deadline = time.time() + timeout
    while time.time() < deadline:
        view = client.get(f"/api/researches/{rid}").json()
        run = next(r for r in view["runs"] if r["id"] == run_id)
        if run["status"] in ("completed", "failed", "paused", "cancelled"):
            return view, run
        time.sleep(0.05)
    raise AssertionError(f"the run did not settle: {run}")


def answer(client, rid):
    run_id = client.post(f"/api/researches/{rid}/runs", json={"kind": "answer"}).json()["id"]
    return (*wait_run(client, rid, run_id), run_id)


def phrase_steps(store, rid):
    """Every criterion-phrase step of this research, oldest first, read without opening one (Lesson C)."""
    return [dict(row) | {"output": json.loads(row["output_json"]) if row["output_json"] else None}
            for row in store.conn.execute(
                "SELECT s.* FROM run_steps s JOIN runs r ON r.id = s.run_id WHERE r.research_id = ?"
                " AND s.operation_key = 'criterion_phrases' ORDER BY s.rowid", (rid,))]


def only_step(store, rid):
    (step,) = phrase_steps(store, rid)
    return step["output"]


def test_an_sw_answer_run_reads_the_phrases_its_research_approved(tmp_path, monkeypatch):
    app = app_for(tmp_path, monkeypatch)
    client = client_of(app)
    try:
        rid = research_with_pdf(client)
        app.state.store.freeze_protocol(rid, 1, body_with(QUESTION, PHRASES))
        view, run, _ = answer(client, rid)
        assert run["status"] == "completed", run
        step = next(s for s in run["steps"] if s["operation_key"] == "criterion_phrases")
    finally:
        client.__exit__(None, None, None)
    assert (step["kind"], step["status"]) == ("code:criterion_phrases", "succeeded")
    assert step["output"] == {"source": "protocol", "reason": None, "protocol_revision": 1,
                              "phrases": sorted(PHRASES), "dropped": []}


def test_a_revised_question_leaves_the_old_phrases_behind(tmp_path, monkeypatch):
    """Lesson A: a protocol row outlives the run that froze it, but it answers only the question it was frozen for."""
    app = app_for(tmp_path, monkeypatch)
    client = client_of(app)
    try:
        rid = research_with_pdf(client)
        app.state.store.freeze_protocol(rid, 1, body_with(QUESTION, PHRASES))
        version = client.get(f"/api/researches/{rid}").json()["research"]["version"]
        revised = client.post(f"/api/researches/{rid}/scope",
                              json={"question": OTHER_QUESTION, "expected_version": version})
        assert revised.status_code == 200, revised.text
        answer(client, rid)
        output = only_step(app.state.store, rid)
    finally:
        client.__exit__(None, None, None)
    assert output == {"source": "none", "reason": "no_criterion", "protocol_revision": None,
                      "phrases": [], "dropped": []}


def test_phrases_frozen_under_another_steering_are_left_behind(tmp_path, monkeypatch):
    """Lesson A: the same question steered elsewhere is another request, and its row does not answer this one."""
    app = app_for(tmp_path, monkeypatch)
    client = client_of(app)
    try:
        rid = research_with_pdf(client)
        app.state.store.freeze_protocol(rid, 1, body_with(QUESTION, PHRASES, steering="SYNTHETIC only trials in adults"))
        answer(client, rid)
        output = only_step(app.state.store, rid)
    finally:
        client.__exit__(None, None, None)
    assert output["source"] == "none" and output["reason"] == "no_criterion" and output["phrases"] == []


def test_a_null_criterion_does_not_hide_an_older_filled_one_of_the_same_question(tmp_path, monkeypatch):
    """A later run that could not reach the model froze a body with no criterion; the filled one behind it is read."""
    app = app_for(tmp_path, monkeypatch)
    client = client_of(app)
    try:
        rid = research_with_pdf(client)
        store = app.state.store
        store.freeze_protocol(rid, 1, body_with(QUESTION, PHRASES))
        store.freeze_protocol(rid, 1, body_with(QUESTION, [], criterion=None), reason="the model was unreachable")
        answer(client, rid)
        output = only_step(store, rid)
    finally:
        client.__exit__(None, None, None)
    assert output["source"] == "protocol" and output["protocol_revision"] == 1
    assert output["phrases"] == sorted(PHRASES)


def test_a_proposal_still_waiting_for_approval_is_not_read(tmp_path, monkeypatch):
    """Phrases come from `protocol_records` alone: what a model proposed is not a criterion until it is frozen."""
    app = app_for(tmp_path, monkeypatch)
    client = client_of(app)
    try:
        rid = research_with_pdf(client)
        store = app.state.store
        proposed = store.create_run(rid, "discovery", {}, None)
        step = store.step(proposed["id"], "criterion", "code:criterion")
        store.finish_step(step["id"], "succeeded", output={
            "origin": "model", "protocol_revision": None, "failures": [],
            "criterion": {"criterion": "SYNTHETIC", "parts": [], "origin": "model", "exclusion_title_words": [],
                          "cue_phrases": [{"phrase": p, "part": None, "runs": [1, 2]} for p in PHRASES]}})
        # The discovery run stopped on the approval card; nothing was frozen, so the answer run reads no phrases.
        store.update_run(proposed["id"], status="paused", pause_reason="awaiting_protocol_approval")
        answer(client, rid)
        output = only_step(store, rid)
    finally:
        client.__exit__(None, None, None)
    assert output == {"source": "none", "reason": "no_criterion", "protocol_revision": None,
                      "phrases": [], "dropped": []}


def test_an_approved_empty_phrase_list_is_a_criterion_with_no_phrases(tmp_path, monkeypatch):
    """The user approved a criterion and removed every phrase. That is an answer, and it is recorded as one."""
    app = app_for(tmp_path, monkeypatch)
    client = client_of(app)
    try:
        rid = research_with_pdf(client)
        app.state.store.freeze_protocol(rid, 1, body_with(QUESTION, []))
        answer(client, rid)
        output = only_step(app.state.store, rid)
    finally:
        client.__exit__(None, None, None)
    assert output == {"source": "protocol", "reason": "no_phrases", "protocol_revision": 1,
                      "phrases": [], "dropped": []}


def test_a_criterion_a_second_discovery_run_changed_is_read_by_the_next_answer_run(tmp_path, monkeypatch):
    """The newer criterion orders the next answer. The answer already given is not made invalid: an order is no evidence."""
    app = app_for(tmp_path, monkeypatch)
    client = client_of(app)
    try:
        rid = research_with_pdf(client)
        store = app.state.store
        store.freeze_protocol(rid, 1, body_with(QUESTION, PHRASES))
        first_view, _, _ = answer(client, rid)
        store.freeze_protocol(rid, 1, body_with(QUESTION, ["blinded outcome assessor"]), reason="the user corrected it")
        second_view, _, _ = answer(client, rid)
        outputs = [step["output"] for step in phrase_steps(store, rid)]
    finally:
        client.__exit__(None, None, None)
    assert [o["phrases"] for o in outputs] == [sorted(PHRASES), ["blinded outcome assessor"]]
    assert [o["protocol_revision"] for o in outputs] == [1, 2]
    # Two answer runs, two steps of their own: the second never looked at the first one's.
    assert len(second_view["answers"]) == 2 and first_view["answers"][0]["id"] in {a["id"] for a in second_view["answers"]}


def test_a_resumed_run_uses_the_phrases_its_step_stored(tmp_path, monkeypatch):
    """The step is frozen like a plan: a protocol frozen between the pause and the resume does not reach this run."""
    holder = {}

    def responder(si):
        from fakes import valid_response
        if si["task_type"] == "grounded_answer" and not holder.get("paused"):
            holder["paused"] = True
            store = holder["app"].state.store
            store.freeze_protocol(holder["rid"], 1, body_with(QUESTION, ["blinded outcome assessor"]),
                                  reason="the user corrected it mid-run")
            store.update_run(si["run_id"], event="run_pause_requested", status="pause_requested",
                             pause_reason="user_requested")
        return valid_response(si)

    holder["app"] = app = app_for(tmp_path, monkeypatch, adapter=FakeAdapter(responder))
    client = client_of(app)
    try:
        holder["rid"] = rid = research_with_pdf(client)
        app.state.store.freeze_protocol(rid, 1, body_with(QUESTION, PHRASES))
        _, run, run_id = answer(client, rid)
        assert (run["status"], run["pause_reason"]) == ("paused", "user_requested")
        client.post(f"/api/runs/{run_id}/resume")
        _, run = wait_run(client, rid, run_id)
        assert run["status"] == "completed", run
        steps = phrase_steps(app.state.store, rid)
    finally:
        client.__exit__(None, None, None)
    (step,) = steps  # one step, opened once, although a newer protocol arrived in between
    assert step["attempt"] == 1 and step["output"]["phrases"] == sorted(PHRASES)
    assert step["output"]["protocol_revision"] == 1


def test_no_other_run_kind_opens_the_step_and_reading_a_run_leaves_none_pending(tmp_path, monkeypatch):
    """Lesson C: `store.step` opens what it reads, so only the answer path that runs the step may call it."""
    app = app_for(tmp_path, monkeypatch)
    client = client_of(app)
    try:
        rid = research_with_pdf(client)
        store = app.state.store
        store.freeze_protocol(rid, 1, body_with(QUESTION, PHRASES))
        collection = client.post(f"/api/researches/{rid}/runs", json={"kind": "pdf_collection"}).json()["id"]
        wait_run(client, rid, collection)
        collection_keys = {s["operation_key"] for s in store.run_steps(collection)}
        retrieval = client.post(f"/api/researches/{rid}/runs", json={"kind": "fulltext_fetch"})
        assert retrieval.status_code < 300, retrieval.text
        _, fetched = wait_run(client, rid, retrieval.json()["id"])
        collection_keys |= {s["operation_key"] for s in store.run_steps(fetched["id"])}
        research_view(store, rid)  # the run view a UI reads must open nothing
        before = phrase_steps(store, rid)
        answer(client, rid)
        research_view(store, rid)
        after = phrase_steps(store, rid)
    finally:
        client.__exit__(None, None, None)
    assert "criterion_phrases" not in collection_keys and before == []
    assert [s["status"] for s in after] == ["succeeded"]


def test_a_legacy_answer_run_opens_no_criterion_phrases_step(tmp_path, monkeypatch):
    app = app_for(tmp_path, monkeypatch, workflow="legacy")
    client = client_of(app)
    try:
        rid = research_with_pdf(client)
        # Even with a protocol carrying phrases, a legacy run is what it was: it never reads them.
        app.state.store.freeze_protocol(rid, 1, body_with(QUESTION, PHRASES))
        _, run, _ = answer(client, rid)
        steps = phrase_steps(app.state.store, rid)
    finally:
        client.__exit__(None, None, None)
    assert run["status"] == "completed" and steps == []


def test_an_sw_answer_opens_the_same_number_of_model_sessions_as_a_legacy_one(tmp_path, monkeypatch):
    """Lesson D: the new step is code, so it spends nothing of the run's budget."""
    calls = {}
    for workflow in ("legacy", "sw"):
        adapter = FakeAdapter()
        app = app_for(tmp_path / workflow, monkeypatch, workflow=workflow, adapter=adapter)
        client = client_of(app)
        try:
            rid = research_with_pdf(client)
            app.state.store.freeze_protocol(rid, 1, body_with(QUESTION, PHRASES))
            _, run, _ = answer(client, rid)
            assert run["status"] == "completed", run
            budget = run["budget"]["max_answer_passages"]
            sent = [len(json.loads(row["payload_json"])["passages"]) for row in app.state.store.conn.execute(
                "SELECT payload_json FROM step_inputs WHERE task_type = 'grounded_answer'")]
        finally:
            client.__exit__(None, None, None)
        calls[workflow] = [(c["task_type"], c["model"]) for c in adapter.calls]
        assert sent and max(sent) <= budget
    assert calls["sw"] == calls["legacy"]


# ---- the two quotas: `_retrieve` on a store built here -------------------------------------------------------

def page_source(store, rid, name, pages, abstract, included=True):
    """One SYNTHETIC included source with an abstract and a PDF whose every page is one passage."""
    record = ProviderRecord(provider_record_id=name, title=f"SYNTHETIC {name}", authors=[], year=None, venue=None,
                            publication_type=None, doi=None, landing_url=None, oa_pdf_url=None, oa_pdf_version=None,
                            version_label=None, abstract=abstract, abstract_origin="provider", identifiers={}, raw={})
    svid, _ = store.upsert_provider_source("known_list", record, None)
    store.add_to_corpus(rid, svid, "search", selection_state="included" if included else "pending",
                        selection_origin="user")
    extraction = SimpleNamespace(status="succeeded", error=None, page_count=len(pages),
                                 pages=[SimpleNamespace(text=text, physical_page=n, printed_label=None)
                                        for n, text in enumerate(pages, 1)])
    store.add_asset_with_pages(svid, f"sha-{name}", 100, f"{name}.pdf", "user_upload", None, f"{name}.pdf",
                               extraction, "test", lambda t: [(0, len(t), t)])
    return svid


def library(tmp_path, workflow="sw", question=QUESTION):
    conn = db.connect(tmp_path / "library.sqlite")
    db.migrate(conn)
    store = Store(conn)
    rid = store.create_research(question, "academic", "quick", ["openalex"], "fake", "fake-model", None,
                                search_workflow=workflow)
    return store, rid


def retrieve(store, rid, included, limit, patterns=None):
    flow = object.__new__(ResearchFlow)
    flow.store = store
    return flow._retrieve(rid, store.scope(rid), included, limit, None, patterns)


def compiled(phrases=PHRASES):
    return criterion_passages.compile_phrases([{"phrase": p} for p in phrases])["patterns"]


def texts(passages):
    return [p["text"] for p in passages]


def test_a_legacy_answer_still_gives_room_to_a_formulation_page(tmp_path):
    """The legacy branch is what it was: the hand-written list still earns a page the question's words do not."""
    store, rid = library(tmp_path, workflow="legacy")
    svid = page_source(store, rid, "one", [TOPIC_PAGE, OFF_PAGE, FORMULATION_PAGE], ABSTRACT)
    assert FORMULATION_PAGE in texts(retrieve(store, rid, [svid], 48))


def test_a_page_holding_an_approved_phrase_and_no_question_word_enters_an_sw_answer(tmp_path):
    store, rid = library(tmp_path)
    svid = page_source(store, rid, "one", [TOPIC_PAGE, OFF_PAGE, CRITERION_PAGE], ABSTRACT)
    assert CRITERION_PAGE in texts(retrieve(store, rid, [svid], 4, compiled()))


def test_without_phrases_the_same_page_does_not_enter_and_the_input_is_the_topic_order(tmp_path):
    """The acceptance condition: an empty list adds nothing, and an sw research never falls back to the legacy list."""
    store, rid = library(tmp_path)
    svid = page_source(store, rid, "one", [TOPIC_PAGE, OFF_PAGE, CRITERION_PAGE], ABSTRACT)
    chosen = texts(retrieve(store, rid, [svid], 4, []))
    assert CRITERION_PAGE not in chosen and TOPIC_PAGE in chosen


def test_a_formulation_page_without_an_approved_phrase_does_not_enter_the_sw_criterion_quota(tmp_path):
    """An sw research is ordered by its own criterion, not by a word list written for one topic (§2 rule 6)."""
    store, rid = library(tmp_path)
    svid = page_source(store, rid, "one", [TOPIC_PAGE, FORMULATION_PAGE, OFF_PAGE, CRITERION_PAGE],
                       ABSTRACT)
    chosen = texts(retrieve(store, rid, [svid], 8, compiled()))
    assert CRITERION_PAGE in chosen and FORMULATION_PAGE not in chosen


def test_the_criterion_quota_fills_in_rounds_so_one_source_does_not_take_it_all(tmp_path):
    """Three sources whose pages all outscore the fourth's would have taken every slot under one global order."""
    store, rid = library(tmp_path)
    limit = 48
    rich = [page_source(store, rid, f"rich{i}", [f"{CRITERION_PAGE} SYNTHETIC page {n}: one more intention to treat row."
                                                 for n in range(MAX_PASSAGES_PER_SOURCE)],
                        ABSTRACT) for i in range(3)]
    weak_page = "SYNTHETIC one intention to treat table is reported."
    thin = page_source(store, rid, "thin", [OFF_PAGE, weak_page], ABSTRACT)
    # The three rich sources can offer 15 pages, more than the whole quota, and every one of them scores higher.
    assert 3 * (MAX_PASSAGES_PER_SOURCE - 1) > limit // criterion_passages.CRITERION_ROOM_DIVISOR
    chosen = retrieve(store, rid, [*rich, thin], limit, compiled())
    assert weak_page in texts([p for p in chosen if p["source_version_id"] == thin])


def test_the_criterion_quota_stays_within_a_quarter_of_the_limit(tmp_path):
    store, rid = library(tmp_path)
    svids = [page_source(store, rid, f"s{i}", [f"{CRITERION_PAGE} SYNTHETIC page {n}." for n in range(6)],
                         ABSTRACT) for i in range(3)]
    limit = 48
    chosen = retrieve(store, rid, svids, limit, compiled())
    criterion_pages = [p for p in chosen if p["kind"] == "pdf_page"]
    # Every page of this fixture is a criterion page, and nothing but the abstracts came from the topic order:
    # the FTS query matches no page, so the quota is the only thing that could have added them.
    assert len(criterion_pages) == limit // criterion_passages.CRITERION_ROOM_DIVISOR
    assert len(chosen) == len(svids) + limit // criterion_passages.CRITERION_ROOM_DIVISOR


def test_no_source_gives_more_than_the_passage_cap(tmp_path):
    store, rid = library(tmp_path)
    svid = page_source(store, rid, "one", [f"{CRITERION_PAGE} SYNTHETIC page {n}." for n in range(10)],
                       ABSTRACT)
    chosen = retrieve(store, rid, [svid], 48, compiled())
    assert len(chosen) == MAX_PASSAGES_PER_SOURCE


def test_a_crowded_selection_that_leaves_room_still_holds_every_source_to_the_passage_cap(tmp_path):
    """Review: the crowded branch and the quota below it run in one call when short sources leave the limit unfilled.

    Seventeen sources count as crowded (17 + 2 x 17 > 48), but sixteen of them hold one page and cannot give a
    second, so the crowded pass ends at 35. The rounds and the topic order then fill the room, and they must count
    the three passages the long source was already given rather than start it again from one.
    """
    store, rid = library(tmp_path)
    limit = 48
    long = page_source(store, rid, "long", [f"{CRITERION_PAGE} SYNTHETIC page {n}." for n in range(12)], ABSTRACT)
    short = [page_source(store, rid, f"short{i}", [OFF_PAGE], f"SYNTHETIC bakery round {i}: an abstract.")
             for i in range(16)]
    assert 17 + PDF_PAGES_PER_SOURCE * 17 > limit
    chosen = retrieve(store, rid, [long, *short], limit, compiled())
    assert len([p for p in chosen if p["source_version_id"] == long]) == MAX_PASSAGES_PER_SOURCE
    assert len(chosen) == MAX_PASSAGES_PER_SOURCE + 2 * len(short)


def test_a_crowded_source_gives_one_topic_page_and_one_criterion_page(tmp_path):
    """D55's crowded case: the count a source contributes does not change, only which pages they are."""
    store, rid = library(tmp_path)
    first = page_source(store, rid, "one", [TOPIC_PAGE, OFF_PAGE, CRITERION_PAGE],
                        ABSTRACT)
    second = page_source(store, rid, "two", [OFF_PAGE, OFF_PAGE], "SYNTHETIC bakery delivery rounds: an abstract.")
    chosen = retrieve(store, rid, [first, second], 3, compiled())
    given = [p for p in chosen if p["source_version_id"] == first]
    assert len(given) == 1 + PDF_PAGES_PER_SOURCE
    assert set(texts(given)) == {ABSTRACT, TOPIC_PAGE, CRITERION_PAGE}


def test_a_crowded_source_without_a_criterion_page_gives_two_topic_pages(tmp_path):
    store, rid = library(tmp_path)
    first = page_source(store, rid, "one", [TOPIC_PAGE, f"{TOPIC_PAGE} SYNTHETIC second.", OFF_PAGE],
                        ABSTRACT)
    second = page_source(store, rid, "two", [OFF_PAGE, OFF_PAGE], "SYNTHETIC bakery delivery rounds: an abstract.")
    chosen = retrieve(store, rid, [first, second], 3, compiled())
    given = texts([p for p in chosen if p["source_version_id"] == first])
    assert len(given) == 1 + PDF_PAGES_PER_SOURCE and OFF_PAGE not in given


def test_a_pdf_another_research_holds_in_the_same_library_does_not_enter(tmp_path):
    """Lesson B: passages are shared rows, phrases are not. Only the included works of this research are scored."""
    store, rid = library(tmp_path)
    mine = page_source(store, rid, "mine", [TOPIC_PAGE, CRITERION_PAGE], ABSTRACT)
    other_rid = store.create_research(OTHER_QUESTION, "academic", "quick", ["openalex"], "fake", "fake-model", None,
                                      search_workflow="sw")
    theirs = page_source(store, other_rid, "theirs",
                         [f"{CRITERION_PAGE} SYNTHETIC a second randomised controlled trial arm."],
                         "SYNTHETIC canopy cover of temperate forests: an abstract.")
    chosen = retrieve(store, rid, [mine], 48, compiled())
    assert {p["source_version_id"] for p in chosen} == {mine} and theirs not in {p["source_version_id"] for p in chosen}


def test_the_same_call_selects_the_same_passages_in_the_same_order(tmp_path):
    store, rid = library(tmp_path)
    svids = [page_source(store, rid, f"s{i}", [TOPIC_PAGE, CRITERION_PAGE, OFF_PAGE],
                         ABSTRACT) for i in range(3)]
    first = [p["id"] for p in retrieve(store, rid, svids, 48, compiled())]
    assert first == [p["id"] for p in retrieve(store, rid, svids, 48, compiled())]
