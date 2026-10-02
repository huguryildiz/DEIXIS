"""Report API and read-model checks using only synthetic evidence and model output."""

import asyncio

import pytest
from fastapi.testclient import TestClient

from deixis.domain.rules import MAX_SCHEMA_REPAIRS
from deixis.storage.db import new_id
from deixis.workflow.report.sections import ROUNDS, run_report
from deixis.workflow.report.store import REPORT_CALL_FLOOR, ReportStore
from deixis.workflow.tables import TableStore
from deixis.workflow.views import report_view, research_view
from helpers import make_pdf
from test_api_flow import app_for, create, session, wait_run
from test_report_flow import COLUMN, FUTURE_WORK_COLUMN, LIMITATIONS_COLUMN, ReportAdapter, report_flow


@pytest.mark.parametrize("case,expected", [("success", 200), ("unknown_link", 422), ("other_link", 422),
    ("other_research", 404), ("running", 409), ("two_tabs", 409), ("long_id", 422), ("too_many", 422),
    ("different_replay", 409), ("equal_replay", 200)])
def test_citation_edit_route_without_models_or_worker(tmp_path, case, expected):
    import httpx
    from deixis.api.app import create_app
    from deixis.config import Settings
    from tests.test_report_assembly import report_with_sections
    from tests.test_report_edit_check import finish
    fixture = report_with_sections.__wrapped__(tmp_path)
    lib = next(fixture)
    try:
        rid = finish(lib)
        cid = lib["store"].conn.execute("SELECT id FROM report_claims WHERE claim_key = 'III.1'").fetchone()[0]
        other_link = lib["store"].conn.execute("SELECT id FROM report_citation_links WHERE claim_id <> ?", (cid,)).fetchone()[0]
        if case == "other_research":
            rid = lib["store"].create_research("SYNTHETIC other", "attached", "quick", [], "fake", "fake", "en")
        elif case == "running":
            lib["store"].update_run(lib["reports"].report(lib["report_id"])["run_id"], status="running")
        def refuse_http(request):
            raise AssertionError("No network or provider call is allowed")
        http = httpx.AsyncClient(transport=httpx.MockTransport(refuse_http))
        app = create_app(Settings(data_dir=tmp_path), adapters={}, http_client=http, start_worker=False,
                         extra_hosts=("testserver",), trusted_clients=("testclient",))
        with TestClient(app) as client:
            session(client)
            url = f"/api/researches/{rid}/reports/{lib['report_id']}/claims/{cid}"
            body = {"link_ids": [], "expected_version": 1}
            headers = {"Idempotency-Key": "citation-edit"}
            if case in {"two_tabs", "equal_replay", "different_replay"}:
                first = client.put(url, json=body, headers=headers)
                assert first.status_code == 200
            if case == "two_tabs":
                body = {"text": "SYNTHETIC second tab", "expected_version": 1}
                headers = {}
            elif case == "different_replay":
                body["text"] = "different request"
            elif case == "unknown_link":
                body["link_ids"] = ["rln_unknown"]
            elif case == "other_link":
                body["link_ids"] = [other_link]
            elif case == "long_id":
                body["link_ids"] = ["x" * 41]
            elif case == "too_many":
                body["link_ids"] = ["x"] * 201
            def counts():
                return tuple(app.state.store.conn.execute("SELECT (SELECT COUNT(*) FROM report_claim_revisions),"
                                                        " (SELECT COUNT(*) FROM events)").fetchone())
            before = counts()
            response = client.put(url, json=body, headers=headers)
            assert response.status_code == expected, response.text
            if case != "success":
                assert counts() == before
            if expected == 200:
                view = response.json()
                edited = next(c for s in view["sections"] for c in s["claims"] if c["id"] == cid)
                assert edited["evidence"] == [] and len(edited["removed_links"]) == 1
                assert edited["evidence_basis"] == "none" and edited["support_type_note"] == "model_written_type"
                assert edited["version"] == 2 and view["has_human_edits"] is True
                if case == "equal_replay":
                    assert response.json() == first.json()
        asyncio.run(http.aclose())
    finally:
        with pytest.raises(StopIteration):
            next(fixture)


@pytest.mark.parametrize("case,expected", [("running", 409), ("other", 404), ("unknown", 404),
                                          ("csrf", 403), ("success", 200)])
