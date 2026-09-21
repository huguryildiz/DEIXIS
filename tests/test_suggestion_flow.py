"""The user asks a model for other names of the search terms, from the approval card (slice 08c, SW2.5).

Driven through the API with a scripted model and mocked OpenAlex. What is checked is workflow behavior: that no
model is asked until the route is called, that nothing the model proposed is searched unless the user adds it, that
an added proposal's count is not asked a second time, that the `model` origin is derived on the server, and that a
run which never asked keeps the body it had. Questions, terms and proposals are SYNTHETIC and from more than one
field; no live model was called anywhere in this slice, so nothing here says whether a proposed name is really
another name for its anchor.
"""

import json
from dataclasses import replace

import httpx

from deixis.models.adapter import ModelStepResult
from deixis.providers.registry import CONNECTORS
from fakes import FakeAdapter, envelope
from test_approval_flow import (OTHER_QUESTION, app_for, approval_of, approve, bodies, client_of, proposing,
                                settled, steps_of)
from test_expansion_flow import ACCEPTED, PAGE, Field
from test_vocabulary_flow import CountingOpenAlex, QUESTION, start, store_at, wait

# SYNTHETIC names the scripted model proposes. The second one is held by no record, so its count drops it.
KEPT = "synthetic sleep schedule"
UNHELD = "synthetic unheld name"


class Counts(CountingOpenAlex):
    """`CountingOpenAlex` that answers zero for named phrases, so a proposal can drop on its own count."""

    def __init__(self, zero=(UNHELD,)):
        super().__init__()
        self.zero = {f'"{phrase}"' for phrase in zero}

    def __call__(self, request):
        params = request.url.params
        query = params.get("search.title_and_abstract")
        if query in self.zero and params.get("per_page") == "1" and params.get("select") == "id":
            self.counts.append(query)
            return httpx.Response(200, json={"meta": {"count": 0}, "results": []})
        return super().__call__(request)


class Table(dict):
    """Counts for the expansion fixture: every phrase is held, except the one this slice needs unheld.

    The accepted second-round phrase keeps the two numbers `test_expansion_flow` uses, so the second round opens
    here for the same reason it opens there.
    """

    def get(self, query, default=None):
        if query == f'"{UNHELD}"':
            return 0
        return 100 if query == f'"{ACCEPTED}"' else 40


def suggesting(names=(KEPT, UNHELD), down=False, criterion_down=None):
    """The criterion-proposing model of slice 08a, with a term-suggestion answer of this slice's own.

    It repeats one phrase the proposal already holds on purpose: such a proposal is valid output that code drops.
    `criterion_down` is a one-item list the test can flip, so one adapter can be the connection that was down when
    the first run proposed and up when the second one did.
    """
    base = proposing().responder

    def responder(si):
        if si["task_type"] != "term_suggestions":
            return base(si)
        anchor = si["suggestion_target"]["phrases"][0]["phrase"]
        terms = [{"phrase": phrase, "synonym_of": anchor} for phrase in names]
        terms.append({"phrase": anchor, "synonym_of": anchor})
        return json.dumps(envelope(si, "deixis.term_suggestions.v1") | {"terms": terms})

    def fail(si):
        if down and si["task_type"] == "term_suggestions":
            return ModelStepResult("failed", error="SYNTHETIC suggestion connection is down")
        if criterion_down and criterion_down[0] and si["task_type"] == "criterion_proposal":
            return ModelStepResult("failed", error="SYNTHETIC criterion connection is down")
        return None

    return FakeAdapter(responder, fail=fail)


def suggest(client, run_id, expect=200):
    response = client.post(f"/api/runs/{run_id}/term-suggestions")
    assert response.status_code == expect, response.text
    return response


def asked(client, rid, run_id):
    """Ask for suggestions and let the run come back to the card."""
    suggest(client, run_id)
    return wait(client, rid, run_id)


def suggestion_steps(run):
    return [s for s in run["steps"] if s["kind"] in ("code:term_suggestions", "model:term_suggestions")]


