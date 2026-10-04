"""L6 synthetic database reads and real flow records with a fake adapter only."""

import ast
import inspect
import json
import sqlite3

import pytest

from deixis.models import prompt
from deixis.storage import db
from deixis.workflow.lineage import view as view_module
from deixis.workflow.lineage.run import build_node, node_snapshot, stale_link_reasons, stale_link_revisions
from deixis.workflow.lineage.view import LineageView
from fakes import valid_response
from test_lineage_flow import (factory, lib, queue, execute, invalid, all_links, publication,
                               reextract, scope_edit, selection_edit, instruction_edit)
from test_lineage_plan import attach, fill
from test_lineage_store import proposal, REJECTION_CODES


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


def test_diamond_from_stored_links(lib):
    for a, b in (("a", "b"), ("a", "c"), ("b", "d"), ("c", "d")):
        human_add(lib, a, b)
    c = read(lib)["components"][0]
    assert c["roots"] == c["branches"] == [lib.ids["a"]] and c["merges"] == [lib.ids["d"]] and not c["has_cycle"]


def test_cross_relation_is_listed_apart_and_builds_no_component(lib):
    human_add(lib, relation="independent_parallel")
    value = read(lib)
    assert value["components"] == [] and len(value["cross_relations"]) == 1
    assert value["counts"]["current_links"] == value["counts"]["cross_relations"] == 1
    assert "cross_relation_only" in row(lib, value=value)["reasons"]


@pytest.mark.parametrize("author,change,reason", [
    ("model", "cell", "node_changed"), ("model", "instruction", "node_changed"), ("model", "scope", "scope_changed"),
    ("model", "removed", "evidence_not_current"), ("model", "replaced", "evidence_not_current"),
    ("model", "extraction", "evidence_not_current"), ("human", "cell", None),
    ("human", "removed", "evidence_not_current"), ("human", "extraction", "evidence_not_current")])
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


@pytest.mark.parametrize("change", ["excluded", "row_removed"])
def test_selection_change_makes_the_link_out_of_scope_not_stale(lib, change):
    model_decision(lib)
    if change == "excluded":
        selection_edit(lib)
    else:
        lib.tables.remove_row(lib.rid, lib.tid, lib.ids["a"], lib.tables._table(lib.rid, lib.tid)["version"])
    value = read(lib)
    assert value["components"] == [] and not value["history"]["stale"]
    assert value["history"]["out_of_scope"][0]["not_live_ends"] == ["from"]
    assert value["history"]["out_of_scope"][0]["stale_reasons"] == []


def test_head_change_is_a_flag_not_a_stale_reason(lib):
    model_decision(lib)
    work = lib.store.source(lib.ids["a"])["work_id"]
    published = lib.store.create_upload_source("SYNTHETIC published version")
    lib.conn.execute("UPDATE source_versions SET work_id = ?, doi = '10.1/synthetic', version_label = 'publishedVersion' WHERE id = ?", (work, published))
    lib.store.add_to_corpus(lib.rid, published, "user_upload", selection_state="included", selection_origin="user")
    assert lib.store.work_heads(lib.rid)[work] == published
    value = read(lib)
    assert links(value)[0]["not_head_ends"] == ["from"] and not links(value)[0]["stale_reasons"]


def stored_state(lib):
    return {t: [tuple(r) for r in lib.conn.execute(f"SELECT * FROM {t}")] for t in
            ("lineage_links", "lineage_link_revisions", "lineage_link_evidence", "events")}


def test_stale_edge_is_excluded_from_assembly_but_the_decision_row_is_unchanged(lib):
    model_decision(lib)
    fill(lib)
    before = stored_state(lib)
    assert read(lib)["components"] == []
    assert stored_state(lib) == before


@pytest.mark.parametrize("reason", ["not_run", "no_pdf_text", "no_candidate", "no_relation", "insufficient_evidence",
                                   "rejected", "not_sent_budget", "step_failed", "human_removed", "cross_relation_only", "stale_only"])
