"""D6: the seeds enrich the search, the question filters it. Each seed asks OpenAlex on its own, the question's request
is the unseeded one, the first chain seeds come only from what the question's request accepted, and the seed PDFs
neither push the code's graph seeds out nor add up their nearness. SYNTHETIC."""

import asyncio
import json

import httpx

from deixis.providers.common import ProviderRecord
from deixis.workflow import fast_search, ranking, search_query, seed_match, small_batch
from test_fetch_overlap_flow import output, wait
from test_fulltext_flow import work
from test_seed_pdf import (QUESTION, SEED_PDF, SEED_TITLE, TITLE_B, SeedTransport, d3_frozen, discovery, pdf_of,
                           protocol_body, records, research, seed_work, seeded, select, upload)
from test_small_batch_flow import app_for, client_of

SHARED_TITLE = "SYNTHETIC one title the question's page repeats"
BEYOND_TITLE = "SYNTHETIC a work past the question's limit"
SEED_ONLY_TITLE = "SYNTHETIC a work only a seed's own request found"
PLAN_KEYS = {"version", "semantic", "keywords", "keyword_cap", "page_size", "order", "s2_bulk", "s2_bulk_index",
             "s2_reserved", "dropped", "expansion"}


class Scripted(SeedTransport):
    """The question's semantic request answers `question`, every other semantic request `seeded`; each OpenAlex
    request is logged in order as (kind, text, per_page)."""

    def __init__(self, works, question, seeded=(), by_doi=(), fail_seed=None):
        super().__init__(works, by_doi=by_doi)
        self.question, self.seeded, self.fail_seed, self.log = question, list(seeded), fail_seed, []

    def __call__(self, request):
        params = request.url.params
        if request.url.host == "api.openalex.org" and "search.semantic" in params:
            text = params["search.semantic"]
            self.semantic_queries.append(text)
            self.log.append(("semantic", text, int(params["per_page"])))
            if text.startswith(QUESTION):
                return httpx.Response(200, json={"meta": {"count": len(self.question)}, "results": self.question})
            if self.fail_seed and text.startswith(self.fail_seed):
                return httpx.Response(400, json={"error": "SYNTHETIC refused"})
            return httpx.Response(200, json={"meta": {"count": len(self.seeded)}, "results": self.seeded})
        if (request.url.host == "api.openalex.org" and "search.title_and_abstract" in params
                and params.get("select") != "id"):
            self.log.append(("keyword", params["search.title_and_abstract"], int(params["per_page"])))
        return super().__call__(request)


def titled(number, title):
    return work(number, title=title) | {"display_name": title}


def unseeded(client):
    return client.post("/api/researches", json={"question": QUESTION, "model_connection": "fake",
                                                "requested_model": "fake-model", "effort": "quick"}).json()["research"]["id"]


def provider_keys(store, run_id):
    return [s["operation_key"] for s in store.run_steps(run_id) if s["kind"].startswith("provider_search")]


# ---- 1. An unseeded run is the run before D6 ------------------------------------------------------------------------

def test_an_unseeded_plan_is_version_1_and_sends_no_seed_request(tmp_path, monkeypatch):
    app, _ = app_for(tmp_path, monkeypatch, transport=Scripted(records(), records()))
    with client_of(app) as client:
        rid = unseeded(client)
        run_id, _ = discovery(client, rid)
        store = app.state.store
        plan = protocol_body(store, run_id)["fast_path_search"]
        assert set(plan) == PLAN_KEYS and plan["version"] == 1
        assert set(plan["semantic"]) == {"provider_id", "endpoint", "query_text", "limit", "query_origin"}
        assert plan["semantic"]["query_text"] == QUESTION and plan["semantic"]["limit"] == 50
        assert not any(":seed:" in key for key in provider_keys(store, run_id))
        assert "accepted_source_version_ids" not in output(store, run_id, "search:fast:semantic")
        assert fast_search.graph_rule(store, store.run(run_id)) == "sum_v1"
        assert "graph_rule" not in output(store, run_id, small_batch.LIST_KEY)["manifest"]
        assert "seed_terms" not in (output(store, run_id, "search_query") or {})


