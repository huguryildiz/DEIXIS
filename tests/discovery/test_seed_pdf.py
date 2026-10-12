"""seed_pdf_v1 (D2) and seed_pdf_v2 (D3): the seed PDFs find their OpenAlex works and guide the query, the chain and the
ranking. SYNTHETIC."""

import asyncio
import json

import httpx
import pytest

from deixis.workflow import fast_chain, fast_search, ranking, seed_match
from deixis.workflow import store as store_module
from deixis.workflow import views
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


def d3_frozen(monkeypatch):
    """Freeze the plan D3 wrote (`fast_path_search` version 1 with the seeds' text behind the question), as a run whose
    protocol froze before D6 still has: the envelope reaches `build_plan` under another rule name, so it takes D3's
    branch."""
    build = fast_search.build_plan
    monkeypatch.setattr(fast_search, "build_plan", lambda store, run, scope, queries, seed_context=None: build(
        store, run, scope, queries, seed_context | {"rule": "frozen_before_d6"} if seed_context else seed_context))


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
        assert client.get(f"/api/researches/{rid}").json()["scope"]["seeds"] == []


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
        match = output(store, run_id, "seed_match")["seeds"][0]
        assert match["status"] == "no_match" and transport.doi_requests == [[OTHER_DOI]]
        assert len(transport.semantic_queries) >= 1
        assert [r["origin"] for r in protocol_body(store, run_id)["fast_path_search"]["seed_semantic"]] == ["pdf_excerpt"]
        assert all(s["origin"] != "seed_pdf" for s in output(store, run_id, "fast_chain:seeds")["seeds"])


def test_two_titles_on_page_one_decide_nothing_and_no_meaning_search_is_sent(tmp_path, monkeypatch):
    other = "SYNTHETIC deficit irrigation scheduling for greenhouse tomato yield revisited"
    pdf = make_pdf([f"{SEED_TITLE}\n{other}\ndoi:{SEED_DOI} doi:10.1/seed.902", "Body"])
    transport = SeedTransport(records(), by_doi=[seed_work(), seed_work(902, other, "10.1/seed.902")])
    app, _ = app_for(tmp_path, monkeypatch, transport=transport)
    with client_of(app) as client:
        rid, _ = seeded(client, pdf)
        run_id, _ = discovery(client, rid)
        match = output(app.state.store, run_id, "seed_match")["seeds"][0]
        assert (match["status"], match["ambiguous"]) == ("no_match", True)
        assert output(app.state.store, run_id, "seed_match:v2:semantic:0") is None


def test_meaning_search_matches_by_title_and_a_failed_lookup_does_not_stop_the_run(tmp_path, monkeypatch):
    pdf = make_pdf([f"{SEED_TITLE}\nA. Author\nAbstract. Deficit irrigation ...", "Body"])
    transport = SeedTransport(records(), semantic=[seed_work()])
    app, _ = app_for(tmp_path, monkeypatch, transport=transport)
    with client_of(app) as client:
        rid, _ = seeded(client, pdf)
        run_id, _ = discovery(client, rid)
        match = output(app.state.store, run_id, "seed_match")["seeds"][0]
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
        assert output(app.state.store, run_id, "seed_match")["seeds"][0]["status"] == "lookup_failed"


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
    monkeypatch.setattr(seed_match, "frozen", lambda store, run: {"rule": seed_match.RULE, "seeds": [context]})
    monkeypatch.setattr(ranking, "verified_seeds", lambda store, rid, scope: ["copy", "up"])
    versions = {"up": {"work_id": "wk-up", "title": "seed.pdf", "abstract": None, "own_ids": set(),
                       "references": set(), "references_read": False},
                "copy": {"work_id": "wk-copy", "title": SEED_TITLE, "abstract": None, "own_ids": {"W900"},
                         "references": {"W5"}, "references_read": True}}
    rows = ranking.seed_rows(None, {"research_id": "r"}, {}, versions, {})
    assert [row["id"] for row in rows] == ["up"] and rows[0]["seed_pdf"]


# ---- seed_pdf_v2 (D3): an ordered set of up to five seed PDFs, uploaded or brought from Zotero. SYNTHETIC. ----------

TITLE_B = "SYNTHETIC sensor based irrigation control for greenhouse cucumbers"
TITLE_C = "SYNTHETIC an unpublished note on drip emitter clogging"
ZOT_TITLE = "SYNTHETIC soil moisture thresholds for drip irrigated tomato"
ZOT_DOI = "10.1/zot.920"
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


class ZoteroSeedTransport(SeedTransport):
    """SeedTransport plus the Zotero desktop app's local API with scripted collections; the PDFs are local files."""

    def __init__(self, works, collections=None, files=None, **kwargs):
        super().__init__(works, **kwargs)
        self.collections, self.files = collections or {}, files or {}

    def __call__(self, request):
        if request.url.host == "127.0.0.1" and request.url.port == 23119:
            path = request.url.path
            for key, rows in self.collections.items():
                if path.endswith(f"/collections/{key}/items"):
                    return httpx.Response(200, json=rows)
            if path.endswith("/file") and path.split("/")[-2] in self.files:
                return httpx.Response(302, headers={"location": self.files[path.split("/")[-2]]})
            return httpx.Response(404)
        return super().__call__(request)


def zotero_item(transport, tmp_path, collection, number, title, doi, pdf):
    """One Zotero article with its DOI and one stored PDF, in `collection`."""
    item, attachment = f"ART{number:05d}", f"PDF{number:05d}"
    path = tmp_path / f"{attachment}.pdf"
    path.write_bytes(pdf)
    transport.files[attachment] = path.as_uri()
    transport.collections.setdefault(collection, []).extend([
        {"key": item, "data": {"key": item, "itemType": "journalArticle", "title": title, "DOI": doi}},
        {"key": attachment, "data": {"key": attachment, "itemType": "attachment", "parentItem": item,
                                     "linkMode": "imported_file", "contentType": "application/pdf",
                                     "filename": f"{attachment}.pdf"}}])


def import_collection(client, rid, collection):
    response = client.post(f"/api/researches/{rid}/zotero-imports", json={"source": "local", "collection_key": collection})
    assert response.status_code == 201, response.text
    return response.json()


