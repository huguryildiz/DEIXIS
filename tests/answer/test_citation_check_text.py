"""Verify Citations V2 (D96): each entry's text (the person's PDF first, then the open-access path), the frozen passage
plan, the 200-pair cap, the preview with its cost range, the counters, OpenAlex's daily budget and the purge. Drafts,
records and PDFs are SYNTHETIC; network goes only through a mocked httpx transport and a fake fetcher, and nothing here
calls a model."""

import httpx
import pytest
from fastapi.testclient import TestClient
from deixis.api.app import create_app
from deixis.config import Settings
from deixis.documents.fetch import FetchResult
from deixis.workflow import citation_check
from fakes import FakeAdapter
from helpers import make_pdf


BIB = b"""@article{a, title = {Depth based routing for underwater acoustic networks}, author = {Zeng, Yi}, year = {2022},
  doi = {10.5555/syn.a}}
@article{b, title = {Void avoidance in sparse acoustic networks}, author = {Kim, Jae}, year = {2021}, doi = {10.5555/syn.b}}
@article{c, title = {Energy aware forwarding in mobile sinks}, author = {Park, Min}, year = {2019}, doi = {10.5555/syn.c}}
@article{d, title = {A record with nothing to read at all}, author = {Lee, Ann}, year = {2018}, doi = {10.5555/syn.d}}
"""


DRAFT = (b"Depth based routing raises packet delivery in sparse networks \\cite{a}. Void avoidance keeps packets moving"
         b" around holes \\cite{b}. Mobile sinks save forwarding energy \\cite{c}. Nothing is known \\cite{d}."
         b" Routing by depth again raises delivery \\cite{a}.")


B_PAGES = [f"SYNTHETIC page {i} of the void study: unrelated filler about antennas and buoys." for i in range(1, 10)]


B_PAGES[6] = "SYNTHETIC page 7: void avoidance keeps packets moving around holes in sparse networks."


def work(key, title, abstract=None, pdf_url=None):
    doi = f"10.5555/syn.{key}"
    return {"id": f"https://openalex.org/W{ord(key)}", "doi": f"https://doi.org/{doi}", "display_name": title,
            "publication_year": 2022, "type": "article", "ids": {"openalex": f"https://openalex.org/W{ord(key)}"},
            "authorships": [{"author": {"display_name": "Ada Provider"}}], "is_retracted": False,
            "primary_location": {"version": "publishedVersion", "source": {"display_name": "Provider Journal"}},
            "best_oa_location": None,
            "abstract_inverted_index": {w: [i] for i, w in enumerate(abstract.split())} if abstract else None,
            "locations": [{"pdf_url": pdf_url, "version": "publishedVersion"}] if pdf_url else []}


WORKS = [work("a", "Depth based routing for underwater acoustic networks", "Depth routing raises delivery."),
         work("b", "Void avoidance in sparse acoustic networks", pdf_url="https://oa.example/b.pdf"),
         work("c", "Energy aware forwarding in mobile sinks", "Mobile sinks save forwarding energy in sparse fields."),
         work("d", "A record with nothing to read at all")]


class Net:
    """OpenAlex (DOI filter for resolution, single-DOI lookup for PDF locations), Crossref and Europe PMC answer 404.
    `quota` makes every single-DOI lookup a spent daily budget."""

    def __init__(self, works=WORKS, quota=False):
        self.works, self.quota, self.seen, self.fetched = list(works), quota, [], []

    def handler(self, request):
        self.seen.append(request)
        if request.url.host != "api.openalex.org":
            return httpx.Response(404)
        if "doi.org" in request.url.path:
            if self.quota:
                return httpx.Response(429, headers={"x-ratelimit-remaining-usd": "0", "x-ratelimit-reset": "3600"})
            doi = request.url.path.split("doi.org/", 1)[1]
            found = [w for w in self.works if w["doi"].endswith(doi)]
            return httpx.Response(200, json=found[0]) if found else httpx.Response(404)
        if "filter" not in request.url.params:  # a title search: nothing matches
            return httpx.Response(200, json={"meta": {"count": 0}, "results": []})
        asked = request.url.params["filter"].removeprefix("doi:").split("|")
        found = [w for w in self.works if w["doi"].removeprefix("https://doi.org/") in asked]
        return httpx.Response(200, json={"meta": {"count": len(found)}, "results": found})

    def doi_lookups(self):
        return [r.url.path.split("doi.org/", 1)[1] for r in self.seen
                if r.url.host == "api.openalex.org" and "doi.org" in r.url.path]

    async def fetch(self, url):
        self.fetched.append(url)
        if url == "https://oa.example/b.pdf":
            return FetchResult("ok", data=make_pdf(B_PAGES), final_url=url, http_status=200)
        return FetchResult("http_error", final_url=url, http_status=404)


