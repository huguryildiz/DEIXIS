"""Copy review evidence and derive model input exclusively from that copy."""

from __future__ import annotations

import copy
import hashlib
import json
from typing import Any

from deixis.domain.contracts import canonical_validator, locate_anchor
from deixis.workflow.candidates.status import derive_status
from .reader import ReviewReader
from .store import NotFound


class NotReviewable(ValueError):
    """The target is not a finished, reviewable record."""


class DuplicateReviewRef(ValueError):
    """A snapshot-local label refers to more than one record."""


class ReviewInputTooLarge(ValueError):
    """A stored value cannot be represented within the review input bounds."""

    def __init__(self, message, *, parts=None):
        super().__init__(message)
        self.parts = parts


def _unique(rows, field):
    refs = [row[field] for row in rows]
    if len(refs) != len(set(refs)):
        raise DuplicateReviewRef(field)


def _bound_errors(errors):
    for error in errors:
        if error.validator in {"maxItems", "maxLength"}:
            yield error
        yield from _bound_errors(error.context)


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


def _candidate_snapshot(reader, research, version_id):
    version = reader.candidate_version(version_id)
    candidate = reader.candidate(version["candidate_id"])
    if candidate["research_id"] != research["id"]:
        raise NotFound(version_id)
    if candidate["trashed_at"] is not None:
        raise NotReviewable("candidate is in the Trash")
    if version["version"] != candidate["current_version"]:
        raise NotReviewable("candidate version is not current")
    search = reader.latest_kill_search(version_id)
    if search is None or search["outcome"] not in {"completed", "failed", "stopped"}:
        raise NotReviewable("no finished kill-search for this version")
    rows = reader.kill_search_rows(search["id"])
    elements = reader.candidate_elements(version_id)
    refs = {e["id"]: "e" + str(e["position"]) for e in elements}
    hits = [h | {"whole_claim_evidence_count": sum(e["source_version_id"] == h["source_version_id"]
            and e["element_id"] is None for e in rows["evidence"])} for h in rows["hits"]]
    status = derive_status(search | {"query_record_count": rows["query_record_count"]},
        rows["queries"], hits, rows["cells"], list(refs))
    revision = reader.run_scope_revision(search["run_id"])
    scope = reader.scope(research["id"], revision)
    owner = reader.latest_override(version_id)
    content = {"version": 1, "research_id": research["id"], "target_kind": "candidate", "target_id": version_id,
        "candidate_id": candidate["id"], "candidate_version_id": version_id, "candidate_version": version["version"],
        "research_title": research["title"], "scope_revision": revision,
        "scope": {"question": scope["question"], "steering": scope["steering"], "language": scope["language_hint"]},
        "language": scope["language_hint"], "report_version": None,
        "candidate_statement": version["claim_statement"], "conditions": json.loads(version["conditions_json"]),
        "critical_assumption": version["critical_assumption"], "nearest_simple_explanation": version["nearest_simple_explanation"],
        "elements": [{"element_ref": refs[e["id"]], "record_id": e["id"], **{k: e[k] for k in ("position", "kind", "text")}}
                     for e in elements],
        "kill_search": {"id": search["id"], "run_id": search["run_id"], "outcome": search["outcome"], **status["facts"]},
        "candidate_status": {"computed": {k: status[k] for k in ("status", "reasons")},
            "owner": {k: owner[k] for k in ("id", "status", "reason")} if owner else None},
        "matrix": [], "claims": [], "sections": [], "cells": [], "columns": [], "passages": [], "sources": []}
    seen = {}
    for hit in hits:
        if not hit["kept"] or hit["assessment_state"] != "assessed":
            continue
        sid = hit["source_version_id"]
        raw = reader.assessment_input(hit["step_input_id"])
        if raw is None:
            raise NotReviewable("assessment step input is missing")
        try:
            passages = json.loads(raw)["passages"]
            if any(p["source_id"] != sid for p in passages):
                raise NotReviewable("assessment passage belongs to another source")
            by_id = {p["passage_id"]: p for p in passages}
            if len(by_id) != len(passages):
                raise NotReviewable("assessment passage ids are ambiguous")
            for p in passages:
                try:
                    live = reader.passage(p["passage_id"])
                except NotFound as exc:
                    raise NotReviewable("assessment passage is missing") from exc
                if live["source_version_id"] != sid:
                    raise NotReviewable("assessment passage belongs to another source")
                if p["passage_id"] in seen and seen[p["passage_id"]] != p:
                    raise NotReviewable("assessment passage copies disagree")
                seen[p["passage_id"]] = copy.deepcopy(p)

            def mapped_quote(e):
                pid = e["passage_id"]
                if e["evidence_kind"] == "abstract":
                    abstracts = [p for p in passages if p["locator"]["kind"] == "abstract"]
                    if len(abstracts) != 1:
                        raise NotReviewable("assessment abstract passage is missing or ambiguous")
                    pid = abstracts[0]["passage_id"]
                if pid not in by_id:
                    raise NotReviewable("matrix quote passage was not supplied to assessment")
                anchor = locate_anchor(e["quote"], by_id[pid]["text"])
                if anchor is None or anchor.kind not in {"exact", "normalized"}:
                    raise NotReviewable("matrix quote is not located in assessment passage")
                return {"passage_id": pid, "quote": e["quote"], "evidence_kind": e["evidence_kind"]}

            own = [e for e in rows["evidence"] if e["source_version_id"] == sid]
            cells = []
            for cell in sorted((c for c in rows["cells"] if c["source_version_id"] == sid),
                               key=lambda c: next(e["position"] for e in elements if e["id"] == c["element_id"])):
                cells.append({"element_ref": refs[cell["element_id"]],
                    **{k: cell[k] for k in ("relation", "condition_alignment", "note")},
                    "quotes": [mapped_quote(e) for e in own if e["matrix_cell_id"] == cell["id"]]})
            content["matrix"].append({"source_id": sid, **{k: hit[k] for k in
                ("rank_key", "reading_depth", "work_relevance", "note", "step_input_id")},
                "states_whole_claim": bool(hit["states_whole_claim"]), "cells": cells,
                "whole_claim_quotes": [mapped_quote(e) for e in own if e["element_id"] is None]})
        except (KeyError, TypeError, ValueError) as exc:
            if isinstance(exc, NotReviewable):
                raise
            raise NotReviewable("assessment step input is unreadable") from exc
    content["passages"] = list(seen.values())
    return content


