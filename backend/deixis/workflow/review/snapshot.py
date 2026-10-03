"""Copy review evidence and derive model input exclusively from that copy."""

from __future__ import annotations

import copy
import hashlib
import json
from typing import Any

from .reader import ReviewReader
from .store import NotFound


class NotReviewable(ValueError):
    """The target is not a finished, reviewable record."""


class DuplicateReviewRef(ValueError):
    """A snapshot-local label refers to more than one record."""


class ReviewInputTooLarge(ValueError):
    """A stored value cannot be represented within the review input bounds."""


def _unique(rows, field):
    refs = [row[field] for row in rows]
    if len(refs) != len(set(refs)):
        raise DuplicateReviewRef(field)


def _shown_passage(row):
    return {"passage_id": row["id"], "source_id": row["source_version_id"],
            "reading_depth": "abstract" if row["kind"] == "abstract" else "selected_sections",
            "locator": {"kind": row["kind"], "physical_page": row["physical_page"], "printed_label": row["printed_label"]},
            "abstract_origin": row["abstract_origin"],
            "text_source": None if row["kind"] == "abstract" else row.get("text_source", "text_layer"), "text": row["text"]}


def evidence_manifest(reader, passages):
    manifest = []
    for passage in passages:
        dep = reader.evidence_dependency(passage["passage_id"])
        if dep is None:
            raise NotFound(passage["passage_id"])
        manifest.append({"passage_id": passage["passage_id"], "source_version_id": dep["source_version_id"],
                         "text_digest": hashlib.sha256(dep["text"].encode("utf-8")).hexdigest(),
                         **{key: dep[key] for key in ("asset_id", "asset_sha256", "extraction_version",
                            "passage_extraction_id", "current_extraction_id_at_snapshot", "evidence_status")}})
    return manifest


def build_snapshot(reader: ReviewReader, research_id: str, target_kind: str, target_id: str) -> tuple[dict, dict]:
    from .stale import markers_for

    if target_kind == "candidate":
        raise NotImplementedError("B8 owns candidate review snapshots")
    if target_kind not in {"answer", "report"}:
        raise ValueError(target_kind)
    with reader.consistent_read():
        research = reader.research(research_id)
        target = reader.answer(target_id) if target_kind == "answer" else reader.report(target_id)
        if target["research_id"] != research_id:
            raise NotFound(target_id)
        if target["status"] not in ({"structurally_valid"} if target_kind == "answer" else {"valid", "draft"}):
            raise NotReviewable(f"{target_kind}: {target['status']}")
        scope = reader.scope(research_id, target["scope_revision"])
        content: dict[str, Any] = {"version": 1, "research_id": research_id, "target_kind": target_kind,
            "target_id": target_id, "research_title": research["title"], "scope_revision": target["scope_revision"],
            "scope": {"question": scope["question"], "steering": scope["steering"], "language": scope["language_hint"]},
            "report_version": target["report_version"], "status": target["status"],
            "language": target["answer_language"] if target_kind == "answer" else target["language"],
            "claims": [], "sections": [], "cells": [], "columns": [], "sources": [], "passages": []}
        content[target_kind + "_id"] = target_id
        if target_kind == "answer":
            rows = reader.answer_claims(target_id)
            _unique(rows, "label")
            links = reader.answer_links(target_id)
            for row in rows:
                content["claims"].append({"claim_id": row["id"], "claim_ref": row["label"], "label": row["label"],
                    "ordinal": row["ordinal"], "text": row["text"], "text_origin": "model", "section": row["section"],
                    "section_ref": None, "support_type": row["support_type"], "citations": [
                        {"link_id": link["id"], "passage_id": link["passage_id"], "cell_id": None,
                         "anchor_text": link["anchor_text"], "anchor_match": link["anchor_match"]}
                        for link in links if link["claim_id"] == row["id"]]})
        else:
            rows = reader.report_claims(target_id)
            _unique(rows, "claim_key")
            rows = [row for row in rows if row["section_id"] != "II"]
            links = reader.report_links(target_id)
            frozen_row = reader.report_snapshot(target_id)
            frozen = json.loads(frozen_row["snapshot_json"])
            content["table_id"] = frozen_row["table_id"]
            content["columns"] = copy.deepcopy(frozen["columns"])
            for section in reader.report_sections(target_id):
                if section["section_id"] != "II":
                    content["sections"].append({"section_ref": section["section_id"], "record_id": section["id"],
                        "title": (section.get("draft") or {}).get("title"), "status": section["status"]})
            for row in rows:
                content["claims"].append({"claim_id": row["id"], "claim_ref": row["claim_key"],
                    "section_ref": row["section_id"], "ordinal": row["ordinal"],
                    "text": row["revision_text"] if row["current_revision_id"] is not None else row["text"],
                    "text_origin": "human_edit" if row["current_revision_id"] is not None else "model",
                    "revision_id": row["current_revision_id"], "version": row["version"],
                    "support_type": row["support_type"], "table_ref": row["table_ref"],
                    "count": json.loads(row["count_json"]) if row["count_json"] else None,
                    "citations": [{"link_id": link["id"], "passage_id": link["passage_id"], "cell_id": link["cell_id"],
                        "anchor_text": link["anchor_text"], "anchor_match": link["anchor_match"]}
                        for link in links if link["claim_id"] == row["id"]]})
            cids = {link["cell_id"] for c in content["claims"] for link in c["citations"] if link["cell_id"]}
            cells = {cell["cell_id"]: cell for cell in frozen["cells"]}
            if cids - cells.keys():
                raise NotFound(f"frozen cells: {sorted(cids - cells.keys())}")
            names = {c["column_id"]: c["name"] for c in frozen["columns"]}
            content["cells"] = [copy.deepcopy(cells[cid]) | {"column_name": names[cells[cid]["column_id"]]} for cid in sorted(cids)]
            for section in content["sections"]:
                section["claims"] = [copy.deepcopy(c) for c in content["claims"] if c["section_ref"] == section["section_ref"]]
        pids = {link["passage_id"] for c in content["claims"] for link in c["citations"] if link["passage_id"]}
        pids.update(e["passage_id"] for c in content["cells"] for e in c["evidence"])
        content["passages"] = [_shown_passage(reader.passage(pid)) for pid in sorted(pids)]
        sids = {p["source_id"] for p in content["passages"]} | {c["source_version_id"] for c in content["cells"]}
        for sid in sorted(sids):
            source = reader.source(sid)
            depths = {p["reading_depth"] for p in content["passages"] if p["source_id"] == sid}
            depths.update(c["reading_depth"] for c in content["cells"] if c["source_version_id"] == sid and c.get("reading_depth"))
            content["sources"].append({"source_id": sid, **{k: source[k] for k in
                ("work_id", "title", "authors", "year", "doi", "version_label")},
                "reading_depth": max(depths, key={"metadata": 0, "abstract": 1, "selected_sections": 2, "full_text": 3}.__getitem__) if depths else "metadata",
                "access_level": reader.source_access(sid)})
        content["evidence_manifest"] = evidence_manifest(reader, content["passages"])
        markers = markers_for(reader, research_id, target_kind, target_id, content)
        return copy.deepcopy(content), copy.deepcopy(markers)


