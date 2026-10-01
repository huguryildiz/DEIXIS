"""Durable pair decisions; anchor location and graph checks do not verify scientific meaning.

Node inputs are opaque here. Callers name stale revisions; unnamed stale inputs still count in cycle checks.
"""

from __future__ import annotations

import json
from collections.abc import Iterator, Mapping
from contextlib import contextmanager
from datetime import datetime, timedelta
from typing import Any

from deixis.domain.contracts import locate_anchor
from deixis.domain.rules import RevisionConflict, check_expected_version
from deixis.storage.db import dumps, new_id, now, transaction
from deixis.workflow.store import NotFound, Store
from deixis.workflow.tables import SOURCE_ACTIVE_SQL, TableStore

RELATIONS = ("extends", "relaxes_assumption", "changes_method", "new_domain_or_condition",
             "corrects_or_contradicts", "independent_parallel")
SUPPORT_TYPES = ("source_stated", "analyst_inference")
DECISIONS = ("link", "no_relation", "insufficient_evidence", "removed")
REVISION_KINDS = ("model_propose", "human_add", "human_edit", "human_remove")
REJECTION_CODES = ("cycle", "anchor_not_found", "same_work", "endpoint_not_included", "superseded_by_human", "stale_input")
MAX_WHAT_CHANGED = 500
MAX_EVIDENCE = 5
LIVE_ENDPOINT_SQL = (
    "SELECT 1 FROM table_rows t JOIN evidence_tables et_endpoint ON et_endpoint.id = t.table_id"
    " JOIN selections s ON s.research_id = et_endpoint.research_id AND s.source_version_id = t.source_version_id"
    f" WHERE t.table_id = ? AND t.source_version_id = ? AND t.removed_at IS NULL AND {SOURCE_ACTIVE_SQL}"
    " AND s.state = 'included'"
)


class InvalidLineageInput(Exception):
    """A caller shape error or a human write refused by the lineage rules."""