def build_snapshot(reader: ReviewReader, research_id: str, target_kind: str, target_id: str) -> tuple[dict, dict]:
    from .stale import markers_for

    if target_kind not in {"answer", "report", "candidate"}:
        raise ValueError(target_kind)
    with reader.consistent_read():
        research = reader.research(research_id)
        if target_kind == "candidate":
            content = _candidate_snapshot(reader, research, target_id)
            _snapshot_sources(reader, content)
            content["evidence_manifest"] = evidence_manifest(reader, content["passages"])
            return copy.deepcopy(content), markers_for(reader, research_id, target_kind, target_id, content)
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
        _snapshot_sources(reader, content)
        content["evidence_manifest"] = evidence_manifest(reader, content["passages"])
        markers = markers_for(reader, research_id, target_kind, target_id, content)
        return copy.deepcopy(content), copy.deepcopy(markers)


def _snapshot_sources(reader, content):
    sids = {p["source_id"] for p in content["passages"]} | {c["source_version_id"] for c in content["cells"]}
    sids.update(m["source_id"] for m in content.get("matrix", []))
    for sid in sorted(sids):
        source = reader.source(sid)
        depths = {p["reading_depth"] for p in content["passages"] if p["source_id"] == sid}
        depths.update(c["reading_depth"] for c in content["cells"] if c["source_version_id"] == sid and c.get("reading_depth"))
        content["sources"].append({"source_id": sid, **{k: source[k] for k in
            ("work_id", "title", "authors", "year", "doi", "version_label")},
            "reading_depth": max(depths, key={"metadata": 0, "abstract": 1, "selected_sections": 2, "full_text": 3}.__getitem__) if depths else "metadata",
            "access_level": reader.source_access(sid)})


