"""A new report version written from a newer answer's frozen evidence, carrying the sections whose question did not change.

A file a person uploads after a report was written re-reads the cells it belongs to. Those cells are evidence of a
report only through an answer (P11b), so the refresh stands on one named answer run's frozen view and on nothing
else: the person starts a new answer, chooses it, and the new report version is written from the view that answer
froze. The earlier version keeps its own snapshot, claims, links and revisions; nothing of it is edited.

What the refresh saves is the sections whose question did not change. One rule decides that, and it is the only one:

> A section is carried when the model input, rebuilt over the new evidence, is identical to the input the earlier
> version's section was written from. Otherwise it is written again.

The input is the complete statement of what a section rests on - the frozen plan, the columns with their
instructions, the selected cells with their quotes, the passages, the corpus and reading records, every row's
membership, the earlier sections' summaries and the count domain - so comparing it needs no list of what a claim
could depend on. The comparison is on the text the model is actually sent, handles and ordering included, together
with the instructions and the output schema, so two inputs that read the same are the same question.

Only III, IV and V can be carried. Every other section is written again on every refresh, because its content is
derived: II is code-written from the snapshot, VI reads candidates computed from it, VII is written over VI's gaps,
VIII is rendered from numbers counting the snapshot and III-VII, and I, IX, the abstract and the index terms are
written over the earlier sections' summaries.

A carried section is the earlier one as the reader read it: a claim the person edited keeps the person's sentence and
the citations the person kept, and the record says whose words they are. Its citations are relocated against the new
view before anything is written, and they are bound to an input record of this run. A section that must be written
again and holds a person's own sentence is never overwritten in silence: a derived section refuses the refresh
before it starts, and a III-V section pauses the run with the decision left to the person.
"""

from __future__ import annotations

import copy
import hashlib
import json
from typing import Any

from deixis.domain import contracts
from deixis.domain.rules import step_model
from deixis.models import prompt
from deixis.storage.db import dumps, new_id, now, transaction
from deixis.workflow.features.report import report_evidence_view as evidence_view, report_sections as sections_mod
from deixis.workflow.features.report.report_plan import freeze_plan
from deixis.workflow.features.report.report_store import ReportStore
from deixis.workflow.run.store import NotFound

# The sections a refresh can carry: the ones written from the evidence itself. Everything else is derived from the
# snapshot or from these, so it is written again whatever the evidence did.
CARRYABLE = ("III", "IV", "V")
DECISION_KEY, DECISION_KIND = "report_refresh", "code:report_refresh"
# Fields of a stored StepInput that name the run rather than the question.
RUN_FIELDS = ("step_input_id", "run_id", "step_id", "created_at")


def _canonical(value: Any) -> str:
    return json.dumps(value, sort_keys=True, separators=(",", ":"), ensure_ascii=False)


# ---- the evidence ------------------------------------------------------------------------------------------------

ROW_FIELDS = ("source_version_id", "passage_ids", "membership", "reading_depth")
VIEW_CELL_FIELDS = ("cell_id", "column_id", "source_version_id", "cell_revision_id", "state", "value",
                    "reading_depth", "depth_narrowed", "compared_method", "condition", "direction", "evidence")
VIEW_COLUMN_FIELDS = ("column_id", "revision", "name", "answer_format", "instruction", "options", "allow_multiple")


def view_content(view: dict[str, Any]) -> dict[str, Any]:
    """The evidence of a frozen view, named field by field: what a report can be different because of.

    An explicit list, not everything but a few keys: a view also carries when its run read to and which run froze
    it, and two answers that bound the same rows, text and cells are the same evidence whenever they ran.
    """
    return {
        "table_id": view.get("table_id"), "table_revision": view.get("table_revision"),
        "rows": [{field: row.get(field) for field in ROW_FIELDS} for row in view.get("rows") or []],
        "cells": [{field: cell.get(field) for field in VIEW_CELL_FIELDS} for cell in view.get("cells") or []],
        "columns": [{field: column.get(field) for field in VIEW_COLUMN_FIELDS}
                    for column in view.get("columns") or []],
        "corpus": view.get("corpus"), "reading": view.get("reading"),
        "rows_not_in_answer": view.get("rows_not_in_answer"),
        "answer_rows_without_a_table_row": view.get("answer_rows_without_a_table_row"),
    }


