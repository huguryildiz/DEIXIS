"""L4 synthetic storage behavior, without providers, model calls or scientific validation."""

import json
import sqlite3
from types import SimpleNamespace

import pytest

from deixis.domain.rules import RevisionConflict
from deixis.storage import db
from deixis.workflow.lineage.run import build_node, node_snapshot, stale_link_reasons, stale_link_revisions
from deixis.workflow.lineage.store import InvalidLineageInput, LineageStore, REJECTION_CODES
from deixis.workflow.store import NotFound, Store
from deixis.workflow.tables import InvalidTableInput, TableStore

TEXT = "SYNTHETIC: The later work extends the earlier method with a bounded scheduling rule."
QUOTE = "extends the earlier method with a bounded scheduling rule"
LINEAGE_TABLES = ("lineage_links", "lineage_link_revisions", "lineage_link_evidence")


def make_library(path):
    conn = db.connect(path)
    db.migrate(conn)
    store = Store(conn)
    rid = store.create_research("SYNTHETIC question?", "attached", "quick", [], "fake", "fake-model", "en")
    ids, passages = {}, {}
    for letter in ("a", "b", "c", "d", "z", "x"):
        svid, work = f"srv_{letter}", f"wrk_{'a' if letter == 'x' else letter}"
        conn.execute("INSERT OR IGNORE INTO works (id, created_at) VALUES (?, 'now')", (work,))
        conn.execute("INSERT INTO source_versions (id, work_id, title, origin, created_at) VALUES (?, ?, ?, 'user_upload', 'now')",
                     (svid, work, f"SYNTHETIC source {letter}"))
        store.add_to_corpus(rid, svid, "user_upload", selection_state="included", selection_origin="user")
        ids[letter] = svid
        passages[letter] = store._insert_passage(svid, None, "abstract", None, None, "provider", None, None, TEXT)
    tables = TableStore(store)
    tid = tables.create_table(rid, "SYNTHETIC table", None, None, None)
    run = store.create_run(rid, "answer", {}, None)
    store.update_run(run["id"], status="completed")
    return SimpleNamespace(conn=conn, store=store, tables=tables, lineage=LineageStore(store), rid=rid, tid=tid,
                           ids=ids, passages=passages, run=run["id"])


@pytest.fixture
def lib(tmp_path):
    lib = make_library(tmp_path / "library.sqlite")
    yield lib
    lib.conn.close()


def state(lib):
    return {t: [tuple(r) for r in lib.conn.execute(
        f"SELECT * FROM {t} ORDER BY " + ("link_revision_id, passage_id, anchor_text" if t == "lineage_link_evidence" else "created_at, id")
    )] for t in LINEAGE_TABLES}


def decision(lib, to="b", value="link", **changes):
    result = dict(decision=value, relation="extends" if value == "link" else None,
                  what_changed="SYNTHETIC scheduling change" if value == "link" else None,
                  support_type="source_stated" if value == "link" else None,
                  evidence=[{"passage_id": lib.passages[to], "quote": QUOTE}] if value == "link" else [], note="SYNTHETIC note")
    return result | changes


def proposal(lib, a="a", b="b", **changes):
    step = lib.store.step(lib.run, db.new_id("op"), "model:lineage_links")
    sti = db.new_id("sti")
    lib.store.insert_step_input(step["id"], lib.rid, lib.run, 0,
                               {"step_input_id": sti, "task_type": "lineage_links", "scope_revision": 1,
                                "skill_package_hash": "sha256:SYNTHETIC"}, "base", "developer", "SYNTHETIC", {})
    pair = lib.lineage.link(lib.tid, lib.ids[a], lib.ids[b])
    return dict(research_id=lib.rid, table_id=lib.tid, from_svid=lib.ids[a], to_svid=lib.ids[b], decision=decision(lib, b),
                edge_state="not_read", run_id=lib.run, step_id=step["id"], step_input_id=sti, scope_revision=1,
                link_version_at_request=pair["version"] if pair else None, inputs={"from": ["opaque-cell-revision"], "to": []},
                input_fingerprint="SYNTHETIC-fingerprint", output_status="structurally_valid") | changes


def model(lib, a="a", b="b", **changes):
    return lib.lineage.apply_model_proposal(**proposal(lib, a, b, **changes))


def human(lib, a="a", b="b", **changes):
    pair = lib.lineage.link(lib.tid, lib.ids[a], lib.ids[b])
    values = dict(research_id=lib.rid, table_id=lib.tid, from_svid=lib.ids[a], to_svid=lib.ids[b], relation="extends",
                  what_changed="SYNTHETIC human change", support_type="analyst_inference",
                  evidence=[{"passage_id": lib.passages[b], "quote": QUOTE}], note="SYNTHETIC human note",
                  expected_version=pair["version"] if pair else 0, idempotency_key=None)
    return lib.lineage.add_link(**(values | changes))


def edit(lib, a="a", b="b", **changes):
    pair = lib.lineage.link(lib.tid, lib.ids[a], lib.ids[b])
    values = dict(research_id=lib.rid, table_id=lib.tid, link_id=pair["id"], relation="changes_method",
                  what_changed="SYNTHETIC edited change", support_type="source_stated",
                  evidence=[{"passage_id": lib.passages[b], "quote": QUOTE}], note=None,
                  based_on_revision_id=pair["current_revision_id"], expected_version=pair["version"], idempotency_key=None)
    return lib.lineage.edit_link(**(values | changes))


def remove(lib, a="a", b="b", **changes):
    pair = lib.lineage.link(lib.tid, lib.ids[a], lib.ids[b])
    values = dict(research_id=lib.rid, table_id=lib.tid, link_id=pair["id"], note="SYNTHETIC removed",
                  based_on_revision_id=pair["current_revision_id"], expected_version=pair["version"], idempotency_key=None)
    return lib.lineage.remove_link(**(values | changes))


def raw_revision(lib, pair=None, **changes):
    pair = pair or lib.lineage.ensure_link(lib.tid, lib.ids["a"], lib.ids["b"])
    p = proposal(lib)
    values = dict(kind="model_propose", author="model", decision="link", disposition="accepted", origin="mention",
                  relation="extends", what_changed="SYNTHETIC", support_type="source_stated",
                  step_input_id=p["step_input_id"], output_status="structurally_valid") | changes
    return lib.lineage._insert_revision(pair, **values)


def raw_evidence(lib, revision, letter="b", **changes):
    row = dict(link_revision_id=revision, passage_id=lib.passages[letter], source_version_id=lib.ids[letter],
               anchor_text=QUOTE, anchor_match="exact") | changes
    lib.conn.execute(f"INSERT INTO lineage_link_evidence ({', '.join(row)}) VALUES ({', '.join('?' * len(row))})", tuple(row.values()))


@pytest.mark.parametrize("changes", [
    {"relation": None}, {"decision": "no_relation"}, {"kind": "human_remove", "author": "human", "origin": "human"},
    {"step_input_id": None}, {"kind": "human_add", "author": "human"}, {"disposition": "rejected"},
    {"rejection_code": "cycle"}, {"kind": "human_add", "author": "human", "origin": "human", "disposition": "rejected", "rejection_code": "cycle"},
])
def test_checks_refuse_inconsistent_decisions(lib, changes):
    with pytest.raises(sqlite3.IntegrityError, match="CHECK"):
        raw_revision(lib, **changes)