def review_step_input_parts(snapshot_id, content, *, focus, owner_note, group_index=1, group_count=1, claim_refs=None, source_ids=None):
    """B2 wraps these frozen parts with an envelope; no library reads happen here."""
    selected = set(claim_refs) if claim_refs is not None else {c["claim_ref"] for c in content["claims"]}
    if selected - {c["claim_ref"] for c in content["claims"]}:
        raise ValueError("unknown snapshot claim ref")
    claims = [{k: c[k] for k in ("claim_ref", "section_ref", "text", "text_origin", "support_type")} |
              {"citations": [{k: e[k] for k in ("passage_id", "cell_id", "anchor_text")} for e in c["citations"]]}
              for c in content["claims"] if c["claim_ref"] in selected]
    cids = {e["cell_id"] for c in claims for e in c["citations"] if e["cell_id"]}
    cells = []
    oversized_cells = []
    for cell in content["cells"]:
        if cell["cell_id"] not in cids:
            continue
        value_text = None if cell["value"] is None else json.dumps(cell["value"], ensure_ascii=False, separators=(",", ":"), allow_nan=False)
        if value_text is not None and len(value_text) > 4000:
            oversized_cells.append(cell["cell_id"])
        cells.append({"cell_id": cell["cell_id"], "column_id": cell["column_id"], "source_id": cell["source_version_id"],
                      "state": cell["state"], "value_text": value_text, "evidence": copy.deepcopy(cell["evidence"])})
    pids = {e["passage_id"] for c in claims for e in c["citations"] if e["passage_id"]}
    pids.update(e["passage_id"] for c in cells for e in c["evidence"])
    passages = [copy.deepcopy(p) for p in content["passages"] if p["passage_id"] in pids]
    sids = {p["source_id"] for p in passages} | {c["source_id"] for c in cells}
    context = None
    if content["target_kind"] == "candidate":
        sids = set(source_ids) if source_ids is not None else {m["source_id"] for m in content["matrix"]}
        if sids - {m["source_id"] for m in content["matrix"]}:
            raise ValueError("unknown snapshot source id")
        passages = [copy.deepcopy(p) for p in content["passages"] if p["source_id"] in sids]
        status = copy.deepcopy(content["candidate_status"])
        if status["owner"] is not None:
            status["owner"].pop("id")
        matrix = []
        for m in content["matrix"]:
            if m["source_id"] not in sids:
                continue
            quote = lambda e: {k: e[k] for k in ("passage_id", "quote")}
            matrix.append({k: copy.deepcopy(m[k]) for k in ("source_id", "reading_depth", "work_relevance", "states_whole_claim", "note")} |
                {"cells": [{k: c[k] for k in ("element_ref", "relation", "condition_alignment", "note")} |
                    {"quotes": [quote(e) for e in c["quotes"]]} for c in m["cells"]],
                 "whole_claim_quotes": [quote(e) for e in m["whole_claim_quotes"]]})
        context = {k: copy.deepcopy(content[k]) for k in ("candidate_version", "conditions", "critical_assumption", "nearest_simple_explanation")}
        context.update(kill_search={k: v for k, v in content["kill_search"].items() if k not in {"id", "run_id"}}, status=status, matrix=matrix)
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
              "elements": [{k: e[k] for k in ("element_ref", "position", "kind", "text")} for e in content.get("elements", [])],
              "candidate_statement": content.get("candidate_statement"), "candidate_context": context,
              "passage_ids": [p["passage_id"] for p in passages]}
    parts = {"sources": sources, "passages": passages, "review_input": review,
            "allowlist": {"candidate_ids": [], "source_ids": [s["source_id"] for s in sources],
                          "passage_ids": review["passage_ids"].copy(), "cell_ids": [c["cell_id"] for c in cells],
                          "claim_refs": [c["claim_ref"] for c in claims], "section_refs": [s["section_ref"] for s in sections],
                          "element_refs": [e["element_ref"] for e in review["elements"]]}}
    if oversized_cells:
        # Retain the unshortened, unsendable parts only for the planner's size audit.
        raise ReviewInputTooLarge(f"cell {oversized_cells[0]}: value_text exceeds 4000 characters", parts=parts)
    if content["target_kind"] == "candidate":
        schema = canonical_validator("StepInput").schema["properties"]["review_input"]
        from jsonschema import Draft202012Validator
        errors = list(Draft202012Validator(schema).iter_errors(review))
        bounds = list(_bound_errors(errors))
        if bounds:
            raise ReviewInputTooLarge(bounds[0].message, parts=parts)
    return parts
