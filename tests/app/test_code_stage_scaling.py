"""Slice 13d: the abstract code stage must not read the library once per record.

On the smoke run's 7,377-candidate research `code:abstract_stage` held the event loop for 177 s, and a profile of
the same database put 173 of them in one `work_heads` call per decided work — a join over every record of the
research, run twice for each of 4,695 works while the API could answer nothing. What is counted here is how many
statements of that shape the stage runs, which must not grow with the number of records. Records are SYNTHETIC;
passing says nothing about screening quality.
"""

from deixis.storage import db
from deixis.workflow.flow import ResearchFlow
from deixis.workflow.store import Store
from test_stage_decisions import record, search
from test_view_scaling import statements

# The `work_heads` join, and the one-record reads `derive_selection` and `_write_abstract_codes` used to make.
# `set_trace_callback` hands over the statement with its parameters already in it, so the shapes carry no `?`.
SHAPES = {
    "work_heads": lambda sql: "LEFT JOIN candidates c" in sql,
    "one_selection": lambda sql: "FROM selections WHERE research_id = " in sql and "source_version_id = " in sql,
    "one_source": lambda sql: sql.startswith("SELECT * FROM source_versions WHERE id = "),
}


def library(tmp_path, records: int):
    conn = db.connect(tmp_path / f"library-{records}.sqlite")
    db.migrate(conn)
    store = Store(conn)
    rid = store.create_research("SYNTHETIC question?", "academic", "standard", ["openalex"], "fake", "m", "en",
                                search_workflow="sw")
    run = store.create_run(rid, "discovery", {"max_model_calls": 4, "max_provider_requests": 4,
                                              "max_candidates": 500, "max_answer_passages": 8}, None)
    search(store, rid, run["id"], 0, "openalex",
           [record(f"W{n}", title=f"SYNTHETIC release scheduling for diffusion channels {n}",
                   doi=f"10.1109/synth.2026.{n}") for n in range(records)])
    return conn, store, rid


def counted(conn, call):
    result, seen = statements(conn, call)
    return result, {name: sum(matches(sql) for sql in seen) for name, matches in SHAPES.items()}


def test_the_stage_s_whole_research_reads_do_not_grow_with_the_number_of_records(tmp_path):
    """`_write_abstract_codes` writes the same decisions for 30 and for 90 records with the same reads."""
    counts = {}
    for records in (30, 90):
        conn, store, rid = library(tmp_path, records)
        flow = ResearchFlow.__new__(ResearchFlow)
        flow.store = store
        writes = [(svid, "both_blocks_missing") for svid in sorted(
            row[0] for row in conn.execute("SELECT source_version_id FROM candidates WHERE research_id = ?", (rid,)))]
        written, counts[records] = counted(conn, lambda: flow._write_abstract_codes({"research_id": rid}, None, writes))
        assert written == {"both_blocks_missing": records}
        assert conn.execute("SELECT COUNT(*) FROM selections WHERE research_id = ? AND origin = 'code_rule'",
                            (rid,)).fetchone()[0] == records
        conn.close()
    assert counts[90] == counts[30], counts