def test_an_unseeded_plan_equals_the_plan_frozen_before_d6():
    """The plan HEAD's code (a09f22e) froze for this input, written down here: an unseeded plan is unchanged."""
    class Store:
        pass
    run = {"budget": {"fast_path": {"mode": "quick", "semantic_top": 50, "keyword_record_cap": 450}}}
    scope = {"question": QUESTION, "language_hint": None, "research_id": "r", "revision": 1}
    queries = [{"provider_id": "openalex", "query_text": "a AND b"}, {"provider_id": "pubmed", "query_text": "c"},
               {"provider_id": "semantic_scholar", "endpoint": "bulk", "query_text": "d"}]
    assert fast_search.build_plan(Store(), run, scope, queries) == {
        "version": 1, "semantic": {"provider_id": "openalex", "endpoint": "semantic", "query_text": QUESTION,
                                   "limit": 50, "query_origin": "question"},
        "keywords": [{"index": 0, "query": queries[0]}], "keyword_cap": 450, "page_size": 100,
        "order": "page_then_query", "s2_bulk": None, "s2_bulk_index": None, "s2_reserved": 0,
        "dropped": [{"index": 1, "query": queries[1], "reason": "openalex_only"},
                    {"index": 2, "query": queries[2], "reason": "openalex_only"}],
        "expansion": "fast_path_frozen_plan"}


# ---- 2. One request per seed, after the question's ------------------------------------------------------------------

def context(svid, status="matched", abstract="An abstract.", page=""):
    return {"source_version_id": svid, "status": status, "title": SEED_TITLE, "abstract": abstract,
            "first_page_text": page}


def test_each_seed_with_text_asks_once_with_its_own_text_and_half_the_question_limit():
    envelope = {"rule": seed_match.RULE, "seeds": [
        context("a"), context("b", status="no_match", page="x" * 2000), context("c", status="no_match", page="  "),
        context("d", abstract=None, page="Head of page one.")]}
    specs = fast_search.seed_requests(envelope, 25)
    assert [(s["index"], s["source_version_id"], s["origin"], s["limit"]) for s in specs] == [
        (0, "a", "match_abstract", 25), (1, "b", "pdf_excerpt", 25), (3, "d", "match_title_pdf_excerpt", 25)]
    assert specs[0]["query_text"] == f"{SEED_TITLE}. An abstract." and len(specs[1]["query_text"]) == 1500
    assert [fast_search.seed_key(s) for s in specs] == [
        "search:fast:semantic:seed:0", "search:fast:semantic:seed:1", "search:fast:semantic:seed:3"]
    assert all(s["provider_id"] == "openalex" and s["endpoint"] == "semantic" for s in specs)


def test_a_seeded_run_asks_the_unseeded_question_then_each_seed_then_the_keywords(tmp_path, monkeypatch):
    transport = Scripted(records(), records(), seeded=[titled(4000, SEED_ONLY_TITLE)], by_doi=[seed_work()])
    app, _ = app_for(tmp_path, monkeypatch, transport=transport)
    with client_of(app) as client:
        rid = research(client)
        a, b = upload(client, rid, "a.pdf", SEED_PDF), upload(client, rid, "b.pdf", pdf_of(TITLE_B))
        select(client, rid, source_version_ids=[a, b])
        run_id, view = discovery(client, rid)
        store = app.state.store
        plan = protocol_body(store, run_id)["fast_path_search"]
        assert plan["version"] == 2 and set(plan) == PLAN_KEYS | {"seed_semantic"}
        assert plan["semantic"]["query_text"] == QUESTION and set(plan["semantic"]) == {
            "provider_id", "endpoint", "query_text", "limit", "query_origin"}
        assert [(s["source_version_id"], s["limit"]) for s in plan["seed_semantic"]] == [(a, 25), (b, 25)]
        semantic = [entry for entry in transport.log if entry[0] == "semantic"]
        question = semantic.index(("semantic", QUESTION, 50))
        # B had no DOI: its lookup (D3) went before the plan; then the question, then A and B by their own text.
        assert [entry[1] for entry in semantic[question + 1:]] == [s["query_text"] for s in plan["seed_semantic"]]
        assert [entry[2] for entry in semantic[question + 1:]] == [25, 25]
        first_keyword = next(i for i, entry in enumerate(transport.log) if entry[0] == "keyword")
        assert transport.log.index(semantic[-1]) < first_keyword
        for i in (0, 1):
            step = store.existing_step(run_id, f"search:fast:semantic:seed:{i}")
            assert step["status"] == "succeeded" and step["output"]["fast_path_request"]["class"] == 0
            assert "accepted_source_version_ids" not in step["output"]
        # The seeds' finds enter the pool as search candidates, never as the first chain seeds.
        found = store.find_source_by_identifier("openalex", "W4000")
        assert found in {c["source_version_id"] for c in store.candidates(rid)}
        assert found not in {s["source_version_id"] for s in output(store, run_id, "fast_chain:seeds")["seeds"]}
        assert [u["semantic"] for u in (s["use"] for s in view["scope"]["seeds"])] == [True, True]
        assert fast_search.graph_rule(store, store.run(run_id)) == "seed_max_v2"
        listing = output(store, run_id, small_batch.LIST_KEY)
        assert listing["manifest"]["graph_rule"] == "seed_max_v2"
        assert small_batch.replay(listing["manifest"])["fused"] == listing["automatic_order"]


