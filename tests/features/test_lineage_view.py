"""L6 synthetic database reads and real flow records with a fake adapter only."""

import json
import sqlite3

import pytest

from deixis.storage import db
from deixis.workflow.lineage_run import build_node, node_snapshot
from deixis.workflow.lineage_view import LineageView
from fakes import valid_response
from test_lineage_flow import lib, queue, execute, invalid, publication, reextract, scope_edit, instruction_edit
from test_lineage_plan import fill
from test_lineage_store import proposal
from test_lineage_flow import factory  # noqa: F401  (fixtures used by name)


def read(lib):
    return LineageView(lib.store).view(lib.rid, lib.tid)


def field(lib):
    return LineageView(lib.store).baseline(lib.rid, lib.tid)


def human_add(lib, a="a", b="b", **kw):
    pair = lib.lineage.link(lib.tid, lib.ids[a], lib.ids[b])
    fields = {"relation": "extends", "what_changed": "SYNTHETIC human change", "support_type": "source_stated",
              "evidence": [{"passage_id": lib.passages[b], "quote": "SYNTHETIC"}], "note": None,
              "expected_version": pair["version"] if pair else 0, "idempotency_key": None}
    return lib.lineage.add_link(lib.rid, lib.tid, lib.ids[a], lib.ids[b], **(fields | kw))


def negatives(si):
    output = json.loads(valid_response(si))
    for d in output["decisions"]:
        d.update(decision="no_relation", relation=None, what_changed=None, support_type=None, evidence=[])
    return json.dumps(output)


def model_decision(lib, a="a", b="b", decision="link", **kw):
    inputs = {"from": node_snapshot(build_node(lib.store, lib.tid, lib.ids[a])),
              "to": node_snapshot(build_node(lib.store, lib.tid, lib.ids[b])),
              "mention_passage_ids": [lib.passages[b]]}
    output = {"decision": decision, "relation": "extends" if decision == "link" else None,
              "what_changed": "SYNTHETIC change" if decision == "link" else None,
              "support_type": "source_stated" if decision == "link" else None,
              "evidence": [{"passage_id": lib.passages[b], "quote": "SYNTHETIC"}] if decision == "link" else [], "note": "SYNTHETIC note"}
    arguments = proposal(lib, a, b, decision=output, inputs=inputs, input_fingerprint=db.new_id("synthetic"))
    return lib.lineage.apply_model_proposal(**(arguments | kw))


def row(lib, letter="b", value=None):
    return next(u for u in (value or read(lib))["unplaceable"] if u["source_version_id"] == lib.ids[letter])


def links(value):
    return [l for c in value["components"] for l in c["links"]]


def test_view_places_links_into_components_with_year_order(lib):
    # Years conflict with table order, so a sort that ignored years would fail.
    for letter, year in (("a", 2005), ("b", 2003), ("c", 2004)):
        lib.conn.execute("UPDATE source_versions SET year = ? WHERE id = ?", (year, lib.ids[letter]))
    model_decision(lib, "a", "b")
    human_add(lib, "b", "c")
    value = read(lib)
    assert len(value["components"]) == 1 and value["components"][0]["members"] == [lib.ids[k] for k in "bca"]
    assert [l["author"] for l in links(value)] == ["human", "model"]
    assert value["status"]["placed_rows"] == 3 and all(u["source_version_id"] not in {lib.ids[k] for k in "abc"} for u in value["unplaceable"])


@pytest.mark.parametrize("author,change,reason", [("model", "extraction", "evidence_not_current"), ("human", "cell", None)])
def test_stale_link_stays_out_of_the_component_and_in_history_with_its_reasons(lib, author, change, reason):
    model_decision(lib) if author == "model" else human_add(lib)
    if change == "cell":
        fill(lib)
    elif change == "instruction":
        instruction_edit(lib)
    elif change == "scope":
        scope_edit(lib)
    elif change == "extraction":
        reextract(lib)
    else:
        lib.conn.execute("UPDATE source_assets SET removed_at = 'now', removal_reason = ? WHERE id = ?",
                         ("replaced" if change == "replaced" else "wrong_file", lib.assets[lib.ids["b"]]))
    value = read(lib)
    if reason:
        assert value["components"] == [] and value["history"]["stale"][0]["stale_reasons"] == [reason]
        assert "stale_only" in row(lib, value=value)["reasons"]
    else:
        assert links(value) and value["history"]["stale"] == []


def stored_state(lib):
    return {t: [tuple(r) for r in lib.conn.execute(f"SELECT * FROM {t}")] for t in
            ("lineage_links", "lineage_link_revisions", "lineage_link_evidence", "events")}


def citation(lib, a="a", b="b", state="present"):
    lib.conn.execute("UPDATE source_versions SET references_read = ? WHERE id = ?", (state != "not_read", lib.ids[b]))
    if state != "unresolved":
        lib.conn.execute("INSERT OR IGNORE INTO identifier_mappings (source_version_id, scheme, value, provider, retrieved_at) VALUES (?, 'openalex', 'W1', 'synthetic_fixture', 'SYNTHETIC')", (lib.ids[a],))
    if state == "present":
        lib.conn.execute("INSERT OR IGNORE INTO record_references (source_version_id, referenced_id) VALUES (?, 'W1')", (lib.ids[b],))


def test_view_and_baseline_reads_execute_no_write_statement(lib):
    model_decision(lib)
    before = stored_state(lib)
    blocked = {getattr(sqlite3, k) for k in ("SQLITE_INSERT", "SQLITE_UPDATE", "SQLITE_DELETE", "SQLITE_CREATE_TABLE",
               "SQLITE_DROP_TABLE", "SQLITE_ALTER_TABLE", "SQLITE_CREATE_INDEX", "SQLITE_DROP_INDEX", "SQLITE_CREATE_TRIGGER", "SQLITE_DROP_TRIGGER")}
    def authorizer(action, *args):
        assert action not in blocked, (action, args)
        return sqlite3.SQLITE_OK
    lib.conn.set_authorizer(authorizer)
    try:
        read(lib)
        field(lib)
    finally:
        lib.conn.set_authorizer(None)
    assert stored_state(lib) == before and lib.adapter.calls == [] and lib.seen == []


def test_a_human_decision_closes_an_open_failure_but_the_run_record_is_kept(lib):
    lib.adapter.responder = invalid
    run = queue(lib)
    execute(lib, run)
    before = publication(lib, run)
    human_add(lib)
    assert read(lib)["step_outcomes"] == [] and publication(lib, run) == before


def test_baseline_uses_stored_counts_and_ranks_only_known_counts(lib):
    lib.conn.execute("UPDATE source_versions SET cited_by_count = 0, cited_by_count_at = 'SYNTHETIC-date' WHERE id = ?", (lib.ids["a"],))
    lib.conn.execute("UPDATE source_versions SET cited_by_count = 12, publication_type = 'review' WHERE id = ?", (lib.ids["b"],))
    value = field(lib)
    entries = value["most_cited_in_corpus"]["entries"]
    assert [e["source_version_id"] for e in entries] == [lib.ids["b"], lib.ids["a"]]
    assert entries[-1]["cited_by_count"] == 0 and entries[-1]["cited_by_count_at"] == "SYNTHETIC-date"
    assert value["review_in_corpus"]["entries"][0]["source_version_id"] == lib.ids["b"]
