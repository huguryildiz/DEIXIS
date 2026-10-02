"""E2 synthetic citation history, read authority and lifecycle; no external calls."""

import ast
import hashlib
import inspect
import json
import sqlite3
from pathlib import Path

import pytest

from deixis.domain.rules import RevisionConflict
from deixis.storage.db import new_id, transaction
from deixis.workflow.report import assembly, edit_check
from deixis.workflow.report.store import ReportStore
from deixis.workflow.store import NotFound
from deixis.workflow.tables import InvalidTableInput, TableStore
from deixis.workflow.views import report_view
from tests.test_report_assembly import report_with_sections, _add_claim, _link, _gap
from tests.test_report_edit_check import finish
from tests.test_report_store import lib, _finished_claim


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


@pytest.mark.parametrize("edit_request", [
    {}, {"link_ids": ["unknown"]}, {"text": ""}, {"text": "x", "restore_from": "model"},
    {"link_ids": [], "restore_from": "model"}, {"restore_from": "unknown"},
    {"text": "Resource allocation assigns capacity."}, {"link_ids": "other_claim"}, {"link_ids": "same"},
])
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


def test_two_tabs_and_trashed_research_write_nothing(report_with_sections):
    lib = report_with_sections
    rid = finish(lib)
    edit(lib, link_ids=[])
    before = state(lib)
    with pytest.raises(RevisionConflict):
        edit(lib, text="second tab", expected_version=1)
    assert state(lib) == before
    lib["store"].trash_research(rid)
    before = state(lib)
    with pytest.raises(NotFound):
        edit(lib, text="trashed")
    assert state(lib) == before
    with pytest.raises(NotFound):
        lib["reports"].edit_claim("unknown", lib["report_id"], claim(lib)["id"], text="x", restore_from=None,
                                    note=None, expected_version=1, idempotency_key=None)
    assert state(lib) == before


def test_request_hash_canonical_replay_legacy_and_null_versus_empty(report_with_sections):
    lib = report_with_sections
    ids = three_links(lib)
    rid = finish(lib)
    first = edit(lib, text=" SYNTHETIC edit ", link_ids=[ids[2], ids[0], ids[0]], note=" note ", idempotency_key="same")
    row = lib["store"].conn.execute("SELECT * FROM report_claim_revisions WHERE id = ?", (first,)).fetchone()
    canonical = json.dumps({"text": "SYNTHETIC edit", "link_ids": sorted([ids[0], ids[2]]),
                            "restore_from": None, "note": "note"}, sort_keys=True, separators=(",", ":"), ensure_ascii=False)
    assert row["request_hash"] == hashlib.sha256(canonical.encode()).hexdigest()
    before = state(lib)
    assert edit(lib, text="SYNTHETIC edit", link_ids=[ids[0], ids[2]], note="note", expected_version=1,
                idempotency_key="same") == first
    assert state(lib) == before
    for key, request in [("III.1", {"text": "different"}), ("abstract.1", {"text": "SYNTHETIC edit"})]:
        with pytest.raises(RevisionConflict):
            edit(lib, key, idempotency_key="same", **request)
    assert state(lib) == before
    edit(lib, text="intermediate", link_ids=[])
    before = state(lib)
    assert edit(lib, text="SYNTHETIC edit", link_ids=[ids[0], ids[2]], note="note", idempotency_key="same",
                expected_version=1) == first
    assert state(lib) == before and view_claim(lib)["text"] == "intermediate"
    old = legacy(lib, idempotency_key=f"{rid}:legacy")
    before = state(lib)
    assert edit(lib, text="anything", expected_version=-1, idempotency_key="legacy") == old
    assert state(lib) == before
    a = edit(lib, text="same new text", link_ids=None)
    edit(lib, restore_from="model")
    b = edit(lib, text="same new text", link_ids=[])
    hashes = [lib["store"].conn.execute("SELECT request_hash FROM report_claim_revisions WHERE id = ?", (i,)).fetchone()[0]
              for i in (a, b)]
    assert hashes[0] != hashes[1] and all(hashes)


