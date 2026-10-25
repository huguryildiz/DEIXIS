"""Append-only review records and narrow research-purge hooks."""

from __future__ import annotations

import copy
import json
import re
import sqlite3
from dataclasses import dataclass

from deixis.domain.canonical import canonical_json, sha256_hex
from deixis.domain.contracts import locate_anchor
from deixis.domain.rules import RevisionConflict
from deixis.storage.db import new_id, now, transaction
from deixis.workflow.store import NotFound

TARGET_KINDS = ("answer", "report", "candidate")
FOCUSES = ("source_support", "assumptions_and_consistency")
DECISIONS = ("accepted", "dismissed", "deferred")


class ReviewRefusal(Exception):
    def __init__(self, status_code, code, detail, **extra_fields):
        super().__init__(detail)
        self.status_code = status_code
        self.code = code
        self.detail = detail
        self.extra_fields = extra_fields


class SnapshotDependencyUnreadable(ReviewRefusal, ValueError):
    """Dependency protection cannot safely interpret a stored snapshot."""

    def __init__(self, detail):
        super().__init__(409, "snapshot_dependency_unreadable", detail)
        self.detail = "A stored review snapshot could not be read, so nothing was deleted."


class ReviewConflict(ReviewRefusal, RevisionConflict):
    def __init__(self, code, detail):
        super().__init__(409, code, detail)


@dataclass(frozen=True)
class ResolvedFinding:
    finding_json: dict
    step_input_id: str

    def __getitem__(self, key):
        return self.finding_json[key]


def _snapshot_source_ids(snapshot_id, content_json):
    try:
        content = json.loads(content_json)
        if not isinstance(content, dict) or type(content.get("version")) is not int or content["version"] != 1:
            raise ValueError("unknown snapshot version")
        referenced = set()
        for field, key in (("sources", "source_id"), ("evidence_manifest", "source_version_id")):
            entries = content[field]
            if not isinstance(entries, list):
                raise ValueError(f"malformed {field}")
            for entry in entries:
                if not isinstance(entry, dict) or not isinstance(entry.get(key), str) or not entry[key]:
                    raise ValueError(f"malformed {field} entry")
                if field == "sources":
                    for k in ("source_id", "work_id", "title", "authors", "year", "doi", "version_label", "access_level", "reading_depth"):
                        if k not in entry:
                            raise ValueError(f"missing source {k}")
                    if not isinstance(entry["authors"], list) or not isinstance(entry["work_id"], str) or not isinstance(entry["title"], str):
                        raise ValueError("malformed source metadata")
                else:
                    for k in ("passage_id", "text_digest", "asset_id", "asset_sha256", "extraction_version",
                              "passage_extraction_id", "current_extraction_id_at_snapshot", "evidence_status"):
                        if k not in entry:
                            raise ValueError(f"missing manifest {k}")
                    if (not isinstance(entry["passage_id"], str) or not isinstance(entry["text_digest"], str)
                            or re.fullmatch(r"[0-9a-f]{64}", entry["text_digest"]) is None):
                        raise ValueError("malformed passage identity")
                    for k in ("asset_id", "asset_sha256", "extraction_version", "passage_extraction_id", "current_extraction_id_at_snapshot"):
                        if entry[k] is not None and not isinstance(entry[k], str):
                            raise ValueError(f"malformed manifest {k}")
                    if entry["evidence_status"] not in {"current", "pdf_replaced", "pdf_removed", "text_superseded"}:
                        raise ValueError("unknown evidence state")
                referenced.add(entry[key])
        return referenced
    except (ValueError, KeyError, TypeError) as exc:
        raise SnapshotDependencyUnreadable(f"snapshot {snapshot_id}: {exc}") from exc


def snapshot_referenced_source_versions(conn, svids) -> set[str]:
    referenced = set()
    for row in conn.execute("SELECT id, content_json FROM owner_review_snapshots"):
        referenced.update(_snapshot_source_ids(*row))
    return referenced & set(svids)


