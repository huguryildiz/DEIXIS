"""The short phrase searches beside the plan (`phrase_search_v1`), driven through the API with OpenAlex mocked.

One model step writes six short phrases from the question; each goes to OpenAlex semantic search after the question's
own request, and its records join the pool as a query list of its own. Records, questions and phrases are SYNTHETIC:
passing shows workflow behavior, not that the phrases find better papers.
"""

import asyncio
import json
import time
from types import SimpleNamespace

import httpx
from fastapi.testclient import TestClient

from deixis.models.adapter import ModelStepResult
from deixis.providers import common, openalex as openalex_provider, pacing
from deixis.providers.common import ProviderRecord, SearchOutcome
from deixis.runtime.config import Settings
from deixis.workflow.run.flow import ResearchFlow
from deixis.workflow.run import fast_path
from deixis.workflow.search import phrase_search, preselect, small_batch
from deixis.workflow.search import search as fast_search
from fakes import FakeAdapter, valid_response
from test_fast_path_clock import library  # noqa: F401  (the fixture)
from test_vocabulary_flow import QUESTION, app_for, start, store_at, wait

PHRASE = "synthetic short phrase number"  # the start of every phrase the fake model writes


def work(n, title):
    """One SYNTHETIC OpenAlex work with its own id and title."""
    return {"id": f"https://openalex.org/W{n}", "doi": f"https://doi.org/10.1/{n}", "display_name": title,
            "publication_year": 2024, "type": "article", "authorships": [],
            "abstract_inverted_index": {"We": [0], "study": [1], "this.": [2]}}


class OpenAlex:
    """Mocked OpenAlex: the question's request and each phrase request answer a work of their own; `hang` keeps every
    phrase request waiting until the test ends, `log` keeps what arrived and when."""

    def __init__(self, hang=False, question_delay=0.0):
        self.hang, self.question_delay = hang, question_delay
        self.log = []  # (kind, text, monotonic time) per request that reached the mock
        self.question_answered = None  # when the question's own request was answered

    async def __call__(self, request):
        if request.url.host != "api.openalex.org":
            return httpx.Response(404)
        params = request.url.params
        semantic = params.get("search.semantic")
        if params.get("per_page") == "1" and params.get("select") == "id":
            return httpx.Response(200, json={"meta": {"count": 40}, "results": []})
        if semantic is None:
            self.log.append(("keyword", params.get("search.title_abstract_keywords"), time.monotonic()))
            return httpx.Response(200, json={"meta": {"count": 1}, "results": [work(1, "SYNTHETIC keyword record")]})
        if semantic == QUESTION:
            self.log.append(("question", semantic, time.monotonic()))
            await asyncio.sleep(self.question_delay)
            self.question_answered = time.monotonic()
            return httpx.Response(200, json={"meta": {"count": 1}, "results": [work(2, "SYNTHETIC question record")]})
        self.log.append(("phrase", semantic, time.monotonic()))
        if self.hang:
            await asyncio.sleep(3600)
        n = 100 + int(semantic.rsplit(" ", 1)[-1])
        return httpx.Response(200, json={"meta": {"count": 1}, "results": [work(n, f"SYNTHETIC {semantic} record")]})

    def sent(self, kind):
        return [text for k, text, _ in self.log if k == kind]


def run_once(tmp_path, monkeypatch, openalex, adapter):
    """Start one Quick discovery run and wait for it to settle; the run's view, its record and the store."""
    with TestClient(app_for(tmp_path, monkeypatch, openalex, adapter)) as client:
        client.headers["x-deixis-csrf"] = client.get("/api/session").json()["csrf_token"]
        rid, run_id = start(client, QUESTION)
        view, run = wait(client, rid, run_id)
    return rid, run_id, view, run, store_at(tmp_path)


def phrase_steps(store, run_id):
    """Each phrase request's step, by key, in the order it opened."""
    return [dict(row) for row in store.conn.execute(
        "SELECT operation_key, status, error_code, protocol_hash FROM run_steps WHERE run_id = ? AND operation_key"
        " LIKE ? ORDER BY rowid", (run_id, fast_search.PHRASE_KEY + "%"))]


