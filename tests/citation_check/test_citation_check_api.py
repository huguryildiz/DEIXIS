"""Verify Citations V1 (D86): the draft routes, bibliography matching and OpenAlex resolution through a mocked httpx
transport, the internal research kept out of every list, and the delete cascade. Drafts and records are SYNTHETIC;
nothing here calls a model or the network."""

import httpx
import pytest
from fastapi.testclient import TestClient

from deixis.api.app import create_app
from deixis.config import Settings
from deixis.workflow import citation_check
from fakes import FakeAdapter

CHILD_TABLES = ("citation_markers", "citation_bib_entries", "citation_pairs")

BIB = b"""@article{zeng2022, title = {Depth based routing for underwater networks}, author = {Zeng, Yi and Li, Xu},
  year = {2022}, doi = {10.5555/syn.zeng}}
@article{kim2021, title = {Void avoidance in sparse acoustic networks}, author = {Kim, Jae}, year = {2021}}
@article{kim2021b, title = {Another Kim study of the same year}, author = {Kim, Jae}, year = {2021}}
@misc{park2019, title = {Energy aware forwarding}, author = {Park, Min}, year = {2019}, eprint = {1901.00001},
  archivePrefix = {arXiv}}
@article{broken, author = {No Title}}
"""


def work(wid, title, doi=None, year=2022, retracted=False):
    return {"id": f"https://openalex.org/{wid}", "doi": f"https://doi.org/{doi}" if doi else None, "display_name": title,
            "publication_year": year, "type": "article", "ids": {"openalex": f"https://openalex.org/{wid}"},
            "authorships": [{"author": {"display_name": "Ada Provider"}}], "is_retracted": retracted,
            "primary_location": {"version": "publishedVersion", "source": {"display_name": "Provider Journal"}},
            "best_oa_location": None, "abstract_inverted_index": None}


class OpenAlex:
    """A DOI filter answers from `works`; a search answers `searches[query]` (else nothing). `status` other than 200
    fails every request; `short_count` reports more works than it returns."""

    def __init__(self, works=(), searches=None, status=200, short_count=False):
        self.works, self.searches = list(works), dict(searches or {})
        self.status, self.short_count, self.seen = status, short_count, []

    def handler(self, request):
        self.seen.append(request)
        if request.url.host != "api.openalex.org":
            return httpx.Response(404)
        if self.status != 200:
            return httpx.Response(self.status)
        params = request.url.params
        if "filter" in params:
            asked = params["filter"].removeprefix("doi:").split("|")
            found = [w for w in self.works if w["doi"] and w["doi"].removeprefix("https://doi.org/") in asked]
        else:
            found = self.searches.get(params["search.title_and_abstract"], [])
        return httpx.Response(200, json={"meta": {"count": len(found) + self.short_count}, "results": found})


@pytest.fixture
def make(tmp_path):
    def build(openalex=None):
        openalex = openalex or OpenAlex()
        settings = Settings(data_dir=tmp_path / "data", port=8765, search_query="code", fulltext_fetch="off")
        app = create_app(settings, adapters={"fake": FakeAdapter()}, http_client=httpx.AsyncClient(
            transport=httpx.MockTransport(openalex.handler)), extra_hosts=("testserver",), trusted_clients=("testclient",))
        return app, openalex
    return build


def session(client):
    client.headers["x-deixis-csrf"] = client.get("/api/session").json()["csrf_token"]
    return client


def submit(client, draft=None, name="draft.md", text=None, bib=None, bib_name="refs.bib"):
    files = {}
    if draft is not None:
        files["file"] = (name, draft, "application/octet-stream")
    if bib is not None:
        files["bibliography"] = (bib_name, bib, "application/octet-stream")
    return client.post("/api/citation-checks", files=files or None, data={"text": text} if text is not None else None)


def pairs(view):
    return [(m["raw"], p["target"], p["status"]) for m in view["markers"] for p in m["pairs"]]


