"""Follow-up questions (UI parity S22a, F17). SYNTHETIC records and the fake adapter: these tests show the workflow
(the passages actually sent are the allowlist, anchors located, fail-closed citations, no search, atomic publication,
the turn's own budget, pause and resume without a second call, model_mismatch, the not-answered path), not whether a
model answers a follow-up well.
"""

import asyncio
import json

import httpx
from fastapi.testclient import TestClient

from deixis.api.app import create_app
from deixis.domain import contracts, skill
from deixis.domain.rules import RevisionConflict
from deixis.workflow import fast_answer, followup
from fakes import FakeAdapter, valid_response
from helpers import make_pdf
from test_api_flow import app_for, create, fake_fetch, session, sw_settings, wait_run

PAGES = [
    "SYNTHETIC. The release schedule uses a binary variable per time slot to decide when molecules are emitted.",
    "SYNTHETIC. Interference between symbols is bounded by a linear constraint on the emitted amount.",
    "SYNTHETIC. The bibliography lists unrelated works on acoustic modems and ocean sensing.",
]
QUESTION = "Which binary variable decides the release time slot?"


def upload(client, rid, name, pages):
    response = client.post(f"/api/researches/{rid}/uploads", files={"file": (name, make_pdf(pages), "application/pdf")})
    assert response.status_code == 201, response.text
    return response.json()["uploaded_source_version_id"]


def research(client, files=(("a.pdf", PAGES),)):
    rid = create(client, source_scope="attached")
    svids = [upload(client, rid, name, pages) for name, pages in files]
    return rid, svids


def revision(client, rid):
    return client.get(f"/api/researches/{rid}").json()["scope"]["revision"]


def ask(client, rid, question=QUESTION, key=None, expected=None):
    headers = {"Idempotency-Key": key} if key else {}
    return client.post(f"/api/researches/{rid}/followup-turns", headers=headers,
                       json={"question": question, "expected_scope_revision": expected or revision(client, rid)})


def answered(client, rid, question=QUESTION, statuses=("completed", "failed", "paused", "cancelled")):
    response = ask(client, rid, question)
    assert response.status_code == 202, response.text
    turn = response.json()
    wait_run(client, rid, turn["run"]["id"], statuses)
    return client.get(f"/api/researches/{rid}/followup-turns/{turn['id']}").json()


def step_inputs(app, run_id):
    return [json.loads(r[0]) for r in app.state.store.conn.execute(
        "SELECT payload_json FROM step_inputs WHERE run_id = ? ORDER BY attempt", (run_id,))]


def test_a_follow_up_is_answered_from_the_passages_sent_and_cites_located_anchors(tmp_path):
    adapter = FakeAdapter()
    app = app_for(tmp_path, adapter)
    with TestClient(app) as client:
        session(client)
        rid, (svid,) = research(client)
        turn = answered(client, rid)
        assert turn["status"] == "answered" and turn["run"]["status"] == "completed"
        assert turn["question"] == QUESTION and turn["stale_scope"] is False
        (payload,) = step_inputs(app, turn["run"]["id"])
        # The turn's question replaces the research question in this StepInput only.
        assert payload["task_type"] == "followup_answer" and payload["question"]["text"] == QUESTION
        assert payload["skill_files"] == ["SKILL.md", "followup.md"]
        assert payload["budget"]["max_model_calls"] == followup.CALLS
        sent = [p["passage_id"] for p in payload["passages"]]
        # The allowlist is exactly the passages and sources sent in this call, and it is stored with its StepInput.
        assert payload["allowlist"]["passage_ids"] == sent and payload["allowlist"]["source_ids"] == [svid]
        assert turn["passages_given"] == len(sent) and turn["passages_considered"] >= len(sent)
        # The live steps read the stored step rows: the selection's count is the call's allowlist (UI parity S22b).
        assert turn["progress"] == {"passages_selected": len(sent), "answer_step": "succeeded",
                                    "more_passages": None, "more_step": None,
                                    "more_error": None}
        selection = app.state.store.existing_step(turn["run"]["id"], followup.SELECTION_KEY)["output"]
        assert selection["passage_ids"] == sent and selection["basis"] == "included_works"
        # The page naming the binary variable ranks first: the lexical ranking matched the turn's words.
        assert "binary variable" in payload["passages"][0]["text"]
        (claim,) = turn["answer"]["claims"]
        (citation,) = claim["citations"]
        assert citation["passage_id"] == sent[0] and citation["source_version_id"] == svid
        assert citation["anchor_text"] and citation["anchor_match"] == "exact"
        assert citation["anchor_text"] in app.state.store.passage(sent[0])["text"]
        # The follow-up answer is not the research's answer, and no search ran.
        view = client.get(f"/api/researches/{rid}").json()
        assert view["answers"] == [] and view["search_runs"] == []
        assert [t["id"] for t in client.get(f"/api/researches/{rid}/followup-turns").json()] == [turn["id"]]


def test_the_allowlist_holds_only_the_passages_actually_selected(tmp_path):
    many = [f"SYNTHETIC page {n}. Release slot number {n} is reported without a variable." for n in range(30)]
    adapter = FakeAdapter()
    app = app_for(tmp_path, adapter)
    with TestClient(app) as client:
        session(client)
        rid, (svid,) = research(client, (("long.pdf", many),))
        turn = answered(client, rid)
        (payload,) = step_inputs(app, turn["run"]["id"])
        pool = {p["id"] for p in app.state.store.passages_for(svid)}
        sent = set(payload["allowlist"]["passage_ids"])
        limit = app.state.store.run(turn["run"]["id"])["budget"]["max_followup_passages"]
        assert len(sent) == limit < len(pool) and sent < pool
        assert sent == {p["passage_id"] for p in payload["passages"]}
        # A passage of this research that was not sent cannot be cited: validation rejects it.
        unsent = sorted(pool - sent)[0]
        draft = json.loads(valid_response(payload))
        draft["claims"][0]["passage_ids"] = [unsent]
        draft["citation_anchors"][0]["passage_id"] = unsent
        assert "unknown_passage_id" in contracts.validate_model_output(payload, draft).codes()


def test_an_invented_locator_or_unlocatable_anchor_fails_closed(tmp_path):
    def invents(si):
        draft = json.loads(valid_response(si))
        if si["task_type"] == "followup_answer":
            draft["claims"][0]["text"] = "Equation 4 on page 12 proves the slot schedule is optimal."
            draft["citation_anchors"][0]["quote"] = "a sentence that is in no passage at all"
        return json.dumps(draft)

    adapter = FakeAdapter(invents)
    app = app_for(tmp_path, adapter)
    with TestClient(app) as client:
        session(client)
        rid, _ = research(client)
        turn = answered(client, rid)
        assert len(adapter.calls) == 2  # the call and its one repair, then it stops; no second round follows
        assert turn["status"] == "unverified_draft" and turn["answer"] is None
        assert {i["code"] for i in turn["issues"]} == {"locator_in_claim_text", "anchor_not_in_passage"}
        assert app.state.store.conn.execute("SELECT COUNT(*) FROM followup_turn_links").fetchone()[0] == 0


def test_a_repair_publishes_once_the_anchor_locates(tmp_path):
    calls = []

    def first_misquotes(si):
        calls.append(si["task_type"])
        draft = json.loads(valid_response(si))
        if len(calls) == 1:
            draft["citation_anchors"][0]["quote"] = "a sentence that is in no passage at all"
        return json.dumps(draft)

    app = app_for(tmp_path, FakeAdapter(first_misquotes))
    with TestClient(app) as client:
        session(client)
        rid, _ = research(client)
        turn = answered(client, rid)
        assert calls == ["followup_answer", "followup_answer"] and turn["status"] == "answered"
        assert turn["answer"]["claims"][0]["citations"][0]["anchor_text"]