def test_1_a_d2_snapshot_reads_as_one_seed_and_selecting_it_again_opens_no_revision(tmp_path, monkeypatch):
    app, _ = app_for(tmp_path, monkeypatch, transport=SeedTransport(records()))
    with client_of(app) as client:
        rid, svid = seeded(client, SEED_PDF)
        store = app.state.store
        written = store.scope(rid)["seeds"][0]
        d2 = {key: value for key, value in written.items() if key != "record_dois"}
        store.conn.execute("UPDATE scope_revisions SET seed_snapshot_json = ? WHERE research_id = ? AND revision = ?",
                           (json.dumps(d2), rid, store.scope(rid)["revision"]))
        store.conn.commit()
        scope = store.scope(rid)
        assert scope["seeds"] == [d2 | {"record_dois": []}] and scope["seed_not_selected"] == scope["seed_skipped"] == []
        assert scope["seed_key"] == store_module.seed_key([d2 | {"record_dois": []}])
        assert store.seed_status(rid) == "ready"
        version, revision = store.research(rid)["version"], scope["revision"]
        select(client, rid, version=version - 1, source_version_id=svid)
        assert (store.research(rid)["version"], store.scope(rid)["revision"]) == (version, revision)
        # The D2 excerpt is read as frozen, never cut again: a changed one stays as stored until the seed is chosen anew.
        cut = d2 | {"passages": [dict(p, text=p["text"][:10]) for p in d2["passages"]]}
        store.conn.execute("UPDATE scope_revisions SET seed_snapshot_json = ? WHERE research_id = ? AND revision = ?",
                           (json.dumps(cut), rid, revision))
        store.conn.commit()
        assert [p["text"] for p in store.scope(rid)["seeds"][0]["passages"]] == [p["text"][:10] for p in d2["passages"]]
        select(client, rid, source_version_id=svid)
        assert store.scope(rid)["revision"] == revision + 1


def test_2_one_seed_keeps_d2s_excerpt_and_n_seeds_share_it():
    def passages(n):
        return [{"id": f"p{i}", "physical_page": i + 1, "printed_label": None, "text_source": "pdf_text",
                 "text": (f"page {i} " + ("irrigation " if i == 3 else "filler ")) * 700} for i in range(n)]
    terms = {"irrigation"}
    one = store_module.Store._seed_excerpt("s", passages(1), terms, 1)
    assert [len(p["text"]) for p in one] == [5600]
    two = store_module.Store._seed_excerpt("s", passages(2), terms, 1)
    assert [len(p["text"]) for p in two] == [2800, 2800]
    four = store_module.Store._seed_excerpt("s", passages(6), terms, 1)
    assert [p["id"] for p in four][:3] == ["p0", "p1", "p3"] and [len(p["text"]) for p in four] == [1400] * 4
    for n, (pages, chars) in {2: (2, 2800), 3: (1, 1866), 4: (1, 1400), 5: (1, 1120)}.items():
        given = store_module.Store._seed_excerpt("s", passages(6), terms, n)
        assert len(given) == pages and sum(len(p["text"]) for p in given) <= 5600 // n
        assert given[0]["id"] == "p0" and len(given[0]["text"]) == chars // pages


@pytest.mark.parametrize("frozen_before_d6", [False, True])
def test_3_three_seeds_send_one_doi_request_and_two_meaning_searches(tmp_path, monkeypatch, frozen_before_d6):
    if frozen_before_d6:
        d3_frozen(monkeypatch)
    transport = SeedTransport(records(), by_doi=[seed_work()], semantic=[seed_work(910, TITLE_B, "10.1/b.910", ("W7",))])
    app, _ = app_for(tmp_path, monkeypatch, transport=transport)
    with client_of(app) as client:
        rid = research(client)
        a, b, c = (upload(client, rid, "a.pdf", SEED_PDF), upload(client, rid, "b.pdf", pdf_of(TITLE_B)),
                   upload(client, rid, "c.pdf", pdf_of(TITLE_C)))
        select(client, rid, source_version_ids=[a, b, c])
        run_id, view = discovery(client, rid)
        store = app.state.store
        match = output(store, run_id, "seed_match")
        assert match["rule"] == "seed_pdf_v2" and match["seed_key"] == store.scope(rid)["seed_key"]
        assert [(s["source_version_id"], s["status"], s["basis"]) for s in match["seeds"]] == [
            (a, "matched", "doi_title"), (b, "matched", "title"), (c, "no_match", None)]
        assert transport.doi_requests == [[SEED_DOI]]
        lookups = [q for q in transport.semantic_queries if not q.startswith(QUESTION)]
        assert len(lookups) == (2 if frozen_before_d6 else 2 + 3)
        assert output(store, run_id, "seed_match:v2:semantic:0") is None
        assert output(store, run_id, "seed_match:v2:semantic:1") and output(store, run_id, "seed_match:v2:semantic:2")
        body = protocol_body(store, run_id)
        assert body["seed_match"] == match
        plan = body["fast_path_search"]["semantic"]
        if frozen_before_d6:
            assert plan["seed_text"] == ["match_abstract", "match_abstract", "pdf_excerpt"]
            assert [p["source_version_id"] for p in plan["seed_parts"]] == [a, b, c] and len(plan["query_text"]) <= 1500
            assert "seed_semantic" not in body["fast_path_search"]
        else:
            assert plan["query_text"] == QUESTION and "seed_parts" not in plan
            assert [(r["source_version_id"], r["origin"], r["index"]) for r in body["fast_path_search"]["seed_semantic"]] == [
                (a, "match_abstract", 0), (b, "match_abstract", 1), (c, "pdf_excerpt", 2)]
        seeds = output(store, run_id, "fast_chain:seeds")["seeds"]
        assert [(s["rank"], s["openalex_id"], s["origin"]) for s in seeds[:2]] == [(0, "W900", "seed_pdf"), (1, "W910", "seed_pdf")]
        assert all(s["origin"] != "seed_pdf" for s in seeds[2:])
        uses = [s["use"] for s in view["scope"]["seeds"]]
        assert [s["source_version_id"] for s in view["scope"]["seeds"]] == [a, b, c]
        assert [u["match"]["status"] for u in uses] == ["matched", "matched", "no_match"]
        assert [u["semantic"] for u in uses] == [True, True, True] and [u["chain"] for u in uses] == [True, True, False]
        assert uses[0]["query_writing"] is False and uses[0]["query_writing_detail"] == "code_query"
        if not frozen_before_d6:
            return
        # A seed whose text took no room in the semantic query did not guide it (v3, item 3).
        frozen = store.current_protocol(rid, store.scope(rid)["revision"])
        frozen["body"]["fast_path_search"]["semantic"]["seed_parts"] = [
            p for p in plan["seed_parts"] if p["source_version_id"] != b]
        monkeypatch.setattr(store, "current_protocol", lambda research_id, revision: frozen)
        uses = [s["use"] for s in client.get(f"/api/researches/{rid}").json()["scope"]["seeds"]]
        assert [u["semantic"] for u in uses] == [True, False, True]