def rows_of(view, run_id):
    return approval_of(view, run_id)["suggestions"]


def added(phrase, block="setting"):
    return [{"op": "add", "phrase": phrase, "block": block}]


def anchor_of(tmp_path, run_id):
    """The first searched phrase of the stored proposal: the one the scripted model names."""
    vocabulary = store_at(tmp_path).approval_step(run_id)["output"]["proposal"]["vocabulary"]
    return vocabulary["terms"][0]["phrase"]


def model_calls(adapter, task="term_suggestions"):
    return len([si for si in adapter.calls if si["task_type"] == task])


def sent(tmp_path, rid):
    return [row["query_text"] for row in store_at(tmp_path).conn.execute(
        "SELECT query_text FROM search_runs WHERE research_id = ?", (rid,))]


def digests(tmp_path, rid):
    return [row["body_sha256"] for row in store_at(tmp_path).conn.execute(
        "SELECT body_sha256 FROM protocol_records WHERE research_id = ? ORDER BY protocol_revision", (rid,))]


# What slice 08a's approval record holds. A run that asked for nothing gains no field from this slice.
EIGHT_A_APPROVAL = {"mode", "approved_by", "edited", "proposal_hash", "term_edits", "criterion_edited",
                    "exclusion_word_in_question"}


# ---- a run that never asks is the run of slice 08a -------------------------------------------------------

def test_a_run_that_never_asked_keeps_its_protocol_body_and_opens_no_step(tmp_path, monkeypatch):
    client = client_of(app_for(tmp_path, monkeypatch, Counts(), suggesting()))
    try:
        rid, run_id = start(client, QUESTION)
        wait(client, rid, run_id)
        approve(client, run_id)
        view, run = wait(client, rid, run_id)
    finally:
        client.__exit__(None, None, None)
    body = bodies(tmp_path, rid)[0]
    assert set(body["approval"]) == EIGHT_A_APPROVAL, body["approval"]
    assert not suggestion_steps(run), steps_of(run)
    # Nothing was asked and nothing is on record; the button is closed only because the protocol is now frozen.
    assert rows_of(view, run_id) == {"status": "none", "available": False, "unavailable_reason": None,
                                     "failure": None, "carried": False, "terms": []}


def test_two_runs_of_the_same_question_that_never_ask_freeze_the_same_digest(tmp_path, monkeypatch):
    """The body of a run that asked for nothing is a function of its scope alone, as it was before this slice."""
    client = client_of(app_for(tmp_path, monkeypatch, Counts(), suggesting()))
    try:
        frozen = []
        for _ in range(2):
            rid, run_id = start(client, QUESTION)
            wait(client, rid, run_id)
            approve(client, run_id)
            wait(client, rid, run_id)
            frozen.append(digests(tmp_path, rid))
    finally:
        client.__exit__(None, None, None)
    assert frozen[0] and frozen[0] == frozen[1]


def test_an_unattended_run_opens_no_suggestion_step_and_refuses_the_request(tmp_path, monkeypatch):
    client = client_of(app_for(tmp_path, monkeypatch, Counts(), suggesting(), approval="as_proposed"))
    try:
        rid, run_id = start(client, QUESTION)
        _, run = wait(client, rid, run_id)
        assert not suggestion_steps(run), steps_of(run)
        suggest(client, run_id, expect=409)
    finally:
        client.__exit__(None, None, None)


def test_a_legacy_research_has_no_card_and_no_suggestion_route(tmp_path, monkeypatch):
    client = client_of(app_for(tmp_path, monkeypatch, Counts(), suggesting(), workflow="legacy"))
    try:
        rid, run_id = start(client, QUESTION)
        view, run = wait(client, rid, run_id)
        assert not suggestion_steps(run), steps_of(run)
        assert approval_of(view, run_id) is None
        suggest(client, run_id, expect=409)
    finally:
        client.__exit__(None, None, None)


# ---- the request itself ----------------------------------------------------------------------------------

