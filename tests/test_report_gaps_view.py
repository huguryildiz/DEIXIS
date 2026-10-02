"""Read-only report aspect route, using synthetic stored rows only."""
from test_candidate_api import api, gap, other_research
from deixis.workflow.views import report_view


def test_report_rows_have_exact_keys_and_insertion_order_without_changing_report(api):
    body = gap(api)
    report_id = body["report_id"]
    before = report_view(api.store, api.rid, report_id)
    api.conn.execute(
        "INSERT INTO report_gaps (id,report_id,gap_id,kind,text,basis_json,provenance_json,created_at)"
        " VALUES ('aaa', ?, 'second', 'stated_limitation', '  SYNTHETIC second\n', '{}', '{}', 'before')", (report_id,))
    rows_before = [tuple(row) for row in api.conn.execute("SELECT * FROM report_gaps")]
    response = api.client.get(f"/api/researches/{api.rid}/reports/{report_id}/gaps")
    assert response.status_code == 200
    assert response.json() == [
        {"id": body["gap_row_id"], "gap_id": body["gap_row_id"], "kind": "corpus_absence", "text": "SYNTHETIC gap"},
        {"id": "aaa", "gap_id": "second", "kind": "stated_limitation", "text": "  SYNTHETIC second\n"},
    ]
    assert report_view(api.store, api.rid, report_id) == before
    assert [tuple(row) for row in api.conn.execute("SELECT * FROM report_gaps")] == rows_before


def test_empty_report_and_ownership_404(api):
    body = gap(api)
    api.conn.execute("DELETE FROM report_gaps WHERE report_id = ?", (body["report_id"],))
    path = f"/api/researches/{api.rid}/reports/{body['report_id']}/gaps"
    assert api.client.get(path).json() == []
    assert api.client.get(path.replace(api.rid, other_research(api))).status_code == 404
    assert api.client.get(path.replace(body["report_id"], "missing")).status_code == 404
