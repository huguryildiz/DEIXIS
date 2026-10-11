"""seed_pdf_v1 (D2): the seed PDF finds its OpenAlex work and guides the query, the chain and the ranking. SYNTHETIC."""

import asyncio
import json

import httpx

from deixis.workflow import fast_search, ranking, seed_match
from helpers import make_pdf
from test_abstract_flow import QUESTION, ON_TOPIC
from test_fetch_overlap_flow import output, wait
from test_fulltext_flow import Transport, work
from test_small_batch_flow import app_for, client_of

SEED_TITLE = "SYNTHETIC deficit irrigation scheduling for greenhouse tomato yield"
SEED_DOI = "10.1/seed.900"
OTHER_DOI = "10.1/cited.901"
OTHER_TITLE = "SYNTHETIC a cited study of soil moisture sensors in open fields"


def seed_work(number=900, title=SEED_TITLE, doi=SEED_DOI, references=("W5", "W6")):
    return work(number, doi=doi, title=title) | {
        "display_name": title, "referenced_works": [f"https://openalex.org/{r}" for r in references]}


class SeedTransport(Transport):
    """The fulltext flow's OpenAlex, which also answers a DOI filter and a meaning search with scripted works."""

    def __init__(self, works, by_doi=(), semantic=None):
        super().__init__(works)
        self.by_doi, self.semantic = list(by_doi), semantic
        self.doi_requests, self.semantic_queries = [], []

    def __call__(self, request):
        params = request.url.params
        if request.url.host == "api.openalex.org" and params.get("filter", "").startswith("doi:"):
            asked = params["filter"].removeprefix("doi:").split("|")
            self.doi_requests.append(asked)
            found = [w for w in self.by_doi if w["doi"].removeprefix("https://doi.org/") in asked]
            return httpx.Response(200, json={"meta": {"count": len(found)}, "results": found})
        if request.url.host == "api.openalex.org" and "search.semantic" in params:
            self.semantic_queries.append(params["search.semantic"])
            if self.semantic is not None:
                return httpx.Response(200, json={"meta": {"count": len(self.semantic)}, "results": self.semantic})
        return super().__call__(request)


def records(n=30):
    return [work(i, title=ON_TOPIC) for i in range(n)]


def seeded(client, pdf, effort="quick"):
    rid = client.post("/api/researches", json={
        "question": QUESTION, "model_connection": "fake", "requested_model": "fake-model", "effort": effort,
        "source_scope": "attached_and_academic", "seed_mode": "uploaded_seed"}).json()["research"]["id"]
    uploaded = client.post(f"/api/researches/{rid}/uploads", files={"file": ("seed.pdf", pdf, "application/pdf")}).json()
    selected = client.post(f"/api/researches/{rid}/seed", json={
        "source_version_id": uploaded["uploaded_source_version_id"], "expected_version": uploaded["research"]["version"]})
    assert selected.status_code == 200, selected.text
    return rid, uploaded["uploaded_source_version_id"]


def discovery(client, rid):
    run_id = client.post(f"/api/researches/{rid}/runs", json={"kind": "discovery"}).json()["id"]
    view, run = wait(client, rid, run_id)
    assert run["status"] == "completed", run
    return run_id, view


def protocol_body(store, run_id):
    revision = output(store, run_id, "protocol")["protocol_revision"]
    row = store.conn.execute("SELECT body_json FROM protocol_records WHERE protocol_revision = ?", (revision,)).fetchone()
    return json.loads(row[0])


SEED_PDF = make_pdf([f"{SEED_TITLE}\nA. Author\ndoi:{SEED_DOI}\nAbstract. Deficit irrigation scheduling raises "
                     f"marketable tomato yield in greenhouses.", "Introduction. Irrigation scheduling ..."])


def test_matched_seed_guides_query_chain_ranking_and_protocol(tmp_path, monkeypatch):
    transport = SeedTransport(records(), by_doi=[seed_work()])
    app, _ = app_for(tmp_path, monkeypatch, transport=transport, search_query="model")
    with client_of(app) as client:
        rid, svid = seeded(client, SEED_PDF)
        assert client.get(f"/api/researches/{rid}").json()["scope"]["seed_use"] == {"status": "selected"}
        run_id, view = discovery(client, rid)
        store = app.state.store
        assert view["scope"]["seed_use"] == {"status": "matched", "basis": "doi_title", "title": SEED_TITLE,
                                             "doi": SEED_DOI, "openalex_id": "W900"}
        match = output(store, run_id, "seed_match")
        assert (match["status"], match["basis"], match["openalex_id"]) == ("matched", "doi_title", "W900")
        assert match["referenced_works"] == ["W5", "W6"] and match["source_version_id"] == svid
        assert transport.doi_requests == [[SEED_DOI]] and not output(store, run_id, "seed_match:semantic")
        body = protocol_body(store, run_id)
        assert body["seed_match"] == match
        plan = body["fast_path_search"]["semantic"]
        assert plan["query_text"].startswith(QUESTION) and SEED_TITLE in plan["query_text"]
        assert plan["seed_text"] == "match_abstract" and len(plan["query_text"]) <= 2000
        seeds = output(store, run_id, "fast_chain:seeds")["seeds"]
        assert seeds[0]["origin"] == "seed_pdf" and seeds[0]["openalex_id"] == "W900" and seeds[0]["rank"] == 0
        assert len({s["openalex_id"] for s in seeds}) == len(seeds)
        query = output(store, run_id, "search_query")
        assert query["seed_passages_sha256"] == match["seed_passages_sha256"]
        step = store.conn.execute("SELECT output_json FROM run_steps WHERE run_id = ? AND operation_key = 'search_query:1'",
                                  (run_id,)).fetchone()
        given = store.step_input_payload(json.loads(step[0])["step_input_id"])
        assert [p["source_id"] for p in given["passages"]] and {p["source_id"] for p in given["passages"]} == {svid}
        assert [s["source_id"] for s in given["sources"]] == [svid]


