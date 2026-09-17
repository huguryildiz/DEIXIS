"""Persistence operations for researches, runs, sources, selections and answers.

All writes happen in short synchronous transactions on one connection; callers
never await inside a transaction, so the API and worker can share the connection
on the event-loop thread. UI-visible events are written in the same transaction
as the state they describe.
"""

from __future__ import annotations

import hashlib
import json
import re
import sqlite3
from typing import Any

from deixis.domain.rules import RevisionConflict, check_expected_version
from deixis.storage.db import dumps, new_id, now, row_dict, transaction
from deixis.workflow.source_keys import key_stem, suffixes

ACTIVE_RUN_STATUSES = ("queued", "running", "pause_requested")
# What became of a passage's file since the passage was stored (D45), over `passages p LEFT JOIN source_assets a`.
EVIDENCE_STATUS_SQL = (
    "CASE WHEN a.id IS NULL THEN 'current'"
    " WHEN a.removed_at IS NOT NULL THEN CASE a.removal_reason WHEN 'replaced' THEN 'pdf_replaced' ELSE 'pdf_removed' END"
    " WHEN p.extraction_version IS NOT a.extraction_version THEN 'text_superseded' ELSE 'current' END"
)
MIN_TITLE_KEY_CHARS = 12  # shorter normalized titles ("Introduction") say too little to suspect a duplicate
ARXIV_DOI_PREFIX = "10.48550/arxiv."  # arXiv's DataCite DOI names a preprint with all its versions (D46)
# Step kinds whose output the research view carries: small counts the transcript reports, not model prose.
STEP_OUTPUT_KINDS = ("fetch_pdf", "pdf_other_copy", "ocr_pages", "ocr_merge")
STEP_OUTPUT_KEYS = ("semantic_retrieval", "source_similarity")


def title_key(title: str | None) -> str:
    return re.sub(r"\W+", " ", (title or "").casefold()).strip()


def is_preprint(source: dict[str, Any]) -> bool:
    label = source.get("version_label") or ""
    return (source.get("doi") or "").startswith(ARXIV_DOI_PREFIX) or label == "submittedVersion" or label.startswith("arXiv")


def is_published(source: dict[str, Any]) -> bool:
    """A record under its own registered DOI that is not a preprint's (D48)."""
    return bool(source.get("doi")) and not is_preprint(source)


def _surnames(authors: list[str]) -> list[str]:
    return [re.sub(r"\W+", "", name.split()[-1].casefold()) for name in authors if name.split()]


def same_publication(a: dict[str, Any], b: dict[str, Any], basis: str) -> bool:
    """A preprint and a published record of one paper (D48): the preprint names the published DOI, or the two share the
    title, the first author and at least half of the shorter author list. Two published records never qualify."""
    if is_preprint(a) == is_preprint(b) or not (is_published(a) or is_published(b)):
        return False
    if basis == "published_doi":
        return True
    first, second = _surnames(a["authors"]), _surnames(b["authors"])
    if not first or not second or first[0] != second[0]:
        return False
    return len(set(first) & set(second)) * 2 >= min(len(set(first)), len(set(second)))


class NotFound(Exception):
    pass


class PdfInUse(Exception):
    """A source version has at most one PDF in use; another file replaces it (D45)."""


class RunInProgress(Exception):
    """A research using the source has a queued, running or pause-requested run (D45)."""


class SameFile(Exception):
    """A PDF can only be replaced by a different file (D45)."""


class NotASource(Exception):
    """A source version that was never a source of the research (D50); the API answers 422."""