def test_passages_that_do_not_say_give_a_not_answered_turn(tmp_path):
    def does_not_say(si):
        if si["task_type"] != "followup_answer":
            return valid_response(si)
        return json.dumps(json.loads(valid_response(si)) | {
            "outcome": "not_answered", "claims": [], "citation_anchors": [],
            "unanswered_aspects": ["None of the given passages reports the lifetime of the network in hours."]})

    app = app_for(tmp_path, FakeAdapter(does_not_say))
    with TestClient(app) as client:
        session(client)
        rid, _ = research(client)
        turn = answered(client, rid, "How long does the network live, in hours?")
        assert turn["status"] == "not_answered" and turn["answer"]["claims"] == []
        assert turn["answer"]["unanswered_aspects"]
        # It starts no search; a new search is the person's own scope revision with this question.
        view = client.get(f"/api/researches/{rid}").json()
        assert view["search_runs"] == [] and view["scope"]["revision"] == turn["scope_revision"]


def test_a_research_without_passages_answers_no_passages_without_a_model_call(tmp_path):
    adapter = FakeAdapter()
    app = app_for(tmp_path, adapter)
    with TestClient(app) as client:
        session(client)
        rid = create(client, source_scope="attached")
        turn = answered(client, rid)
        assert turn["status"] == "no_passages" and turn["run"]["status"] == "completed"
        assert adapter.calls == [] and turn["passages_considered"] == 0 and turn["answer"] is None
        assert turn["progress"] == {"passages_selected": None, "answer_step": None,
                                    "more_passages": None, "more_step": None,
                                    "more_error": None}


def test_no_search_or_provider_request_is_started(tmp_path):
    seen = []

    def handler(request):
        seen.append(str(request.url))
        return httpx.Response(500)

    app = create_app(sw_settings(tmp_path), adapters={"fake": FakeAdapter()},
                     http_client=httpx.AsyncClient(transport=httpx.MockTransport(handler)), fetcher=fake_fetch,
                     extra_hosts=("testserver",), trusted_clients=("testclient",))
    with TestClient(app) as client:
        session(client)
        rid, _ = research(client)
        seen.clear()
        turn = answered(client, rid)
        assert turn["status"] == "answered" and seen == []
        store = app.state.store
        run = store.run(turn["run"]["id"])
        assert run["budget"]["max_provider_requests"] == 0
        assert store.conn.execute("SELECT COUNT(*) FROM search_runs").fetchone()[0] == 0
        assert {r[0] for r in store.conn.execute("SELECT DISTINCT kind FROM run_steps WHERE run_id = ?", (run["id"],))} == {
            "code:followup_pool", "code:followup_passages", "code:followup_conversation", "model:followup_answer"}


def test_pause_during_the_call_publishes_on_resume_without_a_second_call(tmp_path):
    holder = {}

    def responder(si):
        if si["task_type"] == "followup_answer" and not holder.get("paused"):
            holder["paused"] = True
            holder["app"].state.store.update_run(si["run_id"], event="run_pause_requested", status="pause_requested",
                                                 pause_reason="user_requested")
        return valid_response(si)

    adapter = FakeAdapter(responder)
    holder["app"] = app = app_for(tmp_path, adapter)
    with TestClient(app) as client:
        session(client)
        rid, _ = research(client)
        response = ask(client, rid)
        turn = response.json()
        _, run = wait_run(client, rid, turn["run"]["id"])
        assert (run["status"], run["pause_reason"]) == ("paused", "user_requested")
        paused = client.get(f"/api/researches/{rid}/followup-turns/{turn['id']}").json()
        assert paused["status"] == "pending" and paused["passages_given"] is None
        # While unpublished the turn's steps still say what is stored: the selection and the finished call.
        sent = step_inputs(app, run["id"])[0]["passages"]
        assert paused["progress"] == {"passages_selected": len(sent), "answer_step": "succeeded",
                                    "more_passages": None, "more_step": None,
                                    "more_error": None}
        assert client.post(f"/api/runs/{run['id']}/resume").status_code == 200
        wait_run(client, rid, run["id"])
        turn = client.get(f"/api/researches/{rid}/followup-turns/{turn['id']}").json()
        assert turn["status"] == "answered" and len(adapter.calls) == 1


def test_output_from_another_model_is_recorded_but_not_published(tmp_path):
    adapter = FakeAdapter(resolved_model="some-other-model")
    app = app_for(tmp_path, adapter)
    with TestClient(app) as client:
        session(client)
        rid, _ = research(client)
        turn = answered(client, rid)
        assert (turn["run"]["status"], turn["run"]["pause_reason"]) == ("paused", "model_mismatch")
        assert turn["status"] == "pending" and turn["answer"] is None and len(adapter.calls) == 1


def test_the_turn_has_its_own_budget_and_the_one_active_run_rule(tmp_path):
    holder, refused = {}, []

    def always_bad(si):
        if si["task_type"] == "followup_answer" and not refused:
            try:
                followup.request_turn(holder["app"].state.store, si["research_id"], "A second question?", 1, None)
            except RevisionConflict as exc:
                refused.append(str(exc))
        return json.dumps(json.loads(valid_response(si)) | {"claims": [], "citation_anchors": []})

    holder["app"] = app = app_for(tmp_path, FakeAdapter(always_bad))
    with TestClient(app) as client:
        session(client)
        rid, _ = research(client)
        turn = answered(client, rid)
        run = app.state.store.run(turn["run"]["id"])
        # The turn's own four calls (two rounds), whatever the research's other runs used; an invalid first round
        # spends its call and its one repair and asks no second round.
        assert run["budget"]["max_model_calls"] == followup.CALLS == 4 and run["usage"]["model_calls"] == 2
        assert turn["status"] == "unverified_draft" and turn["answer"] is None
        assert {i["code"] for i in turn["issues"]} == {"followup_answer_without_claims"}
        assert refused and "still active" in refused[0]  # one active run per research
        assert len(client.get(f"/api/researches/{rid}/followup-turns").json()) == 1


def test_requests_are_checked_and_replayed_by_their_key(tmp_path):
    app = app_for(tmp_path, FakeAdapter())
    with TestClient(app) as client:
        session(client)
        rid, _ = research(client)
        assert ask(client, rid, "   ").status_code == 422
        assert ask(client, rid, expected=revision(client, rid) + 1).status_code == 409
        first = ask(client, rid, key="k1")
        again = ask(client, rid, key="k1")
        assert first.status_code == again.status_code == 202 and first.json()["id"] == again.json()["id"]
        assert ask(client, rid, "Another question?", key="k1").status_code == 409
        wait_run(client, rid, first.json()["run"]["id"])
        assert client.get(f"/api/researches/{rid}/followup-turns/fut_missing0000000000").status_code == 404
        assert client.get("/api/researches/res_missing0000000000/followup-turns").status_code == 404


def test_a_newer_question_revision_stops_an_unpublished_turn(tmp_path):
    holder = {}

    def revise(si):
        if si["task_type"] == "followup_answer":
            store = holder["app"].state.store
            research = store.research(si["research_id"])
            store.revise_scope(research["id"], research["version"], "A revised SYNTHETIC question about slots?", None)
        return valid_response(si)

    holder["app"] = app = app_for(tmp_path, FakeAdapter(revise))
    with TestClient(app) as client:
        session(client)
        rid, _ = research(client)
        turn = ask(client, rid).json()
        _, run = wait_run(client, rid, turn["run"]["id"])
        assert (run["status"], run["pause_reason"]) == ("cancelled", "scope_revised")
        row = app.state.store.conn.execute("SELECT status FROM followup_turns WHERE id = ?", (turn["id"],)).fetchone()
        assert row["status"] == "pending"


