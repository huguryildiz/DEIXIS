"""Read models returned by the API. Every value comes from stored records."""

from __future__ import annotations

import json
from typing import Any

from deixis.documents import embeddings, local_embedding, pdf
from deixis.documents.jats import RENDITION_SQL
from deixis.domain.contracts import locate_anchor, name_sources_in_prose
from deixis.domain.rules import FULLTEXT_RUNS, effective_reviewer, result_applicability
from deixis.workflow import english_question as english_question_rules
from deixis.workflow import approval as approval_rules
from deixis.workflow import flow_counts as flow_rules
from deixis.workflow import overrides as override_rules
from deixis.workflow import probes as probe_rules
from deixis.workflow import screen_more
from deixis.workflow.chaining import QUERY_PREFIX as CHAIN_PREFIX, policy as chain_policy, request_outcomes
from deixis.workflow import vocabulary as vocabulary_rules
from deixis.workflow.equations import chunk_numbers, equation_state, equations_to_check, latex_numbers
from deixis.workflow.queue import _snapshot as snapshot, context as queue_context, queue_answers, queue_counts, inspection_progress
from deixis.workflow.report.store import DISPLAY_ORDER, ReportStore
from deixis.workflow import waiting as waiting_rules
from deixis.providers import openalex
from deixis.providers.registry import search_providers
from deixis.workflow.store import ENDED_RUN_STATUSES, EVIDENCE_STATUS_SQL, NotFound, Store
from deixis.workflow import chaining as chaining_rules
from deixis.workflow import seed_match as seed_match_rules
from deixis.workflow.evidence_deps import latest_completed_restore, passage_dependencies
from deixis.workflow.report.passage_freshness import passage_freshness
from deixis.workflow import recovery_view
from deixis.workflow import fast_path, fast_search
from deixis.workflow.expansion import queried_form


# What the approval card shows of a vocabulary. The probes stay out: they are large, and the screen shows a term's
# own counts, which are already in the term row.
APPROVAL_VOCABULARY_FIELDS = ("claim_words", "exclusion_words", "outcome_terms", "gate_count", "too_broad")


def _approval_side(vocabulary: dict[str, Any], criterion: dict[str, Any] | None,
                   queries: list[dict[str, Any]], words: list[dict[str, Any]] | None = None) -> dict[str, Any]:
    """What the run searched under, as the approval card reads it (slice 08a). `words` is the frozen plan's record of
    which words a sent query carries (D26): each term gets `searched` and `left_out` from it, both null where the plan
    recorded nothing (frozen before the record, or not frozen yet)."""
    origins = approval_rules.block_origins(vocabulary)
    carried = {(w["block"], w["term"]): w for w in words or []}

    def searched(term: dict[str, Any]) -> dict[str, Any]:
        word = carried.get((term["block"], queried_form(term)))
        return {"searched": word["searched"] if word else None, "left_out": word["left_out"] if word else None}

    side = {
        "terms": [{field: term[field] for field in vocabulary_rules.TERM_FIELDS}
                  | {"block_origin": origins.get(term["phrase"], "rule")} | searched(term) for term in vocabulary["terms"]],
        **{field: vocabulary[field] for field in APPROVAL_VOCABULARY_FIELDS},
        "criterion": criterion,
    }
    # The compiled text of every query this run sends, by provider and, beside a model-written query, by which
    # vocabulary wrote it (D92).
    side["queries"] = [{"provider_id": q["provider_id"], "query_text": q["query_text"],
                        **({"origin": q["origin"]} if q.get("origin") else {})} for q in queries]
    return side


def approval_view(store: Store, run_id: str) -> dict[str, Any] | None:
    """What this run recorded it searched under, or None before it recorded anything (SW2.6, SW14.2).

    Nobody is asked since the clean start (decision B): the record says so (`approved_by: unattended`).
    """
    step = store.approval_step(run_id)
    if step is None or step["status"] != "succeeded":
        return None
    output = step["output"]
    approved = output["approved"]
    return {
        "approved_by": output["approval"].get("approved_by"),
        "proposal_hash": output["proposal_hash"],
        "approved": _approval_side(approved["vocabulary"], approved["criterion"], approved["queries"],
                                   fast_search.frozen_words(store, run_id)),
        # How this run chains citations: the fast chain's rule and limits, frozen in the run's budget when it was
        # queued. The real seeds are only known after the search, in the run view.
        "chaining": _card_chaining(store, store.run(run_id)),
    }


def _card_chaining(store: Store, run: dict[str, Any]) -> dict[str, Any] | None:
    """The card's chain policy, with the attempt limit for the effort the run's scope revision was queued with."""
    return chain_policy(run["budget"], store.scope(run["research_id"], run["scope_revision"])["effort"])


def source_counts(store: Store, run_id: str, probe: dict[str, Any] | None = None) -> dict[str, Any] | None:
    """What each source brought in this run: how many works, and how many no other source brought (D93).

    Works are counted after the DOI and work merge, through the candidate each record became, and a source's work is
    its own when no other source's search found that work anywhere in this run. The numbers come from
    `candidate_hits`, which keeps every search that found a candidate; a run searched before that table existed has
    none, and it says its counts were not kept (`counted` false) instead of reading as zero. None for a run that
    searched nothing.

    With an `sw` research's probe set (slice 19), a counted run also gets `arms`: for each of these rows the records
    it returned and the included and confirmed works it found, in the same "only" universe, the split of a source by
    query origin, and the arm-kind line. Without one the result is exactly D93's.
    """
    conn = store.conn
    searches = [dict(r) for r in conn.execute(
        "SELECT sr.id, sr.provider, sr.status, sr.result_count, st.operation_key FROM search_runs sr"
        " JOIN run_steps st ON st.id = sr.step_id WHERE sr.run_id = ? ORDER BY sr.rowid", (run_id,))]
    if not searches:
        return None
    works: dict[str, set[str]] = {}
    for row in conn.execute(
            "SELECT h.search_run_id, v.work_id FROM candidate_hits h JOIN search_runs sr ON sr.id = h.search_run_id"
            " JOIN source_versions v ON v.id = h.source_version_id WHERE sr.run_id = ?", (run_id,)):
        works.setdefault(row["search_run_id"], set()).add(row["work_id"])
    if any(s["result_count"] and s["status"] == "completed" and s["id"] not in works for s in searches):
        return {"counted": False, "sources": []}
    card = store.existing_step(run_id, "protocol_approval")
    everywhere: dict[str, set[str]] = {}
    # Citation chaining is not one of a source's searches (D95): its works are counted apart, with the works no
    # keyword search of this run found.
    chained: set[str] = set()
    for search in searches:
        if search["operation_key"].startswith(CHAIN_PREFIX):
            chained |= works.get(search["id"], set())
            continue
        everywhere.setdefault(search["provider"], set()).update(works.get(search["id"], set()))
    counts: dict[str, Any] = {"counted": True, "sources": [
        {"provider_id": provider, "works": len(found),
         "only": len(found - set().union(*(w for p, w in everywhere.items() if p != provider)))}
        for provider, found in everywhere.items()]}
    if any(search["operation_key"].startswith(CHAIN_PREFIX) for search in searches):
        counts["chain"] = {"works": len(chained), "only": len(chained - set().union(*everywhere.values()))}
    if probe is not None:
        # Beside D93's rows, not inside them: their fields and meaning stay exactly as D93 wrote them.
        counts["arms"] = probe_rules.arm_counts(store, run_id, searches, works, card, probe)
    return counts


def _json(value: str | None) -> Any:
    return json.loads(value) if value else None


def _model_outputs(store: Store, run_id: str, kind: str) -> list[dict[str, Any]]:
    return [json.loads(r["output_json"]) for r in store.conn.execute(
        "SELECT output_json FROM run_steps WHERE run_id = ? AND kind = ? AND status = 'succeeded' AND output_json IS NOT NULL"
        " ORDER BY rowid", (run_id, kind),
    )]


def ocr_state(store: Store, asset_id: str) -> dict[str, Any]:
    """Pages of the text in use without text (blank pages included), pages read with OCR, and the latest OCR reading (D51)."""
    conn = store.conn
    asset = store.asset(asset_id)
    pages = {r["physical_page"]: r["ocr"] for r in conn.execute(
        "SELECT physical_page, MAX(text_source = 'ocr') AS ocr FROM passages WHERE asset_id = ? AND kind = 'pdf_page'"
        " AND extraction_version IS ? GROUP BY physical_page", (asset_id, asset["extraction_version"]))}
    last = conn.execute(
        "SELECT outcome, rejection_reason, ocr_json, created_at FROM asset_extractions WHERE asset_id = ? AND ocr_json IS NOT NULL"
        " ORDER BY created_at DESC, rowid DESC LIMIT 1", (asset_id,)).fetchone()
    return {"pages_without_text": max(0, (asset["page_count"] or 0) - len(pages)), "ocr_pages": sum(1 for o in pages.values() if o),
            "last_read": {"outcome": last["outcome"], "rejection_reason": last["rejection_reason"], "created_at": last["created_at"]}
            | json.loads(last["ocr_json"]) if last else None}


def report_gaps_view(store: Store, research_id: str, report_id: str) -> list[dict[str, Any]]:
    """Stored report aspects, in insertion order; opening one starts no search."""
    store.research(research_id)
    report = ReportStore(store).report(report_id)
    if report["research_id"] != research_id:
        raise NotFound(report_id)
    return [dict(row) for row in store.conn.execute(
        "SELECT id, gap_id, kind, text FROM report_gaps WHERE report_id = ? ORDER BY rowid", (report_id,))]


