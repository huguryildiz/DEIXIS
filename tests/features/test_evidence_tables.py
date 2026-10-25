"""P5 evidence tables, model-free part: migration, cell revision rules (T09), rows, columns, API, purge and backup.

Model outputs are written straight through TableStore.save_model_output with synthetic StepInputs; the cell
extraction step itself is tested separately. These are data-rule tests, not evidence of model quality.
"""

from types import SimpleNamespace

import pytest
from fastapi.testclient import TestClient

from deixis.config import Settings
from deixis.domain.rules import RevisionConflict
from deixis.storage import db
from deixis.storage.backup import create_backup, restore_backup
from deixis.storage.db import new_id, now, transaction
from deixis.workflow.store import Store
from deixis.workflow.tables import InvalidTableInput, TableStore
from helpers import make_pdf
from test_api_flow import app_for, create, session

PACKET_SIZE = {"name": "Packet size", "instruction": "Report the packet size the study evaluates, as stated.",
               "answer_format": "number_unit", "options": None, "allow_multiple": False, "unit_hint": "byte"}
VALUE = {"number": 128, "unit": "byte", "as_stated": "128 bytes"}


# ---- migration ------------------------------------------------------------------------------
# ---- store rules ----------------------------------------------------------------------------
@pytest.fixture
def lib(tmp_path):
    return make_lib(tmp_path)


def make_lib(tmp_path):
    conn = db.connect(tmp_path / "library.sqlite")
    db.migrate(conn)
    store = Store(conn)
    rid = store.create_research("How large are packets?", "attached", "quick", [], "fake", "fake-model", None)
    published = store.create_upload_source("Packet size study")
    preprint = new_id("srv")
    with transaction(conn):
        conn.execute("INSERT INTO source_versions (id, work_id, title, origin, version_label, created_at)"
                     " VALUES (?, ?, 'Packet size study', 'provider', 'submittedVersion', ?)", (preprint, store.source(published)["work_id"], now()))
        abstracts = {sv: store._insert_passage(sv, None, "abstract", None, None, "provider", None, None, f"Packets of 128 bytes ({sv}).")
                     for sv in (published, preprint)}
    for sv in (published, preprint):
        store.add_to_corpus(rid, sv, "user_upload", selection_state="included", selection_origin="user")
    run = store.create_run(rid, "answer", {"max_model_calls": 4}, None)
    step = store.step(run["id"], "cell", "model:cell_extraction")
    tables = TableStore(store)
    tid = tables.create_table(rid, "Packets", None, None, None)
    cid = tables.add_column(rid, tid, PACKET_SIZE, 1, None)
    return SimpleNamespace(conn=conn, store=store, tables=tables, rid=rid, published=published, preprint=preprint,
                           abstracts=abstracts, run_id=run["id"], step_id=step["id"], tid=tid, cid=cid)


def step_input(lib) -> str:
    sti = new_id("sti")
    lib.store.insert_step_input(lib.step_id, lib.rid, lib.run_id, 0, {"step_input_id": sti, "task_type": "cell_extraction",
                                "scope_revision": 1, "skill_package_hash": "sha256:0"}, "base", "developer", "message", {})
    return sti


def model_output(lib, sv=None, recheck=False, status="structurally_valid", passage=None, at_version=None, value=VALUE, sti=None,
                 anchors=("128 bytes",)):
    sv = sv or lib.published
    passage = passage or lib.abstracts[sv]
    return lib.tables.save_model_output(
        lib.rid, lib.tid, lib.cid, sv, column_revision=1, state="value", value=value, note=None, reading_depth="abstract",
        output_status=status, links=[{"passage_id": passage, "source_version_id": sv, "anchor_text": a, "anchor_match": "exact"} for a in anchors],
        run_id=lib.run_id, step_id=lib.step_id, step_input_id=sti or step_input(lib), model_connection="fake",
        resolved_model="fake-model", scope_revision=1, cell_version_at_request=at_version, recheck=recheck)


