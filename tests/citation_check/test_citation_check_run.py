"""Verify Citations V3 (D99): each planned pair through the model step and the code's verdict, with a FakeAdapter.
Drafts, records, PDFs and model answers are SYNTHETIC and scripted; nothing here calls a real model or the network, so
these tests show what the workflow does with an answer, not how well any model answers."""

import csv
import io
import json

import httpx
import pytest
from fastapi.testclient import TestClient

from deixis.api.app import create_app
from deixis.config import Settings
from deixis.models.adapter import ModelStepResult
from deixis.workflow import citation_check
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


def quote_of(si, words):
    """The given passage (by the handle the model sees) holding these words, with the words as its quote."""
    found = next(p for p in si["passages"] if words.casefold() in p["text"].casefold())
    return {"passage_id": found["passage_id"], "quote": words}


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


def test_one_part_stated_and_one_not_stated_is_found_partial(make):
    def b(si, attempt):
        return answer(si, [
            {"text": "Void avoidance keeps packets moving", "assessment": "stated",
             "evidence": [quote_of(si, "void avoidance keeps packets moving")]},
            {"text": "around holes", "assessment": "not_stated", "evidence": []}])
    app, _ = make(scripted(b))
    with TestClient(app) as raw:
        client = session(raw)
        view = run(client, planned(client)["id"]).json()
        check = b_check(view)["check"]
        assert (check["status"], check["result"]) == ("done", "found_partial")
        assert [p["assessment"] for p in check["parts"]] == ["stated", "not_stated"]
        assert view["counters"]["pairs_found"] == 4


@pytest.mark.parametrize("covers", [True, False])
def test_a_part_left_out_never_reads_as_the_whole_sentence(make, covers):
    """"A stated, B omitted": whether or not the model declares coverage, the part it left out sends the step to
    repair, and a repair that still leaves it out cannot be checked; it is never `found_whole`."""
    def b(si, attempt):
        return answer(si, [{"text": "Void avoidance keeps packets moving", "assessment": "stated",
                            "evidence": [quote_of(si, "void avoidance keeps packets moving")]}], covers=covers)
    responder = scripted(b)
    app, _ = make(responder)
    with TestClient(app) as raw:
        client = session(raw)
        view = run(client, planned(client)["id"]).json()
        check = b_check(view)["check"]
        assert (check["status"], check["result"]) == ("could_not_check", None)
        codes = {i["code"] for i in check["error"]["issues"]}
        assert "parts_leave_out_words" in codes and ("sentence_not_covered" in codes) is not covers
        assert list(responder.attempts.values()) == [2]  # the first answer and its one repair


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


def test_a_repaired_answer_is_checked_and_the_repair_names_the_passage_without_moving_the_quote(make):
    """The quote is in another given passage than the one it names: the issue says where it is, and only the model's
    corrected answer, validated again, is used."""
    seen = []

    def b(si, attempt):
        right = quote_of(si, "void avoidance keeps packets moving around holes")
        wrong = next(p["passage_id"] for p in si["passages"] if p["passage_id"] != right["passage_id"])
        seen.append(right["passage_id"])
        named = right if attempt == 2 else right | {"passage_id": wrong}
        return answer(si, [{"text": sentence(si).rstrip(" ."), "assessment": "stated", "evidence": [named]}])
    responder = scripted(b)
    app, adapter = make(responder)
    with TestClient(app) as raw:
        client = session(raw)
        view = run(client, planned(client)["id"]).json()
        check = b_check(view)["check"]
        assert (check["status"], check["result"]) == ("done", "found_whole")
        sessions = app.state.store.conn.execute(
            "SELECT m.validation_json FROM model_sessions m JOIN step_inputs si ON si.id = m.step_input_id"
            " WHERE json_extract(si.payload_json, '$.citation_check_target.pair_id') = ? ORDER BY m.rowid",
            (b_check(view)["id"],)).fetchall()
        first = json.loads(sessions[0][0])
        assert not first["ok"] and [i["code"] for i in first["issues"]] == ["anchor_not_in_passage"]
        assert "it is in" in first["issues"][0]["message"]
        assert json.loads(sessions[1][0])["ok"]