def purge_owner_reviews(conn, research_id):
    # A reviewed version need not have its own corpus membership (for example an
    # alternate version read by an answer). Its owner purge must collect it too.
    source_ids = set()
    for row in conn.execute("SELECT id, content_json FROM owner_review_snapshots WHERE research_id = ?", (research_id,)):
        source_ids.update(_snapshot_source_ids(*row))
    conn.execute(
        "DELETE FROM owner_review_decisions WHERE finding_id IN (SELECT f.id FROM owner_review_findings f"
        " JOIN owner_reviews r ON r.id = f.review_id WHERE r.research_id = ?)", (research_id,),
    )
    conn.execute("DELETE FROM owner_review_findings WHERE review_id IN (SELECT id FROM owner_reviews WHERE research_id = ?)", (research_id,))
    conn.execute("DELETE FROM owner_reviews WHERE research_id = ?", (research_id,))
    conn.execute("DELETE FROM owner_review_snapshots WHERE research_id = ?", (research_id,))
    return source_ids


def resolve_finding(content, step_input, finding):
    """Resolve only snapshot targets and source-owned exact/normalized quotes from this call."""
    ref = finding["target_ref"]
    kind, label = ref["kind"], ref["ref"]
    choices = {"answer": {"claim", "whole"}, "report": {"claim", "section", "whole"},
               "candidate": {"candidate_element", "whole"}}[step_input["review_input"]["target_kind"]]
    if kind not in choices or (kind == "whole") != (label is None):
        raise ValueError("invalid review target")
    records = {"claim": ("claims", "claim_ref", "claim_id"), "section": ("sections", "section_ref", "record_id"),
               "candidate_element": ("elements", "element_ref", "record_id")}
    target = {"kind": kind, "ref": label, "record_id": None, "text_at_snapshot": None}
    if kind != "whole":
        allow_key = {"claim": "claim_refs", "section": "section_refs", "candidate_element": "element_refs"}[kind]
        if label not in step_input["allowlist"].get(allow_key, []):
            raise ValueError("target outside this call")
        array, key, record_key = records[kind]
        rows = [r for r in content[array] if r[key] == label]
        if len(rows) != 1:
            raise ValueError("target does not resolve uniquely")
        row = rows[0]
        target.update(record_id=row[record_key], text_at_snapshot=row.get("text") if kind != "section" else
                      "\n".join(c["text"] for c in content["claims"] if c["section_ref"] == label))
    passages = {p["passage_id"]: p for p in step_input["passages"]}
    result = copy.deepcopy(finding) | {"target": target,
        "group_index": step_input["review_input"]["group_index"],
        "group_count": step_input["review_input"]["group_count"]}
    if "evidence" in finding:
        evidence = []
        for item in finding["evidence"]:
            pid = item["passage_handle"]
            if pid not in step_input["allowlist"]["passage_ids"] or pid not in passages:
                raise ValueError("passage outside this call")
            passage = passages[pid]
            anchor = locate_anchor(item["anchor"], passage["text"])
            if anchor is None or anchor.kind not in {"exact", "normalized"}:
                raise ValueError("review anchor is not exact or normalized")
            evidence.append({"passage_id": pid, "source_version_id": passage["source_id"],
                             "anchor_text": anchor.text, "anchor_match": anchor.kind})
        result["evidence"] = evidence
    return ResolvedFinding(result, step_input["step_input_id"])


def applied_matches_suggestion(finding_json, revision_text):
    if isinstance(finding_json, ResolvedFinding):
        finding_json = finding_json.finding_json
    finding = json.loads(finding_json) if isinstance(finding_json, str) else finding_json
    suggestion = finding.get("suggested_fix")
    return suggestion is not None and " ".join(suggestion.split()) == " ".join(revision_text.split())


