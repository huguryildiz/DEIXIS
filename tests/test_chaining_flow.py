"""Citation chaining inside a real `sw` discovery run, driven through the API (slice 15, D95).

What is checked here is workflow behavior: that the chain runs after the keyword abstract stage and only when the run's
budget froze it on; that the keyword ranking, the keyword read plan and the keyword groups of the full-text plan are
the same with and without it; that a reference the research holds costs no request, a failed request stops nothing,
the chain's own request limit ends the chain and not the run, and a resumed run asks OpenAlex nothing twice; that the
chained works get their own read limit; and that a `legacy` research and a run queued before D95 never chain.

Records, titles and abstracts are SYNTHETIC and from two fields (greenhouse irrigation, warehouse pallet loading);
OpenAlex is mocked and the model is scripted. Passing shows the chain behaves as the slice says, not that a real chain
reaches relevant works, which the slice's replay and live acceptance measure.
"""

import json
import time

import httpx

from deixis.api.app import create_app
from deixis.config import Settings
from deixis.domain.rules import ABSTRACT_BATCH, CHAIN_ABSTRACT_READ
from deixis.models.adapter import ModelStepResult
from deixis.providers.registry import CONNECTORS
from deixis.workflow import fulltext
from fakes import FakeAdapter, valid_response
from test_abstract_flow import (ON_ABSTRACT, ON_TOPIC, QUESTION, client_of, codes_of, records_of, responder, step_output,
                                wait)
from test_fulltext_flow import Fetcher

PACKING_QUESTION = "How does pallet loading order affect picking time in warehouse operations?"
IRRIGATION = "SYNTHETIC irrigation scheduling of an open field crop"
IRRIGATION_ABSTRACT = "We vary the irrigation scheduling of an open field crop and report the water it used."
PACKING = "SYNTHETIC pallet loading order in a warehouse"
PACKING_ABSTRACT = "We vary the pallet loading order in a warehouse and report the picking time."
OFF_TOPIC = "SYNTHETIC bakery delivery rounds of a small town"
OFF_ABSTRACT = "We measure the bread delivery rounds of a small town bakery and report the distance covered."


def work(number, title=IRRIGATION, abstract=IRRIGATION_ABSTRACT, doi=None, references=(), authors=(), name=None):
    """One SYNTHETIC OpenAlex record with its own reference list."""
    inverted: dict[str, list[int]] = {}
    for position, word in enumerate((abstract or "").split()):
        inverted.setdefault(word, []).append(position)
    return {"id": f"https://openalex.org/W{number}", "doi": f"https://doi.org/{doi or f'10.1/oa.{number}'}",
            "display_name": name or f"{title} {number}", "publication_year": 2024, "type": "article",
            "authorships": [{"author": {"display_name": author}} for author in authors],
            "abstract_inverted_index": inverted or None,
            "referenced_works": [f"https://openalex.org/W{ref}" for ref in references],
            "referenced_works_count": len(references)}


class OpenAlex:
    """Mocked OpenAlex: count probes, one page of keyword records, and the chain's two requests.

    `citing` answers `filter=cites:W…` by cursor, `by_id` answers `filter=openalex:W1|W2…`; every chain request is
    recorded, so a test can ask what was sent and what a resumed run sent again.
    """

    def __init__(self, works, citing=None, by_id=None, fail_cites=(), on_chain=None, limited_cites=()):
        self.works, self.citing, self.by_id = works, citing or {}, by_id or {}
        self.fail_cites, self.on_chain, self.limited_cites = set(fail_cites), on_chain, set(limited_cites)
        self.chain: list[tuple] = []
        self.pages: list[int] = []

    def __call__(self, request):
        if request.url.host != "api.openalex.org":
            return httpx.Response(404)
        params = request.url.params
        found = params.get("filter") or ""
        if found.startswith("cites:"):
            wid, cursor = found.removeprefix("cites:"), params.get("cursor")
            self.chain.append(("forward", wid, cursor))
            if self.on_chain:
                self.on_chain(self)
            if wid in self.fail_cites:
                return httpx.Response(500, text="SYNTHETIC server error")
            if wid in self.limited_cites:
                return httpx.Response(429, headers={"Retry-After": "0"}, text="SYNTHETIC rate limit")
            works, size = self.citing.get(wid, []), int(params["per_page"])
            self.pages.append(size)
            start = 0 if cursor in (None, "*") else int(cursor)
            end = min(start + size, len(works))
            return httpx.Response(200, json={"meta": {"count": len(works),
                                                      "next_cursor": str(end) if end < len(works) else None},
                                             "results": works[start:end]})
        if found.startswith("openalex:"):
            ids = found.removeprefix("openalex:").split("|")
            self.chain.append(("backward", tuple(ids)))
            if self.on_chain:
                self.on_chain(self)
            results = [self.by_id[i] for i in ids if i in self.by_id]
            return httpx.Response(200, json={"meta": {"count": len(results)}, "results": results})
        query = params.get("search.title_and_abstract") or ""
        if params.get("per_page") == "1" and params.get("select") == "id":
            return httpx.Response(200, json={"meta": {"count": 1 if " AND " in query else 40}, "results": []})
        return httpx.Response(200, json={"meta": {"count": len(self.works), "next_cursor": None},
                                         "results": self.works})


