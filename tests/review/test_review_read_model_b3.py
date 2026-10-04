"""B3 projections are the frozen copy, even when named live records change (synthetic API libraries only)."""

import pytest

from deixis.storage import db
from deixis.workflow.review.store import ReviewStore
from deixis.workflow.tables import TableStore
from tests.review_helpers import report_with_sections, review_lib
from tests.review_run_helpers import review_api, body, start, read


@pytest.mark.parametrize("kind", ["answer", "report"])
def test_review_snapshot_display_fields_are_frozen_through_api(review_lib, tmp_path, kind):
    with review_api(review_lib, tmp_path) as api:
        if kind == "answer":
            api.conn.execute("INSERT INTO claims (id, answer_id, ordinal, label, text, support_type, section)"
                             " VALUES (?, ?, 2, 'c2', 'SYNTHETIC second claim.', 'analyst_inference', 'Methods')",
                             (db.new_id("clm"), api.answer_id))
        opened, _, _ = start(api, body(api, kind))
        card = read(api, opened["review"]["id"])
        snapshot = card["snapshot"]
        content = ReviewStore(api.conn).snapshot(snapshot["id"])["content"]
        assert snapshot["scope_revision"] == content["scope_revision"] == 1
        assert snapshot["claims"] == [{k: c[k] for k in ("claim_ref", "section_ref")} for c in content["claims"]]
        assert snapshot["sources"] == [{k: s[k] for k in ("source_id", "title", "year", "version_label", "reading_depth")}
                                       for s in content["sources"]]
        assert snapshot["sources"]
        assert snapshot["cells"] == [{k: c[k] for k in ("cell_id", "column_id", "column_name", "source_version_id")}
                                     for c in content["cells"]]
        assert snapshot["columns"] == [{k: c[k] for k in ("column_id", "name")} for c in content["columns"]]
        assert card["skill_package_hash"] == api.store.run(opened["run"]["id"])["target"]["skill_package_hash"]
        source_id = snapshot["sources"][0]["source_id"]
        api.conn.execute("UPDATE source_versions SET title = 'SYNTHETIC changed live title' WHERE id = ?", (source_id,))
        assert api.conn.execute("SELECT title FROM source_versions WHERE id = ?", (source_id,)).fetchone()[0] != snapshot["sources"][0]["title"]
        if kind == "answer":
            assert snapshot["cells"] == snapshot["columns"] == []
            assert [c["claim_ref"] for c in snapshot["claims"]] == ["c1", "c2"]
            api.conn.execute("UPDATE claims SET label = 'live_' || label, ordinal = 3 - ordinal WHERE answer_id = ?", (api.answer_id,))
            assert [c[0] for c in api.conn.execute("SELECT label FROM claims WHERE answer_id = ? ORDER BY ordinal", (api.answer_id,))] == ["live_c2", "live_c1"]
        else:
            assert snapshot["cells"] and snapshot["columns"]
            column_id = snapshot["columns"][0]["column_id"]
            column = api.conn.execute("SELECT table_id, version FROM table_columns WHERE id = ?", (column_id,)).fetchone()
            TableStore(api.store).revise_column(api.rid, column["table_id"], column_id,
                {"name": "SYNTHETIC changed live column"}, None, column["version"])
            assert api.conn.execute("SELECT name FROM column_revisions WHERE column_id = ? ORDER BY revision DESC", (column_id,)).fetchone()[0] != snapshot["columns"][0]["name"]
        after = read(api, card["id"])
        assert after["snapshot"] == snapshot
        assert after["skill_package_hash"] == card["skill_package_hash"]