def test_second_run_reuses_the_match_and_a_frozen_run_never_opens_it(tmp_path, monkeypatch):
    transport = SeedTransport(records(), by_doi=[seed_work()])
    app, _ = app_for(tmp_path, monkeypatch, transport=transport)
    with client_of(app) as client:
        rid, _ = seeded(client, SEED_PDF)
        first, _ = discovery(client, rid)
        second, _ = discovery(client, rid)
        store = app.state.store
        assert output(store, second, "seed_match")["reused_from_run"] == first
        assert len(transport.doi_requests) == 1
        # A run whose protocol froze before seed_pdf_v1 finishes the way it began: no seed step, no seed context.
        flow = app.state.worker.flow
        store.conn.execute("DELETE FROM run_steps WHERE run_id = ? AND operation_key LIKE 'seed_match%'", (first,))
        store.conn.commit()
        run, scope = store.run(first), store.scope(rid)
        assert asyncio.run(flow._seed_match(run, scope)) is None
        assert store.existing_step(first, "seed_match") is None


def test_unseeded_discovery_has_no_seed_step_and_an_unchanged_plan(tmp_path, monkeypatch):
    transport = SeedTransport(records())
    app, _ = app_for(tmp_path, monkeypatch, transport=transport)
    with client_of(app) as client:
        rid = client.post("/api/researches", json={"question": QUESTION, "model_connection": "fake",
                                                   "requested_model": "fake-model", "effort": "quick"}).json()["research"]["id"]
        run_id, _ = discovery(client, rid)
        store = app.state.store
        assert output(store, run_id, "seed_match") is None and not transport.doi_requests
        body = protocol_body(store, run_id)
        assert "seed_match" not in body
        assert body["fast_path_search"]["semantic"]["query_text"] == QUESTION
        assert "seed_text" not in body["fast_path_search"]["semantic"]
        assert all(s["origin"] != "seed_pdf" for s in output(store, run_id, "fast_chain:seeds")["seeds"])
        assert client.get(f"/api/researches/{rid}").json()["scope"]["seed_use"] is None


def test_a_cited_paper_on_page_two_is_not_taken_for_the_seed(tmp_path, monkeypatch):
    # The PDF names no DOI of its own; its page 2 starts a reference list with another paper's DOI and title.
    pdf = make_pdf([f"{SEED_TITLE}\nA. Author\nAbstract. Deficit irrigation ...",
                    f"References\n[1] {OTHER_TITLE}. doi:{OTHER_DOI}"])
    transport = SeedTransport(records(), by_doi=[seed_work(901, OTHER_TITLE, OTHER_DOI)], semantic=[])
    app, _ = app_for(tmp_path, monkeypatch, transport=transport)
    with client_of(app) as client:
        rid, _ = seeded(client, pdf)
        run_id, _ = discovery(client, rid)
        store = app.state.store
        match = output(store, run_id, "seed_match")
        assert match["status"] == "no_match" and transport.doi_requests == [[OTHER_DOI]]
        assert len(transport.semantic_queries) >= 1
        plan = protocol_body(store, run_id)["fast_path_search"]["semantic"]
        assert plan["seed_text"] == "pdf_excerpt"
        assert all(s["origin"] != "seed_pdf" for s in output(store, run_id, "fast_chain:seeds")["seeds"])


def test_two_titles_on_page_one_decide_nothing_and_no_meaning_search_is_sent(tmp_path, monkeypatch):
    other = "SYNTHETIC deficit irrigation scheduling for greenhouse tomato yield revisited"
    pdf = make_pdf([f"{SEED_TITLE}\n{other}\ndoi:{SEED_DOI} doi:10.1/seed.902", "Body"])
    transport = SeedTransport(records(), by_doi=[seed_work(), seed_work(902, other, "10.1/seed.902")])
    app, _ = app_for(tmp_path, monkeypatch, transport=transport)
    with client_of(app) as client:
        rid, _ = seeded(client, pdf)
        run_id, _ = discovery(client, rid)
        match = output(app.state.store, run_id, "seed_match")
        assert (match["status"], match["ambiguous"]) == ("no_match", True)
        assert output(app.state.store, run_id, "seed_match:semantic") is None