def app_for(tmp_path, monkeypatch, handler, chaining="auto", workflow="sw", adapter=None, fetch="off", fetcher=None,
            overlap=True):
    if not overlap:
        # A discovery run queued before slice 17a: its fetch follows as a retrieval run of its own (decision 3).
        monkeypatch.setattr(fulltext, "overlap_budget", fulltext.fetch_budget)
    for connector in CONNECTORS.values():
        if connector.key_env:
            monkeypatch.delenv(connector.key_env, raising=False)
    monkeypatch.delenv("GEMINI_API_KEY", raising=False)
    monkeypatch.setenv("DEIXIS_SEARCH_WORKFLOW", workflow)
    return create_app(Settings(data_dir=tmp_path / "data", port=8765, search_workflow=workflow, search_query="code",
                               protocol_approval="as_proposed", fulltext_fetch=fetch, fulltext_adjudication="off",
                               citation_chaining=chaining),
                      adapters={"fake": adapter or FakeAdapter(responder())},
                      http_client=httpx.AsyncClient(transport=httpx.MockTransport(handler)),
                      fetcher=fetcher or Fetcher({}), extra_hosts=("testserver",), trusted_clients=("testclient",))


def discover(client, question=QUESTION, effort="quick"):
    payload = {"question": question, "model_connection": "fake", "requested_model": "fake-model", "effort": effort}
    rid = client.post("/api/researches", json=payload).json()["research"]["id"]
    run_id = client.post(f"/api/researches/{rid}/runs", json={"kind": "discovery"}).json()["id"]
    return (rid, run_id, *wait(client, rid, run_id))


def keys(store, run_id):
    return [s["operation_key"] for s in store.run_steps(run_id)]


def chain_links(store, run_id):
    return [dict(row) for row in store.conn.execute(
        "SELECT seed_source_version_id, linked_openalex_id, direction, passed_filter, source_version_id"
        " FROM chain_links WHERE run_id = ? ORDER BY linked_openalex_id, direction, seed_source_version_id", (run_id,))]


def openalex_of(store, svids):
    """The OpenAlex identifiers of these records, in order, so two libraries can be compared."""
    ids = {row[0]: row[1] for row in store.conn.execute(
        "SELECT source_version_id, value FROM identifier_mappings WHERE scheme = 'openalex'")}
    return [ids.get(svid, svid) for svid in svids]


def keyword_pool():
    """Five keyword works that cite each other and three works outside the research. Each abstract is a little longer
    than the one before, so no two works tie in BM25 and the order does not fall back on random record identifiers."""
    return [work(n, abstract=IRRIGATION_ABSTRACT + " Plot" * n, references=references)
            for n, references in ((1, (2, 900)), (2, (901,)), (3, (1, 902)), (4, ()), (5, (900,)))]


# ---- when the chain runs ------------------------------------------------------------------------

def test_an_sw_run_chains_after_the_abstract_stage(tmp_path, monkeypatch):
    by_id = {"W900": work(900), "W901": work(901, OFF_TOPIC, OFF_ABSTRACT), "W902": work(902, abstract=None)}
    transport = OpenAlex(keyword_pool(), citing={"W1": [work(700), work(701, OFF_TOPIC, OFF_ABSTRACT)]}, by_id=by_id)
    # The full text is fetched beside the screening (slice 17a); the chain's steps keep their order around it.
    app = app_for(tmp_path, monkeypatch, transport, fetch="auto", overlap=True)
    client = client_of(app)
    try:
        rid, run_id, view, run = discover(client)
        store = app.state.store
        order, seeds = keys(store, run_id), step_output(store, run_id, "chain_seeds")
        chained = step_output(store, run_id, "chain_filter")
        chained_ids = sorted(openalex_of(store, chained["chained"]))
        summary = step_output(store, run_id, "chain_summary")
        records, codes = records_of(store, rid), codes_of(store, rid)
        counts = next(r for r in view["runs"] if r["id"] == run_id)["source_counts"]
    finally:
        client.__exit__(None, None, None)
    assert run["status"] == "completed", run
    assert (order.index("abstract_stage") < order.index("chain_seeds") < order.index("chain:backward:0")
            < order.index("chain_filter") < order.index("chain_ranking") < order.index("chain_abstract_stage")
            < order.index("chain_summary"))
    # The fetch starts after the keyword code step and its final plan waits for the chain (item 6).
    assert order.index("abstract_stage") < order.index("fetch_baseline")
    assert order.index("chain_summary") < order.index("fulltext_plan") < order.index("fulltext_summary")
    assert [s["kind"] for s in seeds["seeds"]] == ["code"] * 5 and seeds["backward_batches"] == [["W900", "W901", "W902"]]
    # What passed the filter is a record of the research; what did not is a link and nothing else.
    assert {"W700", "W900", "W902"} <= set(records) and not {"W701", "W901"} & set(records)
    assert chained_ids == ["W700", "W900", "W902"]
    assert chained["failed_filter"] == 2 and summary["new_works"] == 3
    assert codes["W902"] == "no_abstract"  # no second source is asked for a chained record's abstract
    assert {codes["W700"], codes["W900"]} == {"runs_agree_candidate"}
    assert "abstract_screening:chain:0:1" in order and "abstract_screening:chain:0:2" in order
    assert counts["chain"] == {"works": 3, "only": 3}
    # The run view carries the chain's summary, with its seeds, for the transcript's chain line.
    shown = next(s for r in view["runs"] if r["id"] == run_id for s in r["steps"] if s["kind"] == "code:chain_summary")
    assert shown["output"]["new_works"] == 3 and shown["output"]["requests"]["sent"] == 6  # five citing requests, one reference batch
    assert [seed["kind"] for seed in shown["output"]["seed_list"]] == ["code"] * 5