def test_every_unplaceable_reason_from_real_state(factory, reason):
    lib = factory(n=28, mentions=(0, *range(2, 28)), only_target=True) if reason == "not_sent_budget" else factory()
    target = "b"
    if reason == "no_pdf_text":
        target = "a"
    elif reason == "no_candidate":
        target = "c"
        execute(lib, queue(lib))
    elif reason in ("no_relation", "insufficient_evidence"):
        model_decision(lib, decision=reason)
    elif reason == "rejected":
        result = model_decision(lib, input_stale=True)
        assert result["rejection_code"] == "stale_input"
    elif reason == "not_sent_budget":
        lib.adapter.responder = negatives
        execute(lib, queue(lib))
    elif reason == "step_failed":
        lib.adapter.responder = invalid
        execute(lib, queue(lib))
    elif reason == "human_removed":
        revision = human_add(lib)
        pair = lib.lineage.link(lib.tid, lib.ids["a"], lib.ids["b"])
        lib.lineage.remove_link(lib.rid, lib.tid, pair["id"], None, revision, pair["version"], None)
    elif reason == "cross_relation_only":
        human_add(lib, relation="independent_parallel")
    elif reason == "stale_only":
        model_decision(lib)
        fill(lib)
    assert reason in row(lib, target)["reasons"]


@pytest.mark.parametrize("code", REJECTION_CODES)
def test_rejected_reason_records_each_l4_rejection_code(lib, code):
    a, b, kw = "a", "b", {}
    if code == "cycle":
        human_add(lib, "b", "a")
    elif code == "same_work":
        lib.conn.execute("UPDATE source_versions SET work_id = ? WHERE id = ?", (lib.store.source(lib.ids["a"])["work_id"], lib.ids["b"]))
    elif code == "endpoint_not_included":
        selection_edit(lib)
    elif code == "superseded_by_human":
        human_add(lib, relation="independent_parallel")
    elif code == "stale_input":
        kw["input_stale"] = True
    elif code == "anchor_not_found":
        lib.passages["b"] = lib.passages["a"]
    result = model_decision(lib, **kw)
    assert result["rejection_code"] == code
    if code == "cycle":
        assert read(lib)["not_accepted"][0]["rejection_code"] == code
    else:
        assert "rejected" in row(lib)["reasons"]


def test_a_row_appears_once_with_several_reasons_and_placed_rows_are_absent(lib):
    model_decision(lib, decision="no_relation")
    human_add(lib, "c", "b", relation="independent_parallel")
    value = read(lib)
    assert {"not_run", "no_relation", "cross_relation_only"} <= set(row(lib, value=value)["reasons"])
    assert len([u for u in value["unplaceable"] if u["source_version_id"] == lib.ids["b"]]) == 1
    human_add(lib)
    assert lib.ids["b"] not in {u["source_version_id"] for u in read(lib)["unplaceable"]}


def test_eligible_row_without_applicable_decision_uses_the_fallback(lib):
    execute(lib, queue(lib))
    reextract(lib, "c", "SYNTHETIC Author000 (2000)")
    # Target has run, has a current candidate, and its new pair has no decision.
    value = read(lib)
    assert row(lib, "c", value)["reasons"] == ["not_run"]
    assert row(lib, "c", value)["last_run"] is not None


def test_not_accepted_lists_the_latest_rejected_revision_and_the_pair_state(lib):
    first = model_decision(lib, input_stale=True)
    last = model_decision(lib, input_stale=True)
    value = read(lib)["not_accepted"][0]
    assert value["revision_id"] == last["revision_id"] != first["revision_id"] and not value["superseded"]
    human_add(lib)
    value = read(lib)["not_accepted"][0]
    assert value["superseded"] and value["pair_state"] == {"decision": "link", "author": "human"}
    model_decision(lib, "c", "d", input_stale=True)
    model_decision(lib, "c", "d", decision="no_relation")
    assert all(n["superseded"] for n in read(lib)["not_accepted"])


