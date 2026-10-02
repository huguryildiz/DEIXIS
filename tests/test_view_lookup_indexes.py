"""P9 H5 fix round 1: the research view's per-source lookups are index searches (migration 0063).

At N=5,000 `research_view` ran about 8 statements per source version, and four of them scanned a whole table each
time (`identifier_mappings`, `run_steps` twice, `source_assets`), so the view grew faster than linearly. Records are
SYNTHETIC; passing shows plans and unchanged view JSON, not speed on a real library.
"""

import json
import shutil
from types import SimpleNamespace

import pytest

from deixis.documents import pdf
from deixis.providers.common import OtherVersion, ProviderRecord
from deixis.storage import db
from deixis.workflow.store import Store
from deixis.workflow.views import research_view

# index name -> (picks the statement out of what `research_view` ran, the plan's name for the table it reads)
LOOKUPS = {
    "identifier_mappings_view_lookup": (lambda q: "FROM identifier_mappings" in q and "scheme = provider" in q, "identifier_mappings"),
    "run_steps_operation": (lambda q: "FROM run_steps" in q and "JOIN" not in q and "operation_key = 'fetch:" in q, "run_steps"),
    "run_steps_operation_joined": (lambda q: "JOIN runs" in q and "operation_key = 'other_copy:" in q, "s"),
    "source_assets_replaced": (lambda q: "removal_reason = 'replaced'" in q, "source_assets"),
    "passages_asset": (lambda q: "FROM passages WHERE asset_id" in q and "kind = 'pdf_page'" in q, "passages"),
}
INDEX_OF = {"run_steps_operation_joined": "run_steps_operation"}


def plan(conn, sql, phase):
    # The comment keeps the text of an EXPLAIN apart per phase: sqlite3 caches the prepared statement by its text and would
    # show the plan from before the indexes were dropped.
    return [row[3] for row in conn.execute(f"EXPLAIN QUERY PLAN {sql} /* {phase} */")]


def traced_lookups(conn, store, rid):
    """The statements `research_view` really ran for each lookup (the trace text has the parameters substituted)."""
    ran = []
    conn.set_trace_callback(ran.append)
    try:
        research_view(store, rid)
    finally:
        conn.set_trace_callback(None)
    ran = [" ".join(q.split()) for q in ran]
    found = {name: sorted({q for q in ran if pick(q)}) for name, (pick, _) in LOOKUPS.items()}
    assert all(found.values()), {name: len(qs) for name, qs in found.items()}  # every lookup was seen, none is hand-copied
    return found


def record(n, provider="openalex", other=False):
    versions = [OtherVersion("submittedVersion", f"https://h5.invalid/{n}.pdf", None, "SYNTHETIC venue")] if other else []
    return ProviderRecord(
        provider_record_id=f"{provider}-{n}", title=f"SYNTHETIC lookup study {n}", authors=["A One", "B Two"], year=2020,
        venue="SYNTHETIC venue", publication_type="journal-article", doi=f"10.5555/h5.lookup.{n}", landing_url=None,
        oa_pdf_url=f"https://h5.invalid/oa/{n}.pdf", oa_pdf_version="publishedVersion", version_label="publishedVersion",
        abstract=f"SYNTHETIC abstract {n}.", abstract_origin="provider_openalex_inverted_index", identifiers={}, raw={},
        other_versions=versions)


def pdf_extraction(tag):
    text = f"SYNTHETIC page text {tag}"
    return pdf.Extraction("succeeded", 1, [pdf.PageText(1, None, text)])