def report_view(store: Store, research_id: str, report_id: str) -> dict[str, Any]:
    """An edited claim's text is working text, not revalidated; draft, validation, word_count and
    report_version still describe the model-written version until a publish step exists."""
    store.research(research_id)
    reports = ReportStore(store)
    report = reports.report(report_id)
    if report["research_id"] != research_id:
        raise NotFound(report_id)

    changes = reports.evidence_changes(report_id)
    try:
        frozen = reports.snapshot(report_id)
    except NotFound:
        frozen = None
    frozen_cells = {cell["cell_id"]: cell for cell in frozen["cells"]} if frozen else {}
    effective_by_claim: dict[str, list[dict]] = {}
    removed_by_claim: dict[str, list[dict]] = {}
    for link in reports.effective_links(report_id):
        effective_by_claim.setdefault(link["claim_id"], []).append(link)
    for link in reports.removed_links(report_id):
        source = store.conn.execute(
            "SELECT v.title, w.source_key FROM source_versions v JOIN works w ON w.id = v.work_id WHERE v.id = ?",
            (link["source_version_id"],),
        ).fetchone()
        removed_by_claim.setdefault(link["claim_id"], []).append(
            {"link_id": link["id"], **{key: link[key] for key in (
                "passage_id", "cell_id", "source_version_id", "anchor_text", "anchor_match")},
             **(dict(source) if source else {})})
    basis_claims: dict[str, list[dict]] = {}
    for row in store.conn.execute(
        "SELECT c.claim_key, c.current_revision_id, s.section_id FROM report_claims c"
        " JOIN report_sections s ON s.id = c.report_section_id WHERE s.report_id = ?", (report_id,),
    ):
        basis_claims.setdefault(row["claim_key"], []).append(dict(row))
    gap_bases = {row["gap_id"]: json.loads(row["basis_json"]) for row in store.conn.execute(
        "SELECT gap_id, basis_json FROM report_gaps WHERE report_id = ?", (report_id,),
    )}
    numbers: dict[str, int] = {}
    first_passage: dict[str, str] = {}
    cited_cells: dict[str, list[str]] = {}
    sections = []
    for section in sorted(reports.sections(report_id), key=lambda item: DISPLAY_ORDER.index(item["section_id"])
                          if item["section_id"] in DISPLAY_ORDER else len(DISPLAY_ORDER)):
        claims = []
        stored_claims = list(store.conn.execute(
            "SELECT id, claim_key, text, support_type, paragraph, table_ref, equation_ref, current_revision_id, version FROM report_claims"
            " WHERE report_section_id = ? ORDER BY ordinal", (section["id"],),
        ))
        first_paragraph = {paragraph: index for index, paragraph in enumerate(dict.fromkeys(
            claim["paragraph"] for claim in stored_claims))}
        for claim in sorted(stored_claims, key=lambda item: first_paragraph[item["paragraph"]]):
            evidence = [
                {"link_id": link["id"], "passage_id": link["passage_id"], "cell_id": link["cell_id"],
                 "source_version_id": link["source_version_id"], "ref_number": numbers.setdefault(
                     link["source_version_id"], len(numbers) + 1),
                 "anchor_text": link["anchor_text"], "anchor_match": link["anchor_match"]}
                for link in effective_by_claim.get(claim["id"], [])
            ]
            for link in evidence:
                # The passage to open: a passage link's own; for a cell link, the frozen evidence passage whose
                # quote holds the located anchor (never merely the cell's first passage), else null.
                link["open_passage_id"] = link["passage_id"] or next((
                    item["passage_id"] for item in frozen_cells.get(link["cell_id"], {}).get("evidence", [])
                    if link["anchor_match"] and item.get("quote") and link["anchor_text"]
                    and locate_anchor(link["anchor_text"], item["quote"]) is not None), None)
                if link["passage_id"]:
                    first_passage.setdefault(link["source_version_id"], link["passage_id"])
                if link["cell_id"]:
                    cited_cells.setdefault(link["source_version_id"], []).append(link["cell_id"])
            revisions = reports.claim_revisions(claim["id"])
            current = next((revision for revision in revisions if revision["id"] == claim["current_revision_id"]), None)
            current_text = current["text"] if current else claim["text"]
            current_ids = {link["link_id"] for link in evidence}
            removed = removed_by_claim.get(claim["id"], [])
            original_ids = current_ids | {link["link_id"] for link in removed}
            for revision in revisions:
                target_ids = original_ids if revision["link_count"] is None else set(revision["link_ids"])
                revision["changes_current"] = revision["text"] != current_text or target_ids != current_ids
            edited_basis = set()
            for ref in store.conn.execute(
                "SELECT ref_kind, ref_value FROM report_claim_refs WHERE claim_id = ?", (claim["id"],),
            ):
                keys = [ref["ref_value"]] if ref["ref_kind"] == "body_ref" else gap_bases.get(
                    ref["ref_value"], {}).get("basis_claim_keys", [])
                for key in keys:
                    matches = [item for item in basis_claims.get(key, [])
                               if ref["ref_kind"] != "body_ref" or item["section_id"] != section["section_id"]]
                    if len(matches) == 1 and matches[0]["current_revision_id"]:
                        edited_basis.add(key)
            claims.append({"id": claim["id"], "claim_key": claim["claim_key"],
                           "version": claim["version"], "text": current_text,
                           "model_text": claim["text"], "edited": current is not None,
                           "warnings": current["warnings"] if current else [], "revisions": revisions,
                           "support_type": claim["support_type"], "paragraph": claim["paragraph"],
                           "table_ref": claim["table_ref"], "equation_ref": claim["equation_ref"],
                           "evidence": evidence, "original_evidence_count": len(original_ids),
                           "removed_links": removed, "evidence_basis": "direct" if evidence else "none",
                           "support_type_note": "model_written_type" if not evidence and original_ids else None,
                           "edited_basis": sorted(edited_basis)})
        sections.append({key: section[key] for key in (
            "section_id", "status", "word_count", "draft", "validation",
        )} | {"claims": claims, "evidence_changes": changes["sections"][section["section_id"]]})
    edited = store.conn.execute(
        "SELECT 1 FROM report_claim_revisions v JOIN report_claims c ON c.id = v.claim_id"
        " JOIN report_sections s ON s.id = c.report_section_id WHERE s.report_id = ? LIMIT 1", (report_id,),
    ).fetchone()
    references = []
    for source_id, number in numbers.items():
        source = store.conn.execute(
            "SELECT v.title, v.authors_json, v.year, v.venue, v.doi, v.version_label, w.source_key"
            " FROM source_versions v JOIN works w ON w.id = v.work_id WHERE v.id = ?", (source_id,),
        ).fetchone()
        if source is None:
            continue
        fallback = next((e["passage_id"] for cell_id in cited_cells.get(source_id, [])
                         for e in frozen_cells.get(cell_id, {}).get("evidence", [])), None)
        references.append({"number": number, "source_version_id": source_id, "source_key": source["source_key"],
                           "title": source["title"], "authors": json.loads(source["authors_json"]),
                           "year": source["year"], "venue": source["venue"], "doi": source["doi"],
                           "version_label": source["version_label"],
                           "open_passage_id": first_passage.get(source_id) or fallback})
    table_i = None
    missing_rows = None
    if frozen:
        failed_ids = {row["source_version_id"] for row in frozen.get("failed_rows", [])}
        if failed_ids:
            missing_rows = {"counts": frozen["row_counts"],
                            "failed_rows": [{key: row[key] for key in (
                                "source_version_id", "source_key", "title", "reason", "missing_columns")}
                                for row in frozen["failed_rows"]]}
        frozen_sources = {}
        for row in frozen["rows"]:
            source = store.conn.execute(
                "SELECT v.title, w.source_key FROM source_versions v JOIN works w ON w.id = v.work_id WHERE v.id = ?",
                (row["source_version_id"],),
            ).fetchone()
            frozen_sources[row["source_version_id"]] = source
        table_i = {
            "columns": [{**{key: column[key] for key in ("column_id", "name", "answer_format")},
                         "options": json.loads(revision["options_json"]) if revision and revision["options_json"] else None}
                        for column in frozen["columns"]
                        for revision in [store.conn.execute(
                            "SELECT options_json FROM column_revisions WHERE column_id = ? AND revision = ?",
                            (column["column_id"], column["revision"]),
                        ).fetchone()]],
            "rows": [{"source_version_id": row["source_version_id"],
                      "ref_number": numbers.get(row["source_version_id"]),
                      "source_key": frozen_sources[row["source_version_id"]]["source_key"] if frozen_sources[row["source_version_id"]] else None,
                      "title": frozen_sources[row["source_version_id"]]["title"] if frozen_sources[row["source_version_id"]] else None,
                      **({"failed": True} if row["source_version_id"] in failed_ids else {})}
                     for row in frozen["rows"]],
            "cells": [{"cell_id": cell["cell_id"], "column_id": cell["column_id"], "source_version_id": cell["source_version_id"],
                       "state": cell["state"], "value": cell["value"],
                       "evidence_passage_ids": [e["passage_id"] for e in cell["evidence"]]}
                      for cell in frozen["cells"]],
        }
    run = store.conn.execute("SELECT id, status, pause_reason FROM runs WHERE id = ?", (report["run_id"],)).fetchone()
    run = dict(run) if run else None
    # The table the report was written from, from its run's stored target (the report row does not keep it).
    table_id = None
    if run:
        stored_run = store.run(run["id"])
        table_id = (stored_run.get("target") or {}).get("table_id")
        error = stored_run["error"]
        if isinstance(error, list) and all(isinstance(item, dict) and isinstance(item.get("rule"), str)
                                          and "section_id" in item and isinstance(item.get("detail"), str)
                                          for item in error):
            run["error"] = error
    return report | {"sections": sections, "evidence_changes": {key: value for key, value in changes.items() if key != "sections"},
                     "passage_freshness": passage_freshness(reports, report_id),
                     "edited_after_version": report["report_version"] if edited else None,
                     "has_human_edits": edited is not None,
                     "edit_check": reports.edit_check_state(report_id) if edited or store.conn.execute(
                         "SELECT 1 FROM report_edit_checks WHERE report_id = ? LIMIT 1", (report_id,),
                     ).fetchone() else None,
                     "references": references, "table_i": table_i, "missing_rows": missing_rows,
                     "run": run, "table_id": table_id}


def research_view(store: Store, research_id: str) -> dict[str, Any]:
    """The research as the screen reads it, from one read snapshot (slice 19, decision 10): an `sw` research derives
    its decision facts once, and the queue counts, the probe set, the arm counts and the signal table share them."""
    with snapshot(store.conn):
        return _research_view(store, research_id)


SEED_VIEW_KEYS = ("source_version_id", "asset_id", "asset_sha256", "extraction_version", "title", "title_basis",
                  "page_count", "text_pages")