def test_a_later_step_input_carries_the_new_package_hash_and_stored_ones_stay(tmp_path, monkeypatch):
    app = app_for(tmp_path, FakeAdapter())
    with TestClient(app) as client:
        session(client)
        rid, _ = research(client)
        first = answered(client, rid)
        store, flow = app.state.store, app.state.worker.flow
        stored = "SELECT id, skill_package_hash, payload_json, developer_instructions FROM step_inputs WHERE run_id = ?"
        before = [tuple(r) for r in store.conn.execute(stored, (first["run"]["id"],))]
        old_hash = flow.deps.package.package_hash
        assert before and all(r[1] == old_hash == json.loads(r[2])["skill_package_hash"] for r in before)
        # A changed method file gives a new package hash for later StepInputs; stored ones are never rewritten.
        changed = skill.SkillPackage(root=skill.SKILL_DIR, package_hash="sha256:" + "f" * 64,
                                     files=flow.deps.package.files)
        monkeypatch.setattr(flow.deps, "package", changed)
        second = answered(client, rid, "Which constraint bounds interference?")
        (later,) = step_inputs(app, second["run"]["id"])
        assert later["skill_package_hash"] == "sha256:" + "f" * 64 != old_hash
        assert [tuple(r) for r in store.conn.execute(stored, (first["run"]["id"],))] == before


def test_basis_answer_input_uses_the_frozen_answer_evidence_and_drops_a_later_exclusion(tmp_path):
    from test_fast_path_answer import answer_run, cutoff, setup, user
    lib = setup(tmp_path, n=3)
    cutoff(lib)
    run = answer_run(lib)
    asyncio.run(fast_answer.answer(lib.flow, run, lib.store.scope(lib.rid)))
    plan = lib.store.existing_step(run["id"], fast_answer.INPUT)["output"]
    assert plan["passage_ids"]
    frozen = followup.pool(lib.store, lib.rid, 1)
    assert frozen["basis"] == "answer_input" and frozen["answer_run_id"] == run["id"]
    assert set(frozen["sources"]) == {i["source_version_id"] for i in plan["items"]}
    user(lib, lib.sources[0], "excluded")
    assert lib.sources[0] not in followup.pool(lib.store, lib.rid, 1)["sources"]


def test_semantic_ranking_over_the_pool_is_fused_with_the_lexical_one(tmp_path, monkeypatch):
    """A Turkish follow-up over English pages matches no word; the semantic ranking (RRF-fused) still puts the page that
    answers it first, and only the pool's passages are embedded. The embedding provider is a SYNTHETIC mock."""
    monkeypatch.setenv("GEMINI_API_KEY", "test-key")
    embedded = []

    def handler(request):
        body = json.loads(request.content)
        vectors = []
        for item in body["requests"]:
            text = item["content"]["parts"][0]["text"]
            embedded.append((item["taskType"], text))
            on_topic = item["taskType"] == "RETRIEVAL_QUERY" or "interference" in text.lower()
            vectors.append({"values": [1.0, 0.0] if on_topic else [0.0, 1.0]})
        return httpx.Response(200, json={"embeddings": vectors})

    app = create_app(sw_settings(tmp_path), adapters={"fake": FakeAdapter()},
                     http_client=httpx.AsyncClient(transport=httpx.MockTransport(handler)), fetcher=fake_fetch,
                     extra_hosts=("testserver",), trusted_clients=("testclient",))
    with TestClient(app) as client:
        session(client)
        rid, (svid,) = research(client)
        embedded.clear()
        turn = answered(client, rid, "Semboller arası girişim nasıl sınırlanıyor?")
        assert turn["status"] == "answered"
        (payload,) = step_inputs(app, turn["run"]["id"])
        assert "Interference between symbols" in payload["passages"][0]["text"]
        selection = app.state.store.existing_step(turn["run"]["id"], followup.SELECTION_KEY)["output"]
        assert selection["lexical_matches"] == 0 and selection["semantic_matches"] > 0
        assert selection["semantic_step"] == "succeeded"
        pool = {p["text"] for p in app.state.store.passages_for(svid)}
        assert {text for kind, text in embedded if kind == "RETRIEVAL_DOCUMENT"} <= pool
        assert ("RETRIEVAL_QUERY", "Semboller arası girişim nasıl sınırlanıyor?\nHow is molecule release scheduling optimized?") in embedded


def exclude(store, rid, svid, state="excluded"):
    version = store.conn.execute("SELECT version FROM selections WHERE research_id = ? AND source_version_id = ?",
                                 (rid, svid)).fetchone()[0]
    store.set_user_selection(rid, svid, state, version, "SYNTHETIC person choice")


def asset_of(store, svid):
    return store.conn.execute("SELECT id FROM source_assets WHERE source_version_id = ? AND removed_at IS NULL",
                              (svid,)).fetchone()[0]


def during_call(change):
    """A responder that lets `change(store, si)` happen while the follow-up call is out, then answers validly."""
    holder = {}

    def respond(si):
        if si["task_type"] == "followup_answer" and not holder.get("done"):
            holder["done"] = True
            change(holder["app"].state.store, si)
        return valid_response(si)
    return holder, respond


def test_a_selection_change_during_the_call_stops_publication(tmp_path):
    def change(store, si):
        svid = store.conn.execute("SELECT source_version_id FROM corpus_memberships WHERE research_id = ?",
                                  (si["research_id"],)).fetchone()[0]
        exclude(store, si["research_id"], svid)

    holder, respond = during_call(change)
    holder["app"] = app = app_for(tmp_path, FakeAdapter(respond))
    with TestClient(app) as client:
        session(client)
        rid, _ = research(client)
        turn = answered(client, rid)
        assert (turn["run"]["status"], turn["run"]["pause_reason"]) == ("failed", followup.SELECTION_CHANGED)
        assert turn["status"] == "pending" and turn["answer"] is None
        store = app.state.store
        assert store.conn.execute("SELECT COUNT(*) FROM followup_turn_links").fetchone()[0] == 0
        assert not store.conn.execute("SELECT 1 FROM events WHERE type = 'followup_answered'").fetchone()


def test_a_pdf_removed_during_the_call_stops_publication(tmp_path):
    def remove(store, si):
        svid = store.conn.execute("SELECT source_version_id FROM corpus_memberships WHERE research_id = ?",
                                  (si["research_id"],)).fetchone()[0]
        store.remove_asset(si["research_id"], svid, asset_of(store, svid))

    holder, respond = during_call(remove)
    holder["app"] = app = app_for(tmp_path, FakeAdapter(respond))
    with TestClient(app) as client:
        session(client)
        rid, _ = research(client)
        turn = answered(client, rid)
        assert turn["run"]["status"] == "failed"
        assert turn["run"]["pause_reason"] in (followup.SOURCES_CHANGED, followup.SELECTION_CHANGED)
        assert turn["status"] == "pending"


def test_a_change_while_paused_stops_the_resumed_turn_unpublished(tmp_path):
    holder = {}

    def pause_first(si):
        if si["task_type"] == "followup_answer" and not holder.get("paused"):
            holder["paused"] = True
            holder["app"].state.store.update_run(si["run_id"], event="run_pause_requested", status="pause_requested",
                                                 pause_reason="user_requested")
        return valid_response(si)

    adapter = FakeAdapter(pause_first)
    holder["app"] = app = app_for(tmp_path, adapter)
    with TestClient(app) as client:
        session(client)
        rid, (svid,) = research(client)
        turn = ask(client, rid).json()
        _, run = wait_run(client, rid, turn["run"]["id"])
        assert run["status"] == "paused" and len(adapter.calls) == 1
        exclude(app.state.store, rid, svid)
        client.post(f"/api/runs/{run['id']}/resume")
        _, run = wait_run(client, rid, run["id"])
        # The stored valid output is not published: the resumed run finds the selection changed first.
        assert (run["status"], run["pause_reason"]) == ("failed", followup.SELECTION_CHANGED) and len(adapter.calls) == 1
        assert client.get(f"/api/researches/{rid}/followup-turns/{turn['id']}").json()["status"] == "pending"


