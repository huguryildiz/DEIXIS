"""Corpus-absence candidates derived from synthetic frozen snapshots."""

from deixis.workflow.report.gaps import generate_corpus_absence_candidates


def test_corpus_absence_requires_at_least_three_full_text_applicable_not_found_rows():
    snapshot = {
        "cells": [
            {"cell_id": f"cel_{i}", "column_id": "col_x", "source_version_id": f"srv_{i}",
             "state": "not_found_in_inspected_scope", "reading_depth": "full_text"}
            for i in range(2)
        ],
        "rows": [{"source_version_id": f"srv_{i}", "reading_depth": "full_text"} for i in range(2)],
    }
    assert generate_corpus_absence_candidates(snapshot, [{"axis_id": "AX1", "column_id": "col_x"}]) == []

    snapshot["cells"] += [{"cell_id": "cel_2", "column_id": "col_x", "source_version_id": "srv_2",
                            "state": "not_found_in_inspected_scope", "reading_depth": "full_text"}]
    snapshot["rows"] += [{"source_version_id": "srv_2", "reading_depth": "full_text"}]
    candidates = generate_corpus_absence_candidates(snapshot, [{"axis_id": "AX1", "column_id": "col_x"}])
    assert len(candidates) == 1 and candidates[0]["full_text_applicable_count"] == 3


def test_not_applicable_cells_never_count_as_absence_evidence():
    snapshot = {
        "cells": [
            {"cell_id": f"cel_{i}", "column_id": "col_x", "source_version_id": f"srv_{i}",
             "state": "not_applicable", "reading_depth": "full_text"}
            for i in range(5)
        ],
        "rows": [{"source_version_id": f"srv_{i}", "reading_depth": "full_text"} for i in range(5)],
    }
    assert generate_corpus_absence_candidates(snapshot, [{"axis_id": "AX1", "column_id": "col_x"}]) == []


def test_mixed_full_text_states_do_not_create_a_corpus_absence_candidate():
    states = ["not_found_in_inspected_scope", "value", "not_found_in_inspected_scope"]
    snapshot = {
        "cells": [
            {"cell_id": f"cel_{i}", "column_id": "col_x", "source_version_id": f"srv_{i}",
             "state": state, "reading_depth": "full_text"}
            for i, state in enumerate(states)
        ],
        "rows": [{"source_version_id": f"srv_{i}", "reading_depth": "full_text"} for i in range(3)],
    }
    assert generate_corpus_absence_candidates(snapshot, [{"axis_id": "AX1", "column_id": "col_x"}]) == []


def test_summary_only_count_is_reported_separately_from_full_text_absence_evidence():
    snapshot = {
        "cells": [
            {"cell_id": f"cel_{i}", "column_id": "col_x", "source_version_id": f"srv_{i}",
             "state": "not_found_in_inspected_scope", "reading_depth": "full_text" if i < 3 else "abstract"}
            for i in range(5)
        ],
        "rows": [{"source_version_id": f"srv_{i}", "reading_depth": "full_text" if i < 3 else "abstract"}
                 for i in range(5)],
    }
    candidate = generate_corpus_absence_candidates(snapshot, [{"axis_id": "AX1", "column_id": "col_x"}])[0]
    assert candidate["basis_cell_ids"] == ["cel_0", "cel_1", "cel_2"]
    assert candidate["summary_only_count"] == 2