def test_not_accepted_non_live_target_ties_use_from_position_before_identity(lib):
    lib.conn.execute("UPDATE source_versions SET year = 2010 WHERE id IN (?, ?)", (lib.ids["c"], lib.ids["d"]))
    # Assign the lexically earlier target to the later from-row to expose an ID tie-break.
    earlier, later = sorted(("c", "d"), key=lambda key: lib.ids[key])
    model_decision(lib, "a", later, input_stale=True)
    model_decision(lib, "b", earlier, input_stale=True)
    selection_edit(lib, "c")
    selection_edit(lib, "d")
    assert [p["from"] for p in read(lib)["not_accepted"]] == [lib.ids["a"], lib.ids["b"]]


def citation(lib, a="a", b="b", state="present"):
    lib.conn.execute("UPDATE source_versions SET references_read = ? WHERE id = ?", (state != "not_read", lib.ids[b]))
    if state != "unresolved":
        lib.conn.execute("INSERT OR IGNORE INTO identifier_mappings (source_version_id, scheme, value, provider, retrieved_at) VALUES (?, 'openalex', 'W1', 'synthetic_fixture', 'SYNTHETIC')", (lib.ids[a],))
    if state == "present":
        lib.conn.execute("INSERT OR IGNORE INTO record_references (source_version_id, referenced_id) VALUES (?, 'W1')", (lib.ids[b],))


def test_unassessed_edge_present_edge_without_mention_in_a_scanned_target(lib):
    citation(lib, "a", "c")
    execute(lib, queue(lib))
    value = read(lib)
    assert {"from": lib.ids["a"], "to": lib.ids["c"]} in value["unassessed_edges"]
    human_add(lib, "a", "c")
    assert {"from": lib.ids["a"], "to": lib.ids["c"]} not in read(lib)["unassessed_edges"]


@pytest.mark.parametrize("target,reason", [("a", "no_pdf_text"), ("c", "not_run")])
def test_present_edge_into_an_unscanned_target_is_listed_apart(lib, target, reason):
    citation(lib, "b", target)
    value = read(lib)
    assert {"from": lib.ids["b"], "to": lib.ids[target], "to_reason": reason} in value["edges_into_unscanned_targets"]
    assert value["unassessed_edges"] == []


@pytest.mark.parametrize("state", ["present", "absent_in_read_list", "unresolved", "not_read"])
def test_unexpected_no_citation_edge_only_when_absent_in_read_list(lib, state):
    human_add(lib)
    citation(lib, state=state)
    value = links(read(lib))[0]
    assert value["edge_state"] == state and value["unexpected_no_citation_edge"] == (state == "absent_in_read_list")


def test_not_sent_budget_list_drops_a_pair_after_a_later_revision(factory):
    lib = factory(n=28, mentions=(0, *range(2, 28)), only_target=True)
    first = queue(lib)
    execute(lib, first)
    assert len(read(lib)["not_sent_budget"]) == 3
    execute(lib, queue(lib))
    assert read(lib)["not_sent_budget"] == []


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


def test_view_is_one_synchronous_read(lib):
    # AST checks every view helper; trace verifies one outer transaction per read.
    tree = ast.parse(inspect.getsource(view_module))
    assert not any(isinstance(n, (ast.Await, ast.AsyncFunctionDef)) for n in ast.walk(tree))
    statements = []
    lib.conn.set_trace_callback(statements.append)
    for operation in (read, field):
        statements.clear()
        operation(lib)
        assert statements.count("BEGIN IMMEDIATE") == 1 and statements.count("COMMIT") == 1
    lib.conn.set_trace_callback(None)


def test_forbidden_words_are_absent_from_deixis_text_but_source_text_is_returned_unchanged(lib):
    text = "foundational founder novel original continuation"
    lib.conn.execute("UPDATE source_versions SET title = ? WHERE id = ?", (text, lib.ids["b"]))
    pid = lib.store._insert_passage(lib.ids["b"], None, "abstract", None, None, "synthetic_fixture", None, None, text)
    human_add(lib, what_changed=text, note=text, evidence=[{"passage_id": pid, "quote": text}])
    value = read(lib)
    link = links(value)[0]
    assert value["nodes"][lib.ids["b"]]["title"] == link["what_changed"] == link["note"] == link["evidence"][0]["anchor_text"] == text
    def keys(obj):
        if isinstance(obj, dict):
            return set(obj) | set().union(*(keys(v) for v in obj.values()))
        if isinstance(obj, list):
            return set().union(*(keys(v) for v in obj))
        return set()
    forbidden = {"foundational", "founder", "continuation"}
    baseline = field(lib)
    for output in (value, baseline):
        assert not {part for key in keys(output) for part in key.split("_")} & forbidden
    assert not any(word in json.dumps([u["reasons"] for u in value["unplaceable"]]) for word in text.split())
    labels = [baseline["scope"], baseline["most_cited_in_corpus"]["note"], baseline["review_in_corpus"]["note"]]
    assert not any(word in label.lower() for label in labels for word in forbidden)