def review_step_input_parts(snapshot_id, content, *, focus, owner_note, group_index=1, group_count=1, claim_refs=None):
    """B2 wraps these frozen parts with an envelope; no library reads happen here."""
    selected = set(claim_refs) if claim_refs is not None else {c["claim_ref"] for c in content["claims"]}
    if selected - {c["claim_ref"] for c in content["claims"]}:
        raise ValueError("unknown snapshot claim ref")
    claims = [{k: c[k] for k in ("claim_ref", "section_ref", "text", "text_origin", "support_type")} |
              {"citations": [{k: e[k] for k in ("passage_id", "cell_id", "anchor_text")} for e in c["citations"]]}
              for c in content["claims"] if c["claim_ref"] in selected]
    cids = {e["cell_id"] for c in claims for e in c["citations"] if e["cell_id"]}
    cells = []
    for cell in content["cells"]:
        if cell["cell_id"] not in cids:
            continue
        value_text = None if cell["value"] is None else json.dumps(cell["value"], ensure_ascii=False, separators=(",", ":"), allow_nan=False)
        if value_text is not None and len(value_text) > 4000:
            raise ReviewInputTooLarge(f"cell {cell['cell_id']}: value_text exceeds 4000 characters")
        cells.append({"cell_id": cell["cell_id"], "column_id": cell["column_id"], "source_id": cell["source_version_id"],
                      "state": cell["state"], "value_text": value_text, "evidence": copy.deepcopy(cell["evidence"])})
    pids = {e["passage_id"] for c in claims for e in c["citations"] if e["passage_id"]}
    pids.update(e["passage_id"] for c in cells for e in c["evidence"])
    passages = [copy.deepcopy(p) for p in content["passages"] if p["passage_id"] in pids]
    sids = {p["source_id"] for p in passages} | {c["source_id"] for c in cells}
    sources = [{k: s[k] for k in ("source_id", "work_id", "title", "year", "version_label", "access_level")}
               for s in content["sources"] if s["source_id"] in sids]
    refs = {c["section_ref"] for c in claims}
    sections = [{k: s[k] for k in ("section_ref", "title", "status")} for s in content["sections"]
                if claim_refs is None or s["section_ref"] in refs]
    columns = [{k: c[k] for k in ("column_id", "name", "answer_format")} for c in content["columns"]
               if c["column_id"] in {cell["column_id"] for cell in cells}]
    review = {"review_snapshot_id": snapshot_id, "target_kind": content["target_kind"], "focus": focus,
              "owner_note": owner_note, "group_index": group_index, "group_count": group_count,
              "claims": claims, "sections": sections, "cells": cells, "columns": columns,
              "elements": copy.deepcopy(content.get("elements", [])), "candidate_statement": content.get("candidate_statement"),
              "passage_ids": [p["passage_id"] for p in passages]}
    return {"sources": sources, "passages": passages, "review_input": review,
            "allowlist": {"candidate_ids": [], "source_ids": [s["source_id"] for s in sources],
                          "passage_ids": review["passage_ids"].copy(), "cell_ids": [c["cell_id"] for c in cells],
                          "claim_refs": [c["claim_ref"] for c in claims], "section_refs": [s["section_ref"] for s in sections],
                          "element_refs": [e["element_ref"] for e in review["elements"]]}}