def fingerprint(base_report_id: str, view: dict[str, Any], changes: dict[str, Any]) -> str:
    """One refresh of one report over one state of the evidence.

    The answer run is not in it: a second answer run that freezes an equivalent view must not let the same evidence
    be published a second time. Which run it was is stored beside the report instead.
    """
    body = {"base_report_id": base_report_id, "view": view_content(view), "changes": changes["keys"]}
    return hashlib.sha256(_canonical(body).encode()).hexdigest()


def _rows(view: dict[str, Any]) -> dict[str, dict[str, Any]]:
    return {row["source_version_id"]: row for row in view.get("rows") or []}


def _cells(view: dict[str, Any]) -> dict[str, dict[str, Any]]:
    return {cell["cell_id"]: cell for cell in view.get("cells") or []}


CELL_FIELDS = ("cell_revision_id", "state", "value", "reading_depth", "depth_narrowed",
               "compared_method", "condition", "direction")
COLUMN_FIELDS = ("revision", "name", "answer_format", "instruction")


def diff(base: dict[str, Any], new: dict[str, Any]) -> dict[str, Any]:
    """What changed between the report's frozen evidence and the answer's.

    A record of the change, for the refusal when there is none, for the fingerprint and for what the person is shown.
    The carry decision is not taken from it, so no claim rests on this being complete.
    """
    base_rows, new_rows = _rows(base), _rows(new)
    base_cells, new_cells = _cells(base), _cells(new)
    base_columns = {column["column_id"]: column for column in base.get("columns") or []}
    new_columns = {column["column_id"]: column for column in new.get("columns") or []}
    keys: list[str] = []
    record: dict[str, Any] = {
        "added_rows": sorted(new_rows.keys() - base_rows.keys()),
        "removed_rows": sorted(base_rows.keys() - new_rows.keys()),
        "rows_read_differently": [], "added_cells": sorted(new_cells.keys() - base_cells.keys()),
        "removed_cells": sorted(base_cells.keys() - new_cells.keys()), "changed_cells": [],
        "added_columns": sorted(new_columns.keys() - base_columns.keys()),
        "removed_columns": sorted(base_columns.keys() - new_columns.keys()), "revised_columns": [],
        "corpus_changed": base.get("corpus") != new.get("corpus"),
        "reading_changed": base.get("reading") != new.get("reading"),
    }
    for svid in sorted(base_rows.keys() & new_rows.keys()):
        before, after = base_rows[svid], new_rows[svid]
        if (sorted(before.get("passage_ids") or ()) != sorted(after.get("passage_ids") or ())
                or before.get("reading_depth") != after.get("reading_depth")
                or before.get("membership") != after.get("membership")):
            record["rows_read_differently"].append(svid)
    for cell_id in sorted(base_cells.keys() & new_cells.keys()):
        before, after = base_cells[cell_id], new_cells[cell_id]
        if (any(before.get(field) != after.get(field) for field in CELL_FIELDS)
                or _canonical(before.get("evidence") or []) != _canonical(after.get("evidence") or [])):
            record["changed_cells"].append(cell_id)
    for column_id in sorted(base_columns.keys() & new_columns.keys()):
        if any(base_columns[column_id].get(f) != new_columns[column_id].get(f) for f in COLUMN_FIELDS):
            record["revised_columns"].append(column_id)
    for field in ("added_rows", "removed_rows", "rows_read_differently", "added_cells", "removed_cells",
                  "changed_cells", "added_columns", "removed_columns", "revised_columns"):
        keys += [f"{field}:{value}" for value in record[field]]
    keys += [field for field in ("corpus_changed", "reading_changed") if record[field]]
    record["keys"] = sorted(keys)
    record["any"] = bool(keys)
    return record


def allowed_passages(view: dict[str, Any]) -> set[str]:
    """Every passage the new view bound for one of its rows."""
    return {pid for row in view.get("rows") or [] for pid in (row.get("passage_ids") or ())}


def plan_references_missing(plan: dict[str, Any], view: dict[str, Any]) -> list[str]:
    """Plan references the new evidence no longer holds: a carried plan cannot point outside its own view."""
    columns = {column["column_id"] for column in view.get("columns") or []}
    passages = allowed_passages(view)
    missing = [f"axis:{axis['axis_id']}" for axis in plan.get("axes") or [] if axis["column_id"] not in columns]
    missing += [f"glossary:{item['term']}" for item in plan.get("glossary") or []
                if item["passage_id"] not in passages]
    missing += [f"role:{name}" for name in ("limitations_column_id", "future_work_column_id")
                if plan.get(name) is not None and plan[name] not in columns]
    return missing


