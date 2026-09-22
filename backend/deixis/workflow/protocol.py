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
from deixis.domain.rules import (ABSTRACT_BATCH, ABSTRACT_QUOTE_MIN_CHARS, ABSTRACT_READ_LIMIT, ABSTRACT_RUNS,
                                 FULLTEXT_CRITERION_PASSAGES, FULLTEXT_PASSAGES_PER_CALL, FULLTEXT_QUOTE_MIN_CHARS,
                                 FULLTEXT_READ_LIMIT, FULLTEXT_RUNS, FULLTEXT_WORK_LIMIT, PROVIDER_WAIT,
                                 SCREENING_BATCH, SW_READ_LIMIT, effective_reviewer, step_model)
from deixis.domain.survey import THRESHOLDS as SURVEY_THRESHOLDS
from deixis.domain.survey_words import ABSTRACT_SELF_DESCRIPTIONS as SURVEY_PATTERNS
from deixis.providers import query_compiler
from deixis.providers.registry import CONNECTORS

PROTOCOL_SCHEMA = "deixis.protocol.v1"
# What the criterion body says about where it came from. It is kept out of `decisions.CRITERION_FIELDS` on purpose:
# the same criterion read back from an earlier protocol must not make the decisions taken under it stale (SW11.10).
CRITERION_ORIGIN_FIELDS = ("origin", "base_run", "runs_ok", "dropped_exclusion_title_words", "sought_term_in_criterion")


def _model(role: tuple[str, str | None, str | None] | None) -> dict[str, Any] | None:
    if role is None:
        return None
    connection, model, reasoning_effort = role
    return {"connection": connection, "model": model, "reasoning_effort": reasoning_effort}