def test_a_wrongly_named_passage_whose_repair_is_wrong_again_is_not_recovered(make):
    def b(si, attempt):
        right = quote_of(si, "void avoidance keeps packets moving around holes")
        wrong = next(p["passage_id"] for p in si["passages"] if p["passage_id"] != right["passage_id"])
        return answer(si, [{"text": sentence(si).rstrip(" ."), "assessment": "stated",
                            "evidence": [right | {"passage_id": wrong}]}])
    app, _ = make(scripted(b))
    with TestClient(app) as raw:
        client = session(raw)
        check = b_check(run(client, planned(client)["id"]).json())["check"]
        assert (check["status"], check["result"]) == ("could_not_check", None)
        assert {i["code"] for i in check["error"]["issues"]} == {"anchor_not_in_passage"}


def test_quotes_outside_the_given_passages_are_never_located(make):
    """A passage of the same work that was not given, a passage of another work, and an invented passage id."""
    state = {}

    def b(si, attempt):
        return answer(si, [{"text": sentence(si).rstrip(" ."), "assessment": "stated", "evidence": [
            {"passage_id": state["not_given"], "quote": "SYNTHETIC page"},
            {"passage_id": state["other_work"], "quote": "SYNTHETIC page 2"},
            {"passage_id": "psg_P0000099", "quote": "void avoidance"}]}])
    app, _ = make(scripted(b))
    with TestClient(app) as raw:
        client = session(raw)
        view = planned(client)
        preview = client.get(f"/api/citation-checks/{view['id']}/preview").json()
        store = app.state.store
        b_item = next(i for i in preview["selected"] if i["target"] == "b")
        a_item = next(i for i in preview["selected"] if i["target"] == "a")
        state["not_given"] = next(p["id"] for p in store.passages_for(b_item["text_source_version_id"])
                                  if p["id"] not in b_item["passage_ids"])
        state["other_work"] = a_item["passage_ids"][0]
        check = b_check(run(client, view["id"]).json())["check"]
        assert (check["status"], check["result"]) == ("could_not_check", None)
        issues = check["error"]["issues"]
        assert [i["code"] for i in issues] == ["unknown_passage_id"] * 3
        assert {i["path"] for i in issues} == {f"/parts/0/evidence/{j}/passage_id" for j in range(3)}


def test_every_quote_rejected_is_could_not_check(make):
    def b(si, attempt):
        first = si["passages"][0]["passage_id"]
        return answer(si, [{"text": sentence(si).rstrip(" ."), "assessment": "partly", "evidence": [
            {"passage_id": first, "quote": "an invented sentence that no passage holds anywhere"},
            {"passage_id": first, "quote": "another invented quotation about lake ice"}]}])
    app, _ = make(scripted(b))
    with TestClient(app) as raw:
        client = session(raw)
        check = b_check(run(client, planned(client)["id"]).json())["check"]
        assert (check["status"], check["result"]) == ("could_not_check", None)
        assert [i["code"] for i in check["error"]["issues"]] == ["anchor_not_in_passage"] * 2


NEGATED = "SYNTHETIC page 7: void avoidance does not significantly improve delivery around holes in sparse networks."


def test_a_quote_that_drops_a_negation_is_refused(make, monkeypatch):
    """"significantly improves" is located in "does not significantly improve" by the fuzzy matcher; the check refuses
    the quote, so the part has no located quote and the pair cannot be checked."""
    import test_citation_check_text
    from deixis.domain.contracts import locate_anchor
    match = locate_anchor("void avoidance significantly improves delivery", NEGATED)
    assert match is not None and match.kind == "fuzzy" and match.ratio >= 0.9
    pages = list(test_citation_check_text.B_PAGES)
    pages[6] = NEGATED  # b's open-access PDF, page 7
    monkeypatch.setattr(test_citation_check_text, "B_PAGES", pages)

    def b(si, attempt):
        passage = next(p for p in si["passages"] if "does not" in p["text"])
        return answer(si, [{"text": sentence(si).rstrip(" ."), "assessment": "stated", "evidence": [
            {"passage_id": passage["passage_id"], "quote": "void avoidance significantly improves delivery"}]}])
    app, _ = make(scripted(b))
    with TestClient(app) as raw:
        client = session(raw)
        check = b_check(run(client, planned(client)["id"]).json())["check"]
        assert (check["status"], check["result"]) == ("could_not_check", None)
        assert [i["code"] for i in check["error"]["issues"]] == ["quote_meaning_differs"]
        assert "negation" in check["error"]["issues"][0]["message"]


