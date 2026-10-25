"""Deterministic, section-specific selection from a frozen report snapshot."""

from __future__ import annotations

import json
import math
from typing import Any

from deixis.domain import contracts
from deixis.workflow.run.store import NotFound, Store
from deixis.workflow.features.report.report_snapshot import evidence_row_ids, frozen_passage_ids


SECTION_BUDGET_TOKENS = {
    "III": 6000, "IV": 10000, "V": 8000, "VI": 6000, "VII": 4000, "VIII": 3000,
    "I": 3000, "IX": 3000, "abstract": 1500, "index_terms": 500,
}
# D58: a cell section's budget is max(base, its cells + reserve), capped at the ceiling; the reserve is page room.
CELL_RESERVE_TOKENS = {"IV": 10000, "V": 6000, "VI": 4000, "VII": 3000}
CELL_CEILING_TOKENS = {"IV": 60000, "V": 40000, "VI": 20000, "VII": 15000}
MAX_RANKED_PASSAGES = 40


def _estimated_tokens(record: dict[str, Any]) -> int:
    # Assume four serialized characters per token; measure real report inputs later and replace this approximation.
    return max(1, math.ceil(len(json.dumps(record, ensure_ascii=False, separators=(",", ":"))) / 4))


def _passage_id(passage: dict[str, Any]) -> str:
    return passage.get("id") or passage["passage_id"]


def _has_math(cell: dict[str, Any]) -> bool:
    value = cell.get("value")
    texts = [text for text in value.values() if isinstance(text, str)] if isinstance(value, dict) else []
    texts += [link["quote"] for link in cell.get("evidence", []) if link.get("quote")]
    return any(contracts._math_spans(text) for text in texts)


def _query(plan: dict[str, Any]) -> str:
    terms = [entry["term"] for entry in plan.get("glossary", [])]
    terms += [axis["label"] for axis in plan.get("axes", [])]
    return " OR ".join(f'"{term.replace(chr(34), "")}"' for term in terms if term.strip())


def row_passages(store: Store, snapshot: dict[str, Any], source_id: str) -> list[dict[str, Any]]:
    """The passages a report step may read for one row: the one way report code reads them (D114).

    A row whose snapshot froze its passages (a row without PDF text when the snapshot was taken) gets exactly those, by
    id, whatever the source gained since; a PDF that arrives later needs a new snapshot. Any other row reads the
    source's current passages, as before.
    """
    frozen = frozen_passage_ids(snapshot).get(source_id)
    if frozen is None:
        return store.passages_for(source_id)
    passages = []
    for passage_id in frozen:
        try:
            passages.append(store.passage(passage_id))
        except NotFound:
            continue
    return passages


def allowed_passage(snapshot: dict[str, Any], passage: dict[str, Any]) -> bool:
    """Whether a passage may reach a report step: any passage of an unfrozen row, only the frozen ones of a frozen row."""
    frozen = frozen_passage_ids(snapshot).get(passage["source_version_id"])
    return frozen is None or _passage_id(passage) in frozen


def usable_cells(snapshot: dict[str, Any]) -> list[dict[str, Any]]:
    """The snapshot cells a report section may cite or count (D68). A source without text ('inaccessible') and a value
    without linked evidence ('not_verified') stay in Table I and the basis note, but are neither evidence nor a count."""
    return [cell for cell in snapshot.get("cells", [])
            if cell["state"] != "inaccessible" and not (cell["state"] == "not_verified" and not cell.get("evidence"))]