def test_4_a_zotero_record_doi_decides_only_with_its_title_at_the_head_of_the_first_text_page(tmp_path, monkeypatch):
    other = "SYNTHETIC a different study of tomato canopy temperature"
    transport = ZoteroSeedTransport(records(), by_doi=[seed_work(920, ZOT_TITLE, ZOT_DOI)], semantic=[])
    # An image cover page: page 1 has no text, page 2 is the paper.
    zotero_item(transport, tmp_path, "COVER001", 1, ZOT_TITLE, ZOT_DOI,
                make_pdf(["", f"{ZOT_TITLE}\nA. Author\nAbstract. Soil moisture thresholds."]))
    # The wrong attachment: another paper whose page 2 cites the record by its full title and DOI.
    zotero_item(transport, tmp_path, "WRONG001", 2, ZOT_TITLE, ZOT_DOI,
                make_pdf([f"{other}\nA. Author\nAbstract. Canopy temperature.", f"References\n[1] {ZOT_TITLE}. doi:{ZOT_DOI}"]))
    app, _ = app_for(tmp_path, monkeypatch, transport=transport)
    with client_of(app) as client:
        store = app.state.store
        cover = research(client)
        import_collection(client, cover, "COVER001")
        select(client, cover, all_eligible=True)
        seed = store.scope(cover)["seeds"][0]
        assert (seed["title_basis"], seed["record_dois"]) == ("record", [ZOT_DOI])
        run_id, _ = discovery(client, cover)
        context = output(store, run_id, "seed_match")["seeds"][0]
        assert (context["status"], context["basis"], context["openalex_id"]) == ("matched", "record_doi", "W920")
        assert context["record_check"] == {"dois": [ZOT_DOI], "status": "confirmed"}
        assert output(store, run_id, "seed_match:v2:semantic:0") is None

        wrong = research(client)
        import_collection(client, wrong, "WRONG001")
        select(client, wrong, all_eligible=True)
        run_id, _ = discovery(client, wrong)
        context = output(store, run_id, "seed_match")["seeds"][0]
        assert context["record_check"] == {"dois": [ZOT_DOI], "status": "not_in_pdf"}
        assert context["status"] == "no_match" and context["basis"] is None


def test_4_record_check_statuses():
    snapshot = {"title": ZOT_TITLE, "record_dois": [ZOT_DOI]}
    head = f"{ZOT_TITLE}\nA. Author"
    work_920 = seed_work(920, ZOT_TITLE, ZOT_DOI)
    assert seed_match.record_decision(head, snapshot, [work_920]) == (work_920, "confirmed")
    assert seed_match.record_decision(head, snapshot, [seed_work(921, ZOT_TITLE, "10.1/other")]) == (None, "no_record")
    assert seed_match.record_decision(head, snapshot, [seed_work(920, OTHER_TITLE, ZOT_DOI)]) == (None, "title_differs")
    assert seed_match.record_decision("  ", snapshot, [work_920]) == (None, "no_region_text")
    assert seed_match.record_decision("Another paper", snapshot, [work_920]) == (None, "not_in_pdf")
    assert seed_match.record_decision(head, snapshot, [work_920, seed_work(922, ZOT_TITLE, ZOT_DOI)]) == (None, "ambiguous")


def test_5_6_seven_candidates_keep_five_by_question_words_and_share_the_excerpt(tmp_path, monkeypatch):
    transport = SeedTransport(records(), semantic=[])
    app, _ = app_for(tmp_path, monkeypatch, transport=transport, search_query="model")
    scores = [1, 5, 2, 5, 0, 3, 4]
    with client_of(app) as client:
        rid = research(client)
        for i, score in enumerate(scores):
            upload(client, rid, f"p{i}.pdf", make_pdf([f"SYNTHETIC paper {i} " + " ".join(TERMS[:score]), "Body text"]))
        store = app.state.store
        candidates = [c["source_version_id"] for c in client.get(f"/api/researches/{rid}").json()["scope"]["seed_candidates"]]
        assert len(candidates) == 7
        version = store.research(rid)["version"]
        view = select(client, rid, version=version, all_eligible=True)
        kept = [candidates[i] for i in (1, 2, 3, 5, 6)]
        assert [s["source_version_id"] for s in view["scope"]["seeds"]] == kept
        assert view["scope"]["seed_not_selected"] == [
            {"source_version_id": candidates[0], "title": "p0", "score": 1},
            {"source_version_id": candidates[4], "title": "p4", "score": 0}]
        revision = store.scope(rid)["revision"]
        # The same request again, after a lost reply, with the version it was first sent with: no conflict, no revision.
        select(client, rid, version=version, all_eligible=True)
        assert store.scope(rid)["revision"] == revision
        # Another selection sent with that old version is a real conflict.
        select(client, rid, expect=409, version=version, source_version_ids=kept[:2])
        run_id, _ = discovery(client, rid)
        step = store.conn.execute("SELECT output_json FROM run_steps WHERE run_id = ? AND operation_key = 'search_query:1'",
                                  (run_id,)).fetchone()
        given = store.step_input_payload(json.loads(step[0])["step_input_id"])
        assert len(given["passages"]) == 5 and sum(len(p["text"]) for p in given["passages"]) <= 5600
        assert [p["source_id"] for p in given["passages"]] == kept
        assert [s["source_id"] for s in given["sources"]] == kept