def test_a_latex_draft_with_bibtex_maps_keys_and_author_year_and_never_guesses(make):
    app, _ = make()
    draft = (b"\\begin{document}Routing helps \\cite{zeng2022,park2019}. Unknown \\cite{nobody}. Sparse nets (Kim, 2021)"
             b" differ. Zeng and Li (2022) agree. Kim (2021a) too. Broken \\cite{a b}.\\end{document}")
    with TestClient(app) as raw:
        client = session(raw)
        response = submit(client, draft, "draft.tex", bib=BIB)
        assert response.status_code == 201, response.text
        view = response.json()
        assert view["format"] == "tex" and view["bibliography"]["origin"] == "bibtex"
        assert [e["code"] for e in view["bibliography"]["errors"]] == ["no_title"]
        assert pairs(view) == [
            ("\\cite{zeng2022,park2019}", "zeng2022", "planned"), ("\\cite{zeng2022,park2019}", "park2019", "planned"),
            ("\\cite{nobody}", "nobody", "unresolved"),
            ("(Kim, 2021)", "Kim, 2021", "ambiguous"),  # two Kim 2021 entries
            ("Zeng and Li (2022)", "Zeng and Li, 2022", "planned"),
            ("Kim (2021a)", "Kim, 2021a", "ambiguous"),  # a BibTeX entry has no letter suffix
        ]
        assert [m["parse_status"] for m in view["markers"]] == [
            "recognized", "recognized", "ambiguous", "recognized", "ambiguous", "unrecognized"]
        counters = view["counters"]
        assert (counters["occurrences"], counters["occurrences_recognized"], counters["occurrences_ambiguous"],
                counters["occurrences_unrecognized"]) == (6, 3, 2, 1)
        # zeng2022 is cited twice (two pairs) but is one source.
        assert (counters["sources_unique"], counters["sources_resolved"], counters["pairs"]) == (2, 0, 6)
        assert counters["pairs_by_status"]["planned"] == 3 and counters["sources_with_text"] is None
        assert (counters["pairs_sent_to_model"], counters["pairs_done"], counters["pairs_found"],
                counters["pairs_could_not_check"]) == (0, 0, 0, 0)
        park = next(e for e in view["entries"] if e["key"] == "park2019")
        assert park["as_written"]["arxiv_id"] == "1901.00001" and park["source"] is None


def test_an_ieee_draft_with_its_own_numbered_list_and_a_ris_file_for_author_year(make):
    app, _ = make()
    draft = (b"Delivery rises [1]. Energy falls [1]-[3]. Both [2, 4] agree.\n\nReferences\n"
             b"[1] Y. Zeng, \"Depth based routing for underwater networks,\" 2022, doi:10.5555/syn.zeng.\n"
             b"[2] J. Kim, \"Void avoidance in sparse acoustic networks,\" 2021.\n[3] M. Park, \"Energy aware forwarding,\" 2019.\n")
    ris = (b"TY  - JOUR\nID  - k1\nTI  - Void avoidance in sparse acoustic networks\nAU  - Kim, Jae\nPY  - 2021\nER  - \n"
           b"TY  - JOUR\nID  - z1\nTI  - Depth based routing\nAU  - Zeng, Yi\nAU  - Li, Xu\nPY  - 2022\nER  - \n")
    with TestClient(app) as raw:
        client = session(raw)
        view = submit(client, draft, "draft.md").json()
        assert view["bibliography"]["origin"] == "draft_list"
        assert pairs(view) == [("[1]", "1", "planned"), ("[1]-[3]", "1", "planned"), ("[1]-[3]", "2", "planned"),
                               ("[1]-[3]", "3", "planned"), ("[2, 4]", "2", "planned"), ("[2, 4]", "4", "unresolved")]
        assert view["entries"][0]["as_written"]["doi"] == "10.5555/syn.zeng"
        assert view["counters"]["sources_unique"] == 3

        view = submit(client, text="Kim (2021) and (Zeng et al., 2022) agree [1].", bib=ris, bib_name="refs.ris").json()
        assert view["format"] == "text" and view["bibliography"]["origin"] == "ris"
        # A numeric marker has no numbered list to map to when the bibliography is a RIS file.
        assert pairs(view) == [("Kim (2021)", "Kim, 2021", "planned"), ("(Zeng et al., 2022)", "Zeng et al., 2022", "planned"),
                               ("[1]", "1", "unresolved")]