class Store:
    def __init__(self, conn: sqlite3.Connection):
        self.conn = conn

    # ---- events -----------------------------------------------------------------
    def _event(self, research_id: str, type_: str, payload: dict[str, Any], run_id: str | None = None) -> int:
        cur = self.conn.execute(
            "INSERT INTO events (research_id, run_id, type, payload_json, created_at) VALUES (?, ?, ?, ?, ?)",
            (research_id, run_id, type_, dumps(payload), now()),
        )
        return int(cur.lastrowid)

    def events_after(self, research_id: str, after_id: int, limit: int = 200) -> list[dict[str, Any]]:
        rows = self.conn.execute(
            "SELECT * FROM events WHERE research_id = ? AND id > ? ORDER BY id LIMIT ?",
            (research_id, after_id, limit),
        ).fetchall()
        return [{**dict(r), "payload": json.loads(r["payload_json"])} for r in rows]

    # ---- researches ----------------------------------------------------------------
    def create_research(
        self,
        question: str,
        source_scope: str,
        effort: str,
        providers: list[str],
        model_connection: str,
        requested_model: str | None,
        language_hint: str | None,
        reasoning_effort: str | None = None,
        literature_model: str | None = None,
        literature_reasoning_effort: str | None = None,
        review_mode: str = "default",
        review_model: str | None = None,
        review_reasoning_effort: str | None = None,
        literature_connection: str | None = None,
        review_connection: str | None = None,
    ) -> str:
        rid, ts = new_id("res"), now()
        title = question.strip().splitlines()[0][:160]
        with transaction(self.conn):
            self.conn.execute(
                "INSERT INTO researches (id, title, created_at, updated_at) VALUES (?, ?, ?, ?)", (rid, title, ts, ts)
            )
            self.conn.execute(
                "INSERT INTO scope_revisions (research_id, revision, question, language_hint, source_scope, providers_json,"
                " effort, model_connection, requested_model, reasoning_effort, literature_model, literature_reasoning_effort,"
                " review_mode, review_model, review_reasoning_effort, literature_connection, review_connection, created_at)"
                " VALUES (?, 1, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)",
                (rid, question.strip(), language_hint, source_scope, dumps(providers), effort, model_connection, requested_model,
                 reasoning_effort, literature_model, literature_reasoning_effort, review_mode, review_model, review_reasoning_effort,
                 literature_connection, review_connection, ts),
            )
            self._event(rid, "research_created", {"scope_revision": 1})
        return rid

    def research(self, research_id: str) -> dict[str, Any]:
        row = self.conn.execute("SELECT * FROM researches WHERE id = ? AND trashed_at IS NULL", (research_id,)).fetchone()
        if row is None:
            raise NotFound(research_id)
        return dict(row)

    def trash_research(self, research_id: str) -> None:
        """Move a research to trash; active work must be finished or cancelled first."""
        with transaction(self.conn):
            self.research(research_id)
            active = self.conn.execute(
                "SELECT 1 FROM runs WHERE research_id = ? AND status IN ('queued', 'running', 'pause_requested') LIMIT 1",
                (research_id,),
            ).fetchone()
            if active:
                raise RevisionConflict("Cancel or finish active runs before trashing this research")
            self.conn.execute("UPDATE researches SET trashed_at = ? WHERE id = ?", (now(), research_id))

    def trash(self) -> dict[str, list[dict[str, Any]]]:
        """What the Trash page lists, by kind, each with what it holds (D50).

        A trashed research's tables and removed sources are not listed on their own: they go and come back with it.
        """
        researches = [dict(r) for r in self.conn.execute(
            "SELECT id, title, trashed_at FROM researches WHERE trashed_at IS NOT NULL ORDER BY trashed_at DESC"
        )]
        tables = [dict(r) for r in self.conn.execute(
            "SELECT t.id, t.title, t.research_id, r.title AS research_title, t.version, t.trashed_at,"
            " (SELECT COUNT(*) FROM table_rows w WHERE w.table_id = t.id AND w.removed_at IS NULL) AS rows,"
            " (SELECT COUNT(*) FROM table_columns c WHERE c.table_id = t.id AND c.removed_at IS NULL) AS columns,"
            " (SELECT COUNT(*) FROM evidence_cells c WHERE c.table_id = t.id AND c.current_revision_id IS NOT NULL) AS cells,"
            " (SELECT COUNT(*) FROM cell_revisions v JOIN evidence_cells c ON c.id = v.cell_id"
            "  WHERE c.table_id = t.id AND v.kind IN ('human_edit', 'accept_proposal')) AS human_edits"
            " FROM evidence_tables t JOIN researches r ON r.id = t.research_id"
            " WHERE t.trashed_at IS NOT NULL AND r.trashed_at IS NULL ORDER BY t.trashed_at DESC"
        )]
        sources = [dict(r) for r in self.conn.execute(
            "SELECT m.source_version_id, v.work_id, v.title, v.version_label, v.year, m.research_id, r.title AS research_title,"
            " m.removed_at, m.removal_note, m.found_again_at,"
            " (SELECT COUNT(*) FROM evidence_links l JOIN claims c ON c.id = l.claim_id JOIN answers a ON a.id = c.answer_id"
            "  WHERE a.research_id = m.research_id AND l.source_version_id = m.source_version_id) AS quotes,"
            " (SELECT COUNT(*) FROM evidence_cells c JOIN evidence_tables t ON t.id = c.table_id"
            "  WHERE t.research_id = m.research_id AND c.source_version_id = m.source_version_id AND c.current_revision_id IS NOT NULL) AS cells"
            " FROM corpus_memberships m JOIN source_versions v ON v.id = m.source_version_id JOIN researches r ON r.id = m.research_id"
            " WHERE m.removed_at IS NOT NULL AND r.trashed_at IS NULL ORDER BY m.removed_at DESC, v.title"
        )]
        templates = [dict(r) for r in self.conn.execute(
            "SELECT id, name, trashed_at, json_array_length(columns_json) AS columns FROM table_templates"
            " WHERE trashed_at IS NOT NULL ORDER BY trashed_at DESC"
        )]
        return {"researches": researches, "tables": tables, "sources": sources, "templates": templates}

    def restore_research(self, research_id: str) -> None:
        with transaction(self.conn):
            result = self.conn.execute(
                "UPDATE researches SET trashed_at = NULL WHERE id = ? AND trashed_at IS NOT NULL", (research_id,)
            )
            if not result.rowcount:
                raise NotFound(research_id)

    def purge_research(self, research_id: str) -> tuple[list[str], list[str]]:
        """Delete a trashed research and unshared source records; return orphaned file paths for cleanup."""
        with transaction(self.conn):
            row = self.conn.execute("SELECT trashed_at FROM researches WHERE id = ?", (research_id,)).fetchone()
            if row is None or row["trashed_at"] is None:
                raise NotFound(research_id)
            active = self.conn.execute(
                "SELECT 1 FROM runs WHERE research_id = ? AND status IN ('queued', 'running', 'pause_requested') LIMIT 1",
                (research_id,),
            ).fetchone()
            if active:
                raise RevisionConflict("Active runs prevent permanent deletion")
            source_ids = [r[0] for r in self.conn.execute(
                "SELECT source_version_id FROM corpus_memberships WHERE research_id = ? UNION "
                "SELECT source_version_id FROM candidates WHERE research_id = ?", (research_id, research_id)
            )]
            payloads = [r[0] for r in self.conn.execute(
                "SELECT raw_payload_path FROM search_runs WHERE research_id = ? AND raw_payload_path IS NOT NULL",
                (research_id,),
            )]
            self.conn.execute("INSERT INTO research_purge_authorizations VALUES (?)", (research_id,))
            from deixis.workflow.tables import purge_tables  # tables builds on this module
            purge_tables(self.conn, research_id)  # cell revisions reference runs, step inputs and passages deleted below
            self.conn.execute("DELETE FROM evidence_links WHERE claim_id IN (SELECT id FROM claims WHERE answer_id IN (SELECT id FROM answers WHERE research_id = ?))", (research_id,))
            self.conn.execute("DELETE FROM claims WHERE answer_id IN (SELECT id FROM answers WHERE research_id = ?)", (research_id,))
            self.conn.execute("DELETE FROM pdf_candidates WHERE discovery_run_id IN (SELECT id FROM pdf_discovery_runs WHERE research_id = ?)", (research_id,))
            self.conn.execute("DELETE FROM pdf_discovery_runs WHERE research_id = ?", (research_id,))
            for table in ("answer_reviews", "answers", "model_sessions", "step_inputs", "candidates", "search_runs",
                          "selections", "selection_history", "suspected_duplicates", "corpus_memberships", "events",
                          "source_similarities"):
                self.conn.execute(f"DELETE FROM {table} WHERE research_id = ?", (research_id,))
            self.conn.execute("DELETE FROM run_steps WHERE run_id IN (SELECT id FROM runs WHERE research_id = ?)", (research_id,))
            for table in ("runs", "scope_revisions"):
                self.conn.execute(f"DELETE FROM {table} WHERE research_id = ?", (research_id,))
            self.conn.execute("DELETE FROM researches WHERE id = ?", (research_id,))
            self.conn.execute("DELETE FROM research_purge_authorizations WHERE research_id = ?", (research_id,))
            orphan_files: list[str] = []
            for source_id in source_ids:
                # A provider source may be shared by another research. Keep its evidence and files in that case.
                shared = self.conn.execute(
                    "SELECT 1 FROM corpus_memberships WHERE source_version_id = ? UNION SELECT 1 FROM candidates WHERE source_version_id = ? LIMIT 1",
                    (source_id, source_id),
                ).fetchone()
                if shared:
                    continue
                source = self.conn.execute("SELECT work_id, provider_payload_path FROM source_versions WHERE id = ?", (source_id,)).fetchone()
                if source is None:
                    continue
                if source["provider_payload_path"]:
                    payloads.append(source["provider_payload_path"])
                orphan_files.extend(r[0] for r in self.conn.execute("SELECT storage_path FROM source_assets WHERE source_version_id = ?", (source_id,)))
                self.conn.execute("DELETE FROM identifier_mappings WHERE source_version_id = ?", (source_id,))
                self.conn.execute("DELETE FROM passage_embeddings WHERE passage_id IN (SELECT id FROM passages WHERE source_version_id = ?)", (source_id,))
                self.conn.execute("DELETE FROM passages_fts WHERE rowid IN (SELECT rowid FROM passages WHERE source_version_id = ?)", (source_id,))
                self.conn.execute("DELETE FROM passages WHERE source_version_id = ?", (source_id,))
                self.conn.execute("DELETE FROM asset_extractions WHERE asset_id IN (SELECT id FROM source_assets WHERE source_version_id = ?)", (source_id,))
                self.conn.execute("DELETE FROM source_assets WHERE source_version_id = ?", (source_id,))
                self.conn.execute("DELETE FROM source_versions WHERE id = ?", (source_id,))
                self.conn.execute("DELETE FROM works WHERE id = ? AND NOT EXISTS (SELECT 1 FROM source_versions WHERE work_id = ?)", (source["work_id"], source["work_id"]))
            # Files are content-addressed and may be referenced by another asset or search run.
            orphan_files = [p for p in set(orphan_files) if not self.conn.execute("SELECT 1 FROM source_assets WHERE storage_path = ?", (p,)).fetchone()]
            payloads = [p for p in set(payloads) if not self.conn.execute(
                "SELECT 1 FROM search_runs WHERE raw_payload_path = ? UNION SELECT 1 FROM source_versions WHERE provider_payload_path = ?", (p, p)
            ).fetchone()]
        return orphan_files, payloads

    def selection_revision(self, research_id: str) -> int:
        return self.research(research_id)["selection_revision"]

    def _bump_selection_revision(self, research_id: str, old_state: str | None, new_state: str) -> None:
        if old_state != new_state and "included" in (old_state, new_state):
            self.conn.execute("UPDATE researches SET selection_revision = selection_revision + 1 WHERE id = ?", (research_id,))

    def list_researches(self) -> list[dict[str, Any]]:
        rows = self.conn.execute(
            "SELECT r.*, s.question, s.source_scope, s.effort,"
            " (SELECT status FROM runs WHERE research_id = r.id ORDER BY created_at DESC LIMIT 1) AS last_run_status,"
            " (SELECT kind FROM runs WHERE research_id = r.id ORDER BY created_at DESC LIMIT 1) AS last_run_kind,"
            " (SELECT COUNT(*) FROM answers WHERE research_id = r.id AND status = 'structurally_valid') AS answer_count"
            " FROM researches r JOIN scope_revisions s ON s.research_id = r.id AND s.revision = r.current_scope_revision"
            " WHERE r.trashed_at IS NULL"
            " ORDER BY r.updated_at DESC"
        ).fetchall()
        return [dict(r) for r in rows]

    def quick_search(self, text: str, limit: int = 8) -> dict[str, list[dict[str, Any]]]:
        """Substring match (ASCII case-insensitive) over research titles/questions and the titles of each research's sources."""
        researches = self.conn.execute(
            "SELECT r.id, r.title, s.question, r.updated_at FROM researches r"
            " JOIN scope_revisions s ON s.research_id = r.id AND s.revision = r.current_scope_revision"
            " WHERE r.trashed_at IS NULL AND (instr(lower(r.title), lower(?)) > 0 OR instr(lower(s.question), lower(?)) > 0)"
            " ORDER BY r.updated_at DESC LIMIT ?", (text, text, limit)
        ).fetchall()
        sources = self.conn.execute(
            "SELECT v.id AS source_version_id, v.title, v.year, v.version_label, m.research_id, r.title AS research_title"
            " FROM corpus_memberships m JOIN source_versions v ON v.id = m.source_version_id JOIN researches r ON r.id = m.research_id"
            " WHERE r.trashed_at IS NULL AND m.removed_at IS NULL AND instr(lower(v.title), lower(?)) > 0 ORDER BY r.updated_at DESC, v.title LIMIT ?", (text, limit * 2)
        ).fetchall()
        return {"researches": [dict(r) for r in researches], "sources": [dict(r) for r in sources]}

    def scope(self, research_id: str, revision: int | None = None) -> dict[str, Any]:
        if revision is None:
            revision = self.research(research_id)["current_scope_revision"]
        row = self.conn.execute(
            "SELECT * FROM scope_revisions WHERE research_id = ? AND revision = ?", (research_id, revision)
        ).fetchone()
        if row is None:
            raise NotFound(f"{research_id} revision {revision}")
        scope = dict(row)
        scope["providers"] = json.loads(scope.pop("providers_json"))
        return scope

    def revise_scope(self, research_id: str, expected_version: int, question: str, steering: str | None) -> int:
        with transaction(self.conn):
            research = self.research(research_id)
            check_expected_version(expected_version, research["version"])
            current = self.scope(research_id)
            revision = research["current_scope_revision"] + 1
            self.conn.execute(
                "INSERT INTO scope_revisions (research_id, revision, question, language_hint, source_scope, providers_json,"
                " effort, model_connection, requested_model, reasoning_effort, literature_model, literature_reasoning_effort,"
                " review_mode, review_model, review_reasoning_effort, literature_connection, review_connection, steering, created_at)"
                " VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)",
                (research_id, revision, question.strip(), current["language_hint"], current["source_scope"],
                 dumps(current["providers"]), current["effort"], current["model_connection"], current["requested_model"],
                 current["reasoning_effort"], current["literature_model"], current["literature_reasoning_effort"],
                 current["review_mode"], current["review_model"], current["review_reasoning_effort"],
                 current["literature_connection"], current["review_connection"], steering, now()),
            )
            self.conn.execute(
                "UPDATE researches SET current_scope_revision = ?, version = version + 1, title = ?, updated_at = ? WHERE id = ?",
                (revision, question.strip().splitlines()[0][:160], now(), research_id),
            )
            self._event(research_id, "scope_revised", {"scope_revision": revision})
        return revision

    # ---- runs -------------------------------------------------------------------------
    def create_run(self, research_id: str, kind: str, budget: dict[str, Any], idempotency_key: str | None,
                   target: dict[str, Any] | None = None) -> dict[str, Any]:
        """Queue a run. Evidence table runs carry their target (table, columns, planned sources or cell)."""
        with transaction(self.conn):
            if idempotency_key:
                existing = self.conn.execute("SELECT * FROM runs WHERE idempotency_key = ?", (idempotency_key,)).fetchone()
                if existing:
                    return self.run(existing["id"])
            research = self.research(research_id)
            active = self.conn.execute(
                f"SELECT id FROM runs WHERE research_id = ? AND status IN ({','.join('?' * len(ACTIVE_RUN_STATUSES))})",
                (research_id, *ACTIVE_RUN_STATUSES),
            ).fetchone()
            if active:
                raise RevisionConflict(f"run {active['id']} is still active")
            run_id, ts = new_id("run"), now()
            stage = {"discovery": "discovery", "answer": "inspection", "pdf_collection": "inspection", "research_title": "intake"}.get(kind, "extraction")
            self.conn.execute(
                "INSERT INTO runs (id, research_id, scope_revision, kind, status, stage, budget_json, idempotency_key, target_json,"
                " created_at, updated_at) VALUES (?, ?, ?, ?, 'queued', ?, ?, ?, ?, ?, ?)",
                (run_id, research_id, research["current_scope_revision"], kind, stage, dumps(budget), idempotency_key,
                 dumps(target) if target is not None else None, ts, ts),
            )
            self.conn.execute("UPDATE researches SET updated_at = ? WHERE id = ?", (ts, research_id))
            self._event(research_id, "run_queued", {"kind": kind}, run_id)
        return self.run(run_id)

    def run(self, run_id: str) -> dict[str, Any]:
        row = self.conn.execute("SELECT * FROM runs WHERE id = ?", (run_id,)).fetchone()
        if row is None:
            raise NotFound(run_id)
        run = dict(row)
        run["budget"] = json.loads(run.pop("budget_json"))
        run["usage"] = json.loads(run.pop("usage_json"))
        error = run.pop("error_json")
        run["error"] = json.loads(error) if error else None
        target = run.pop("target_json")
        run["target"] = json.loads(target) if target else None
        return run

    def next_queued_run(self) -> dict[str, Any] | None:
        row = self.conn.execute("SELECT id FROM runs WHERE status = 'queued' ORDER BY created_at LIMIT 1").fetchone()
        return self.run(row["id"]) if row else None

    def update_run(self, run_id: str, event: str | None = None, **fields: Any) -> dict[str, Any]:
        columns = {k: (dumps(v) if k in ("usage_json", "error_json") and v is not None else v) for k, v in fields.items()}
        columns["updated_at"] = now()
        with transaction(self.conn):
            run = self.run(run_id)
            assignments = ", ".join(f"{k} = ?" for k in columns)
            self.conn.execute(f"UPDATE runs SET {assignments}, version = version + 1 WHERE id = ?", (*columns.values(), run_id))
            if event:
                self._event(run["research_id"], event, {k: v for k, v in fields.items() if k != "usage_json"}, run_id)
        return self.run(run_id)

    def add_usage(self, run_id: str, key: str, amount: int = 1) -> dict[str, Any]:
        with transaction(self.conn):
            run = self.run(run_id)
            usage = run["usage"]
            usage[key] = usage.get(key, 0) + amount
            self.conn.execute("UPDATE runs SET usage_json = ?, updated_at = ? WHERE id = ?", (dumps(usage), now(), run_id))
        return usage

    # ---- steps --------------------------------------------------------------------------
    def step(self, run_id: str, operation_key: str, kind: str) -> dict[str, Any]:
        with transaction(self.conn):
            row = self.conn.execute(
                "SELECT * FROM run_steps WHERE run_id = ? AND operation_key = ?", (run_id, operation_key)
            ).fetchone()
            if row is None:
                sid = new_id("stp")
                self.conn.execute(
                    "INSERT INTO run_steps (id, run_id, operation_key, kind, status) VALUES (?, ?, ?, ?, 'pending')",
                    (sid, run_id, operation_key, kind),
                )
                row = self.conn.execute("SELECT * FROM run_steps WHERE id = ?", (sid,)).fetchone()
        step = dict(row)
        step["output"] = json.loads(step.pop("output_json")) if step["output_json"] else None
        return step

    def start_step(self, step_id: str) -> None:
        with transaction(self.conn):
            row = self.conn.execute(
                "SELECT s.*, r.research_id FROM run_steps s JOIN runs r ON r.id = s.run_id WHERE s.id = ?", (step_id,)
            ).fetchone()
            self.conn.execute(
                "UPDATE run_steps SET status = 'running', attempt = attempt + 1, started_at = ?, finished_at = NULL,"
                " error_code = NULL, error_json = NULL, delivery_class = NULL WHERE id = ?",
                (now(), step_id),
            )
            self._event(row["research_id"], "step_started", {"step_id": step_id, "kind": row["kind"], "operation_key": row["operation_key"]}, row["run_id"])

    def finish_step(
        self,
        step_id: str,
        status: str,
        output: Any = None,
        error_code: str | None = None,
        error: Any = None,
        delivery_class: str | None = None,
    ) -> None:
        with transaction(self.conn):
            row = self.conn.execute(
                "SELECT s.*, r.research_id FROM run_steps s JOIN runs r ON r.id = s.run_id WHERE s.id = ?", (step_id,)
            ).fetchone()
            self.conn.execute(
                "UPDATE run_steps SET status = ?, output_json = ?, error_code = ?, error_json = ?, delivery_class = ?, finished_at = ? WHERE id = ?",
                (status, dumps(output) if output is not None else None, error_code,
                 dumps(error) if error is not None else None, delivery_class, now(), step_id),
            )
            self._event(
                row["research_id"], "step_finished",
                {"step_id": step_id, "kind": row["kind"], "operation_key": row["operation_key"], "status": status, "error_code": error_code,
                 **({"http_status": error["http_status"]} if isinstance(error, dict) and error.get("http_status") else {})},
                row["run_id"],
            )

    def set_step_output(self, step_id: str, output: Any) -> None:
        """Add to a finished step's stored output (the compiled queries of a search plan) without a second step event."""
        with transaction(self.conn):
            self.conn.execute("UPDATE run_steps SET output_json = ? WHERE id = ?", (dumps(output), step_id))

    def run_steps(self, run_id: str) -> list[dict[str, Any]]:
        rows = self.conn.execute(
            "SELECT id, operation_key, kind, status, attempt, delivery_class, error_code, error_json, output_json, started_at, finished_at"
            " FROM run_steps WHERE run_id = ? ORDER BY rowid", (run_id,)
        ).fetchall()
        return [{**{k: r[k] for k in r.keys() if k != "output_json"},
                 "error": json.loads(r["error_json"]) if r["error_json"] else None,
                 # Only small counting/provenance outputs are carried here; model prose is read through its own view.
                 "output": json.loads(r["output_json"]) if r["output_json"] and (r["kind"] in STEP_OUTPUT_KINDS or r["operation_key"] in STEP_OUTPUT_KEYS) else None}
                for r in rows]

    # ---- model step records ---------------------------------------------------------
    def insert_step_input(self, step_id: str, research_id: str, run_id: str, attempt: int, payload: dict[str, Any],
                          base: str, developer: str, message: str, output_schema: dict[str, Any],
                          selection_revision: int | None = None) -> None:
        with transaction(self.conn):
            self.conn.execute(
                "INSERT INTO step_inputs (id, step_id, research_id, run_id, attempt, task_type, scope_revision, selection_revision,"
                " skill_package_hash, payload_json, base_instructions, developer_instructions, user_message, output_schema_json, created_at)"
                " VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)",
                (payload["step_input_id"], step_id, research_id, run_id, attempt, payload["task_type"], payload["scope_revision"],
                 selection_revision, payload["skill_package_hash"], dumps(payload), base, developer, message, dumps(output_schema), now()),
            )

    def start_model_session(self, research_id: str, run_id: str, step_id: str, step_input_id: str,
                            connection: str, requested_model: str | None) -> str:
        msid = new_id("mss")
        with transaction(self.conn):
            self.conn.execute(
                "INSERT INTO model_sessions (id, research_id, run_id, step_id, step_input_id, connection, requested_model, status, started_at)"
                " VALUES (?, ?, ?, ?, ?, ?, ?, 'started', ?)",
                (msid, research_id, run_id, step_id, step_input_id, connection, requested_model, now()),
            )
            run = self.run(run_id)
            usage = run["usage"]
            usage["model_calls"] = usage.get("model_calls", 0) + 1
            self.conn.execute("UPDATE runs SET usage_json = ? WHERE id = ?", (dumps(usage), run_id))
            self._event(research_id, "model_call_started", {"step_id": step_id, "connection": connection, "requested_model": requested_model}, run_id)
        return msid

    def finish_model_session(self, session_id: str, **fields: Any) -> None:
        encoded = {k: (dumps(v) if k.endswith("_json") and v is not None else v) for k, v in fields.items()}
        encoded["finished_at"] = now()
        with transaction(self.conn):
            self.conn.execute(
                f"UPDATE model_sessions SET {', '.join(f'{k} = ?' for k in encoded)} WHERE id = ?",
                (*encoded.values(), session_id),
            )

    def model_session(self, step_input_id: str) -> dict[str, Any]:
        row = self.conn.execute(
            "SELECT connection, resolved_model, raw_output FROM model_sessions WHERE step_input_id = ? ORDER BY started_at DESC LIMIT 1",
            (step_input_id,),
        ).fetchone()
        if row is None:
            raise NotFound(step_input_id)
        return dict(row)

    def complete_model_step(self, session_id: str, session_fields: dict[str, Any], step_id: str, status: str, **step_fields: Any) -> None:
        """Commit the model session result and the step outcome together, so recovery never finds one without the other."""
        with transaction(self.conn):
            self.finish_model_session(session_id, **session_fields)
            self.finish_step(step_id, status, **step_fields)

    # ---- sources ----------------------------------------------------------------------
    def find_source_by_identifier(self, scheme: str, value: str) -> str | None:
        row = self.conn.execute(
            "SELECT source_version_id FROM identifier_mappings WHERE scheme = ? AND value = ? ORDER BY id LIMIT 1", (scheme, value)
        ).fetchone()
        return row["source_version_id"] if row else None

    def upsert_provider_source(self, provider: str, record: Any, payload_path: str | None) -> tuple[str, bool]:
        """Reuse the provider's own record mapping, else a source version with the same normalized DOI.

        A DOI names one registered version, so the same DOI from several providers is one source version with a mapping
        per provider. A record whose DOI covers several file versions (`merge_by_doi` false, e.g. arXiv) never merges,
        and title matches never merge; `record_search` flags those as suspected duplicates. Records with one arXiv DOI
        (an arXiv version, or another provider's record of the preprint) are separate versions of one work (D46).
        Other versions the provider lists for the record become separate source versions of the same work.
        """
        existing = self.find_source_by_identifier(provider, record.provider_record_id)
        if existing is None and record.doi and record.merge_by_doi:
            existing = self.find_source_by_identifier("doi", record.doi)
        with transaction(self.conn):
            if existing:
                svid, wid = existing, self.source(existing)["work_id"]
                self._insert_mappings(svid, provider, record, now())
                self.enrich_source(provider, svid, record)
                has_abstract = self.conn.execute(
                    "SELECT 1 FROM passages WHERE source_version_id = ? AND kind = 'abstract'", (svid,)
                ).fetchone()
                if record.abstract and not has_abstract:
                    self._insert_passage(svid, None, "abstract", None, None, record.abstract_origin, payload_path, None, record.abstract)
                if record.cited_by_count is not None:
                    # A citation count changes over time; the latest retrieval replaces it, with its date.
                    self.conn.execute("UPDATE source_versions SET cited_by_count = ?, cited_by_count_at = ? WHERE id = ?",
                                      (record.cited_by_count, now(), svid))
            else:
                svid, wid = self._insert_provider_record(provider, record, payload_path)
            for other in record.other_versions:
                self._insert_other_version(provider, record, wid, other, payload_path)
        return svid, existing is None

    def other_version_ids(self, provider: str, record: Any) -> list[str]:
        return [self.find_source_by_identifier(f"{provider}_version", f"{record.provider_record_id}:{o.version_label}")
                for o in record.other_versions]

    def _insert_other_version(self, provider: str, record: Any, wid: str, other: Any, payload_path: str | None) -> None:
        # The DOI identifies the record's version and the provider abstract describes the record, so neither is copied.
        key = f"{record.provider_record_id}:{other.version_label}"
        if self.find_source_by_identifier(f"{provider}_version", key):
            return
        ts, oid = now(), new_id("srv")
        self.conn.execute(
            "INSERT INTO source_versions (id, work_id, title, authors_json, year, venue, version_label, publication_type, doi,"
            " landing_url, oa_pdf_url, oa_pdf_version, origin, provider_payload_path, created_at, volume, issue, pages)"
            " VALUES (?, ?, ?, ?, NULL, ?, ?, ?, NULL, ?, ?, ?, 'provider', ?, ?, ?, ?, ?)",
            (oid, wid, record.title, dumps(record.authors), other.venue, other.version_label, record.publication_type,
             other.landing_url, other.pdf_url, other.version_label, payload_path, ts,
             record.volume, record.issue, record.pages),
        )
        self.conn.execute(
            "INSERT INTO identifier_mappings (source_version_id, scheme, value, provider, retrieved_at) VALUES (?, ?, ?, ?, ?)",
            (oid, f"{provider}_version", key, provider, ts),
        )

    def _insert_provider_record(self, provider: str, record: Any, payload_path: str | None) -> tuple[str, str]:
        ts, svid = now(), new_id("srv")
        same_preprint = self.conn.execute(
            "SELECT work_id FROM source_versions WHERE doi = ? ORDER BY created_at, id LIMIT 1", (record.doi,)
        ).fetchone() if record.doi and record.doi.startswith(ARXIV_DOI_PREFIX) else None
        if same_preprint:
            wid = same_preprint["work_id"]
        else:
            wid = new_id("wrk")
            self.conn.execute("INSERT INTO works (id, created_at) VALUES (?, ?)", (wid, ts))
        self.conn.execute(
            "INSERT INTO source_versions (id, work_id, title, authors_json, year, venue, version_label, publication_type, doi,"
            " landing_url, oa_pdf_url, oa_pdf_version, origin, provider_payload_path, created_at, cited_by_count, cited_by_count_at,"
            " volume, issue, pages)"
            " VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, 'provider', ?, ?, ?, ?, ?, ?, ?)",
            (svid, wid, record.title, dumps(record.authors), record.year, record.venue, record.version_label,
             record.publication_type, record.doi, record.landing_url, record.oa_pdf_url, record.oa_pdf_version, payload_path, ts,
             record.cited_by_count, ts if record.cited_by_count is not None else None,
             record.volume, record.issue, record.pages),
        )
        self._insert_mappings(svid, provider, record, ts)
        if record.abstract:
            self._insert_passage(svid, None, "abstract", None, None, record.abstract_origin, payload_path, None, record.abstract)
        if not same_preprint:
            self._assign_source_key(wid)
        return svid, wid

    def enrich_source(self, provider: str, svid: str, record: Any) -> None:
        """Fill absent citation fields from an exact-identity provider lookup; never replace existing metadata."""
        ts = now()
        with transaction(self.conn):
            self.conn.execute(
                "UPDATE source_versions SET"
                " authors_json = CASE WHEN authors_json = '[]' AND ? <> '[]' THEN ? ELSE authors_json END,"
                " year = COALESCE(year, ?), venue = COALESCE(venue, ?), publication_type = COALESCE(publication_type, ?),"
                " landing_url = COALESCE(landing_url, ?), volume = COALESCE(volume, ?), issue = COALESCE(issue, ?),"
                " pages = COALESCE(pages, ?) WHERE id = ?",
                (dumps(record.authors), dumps(record.authors), record.year, record.venue, record.publication_type,
                 record.landing_url, record.volume, record.issue, record.pages, svid),
            )
            self.conn.execute(
                "INSERT OR IGNORE INTO identifier_mappings (source_version_id, scheme, value, provider, retrieved_at)"
                " VALUES (?, ?, ?, ?, ?)",
                (svid, provider, record.provider_record_id, provider, ts),
            )
            # A key taken from the title gives way to the author an enrichment brings; an author key is never changed (D59).
            self._assign_source_key(self.source(svid)["work_id"], replace_title_key=True)

    def _insert_mappings(self, svid: str, provider: str, record: Any, ts: str) -> None:
        mappings = [(provider, record.provider_record_id)]
        if record.doi and record.merge_by_doi:
            mappings.append(("doi", record.doi))
        if record.identifiers.get("published_doi"):
            mappings.append(("published_doi", record.identifiers["published_doi"]))
        for scheme, value in mappings:
            self.conn.execute(
                "INSERT OR IGNORE INTO identifier_mappings (source_version_id, scheme, value, provider, retrieved_at) VALUES (?, ?, ?, ?, ?)",
                (svid, scheme, value, provider, ts),
            )

    def create_upload_source(self, title: str) -> str:
        ts, wid, svid = now(), new_id("wrk"), new_id("srv")
        with transaction(self.conn):
            self.conn.execute("INSERT INTO works (id, created_at) VALUES (?, ?)", (wid, ts))
            self.conn.execute(
                "INSERT INTO source_versions (id, work_id, title, origin, version_label, created_at) VALUES (?, ?, ?, 'user_upload', 'uploaded file', ?)",
                (svid, wid, title, ts),
            )
            self._assign_source_key(wid)
        return svid

    def _assign_source_key(self, work_id: str, replace_title_key: bool = False) -> None:
        """Give a work its short author–year key (D59): from its published record's authors when it has one, else from
        another version's authors, else from the title. A key is kept once given; only a title key may be replaced."""
        if not any(col[1] == "source_key" for col in self.conn.execute("PRAGMA table_info(works)")):
            return  # a library opened at a schema before migration 33, as the migration tests do
        work = self.conn.execute("SELECT source_key, source_key_basis FROM works WHERE id = ?", (work_id,)).fetchone()
        if work is None or (work["source_key"] and not (replace_title_key and work["source_key_basis"] == "title")):
            return
        versions = [self.source(r[0]) for r in self.conn.execute(
            "SELECT id FROM source_versions WHERE work_id = ? ORDER BY created_at, id", (work_id,))]
        if not versions:
            return
        best = min(versions, key=lambda v: (not v["authors"], not is_published(v), v["year"] is None))
        stem, basis = key_stem(best["authors"], best["title"], best["year"] or next((v["year"] for v in versions if v["year"]), None))
        if work["source_key"] and basis == "title":
            return
        for suffix in suffixes():
            key = f"{stem}{suffix}"
            if not self.conn.execute("SELECT 1 FROM works WHERE source_key = ? COLLATE NOCASE AND id != ?", (key, work_id)).fetchone():
                self.conn.execute("UPDATE works SET source_key = ?, source_key_basis = ? WHERE id = ?", (key, basis, work_id))
                return

    def assign_source_keys(self) -> int:
        """Key every work stored without one, oldest first; returns how many were keyed."""
        with transaction(self.conn):
            missing = [r[0] for r in self.conn.execute("SELECT id FROM works WHERE source_key IS NULL ORDER BY created_at, id")]
            for work_id in missing:
                self._assign_source_key(work_id)
        return len(missing)

    def _insert_passage(self, svid: str, asset_id: str | None, kind: str, page: int | None, label: str | None,
                        abstract_origin: str | None, payload_ref: str | None, extraction_version: str | None, text: str,
                        text_source: str = "text_layer") -> str:
        digest = hashlib.sha256(text.encode()).hexdigest()
        existing = self.conn.execute(
            "SELECT id FROM passages WHERE source_version_id = ? AND kind = ? AND IFNULL(asset_id, '') = IFNULL(?, '')"
            " AND IFNULL(physical_page, 0) = IFNULL(?, 0) AND text_sha256 = ? AND extraction_version IS ?",
            (svid, kind, asset_id, page, digest, extraction_version),
        ).fetchone()
        if existing:
            return existing["id"]
        pid, ts = new_id("psg"), now()
        self.conn.execute(
            "INSERT INTO passages (id, source_version_id, asset_id, kind, physical_page, printed_label, abstract_origin, payload_ref,"
            " extraction_version, text, text_sha256, retrieved_at, created_at" + (", text_source" if text_source != "text_layer" else "")
            + ") VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?" + (", ?" if text_source != "text_layer" else "") + ")",
            # The text layer is the column's default, so code before migration 0030's text sources writes the same rows.
            (pid, svid, asset_id, kind, page, label, abstract_origin, payload_ref, extraction_version, text, digest, ts, ts)
            + ((text_source,) if text_source != "text_layer" else ()),
        )
        return pid

    def asset_by_sha(self, sha256: str) -> dict[str, Any] | None:
        return row_dict(self.conn.execute(
            "SELECT * FROM source_assets WHERE sha256 = ? AND removed_at IS NULL ORDER BY retrieved_at LIMIT 1", (sha256,)
        ).fetchone())

    def asset(self, asset_id: str) -> dict[str, Any]:
        row = self.conn.execute("SELECT * FROM source_assets WHERE id = ?", (asset_id,)).fetchone()
        if row is None:
            raise NotFound(asset_id)
        return dict(row)

    def asset_passage_count(self, asset_id: str) -> int:
        return self.conn.execute("SELECT COUNT(*) FROM passages WHERE asset_id = ?", (asset_id,)).fetchone()[0]

    def add_asset_with_pages(self, svid: str, sha256: str, size: int, storage_path: str, origin: str,
                             retrieved_from: str | None, filename: str | None, extraction: Any,
                             extraction_version: str, chunker: Any) -> str:
        aid = new_id("ast")
        with transaction(self.conn):
            try:
                self.conn.execute(
                    "INSERT INTO source_assets (id, source_version_id, sha256, byte_size, media_type, storage_path, original_filename,"
                    " retrieved_from, retrieved_at, origin, extraction_status, extraction_version, extraction_error, page_count)"
                    " VALUES (?, ?, ?, ?, 'application/pdf', ?, ?, ?, ?, ?, ?, ?, ?, ?)",
                    (aid, svid, sha256, size, storage_path, filename, retrieved_from, now(), origin,
                     extraction.status, extraction_version, extraction.error, extraction.page_count),
                )
            except sqlite3.IntegrityError as exc:
                if self.has_asset(svid):
                    raise PdfInUse(svid) from exc
                raise
            self._write_extraction(svid, aid, extraction, extraction_version, chunker, "current")
        return aid

    def _write_extraction(self, svid: str, aid: str, extraction: Any, extraction_version: str, chunker: Any,
                          outcome: str, rejection_reason: str | None = None) -> None:
        passage_ids = []
        for page in extraction.pages:
            for start, end, text in chunker(page.text):
                passage_ids.append((page.physical_page, self._insert_passage(
                    svid, aid, "pdf_page", page.physical_page, page.printed_label, None, f"chars:{start}-{end}", extraction_version, text,
                    getattr(page, "text_source", "text_layer"))))
        math, ocr = getattr(extraction, "math", None), getattr(extraction, "ocr", None)
        self.conn.execute(
            "INSERT INTO asset_extractions (id, asset_id, extraction_version, status, error, page_count, text_pages, passage_count,"
            " outcome, rejection_reason, created_at, math_json, ocr_json) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)",
            (new_id("ext"), aid, extraction_version, extraction.status, extraction.error, extraction.page_count,
             len({page for page, _ in passage_ids}), len(set(pid for _, pid in passage_ids)), outcome, rejection_reason, now(),
             dumps(math) if math is not None else None, dumps(ocr) if ocr is not None else None),
        )

    def reextract_asset(self, asset_id: str, extraction: Any, extraction_version: str, chunker: Any,
                        dry_run: bool = False, allow_run_id: str | None = None) -> dict[str, Any]:
        """Write a new text extraction of a PDF in use; it becomes current only if it loses nothing visible (D45).

        Current: its status is not worse, its page count is equal and it has text on no fewer pages. Otherwise it is
        recorded as rejected and the old text stays in use. Old passages are shadowed, never deleted. An OCR reading (D51)
        that found text on no page is rejected too, and is reported as `asset_ocr_read` with its page counts.
        """
        asset = self.asset(asset_id)
        if asset["removed_at"] is not None:
            raise NotFound(asset_id)
        if self.conn.execute("SELECT 1 FROM asset_extractions WHERE asset_id = ? AND extraction_version = ?",
                             (asset_id, extraction_version)).fetchone():
            return {"asset_id": asset_id, "outcome": "unchanged"}
        old = self.conn.execute(
            "SELECT status, page_count, text_pages, passage_count FROM asset_extractions WHERE asset_id = ? AND outcome = 'current'",
            (asset_id,)).fetchone()
        rank = {"succeeded": 3, "partial": 2, "no_text": 1, "failed": 0}
        text_pages = len({page.physical_page for page in extraction.pages if chunker(page.text)})
        reason = None
        if old is not None:
            if rank.get(extraction.status, 0) < rank.get(old["status"], 0):
                reason = f"status {extraction.status} is worse than {old['status']}"
            elif extraction.page_count != old["page_count"]:
                reason = f"page count {extraction.page_count} differs from {old['page_count']}"
            elif text_pages < old["text_pages"]:
                reason = f"text on {text_pages} pages, fewer than {old['text_pages']}"
        # A Marker reading keeps OCR pages it was built on (D52) but is not itself an OCR reading.
        ocr = getattr(extraction, "ocr", None) if getattr(extraction, "math", None) is None else None
        if ocr is not None and not reason and not ocr["pages_with_text"]:
            reason = "OCR found no text"
        report = {"asset_id": asset_id, "source_version_id": asset["source_version_id"], "outcome": "rejected" if reason else "current",
                  "rejection_reason": reason, "old_version": asset["extraction_version"], "text_pages": text_pages,
                  "old_text_pages": old["text_pages"] if old else None}
        if dry_run:
            return report
        researches = [r[0] for r in self.conn.execute(
            "SELECT research_id FROM corpus_memberships WHERE source_version_id = ?", (asset["source_version_id"],))]
        with transaction(self.conn):
            # The run that asked for this extraction (an answer waiting for its sources' equations, D52) does not block it.
            active = self.conn.execute(
                f"SELECT 1 FROM runs WHERE research_id IN ({', '.join('?' * len(researches))}) AND status IN"
                f" ({', '.join('?' * len(ACTIVE_RUN_STATUSES))}) AND id IS NOT ? LIMIT 1", (*researches, *ACTIVE_RUN_STATUSES, allow_run_id)
            ).fetchone() if researches else None
            if active:
                raise RunInProgress(asset_id)
            if not reason:
                self.conn.execute("UPDATE asset_extractions SET outcome = 'superseded' WHERE asset_id = ? AND outcome = 'current'",
                                  (asset_id,))
            self._write_extraction(asset["source_version_id"], asset_id, extraction, extraction_version, chunker,
                                   report["outcome"], reason)
            if not reason:
                self.conn.execute(
                    "UPDATE source_assets SET extraction_version = ?, extraction_status = ?, extraction_error = ?, page_count = ?"
                    " WHERE id = ?", (extraction_version, extraction.status, extraction.error, extraction.page_count, asset_id))
            payload = {k: report[k] for k in ("asset_id", "source_version_id", "outcome", "rejection_reason")} | {"extraction_version": extraction_version}
            for research_id in researches:
                if ocr is not None:
                    self._event(research_id, "asset_ocr_read", payload | {k: ocr[k] for k in (
                        "languages", "pages_read", "pages_with_text", "blank_pages", "failed_pages")})
                else:
                    self._event(research_id, "asset_reextracted", payload)
        return report

    def replace_asset(self, asset_id: str, sha256: str, size: int, storage_path: str, origin: str, retrieved_from: str | None,
                      filename: str | None, extraction: Any, extraction_version: str, chunker: Any) -> str:
        """Put another file in use for the source version, in every research that uses it (D45).

        The new file gets its own passages even when its text is the same; the old file is marked replaced, and the evidence
        that cites its passages keeps them. The selection does not change, so no selection revision is bumped.
        """
        asset = self.asset(asset_id)
        if asset["removed_at"] is not None:
            raise NotFound(asset_id)
        if asset["sha256"] == sha256:
            raise SameFile(asset_id)
        svid, aid, ts = asset["source_version_id"], new_id("ast"), now()
        researches = [r[0] for r in self.conn.execute("SELECT research_id FROM corpus_memberships WHERE source_version_id = ?", (svid,))]
        with transaction(self.conn):
            if researches and self.conn.execute(
                f"SELECT 1 FROM runs WHERE research_id IN ({', '.join('?' * len(researches))}) AND status IN"
                f" ({', '.join('?' * len(ACTIVE_RUN_STATUSES))}) LIMIT 1", (*researches, *ACTIVE_RUN_STATUSES)
            ).fetchone():
                raise RunInProgress(asset_id)
            # The old file leaves use first, so the one-file-in-use index holds throughout the transaction.
            self.conn.execute("UPDATE source_assets SET removed_at = ?, removal_reason = 'replaced' WHERE id = ?", (ts, asset_id))
            self.conn.execute(
                "INSERT INTO source_assets (id, source_version_id, sha256, byte_size, media_type, storage_path, original_filename,"
                " retrieved_from, retrieved_at, origin, extraction_status, extraction_version, extraction_error, page_count)"
                " VALUES (?, ?, ?, ?, 'application/pdf', ?, ?, ?, ?, ?, ?, ?, ?, ?)",
                (aid, svid, sha256, size, storage_path, filename, retrieved_from, ts, origin,
                 extraction.status, extraction_version, extraction.error, extraction.page_count),
            )
            self.conn.execute("UPDATE source_assets SET replaced_by_asset_id = ? WHERE id = ?", (aid, asset_id))
            self._write_extraction(svid, aid, extraction, extraction_version, chunker, "current")
            for research_id in researches:
                self._event(research_id, "asset_replaced", {"source_version_id": svid, "asset_id": asset_id, "replaced_by_asset_id": aid})
                self.conn.execute("UPDATE researches SET updated_at = ? WHERE id = ?", (ts, research_id))
        return aid

    def evidence_statuses(self, passage_ids: list[str]) -> dict[str, str]:
        found: dict[str, str] = {}
        for start in range(0, len(passage_ids), 500):
            chunk = passage_ids[start:start + 500]
            found.update({r[0]: r[1] for r in self.conn.execute(
                f"SELECT p.id, {EVIDENCE_STATUS_SQL} FROM passages p LEFT JOIN source_assets a ON a.id = p.asset_id"
                f" WHERE p.id IN ({','.join('?' * len(chunk))})", chunk)})
        return found

    def research_cites_asset(self, research_id: str, asset_id: str) -> bool:
        """Whether an answer or an evidence table cell of this research links a passage of the file."""
        return self.conn.execute(
            "SELECT 1 FROM evidence_links l JOIN claims c ON c.id = l.claim_id JOIN answers an ON an.id = c.answer_id"
            " JOIN passages p ON p.id = l.passage_id WHERE an.research_id = ? AND p.asset_id = ?"
            " UNION ALL SELECT 1 FROM cell_evidence_links l JOIN cell_revisions r ON r.id = l.cell_revision_id"
            " JOIN evidence_cells ce ON ce.id = r.cell_id JOIN evidence_tables t ON t.id = ce.table_id"
            " JOIN passages p ON p.id = l.passage_id WHERE t.research_id = ? AND p.asset_id = ? LIMIT 1",
            (research_id, asset_id, research_id, asset_id),
        ).fetchone() is not None

    def asset_impact(self, asset_id: str) -> dict[str, Any]:
        """What cites this file's passages: researches using its source, evidence table cells and answer quotes."""
        asset = self.asset(asset_id)
        researches = [dict(r) for r in self.conn.execute(
            "SELECT r.id, r.title FROM corpus_memberships m JOIN researches r ON r.id = m.research_id"
            " WHERE m.source_version_id = ? AND r.trashed_at IS NULL ORDER BY r.updated_at DESC", (asset["source_version_id"],)
        )]
        cells = self.conn.execute(
            "SELECT COUNT(DISTINCT r.cell_id) FROM cell_evidence_links l JOIN cell_revisions r ON r.id = l.cell_revision_id"
            " JOIN passages p ON p.id = l.passage_id WHERE p.asset_id = ?", (asset_id,)
        ).fetchone()[0]
        quotes = self.conn.execute(
            "SELECT COUNT(*) FROM evidence_links l JOIN passages p ON p.id = l.passage_id WHERE p.asset_id = ?", (asset_id,)
        ).fetchone()[0]
        return {"asset_id": asset_id, "researches": researches, "cells": cells, "quotes": quotes}

    def remove_asset(self, research_id: str, svid: str, asset_id: str) -> None:
        """Withdraw an attachment from future use while retaining its immutable audit evidence."""
        with transaction(self.conn):
            asset = self.conn.execute(
                "SELECT id FROM source_assets WHERE id = ? AND source_version_id = ? AND removed_at IS NULL",
                (asset_id, svid),
            ).fetchone()
            if asset is None:
                raise NotFound(asset_id)
            ts = now()
            self.conn.execute("UPDATE source_assets SET removed_at = ?, removal_reason = 'wrong_file' WHERE id = ?", (ts, asset_id))
            included = self.conn.execute(
                "SELECT 1 FROM selections WHERE research_id = ? AND source_version_id = ? AND state = 'included'",
                (research_id, svid),
            ).fetchone()
            if included:
                self.conn.execute(
                    "UPDATE researches SET selection_revision = selection_revision + 1, updated_at = ? WHERE id = ?",
                    (ts, research_id),
                )
            else:
                self.conn.execute("UPDATE researches SET updated_at = ? WHERE id = ?", (ts, research_id))
            self._event(research_id, "asset_removed", {"source_version_id": svid, "asset_id": asset_id})

    def restore_asset(self, research_id: str, svid: str, asset_id: str) -> None:
        """Put a PDF removed as the wrong file back in use, with its passages; only while no other PDF is in use (D50).

        A replaced file is not restored this way: replacing it again is the explicit action for that.
        """
        researches = [r[0] for r in self.conn.execute("SELECT research_id FROM corpus_memberships WHERE source_version_id = ?", (svid,))]
        with transaction(self.conn):
            if not self.conn.execute(
                "SELECT 1 FROM source_assets WHERE id = ? AND source_version_id = ? AND removal_reason = 'wrong_file'", (asset_id, svid)
            ).fetchone():
                raise NotFound(asset_id)
            if researches and self.conn.execute(
                f"SELECT 1 FROM runs WHERE research_id IN ({', '.join('?' * len(researches))}) AND status IN"
                f" ({', '.join('?' * len(ACTIVE_RUN_STATUSES))}) LIMIT 1", (*researches, *ACTIVE_RUN_STATUSES)
            ).fetchone():
                raise RunInProgress(asset_id)
            if self.has_asset(svid):
                raise PdfInUse(svid)
            ts = now()
            self.conn.execute("UPDATE source_assets SET removed_at = NULL, removal_reason = NULL WHERE id = ?", (asset_id,))
            # As removing it did: an included source's answer input changes, so the selection revision moves.
            included = self.conn.execute(
                "SELECT 1 FROM selections WHERE research_id = ? AND source_version_id = ? AND state = 'included'", (research_id, svid)
            ).fetchone()
            self.conn.execute(f"UPDATE researches SET updated_at = ?{', selection_revision = selection_revision + 1' if included else ''}"
                              " WHERE id = ?", (ts, research_id))
            self._event(research_id, "asset_restored", {"source_version_id": svid, "asset_id": asset_id})

    def source_key(self, work_id: str) -> str | None:
        row = self.conn.execute("SELECT source_key FROM works WHERE id = ?", (work_id,)).fetchone()
        return row[0] if row else None

    def source(self, svid: str) -> dict[str, Any]:
        row = self.conn.execute("SELECT * FROM source_versions WHERE id = ?", (svid,)).fetchone()
        if row is None:
            raise NotFound(svid)
        source = dict(row)
        source["authors"] = json.loads(source.pop("authors_json"))
        return source

    # ---- PDF acquisition -------------------------------------------------------------
    def record_pdf_discovery(self, research_id: str, svid: str, provider: str, query: str, outcome: Any) -> str:
        run_id, ts = new_id("pdr"), now()
        with transaction(self.conn):
            self.conn.execute(
                "INSERT INTO pdf_discovery_runs (id, research_id, source_version_id, provider, query_text, status,"
                " result_count, other_title_count, http_status, error_code, created_at, finished_at)"
                " VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)",
                (run_id, research_id, svid, provider, query, outcome.status, len(outcome.candidates),
                 getattr(outcome, "other_title_count", 0), outcome.http_status, outcome.error_code, ts, ts),
            )
            self._event(research_id, "pdf_discovery_recorded", {
                "source_version_id": svid, "provider": provider, "status": outcome.status,
                "result_count": len(outcome.candidates), "http_status": outcome.http_status,
                "error_code": outcome.error_code,
            })
        return run_id

    def record_pdf_candidates(self, svid: str, run_id: str, candidates: list[Any]) -> list[dict[str, Any]]:
        with transaction(self.conn):
            for candidate in candidates:
                self.conn.execute(
                    "INSERT INTO pdf_candidates (id, source_version_id, discovery_run_id, provider, candidate_url,"
                    " landing_url, version_label, license, identity_status, version_status, access_status, discovered_at)"
                    " VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, 'not_attempted', ?)"
                    " ON CONFLICT(source_version_id, provider, candidate_url) DO UPDATE SET"
                    " discovery_run_id = excluded.discovery_run_id, provider = excluded.provider,"
                    " landing_url = COALESCE(excluded.landing_url, pdf_candidates.landing_url),"
                    " version_label = COALESCE(excluded.version_label, pdf_candidates.version_label),"
                    " license = COALESCE(excluded.license, pdf_candidates.license),"
                    " identity_status = excluded.identity_status, version_status = excluded.version_status",
                    (new_id("pdc"), svid, run_id, candidate.provider, candidate.url, candidate.landing_url,
                     candidate.version_label, candidate.license, candidate.identity_status, candidate.version_status, now()),
                )
        return self.pdf_candidates(svid)

    def pdf_candidates(self, svid: str) -> list[dict[str, Any]]:
        return [dict(r) for r in self.conn.execute(
            "SELECT * FROM pdf_candidates WHERE source_version_id = ? ORDER BY discovered_at, rowid", (svid,)
        )]

    def pdf_discoveries(self, research_id: str, svid: str) -> list[dict[str, Any]]:
        return [dict(r) for r in self.conn.execute(
            "SELECT provider, query_text, status, result_count, other_title_count, http_status, error_code, created_at,"
            " finished_at FROM pdf_discovery_runs WHERE research_id = ? AND source_version_id = ? ORDER BY created_at, rowid",
            (research_id, svid),
        )]

    def pdf_link_refusal(self, svid: str, url: str) -> dict[str, Any] | None:
        """The latest refusal of this open-access link in any run. A timeout or lost connection is not a refusal."""
        return row_dict(self.conn.execute(
            "SELECT error_code, json_extract(error_json, '$.http_status') AS http_status FROM run_steps"
            " WHERE operation_key = ? AND kind = 'fetch_pdf' AND status = 'failed'"
            " AND error_code IN ('fetch_http_error', 'fetch_not_pdf', 'fetch_too_large', 'fetch_blocked_url')"
            # A failure recorded before the link was stored with it is taken to concern the same link.
            " AND COALESCE(json_extract(error_json, '$.url'), ?) = ? ORDER BY finished_at DESC LIMIT 1",
            (f"fetch:{svid}", url, url),
        ).fetchone())

    def record_pdf_attempt(self, candidate_id: str, result: Any) -> None:
        with transaction(self.conn):
            self.conn.execute(
                "UPDATE pdf_candidates SET access_status = ?, http_status = ?, error_code = ?, final_url = ?, attempted_at = ?"
                " WHERE id = ?",
                ("downloaded" if result.status == "ok" else result.status, result.http_status, result.error,
                 result.final_url, now(), candidate_id),
            )

    # ---- research corpus -------------------------------------------------------------
    def record_search(self, search_fields: dict[str, Any], provider: str, records: list[Any], payload_path: str | None,
                      step_id: str, step_status: str, step_output: dict[str, Any] | None = None, **step_fields: Any) -> str:
        """Commit the search run, normalized sources, candidates and the step outcome together."""
        with transaction(self.conn):
            srid = self.add_search_run(**search_fields)
            found = []
            for rank, record in enumerate(records):
                svid, _ = self.upsert_provider_source(provider, record, payload_path)
                found.append(svid)
                # A version of a work that already has a candidate here is found again as that candidate (D46).
                record_svid = self._work_candidate(search_fields["research_id"], svid) or svid
                self.add_to_corpus(search_fields["research_id"], record_svid, "search", srid, rank, scope_revision=search_fields["scope_revision"])
                if record_svid != svid:
                    self.add_to_corpus(search_fields["research_id"], svid, "search", srid, candidate=False)
                for other in self.other_version_ids(provider, record):  # kept with the record, not screened as separate candidates
                    self.add_to_corpus(search_fields["research_id"], other, "search", srid, candidate=False)
            self._flag_suspected_duplicates(search_fields["research_id"], found)
            output = {**step_output, "search_run_id": srid} if step_output is not None else None
            self.finish_step(step_id, step_status, output=output, **step_fields)
        return srid

    def _work_candidate(self, research_id: str, svid: str) -> str | None:
        """Another source version of svid's work that is a candidate of the research, unless svid is one itself.

        A published record is its own candidate when the work's candidates are only preprints, so it can head the work (D48).
        """
        row = self.conn.execute(
            "SELECT c.source_version_id, c.source_version_id = ? AS own FROM candidates c"
            " JOIN source_versions v ON v.id = c.source_version_id"
            " WHERE c.research_id = ? AND v.work_id = (SELECT work_id FROM source_versions WHERE id = ?)"
            " ORDER BY own DESC, c.created_at LIMIT 1", (svid, research_id, svid)
        ).fetchone()
        if not row or row[1]:
            return None
        return None if is_published(self.source(svid)) and not is_published(self.source(row[0])) else row[0]

    def _flag_suspected_duplicates(self, research_id: str, svids: list[str]) -> None:
        """Record candidates of other works that may be the same publication; nothing is merged.

        A preprint and its published record become versions of one work instead of being flagged (D48).
        """
        rows = {r["id"]: r for r in self.conn.execute(
            "SELECT v.id, v.work_id, v.title, v.doi FROM candidates c JOIN source_versions v ON v.id = c.source_version_id"
            " WHERE c.research_id = ?", (research_id,)
        )}
        by_title: dict[str, list[str]] = {}
        for row in rows.values():
            by_title.setdefault(title_key(row["title"]), []).append(row["id"])
        pairs = set()
        for svid in dict.fromkeys(svids):
            if svid not in rows:
                continue
            key = title_key(rows[svid]["title"])
            if len(key) >= MIN_TITLE_KEY_CHARS:
                pairs |= {(svid, other, "same_title") for other in by_title[key]}
            doi = rows[svid]["doi"]
            linked = self.conn.execute(
                "SELECT source_version_id FROM identifier_mappings WHERE scheme = 'published_doi' AND value = ?", (doi,)
            ).fetchall() if doi else []
            linked += self.conn.execute(
                "SELECT d.source_version_id FROM identifier_mappings p JOIN identifier_mappings d"
                " ON d.scheme = 'doi' AND d.value = p.value WHERE p.scheme = 'published_doi' AND p.source_version_id = ?", (svid,)
            ).fetchall()
            pairs |= {(svid, r[0], "published_doi") for r in linked}
        ts = now()
        for a, b, basis in sorted(pairs, key=lambda pair: pair[2] != "published_doi"):
            if b in rows and not self._join_if_same_publication(a, b, basis):
                first, second = sorted((a, b))
                self.conn.execute(
                    "INSERT OR IGNORE INTO suspected_duplicates (research_id, source_version_id, other_source_version_id, basis, created_at)"
                    " VALUES (?, ?, ?, ?, ?)", (research_id, first, second, basis, ts),
                )

    def _join_if_same_publication(self, a: str, b: str, basis: str) -> bool:
        """Put a preprint and its published record in one work, headed by the published record (D48).

        True when the two already share a work or were joined; false when they stay separate works. The versions stay
        separate source versions: nothing about either record is merged, and evidence never moves between them.
        """
        first, second = self.source(a), self.source(b)
        if first["work_id"] == second["work_id"]:
            return True
        if not same_publication(first, second, basis):
            return False
        keep, drop = (first, second) if is_published(first) else (second, first)
        self.conn.execute("UPDATE source_versions SET work_id = ? WHERE work_id = ?", (keep["work_id"], drop["work_id"]))
        self.conn.execute("DELETE FROM works WHERE id = ?", (drop["work_id"],))
        self.conn.execute(
            "DELETE FROM suspected_duplicates WHERE (SELECT work_id FROM source_versions WHERE id = source_version_id)"
            " = (SELECT work_id FROM source_versions WHERE id = other_source_version_id)"
        )
        for (research_id,) in self.conn.execute(
            "SELECT DISTINCT m.research_id FROM corpus_memberships m JOIN source_versions v ON v.id = m.source_version_id"
            " WHERE v.work_id = ?", (keep["work_id"],)
        ).fetchall():
            self._settle_work_head(research_id, keep["work_id"])
        return True

    def link_published_versions(self) -> int:
        """Join preprints and published records flagged as suspected duplicates before D48; returns the pairs joined."""
        joined = 0
        with transaction(self.conn):
            for r in self.conn.execute(
                "SELECT source_version_id, other_source_version_id, basis FROM suspected_duplicates ORDER BY basis != 'published_doi'"
            ).fetchall():
                a, b = self.source(r[0]), self.source(r[1])
                if a["work_id"] != b["work_id"] and self._join_if_same_publication(r[0], r[1], r[2]):
                    joined += 1
        return joined

    def work_heads(self, research_id: str, include_removed: bool = False) -> dict[str, str]:
        """The record that heads each work in the research: a published record, else the first record (D46, D48).

        A record is a candidate or a source added other than by search; other versions found by search never head a work.
        Sources removed from the research head nothing unless include_removed (D50).
        """
        heads: dict[str, dict[str, Any]] = {}
        for row in self.conn.execute(
            "SELECT v.id, v.work_id, v.doi, v.version_label FROM corpus_memberships m JOIN source_versions v ON v.id = m.source_version_id"
            " LEFT JOIN candidates c ON c.research_id = m.research_id AND c.source_version_id = m.source_version_id"
            f" WHERE m.research_id = ?{'' if include_removed else ' AND m.removed_at IS NULL'} AND (c.id IS NOT NULL OR m.added_by != 'search')"
            " ORDER BY m.created_at, c.rank", (research_id,)
        ):
            current = heads.get(row["work_id"])
            if current is None or (is_published(dict(row)) and not is_published(current)):
                heads[row["work_id"]] = dict(row)
        return {wid: row["id"] for wid, row in heads.items()}

    def _settle_work_head(self, research_id: str, work_id: str) -> None:
        """Give a new head the selection its work already had in this research.

        When a published record joins a work whose preprint was screened or chosen, the head has no decision of its own
        yet; it takes the other record's user choice, else its model proposal. A head with its own decision keeps it.
        """
        head = self.work_heads(research_id).get(work_id)
        if head is None:
            return
        current = self.conn.execute("SELECT * FROM selections WHERE research_id = ? AND source_version_id = ?", (research_id, head)).fetchone()
        if current is None or current["origin"] != "default":
            return
        source = self.conn.execute(
            "SELECT s.* FROM selections s JOIN source_versions v ON v.id = s.source_version_id"
            " JOIN candidates c ON c.research_id = s.research_id AND c.source_version_id = s.source_version_id"
            " JOIN corpus_memberships m ON m.research_id = s.research_id AND m.source_version_id = s.source_version_id AND m.removed_at IS NULL"
            " WHERE s.research_id = ? AND v.work_id = ? AND s.source_version_id != ? AND s.origin != 'default'"
            " ORDER BY s.origin = 'user' DESC, s.updated_at DESC LIMIT 1", (research_id, work_id, head)
        ).fetchone()
        if source is None:
            return
        self.conn.execute(
            "UPDATE selections SET state = ?, origin = ?, user_reason = ?, proposal = ?, proposal_reason = ?, proposal_basis = ?,"
            " proposal_step_id = ?, version = version + 1, updated_at = ? WHERE research_id = ? AND source_version_id = ?",
            (source["state"], source["origin"], source["user_reason"], source["proposal"], source["proposal_reason"],
             source["proposal_basis"], source["proposal_step_id"], now(), research_id, head),
        )
        self.conn.execute(
            "INSERT INTO selection_history (research_id, source_version_id, old_state, new_state, origin, reason, created_at) VALUES (?, ?, ?, ?, ?, ?, ?)",
            (research_id, head, current["state"], source["state"], source["origin"], "taken from another version of the same work", now()),
        )
        self._bump_selection_revision(research_id, current["state"], source["state"])

    def included_works(self, research_id: str) -> list[str]:
        """Heads of the works included in the research: a work counts once, by its head's selection (D48)."""
        heads = set(self.work_heads(research_id).values())
        return [svid for svid in self.included_sources(research_id) if svid in heads]

    def work_versions(self, research_id: str, svid: str) -> list[str]:
        """The research's other versions of svid's work, those with a PDF in use first, then in the order found."""
        return [r[0] for r in self.conn.execute(
            "SELECT v.id FROM corpus_memberships m JOIN source_versions v ON v.id = m.source_version_id"
            " WHERE m.research_id = ? AND m.removed_at IS NULL AND v.id != ? AND v.work_id = (SELECT work_id FROM source_versions WHERE id = ?)"
            " ORDER BY EXISTS (SELECT 1 FROM source_assets a WHERE a.source_version_id = v.id AND a.removed_at IS NULL) DESC, m.created_at",
            (research_id, svid, svid)
        )]

    def answer_version(self, research_id: str, head: str) -> str:
        """The version of a work whose text an answer reads: the head when it has PDF text, else the first other version
        with PDF text, else the head's abstract (D48). One version per work, so versions never corroborate each other."""
        if self.has_pdf_text(head):
            return head
        return next((svid for svid in self.work_versions(research_id, head) if self.has_pdf_text(svid)), head)

    def has_pdf_text(self, svid: str) -> bool:
        return any(p["kind"] == "pdf_page" for p in self.passages_for(svid))

    def suspected_duplicates(self, research_id: str) -> dict[str, list[dict[str, str]]]:
        result: dict[str, list[dict[str, str]]] = {}
        for r in self.conn.execute(
            "SELECT source_version_id, other_source_version_id, basis FROM suspected_duplicates WHERE research_id = ?", (research_id,)
        ):
            result.setdefault(r[0], []).append({"source_version_id": r[1], "basis": r[2]})
            result.setdefault(r[1], []).append({"source_version_id": r[0], "basis": r[2]})
        return result

    def add_search_run(self, **fields: Any) -> str:
        srid = new_id("srn")
        fields = {"id": srid, **fields, "retrieved_at": now()}
        with transaction(self.conn):
            self.conn.execute(
                f"INSERT INTO search_runs ({', '.join(fields)}) VALUES ({', '.join('?' * len(fields))})", tuple(fields.values())
            )
            self._event(fields["research_id"], "search_recorded",
                        {"provider": fields["provider"], "status": fields["status"], "result_count": fields["result_count"]}, fields["run_id"])
        return srid

    def add_to_corpus(self, research_id: str, svid: str, added_by: str, search_run_id: str | None = None,
                      rank: int | None = None, selection_state: str = "pending", selection_origin: str = "default",
                      scope_revision: int | None = None, candidate: bool = True) -> None:
        ts = now()
        with transaction(self.conn):
            membership = self.conn.execute(
                "SELECT removed_at FROM corpus_memberships WHERE research_id = ? AND source_version_id = ?", (research_id, svid)
            ).fetchone()
            # A search or a Zotero collection import adds many records at once; it never undoes the user's removal (D50).
            bulk = added_by in ("search", "zotero_import")
            if membership is None:
                # A new version of a work the user removed from this research joins it removed.
                work_removed = bulk and self.conn.execute(
                    "SELECT MIN(m.removed_at IS NOT NULL) FROM corpus_memberships m JOIN source_versions v ON v.id = m.source_version_id"
                    " WHERE m.research_id = ? AND v.work_id = (SELECT work_id FROM source_versions WHERE id = ?)", (research_id, svid)
                ).fetchone()[0] == 1
                self.conn.execute(
                    "INSERT INTO corpus_memberships (research_id, source_version_id, added_by, created_at, removed_at, found_again_at)"
                    " VALUES (?, ?, ?, ?, ?, ?)", (research_id, svid, added_by, ts, *((ts, ts) if work_removed else (None, None))),
                )
            elif membership["removed_at"] is not None and bulk:
                # Found again: it stays removed, and the Sources summary counts it (D50).
                self.conn.execute("UPDATE corpus_memberships SET found_again_at = ? WHERE research_id = ? AND source_version_id = ?",
                                  (ts, research_id, svid))
            if added_by == "search" and candidate:
                # A record found again under a newer question revision becomes a candidate of that revision; found again
                # under the same revision (another query or provider), it keeps its best rank and the search that gave it.
                self.conn.execute(
                    "INSERT INTO candidates (id, research_id, search_run_id, source_version_id, rank, scope_revision, created_at)"
                    " VALUES (?, ?, ?, ?, ?, ?, ?) ON CONFLICT (research_id, source_version_id) DO UPDATE SET"
                    " search_run_id = CASE WHEN candidates.scope_revision = excluded.scope_revision AND candidates.rank <= excluded.rank"
                    " THEN candidates.search_run_id ELSE excluded.search_run_id END,"
                    " rank = CASE WHEN candidates.scope_revision = excluded.scope_revision AND candidates.rank <= excluded.rank"
                    " THEN candidates.rank ELSE excluded.rank END, scope_revision = excluded.scope_revision",
                    (new_id("cnd"), research_id, search_run_id, svid, rank, scope_revision, ts),
                )
            inserted = self.conn.execute(
                "INSERT OR IGNORE INTO selections (research_id, source_version_id, state, origin, updated_at) VALUES (?, ?, ?, ?, ?)",
                (research_id, svid, selection_state, selection_origin, ts),
            ).rowcount
            if inserted:
                self.conn.execute(
                    "INSERT INTO selection_history (research_id, source_version_id, old_state, new_state, origin, created_at) VALUES (?, ?, NULL, ?, ?, ?)",
                    (research_id, svid, selection_state, selection_origin, ts),
                )
                self._bump_selection_revision(research_id, None, selection_state)

    def remove_sources(self, research_id: str, svids: list[str], note: str | None) -> list[str]:
        """Take sources out of the research; returns the source versions removed (D50).

        The membership row stays, so the research's answers and cells still open what they cite, and nothing about the
        source, its files, passages or embeddings changes. Removing a work's head removes every version of the work here.
        """
        with transaction(self.conn):
            self._check_corpus_change(research_id, svids)
            heads = set(self.work_heads(research_id).values())
            chosen: list[str] = []
            for svid in dict.fromkeys(svids):
                if not self.is_active_member(research_id, svid):
                    continue
                chosen += [svid] + (self.work_versions(research_id, svid) if svid in heads else [])
            chosen = list(dict.fromkeys(chosen))
            if not chosen:
                return []
            ts = now()
            self.conn.executemany(
                "UPDATE corpus_memberships SET removed_at = ?, removal_note = ?, found_again_at = NULL WHERE research_id = ? AND source_version_id = ?",
                [(ts, (note or "").strip() or None, research_id, svid) for svid in chosen],
            )
            self._corpus_changed(research_id, "source_removed", chosen, ts)
        return chosen

    def restore_sources(self, research_id: str, svids: list[str]) -> list[str]:
        """Put removed sources back; returns the source versions restored.

        A version comes back with the versions of its work removed in the same action, and with its work's head when that
        was removed, so a version never shows without its record.
        """
        with transaction(self.conn):
            self._check_corpus_change(research_id, svids)
            removed = {r[0]: r[1] for r in self.conn.execute(
                "SELECT source_version_id, removed_at FROM corpus_memberships WHERE research_id = ? AND removed_at IS NOT NULL", (research_id,))}
            heads = self.work_heads(research_id, include_removed=True)

            def group(svid: str) -> list[str]:
                return [other for other, at in removed.items() if at == removed[svid]
                        and self.source(other)["work_id"] == self.source(svid)["work_id"]]

            chosen: list[str] = []
            for svid in dict.fromkeys(svids):
                if svid not in removed:
                    continue
                chosen += group(svid)
                head = heads.get(self.source(svid)["work_id"])
                if head in removed:
                    chosen += group(head)
            chosen = list(dict.fromkeys(chosen))
            if not chosen:
                return []
            self.conn.executemany(
                "UPDATE corpus_memberships SET removed_at = NULL, removal_note = NULL, found_again_at = NULL"
                " WHERE research_id = ? AND source_version_id = ?", [(research_id, svid) for svid in chosen],
            )
            self._corpus_changed(research_id, "source_restored", chosen, now())
        return chosen

    def _check_corpus_change(self, research_id: str, svids: list[str]) -> None:
        self.research(research_id)
        if self.conn.execute(
            f"SELECT 1 FROM runs WHERE research_id = ? AND status IN ({', '.join('?' * len(ACTIVE_RUN_STATUSES))}) LIMIT 1",
            (research_id, *ACTIVE_RUN_STATUSES),
        ).fetchone():
            raise RevisionConflict("Cancel or finish active runs before changing this research's sources")
        if missing := [svid for svid in dict.fromkeys(svids) if not self.was_member(research_id, svid)]:
            raise NotASource(", ".join(missing))

    def _corpus_changed(self, research_id: str, event: str, svids: list[str], ts: str) -> None:
        """An included source entering or leaving the corpus changes what an answer reads, as a selection change does."""
        marks = ", ".join("?" * len(svids))
        included = self.conn.execute(
            f"SELECT 1 FROM selections WHERE research_id = ? AND state = 'included' AND source_version_id IN ({marks}) LIMIT 1",
            (research_id, *svids),
        ).fetchone()
        self.conn.execute(f"UPDATE researches SET updated_at = ?{', selection_revision = selection_revision + 1' if included else ''}"
                          " WHERE id = ?", (ts, research_id))
        self._event(research_id, event, {"source_version_ids": svids})

    def is_active_member(self, research_id: str, svid: str) -> bool:
        """A source of the research now: lists, model inputs and new work (uploads, PDF lookups, table rows) need this."""
        return self.conn.execute(
            "SELECT 1 FROM corpus_memberships WHERE research_id = ? AND source_version_id = ? AND removed_at IS NULL", (research_id, svid)
        ).fetchone() is not None

    def was_member(self, research_id: str, svid: str) -> bool:
        """A source of the research now or before a removal (D50): opening the research's evidence needs only this."""
        return self.conn.execute(
            "SELECT 1 FROM corpus_memberships WHERE research_id = ? AND source_version_id = ?", (research_id, svid)
        ).fetchone() is not None

    def candidates(self, research_id: str, scope_revision: int | None = None) -> list[dict[str, Any]]:
        """Candidates of one question revision (all when None); ones without a proposal come first.

        Within that, candidates interleave by their rank in their search, so a candidate limit keeps every query's
        first results instead of only the earliest query's.
        """
        revision_filter = " AND c.scope_revision = ?" if scope_revision is not None else ""
        params = (research_id, scope_revision) if scope_revision is not None else (research_id,)
        rows = self.conn.execute(
            "SELECT c.id AS candidate_id, c.source_version_id, c.rank, s.state, s.origin FROM candidates c"
            " JOIN selections s ON s.research_id = c.research_id AND s.source_version_id = c.source_version_id"
            f" WHERE c.research_id = ?{revision_filter} ORDER BY s.proposal IS NOT NULL, c.rank, c.created_at", params
        ).fetchall()
        return [dict(r) for r in rows]

    def apply_screening_proposal(self, research_id: str, svid: str, proposal: str, reason: str, basis: str, step_id: str) -> None:
        """Record the proposal; change state only when the user has not decided."""
        state = {"include": "included", "exclude": "excluded"}.get(proposal, "pending")
        with transaction(self.conn):
            current = self.conn.execute(
                "SELECT * FROM selections WHERE research_id = ? AND source_version_id = ?", (research_id, svid)
            ).fetchone()
            if current["proposal_step_id"] == step_id:
                return  # already applied by this step, e.g. when a run resumes after a restart
            if current["origin"] == "user":
                self.conn.execute(
                    "UPDATE selections SET proposal = ?, proposal_reason = ?, proposal_basis = ?, proposal_step_id = ? WHERE research_id = ? AND source_version_id = ?",
                    (proposal, reason, basis, step_id, research_id, svid),
                )
                return
            self.conn.execute(
                "UPDATE selections SET state = ?, origin = 'model_proposal', proposal = ?, proposal_reason = ?, proposal_basis = ?,"
                " proposal_step_id = ?, version = version + 1, updated_at = ? WHERE research_id = ? AND source_version_id = ?",
                (state, proposal, reason, basis, step_id, now(), research_id, svid),
            )
            self.conn.execute(
                "INSERT INTO selection_history (research_id, source_version_id, old_state, new_state, origin, reason, created_at) VALUES (?, ?, ?, ?, 'model_proposal', ?, ?)",
                (research_id, svid, current["state"], state, reason, now()),
            )
            self._bump_selection_revision(research_id, current["state"], state)

    def set_research_title(self, research_id: str, scope_revision: int, title: str) -> None:
        """Apply a discovery-time title for the active question revision. A valid answer may rename it later."""
        with transaction(self.conn):
            self.conn.execute(
                "UPDATE researches SET title = ?, updated_at = ? WHERE id = ? AND current_scope_revision = ?",
                (title.strip(), now(), research_id, scope_revision),
            )

    def set_user_selection(self, research_id: str, svid: str, state: str, expected_version: int, reason: str | None) -> dict[str, Any]:
        with transaction(self.conn):
            current = self.conn.execute(
                "SELECT * FROM selections WHERE research_id = ? AND source_version_id = ?", (research_id, svid)
            ).fetchone()
            if current is None:
                raise NotFound(svid)
            check_expected_version(expected_version, current["version"])
            self.conn.execute(
                "UPDATE selections SET state = ?, origin = 'user', user_reason = ?, version = version + 1, updated_at = ?"
                " WHERE research_id = ? AND source_version_id = ?",
                (state, reason, now(), research_id, svid),
            )
            self.conn.execute(
                "INSERT INTO selection_history (research_id, source_version_id, old_state, new_state, origin, reason, created_at) VALUES (?, ?, ?, ?, 'user', ?, ?)",
                (research_id, svid, current["state"], state, reason, now()),
            )
            self._bump_selection_revision(research_id, current["state"], state)
            self.conn.execute("UPDATE researches SET updated_at = ? WHERE id = ?", (now(), research_id))
            self._event(research_id, "selection_changed", {"source_version_id": svid, "state": state, "origin": "user"})
        return dict(self.conn.execute(
            "SELECT * FROM selections WHERE research_id = ? AND source_version_id = ?", (research_id, svid)
        ).fetchone())

    def included_sources(self, research_id: str) -> list[str]:
        return [r[0] for r in self.conn.execute(
            "SELECT s.source_version_id FROM selections s JOIN corpus_memberships m"
            " ON m.research_id = s.research_id AND m.source_version_id = s.source_version_id AND m.removed_at IS NULL"
            " WHERE s.research_id = ? AND s.state = 'included' ORDER BY s.updated_at", (research_id,)
        )]

    def answer_order_facts(self, research_id: str, svids: list[str]) -> dict[str, tuple[bool, int]]:
        """Per source: whether the user chose its selection, and how many providers returned a record of it.

        bioRxiv is searched through OpenAlex, so the two count as one provider.
        """
        facts = {}
        for svid in svids:
            origin = self.conn.execute(
                "SELECT origin FROM selections WHERE research_id = ? AND source_version_id = ?", (research_id, svid)
            ).fetchone()
            providers = self.conn.execute(
                "SELECT COUNT(DISTINCT CASE provider WHEN 'biorxiv' THEN 'openalex' ELSE provider END) FROM identifier_mappings"
                " WHERE source_version_id = ? AND scheme = provider", (svid,)
            ).fetchone()[0]
            facts[svid] = (origin is not None and origin["origin"] == "user", providers)
        return facts

    def passages_for(self, svid: str) -> list[dict[str, Any]]:
        """Passages a model step may read: an abstract, or text of the PDF in use from its current extraction (D45).

        Passages of a removed file or of another extraction stay resolvable through `passage` for the evidence citing them.
        """
        return [dict(r) for r in self.conn.execute(
            "SELECT p.* FROM passages p WHERE p.source_version_id = ? AND (p.asset_id IS NULL OR EXISTS"
            " (SELECT 1 FROM source_assets a WHERE a.id = p.asset_id AND a.removed_at IS NULL AND a.extraction_version IS p.extraction_version))"
            " ORDER BY p.kind, p.physical_page, p.rowid", (svid,)
        )]

    def search_passages(self, svids: list[str], fts_query: str, limit: int) -> list[dict[str, Any]]:
        if not svids or not fts_query:
            return []
        marks = ",".join("?" * len(svids))
        rows = self.conn.execute(
            f"SELECT p.* FROM passages_fts f JOIN passages p ON p.rowid = f.rowid"
            f" WHERE passages_fts MATCH ? AND p.source_version_id IN ({marks}) AND (p.asset_id IS NULL OR EXISTS"
            f" (SELECT 1 FROM source_assets a WHERE a.id = p.asset_id AND a.removed_at IS NULL AND a.extraction_version IS p.extraction_version))"
            " ORDER BY bm25(passages_fts) LIMIT ?",
            (fts_query, *svids, limit),
        ).fetchall()
        return [dict(r) for r in rows]

    def passage(self, passage_id: str) -> dict[str, Any]:
        row = self.conn.execute("SELECT * FROM passages WHERE id = ?", (passage_id,)).fetchone()
        if row is None:
            raise NotFound(passage_id)
        return dict(row)

    # ---- answers --------------------------------------------------------------------------
    def latest_step_output(self, research_id: str, operation_key: str, scope_revision: int) -> dict[str, Any] | None:
        row = self.conn.execute(
            "SELECT s.output_json FROM run_steps s JOIN runs r ON r.id = s.run_id WHERE r.research_id = ? AND s.operation_key = ?"
            " AND r.scope_revision = ? AND s.status = 'succeeded' ORDER BY s.finished_at DESC LIMIT 1",
            (research_id, operation_key, scope_revision),
        ).fetchone()
        return json.loads(row["output_json"]) if row and row["output_json"] else None

    def step_input_selection_revision(self, step_input_id: str) -> int | None:
        row = self.conn.execute("SELECT selection_revision FROM step_inputs WHERE id = ?", (step_input_id,)).fetchone()
        return row["selection_revision"] if row else None

    def step_input_payload(self, step_input_id: str) -> dict[str, Any]:
        row = self.conn.execute("SELECT payload_json FROM step_inputs WHERE id = ?", (step_input_id,)).fetchone()
        if row is None:
            raise NotFound(step_input_id)
        return json.loads(row["payload_json"])

    def has_asset(self, svid: str) -> bool:
        return self.conn.execute(
            "SELECT 1 FROM source_assets WHERE source_version_id = ? AND removed_at IS NULL", (svid,)
        ).fetchone() is not None

    def passage_embeddings(self, passage_ids: list[str], model: str) -> dict[str, bytes]:
        found: dict[str, bytes] = {}
        for start in range(0, len(passage_ids), 500):
            chunk = passage_ids[start:start + 500]
            rows = self.conn.execute(
                f"SELECT passage_id, vector FROM passage_embeddings WHERE model = ? AND passage_id IN ({','.join('?' * len(chunk))})",
                (model, *chunk),
            )
            found.update({row["passage_id"]: row["vector"] for row in rows})
        return found

    def save_passage_embeddings(self, model: str, dimensions: int, vectors: dict[str, bytes]) -> None:
        ts = now()
        with transaction(self.conn):
            self.conn.executemany(
                "INSERT OR IGNORE INTO passage_embeddings (passage_id, model, dimensions, vector, created_at) VALUES (?, ?, ?, ?, ?)",
                [(pid, model, dimensions, blob, ts) for pid, blob in vectors.items()],
            )

    def scored_sources(self, research_id: str, scope_revision: int, model: str) -> set[str]:
        return {r[0] for r in self.conn.execute(
            "SELECT source_version_id FROM source_similarities WHERE research_id = ? AND scope_revision = ? AND model = ?",
            (research_id, scope_revision, model),
        )}

    def save_source_similarities(self, research_id: str, scope_revision: int, model: str, scores: dict[str, float]) -> None:
        ts = now()
        with transaction(self.conn):
            self.conn.executemany(
                "INSERT OR IGNORE INTO source_similarities (research_id, source_version_id, scope_revision, model, similarity, created_at)"
                " VALUES (?, ?, ?, ?, ?, ?)",
                [(research_id, svid, scope_revision, model, score, ts) for svid, score in scores.items()],
            )

    def save_answer(self, research_id: str, run_id: str, step_id: str | None, step_input_id: str | None, scope_revision: int,
                    status: str, draft: dict[str, Any] | None, validation: dict[str, Any],
                    links: list[dict[str, Any]] | None = None, selection_revision: int | None = None) -> str:
        aid = new_id("ans")
        with transaction(self.conn):
            existing = self.conn.execute(
                "SELECT id FROM answers WHERE run_id = ? AND IFNULL(step_input_id, '') = IFNULL(?, '') AND status = ?",
                (run_id, step_input_id, status),
            ).fetchone()
            if existing:
                return existing["id"]  # saved before a restart; a resumed run must not duplicate it
            report_version = self.conn.execute(
                "SELECT IFNULL(MAX(report_version), 0) + 1 FROM answers WHERE research_id = ?", (research_id,)
            ).fetchone()[0] if status == "structurally_valid" else None
            self.conn.execute(
                "INSERT INTO answers (id, research_id, run_id, step_id, step_input_id, scope_revision, selection_revision, status,"
                " answer_language, draft_json, validation_json, report_version, created_at) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)",
                (aid, research_id, run_id, step_id, step_input_id, scope_revision, selection_revision, status,
                 (draft or {}).get("answer_language"), dumps(draft) if draft is not None else None, dumps(validation), report_version, now()),
            )
            if status == "structurally_valid" and draft is not None:
                claim_ids = {}
                for ordinal, claim in enumerate(draft.get("claims", [])):
                    cid = new_id("clm")
                    claim_ids[claim["claim_label"]] = cid
                    self.conn.execute(
                        "INSERT INTO claims (id, answer_id, label, ordinal, text, support_type, section) VALUES (?, ?, ?, ?, ?, ?, ?)",
                        (cid, aid, claim["claim_label"], ordinal, claim["text"], claim["support_type"], claim.get("section")),
                    )
                for link in links or []:
                    self.conn.execute(
                        "INSERT INTO evidence_links (id, claim_id, passage_id, source_version_id, step_input_id, anchor_text, anchor_match)"
                        " VALUES (?, ?, ?, ?, ?, ?, ?)",
                        (new_id("evl"), claim_ids[link["claim_label"]], link["passage_id"], link["source_id"], step_input_id,
                         link.get("anchor_text"), link.get("anchor_match")),
                    )
                # Only a valid answer for the active question revision may replace the provisional question-as-title.
                self.conn.execute(
                    "UPDATE researches SET title = ? WHERE id = ? AND current_scope_revision = ?",
                    (draft["title"], research_id, scope_revision),
                )
            self.conn.execute("UPDATE researches SET updated_at = ? WHERE id = ?", (now(), research_id))
            self._event(research_id, "answer_saved", {"answer_id": aid, "status": status}, run_id)
        return aid

    def answer_review(self, answer_id: str) -> dict[str, Any] | None:
        row = self.conn.execute("SELECT * FROM answer_reviews WHERE answer_id = ?", (answer_id,)).fetchone()
        if row is None:
            return None
        review = dict(row)
        review["review"] = json.loads(review.pop("review_json")) if review["review_json"] else None
        return review

    def save_answer_review(self, answer_id: str, research_id: str, run_id: str, step_id: str | None, step_input_id: str | None,
                           status: str, review: dict[str, Any] | None, failure_reason: str | None = None) -> None:
        with transaction(self.conn):
            inserted = self.conn.execute(
                "INSERT OR IGNORE INTO answer_reviews (id, answer_id, research_id, run_id, step_id, step_input_id, status,"
                " failure_reason, review_json, created_at) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)",
                (new_id("rvw"), answer_id, research_id, run_id, step_id, step_input_id, status, failure_reason,
                 dumps(review) if review is not None else None, now()),
            ).rowcount
            if inserted:  # a resumed run finds the review it already saved
                self._event(research_id, "answer_reviewed", {"answer_id": answer_id, "status": status, "failure_reason": failure_reason}, run_id)

    # ---- app settings -----------------------------------------------------------------------
    def setting(self, key: str) -> Any:
        row = self.conn.execute("SELECT value_json FROM app_settings WHERE key = ?", (key,)).fetchone()
        return json.loads(row["value_json"]) if row else None

    def set_setting(self, key: str, value: Any) -> None:
        with transaction(self.conn):
            self.conn.execute(
                "INSERT INTO app_settings (key, value_json, updated_at) VALUES (?, ?, ?)"
                " ON CONFLICT(key) DO UPDATE SET value_json = excluded.value_json, updated_at = excluded.updated_at",
                (key, dumps(value), now()),
            )
