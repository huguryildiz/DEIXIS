"""An `sw` discovery run that stops before its first search until the user approves the protocol (slice 08a, SW2.6).

What is checked is workflow behavior: that nothing is searched before the approval, that a correction reaches the
frozen protocol and the query text that is really sent, that a resumed run, a second discovery run and a scope
revision ask nothing twice, and that a `legacy` research gains none of it. Questions, records and criteria are
SYNTHETIC and the transport is mocked: passing shows the workflow, not recall or criterion quality.
"""

import json
import time

import httpx
from fastapi.testclient import TestClient

from deixis.api.app import create_app
from deixis.config import Settings
from deixis.domain.canonical import sha256_hex
from deixis.providers.registry import CONNECTORS
from deixis.workflow.decisions import CRITERION_FIELDS
from fakes import FakeAdapter, envelope, valid_response
from test_criterion_proposal import three_runs
from test_provider_flow import routed, two_provider_plan
from test_vocabulary_flow import (CountingOpenAlex, DeadAdapter, QUESTION, no_fetch, start, store_at, wait)

# SYNTHETIC and from a field the other approval tests do not use.
OTHER_QUESTION = "How does canopy cover affect seedling survival in temperate forests?"
RUNS = three_runs()


def proposing():
    """A model that answers each criterion call with its own proposal and fails everything else."""
    order = []

    def number(si):
        if si["step_id"] not in order:
            order.append(si["step_id"])
        return order.index(si["step_id"]) % len(RUNS) + 1

    def responder(si):
        if si["task_type"] != "criterion_proposal":
            return valid_response(si)
        return json.dumps(envelope(si, "deixis.criterion_proposal.v1") | RUNS[number(si)])

    return FakeAdapter(responder)


def app_for(tmp_path, monkeypatch, handler, adapter=None, workflow="sw", approval="ask"):
    for connector in CONNECTORS.values():
        if connector.key_env:
            monkeypatch.delenv(connector.key_env, raising=False)
    monkeypatch.setenv("DEIXIS_SEARCH_WORKFLOW", workflow)
    return create_app(Settings(data_dir=tmp_path / "data", port=8765, search_workflow=workflow,
                               protocol_approval=approval),
                      adapters={"fake": adapter or DeadAdapter()},
                      http_client=httpx.AsyncClient(transport=httpx.MockTransport(handler)), fetcher=no_fetch,
                      extra_hosts=("testserver",), trusted_clients=("testclient",))


def client_of(app):
    client = TestClient(app)
    client.__enter__()
    client.headers["x-deixis-csrf"] = client.get("/api/session").json()["csrf_token"]
    return client


def approve(client, run_id, terms=(), criterion=None, note=None, expect=200):
    body = {"terms": list(terms), "criterion": criterion, "note": note}
    response = client.post(f"/api/runs/{run_id}/protocol-approval", json=body)
    assert response.status_code == expect, response.text
    return response


def settled(client, rid, run_id):
    """`wait`, and a cancelled run is settled too: a scope revision cancels the run that was waiting."""
    deadline = time.time() + 15
    while time.time() < deadline:
        view = client.get(f"/api/researches/{rid}").json()
        run = next(r for r in view["runs"] if r["id"] == run_id)
        if run["status"] in ("completed", "failed", "paused", "cancelled"):
            return view, run
        time.sleep(0.05)
    raise AssertionError("the run did not settle")


def approval_of(view, run_id):
    return next(r for r in view["runs"] if r["id"] == run_id)["approval"]


def steps_of(run):
    return [s["operation_key"] for s in run["steps"]]


def bodies(tmp_path, rid):
    rows = store_at(tmp_path).conn.execute(
        "SELECT body_json, body_sha256, reason FROM protocol_records WHERE research_id = ?"
        " ORDER BY protocol_revision", (rid,)).fetchall()
    return [json.loads(row["body_json"]) for row in rows]


def criterion_digest(body):
    return sha256_hex({field: body[field] for field in CRITERION_FIELDS})


# ---- nothing is searched before the approval --------------------------------------------------------------