def test_check_edits_route_without_model_or_worker(tmp_path, case, expected):
    import httpx
    from deixis.api.app import create_app
    from deixis.config import Settings
    from tests.test_report_assembly import report_with_sections
    from tests.test_report_edit_check import finish, edit
    fixture = report_with_sections.__wrapped__(tmp_path)
    lib = next(fixture)
    try:
        rid = finish(lib, "draft")
        edit(lib, "A novel SYNTHETIC revision.")
        if case == "running":
            lib["store"].update_run(lib["reports"].report(lib["report_id"])["run_id"], status="running")
        if case == "other":
            rid = lib["store"].create_research("SYNTHETIC other research", "attached", "quick", [], "fake", "fake", "en")
        report_id = "rpt_unknown" if case == "unknown" else lib["report_id"]
        def refuse_http(request):
            raise AssertionError("No provider or network call is allowed")
        http = httpx.AsyncClient(transport=httpx.MockTransport(refuse_http))
        app = create_app(Settings(data_dir=tmp_path), adapters={}, http_client=http,
                         start_worker=False, extra_hosts=("testserver",), trusted_clients=("testclient",))
        with TestClient(app) as client:
            if case != "csrf":
                session(client)
            response = client.post(f"/api/researches/{rid}/reports/{report_id}/check-edits")
            assert response.status_code == expected, response.text
            if case == "success":
                view = response.json()
                assert view["has_human_edits"] is True and view["edited_after_version"] is None
                assert view["edit_check"]["current"] is True
                assert view["edit_check"]["errors"] == 1
                assert view["edit_check"]["skipped"] == 1
                assert view["edit_check"]["skipped_rules"] == [{"rule": "phrase_frames", "section_id": "III",
                                                             "claim_key": "III.1", "reason": "human_text"}]
                assert client.get(f"/api/researches/{rid}/reports/{report_id}").json()["edit_check"] == view["edit_check"]
        asyncio.run(http.aclose())
    finally:
        with pytest.raises(StopIteration):
            next(fixture)


def upload_and_include(client, research_id):
    response = client.post(
        f"/api/researches/{research_id}/uploads",
        files={"file": ("report.pdf", make_pdf([
            "SYNTHETIC evidence states that molecule release scheduling uses a bounded formulation."
        ]), "application/pdf")},
    )
    assert response.status_code == 201, response.text
    return response.json()["sources"][0]["source_version_id"]


def create_table(client, research_id, *, with_columns):
    response = client.post(f"/api/researches/{research_id}/tables", json={"title": "SYNTHETIC evidence"})
    assert response.status_code == 201, response.text
    view = response.json()
    if with_columns:
        for column in (COLUMN, LIMITATIONS_COLUMN, FUTURE_WORK_COLUMN):
            body = column | {"expected_version": view["table"]["version"]}
            response = client.post(
                f"/api/researches/{research_id}/tables/{view['table']['id']}/columns", json=body,
            )
            assert response.status_code == 201, response.text
            view = response.json()
    return view


def fill_table(client, research_id, view):
    response = client.post(
        f"/api/researches/{research_id}/tables/{view['table']['id']}/fill",
        json={"expected_version": view["table"]["version"]},
    )
    assert response.status_code == 202, response.text
    _, run = wait_run(client, research_id, response.json()["id"])
    assert run["status"] == "completed"


def test_start_report_refuses_a_table_without_columns_and_creates_nothing(tmp_path):
    with TestClient(app_for(tmp_path, ReportAdapter())) as raw:
        client = session(raw)
        research_id = create(client, source_scope="attached", effort="standard")
        upload_and_include(client, research_id)
        table_id = create_table(client, research_id, with_columns=False)["table"]["id"]

        response = client.post(f"/api/researches/{research_id}/reports", json={"table_id": table_id})

        assert response.status_code == 409
        assert [run for run in client.get(f"/api/researches/{research_id}").json()["runs"]
                if run["kind"] == "report"] == []
        assert raw.app.state.store.conn.execute("SELECT COUNT(*) FROM reports").fetchone()[0] == 0


