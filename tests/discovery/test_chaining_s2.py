"""Semantic Scholar as the second citation-chain source, inside a real `sw` discovery run (D229).

Workflow behavior only: the Semantic Scholar API is mocked (SYNTHETIC records), as is OpenAlex, and the model is
scripted. Passing shows the arm is bounded, resumable and counted; it does not show that Semantic Scholar's links add
relevant works, which is not measured.
"""

import asyncio
import json

import httpx

from deixis.workflow import chaining
from test_abstract_flow import QUESTION, client_of, step_output, wait
from test_chaining_flow import (IRRIGATION, IRRIGATION_ABSTRACT, OFF_ABSTRACT, OFF_TOPIC, OpenAlex, app_for, discover,
                                keyword_pool, work)


def paper(number, title=IRRIGATION, abstract=IRRIGATION_ABSTRACT, doi=None):
    return {"paperId": f"s2p{number}", "externalIds": {"DOI": doi or f"10.2/s2.{number}"},
            "title": f"{title} {number}", "abstract": abstract, "year": 2024, "venue": "SYNTHETIC",
            "publicationTypes": ["JournalArticle"], "authors": [{"name": "A. Author"}],
            "url": f"https://www.semanticscholar.org/paper/s2p{number}"}


class Both:
    """OpenAlex (the existing mock) and a Semantic Scholar mock that answers /references and /citations by DOI."""

    def __init__(self, openalex, references=None, citations=None, status=None, unknown=()):
        self.openalex, self.references, self.citations = openalex, references or {}, citations or {}
        self.status, self.unknown = status, set(unknown)
        self.s2: list[tuple[str, str, str, str]] = []  # (kind, doi, limit, offset) of every chain request

    def __call__(self, request):
        if request.url.host == "api.openalex.org":
            return self.openalex(request)
        if request.url.host != "api.semanticscholar.org":
            return httpx.Response(404)
        path = request.url.path
        if path.endswith("/search/bulk") or path.endswith("/search"):
            return httpx.Response(200, json={"total": 0, "data": []})
        doi, _, kind = path.removeprefix("/graph/v1/paper/DOI:").rpartition("/")
        params = request.url.params
        self.s2.append((kind, doi, params["limit"], params["offset"]))
        if self.status:
            return httpx.Response(self.status, headers={"Retry-After": "0"}, text="SYNTHETIC rate limit")
        if doi in self.unknown:
            return httpx.Response(404, json={"error": "Paper not found"})
        items = (self.references if kind == "references" else self.citations).get(doi, [])
        field = "citedPaper" if kind == "references" else "citingPaper"
        return httpx.Response(200, json={"offset": 0, "data": [{field: item} for item in items]})


def s2_steps(store, run_id):
    return [s for s in store.run_steps(run_id) if s["kind"] == chaining.STEP_KIND_S2]


class Done:
    """What a finished run left, read before the app closes its database."""

    def __init__(self, app, rid, run_id, view, run):
        store = app.state.store
        self.app, self.rid, self.run_id, self.view, self.run = app, rid, run_id, view, run
        self.summary = step_output(store, run_id, "chain_summary")
        self.steps = s2_steps(store, run_id)
        self.filtered = step_output(store, run_id, "chain_filter")
        self.body = store.current_protocol(rid, 1)["body"]["citation_chaining"]
        self.link_rows = store.conn.execute("SELECT COUNT(*) FROM chain_links WHERE run_id = ? AND direction = 'forward'",
                                            (run_id,)).fetchone()[0]
        self.doi_700 = store.conn.execute("SELECT COUNT(*) FROM source_versions WHERE doi = '10.1/oa.700'").fetchone()[0]


def run_once(tmp_path, monkeypatch, transport, limit=None):
    if limit:
        monkeypatch.setattr("deixis.api.app.CHAIN_REQUEST_LIMIT", limit)
    app = app_for(tmp_path, monkeypatch, transport)
    client = client_of(app)
    try:
        rid, run_id, view, run = discover(client)
        return Done(app, rid, run_id, view, run)
    finally:
        client.__exit__(None, None, None)


