"""Synthetic, model-independent tests for report evidence selection."""

from deixis.workflow.store import NotFound
from deixis.workflow.report_selection import (
    CELL_CEILING_TOKENS, CELL_RESERVE_TOKENS, SECTION_BUDGET_TOKENS, _estimated_tokens, select_evidence,
)


class PassageStore:
    def __init__(self, passages, superseded=()):
        self.passages = passages
        self.superseded = {item["id"]: item for item in superseded}

    def passage(self, passage_id):
        found = self.superseded.get(passage_id) or next(
            (item for items in self.passages.values() for item in items if item["id"] == passage_id), None)
        if found is None:
            raise NotFound(passage_id)
        return found

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


def test_section_iv_admits_every_cell_with_its_quotes_before_any_page(monkeypatch):
    # D58 replaces the old rule that a cell came only with all of its pages: a cell carries its stored quotes, and pages
    # are added after every cell, while the room lasts.
    first = passage(1, "srv_source01", "SYNTHETIC " + "a" * 600)
    second = passage(2, "srv_source02", "SYNTHETIC " + "b" * 600)
    snapshot = {
        "rows": [{"source_version_id": "srv_source01"}, {"source_version_id": "srv_source02"}],
        "columns": [{"column_id": "col_method01", "name": "Method", "instruction": "Method"}],
        "cells": [cell(1, "srv_source01", "col_method01", [first]),
                  cell(2, "srv_source02", "col_method01", [second])],
    }
    monkeypatch.setitem(SECTION_BUDGET_TOKENS, "IV", 650)
    monkeypatch.setitem(CELL_RESERVE_TOKENS, "IV", 0)

    selected = select_evidence(PassageStore({"srv_source01": [first], "srv_source02": [second]}),
                               snapshot, "IV", {"axes": []}, [])

    assert [item["cell_id"] for item in selected["cells"]] == ["cel_00000001", "cel_00000002"]
    assert {item["id"] for item in selected["passages"]} == {"psg_00000001"}
    assert selected["truncated"] == [{"source_version_id": "srv_source02", "record_kind": "cell_page"}]


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


def test_section_viii_selects_no_records_or_truncation():
    source = passage(1, "srv_source01")
    snapshot = {"rows": [{"source_version_id": "srv_source01"}],
                "cells": [cell(1, "srv_source01", "col_method01", [source])]}
    assert select_evidence(PassageStore({"srv_source01": [source]}), snapshot, "VIII", {}, []) == {
        "passages": [], "cells": [], "truncated": []}


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


def _grid(rows, columns, page_text, pages_per_row=3, values=None):
    """SYNTHETIC rows x columns table; column c of a row cites that row's page c mod pages_per_row (shared pages)."""
    pages = {f"srv_row{r:05d}": [{"id": f"psg_r{r:03d}p{p}xxxx", "source_version_id": f"srv_row{r:05d}",
                                  "kind": "pdf_page", "text": page_text(r, p)} for p in range(pages_per_row)]
             for r in range(1, rows + 1)}
    cells = []
    for r in range(1, rows + 1):
        for c in range(columns):
            page = pages[f"srv_row{r:05d}"][c % pages_per_row]
            item = cell(r * 100 + c, f"srv_row{r:05d}", f"col_column{c:03d}", [page])
            item["evidence"][0]["quote"] = f"SYNTHETIC quote r{r} c{c}"
            item["value"] = (values or {}).get((r, c), {"text": f"SYNTHETIC value r{r} c{c}"})
            cells.append(item)
    snapshot = {"rows": [{"source_version_id": source} for source in pages],
                "columns": [{"column_id": f"col_column{c:03d}", "name": f"C{c}", "instruction": "x"} for c in range(columns)],
                "cells": cells}
    return PassageStore(pages), snapshot