def test_an_sw_run_stops_before_its_first_search_and_has_sent_count_probes_only(tmp_path, monkeypatch):
    openalex = CountingOpenAlex()
    client = client_of(app_for(tmp_path, monkeypatch, openalex, proposing()))
    try:
        rid, run_id = start(client, QUESTION)
        view, run = wait(client, rid, run_id)
    finally:
        client.__exit__(None, None, None)
    assert (run["status"], run["pause_reason"]) == ("paused", "protocol_approval_needed"), run
    # The acceptance condition of this slice, named three ways.
    assert not [s for s in run["steps"] if s["kind"].startswith("provider_search")], steps_of(run)
    assert openalex.counts and not openalex.searches
    assert view["counts"]["unique"] == 0
    assert bodies(tmp_path, rid) == []
    # The step is still `pending`: a step that was never started is not half-finished work the recovery guesses at.
    step = store_at(tmp_path).approval_step(run_id)
    assert step["status"] == "pending" and step["output"]["submitted"] is None
    assert steps_of(run)[-1] == "protocol_approval"


def test_a_run_waiting_for_the_approval_refuses_a_plain_resume(tmp_path, monkeypatch):
    client = client_of(app_for(tmp_path, monkeypatch, CountingOpenAlex(), proposing()))
    try:
        rid, run_id = start(client, QUESTION)
        wait(client, rid, run_id)
        response = client.post(f"/api/runs/{run_id}/resume")
        assert response.status_code == 409 and "Approve" in response.text
        assert client.get(f"/api/researches/{rid}").json()["runs"][0]["status"] == "paused"
    finally:
        client.__exit__(None, None, None)


def test_an_approval_without_a_term_edit_sends_no_count_request_and_keeps_the_proposed_queries(tmp_path, monkeypatch):
    openalex = CountingOpenAlex()
    client = client_of(app_for(tmp_path, monkeypatch, openalex, proposing()))
    try:
        rid, run_id = start(client, QUESTION)
        wait(client, rid, run_id)
        proposed = approval_of(client.get(f"/api/researches/{rid}").json(), run_id)
        probed = list(openalex.counts)
        approve(client, run_id)
        view, run = wait(client, rid, run_id)
    finally:
        client.__exit__(None, None, None)
    assert openalex.counts == probed, "an approval with no term edit asked the literature again"
    assert openalex.searches
    stored = store_at(tmp_path).approval_step(run_id)["output"]
    # Byte for byte the queries the vocabulary step compiled, and the searches that were really sent.
    assert stored["approved"]["queries"] == stored["proposal"]["queries"]
    sent = {row["query_text"] for row in store_at(tmp_path).conn.execute(
        "SELECT query_text FROM search_runs WHERE research_id = ?", (rid,))}
    assert sent == {q["query_text"] for q in stored["proposal"]["queries"]}
    assert approval_of(view, run_id)["proposal"] == proposed["proposal"]


# ---- what a correction changes --------------------------------------------------------------------------

def corrected(client, rid, run_id, **kwargs):
    wait(client, rid, run_id)
    approve(client, run_id, **kwargs)
    return wait(client, rid, run_id)


def test_a_term_edit_reaches_the_frozen_protocol_and_the_query_that_is_really_sent(tmp_path, monkeypatch):
    openalex = CountingOpenAlex()
    client = client_of(app_for(tmp_path, monkeypatch, openalex, proposing()))
    try:
        rid, run_id = start(client, QUESTION)
        wait(client, rid, run_id)
        proposal = store_at(tmp_path).approval_step(run_id)["output"]["proposal"]
        removed = next(t["phrase"] for t in proposal["vocabulary"]["terms"] if t["block"] == "task")
        view, run = corrected(client, rid, run_id, terms=[
            {"op": "remove", "phrase": removed},
            {"op": "add", "phrase": "synthetic duty cycle", "block": "task"}], note="SYNTHETIC: why I changed it.")
    finally:
        client.__exit__(None, None, None)
    body = bodies(tmp_path, rid)[0]
    phrases = {term["phrase"]: term for term in body["vocabulary"]}
    assert removed not in phrases
    assert phrases["synthetic duty cycle"]["origin"] == "user"
    assert phrases["synthetic duty cycle"]["block_origin"] == "user"
    assert body["approval"] == {
        "mode": "ask", "approved_by": "user", "edited": True, "term_edits": 2, "criterion_edited": False,
        "proposal_hash": body["approval"]["proposal_hash"], "exclusion_word_in_question": [],
        "note": "SYNTHETIC: why I changed it."}
    sent = [row["query_text"] for row in store_at(tmp_path).conn.execute(
        "SELECT query_text FROM search_runs WHERE research_id = ?", (rid,))]
    assert sent and all(removed.split()[0] not in text for text in sent), sent
    added = next(t for t in bodies(tmp_path, rid)[0]["vocabulary"] if t["phrase"] == "synthetic duty cycle")
    form = added["root"] if added["in_query"] == "root" else added["phrase"]
    assert form in body["concept_blocks"]["task"]
    assert any(form in text for text in sent), (form, sent)
    # The added phrase met the same count probe every other term met.
    assert '"synthetic duty cycle"' in openalex.counts