def test_7_semantic_query_keeps_the_whole_question():
    def envelope(n):
        return {"seeds": [{"source_version_id": f"s{i}", "status": "no_match", "first_page_text": f"{i}" * 3000}
                          for i in range(n)]}
    question = "q" * 100
    query, origin, parts = fast_search.seed_query(question, envelope(1))
    # OpenAlex refuses a semantic query over 1,500 characters (HTTP 400), so that is the budget (D3).
    assert query == (question + " " + "0" * 3000)[:1500] and origin == "pdf_excerpt"
    assert parts == [{"source_version_id": "s0", "origin": "pdf_excerpt", "chars": 1399}]
    query, origin, parts = fast_search.seed_query(question, envelope(3))
    assert query.startswith(question + " ") and len(query) <= 1500 and origin == ["pdf_excerpt"] * 3
    assert [p["chars"] for p in parts] == [465] * 3
    for length in (1499, 1500):
        query, _, parts = fast_search.seed_query("q" * length, envelope(3))
        assert query == "q" * length and parts == []
    query, _, parts = fast_search.seed_query("q" * 1500, envelope(1))
    assert query == "q" * 1500 and parts == []
    query, _, parts = fast_search.seed_query("q" * 2000, envelope(1))
    assert query == "q" * 1500 and parts == []


def test_8_canonical_order_decides_and_duplicates_count_once(tmp_path, monkeypatch):
    app, _ = app_for(tmp_path, monkeypatch, transport=SeedTransport(records()))
    with client_of(app) as client:
        store = app.state.store
        rid = research(client)
        a, b = upload(client, rid, "a.pdf", SEED_PDF), upload(client, rid, "b.pdf", pdf_of(TITLE_B))
        select(client, rid, source_version_ids=[a, b])
        first = store.scope(rid)
        select(client, rid, source_version_ids=[b, a])
        second = store.scope(rid)
        assert second["revision"] == first["revision"] + 1 and store_module.seed_source_ids(second) == [b, a]
        assert second["seed_key"] != first["seed_key"]
        assert ranking.verified_seeds(store, rid, second)[:2] == [b, a]
        select(client, rid, source_version_ids=[a, a, b])
        assert store_module.seed_source_ids(store.scope(rid)) == [a, b]
        assert store.scope(rid)["revision"] == second["revision"] + 1

    def context(svid):
        return {"source_version_id": svid, "status": "matched", "work_id": f"wk-{svid}", "title_key": "t",
                "title": SEED_TITLE, "abstract": None, "openalex_id": "W900", "referenced_works": ["W5"],
                "references_read": True, "first_page_text": "", "lookups": [{"payload_sha256": "x"}]}
    envelope = {"rule": seed_match.RULE, "seeds": [context("b"), context("a")]}
    round_ = fast_chain.Round.__new__(fast_chain.Round)
    round_.store, round_.run, round_.policy = None, {}, {"chain_seeds": 10}
    monkeypatch.setattr(seed_match, "frozen", lambda store, run: envelope)
    assert [(s["rank"], s["source_version_id"]) for s in round_.pdf_seeds()] == [(0, "b")]
    monkeypatch.setattr(ranking, "verified_seeds", lambda store, rid, scope: ["b", "a"])
    versions = {svid: {"work_id": f"wk-{svid}", "title": f"{svid}.pdf", "abstract": None, "own_ids": set(),
                       "references": set(), "references_read": False} for svid in ("a", "b")}
    assert [row["id"] for row in ranking.seed_rows(None, {"research_id": "r"}, {}, versions, {})] == ["b"]


def test_9_the_same_file_under_another_source_is_a_new_seed_and_reextraction_is_stale(tmp_path, monkeypatch):
    transport = ZoteroSeedTransport(records(), by_doi=[seed_work()])
    zotero_item(transport, tmp_path, "SAMEPDF1", 3, SEED_TITLE, SEED_DOI, SEED_PDF)
    app, _ = app_for(tmp_path, monkeypatch, transport=transport)
    with client_of(app) as client:
        store = app.state.store
        rid, uploaded = seeded(client, SEED_PDF)
        first, _ = discovery(client, rid)
        import_collection(client, rid, "SAMEPDF1")
        record = next(c["source_version_id"] for c in store.seed_candidates(rid) if c["origin"] == "zotero_import")
        select(client, rid, source_version_ids=[record])
        seed = store.scope(rid)["seeds"][0]
        assert seed["asset_sha256"] == output(store, first, "seed_match")["seeds"][0]["asset_sha256"]
        second, _ = discovery(client, rid)
        match = output(store, second, "seed_match")
        assert "reused_from_run" not in match and len(transport.doi_requests) == 2
        assert match["seeds"][0]["basis"] == "record_doi" and match["seed_key"] != output(store, first, "seed_match")["seed_key"]
        store.conn.execute("UPDATE source_assets SET extraction_version = 'SYNTHETIC-old' WHERE id = ?", (seed["asset_id"],))
        store.conn.commit()
        assert store.seed_status(rid) == "stale"
        assert client.post(f"/api/researches/{rid}/runs", json={"kind": "discovery"}).status_code == 409


def v1_context(store, rid, svid):
    """The context D2's step stored for SEED_PDF matched by its DOI."""
    scope = store.scope(rid)
    head, _, first_page = seed_match.first_pages(store, scope["seeds"][0])
    return {"rule": "seed_pdf_v1", "status": None, "basis": None, "source_version_id": svid,
            "work_id": store.source(svid)["work_id"], "asset_sha256": scope["seeds"][0]["asset_sha256"],
            "seed_passages_sha256": seed_match.passages_sha256(scope["seeds"]), "first_page_text": first_page,
            "lookups": [{"key": "seed_match:doi", "status": "completed", "retries": 0, "request": "SYNTHETIC",
                         "payload_sha256": "SYNTHETIC"}]} | seed_match.matched(seed_work(), "doi_title")