@pytest.fixture
def make(tmp_path, monkeypatch):
    monkeypatch.setenv("DEIXIS_CONTACT_EMAIL", "")  # Unpaywall and CORE are not configured, so they send nothing
    monkeypatch.setenv("CORE_API_KEY", "")

    def build(net=None):
        net = net or Net()
        settings = Settings(data_dir=tmp_path / "data", port=8765, search_query="code", fulltext_fetch="off")
        app = create_app(settings, adapters={"fake": FakeAdapter()}, http_client=httpx.AsyncClient(
            transport=httpx.MockTransport(net.handler)), fetcher=net.fetch, extra_hosts=("testserver",),
            trusted_clients=("testclient",))
        return app, net, settings
    return build


def session(client):
    client.headers["x-deixis-csrf"] = client.get("/api/session").json()["csrf_token"]
    return client


def start(client, draft=DRAFT, bib=BIB):
    """A draft with its bibliography, resolved; returns the view."""
    response = client.post("/api/citation-checks", files={"file": ("draft.tex", draft, "application/octet-stream"),
                                                          "bibliography": ("refs.bib", bib, "application/octet-stream")})
    assert response.status_code == 201, response.text
    view = client.post(f"/api/citation-checks/{response.json()['id']}/resolve").json()
    assert view["resolved_now"]["lookup_failed"] == 0
    return view


def entry(view, key):
    return next(e for e in view["entries"] if e["key"] == key)


def upload(client, view, key, pages):
    return client.post(f"/api/citation-checks/{view['id']}/entries/{entry(view, key)['id']}/uploads",
                       files={"file": ("mine.pdf", make_pdf(pages), "application/pdf")})


def pair_rows(view):
    return [(m["ordinal"], p) for m in view["markers"] for p in m["pairs"]]


A_PAGES = ["SYNTHETIC doi:10.5555/syn.a Depth based routing for underwater acoustic networks. Delivery rises.",
           "SYNTHETIC page 2: depth routing raises packet delivery in sparse networks."]


def test_the_persons_pdf_is_read_first_then_the_open_access_path_then_the_abstract(make):
    app, net, _ = make()
    with TestClient(app) as raw:
        client = session(raw)
        view = start(client)
        response = upload(client, view, "a", A_PAGES)
        assert response.status_code == 201, response.text
        assert entry(response.json(), "a")["upload"]["identity"] == "doi"
        assert entry(response.json(), "a")["flags"] == []
        view = client.post(f"/api/citation-checks/{view['id']}/acquire").json()
        assert view["acquired_now"] == {"status": "completed", "reset_at": None, "asked": 4, "settled": 4, "pending": 0}
        texts = {key: entry(view, key)["text"] for key in "abcd"}
        assert (texts["a"]["available"], texts["a"]["origin"], texts["a"]["version"]) == ("full_text", "person_pdf", "upload")
        assert (texts["b"]["available"], texts["b"]["origin"], texts["b"]["version"]) == ("full_text", "open_access", "publisher")
        assert (texts["c"]["available"], texts["c"]["origin"], texts["c"]["note"]) == ("abstract", "record", "no_open_copy")
        assert texts["d"]["available"] == "metadata_only"
        # The person's PDF answered for `a`: its open-access path was never asked, and only b's copy was fetched.
        assert "10.5555/syn.a" not in net.doi_lookups() and net.fetched == ["https://oa.example/b.pdf"]
        assert view["text_acquisition"]["status"] == "completed"
        assert view["counters"]["sources_with_text"] == {"full_text": 2, "abstract": 1, "metadata_only": 1, "pending": 0}
        # A settled entry is not asked again.
        sent = len(net.seen)
        again = client.post(f"/api/citation-checks/{view['id']}/acquire").json()
        assert again["acquired_now"]["asked"] == 0 and len(net.seen) == sent