def frozen_route(store, run_id):
    """What the run's protocol froze of the route (None where it froze nothing of it)."""
    return fast_search.frozen_body(store, store.run(run_id))["fast_path_search"].get("phrase_search")


def test_the_phrase_step_writes_six_phrases_whose_requests_join_the_pool_as_lists_of_their_own(tmp_path, monkeypatch):
    openalex, adapter = OpenAlex(), FakeAdapter()
    rid, run_id, view, run, store = run_once(tmp_path, monkeypatch, openalex, adapter)
    assert run["status"] == "completed", run
    # One phrase call, given the question and the count, and no record.
    calls = [si for si in adapter.calls if si["task_type"] == "search_phrases"]
    assert len(calls) == 1 and calls[0]["phrase_target"] == {"count": 6, "english_question": None}
    step = store.step(run_id, phrase_search.STEP_KEY, "model:search_phrases")
    assert step["status"] == "succeeded" and len(step["output"]["result"]["phrases"]) == 6
    # The frozen body holds the phrases and the six requests they became, 50 records each.
    frozen = frozen_route(store, run_id)
    assert (frozen["rule"], frozen["status"], frozen["count"]) == (fast_path.PHRASE_SEARCH_RULE, "ready", 6)
    assert [r["query_text"] for r in frozen["requests"]] == [f"{PHRASE} {n}" for n in range(1, 7)]
    assert {r["limit"] for r in frozen["requests"]} == {50}
    assert sorted(openalex.sent("phrase")) == sorted(r["query_text"] for r in frozen["requests"])
    assert [(s["operation_key"], s["status"]) for s in phrase_steps(store, run_id)] == [
        (fast_search.phrase_key(n), "succeeded") for n in range(6)]
    # Their records are in the pool, and each phrase request is a list of its own beside the question's.
    listing = store.step(run_id, small_batch.LIST_KEY, "code:small_batch_list")["output"]
    manifest = listing.get("manifest") or listing
    assert manifest["preselect"]["list_identity"] == preselect.ENDPOINT_IDENTITY
    semantic = sorted(e["query_text"] for e in manifest["query_lists"] if e.get("endpoint") == "semantic")
    assert semantic == sorted([QUESTION] + [f"{PHRASE} {n}" for n in range(1, 7)])
    pool = {row["id"] for row in manifest["pool"]}
    phrase_lists = [e for e in manifest["query_lists"] if e["query_text"].startswith(PHRASE)]
    assert len(phrase_lists) == 6 and all(set(e["members"]) <= pool and e["votes"] for e in phrase_lists)


class PacerClock:
    """A fake clock for the provider pacer alone: a wait moves the clock on at once instead of sleeping."""

    def __init__(self):
        self.now = 1000.0

    def monotonic(self):
        return self.now

    async def sleep(self, seconds):
        self.now += max(0.0, seconds)
        await REAL_SLEEP(0)


REAL_SLEEP = asyncio.sleep


def test_phrases_follow_the_questions_send_not_its_reply_one_at_a_time_through_the_real_pacer(tmp_path, monkeypatch):
    # The real 1.5 s pacer on a fake clock: the conftest fixture zeroes the interval, so it is set back here.
    clock, pacer = PacerClock(), openalex_provider.SEMANTIC_PACER
    monkeypatch.setattr(pacer, "interval_seconds", 1.5)
    monkeypatch.setattr(pacer, "_next", 0.0)
    monkeypatch.setattr(pacing, "time", SimpleNamespace(monotonic=clock.monotonic))
    monkeypatch.setattr(pacing, "asyncio", SimpleNamespace(sleep=clock.sleep))
    starts, waiting, peak = [], [0], [0]  # (who, fake time) per start; phrases waiting at the pacer now and at most
    start = pacer.start

    async def counted():
        task = asyncio.current_task()
        phrase = task is not None and task.get_coro().__qualname__ == "Route._request"
        waiting[0] += phrase
        peak[0] = max(peak[0], waiting[0])
        try:
            await start()
        finally:
            waiting[0] -= phrase
        starts.append(("phrase" if phrase else "other", clock.now))

    monkeypatch.setattr(pacer, "start", counted)
    # The question's reply takes a real second: the phrases must not wait for it.
    service = OpenAlex(question_delay=1.0)
    rid, run_id, view, run, store = run_once(tmp_path, monkeypatch, service, FakeAdapter())
    assert run["status"] == "completed", run
    phrases = [at for kind, _, at in service.log if kind == "phrase"]
    question = next(at for kind, _, at in service.log if kind == "question")
    assert len(phrases) == 6 and question <= min(phrases) and max(phrases) < service.question_answered
    # One phrase at the pacer at a time, and every start at least one interval after the one before it.
    assert peak[0] == 1 and [who for who, _ in starts].count("phrase") == 6
    times = [at for _, at in starts]
    assert all(later - earlier >= 1.5 for earlier, later in zip(times, times[1:]))