def test_iv_on_a_31_by_8_table_admits_all_248_cells_then_pages_math_first_and_row_by_row():
    store, snapshot = _grid(31, 8, lambda r, p: f"SYNTHETIC page {r}.{p} " + "w" * 600,
                            values={(20, 5): {"text": "SYNTHETIC rate $x^2$"}})

    selected = select_evidence(store, snapshot, "IV", {"axes": []}, [])

    assert len(selected["cells"]) == 248
    assert {item["source_version_id"] for item in selected["cells"]} == {f"srv_row{r:05d}" for r in range(1, 32)}
    ids = [item["id"] for item in selected["passages"]]
    assert ids[0] == "psg_r020p2xxxx"  # the math cell's page comes first (5 mod 3 = 2)
    assert len(ids) == len(set(ids))
    assert ids.index("psg_r031p0xxxx") < ids.index("psg_r001p1xxxx")  # row 31's first page before row 1's second
    assert 31 < len(ids) < 93
    assert selected["truncated"] and {item["record_kind"] for item in selected["truncated"]} == {"cell_page"}


def test_iv_and_v_still_add_their_ranked_passages_after_the_cell_pages():
    store, snapshot = _grid(2, 2, lambda r, p: f"SYNTHETIC page {r}.{p}", pages_per_row=2)
    for source, rows in store.passages.items():
        rows.insert(0, {"id": f"psg_{source[4:]}rank", "source_version_id": source, "kind": "pdf_page",
                        "text": "SYNTHETIC ranked page"})
    snapshot["cells"][3]["value"] = {"text": "SYNTHETIC other value"}
    plan = {"axes": [{"axis_id": "AX1", "label": "C1", "column_id": "col_column001"}]}

    iv = [item["id"] for item in select_evidence(store, snapshot, "IV", plan, [])["passages"]]
    v = [item["id"] for item in select_evidence(store, snapshot, "V", plan, [])["passages"]]

    assert iv == ["psg_r001p0xxxx", "psg_r002p0xxxx", "psg_r001p1xxxx", "psg_r002p1xxxx",
                  "psg_row00001rank", "psg_row00002rank"]
    assert v == ["psg_r001p1xxxx", "psg_r002p1xxxx", "psg_row00001rank", "psg_row00002rank"]


def test_a_one_row_table_selects_what_it_selected_before():
    first, second = passage(1, "srv_source01"), passage(2, "srv_source01")
    snapshot = {"rows": [{"source_version_id": "srv_source01"}],
                "columns": [{"column_id": "col_method01", "name": "Method", "instruction": "Method"},
                            {"column_id": "col_result01", "name": "Result", "instruction": "Result"}],
                "cells": [cell(1, "srv_source01", "col_method01", [first]),
                          cell(2, "srv_source01", "col_result01", [second, first])]}

    selected = select_evidence(PassageStore({"srv_source01": [first, second]}), snapshot, "IV", {"axes": []}, [])

    assert selected == {"passages": [first, second], "cells": snapshot["cells"], "truncated": []}


def _cells_cost(snapshot, column=None):
    return sum(_estimated_tokens(item) for item in snapshot["cells"] if column is None or item["column_id"] == column)


def test_cells_exactly_at_the_ceiling_are_all_admitted_and_one_token_less_omits_a_column(monkeypatch):
    store, snapshot = _grid(4, 3, lambda r, p: f"SYNTHETIC page {r}.{p}")
    monkeypatch.setitem(CELL_RESERVE_TOKENS, "IV", 100)
    monkeypatch.setitem(CELL_CEILING_TOKENS, "IV", _cells_cost(snapshot) + 100)

    selected = select_evidence(store, snapshot, "IV", {"axes": []}, [])
    assert len(selected["cells"]) == 12
    assert not any(item["record_kind"].startswith("column_") for item in selected["truncated"])

    monkeypatch.setitem(CELL_CEILING_TOKENS, "IV", _cells_cost(snapshot) + 99)
    selected = select_evidence(store, snapshot, "IV", {"axes": []}, [])
    assert {item["column_id"] for item in selected["cells"]} == {"col_column000", "col_column001"}
    assert {"column_id": "col_column002", "record_kind": "column_omitted"} in selected["truncated"]