def test_a_criterion_the_user_wrote_reaches_the_protocol_and_the_origin_says_user(tmp_path, monkeypatch):
    written = {"criterion": "SYNTHETIC: the paper reports a measured energy budget for a named packet size.",
               "parts": [{"name": "packet size", "definition": "SYNTHETIC: a size is named."},
                         {"name": "energy", "definition": "SYNTHETIC: a joule figure is given."}],
               "cue_phrases": [{"phrase": "energy per bit", "part": "energy"}],
               "exclusion_title_words": ["editorial"]}
    client = client_of(app_for(tmp_path, monkeypatch, CountingOpenAlex(), proposing()))
    try:
        rid, run_id = start(client, QUESTION)
        corrected(client, rid, run_id, criterion=written)
    finally:
        client.__exit__(None, None, None)
    body = bodies(tmp_path, rid)[0]
    assert body["inclusion_criterion"] == written["criterion"]
    assert [p["name"] for p in body["criterion_parts"]] == ["packet size", "energy"]
    assert [c["phrase"] for c in body["cue_phrases"]] == ["energy per bit"]
    assert body["criterion_origin"]["origin"] == "user"
    # The record of the proposal the user corrected travels with it.
    assert body["criterion_origin"]["runs_ok"] == [1, 2, 3]
    assert body["approval"]["criterion_edited"] is True and body["approval"]["edited"] is True


def test_the_proposal_stays_beside_what_was_approved(tmp_path, monkeypatch):
    """SW14.2: nothing is edited in place, so the user can still see what was proposed."""
    client = client_of(app_for(tmp_path, monkeypatch, CountingOpenAlex(), proposing()))
    try:
        rid, run_id = start(client, QUESTION)
        wait(client, rid, run_id)
        proposal = store_at(tmp_path).approval_step(run_id)["output"]["proposal"]
        removed = next(t["phrase"] for t in proposal["vocabulary"]["terms"] if t["block"] == "task")
        view, _ = corrected(client, rid, run_id, terms=[{"op": "remove", "phrase": removed}])
        approval = approval_of(view, run_id)
    finally:
        client.__exit__(None, None, None)
    assert approval["status"] == "approved" and approval["edited"] is True
    assert removed in [t["phrase"] for t in approval["proposal"]["terms"]]
    assert removed not in [t["phrase"] for t in approval["approved"]["terms"]]
    stored = store_at(tmp_path).approval_step(run_id)["output"]
    assert stored["proposal"]["vocabulary"] == proposal["vocabulary"]


def test_a_correction_that_empties_the_vocabulary_stops_the_run_and_can_be_sent_again(tmp_path, monkeypatch):
    client = client_of(app_for(tmp_path, monkeypatch, CountingOpenAlex(), proposing()))
    try:
        rid, run_id = start(client, QUESTION)
        wait(client, rid, run_id)
        proposal = store_at(tmp_path).approval_step(run_id)["output"]["proposal"]
        everything = [{"op": "remove", "phrase": t["phrase"]} for t in proposal["vocabulary"]["terms"]]
        approve(client, run_id, terms=everything)
        view, run = wait(client, rid, run_id)
        assert run["pause_reason"] == "vocabulary_empty", run
        assert store_at(tmp_path).approval_step(run_id)["status"] != "succeeded"
        assert bodies(tmp_path, rid) == []
        # The user sends another correction rather than being stuck with the first one.
        approve(client, run_id, terms=everything[:-1])
        view, run = wait(client, rid, run_id)
    finally:
        client.__exit__(None, None, None)
    assert run["pause_reason"] != "vocabulary_empty", run
    assert bodies(tmp_path, rid), "the second correction never froze a protocol"


