"""A synthetic pre-D242 library record shared by persistence and browser acceptance."""
import json
from pathlib import Path

from deixis.storage.db import dumps, now


def seed(store, connection="codex", model="synthetic-model"):
    fixture = json.loads((Path(__file__).parent / "fixtures/legacy_sw_inspection.json").read_text())
    rid = store.create_research("SYNTHETIC stored sw research", "academic", "quick", ["openalex"],
                                connection, model, "en", search_workflow="sw")
    source = store.create_upload_source("SYNTHETIC historical sw source")
    store.add_to_corpus(rid, source, "search")
    pid = store._insert_passage(source, None, "abstract", None, None, "synthetic", None, None, fixture["abstract"])
    for run_id, kind in (("run_old_sw_discovery", "discovery"), ("run_old_sw_answer", "answer")):
        store.conn.execute(
            "INSERT INTO runs (id, research_id, scope_revision, kind, status, stage, budget_json, created_at, updated_at)"
            " VALUES (?, ?, 1, ?, 'completed', 'inspection', ?, ?, ?)",
            (run_id, rid, kind, dumps(fixture["budget"]), now(), now()))
    plan = store.step("run_old_sw_discovery", "fulltext_plan", "code:fulltext_plan")
    store.finish_step(plan["id"], "succeeded", output={"works": [source], "already_text": [], "not_reached": []})
    from deixis.workflow.decisions import DecisionStore
    DecisionStore(store).record(rid, source, "no_fulltext", step_id=plan["id"])
    step = store.step("run_old_sw_answer", "answer", "model:grounded_answer")
    passage = store.passage(pid) | {"passage_id": pid, "source_id": source}
    payload = {"step_input_id": "input_old_sw", "task_type": "grounded_answer", "scope_revision": 1,
               "skill_package_hash": "stored-package", "sources": [{"source_id": source}], "passages": [passage]}
    store.insert_step_input(step["id"], rid, "run_old_sw_answer", 1, payload, "stored base", "stored developer", "stored message", {})
    store.finish_step(step["id"], "succeeded", output={"result": {"answer_markdown": fixture["answer"]}})
    store.save_answer(rid, "run_old_sw_answer", step["id"], "input_old_sw", 1, "structurally_valid",
                      {"title": "Stored sw evidence", "answer_language": "en", "answer_markdown": fixture["answer"] + " [C1]",
                       "claims": [{"claim_label": "C1", "text": fixture["claim"], "support_type": "source_stated"}]}, {},
                      [{"claim_label": "C1", "passage_id": pid, "source_id": source,
                        "anchor_text": fixture["abstract"], "anchor_match": "exact"}])
    return rid
