"""P5 slice 3 (D50): a PDF removed as the wrong file comes back while no other PDF is in use for its source version.

Records and model outputs are SYNTHETIC (scripted FakeAdapter). Passing shows the file, its passages and the evidence citing
them return to use; it says nothing about whether the file was the right one.
"""

import pytest
from fastapi.testclient import TestClient

from deixis.workflow.store import NotFound, PdfInUse, RunInProgress
from helpers import make_pdf
from test_api_flow import app_for, create, session, wait_run
from test_asset_replacement import PAGES, replace
from test_table_extraction import add_pdf, cell, execute, fill, library


def pdf_asset(lib):
    (asset,) = {p["asset_id"] for p in lib.store.passages_for(lib.published) if p["asset_id"]}
    return asset


def in_use(store, svid):
    return store.conn.execute("SELECT COUNT(*) FROM source_assets WHERE source_version_id = ? AND removed_at IS NULL", (svid,)).fetchone()[0]


def test_a_wrong_file_comes_back_with_its_passages_and_its_evidence_is_current_again(tmp_path):
    lib = library(tmp_path)
    assert execute(lib, fill(lib))["status"] == "completed"
    store, asset = lib.store, pdf_asset(lib)
    passages = store.passages_for(lib.published)
    revision = store.selection_revision(lib.rid)

    store.remove_asset(lib.rid, lib.published, asset)
    assert store.selection_revision(lib.rid) == revision + 1 and "pdf_removed" in cell(lib, lib.published)["flags"]
    assert all(p["kind"] == "abstract" for p in store.passages_for(lib.published))

    store.restore_asset(lib.rid, lib.published, asset)
    assert store.selection_revision(lib.rid) == revision + 2  # the source is included: the answer reads its PDF again
    assert store.passages_for(lib.published) == passages
    view = cell(lib, lib.published)
    assert {e["evidence_status"] for e in view["current"]["evidence"]} == {"current"} and view["flags"] == []
    assert (store.asset(asset)["removed_at"], store.asset(asset)["removal_reason"]) == (None, None)
    assert "asset_restored" in [e["type"] for e in store.events_after(lib.rid, 0)]
    with pytest.raises(NotFound):  # in use, nothing to restore
        store.restore_asset(lib.rid, lib.published, asset)


def test_a_wrong_file_does_not_come_back_over_another_pdf_or_during_a_run_and_a_replaced_file_never_does(tmp_path):
    lib = library(tmp_path)
    store, asset = lib.store, pdf_asset(lib)
    store.remove_asset(lib.rid, lib.published, asset)
    other = add_pdf(store, lib.published, ["SYNTHETIC the right file."], "7" * 64)
    with pytest.raises(PdfInUse):
        store.restore_asset(lib.rid, lib.published, asset)
    assert in_use(store, lib.published) == 1 and store.asset(asset)["removed_at"] is not None

    store.remove_asset(lib.rid, lib.published, other)
    fill_run = store.create_run(lib.rid, "answer", {"max_model_calls": 1, "max_provider_requests": 0}, None)
    with pytest.raises(RunInProgress):
        store.restore_asset(lib.rid, lib.published, asset)
    store.update_run(fill_run["id"], status="cancelled")
    store.restore_asset(lib.rid, lib.published, asset)

    old, _ = replace(lib, PAGES, "9" * 64)
    with pytest.raises(NotFound):  # replacing is undone by replacing again, not by restoring
        store.restore_asset(lib.rid, lib.published, old)
    with pytest.raises(NotFound):
        store.restore_asset(lib.rid, lib.no_text, other)  # another source's file


def test_restore_pdf_api(tmp_path):
    app = app_for(tmp_path)
    with TestClient(app) as raw:
        client = session(raw)
        store = app.state.store
        rid = create(client, source_scope="attached")
        uploaded = client.post(f"/api/researches/{rid}/uploads", files={"file": ("notes.pdf", make_pdf(["SYNTHETIC uploaded molecule schedule notes."]), "application/pdf")})
        source = uploaded.json()["sources"][0]
        svid, asset = source["source_version_id"], source["access"]["assets"][0]["id"]
        view, run = wait_run(client, rid, client.post(f"/api/researches/{rid}/runs", json={"kind": "answer"}).json()["id"])
        assert run["status"] == "completed", run
        quote = view["answers"][0]["claims"][0]["evidence"][0]
        url = f"/api/researches/{rid}/sources/{svid}/assets/{asset}"

        removed = client.delete(url).json()
        assert removed["sources"][0]["access"]["assets"] == [] and removed["answers"][0]["claims"][0]["evidence"][0]["evidence_status"] == "pdf_removed"
        assert client.get(f"/api/researches/{rid}/assets/{asset}").status_code == 404
        assert raw.post(f"{url}/restore", headers={"x-deixis-csrf": "wrong"}).status_code == 403
        other = create(client, question="SYNTHETIC research B", source_scope="attached")
        assert client.post(f"/api/researches/{other}/sources/{svid}/assets/{asset}/restore").status_code == 404  # not its source

        restored = client.post(f"{url}/restore")
        assert restored.status_code == 200, restored.text
        assert [a["id"] for a in restored.json()["sources"][0]["access"]["assets"]] == [asset]
        assert restored.json()["answers"][0]["claims"][0]["evidence"][0]["evidence_status"] == "current"
        assert client.get(f"/api/researches/{rid}/assets/{asset}").status_code == 200
        assert client.get(f"/api/researches/{rid}/passages/{quote['passage_id']}").json()["evidence_status"] == "current"
        assert client.post(f"{url}/restore").status_code == 404

        client.delete(url)
        assert client.post(f"/api/researches/{rid}/sources/{svid}/uploads",
                           files={"file": ("right.pdf", make_pdf(["SYNTHETIC the right notes."]), "application/pdf")}).status_code == 201
        conflict = client.post(f"{url}/restore")
        assert conflict.status_code == 409 and in_use(store, svid) == 1