# ---- asking once --------------------------------------------------------------------------------------

def test_a_run_paused_and_resumed_after_the_approval_does_not_stop_again_or_probe_again(tmp_path, monkeypatch):
    openalex = CountingOpenAlex()
    client = client_of(app_for(tmp_path, monkeypatch, openalex, proposing()))
    try:
        rid, run_id = start(client, QUESTION)
        corrected(client, rid, run_id, terms=[{"op": "add", "phrase": "synthetic duty cycle", "block": "task"}])
        after = list(openalex.counts)
        client.post(f"/api/runs/{run_id}/resume")
        view, run = wait(client, rid, run_id)
    finally:
        client.__exit__(None, None, None)
    assert run["pause_reason"] != "protocol_approval_needed", run
    assert openalex.counts == after, "the resumed run probed the literature again"


def test_a_second_discovery_run_of_the_same_scope_does_not_ask_again_and_carries_the_same_correction(tmp_path, monkeypatch):
    client = client_of(app_for(tmp_path, monkeypatch, CountingOpenAlex(), proposing()))
    try:
        rid, first_id = start(client, QUESTION)
        wait(client, rid, first_id)
        proposal = store_at(tmp_path).approval_step(first_id)["output"]["proposal"]
        removed = next(t["phrase"] for t in proposal["vocabulary"]["terms"] if t["block"] == "task")
        corrected(client, rid, first_id, terms=[{"op": "remove", "phrase": removed}])
        second_id = client.post(f"/api/researches/{rid}/runs", json={"kind": "discovery"}).json()["id"]
        view, run = wait(client, rid, second_id)
    finally:
        client.__exit__(None, None, None)
    assert run["pause_reason"] != "protocol_approval_needed", run
    step = store_at(tmp_path).approval_step(second_id)
    assert step["status"] == "succeeded"
    assert step["output"]["approval"]["approved_by"] == "earlier_approval"
    assert removed not in [t["phrase"] for t in step["output"]["approved"]["vocabulary"]["terms"]]


def test_a_second_run_takes_the_approved_criterion_back_and_does_not_correct_it_again(tmp_path, monkeypatch):
    written = {"criterion": "SYNTHETIC: the paper reports a measured energy budget for a named packet size.",
               "parts": [{"name": "packet size", "definition": "SYNTHETIC: a size is named."},
                         {"name": "energy", "definition": "SYNTHETIC: a joule figure is given."}],
               "cue_phrases": [{"phrase": "energy per bit", "part": "energy"}],
               "exclusion_title_words": ["editorial"]}
    client = client_of(app_for(tmp_path, monkeypatch, CountingOpenAlex(), proposing()))
    try:
        rid, first_id = start(client, QUESTION)
        corrected(client, rid, first_id, criterion=written)
        second_id = client.post(f"/api/researches/{rid}/runs", json={"kind": "discovery"}).json()["id"]
        _, run = wait(client, rid, second_id)
    finally:
        client.__exit__(None, None, None)
    assert run["pause_reason"] != "protocol_approval_needed", run
    second = bodies(tmp_path, rid)[-1]
    # The criterion came back from the frozen protocol, so it is the approved one and it was not edited again.
    assert second["inclusion_criterion"] == written["criterion"]
    assert second["criterion_origin"]["origin"] == "protocol"
    assert second["approval"]["criterion_edited"] is False
    assert second["approval"]["approved_by"] == "earlier_approval"


def test_a_scope_revision_that_keeps_the_question_does_not_ask_again_and_one_that_changes_it_does(tmp_path, monkeypatch):
    client = client_of(app_for(tmp_path, monkeypatch, CountingOpenAlex(), proposing()))
    try:
        rid, first_id = start(client, QUESTION)
        corrected(client, rid, first_id)
        version = client.get(f"/api/researches/{rid}").json()["research"]["version"]
        client.post(f"/api/researches/{rid}/scope",
                    json={"question": QUESTION, "steering": None, "expected_version": version})
        same_id = client.post(f"/api/researches/{rid}/runs", json={"kind": "discovery"}).json()["id"]
        _, same = wait(client, rid, same_id)
        version = client.get(f"/api/researches/{rid}").json()["research"]["version"]
        client.post(f"/api/researches/{rid}/scope",
                    json={"question": OTHER_QUESTION, "steering": None, "expected_version": version})
        other_id = client.post(f"/api/researches/{rid}/runs", json={"kind": "discovery"}).json()["id"]
        _, other = wait(client, rid, other_id)
    finally:
        client.__exit__(None, None, None)
    assert same["pause_reason"] != "protocol_approval_needed", same
    assert other["pause_reason"] == "protocol_approval_needed", other