def test_a_carried_failure_stays_an_open_pair_failure_when_the_later_run_publishes_empty_failed_pairs(factory):
    lib = factory(n=28, mentions=(0, *range(2, 28)), only_target=True)
    lib.adapter.responder = invalid
    first = queue(lib)
    execute(lib, first)
    initial = read(lib)["failed_pairs"]
    assert len(initial) == 24
    lib.adapter.responder = valid_response
    second = queue(lib)
    execute(lib, second)
    assert publication(lib, second)["failed_pairs"] == []
    assert read(lib)["failed_pairs"] == initial
    execute(lib, queue(lib, retry_failed=True))
    assert read(lib)["failed_pairs"] == []
    fill(lib, text="SYNTHETIC input B")
    assert read(lib)["failed_pairs"] == []
    # Restore A's current pointer; old failed fingerprints must not resurrect.
    lib.conn.execute("UPDATE evidence_cells SET current_revision_id = NULL WHERE table_id = ?", (lib.tid,))
    assert read(lib)["failed_pairs"] == []


def test_a_pair_failure_is_listed_whether_or_not_its_row_is_placed(lib):
    lib.adapter.responder = invalid
    execute(lib, queue(lib))
    assert read(lib)["failed_pairs"]
    human_add(lib, "c", "b")
    value = read(lib)
    assert value["failed_pairs"] and lib.ids["b"] not in {u["source_version_id"] for u in value["unplaceable"]}


def test_no_candidate_is_current_not_historical(lib):
    execute(lib, queue(lib))
    assert "no_candidate" in row(lib, "c")["reasons"]
    reextract(lib, "c", "SYNTHETIC Author000 (2000)")
    assert "no_candidate" not in row(lib, "c")["reasons"]
    human_add(lib, "a", "c", relation="independent_parallel")
    assert "no_candidate" not in row(lib, "c")["reasons"]


@pytest.mark.parametrize("decision", ["no_relation", "insufficient_evidence", "rejected"])
@pytest.mark.parametrize("change,reason", [("scope", "scope_changed"), ("node", "node_changed"), ("passage", "passage_changed")])
def test_old_negative_decisions_say_they_are_not_current(lib, decision, change, reason):
    model_decision(lib, decision="no_relation" if decision == "rejected" else decision, input_stale=decision == "rejected")
    if change == "scope":
        scope_edit(lib)
    elif change == "node":
        fill(lib)
    else:
        reextract(lib)
    detail = next(d for d in row(lib)["details"] if d["reason"] == decision)
    assert detail["current"] is False and reason in detail["stale_reasons"] and "passage_text" in detail["unchecked"]


def test_nodes_include_non_live_ends_with_live_false(lib):
    model_decision(lib)
    model_decision(lib, "c", "d", input_stale=True)
    selection_edit(lib, "a")
    selection_edit(lib, "c")
    value = read(lib)
    assert value["history"]["out_of_scope"] and value["not_accepted"]
    for key in ("a", "c"):
        node = value["nodes"][lib.ids[key]]
        assert not node["live"] and all(node[k] is None for k in ("position", "eligible", "access_level"))


def test_partial_success_keeps_the_failed_chunk_visible_though_its_row_is_placed(factory):
    lib = factory(n=11, mentions=(0, *range(2, 11)), only_target=True)
    lib.adapter.responder = lambda si: invalid(si) if len(si["lineage_target"]["candidates"]) == 8 else all_links(si)
    execute(lib, queue(lib))
    value = read(lib)
    assert links(value) and len(value["failed_pairs"]) == 8
    assert any(o["kind"] == "step_failed" for o in value["step_outcomes"])
    assert lib.ids["b"] not in {u["source_version_id"] for u in value["unplaceable"]}