def carried_plan(base_plan: dict[str, Any], snapshot: dict[str, Any]) -> dict[str, Any]:
    """The earlier version's plan, re-frozen over the new evidence.

    A refresh asks no plan: the plan states the question and the write-up scope, which the reader has already read,
    and asking again would change every section's input and so carry nothing. The code-owned fields - the corpus, the
    word budgets and the support rules - are taken from the new snapshot, so a changed corpus changes every section's
    question, as it should.
    """
    return freeze_plan(copy.deepcopy(base_plan), snapshot,
                       snapshot.get("row_counts", {}).get("completed", len(snapshot["rows"])))


# ---- the question ------------------------------------------------------------------------------------------------

def _without_run_fields(payload: dict[str, Any]) -> dict[str, Any]:
    body = {key: value for key, value in payload.items() if key not in RUN_FIELDS}
    target = body.get("report_target")
    if isinstance(target, dict):
        body["report_target"] = {key: value for key, value in target.items() if key != "report_id"}
    return body


def question_text(payload: dict[str, Any]) -> str:
    """What a model would be shown for this input, with the run's own identifiers taken out.

    Handled rather than compared field by field, so the short names a record is shown under and the order they are
    numbered in - which follow the records the input carries, not the names of the fields - are part of what is
    compared. The body is written in one canonical order, because the store already keeps a sent input with its keys
    sorted while the message was rendered from the live dictionary: the order of the fields is no part of the question.
    """
    body = _without_run_fields(payload)
    return _canonical(contracts.with_citation_handles(body))


def same_question(base_row: Any, payload: dict[str, Any], base: str, developer: str, schema: dict[str, Any]) -> bool:
    """Whether this input asks what the stored input asked: the same message, instructions and output schema."""
    return (question_text(json.loads(base_row["payload_json"])) == question_text(payload)
            and base_row["base_instructions"] == base and base_row["developer_instructions"] == developer
            and json.loads(base_row["output_schema_json"]) == schema)


def _base_step_input(store: Any, step_id: str | None) -> Any:
    """The last input a section's step sent, which is the one its stored draft answered."""
    if step_id is None:
        return None
    return store.conn.execute(
        "SELECT payload_json, base_instructions, developer_instructions, output_schema_json FROM step_inputs"
        " WHERE step_id = ? ORDER BY attempt DESC, rowid DESC LIMIT 1", (step_id,)).fetchone()


# ---- carrying ----------------------------------------------------------------------------------------------------

def _effective(store: Any, reports: ReportStore, claim: dict[str, Any]) -> tuple[str, str, list[dict[str, Any]]]:
    """A claim as the reader last read it: its current text, whose words they are, and the citations left on it."""
    origin, text = "model", claim["text"]
    if claim["current_revision_id"] is not None:
        row = store.conn.execute("SELECT kind, text FROM report_claim_revisions WHERE id = ?",
                                 (claim["current_revision_id"],)).fetchone()
        if row is not None:
            origin, text = row["kind"], row["text"]
    links = [link for link in reports.effective_links(claim["report_id"]) if link["claim_id"] == claim["id"]]
    return text, origin, links


def relocate(store: Any, links: list[dict[str, Any]], view: dict[str, Any],
             payload: dict[str, Any]) -> dict[str, str] | None:
    """Relocate every citation of a section in the text that section's own input gives, or None for the whole section.

    Not "is it somewhere in the new evidence": a citation must name a record this step was given and locate in the
    text it was given, which is the rule every citation of the report follows. The match kind is read from where the
    quote was found now, never copied from the earlier version.
    """
    passages = {passage["passage_id"]: passage for passage in payload.get("passages") or []}
    cells = {cell["cell_id"]: cell for cell in (payload.get("report_target") or {}).get("cells") or []}
    allowed = payload.get("allowlist") or {}
    matches: dict[str, str] = {}
    for link in links:
        if not link["anchor_text"]:
            return None
        if link["cell_id"] is not None:
            cell = cells.get(link["cell_id"])
            if cell is None or link["cell_id"] not in (allowed.get("cell_ids") or ()):
                return None
            found = contracts.locate_in_cell_evidence(link["anchor_text"], cell)
        else:
            passage = passages.get(link["passage_id"])
            if passage is None or link["passage_id"] not in (allowed.get("passage_ids") or ()):
                return None
            found = contracts.locate_anchor(link["anchor_text"], passage["text"])
        if found is None:
            return None
        matches[link["id"]] = found.kind
    return matches


