"""The browser fixture's parity-harness markers, driven without a socket (SYNTHETIC records, scripted model).

Each test reaches the state a Playwright spec needs from one question marker of `fixture_server.py` and asserts what the
page reads. Passing shows the fixture produces the state through the app's own routes; it says nothing about model
quality or live provider access.
"""

import time

import httpx
import pytest
from fastapi.testclient import TestClient

import fixture_server as fx
from deixis.api.app import create_app
from deixis.config import Settings
from helpers import make_pdf

ACTIVE = ("queued", "running", "pause_requested")


@pytest.fixture(autouse=True)
def clean_markers(monkeypatch):
    """Module flags are globals: every test starts and ends with them reset, so nothing leaks to the next test."""
    fx.reset_markers()
    monkeypatch.setattr(fx, "JOBS_FETCH_SECONDS", 1.5)
    monkeypatch.setattr(fx, "NO_INCLUDE_HOLD_SECONDS", 1.0)
    yield
    fx.reset_markers()


def client_for(tmp_path, *, fulltext=False):
    scripted = fx.ScriptedCodex(tmp_path)
    app = create_app(
        Settings(data_dir=tmp_path, port=8877, model_concurrency=1, search_query="code",
                 fulltext_fetch="auto" if fulltext else "off", fulltext_adjudication="auto" if fulltext else "off"),
        adapters={"codex": scripted}, http_client=httpx.AsyncClient(transport=httpx.MockTransport(fx.openalex)),
        fetcher=fx.fetch, extra_hosts=("testserver",), trusted_clients=("testclient",))
    scripted.app = app
    client = TestClient(app)
    return client


def start(client):
    client.headers["x-deixis-csrf"] = client.get("/api/session").json()["csrf_token"]


def research(client, question, effort="quick", scope="academic"):
    response = client.post("/api/researches", json={"question": question, "model_connection": "codex",
                                                    "requested_model": fx.MODEL, "effort": effort, "source_scope": scope})
    assert response.status_code == 201, response.text
    return response.json()["research"]["id"]


def view(client, rid):
    return client.get(f"/api/researches/{rid}").json()


def settle(client, rid, kinds=("discovery", "answer"), deadline=90.0):
    """Wait until a run of each kind exists and no run of the research is active."""
    end = time.time() + deadline
    while time.time() < end:
        v = view(client, rid)
        if all(any(r["kind"] == k for r in v["runs"]) for k in kinds) and not any(r["status"] in ACTIVE for r in v["runs"]):
            return v
        time.sleep(0.05)
    raise AssertionError(f"the research did not settle: {[(r['kind'], r['status']) for r in view(client, rid)['runs']]}")


def discover(client, rid):
    response = client.post(f"/api/researches/{rid}/runs", json={"kind": "discovery"})
    assert response.status_code == 202, response.text
    return response.json()["id"]


def upload(client, rid, name, pages):
    response = client.post(f"/api/researches/{rid}/uploads",
                           files={"file": (name, make_pdf(pages), "application/pdf")})
    assert response.status_code == 201, response.text
    return response.json()["uploaded_source_version_id"]


