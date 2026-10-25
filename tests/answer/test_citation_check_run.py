"""Verify Citations V3 (D99): each planned pair through the model step and the code's verdict, with a FakeAdapter.
Drafts, records, PDFs and model answers are SYNTHETIC and scripted; nothing here calls a real model or the network, so
these tests show what the workflow does with an answer, not how well any model answers."""

import json
import httpx
import pytest
from fastapi.testclient import TestClient
from deixis.api.app import create_app
from deixis.config import Settings
from deixis.models.adapter import ModelStepResult
from deixis.workflow.answer import citation_check
from fakes import FakeAdapter, envelope, valid_response
from test_citation_check_text import A_PAGES, Net, frozen, pair_rows, session, start, upload


MODEL = {"connection": "fake", "model": "fake-model"}


@pytest.fixture
def make(tmp_path, monkeypatch):
    monkeypatch.setenv("DEIXIS_CONTACT_EMAIL", "")
    monkeypatch.setenv("CORE_API_KEY", "")

    def build(responder=valid_response, fail=None):
        net = Net()
        adapter = FakeAdapter(responder, fail=fail)
        settings = Settings(data_dir=tmp_path / "data", port=8799, search_query="code", fulltext_fetch="off")
        app = create_app(settings, adapters={"fake": adapter}, http_client=httpx.AsyncClient(
            transport=httpx.MockTransport(net.handler)), fetcher=net.fetch, extra_hosts=("testserver",),
            trusted_clients=("testclient",))
        return app, adapter
    return build


def planned(client, pdf=A_PAGES):
    """A resolved draft with every text decided and its plan frozen: pairs a, b, c, a planned and d `no_text`."""
    view = start(client)
    upload(client, view, "a", pdf)
    client.post(f"/api/citation-checks/{view['id']}/acquire")
    return frozen(client, view["id"])


def run(client, draft_id, revision=1, preview=True, **body):
    """The person's flow: preview the plan for the model, then check it with that model."""
    if preview:
        client.get(f"/api/citation-checks/{draft_id}/preview", params=MODEL)
    return client.post(f"/api/citation-checks/{draft_id}/check", json={"plan_revision": revision, **MODEL, **body})


def by_target(view):
    return [(p["target"], p["status"], p["result"]) for _, p in pair_rows(view)]


def answer(si, parts, covers=True):
    return json.dumps(envelope(si, "deixis.citation_check.v1") | {"parts": parts, "covers_whole_sentence": covers})


def sentence(si):
    return si["citation_check_target"]["sentence"]


def is_b(si):
    return sentence(si).startswith("Void avoidance")


def scripted(for_b, others=valid_response):
    """`for_b(si, attempt)` answers pair b's step; every other pair gets the valid default."""
    attempts: dict[str, int] = {}

    def respond(si):
        if not is_b(si):
            return others(si)
        key = si["citation_check_target"]["pair_id"]
        attempts[key] = attempts.get(key, 0) + 1
        return for_b(si, attempts[key])
    respond.attempts = attempts
    return respond


def b_check(view):
    return next(p for _, p in pair_rows(view) if p["target"] == "b")


