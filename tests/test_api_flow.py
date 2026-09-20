"""Model-independent end-to-end checks of the local API, worker and persistence.

Uses the test-only FakeAdapter, mocked OpenAlex HTTP and a fake PDF fetcher. These
show workflow/persistence behavior (A–G deterministic parts), not model quality or
live provider access.
"""

import json
import time

import httpx
import pytest
from fastapi.testclient import TestClient

from deixis.api.app import create_app
from deixis.config import Settings
from deixis.documents import acquisition
from deixis.documents.fetch import FetchResult
from deixis.providers import scopus
from deixis.storage import db
from fakes import FakeAdapter, envelope, valid_response
from helpers import make_pdf

WORKS = [
    {
        "id": "https://openalex.org/W1", "doi": "https://doi.org/10.1/a", "display_name": "SYNTHETIC diffusion channel scheduling",
        "publication_year": 2021, "type": "article", "authorships": [], "ids": {"openalex": "https://openalex.org/W1"},
        "primary_location": {"version": "publishedVersion", "source": {"display_name": "Synthetic J"}},
        "best_oa_location": {"pdf_url": "https://example.org/w1.pdf", "version": "publishedVersion"},
        "abstract_inverted_index": {"We": [0], "schedule": [1], "molecule": [2], "releases.": [3]},
    },
    {
        "id": "https://openalex.org/W2", "doi": None, "display_name": "SYNTHETIC relay budget", "publication_year": 2019,
        "type": "article", "authorships": [], "ids": {}, "primary_location": {}, "best_oa_location": None,
        "abstract_inverted_index": {"Relays": [0], "share": [1], "nutrients.": [2]},
    },
    {
        "id": "https://openalex.org/W3", "doi": "https://doi.org/10.1/c", "display_name": "SYNTHETIC molecule schedule letter",
        "publication_year": 2017, "type": "article", "authorships": [], "ids": {},
        "primary_location": {"version": "publishedVersion"},
        "best_oa_location": {"pdf_url": "https://example.org/w3-manuscript.pdf", "version": "submittedVersion"},
        "abstract_inverted_index": {"Molecule": [0], "schedule": [1], "letter.": [2]},
    },
]


def openalex_client(status=200):
    def handler(request):
        if status != 200:
            return httpx.Response(status, headers={"retry-after": "60"})
        return httpx.Response(200, json={"meta": {"count": len(WORKS)}, "results": WORKS})
    return httpx.AsyncClient(transport=httpx.MockTransport(handler))


async def fake_fetch(url):
    return FetchResult("ok", data=make_pdf(["SYNTHETIC page one: molecule release schedule minimizes error."]), final_url=url, http_status=200)


def app_for(tmp_path, adapter=None, http_status=200):
    # These API tests script pause/cancel inside one call and assume the next source is not yet in flight.
    settings = Settings(data_dir=tmp_path / "data", port=8765, model_concurrency=1)
    return create_app(settings, adapters={"fake": adapter or FakeAdapter()}, http_client=openalex_client(http_status),
                      fetcher=fake_fetch, extra_hosts=("testserver",), trusted_clients=("testclient",))


def session(client):
    token = client.get("/api/session").json()["csrf_token"]
    client.headers["x-deixis-csrf"] = token
    return client


def wait_run(client, rid, run_id, statuses=("completed", "failed", "paused", "cancelled"), timeout=15):
    deadline = time.time() + timeout
    while time.time() < deadline:
        view = client.get(f"/api/researches/{rid}").json()
        run = next(r for r in view["runs"] if r["id"] == run_id)
        if run["status"] in statuses:
            return view, run
        time.sleep(0.1)
    raise AssertionError(f"run did not finish: {run}")


def create(client, **overrides):
    body = {"question": "How is molecule release scheduling optimized?", "model_connection": "fake",
            "requested_model": "fake-model", "effort": "quick"} | overrides
    response = client.post("/api/researches", json=body)
    assert response.status_code == 201, response.text
    return response.json()["research"]["id"]


def test_trash_restore_and_permanent_delete_with_evidence(tmp_path):
    app = app_for(tmp_path)
    with TestClient(app) as raw:
        client = session(raw)
        rid = create(client, source_scope="attached")
        uploaded = client.post(f"/api/researches/{rid}/uploads", files={"file": (
            "notes.pdf", make_pdf(["SYNTHETIC molecule notes"]), "application/pdf"
        )})
        assert uploaded.status_code == 201
        asset_id = uploaded.json()["sources"][0]["access"]["assets"][0]["id"]
        assert client.get(f"/api/researches/{rid}/assets/{asset_id}").status_code == 200
        asset_text = client.get(f"/api/researches/{rid}/assets/{asset_id}/text")
        assert asset_text.status_code == 200
        assert asset_text.json()["asset"]["id"] == asset_id
        assert "SYNTHETIC molecule notes" in asset_text.json()["passages"][0]["text"]

        assert client.delete(f"/api/researches/{rid}").json() == {"trashed": True}
        assert rid not in [r["id"] for r in client.get("/api/researches").json()]
        assert client.get(f"/api/researches/{rid}").status_code == 404
        assert client.get(f"/api/researches/{rid}/assets/{asset_id}").status_code == 404
        assert client.get(f"/api/researches/{rid}/assets/{asset_id}/text").status_code == 404
        assert client.get(f"/api/researches/{rid}/bibliography").status_code == 404
        assert client.get("/api/search", params={"q": "molecule"}).json() == {"researches": [], "sources": []}
        assert client.get("/api/trash").json()["researches"][0]["id"] == rid
        assert client.delete(f"/api/researches/{rid}").status_code == 404

        assert client.post(f"/api/trash/{rid}/restore").json() == {"restored": True}
        assert client.get(f"/api/researches/{rid}").status_code == 200
        assert client.delete(f"/api/trash/{rid}").status_code == 404
        assert client.delete(f"/api/researches/{rid}").status_code == 200
        result = client.delete(f"/api/trash/{rid}")
        assert result.status_code == 200, result.text
        assert result.json() == {"deleted": True, "files_not_removed": []}
        assert client.get("/api/trash").json() == {"researches": [], "tables": [], "sources": [], "templates": []}
        assert client.get(f"/api/researches/{rid}").status_code == 404
        assert client.get(f"/api/researches/{rid}/assets/{asset_id}").status_code == 404
        assert client.delete(f"/api/trash/{rid}").status_code == 404
        assert not list((tmp_path / "data" / "papers").glob("*.pdf"))
        assert app.state.store.conn.execute("PRAGMA foreign_key_check").fetchall() == []


def test_trash_rejects_active_run_and_purge_removes_model_provenance(tmp_path):
    app = app_for(tmp_path)
    with TestClient(app) as raw:
        client = session(raw)
        rid = create(client)
        queued = app.state.store.create_run(rid, "discovery", {}, None)
        assert client.delete(f"/api/researches/{rid}").status_code == 409
        assert client.get(f"/api/researches/{rid}").status_code == 200
        app.state.store.update_run(queued["id"], status="cancelled")
        run = client.post(f"/api/researches/{rid}/runs", json={"kind": "discovery"}).json()
        view, _ = wait_run(client, rid, run["id"])
        assert view["sources"]
        assert app.state.store.conn.execute("SELECT COUNT(*) FROM step_inputs WHERE research_id = ?", (rid,)).fetchone()[0] > 0
        assert client.delete(f"/api/researches/{rid}").status_code == 200
        result = client.delete(f"/api/trash/{rid}")
        assert result.status_code == 200, result.text
        assert app.state.store.conn.execute("SELECT COUNT(*) FROM step_inputs WHERE research_id = ?", (rid,)).fetchone()[0] == 0
        assert app.state.store.conn.execute("PRAGMA foreign_key_check").fetchall() == []


def test_permanent_delete_keeps_sources_shared_with_another_research(tmp_path):
    app = app_for(tmp_path)
    with TestClient(app) as raw:
        client = session(raw)
        first, second = create(client), create(client)
        for rid in (first, second):
            run = client.post(f"/api/researches/{rid}/runs", json={"kind": "discovery"}).json()
            wait_run(client, rid, run["id"])
        common = {s["source_version_id"] for s in client.get(f"/api/researches/{first}").json()["sources"]} & {
            s["source_version_id"] for s in client.get(f"/api/researches/{second}").json()["sources"]
        }
        assert common
        assert client.delete(f"/api/researches/{first}").status_code == 200
        response = client.delete(f"/api/trash/{first}")
        assert response.status_code == 200, response.text
        surviving = client.get(f"/api/researches/{second}")
        assert surviving.status_code == 200
        assert common <= {s["source_version_id"] for s in surviving.json()["sources"]}
        assert app.state.store.conn.execute("PRAGMA foreign_key_check").fetchall() == []


def test_institutional_access_is_checked_through_scopus_and_cached(tmp_path, monkeypatch):
    calls, route = [], ["192.168.0.2"]

    def handler(request):
        calls.append(request)
        return httpx.Response(200, json={"search-results": {}})
    monkeypatch.delenv("SCOPUS_API_KEY", raising=False)
    monkeypatch.setattr(scopus, "route_source", lambda: route[0])
    app = create_app(Settings(data_dir=tmp_path / "data", port=8765), adapters={"fake": FakeAdapter()},
                     http_client=httpx.AsyncClient(transport=httpx.MockTransport(handler)), fetcher=fake_fetch,
                     extra_hosts=("testserver",), trusted_clients=("testclient",))
    with TestClient(app) as client:
        assert client.get("/api/institutional-access").json()["status"] == "not_checked" and not calls
        monkeypatch.setenv("SCOPUS_API_KEY", "SECRET")
        assert client.get("/api/institutional-access?refresh=true").json() == {"status": "institutional", "via": "scopus"}
        assert client.get("/api/institutional-access").json()["status"] == "institutional"
        assert len(calls) == 1  # same route: answered from the cache
        route[0] = "10.10.9.22"  # a VPN started routing Scopus traffic
        client.get("/api/institutional-access")
        assert len(calls) == 2


def test_question_to_cited_answer_and_restart(tmp_path):
    adapter = FakeAdapter()
    with TestClient(app_for(tmp_path, adapter)) as client:
        session(client)
        rid = create(client, source_scope="attached_and_academic")
        first = client.post(f"/api/researches/{rid}/runs", json={"kind": "discovery"}, headers={"Idempotency-Key": "k1"}).json()
        again = client.post(f"/api/researches/{rid}/runs", json={"kind": "discovery"}, headers={"Idempotency-Key": "k1"}).json()
        assert first["id"] == again["id"]  # F: double submit does not create a second run

        view, run = wait_run(client, rid, first["id"])
        assert run["status"] == "completed", run
        assert view["counts"]["found"] == 3 and view["counts"]["unique"] == 3
        assert all(s["selection"]["origin"] == "model_proposal" for s in view["sources"] if s["version_role"] == "record")

        second = next(s for s in view["sources"] if "relay" in s["title"])
        stale = client.patch(f"/api/researches/{rid}/selections/{second['source_version_id']}",
                             json={"state": "excluded", "expected_version": second["selection"]["version"] - 1})
        assert stale.status_code == 409
        changed = client.patch(f"/api/researches/{rid}/selections/{second['source_version_id']}",
                               json={"state": "excluded", "expected_version": second["selection"]["version"], "reason": "not about scheduling"})
        assert changed.status_code == 200 and changed.json()["origin"] == "user"

        upload = client.post(f"/api/researches/{rid}/uploads", files={"file": ("my_notes.pdf", make_pdf(["SYNTHETIC uploaded molecule schedule notes."]), "application/pdf")})
        assert upload.status_code == 201

        answer_run = client.post(f"/api/researches/{rid}/runs", json={"kind": "answer"}).json()
        view, run = wait_run(client, rid, answer_run["id"])
        assert run["status"] == "completed", run
        answer = view["answers"][0]
        assert answer["status"] == "structurally_valid" and answer["applicability"] == "current"
        evidence = answer["claims"][0]["evidence"][0]
        assert evidence["source_version_id"] != second["source_version_id"]  # excluded source not given to the model
        given = adapter.calls[-1]
        assert second["title"] not in [s["title"] for s in given["sources"]]
        assert given["passages"][0]["passage_id"] == "psg_P0000001"  # the model sees short handles, the answer keeps record IDs

        passage = client.get(f"/api/researches/{rid}/passages/{evidence['passage_id']}").json()
        assert passage["source"]["id"] == evidence["source_version_id"]
        assert evidence["text_source"] == passage["text_source"]  # a quote says whether its text was read with OCR (D51)
        pdf_sources = [s for s in view["sources"] if s["access"]["assets"]]
        assert len(pdf_sources) == 3  # downloaded OA PDF + the letter's open manuscript (D48) + uploaded file
        letter, manuscript = [s for s in view["sources"] if "letter" in s["title"]]
        assert letter["access"]["oa_pdf_version"] == "submittedVersion" and not letter["access"]["assets"]  # other version not attached
        assert manuscript["access"]["assets"] and letter["answer_reads_version_id"] == manuscript["source_version_id"]
        asset_id = pdf_sources[0]["access"]["assets"][0]["id"]
        assert client.get(f"/api/researches/{rid}/assets/{asset_id}").headers["content-type"] == "application/pdf"
        before = view

    with TestClient(app_for(tmp_path)) as client:  # F: backend restart
        after = client.get(f"/api/researches/{rid}").json()
        assert after["answers"][0]["claims"] == before["answers"][0]["claims"]
        assert [s["selection"] for s in after["sources"]] == [s["selection"] for s in before["sources"]]

        session(client)
        other = create(client, question="Unrelated research B question")
        leak = client.get(f"/api/researches/{other}/passages/{evidence['passage_id']}")
        assert leak.status_code == 404  # T08: passage outside research B's corpus


def test_run_view_reports_the_plan_screening_notes_and_counting_step_outputs(tmp_path):
    with TestClient(app_for(tmp_path)) as raw:
        client = session(raw)
        rid = create(client)
        discovery = client.post(f"/api/researches/{rid}/runs", json={"kind": "discovery"}).json()
        view, run = wait_run(client, rid, discovery["id"])
        assert run["status"] == "completed", run
        plan = run["plan"]
        assert plan["question_interpretation"] == "fake interpretation" and plan["search_rationale"] == "fake"
        assert plan["scope_boundaries"] == ["fake"]
        assert plan["concepts"][0]["label"] == "molecular communication" and plan["concepts"][0]["synonyms"] == ["molecular communication", "diffusion channel"]
        assert [(q["provider_id"], q["query_text"], q["rationale"]) for q in plan["queries"]] == [
            ("openalex", '("molecular communication" OR "diffusion channel") AND optimization',
             'Core "molecular communication" with the method family "optimization"')]
        assert [n["text"] for n in run["screening_notes"]] == ["fake screening notes."]
        # A model step's output stays out of the view; the counting steps carry theirs.
        assert next(s for s in run["steps"] if s["kind"] == "model:search_plan")["output"] is None

        answer_run = client.post(f"/api/researches/{rid}/runs", json={"kind": "answer"}).json()
        view, run = wait_run(client, rid, answer_run["id"])
        assert run["status"] == "completed", run
        assert run["plan"] is None and run["screening_notes"] == []
        fetched = next(s for s in run["steps"] if s["kind"] == "fetch_pdf" and s["status"] == "succeeded")
        assert fetched["output"]["page_count"] == 1 and fetched["output"]["passage_count"] >= 1
        assert fetched["output"]["asset_id"] in [a["id"] for s in view["sources"] for a in s["access"]["assets"]]


