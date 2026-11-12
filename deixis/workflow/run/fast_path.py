"""Frozen policy, durable active wall time and stage-specific soft deadlines."""

from __future__ import annotations

import asyncio
import json
from datetime import datetime, timedelta, timezone
from typing import Any, NamedTuple, Protocol

from deixis.domain import canonical
from deixis.domain.rules import ROUTE_SHARE, SOURCE_ROUTES_VERSION
from deixis.storage.db import new_id, transaction

POLICY = "fast_path_v1"
RUNNER_VERSION = 2
STAGES = ("plan", "search", "ranking", "read", "answer")
# The stages that must be done before the answer is written. Their bases sum to the depth's handover moment.
PRE_ANSWER = STAGES[:4]
# The stages after ranking, which the reranker's own allowance must not shorten.
AFTER_RANKING = STAGES[STAGES.index("ranking") + 1:]
# The plan rule every run freezes: one model call reads the first semantic page and writes the terms, their blocks
# and the chain's starting works. A run whose budget names no plan rule was frozen under a search method this
# version no longer carries, and `small_batch.removed_rule` stops it rather than running it under a rule that is
# gone. A query is only reused from a run that froze this same rule (`store.search_query_of`).
PLAN_RULE = "search_plan_v1"
# The chain admission rule a run freezes: words are matched against the protocol's frozen forms, and a few linked
# records those words do not reach are still written as ranked candidates under the rescue quota. Older budgets
# name `fast_chain_v1` or `fast_chain_v2`; their code is gone and `small_batch.removed_rule` stops those runs.
CHAIN_RULE = "fast_chain_v3"
CHAIN_RULES = (CHAIN_RULE,)
# The plan rules this version carries out, as `CHAIN_RULES` does for the chain.
PLAN_RULES = (PLAN_RULE,)
# The deeper screening: a Standard or Detailed discovery queued with the option on also screens the next
# `DEEP_SCREENING_WORKS` works of the frozen list, places N+1..N+100, one model read per batch. Frozen in the policy under
# its rule's name; a policy without the key screens 1..N only, as before.
DEEP_SCREENING_RULE = "m3_v1"
# Which of a record's found copies is downloaded first (`acquisition.candidate_order`): a fixed provider priority,
# then the version and the identity, then the URL — never the order the providers happened to answer in. Frozen in
# the policy, so the choice an older run made can be read back as the rule it was made under.
ACQUIRE_RULE = "fast_acquire_v1"
# How many works one research may ask the person for a file for (`report_file_asks`): the depth's own allowance,
# frozen in the policy so a later depth change cannot hand spent asks back. A run queued before the rule carries
# neither key and asks for nothing: the list is opened only by a run whose policy names the rule.
FILE_ASK_RULE = "file_ask_v1"
# How many works one research may send an open-web full-text search for (`workflow.read.fulltext_search`): a metered
# search, so the depth's own allowance, frozen in the policy and reserved before each request goes out. A run queued
# before the rule carries neither key and sends none.
FULLTEXT_SEARCH_RULE = "fulltext_search_v1"
# Which sources beside OpenAlex a depth searches, and by what field share they are chosen: the routing step already
# reads the field distribution of the question's gate query, and this rule says how many of the sources it chose a
# depth pays for and how many records each may read. Frozen in the policy with the share and the table's own
# version, so a run decides by the numbers it started with. A run queued before the rule carries none and searches
# OpenAlex alone, as every run did.
FIELD_SEARCH_RULE = "field_search_v1"
# The delivery-time rule: each depth has an end-to-end target for the first sourced answer and a moment by which
# the run must hand over to answer writing, whatever it has read. Both count on the person's own clock, from the
# question's submission, so the queue and any pause are inside them. Frozen in the policy under this name; a run
# queued before the rule carries no handover and keeps its stage deadlines alone.
HANDOVER_RULE = "answer_handover_v1"
# Completing OpenAlex with Semantic Scholar: three observable states, three actions. The abstract lookup of a work
# whose DOI is known runs as it always has; the other two are this arm. `conditional` sends a request only when the
# state the design names is observed — OpenAlex could not complete for a technical reason, or a part of the question
# the plan named is not met in what the main query found. `always` sends the snippet query on every question and is a
# measurement arm only. `off` freezes nothing, so a run of that arm carries the policy frozen before the rule, hash
# included.
COMPLETION_RULE = "s2_completion_v1"
COMPLETION_ARMS = ("off", "conditional", "always")
# The second independent index a depth may pay for (`registry.broad_index`). `conditional` searches it only
# where the run's plan names no independent field source of its own, `always` on every run of a depth that
# pays for one, `off` never. The arm is frozen into the run's budget, so a run sends what it was queued with.
BROAD_INDEX_RULE = "broad_index_v1"
BROAD_INDEX_ARMS = ("off", "conditional", "always")
# The one sub-topic search a depth that pays for no second index of its own may send instead: after its field
# source has been searched, a part of the question the plan named that the records found so far still do not
# carry is asked of the broad index on its own. `conditional` sends only where that gap is still open, `always`
# on every question of the depth that named such a part, `off` never.
SUBTOPIC_RULE = "subtopic_search_v1"
SUBTOPIC_ARMS = ("off", "conditional", "always")
# The years a run searches in, where the question states them or a measurement supplies them
# (`search.date_scope`). Frozen here with the rest of the policy, before the first request opens: the question's
# own semantic request goes out before the protocol is frozen, so a bound kept only in the protocol would miss it.
DATE_SCOPE_RULE = "date_scope_v1"
# The reranker's own time: once the pool is ranked, the reranker may run for the depth's allowance even when the
# ranking stage's time, or the depth's handover moment, is already gone. The time it runs past that cutoff is not
# taken from the read stage: read keeps the allocation and the handover cap it would have had, so the answer comes
# later by that time. Frozen in the policy with the number; a run queued before the rule carries none and keeps the
# old arithmetic, in which the reranker had only what was left of the ranking stage.
RERANK_ALLOWANCE_RULE = "rerank_allowance_v1"
# Short semantic searches beside the plan: one model step writes the depth's number of short phrases from the question
# alone, and each phrase is one OpenAlex semantic request of its own. Frozen in the policy with the number and the
# records each request reads; a run queued before the rule names no key and sends none (`phrase_search`).
PHRASE_SEARCH_RULE = "phrase_search_v1"
PHRASE_SEARCH_RECORDS = 50  # records one phrase request reads: one semantic page
# Where the reranker was applied to the frozen list, the abstract stage does not close a work of the top-N window for
# naming neither gate block: the model reads it. A run frozen before the rule names no key and closes as it did.
WINDOW_WORD_RULE = "reranked_window_open_v1"
# The evidence a run must gather before it answers, whatever its handover moment says: the search stage keeps at least
# `search_ms` from its own start, and the model's reads of the top N abstracts are waited for up to `abstract_ceiling_ms`
# from the moment those reads can start. Under the rule no stage carries an earlier stage's overrun as debt, and the
# handover cuts no stage: it and the end-to-end target stay recorded targets, and every stage keeps its own finite
# deadline. A run frozen before the rule names no key and runs as it did.
EVIDENCE_MINIMUM_RULE = "evidence_minimum_v1"
EVIDENCE_SEARCH_MS = 10_000  # twelve measured keyword pages took 1.1-1.8 s each; a starting value, not a guarantee
EVIDENCE_ABSTRACT_CEILING_MS = 60_000  # a ceiling that ends a hung call, not a measured sufficient time
# A run in one of these states will send nothing more, so whether it met its target is settled.
TERMINAL = ("completed", "failed", "cancelled")
DEEP_SCREENING_WORKS = 100
DEEP_SCREENING_EFFORTS = ("standard", "detailed")