def test_resolution_by_doi_needs_exactly_one_work_and_is_idempotent(make):
    openalex = OpenAlex(works=[work("W1", "Depth based routing for underwater networks", "10.5555/syn.zeng"),
                               work("W2", "Twin A", "10.5555/syn.twin"), work("W3", "Twin B", "10.5555/syn.twin"),
                               work("W4", "Energy aware forwarding", "10.48550/arxiv.1901.00001", year=2019)])
    app, _ = make(openalex)
    bib = BIB + b"@article{twin, title = {Twin A}, author = {T, A}, year = {2020}, doi = {10.5555/syn.twin}}\n" \
                b"@article{gone, title = {Gone}, author = {G, A}, year = {2020}, doi = {10.5555/syn.gone}}\n"
    with TestClient(app) as raw:
        client = session(raw)
        draft_id = submit(client, b"A \\cite{zeng2022, park2019, twin, gone}.", "d.tex", bib=bib).json()["id"]
        response = client.post(f"/api/citation-checks/{draft_id}/resolve")
        assert response.status_code == 200, response.text
        view = response.json()
        assert view["resolved_now"] == {"asked": 4, "resolved": 2, "unresolved": 2, "lookup_failed": 0}
        entries = {e["key"]: e for e in view["entries"]}
        assert (entries["zeng2022"]["resolution"]["status"], entries["zeng2022"]["resolution"]["method"]) == ("resolved", "doi")
        assert entries["zeng2022"]["resolution"]["origin"] == "code"
        # Titles and authors shown come from the stored record, not the entry.
        assert entries["zeng2022"]["source"]["title"] == "Depth based routing for underwater networks"
        assert entries["zeng2022"]["source"]["authors"] == ["Ada Provider"]
        assert (entries["park2019"]["resolution"]["method"], entries["park2019"]["source"]["year"]) == ("arxiv", 2019)
        assert (entries["twin"]["resolution"]["status"], entries["twin"]["resolution"]["reason"]) == ("unresolved", "doi_several_works")
        assert entries["gone"]["resolution"]["reason"] == "doi_not_found"
        assert [p["status"] for p in view["markers"][0]["pairs"]] == ["planned", "planned", "unresolved", "unresolved"]
        assert view["counters"]["sources_resolved"] == 2
        sent = len(openalex.seen)
        again = client.post(f"/api/citation-checks/{draft_id}/resolve").json()
        assert again["resolved_now"]["asked"] == 0 and len(openalex.seen) == sent


@pytest.mark.parametrize("openalex, reason", [(OpenAlex(status=500), "failed"),
                                              (OpenAlex(works=[work("W1", "X", "10.5555/syn.zeng")], short_count=True),
                                               "incomplete_answer")])
def test_a_failed_or_incomplete_lookup_is_asked_again_and_is_not_unresolved(make, openalex, reason):
    app, _ = make(openalex)
    with TestClient(app) as raw:
        client = session(raw)
        draft_id = submit(client, b"A \\cite{zeng2022}.", "d.tex", bib=BIB).json()["id"]
        view = client.post(f"/api/citation-checks/{draft_id}/resolve").json()
        entry = next(e for e in view["entries"] if e["key"] == "zeng2022")
        assert entry["resolution"]["status"] == "lookup_failed"
        assert entry["resolution"]["reason"] == reason
        assert view["markers"][0]["pairs"][0]["status"] == "planned"
        sent = len(openalex.seen)
        assert client.post(f"/api/citation-checks/{draft_id}/resolve").json()["resolved_now"]["asked"] == 1
        assert len(openalex.seen) > sent