def test_the_keyword_search_never_waits_for_a_phrase_and_the_cutoff_cancels_and_records_them(tmp_path, monkeypatch):
    # Every phrase request hangs: the run still ends, and each one is closed at the end of the search stage.
    openalex = OpenAlex(hang=True)
    rid, run_id, view, run, store = run_once(tmp_path, monkeypatch, openalex, FakeAdapter())
    assert run["status"] == "completed", run
    assert openalex.sent("keyword")
    steps = phrase_steps(store, run_id)
    assert steps and {(s["status"], s["error_code"]) for s in steps} == {("cancelled", phrase_search.CUTOFF)}
    # Nothing is sent once the stage is closed.
    sent = len(openalex.sent("phrase"))
    time.sleep(0.3)
    assert len(openalex.sent("phrase")) == sent


def test_a_failed_or_refused_phrase_step_does_not_pause_the_run(tmp_path, monkeypatch):
    def wrong_count(si):
        # Five phrases where six were asked: refused, repaired once, refused again.
        text = valid_response(si)
        if si["task_type"] == "search_phrases":
            body = json.loads(text)
            body["phrases"] = body["phrases"][:5]
            return json.dumps(body)
        return text

    fail = lambda si: (ModelStepResult("failed", error="SYNTHETIC phrase call failed")  # noqa: E731
                       if si["task_type"] == "search_phrases" else None)
    for case, adapter in (("failed", FakeAdapter(fail=fail)), ("invalid", FakeAdapter(responder=wrong_count))):
        openalex = OpenAlex()
        rid, run_id, view, run, store = run_once(tmp_path / case, monkeypatch, openalex, adapter)
        assert run["status"] == "completed", (case, run)
        frozen = frozen_route(store, run_id)
        assert frozen["status"] == "not_written" and frozen["reason"], (case, frozen)
        assert not openalex.sent("phrase") and not phrase_steps(store, run_id)
        step = store.existing_step(run_id, phrase_search.STEP_KEY)
        assert step["status"] != "succeeded"


def test_a_resume_neither_asks_for_the_phrases_again_nor_resends_an_answered_request(tmp_path, monkeypatch):
    from fakes import without_evidence_minimum
    # A failed abstract read pauses only a run frozen before the evidence minimum, which is the pause this test uses.
    without_evidence_minimum(monkeypatch)
    down = True

    def failure(si):
        # The run pauses after its search stage, at the abstract stage, while the connection is down.
        if down and si["task_type"] == "abstract_screening":
            return ModelStepResult("failed", error="SYNTHETIC paused connection")

    openalex, adapter = OpenAlex(), FakeAdapter(fail=failure)
    # The records carry no word of the plan's blocks, so the abstract stage asks the model and the run pauses.
    with TestClient(app_for(tmp_path, monkeypatch, openalex, adapter)) as client:
        client.headers["x-deixis-csrf"] = client.get("/api/session").json()["csrf_token"]
        rid, run_id = start(client, QUESTION)
        view, run = wait(client, rid, run_id)
        assert run["status"] == "paused", run
        sent, calls = list(openalex.log), [si for si in adapter.calls if si["task_type"] == "search_phrases"]
        down = False
        assert client.post(f"/api/runs/{run_id}/resume").status_code == 200
        view, run = wait(client, rid, run_id)
    assert run["status"] == "completed", run
    assert [si for si in adapter.calls if si["task_type"] == "search_phrases"] == calls
    assert [entry for entry in openalex.log if entry[0] == "phrase"] == [entry for entry in sent if entry[0] == "phrase"]