def test_chaining_off_sends_nothing_and_writes_no_step(tmp_path, monkeypatch):
    transport = OpenAlex(keyword_pool(), citing={"W1": [work(700)]}, by_id={"W900": work(900)})
    app = app_for(tmp_path, monkeypatch, transport, chaining="off")
    client = client_of(app)
    try:
        rid, run_id, view, run = discover(client)
        store = app.state.store
        steps = keys(store, run_id)
        body = store.current_protocol(rid, 1)["body"]
    finally:
        client.__exit__(None, None, None)
    assert run["status"] == "completed" and transport.chain == []
    assert not [key for key in steps if "chain" in key]
    assert run["budget"]["citation_chaining"] == "off" and "max_chain_requests" not in run["budget"]
    assert body["citation_chaining"] == {"enabled": False} and "chain" not in body["thresholds"]


def test_a_legacy_research_never_chains(tmp_path, monkeypatch):
    transport = OpenAlex(keyword_pool(), citing={"W1": [work(700)]})
    app = app_for(tmp_path, monkeypatch, transport, workflow="legacy", adapter=FakeAdapter(valid_response))
    client = client_of(app)
    try:
        rid, run_id, view, run = discover(client)
        store = app.state.store
        steps = keys(store, run_id)
        body = store.current_protocol(rid, 1)["body"]
    finally:
        client.__exit__(None, None, None)
    assert run["status"] == "completed" and transport.chain == []
    assert not [key for key in steps if "chain" in key]
    assert "citation_chaining" not in run["budget"] and "citation_chaining" not in body


def test_a_run_queued_before_this_change_keeps_its_budget(tmp_path, monkeypatch):
    from deixis.domain.rules import CRITERION_CALLS, SUGGESTION_CALLS, TEST_EFFORT_BUDGETS

    transport = OpenAlex(keyword_pool(), citing={"W1": [work(700)]})
    app = app_for(tmp_path, monkeypatch, transport)
    client = client_of(app)
    try:
        payload = {"question": QUESTION, "model_connection": "fake", "requested_model": "fake-model", "effort": "quick"}
        rid = client.post("/api/researches", json=payload).json()["research"]["id"]
        store = app.state.store
        # The budget an sw discovery run was queued with before D95: no chain setting and no chain calls.
        preset = TEST_EFFORT_BUDGETS["quick"].__dict__
        old = preset | {"max_model_calls": preset["max_model_calls"] + CRITERION_CALLS + SUGGESTION_CALLS + 4}
        queued = store.create_run(rid, "discovery", old, None)
        app.state.worker.wake()
        view, run = wait(client, rid, queued["id"])
        body = store.current_protocol(rid, 1)["body"]
        chain_steps = [key for key in keys(store, queued["id"]) if "chain" in key]
    finally:
        client.__exit__(None, None, None)
    assert run["status"] == "completed" and run["budget"] == old and transport.chain == []
    assert chain_steps == [] and "citation_chaining" not in body and "chain" not in body["thresholds"]


# ---- what the chain sends ---------------------------------------------------------------------

def test_backward_links_the_library_holds_send_no_request(tmp_path, monkeypatch):
    transport = OpenAlex(keyword_pool(), by_id={"W900": work(900), "W901": work(901), "W902": work(902)})
    app = app_for(tmp_path, monkeypatch, transport)
    client = client_of(app)
    try:
        rid, run_id, view, run = discover(client)
        seeds = step_output(app.state.store, run_id, "chain_seeds")
    finally:
        client.__exit__(None, None, None)
    backward = [entry[1] for entry in transport.chain if entry[0] == "backward"]
    # W1 and W2 are keyword works the seeds cite: they are held, and only the three outside works are asked for.
    assert backward == [("W900", "W901", "W902")]
    assert seeds["references_held"] == 2


def test_a_failed_citing_request_is_recorded_and_the_others_go_on(tmp_path, monkeypatch):
    transport = OpenAlex(keyword_pool(), citing={"W1": [work(700)], "W3": [work(703)]}, fail_cites={"W1"})
    app = app_for(tmp_path, monkeypatch, transport)
    client = client_of(app)
    try:
        rid, run_id, view, run = discover(client)
        store = app.state.store
        steps = {s["operation_key"]: s for s in store.run_steps(run_id)}
        summary = step_output(store, run_id, "chain_summary")
        failed = [r for r in view["search_runs"] if r["query_text"] == "chain:forward:W1"]
        records = records_of(store, rid)
    finally:
        client.__exit__(None, None, None)
    assert run["status"] == "completed", run
    assert steps["chain:forward:W1:1"]["status"] in ("failed", "outcome_unknown")
    assert steps["chain:forward:W3:1"]["status"] == "succeeded" and "W703" in records and "W700" not in records
    assert failed and failed[0]["status"] == "failed" and summary["requests"]["failed"] == 1