@pytest.mark.parametrize("effort", ["quick", "standard"])
def test_start_report_returns_an_idempotent_run_with_both_target_ids(tmp_path, effort):
    with TestClient(app_for(tmp_path, ReportAdapter())) as raw:
        client = session(raw)
        research_id = create(client, source_scope="attached", effort=effort)
        upload_and_include(client, research_id)
        table = create_table(client, research_id, with_columns=True)
        fill_table(client, research_id, table)
        url = f"/api/researches/{research_id}/reports"

        started = client.post(url, json={"table_id": table["table"]["id"]}, headers={"Idempotency-Key": "r1"})
        replay = client.post(url, json={"table_id": table["table"]["id"]}, headers={"Idempotency-Key": "r1"})

        assert started.status_code == 202, started.text
        assert replay.status_code == 202, replay.text
        assert replay.json()["id"] == started.json()["id"]
        assert started.json()["budget"]["max_model_calls"] == max(REPORT_CALL_FLOOR, (
            1 + sum(map(len, ROUNDS)) + 1 + sum(map(len, ROUNDS))
        ) * (1 + MAX_SCHEMA_REPAIRS)) == 50
        assert started.json()["budget"]["max_provider_requests"] == 0
        assert started.json()["target"] == {
            "table_id": table["table"]["id"],
            "report_id": started.json()["target"]["report_id"],
        }
        assert raw.app.state.store.conn.execute("SELECT COUNT(*) FROM reports").fetchone()[0] == 1
        _, report_run = wait_run(client, research_id, started.json()["id"])
        assert report_run["status"] == "completed"
        report_id = started.json()["target"]["report_id"]
        detail = client.get(f"{url}/{report_id}")
        assert detail.status_code == 200
        assert detail.json()["id"] == report_id
        summaries = client.get(url)
        assert summaries.status_code == 200
        assert summaries.json() == [{
            "id": report_id,
            "status": "valid",
            "report_version": 1,
            "created_at": summaries.json()[0]["created_at"],
        }]


def test_report_run_completes_with_fake_adapter_and_produces_a_valid_report(tmp_path):
    with TestClient(app_for(tmp_path, ReportAdapter())) as raw:
        client = session(raw)
        research_id = create(client, source_scope="attached", effort="quick")
        upload_and_include(client, research_id)
        table = create_table(client, research_id, with_columns=True)
        fill_table(client, research_id, table)
        url = f"/api/researches/{research_id}/reports"

        started = client.post(
            url,
            json={"table_id": table["table"]["id"]},
            headers={"Idempotency-Key": "report-end-to-end"},
        )

        assert started.status_code == 202, started.text
        _, report_run = wait_run(client, research_id, started.json()["id"])
        assert report_run["status"] == "completed"
        assert report_run["pause_reason"] is None

        report_id = started.json()["target"]["report_id"]
        response = client.get(f"{url}/{report_id}")
        assert response.status_code == 200, response.text
        report = response.json()
        assert report["status"] == "valid"
        assert report["report_version"] == 1
        assert [section["section_id"] for section in report["sections"]] == [
            "abstract", "index_terms", "I", "II", "III", "IV", "V", "VI", "VII", "VIII", "IX",
        ]
        assert all(section["draft"] for section in report["sections"])

        citation_links = [
            link
            for section in report["sections"]
            for claim in section["claims"]
            for link in claim["evidence"]
        ]
        assert citation_links
        assert all(link["anchor_text"] for link in citation_links)
        assert all(bool(link["passage_id"]) != bool(link["cell_id"]) for link in citation_links)

        research = client.get(f"/api/researches/{research_id}")
        assert research.status_code == 200, research.text
        summary = next(item for item in research.json()["reportRuns"] if item["id"] == report_id)
        assert summary["status"] == "valid"
        assert summary["report_version"] == 1


def test_report_routes_reject_unknown_and_cross_research_ids(tmp_path):
    with TestClient(app_for(tmp_path, ReportAdapter())) as raw:
        client = session(raw)
        first = create(client, source_scope="attached")
        second = create(client, source_scope="attached")

        assert client.get(f"/api/researches/{first}/reports/rpt_unknown000").status_code == 404

        store = raw.app.state.store
        run = store.create_run(second, "report", {"max_model_calls": 1, "max_provider_requests": 0}, None,
                               {"table_id": "tbl_synthetic"})
        report_id = ReportStore(store).create_report(second, run["id"], run["scope_revision"], "en")
        assert client.get(f"/api/researches/{first}/reports/{report_id}").status_code == 404


def test_research_view_lists_only_report_summaries(tmp_path):
    _, store, _, _, run, _, report_id = report_flow(tmp_path)

    view = research_view(store, run["research_id"])

    assert view["reportRuns"] == [{
        "id": report_id,
        "status": "in_progress",
        "report_version": None,
        "created_at": view["reportRuns"][0]["created_at"],
    }]
    assert set(view["reportRuns"][0]) == {"id", "status", "report_version", "created_at"}
    assert "sections" not in view["reportRuns"][0]