def test_checks_refuse_identical_pair_endpoints(lib):
    with pytest.raises(sqlite3.IntegrityError, match="CHECK"):
        lib.conn.execute("INSERT INTO lineage_links (id, table_id, from_source_version_id, to_source_version_id, created_at, updated_at)"
                         " VALUES ('llk_bad', ?, ?, ?, 'now', 'now')", (lib.tid, lib.ids["a"], lib.ids["a"]))
    with pytest.raises(InvalidLineageInput):
        lib.lineage.ensure_link(lib.tid, lib.ids["a"], lib.ids["a"])


@pytest.mark.parametrize("authorization", ["research", "table"])
def test_append_only_triggers(lib, authorization):
    result = model(lib)
    for sql in ("UPDATE lineage_link_revisions SET note = 'changed'", "UPDATE lineage_link_evidence SET anchor_text = 'changed'",
                "DELETE FROM lineage_link_evidence", "DELETE FROM lineage_link_revisions"):
        with pytest.raises(sqlite3.IntegrityError, match="immutable"):
            lib.conn.execute(sql)
    lib.conn.execute(f"INSERT INTO {authorization}_purge_authorizations VALUES (?)", (lib.rid if authorization == "research" else lib.tid,))
    lib.conn.execute("UPDATE lineage_links SET current_revision_id = NULL")
    lib.conn.execute("DELETE FROM lineage_link_evidence")
    lib.conn.execute("DELETE FROM lineage_link_revisions")
    assert not lib.lineage.revisions(result["link_id"])


@pytest.mark.parametrize("insert", ["INSERT OR REPLACE INTO", "REPLACE INTO", "INSERT OR IGNORE INTO"])
@pytest.mark.parametrize("case", ["revision", "revision_key", "evidence", "link_id", "link_pair"])
def test_conflicting_inserts_cannot_replace_lineage_history(lib, insert, case):
    model(lib, idempotency_key="SYNTHETIC key", output_status="unverified_draft" if case == "revision_key" else "structurally_valid")
    assert lib.conn.execute("PRAGMA recursive_triggers").fetchone()[0] == 0
    table = {"revision": "lineage_link_revisions", "revision_key": "lineage_link_revisions",
             "evidence": "lineage_link_evidence"}.get(case, "lineage_links")
    row = dict(lib.conn.execute(f"SELECT * FROM {table}").fetchone())
    if case.startswith("revision"):
        row["note"] = "SYNTHETIC replacement"
        if case == "revision_key":
            row["id"] = "llr_duplicate_key"
    elif case == "evidence":
        row["anchor_match"] = "normalized"
    else:
        # A NULL insert pointer satisfies the first-insert guard, so only the collision guard can refuse it.
        row["current_revision_id"] = None
        if case == "link_id":
            row["to_source_version_id"] = lib.ids["d"]
        else:
            row["id"] = "llk_duplicate_pair"
    before = state(lib)
    with pytest.raises(sqlite3.IntegrityError, match="already exists"):
        lib.conn.execute(f"{insert} {table} ({', '.join(row)}) VALUES ({', '.join('?' * len(row))})", tuple(row.values()))
    assert state(lib) == before


@pytest.mark.parametrize("insert", ["INSERT OR REPLACE INTO", "REPLACE INTO"])
@pytest.mark.parametrize("table", LINEAGE_TABLES)
@pytest.mark.parametrize("rowid", ["rowid", "_rowid_", "oid"])
def test_hidden_row_identity_is_not_addressable_for_replacement(lib, insert, table, rowid):
    model(lib, idempotency_key="SYNTHETIC key")
    assert lib.conn.execute("PRAGMA recursive_triggers").fetchone()[0] == 0
    row = dict(lib.conn.execute(f"SELECT * FROM {table}").fetchone())
    if table == "lineage_links":
        row.update(id="llk_replacement", from_source_version_id=lib.ids["c"],
                   to_source_version_id=lib.ids["d"], current_revision_id=None)
    elif table == "lineage_link_revisions":
        row.update(id="llr_replacement", idempotency_key=None, note="SYNTHETIC replacement")
    else:
        row["anchor_text"] = "SYNTHETIC replacement anchor"
    row[rowid] = 1
    before = state(lib)
    with pytest.raises(sqlite3.OperationalError, match=f"no column named {rowid}"):
        lib.conn.execute(f"{insert} {table} ({', '.join(row)}) VALUES ({', '.join('?' * len(row))})", tuple(row.values()))
    assert state(lib) == before
    assert lib.conn.execute("PRAGMA foreign_key_check").fetchall() == []


def test_upsert_cannot_rewrite_a_lineage_revision(lib):
    model(lib)
    row = dict(lib.conn.execute("SELECT * FROM lineage_link_revisions").fetchone())
    row["note"] = "SYNTHETIC replacement"
    before = state(lib)
    with pytest.raises(sqlite3.IntegrityError, match="already exists"):
        lib.conn.execute(
            f"INSERT INTO lineage_link_revisions ({', '.join(row)}) VALUES ({', '.join('?' * len(row))})"
            " ON CONFLICT(id) DO UPDATE SET note = excluded.note", tuple(row.values()),
        )
    assert state(lib) == before


def test_ensure_link_returns_the_existing_pair_without_inserting(lib):
    pair = lib.lineage.ensure_link(lib.tid, lib.ids["a"], lib.ids["b"])
    before = state(lib)
    assert lib.lineage.ensure_link(lib.tid, lib.ids["a"], lib.ids["b"]) == pair
    assert state(lib) == before


def test_revision_reads_and_step_replay_keep_insertion_order_within_one_millisecond(lib, monkeypatch):
    pair = lib.lineage.ensure_link(lib.tid, lib.ids["a"], lib.ids["b"])
    p = proposal(lib)
    ids = iter(("llr_z", "llr_y", "llr_a"))  # random ids must not decide the order of writes made in one millisecond
    monkeypatch.setattr("deixis.workflow.lineage.store.new_id", lambda prefix: next(ids))
    for timestamp in ("2026-10-01T00:00:00.000+00:00",) * 3:
        monkeypatch.setattr("deixis.workflow.lineage.store.now", lambda: timestamp)
        lib.lineage._insert_revision(pair, kind="model_propose", author="model", decision="no_relation",
                                     disposition="accepted", origin="mention", step_input_id=p["step_input_id"],
                                     output_status="structurally_valid")
    assert [r["id"] for r in lib.lineage.revisions(pair["id"])] == ["llr_z", "llr_y", "llr_a"]
    assert lib.lineage._replay(pair, None, p["step_input_id"])["id"] == "llr_z"


def test_active_link_reads_use_oldest_time_then_primary_key(lib, monkeypatch):
    ids = iter(("llk_z", "llr_z", "llk_y", "llr_y", "llk_a", "llr_a"))
    monkeypatch.setattr("deixis.workflow.lineage.store.new_id", lambda prefix: next(ids))
    for (a, b), timestamp in zip((("a", "b"), ("a", "c"), ("a", "d")),
                                 ("2026-10-02T00:00:00+00:00", "2026-10-01T00:00:00+00:00", "2026-10-01T00:00:00+00:00")):
        monkeypatch.setattr("deixis.workflow.lineage.store.now", lambda: timestamp)
        human(lib, a, b)
    assert [r["id"] for r in lib.lineage.active_links(lib.tid)] == ["llk_a", "llk_y", "llk_z"]


def test_evidence_reads_use_stable_anchor_and_passage_order(lib):
    revision = raw_revision(lib)
    other_passage = lib.store._insert_passage(lib.ids["b"], None, "abstract", None, None, "provider", None, None,
                                              TEXT + " SYNTHETIC second passage.")
    for passage, anchor in ((other_passage, "earlier method"), (lib.passages["b"], "bounded scheduling rule"),
                            (lib.passages["b"], "earlier method")):
        raw_evidence(lib, revision, passage_id=passage, anchor_text=anchor)
    assert [(r["anchor_text"], r["passage_id"]) for r in lib.lineage.evidence(revision)] == [
        ("bounded scheduling rule", lib.passages["b"]),
        *(sorted(("earlier method", passage) for passage in (lib.passages["b"], other_passage))),
    ]