def test_message_too_large_and_skipped_chunks_appear_in_step_outcomes(factory, monkeypatch):
    lib = factory()
    run = queue(lib)
    original = prompt.step_message
    monkeypatch.setattr(prompt, "step_message", lambda si: original(si) + "x" * 48_000)
    execute(lib, run)
    outcome = read(lib)["step_outcomes"][0]
    assert outcome["kind"] == "step_failed" and outcome["reason"] == "message_too_large" and outcome["current"] is True
    monkeypatch.setattr(prompt, "step_message", original)
    other = factory()
    run = queue(other)
    reextract(other, allow_run_id=run["id"])
    execute(other, run)
    value = read(other)
    assert [o["kind"] for o in value["step_outcomes"]] == ["skipped"]
    assert value["step_outcomes"][0]["current"] is None


def test_a_human_decision_closes_an_open_failure_but_the_run_record_is_kept(lib):
    lib.adapter.responder = invalid
    run = queue(lib)
    execute(lib, run)
    before = publication(lib, run)
    human_add(lib)
    assert read(lib)["step_outcomes"] == [] and publication(lib, run) == before


def test_an_unrelated_pair_assessment_does_not_close_a_chunk_failure(lib):
    lib.adapter.responder = invalid
    execute(lib, queue(lib))
    model_decision(lib, "c", "d", decision="no_relation")
    assert any(o["kind"] == "step_failed" for o in read(lib)["step_outcomes"])


@pytest.mark.parametrize("change,reason", [("node", "node_changed"), ("passage", "passage_changed")])
def test_unchecked_inputs_never_report_current_true(factory, change, reason):
    lib = factory(n=28, mentions=(0, *range(2, 28)), only_target=True)
    lib.adapter.responder = invalid
    execute(lib, queue(lib))
    if change == "node":
        fill(lib)
    else:
        reextract(lib)
    value = read(lib)
    assert any(o["current"] is False and reason in o["stale_reasons"] for o in value["failed_pairs"])
    assert all(o["current"] is None and o["unchecked"] == ["node_snapshots", "passages"] for o in value["not_sent_budget"])


def test_a_mention_only_change_does_not_change_stale_link_revisions(lib):
    mention = lib.store._insert_passage(lib.ids["b"], lib.assets[lib.ids["b"]], "pdf_page", 2, "2", "synthetic_fixture", None, "SYNTHETIC-v1", "SYNTHETIC extra mention")
    inputs = {"from": node_snapshot(build_node(lib.store, lib.tid, lib.ids["a"])),
              "to": node_snapshot(build_node(lib.store, lib.tid, lib.ids["b"])), "mention_passage_ids": [mention]}
    result = model_decision(lib, inputs=inputs)
    assert mention not in {e["passage_id"] for e in lib.lineage.evidence(result["revision_id"])}
    before = stale_link_revisions(lib.store, lib.tid)
    # Deliberate synthetic tamper after the snapshot, in this isolated test library.
    lib.conn.execute("DROP TRIGGER passages_no_update")
    lib.conn.execute("UPDATE passages SET extraction_version = 'SYNTHETIC-old' WHERE id = ?", (mention,))
    assert stale_link_revisions(lib.store, lib.tid) == before == {}


def test_scope_changed_failure_and_unsent_records_remain_visible_with_false_currency(factory):
    lib = factory(n=28, mentions=(0, *range(2, 28)), only_target=True)
    lib.adapter.responder = invalid
    execute(lib, queue(lib))
    scope_edit(lib)
    value = read(lib)
    assert value["failed_pairs"] and value["not_sent_budget"]
    for outcome in value["step_outcomes"]:
        assert outcome["current"] is False and "scope_changed" in outcome["stale_reasons"]
    assert all(o["unchecked"] == ["node_snapshots", "passages"] for o in value["not_sent_budget"])