def test_a_change_before_the_repair_is_sent_stops_it_at_the_send_gate(tmp_path):
    holder = {}

    def invalid_and_change(si):
        if si["task_type"] == "followup_answer" and not holder.get("done"):
            holder["done"] = True
            store = holder["app"].state.store
            svid = store.conn.execute("SELECT source_version_id FROM corpus_memberships WHERE research_id = ?",
                                      (si["research_id"],)).fetchone()[0]
            exclude(store, si["research_id"], svid)
        return json.dumps(json.loads(valid_response(si)) | {"claims": [], "citation_anchors": []})

    adapter = FakeAdapter(invalid_and_change)
    holder["app"] = app = app_for(tmp_path, adapter)
    with TestClient(app) as client:
        session(client)
        rid, _ = research(client)
        turn = answered(client, rid)
        assert (turn["run"]["status"], turn["run"]["pause_reason"]) == ("failed", followup.SELECTION_CHANGED)
        assert len(adapter.calls) == 1 and turn["status"] == "pending"


def test_a_published_turn_shows_a_later_selection_change_apart_from_the_question(tmp_path):
    app = app_for(tmp_path, FakeAdapter())
    with TestClient(app) as client:
        session(client)
        rid, (svid,) = research(client)
        turn = answered(client, rid)
        assert turn["stale_selection"] is False and turn["stale_scope"] is False
        exclude(app.state.store, rid, svid)
        turn = client.get(f"/api/researches/{rid}/followup-turns/{turn['id']}").json()
        assert turn["stale_selection"] is True and turn["stale_scope"] is False and turn["status"] == "answered"


def test_a_source_the_person_set_pending_leaves_the_pool(tmp_path):
    from test_fast_path_answer import answer_run, cutoff, setup, user
    lib = setup(tmp_path, n=3)
    cutoff(lib)
    run = answer_run(lib)
    asyncio.run(fast_answer.answer(lib.flow, run, lib.store.scope(lib.rid)))
    frozen = followup.pool(lib.store, lib.rid, 1)
    assert lib.sources[1] in frozen["sources"]
    user(lib, lib.sources[1], "pending")  # a user selection in state `pending`, after the answer froze its input
    later = followup.pool(lib.store, lib.rid, 1)
    assert lib.sources[1] not in later["sources"] and set(later["sources"]) < set(frozen["sources"])
    assert followup.changed(lib.store, lib.rid, frozen) == followup.SELECTION_CHANGED


def test_a_pause_at_the_second_invalid_output_publishes_the_draft_on_resume_without_a_call(tmp_path):
    holder, calls = {}, []

    def invalid_then_pause(si):
        calls.append(si["task_type"])
        if len(calls) == 2:  # the repair's output comes back invalid while a pause is requested
            holder["app"].state.store.update_run(si["run_id"], event="run_pause_requested", status="pause_requested",
                                                 pause_reason="user_requested")
        return json.dumps(json.loads(valid_response(si)) | {"claims": [], "citation_anchors": []})

    adapter = FakeAdapter(invalid_then_pause)
    holder["app"] = app = app_for(tmp_path, adapter)
    with TestClient(app) as client:
        session(client)
        rid, _ = research(client)
        turn = ask(client, rid).json()
        _, run = wait_run(client, rid, turn["run"]["id"])
        assert (run["status"], run["pause_reason"]) == ("paused", "user_requested") and len(adapter.calls) == 2
        assert client.get(f"/api/researches/{rid}/followup-turns/{turn['id']}").json()["status"] == "pending"
        client.post(f"/api/runs/{run['id']}/resume")
        _, run = wait_run(client, rid, run["id"])
        turn = client.get(f"/api/researches/{rid}/followup-turns/{turn['id']}").json()
        assert run["status"] == "completed" and turn["status"] == "unverified_draft" and turn["answer"] is None
        assert len(adapter.calls) == 2 and app.state.store.run(run["id"])["usage"]["model_calls"] == 2


def test_a_pdf_cited_only_by_a_follow_up_still_opens_after_its_source_is_removed(tmp_path):
    app = app_for(tmp_path, FakeAdapter())
    with TestClient(app) as client:
        session(client)
        rid, (svid,) = research(client)
        turn = answered(client, rid)
        assert turn["answer"]["claims"][0]["citations"][0]["reading_depth"] == "selected_sections"
        aid = asset_of(app.state.store, svid)
        assert client.request("DELETE", f"/api/researches/{rid}/sources", json={"source_version_ids": [svid]}).status_code == 200
        assert client.get(f"/api/researches/{rid}/assets/{aid}").status_code == 200
        assert app.state.store.asset_impact(aid)["followup_quotes"] == 1
        # Another research never reaches it through this one's follow-up.
        other, _ = research(client, (("b.pdf", ["SYNTHETIC other study."]),))
        assert client.get(f"/api/researches/{other}/assets/{aid}").status_code == 404


def test_a_failed_link_insert_rolls_the_turn_and_its_event_back_together(tmp_path, monkeypatch):
    real = contracts.derive_evidence_links

    def broken(payload, result):
        return [link | {"passage_id": "psg_missing000000000000"} for link in real(payload, result)]

    monkeypatch.setattr(followup.contracts, "derive_evidence_links", broken)
    app = app_for(tmp_path, FakeAdapter())
    with TestClient(app) as client:
        session(client)
        rid, _ = research(client)
        turn = answered(client, rid)
        assert turn["run"]["status"] in ("failed", "paused") and turn["status"] == "pending"
        store = app.state.store
        row = store.conn.execute("SELECT * FROM followup_turns WHERE id = ?", (turn["id"],)).fetchone()
        assert row["published_at"] is None and row["draft_json"] is None and row["step_input_id"] is None
        assert store.conn.execute("SELECT COUNT(*) FROM followup_turn_links").fetchone()[0] == 0
        assert not store.conn.execute("SELECT 1 FROM events WHERE type = 'followup_answered'").fetchone()


def test_a_pause_at_the_first_invalid_output_sends_no_repair_until_resumed(tmp_path):
    holder = {}

    def invalid_and_pause(si):
        if not holder.get("paused"):
            holder["paused"] = True  # the first output comes back invalid while a pause is requested
            holder["app"].state.store.update_run(si["run_id"], event="run_pause_requested", status="pause_requested",
                                                 pause_reason="user_requested")
        return json.dumps(json.loads(valid_response(si)) | {"claims": [], "citation_anchors": []})

    adapter = FakeAdapter(invalid_and_pause)
    holder["app"] = app = app_for(tmp_path, adapter)
    with TestClient(app) as client:
        session(client)
        rid, _ = research(client)
        turn = ask(client, rid).json()
        _, run = wait_run(client, rid, turn["run"]["id"])
        # The send gate checks the pause before the repair is built: no second call while paused.
        assert (run["status"], run["pause_reason"]) == ("paused", "user_requested") and len(adapter.calls) == 1
        client.post(f"/api/runs/{run['id']}/resume")
        _, run = wait_run(client, rid, run["id"])
        turn = client.get(f"/api/researches/{rid}/followup-turns/{turn['id']}").json()
        # The resumed run sends the one repair from the stored invalid output, then closes fail-closed.
        assert run["status"] == "completed" and turn["status"] == "unverified_draft" and len(adapter.calls) == 2


