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


def test_a_pdf_that_does_not_name_its_work_is_flagged_not_hidden(make):
    app, _, _ = make()
    with TestClient(app) as raw:
        client = session(raw)
        view = start(client)
        view = upload(client, view, "a", ["SYNTHETIC doi:10.9999/other.paper An unrelated study of lake ice."]).json()
        assert entry(view, "a")["upload"]["identity"] == "unconfirmed"
        assert "identity_unconfirmed" in entry(view, "a")["flags"]
        view = client.post(f"/api/citation-checks/{view['id']}/acquire").json()
        assert entry(view, "a")["text"]["origin"] == "person_pdf"
        assert all("identity_unconfirmed" in p["flags"] for _, p in pair_rows(view) if p["target"] == "a")
        # An entry that names no record takes no PDF.
        unresolved = start(client, b"Nobody \\cite{zz}.", BIB + b"@article{zz, title = {Gone away}, author = {Z, Z}, year = {2001}}")
        assert upload(client, unresolved, "zz", A_PAGES).status_code == 409


def frozen(client, draft_id, refreeze=False):
    response = client.post(f"/api/citation-checks/{draft_id}/plan", json={"refreeze": refreeze})
    assert response.status_code == 200, response.text
    return response.json()


def test_the_plan_gives_k_ranked_passages_the_abstract_alone_or_nothing(make):
    app, _, _ = make()
    with TestClient(app) as raw:
        client = session(raw)
        view = start(client)
        upload(client, view, "a", A_PAGES)
        client.post(f"/api/citation-checks/{view['id']}/acquire")
        view = frozen(client, view["id"])
        assert view["frozen"]["revision"] == 1 and view["frozen"]["frozen_now"]
        preview = client.get(f"/api/citation-checks/{view['id']}/preview").json()
        by_target = {}
        for item in preview["selected"]:
            by_target.setdefault(item["target"], item)
        # b has nine pages: six are given, three are not, and the page that shares the sentence's words comes first.
        b = by_target["b"]
        assert (b["depth"], b["passages_given"], b["passages_total"], b["passages_not_given"]) == ("selected_passages", 6, 9, 3)
        store = app.state.store
        assert store.passage(b["passage_ids"][0])["physical_page"] == 7
        assert citation_check.PASSAGES_PER_PAIR == 6
        # The person's two-page PDF is given whole: only then is the depth full_text.
        a = by_target["a"]
        assert (a["depth"], a["passages_given"], a["passages_not_given"]) == ("full_text", 2, 0)
        # An abstract-only record is read from its abstract, one passage.
        c = by_target["c"]
        assert (c["depth"], c["passages_given"], c["passages_total"]) == ("abstract", 1, 1)
        assert store.passage(c["passage_ids"][0])["kind"] == "abstract"
        # Only metadata: no plan, no model call.
        d = [p for _, p in pair_rows(view) if p["target"] == "d"]
        assert [(p["status"], p["plan"]["depth"], p["plan"]["passage_ids"]) for p in d] == [("no_text", None, [])]
        assert "d" not in by_target
        counters = preview["counters"]
        assert (counters["pairs"], counters["pairs_in_plan"], counters["pairs_to_send"], counters["pairs_out_of_cap"]) == (5, 4, 4, 0)
        assert counters["pairs_by_status"]["no_text"] == 1
        # `a` is cited twice: one source, two pairs.
        assert counters["sources_unique"] == 4 and sum(1 for item in preview["selected"] if item["target"] == "a") == 2
        assert (counters["pairs_sent_to_model"], counters["pairs_done"], counters["pairs_found"],
                counters["pairs_could_not_check"]) == (None, None, None, None)


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


