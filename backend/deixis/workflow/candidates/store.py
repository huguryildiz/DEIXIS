"""Durable applied candidate results; no retrieval, model execution or quote location.

The shared source upsert can enrich other researches' library records. Only corpus
and selection isolation is promised here, not isolation of the shared library.
"""
from __future__ import annotations

import hashlib
import json
from collections.abc import Iterator
from contextlib import contextmanager
from datetime import datetime, timedelta
from typing import Any

from deixis.domain.contracts import GAP_KINDS
from deixis.domain.rules import RevisionConflict, check_expected_version
from deixis.storage.db import dumps, new_id, now, transaction
from deixis.workflow.candidates.hits import merge_and_cut
from deixis.workflow.candidates.status import STATUSES, SUPPORT_RELATIONS, derive_status
from deixis.workflow.store import ACTIVE_RUN_STATUSES, NotFound, Store

ORIGINS = ("report_gap", "owner_text")
VERSION_ORIGINS = ("model_decomposition", "human_edit")
ELEMENT_KINDS = ("mechanism", "condition", "outcome", "parameter")
OUTCOMES = ("running", "paused", "completed", "failed", "stopped")
TERMINAL_OUTCOMES = ("completed", "failed", "stopped")
QUERY_STATUSES = ("succeeded", "failed", "outcome_unknown")
READING_DEPTHS = ("abstract", "stored_passages", "metadata_only")
ASSESSMENT_STATES = ("pending", "assessed", "insufficient_access", "not_assessed_budget")
WORK_RELEVANCES = ("unrelated", "related", "uncertain")
RELATIONS = (*SUPPORT_RELATIONS, "no_match_in_supplied_text", "uncertain")
ALIGNMENTS = ("aligned", "different_conditions", "unclear")
EVIDENCE_KINDS = ("abstract", "passage")
CANDIDATE_TABLES = ("research_candidates", "candidate_versions", "claim_elements", "kill_searches",
                    "kill_search_queries", "kill_search_query_records", "kill_search_hits",
                    "claim_matrix_cells", "claim_matrix_evidence", "candidate_status_overrides")


class InvalidCandidateInput(Exception):
    """A refused caller shape or conflicting replay."""


def _digest(value: Any) -> str:
    return hashlib.sha256(json.dumps(value, sort_keys=True, separators=(",", ":"),
                                     ensure_ascii=False).encode("utf-8")).hexdigest()


def purge_candidates(conn, research_id: str) -> None:
    """Called only inside Store.purge_research's authorized transaction."""
    candidates = "SELECT id FROM research_candidates WHERE research_id = ?"
    versions = f"SELECT id FROM candidate_versions WHERE candidate_id IN ({candidates})"
    searches = f"SELECT id FROM kill_searches WHERE candidate_version_id IN ({versions})"
    for table, column, scope in (
        ("candidate_status_overrides", "candidate_version_id", versions),
        ("claim_matrix_evidence", "kill_search_id", searches),
        ("claim_matrix_cells", "kill_search_id", searches),
        ("kill_search_hits", "kill_search_id", searches),
        ("kill_search_query_records", "kill_search_id", searches),
        ("kill_search_queries", "kill_search_id", searches),
        ("kill_searches", "candidate_version_id", versions),
        ("claim_elements", "candidate_version_id", versions),
        ("candidate_versions", "candidate_id", candidates),
    ):
        conn.execute(f"DELETE FROM {table} WHERE {column} IN ({scope})", (research_id,))
    conn.execute("DELETE FROM research_candidates WHERE research_id = ?", (research_id,))


