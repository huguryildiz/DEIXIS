"""R1/R2/R3 red-on-old entry points; R4 crash atomicity is a new contract paired with R1."""

import asyncio
from types import SimpleNamespace

import pytest

from deixis import __main__ as cli
from deixis.documents import pdf
from deixis.workflow.worker import Worker
from tests.reextract_r2a_helpers import api_library, body, counts, head, protected, sharing, store_library, url
from tests.reextract_r2b_helpers import tear
from tests.reextract_r2c_helpers import child, events, forbid_calls, startup


def test_r1_crashed_text_retry_fresh_post_promotes_red_on_old(tmp_path, monkeypatch):
    with api_library(tmp_path) as lib:
        with child(lib, "crash_text"):
            pass
        old = lib.store.text_retry_by_key("crashed_request")
        forbid_calls(monkeypatch, parser=False)
        real, calls = pdf.extract_pdf, []
        def parser(path):
            calls.append(path)
            return real(path)
        monkeypatch.setattr(pdf, "extract_pdf", parser)
        response = lib.client.post(url(lib), json=body(lib))
        assert response.status_code == 200 and response.json()["recovery"]["outcome"] == "promoted", response.text
        assert len(calls) == 1  # Only the newly authorized retry parses.
        saved = lib.store.text_retry_view(old["id"])
        assert (saved["lifecycle"], saved["reason"], saved["input_observation_id"]) == (
            "interrupted", "process_ended", old["input_observation_id"])
        assert saved["input_integrity"] == "verified"
        assert len(events(lib.store, "asset_text_retried", old["id"])) == 1
        assert events(lib.store, "asset_text_retried", old["id"])[0]["reason"] == "process_ended"
        forbid_calls(monkeypatch)
        assert lib.client.post(url(lib), json=body(lib, "crashed_request")).json()["recovery"] == saved | {"replayed": True}


def test_r1_crashed_cli_retry_then_real_cli_promotes_red_on_old(tmp_path, monkeypatch, capsys):
    with store_library(tmp_path) as lib:
        with child(lib, "cli"):
            pass
        old = dict(lib.conn.execute("SELECT * FROM asset_recovery_operations").fetchone())
        forbid_calls(monkeypatch, parser=False)
        monkeypatch.setenv("DEIXIS_DATA_DIR", str(lib.settings.data_dir))
        result = cli.main(["reextract", "--retry", lib.aid, "--expected-extraction", lib.eid])
        assert result == 0, capsys.readouterr().err
        assert lib.store.text_retry_view(old["id"])["reason"] == "process_ended"
        assert head(lib.store, lib.aid)["id"] != lib.eid


def test_r2_startup_reconciles_text_without_parsing_red_on_old(tmp_path, monkeypatch):
    with store_library(tmp_path) as lib:
        with child(lib, "crash_text"):
            pass
        old = lib.store.text_retry_by_key("crashed_request")
        before, rows = protected(lib.store), counts(lib.store)
        forbid_calls(monkeypatch)
        with startup(lib) as (app, _):
            result = app.state.store.text_retry_view(old["id"])
            assert result["lifecycle"] != "running"
            assert result["reason"] == "process_ended"
            assert app.state.reconciled == {"text_retries": 1, "file_restores": 0, "live": 0}
            assert protected(app.state.store) == before
            after = counts(app.state.store)
            for table in ("asset_extractions", "passages", "asset_recovery_operations", "asset_file_observations"):
                assert after[table] == rows[table]
            assert len(events(app.state.store, "asset_text_retried", old["id"])) == 1