def test_pdf_discovery_is_visible_and_user_can_attach_pdf_to_existing_source(tmp_path):
    with TestClient(app_for(tmp_path)) as raw:
        client = session(raw)
        rid = create(client)
        run = client.post(f"/api/researches/{rid}/runs", json={"kind": "discovery"}).json()
        view, completed = wait_run(client, rid, run["id"])
        assert completed["status"] == "completed"
        source = next(s for s in view["sources"] if s["doi"])

        found = client.post(f"/api/researches/{rid}/sources/{source['source_version_id']}/pdf-discovery")
        assert found.status_code == 200, found.text
        refreshed = next(s for s in found.json()["sources"] if s["source_version_id"] == source["source_version_id"])
        assert [d["provider"] for d in refreshed["access"]["pdf_discoveries"]] == ["unpaywall", "openalex", "crossref", "core", "web_search"]

        attached = client.post(
            f"/api/researches/{rid}/sources/{source['source_version_id']}/uploads",
            files={"file": ("author-copy.pdf", make_pdf(["SYNTHETIC author copy"]), "application/pdf")},
        )
        assert attached.status_code == 201, attached.text
        same = next(s for s in attached.json()["sources"] if s["source_version_id"] == source["source_version_id"])
        assert same["access"]["assets"][0]["origin"] == "user_upload"


def test_version_uncertain_pdf_candidate_is_attached_only_when_the_user_confirms_it(tmp_path):
    fetched = []

    async def fetcher(url):
        fetched.append(url)
        if "gated" in url:
            return FetchResult("http_error", final_url=url, http_status=403)
        return FetchResult("ok", data=make_pdf(["SYNTHETIC repository copy"]), final_url=url, http_status=200)

    app = create_app(Settings(data_dir=tmp_path / "data", port=8765), adapters={"fake": FakeAdapter()},
                     http_client=openalex_client(), fetcher=fetcher, extra_hosts=("testserver",), trusted_clients=("testclient",))
    with TestClient(app) as raw:
        client = session(raw)
        rid = create(client)
        run = client.post(f"/api/researches/{rid}/runs", json={"kind": "discovery"}).json()
        view, completed = wait_run(client, rid, run["id"])
        assert completed["status"] == "completed"
        source = next(s for s in view["sources"] if s["doi"] == "10.1/c")
        svid = source["source_version_id"]
        assert not source["access"]["assets"]
        store = app.state.store
        discovery = store.record_pdf_discovery(rid, svid, "web_search", '"SYNTHETIC molecule schedule letter"',
                                               acquisition.Lookup("completed", []))
        store.record_pdf_candidates(svid, discovery, [
            acquisition.Candidate("web_search", "https://gated.example/copy.pdf", None, None, None, "title_verified", "uncertain"),
            acquisition.Candidate("web_search", "https://repo.example/copy.pdf", None, None, None, "title_verified", "uncertain"),
            acquisition.Candidate("openalex", "https://repo.example/manuscript.pdf", None, "submittedVersion", None,
                                  "doi_verified", "different"),
            acquisition.Candidate("web_search", "https://other.example/unrelated.pdf", None, None, None, "unverified", "uncertain"),
        ])
        ids = {c["candidate_url"]: c["id"] for c in store.pdf_candidates(svid)}
        attach = lambda url: client.post(f"/api/researches/{rid}/sources/{svid}/pdf-candidates/{ids[url]}/attach")
        before = len(fetched)

        assert attach("https://repo.example/manuscript.pdf").status_code == 422
        assert attach("https://other.example/unrelated.pdf").status_code == 422
        assert len(fetched) == before

        gated = attach("https://gated.example/copy.pdf")
        assert gated.status_code == 502 and "HTTP 403" in gated.json()["detail"]
        refreshed = next(s for s in client.get(f"/api/researches/{rid}").json()["sources"] if s["source_version_id"] == svid)
        assert not refreshed["access"]["assets"]
        # A stored web result under another paper's title stays refusable but is not listed.
        assert "https://other.example/unrelated.pdf" not in {c["candidate_url"] for c in refreshed["access"]["pdf_candidates"]}

        attached = attach("https://repo.example/copy.pdf")
        assert attached.status_code == 200, attached.text
        same = next(s for s in attached.json()["sources"] if s["source_version_id"] == svid)
        assert [a["origin"] for a in same["access"]["assets"]] == ["user_upload"]
        outcomes = {c["candidate_url"]: (c["access_status"], c["http_status"]) for c in same["access"]["pdf_candidates"]}
        assert outcomes["https://gated.example/copy.pdf"] == ("http_error", 403)
        assert outcomes["https://repo.example/copy.pdf"] == ("downloaded", 200)

        assert attach("https://gated.example/copy.pdf").status_code == 409
        assert client.post(f"/api/researches/{rid}/sources/{svid}/pdf-candidates/pdc_missing/attach").status_code == 404


@pytest.mark.parametrize("copy_found", [True, False])
def test_refused_link_leads_to_one_lookup_for_another_copy_and_is_not_requested_again(tmp_path, monkeypatch, copy_found):
    monkeypatch.setenv("DEIXIS_CONTACT_EMAIL", "")  # Unpaywall and CORE are not configured, so they send nothing
    monkeypatch.setenv("CORE_API_KEY", "")
    fetched, lookups = [], []

    def handler(request):
        if request.url.host == "api.openalex.org" and "doi.org" in request.url.path:
            lookups.append(request.url.host)
            return httpx.Response(200, json={"doi": "https://doi.org/10.1/a", "locations": [
                {"pdf_url": "https://repository.example/w1.pdf", "version": "publishedVersion"}]})
        if request.url.host == "api.crossref.org":
            lookups.append(request.url.host)
            return httpx.Response(404)
        return httpx.Response(200, json={"meta": {"count": len(WORKS)}, "results": WORKS})

    async def fetcher(url):
        fetched.append(url)
        if copy_found and "repository" in url:
            return FetchResult("ok", data=make_pdf(["SYNTHETIC repository copy"]), final_url=url, http_status=200)
        return FetchResult("http_error", final_url=url, http_status=403)

    app = create_app(Settings(data_dir=tmp_path / "data", port=8765), adapters={"fake": FakeAdapter()},
                     http_client=httpx.AsyncClient(transport=httpx.MockTransport(handler)), fetcher=fetcher,
                     extra_hosts=("testserver",), trusted_clients=("testclient",))
    with TestClient(app) as raw:
        client = session(raw)
        rid = create(client)
        discovery = client.post(f"/api/researches/{rid}/runs", json={"kind": "discovery"}).json()
        wait_run(client, rid, discovery["id"])
        answer = client.post(f"/api/researches/{rid}/runs", json={"kind": "answer"}).json()
        view, run = wait_run(client, rid, answer["id"])
        assert run["status"] == "completed", run

        refused = next(s for s in run["steps"] if s["kind"] == "fetch_pdf")
        assert (refused["status"], refused["error_code"], refused["error"]["http_status"]) == ("failed", "fetch_http_error", 403)
        other = next(s for s in run["steps"] if s["kind"] == "pdf_other_copy")
        source = next(s for s in view["sources"] if s["doi"] == "10.1/a")
        # The automatic lookup leaves web search to the user's own "Find PDF".
        assert [d["provider"] for d in source["access"]["pdf_discoveries"]] == ["unpaywall", "openalex", "crossref", "core"]
        assert source["access"]["fetch"]["http_status"] == 403
        if copy_found:
            assert other["status"] == "succeeded" and other["output"]["page_count"] == 1
            assert [a["origin"] for a in source["access"]["assets"]] == ["download"]
        else:
            assert (other["status"], other["error_code"]) == ("failed", "no_other_copy")
            assert not source["access"]["assets"] and source["access"]["other_copy"]["status"] == "failed"
        # The letter's published record has no open PDF, so its open manuscript is retrieved for the answer (D48).
        assert sorted(fetched) == ["https://example.org/w1.pdf", "https://example.org/w3-manuscript.pdf", "https://repository.example/w1.pdf"]
        assert lookups == ["api.openalex.org", "api.crossref.org"]

        again = client.post(f"/api/researches/{rid}/runs", json={"kind": "answer"}).json()
        _, rerun = wait_run(client, rid, again["id"])
        assert rerun["status"] == "completed", rerun
        assert not [s for s in rerun["steps"] if s["kind"] in ("fetch_pdf", "pdf_other_copy")]
        assert len(fetched) == 3 and len(lookups) == 2  # neither the refused link nor the lookup is repeated


def test_invalid_output_is_repaired_once_then_kept_as_unverified_draft(tmp_path):
    def bad(si):
        if si["task_type"] != "grounded_answer":
            return valid_response(si)
        return json.dumps(envelope(si, "deixis.grounded_answer_draft.v3") | {
            "title": "Synthetic evidence for release scheduling and optimization in constrained molecular communication networks",
            "answer_language": "en",
            "claims": [{"claim_label": "c1", "section": "Overview", "text": "It has been reported that X was invented.", "support_type": "source_stated", "passage_ids": ["psg_INVENTED0001"]}],
            "citation_anchors": [],
            "limitations": [], "unanswered_aspects": [], "capability_notice": None,
        })

    adapter = FakeAdapter(bad)
    with TestClient(app_for(tmp_path, adapter)) as client:
        session(client)
        rid = create(client, source_scope="attached")
        client.post(f"/api/researches/{rid}/uploads", files={"file": ("a.pdf", make_pdf(["SYNTHETIC molecule text"]), "application/pdf")})
        run = client.post(f"/api/researches/{rid}/runs", json={"kind": "answer"}).json()
        view, run = wait_run(client, rid, run["id"])
        answer = view["answers"][0]
        assert answer["status"] == "unverified_draft" and answer["claims"] == []
        assert {i["code"] for i in answer["validation"]["issues"]} == {"unknown_passage_id"}
        assert len(adapter.calls) == 2  # original + one repair
        assert run["usage"]["model_calls"] == 2


def test_missing_anchor_is_repaired_before_the_answer_is_published(tmp_path):
    answer_attempts = 0

    def missing_then_valid(si):
        nonlocal answer_attempts
        draft = json.loads(valid_response(si))
        if si["task_type"] == "grounded_answer":
            answer_attempts += 1
            if answer_attempts == 1:
                draft["citation_anchors"] = []
        return json.dumps(draft)

    adapter = FakeAdapter(missing_then_valid)
    with TestClient(app_for(tmp_path, adapter)) as client:
        session(client)
        rid = create(client, source_scope="attached")
        client.post(f"/api/researches/{rid}/uploads", files={"file": ("a.pdf", make_pdf(["SYNTHETIC molecule text"]), "application/pdf")})
        run = client.post(f"/api/researches/{rid}/runs", json={"kind": "answer"}).json()
        view, run = wait_run(client, rid, run["id"])
        answer = view["answers"][0]
        assert answer["status"] == "structurally_valid"
        assert all(evidence["anchor_text"] for claim in answer["claims"] for evidence in claim["evidence"])
        assert [task for task, _, _ in adapter.sent].count("grounded_answer") == 2
        assert run["usage"]["model_calls"] == 2


def test_a_final_draft_with_only_repeated_quotes_and_unquoted_extra_citations_is_published_without_them(tmp_path):
    def sloppy(si):
        draft = json.loads(valid_response(si))
        if si["task_type"] == "grounded_answer" and len(si["passages"]) > 1:
            first, second = si["passages"][0], si["passages"][1]
            draft["claims"][0]["passage_ids"].append(second["passage_id"])  # cited without a quote
            draft["citation_anchors"].append(dict(draft["citation_anchors"][0]))  # the same quote twice
            draft["citation_anchors"].append({"claim_label": "c1", "passage_id": "psg_P" + first["passage_id"].removeprefix("psg_P").rjust(8, "0"),
                                              "quote": draft["citation_anchors"][0]["quote"]})  # a handle with an extra zero
        return json.dumps(draft)

    adapter = FakeAdapter(sloppy)
    with TestClient(app_for(tmp_path, adapter)) as client:
        session(client)
        rid = create(client, source_scope="attached")
        client.post(f"/api/researches/{rid}/uploads", files={"file": ("a.pdf", make_pdf(["SYNTHETIC molecule text one", "SYNTHETIC molecule text two"]), "application/pdf")})
        run = client.post(f"/api/researches/{rid}/runs", json={"kind": "answer"}).json()
        view, run = wait_run(client, rid, run["id"])
        answer = view["answers"][0]
        assert [task for task, _, _ in adapter.sent].count("grounded_answer") == 2  # the repair is still asked for first
        assert answer["status"] == "structurally_valid"
        assert [len(claim["evidence"]) for claim in answer["claims"]] == [1]
        assert all(evidence["anchor_text"] for claim in answer["claims"] for evidence in claim["evidence"])
        warnings = {w["code"] for w in answer["validation"]["warnings"]}
        assert {"duplicate_citation_anchor_ignored", "citation_without_quote_removed"} <= warnings


def test_long_answer_title_is_repaired_and_the_valid_title_replaces_the_question(tmp_path):
    attempts = 0

    def long_then_valid(si):
        nonlocal attempts
        draft = json.loads(valid_response(si))
        if si["task_type"] == "grounded_answer":
            attempts += 1
            if attempts == 1:
                draft["title"] = " ".join(f"word{n}" for n in range(21))
        return json.dumps(draft)

    adapter = FakeAdapter(long_then_valid)
    with TestClient(app_for(tmp_path, adapter)) as client:
        session(client)
        rid = create(client, source_scope="attached")
        original = client.get(f"/api/researches/{rid}").json()["research"]["title"]
        client.post(f"/api/researches/{rid}/uploads", files={"file": ("a.pdf", make_pdf(["SYNTHETIC molecule text"]), "application/pdf")})
        run = client.post(f"/api/researches/{rid}/runs", json={"kind": "answer"}).json()
        view, run = wait_run(client, rid, run["id"])
        assert view["answers"][0]["status"] == "structurally_valid"
        assert view["research"]["title"] == "Synthetic evidence for release scheduling and optimization in constrained molecular communication networks"
        assert view["research"]["title"] != original
        assert attempts == 2 and run["usage"]["model_calls"] == 2