def test_a_scope_revision_that_arrives_while_the_run_waits_cancels_it_and_the_next_run_asks_again(tmp_path, monkeypatch):
    client = client_of(app_for(tmp_path, monkeypatch, CountingOpenAlex(), proposing()))
    try:
        rid, run_id = start(client, QUESTION)
        wait(client, rid, run_id)
        version = client.get(f"/api/researches/{rid}").json()["research"]["version"]
        client.post(f"/api/researches/{rid}/scope",
                    json={"question": OTHER_QUESTION, "steering": None, "expected_version": version})
        # The stale run is answered anyway; the checkpoint of the older revision cancels it (existing behavior).
        approve(client, run_id)
        _, stale = settled(client, rid, run_id)
        next_id = client.post(f"/api/researches/{rid}/runs", json={"kind": "discovery"}).json()["id"]
        _, fresh = wait(client, rid, next_id)
    finally:
        client.__exit__(None, None, None)
    assert (stale["status"], stale["pause_reason"]) == ("cancelled", "scope_revised"), stale
    assert fresh["pause_reason"] == "protocol_approval_needed", fresh


# ---- the approval is not lost on the way ----------------------------------------------------------------

def test_the_expansion_revision_carries_the_correction_and_the_criterion(tmp_path, monkeypatch):
    """The trap of slices 06 and 07 a third time: a revision built from the proposal would undo the correction."""
    from dataclasses import replace

    from test_expansion_flow import ACCEPTED, Field, PAGE, QUESTION as PACKET_QUESTION

    # The user takes one phrase out of the setting block, so the second round's field probe is asked against the
    # block the correction left behind; both counts are SYNTHETIC and fixed.
    moved = "energy consumption"
    counts = {f'"{ACCEPTED}"': 100, f'"{ACCEPTED}" AND (wireless)': 40}
    monkeypatch.setitem(CONNECTORS, "openalex", replace(CONNECTORS["openalex"], max_results=PAGE))
    client = client_of(app_for(tmp_path, monkeypatch, Field(counts=counts), proposing()))
    try:
        rid, run_id = start(client, PACKET_QUESTION)
        corrected(client, rid, run_id, terms=[{"op": "move", "phrase": moved, "block": "outcome"}])
    finally:
        client.__exit__(None, None, None)
    frozen = bodies(tmp_path, rid)
    assert len(frozen) >= 2, "the second round froze no revision"
    first, second = frozen[0], frozen[-1]
    assert ACCEPTED in second["expansion"]["terms"]
    # The correction and the criterion are in the later revision too: a revision built from the proposal would
    # undo the user's correction and mark every decision taken under the criterion stale.
    for body in (first, second):
        assert moved not in [f for f in body["concept_blocks"]["setting"]], body["concept_blocks"]
        assert body["approval"]["approved_by"] == "user" and body["approval"]["edited"] is True
    assert criterion_digest(first) == criterion_digest(second)
    assert second["approval"] == first["approval"]


def test_the_run_searches_with_what_was_approved_and_not_with_what_was_proposed(tmp_path, monkeypatch):
    client = client_of(app_for(tmp_path, monkeypatch, CountingOpenAlex(), proposing()))
    try:
        rid, run_id = start(client, QUESTION)
        wait(client, rid, run_id)
        proposal = store_at(tmp_path).approval_step(run_id)["output"]["proposal"]
        removed = next(t["phrase"] for t in proposal["vocabulary"]["terms"] if t["block"] == "setting")
        corrected(client, rid, run_id, terms=[{"op": "move", "phrase": removed, "block": "claim"}])
    finally:
        client.__exit__(None, None, None)
    body = bodies(tmp_path, rid)[0]
    assert removed in body["claim_words"]
    assert removed not in [f for block in body["concept_blocks"].values() for f in block]
    sent = [row["query_text"] for row in store_at(tmp_path).conn.execute(
        "SELECT query_text FROM search_runs WHERE research_id = ?", (rid,))]
    assert sent and all(removed.split()[0] not in text for text in sent), sent