def test_the_chain_request_limit_stops_chaining_without_pausing_the_run(tmp_path, monkeypatch):
    monkeypatch.setattr("deixis.api.app.CHAIN_REQUEST_LIMIT", 3)
    transport = OpenAlex(keyword_pool(), citing={f"W{n}": [work(700 + n)] for n in range(1, 6)},
                         by_id={"W900": work(900)})
    app = app_for(tmp_path, monkeypatch, transport)
    client = client_of(app)
    try:
        rid, run_id, view, run = discover(client)
        summary = step_output(app.state.store, run_id, "chain_summary")
    finally:
        client.__exit__(None, None, None)
    assert run["status"] == "completed" and run["pause_reason"] is None
    assert len(transport.chain) == 3 and run["usage"]["chain_requests"] == 3
    assert summary["requests"]["sent"] == 3 and summary["requests"]["not_reached_seeds"] == 3
    assert run["usage"].get("provider_requests", 0) <= run["budget"]["max_provider_requests"] + 10


def test_user_seeds_do_not_shorten_the_fifteen_code_seeds(tmp_path, monkeypatch):
    pool = [work(n, PACKING, PACKING_ABSTRACT) for n in range(1, 21)]
    transport = OpenAlex(pool)
    app = app_for(tmp_path, monkeypatch, transport)
    client = client_of(app)
    try:
        rid, first, view, run = discover(client, question=PACKING_QUESTION)
        store = app.state.store
        chosen = records_of(store, rid)["W7"]
        version = next(s for s in view["sources"] if s["source_version_id"] == chosen)["selection"]["version"]
        client.patch(f"/api/researches/{rid}/selections/{chosen}",
                     json={"state": "included", "expected_version": version, "reason": "SYNTHETIC: the user's own seed"})
        second = client.post(f"/api/researches/{rid}/runs", json={"kind": "discovery"}).json()["id"]
        wait(client, rid, second)
        seeds = step_output(store, second, "chain_seeds")
        ranking = step_output(store, second, "ranking")
    finally:
        client.__exit__(None, None, None)
    kinds = [seed["kind"] for seed in seeds["seeds"]]
    assert kinds.count("code") == 15 and kinds.count("user") == 1
    assert chosen not in [s["source_version_id"] for s in seeds["seeds"] if s["kind"] == "code"]
    # The ranking's own graph seeds are fifteen in all, the user's included: that list is shorter by one.
    assert sum(seed["kind"] == "code" for seed in ranking["seeds"]) == 14


# ---- what the chain writes --------------------------------------------------------------------

def test_a_chained_record_that_merges_into_a_pool_work_is_not_chained(tmp_path, monkeypatch):
    # W800 is W4 under another OpenAlex identifier: the same DOI makes it the same source version.
    transport = OpenAlex(keyword_pool(), citing={"W1": [work(800, doi="10.1/oa.4"), work(801)]})
    app = app_for(tmp_path, monkeypatch, transport)
    client = client_of(app)
    try:
        rid, run_id, view, run = discover(client)
        store = app.state.store
        chained = openalex_of(store, step_output(store, run_id, "chain_filter")["chained"])
        links = chain_links(store, run_id)
        filtered = step_output(store, run_id, "chain_filter")
    finally:
        client.__exit__(None, None, None)
    assert chained == ["W801"] and filtered["in_keyword_pool"] == 1
    assert {row["linked_openalex_id"] for row in links if row["passed_filter"]} == {"W800", "W801"}


def test_a_published_version_the_chain_joins_to_a_keyword_preprint_keeps_the_keyword_place(tmp_path, monkeypatch):
    # W4 is a keyword preprint; the chain brings W804, its published version (same title, abstract and author).
    # The record path joins them into one work headed by the published record. That work is a keyword work: it is
    # not chained, and it keeps the keyword place its preprint had in the full-text plan.
    title, abstract = "SYNTHETIC irrigation scheduling of a joined crop study", IRRIGATION_ABSTRACT + " Plot" * 4

    def library(path, chaining):
        pool = keyword_pool()
        pool[3] = work(4, abstract=abstract, doi="10.48550/arxiv.2401.00004", authors=("Ada Rainfield",), name=title)
        citing = {"W1": [work(804, abstract=abstract, doi="10.1/pub.4", authors=("Ada Rainfield",), name=title),
                         work(801)]}
        app = app_for(path, monkeypatch, OpenAlex(pool, citing=citing), chaining=chaining, fetch="auto")
        client = client_of(app)
        try:
            rid, run_id, view, run = discover(client)
            store = app.state.store
            # The plan is the one the discovery run writes itself once its screening is done (slice 17a).
            plan = step_output(store, run_id, "fulltext_plan")
            work_of = store.work_ids(plan["works"])
            # Each planned work by every OpenAlex identifier its records carry, so a new head reads as the same work.
            planned = [sorted(openalex_of(store, [row[0] for row in store.conn.execute(
                "SELECT id FROM source_versions WHERE work_id = ?", (work_of[head],))])) for head in plan["works"]]
            filtered = step_output(store, run_id, "chain_filter") if chaining == "auto" else None
        finally:
            client.__exit__(None, None, None)
        return planned, filtered

    on, filtered = library(tmp_path / "on", "auto")
    off, _ = library(tmp_path / "off", "off")
    assert ["W4", "W804"] in on and filtered["in_keyword_pool"] >= 1
    assert [w for w in on if w != ["W801"]] == [["W4", "W804"] if w == ["W4"] else w for w in off]
    assert on[-1] == ["W801"]