def rich_library(path, works=6):
    """A research with what the per-source loop reads: replaced assets, a failed fetch, another copy lookup, PDF
    candidates and discoveries, a second provider's record, another version, and an earlier run of the same step."""
    conn = db.connect(path)
    db.migrate(conn)
    store = Store(conn)
    rid = store.create_research("SYNTHETIC lookup question", "academic", "standard", ["openalex"], "codex", None, None)
    first = store.create_run(rid, "discovery", {"max_model_calls": 0, "max_provider_requests": 1}, None)
    conn.execute("UPDATE runs SET status = 'completed' WHERE id = ?", (first["id"],))
    second = store.create_run(rid, "pdf_collection", {"max_model_calls": 0, "max_provider_requests": 1}, None)
    conn.execute("UPDATE runs SET status = 'completed' WHERE id = ?", (second["id"],))
    search = store.step(first["id"], "search:0", "search")
    srid = store.add_search_run(research_id=rid, run_id=first["id"], step_id=search["id"], scope_revision=1, provider="openalex",
                                query_text="SYNTHETIC", request_description="SYNTHETIC", access_mode="open", status="completed",
                                result_count=works, page_limit=1)
    store.finish_step(search["id"], "succeeded")
    svids = []
    for n in range(works):
        rec = record(n, other=n == 3)
        svid, _ = store.upsert_provider_source("openalex", rec, None)
        if n % 2 == 0:
            store.upsert_provider_source("crossref", record(n, "crossref"), None)
        store.add_to_corpus(rid, svid, "search", srid, n, selection_state="included" if n < 4 else "pending", scope_revision=1)
        for other in store.other_version_ids("openalex", rec):
            store.add_to_corpus(rid, other, "search", srid, candidate=False, scope_revision=1)
        svids.append(svid)
    chunker = pdf.chunk_page
    first_asset = store.add_asset_with_pages(svids[0], "a" * 64, 10, "a.pdf", "download", None, None, pdf_extraction("a"),
                                             pdf.EXTRACTION_VERSION, chunker)
    store.replace_asset(first_asset, "b" * 64, 10, "b.pdf", "user_upload", None, "b.pdf", pdf_extraction("b"),
                        pdf.EXTRACTION_VERSION, chunker)
    store.add_asset_with_pages(svids[1], "c" * 64, 10, "c.pdf", "download", None, None, pdf_extraction("c"), pdf.EXTRACTION_VERSION, chunker)
    # An earlier and a later attempt of the same fetch: the view reads the latest one.
    for run, status, code, started in ((first, "failed", "fetch_http_error", "2026-01-01T00:00:00+00:00"),
                                       (second, "failed", "fetch_not_pdf", "2026-02-01T00:00:00+00:00")):
        step = store.step(run["id"], f"fetch:{svids[2]}", "fetch_pdf")
        store.start_step(step["id"], started)
        store.finish_step(step["id"], "failed", error_code=code, error={"http_status": 403})
    copy = store.step(second["id"], f"other_copy:{svids[2]}", "other_copy")
    store.start_step(copy["id"], "2026-02-02T00:00:00+00:00")
    store.finish_step(copy["id"], "succeeded")
    discovery = store.record_pdf_discovery(rid, svids[4], "unpaywall", "SYNTHETIC query",
                                           SimpleNamespace(status="completed", candidates=[1], other_title_count=0, http_status=200, error_code=None))
    store.record_pdf_candidates(svids[4], discovery, [SimpleNamespace(
        provider="unpaywall", url="https://h5.invalid/c.pdf", landing_url=None, version_label="acceptedVersion", license=None,
        identity_status="doi_verified", version_status="match")])
    conn.commit()
    return conn, store, rid, svids


def view_json(store, rid):
    return json.dumps(research_view(store, rid), sort_keys=True, default=str)


def drop_indexes(conn):
    conn.execute("DROP INDEX IF EXISTS identifier_mappings_view_lookup")
    conn.execute("DROP INDEX IF EXISTS run_steps_operation")
    conn.execute("DROP INDEX IF EXISTS source_assets_replaced")
    conn.execute("DROP INDEX IF EXISTS passages_asset")