def citations_not_located(store: Any, reports: ReportStore, report_id: str) -> list[dict[str, Any]]:
    """Every citation of the new version that does not locate in the text its own step was given.

    A refresh publishes nothing on one of these: a version that carries sentences written for an earlier input must
    not be the way an unlocated citation reaches a delivered report.
    """
    payloads: dict[str, dict[str, Any]] = {}
    unlocated = []
    for link in reports.effective_links(report_id):
        step_input_id = link["step_input_id"]
        if step_input_id not in payloads:
            try:
                payloads[step_input_id] = store.step_input_payload(step_input_id)
            except Exception:  # noqa: BLE001 - an input nobody can read gives the citation no basis
                payloads[step_input_id] = {}
        if relocate(store, [link], {}, payloads[step_input_id]) is None:
            unlocated.append({"claim_key": link["claim_key"], "section_id": link["section_id"],
                              "passage_id": link["passage_id"], "cell_id": link["cell_id"]})
    return unlocated


def _claims_of(store: Any, report_section_id: str, report_id: str) -> list[dict[str, Any]]:
    return [dict(row) | {"report_id": report_id} for row in store.conn.execute(
        "SELECT * FROM report_claims WHERE report_section_id = ? ORDER BY ordinal", (report_section_id,))]


def person_edited(store: Any, report_id: str) -> dict[str, list[str]]:
    """Per section of a report, the claims whose current text is the person's own."""
    edited: dict[str, list[str]] = {}
    for row in store.conn.execute(
        "SELECT s.section_id, c.claim_key FROM report_claims c JOIN report_sections s ON s.id = c.report_section_id"
        " WHERE s.report_id = ? AND c.current_revision_id IS NOT NULL ORDER BY s.ordinal, c.ordinal", (report_id,),
    ):
        edited.setdefault(row["section_id"], []).append(row["claim_key"])
    return edited


def carry_section(flow: Any, run: dict[str, Any], reports: ReportStore, report_id: str, base_report_id: str,
                  section_id: str, step_id: str, step_input_id: str, base_section: dict[str, Any],
                  base_claims: list[dict[str, Any]], matches: dict[str, str],
                  checked: dict[str, Any]) -> None:
    """Write one section of the earlier version into the new report, in one transaction.

    The claims are the text and the citations the reader last read, the person's own sentence included. The section
    records that it was carried and what was checked for it, so no surface reads the earlier model validation as a
    check of the person's words.
    """
    store = reports.store
    section_key = reports.create_section(report_id, section_id, sections_mod.ORDINALS[section_id])
    base_validation = base_section["validation"] or {}
    # The earlier validation is kept inside the carried record, where it says which version and which text it
    # belongs to; it is not this section's own result, and a sentence the person wrote was never its subject.
    validation = {"ok": True, "issues": [], "truncated": bool(base_validation.get("truncated")),
                  "carried": checked | {"earlier_validation": base_validation}}
    with transaction(reports.conn):
        reports.conn.execute(
            "UPDATE report_sections SET step_id = ?, status = 'valid', draft_json = ?, validation_json = ?,"
            " word_count = ?, carried_from_section_id = ?, updated_at = ? WHERE id = ?",
            (step_id, dumps(base_section["draft"]), dumps(validation), base_section["word_count"],
             base_section["id"], now(), section_key),
        )
        for ordinal, claim in enumerate(base_claims, 1):
            text, origin, links = _effective(store, reports, claim)
            claim_id = new_id("rcl")
            reports.conn.execute(
                "INSERT INTO report_claims (id, report_section_id, claim_key, ordinal, paragraph, text, support_type,"
                " table_ref, equation_ref, axis_id, count_json, equation_origin_json, carried_from, carried_text_origin)"
                " VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)",
                (claim_id, section_key, claim["claim_key"], ordinal, claim["paragraph"], text, claim["support_type"],
                 claim["table_ref"], claim["equation_ref"], claim["axis_id"], claim["count_json"],
                 claim["equation_origin_json"], claim["id"], origin),
            )
            reports.conn.executemany(
                "INSERT INTO report_claim_refs (claim_id, ref_kind, ref_value) VALUES (?, ?, ?)",
                [(claim_id, row["ref_kind"], row["ref_value"]) for row in store.conn.execute(
                    "SELECT ref_kind, ref_value FROM report_claim_refs WHERE claim_id = ?", (claim["id"],))],
            )
            for link in links:
                reports.conn.execute(
                    "INSERT INTO report_citation_links (id, claim_id, passage_id, cell_id, source_version_id,"
                    " step_input_id, anchor_text, anchor_match, carried_from_step_input_id)"
                    " VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)",
                    (new_id("rln"), claim_id, link["passage_id"], link["cell_id"], link["source_version_id"],
                     step_input_id, link["anchor_text"], matches[link["id"]], link["step_input_id"]),
                )
        store._event(run["research_id"], "report_section_carried",
                     {"report_id": report_id, "from_report_id": base_report_id, "section_id": section_id,
                      "claims": len(base_claims)}, run["id"])


