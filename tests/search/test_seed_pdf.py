"""seed_pdf_v1 (D2) and seed_pdf_v2 (D3): the seed PDFs find their OpenAlex works and guide the query, the chain and the
ranking. SYNTHETIC."""

import json

import httpx
import pytest

from deixis.workflow import fast_chain, ranking, seed_match
from helpers import make_pdf
from test_abstract_flow import QUESTION, ON_TOPIC
from overlap_flow_helpers import output, wait
from test_fulltext_flow import Transport, work
from test_small_batch_flow import app_for, client_of


@pytest.fixture(autouse=True)
def no_upload_lookup(monkeypatch):
    """These tests count the seed lookup's own OpenAlex requests; an upload's record lookup (D37) is tested in
    test_upload_record.py, so here it finds nothing and sends nothing."""
    async def nothing(*_args, **_kwargs):
        return False
    monkeypatch.setattr("deixis.documents.upload_record.identify", nothing)

SEED_TITLE = "SYNTHETIC deficit irrigation scheduling for greenhouse tomato yield"
SEED_DOI = "10.1/seed.900"
OTHER_DOI = "10.1/cited.901"


def seed_work(number=900, title=SEED_TITLE, doi=SEED_DOI, references=("W5", "W6")):
    return work(number, doi=doi, title=title) | {
        "display_name": title, "referenced_works": [f"https://openalex.org/{r}" for r in references]}


class SeedTransport(Transport):
    """The fulltext flow's OpenAlex, which also answers a DOI filter and a meaning search with scripted works."""

    def __init__(self, works, by_doi=(), semantic=None, hidden=0):
        super().__init__(works)
        self.by_doi, self.semantic, self.hidden = list(by_doi), semantic, hidden
        self.doi_requests, self.semantic_queries = [], []

    def __call__(self, request):
        params = request.url.params
        if request.url.host == "api.openalex.org" and params.get("filter", "").startswith("doi:"):
            asked = params["filter"].removeprefix("doi:").split("|")
            self.doi_requests.append(asked)
            # One page of `per_page` records; `hidden` more works match than OpenAlex would ever return here.
            found = [w for w in self.by_doi if w["doi"].removeprefix("https://doi.org/") in asked]
            return httpx.Response(200, json={"meta": {"count": len(found) + self.hidden},
                                             "results": found[:int(params["per_page"])]})
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
        assert client.get(f"/api/researches/{rid}").json()["scope"]["seeds"][0]["use"] == {"state": "selected"}
        run_id, view = discovery(client, rid)
        store = app.state.store
        assert view["scope"]["seeds"][0]["use"]["match"] == {"status": "matched", "basis": "doi_title",
                                                             "title": SEED_TITLE, "doi": SEED_DOI, "openalex_id": "W900"}
        match = output(store, run_id, "seed_match")
        context = match["seeds"][0]
        assert (context["status"], context["basis"], context["openalex_id"]) == ("matched", "doi_title", "W900")
        assert context["referenced_works"] == ["W5", "W6"] and context["source_version_id"] == svid
        assert transport.doi_requests == [[SEED_DOI]] and not output(store, run_id, "seed_match:v2:semantic:0")
        body = protocol_body(store, run_id)
        assert body["seed_match"] == match
        # D6: the question's request is the unseeded one; the seed asks on its own with its title and abstract.
        assert body["fast_path_search"]["version"] == 2
        assert body["fast_path_search"]["semantic"]["query_text"] == QUESTION
        assert "seed_text" not in body["fast_path_search"]["semantic"]
        [request] = body["fast_path_search"]["seed_semantic"]
        assert request["query_text"].startswith(SEED_TITLE) and request["origin"] == "match_abstract"
        assert request["source_version_id"] == svid and len(request["query_text"]) <= 1500
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


# ---- seed_pdf_v2 (D3): an ordered set of up to five seed PDFs, uploaded or brought from Zotero. SYNTHETIC. ----------

TITLE_B = "SYNTHETIC sensor based irrigation control for greenhouse cucumbers"
TERMS = ["irrigation", "scheduling", "affect", "marketable", "yield", "greenhouse", "tomato", "production"]


def pdf_of(title, doi=None, page_two="Introduction. Body text."):
    return make_pdf([f"{title}\nA. Author\n" + (f"doi:{doi}\n" if doi else "") + "Abstract. Irrigation results.",
                     page_two])


def research(client, effort="quick"):
    return client.post("/api/researches", json={
        "question": QUESTION, "model_connection": "fake", "requested_model": "fake-model", "effort": effort,
        "source_scope": "attached_and_academic", "seed_mode": "uploaded_seed"}).json()["research"]["id"]


def upload(client, rid, name, pdf):
    response = client.post(f"/api/researches/{rid}/uploads", files={"file": (name, pdf, "application/pdf")})
    assert response.status_code == 201, response.text
    return response.json()["uploaded_source_version_id"]


def select(client, rid, expect=200, version=None, **body):
    version = client.get(f"/api/researches/{rid}").json()["research"]["version"] if version is None else version
    response = client.post(f"/api/researches/{rid}/seed", json=body | {"expected_version": version})
    assert response.status_code == expect, response.text
    return response.json()