def test_a_failed_seed_request_shows_that_seed_did_not_guide_the_search(tmp_path, monkeypatch):
    transport = Scripted(records(), records(), by_doi=[seed_work()], fail_seed=SEED_TITLE)
    app, _ = app_for(tmp_path, monkeypatch, transport=transport)
    with client_of(app) as client:
        rid = research(client)
        a, b = upload(client, rid, "a.pdf", SEED_PDF), upload(client, rid, "b.pdf", pdf_of(TITLE_B))
        select(client, rid, source_version_ids=[a, b])
        run_id, view = discovery(client, rid)
        store = app.state.store
        assert store.existing_step(run_id, "search:fast:semantic")["status"] == "succeeded"
        assert store.existing_step(run_id, "search:fast:semantic:seed:0")["status"] == "failed"
        assert [s["use"]["semantic"] for s in view["scope"]["seeds"]] == [False, True]


def test_past_the_search_deadline_a_seed_request_is_closed_unsent(tmp_path, monkeypatch):
    transport = Scripted(records(), records(), by_doi=[seed_work()])
    app, _ = app_for(tmp_path, monkeypatch, transport=transport)
    real = fast_search.fast_path.past_deadline

    def past(store, run, stage):
        # The deadline falls once the question's request is written.
        sent = store.existing_step(run["id"], "search:fast:semantic")
        return stage == "search" and bool(sent and sent["status"] == "succeeded") or real(store, run, stage)

    monkeypatch.setattr(fast_search.fast_path, "past_deadline", past)
    with client_of(app) as client:
        rid, _ = seeded(client, SEED_PDF)
        run_id, _ = discovery(client, rid)
        step = app.state.store.existing_step(run_id, "search:fast:semantic:seed:0")
        assert (step["status"], step["error_code"]) == ("cancelled", "deadline")
        assert not [q for q in transport.semantic_queries if q.startswith(SEED_TITLE)]


def test_a_seed_request_admits_no_more_than_its_limit(tmp_path, monkeypatch):
    transport = Scripted(records(), records(), seeded=[titled(4100 + i, f"SYNTHETIC seed find {i}") for i in range(30)],
                         by_doi=[seed_work()])
    app, _ = app_for(tmp_path, monkeypatch, transport=transport)
    with client_of(app) as client:
        rid, _ = seeded(client, SEED_PDF)
        run_id, _ = discovery(client, rid)
        store = app.state.store
        step = output(store, run_id, "search:fast:semantic:seed:0")
        assert step["result_count"] == 25 and step["fast_path_request"]["returned_count"] == 30
        held = [w for w in (f"W{4100 + i}" for i in range(30)) if store.find_source_by_identifier("openalex", w)]
        assert held == [f"W{4100 + i}" for i in range(25)]


def test_an_exhausted_openalex_quota_sends_no_further_seed_request(tmp_path, monkeypatch):
    class Quota(Scripted):
        def __call__(self, request):
            text = request.url.params.get("search.semantic", "")
            if text.startswith(SEED_TITLE):
                self.semantic_queries.append(text)
                return httpx.Response(429, headers={"x-ratelimit-remaining-usd": "0"}, json={"error": "SYNTHETIC"})
            return super().__call__(request)

    transport = Quota(records(), records(), by_doi=[seed_work()])
    app, _ = app_for(tmp_path, monkeypatch, transport=transport)
    with client_of(app) as client:
        rid = research(client)
        a, b = upload(client, rid, "a.pdf", SEED_PDF), upload(client, rid, "b.pdf", pdf_of(TITLE_B))
        select(client, rid, source_version_ids=[a, b])
        run_id = client.post(f"/api/researches/{rid}/runs", json={"kind": "discovery"}).json()["id"]
        wait(client, rid, run_id)
        store = app.state.store
        first, second = (store.existing_step(run_id, f"search:fast:semantic:seed:{i}") for i in (0, 1))
        assert first["status"] == "failed" and json.loads(first["error_json"])["error_kind"] == "quota_exhausted"
        assert second["status"] == "failed" and second["delivery_class"] == "before_send"
        # Nothing semantic went out after the question's request but the refused first seed: B's request was held.
        semantic = [entry for entry in transport.log if entry[0] == "semantic"]
        assert semantic[-1][1] == QUESTION


