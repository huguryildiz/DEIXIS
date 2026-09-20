"""The protocol body a research freezes before its first provider request (SW14.1).

`build_protocol` is pure: no clock, no randomness, no network, so the same research state gives the same body and the
same digest on a resumed run. Fields the product does not decide yet are written as null and filled by later slices;
a null here means "not decided in this version", not "empty".
"""

from __future__ import annotations

from importlib.metadata import version
from typing import Any

from deixis.config import Settings
from deixis.domain.record_identity import THRESHOLDS
from deixis.domain.rules import SCREENING_BATCH, effective_reviewer, step_model
from deixis.providers import query_compiler

PROTOCOL_SCHEMA = "deixis.protocol.v1"


def _model(role: tuple[str, str | None, str | None] | None) -> dict[str, Any] | None:
    if role is None:
        return None
    connection, model, reasoning_effort = role
    return {"connection": connection, "model": model, "reasoning_effort": reasoning_effort}


def build_protocol(scope: dict[str, Any], budget: dict[str, Any], plan: dict[str, Any] | None,
                   queries: list[dict[str, Any]], skill_package_hash: str, settings: Settings) -> dict[str, Any]:
    # Imported here: flow loads this module, and the thresholds are read from their one definition rather than repeated.
    from deixis.documents.pdf import CHUNK_CHARS
    from deixis.workflow.flow import (FORMULATION_SCORE_THRESHOLD, MAX_ABSTRACT_CHARS, MAX_PASSAGES_PER_SOURCE,
                                      PDF_PAGES_PER_SOURCE, RRF_K)

    compiler_version = (query_compiler.COMPACT_VERSION if settings.query_strategy == "compact_openalex_v1"
                        else query_compiler.VERSION)
    return {
        "schema": PROTOCOL_SCHEMA,
        "search_workflow": scope.get("search_workflow", "legacy"),
        "question": scope["question"],
        "steering": scope.get("steering"),
        "language_hint": scope.get("language_hint"),
        "source_scope": scope["source_scope"],
        "seed_mode": scope.get("seed_mode", "question_only"),
        # The inclusion criterion and its phrases arrive in slice 06, the concept blocks in slice 04.
        "inclusion_criterion": None,
        "criterion_parts": None,
        "cue_phrases": None,
        "exclusion_title_words": None,
        "concept_blocks": None,
        "claim_words": None,
        "exclusion_words": None,
        "vocabulary": ([{"label": c["label"], "role": c["role"], "synonyms": list(c.get("synonyms") or [])}
                        for c in plan.get("concepts", [])] if plan else None),
        "compiled_queries": [{"provider_id": q["provider_id"], "query_text": q["query_text"],
                              **({"results": q["results"]} if q.get("results") is not None else {})}
                             for q in queries],
        "providers": sorted(scope["providers"]),
        "arms": ["keyword_search"],
        "signals": [],  # record-level ranking signals arrive in slice 07
        "thresholds": {
            "screening_batch": SCREENING_BATCH,
            "max_abstract_chars": MAX_ABSTRACT_CHARS,
            "rrf_k": RRF_K,
            "chunk_chars": CHUNK_CHARS,
            "max_passages_per_source": MAX_PASSAGES_PER_SOURCE,
            "pdf_pages_per_source": PDF_PAGES_PER_SOURCE,
            "formulation_score_threshold": FORMULATION_SCORE_THRESHOLD,
            # The identity rule runs only on the sw workflow, so a legacy protocol body stays exactly as it was.
            **({"record_identity": THRESHOLDS} if scope.get("search_workflow") == "sw" else {}),
        },
        "rule_table_version": "legacy",
        "budget": budget,
        # The reviewer that follows the app-wide default setting is not resolved here: the body is built without a store.
        "models": {"research": _model(step_model(scope, "grounded_answer")),
                   "literature": _model(step_model(scope, "search_plan")),
                   "review": _model(effective_reviewer(scope, None))},
        "skill_package_hash": skill_package_hash,
        "code_version": f"deixis/{version('deixis')} {compiler_version}",
        "query_strategy": settings.query_strategy,
    }