def test_invented_locator_in_claim_text_is_repaired_or_never_shown_as_cited(tmp_path):
    # B: the first draft asserts a page and an equation; the repair attempt removes them.
    def with_claim_text(si, text):
        draft = json.loads(valid_response(si))
        if si["task_type"] == "grounded_answer" and text:
            draft["claims"][0]["text"] = text
        return json.dumps(draft)

    answers_given = []

    def first_invents(si):
        answers_given.append(si["task_type"])
        invented = si["task_type"] == "grounded_answer" and answers_given.count("grounded_answer") == 1
        return with_claim_text(si, "Equation 4 on page 12 proves the schedule is optimal." if invented else None)

    adapter = FakeAdapter(first_invents)
    with TestClient(app_for(tmp_path, adapter)) as client:
        session(client)
        rid = attached_research(client)
        run = client.post(f"/api/researches/{rid}/runs", json={"kind": "answer"}).json()
        view, run = wait_run(client, rid, run["id"])
        answer = view["answers"][0]
        assert len(adapter.calls) == 2 and answer["status"] == "structurally_valid"
        assert all("page 12" not in c["text"].lower() for c in answer["claims"])

    always = FakeAdapter(lambda si: with_claim_text(si, "It has been reported on page 12 that X holds."))
    with TestClient(app_for(tmp_path / "second", always)) as client:
        session(client)
        rid = attached_research(client)
        run = client.post(f"/api/researches/{rid}/runs", json={"kind": "answer"}).json()
        view, _ = wait_run(client, rid, run["id"])
        answer = view["answers"][0]
        assert answer["status"] == "unverified_draft" and answer["claims"] == []
        assert {i["code"] for i in answer["validation"]["issues"]} == {"locator_in_claim_text"}


def test_attached_only_scope_never_searches(tmp_path):
    with TestClient(app_for(tmp_path)) as client:
        session(client)
        rid = create(client, source_scope="attached")
        assert client.post(f"/api/researches/{rid}/runs", json={"kind": "discovery"}).status_code == 422
        view = client.get(f"/api/researches/{rid}").json()
        assert view["search_runs"] == [] and view["scope"]["providers"] == []


def test_selected_pdf_seed_is_frozen_for_the_search_plan_and_revisions(tmp_path):
    adapter = FakeAdapter()
    app = app_for(tmp_path, adapter)
    with TestClient(app) as client:
        session(client)
        rid = create(client, source_scope="attached_and_academic", seed_mode="uploaded_seed")
        assert client.post(f"/api/researches/{rid}/runs", json={"kind": "discovery"}).status_code == 422
        first = client.post(f"/api/researches/{rid}/uploads", files={"file": (
            "seed-notes.pdf", make_pdf(["SYNTHETIC molecule release model and scheduling objective.",
                                        "SYNTHETIC channel parameters and constrained optimization."]), "application/pdf"
        )})
        assert first.status_code == 201, first.text
        first_view = first.json()
        seed_id = first_view["uploaded_source_version_id"]
        selection_revision = first_view["research"]["selection_revision"]
        selected = client.post(f"/api/researches/{rid}/seed", json={
            "source_version_id": seed_id, "expected_version": first_view["research"]["version"]
        })
        assert selected.status_code == 200, selected.text
        view = selected.json()
        assert view["scope"]["revision"] == 2 and view["scope"]["seed_status"] == "ready"
        assert view["scope"]["seed"]["source_version_id"] == seed_id
        assert "passages" not in view["scope"]["seed"]
        assert view["research"]["selection_revision"] == selection_revision
        same = client.post(f"/api/researches/{rid}/seed", json={
            "source_version_id": seed_id, "expected_version": view["research"]["version"]
        }).json()
        assert same["scope"]["revision"] == 2

        run = client.post(f"/api/researches/{rid}/runs", json={"kind": "discovery"}).json()
        _, result = wait_run(client, rid, run["id"])
        assert result["status"] == "completed", result
        payload_row = app.state.store.conn.execute(
            "SELECT payload_json FROM step_inputs WHERE run_id = ? AND task_type = 'search_plan' ORDER BY rowid LIMIT 1",
            (run["id"],),
        ).fetchone()
        payload = json.loads(payload_row["payload_json"])
        assert [source["source_id"] for source in payload["sources"]] == [seed_id]
        assert payload["passages"] and all(p["source_id"] == seed_id for p in payload["passages"])
        assert "SYNTHETIC molecule release" in payload["passages"][0]["text"]
        assert app.state.store.scope(rid)["seed_snapshot"]["asset_sha256"] == view["scope"]["seed"]["asset_sha256"]

        asset_id = view["scope"]["seed"]["asset_id"]
        removed = client.delete(f"/api/researches/{rid}/sources/{seed_id}/assets/{asset_id}")
        assert removed.status_code == 200, removed.text
        stale = client.get(f"/api/researches/{rid}").json()
        assert stale["scope"]["seed_status"] == "stale"
        assert client.post(f"/api/researches/{rid}/runs", json={"kind": "discovery"}).status_code == 409
        revised = client.post(f"/api/researches/{rid}/scope", json={
            "question": "SYNTHETIC revised scheduling question", "expected_version": stale["research"]["version"]
        })
        assert revised.status_code == 200, revised.text
        assert revised.json()["scope"]["seed_status"] == "missing"
        assert app.state.store.scope(rid, 2)["seed_snapshot"]["asset_id"] == asset_id
        assert client.post(f"/api/researches/{rid}/runs", json={"kind": "discovery"}).status_code == 422


def test_seed_requires_readable_uploaded_pdf_and_rejects_other_scopes(tmp_path):
    with TestClient(app_for(tmp_path)) as client:
        session(client)
        rejected = client.post("/api/researches", json={
            "question": "SYNTHETIC seed question", "source_scope": "academic", "seed_mode": "uploaded_seed",
            "model_connection": "fake", "requested_model": "fake-model"
        })
        assert rejected.status_code == 422
        rid = create(client, source_scope="attached_and_academic", seed_mode="uploaded_seed")
        uploaded = client.post(f"/api/researches/{rid}/uploads", files={"file": (
            "scan.pdf", make_pdf([""]), "application/pdf"
        )}).json()
        response = client.post(f"/api/researches/{rid}/seed", json={
            "source_version_id": uploaded["uploaded_source_version_id"],
            "expected_version": uploaded["research"]["version"]
        })
        assert response.status_code == 422
        assert client.get(f"/api/researches/{rid}").json()["scope"]["seed_status"] == "missing"


def test_user_can_edit_research_title(tmp_path):
    with TestClient(app_for(tmp_path)) as client:
        session(client)
        rid = create(client)
        view = client.get(f"/api/researches/{rid}").json()
        updated = client.post(f"/api/researches/{rid}/title", json={
            "title": "SYNTHETIC custom project title",
            "expected_version": view["research"]["version"],
        })
        assert updated.status_code == 200, updated.text
        payload = updated.json()
        assert payload["research"]["title"] == "SYNTHETIC custom project title"
        assert payload["research"]["version"] == view["research"]["version"] + 1
        assert client.get(f"/api/researches/{rid}").json()["research"]["title"] == "SYNTHETIC custom project title"


def test_provider_rate_limit_pauses_without_fallback(tmp_path):
    with TestClient(app_for(tmp_path, http_status=429)) as client:
        session(client)
        rid = create(client)
        run = client.post(f"/api/researches/{rid}/runs", json={"kind": "discovery"}).json()
        view, run = wait_run(client, rid, run["id"])
        assert run["status"] == "paused" and run["pause_reason"] == "provider_rate_limited"
        assert view["search_runs"][0]["status"] == "rate_limited"
        assert view["counts"]["found"] == 0  # E: not shown as zero results of a completed search


def test_model_not_ready_pauses_run(tmp_path):
    with TestClient(app_for(tmp_path, FakeAdapter(ready=False))) as client:
        session(client)
        rid = create(client)
        run = client.post(f"/api/researches/{rid}/runs", json={"kind": "discovery"}).json()
        _, run = wait_run(client, rid, run["id"])
        assert (run["status"], run["pause_reason"]) == ("paused", "model_connection_not_ready")


def test_backend_crash_mid_run_is_recovered_as_paused_then_resumable(tmp_path):
    app = app_for(tmp_path)
    with TestClient(app) as client:
        session(client)
        rid = create(client, source_scope="attached")
        client.post(f"/api/researches/{rid}/uploads", files={"file": ("a.pdf", make_pdf(["SYNTHETIC molecule text"]), "application/pdf")})
    conn = db.connect(tmp_path / "data" / "library.sqlite")
    conn.execute(
        "INSERT INTO runs (id, research_id, scope_revision, kind, status, stage, budget_json, created_at, updated_at)"
        " VALUES ('run_CRASHED000001', ?, 1, 'answer', 'running', 'answer', ?, 'now', 'now')",
        (rid, json.dumps({"max_model_calls": 4, "max_provider_requests": 2, "max_candidates": 15, "max_answer_passages": 8})),
    )
    conn.execute(
        "INSERT INTO run_steps (id, run_id, operation_key, kind, status, attempt) VALUES ('stp_CRASHED000001', 'run_CRASHED000001', 'grounded_answer', 'model:grounded_answer', 'running', 1)"
    )
    conn.close()

    with TestClient(app_for(tmp_path)) as client:
        session(client)
        assert client.get("/api/health").json()["recovered"] == {"runs": 1, "steps": 1, "model_sessions": 0}
        view = client.get(f"/api/researches/{rid}").json()
        run = view["runs"][0]
        assert (run["status"], run["pause_reason"]) == ("paused", "backend_restarted")
        assert run["steps"][0]["status"] == "outcome_unknown"
        client.post(f"/api/runs/{run['id']}/resume")
        view, run = wait_run(client, rid, run["id"])
        assert run["status"] == "completed" and view["answers"][0]["status"] == "structurally_valid"


def test_second_instance_does_not_start_a_worker(tmp_path):
    with TestClient(app_for(tmp_path)) as first, TestClient(app_for(tmp_path)) as second:
        assert first.get("/api/health").json()["worker"] == "owner"
        assert second.get("/api/health").json()["worker"] == "not_owner"


def test_waiting_instance_takes_over_after_owner_stops(tmp_path):
    first = TestClient(app_for(tmp_path)).__enter__()
    second = TestClient(app_for(tmp_path)).__enter__()
    try:
        assert second.get("/api/health").json()["worker"] == "not_owner"
        first.__exit__(None, None, None)  # e.g. a restart that starts before the old process has exited
        deadline = time.time() + 5
        while second.get("/api/health").json()["worker"] != "owner" and time.time() < deadline:
            time.sleep(0.1)
        assert second.get("/api/health").json()["worker"] == "owner"
    finally:
        second.__exit__(None, None, None)


def attached_research(client):
    rid = create(client, source_scope="attached")
    client.post(f"/api/researches/{rid}/uploads", files={"file": ("a.pdf", make_pdf(["SYNTHETIC molecule release schedule"]), "application/pdf")})
    return rid


def test_research_requires_an_explicit_listed_model(tmp_path):
    with TestClient(app_for(tmp_path, FakeAdapter(models=["fake-model"]))) as client:
        session(client)
        body = {"question": "How is molecule release scheduling optimized?", "model_connection": "fake"}
        assert client.post("/api/researches", json=body).status_code == 422
        assert client.post("/api/researches", json=body | {"requested_model": "unlisted-model"}).status_code == 422
        assert client.post("/api/researches", json=body | {"requested_model": "fake-model"}).status_code == 201


def test_reasoning_effort_must_be_listed_and_is_sent_with_every_model_step(tmp_path):
    adapter = FakeAdapter(models=["fake-model"], efforts=["low", "high"])
    with TestClient(app_for(tmp_path, adapter)) as client:
        session(client)
        body = {"question": "How is molecule release scheduling optimized?", "model_connection": "fake", "requested_model": "fake-model"}
        assert client.post("/api/researches", json=body | {"reasoning_effort": "xhigh"}).status_code == 422
        rid = create(client, source_scope="attached", reasoning_effort="high")
        client.post(f"/api/researches/{rid}/uploads", files={"file": ("a.pdf", make_pdf(["SYNTHETIC molecule text"]), "application/pdf")})
        run = client.post(f"/api/researches/{rid}/runs", json={"kind": "answer"}).json()
        view, run = wait_run(client, rid, run["id"])
        assert run["status"] == "completed", run
        assert view["scope"]["reasoning_effort"] == "high"
        assert adapter.sent_efforts and set(adapter.sent_efforts) == {"high"}


def test_output_from_another_model_is_recorded_but_not_used(tmp_path):
    adapter = FakeAdapter(resolved_model="some-other-model")
    with TestClient(app_for(tmp_path, adapter)) as client:
        session(client)
        rid = attached_research(client)
        run = client.post(f"/api/researches/{rid}/runs", json={"kind": "answer"}).json()
        view, run = wait_run(client, rid, run["id"])
        assert (run["status"], run["pause_reason"]) == ("paused", "model_mismatch")
        assert view["answers"] == [] and len(adapter.calls) == 1


def test_pause_during_final_model_call_applies_result_only_after_resume(tmp_path):
    holder = {}

    def responder(si):
        if si["task_type"] == "grounded_answer" and not holder.get("paused"):
            holder["paused"] = True
            holder["app"].state.store.update_run(si["run_id"], event="run_pause_requested", status="pause_requested",
                                                 pause_reason="user_requested")
        return valid_response(si)

    adapter = FakeAdapter(responder)
    holder["app"] = app = app_for(tmp_path, adapter)
    with TestClient(app) as client:
        session(client)
        rid = attached_research(client)
        run = client.post(f"/api/researches/{rid}/runs", json={"kind": "answer"}).json()
        view, run = wait_run(client, rid, run["id"])
        assert (run["status"], run["pause_reason"]) == ("paused", "user_requested") and view["answers"] == []
        client.post(f"/api/runs/{run['id']}/resume")
        view, run = wait_run(client, rid, run["id"])
        assert run["status"] == "completed" and len(view["answers"]) == 1
        assert len(adapter.calls) == 1  # the recorded output is applied; the model is not called again


def test_cancel_during_model_call_keeps_output_unapplied(tmp_path):
    holder = {}

    def responder(si):
        if si["task_type"] == "grounded_answer":
            holder["app"].state.store.update_run(si["run_id"], event="run_cancelled", status="cancelled", pause_reason="user_cancelled")
        return valid_response(si)

    holder["app"] = app = app_for(tmp_path, FakeAdapter(responder))
    with TestClient(app) as client:
        session(client)
        rid = attached_research(client)
        run = client.post(f"/api/researches/{rid}/runs", json={"kind": "answer"}).json()
        view, run = wait_run(client, rid, run["id"])
        assert run["status"] == "cancelled" and view["answers"] == []
        assert next(s for s in run["steps"] if s["kind"] == "model:grounded_answer")["status"] == "succeeded"


def test_selection_change_marks_existing_answer_stale(tmp_path):
    with TestClient(app_for(tmp_path)) as client:
        session(client)
        rid = attached_research(client)
        run = client.post(f"/api/researches/{rid}/runs", json={"kind": "answer"}).json()
        view, _ = wait_run(client, rid, run["id"])
        assert view["answers"][0]["applicability"] == "current"
        source = view["sources"][0]
        client.patch(f"/api/researches/{rid}/selections/{source['source_version_id']}",
                     json={"state": "excluded", "expected_version": source["selection"]["version"]})
        assert client.get(f"/api/researches/{rid}").json()["answers"][0]["applicability"] == "stale_selection"