def test_not_found_only_from_all_parts_not_stated_with_the_sentence_covered(make):
    def b(si, attempt):
        return answer(si, [{"text": "Void avoidance keeps packets moving", "assessment": "not_stated", "evidence": []},
                           {"text": "around holes", "assessment": "not_stated", "evidence": []}])
    app, _ = make(scripted(b))
    with TestClient(app) as raw:
        client = session(raw)
        view = run(client, planned(client)["id"]).json()
        assert (b_check(view)["status"], b_check(view)["result"]) == ("done", "not_found_in_given")
        assert b_check(view)["check"]["basis"]["passages_not_given"] == 3  # said only of the six given passages
        counters = view["counters"]
        assert (counters["pairs_done"], counters["pairs_found"], counters["pairs_not_found_in_given"]) == (4, 3, 1)


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


def test_a_succeeded_step_without_its_stored_result_is_read_back_not_resent(make):
    """A restart between the step's end and the result's write: the next check reads the step's output."""
    app, adapter = make()
    with TestClient(app) as raw:
        client = session(raw)
        draft_id = planned(client)["id"]
        view = run(client, draft_id).json()
        store = app.state.store
        first = next(p for _, p in pair_rows(view) if p["status"] == "done")
        with store.conn:
            store.conn.execute("DELETE FROM citation_checks WHERE pair_id = ?", (first["id"],))
            store.conn.execute("UPDATE citation_pairs SET status = 'planned' WHERE id = ?", (first["id"],))
        calls = len(adapter.calls)
        first_run = first["check"]["run_id"]
        # The recovery is asked for with another model: the stored result still names the model and run that answered.
        other = {"connection": "fake", "model": "other-model"}
        client.get(f"/api/citation-checks/{draft_id}/preview", params=other)
        view = client.post(f"/api/citation-checks/{draft_id}/check", json={"plan_revision": 1, **other}).json()
        assert len(adapter.calls) == calls and view["checked"]["checked_now"] == 1
        restored = next(p for _, p in pair_rows(view) if p["id"] == first["id"])
        assert (restored["status"], restored["result"]) == ("done", "found_whole")
        model = restored["check"]["model"]
        assert (model["connection"], model["requested_model"], model["resolved_model"], model["sent"]) == (
            "fake", "fake-model", "fake-model", True)
        assert restored["check"]["run_id"] == first_run != view["checked"]["run_id"]


def test_could_not_check_survives_a_restart_and_the_export(make, tmp_path):
    def b(si, attempt):
        return answer(si, [{"text": sentence(si).rstrip(" ."), "assessment": "stated", "evidence": []}])
    app, _ = make(scripted(b))
    with TestClient(app) as raw:
        client = session(raw)
        draft_id = planned(client)["id"]
        run(client, draft_id)
    app2, adapter2 = make()  # the same library, a new process
    with TestClient(app2) as raw:
        client = session(raw)
        view = client.get(f"/api/citation-checks/{draft_id}").json()
        assert (b_check(view)["status"], b_check(view)["result"]) == ("could_not_check", None)
        assert run(client, draft_id).json()["checked"]["status"] == "nothing_to_check" and adapter2.calls == []
        rows = list(csv.DictReader(io.StringIO(client.get(f"/api/citation-checks/{draft_id}/export").text)))
        assert [(r["target"], r["status"], r["result"], r["error"]) for r in rows] == [
            ("a", "done", "found_whole", ""), ("b", "could_not_check", "", "invalid_model_output"),
            ("c", "done", "found_whole", ""), ("d", "no_text", "", ""), ("a", "done", "found_whole", "")]
        assert rows[0]["depth"] == "full_text" and rows[2]["depth"] == "abstract" and rows[0]["located_quotes"]
        markdown = client.get(f"/api/citation-checks/{draft_id}/export", params={"format": "md"})
        assert markdown.headers["content-type"].startswith("text/markdown")
        assert "| could_not_check |" in markdown.text and markdown.text.count("\n") == 7