def test_s2_backward_and_forward_are_steps_and_search_rows(tmp_path, monkeypatch):
    oa = OpenAlex(keyword_pool())
    transport = Both(oa, references={"10.1/oa.1": [paper(1), paper(2, OFF_TOPIC, OFF_ABSTRACT), {"paperId": None, "title": "x"}]},
                     citations={"10.1/oa.2": [paper(3)]})
    d = run_once(tmp_path, monkeypatch, transport)
    assert d.run["status"] == "completed", d.run
    assert len(d.steps) == 10 and all(s["operation_key"].startswith("chain:s2:") for s in d.steps)
    assert {s["status"] for s in d.steps} == {"succeeded"}
    rows = [r for r in d.view["search_runs"] if r["provider"] == "semantic_scholar" and r["query_text"].startswith("chain:")]
    assert len(rows) == 10
    # Each seed is asked both ways, one request each, with the limit and offset the API names.
    assert len(transport.s2) == 10
    assert sorted({(kind, limit, offset) for kind, _, limit, offset in transport.s2}) == [
        ("citations", "400", "0"), ("references", "1000", "0")]
    titles = {s["title"] for s in d.view["sources"]}
    assert f"{IRRIGATION} 1" in titles and f"{IRRIGATION} 3" in titles and f"{OFF_TOPIC} 2" not in titles
    assert d.summary["semantic_scholar"]["requests"] == {"backward": 5, "forward": 5, "failed": 0, "rate_limited": 0}
    assert d.summary["semantic_scholar"]["seeds_without_doi"] == 0
    assert d.summary["requests"]["sent"] == len(oa.chain) + 10
    assert d.run["budget"]["chain_sources"] == ["openalex", "semantic_scholar"]
    assert d.body["sources"] == ["openalex", "semantic_scholar"] and d.body["rule_version"] == "deixis.citation_chaining.v2"


def test_a_link_both_sources_found_is_counted_once(tmp_path, monkeypatch):
    # OpenAlex says W1 is cited by W700; Semantic Scholar says the same paper (same DOI) cites it too, and one more.
    oa = OpenAlex(keyword_pool(), citing={"W1": [work(700)]})
    transport = Both(oa, citations={"10.1/oa.1": [paper(9, doi="10.1/oa.700"), paper(10)]})
    d = run_once(tmp_path, monkeypatch, transport)
    assert d.run["status"] == "completed", d.run
    assert d.filtered["links"]["forward"] == 2  # W700 (found by both) and s2p10
    assert d.filtered["linked_works"] == 2 and d.filtered["new_works"] == 2
    # The table keeps one row per source and link; the counts are by work, and the two records are one.
    assert d.link_rows == 3 and d.doi_700 == 1


def test_s2_shares_the_request_limit_and_gets_what_openalex_leaves(tmp_path, monkeypatch):
    oa = OpenAlex(keyword_pool(), by_id={"W900": work(900)})
    transport = Both(oa)
    d = run_once(tmp_path, monkeypatch, transport, limit=8)
    # OpenAlex: five citing requests and one reference batch = 6; Semantic Scholar gets the 2 left.
    assert len(oa.chain) == 6 and len(transport.s2) == 2
    assert d.run["usage"]["chain_requests"] == 8 and d.run["budget"]["max_chain_requests"] == 8
    assert d.summary["requests"]["sent"] == 8 and d.summary["semantic_scholar"]["not_reached_seeds"] == 3


def test_a_resumed_run_sends_no_semantic_scholar_request_twice(tmp_path, monkeypatch):
    oa = OpenAlex(keyword_pool())
    transport = Both(oa, references={"10.1/oa.1": [paper(1)]}, citations={"10.1/oa.2": [paper(3)]})
    app = app_for(tmp_path, monkeypatch, transport)
    client = client_of(app)
    try:
        rid, run_id, view, run = discover(client)
        store, flow = app.state.store, app.state.worker.flow
        sent, stored = len(transport.s2), {s["operation_key"]: s["output"] for s in s2_steps(store, run_id)}
        run_row = store.run(run_id)
        scope = store.scope(rid, run_row["scope_revision"])
        # The arm runs again over the stored steps, as a resumed run does: every succeeded step returns its output.
        asyncio.run(flow._chain_requests_s2(run_row, scope, {}))
        again = {s["operation_key"]: s["output"] for s in s2_steps(store, run_id)}
    finally:
        client.__exit__(None, None, None)
    assert sent == 10 and len(transport.s2) == sent and again == stored