def test_citation_only_count_warning_uses_current_text(lib):
    store, reports, rid, _ = lib
    report, _, (cid,) = _finished_claim(lib, count={"value": 2})
    source = store.create_upload_source("SYNTHETIC count source")
    passage = store._insert_passage(source, None, "abstract", None, None, "synthetic", None, None, "SYNTHETIC count")
    step = store.step(reports.report(report)["run_id"], "synthetic:link", "model:report_section")
    sti = new_id("sti")
    store.insert_step_input(step["id"], rid, reports.report(report)["run_id"], 1,
                            {"step_input_id": sti, "task_type": "report_section", "scope_revision": 1,
                             "skill_package_hash": "sha256:synthetic"}, "x", "x", "x", {})
    store.conn.execute("INSERT INTO report_citation_links VALUES (?, ?, ?, NULL, ?, ?, ?, 'exact')",
                       (new_id("rln"), cid, passage, source, sti, "SYNTHETIC count"))
    reports.edit_claim(rid, report, cid, text=None, restore_from=None, link_ids=[], note=None,
                       expected_version=1, idempotency_key=None)
    assert reports.claim_revisions(cid)[0]["warnings"] == [
        {"kind": "count_not_rechecked", "detail": "The count was not rechecked after this edit"}]


def test_citation_only_edit_keeps_edited_text_and_model_whitespace_verbatim(report_with_sections):
    lib = report_with_sections
    ids = three_links(lib)
    finish(lib)
    edit(lib, text="Human $\\frac{a$ text")
    revision = edit(lib, link_ids=ids[:1])
    stored = lib["store"].conn.execute("SELECT text, warnings_json FROM report_claim_revisions WHERE id = ?",
                                       (revision,)).fetchone()
    assert stored["text"] == "Human $\\frac{a$ text" and "math_not_well_formed" in stored["warnings_json"]
    # A model text with edge whitespace is kept exactly by a citation-only edit of an unedited claim.
    lib["store"].conn.execute("UPDATE report_claims SET text = ' padded model text ' WHERE claim_key = 'abstract.1'")
    padded = edit(lib, key="abstract.1", link_ids=[])
    assert lib["store"].conn.execute("SELECT text FROM report_claim_revisions WHERE id = ?",
                                     (padded,)).fetchone()[0] == " padded model text "


@pytest.mark.parametrize("mode", ["late", "empty", "legacy", "foreign"])
def test_sealed_sets_reject_inserts(report_with_sections, mode):
    lib = report_with_sections
    ids = three_links(lib)
    finish(lib)
    rev = edit(lib, link_ids=[] if mode == "empty" else ids[:1])
    if mode == "legacy":
        rev = legacy(lib)
    if mode == "foreign":
        # An unfilled synthetic row isolates the claim-ownership guard from the size guard.
        rev = new_id("rcv")
        lib["store"].conn.execute("INSERT INTO report_claim_revisions (id, claim_id, kind, text, created_at, link_count)"
                                 " VALUES (?, ?, 'human_edit', 'synthetic', 'today', 1)", (rev, claim(lib)["id"]))
    link = links(lib, "abstract.1")[0] if mode == "foreign" else ids[1]
    before = state(lib)
    with pytest.raises(sqlite3.IntegrityError, match="sealed"):
        lib["store"].conn.execute("INSERT INTO report_claim_revision_links VALUES (?, ?)", (rev, link))
    assert state(lib) == before


@pytest.mark.parametrize("size", [0, 1])
@pytest.mark.parametrize("conflict", ["id", "rowid", "key"])
def test_replace_cannot_rewrite_revision_including_explicit_rowid(report_with_sections, size, conflict):
    lib = report_with_sections
    ids = three_links(lib)
    finish(lib)
    rev = edit(lib, link_ids=ids[:size], idempotency_key="sealed")
    conn = lib["store"].conn
    row = dict(conn.execute("SELECT rowid, * FROM report_claim_revisions WHERE id = ?", (rev,)).fetchone())
    replacement = dict(row)
    replacement["link_count"] = 20
    if conflict != "id":
        replacement["id"] = new_id("rcv")
    if conflict != "rowid":
        replacement.pop("rowid")
    if conflict != "key":
        replacement["idempotency_key"] = None
    before = state(lib)
    names = list(replacement)
    with pytest.raises(sqlite3.IntegrityError, match="already exists"):
        conn.execute(f"INSERT OR REPLACE INTO report_claim_revisions ({', '.join(names)})"
                     f" VALUES ({', '.join('?' for _ in names)})", list(replacement.values()))
    with pytest.raises(sqlite3.IntegrityError):
        conn.execute("DELETE FROM report_claim_revisions WHERE id = ?", (rev,))
    with pytest.raises(sqlite3.IntegrityError, match="sealed"):
        conn.execute("INSERT INTO report_claim_revision_links VALUES (?, ?)", (rev, ids[2]))
    assert state(lib) == before


