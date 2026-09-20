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
from deixis.domain.rules import SCREENING_BATCH, SW_READ_LIMIT, effective_reviewer, step_model
from deixis.providers import query_compiler

PROTOCOL_SCHEMA = "deixis.protocol.v1"


def _model(role: tuple[str, str | None, str | None] | None) -> dict[str, Any] | None:
    if role is None:
        return None
    connection, model, reasoning_effort = role
    return {"connection": connection, "model": model, "reasoning_effort": reasoning_effort}


def build_protocol(scope: dict[str, Any], budget: dict[str, Any], plan: dict[str, Any] | None,
                   queries: list[dict[str, Any]], skill_package_hash: str, settings: Settings,
                   vocabulary: dict[str, Any] | None = None) -> dict[str, Any]:
    """The body a research freezes. `vocabulary` is the sw workflow's code vocabulary step output (SW2).

    Its counts are the ones the first run read; they change in the literature over time and are never re-probed, so
    the body keeps the numbers that actually decided this research's query.
    """
    # Imported here: flow loads this module, and the thresholds are read from their one definition rather than repeated.
    from deixis.documents.pdf import CHUNK_CHARS
    from deixis.workflow.flow import (FORMULATION_SCORE_THRESHOLD, MAX_ABSTRACT_CHARS, MAX_PASSAGES_PER_SOURCE,
                                      PDF_PAGES_PER_SOURCE, RRF_K)
    from deixis.workflow.vocabulary import GATE_BLOCKS, THRESHOLDS as VOCABULARY_THRESHOLDS

    queried = [t for t in vocabulary["terms"] if not t["dropped"]] if vocabulary else []
    # Who put each phrase in its block: the code rule, the model's labelling step (SW17.6) or the user's key terms.
    default_origin = "user" if vocabulary and vocabulary["block_assignment"] == "user" else "rule"
    block_origin = {record["phrase"]: record["origin"]
                    for record in (vocabulary or {}).get("labelling", {}).get("phrases", [])}

    # A code vocabulary's queries came from the block compiler, so the body names that compiler, not the plan one.
    compiler_version = (query_compiler.BLOCKS_VERSION if vocabulary else
                        query_compiler.COMPACT_VERSION if settings.query_strategy == "compact_openalex_v1"
                        else query_compiler.VERSION)
    return {
        "schema": PROTOCOL_SCHEMA,
        "search_workflow": scope.get("search_workflow", "legacy"),
        "question": scope["question"],
        "steering": scope.get("steering"),
        "language_hint": scope.get("language_hint"),
        "source_scope": scope["source_scope"],
        "seed_mode": scope.get("seed_mode", "question_only"),
        # The inclusion criterion and its phrases arrive in slice 06.
        "inclusion_criterion": None,
        "criterion_parts": None,
        "cue_phrases": None,
        "exclusion_title_words": None,
        # The blocks a code vocabulary gated the search with, each holding the form of its terms that was queried.
        "concept_blocks": ({block: [t["root"] if t["in_query"] == "root" else t["phrase"]
                                    for t in queried if t["block"] == block] for block in GATE_BLOCKS}
                           if vocabulary else None),
        "block_assignment": vocabulary["block_assignment"] if vocabulary else None,
        "claim_words": list(vocabulary["claim_words"]) if vocabulary else None,
        "exclusion_words": list(vocabulary["exclusion_words"]) if vocabulary else None,
        "vocabulary": ([{"label": c["label"], "role": c["role"], "synonyms": list(c.get("synonyms") or [])}
                        for c in plan.get("concepts", [])] if plan else
                       [{"phrase": t["phrase"], "origin": t["origin"], "block": t["block"],
                         "block_origin": block_origin.get(t["phrase"], default_origin), "root": t["root"],
                         "in_query": t["in_query"], "phrase_count": t["phrase_count"], "root_count": t["root_count"],
                         "and_only": t["and_only"], "dropped": t["dropped"]} for t in vocabulary["terms"]]
                       if vocabulary else None),
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
            # The identity rule and the page read limit run only on the sw workflow, so a legacy protocol body stays
            # exactly as it was.
            **({"record_identity": THRESHOLDS,
                "search_read": {"read_limit_per_query": SW_READ_LIMIT}} if scope.get("search_workflow") == "sw" else {}),
            **({"vocabulary": VOCABULARY_THRESHOLDS} if vocabulary else {}),
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