def test_a_question_revision_during_the_health_check_sends_no_first_call(tmp_path):
    holder = {}

    class RevisingAdapter(FakeAdapter):
        async def health(self, refresh=False):
            store = holder["app"].state.store
            opened = store.conn.execute("SELECT run_id FROM run_steps WHERE operation_key = ?",
                                        (followup.TASK,)).fetchone()
            if opened and not holder.get("revised"):
                holder["revised"] = True
                research = store.research(store.run(opened["run_id"])["research_id"])
                store.revise_scope(research["id"], research["version"], "A revised SYNTHETIC question about slots?", None)
            return await super().health(refresh)

    adapter = RevisingAdapter()
    holder["app"] = app = app_for(tmp_path, adapter)
    with TestClient(app) as client:
        session(client)
        rid, _ = research(client)
        turn = ask(client, rid).json()
        _, run = wait_run(client, rid, turn["run"]["id"])
        assert holder.get("revised") and adapter.calls == []
        assert (run["status"], run["pause_reason"]) == ("cancelled", "scope_revised")
        assert client.get(f"/api/researches/{rid}/followup-turns/{turn['id']}").json()["status"] == "pending"


def test_spent_calls_after_a_transport_error_close_the_stored_invalid_output_as_a_draft(tmp_path):
    from deixis.models.adapter import ModelStepResult

    adapter = FakeAdapter(lambda si: json.dumps(json.loads(valid_response(si)) | {"claims": [], "citation_anchors": []}),
                          fail=lambda si: ModelStepResult("failed", error="SYNTHETIC connection reset")
                          if len(adapter.calls) <= 3 else None)
    app = app_for(tmp_path, adapter)
    with TestClient(app) as client:
        session(client)
        rid, _ = research(client)
        turn = ask(client, rid).json()
        _, run = wait_run(client, rid, turn["run"]["id"])
        assert run["status"] == "paused" and app.state.store.run(run["id"])["usage"]["model_calls"] == 1
        while run["status"] == "paused":  # three transport errors spend three of the turn's four calls
            client.post(f"/api/runs/{run['id']}/resume")
            _, run = wait_run(client, rid, run["id"])
        turn = client.get(f"/api/researches/{rid}/followup-turns/{turn['id']}").json()
        # The second call came back invalid and no call is left for its repair: the turn closes as that draft
        # instead of pausing again with budget_exhausted.
        assert (run["status"], run["pause_reason"]) == ("completed", None), run
        assert turn["status"] == "unverified_draft" and turn["answer"] is None and turn["issues"]
        assert len(adapter.calls) == 4 and app.state.store.run(run["id"])["usage"]["model_calls"] == 4


def test_follow_up_citations_carry_the_answer_views_evidence_marks_and_warnings(tmp_path):
    app = app_for(tmp_path, FakeAdapter())
    with TestClient(app) as client:
        session(client)
        rid, (svid,) = research(client)
        turn = answered(client, rid)
        (citation,) = turn["answer"]["claims"][0]["citations"]
        assert (citation["evidence_status"], citation["removed_from_research"], citation["rendition"]) == ("current", False, False)
        assert citation["text_source"] == "text_layer" and turn["answer"]["warnings"] == []
        aid = asset_of(app.state.store, svid)
        assert client.request("DELETE", f"/api/researches/{rid}/sources", json={"source_version_ids": [svid]}).status_code == 200
        (citation,) = client.get(f"/api/researches/{rid}/followup-turns/{turn['id']}").json()["answer"]["claims"][0]["citations"]
        assert citation["removed_from_research"] is True and citation["source_version_id"] == svid
        assert app.state.store.asset_impact(aid)["followup_quotes"] == 1


def published_version_of(lib, svid):
    """A SYNTHETIC published version (its own DOI) of `svid`'s work, added to the research: it now heads the work."""
    from deixis.providers.common import ProviderRecord
    record = ProviderRecord(provider_record_id="published", title="SYNTHETIC published", authors=[], year=None,
                            venue=None, publication_type=None, doi="10.5555/synthetic.published", landing_url=None,
                            oa_pdf_url=None, oa_pdf_version=None, version_label=None, abstract="SYNTHETIC published.",
                            abstract_origin="provider", identifiers={}, raw={})
    new, _ = lib.store.upsert_provider_source("known_list", record, None)
    work = lib.store.source(svid)["work_id"]
    lib.store.conn.execute("UPDATE source_versions SET work_id = ? WHERE id = ?", (work, new))
    lib.store.add_to_corpus(lib.rid, new, "search")
    assert lib.store.work_heads(lib.rid)[work] == new
    return new


def test_a_choice_on_the_works_new_head_takes_its_frozen_passages_out_of_the_pool(tmp_path):
    from test_fast_path_answer import answer_run, cutoff, setup, user
    for state in ("excluded", "pending"):
        lib = setup(tmp_path / state, n=2)
        cutoff(lib)
        run = answer_run(lib)
        asyncio.run(fast_answer.answer(lib.flow, run, lib.store.scope(lib.rid)))
        old = lib.sources[0]
        assert old in followup.pool(lib.store, lib.rid, 1)["sources"]
        new = published_version_of(lib, old)
        user(lib, new, state)
        # The frozen answer named the old head; the person's choice on the work's head now still takes it out.
        frozen = followup.pool(lib.store, lib.rid, 1)
        assert old not in frozen["sources"] and new not in frozen["sources"]
        assert lib.sources[1] in frozen["sources"]


def test_an_invalid_answer_language_is_not_written_to_the_typed_column(tmp_path):
    for value in ({"tag": "en"}, ["en", "tr"]):
        def bad_language(si, value=value):
            return json.dumps(json.loads(valid_response(si)) | {"claims": [], "citation_anchors": [],
                                                                 "answer_language": value})

        app = app_for(tmp_path / type(value).__name__, FakeAdapter(bad_language))
        with TestClient(app) as client:
            session(client)
            rid, _ = research(client)
            turn = answered(client, rid)
            assert turn["status"] == "unverified_draft" and turn["run"]["status"] == "completed"
            row = app.state.store.conn.execute("SELECT answer_language, draft_json FROM followup_turns WHERE id = ?",
                                               (turn["id"],)).fetchone()
            # The column holds a language tag or nothing; the raw value stays in the stored draft.
            assert row["answer_language"] is None and json.loads(row["draft_json"])["answer_language"] == value


def test_a_follow_up_is_read_with_the_research_question_and_the_earlier_turns(tmp_path):
    """D49: a request that names no topic of its own ("a report from the full texts") is sent with the research
    question, the earlier turns and their answers, and its passages are ranked with the research question's words."""
    app = app_for(tmp_path, FakeAdapter())
    with TestClient(app) as client:
        session(client)
        rid, _ = research(client)
        first = answered(client, rid)
        assert first["status"] == "answered"
        second = answered(client, rid, "Prepare a short report from the full texts that were read")
        (payload,) = step_inputs(app, second["run"]["id"])
        assert payload["question"]["text"] == "Prepare a short report from the full texts that were read"
        context = payload["conversation"]
        assert context["research_question"] == "How is molecule release scheduling optimized?"
        assert context["latest_answer"] == []
        (earlier,) = context["earlier_turns"]
        assert earlier["question"] == QUESTION
        assert earlier["answer"] == [c["text"] for c in first["answer"]["claims"]]
        # The research question's words rank the page about the release schedule first.
        selection = app.state.store.existing_step(second["run"]["id"], followup.SELECTION_KEY)["output"]
        assert "release" in selection["terms"] and selection["lexical_matches"] > 0
        assert "release schedule" in payload["passages"][0]["text"]
        # The first turn saw no earlier turn, and its own conversation step is stored for a resume.
        (first_payload,) = step_inputs(app, first["run"]["id"])
        assert first_payload["conversation"]["earlier_turns"] == []
        stored = app.state.store.existing_step(second["run"]["id"], followup.CONVERSATION_KEY)["output"]
        assert context == stored | {"more_queries_allowed": True}