def test_a_run_stopped_between_two_seed_requests_resumes_without_sending_the_first_again(tmp_path, monkeypatch):
    from deixis.workflow.flow import ResearchFlow
    original, state = ResearchFlow._checkpoint, {}

    def pause_after_first_seed(self, run_id, scope_revision=None):
        first = self.store.existing_step(run_id, "search:fast:semantic:seed:0")
        if first and first["status"] == "succeeded" and not state.get("paused"):
            state["paused"] = True
            self.store.update_run(run_id, event="run_pause_requested", status="pause_requested",
                                  pause_reason="user_requested")
        return original(self, run_id, scope_revision)

    monkeypatch.setattr(ResearchFlow, "_checkpoint", pause_after_first_seed)
    transport = Scripted(records(), records(), by_doi=[seed_work()])
    app, _ = app_for(tmp_path, monkeypatch, transport=transport)
    with client_of(app) as client:
        rid = research(client)
        a, b = upload(client, rid, "a.pdf", SEED_PDF), upload(client, rid, "b.pdf", pdf_of(TITLE_B))
        select(client, rid, source_version_ids=[a, b])
        run_id = client.post(f"/api/researches/{rid}/runs", json={"kind": "discovery"}).json()["id"]
        wait(client, rid, run_id, statuses=("paused",))
        store = app.state.store
        assert store.existing_step(run_id, "search:fast:semantic:seed:1") is None
        assert client.post(f"/api/runs/{run_id}/resume").status_code == 200
        _, run = wait(client, rid, run_id)
        assert run["status"] == "completed", run
        texts = [s["query_text"] for s in protocol_body(store, run_id)["fast_path_search"]["seed_semantic"]]
        assert [sum(q == text for q in transport.semantic_queries) for text in texts] == [1, 1]
        assert [output(store, run_id, f"search:fast:semantic:seed:{i}")["fast_path_request"]["request_index"]
                for i in (0, 1)] == [1, 2]
        assert sum(q == QUESTION for q in transport.semantic_queries) == 1


def test_searching_a_finished_run_again_sends_no_seed_request(tmp_path, monkeypatch):
    transport = Scripted(records(), records(), by_doi=[seed_work()])
    app, _ = app_for(tmp_path, monkeypatch, transport=transport)
    with client_of(app) as client:
        rid, _ = seeded(client, SEED_PDF)
        run_id, _ = discovery(client, rid)
        store, flow = app.state.store, app.state.worker.flow
        sent = len(transport.log)
        run = store.run(run_id) | {"status": "running"}
        monkeypatch.setattr(flow, "_checkpoint", lambda *args: None)
        monkeypatch.setattr(flow, "_stop_requested", lambda *args: False)
        asyncio.run(fast_search.execute(flow, run, store.scope(rid), fast_search.stored_plan(store, run), False))
        assert len(transport.log) == sent


# ---- 3. The first chain seeds come only from what the question's request accepted (v4) ------------------------------