def test_current_scan_runs_once_and_includes_human_pairs_without_scanning_unrecorded_targets(lib, monkeypatch):
    execute(lib, queue(lib))
    calls = []
    original = view_module.find_candidates
    def scan(works, targets, excluded_pairs):
        works, targets = tuple(works), tuple(targets)
        calls.append(({w.source_version_id for w in targets}, excluded_pairs))
        assert all(not w.passages for w in works if w.source_version_id not in calls[-1][0])
        return original(works, targets, excluded_pairs)
    monkeypatch.setattr(view_module, "find_candidates", scan)
    read(lib)
    assert len(calls) == 1 and calls[0][1] == frozenset()
    assert calls[0][0] == {lib.ids[k] for k in "bcdef"}


def test_link_year_warning_is_current_and_history_with_non_live_end_has_no_edge_state(lib):
    human_add(lib, "b", "a")
    value = read(lib)
    assert links(value)[0]["year_order_warning"] is True
    selection_edit(lib, "b")
    assert read(lib)["history"]["out_of_scope"][0]["edge_state"] is None


def test_combined_stale_reasons_and_non_live_ends_equal_the_old_stale_map(lib):
    result = model_decision(lib)
    fill(lib)
    scope_edit(lib)
    reextract(lib)
    selection_edit(lib)
    reasons = stale_link_reasons(lib.store, lib.tid)
    assert reasons == {result["link_id"]: (result["revision_id"], ("evidence_not_current", "scope_changed", "node_changed"))}
    assert stale_link_revisions(lib.store, lib.tid) == {result["link_id"]: result["revision_id"]}
    link = read(lib)["history"]["out_of_scope"][0]
    assert link["not_live_ends"] == ["from"] and len(link["stale_reasons"]) == 3


def test_pair_decisions_list_every_pair_with_its_version(lib):
    model_decision(lib, decision="no_relation")
    model_decision(lib, "c", "d", decision="insufficient_evidence")
    model_decision(lib, "e", "f", input_stale=True)
    lib.lineage.ensure_link(lib.tid, lib.ids["g"], lib.ids["h"])
    value = read(lib)
    assert len(value["pair_decisions"]) == 4
    # Pair order follows generated ids, so compare (version, decision) pairs without order.
    got = sorted(((p["version"], p["decision"] or "") for p in value["pair_decisions"]), reverse=True)
    assert got == [(1, "no_relation"), (1, "insufficient_evidence"), (0, ""), (0, "")]


def test_extraction_change_marks_a_link_stale_and_a_refreshed_revision_is_not_excluded_by_an_old_stale_map(lib):
    lib.adapter.responder = all_links
    execute(lib, queue(lib))
    old = links(read(lib))[0]
    reextract(lib)
    assert read(lib)["history"]["stale"]
    execute(lib, queue(lib))
    refreshed = links(read(lib))[0]
    assert refreshed["revision_id"] != old["revision_id"] and read(lib)["history"]["stale"] == []


def test_edge_state_counts_are_kept_apart_from_link_counts(lib):
    human_add(lib)
    value = read(lib)
    assert value["counts"]["current_links"] == 1
    assert sum(value["counts"]["edge_states"].values()) == len(lib.ids) * (len(lib.ids) - 1)


def test_baseline_uses_stored_counts_and_ranks_only_known_counts(lib):
    lib.conn.execute("UPDATE source_versions SET cited_by_count = 0, cited_by_count_at = 'SYNTHETIC-date' WHERE id = ?", (lib.ids["a"],))
    lib.conn.execute("UPDATE source_versions SET cited_by_count = 12, publication_type = 'review' WHERE id = ?", (lib.ids["b"],))
    value = field(lib)
    entries = value["most_cited_in_corpus"]["entries"]
    assert [e["source_version_id"] for e in entries] == [lib.ids["b"], lib.ids["a"]]
    assert entries[-1]["cited_by_count"] == 0 and entries[-1]["cited_by_count_at"] == "SYNTHETIC-date"
    assert value["review_in_corpus"]["entries"][0]["source_version_id"] == lib.ids["b"]