# ---- the run that nobody attends, and the model that is down ---------------------------------------------

def test_the_run_still_stops_for_the_approval_while_every_model_call_fails(tmp_path, monkeypatch):
    openalex = CountingOpenAlex()
    client = client_of(app_for(tmp_path, monkeypatch, openalex, DeadAdapter()))
    try:
        rid, run_id = start(client, QUESTION)
        _, run = wait(client, rid, run_id)
        assert run["pause_reason"] == "protocol_approval_needed", run
        view = client.get(f"/api/researches/{rid}").json()
        approval = approval_of(view, run_id)
        assert approval["proposal"]["criterion"] is None
        assert approval["proposal"]["criterion_available"] is False
        approve(client, run_id)
        _, run = wait(client, rid, run_id)
    finally:
        client.__exit__(None, None, None)
    assert openalex.searches, "the approved run did not search"
    assert bodies(tmp_path, rid)[0]["inclusion_criterion"] is None


def test_the_as_proposed_setting_never_stops_and_says_so_in_the_protocol(tmp_path, monkeypatch):
    client = client_of(app_for(tmp_path, monkeypatch, CountingOpenAlex(), proposing(), approval="as_proposed"))
    try:
        rid, run_id = start(client, QUESTION)
        _, run = wait(client, rid, run_id)
    finally:
        client.__exit__(None, None, None)
    assert run["pause_reason"] != "protocol_approval_needed", run
    body = bodies(tmp_path, rid)[0]
    # A run nobody attended never looks like a run a user approved.
    assert body["approval"]["approved_by"] == "setting" and body["approval"]["mode"] == "as_proposed"
    assert body["approval"]["edited"] is False and body["approval"]["term_edits"] == 0
    assert all(term["block_origin"] != "user" for term in body["vocabulary"])


def test_a_legacy_research_opens_no_approval_step_and_its_protocol_body_is_what_it_was(tmp_path, monkeypatch):
    client = client_of(app_for(tmp_path, monkeypatch, routed, FakeAdapter(two_provider_plan), workflow="legacy"))
    try:
        rid, run_id = start(client, QUESTION)
        view, run = wait(client, rid, run_id)
    finally:
        client.__exit__(None, None, None)
    assert "protocol_approval" not in steps_of(run)
    assert run["pause_reason"] != "protocol_approval_needed", run
    assert next(r for r in view["runs"] if r["id"] == run_id)["approval"] is None
    body = bodies(tmp_path, rid)[0]
    assert "approval" not in body and body["search_workflow"] == "legacy"


# ---- the route and what the view carries ------------------------------------------------------------------

def test_the_route_refuses_a_run_that_has_not_proposed_a_protocol(tmp_path, monkeypatch):
    client = client_of(app_for(tmp_path, monkeypatch, CountingOpenAlex(), proposing(), approval="as_proposed"))
    try:
        rid, run_id = start(client, QUESTION)
        wait(client, rid, run_id)
        # The approval of this run succeeded on its own, so there is nothing left to answer.
        response = client.post(f"/api/runs/{run_id}/protocol-approval", json={"terms": []})
        assert response.status_code == 409 and "already approved" in response.text
    finally:
        client.__exit__(None, None, None)


def test_the_route_refuses_a_legacy_run_that_proposed_nothing(tmp_path, monkeypatch):
    client = client_of(app_for(tmp_path, monkeypatch, routed, FakeAdapter(two_provider_plan), workflow="legacy"))
    try:
        rid, run_id = start(client, QUESTION)
        wait(client, rid, run_id)
        response = client.post(f"/api/runs/{run_id}/protocol-approval", json={"terms": []})
        assert response.status_code == 409 and "not proposed" in response.text
    finally:
        client.__exit__(None, None, None)


def test_the_route_refuses_a_run_that_is_no_longer_waiting(tmp_path, monkeypatch):
    client = client_of(app_for(tmp_path, monkeypatch, CountingOpenAlex(), proposing()))
    try:
        rid, run_id = start(client, QUESTION)
        wait(client, rid, run_id)
        client.post(f"/api/runs/{run_id}/cancel")
        response = client.post(f"/api/runs/{run_id}/protocol-approval", json={"terms": []})
        assert response.status_code == 409 and "status cancelled" in response.text
    finally:
        client.__exit__(None, None, None)


