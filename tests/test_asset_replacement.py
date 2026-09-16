"""P5 slice 2 (D45): replacing the PDF in use, its API, and model inputs after a replacement.

Records and model outputs are SYNTHETIC (scripted FakeAdapter). Passing these tests shows which passages later steps read
and that earlier evidence keeps its passages; it says nothing about extraction or model quality.
"""

import json
from collections import Counter
from pathlib import Path
from types import SimpleNamespace

import pytest
from fastapi.testclient import TestClient

from deixis.config import Settings
from deixis.storage.backup import create_backup, restore_backup
from deixis.workflow.store import RunInProgress, SameFile
from helpers import make_pdf
from test_api_flow import app_for, create, session, wait_run
from test_table_extraction import cell, execute, fill, library, recheck, stored_inputs

PAGES = ["SYNTHETIC page one: packets of 128 bytes minimize energy per bit.", "SYNTHETIC page two: a relay forwards each packet once."]


def extraction(pages):
    return SimpleNamespace(status="succeeded", error=None, page_count=len(pages),
                           pages=[SimpleNamespace(physical_page=n, printed_label=None, text=text) for n, text in enumerate(pages, 1)])


def replace(lib, pages, sha):
    (old,) = {p["asset_id"] for p in lib.store.passages_for(lib.published) if p["asset_id"]}
    new = lib.store.replace_asset(old, sha, 10, f"{sha}.pdf", "user_upload", None, "new.pdf", extraction(pages), "test-v1",
                                  lambda text: [(0, len(text), text)])
    return old, new


def test_replacing_keeps_old_evidence_and_later_steps_read_only_the_new_file(tmp_path):
    lib = library(tmp_path)
    assert execute(lib, fill(lib))["status"] == "completed"
    before = cell(lib, lib.published)["current"]
    cited = {e["passage_id"] for e in before["evidence"]}
    selection = lib.store.selection_revision(lib.rid)

    old, new = replace(lib, PAGES, "9" * 64)  # the same text in another file

    asset = lib.store.asset(old)
    assert (asset["removal_reason"], asset["replaced_by_asset_id"]) == ("replaced", new) and asset["removed_at"] is not None
    links = lambda view: [(e["passage_id"], e["anchor_text"]) for e in view["evidence"]]
    after = cell(lib, lib.published)["current"]
    assert (after["id"], links(after)) == (before["id"], links(before))
    assert all(lib.store.passage(pid)["asset_id"] == old for pid in cited)
    live = lib.store.passages_for(lib.published)
    assert {p["asset_id"] for p in live} == {new} and not cited & {p["id"] for p in live}
    assert lib.store.selection_revision(lib.rid) == selection  # the selection did not change
    assert [e["type"] for e in lib.store.events_after(lib.rid, 0)].count("asset_replaced") == 1

    run = recheck(lib, lib.published, cell(lib, lib.published)["version"])
    assert execute(lib, run)["status"] == "completed"
    (payload,) = stored_inputs(lib, run["id"])
    assert set(payload["allowlist"]["passage_ids"]) == {p["id"] for p in live}
    assert max(Counter(p["text"] for p in payload["passages"]).values()) == 1
    assert payload["extraction_target"]["passage_scope"] == {"given": 2, "available": 2, "all_pages_given": True}


def test_an_answer_input_after_a_replacement_has_each_text_once(tmp_path):
    lib = library(tmp_path)
    replace(lib, PAGES, "9" * 64)
    scope = lib.store.scope(lib.rid)
    given = lib.flow._retrieve(lib.rid, scope, [lib.published], 48)
    assert sorted(p["id"] for p in given) == sorted(p["id"] for p in lib.store.passages_for(lib.published))
    assert max(Counter(p["text"] for p in given).values()) == 1


def test_replacing_is_refused_for_the_same_file_a_removed_file_or_during_a_run(tmp_path):
    lib = library(tmp_path)
    (old,) = {p["asset_id"] for p in lib.store.passages_for(lib.published) if p["asset_id"]}
    sha = lib.store.asset(old)["sha256"]
    with pytest.raises(SameFile):
        lib.store.replace_asset(old, sha, 10, f"{sha}.pdf", "user_upload", None, "p.pdf", extraction(PAGES), "test-v1", lambda t: [(0, len(t), t)])
    fill(lib)  # queued
    with pytest.raises(RunInProgress):
        replace(lib, ["SYNTHETIC other"], "8" * 64)
    assert lib.store.asset(old)["removed_at"] is None