def _same_seeds(envelope: dict[str, Any] | None, scope: dict[str, Any]) -> bool:
    """Whether a frozen seed envelope was made for the scope's current seeds (D3): a v2 one by its seed key; D2's
    single context by its file, its source and the fingerprint of its excerpt, since it has no seed key."""
    if not envelope or not envelope["seeds"]:
        return False
    if envelope["rule"] != seed_match_rules.RULE_V1:
        return envelope["seed_key"] == scope["seed_key"]
    context, seeds = envelope["seeds"][0], scope["seeds"]
    return (len(seeds) == 1 and context["source_version_id"] == seeds[0]["source_version_id"]
            and context["asset_sha256"] == seeds[0]["asset_sha256"]
            and context["seed_passages_sha256"] == seed_match_rules.passages_sha256(seeds))


def _seed_uses(store: Store, research_id: str, scope: dict[str, Any]) -> list[dict[str, Any]]:
    """What each seed PDF did in this revision's search (D2, D3): `selected` before any protocol, `not_used` when the
    protocol froze without these seeds, else its match from the protocol and what read it, from the stored steps of
    the discovery run that froze that protocol. A use is True or False once its step settled and None (not known
    yet) while the run may still reach it."""
    seeds = scope["seeds"]
    frozen = store.current_protocol(research_id, scope["revision"])
    if frozen is None:
        return [{"state": "selected"} for _ in seeds]
    envelope = seed_match_rules.contexts(frozen["body"].get("seed_match"))
    if not _same_seeds(envelope, scope):
        return [{"state": "not_used"} for _ in seeds]
    row = store.conn.execute(
        "SELECT r.id, r.status FROM runs r JOIN run_steps s ON s.run_id = r.id WHERE r.research_id = ?"
        " AND r.scope_revision = ? AND r.kind = 'discovery' AND s.operation_key = 'protocol' AND s.status = 'succeeded'"
        " AND json_extract(s.output_json, '$.protocol_revision') = ? ORDER BY r.created_at DESC, r.id DESC LIMIT 1",
        (research_id, scope["revision"], frozen["protocol_revision"])).fetchone()
    # A paused run may still reach a step; only an ended one settles what it never did.
    run_id, active = (row["id"], row["status"] not in ENDED_RUN_STATUSES) if row else (None, False)

    def step(key: str) -> dict[str, Any] | None:
        return store.existing_step(run_id, key) if run_id else None

    def settled(found: dict[str, Any] | None) -> bool | None:
        if found is None or found["status"] in ("pending", "running"):
            return None if active else False
        return {"succeeded": True, "outcome_unknown": None}.get(found["status"], False)

    query = step("search_query")
    if query is None:
        writing, detail = (False, "code_query") if run_id else (None, None)
    elif query["status"] != "succeeded":
        writing, detail = None, None
    else:
        out = query["output"] or {}
        writing = out.get("status") == "ready" and bool(out.get("seed_passages_sha256"))
        detail = ("reused" if out.get("reused_from_run") else None) if writing else \
            {"skipped": out.get("reason"), "code_only": "code_only"}.get(out.get("status"), "written_without_seed")
    search_plan = frozen["body"].get("fast_path_search") or {}
    semantic_plan = search_plan.get("semantic") or {}
    # D6: a version 2 plan sends each seed's own semantic request; the seed used it when that request succeeded.
    seed_requests = ({spec["source_version_id"]: f"search:fast:semantic:seed:{spec['index']}"
                      for spec in search_plan.get("seed_semantic") or []} if search_plan.get("version") == 2 else None)
    # A plan frozen before seed_parts (D2) names its one seed's text by `seed_text`; the seed's text went in only when
    # the query sent (cut to OpenAlex's limit) is longer than the question part and its separator.
    sentence = english_question_rules.embedding_query(store, scope)
    limit = openalex.SEMANTIC_MAX_CHARS
    v1_part = bool(semantic_plan.get("seed_text") and sentence and semantic_plan.get("query_text")
                   and len(semantic_plan["query_text"][:limit]) > len(sentence[0][:limit]) + 1)
    semantic_step = settled(step("search:fast:semantic"))
    seeds_step = step("fast_chain:seeds")
    chained = ({s["source_version_id"] for s in seeds_step["output"]["seeds"] if s["origin"] == "seed_pdf"}
               if seeds_step and seeds_step["status"] == "succeeded" else None)
    plans = [found for key in ("fast_chain:plan", "fast_chain:plan_fallback")
             if (found := step(key)) is not None and found["status"] == "succeeded"]
    by_source = {context["source_version_id"]: context for context in envelope["seeds"]}
    # A seed part counts only when some of it was in the query sent: a plan frozen before the 1,500-character limit may
    # name parts that were cut off on sending (question, then each part behind one separator).
    sent_parts, at = set(), len(sentence[0][:limit]) if sentence else 0
    for part in semantic_plan.get("seed_parts") or []:
        if at + 1 < limit and part["chars"]:
            sent_parts.add(part["source_version_id"])
        at += 1 + part["chars"]
    uses = []
    for seed in seeds:
        svid = seed["source_version_id"]
        context = by_source.get(svid)
        if context is None:
            uses.append({"state": "not_used"})
            continue
        parts = semantic_plan.get("seed_parts")
        has_part = svid in sent_parts if parts is not None else v1_part
        requests = None
        if plans:
            requests = {"planned": 0, "sent": 0, "unsent": 0, "unknown": 0}
            for found in plans:
                for spec in found["output"]["requests"]:
                    if not any((link[0] if isinstance(link, list) else link) == svid for link in spec.get("links") or []):
                        continue
                    requests["planned"] += 1
                    sent = store.existing_step(run_id, spec["key"])
                    # A request not yet settled is planned only; `request_sent` decides the rest (v4).
                    if sent is None or sent["status"] in ("pending", "running"):
                        continue
                    outcome = chaining_rules.request_sent(sent)
                    requests["unknown" if outcome is None else "sent" if outcome else "unsent"] += 1
        elif not active and run_id:
            requests = {"planned": 0, "sent": 0, "unsent": 0, "unknown": 0}
        uses.append({"state": "used", "run_id": run_id, "run_active": active,
                     "match": {key: context.get(key) for key in ("status", "basis", "title", "doi", "openalex_id")},
                     "query_writing": writing, "query_writing_detail": detail,
                     "semantic": (settled(step(seed_requests[svid])) if svid in seed_requests else False)
                                 if seed_requests is not None else semantic_step if has_part else False,
                     "chain": (svid in chained) if chained is not None else (None if active else False),
                     "chain_requests": requests})
    return uses


def source_text_changed(store: Store, given: dict[str, Any] | None) -> bool:
    """Whether a file or text extraction an answer was given is no longer in use (D45)."""
    return bool(given) and any(
        status != "current" for status in store.evidence_statuses([p["passage_id"] for p in given["passages"]]).values())


def late_applicability(late: dict[str, Any], applicability: str) -> str:
    """Pending abstract candidates can be excluded without bumping the included-source revision; an answer whose late
    full text excluded a work is then out of date for its selection."""
    if late.get("late_revision_status", {}).get("late_excluded") and applicability == "current":
        return "stale_selection"
    return applicability


def answer_is_current(store: Store, research: dict[str, Any], answer: dict[str, Any]) -> bool:
    """An answer row that is current for every reason the answer view checks: the question and the selection it was
    made for are today's, no late full text excluded a work it read, and no text it was given has been replaced."""
    from deixis.workflow import late_revision
    applicability = late_applicability(late_revision.answer_view(store, answer["id"]), result_applicability(
        answer["scope_revision"], research["current_scope_revision"], answer["selection_revision"], research["selection_revision"]))
    given = store.step_input_payload(answer["step_input_id"]) if answer["step_input_id"] else None
    return applicability == "current" and not source_text_changed(store, given)


def intent_outcome(store: Store, research: dict[str, Any]) -> dict[str, Any] | None:
    """What a `table`/`compare` discovery of the current question did instead of the answer, when it wrote no table:
    the `study_table_skipped` of the latest discovery run of this revision (UI parity S5a). None otherwise, so a skip
    of an earlier discovery no longer shows once a later one of the same question ran (S5b)."""
    latest = store.conn.execute(
        "SELECT id FROM runs WHERE research_id = ? AND kind = 'discovery' AND scope_revision = ?"
        " ORDER BY created_at DESC, rowid DESC LIMIT 1",
        (research["id"], research["current_scope_revision"])).fetchone()
    if latest is None:
        return None
    row = store.conn.execute(
        "SELECT payload_json, run_id FROM events WHERE research_id = ? AND type = 'study_table_skipped' AND run_id = ?"
        " ORDER BY id DESC LIMIT 1", (research["id"], latest["id"])).fetchone()
    if row is None:
        return None
    return {"kind": "table_skipped", "reason": json.loads(row["payload_json"])["reason"], "run_id": row["run_id"]}