def test_parity_counts(tmp_path):
    question = ("[parity] How has the relationship between k-connectivity, network lifetime and energy consumption "
                "been modeled in SYNTHETIC wireless sensor networks?")
    with client_for(tmp_path, fulltext=True) as client:
        start(client)
        rid = research(client, question, effort="standard")
        discover(client, rid)
        v = settle(client, rid)
        counts = v["counts"]
        boxes = {b["key"]: b["count"] for b in counts["flow_boxes"]["boxes"]}
        assert (counts["found"], counts["unique"]) == (fx.PARITY_TOTAL, fx.PARITY_TOTAL)
        assert boxes["abstract_read_by_model"] == 50  # Standard N
        assert counts["funnel"]["candidates"] == fx.PARITY_PASS
        assert boxes["out_of_scope_model"] == 50 - fx.PARITY_PASS
        assert boxes["fulltext_read"] == 20  # Standard K
        assert counts["included"] == 17 and counts["queue"] == 3
        assert counts["cited"] == fx.PARITY_CITED
        # The Sources list's per-work screening (S13): the works that passed the abstract stage are the funnel's
        # candidates, an included work shows its full-text decision, and other versions carry none.
        records = [s for s in v["sources"] if s["version_role"] == "record"]
        assert sum(s["screening"]["passed_abstract"] for s in records) == counts["funnel"]["candidates"]
        assert all(s["screening"] is None for s in v["sources"] if s["version_role"] == "other_version")
        assert all(s["screening"]["stage"] == "fulltext" and s["screening"]["outcome"] == "include"
                   for s in records if s["selection"]["state"] == "included" and s["selection"]["origin"] != "user")
        assert {s["screening"]["outcome"] for s in records if s["screening"]["stage"] == "abstract"} <= {"candidate", "out_of_scope", "unresolved"}
        rows = client.get(f"/api/researches/{rid}/queue").json()["rows"]
        assert sorted(r["kind"] for r in rows) == ["choose_run", "confirm_quote", "find_part"]
        first = [a for a in v["answers"] if a["status"] == "structurally_valid"]
        assert len(first) == 1
        assert first[0]["unanswered_aspects"] == list(fx.PARITY_UNANSWERED)  # Home's "Suggested" cards (S5b)

        # V2: a second answer run, as "Generate a new answer" asks; the first answer stays as it was.
        assert client.post(f"/api/researches/{rid}/runs", json={"kind": "answer"}).status_code == 202
        time.sleep(0.2)
        v = settle(client, rid)
        answers = [a for a in v["answers"] if a["status"] == "structurally_valid"]
        assert len(answers) == 2 and first[0]["id"] in {a["id"] for a in answers}
        assert sorted(a["report_version"] for a in answers) == [1, 2]

        # The study table the harness may build: six included sources, four text columns, one fill.
        included = [s["source_version_id"] for s in v["sources"]
                    if s["version_role"] == "record" and s["selection"]["state"] == "included"][:6]
        table = client.post(f"/api/researches/{rid}/tables", json={"title": "SYNTHETIC study table", "rows": included})
        assert table.status_code == 201, table.text
        table = table.json()
        path = f"/api/researches/{rid}/tables/{table['table']['id']}"
        for name in ("Network model", "k", "Lifetime definition", "Energy model"):
            response = client.post(path + "/columns", json={
                "name": name, "instruction": f"State the {name.lower()} the source uses.", "answer_format": "text",
                "expected_version": table["table"]["version"]})
            assert response.status_code == 201, response.text
            table = response.json()
        response = client.post(path + "/fill", json={"expected_version": table["table"]["version"]})
        assert response.status_code == 202, response.text
        time.sleep(0.2)
        settle(client, rid)
        table = client.get(path).json()
        assert len(table["rows"]) == 6 and len(table["columns"]) == 4
        # Filled cells arrive as proposals the person accepts or not; every one of the 24 has one.
        assert sum(1 for cell in table["cells"] if cell["current"] or cell["pending_proposal"]) == 24, table["cells"][:2]


def test_oa_quota_refuses_later_keyword_pages(tmp_path):
    with client_for(tmp_path) as client:
        start(client)
        rid = research(client, "[oa-quota] How is molecule release scheduled with bisection in relay networks?")
        discover(client, rid)
        v = settle(client, rid)
        discovery = next(r for r in v["runs"] if r["kind"] == "discovery")
        assert discovery["status"] == "completed", discovery
        refused = [s for s in v["search_runs"] if s["status"] == "rate_limited"]
        assert refused and all((s.get("error") or {}).get("error_kind") == "quota_exhausted" for s in refused), v["search_runs"]
        # The keyword query's second page is the one refused; its first page and the semantic page answered.
        assert any(s["page_number"] == 1 and not s["query_text"].startswith("chain:") for s in refused)
        assert any(s["status"] == "completed" and s["result_count"] for s in v["search_runs"])
        assert v["counts"]["unique"] == len(fx.WORKS)


def test_no_passages_answer(tmp_path):
    with client_for(tmp_path) as client:
        start(client)
        rid = research(client, "[no-passages] How is molecule release scheduled with bisection in relay networks?")
        discover(client, rid)
        v = settle(client, rid)
        answer = next(a for a in v["answers"])
        assert answer["status"] == "no_evidence"
        assert answer["validation"]["reason"] != "no_includable_source"  # the page's "No text passages…" branch


def selection_version(client, rid, svid):
    return next(s for s in view(client, rid)["sources"] if s["source_version_id"] == svid)["selection"]["version"]