def test_replace_reextract_and_impact_api(tmp_path):
    app = app_for(tmp_path)
    with TestClient(app) as raw:
        client = session(raw)
        rid = create(client, source_scope="attached")
        store = app.state.store
        client.post(f"/api/researches/{rid}/uploads", files={"file": ("a.pdf", make_pdf(["SYNTHETIC molecule notes"]), "application/pdf")})
        svid = store.conn.execute("SELECT source_version_id FROM corpus_memberships WHERE research_id = ?", (rid,)).fetchone()[0]
        (aid,) = store.conn.execute("SELECT id FROM source_assets WHERE source_version_id = ?", (svid,)).fetchone()
        base = f"/api/researches/{rid}/sources/{svid}/assets"

        impact = client.get(f"{base}/{aid}/impact").json()
        assert impact == {"asset_id": aid, "researches": [{"id": rid, "title": impact["researches"][0]["title"]}], "cells": 0, "quotes": 0}

        same = client.put(f"{base}/{aid}", files={"file": ("a.pdf", make_pdf(["SYNTHETIC molecule notes"]), "application/pdf")})
        assert same.status_code == 422
        replaced = client.put(f"{base}/{aid}", files={"file": ("b.pdf", make_pdf(["SYNTHETIC better notes"]), "application/pdf")})
        assert replaced.status_code == 200, replaced.text
        (new,) = store.conn.execute("SELECT id FROM source_assets WHERE source_version_id = ? AND removed_at IS NULL", (svid,)).fetchone()
        assert store.asset(aid)["replaced_by_asset_id"] == new
        (access,) = [s["access"] for s in replaced.json()["sources"] if s["source_version_id"] == svid]
        assert [a["id"] for a in access["assets"]] == [new] and access["assets"][0]["current_extraction"] is True
        assert access["assets"][0]["rejected_extraction"] is None
        assert [(a["id"], a["original_filename"], a["replaced_by_asset_id"]) for a in access["replaced_assets"]] == [(aid, "a.pdf", new)]
        assert client.put(f"{base}/{aid}", files={"file": ("c.pdf", make_pdf(["SYNTHETIC"]), "application/pdf")}).status_code == 404

        again = client.post(f"{base}/{new}/extractions")
        assert again.status_code == 200 and again.json()["reextraction"]["outcome"] == "unchanged"

        raw.headers.pop("x-deixis-csrf")
        assert client.put(f"{base}/{new}", files={"file": ("d.pdf", make_pdf(["SYNTHETIC d"]), "application/pdf")}).status_code == 403
        assert client.post(f"{base}/{new}/extractions").status_code == 403


# ---- T15 part of slice 2: backup, restore and permanent deletion keep replaced files and both extractions --------
def answered_with_replacement(client, store, rid):
    client.post(f"/api/researches/{rid}/uploads", files={"file": ("a.pdf", make_pdf(["SYNTHETIC uploaded molecule schedule notes."]), "application/pdf")})
    view, run = wait_run(client, rid, client.post(f"/api/researches/{rid}/runs", json={"kind": "answer"}).json()["id"])
    assert run["status"] == "completed", run
    evidence = view["answers"][0]["claims"][0]["evidence"][0]
    svid = evidence["source_version_id"]
    (old,) = store.conn.execute("SELECT id FROM source_assets WHERE source_version_id = ?", (svid,)).fetchone()
    replaced = client.put(f"/api/researches/{rid}/sources/{svid}/assets/{old}",
                          files={"file": ("b.pdf", make_pdf(["SYNTHETIC uploaded molecule schedule notes, full scan."]), "application/pdf")})
    assert replaced.status_code == 200, replaced.text
    return evidence, svid, old


def test_backup_and_restore_keep_the_replaced_file_its_passages_and_extraction_records(tmp_path):
    app = app_for(tmp_path)
    with TestClient(app) as raw:
        client = session(raw)
        rid = create(client, source_scope="attached")
        store = app.state.store
        evidence, svid, old = answered_with_replacement(client, store, rid)
        before = client.get(f"/api/researches/{rid}").json()
        extractions = store.conn.execute("SELECT COUNT(*) FROM asset_extractions").fetchone()[0]
        files = {r[0] for r in store.conn.execute("SELECT storage_path FROM source_assets WHERE source_version_id = ?", (svid,))}
        backup = create_backup(Settings(data_dir=tmp_path / "data", port=8765), tmp_path / "backups")
    manifest = json.loads((backup / "manifest.json").read_text())
    assert len(files) == 2 and files <= {Path(f["path"]).name for f in manifest["files"]}  # the previous and the current file

    restored = tmp_path / "restored"
    restore_backup(backup, Settings(data_dir=restored / "data", port=8765))
    app = app_for(restored)
    with TestClient(app) as client:
        after = client.get(f"/api/researches/{rid}").json()
        assert after["answers"] == before["answers"] and after["answers"][0]["source_text_changed"] is True
        assert client.get(f"/api/researches/{rid}/passages/{evidence['passage_id']}").json()["evidence_status"] == "pdf_replaced"
        assert client.get(f"/api/researches/{rid}/assets/{old}").status_code == 200
        assert app.state.store.conn.execute("SELECT COUNT(*) FROM asset_extractions").fetchone()[0] == extractions


def test_deleting_a_research_keeps_a_replaced_file_another_research_cites(tmp_path):
    app = app_for(tmp_path)
    with TestClient(app) as raw:
        client = session(raw)
        store = app.state.store
        a = create(client, source_scope="attached")
        client.post(f"/api/researches/{a}/uploads", files={"file": ("a.pdf", make_pdf(["SYNTHETIC uploaded molecule schedule notes."]), "application/pdf")})
        b = create(client, question="SYNTHETIC research B", source_scope="attached")
        evidence, svid, old = answered_with_replacement(client, store, b)  # the same bytes: B uses A's source
        assert store.conn.execute("SELECT COUNT(*) FROM corpus_memberships WHERE source_version_id = ?", (svid,)).fetchone()[0] == 2
        path = tmp_path / "data" / "papers" / store.asset(old)["storage_path"]

        assert client.delete(f"/api/researches/{a}").status_code == 200
        assert client.delete(f"/api/trash/{a}").status_code == 200
        assert path.exists() and client.get(f"/api/researches/{b}/assets/{old}").status_code == 200
        assert client.get(f"/api/researches/{b}/passages/{evidence['passage_id']}").json()["evidence_status"] == "pdf_replaced"