def test_a_seed_without_a_doi_is_skipped_and_counted(tmp_path, monkeypatch):
    pool = keyword_pool()
    pool[0]["doi"] = None  # W1 has no DOI
    transport = Both(OpenAlex(pool))
    d = run_once(tmp_path, monkeypatch, transport)
    assert d.run["status"] == "completed", d.run
    assert d.summary["semantic_scholar"]["seeds_without_doi"] == 1 and d.summary["semantic_scholar"]["seeds_with_doi"] == 4
    assert len(transport.s2) == 8 and not [d for _, d, _, _ in transport.s2 if d.endswith("oa.1")]


def test_a_rate_limited_answer_ends_the_s2_arm_not_the_run(tmp_path, monkeypatch):
    transport = Both(OpenAlex(keyword_pool()), status=429)
    d = run_once(tmp_path, monkeypatch, transport)
    assert d.run["status"] == "completed" and d.run["pause_reason"] is None, d.run
    assert len(d.steps) == 1 and d.steps[0]["status"] == "failed" and d.steps[0]["error_code"] == "rate_limited"
    assert d.summary["semantic_scholar"]["requests"]["rate_limited"] == 1 and d.summary["requests"]["failed"] == 1
    assert d.summary["semantic_scholar"]["not_reached_seeds"] == 4
    # The provider's own retries were spent from the chain's limit, never beyond it.
    assert d.run["usage"]["chain_requests"] <= d.run["budget"]["max_chain_requests"]


def test_an_unknown_paper_is_an_empty_answer_not_a_failure(tmp_path, monkeypatch):
    transport = Both(OpenAlex(keyword_pool()), unknown=[f"10.1/oa.{n}" for n in range(1, 6)])
    d = run_once(tmp_path, monkeypatch, transport)
    assert {s["status"] for s in d.steps} == {"succeeded"} and d.summary["semantic_scholar"]["requests"]["failed"] == 0


def test_s2_out_of_the_research_sources_is_skipped_with_its_reason(tmp_path, monkeypatch):
    transport = Both(OpenAlex(keyword_pool()))
    app = app_for(tmp_path, monkeypatch, transport)
    client = client_of(app)
    try:
        payload = {"question": QUESTION, "model_connection": "fake", "requested_model": "fake-model", "effort": "quick"}
        rid = client.post("/api/researches", json=payload).json()["research"]["id"]
        store = app.state.store
        store.conn.execute("UPDATE scope_revisions SET providers_json = ? WHERE research_id = ?",
                           (json.dumps(["openalex"]), rid))
        store.conn.commit()
        run_id = client.post(f"/api/researches/{rid}/runs", json={"kind": "discovery"}).json()["id"]
        view, run = wait(client, rid, run_id)
        summary = step_output(store, run_id, "chain_summary")
        plan = step_output(store, run_id, "chain_s2_plan")
    finally:
        client.__exit__(None, None, None)
    assert run["status"] == "completed", run
    assert plan["status"] == "skipped" and plan["reason"] == "not_in_scope" and transport.s2 == []
    assert summary["semantic_scholar"]["status"] == "skipped"


# ---- the provider call and the policy block, without a run -----------------------------------