@pytest.mark.parametrize("letter", ["a", "c"])
def test_evidence_must_come_from_the_later_work(lib, letter):
    revision = raw_revision(lib)
    with pytest.raises(sqlite3.IntegrityError, match="later work"):
        raw_evidence(lib, revision, letter)
    with pytest.raises(sqlite3.IntegrityError, match="later work"):
        raw_evidence(lib, revision, source_version_id=lib.ids["c"])


@pytest.mark.parametrize("case", ["other_pair", "rejected", "draft", "no_evidence"])
def test_pointer_guard(lib, case):
    pair = lib.lineage.ensure_link(lib.tid, lib.ids["a"], lib.ids["b"])
    other = lib.lineage.ensure_link(lib.tid, lib.ids["c"], lib.ids["b"])
    changes = {"disposition": "rejected", "rejection_code": "cycle"} if case == "rejected" else {}
    if case == "draft":
        changes["output_status"] = "unverified_draft"
    revision = raw_revision(lib, other if case == "other_pair" else pair, **changes)
    if case != "no_evidence":
        raw_evidence(lib, revision)
    with pytest.raises(sqlite3.IntegrityError, match="publishable"):
        lib.conn.execute("UPDATE lineage_links SET current_revision_id = ? WHERE id = ?", (revision, pair["id"]))
    lib.conn.execute("UPDATE lineage_links SET current_revision_id = NULL WHERE id = ?", (pair["id"],))


def test_pointer_insert_and_identity_guards(lib):
    result = model(lib)
    with pytest.raises(sqlite3.IntegrityError, match="starts without"):
        lib.conn.execute("INSERT INTO lineage_links (id, table_id, from_source_version_id, to_source_version_id, current_revision_id, created_at, updated_at)"
                         " VALUES ('llk_insert', ?, ?, ?, ?, 'now', 'now')", (lib.tid, lib.ids["c"], lib.ids["b"], result["revision_id"]))
    for field, value in (("from_source_version_id", lib.ids["c"]), ("to_source_version_id", lib.ids["d"]), ("table_id", "missing")):
        with pytest.raises(sqlite3.IntegrityError, match="identity"):
            lib.conn.execute(f"UPDATE lineage_links SET {field} = ? WHERE id = ?", (value, result["link_id"]))


@pytest.mark.parametrize("value", ["link", "no_relation", "insufficient_evidence"])
def test_first_accepted_model_decision_fills_the_empty_pointer(lib, value):
    result = model(lib, decision=decision(lib, value=value))
    pair = lib.lineage.link_by_id(result["link_id"])
    assert result["current"] and result["disposition"] == "accepted" and pair["version"] == 1
    assert pair["current_revision_id"] == result["revision_id"]
    assert len(lib.lineage.active_links(lib.tid)) == (value == "link")
    assert [e["type"] for e in lib.store.events_after(lib.rid, 0)].count("lineage_changed") == 1
    revision = lib.lineage.revisions(pair["id"])[0]
    assert json.loads(revision["inputs_json"]) == {"fingerprint": "SYNTHETIC-fingerprint", "inputs": {"from": ["opaque-cell-revision"], "to": []}}


@pytest.mark.parametrize("value", ["no_relation", "insufficient_evidence"])
def test_link_then_no_relation_moves_the_pointer_and_drops_the_edge(lib, value):
    model(lib)
    result = model(lib, decision=decision(lib, value=value), input_fingerprint="changed")
    assert result["current"] and not lib.lineage.active_links(lib.tid)
    assert lib.lineage.link_by_id(result["link_id"])["version"] == 2


def test_accepted_model_revision_with_unchanged_fingerprint_is_recorded_but_not_current(lib):
    first = model(lib)
    result = model(lib)
    assert result["disposition"] == "accepted" and not result["current"]
    assert lib.lineage.link_by_id(first["link_id"])["version"] == 1
    assert len(lib.lineage.revisions(first["link_id"])) == 2
    assert len([e for e in lib.store.events_after(lib.rid, 0) if e["type"] == "lineage_changed"]) == 1


def test_changed_fingerprint_replaces_a_model_current(lib):
    first = model(lib)
    second = model(lib, input_fingerprint="changed")
    assert second["current"] and second["revision_id"] != first["revision_id"]


@pytest.mark.parametrize("existing", [False, True])
def test_unverified_draft_is_never_current(lib, existing):
    if existing:
        model(lib)
    before = lib.lineage.link(lib.tid, lib.ids["a"], lib.ids["b"])
    result = model(lib, output_status="unverified_draft", input_fingerprint="changed")
    assert result["disposition"] == "accepted" and not result["current"]
    assert lib.lineage.link_by_id(result["link_id"])["version"] == (before["version"] if before else 0)
    assert lib.lineage.evidence(result["revision_id"])


@pytest.mark.parametrize("code", ["same_work", "endpoint_not_included", "superseded_by_human", "stale_scope", "stale_version", "anchor_not_found", "cycle"])
@pytest.mark.parametrize("existing", [False, True])
def test_rejected_proposal_keeps_pointer_version_and_old_link(lib, code, existing):
    a, b = ("a", "x") if code == "same_work" else ("a", "b")
    if existing:
        if code == "same_work":
            pair = lib.lineage.ensure_link(lib.tid, lib.ids[a], lib.ids[b])
            rev = raw_revision(lib, pair)
            raw_evidence(lib, rev, "x")
            lib.conn.execute("UPDATE lineage_links SET current_revision_id = ?, version = 1 WHERE id = ?", (rev, pair["id"]))
        else:
            model(lib)
    changes = {}
    if code == "endpoint_not_included":
        lib.conn.execute("UPDATE selections SET state = 'excluded' WHERE source_version_id = ?", (lib.ids[b],))
    elif code == "superseded_by_human":
        if existing:
            edit(lib)
        else:
            human(lib)
    elif code == "stale_scope":
        changes["scope_revision"] = 0
    elif code == "stale_version":
        changes["link_version_at_request"] = 999
    elif code == "anchor_not_found":
        changes["decision"] = decision(lib, b, evidence=[{"passage_id": lib.passages[b], "quote": "ZZZZZZ nonexistent quote"}])
    elif code == "cycle":
        human(lib, "b", "a", relation="independent_parallel", support_type="source_stated")
        # Convert this separate cross-relation into a directed link with a named stale a->b when needed.
        old = lib.lineage.link(lib.tid, lib.ids[a], lib.ids[b])
        stale = {old["id"]: old["current_revision_id"]} if old else {}
        edit(lib, "b", "a", relation="extends", stale_revisions=stale)
    before = lib.lineage.link(lib.tid, lib.ids[a], lib.ids[b])
    result = model(lib, a, b, input_fingerprint="changed", **changes)
    after = lib.lineage.link_by_id(result["link_id"])
    expected = "stale_input" if code.startswith("stale_") else code
    assert expected in REJECTION_CODES and result["rejection_code"] == expected and result["disposition"] == "rejected"
    assert after["current_revision_id"] == (before["current_revision_id"] if before else None)
    assert after["version"] == (before["version"] if before else 0)
    revision = next(r for r in lib.lineage.revisions(after["id"]) if r["id"] == result["revision_id"])
    for field in ("decision", "relation", "what_changed", "support_type", "note"):
        assert revision[field] == changes.get("decision", decision(lib, b))[field]
    assert revision["origin"] == "mention" and not lib.lineage.evidence(result["revision_id"])