def test_10_runs_that_began_under_d2_finish_under_d2(tmp_path, monkeypatch):
    from deixis.workflow.flow import ResearchFlow
    original = ResearchFlow._seed_match
    opened = {}

    async def begun_under_d2(self, run, scope):
        # The step D2 opened before this version was installed: succeeded, or open with its DOI lookup done.
        if mode not in opened and self.store.existing_step(run["id"], "seed_match") is None:
            opened[mode] = True
            step = self.store.step(run["id"], "seed_match", "code:seed_match")
            self.store.start_step(step["id"])
            if mode == "succeeded":
                self.store.finish_step(step["id"], "succeeded", output=v1_context(self.store, run["research_id"], svid))
            else:
                sub = self.store.step(run["id"], "seed_match:doi", "code:seed_match_lookup")
                self.store.start_step(sub["id"])
                self.store.finish_step(sub["id"], "succeeded", output={"failed": False, "works": [seed_work()], "summary": {
                    "key": "seed_match:doi", "status": "completed", "retries": 0, "request": "SYNTHETIC", "payload_sha256": "d"}})
        return await original(self, run, scope)

    monkeypatch.setattr(ResearchFlow, "_seed_match", begun_under_d2)
    for mode in ("succeeded", "open"):
        transport = SeedTransport(records(), by_doi=[seed_work()])
        app, _ = app_for(tmp_path / mode, monkeypatch, transport=transport, search_query="model")
        with client_of(app) as client:
            store = app.state.store
            rid, svid = seeded(client, SEED_PDF)
            run_id, view = discovery(client, rid)
            match = output(store, run_id, "seed_match")
            assert match["rule"] == "seed_pdf_v1" and store.existing_step(run_id, "seed_match")["kind"] == "code:seed_match"
            assert (match["status"], match["basis"], match["openalex_id"]) == ("matched", "doi_title", "W900")
            # (b) the DOI lookup D2 already sent is read back, not sent again.
            assert transport.doi_requests == [] and output(store, run_id, "seed_match:v2:doi") is None
            body = protocol_body(store, run_id)
            assert body["seed_match"] == match  # D2's dict, never rewritten as an envelope
            assert body["fast_path_search"]["semantic"]["seed_text"] == "match_abstract"
            seeds = output(store, run_id, "fast_chain:seeds")["seeds"]
            assert (seeds[0]["rank"], seeds[0]["openalex_id"], seeds[0]["origin"]) == (0, "W900", "seed_pdf")
            assert output(store, run_id, "search_query")["seed_passages_sha256"] == match["seed_passages_sha256"]
            # The page matches D2's context to the scope by file, source and excerpt (v3, item 2).
            assert view["scope"]["seeds"][0]["use"]["state"] == "used"
            assert view["scope"]["seeds"][0]["use"]["match"]["basis"] == "doi_title"
            assert view["scope"]["seeds"][0]["use"]["semantic"] is True
            # A plan D2 froze has no seed_parts: when the question fills the 1,500 characters OpenAlex takes, the PDF's
            # text took no room in the query sent, though `seed_text` names it; only a sent query longer than the
            # question and its separator counts. A D2 plan's 2,000-character query is cut to 1,500 when sent.
            frozen = store.current_protocol(rid, store.scope(rid)["revision"])
            semantic = frozen["body"]["fast_path_search"]["semantic"]
            semantic.pop("seed_parts")
            assert semantic["seed_text"] == "match_abstract"
            with monkeypatch.context() as patch:
                patch.setattr(store, "current_protocol", lambda research_id, revision: frozen)
                for length, query, used in ((1500, "q" * 1500, False), (1499, "q" * 1499 + " ", False),
                                            (1498, "q" * 1498 + " x", True), (1998, "q" * 1998 + " x", False)):
                    patch.setattr(views.english_question_rules, "embedding_query",
                                  lambda store, scope, length=length: ("q" * length, "question"))
                    semantic["query_text"] = query
                    use = client.get(f"/api/researches/{rid}").json()["scope"]["seeds"][0]["use"]
                    assert use["semantic"] is used
            # (c) a run whose protocol froze with D2's context goes on reading it as a one-seed envelope.
            store.conn.execute("DELETE FROM run_steps WHERE run_id = ? AND operation_key LIKE 'seed_match%'", (run_id,))
            store.conn.commit()
            run = store.run(run_id)
            assert asyncio.run(app.state.worker.flow._seed_match(run, store.scope(rid))) is None
            frozen = seed_match.frozen(store, run)
            assert frozen["rule"] == "seed_pdf_v1" and frozen["seed_key"] is None and frozen["seeds"] == [match]
            # A later run of the revision does not reuse D2's output; it looks the seed up under v2.
            second, _ = discovery(client, rid)
            assert output(store, second, "seed_match")["rule"] == "seed_pdf_v2"
            assert "reused_from_run" not in output(store, second, "seed_match")


def test_11_a_removed_seed_makes_the_set_stale(tmp_path, monkeypatch):
    app, _ = app_for(tmp_path, monkeypatch, transport=SeedTransport(records()))
    with client_of(app) as client:
        store = app.state.store
        rid = research(client)
        a, b = upload(client, rid, "a.pdf", SEED_PDF), upload(client, rid, "b.pdf", pdf_of(TITLE_B))
        select(client, rid, source_version_ids=[a, b])
        assert store.seed_status(rid) == "ready"
        store.remove_sources(rid, [b], None)
        assert store.seed_status(rid) == "stale"
        assert client.post(f"/api/researches/{rid}/runs", json={"kind": "discovery"}).status_code == 409


def test_12_a_zotero_collection_seeds_the_search_through_all_eligible(tmp_path, monkeypatch):
    transport = ZoteroSeedTransport(records(), by_doi=[seed_work(920, ZOT_TITLE, ZOT_DOI)])
    zotero_item(transport, tmp_path, "ONLYZOT1", 4, ZOT_TITLE, ZOT_DOI, pdf_of(ZOT_TITLE))
    app, _ = app_for(tmp_path, monkeypatch, transport=transport)
    with client_of(app) as client:
        rid = research(client)
        version = client.get(f"/api/researches/{rid}").json()["research"]["version"]
        for body in ({"source_version_id": "srv_SYNTHETIC1", "all_eligible": True}, {}, {"source_version_ids": []},
                     {"source_version_ids": [f"srv_SYNTHETIC{i:02d}" for i in range(51)]}, {"all_eligible": False}):
            assert client.post(f"/api/researches/{rid}/seed", json=body | {"expected_version": version}).status_code == 422
        # No PDF yet: nothing is eligible.
        select(client, rid, expect=422, all_eligible=True)
        view = import_collection(client, rid, "ONLYZOT1")
        assert [c["origin"] for c in view["scope"]["seed_candidates"]] == ["zotero_import"]
        view = select(client, rid, all_eligible=True)
        assert view["scope"]["seed_status"] == "ready" and view["scope"]["seeds"][0]["use"] == {"state": "selected"}
        run_id, _ = discovery(client, rid)
        context = output(app.state.store, run_id, "seed_match")["seeds"][0]
        assert (context["status"], context["basis"]) == ("matched", "record_doi")