def cell(lib, sv=None):
    return lib.tables.cell_view(lib.rid, lib.tid, lib.cid, sv or lib.published)


def edit(lib, version, sv=None, state="not_verified", value=None, key=None, keep=None):
    value = {"number": 256, "unit": "byte"} if value is None and state in ("value", "not_verified") else value
    return lib.tables.edit_cell(lib.rid, lib.tid, lib.cid, sv or lib.published, state, value, None, keep, version, key)


def decide(lib, proposal, accept, version, sv=None):
    return lib.tables.decide_proposal(lib.rid, lib.tid, lib.cid, sv or lib.published, proposal, accept, version, None)


def test_t09a_f_a_fill_gives_a_value_only_to_an_empty_cell(lib):
    first = model_output(lib)
    assert cell(lib)["current"]["id"] == first and cell(lib)["current"]["kind"] == "model_fill" and cell(lib)["version"] == 1

    human = edit(lib, 0, sv=lib.preprint)
    later = model_output(lib, sv=lib.preprint)
    view = cell(lib, lib.preprint)
    assert view["current"]["id"] == human and view["current"]["author"] == "human"
    assert view["pending_proposal"]["id"] == later and view["pending_proposal"]["kind"] == "model_proposal"


def test_t09b_c_l_a_recheck_proposes_and_only_the_user_changes_the_value(lib):
    fill = model_output(lib)
    proposal = model_output(lib, recheck=True, value={"number": 64, "unit": "byte", "as_stated": "64 bytes"})
    assert cell(lib)["current"]["id"] == fill  # l: a model value is not replaced by a recheck either

    dismissed = decide(lib, proposal, False, 1)
    view = cell(lib)
    assert view["current"]["id"] == fill and view["pending_proposal"] is None and view["version"] == 2
    with pytest.raises(RevisionConflict):
        decide(lib, proposal, True, 2)

    human = edit(lib, 2)
    second = model_output(lib, recheck=True)
    accepted = decide(lib, second, True, 3)
    view = cell(lib)
    assert view["current"]["id"] == accepted and view["current"]["author"] == "human" and view["current"]["value"] == VALUE
    assert view["current"]["evidence"][0]["passage_id"] == lib.abstracts[lib.published]
    link = lib.conn.execute("SELECT step_input_id FROM cell_evidence_links WHERE cell_revision_id = ?", (accepted,)).fetchone()
    assert link[0] is not None  # the StepInput that gave the passage stays with the accepted value
    history = {r["id"]: r for r in view["revisions"]}
    assert set(history) == {fill, proposal, dismissed, human, second, accepted}
    assert history[proposal]["decision"] == "dismissed" and history[second]["decision"] == "accepted"


def test_t09d_an_older_screen_cannot_overwrite_a_newer_edit(lib):
    first = edit(lib, 0, value={"number": 1, "unit": "byte"})
    with pytest.raises(RevisionConflict):
        edit(lib, 0, value={"number": 2, "unit": "byte"})
    assert cell(lib)["current"]["id"] == first and cell(lib)["current"]["value"]["number"] == 1


def test_t09h_an_invalid_proposal_cannot_be_accepted(lib):
    proposal = model_output(lib, status="unverified_draft")
    view = cell(lib)
    assert view["current"] is None and "proposal_invalid" in view["flags"]  # an invalid fill result never becomes the value
    with pytest.raises(InvalidTableInput):
        decide(lib, proposal, True, 0)
    assert cell(lib)["current"] is None


def test_t09i_a_changed_column_marks_earlier_values_stale(lib):
    model_output(lib)
    column = lib.tables.table_view(lib.rid, lib.tid)["columns"][0]
    lib.tables.revise_column(lib.rid, lib.tid, lib.cid, {"name": "Packet size"}, None, column["version"])  # no change
    assert lib.tables.table_view(lib.rid, lib.tid)["columns"][0]["revision"] == 1
    lib.tables.revise_column(lib.rid, lib.tid, lib.cid, {"instruction": "Report the largest packet size."}, None, column["version"] + 1)
    assert "stale_column" in cell(lib)["flags"]
    with pytest.raises(RevisionConflict):
        lib.tables.revise_column(lib.rid, lib.tid, lib.cid, {"name": "Size"}, None, column["version"])