@pytest.mark.parametrize("entry", ["startup", "worker", "upload"])
@pytest.mark.parametrize("boundary", ["reservation", "retained", "before", "replace", "replacement_commit", "after"])
def test_r3_restore_crash_old_entry_reconciles_red_on_old(tmp_path, monkeypatch, entry, boundary):
    with api_library(tmp_path) as lib:
        tear(lib)
        (lib.settings.data_dir / "synthetic-full.pdf").write_bytes(lib.data)
        with child(lib, "crash_restore", boundary):
            pass
        old = dict(lib.conn.execute("SELECT * FROM asset_recovery_operations").fetchone())
        before = protected(lib.store)
        observed_target, observed_head = lib.path.read_bytes(), head(lib.store, lib.aid)
        forbid_calls(monkeypatch)
        if entry == "startup":
            with startup(lib) as (app, _):
                result = app.state.store._text_retry_operation(old["id"])
        elif entry == "worker":
            asyncio.run(lib.app.state.worker._turn())
            result = lib.store._text_retry_operation(old["id"])
        else:
            response = lib.client.post(f"/api/researches/{lib.rid}/uploads",
                files={"file": ("SYNTHETIC.pdf", lib.data, "application/pdf")})
            result = lib.store._text_retry_operation(old["id"])
        assert result["lifecycle"] != "running"
        assert observed_target == (lib.torn if boundary in ("reservation", "retained", "before") else lib.data)
        assert observed_head == lib.old_head
        assert (result["lifecycle"], result["reason"], result["outcome"]) == ("interrupted", "process_ended", None)
        assert protected(lib.store) == before
        assert len(events(lib.store, "asset_file_restore_finished", old["id"])) == 1
        assert result["before_observation_id"] == old["before_observation_id"]
        view = lib.store.file_restore_view(old["id"])
        assert view["after_integrity"] == (None if boundary in ("reservation", "retained") else
                                           "mismatch" if boundary == "before" else "verified")
        if boundary != "reservation":
            assert (lib.settings.papers_dir / ("retained-" + lib.torn_sha + ".bin")).read_bytes() == lib.torn
        again = lib.client.post(f"/api/researches/{lib.rid}/uploads",
            files={"file": ("SYNTHETIC.pdf", lib.data, "application/pdf")})
        assert again.status_code == 201 and lib.path.read_bytes() == lib.data
        newest = lib.store.latest_file_restore(lib.sha)
        if boundary in ("reservation", "retained", "before"):
            assert newest["operation_id"] != old["id"] and newest["outcome"] == "file_restored"
        else:
            assert newest["operation_id"] == old["id"] and again.json()["file_restore"] is None


@pytest.mark.parametrize("boundary", ["reservation", "input", "parser", "superseded", "candidate", "passages", "mirrors", "event", "committed"])
def test_r4_text_crash_atomic_old_or_complete_new_head_new_contract(tmp_path, monkeypatch, boundary):
    with store_library(tmp_path) as lib:
        other = sharing(lib)
        before = protected(lib.store)
        with child(lib, "crash_text", boundary):
            pass
        old = lib.store.text_retry_by_key("crashed_request")
        current = head(lib.store, lib.aid)
        if boundary == "committed":
            assert current["id"] != lib.eid and current["recovery_operation_id"] == old["id"]
            asset = lib.store.asset(lib.aid)
            assert (asset["extraction_version"], asset["extraction_status"], asset["extraction_error"], asset["page_count"]) == (
                current["extraction_version"], current["status"], current["error"], current["page_count"])
            assert {p["physical_page"] for p in lib.store.passages_for(lib.svid)} == {1, 2, 3}
            assert len(events(lib.store, "asset_text_retried", old["id"])) == 2
        else:
            assert protected(lib.store) == before and current["id"] == lib.eid
            assert lib.conn.execute("SELECT count(*) FROM asset_extractions WHERE recovery_operation_id = ?", (old["id"],)).fetchone()[0] == 0
            assert events(lib.store, "asset_text_retried", old["id"]) == []
        forbid_calls(monkeypatch)
        from deixis.workflow import reconcile
        result = asyncio.run(reconcile.reconcile_stale(lib.store, lib.settings.papers_dir, lib.settings.recovery_dir))
        assert result["text_retries"] == (0 if boundary == "committed" else 1)
        row = lib.store._text_retry_operation(old["id"])
        assert row["lifecycle"] == ("completed" if boundary == "committed" else "interrupted")
        assert row["reason"] == (None if boundary == "committed" else "process_ended")
        assert len(events(lib.store, "asset_text_retried", old["id"])) == 2
        holding = lib.conn.execute("SELECT research_id FROM events WHERE type = 'asset_text_retried' AND json_extract(payload_json, '$.operation_id') = ?", (old["id"],)).fetchall()
        assert {row[0] for row in holding} == {lib.rid, other}
        assert asyncio.run(reconcile.reconcile_stale(lib.store, lib.settings.papers_dir, lib.settings.recovery_dir)) == {
            "text_retries": 0, "file_restores": 0, "live": 0}