def frozen(client, draft_id, refreeze=False):
    response = client.post(f"/api/citation-checks/{draft_id}/plan", json={"refreeze": refreeze})
    assert response.status_code == 200, response.text
    return response.json()


def test_preview_reads_the_frozen_plan_and_only_a_requested_refreeze_changes_it(make):
    app, _, _ = make()
    with TestClient(app) as raw:
        client = session(raw)
        view = start(client)
        draft_id = view["id"]
        assert client.get(f"/api/citation-checks/{draft_id}/preview").json()["code"] == "plan_not_frozen"
        client.post(f"/api/citation-checks/{draft_id}/acquire")
        frozen(client, draft_id)
        first = client.get(f"/api/citation-checks/{draft_id}/preview").json()
        assert client.get(f"/api/citation-checks/{draft_id}/preview").json() == first
        # The person's PDF arrives after the freeze: the plan stands, and the pairs say it is stale.
        upload(client, view, "a", A_PAGES)
        client.post(f"/api/citation-checks/{draft_id}/acquire")
        again = frozen(client, draft_id)
        assert again["frozen"] == {"revision": 1, "frozen_at": first["plan_frozen_at"], "frozen_now": False}
        second = client.get(f"/api/citation-checks/{draft_id}/preview").json()
        assert [i["passage_ids"] for i in second["selected"]] == [i["passage_ids"] for i in first["selected"]]
        assert [i["stale"] for i in second["selected"] if i["target"] == "a"] == [True, True]
        # Only the person's re-freeze writes revision 2, and each pair keeps its first plan.
        view = frozen(client, draft_id, refreeze=True)
        assert view["plan"]["revision"] == 2
        third = client.get(f"/api/citation-checks/{draft_id}/preview").json()
        a = [i for i in third["selected"] if i["target"] == "a"]
        assert [(i["depth"], i["text_version"], i["stale"]) for i in a] == [("full_text", "upload", False)] * 2
        assert all(p["plan"]["earlier_revisions"] == 1 for _, p in pair_rows(view))
        row = app.state.store.conn.execute(
            "SELECT previous_plans_json FROM citation_pairs WHERE draft_id = ? ORDER BY ordinal LIMIT 1", (draft_id,)).fetchone()
        assert '"revision": 1' in row[0] and '"abstract"' in row[0]


def test_at_most_200_pairs_go_to_the_model_in_draft_order(make):
    app, _, _ = make()
    draft = b" ".join(b"Claim %d about mobile sinks holds \\cite{c}." % i for i in range(1, 206))
    with TestClient(app) as raw:
        client = session(raw)
        view = start(client, draft)
        client.post(f"/api/citation-checks/{view['id']}/acquire")
        frozen(client, view["id"])
        preview = client.get(f"/api/citation-checks/{view['id']}/preview").json()
        assert preview["cap"] == citation_check.MAX_PAIRS_TO_MODEL == 200
        assert [i["ordinal"] for i in preview["selected"]] == list(range(1, 201))
        assert [i["ordinal"] for i in preview["out_of_cap"]] == list(range(201, 206))
        assert preview["out_of_cap"][0]["sentence"].startswith("Claim 201 ")
        counters = preview["counters"]
        # 205 citations of one work: one source, 205 pairs.
        assert (counters["sources_unique"], counters["pairs"], counters["pairs_in_plan"], counters["pairs_to_send"],
                counters["pairs_out_of_cap"]) == (1, 205, 205, 200, 5)
        assert counters["pairs_by_status"]["out_of_cap"] == 5


def test_a_paused_citation_check_run_is_never_resumed_or_queued_by_the_generic_path(make):
    from deixis.domain.rules import RevisionConflict
    app, _, _ = make(Net(quota=True))
    with TestClient(app) as raw:
        client = session(raw)
        view = client.post(f"/api/citation-checks/{start(client)['id']}/acquire").json()
        store = app.state.store
        run_id = view["text_acquisition"]["run_id"]
        with pytest.raises(RevisionConflict):
            store.resume_run(run_id)
        assert store.run(run_id)["status"] == "paused"
        with pytest.raises(RevisionConflict):
            store.create_run(view["research_id"], "citation_check", {}, None)


