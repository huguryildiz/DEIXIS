"""Generate bounded corpus-absence candidates from a frozen evidence-table snapshot."""

from __future__ import annotations

from typing import Any


def generate_corpus_absence_candidates(snapshot: dict[str, Any],
                                       axes: list[dict[str, Any]]) -> list[dict[str, Any]]:
    candidates = []
    for axis in axes:
        column_cells = [cell for cell in snapshot["cells"] if cell["column_id"] == axis["column_id"]]
        applicable_full_text = [
            cell for cell in column_cells
            if cell["reading_depth"] == "full_text" and cell["state"] != "not_applicable"
        ]
        if len(applicable_full_text) < 3 or any(
            cell["state"] != "not_found_in_inspected_scope" for cell in applicable_full_text
        ):
            continue
        candidates.append({
            "gap_id": f"gap{len(candidates) + 1}",
            "kind": "corpus_absence",
            "column_id": axis["column_id"],
            "basis_cell_ids": [cell["cell_id"] for cell in applicable_full_text],
            "full_text_applicable_count": len(applicable_full_text),
            "summary_only_count": sum(cell["reading_depth"] != "full_text" for cell in column_cells),
        })
    return candidates