def test_an_oversized_non_axis_column_is_omitted_whole_and_smaller_columns_still_enter(monkeypatch):
    big = {(r, 1): {"text": "SYNTHETIC long value " + "v" * 2000} for r in range(1, 5)}
    store, snapshot = _grid(4, 3, lambda r, p: f"SYNTHETIC page {r}.{p}", values=big)
    plan = {"axes": [{"axis_id": "AX1", "label": "C2", "column_id": "col_column002"}]}
    monkeypatch.setitem(CELL_RESERVE_TOKENS, "IV", 100)
    small = _cells_cost(snapshot, "col_column000") + _cells_cost(snapshot, "col_column002")
    monkeypatch.setitem(CELL_CEILING_TOKENS, "IV", small + 100)

    selected = select_evidence(store, snapshot, "IV", plan, [])

    assert [item["column_id"] for item in selected["cells"]] == ["col_column000", "col_column002"] * 4
    assert [item for item in selected["truncated"] if item["record_kind"] not in ("cell_page", "passage")] == [
        *({"source_version_id": f"srv_row{r:05d}", "record_kind": "cell"} for r in range(1, 5)),
        {"column_id": "col_column001", "record_kind": "column_omitted"}]


def test_an_oversized_first_axis_column_is_admitted_row_by_row_and_named(monkeypatch):
    big = {(r, 1): {"text": "SYNTHETIC long value " + "v" * 2000} for r in range(1, 5)}
    store, snapshot = _grid(4, 2, lambda r, p: f"SYNTHETIC page {r}.{p}", values=big)
    plan = {"axes": [{"axis_id": "AX1", "label": "C1", "column_id": "col_column001"}]}
    one = _estimated_tokens(snapshot["cells"][1])
    monkeypatch.setitem(CELL_RESERVE_TOKENS, "IV", 100)
    monkeypatch.setitem(CELL_CEILING_TOKENS, "IV", 2 * one + 150)

    selected = select_evidence(store, snapshot, "IV", plan, [])

    assert [(item["source_version_id"], item["column_id"]) for item in selected["cells"]] == [
        ("srv_row00001", "col_column001"), ("srv_row00002", "col_column001")]
    assert {"column_id": "col_column001", "record_kind": "column_partial"} in selected["truncated"]
    assert {"column_id": "col_column000", "record_kind": "column_omitted"} in selected["truncated"]


def test_a_page_larger_than_the_remaining_room_is_left_out_and_smaller_pages_still_enter(monkeypatch):
    store, snapshot = _grid(3, 1, lambda r, p: "SYNTHETIC " + ("h" * 40000 if r == 1 else "short page"),
                            pages_per_row=1)

    selected = select_evidence(store, snapshot, "IV", {"axes": []}, [])

    assert len(selected["cells"]) == 3
    assert [item["id"] for item in selected["passages"]] == ["psg_r002p0xxxx", "psg_r003p0xxxx"]
    assert selected["truncated"] == [{"source_version_id": "srv_row00001", "record_kind": "cell_page"}]


def test_a_cell_citing_a_superseded_page_is_admitted_quote_only_and_a_missing_page_is_not():
    current = passage(1, "srv_source01")
    old = passage(2, "srv_source01", "SYNTHETIC page of an earlier extraction")
    snapshot = {"rows": [{"source_version_id": "srv_source01"}],
                "columns": [{"column_id": "col_method01", "name": "Method", "instruction": "Method"}],
                "cells": [cell(1, "srv_source01", "col_method01", [old, current]),
                          cell(2, "srv_source01", "col_method01", [passage(3, "srv_source01")])]}

    selected = select_evidence(PassageStore({"srv_source01": [current]}, superseded=[old]), snapshot, "IV",
                               {"axes": []}, [])

    assert [item["cell_id"] for item in selected["cells"]] == ["cel_00000001"]
    assert [item["id"] for item in selected["passages"]] == ["psg_00000001"]
    assert selected["truncated"] == [{"source_version_id": "srv_source01", "record_kind": "cell_missing_evidence"}]