def test_a_route_built_again_on_a_finished_run_asks_and_sends_nothing(tmp_path, monkeypatch):
    # The resume guard without a pause: a second route over the stored run reads the frozen phrases and skips every
    # answered request.
    openalex, adapter = OpenAlex(), FakeAdapter()
    app = app_for(tmp_path, monkeypatch, openalex, adapter)
    with TestClient(app) as client:
        client.headers["x-deixis-csrf"] = client.get("/api/session").json()["csrf_token"]
        rid, run_id = start(client, QUESTION)
        view, run = wait(client, rid, run_id)
        assert run["status"] == "completed", run
        store, flow = app.state.store, app.state.worker.flow
        before = (len(adapter.calls), list(openalex.log))

        async def again():
            done = asyncio.get_running_loop().create_future()
            done.set_result(None)
            route = phrase_search.Route(flow, store.run(run_id), store.scope(rid, 1), done)
            route.start()
            await asyncio.gather(route.model_task, route.sender)
            return route

        route = asyncio.run(again())
    assert route.tasks == {} and (len(adapter.calls), openalex.log) == before


def test_a_duplicate_phrase_request_counts_once_and_a_keyword_query_of_its_text_is_its_own_list():
    hit = lambda head, query, rank, endpoint: {"head": head, "provider": "openalex", "query_text": query,  # noqa: E731
                                               "rank": rank, "sort": None, "relevance": True, "read_total": None,
                                               "endpoint": endpoint}
    hits = [hit("a", "short phrase", 0, "semantic"), hit("a", "short phrase", 0, "semantic"),
            hit("b", "short phrase", 1, "semantic"), hit("a", "short phrase", 3, "keyword")]
    lists = preselect.lists(hits, preselect.ENDPOINT_IDENTITY)
    assert [(e["endpoint"], e["size"]) for e in lists] == [("keyword", 1), ("semantic", 2)]
    # "a" has one vote from the repeated semantic request and one from the keyword list, no more.
    assert [part["rank"] for part in preselect.scores(lists)["a"]] == [4, 1]


def test_an_old_manifest_keeps_its_lists_and_replays_unchanged():
    # Without the identity, the key and every list are what they were before the rule: the endpoint is ignored.
    hits = [{"head": "a", "provider": "openalex", "query_text": "Q", "rank": 0, "sort": None, "relevance": True,
             "read_total": None, "endpoint": "semantic"},
            {"head": "b", "provider": "openalex", "query_text": "Q", "rank": 1, "sort": None, "relevance": True,
             "read_total": None, "endpoint": "keyword"}]
    old = preselect.lists(hits)
    assert old == [{"provider": "openalex", "query_text": "Q", "sort": None, "votes": True, "read_total": None,
                    "members": ["a", "b"], "places": {"a": 0, "b": 1}, "size": 2}]
    assert old == preselect.lists([{k: v for k, v in h.items() if k != "endpoint"} for h in hits])
    # The window reads the frozen lists as they were frozen; a manifest naming no identity gives the same window.
    manifest = {"preselect": {"rule": preselect.RULE, "k": preselect.K, "floors": {}}, "query_lists": old,
                "pool": [{"id": "a", "work_id": "w-a"}, {"id": "b", "work_id": "w-b"}, {"id": "c", "work_id": "w-c"}]}
    window = small_batch.window_for(manifest, ["c", "b", "a"], 2)
    assert window["window"] == small_batch.window_for(json.loads(json.dumps(manifest)), ["c", "b", "a"], 2)["window"]
    assert set(window["window"]) == {"a", "b"}