def test_a_value_needs_evidence_or_is_recorded_as_not_verified(lib):
    fill = model_output(lib)
    with pytest.raises(InvalidTableInput):
        edit(lib, 1, state="value")
    corrected = edit(lib, 1, state="value", value={"number": 128, "unit": "B"}, keep=fill)
    assert cell(lib)["current"]["evidence"][0]["passage_id"] == lib.abstracts[lib.published]
    with pytest.raises(InvalidTableInput):
        edit(lib, 2, state="not_verified", keep=corrected)
    with pytest.raises(InvalidTableInput):
        edit(lib, 2, state="value", keep=model_output(lib, sv=lib.preprint))  # evidence of another cell


def test_no_text_fills_only_an_empty_cell(lib):
    assert lib.tables.save_no_text(lib.rid, lib.tid, lib.cid, lib.published, column_revision=1, run_id=lib.run_id,
                                   step_id=lib.step_id, scope_revision=1) is not None
    assert cell(lib)["current"]["state"] == "inaccessible" and cell(lib)["current"]["author"] == "system"
    edit(lib, 0, sv=lib.preprint)
    assert lib.tables.save_no_text(lib.rid, lib.tid, lib.cid, lib.preprint, column_revision=1, run_id=lib.run_id,
                                   step_id=lib.step_id, scope_revision=1) is None


def test_rows_are_explicit_and_removing_one_keeps_its_cells(lib):
    table = lib.tables.table_view(lib.rid, lib.tid)["table"]
    assert {r["source_version_id"] for r in lib.tables.table_view(lib.rid, lib.tid)["rows"]} == {lib.published, lib.preprint}
    with pytest.raises(InvalidTableInput):
        lib.tables.add_rows(lib.rid, lib.tid, [new_id("srv")], table["version"])
    model_output(lib)
    lib.store.set_user_selection(lib.rid, lib.published, "excluded", 1, None)  # narrowing Sources does not shrink the table
    assert lib.published in {r["source_version_id"] for r in lib.tables.table_view(lib.rid, lib.tid)["rows"]}

    lib.tables.remove_row(lib.rid, lib.tid, lib.published, table["version"])
    view = lib.tables.table_view(lib.rid, lib.tid)
    assert [r["source_version_id"] for r in view["removed_rows"]] == [lib.published] and not view["cells"]
    with pytest.raises(InvalidTableInput):
        edit(lib, 1)
    lib.tables.add_rows(lib.rid, lib.tid, [lib.published], table["version"] + 1)
    assert lib.tables.table_view(lib.rid, lib.tid)["cells"][0]["current"]["value"] == VALUE


# ---- API ------------------------------------------------------------------------------------
def upload(client, rid, name, text):
    response = client.post(f"/api/researches/{rid}/uploads", files={"file": (name, make_pdf([text]), "application/pdf")})
    assert response.status_code == 201, response.text