def test_a_requested_suggestion_stops_the_run_at_the_card_again_and_searches_nothing(tmp_path, monkeypatch):
    openalex = Counts()
    client = client_of(app_for(tmp_path, monkeypatch, openalex, suggesting()))
    try:
        rid, run_id = start(client, QUESTION)
        waiting, _ = wait(client, rid, run_id)
        # The card of a run waiting for its approval offers the button and nothing has been proposed yet.
        assert rows_of(waiting, run_id) == {"status": "none", "available": True, "unavailable_reason": None,
                                            "failure": None, "carried": False, "terms": []}
        before = len(openalex.counts)
        view, run = asked(client, rid, run_id)
    finally:
        client.__exit__(None, None, None)
    assert (run["status"], run["pause_reason"]) == ("paused", "protocol_approval_needed"), run
    assert not [s for s in run["steps"] if s["kind"].startswith("provider_search")], steps_of(run)
    assert not openalex.searches and view["counts"]["unique"] == 0
    assert bodies(tmp_path, rid) == []
    # One count request per proposal that survived the code screen: the kept one and the unheld one.
    assert openalex.counts[before:] == [f'"{KEPT}"', f'"{UNHELD}"']
    anchor = anchor_of(tmp_path, run_id)
    suggestions = rows_of(view, run_id)
    assert suggestions["status"] == "ready" and suggestions["carried"] is False
    assert suggestions["available"] is False and suggestions["unavailable_reason"] == "already_suggested"
    assert {(row["phrase"], row["dropped"], row["phrase_count"]) for row in suggestions["terms"]} == {
        (KEPT, None, 40), (UNHELD, "zero_results", 0), (anchor, "already_present", None)}
    # Canonical order: the anchor's place in the vocabulary, then the phrase. Every row shares one anchor here.
    assert [row["phrase"] for row in suggestions["terms"]] == sorted(row["phrase"] for row in suggestions["terms"])
    assert {row["block"] for row in suggestions["terms"]} == {"setting"}
    assert {row["synonym_of"] for row in suggestions["terms"]} == {anchor}


def test_the_two_step_keys_are_the_ones_the_slice_names(tmp_path, monkeypatch):
    client = client_of(app_for(tmp_path, monkeypatch, Counts(), suggesting()))
    try:
        rid, run_id = start(client, QUESTION)
        wait(client, rid, run_id)
        _, run = asked(client, rid, run_id)
    finally:
        client.__exit__(None, None, None)
    assert {s["operation_key"]: s["kind"] for s in suggestion_steps(run)} == {
        "term_suggestions:1": "code:term_suggestions", "term_suggestion:1": "model:term_suggestions"}


# ---- nothing enters the query unless the user adds it ----------------------------------------------------

def test_a_user_who_adds_none_of_the_proposals_searches_the_proposal_s_queries_byte_for_byte(tmp_path, monkeypatch):
    client = client_of(app_for(tmp_path, monkeypatch, Counts(), suggesting()))
    try:
        rid, run_id = start(client, QUESTION)
        wait(client, rid, run_id)
        asked(client, rid, run_id)
        approve(client, run_id)
        wait(client, rid, run_id)
    finally:
        client.__exit__(None, None, None)
    stored = store_at(tmp_path).approval_step(run_id)["output"]
    assert stored["approved"]["queries"] == stored["proposal"]["queries"]
    queries = sent(tmp_path, rid)
    assert set(queries) == {q["query_text"] for q in stored["proposal"]["queries"]}
    assert all(KEPT not in text and UNHELD not in text for text in queries), queries
    body = bodies(tmp_path, rid)[0]
    record = body["approval"]["suggestions"]
    assert record == {"requests": 1, "proposed": 3, "dropped": 2, "accepted": 0,
                      "step_input_id": record["step_input_id"], "carried_from_step_id": None}
    assert record["step_input_id"] is not None
    assert all(term["origin"] != "model" for term in body["vocabulary"])