def _research_view(store: Store, research_id: str) -> dict[str, Any]:
    conn = store.conn
    research = store.research(research_id)
    scope = store.scope(research_id)
    from deixis.workflow import intent as intent_rules
    # The frame of a `compare` research follows its current question; its column suggestions get the frame of the
    # revision they run under (UI parity S5a).
    research["comparison_frame"] = intent_rules.frame_for(research, scope)
    # One queue context: the facts and every work's outcome, read once for all four (slice 19).
    ctx = queue_context(store, research_id)
    probe = probe_rules.probe_set(ctx)
    scope_view = dict(scope)
    # Each seed PDF in canonical order with what it did in this revision's search (D3); never its excerpt's text.
    scope_view["seeds"] = [{key: seed[key] for key in SEED_VIEW_KEYS} | {"passage_count": len(seed["passages"]), "use": use}
                           for seed, use in zip(scope["seeds"], _seed_uses(store, research_id, scope))]
    scope_view["seed_candidates"] = (store.seed_candidates(research_id)
                                     if scope["source_scope"] == "attached_and_academic" else [])
    scope_view["seed_status"] = store.seed_status(research_id, scope)
    # An sw research may ask for an answer with no included work once this revision's search finished (SW22, D106).
    scope_view["discovery_completed"] = store.discovery_completed(research_id)
    # The providers a query may go to; a verification connector in the scope is not one (D87), nor Scopus (D91).
    scope_view["search_providers"] = search_providers(scope["providers"])

    service_waits = {row["run_id"]: json.loads(row["payload_json"]) for row in conn.execute(
        "SELECT run_id, payload_json FROM events WHERE research_id = ? AND type = 'service_waiting' ORDER BY id",
        (research_id,))}
    runs = []
    # The ten latest runs, plus the runs the latest answer and the latest discovery belong to: the transcript draws an
    # answer inside its own run, so later full-text reads and table fills must not push it out of the list.
    for row in conn.execute(
            "SELECT id FROM runs WHERE research_id = ?1 AND ("
            " id IN (SELECT id FROM runs WHERE research_id = ?1 ORDER BY created_at DESC LIMIT 10)"
            " OR id = (SELECT run_id FROM answers WHERE research_id = ?1 ORDER BY created_at DESC, rowid DESC LIMIT 1)"
            " OR id = (SELECT id FROM runs WHERE research_id = ?1 AND kind = 'discovery' ORDER BY created_at DESC LIMIT 1))"
            " ORDER BY created_at DESC", (research_id,)):
        run = store.run(row["id"])
        run["steps"] = store.run_steps(run["id"])
        # The models each step's calls went to, from its stored sessions (UI parity S27, D15): a step names the model it
        # ran on, never the role's model in effect now. The model that answered when known, else the one asked for, with
        # the reasoning effort the call was sent with (null when none was sent or the session predates migration 0009,
        # D25); each model and effort once, ordered by its latest call, so the last entry is where the step's latest call
        # went (the model line compares the role's next calls with it).
        called: dict[str, list[dict[str, Any]]] = {}
        for session in conn.execute("SELECT step_id, connection, requested_model, resolved_model, reasoning_effort"
                                    " FROM model_sessions WHERE run_id = ? ORDER BY rowid", (run["id"],)):
            entry = {"connection": session["connection"], "model": session["resolved_model"] or session["requested_model"],
                     "effort": session["reasoning_effort"]}
            seen = called.setdefault(session["step_id"], [])
            if entry in seen:
                seen.remove(entry)
            seen.append(entry)
        for step in run["steps"]:
            step["models"] = called.get(step["id"], [])
        run["service_wait"] = service_waits.get(run["id"])
        if fast_path.enabled(run["budget"]):
            run["fast_path"] = fast_path.view(store, run)
            if fast_path.enforces(run["budget"], "read"):
                from deixis.workflow import fast_read
                run["fast_path"]["read"] = fast_read.view(store, run)
        if (run["budget"].get("inspection") or {}).get("policy") == "small_batch_fused_v1":
            run["inspection_progress"] = inspection_progress(store, run)
        # The protocol this run froze; a run that froze none (an answer run) ran under the revision's latest one.
        own = next((s["output"] for s in run["steps"] if s["operation_key"] == "protocol" and s["output"]), None)
        frozen = own or store.current_protocol(research_id, run["scope_revision"])
        run["protocol_hash"] = (frozen.get("protocol_hash") or frozen.get("hash")) if frozen else None
        # Screening runs in batches; each batch's note is its own line, timed by its step.
        # What this run asked the user to approve before it froze its protocol (slice 08a).
        run["approval"] = approval_view(store, run["id"])
        # What each source brought in this run, and how much of it no other source did (D93).
        run["source_counts"] = source_counts(store, run["id"], probe) if run["kind"] == "discovery" else None
        # What became of the fast chain's requests, by the one rule the report's method section uses too.
        run["chain_requests"] = request_outcomes(run["steps"]) if run["kind"] == "discovery" else None
        # Where the person's confirmed works stood in this run's keyword ranking, descriptively (slice 19).
        run["signals"] = probe_rules.signal_table(store, run["id"], probe) if run["kind"] == "discovery" else None
        run["screening_notes"] = [
            {"step_id": r["id"], "text": note} for r in store.conn.execute(
                "SELECT id, output_json FROM run_steps WHERE run_id = ? AND kind = 'model:screening' AND status = 'succeeded'"
                " AND output_json IS NOT NULL ORDER BY rowid", (run["id"],))
            if (note := (json.loads(r["output_json"]).get("result") or {}).get("notes", "").strip())
        ]
        runs.append(run)

    search_runs = [
        {**{k: r[k] for k in ("id", "run_id", "step_id", "scope_revision", "provider", "query_text", "access_mode", "status", "result_count", "provider_total", "page_limit", "retrieved_at",
                              "page_number", "read_limit", "read_total", "stop_reason", "unread_count")},
         "error": _json(r["error_json"])}
        for r in conn.execute("SELECT * FROM search_runs WHERE research_id = ? ORDER BY retrieved_at", (research_id,))
    ]
    # What a paged query left unread is the count on its last stopped page; a page read again replaces the earlier
    # row rather than adding to it, and an unknown provider total is skipped instead of counted as zero (slice 04c).
    last_stopped: dict[tuple[str, str, str], dict[str, Any]] = {}
    for row in search_runs:
        if row["stop_reason"] is None:
            continue
        key = (row["run_id"], row["provider"], row["query_text"])
        order = (row["page_number"] or 0, row["retrieved_at"], row["id"])
        seen = last_stopped.get(key)
        if seen is None or order >= (seen["page_number"] or 0, seen["retrieved_at"], seen["id"]):
            last_stopped[key] = row

    from deixis.workflow import late_revision
    answers = []
    cited_sources: set[str] = set()
    # A quote of a source removed from this research still opens; the view names the removal (D50).
    removed = {r[0] for r in conn.execute(
        "SELECT source_version_id FROM corpus_memberships WHERE research_id = ? AND removed_at IS NOT NULL", (research_id,))}
    for a in conn.execute("SELECT * FROM answers WHERE research_id = ? ORDER BY created_at DESC, rowid DESC", (research_id,)):
        draft = _json(a["draft_json"])
        claims = []
        for c in conn.execute("SELECT * FROM claims WHERE answer_id = ? ORDER BY ordinal", (a["id"],)):
            evidence = [
                {"passage_id": e["passage_id"], "source_version_id": e["source_version_id"], "work_id": e["work_id"],
                 "source_key": e["source_key"], "kind": e["kind"],
                 "physical_page": e["physical_page"], "printed_label": e["printed_label"],
                 "reading_depth": "abstract" if e["kind"] == "abstract" else "selected_sections", "title": e["title"],
                 "version_label": e["version_label"], "anchor_text": e["anchor_text"], "evidence_status": e["evidence_status"],
                 "text_source": e["text_source"], "removed_from_research": e["source_version_id"] in removed,
                 # Europe PMC's text drawn as a PDF: its page is DEIXIS's, not the publisher's (SW21).
                 "rendition": bool(e["rendition"])}
                for e in conn.execute(
                    "SELECT l.passage_id, l.source_version_id, s.work_id, l.anchor_text, p.kind, p.physical_page, p.printed_label, p.text_source, s.title, s.version_label,"
                    " (SELECT w.source_key FROM works w WHERE w.id = s.work_id) AS source_key,"
                    f" {EVIDENCE_STATUS_SQL} AS evidence_status, {RENDITION_SQL} AS rendition FROM evidence_links l"
                    " JOIN passages p ON p.id = l.passage_id JOIN source_versions s ON s.id = l.source_version_id"
                    " LEFT JOIN source_assets a ON a.id = p.asset_id"
                    " WHERE l.claim_id = ? ORDER BY l.rowid", (c["id"],)
                )
            ]
            if not answers:
                cited_sources.update(e["source_version_id"] for e in evidence)
            claims.append({"id": c["id"], "label": c["label"], "section": c["section"], "text": c["text"], "support_type": c["support_type"],
                           "semantic_review": c["semantic_review"], "evidence": evidence})
        fast_answer = fast_path.enforces(store.run(a["run_id"])["budget"], "answer")
        if fast_answer:
            for claim in claims:
                kinds = {e["kind"] for e in claim["evidence"]}
                claim["evidence_basis"] = ("abstract" if kinds == {"abstract"} else "mixed"
                                           if "abstract" in kinds else "full_text" if kinds else None)
        session = conn.execute(
            "SELECT connection, requested_model, resolved_model, token_usage_json FROM model_sessions WHERE step_input_id = ?",
            (a["step_input_id"],),
        ).fetchone() if a["step_input_id"] else None
        review = _review_view(store, a["id"])
        verdicts = {r["claim_label"]: {"verdict": r["verdict"], "reason": r["reason"]} for r in (review or {}).get("reviews", [])}
        for claim in claims:
            claim["review"] = verdicts.get(claim["label"])
        given = store.step_input_payload(a["step_input_id"]) if a["step_input_id"] else None
        validation = _json(a["validation_json"]) or {}
        answers.append({
            **late_revision.answer_view(store, a["id"]),
            "id": a["id"], "run_id": a["run_id"], "status": a["status"], "scope_revision": a["scope_revision"],
            # A report keeps the number it was saved with; later answers do not rewrite it. The title is V1's (below).
            "report_version": a["report_version"], "report_revision": a["report_revision"],
            "report_title": (draft or {}).get("title") if a["status"] == "structurally_valid" else None,
            "applicability": result_applicability(a["scope_revision"], research["current_scope_revision"],
                                                  a["selection_revision"], research["selection_revision"]),
            "answer_language": a["answer_language"], "created_at": a["created_at"], "claims": claims,
            # Works this answer read only because a person's Screen more run made them candidates after the read
            # cutoff: abstract-based evidence, screened after the cutoff (UI parity S20).
            "screened_after_cutoff": screen_more.answer_view(store, a["run_id"]),
            "limitations": (draft or {}).get("limitations", []) if a["status"] == "structurally_valid" else [],
            "unanswered_aspects": (draft or {}).get("unanswered_aspects", []) if a["status"] == "structurally_valid" else [],
            "capability_notice": (draft or {}).get("capability_notice") if a["status"] == "structurally_valid" else None,
            "clarification": draft if a["status"] == "clarification" else None,
            "unverified_draft": draft if a["status"] == "unverified_draft" else None,
            "validation": validation,
            "model": {"connection": session["connection"], "requested_model": session["requested_model"],
                      "resolved_model": session["resolved_model"], "token_usage": _json(session["token_usage_json"])} if session else None,
            # A file or text extraction this answer read is no longer in use; its quotes still open what was read (D45).
            "source_text_changed": source_text_changed(store, given),
            # Works whose full text a model or a person read and decided on after this answer's run started: what a new
            # answer would read that this one did not ("Update the answer with N new full texts").
            "fulltext_read_since": _fulltext_read_since(store, a),
            "inputs_given": {"sources": len(given["sources"]), "passages": len(given["passages"]),
                             "source_ids": [s["source_id"] for s in given["sources"]],
                             "depth": _given_depth(given)} if given else None,
            # Where the flow stood when this answer's run started (slice 20); null for an answer whose run kept none,
            # never today's counts in its place. Beside `inputs_given`, not instead of it.
            "start_snapshot": _start_snapshot(store, a),
            "review": review,
            **({"abstract_only_sources": len({e["source_version_id"] for c in claims for e in c["evidence"]
                if e["kind"] == "abstract"} - {e["source_version_id"] for c in claims for e in c["evidence"]
                if e["kind"] != "abstract"})} if fast_answer else {}),
        })
        answers[-1]["applicability"] = late_applicability(answers[-1], answers[-1]["applicability"])
    # A research keeps one report title: every version carries the title V1 was saved with.
    first = min((a for a in answers if a["report_title"] is not None and a["report_version"] is not None),
                key=lambda a: (a["report_version"], a["report_revision"] or 0), default=None)
    for a in answers:
        if first and a["report_title"] is not None:
            a["report_title"] = first["report_title"]
    # Similarity from the chosen semantic search model only; with semantic search off, no source has one (D30).
    provider, model = embeddings.chosen(store.setting("semantic_search"))
    similarity_model = embeddings.Embedder(provider, model).stored_model if provider != "off" and model else None
    answered_in_queue = queue_answers(store, research_id)
    sources = []
    work_flags = store.research_works_retracted(research_id)
    for row in conn.execute(
        "SELECT m.added_by, m.created_at AS added_at, s.*, sel.state, sel.origin AS selection_origin, sel.version AS selection_version, sel.proposal,"
        " (SELECT w.source_key FROM works w WHERE w.id = s.work_id) AS source_key,"
        " sel.proposal_reason, sel.proposal_basis, sel.user_reason, c.id AS candidate_id, c.rank, c.scope_revision AS found_in_revision,"
        " (SELECT ss.similarity FROM source_similarities ss WHERE ss.research_id = m.research_id AND ss.source_version_id = m.source_version_id"
        "  AND ss.scope_revision = c.scope_revision AND ss.model = ?) AS similarity"
        " FROM corpus_memberships m JOIN source_versions s ON s.id = m.source_version_id"
        " JOIN selections sel ON sel.research_id = m.research_id AND sel.source_version_id = m.source_version_id"
        " LEFT JOIN candidates c ON c.research_id = m.research_id AND c.source_version_id = m.source_version_id"
        " WHERE m.research_id = ? AND m.removed_at IS NULL ORDER BY m.created_at, c.rank", (similarity_model, research_id)
    ):
        svid = row["id"]
        # The PDF in use, whether its text comes from the current extractor, and a later extraction that was not taken (D45).
        # A math extraction (D52) or an arXiv source reading (D104) builds on the current extractor's text; its own
        # "nothing to read" or failed attempts are reported as the PDF's equation state, not as a rejected re-extraction.
        assets = [dict(r) | {"text_recovery": recovery_view.text_recovery(store, store.asset(r["id"]), svid, None),
                             "current_extraction": (r["extraction_version"] or "").split("+")[0] == pdf.EXTRACTION_VERSION,
                             "equations": equation_state(store, r["id"]), "ocr": ocr_state(store, r["id"]), "rejected_extraction": dict(rejected) if (rejected := conn.execute(
            "SELECT extraction_version, rejection_reason, created_at FROM asset_extractions WHERE asset_id = ? AND outcome = 'rejected'"
            " AND extraction_version NOT LIKE '%+marker-%' AND extraction_version NOT LIKE '%+arxiv-latex-%'"
            " AND extraction_version NOT LIKE '%+mathpix-%'"
            " ORDER BY created_at DESC, rowid DESC LIMIT 1", (r["id"],)).fetchone()) else None} for r in conn.execute(
            "SELECT id, extraction_status, extraction_error, extraction_version, page_count, origin, byte_size, original_filename"
            " FROM source_assets WHERE source_version_id = ? AND removed_at IS NULL", (svid,)
        )]
        replaced_assets = [dict(r) for r in conn.execute(
            "SELECT id, original_filename, removed_at, replaced_by_asset_id FROM source_assets"
            " WHERE source_version_id = ? AND removal_reason = 'replaced' ORDER BY removed_at DESC", (svid,)
        )]
        abstract = conn.execute(
            "SELECT id, abstract_origin FROM passages WHERE source_version_id = ? AND kind = 'abstract' LIMIT 1", (svid,)
        ).fetchone()
        # The link's latest attempt in any research: a refused link is not requested again (see Store.pdf_link_refusal).
        # Equal start times select the last inserted step (rowid), not the random step id or the index's traversal order.
        fetch = conn.execute(
            "SELECT status, error_code, json_extract(error_json, '$.http_status') AS http_status FROM run_steps"
            " WHERE operation_key = ? ORDER BY started_at DESC, rowid DESC LIMIT 1", (f"fetch:{svid}",)
        ).fetchone()
        other_copy = conn.execute(
            "SELECT s.status, s.error_code FROM run_steps s JOIN runs r ON r.id = s.run_id"
            " WHERE r.research_id = ? AND s.operation_key = ? ORDER BY s.started_at DESC, s.rowid DESC LIMIT 1", (research_id, f"other_copy:{svid}")
        ).fetchone()
        pdf_candidates = [{k: r[k] for k in (
            "id", "provider", "candidate_url", "landing_url", "version_label", "license", "identity_status",
            "version_status", "access_status", "http_status", "error_code", "final_url", "discovered_at", "attempted_at"
        )} for r in conn.execute(
            # Web results under another paper's title, stored before those were dropped at lookup, are not shown.
            "SELECT * FROM pdf_candidates WHERE source_version_id = ? AND identity_status != 'unverified'"
            " ORDER BY discovered_at, rowid", (svid,)
        )]
        sources.append({
            "source_version_id": svid, "work_id": row["work_id"], "source_key": row["source_key"], "title": row["title"],
            "authors": json.loads(row["authors_json"]),
            "year": row["year"], "venue": row["venue"], "volume": row["volume"], "issue": row["issue"],
            "pages": row["pages"], "doi": row["doi"], "landing_url": row["landing_url"],
            "version_label": row["version_label"], "publication_type": row["publication_type"], "origin": row["origin"],
            # The record an uploaded PDF was identified as (D37); None for a provider record or an unmatched upload.
            "record_match": json.loads(row["record_match_json"]) if row["record_match_json"] else None,
            "cited_by_count": row["cited_by_count"], "cited_by_count_at": row["cited_by_count_at"],
            # The version's own flag, and the work's: a preprint of a retracted article is marked too (D27).
            "is_retracted": _retracted(row["is_retracted"]), "work_is_retracted": work_flags.get(row["work_id"]),
            "added_by": row["added_by"], "added_at": row["added_at"], "rank": row["rank"], "similarity": row["similarity"],
            # Whether an answer can read this version's PDF pages rather than its abstract (D49).
            "has_pdf_text": bool(assets) and store.has_pdf_text(svid),
            # Some of that text was read with OCR from scanned pages and is labelled so (D51).
            "has_ocr_text": bool(assets) and any(p["text_source"] == "ocr" for p in store.passages_for(svid)),
            # "other_version": another version of a found record (e.g. its submitted manuscript), stored separately.
            "version_role": "other_version" if row["added_by"] == "search" and row["candidate_id"] is None else "record",
            # A search result keeps the question revision it was found for; attached files belong to no revision.
            "found_in_revision": row["found_in_revision"],
            "applicability": "current" if row["found_in_revision"] is None
            else result_applicability(row["found_in_revision"], research["current_scope_revision"]),
            "access": {"abstract_passage_id": abstract["id"] if abstract else None,
                       "abstract_origin": abstract["abstract_origin"] if abstract else None,
                       "oa_pdf_url": row["oa_pdf_url"], "oa_pdf_version": row["oa_pdf_version"], "assets": assets, "replaced_assets": replaced_assets,
                       "fetch": dict(fetch) if fetch else None, "other_copy": dict(other_copy) if other_copy else None,
                       "pdf_candidates": pdf_candidates,
                       "pdf_discoveries": store.pdf_discoveries(research_id, svid, retry_after=True)},
            "selection": {"state": row["state"], "origin": row["selection_origin"], "version": row["selection_version"],
                          "proposal": row["proposal"], "proposal_reason": row["proposal_reason"],
                          "proposal_basis": row["proposal_basis"], "user_reason": row["user_reason"],
                          # A selection the human queue wrote (slice 17): the answer, read from its stored link.
                          "queue_answer": answered_in_queue.get((svid, row["selection_version"]))
                          if row["selection_origin"] == "user" else None},
            "cited_in_latest_answer": svid in cited_sources,
            # Providers whose records map to this source version (one DOI from several providers is one source).
            "provider_records": [r[0] for r in conn.execute(
                "SELECT DISTINCT provider FROM identifier_mappings WHERE source_version_id = ? AND scheme = provider ORDER BY provider", (svid,)
            )],
        })

    # A work has one record, its head: a published record, else the first (D46, D48). Another candidate of the same work
    # (a preprint screened before its published record joined the work) is shown as another version of the head.
    heads = store.work_heads(research_id)
    reads_version = store.answer_versions(research_id)
    for s in sources:
        if s["version_role"] == "record" and heads.get(s["work_id"]) != s["source_version_id"]:
            s["version_role"] = "other_version"
        # The version whose text an answer reads when it is not the head itself (D48), and whether the answer reads
        # no version of the work at all: its only PDF text is a person's file not read yet (slice 18b, decision 8).
        s["answer_reads_version_id"] = None
        s["answer_reads_nothing"] = False
        # What code and the model runs decided about the work, for the list's "Model proposal" column (UI parity S13);
        # other versions follow their record.
        s["screening"] = flow_rules.machine_screening(ctx, s["work_id"]) if s["version_role"] == "record" else None
        if s["version_role"] == "record":
            reads = reads_version.get(s["source_version_id"], s["source_version_id"])
            if reads is None:
                s["answer_reads_nothing"] = True
            elif reads != s["source_version_id"]:
                s["answer_reads_version_id"] = reads

    # Other versions follow the record of their work and share its question revision.
    others: dict[str, list[dict[str, Any]]] = {}
    for s in sources:
        if s["version_role"] == "other_version":
            others.setdefault(s["work_id"], []).append(s)
    ordered: list[dict[str, Any]] = []
    for record in (s for s in sources if s["version_role"] == "record"):
        ordered.append(record)
        # Grouped once rather than scanned per record: the nested scan was 2.2 s of the view's 7.2 s on the
        # smoke run's 7,769-source research (slice 13d).
        ordered += [s | {"found_in_revision": record["found_in_revision"], "applicability": record["applicability"]}
                    for s in others.get(record["work_id"], ())]
    placed = {s["source_version_id"] for s in ordered}
    sources = ordered + [s for s in sources if s["source_version_id"] not in placed]

    # Versions of one work are not independent: unique, included, given and cited count works.
    work_of = {s["source_version_id"]: s["work_id"] for s in sources}

    def works(ids: Any) -> int:
        return len({work_of.get(i, i) for i in ids})

    latest_given = next((a["inputs_given"] for a in answers if a["inputs_given"]), None)
    counts = {
        "found": sum(s["result_count"] for s in search_runs),
        "unread": sum(s["unread_count"] or 0 for s in last_stopped.values()),
        "unique": works(work_of),
        # A work's selection is its head's; other versions follow it (D48).
        "included": sum(s["selection"]["state"] == "included" for s in sources if s["version_role"] == "record"),
        "excluded": sum(s["selection"]["state"] == "excluded" for s in sources if s["version_role"] == "record"),
        "pending": sum(s["selection"]["state"] == "pending" for s in sources if s["version_role"] == "record"),
        "inspected": works(latest_given["source_ids"]) if latest_given else 0,
        "cited": works(cited_sources),
        # Works the user removed from this research, and those a later search found again; neither is listed (D50).
        **dict(zip(("removed", "removed_found_again"), conn.execute(
            "SELECT COUNT(DISTINCT v.work_id), COUNT(DISTINCT CASE WHEN m.found_again_at IS NOT NULL THEN v.work_id END)"
            " FROM corpus_memberships m JOIN source_versions v ON v.id = m.source_version_id"
            " WHERE m.research_id = ? AND m.removed_at IS NOT NULL", (research_id,)).fetchone())),
    }
    counts["fulltext_read_works"] = _fulltext_read_works(store, research_id, research["current_scope_revision"])
    # The human queue's open rows and the decisions to look at again (slice 16).
    counts |= queue_counts(store, research_id, ctx)
    # The works waiting for the person's PDF (slice 18a).
    counts["waiting_for_pdf"] = len(waiting_rules.for_context(ctx)[1])
    # Every work of the revision in one bucket, PRISMA 2020-style boxes and the override count (slice 20), from the
    # same context and probe set as the queue counts.
    flow = flow_rules.flow_counts(ctx, probe)
    counts["flow"] = flow
    counts["flow_boxes"] = flow_rules.flow_boxes(ctx, flow)
    # Provider rows → unique works → abstracts read → candidates → included, for the search step's headline (D233).
    counts["funnel"] = flow_rules.funnel(ctx, flow, counts["flow_boxes"])
    counts["overrides"] = override_rules.overrides_view(ctx, probe)
    last_event = conn.execute("SELECT MAX(id) FROM events WHERE research_id = ?", (research_id,)).fetchone()[0] or 0
    reviewer = effective_reviewer(scope, store.setting("reviewer"))
    report_runs = [dict(row) for row in conn.execute(
        "SELECT id, status, report_version, created_at FROM reports"
        " WHERE research_id = ? ORDER BY created_at DESC, rowid DESC", (research_id,),
    )]
    # Every run of the research, not only the ten listed in `runs` (UI parity S11, the rail's Activity row). Beside
    # `runs`, not in `counts`: it is not an evidence count, and a watch check, which is a run, changes no count.
    run_total = conn.execute("SELECT COUNT(*) FROM runs WHERE research_id = ?", (research_id,)).fetchone()[0]
    # The study table an unfinished answer opens when it ends (report_pipeline.after_answer), so the rail can say it is
    # coming: only while the research has no table and includes a source; a late full-text revision opens none.
    included_now = store.included_sources(research_id) if store.study_table == "auto" else []
    study_table_pending = {"sources": len(included_now)} if included_now and not conn.execute(
        "SELECT 1 FROM evidence_tables WHERE research_id = ? AND trashed_at IS NULL LIMIT 1", (research_id,)).fetchone() and conn.execute(
        "SELECT 1 FROM runs r LEFT JOIN runs a ON a.id = json_extract(r.target_json, '$.answer_run_id')"
        " WHERE r.research_id = ? AND r.scope_revision = ? AND r.kind IN ('answer', 'answer_review')"
        " AND r.status IN ('queued', 'running', 'pause_requested', 'paused')"
        " AND COALESCE(json_extract(COALESCE(a.budget_json, r.budget_json), '$.trigger'), '') != 'late_fulltext' LIMIT 1",
        (research_id, research["current_scope_revision"])).fetchone() else None
    return {"research": research, "intent_outcome": intent_outcome(store, research), "scope": scope_view, "runs": runs,
            "run_total": run_total, "study_table_pending": study_table_pending, "search_runs": search_runs, "sources": sources,
            "answers": answers, "reportRuns": report_runs, "counts": counts, "last_event_id": last_event,
            # The semantic search arm for this research's current revision (slice 21); no count of what will be sent.
            "semantic": semantic_view(store, research_id, scope),
            # The probe set's columns and the probes no arm found (slice 19).
            "probes": probe_rules.probes_view(store, research_id, probe),
            # The reviewer the next answer would get: the research's own setting, else the app-wide default.
            "reviewer": {"mode": scope["review_mode"], "connection": reviewer[0] if reviewer else None, "model": reviewer[1] if reviewer else None,
                         "reasoning_effort": reviewer[2] if reviewer else None},
            # Every model change a person made in this research, oldest first (UI parity S17, F10); `scope` and
            # `reviewer` above already give the models in effect now.
            "model_changes": store.model_changes(research_id)}