def test_meaning_search_matches_by_title_and_a_failed_lookup_does_not_stop_the_run(tmp_path, monkeypatch):
    pdf = make_pdf([f"{SEED_TITLE}\nA. Author\nAbstract. Deficit irrigation ...", "Body"])
    transport = SeedTransport(records(), semantic=[seed_work()])
    app, _ = app_for(tmp_path, monkeypatch, transport=transport)
    with client_of(app) as client:
        rid, _ = seeded(client, pdf)
        run_id, _ = discovery(client, rid)
        match = output(app.state.store, run_id, "seed_match")
        assert (match["status"], match["basis"]) == ("matched", "title") and not transport.doi_requests

    class Down(SeedTransport):
        def __call__(self, request):
            if "search.semantic" in request.url.params and not self.semantic_queries:
                self.semantic_queries.append("down")
                return httpx.Response(500)
            return super().__call__(request)

    app, _ = app_for(tmp_path / "down", monkeypatch, transport=Down(records()))
    with client_of(app) as client:
        rid, _ = seeded(client, pdf)
        run_id, _ = discovery(client, rid)
        assert output(app.state.store, run_id, "seed_match")["status"] == "lookup_failed"


def test_page_one_without_text_is_never_replaced_by_a_later_page(tmp_path):
    class Store:
        class conn:
            @staticmethod
            def execute(sql, params):
                return Rows([{"physical_page": 1, "text": "  "}, {"physical_page": 2, "text": f"{SEED_TITLE} doi:{SEED_DOI}"}])

    class Rows(list):
        def fetchall(self):
            return list(self)

    assert seed_match.first_pages(Store, {"asset_id": "a", "extraction_version": "v"}) == ("", "", "")


def test_pick_needs_one_title_in_the_head_of_page_one():
    works = [seed_work(), seed_work(901, OTHER_TITLE, OTHER_DOI)]
    assert seed_match.pick(f"{SEED_TITLE} by A. Author", works)[0]["display_name"] == SEED_TITLE
    assert seed_match.pick("nothing here", works) == (None, 0)
    assert seed_match.pick(f"{SEED_TITLE} {OTHER_TITLE}", works) == (None, 2)
    assert seed_match.pick("SYNTHETIC short", [seed_work(903, "SYNTHETIC short")]) == (None, 0)


def test_ranking_never_scores_the_seed_against_its_own_openalex_copy():
    seed = {"id": "up", "work_id": "wk-up", "title": SEED_TITLE, "abstract": None, "own_ids": frozenset(),
            "references": None}
    context = {"status": "matched", "title": SEED_TITLE, "abstract": "deficit irrigation tomato", "openalex_id": "W900",
               "referenced_works": ["W5", "W6"], "references_read": True, "first_page_text": SEED_TITLE}
    row = ranking.pdf_row(seed, context)
    copy = {"id": "c", "work_id": "wk-copy", "title": SEED_TITLE, "abstract": "deficit irrigation tomato",
            "own_ids": frozenset({"W900"}), "references": frozenset({"W5", "W6"})}
    other = {"id": "o", "work_id": "wk-o", "title": "SYNTHETIC drip irrigation tomato", "abstract": "irrigation",
             "own_ids": frozenset({"W7"}), "references": frozenset({"W5"})}
    assert ranking.graph_scores([copy, other], [row]) == {"c": 0.0, "o": 1 / 2 ** 0.5}
    assert ranking.tfidf_scores([copy, other], [row])["c"] == 0.0
    ranked = ranking.rank_pool([copy, other], [row], {"irrigation"}, {}, None, {})
    assert [s["id"] for s in ranked["graph_seeds"]] == ["up", "o"]


def test_a_user_included_openalex_copy_of_the_seed_is_one_seed(monkeypatch):
    context = {"source_version_id": "up", "status": "matched", "title": SEED_TITLE, "abstract": None,
               "openalex_id": "W900", "referenced_works": ["W5"], "references_read": True, "first_page_text": ""}
    monkeypatch.setattr(seed_match, "frozen", lambda store, run: context)
    monkeypatch.setattr(ranking, "verified_seeds", lambda store, rid, scope: ["copy", "up"])
    versions = {"up": {"work_id": "wk-up", "title": "seed.pdf", "abstract": None, "own_ids": set(),
                       "references": set(), "references_read": False},
                "copy": {"work_id": "wk-copy", "title": SEED_TITLE, "abstract": None, "own_ids": {"W900"},
                         "references": {"W5"}, "references_read": True}}
    rows = ranking.seed_rows(None, {"research_id": "r"}, {}, versions, {})
    assert [row["id"] for row in rows] == ["up"] and rows[0]["seed_pdf"]