def test_the_view_lookups_are_index_searches_and_scans_without_the_indexes(tmp_path):
    conn, store, rid, _ = rich_library(tmp_path / "library.sqlite")
    found = traced_lookups(conn, store, rid)
    for name, queries in found.items():
        table, index = LOOKUPS[name][1], INDEX_OF.get(name, name)
        for query in queries:
            steps = plan(conn, query, "with indexes")
            assert any(f"SEARCH {table}" in step and "USING" in step and index in step for step in steps), (name, query, steps)
            assert not any(step.startswith(f"SCAN {table}") for step in steps), (name, query, steps)
    drop_indexes(conn)
    for name, queries in found.items():
        table = LOOKUPS[name][1]
        for query in queries:
            steps = plan(conn, query, "without indexes")
            assert any(step.startswith(f"SCAN {table}") for step in steps), (name, query, steps)  # the regression: the old schema scanned


def test_the_view_is_the_same_with_and_without_the_indexes(tmp_path):
    conn, store, rid, svids = rich_library(tmp_path / "library.sqlite")
    with_indexes = view_json(store, rid)
    view = json.loads(with_indexes)
    by_id = {s["source_version_id"]: s for s in view["sources"]}
    # The fixture really exercises the lookups, so that equality is not between two empty answers.
    assert len(by_id[svids[0]]["access"]["replaced_assets"]) == 1
    assert by_id[svids[2]]["access"]["fetch"]["error_code"] == "fetch_not_pdf"
    assert by_id[svids[2]]["access"]["other_copy"]["status"] == "succeeded"
    assert by_id[svids[4]]["access"]["pdf_discoveries"] and by_id[svids[4]]["access"]["pdf_candidates"]
    assert by_id[svids[0]]["provider_records"] == ["crossref", "openalex"]
    assert any(s["version_role"] == "other_version" for s in view["sources"])
    drop_indexes(conn)
    assert view_json(store, rid) == with_indexes


def test_migration_0063_applies_on_an_old_library_once_and_changes_no_rows(tmp_path):
    old = tmp_path / "migrations"
    old.mkdir()
    for path in db.MIGRATIONS_DIR.glob("*.sql"):
        if int(path.name.split("_", 1)[0]) <= 62:
            shutil.copy(path, old / path.name)
    real = db.MIGRATIONS_DIR
    try:
        db.MIGRATIONS_DIR = old
        conn = db.connect(tmp_path / "library.sqlite")
        db.migrate(conn)
    finally:
        db.MIGRATIONS_DIR = real
    store = Store(conn)
    rid = store.create_research("SYNTHETIC old library", "academic", "standard", ["openalex"], "codex", None, None)
    svid, _ = store.upsert_provider_source("openalex", record(1), None)
    store.add_to_corpus(rid, svid, "search", None, 0, selection_state="pending", scope_revision=1)
    tables = [r[0] for r in conn.execute("SELECT name FROM sqlite_master WHERE type = 'table' AND name NOT LIKE 'sqlite_%'")]
    before = {t: sorted((tuple(r) for r in conn.execute(f"SELECT * FROM {t}")), key=repr) for t in tables}
    assert not conn.execute("SELECT 1 FROM sqlite_master WHERE name = 'run_steps_operation'").fetchone()

    assert db.migrate(conn) == [63]
    assert db.migrate(conn) == []  # an applied migration is not run again
    after = {t: sorted((tuple(r) for r in conn.execute(f"SELECT * FROM {t}")), key=repr) for t in tables}
    migrations = {t: rows for t, rows in after.items() if t != "schema_migrations"}
    assert migrations == {t: rows for t, rows in before.items() if t != "schema_migrations"}
    names = {r[0] for r in conn.execute("SELECT name FROM sqlite_master WHERE type = 'index'")}
    assert {"identifier_mappings_view_lookup", "run_steps_operation", "source_assets_replaced", "passages_asset"} <= names
    # The file is written to be run twice without harm as well.
    sql = (real / "0063_view_lookup_indexes.sql").read_text()
    conn.executescript(sql)