class Mode(NamedTuple):
    """One research depth's numbers, frozen into a run's budget by `freeze_budget`."""
    stage_seconds: tuple[int, int, int, int, int]  # soft deadline of each of STAGES, in order
    read_top: int  # N: the top of the ranking a run reads
    fulltext_works: int  # K: the most works a run reads in full text
    keyword_record_cap: int
    chain_seeds: int  # the works citation chaining starts from: none in Quick, one in Standard, three in Deep
    backward_requests: int
    forward_requests: int
    boolean_plans: int  # the most distinct Boolean query plans a run of this depth sends: one main, the rest focused
    chain_rescue: int  # the most linked records the gate's words do not reach that are still written as candidates
    rerank_pool: float  # the most records the reranker reads, as a multiple of N; a saved factor is kept under it
    rerank_point: str  # "before_list": the list waits for the reranker; "after_list": it is frozen first (old Quick)
    file_asks: int  # the most works this depth asks the person for a file for, over the research's whole life
    fulltext_searches: int  # the most works this depth sends an open-web full-text search for, over the same life
    completion_records: int  # records the completion arm may read, taken off the keyword cap while the arm is frozen
    snippet_requests: int  # snippet queries this depth may send; Quick names no focused concept, so none
    field_sources: int  # field sources this depth searches beside OpenAlex: none in Quick, one in Standard and Deep
    field_records: int  # records each of them may read, taken off the same keyword cap
    broad_index_records: int  # records the second independent index may read; none at the depths that pay for none
    subtopic_records: int  # records the one sub-topic search may read; none where a depth searches that index anyway
    rerank_allowance: int  # seconds the reranker keeps of its own past the ranking cutoff; 0 freezes no allowance
    phrase_searches: int  # short semantic phrase searches beside the plan; 0 turns the route off


# The stage seconds are the delivery-time targets split across the stages: the four pre-answer stages sum to the
# depth's handover moment (35 s / 1 min 10 s / 3 min 30 s) and all five to its end-to-end target (1 / 2 / 5 minutes).
# The split inside the handover is today's pilot configuration, each stage scaled from the budget it had before the
# targets were applied; which split and which K/N actually hold the targets is measured, not assumed.
MODES = {
    # Quick opens no citation request of its own: the reference ids the first semantic page brings are stored and
    # the links inside that page are written, which costs nothing, but no seed work is read.
    "quick": Mode((7, 7, 7, 14, 25), read_top=25, fulltext_works=10, keyword_record_cap=450, chain_seeds=0,
                  backward_requests=0, forward_requests=0, boolean_plans=1, chain_rescue=0,
                  # Quick's list waits for the reranker, as Standard's does, and the reranker reads the same 400
                  # records Standard's reads (16 x 25): the right paper has to reach Quick's top 25 to be screened.
                  # Quick asks for no file at all: it is the depth that answers from what it can reach itself.
                  # Quick sends no snippet query: it writes no focused concept, so there is no recorded gap to ask
                  # about, and its first list waits for no extra search. The records are for the fallback alone,
                  # which is the only thing that stands between a technical OpenAlex failure and an empty Quick run.
                  rerank_pool=16.0, rerank_point="before_list", file_asks=0, fulltext_searches=0,
                  completion_records=50, snippet_requests=0,
                  # Quick binds its first list to no other source: it searches OpenAlex alone.
                  field_sources=0, field_records=0, broad_index_records=0, subtopic_records=0,
                  # Standard's allowance for the same 400-record window: not measured at Quick.
                  rerank_allowance=3,
                  # Six phrases at every depth to begin with: the number of the ten-question loss trace, not measured
                  # against any other.
                  phrase_searches=6),
    "standard": Mode((8, 12, 17, 33, 50), read_top=50, fulltext_works=20, keyword_record_cap=1000, chain_seeds=1,
                     backward_requests=4, forward_requests=8, boolean_plans=2, chain_rescue=5,
                     rerank_pool=8.0, rerank_point="before_list", file_asks=3, fulltext_searches=3,
                     completion_records=100, snippet_requests=1,
                     # The one field source the question's own field distribution points at. The records are a pilot
                     # setting: nothing has measured what a field source adds for what it takes off OpenAlex.
                     field_sources=1, field_records=250,
                     # Standard pays for no second index of its own; what it pays for is the one sub-topic search
                     # of that index, and only where its field source left the sub-topic unmet.
                     broad_index_records=0, subtopic_records=25,
                     # The 95th percentile of seven successful Voyage rerank-3-lite steps over a 400-record window
                     # (1.6 to 2.3 s), rounded up to a whole second. Steps that timed out are not in the sample, so
                     # this is a starting value, not a guarantee.
                     rerank_allowance=3, phrase_searches=6),
    "detailed": Mode((18, 36, 48, 108, 90), read_top=100, fulltext_works=40, keyword_record_cap=2000, chain_seeds=3,
                     backward_requests=8, forward_requests=16, boolean_plans=3, chain_rescue=10,
                     # 8 x 100 is past the reranker's own 400-record limit, so Deep reads the widest window there is.
                     rerank_pool=8.0, rerank_point="before_list", file_asks=5, fulltext_searches=5,
                     completion_records=200, snippet_requests=2,
                     # Deep searches the same one field source and pays for a second independent index beside it,
                     # whose records come off the same keyword cap. The number is a pilot setting: what that index
                     # adds to the first list is not measured.
                     # Deep searches that index on its own, so it sends no sub-topic search of it: one query per
                     # source stands.
                     field_sources=1, field_records=250, broad_index_records=100, subtopic_records=0,
                     # No Deep reranker step has been measured; its window is the same 400 records as Standard's,
                     # so it takes Standard's number until one is.
                     rerank_allowance=3, phrase_searches=6),
}


class LedgerMismatch(RuntimeError):
    """The stored fast-path ledger or stage intervals contradict the run being written."""


class Clock(Protocol):
    def now(self) -> datetime: ...

    async def sleep(self, seconds: float) -> None: ...


class SystemClock:
    def now(self) -> datetime:
        return datetime.now(timezone.utc)

    async def sleep(self, seconds: float) -> None:
        await asyncio.sleep(seconds)


def timestamp(clock: Clock) -> str:
    return clock.now().isoformat(timespec="milliseconds")


