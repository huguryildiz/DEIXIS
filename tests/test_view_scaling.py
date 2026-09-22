"""Slice 13 follow-up: the research view must not read the library once per work.

On the smoke run's 7,769-source research `research_view` took 37 s on the event loop, 30 s of them in one
`work_versions` query per work over an unindexed `source_versions.work_id`; the DeepSeek health check's 20 s
connect timeout then expired while the loop was blocked and the run paused as `model_connection_not_ready`.
Records are SYNTHETIC; passing shows how many statements the view runs, not what it shows.
"""

from deixis.storage import db
from deixis.workflow.store import Store
from deixis.workflow.views import research_view
from test_source_versions import raw_asset


def library(tmp_path, works: int):
    conn = db.connect(tmp_path / f"library-{works}.sqlite")
    db.migrate(conn)
    store = Store(conn)
    rid = store.create_research("SYNTHETIC question", "attached", "quick", [], "fake", "fake-model", None)
    heads = []
    for n in range(works):
        head = store.create_upload_source(f"SYNTHETIC work {n}")
        store.add_to_corpus(rid, head, "user_upload", candidate=False)
        other = store.open_lookup_version(rid, head, "acceptedVersion", None)
        raw_asset(conn, other, f"sha-{n}", ["SYNTHETIC page text"], "v1")
        heads.append((head, other))
    return conn, store, rid, heads


def statements(conn, call):
    seen = []
    conn.set_trace_callback(seen.append)
    try:
        result = call()
    finally:
        conn.set_trace_callback(None)
    return result, seen


def test_the_version_an_answer_reads_is_found_for_every_work_in_a_bounded_number_of_statements(tmp_path):
    counts = {}
    for works in (3, 9):
        conn, store, rid, heads = library(tmp_path, works)
        view, seen = statements(conn, lambda: research_view(store, rid))
        by_id = {s["source_version_id"]: s for s in view["sources"]}
        assert all(by_id[head]["answer_reads_version_id"] == other for head, other in heads)
        counts[works] = sum("source_versions" in sql and "work_id" in sql for sql in seen)
    assert counts[9] == counts[3], counts  # the version lookup does not grow with the number of works


def test_source_versions_are_indexed_by_work(tmp_path):
    conn = db.connect(tmp_path / "library.sqlite")
    db.migrate(conn)
    plan = conn.execute("EXPLAIN QUERY PLAN SELECT id FROM source_versions WHERE work_id = ?", ("wrk_x",)).fetchall()
    assert any("USING INDEX" in row[3] and "work_id" in row[3] for row in plan), [tuple(r) for r in plan]