def test_13_the_page_counts_only_what_really_read_each_seed(tmp_path, monkeypatch):
    b_doi, c_doi = "10.1/b.910", "10.1/c.911"

    class NoSemantic(SeedTransport):
        def __call__(self, request):
            if request.url.params.get("search.semantic", "").startswith(QUESTION):
                return httpx.Response(400, json={"error": "SYNTHETIC refused"})
            return super().__call__(request)

    transport = NoSemantic(records(), by_doi=[seed_work(), seed_work(910, TITLE_B, b_doi, ("W7",)),
                                              seed_work(911, TITLE_C, c_doi, ("W8",))])
    app, _ = app_for(tmp_path, monkeypatch, transport=transport)
    with client_of(app) as client:
        store = app.state.store
        rid = research(client)
        a, b, c = (upload(client, rid, "a.pdf", SEED_PDF), upload(client, rid, "b.pdf", pdf_of(TITLE_B, b_doi)),
                   upload(client, rid, "c.pdf", pdf_of(TITLE_C, c_doi)))
        select(client, rid, source_version_ids=[a, b, c])
        run_id, view = discovery(client, rid)
        uses = {s["source_version_id"]: s["use"] for s in view["scope"]["seeds"]}
        assert all(u["query_writing"] is False and u["query_writing_detail"] == "code_query" for u in uses.values())
        assert store.existing_step(run_id, "search:fast:semantic")["status"] == "failed"
        # D6: each seed's own request is not the question's; they were answered, so each seed guided the search.
        assert all(u["semantic"] is True for u in uses.values())
        assert all(u["chain"] is True for u in uses.values())
        # Quick sends two forward requests: the third PDF is chained only through the backward request.
        requests = output(store, run_id, "fast_chain:plan")["requests"]
        forward = {r["links"][0]: r["key"] for r in requests if r["direction"] == "forward"}
        assert set(forward) == {a, b}
        assert uses[c]["chain_requests"] == {"planned": 1, "sent": 1, "unsent": 0, "unknown": 0}
        assert uses[a]["chain_requests"] == {"planned": 2, "sent": 2, "unsent": 0, "unknown": 0}
        # A request cut before sending, one that failed before it went out, and one with an unknown outcome and no
        # trace of a send (v4): only `request_sent` decides.
        backward = next(r["key"] for r in requests if r["direction"] == "backward")
        for key, status, delivery, out in ((backward, "cancelled", None, {"unsent": "cutoff", "returned": 0}),
                                           (forward[a], "failed", "before_send", {}),
                                           (forward[b], "outcome_unknown", None, {})):
            store.conn.execute("UPDATE run_steps SET status = ?, delivery_class = ?, output_json = ? WHERE run_id = ?"
                               " AND operation_key = ?", (status, delivery, json.dumps(out), run_id, key))
        store.conn.commit()
        uses = {s["source_version_id"]: s["use"] for s in client.get(f"/api/researches/{rid}").json()["scope"]["seeds"]}
        assert uses[c]["chain_requests"] == {"planned": 1, "sent": 0, "unsent": 1, "unknown": 0}
        assert uses[a]["chain_requests"] == {"planned": 2, "sent": 0, "unsent": 2, "unknown": 0}
        assert uses[b]["chain_requests"] == {"planned": 2, "sent": 0, "unsent": 1, "unknown": 1}


def test_a_seed_doi_reply_must_hold_every_work_that_shares_the_doi(tmp_path, monkeypatch):
    # Two OpenAlex works carry the record's DOI and title: read in full they are ambiguous, never a confirmed match.
    twin = seed_work(921, ZOT_TITLE, ZOT_DOI)
    for hidden, status, check in ((0, "no_first_page_text", "ambiguous"), (1, "lookup_failed", "lookup_failed")):
        transport = ZoteroSeedTransport(records(), by_doi=[seed_work(920, ZOT_TITLE, ZOT_DOI), twin], hidden=hidden)
        (tmp_path / str(hidden)).mkdir()
        zotero_item(transport, tmp_path / str(hidden), "TWINDOI1", 5, ZOT_TITLE, ZOT_DOI,
                    make_pdf(["", f"{ZOT_TITLE}\nA. Author\nAbstract. Soil moisture thresholds."]))
        app, _ = app_for(tmp_path / f"app{hidden}", monkeypatch, transport=transport)
        with client_of(app) as client:
            rid = research(client)
            import_collection(client, rid, "TWINDOI1")
            select(client, rid, all_eligible=True)
            run_id, _ = discovery(client, rid)
            store = app.state.store
            context = output(store, run_id, "seed_match")["seeds"][0]
            assert (context["status"], context["record_check"]["status"]) == (status, check)
            assert "openalex_id" not in context
            lookup = store.existing_step(run_id, "seed_match:v2:doi")
            assert "per_page=100" in lookup["output"]["summary"]["request"]
            assert (lookup["status"], lookup["error_code"]) == (("succeeded", None) if not hidden else ("failed", "incomplete"))


def test_10c_a_paused_run_that_froze_under_d2_resumes_through_the_worker_without_a_second_lookup(tmp_path, monkeypatch):
    from deixis.workflow.flow import ResearchFlow
    original_match, original_close = ResearchFlow._seed_match, ResearchFlow._close_clock_stage
    state = {}

    async def begun_under_d2(self, run, scope):
        # D2 opened its seed step before this version was installed; the run finishes that step under D2.
        if not state.get("opened") and self.store.existing_step(run["id"], "seed_match") is None:
            state["opened"] = True
            self.store.start_step(self.store.step(run["id"], "seed_match", "code:seed_match")["id"])
        return await original_match(self, run, scope)

    def paused_after_planning(self, run, stage):
        # The person pauses the run once its protocol is frozen: it stops at its next checkpoint.
        original_close(self, run, stage)
        if stage == "plan" and not state.get("paused"):
            state["paused"] = True
            self.store.update_run(run["id"], event="run_pause_requested", status="pause_requested",
                                  pause_reason="user_requested")

    monkeypatch.setattr(ResearchFlow, "_seed_match", begun_under_d2)
    monkeypatch.setattr(ResearchFlow, "_close_clock_stage", paused_after_planning)
    transport = SeedTransport(records(), by_doi=[seed_work()])
    app, _ = app_for(tmp_path, monkeypatch, transport=transport)
    with client_of(app) as client:
        store = app.state.store
        rid, _ = seeded(client, SEED_PDF)
        run_id = client.post(f"/api/researches/{rid}/runs", json={"kind": "discovery"}).json()["id"]
        _, run = wait(client, rid, run_id, statuses=("paused",))
        frozen = output(store, run_id, "protocol")
        assert protocol_body(store, run_id)["seed_match"]["rule"] == "seed_pdf_v1"
        assert transport.doi_requests == [[SEED_DOI]]
        sent = list(transport.semantic_queries)
        protocols = store.conn.execute("SELECT COUNT(*) FROM protocol_records WHERE research_id = ?", (rid,)).fetchone()[0]
        assert client.post(f"/api/runs/{run_id}/resume").status_code == 200
        _, run = wait(client, rid, run_id)
        assert run["status"] == "completed", run
        assert transport.doi_requests == [[SEED_DOI]] and transport.semantic_queries[:len(sent)] == sent
        assert not [q for q in transport.semantic_queries[len(sent):] if not q.startswith(QUESTION)]
        assert output(store, run_id, "protocol") == frozen
        assert store.conn.execute("SELECT COUNT(*) FROM protocol_records WHERE research_id = ?", (rid,)).fetchone()[0] == protocols
        assert output(store, run_id, "seed_match")["rule"] == "seed_pdf_v1"
        assert output(store, run_id, "seed_match:v2:doi") is None
        seeds = output(store, run_id, "fast_chain:seeds")["seeds"]
        assert (seeds[0]["openalex_id"], seeds[0]["origin"]) == ("W900", "seed_pdf")