def test_link_rows_cannot_move_replace_or_delete_except_owning_purge(report_with_sections):
    lib = report_with_sections
    ids = three_links(lib)
    rid = finish(lib)
    rev = edit(lib, link_ids=ids[:1])
    second = edit(lib, link_ids=ids[1:2])
    conn = lib["store"].conn
    for sql, params in [
        ("UPDATE report_claim_revision_links SET revision_id = ? WHERE revision_id = ?", (second, rev)),
        ("UPDATE report_claim_revision_links SET link_id = ? WHERE revision_id = ?", (ids[2], rev)),
        ("INSERT OR REPLACE INTO report_claim_revision_links VALUES (?, ?)", (rev, ids[0])),
        ("INSERT OR REPLACE INTO report_claim_revision_links VALUES (?, ?)", (second, ids[0])),
        ("INSERT OR REPLACE INTO report_claim_revision_links (rowid, revision_id, link_id) VALUES (1, ?, ?)", (rev, ids[0])),
        ("DELETE FROM report_claim_revision_links", ()),
    ]:
        before = state(lib)
        with pytest.raises((sqlite3.IntegrityError, sqlite3.OperationalError)):
            conn.execute(sql, params)
        assert state(lib) == before
    other = lib["store"].create_research("SYNTHETIC other", "attached", "quick", [], "fake", "fake", "en")
    with transaction(conn):
        conn.execute("INSERT INTO research_purge_authorizations VALUES (?)", (other,))
        with pytest.raises(sqlite3.IntegrityError, match="immutable"):
            conn.execute("DELETE FROM report_claim_revision_links")
        conn.execute("DELETE FROM research_purge_authorizations WHERE research_id = ?", (other,))
    with transaction(conn):
        conn.execute("INSERT INTO research_purge_authorizations VALUES (?)", (rid,))
        conn.execute("DELETE FROM report_claim_revision_links")
        assert rows(conn, "report_claim_revision_links") == []
        conn.execute("DELETE FROM research_purge_authorizations WHERE research_id = ?", (rid,))
    assert conn.execute("PRAGMA foreign_key_check").fetchall() == []


def test_insert_count_verification_and_event_failure_roll_back(report_with_sections, monkeypatch):
    lib = report_with_sections
    ids = three_links(lib)
    finish(lib)
    conn = lib["store"].conn
    conn.execute("CREATE TRIGGER synthetic_skip BEFORE INSERT ON report_claim_revision_links BEGIN SELECT RAISE(IGNORE); END")
    before = state(lib)
    with pytest.raises(RuntimeError, match="incomplete"):
        edit(lib, link_ids=ids[:1])
    assert state(lib) == before
    conn.execute("DROP TRIGGER synthetic_skip")
    def fail(*args, **kwargs):
        assert conn.in_transaction
        raise RuntimeError("SYNTHETIC event failure")
    monkeypatch.setattr(lib["reports"], "_event", fail)
    with pytest.raises(RuntimeError, match="event failure"):
        edit(lib, link_ids=[])
    assert state(lib) == before


CITATION_READERS = {
    ("workflow/report/assembly.py", "_links"), ("workflow/report/assembly.py", "_claim_depths"),
    ("workflow/report/assembly.py", "_check_gap_bases"), ("workflow/report/sections.py", "_prior_summaries"),
    ("workflow/report/review.py", "_input"), ("workflow/report/store.py", "ReportStore.save_claims"),
    ("workflow/report/store.py", "ReportStore.effective_links"), ("workflow/report/store.py", "ReportStore.removed_links"),
    ("workflow/report/store.py", "ReportStore.original_links"), ("workflow/store.py", "Store.purge_research"),
    ("workflow/store.py", "Store.cited_source_versions"), ("workflow/store.py", "Store.trash"),
    ("workflow/store.py", "Store.research_cites_asset"), ("workflow/store.py", "Store.asset_impact"),
}
REVISION_READERS = {
    ("workflow/report/store.py", "ReportStore.effective_links"), ("workflow/report/store.py", "ReportStore.claim_revisions"),
    ("workflow/report/store.py", "ReportStore.edit_claim"), ("workflow/store.py", "Store.purge_research"),
}


@pytest.mark.parametrize("table,expected", [("report_citation_links", CITATION_READERS),
                                           ("report_claim_revision_links", REVISION_READERS)])
