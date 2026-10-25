"""E2 synthetic citation history, read authority and lifecycle; no external calls."""


import pytest

from deixis.storage.db import new_id
from deixis.workflow.tables import InvalidTableInput, TableStore
from deixis.workflow.views import report_view
from test_report_assembly import report_with_sections, _add_claim, _link, _gap
from test_report_edit_check import finish
from test_report_store import lib


def claim(lib, key="III.1"):
    return dict(lib["store"].conn.execute("SELECT * FROM report_claims WHERE claim_key = ?", (key,)).fetchone())


def edit(lib, key="III.1", **request):
    row = claim(lib, key)
    args = dict(text=None, restore_from=None, note=None, expected_version=row["version"], idempotency_key=None)
    args.update(request)
    return lib["reports"].edit_claim(lib["reports"].report(lib["report_id"])["research_id"],
                                    lib["report_id"], row["id"], **args)


def links(lib, key="III.1"):
    return [row["id"] for row in lib["reports"].original_links(claim(lib, key)["id"])]


def rows(conn, table):
    return sorted((tuple(row) for row in conn.execute(f"SELECT * FROM {table}")), key=repr)


def state(lib):
    return {table: rows(lib["store"].conn, table) for table in (
        "report_claims", "report_claim_revisions", "report_claim_revision_links", "reports", "events")}


def legacy(lib, key="III.1", *, text="SYNTHETIC legacy", idempotency_key=None):
    rid = new_id("rcv")
    lib["store"].conn.execute(
        "INSERT INTO report_claim_revisions (id, claim_id, kind, text, created_at, idempotency_key)"
        " VALUES (?, ?, 'human_edit', ?, '2026-10-01', ?)", (rid, claim(lib, key)["id"], text, idempotency_key),
    )
    return rid


def three_links(lib):
    conn = lib["store"].conn
    base = lib["reports"].original_links(claim(lib)["id"])[0]
    for _ in range(2):
        conn.execute("INSERT INTO report_citation_links (id, claim_id, passage_id, source_version_id,"
                     " step_input_id, anchor_text, anchor_match) VALUES (?, ?, ?, ?, ?, ?, ?)",
                     (new_id("rln"), base["claim_id"], base["passage_id"], base["source_version_id"],
                      base["step_input_id"], base["anchor_text"], base["anchor_match"]))
    return links(lib)


def view_claim(lib, key="III.1"):
    report = lib["reports"].report(lib["report_id"])
    return next(c for section in report_view(lib["store"], report["research_id"], lib["report_id"])["sections"]
                for c in section["claims"] if c["claim_key"] == key)


def test_citation_only_text_and_set_restore_and_unchanged_originals(report_with_sections):
    lib = report_with_sections
    ids = three_links(lib)
    finish(lib)
    original = rows(lib["store"].conn, "report_citation_links")
    initial = claim(lib)["text"]
    first = edit(lib, link_ids=[ids[2], ids[0], ids[0]], idempotency_key="first")
    assert claim(lib)["version"] == 2
    assert view_claim(lib)["text"] == initial
    assert [r["id"] for r in lib["reports"].effective_links(lib["report_id"]) if r["claim_key"] == "III.1"] == [ids[0], ids[2]]
    history = lib["reports"].claim_revisions(claim(lib)["id"])
    assert history[0]["link_count"] == 2 and set(history[0]["link_ids"]) == {ids[0], ids[2]}
    second = edit(lib, text=" SYNTHETIC text and set ", link_ids=[])
    assert view_claim(lib)["text"] == "SYNTHETIC text and set"
    assert view_claim(lib)["support_type_note"] == "model_written_type"
    edit(lib, restore_from=first)
    assert view_claim(lib)["text"] == initial and len(view_claim(lib)["evidence"]) == 2
    edit(lib, restore_from="model")
    assert len(view_claim(lib)["evidence"]) == 3 and view_claim(lib)["text"] == initial
    edit(lib, restore_from=second)
    assert view_claim(lib)["evidence"] == []
    old = legacy(lib)
    edit(lib, restore_from=old)
    assert view_claim(lib)["text"] == "SYNTHETIC legacy" and len(view_claim(lib)["evidence"]) == 3
    edit(lib, text="SYNTHETIC only text")
    assert len(view_claim(lib)["evidence"]) == 3
    assert rows(lib["store"].conn, "report_citation_links") == original
    events = lib["store"].events_after(lib["reports"].report(lib["report_id"])["research_id"], 0, 1000)
    assert [e["payload"]["link_count"] for e in events if e["type"] == "report_claim_edited"] == [2, 0, 2, 3, 0, 3, 3]