@pytest.mark.parametrize("case,expected", [("same_work_and_endpoint", "same_work"), ("endpoint_and_human", "endpoint_not_included"),
                                          ("human_and_stale", "superseded_by_human"), ("stale_and_anchor", "stale_input"),
                                          ("anchor_and_cycle", "anchor_not_found")])
def test_first_failing_rule_has_the_fixed_order(lib, case, expected):
    if case == "same_work_and_endpoint":
        lib.conn.execute("UPDATE selections SET state = 'excluded' WHERE source_version_id = ?", (lib.ids["x"],))
        result = model(lib, "a", "x")
    else:
        if "human" in case:
            human(lib)
        if case == "endpoint_and_human":
            lib.conn.execute("UPDATE table_rows SET removed_at = 'now' WHERE source_version_id = ?", (lib.ids["b"],))
        if case == "anchor_and_cycle":
            human(lib, "b", "a")
        result = model(lib, scope_revision=0 if "stale" in case else 1,
                       decision=decision(lib, evidence=[{"passage_id": lib.passages["b"], "quote": "ZZZZZZ"}]))
    assert result["rejection_code"] == expected


@pytest.mark.parametrize("quote,kind", [(QUOTE, "exact"), (QUOTE.upper().replace(" ", "-"), "normalized"),
                                       (QUOTE.replace("earlier", "earlierx"), "fuzzy")])
def test_stored_anchor_is_the_located_source_text_not_the_raw_quote(lib, quote, kind):
    result = model(lib, decision=decision(lib, evidence=[{"passage_id": lib.passages["b"], "quote": quote}]))
    assert result["current"]
    evidence = lib.lineage.evidence(result["revision_id"])[0]
    assert evidence["anchor_text"] == QUOTE and evidence["anchor_match"] == kind


def test_same_located_text_twice_is_stored_once(lib):
    result = model(lib, decision=decision(lib, evidence=[{"passage_id": lib.passages["b"], "quote": q} for q in (QUOTE, QUOTE.upper())]))
    assert len(lib.lineage.evidence(result["revision_id"])) == 1


def test_diamond_is_valid_and_directed_cycle_is_rejected(lib):
    for a, b in (("a", "b"), ("a", "c"), ("b", "d"), ("c", "d")):
        assert model(lib, a, b)["current"]
    assert len(lib.lineage.active_links(lib.tid)) == 4
    assert model(lib, "d", "a")["rejection_code"] == "cycle"


def test_independent_parallel_adds_no_edge_and_is_not_cycle_checked(lib):
    model(lib)
    result = model(lib, "b", "a", decision=decision(lib, "a", relation="independent_parallel"))
    assert result["current"]
    assert model(lib, "a", "c")["current"] and model(lib, "c", "b")["current"]
    assert len(lib.lineage.active_links(lib.tid)) == 4  # unfiltered read includes the cross-relation


def test_replacing_a_link_removes_its_own_old_edge_for_the_cycle_check(lib):
    model(lib)
    assert model(lib, input_fingerprint="changed")["current"]
    assert edit(lib)


@pytest.mark.parametrize("order", [(0, 1, 2), (2, 0, 1), (1, 2, 0)])
def test_batch_applies_in_fixed_order_whatever_the_input_order(lib, order, monkeypatch):
    # Distinct stored times let this assertion observe application order independently of random ids.
    timestamps = iter(f"2026-10-01T00:00:00.{n:03d}+00:00" for n in range(20))
    monkeypatch.setattr("deixis.workflow.lineage.store.now", lambda: next(timestamps))
    proposals = [proposal(lib, a, b) for a, b in (("c", "d"), ("a", "b"), ("a", "d"))]
    results = lib.lineage.apply_model_proposals([proposals[i] for i in order])
    pairs = [lib.lineage.link_by_id(r["link_id"]) for r in results]
    expected = [("srv_b", "srv_a"), ("srv_d", "srv_a"), ("srv_d", "srv_c")]
    assert [(p["to_source_version_id"], p["from_source_version_id"]) for p in pairs] == expected
    assert [r[0] for r in lib.conn.execute("SELECT link_id FROM lineage_link_revisions ORDER BY created_at, id")] == [r["link_id"] for r in results]


def test_batch_catches_a_cycle_closed_by_two_proposals(lib):
    results = lib.lineage.apply_model_proposals([proposal(lib, "a", "b"), proposal(lib, "b", "a")])
    assert results[0]["current"] and results[1]["rejection_code"] == "cycle"


def test_batch_is_atomic(lib):
    proposals = [proposal(lib), proposal(lib, "c", "d", decision=decision(lib, "d", evidence=[]))]
    before, events = state(lib), lib.store.events_after(lib.rid, 0)
    with pytest.raises(InvalidLineageInput):
        lib.lineage.apply_model_proposals(proposals)
    assert state(lib) == before and lib.store.events_after(lib.rid, 0) == events


def test_batch_rolls_back_when_an_outer_transaction_catches_the_error(lib):
    proposals = [proposal(lib), proposal(lib, "c", "d", decision=decision(lib, "d", evidence=[]))]
    before, events = state(lib), lib.store.events_after(lib.rid, 0)
    table = lib.tables._table(lib.rid, lib.tid)
    with db.transaction(lib.conn):
        lib.conn.execute("UPDATE evidence_tables SET title = 'SYNTHETIC outer edit' WHERE id = ?", (lib.tid,))
        with pytest.raises(InvalidLineageInput):
            lib.lineage.apply_model_proposals(proposals)
        assert lib.conn.in_transaction
    assert state(lib) == before
    assert lib.store.events_after(lib.rid, 0) == events
    assert lib.tables._table(lib.rid, lib.tid) == table | {"title": "SYNTHETIC outer edit"}
    assert not lib.conn.in_transaction


def test_single_proposal_rolls_back_a_late_error_inside_an_outer_transaction(lib, monkeypatch):
    p = proposal(lib)
    before, events = state(lib), lib.store.events_after(lib.rid, 0)
    table = lib.tables._table(lib.rid, lib.tid)
    record_event = lib.store._event

    def fail_after_event(*args, **kwargs):
        record_event(*args, **kwargs)
        raise InvalidLineageInput("SYNTHETIC failure after publication")

    monkeypatch.setattr(lib.store, "_event", fail_after_event)
    with db.transaction(lib.conn):
        with pytest.raises(InvalidLineageInput, match="after publication"):
            lib.lineage.apply_model_proposal(**p)
        assert lib.conn.in_transaction
    assert state(lib) == before
    assert lib.store.events_after(lib.rid, 0) == events
    assert lib.tables._table(lib.rid, lib.tid) == table


@pytest.mark.parametrize("batch", [False, True])
def test_successful_proposals_do_not_commit_the_outer_transaction(lib, batch):
    p = proposal(lib)
    before, events = state(lib), lib.store.events_after(lib.rid, 0)
    with pytest.raises(RuntimeError, match="outer rollback"):
        with db.transaction(lib.conn):
            result = lib.lineage.apply_model_proposals([p])[0] if batch else lib.lineage.apply_model_proposal(**p)
            assert result["current"] and lib.conn.in_transaction
            raise RuntimeError("SYNTHETIC outer rollback")
    assert state(lib) == before
    assert lib.store.events_after(lib.rid, 0) == events