def test_an_added_proposal_enters_the_query_carries_the_model_origin_and_is_not_counted_again(tmp_path, monkeypatch):
    openalex = Counts()
    client = client_of(app_for(tmp_path, monkeypatch, openalex, suggesting()))
    try:
        rid, run_id = start(client, QUESTION)
        wait(client, rid, run_id)
        asked(client, rid, run_id)
        approve(client, run_id, terms=added(KEPT))
        wait(client, rid, run_id)
    finally:
        client.__exit__(None, None, None)
    body = bodies(tmp_path, rid)[0]
    entered = next(term for term in body["vocabulary"] if term["phrase"] == KEPT)
    # The origin is derived on the server from this approval's stored proposals; the `add` operation never said it.
    assert entered["origin"] == "model" and entered["block_origin"] == "user"
    assert store_at(tmp_path).approval_step(run_id)["output"]["edits"]["terms"] == [
        {"op": "add", "phrase": KEPT, "block": "setting"}]
    form = entered["root"] if entered["in_query"] == "root" else entered["phrase"]
    queries = sent(tmp_path, rid)
    assert queries and any(form in text for text in queries), (form, queries)
    # The count the suggestion step read is reused: the phrase query was sent once, not twice.
    assert openalex.counts.count(f'"{KEPT}"') == 1
    assert body["approval"]["suggestions"]["accepted"] == 1


def test_a_proposal_no_record_holds_drops_again_when_the_user_types_it_by_hand(tmp_path, monkeypatch):
    openalex = Counts()
    client = client_of(app_for(tmp_path, monkeypatch, openalex, suggesting()))
    try:
        rid, run_id = start(client, QUESTION)
        wait(client, rid, run_id)
        asked(client, rid, run_id)
        approve(client, run_id, terms=added(UNHELD))
        wait(client, rid, run_id)
    finally:
        client.__exit__(None, None, None)
    body = bodies(tmp_path, rid)[0]
    entered = next(term for term in body["vocabulary"] if term["phrase"] == UNHELD)
    assert (entered["dropped"], entered["origin"]) == ("zero_results", "model")
    assert openalex.counts.count(f'"{UNHELD}"') == 1
    assert all(UNHELD not in text for text in sent(tmp_path, rid))


def test_a_dropped_proposal_the_user_never_added_reaches_no_query_and_no_vocabulary(tmp_path, monkeypatch):
    client = client_of(app_for(tmp_path, monkeypatch, Counts(), suggesting()))
    try:
        rid, run_id = start(client, QUESTION)
        wait(client, rid, run_id)
        view, _ = asked(client, rid, run_id)
        approve(client, run_id)
        wait(client, rid, run_id)
    finally:
        client.__exit__(None, None, None)
    phrases = {term["phrase"] for term in bodies(tmp_path, rid)[0]["vocabulary"]}
    assert KEPT not in phrases and UNHELD not in phrases
    # The whole proposed list is still readable, with each row's reason: nothing was edited in place (SW14.2).
    assert len(rows_of(view, run_id)["terms"]) == 3


# ---- the model is not asked twice ------------------------------------------------------------------------

def test_a_second_request_while_a_list_is_ready_is_refused(tmp_path, monkeypatch):
    adapter = suggesting()
    client = client_of(app_for(tmp_path, monkeypatch, Counts(), adapter))
    try:
        rid, run_id = start(client, QUESTION)
        wait(client, rid, run_id)
        _, run = asked(client, rid, run_id)
        response = suggest(client, run_id, expect=409)
        assert "already" in response.text.lower(), response.text
    finally:
        client.__exit__(None, None, None)
    assert model_calls(adapter) == 1
    assert len(suggestion_steps(run)) == 2