def test_the_first_chain_seeds_are_only_what_the_question_request_accepted(tmp_path, monkeypatch):
    for frozen_before_d6 in (False, True):
        with monkeypatch.context() as patch:
            if frozen_before_d6:
                d3_frozen(patch)
            # 50 records within the question's limit share one title, so only the first can be a chain seed; two more
            # lie past the limit, one of which an earlier research already holds.
            question = ([titled(2000 + i, SHARED_TITLE) for i in range(50)]
                        + [titled(2050, BEYOND_TITLE), titled(2051, BEYOND_TITLE + " two")])
            transport = Scripted(records() + [titled(2050, BEYOND_TITLE)], question,
                                 seeded=[titled(4000, SEED_ONLY_TITLE)], by_doi=[seed_work()])
            app, _ = app_for(tmp_path / str(frozen_before_d6), patch, transport=transport)
            with client_of(app) as client:
                store = app.state.store
                discovery(client, unseeded(client))
                held, refound = (store.find_source_by_identifier("openalex", w) for w in ("W2050", "W2000"))
                assert held and refound
                rid, _ = seeded(client, SEED_PDF)
                run_id, _ = discovery(client, rid)
                seeds = output(store, run_id, "fast_chain:seeds")["seeds"]
                chosen = {s["source_version_id"] for s in seeds if s["origin"] == "semantic"}
                accepted = output(store, run_id, "search:fast:semantic").get("accepted_source_version_ids")
                # (b) a work found again (same version) enters; (d) the seed request's find does not.
                assert refound in chosen
                assert store.find_source_by_identifier("openalex", "W4000") not in chosen
                # A record past the limit that nobody held is never written, so it cannot be chosen either way.
                assert store.find_source_by_identifier("openalex", "W2051") is None
                if frozen_before_d6:
                    # The rule before D6: a held record past the limit was taken from the raw page.
                    assert accepted is None and held in chosen
                else:
                    # (a) past the limit and already held: not accepted, so not a first chain seed.
                    assert len(accepted) == 50 and held not in accepted and held not in chosen
                    assert chosen <= set(accepted)


def test_a_version_sent_to_another_versions_candidate_is_accepted_by_its_own_id(tmp_path):
    """(c) A preprint of a work whose published version already heads it: the step keeps the version the request itself
    wrote, the one its OpenAlex identifier names, not the work's head."""
    from deixis.storage import db
    from deixis.workflow.store import Store

    connection = db.connect(tmp_path / "library.sqlite")
    db.migrate(connection)
    store = Store(connection)
    rid = store.create_research("SYNTHETIC question?", "academic", "standard", ["openalex", "pubmed"], "fake", "m", "en")
    run_id = store.create_run(rid, "discovery", {"max_model_calls": 4, "max_provider_requests": 8, "max_candidates": 50,
                                                 "max_answer_passages": 8}, None)["id"]

    def record(record_id, doi, **extra):
        return ProviderRecord(provider_record_id=record_id, title="SYNTHETIC one study in two versions", authors=[],
                              year=2025, venue=None, publication_type=None, doi=doi, landing_url=None, oa_pdf_url=None,
                              oa_pdf_version=None, version_label=extra.pop("version_label", "publishedVersion"),
                              abstract=None, abstract_origin=None, identifiers=extra, raw={},
                              merge_by_doi=extra.pop("merge_by_doi", True))

    def search(key, records, keep_found):
        step = store.step(run_id, key, "provider_search:openalex")
        store.record_search(dict(
            research_id=rid, run_id=run_id, step_id=step["id"], scope_revision=1, provider="openalex", query_text="q",
            request_description="GET SYNTHETIC", access_mode="keyless", status="completed", delivery_class=None,
            result_count=len(records), provider_total=len(records), page_limit=25, error_json=None,
            raw_payload_path=None), "openalex", records, None, step["id"], "succeeded",
            step_output={"status": "completed"}, keep_found=keep_found)
        return store.existing_step(run_id, key)["output"]

    search("search:0", [record("W1", "10.9/one")], False)
    (candidate,) = store.candidates(rid)
    accepted = search("search:fast:semantic", [record(
        "W2", "10.48550/arxiv.2601.00001", merge_by_doi=False, version_label="submittedVersion",
        published_doi="10.9/one")], True)
    own = store.find_source_by_identifier("openalex", "W2")
    assert own and own != candidate["source_version_id"]
    assert store.source(own)["work_id"] == store.source(candidate["source_version_id"])["work_id"]
    assert accepted["accepted_source_version_ids"] == [own]
    assert store.work_heads(rid) == {store.source(own)["work_id"]: candidate["source_version_id"]}
    connection.close()