@pytest.mark.parametrize("by_step", [False, True])
def test_replay_does_not_add_a_second_revision(lib, by_step):
    p = proposal(lib, idempotency_key="key")
    first = lib.lineage.apply_model_proposal(**p)
    replay = p if by_step else proposal(lib, idempotency_key="key", scope_revision=99)
    if by_step:
        replay = replay | {"idempotency_key": None}
    assert lib.lineage.apply_model_proposal(**replay) == first
    assert len(lib.lineage.revisions(first["link_id"])) == 1


def test_accepted_model_draft_never_becomes_current_by_itself(lib):
    pair = lib.lineage.ensure_link(lib.tid, lib.ids["a"], lib.ids["b"])
    revision = raw_revision(lib, pair)
    raw_evidence(lib, revision)
    assert lib.lineage.link_by_id(pair["id"])["current_revision_id"] is None
    assert lib.lineage.link_by_id(pair["id"])["version"] == 0


@pytest.mark.parametrize("evidence", [[], [{"passage_id": "from", "quote": QUOTE}], [{"passage_id": "later", "quote": "ZZZZZZ"}]])
def test_human_add_needs_a_placed_quote_from_the_later_work(lib, evidence):
    evidence = [{**e, "passage_id": lib.passages["a" if e["passage_id"] == "from" else "b"]} for e in evidence]
    with pytest.raises(InvalidLineageInput):
        human(lib, evidence=evidence)
    assert not lib.lineage.link(lib.tid, lib.ids["a"], lib.ids["b"])


@pytest.mark.parametrize("previous", ["none", "no_relation", "insufficient_evidence", "removed"])
def test_human_add_over_none_no_relation_and_removed(lib, previous):
    if previous == "removed":
        human(lib)
        remove(lib)
    elif previous != "none":
        model(lib, decision=decision(lib, value=previous))
    revision = human(lib)
    pair = lib.lineage.link(lib.tid, lib.ids["a"], lib.ids["b"])
    assert pair["current_revision_id"] == revision and lib.lineage.active_links(lib.tid)


def test_human_add_refused_over_an_active_link(lib):
    model(lib)
    with pytest.raises(RevisionConflict, match="use edit"):
        human(lib)


@pytest.mark.parametrize("action", [edit, remove])
@pytest.mark.parametrize("changes", [{"expected_version": 0}, {"based_on_revision_id": "wrong"}])
def test_human_edit_and_remove_use_expected_version_and_based_on(lib, action, changes):
    model(lib)
    before = state(lib)
    with pytest.raises(RevisionConflict):
        action(lib, **changes)
    assert state(lib) == before
    revision = action(lib)
    assert lib.lineage.link(lib.tid, lib.ids["a"], lib.ids["b"])["current_revision_id"] == revision
    row = next(r for r in lib.lineage.revisions(lib.lineage.link(lib.tid, lib.ids["a"], lib.ids["b"])["id"]) if r["id"] == revision)
    assert row["author"] == row["origin"] == "human" and row["output_status"] is None
    assert row["step_id"] is None and row["step_input_id"] is None and row["run_id"] is None


@pytest.mark.parametrize("action", [edit, remove])
def test_human_decision_survives_a_later_model_run(lib, action):
    model(lib)
    revision = action(lib)
    result = model(lib, input_fingerprint="changed")
    assert result["rejection_code"] == "superseded_by_human"
    assert lib.lineage.link_by_id(result["link_id"])["current_revision_id"] == revision
    assert bool(lib.lineage.active_links(lib.tid)) == (action == edit)


def test_human_cycle_is_refused(lib):
    human(lib)
    with pytest.raises(InvalidLineageInput, match="cycle"):
        human(lib, "b", "a")


def test_human_decided_pairs_is_the_exclusion_set(lib):
    from deixis.workflow.lineage.candidates import find_candidates, LineageWork
    from deixis.workflow.lineage.mentions import PassageText

    human(lib)
    human(lib, "c", "d")
    remove(lib, "c", "d")
    model(lib, "a", "z")
    excluded = lib.lineage.human_decided_pairs(lib.tid)
    assert excluded == {(lib.ids["a"], lib.ids["b"]), (lib.ids["c"], lib.ids["d"])}
    # The existing L2 parameter consumes version-pair identities, including human removals.
    sources = [LineageWork(lib.ids[k], f"wrk_{k}", i, f"SYNTHETIC {k}", ("Smith",) if k == "a" else (),
                           2020, (), False, frozenset(), frozenset(),
                           (PassageText(lib.passages["b"], "pdf_page", "SYNTHETIC Smith 2020 extends a method.", 1),) if k == "b" else ())
               for i, k in enumerate(("a", "b"))]
    assert len(find_candidates(sources).candidates) == 1 and not find_candidates(sources, excluded_pairs=excluded).candidates


def test_human_write_replay_and_foreign_key_reuse(lib):
    revision = human(lib, idempotency_key="human-key")
    assert human(lib, idempotency_key="human-key", expected_version=0) == revision
    with pytest.raises(InvalidLineageInput, match="another pair"):
        human(lib, "c", "d", idempotency_key="human-key")
    edited = edit(lib, idempotency_key="edit-key")
    assert edit(lib, idempotency_key="edit-key", expected_version=0, based_on_revision_id="wrong") == edited
    removed = remove(lib, idempotency_key="remove-key")
    assert remove(lib, idempotency_key="remove-key", expected_version=0, based_on_revision_id="wrong") == removed


@pytest.mark.parametrize("changes", [{"what_changed": ""}, {"what_changed": " "}, {"what_changed": "   "},
                                      {"what_changed": "\t"}, {"what_changed": "\n"}, {"what_changed": "x" * 501},
                                      {"relation": "invented"}, {"support_type": "invented"}])
def test_what_changed_length_and_vocabularies(lib, changes):
    with pytest.raises(InvalidLineageInput):
        human(lib, **changes)
    assert human(lib, what_changed="x" * 500)


def restore_scenario(lib, *, ordinary=False):
    lib.tables.add_development_columns(lib.rid, lib.tid, lib.tables._table(lib.rid, lib.tid)["version"], None)
    if ordinary:
        cid = lib.tables.add_column(lib.rid, lib.tid, dict(name="SYNTHETIC ordinary", instruction="Record the method.",
            answer_format="text", options=None, allow_multiple=False, unit_hint=None),
            lib.tables._table(lib.rid, lib.tid)["version"], None)
        column = lib.tables._column(lib.tid, cid)
    else:
        column = lib.tables._columns(lib.tid)[0]
    inputs = {"from": node_snapshot(build_node(lib.store, lib.tid, lib.ids["a"])),
              "to": node_snapshot(build_node(lib.store, lib.tid, lib.ids["b"])),
              "mention_passage_ids": [lib.passages["b"]]}
    result = model(lib, inputs=inputs)
    assert result["current"] and result["disposition"] == "accepted"
    assert stale_link_revisions(lib.store, lib.tid) == {}
    lib.tables.remove_column(lib.rid, lib.tid, column["id"], column["version"])
    if not ordinary:
        assert stale_link_reasons(lib.store, lib.tid)[result["link_id"]] == (result["revision_id"], ("node_changed",))
    return column, result


def restore_state(lib):
    return state(lib) | {t: [tuple(r) for r in lib.conn.execute(f"SELECT * FROM {t} ORDER BY rowid")]
                        for t in ("table_columns", "column_revisions", "evidence_tables", "events")}


def graph_has_cycle(lib, stale_revisions):
    revisions = {edge["id"]: edge["revision_id"] for edge in lib.lineage.active_links(lib.tid)}
    return lib.lineage.reactivation_closes_cycle(lib.tid, revisions, stale_revisions)