def select_evidence(store: Store, snapshot: dict[str, Any], section_id: str, plan: dict[str, Any],
                    prior_summaries: list[dict[str, Any]]) -> dict[str, Any]:
    """Return budgeted passages and cells plus source/kind records for omitted candidates.

    The store supplies live passage records, while the snapshot alone determines the eligible source versions,
    columns, cells and their frozen revisions. ``prior_summaries`` is accepted for the round interface; the summaries
    themselves are supplied separately to the model and therefore do not consume this evidence budget.
    """
    if section_id not in SECTION_BUDGET_TOKENS:
        raise ValueError(f"Unknown report section: {section_id}")
    if section_id == "VIII":
        # VIII receives its numeric core and prior summaries; source limitation claims belong to VI.
        return {"passages": [], "cells": [], "truncated": []}

    del prior_summaries
    source_ids = evidence_row_ids(snapshot)
    passages_by_source = {source_id: row_passages(store, snapshot, source_id) for source_id in source_ids}
    frozen = frozen_passage_ids(snapshot)
    passage_by_id = {_passage_id(passage): passage for passages in passages_by_source.values() for passage in passages}
    selected_passages: list[dict[str, Any]] = []
    selected_cells: list[dict[str, Any]] = []
    selected_passage_ids: set[str] = set()
    refused: set[str] = set()
    truncated: list[dict[str, str]] = []
    used = 0
    budget = SECTION_BUDGET_TOKENS[section_id]

    def _exists(passage_id: str) -> bool:
        try:
            store.passage(passage_id)
        except NotFound:
            return False
        return True

    def omit(source_version_id: str, record_kind: str) -> None:
        truncated.append({"source_version_id": source_version_id, "record_kind": record_kind})

    def add_passage(passage: dict[str, Any], kind: str = "passage") -> bool:
        nonlocal used
        passage_id = _passage_id(passage)
        if passage_id in selected_passage_ids:
            return True
        if passage_id in refused:
            return False
        cost = _estimated_tokens(passage)
        if used + cost > budget:
            omit(passage["source_version_id"], kind)
            refused.add(passage_id)
            return False
        selected_passages.append(passage)
        selected_passage_ids.add(passage_id)
        used += cost
        return True

    def add_cells(candidates: list[dict[str, Any]], ranked_columns: list[str]) -> None:
        """Admit cell records with their quotes first, then their pages (D58). A page left out is `cell_page`, not a
        budget cut: its cell is still supplied with the page's quoted words.

        A cell's page is not needed to cite the cell: its stored quotes carry the anchor. Over the ceiling whole columns
        are left out, never rows; only a first-ranked column that alone exceeds the room is admitted row by row.
        """
        nonlocal used, budget
        ready = []
        for item in candidates:
            # A page of a replaced file or an earlier extraction is never supplied, but its cell is admitted quote-only.
            if all(link["passage_id"] in passage_by_id or _exists(link["passage_id"]) for link in item.get("evidence", [])):
                ready.append(item)
            else:
                omit(item["source_version_id"], "cell_missing_evidence")
        costs = {item["cell_id"]: _estimated_tokens(item) for item in ready}
        total, reserve, ceiling = sum(costs.values()), CELL_RESERVE_TOKENS[section_id], CELL_CEILING_TOKENS[section_id]
        budget = min(max(budget, total + reserve), ceiling)
        admitted = {item["cell_id"] for item in ready}
        if total + reserve > ceiling:
            admitted, room = set(), ceiling - reserve
            for rank, column_id in enumerate(ranked_columns):
                column = [item for item in ready if item["column_id"] == column_id]
                cost = sum(costs[item["cell_id"]] for item in column)
                if cost <= room:
                    admitted.update(item["cell_id"] for item in column)
                    room -= cost
                    continue
                for item in column:
                    if rank == 0 and costs[item["cell_id"]] <= room:
                        admitted.add(item["cell_id"])
                        room -= costs[item["cell_id"]]
                    else:
                        omit(item["source_version_id"], "cell")
                truncated.append({"column_id": column_id, "record_kind": "column_partial" if rank == 0 else "column_omitted"})
        selected_cells.extend(item for item in ready if item["cell_id"] in admitted)
        used += sum(costs[cell_id] for cell_id in admitted)

        def pages(item: dict[str, Any]) -> list[str]:
            return list(dict.fromkeys(link["passage_id"] for link in item["evidence"] if link["passage_id"] in passage_by_id))

        # An equation claim needs its page supplied with recognized math, so pages of math cells come first.
        for item in selected_cells:
            if _has_math(item):
                for passage_id in pages(item):
                    add_passage(passage_by_id[passage_id], "cell_page")
        # Then each row's next page in turn, so a long table does not spend the room on its first rows.
        queues: dict[str, list[str]] = {}
        for item in selected_cells:
            queues.setdefault(item["source_version_id"], []).extend(pages(item))
        row_rank = {source_id: index for index, source_id in enumerate(source_ids)}
        rows = sorted(queues, key=lambda source_id: row_rank.get(source_id, len(row_rank)))
        while any(queues.values()):
            for row in rows:
                while queues[row]:
                    passage_id = queues[row].pop(0)
                    if passage_id not in selected_passage_ids and passage_id not in refused:
                        add_passage(passage_by_id[passage_id], "cell_page")
                        break

    query = _query(plan)
    cells = usable_cells(snapshot)

    def search(ids: list[str], limit: int) -> list[dict[str, Any]]:
        # A frozen row is ranked only within its frozen passages, before the limit (D114).
        return store.search_passages(ids, query, limit, frozen) if frozen else store.search_passages(ids, query, limit)
    if section_id == "III":
        for entry in plan.get("glossary", []):
            passage = passage_by_id.get(entry["passage_id"])
            if passage is not None:
                add_passage(passage)
        # One ranked passage per possible claim is enough; the token budget remains the final admission gate.
        ranked = search(source_ids, MAX_RANKED_PASSAGES) if query else []
        for passage in ranked:
            add_passage(passage)
        # Preserve at least one passage per source when the lexical query did not return one.
        represented = {passage["source_version_id"] for passage in selected_passages}
        for source_id in source_ids:
            if source_id not in represented and passages_by_source[source_id]:
                add_passage(passages_by_source[source_id][0])
    elif section_id == "IV":
        axis_columns = [axis["column_id"] for axis in plan.get("axes", [])]
        table_columns = [column["column_id"] for column in snapshot.get("columns", [])]
        add_cells(cells, list(dict.fromkeys(axis_columns + table_columns + [item["column_id"] for item in cells])))
        for source_id in source_ids:
            ranked = search([source_id], 2) if query else passages_by_source[source_id][:2]
            for passage in ranked[:2]:
                add_passage(passage)
    elif section_id == "V":
        axis_columns = {axis["column_id"] for axis in plan.get("axes", [])}
        axis_cells = sorted(
            (item for item in cells if item["column_id"] in axis_columns),
            key=lambda item: (item["column_id"], item["source_version_id"]),
        )
        add_cells(axis_cells, list(dict.fromkeys(axis["column_id"] for axis in plan.get("axes", []))))
        varied_columns = {column_id for column_id in axis_columns if len({
            json.dumps(item.get("value"), sort_keys=True) for item in axis_cells if item["column_id"] == column_id
        }) > 1}
        varied_sources = list(dict.fromkeys(item["source_version_id"] for item in axis_cells
                                             if item["column_id"] in varied_columns))
        for source_id in varied_sources:
            ranked = search([source_id], 1) if query else passages_by_source[source_id][:1]
            for passage in ranked[:1]:
                add_passage(passage)
    elif section_id == "VI":
        # Slice 1e gaps.py adds absence totals; V's contradiction claims come from the already-written sections.
        limitation_column_id = plan.get("limitations_column_id")
        add_cells([item for item in cells if limitation_column_id is not None and item["column_id"] == limitation_column_id],
                  [limitation_column_id])
    elif section_id == "VII":
        # Slice 1e gaps.py supplies VI's candidates and their basis records; this branch supplies future-work cells.
        future_work_column_id = plan.get("future_work_column_id")
        add_cells([item for item in cells if future_work_column_id is not None and item["column_id"] == future_work_column_id],
                  [future_work_column_id])

    return {"passages": selected_passages, "cells": selected_cells, "truncated": truncated}
