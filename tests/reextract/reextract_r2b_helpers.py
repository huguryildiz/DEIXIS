"""Synthetic torn shared-file seeds, compatible with the old placement paths."""

import asyncio
import hashlib
import json

from deixis.providers.common import ProviderRecord
from tests.reextract.reextract_r2a_helpers import head


def tear(lib):
    lib.torn = lib.data[:len(lib.data) * 4 // 10]
    lib.torn_sha = hashlib.sha256(lib.torn).hexdigest()
    lib.path.write_bytes(lib.torn)
    lib.old_head = head(lib.store, lib.aid)
    return lib


def retained(lib):
    return any(p.is_file() and not p.is_symlink() and hashlib.sha256(p.read_bytes()).hexdigest() == lib.torn_sha
               for p in lib.settings.data_dir.rglob("*") if p.is_file() and p.suffix not in (".sqlite", "-wal", "-shm"))


def receipt(lib):
    assert (lib.settings.papers_dir / ("retained-" + lib.torn_sha + ".bin")).read_bytes() == lib.torn
    rows = lib.conn.execute("SELECT * FROM asset_recovery_operations WHERE kind = 'file_restore'").fetchall()
    assert len(rows) == 1
    operation = dict(rows[0])
    view = lib.store.file_restore_view(operation["id"])
    assert (view["lifecycle"], view["outcome"], view["before_integrity"], view["after_integrity"], view["retained"]) == (
        "completed", "file_restored", "mismatch", "verified", True)
    before = dict(lib.conn.execute("SELECT * FROM asset_file_observations WHERE id = ?",
                                  (operation["before_observation_id"],)).fetchone())
    assert before["observed_sha256"] == lib.torn_sha and before["observed_byte_size"] == len(lib.torn)
    assert before["retained_filename"] == "retained-" + lib.torn_sha + ".bin"
    assert operation["asset_id"] is None and operation["mode"] is None
    assert operation["idempotency_key"].startswith("restore-")
    assert lib.path.read_bytes() == lib.data and head(lib.store, lib.aid) == lib.old_head
    assert lib.conn.execute("SELECT count(*) FROM passages WHERE asset_id = ?", (lib.aid,)).fetchone()[0] == 0
    events = [(r["research_id"], json.loads(r["payload_json"])) for r in lib.conn.execute(
        "SELECT * FROM events WHERE type = 'asset_file_restore_finished'")]
    assets = lib.store.file_restore_assets(lib.sha)
    expected = {r for a in assets for r in lib.store._asset_researches(a["source_version_id"])}
    if operation["research_id"]:
        expected.add(operation["research_id"])
    assert {rid for rid, _ in events} == expected and len(events) == len(expected)
    for _, payload in events:
        assert payload == {k: view[k] for k in ("operation_id", "sha256", "lifecycle", "outcome", "reason",
                                               "before_integrity", "after_integrity", "retained")} | {
            "affected_asset_ids": [lib.aid]}  # The destination asset is attached after the repair ends.
    assert not list(lib.settings.papers_dir.glob("*.part")) and not list(lib.settings.papers_dir.glob("*.partial"))
    return view


def research(store):
    return store.create_research("SYNTHETIC destination?", "attached", "quick", [], "fake", "fake", None)


def source(lib, rid=None):
    rid = rid or lib.rid
    record = ProviderRecord(provider_record_id="R2B", title="SYNTHETIC destination", authors=[], year=2026,
        venue=None, publication_type="article", doi="10.1/r2b", landing_url=None,
        oa_pdf_url="https://example.org/r2b.pdf", oa_pdf_version="publishedVersion", version_label="publishedVersion",
        abstract=None, abstract_origin=None, identifiers={}, raw={})
    svid, _ = lib.store.upsert_provider_source("openalex", record, None)
    lib.store.add_to_corpus(rid, svid, "search", selection_state="included", selection_origin="user")
    return svid, record


def write(lib, caller="upload", rid=None):
    from deixis.workflow import file_restore
    return asyncio.run(file_restore.store_pdf_file(lib.store, lib.settings.papers_dir, lib.settings.recovery_dir,
                       lib.data, caller=caller, research_id=rid or lib.rid))