def test_chain_page_maps_papers_and_names_the_next_offset():
    from deixis.providers import semantic_scholar

    seen = []

    def handler(request):
        seen.append(request)
        return httpx.Response(200, json={"offset": 0, "next": 2, "data": [
            {"citingPaper": paper(1)}, {"citingPaper": {"paperId": None}}, {"citingPaper": None}]})

    async def go():
        async with httpx.AsyncClient(transport=httpx.MockTransport(handler)) as http:
            return await semantic_scholar.chain_page(http, "10.1/x", "forward", 5000, 0, api_key="SYNTHETIC-KEY")

    outcome = asyncio.run(go())
    request = seen[0]
    assert request.url.path == "/graph/v1/paper/DOI:10.1/x/citations" and request.headers["x-api-key"] == "SYNTHETIC-KEY"
    assert request.url.params["limit"] == "1000" and request.url.params["offset"] == "0"
    assert request.url.params["fields"] == semantic_scholar.FIELDS
    assert [r.provider_record_id for r in outcome.records] == ["s2p1"] and outcome.next_cursor == "2"
    assert outcome.status == "completed" and outcome.access_mode == "api_key"


def test_the_policy_block_names_its_sources_only_when_the_budget_froze_them():
    old = {"citation_chaining": "auto", "max_chain_requests": 40}
    new = old | {"chain_rule_version": chaining.RULE_VERSION, "chain_sources": list(chaining.SOURCES)}
    assert "sources" not in chaining.policy(old, "quick") and not chaining.s2_planned(old)
    assert chaining.policy(old, "quick")["rule_version"] == chaining.RULE_VERSION_V1
    assert chaining.policy(new, "quick")["sources"] == ["openalex", "semantic_scholar"] and chaining.s2_planned(new)
    assert not chaining.s2_planned({"citation_chaining": "off", "chain_sources": ["semantic_scholar"]})


# ---- review fixes: resume after a rate limit, the 400 cap, DOI path data, links by work -------

def test_a_resumed_run_keeps_the_s2_rate_limit_stop(tmp_path, monkeypatch):
    transport = Both(OpenAlex(keyword_pool()), status=429)
    app = app_for(tmp_path, monkeypatch, transport)
    client = client_of(app)
    try:
        rid, run_id, view, run = discover(client)
        store, flow = app.state.store, app.state.worker.flow
        sent = len(transport.s2)
        run_row = store.run(run_id)
        asyncio.run(flow._chain_requests_s2(run_row, store.scope(rid, run_row["scope_revision"]), {}))
        steps = s2_steps(store, run_id)
    finally:
        client.__exit__(None, None, None)
    assert sent >= 1 and len(transport.s2) == sent and len(steps) == 1


class Windowed(Both):
    """Every /citations answer consumes 150 raw items, none of them a usable paper, and names the next offset."""

    def __call__(self, request):
        if request.url.host == "api.semanticscholar.org" and request.url.path.endswith("/citations"):
            offset = int(request.url.params["offset"])
            self.s2.append(("citations", request.url.path, request.url.params["limit"], str(offset)))
            return httpx.Response(200, json={"offset": offset, "next": offset + 150,
                                             "data": [{"citingPaper": None}, {"citingPaper": {"paperId": None}}]})
        return super().__call__(request)


def test_forward_is_one_request_per_seed_even_when_a_next_offset_is_named(tmp_path, monkeypatch):
    transport = Windowed(OpenAlex(keyword_pool()))
    d = run_once(tmp_path, monkeypatch, transport)
    assert d.run["status"] == "completed", d.run
    asked = [(int(offset), int(limit)) for kind, _, limit, offset in transport.s2 if kind == "citations"]
    assert asked == [(0, 400)] * 5, asked
    assert len(transport.s2) == 10


def _chain_answer(payload, direction="forward", offset=0, doi="10.1/x"):
    from deixis.providers import semantic_scholar

    def handler(request):
        return httpx.Response(200, json=payload)

    async def go():
        async with httpx.AsyncClient(transport=httpx.MockTransport(handler)) as http:
            return await semantic_scholar.chain_page(http, doi, direction, 400, offset)

    return asyncio.run(go())


def test_a_malformed_next_offset_is_a_parse_error_not_a_crash():
    outcome = _chain_answer({"next": "bogus", "data": [{"citingPaper": paper(1)}]})
    assert outcome.status == "parse_error" and outcome.next_cursor is None and outcome.records == []