def test_the_conversation_carries_the_latest_answers_claims_as_text_only(tmp_path):
    from test_fast_path_answer import answer_run, cutoff, setup
    lib = setup(tmp_path, n=3)
    cutoff(lib)
    run = answer_run(lib)
    asyncio.run(fast_answer.answer(lib.flow, run, lib.store.scope(lib.rid)))
    texts = [r[0] for r in lib.store.conn.execute(
        "SELECT c.text FROM claims c JOIN answers a ON a.id = c.answer_id WHERE a.research_id = ?"
        " AND a.status = 'structurally_valid' ORDER BY c.ordinal", (lib.rid,))]
    assert texts
    context = followup.conversation(lib.store, lib.rid, "SYNTHETIC research question", {"id": "none", "created_at": "9999"})
    assert context == {"research_question": "SYNTHETIC research question", "latest_answer": texts, "earlier_turns": [],
                       "evidence_table": []}


def test_a_step_input_for_another_task_may_not_carry_a_conversation():
    from test_followup_contract import STEP_INPUTS
    si = STEP_INPUTS["K_followup_answer"]
    assert not contracts.check_step_input(si)
    without = {k: v for k, v in si.items() if k != "conversation"}
    assert any(i.code == "conversation_mismatch" for i in contracts.check_step_input(without))


def test_a_full_text_read_after_the_answer_joins_the_follow_up_pool(tmp_path):
    """D49: the research grew after its answer. A work whose full text was read and included since the answer's run
    started gives its pages to a follow-up; excluding it takes them out, and a file extracted again since the read
    gives no page nobody read."""
    from test_fast_path_answer import answer_run, cutoff, inspected_pdf, setup, user
    lib = setup(tmp_path, pdf=True)
    cutoff(lib)
    run = answer_run(lib)
    asyncio.run(fast_answer.answer(lib.flow, run, lib.store.scope(lib.rid)))
    pdf = lib.sources[-1]
    pages = {p["id"] for p in lib.store.passages_for(pdf) if p["kind"] == "pdf_page"}
    assert pages and not pages & set(followup.pool(lib.store, lib.rid, 1, lib.flow)["sources"].get(pdf, []))
    user(lib, pdf, "included")  # the fixture's file starts as the person's "not sure", which keeps a work out
    _, item = inspected_pdf(lib)
    decision = lib.store.conn.execute(
        "SELECT outcome, decided_by FROM stage_decisions WHERE source_version_id = ? AND stage = 'fulltext'"
        " AND superseded_at IS NULL", (pdf,)).fetchone()
    assert tuple(decision) == ("include", "model_agreement")
    frozen = followup.pool(lib.store, lib.rid, 1, lib.flow)
    assert frozen["basis"] == "answer_input" and pages <= set(frozen["sources"][pdf])
    # A person's queue answer supersedes the model's decision and carries no reading; the reading before it counts.
    from deixis.workflow.decisions import DecisionStore
    DecisionStore(lib.store).record(lib.rid, pdf, "human_include")
    assert lib.store.conn.execute(
        "SELECT decided_by FROM stage_decisions WHERE source_version_id = ? AND stage = 'fulltext'"
        " AND superseded_at IS NULL", (pdf,)).fetchone()[0] == "human"
    assert pages <= set(followup.pool(lib.store, lib.rid, 1, lib.flow)["sources"][pdf])
    # Without the flow the read cannot be checked against the file in use, and nothing later is added.
    assert not pages & set(followup.pool(lib.store, lib.rid, 1)["sources"].get(pdf, []))
    lib.store.conn.execute("UPDATE source_assets SET extraction_version = 'SYNTHETIC new extraction' WHERE id = ?",
                           (item["asset_id"],))
    assert not pages & set(followup.pool(lib.store, lib.rid, 1, lib.flow)["sources"].get(pdf, []))
    lib.store.conn.execute("UPDATE source_assets SET extraction_version = ? WHERE id = ?",
                           (lib.store.passage(next(iter(pages)))["extraction_version"], item["asset_id"]))
    assert pages <= set(followup.pool(lib.store, lib.rid, 1, lib.flow)["sources"][pdf])
    user(lib, pdf, "excluded")
    assert pdf not in followup.pool(lib.store, lib.rid, 1, lib.flow)["sources"]


def test_the_evidence_tables_values_are_context_and_their_passages_come_first(tmp_path):
    """D50: a follow-up starts from what the research established. The evidence table's current value is sent as
    context (work, column, value as the table shows it), and the passage it cites is a priority passage of the pool."""
    from test_evidence_tables import make_lib, model_output
    lib = make_lib(tmp_path)
    model_output(lib)
    context = followup.conversation(lib.store, lib.rid, "How large are packets?", {"id": "none", "created_at": "9999"})
    assert context["evidence_table"] == [{"work": "Packet size study", "column": "Packet size", "value": "128 bytes"}]
    choice = followup.table_choice(followup._table_values(lib.store, lib.rid), {lib.abstracts[lib.published]: 0})
    assert choice["columns"] == ["packet size"] and choice["passage_ids"] == [lib.abstracts[lib.published]]
    # The pool's own priority is the latest answer's passages only (D53): the table's are chosen per follow-up.
    assert followup.pool(lib.store, lib.rid, 1)["priority"] == []
    # A trashed table gives nothing.
    lib.conn.execute("UPDATE evidence_tables SET trashed_at = '2026-10-16' WHERE id = ?", (lib.tid,))
    assert followup.conversation(lib.store, lib.rid, "Q", {"id": "none", "created_at": "9999"})["evidence_table"] == []
    assert followup.table_choice(followup._table_values(lib.store, lib.rid), {})["cell_ids"] == []


def test_the_model_may_ask_the_library_once_more_and_the_second_round_answers(tmp_path):
    """D50: the first round finds the passages short and names search phrases; the library is ranked with them, a
    page the first round did not send comes in, and the second round's answer is published. No provider is asked."""
    many = [f"SYNTHETIC page {n}. Release slot number {n} is reported without a variable." for n in range(59)]
    many.append("SYNTHETIC page 59. The acoustic modem sends at a baud rate of nine thousand six hundred.")
    rounds = []

    def respond(si):
        rounds.append(si["conversation"]["more_queries_allowed"])
        draft = json.loads(valid_response(si))
        if si["conversation"]["more_queries_allowed"]:
            draft |= {"outcome": "partly_answered", "unanswered_aspects": ["the modem's baud rate"],
                      "more_queries": ["acoustic modem baud rate"]}
        else:
            page = next(p for p in si["passages"] if "baud rate" in p["text"])
            draft["claims"][0]["passage_ids"] = [page["passage_id"]]
            draft["citation_anchors"][0] |= {"passage_id": page["passage_id"], "quote": " ".join(page["text"].split())}
        return json.dumps(draft)

    app = app_for(tmp_path, FakeAdapter(respond))
    with TestClient(app) as client:
        session(client)
        rid, (svid,) = research(client, (("long.pdf", many),))
        turn = answered(client, rid)
        assert rounds == [True, False] and turn["status"] == "answered"
        first, second = step_inputs(app, turn["run"]["id"])
        assert not any("baud rate" in p["text"] for p in first["passages"])
        assert any("baud rate" in p["text"] for p in second["passages"])
        limit = app.state.store.run(turn["run"]["id"])["budget"]["max_followup_passages"]
        assert len(second["passages"]) <= limit
        (claim,) = turn["answer"]["claims"]
        assert "baud rate" in claim["citations"][0]["anchor_text"]
        assert turn["progress"]["more_step"] == "succeeded" and turn["progress"]["more_passages"] >= 1
        more = app.state.store.existing_step(turn["run"]["id"], followup.MORE_SELECTION_KEY)["output"]
        assert more["queries"] == ["acoustic modem baud rate"] and more["lexical_matches"] >= 1
        assert app.state.store.run(turn["run"]["id"])["usage"]["model_calls"] == 2