def semantic_view(store: Store, research_id: str, scope: dict[str, Any]) -> dict[str, Any]:
    """The provider semantic search uses, and whether its arm runs for this revision (D103, decision 10).

    `arm`: "off" (no provider), "english_question_missing" (the built-in model, a question not in English and no
    sentence saved), "not_installed" (the built-in model is chosen but not ready now), else "on". The provider is
    what Settings say now; a run freezes its own in its step."""
    provider, model = embeddings.chosen(store.setting("semantic_search"))
    stored_model = embeddings.Embedder(provider, model).stored_model if provider != "off" and model else None
    row = store.english_question(research_id, scope["revision"])
    needs = provider == "builtin" and not english_question_rules.is_english(scope["question"], scope.get("language_hint"))
    if stored_model is None:
        arm = "off"
    elif needs and row is None:
        arm = "english_question_missing"
    elif provider == "builtin" and not local_embedding.builtin_available():
        arm = "not_installed"
    else:
        arm = "on"
    return {"provider": provider, "stored_model": stored_model, "arm": arm,
            "english_question": {"text": row["text"], "origin": row["origin"]} if row else None,
            "needs_english_question": needs}


def _given_depth(given: dict[str, Any]) -> dict[str, int]:
    """How deeply an answer was given each work it read, in works, from its stored StepInput (UI parity S11): `pdf`
    when at least one PDF page of the work was given, `abstract` when only its abstract was, `metadata` when the work
    was given with no passage. A PDF or a selection that changed after the answer does not change it."""
    work_of = {s["source_id"]: s.get("work_id") or s["source_id"] for s in given["sources"]}
    kinds: dict[str, set[str]] = {work: set() for work in work_of.values()}
    for passage in given["passages"]:
        if not isinstance(passage, dict) or not passage.get("source_id"):
            continue  # a stored input without the passage's source names no work to count it under
        work = work_of.get(passage["source_id"], passage["source_id"])
        kinds.setdefault(work, set()).add("abstract" if (passage.get("locator") or {}).get("kind") == "abstract" else "pdf")
    return {"pdf": sum("pdf" in k for k in kinds.values()), "abstract": sum(k == {"abstract"} for k in kinds.values()),
            "metadata": sum(not k for k in kinds.values())}


