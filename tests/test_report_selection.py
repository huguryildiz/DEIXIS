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


def test_section_rules_select_glossary_axis_limitation_and_future_work_records():
    method = passage(1, "srv_source01")
    limitation = passage(2, "srv_source01")
    future = passage(3, "srv_source02")
    snapshot = {
        "rows": [{"source_version_id": "srv_source01"}, {"source_version_id": "srv_source02"}],
        "columns": [
            {"column_id": "col_method01", "name": "Method", "instruction": "Reported method"},
            {"column_id": "col_limit001", "name": "Limitations", "instruction": "Authors' limitations"},
            {"column_id": "col_future01", "name": "Future work", "instruction": "Recommended future work"},
        ],
        "cells": [cell(1, "srv_source01", "col_method01", [method]),
                  cell(2, "srv_source01", "col_limit001", [limitation]),
                  cell(3, "srv_source02", "col_future01", [future])],
    }
    store = PassageStore({"srv_source01": [method, limitation], "srv_source02": [future]})
    plan = {"glossary": [{"term": "method", "passage_id": method["id"]}],
            "axes": [{"axis_id": "AX1", "label": "Method", "column_id": "col_method01"}]}

    assert method["id"] in {item["id"] for item in select_evidence(store, snapshot, "III", plan, [])["passages"]}
    assert [item["column_id"] for item in select_evidence(store, snapshot, "V", plan, [])["cells"]] == ["col_method01"]
    assert [item["column_id"] for item in select_evidence(store, snapshot, "VI", plan, [])["cells"]] == ["col_limit001"]
    assert [item["column_id"] for item in select_evidence(store, snapshot, "VII", plan, [])["cells"]] == ["col_future01"]