def test_the_cost_range_uses_the_price_table_and_an_unknown_price_is_unknown(make):
    app, _, _ = make()
    with TestClient(app) as raw:
        client = session(raw)
        view = start(client)
        client.post(f"/api/citation-checks/{view['id']}/acquire")
        frozen(client, view["id"])
        url = f"/api/citation-checks/{view['id']}/preview"
        unlisted = client.get(url, params={"connection": "openai", "model": "no-such-model"}).json()["cost"]
        assert (unlisted["applies"], unlisted["usd"], unlisted["reason"]) == (True, "unknown", "price_not_listed")
        assert unlisted["calls"] == [4, 8]
        listed = client.get(url, params={"connection": "anthropic", "model": "claude-sonnet-4-6",
                                         "reasoning_effort": "medium"}).json()["cost"]
        assert 0 < listed["usd"][0] < listed["usd"][1]
        assert client.get(url).json()["cost"]["usd"] == "unknown"  # no literature model set in Settings
        subscription = client.get(url, params={"connection": "codex", "model": "gpt-6-sol"}).json()["cost"]
        assert (subscription["applies"], subscription["usd"]) == (False, None)


def test_a_spent_openalex_budget_pauses_and_keeps_what_was_decided(make):
    app, net, _ = make(Net(quota=True))
    with TestClient(app) as raw:
        client = session(raw)
        view = start(client)
        upload(client, view, "a", A_PAGES)
        view = client.post(f"/api/citation-checks/{view['id']}/acquire").json()
        outcome = view["acquired_now"]
        assert (outcome["status"], outcome["settled"], outcome["pending"]) == ("paused", 1, 3) and outcome["reset_at"]
        assert entry(view, "a")["text"]["status"] == "settled"
        assert [entry(view, k)["text"]["note"] for k in "bcd"] == [citation_check.BUDGET_STOP] * 3
        # Only b's lookup was sent; c and d were not asked once the budget was known to be spent.
        assert net.doi_lookups() == ["10.5555/syn.b"]
        assert (view["text_acquisition"]["status"], view["text_acquisition"]["pause_reason"]) == ("paused", "openalex_budget_exhausted")
        assert app.state.store.openalex_budget_reset() is not None  # every other run of the app sees it too
        assert view["counters"]["sources_with_text"]["pending"] == 3
        refused = client.post(f"/api/citation-checks/{view['id']}/plan", json={})
        assert (refused.status_code, refused.json()["code"]) == (409, "text_pending")
        sent = len(net.seen)
        again = client.post(f"/api/citation-checks/{view['id']}/acquire").json()
        assert again["acquired_now"]["status"] == "paused" and len(net.seen) == sent
        assert entry(again, "a")["text"]["origin"] == "person_pdf"


def test_deleting_the_draft_removes_the_files_and_passages_it_acquired(make):
    app, _, settings = make()
    with TestClient(app) as raw:
        client = session(raw)
        view = start(client)
        upload(client, view, "a", A_PAGES)
        view = client.post(f"/api/citation-checks/{view['id']}/acquire").json()
        store = app.state.store
        read = [entry(view, k)["text"]["source_version_id"] for k in "abc"]
        files = [r[0] for r in store.conn.execute(
            f"SELECT storage_path FROM source_assets WHERE source_version_id IN ({','.join('?' * len(read))})", read)]
        assert len(files) == 2 and all((settings.papers_dir / f).exists() for f in files)
        assert store.conn.execute(f"SELECT COUNT(*) FROM passages WHERE source_version_id IN ({','.join('?' * len(read))})",
                                  read).fetchone()[0] > 0
        response = client.delete(f"/api/citation-checks/{view['id']}")
        assert response.json() == {"deleted": True, "files_not_removed": []}
        assert not any((settings.papers_dir / f).exists() for f in files)
        marks = ",".join("?" * len(read))
        assert store.conn.execute(f"SELECT COUNT(*) FROM passages WHERE source_version_id IN ({marks})", read).fetchone()[0] == 0
        assert store.conn.execute(f"SELECT COUNT(*) FROM source_versions WHERE id IN ({marks})", read).fetchone()[0] == 0
        assert store.conn.execute("SELECT COUNT(*) FROM runs WHERE research_id = ?", (view["research_id"],)).fetchone()[0] == 0


