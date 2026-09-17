"""Synthetic, model-independent tests for report evidence selection."""

from deixis.workflow.report.selection import SECTION_BUDGET_TOKENS, select_evidence


class PassageStore:
    def __init__(self, passages):
        self.passages = passages

    def passages_for(self, source_version_id):
        return list(self.passages.get(source_version_id, []))

    def search_passages(self, source_version_ids, _query, limit):
        return [passage for source_id in source_version_ids
                for passage in self.passages.get(source_id, [])][:limit]


def passage(number, source, text="SYNTHETIC passage"):
    return {"id": f"psg_{number:08d}", "source_version_id": source, "kind": "pdf_page", "text": text}


def cell(number, source, column, evidence):
    return {
        "cell_id": f"cel_{number:08d}", "cell_revision_id": f"crv_{number:08d}", "column_id": column,
        "source_version_id": source, "state": "value", "value": {"text": f"value {number}"},
        "reading_depth": "full_text", "evidence": [
            {"passage_id": item["id"], "quote": item["text"]} for item in evidence
        ],
    }


def test_section_iv_keeps_table_order_and_never_selects_a_cell_without_its_evidence_passage(monkeypatch):
    first = passage(1, "srv_source01", "SYNTHETIC " + "a" * 600)
    second = passage(2, "srv_source02", "SYNTHETIC " + "b" * 600)
    snapshot = {
        "rows": [{"source_version_id": "srv_source01"}, {"source_version_id": "srv_source02"}],
        "columns": [{"column_id": "col_method01", "name": "Method", "instruction": "Method"}],
        "cells": [cell(1, "srv_source01", "col_method01", [first]),
                  cell(2, "srv_source02", "col_method01", [second])],
    }
    monkeypatch.setitem(SECTION_BUDGET_TOKENS, "IV", 450)

    selected = select_evidence(PassageStore({"srv_source01": [first], "srv_source02": [second]}),
                               snapshot, "IV", {"axes": []}, [])

    assert [item["cell_id"] for item in selected["cells"]] == ["cel_00000001"]
    assert {item["id"] for item in selected["passages"]} == {"psg_00000001"}
    assert {"source_version_id": "srv_source02", "record_kind": "cell"} in selected["truncated"]
    selected_passage_ids = {item["id"] for item in selected["passages"]}
    assert all(evidence["passage_id"] in selected_passage_ids
               for item in selected["cells"] for evidence in item["evidence"])


def test_missing_cell_evidence_is_not_recorded_as_budget_truncation():
    missing = passage(1, "srv_source01")
    snapshot = {
        "rows": [{"source_version_id": "srv_source01"}],
        "columns": [{"column_id": "col_method01", "name": "Method", "instruction": "Method"}],
        "cells": [cell(1, "srv_source01", "col_method01", [missing])],
    }

    selected = select_evidence(PassageStore({"srv_source01": []}), snapshot, "IV", {"axes": []}, [])

    assert selected["cells"] == []
    assert selected["truncated"] == [
        {"source_version_id": "srv_source01", "record_kind": "cell_missing_evidence"}
    ]


def test_section_rules_select_glossary_axis_and_plan_named_column_roles_without_language_heuristics():
    method = passage(1, "srv_source01")
    limitation = passage(2, "srv_source01")
    future = passage(3, "srv_source02")
    snapshot = {
        "rows": [{"source_version_id": "srv_source01"}, {"source_version_id": "srv_source02"}],
        "columns": [
            {"column_id": "col_method01", "name": "Method", "instruction": "Reported method"},
            {"column_id": "col_limit001", "name": "Einschränkungen", "instruction": "Von den Autoren genannt"},
            {"column_id": "col_future01", "name": "Travaux futurs", "instruction": "Recommandés par les auteurs"},
        ],
        "cells": [cell(1, "srv_source01", "col_method01", [method]),
                  cell(2, "srv_source01", "col_limit001", [limitation]),
                  cell(3, "srv_source02", "col_future01", [future])],
    }
    store = PassageStore({"srv_source01": [method, limitation], "srv_source02": [future]})
    plan = {"glossary": [{"term": "method", "passage_id": method["id"]}],
            "axes": [{"axis_id": "AX1", "label": "Method", "column_id": "col_method01"}],
            "limitations_column_id": "col_limit001", "future_work_column_id": "col_future01"}

    assert method["id"] in {item["id"] for item in select_evidence(store, snapshot, "III", plan, [])["passages"]}
    assert [item["column_id"] for item in select_evidence(store, snapshot, "V", plan, [])["cells"]] == ["col_method01"]
    assert [item["column_id"] for item in select_evidence(store, snapshot, "VI", plan, [])["cells"]] == ["col_limit001"]
    assert [item["column_id"] for item in select_evidence(store, snapshot, "VII", plan, [])["cells"]] == ["col_future01"]
    assert select_evidence(store, snapshot, "VI", {"axes": []}, [])["cells"] == []
    assert select_evidence(store, snapshot, "VII", {"axes": []}, [])["cells"] == []


def test_section_v_orders_cells_by_column_then_source():
    passages = [passage(1, "srv_source02"), passage(2, "srv_source01")]
    snapshot = {
        "rows": [{"source_version_id": "srv_source02"}, {"source_version_id": "srv_source01"}],
        "columns": [],
        "cells": [
            cell(1, "srv_source02", "col_second01", [passages[0]]),
            cell(2, "srv_source01", "col_second01", [passages[1]]),
            cell(3, "srv_source02", "col_first001", [passages[0]]),
            cell(4, "srv_source01", "col_first001", [passages[1]]),
        ],
    }
    plan = {"axes": [
        {"axis_id": "AX1", "label": "Second", "column_id": "col_second01"},
        {"axis_id": "AX2", "label": "First", "column_id": "col_first001"},
    ]}
    store = PassageStore({"srv_source01": [passages[1]], "srv_source02": [passages[0]]})

    selected = select_evidence(store, snapshot, "V", plan, [])

    assert [(item["column_id"], item["source_version_id"]) for item in selected["cells"]] == [
        ("col_first001", "srv_source01"), ("col_first001", "srv_source02"),
        ("col_second01", "srv_source01"), ("col_second01", "srv_source02"),
    ]