def test_raw_table_access_has_a_fixed_source_allowlist(table, expected):
    root = Path(__file__).resolve().parents[1] / "backend/deixis"
    found = set()
    def visit(node, file, scope=()):
        if isinstance(node, (ast.ClassDef, ast.FunctionDef, ast.AsyncFunctionDef)):
            scope = (*scope, node.name)
        if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)) and any(
                isinstance(item, ast.Constant) and isinstance(item.value, str) and table in item.value
                for item in ast.walk(node)):
            found.add((file, ".".join(scope)))
        for child in ast.iter_child_nodes(node):
            visit(child, file, scope)
    for path in root.rglob("*.py"):
        visit(ast.parse(path.read_text()), path.relative_to(root).as_posix())
    assert found == expected


def test_view_and_staleness_runtime_reads_use_only_authorized_points(report_with_sections, monkeypatch):
    lib = report_with_sections
    rid = finish(lib)
    edit(lib, link_ids=[])
    # Force the view's edit-check manifest branch as well as historical and current projections.
    lib["reports"].check_edits(rid, lib["report_id"])
    failures = []
    seen = []
    allowed = {ReportStore.effective_links.__code__, ReportStore.removed_links.__code__, ReportStore.claim_revisions.__code__}
    def trace(sql):
        if "report_citation_links" not in sql and "report_claim_revision_links" not in sql:
            return
        seen.append(sql)
        frame = inspect.currentframe().f_back
        while frame is not None:
            if frame.f_code in allowed:
                return
            frame = frame.f_back
        failures.append(sql)
    def forbidden(*args):
        raise AssertionError("View and staleness must not read original_links")
    monkeypatch.setattr(ReportStore, "original_links", forbidden)
    lib["store"].conn.set_trace_callback(trace)
    try:
        view = report_view(lib["store"], rid, lib["report_id"])
        changes = lib["reports"].evidence_changes(lib["report_id"])
    finally:
        lib["store"].conn.set_trace_callback(None)
    assert not failures and seen
    assert view["has_human_edits"] and changes["any"] is False


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


def test_gap_basis_cells_ignore_claim_citation_removal(report_with_sections):
    lib = report_with_sections
    cell_report(lib)
    _gap(lib, "stated_limitation", cell_ids=[lib["cell_id"]], claim_keys=["III.1"])
    edit(lib, link_ids=[])
    change_cell(lib)
    changes = lib["reports"].evidence_changes(lib["report_id"])
    assert changes["sections"]["III"]["open"] == [] and changes["sections"]["abstract"]["open"] == []
    assert changes["sections"]["VI"]["open"][0]["cell_id"] == lib["cell_id"]
    assert view_claim(lib, "VI.1")["edited_basis"] == ["III.1"]


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


def test_source_departure_s7_still_counts_report_and_restores_section_marks(report_with_sections):
    lib = report_with_sections
    rid = cell_report(lib)
    edit(lib, link_ids=[])
    edit(lib, "abstract.1", link_ids=[])
    lib["store"].remove_sources(rid, [lib["source_id"]], "SYNTHETIC S7")
    removed = lib["reports"].evidence_changes(lib["report_id"])
    assert removed["removed_sources"] == 1
    assert all(not removed["sections"][sid]["open"] for sid in ("III", "abstract", "VI"))
    edit(lib, restore_from="model")
    restored = lib["reports"].evidence_changes(lib["report_id"])
    assert totals(restored) == totals(removed)
    for sid in ("III", "abstract", "VI"):
        assert restored["sections"][sid]["open"][0]["kind"] == "source_removed"


