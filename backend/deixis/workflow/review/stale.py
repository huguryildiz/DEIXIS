"""Read-time comparisons against live tokens captured at the snapshot boundary."""

from __future__ import annotations

import hashlib
import json

from .reader import ReviewReader

REASONS = (
    "newer_answer", "scope_revised", "sources_added", "sources_removed", "selection_changed",
    "newer_report_version", "report_version_changed", "claim_edited", "claim_removed", "cell_changed",
    "rows_added", "rows_removed", "column_revised", "passage_changed", "asset_changed",
    "extraction_changed", "evidence_missing", "pdf_replaced", "pdf_removed", "text_superseded",
)


def markers_for(reader: ReviewReader, research_id, target_kind, target_id, content):
    with reader.consistent_read():
        research = reader.research(research_id)
        markers = {"scope_revision": research["current_scope_revision"]}
        if target_kind == "candidate":
            raise NotImplementedError("B8 owns candidate review stale tokens")
        if target_kind == "answer":
            latest = reader.latest_answer(research_id)
            markers.update({"latest_answer_id": latest,
                            "latest_answer_version": reader.answer(latest)["report_version"] if latest else None,
                            "included_sources": sorted(reader.included_sources(research_id)),
                            "selection_revision": research["selection_revision"],
                            "selection_stamp": reader.selection_stamp(research_id)})
        elif target_kind == "report":
            report = reader.report(target_id)
            markers.update({"latest_report_version": reader.latest_report_version(research_id, exclude_report_id=target_id),
                            "report_version": report["report_version"],
                            "claims": {c["claim_key"]: {"revision_id": c["current_revision_id"], "version": c["version"]}
                                       for c in reader.report_claims(target_id) if c["section_id"] != "II"},
                            "cells": {cid: row["current_revision_id"] for cid, row in reader.cells(
                                [c["cell_id"] for c in content["cells"]]).items()},
                            "columns": {cid: row["current_revision"] for cid, row in reader.columns(
                                [c["column_id"] for c in content["columns"]]).items()},
                            "rows": sorted(reader.included_rows(research_id, content["table_id"]))})
        else:
            raise ValueError(target_kind)
        return markers


def _targets(content, passage_id):
    targets = []
    for claim in content["claims"]:
        if any(e["passage_id"] == passage_id for e in claim["citations"]):
            targets.append({"kind": "claim", "ref": claim["claim_ref"]})
    for cell in content["cells"]:
        if any(e["passage_id"] == passage_id for e in cell["evidence"]):
            targets.append({"kind": "cell", "ref": cell["cell_id"]})
    return targets


def stale_reasons(reader: ReviewReader, snapshot_row) -> list[dict]:
    if snapshot_row["target_kind"] == "candidate":
        raise NotImplementedError("B8 owns candidate review stale reasons")
    content = snapshot_row.get("content") or json.loads(snapshot_row["content_json"])
    old = snapshot_row.get("markers") or json.loads(snapshot_row["markers_json"])
    reasons = []

    def add(code, **details):
        reasons.append({"code": code, **details})

    with reader.consistent_read():
        live = markers_for(reader, snapshot_row["research_id"], snapshot_row["target_kind"], snapshot_row["target_id"], content)
        if live["scope_revision"] != old["scope_revision"]:
            add("scope_revised")
        if snapshot_row["target_kind"] == "answer":
            if (live["latest_answer_version"] or 0) > (old["latest_answer_version"] or 0):
                add("newer_answer", answer_id=live["latest_answer_id"])
            before, after = set(old["included_sources"]), set(live["included_sources"])
            if after - before:
                add("sources_added", source_version_ids=sorted(after - before))
            if before - after:
                add("sources_removed", source_version_ids=sorted(before - after))
            if before == after and any(old[key] != live[key] for key in ("selection_stamp", "selection_revision")):
                add("selection_changed")
        else:
            if (live["latest_report_version"] or 0) > (old["latest_report_version"] or 0):
                add("newer_report_version", report_version=live["latest_report_version"])
            if live["report_version"] != old["report_version"]:
                add("report_version_changed")
            for ref, token in old["claims"].items():
                if ref not in live["claims"]:
                    add("claim_removed", claim_ref=ref)
                elif token != live["claims"][ref]:
                    add("claim_edited", claim_ref=ref)
            for cid, token in old["cells"].items():
                if live["cells"].get(cid) != token:
                    add("cell_changed", cell_id=cid)
            for cid, token in old["columns"].items():
                if live["columns"].get(cid) != token:
                    add("column_revised", column_id=cid)
            before, after = set(old["rows"]), set(live["rows"])
            if after - before:
                add("rows_added", source_version_ids=sorted(after - before))
            if before - after:
                add("rows_removed", source_version_ids=sorted(before - after))
        for entry in content["evidence_manifest"]:
            pid = entry["passage_id"]
            targets = _targets(content, pid)
            details = {"passage_id": pid, "targets": targets,
                       "target_ref": targets[0] if len(targets) == 1 else {"kind": "whole", "ref": None}}
            dep = reader.evidence_dependency(pid)
            missing = dep is None or not reader.evidence_exists(entry["asset_id"], entry["passage_extraction_id"])
            if missing:
                add("evidence_missing", **details)
            if dep is None:
                continue
            if hashlib.sha256(dep["text"].encode("utf-8")).hexdigest() != entry["text_digest"]:
                add("passage_changed", **details)
            if dep["asset_id"] != entry["asset_id"] or dep["asset_sha256"] != entry["asset_sha256"]:
                add("asset_changed", **details)
            if entry["asset_id"] is not None and dep["current_extraction_id_at_snapshot"] != entry["current_extraction_id_at_snapshot"]:
                add("extraction_changed", **details)
            if entry["evidence_status"] == "current" and dep["evidence_status"] in {"pdf_replaced", "pdf_removed", "text_superseded"}:
                add(dep["evidence_status"], **details)
    return reasons


def claim_text_changed(content, live):
    """Whether a snapshot claim's words differ from its live effective words."""
    if isinstance(content, str):
        saved_text = content
    else:
        saved_text = content["text"]
    if live is None:
        return True
    live_text = live if isinstance(live, str) else live.get("revision_text") if live.get("current_revision_id") else live["text"]
    return saved_text != live_text