def test_an_answered_first_round_or_an_invalid_second_round_publishes_the_first(tmp_path):
    """D50: phrases with an `answered` outcome start no second round, and a second round that ends invalid leaves the
    first round's valid answer published."""
    many = [f"SYNTHETIC page {n}. Release slot number {n} is reported without a variable." for n in range(59)]
    many.append("SYNTHETIC page 59. The acoustic modem sends at a baud rate of nine thousand six hundred.")

    def respond(si):
        draft = json.loads(valid_response(si))
        if si["conversation"]["more_queries_allowed"]:
            return json.dumps(draft | {"outcome": "partly_answered", "unanswered_aspects": ["the baud rate"],
                                       "more_queries": ["acoustic modem baud rate"]})
        return json.dumps(draft | {"claims": [], "citation_anchors": []})  # invalid: an answer without claims

    app = app_for(tmp_path, FakeAdapter(respond))
    with TestClient(app) as client:
        session(client)
        rid, _ = research(client, (("long.pdf", many),))
        turn = answered(client, rid)
        assert turn["status"] == "partly_answered" and turn["answer"]["claims"]
        assert turn["progress"]["more_step"] == "failed" and turn["progress"]["more_error"] == "invalid_model_output"
        assert len(step_inputs(app, turn["run"]["id"])) == 3  # the first call, the second and its one repair

    answered_anyway = FakeAdapter(lambda si: json.dumps(json.loads(valid_response(si)) | {"more_queries": ["anything"]}))
    app = app_for(tmp_path / "b", answered_anyway)
    with TestClient(app) as client:
        session(client)
        rid, _ = research(client, (("long.pdf", many),))
        turn = answered(client, rid)
        assert turn["status"] == "answered" and len(answered_anyway.calls) == 1
        assert turn["progress"]["more_step"] is None


def test_spent_calls_before_the_second_round_publish_the_first_rounds_answer(tmp_path):
    """D50: three transport errors spend three of the turn's four calls; the first round's valid answer asks for more,
    the second round is not reached, and the first answer is published instead of the run pausing for good."""
    from deixis.models.adapter import ModelStepResult
    many = [f"SYNTHETIC page {n}. Release slot number {n} is reported without a variable." for n in range(59)]
    many.append("SYNTHETIC page 59. The acoustic modem sends at a baud rate of nine thousand six hundred.")
    adapter = FakeAdapter(lambda si: json.dumps(json.loads(valid_response(si)) | {
                              "outcome": "partly_answered", "unanswered_aspects": ["the baud rate"],
                              "more_queries": ["acoustic modem baud rate"]}),
                          fail=lambda si: ModelStepResult("failed", error="SYNTHETIC connection reset")
                          if len(adapter.calls) <= 3 else None)
    app = app_for(tmp_path, adapter)
    with TestClient(app) as client:
        session(client)
        rid, _ = research(client, (("long.pdf", many),))
        turn = ask(client, rid).json()
        _, run = wait_run(client, rid, turn["run"]["id"])
        while run["status"] == "paused":
            client.post(f"/api/runs/{run['id']}/resume")
            _, run = wait_run(client, rid, run["id"])
        turn = client.get(f"/api/researches/{rid}/followup-turns/{turn['id']}").json()
        assert run["status"] == "completed" and turn["status"] == "partly_answered" and turn["answer"]["claims"]
        assert len(adapter.calls) == 4 and turn["progress"]["more_step"] == "failed"
        assert turn["progress"]["more_error"] == "budget_exhausted"


def test_two_tables_with_the_same_column_name_keep_both_values(tmp_path):
    from test_evidence_tables import PACKET_SIZE, make_lib, model_output
    lib = make_lib(tmp_path)
    model_output(lib)
    lib.tid = lib.tables.create_table(lib.rid, "Packets again", None, None, None)
    lib.cid = lib.tables.add_column(lib.rid, lib.tid, PACKET_SIZE, 1, None)
    model_output(lib, value={"number": 64, "unit": "byte", "as_stated": "64 bytes"}, anchors=("Packets of 128 bytes",))
    values = followup.conversation(lib.store, lib.rid, "Q", {"id": "none", "created_at": "9999"})["evidence_table"]
    assert [v["value"] for v in values] == ["128 bytes", "64 bytes"]


def test_an_empty_pool_with_a_reserve_reads_the_reserve(tmp_path, monkeypatch):
    """D50: the answer's evidence left the research while other included works hold text; those are the pool."""
    from test_evidence_tables import make_lib
    lib = make_lib(tmp_path)
    monkeypatch.setattr(followup, "_included", lambda store, rid, current: {"svA": ["p1", "p2"]})
    frozen = followup._with_reserve(lib.store, lib.rid, {}, {"sources": {}, "basis": "answer_input"})
    assert frozen["sources"] == {"svA": ["p1", "p2"]} and frozen["reserve"] == {}


def table_rows(spec):
    """SYNTHETIC `_table_values` rows: (cell id, column name, passage id) per cited passage."""
    return [{"cell_id": cell, "column_name": column, "passage_id": pid} for cell, column, pid in spec]


def test_the_columns_most_related_to_the_follow_up_give_their_values_across_tables():
    """D53: a value scores by the rank its cited passages reached for this follow-up; a column, by name across the
    research's tables, by its values' mean. The best columns give all their values, best first; others give none."""
    rows = table_rows([
        ("c1", "Packet delivery result", "p_pdr1"), ("c2", "Packet delivery result", "p_pdr2"),
        ("c3", "Energy result", "p_energy"), ("c4", "Routing family", "p_family"), ("c5", "Evaluation setting", None),
        ("c6", "Packet  delivery RESULT", "p_pdr3"),  # the same column in another table
        ("c7", "Comparison protocols", "p_far"),
    ])
    rank = {"p_pdr2": 0, "p_pdr1": 1, "p_pdr3": 2, "p_energy": 5, "p_family": 40, "p_far": 400}
    choice = followup.table_choice(rows, rank)
    assert choice["columns"] == ["packet delivery result", "energy result", "routing family"]
    assert choice["cell_ids"] == ["c2", "c1", "c6", "c3", "c4"]
    assert choice["passage_ids"] == ["p_pdr2", "p_pdr1", "p_pdr3", "p_energy", "p_family"]
    # No ranking reached a table passage: the first columns in table order, as before.
    assert followup.table_choice(rows, {})["columns"] == ["packet delivery result", "energy result", "routing family"]
    many = table_rows([(f"v{n}", "Packet delivery result", f"q{n}") for n in range(200)])
    assert len(followup.table_choice(many, {f"q{n}": n for n in range(200)})["cell_ids"]) == followup.MAX_TABLE_VALUES