@pytest.mark.parametrize("edit_request", [pytest.param({}, id="edit_request0")])
def test_invalid_requests_leave_every_write_unchanged(report_with_sections, edit_request):
    lib = report_with_sections
    finish(lib)
    request = dict(edit_request)
    if request.get("link_ids") == "other_claim":
        request["link_ids"] = links(lib, "abstract.1")
    elif request.get("link_ids") == "same":
        request["link_ids"] = links(lib)
    before = state(lib)
    with pytest.raises(InvalidTableInput):
        edit(lib, **request)
    assert state(lib) == before


def cell_report(lib):
    lib["reports"].save_claims(lib["section_ids"]["III"], [
        {"claim_key": "III.1", "text": "SYNTHETIC cell claim", "paragraph": 1, "support_type": "source_stated"},
    ], [_link(lib, "III.1", passage=False)])
    _add_claim(lib, "VI", "VI.1", "SYNTHETIC gap claim", gap_refs=["gap1"])
    _gap(lib, "stated_limitation", claim_keys=["III.1"])
    return finish(lib)


def change_cell(lib):
    row = lib["store"].conn.execute("SELECT * FROM evidence_cells WHERE id = ?", (lib["cell_id"],)).fetchone()
    TableStore(lib["store"]).edit_cell(lib["reports"].report(lib["report_id"])["research_id"], row["table_id"],
                                      row["column_id"], row["source_version_id"], "not_verified",
                                      {"text": "SYNTHETIC changed"}, None, None, row["version"], None)


def totals(changes):
    return {key: value for key, value in changes.items() if key != "sections"}


def test_staleness_removed_cell_body_and_gap_refs_restore_and_acknowledgement(report_with_sections):
    lib = report_with_sections
    rid = cell_report(lib)
    edit(lib, link_ids=[])
    change_cell(lib)
    removed = lib["reports"].evidence_changes(lib["report_id"])
    assert removed["changed_cells"] == 1
    assert all(not removed["sections"][sid]["open"] for sid in ("III", "abstract", "VI"))
    edit(lib, restore_from="model")
    restored = lib["reports"].evidence_changes(lib["report_id"])
    assert totals(restored) == totals(removed)
    assert [restored["sections"][sid]["open"][0]["via"] for sid in ("III", "abstract", "VI")] == [
        "citation", "body_ref", "gap_ref"]
    for sid in ("III", "abstract", "VI"):
        keys = [c["key"] for c in restored["sections"][sid]["open"]]
        lib["reports"].acknowledge_changes(rid, lib["report_id"], sid, keys)
    edit(lib, link_ids=[])
    edit(lib, restore_from="model")
    acknowledged = lib["reports"].evidence_changes(lib["report_id"])
    for sid in ("III", "abstract", "VI"):
        assert acknowledged["sections"][sid]["open"] == []
        assert acknowledged["sections"][sid]["acknowledged_count"] == 1
    change_cell(lib)
    assert all(lib["reports"].evidence_changes(lib["report_id"])["sections"][sid]["open"]
               for sid in ("III", "abstract", "VI"))


def test_still_effective_cell_link_opens_while_removed_link_does_not(report_with_sections):
    lib = report_with_sections
    cell_report(lib)
    _add_claim(lib, "IV", "IV.1", "SYNTHETIC retained basis", links=[_link(lib, passage=False)])
    edit(lib, link_ids=[])
    change_cell(lib)
    changes = lib["reports"].evidence_changes(lib["report_id"])
    assert changes["sections"]["III"]["open"] == []
    assert changes["sections"]["abstract"]["open"] == []
    assert changes["sections"]["IV"]["open"][0]["cell_id"] == lib["cell_id"]
    assert changes["changed_cells"] == 1