# ---- review round 1 (Sol): identity on every chosen PDF, frozen identity per revision, staleness, resume, retries

B_NAMED = ["SYNTHETIC doi:10.5555/syn.b Void avoidance in sparse acoustic networks."] + B_PAGES[1:]


def pair_flags_of(view, key):
    return [p["flags"] for _, p in pair_rows(view) if p["target"] == key]


def test_an_open_access_pdf_that_does_not_name_its_work_is_flagged_through_plan_and_preview(make):
    app, _, _ = make()  # b's open copy is an unrelated text under b's correct DOI
    with TestClient(app) as raw:
        client = session(raw)
        view = start(client)
        view = client.post(f"/api/citation-checks/{view['id']}/acquire").json()
        b = entry(view, "b")
        assert (b["text"]["origin"], b["text"]["identity"]) == ("open_access", "unconfirmed")
        assert "identity_unconfirmed" in b["flags"] and pair_flags_of(view, "b") == [["identity_unconfirmed"]]
        view = frozen(client, view["id"])
        assert pair_flags_of(view, "b") == [["identity_unconfirmed"]]
        item = next(i for i in client.get(f"/api/citation-checks/{view['id']}/preview").json()["selected"] if i["target"] == "b")
        assert item["flags"] == ["identity_unconfirmed"] and item["identity"]["result"] == "unconfirmed"
        assert item["identity"]["asset_id"] and item["identity"]["extraction_version"]


def test_an_open_access_pdf_that_names_its_work_is_confirmed(make):
    net = Net()

    async def fetch(url):
        net.fetched.append(url)
        return FetchResult("ok", data=make_pdf(B_NAMED), final_url=url, http_status=200)

    net.fetch = fetch
    app, _, _ = make(net)
    with TestClient(app) as raw:
        client = session(raw)
        view = client.post(f"/api/citation-checks/{start(client)['id']}/acquire").json()
        assert entry(view, "b")["text"]["identity"] == "doi" and pair_flags_of(view, "b") == [[]]


def test_a_stored_pdf_is_checked_too(make):
    app, _, _ = make()
    with TestClient(app) as raw:
        client = session(raw)
        client.post(f"/api/citation-checks/{start(client)['id']}/acquire")  # b's unrelated copy is now stored on b
        view = start(client, b"Void avoidance keeps packets moving \\cite{b}.")
        view = client.post(f"/api/citation-checks/{view['id']}/acquire").json()
        b = entry(view, "b")
        assert (b["text"]["origin"], b["text"]["identity"]) == ("stored_pdf", "unconfirmed")
        assert pair_flags_of(view, "b") == [["identity_unconfirmed"]]


def test_a_new_upload_never_clears_a_frozen_revisions_warning(make):
    app, _, _ = make()
    with TestClient(app) as raw:
        client = session(raw)
        view = start(client)
        upload(client, view, "a", ["SYNTHETIC doi:10.9999/other.paper An unrelated study of lake ice."])
        client.post(f"/api/citation-checks/{view['id']}/acquire")
        frozen(client, view["id"])
        upload(client, view, "a", A_PAGES)  # the right PDF, confirmed by its DOI
        view = client.post(f"/api/citation-checks/{view['id']}/acquire").json()
        assert entry(view, "a")["text"]["identity"] == "doi" and "identity_unconfirmed" not in entry(view, "a")["flags"]
        # The frozen revision still reads the unrelated PDF, so its pairs keep the warning, and say they are stale.
        assert pair_flags_of(view, "a") == [["identity_unconfirmed"], ["identity_unconfirmed"]]
        preview = client.get(f"/api/citation-checks/{view['id']}/preview").json()
        a = [i for i in preview["selected"] if i["target"] == "a"]
        assert [(i["flags"], i["stale"], i["identity"]["result"]) for i in a] == [(["identity_unconfirmed"], True, "unconfirmed")] * 2
        view = frozen(client, view["id"], refreeze=True)
        assert pair_flags_of(view, "a") == [[], []]
        row = app.state.store.conn.execute(
            "SELECT previous_plans_json FROM citation_pairs WHERE draft_id = ? AND target = 'a' ORDER BY ordinal LIMIT 1",
            (view["id"],)).fetchone()
        assert '"unconfirmed"' in row[0]  # the earlier revision keeps the result it read