def _fulltext_read_works(store: Store, research_id: str, revision: int) -> int:
    """Works of this question revision whose full text was read (UI parity S11): both passes of the reading stored a
    result in the same run on the same version, as the reading step's line counts one run; here over every run of the
    revision, each work once. The version and the pass are the ones the stored StepInput was given."""
    passes: dict[tuple[str, str], set[int]] = {}
    for row in store.conn.execute(
            "SELECT DISTINCT i.run_id, json_extract(i.payload_json, '$.adjudication_target.source_id') AS source,"
            " json_extract(i.payload_json, '$.adjudication_target.run') AS pass FROM step_inputs i"
            " JOIN run_steps s ON s.id = i.step_id JOIN runs r ON r.id = i.run_id"
            " WHERE i.research_id = ? AND i.task_type = 'fulltext_adjudication' AND r.scope_revision = ?"
            " AND s.kind = 'model:fulltext_adjudication' AND s.status = 'succeeded'", (research_id, revision)):
        if row["source"] and row["pass"] is not None:
            passes.setdefault((row["run_id"], row["source"]), set()).add(row["pass"])
    read = sorted({source for (_, source), done in passes.items() if set(range(1, FULLTEXT_RUNS + 1)) <= done})
    if not read:
        return 0
    return store.conn.execute(
        f"SELECT COUNT(DISTINCT work_id) FROM source_versions WHERE id IN ({','.join('?' * len(read))})", read
    ).fetchone()[0]


def _fulltext_read_since(store: Store, answer: Any) -> int:
    return store.conn.execute(
        "SELECT COUNT(DISTINCT d.source_version_id) FROM stage_decisions d JOIN runs r ON r.id = ?"
        " WHERE d.research_id = r.research_id AND d.stage = 'fulltext' AND d.decided_by IN ('model_agreement', 'human')"
        " AND d.outcome IN ('include', 'criterion_not_met') AND d.superseded_at IS NULL AND d.created_at > r.created_at",
        (answer["run_id"],)).fetchone()[0]