def test_reports_keep_their_own_number_and_title_and_all_are_listed(tmp_path):
    app = app_for(tmp_path)
    with TestClient(app) as client:
        session(client)
        rid = attached_research(client)
        first = client.post(f"/api/researches/{rid}/runs", json={"kind": "answer"}).json()
        view, _ = wait_run(client, rid, first["id"])
        store = app.state.store
        run_id = first["id"]
        # A clarification takes no number, and a later title change does not rename the saved report.
        store.save_answer(rid, run_id, None, None, 1, "clarification", {"question": "Which network?"}, {})
        store.conn.execute("UPDATE answers SET draft_json = json_set(draft_json, '$.title', 'Saved title') WHERE status = 'structurally_valid'")
        for _ in range(11):
            later = store.create_run(rid, "answer", {}, None)["id"]
            store.update_run(later, status="cancelled")
            store.save_answer(rid, later, None, None, 1, "structurally_valid", {"title": "Later title", "claims": []}, {})
        answers = client.get(f"/api/researches/{rid}").json()["answers"]
        assert len(answers) == 13  # older answers are no longer cut off at ten
        reports = [a for a in answers if a["status"] == "structurally_valid"]
        assert [a["report_version"] for a in reports] == list(range(12, 0, -1))
        assert reports[-1]["report_title"] == "Saved title" and reports[0]["report_title"] == "Later title"
        assert next(a for a in answers if a["status"] == "clarification")["report_version"] is None


def test_resume_after_crash_following_saved_answer_does_not_duplicate_it(tmp_path):
    with TestClient(app_for(tmp_path)) as client:
        session(client)
        rid = attached_research(client)
        run = client.post(f"/api/researches/{rid}/runs", json={"kind": "answer"}).json()
        wait_run(client, rid, run["id"])
    conn = db.connect(tmp_path / "data" / "library.sqlite")
    conn.execute("UPDATE runs SET status = 'running' WHERE id = ?", (run["id"],))  # crash before completion was recorded
    conn.close()

    adapter = FakeAdapter()
    with TestClient(app_for(tmp_path, adapter)) as client:
        session(client)
        client.post(f"/api/runs/{run['id']}/resume")
        view, resumed = wait_run(client, rid, run["id"], statuses=("completed", "failed", "cancelled"))
        assert resumed["status"] == "completed"
        assert len(view["answers"]) == 1 and adapter.calls == []


def test_question_revision_during_discovery_stops_applying_its_results(tmp_path):
    holder = {}

    def responder(si):
        if si["task_type"] == "search_plan":
            store = holder["app"].state.store
            store.revise_scope(si["research_id"], store.research(si["research_id"])["version"], "A revised molecule release question", None)
        return valid_response(si)

    adapter = FakeAdapter(responder)
    holder["app"] = app = app_for(tmp_path, adapter)
    with TestClient(app) as client:
        session(client)
        rid = create(client)
        run = client.post(f"/api/researches/{rid}/runs", json={"kind": "discovery"}).json()
        view, run = wait_run(client, rid, run["id"])
        assert (run["status"], run["pause_reason"]) == ("cancelled", "scope_revised")
        assert view["search_runs"] == [] and view["sources"] == []
        assert [c["task_type"] for c in adapter.calls] == ["search_plan"]


def test_submitted_and_published_versions_stay_separate_versions_of_one_work(tmp_path):
    # C: one work family, separate versions; evidence stays with the inspected version; versions are not counted twice.
    def cite_manuscript(si):
        if si["task_type"] != "grounded_answer":
            return valid_response(si)
        manuscript = next(s["source_id"] for s in si["sources"] if s["version_label"] == "submittedVersion")
        passage = next(p for p in si["passages"] if p["source_id"] == manuscript)
        return valid_response(si | {"passages": [passage]})

    adapter = FakeAdapter(cite_manuscript)
    with TestClient(app_for(tmp_path, adapter)) as client:
        session(client)
        rid = create(client)
        run = client.post(f"/api/researches/{rid}/runs", json={"kind": "discovery"}).json()
        view, _ = wait_run(client, rid, run["id"])
        assert len(view["sources"]) == 4 and view["counts"]["unique"] == 3
        record, manuscript = [s for s in view["sources"] if "letter" in s["title"]]  # the other version follows its record
        assert (record["version_role"], manuscript["version_role"]) == ("record", "other_version")
        assert record["work_id"] == manuscript["work_id"] and record["source_version_id"] != manuscript["source_version_id"]
        assert (manuscript["version_label"], manuscript["doi"], manuscript["access"]["abstract_passage_id"]) == ("submittedVersion", None, None)
        assert manuscript["selection"]["origin"] == "default"  # not screened as a separate candidate
        screening = [c for c in adapter.calls if c["task_type"] == "screening"][-1]
        assert len(screening["candidates"]) == 3

        client.patch(f"/api/researches/{rid}/selections/{manuscript['source_version_id']}",
                     json={"state": "included", "expected_version": manuscript["selection"]["version"]})
        run = client.post(f"/api/researches/{rid}/runs", json={"kind": "answer"}).json()
        view, run = wait_run(client, rid, run["id"])
        assert run["status"] == "completed", run
        # One version per work: the published record has no PDF text, so the answer reads the manuscript's (D48).
        letters = [s for s in adapter.calls[-1]["sources"] if "letter" in s["title"]]
        assert [s["version_label"] for s in letters] == ["submittedVersion"]

        evidence = view["answers"][0]["claims"][0]["evidence"][0]
        assert evidence["source_version_id"] == manuscript["source_version_id"] and evidence["kind"] == "pdf_page"
        assert evidence["anchor_text"]
        passage = client.get(f"/api/researches/{rid}/passages/{evidence['passage_id']}").json()
        assert passage["source"]["version_label"] == "submittedVersion"
        by_id = {s["source_version_id"]: s for s in view["sources"]}
        assert not by_id[record["source_version_id"]]["access"]["assets"]  # the manuscript PDF is not attached to the published record
        assert view["counts"]["included"] == 3 and view["counts"]["cited"] == 1

        run = client.post(f"/api/researches/{rid}/runs", json={"kind": "discovery"}).json()  # found again
        view, _ = wait_run(client, rid, run["id"])
        assert len(view["sources"]) == 4
        again = next(s for s in view["sources"] if s["source_version_id"] == manuscript["source_version_id"])
        assert (again["selection"]["state"], again["selection"]["origin"]) == ("included", "user")
        assert view["answers"][0]["claims"][0]["evidence"][0]["source_version_id"] == manuscript["source_version_id"]


def test_sources_found_for_an_earlier_question_revision_are_labelled(tmp_path):
    with TestClient(app_for(tmp_path)) as client:
        session(client)
        rid = create(client, source_scope="attached_and_academic")
        run = client.post(f"/api/researches/{rid}/runs", json={"kind": "discovery"}).json()
        view, _ = wait_run(client, rid, run["id"])
        client.post(f"/api/researches/{rid}/uploads", files={"file": ("notes.pdf", make_pdf(["SYNTHETIC notes"]), "application/pdf")})
        version = client.get(f"/api/researches/{rid}").json()["research"]["version"]
        client.post(f"/api/researches/{rid}/scope", json={"question": "A narrower molecule release question", "expected_version": version})

        view = client.get(f"/api/researches/{rid}").json()
        found = [s for s in view["sources"] if s["origin"] == "provider"]
        uploaded = next(s for s in view["sources"] if s["origin"] == "user_upload")
        assert found and all((s["applicability"], s["found_in_revision"]) == ("stale_scope", 1) for s in found)
        assert (uploaded["applicability"], uploaded["found_in_revision"]) == ("current", None)
        assert {r["scope_revision"] for r in view["search_runs"]} == {1}

        run = client.post(f"/api/researches/{rid}/runs", json={"kind": "discovery"}).json()
        view, _ = wait_run(client, rid, run["id"])
        assert all((s["applicability"], s["found_in_revision"]) == ("current", 2) for s in view["sources"] if s["origin"] == "provider")


def test_quick_find_matches_researches_and_their_sources(tmp_path):
    with TestClient(app_for(tmp_path)) as client:
        session(client)
        rid = create(client, source_scope="attached")
        client.post(f"/api/researches/{rid}/uploads", files={"file": ("Relay_Budget_Notes.pdf", make_pdf(["SYNTHETIC"]), "application/pdf")})
        found = client.get("/api/search", params={"q": "MOLECULE release"}).json()
        assert [r["id"] for r in found["researches"]] == [rid] and found["sources"] == []
        found = client.get("/api/search", params={"q": "budget notes"}).json()
        assert [(s["title"], s["research_id"]) for s in found["sources"]] == [("Relay Budget Notes", rid)]
        assert client.get("/api/search", params={"q": "  "}).json() == {"researches": [], "sources": []}
        assert client.get("/api/search", params={"q": "%"}).json() == {"researches": [], "sources": []}  # no wildcard matching


def test_standard_depth_reads_more_results_screens_in_batches_and_gives_every_included_source(tmp_path):
    from deixis.domain.rules import SCREENING_BATCH

    seen, cited = [], {"base": 10}

    def handler(request):
        seen.append(request.url.params["per_page"])
        works = [{"id": f"https://openalex.org/W{100 + i}", "doi": None, "display_name": f"SYNTHETIC molecule schedule study {i}",
                  "publication_year": 2020, "type": "article", "authorships": [], "ids": {}, "primary_location": {},
                  "best_oa_location": None, "abstract_inverted_index": {"Molecule": [0], "release": [1], f"schedule{i}.": [2]},
                  "cited_by_count": cited["base"] + i} for i in range(45)]
        return httpx.Response(200, json={"meta": {"count": 300}, "results": works})

    adapter = FakeAdapter()
    app = create_app(Settings(data_dir=tmp_path / "data", port=8765), adapters={"fake": adapter},
                     http_client=httpx.AsyncClient(transport=httpx.MockTransport(handler)), fetcher=fake_fetch,
                     extra_hosts=("testserver",), trusted_clients=("testclient",))
    with TestClient(app) as client:
        session(client)
        rid = create(client, effort="standard")
        run = client.post(f"/api/researches/{rid}/runs", json={"kind": "discovery"}).json()
        view, run = wait_run(client, rid, run["id"])
        assert run["status"] == "completed", run
        # OpenAlex reads the core group alone to 100 results first, then the paired query to 25 (search-recall-depth note).
        assert seen == ["100", "25"] and view["search_runs"][0]["provider_total"] == 300
        assert [len(c["candidates"]) for c in adapter.calls if c["task_type"] == "screening"] == [SCREENING_BATCH, 45 - SCREENING_BATCH]
        assert view["counts"]["included"] == 45
        first = next(s for s in view["sources"] if s["title"].endswith("study 0"))
        assert first["cited_by_count"] == 10 and first["cited_by_count_at"]

        run = client.post(f"/api/researches/{rid}/runs", json={"kind": "answer"}).json()
        view, run = wait_run(client, rid, run["id"])
        assert run["status"] == "completed", run
        assert len(adapter.calls[-1]["sources"]) == 45 and view["answers"][0]["inputs_given"]["sources"] == 45
        assert all("cited_by_count" not in s for s in adapter.calls[-1]["sources"])  # shown to the user, not given to the model
        passage = client.get(f"/api/researches/{rid}/passages/{first['access']['abstract_passage_id']}").json()
        assert passage["source"]["cited_by_count"] == 10

        cited["base"] = 50  # the provider reports newer counts when the records are found again
        run = client.post(f"/api/researches/{rid}/runs", json={"kind": "discovery"}).json()
        view, _ = wait_run(client, rid, run["id"])
        assert next(s for s in view["sources"] if s["title"].endswith("study 0"))["cited_by_count"] == 50


def test_upload_size_is_bounded_before_and_while_reading(tmp_path, monkeypatch):
    from deixis.api import app as app_module

    monkeypatch.setattr(app_module, "MAX_UPLOAD_BYTES", 10_000)
    with TestClient(app_for(tmp_path)) as client:
        session(client)
        rid = create(client, source_scope="attached")
        declared_too_large = make_pdf(["SYNTHETIC"]) + b"%" * 100_000
        response = client.post(f"/api/researches/{rid}/uploads", files={"file": ("big.pdf", declared_too_large, "application/pdf")})
        assert response.status_code == 413  # refused from the declared length, before the body is parsed
        over_limit = make_pdf(["SYNTHETIC"]) + b"%" * 20_000  # within the multipart allowance, over the file limit
        response = client.post(f"/api/researches/{rid}/uploads", files={"file": ("big.pdf", over_limit, "application/pdf")})
        assert response.status_code == 413
        assert not list((tmp_path / "data" / "papers").glob("*"))  # no partial file left behind
        assert client.get(f"/api/researches/{rid}").json()["sources"] == []


def test_mutations_require_csrf_and_known_host(tmp_path):
    with TestClient(app_for(tmp_path)) as client:
        body = {"question": "x question", "model_connection": "fake"}
        assert client.post("/api/researches", json=body).status_code == 403
        session(client)
        assert client.post("/api/researches", json=body, headers={"origin": "http://evil.example"}).status_code == 403
        assert client.get("/api/health", headers={"host": "evil.example"}).status_code == 403
        assert client.post("/api/researches", json=body | {"model_connection": "codex"}).status_code == 422
        rid = create(client)
        pdf_file = {"file": ("a.pdf", make_pdf(["SYNTHETIC"]), "application/pdf")}
        assert client.post(f"/api/researches/{rid}/uploads", files=pdf_file).status_code == 422  # academic-only scope

    remote_app = create_app(Settings(data_dir=tmp_path / "remote", port=8765), adapters={"fake": FakeAdapter()},
                            http_client=openalex_client(), fetcher=fake_fetch, extra_hosts=("testserver",))
    with TestClient(remote_app) as remote:
        assert remote.get("/api/health").status_code == 403  # the test client's peer address is not loopback


def run_to_end(client, rid, kind):
    run = client.post(f"/api/researches/{rid}/runs", json={"kind": kind}).json()
    view, run = wait_run(client, rid, run["id"])
    assert run["status"] == "completed", run
    return view


def test_literature_model_runs_search_steps_and_the_research_model_writes_the_answer(tmp_path):
    adapter = FakeAdapter(models=["answer-model", "lit-model"], efforts=["low", "high"])
    with TestClient(app_for(tmp_path, adapter)) as client:
        session(client)
        rid = create(client, requested_model="answer-model", reasoning_effort="high",
                     literature_model="lit-model", literature_reasoning_effort="low")
        run_to_end(client, rid, "discovery")
        view = run_to_end(client, rid, "answer")
        assert set(adapter.sent) == {("search_plan", "lit-model", "low"), ("screening", "lit-model", "low"),
                                     ("research_title", "answer-model", "high"),
                                     ("grounded_answer", "answer-model", "high")}
        assert view["answers"][0]["review"] is None and view["reviewer"]["model"] is None  # no reviewer set anywhere
        revised = client.post(f"/api/researches/{rid}/scope", json={"question": "How is molecule release timing optimized?",
                                                                    "expected_version": view["research"]["version"]}).json()
        assert (revised["scope"]["literature_model"], revised["scope"]["literature_reasoning_effort"]) == ("lit-model", "low")


def test_research_without_a_literature_model_searches_with_its_research_model(tmp_path):
    adapter = FakeAdapter(models=["fake-model"])
    with TestClient(app_for(tmp_path, adapter)) as client:
        session(client)
        run_to_end(client, create(client), "discovery")
        assert {model for _, model, _ in adapter.sent} == {"fake-model"}