def test_title_resolution_needs_one_close_match(make):
    title = "Void avoidance in sparse acoustic networks"
    close = work("W5", "Void avoidance in sparse acoustic network", year=2021)
    assert citation_check.title_similarity(title, close["display_name"]) >= citation_check.TITLE_MATCH_MIN
    far = work("W6", "Void handling in dense acoustic networks", year=2021)
    assert citation_check.title_similarity(title, far["display_name"]) < citation_check.TITLE_MATCH_MIN
    cases = [([close, far], "resolved", None), ([far], "unresolved", "title_no_match"),
             ([close, work("W7", title, year=2021)], "unresolved", "title_several_matches"),
             ([work("W8", title, year=2015)], "unresolved", "title_no_match")]
    for results, status, why in cases:
        app, _ = make(OpenAlex(searches={title: results}))
        with TestClient(app) as raw:
            client = session(raw)
            draft_id = submit(client, b"A \\cite{kim2021}.", "d.tex", bib=BIB).json()["id"]
            entry = next(e for e in client.post(f"/api/citation-checks/{draft_id}/resolve").json()["entries"]
                         if e["key"] == "kim2021")
            assert (entry["resolution"]["status"], entry["resolution"]["reason"]) == (status, why), results
            if status == "resolved":
                assert entry["resolution"]["method"] == "title" and entry["source"]["title"] == close["display_name"]
                assert entry["flags"] == ["title_mismatch"]  # the record's title is not the entry's, letter for letter


def test_title_mismatch_and_retraction_are_flags_beside_the_resolution(make):
    openalex = OpenAlex(works=[work("W1", "A different paper altogether", "10.5555/syn.zeng", retracted=True)])
    app, _ = make(openalex)
    with TestClient(app) as raw:
        client = session(raw)
        draft_id = submit(client, b"A \\cite{zeng2022}.", "d.tex", bib=BIB).json()["id"]
        view = client.post(f"/api/citation-checks/{draft_id}/resolve").json()
        pair = view["markers"][0]["pairs"][0]
        assert pair["status"] == "planned" and pair["flags"] == ["title_mismatch", "retracted"]
        assert pair["source"]["title"] == "A different paper altogether" and pair["result"] is None


def test_the_internal_research_is_kept_out_of_every_list_and_route(make):
    app, _ = make()
    with TestClient(app) as raw:
        client = session(raw)
        view = submit(client, b"Citation check claim [1].", "Citation draft.md").json()
        rid = view["research_id"]
        store = app.state.store
        assert store.is_internal_research(rid)
        # Creating it started nothing: no scope revision, no run, no event, no model call.
        for table in ("scope_revisions", "runs", "events", "model_sessions"):
            assert store.conn.execute(f"SELECT COUNT(*) FROM {table} WHERE research_id = ?", (rid,)).fetchone()[0] == 0
        assert client.get("/api/researches").json() == []
        assert client.get("/api/search", params={"q": "Citation"}).json() == {"researches": [], "sources": []}
        assert client.get("/api/library").json()["researches"] == []
        assert client.get("/api/trash").json()["researches"] == []
        assert client.get("/api/suggestions").status_code == 200
        for path in (f"/api/researches/{rid}", f"/api/researches/{rid}/activity-runs", f"/api/researches/{rid}/queue"):
            assert client.get(path).status_code == 404, path
        assert client.delete(f"/api/researches/{rid}").status_code == 404
        assert client.post(f"/api/trash/{rid}/restore").status_code == 404
        assert client.delete(f"/api/trash/{rid}").status_code == 404
        assert store.conn.execute("SELECT trashed_at FROM researches WHERE id = ?", (rid,)).fetchone()[0] is None
        # A normal research beside it still lists.
        normal = store.create_research("A SYNTHETIC question?", "academic", "quick", [], "fake", "fake-model", None)
        assert [r["id"] for r in client.get("/api/researches").json()] == [normal]
        assert client.get(f"/api/researches/{normal}").status_code == 200