def preexisting_human_cycle(lib, a="a", b="b", c="c"):
    human(lib, a, b)
    human(lib, b, c)
    excluded = lib.store.set_user_selection(lib.rid, lib.ids[b], "excluded", 1, "SYNTHETIC exclusion")
    human(lib, c, a)
    lib.store.set_user_selection(lib.rid, lib.ids[b], "included", excluded["version"], "SYNTHETIC re-inclusion")
    assert stale_link_revisions(lib.store, lib.tid) == {}
    assert graph_has_cycle(lib, {})


@pytest.mark.parametrize("case, expected", [
    ("reactivated", True), ("not_stale_before", False), ("different_before_revision", False),
    ("still_stale", False), ("unrelated_edge", False),
])
def test_reactivation_cycle_check_requires_the_named_revision_on_a_cycle(lib, case, expected):
    preexisting_human_cycle(lib)
    human(lib, "d", "z")
    a, b = ("d", "z") if case == "unrelated_edge" else ("a", "b")
    edge = lib.lineage.link(lib.tid, lib.ids[a], lib.ids[b])
    before = {edge["id"]: edge["current_revision_id"]}
    after = {}
    if case == "not_stale_before":
        before = {}
    elif case == "different_before_revision":
        before[edge["id"]] = "different-revision"
    elif case == "still_stale":
        after = before.copy()

    assert lib.lineage.reactivation_closes_cycle(lib.tid, before, after) is expected


def test_restore_succeeds_with_preexisting_cycle_unrelated_to_column(lib):
    lib.tables.add_development_columns(lib.rid, lib.tid, lib.tables._table(lib.rid, lib.tid)["version"], None)
    preexisting_human_cycle(lib)
    column = lib.tables._columns(lib.tid)[0]
    lib.tables.remove_column(lib.rid, lib.tid, column["id"], column["version"])
    history = state(lib)
    events = lib.conn.execute("SELECT COUNT(*) FROM events WHERE type = 'column_restored'").fetchone()[0]

    lib.tables.restore_column(lib.rid, lib.tid, column["id"], column["version"] + 1)

    assert lib.tables._column(lib.tid, column["id"])["removed_at"] is None
    assert state(lib) == history
    assert lib.conn.execute("SELECT COUNT(*) FROM events WHERE type = 'column_restored'").fetchone()[0] == events + 1
    assert graph_has_cycle(lib, {})


def test_restore_refuses_reactivated_cycle_despite_unrelated_preexisting_cycle(lib):
    lib.tables.add_development_columns(lib.rid, lib.tid, lib.tables._table(lib.rid, lib.tid)["version"], None)
    preexisting_human_cycle(lib, "c", "d", "z")
    column, accepted = restore_scenario(lib)
    stale = stale_link_revisions(lib.store, lib.tid)
    human(lib, "b", "a", stale_revisions=stale)
    assert graph_has_cycle(lib, stale)
    before = restore_state(lib)

    with pytest.raises(InvalidTableInput, match="re-activate.*cycle.*remove or edit"):
        lib.tables.restore_column(lib.rid, lib.tid, column["id"], column["version"] + 1)

    assert restore_state(lib) == before
    assert stale_link_revisions(lib.store, lib.tid) == stale
    assert lib.lineage.link_by_id(accepted["link_id"])["current_revision_id"] == accepted["revision_id"]
    remove(lib, "b", "a")
    lib.tables.restore_column(lib.rid, lib.tid, column["id"], column["version"] + 1)
    assert lib.tables._column(lib.tid, column["id"])["removed_at"] is None
    assert graph_has_cycle(lib, {})


@pytest.mark.parametrize("three_nodes", [False, True], ids=["two-node-cycle", "three-node-cycle"])
def test_restore_refuses_reactivated_cycle_and_preserves_every_record(lib, three_nodes):
    column, accepted = restore_scenario(lib)
    stale = stale_link_revisions(lib.store, lib.tid)
    if three_nodes:
        human(lib, "b", "c", stale_revisions=stale)
        human(lib, "c", "a", stale_revisions=stale)
        closing = ("c", "a")
    else:
        human(lib, "b", "a", stale_revisions=stale)
        closing = ("b", "a")
    before = restore_state(lib)
    with pytest.raises(InvalidTableInput, match="re-activate.*cycle.*remove or edit"):
        lib.tables.restore_column(lib.rid, lib.tid, column["id"], column["version"] + 1)
    assert restore_state(lib) == before  # Includes column version, table timestamp, events and lineage history.
    assert next(c for c in lib.tables._columns(lib.tid, include_removed=True)
                if c["id"] == column["id"])["removed_at"] is not None
    assert lib.lineage.link_by_id(accepted["link_id"])["current_revision_id"] == accepted["revision_id"]
    assert lib.lineage.revisions(accepted["link_id"])[0]["disposition"] == "accepted"
    assert not graph_has_cycle(lib, stale_link_revisions(lib.store, lib.tid))
    remove(lib, *closing)
    lib.tables.restore_column(lib.rid, lib.tid, column["id"], column["version"] + 1)
    assert lib.tables._column(lib.tid, column["id"])["removed_at"] is None
    assert stale_link_revisions(lib.store, lib.tid) == {}
    assert not graph_has_cycle(lib, {})


@pytest.mark.parametrize("case", ["path", "diamond", "ordinary", "independent_parallel", "non_live",
                                   "scope_changed", "evidence_not_current"])
def test_restore_succeeds_when_filtered_graph_has_no_cycle(lib, case, monkeypatch):
    if case == "evidence_not_current":
        from test_lineage_plan import attach
        asset = attach(lib, lib.ids["b"], TEXT)
        lib.passages["b"] = next(p["id"] for p in lib.store.passages_for(lib.ids["b"]) if p["asset_id"] == asset)
    column, accepted = restore_scenario(lib, ordinary=case == "ordinary")
    stale = stale_link_revisions(lib.store, lib.tid)
    if case == "diamond":
        for a, b in (("a", "c"), ("b", "d"), ("c", "d")):
            human(lib, a, b, stale_revisions=stale)
    elif case in ("path", "ordinary"):
        human(lib, "b", "c", stale_revisions=stale)
    else:
        human(lib, "b", "a", stale_revisions=stale,
              **({"relation": "independent_parallel", "support_type": "source_stated"}
                 if case == "independent_parallel" else {}))
        if case == "non_live":
            lib.store.set_user_selection(lib.rid, lib.ids["a"], "excluded", 1, "SYNTHETIC exclusion")
        elif case == "scope_changed":
            lib.store.revise_scope(lib.rid, lib.store.research(lib.rid)["version"], "SYNTHETIC changed question?", None)
        elif case == "evidence_not_current":
            lib.store.remove_asset(lib.rid, lib.ids["b"], asset)
    if case == "ordinary":
        def unexpected_check(*args):
            raise AssertionError("An ordinary column must skip the graph check")
        monkeypatch.setattr(LineageStore, "reactivation_closes_cycle", unexpected_check)
    history = state(lib)
    events = lib.conn.execute("SELECT COUNT(*) FROM events WHERE type = 'column_restored'").fetchone()[0]
    lib.tables.restore_column(lib.rid, lib.tid, column["id"], column["version"] + 1)
    assert lib.tables._column(lib.tid, column["id"])["removed_at"] is None
    assert state(lib) == history
    assert lib.conn.execute("SELECT COUNT(*) FROM events WHERE type = 'column_restored'").fetchone()[0] == events + 1
    reasons = stale_link_reasons(lib.store, lib.tid)
    if case in ("scope_changed", "evidence_not_current"):
        assert reasons[accepted["link_id"]] == (accepted["revision_id"], (case,))
    else:
        assert accepted["link_id"] not in reasons
    if case != "ordinary":
        assert not graph_has_cycle(lib, stale_link_revisions(lib.store, lib.tid))