def test_the_check_reads_only_the_previewed_unstale_plan_and_names_a_model(make):
    app, adapter = make()
    with TestClient(app) as raw:
        client = session(raw)
        view = planned(client)
        draft_id = view["id"]
        # No model named and none in Settings: refused, nothing sent to any other model.
        refused = client.post(f"/api/citation-checks/{draft_id}/check", json={"plan_revision": 1})
        assert refused.status_code == 409 and refused.json()["code"] == "no_model"
        # A revision other than the frozen one the preview showed.
        refused = run(client, draft_id, revision=2)
        assert refused.status_code == 409 and refused.json()["code"] == "plan_revision_mismatch"
        # The frozen revision, never previewed: refused (the preview above was this test's only one, for revision 1,
        # so a fresh draft shows the rule).
        other = planned(client)
        refused = run(client, other["id"], preview=False)
        assert refused.status_code == 409 and refused.json()["code"] == "plan_not_previewed"
        client.get(f"/api/citation-checks/{other['id']}/preview", params={**MODEL, "reasoning_effort": "high"})
        refused = run(client, other["id"], preview=False)
        assert refused.status_code == 409 and refused.json()["code"] == "model_not_previewed"
        # The text of a planned pair changed after the freeze: refused until the person freezes and previews again.
        upload(client, view, "b", ["SYNTHETIC doi:10.5555/syn.b Void avoidance in sparse acoustic networks.",
                                   "SYNTHETIC: void avoidance keeps packets moving around holes."])
        client.post(f"/api/citation-checks/{draft_id}/acquire")
        refused = run(client, draft_id)
        assert refused.status_code == 409 and refused.json()["code"] == "plan_stale" and refused.json()["pairs"] == [2]
        assert adapter.calls == [] and client.get(f"/api/citation-checks/{draft_id}").json()["check_run"] is None
        assert client.get(f"/api/citation-checks/{draft_id}").json()["counters"]["pairs_sent_to_model"] is None
        frozen(client, draft_id, refreeze=True)
        view = run(client, draft_id, revision=2).json()
        assert view["checked"]["status"] == "completed"
        assert b_check(view)["check"]["plan_revision"] == 2
        # With no literature model in Settings, a request that names none is refused even with nothing left to send.
        assert client.post(f"/api/citation-checks/{draft_id}/check", json={"plan_revision": 2}).status_code == 409


def test_results_carry_the_identity_flag_of_the_revision_they_read(make):
    app, _ = make()
    with TestClient(app) as raw:
        client = session(raw)
        view = planned(client, pdf=["SYNTHETIC doi:10.9999/other.paper An unrelated study of lake ice."])
        view = run(client, view["id"]).json()
        a_pairs = [p for _, p in pair_rows(view) if p["target"] == "a"]
        assert all("identity_unconfirmed" in p["check"]["flags"] for p in a_pairs)
        assert all(p["result"] == "found_whole" for p in a_pairs)  # a flag never changes a result
        c = next(p for _, p in pair_rows(view) if p["target"] == "c")  # an abstract: no file to identify
        assert "identity_unconfirmed" not in c["check"]["flags"]


def test_the_settings_literature_model_is_the_default_and_the_cap_holds(make):
    app, adapter = make()
    with TestClient(app) as raw:
        client = session(raw)
        draft = b" ".join(b"Claim %d about mobile sinks holds \\cite{c}." % i for i in range(1, 204))
        view = start(client, draft)
        client.post(f"/api/citation-checks/{view['id']}/acquire")
        frozen(client, view["id"])
        store = app.state.store
        store.set_setting("literature", {"model_connection": "fake", "model": "fake-literature", "reasoning_effort": None})
        # Previewed for fake-model only: a check on the Settings model is refused until that model is previewed.
        client.get(f"/api/citation-checks/{view['id']}/preview", params=MODEL)
        refused = client.post(f"/api/citation-checks/{view['id']}/check", json={"plan_revision": 1})
        assert refused.status_code == 409 and refused.json()["code"] == "model_not_previewed"
        client.get(f"/api/citation-checks/{view['id']}/preview")
        view = client.post(f"/api/citation-checks/{view['id']}/check", json={"plan_revision": 1}).json()
        assert view["checked"]["checked_now"] == citation_check.MAX_PAIRS_TO_MODEL == 200
        assert len(adapter.calls) == 200 and {s[1] for s in adapter.sent} == {"fake-literature"}
        counters = view["counters"]
        assert (counters["pairs_done"], counters["pairs_out_of_cap"], counters["pairs_to_send"]) == (200, 3, 0)