def test_deleting_a_draft_removes_everything_read_from_it_and_its_research(make):
    openalex = OpenAlex(works=[work("W1", "Depth based routing for underwater networks", "10.5555/syn.zeng")])
    app, _ = make(openalex)
    with TestClient(app) as raw:
        client = session(raw)
        keep = submit(client, b"Kept \\cite{kim2021}.", "keep.tex", bib=BIB).json()
        view = submit(client, b"A \\cite{zeng2022} and (Kim, 2021).", "d.tex", bib=BIB).json()
        client.post(f"/api/citation-checks/{view['id']}/resolve")
        store = app.state.store
        svid = next(e for e in client.get(f"/api/citation-checks/{view['id']}").json()["entries"]
                    if e["key"] == "zeng2022")["source"]["source_version_id"]
        pair = store.conn.execute("SELECT id FROM citation_pairs WHERE draft_id = ? AND bib_entry_id IS NOT NULL",
                                  (view["id"],)).fetchone()[0]
        store.conn.execute("INSERT INTO citation_checks (id, pair_id, status, error_json, created_at)"
                           " VALUES ('chk_1', ?, 'could_not_check', '\"repair_exhausted\"', 'now')", (pair,))
        assert client.delete(f"/api/citation-checks/{view['id']}").json() == {"deleted": True}
        assert client.get(f"/api/citation-checks/{view['id']}").status_code == 404
        assert store.conn.execute("SELECT COUNT(*) FROM researches WHERE id = ?", (view["research_id"],)).fetchone()[0] == 0
        for table in CHILD_TABLES:
            assert store.conn.execute(f"SELECT COUNT(*) FROM {table} WHERE draft_id = ?", (view["id"],)).fetchone()[0] == 0
        assert store.conn.execute("SELECT COUNT(*) FROM citation_checks").fetchone()[0] == 0
        # The other draft and the stored provider record stay.
        assert client.get(f"/api/citation-checks/{keep['id']}").status_code == 200
        assert store.source(svid)["title"] == "Depth based routing for underwater networks"
        assert client.delete("/api/citation-checks/cdr_missing").status_code == 404


@pytest.mark.parametrize("files, data, code", [
    (None, None, "draft_missing"),
    ({"file": ("d.pdf", b"%PDF", "application/pdf")}, None, "draft_unknown_format"),
    ({"file": ("d.md", b"A [1].", "text/plain"), "bibliography": ("r.txt", b"nothing here", "text/plain")}, None,
     "import_unknown_format"),
    ({"file": ("d.md", b"A [1].", "text/plain"), "bibliography": ("r.bib", b"@article{x, author={A}}", "text/plain")},
     None, "import_no_entries"),
])
def test_refused_drafts_store_nothing(make, files, data, code):
    app, _ = make()
    with TestClient(app) as raw:
        client = session(raw)
        response = client.post("/api/citation-checks", files=files, data=data)
        assert response.status_code in (413, 415, 422) and response.json()["code"] == code, response.text
        assert app.state.store.conn.execute("SELECT COUNT(*) FROM citation_drafts").fetchone()[0] == 0
        assert app.state.store.conn.execute("SELECT COUNT(*) FROM researches").fetchone()[0] == 0


def test_an_oversized_body_is_refused_before_it_is_read_and_csrf_is_required(make):
    app, _ = make()
    with TestClient(app) as raw:
        client = session(raw)
        too_big = client.post("/api/citation-checks", content=b"x", headers={
            "content-type": "multipart/form-data; boundary=b", "content-length": str(30 * 1024 * 1024)})
        assert too_big.status_code == 413 and too_big.json()["code"] == "draft_too_large"
        assert raw.post("/api/citation-checks", data={"text": "A [1]."}, headers={"x-deixis-csrf": "wrong"}).status_code == 403