def test_a_run_frozen_before_the_rule_sends_no_phrase_request(tmp_path, monkeypatch):
    # A budget frozen before the rule names no `phrase_search`: no phrase call, no phrase request, the old list key.
    freeze = fast_path.freeze_budget

    def before_the_rule(*args, **kwargs):
        policy = freeze(*args, **kwargs)
        policy.pop("phrase_search", None)
        return policy

    monkeypatch.setattr(fast_path, "freeze_budget", before_the_rule)
    openalex, adapter = OpenAlex(), FakeAdapter()
    rid, run_id, view, run, store = run_once(tmp_path, monkeypatch, openalex, adapter)
    assert run["status"] == "completed", run
    assert fast_path.phrase_search(store.run(run_id)["budget"]) is None
    assert not [si for si in adapter.calls if si["task_type"] == "search_phrases"]
    assert not openalex.sent("phrase") and not phrase_steps(store, run_id)
    assert frozen_route(store, run_id) is None
    listing = store.step(run_id, small_batch.LIST_KEY, "code:small_batch_list")["output"]
    manifest = listing.get("manifest") or listing
    assert "list_identity" not in (manifest.get("preselect") or {})


def test_a_connection_that_answers_one_call_at_a_time_is_not_asked_for_phrases(tmp_path, monkeypatch):
    # The fake connection stands for a model this computer runs: its one call at a time would hold up the plan.
    monkeypatch.setattr(phrase_search, "SERIAL_CONNECTIONS", frozenset({"fake"}))
    openalex, adapter = OpenAlex(), FakeAdapter()
    rid, run_id, view, run, store = run_once(tmp_path, monkeypatch, openalex, adapter)
    assert run["status"] == "completed", run
    assert not [si for si in adapter.calls if si["task_type"] == "search_phrases"]
    step = store.existing_step(run_id, phrase_search.STEP_KEY)
    assert (step["status"], step["error_code"]) == ("cancelled", phrase_search.SERIAL)
    assert frozen_route(store, run_id) | {"rule": None} == {"rule": None, "count": 6, "records": 50,
                                                             "status": "not_written", "reason": phrase_search.SERIAL}
    assert not openalex.sent("phrase") and not phrase_steps(store, run_id)


def test_the_phrase_step_is_given_no_steering(tmp_path, monkeypatch):
    openalex, adapter = OpenAlex(), FakeAdapter()
    app = app_for(tmp_path, monkeypatch, openalex, adapter)
    with TestClient(app) as client:
        client.headers["x-deixis-csrf"] = client.get("/api/session").json()["csrf_token"]
        response = client.post("/api/researches", json={"question": QUESTION, "model_connection": "fake",
                                                        "requested_model": "fake-model", "effort": "quick"})
        rid = response.json()["research"]["id"]
        # A steering note on the question's revision, as a scope revision writes it.
        app.state.store.conn.execute("UPDATE scope_revisions SET steering = ? WHERE research_id = ?",
                                     ("SYNTHETIC steering note", rid))
        run_id = client.post(f"/api/researches/{rid}/runs", json={"kind": "discovery"}).json()["id"]
        view, run = wait(client, rid, run_id)
    assert run["status"] == "completed", run
    phrases = next(si for si in adapter.calls if si["task_type"] == "search_phrases")
    assert phrases["user_steering"] == [] and "SYNTHETIC steering note" not in json.dumps(phrases)
    # The note was set: another step of the run is given it.
    assert any("SYNTHETIC steering note" in si["user_steering"] for si in adapter.calls)
    # The stored input is the one sent.
    store = store_at(tmp_path)
    stored = store.conn.execute("SELECT si.payload_json FROM step_inputs si JOIN run_steps s ON s.id = si.step_id"
                                " WHERE s.run_id = ? AND s.operation_key = ?", (run_id, phrase_search.STEP_KEY)).fetchall()
    assert stored and all("SYNTHETIC steering note" not in row[0] for row in stored)


# ---- one route over a run of the clock library: the deadline, a crash and a pause -----------------------------------