def test_no_include_answer(tmp_path):
    with client_for(tmp_path) as client:
        start(client)
        # One run per research at a time, and one worker for all: a title run of another research holds the worker,
        # so this research's answer run waits queued while the person takes their one included file out.
        hold = research(client, "[no-include] SYNTHETIC holding research", scope="attached")
        upload(client, hold, "SYNTHETIC hold.pdf", fx.SEED_PAGES)
        rid = research(client, "[no-include] What do SYNTHETIC attached notes say about release timing?", scope="attached")
        svid = upload(client, rid, "SYNTHETIC notes.pdf", fx.SEED_PAGES[::-1])
        assert client.post(f"/api/researches/{hold}/runs", json={"kind": "research_title"}).status_code == 202
        time.sleep(0.2)
        assert client.post(f"/api/researches/{rid}/runs", json={"kind": "answer"}).status_code == 202
        response = client.patch(f"/api/researches/{rid}/selections/{svid}",
                                json={"state": "excluded", "expected_version": selection_version(client, rid, svid)})
        assert response.status_code == 200, response.text
        assert next(r for r in view(client, rid)["runs"] if r["kind"] == "answer")["status"] == "queued"
        v = settle(client, rid, kinds=("answer",))
        answer = next(a for a in v["answers"])
        assert (answer["status"], answer["validation"]["reason"]) == ("no_evidence", "no_includable_source")


def test_jobs_running_pdf_collection(tmp_path):
    with client_for(tmp_path) as client:
        start(client)
        rid = research(client, "[jobs-running] How is molecule release scheduled in SYNTHETIC relay networks?")
        discover(client, rid)
        v = settle(client, rid)
        for source in [s for s in v["sources"] if s["version_role"] == "record"]:
            response = client.patch(f"/api/researches/{rid}/selections/{source['source_version_id']}",
                                    json={"state": "included", "expected_version": source["selection"]["version"]})
            assert response.status_code == 200, response.text
        run_id = client.post(f"/api/researches/{rid}/runs", json={"kind": "pdf_collection"}).json()["id"]
        seen_running = False
        end = time.time() + 30
        while time.time() < end:
            summary = next(r for r in client.get("/api/researches").json() if r["id"] == rid)
            run = next(r for r in view(client, rid)["runs"] if r["id"] == run_id)
            if run["status"] == "running":
                seen_running = True
                assert (summary["last_run_kind"], summary["last_run_status"]) == ("pdf_collection", "running")
            if run["status"] not in ACTIVE:
                break
            time.sleep(0.1)
        assert seen_running and run["status"] == "completed", run
        assert all(s["has_pdf_text"] for s in view(client, rid)["sources"] if s["version_role"] == "record")


def test_pause_at_read_then_resume(tmp_path):
    with client_for(tmp_path, fulltext=True) as client:
        start(client)
        rid = research(client, "[pause-at-read] How is molecule release scheduled with bisection in relay networks?")
        run_id = discover(client, rid)
        end = time.time() + 30
        while time.time() < end:
            run = next(r for r in view(client, rid)["runs"] if r["id"] == run_id)
            if run["status"] not in ACTIVE:
                break
            time.sleep(0.05)
        assert (run["status"], run["pause_reason"], run["stage"]) == ("paused", "user_requested", "screening"), run
        assert client.post(f"/api/runs/{run_id}/resume").status_code == 200
        v = settle(client, rid)
        assert next(r for r in v["runs"] if r["id"] == run_id)["status"] == "completed"
        assert any(a["status"] == "structurally_valid" for a in v["answers"])


def test_stale_seed_then_current_text(tmp_path):
    with client_for(tmp_path) as client:
        start(client)
        rid = research(client, "[stale-seed] How are k-connected SYNTHETIC sensor networks kept alive?",
                       scope="attached_and_academic")
        svid = upload(client, rid, "SYNTHETIC seed.pdf", fx.SEED_PAGES)
        v = view(client, rid)
        response = client.post(f"/api/researches/{rid}/seed", json={"source_version_ids": [svid],
                                                                    "expected_version": v["research"]["version"]})
        assert response.status_code == 200, response.text
        assert response.json()["scope"]["seed_status"] == "ready"
        discover(client, rid)
        settle(client, rid)
        end = time.time() + 10
        while view(client, rid)["scope"]["seed_status"] != "stale" and time.time() < end:
            time.sleep(0.05)
        v = view(client, rid)
        assert v["scope"]["seed_status"] == "stale"
        revision = v["scope"]["revision"]
        # "Use current PDF text": the same seeds again, frozen from the file now in use, in a new scope revision.
        response = client.post(f"/api/researches/{rid}/seed", json={"source_version_ids": [svid],
                                                                    "expected_version": v["research"]["version"]})
        assert response.status_code == 200, response.text
        assert (response.json()["scope"]["revision"], response.json()["scope"]["seed_status"]) == (revision + 1, "ready")