def elapsed(start: str, end: str) -> int:
    delta = datetime.fromisoformat(end) - datetime.fromisoformat(start)
    return max(0, delta // timedelta(milliseconds=1))


def freeze_budget(budget: dict[str, Any], effort: str, local_model: bool = False,
                  deep_screening: bool = False,
                  lexical_exclusion: bool = True, candidate_embedding: bool = True,
                  completion_arm: str = "off", broad_index_arm: str = "off",
                  subtopic_arm: str = "off", date_scope: dict[str, Any] | None = None) -> dict[str, Any]:
    """A run on a model this computer runs (`local_model`) keeps no deadline on the stages where the model works,
    read and answer: a local model screens and answers far slower than the stage bases assume, and a cut read
    leaves the answer unscreened evidence. Search and ranking do not wait on the model and keep theirs; each model
    call still has its own limit (openai_compat.LOCAL_TURN_TIMEOUT).

    `deep_screening` adds the deeper screening's window under `deep_screening`; off adds nothing, so a policy
    frozen without it is byte for byte the one frozen before, hash included. Quick takes no window.

    `candidate_embedding` off records that this run embeds no candidate, so the ranking's embedding signal is left
    out and says why; the reranker reads titles and abstracts as text and needs no embedding. On adds nothing.

    `lexical_exclusion` off records that the abstract stage may not close a record for naming neither gate block
    (`flow._abstract_code_stage`); on adds nothing and leaves the policy as it was. The arm is frozen here, so a
    resumed run screens the way it was queued and the two arms of the measurement stay apart.

    `completion_arm` is which Semantic Scholar completion arm this run may send (`COMPLETION_ARMS`), and it is the
    default here so that a policy frozen without it is byte for byte the one frozen before the rule, hash included:
    the absence of the key **is** the `off` arm, and `completion()` reads it that way. The other two arms name
    themselves, the records the arm may read and how many snippet queries the depth may send.

    `broad_index_arm` is the same shape for the second independent index (`BROAD_INDEX_ARMS`): `off` writes no
    key, which is the policy frozen before the rule, and the other two name the arm and the records.
    `subtopic_arm` is the same shape again for the one sub-topic search of that index (`SUBTOPIC_ARMS`).

    `date_scope` is the years this run searches in, built by `search.date_scope` from the person's own question or
    supplied with the run by a measurement. A run that bounds no years names no key, which is byte for byte the
    policy frozen before the rule."""
    if completion_arm not in COMPLETION_ARMS:
        raise ValueError(f"unknown completion arm {completion_arm!r}")
    if broad_index_arm not in BROAD_INDEX_ARMS:
        raise ValueError(f"unknown broad index arm {broad_index_arm!r}")
    if subtopic_arm not in SUBTOPIC_ARMS:
        raise ValueError(f"unknown sub-topic search arm {subtopic_arm!r}")
    mode = MODES[effort]
    bases = mode.stage_seconds
    policy = {
        "policy": POLICY, "runner_version": RUNNER_VERSION, "enforcement": ["search", "ranking", "read", "answer"],
        "enforced_stages": ["search", "ranking", "read", "answer"], "background_fetch_slots": 4,
        "approval_mode": "unattended", "auto_answer": True,
        "late_revision": {"mode": "auto", "max_revisions": 1},
        "mode": "deep" if effort == "detailed" else effort,
        "stage_base_ms": dict(zip(STAGES, (s * 1000 for s in bases))), "total_ms": sum(bases) * 1000,
        # The delivery-time target and the handover moment, both on the person's clock from the question's submission.
        "handover_rule": HANDOVER_RULE, "handover_ms": sum(bases[:len(PRE_ANSWER)]) * 1000,
        "N": mode.read_top, "K": mode.fulltext_works, "keyword_record_cap": mode.keyword_record_cap, "semantic_top": 50,
        "chain_seeds": mode.chain_seeds, "backward_requests": mode.backward_requests, "backward_page_size": 50,
        "forward_requests": mode.forward_requests, "forward_page_size": 25,
        # The chain matches the protocol's frozen word forms and keeps the rescue quota: `chain_rescue` linked
        # records the gate's words do not reach are written as ranked candidates, and the gate's own verdict on
        # them is still recorded.
        "chain_in_flight": 5, "chain_rule": CHAIN_RULE, "chain_rescue": mode.chain_rescue,
        "acquire_rule": ACQUIRE_RULE,
        # The model writes the plan from the first semantic page and the chain starts from the works it names.
        # `boolean_plans` counts the distinct Boolean query plans the run may send, the main one included; one plan
        # still goes to every enabled provider in that provider's syntax, and those requests are counted elsewhere.
        "plan_rule": PLAN_RULE, "boolean_plans": mode.boolean_plans,
        "file_ask_rule": FILE_ASK_RULE, "file_asks": mode.file_asks,
        # Which other sources this depth searches, and by what share of the question's field distribution they are
        # chosen. The share is frozen here so a run decides by the value it started with, and a pilot that moves the
        # table or the share cannot change what a waiting run sends.
        "field_search": {"rule": FIELD_SEARCH_RULE, "sources": mode.field_sources, "records": mode.field_records,
                         "share": ROUTE_SHARE, "table_version": SOURCE_ROUTES_VERSION},
        "fulltext_search_rule": FULLTEXT_SEARCH_RULE, "fulltext_searches": mode.fulltext_searches,
        "embedding_threads": 4, "fetch_slots": 12, "slot_refill": True, "read_drain_ms": 5000, "arrival_margin_ms": 5000,
        "checkpoint_ms": 5000, "floor_ratio": 0.25,
        # Search always gets at least its own base; an earlier overrun is charged to the later stages instead.
        "protected_stages": ["search"],
        # K admission takes the abstract stage's unresolved works after the candidates (`read.selected`).
        "admission_order": "unresolved_last",
    }
    if deep_screening:
        if effort not in DEEP_SCREENING_EFFORTS:
            raise ValueError(f"deeper screening is not offered at {effort!r}")
        from deixis.domain.rules import ABSTRACT_BATCH
        policy["deep_screening"] = {"rule": DEEP_SCREENING_RULE, "first": mode.read_top + 1,
                                    "last": mode.read_top + DEEP_SCREENING_WORKS, "runs": 1, "batch": ABSTRACT_BATCH}
    if completion_arm != "off":
        # The records come off the keyword cap (`search.build_plan`), so every arm of the measurement reads the same
        # total; what the arm did not spend is recorded, which is how the pilot sees the cost of the reservation.
        policy["completion"] = {"rule": COMPLETION_RULE, "arm": completion_arm, "records": mode.completion_records,
                                "snippet_requests": mode.snippet_requests}
    if broad_index_arm != "off":
        # The records come off the keyword cap too (`search.build_plan`). A policy frozen with the `off` arm names
        # no block, which is byte for byte the policy frozen before the rule: a run queued then sends none either.
        policy["broad_index"] = {"rule": BROAD_INDEX_RULE, "arm": broad_index_arm,
                                 "records": mode.broad_index_records}
    if subtopic_arm != "off":
        # These records come off no cap: whether the request is sent can only be read after the field source's
        # last page, which is after the keyword loop that would spend them has ended, so records taken off that
        # loop's cap would be lost on every question where nothing is sent and the arms would read different
        # keyword totals. A run that sends it reads these records on top of the keyword cap. An `off` policy
        # names no key, which is the policy frozen before the rule.
        policy["subtopic_search"] = {"rule": SUBTOPIC_RULE, "arm": subtopic_arm, "records": mode.subtopic_records}
    if date_scope is not None:
        if date_scope.get("rule") != DATE_SCOPE_RULE:
            raise ValueError(f"unknown date scope rule {date_scope.get('rule')!r}")
        bounds = (date_scope.get("from_year"), date_scope.get("to_year"))
        if all(year is None for year in bounds):
            raise ValueError("a date scope names a lower bound, an upper bound, or both")
        if any(year is not None and not isinstance(year, int) for year in bounds):
            raise ValueError("a date scope's bounds are years")
        # The whole scope is frozen, the words it was read from included, so the measurement can say what the run
        # was bounded by and why without re-reading the question.
        policy["date_scope"] = {key: date_scope[key] for key in ("rule", "from_year", "to_year", "basis", "origin")}
    # The rule that also searches the other number form of a quoted phrase: every depth, every model.
    from deixis.providers.query_compiler import PHRASE_FORMS_RULE
    policy["phrase_forms_rule"] = PHRASE_FORMS_RULE
    if mode.rerank_allowance and not local_model:
        # A depth without an allowance, and a local-model run, name no key: their policy is the one frozen before.
        policy["rerank_allowance"] = {"rule": RERANK_ALLOWANCE_RULE, "ms": mode.rerank_allowance * 1000}
    if mode.phrase_searches:
        # The short phrase searches: how many phrases the step writes and what each request reads. A depth set to
        # none names no key, which is the policy frozen before the rule.
        policy["phrase_search"] = {"rule": PHRASE_SEARCH_RULE, "count": mode.phrase_searches,
                                   "records": PHRASE_SEARCH_RECORDS}
    # The word rule of a reranked window, frozen before the hash below: every depth, every model.
    policy["window_word_rule"] = WINDOW_WORD_RULE
    # The evidence minimum, frozen before the hash below: every depth, every model.
    policy["evidence_minimum"] = {"rule": EVIDENCE_MINIMUM_RULE, "search_ms": EVIDENCE_SEARCH_MS,
                                  "abstract_ceiling_ms": EVIDENCE_ABSTRACT_CEILING_MS}
    if not lexical_exclusion:
        policy["lexical_exclusion"] = False
    if not candidate_embedding:
        policy["candidate_embedding"] = False
    if local_model:
        # Still fast-path stages (`enforces` routes on them); only their deadline is gone.
        policy["no_deadline_stages"] = ["read", "answer"]
        # The handover goes with them, and the policy says so by name rather than simply missing the key: the design
        # gives every depth a handover moment, so a run that keeps none is a departure from it, readable in the run's
        # own record. The reason is the one the stage deadlines already carry: a model this computer runs screens and
        # answers far slower than the bases assume, and cutting its read hands the answer unscreened evidence.
        policy["handover"] = "none_local_model"
        del policy["handover_ms"]
    return policy | {"policy_hash": canonical.sha256_hex(policy)}


def with_intent(policy: dict[str, Any], intent: str) -> dict[str, Any]:
    """The frozen policy routed by the research's intent (UI parity S5a): `report` leaves it as it is; `papers` queues
    no answer after discovery; `table` and `compare` queue no answer and open the study table instead
    (`intent.after_discovery`); `statement` queues no answer and checks the research's sentence against the works read
    instead (`statement_check.after_discovery`). The hash covers the routing, so a run keeps the route it was queued
    with."""
    if intent == "report":
        return policy
    routed = {k: v for k, v in policy.items() if k != "policy_hash"} | {"auto_answer": False}
    if intent in ("table", "compare"):
        routed["after_discovery"] = "study_table"
    elif intent == "statement":
        routed["after_discovery"] = "statement_check"
    return routed | {"policy_hash": canonical.sha256_hex(routed)}


def deep_window(policy: dict[str, Any]) -> dict[str, Any] | None:
    """The frozen deeper-screening window of a run's policy, or None when the run was queued without it."""
    deep = policy.get("deep_screening")
    return deep if isinstance(deep, dict) and deep.get("rule") == DEEP_SCREENING_RULE else None


def read_window(policy: dict[str, Any]) -> int:
    """The last list place the run screens: the deeper window's last place when it has one, else N."""
    deep = deep_window(policy)
    return deep["last"] if deep else policy["N"]


def screened_once(effort: str) -> dict[str, int] | None:
    """The list places the deeper screening reads once at this depth, or None where it is not offered."""
    if effort not in DEEP_SCREENING_EFFORTS:
        return None
    n = MODES[effort].read_top
    return {"first": n + 1, "last": n + DEEP_SCREENING_WORKS}


def effort_limits(deep_screening: bool = False) -> dict[str, Any]:
    """What each research depth gives a run, read from MODES at the moment of asking: the depth text says these
    numbers, so a changed mode cannot leave the text behind. `papers` is N, the top of the ranking a run reads;
    `fulltext` is K, the most works a run reads in their full text (selected pages, UI parity S14's funnel). With
    `deep_screening` on, Standard and Detailed add `screened_once`, the list places read once.

    No minutes: a depth's stage budgets are soft deadlines aimed at a delivery target, and how often that target is
    actually met is measured rather than assumed, so a number of minutes here would promise the person something no
    measurement supports. The target and its attainment rate belong to the measurement, not to the depth's label."""
    return {"efforts": {effort: {"papers": mode.read_top,
                                 "fulltext": mode.fulltext_works,
                                 **({"screened_once": once} if deep_screening and (once := screened_once(effort)) else {})}
                        for effort, mode in MODES.items()}}


def enabled(budget: dict[str, Any]) -> bool:
    return (budget.get("fast_path") or {}).get("policy") == POLICY




def completion(budget: dict[str, Any]) -> dict[str, Any] | None:
    """The Semantic Scholar completion arm this run froze, or None for a run of the `off` arm and for every run
    queued before the rule."""
    return (budget.get("fast_path") or {}).get("completion")


def broad_index(budget: dict[str, Any]) -> dict[str, Any] | None:
    """The second independent index's arm this run froze, or None for a run of the `off` arm and for every run
    queued before the rule."""
    return (budget.get("fast_path") or {}).get("broad_index")


def subtopic_search(budget: dict[str, Any]) -> dict[str, Any] | None:
    """The sub-topic search's arm this run froze, or None for a run of the `off` arm and for every run queued
    before the rule."""
    return (budget.get("fast_path") or {}).get("subtopic_search")


def date_scope(budget: dict[str, Any]) -> dict[str, Any] | None:
    """The years this run searches in, or None for a run that bounds none and for every run queued before the rule."""
    return (budget.get("fast_path") or {}).get("date_scope")


def scope_years(store, research_id: str, scope_revision: int) -> dict[str, Any] | None:
    """The years the searches of this question revision are bounded to, read from its own discovery runs.

    A later search of the same question — a follow-up search, a citation-map walk, a watch — searches the same
    years: the candidates are one pool per question revision, and a request outside those years would add records
    the question never asked for. None where nothing bounded them, which is every question asked before the rule.
    """
    for row in store.conn.execute(
            "SELECT budget_json FROM runs WHERE research_id = ? AND scope_revision = ? AND kind = 'discovery'"
            " ORDER BY rowid", (research_id, scope_revision)):
        years = date_scope(json.loads(row["budget_json"]))
        if years is not None:
            return years
    return None


def phrase_forms_on(budget: dict[str, Any]) -> bool:
    """Whether this run froze the rule that also searches the other number form of a quoted phrase; a run queued
    before it counts and compiles its plan as it always did."""
    from deixis.providers.query_compiler import PHRASE_FORMS_RULE
    return (budget.get("fast_path") or {}).get("phrase_forms_rule") == PHRASE_FORMS_RULE


def evidence_minimum(store: Any, run: dict[str, Any]) -> dict[str, Any] | None:
    """The evidence minimum the run's ledger froze (`EVIDENCE_MINIMUM_RULE`), or None for a run frozen before it."""
    binding = run["budget"].get("fast_path") or {}
    ledger_id = binding.get("ledger_run_id", run["id"])
    policy = binding if ledger_id == run["id"] else (store.run(ledger_id)["budget"].get("fast_path") or {})
    rule = policy.get("evidence_minimum") or {}
    return rule if rule.get("rule") == EVIDENCE_MINIMUM_RULE else None


def window_word_rule(policy: dict[str, Any]) -> bool:
    """Whether this run froze the rule that keeps a reranked top-N window open to the model (`WINDOW_WORD_RULE`)."""
    return policy.get("window_word_rule") == WINDOW_WORD_RULE


def phrase_search(budget: dict[str, Any]) -> dict[str, Any] | None:
    """The short phrase searches this run froze, or None for a run queued before the rule or at a depth set to none."""
    rule = (budget.get("fast_path") or {}).get("phrase_search") or {}
    return rule if rule.get("rule") == PHRASE_SEARCH_RULE and rule.get("count") else None


def rerank_allowance_ms(budget: dict[str, Any]) -> int | None:
    """The reranker's own allowance this run froze, in ms, or None for a run queued before the rule."""
    allowance = (budget.get("fast_path") or {}).get("rerank_allowance") or {}
    return allowance.get("ms") if allowance.get("rule") == RERANK_ALLOWANCE_RULE else None


def rerank_carry_ms(store: Any, run: dict[str, Any]) -> int:
    """The time the reranker ran past the ranking cutoff on its allowance, as its step recorded it, every attempt of
    it included (a paused step keeps what it used); 0 when it ran none, and always 0 for a run whose policy froze no
    allowance."""
    binding = run["budget"].get("fast_path") or {}
    ledger_id = binding.get("ledger_run_id", run["id"])
    policy = binding if ledger_id == run["id"] else (store.run(ledger_id)["budget"].get("fast_path") or {})
    if rerank_allowance_ms({"fast_path": policy}) is None:
        return 0
    from deixis.workflow.search.small_batch import RERANK_KEY
    row = store.conn.execute("SELECT output_json FROM run_steps WHERE run_id = ? AND operation_key = ?",
                             (ledger_id, RERANK_KEY)).fetchone()
    output = json.loads(row["output_json"]) if row and row["output_json"] else {}
    return int((output.get("allowance") or {}).get("past_cutoff_ms") or 0)


def candidate_embedding_on(budget: dict[str, Any]) -> bool:
    """Whether this run embeds its candidates. A budget frozen before the switch embedded them, so it still does."""
    return (budget.get("fast_path") or {}).get("candidate_embedding", True)


def chain_on(budget: dict[str, Any]) -> bool:
    return enabled(budget) and budget["fast_path"].get("chain_rule") in CHAIN_RULES


def enforces(budget: dict[str, Any], stage: str) -> bool:
    stages = (budget.get("fast_path") or {}).get("enforced_stages")
    return enabled(budget) and isinstance(stages, list) and stage in stages


def ledger_started_at(store: Any, run: dict[str, Any]) -> datetime | None:
    """When this run's clock started: the moment the question was submitted and the discovery run was created."""
    ledger_id = (run["budget"].get("fast_path") or {}).get("ledger_run_id", run["id"])
    row = store.conn.execute("SELECT started_at FROM fast_path_ledgers WHERE ledger_run_id = ?", (ledger_id,)).fetchone()
    return datetime.fromisoformat(row["started_at"]) if row else None


def handover_deadline(store: Any, run: dict[str, Any]) -> datetime | None:
    """The moment this run must hand over to answer writing, however much it has read by then.

    It is read from the ledger's start, not from the time the stages were actually working: the person's clock runs
    from the question's submission to the answer in front of them, so the queue, the gaps between stages and a pause
    are all inside it. A run that stopped overnight has missed its target; it does not get a fresh window on resume.
    None where the policy carries no handover: a run frozen before the rule, and a run on a model this computer
    runs (`handover` = `none_local_model`)."""
    binding = (run["budget"].get("fast_path") or {})
    if not enabled(run["budget"]):
        return None
    handover = binding.get("handover_ms")
    if handover is None and (ledger_id := binding.get("ledger_run_id")):
        # An answer run carries only its binding, so the depth's handover is read from the run that froze it.
        handover = ((store.run(ledger_id)["budget"].get("fast_path") or {}).get("handover_ms"))
    if not isinstance(handover, int) or isinstance(handover, bool):
        return None
    started = ledger_started_at(store, run)
    return None if started is None else started + timedelta(milliseconds=handover)


def stage_deadline(store: Any, run: dict[str, Any], stage: str) -> datetime | None:
    """A stage's own soft deadline, never later than the run's handover moment for a stage that must be done before
    the answer is written, except under the evidence minimum, where the handover cuts no stage. The handover is the harder of the two: a stage that carried time forward, or a protected
    stage that keeps its whole base, cannot push the first answer past the depth's target.

    The handover stands even where the stage has no deadline of its own, which is how it reaches the two places the
    stage accounting does not: a stage this policy does not enforce, the plan stage above all, and a stage working in
    a rework interval, which is what retrying a failed search of a completed run opens. The person's clock has run
    out in both cases."""
    # Under the evidence minimum the handover is a recorded target and cuts no stage.
    evidence = evidence_minimum(store, run)
    handover = handover_deadline(store, run) if stage in PRE_ANSWER and evidence is None else None
    if handover is not None and stage in AFTER_RANKING:
        # The time the reranker ran past the ranking cutoff on its own allowance moves the cap with it, so the read
        # stage keeps the time it would have had and the answer comes that much later.
        handover += timedelta(milliseconds=rerank_carry_ms(store, run))
    if not enforces(run["budget"], stage) or stage in run["budget"]["fast_path"].get("no_deadline_stages", ()):
        return handover
    ledger = run["budget"]["fast_path"].get("ledger_run_id", run["id"])
    row = store.conn.execute(
        "SELECT i.started_at, s.alloc_ms, s.used_ms FROM fast_path_stages s"
        " JOIN fast_path_intervals i ON i.ledger_run_id = s.ledger_run_id AND i.stage = s.stage"
        " WHERE s.ledger_run_id = ? AND s.stage = ? AND s.status = 'open'"
        " AND i.run_id = ? AND i.closed_at IS NULL AND i.rework = 0",
        (ledger, stage, run["id"])).fetchone()
    minimum = evidence if stage == "search" else None
    if row is None and evidence is not None:
        # A rework interval (retrying a failed search of a completed run) has no stage accounting, and under the
        # evidence minimum no handover either: it keeps the stage's allocation, and search its minimum, from its start.
        rework = store.conn.execute(
            "SELECT i.started_at, s.alloc_ms FROM fast_path_stages s"
            " JOIN fast_path_intervals i ON i.ledger_run_id = s.ledger_run_id AND i.stage = s.stage"
            " WHERE s.ledger_run_id = ? AND s.stage = ? AND i.run_id = ? AND i.closed_at IS NULL AND i.rework = 1",
            (ledger, stage, run["id"])).fetchone()
        if rework is not None:
            begun = datetime.fromisoformat(rework["started_at"])
            return begun + timedelta(milliseconds=max(rework["alloc_ms"], (minimum or {}).get("search_ms", 0)))
    if row is None:
        if minimum is not None and store.conn.execute(
                "SELECT 1 FROM fast_path_stages WHERE ledger_run_id = ? AND stage = 'search'", (ledger,)).fetchone() is None:
            # The search stage has not started, so its minimum has not either: nothing of it has passed yet.
            return None
        return handover
    deadline = datetime.fromisoformat(row["started_at"]) + timedelta(milliseconds=row["alloc_ms"] - row["used_ms"])
    deadline = deadline if handover is None else min(deadline, handover)
    if minimum is not None:
        # The search stage keeps its minimum from its own start, whatever the handover moment says.
        deadline = max(deadline, datetime.fromisoformat(row["started_at"]) + timedelta(milliseconds=minimum["search_ms"]))
    return deadline


def past_deadline(store: Any, run: dict[str, Any], stage: str) -> bool:
    """Whether this stage must stop. A pre-answer stage past the run's handover moment also records that the run
    missed its depth's target, wherever in the run that moment arrives."""
    deadline = stage_deadline(store, run, stage)
    past = deadline is not None and store.clock.now() >= deadline
    # Under the evidence minimum the handover cuts no stage, so its passing is recorded whether or not the stage stops.
    if stage in PRE_ANSWER and (past or evidence_minimum(store, run) is not None):
        note_handover_passed(store, run)
    return past


def note_handover_passed(store: Any, run: dict[str, Any]) -> None:
    """Write the moment this run's delivery clock ran out, once, if it has. The record is what the handover produces
    where stopping would leave nothing usable: a plan cut in the middle leaves no query to search with, so planning
    goes on and the run is marked as having missed its target instead of being abandoned."""
    handover = handover_deadline(store, run)
    # The moment itself is inside the target, which is how `view()` and the measurement read it too: a run that
    # turns to writing at exactly that second met the depth's deadline. Only passing it is a miss.
    if handover is None or store.clock.now() <= handover:
        return
    ledger_id = run["budget"]["fast_path"].get("ledger_run_id", run["id"])
    # Read before writing: the read stage asks this on every work it considers, and once the moment is recorded a
    # repeated write would take a lock to change nothing.
    row = store.conn.execute("SELECT handover_passed_at FROM fast_path_ledgers WHERE ledger_run_id = ?",
                             (ledger_id,)).fetchone()
    if row is None or row["handover_passed_at"]:
        return
    store.conn.execute("UPDATE fast_path_ledgers SET handover_passed_at = ? WHERE ledger_run_id = ?"
                       " AND handover_passed_at IS NULL", (timestamp(store.clock), ledger_id))


def ranking_similarities(store: Any, run: dict[str, Any], model: str) -> dict[str, float]:
    scores = store.source_similarities(run["research_id"], run["scope_revision"], model)
    if not enabled(run["budget"]) or run["kind"] != "discovery":
        return scores
    heads = store.work_heads(run["research_id"])
    for row in store.conn.execute(
            "SELECT q.source_version_id, v.work_id FROM fast_path_embedding_queue q"
            " JOIN source_versions v ON v.id = q.source_version_id"
            " WHERE q.run_id = ? AND q.status = 'unembedded_at_cutoff'", (run["id"],)):
        scores.pop(row["source_version_id"], None)
        scores.pop(heads.get(row["work_id"]), None)
    return scores


def answer_budget(store: Any, rid: str, revision: int, budget: dict[str, Any]) -> dict[str, Any]:
    ledger_id = (budget.get("inspection") or {}).get("list_run_id")
    if not ledger_id:
        return budget
    discovery = store.run(ledger_id)
    policy = discovery["budget"].get("fast_path")
    if not enabled(discovery["budget"]):
        return budget
    ledger = store.conn.execute("SELECT * FROM fast_path_ledgers WHERE ledger_run_id = ?", (ledger_id,)).fetchone()
    if ledger is None or (ledger["research_id"], ledger["scope_revision"], ledger["policy_hash"]) != (rid, revision, policy["policy_hash"]):
        return budget
    return budget | {"fast_path": {"policy": POLICY, "policy_hash": ledger["policy_hash"],
                                   "ledger_run_id": ledger_id, "role": "rerun" if ledger["answer_run_id"] else "first",
                                   **({"enforced_stages": ["answer"]}
                                      if enforces(discovery["budget"], "answer") else {})}}


def create_run(store: Any, run: dict[str, Any]) -> None:
    if not enabled(run["budget"]):
        return
    policy = run["budget"]["fast_path"]
    if run["kind"] == "discovery":
        store.conn.execute(
            "INSERT INTO fast_path_ledgers (ledger_run_id, research_id, scope_revision, policy, policy_hash, mode, started_at)"
            " VALUES (?, ?, ?, ?, ?, ?, ?)",
            (run["id"], run["research_id"], run["scope_revision"], POLICY, policy["policy_hash"], policy["mode"], run["created_at"]))
    elif run["kind"] == "answer":
        ledger = store.conn.execute("SELECT * FROM fast_path_ledgers WHERE ledger_run_id = ?", (policy["ledger_run_id"],)).fetchone()
        if ledger is None or (ledger["research_id"], ledger["scope_revision"], ledger["policy_hash"]) != (
                run["research_id"], run["scope_revision"], policy["policy_hash"]):
            raise LedgerMismatch(f"answer run {run['id']}: discovery ledger {policy['ledger_run_id']} is missing or"
                                 " belongs to another research, revision or policy")
        # The role is fixed by the same transaction that queues the answer, rather than by a preceding API read.
        policy["role"] = ("late_revision" if run["budget"].get("late_revision_id")
                          else "rerun" if ledger["answer_run_id"] else "first")
        if policy["role"] == "first":
            store.conn.execute("UPDATE fast_path_ledgers SET answer_run_id = ? WHERE ledger_run_id = ? AND answer_run_id IS NULL",
                               (run["id"], policy["ledger_run_id"]))
        from deixis.storage.db import dumps
        store.conn.execute("UPDATE runs SET budget_json = ? WHERE id = ?", (dumps(run["budget"]), run["id"]))


def enter_stage(store: Any, run: dict[str, Any], stage: str) -> str | None:
    if not enabled(run["budget"]):
        return None
    if run["budget"]["fast_path"].get("role") == "late_revision":
        return None
    note_handover_passed(store, run)
    conn, ts = store.conn, timestamp(store.clock)
    binding = run["budget"]["fast_path"]
    ledger_id = binding.get("ledger_run_id", run["id"])
    generation = run["budget"].get("retry_provider_requests", 0)
    with transaction(conn):
        if store.run(run["id"])["status"] not in ("running", "pause_requested"):
            return None
        if stage == "answer":
            if binding["role"] == "rerun":
                stage = "answer_rerun"
                if conn.execute("SELECT 1 FROM fast_path_intervals WHERE run_id = ? AND stage = ? AND close_reason = 'stage_done'",
                                (run["id"], stage)).fetchone():
                    return None
            elif conn.execute("SELECT answer_outcome FROM fast_path_ledgers WHERE ledger_run_id = ?", (ledger_id,)).fetchone()[0]:
                return None
        opened = conn.execute("SELECT id FROM fast_path_intervals WHERE run_id = ? AND stage = ? AND closed_at IS NULL",
                              (run["id"], stage)).fetchone()
        if opened:
            return opened[0]
        row = conn.execute("SELECT * FROM fast_path_stages WHERE ledger_run_id = ? AND stage = ?", (ledger_id, stage)).fetchone()
        if row and row["status"] in ("done", "skipped") and row["done_generation"] >= generation:
            return None
        seq = STAGES.index(stage) + 1 if stage in STAGES else 0
        if seq:
            if conn.execute(
                    "SELECT 1 FROM fast_path_intervals i JOIN fast_path_stages s"
                    " ON s.ledger_run_id = i.ledger_run_id AND s.stage = i.stage"
                    " WHERE i.ledger_run_id = ? AND i.closed_at IS NULL AND s.seq > 0 AND s.seq < ?",
                    (ledger_id, seq)).fetchone():
                raise LedgerMismatch(f"run {run['id']}: cannot enter {stage}, a previous stage still has an open interval")
        if row is None and stage != "answer_rerun":
            policy = store.run(ledger_id)["budget"]["fast_path"]
            for ordinal, earlier in enumerate(STAGES[:max(0, seq - 1)], 1):
                conn.execute(
                    "INSERT OR IGNORE INTO fast_path_stages"
                    " (ledger_run_id, stage, seq, base_ms, balance_before_ms, alloc_ms, opened_at, status, done_at, done_generation)"
                    " VALUES (?, ?, ?, ?, 0, 0, ?, 'skipped', ?, ?)",
                    (ledger_id, earlier, ordinal, policy["stage_base_ms"][earlier], ts, ts, generation))
            balance = conn.execute(
                "SELECT COALESCE(SUM(base_ms - used_ms), 0) FROM fast_path_stages"
                " WHERE ledger_run_id = ? AND seq > 0 AND seq < ? AND status IN ('done', 'skipped')", (ledger_id, seq)).fetchone()[0]
            debt_free = (policy.get("evidence_minimum") or {}).get("rule") == EVIDENCE_MINIMUM_RULE
            if debt_free:
                # Unused time carries forward and is spent in order; an overrun is never carried as debt:
                # B_next = max(0, B + base - used). The reranker's time past its cutoff is an overrun of the ranking
                # stage, already not charged here, so it is not given back a second time.
                balance = 0
                for earlier in conn.execute(
                        "SELECT base_ms, used_ms FROM fast_path_stages WHERE ledger_run_id = ? AND seq > 0 AND seq < ?"
                        " AND status IN ('done', 'skipped') ORDER BY seq", (ledger_id, seq)):
                    balance = max(0, balance + earlier["base_ms"] - earlier["used_ms"])
            elif stage in AFTER_RANKING:
                # The time the reranker ran past the ranking cutoff on its allowance is not charged to this stage.
                balance += rerank_carry_ms(store, run)
            base = policy["stage_base_ms"].get(stage, 0)
            # A protected stage's floor is its whole base; a policy frozen without the field keeps the 25% floor.
            floor = base if stage in policy.get("protected_stages", ()) else int(base * policy["floor_ratio"])
            alloc = max(floor, base + balance) if seq else 0
            conn.execute(
                "INSERT INTO fast_path_stages (ledger_run_id, stage, seq, base_ms, balance_before_ms, alloc_ms, opened_at, status)"
                " VALUES (?, ?, ?, ?, ?, ?, ?, 'open')", (ledger_id, stage, seq, base, balance, alloc, ts))
        rework = int(row is not None and row["status"] in ("done", "skipped"))
        attempt = conn.execute("SELECT COUNT(*) + 1 FROM fast_path_intervals WHERE run_id = ? AND stage = ?", (run["id"], stage)).fetchone()[0]
        interval_id = new_id("fpi")
        conn.execute(
            "INSERT INTO fast_path_intervals (id, ledger_run_id, run_id, stage, attempt, generation, rework, started_at, last_checkpoint_at)"
            " VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)", (interval_id, ledger_id, run["id"], stage, attempt, generation, rework, ts, ts))
        return interval_id


def checkpoint(store: Any, interval_id: str) -> None:
    ts = timestamp(store.clock)
    with transaction(store.conn):
        row = store.conn.execute("SELECT * FROM fast_path_intervals WHERE id = ? AND closed_at IS NULL", (interval_id,)).fetchone()
        if row:
            store.conn.execute(
                "UPDATE fast_path_intervals SET last_checkpoint_at = ?, max_checkpoint_gap_ms = MAX(max_checkpoint_gap_ms, ?)"
                " WHERE id = ? AND closed_at IS NULL", (ts, elapsed(row["last_checkpoint_at"], ts), interval_id))


def close_interval(store: Any, row: Any, ts: str, reason: str) -> None:
    conn = store.conn
    changed = conn.execute(
        "UPDATE fast_path_intervals SET closed_at = ?, close_reason = ?, max_checkpoint_gap_ms = MAX(max_checkpoint_gap_ms, ?)"
        " WHERE id = ? AND closed_at IS NULL",
        (ts, reason, elapsed(row["last_checkpoint_at"], ts), row["id"])).rowcount
    if not changed:
        return
    used = elapsed(row["started_at"], ts)
    conn.execute(
        "UPDATE fast_path_stages SET used_ms = used_ms + ?, rework_ms = rework_ms + ?,"
        " overrun_ms = MAX(0, used_ms + ? - alloc_ms) WHERE ledger_run_id = ? AND stage = ?",
        (used, used if row["rework"] else 0, used, row["ledger_run_id"], row["stage"]))
    if reason == "stage_done":
        conn.execute(
            "UPDATE fast_path_stages SET status = 'done', done_at = ?, done_generation = ? WHERE ledger_run_id = ? AND stage = ?",
            (ts, row["generation"], row["ledger_run_id"], row["stage"]))


def close_stage(store: Any, run_id: str, stage: str) -> None:
    with transaction(store.conn):
        rows = store.conn.execute("SELECT * FROM fast_path_intervals WHERE run_id = ? AND stage = ? AND closed_at IS NULL",
                                  (run_id, stage)).fetchall()
        ts = timestamp(store.clock)
        for row in rows:
            close_interval(store, row, ts, "stage_done")


def close_run(store: Any, run_id: str, reason: str) -> None:
    ts = timestamp(store.clock)
    for row in store.conn.execute("SELECT * FROM fast_path_intervals WHERE run_id = ? AND closed_at IS NULL", (run_id,)).fetchall():
        close_interval(store, row, ts, reason)


def recover(store: Any) -> None:
    for row in store.conn.execute("SELECT * FROM fast_path_intervals WHERE closed_at IS NULL").fetchall():
        close_interval(store, row, row["last_checkpoint_at"], "recovered")


def save_answer(store: Any, run_id: str, outcome: str) -> None:
    run = store.run(run_id)
    if not enabled(run["budget"]):
        return
    binding, ts = run["budget"]["fast_path"], timestamp(store.clock)
    if binding.get("role") == "late_revision":
        return
    if binding["role"] == "rerun":
        close_stage(store, run_id, "answer_rerun")
        return
    changed = store.conn.execute(
        "UPDATE fast_path_ledgers SET answer_outcome = ?, answer_published_at = ?"
        " WHERE ledger_run_id = ? AND answer_run_id = ? AND answer_outcome IS NULL",
        (outcome, ts if outcome == "structurally_valid" else None, binding["ledger_run_id"], run_id)).rowcount
    if changed:
        close_stage(store, run_id, "answer")


# The names a pre-answer stage's time past the handover moment takes, before and after the stage's own allocation
# ran out: the plan's overrun; the search stage's own time and the minimum past it; ranking's own time and the
# reranker's allowance past it; the read stage's own time and the required abstract reads past it.
EVIDENCE_CAUSES = {"plan": ("plan_overrun", "plan_overrun"), "search": ("search_allocation", "search_minimum"),
                   "ranking": ("ranking_allocation", "reranker_allowance"),
                   "read": ("read_allocation", "required_abstract_reads")}


def evidence_causes(ledger: dict[str, Any], intervals: list[dict[str, Any]], stages: list[dict[str, Any]],
                    policy: dict[str, Any], end: str) -> dict[str, int]:
    """The handover miss split by cause, in ms; empty while the handover has not passed. `end` is when the answer
    stage opened, or now while it has not."""
    if not isinstance(policy.get("handover_ms"), int):
        return {}
    handover = datetime.fromisoformat(ledger["started_at"]) + timedelta(milliseconds=policy["handover_ms"])
    stop = datetime.fromisoformat(end)
    if stop <= handover:
        return {}
    causes: dict[str, int] = {}
    alloc = {stage["stage"]: stage["alloc_ms"] for stage in stages}
    for name, (within, beyond) in EVIDENCE_CAUSES.items():
        used = 0  # what the stage's earlier intervals used of its allocation
        for interval in sorted((i for i in intervals if i["stage"] == name and not i["rework"]),
                               key=lambda i: i["started_at"]):
            begun = datetime.fromisoformat(interval["started_at"])
            closed = min(datetime.fromisoformat(interval["closed_at"]) if interval["closed_at"] else stop, stop)
            # Where the stage's own allocation ran out in this interval.
            own = begun + timedelta(milliseconds=max(0, alloc.get(name, 0) - used))
            for label, start, finish in ((within, max(begun, handover), min(closed, own)),
                                         (beyond, max(begun, handover, own), closed)):
                if finish > start:
                    causes[label] = causes.get(label, 0) + round((finish - start).total_seconds() * 1000)
            used += max(0, round((closed - begun).total_seconds() * 1000))
    # Whatever no stage interval covers: the gaps between stages, queueing the answer run, the optional title call.
    causes["between_stages"] = max(0, round((stop - handover).total_seconds() * 1000) - sum(causes.values()))
    return causes


def view(store: Any, run: dict[str, Any]) -> dict[str, Any] | None:
    if not enabled(run["budget"]):
        return None
    binding = run["budget"]["fast_path"]
    ledger_id = binding.get("ledger_run_id", run["id"])
    ledger = dict(store.conn.execute("SELECT * FROM fast_path_ledgers WHERE ledger_run_id = ?", (ledger_id,)).fetchone())
    ts = timestamp(store.clock)
    intervals = [dict(row) for row in store.conn.execute("SELECT * FROM fast_path_intervals WHERE ledger_run_id = ?", (ledger_id,))]
    stages = []
    for row in store.conn.execute("SELECT * FROM fast_path_stages WHERE ledger_run_id = ? ORDER BY seq", (ledger_id,)):
        stage = dict(row)
        opened = [i for i in intervals if i["stage"] == stage["stage"] and i["closed_at"] is None]
        stage["live"] = bool(opened)
        stage["used_ms"] += sum(elapsed(i["started_at"], ts) for i in opened)
        stage["rework_ms"] += sum(elapsed(i["started_at"], ts) for i in opened if i["rework"])
        stage["overrun_ms"] = max(0, stage["used_ms"] - stage["alloc_ms"])
        stages.append(stage)
    result = {
        "policy": ledger["policy"], "policy_hash": ledger["policy_hash"], "enforcement": "none",
        "ledger_run_id": ledger_id, "role": binding.get("role"), "stages": stages,
        "balance_ms": sum(s["base_ms"] - s["used_ms"] for s in stages if s["seq"] > 0),
        "used_ms": sum(s["used_ms"] for s in stages if s["seq"] > 0),
        # The time to the answer being recorded, not to it being on screen: the display is not timed here, so a
        # delivery rate read from this number is a rate to the record and is named that way wherever it is reported.
        "latency_ms": elapsed(ledger["started_at"], ledger["answer_published_at"]) if ledger["answer_published_at"] else None,
        "answer_outcome": ledger["answer_outcome"],
        "max_checkpoint_gap_ms": max((i["max_checkpoint_gap_ms"] for i in intervals), default=0),
        "rerun_used_ms": sum(elapsed(i["started_at"], i["closed_at"] or ts) for i in intervals
                             if i["run_id"] == run["id"] and i["stage"] == "answer_rerun"),
    }
    policy = store.run(ledger_id)["budget"]["fast_path"]
    if "enforced_stages" in policy:
        result["enforced_stages"] = policy["enforced_stages"]
        result["enforcement"] = policy["enforced_stages"]
    # The depth's delivery-time target and handover moment, and where this run actually stood against them.
    result["target_ms"] = policy.get("total_ms")
    result["handover_ms"] = policy.get("handover_ms")
    result["handover"] = policy.get("handover")
    # Already recorded as having missed the target, by whichever stage first saw the moment pass.
    result["handover_passed_at"] = ledger["handover_passed_at"]
    # When the run actually turned to writing: the answer stage opening, not the read stage closing. Between the two
    # sit the optional title call and queuing the answer run, and a reworked read stage would move its `done_at`.
    answer_started = min((i["started_at"] for i in intervals if i["stage"] == "answer"), default=None)
    result["handover_at_ms"] = elapsed(ledger["started_at"], answer_started) if answer_started else None
    target, handover = result["target_ms"], result["handover_ms"]
    # An answer that ended without being published missed the target: the person was given no sourced answer inside
    # it. Undecided only while the run may still publish one.
    answer_status = (store.conn.execute("SELECT status FROM runs WHERE id = ?", (ledger["answer_run_id"],)).fetchone()
                     if ledger["answer_run_id"] else None)
    # Nothing more can arrive: the answer recorded an outcome, the answer run ended, or no answer was ever queued
    # and the run that would have queued one ended.
    ended = bool(ledger["answer_outcome"]) or (
        answer_status["status"] in TERMINAL if answer_status
        else store.run(ledger_id)["status"] in TERMINAL)
    if policy.get("handover") == "none_local_model":
        # No handover and no deadline on the stages where the model works, so no delivery target to meet either.
        result["on_target"] = None
    elif result["latency_ms"] is not None and isinstance(target, int):
        result["on_target"] = result["latency_ms"] <= target
    elif isinstance(target, int) and (ended or elapsed(ledger["started_at"], ts) > target):
        # Still working, but the depth's whole target has passed: an answer recorded now cannot meet it either, so
        # leaving this run undecided would report the rate among the runs that were quick enough.
        result["on_target"] = False
    else:
        result["on_target"] = None
    result["handover_on_target"] = (result["handover_at_ms"] <= handover
                                    if result["handover_at_ms"] is not None and isinstance(handover, int) else None)
    if (policy.get("evidence_minimum") or {}).get("rule") == EVIDENCE_MINIMUM_RULE:
        # Why the run turned to writing late, read from the stage intervals: each pre-answer stage's time past the
        # handover moment is named by what kept it going, and the gaps between stages are their own cause, so the
        # causes add up to the handover miss.
        result["evidence_minimum"] = {
            "rule": EVIDENCE_MINIMUM_RULE,
            "causes": evidence_causes(ledger, intervals, stages, policy, answer_started or ts),
            "handover_missed_ms": (max(0, result["handover_at_ms"] - handover)
                                   if result["handover_at_ms"] is not None and isinstance(handover, int) else None),
            "target_missed_ms": (max(0, result["latency_ms"] - target)
                                 if result["latency_ms"] is not None and isinstance(target, int) else None)}
    return result
