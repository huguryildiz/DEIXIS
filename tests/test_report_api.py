"""Report API and read-model checks using only synthetic evidence and model output."""

import asyncio

import pytest
from fastapi.testclient import TestClient

from deixis.domain.rules import MAX_SCHEMA_REPAIRS
from deixis.workflow.report.sections import ROUNDS, run_report
from deixis.workflow.report.store import REPORT_CALL_FLOOR, ReportStore
from deixis.workflow.views import report_view, research_view
from helpers import make_pdf
from test_api_flow import app_for, create, session, wait_run
from test_report_flow import COLUMN, FUTURE_WORK_COLUMN, LIMITATIONS_COLUMN, ReportAdapter, report_flow


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
            "abstract", "I", "II", "III", "IV", "V", "VI", "VII", "VIII", "IX", "index_terms",
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

    assert [section["section_id"] for section in view["sections"]] == [
        "abstract", "I", "II", "III", "IV", "V", "VI", "VII", "VIII", "IX", "index_terms",
    ]
    cited_claims = [claim for section in view["sections"] for claim in section["claims"] if claim["evidence"]]
    assert cited_claims
    assert all(set(claim) == {"claim_key", "text", "support_type", "evidence"} for claim in cited_claims)
    assert all(set(link) == {"passage_id", "cell_id", "anchor_text"}
               for claim in cited_claims for link in claim["evidence"])
    assert all(link["anchor_text"] for claim in cited_claims for link in claim["evidence"])
    assert all(bool(link["passage_id"]) != bool(link["cell_id"])
               for claim in cited_claims for link in claim["evidence"])


def test_research_view_has_an_empty_report_summary_list(tmp_path):
    _, store, _, _, _, _, _ = report_flow(tmp_path)
    research_id = store.create_research(
        "How is a SYNTHETIC system evaluated?", "attached", "quick", [], "fake", "fake-model", "en",
    )

    assert research_view(store, research_id)["reportRuns"] == []