def test_report_view_returns_ordered_sections_claims_and_citation_anchors(tmp_path):
    flow, store, _, _, run, scope, report_id = report_flow(tmp_path)
    asyncio.run(run_report(flow, run, scope))

    view = report_view(store, run["research_id"], report_id)
    viii = next(section for section in view["sections"] if section["section_id"] == "VIII")
    assert viii["draft"]["text"]
    assert viii["validation"]["numbers"]["kind"] == "limitations"

    assert [section["section_id"] for section in view["sections"]] == [
        "abstract", "index_terms", "I", "II", "III", "IV", "V", "VI", "VII", "VIII", "IX",
    ]
    cited_claims = [claim for section in view["sections"] for claim in section["claims"] if claim["evidence"]]
    assert cited_claims
    assert all({"id", "version", "claim_key", "text", "model_text", "edited", "warnings", "revisions",
                "support_type", "evidence", "paragraph", "table_ref", "equation_ref", "original_evidence_count",
                "removed_links", "evidence_basis", "support_type_note", "edited_basis"} == set(claim) for claim in cited_claims)
    assert all(set(link) == {"link_id", "passage_id", "cell_id", "source_version_id", "ref_number", "anchor_text", "anchor_match", "open_passage_id"}
               for claim in cited_claims for link in claim["evidence"])
    assert all(link["anchor_text"] for claim in cited_claims for link in claim["evidence"])
    assert all(bool(link["passage_id"]) != bool(link["cell_id"])
               for claim in cited_claims for link in claim["evidence"])
    assert view["run"] == {"id": run["id"], "status": "running", "pause_reason": None}
    assert view["table_i"] is not None
    assert all(row["source_key"] for row in view["table_i"]["rows"])
    assert [ref["number"] for ref in view["references"]] == list(range(1, len(view["references"]) + 1))
    assert {link["ref_number"] for claim in cited_claims for link in claim["evidence"]} == \
        {ref["number"] for ref in view["references"]}


def test_report_view_numbers_source_versions_and_keeps_frozen_table(tmp_path):
    flow, store, _, _, run, scope, report_id = report_flow(tmp_path)
    asyncio.run(run_report(flow, run, scope))
    research_id = run["research_id"]
    before = report_view(store, research_id, report_id)
    frozen = before["table_i"]["cells"][0]
    table_id = run["target"]["table_id"]
    cell = TableStore(store).cell_view(research_id, table_id, frozen["column_id"], frozen["source_version_id"])
    TableStore(store).edit_cell(research_id, table_id, frozen["column_id"], frozen["source_version_id"],
                                "not_verified", {"text": "SYNTHETIC edited later"}, None, None,
                                cell["version"], None)
    assert report_view(store, research_id, report_id)["table_i"]["cells"][0]["value"] == frozen["value"]

    other = store.create_upload_source("SYNTHETIC second source")
    passage = store._insert_passage(other, None, "abstract", None, None, "synthetic_fixture", None, None,
                                    "SYNTHETIC second passage")
    claims = [claim for section in before["sections"] for claim in section["claims"] if claim["evidence"]]
    assert len(claims) >= 3
    first_link = store.conn.execute("SELECT * FROM report_citation_links WHERE claim_id = ? LIMIT 1",
                                    (claims[0]["id"],)).fetchone()
    store.conn.execute("DELETE FROM report_citation_links WHERE claim_id = ?", (claims[1]["id"],))
    store.conn.execute("INSERT INTO report_citation_links"
                       " (id, claim_id, passage_id, cell_id, source_version_id, step_input_id, anchor_text, anchor_match)"
                       " VALUES (?, ?, ?, NULL, ?, ?, ?, 'exact')",
                       (new_id("rcl"), claims[1]["id"], passage, other, first_link["step_input_id"],
                        "SYNTHETIC second passage"))
    store.conn.execute("DELETE FROM report_citation_links WHERE claim_id = ?", (claims[2]["id"],))
    store.conn.execute("INSERT INTO report_citation_links"
                       " (id, claim_id, passage_id, cell_id, source_version_id, step_input_id, anchor_text, anchor_match)"
                       " VALUES (?, ?, NULL, ?, ?, ?, ?, 'exact')",
                       (new_id("rcl"), claims[2]["id"], frozen["cell_id"], frozen["source_version_id"],
                        first_link["step_input_id"], "SYNTHETIC"))
    numbered = report_view(store, research_id, report_id)
    links = [claim["evidence"] for section in numbered["sections"] for claim in section["claims"] if claim["evidence"]]
    assert links[0][0]["ref_number"] == 1
    assert links[1][0]["ref_number"] == 2
    assert links[2][0]["ref_number"] == 1
    assert links[2][0]["cell_id"] == frozen["cell_id"]
    assert numbered["references"][1]["open_passage_id"] == passage
    # A cell link opens the frozen evidence passage whose quote holds the located anchor, not just the first one.
    from deixis.domain.contracts import locate_anchor
    from deixis.workflow.report.store import ReportStore
    evidence = next(c for c in ReportStore(store).snapshot(report_id)["cells"] if c["cell_id"] == frozen["cell_id"])["evidence"]
    expected = next((e["passage_id"] for e in evidence if e["quote"] and locate_anchor("SYNTHETIC", e["quote"])), None)
    assert links[2][0]["open_passage_id"] == expected
    assert links[1][0]["open_passage_id"] == passage