def test_the_first_chain_choice_takes_the_accepted_version_of_a_redirected_record(tmp_path, monkeypatch):
    """(c) through `Round.initial`: the question's page names the preprint W2 of a work whose published version heads
    it; the version the request wrote is accepted, so W2 is a first chain seed under version 2."""
    from types import SimpleNamespace
    from deixis.storage import db
    from deixis.workflow import fast_chain
    from deixis.workflow.store import Store

    connection = db.connect(tmp_path / "library.sqlite")
    db.migrate(connection)
    store = Store(connection)
    rid = store.create_research("SYNTHETIC question?", "academic", "standard", ["openalex"], "fake", "m", "en")
    run = store.create_run(rid, "discovery", {"max_model_calls": 4, "max_provider_requests": 8, "max_candidates": 50,
                                              "max_answer_passages": 8}, None)

    def record(record_id, doi, **extra):
        return ProviderRecord(provider_record_id=record_id, title=f"SYNTHETIC version {record_id}", authors=[],
                              year=2025, venue=None, publication_type=None, doi=doi, landing_url=None, oa_pdf_url=None,
                              oa_pdf_version=None, version_label=extra.pop("version_label", "publishedVersion"),
                              abstract=None, abstract_origin=None, identifiers=extra, raw={},
                              merge_by_doi=extra.pop("merge_by_doi", True))

    def search(key, records, keep_found, payload=None):
        step = store.step(run["id"], key, "provider_search:openalex")
        path = None
        if payload is not None:
            path = f"{key}.json"
            (tmp_path / path).write_text(json.dumps(payload))
        store.record_search(dict(
            research_id=rid, run_id=run["id"], step_id=step["id"], scope_revision=1, provider="openalex",
            query_text="q", request_description="GET SYNTHETIC", access_mode="keyless", status="completed",
            delivery_class=None, result_count=len(records), provider_total=len(records), page_limit=25,
            error_json=None, raw_payload_path=path), "openalex", records, path, step["id"], "succeeded",
            step_output={"status": "completed"}, keep_found=keep_found)

    search("search:0", [record("W1", "10.9/one"), record("W3", "10.9/three")], False)
    preprint = record("W2", "10.48550/arxiv.2601.00002", merge_by_doi=False, version_label="submittedVersion",
                      published_doi="10.9/one")
    page = {"results": [{"id": "https://openalex.org/W2", "referenced_works": ["https://openalex.org/W9"]},
                        {"id": "https://openalex.org/W3", "referenced_works": []}]}
    search("search:fast:semantic", [preprint], True, page)
    accepted = store.existing_step(run["id"], "search:fast:semantic")["output"]["accepted_source_version_ids"]
    head = store.work_heads(rid)[store.source(accepted[0])["work_id"]]
    assert accepted == [store.find_source_by_identifier("openalex", "W2")] and head != accepted[0]

    def first_choice(version):
        monkeypatch.setattr(fast_search, "plan_version", lambda store_, run_: version)
        monkeypatch.setattr(fast_chain.seed_match, "frozen", lambda store_, run_: None)
        monkeypatch.setattr(fast_chain.ranking, "verified_seeds", lambda store_, rid_, scope_: [])
        store.conn.execute("DELETE FROM run_steps WHERE run_id = ? AND operation_key LIKE 'fast_chain:%'", (run["id"],))
        round_ = fast_chain.Round.__new__(fast_chain.Round)
        round_.flow = SimpleNamespace(_checkpoint=lambda *args: None,
                                      deps=SimpleNamespace(settings=SimpleNamespace(payloads_dir=tmp_path)))
        round_.store, round_.run, round_.scope, round_.closed = store, run, {}, False
        round_.policy = {"chain_seeds": 10, "backward_page_size": 50, "backward_requests": 2, "forward_requests": 2,
                         "forward_page_size": 50}
        round_.launch = lambda specs: None
        round_.initial()
        return [s["openalex_id"] for s in store.existing_step(run["id"], "fast_chain:seeds")["output"]["seeds"]]

    # Version 2 takes only the accepted preprint; the rule before D6 also took the held W3, which the page named but
    # this request never wrote.
    assert first_choice(2) == ["W2"]
    assert first_choice(1) == ["W2", "W3"]
    connection.close()


# ---- 4. The ranking: seed PDFs take no code seed's place and count by the nearest -----------------------------------

def row(rid, refs, *, work=None, own=None, pdf=False):
    found = {"id": rid, "work_id": work or f"w-{rid}", "title": f"SYNTHETIC {rid}", "abstract": None,
             "own_ids": frozenset(own or {f"O{rid}"}), "references": frozenset(refs)}
    return found | ({"seed_pdf": True} if pdf else {})


def pool_of(n=24):
    return [row(f"r{i:02d}", {f"R{i}", "RA"}) for i in range(n)]


def test_three_seed_pdfs_push_no_code_seed_out():
    pool = pool_of()
    pdfs = [row(f"p{i}", {"RA", f"P{i}"}, pdf=True) for i in range(3)]
    old = ranking.rank_pool(pool, pdfs, {"synthetic"}, {}, None, {})
    new = ranking.rank_pool(pool, pdfs, {"synthetic"}, {}, None, {}, graph_rule="seed_max_v2")
    assert len(old["graph_seeds"]) == ranking.GRAPH_SEEDS and old["graph_seeds"][:3] == pdfs
    code = [s for s in new["graph_seeds"] if not s.get("seed_pdf")]
    assert len(code) == ranking.GRAPH_SEEDS and new["graph_seeds"][-3:] == pdfs