class ReviewStore:
    def __init__(self, conn: sqlite3.Connection, reader=None):
        self.conn = conn
        self._reader = reader

    def _visible(self, research_id):
        if not self.conn.execute("SELECT 1 FROM researches WHERE id = ? AND trashed_at IS NULL", (research_id,)).fetchone():
            raise NotFound(research_id)

    def add_snapshot(self, content, markers):
        snapshot_id = new_id("rvs")
        with transaction(self.conn):
            self._visible(content["research_id"])
            self.conn.execute(
                "INSERT INTO owner_review_snapshots (id, research_id, target_kind, target_id, content_json, content_sha256, markers_json, created_at)"
                " VALUES (?, ?, ?, ?, ?, ?, ?, ?)",
                (snapshot_id, content["research_id"], content["target_kind"], content["target_id"],
                 canonical_json(content), sha256_hex(content), canonical_json(markers), now()),
            )
        return snapshot_id

    def snapshot(self, snapshot_id):
        row = self.conn.execute("SELECT * FROM owner_review_snapshots WHERE id = ?", (snapshot_id,)).fetchone()
        if row is None:
            raise NotFound(snapshot_id)
        self._visible(row["research_id"])
        return dict(row) | {"content": json.loads(row["content_json"]), "markers": json.loads(row["markers_json"])}

    def create_review(self, research_id, snapshot_id, run_id, *, focus, owner_note=None,
                      requested_connection, requested_model=None, requested_effort=None, idempotency_key=None):
        if focus not in FOCUSES or owner_note is not None and (not owner_note.strip() or len(owner_note) > 500):
            raise ValueError("invalid focus or owner note")
        with transaction(self.conn):
            self._visible(research_id)
            fields = {"research_id": research_id, "snapshot_id": snapshot_id, "run_id": run_id, "focus": focus,
                      "owner_note": owner_note, "requested_connection": requested_connection,
                      "requested_model": requested_model, "requested_effort": requested_effort}
            if idempotency_key:
                old = self.conn.execute("SELECT * FROM owner_reviews WHERE idempotency_key = ?", (idempotency_key,)).fetchone()
                if old:
                    if any(old[k] != v for k, v in fields.items()):
                        raise RevisionConflict("This idempotency key was used for another review request")
                    return dict(old)
            review_id = new_id("orv")
            self.conn.execute(
                "INSERT INTO owner_reviews (id, research_id, snapshot_id, run_id, focus, owner_note, requested_connection, requested_model, requested_effort, idempotency_key, created_at)"
                " VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)",
                (review_id, *fields.values(), idempotency_key, now()),
            )
            return dict(self.conn.execute("SELECT * FROM owner_reviews WHERE id = ?", (review_id,)).fetchone())

    def _review(self, review_id):
        row = self.conn.execute("SELECT * FROM owner_reviews WHERE id = ?", (review_id,)).fetchone()
        if row is None:
            raise NotFound(review_id)
        self._visible(row["research_id"])
        return dict(row)

    def set_not_reviewed(self, review_id, rows):
        with transaction(self.conn):
            self._review(review_id)
            self.conn.execute("UPDATE owner_reviews SET sections_not_reviewed_json = ? WHERE id = ?", (canonical_json(rows), review_id))

    def set_failure(self, review_id, reason):
        with transaction(self.conn):
            self._review(review_id)
            self.conn.execute("UPDATE owner_reviews SET failure_reason = ? WHERE id = ?", (reason, review_id))

    def add_findings(self, review_id, rows):
        rows = list(rows)
        if any(not isinstance(row, ResolvedFinding) for row in rows):
            raise TypeError("findings must come from resolve_finding")
        ids = []
        with transaction(self.conn):
            self._review(review_id)
            ordinal = self.conn.execute("SELECT COALESCE(MAX(ordinal), 0) FROM owner_review_findings WHERE review_id = ?", (review_id,)).fetchone()[0]
            for row in rows:
                ordinal += 1
                finding_id = new_id("orf")
                self.conn.execute(
                    "INSERT INTO owner_review_findings (id, review_id, ordinal, finding_json, step_input_id) VALUES (?, ?, ?, ?, ?)",
                    (finding_id, review_id, ordinal, canonical_json(row.finding_json), row.step_input_id),
                )
                ids.append(finding_id)
        return ids

    def add_group_findings(self, review_id, step_input_id, resolved):
        resolved = list(resolved)
        if any(not isinstance(row, ResolvedFinding) or row.step_input_id != step_input_id for row in resolved):
            raise TypeError("group findings must resolve from the group's StepInput")
        with transaction(self.conn):
            self._review(review_id)
            if self.conn.execute("SELECT 1 FROM owner_review_findings WHERE review_id = ? AND step_input_id = ?",
                                 (review_id, step_input_id)).fetchone():
                return []
            return self.add_findings(review_id, resolved)

    def findings(self, review_id):
        self._review(review_id)
        return [dict(r) | {"finding": json.loads(r["finding_json"])} for r in self.conn.execute(
            "SELECT * FROM owner_review_findings WHERE review_id = ? ORDER BY ordinal", (review_id,),
        )]

    def decision_request(self, key, request_hash):
        old = self.conn.execute("SELECT * FROM owner_review_decisions WHERE idempotency_key = ?", (key,)).fetchone()
        if old is not None and old["request_hash"] != request_hash:
            raise ReviewConflict("idempotency_key_reused", "This key was used for a different review command.")
        return dict(old) if old is not None else None

    def add_decision(self, finding_id, decision, reason=None, applied_ref=None, *,
                     idempotency_key=None, request_hash=None, expected_ordinal=None):
        if decision not in DECISIONS or decision == "dismissed" and (reason is None or not reason.strip()):
            raise ValueError("dismissed needs a reason and decision must be known")
        if applied_ref is not None and decision != "accepted":
            raise ValueError("only accepted decisions can name an applied revision")
        with transaction(self.conn):
            finding, review = self._finding_review(finding_id)
            if idempotency_key is not None:
                replay = self.decision_request(idempotency_key, request_hash)
                if replay is not None:
                    return replay
            current = self.current_decision(finding_id)
            if expected_ordinal is not None and expected_ordinal != (current["ordinal"] if current else 0):
                raise ReviewConflict("decision_changed", "The finding's decision changed. Read it again before deciding.")
            if applied_ref is not None:
                self._check_applied(finding, review, applied_ref)
            ordinal = self.conn.execute("SELECT COALESCE(MAX(ordinal), 0) + 1 FROM owner_review_decisions WHERE finding_id = ?", (finding_id,)).fetchone()[0]
            decision_id = new_id("ord")
            self.conn.execute(
                "INSERT INTO owner_review_decisions (id, finding_id, ordinal, decision, reason, applied_ref, created_at, idempotency_key, request_hash) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)",
                (decision_id, finding_id, ordinal, decision, reason, applied_ref, now(), idempotency_key, request_hash),
            )
        return dict(self.conn.execute("SELECT * FROM owner_review_decisions WHERE id = ?", (decision_id,)).fetchone())

    def _finding_review(self, finding_id):
        finding = self.conn.execute("SELECT * FROM owner_review_findings WHERE id = ?", (finding_id,)).fetchone()
        if finding is None:
            raise NotFound(finding_id)
        return dict(finding), self._review(finding["review_id"])

    def _check_applied(self, finding, review, applied_ref):
        content = self.snapshot(review["snapshot_id"])["content"]
        saved = json.loads(finding["finding_json"])
        ref = saved["target_ref"]
        if content["target_kind"] != "report" or ref["kind"] != "claim":
            raise ValueError("applied_ref requires a report claim; no change was made to an answer")
        claim = next((c for c in content["claims"] if c["claim_ref"] == ref["ref"]), None)
        if claim is None:
            raise ValueError("applied_ref must name a later human revision of the target claim")
        if self._reader is None:
            raise ValueError("applied_ref requires a ReviewReader")
        revision = next((r for r in self._reader.report_claim_revisions(claim["claim_id"])
                         if r["id"] == applied_ref), None)
        if (claim is None or revision is None or revision["claim_id"] != claim["claim_id"]
                or revision["kind"] not in {"human_edit", "human_restore"} or revision["created_at"] < review["created_at"]):
            raise ValueError("applied_ref must name a later human revision of the target claim")
        links = set(revision["link_ids"]) if revision["link_ids"] is not None else {
            r["id"] for r in self._reader.report_original_links(claim["claim_id"])}
        if revision["text"] == claim["text"] and links == {e["link_id"] for e in claim["citations"]}:
            raise ValueError("applied_ref changes neither snapshot text nor citations")

    def decisions(self, finding_id):
        self._finding_review(finding_id)
        return [dict(r) for r in self.conn.execute("SELECT * FROM owner_review_decisions WHERE finding_id = ? ORDER BY ordinal", (finding_id,))]

    def current_decision(self, finding_id):
        rows = self.decisions(finding_id)
        return rows[-1] if rows else None

    def reviews_for_target(self, research_id, target_kind, target_id):
        return [dict(r) for r in self.conn.execute(
            "SELECT r.* FROM owner_reviews r JOIN owner_review_snapshots s ON s.id = r.snapshot_id"
            " JOIN researches q ON q.id = r.research_id WHERE r.research_id = ? AND s.target_kind = ?"
            " AND s.target_id = ? AND q.trashed_at IS NULL ORDER BY r.created_at DESC, r.id DESC",
            (research_id, target_kind, target_id),
        )]