PHRASES = [{"text": "synthetic short phrase number 1", "kind": "subject"}]


class HeldSearch:
    """A scripted provider send: it is handed to the client at once and answers only when `reply` is set."""

    def __init__(self):
        self.calls, self.handed, self.reply = [], asyncio.Event(), asyncio.Event()

    async def __call__(self, run_id, connector, query, limit, page=None, **kwargs):
        self.calls.append(query["query_text"])
        if (handed := common.on_handed.get()) is not None:
            handed()  # what the real transport does once the request has passed the pacer
        self.handed.set()
        await self.reply.wait()
        record = ProviderRecord(provider_record_id="W900", title="SYNTHETIC late record", authors=[], year=2026,
                                venue=None, publication_type="article", doi=None, landing_url=None, oa_pdf_url=None,
                                oa_pdf_version=None, version_label="publishedVersion", abstract="SYNTHETIC abstract",
                                abstract_origin="provider_openalex_inverted_index", identifiers={"openalex": "W900"},
                                raw={"id": "W900"})
        return SearchOutcome("completed", "rejected_not_executed", "SYNTHETIC request", "keyless", records=[record],
                             provider_total=1)


def unit_flow(lib, tmp_path, send):
    """A flow over the clock library whose question request has answered and whose search stage is open."""
    flow = ResearchFlow(SimpleNamespace(store=lib.store, clock=lib.clock, settings=Settings(data_dir=tmp_path / "data"),
                                        local_embedder=None))
    flow._send_search = send
    question = lib.store.step(lib.run["id"], "search:fast:semantic", "provider_search:openalex")
    lib.store.start_step(question["id"])
    lib.store.finish_step(question["id"], "succeeded", output={"result_count": 0})
    fast_path.enter_stage(lib.store, lib.run, "search")
    return flow


def unit_route(lib, flow):
    """A route whose phrase step has already answered, its sender started."""
    loop = asyncio.get_running_loop()
    done, phrases = loop.create_future(), loop.create_future()
    done.set_result(None)
    phrases.set_result(PHRASES)
    route = phrase_search.Route(flow, lib.run, lib.store.scope(lib.rid), done)
    route.model_task = phrases
    route.sender = asyncio.create_task(route._send())
    return route


def phrase_page(lib):
    """The phrase request's step, and how many hits it wrote."""
    step = lib.store.existing_step(lib.run["id"], fast_search.phrase_key(0))
    hits = lib.conn.execute("SELECT COUNT(*) FROM candidate_hits h JOIN search_runs sr ON sr.id = h.search_run_id"
                            " WHERE sr.step_id = ?", (step["id"],)).fetchone()[0]
    return step, hits


def past_the_cutoff(lib, seconds=1):
    """Move the run's clock `seconds` past the search stage's deadline."""
    deadline = fast_path.stage_deadline(lib.store, lib.run, "search")
    lib.clock.advance((deadline - lib.clock.now()).total_seconds() + seconds)


def test_a_phrase_reply_after_the_search_deadline_is_not_written_whenever_the_keyword_path_ends(library, tmp_path):
    lib, send = library, HeldSearch()
    flow = unit_flow(lib, tmp_path, send)

    async def late_reply():
        # Cutoff at 7, phrase reply at 8, keyword path ending at 10: the reply is cancelled, its record kept out.
        route = unit_route(lib, flow)
        await send.handed.wait()
        assert phrase_page(lib)[0]["status"] == "running"
        past_the_cutoff(lib, 1)
        send.reply.set()
        await asyncio.gather(route.sender, *route.tasks.values(), return_exceptions=True)
        lib.clock.advance(2)
        await route.close()

    asyncio.run(late_reply())
    step, hits = phrase_page(lib)
    assert (step["status"], step["error_code"], hits) == ("cancelled", phrase_search.CUTOFF, 0)