def test_nearness_to_two_seed_pdfs_is_not_added_up():
    near_two = row("x", {"S1", "S2", "Z"})
    near_one = row("y", {"S1", "Z", "Q"})
    pdfs = [row("p1", {"S1", "K1"}, pdf=True), row("p2", {"S2", "K2"}, pdf=True)]
    summed = ranking.graph_scores([near_two, near_one], pdfs)
    nearest = ranking.graph_scores_v2([near_two, near_one], [], pdfs)
    assert summed["x"] > summed["y"]
    assert nearest["x"] == nearest["y"] == summed["y"]
    # A seed PDF never scores its own work, and the user's and code's seeds still add up.
    own = row("p1copy", {"S1"}, work="w-p1")
    assert ranking.graph_scores_v2([own], [], pdfs[:1]) == {"p1copy": 0.0}
    others = [row("u1", {"Z"}), row("u2", {"Z"})]
    assert ranking.graph_scores_v2([near_one], others, []) == ranking.graph_scores([near_one], others)


def test_without_seed_pdfs_the_new_rule_ranks_as_the_old():
    pool = pool_of()
    included = [pool[3], row("u", {"RA", "R7"})]
    old = ranking.rank_pool(pool, included, {"synthetic"}, {}, None, {})
    new = ranking.rank_pool(pool, included, {"synthetic"}, {}, None, {}, graph_rule="seed_max_v2")
    assert old["fused"] == new["fused"] and old["ranks"] == new["ranks"]
    assert [s["id"] for s in old["graph_seeds"]] == [s["id"] for s in new["graph_seeds"]]


def test_a_frozen_list_replays_under_the_rule_it_froze():
    pool = pool_of()
    pdfs = [row(f"p{i}", {"RA", f"R{i}"}, pdf=True) for i in range(3)]

    def stored(r):
        return r | {"own_ids": sorted(r["own_ids"]), "references": sorted(r["references"]), "cited_by_count": None}
    manifest = {"ranking_version": 3, "pool": [stored(r) for r in pool], "verified": [stored(r) for r in pdfs],
                "query_words": ["synthetic"], "blocks": {}, "embedding_model": None, "similarities": {},
                "off_reason": None, "compared_terms": None}
    old = small_batch.replay(manifest)
    new = small_batch.replay(manifest | {"graph_rule": "seed_max_v2"})
    assert old["graph_seeds"][:3] == [r | {"own_ids": set(r["own_ids"]), "references": set(r["references"])}
                                      for r in manifest["verified"]]
    assert [s["id"] for s in new["graph_seeds"][-3:]] == ["p0", "p1", "p2"]
    assert small_batch.replay(manifest)["fused"] == old["fused"]


def test_a_seed_pdfs_openalex_copy_is_never_a_summed_seed_in_the_frozen_list():
    pool = pool_of()
    copy = row("copy", {"RA", "P0"}, own={"W900"})
    pdf = row("p0", {"RA", "P0"}, own={"W900", "Op0"}, pdf=True)

    def stored(r):
        return r | {"own_ids": sorted(r["own_ids"]), "references": sorted(r["references"]), "cited_by_count": None}
    manifest = {"ranking_version": 3, "pool": [stored(r) for r in [copy] + pool], "verified": [stored(pdf)],
                "query_words": ["synthetic"], "blocks": {}, "embedding_model": None, "similarities": {},
                "off_reason": None, "compared_terms": None, "graph_rule": "seed_max_v2"}
    ranked = small_batch.replay(manifest)
    assert "copy" not in [s["id"] for s in ranked["graph_seeds"]]
    assert [s["id"] for s in ranked["graph_seeds"]][-1] == "p0"


# ---- 5. A run frozen before D6 finishes under it ---------------------------------------------------------------------