class CandidateStore:
    def __init__(self, store: Store):
        self.store = store
        self.conn = store.conn

    @contextmanager
    def _transaction(self) -> Iterator[None]:
        if not self.conn.in_transaction:
            with transaction(self.conn):
                yield
            return
        # A caught publication failure must not leave partial evidence in an outer transaction.
        savepoint = new_id("candidate_write")
        self.conn.execute(f"SAVEPOINT {savepoint}")
        try:
            yield
        except BaseException:
            self.conn.execute(f"ROLLBACK TO {savepoint}")
            self.conn.execute(f"RELEASE {savepoint}")
            raise
        else:
            self.conn.execute(f"RELEASE {savepoint}")

    def _insert(self, table: str, row: dict) -> None:
        self.conn.execute(f"INSERT INTO {table} ({', '.join(row)}) VALUES ({', '.join('?' * len(row))})",
                          tuple(row.values()))

    def _rows(self, sql: str, args=()) -> list[dict]:
        return [dict(row) for row in self.conn.execute(sql, args)]

    def _one(self, table: str, id_: str) -> dict:
        row = self.conn.execute(f"SELECT * FROM {table} WHERE id = ?", (id_,)).fetchone()
        if row is None:
            raise NotFound(id_)
        return dict(row)

    def _pair(self, research_id: str, candidate_id: str) -> dict:
        candidate = self.candidate(candidate_id)
        if candidate["research_id"] != research_id:
            raise NotFound(candidate_id)
        return candidate

    def _version_pair(self, research_id: str, version_id: str) -> tuple[dict, dict]:
        version = self.version(version_id)
        return self._pair(research_id, version["candidate_id"]), version

    def _event(self, candidate_id: str, change: str) -> None:
        self.store._event(self.candidate(candidate_id)["research_id"], "candidate_changed",
                          {"candidate_id": candidate_id, "change": change})

    def _search_candidate(self, search: dict) -> dict:
        return self.candidate(self.version(search["candidate_version_id"])["candidate_id"])

    @staticmethod
    def _nonterminal(search: dict) -> None:
        if search["outcome"] in TERMINAL_OUTCOMES:
            raise RevisionConflict("The kill-search is terminal")

    def _timestamp(self, table: str, column: str, value: str) -> str:
        ts = now()
        last = self.conn.execute(f"SELECT MAX(created_at) FROM {table} WHERE {column} = ?", (value,)).fetchone()[0]
        if last is not None and ts <= last:
            ts = (datetime.fromisoformat(last) + timedelta(milliseconds=1)).isoformat(timespec="milliseconds")
        return ts

    @staticmethod
    def _text(value, field: str, *, nullable=False, nonempty=False) -> None:
        if nullable and value is None:
            return
        if not isinstance(value, str) or (nonempty and not value.strip()):
            raise InvalidCandidateInput(f"{field} must be {'non-empty ' if nonempty else ''}text")

    def candidate(self, candidate_id: str) -> dict:
        row = self._one("research_candidates", candidate_id)
        row["origin_changed"] = bool(row["origin_gap_row_id"] and self.conn.execute(
            "SELECT 1 FROM research_candidates WHERE research_id = ? AND origin_gap_row_id = ?"
            " AND (created_at, id) > (?, ?) LIMIT 1",
            (row["research_id"], row["origin_gap_row_id"], row["created_at"], row["id"])).fetchone())
        return row

    def candidates(self, research_id: str, include_trashed=False) -> list[dict]:
        self.store.research(research_id)
        return [self.candidate(row["id"]) for row in self._rows(
            "SELECT id FROM research_candidates WHERE research_id = ?"
            + ("" if include_trashed else " AND trashed_at IS NULL"), (research_id,))]

    def version(self, candidate_version_id: str) -> dict:
        row = self._one("candidate_versions", candidate_version_id)
        row["elements"] = self._rows("SELECT * FROM claim_elements WHERE candidate_version_id = ? ORDER BY position",
                                     (candidate_version_id,))
        return row

    def versions(self, candidate_id: str) -> list[dict]:
        self.candidate(candidate_id)
        return [self.version(row["id"]) for row in self._rows(
            "SELECT id FROM candidate_versions WHERE candidate_id = ? ORDER BY version", (candidate_id,))]

    @staticmethod
    def _cell_text(value, options_json) -> str:
        if isinstance(value, str):
            return value
        if value is None:
            return ""
        if isinstance(value, dict):
            if isinstance(value.get("text"), str):
                return value["text"]
            if isinstance(value.get("number"), (int, float)):
                return " ".join(str(part) for part in (value["number"], value.get("unit")) if part is not None and part != "")
            if isinstance(value.get("answer"), str):
                return value["answer"]
            if isinstance(value.get("option_ids"), list):
                try:
                    options = json.loads(options_json) if options_json else []
                    labels = {option["id"]: option["label"] for option in options}
                except (TypeError, ValueError, KeyError):
                    labels = {}
                return ", ".join(str(labels.get(id_, id_)) for id_ in value["option_ids"])
        return dumps(value)

    def _basis_view(self, report_id: str, basis: dict) -> dict:
        view = {}
        for key in ("basis_cell_ids", "basis_passage_ids", "basis_claim_keys"):
            view[key] = []
            for id_ in basis.get(key, []):
                if key == "basis_cell_ids":
                    row = self.conn.execute(
                        "SELECT r.value_json, cr.options_json FROM evidence_cells c"
                        " JOIN cell_revisions r ON r.id = c.current_revision_id"
                        " JOIN table_columns tc ON tc.id = c.column_id"
                        " LEFT JOIN column_revisions cr ON cr.column_id = tc.id AND cr.revision = tc.current_revision"
                        " WHERE c.id = ?", (id_,)).fetchone()
                    if row is not None:
                        try:
                            value = json.loads(row["value_json"]) if row["value_json"] is not None else None
                        except (TypeError, ValueError):
                            value = row["value_json"]
                        item = {"id": id_, "text": self._cell_text(value, row["options_json"])}
                elif key == "basis_passage_ids":
                    row = self.conn.execute("SELECT text, source_version_id FROM passages WHERE id = ?", (id_,)).fetchone()
                    if row is not None:
                        item = {"id": id_, **dict(row)}
                else:
                    matches = self.conn.execute(
                        "SELECT COALESCE(v.text, c.text) AS text FROM report_claims c"
                        " JOIN report_sections s ON s.id = c.report_section_id"
                        " LEFT JOIN report_claim_revisions v ON v.id = c.current_revision_id"
                        " WHERE s.report_id = ? AND c.claim_key = ?", (report_id, id_)).fetchall()
                    # Claim keys are section-scoped; an ambiguous report-level key cannot name one visible claim.
                    row = matches[0] if len(matches) == 1 else None
                    if row is not None:
                        item = {"id": id_, "text": row["text"]}
                view[key].append(item if row is not None else {"id": id_, "missing": True})
        return view

    def open_from_gap(self, research_id: str, report_id: str, gap_row_id: str) -> dict:
        with self._transaction():
            row = self.conn.execute(
                "SELECT g.* FROM report_gaps g JOIN reports r ON r.id = g.report_id"
                " WHERE g.id = ? AND g.report_id = ? AND r.research_id = ?",
                (gap_row_id, report_id, research_id)).fetchone()
            if row is None:
                raise NotFound(gap_row_id)
            if row["kind"] not in GAP_KINDS:
                raise InvalidCandidateInput("Unknown gap kind")
            basis = json.loads(row["basis_json"])
            fingerprint = _digest({"kind": row["kind"], "text": row["text"], "basis": basis})
            existing = self.conn.execute(
                "SELECT id FROM research_candidates WHERE research_id = ? AND origin_gap_row_id = ? AND origin_fingerprint = ?",
                (research_id, gap_row_id, fingerprint)).fetchone()
            if existing:
                return self.candidate(existing["id"])
            id_ = new_id("rcd")
            self._insert("research_candidates", {
                "id": id_, "research_id": research_id, "origin": "report_gap", "origin_report_id": report_id,
                "origin_gap_row_id": gap_row_id, "gap_kind": row["kind"], "origin_text": row["text"],
                "origin_basis_json": row["basis_json"], "origin_basis_view_json": dumps(self._basis_view(report_id, basis)),
                "origin_provenance_json": row["provenance_json"], "origin_fingerprint": fingerprint,
                "created_at": self._timestamp("research_candidates", "research_id", research_id)})
            self._event(id_, "opened")
            return self.candidate(id_)

    def open_from_owner_text(self, research_id: str, text: str, idempotency_key=None) -> dict:
        with self._transaction():
            self.store.research(research_id)
            self._text(text, "text", nonempty=True)
            text = text.strip()
            if len(text) > 2000:
                raise InvalidCandidateInput("Owner text exceeds 2000 characters")
            if idempotency_key is not None:
                row = self.conn.execute("SELECT * FROM research_candidates WHERE idempotency_key = ?", (idempotency_key,)).fetchone()
                if row:
                    if row["research_id"] != research_id or row["origin_text"] != text or row["origin"] != "owner_text":
                        raise InvalidCandidateInput("Owner-text idempotency key content mismatch")
                    return self.candidate(row["id"])
            id_ = new_id("rcd")
            self._insert("research_candidates", {"id": id_, "research_id": research_id, "origin": "owner_text",
                         "origin_text": text, "origin_basis_json": "{}", "origin_basis_view_json": "{}",
                         "origin_provenance_json": "{}", "idempotency_key": idempotency_key,
                         "created_at": self._timestamp("research_candidates", "research_id", research_id)})
            self._event(id_, "opened")
            return self.candidate(id_)

    def add_version(self, research_id, candidate_id, *, claim_statement, conditions, elements,
                    nearest_simple_explanation, critical_assumption, validation_plan, origin,
                    step_input_id, expected_version, idempotency_key=None) -> dict:
        with self._transaction():
            candidate = self._pair(research_id, candidate_id)
            self._text(claim_statement, "claim_statement", nonempty=True)
            self._text(nearest_simple_explanation, "nearest_simple_explanation", nullable=True)
            self._text(critical_assumption, "critical_assumption")
            self._text(validation_plan, "validation_plan")
            if not isinstance(conditions, list) or any(not isinstance(c, str) or not c.strip() for c in conditions):
                raise InvalidCandidateInput("conditions must be a list of non-empty strings")
            if not isinstance(elements, list) or not 2 <= len(elements) <= 6:
                raise InvalidCandidateInput("A version needs two to six elements")
            for element in elements:
                if not isinstance(element, dict) or element.get("kind") not in ELEMENT_KINDS:
                    raise InvalidCandidateInput("Unknown element kind")
                self._text(element.get("text"), "element text", nonempty=True)
            if origin not in VERSION_ORIGINS or ((origin == "model_decomposition") != (step_input_id is not None)):
                raise InvalidCandidateInput("Version origin and step input mismatch")
            if step_input_id is not None:
                self._text(step_input_id, "step_input_id", nonempty=True)
                if not self.conn.execute("SELECT 1 FROM step_inputs WHERE id = ?", (step_input_id,)).fetchone():
                    raise InvalidCandidateInput("The decomposition step input is missing")
            content = {"claim_statement": claim_statement, "conditions_json": dumps(conditions),
                       "nearest_simple_explanation": nearest_simple_explanation, "critical_assumption": critical_assumption,
                       "validation_plan": validation_plan, "origin": origin, "step_input_id": step_input_id}
            element_content = [{"text": e["text"], "kind": e["kind"]} for e in elements]
            if idempotency_key is not None:
                replay = self.conn.execute("SELECT id FROM candidate_versions WHERE idempotency_key = ?", (idempotency_key,)).fetchone()
                if replay:
                    old = self.version(replay["id"])
                    if (old["candidate_id"] != candidate_id or any(old[k] != v for k, v in content.items())
                            or [{"text": e["text"], "kind": e["kind"]} for e in old["elements"]] != element_content):
                        raise InvalidCandidateInput("Version idempotency key content mismatch")
                    return old
            if candidate["trashed_at"] is not None:
                raise InvalidCandidateInput("A trashed candidate refuses new versions")
            check_expected_version(expected_version, candidate["current_version"])
            id_, number = new_id("clv"), candidate["current_version"] + 1
            self._insert("candidate_versions", {"id": id_, "candidate_id": candidate_id, "version": number,
                         **content, "idempotency_key": idempotency_key,
                         "created_at": self._timestamp("candidate_versions", "candidate_id", candidate_id)})
            for position, element in enumerate(element_content, 1):
                self._insert("claim_elements", {"id": new_id("ele"), "candidate_version_id": id_, "position": position, **element})
            self.conn.execute("UPDATE research_candidates SET current_version = ? WHERE id = ?", (number, candidate_id))
            self._event(candidate_id, "version_added")
            return self.version(id_)

    def _trash(self, research_id, candidate_id, trashed):
        with self._transaction():
            candidate = self._pair(research_id, candidate_id)
            if self.conn.execute(
                f"SELECT 1 FROM runs WHERE research_id = ? AND kind IN ('claim_decomposition', 'kill_search')"
                f" AND status IN ({', '.join('?' * len(ACTIVE_RUN_STATUSES))})"
                " AND json_extract(target_json, '$.candidate_id') = ? LIMIT 1",
                (research_id, *ACTIVE_RUN_STATUSES, candidate_id)).fetchone():
                raise RevisionConflict("Active candidate runs prevent trash or restore")
            if (candidate["trashed_at"] is not None) != trashed:
                self.conn.execute("UPDATE research_candidates SET trashed_at = ? WHERE id = ?",
                                  (now() if trashed else None, candidate_id))
                self._event(candidate_id, "trashed" if trashed else "restored")
            return self.candidate(candidate_id)

    def trash_candidate(self, research_id, candidate_id):
        return self._trash(research_id, candidate_id, True)

    def restore_candidate(self, research_id, candidate_id):
        return self._trash(research_id, candidate_id, False)

    def start_kill_search(self, research_id, candidate_version_id, run_id, *, query_block,
                          rendered_queries, skipped_terms, selection) -> dict:
        with self._transaction():
            candidate, _ = self._version_pair(research_id, candidate_version_id)
            run = self.store.run(run_id)
            if run["kind"] != "kill_search" or run["research_id"] != research_id:
                raise InvalidCandidateInput("Kill-search run kind or research mismatch")
            frozen = {"candidate_version_id": candidate_version_id, "query_block_json": dumps(query_block),
                      "rendered_queries_json": dumps(rendered_queries), "skipped_terms_json": dumps(skipped_terms),
                      "selection_json": dumps(selection)}
            old = self.conn.execute("SELECT * FROM kill_searches WHERE run_id = ?", (run_id,)).fetchone()
            if old:
                if any(old[k] != v for k, v in frozen.items()):
                    raise InvalidCandidateInput("Kill-search replay content mismatch")
                return dict(old)
            id_ = new_id("kls")
            self._insert("kill_searches", {"id": id_, "run_id": run_id, **frozen, "outcome": "running",
                         "created_at": self._timestamp("kill_searches", "candidate_version_id", candidate_version_id)})
            self._event(candidate["id"], "search_started")
            return self.kill_search(id_)

    def kill_search(self, kill_search_id) -> dict:
        return self._one("kill_searches", kill_search_id)

    def searches(self, candidate_version_id) -> list[dict]:
        self.version(candidate_version_id)
        return self._rows("SELECT * FROM kill_searches WHERE candidate_version_id = ? ORDER BY created_at, id",
                          (candidate_version_id,))

    def queries(self, kill_search_id) -> list[dict]:
        self.kill_search(kill_search_id)
        return self._rows("SELECT * FROM kill_search_queries WHERE kill_search_id = ? ORDER BY position", (kill_search_id,))

    def _query_records(self, kill_search_id, position) -> list[dict]:
        return self._rows("SELECT provider, source_version_id, work_id FROM kill_search_query_records"
                          " WHERE kill_search_id = ? AND position = ? ORDER BY rank", (kill_search_id, position))

    def query_records(self, kill_search_id) -> list[list[dict]]:
        return [self._query_records(kill_search_id, q["position"]) for q in self.queries(kill_search_id)
                if q["status"] == "succeeded"]

    def record_query(self, kill_search_id, *, position, provider, query_text, status, records,
                     error_code=None, raw_payload_path=None, payload_sha256=None, step_id=None) -> list[dict]:
        with self._transaction():
            search = self.kill_search(kill_search_id)
            self._nonterminal(search)
            if (not isinstance(position, int) or isinstance(position, bool) or position < 1
                    or status not in QUERY_STATUSES or not isinstance(records, list)
                    or (status != "succeeded" and records)):
                raise InvalidCandidateInput("Query position, status or record shape mismatch")
            self._text(provider, "provider", nonempty=True)
            self._text(query_text, "query_text", nonempty=True)
            digest = _digest([{key: getattr(r, key) for key in ("provider_record_id", "title", "doi", "abstract")} for r in records])
            row = {"kill_search_id": kill_search_id, "position": position, "provider": provider, "query_text": query_text,
                   "status": status, "record_count": len(records), "error_code": error_code,
                   "raw_payload_path": raw_payload_path, "payload_sha256": payload_sha256,
                   "step_id": step_id, "records_sha256": digest}
            old = self.conn.execute("SELECT * FROM kill_search_queries WHERE kill_search_id = ? AND position = ?",
                                    (kill_search_id, position)).fetchone()
            if old:
                if any(old[k] != v for k, v in row.items()):
                    raise InvalidCandidateInput("Query replay content mismatch")
                return self._query_records(kill_search_id, position)
            if search["hits_recorded"]:
                raise RevisionConflict("Queries are frozen after recording the merge")
            self._insert("kill_search_queries", row)
            for rank, record in enumerate(records, 1):
                svid, _ = self.store.upsert_provider_source(provider, record, raw_payload_path)
                work_id = self.conn.execute("SELECT work_id FROM source_versions WHERE id = ?", (svid,)).fetchone()[0]
                self._insert("kill_search_query_records", {"kill_search_id": kill_search_id, "position": position,
                             "rank": rank, "provider": provider, "source_version_id": svid, "work_id": work_id})
            self._event(self._search_candidate(search)["id"], "query_recorded")
            return self._query_records(kill_search_id, position)

    def hits(self, kill_search_id) -> list[dict]:
        self.kill_search(kill_search_id)
        return self._rows("SELECT * FROM kill_search_hits WHERE kill_search_id = ? ORDER BY rank_key", (kill_search_id,))

    def record_hits(self, kill_search_id, merged, reading_depths) -> None:
        with self._transaction():
            search = self.kill_search(kill_search_id)
            self._nonterminal(search)
            if search["hits_recorded"]:
                raise RevisionConflict("Hits have already been recorded")
            # Persisted query records are the authority for counts and merged identities.
            try:
                expected = merge_and_cut(self.query_records(kill_search_id), keep=merged["kept_count"])
            except (KeyError, TypeError, ValueError) as exc:
                raise InvalidCandidateInput("Invalid merged records") from exc
            if merged != expected:
                raise InvalidCandidateInput("Merge differs from the persisted query records")
            for record in merged["kept"]:
                if reading_depths.get(record["source_version_id"]) not in READING_DEPTHS:
                    raise InvalidCandidateInput("Every kept source needs a reading depth")
            for kept, records in ((1, merged["kept"]), (0, merged["cut"])):
                for record in records:
                    self._insert("kill_search_hits", {"kill_search_id": kill_search_id, **{k: record[k] for k in
                                 ("source_version_id", "work_id", "rank_key")}, "kept": kept,
                                 "cut_reason": None if kept else "rank_cut",
                                 "reading_depth": reading_depths[record["source_version_id"]] if kept else None,
                                 "assessment_state": "pending" if kept else None})
            self.conn.execute("UPDATE kill_searches SET found = ?, kept = ?, rank_cut = ?, duplicates = ?, hits_recorded = 1 WHERE id = ?",
                              (merged["found"], merged["kept_count"], merged["rank_cut"], merged["duplicates"], kill_search_id))
            self._event(self._search_candidate(search)["id"], "hits_recorded")

    def cells(self, kill_search_id) -> list[dict]:
        self.kill_search(kill_search_id)
        return self._rows("SELECT c.* FROM claim_matrix_cells c JOIN claim_elements e ON e.id = c.element_id"
                          " WHERE c.kill_search_id = ? ORDER BY c.source_version_id, e.position", (kill_search_id,))

    def evidence(self, kill_search_id) -> list[dict]:
        self.kill_search(kill_search_id)
        return self._rows("SELECT * FROM claim_matrix_evidence WHERE kill_search_id = ? ORDER BY id", (kill_search_id,))

    def _quotes(self, quotes, source_version_id) -> list[dict]:
        if not isinstance(quotes, (list, tuple)):
            raise InvalidCandidateInput("Quotes must be a list")
        result = []
        for quote in quotes:
            if not isinstance(quote, dict) or quote.get("evidence_kind") not in EVIDENCE_KINDS:
                raise InvalidCandidateInput("Unknown evidence kind")
            self._text(quote.get("quote"), "quote", nonempty=True)
            passage_id = quote.get("passage_id")
            if (quote["evidence_kind"] == "passage") != (passage_id is not None):
                raise InvalidCandidateInput("Passage evidence needs a passage id; abstract evidence has none")
            if passage_id is not None and not self.conn.execute(
                "SELECT 1 FROM passages WHERE id = ? AND source_version_id = ?", (passage_id, source_version_id)).fetchone():
                raise InvalidCandidateInput("The passage belongs to another source or is missing")
            result.append({"evidence_kind": quote["evidence_kind"], "passage_id": passage_id, "quote": quote["quote"]})
        return result

    def _assessment_content(self, search, source_version_id, assessment_state, work_relevance,
                            states_whole_claim, note, step_input_id, cells, whole_claim_quotes) -> dict:
        if assessment_state not in ASSESSMENT_STATES[1:] or not isinstance(states_whole_claim, bool):
            raise InvalidCandidateInput("Unknown assessment state or non-boolean whole-claim flag")
        if assessment_state != "assessed":
            if cells or whole_claim_quotes or work_relevance is not None or step_input_id is not None or note is not None or states_whole_claim:
                raise InvalidCandidateInput("An unread hit has no assessment fields, cells or quotes")
            return {"assessment_state": assessment_state, "work_relevance": None, "states_whole_claim": None,
                    "note": None, "step_input_id": None, "cells": [], "whole_claim_quotes": []}
        if work_relevance not in WORK_RELEVANCES:
            raise InvalidCandidateInput("Unknown work relevance")
        self._text(step_input_id, "step_input_id", nonempty=True)
        self._text(note, "note", nullable=True)
        if not self.conn.execute("SELECT 1 FROM step_inputs WHERE id = ?", (step_input_id,)).fetchone():
            raise InvalidCandidateInput("The assessment step input is missing")
        elements = {e["id"] for e in self.version(search["candidate_version_id"])["elements"]}
        if not isinstance(cells, (list, tuple)) or any(not isinstance(c, dict) for c in cells):
            raise InvalidCandidateInput("Cells must be a list of objects")
        ids = [c.get("element_id") for c in cells]
        if any(not isinstance(id_, str) for id_ in ids) or len(ids) != len(elements) or set(ids) != elements:
            raise InvalidCandidateInput("Exactly one cell for every version element is required")
        normalized = []
        for cell in cells:
            relation, alignment = cell.get("relation"), cell.get("condition_alignment")
            if relation not in RELATIONS or (alignment is not None and alignment not in ALIGNMENTS):
                raise InvalidCandidateInput("Unknown relation or condition alignment")
            if (relation in SUPPORT_RELATIONS and alignment is None) or (relation == "no_match_in_supplied_text" and alignment is not None):
                raise InvalidCandidateInput("Relation and condition alignment mismatch")
            quotes = self._quotes(cell.get("quotes", []), source_version_id)
            if relation in SUPPORT_RELATIONS and not quotes:
                raise InvalidCandidateInput("A support cell needs a quote")
            self._text(cell.get("note"), "cell note", nullable=True)
            normalized.append({"element_id": cell["element_id"], "relation": relation,
                               "condition_alignment": alignment, "note": cell.get("note"), "quotes": quotes})
        relations = [c["relation"] for c in normalized]
        if ((work_relevance == "unrelated" and any(r != "no_match_in_supplied_text" for r in relations))
                or (work_relevance == "related" and not any(r in SUPPORT_RELATIONS for r in relations))
                or (work_relevance == "uncertain" and "uncertain" not in relations)):
            raise InvalidCandidateInput("Relevance and cell relations mismatch")
        whole = self._quotes(whole_claim_quotes, source_version_id)
        if (states_whole_claim and (not whole or work_relevance != "related")) or (not states_whole_claim and whole):
            raise InvalidCandidateInput("Whole-claim flag needs related relevance and a whole-claim quote")
        return {"assessment_state": assessment_state, "work_relevance": work_relevance,
                "states_whole_claim": int(states_whole_claim), "note": note, "step_input_id": step_input_id,
                "cells": sorted(normalized, key=lambda c: c["element_id"]), "whole_claim_quotes": whole}

    def _assessment(self, kill_search_id, source_version_id) -> dict:
        hit = next((h for h in self.hits(kill_search_id) if h["source_version_id"] == source_version_id), None)
        if hit is None or not hit["kept"]:
            raise NotFound(source_version_id)
        evidence = [e for e in self.evidence(kill_search_id) if e["source_version_id"] == source_version_id]
        quote_keys = ("evidence_kind", "passage_id", "quote")
        cells = [{**{k: c[k] for k in ("element_id", "relation", "condition_alignment", "note")},
                  "quotes": [{k: e[k] for k in quote_keys} for e in evidence if e["matrix_cell_id"] == c["id"]]}
                 for c in self.cells(kill_search_id) if c["source_version_id"] == source_version_id]
        return {**{k: hit[k] for k in ("assessment_state", "work_relevance", "states_whole_claim", "note", "step_input_id")},
                "cells": sorted(cells, key=lambda c: c["element_id"]),
                "whole_claim_quotes": [{k: e[k] for k in quote_keys} for e in evidence if e["element_id"] is None]}

    @staticmethod
    def _comparable_assessment(content):
        # Evidence row ids do not encode insertion order; quote order has no publication meaning.
        result = dict(content)
        result["cells"] = [dict(c, quotes=sorted(c["quotes"], key=dumps)) for c in content["cells"]]
        result["whole_claim_quotes"] = sorted(content["whole_claim_quotes"], key=dumps)
        return result

    def publish_assessment(self, kill_search_id, source_version_id, *, assessment_state, work_relevance=None,
                           states_whole_claim=False, note=None, step_input_id=None, cells=(), whole_claim_quotes=()) -> dict:
        with self._transaction():
            search = self.kill_search(kill_search_id)
            self._nonterminal(search)
            old = self._assessment(kill_search_id, source_version_id)
            if old["assessment_state"] != "pending":
                try:
                    requested = self._assessment_content(search, source_version_id, assessment_state, work_relevance,
                                                         states_whole_claim, note, step_input_id, cells, whole_claim_quotes)
                except InvalidCandidateInput as exc:
                    raise RevisionConflict("The hit has already been published") from exc
                if self._comparable_assessment(requested) == self._comparable_assessment(old):
                    return old
                raise RevisionConflict("The hit has already been published")
            content = self._assessment_content(search, source_version_id, assessment_state, work_relevance,
                                               states_whole_claim, note, step_input_id, cells, whole_claim_quotes)
            fields = ("assessment_state", "work_relevance", "states_whole_claim", "note", "step_input_id")
            self.conn.execute(f"UPDATE kill_search_hits SET {', '.join(k + ' = ?' for k in fields)}"
                              " WHERE kill_search_id = ? AND source_version_id = ?",
                              (*[content[k] for k in fields], kill_search_id, source_version_id))
            for cell in content["cells"]:
                cell_id = new_id("cmx")
                self._insert("claim_matrix_cells", {"id": cell_id, "kill_search_id": kill_search_id,
                             "source_version_id": source_version_id, **{k: cell[k] for k in
                             ("element_id", "relation", "condition_alignment", "note")}})
                for quote in cell["quotes"]:
                    self._insert("claim_matrix_evidence", {"id": new_id("cmx"), "kill_search_id": kill_search_id,
                                 "source_version_id": source_version_id, "element_id": cell["element_id"],
                                 "matrix_cell_id": cell_id, **quote})
            for quote in content["whole_claim_quotes"]:
                self._insert("claim_matrix_evidence", {"id": new_id("cmx"), "kill_search_id": kill_search_id,
                             "source_version_id": source_version_id, "element_id": None, "matrix_cell_id": None, **quote})
            self._event(self._search_candidate(search)["id"], "assessment_published")
            return self._assessment(kill_search_id, source_version_id)

    def finish_kill_search(self, kill_search_id, outcome):
        if outcome not in TERMINAL_OUTCOMES:
            raise InvalidCandidateInput("finish needs a terminal outcome")
        return self._set_state(kill_search_id, outcome)

    def set_kill_search_state(self, kill_search_id, outcome):
        if outcome not in ("running", "paused"):
            raise InvalidCandidateInput("state must be running or paused")
        return self._set_state(kill_search_id, outcome)

    def _set_state(self, kill_search_id, outcome):
        with self._transaction():
            search = self.kill_search(kill_search_id)
            if search["outcome"] == outcome:
                return search
            self._nonterminal(search)
            if outcome == "completed" and not search["hits_recorded"] and self.conn.execute(
                "SELECT 1 FROM kill_search_queries WHERE kill_search_id = ?"
                " AND status = 'succeeded' AND record_count > 0 LIMIT 1", (kill_search_id,),
            ).fetchone():
                raise RevisionConflict("Record the query-result merge before completing kill-search")
            self.conn.execute("UPDATE kill_searches SET outcome = ? WHERE id = ?", (outcome, kill_search_id))
            self._event(self._search_candidate(search)["id"], "search_state_changed")
            return self.kill_search(kill_search_id)

    def record_owner_decision(self, research_id, candidate_version_id, status, reason) -> dict:
        with self._transaction():
            candidate, _ = self._version_pair(research_id, candidate_version_id)
            if status not in STATUSES:
                raise InvalidCandidateInput("Unknown candidate status")
            self._text(reason, "reason", nonempty=True)
            id_ = new_id("cmx")
            self._insert("candidate_status_overrides", {"id": id_, "candidate_version_id": candidate_version_id,
                         "status": status, "reason": reason,
                         "created_at": self._timestamp("candidate_status_overrides", "candidate_version_id", candidate_version_id)})
            self._event(candidate["id"], "owner_decision_added")
            return self._one("candidate_status_overrides", id_)

    def overrides(self, candidate_version_id) -> list[dict]:
        self.version(candidate_version_id)
        return self._rows("SELECT * FROM candidate_status_overrides WHERE candidate_version_id = ? ORDER BY created_at, id",
                          (candidate_version_id,))

    def _derive(self, search, element_ids) -> dict:
        if search is None:
            return derive_status(None, [], [], [], element_ids)
        hits = self.hits(search["id"])
        counts = {row["source_version_id"]: row["count"] for row in self._rows(
            "SELECT source_version_id, COUNT(*) AS count FROM claim_matrix_evidence"
            " WHERE kill_search_id = ? AND element_id IS NULL GROUP BY source_version_id", (search["id"],))}
        for hit in hits:
            hit["whole_claim_evidence_count"] = counts.get(hit["source_version_id"], 0)
        search = search | {"query_record_count": self.conn.execute(
            "SELECT COUNT(*) FROM kill_search_query_records WHERE kill_search_id = ?", (search["id"],),
        ).fetchone()[0]}
        return derive_status(search, self.queries(search["id"]), hits, self.cells(search["id"]), element_ids)

    def candidate_status(self, candidate_version_id) -> dict:
        element_ids = [e["id"] for e in self.version(candidate_version_id)["elements"]]
        searches = self.searches(candidate_version_id)
        latest = searches[-1] if searches else None
        previous = next((s for s in reversed(searches[:-1]) if s["outcome"] == "completed"), None)
        owner = self.overrides(candidate_version_id)
        return {"computed": self._derive(latest, element_ids),
                "previous": self._derive(previous, element_ids) if previous else None,
                "owner": owner[-1] if owner else None}