def test_effective_order_legacy_and_view_revision_changes_current(report_with_sections):
    lib = report_with_sections
    ids = three_links(lib)
    rid = finish(lib)
    old = legacy(lib, text=claim(lib)["text"])
    lib["store"].conn.execute("UPDATE report_claims SET current_revision_id = ? WHERE id = ?", (old, claim(lib)["id"]))
    assert [r["id"] for r in lib["reports"].effective_links(lib["report_id"])] == [
        r["id"] for r in lib["store"].conn.execute("SELECT id FROM report_citation_links ORDER BY rowid")]
    edit(lib, link_ids=[ids[0], ids[2]])
    edited = view_claim(lib)
    assert edited["evidence_basis"] == "direct" and edited["support_type_note"] is None
    assert edited["original_evidence_count"] == 3
    assert edited["removed_links"] == [{"link_id": ids[1], "passage_id": lib["section_passage"], "cell_id": None,
        "source_version_id": lib["source_id"], "anchor_text": "selected-section evidence", "anchor_match": "exact",
        "title": "SYNTHETIC method study", "source_key": lib["store"].conn.execute(
            "SELECT w.source_key FROM works w JOIN source_versions s ON s.work_id = w.id WHERE s.id = ?",
            (lib["source_id"],)).fetchone()[0]}]
    assert [(r["link_count"], r["link_ids"], r["changes_current"]) for r in edited["revisions"]] == [
        (None, None, True), (2, sorted([ids[0], ids[2]]), False)]
    assert view_claim(lib, "abstract.1")["edited_basis"] == ["III.1"]
    edit(lib, link_ids=[])
    assert view_claim(lib)["evidence_basis"] == "none" and view_claim(lib)["support_type_note"] == "model_written_type"
    assert report_view(lib["store"], rid, lib["report_id"])["has_human_edits"] is True


def test_never_cited_claim_has_no_removal_note_and_ambiguous_refs_have_no_edited_basis(report_with_sections):
    lib = report_with_sections
    _add_claim(lib, "IV", "IV.1", "SYNTHETIC never cited", gap_refs=["gap1"])
    _gap(lib, "stated_limitation", claim_keys=["III.1"])
    finish(lib)
    edit(lib, link_ids=[])
    uncited = view_claim(lib, "IV.1")
    assert uncited["evidence_basis"] == "none" and uncited["support_type_note"] is None
    assert uncited["original_evidence_count"] == 0 and uncited["removed_links"] == []
    assert uncited["edited_basis"] == ["III.1"]
    assert view_claim(lib, "abstract.1")["edited_basis"] == ["III.1"]
    _add_claim(lib, "V", "III.1", "SYNTHETIC ambiguous target")
    assert view_claim(lib, "IV.1")["edited_basis"] == []
    assert view_claim(lib, "abstract.1")["edited_basis"] == []


def test_zero_effective_links_count_with_no_integer_records_explicit_skip(report_with_sections):
    lib = report_with_sections
    snapshot = lib["reports"].snapshot(lib["report_id"])
    count = {"numerator_source_ids": [lib["source_id"]], "denominator_source_ids": [lib["source_id"]],
             "column_id": snapshot["columns"][0]["column_id"]}
    _add_claim(lib, "IV", "IV.1", "One source.", count=count, links=[_link(lib)])
    finish(lib)
    assert assembly.run_assembly_checks(lib["store"], lib["reports"], lib["report_id"]) == []
    edit(lib, "IV.1", link_ids=[])
    result = assembly.run_current_checks(lib["store"], lib["reports"], lib["report_id"])
    assert result["items"] == []
    assert result["skipped"] == [
        {"rule": "count_text_not_checked", "section_id": "IV", "claim_key": "IV.1", "reason": "no_integer_in_text"},
        {"rule": "phrase_frames", "section_id": "IV", "claim_key": "IV.1", "reason": "human_text"},
    ]
    assert result["counts"]["skipped"] == 2


def test_report_citations_impact_counts_passage_links_only(report_with_sections):
    from tests.test_asset_replacement import extraction
    lib = report_with_sections
    cell_report(lib)
    asset = lib["store"].add_asset_with_pages(lib["source_id"], "f" * 64, 10, "synthetic-cell.pdf", "user_upload", None,
                                              "synthetic.pdf", extraction(["SYNTHETIC unrelated asset passage"]), "synthetic-v1",
                                              lambda text: [(0, len(text), text)])
    assert lib["store"].asset_impact(asset)["report_citations"] == 0