def test_role_models_must_be_listed_and_complete(tmp_path):
    with TestClient(app_for(tmp_path, FakeAdapter(models=["fake-model"], efforts=["low"]))) as client:
        session(client)
        body = {"question": "How is molecule release scheduling optimized?", "model_connection": "fake", "requested_model": "fake-model"}
        for bad in ({"literature_model": "unlisted"}, {"literature_model": "fake-model", "literature_reasoning_effort": "xhigh"},
                    {"literature_reasoning_effort": "low"}, {"review_mode": "custom"}, {"review_mode": "custom", "review_model": "unlisted"},
                    {"review_model": "fake-model"}, {"review_mode": "off", "review_reasoning_effort": "low"}):
            assert client.post("/api/researches", json=body | bad).status_code == 422, bad
        assert client.put("/api/settings/reviewer", json={"model_connection": "fake", "model": "unlisted"}).status_code == 422
        assert client.put("/api/settings/reviewer", json={"model_connection": "fake", "reasoning_effort": "low"}).status_code == 422
        assert client.put("/api/settings/reviewer", json={"model_connection": "nope", "model": "fake-model"}).status_code == 422


def test_each_role_can_use_a_model_from_another_connection(tmp_path):
    answer = FakeAdapter(models=["answer-model"], efforts=["high"])
    # A second connection registered under a connection id the step input contract lists.
    other = FakeAdapter(models=["lit-model", "review-model"], efforts=["low"])
    app = create_app(Settings(data_dir=tmp_path / "data", port=8765), adapters={"fake": answer, "gemini": other},
                     http_client=openalex_client(), fetcher=fake_fetch, extra_hosts=("testserver",), trusted_clients=("testclient",))
    with TestClient(app) as client:
        session(client)
        rid = create(client, requested_model="answer-model", reasoning_effort="high",
                     literature_connection="gemini", literature_model="lit-model", literature_reasoning_effort="low",
                     review_mode="custom", review_connection="gemini", review_model="review-model")
        run_to_end(client, rid, "discovery")
        view = run_to_end(client, rid, "answer")
        assert set(answer.sent) == {("research_title", "answer-model", "high"),
                                    ("grounded_answer", "answer-model", "high")}
        assert set(other.sent) == {("search_plan", "lit-model", "low"), ("screening", "lit-model", "low"),
                                   ("answer_review", "review-model", None)}
        assert view["reviewer"] == {"mode": "custom", "connection": "gemini", "model": "review-model", "reasoning_effort": None}
        assert view["answers"][0]["review"]["model"]["connection"] == "gemini"
        revised = client.post(f"/api/researches/{rid}/scope", json={"question": "How is molecule release timing optimized?",
                                                                    "expected_version": view["research"]["version"]}).json()
        assert (revised["scope"]["literature_connection"], revised["scope"]["review_connection"]) == ("gemini", "gemini")

        body = {"question": "How is molecule release scheduling optimized?", "model_connection": "fake", "requested_model": "answer-model"}
        for bad in ({"literature_model": "lit-model"}, {"literature_connection": "gemini", "literature_model": "answer-model"},
                    {"literature_connection": "nope", "literature_model": "lit-model"}, {"literature_connection": "gemini"},
                    {"review_mode": "custom", "review_model": "review-model"}, {"review_connection": "gemini"}):
            assert client.post("/api/researches", json=body | bad).status_code == 422, bad


def test_model_defaults_are_kept_per_role_and_must_be_listed(tmp_path):
    with TestClient(app_for(tmp_path, FakeAdapter(models=["fake-model"], efforts=["low"]))) as client:
        session(client)
        assert {role: s["model"] for role, s in client.get("/api/settings").json().items()} == {"answer": None, "literature": None, "reviewer": None}
        saved = client.put("/api/settings/answer", json={"model_connection": "fake", "model": "fake-model", "reasoning_effort": "low"})
        assert saved.status_code == 200
        settings = client.get("/api/settings").json()
        assert (settings["answer"]["model"], settings["answer"]["reasoning_effort"]) == ("fake-model", "low")
        assert settings["literature"]["model"] is None and settings["reviewer"]["model"] is None  # roles do not share a default
        assert client.put("/api/settings/literature", json={"model_connection": "fake", "model": "unlisted"}).status_code == 422
        assert client.put("/api/settings/writer", json={"model_connection": "fake", "model": "fake-model"}).status_code == 422


def test_app_wide_reviewer_reviews_every_research_and_a_research_setting_overrides_it(tmp_path):
    adapter = FakeAdapter(models=["fake-model", "review-model", "other-reviewer"], efforts=["high"])
    with TestClient(app_for(tmp_path, adapter)) as client:
        session(client)
        assert client.get("/api/settings").json()["reviewer"]["model"] is None
        saved = client.put("/api/settings/reviewer", json={"model_connection": "fake", "model": "review-model", "reasoning_effort": "high"})
        assert saved.status_code == 200 and client.get("/api/settings").json()["reviewer"]["model"] == "review-model"

        def answered(**overrides):
            rid = create(client, source_scope="attached", **overrides)
            client.post(f"/api/researches/{rid}/uploads", files={"file": ("a.pdf", make_pdf(["SYNTHETIC molecule release schedule"]), "application/pdf")})
            return run_to_end(client, rid, "answer")

        view = answered()
        review = view["answers"][0]["review"]
        assert review["status"] == "completed" and review["model"]["requested_model"] == "review-model"
        assert view["answers"][0]["status"] == "structurally_valid"
        assert all(c["review"]["verdict"] == "supported" for c in view["answers"][0]["claims"])
        assert view["reviewer"] == {"mode": "default", "connection": "fake", "model": "review-model", "reasoning_effort": "high"}
        assert ("answer_review", "review-model", "high") in adapter.sent

        custom = answered(review_mode="custom", review_model="other-reviewer")
        assert custom["answers"][0]["review"]["model"]["requested_model"] == "other-reviewer"

        adapter.sent.clear()
        off = answered(review_mode="off")
        assert off["answers"][0]["review"] is None and off["reviewer"]["model"] is None
        assert off["answers"][0]["claims"][0]["review"] is None
        assert [task for task, _, _ in adapter.sent] == ["grounded_answer"]


def test_a_failed_review_is_recorded_without_pausing_or_changing_the_answer(tmp_path):
    adapter = FakeAdapter(responder=lambda si: "not json" if si["task_type"] == "answer_review" else valid_response(si),
                          models=["fake-model"])
    with TestClient(app_for(tmp_path, adapter)) as client:
        session(client)
        client.put("/api/settings/reviewer", json={"model_connection": "fake", "model": "fake-model"})
        view = run_to_end(client, attached_research(client), "answer")  # completed, not paused
        answer = view["answers"][0]
        assert answer["status"] == "structurally_valid" and answer["claims"]
        assert answer["review"]["status"] == "failed" and answer["review"]["failure_reason"] == "invalid_model_output"
        assert answer["review"]["issues"] and answer["claims"][0]["review"] is None
        assert [task for task, _, _ in adapter.sent].count("answer_review") == 2  # one repair, as for every model step


def test_pdf_collection_run_retrieves_open_pdfs_without_a_model_call_and_the_answer_does_not_fetch_again(tmp_path):
    fetched = []

    async def fetcher(url):
        fetched.append(url)
        return await fake_fetch(url)

    app = create_app(Settings(data_dir=tmp_path / "data", port=8765), adapters={"fake": FakeAdapter()},
                     http_client=openalex_client(), fetcher=fetcher, extra_hosts=("testserver",), trusted_clients=("testclient",))
    with TestClient(app) as raw:
        client = session(raw)
        rid = create(client)
        discovery = client.post(f"/api/researches/{rid}/runs", json={"kind": "discovery"}).json()
        wait_run(client, rid, discovery["id"])
        collection = client.post(f"/api/researches/{rid}/runs", json={"kind": "pdf_collection"}).json()
        view, run = wait_run(client, rid, collection["id"])
        assert run["status"] == "completed", run
        assert run["usage"].get("model_calls", 0) == 0 and fetched
        assert {s["kind"] for s in run["steps"]} <= {"fetch_pdf", "pdf_other_copy"}
        source = next(s for s in view["sources"] if s["doi"] == "10.1/a")
        assert source["has_pdf_text"] is True
        assert next(s for s in view["sources"] if s["doi"] is None)["has_pdf_text"] is False  # abstract only

        answer = client.post(f"/api/researches/{rid}/runs", json={"kind": "answer"}).json()
        _, answered = wait_run(client, rid, answer["id"])
        assert answered["status"] == "completed", answered
        assert not [s for s in answered["steps"] if s["kind"] in ("fetch_pdf", "pdf_other_copy")]


def test_dropped_pdfs_are_matched_to_included_sources_by_doi_or_title_and_not_attached(tmp_path):
    with TestClient(app_for(tmp_path)) as raw:
        client = session(raw)
        rid = create(client)
        discovery = client.post(f"/api/researches/{rid}/runs", json={"kind": "discovery"}).json()
        view, _ = wait_run(client, rid, discovery["id"])
        by_doi = next(s for s in view["sources"] if s["doi"] == "10.1/a")
        by_title = next(s for s in view["sources"] if s["title"] == "SYNTHETIC molecule schedule letter")
        files = [
            ("files", ("a.pdf", make_pdf(["SYNTHETIC paper. https://doi.org/10.1/a."]), "application/pdf")),
            ("files", ("b.pdf", make_pdf(["SYNTHETIC molecule\nschedule letter", "Molecule schedule letter."]), "application/pdf")),
            ("files", ("c.pdf", make_pdf(["SYNTHETIC unrelated notes"]), "application/pdf")),
        ]
        response = client.post(f"/api/researches/{rid}/uploads/match", files=files)
        assert response.status_code == 200, response.text
        assert by_doi["selection"]["state"] == by_title["selection"]["state"] == "included"
        assert [(m["filename"], m["source_version_id"], m["basis"]) for m in response.json()["matches"]] == [
            ("a.pdf", by_doi["source_version_id"], "doi"), ("b.pdf", by_title["source_version_id"], "title"), ("c.pdf", None, None)]
        after = client.get(f"/api/researches/{rid}").json()
        assert after["answers"][0]["claims"] == before["answers"][0]["claims"]
        assert [s["selection"] for s in after["sources"]] == [s["selection"] for s in before["sources"]]

        session(client)
        other = create(client, question="Unrelated research B question")
        leak = client.get(f"/api/researches/{other}/passages/{evidence['passage_id']}")
        assert leak.status_code == 404  # T08: passage outside research B's corpus


def test_run_view_reports_the_plan_screening_notes_and_counting_step_outputs(tmp_path):
    with TestClient(app_for(tmp_path)) as raw:
        client = session(raw)
        rid = create(client)
        discovery = client.post(f"/api/researches/{rid}/runs", json={"kind": "discovery"}).json()
        view, run = wait_run(client, rid, discovery["id"])
        assert run["status"] == "completed", run
        plan = run["plan"]
        assert plan["question_interpretation"] == "fake interpretation" and plan["search_rationale"] == "fake"
        assert plan["scope_boundaries"] == ["fake"]
        assert plan["concepts"][0]["label"] == "molecular communication" and plan["concepts"][0]["synonyms"] == ["molecular communication", "diffusion channel"]
        assert [(q["provider_id"], q["query_text"], q["rationale"]) for q in plan["queries"]] == [
            ("openalex", '("molecular communication" OR "diffusion channel") AND optimization',
             'Core "molecular communication" with the method family "optimization"')]
        assert [n["text"] for n in run["screening_notes"]] == ["fake screening notes."]
        # A model step's output stays out of the view; the counting steps carry theirs.
        assert next(s for s in run["steps"] if s["kind"] == "model:search_plan")["output"] is None

        answer_run = client.post(f"/api/researches/{rid}/runs", json={"kind": "answer"}).json()
        view, run = wait_run(client, rid, answer_run["id"])
        assert run["status"] == "completed", run
        assert run["plan"] is None and run["screening_notes"] == []
        fetched = next(s for s in run["steps"] if s["kind"] == "fetch_pdf" and s["status"] == "succeeded")
        assert fetched["output"]["page_count"] == 1 and fetched["output"]["passage_count"] >= 1
        assert fetched["output"]["asset_id"] in [a["id"] for s in view["sources"] for a in s["access"]["assets"]]


def test_pdf_discovery_is_visible_and_user_can_attach_pdf_to_existing_source(tmp_path):
    with TestClient(app_for(tmp_path)) as raw:
        client = session(raw)
        rid = create(client)
        run = client.post(f"/api/researches/{rid}/runs", json={"kind": "discovery"}).json()
        view, completed = wait_run(client, rid, run["id"])
        assert completed["status"] == "completed"
        source = next(s for s in view["sources"] if s["doi"])

        found = client.post(f"/api/researches/{rid}/sources/{source['source_version_id']}/pdf-discovery")
        assert found.status_code == 200, found.text
        refreshed = next(s for s in found.json()["sources"] if s["source_version_id"] == source["source_version_id"])
        assert [d["provider"] for d in refreshed["access"]["pdf_discoveries"]] == ["unpaywall", "openalex", "crossref", "core", "web_search"]

        attached = client.post(
            f"/api/researches/{rid}/sources/{source['source_version_id']}/uploads",
            files={"file": ("author-copy.pdf", make_pdf(["SYNTHETIC author copy"]), "application/pdf")},
        )
        assert attached.status_code == 201, attached.text
        same = next(s for s in attached.json()["sources"] if s["source_version_id"] == source["source_version_id"])
        assert same["access"]["assets"][0]["origin"] == "user_upload"


def test_version_uncertain_pdf_candidate_is_attached_only_when_the_user_confirms_it(tmp_path):
    fetched = []

    async def fetcher(url):
        fetched.append(url)
        if "gated" in url:
            return FetchResult("http_error", final_url=url, http_status=403)
        return FetchResult("ok", data=make_pdf(["SYNTHETIC repository copy"]), final_url=url, http_status=200)

    app = create_app(Settings(data_dir=tmp_path / "data", port=8765), adapters={"fake": FakeAdapter()},
                     http_client=openalex_client(), fetcher=fetcher, extra_hosts=("testserver",), trusted_clients=("testclient",))
    with TestClient(app) as raw:
        client = session(raw)
        rid = create(client)
        run = client.post(f"/api/researches/{rid}/runs", json={"kind": "discovery"}).json()
        view, completed = wait_run(client, rid, run["id"])
        assert completed["status"] == "completed"
        source = next(s for s in view["sources"] if s["doi"] == "10.1/c")
        svid = source["source_version_id"]
        assert not source["access"]["assets"]
        store = app.state.store
        discovery = store.record_pdf_discovery(rid, svid, "web_search", '"SYNTHETIC molecule schedule letter"',
                                               acquisition.Lookup("completed", []))
        store.record_pdf_candidates(svid, discovery, [
            acquisition.Candidate("web_search", "https://gated.example/copy.pdf", None, None, None, "title_verified", "uncertain"),
            acquisition.Candidate("web_search", "https://repo.example/copy.pdf", None, None, None, "title_verified", "uncertain"),
            acquisition.Candidate("openalex", "https://repo.example/manuscript.pdf", None, "submittedVersion", None,
                                  "doi_verified", "different"),
            acquisition.Candidate("web_search", "https://other.example/unrelated.pdf", None, None, None, "unverified", "uncertain"),
        ])
        ids = {c["candidate_url"]: c["id"] for c in store.pdf_candidates(svid)}
        attach = lambda url: client.post(f"/api/researches/{rid}/sources/{svid}/pdf-candidates/{ids[url]}/attach")
        before = len(fetched)

        assert attach("https://repo.example/manuscript.pdf").status_code == 422
        assert attach("https://other.example/unrelated.pdf").status_code == 422
        assert len(fetched) == before

        gated = attach("https://gated.example/copy.pdf")
        assert gated.status_code == 502 and "HTTP 403" in gated.json()["detail"]
        refreshed = next(s for s in client.get(f"/api/researches/{rid}").json()["sources"] if s["source_version_id"] == svid)
        assert not refreshed["access"]["assets"]
        # A stored web result under another paper's title stays refusable but is not listed.
        assert "https://other.example/unrelated.pdf" not in {c["candidate_url"] for c in refreshed["access"]["pdf_candidates"]}

        attached = attach("https://repo.example/copy.pdf")
        assert attached.status_code == 200, attached.text
        same = next(s for s in attached.json()["sources"] if s["source_version_id"] == svid)
        assert [a["origin"] for a in same["access"]["assets"]] == ["user_upload"]
        outcomes = {c["candidate_url"]: (c["access_status"], c["http_status"]) for c in same["access"]["pdf_candidates"]}
        assert outcomes["https://gated.example/copy.pdf"] == ("http_error", 403)
        assert outcomes["https://repo.example/copy.pdf"] == ("downloaded", 200)

        assert attach("https://gated.example/copy.pdf").status_code == 409
        assert client.post(f"/api/researches/{rid}/sources/{svid}/pdf-candidates/pdc_missing/attach").status_code == 404