def _start_snapshot(store: Store, answer: Any) -> dict[str, Any] | None:
    """The `code:answer_start_snapshot` step of this answer's run, and whether the included sources' state moved
    while the answer ran (its own selection revision is not the one the snapshot read)."""
    step = store.existing_step(answer["run_id"], "answer_start_snapshot")
    if step is None or step["status"] != "succeeded" or not step["output"]:
        return None
    output = step["output"]
    return output | {"included_state_changed": answer["selection_revision"] is not None
                     and output["selection_revision"] != answer["selection_revision"]}


# Reading depth of one stored source version. A PDF text layer, an abstract and bare metadata are
# different evidence levels (AGENTS.md), so the library names the level instead of a generic badge.
_HAS_PDF_TEXT = ("EXISTS (SELECT 1 FROM passages p JOIN source_assets a ON a.id = p.asset_id"
                 " WHERE p.source_version_id = v.id AND a.removed_at IS NULL)")
_HAS_ABSTRACT = "EXISTS (SELECT 1 FROM passages p WHERE p.source_version_id = v.id AND p.kind = 'abstract')"
_ACCESS_ORDER = ["metadata", "abstract", "pdf_available"]


def _access_level(has_pdf_text: int, has_abstract: int) -> str:
    return "pdf_available" if has_pdf_text else "abstract" if has_abstract else "metadata"


def _retracted(value: int | None) -> bool | None:
    """One version's stored OpenAlex flag (D27): None is unknown; False means only that OpenAlex does not flag it."""
    return None if value is None else bool(value)


# Rank one version of a work as the representative shown in the library table: richer bibliographic
# records first, so a bare preprint never hides the published version's metadata.
def _library_representative_score(row: dict[str, Any]) -> tuple[int, ...]:
    return (
        1 if row["cited_by_count"] is not None else 0,
        1 if row["authors"] else 0,
        1 if row["year"] is not None else 0,
        1 if row["venue"] else 0,
        1 if row["doi"] else 0,
        1 if row["version_label"] else 0,
        1 if row["publication_type"] else 0,
    )


_LIBRARY_ITEM_COLUMNS = "origin, metadata_origin, metadata_confirmed_by, metadata_confirmed_at, added_at"


def _library_items(conn: Any, svids: list[str] | None = None) -> dict[str, dict[str, Any]]:
    """Saved Library items by source version (S19a); every one when `svids` is None."""
    where = f" WHERE source_version_id IN ({', '.join('?' * len(svids))})" if svids is not None else ""
    rows = conn.execute(f"SELECT source_version_id, {_LIBRARY_ITEM_COLUMNS} FROM library_items{where}", svids or ()).fetchall()
    return {row["source_version_id"]: {k: row[k] for k in row.keys() if k != "source_version_id"} for row in rows}


def library_view(store: Store) -> dict[str, Any]:
    """Every work (publication) in any non-trashed research or saved in the Library, with its versions and the
    researches it belongs to. Each version stays its own record; a saved one carries its `library_item`."""
    conn = store.conn
    rows = conn.execute(
        "SELECT v.id AS source_version_id, v.work_id, v.title, v.authors_json, v.year, v.venue, v.volume, v.issue,"
        " v.pages, v.publication_type, v.doi, v.landing_url, v.version_label, v.cited_by_count, v.cited_by_count_at,"
        " v.created_at AS source_created_at, r.id AS research_id, r.title AS research_title, r.updated_at AS research_updated_at,"
        " m.removed_at,"
        f" {_HAS_PDF_TEXT} AS has_pdf_text, {_HAS_ABSTRACT} AS has_abstract"
        " FROM corpus_memberships m JOIN source_versions v ON v.id = m.source_version_id"
        " JOIN researches r ON r.id = m.research_id WHERE r.trashed_at IS NULL"
        " ORDER BY v.created_at DESC, r.updated_at DESC"
    ).fetchall()
    # Saved items join with no research: one held only by the Library, or by a trashed research, still lists.
    saved_rows = conn.execute(
        "SELECT v.id AS source_version_id, v.work_id, v.title, v.authors_json, v.year, v.venue, v.volume, v.issue,"
        " v.pages, v.publication_type, v.doi, v.landing_url, v.version_label, v.cited_by_count, v.cited_by_count_at,"
        " v.created_at AS source_created_at, NULL AS research_id, NULL AS research_title, NULL AS research_updated_at,"
        " NULL AS removed_at,"
        f" {_HAS_PDF_TEXT} AS has_pdf_text, {_HAS_ABSTRACT} AS has_abstract"
        " FROM library_items i JOIN source_versions v ON v.id = i.source_version_id ORDER BY v.created_at DESC"
    ).fetchall()
    saved = _library_items(conn)
    # A source counts as relevant to its research when the user brought it, the full-text reading included it, or the
    # abstract reading kept it as a candidate that no full-text reading rejected. Works the search found but never read,
    # or read and set aside, stay listed; the Library only hides them by default.
    relevant = {(r["research_id"], r["source_version_id"]) for r in conn.execute(
        "SELECT m.research_id, m.source_version_id FROM corpus_memberships m WHERE m.removed_at IS NULL AND ("
        " m.added_by != 'search'"
        " OR EXISTS (SELECT 1 FROM stage_decisions d WHERE d.research_id = m.research_id"
        "  AND d.source_version_id = m.source_version_id AND d.superseded_at IS NULL AND d.stage = 'fulltext' AND d.outcome = 'include')"
        " OR (EXISTS (SELECT 1 FROM stage_decisions d WHERE d.research_id = m.research_id"
        "  AND d.source_version_id = m.source_version_id AND d.superseded_at IS NULL AND d.stage = 'abstract' AND d.outcome = 'candidate')"
        "  AND NOT EXISTS (SELECT 1 FROM stage_decisions d WHERE d.research_id = m.research_id"
        "  AND d.source_version_id = m.source_version_id AND d.superseded_at IS NULL AND d.stage = 'fulltext'"
        "  AND d.outcome = 'criterion_not_met')))"
    )}

    works: dict[str, dict[str, Any]] = {}
    for row in [*rows, *saved_rows]:
        work = works.setdefault(row["work_id"], {"versions": {}, "researches": {}, "relevant": set()})
        svid = row["source_version_id"]
        if svid not in work["versions"]:
            work["versions"][svid] = {
                "source_version_id": svid, "title": row["title"], "version_label": row["version_label"], "year": row["year"],
                "venue": row["venue"], "doi": row["doi"], "authors": json.loads(row["authors_json"]),
                "publication_type": row["publication_type"], "landing_url": row["landing_url"],
                "cited_by_count": row["cited_by_count"], "cited_by_count_at": row["cited_by_count_at"],
                "source_created_at": row["source_created_at"],
                "access_level": _access_level(row["has_pdf_text"], row["has_abstract"]),
                "library_item": saved.get(svid), "research_ids": [],
            }
        rid = row["research_id"]
        # A source removed from a research stays in the library but not in that research's project group (D50).
        if rid is not None and row["removed_at"] is None:
            # Which researches hold this version now, so a removal names only versions the research holds (S25).
            if rid not in work["versions"][svid]["research_ids"]:
                work["versions"][svid]["research_ids"].append(rid)
            if rid not in work["researches"]:
                work["researches"][rid] = {"id": rid, "title": row["research_title"], "updated_at": row["research_updated_at"]}
            if (rid, svid) in relevant:
                work["relevant"].add(rid)

    entries = []
    for work_id, work in works.items():
        versions = list(work["versions"].values())
        versions.sort(key=lambda v: (v["source_created_at"] is None, v["source_created_at"] or ""), reverse=True)
        representative = max(versions, key=_library_representative_score)
        researches = sorted(work["researches"].values(), key=lambda r: r["updated_at"] or "", reverse=True)
        entries.append({
            "work_id": work_id, "source_key": store.source_key(work_id),
            "title": representative["title"],
            "authors": representative["authors"],
            "year": representative["year"], "venue": representative["venue"],
            "publication_type": representative["publication_type"], "doi": representative["doi"],
            "landing_url": representative["landing_url"],
            "cited_by_count": max((v["cited_by_count"] for v in versions if v["cited_by_count"] is not None), default=None),
            "cited_by_count_at": representative["cited_by_count_at"],
            "is_retracted": store.work_retracted(work_id),
            "versions": [{"source_version_id": v["source_version_id"], "version_label": v["version_label"],
                          "year": v["year"], "venue": v["venue"], "access_level": v["access_level"],
                          "library_item": v["library_item"], "research_ids": v["research_ids"]} for v in versions],
            # The version whose bibliographic fields the row shows; a bibliography of the row exports this record.
            "representative_source_version_id": representative["source_version_id"],
            "saved": any(v["library_item"] for v in versions),
            # The best reading depth any stored version of this work reaches; the panel lists each version separately.
            "access_level": max((v["access_level"] for v in versions), key=_ACCESS_ORDER.index),
            "researches": researches,
            # The researches this work is relevant to (see `relevant` above), newest first.
            "relevant_research_ids": [r["id"] for r in researches if r["id"] in work["relevant"]],
            "first_research_id": researches[0]["id"] if researches else None,
            "newest_source_at": max(max(v["source_created_at"] or "", (v["library_item"] or {}).get("added_at") or "")
                                    for v in versions),
        })

    # Most recently added works first; within a tie, newest active research first.
    entries.sort(key=lambda e: (e["newest_source_at"], e["first_research_id"] or ""), reverse=True)
    # Every active research, including ones with no source yet, so each can be a group and a drop target.
    researches = [dict(r) for r in conn.execute(
        "SELECT id, title, updated_at FROM researches WHERE trashed_at IS NULL ORDER BY updated_at DESC"
    )]
    return {
        "entries": entries,
        "researches": researches,
        "counts": {"works": len(entries), "versions": sum(len(e["versions"]) for e in entries),
                   "researches": len({r["id"] for e in entries for r in e["researches"]})},
    }