def plan_carry(flow: Any, run: dict[str, Any], scope: dict[str, Any], reports: ReportStore, report_id: str,
               base_report_id: str, frozen_plan: dict[str, Any], snapshot: dict[str, Any]) -> dict[str, Any]:
    """Decide which sections are carried and which are written again, writing nothing.

    Every section is decided over the same state of the new report, because a section carried into it would
    otherwise become an earlier section of the next one's question. Nothing is written here, so a run that stops
    on a person's own words decides again when the person resumes it, instead of stopping for ever on a frozen
    verdict.
    """
    store = reports.store
    model = step_model(scope, "report_section")
    base_sections = {section["section_id"]: section for section in reports.sections(base_report_id)}
    edited = person_edited(store, base_report_id)
    base_text, developer, schema = _instructions(flow, model)
    decision: dict[str, Any] = {"carried": [], "rewritten": [], "reasons": {}, "person_edited": edited}
    prepared: dict[str, dict[str, Any]] = {}
    for section_id in CARRYABLE:
        base_section = base_sections.get(section_id)
        if base_section is None or base_section["status"] != "valid":
            decision["rewritten"].append(section_id)
            decision["reasons"][section_id] = "no_valid_earlier_section"
            continue
        base_row = _base_step_input(store, base_section["step_id"])
        if base_row is None:
            decision["rewritten"].append(section_id)
            decision["reasons"][section_id] = "no_stored_input"
            continue
        target, evidence, _ = sections_mod.section_target(flow, reports, report_id, frozen_plan, snapshot, section_id)
        try:
            target["validation_context"] = sections_mod._validation_context(flow, report_id, snapshot, section_id)
        except ValueError:
            decision["rewritten"].append(section_id)
            decision["reasons"][section_id] = "validation_context_invalid"
            continue
        source_ids = list(dict.fromkeys([passage["source_version_id"] for passage in evidence["passages"]]
                                        + [cell["source_version_id"] for cell in evidence["cells"]]))
        # The step this section would be asked on, so the input record the carried citations are bound to is this
        # run's own. The step stays as it is when the section is written again instead.
        step = store.step(run["id"], f"report_section:{section_id}", "model:report_section")
        payload = flow._step_input(run, scope, step["id"], "report_section", [], source_ids,
                                   evidence["passages"], [], model, report_target=target)
        if not same_question(base_row, payload, base_text, developer, schema):
            decision["rewritten"].append(section_id)
            decision["reasons"][section_id] = "question_changed"
            continue
        base_claims = _claims_of(store, base_section["id"], base_report_id)
        claim_ids = {claim["id"] for claim in base_claims}
        links = [link for link in reports.effective_links(base_report_id) if link["claim_id"] in claim_ids]
        relocated = relocate(store, links, snapshot, payload)
        if relocated is None:
            decision["rewritten"].append(section_id)
            decision["reasons"][section_id] = "citation_not_located"
            continue
        prepared[section_id] = {"step_id": step["id"], "payload": payload, "base_section": base_section,
                                "base_claims": base_claims, "matches": relocated,
                                "instructions": (base_text, developer, schema)}
        decision["carried"].append(section_id)
    decision["person_edited_to_rewrite"] = sorted(
        section_id for section_id, keys in edited.items() if keys and section_id not in decision["carried"])
    return decision | {"prepared": prepared}


def carry_all(flow: Any, run: dict[str, Any], reports: ReportStore, report_id: str, base_report_id: str,
              decision: dict[str, Any]) -> dict[str, Any]:
    """Write every carried section of a decided refresh, and return the decision as the run's own record."""
    store = reports.store
    edited = decision["person_edited"]
    for section_id, item in decision["prepared"].items():
        base_text, developer, schema = item["instructions"]
        store.insert_step_input(item["step_id"], run["research_id"], run["id"], 0, item["payload"], base_text,
                                developer, prompt.step_message(contracts.with_citation_handles(item["payload"])),
                                schema)
        store.start_step(item["step_id"])
        store.finish_step(item["step_id"], "succeeded",
                          output={"carried_from_report_id": base_report_id, "section_id": section_id})
        carry_section(flow, run, reports, report_id, base_report_id, section_id, item["step_id"],
                      item["payload"]["step_input_id"], item["base_section"], item["base_claims"], item["matches"],
                      {"from_report_id": base_report_id, "from_section_id": item["base_section"]["id"],
                       "input_identical": True, "citations_relocated": True,
                       "person_edited_claims": edited.get(section_id, []),
                       "not_checked": ["semantic_support"]})
    return {key: value for key, value in decision.items() if key != "prepared"}