def test_table_api_versions_idempotency_and_scope(tmp_path):
    with TestClient(app_for(tmp_path)) as raw:
        client = session(raw)
        rid = create(client, source_scope="attached")
        upload(client, rid, "a.pdf", "SYNTHETIC packets of 128 bytes")
        upload(client, rid, "b.pdf", "SYNTHETIC packets of 64 bytes")
        base = f"/api/researches/{rid}/tables"

        created = client.post(base, json={"title": "Packet sizes"}, headers={"Idempotency-Key": "t1"})
        assert created.status_code == 201, created.text
        table = created.json()
        assert len(table["rows"]) == 2 and table["counts"]["columns"] == 0
        assert client.post(base, json={"title": "Packet sizes"}, headers={"Idempotency-Key": "t1"}).json()["table"]["id"] == table["table"]["id"]
        assert len(client.get(base).json()) == 1
        tid, version = table["table"]["id"], table["table"]["version"]

        column_body = PACKET_SIZE | {"expected_version": version}
        added = client.post(f"{base}/{tid}/columns", json=column_body, headers={"Idempotency-Key": "c1"})
        assert added.status_code == 201, added.text
        assert client.post(f"{base}/{tid}/columns", json=column_body, headers={"Idempotency-Key": "c1"}).status_code == 201
        assert client.post(f"{base}/{tid}/columns", json=column_body).status_code == 409
        view = client.get(f"{base}/{tid}").json()
        assert len(view["columns"]) == 1
        column, svid = view["columns"][0], view["rows"][0]["source_version_id"]

        url = f"{base}/{tid}/cells/{column['id']}/{svid}"
        assert client.get(url).json()["version"] == 0
        body = {"state": "not_verified", "value": {"number": 128, "unit": "byte"}, "expected_version": 0}
        edited = client.put(url, json=body, headers={"Idempotency-Key": "e1"})
        assert edited.status_code == 200, edited.text
        assert edited.json()["current"]["author"] == "human" and edited.json()["version"] == 1
        assert client.put(url, json=body, headers={"Idempotency-Key": "e1"}).json()["current"]["id"] == edited.json()["current"]["id"]
        assert client.put(url, json={"state": "unknown", "expected_version": 0}).status_code == 409
        assert client.put(url, json={"state": "value", "value": {"number": 1}, "expected_version": 1}).status_code == 422
        assert client.put(url, json={"state": "unknown", "expected_version": 1}, headers={"x-deixis-csrf": "wrong"}).status_code == 403

        changed = client.patch(f"{base}/{tid}/columns/{column['id']}", json={"answer_format": "text", "expected_version": column["version"]})
        assert changed.status_code == 200, changed.text
        assert changed.json()["columns"][0]["unit_hint"] is None and "stale_column" in client.get(url).json()["flags"]

        other = create(client, source_scope="attached")
        assert client.get(f"/api/researches/{other}/tables/{tid}").status_code == 404
        assert client.get(url.replace(rid, other)).status_code == 404
        current = client.get(f"{base}/{tid}").json()["table"]["version"]
        assert client.post(f"{base}/{tid}/rows", json={"source_version_ids": ["srv_missing000000"], "expected_version": current}).status_code == 422

        template = client.post("/api/table-templates", json={"name": "Packets", "research_id": rid, "table_id": tid})
        assert template.status_code == 201 and template.json()["columns"][0]["answer_format"] == "text"
        from_template = client.post(base, json={"title": "Again", "template_id": template.json()["id"]}).json()
        assert [c["origin"] for c in from_template["columns"]] == ["template"]

        renamed = client.patch(f"{base}/{tid}", json={"title": "Sizes", "expected_version": current})
        assert renamed.json()["table"]["title"] == "Sizes"
        assert client.delete(f"{base}/{tid}", params={"expected_version": current}).status_code == 409
        assert client.delete(f"{base}/{tid}", params={"expected_version": current + 1}).json() == {"trashed": True}
        assert client.get(f"{base}/{tid}").status_code == 404


def table_with_edit(client, rid):
    upload(client, rid, "a.pdf", "SYNTHETIC packets of 128 bytes")
    table = client.post(f"/api/researches/{rid}/tables", json={"title": "Packets"}).json()
    tid = table["table"]["id"]
    view = client.post(f"/api/researches/{rid}/tables/{tid}/columns", json=PACKET_SIZE | {"expected_version": table["table"]["version"]}).json()
    url = f"/api/researches/{rid}/tables/{tid}/cells/{view['columns'][0]['id']}/{view['rows'][0]['source_version_id']}"
    assert client.put(url, json={"state": "not_reported", "note": "Checked the whole paper.", "expected_version": 0}).status_code == 200
    return tid