def test_the_semantic_request_never_sends_more_than_openalex_accepts():
    """OpenAlex answers HTTP 400 "Search query too long" past 1,500 characters (measured live, 11 Oct 2026)."""
    from deixis.providers import openalex
    sent = []
    def handler(request):
        sent.append(request.url.params["search.semantic"])
        return httpx.Response(200, json={"meta": {"count": 0}, "results": []})
    async def go():
        async with httpx.AsyncClient(transport=httpx.MockTransport(handler)) as client:
            return await openalex.search_semantic(client, "x" * 3000, 10)
    outcome = asyncio.run(go())
    assert sent == ["x" * openalex.SEMANTIC_MAX_CHARS] and openalex.SEMANTIC_MAX_CHARS == 1500
    assert "x" * 1501 not in outcome.request_description


def test_a_semantic_request_spaces_every_attempt_start_and_waits_for_no_other_reply():
    """OpenAlex semantic search allows one request per second: the pacer spaces starts, retries included, and holds no
    lock through a reply (help.openalex.org, read 2026-10-12)."""
    from deixis.providers import openalex
    waits, seen = [], []

    class Spy:
        async def start(self):
            waits.append(len(seen))

    def handler(request):
        seen.append(request.url.params["search.semantic"])
        if len(seen) == 1:
            return httpx.Response(429, json={"error": "SYNTHETIC busy"})
        return httpx.Response(200, json={"meta": {"count": 0}, "results": []})

    from unittest.mock import patch
    from deixis.providers import common, pacing
    real_sleep = asyncio.sleep

    async def no_wait(seconds):
        await real_sleep(0)

    async def go():
        async with httpx.AsyncClient(transport=httpx.MockTransport(handler)) as client:
            return await openalex.search_semantic(client, "q", 10)
    with patch.object(openalex, "SEMANTIC_PACER", Spy()), patch.object(common.asyncio, "sleep", no_wait):
        outcome = asyncio.run(go())
    # One slot is taken before each attempt: the first request and its retry after the 429.
    assert outcome.status in ("completed", "zero_results") and waits == [0, 1] and len(seen) == 2
    assert openalex.MAX_RESULTS == 100 and isinstance(openalex.SEMANTIC_PACER, pacing.StartPacer)


def test_callers_that_overslept_together_still_start_one_interval_apart():
    """A start is claimed when its caller wakes, not when it began to wait: after a stall the waiters do not all go."""
    from unittest.mock import patch
    from deixis.providers import pacing
    real_sleep, clock, starts = asyncio.sleep, {"now": 100.0}, []

    async def go():
        stalled = asyncio.Event()

        async def sleep(seconds):
            if not stalled.is_set():
                await stalled.wait()  # the loop stalls; every waiter wakes at once when it ends
            else:
                clock["now"] += seconds
                await real_sleep(0)

        async def stall():
            for _ in range(3):
                await real_sleep(0)
            clock["now"] = 110.0
            stalled.set()

        gate = pacing.StartPacer(1.5)

        async def one():
            await gate.start()
            starts.append(clock["now"])
        with patch.object(pacing.asyncio, "sleep", sleep):
            await asyncio.gather(one(), one(), one(), stall())
    with patch.object(pacing.time, "monotonic", lambda: clock["now"]):
        asyncio.run(go())
    assert starts[0] == 100.0 and len(starts) == 3 and all(b - a >= 1.5 for a, b in zip(starts, starts[1:]))


def test_a_request_waiting_for_its_start_sends_nothing_once_the_quota_ran_out():
    from deixis.providers import common, openalex
    from unittest.mock import patch
    seen = []

    class Gate:
        async def start(self):
            pass

    def handler(request):
        seen.append(request.url)
        return httpx.Response(200, json={"meta": {"count": 0}, "results": []})

    async def go(why):
        token = common.send_blocked.set(lambda: why)
        try:
            with common.collect_transport() as entries:
                async with httpx.AsyncClient(transport=httpx.MockTransport(handler)) as client:
                    return await openalex.search_semantic(client, "q", 10), entries
        finally:
            common.send_blocked.reset(token)
    with patch.object(openalex, "SEMANTIC_PACER", Gate()):
        (quota, quota_entries), (stopped, stopped_entries) = asyncio.run(go("quota_exhausted")), asyncio.run(go("stopped"))
    assert not seen and quota.error_kind == "quota_exhausted" and quota.delivery_class == "before_send"
    assert (stopped.status, stopped.delivery_class, stopped.error_kind) == ("failed", "before_send", None)
    # An attempt stopped at its gate costs no request allowance: nothing is counted, nothing was sent.
    assert [(e["attempts"], e["sends"]) for e in quota_entries + stopped_entries] == [(0, 0), (0, 0)]