def test_a_changed_passage_set_under_the_same_record_shows_the_plan_stale(make):
    app, _, _ = make()
    with TestClient(app) as raw:
        client = session(raw)
        view = start(client)
        client.post(f"/api/citation-checks/{view['id']}/acquire")
        frozen(client, view["id"])
        url = f"/api/citation-checks/{view['id']}/preview"
        b = next(i for i in client.get(url).json()["selected"] if i["target"] == "b")
        assert (b["depth"], b["stale"]) == ("selected_passages", False)
        store = app.state.store
        page = store.passage(b["passage_ids"][0])
        with store.conn:
            store._insert_passage(page["source_version_id"], page["asset_id"], "pdf_page", 10, None, None, "chars:0-9",
                                  page["extraction_version"], "SYNTHETIC added page")
        assert next(i for i in client.get(url).json()["selected"] if i["target"] == "b")["stale"] is True


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


def test_a_busy_file_leaves_the_entry_pending_for_the_next_acquisition(make, monkeypatch):
    from deixis.documents import acquisition
    from deixis.workflow import text_retry
    app, _, _ = make()
    real = acquisition.acquire_for_source

    async def busy(*args, **kwargs):
        raise text_retry.FileBusy()

    with TestClient(app) as raw:
        client = session(raw)
        view = start(client)
        monkeypatch.setattr(acquisition, "acquire_for_source", busy)
        view = client.post(f"/api/citation-checks/{view['id']}/acquire").json()
        assert (entry(view, "b")["text"]["status"], entry(view, "b")["text"]["note"]) == ("pending", "file_busy")
        monkeypatch.setattr(acquisition, "acquire_for_source", real)
        view = client.post(f"/api/citation-checks/{view['id']}/acquire").json()
        assert entry(view, "b")["text"]["origin"] == "open_access"


# ---- review round 2 (Sol): a missing or mismatched identity result never reads as confirmed


def confirmed_draft(client):
    """A draft whose `a` reads the person's confirmed PDF, acquired."""
    view = start(client)
    upload(client, view, "a", A_PAGES)
    return client.post(f"/api/citation-checks/{view['id']}/acquire").json()


def test_an_entry_settled_before_identity_was_stored_is_unconfirmed_until_the_next_acquire_checks_it(make):
    app, net, _ = make()
    with TestClient(app) as raw:
        client = session(raw)
        view = confirmed_draft(client)
        store = app.state.store
        with store.conn:  # as a library migrated to 0006 holds it: the columns exist and are empty
            store.conn.execute("UPDATE citation_bib_entries SET text_identity = NULL, text_identity_asset_id = NULL,"
                               " text_identity_extraction = NULL, upload_identity = NULL WHERE draft_id = ?", (view["id"],))
        view = client.get(f"/api/citation-checks/{view['id']}").json()
        assert "identity_unconfirmed" in entry(view, "a")["flags"]
        assert pair_flags_of(view, "a") == [["identity_unconfirmed"], ["identity_unconfirmed"]]
        sent = len(net.seen)
        view = client.post(f"/api/citation-checks/{view['id']}/acquire").json()
        assert entry(view, "a")["text"]["identity"] == "doi" and len(net.seen) == sent  # read again, nothing sent
        assert entry(view, "a")["upload"]["identity"] == "doi" and entry(view, "a")["flags"] == []