def test_a_run_resumed_after_the_suggestion_step_repeats_neither_the_model_nor_the_counts(tmp_path, monkeypatch):
    openalex = Counts()
    adapter = suggesting()
    client = client_of(app_for(tmp_path, monkeypatch, openalex, adapter))
    try:
        rid, run_id = start(client, QUESTION)
        wait(client, rid, run_id)
        asked(client, rid, run_id)
        calls, counts = len(adapter.calls), list(openalex.counts)
        # Queued again as if the worker had been interrupted after the step closed. It is queued through the store,
        # because the API refuses a plain resume on a run that is waiting for its approval (D80).
        client.app.state.store.update_run(run_id, event="run_resumed", status="queued", pause_reason=None)
        client.app.state.worker.wake()
        _, run = wait(client, rid, run_id)
    finally:
        client.__exit__(None, None, None)
    assert run["pause_reason"] == "protocol_approval_needed", run
    assert len(adapter.calls) == calls, "the resumed run asked the model again"
    assert openalex.counts == counts, "the resumed run counted the proposals again"


def test_a_failed_request_is_recorded_the_card_reopens_and_the_user_can_approve_without_it(tmp_path, monkeypatch):
    client = client_of(app_for(tmp_path, monkeypatch, Counts(), suggesting(down=True)))
    try:
        rid, run_id = start(client, QUESTION)
        wait(client, rid, run_id)
        view, run = asked(client, rid, run_id)
        assert (run["status"], run["pause_reason"]) == ("paused", "protocol_approval_needed"), run
        suggestions = rows_of(view, run_id)
        assert suggestions["status"] == "failed" and suggestions["failure"] == "model_call_failed"
        assert suggestions["terms"] == [] and suggestions["available"] is True
        approve(client, run_id)
        _, run = wait(client, rid, run_id)
    finally:
        client.__exit__(None, None, None)
    assert run["pause_reason"] != "protocol_approval_needed", run
    assert bodies(tmp_path, rid)[0]["approval"]["suggestions"] == {
        "requests": 1, "proposed": 0, "dropped": 0, "accepted": 0,
        "step_input_id": None, "carried_from_step_id": None}


def test_a_failed_request_may_be_repeated_under_a_new_step_key(tmp_path, monkeypatch):
    adapter = suggesting(down=True)
    client = client_of(app_for(tmp_path, monkeypatch, Counts(), adapter))
    try:
        rid, run_id = start(client, QUESTION)
        wait(client, rid, run_id)
        asked(client, rid, run_id)
        # Allowed because the first one failed; it fails again on the same dead connection.
        _, run = asked(client, rid, run_id)
    finally:
        client.__exit__(None, None, None)
    assert sorted(s["operation_key"] for s in suggestion_steps(run)) == [
        "term_suggestion:1", "term_suggestion:2", "term_suggestions:1", "term_suggestions:2"]
    assert model_calls(adapter) == 2


# ---- what a later run of the same question sees ----------------------------------------------------------

def test_a_second_discovery_run_reapplies_the_correction_and_keeps_the_model_origin(tmp_path, monkeypatch):
    adapter = suggesting()
    client = client_of(app_for(tmp_path, monkeypatch, Counts(), adapter))
    try:
        rid, first_id = start(client, QUESTION)
        wait(client, rid, first_id)
        asked(client, rid, first_id)
        approve(client, first_id, terms=added(KEPT))
        wait(client, rid, first_id)
        calls = model_calls(adapter)
        second_id = client.post(f"/api/researches/{rid}/runs", json={"kind": "discovery"}).json()["id"]
        _, run = wait(client, rid, second_id)
    finally:
        client.__exit__(None, None, None)
    assert run["pause_reason"] != "protocol_approval_needed", run
    assert model_calls(adapter) == calls, "the second run asked the model for suggestions again"
    step = store_at(tmp_path).approval_step(second_id)
    assert step["output"]["approval"]["approved_by"] == "earlier_approval"
    entered = next(t for t in step["output"]["approved"]["vocabulary"]["terms"] if t["phrase"] == KEPT)
    assert entered["origin"] == "model"
    body = bodies(tmp_path, rid)[-1]
    assert next(t for t in body["vocabulary"] if t["phrase"] == KEPT)["origin"] == "model"
    assert body["approval"]["suggestions"]["carried_from_step_id"] == \
        step["output"]["approval"]["earlier_approval_step_id"]