def test_openalex_counts_a_letter_outside_the_basic_plane_twice():
    """OpenAlex counts UTF-16 code units: 1,500 characters with three math italic letters were refused as 1,503
    (measured live, 11 Oct 2026, a battery seed PDF's first page)."""
    from deixis.providers import openalex
    def units(text):
        return len(text.encode("utf-16-le")) // 2
    text = "𝑆𝑜𝐻 " + "x" * 1600
    cut = openalex.semantic_text(text)
    assert units(cut) == 1500 and cut == text[:1497]
    assert openalex.semantic_text("𝑆" * 800) == "𝑆" * 750
    assert openalex.semantic_text("x" * 1499 + "𝑆") == "x" * 1499
    assert openalex.semantic_text("© ∗ plain") == "© ∗ plain"
    plain = "y" * 3000
    assert openalex.semantic_text(plain) == plain[:1500]
    sent = []
    def handler(request):
        sent.append(request.url.params["search.semantic"])
        return httpx.Response(200, json={"meta": {"count": 0}, "results": []})
    async def go():
        async with httpx.AsyncClient(transport=httpx.MockTransport(handler)) as client:
            await openalex.search_semantic(client, text, 10)
    asyncio.run(go())
    assert [units(q) for q in sent] == [1500]
    envelope = {"rule": seed_match.RULE, "seeds": [{"source_version_id": "a", "status": "no_match", "first_page_text": text}]}
    assert units(fast_search.seed_requests(envelope, 25)[0]["query_text"]) == 1500


def test_a_failed_lookup_is_asked_again_by_the_next_run(tmp_path, monkeypatch):
    """A run whose seed lookup failed (an OpenAlex 400 before the 1,500-character limit, an incomplete DOI reply) does
    not hand that failure to the next run of the revision; the next run asks again (D3)."""
    transport = SeedTransport(records(), by_doi=[seed_work()], hidden=1)
    app, _ = app_for(tmp_path, monkeypatch, transport=transport)
    with client_of(app) as client:
        rid, _ = seeded(client, SEED_PDF)
        first, _ = discovery(client, rid)
        store = app.state.store
        assert output(store, first, "seed_match")["seeds"][0]["status"] == "lookup_failed"
        transport.hidden = 0
        second, view = discovery(client, rid)
        match = output(store, second, "seed_match")
        assert "reused_from_run" not in match and match["seeds"][0]["status"] == "matched"
        assert len(transport.doi_requests) == 2


def test_a_seed_part_cut_off_on_sending_did_not_guide_the_semantic_search(tmp_path, monkeypatch):
    """A plan frozen before the 1,500-character limit may name seed parts that sending cut off; only parts that reached
    OpenAlex count as use (D3)."""
    d3_frozen(monkeypatch)
    app, _ = app_for(tmp_path, monkeypatch, transport=SeedTransport(records(), by_doi=[seed_work()]))
    with client_of(app) as client:
        rid, svid = seeded(client, SEED_PDF)
        discovery(client, rid)
        store = app.state.store
        frozen = store.current_protocol(rid, store.scope(rid)["revision"])
        frozen["body"]["fast_path_search"]["semantic"]["seed_parts"] = [
            {"source_version_id": svid, "origin": "match_abstract", "chars": 400}]
        with monkeypatch.context() as patch:
            patch.setattr(store, "current_protocol", lambda research_id, revision: frozen)
            for length, used in ((1600, False), (1499, False), (1498, True), (100, True)):
                patch.setattr(views.english_question_rules, "embedding_query",
                              lambda store, scope, length=length: ("q" * length, "question"))
                use = client.get(f"/api/researches/{rid}").json()["scope"]["seeds"][0]["use"]
                assert use["semantic"] is used, length


def test_s5b_an_excluded_upload_leaves_the_choice_of_five_to_the_backend(tmp_path, monkeypatch):
    """UI parity S5b: Home unchecks an uploaded PDF. With six Zotero PDFs and one other upload there are seven usable
    candidates; D3's rule keeps five by question words and records the other two as not selected. The unchecked upload
    scores highest, yet is neither a seed, nor not selected, nor skipped, and stays an attached source."""
    transport = ZoteroSeedTransport(records(), semantic=[])
    zotero_scores = [5, 0, 3, 1, 2, 4]
    for i, score in enumerate(zotero_scores):
        zotero_item(transport, tmp_path, "MANYZOT1", 30 + i, f"SYNTHETIC Zotero paper {i}", f"10.1/zot.{930 + i}",
                    make_pdf([f"SYNTHETIC Zotero paper {i} " + " ".join(TERMS[:score]), "Body text"]))
    app, _ = app_for(tmp_path, monkeypatch, transport=transport)
    with client_of(app) as client:
        rid = research(client)
        kept_upload = upload(client, rid, "a.pdf", make_pdf(["SYNTHETIC upload a " + " ".join(TERMS[:4]), "Body text"]))
        unchecked = upload(client, rid, "b.pdf", make_pdf(["SYNTHETIC upload b " + " ".join(TERMS[:6]), "Body text"]))
        import_collection(client, rid, "MANYZOT1")
        store = app.state.store
        candidates = client.get(f"/api/researches/{rid}").json()["scope"]["seed_candidates"]
        zotero = {c["title"]: c["source_version_id"] for c in candidates if c["origin"] == "zotero_import"}
        assert len(candidates) == 8 and len(zotero) == 6
        # Only with every eligible PDF; never with a named list.
        select(client, rid, expect=422, source_version_ids=[kept_upload], excluded_source_version_ids=[unchecked])
        view = select(client, rid, all_eligible=True, excluded_source_version_ids=[unchecked])
        z = [zotero[f"SYNTHETIC Zotero paper {i}"] for i in range(6)]
        scope = view["scope"]
        assert {s["source_version_id"] for s in scope["seeds"]} == {kept_upload, z[0], z[2], z[4], z[5]}
        assert [(n["source_version_id"], n["score"]) for n in scope["seed_not_selected"]] == [(z[1], 0), (z[3], 1)]
        assert scope["seed_skipped"] == []
        assert unchecked in {s["source_version_id"] for s in view["sources"] if s["selection"]["state"] == "included"}
        event = store.conn.execute("SELECT payload_json FROM events WHERE research_id = ? AND type = 'seed_selected'"
                                   " ORDER BY id DESC LIMIT 1", (rid,)).fetchone()[0]
        assert json.loads(event)["excluded_by_user"] == [unchecked]
        # The same request again changes nothing.
        revision = store.scope(rid)["revision"]
        select(client, rid, all_eligible=True, excluded_source_version_ids=[unchecked])
        assert store.scope(rid)["revision"] == revision
