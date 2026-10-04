"""P5 slice 2 (D45): what earlier cell evidence and answer quotes show after a PDF is removed, replaced or re-extracted.

Records and model outputs are SYNTHETIC (scripted FakeAdapter). Passing shows the recorded evidence keeps resolving and is
marked; it says nothing about whether the new text supports the old value.
"""

from types import SimpleNamespace

from fastapi.testclient import TestClient

from helpers import make_pdf
from test_api_flow import app_for, create, session, wait_run
from test_asset_replacement import PAGES, extraction, replace
from test_table_extraction import cell, execute, fill, library

CHUNK = lambda text: [(0, len(text), text)]  # noqa: E731


def filled(tmp_path):
    lib = library(tmp_path)
    assert execute(lib, fill(lib))["status"] == "completed"
    return lib


def statuses(view):
    return {e["evidence_status"] for e in view["current"]["evidence"]}


def test_cell_evidence_is_marked_by_what_happened_to_its_file(tmp_path):
    lib = filled(tmp_path / "current")
    assert statuses(cell(lib, lib.published)) == {"current"} and cell(lib, lib.published)["flags"] == []
    assert statuses(cell(lib, lib.preprint)) == {"current"}  # abstracts have no file

    lib = filled(tmp_path / "removed")
    (asset,) = {p["asset_id"] for p in lib.store.passages_for(lib.published) if p["asset_id"]}
    lib.store.remove_asset(lib.rid, lib.published, asset)
    view = cell(lib, lib.published)
    assert statuses(view) == {"pdf_removed"} and "pdf_removed" in view["flags"]

    lib = filled(tmp_path / "replaced")
    replace(lib, PAGES, "9" * 64)
    view = cell(lib, lib.published)
    assert statuses(view) == {"pdf_replaced"} and "pdf_replaced" in view["flags"]

    lib = filled(tmp_path / "reextracted")
    (asset,) = {p["asset_id"] for p in lib.store.passages_for(lib.published) if p["asset_id"]}
    assert lib.store.reextract_asset(asset, extraction([p.upper() for p in PAGES]), "test-v2", CHUNK)["outcome"] == "current"
    view = cell(lib, lib.published)
    assert statuses(view) == {"text_superseded"} and "text_superseded" in view["flags"]
    assert view["current"]["evidence"][0]["physical_page"] in (1, 2)


def test_a_stale_fill_proposes_for_cells_whose_evidence_is_shadowed(tmp_path):
    lib = filled(tmp_path)
    current = cell(lib, lib.published)["current"]
    replace(lib, PAGES, "9" * 64)

    assert lib.published not in {s["source_version_id"] for s in lib.tables.fill_plan(lib.rid, lib.tid)["sources"]}
    planned = {s["source_version_id"] for s in lib.tables.fill_plan(lib.rid, lib.tid, include_stale=True)["sources"]}
    assert planned == {lib.published}  # the preprint's abstract evidence is still current

    assert execute(lib, fill(lib, include_stale=True))["status"] == "completed"
    view = cell(lib, lib.published)
    assert view["current"]["id"] == current["id"]
    assert view["pending_proposal"] is not None and statuses({"current": view["pending_proposal"]}) == {"current"}


def test_answer_quotes_and_passages_show_a_replaced_pdf_and_the_old_file_opens_only_where_cited(tmp_path):
    app = app_for(tmp_path)
    with TestClient(app) as raw:
        client = session(raw)
        rid = create(client, source_scope="attached")
        store = app.state.store
        client.post(f"/api/researches/{rid}/uploads", files={"file": ("notes.pdf", make_pdf(["SYNTHETIC uploaded molecule schedule notes."]), "application/pdf")})
        view, run = wait_run(client, rid, client.post(f"/api/researches/{rid}/runs", json={"kind": "answer"}).json()["id"])
        assert run["status"] == "completed", run
        answer = view["answers"][0]
        evidence = answer["claims"][0]["evidence"][0]
        assert evidence["evidence_status"] == "current" and answer["source_text_changed"] is False
        svid = evidence["source_version_id"]
        (old,) = store.conn.execute("SELECT id FROM source_assets WHERE source_version_id = ?", (svid,)).fetchone()

        replaced = client.put(f"/api/researches/{rid}/sources/{svid}/assets/{old}",
                              files={"file": ("better.pdf", make_pdf(["SYNTHETIC uploaded molecule schedule notes, full scan."]), "application/pdf")})
        answer = replaced.json()["answers"][0]
        assert answer["claims"][0]["evidence"][0]["evidence_status"] == "pdf_replaced"
        assert answer["claims"][0]["evidence"][0]["passage_id"] == evidence["passage_id"]
        assert answer["source_text_changed"] is True and answer["applicability"] == "current"

        passage = client.get(f"/api/researches/{rid}/passages/{evidence['passage_id']}").json()
        assert (passage["evidence_status"], passage["asset_id"]) == ("pdf_replaced", old)
        assert client.get(f"/api/researches/{rid}/assets/{old}").status_code == 200  # cited here: read-only old PDF

        other = create(client, question="SYNTHETIC research B", source_scope="attached")
        store.add_to_corpus(other, svid, "user_upload", selection_state="included", selection_origin="user")
        assert client.get(f"/api/researches/{other}/assets/{old}").status_code == 404  # nothing in B cites the old file

        (new,) = store.conn.execute("SELECT id FROM source_assets WHERE source_version_id = ? AND removed_at IS NULL", (svid,)).fetchone()
        client.delete(f"/api/researches/{rid}/sources/{svid}/assets/{new}")
        assert client.get(f"/api/researches/{rid}/assets/{new}").status_code == 404  # a mistaken file stays closed