def test_unknown_count_is_not_zero_and_is_counted(lib):
    assert field(lib)["unknown_count_works"] == len(lib.ids)
    assert field(lib)["most_cited_in_corpus"]["entries"] == []


def test_baseline_counts_distinct_works_not_versions_and_excludes_the_target(lib):
    citation(lib, "a", "b")
    lib.conn.execute("UPDATE source_versions SET work_id = ? WHERE id = ?", (lib.store.source(lib.ids["b"])["work_id"], lib.ids["c"]))
    citation(lib, "a", "c")
    lib.conn.execute("UPDATE source_versions SET cited_by_count = 1 WHERE id = ?", (lib.ids["a"],))
    count = field(lib)["most_cited_in_corpus"]["entries"][0]["cited_by_included_works"]
    assert count == {"count": 1, "other_works": 6, "lists_read": 1, "target_resolved": True}


def test_baseline_representative_uses_membership_creation_time_not_version_creation_time(lib, monkeypatch):
    work = lib.store.source(lib.ids["a"])["work_id"]
    lib.conn.execute("UPDATE source_versions SET work_id = ?, created_at = '1900' WHERE id = ?", (work, lib.ids["b"]))
    lib.conn.execute("UPDATE source_versions SET created_at = '2000' WHERE id = ?", (lib.ids["a"],))
    lib.conn.execute("UPDATE corpus_memberships SET created_at = '2001' WHERE source_version_id = ?", (lib.ids["b"],))
    lib.conn.execute("UPDATE corpus_memberships SET created_at = '1999' WHERE source_version_id = ?", (lib.ids["a"],))
    # Equalize head and asset priority to isolate membership-time ordering.
    monkeypatch.setattr(lib.store, "work_heads", lambda rid: {})
    attach(lib, lib.ids["a"], "SYNTHETIC A")
    representative = next(r for r in field(lib)["representatives"] if r["work_id"] == work)
    assert representative["source_version_id"] == lib.ids["a"]
    assert representative["versions_considered"] == [lib.ids["a"], lib.ids["b"]]


def test_baseline_representative_is_shown_and_not_filled_from_another_version(lib, monkeypatch):
    work = lib.store.source(lib.ids["b"])["work_id"]
    lib.conn.execute("UPDATE source_versions SET work_id = ?, cited_by_count = 999, publication_type = 'review' WHERE id = ?", (work, lib.ids["a"]))
    heads = lib.store.work_heads(lib.rid)
    heads[work] = lib.ids["b"]
    monkeypatch.setattr(lib.store, "work_heads", lambda rid: heads)
    rep = next(r for r in field(lib)["representatives"] if r["work_id"] == work)
    assert rep["source_version_id"] == heads[work]
    source = lib.store.source(rep["source_version_id"])
    entries = field(lib)["most_cited_in_corpus"]["entries"]
    assert source["cited_by_count"] is None and work not in {e["work_id"] for e in entries}
    assert work not in {e["work_id"] for e in field(lib)["review_in_corpus"]["entries"]}


def test_review_note_says_registered_type_and_no_foundational_word(lib):
    note = field(lib)["review_in_corpus"]["note"]
    assert "Registered type: review" in note and "foundational" not in note


def test_included_citation_count_is_null_not_zero_without_read_lists(lib):
    lib.conn.execute("UPDATE source_versions SET cited_by_count = 1 WHERE id = ?", (lib.ids["a"],))
    entry = field(lib)["most_cited_in_corpus"]["entries"][0]
    assert entry["cited_by_included_works"]["count"] is None


def test_first_five_shown_and_all_returned(lib):
    lib.conn.execute("UPDATE source_versions SET cited_by_count = 1, publication_type = 'review'")
    value = field(lib)
    for key in ("most_cited_in_corpus", "review_in_corpus"):
        assert value[key]["total"] == 8 and len(value[key]["shown"]) == 5 and len(value[key]["entries"]) == 8
        assert value[key]["shown"] == value[key]["entries"][:5]


def test_baseline_makes_no_model_or_search_call(lib):
    field(lib)
    assert lib.adapter.calls == [] and lib.seen == []