def test_a_follow_up_reads_the_table_values_its_question_is_about(tmp_path):
    """D53 end to end: the table has two columns; the follow-up's ranking reaches the page one column's value cites,
    so that column's value is sent as context and its page goes first. SYNTHETIC records and the fake adapter."""
    from types import SimpleNamespace
    from deixis.workflow.tables import TableStore
    from test_evidence_tables import model_output
    pages = ["SYNTHETIC. Interference between symbols is bounded by a linear constraint on the emitted amount.",
             "SYNTHETIC. The release schedule uses a binary variable per time slot to decide when molecules are emitted.",
             "SYNTHETIC. The bibliography lists unrelated works on acoustic modems and ocean sensing."]
    adapter = FakeAdapter()
    app = app_for(tmp_path, adapter)
    with TestClient(app) as client:
        session(client)
        rid, (svid,) = research(client, (("a.pdf", pages),))
        store = app.state.store
        page = {p["text"][:40]: p["id"] for p in store.passages_for(svid)}
        variable = next(pid for text, pid in page.items() if "release schedule" in text)
        interference = next(pid for text, pid in page.items() if "Interference" in text)
        run = store.create_run(rid, "answer", {"max_model_calls": 4}, None)
        store.update_run(run["id"], status="completed")
        lib = SimpleNamespace(store=store, conn=store.conn, tables=TableStore(store), rid=rid, published=svid,
                              run_id=run["id"], step_id=store.step(run["id"], "cell", "model:cell_extraction")["id"])
        lib.tid = lib.tables.create_table(rid, "Study table", None, None, None)
        columns = {}
        for name in ("Interference bound", "Decision variable"):  # table order puts the other column first
            lib.cid = columns[name] = lib.tables.add_column(rid, lib.tid, {
                "name": name, "instruction": f"SYNTHETIC {name}.", "answer_format": "text", "options": None,
                "allow_multiple": False, "unit_hint": None},
                store.conn.execute("SELECT version FROM evidence_tables WHERE id = ?", (lib.tid,)).fetchone()[0], None)
            pid, quote = (variable, "binary variable per time slot") if name == "Decision variable" else (
                interference, "bounded by a linear constraint")
            model_output(lib, passage=pid, value={"text": f"SYNTHETIC value for {name}"}, anchors=(quote,))
        turn = answered(client, rid)  # "Which binary variable decides the release time slot?"
        (payload,) = step_inputs(app, turn["run"]["id"])
        table = payload["conversation"]["evidence_table"]
        assert table[0]["column"] == "Decision variable" and payload["passages"][0]["passage_id"] == variable
        selection = store.existing_step(turn["run"]["id"], followup.SELECTION_KEY)["output"]
        assert selection["table_columns"][0] == "decision variable"
        # The values are frozen with the selection: the conversation a resumed turn sends is read from it.
        assert selection["table_values"] == table


def test_table_values_dedupe_by_source_and_column_and_freeze_with_the_selection():
    """D53: two works that share a title and year keep their own values; the same work's same value under the same
    column (spaced differently) in another table is sent once."""
    def row(cell, svid, column, text):
        return {"cell_id": cell, "source_version_id": svid, "title": "SYNTHETIC same title", "year": 2020,
                "column_name": column, "options_json": None, "value_json": json.dumps({"text": text}), "passage_id": None}
    rows = [row("a", "sv1", "Packet delivery result", "88%"), row("b", "sv2", "Packet delivery result", "88%"),
            row("c", "sv1", "Packet  delivery result", "88%"), row("d", "sv1", "Packet delivery result", "x" * 900)]
    values = followup.table_values(rows, ["a", "b", "c", "d"])
    assert [v["value"] for v in values] == ["88%", "88%", "x" * followup.MAX_VALUE_CHARS]


def first_answer(client, rid):
    run = client.post(f"/api/researches/{rid}/runs", json={"kind": "answer"}).json()
    wait_run(client, rid, run["id"], ("completed",))
    return [a for a in client.get(f"/api/researches/{rid}").json()["answers"] if a["status"] == "structurally_valid"]


def test_a_follow_up_asking_for_a_report_change_opens_the_next_report_version(tmp_path):
    # D57: the model says the turn asks for the report to change; the turn is answered as usual and a new answer run,
    # started for the person with their words as steering, writes the next report version.
    app = app_for(tmp_path, FakeAdapter())
    with TestClient(app) as client:
        session(client)
        rid, _ = research(client)
        (v1,) = first_answer(client, rid)
        assert (v1["report_version"], v1["report_revision"]) == (1, 0)
        request = "[report-change] Add the interference bound to the report."
        turn = answered(client, rid, request)
        assert turn["status"] == "answered" and turn["report_change"]["run_id"] and turn["report_change"]["not_started"] is None
        run_id = turn["report_change"]["run_id"]
        run = app.state.store.run(run_id)
        assert run["kind"] == "answer" and run["budget"].get("trigger") is None
        assert run["target"]["report_request"] == {"turn_id": turn["id"], "text": request}
        wait_run(client, rid, run_id, ("completed",))
        answers = [a for a in client.get(f"/api/researches/{rid}").json()["answers"] if a["status"] == "structurally_valid"]
        assert [(a["report_version"], a["report_revision"]) for a in answers] == [(2, 0), (1, 0)]
        done = client.get(f"/api/researches/{rid}/followup-turns/{turn['id']}").json()["report_change"]
        assert (done["run_status"], done["answer_status"], done["report_version"]) == ("completed", "structurally_valid", 2)
        sent = [p for p in step_inputs(app, run_id) if p["task_type"] == "grounded_answer"]
        assert sent and all(request in p["user_steering"] for p in sent)


def test_a_plain_follow_up_question_leaves_the_report_alone(tmp_path):
    app = app_for(tmp_path, FakeAdapter())
    with TestClient(app) as client:
        session(client)
        rid, _ = research(client)
        first_answer(client, rid)
        turn = answered(client, rid)
        assert turn["status"] == "answered" and turn["report_change"] is None
        assert not app.state.store.conn.execute(
            "SELECT 1 FROM runs WHERE research_id = ? AND idempotency_key = ?", (rid, followup.report_run_key(turn["id"]))).fetchone()
        assert len([a for a in client.get(f"/api/researches/{rid}").json()["answers"] if a["status"] == "structurally_valid"]) == 1


def test_a_report_change_that_cannot_start_says_why(tmp_path, monkeypatch):
    # Another run holding the research when the turn ends: no answer run is queued and the turn says why (D57).
    app = app_for(tmp_path, FakeAdapter())
    with TestClient(app) as client:
        session(client)
        rid, _ = research(client)
        first_answer(client, rid)
        store = app.state.store
        create_run = store.create_run

        def busy(research_id, kind, *args, **kwargs):
            if kind == "answer":
                raise RevisionConflict("run run_OTHER is still active")
            return create_run(research_id, kind, *args, **kwargs)
        monkeypatch.setattr(store, "create_run", busy)
        turn = answered(client, rid, "[report-change] Shorten the report.")
        assert turn["status"] == "answered"
        assert turn["report_change"] == {"run_id": None, "run_status": None, "answer_status": None, "report_version": None,
                                         "not_started": "run_active"}
        assert len([a for a in client.get(f"/api/researches/{rid}").json()["answers"] if a["status"] == "structurally_valid"]) == 1


def test_a_report_change_whose_answer_is_not_valid_opens_no_version(tmp_path):
    # The queued answer ends as an unverified draft: the run completes, no report version is written, and the turn
    # says so from the answer the run saved, not from the run's status (D57).
    def responder(si):
        if si["task_type"] == "grounded_answer" and si["user_steering"]:
            return "{not json"
        return valid_response(si)
    app = app_for(tmp_path, FakeAdapter(responder))
    with TestClient(app) as client:
        session(client)
        rid, _ = research(client)
        first_answer(client, rid)
        turn = answered(client, rid, "[report-change] Rewrite the report around the interference bound.")
        wait_run(client, rid, turn["report_change"]["run_id"], ("completed", "failed"))
        done = client.get(f"/api/researches/{rid}/followup-turns/{turn['id']}").json()["report_change"]
        assert done["answer_status"] in (None, "unverified_draft") and done["report_version"] is None
        assert [a["report_version"] for a in client.get(f"/api/researches/{rid}").json()["answers"]
                if a["status"] == "structurally_valid"] == [1]


def test_question_keeps_quote_lines():
    # "Add to chat" quotes come as Markdown quote blocks ahead of the question; their line breaks must survive the cleanup.
    assert followup._clean("  > quoted  line\n> second\n\n\n\nWhy   is that?  ") == "> quoted line\n> second\n\nWhy is that?"
    assert followup._clean("plain   question") == "plain question"