@pytest.mark.parametrize("kind", ["excluded", "removed_row", "removed_corpus"])
def test_cycle_check_ignores_edges_with_excluded_or_removed_ends(lib, kind):
    model(lib, "b", "c")
    model(lib, "c", "a")
    if kind == "excluded":
        lib.conn.execute("UPDATE selections SET state = 'excluded' WHERE source_version_id = ?", (lib.ids["c"],))
    elif kind == "removed_row":
        lib.conn.execute("UPDATE table_rows SET removed_at = 'now' WHERE source_version_id = ?", (lib.ids["c"],))
    else:
        lib.conn.execute("UPDATE corpus_memberships SET removed_at = 'now' WHERE source_version_id = ?", (lib.ids["c"],))
    assert model(lib)["current"]
    assert len(lib.lineage.active_links(lib.tid)) == 3  # read helper deliberately keeps out-of-scope edges


@pytest.mark.parametrize("human_write", [False, True])
def test_cycle_check_ignores_named_stale_revisions(lib, human_write):
    first = model(lib, "b", "a")
    assert model(lib)["rejection_code"] == "cycle"
    assert model(lib, stale_revisions={first["link_id"]: "different-revision"})["rejection_code"] == "cycle"
    stale = {first["link_id"]: first["revision_id"]}
    if human_write:
        assert human(lib, stale_revisions=stale)
    else:
        assert model(lib, stale_revisions=stale)["current"]


def test_refreshed_stale_link_counts_again_inside_the_same_batch(lib):
    first = model(lib, "z", "a")
    stale = {first["link_id"]: first["revision_id"]}
    results = lib.lineage.apply_model_proposals([proposal(lib, "a", "z"),
                                               proposal(lib, "z", "a", input_fingerprint="changed")], stale_revisions=stale)
    assert results[0]["current"] and results[1]["rejection_code"] == "cycle"


@pytest.mark.parametrize("case", ["empty_evidence", "nonlink_fields", "independent_inference", "output_status", "empty_step", "removed", "bad_decision"])
def test_proposal_shape_errors_raise_and_store_nothing(lib, case):
    p = proposal(lib)
    if case == "empty_evidence":
        p["decision"]["evidence"] = []
    elif case == "nonlink_fields":
        p["decision"]["decision"] = "no_relation"
    elif case == "independent_inference":
        p["decision"].update(relation="independent_parallel", support_type="analyst_inference")
    elif case == "output_status":
        p["output_status"] = "verified"
    elif case == "empty_step":
        p["step_input_id"] = ""
    elif case == "removed":
        p["decision"] = decision(lib, value="removed")
    else:
        p["decision"]["decision"] = "unknown"
    before = state(lib)
    with pytest.raises(InvalidLineageInput):
        lib.lineage.apply_model_proposal(**p)
    assert state(lib) == before


@pytest.mark.parametrize("by_step", [False, True])
def test_replay_recomputes_current_after_a_human_edit(lib, by_step):
    p = proposal(lib, idempotency_key="key")
    first = lib.lineage.apply_model_proposal(**p)
    edit(lib)
    replay = lib.lineage.apply_model_proposal(**(p | {"idempotency_key": None if by_step else "key"}))
    assert replay == first | {"current": False}
    assert len(lib.lineage.revisions(first["link_id"])) == 2


def test_model_key_reused_for_another_pair_is_refused(lib):
    model(lib, idempotency_key="key")
    with pytest.raises(InvalidLineageInput, match="another pair"):
        model(lib, "c", "d", idempotency_key="key")
    assert not lib.lineage.link(lib.tid, lib.ids["c"], lib.ids["d"])


def test_human_independent_parallel_needs_source_stated(lib):
    with pytest.raises(InvalidLineageInput, match="source_stated"):
        human(lib, relation="independent_parallel")
    assert human(lib, relation="independent_parallel", support_type="source_stated")


def test_remove_link_works_when_an_end_is_no_longer_live(lib):
    human(lib)
    lib.conn.execute("UPDATE selections SET state = 'excluded' WHERE source_version_id = ?", (lib.ids["b"],))
    with pytest.raises(InvalidLineageInput):
        edit(lib)
    assert remove(lib)
    assert not lib.lineage.active_links(lib.tid)


def test_human_link_requires_different_works_and_live_endpoints(lib):
    with pytest.raises(InvalidLineageInput, match="different works"):
        human(lib, "a", "x")
    lib.conn.execute("UPDATE corpus_memberships SET removed_at = 'now' WHERE source_version_id = ?", (lib.ids["b"],))
    with pytest.raises(InvalidLineageInput, match="live included"):
        human(lib)


@pytest.mark.parametrize("count", [5, 6])
def test_evidence_item_limit_is_checked_before_located_duplicates_are_collapsed(lib, count):
    evidence = [{"passage_id": lib.passages["b"], "quote": QUOTE}] * count
    if count == 6:
        with pytest.raises(InvalidLineageInput, match="1 to 5"):
            model(lib, decision=decision(lib, evidence=evidence))
        with pytest.raises(InvalidLineageInput, match="1 to 5"):
            human(lib, evidence=evidence)
        assert not lib.lineage.link(lib.tid, lib.ids["a"], lib.ids["b"])
    else:
        result = model(lib, decision=decision(lib, evidence=evidence))
        assert result["current"] and len(lib.lineage.evidence(result["revision_id"])) == 1


def test_storage_joins_and_rolls_back_with_the_callers_transaction(lib):
    p = proposal(lib)
    before = state(lib)
    with pytest.raises(RuntimeError, match="SYNTHETIC outer rollback"):
        with db.transaction(lib.conn):
            result = lib.lineage.apply_model_proposal(**p)
            assert result["current"] and lib.conn.in_transaction
            raise RuntimeError("SYNTHETIC outer rollback")
    assert state(lib) == before


def test_rejected_model_revision_replays_without_changing_its_rejection(lib):
    p = proposal(lib, scope_revision=0, idempotency_key="rejected-key")
    first = lib.lineage.apply_model_proposal(**p)
    assert first["rejection_code"] == "stale_input"
    replay = lib.lineage.apply_model_proposal(**(p | {"scope_revision": 1}))
    assert replay == first and len(lib.lineage.revisions(first["link_id"])) == 1


def test_lookup_and_table_scope_refusals(lib):
    with pytest.raises(NotFound):
        lib.lineage.link_by_id("missing")
    with pytest.raises(NotFound):
        lib.lineage.ensure_link(lib.tid, "missing", lib.ids["b"])
    human(lib)
    with pytest.raises(NotFound):
        edit(lib, table_id=lib.tables.create_table(lib.rid, "SYNTHETIC other", None, None, None))


def test_purge_table_deletes_lineage_rows_in_order(lib):
    model(lib)
    edit(lib)
    remove(lib)
    other = lib.tables.create_table(lib.rid, "SYNTHETIC other", None, None, None)
    lib.conn.execute("INSERT INTO table_purge_authorizations VALUES (?)", (other,))
    with pytest.raises(sqlite3.IntegrityError, match="immutable"):
        lib.conn.execute("DELETE FROM lineage_link_evidence")
    lib.conn.execute("DELETE FROM table_purge_authorizations")
    lib.tables.trash_table(lib.rid, lib.tid, lib.tables._table(lib.rid, lib.tid)["version"])
    lib.tables.purge_table(lib.tid)
    assert all(not rows for rows in state(lib).values())
    assert lib.conn.execute("PRAGMA foreign_key_check").fetchall() == []
    assert not lib.conn.execute("SELECT * FROM table_purge_authorizations").fetchall()