def test_a_card_asked_again_carries_the_earlier_suggestions_and_calls_no_model(tmp_path, monkeypatch):
    """The "criterion nobody saw" case of the slice 08a review: the user is asked again, the model is not."""
    criterion_down = [True]
    adapter = suggesting(criterion_down=criterion_down)
    client = client_of(app_for(tmp_path, monkeypatch, Counts(), adapter))
    try:
        rid, first_id = start(client, QUESTION)
        wait(client, rid, first_id)
        asked(client, rid, first_id)
        approve(client, first_id, terms=added(KEPT))
        wait(client, rid, first_id)
        calls = model_calls(adapter)
        criterion_down[0] = False  # the second run reaches the model and gets a criterion nobody has seen
        second_id = client.post(f"/api/researches/{rid}/runs", json={"kind": "discovery"}).json()["id"]
        view, run = wait(client, rid, second_id)
        carried = store_at(tmp_path).approval_step(second_id)["output"]["carried_suggestions"]
    finally:
        client.__exit__(None, None, None)
    assert run["pause_reason"] == "protocol_approval_needed", run
    assert model_calls(adapter) == calls, "the re-asked card asked the model again"
    assert [row["phrase"] for row in carried["terms"]] == sorted([KEPT, UNHELD, anchor_of(tmp_path, first_id)])
    assert carried["from_step_id"]
    suggestions = rows_of(view, second_id)
    assert (suggestions["status"], suggestions["carried"]) == ("ready", True)
    assert suggestions["available"] is False and suggestions["unavailable_reason"] == "already_suggested"


def test_the_expansion_revision_carries_the_model_origin(tmp_path, monkeypatch):
    monkeypatch.setitem(CONNECTORS, "openalex", replace(CONNECTORS["openalex"], max_results=PAGE))
    client = client_of(app_for(tmp_path, monkeypatch, Field(counts=Table()), suggesting()))
    try:
        rid, run_id = start(client, QUESTION)
        wait(client, rid, run_id)
        asked(client, rid, run_id)
        approve(client, run_id, terms=added(KEPT))
        wait(client, rid, run_id)
    finally:
        client.__exit__(None, None, None)
    frozen = bodies(tmp_path, rid)
    # The second revision is the data expansion's; it carries the vocabulary the user approved, not the proposal.
    assert [body.get("arms") for body in frozen] == [["keyword_search"], ["keyword_search", "data_expansion"]], \
        [body["approval"] for body in frozen]
    for body in frozen:
        entered = next(t for t in body["vocabulary"] if t["phrase"] == KEPT)
        assert (entered["origin"], entered["block_origin"]) == ("model", "user")


def test_a_scope_revision_cancels_a_run_that_was_asked_for_suggestions(tmp_path, monkeypatch):
    adapter = suggesting()
    client = client_of(app_for(tmp_path, monkeypatch, Counts(), adapter))
    try:
        rid, run_id = start(client, QUESTION)
        wait(client, rid, run_id)
        version = client.get(f"/api/researches/{rid}").json()["research"]["version"]
        client.post(f"/api/researches/{rid}/scope",
                    json={"question": OTHER_QUESTION, "steering": None, "expected_version": version})
        suggest(client, run_id)
        _, stale = settled(client, rid, run_id)
    finally:
        client.__exit__(None, None, None)
    assert (stale["status"], stale["pause_reason"]) == ("cancelled", "scope_revised"), stale
    assert model_calls(adapter) == 0
    assert bodies(tmp_path, rid) == []


# ---- the route's refusals and the view's states ----------------------------------------------------------

def test_a_request_without_the_csrf_header_is_refused(tmp_path, monkeypatch):
    client = client_of(app_for(tmp_path, monkeypatch, Counts(), suggesting()))
    try:
        rid, run_id = start(client, QUESTION)
        wait(client, rid, run_id)
        del client.headers["x-deixis-csrf"]
        response = client.post(f"/api/runs/{run_id}/term-suggestions")
    finally:
        client.__exit__(None, None, None)
    assert response.status_code == 403, response.text


