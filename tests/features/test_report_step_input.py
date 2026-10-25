"""Model-independent checks for report StepInput construction and routing."""

import asyncio
import json

import pytest

from deixis.config import Settings
from deixis.domain import contracts, skill
from deixis.storage import db
from deixis.storage.db import transaction
from deixis.workflow.flow import FlowDeps, ResearchFlow, RunStopped
from deixis.workflow.store import Store
from fakes import FakeAdapter


class CapturingAdapter(FakeAdapter):
    developer = ""

    async def run_step(self, base, developer, message, output_schema, requested_model, reasoning_effort=None):
        self.developer = developer
        return await super().run_step(base, developer, message, output_schema, requested_model, reasoning_effort)


def report_flow(tmp_path):
    conn = db.connect(tmp_path / "library.sqlite")
    db.migrate(conn)
    store = Store(conn)
    research_id = store.create_research(
        "How are molecular communication systems optimized?", "attached", "quick", [], "fake", "fake-model", "en",
    )
    source_id = store.create_upload_source("SYNTHETIC molecular communication study")
    with transaction(conn):
        passage_id = store._insert_passage(
            source_id, None, "abstract", None, None, "synthetic_fixture", None, None,
            "SYNTHETIC. Molecule release scheduling is formulated as a mixed-integer linear program.",
        )
    adapter = CapturingAdapter()
    flow = ResearchFlow(FlowDeps(
        Settings(data_dir=tmp_path / "data", port=8765), store, {"fake": adapter}, skill.load_skill_package(), None,
    ))
    run = store.create_run(research_id, "report", {"max_model_calls": 4, "max_provider_requests": 0}, None)
    store.update_run(run["id"], status="running")
    return flow, store, adapter, store.run(run["id"]), store.scope(research_id), source_id, passage_id


def report_target(source_id, passage_id):
    cell_ids = [f"cel_SYNTH000{i}" for i in range(1, 4)]
    column_id = "col_SYNTH0001"
    cells = [{
        "cell_id": cell_id,
        "cell_revision_id": f"crv_SYNTH000{i}",
        "column_id": column_id,
        "source_version_id": source_id,
        "state": "value",
        "value": {"text": f"SYNTHETIC value {i}"},
        "reading_depth": "abstract",
        "evidence": [{"passage_id": passage_id, "quote": "Molecule release scheduling is formulated"}],
    } for i, cell_id in enumerate(cell_ids, 1)]
    return {
        "report_id": "rpt_SYNTH0001",
        "section_id": "IV",
        "columns": [
            {"column_id": column_id, "revision": 1, "name": "SYNTHETIC method",
             "instruction": "Record the SYNTHETIC method.", "answer_format": "text"},
            {"column_id": "col_SYNTH0002", "revision": 2, "name": "SYNTHETIC limitations",
             "instruction": "Record stated limitations.", "answer_format": "text"},
        ],
        "plan": {
            "scope_statement": "SYNTHETIC scope.",
            "research_questions": [],
            "glossary": [],
            "axes": [{"column_id": "col_SYNTH0002"}],
            "limitations_column_id": "col_SYNTH0002",
            "future_work_column_id": None,
            "corpus": {"found": 1, "unique": 1, "screened": 1, "included": 1, "full_text": 0},
            "section_budgets": {"IV": {"min_words": 1, "max_words": 500, "max_claims": 10}},
            "allowed_support": {"IV": ["source_stated", "analyst_inference"]},
        },
        "cells": cells,
        "gap_candidates": [{
            "gap_id": "gap1", "kind": "corpus_absence", "column_id": column_id,
            "basis_cell_ids": cell_ids, "full_text_applicable_count": 3, "summary_only_count": 0,
        }],
        "prior_summaries": [],
        "repair_request": None,
        "review_scope": None,
        "review_sections": None,
        "limitations_core": None,
        "validation_context": {"source_ids": [source_id], "column_ids": [column_id],
            "cells": [{name: c[name] for name in ("cell_id", "source_version_id", "column_id", "state", "value", "reading_depth")} for c in cells],
            "accepted_gaps": [], "basis_cells": [], "basis_passages": []},
    }


def run_report_section(flow, store, run, scope, source_id, passage_id, target):
    passage = store.passage(passage_id)
    return asyncio.run(flow._model_step(
        run, scope, "report:IV", "report_section", source_ids=[source_id], passage_rows=[passage],
        model=("fake", "fake-model", None), report_target=target,
    ))


def test_report_section_builds_a_valid_step_input_with_report_allowlists(tmp_path):
    flow, store, adapter, run, scope, source_id, passage_id = report_flow(tmp_path)
    target = report_target(source_id, passage_id)

    run_report_section(flow, store, run, scope, source_id, passage_id, target)

    (step_input,) = adapter.calls
    assert contracts.check_step_input(step_input) == []
    stored = store.conn.execute("SELECT payload_json FROM step_inputs").fetchone()[0]
    assert json.loads(stored)["report_target"] == target
    assert step_input == contracts.with_citation_handles(json.loads(stored))
    assert step_input["allowlist"]["column_ids"] == ["col_C0000001", "col_C0000002"]
    assert step_input["allowlist"]["cell_ids"] == [f"cel_L{i:07d}" for i in range(1, 4)]
    assert step_input["allowlist"]["gap_ids"] == ["gap1"]


def test_report_target_with_a_cell_that_was_not_given_fails_before_the_model_call(tmp_path):
    flow, store, adapter, run, scope, source_id, passage_id = report_flow(tmp_path)
    target = report_target(source_id, passage_id)
    target["gap_candidates"][0]["basis_cell_ids"][2] = "cel_NOTGIVEN01"

    with pytest.raises(RunStopped):
        run_report_section(flow, store, run, scope, source_id, passage_id, target)

    assert adapter.calls == []
    assert store.run(run["id"])["pause_reason"] == "step_input_invalid"
    step = store.step(run["id"], "report:IV", "model:report_section")
    assert (step["status"], step["error_code"]) == ("failed", "step_input_invalid")
