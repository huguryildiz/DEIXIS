"""L4 synthetic storage behavior, without providers, model calls or scientific validation."""

import sqlite3
from types import SimpleNamespace

import pytest

from deixis.storage import db
from deixis.workflow.lineage_run import build_node, node_snapshot, stale_link_reasons, stale_link_revisions
from deixis.workflow.lineage_store import InvalidLineageInput, LineageStore
from deixis.workflow.store import Store
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


@pytest.mark.parametrize("authorization", ["table"])
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


@pytest.mark.parametrize("insert", ["INSERT OR REPLACE INTO"])
@pytest.mark.parametrize("case", ["revision"])
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


@pytest.mark.parametrize("letter", ["a"])
def test_evidence_must_come_from_the_later_work(lib, letter):
    revision = raw_revision(lib)
    with pytest.raises(sqlite3.IntegrityError, match="later work"):
        raw_evidence(lib, revision, letter)
    with pytest.raises(sqlite3.IntegrityError, match="later work"):
        raw_evidence(lib, revision, source_version_id=lib.ids["c"])


@pytest.mark.parametrize("existing", [True])
def test_unverified_draft_is_never_current(lib, existing):
    if existing:
        model(lib)
    before = lib.lineage.link(lib.tid, lib.ids["a"], lib.ids["b"])
    result = model(lib, output_status="unverified_draft", input_fingerprint="changed")
    assert result["disposition"] == "accepted" and not result["current"]
    assert lib.lineage.link_by_id(result["link_id"])["version"] == (before["version"] if before else 0)
    assert lib.lineage.evidence(result["revision_id"])


@pytest.mark.parametrize("quote,kind", [(QUOTE.replace("earlier", "earlierx"), "fuzzy")])
def test_stored_anchor_is_the_located_source_text_not_the_raw_quote(lib, quote, kind):
    result = model(lib, decision=decision(lib, evidence=[{"passage_id": lib.passages["b"], "quote": quote}]))
    assert result["current"]
    evidence = lib.lineage.evidence(result["revision_id"])[0]
    assert evidence["anchor_text"] == QUOTE and evidence["anchor_match"] == kind


def test_diamond_is_valid_and_directed_cycle_is_rejected(lib):
    for a, b in (("a", "b"), ("a", "c"), ("b", "d"), ("c", "d")):
        assert model(lib, a, b)["current"]
    assert len(lib.lineage.active_links(lib.tid)) == 4
    assert model(lib, "d", "a")["rejection_code"] == "cycle"


def test_batch_is_atomic(lib):
    proposals = [proposal(lib), proposal(lib, "c", "d", decision=decision(lib, "d", evidence=[]))]
    before, events = state(lib), lib.store.events_after(lib.rid, 0)
    with pytest.raises(InvalidLineageInput):
        lib.lineage.apply_model_proposals(proposals)
    assert state(lib) == before and lib.store.events_after(lib.rid, 0) == events


@pytest.mark.parametrize("by_step", [True])
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


@pytest.mark.parametrize("action", [remove])
def test_human_decision_survives_a_later_model_run(lib, action):
    model(lib)
    revision = action(lib)
    result = model(lib, input_fingerprint="changed")
    assert result["rejection_code"] == "superseded_by_human"
    assert lib.lineage.link_by_id(result["link_id"])["current_revision_id"] == revision
    assert bool(lib.lineage.active_links(lib.tid)) == (action == edit)


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


@pytest.mark.parametrize("three_nodes", [True], ids=["three-node-cycle"])
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