def dedicated_report_source(lib):
    """A source and asset with no path to citation protection except its report passage."""
    from test_asset_replacement import extraction
    store = lib["store"]
    source = store.create_upload_source("SYNTHETIC report-only source")
    rid = lib["reports"].report(lib["report_id"])["research_id"]
    store.add_to_corpus(rid, source, "user_upload", selection_state="included", selection_origin="user")
    asset = store.add_asset_with_pages(source, "e" * 64, 10, "synthetic-report.pdf", "user_upload", None,
                                      "synthetic.pdf", extraction(["SYNTHETIC report-only quote"]), "synthetic-v1",
                                      lambda text: [(0, len(text), text)])
    passage = store.passages_for(source)[0]["id"]
    payload = store.step_input_payload(lib["report_input_id"])
    payload["step_input_id"] = new_id("sti")
    payload["passages"].append({"passage_id": passage})
    report = lib["reports"].report(lib["report_id"])
    store.insert_step_input(lib["report_step_id"], rid, report["run_id"], 1, payload, "base", "developer", "message", {})
    _add_claim(lib, "IV", "IV.1", "SYNTHETIC report-only claim", links=[
        _link(lib) | {"source_version_id": source, "passage_id": passage, "anchor_text": "report-only quote",
                      "step_input_id": payload["step_input_id"]}])
    assert_only_report_cites(store, source)
    return source, asset


def assert_only_report_cites(store, source):
    for table, predicate in [
        ("evidence_links", "source_version_id = ?"), ("table_rows", "source_version_id = ?"),
        ("evidence_cells", "source_version_id = ?"),
        ("cell_evidence_links", "passage_id IN (SELECT id FROM passages WHERE source_version_id = ?)"),
        ("lineage_links", "from_source_version_id = ? OR to_source_version_id = ?"),
        ("lineage_link_evidence", "source_version_id = ?"), ("claim_matrix_cells", "source_version_id = ?"),
        ("claim_matrix_evidence", "source_version_id = ?"), ("kill_search_hits", "source_version_id = ?"),
    ]:
        assert not store.conn.execute(f"SELECT 1 FROM {table} WHERE {predicate}",
                                       (source,) * predicate.count('?')).fetchone(), table


def test_trash_restore_and_purge_preserve_then_delete_sets_and_other_research(report_with_sections):
    lib = report_with_sections
    source, asset = dedicated_report_source(lib)
    rid = finish(lib)
    edit(lib, "IV.1", link_ids=[])
    edit(lib, "IV.1", restore_from="model")
    other = lib["store"].create_research("SYNTHETIC other", "attached", "quick", [], "fake", "fake", "en")
    other_run = lib["store"].create_run(other, "report", {}, None)
    reports = lib["reports"]
    report = reports.create_report(other, other_run["id"], 1, "en")
    section = reports.create_section(report, "IV", 4)
    lib["store"].add_to_corpus(other, source, "user_upload", selection_state="included", selection_origin="user")
    step = lib["store"].step(other_run["id"], "synthetic:other-report", "model:report_section")
    sti = new_id("sti")
    passage = lib["store"].passages_for(source)[0]["id"]
    lib["store"].insert_step_input(step["id"], other, other_run["id"], 1,
                                   {"step_input_id": sti, "task_type": "report_section", "scope_revision": 1,
                                    "skill_package_hash": "sha256:synthetic", "passages": [{"passage_id": passage}]},
                                   "base", "developer", "message", {})
    reports.save_claims(section, [{"claim_key": "IV.other", "paragraph": 1, "text": "SYNTHETIC other", "support_type": "source_stated"}],
                       [{"claim_key": "IV.other", "passage_id": passage, "source_version_id": source,
                         "step_input_id": sti, "anchor_text": "report-only quote", "anchor_match": "exact"}])
    lib["store"].update_run(other_run["id"], status="completed")
    reports.finalize(report, "draft")
    cid = lib["store"].conn.execute("SELECT id FROM report_claims WHERE report_section_id = ?", (section,)).fetchone()[0]
    other_rev = reports.edit_claim(other, report, cid, text="SYNTHETIC changed", restore_from=None, note=None,
                                    expected_version=1, idempotency_key=None)
    other_set = rows(lib["store"].conn, "report_claim_revision_links")
    other_set = [row for row in other_set if row[0] == other_rev]
    assert len(other_set) == 1
    before = state(lib)
    lib["store"].trash_research(rid)
    assert state(lib) == before
    lib["store"].restore_research(rid)
    assert state(lib) == before
    lib["store"].trash_research(rid)
    lib["store"].purge_research(rid)
    assert rows(lib["store"].conn, "report_claim_revision_links") == other_set
    assert reports.claim_revisions(cid)[0]["id"] == other_rev
    assert lib["store"].research(other)["id"] == other
    assert lib["store"].conn.execute("PRAGMA foreign_key_check").fetchall() == []
