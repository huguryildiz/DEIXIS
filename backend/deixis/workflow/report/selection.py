"""Deterministic, section-specific selection from a frozen report snapshot."""

from __future__ import annotations

import json
import math
from typing import Any

from deixis.workflow.store import Store


SECTION_BUDGET_TOKENS = {
    "III": 6000, "IV": 10000, "V": 8000, "VI": 6000, "VII": 4000, "VIII": 3000,
    "I": 3000, "IX": 3000, "abstract": 1500, "index_terms": 500,
}
MAX_RANKED_PASSAGES = 40


def _estimated_tokens(record: dict[str, Any]) -> int:
    # Assume four serialized characters per token; measure real report inputs later and replace this approximation.
    return max(1, math.ceil(len(json.dumps(record, ensure_ascii=False, separators=(",", ":"))) / 4))


def _passage_id(passage: dict[str, Any]) -> str:
    return passage.get("id") or passage["passage_id"]


def _query(plan: dict[str, Any]) -> str:
    terms = [entry["term"] for entry in plan.get("glossary", [])]
    terms += [axis["label"] for axis in plan.get("axes", [])]
    return " OR ".join(f'"{term.replace(chr(34), "")}"' for term in terms if term.strip())


def select_evidence(store: Store, snapshot: dict[str, Any], section_id: str, plan: dict[str, Any],
                    prior_summaries: list[dict[str, Any]]) -> dict[str, Any]:
    """Return budgeted passages and cells plus source/kind records for omitted candidates.

    The store supplies live passage records, while the snapshot alone determines the eligible source versions,
    columns, cells and their frozen revisions. ``prior_summaries`` is accepted for the round interface; the summaries
    themselves are supplied separately to the model and therefore do not consume this evidence budget.
    """
    if section_id not in SECTION_BUDGET_TOKENS:
        raise ValueError(f"Unknown report section: {section_id}")

    del prior_summaries
    source_ids = [row["source_version_id"] for row in snapshot.get("rows", [])]
    passages_by_source = {source_id: store.passages_for(source_id) for source_id in source_ids}
    passage_by_id = {_passage_id(passage): passage for passages in passages_by_source.values() for passage in passages}
    selected_passages: list[dict[str, Any]] = []
    selected_cells: list[dict[str, Any]] = []
    selected_passage_ids: set[str] = set()
    truncated: list[dict[str, str]] = []
    used = 0
    budget = SECTION_BUDGET_TOKENS[section_id]

    def omit(source_version_id: str, record_kind: str) -> None:
        truncated.append({"source_version_id": source_version_id, "record_kind": record_kind})

    def add_passage(passage: dict[str, Any]) -> bool:
        nonlocal used
        passage_id = _passage_id(passage)
        if passage_id in selected_passage_ids:
            return True
        cost = _estimated_tokens(passage)
        if used + cost > budget:
            omit(passage["source_version_id"], "passage")
            return False
        selected_passages.append(passage)
        selected_passage_ids.add(passage_id)
        used += cost
        return True

    def add_cell(item: dict[str, Any]) -> bool:
        nonlocal used
        required_ids = list(dict.fromkeys(link["passage_id"] for link in item.get("evidence", [])))
        required = [passage_by_id.get(passage_id) for passage_id in required_ids]
        if any(passage is None for passage in required):
            omit(item["source_version_id"], "cell_missing_evidence")
            return False
        new_passages = [passage for passage in required if _passage_id(passage) not in selected_passage_ids]
        cost = _estimated_tokens(item) + sum(_estimated_tokens(passage) for passage in new_passages)
        if used + cost > budget:
            omit(item["source_version_id"], "cell")
            return False
        selected_cells.append(item)
        selected_passages.extend(new_passages)
        selected_passage_ids.update(_passage_id(passage) for passage in new_passages)
        used += cost
        return True

    query = _query(plan)
    cells = snapshot.get("cells", [])
    if section_id == "III":
        for entry in plan.get("glossary", []):
            passage = passage_by_id.get(entry["passage_id"])
            if passage is not None:
                add_passage(passage)
        # One ranked passage per possible claim is enough; the token budget remains the final admission gate.
        ranked = store.search_passages(source_ids, query, MAX_RANKED_PASSAGES) if query else []
        for passage in ranked:
            add_passage(passage)
        # Preserve at least one passage per source when the lexical query did not return one.
        represented = {passage["source_version_id"] for passage in selected_passages}
        for source_id in source_ids:
            if source_id not in represented and passages_by_source[source_id]:
                add_passage(passages_by_source[source_id][0])
    elif section_id == "IV":
        for item in cells:
            add_cell(item)
        for source_id in source_ids:
            ranked = store.search_passages([source_id], query, 2) if query else passages_by_source[source_id][:2]
            for passage in ranked[:2]:
                add_passage(passage)
    elif section_id == "V":
        axis_columns = {axis["column_id"] for axis in plan.get("axes", [])}
        axis_cells = sorted(
            (item for item in cells if item["column_id"] in axis_columns),
            key=lambda item: (item["column_id"], item["source_version_id"]),
        )
        for item in axis_cells:
            add_cell(item)
        varied_columns = {column_id for column_id in axis_columns if len({
            json.dumps(item.get("value"), sort_keys=True) for item in axis_cells if item["column_id"] == column_id
        }) > 1}
        varied_sources = list(dict.fromkeys(item["source_version_id"] for item in axis_cells
                                             if item["column_id"] in varied_columns))
        for source_id in varied_sources:
            ranked = store.search_passages([source_id], query, 1) if query else passages_by_source[source_id][:1]
            for passage in ranked[:1]:
                add_passage(passage)
    elif section_id == "VI":
        # Slice 1e gaps.py adds absence totals; V's contradiction claims come from the already-written sections.
        limitation_column_id = plan.get("limitations_column_id")
        for item in cells:
            if limitation_column_id is not None and item["column_id"] == limitation_column_id:
                add_cell(item)
    elif section_id == "VII":
        # Slice 1e gaps.py supplies VI's candidates and their basis records; this branch supplies future-work cells.
        future_work_column_id = plan.get("future_work_column_id")
        for item in cells:
            if future_work_column_id is not None and item["column_id"] == future_work_column_id:
                add_cell(item)

    return {"passages": selected_passages, "cells": selected_cells, "truncated": truncated}