def test_a_revision_without_an_identity_result_reads_unconfirmed_and_a_refreeze_checks_again(make):
    app, _, _ = make()
    with TestClient(app) as raw:
        client = session(raw)
        view = confirmed_draft(client)
        frozen(client, view["id"])
        store = app.state.store
        with store.conn:
            store.conn.execute("UPDATE citation_pairs SET plan_identity_json = NULL WHERE draft_id = ?", (view["id"],))
            store.conn.execute("UPDATE citation_bib_entries SET text_identity = NULL, text_identity_asset_id = NULL,"
                               " text_identity_extraction = NULL WHERE draft_id = ?", (view["id"],))
        view = client.get(f"/api/citation-checks/{view['id']}").json()
        assert pair_flags_of(view, "a") == [["identity_unconfirmed"], ["identity_unconfirmed"]]
        preview = client.get(f"/api/citation-checks/{view['id']}/preview").json()
        a = [i for i in preview["selected"] if i["target"] == "a"]
        assert [(i["flags"], i["stale"], i["identity"]) for i in a] == [(["identity_unconfirmed"], True, None)] * 2
        # A re-freeze over an entry with no stored result checks the selected passages' file itself.
        frozen(client, view["id"], refreeze=True)
        preview = client.get(f"/api/citation-checks/{view['id']}/preview").json()
        a = [i for i in preview["selected"] if i["target"] == "a"]
        assert [(i["flags"], i["stale"], i["identity"]["result"]) for i in a] == [([], False, "doi")] * 2


def test_a_stored_result_of_another_extraction_is_never_copied_into_a_plan(make):
    app, _, _ = make()
    with TestClient(app) as raw:
        client = session(raw)
        view = confirmed_draft(client)
        store = app.state.store
        with store.conn:  # b's current text checks unconfirmed; a stale `title` result of another file is stored
            store.conn.execute("UPDATE citation_bib_entries SET text_identity = 'title', text_identity_asset_id = 'ast_old',"
                               " text_identity_extraction = 'old' WHERE draft_id = ? AND entry_key = 'b'", (view["id"],))
        frozen(client, view["id"])
        item = next(i for i in client.get(f"/api/citation-checks/{view['id']}/preview").json()["selected"] if i["target"] == "b")
        assert (item["flags"], item["identity"]["result"], item["stale"]) == (["identity_unconfirmed"], "unconfirmed", False)
        # A revision whose kept result names another file than its passages' is unconfirmed and stale.
        with store.conn:
            store.conn.execute("UPDATE citation_pairs SET plan_identity_json = ? WHERE draft_id = ? AND target = 'a'",
                               ('{"result": "doi", "asset_id": "ast_old", "extraction_version": "old"}', view["id"]))
        a = [i for i in client.get(f"/api/citation-checks/{view['id']}/preview").json()["selected"] if i["target"] == "a"]
        assert [(i["flags"], i["stale"]) for i in a] == [(["identity_unconfirmed"], True)] * 2


def test_a_plan_frozen_before_fingerprints_reads_stale_instead_of_failing(make):
    app, _, _ = make()
    with TestClient(app) as raw:
        client = session(raw)
        view = confirmed_draft(client)
        frozen(client, view["id"])
        store = app.state.store
        with store.conn:
            store.conn.execute("UPDATE citation_pairs SET passage_plan_json = json_remove(passage_plan_json, '$.fingerprint')"
                               " WHERE draft_id = ? AND passage_plan_json IS NOT NULL", (view["id"],))
        response = client.get(f"/api/citation-checks/{view['id']}")
        assert response.status_code == 200
        assert all(p["plan"]["stale"] for _, p in pair_rows(response.json()) if p["status"] == "planned")


def test_text_counters_name_entries_and_unique_records_apart(make):
    app, _, _ = make()
    bib = BIB + b"@article{b2, title = {Void avoidance in sparse acoustic networks}, author = {Kim, Jae}, year = {2021},"\
                b" doi = {10.5555/syn.b}}\n"
    with TestClient(app) as raw:
        client = session(raw)
        view = start(client, b"Void avoidance \\cite{b}. Holes again \\cite{b2}.", bib)
        view = client.post(f"/api/citation-checks/{view['id']}/acquire").json()
        counters = view["counters"]
        assert counters["entries_with_text"]["full_text"] == 2 and counters["sources_with_text"]["full_text"] == 1