def test_the_route_names_every_fault_of_a_broken_correction(tmp_path, monkeypatch):
    client = client_of(app_for(tmp_path, monkeypatch, CountingOpenAlex(), proposing()))
    try:
        rid, run_id = start(client, QUESTION)
        wait(client, rid, run_id)
        response = approve(client, run_id, terms=[
            {"op": "remove", "phrase": "a phrase nobody proposed"},
            {"op": "add", "phrase": "another", "block": "nowhere"}], expect=422)
        errors = response.json()["detail"]["errors"]
        assert len(errors) == 2, errors
        # Nothing was stored and the run is still waiting: a refused correction is refused whole.
        assert store_at(tmp_path).approval_step(run_id)["output"]["submitted"] is None
        _, run = wait(client, rid, run_id)
        assert run["pause_reason"] == "protocol_approval_needed"
    finally:
        client.__exit__(None, None, None)


def test_a_correction_without_the_csrf_header_is_refused(tmp_path, monkeypatch):
    client = client_of(app_for(tmp_path, monkeypatch, CountingOpenAlex(), proposing()))
    try:
        rid, run_id = start(client, QUESTION)
        wait(client, rid, run_id)
        del client.headers["x-deixis-csrf"]
        response = client.post(f"/api/runs/{run_id}/protocol-approval", json={"terms": []})
        assert response.status_code == 403, response.text
    finally:
        client.__exit__(None, None, None)


def test_a_second_correction_overwrites_the_first_until_the_approval_succeeds(tmp_path, monkeypatch):
    client = client_of(app_for(tmp_path, monkeypatch, CountingOpenAlex(), proposing()))
    try:
        rid, run_id = start(client, QUESTION)
        wait(client, rid, run_id)
        proposal = store_at(tmp_path).approval_step(run_id)["output"]["proposal"]
        everything = [{"op": "remove", "phrase": t["phrase"]} for t in proposal["vocabulary"]["terms"]]
        approve(client, run_id, terms=everything)
        wait(client, rid, run_id)  # stops with vocabulary_empty, so the step is still open
        approve(client, run_id, note="SYNTHETIC: second try.")
        _, run = wait(client, rid, run_id)
        stored = store_at(tmp_path).approval_step(run_id)["output"]
        assert stored["edits"]["note"] == "SYNTHETIC: second try." and stored["edits"]["terms"] == []
        # The proposal itself never changed between the two submissions.
        assert stored["proposal"]["vocabulary"] == proposal["vocabulary"]
        # Once it has succeeded the answer is closed: a change is a new scope revision.
        response = client.post(f"/api/runs/{run_id}/protocol-approval", json={"terms": []})
        assert response.status_code == 409 and "revise the scope" in response.text
    finally:
        client.__exit__(None, None, None)


def test_the_view_carries_the_waiting_then_approved_states_with_both_sides(tmp_path, monkeypatch):
    client = client_of(app_for(tmp_path, monkeypatch, CountingOpenAlex(), proposing()))
    try:
        rid, run_id = start(client, QUESTION)
        wait(client, rid, run_id)
        waiting = approval_of(client.get(f"/api/researches/{rid}").json(), run_id)
        assert waiting["status"] == "waiting" and waiting["approved"] is None
        assert waiting["approved_by"] is None and waiting["skipped_edits"] == []
        term = waiting["proposal"]["terms"][0]
        assert set(term) == {"phrase", "block", "origin", "root", "in_query", "phrase_count", "root_count",
                             "and_only", "dropped", "block_origin"}
        assert waiting["proposal"]["criterion_available"] is True
        assert "probes" not in waiting["proposal"] and "queries" not in waiting["proposal"]
        approve(client, run_id)
        view, _ = wait(client, rid, run_id)
        approved = approval_of(view, run_id)
    finally:
        client.__exit__(None, None, None)
    assert approved["status"] == "approved" and approved["approved_by"] == "user"
    assert approved["proposal"]["terms"] == waiting["proposal"]["terms"]
    # The compiled queries reach the screen by provider and text only.
    assert approved["approved"]["queries"]
    assert all(set(q) == {"provider_id", "query_text"} for q in approved["approved"]["queries"])