@pytest.mark.parametrize("copy_found", [True, False])
def test_refused_link_leads_to_one_lookup_for_another_copy_and_is_not_requested_again(tmp_path, monkeypatch, copy_found):
    monkeypatch.setenv("DEIXIS_CONTACT_EMAIL", "")  # Unpaywall and CORE are not configured, so they send nothing
    monkeypatch.setenv("CORE_API_KEY", "")
    fetched, lookups = [], []

    def handler(request):
        if request.url.host == "api.openalex.org" and "doi.org" in request.url.path:
            lookups.append(request.url.host)
            return httpx.Response(200, json={"doi": "https://doi.org/10.1/a", "locations": [
                {"pdf_url": "https://repository.example/w1.pdf", "version": "publishedVersion"}]})
        if request.url.host == "api.crossref.org":
            lookups.append(request.url.host)
            return httpx.Response(404)
        return httpx.Response(200, json={"meta": {"count": len(WORKS)}, "results": WORKS})

    async def fetcher(url):
        fetched.append(url)
        if copy_found and "repository" in url:
            return FetchResult("ok", data=make_pdf(["SYNTHETIC repository copy"]), final_url=url, http_status=200)
        return FetchResult("http_error", final_url=url, http_status=403)

    app = create_app(Settings(data_dir=tmp_path / "data", port=8765), adapters={"fake": FakeAdapter()},
                     http_client=httpx.AsyncClient(transport=httpx.MockTransport(handler)), fetcher=fetcher,
                     extra_hosts=("testserver",), trusted_clients=("testclient",))
    with TestClient(app) as raw:
        client = session(raw)
        rid = create(client)
        discovery = client.post(f"/api/researches/{rid}/runs", json={"kind": "discovery"}).json()
        wait_run(client, rid, discovery["id"])
        answer = client.post(f"/api/researches/{rid}/runs", json={"kind": "answer"}).json()
        view, run = wait_run(client, rid, answer["id"])
        assert run["status"] == "completed", run

        refused = next(s for s in run["steps"] if s["kind"] == "fetch_pdf")
        assert (refused["status"], refused["error_code"], refused["error"]["http_status"]) == ("failed", "fetch_http_error", 403)
        other = next(s for s in run["steps"] if s["kind"] == "pdf_other_copy")
        source = next(s for s in view["sources"] if s["doi"] == "10.1/a")
        # The automatic lookup leaves web search to the user's own "Find PDF".
        assert [d["provider"] for d in source["access"]["pdf_discoveries"]] == ["unpaywall", "openalex", "crossref", "core"]
        assert source["access"]["fetch"]["http_status"] == 403
        if copy_found:
            assert other["status"] == "succeeded" and other["output"]["page_count"] == 1
            assert [a["origin"] for a in source["access"]["assets"]] == ["download"]
        else:
            assert (other["status"], other["error_code"]) == ("failed", "no_other_copy")
            assert not source["access"]["assets"] and source["access"]["other_copy"]["status"] == "failed"
        # The letter's published record has no open PDF, so its open manuscript is retrieved for the answer (D48).
        assert sorted(fetched) == ["https://example.org/w1.pdf", "https://example.org/w3-manuscript.pdf", "https://repository.example/w1.pdf"]
        assert lookups == ["api.openalex.org", "api.crossref.org"]

        again = client.post(f"/api/researches/{rid}/runs", json={"kind": "answer"}).json()
        _, rerun = wait_run(client, rid, again["id"])
        assert rerun["status"] == "completed", rerun
        assert not [s for s in rerun["steps"] if s["kind"] in ("fetch_pdf", "pdf_other_copy")]
        assert len(fetched) == 3 and len(lookups) == 2  # neither the refused link nor the lookup is repeated


def test_invalid_output_is_repaired_once_then_kept_as_unverified_draft(tmp_path):
    def bad(si):
        if si["task_type"] != "grounded_answer":
            return valid_response(si)
        return json.dumps(envelope(si, "deixis.grounded_answer_draft.v3") | {
            "title": "Synthetic evidence for release scheduling and optimization in constrained molecular communication networks",
            "answer_language": "en",
            "claims": [{"claim_label": "c1", "section": "Overview", "text": "It has been reported that X was invented.", "support_type": "source_stated", "passage_ids": ["psg_INVENTED0001"]}],
            "citation_anchors": [],
            "limitations": [], "unanswered_aspects": [], "capability_notice": None,
        })

    adapter = FakeAdapter(bad)
    with TestClient(app_for(tmp_path, adapter)) as client:
        session(client)
        rid = create(client, source_scope="attached")
        client.post(f"/api/researches/{rid}/uploads", files={"file": ("a.pdf", make_pdf(["SYNTHETIC molecule text"]), "application/pdf")})
        run = client.post(f"/api/researches/{rid}/runs", json={"kind": "answer"}).json()
        view, run = wait_run(client, rid, run["id"])
        answer = view["answers"][0]
        assert answer["status"] == "unverified_draft" and answer["claims"] == []
        assert {i["code"] for i in answer["validation"]["issues"]} == {"unknown_passage_id"}
        assert len(adapter.calls) == 2  # original + one repair
        assert run["usage"]["model_calls"] == 2


def test_missing_anchor_is_repaired_before_the_answer_is_published(tmp_path):
    answer_attempts = 0

    def missing_then_valid(si):
        nonlocal answer_attempts
        draft = json.loads(valid_response(si))
        if si["task_type"] == "grounded_answer":
            answer_attempts += 1
            if answer_attempts == 1:
                draft["citation_anchors"] = []
        return json.dumps(draft)

    adapter = FakeAdapter(missing_then_valid)
    with TestClient(app_for(tmp_path, adapter)) as client:
        session(client)
        rid = create(client, source_scope="attached")
        client.post(f"/api/researches/{rid}/uploads", files={"file": ("a.pdf", make_pdf(["SYNTHETIC molecule text"]), "application/pdf")})
        run = client.post(f"/api/researches/{rid}/runs", json={"kind": "answer"}).json()
        view, run = wait_run(client, rid, run["id"])
        answer = view["answers"][0]
        assert answer["status"] == "structurally_valid"
        assert all(evidence["anchor_text"] for claim in answer["claims"] for evidence in claim["evidence"])
        assert [task for task, _, _ in adapter.sent].count("grounded_answer") == 2
        assert run["usage"]["model_calls"] == 2


def test_long_answer_title_is_repaired_and_the_valid_title_replaces_the_question(tmp_path):
    attempts = 0

    def long_then_valid(si):
        nonlocal attempts
        draft = json.loads(valid_response(si))
        if si["task_type"] == "grounded_answer":
            attempts += 1
            if attempts == 1:
                draft["title"] = " ".join(f"word{n}" for n in range(21))
        return json.dumps(draft)

    adapter = FakeAdapter(long_then_valid)
    with TestClient(app_for(tmp_path, adapter)) as client:
        session(client)
        rid = create(client, source_scope="attached")
        original = client.get(f"/api/researches/{rid}").json()["research"]["title"]
        client.post(f"/api/researches/{rid}/uploads", files={"file": ("a.pdf", make_pdf(["SYNTHETIC molecule text"]), "application/pdf")})
        run = client.post(f"/api/researches/{rid}/runs", json={"kind": "answer"}).json()
        view, run = wait_run(client, rid, run["id"])
        assert view["answers"][0]["status"] == "structurally_valid"
        assert view["research"]["title"] == "Synthetic evidence for release scheduling and optimization in constrained molecular communication networks"
        assert view["research"]["title"] != original
        assert attempts == 2 and run["usage"]["model_calls"] == 2


def test_invented_locator_in_claim_text_is_repaired_or_never_shown_as_cited(tmp_path):
    # B: the first draft asserts a page and an equation; the repair attempt removes them.
    def with_claim_text(si, text):
        draft = json.loads(valid_response(si))
        if si["task_type"] == "grounded_answer" and text:
            draft["claims"][0]["text"] = text
        return json.dumps(draft)

    answers_given = []

    def first_invents(si):
        answers_given.append(si["task_type"])
        invented = si["task_type"] == "grounded_answer" and answers_given.count("grounded_answer") == 1
        return with_claim_text(si, "Equation 4 on page 12 proves the schedule is optimal." if invented else None)

    adapter = FakeAdapter(first_invents)
    with TestClient(app_for(tmp_path, adapter)) as client:
        session(client)
        rid = attached_research(client)
        run = client.post(f"/api/researches/{rid}/runs", json={"kind": "answer"}).json()
        view, run = wait_run(client, rid, run["id"])
        answer = view["answers"][0]
        assert len(adapter.calls) == 2 and answer["status"] == "structurally_valid"
        assert all("page 12" not in c["text"].lower() for c in answer["claims"])

    always = FakeAdapter(lambda si: with_claim_text(si, "It has been reported on page 12 that X holds."))
    with TestClient(app_for(tmp_path / "second", always)) as client:
        session(client)
        rid = attached_research(client)
        run = client.post(f"/api/researches/{rid}/runs", json={"kind": "answer"}).json()
        view, _ = wait_run(client, rid, run["id"])
        answer = view["answers"][0]
        assert answer["status"] == "unverified_draft" and answer["claims"] == []
        assert {i["code"] for i in answer["validation"]["issues"]} == {"locator_in_claim_text"}


def test_attached_only_scope_never_searches(tmp_path):
    with TestClient(app_for(tmp_path)) as client:
        session(client)
        rid = create(client, source_scope="attached")
        assert client.post(f"/api/researches/{rid}/runs", json={"kind": "discovery"}).status_code == 422
        view = client.get(f"/api/researches/{rid}").json()
        assert view["search_runs"] == [] and view["scope"]["providers"] == []


def test_provider_rate_limit_pauses_without_fallback(tmp_path):
    with TestClient(app_for(tmp_path, http_status=429)) as client:
        session(client)
        rid = create(client)
        run = client.post(f"/api/researches/{rid}/runs", json={"kind": "discovery"}).json()
        view, run = wait_run(client, rid, run["id"])
        assert run["status"] == "paused" and run["pause_reason"] == "provider_rate_limited"
        assert view["search_runs"][0]["status"] == "rate_limited"
        assert view["counts"]["found"] == 0  # E: not shown as zero results of a completed search


def test_model_not_ready_pauses_run(tmp_path):
    with TestClient(app_for(tmp_path, FakeAdapter(ready=False))) as client:
        session(client)
        rid = create(client)
        run = client.post(f"/api/researches/{rid}/runs", json={"kind": "discovery"}).json()
        _, run = wait_run(client, rid, run["id"])
        assert (run["status"], run["pause_reason"]) == ("paused", "model_connection_not_ready")


def test_backend_crash_mid_run_is_recovered_as_paused_then_resumable(tmp_path):
    app = app_for(tmp_path)
    with TestClient(app) as client:
        session(client)
        rid = create(client, source_scope="attached")
        client.post(f"/api/researches/{rid}/uploads", files={"file": ("a.pdf", make_pdf(["SYNTHETIC molecule text"]), "application/pdf")})
    conn = db.connect(tmp_path / "data" / "library.sqlite")
    conn.execute(
        "INSERT INTO runs (id, research_id, scope_revision, kind, status, stage, budget_json, created_at, updated_at)"
        " VALUES ('run_CRASHED000001', ?, 1, 'answer', 'running', 'answer', ?, 'now', 'now')",
        (rid, json.dumps({"max_model_calls": 4, "max_provider_requests": 2, "max_candidates": 15, "max_answer_passages": 8})),
    )
    conn.execute(
        "INSERT INTO run_steps (id, run_id, operation_key, kind, status, attempt) VALUES ('stp_CRASHED000001', 'run_CRASHED000001', 'grounded_answer', 'model:grounded_answer', 'running', 1)"
    )
    conn.close()

    with TestClient(app_for(tmp_path)) as client:
        session(client)
        assert client.get("/api/health").json()["recovered"] == {"runs": 1, "steps": 1, "model_sessions": 0}
        view = client.get(f"/api/researches/{rid}").json()
        run = view["runs"][0]
        assert (run["status"], run["pause_reason"]) == ("paused", "backend_restarted")
        assert run["steps"][0]["status"] == "outcome_unknown"
        client.post(f"/api/runs/{run['id']}/resume")
        view, run = wait_run(client, rid, run["id"])
        assert run["status"] == "completed" and view["answers"][0]["status"] == "structurally_valid"


def test_second_instance_does_not_start_a_worker(tmp_path):
    with TestClient(app_for(tmp_path)) as first, TestClient(app_for(tmp_path)) as second:
        assert first.get("/api/health").json()["worker"] == "owner"
        assert second.get("/api/health").json()["worker"] == "not_owner"


def test_waiting_instance_takes_over_after_owner_stops(tmp_path):
    first = TestClient(app_for(tmp_path)).__enter__()
    second = TestClient(app_for(tmp_path)).__enter__()
    try:
        assert second.get("/api/health").json()["worker"] == "not_owner"
        first.__exit__(None, None, None)  # e.g. a restart that starts before the old process has exited
        deadline = time.time() + 5
        while second.get("/api/health").json()["worker"] != "owner" and time.time() < deadline:
            time.sleep(0.1)
        assert second.get("/api/health").json()["worker"] == "owner"
    finally:
        second.__exit__(None, None, None)


def attached_research(client):
    rid = create(client, source_scope="attached")
    client.post(f"/api/researches/{rid}/uploads", files={"file": ("a.pdf", make_pdf(["SYNTHETIC molecule release schedule"]), "application/pdf")})
    return rid


