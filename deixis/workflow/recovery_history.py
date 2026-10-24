"""Authorized recovery deletion and fail-closed protection of frozen passage references."""

from __future__ import annotations

import json
import logging
import re
import time
from contextlib import contextmanager

from deixis.domain.rules import RevisionConflict
from deixis.storage.db import transaction
from deixis.workflow import file_restore, text_retry

logger = logging.getLogger(__name__)
RETAINED = re.compile(r"^retained-[0-9a-f]{64}\.bin$")


class FrozenDependencyUnreadable(ValueError):
    code = "frozen_dependency_unreadable"
    detail = "A stored model input, report snapshot or gap record could not be read, so nothing was deleted."


def frozen_source_versions(conn, source_ids, *, research_id=None) -> set[str]:
    """Read frozen records only where these sources could have entered research work."""
    sources = json.dumps(sorted(set(source_ids)))
    queries = [f"SELECT research_id FROM {table} WHERE source_version_id IN chosen"
               for table in ("corpus_memberships", "candidates")]
    for table in ("kill_search_query_records", "kill_search_hits"):
        queries.append(f"SELECT c.research_id FROM {table} q"
                       " JOIN kill_searches s ON s.id = q.kill_search_id"
                       " JOIN candidate_versions v ON v.id = s.candidate_version_id"
                       " JOIN research_candidates c ON c.id = v.candidate_id WHERE q.source_version_id IN chosen")
    linked = {r[0] for r in conn.execute(
        "WITH chosen AS (SELECT value FROM json_each(?)) " + " UNION ".join(queries), (sources,),
    )}
    if research_id is not None:
        linked.add(research_id)
    if not linked:
        return set()
    scope = json.dumps(sorted(linked))
    ids = set()

    def collect(value):
        if isinstance(value, dict):
            for key, item in value.items():
                if key == "passage_id":
                    if item is not None and not isinstance(item, str):
                        raise FrozenDependencyUnreadable()
                    if item is not None:
                        ids.add(item)
                elif key in ("passage_ids", "basis_passage_ids"):
                    if not isinstance(item, list) or any(v is not None and not isinstance(v, str) for v in item):
                        raise FrozenDependencyUnreadable()
                    ids.update(v for v in item if v is not None)
                collect(item)
        elif isinstance(value, list):
            for item in value:
                collect(item)

    for table, column in (("step_inputs", "payload_json"), ("report_snapshot", "snapshot_json"), ("report_gaps", "basis_json")):
        if table == "step_inputs":
            query = "SELECT payload_json FROM step_inputs WHERE research_id IN (SELECT value FROM json_each(?))"
        else:
            query = (f"SELECT f.{column} FROM {table} f JOIN reports r ON r.id = f.report_id"
                     " WHERE r.research_id IN (SELECT value FROM json_each(?))")
        for row in conn.execute(query, (scope,)):
            try:
                collect(json.loads(row[0]))
            except (ValueError, TypeError, RecursionError) as exc:
                raise FrozenDependencyUnreadable() from exc
    result = set()
    ordered = sorted(ids)
    for start in range(0, len(ordered), 500):
        result.update(r[0] for r in conn.execute(
            "SELECT DISTINCT source_version_id FROM passages WHERE id IN (SELECT value FROM json_each(?))",
            (json.dumps(ordered[start:start + 500]),),
        ))
    return result


@contextmanager
def waited_hash_lock(recovery_dir, sha256):
    deadline = time.monotonic() + file_restore.WRITER_LOCK_WAIT_SECONDS
    while True:
        lock = text_retry.file_lock(recovery_dir, sha256)
        try:
            lock.__enter__()
            break
        except text_retry.FileBusy:
            remaining = deadline - time.monotonic()
            if remaining <= 0:
                raise
            time.sleep(min(0.05, remaining))
    try:
        yield
    finally:
        lock.__exit__(None, None, None)