def test_research_deletion_deletes_lineage_rows(lib):
    model(lib)
    edit(lib)
    remove(lib)
    lib.store.trash_research(lib.rid)
    lib.store.purge_research(lib.rid)
    assert all(not rows for rows in state(lib).values())
    for table in ("runs", "run_steps", "step_inputs", "researches"):
        assert not lib.conn.execute(f"SELECT * FROM {table}").fetchall()
    assert lib.conn.execute("PRAGMA foreign_key_check").fetchall() == []


def test_cited_source_versions_sees_lineage_ends_and_evidence(lib):
    model(lib)
    model(lib, input_fingerprint="changed", decision=decision(lib, value="no_relation"))
    human(lib, "c", "d")
    remove(lib, "c", "d")
    # Isolate lineage protection from table_rows, without inventing impossible third-source evidence.
    lib.conn.execute("DELETE FROM table_rows")
    assert lib.store.cited_source_versions(list(lib.ids.values())) == {lib.ids[k] for k in ("a", "b", "c", "d")}
    other_rid = lib.store.create_research("SYNTHETIC other?", "attached", "quick", [], "fake", "fake-model", "en")
    other_tid = lib.tables.create_table(other_rid, "SYNTHETIC other", None, None, None)
    lib.lineage.ensure_link(other_tid, lib.ids["z"], lib.ids["x"])
    assert lib.store.cited_source_versions([lib.ids["z"], lib.ids["x"]]) == {lib.ids["z"], lib.ids["x"]}
    assert lib.store.cited_source_versions([]) == set()


def attach_synthetic_asset(lib, letter="b"):
    asset = db.new_id("ast")
    lib.conn.execute("INSERT INTO source_assets (id, source_version_id, sha256, byte_size, media_type, storage_path, retrieved_at, origin, extraction_status)"
                     " VALUES (?, ?, ?, 10, 'application/pdf', 'synthetic.pdf', 'now', 'user_upload', 'succeeded')", (asset, lib.ids[letter], "a" * 64))
    passage = lib.store._insert_passage(lib.ids[letter], asset, "pdf_page", 1, None, "pdf_extraction", None, None, TEXT)
    lib.passages[letter] = passage
    return asset


def test_research_cites_asset_sees_lineage_evidence(lib, tmp_path):
    from fastapi.testclient import TestClient
    from deixis.api.app import create_app
    from deixis.config import Settings
    from fakes import FakeAdapter
    from helpers import make_pdf
    from test_api_flow import create, session

    asset = attach_synthetic_asset(lib)
    model(lib)
    remove(lib)
    assert lib.store.research_cites_asset(lib.rid, asset)
    other = lib.store.create_research("SYNTHETIC unrelated?", "attached", "quick", [], "fake", "fake-model", "en")
    assert not lib.store.research_cites_asset(other, asset)
    app = create_app(Settings(data_dir=tmp_path / "api-data"), adapters={"fake": FakeAdapter()}, start_worker=False,
                     extra_hosts=("testserver",), trusted_clients=("testclient",))
    with TestClient(app) as client:
        session(client)
        rid = create(client, source_scope="attached")
        store = app.state.store
        earlier = store.create_upload_source("SYNTHETIC earlier")
        store.add_to_corpus(rid, earlier, "user_upload", selection_state="included", selection_origin="user")
        response = client.post(f"/api/researches/{rid}/uploads", files={"file": ("synthetic.pdf", make_pdf([TEXT]), "application/pdf")})
        assert response.status_code == 201, response.text
        later = next(s[0] for s in store.conn.execute("SELECT source_version_id FROM source_assets"))
        store.conn.execute("UPDATE selections SET state = 'included' WHERE research_id = ? AND source_version_id = ?", (rid, later))
        aid = store.conn.execute("SELECT id FROM source_assets WHERE source_version_id = ?", (later,)).fetchone()[0]
        passage = next(p for p in store.passages_for(later) if p["asset_id"] == aid)
        tables, lineage = TableStore(store), LineageStore(store)
        tid = tables.create_table(rid, "SYNTHETIC API table", None, None, None)
        lineage.add_link(rid, tid, earlier, later, "extends", "SYNTHETIC change", "source_stated",
                         [{"passage_id": passage["id"], "quote": QUOTE}], None, 0, None)
        assert not store.conn.execute("SELECT * FROM evidence_links").fetchall()
        assert not store.conn.execute("SELECT * FROM cell_evidence_links").fetchall()
        base = f"/api/researches/{rid}/sources/{later}/assets/{aid}"
        assert client.delete(base).status_code == 200
        # Existing wrong-file removal deliberately denies the PDF even when cited; its citation record survives.
        assert client.get(f"/api/researches/{rid}/assets/{aid}").status_code == 404
        assert store.research_cites_asset(rid, aid)
        assert client.post(base + "/restore").status_code == 200
        replacement = client.put(base, files={"file": ("new.pdf", make_pdf(["SYNTHETIC replacement notes"]), "application/pdf")})
        assert replacement.status_code == 200, replacement.text
        assert client.get(f"/api/researches/{rid}/assets/{aid}").status_code == 200
        assert store.research_cites_asset(rid, aid)
        store.remove_sources(rid, [later], "SYNTHETIC corpus removal")
        assert client.get(f"/api/researches/{rid}/assets/{aid}").status_code == 200


def test_asset_impact_counts_lineage_links(lib):
    asset = attach_synthetic_asset(lib)
    model(lib)
    edit(lib)
    remove(lib)
    human(lib, "c", "b")
    impact = lib.store.asset_impact(asset)
    assert impact["lineage_links"] == 2 and impact["cells"] == impact["quotes"] == 0


def test_table_impact_counts_lineage_links_and_human_edits(lib):
    model(lib)
    edit(lib)
    remove(lib)
    human(lib, "c", "d")
    assert lib.tables.table_impact(lib.tid) == {"cells": 0, "human_edits": 0, "lineage_links": 1, "lineage_human_edits": 3}


@pytest.mark.parametrize("status", ["queued", "running", "pause_requested"])
def test_trash_table_refuses_while_a_lineage_run_is_active(lib, status):
    lib.conn.execute("INSERT INTO runs (id, research_id, scope_revision, kind, status, stage, budget_json, target_json, created_at, updated_at)"
                     " VALUES ('run_lineage', ?, 1, 'lineage_links', ?, 'synthesis', '{}', ?, 'now', 'now')",
                     (lib.rid, status, db.dumps({"table_id": lib.tid, "plan_version": 1})))
    with pytest.raises(RevisionConflict):
        lib.tables.trash_table(lib.rid, lib.tid, lib.tables._table(lib.rid, lib.tid)["version"])
    lib.conn.execute("UPDATE runs SET status = 'completed' WHERE id = 'run_lineage'")
    lib.tables.trash_table(lib.rid, lib.tid, lib.tables._table(lib.rid, lib.tid)["version"])


def test_trash_and_restore_do_not_rewrite_lineage_history(lib):
    model(lib)
    edit(lib)
    remove(lib)
    before = state(lib)
    version = lib.tables._table(lib.rid, lib.tid)["version"]
    lib.tables.trash_table(lib.rid, lib.tid, version)
    assert state(lib) == before
    lib.tables.restore_table(lib.rid, lib.tid, version + 1)
    assert state(lib) == before
