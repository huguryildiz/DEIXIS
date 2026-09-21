"""Why a record was kept, dropped or left open at each screening stage (SW9, SW11).

A stage decision carries a code from this table, not free text: the code fixes the stage it belongs to, the outcome it
stands for, who is allowed to decide it and what the workflow does next. Codes live here and not in the database, so a
new code is a code change that is read in review. A later slice adds codes with the step that writes them; it never
changes what an existing code means, because decisions already stored carry it.
"""

from __future__ import annotations

from dataclasses import dataclass

STAGES = ("abstract", "fulltext")
OUTCOMES = {"abstract": ("candidate", "out_of_scope", "unresolved"),
            "fulltext": ("include", "criterion_not_met", "unresolved")}
DECIDERS = ("code", "model_agreement", "human")
NEXT_STEPS = ("none", "abstract_lookup", "abstract_model", "fulltext_fetch", "reading_queue", "fulltext_model",
              "human_queue", "waiting_for_pdf", "seed_pool", "answer")


@dataclass(frozen=True)
class ReasonCode:
    code: str
    stage: str
    outcome: str
    decided_by: str
    next_step: str


def _table(*codes: ReasonCode) -> dict[str, ReasonCode]:
    for entry in codes:
        if entry.stage not in STAGES or entry.outcome not in OUTCOMES[entry.stage]:
            raise ValueError(f"{entry.code}: {entry.outcome} is not an outcome of the {entry.stage} stage")
        if entry.decided_by not in DECIDERS or entry.next_step not in NEXT_STEPS:
            raise ValueError(f"{entry.code}: unknown decider or next step")
    return {entry.code: entry for entry in codes}


REASON_CODES: dict[str, ReasonCode] = _table(
    # ---- abstract stage ----------------------------------------------------------------
    ReasonCode("blocks_in_title", "abstract", "candidate", "code", "fulltext_fetch"),
    ReasonCode("both_blocks_missing", "abstract", "out_of_scope", "code", "none"),
    ReasonCode("no_abstract", "abstract", "unresolved", "code", "abstract_lookup"),
    ReasonCode("runs_agree_candidate", "abstract", "candidate", "model_agreement", "fulltext_fetch"),
    ReasonCode("runs_agree_out_of_scope", "abstract", "out_of_scope", "model_agreement", "none"),
    # Two runs that disagree, or a quote that is not in the abstract, keep the record rather than drop it (SW11.4).
    ReasonCode("runs_disagree_kept_as_candidate", "abstract", "candidate", "code", "fulltext_fetch"),
    ReasonCode("quote_not_found_kept_as_candidate", "abstract", "candidate", "code", "fulltext_fetch"),
    ReasonCode("abstract_not_proposed", "abstract", "unresolved", "code", "abstract_model"),
    # A strong title word routes the record out of screening and into the seed pool; it is not "out of scope"
    # (SW5.4, SW9.3). The record is never deleted and the user may still include it.
    ReasonCode("survey_title_word", "abstract", "unresolved", "code", "seed_pool"),
    # Both second sources answered without an abstract, or the record has no DOI to ask by; only a full text can
    # decide it. A record without an abstract is never out of scope, by any route (SW5.5).
    ReasonCode("abstract_not_found", "abstract", "unresolved", "code", "fulltext_fetch"),
    # ---- full-text stage ---------------------------------------------------------------
    ReasonCode("all_parts_verified", "fulltext", "include", "model_agreement", "answer"),
    ReasonCode("criterion_absent", "fulltext", "criterion_not_met", "model_agreement", "none"),
    ReasonCode("no_fulltext", "fulltext", "unresolved", "code", "waiting_for_pdf"),
    ReasonCode("text_unreadable", "fulltext", "unresolved", "code", "waiting_for_pdf"),
    ReasonCode("not_read_yet", "fulltext", "unresolved", "code", "reading_queue"),
    ReasonCode("fulltext_runs_disagree", "fulltext", "unresolved", "code", "human_queue"),
    ReasonCode("include_quote_unverified", "fulltext", "unresolved", "code", "human_queue"),
    ReasonCode("part_without_evidence", "fulltext", "unresolved", "code", "human_queue"),
    ReasonCode("abstract_promise_absent", "fulltext", "unresolved", "code", "human_queue"),
    # ---- what the user decided (SW11.7, SW11.11) ---------------------------------------
    ReasonCode("human_include", "fulltext", "include", "human", "answer"),
    ReasonCode("human_criterion_not_met", "fulltext", "criterion_not_met", "human", "none"),
    ReasonCode("human_not_sure", "fulltext", "unresolved", "human", "none"),
    ReasonCode("human_pdf_wrong", "fulltext", "unresolved", "human", "waiting_for_pdf"),
)


def reason(code: str) -> ReasonCode:
    try:
        return REASON_CODES[code]
    except KeyError:
        raise KeyError(f"unknown reason code: {code}") from None