def test_research_view_has_an_empty_report_summary_list(tmp_path):
    _, store, _, _, _, _, _ = report_flow(tmp_path)
    research_id = store.create_research(
        "How is a SYNTHETIC system evaluated?", "attached", "quick", [], "fake", "fake-model", "en",
    )

    assert research_view(store, research_id)["reportRuns"] == []


def test_report_edit_and_acknowledgement_routes_require_current_state_and_csrf(tmp_path):
    with TestClient(app_for(tmp_path, ReportAdapter())) as client:
        session(client)
        research_id = create(client, source_scope="attached", effort="quick")
        upload_and_include(client, research_id)
        table = create_table(client, research_id, with_columns=True)
        fill_table(client, research_id, table)
        started = client.post(f"/api/researches/{research_id}/reports",
                              json={"table_id": table["table"]["id"]})
        assert started.status_code == 202
        report_id = started.json()["target"]["report_id"]
        _, run = wait_run(client, research_id, started.json()["id"])
        assert run["status"] == "completed"
        report_url = f"/api/researches/{research_id}/reports/{report_id}"
        view = client.get(report_url).json()
        claim = next(c for s in view["sections"] for c in s["claims"]
                     if any(link["cell_id"] for link in c["evidence"]))
        section = next(s for s in view["sections"] if claim in s["claims"])
        edit_url = f"{report_url}/claims/{claim['id']}"
        body = {"text": "SYNTHETIC human correction", "expected_version": 1}
        assert client.put(edit_url, json=body, headers={"x-deixis-csrf": ""}).status_code == 403
        edited = client.put(edit_url, json=body)
        assert edited.status_code == 200, edited.text
        edited_claim = next(c for s in edited.json()["sections"] for c in s["claims"] if c["id"] == claim["id"])
        assert edited_claim["evidence"] == claim["evidence"]
        assert edited.json()["report_version"] == view["report_version"]
        assert client.put(edit_url, json=body).status_code == 409
        cell_id = next(link["cell_id"] for link in claim["evidence"] if link["cell_id"])
        cell = client.app.state.store.conn.execute(
            "SELECT table_id, column_id, source_version_id, version FROM evidence_cells WHERE id = ?", (cell_id,),
        ).fetchone()
        cell_url = (f"/api/researches/{research_id}/tables/{cell['table_id']}/cells/"
                    f"{cell['column_id']}/{cell['source_version_id']}")
        changed = client.put(cell_url, json={"state": "not_verified", "value": {"text": "SYNTHETIC changed"},
                                             "expected_version": cell["version"]})
        assert changed.status_code == 200, changed.text
        key = client.get(report_url).json()["sections"][[s["section_id"] for s in view["sections"]].index(
            section["section_id"])]["evidence_changes"]["open"][0]["key"]
        ack_url = f"{report_url}/sections/{section['section_id']}/acknowledge-changes"
        assert client.post(ack_url, json={"change_keys": [key]}, headers={"x-deixis-csrf": ""}).status_code == 403
        acknowledged = client.post(ack_url, json={"change_keys": [key]})
        assert acknowledged.status_code == 200, acknowledged.text
        assert acknowledged.json()["sections"][[s["section_id"] for s in view["sections"]].index(
            section["section_id"])]["evidence_changes"]["acknowledged_count"] == 1
        assert client.post(ack_url, json={"change_keys": [key]}).status_code == 409