def purge_asset_history(conn, source_id) -> list[str]:
    """Compute the surviving FK closure before deleting any row of this source."""
    assets = list(conn.execute("SELECT id, sha256 FROM source_assets WHERE source_version_id = ?", (source_id,)))
    deleting_assets = {r["id"] for r in assets}
    hashes = {r["sha256"] for r in assets}
    unshared = hashes - {r[0] for r in conn.execute(
        "SELECT DISTINCT sha256 FROM source_assets WHERE sha256 IN (SELECT value FROM json_each(?))"
        " AND source_version_id <> ?", (json.dumps(sorted(hashes)), source_id),
    )}
    asset_ids = json.dumps(sorted(deleting_assets))
    if conn.execute(
        "SELECT 1 FROM asset_recovery_operations WHERE lifecycle = 'running' AND"
        " (asset_id IN (SELECT value FROM json_each(?)) OR"
        " (kind = 'file_restore' AND expected_sha256 IN (SELECT value FROM json_each(?)))) LIMIT 1",
        (asset_ids, json.dumps(sorted(hashes))),
    ).fetchone():
        raise RevisionConflict("A file repair or text retry of these sources is still running; try again when it ends.")

    specs = {
        "e": ("asset_extractions", "id, asset_id, baseline_extraction_id, input_observation_id, recovery_operation_id",
              (("asset_id", "a"), ("baseline_extraction_id", "e"), ("input_observation_id", "obs"), ("recovery_operation_id", "o"))),
        "o": ("asset_recovery_operations", "id, asset_id, expected_sha256, baseline_extraction_id, before_observation_id, after_observation_id, input_observation_id",
              (("asset_id", "a"), ("baseline_extraction_id", "e"), ("before_observation_id", "obs"), ("after_observation_id", "obs"), ("input_observation_id", "obs"))),
        "obs": ("asset_file_observations", "id, operation_id, expected_sha256, retained_filename", (("operation_id", "o"),)),
    }
    records = {kind: {} for kind in specs}
    graph = {}

    def load(kind, where, params):
        table, columns, edges = specs[kind]
        nodes = set()
        for row in conn.execute(f"SELECT {columns} FROM {table} WHERE {where}", params):
            records[kind][row["id"]] = row
            node = (kind, row["id"])
            graph[node] = [(target, row[column]) for column, target in edges if row[column] is not None]
            nodes.add(node)
        return nodes

    load("e", "asset_id IN (SELECT value FROM json_each(?))", (asset_ids,))
    load("o", "asset_id IN (SELECT value FROM json_each(?)) OR"
         " (kind = 'file_restore' AND expected_sha256 IN (SELECT value FROM json_each(?)))",
         (asset_ids, json.dumps(sorted(unshared))))
    deleting_e, deleting_o = set(records["e"]), set(records["o"])
    deleting_obs = {r["input_observation_id"] for r in records["e"].values() if r["input_observation_id"]}
    deleting_obs.update(r[key] for r in records["o"].values()
                        for key in ("before_observation_id", "after_observation_id", "input_observation_id") if r[key])
    load("obs", "id IN (SELECT value FROM json_each(?)) OR operation_id IN (SELECT value FROM json_each(?))",
         (json.dumps(sorted(deleting_obs)), json.dumps(sorted(deleting_o))))
    deleting_obs = set(records["obs"])
    candidates = ({("e", i) for i in deleting_e} | {("o", i) for i in deleting_o}
                  | {("obs", i) for i in deleting_obs})
    deleting = {"a": deleting_assets, "e": deleting_e, "o": deleting_o, "obs": deleting_obs}
    # Only outside rows with an incoming FK into the deletion set can keep it alive.
    # From those roots, follow the same outgoing FK closure to a fixpoint.
    roots = set()
    for kind, (_, _, edges) in specs.items():
        clauses, params = [], []
        for column, target in edges:
            if deleting[target]:
                clauses.append(f"{column} IN (SELECT value FROM json_each(?))")
                params.append(json.dumps(sorted(deleting[target])))
        if clauses:
            roots.update(load(kind, " OR ".join(clauses), params) - candidates)
    kept, todo = set(roots), roots
    while todo:
        for kind in specs:
            missing = {oid for k, oid in todo if k == kind and (k, oid) not in graph}
            if missing:
                load(kind, "id IN (SELECT value FROM json_each(?))", (json.dumps(sorted(missing)),))
        targets = {target for node in todo for target in graph.get(node, [])}
        todo = targets - kept
        kept.update(todo)
    if any(("a", aid) in kept for aid in deleting_assets) or any(("e", eid) in kept for eid in deleting_e):
        raise RevisionConflict("Recovery history of these sources is still referenced elsewhere; nothing was deleted.")
    deleting_o -= {oid for kind, oid in kept if kind == "o"}
    deleting_obs -= {oid for kind, oid in kept if kind == "obs"}
    operations, observations = records["o"], records["obs"]
    touched = {operations[oid]["expected_sha256"] for oid in deleting_o} | {
        observations[oid]["expected_sha256"] for oid in deleting_obs}
    conn.executemany("INSERT INTO recovery_purge_authorizations (sha256) VALUES (?)", [(sha,) for sha in sorted(touched)])
    retained = {observations[oid]["retained_filename"] for oid in deleting_obs if observations[oid]["retained_filename"]}
    conn.execute("DELETE FROM asset_extractions WHERE id IN (SELECT value FROM json_each(?))", (json.dumps(sorted(deleting_e)),))
    conn.execute("DELETE FROM asset_file_observations WHERE id IN (SELECT value FROM json_each(?))", (json.dumps(sorted(deleting_obs)),))
    conn.execute("DELETE FROM asset_recovery_operations WHERE id IN (SELECT value FROM json_each(?))", (json.dumps(sorted(deleting_o)),))
    conn.executemany("DELETE FROM recovery_purge_authorizations WHERE sha256 = ?", [(sha,) for sha in sorted(touched)])
    return sorted(name for name in retained if not conn.execute(
        "SELECT 1 FROM asset_file_observations WHERE retained_filename = ?", (name,),
    ).fetchone())


def remove_retained(store, papers_dir, name) -> bool:
    if not RETAINED.fullmatch(name):
        return False
    if store.conn.in_transaction:
        raise ValueError("Retained unlink requires its own short transaction")
    try:
        with transaction(store.conn):
            if store.conn.execute("SELECT 1 FROM asset_file_observations WHERE retained_filename = ?", (name,)).fetchone():
                return False
            if store.conn.execute("SELECT 1 FROM asset_recovery_operations WHERE kind = 'file_restore'"
                                  " AND lifecycle = 'running' LIMIT 1").fetchone():
                return False
            (papers_dir / name).unlink(missing_ok=True)
        return True
    except OSError:
        logger.exception("Could not remove retained recovery file %s", name)
        return False


def unreferenced_retained(store, papers_dir):
    referenced = {r[0] for r in store.conn.execute(
        "SELECT retained_filename FROM asset_file_observations WHERE retained_filename IS NOT NULL")}
    return [(path.name, path.stat().st_size) for path in sorted(papers_dir.glob("retained-*.bin"))
            if RETAINED.fullmatch(path.name) and path.name not in referenced and path.is_file() and not path.is_symlink()]