def test_a_cancelled_run_refuses_the_request_and_names_its_status(tmp_path, monkeypatch):
    client = client_of(app_for(tmp_path, monkeypatch, Counts(), suggesting()))
    try:
        rid, run_id = start(client, QUESTION)
        wait(client, rid, run_id)
        client.post(f"/api/runs/{run_id}/cancel")
        response = suggest(client, run_id, expect=409)
    finally:
        client.__exit__(None, None, None)
    assert "cancelled" in response.text, response.text


def test_an_approved_run_refuses_the_request_because_its_protocol_is_frozen(tmp_path, monkeypatch):
    client = client_of(app_for(tmp_path, monkeypatch, Counts(), suggesting()))
    try:
        rid, run_id = start(client, QUESTION)
        wait(client, rid, run_id)
        approve(client, run_id)
        wait(client, rid, run_id)
        response = suggest(client, run_id, expect=409)
    finally:
        client.__exit__(None, None, None)
    assert "approved" in response.text, response.text


def test_a_proposal_with_no_searched_phrase_offers_no_request(tmp_path, monkeypatch):
    """The `vocabulary_empty` corner of the slice file: with no anchor the button is closed and says why."""
    client = client_of(app_for(tmp_path, monkeypatch, Counts(), suggesting()))
    try:
        rid, run_id = start(client, QUESTION)
        wait(client, rid, run_id)
        store = client.app.state.store
        step = store.approval_step(run_id)
        empty = json.loads(json.dumps(step["output"]))
        empty["proposal"]["vocabulary"]["terms"] = []
        store.set_step_output(step["id"], empty)
        response = suggest(client, run_id, expect=409)
        view = client.get(f"/api/researches/{rid}").json()
    finally:
        client.__exit__(None, None, None)
    assert "searched term" in response.text, response.text
    assert rows_of(view, run_id) == {"status": "none", "available": False,
                                     "unavailable_reason": "no_anchor_phrases", "failure": None,
                                     "carried": False, "terms": []}


def test_the_view_says_requested_while_the_worker_has_not_answered_the_latest_request(tmp_path, monkeypatch):
    client = client_of(app_for(tmp_path, monkeypatch, Counts(), suggesting()))
    try:
        rid, run_id = start(client, QUESTION)
        wait(client, rid, run_id)
        asked(client, rid, run_id)
        store = client.app.state.store
        step = store.approval_step(run_id)
        # A second request the worker has not picked up yet: the card locks and says the model is working.
        store.set_step_output(step["id"], step["output"] | {"suggestion_requests": 2})
        view = client.get(f"/api/researches/{rid}").json()
    finally:
        client.__exit__(None, None, None)
    suggestions = rows_of(view, run_id)
    assert suggestions["status"] == "requested" and suggestions["available"] is False
    # The list of the answered request stays on the card while the next one runs.
    assert [row["phrase"] for row in suggestions["terms"]] == sorted([KEPT, UNHELD, anchor_of(tmp_path, run_id)])


def test_the_suggestions_stay_on_the_card_after_the_approval(tmp_path, monkeypatch):
    client = client_of(app_for(tmp_path, monkeypatch, Counts(), suggesting()))
    try:
        rid, run_id = start(client, QUESTION)
        wait(client, rid, run_id)
        asked(client, rid, run_id)
        approve(client, run_id, terms=added(KEPT))
        view, _ = wait(client, rid, run_id)
    finally:
        client.__exit__(None, None, None)
    approval = approval_of(view, run_id)
    assert approval["status"] == "approved"
    suggestions = approval["suggestions"]
    assert suggestions["status"] == "ready" and suggestions["available"] is False
    assert [row["phrase"] for row in suggestions["terms"]] == sorted(
        [KEPT, UNHELD, approval["proposal"]["terms"][0]["phrase"]])
    assert next(t for t in approval["approved"]["terms"] if t["phrase"] == KEPT)["origin"] == "model"
