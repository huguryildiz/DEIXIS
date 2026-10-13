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
        assert turn["progress"] == {"passages_selected": len(sent), "answer_step": "succeeded"}
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
        assert len(adapter.calls) == followup.CALLS  # the call and its one repair, then it stops
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
        assert turn["progress"] == {"passages_selected": None, "answer_step": None}


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
            "code:followup_pool", "code:followup_passages", "model:followup_answer"}


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
        assert paused["progress"] == {"passages_selected": len(sent), "answer_step": "succeeded"}
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
        # The call and its one repair: the turn's own two calls, whatever the research's other runs used.
        assert run["budget"]["max_model_calls"] == followup.CALLS == run["usage"]["model_calls"]
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
        assert ("RETRIEVAL_QUERY", "Semboller arası girişim nasıl sınırlanıyor?") in embedded


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
                          if len(adapter.calls) == 1 else None)
    app = app_for(tmp_path, adapter)
    with TestClient(app) as client:
        session(client)
        rid, _ = research(client)
        turn = ask(client, rid).json()
        _, run = wait_run(client, rid, turn["run"]["id"])
        assert run["status"] == "paused" and app.state.store.run(run["id"])["usage"]["model_calls"] == 1
        client.post(f"/api/runs/{run['id']}/resume")
        _, run = wait_run(client, rid, run["id"])
        turn = client.get(f"/api/researches/{rid}/followup-turns/{turn['id']}").json()
        # The second call came back invalid and no call is left for its repair: the turn closes as that draft
        # instead of pausing again with budget_exhausted.
        assert (run["status"], run["pause_reason"]) == ("completed", None), run
        assert turn["status"] == "unverified_draft" and turn["answer"] is None and turn["issues"]
        assert len(adapter.calls) == 2 and app.state.store.run(run["id"])["usage"]["model_calls"] == 2


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