def test_every_planned_pair_is_checked_in_draft_order_and_found_whole_needs_located_quotes(make):
    app, adapter = make()
    with TestClient(app) as raw:
        client = session(raw)
        view = planned(client)
        response = run(client, view["id"])
        assert response.status_code == 200, response.text
        view = response.json()
        assert view["checked"]["status"] == "completed" and view["checked"]["checked_now"] == 4
        assert by_target(view) == [("a", "done", "found_whole"), ("b", "done", "found_whole"),
                                   ("c", "done", "found_whole"), ("d", "no_text", None), ("a", "done", "found_whole")]
        # Draft order, each pair once, on the model the request named; the step reads only its own work's passages.
        assert [si["citation_check_target"]["pair_id"] for si in adapter.calls] == [
            p["id"] for _, p in pair_rows(view) if p["status"] == "done"]
        assert {sent[1] for sent in adapter.sent} == {"fake-model"}
        for si in adapter.calls:
            assert si["task_type"] == "citation_check" and len(si["sources"]) == 1
            assert {p["source_id"] for p in si["passages"]} == {si["citation_check_target"]["assessed_source_id"]}
        b = b_check(view)["check"]
        assert (b["depth"], b["basis"]["passages_given"], b["basis"]["passages_not_given"]) == ("selected_passages", 6, 3)
        assert b["basis"]["located_passage_kinds"] == ["pdf_page"]
        c = next(p for _, p in pair_rows(view) if p["target"] == "c")["check"]
        assert (c["depth"], c["basis"]["located_passage_kinds"]) == ("abstract", ["abstract"])
        # The located words are the passage's own, stored by the backend.
        evidence = b["parts"][0]["evidence"][0]
        store = app.state.store
        assert evidence["located"] and evidence["anchor_text"] in store.passage(evidence["passage_id"])["text"]
        counters = view["counters"]
        assert (counters["pairs_sent_to_model"], counters["pairs_done"], counters["pairs_found"],
                counters["pairs_not_found_in_given"], counters["pairs_could_not_check"]) == (4, 4, 4, 0, 0)
        assert (counters["pairs_in_plan"], counters["pairs_to_send"]) == (4, 0)
        assert view["check_run"]["status"] == "completed" and view["check_run"]["model"]["model"] == "fake-model"
        # Nothing is left to send; a second call opens no run and sends nothing.
        again = run(client, view["id"]).json()
        assert again["checked"]["status"] == "nothing_to_check" and len(adapter.calls) == 4
        # The plan the checks read stays: a re-freeze is refused once a pair was checked.
        refreeze = client.post(f"/api/citation-checks/{view['id']}/plan", json={"refreeze": True})
        assert refreeze.status_code == 409 and refreeze.json()["code"] == "already_checked"


def test_a_positive_part_without_a_quote_is_repaired_then_could_not_check_never_not_found(make):
    def b(si, attempt):
        return answer(si, [{"text": sentence(si).rstrip(" ."), "assessment": "stated", "evidence": []}])
    responder = scripted(b)
    app, _ = make(responder)
    with TestClient(app) as raw:
        client = session(raw)
        view = run(client, planned(client)["id"]).json()
        check = b_check(view)["check"]
        assert (b_check(view)["status"], check["result"]) == ("could_not_check", None)
        assert check["error"]["code"] == "invalid_model_output"
        assert {i["code"] for i in check["error"]["issues"]} == {"positive_part_without_quote"}
        assert check["raw_output"] and json.loads(check["raw_output"])["parts"][0]["evidence"] == []
        assert list(responder.attempts.values()) == [2]
        counters = view["counters"]
        # Excluded from the done and the not-found counts, and from found.
        assert (counters["pairs_done"], counters["pairs_found"], counters["pairs_not_found_in_given"],
                counters["pairs_could_not_check"], counters["pairs_sent_to_model"]) == (3, 3, 0, 1, 4)


NEGATED = "SYNTHETIC page 7: void avoidance does not significantly improve delivery around holes in sparse networks."


def test_a_provider_failure_pauses_and_the_next_check_never_resends_a_checked_pair(make):
    failing = {"on": True}

    def fail(si):
        if failing["on"] and sentence(si).startswith("Mobile sinks"):
            return ModelStepResult("failed", error="SYNTHETIC provider error")
        return None
    app, adapter = make(fail=fail)
    with TestClient(app) as raw:
        client = session(raw)
        draft_id = planned(client)["id"]
        view = run(client, draft_id).json()
        assert view["checked"]["status"] == "paused" and view["checked"]["pause_reason"] == "model_call_failed"
        # Pairs a and b are done; c failed at the provider and stays planned, with no result and no check row.
        assert by_target(view)[:3] == [("a", "done", "found_whole"), ("b", "done", "found_whole"), ("c", "planned", None)]
        assert view["counters"]["pairs_could_not_check"] == 0 and view["counters"]["pairs_sent_to_model"] == 3
        sent_before = [si["citation_check_target"]["pair_id"] for si in adapter.calls]
        failing["on"] = False
        view = run(client, draft_id).json()
        assert view["checked"]["status"] == "completed"
        sent_after = [si["citation_check_target"]["pair_id"] for si in adapter.calls][len(sent_before):]
        pairs = [p for _, p in pair_rows(view)]
        assert sent_after == [pairs[2]["id"], pairs[4]["id"]]  # c and the second a; never a or b again
        assert [p["status"] for p in pairs] == ["done", "done", "done", "no_text", "done"]