def test_a_superseded_proposal_is_refused_by_the_api_and_an_earlier_decision_replays(tmp_path):
    app = app_for(tmp_path)
    with TestClient(app) as raw:
        client = session(raw)
        rid = create(client, source_scope="attached")
        upload(client, rid, "a.pdf", "SYNTHETIC packets of 128 bytes")
        table = client.post(f"/api/researches/{rid}/tables", json={"title": "Packets"}).json()
        tid = table["table"]["id"]
        view = client.post(f"/api/researches/{rid}/tables/{tid}/columns", json=PACKET_SIZE | {"expected_version": table["table"]["version"]}).json()
        cid, svid = view["columns"][0]["id"], view["rows"][0]["source_version_id"]
        store = app.state.store
        run = store.create_run(rid, "answer", {"max_model_calls": 4}, None)
        (passage,) = [p["id"] for p in store.passages_for(svid)][:1]
        lib = SimpleNamespace(store=store, tables=TableStore(store), rid=rid, tid=tid, cid=cid, published=svid, run_id=run["id"],
                              step_id=store.step(run["id"], "cell", "model:cell_extraction")["id"])
        url = f"/api/researches/{rid}/tables/{tid}/cells/{cid}/{svid}"

        model_output(lib, passage=passage)
        accepted_one = model_output(lib, recheck=True, passage=passage, at_version=1)
        first = client.post(f"{url}/proposals/{accepted_one}/accept", json={"expected_version": 1}, headers={"Idempotency-Key": "d1"})
        assert first.status_code == 200, first.text
        older = model_output(lib, recheck=True, passage=passage, at_version=2)
        version = client.put(url, json={"state": "not_verified", "value": {"number": 256, "unit": "byte"}, "expected_version": 2}).json()["version"]
        # A value newer than the proposal supersedes it: deciding it now is a conflict, even at the cell's current version.
        refused = client.post(f"{url}/proposals/{older}/accept", json={"expected_version": version})
        assert refused.status_code == 409, refused.text
        assert client.post(f"{url}/proposals/{older}/dismiss", json={"expected_version": version}).status_code == 409
        after = client.get(url).json()
        assert after["version"] == version and after["current"]["author"] == "human" and after["pending_proposal"] is None
        # The earlier accepted decision still replays: same revision, nothing added.
        count = len(after["revisions"])
        replayed = client.post(f"{url}/proposals/{accepted_one}/accept", json={"expected_version": 1}, headers={"Idempotency-Key": "d1"})
        assert replayed.status_code == 200, replayed.text
        assert len(replayed.json()["revisions"]) == count
        assert [r["id"] for r in replayed.json()["revisions"] if r["kind"] == "accept_proposal"] == [first.json()["current"]["id"]]


def test_permanent_deletion_removes_tables(tmp_path):
    app = app_for(tmp_path)
    with TestClient(app) as raw:
        client = session(raw)
        rid = create(client, source_scope="attached")
        table_with_edit(client, rid)
        assert client.delete(f"/api/researches/{rid}").status_code == 200
        assert client.delete(f"/api/trash/{rid}").status_code == 200
        conn = app.state.store.conn
        for name in ("evidence_tables", "table_rows", "table_columns", "column_revisions", "evidence_cells", "cell_revisions"):
            assert conn.execute(f"SELECT COUNT(*) FROM {name}").fetchone()[0] == 0


def test_backup_restores_tables_and_human_edits(tmp_path):
    with TestClient(app_for(tmp_path)) as raw:
        client = session(raw)
        rid = create(client, source_scope="attached")
        tid = table_with_edit(client, rid)
        before = client.get(f"/api/researches/{rid}/tables/{tid}").json()
        backup = create_backup(Settings(data_dir=tmp_path / "data", port=8765), tmp_path / "backups")
    restored = tmp_path / "restored"
    restore_backup(backup, Settings(data_dir=restored / "data", port=8765))
    with TestClient(app_for(restored)) as client:
        after = client.get(f"/api/researches/{rid}/tables/{tid}").json()
    assert after == before and after["cells"][0]["current"]["state"] == "not_reported"