def build_protocol(scope: dict[str, Any], budget: dict[str, Any], plan: dict[str, Any] | None,
                   queries: list[dict[str, Any]], skill_package_hash: str, settings: Settings,
                   vocabulary: dict[str, Any] | None = None,
                   expansion: dict[str, Any] | None = None,
                   criterion: dict[str, Any] | None = None,
                   approval: dict[str, Any] | None = None,
                   embedding_model: str | None = None) -> dict[str, Any]:
    """The body a research freezes. `vocabulary` is the sw workflow's code vocabulary step output (SW2).

    Its counts are the ones the first run read; they change in the literature over time and are never re-probed, so
    the body keeps the numbers that actually decided this research's query. `expansion` is the step output of the
    second arm (SW2.4) and is given only for the revision that opened it, so a body without one is what it was.
    `criterion` is what three proposals agreed on (SW15.2); without one the four criterion fields stay null, which
    is what a `legacy` body and a run whose model was unreachable both have. `embedding_model` is the semantic search
    model the research was configured with when it froze this body; the flow reads it, because this function sees no
    store; it says which signals were configured, never which of them really ran — that is in the ranking step's own
    output — so a research whose embedding failed keeps the body it froze. `approval` is how the vocabulary and the
    criterion below were agreed (slice 08a): who approved them, whether they were corrected and what the user was
    asked about. A body without one is a `legacy` body or one frozen before that step existed.
    """
    # Imported here: flow loads this module, and the thresholds are read from their one definition rather than repeated.
    from deixis.documents.pdf import CHUNK_CHARS
    from deixis.workflow.flow import (FORMULATION_SCORE_THRESHOLD, MAX_ABSTRACT_CHARS, MAX_PASSAGES_PER_SOURCE,
                                      PDF_PAGES_PER_SOURCE, RRF_K)
    from deixis.workflow.criterion import THRESHOLDS as CRITERION_THRESHOLDS
    from deixis.workflow.criterion_passages import THRESHOLDS as CRITERION_PASSAGE_THRESHOLDS
    from deixis.workflow.expansion import THRESHOLDS as EXPANSION_THRESHOLDS
    from deixis.workflow.lookups import THRESHOLDS as LOOKUP_THRESHOLDS, title_words
    from deixis.workflow.ranking import THRESHOLDS as RANKING_THRESHOLDS
    from deixis.workflow.approval import block_origins
    from deixis.workflow.vocabulary import GATE_BLOCKS, THRESHOLDS as VOCABULARY_THRESHOLDS

    queried = [t for t in vocabulary["terms"] if not t["dropped"]] if vocabulary else []
    # The words this research reads a title for a survey with, and the ones its own question took away (SW5.1).
    kept_words, dropped_words = title_words(vocabulary) if vocabulary else ((), ())
    # Who put each phrase in its block: the code rule, the model's labelling step (SW17.6), the user's key terms or
    # the user's own correction at the approval step (SW2.6).
    default_origin = "user" if vocabulary and vocabulary["block_assignment"] == "user" else "rule"
    block_origin = block_origins(vocabulary) if vocabulary else {}

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
        # What a record must contain to be included, and the words an author of such a paper writes (SW15). Null
        # here means the criterion was not built — no sw workflow, or fewer than two valid proposals.
        "inclusion_criterion": criterion["criterion"] if criterion else None,
        "criterion_parts": criterion["parts"] if criterion else None,
        "cue_phrases": criterion["cue_phrases"] if criterion else None,
        "exclusion_title_words": criterion["exclusion_title_words"] if criterion else None,
        **({"criterion_origin": {name: criterion[name] for name in CRITERION_ORIGIN_FIELDS}} if criterion else {}),
        # How this vocabulary and criterion were agreed before the freeze (SW2.6, SW15.3).
        **({"approval": approval} if approval else {}),
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
        # The second arm's own record: every candidate phrase with its two counts and why it was kept or refused.
        **({"expansion": {"skipped": expansion["skipped"], "candidates": expansion["candidates"],
                          "terms": list(expansion["terms"])}} if expansion else {}),
        "compiled_queries": [{"provider_id": q["provider_id"], "query_text": q["query_text"],
                              **({"results": q["results"]} if q.get("results") is not None else {})}
                             for q in queries],
        # The databases searched, which is what the record reports (PRISMA-S item 1); a connector kept in scope only
        # to verify a known DOI is named apart so that it is not read as a searched source (D87). A `legacy` body
        # keeps the list it always had, digest and all.
        **({"providers": sorted(p for p in scope["providers"] if CONNECTORS[p].searchable),
            "verification_providers": sorted(p for p in scope["providers"] if not CONNECTORS[p].searchable)}
           if scope.get("search_workflow") == "sw" else {"providers": sorted(scope["providers"])}),
        "arms": ["keyword_search", "data_expansion"] if expansion else ["keyword_search"],
        # How this research decides a record describes itself as a survey. A `legacy` body carries none of it.
        **({"survey": {"title_words": list(kept_words), "dropped_title_words": list(dropped_words),
                       "abstract_patterns": list(SURVEY_PATTERNS)}}
           if scope.get("search_workflow") == "sw" else {}),
        # How this research was configured to order its inspection list (SW7, SW8). A `legacy` body has no signal.
        "signals": ([{"signal": "bm25"}, {"signal": "blocks"},
                     {"signal": "tfidf", "seeds": "verified"},
                     {"signal": "graph", "seeds": "verified_then_code"},
                     {"signal": "embedding", "model": embedding_model, "rescue": True}]
                    if scope.get("search_workflow") == "sw" else []),
        "thresholds": {
            "screening_batch": SCREENING_BATCH,
            "max_abstract_chars": MAX_ABSTRACT_CHARS,
            "rrf_k": RRF_K,
            "chunk_chars": CHUNK_CHARS,
            "max_passages_per_source": MAX_PASSAGES_PER_SOURCE,
            "pdf_pages_per_source": PDF_PAGES_PER_SOURCE,
            # The hand-written formulation quota is a legacy body's alone: an sw answer fills that room from the
            # criterion's approved cue phrases instead (D84), so a threshold it no longer applies is not recorded.
            **({"formulation_score_threshold": FORMULATION_SCORE_THRESHOLD}
               if scope.get("search_workflow") != "sw" else {}),
            # The identity rule and the page read limit run only on the sw workflow, so a legacy protocol body stays
            # exactly as it was.
            **({"record_identity": THRESHOLDS,
                # How much of the answer input the criterion order may fill, and how it is split per source (D84).
                "criterion_passages": CRITERION_PASSAGE_THRESHOLDS,
                "survey": SURVEY_THRESHOLDS, "lookup": LOOKUP_THRESHOLDS, "criterion": CRITERION_THRESHOLDS,
                "ranking": RANKING_THRESHOLDS,
                # How deep the abstract stage reads and what it counts as a verbatim quote (D81). `read_limit` is
                # this research's own effort: it says how many works the model was asked about, not how many exist.
                "abstract_screening": {"read_limit": ABSTRACT_READ_LIMIT[scope["effort"]], "batch": ABSTRACT_BATCH,
                                       "runs": ABSTRACT_RUNS, "quote_min_chars": ABSTRACT_QUOTE_MIN_CHARS},
                # How many records one query reads and how many 429s the read waits out, both this research's
                # own effort (D88). No effort stops a run at a time: the minute targets are measured, not enforced.
                "search_read": {"read_limit_per_query": SW_READ_LIMIT[scope["effort"]],
                                "rate_limit_retries": PROVIDER_WAIT[scope["effort"]]},
                # How many works one full-text retrieval run fetches (D83). This research's own effort, so it says
                # how many works were tried, not how many have a full text.
                "fulltext_fetch": {"work_limit": FULLTEXT_WORK_LIMIT[scope["effort"]]},
                # How many works one reading run sends to the model, and what one call is shown (D85).
                "fulltext_adjudication": {"read_limit": FULLTEXT_READ_LIMIT[scope["effort"]], "runs": FULLTEXT_RUNS,
                                          "passages_per_call": FULLTEXT_PASSAGES_PER_CALL,
                                          "criterion_passages": FULLTEXT_CRITERION_PASSAGES,
                                          "quote_min_chars": FULLTEXT_QUOTE_MIN_CHARS}}
               if scope.get("search_workflow") == "sw" else {}),
            **({"vocabulary": VOCABULARY_THRESHOLDS} if vocabulary else {}),
            **({"expansion": EXPANSION_THRESHOLDS} if expansion else {}),
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