def test_research_requires_an_explicit_listed_model(tmp_path):
    with TestClient(app_for(tmp_path, FakeAdapter(models=["fake-model"]))) as client:
        session(client)
        body = {"question": "How is molecule release scheduling optimized?", "model_connection": "fake"}
        assert client.post("/api/researches", json=body).status_code == 422
        assert client.post("/api/researches", json=body | {"requested_model": "unlisted-model"}).status_code == 422
        assert client.post("/api/researches", json=body | {"requested_model": "fake-model"}).status_code == 201


def test_reasoning_effort_must_be_listed_and_is_sent_with_every_model_step(tmp_path):
    adapter = FakeAdapter(models=["fake-model"], efforts=["low", "high"])
    with TestClient(app_for(tmp_path, adapter)) as client:
        session(client)
        body = {"question": "How is molecule release scheduling optimized?", "model_connection": "fake", "requested_model": "fake-model"}
        assert client.post("/api/researches", json=body | {"reasoning_effort": "xhigh"}).status_code == 422
        rid = create(client, source_scope="attached", reasoning_effort="high")
        client.post(f"/api/researches/{rid}/uploads", files={"file": ("a.pdf", make_pdf(["SYNTHETIC molecule text"]), "application/pdf")})
        run = client.post(f"/api/researches/{rid}/runs", json={"kind": "answer"}).json()
        view, run = wait_run(client, rid, run["id"])
        assert run["status"] == "completed", run
        assert view["scope"]["reasoning_effort"] == "high"
        assert adapter.sent_efforts and set(adapter.sent_efforts) == {"high"}


def test_output_from_another_model_is_recorded_but_not_used(tmp_path):
    adapter = FakeAdapter(resolved_model="some-other-model")
    with TestClient(app_for(tmp_path, adapter)) as client:
        session(client)
        rid = attached_research(client)
        run = client.post(f"/api/researches/{rid}/runs", json={"kind": "answer"}).json()
        view, run = wait_run(client, rid, run["id"])
        assert (run["status"], run["pause_reason"]) == ("paused", "model_mismatch")
        assert view["answers"] == [] and len(adapter.calls) == 1


def test_pause_during_final_model_call_applies_result_only_after_resume(tmp_path):
    holder = {}

    def responder(si):
        if si["task_type"] == "grounded_answer" and not holder.get("paused"):
            holder["paused"] = True
            holder["app"].state.store.update_run(si["run_id"], event="run_pause_requested", status="pause_requested",
                                                 pause_reason="user_requested")
        return valid_response(si)

    adapter = FakeAdapter(responder)
    holder["app"] = app = app_for(tmp_path, adapter)
    with TestClient(app) as client:
        session(client)
        rid = attached_research(client)
        run = client.post(f"/api/researches/{rid}/runs", json={"kind": "answer"}).json()
        view, run = wait_run(client, rid, run["id"])
        assert (run["status"], run["pause_reason"]) == ("paused", "user_requested") and view["answers"] == []
        client.post(f"/api/runs/{run['id']}/resume")
        view, run = wait_run(client, rid, run["id"])
        assert run["status"] == "completed" and len(view["answers"]) == 1
        assert len(adapter.calls) == 1  # the recorded output is applied; the model is not called again


def test_cancel_during_model_call_keeps_output_unapplied(tmp_path):
    holder = {}

    def responder(si):
        if si["task_type"] == "grounded_answer":
            holder["app"].state.store.update_run(si["run_id"], event="run_cancelled", status="cancelled", pause_reason="user_cancelled")
        return valid_response(si)

    holder["app"] = app = app_for(tmp_path, FakeAdapter(responder))
    with TestClient(app) as client:
        session(client)
        rid = attached_research(client)
        run = client.post(f"/api/researches/{rid}/runs", json={"kind": "answer"}).json()
        view, run = wait_run(client, rid, run["id"])
        assert run["status"] == "cancelled" and view["answers"] == []
        assert next(s for s in run["steps"] if s["kind"] == "model:grounded_answer")["status"] == "succeeded"


def test_selection_change_marks_existing_answer_stale(tmp_path):
    with TestClient(app_for(tmp_path)) as client:
        session(client)
        rid = attached_research(client)
        run = client.post(f"/api/researches/{rid}/runs", json={"kind": "answer"}).json()
        view, _ = wait_run(client, rid, run["id"])
        assert view["answers"][0]["applicability"] == "current"
        source = view["sources"][0]
        client.patch(f"/api/researches/{rid}/selections/{source['source_version_id']}",
                     json={"state": "excluded", "expected_version": source["selection"]["version"]})
        assert client.get(f"/api/researches/{rid}").json()["answers"][0]["applicability"] == "stale_selection"


def test_reports_keep_their_own_number_and_title_and_all_are_listed(tmp_path):
    app = app_for(tmp_path)
    with TestClient(app) as client:
        session(client)
        rid = attached_research(client)
        first = client.post(f"/api/researches/{rid}/runs", json={"kind": "answer"}).json()
        view, _ = wait_run(client, rid, first["id"])
        store = app.state.store
        run_id = first["id"]
        # A clarification takes no number, and a later title change does not rename the saved report.
        store.save_answer(rid, run_id, None, None, 1, "clarification", {"question": "Which network?"}, {})
        store.conn.execute("UPDATE answers SET draft_json = json_set(draft_json, '$.title', 'Saved title') WHERE status = 'structurally_valid'")
        for _ in range(11):
            later = store.create_run(rid, "answer", {}, None)["id"]
            store.update_run(later, status="cancelled")
            store.save_answer(rid, later, None, None, 1, "structurally_valid", {"title": "Later title", "claims": []}, {})
        answers = client.get(f"/api/researches/{rid}").json()["answers"]
        assert len(answers) == 13  # older answers are no longer cut off at ten
        reports = [a for a in answers if a["status"] == "structurally_valid"]
        assert [a["report_version"] for a in reports] == list(range(12, 0, -1))
        assert reports[-1]["report_title"] == "Saved title" and reports[0]["report_title"] == "Later title"
        assert next(a for a in answers if a["status"] == "clarification")["report_version"] is None


def test_resume_after_crash_following_saved_answer_does_not_duplicate_it(tmp_path):
    with TestClient(app_for(tmp_path)) as client:
        session(client)
        rid = attached_research(client)
        run = client.post(f"/api/researches/{rid}/runs", json={"kind": "answer"}).json()
        wait_run(client, rid, run["id"])
    conn = db.connect(tmp_path / "data" / "library.sqlite")
    conn.execute("UPDATE runs SET status = 'running' WHERE id = ?", (run["id"],))  # crash before completion was recorded
    conn.close()

    adapter = FakeAdapter()
    with TestClient(app_for(tmp_path, adapter)) as client:
        session(client)
        client.post(f"/api/runs/{run['id']}/resume")
        view, resumed = wait_run(client, rid, run["id"], statuses=("completed", "failed", "cancelled"))
        assert resumed["status"] == "completed"
        assert len(view["answers"]) == 1 and adapter.calls == []


def test_question_revision_during_discovery_stops_applying_its_results(tmp_path):
    holder = {}

    def responder(si):
        if si["task_type"] == "search_plan":
            store = holder["app"].state.store
            store.revise_scope(si["research_id"], store.research(si["research_id"])["version"], "A revised molecule release question", None)
        return valid_response(si)

    adapter = FakeAdapter(responder)
    holder["app"] = app = app_for(tmp_path, adapter)
    with TestClient(app) as client:
        session(client)
        rid = create(client)
        run = client.post(f"/api/researches/{rid}/runs", json={"kind": "discovery"}).json()
        view, run = wait_run(client, rid, run["id"])
        assert (run["status"], run["pause_reason"]) == ("cancelled", "scope_revised")
        assert view["search_runs"] == [] and view["sources"] == []
        assert [c["task_type"] for c in adapter.calls] == ["search_plan"]


def test_submitted_and_published_versions_stay_separate_versions_of_one_work(tmp_path):
    # C: one work family, separate versions; evidence stays with the inspected version; versions are not counted twice.
    def cite_manuscript(si):
        if si["task_type"] != "grounded_answer":
            return valid_response(si)
        manuscript = next(s["source_id"] for s in si["sources"] if s["version_label"] == "submittedVersion")
        passage = next(p for p in si["passages"] if p["source_id"] == manuscript)
        return valid_response(si | {"passages": [passage]})

    adapter = FakeAdapter(cite_manuscript)
    with TestClient(app_for(tmp_path, adapter)) as client:
        session(client)
        rid = create(client)
        run = client.post(f"/api/researches/{rid}/runs", json={"kind": "discovery"}).json()
        view, _ = wait_run(client, rid, run["id"])
        assert len(view["sources"]) == 4 and view["counts"]["unique"] == 3
        record, manuscript = [s for s in view["sources"] if "letter" in s["title"]]  # the other version follows its record
        assert (record["version_role"], manuscript["version_role"]) == ("record", "other_version")
        assert record["work_id"] == manuscript["work_id"] and record["source_version_id"] != manuscript["source_version_id"]
        assert (manuscript["version_label"], manuscript["doi"], manuscript["access"]["abstract_passage_id"]) == ("submittedVersion", None, None)
        assert manuscript["selection"]["origin"] == "default"  # not screened as a separate candidate
        screening = [c for c in adapter.calls if c["task_type"] == "screening"][-1]
        assert len(screening["candidates"]) == 3

        client.patch(f"/api/researches/{rid}/selections/{manuscript['source_version_id']}",
                     json={"state": "included", "expected_version": manuscript["selection"]["version"]})
        run = client.post(f"/api/researches/{rid}/runs", json={"kind": "answer"}).json()
        view, run = wait_run(client, rid, run["id"])
        assert run["status"] == "completed", run
        # One version per work: the published record has no PDF text, so the answer reads the manuscript's (D48).
        letters = [s for s in adapter.calls[-1]["sources"] if "letter" in s["title"]]
        assert [s["version_label"] for s in letters] == ["submittedVersion"]

        evidence = view["answers"][0]["claims"][0]["evidence"][0]
        assert evidence["source_version_id"] == manuscript["source_version_id"] and evidence["kind"] == "pdf_page"
        assert evidence["anchor_text"]
        passage = client.get(f"/api/researches/{rid}/passages/{evidence['passage_id']}").json()
        assert passage["source"]["version_label"] == "submittedVersion"
        by_id = {s["source_version_id"]: s for s in view["sources"]}
        assert not by_id[record["source_version_id"]]["access"]["assets"]  # the manuscript PDF is not attached to the published record
        assert view["counts"]["included"] == 3 and view["counts"]["cited"] == 1

        run = client.post(f"/api/researches/{rid}/runs", json={"kind": "discovery"}).json()  # found again
        view, _ = wait_run(client, rid, run["id"])
        assert len(view["sources"]) == 4
        again = next(s for s in view["sources"] if s["source_version_id"] == manuscript["source_version_id"])
        assert (again["selection"]["state"], again["selection"]["origin"]) == ("included", "user")
        assert view["answers"][0]["claims"][0]["evidence"][0]["source_version_id"] == manuscript["source_version_id"]


def test_sources_found_for_an_earlier_question_revision_are_labelled(tmp_path):
    with TestClient(app_for(tmp_path)) as client:
        session(client)
        rid = create(client, source_scope="attached_and_academic")
        run = client.post(f"/api/researches/{rid}/runs", json={"kind": "discovery"}).json()
        view, _ = wait_run(client, rid, run["id"])
        client.post(f"/api/researches/{rid}/uploads", files={"file": ("notes.pdf", make_pdf(["SYNTHETIC notes"]), "application/pdf")})
        version = client.get(f"/api/researches/{rid}").json()["research"]["version"]
        client.post(f"/api/researches/{rid}/scope", json={"question": "A narrower molecule release question", "expected_version": version})

        view = client.get(f"/api/researches/{rid}").json()
        found = [s for s in view["sources"] if s["origin"] == "provider"]
        uploaded = next(s for s in view["sources"] if s["origin"] == "user_upload")
        assert found and all((s["applicability"], s["found_in_revision"]) == ("stale_scope", 1) for s in found)
        assert (uploaded["applicability"], uploaded["found_in_revision"]) == ("current", None)
        assert {r["scope_revision"] for r in view["search_runs"]} == {1}

        run = client.post(f"/api/researches/{rid}/runs", json={"kind": "discovery"}).json()
        view, _ = wait_run(client, rid, run["id"])
        assert all((s["applicability"], s["found_in_revision"]) == ("current", 2) for s in view["sources"] if s["origin"] == "provider")


def test_quick_find_matches_researches_and_their_sources(tmp_path):
    with TestClient(app_for(tmp_path)) as client:
        session(client)
        rid = create(client, source_scope="attached")
        client.post(f"/api/researches/{rid}/uploads", files={"file": ("Relay_Budget_Notes.pdf", make_pdf(["SYNTHETIC"]), "application/pdf")})
        found = client.get("/api/search", params={"q": "MOLECULE release"}).json()
        assert [r["id"] for r in found["researches"]] == [rid] and found["sources"] == []
        found = client.get("/api/search", params={"q": "budget notes"}).json()
        assert [(s["title"], s["research_id"]) for s in found["sources"]] == [("Relay Budget Notes", rid)]
        assert client.get("/api/search", params={"q": "  "}).json() == {"researches": [], "sources": []}
        assert client.get("/api/search", params={"q": "%"}).json() == {"researches": [], "sources": []}  # no wildcard matching


def test_standard_depth_reads_more_results_screens_in_batches_and_gives_every_included_source(tmp_path):
    from deixis.domain.rules import SCREENING_BATCH

    seen, cited = [], {"base": 10}

    def handler(request):
        seen.append(request.url.params["per_page"])
        works = [{"id": f"https://openalex.org/W{100 + i}", "doi": None, "display_name": f"SYNTHETIC molecule schedule study {i}",
                  "publication_year": 2020, "type": "article", "authorships": [], "ids": {}, "primary_location": {},
                  "best_oa_location": None, "abstract_inverted_index": {"Molecule": [0], "release": [1], f"schedule{i}.": [2]},
                  "cited_by_count": cited["base"] + i} for i in range(45)]
        return httpx.Response(200, json={"meta": {"count": 300}, "results": works})

    adapter = FakeAdapter()
    app = create_app(Settings(data_dir=tmp_path / "data", port=8765), adapters={"fake": adapter},
                     http_client=httpx.AsyncClient(transport=httpx.MockTransport(handler)), fetcher=fake_fetch,
                     extra_hosts=("testserver",), trusted_clients=("testclient",))
    with TestClient(app) as client:
        session(client)
        rid = create(client, effort="standard")
        run = client.post(f"/api/researches/{rid}/runs", json={"kind": "discovery"}).json()
        view, run = wait_run(client, rid, run["id"])
        assert run["status"] == "completed", run
        # OpenAlex reads the core group alone to 100 results first, then the paired query to 25 (search-recall-depth note).
        assert seen == ["100", "25"] and view["search_runs"][0]["provider_total"] == 300
        assert [len(c["candidates"]) for c in adapter.calls if c["task_type"] == "screening"] == [SCREENING_BATCH, 45 - SCREENING_BATCH]
        assert view["counts"]["included"] == 45
        first = next(s for s in view["sources"] if s["title"].endswith("study 0"))
        assert first["cited_by_count"] == 10 and first["cited_by_count_at"]

        run = client.post(f"/api/researches/{rid}/runs", json={"kind": "answer"}).json()
        view, run = wait_run(client, rid, run["id"])
        assert run["status"] == "completed", run
        assert len(adapter.calls[-1]["sources"]) == 45 and view["answers"][0]["inputs_given"]["sources"] == 45
        assert all("cited_by_count" not in s for s in adapter.calls[-1]["sources"])  # shown to the user, not given to the model
        passage = client.get(f"/api/researches/{rid}/passages/{first['access']['abstract_passage_id']}").json()
        assert passage["source"]["cited_by_count"] == 10

        cited["base"] = 50  # the provider reports newer counts when the records are found again
        run = client.post(f"/api/researches/{rid}/runs", json={"kind": "discovery"}).json()
        view, _ = wait_run(client, rid, run["id"])
        assert next(s for s in view["sources"] if s["title"].endswith("study 0"))["cited_by_count"] == 50