def test_the_chain_read_reads_at_most_its_limit_and_leaves_the_rest_unread(tmp_path, monkeypatch):
    many = [work(700 + n, abstract=f"{IRRIGATION_ABSTRACT} Plot {n}.") for n in range(CHAIN_ABSTRACT_READ["quick"] + 5)]
    transport = OpenAlex(keyword_pool(), citing={"W1": many})
    app = app_for(tmp_path, monkeypatch, transport)
    client = client_of(app)
    try:
        rid, run_id, view, run = discover(client)
        store = app.state.store
        plan = step_output(store, run_id, "chain_abstract_stage")
        codes = codes_of(store, rid)
        model_keys = [key for key in keys(store, run_id) if key.startswith("abstract_screening:chain:")]
    finally:
        client.__exit__(None, None, None)
    read = [svid for batch in plan["batches"] for svid in batch]
    assert run["status"] == "completed" and len(read) == CHAIN_ABSTRACT_READ["quick"] and plan["not_read"] == 5
    assert len(model_keys) == 2 * -(-CHAIN_ABSTRACT_READ["quick"] // ABSTRACT_BATCH)
    chained_codes = [codes[f"W{700 + n}"] for n in range(len(many))]
    assert chained_codes.count("abstract_not_read") == 5
    assert chained_codes.count("runs_agree_candidate") == CHAIN_ABSTRACT_READ["quick"]


def test_the_keyword_ranking_read_plan_and_fetch_plan_are_unchanged_by_chaining(tmp_path, monkeypatch):
    def library(path, chaining):
        pool = keyword_pool() + [work(n, ON_TOPIC, ON_ABSTRACT + " Plot" * n) for n in range(10, 14)]
        transport = OpenAlex(pool, citing={"W1": [work(700), work(701)], "W10": [work(710)]},
                             by_id={"W900": work(900)})
        # The plan is the one the discovery run writes itself once its screening is done (slice 17a).
        app = app_for(path, monkeypatch, transport, chaining=chaining, fetch="auto", overlap=True)
        client = client_of(app)
        try:
            rid, run_id, view, run = discover(client)
            store = app.state.store
            fetch_run = run_id
            ranking_step = store.step(run_id, "ranking", "code:ranking")["id"]
            ranks = sorted((openalex_of(store, [row["source_version_id"]])[0], row["signal"], row["rank"],
                            row["available"]) for row in store.conn.execute(
                "SELECT * FROM record_signal_ranks WHERE ranking_step_id = ?", (ranking_step,)))
            batches = [openalex_of(store, batch) for batch in step_output(store, run_id, "abstract_stage")["batches"]]
            plan = step_output(store, fetch_run, "fulltext_plan")
            chained = set(step_output(store, run_id, "chain_filter")["chained"]) if chaining == "auto" else set()
            planned = openalex_of(store, plan["works"])
            groups = [head in chained for head in plan["works"]]
        finally:
            client.__exit__(None, None, None)
        return ranks, batches, planned, groups, plan

    on_ranks, on_batches, on_plan, on_groups, on = library(tmp_path / "on", "auto")
    off_ranks, off_batches, off_plan, off_groups, off = library(tmp_path / "off", "off")
    assert on_ranks == off_ranks and on_batches == off_batches
    keyword = [w for w, chained in zip(on_plan, on_groups) if not chained]
    assert keyword == off_plan and not any(off_groups)
    # The chained works come after every keyword work, in their own group.
    assert sorted(w for w, chained in zip(on_plan, on_groups) if chained) == ["W700", "W701", "W710", "W900"]
    assert on_groups == sorted(on_groups) and on["groups"]["chain"] == 4 and "chain" not in off["groups"]
    assert on["groups"] | {"chain": 0} == off["groups"] | {"chain": 0}


def test_the_expansion_revision_carries_the_same_chain_policy(tmp_path, monkeypatch):
    from test_expansion_flow import QUESTION as PACKET_QUESTION, DeadAdapter, Field

    app = app_for(tmp_path, monkeypatch, Field(), adapter=DeadAdapter())
    client = client_of(app)
    try:
        rid, run_id, view, run = discover(client, question=PACKET_QUESTION)
        bodies = [json.loads(row["body_json"]) for row in app.state.store.conn.execute(
            "SELECT body_json FROM protocol_records WHERE research_id = ? ORDER BY protocol_revision", (rid,))]
    finally:
        client.__exit__(None, None, None)
    assert len(bodies) == 2 and bodies[1]["arms"] == ["keyword_search", "data_expansion"]
    assert bodies[0]["citation_chaining"] == bodies[1]["citation_chaining"]
    assert bodies[0]["citation_chaining"]["enabled"] and bodies[0]["citation_chaining"]["abstract_read"] == 20
    assert bodies[0]["thresholds"]["chain"] == bodies[1]["thresholds"]["chain"] == {
        "seeds": 15, "citing_cap": 400, "backward_batch": 100, "request_limit": 40, "abstract_read": 20,
        "plan_room": 12}


# ---- resuming -----------------------------------------------------------------------------------

CHAINED = "SYNTHETIC irrigation scheduling of a chained crop"


def test_a_resumed_run_asks_openalex_nothing_again(tmp_path, monkeypatch):
    paused_once: list = []

    def pause_during_the_chain_read(si):
        chained = any(CHAINED in c["title"] for c in si.get("candidates") or [])
        if si["task_type"] == "abstract_screening" and chained and not paused_once:
            paused_once.append(si)
            store = app.state.store
            running = store.conn.execute("SELECT id FROM runs WHERE kind = 'discovery' AND status = 'running'").fetchone()
            store.update_run(running[0], status="pause_requested")
        return None

    transport = OpenAlex(keyword_pool(), citing={"W1": [work(700, CHAINED)], "W3": [work(703, CHAINED)]},
                         by_id={"W900": work(900, CHAINED)})
    app = app_for(tmp_path, monkeypatch, transport, adapter=FakeAdapter(responder(), fail=pause_during_the_chain_read))
    client = client_of(app)
    try:
        rid, run_id, view, paused = discover(client)
        store = app.state.store
        sent, links = list(transport.chain), chain_links(store, run_id)
        seeds = step_output(store, run_id, "chain_seeds")
        client.post(f"/api/runs/{run_id}/resume")
        view, run = wait(client, rid, run_id)
        codes = codes_of(store, rid)
        again = chain_links(store, run_id)
        seeds_after = step_output(store, run_id, "chain_seeds")
    finally:
        client.__exit__(None, None, None)
    assert (paused["status"], paused["pause_reason"]) == ("paused", "user_requested"), paused
    assert run["status"] == "completed" and transport.chain == sent and again == links
    assert seeds_after == seeds
    assert {codes["W700"], codes["W703"], codes["W900"]} == {"runs_agree_candidate"}


def test_chain_links_are_written_once_on_resume(tmp_path, monkeypatch):
    def pause_after_the_first(transport):
        if len(transport.chain) == 1:
            store = app.state.store
            running = store.conn.execute("SELECT id FROM runs WHERE kind = 'discovery' AND status = 'running'").fetchone()
            store.update_run(running[0], status="pause_requested")

    transport = OpenAlex(keyword_pool(), citing={"W1": [work(700)], "W2": [work(702)], "W3": [work(703)]},
                         by_id={"W900": work(900), "W901": work(901)}, on_chain=pause_after_the_first)
    app = app_for(tmp_path, monkeypatch, transport)
    client = client_of(app)
    try:
        rid, run_id, view, paused = discover(client)
        store = app.state.store
        first = chain_links(store, run_id)
        client.post(f"/api/runs/{run_id}/resume")
        view, run = wait(client, rid, run_id)
        links = chain_links(store, run_id)
        rows = store.conn.execute("SELECT COUNT(*) FROM chain_links WHERE run_id = ?", (run_id,)).fetchone()[0]
    finally:
        client.__exit__(None, None, None)
    assert (paused["status"], paused["pause_reason"]) == ("paused", "user_requested"), paused
    assert transport.chain[0][0] == "backward" and transport.chain.count(transport.chain[0]) == 1
    assert run["status"] == "completed" and first and all(row in links for row in first)
    assert rows == len(links) == len({(r["seed_source_version_id"], r["linked_openalex_id"], r["direction"])
                                      for r in links})
    assert {"W700", "W702", "W703", "W900", "W901"} <= {row["linked_openalex_id"] for row in links}


# ---- review findings (Sol high, 2026-09-24) ------------------------------------------------------

def test_a_failed_chain_read_is_recorded_and_the_run_goes_on(tmp_path, monkeypatch):
    def fail_the_chain_read(si):
        if si["task_type"] == "abstract_screening" and any(CHAINED in c["title"] for c in si.get("candidates") or []):
            return ModelStepResult("failed", error="SYNTHETIC model connection dropped")
        return None

    transport = OpenAlex(keyword_pool(), citing={"W1": [work(700, CHAINED)]})
    app = app_for(tmp_path, monkeypatch, transport, adapter=FakeAdapter(responder(), fail=fail_the_chain_read))
    client = client_of(app)
    try:
        rid, run_id, view, run = discover(client)
        store = app.state.store
        summary = step_output(store, run_id, "chain_summary")
        codes = codes_of(store, rid)
        failed = [s for s in store.run_steps(run_id) if s["operation_key"].startswith("abstract_screening:chain:")]
    finally:
        client.__exit__(None, None, None)
    # The chain never pauses the run: the failed read is recorded, the work stays unresolved and the run completes.
    assert run["status"] == "completed" and run["pause_reason"] is None, run
    assert failed and all(s["status"] == "failed" for s in failed)
    assert summary["new_works"] == 1 and codes["W700"] not in ("runs_agree_candidate", "runs_agree_out_of_scope")


def test_a_second_discovery_run_keeps_the_earlier_chained_works_out_of_the_keyword_path(tmp_path, monkeypatch):
    transport = OpenAlex(keyword_pool(), citing={"W1": [work(700, CHAINED)]})
    app = app_for(tmp_path, monkeypatch, transport)
    client = client_of(app)
    try:
        rid, first, view, run = discover(client)
        store = app.state.store
        chained = records_of(store, rid)["W700"]
        second = client.post(f"/api/researches/{rid}/runs", json={"kind": "discovery"}).json()["id"]
        view, run = wait(client, rid, second)
        ranked = {row[0] for row in store.conn.execute(
            "SELECT source_version_id FROM record_signal_ranks WHERE ranking_step_id = ?",
            (store.step(second, "ranking", "code:ranking")["id"],))}
        keyword_read = {svid for batch in step_output(store, second, "abstract_stage")["batches"] for svid in batch}
        chained_again = step_output(store, second, "chain_filter")["chained"]
    finally:
        client.__exit__(None, None, None)
    assert run["status"] == "completed", run
    # The first run's chained work is not a keyword record of the second run; the second chain finds it again.
    assert chained not in ranked and chained not in keyword_read and chained in chained_again


def test_the_request_limit_holds_through_rate_limit_retries(tmp_path, monkeypatch):
    monkeypatch.setattr("deixis.api.app.CHAIN_REQUEST_LIMIT", 3)
    transport = OpenAlex(keyword_pool(), limited_cites={f"W{n}" for n in range(1, 6)})
    app = app_for(tmp_path, monkeypatch, transport)
    client = client_of(app)
    try:
        # `detailed` retries a rate-limited request inside the provider call; `quick` does not.
        rid, run_id, view, run = discover(client, effort="detailed")
    finally:
        client.__exit__(None, None, None)
    forward = [entry for entry in transport.chain if entry[0] == "forward"]
    assert run["status"] == "completed" and run["pause_reason"] is None
    assert len(transport.chain) <= 3 and run["usage"]["chain_requests"] <= 3 and forward


def test_a_backward_id_openalex_does_not_return_is_counted_unresolved(tmp_path, monkeypatch):
    transport = OpenAlex(keyword_pool(), by_id={"W900": work(900), "W902": work(902)})
    app = app_for(tmp_path, monkeypatch, transport)
    client = client_of(app)
    try:
        rid, run_id, view, run = discover(client)
        store = app.state.store
        batch = step_output(store, run_id, "chain:backward:0")
        summary = step_output(store, run_id, "chain_summary")
    finally:
        client.__exit__(None, None, None)
    assert batch["unresolved"] == ["W901"] and summary["unresolved_links"] == 1


def test_the_last_citing_page_asks_only_for_what_the_cap_leaves(tmp_path, monkeypatch):
    monkeypatch.setattr("deixis.workflow.flow.CHAIN_CITING_CAP", 3)
    monkeypatch.setattr("deixis.workflow.flow.CHAIN_CITING_PAGE", 2)
    transport = OpenAlex(keyword_pool(), citing={"W1": [work(700 + n) for n in range(5)]})
    app = app_for(tmp_path, monkeypatch, transport)
    client = client_of(app)
    try:
        rid, run_id, view, run = discover(client)
        records = records_of(app.state.store, rid)
    finally:
        client.__exit__(None, None, None)
    w1 = [entry for entry in transport.chain if entry[:2] == ("forward", "W1")]
    assert len(w1) == 2 and transport.pages[:2] == [2, 1]
    assert {"W700", "W701", "W702"} <= set(records) and not {"W703", "W704"} & set(records)


def test_a_queued_run_keeps_the_chain_read_and_room_it_was_queued_with(tmp_path, monkeypatch):
    many = [work(700 + n, abstract=f"{IRRIGATION_ABSTRACT} Plot {n}.") for n in range(6)]
    transport = OpenAlex(keyword_pool(), citing={"W1": many})
    app = app_for(tmp_path, monkeypatch, transport, fetch="auto")
    client = client_of(app)
    try:
        payload = {"question": QUESTION, "model_connection": "fake", "requested_model": "fake-model", "effort": "quick"}
        rid = client.post("/api/researches", json=payload).json()["research"]["id"]
        run_id = client.post(f"/api/researches/{rid}/runs", json={"kind": "discovery"}).json()["id"]
        store = app.state.store
        frozen = store.run(run_id)["budget"]
        view, run = wait(client, rid, run_id)
        body = store.current_protocol(rid, 1)["body"]
    finally:
        client.__exit__(None, None, None)
    assert frozen["chain_abstract_read"] == CHAIN_ABSTRACT_READ["quick"] and "chain_plan_room" in frozen
    assert body["thresholds"]["chain"]["abstract_read"] == frozen["chain_abstract_read"]
    assert body["thresholds"]["chain"]["plan_room"] == frozen["chain_plan_room"]
    # The fetch runs inside the discovery run (slice 17a) and reads the room frozen with it.
    assert frozen["fulltext_fetch"]["chain_room"] == frozen["chain_plan_room"]


# ---- fix check findings (Sol high, 2026-09-24) ---------------------------------------------------

def test_a_failed_chain_read_is_not_sent_again_on_resume(tmp_path, monkeypatch):
    sent: list[int] = []

    def fail_the_chain_read_then_pause(si):
        if si["task_type"] == "abstract_screening" and any(CHAINED in c["title"] for c in si.get("candidates") or []):
            sent.append(si["screening_target"]["run"])
            store = app.state.store
            running = store.conn.execute("SELECT id FROM runs WHERE kind = 'discovery' AND status = 'running'").fetchone()
            if running:
                store.update_run(running[0], status="pause_requested")
            return ModelStepResult("failed", error="SYNTHETIC model connection dropped")
        return None

    transport = OpenAlex(keyword_pool(), citing={"W1": [work(700, CHAINED)]})
    app = app_for(tmp_path, monkeypatch, transport, adapter=FakeAdapter(responder(), fail=fail_the_chain_read_then_pause))
    client = client_of(app)
    try:
        rid, run_id, view, paused = discover(client)
        before = list(sent)
        client.post(f"/api/runs/{run_id}/resume")
        view, run = wait(client, rid, run_id)
        store = app.state.store
        failed = [s for s in store.run_steps(run_id) if s["operation_key"].startswith("abstract_screening:chain:")]
    finally:
        client.__exit__(None, None, None)
    assert (paused["status"], paused["pause_reason"]) == ("paused", "user_requested"), paused
    # Both runs of the chain batch were sent and failed once; the resumed run reads them as answered.
    assert sorted(before) == [1, 2] and sent == before, sent
    assert run["status"] == "completed" and all(s["status"] == "failed" for s in failed)


def test_a_chain_read_the_connection_was_not_ready_for_is_not_sent_on_resume(tmp_path, monkeypatch):
    class NotReadyForTheChainRead(FakeAdapter):
        """Ready until the chain's requests have gone out; then not ready once per call, with a user pause."""
        armed = False

        async def health(self, refresh=False):
            if self.armed:
                store = app.state.store
                running = store.conn.execute(
                    "SELECT id FROM runs WHERE kind = 'discovery' AND status = 'running'").fetchone()
                if running:
                    store.update_run(running[0], status="pause_requested")
                return {"connection": "fake", "ready": False, "reason": "SYNTHETIC not ready"}
            return await super().health(refresh)

    adapter = NotReadyForTheChainRead(responder())

    def arm(transport):
        adapter.armed = True

    transport = OpenAlex(keyword_pool(), citing={"W1": [work(700, CHAINED)]}, on_chain=arm)
    app = app_for(tmp_path, monkeypatch, transport, adapter=adapter)
    client = client_of(app)
    try:
        rid, run_id, view, paused = discover(client)
        adapter.armed, transport.on_chain = False, None
        client.post(f"/api/runs/{run_id}/resume")
        view, run = wait(client, rid, run_id)
        store = app.state.store
        chain_steps = [s for s in store.run_steps(run_id) if s["operation_key"].startswith("abstract_screening:chain:")]
        chain_calls = [si for si in adapter.calls if any(CHAINED in c["title"] for c in si.get("candidates") or [])]
    finally:
        client.__exit__(None, None, None)
    assert (paused["status"], paused["pause_reason"]) == ("paused", "user_requested"), paused
    assert run["status"] == "completed" and not chain_calls
    assert chain_steps and all((s["status"], s["error_code"]) == ("failed", "model_connection_not_ready")
                               for s in chain_steps), chain_steps


def test_a_keyword_work_of_a_research_older_than_its_hits_is_not_chain_only(tmp_path, monkeypatch):
    # W3 is a keyword work that cites W1, so the chain adds a hit to it. A research older than D93 has no keyword
    # hits in `candidate_hits`; deleting them imitates one. W3's candidate row still names its keyword search.
    pool = keyword_pool()
    transport = OpenAlex(pool, citing={"W1": [pool[2], work(700, CHAINED)]})
    app = app_for(tmp_path, monkeypatch, transport)
    client = client_of(app)
    try:
        rid, run_id, view, run = discover(client)
        store = app.state.store
        records = records_of(store, rid)
        store.conn.execute("DELETE FROM candidate_hits WHERE search_run_id IN"
                           " (SELECT id FROM search_runs WHERE query_text NOT LIKE 'chain:%')")
        store.conn.commit()
        chain_only = store.chain_only_works(rid, 1)
        work_of = store.work_ids([records["W3"], records["W700"]])
    finally:
        client.__exit__(None, None, None)
    assert run["status"] == "completed", run
    assert work_of[records["W700"]] in chain_only and work_of[records["W3"]] not in chain_only


def test_a_chained_work_a_later_keyword_search_finds_leaves_the_chain_group(tmp_path, monkeypatch):
    chained_work = work(700, CHAINED)
    transport = OpenAlex(keyword_pool(), citing={"W1": [chained_work]})
    app = app_for(tmp_path, monkeypatch, transport)
    client = client_of(app)
    try:
        rid, first, view, run = discover(client)
        flow = app.state.worker.flow
        w700 = records_of(app.state.store, rid)["W700"]
        assert w700 in flow._chain_state(rid, 1)[0]
        # The second run does not chain (the setting changed) and its keyword search returns W700.
        object.__setattr__(flow.deps.settings, "citation_chaining", "off")
        transport.works = keyword_pool() + [chained_work]
        second = client.post(f"/api/researches/{rid}/runs", json={"kind": "discovery"}).json()["id"]
        view, run = wait(client, rid, second)
        chained, order, chain_order = flow._chain_state(rid, 1)
        grouped = {w["head"]: w.get("chained") for w in flow._fulltext_works(rid, chained)}
    finally:
        client.__exit__(None, None, None)
    assert run["status"] == "completed", run
    assert w700 not in chained and grouped.get(w700) is not True