def library_version_to_add(work: dict[str, Any]) -> dict[str, Any]:
    """The one version of a work that joins a research when the user adds the work from the Library.

    The deepest stored reading comes first, so a paywalled published record never replaces a preprint whose
    text DEIXIS holds; among equals, the richer bibliographic record. Other versions stay out: they are
    different evidence, not copies.
    """
    return max(work["versions"], key=lambda v: (_ACCESS_ORDER.index(v["access_level"]), _library_representative_score(v)))


def library_work_view(store: Store, work_id: str) -> dict[str, Any] | None:
    """One work in reading depth: every stored version with its access level, abstract and PDF asset.

    Versions stay separate. A preprint and a published version are different evidence, so the panel
    never merges their abstracts or files into one record.
    """
    conn = store.conn
    rows = conn.execute(
        "SELECT v.id AS source_version_id, v.work_id, v.title, v.authors_json, v.year, v.venue, v.doi,"
        " v.landing_url, v.version_label, v.publication_type, v.cited_by_count, v.cited_by_count_at, v.is_retracted,"
        f" v.created_at AS source_created_at, {_HAS_PDF_TEXT} AS has_pdf_text, {_HAS_ABSTRACT} AS has_abstract"
        " FROM source_versions v WHERE v.work_id = ?"
        " AND (EXISTS (SELECT 1 FROM corpus_memberships m JOIN researches r ON r.id = m.research_id"
        "  WHERE m.source_version_id = v.id AND r.trashed_at IS NULL)"
        "  OR EXISTS (SELECT 1 FROM library_items i WHERE i.source_version_id = v.id))"
        " ORDER BY v.created_at DESC", (work_id,)
    ).fetchall()
    if not rows:
        return None
    saved = _library_items(conn, [row["source_version_id"] for row in rows])

    versions, researches = [], {}
    for row in rows:
        svid = row["source_version_id"]
        abstract = conn.execute(
            "SELECT id, text, abstract_origin FROM passages WHERE source_version_id = ? AND kind = 'abstract'"
            " ORDER BY created_at DESC LIMIT 1", (svid,)
        ).fetchone()
        asset = conn.execute(
            "SELECT id, page_count, original_filename, extraction_status FROM source_assets"
            " WHERE source_version_id = ? AND removed_at IS NULL ORDER BY retrieved_at DESC LIMIT 1", (svid,)
        ).fetchone()
        members = conn.execute(
            "SELECT r.id, r.title, r.updated_at FROM corpus_memberships m JOIN researches r ON r.id = m.research_id"
            " WHERE m.source_version_id = ? AND m.removed_at IS NULL AND r.trashed_at IS NULL ORDER BY r.updated_at DESC", (svid,)
        ).fetchall()
        for member in members:
            researches.setdefault(member["id"], {"id": member["id"], "title": member["title"],
                                                 "updated_at": member["updated_at"]})
        versions.append({
            "source_version_id": svid, "version_label": row["version_label"], "year": row["year"],
            "venue": row["venue"], "doi": row["doi"], "landing_url": row["landing_url"],
            "publication_type": row["publication_type"], "authors": json.loads(row["authors_json"]),
            "cited_by_count": row["cited_by_count"], "is_retracted": _retracted(row["is_retracted"]),
            "added_at": row["source_created_at"],
            "access_level": _access_level(row["has_pdf_text"], row["has_abstract"]),
            "abstract": abstract["text"] if abstract else None,
            "abstract_origin": abstract["abstract_origin"] if abstract else None,
            # The PDF opens through a research that holds this version; the asset route is research-scoped.
            "asset": {"id": asset["id"], "page_count": asset["page_count"],
                      "original_filename": asset["original_filename"],
                      "extraction_status": asset["extraction_status"]} if asset else None,
            "abstract_passage_id": abstract["id"] if abstract else None,
            "library_item": saved.get(svid),
            "research_id": members[0]["id"] if members else None,
            # No research holds this version now, but the one it was removed from still opens its stored text (D50).
            "removed_research_id": None if members else (removed["id"] if (removed := conn.execute(
                "SELECT r.id FROM corpus_memberships m JOIN researches r ON r.id = m.research_id"
                " WHERE m.source_version_id = ? AND m.removed_at IS NOT NULL AND r.trashed_at IS NULL"
                " ORDER BY m.removed_at DESC LIMIT 1", (svid,)).fetchone()) else None),
        })

    titles = {row["source_version_id"]: row["title"] for row in rows}
    representative = max(versions, key=_library_representative_score)
    return {
        "work_id": work_id, "source_key": store.source_key(work_id), "title": titles[representative["source_version_id"]],
        "authors": representative["authors"],
        "year": representative["year"], "venue": representative["venue"], "doi": representative["doi"],
        "landing_url": representative["landing_url"], "publication_type": representative["publication_type"],
        "cited_by_count": max((v["cited_by_count"] for v in versions if v["cited_by_count"] is not None), default=None),
        "is_retracted": store.work_retracted(work_id),
        "versions": versions,
        "researches": sorted(researches.values(), key=lambda r: r["updated_at"] or "", reverse=True),
    }


def _review_view(store: Store, answer_id: str) -> dict[str, Any] | None:
    review = store.answer_review(answer_id)
    if review is None:
        return None
    session = store.conn.execute(
        "SELECT connection, requested_model, resolved_model FROM model_sessions WHERE step_id = ? ORDER BY started_at DESC LIMIT 1",
        (review["step_id"],),
    ).fetchone() if review["step_id"] else None
    completed = review["status"] == "completed"
    if completed and review["step_input_id"]:
        # Handles the reviewer wrote into its reasons or notes reach the reader as source titles.
        review["review"] = name_sources_in_prose(store.step_input_payload(review["step_input_id"]), review["review"])
    return {"status": review["status"], "failure_reason": review["failure_reason"], "created_at": review["created_at"],
            "reviews": review["review"]["reviews"] if completed else [], "notes": review["review"]["notes"] if completed else "",
            "issues": (review["review"] or {}).get("issues", []) if not completed else [],
            "model": dict(session) if session else None}


def occurrence_view(store: Store, asset: dict, extraction: dict | None, *, extraction_version=None) -> dict:
    """Recorded parser input relative to the expected identity, never today's served bytes."""
    current = store.conn.execute("SELECT id FROM asset_extractions WHERE asset_id = ? AND outcome = 'current'",
                                 (asset["id"],)).fetchone()
    extraction_id = extraction["id"] if extraction else None
    result = {"extraction_id": extraction_id,
              "extraction_version": extraction["extraction_version"] if extraction else extraction_version,
              "extractor_profile": extraction.get("extractor_profile") if extraction else None,
              "outcome": extraction["outcome"] if extraction else None,
              "is_current": bool(extraction_id and current and extraction_id == current["id"]),
              "current_extraction_id": current["id"] if current else None,
              "input": None, "input_relation": "input_not_recorded",
              "file_restored_after": False, "latest_file_restore": None}
    observation_id = extraction.get("input_observation_id") if extraction else None
    observation = store.conn.execute(
        "SELECT id, integrity, observed_sha256 FROM asset_file_observations WHERE id = ?", (observation_id,),
    ).fetchone()
    if observation:
        result["input"] = {"observation_id": observation["id"], "integrity": observation["integrity"],
                           "observed_sha256": observation["observed_sha256"]}
        if observation["integrity"] == "verified" and observation["observed_sha256"] == asset["sha256"]:
            result["input_relation"] = "input_matched_expected_hash"
        elif observation["integrity"] == "mismatch":
            result["input_relation"] = "input_differed_from_expected_hash"
            result["retained_copy"] = store.conn.execute(
                "SELECT 1 FROM asset_file_observations WHERE kind = 'before_restore'"
                " AND observed_sha256 = ? AND retained_filename = ? LIMIT 1",
                (observation["observed_sha256"], "retained-" + observation["observed_sha256"] + ".bin"),
            ).fetchone() is not None
    repair = latest_completed_restore(store.conn, asset["sha256"])
    if repair:
        result["latest_file_restore"] = store.file_restore_view(repair["id"])
        result["file_restored_after"] = bool(extraction and repair["finished_at"] > extraction["created_at"])
    return result


def passage_view(store: Store, research_id: str, passage_id: str) -> dict[str, Any] | None:
    passage = store.passage(passage_id)
    if not store.was_member(research_id, passage["source_version_id"]):
        return None
    source = store.source(passage["source_version_id"])
    dependency = passage_dependencies(store.conn, [passage_id])[passage_id]
    extraction = store.conn.execute("SELECT * FROM asset_extractions WHERE id = ?",
                                    (dependency["passage_extraction_id"],)).fetchone()
    occurrence = (occurrence_view(store, store.asset(passage["asset_id"]), dict(extraction) if extraction else None,
                                  extraction_version=passage["extraction_version"]) if passage["asset_id"] else None)
    return {
        "id": passage["id"], "kind": passage["kind"], "text": passage["text"], "physical_page": passage["physical_page"],
        "printed_label": passage["printed_label"], "abstract_origin": passage["abstract_origin"],
        "extraction_version": passage["extraction_version"], "payload_ref": passage["payload_ref"], "text_source": passage["text_source"],
        "equations_to_check": equations_to_check(store, passage["asset_id"], passage["extraction_version"]).get(passage["physical_page"], 0)
        if passage["text_source"] == "marker" else 0,
        # The equation numbers in this chunk placed from the arXiv source (D104) or read by Mathpix (D40); the rest of the
        # chunk is the PDF's text.
        "source_equations": chunk_numbers(latex_numbers(store, passage["asset_id"], passage["extraction_version"]),
                                          passage["physical_page"], passage["payload_ref"])
        if passage["text_source"] in ("latex_source", "equation_ocr") else [],
        "reading_depth": "abstract" if passage["kind"] == "abstract" else "selected_sections",
        "asset_id": passage["asset_id"],
        "rendition": store.asset_rendition(passage["asset_id"]),
        "evidence_status": dependency["evidence_status"], "occurrence": occurrence,
        "removed_from_research": not store.is_active_member(research_id, passage["source_version_id"]),
        "source": {k: source[k] for k in ("id", "work_id", "title", "authors", "year", "venue", "doi", "landing_url", "version_label", "origin",
                                            "cited_by_count", "cited_by_count_at")}
        | {"source_key": store.source_key(source["work_id"]), "is_retracted": _retracted(source["is_retracted"]),
           "work_is_retracted": store.work_retracted(source["work_id"])},
    }
