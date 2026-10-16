"""Storage of follow-up turns (UI parity S22a, F17): the
turn is published once and never edited, its links are append-only, and research purge, source purge and
backup/restore cover both tables. Records are SYNTHETIC."""

import sqlite3

import pytest
from fastapi.testclient import TestClient

from deixis.config import Settings
from deixis.storage import db
from deixis.storage.backup import create_backup, restore_backup
from fakes import FakeAdapter
from test_api_flow import app_for, session
from test_followup_turns import answered, research

def test_a_published_turn_is_never_edited_or_deleted_and_its_links_are_append_only(tmp_path):
    app = app_for(tmp_path, FakeAdapter())
    with TestClient(app) as client:
        session(client)
        rid, _ = research(client)
        turn = answered(client, rid)
        assert turn["status"] == "answered"
        conn = app.state.store.conn
        with pytest.raises(sqlite3.IntegrityError, match="published once"):
            conn.execute("UPDATE followup_turns SET status = 'not_answered' WHERE id = ?", (turn["id"],))
        with pytest.raises(sqlite3.IntegrityError, match="purge authorization"):
            conn.execute("DELETE FROM followup_turns WHERE id = ?", (turn["id"],))
        with pytest.raises(sqlite3.IntegrityError, match="append-only"):
            conn.execute("UPDATE followup_turn_links SET anchor_text = 'x'")
        with pytest.raises(sqlite3.IntegrityError, match="purge authorization"):
            conn.execute("DELETE FROM followup_turn_links")
        link = dict(conn.execute("SELECT * FROM followup_turn_links").fetchone())
        with pytest.raises(sqlite3.IntegrityError, match="published valid answer of the same StepInput"):
            conn.execute("INSERT INTO followup_turn_links (id, turn_id, claim_label, passage_id, source_version_id,"
                         " step_input_id, support_type, anchor_text, anchor_match) VALUES ('ful_x', ?, 'c9', ?, ?,"
                         " 'sti_other', 'source_stated', 'x', 'exact')",
                         (turn["id"], link["passage_id"], link["source_version_id"]))
        # A pending row may not claim to be published without its time.
        with pytest.raises(sqlite3.IntegrityError, match="CHECK"):
            conn.execute("INSERT INTO followup_turns (id, research_id, scope_revision, question, run_id, status, created_at)"
                         " VALUES ('fut_y', ?, 1, 'SYNTHETIC?', ?, 'answered', 'now')", (rid, turn["run"]["id"] + "x"))


def test_a_cited_source_is_not_purged_and_the_research_purge_removes_the_turns(tmp_path):
    app = app_for(tmp_path, FakeAdapter())
    with TestClient(app) as client:
        session(client)
        rid, (svid,) = research(client)
        answered(client, rid)
        store = app.state.store
        assert store.cited_source_versions([svid]) == {svid}
        assert client.request("DELETE", f"/api/researches/{rid}/sources", json={"source_version_ids": [svid]}).status_code == 200
        assert client.post(f"/api/researches/{rid}/sources/purge", json={"source_version_ids": [svid]}).status_code == 409
        assert store.conn.execute("SELECT COUNT(*) FROM followup_turn_links").fetchone()[0] == 1

        assert client.delete(f"/api/researches/{rid}").status_code == 200  # to Trash
        assert client.delete(f"/api/trash/{rid}").json()["deleted"] is True
        for table in ("followup_turns", "followup_turn_links", "runs", "step_inputs"):
            assert store.conn.execute(f"SELECT COUNT(*) FROM {table}").fetchone()[0] == 0, table
        assert store.conn.execute("SELECT 1 FROM source_versions WHERE id = ?", (svid,)).fetchone() is None


def test_backup_and_restore_keep_the_turns_and_their_links(tmp_path):
    app = app_for(tmp_path, FakeAdapter())
    with TestClient(app) as client:
        session(client)
        rid, _ = research(client)
        turn = answered(client, rid)
        conn = app.state.store.conn
        turns = [tuple(r) for r in conn.execute("SELECT * FROM followup_turns")]
        links = [tuple(r) for r in conn.execute("SELECT * FROM followup_turn_links")]
        backup_dir = create_backup(Settings(data_dir=tmp_path / "data", port=8765), tmp_path / "backups")
    assert len(turns) == 1 and len(links) == 1

    restored = tmp_path / "restored"
    restore_backup(backup_dir, Settings(data_dir=restored / "data", port=8765))
    conn = db.connect(restored / "data" / "library.sqlite")
    try:
        db.migrate(conn)
        assert [tuple(r) for r in conn.execute("SELECT * FROM followup_turns")] == turns
        assert [tuple(r) for r in conn.execute("SELECT * FROM followup_turn_links")] == links
    finally:
        conn.close()
    with TestClient(app_for(restored)) as client:
        assert client.get(f"/api/researches/{rid}/followup-turns/{turn['id']}").json() == turn