def test_a_non_integer_numeric_next_offset_is_a_parse_error():
    from deixis.providers import semantic_scholar

    for value in (150.5, True, "1e3"):
        assert _chain_answer({"next": value, "data": [{"citingPaper": paper(1)}]}).status == "parse_error", value

    async def overflow():  # 1e309 is not valid JSON to write, so the body is sent as text
        transport = httpx.MockTransport(lambda request: httpx.Response(200, content=b'{"next": 1e309, "data": []}'))
        async with httpx.AsyncClient(transport=transport) as http:
            return await semantic_scholar.chain_page(http, "10.1/x", "forward", 400, 0)

    assert asyncio.run(overflow()).status == "parse_error"
    assert _chain_answer({"next": "150", "data": [{"citingPaper": paper(1)}]}).next_cursor == "150"


def test_a_truncated_backward_page_states_no_total():
    truncated = _chain_answer({"next": 1000, "data": [{"citedPaper": paper(1)}]}, direction="backward")
    assert truncated.next_cursor is None and truncated.provider_total is None
    whole = _chain_answer({"data": [{"citedPaper": paper(1)}, {"citedPaper": paper(2)}]}, direction="backward")
    assert whole.provider_total == 2


def test_a_repeated_or_falling_next_offset_ends_paging():
    assert _chain_answer({"next": 100, "data": [{"citingPaper": paper(1)}]}, offset=100).next_cursor is None
    assert _chain_answer({"next": 50, "data": [{"citingPaper": paper(1)}]}, offset=100).next_cursor is None
    assert _chain_answer({"next": 150, "data": [{"citingPaper": paper(1)}]}, offset=100).next_cursor == "150"


def test_backward_never_reads_next():
    outcome = _chain_answer({"next": "bogus", "data": [{"citedPaper": paper(1)}]}, direction="backward")
    assert outcome.status == "completed" and outcome.next_cursor is None and len(outcome.records) == 1


def test_a_doi_with_dot_segments_keeps_its_identity_on_the_wire():
    from deixis.providers import semantic_scholar

    seen = []

    def handler(request):
        seen.append(request)
        return httpx.Response(200, json={"data": []})

    async def go():
        async with httpx.AsyncClient(transport=httpx.MockTransport(handler)) as http:
            return await semantic_scholar.chain_page(http, "10.1234/a/../b", "forward", 10)

    asyncio.run(go())
    assert seen[0].url.raw_path.split(b"?")[0] == b"/graph/v1/paper/DOI:10.1234%2Fa%2F..%2Fb/citations"


def test_a_doi_with_reserved_characters_is_encoded_as_path_data():
    from deixis.providers import semantic_scholar

    seen = []

    def handler(request):
        seen.append(request)
        return httpx.Response(200, json={"data": []})

    async def go():
        async with httpx.AsyncClient(transport=httpx.MockTransport(handler)) as http:
            return await semantic_scholar.chain_page(http, "10.1/a?b#c%d e", "backward", 10)

    asyncio.run(go())
    request = seen[0]
    assert request.url.raw_path.split(b"?")[0] == b"/graph/v1/paper/DOI:10.1%2Fa%3Fb%23c%25d%20e/references"
    assert request.url.fragment == "" and request.url.params["limit"] == "10"


def test_a_preprint_and_its_published_version_are_one_linked_work(tmp_path, monkeypatch):
    # OpenAlex lists the arXiv preprint as citing W1; Semantic Scholar lists the published version (another DOI).
    pre = work(700, doi="10.48550/arxiv.700", authors=["A. Author"])
    oa = OpenAlex(keyword_pool(), citing={"W1": [pre]})
    transport = Both(oa, citations={"10.1/oa.1": [paper(700, doi="10.2/pub.700")]})
    d = run_once(tmp_path, monkeypatch, transport)
    assert d.run["status"] == "completed", d.run
    assert d.link_rows == 2
    assert d.filtered["links"]["forward"] == 1
    assert d.filtered["linked_works"] == 1 and d.filtered["passed_filter"] == 1