def _instructions(flow: Any, model: tuple[str, str | None, str | None]) -> tuple[str, str, dict[str, Any]]:
    """The instructions and output schema this run would send for a report section."""
    schema = contracts.model_output_schema("report_section")
    developer = prompt.developer_instructions(flow.deps.package, "report_section")
    adapter = flow.deps.adapters.get(model[0])
    if adapter is not None and not adapter.enforces_schema:
        developer = developer + "\n\n" + prompt.schema_appendix("report_section", schema)
    return prompt.BASE_INSTRUCTIONS, developer, schema


def _answer_stamp(store: Any, answer_run_id: str | None) -> tuple[str, int] | None:
    """When one answer run's valid answer was written, for ordering one answer against another."""
    if answer_run_id is None:
        return None
    row = store.conn.execute(
        "SELECT created_at, rowid FROM answers WHERE run_id = ? AND status = 'structurally_valid'"
        " ORDER BY created_at DESC, rowid DESC LIMIT 1", (answer_run_id,)).fetchone()
    return (row["created_at"], row["rowid"]) if row is not None else None


def newer_answers(store: Any, research_id: str, scope_revision: int, base_answer_run_id: str | None) -> list[str]:
    """The valid answers of this question written after the one a report rests on, newest first.

    A refresh is written from evidence its report has not read, so an answer written before it is no refresh of it,
    however the research came to hold it: a research can have more than one answer of one question.
    """
    base = _answer_stamp(store, base_answer_run_id)
    rows = store.conn.execute(
        "SELECT run_id, created_at, rowid FROM answers WHERE research_id = ? AND status = 'structurally_valid'"
        " AND scope_revision = ? ORDER BY created_at DESC, rowid DESC", (research_id, scope_revision))
    return [row["run_id"] for row in rows if base is None or (row["created_at"], row["rowid"]) > base]


def offer(store: Any, reports: ReportStore, research_id: str, report_id: str) -> dict[str, Any]:
    """Whether this report can be refreshed, read from the two frozen views rather than from the stale notice.

    The notice on a report closes when a person marks it seen; whether newer evidence exists does not.
    """
    report = reports.report(report_id)
    if report["research_id"] != research_id:
        raise NotFound(report_id)
    saved = store.conn.execute("SELECT table_id, snapshot_json FROM report_snapshot WHERE report_id = ?",
                               (report_id,)).fetchone()
    empty = {"can_refresh": False, "answer_run_id": None, "diff": None, "sections": None}
    if report["status"] != "valid" or saved is None:
        return empty | {"reason": "report_not_valid" if report["status"] != "valid" else "no_base_snapshot"}
    base = json.loads(saved["snapshot_json"])
    if not base.get("bound_to_answer"):
        return empty | {"reason": "base_report_not_answer_bound"}
    if not report["plan"]:
        return empty | {"reason": "no_base_plan"}
    candidates = newer_answers(store, research_id, report["scope_revision"], base.get("answer_run_id"))
    if not candidates:
        return empty | {"reason": "refresh_needs_a_new_answer"}
    answer_run_id = candidates[0]
    view = evidence_view.for_answer(store, answer_run_id, saved["table_id"])
    if view is None:
        return empty | {"reason": "refresh_needs_a_new_answer"}
    changes = diff(base, view)
    if not changes["any"]:
        return empty | {"reason": "nothing_changed"}
    missing = plan_references_missing(report["plan"] or {}, view)
    if missing:
        return empty | {"reason": "plan_references_missing"}
    edited = person_edited(store, report_id)
    derived = sorted(section_id for section_id in edited if section_id not in CARRYABLE)
    if derived:
        return empty | {"reason": "person_edited_derived_section", "sections": {"person_edited": derived}}
    return {"can_refresh": True, "reason": None, "answer_run_id": answer_run_id,
            "diff": {key: value for key, value in changes.items() if key != "keys"},
            "sections": {"person_edited": sorted(edited)}}