def test_a_run_frozen_before_d6_finishes_under_d3(tmp_path, monkeypatch):
    d3_frozen(monkeypatch)
    transport = Scripted(records(), records(), by_doi=[seed_work()])
    app, _ = app_for(tmp_path, monkeypatch, transport=transport)
    with client_of(app) as client:
        rid, _ = seeded(client, SEED_PDF)
        run_id, view = discovery(client, rid)
        store = app.state.store
        plan = protocol_body(store, run_id)["fast_path_search"]
        assert plan["version"] == 1 and plan["semantic"]["seed_parts"] and "seed_semantic" not in plan
        assert not any(":seed:" in key for key in provider_keys(store, run_id))
        assert fast_search.graph_rule(store, store.run(run_id)) == "sum_v1"
        assert "graph_rule" not in output(store, run_id, small_batch.LIST_KEY)["manifest"]
        assert view["scope"]["seeds"][0]["use"]["semantic"] is True


def test_a_run_that_froze_d3s_plan_and_paused_resumes_under_d6_code_without_seed_requests(tmp_path, monkeypatch):
    from deixis.workflow.flow import ResearchFlow
    original, state = ResearchFlow._close_clock_stage, {}

    def paused_after_planning(self, run, stage):
        original(self, run, stage)
        if stage == "plan" and not state.get("paused"):
            state["paused"] = True
            self.store.update_run(run["id"], event="run_pause_requested", status="pause_requested",
                                  pause_reason="user_requested")

    monkeypatch.setattr(ResearchFlow, "_close_clock_stage", paused_after_planning)
    transport = Scripted(records(), records(), by_doi=[seed_work()])
    app, _ = app_for(tmp_path, monkeypatch, transport=transport)
    with client_of(app) as client:
        store = app.state.store
        rid, _ = seeded(client, SEED_PDF)
        with monkeypatch.context() as patch:
            d3_frozen(patch)
            run_id = client.post(f"/api/researches/{rid}/runs", json={"kind": "discovery"}).json()["id"]
            wait(client, rid, run_id, statuses=("paused",))
        frozen = output(store, run_id, "protocol")
        assert protocol_body(store, run_id)["fast_path_search"]["version"] == 1
        # D3's plan is gone from the code; the resumed run reads the plan it froze.
        assert client.post(f"/api/runs/{run_id}/resume").status_code == 200
        _, run = wait(client, rid, run_id)
        assert run["status"] == "completed", run
        assert output(store, run_id, "protocol") == frozen
        assert not any(":seed:" in key for key in provider_keys(store, run_id))
        assert [q for q in transport.semantic_queries if q.startswith(QUESTION)][0].startswith(QUESTION + " ")
        assert not [q for q in transport.semantic_queries if q.startswith(SEED_TITLE)]
        assert "accepted_source_version_ids" not in output(store, run_id, "search:fast:semantic")
        assert fast_search.graph_rule(store, store.run(run_id)) == "sum_v1"
        assert "graph_rule" not in output(store, run_id, small_batch.LIST_KEY)["manifest"]


# ---- 6. seed_terms: the terms the seeds brought, a diagnosis only ---------------------------------------------------

def test_seed_terms_are_the_searched_terms_with_no_question_word_and_a_seed_word():
    terms = [{"phrase": "deficit irrigation", "block": "task", "dropped": None},
             {"phrase": "Greenhouse Tomato", "block": "setting", "dropped": None},
             {"phrase": "crop water stress index", "block": "task", "dropped": None},
             {"phrase": "stomatal conductance", "block": "task", "dropped": "no_records"},
             {"phrase": "lysimeter", "block": "setting", "dropped": None}]
    passages = [{"text": "Crop WATER stress and stomatal conductance under deficit irrigation."}]
    question = ["Does irrigation scheduling affect greenhouse tomato yield?", "Sulama zamanlaması verimi etkiler mi?"]
    assert search_query.seed_terms(terms, question, passages) == [{"phrase": "crop water stress index", "block": "task"}]
    assert search_query.seed_terms(terms, question, []) == []


def test_a_seeded_model_query_records_its_seed_terms(tmp_path, monkeypatch):
    transport = Scripted(records(), records(), by_doi=[seed_work()])
    app, _ = app_for(tmp_path, monkeypatch, transport=transport, search_query="model")
    with client_of(app) as client:
        rid, _ = seeded(client, SEED_PDF)
        run_id, _ = discovery(client, rid)
        query = output(app.state.store, run_id, "search_query")
        assert query["status"] == "ready" and isinstance(query["seed_terms"], list)
        terms = [t for t in query["vocabulary"]["terms"] if not t.get("dropped")]
        assert query["seed_terms"] == search_query.seed_terms(terms, [QUESTION], [
            p for s in app.state.store.scope(rid)["seeds"] for p in s["passages"]])
