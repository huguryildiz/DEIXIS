"""Persistence operations for researches, runs, sources, selections and answers.

All writes happen in short synchronous transactions on one connection; callers
never await inside a transaction, so the API and worker can share the connection
on the event-loop thread. UI-visible events are written in the same transaction
as the state they describe.
"""

from __future__ import annotations

import hashlib
import json
import sqlite3
from typing import Any

from deixis.domain.rules import RevisionConflict, check_expected_version
from deixis.storage.db import dumps, new_id, now, row_dict, transaction

ACTIVE_RUN_STATUSES = ("queued", "running", "pause_requested")


class NotFound(Exception):
    pass


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
    ) -> str:
        rid, ts = new_id("res"), now()
        title = question.strip().splitlines()[0][:160]
        with transaction(self.conn):
            self.conn.execute(
                "INSERT INTO researches (id, title, created_at, updated_at) VALUES (?, ?, ?, ?)", (rid, title, ts, ts)
            )
            self.conn.execute(
                "INSERT INTO scope_revisions (research_id, revision, question, language_hint, source_scope, providers_json,"
                " effort, model_connection, requested_model, created_at) VALUES (?, 1, ?, ?, ?, ?, ?, ?, ?, ?)",
                (rid, question.strip(), language_hint, source_scope, dumps(providers), effort, model_connection, requested_model, ts),
            )
            self._event(rid, "research_created", {"scope_revision": 1})
        return rid

    def research(self, research_id: str) -> dict[str, Any]:
        row = self.conn.execute("SELECT * FROM researches WHERE id = ?", (research_id,)).fetchone()
        if row is None:
            raise NotFound(research_id)
        return dict(row)

    def selection_revision(self, research_id: str) -> int:
        return self.research(research_id)["selection_revision"]

    def _bump_selection_revision(self, research_id: str, old_state: str | None, new_state: str) -> None:
        if old_state != new_state and "included" in (old_state, new_state):
            self.conn.execute("UPDATE researches SET selection_revision = selection_revision + 1 WHERE id = ?", (research_id,))

    def list_researches(self) -> list[dict[str, Any]]:
        rows = self.conn.execute(
            "SELECT r.*, s.question, s.source_scope, s.effort,"
            " (SELECT status FROM runs WHERE research_id = r.id ORDER BY created_at DESC LIMIT 1) AS last_run_status,"
            " (SELECT COUNT(*) FROM answers WHERE research_id = r.id AND status = 'structurally_valid') AS answer_count"
            " FROM researches r JOIN scope_revisions s ON s.research_id = r.id AND s.revision = r.current_scope_revision"
            " ORDER BY r.updated_at DESC"
        ).fetchall()
        return [dict(r) for r in rows]

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
                " effort, model_connection, requested_model, steering, created_at) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)",
                (research_id, revision, question.strip(), current["language_hint"], current["source_scope"],
                 dumps(current["providers"]), current["effort"], current["model_connection"], current["requested_model"], steering, now()),
            )
            self.conn.execute(
                "UPDATE researches SET current_scope_revision = ?, version = version + 1, title = ?, updated_at = ? WHERE id = ?",
                (revision, question.strip().splitlines()[0][:160], now(), research_id),
            )
            self._event(research_id, "scope_revised", {"scope_revision": revision})
        return revision

    # ---- runs -------------------------------------------------------------------------
    def create_run(self, research_id: str, kind: str, budget: dict[str, Any], idempotency_key: str | None) -> dict[str, Any]:
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
            stage = "discovery" if kind == "discovery" else "inspection"
            self.conn.execute(
                "INSERT INTO runs (id, research_id, scope_revision, kind, status, stage, budget_json, idempotency_key, created_at, updated_at)"
                " VALUES (?, ?, ?, ?, 'queued', ?, ?, ?, ?, ?)",
                (run_id, research_id, research["current_scope_revision"], kind, stage, dumps(budget), idempotency_key, ts, ts),
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
                {"step_id": step_id, "kind": row["kind"], "operation_key": row["operation_key"], "status": status, "error_code": error_code},
                row["run_id"],
            )

    def run_steps(self, run_id: str) -> list[dict[str, Any]]:
        rows = self.conn.execute(
            "SELECT id, operation_key, kind, status, attempt, delivery_class, error_code, error_json, started_at, finished_at"
            " FROM run_steps WHERE run_id = ? ORDER BY rowid", (run_id,)
        ).fetchall()
        return [{**dict(r), "error": json.loads(r["error_json"]) if r["error_json"] else None} for r in rows]

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
        """Reuse only an exact provider-record mapping; DOI or title matches never merge records here."""
        existing = self.find_source_by_identifier(provider, record.provider_record_id)
        if existing:
            return existing, False
        ts = now()
        wid, svid = new_id("wrk"), new_id("srv")
        with transaction(self.conn):
            self.conn.execute("INSERT INTO works (id, created_at) VALUES (?, ?)", (wid, ts))
            self.conn.execute(
                "INSERT INTO source_versions (id, work_id, title, authors_json, year, venue, version_label, publication_type, doi,"
                " landing_url, oa_pdf_url, oa_pdf_version, origin, provider_payload_path, created_at)"
                " VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, 'provider', ?, ?)",
                (svid, wid, record.title, dumps(record.authors), record.year, record.venue, record.version_label,
                 record.publication_type, record.doi, record.landing_url, record.oa_pdf_url, record.oa_pdf_version, payload_path, ts),
            )
            mappings = [(provider, record.provider_record_id)] + ([("doi", record.doi)] if record.doi else [])
            for scheme, value in mappings:
                self.conn.execute(
                    "INSERT OR IGNORE INTO identifier_mappings (source_version_id, scheme, value, provider, retrieved_at) VALUES (?, ?, ?, ?, ?)",
                    (svid, scheme, value, provider, ts),
                )
            if record.abstract:
                self._insert_passage(svid, None, "abstract", None, None, record.abstract_origin, payload_path, None, record.abstract)
        return svid, True

    def create_upload_source(self, title: str) -> str:
        ts, wid, svid = now(), new_id("wrk"), new_id("srv")
        with transaction(self.conn):
            self.conn.execute("INSERT INTO works (id, created_at) VALUES (?, ?)", (wid, ts))
            self.conn.execute(
                "INSERT INTO source_versions (id, work_id, title, origin, version_label, created_at) VALUES (?, ?, ?, 'user_upload', 'uploaded file', ?)",
                (svid, wid, title, ts),
            )
        return svid

    def _insert_passage(self, svid: str, asset_id: str | None, kind: str, page: int | None, label: str | None,
                        abstract_origin: str | None, payload_ref: str | None, extraction_version: str | None, text: str) -> str:
        digest = hashlib.sha256(text.encode()).hexdigest()
        existing = self.conn.execute(
            "SELECT id FROM passages WHERE source_version_id = ? AND kind = ? AND IFNULL(asset_id, '') = IFNULL(?, '')"
            " AND IFNULL(physical_page, 0) = IFNULL(?, 0) AND text_sha256 = ?",
            (svid, kind, asset_id, page, digest),
        ).fetchone()
        if existing:
            return existing["id"]
        pid, ts = new_id("psg"), now()
        self.conn.execute(
            "INSERT INTO passages (id, source_version_id, asset_id, kind, physical_page, printed_label, abstract_origin, payload_ref,"
            " extraction_version, text, text_sha256, retrieved_at, created_at) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)",
            (pid, svid, asset_id, kind, page, label, abstract_origin, payload_ref, extraction_version, text, digest, ts, ts),
        )
        return pid

    def asset_by_sha(self, sha256: str) -> dict[str, Any] | None:
        return row_dict(self.conn.execute("SELECT * FROM source_assets WHERE sha256 = ? ORDER BY retrieved_at LIMIT 1", (sha256,)).fetchone())

    def asset(self, asset_id: str) -> dict[str, Any]:
        row = self.conn.execute("SELECT * FROM source_assets WHERE id = ?", (asset_id,)).fetchone()
        if row is None:
            raise NotFound(asset_id)
        return dict(row)

    def add_asset_with_pages(self, svid: str, sha256: str, size: int, storage_path: str, origin: str,
                             retrieved_from: str | None, filename: str | None, extraction: Any,
                             extraction_version: str, chunker: Any) -> str:
        aid = new_id("ast")
        with transaction(self.conn):
            self.conn.execute(
                "INSERT INTO source_assets (id, source_version_id, sha256, byte_size, media_type, storage_path, original_filename,"
                " retrieved_from, retrieved_at, origin, extraction_status, extraction_version, extraction_error, page_count)"
                " VALUES (?, ?, ?, ?, 'application/pdf', ?, ?, ?, ?, ?, ?, ?, ?, ?)",
                (aid, svid, sha256, size, storage_path, filename, retrieved_from, now(), origin,
                 extraction.status, extraction_version, extraction.error, extraction.page_count),
            )
            for page in extraction.pages:
                for start, end, text in chunker(page.text):
                    self._insert_passage(svid, aid, "pdf_page", page.physical_page, page.printed_label, None,
                                         f"chars:{start}-{end}", extraction_version, text)
        return aid

    def source(self, svid: str) -> dict[str, Any]:
        row = self.conn.execute("SELECT * FROM source_versions WHERE id = ?", (svid,)).fetchone()
        if row is None:
            raise NotFound(svid)
        source = dict(row)
        source["authors"] = json.loads(source.pop("authors_json"))
        return source

    # ---- research corpus -------------------------------------------------------------
    def record_search(self, search_fields: dict[str, Any], provider: str, records: list[Any], payload_path: str | None,
                      step_id: str, step_status: str, step_output: dict[str, Any] | None = None, **step_fields: Any) -> str:
        """Commit the search run, normalized sources, candidates and the step outcome together."""
        with transaction(self.conn):
            srid = self.add_search_run(**search_fields)
            for rank, record in enumerate(records):
                svid, _ = self.upsert_provider_source(provider, record, payload_path)
                self.add_to_corpus(search_fields["research_id"], svid, "search", srid, rank, scope_revision=search_fields["scope_revision"])
            output = {**step_output, "search_run_id": srid} if step_output is not None else None
            self.finish_step(step_id, step_status, output=output, **step_fields)
        return srid

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
                      scope_revision: int | None = None) -> None:
        ts = now()
        with transaction(self.conn):
            self.conn.execute(
                "INSERT OR IGNORE INTO corpus_memberships (research_id, source_version_id, added_by, created_at) VALUES (?, ?, ?, ?)",
                (research_id, svid, added_by, ts),
            )
            if added_by == "search":
                # A record found again under a newer question revision becomes a candidate of that revision.
                self.conn.execute(
                    "INSERT INTO candidates (id, research_id, search_run_id, source_version_id, rank, scope_revision, created_at)"
                    " VALUES (?, ?, ?, ?, ?, ?, ?) ON CONFLICT (research_id, source_version_id) DO UPDATE SET"
                    " search_run_id = excluded.search_run_id, rank = excluded.rank, scope_revision = excluded.scope_revision",
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

    def is_member(self, research_id: str, svid: str) -> bool:
        return self.conn.execute(
            "SELECT 1 FROM corpus_memberships WHERE research_id = ? AND source_version_id = ?", (research_id, svid)
        ).fetchone() is not None

    def candidates(self, research_id: str, scope_revision: int | None = None) -> list[dict[str, Any]]:
        """Candidates of one question revision (all when None); ones without a proposal come first."""
        revision_filter = " AND c.scope_revision = ?" if scope_revision is not None else ""
        params = (research_id, scope_revision) if scope_revision is not None else (research_id,)
        rows = self.conn.execute(
            "SELECT c.id AS candidate_id, c.source_version_id, c.rank, s.state, s.origin FROM candidates c"
            " JOIN selections s ON s.research_id = c.research_id AND s.source_version_id = c.source_version_id"
            f" WHERE c.research_id = ?{revision_filter} ORDER BY s.proposal IS NOT NULL, c.created_at, c.rank", params
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
            "SELECT source_version_id FROM selections WHERE research_id = ? AND state = 'included' ORDER BY updated_at", (research_id,)
        )]

    def passages_for(self, svid: str) -> list[dict[str, Any]]:
        return [dict(r) for r in self.conn.execute(
            "SELECT * FROM passages WHERE source_version_id = ? ORDER BY kind, physical_page, rowid", (svid,)
        )]

    def search_passages(self, svids: list[str], fts_query: str, limit: int) -> list[dict[str, Any]]:
        if not svids or not fts_query:
            return []
        marks = ",".join("?" * len(svids))
        rows = self.conn.execute(
            f"SELECT p.* FROM passages_fts f JOIN passages p ON p.rowid = f.rowid"
            f" WHERE passages_fts MATCH ? AND p.source_version_id IN ({marks}) ORDER BY bm25(passages_fts) LIMIT ?",
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
        return self.conn.execute("SELECT 1 FROM source_assets WHERE source_version_id = ?", (svid,)).fetchone() is not None

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
            self.conn.execute(
                "INSERT INTO answers (id, research_id, run_id, step_id, step_input_id, scope_revision, selection_revision, status,"
                " answer_language, draft_json, validation_json, created_at) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)",
                (aid, research_id, run_id, step_id, step_input_id, scope_revision, selection_revision, status,
                 (draft or {}).get("answer_language"), dumps(draft) if draft is not None else None, dumps(validation), now()),
            )
            if status == "structurally_valid" and draft is not None:
                claim_ids = {}
                for ordinal, claim in enumerate(draft.get("claims", [])):
                    cid = new_id("clm")
                    claim_ids[claim["claim_label"]] = cid
                    self.conn.execute(
                        "INSERT INTO claims (id, answer_id, label, ordinal, text, support_type) VALUES (?, ?, ?, ?, ?, ?)",
                        (cid, aid, claim["claim_label"], ordinal, claim["text"], claim["support_type"]),
                    )
                for link in links or []:
                    self.conn.execute(
                        "INSERT INTO evidence_links (id, claim_id, passage_id, source_version_id, step_input_id) VALUES (?, ?, ?, ?, ?)",
                        (new_id("evl"), claim_ids[link["claim_label"]], link["passage_id"], link["source_id"], step_input_id),
                    )
            self.conn.execute("UPDATE researches SET updated_at = ? WHERE id = ?", (now(), research_id))
            self._event(research_id, "answer_saved", {"answer_id": aid, "status": status}, run_id)
        return aid