def test_upload_size_is_bounded_before_and_while_reading(tmp_path, monkeypatch):
    from deixis.api import app as app_module

    monkeypatch.setattr(app_module, "MAX_UPLOAD_BYTES", 10_000)
    with TestClient(app_for(tmp_path)) as client:
        session(client)
        rid = create(client, source_scope="attached")
        declared_too_large = make_pdf(["SYNTHETIC"]) + b"%" * 100_000
        response = client.post(f"/api/researches/{rid}/uploads", files={"file": ("big.pdf", declared_too_large, "application/pdf")})
        assert response.status_code == 413  # refused from the declared length, before the body is parsed
        over_limit = make_pdf(["SYNTHETIC"]) + b"%" * 20_000  # within the multipart allowance, over the file limit
        response = client.post(f"/api/researches/{rid}/uploads", files={"file": ("big.pdf", over_limit, "application/pdf")})
        assert response.status_code == 413
        assert not list((tmp_path / "data" / "papers").glob("*"))  # no partial file left behind
        assert client.get(f"/api/researches/{rid}").json()["sources"] == []


def test_mutations_require_csrf_and_known_host(tmp_path):
    with TestClient(app_for(tmp_path)) as client:
        body = {"question": "x question", "model_connection": "fake"}
        assert client.post("/api/researches", json=body).status_code == 403
        session(client)
        assert client.post("/api/researches", json=body, headers={"origin": "http://evil.example"}).status_code == 403
        assert client.get("/api/health", headers={"host": "evil.example"}).status_code == 403
        assert client.post("/api/researches", json=body | {"model_connection": "codex"}).status_code == 422
        rid = create(client)
        pdf_file = {"file": ("a.pdf", make_pdf(["SYNTHETIC"]), "application/pdf")}
        assert client.post(f"/api/researches/{rid}/uploads", files=pdf_file).status_code == 422  # academic-only scope

    remote_app = create_app(Settings(data_dir=tmp_path / "remote", port=8765), adapters={"fake": FakeAdapter()},
                            http_client=openalex_client(), fetcher=fake_fetch, extra_hosts=("testserver",))
    with TestClient(remote_app) as remote:
        assert remote.get("/api/health").status_code == 403  # the test client's peer address is not loopback


def run_to_end(client, rid, kind):
    run = client.post(f"/api/researches/{rid}/runs", json={"kind": kind}).json()
    view, run = wait_run(client, rid, run["id"])
    assert run["status"] == "completed", run
    return view


def test_literature_model_runs_search_steps_and_the_research_model_writes_the_answer(tmp_path):
    adapter = FakeAdapter(models=["answer-model", "lit-model"], efforts=["low", "high"])
    with TestClient(app_for(tmp_path, adapter)) as client:
        session(client)
        rid = create(client, requested_model="answer-model", reasoning_effort="high",
                     literature_model="lit-model", literature_reasoning_effort="low")
        run_to_end(client, rid, "discovery")
        view = run_to_end(client, rid, "answer")
        assert set(adapter.sent) == {("search_plan", "lit-model", "low"), ("screening", "lit-model", "low"),
                                     ("research_title", "answer-model", "high"),
                                     ("grounded_answer", "answer-model", "high")}
        assert view["answers"][0]["review"] is None and view["reviewer"]["model"] is None  # no reviewer set anywhere
        revised = client.post(f"/api/researches/{rid}/scope", json={"question": "How is molecule release timing optimized?",
                                                                    "expected_version": view["research"]["version"]}).json()
        assert (revised["scope"]["literature_model"], revised["scope"]["literature_reasoning_effort"]) == ("lit-model", "low")


def test_research_without_a_literature_model_searches_with_its_research_model(tmp_path):
    adapter = FakeAdapter(models=["fake-model"])
    with TestClient(app_for(tmp_path, adapter)) as client:
        session(client)
        run_to_end(client, create(client), "discovery")
        assert {model for _, model, _ in adapter.sent} == {"fake-model"}


def test_role_models_must_be_listed_and_complete(tmp_path):
    with TestClient(app_for(tmp_path, FakeAdapter(models=["fake-model"], efforts=["low"]))) as client:
        session(client)
        body = {"question": "How is molecule release scheduling optimized?", "model_connection": "fake", "requested_model": "fake-model"}
        for bad in ({"literature_model": "unlisted"}, {"literature_model": "fake-model", "literature_reasoning_effort": "xhigh"},
                    {"literature_reasoning_effort": "low"}, {"review_mode": "custom"}, {"review_mode": "custom", "review_model": "unlisted"},
                    {"review_model": "fake-model"}, {"review_mode": "off", "review_reasoning_effort": "low"}):
            assert client.post("/api/researches", json=body | bad).status_code == 422, bad
        assert client.put("/api/settings/reviewer", json={"model_connection": "fake", "model": "unlisted"}).status_code == 422
        assert client.put("/api/settings/reviewer", json={"model_connection": "fake", "reasoning_effort": "low"}).status_code == 422
        assert client.put("/api/settings/reviewer", json={"model_connection": "nope", "model": "fake-model"}).status_code == 422


def test_each_role_can_use_a_model_from_another_connection(tmp_path):
    answer = FakeAdapter(models=["answer-model"], efforts=["high"])
    # A second connection registered under a connection id the step input contract lists.
    other = FakeAdapter(models=["lit-model", "review-model"], efforts=["low"])
    app = create_app(Settings(data_dir=tmp_path / "data", port=8765), adapters={"fake": answer, "gemini": other},
                     http_client=openalex_client(), fetcher=fake_fetch, extra_hosts=("testserver",), trusted_clients=("testclient",))
    with TestClient(app) as client:
        session(client)
        rid = create(client, requested_model="answer-model", reasoning_effort="high",
                     literature_connection="gemini", literature_model="lit-model", literature_reasoning_effort="low",
                     review_mode="custom", review_connection="gemini", review_model="review-model")
        run_to_end(client, rid, "discovery")
        view = run_to_end(client, rid, "answer")
        assert set(answer.sent) == {("research_title", "answer-model", "high"),
                                    ("grounded_answer", "answer-model", "high")}
        assert set(other.sent) == {("search_plan", "lit-model", "low"), ("screening", "lit-model", "low"),
                                   ("answer_review", "review-model", None)}
        assert view["reviewer"] == {"mode": "custom", "connection": "gemini", "model": "review-model", "reasoning_effort": None}
        assert view["answers"][0]["review"]["model"]["connection"] == "gemini"
        revised = client.post(f"/api/researches/{rid}/scope", json={"question": "How is molecule release timing optimized?",
                                                                    "expected_version": view["research"]["version"]}).json()
        assert (revised["scope"]["literature_connection"], revised["scope"]["review_connection"]) == ("gemini", "gemini")

        body = {"question": "How is molecule release scheduling optimized?", "model_connection": "fake", "requested_model": "answer-model"}
        for bad in ({"literature_model": "lit-model"}, {"literature_connection": "gemini", "literature_model": "answer-model"},
                    {"literature_connection": "nope", "literature_model": "lit-model"}, {"literature_connection": "gemini"},
                    {"review_mode": "custom", "review_model": "review-model"}, {"review_connection": "gemini"}):
            assert client.post("/api/researches", json=body | bad).status_code == 422, bad


def test_model_defaults_are_kept_per_role_and_must_be_listed(tmp_path):
    with TestClient(app_for(tmp_path, FakeAdapter(models=["fake-model"], efforts=["low"]))) as client:
        session(client)
        assert {role: s["model"] for role, s in client.get("/api/settings").json().items()} == {"answer": None, "literature": None, "reviewer": None}
        saved = client.put("/api/settings/answer", json={"model_connection": "fake", "model": "fake-model", "reasoning_effort": "low"})
        assert saved.status_code == 200
        settings = client.get("/api/settings").json()
        assert (settings["answer"]["model"], settings["answer"]["reasoning_effort"]) == ("fake-model", "low")
        assert settings["literature"]["model"] is None and settings["reviewer"]["model"] is None  # roles do not share a default
        assert client.put("/api/settings/literature", json={"model_connection": "fake", "model": "unlisted"}).status_code == 422
        assert client.put("/api/settings/writer", json={"model_connection": "fake", "model": "fake-model"}).status_code == 422


def test_app_wide_reviewer_reviews_every_research_and_a_research_setting_overrides_it(tmp_path):
    adapter = FakeAdapter(models=["fake-model", "review-model", "other-reviewer"], efforts=["high"])
    with TestClient(app_for(tmp_path, adapter)) as client:
        session(client)
        assert client.get("/api/settings").json()["reviewer"]["model"] is None
        saved = client.put("/api/settings/reviewer", json={"model_connection": "fake", "model": "review-model", "reasoning_effort": "high"})
        assert saved.status_code == 200 and client.get("/api/settings").json()["reviewer"]["model"] == "review-model"

        def answered(**overrides):
            rid = create(client, source_scope="attached", **overrides)
            client.post(f"/api/researches/{rid}/uploads", files={"file": ("a.pdf", make_pdf(["SYNTHETIC molecule release schedule"]), "application/pdf")})
            return run_to_end(client, rid, "answer")

        view = answered()
        review = view["answers"][0]["review"]
        assert review["status"] == "completed" and review["model"]["requested_model"] == "review-model"
        assert view["answers"][0]["status"] == "structurally_valid"
        assert all(c["review"]["verdict"] == "supported" for c in view["answers"][0]["claims"])
        assert view["reviewer"] == {"mode": "default", "connection": "fake", "model": "review-model", "reasoning_effort": "high"}
        assert ("answer_review", "review-model", "high") in adapter.sent

        custom = answered(review_mode="custom", review_model="other-reviewer")
        assert custom["answers"][0]["review"]["model"]["requested_model"] == "other-reviewer"

        adapter.sent.clear()
        off = answered(review_mode="off")
        assert off["answers"][0]["review"] is None and off["reviewer"]["model"] is None
        assert off["answers"][0]["claims"][0]["review"] is None
        assert [task for task, _, _ in adapter.sent] == ["grounded_answer"]


def test_a_failed_review_is_recorded_without_pausing_or_changing_the_answer(tmp_path):
    adapter = FakeAdapter(responder=lambda si: "not json" if si["task_type"] == "answer_review" else valid_response(si),
                          models=["fake-model"])
    with TestClient(app_for(tmp_path, adapter)) as client:
        session(client)
        client.put("/api/settings/reviewer", json={"model_connection": "fake", "model": "fake-model"})
        view = run_to_end(client, attached_research(client), "answer")  # completed, not paused
        answer = view["answers"][0]
        assert answer["status"] == "structurally_valid" and answer["claims"]
        assert answer["review"]["status"] == "failed" and answer["review"]["failure_reason"] == "invalid_model_output"
        assert answer["review"]["issues"] and answer["claims"][0]["review"] is None
        assert [task for task, _, _ in adapter.sent].count("answer_review") == 2  # one repair, as for every model step


def test_pdf_collection_run_retrieves_open_pdfs_without_a_model_call_and_the_answer_does_not_fetch_again(tmp_path):
    fetched = []

    async def fetcher(url):
        fetched.append(url)
        return await fake_fetch(url)

    app = create_app(Settings(data_dir=tmp_path / "data", port=8765), adapters={"fake": FakeAdapter()},
                     http_client=openalex_client(), fetcher=fetcher, extra_hosts=("testserver",), trusted_clients=("testclient",))
    with TestClient(app) as raw:
        client = session(raw)
        rid = create(client)
        discovery = client.post(f"/api/researches/{rid}/runs", json={"kind": "discovery"}).json()
        wait_run(client, rid, discovery["id"])
        collection = client.post(f"/api/researches/{rid}/runs", json={"kind": "pdf_collection"}).json()
        view, run = wait_run(client, rid, collection["id"])
        assert run["status"] == "completed", run
        assert run["usage"].get("model_calls", 0) == 0 and fetched
        assert {s["kind"] for s in run["steps"]} <= {"fetch_pdf", "pdf_other_copy"}
        source = next(s for s in view["sources"] if s["doi"] == "10.1/a")
        assert source["has_pdf_text"] is True
        assert next(s for s in view["sources"] if s["doi"] is None)["has_pdf_text"] is False  # abstract only

        answer = client.post(f"/api/researches/{rid}/runs", json={"kind": "answer"}).json()
        _, answered = wait_run(client, rid, answer["id"])
        assert answered["status"] == "completed", answered
        assert not [s for s in answered["steps"] if s["kind"] in ("fetch_pdf", "pdf_other_copy")]


def test_dropped_pdfs_are_matched_to_included_sources_by_doi_or_title_and_not_attached(tmp_path):
    with TestClient(app_for(tmp_path)) as raw:
        client = session(raw)
        rid = create(client)
        discovery = client.post(f"/api/researches/{rid}/runs", json={"kind": "discovery"}).json()
        view, _ = wait_run(client, rid, discovery["id"])
        by_doi = next(s for s in view["sources"] if s["doi"] == "10.1/a")
        by_title = next(s for s in view["sources"] if s["title"] == "SYNTHETIC molecule schedule letter")
        files = [
            ("files", ("a.pdf", make_pdf(["SYNTHETIC paper. https://doi.org/10.1/a."]), "application/pdf")),
            ("files", ("b.pdf", make_pdf(["SYNTHETIC molecule\nschedule letter", "Molecule schedule letter."]), "application/pdf")),
            ("files", ("c.pdf", make_pdf(["SYNTHETIC unrelated notes"]), "application/pdf")),
        ]
        response = client.post(f"/api/researches/{rid}/uploads/match", files=files)
        assert response.status_code == 200, response.text
        included = {s["source_version_id"] for s in view["sources"] if s["selection"]["state"] == "included"}
        expected = [("a.pdf", by_doi["source_version_id"] if by_doi["source_version_id"] in included else None),
                    ("b.pdf", by_title["source_version_id"] if by_title["source_version_id"] in included else None), ("c.pdf", None)]
        assert expected[0][1] and expected[1][1]  # both sources are included by the fake screening
        assert [(m["filename"], m["source_version_id"]) for m in response.json()["matches"]] == expected
        after = client.get(f"/api/researches/{rid}").json()
        assert not any(s["access"]["assets"] for s in after["sources"])  # a match attaches nothing