@pytest.mark.parametrize("case", ["future_cell", "equation_origin", "derived_depth"])
def test_real_removals_run_e1_rules_and_explicit_skips_without_changing_base(report_with_sections, case):
    lib = report_with_sections
    if case == "future_cell":
        _add_claim(lib, "VII", "VII.1", "SYNTHETIC stated direction.", links=[_link(lib, "VII.1", passage=False)])
        key = "VII.1"
    elif case == "equation_origin":
        # Use an actual stored math passage and actual shown input, so only removal introduces origin errors.
        passage = lib["store"]._insert_passage(lib["source_id"], None, "section", None, None, None, None, None,
                                              "SYNTHETIC equation $$x$$.")
        payload = lib["store"].step_input_payload(lib["report_input_id"])
        payload["passages"].append({"passage_id": passage})
        payload["step_input_id"] = new_id("sti")
        report = lib["reports"].report(lib["report_id"])
        lib["store"].insert_step_input(lib["report_step_id"], report["research_id"], report["run_id"], 1,
                                       payload, "base", "developer", "message", {})
        _add_claim(lib, "IV", "IV.1", "SYNTHETIC equation $$x$$.", origin={"passage_id": passage, "text_source": "text_layer"},
                   links=[_link(lib) | {"passage_id": passage, "anchor_text": "equation", "step_input_id": payload["step_input_id"]}])
        key = "IV.1"
    else:
        key = "III.1"
    rid = finish(lib)
    before = assembly.run_assembly_checks(lib["store"], lib["reports"], lib["report_id"])
    assert before == []
    one = lib["reports"].check_edits(rid, lib["report_id"])
    edit(lib, key, link_ids=[])
    two = lib["reports"].check_edits(rid, lib["report_id"])
    assert one["input_fingerprint"] != two["input_fingerprint"]
    result = two["result"]
    assert result["counts"]["edited_claims"] == 1
    expected = []
    if case == "future_cell":
        expected = [{"rule": "vii_claim_without_basis", "section_id": "VII", "detail": "ERROR: VII.1 lacks a basis.", "severity": "error"}]
    elif case == "equation_origin":
        expected = [
            {"rule": "equation_origin_not_cited", "section_id": "IV", "detail": "ERROR: IV.1 origin is not cited by this claim.", "severity": "error"},
            {"rule": "equation_origin_not_in_input", "section_id": "IV", "detail": "ERROR: IV.1 origin was not supplied.", "severity": "error"},
        ]
    assert result["items"] == expected
    expected_skips = [{"rule": "phrase_frames", "section_id": key.split('.')[0], "claim_key": key, "reason": "human_text"}]
    if case == "derived_depth":
        expected_skips.append({"rule": "derived_depth_not_checked", "section_id": "abstract", "claim_key": "abstract.1", "reason": "no_citation_depth"})
    assert result["skipped"] == expected_skips
    assert assembly.run_assembly_checks(lib["store"], lib["reports"], lib["report_id"]) == before
    edit(lib, key, restore_from="model")
    three = lib["reports"].check_edits(rid, lib["report_id"])
    assert three["input_fingerprint"] not in {one["input_fingerprint"], two["input_fingerprint"]}
    assert three["result"]["items"] == []


def dedicated_report_source(lib):
    """A source and asset with no path to citation protection except its report passage."""
    from tests.test_asset_replacement import extraction
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


def test_report_only_asset_protection_and_source_purge_before_removed_restored(report_with_sections):
    lib = report_with_sections
    source, asset = dedicated_report_source(lib)
    rid = finish(lib)
    other = lib["store"].create_research("SYNTHETIC unrelated", "attached", "quick", [], "fake", "fake", "en")
    lib["store"].remove_sources(rid, [source], "SYNTHETIC removed membership")
    for stage in ("original", "removed", "restored"):
        if stage == "removed":
            edit(lib, "IV.1", link_ids=[])
        elif stage == "restored":
            edit(lib, "IV.1", restore_from="model")
        assert_only_report_cites(lib["store"], source)
        assert lib["store"].research_cites_asset(rid, asset)
        assert not lib["store"].research_cites_asset(other, asset)
        impact = lib["store"].asset_impact(asset)
        assert impact["report_citations"] == 1
        assert all(impact[key] == 0 for key in ("cells", "quotes", "lineage_links", "candidate_quotes"))
        assert lib["store"].cited_source_versions([source]) == {source}
        listed = next(row for row in lib["store"].trash()["sources"] if row["source_version_id"] == source)
        assert listed["cited"] == 1 and listed["cells"] == listed["quotes"] == 0
        with pytest.raises(RevisionConflict, match="Evidence still cites"):
            lib["store"].purge_sources(rid, [source])


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


def test_purge_with_nonempty_recorded_sets_leaves_no_revision_links(report_with_sections):
    lib = report_with_sections
    rid = finish(lib)
    edit(lib, link_ids=[])
    edit(lib, restore_from="model")
    assert rows(lib["store"].conn, "report_claim_revision_links")
    lib["store"].trash_research(rid)
    lib["store"].purge_research(rid)
    assert rows(lib["store"].conn, "report_claim_revision_links") == []
    assert lib["store"].conn.execute("PRAGMA foreign_key_check").fetchall() == []
