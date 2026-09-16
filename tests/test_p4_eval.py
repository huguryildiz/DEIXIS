"""Regression checks for the P4 measurement tool's identity comparison."""

from scripts.p4_eval.measure import similar


def test_crossref_encoded_inline_formula_does_not_create_a_title_mismatch():
    source = "$k$ -Connectivity in Random Key Graphs With Unreliable Links"
    crossref = ('&lt;inline-formula&gt; &lt;tex-math notation="LaTeX"&gt;$k$ '
                '&lt;/tex-math&gt;&lt;/inline-formula&gt;-Connectivity in Random Key Graphs With Unreliable Links')
    assert similar(source, crossref) == 1.0


# P5 slice 5: DOI aliases, table cell review and PDF paths (synthetic views, no model or provider).

import json
from pathlib import Path

from scripts.p4_eval.measure import cell_summary, cell_sheet, coverage, score_cells


def _source(svid, doi, title, state="included", assets=()):
    return {"source_version_id": svid, "doi": doi, "title": title, "version_role": "record",
            "selection": {"state": state, "user_reason": None, "proposal_reason": "SYNTHETIC"},
            "access": {"assets": [{"id": f"ast_{svid}", "origin": origin, "page_count": 3} for origin in assets]}}


def test_a_known_entry_matches_any_of_its_doi_aliases_and_reports_the_pdf_path(tmp_path: Path):
    known = tmp_path / "known.txt"
    known.write_text("# stratum: s\n10.1234/a | 10.1234/a-alias\n10.1234/b\nA Title Without DOI\n", encoding="utf-8")
    view = {"sources": [_source("srv_1", "10.1234/a-alias", "SYNTHETIC A", assets=["download"]),
                        _source("srv_2", None, "A title without DOI", assets=["user_upload"])]}
    answer = {"inputs_given": {"source_ids": ["srv_1"]}, "claims": []}
    rows = coverage(known, view, answer)
    assert [(r["found"], r["given_to_model"], r["pdf_origins"]) for r in rows] == [
        (True, True, ["download"]), (False, False, []), (True, False, ["user_upload"])]


def _cell(col, svid, state, depth, evidence_kind="pdf_page", valid=True):
    revision = {"state": state, "reading_depth": depth, "output_status": "structurally_valid" if valid else "invalid",
                "value": {"text": f"SYNTHETIC {col} {svid}"}, "note": None,
                "evidence": [{"passage_id": "psg_1", "anchor_text": "SYNTHETIC anchor", "anchor_match": "exact",
                              "kind": evidence_kind, "physical_page": 2 if evidence_kind == "pdf_page" else None}]}
    return {"column_id": col, "source_version_id": svid, "current": revision if valid else None,
            "pending_proposal": None if valid else revision, "flags": []}


def _table():
    columns = [{"id": "c1", "name": "Amaç", "answer_format": "text"}, {"id": "c2", "name": "Boyut", "answer_format": "number_unit"}]
    rows = [{"source_version_id": s, "title": f"SYNTHETIC {s}"} for s in ("srv_1", "srv_2")]
    cells = [_cell("c1", "srv_1", "value", "selected_sections"), _cell("c2", "srv_1", "not_found_in_inspected_scope", "selected_sections"),
             _cell("c1", "srv_2", "value", "abstract", "abstract"), _cell("c2", "srv_2", "value", "abstract", "abstract", valid=False)]
    run = {"steps": [{"kind": "model:table_fill", "status": "succeeded"}, {"kind": "model:table_fill", "status": "failed"}]}
    return {"table": {"id": "tbl_1"}, "columns": columns, "rows": rows, "cells": cells}, run


def test_cell_summary_counts_valid_steps_states_and_depth_apart():
    table, run = _table()
    summary = cell_summary(table, [run])
    assert summary["fill_steps"] == {"succeeded": 1, "total": 2}
    assert summary["valid_cells"] == {"value": 2, "not_found_in_inspected_scope": 1}
    assert summary["unverified_proposals"] == 1
    assert summary["valid_values_by_depth"] == {"selected_sections": 1, "abstract": 1}


def test_cell_sheet_samples_values_lists_every_not_found_and_number_cell_and_scores_back(tmp_path: Path):
    table, _ = _table()
    sheet = cell_sheet(table, sample=5, seed=1)
    assert sheet.count("### V") == 2 and sheet.count("### N") == 1 and sheet.count("### E") == 0
    ticked = sheet.replace("- [ ] Doğru", "- [x] Doğru", 1).replace("- [ ] Yayında gerçekten yok", "- [x] Yayında gerçekten yok", 1)
    (tmp_path / "cells.md").write_text(ticked, encoding="utf-8")
    result = score_cells(tmp_path / "cells.md")
    assert result["values"] == {"judged": 1, "total": 2, "correct": 1, "partial": 0, "wrong": 0}
    assert result["not_found"] == {"judged": 1, "total": 1, "truly_absent": 1, "present": 0}
    json.dumps(result)