def test_the_deadline_watch_closes_a_phrase_request_still_out_before_the_keyword_path_ends(library, tmp_path):
    lib, send = library, HeldSearch()
    flow = unit_flow(lib, tmp_path, send)

    async def watched():
        route = unit_route(lib, flow)
        route.watch()
        await send.handed.wait()
        past_the_cutoff(lib, 1)
        # The watch closes it by itself; the keyword path has not ended and `close` is not called here.
        await asyncio.wait_for(route.watcher, 5)
        status = phrase_page(lib)[0]["status"]
        send.reply.set()  # an answer now finds nothing waiting for it
        await asyncio.sleep(0.05)
        return status

    assert asyncio.run(watched()) == "cancelled"
    step, hits = phrase_page(lib)
    assert (step["status"], step["error_code"], hits) == ("cancelled", phrase_search.CUTOFF, 0)
    assert len(send.calls) == 1


def test_a_phrase_request_a_crash_cut_after_it_started_is_never_sent_again(library, tmp_path):
    lib, send = library, HeldSearch()
    flow = unit_flow(lib, tmp_path, send)

    async def crash():
        route = unit_route(lib, flow)
        await send.handed.wait()
        # A crash: the tasks die without any closing, and the next start marks every running step unknown.
        for task in (route.sender, *route.tasks.values()):
            task.cancel()
        await asyncio.gather(route.sender, *route.tasks.values(), return_exceptions=True)
        lib.conn.execute("UPDATE run_steps SET status = 'outcome_unknown' WHERE status = 'running'")
        resumed = unit_route(lib, flow)
        await resumed.sender
        return resumed.tasks

    assert asyncio.run(crash()) == {} and len(send.calls) == 1
    assert phrase_page(lib)[0]["status"] == "outcome_unknown"


def test_a_phrase_request_a_pause_cut_after_it_started_is_closed_and_not_sent_again(library, tmp_path):
    lib, send = library, HeldSearch()
    flow = unit_flow(lib, tmp_path, send)

    async def pause():
        route = unit_route(lib, flow)
        await send.handed.wait()
        await route.stop()  # the run stopped while the request was out
        resumed = unit_route(lib, flow)
        await resumed.sender
        return resumed.tasks

    assert asyncio.run(pause()) == {} and len(send.calls) == 1
    step, hits = phrase_page(lib)
    assert (step["status"], step["error_code"], hits) == ("cancelled", phrase_search.INTERRUPTED, 0)


def question_failed(lib, delivery_class):
    """The question's own request stored as failed, with the delivery class its record holds."""
    question = lib.store.existing_step(lib.run["id"], "search:fast:semantic")
    lib.conn.execute("UPDATE run_steps SET status = 'failed', error_code = 'rate_limited', delivery_class = ?"
                     " WHERE id = ?", (delivery_class, question["id"]))


def test_a_question_request_that_failed_before_its_send_opens_no_phrase_request(library, tmp_path):
    # A quota block or a stop at the pacer: the request never reached the transport and `handed` never fired.
    lib, send = library, HeldSearch()
    flow = unit_flow(lib, tmp_path, send)
    question_failed(lib, "before_send")

    async def scenario():
        route = unit_route(lib, flow)
        await route.sender
        await route.close()
        return route

    route = asyncio.run(scenario())
    assert send.calls == [] and route.tasks == {} and route.reason == phrase_search.NOT_SENT
    step = lib.store.existing_step(lib.run["id"], fast_search.phrase_key(0))
    assert (step["status"], step["error_code"]) == ("cancelled", phrase_search.NOT_SENT)


def test_a_question_request_that_failed_after_it_was_handed_does_not_block_the_phrases(library, tmp_path):
    lib, send = library, HeldSearch()
    flow = unit_flow(lib, tmp_path, send)
    question_failed(lib, "before_send")  # what its record says matters less than the send this run saw

    async def scenario():
        route = unit_route(lib, flow)
        route.handed.set()  # the request reached the transport before it failed
        await send.handed.wait()
        send.reply.set()
        await route.sender
        return route

    route = asyncio.run(scenario())
    assert len(send.calls) == 1 and route.reason is None
    assert lib.store.existing_step(lib.run["id"], fast_search.phrase_key(0))["status"] == "succeeded"