class LineageStore:
    def __init__(self, store: Store):
        self.store = store
        self.conn = store.conn
        self.tables = TableStore(store)

    def link(self, table_id: str, from_svid: str, to_svid: str) -> dict[str, Any] | None:
        row = self.conn.execute(
            "SELECT * FROM lineage_links WHERE table_id = ? AND from_source_version_id = ? AND to_source_version_id = ?",
            (table_id, from_svid, to_svid),
        ).fetchone()
        return dict(row) if row else None

    def link_by_id(self, link_id: str) -> dict[str, Any]:
        row = self.conn.execute("SELECT * FROM lineage_links WHERE id = ?", (link_id,)).fetchone()
        if row is None:
            raise NotFound(link_id)
        return dict(row)

    def ensure_link(self, table_id: str, from_svid: str, to_svid: str) -> dict[str, Any]:
        with transaction(self.conn):
            if from_svid == to_svid:
                raise InvalidLineageInput("A lineage pair needs two different source versions")
            if existing := self.link(table_id, from_svid, to_svid):
                return existing
            if not self.conn.execute("SELECT 1 FROM evidence_tables WHERE id = ?", (table_id,)).fetchone():
                raise NotFound(table_id)
            self._work(from_svid)
            self._work(to_svid)
            ts = now()
            self.conn.execute(
                "INSERT INTO lineage_links (id, table_id, from_source_version_id, to_source_version_id, created_at, updated_at)"
                " VALUES (?, ?, ?, ?, ?, ?)", (new_id("llk"), table_id, from_svid, to_svid, ts, ts),
            )
            return self.link(table_id, from_svid, to_svid)

    def revisions(self, link_id: str) -> list[dict[str, Any]]:
        return [dict(r) for r in self.conn.execute(
            "SELECT * FROM lineage_link_revisions WHERE link_id = ? ORDER BY created_at, id", (link_id,))]

    def evidence(self, revision_id: str) -> list[dict[str, Any]]:
        return [dict(r) for r in self.conn.execute(
            "SELECT * FROM lineage_link_evidence WHERE link_revision_id = ? ORDER BY anchor_text, passage_id", (revision_id,))]

    def active_links(self, table_id: str) -> list[dict[str, Any]]:
        return [dict(r) for r in self.conn.execute(
            "SELECT l.*, r.id AS revision_id, r.relation, r.support_type FROM lineage_links l"
            " JOIN lineage_link_revisions r ON r.id = l.current_revision_id"
            " WHERE l.table_id = ? AND r.disposition = 'accepted' AND r.decision = 'link' ORDER BY l.created_at, l.id", (table_id,))]

    def human_decided_pairs(self, table_id: str) -> set[tuple[str, str]]:
        return {tuple(r) for r in self.conn.execute(
            "SELECT l.from_source_version_id, l.to_source_version_id FROM lineage_links l"
            " JOIN lineage_link_revisions r ON r.id = l.current_revision_id WHERE l.table_id = ? AND r.author = 'human'",
            (table_id,))}

    def _current(self, pair: dict[str, Any]) -> dict[str, Any] | None:
        row = self.conn.execute("SELECT * FROM lineage_link_revisions WHERE id = ?", (pair["current_revision_id"],)).fetchone()
        return dict(row) if row else None

    def _work(self, svid: str) -> str:
        row = self.conn.execute("SELECT work_id FROM source_versions WHERE id = ?", (svid,)).fetchone()
        if row is None:
            raise NotFound(svid)
        return row[0]

    def _live(self, table_id: str, svid: str) -> bool:
        return self.conn.execute(LIVE_ENDPOINT_SQL, (table_id, svid)).fetchone() is not None

    def _replay(self, pair: dict[str, Any] | None, key: str | None, step_input_id: str | None = None) -> dict[str, Any] | None:
        if key is not None:
            row = self.conn.execute("SELECT * FROM lineage_link_revisions WHERE idempotency_key = ?", (key,)).fetchone()
            if row:
                if pair is None or row["link_id"] != pair["id"]:
                    raise InvalidLineageInput("This idempotency key was used for another pair")
                return dict(row)
        if pair and isinstance(step_input_id, str) and step_input_id:
            row = self.conn.execute(
                "SELECT * FROM lineage_link_revisions WHERE link_id = ? AND step_input_id = ? AND author = 'model'"
                " ORDER BY created_at, id LIMIT 1", (pair["id"], step_input_id),
            ).fetchone()
            if row:
                return dict(row)
        return None

    def _result(self, revision: dict[str, Any]) -> dict[str, Any]:
        pair = self.link_by_id(revision["link_id"])
        return {"link_id": pair["id"], "revision_id": revision["id"], "disposition": revision["disposition"],
                "rejection_code": revision["rejection_code"], "current": pair["current_revision_id"] == revision["id"]}

    @staticmethod
    def _shape(decision: dict[str, Any]) -> None:
        if not isinstance(decision, dict) or not {"decision", "relation", "what_changed", "support_type", "evidence", "note"} <= decision.keys():
            raise InvalidLineageInput("A decision needs decision, relation, what_changed, support_type, evidence and note")
        if decision["decision"] not in DECISIONS:
            raise InvalidLineageInput("Unknown decision")
        evidence = decision["evidence"]
        if not isinstance(evidence, list):
            raise InvalidLineageInput("Evidence must be a list")
        if decision["note"] is not None and not isinstance(decision["note"], str):
            raise InvalidLineageInput("A note is text or null")
        if decision["decision"] != "link":
            if any(decision[k] is not None for k in ("relation", "what_changed", "support_type")) or evidence:
                raise InvalidLineageInput("A non-link has null link fields and no evidence")
            return
        changed = decision["what_changed"]
        if decision["relation"] not in RELATIONS or decision["support_type"] not in SUPPORT_TYPES:
            raise InvalidLineageInput("Unknown relation or support type")
        if not isinstance(changed, str) or not changed.strip() or not 1 <= len(changed) <= MAX_WHAT_CHANGED:
            raise InvalidLineageInput(f"what_changed needs 1 to {MAX_WHAT_CHANGED} characters")
        if decision["relation"] == "independent_parallel" and decision["support_type"] != "source_stated":
            raise InvalidLineageInput("independent_parallel needs source_stated support")
        if not 1 <= len(evidence) <= MAX_EVIDENCE:
            raise InvalidLineageInput(f"A link needs 1 to {MAX_EVIDENCE} evidence items")
        for item in evidence:
            if (not isinstance(item, dict) or not isinstance(item.get("passage_id"), str) or not item["passage_id"]
                    or not isinstance(item.get("quote"), str) or not item["quote"].strip()):
                raise InvalidLineageInput("Each evidence item needs a passage_id and a non-empty quote")

    def _locate(self, to_svid: str, evidence: list[dict[str, Any]]) -> list[dict[str, Any]] | None:
        located, seen = [], set()
        for item in evidence:
            passage = self.conn.execute("SELECT source_version_id, text FROM passages WHERE id = ?", (item["passage_id"],)).fetchone()
            if passage is None or passage["source_version_id"] != to_svid:
                return None
            match = locate_anchor(item["quote"], passage["text"])
            if match is None:
                return None
            key = (item["passage_id"], match.text)
            if key not in seen:
                seen.add(key)
                located.append({"passage_id": item["passage_id"], "source_version_id": to_svid,
                                "anchor_text": match.text, "anchor_match": match.kind})
        return located

    def _cycle(self, pair: dict[str, Any], stale_revisions: Mapping[str, str]) -> bool:
        graph: dict[str, set[str]] = {}
        for edge in self.active_links(pair["table_id"]):
            if (edge["id"] == pair["id"] or edge["relation"] == "independent_parallel"
                    or stale_revisions.get(edge["id"]) == edge["revision_id"]):
                continue
            a, b = edge["from_source_version_id"], edge["to_source_version_id"]
            if self._live(pair["table_id"], a) and self._live(pair["table_id"], b):
                graph.setdefault(a, set()).add(b)
        # Adding from -> to closes a directed cycle iff to already reaches from.
        pending, seen = [pair["to_source_version_id"]], set()
        while pending:
            node = pending.pop()
            if node == pair["from_source_version_id"]:
                return True
            if node not in seen:
                seen.add(node)
                pending.extend(graph.get(node, ()))
        return False

    def _insert_revision(self, pair: dict[str, Any], key: str | None = None, **fields: Any) -> str:
        # Reads order a pair's history by created_at; two writes in one millisecond must keep their insertion order.
        ts, last = now(), self.conn.execute("SELECT MAX(created_at) FROM lineage_link_revisions WHERE link_id = ?", (pair["id"],)).fetchone()[0]
        if last is not None and ts <= last:
            ts = (datetime.fromisoformat(last) + timedelta(milliseconds=1)).isoformat(timespec="milliseconds")
        row = {"id": new_id("llr"), "link_id": pair["id"], **fields, "idempotency_key": key, "created_at": ts}
        if row.get("inputs_json") is not None:
            row["inputs_json"] = dumps(row["inputs_json"])
        self.conn.execute(f"INSERT INTO lineage_link_revisions ({', '.join(row)}) VALUES ({', '.join('?' * len(row))})", tuple(row.values()))
        return row["id"]

    def _insert_evidence(self, revision_id: str, evidence: list[dict[str, Any]]) -> None:
        self.conn.executemany(
            "INSERT INTO lineage_link_evidence (link_revision_id, passage_id, source_version_id, anchor_text, anchor_match)"
            " VALUES (?, ?, ?, ?, ?)",
            [(revision_id, e["passage_id"], e["source_version_id"], e["anchor_text"], e["anchor_match"]) for e in evidence],
        )

    def _publish(self, research_id: str, pair: dict[str, Any], revision_id: str) -> None:
        self.conn.execute("UPDATE lineage_links SET current_revision_id = ?, version = version + 1, updated_at = ? WHERE id = ?",
                          (revision_id, now(), pair["id"]))
        self.tables._touch(pair["table_id"])
        self.store._event(research_id, "lineage_changed", {"table_id": pair["table_id"], "link_id": pair["id"], "revision_id": revision_id})

    @contextmanager
    def _proposal_transaction(self) -> Iterator[None]:
        if not self.conn.in_transaction:
            with transaction(self.conn):
                yield
            return
        # A caller may catch a proposal error and still commit its own unrelated writes.
        savepoint = new_id("lineage_proposal")
        self.conn.execute(f"SAVEPOINT {savepoint}")
        try:
            yield
        except BaseException:
            self.conn.execute(f"ROLLBACK TO {savepoint}")
            self.conn.execute(f"RELEASE {savepoint}")
            raise
        else:
            self.conn.execute(f"RELEASE {savepoint}")

    def apply_model_proposal(self, *, research_id: str, table_id: str, from_svid: str, to_svid: str,
                             decision: dict[str, Any], edge_state: str, run_id: str, step_id: str, step_input_id: str,
                             scope_revision: int, link_version_at_request: int | None, inputs: dict[str, Any],
                             input_fingerprint: str, output_status: str, idempotency_key: str | None = None,
                             stale_revisions: Mapping[str, str] | None = None,
                             input_stale: bool = False) -> dict[str, Any]:
        with self._proposal_transaction():
            pair = self.link(table_id, from_svid, to_svid)
            if replay := self._replay(pair, idempotency_key, step_input_id):
                return self._result(replay)
            self._shape(decision)
            if decision["decision"] == "removed":
                raise InvalidLineageInput("Only a human removal can decide removed")
            if output_status not in ("structurally_valid", "unverified_draft") or not isinstance(step_input_id, str) or not step_input_id.strip():
                raise InvalidLineageInput("A model proposal needs a step_input_id and a valid output_status")
            if edge_state not in ("present", "absent_in_read_list", "unresolved", "not_read"):
                raise InvalidLineageInput("Unknown edge state")
            if not isinstance(inputs, dict) or not isinstance(input_fingerprint, str):
                raise InvalidLineageInput("Inputs are an object and the fingerprint is text")
            self.tables._table(research_id, table_id)
            pair = self.ensure_link(table_id, from_svid, to_svid)
            current = self._current(pair)
            rejection, located = None, []
            if self._work(from_svid) == self._work(to_svid):
                rejection = "same_work"
            elif not self._live(table_id, from_svid) or not self._live(table_id, to_svid):
                rejection = "endpoint_not_included"
            elif current and current["author"] == "human":
                rejection = "superseded_by_human"
            elif input_stale or scope_revision != self.store.research(research_id)["current_scope_revision"] or (0 if link_version_at_request is None else link_version_at_request) != pair["version"]:
                rejection = "stale_input"
            elif decision["decision"] == "link":
                located = self._locate(to_svid, decision["evidence"])
                if located is None:
                    rejection = "anchor_not_found"
                elif decision["relation"] != "independent_parallel" and self._cycle(pair, stale_revisions or {}):
                    rejection = "cycle"
            revision_id = self._insert_revision(
                pair, idempotency_key, kind="model_propose", author="model", disposition="rejected" if rejection else "accepted",
                rejection_code=rejection, origin="mention", edge_state=edge_state, decision=decision["decision"],
                relation=decision["relation"], what_changed=decision["what_changed"], support_type=decision["support_type"], note=decision["note"],
                run_id=run_id, step_id=step_id, step_input_id=step_input_id, scope_revision=scope_revision,
                link_version_at_request=link_version_at_request, inputs_json={"fingerprint": input_fingerprint, "inputs": inputs}, output_status=output_status,
            )
            if not rejection:
                self._insert_evidence(revision_id, located)
                changed = current is None or (current["author"] == "model" and
                    json.loads(current["inputs_json"] or "{}").get("fingerprint") != input_fingerprint)
                if changed and output_status == "structurally_valid":
                    self._publish(research_id, pair, revision_id)
            revision = dict(self.conn.execute("SELECT * FROM lineage_link_revisions WHERE id = ?", (revision_id,)).fetchone())
            return self._result(revision)

    def apply_model_proposals(self, proposals: list[dict[str, Any]], *,
                              stale_revisions: Mapping[str, str] | None = None) -> list[dict[str, Any]]:
        with self._proposal_transaction():
            if not isinstance(proposals, list) or any(
                not isinstance(p, dict) or not isinstance(p.get("to_svid"), str) or not isinstance(p.get("from_svid"), str)
                for p in proposals
            ):
                raise InvalidLineageInput("A proposal batch is a list of proposals with real endpoint ids")
            results = []
            for p in sorted(proposals, key=lambda p: (p["to_svid"], p["from_svid"])):
                arguments = dict(p)
                if stale_revisions is not None:
                    arguments["stale_revisions"] = stale_revisions
                results.append(self.apply_model_proposal(**arguments))
            return results

    def _human_pair(self, research_id: str, table_id: str, link_id: str) -> dict[str, Any]:
        self.tables._table(research_id, table_id)
        pair = self.link_by_id(link_id)
        if pair["table_id"] != table_id:
            raise NotFound(link_id)
        return pair

    def _human_write(self, research_id: str, pair: dict[str, Any], kind: str, decision: dict[str, Any],
                     based_on_revision_id: str | None, expected_version: int, idempotency_key: str | None,
                     stale_revisions: Mapping[str, str]) -> str:
        if replay := self._replay(pair, idempotency_key):
            return replay["id"]
        check_expected_version(expected_version, pair["version"])
        current = self._current(pair)
        active = current and current["disposition"] == "accepted" and current["decision"] == "link"
        if kind == "human_add":
            if active:
                raise RevisionConflict("This pair already has an active link; use edit")
        elif not active or based_on_revision_id != pair["current_revision_id"]:
            raise RevisionConflict("Edit or remove needs the current active link revision")
        self._shape(decision)
        located = []
        if kind != "human_remove":
            a, b = pair["from_source_version_id"], pair["to_source_version_id"]
            if not self._live(pair["table_id"], a) or not self._live(pair["table_id"], b):
                raise InvalidLineageInput("Both endpoints must be live included rows")
            if self._work(a) == self._work(b):
                raise InvalidLineageInput("A link needs different works")
            located = self._locate(b, decision["evidence"])
            if located is None:
                raise InvalidLineageInput("Every quote must be located in a passage of the later work")
            if decision["relation"] != "independent_parallel" and self._cycle(pair, stale_revisions):
                raise InvalidLineageInput("This link would close a directed cycle")
        revision_id = self._insert_revision(
            pair, idempotency_key, kind=kind, author="human", origin="human", disposition="accepted",
            decision=decision["decision"], relation=decision["relation"], what_changed=decision["what_changed"],
            support_type=decision["support_type"], note=decision["note"], based_on_revision_id=based_on_revision_id,
        )
        self._insert_evidence(revision_id, located)
        self._publish(research_id, pair, revision_id)
        return revision_id

    def add_link(self, research_id: str, table_id: str, from_svid: str, to_svid: str, relation: str,
                 what_changed: str, support_type: str, evidence: list[dict[str, Any]], note: str | None,
                 expected_version: int, idempotency_key: str | None, *, stale_revisions: Mapping[str, str] | None = None) -> str:
        with transaction(self.conn):
            pair = self.link(table_id, from_svid, to_svid)
            if replay := self._replay(pair, idempotency_key):
                return replay["id"]
            self.tables._table(research_id, table_id)
            pair = self.ensure_link(table_id, from_svid, to_svid)
            decision = dict(decision="link", relation=relation, what_changed=what_changed, support_type=support_type, evidence=evidence, note=note)
            return self._human_write(research_id, pair, "human_add", decision, None, expected_version, idempotency_key, stale_revisions or {})

    def edit_link(self, research_id: str, table_id: str, link_id: str, relation: str, what_changed: str, support_type: str,
                  evidence: list[dict[str, Any]], note: str | None, based_on_revision_id: str, expected_version: int,
                  idempotency_key: str | None, *, stale_revisions: Mapping[str, str] | None = None) -> str:
        with transaction(self.conn):
            pair = self._human_pair(research_id, table_id, link_id)
            decision = dict(decision="link", relation=relation, what_changed=what_changed, support_type=support_type, evidence=evidence, note=note)
            return self._human_write(research_id, pair, "human_edit", decision, based_on_revision_id, expected_version, idempotency_key, stale_revisions or {})

    def remove_link(self, research_id: str, table_id: str, link_id: str, note: str | None, based_on_revision_id: str,
                    expected_version: int, idempotency_key: str | None) -> str:
        with transaction(self.conn):
            pair = self._human_pair(research_id, table_id, link_id)
            decision = dict(decision="removed", relation=None, what_changed=None, support_type=None, evidence=[], note=note)
            return self._human_write(research_id, pair, "human_remove", decision, based_on_revision_id, expected_version, idempotency_key, {})
