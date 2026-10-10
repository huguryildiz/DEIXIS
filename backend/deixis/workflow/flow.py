"""Execution of discovery and answer runs.

Discovery: code vocabulary → compiled provider queries → paged provider searches → abstract screening.
Answer: fetch accessible PDFs for included sources → text retrieval → grounded answer (model)
→ claim review (reviewer model, when one is set).
The literature model reads abstracts and full text; the research model writes the answer.
Completed steps are skipped on resume. A connection or provider failure is recorded
with its reason; discovery continues when another provider search succeeds, and nothing is silently substituted. A review failure is recorded
on the review and does not pause the run: the answer never depends on its review.
"""

from __future__ import annotations

import asyncio
import copy
import hashlib
import json
import logging
import math
from deixis.domain.limits import service_error_kind, retry_at, safe_error
import re
from collections import Counter
from dataclasses import dataclass, field
from typing import Any, Awaitable, Callable, Iterator

import httpx

from deixis.config import Settings
from deixis.documents import fetch as fetch_module
from deixis.documents import acquisition, embeddings, identity, math_reader, ocr, pdf
from deixis.domain import canonical, contracts, expansion as phrase_candidates, phrasebank, vocabulary as question_words
from deixis.domain.rules import (ABSTRACT_BATCH, ABSTRACT_QUOTE_MIN_CHARS, ABSTRACT_READ_LIMIT, ABSTRACT_RUNS,
                                 CHAIN_ABSTRACT_READ, CHAIN_CITING_CAP, CHAIN_CITING_PAGE, FULLTEXT_CRITERION_PASSAGES, FULLTEXT_PASSAGES_PER_CALL, FULLTEXT_QUOTE_MIN_CHARS,
                                 FULLTEXT_RUNS, MAX_RATE_LIMIT_MODEL_RETRIES, MAX_TRANSIENT_NETWORK_RETRIES,
                                 PROVIDER_WAIT, SEARCH_PARALLEL_HOSTS, SW_READ_LIMIT,
                                 after_invalid_output, effective_reviewer, schema_repairs, step_model)
from deixis.domain.rules import CHAIN_S2_BACKWARD_LIMIT, RevisionConflict
from deixis.domain.skill import RUNTIME_FILES, SkillPackage
from deixis.domain.vocabulary import Extraction
from deixis.models import prompt
from deixis.models.adapter import ModelAdapter, ModelStepResult, is_rate_limited
from deixis.providers import openalex, query_compiler, facade, contract, semantic_scholar
from deixis.providers.common import FIRST_PAGE, MAX_RATE_LIMIT_RETRIES, SearchOutcome, normalize_doi
from deixis.providers.registry import CONNECTORS, Connector, endpoint_options, reading, search_providers
from deixis.storage.db import dumps, new_id, now, transaction
from deixis.workflow.concurrency import ModelCallLimiter
from deixis.workflow import abstract_stage
from deixis.workflow import small_batch
from deixis.workflow import fast_path
from deixis.workflow import adjudication
from deixis.workflow import approval as approval_rules
from deixis.workflow import chaining
from deixis.workflow import criterion as criterion_rules
from deixis.workflow import criterion_passages
from deixis.workflow import english_question
from deixis.workflow import expansion as expansion_rules
from deixis.workflow import flow_counts
from deixis.workflow import fulltext
from deixis.workflow import lookups
from deixis.workflow import person_reading
from deixis.workflow import probes as probe_rules
from deixis.workflow import protocol
from deixis.workflow import queue as human_queue
from deixis.workflow import ranking as ranking_rules
from deixis.workflow import report_pipeline
from deixis.workflow import routing as routing_rules
from deixis.workflow import search_query as search_query_rules
from deixis.workflow import suggestions as suggestion_rules
from deixis.workflow import vocabulary as vocabulary_rules
from deixis.workflow.decisions import DecisionStore, HumanDecisionStands
from deixis.workflow.equations import EXTRACTION_FAILED, MAX_ATTEMPTS as EQUATION_ATTEMPTS, equation_state
from deixis.workflow.store import ACTIVE_RUN_STATUSES, NotFound, RunInProgress, Store
from deixis.workflow.tables import MAX_COLUMNS_PER_CALL, MAX_FILL_SOURCES, TableStore, check_value

log = logging.getLogger(__name__)

CAPABILITIES = {
    "supported_tasks": ["grounded_answer", "answer_review", "cell_extraction", "table_columns", "research_title"],
    # `abstract_screening` is deliberately not listed: adding it would change every stored StepInput, including a
    # `legacy` run's, and this field tells the model what the product can do, not which step it is running.
    "unsupported_tasks": ["synthesis", "candidate_development", "claim_check", "experiment"],
}
MAX_DOWNLOADS_PER_RUN = 8
RESPLIT_KEY = "grounded_answer_resplit"  # D249: the one extra repair of an answer that fails only on D247's rule
INFERENCE_CAP_KEY = "grounded_answer_inference_cap"  # D260: one rewrite of a valid answer that is mostly analyst inference
# The reason an sw answer records when neither included works nor eligible abstracts are available (D234).
NO_INCLUDABLE_SOURCE = "no_includable_source"
MAX_ABSTRACT_CHARS = 2500
MAX_PASSAGES_PER_SOURCE = 6  # passages one included source may contribute to an answer step
PDF_PAGES_PER_SOURCE = 2  # PDF passages a source adds to its abstract when the included sources outnumber the passage limit
MAX_SMALL_PDF_CHARS = 60_000  # bounded full extracted text for a single attached PDF
MAX_SMALL_PDF_PAGES = 12
# Passages of its one source a cell extraction call reads. A source within MAX_CELL_PASSAGES and MAX_SMALL_PDF_CHARS is
# given whole; the other limits are test defaults, to be measured in P5 slice 5.
MAX_CELL_PASSAGES = 48
MAX_FILL_PASSAGES = 24
MAX_RECHECK_PASSAGES = 16
COLUMN_FIELDS = ("name", "instruction", "answer_format", "options", "allow_multiple", "unit_hint")
RRF_K = 60  # reciprocal rank fusion constant (D27)
# The candidate rank a chained record is written with (D95): after every keyword record, so a record a keyword query
# already found keeps the rank and the search its candidate row names.
CHAIN_RANK_BASE = 1_000_000_000
# Steps whose records are shown as short handles instead of stored identifiers, because long random IDs were
# mis-copied (D12). The abstract stage joined them in slice 09: its batches name 20 candidates each.
HANDLE_TASKS = ("grounded_answer", "answer_review", "cell_extraction", "abstract_screening",
                "fulltext_adjudication", "lineage_links") + contracts.REPORT_TASKS + contracts.CANDIDATE_TASKS + contracts.REVIEW_TASKS
FORMULATION_SCORE_THRESHOLD = 3
FORMULATION_TERMS = re.compile(
    r"\b(?:minimi[sz]e|maximi[sz]e|subject\s+to|s\.\s*t|objective\s+function|constraints?|decision\s+variables?"
    r"|mixed[-\s]integer|MILP|linear\s+program|integer\s+program|optimization\s+problem|amaç\s+fonksiyonu"
    r"|kısıt(?:ı|lar(?:ı)?)?|karar\s+değişken(?:i|leri))\b", re.IGNORECASE,
)
FORMULATION_SYMBOLS = re.compile(r"(?:<=|>=|[=≤≥∑∈∀∃∫])")
STOPWORDS = set(
    "the and for with what which how are was were from that this into about does using used use their there have has "
    "not but can our its them they than then also between within over under nasıl nedir neler olan için ile gibi veya "
    "ve bir bu şu hangi mı mi mu mü midir var yok daha çok".split()
)
RATE_LIMIT_BACKOFF_SECONDS = 1.5  # matches the provider search retry backoff in providers/common.py
# The batch stages in which one call that outlived the adapter's turn limit is sent once more instead of pausing the
# stage (slice 13e): there one slow call stopped every other call of the stage. Elsewhere a call is the stage.
TIMEOUT_RETRIED_TASKS = ("abstract_screening", "fulltext_adjudication")
# A route that did not answer, so the work it was tried for is decided by no code and is tried again (SW10, D35).
UNANSWERED_FETCH_CODES = ("fetch_timeout", "fetch_failed")
UNANSWERED_LOOKUP_STATUSES = ("timeout", "rate_limited", "failed")


def formulation_score(text: str) -> int:
    """Favor explicit optimization language and notation over narrative mentions of a model."""
    return 2 * len(FORMULATION_TERMS.findall(text)) + min(6, len(FORMULATION_SYMBOLS.findall(text)))


def fuse_rankings(*rankings: list[dict[str, Any]], k: int = RRF_K) -> list[dict[str, Any]]:
    """Reciprocal rank fusion: a passage ranked high lexically or semantically comes first (D27)."""
    scores: dict[str, float] = {}
    rows: dict[str, dict[str, Any]] = {}
    for ranking in rankings:
        for position, row in enumerate(ranking):
            scores[row["id"]] = scores.get(row["id"], 0.0) + 1 / (k + position + 1)
            rows.setdefault(row["id"], row)
    # An equal score is broken by the record identifier, never by which ranking was passed first (SW14.6).
    return sorted(rows.values(), key=lambda row: (-scores[row["id"]], row["id"]))


def extraction_column(column: dict[str, Any]) -> dict[str, Any]:
    """A table column as a StepInput shows it: the revision the model answers and its definition, never a cell value."""
    return {"column_id": column["id"], "revision": column["current_revision"], **{k: column[k] for k in COLUMN_FIELDS}}


def answer_source_order(included: list[str], facts: dict[str, tuple[bool, int]], texts: dict[str, str], terms: list[str],
                        semantic_rank: dict[str, int] | None = None) -> list[str]:
    """Order included sources for the answer step, whose input holds a limited number of passages.

    Sources the user chose come first, then sources more providers returned, then sources whose title and abstract match
    the question and search-plan terms best (BM25), then selection order. Offline on D13's three all-provider runs this
    put 6, 6 and 5 of the included known papers into the first 48, against 3, 3 and 4 in selection order (D17).
    With a semantic ranking, the BM25 rank is fused with each source's best passage rank (D27).
    """
    docs = {svid: re.findall(r"\w+", texts.get(svid, "").lower()) for svid in included}
    count = len(docs) or 1
    average = sum(map(len, docs.values())) / count or 1.0
    frequency = Counter(t for words in docs.values() for t in set(words))

    def match(svid: str) -> float:
        tf, length = Counter(docs[svid]), len(docs[svid])
        return sum(math.log(1 + (count - frequency[t] + 0.5) / (frequency[t] + 0.5)) * tf[t] * 2.2
                   / (tf[t] + 1.2 * (0.25 + 0.75 * length / average)) for t in terms if tf[t])

    position = {svid: i for i, svid in enumerate(included)}
    relevance = {s: match(s) for s in included}
    if semantic_rank is not None:
        lexical_rank = {s: i for i, s in enumerate(sorted(included, key=lambda s: (-relevance[s], position[s])))}
        relevance = {s: 1 / (61 + lexical_rank[s]) + (1 / (61 + semantic_rank[s]) if s in semantic_rank else 0.0) for s in included}
    # Selection order stays a signal (D17); the identifier only breaks what is equal down to that order (SW14.6).
    return sorted(included, key=lambda s: (not facts.get(s, (False, 0))[0], -facts.get(s, (False, 0))[1], -relevance[s], position[s], s))


def _sought_terms(vocabulary: dict[str, Any]) -> list[str]:
    """The forms of the question's own task terms, for the record of whether the criterion named what is sought.

    Both forms are given because a term enters the query as one of them and the criterion may write either.
    """
    return [form for term in vocabulary["terms"] + search_query_rules.code_terms(vocabulary)
            if term["block"] == "task" and not term["dropped"] for form in (term["phrase"], term["root"])]


def _criterion_result(output: dict[str, Any]) -> dict[str, Any] | None:
    """The stored criterion step output read back as the value the protocol is built from."""
    return output["criterion"] | {"origin": output["origin"]} if output["criterion"] else None


def turn_timed_out(result: ModelStepResult) -> bool:
    """Whether a failed call is one the adapter's turn limit cut off after it was sent.

    Read the way the Codex adapter reports it: a turn that outlived its limit comes back `failed`, with the turn's
    own status `client_timeout` as its error, and may have been delivered. The other adapters word their turn
    limits differently and are not recognised here; their timeouts pause the stage as before (slice 13e).
    """
    return (result.status == "failed" and result.error == "client_timeout"
            and result.delivery_class == "after_send_unknown")


class _ReadCutoff(Exception):
    """A model call the read window's cutoff (D258) reached before it was sent."""


class RunStopped(Exception):
    """The run ended early (pause, cancel or recorded failure); state is already persisted."""


class OptionalStepFailed(Exception):
    """An optional model step could not produce a result; the run continues without it."""

    def __init__(self, reason: str, detail: Any = None):
        super().__init__(reason)
        self.reason, self.detail = reason, detail


@dataclass(frozen=True)
class Page:
    """One page of an sw query's read; each gets its own step, search run and stored payload (slice 04c)."""

    number: int              # 0 for the first page
    cursor: str              # FIRST_PAGE or the previous page's next_cursor
    read_before: int         # records this query read on earlier pages
    known_total: int | None  # the provider total an earlier page reported
    read_limit: int          # records this effort reads per query (D88)
    rate_limit_retries: int  # times this effort waits out a 429 on this page (D88); 0 ends the read instead
    query_key: str           # the query's first step key, which its own request count is kept under (D89)
    allowance: int           # requests this query may send in this run (`page_allowance`, D89)


def page_allowance(query: dict[str, Any], effort: str, budget: dict[str, Any]) -> int:
    """Requests one sw query may send, derived before its read starts from the query and the run alone (D89).

    The query is allowed the pages its provider needs to reach the read limit (or its own reachable depth), and every
    page the bounded retries it may need: a retry is counted as a request. What a retry action adds to the run
    (`retry_provider_requests`, one per failed search it retries) is added to every query's share alike, so the page
    it sends again has room. Nothing here reads another query's count, so the share does not depend on which host
    answered first. Both figures are this research's effort (D88): a lighter effort reads fewer records per query
    and waits out fewer 429s.
    """
    read_limit = SW_READ_LIMIT[effort]
    connector = reading(query)  # the endpoint the query names pages its own way (D93)
    per_page = connector.requests_per_search * (1 + PROVIDER_WAIT[effort]) + MAX_TRANSIENT_NETWORK_RETRIES
    pages = 1 if connector.paging == "single_page" else math.ceil(
        min(read_limit, connector.max_reachable or read_limit) / connector.max_results)
    return pages * per_page + budget.get("retry_provider_requests", 0)


@dataclass
class _PageRead:
    """One page a host's task read, held until every query before its own has been written (D89)."""

    key: str                 # the page's step key
    page: Page
    outcome: SearchOutcome
    limit: int               # records asked for
    stop_reason: str | None  # decided when the page arrived
    started_at: str          # the request's own clock, which its step carries
    finished_at: str
    dispatched: facade.Dispatched | None = None
    transport: dict[str, Any] = field(default_factory=dict)


@dataclass
class _QueryRead:
    """What one sw query read in this round, in page order, and whether its read has ended (D89)."""

    index: int
    query: dict[str, Any]
    pages: list[_PageRead] = field(default_factory=list)
    allowance_ended: str | None = None  # the step key of a page not asked because the query's share was spent
    ended: bool = False


def _stop_reason(connector: Connector, outcome: SearchOutcome, ok: bool, read_total: int, read_limit: int,
                 returned_count: int | None = None) -> str | None:
    """Why this page ends the query's read, or None while another page follows."""
    if not ok:
        return "page_failed"
    if connector.paging == "single_page":
        return "single_page"
    if outcome.next_cursor is None or not (len(outcome.records) if returned_count is None else returned_count):
        # The provider has no more. An empty page ends the read even when it carries a cursor: the read total would
        # not grow, and the query would ask for empty pages until its request allowance ran out.
        return "exhausted"
    if read_total >= read_limit:
        return "read_limit"
    if connector.max_reachable is not None and read_total >= connector.max_reachable:
        return "provider_cap"
    return None


@dataclass
class _FillJob:
    key: str
    svid: str
    columns: list[dict[str, Any]]
    cell_versions: dict[str, int]


@dataclass
class _AbstractJob:
    key: str
    number: int               # the batch's place in the frozen read plan
    run_no: int               # 1 or 2: the two independent reads of that batch (K3)
    rows: list[dict[str, Any]]


@dataclass
class _AdjudicationJob:
    key: str
    head: str
    read_version: str
    run_no: int               # 1 or 2: the two independent reads of that work (D85)


@dataclass
class _Held:
    """A discovery run whose full-text fetch overlaps its screening (slice 17a, decision 4).

    While both arms run, no call under them writes a stop on the run: `_checkpoint` only reads one, and `_pause` and
    `_fail` note theirs here and stop their arm. The coordinator writes the stop once both arms have drained.
    """

    revision: int
    wake: asyncio.Event = field(default_factory=asyncio.Event)  # an abstract batch closed, or an arm ended
    halted: bool = False             # the coordinator stopped both arms
    model_done: bool = False         # the model arm finished: the final plan can be written
    stop: tuple[str, str, Any] | None = None  # ("pause" | "fail", reason, detail) a call asked for
    closed: dict[str, set[int]] = field(default_factory=dict)  # abstract batches closed in this process, by key prefix


@dataclass
class FlowDeps:
    settings: Settings
    store: Store
    adapters: dict[str, ModelAdapter]
    package: SkillPackage
    http: httpx.AsyncClient
    fetch_pdf: Callable[[str], Awaitable[fetch_module.FetchResult]] = fetch_module.fetch_pdf
    equations: Any = None  # workflow.equations.EquationService when the equation reader is set up (D52)
    limiter: ModelCallLimiter = field(default_factory=lambda: ModelCallLimiter(1))
    local_embedder: Any = None  # documents.local_embedding.LocalEmbedder: the built-in embedding model (slice 21)
    fetch_xml: Callable[[str], Awaitable[fetch_module.FetchResult]] = acquisition.fetch_xml  # Europe PMC (SW21)
    clock: fast_path.Clock | None = None
    fetch_slots: Any = None


class ResearchFlow:
    def __init__(self, deps: FlowDeps):
        self.deps = deps
        self.store = deps.store
        if getattr(deps, "clock", None) is not None:
            self.store.clock = deps.clock
        self._clock_tasks: dict[str, dict[str, tuple[str, asyncio.Task]]] = {}
        self._fast_consumers: dict[str, Any] = {}
        self._fast_chains: dict[str, Any] = {}
        self._held: dict[str, _Held] = {}
        # D258: per run, the latest time a model answer is still waited for (a fast-path read window's cutoff).
        self._send_by: dict[str, Callable[[], Any]] = {}
        self._quota_out: dict[str, set[str]] = {}
        self._openalex_budget: dict[str, acquisition.OpenAlexBudget] = {}
        from deixis.workflow.background_fetch import BackgroundFetchLane, FetchSlots
        if getattr(deps, "fetch_slots", None) is None:
            deps.fetch_slots = FetchSlots()
        self.background_fetch = BackgroundFetchLane(self)

    async def execute(self, run_id: str) -> None:
        # Resume and retry use the same flow and run ID; quota may have reset between executions.
        self._quota_out.pop(run_id, None)
        from deixis.providers.common import fast_openalex_pacing
        pacing = fast_openalex_pacing.set(fast_path.chain_on(self.store.run(run_id)["budget"]))
        try:
            await self._execute_run(run_id)
        finally:
            chain = self._fast_chains.pop(run_id, None)
            if chain is not None:
                await chain.stop()
                chain.close_open("interrupted")
            fast_openalex_pacing.reset(pacing)
            consumer = self._fast_consumers.pop(run_id, None)
            if consumer is not None:
                await consumer.stop()
            tasks = self._clock_tasks.pop(run_id, {})
            for _, task in tasks.values():
                task.cancel()
            results = await asyncio.gather(*(task for _, task in tasks.values()), return_exceptions=True)
            for result in results:
                if isinstance(result, Exception):
                    log.exception("Fast-path checkpoint task failed for run %s", run_id,
                                  exc_info=(type(result), result, result.__traceback__))
            with transaction(self.store.conn):
                run = self.store.run(run_id)
                if fast_path.enabled(run["budget"]) and run["status"] not in ("running", "pause_requested"):
                    fast_path.close_run(self.store, run_id, "paused" if run["status"] == "paused" else "stopped")
            if run["kind"] == "kill_search":
                from deixis.workflow.candidates.store import CandidateStore
                CandidateStore(self.store).sync_search_outcome(run_id)

    def _enter_clock_stage(self, run: dict[str, Any], stage: str) -> None:
        interval_id = fast_path.enter_stage(self.store, run, stage)
        if interval_id is None:
            return
        tasks = self._clock_tasks.setdefault(run["id"], {})
        if interval_id not in tasks:
            tasks[interval_id] = (stage, asyncio.create_task(self._clock_checkpoint(interval_id)))

    async def _clock_checkpoint(self, interval_id: str) -> None:
        while self.store.conn.execute(
                "SELECT 1 FROM fast_path_intervals WHERE id = ? AND closed_at IS NULL", (interval_id,)).fetchone():
            await self.store.clock.sleep(5)
            fast_path.checkpoint(self.store, interval_id)

    def _close_clock_stage(self, run: dict[str, Any], stage: str) -> None:
        if not fast_path.enabled(run["budget"]):
            return
        fast_path.close_stage(self.store, run["id"], stage)
        for name, task in self._clock_tasks.get(run["id"], {}).values():
            if name == stage:
                task.cancel()

    def _openalex_budget_of(self, run_id: str) -> acquisition.OpenAlexBudget:
        """The run's memory of OpenAlex's daily budget, brought up to date with the store at every lookup: a resumed or
        restarted run, a later run, and a run another run's refusal has overtaken do not send what a refusal that
        has not yet reset says cannot be served."""
        budget = self._openalex_budget.setdefault(run_id, acquisition.OpenAlexBudget())
        stored = self.store.openalex_budget_reset()
        if stored and (budget.reset_at is None or stored > budget.reset_at):
            budget.reset_at = stored
        return budget

    async def _execute_run(self, run_id: str) -> None:
        run = self.store.run(run_id)
        self.store._guard_legacy_run(run)
        scope = {} if run["kind"] == "review" else self.store.scope(run["research_id"], run["scope_revision"])
        try:
            if run["kind"] == "discovery":
                await self._discovery(run, scope)
            elif run["kind"] == "answer":
                await self._answer(run, scope)
            elif run["kind"] == "answer_review":
                from deixis.workflow import fast_answer
                await fast_answer.review(self, run, scope)
            elif run["kind"] == "pdf_collection":
                await self._inspect(run, limit=None)
            elif run["kind"] == "fulltext_adjudication":
                from deixis.workflow import late_revision
                late = late_revision.row_for_run(self.store, run)
                if late:
                    self._checkpoint(run_id, run["scope_revision"])
                    await self._fulltext_adjudication(run, scope, batch_key=f"late:{late['ledger_run_id']}",
                        order=run["target"]["heads"], read_limit=run["budget"]["max_fulltext_reads"])
                    self._checkpoint(run_id, run["scope_revision"])
                else:
                    await self._fulltext_adjudication(run, scope)
            elif run["kind"] == "pdf_ocr":
                await self._pdf_ocr(run)
            elif run["kind"] == "table_fill":
                await self._table_fill(run, scope)
            elif run["kind"] == "lineage_links":
                await self._lineage_links(run, scope)
                self._lineage_send_gate(run)
            elif run["kind"] == "cell_recheck":
                await self._cell_recheck(run, scope)
            elif run["kind"] == "research_title":
                await self._research_title(run, scope)
            elif run["kind"] == "report":
                await self._report(run, scope)
            elif run["kind"] == "claim_decomposition":
                await self._claim_decomposition(run, scope)
                self._candidate_send_gate(run)
            elif run["kind"] == "kill_search":
                await self._kill_search(run, scope)
                self._candidate_send_gate(run)
            elif run["kind"] == "review":
                await self._owner_review(run)
            elif run["kind"] == "watch_check":
                await self._watch_check(run)
            elif run["kind"] == "table_columns":
                await self._table_columns(run, scope)
            else:
                self._fail(run_id, "unknown_run_kind", {"kind": run["kind"]})
        except RunStopped:
            return
        if (self.store.run(run_id)["status"] in ("running", "pause_requested")
                and run["kind"] == "discovery" and small_batch.enabled(run["budget"])):
            with transaction(self.store.conn):
                self.store.update_run(run_id, event="run_completed", status="completed", pause_reason=None)
                if fast_path.enforces(run["budget"], "answer"):
                    from deixis.workflow import fast_answer
                    fast_answer.auto_answer(self.store, run)
        elif self.store.run(run_id)["status"] in ("running", "pause_requested"):
            if ((run["kind"] == "answer" and fast_path.enforces(run["budget"], "answer"))
                    or run["kind"] == "answer_review"):
                from deixis.workflow import fast_answer
                with transaction(self.store.conn):
                    self.store.update_run(run_id, event="run_completed", status="completed", pause_reason=None)
                    if run["kind"] == "answer":
                        fast_answer.after_answer(self, run)
                    elif (self.deps.settings.study_table == "auto"
                          and self.store.run(run["target"]["answer_run_id"])["budget"].get("trigger") != "late_fulltext"):
                        report_pipeline.after_answer(self.store, self.store.run(run["target"]["answer_run_id"]))
                return
            # Nothing is left to pause once the last step's result has been applied. A person's file this run held
            # and did not read is `unread` from the same write (`Store.update_run`, slice 18b).
            self.store.update_run(run_id, event="run_completed", status="completed", pause_reason=None)
            if run["kind"] == "answer" and self.deps.settings.study_table == "auto":
                report_pipeline.after_answer(self.store, run)  # the study table follows a valid answer, once per answer
            elif run["kind"] in ("table_columns", "table_fill"):
                report_pipeline.continue_after(self.store, run)  # the study table's chain; other runs pass

    # ---- run control ---------------------------------------------------------------
    def _checkpoint(self, run_id: str, scope_revision: int | None = None) -> None:
        guard = getattr(self, "_small_batch_guard", None)
        if guard and guard.get("late_revision"):
            from deixis.workflow import late_revision
            late_revision.checkpoint(self, self.store.run(run_id))
        if guard and guard["run_id"] == run_id:
            changed = small_batch.guard_reason(self.store, guard)
            if changed:
                self._pause(run_id, changed)
            if guard.get("fast_answer"):
                from deixis.workflow import fast_answer
                fast_answer.check_input(self, run_id, guard["input"])
        # getattr: existing tests build the flow with object.__new__ and call the embedding steps, which now checkpoint.
        held = getattr(self, "_held", {}).get(run_id)
        if held is not None:
            # Inside the overlap a call only reads the stop; the coordinator writes it once both arms have drained.
            if self._stop_requested(run_id, held.revision):
                raise RunStopped
            return
        run = self.store.run(run_id)
        if (run.get("target") or {}).get("late_revision_id") or run["budget"].get("late_revision_id"):
            from deixis.workflow import late_revision
            late_revision.checkpoint(self, run)
        if run["status"] == "pause_requested":
            self.store.update_run(run_id, event="run_paused", status="paused", pause_reason="user_requested")
            raise RunStopped
        if run["status"] in ("cancelled", "paused", "failed"):
            raise RunStopped
        if scope_revision is not None and self.store.research(run["research_id"])["current_scope_revision"] != scope_revision:
            # Results of an older question revision stay recorded under this run but are not applied.
            self.store.update_run(run_id, event="run_cancelled", status="cancelled", pause_reason="scope_revised")
            raise RunStopped
        if guard and guard["run_id"] == run_id and guard.get("halted"):
            raise RunStopped

    def _pause(self, run_id: str, reason: str, detail: Any = None) -> None:
        if self._hold(run_id, "pause", reason, detail):
            raise RunStopped
        if self.store.run(run_id)["status"] == "cancelled":
            raise RunStopped
        self.store.update_run(run_id, event="run_paused", status="paused", pause_reason=reason, error_json=detail)
        raise RunStopped

    def _fail(self, run_id: str, reason: str, detail: Any = None) -> None:
        if self._hold(run_id, "fail", reason, detail):
            raise RunStopped
        self.store.update_run(run_id, event="run_failed", status="failed", pause_reason=reason, error_json=detail)
        raise RunStopped

    def _hold(self, run_id: str, kind: str, reason: str, detail: Any) -> bool:
        """Note a pause or failure a call under the overlap asked for, and stop both arms; False outside it."""
        held = self._held.get(run_id)
        if held is None:
            return False
        held.stop = held.stop or (kind, reason, detail)
        held.halted = True
        held.wake.set()
        return True

    # ---- discovery -----------------------------------------------------------------
    async def _discovery(self, run: dict[str, Any], scope: dict[str, Any]) -> None:
        run_id, rid, revision = run["id"], run["research_id"], run["scope_revision"]
        if scope["source_scope"] == "attached":
            return
        from deixis.workflow import fast_search
        use_fast_search = fast_search.applicable(self.store, run)
        self._enter_clock_stage(run, "plan")
        if use_fast_search:
            from deixis.workflow.fast_embedding import Consumer
            self._fast_consumers[run_id] = Consumer(self, run, scope)
        self._checkpoint(run_id, revision)
        if scope["seed_mode"] == "uploaded_seed" and self.store.seed_status(rid, scope) != "ready":
            self._pause(run_id, "seed_unavailable")
        vocabulary = criterion = approval = None
        # The first search's words come from code, so no model runs before the search (SW2.3).
        vocabulary, queries = await self._vocabulary(run, scope)
        vocabulary, queries = await self._search_query(run, scope, vocabulary, queries)
        vocabulary, queries = await self._source_routing(run, scope, vocabulary, queries)
        criterion = await self._criterion(run, scope, vocabulary)
        vocabulary, queries, criterion, approval = await self._approval(run, scope, vocabulary, queries, criterion)
        # The protocol is frozen before the first provider request and every step opened after it carries its hash (SW14.1).
        protocol_step = self.store.step(run_id, "protocol", "protocol:freeze")
        if protocol_step["status"] != "succeeded":
            self.store.start_step(protocol_step["id"])
            # A later discovery run of the same scope revision may plan other queries; that is a new protocol revision
            # with its reason, never an edit of the first one (SW14.2).
            reason = "later_discovery_run" if self.store.current_protocol(rid, revision) else None
            fast_plan = None
            if use_fast_search:
                fast_plan = fast_search.build_plan(self.store, run, scope, queries)
            record = self.store.freeze_protocol(rid, revision, protocol.build_protocol(
                scope, run["budget"], None, queries,
                self.deps.package.package_hash, self.deps.settings, vocabulary=vocabulary, criterion=criterion,
                approval=approval, embedding_model=self._embedding_model(), routing=self._routing(run_id),
                fast_path_search=fast_plan,
            ), reason=reason)
            self.store.finish_step(protocol_step["id"], "succeeded",
                                   output={"protocol_revision": record["protocol_revision"], "protocol_hash": record["hash"]})

        self._close_clock_stage(run, "plan")
        self._enter_clock_stage(run, "search")

        # A failed search is recorded and shown, and the other searches go on (D18). The run pauses on a failure only when
        # none of its searches succeeded; resuming it then retries the failed searches.
        def searched() -> bool:
            return any(s["kind"].startswith("provider_search") and s["status"] == "succeeded" for s in self.store.run_steps(run_id))

        # A deliberate retry action reuses the stored plan and retries only failed provider searches. A normal resume
        # retries failures only when the whole search stage had no successful query (D18).
        retry_failed = bool(run["budget"].get("retry_failed_searches_only")) or not searched()
        failure = None
        # Each query is read page by page up to its effort's read limit.
        effort = scope["effort"]
        self._checkpoint(run_id, revision)
        if use_fast_search:
            if fast_path.chain_on(run["budget"]):
                from deixis.workflow.fast_chain import Round
                self._fast_chains[run_id] = Round(self, run, scope, vocabulary)
            self._fast_consumers[run_id].start()
            failure = await fast_search.execute(self, run, scope, fast_search.stored_plan(self.store, run), retry_failed)
        else:
            failure = await self._search_round(run, list(enumerate(queries)), retry_failed, effort)
        if failure and not searched():
            self._pause(run_id, *failure)
        if not searched() and self._allowance_ended_searches(run_id):
            # No search succeeded and none failed: every query's share was spent before it asked (a run resumed after
            # a crash). Going on would screen a round that searched nothing (D18); asked to search again, the retry
            # adds to every query's share (review of 13f, 2026-09-23).
            self._pause(run_id, "budget_exhausted", {"limit": "query_requests"})
        # Expansion reads the first round's records and searches only additional phrases.
        if use_fast_search:
            self._close_clock_stage(run, "search")
            if fast_path.chain_on(run["budget"]):
                self._enter_clock_stage(run, "ranking")
                self._fast_chains[run_id].fallback()
                self._fast_chains[run_id].admit.set()
            else:
                self._enter_clock_stage(run, "lookups")
                await self._second_sources(run, scope, vocabulary)
                self._close_clock_stage(run, "lookups")
        else:
            more = await self._expansion(run, scope, vocabulary, queries, criterion, approval)
            await self._search_round(run, list(enumerate(more, start=len(queries))), retry_failed, effort)
            await self._second_sources(run, scope, vocabulary)
            self._close_clock_stage(run, "search")

        self._checkpoint(run_id, revision)
        # A work is screened once, through its head; its other versions follow the head's selection (D46, D48).
        heads = set(self.store.work_heads(rid).values())
        pool = [c for c in self.store.candidates(rid, revision)
                if c["origin"] != "user" and c["source_version_id"] in heads]
        # Rank the full pool before deciding which abstracts to read.
        self._enter_clock_stage(run, "ranking")
        if use_fast_search:
            await self._fast_consumers[run_id].drain(pool)
        await self._source_similarity(run, scope, pool)
        await self._ranking(run, scope, vocabulary)
        read_enforced = fast_path.enforces(run["budget"], "read")
        if not read_enforced:
            self._close_clock_stage(run, "ranking")
        self.store.update_run(run_id, stage="screening")
        if not read_enforced:
            self._enter_clock_stage(run, "read")
        await small_batch.execute(self, run, scope, vocabulary)
        if not read_enforced:
            self._close_clock_stage(run, "read")

        # Derive a short title from the question and the included sources once screening is done. A structurally valid
        # answer later replaces it (store.save_answer). Optional: the run continues with the provisional title on failure.
        if self.store.included_works(rid):
            try:
                await self._research_title(run, scope, optional=True)
            except OptionalStepFailed:
                return


    async def _second_sources(self, run: dict[str, Any], scope: dict[str, Any],
                              vocabulary: dict[str, Any] | None, *, only: set[str] | None = None) -> None:
        """The three code steps of slice 05 (SW5, SW9.3).

        No model is called and no selection is written here. A failed lookup is recorded on the record and the run
        carries on (D18); a resumed run reads the stored plan and asks nothing twice. Which records stay away from
        the model is no longer read here: since slice 09 the abstract stage's own read plan decides that, and
        `lookups.held_from_screening` is what `record_flags` counts with.
        """
        run_id, revision = run["id"], run["scope_revision"]
        words, _ = lookups.title_words(vocabulary)
        await lookups.ask_second_sources(self.store, self.deps.http, self.deps.settings, run, scope, words,
                                         lambda: self._checkpoint(run_id, revision), **({"only": only} if only is not None else {}))
        lookups.external_links(self.store, run)
        lookups.flag_and_decide(self.store, run, scope, words)

    def _count_probe(self, scope: dict[str, Any], run_id: str) -> Callable[[str], Awaitable[int | None]]:
        """The count request the vocabulary step probes with, or one that answers "unknown" without asking.

        OpenAlex is the count backbone (SW3.1). Out of scope or without the access it needs, no count is read and
        every term enters the query as its whole phrase; nothing is substituted for it.
        """
        connector = CONNECTORS["openalex"]
        if "openalex" not in scope["providers"] or connector.access_mode() == "not_configured":
            async def unavailable(query: str) -> int | None:
                return None
            return unavailable

        async def probe(query: str) -> int | None:
            if connector.provider_id in self._quota_out.get(run_id, set()):
                return None
            return await openalex.count_works(self.deps.http, query, api_key=connector.api_key(),
                                              mailto=self.deps.settings.contact_email)
        return probe

    async def _vocabulary(self, run: dict[str, Any], scope: dict[str, Any]) -> tuple[dict[str, Any], list[dict[str, Any]]]:
        """The sw workflow's search words and queries, taken from the question by code (SW2).

        A step that already succeeded returns its stored output whole, so a resumed run sends no count request twice
        and searches exactly the queries the first run compiled.
        """
        run_id, revision, budget = run["id"], run["scope_revision"], run["budget"]
        step = self.store.step(run_id, "vocabulary", "code:vocabulary")
        if step["status"] == "succeeded":
            stored = step["output"]
            return self._code_proposed(run_id, stored["vocabulary"], stored["queries"])
        try:
            extraction = question_words.extract(scope["question"], scope.get("language_hint"), scope.get("key_terms"))
        except ValueError as exc:
            self._pause(run_id, "key_terms_needed", {"error": str(exc)})
        if extraction is None:
            # Code does not translate. The run waits for the user's English terms in a new scope revision (SW2.1).
            self._pause(run_id, "key_terms_needed", {"language": scope.get("language_hint") or "other"})
        extraction, labelling = await self._vocabulary_labels(run, scope, extraction)
        self.store.start_step(step["id"])
        built = await vocabulary_rules.build_vocabulary(extraction, self._count_probe(scope, run_id))
        built["labelling"] = labelling
        self._checkpoint(run_id, revision)
        queries = query_compiler.compile_block_queries(built, scope["providers"], budget["max_provider_requests"])
        self.store.finish_step(step["id"], "succeeded", output={
            "vocabulary": built, "queries": queries, "query_compiler": query_compiler.BLOCKS_VERSION})
        # The counts are stored before the run stops, so resuming re-reads them instead of paying for them again.
        return self._code_proposed(run_id, built, queries)

    def _code_proposed(self, run_id: str, built: dict[str, Any], queries: list[dict[str, Any]]
                       ) -> tuple[dict[str, Any], list[dict[str, Any]]]:
        """The code vocabulary as the step left it. Where a model writes the query, a code query that cannot be
        searched does not stop the run here: it is left out beside the model's, or stops the run later if the user
        chooses it alone (D92)."""
        if self.deps.settings.search_query == "model":
            return built, queries
        return self._proposed(run_id, built, queries)

    async def _search_query(self, run: dict[str, Any], scope: dict[str, Any], code_vocabulary: dict[str, Any],
                            code_queries: list[dict[str, Any]]) -> tuple[dict[str, Any], list[dict[str, Any]]]:
        """The model-written query and the code's beside it, or the code's alone where no model writes one (D92).

        One call per scope revision, with the one repair `_model_step` allows; nothing is voted on. A call that fails,
        or an answer that leaves a block with no term after the counts, stops the run with `search_query_failed`: the
        code's query is never searched in its place without the user saying so. Resuming asks the model once more
        (`ATTEMPTS`); the user's other way out is to search with the code's query alone, which the route writes on
        this step. A step that already succeeded returns its stored vocabulary and queries, so a resumed run calls
        no model and reads no count twice, and a second discovery run of the same scope revision takes the query the
        first one wrote.

        The setting is read when the step is first written: a run already stopped for the model's query stays on it
        after the service is restarted with `search_query=code`, so its resume never searches the code's query alone.
        """
        run_id, rid, revision = run["id"], run["research_id"], run["scope_revision"]
        step = self.store.existing_step(run_id, "search_query")
        if step is None and self.deps.settings.search_query != "model":
            return code_vocabulary, code_queries
        step = step or self.store.step(run_id, "search_query", "code:search_query")
        if step["status"] == "succeeded":
            stored = step["output"]
            return self._proposed(run_id, search_query_rules.settled(stored["vocabulary"], stored["queries"]),
                                  stored["queries"])
        earlier = self.store.search_query_of(rid, revision, run_id) if step["output"] is None else None
        if earlier is not None:
            # D92 is one call per scope revision: the query the user already saw is searched again, and the approval
            # the earlier run closed is reapplied to that same query, never to one the user has not seen.
            output = earlier["output"] | {"reused_from_run": earlier["output"].get("reused_from_run", earlier["run_id"])}
            self.store.start_step(step["id"])
            self.store.finish_step(step["id"], "succeeded", output=output)
            return self._proposed(run_id, search_query_rules.settled(output["vocabulary"], output["queries"]),
                                  output["queries"])
        if code_vocabulary["block_assignment"] == "user":
            # The user's own key terms are above any proposal (SW2.6): the model is not asked to write another.
            self.store.start_step(step["id"])
            self.store.finish_step(step["id"], "succeeded", output={
                "status": "skipped", "reason": "user_key_terms", "vocabulary": code_vocabulary, "queries": code_queries})
            return self._proposed(run_id, code_vocabulary, code_queries)
        output = step["output"] or {"attempts": [], "choice": None}
        if output.get("choice") == "code_only":
            # The user chose the code's query after the model's failed; the vocabulary says so wherever it is read.
            chosen = code_vocabulary | {"search_query": {"status": "failed", "choice": "code_only",
                                                         "attempts": output["attempts"]}}
            self.store.start_step(step["id"])
            self.store.finish_step(step["id"], "succeeded", output=output | {
                "status": "code_only", "vocabulary": chosen, "queries": code_queries})
            return self._proposed(run_id, chosen, code_queries)
        # A call whose failure its model step stored, but whose attempt the worker did not live to write here, is
        # counted now rather than sent again: the attempt bound counts calls sent, not attempts written.
        while ((sent := self.store.existing_step(run_id, f"search_query:{len(output['attempts']) + 1}"))
               and sent["status"] in ("failed", "outcome_unknown")):
            output["attempts"].append(self._query_attempt(run_id, len(output["attempts"]) + 1, {
                "reason": sent["error_code"] or "model_call_failed",
                "detail": json.loads(sent["error_json"]) if sent["error_json"] else None}))
            self.store.set_step_output(step["id"], output)
        attempt = len(output["attempts"]) + 1
        if attempt > search_query_rules.ATTEMPTS:
            self._pause(run_id, "search_query_failed", {"attempts": output["attempts"], "retries_left": 0})
        self._checkpoint(run_id, revision)
        failure: dict[str, Any] | None = None
        try:
            answer = await self._model_step(run, scope, f"search_query:{attempt}", "search_query", optional=True)
        except OptionalStepFailed as exc:
            failure = {"reason": exc.reason, "detail": exc.detail}
        else:
            if answer.get("invalid"):
                failure = {"reason": "invalid_model_output", "detail": answer["issues"]}
        self._checkpoint(run_id, revision)
        if failure is None:
            # The counts are written on the step as soon as they are read, so a worker that dies before the step
            # closes reads them back instead of asking OpenAlex again (the model step itself is already stored).
            stored = output.get("checked")
            if stored is not None and stored["attempt"] == attempt:
                checked = stored["result"]
            else:
                checked = await search_query_rules.check(answer["result"], self._count_probe(scope, run_id))
                output["checked"] = {"attempt": attempt, "result": checked}
                self.store.set_step_output(step["id"], output)
            if not checked["searchable"]:
                failure = {"reason": "no_searchable_term", "detail": checked["checks"]}
        if failure is not None:
            # Written on the step, which is never started: a step still `pending` is not half-finished work.
            output["attempts"].append(self._query_attempt(run_id, attempt, failure))
            self.store.set_step_output(step["id"], output)
            self._pause(run_id, "search_query_failed", {
                "reason": failure["reason"], "retries_left": search_query_rules.ATTEMPTS - attempt})
        record = {"status": "ready", "attempts": output["attempts"] + [{"attempt": attempt, "reason": None}],
                  "step_input_id": answer["step_input_id"], "resolved_model": answer["resolved_model"],
                  # The package the model was sent, from its stored StepInput: the body is frozen later, perhaps
                  # under a newer package, and must not credit the answer to that one.
                  "skill_package_hash": self.store.step_input_payload(answer["step_input_id"])["skill_package_hash"],
                  "answer": answer["result"]}
        built = search_query_rules.vocabulary(code_vocabulary, code_queries, checked, record)
        queries = search_query_rules.compile_queries(built, scope["providers"], run["budget"]["max_provider_requests"])
        built = search_query_rules.with_compiled(built, queries)
        self.store.start_step(step["id"])
        self.store.finish_step(step["id"], "succeeded", output=output | {
            "status": "ready", "vocabulary": built, "queries": queries,
            "query_compiler": query_compiler.BLOCKS_VERSION})
        return self._proposed(run_id, built, queries)

    def _query_attempt(self, run_id: str, attempt: int, failure: dict[str, Any]) -> dict[str, Any]:
        """A failed search_query call as the protocol keeps it: the StepInput and the package it was sent, when one
        was sent at all (a connection that was not ready sent nothing)."""
        call = self.store.existing_step(run_id, f"search_query:{attempt}")
        sent = self.store.last_step_input(call["id"]) if call else None
        return {"attempt": attempt, **failure, "step_input_id": sent["id"] if sent else None,
                "skill_package_hash": sent["skill_package_hash"] if sent else None}

    def _proposed(self, run_id: str, built: dict[str, Any], queries: list[dict[str, Any]]) -> tuple[dict[str, Any], list[dict[str, Any]]]:
        """A vocabulary that cannot be searched stops an unattended run here. A run that asks for the approval takes
        it to the user instead: removing or adding a term is how it becomes searchable, and `_approval` checks what
        the user approved before anything is frozen."""
        if self.deps.settings.protocol_approval in ("ask", "warn"):
            return built, queries
        return self._searchable(run_id, built, queries)

    async def _optional_calls(self, run: dict[str, Any], keys: list[str],
                              call: Callable[[str], Awaitable[dict[str, Any]]]) -> list[dict[str, Any] | OptionalStepFailed]:
        """Send the repeated runs of one optional step at once, through the run's limiter, and return them in key order.

        A run that failed comes back as its OptionalStepFailed. A pause, cancel or newer revision is checked before the
        calls go out and by each call before it sends; the first such stop is raised once every call has returned.
        """
        self._checkpoint(run["id"], run["scope_revision"])

        async def one(key: str) -> dict[str, Any] | OptionalStepFailed:
            try:
                return await self.deps.limiter.run(f"{run['id']}:{key}", lambda: call(key))
            except OptionalStepFailed as failure:
                return failure

        results = await asyncio.gather(*(one(key) for key in keys), return_exceptions=True)
        stop = next((result for result in results if isinstance(result, BaseException)
                     and not isinstance(result, OptionalStepFailed)), None)
        if stop is not None:
            raise stop
        return results

    async def _vocabulary_labels(self, run: dict[str, Any], scope: dict[str, Any],
                                 extraction: Extraction) -> tuple[Extraction, dict[str, Any]]:
        """Ask a model which block each extracted phrase belongs to, and keep the rule wherever it does not answer (SW17).

        Three optional calls: a failed one is recorded and the run goes on, and with too few of them the rule's own
        assignment stands, so a search never waits for a model. A call whose step already succeeded returns its stored
        output, so a resumed run labels nothing twice.
        """
        run_id, revision = run["id"], run["scope_revision"]
        phrases = vocabulary_rules.labelling_phrases(extraction)
        skipped = ("user_key_terms" if extraction.block_assignment == "user" else
                   "no_phrases" if not phrases else
                   "too_many_phrases" if len(phrases) > vocabulary_rules.MAX_LABELLED_PHRASES else None)
        if skipped:
            # The user's own key terms are above both assignments (SW2.6), and a list this long is not sent at all.
            return extraction, {"runs_ok": 0, "skipped": skipped, "failures": [], "phrases": []}
        target = {"question_text": scope["question"], "language": extraction.language, "phrases": phrases}
        runs: list[dict[str, str]] = []
        failures: list[dict[str, Any]] = []
        keys = [f"vocabulary_labels_{index + 1}" for index in range(vocabulary_rules.LABEL_RUNS)]
        outputs = await self._optional_calls(run, keys, lambda key: self._model_step(
            run, scope, key, "vocabulary_labels", optional=True, vocabulary_target=target))
        for key, output in zip(keys, outputs):
            if isinstance(output, OptionalStepFailed):
                failures.append({"step": key, "reason": output.reason})
                continue
            if output.get("invalid"):
                # An invented, missing or repeated phrase drops this run; it is not repaired and not half-applied.
                failures.append({"step": key, "reason": "invalid_model_output"})
                continue
            runs.append({label["phrase"]: label["block"] for label in output["result"]["labels"]})
        self._checkpoint(run_id, revision)
        labelled, records = vocabulary_rules.apply_labels(extraction, runs)
        # Enough runs arrived and the rule still stands: the labelling left nothing to search with (apply_labels).
        fallback = ("labelling_unsearchable" if len(runs) >= vocabulary_rules.LABEL_MAJORITY
                    and labelled.block_assignment != "model" else None)
        return labelled, {"runs_ok": len(runs), "skipped": None, "fallback": fallback, "failures": failures, "phrases": records}

    async def _criterion(self, run: dict[str, Any], scope: dict[str, Any],
                         vocabulary: dict[str, Any]) -> dict[str, Any] | None:
        """The inclusion criterion, its parts and cue phrases, proposed from the question alone (SW15.1, SW15.2).

        Three optional calls, and nothing one of them said on its own is used: `consensus` keeps the phrases at least
        two runs wrote and returns nothing at all below two valid runs. A failed call is recorded and the run goes on,
        so a search never waits for a model. A criterion this research already froze for the same question and
        steering is taken back unchanged instead of asked again: the same criterion in other words would mark every
        decision made under the old one stale (SW11.10).

        The step is `succeeded` even when no criterion could be built, so a resumed run does not call the model again;
        a later discovery run of the same scope asks afresh, because it has no frozen criterion to read.
        """
        run_id, rid, revision = run["id"], run["research_id"], run["scope_revision"]
        step = self.store.step(run_id, "criterion", "code:criterion")
        if step["status"] == "succeeded":
            return _criterion_result(step["output"])
        self.store.start_step(step["id"])
        frozen = self.store.frozen_criterion(rid, scope["question"], scope.get("steering"))
        if frozen is not None:
            taken = frozen.pop("protocol_revision")  # where it was read from; the criterion fields stay as they were
            output = {"origin": "protocol", "criterion": frozen, "protocol_revision": taken, "failures": []}
        else:
            runs: dict[int, dict[str, Any]] = {}
            failures: list[dict[str, Any]] = []
            keys = [f"criterion_proposal_{index + 1}" for index in range(criterion_rules.PROPOSAL_RUNS)]
            proposals = await self._optional_calls(run, keys, lambda key: self._model_step(
                run, scope, key, "criterion_proposal", optional=True))
            for index, (key, proposal) in enumerate(zip(keys, proposals)):
                if isinstance(proposal, OptionalStepFailed):
                    failures.append({"step": key, "reason": proposal.reason})
                    continue
                if proposal.get("invalid"):
                    # A proposal that broke a bound of the contract is dropped whole; a half-used one would enter
                    # the vote with parts or phrases the step was not allowed to write.
                    failures.append({"step": key, "reason": "invalid_model_output"})
                    continue
                runs[index + 1] = proposal["result"]
            self._checkpoint(run_id, revision)
            agreed = criterion_rules.consensus(scope["question"], runs, _sought_terms(vocabulary))
            output = {"origin": "model" if agreed else None, "criterion": agreed,
                      "protocol_revision": None, "failures": failures}
        self.store.finish_step(step["id"], "succeeded", output=output)
        return _criterion_result(output)

    async def _approval(self, run: dict[str, Any], scope: dict[str, Any], vocabulary: dict[str, Any],
                        queries: list[dict[str, Any]], criterion: dict[str, Any] | None
                        ) -> tuple[dict[str, Any], list[dict[str, Any]], dict[str, Any] | None, dict[str, Any]]:
        """Stop the run until the user has approved or corrected what it would search under (SW2.6, SW15.3).

        Everything before this point is code and count probes; nothing has been searched and no protocol has been
        frozen, so this is the last place a correction is free. A step that already succeeded returns the approved
        vocabulary, queries and criterion, so a resumed run asks nothing again and probes nothing again.

        The user is asked once per question, steering and key terms. A second discovery run of the same scope, and a
        revision that changed only the providers, reapply the corrections the user already made; a revision that
        changed what was asked about asks again.
        """
        run_id, rid, revision = run["id"], run["research_id"], run["scope_revision"]
        step = self.store.step(run_id, "protocol_approval", "code:protocol_approval")
        unattended = (fast_path.enforces(run["budget"], "answer")
                      and run["budget"]["fast_path"].get("approval_mode") == "unattended")
        if step["status"] == "succeeded":
            approved = step["output"]["approved"]
            return (search_query_rules.settled(approved["vocabulary"], approved["queries"]), approved["queries"],
                    approved["criterion"], step["output"]["approval"])
        asked_for = {"question": scope["question"], "steering": scope.get("steering"),
                     "key_terms": scope.get("key_terms")}
        # The newest approval this research closed for the same question, steering and key terms. It is both what a
        # correction is reapplied from and what a re-asked card takes its suggestions back from.
        # A run that went on because nothing was wrong (`no_warning`), or kept every warned term (`warn_kept`, D233;
        # `model_advice` is the same run before D233), asked nobody: it is no approval to take back.
        earlier = next((row for row in self.store.approvals_of(rid)
                        if row["output"]["asked_for"] == asked_for
                        and (row["output"].get("approval") or {}).get("approved_by") not in ("no_warning", "warn_kept", "model_advice", "unattended")), None)
        output = step["output"]
        if output is None:
            failures = (self.store.step(run_id, "criterion", "code:criterion")["output"] or {}).get("failures", [])
            output = {"proposal": {"vocabulary": vocabulary, "queries": queries, "criterion": criterion,
                                   "criterion_failures": failures,
                                   **({"routing": routing} if (routing := self._routing_step(run_id)) else {})},
                      "proposal_hash": approval_rules.proposal_hash(vocabulary, criterion),
                      "asked_for": asked_for, "submitted": None, "suggestion_requests": 0}
            # The model is not asked twice for the same thing (SW2.6): an earlier approval's suggestions are carried
            # over, so a card the user is shown again for the same question has them without a new call.
            # They are judged again against this proposal, whose phrases need not be the earlier one's. An answer
            # that proposed nothing is carried too: it is an answer, and asking again would be the second call.
            if (carried := (earlier or {}).get("output", {}).get("suggestions")) is not None:
                output["carried_suggestions"] = {"terms": suggestion_rules.carry(vocabulary, carried),
                                                 "from_step_id": earlier["id"]}
            # Written before the run can stop, and never started: a step that is still `pending` is not half-finished
            # work the worker's recovery has to guess about.
            self.store.set_step_output(step["id"], output)

        if "warnings" not in output and self.deps.settings.protocol_approval != "as_proposed" and not unattended:
            # Read once and stored, with every count it asked (a card stored before the check existed has neither):
            # a resumed run reads them back and probes nothing again, and each count is written as it arrives.
            def save(checks: list[dict[str, Any]]) -> None:
                self.store.set_step_output(step["id"], output | {"warning_checks": checks})
            found, checks = await approval_rules.inflating_terms(
                output["proposal"]["vocabulary"], self._count_probe(scope, run_id), output.get("warning_checks"), save)
            output = output | {"warnings": found, "warning_checks": checks}
            self.store.set_step_output(step["id"], output)

        if output.get("warnings") and "advice" not in output and output["submitted"] is None and earlier is None and not unattended:
            connection, requested, _ = step_model(scope, "term_advice")
            output = output | {"advice": await self._term_advice(run, scope, output),
                               "advice_model": {"connection": connection, "model": requested}}
            self.store.set_step_output(step["id"], output)

        requests = output.get("suggestion_requests") or 0
        if requests and self.store.step(run_id, f"term_suggestions:{requests}",
                                        "code:term_suggestions")["status"] != "succeeded":
            # The user pressed the button. The model runs here, in the worker, and the run comes back to the card in
            # every case: a run that asked for other names never approves on the submission it asked from.
            await self._term_suggestions(run, scope, vocabulary, requests)
            self._pause(run_id, "protocol_approval_needed", {"proposal_hash": output["proposal_hash"]})
        # An earlier approval covers the criterion only when this run took it back from the protocol that approval
        # froze. One the model proposed for this run — the earlier run's model was down, so the user approved none —
        # has been seen by nobody, and the user is asked again (SW15.3).
        proposed_now = (self.store.step(run_id, "criterion", "code:criterion")["output"] or {}).get("origin") == "model"
        if criterion is not None and proposed_now and not unattended:
            earlier = None
        if output["submitted"] is not None:
            edits, source, by = output["submitted"], "submitted", "user"
        elif earlier is not None:
            # Only the term operations are reapplied. The criterion this run holds already came back from the
            # protocol the earlier approval froze, so correcting it a second time would rewrite what was agreed.
            done = earlier["output"]["edits"]
            edits, source, by = ({"terms": done["terms"], "criterion": None, "note": done.get("note"),
                                  "code_query": done.get("code_query")}, "earlier", "earlier_approval")
        elif unattended:
            edits, source, by = {"terms": [], "criterion": None, "note": None}, "unattended", "unattended"
        elif self.deps.settings.protocol_approval == "as_proposed":
            # A run nobody attends: the proposal is approved as it stands and the protocol says so by name, so a body
            # approved by a setting is never read as a body a user approved.
            edits, source, by = {"terms": [], "criterion": None, "note": None}, "setting", "setting"
        elif self.deps.settings.protocol_approval == "warn" and output.get("warnings"):
            # The model's advice, when it gave any, is information only (D233): every warned term is kept and the run
            # goes on, with no card and no pause, also when the advice call failed. Nobody is asked, and the protocol
            # says so, so this body is never read as one a person approved.
            advice_rows = approval_rules.advice_rows(output["warnings"], output.get("advice") or {})
            edits, source, by = {"terms": [], "criterion": None, "note": None}, "warn_kept", "warn_kept"
        elif self.deps.settings.protocol_approval == "warn" and not output.get("warnings"):
            # Nothing the application can see is wrong with the proposal, so the run does not stop. The protocol says
            # that nobody was asked, so this body is never read as one a person approved.
            edits, source, by = {"terms": [], "criterion": None, "note": None}, "no_warning", "no_warning"
        else:
            self._pause(run_id, "protocol_approval_needed", {"proposal_hash": output["proposal_hash"]})

        self._checkpoint(run_id, revision)
        # What this approval proposed, whether it asked for it or carried it from the approval before. A phrase the
        # user adds from this list carries the origin `model`, and its count is not read a second time (slice 08c).
        proposals, from_step = self._suggested(run_id, output)
        # The network work of an approval happens here, in the worker, and only for the terms the user added.
        routing = self._routing_step(run_id)
        built, compiled, kept, skipped = await self._approved_vocabulary(
            run, scope, vocabulary, queries, edits.get("terms") or [], reapply=source == "earlier",
            proposals=proposals, code_query=edits.get("code_query"),
            providers=routing["providers"] if routing else None)
        if routing is not None and (gate := routing_rules.gate_query(built)) != routing["query"]:
            # The correction changed the gate query: the distribution is read once more for it, and the queries are
            # compiled for the sources it routes to. A query already read is not asked again (D93).
            routing = await self._reroute(run, scope, step, output, gate)
            built, compiled = self._compiled(built, routing["providers"], run["budget"])
        agreed = approval_rules.apply_criterion(criterion, edits.get("criterion"))
        # Switching the code's query off beside a model-written one is a correction too (D92).
        code_off = (search_query_rules.is_model_written(built) and vocabulary["code_query"]["searched"]
                    and not built["code_query"]["searched"])
        record = {
            "mode": "unattended" if unattended else self.deps.settings.protocol_approval, "approved_by": by,
            **({"asked": False} if source == "unattended" else {}),
            "edited": bool(kept or edits.get("criterion") or code_off),
            "proposal_hash": output["proposal_hash"], "term_edits": len(kept),
            "criterion_edited": edits.get("criterion") is not None,
            "exclusion_word_in_question": approval_rules.exclusion_words_in_question(scope["question"], agreed),
            **({"asked": False, "reason": "no_warning"} if source == "no_warning" else {}),
            **({"asked": False, "reason": "warn_kept", "advice": advice_rows,
                "advice_given": bool(output.get("advice")),
                "advice_model": output.get("advice_model") if output.get("advice") else None}
               if source == "warn_kept" else {}),
            **({"warnings": output["warnings"]} if output.get("warnings") else {}),
            **({"note": edits["note"]} if edits.get("note") else {}),
            **({"earlier_approval_step_id": earlier["id"]} if source == "earlier" else {}),
            # Only a run that asked, or one that carried an earlier answer, says anything about suggestions here:
            # the body of a run that asked for none is what it was before this slice.
            **({"suggestions": {
                "requests": requests, "proposed": len(proposals),
                "dropped": sum(1 for row in proposals if row["dropped"]),
                # Terms of the approved vocabulary the model proposed and the user really added.
                "accepted": sum(1 for term in built["terms"] if term["origin"] == "model"),
                "step_input_id": from_step,
                "carried_from_step_id": (output.get("carried_suggestions") or {}).get("from_step_id"),
            }} if requests or output.get("carried_suggestions") else {}),
        }
        # A correction that empties the vocabulary or makes it too broad stops the run with the step still open, so
        # the user can send another one; an approval is never closed on a search that cannot run.
        built, compiled = self._searchable(run_id, built, compiled)
        self.store.finish_step(step["id"], "succeeded", output=output | {
            # What the user sent, not what this run could apply: a later run reapplies the whole correction against
            # its own phrases and decides for itself which operations still have something to act on.
            "edits": {"terms": approval_rules.canonical_edits(edits.get("terms") or []),
                      "criterion": edits.get("criterion"), "note": edits.get("note"),
                      **({"code_query": edits["code_query"]} if edits.get("code_query") is not None else {})},
            "approved": {"vocabulary": built, "queries": compiled, "criterion": agreed,
                         **({"routing": routing} if routing else {})},
            # What was proposed stays with the closed approval, so a later run of this question can carry it and a
            # reader can still see which proposals were added and which were not (SW14.2).
            "suggestions": proposals if from_step or output.get("carried_suggestions") else None,
            "approval": record, "skipped_edits": skipped})
        return built, compiled, agreed, record

    async def _term_advice(self, run: dict[str, Any], scope: dict[str, Any], output: dict[str, Any]) -> dict[str, Any]:
        """Ask a model whether to remove or keep each warned term, once, and never block the run on it (D232, D233).

        Returns `{phrase: {recommendation, reason}}`, empty when the model is down, the call budget is spent or the
        answer does not name exactly the warned phrases. One call with no repair: a failure is stored as no advice, so
        a resumed run does not call again. The advice is shown as information; under `warn` every term is kept.
        """
        self._checkpoint(run["id"], run["scope_revision"])
        try:
            answer = await self._model_step(
                run, scope, "term_advice:1", "term_advice", optional=True,
                advice_target=approval_rules.advice_target(scope["question"], output["proposal"]["vocabulary"],
                                                           output["warnings"]))
        except OptionalStepFailed:
            return {}
        if answer.get("invalid"):
            return {}
        return {entry["phrase"]: {"recommendation": entry["recommendation"], "reason": entry["reason"].strip()}
                for entry in answer["result"]["advice"]}

    def _suggested(self, run_id: str, output: dict[str, Any]) -> tuple[list[dict[str, Any]], str | None]:
        """This approval's own proposed names, and the StepInput they came from (slice 08c).

        The newest ready request wins; with none, the list an earlier approval of the same question left behind is
        used, which is also what a reapplied correction's `model` origins must be read against. A failed request
        contributes nothing and leaves an earlier list in place.
        """
        ready = [step for step in self.store.suggestion_steps(run_id)
                 if (step["output"] or {}).get("status") == "ready"]
        if ready:
            return ready[-1]["output"]["terms"], ready[-1]["output"]["step_input_id"]
        return (output.get("carried_suggestions") or {}).get("terms") or [], None

    async def _term_suggestions(self, run: dict[str, Any], scope: dict[str, Any], vocabulary: dict[str, Any],
                                number: int) -> None:
        """Ask a model for other names of the searched phrases, and count every name it proposed (SW2.5).

        One optional call, no repair: a failed request is recorded as failed and the card offers to try again, so a
        resumed run never calls the model a second time for the same request. Nothing proposed enters the vocabulary
        or a query here — the rows are stored, the user decides — and the counts are written with the step, so a run
        resumed after this point reads them back instead of paying for them again.
        """
        run_id, revision = run["id"], run["scope_revision"]
        step = self.store.step(run_id, f"term_suggestions:{number}", "code:term_suggestions")
        self.store.start_step(step["id"])
        self._checkpoint(run_id, revision)
        try:
            output = await self._model_step(run, scope, f"term_suggestion:{number}", "term_suggestions",
                                            optional=True,
                                            suggestion_target=suggestion_rules.target(scope["question"], vocabulary))
        except OptionalStepFailed as failure:
            self.store.finish_step(step["id"], "succeeded",
                                   output={"status": "failed", "failure": failure.reason, "terms": []})
            return
        if output.get("invalid"):
            # Not repaired and not half-used: a proposal whose anchor is not one of the given phrases has no block.
            self.store.finish_step(step["id"], "succeeded",
                                   output={"status": "failed", "failure": "invalid_model_output", "terms": []})
            return
        rows = suggestion_rules.screen(vocabulary, output["result"]["terms"])
        self._checkpoint(run_id, revision)
        probe = self._count_probe(scope, run_id)
        for row in rows:
            if row["dropped"]:
                continue  # a phrase that cannot enter the query is not worth a request
            row["phrase_count"] = await probe(query_compiler.quoted(row["phrase"]))
            if row["phrase_count"] == 0:
                row["dropped"] = "zero_results"
        self.store.finish_step(step["id"], "succeeded", output={
            "status": "ready", "terms": rows, "step_input_id": output["step_input_id"]})
        self._checkpoint(run_id, revision)

    async def _approved_vocabulary(self, run: dict[str, Any], scope: dict[str, Any], vocabulary: dict[str, Any],
                                   queries: list[dict[str, Any]], term_edits: list[dict[str, Any]], reapply: bool,
                                   proposals: list[dict[str, Any]] | None = None, code_query: bool | None = None,
                                   providers: list[str] | None = None
                                   ) -> tuple[dict[str, Any], list[dict[str, Any]], list[dict[str, Any]], list[dict[str, Any]]]:
        """The vocabulary and queries the run searches with, rebuilt through the one code path that builds them.

        With no term edit the proposal is returned as it is: no probe is sent and the queries are the objects the
        vocabulary step compiled, byte for byte. With one, the corrected phrases go back through `build_vocabulary`,
        which decides the root or phrase form, the AND-only mark and the gate narrowing again — a patched term list
        would carry decisions that were taken for other phrases. The counts the proposal already read are given to
        it, so only a phrase the user added is really probed. `providers` is the routed list the proposal was compiled
        for (D93); without one — a run from before D93 — the scope's, compiled as before routing.
        """
        routed = providers is not None
        providers = providers if providers is not None else scope["providers"]
        kept, skipped = approval_rules.applicable(vocabulary, term_edits) if reapply else (term_edits, [])
        if search_query_rules.is_model_written(vocabulary):
            # The model's terms are corrected as whole phrases and the code's query is only switched on or off; the
            # code vocabulary's forms are not applied to what the model wrote (D92).
            if not kept and (code_query is None or code_query == vocabulary["code_query"]["searched"]):
                return vocabulary, queries, [], skipped
            built = await search_query_rules.rebuild(
                vocabulary, kept, code_query if vocabulary["code_query"]["searched"] else None,
                self._count_probe(scope, run["id"]), suggestion_rules.model_phrases(proposals or []))
            built, compiled = self._compiled(built, providers, run["budget"], routed=routed)
            return built, compiled, built["user_edits"], skipped
        if not kept:
            return vocabulary, queries, [], skipped
        proposals = proposals or []
        extraction = approval_rules.edited_extraction(
            vocabulary, kept, model_phrases=suggestion_rules.model_phrases(proposals))
        built = await vocabulary_rules.build_vocabulary(
            extraction, self._count_probe(scope, run["id"]),
            # The counts of this run's own probes and of the proposals it counted: an added name is not asked again.
            known={p["query"]: p["count"] for p in vocabulary["probes"]} | suggestion_rules.known_counts(proposals))
        # What the labelling runs said stays on record; the user's own operations are written beside it, and
        # `block_origins` reads both, so a phrase the user placed keeps `user` wherever its block is shown.
        built["labelling"] = vocabulary.get("labelling")
        built["user_edits"] = approval_rules.canonical_edits(kept)
        compiled = query_compiler.compile_block_queries(built, providers, run["budget"]["max_provider_requests"],
                                                        routed=routed)
        return built, compiled, built["user_edits"], skipped

    async def _source_routing(self, run: dict[str, Any], scope: dict[str, Any], vocabulary: dict[str, Any],
                              queries: list[dict[str, Any]]) -> tuple[dict[str, Any], list[dict[str, Any]]]:
        """Read where the proposal's records lie and compile its queries for the sources that routes to (D93).

        One OpenAlex request for the gate query (`routing.gate_query`), stored with its answer before the step ends, so
        a resumed run sends nothing again and searches the queries the step compiled. A run that showed its approval
        card before this step existed goes on without it, searching the queries the card showed; a new scope revision
        is routed. No domain source usable in the scope: nothing is asked. A distribution that cannot be read: every
        usable domain source is searched, and the step says so.
        """
        run_id, revision = run["id"], run["scope_revision"]
        step = self.store.existing_step(run_id, "source_routing")
        if step is not None and step["status"] == "succeeded":
            stored = step["output"]
            return search_query_rules.settled(stored["vocabulary"], stored["queries"]), stored["queries"]
        card = self.store.existing_step(run_id, "protocol_approval")
        if step is None and card is not None and card["output"] is not None:
            return vocabulary, queries
        step = step or self.store.step(run_id, "source_routing", "code:source_routing")
        self.store.start_step(step["id"])
        query = routing_rules.gate_query(vocabulary)
        reads = await self._distribution(scope, query, {})
        routing = routing_rules.route(scope["providers"], query, *reads[query] if query in reads else (None, "unavailable"))
        built, compiled = self._compiled(vocabulary, routing["providers"], run["budget"])
        # Written before the run can stop, so a resumed run reads the answer back instead of asking again.
        self.store.finish_step(step["id"], "succeeded", output={
            "routing": routing, "reads": {q: dist for q, (dist, _) in reads.items()}, "vocabulary": built,
            "queries": compiled, "query_compiler": query_compiler.BLOCKS_VERSION})
        self._checkpoint(run_id, revision)
        return self._proposed(run_id, built, compiled)

    async def _distribution(self, scope: dict[str, Any], query: str | None,
                            known: dict[str, dict[str, Any] | None]) -> dict[str, tuple[dict[str, Any] | None, str]]:
        """The field distribution of `query` with its routing status, keyed by the query; one request at most, none
        for a query already in `known`, none when no domain source could be chosen or OpenAlex cannot be asked."""
        if query is None:
            return {}
        if not routing_rules.needs_distribution(scope["providers"]):
            return {query: (None, "not_needed")}
        if query in known:
            return {query: (known[query], "read" if known[query] else "unavailable")}
        connector = CONNECTORS["openalex"]
        if "openalex" not in scope["providers"] or connector.access_mode() == "not_configured":
            return {query: (None, "unavailable")}
        distribution = await openalex.field_distribution(self.deps.http, query, api_key=connector.api_key(),
                                                         mailto=self.deps.settings.contact_email)
        return {query: (distribution, "read" if distribution else "unavailable")}

    async def _reroute(self, run: dict[str, Any], scope: dict[str, Any], approval_step: dict[str, Any],
                       output: dict[str, Any], query: str) -> dict[str, Any]:
        """Route again for a gate query the user's correction changed. The read is written on the approval step
        before anything else happens, so a worker that dies here reads it back instead of asking again."""
        known = {**(self._routing_step_output(run["id"]) or {}).get("reads", {}), **output.get("routing_reads", {})}
        reads = await self._distribution(scope, query, known)
        if query in reads and query not in known and reads[query][1] in ("read", "unavailable"):
            output["routing_reads"] = {**output.get("routing_reads", {}), query: reads[query][0]}
            self.store.set_step_output(approval_step["id"], output)
        self._checkpoint(run["id"], run["scope_revision"])
        return routing_rules.route(scope["providers"], query, *reads.get(query, (None, "unavailable")))

    def _compiled(self, vocabulary: dict[str, Any], providers: list[str], budget: dict[str, Any], *,
                  routed: bool = True) -> tuple[dict[str, Any], list[dict[str, Any]]]:
        """The first round's queries for these providers, through the compiler that wrote the vocabulary's: a
        model-written vocabulary's with the code's query beside it (D92), recompiled for the same providers.

        `routed` false is an sw run from before D93 (review of slice 14, 2026-09-23): its queries are compiled as its
        card showed them, and the code's query keeps the queries stored with it, as before routing.
        """
        limit = budget["max_provider_requests"]
        if not search_query_rules.is_model_written(vocabulary):
            return vocabulary, query_compiler.compile_block_queries(vocabulary, providers, limit, routed=routed)
        if not routed:
            compiled = search_query_rules.compile_queries(vocabulary, providers, limit, routed=False)
            return search_query_rules.with_compiled(vocabulary, compiled), compiled
        code = vocabulary["code_query"]
        built = vocabulary | {"code_query": code | {
            "queries": query_compiler.compile_block_queries(code["vocabulary"], providers, limit)}}
        compiled = search_query_rules.compile_queries(built, providers, limit)
        return search_query_rules.with_compiled(built, compiled), compiled

    def _routing_step_output(self, run_id: str) -> dict[str, Any] | None:
        step = self.store.existing_step(run_id, "source_routing")
        return step["output"] if step is not None and step["status"] == "succeeded" else None

    def _routing_step(self, run_id: str) -> dict[str, Any] | None:
        """The routing this run's proposal was compiled for, or None for a run from before D93."""
        return (self._routing_step_output(run_id) or {}).get("routing")

    def _routing(self, run_id: str) -> dict[str, Any] | None:
        """The routing this run searches under: the approved one where a correction routed again, else the step's."""
        card = self.store.existing_step(run_id, "protocol_approval")
        approved = ((card or {}).get("output") or {}).get("approved") or {}
        return approved.get("routing") or self._routing_step(run_id)

    def _providers(self, run_id: str, scope: dict[str, Any]) -> list[str]:
        """The providers this run's queries are compiled for: the routed ones (D93), else the scope's."""
        routing = self._routing(run_id)
        return routing["providers"] if routing else scope["providers"]

    def _searchable(self, run_id: str, built: dict[str, Any], queries: list[dict[str, Any]]) -> tuple[dict[str, Any], list[dict[str, Any]]]:
        """Stop the run when its vocabulary cannot be searched. A resumed run reads the same stored vocabulary, so it
        stops for the same reason again instead of going on with no query or with the query that was refused; the way
        out is a scope revision that names key terms."""
        if not queries:
            self._pause(run_id, "vocabulary_empty")
        if built["too_broad"]:
            self._pause(run_id, "vocabulary_too_broad", {"gate_count": built["gate_count"]})
        return built, queries

    async def _research_title(self, run: dict[str, Any], scope: dict[str, Any], optional: bool = False) -> None:
        """Name the research from its question and included sources' titles and abstracts (D39, D42)."""
        run_id, rid, revision = run["id"], run["research_id"], run["scope_revision"]
        included = self.store.included_works(rid)
        abstracts = [p for svid in included for p in self.store.passages_for(svid) if p["kind"] == "abstract"]
        self._checkpoint(run_id, revision)
        output = await self._model_step(run, scope, "research_title", "research_title", source_ids=included,
                                        passage_rows=abstracts, optional=optional)
        self._checkpoint(run_id, revision)
        if not output.get("invalid"):
            self.store.set_research_title(rid, revision, output["result"]["title"])
        elif not optional:
            self._fail(run_id, "invalid_model_output", {"step": "research_title", "issues": output["issues"]})

    async def _report(self, run: dict[str, Any], scope: dict[str, Any]) -> None:
        from deixis.workflow.report.sections import run_report

        await run_report(self, run, scope)

    def _embedding_model(self) -> str | None:
        """The semantic search model this research would embed with, or None when it is off (D29, SW8.3).

        The protocol step and the expansion revision both read it here, so the two bodies name the same model and a
        changed setting never turns the frozen one into null (SW11.10).
        """
        provider, model = embeddings.chosen(self.store.setting("semantic_search"))
        if provider == "off" or not model:
            return None
        return embeddings.Embedder(provider, model).stored_model

    async def _ranking(self, run: dict[str, Any], scope: dict[str, Any], vocabulary: dict[str, Any]) -> list[str]:
        """Order this revision's records by rank fusion before screening reads them; returns the inspection order.

        The step is code, not a model call: with every model call failing the run still searches, ranks and stores
        every rank (SW7). A step that already succeeded is not computed again — its stored order comes back, so a
        resumed run screens the same batches, whose keys are places in that order. A *new* discovery run of the same
        scope opens its own step and ranks again, because the pool may have grown and the user may have verified a
        seed; the earlier step's rows stay where they are.
        """
        run_id, rid, revision = run["id"], run["research_id"], run["scope_revision"]
        self._checkpoint(run_id, revision)
        decisions = DecisionStore(self.store)
        step = self.store.step(run_id, "ranking", "code:ranking")
        if step["status"] == "succeeded":
            return decisions.ranking_order(step["id"])
        self.store.start_step(step["id"])
        stored = self.store.step(run_id, "vocabulary_expansion", "code:vocabulary_expansion")["output"] or {}
        terms = expansion_rules.expansion_blocks(stored.get("expansion"), stored.get("queries"))
        model, off_reason = self._ranking_embedding(run, scope)
        output = ranking_rules.rank_records(self.store, run, scope, vocabulary, terms, model, off_reason)
        similarity = (self.store.existing_step(run_id, "source_similarity") or {}).get("output") or {}
        if model and "from_store" in similarity:
            # How many of the similarities the ranking read were stored before this run, and how many it embedded (D103).
            output |= {"embedding_from_store": similarity["from_store"], "embedding_this_run": similarity.get("embedded", 0)}
        self.store.finish_step(step["id"], "succeeded", output=output)
        return decisions.ranking_order(step["id"])

    def _ranking_embedding(self, run: dict[str, Any], scope: dict[str, Any]) -> tuple[str | None, str | None]:
        """The embedding model this run's ranking reads, and why none when it reads none (slice 21, decision 4a).

        The model is the one this run's similarity step froze when it opened, not what Settings say now: a setting
        changed during the embedding takes effect in the next run. With no step, the built-in model without an English
        sentence reads none (`english_question_missing`); otherwise the configured model, as before (a run from
        before this slice that had nothing to embed opened no step).
        """
        step = self.store.existing_step(run["id"], "source_similarity")
        output = (step or {}).get("output") or {}
        if output.get("fast_path_queue") and output.get("embedding_off_reason"):
            return None, output["embedding_off_reason"]
        if output.get("stored_model") or output.get("model"):
            return output.get("stored_model") or output["model"], None
        provider, model = embeddings.chosen(self.store.setting("semantic_search"))
        if provider == "builtin" and model and english_question.embedding_query(self.store, scope) is None:
            return None, english_question.MISSING
        return self._embedding_model(), None

    # ---- the abstract stage of an sw run (slice 09, SW9, SW1, SW11) ----------------------
    async def _abstract_stage(self, run: dict[str, Any], scope: dict[str, Any], vocabulary: dict[str, Any],
                              order: list[str], chain: list[str] | None = None, *,
                              batch_key: str | None = None, read_limit: int | None = None,
                              frozen_plan: dict[str, Any] | None = None,
                              cutoff: Callable[[], bool] | None = None) -> None:
        """Classify every record by code, then ask the model twice about the works code left open (K3, D81).

        Nothing is included here: the abstract stage has no `include` outcome (SW1.2). A work is included only by
        the full-text reading run, and only when both of its runs agree and every quote is on the page (D85). What
        the read limit does not reach is `abstract_not_read`, which is
        `unresolved`, so the next discovery run of the same question reads on from there rather than repeating.
        The plan is frozen in the code step's output: a resumed run reads it back instead of deriving it again,
        because "the works still needing a model" is a different list by then and the batch keys would move to
        other records (the bug slice 07's review found).

        The (batch, run) calls go out through the run's shared limiter, in the one submission loop table fill uses,
        and a batch is closed on the event loop as soon as both of its runs are back: which order the answers
        arrive in does not reach the decisions, because the batches hold no work in common and what a pair of runs
        means is read from that pair alone (Task 5).

        With `chain`, the same stage reads the works citation chaining brought, and only those, in the chain's own
        order, up to its own limit and under its own keys (`abstract_screening:chain:…`; D95). The contract, the
        prompt and the rules are the keyword stage's: the model is not told where a work came from.
        """
        run_id, revision = run["id"], run["scope_revision"]
        prefix = "abstract_screening:chain" if chain is not None else "abstract_screening"
        if batch_key:
            prefix = f"{batch_key}:abstract_screening"
        plan = frozen_plan if frozen_plan is not None else self._abstract_code_stage(
            run, scope, vocabulary, order, chain, batch_key=batch_key, read_limit=read_limit)
        self._wake_fetch(run_id)  # the code's decisions are written: more works may be certain now (slice 17a)
        batches, runs = plan["batches"], plan["runs"]
        by_svid = {c["source_version_id"]: c for c in self.store.candidates(run["research_id"])}
        spent_before = self.store.run(run_id)["usage"].get("model_calls", 0)
        unread: list[str] = []
        submitted = 0
        collected: dict[int, dict[int, dict[str, Any] | None]] = {}
        rows_of: dict[int, list[dict[str, Any]]] = {}
        closed: set[int] = set()
        cutoff_batches: set[int] = set()

        # Read, not opened: a batch the budget never reaches must not be left with a pending step of its own.
        # The chain's read is optional (D95): a call of it that failed is answered too, and reads as nothing, so a
        # resumed run does not send and charge it again.
        answered = {s["operation_key"] for s in self.store.run_steps(run_id)
                    if s["kind"] == "model:abstract_screening"
                    and (s["status"] == "succeeded" or s["error_code"] in ("invalid_model_output", "model_read_cutoff")
                         or (chain is not None and s["operation_key"].startswith(f"{prefix}:")
                             and s["status"] in ("failed", "outcome_unknown")))}

        def jobs() -> Iterator[_AbstractJob]:
            """The (batch, run) calls in plan order, up to the batch the budget no longer holds whole.

            Right before a batch is sent, the records of works a person decided since the plan was frozen leave it
            (slice 16): the plan step keeps its list, the StepInput stores the one sent, and a batch left empty is
            not sent at all. No decision of this batch is written for a record that left it.
            """
            nonlocal submitted
            for number, planned in enumerate(batches):
                decided = self._human_decided_records(run["research_id"], planned)
                batch = [svid for svid in planned if svid not in decided]
                if not batch:
                    continue
                # A call whose step is already stored is read back and costs nothing, so a resumed run charges the
                # budget only for the calls it still has to make; counting the stored ones too left paid-for
                # answers unused and later batches unread while the budget still held them.
                owed = [run_no for run_no in range(1, runs + 1)
                        if f"{prefix}:{number}:{run_no}" not in answered]
                if owed and cutoff is not None and cutoff():
                    return
                if owed and not self._reserve_model_pair(run,
                        [f"{prefix}:{number}:{n}" for n in owed], submitted, spent_before):
                    # The budget stopped short of this batch. Its records are unread, which is a state the workflow
                    # already has, so the run finishes rather than pausing on something a later run will pick up.
                    unread.extend(svid for later in batches[number:] for svid in later
                                  if svid not in self._human_decided_records(run["research_id"], later))
                    return
                rows_of[number] = [by_svid[svid] for svid in batch if svid in by_svid]
                for run_no in range(1, runs + 1):
                    submitted += run_no in owed
                    yield _AbstractJob(f"{prefix}:{number}:{run_no}", number, run_no, rows_of[number])

        def undecided(rows: list[dict[str, Any]]) -> list[dict[str, Any]] | None:
            """The rows still to send, or None when none are."""
            decided = self._human_decided_records(run["research_id"], [row["source_version_id"] for row in rows])
            kept = [row for row in rows if row["source_version_id"] not in decided]
            return kept or None

        async def call(job: _AbstractJob) -> dict[str, Any] | None:
            nonlocal submitted
            if job.key not in answered and cutoff is not None and cutoff():
                cutoff_batches.add(job.number)
                submitted -= 1
                return None
            # Checked again once the limiter let the call through, and once more before every send (`_model_step`): a
            # person may have decided a record's work while the call waited. Those records are not sent; a call left
            # with none is not made or charged (slice 16).
            rows = undecided(job.rows)
            if rows is None:
                submitted -= job.key not in answered
                return None
            output = await self._abstract_call(run, scope, job.number, job.run_no, rows, self.deps.limiter, prefix,
                                               recheck=undecided)
            if output is not None and output.get("cutoff"):
                cutoff_batches.add(job.number)
                return None
            return output

        def close_ready(completed: list[tuple[dict[str, Any] | None, _AbstractJob]]) -> None:
            """Close every batch both of whose runs have come back, on the event loop, one short transaction each."""
            for output, job in completed:
                collected.setdefault(job.number, {})[job.run_no] = output
            for number in sorted(collected):
                if number in closed or len(collected[number]) < runs:
                    continue
                if number in cutoff_batches:
                    unread.extend(row["source_version_id"] for row in rows_of[number])
                    closed.add(number)
                    continue
                self._checkpoint(run_id, revision)
                closed.add(number)
                # A record one run of the batch was not sent gets nothing from the batch, even if the person's
                # decision was taken back since: only what both runs saw is closed.
                sent = self._sent_to_every_run(run_id, prefix, number, runs, rows_of[number])
                self._close_abstract_batch(run, number, sent,
                                           [collected[number][run_no] for run_no in range(1, runs + 1)], runs, prefix)
                self._wake_fetch(run_id, prefix, number)

        stop = await self._send_through_limiter(run, jobs(), call, close_ready)
        if cutoff is not None:
            unread.extend(svid for n, batch in enumerate(batches) if n not in closed for svid in batch
                          if svid not in self._human_decided_records(run["research_id"], batch))
        if unread and stop is None:
            key = "chain_abstract_stage" if chain is not None else "abstract_stage"
            if batch_key:
                key = f"{batch_key}:abstract_stage"
            step_id = self.store.step(run_id, key, f"code:{key}")["id"]
            self._write_abstract_codes(run, step_id, [(svid, "abstract_not_read") for svid in unread])
            if frozen_plan is not None:
                # The owning batch already reserves these sources against the abstract limit.
                self.store.finish_step(step_id, "succeeded", output={"abstract_not_read": unread})
        if stop is not None:
            raise stop

    def _sent_to_every_run(self, run_id: str, prefix: str, number: int, runs: int,
                           rows: list[dict[str, Any]]) -> list[dict[str, Any]]:
        """The batch's rows that every run of it was sent, read from the stored steps and StepInputs (slice 16).

        A run never sent (no step, or one closed unsent for a person's decision) saw nothing; a run that stored a
        StepInput saw that StepInput's candidates, its last attempt's. A run stopped before storing one for another
        reason (the budget) narrows nothing, as before. Being read from the store, a resumed run closes the same
        records the stopped one would have.
        """
        for run_no in range(1, runs + 1):
            key = f"{prefix}:{number}:{run_no}"
            if self._unsent(run_id, key):
                return []
            last = self.store.last_step_input(self.store.existing_step(run_id, key)["id"])
            if last is not None:
                seen = {c["candidate_id"] for c in self.store.step_input_payload(last["id"])["candidates"]}
                rows = [row for row in rows if row["candidate_id"] in seen]
        return rows

    def _unsent(self, run_id: str, key: str) -> bool:
        """Whether this call of a two-run stage was never sent: it has no step, or its step was closed unsent because
        a person decided its work (slice 16). Read from the store, so a resumed run sees what the stopped one did."""
        step = self.store.existing_step(run_id, key)
        return step is None or step["error_code"] == "human_decided"

    def _human_decided_records(self, research_id: str, svids: list[str]) -> set[str]:
        """Which of these records belong to a work a person decided at any stage (slice 16)."""
        works = DecisionStore(self.store).human_decided_works(research_id)
        if not works:
            return set()
        work_of = self.store.work_ids(svids)
        return {svid for svid in svids if work_of.get(svid) in works}

    def _model_calls_left(self, run: dict[str, Any], wanted: int, submitted: int = 0,
                          before: int | None = None) -> bool:
        """Whether the run's model-call budget still holds a whole batch. A batch is read twice or not at all.

        `usage` counts a call from the moment it opens its model session, so a call handed to the limiter that has
        not got that far is not in it yet. A concurrent sender passes how many calls it has submitted since the
        run's spent count was `before`, and the larger of the two is charged: no submission takes the run past its
        budget, and a batch whose two calls no longer fit is not half-sent.
        """
        spent = self.store.run(run["id"])["usage"].get("model_calls", 0)
        if before is not None:
            spent = before + max(spent - before, submitted)
        return spent + wanted <= run["budget"]["max_model_calls"]

    def _reserve_model_pair(self, run: dict[str, Any], keys: list[str], submitted: int,
                            before: int) -> bool:
        guard = getattr(self, "_small_batch_guard", None)
        if not guard or guard["run_id"] != run["id"] or "reserved_calls" not in guard:
            return self._model_calls_left(run, len(keys), submitted, before)
        reserved = guard["reserved_calls"]
        wanted = set(keys) - reserved
        if not self._model_calls_left(run, len(reserved) + len(wanted)):
            return False
        # Both senders run on the same event loop; reserve the whole pair without yielding.
        reserved.update(wanted)
        return True

    async def _abstract_call(self, run: dict[str, Any], scope: dict[str, Any], number: int, run_no: int,
                             rows: list[dict[str, Any]], limiter: ModelCallLimiter | None = None,
                             prefix: str = "abstract_screening",
                             recheck: Callable[[list[dict[str, Any]]], list[dict[str, Any]] | None] | None = None,
                             ) -> dict[str, Any] | None:
        """One run of one batch; None when the model's output did not validate.

        An invalid output does not stop the run and is not repaired: its records stay `abstract_not_proposed` and
        a later discovery run reads them. A resumed run does not call the step again either (the guard
        `_extraction` uses), so an unusable answer is paid for once.
        """
        key = f"{prefix}:{number}:{run_no}"
        optional = prefix == "abstract_screening:chain"
        step = self.store.step(run["id"], key, "model:abstract_screening")
        if step["status"] == "failed" and step["error_code"] == "invalid_model_output":
            return None
        if step["error_code"] == "model_read_cutoff":
            return {"cutoff": True}  # D258: a resumed run does not send it again
        if optional and step["status"] in ("failed", "outcome_unknown"):
            return None
        try:
            # The chain's read is optional (D95): a failed call is recorded and its works stay unread, the run goes on.
            output = await self._model_step(run, scope, key, "abstract_screening", candidate_rows=rows,
                                            screening_target={"runs": ABSTRACT_RUNS, "run": run_no}, limiter=limiter,
                                            budget_short="skip", optional=optional, recheck=recheck)
        except OptionalStepFailed as failure:
            # A call stopped before it was sent (no connection, or one not ready) is closed as failed here, so a
            # resumed run reads it as answered like any other failed chain call.
            if self.store.step(run["id"], key, "model:abstract_screening")["status"] in ("pending", "running"):
                self.store.finish_step(step["id"], "failed", error_code=failure.reason, error=failure.detail)
            return None
        return None if output.get("invalid") else output

    def _abstract_code_stage(self, run: dict[str, Any], scope: dict[str, Any], vocabulary: dict[str, Any],
                             order: list[str], chain: list[str] | None = None, *,
                             batch_key: str | None = None, read_limit: int | None = None) -> dict[str, Any]:
        """Write what code decides about every record, then freeze the read plan in this step's output.

        With `chain`, only the chained works are classified and planned, with the chain's own read limit (D95).
        """
        run_id, rid, revision = run["id"], run["research_id"], run["scope_revision"]
        key = "chain_abstract_stage" if chain is not None else "abstract_stage"
        if batch_key:
            key = f"{batch_key}:abstract_stage"
        step = self.store.step(run_id, key, f"code:{key}")
        if step["status"] == "succeeded":
            return step["output"]
        self.store.start_step(step["id"])
        decisions = DecisionStore(self.store)
        stale_key = decisions.staleness_key(rid)
        stored = self.store.step(run_id, "vocabulary_expansion", "code:vocabulary_expansion")["output"] or {}
        terms = list((stored.get("expansion") or {}).get("terms") or [])
        _, blocks = ranking_rules.query_vocabulary(scope, vocabulary, terms)
        # One read of the whole research, as the ranking does: asking per record cost a second on 2,000 candidates
        # on the thread the API answers from (slice 05 and 07 reviews).
        versions = ranking_rules._versions(self.store, rid)
        current = self._abstract_decisions(rid)
        links = self._artifact_links(rid)
        candidates = {c["source_version_id"]: c for c in self.store.candidates(rid)}
        heads = self.store.work_heads(rid)
        by_work: dict[str, list[dict[str, Any]]] = {}
        for version in versions.values():
            # Only records a search offered are screened; an uploaded source is the user's own and is not judged.
            if version["id"] in candidates:
                by_work.setdefault(version["work_id"], []).append(version)

        works, writes = [], []
        fulltext_human = decisions.human_decided_works(rid, "fulltext")
        chained = set(chain) if chain is not None else None
        # The keyword stage leaves out what only an earlier run's chain found (D95); the chain reads its own.
        chain_only = self.store.chain_only_works(rid, revision) if chain is None else set()
        for candidate in self.store.candidates(rid, revision):
            svid = candidate["source_version_id"]
            if batch_key and svid not in order:
                continue
            if candidate["origin"] == "user" or svid not in versions or heads.get(versions[svid]["work_id"]) != svid:
                continue
            if chained is not None and svid not in chained:
                continue
            if not batch_key and versions[svid]["work_id"] in chain_only:
                continue
            rows = []
            for version in sorted(by_work[versions[svid]["work_id"]], key=lambda v: v["id"]):
                held = current.get(version["id"])
                record = dict(version, decision=held["reason_code"] if held else None)
                code = abstract_stage.code_outcome(record, blocks, links)
                stale = bool(held) and decisions.is_stale(held, stale_key)
                if batch_key and held and held["decided_by"] != "human" and not stale:
                    changed = (held["reason_code"] in abstract_stage.MODEL_CODES
                               and not small_batch.abstract_reusable(self.store, held, candidates[version["id"]]["candidate_id"],
                                                                     version, MAX_ABSTRACT_CHARS))
                    changed = changed or (held["reason_code"] in abstract_stage.OWNED_CODES
                                          and held["reason_code"] not in abstract_stage.MODEL_CODES + abstract_stage.UNREAD_CODES
                                          and code != held["reason_code"])
                    if changed:
                        writes.append((version["id"], "abstract_not_read"))
                        held, stale = {"reason_code": "abstract_not_read", "decided_by": "code"}, True
                if code and (held is None or held["decided_by"] != "human") and abstract_stage.should_write(held, code, stale):
                    writes.append((version["id"], code))
                    held, stale = {"reason_code": code, "decided_by": "code"}, False
                rows.append({"id": version["id"], "has_abstract": bool(version["abstract"]), "code": code,
                             "decision": held["reason_code"] if held else None,
                             "decided_by": held["decided_by"] if held else None, "stale": stale})
            work = {"work_id": versions[svid]["work_id"], "head": svid, "versions": rows}
            if work["work_id"] in fulltext_human:
                work["fulltext_human"] = True
            works.append(work)

        limit = (run["budget"].get("chain_abstract_read", CHAIN_ABSTRACT_READ[scope["effort"]]) if chain is not None
                 else ABSTRACT_READ_LIMIT[scope["effort"]])
        if read_limit is not None:
            limit = read_limit
        plan = abstract_stage.read_plan(order, works, limit, ABSTRACT_BATCH)
        writes += [(svid, "abstract_not_read") for svid in plan["not_read"]]
        written = self._write_abstract_codes(run, step["id"], writes)
        output = {"decisions": written, "limit": limit, "batch": ABSTRACT_BATCH, "runs": ABSTRACT_RUNS,
                  "batches": plan["batches"], "not_read": len(plan["not_read"]),
                  "works_needing_model": sum(len(batch) for batch in plan["batches"]) + len(plan["not_read"])}
        self.store.finish_step(step["id"], "succeeded", output=output)
        return output

    def _abstract_decisions(self, research_id: str) -> dict[str, dict[str, Any]]:
        """Every record's open abstract-stage decision, in one query."""
        return {row["source_version_id"]: dict(row) for row in self.store.conn.execute(
            "SELECT * FROM stage_decisions WHERE research_id = ? AND stage = 'abstract' AND superseded_at IS NULL",
            (research_id,))}

    def _artifact_links(self, research_id: str) -> set[str]:
        """The records of this research carrying an open `artifact_of` link, from either side of the pair (SW6.2).

        A link the user undid is closed and is not here, so an artifact whose link was taken back is screened like
        any other record.
        """
        member = ("SELECT source_version_id FROM corpus_memberships WHERE research_id = ? AND removed_at IS NULL")
        found: set[str] = set()
        for row in self.store.conn.execute(
            "SELECT source_version_id, other_source_version_id FROM record_links"
            " WHERE link_kind = 'artifact_of' AND closed_at IS NULL"
            f" AND (source_version_id IN ({member}) OR other_source_version_id IN ({member}))",
            (research_id, research_id),
        ):
            found |= {row["source_version_id"], row["other_source_version_id"]}
        return found

    def _write_abstract_codes(self, run: dict[str, Any], step_id: str | None,
                              writes: list[tuple[str, str]]) -> dict[str, int]:
        """Write these abstract-stage decisions and derive the selection of each work they touched.

        The user's own decision is skipped, never swallowed into a code decision (AGENTS.md, User Authority), and
        a decision that already says this is not closed and written again merely because the step identifier is
        new — so a second discovery run of the same question adds no row for what it re-derives.
        """
        rid = run["research_id"]
        decisions = DecisionStore(self.store)
        stale_key = decisions.staleness_key(rid)
        written: dict[str, int] = {}
        touched: set[str] = set()
        # Which work each record belongs to, read in one statement: asking per record was one query per write
        # and every one of them on the thread the API answers from (slice 13d).
        work_of = self.store.work_ids([svid for svid, _ in writes])
        for svid, code in writes:
            held = decisions.current(rid, svid, "abstract")
            if held is not None and held["decided_by"] == "human":
                continue
            if not abstract_stage.should_write(held, code, bool(held) and decisions.is_stale(held, stale_key)):
                continue
            try:
                decisions.record(rid, svid, code, step_id=step_id)
            except HumanDecisionStands:
                continue
            written[code] = written.get(code, 0) + 1
            touched.add(work_of[svid])
        decisions.derive_selections(rid, sorted(touched))
        return dict(sorted(written.items()))

    def _close_abstract_batch(self, run: dict[str, Any], number: int, rows: list[dict[str, Any]],
                              outputs: list[dict[str, Any] | None], runs: int,
                              prefix: str = "abstract_screening") -> None:
        """Store what each run proposed for each record of the batch and write the code the two of them mean.

        Code does this, not the model: the quote is looked for in the abstract the model was shown, and the pair of
        labels is read through `abstract_stage.combine`. Called again on a resumed run it adds no row, because
        `add_proposal` and `DecisionStore.record` both already say the same thing twice without writing twice.
        """
        rid = run["research_id"]
        decisions = DecisionStore(self.store)
        # A record whose work a person decided while the batch was out gets nothing from it (slice 16).
        decided = self._human_decided_records(rid, [row["source_version_id"] for row in rows])
        rows = [row for row in rows if row["source_version_id"] not in decided]
        if not rows:
            return  # nothing left to write, and no step to open for a call that was never made
        steps = [self.store.step(run["id"], f"{prefix}:{number}:{run_no}", "model:abstract_screening")["id"]
                 for run_no in range(1, runs + 1)]
        proposals: list[dict[str, Any]] = []
        for output in outputs:
            if output is None:
                proposals.append({})
                continue
            payload = self.store.step_input_payload(output["step_input_id"])
            proposals.append(abstract_stage.proposals_of(payload["candidates"], output["result"]["records"],
                                                         ABSTRACT_QUOTE_MIN_CHARS))
        writes = []
        for row in rows:
            cid, svid = row["candidate_id"], row["source_version_id"]
            pair = [found.get(cid) for found in proposals]
            for run_no, (found, step_id) in enumerate(zip(pair, steps), start=1):
                if found is not None:
                    decisions.add_proposal(rid, svid, "abstract", step_id, run_no, found["label"],
                                           quote=found["quote"], quote_verified=found["quote_verified"])
            writes.append((svid, abstract_stage.combine(*pair)))
        # The decision is attributed to the last run's step: it is the one that made the pair readable.
        self._write_abstract_codes(run, steps[-1], writes)

    # ---- citation chaining of an sw run (slice 15, D95) --------------------------------------------

    def _chain_forms(self, run: dict[str, Any], scope: dict[str, Any], vocabulary: dict[str, Any]) -> dict[str, list[str]]:
        """The two gate blocks' forms the chain's filter reads: the blocks the keyword ranking ranked with."""
        stored = self.store.step(run["id"], "vocabulary_expansion", "code:vocabulary_expansion")["output"] or {}
        terms = expansion_rules.expansion_blocks(stored.get("expansion"), stored.get("queries"))
        _, blocks = ranking_rules.query_vocabulary(scope, vocabulary, terms)
        return ranking_rules.block_forms({block: blocks.get(block) or [] for block in vocabulary_rules.GATE_BLOCKS})

    def _chain_seeds(self, run: dict[str, Any], scope: dict[str, Any]) -> dict[str, Any]:
        """Freeze the seeds, their identifiers and reference lists, and the backward batches (decision 2)."""
        run_id, rid = run["id"], run["research_id"]
        step = self.store.step(run_id, "chain_seeds", "code:chain_seeds")
        if step["status"] == "succeeded":
            return step["output"]
        self.store.start_step(step["id"])
        decisions = DecisionStore(self.store)
        ranking_step = self.store.step(run_id, "ranking", "code:ranking")
        pool_heads = decisions.ranking_order(ranking_step["id"])
        order = ranking_rules.fuse(decisions.signal_ranks(ranking_step["id"], ("bm25", "blocks")), ("bm25", "blocks"))
        versions = ranking_rules._versions(self.store, rid)
        by_work: dict[str, list[dict[str, Any]]] = {}
        for version in versions.values():
            by_work.setdefault(version["work_id"], []).append(version)
        rows = {head: ranking_rules._work_row(head, by_work[versions[head]["work_id"]])
                for head in pool_heads if head in versions}
        user = [row for svid in ranking_rules.verified_seeds(self.store, rid, scope)
                if (row := rows.get(svid) or ranking_rules._seed_row(svid, versions)) is not None]
        by_id = rows | {row["id"]: row for row in user}
        seeds = [entry | {"openalex_ids": sorted(by_id[entry["source_version_id"]]["own_ids"]),
                          "references": (sorted(by_id[entry["source_version_id"]]["references"])
                                         if by_id[entry["source_version_id"]]["references"] is not None else None)}
                 for entry in chaining.seed_list(order, rows, user)]
        held = set().union(*[version["own_ids"] for version in versions.values()]) if versions else set()
        output = {"seeds": seeds, "code": sum(s["kind"] == "code" for s in seeds),
                  "user": sum(s["kind"] == "user" for s in seeds),
                  "without_openalex_id": sum(not s["openalex_ids"] for s in seeds),
                  "without_references": sum(not s["references"] for s in seeds),
                  "references_held": len({ref for s in seeds for ref in s["references"] or () if ref in held}),
                  "backward_batches": chaining.backward_batches(seeds, held)}
        self.store.finish_step(step["id"], "succeeded", output=output)
        return output

    def _chain_requests_left(self, run: dict[str, Any]) -> bool:
        return self.store.run(run["id"])["usage"].get("chain_requests", 0) < run["budget"]["max_chain_requests"]

    async def _chain_requests(self, run: dict[str, Any], scope: dict[str, Any], seeds: dict[str, Any],
                              forms: dict[str, list[str]]) -> None:
        """Send the backward batches, then every seed's citing pages, one request at a time through the host gate."""
        rows = seeds["seeds"]
        for number, batch in enumerate(seeds["backward_batches"]):
            links = chaining.backward_links(rows, batch)
            await self._chain_request(run, scope, f"chain:backward:{number}", "backward", forms, links, batch=batch)
        forward: dict[str, list[str]] = {}
        for seed in rows:
            for work_id in seed["openalex_ids"]:
                forward.setdefault(work_id, []).append(seed["source_version_id"])
        for work_id, of in forward.items():
            cursor, read, page = FIRST_PAGE, 0, 1
            while cursor is not None and read < CHAIN_CITING_CAP:
                done = await self._chain_request(run, scope, f"chain:forward:{work_id}:{page}", "forward", forms,
                                                 of, cites=work_id, cursor=cursor, page=page,
                                                 per_page=min(CHAIN_CITING_PAGE, CHAIN_CITING_CAP - read))
                if done is None:
                    break
                cursor, read, page = done.get("next_cursor"), read + done.get("returned", 0), page + 1
        # Semantic Scholar goes second, with whatever room OpenAlex left under the same limit (D229).
        if chaining.s2_planned(run["budget"]):
            await self._chain_requests_s2(run, scope, forms)

    def _chain_s2_plan(self, run: dict[str, Any], scope: dict[str, Any]) -> dict[str, Any]:
        """Freeze whether Semantic Scholar is asked and about which seeds: those with a DOI (D229).

        Skipped, with the reason stored, when the research's sources do not include it or it has no access it needs. A
        seed without a DOI is not asked about and is counted, so the summary can say how many the arm could not use.
        """
        run_id = run["id"]
        step = self.store.step(run_id, "chain_s2_plan", "code:chain_s2_plan")
        if step["status"] == "succeeded":
            return step["output"]
        self.store.start_step(step["id"])
        seeds = (self.store.step(run_id, "chain_seeds", "code:chain_seeds")["output"] or {}).get("seeds") or []
        connector = CONNECTORS[chaining.S2_SOURCE]
        reason = ("not_in_scope" if chaining.S2_SOURCE not in scope["providers"]
                  else "not_configured" if connector.access_mode() == "not_configured" else None)
        dois: dict[str, str | None] = {}
        for seed in seeds:
            svid = seed["source_version_id"]
            row = self.store.conn.execute(
                "SELECT doi FROM source_versions WHERE doi IS NOT NULL AND work_id ="
                " (SELECT work_id FROM source_versions WHERE id = ?) ORDER BY id = ? DESC, id LIMIT 1",
                (svid, svid)).fetchone()
            dois[svid] = normalize_doi(row["doi"]) if row else None
        asked, without_doi = chaining.s2_seed_links(seeds, dois)
        output = {"status": "skipped" if reason else "planned", "reason": reason,
                  "seeds": [] if reason else asked, "with_doi": len(asked), "without_doi": without_doi}
        self.store.finish_step(step["id"], "succeeded", output=output)
        return output

    async def _chain_requests_s2(self, run: dict[str, Any], scope: dict[str, Any], forms: dict[str, list[str]]) -> None:
        """Each seed's references, then each seed's citing works, from Semantic Scholar, one request at a time.

        A rate-limited answer ends this arm (the pacer and the bounded retries already waited), recorded as a failed
        request; the run and the OpenAlex arm are untouched.
        """
        plan = self._chain_s2_plan(run, scope)
        seeds = plan["seeds"]
        for direction in chaining.DIRECTIONS:
            for seed in seeds:
                svid, doi = seed["source_version_id"], seed["doi"]
                # One page a seed and direction: its references up to 1,000, its citing works up to the 400 cap.
                cap = CHAIN_S2_BACKWARD_LIMIT if direction == "backward" else CHAIN_CITING_CAP
                key = f"{chaining.S2_KEY}{direction}:{svid}" + (":1" if direction == "forward" else "")
                done = await self._chain_request_s2(run, scope, key, direction, forms, svid, doi, 0, 1, cap)
                if done is not None and done.get("status") == "rate_limited":
                    return

    async def _chain_request_s2(self, run: dict[str, Any], scope: dict[str, Any], key: str, direction: str,
                                forms: dict[str, list[str]], seed: str, doi: str, offset: int, page: int,
                                per_page: int) -> dict[str, Any] | None:
        """One Semantic Scholar chain request, sent once as a step of its own and recorded as a search row whose
        query text starts `chain:`. Returns the step's output, or None when nothing more should follow it. A rate-limited
        answer is returned too, so the caller can end the arm."""
        run_id = run["id"]
        step = self.store.step(run_id, key, chaining.STEP_KIND_S2)
        if step["status"] == "succeeded":
            return step["output"]
        if step["status"] == "failed" and step["error_code"] == "rate_limited":
            return {"status": "rate_limited"}  # a resumed run ends the arm where the first pass did
        if step["status"] != "pending":
            return None  # failed, or unknown after a crash: recorded, and not sent a second time (D18)
        self._checkpoint(run_id, run["scope_revision"])
        connector = CONNECTORS[chaining.S2_SOURCE]
        if direction == "forward" and page > 1:
            previous = self.store.existing_step(run_id, key.rpartition(":")[0] + f":{page - 1}")
            refusal = self._continuation_error(previous or {"id": ""}, connector)
            if refusal:
                self.store.finish_step(step["id"], "failed", error_code=refusal, delivery_class="before_send")
                return None
        if not self._chain_requests_left(run):
            return None  # counted `not_reached` by the summary
        self.store.start_step(step["id"])
        attempts = 0
        while True:
            api_key = connector.api_key()
            left = run["budget"]["max_chain_requests"] - self.store.run(run_id)["usage"].get("chain_requests", 0)
            retries = max(0, min(PROVIDER_WAIT[scope["effort"]], left - 1))
            reserved = 1 + retries
            self.store.add_usage(run_id, "chain_requests", reserved)
            async with fetch_module.host_gate(semantic_scholar.SEARCH_URL):
                dispatched = await facade.dispatch_s2_chain(self.deps.http, doi, direction, per_page, offset, api_key,
                                                            retries)
            lookups.settle_dispatch(self.store, run_id, step, dispatched, reserved, "chain_requests", "chain_sends")
            outcome = dispatched.outcome
            if (outcome.status == "failed" and outcome.delivery_class == "before_send"
                    and attempts < MAX_TRANSIENT_NETWORK_RETRIES and self._chain_requests_left(run)):
                attempts += 1
                await asyncio.sleep(1.5 * attempts)
                continue
            break
        self._record_chain(run, step, key, direction, dispatched, forms, [seed], cites=None, page=page,
                           per_page=per_page, provider=chaining.S2_SOURCE,
                           query_text=key.rpartition(":")[0] if direction == "forward" else key)
        if outcome.status == "rate_limited":
            return {"status": "rate_limited"}
        return (self.store.step(run_id, key, chaining.STEP_KIND_S2)["output"]
                if outcome.status in ("completed", "zero_results") else None)

    async def _chain_request(self, run: dict[str, Any], scope: dict[str, Any], key: str, direction: str,
                             forms: dict[str, list[str]], links: list[Any], *, batch: list[str] | None = None,
                             cites: str | None = None, cursor: str | None = None,
                             page: int | None = None, per_page: int = CHAIN_CITING_PAGE) -> dict[str, Any] | None:
        """One chain request: sent once, its passing records written through the search's record path with their
        links, in one transaction. Returns the step's output, or None when nothing more should follow it (the
        request failed, was not sent, or the chain's request limit is spent)."""
        run_id = run["id"]
        step = self.store.step(run_id, key, chaining.STEP_KIND)
        if step["status"] == "succeeded":
            return step["output"]
        if step["status"] != "pending":
            return None  # failed, or unknown after a crash: recorded, and not sent a second time (D18)
        self._checkpoint(run_id, run["scope_revision"])
        connector = CONNECTORS["openalex"]
        if cites is not None and page is not None and page > 1:
            previous = self.store.existing_step(run_id, f"chain:forward:{cites}:{page - 1}")
            refusal = self._continuation_error(previous or {"id": ""}, connector)
            if refusal:
                self.store.finish_step(step["id"], "failed", error_code=refusal, delivery_class="before_send")
                return None
        if not self._chain_requests_left(run):
            return None  # counted `not_reached` by the summary
        self.store.start_step(step["id"])
        attempts = 0
        while True:
            operation_key = connector.api_key()
            # The provider's own rate-limit retries are requests too: they get only what the chain's limit leaves.
            left = run["budget"]["max_chain_requests"] - self.store.run(run_id)["usage"].get("chain_requests", 0)
            retries = max(0, min(PROVIDER_WAIT[scope["effort"]], left - 1))
            reserved = 1 + retries
            self.store.add_usage(run_id, "chain_requests", reserved)
            async with fetch_module.host_gate(openalex.WORKS_URL):
                if cites is not None:
                    dispatched = await facade.dispatch_citing("openalex", self.deps.http, cites, cursor or FIRST_PAGE,
                        per_page, operation_key, self.deps.settings.contact_email, retries)
                else:
                    dispatched = await facade.dispatch_lookup("openalex", "id_lookup", self.deps.http,
                        tuple(batch or []), operation_key, self.deps.settings.contact_email, retries)
            lookups.settle_dispatch(self.store, run_id, step, dispatched, reserved, "chain_requests", "chain_sends")
            outcome = dispatched.outcome
            if (outcome.status == "failed" and outcome.delivery_class == "before_send"
                    and attempts < MAX_TRANSIENT_NETWORK_RETRIES and self._chain_requests_left(run)):
                attempts += 1
                await asyncio.sleep(1.5 * attempts)
                continue
            break
        self._record_chain(run, step, key, direction, dispatched, forms, links, cites=cites, page=page, batch=batch,
                           per_page=per_page)
        return self.store.step(run_id, key, chaining.STEP_KIND)["output"] if outcome.status in ("completed", "zero_results") else None

    def _record_chain(self, run: dict[str, Any], step: dict[str, Any], key: str, direction: str,
                      outcome: SearchOutcome | facade.Dispatched | facade.DispatchedLookup,
                      forms: dict[str, list[str]], links: list[Any], *, cites: str | None, page: int | None,
                      batch: list[str] | None = None, per_page: int = CHAIN_CITING_PAGE,
                      provider: str = "openalex", query_text: str | None = None,
                      fast_request: int | None = None, fast_arrival: dict[str, Any] | None = None) -> None:
        """Write one answered chain request: the filter runs first, and only the records that pass are written, as a
        search writes them (normalised, merged by DOI, linked, a candidate with its hit). Every link is kept, passing
        or not, in `chain_links`."""
        run_id, rid, revision = run["id"], run["research_id"], run["scope_revision"]
        dispatched = outcome if isinstance(outcome, (facade.Dispatched, facade.DispatchedLookup)) else None
        outcome = dispatched.outcome if dispatched is not None else outcome
        returned_count = dispatched.returned_count if dispatched is not None else len(outcome.records)
        settings = self.deps.settings
        payload_path = payload_digest = None
        if outcome.raw_payload is not None:
            settings.payloads_dir.mkdir(parents=True, exist_ok=True)
            payload_path = f"{step['id']}.json"
            (settings.payloads_dir / payload_path).write_text(json.dumps(outcome.raw_payload), encoding="utf-8")
            payload_digest = canonical.sha256_hex(outcome.raw_payload)
        passed = [record for record in outcome.records if chaining.passes(forms, record.title, record.abstract)]
        if fast_arrival and fast_arrival["late"]:
            passed = []
        ok = outcome.status in ("completed", "zero_results")
        search_fields = dict(
            research_id=rid, run_id=run_id, step_id=step["id"], scope_revision=revision, provider=provider,
            query_text=query_text or (f"chain:fast:{direction}:{fast_request}" if fast_request is not None
                                     else key.rpartition(":")[0] if cites is not None else key),
            request_description=f"citation chaining, {direction}: {outcome.request_description}",
            access_mode=outcome.access_mode, status=outcome.status, delivery_class=outcome.delivery_class,
            result_count=len(passed), provider_total=outcome.provider_total, page_limit=per_page,
            error_json=dumps({"error": outcome.error, "http_status": outcome.http_status, "rate_limit": outcome.rate_limit,
                              "returned": returned_count, "passed_filter": len(passed)}
                             | ({"error_kind": outcome.error_kind} if outcome.error_kind is not None else {})),
            raw_payload_path=payload_path, payload_sha256=payload_digest,
            **({"connector_json": dumps(dispatched.connector)} if dispatched is not None else {}),
            **({"page_number": page} if page is not None else {}),
        )
        output = {"status": outcome.status, "direction": direction, "returned": returned_count,
                  "passed_filter": len(passed),
                  "next_cursor": outcome.next_cursor if cites is not None or provider != "openalex" else None,
                  "provider_total": outcome.provider_total}
        output = lookups.transport_output(self.store, step, output)
        if fast_arrival is not None:
            output |= fast_arrival
        if dispatched is not None and dispatched.dropped_records:
            output["dropped_records"] = dispatched.dropped_records
        if cites is None and provider == "openalex":
            # A reference OpenAlex did not return has no record to link and no title to filter: it is named here, and
            # the summary counts it, rather than stored as a link that failed the filter.
            answered = {record.provider_record_id for record in outcome.records}
            output["unresolved"] = sorted(set(batch or []) - answered)
        with transaction(self.store.conn):
            if ok:
                # A chained record ranks after every keyword record: a record a keyword query already found keeps the
                # rank and the search its candidate row names, and only gains a hit (D93's `candidate_hits`).
                self.store.record_search(search_fields, provider, passed, payload_path, step["id"], "succeeded",
                                         step_output=output, first_rank=CHAIN_RANK_BASE + (fast_request or 0) * 1000)
            else:
                final = "outcome_unknown" if outcome.delivery_class == "after_send_unknown" else "failed"
                self.store.record_search(search_fields, provider, [], payload_path, step["id"], final,
                                         step_output=output,
                                         error_code=outcome.status,
                                         error={"error": outcome.error, "http_status": outcome.http_status}
                                         | ({"error_kind": outcome.error_kind} if outcome.error_kind is not None else {}),
                                         delivery_class=outcome.delivery_class)
                return
            if fast_arrival and fast_arrival["late"]:
                return
            # A Semantic Scholar paper id is kept apart from OpenAlex's in `chain_links` by its `s2:` front.
            front = "" if provider == "openalex" else chaining.S2_PREFIX
            became = {front + record.provider_record_id: self.store.find_source_by_identifier(provider, record.provider_record_id)
                      for record in passed}
            returned = {front + record.provider_record_id for record in outcome.records}
            pairs = ([(seed, linked) for seed, linked in links if linked in returned]
                     if direction == "backward" and provider == "openalex"
                     else [(seed, linked) for seed in links for linked in sorted(returned)])
            self.store.conn.executemany(
                "INSERT OR IGNORE INTO chain_links (research_id, scope_revision, run_id, seed_source_version_id,"
                " linked_openalex_id, direction, passed_filter, source_version_id) VALUES (?, ?, ?, ?, ?, ?, ?, ?)",
                [(rid, revision, run_id, seed, linked, direction, int(linked in became), became.get(linked))
                 for seed, linked in pairs])
            if fast_request is not None:
                search = self.store.conn.execute("SELECT id FROM search_runs WHERE step_id = ?", (step["id"],)).fetchone()
                queued = set()
                for position, record in enumerate(outcome.records):
                    svid = became.get(record.provider_record_id)
                    if svid and svid not in queued:
                        queued.add(svid)
                        self.store.conn.execute("UPDATE candidates SET rank = ? WHERE search_run_id = ? AND source_version_id = ?",
                                                (CHAIN_RANK_BASE + fast_request * 1000 + position, search[0], svid))
                        self.store.conn.execute(
                            "INSERT OR IGNORE INTO fast_path_embedding_queue (run_id, class, request_index, position,"
                            " source_version_id, search_run_id, enqueued_at, status) VALUES (?, 2, ?, ?, ?, ?, ?, 'pending')",
                            (run_id, fast_request, position, svid, search[0], fast_path.timestamp(self.store.clock)))

    def _chain_filter(self, run: dict[str, Any]) -> list[str]:
        """Freeze the chained works: the heads of the records that passed, after the record path merged them, that
        the keyword pool does not hold (slice 15, Task 3.5)."""
        run_id, rid = run["id"], run["research_id"]
        step = self.store.step(run_id, "chain_filter", "code:chain_filter")
        if step["status"] == "succeeded":
            return step["output"]["chained"]
        self.store.start_step(step["id"])
        linked = [dict(row) for row in self.store.conn.execute(
            "SELECT seed_source_version_id, linked_openalex_id, direction, passed_filter, source_version_id"
            " FROM chain_links WHERE run_id = ?",
            (run_id,))]
        written = sorted({row["source_version_id"] for row in linked if row["source_version_id"]})
        heads = self.store.work_heads(rid)
        work_of = self.store.work_ids(written)
        ranked = DecisionStore(self.store).ranking_order(self.store.step(run_id, "ranking", "code:ranking")["id"])
        # The keyword pool as it stands now, by work: a chain record the record path joined to a keyword work (a
        # published version of a keyword preprint) can head that work, and the work is still a keyword work.
        keyword_pool = set(self._current_heads(rid, ranked))
        linked_heads = {heads[work_of[svid]] for svid in written if work_of.get(svid) in heads}
        chained = chaining.chained_heads(linked_heads, keyword_pool)
        # A run whose chain asked Semantic Scholar too counts by work: a link both sources found is one link, and a
        # work both brought is one work (they merged by DOI into one record). Without it the count is by identifier.
        both = any(row["linked_openalex_id"].startswith(chaining.S2_PREFIX) for row in linked)
        work_key = (lambda row: work_of.get(row["source_version_id"]) or row["source_version_id"]
                    or row["linked_openalex_id"]) if both \
            else (lambda row: row["linked_openalex_id"])
        output = {"chained": chained,
                  "links": {direction: (len({(row["seed_source_version_id"], work_key(row)) for row in linked
                                             if row["direction"] == direction}) if both
                                        else sum(row["direction"] == direction for row in linked))
                            for direction in chaining.DIRECTIONS},
                  "linked_works": len({work_key(row) for row in linked}),
                  "passed_filter": len({work_key(row) for row in linked if row["passed_filter"]}),
                  "failed_filter": len({work_key(row) for row in linked if not row["passed_filter"]}),
                  "records": len(written), "in_keyword_pool": len(linked_heads & keyword_pool),
                  "new_works": len(chained)}
        self.store.finish_step(step["id"], "succeeded", output=output)
        return chained

    def _chain_ranking(self, run: dict[str, Any], scope: dict[str, Any], vocabulary: dict[str, Any],
                       chained: list[str]) -> list[str]:
        """Rank the keyword pool and the chained works together and store the chained works' places alone (Task 3.6).

        The keyword ranking step is not touched: its rows stay what they were, and `latest_ranking` never reads this
        step. The joint pool only gives the chained works a scale the keyword works set.
        """
        run_id, rid, revision = run["id"], run["research_id"], run["scope_revision"]
        decisions = DecisionStore(self.store)
        step = self.store.step(run_id, "chain_ranking", "code:chain_ranking")
        if step["status"] == "succeeded":
            return decisions.ranking_order(step["id"])
        self.store.start_step(step["id"])
        stored = self.store.step(run_id, "vocabulary_expansion", "code:vocabulary_expansion")["output"] or {}
        terms = expansion_rules.expansion_blocks(stored.get("expansion"), stored.get("queries"))
        query_words, blocks = ranking_rules.query_vocabulary(scope, vocabulary, terms)
        versions = ranking_rules._versions(self.store, rid)
        by_work: dict[str, list[dict[str, Any]]] = {}
        for version in versions.values():
            by_work.setdefault(version["work_id"], []).append(version)
        keyword = decisions.ranking_order(self.store.step(run_id, "ranking", "code:ranking")["id"])
        pool = [ranking_rules._work_row(head, by_work[versions[head]["work_id"]])
                for head in [*keyword, *chained] if head in versions]
        in_pool = {row["id"]: row for row in pool}
        verified = [row for svid in ranking_rules.verified_seeds(self.store, rid, scope)
                    if (row := in_pool.get(svid) or ranking_rules._seed_row(svid, versions)) is not None]
        model, off_reason = self._ranking_embedding(run, scope)
        similarities = self.store.source_similarities(rid, revision, model) if model else {}
        ranked = ranking_rules.rank_pool(pool, verified, query_words, blocks, model, similarities, off_reason,
                                         ranking_rules.joint_terms(self.store, scope, vocabulary))
        keep = set(chained) & set(in_pool)
        decisions.save_ranks(step["id"], rid, ranking_rules.rank_rows(ranked, keep))
        self.store.finish_step(step["id"], "succeeded", output={
            "pool": len(pool), "chained": len(keep),
            "signals": {name: ranked["ranks"].get(name) is not None for name in ranking_rules.SIGNALS}})
        return decisions.ranking_order(step["id"])

    def _chain_summary(self, run: dict[str, Any]) -> None:
        """What the chain did in this run, totalled from its stored steps and rows so a resumed run matches."""
        run_id, rid = run["id"], run["research_id"]
        step = self.store.step(run_id, "chain_summary", "code:chain_summary")
        if step["status"] == "succeeded":
            return
        self.store.start_step(step["id"])
        steps = [s for s in self.store.run_steps(run_id) if s["kind"] == chaining.STEP_KIND]
        seeds = self.store.step(run_id, "chain_seeds", "code:chain_seeds")["output"] or {}
        filtered = self.store.step(run_id, "chain_filter", "code:chain_filter")["output"] or {}
        stage = self.store.existing_step(run_id, "chain_abstract_stage")
        plan = (stage or {}).get("output") or {}
        refused = [s for s in steps if s["error_code"] in ("connector_provenance_invalid", "adapter_revision_changed")]
        sent = [s for s in steps if s["status"] != "pending" and s not in refused]
        forward_seeds = {work_id for seed in seeds.get("seeds") or [] for work_id in seed["openalex_ids"]}
        reached = {s["operation_key"].split(":")[2] for s in sent if s["operation_key"].startswith("chain:forward:")}
        s2 = self._chain_s2_summary(run) if chaining.s2_planned(run["budget"]) else None
        chained = filtered.get("chained") or []
        decisions = DecisionStore(self.store)
        facts = decisions.facts(rid)
        # What the chained works read as once their abstract stage is done: the reason code that speaks for each.
        outcomes: Counter[str] = Counter(
            decisions.work_outcome(rid, work_id, facts).get("reason_code") or "none"
            for work_id in self.store.work_ids(chained).values())
        summary = {
            "seeds": {key: seeds.get(key, 0) for key in ("code", "user", "without_openalex_id", "without_references")},
            # The seeds alone, for the run view: the seed step's own output also carries every reference list.
            "seed_list": [{"source_version_id": seed["source_version_id"], "kind": seed["kind"]}
                          for seed in seeds.get("seeds") or []],
            "requests": {"backward": sum(s["operation_key"].startswith("chain:backward:") for s in sent),
                         "forward": sum(s["operation_key"].startswith("chain:forward:") for s in sent),
                         "failed": sum(s["status"] in ("failed", "outcome_unknown") for s in sent)
                         + (s2["requests"]["failed"] if s2 else 0),
                         "sent": self.store.run(run_id)["usage"].get("chain_requests", 0),
                         "continuation_refused": len(refused),
                         "limit": run["budget"].get("max_chain_requests"),
                         "not_reached_batches": len(seeds.get("backward_batches") or [])
                         - sum(s["operation_key"].startswith("chain:backward:") for s in sent),
                         "not_reached_seeds": len(forward_seeds - reached)},
            "unresolved_links": sum(len(json.loads(row[0] or "{}").get("unresolved") or []) for row in self.store.conn.execute(
                "SELECT output_json FROM run_steps WHERE run_id = ? AND kind = ? AND operation_key LIKE 'chain:backward:%'",
                (run_id, chaining.STEP_KIND))),
            "links": filtered.get("links") or {}, "passed_filter": filtered.get("passed_filter", 0),
            "failed_filter": filtered.get("failed_filter", 0), "in_keyword_pool": filtered.get("in_keyword_pool", 0),
            "new_works": len(chained),
            "read_by_model": sum(len(batch) for batch in plan.get("batches") or []),
            "not_read": plan.get("not_read", 0),
            "outcomes": dict(sorted(outcomes.items())),
        }
        if s2 is not None:
            summary["semantic_scholar"] = s2  # absent for a run queued before D229: its summary is what it was
        self.store.finish_step(step["id"], "succeeded", output=summary)

    def _chain_s2_summary(self, run: dict[str, Any]) -> dict[str, Any]:
        """What the Semantic Scholar arm did, from its stored plan and steps (D229)."""
        plan = self.store.existing_step(run["id"], "chain_s2_plan")
        plan = (plan or {}).get("output") or {}
        steps = [x for x in self.store.run_steps(run["id"]) if x["kind"] == chaining.STEP_KIND_S2]
        sent = [x for x in steps if x["status"] != "pending"]
        count = lambda direction: sum(f"{chaining.S2_KEY}{direction}:" in x["operation_key"] for x in sent)
        asked = {x["operation_key"].split(":")[3] for x in sent if x["operation_key"].startswith(chaining.S2_KEY)}
        planned = {seed["source_version_id"] for seed in plan.get("seeds") or []}
        return {"status": plan.get("status", "not_planned"), "reason": plan.get("reason"),
                "seeds_with_doi": plan.get("with_doi", 0), "seeds_without_doi": plan.get("without_doi", 0),
                "requests": {"backward": count("backward"), "forward": count("forward"),
                             "failed": sum(x["status"] in ("failed", "outcome_unknown") for x in sent),
                             "rate_limited": sum(x["error_code"] == "rate_limited" for x in sent)},
                "not_reached_seeds": len(planned - asked)}

    async def _source_similarity(self, run: dict[str, Any], scope: dict[str, Any], candidates: list[dict[str, Any]], *,
                                 key: str = "source_similarity", identity_step: str | None = None) -> None:
        """Score sources by the similarity of their title and abstract to the question (D30, D79, D103).

        Uses the semantic search provider (D29), frozen in the step when it opens (decision 4a): a resumed run reads it
        from the step, not from Settings. The query is embedded first, then the missing sources batch by batch, each
        batch written in its own transaction and followed by a checkpoint, so a pause waits at most one batch and a
        resumed run embeds only what is still missing. With nothing missing no call is made: stored similarities are
        scores, read even when the model is not installed now (decision 5). A failed batch ends the step `partial`
        (earlier batches stay) or `failed`; either way the run goes on and the four code signals rank the same.
        """
        run_id, rid, revision = run["id"], run["research_id"], run["scope_revision"]
        if key == "source_similarity" and run_id in getattr(self, "_fast_consumers", {}):
            return  # The durable consumer owns this step, including failed/partial cutoffs.
        step, embedder, identity_from = self._embedding_choice(run_id, key)
        if identity_step and step is None:
            frozen = self.store.existing_step(run_id, identity_step)
            if not frozen:
                return
            identity = frozen.get("output") or {}
            if not identity.get("provider") or not identity.get("stored_model"):
                return
            embedder = embeddings.Embedder.from_identity(identity["provider"], identity["stored_model"],
                                                         getattr(self.deps, "local_embedder", None))
            identity_from = identity_step
        if embedder is None or (step is not None and step["status"] == "succeeded"):
            return
        query = self._embedding_query(scope, embedder)
        if query is None:
            return  # the built-in model without an English sentence: the arm is off and the ranking says why
        identity = self._identity(embedder, identity_from)
        step = self.store.step(run_id, key, f"similarity:{embedder.stored_model}", output=identity)
        if identity_from:
            self._merge_step_output(step["id"], {}, identity)
        self.store.start_step(step["id"])
        ids = list(dict.fromkeys(c["source_version_id"] for c in candidates))
        stored = self.store.source_similarities(rid, revision, embedder.stored_model)
        missing = [svid for svid in ids if svid not in stored]
        query_text, origin = query
        # Counted for the whole step: a resumed step keeps what its earlier attempts found stored and embedded.
        prior = self.store.step_output(step["id"]) or {}
        progress = {"from_store": prior.get("from_store", len(ids) - len(missing)), "embedded": prior.get("embedded", 0)}

        # Whether the built-in model was installed and its files checked when this step ran: the transcript says so
        # from the step, never from what Settings say later (D103, decision 5).
        installed = ({"model_installed": bool(getattr(embedder.local, "integrity", None) and embedder.local.integrity.available())}
                     if embedder.provider == "builtin" else {})

        def counts() -> dict[str, Any]:
            return {"model": embedder.stored_model, "sources": len(ids), **progress, "missing": len(missing), **installed,
                    "query_origin": origin, "query_sha256": english_question.query_sha256(query_text)}

        self._merge_step_output(step["id"], counts(), identity)
        if not missing:
            self._finish_embedding_step(step["id"], "succeeded", counts(), identity)
            return
        budget, stop = self._rate_budget(step["id"], identity), lambda: self._checkpoint(run_id, revision)
        try:
            (query_vector,) = await embedder.embed(self.deps.http, [query_text], "RETRIEVAL_QUERY", budget, stop)
            progress["dimensions"] = self._query_dimensions(query_vector, prior)
            while missing:
                batch = missing[:embedder.batch]
                texts = ["\n\n".join([self.store.source(svid)["title"], *(p["text"] for p in self.store.passages_for(svid) if p["kind"] == "abstract")])
                         for svid in batch]
                vectors = await embedder.embed(self.deps.http, texts, "RETRIEVAL_DOCUMENT", budget, stop)
                embeddings.same_dimension(vectors, progress["dimensions"])
                missing = missing[len(batch):]
                progress["embedded"] += len(batch)
                with transaction(self.store.conn):  # the batch and the step's count in one short write
                    self.store.save_source_similarities(rid, revision, embedder.stored_model,
                                                        {svid: embeddings.similarity(query_vector, v) for svid, v in zip(batch, vectors)})
                    self._merge_step_output(step["id"], counts(), identity)
                self._checkpoint(run_id, revision)
        except embeddings.EmbeddingError as exc:
            self._finish_embedding_step(step["id"], "partial" if progress["embedded"] else "failed", counts() | budget.counts(),
                                        identity, error_code="embedding_failed", error={"error": str(exc)})
            return
        self._finish_embedding_step(step["id"], "succeeded", counts() | budget.counts(), identity)

    # ---- embedding steps: the frozen model, the query, the shared wait budget (slice 21) --------------------
    def _embedding_choice(self, run_id: str, key: str) -> tuple[dict[str, Any] | None, embeddings.Embedder | None, str | None]:
        """The step of this key, the embedder it froze (else the one Settings name now; None when off), and
        "resume" when an earlier step without a frozen identity takes the current setting."""
        local = getattr(self.deps, "local_embedder", None)
        step = self.store.existing_step(run_id, key)
        output = (step or {}).get("output") or {}
        if output.get("fast_path_queue") and output.get("provider") == "off":
            return step, None, None
        if output.get("provider") and output.get("stored_model"):
            return step, embeddings.Embedder.from_identity(output["provider"], output["stored_model"], local), None
        provider, model = embeddings.chosen(self.store.setting("semantic_search"))
        if provider == "off" or not model:
            return step, None, None
        return step, embeddings.Embedder(provider, model, local), "resume" if step is not None else None

    @staticmethod
    def _query_dimensions(query_vector: Any, prior: dict[str, Any]) -> int:
        """The query vector's dimension, kept in the step: every batch of the step, across a resume, must match it
        (a provider's reply of another dimension is a bad reply, never a similarity of truncated vectors)."""
        if prior.get("dimensions") and len(query_vector) != prior["dimensions"]:
            raise embeddings.EmbeddingError(f"bad_reply: the query has {len(query_vector)} dimensions where this step "
                                            f"had {prior['dimensions']}")
        return len(query_vector)

    @staticmethod
    def _identity(embedder: embeddings.Embedder, identity_from: str | None) -> dict[str, Any]:
        return ({"provider": embedder.provider, "stored_model": embedder.stored_model}
                | ({"identity_from": identity_from} if identity_from else {}))

    def _embedding_query(self, scope: dict[str, Any], embedder: embeddings.Embedder,
                         query_text: str | None = None) -> tuple[str, str] | None:
        """(text, origin) of the query. The built-in model reads English only (D103): the question when it is English,
        else the revision's English sentence; a table column's text only when it is English. Other providers take
        the text as written."""
        if query_text is not None:
            if embedder.provider == "builtin" and not english_question.is_english(query_text):
                return None
            return query_text, "column"
        if embedder.provider == "builtin":
            return english_question.embedding_query(self.store, scope)
        return scope["question"], "question"

    def _merge_step_output(self, step_id: str, extra: dict[str, Any], identity: dict[str, Any]) -> None:
        """Write `latest stored output | extra | identity`: `set_step_output` replaces the whole output."""
        self.store.set_step_output(step_id, (self.store.step_output(step_id) or {}) | extra | identity)

    def _finish_embedding_step(self, step_id: str, status: str, counts: dict[str, Any], identity: dict[str, Any],
                               error_code: str | None = None, error: Any = None) -> None:
        """Every finish of an embedding step, succeeded, partial or failed: `finish_step` replaces the output, so the
        latest stored output (the opening identity, the waits) is read first and the identity is written last."""
        output = (self.store.step_output(step_id) or {}) | counts | identity
        self.store.finish_step(step_id, status, output=output, error_code=error_code, error=error)

    def _rate_budget(self, step_id: str, identity: dict[str, Any]) -> embeddings.RateBudget:
        """The step's 429 wait budget, from what its stored output says it has waited; each second is written back."""
        return embeddings.RateBudget.from_output(
            self.store.step_output(step_id), on_wait=lambda b: self._merge_step_output(step_id, b.counts(), identity))

    def _skip_unsearchable(self, run: dict[str, Any], index: int, query: dict[str, Any]) -> bool:
        """Whether this query names a connector no query goes to, and the step that records the skip (D87).

        A plan stored before the connector's role changed keeps the query it named; the request is not sent, the step
        says why, and the rest of the run goes on exactly as it does past a failed search (D18). Nothing is written
        to `search_runs`, so the record counts and the earlier searches of the research stand untouched.
        """
        connector = CONNECTORS[query["provider_id"]]
        if connector.searchable:
            return False
        step = self.store.step(run["id"], f"search:{index}", f"provider_search:{connector.provider_id}")
        if step["status"] in ("pending", "running"):  # a step that already ended keeps its ending on a resumed run
            self.store.finish_step(step["id"], "cancelled", output={"status": "skipped", "result_count": 0},
                                   error_code="provider_not_searchable")
        return True

    async def _send_search(self, run_id: str, connector: Connector, query: dict[str, Any], limit: int,
                           page: Page | None = None, stop: Callable[[], bool] | None = None,
                           transport: dict[str, Any] | None = None) -> SearchOutcome | facade.Dispatched | None:
        """Send one search request, with its bounded retries, counting each against the run and, for an sw page,
        against the query's own count too (D89). Exhausted providers are remembered for this execution in memory;
        later searches send nothing and consume no request allowance. Every resume or retry resets the guard.

        With `stop`, a stop asked during the wait before a network retry sends nothing more and returns None: the
        page is left unwritten and a resumed run asks for it again (second review of 13f, 2026-09-23). The 429 waits
        inside a connector's own `send` are not interrupted."""
        query_key = page.query_key if page else None
        transport = transport if transport is not None else {}
        reserve = connector.requests_per_search * (1 + (page.rate_limit_retries if page else MAX_RATE_LIMIT_RETRIES))
        attempts = 0
        while True:
            key = connector.api_key()
            if connector.key_required and not key:
                return SearchOutcome("not_configured", "before_send",
                                     f"{connector.provider_id} search not sent: access=not_configured", "not_configured")
            if connector.provider_id in self._quota_out.get(run_id, set()):
                return SearchOutcome("rate_limited", "before_send", "Suppressed: provider quota exhausted in this run",
                                     "api_key" if key else "keyless", error_kind="quota_exhausted")
            self.store.add_usage(run_id, "provider_requests", reserve, query=query_key)
            # A paged read supplies the connector's search options.
            dispatched = await facade.dispatch_search(connector.provider_id, self.deps.http, query["query_text"], limit, key,
                                             self.deps.settings.contact_email,
                                             **({"cursor": page.cursor, "max_rate_limit_retries": page.rate_limit_retries,
                                                 **connector.sw_options, **endpoint_options(query)} if page else {}))
            outcome = dispatched.outcome
            actual = sum(entry["attempts"] for entry in dispatched.transport)
            sends = sum(entry["sends"] for entry in dispatched.transport)
            self.store.settle_usage(run_id, query_key, actual - reserve, sends)
            transport["reserved"] = transport.get("reserved", 0) + reserve
            transport["attempts"] = transport.get("attempts", 0) + actual
            transport["sends"] = transport.get("sends", 0) + sends
            if actual > reserve:
                transport["over_reservation"] = transport.get("over_reservation", 0) + actual - reserve
            transport.setdefault("dispatches", []).append({"subrequests": list(dispatched.transport)})
            if outcome.error_kind == "quota_exhausted":
                self._quota_out.setdefault(run_id, set()).add(connector.provider_id)
            if (outcome.status == "failed" and outcome.delivery_class == "before_send"
                    and attempts < MAX_TRANSIENT_NETWORK_RETRIES
                    and (page is None or self._query_requests(run_id, page.query_key) < page.allowance)):
                attempts += 1
                await asyncio.sleep(1.5 * attempts)
                if stop is not None and stop():
                    return None
                continue
            return dispatched

    def _record_search(self, run: dict[str, Any], step: dict[str, Any], query: dict[str, Any], outcome: SearchOutcome | facade.Dispatched,
                       limit: int, page: Page | None = None, stop_reason: str | None = None,
                       finished_at: str | None = None,
                       dispatched: facade.Dispatched | None = None,
                       transport: dict[str, Any] | None = None,
                       admission: dict[str, Any] | None = None) -> tuple[str, dict[str, Any]] | None:
        """Write one answered request: its payload, its search run, its records and its step's ending together.

        For an sw page, `stop_reason` is the one the read decided when the page arrived (`_read_query`).
        A failure is returned as (pause reason, detail).
        """
        run_id, rid = run["id"], run["research_id"]
        settings = self.deps.settings
        provider = CONNECTORS[query["provider_id"]].provider_id
        if isinstance(outcome, facade.Dispatched):
            dispatched, outcome = outcome, outcome.outcome
        transport_output = {"transport": transport} if transport and transport.get("dispatches") else {}
        if admission is not None:
            transport_output["fast_path_request"] = admission
        if outcome.status in ("adapter_revision_changed", "connector_provenance_invalid"):
            self.store.finish_step(step["id"], "failed", output={"status": outcome.status, "result_count": 0} | transport_output,
                                   error_code=outcome.status, error={"error": outcome.error},
                                   delivery_class="before_send", finished_at=finished_at)
            return "provider_adapter_revision_changed", {"provider": provider, "http_status": None,
                                                         "error_kind": None, "retry_after": None}
        if outcome.status == "not_configured":
            # Missing configuration creates no retrieval row, even after an earlier dispatch in this operation.
            self.store.finish_step(step["id"], "failed", output={"status": "not_configured", "result_count": 0} | transport_output,
                                   error_code="not_configured",
                                   error={"error": outcome.request_description, "http_status": None},
                                   delivery_class="before_send", finished_at=finished_at)
            return "provider_not_configured", {"provider": provider, "http_status": None,
                                                "error_kind": None, "retry_after": None, "service_kind": "needs_key", "reset_at": None}
        payload_path = payload_digest = None
        if outcome.raw_payload is not None:
            settings.payloads_dir.mkdir(parents=True, exist_ok=True)
            payload_path = f"{step['id']}.json"
            (settings.payloads_dir / payload_path).write_text(json.dumps(outcome.raw_payload), encoding="utf-8")
            payload_digest = canonical.sha256_hex(outcome.raw_payload)
        search_fields = dict(
            research_id=rid, run_id=run_id, step_id=step["id"], scope_revision=run["scope_revision"], provider=provider,
            query_text=query["query_text"], request_description=outcome.request_description,
            access_mode=outcome.access_mode, status=outcome.status, delivery_class=outcome.delivery_class,
            result_count=len(outcome.records), provider_total=outcome.provider_total, page_limit=limit,
            error_json=dumps({"error": outcome.error, "http_status": outcome.http_status, "rate_limit": outcome.rate_limit}
                             | ({"error_kind": outcome.error_kind} if outcome.error_kind is not None else {})
                             | {"service_kind": outcome.service_kind or service_error_kind(outcome.error_kind or outcome.http_status or outcome.status),
                                "reset_at": retry_at(outcome.rate_limit.get("retry-after")), "retries": outcome.retries}
                             # How many 429s this effort was willing to wait out here: a skipped wait is on the row,
                             # never silent (D88).
                             | ({"rate_limit_retries": page.rate_limit_retries} if page else {})),
            raw_payload_path=payload_path, payload_sha256=payload_digest,
            connector_json=dumps(dispatched.connector) if dispatched is not None else None,
        )
        ok = outcome.status in ("completed", "zero_results")
        read_total = None
        if page is not None:
            read_total = page.read_before + (dispatched.returned_count if dispatched else len(outcome.records))
            # The total a later page did not repeat is the one an earlier page reported; unknown stays NULL, not zero.
            total = outcome.provider_total if outcome.provider_total is not None else page.known_total
            search_fields |= dict(
                page_number=page.number, read_limit=page.read_limit, read_total=read_total, stop_reason=stop_reason,
                unread_count=max(0, total - read_total) if stop_reason and total is not None else None,
            )
        if ok:
            output = {"status": outcome.status, "result_count": len(outcome.records)} | transport_output
            if dispatched is not None and dispatched.dropped_records:
                output["dropped_records"] = dispatched.dropped_records
            if page is not None:
                output |= {"page": page.number, "next_cursor": outcome.next_cursor, "read_total": read_total,
                           "provider_total": outcome.provider_total, "stop_reason": stop_reason}
            self.store.record_search(search_fields, provider, outcome.records, payload_path, step["id"], "succeeded",
                                     step_output=output, first_rank=page.read_before if page else 0,
                                     finished_at=finished_at)
            return None
        final = "outcome_unknown" if outcome.delivery_class == "after_send_unknown" else "failed"
        self.store.record_search(search_fields, provider, outcome.records, payload_path, step["id"], final,
                                 step_output=(transport_output | {"dropped_records": dispatched.dropped_records}
                                 if dispatched is not None and dispatched.dropped_records else transport_output or None),
                                 error_code=outcome.status, error={"error": outcome.error, "http_status": outcome.http_status}
                                 | {"error_kind": outcome.error_kind, "service_kind": outcome.service_kind or service_error_kind(outcome.error_kind or outcome.http_status or outcome.status),
                                    "reset_at": retry_at(outcome.rate_limit.get("retry-after"))},
                                 delivery_class=outcome.delivery_class, first_rank=page.read_before if page else 0,
                                 finished_at=finished_at)
        reason = "provider_quota_exhausted" if outcome.error_kind == "quota_exhausted" else f"provider_{outcome.status}"
        return reason, {"provider": provider, "http_status": outcome.http_status,
                                              "error_kind": outcome.error_kind,
                                              "retry_after": outcome.rate_limit.get("retry-after"),
                                              "service_kind": outcome.service_kind or service_error_kind(outcome.error_kind or outcome.http_status or outcome.status),
                                              "reset_at": retry_at(outcome.rate_limit.get("retry-after"))}

    def _allowance_ended_searches(self, run_id: str) -> bool:
        """Whether a search step of this run was closed because its query's share was spent before it asked (D89)."""
        return any(s["kind"].startswith("provider_search") and s["status"] == "cancelled"
                   and s["error_code"] == "budget_exhausted" for s in self.store.run_steps(run_id))

    def _query_requests(self, run_id: str, query_key: str) -> int:
        """Requests this sw query has sent in this run, retries included (D89)."""
        return self.store.run(run_id)["usage"].get("query_requests", {}).get(query_key, 0)

    async def _search_round(self, run: dict[str, Any], queries: list[tuple[int, dict[str, Any]]], retry_failed: bool,
                            effort: str) -> tuple[str, dict[str, Any]] | None:
        """Read one round of sw queries, hosts side by side, and write what they read in query order (D89, slice 13f).

        The queries are grouped by the host their requests go to, in the order of each host's first query. A host's
        queries and pages are read one at a time, in query and page order, and at most `SEARCH_PARALLEL_HOSTS` hosts
        are read at once; the pacing each connector already has (its gap between pages, arXiv's interval, the
        Semantic Scholar gate, the effort's 429 waiting) runs inside its host's task, unchanged. A host's task writes
        nothing but request counts. What it reads is held until every query before it has been written, and the
        pages are then written here, in query order and page order: the same rows, records, outputs and events, in
        the same order, as reading the queries one by one wrote. The one thing that differs is the clock of each
        page's step, which is the request's own.

        A stop (a pause, a cancellation, a newer question revision) is looked at before each request and written
        only after the requests in flight have finished: every page read is written, in query order, so a half-read
        query goes on from its stored cursor when the run is resumed and no page is asked twice. A page read but not
        written when the process dies has no step at all, and a resumed run asks for it again.

        A failed page is recorded and ends its own query's read (D18); the failure returned is the last one in query
        order, as the one-by-one loop returned it.
        """
        run_id, revision = run["id"], run["scope_revision"]
        reads = [_QueryRead(index, query) for index, query in queries]
        hosts: dict[str, list[_QueryRead]] = {}
        for read in reads:
            connector = CONNECTORS[read.query["provider_id"]]
            if connector.searchable:
                hosts.setdefault(connector.host, []).append(read)
        waiting = iter(hosts.values())
        pending: set[asyncio.Future[bool]] = set()
        progress = asyncio.Event()
        abort = asyncio.Event()  # set on an error: the other hosts stop before their next request
        stopping = False
        error: BaseException | None = None
        written = 0
        failure = None

        def write(ended_only: bool) -> None:
            nonlocal written, failure
            while written < len(reads):
                read = reads[written]
                if self._skip_unsearchable(run, read.index, read.query):
                    pass
                elif ended_only and not read.ended:
                    return
                else:
                    failure = self._write_query(run, read) or failure
                written += 1

        while True:
            while not stopping and error is None and len(pending) < SEARCH_PARALLEL_HOSTS:
                group = next(waiting, None)
                if group is None:
                    break
                pending.add(asyncio.ensure_future(self._read_host(run, group, retry_failed, effort, progress, abort)))
            if not pending:
                break
            woken = asyncio.ensure_future(progress.wait())
            done, _ = await asyncio.wait(pending | {woken}, return_when=asyncio.FIRST_COMPLETED)
            woken.cancel()
            progress.clear()
            for task in done - {woken}:
                pending.discard(task)
                try:
                    stopping = task.result() or stopping
                except Exception as exc:
                    error = error or exc
                    abort.set()
            if error is None:
                write(ended_only=True)
        write(ended_only=False)  # after a stop or an error: the pages of queries left half read, in query order
        if error is not None:
            # What the other hosts had read is written first, so the requests they spent are not lost with it
            # (review of 13f, 2026-09-23).
            raise error
        self._checkpoint(run_id, revision)
        if stopping:
            # The stop was taken back before it was written (a resume of a pause still being requested): read on,
            # from the pages just written.
            return await self._search_round(run, queries, retry_failed, effort) or failure
        return failure

    async def _read_host(self, run: dict[str, Any], group: list[_QueryRead], retry_failed: bool, effort: str,
                         progress: asyncio.Event, abort: asyncio.Event | None = None) -> bool:
        """Read one host's queries in query order; True when a stop ended the reading before the last of them."""
        for read in group:
            if await self._read_query(run, read, retry_failed, effort, abort):
                return True
            read.ended = True
            progress.set()
        return False

    def _continuation_error(self, step, connector):
        row = self.store.conn.execute("SELECT connector_json FROM search_runs WHERE step_id = ?", (step["id"],)).fetchone()
        if row is None:
            return "connector_provenance_invalid"
        if row["connector_json"] is None:
            return None  # Pre-B4 pages retain compatibility continuation.
        try:
            recorded = json.loads(row["connector_json"])
        except (ValueError, TypeError):
            return "connector_provenance_invalid"
        if (not isinstance(recorded, dict) or not isinstance(recorded.get("contract_id"), str)
                or type(recorded.get("adapter_revision")) is not int):
            return "connector_provenance_invalid"
        current = facade.CompatibilityConnector(CONNECTORS[connector.provider_id]).descriptor
        if (recorded["contract_id"] not in contract.SUPPORTED_CONTRACTS
                or recorded["adapter_revision"] != current.adapter_revision):
            return "adapter_revision_changed"
        return None

    async def _read_query(self, run: dict[str, Any], read: _QueryRead, retry_failed: bool, effort: str,
                          abort: asyncio.Event | None = None) -> bool:
        """Read one sw query page by page up to this effort's read limit, holding each page for `_write_query`.

        A page whose step already ended is not asked again: its stored output gives the next cursor, as it always
        did (04c). A failed page ends the query's read (D18); so does a page after which the query has no request
        left of its own share (`budget_exhausted`, D89). True when a stop was requested before a page was sent.
        """
        run_id, revision = run["id"], run["scope_revision"]
        connector = reading(read.query)  # a query stored before D93 names no endpoint and reads as it did
        query_key = f"search:{read.index}"
        allowance = page_allowance(read.query, effort, run["budget"])
        cursor, before, number, known_total = FIRST_PAGE, 0, 0, None
        continuation_step = None
        while True:
            key = query_key if number == 0 else f"{query_key}:page:{number}"
            step = self.store.existing_step(run_id, key)
            status = step["status"] if step else "pending"
            if status == "succeeded" or (status in ("failed", "outcome_unknown") and not retry_failed):
                output = (step["output"] or {}) if status == "succeeded" else {}
                if status != "succeeded" or output.get("stop_reason") or not output.get("next_cursor"):
                    return False
                continuation_step = step
                before = output.get("read_total", before)
                if output.get("provider_total") is not None:
                    known_total = output["provider_total"]
                cursor, number = output["next_cursor"], number + 1
                continue
            if (abort is not None and abort.is_set()) or self._stop_requested(run_id, revision):
                return True
            if before >= min(SW_READ_LIMIT[effort], connector.max_reachable or SW_READ_LIMIT[effort]):
                # A query resumed after its read limit was lowered (13g halved `detailed`) has read what it may:
                # asking for the rest would ask for a page of no or minus records (review of 13f and 13g, 2026-09-23).
                return False
            if self._query_requests(run_id, query_key) >= allowance:
                # Only a query resumed after its last page was read, or one asked to search again, reaches this:
                # nothing is sent, and the step of the page it would have asked for says why (D89).
                read.allowance_ended = key
                return False
            if continuation_step is not None:
                error = self._continuation_error(continuation_step, connector)
                if error is not None:
                    refused_page = Page(number, cursor, before, known_total, SW_READ_LIMIT[effort],
                                        PROVIDER_WAIT[effort], query_key, allowance)
                    read.pages.append(_PageRead(key, refused_page,
                        SearchOutcome(error, "before_send", "Continuation refused", "keyless", error=error),
                        0, "page_failed", now(), now()))
                    read.ended = True
                    return False
                continuation_step = None
            if number and connector.page_gap:
                await asyncio.sleep(connector.page_gap)  # only before a page that is really requested
                if (abort is not None and abort.is_set()) or self._stop_requested(run_id, revision):
                    return True  # a stop asked during the gap (arXiv's is 3 s) sends no further page
            page = Page(number, cursor, before, known_total, SW_READ_LIMIT[effort], PROVIDER_WAIT[effort], query_key,
                        allowance)
            # A paged read is bounded by the read limit, not by results_per_query, and its last page asks only for
            # what is left of that limit.
            ceiling = min(page.read_limit, connector.max_reachable or page.read_limit)
            limit = min(connector.max_results, ceiling - page.read_before)
            started = now()
            transport: dict[str, Any] = {}
            outcome = await self._send_search(
                run_id, connector, read.query, limit, page,
                stop=lambda: (abort is not None and abort.is_set()) or self._stop_requested(run_id, revision),
                transport=transport)
            if outcome is None:
                return True
            dispatched = outcome if isinstance(outcome, facade.Dispatched) else None
            returned_count = dispatched.returned_count if dispatched else len(outcome.records)
            outcome = dispatched.outcome if dispatched else outcome
            ok = outcome.status in ("completed", "zero_results")
            read_total = before + returned_count
            stop_reason = _stop_reason(connector, outcome, ok, read_total, page.read_limit, returned_count)
            if stop_reason is None and self._query_requests(run_id, query_key) >= allowance:
                stop_reason = "budget_exhausted"  # the next page would need a request the query no longer has (D89)
            read.pages.append(_PageRead(key, page, outcome, limit, stop_reason, started, now(), dispatched, transport))
            if stop_reason:
                return False
            before = read_total
            if outcome.provider_total is not None:
                known_total = outcome.provider_total
            cursor, number = outcome.next_cursor, number + 1

    def _write_query(self, run: dict[str, Any], read: _QueryRead) -> tuple[str, dict[str, Any]] | None:
        """Write the pages one query read, in page order; each page's step, search run and records in one transaction.

        A page's step is opened, started and ended together, so no search step is ever left `running` while its
        request is on the network, and none can end up `outcome_unknown` without having been written.
        """
        kind = f"provider_search:{CONNECTORS[read.query['provider_id']].provider_id}"
        failure = None
        for held in read.pages:
            with transaction(self.store.conn):
                step = self.store.step(run["id"], held.key, kind)
                self.store.start_step(step["id"], started_at=held.started_at)
                failure = self._record_search(run, step, read.query, held.outcome, held.limit, held.page,
                                              held.stop_reason, held.finished_at, held.dispatched, held.transport) or failure
        if read.allowance_ended is not None:
            step = self.store.step(run["id"], read.allowance_ended, kind)
            if step["status"] != "cancelled":  # a resumed run finds it already closed and writes nothing again
                self.store.finish_step(step["id"], "cancelled", error_code="budget_exhausted", output={
                    "status": "skipped", "result_count": 0, "stop_reason": "budget_exhausted"})
        return failure

    async def _expansion(self, run: dict[str, Any], scope: dict[str, Any], vocabulary: dict[str, Any],
                         queries: list[dict[str, Any]], criterion: dict[str, Any] | None = None,
                         approval: dict[str, Any] | None = None) -> list[dict[str, Any]]:
        """The second round's queries, taken from the first round's own records by code (SW2.4, slice 04b).

        No model is called: the candidate phrases are the authors' keywords and the titles' repeated n-grams, and a
        count probe decides which of them the field really uses. A step that already succeeded returns its stored
        queries, so a resumed run sends no count request and reads no page twice, and the counts are stored before
        the run can stop.
        """
        run_id, rid, revision, budget = run["id"], run["research_id"], run["scope_revision"], run["budget"]
        step = self.store.step(run_id, "vocabulary_expansion", "code:vocabulary_expansion")
        if step["status"] == "succeeded":
            result, more = step["output"]["expansion"], step["output"]["queries"]
        else:
            # The second round grows from the model's own query where one was written, as it was measured: the
            # code's query beside it has no second round, and its records are not what the candidates are read from
            # (D92). A vocabulary with no origin marks reads every first-round record, as before.
            own = search_query_rules.model_queries(queries)
            records = expansion_rules.first_round_records(
                self.store, rid, revision,
                {(q["provider_id"], q["query_text"]) for q in own} if len(own) < len(queries) else None)
            found = phrase_candidates.candidates(
                records, [expansion_rules.queried_form(term) for term in expansion_rules.queried_terms(vocabulary)],
                [*vocabulary["claim_words"], *vocabulary["exclusion_words"]])
            self.store.start_step(step["id"])
            result = await expansion_rules.expand(vocabulary, found, self._count_probe(scope, run_id))
            # Abbreviations the first round's abstracts define for the task terms (D231): every first-round record is
            # read, the code query's too, since a paper naming a method only by its abbreviation is often one the
            # model's query did not find.
            task_terms = [term["phrase"] for term in expansion_rules.searched_terms(vocabulary, expansion_rules.TASK_BLOCK)]
            short = await expansion_rules.expand_abbreviations(
                vocabulary, expansion_rules.abbreviation_candidates(
                    expansion_rules.first_round_records(self.store, rid, revision), task_terms),
                self._count_probe(scope, run_id))
            result["abbreviations"] = short
            second = expansion_rules.second_round_vocabulary(vocabulary, result["terms"], own)
            # Where each accepted phrase went (D90); the protocol body keeps the compiled queries, not this.
            result["second_round"] = {key: second[key] for key in ("setting_synonyms", "task_additions", "setting_width")}
            # One query allowance for the whole second round. The abbreviation queries take theirs first: they were
            # measured on the benchmark (D231), the phrase arm's thresholds on one topic only (`expansion` module).
            # A run from before D93 compiles its second round as its first was (review of slice 14, 2026-09-23).
            limit, routed = budget["max_provider_requests"], self._routing(run_id) is not None
            shorts = expansion_rules.abbreviation_vocabulary(vocabulary, short["terms"])
            short_queries = [query | {"origin": "abbreviation"} for query in query_compiler.compile_block_queries(
                shorts, self._providers(run_id, scope), limit, routed=routed)] if shorts["terms"] else []
            room = limit - len(short_queries)
            more = query_compiler.compile_block_queries(
                second, self._providers(run_id, scope), room, routed=routed) if second["terms"] and room > 0 else []
            result["searched"] = expansion_rules.searched_additions(result, more)
            # An abbreviation counts as searched where one of its queries kept it, as an accepted phrase does.
            result["searched"][expansion_rules.TASK_BLOCK] += [
                term for term in short["terms"]
                if any(term not in (query.get("dropped_terms") or []) for query in short_queries)
                and term not in result["searched"][expansion_rules.TASK_BLOCK]]
            more += [query for query in short_queries
                     if (query["provider_id"], query["query_text"]) not in {(q["provider_id"], q["query_text"]) for q in more}]
            # What each term had brought in by the time the expansion ended: one dated photograph, never a number
            # the research keeps as its own (the live figure is derived by `term_yields`).
            result["yield_at_expansion"] = expansion_rules.count_yields(
                self.store, rid, revision, expansion_rules.term_rows(vocabulary["terms"], result))
            self.store.finish_step(step["id"], "succeeded", output={
                "expansion": result, "queries": more, "query_compiler": query_compiler.BLOCKS_VERSION})
        self._checkpoint(run_id, revision)
        if more:
            self._freeze_expansion(run, scope, vocabulary, queries + more, result, criterion, approval)
        return more

    def _freeze_expansion(self, run: dict[str, Any], scope: dict[str, Any], vocabulary: dict[str, Any],
                          queries: list[dict[str, Any]], expansion: dict[str, Any],
                          criterion: dict[str, Any] | None = None,
                          approval: dict[str, Any] | None = None) -> None:
        """Freeze the protocol again, before the second round's first provider request.

        The first record is never edited: a query the research did not have when it started is a new revision with
        its reason (SW14.2). With no accepted term there is no second revision at all. The criterion is carried over
        unchanged: a revision that dropped it would mark every decision made under it stale (SW11.10). So is the
        approval, and with it the corrected vocabulary: a revision built from the proposal instead would undo the
        user's correction and, by changing the criterion fields, mark every decision stale as well (SW2.6).
        """
        run_id, rid, revision = run["id"], run["research_id"], run["scope_revision"]
        step = self.store.step(run_id, "protocol_expansion", "protocol:expansion")
        if step["status"] == "succeeded":
            return
        self.store.start_step(step["id"])
        # The same embedding model the first revision named: a revision that dropped it would say this research
        # ordered its records without one, which is not what happened (the criterion is carried over for the same reason).
        record = self.store.freeze_protocol(rid, revision, protocol.build_protocol(
            scope, run["budget"], None, queries, self.deps.package.package_hash, self.deps.settings,
            vocabulary=vocabulary, expansion=expansion, criterion=criterion, approval=approval,
            embedding_model=self._embedding_model(), routing=self._routing(run_id)), reason="data_expansion")
        self.store.finish_step(step["id"], "succeeded",
                               output={"protocol_revision": record["protocol_revision"], "protocol_hash": record["hash"]})

    # ---- answer ---------------------------------------------------------------------
    async def _answer(self, run: dict[str, Any], scope: dict[str, Any]) -> None:
        run_id, rid = run["id"], run["research_id"]
        self._enter_clock_stage(run, "answer")
        if fast_path.enforces(run["budget"], "answer"):
            from deixis.workflow import fast_answer
            await fast_answer.answer(self, run, scope)
            return
        if small_batch.enabled(run["budget"]):
            inspection = run["budget"]["inspection"]
            if inspection.get("binding_error"):
                self._fail(run_id, inspection["binding_error"], {
                    "list_run_id": inspection["list_run_id"],
                    "note": "The completed discovery has no successful frozen list; run discovery again."})
        heads = self.store.included_works(rid)  # one per included work
        selection_revision = self.store.selection_revision(rid)  # read together with the included set it describes
        if scope.get("search_workflow") == "sw":
            # No await between the two reads above and this step's write: the snapshot is the state they describe.
            self._answer_start_snapshot(run, heads, selection_revision)
            if not heads and not self._abstract_sources(run, heads):
                # Neither evidence route is available (D234). Keep D106's recorded no-evidence result;
                # the snapshot describes inclusion, not a finding about the literature.
                self.store.save_answer(rid, run_id, None, None, run["scope_revision"], "no_evidence", None,
                                       {"ok": True, "issues": [], "reason": NO_INCLUDABLE_SOURCE,
                                        "note": "No work was included at full text when this answer started;"
                                                " no model was asked."},
                                       selection_revision=selection_revision)
                return
        if heads or scope.get("search_workflow") != "sw":
            await self._inspect(run, limit=MAX_DOWNLOADS_PER_RUN)
        # A work whose only PDF text is a person's file not read under this criterion, with no abstract-only version
        # to give instead, gives the answer nothing (slice 18b, decision 8).
        included = [read for head in heads if (read := self.store.answer_version(rid, head)) is not None]
        await self._read_equations(run, included)

        self._checkpoint(run_id)
        self.store.update_run(run_id, stage="answer")
        # Candidates the full-text stage never reached, or found no open text for, give their abstracts (D225).
        extra = self._abstract_sources(run, heads) if scope.get("search_workflow") == "sw" else []
        semantic = await self._semantic_ranking(run, scope, included + extra)
        # An sw research fills part of the input from the cue phrases its criterion was approved with (D84); a
        # legacy research passes nothing and keeps the hand-written formulation quota it had.
        patterns = self._criterion_phrases(run, scope) if scope.get("search_workflow") == "sw" else None
        if small_batch.enabled(run["budget"]):
            passages = self._small_batch_answer_passages(run, scope, included, extra, semantic, patterns)
        else:
            passages = self._retrieve(rid, scope, included, run["budget"]["max_answer_passages"], semantic, patterns)
        if not passages:
            self.store.save_answer(rid, run_id, None, None, run["scope_revision"], "no_evidence", None,
                                   {"ok": True, "issues": [], "note": "No accessible passages for the included sources."},
                                   selection_revision=selection_revision)
            return
        await self._generate_answer(run, scope, passages, selection_revision)

    async def _generate_answer(self, run: dict[str, Any], scope: dict[str, Any],
                               passages: list[dict[str, Any]], selection_revision: int) -> None:
        run_id, rid = run["id"], run["research_id"]
        source_ids = list(dict.fromkeys(p["source_version_id"] for p in passages))
        key, extra_repair = "grounded_answer", None
        later = self.store.existing_step(run_id, RESPLIT_KEY)
        if later is not None and later["status"] == "succeeded":
            output, key = later["output"], RESPLIT_KEY  # resumed after the extra repair: nothing is sent again
            extra_repair = output.get("resplit")
        else:
            output = await self._model_step(run, scope, "grounded_answer", "grounded_answer", source_ids=source_ids, passage_rows=passages,
                                            selection_revision=selection_revision)
            self._checkpoint(run_id)
            labels = None
            if output.get("invalid") and output.get("raw_output"):
                failed_input = self.store.step_input_payload(output["step_input_id"])
                labels = contracts.resplit_labels(
                    output["issues"], contracts.resolve_citation_handles(failed_input, output["raw_output"]), failed_input)
            if labels and not output.get("repair_skipped"):
                # D249: one extra repair, only when D247's several-sources rule (and D244-salvageable anchor defects) is all
                # that still blocks the answer; a call the budget no longer holds is skipped, never a pause.
                seed = {"issues": output["issues"], "raw_output": output["raw_output"],
                        "step_input_id": output["step_input_id"], "labels": labels}
                # Built from the failed attempt's stored StepInput: its passages, allowlist and handle mapping are the
                # ones its draft was written against, whatever retrieval returns now.
                frozen = self.store.step_input_payload(output["step_input_id"])
                connection, requested, effort = step_model(scope, "grounded_answer")
                if frozen["model"]["requested_model"] is not None:
                    connection, requested = frozen["model"]["connection"], frozen["model"]["requested_model"]

                def same_input(step_id: str, frozen=frozen) -> dict[str, Any]:
                    return copy.deepcopy(frozen) | {"step_input_id": new_id("sti"), "step_id": step_id, "created_at": now()}
                second = await self._model_step(run, scope, RESPLIT_KEY, "grounded_answer", step_input_builder=same_input,
                                                model=(connection, requested, effort),
                                                selection_revision=self.store.step_input_selection_revision(output["step_input_id"]),
                                                budget_short="skip", resplit=seed)
                self._checkpoint(run_id)
                if not second.get("repair_skipped"):
                    output, key = second, RESPLIT_KEY
                    extra_repair = {"labels": labels, "outcome": "rejected" if second.get("invalid") else "published"}
                    stored = (self.store.existing_step(run_id, RESPLIT_KEY) or {}).get("output") or {}
                    if (stored.get("resplit") or {}).get("relabelled"):  # D259
                        extra_repair["relabelled"] = stored["resplit"]["relabelled"]
                else:
                    extra_repair = {"labels": labels, "outcome": "skipped_budget"}
        inference_cap = None
        if not output.get("invalid"):
            output, key, inference_cap = await self._cap_inference(run, scope, output, key)
        step = self.store.step(run_id, key, "model:grounded_answer")
        if fast_path.enforces(run["budget"], "answer"):
            self._checkpoint(run_id, run["scope_revision"])
        # The revision recorded with the StepInput the output came from; a resumed run may reuse an earlier output.
        step_selection = self.store.step_input_selection_revision(output["step_input_id"])
        if output.get("invalid"):
            try:
                draft = json.loads(output["raw_output"] or "")
                draft = draft if isinstance(draft, dict) else None
            except json.JSONDecodeError:
                draft = None
            self.store.save_answer(rid, run_id, step["id"], output["step_input_id"], run["scope_revision"], "unverified_draft",
                                   draft, {"ok": False, "issues": output["issues"]} | ({"extra_repair": extra_repair} if extra_repair else {}),
                                   selection_revision=step_selection)
            return
        payload = self.store.step_input_payload(output["step_input_id"])
        links = contracts.derive_evidence_links(payload, output["result"])
        answer_id = self.store.save_answer(rid, run_id, step["id"], output["step_input_id"], run["scope_revision"], "structurally_valid",
                                           output["result"], {"ok": True, "issues": [], "warnings": output.get("warnings", [])}
                                           | ({"extra_repair": extra_repair} if extra_repair else {})
                                           | ({"inference_cap": inference_cap} if inference_cap else {}), links,
                                           selection_revision=step_selection)
        for _, task in self._clock_tasks.get(run_id, {}).values():
            task.cancel()
        if not fast_path.enforces(run["budget"], "answer"):
            await self._review(run, scope, answer_id, output["result"])

    def _answer_start_snapshot(self, run: dict[str, Any], heads: list[str], selection_revision: int) -> None:
        """Where the flow stood when this `sw` answer run started (slice 20, decision 3), kept in a code step.

        A snapshot, not the works the answer used: which works and passages reached the model is the StepInput's
        (`inputs_given`), read after `_inspect`. A resumed run keeps the snapshot its start wrote. Synchronous, so
        nothing else writes between the included set and selection revision the caller read and this step.
        """
        step = self.store.step(run["id"], "answer_start_snapshot", "code:answer_start_snapshot")
        if step["status"] == "succeeded":
            return
        rid = run["research_id"]
        self.store.start_step(step["id"])
        ctx = human_queue.context(self.store, rid)
        flow = flow_counts.flow_counts(ctx, probe_rules.probe_set(ctx))
        self.store.finish_step(step["id"], "succeeded", output={
            "scope_revision": run["scope_revision"], "selection_revision": selection_revision,
            "flow": flow, "included": len(heads),
            # Included works whose only text is the person's file not read yet: they give the answer nothing (D100).
            "included_without_answer_text": sum(1 for head in heads if self.store.answer_version(rid, head) is None)})

    def _abstract_sources(self, run: dict[str, Any], heads: list[str]) -> list[str]:
        """Eligible abstract-only works in the answer's bound frozen list (D225, D238).

        A work counts when the abstract stage kept it as a candidate and the full-text stage either never decided it
        or found no open text for it (`no_fulltext`), under this question revision; its selection is still pending
        (nothing excluded it, no person decided it) and it has an abstract and no PDF text. The pool is the run's
        `max_candidates` eligible works from that list. A resumed run keeps the list its
        first pass stored, less any work a person has decided since.
        Passage allocation is handled by `_small_batch_answer_passages`.
        """
        # Unbound answers (attached scope, or mixed without a completed small-batch discovery) have no
        # automatic abstract candidate route. D119 answers do not call this helper; old sw answers cannot execute.
        if not small_batch.enabled(run["budget"]):
            return []
        rid, revision = run["research_id"], run["scope_revision"]
        pending = {r[0] for r in self.store.conn.execute(
            "SELECT source_version_id FROM selections WHERE research_id = ? AND state = 'pending' AND origin != 'user'",
            (rid,))}
        def without_text(head: str) -> bool:
            return not any(self.store.has_pdf_text(v) for v in [head, *self.store.work_versions(rid, head)])

        step = self.store.step(run["id"], "answer_abstract_sources", "code:answer_abstract_sources")
        if step["status"] == "succeeded":
            # A person who decided one of them since the list was stored has the last word (AGENTS.md, User Authority),
            # and a work whose PDF text arrived since is no longer abstract-only.
            return [svid for svid in step["output"]["sources"] if svid in pending and without_text(svid)]
        self.store.start_step(step["id"])
        decisions = DecisionStore(self.store)
        limit = run["budget"]["max_candidates"]
        facts = decisions.facts(rid)
        work_heads = facts["heads"]
        listing = small_batch.answer_listing(self.store, run)
        order = small_batch.unchanged_heads(self.store, rid, listing, listing["items"])
        ranking_context = {"ordering_rule": small_batch.POLICY, "manifest_hash": listing["manifest_hash"]}
        head_of = {svid: work_heads[wid] for svid, wid in
                   self.store.work_ids(order).items()
                   if wid in work_heads}
        taken, sources, reasons = set(heads), [], Counter()
        for svid in order:
            head = head_of.get(svid)
            if head is None or head in taken or len(sources) >= limit:
                continue
            taken.add(head)
            outcome = decisions.work_outcome(rid, self.store.source(head)["work_id"], facts)
            kept = (outcome.get("stage") == "abstract" and outcome.get("outcome") == "candidate"
                    or outcome.get("stage") == "fulltext" and outcome.get("outcome") == "unresolved"
                    and outcome.get("reason_code") == "no_fulltext")
            # Decided under this question revision: an older revision's candidate was screened against another question.
            kept = kept and self.store.conn.execute(
                "SELECT 1 FROM stage_decisions WHERE research_id = ? AND source_version_id = ? AND stage = ?"
                " AND superseded_at IS NULL AND scope_revision = ?",
                (rid, outcome["source_version_id"], outcome["stage"], revision)).fetchone() is not None
            # A work with PDF text in any version is not abstract-only.
            if (kept and head in pending and without_text(head)
                    and any(p["kind"] == "abstract" for p in self.store.passages_for(head))):
                sources.append(head)
                reasons[f"{outcome['stage']}/{outcome['reason_code']}"] += 1
        self.store.finish_step(step["id"], "succeeded", output={"sources": sources, "limit": limit,
                                                                "by_decision": dict(reasons), **ranking_context})
        return sources

    def _small_batch_answer_passages(self, run: dict[str, Any], scope: dict[str, Any], included: list[str],
                                     extra: list[str], semantic: list[dict[str, Any]] | None,
                                     patterns: list[tuple[str, re.Pattern[str]]] | None) -> list[dict[str, Any]]:
        """D238: retain order within evidence layers; rank passages only within each eligible work."""
        rid = run["research_id"]
        listing = small_batch.answer_listing(self.store, run)
        saved = self.store.existing_step(run["id"], "small_batch:v1:answer_input")
        if saved is not None and saved["status"] == "succeeded":
            plan = saved["output"]
            if plan["selection_revision"] != self.store.selection_revision(rid):
                self._fail(run["id"], "selection_changed", {"note": "The frozen answer input is stale."})
            return [self.store.passage(pid) for pid in plan["passage_ids"]]
        valid = set(small_batch.unchanged_heads(self.store, rid, listing, listing["items"]))
        eligible = {wid: svid for svid, wid in self.store.work_ids(included + extra).items()}
        user_works = set(self.store.work_ids([row[0] for row in self.store.conn.execute(
            "SELECT source_version_id FROM selections WHERE research_id = ? AND state = 'included'"
            " AND origin = 'user'", (rid,))]).values())
        ordered = [item | {"ordering_reason": "frozen_list"} for item in listing["items"]
                   if item["work_id"] in eligible and item["head"] in valid]
        present = {item["work_id"] for item in ordered}
        additions = [{"work_id": wid, "head": eligible[wid], "position": None,
                      "user_priority": wid in user_works,
                      "ordering_reason": "user_included_outside_frozen_list" if wid in user_works
                      else "included_outside_frozen_list"}
                     for wid in sorted(eligible.keys() - present)]
        ordered = ([item for item in additions if item["user_priority"]]
                   + [item for item in ordered if item["user_priority"] or item["work_id"] in user_works]
                   + [item for item in ordered if not item["user_priority"] and item["work_id"] not in user_works]
                   + [item for item in additions if not item["user_priority"]])
        fts = " OR ".join(f'"{term}"' for term in self._topic_terms(rid, scope))
        queues, items = [], []
        for item in ordered:
            svid = eligible.get(item["work_id"])
            passages = self.store.passages_for(svid)
            if svid in extra:
                queue = [p for p in passages if p["kind"] == "abstract"][:1]
            else:
                # PDF text leads; the abstract may follow, but cannot displace the best question/criterion page.
                pages = [p for p in passages if p["kind"] == "pdf_page"]
                ids = {p["id"] for p in pages}
                topic = [p for p in self.store.search_passages([svid], fts, len(passages)) if p["id"] in ids]
                if semantic is not None:
                    topic = fuse_rankings(topic, [p for p in semantic if p["id"] in ids])
                criterion = criterion_passages.criterion_order(pages, patterns or [])
                ranked = fuse_rankings(topic, criterion) if criterion else topic
                queue = list({p["id"]: p for p in [*ranked, *pages, *passages]}.values())[:MAX_PASSAGES_PER_SOURCE]
            if queue:
                queues.append(queue)
                items.append(item | {"source_version_id": svid,
                                     "evidence_layer": "included_fulltext" if svid in included
                                     and self.store.has_pdf_text(svid) else "abstract_only"})
        limit = run["budget"]["max_answer_passages"]
        # Keep the former breadth prefix when room permits, while giving included PDF evidence
        # representation before depth. A fixed 24-work cap would lose early D225 sources at DBR.
        original_prefix = {item["source_version_id"] for item in items[:max(1, limit // 2)]}
        layered = run["budget"]["inspection"].get("answer_allocation_version", 1) >= 2
        breadth = max(1, limit // 2)
        if layered:
            pairs = sorted(zip(items, queues), key=lambda pair: (
                not (pair[0]["user_priority"] or pair[0]["work_id"] in user_works),
                pair[0]["evidence_layer"] != "included_fulltext"))
            items = [item for item, _ in pairs]
            queues = [queue for _, queue in pairs]
            breadth = min(limit, sum(item["evidence_layer"] == "included_fulltext"
                                     or item["source_version_id"] in original_prefix for item in items))
        passages = small_batch.allocate(queues, limit, MAX_PASSAGES_PER_SOURCE, breadth=breadth)
        represented = {p["source_version_id"] for p in passages}
        selection_revision = self.store.selection_revision(rid)
        small_batch.save_code(self, run, "small_batch:v1:answer_input", "code:small_batch_answer_input", lambda: {
            "policy": small_batch.POLICY, "manifest_hash": listing["manifest_hash"],
            "allocation_rule": "user_priority_then_included_fulltext_v2" if layered else "frozen_work_order_v1",
            "representation_limit": breadth,
            "selection_revision": selection_revision, "limit": limit,
            "items": [{"work_id": item["work_id"], "source_version_id": item["source_version_id"],
                       "position": item["position"],
                       "ordering_reason": item["ordering_reason"],
                       "evidence_layer": item["evidence_layer"],
                       "reason": None if item["source_version_id"] in represented else "answer_budget_deferred"}
                      for item in items], "passage_ids": [p["id"] for p in passages]})
        return passages

    def _criterion_phrases(self, run: dict[str, Any], scope: dict[str, Any]) -> list[tuple[str, re.Pattern[str]]]:
        """The approved cue phrases this answer run orders criterion passages with, compiled (D84, SW12.3).

        They are read from `protocol_records` alone, never from a step output: a proposal still waiting on the
        approval card is not a criterion, and a phrase list belongs to the research, not to the run that proposed it.
        `frozen_criterion` matches the question and steering this run answers, so a revised question leaves the old
        phrases behind, and passes over a body whose criterion is null, so an older filled body of the same question
        is used instead (D78).

        The step is frozen like a plan: a resumed run recompiles what it stored and does not read the protocol again,
        and a second answer run opens its own step. No model is called and nothing can fail here, so the step is
        `succeeded` even when it found no phrases; what it found is in its output.
        """
        step = self.store.step(run["id"], "criterion_phrases", "code:criterion_phrases")
        if step["status"] == "succeeded":
            return criterion_passages.compile_phrases([{"phrase": p} for p in step["output"]["phrases"]])["patterns"]
        self.store.start_step(step["id"])
        frozen = self.store.frozen_criterion(run["research_id"], scope["question"], scope.get("steering"))
        compiled = criterion_passages.compile_phrases((frozen or {}).get("cue_phrases") or [])
        phrases = [phrase for phrase, _ in compiled["patterns"]]
        reason = "no_criterion" if frozen is None else None if phrases else "no_phrases"
        self.store.finish_step(step["id"], "succeeded", output={
            "source": "none" if frozen is None else "protocol", "reason": reason,
            "protocol_revision": frozen["protocol_revision"] if frozen else None,
            "phrases": phrases, "dropped": compiled["dropped"]})
        return compiled["patterns"]

    async def _pdf_ocr(self, run: dict[str, Any]) -> None:
        """Read a PDF's scanned pages with the local Tesseract, one step per page, and write the OCR extraction (D51).

        A page read once is not read again when the run resumes. When a page fails the other pages are still read, then the
        run pauses and nothing is written; resuming reads the failed pages again. The question's scope does not matter here.
        """
        run_id, asset_id, langs = run["id"], run["target"]["asset_id"], run["target"]["languages"]
        asset = self.store.asset(asset_id)
        if asset["removed_at"] is not None:
            self._fail(run_id, "asset_removed", {"asset_id": asset_id})
        path = self.deps.settings.papers_dir / asset["storage_path"]

        step = self.store.step(run_id, "ocr:pages", "ocr_pages")
        if step["status"] == "succeeded":
            found = step["output"]
        else:
            self._checkpoint(run_id)
            self.store.start_step(step["id"])
            extraction = await asyncio.to_thread(pdf.extract_pdf, path)
            if extraction.status == "failed":
                self.store.finish_step(step["id"], "failed", error_code="extraction_failed", error={"error": extraction.error})
                self._fail(run_id, "extraction_failed", {"error": extraction.error})
            found = {"page_count": extraction.page_count, "image_pages": extraction.image_pages, "blank_pages": extraction.blank_pages}
            self.store.finish_step(step["id"], "succeeded", output=found)

        pages, failed = [], {}
        for number in found["image_pages"]:
            self._checkpoint(run_id)
            step = self.store.step(run_id, f"ocr:page:{number}", "ocr_page")
            result = step["output"]
            if step["status"] != "succeeded":
                self.store.start_step(step["id"])
                page = await asyncio.to_thread(ocr.read_page, path, number, langs)
                if page.status == "failed":
                    self.store.finish_step(step["id"], "failed", error_code="ocr_page_failed", error={"error": page.error})
                    failed[str(number)] = page.error
                    continue
                result = {"status": page.status, "text": page.text, "printed_label": page.printed_label}
                self.store.finish_step(step["id"], "succeeded", output=result)
            pages.append(ocr.OcrPage(number, result["status"], result["text"], printed_label=result["printed_label"]))
        if failed:
            self._pause(run_id, "ocr_pages_failed", {"failed_pages": sorted(map(int, failed)), "errors": failed})

        self._checkpoint(run_id)
        step = self.store.step(run_id, "ocr:merge", "ocr_merge")
        if step["status"] == "succeeded":
            return
        self.store.start_step(step["id"])
        base = await asyncio.to_thread(pdf.extract_pdf, path)
        from deixis.workflow import recovery

        base.extraction_version = recovery.text_base(self.store.asset(asset_id)["extraction_version"])
        try:
            read = ocr.merge(base, pages, langs)
        except ValueError as exc:  # the extractor changed since the pages were found
            self.store.finish_step(step["id"], "failed", error_code="ocr_pages_changed", error={"error": str(exc)})
            self._fail(run_id, "ocr_pages_changed", {"error": str(exc)})
        try:
            report = self.store.reextract_asset(asset_id, read, read.extraction_version, pdf.chunk_page, allow_run_id=run_id)
        except RunInProgress:  # another research using this source has a run
            self.store.finish_step(step["id"], "failed", error_code="ocr_blocked_by_run", error={"asset_id": asset_id})
            self._pause(run_id, "ocr_blocked_by_run", {"asset_id": asset_id})
        except NotFound:
            self.store.finish_step(step["id"], "failed", error_code="asset_removed", error={"asset_id": asset_id})
            self._fail(run_id, "asset_removed", {"asset_id": asset_id})
        self.store.finish_step(step["id"], "succeeded", output=report)

    async def _inspect(self, run: dict[str, Any], limit: int | None) -> None:
        """Retrieve the included works' open PDFs. An answer run stops after `limit` downloads; a PDF collection run,
        which the user starts before an answer, tries every work (D49). A retrieved PDF is not fetched again."""
        run_id, rid = run["id"], run["research_id"]
        heads = self.store.included_works(rid)
        if not heads:
            self._fail(run_id, "no_included_sources")
        self.store.update_run(run_id, stage="inspection")
        downloads = 0
        for head in heads:
            self._checkpoint(run_id)
            downloads += await self._acquire_pdf(run, head, downloads, limit)
            # A head without PDF text (often a paywalled published record) is read through an open version of the
            # same work, such as its arXiv preprint; the passages carry that version's label (D48).
            for other in [] if self.store.has_pdf_text(head) else self.store.work_versions(rid, head):
                if not self.store.has_pdf_text(other):
                    self._checkpoint(run_id)
                    downloads += await self._acquire_pdf(run, other, downloads, limit)
                if self.store.has_pdf_text(other):
                    break

    async def _read_equations(self, run: dict[str, Any], svids: list[str]) -> None:
        """Wait until the equations of the PDFs an answer or a table cell reads have been read with Marker (D52).

        Without the equation reader nothing waits. A failed read pauses the run with its reason; resuming continues
        with that PDF's text layer, since its step stays failed.

        Without Marker and with the arXiv source route on (D104), a PDF the route may read is read once per run through
        it; no outcome of the route pauses the run: the step ends `succeeded` with the PDF's state in its output.
        """
        service = self.deps.equations
        if service is None:
            return
        if not service.available():
            if service.route_active():
                await self._read_source_equations(run, svids)
            return
        run_id = run["id"]
        assets = [r[0] for svid in svids for r in self.store.conn.execute(
            "SELECT id FROM source_assets WHERE source_version_id = ? AND removed_at IS NULL", (svid,))]
        skipped = 0
        for asset_id in assets:
            step = self.store.step(run_id, f"equations:{asset_id}", "read_equations")
            if step["status"] in ("succeeded", "failed") or equation_state(self.store, asset_id)["state"] in ("read", "no_math"):
                continue
            if self.store.equation_skip_requested(run_id):  # "Answer now with PDF text": the rest keep their text layer
                skipped += 1
                continue
            self._checkpoint(run_id)
            self.store.start_step(step["id"])
            try:
                state = await service.read_asset(asset_id, run_id)
            except RunInProgress:
                self.store.finish_step(step["id"], "failed", error_code="equations_blocked_by_run", error={"asset_id": asset_id})
                self._pause(run_id, "equations_blocked_by_run", {"asset_id": asset_id})
            except math_reader.MathReaderUnavailable as exc:
                self.store.finish_step(step["id"], "failed", error_code="equation_reader_unavailable", error={"error": str(exc)})
                self._pause(run_id, "equation_reader_unavailable", {"error": str(exc)})
            if state["state"] == "failed" and state.get("outcome") != "file_busy":
                self.store.finish_step(step["id"], "failed", error_code="equations_failed", error={"asset_id": asset_id, **state})
                self._pause(run_id, "equations_failed", {"asset_id": asset_id, **state})
            self.store.finish_step(step["id"], "succeeded", output={"asset_id": asset_id, **state})
        if skipped:
            summary = self.store.step(run_id, "equations_skipped", "equations_skipped")
            if summary["status"] != "succeeded":
                self.store.start_step(summary["id"])
                self.store.finish_step(summary["id"], "succeeded", output={"pdfs_read": len(assets) - skipped, "pdfs_skipped": skipped})

    async def _read_source_equations(self, run: dict[str, Any], svids: list[str]) -> None:
        """The arXiv source route's step per PDF (D104): tried at most once per run, never pausing it."""
        service = self.deps.equations
        run_id = run["id"]
        assets = [r[0] for svid in svids for r in self.store.conn.execute(
            "SELECT id FROM source_assets WHERE source_version_id = ? AND removed_at IS NULL", (svid,))]
        for asset_id in assets:
            state = equation_state(self.store, asset_id)
            again = (state["state"] == "failed" and state.get("reason") == EXTRACTION_FAILED
                     and state.get("attempts", EQUATION_ATTEMPTS) < EQUATION_ATTEMPTS)
            waiting = state["state"] == "source_waiting"  # rule 3's table: the step records the wait and does not wait
            if not service.route_target(asset_id) or (state["state"] != "pending" and not again and not waiting):
                continue  # read, refused, permanently absent or failed for good: nothing to ask, no request
            step = self.store.step(run_id, f"equations:{asset_id}", "read_equations")
            if step["status"] in ("succeeded", "failed"):
                continue
            self._checkpoint(run_id)
            self.store.start_step(step["id"])
            if waiting:
                self.store.finish_step(step["id"], "succeeded", output={"asset_id": asset_id, "route": "arxiv_source", **state})
                continue
            try:
                state = await service.read_asset(asset_id, run_id)
            except RunInProgress:
                state = {"state": "pending", "outcome": "blocked_by_run"}
            except Exception as exc:  # noqa: BLE001 - a gain, never a requirement: the run goes on with the current text
                log.exception("arXiv source reading failed for %s", asset_id)
                state = {"state": "pending", "outcome": "error", "error": f"{type(exc).__name__}: {exc}"[:300]}
            self.store.finish_step(step["id"], "succeeded", output={"asset_id": asset_id, "route": "arxiv_source", **state})

    async def _acquire_pdf(self, run: dict[str, Any], svid: str, downloads: int, limit: int | None,
                           other_versions: bool = False) -> int:
        """Retrieve the source's open PDF of the same version, if it has none yet; returns the downloads it counted.

        `other_versions` is passed by the full-text retrieval run alone (D83) and reaches only the DOI lookup a
        refused link opens here; an answer run and a PDF collection run never pass it.
        """
        source = self.store.source(svid)
        # A PDF from a different version (e.g. a submitted manuscript for a published record) is not attached.
        same_version = source["oa_pdf_version"] is not None and source["oa_pdf_version"] == source["version_label"]
        if not (source["origin"] == "provider" and source["oa_pdf_url"] and same_version and not self.store.has_asset(svid)):
            return 0
        # A link that refused in an earlier run is not requested again; a timeout or lost connection is.
        refusal = self.store.pdf_link_refusal(svid, source["oa_pdf_url"])
        if (refusal is not None and not self._needs_other_copy(run["research_id"], source, refusal)) or (limit is not None and downloads >= limit):
            return 0
        if refusal is None:
            await self._fetch_pdf(run, source)
            refusal = self.store.pdf_link_refusal(svid, source["oa_pdf_url"])
        if refusal is not None and self._needs_other_copy(run["research_id"], source, refusal):
            await self._find_other_copy(run, source, other_versions=other_versions)
        return 1

    async def _review(self, run: dict[str, Any], scope: dict[str, Any], answer_id: str, draft: dict[str, Any]) -> None:
        """Ask the reviewer model whether each claim's cited passages support it; the answer itself is never changed."""
        run_id = run["id"]
        reviewer = effective_reviewer(scope, self.store.setting("reviewer"))
        if reviewer is None or not draft["claims"] or self.store.answer_review(answer_id) is not None:
            return
        self._checkpoint(run_id)
        self.store.update_run(run_id, stage="claim_check")
        claims = [{k: c[k] for k in ("claim_label", "text", "support_type", "passage_ids")} for c in draft["claims"]]
        passages = [self.store.passage(pid) for pid in dict.fromkeys(pid for c in claims for pid in c["passage_ids"])]
        source_ids = list(dict.fromkeys(p["source_version_id"] for p in passages))
        key = "answer_review"
        try:
            output = await self._model_step(run, scope, key, key, source_ids=source_ids, passage_rows=passages,
                                            claims=claims, model=reviewer, optional=True)
        except OptionalStepFailed as failure:
            step = self.store.step(run_id, key, f"model:{key}")
            self.store.save_answer_review(answer_id, run["research_id"], run_id, step["id"], None, "failed",
                                          {"detail": failure.detail}, failure.reason)
            return
        self._checkpoint(run_id)
        step = self.store.step(run_id, key, f"model:{key}")
        if output.get("invalid"):
            self.store.save_answer_review(answer_id, run["research_id"], run_id, step["id"], output["step_input_id"], "failed",
                                          {"issues": output["issues"]}, "invalid_model_output")
            return
        self.store.save_answer_review(answer_id, run["research_id"], run_id, step["id"], output["step_input_id"], "completed",
                                      output["result"])

    async def _fetch_pdf(self, run: dict[str, Any], source: dict[str, Any]) -> None:
        from deixis.workflow import file_restore, text_retry

        step = self.store.step(run["id"], f"fetch:{source['id']}", "fetch_pdf")
        if step["status"] in ("succeeded", "failed"):
            return
        self.store.start_step(step["id"])
        self.store.add_usage(run["id"], "downloads")
        result = await self.deps.fetch_pdf(source["oa_pdf_url"])
        if result.status != "ok":
            self.store.finish_step(step["id"], "failed", error_code=f"fetch_{result.status}",
                                   error={"http_status": result.http_status, "error": result.error, "url": source["oa_pdf_url"]})
            return
        sha = hashlib.sha256(result.data).hexdigest()
        papers = self.deps.settings.papers_dir
        papers.mkdir(parents=True, exist_ok=True)
        try:
            placement = await file_restore.store_pdf_file(self.store, papers, self.deps.settings.recovery_dir, result.data,
                                                          caller="run_fetch", research_id=run["research_id"])
            read = await text_retry.read_verified(self.store, papers, self.deps.settings.recovery_dir,
                storage_path=placement.path.name, sha256=sha, byte_size=len(result.data), lock=True)
        except (file_restore.FileRestoreRefused, text_retry.FileBusy) as exc:
            refused = isinstance(exc, file_restore.FileRestoreRefused)
            self.store.finish_step(step["id"], "failed",
                error_code="fetch_file_repair_refused" if refused else "fetch_file_busy",
                error={"url": source["oa_pdf_url"], **({"code": exc.code} if refused else {})})
            return
        path = placement.path
        extraction = read.extraction
        if fast_path.enforces(run["budget"], "read"):
            from deixis.workflow.background_fetch import before_publish
            await before_publish(self, run, source["work_id"])
        asset_id = self.store.add_asset_with_pages(
            source["id"], sha, len(result.data), path.name, "download", result.final_url, None,
            extraction, pdf.EXTRACTION_VERSION, pdf.chunk_page,
            input_observation=read.observation,
        )
        status = "succeeded" if extraction.status in ("succeeded", "partial") else "partial"
        self.store.finish_step(step["id"], status, output={"asset_id": asset_id, "extraction_status": extraction.status,
                                                          "page_count": extraction.page_count,
                                                          "passage_count": self.store.asset_passage_count(asset_id)},
                               error_code=None if status == "succeeded" else f"extraction_{extraction.status}")

    def _needs_other_copy(self, research_id: str, source: dict[str, Any], refusal: dict[str, Any]) -> bool:
        """A blocked (403) or missing (404) link leads to one lookup per source; "Find PDF" repeats it on request."""
        # A lookup history that was interrupted, or has a route that did not answer, is resumed here too (D248).
        return (refusal["http_status"] in (403, 404) and normalize_doi(source["doi"]) is not None
                and (not self.store.pdf_discoveries(research_id, source["id"])
                     or self._unanswered_lookups(research_id, source["id"]) > 0))

    async def _find_other_copy(self, run: dict[str, Any], source: dict[str, Any],
                               other_versions: bool = False) -> dict[str, Any]:
        """Look the DOI up in Unpaywall, OpenAlex, Crossref and CORE and retrieve a copy of the same version.

        Web search stays the user's "Find PDF" action, and a copy of uncertain version waits for the user to confirm it.
        `other_versions` is the full-text retrieval run's addition (D83): a verified copy of a different declared
        version is attached to its own row under the work. An answer run and a PDF collection run never pass it.
        """
        from deixis.workflow import file_restore, text_retry

        step = self.store.step(run["id"], f"other_copy:{source['id']}", "pdf_other_copy")
        self.store.start_step(step["id"])
        settings = self.deps.settings
        try:
            found = await acquisition.acquire_for_source(
                self.store, run["research_id"], source["id"], self.deps.http, settings.papers_dir, settings.contact_email, None,
                self.deps.fetch_pdf, core_key=CONNECTORS["core"].api_key(), web_search=False, other_versions=other_versions,
                xml_fetcher=self.deps.fetch_xml, recovery_dir=settings.recovery_dir,
                openalex_budget=self._openalex_budget_of(run["id"]), workflow_run_id=run["id"],
                **({"before_publish": lambda: self._fast_fetch_publish(run, source["work_id"])}
                   if fast_path.enforces(run["budget"], "read") else {}),
            )
        except (file_restore.FileRestoreRefused, text_retry.FileBusy) as exc:
            refused = isinstance(exc, file_restore.FileRestoreRefused)
            self.store.finish_step(step["id"], "failed",
                error_code="fetch_file_repair_refused" if refused else "fetch_file_busy",
                error={"code": exc.code} if refused else None)
            return {"source_version_id": source["id"], "lookups": len(self.store.pdf_discoveries(run["research_id"], source["id"])),
                    "asset_id": None, "candidates": len(self.store.pdf_candidates(source["id"])),
                    "pdf_found": self.store.has_asset(source["id"])}
        if found["asset_id"] is None:
            self.store.finish_step(step["id"], "failed", error_code="no_other_copy", error={"candidates": found["candidates"]})
            return found
        asset = self.store.asset(found["asset_id"])
        status = "succeeded" if asset["extraction_status"] in ("succeeded", "partial") else "partial"
        self.store.finish_step(step["id"], status, output={"asset_id": asset["id"], "extraction_status": asset["extraction_status"],
                                                          "page_count": asset["page_count"],
                                                          "passage_count": self.store.asset_passage_count(asset["id"]),
                                                          **({"source_version_id": found["lookup_version_id"]}
                                                             if found.get("lookup_version_id") else {})},
                               error_code=None if status == "succeeded" else f"extraction_{asset['extraction_status']}")
        return found

    async def _fast_fetch_publish(self, run: dict[str, Any], work_id: str | None = None) -> None:
        from deixis.workflow.background_fetch import before_publish
        await before_publish(self, run, work_id)


    def _stop_requested(self, run_id: str, revision: int) -> bool:
        """Whether `_checkpoint` would stop the run now, without writing the stop: a pause, a cancellation or a newer
        question revision, or, inside the overlap, the other arm's stop (slice 17a)."""
        held = self._held.get(run_id)
        if held is not None and held.halted:
            return True
        run = self.store.run(run_id)
        guard = getattr(self, "_small_batch_guard", None)
        return (bool(guard and guard["run_id"] == run_id and guard.get("halted"))
                or run["status"] in ("pause_requested", "cancelled", "paused", "failed")
                or self.store.research(run["research_id"])["current_scope_revision"] != revision)

    def _stop_work_if_requested(self, run: dict[str, Any]) -> None:
        """Stop this work; the small-batch coordinator drains in-flight work before recording the pause."""
        if self._stop_requested(run["id"], run["scope_revision"]):
            raise RunStopped


    def _chain_state(self, research_id: str, revision: int) -> tuple[set[str], list[str], list[str]]:
        """The works citation chaining brought under this question revision, the keyword order and the chain's order
        (D95): the latest chain filter's list, the latest keyword ranking and the latest chain ranking.

        When the chain ran, the keyword order is read by work: a chain record joined to a keyword work can head it
        now, and the work keeps the place its earlier head had. Without a chain the keyword order is read as stored.
        """
        decisions = DecisionStore(self.store)
        stored = self.store.latest_step_output(research_id, "chain_filter", revision)
        order = decisions.latest_ranking(research_id, revision) or []
        if stored is None:
            return set(), order, []
        # Every work only a chain found under this revision, an earlier discovery run's too: none is a keyword work.
        # The stored list is not merged in: a work it names that a later keyword search found is a keyword work now.
        heads = self.store.work_heads(research_id)
        chained = {heads[work_id] for work_id in self.store.chain_only_works(research_id, revision) if work_id in heads}
        return chained, self._current_heads(research_id, order), decisions.latest_chain_ranking(research_id, revision)

    def _current_heads(self, research_id: str, order: list[str]) -> list[str]:
        """These records as the heads of their works now, in the same order, each work once (D95)."""
        heads = self.store.work_heads(research_id)
        work_of = self.store.work_ids(order)
        return list(dict.fromkeys(heads.get(work_of.get(svid), svid) for svid in order))

    def _fulltext_works(self, research_id: str, chained: set[str] = frozenset()) -> list[dict[str, Any]]:
        """Every work of the research with what the retrieval plan reads about it, in a few whole-research queries.

        Asking per record cost a second on 2,000 candidates on the thread the API answers from (slices 05 and 07),
        and this runs on the same thread. `chained` names the heads citation chaining brought (D95).
        """
        decisions = DecisionStore(self.store)
        stale_key = decisions.staleness_key(research_id)
        versions = ranking_rules._versions(self.store, research_id)
        heads = self.store.work_heads(research_id)
        with_text = {row[0] for row in self.store.conn.execute(
            "SELECT DISTINCT p.source_version_id FROM passages p"
            " JOIN corpus_memberships m ON m.source_version_id = p.source_version_id"
            "  AND m.research_id = ? AND m.removed_at IS NULL"
            " JOIN source_assets a ON a.id = p.asset_id AND a.removed_at IS NULL"
            "  AND a.extraction_version IS p.extraction_version"
            " WHERE p.kind = 'pdf_page'", (research_id,))}
        held: dict[tuple[str, str], dict[str, Any]] = {}
        for row in self.store.conn.execute(
            "SELECT * FROM stage_decisions WHERE research_id = ? AND superseded_at IS NULL", (research_id,)
        ):
            held[(row["source_version_id"], row["stage"])] = dict(row)
        selections = {row["source_version_id"]: {"state": row["state"], "origin": row["origin"]}
                      for row in self.store.conn.execute(
                          "SELECT source_version_id, state, origin FROM selections WHERE research_id = ?", (research_id,))}
        # A person's file and the state of its reading request (slice 18b); a version with none carries None.
        person = {svid: {"status": request["status"], "asset_id": request["asset_id"],
                         "order": [request["asset_at"], request["asset_id"]]}
                  for svid, request in self.store.person_files(research_id).items()}

        by_work: dict[str, list[str]] = {}
        for version in versions.values():
            by_work.setdefault(version["work_id"], []).append(version["id"])

        def decision(svid: str, stage: str) -> dict[str, Any] | None:
            row = held.get((svid, stage))
            return None if row is None else {"reason_code": row["reason_code"], "decided_by": row["decided_by"],
                                             "stale": decisions.is_stale(row, stale_key)}

        return [{"work_id": work_id, "head": head, "selection": selections.get(head), "chained": head in chained,
                 "versions": [{"id": svid, "has_text": svid in with_text,
                               "abstract": decision(svid, "abstract"), "fulltext": decision(svid, "fulltext"),
                               "person": person.get(svid)}
                              for svid in sorted(by_work.get(work_id, []))]}
                for work_id, head in sorted(heads.items())]


    async def _fetch_work_text(self, run: dict[str, Any], head: str) -> dict[str, Any]:
        """Try this work's routes in order and report what the attempt found; writes no decision itself.

        The routes are the ones an answer run already uses: the record's own open link, then the research's other
        versions of the same work (D48), then one DOI lookup for another copy. Web search stays off — it is the
        user's "Find PDF" action (SW10.4) — and no second downloader, arXiv title search or Europe PMC request is
        opened here.
        """
        run_id, rid = run["id"], run["research_id"]
        source = self.store.source(head)
        route = None
        # A refused link opens the DOI lookup inside `_acquire_pdf`, and that lookup is this work's one lookup: it
        # has to be the one that may open a row for another version, or no later one ever would.
        await self._acquire_pdf(run, head, 0, None, other_versions=True)
        if self.store.has_pdf_text(head):
            route = "other_copy" if self._other_copy_found(run_id, head) else "record_link"
        elif self._opened_version_has_text(run_id, head):
            route = "lookup_version"
        else:
            for other in self.store.work_versions(rid, head):
                if not self.store.has_pdf_text(other):
                    self._stop_work_if_requested(run)
                    await self._acquire_pdf(run, other, 0, None)
                if self.store.has_pdf_text(other):
                    route = "work_version"
                    break
        # Wider than D35, by name: `_needs_other_copy` opens the lookup only after a link that answered 403 or 404,
        # so a work with no open link at all — most closed publisher records — would never be looked up, and
        # SW10.5's "the twin first, then the author's copy" would never be tried. An answer run and a PDF
        # collection run keep the narrow trigger.
        # The lookup rows are the research's history, not this run's: a lookup or a copy that did not answer an
        # earlier run is asked again here, or the work would be planned by every later run and settled by none.
        if route is None and normalize_doi(source["doi"]) and (
                not self.store.pdf_discoveries(rid, head) or self._unanswered_lookups(rid, head)):
            self._stop_work_if_requested(run)
            found = await self._find_other_copy(run, source, other_versions=True)
            opened = found.get("lookup_version_id")
            if opened and self.store.has_pdf_text(opened):
                route = "lookup_version"
            elif self.store.has_pdf_text(head):
                route = "other_copy"

        versions = [head, *self.store.work_versions(rid, head)]
        has_text = any(self.store.has_pdf_text(svid) for svid in versions)
        has_asset = any(self.store.has_asset(svid) for svid in versions)
        unanswered = self._unanswered_routes(run_id, rid, versions)
        deferred = sum(self._quota_deferred(rid, svid) for svid in versions)
        read = self._text_version(rid, head) if has_text else head
        asset_id = self._current_asset(read) if has_text else None
        return {"work_id": source["work_id"], "head": head, "read_version": read,
                "version_label": self.store.source(read)["version_label"], "asset_id": asset_id, "route": route,
                "identity": identity.check(self._pdf_head_text(read), [self.store.source(s) for s in versions])
                            if has_text else None,
                "code": fulltext.settled_code({"has_text": has_text, "has_asset": has_asset,
                                               "unanswered": unanswered + deferred}),
                "requests_unanswered": unanswered, "quota_deferred": deferred}

    def _other_copy_step(self, run_id: str, svid: str) -> dict[str, Any]:
        """This run's DOI lookup step for the record, read without opening one: `store.step` would leave a step
        that never runs on the timeline of every work that needed no lookup."""
        row = self.store.conn.execute(
            "SELECT status, output_json FROM run_steps WHERE run_id = ? AND operation_key = ?",
            (run_id, f"other_copy:{svid}")).fetchone()
        return {"status": row["status"], "output": json.loads(row["output_json"] or "{}")} if row else {"status": None, "output": {}}

    def _other_copy_found(self, run_id: str, svid: str) -> bool:
        return self._other_copy_step(run_id, svid)["status"] in ("succeeded", "partial")

    def _opened_version_has_text(self, run_id: str, svid: str) -> bool:
        """Whether this run's DOI lookup for the record opened a row for another version, and that row has text."""
        opened = self._other_copy_step(run_id, svid)["output"].get("source_version_id")
        return bool(opened) and self.store.has_pdf_text(opened)

    def _current_asset(self, svid: str) -> str | None:
        row = self.store.conn.execute(
            "SELECT id FROM source_assets WHERE source_version_id = ? AND removed_at IS NULL"
            " ORDER BY retrieved_at DESC, id DESC LIMIT 1", (svid,)).fetchone()
        return row["id"] if row else None

    def _pdf_head_text(self, svid: str) -> str:
        """The start of this record's stored PDF text, for the identity check. A paper names itself on its first
        page; a later page may quote any number of other papers."""
        pages = [p["text"] for p in self.store.passages_for(svid) if p["kind"] == "pdf_page"]
        return "\n".join(pages)[:identity.MATCH_TEXT_CHARS]

    def _unanswered_routes(self, run_id: str, research_id: str, svids: list[str]) -> int:
        """How many routes tried for this work did not answer: a timeout, a lost connection, a 429 or a 5xx.

        A link that refused, a 404, a lookup with no result and a route that was never configured have all
        answered, and a work for which every route answered has no open full text. The same distinction D35 draws
        between a link that refused — which is not requested again — and one that timed out.
        """
        unanswered = 0
        for svid in svids:
            for row in self.store.conn.execute(
                "SELECT error_code, json_extract(error_json, '$.http_status') AS http_status FROM run_steps"
                " WHERE run_id = ? AND operation_key = ? AND kind = 'fetch_pdf' AND status = 'failed'",
                (run_id, f"fetch:{svid}"),
            ):
                status = row["http_status"]
                unanswered += (row["error_code"] in UNANSWERED_FETCH_CODES
                               or (row["error_code"] == "fetch_http_error" and bool(status)
                                   and (status == 429 or status >= 500)))
            unanswered += self._unanswered_lookups(research_id, svid)
        return unanswered

    def _unanswered_lookups(self, research_id: str, svid: str) -> int:
        """How many of this record's DOI lookups and looked-up copies did not answer the last time they were asked.

        A lookup is stored once per asking, so only each provider's newest row counts: a 429 an earlier run met
        says nothing once the same provider has answered since. A copy's row is updated in place.
        """
        latest = {d["provider"]: d for d in self.store.pdf_discoveries(research_id, svid, retry_after=True)}
        # Each lookup is stored as it returns, so an interruption can leave a lookup history that stops part way: a
        # route of the four that has no row was never asked, and the work is not settled without it.
        missing = len(acquisition.REQUIRED_ROUTES - latest.keys()) if latest else 0
        # A lookup OpenAlex's daily budget refused is asked again once its reset has passed, and until then it is
        # deferred (`_quota_deferred`), not unanswered: asking before the reset would only be refused again.
        return (missing
                + sum(1 for d in latest.values() if d["status"] in UNANSWERED_LOOKUP_STATUSES and not self._budget_wait(d))
                + sum(1 for c in self.store.pdf_candidates(svid) if c["access_status"] in UNANSWERED_LOOKUP_STATUSES))

    @staticmethod
    def _budget_wait(lookup: dict[str, Any]) -> bool:
        """Whether this lookup row is one OpenAlex's budget refused whose reset has not come yet."""
        return (lookup["error_code"] == acquisition.QUOTA_EXHAUSTED
                and acquisition.OpenAlexBudget(reset_at=lookup["retry_after"]).exhausted)

    def _quota_deferred(self, research_id: str, svid: str) -> int:
        """How many of this record's newest lookups wait for OpenAlex's daily budget to return. Such a lookup was not
        answered, so it says nothing about whether an open copy exists."""
        latest = {d["provider"]: d for d in self.store.pdf_discoveries(research_id, svid, retry_after=True)}
        return sum(1 for d in latest.values() if self._budget_wait(d))

    def _write_fulltext_codes(self, run: dict[str, Any], step_id: str | None,
                              writes: list[tuple[str, str]]) -> dict[str, int]:
        """Write these full-text decisions and derive the selection of each work they touched.

        The user's own decision is skipped, never swallowed (AGENTS.md, User Authority), and a decision that
        already says this is not closed and written again merely because the step identifier is new — so a second
        retrieval run adds no row for what it re-derives. Every code written here is `unresolved`, which derives
        to the `pending` the record already had: no work is included or excluded by this run.
        """
        rid = run["research_id"]
        decisions = DecisionStore(self.store)
        stale_key = decisions.staleness_key(rid)
        written: dict[str, int] = {}
        touched: set[str] = set()
        for svid, code in writes:
            held = decisions.current(rid, svid, "fulltext")
            if held is not None and held["decided_by"] == "human":
                continue
            if not fulltext.should_write(held, code, bool(held) and decisions.is_stale(held, stale_key)):
                continue
            try:
                decisions.record(rid, svid, code, step_id=step_id)
            except HumanDecisionStands:
                continue
            written[code] = written.get(code, 0) + 1
            touched.add(self.store.source(svid)["work_id"])
        for work_id in sorted(touched):
            decisions.derive_selection(rid, work_id)
        return dict(sorted(written.items()))


    # ---- the full-text fetch that overlaps an sw discovery run (slice 17a) -------------------

    def _wake_fetch(self, run_id: str, prefix: str | None = None, number: int | None = None) -> None:
        """Tell the fetch arm that an abstract decision was written: a batch closed, or a code step ended."""
        held = self._held.get(run_id)
        if held is None:
            return
        if prefix is not None:
            held.closed.setdefault(prefix, set()).add(number)
        held.wake.set()


    def _claims(self, run_id: str) -> dict[str, dict[str, Any]]:
        """This run's claimed works, by `work_id`, in the order they were claimed."""
        return {row["operation_key"].split(":", 1)[1]: {**dict(row), "output": json.loads(row["output_json"] or "{}")}
                for row in self.store.conn.execute(
                    "SELECT operation_key, status, attempt, output_json FROM run_steps"
                    " WHERE run_id = ? AND kind = 'code:fulltext_work' ORDER BY rowid", (run_id,))}

    def _claim(self, run_id: str, work_id: str, early: bool, group: str | None) -> None:
        """Open the work's step with its claim, in one transaction; a claim is never taken back (item 2)."""
        self.store.step(run_id, f"fulltext_work:{work_id}", "code:fulltext_work",
                        output={"claim": {"claimed_at": now(), "early": early, "group": group}})


    async def _overlap_work(self, run: dict[str, Any], work_id: str) -> None:
        """One claimed work's attempt, as `_fulltext_work`, keyed by the work and settled in one transaction (item 2).

        The step's output, the `fulltext_work_settled` event and the work's code are written together, so none of them
        exists without the others. A person's full-text decision on the version stands: then no code is written, and
        the step and the event say so. A step a crash left `outcome_unknown` is sent again, at most
        `FULLTEXT_WORK_ATTEMPTS` starts in all; then it is closed as not settled and a later run tries it (D18).
        """
        run_id, rid = run["id"], run["research_id"]
        step = self.store.existing_step(run_id, f"fulltext_work:{work_id}")
        if step["status"] in ("succeeded", "failed"):
            return
        claim = (step["output"] or {}).get("claim")
        if step["status"] == "outcome_unknown" and step["attempt"] >= fulltext.FULLTEXT_WORK_ATTEMPTS:
            self.store.finish_step(step["id"], "failed", output={"claim": claim, "work_id": work_id},
                                   error_code="fetch_not_settled", error={"work_id": work_id, "attempts": step["attempt"]})
            return
        head = self.store.work_heads(rid).get(work_id)
        if head is None:  # the work left the research since it was claimed
            self.store.finish_step(step["id"], "failed", output={"claim": claim, "work_id": work_id},
                                   error_code="fulltext_work_failed", error={"work_id": work_id, "error": "no head"})
            return
        self.store.start_step(step["id"])
        try:
            output = await self._fetch_work_text(run, head)
        except RunStopped:
            # Stopped between two routes: nothing is settled and the step does not stay `running` under a stopped run.
            # A resumed run sends the work again (the routes that answered are not asked twice).
            self.store.finish_step(step["id"], "cancelled", output={"claim": claim, "work_id": work_id},
                                   error_code="run_stopped")
            raise
        except Exception as exc:  # noqa: BLE001 - one work's failure must not end the run
            self.store.finish_step(step["id"], "failed", output={"claim": claim, "work_id": work_id},
                                   error_code="fulltext_work_failed",
                                   error={"head": head, "error": f"{type(exc).__name__}: {exc}"})
            return
        output["claim"] = claim
        if fast_path.enforces(run["budget"], "read"):
            try:
                await self._fast_fetch_publish(run, work_id)
            except RunStopped:
                self.store.finish_step(step["id"], "cancelled", output=output, error_code="run_stopped")
                raise
        if output["code"] is None:
            # Waiting for OpenAlex's budget is its own cause: nothing was tried that could settle the work, and the
            # work stays open for the first run after the reset.
            cause = "quota_deferred" if output["quota_deferred"] and not output["requests_unanswered"] else "fetch_not_settled"
            self.store.finish_step(step["id"], "failed", output=output, error_code=cause,
                                   error={"head": head, "requests_unanswered": output["requests_unanswered"],
                                          "quota_deferred": output["quota_deferred"]})
            return
        decisions = DecisionStore(self.store)
        with transaction(self.store.conn):
            if self.store.research(rid)["current_scope_revision"] != run["scope_revision"]:
                # The question changed while the file was on its way: a code written now would be dated under the new
                # revision. The answer is kept on the step and nothing is decided; the run is cancelled at its stop.
                self.store.finish_step(step["id"], "cancelled", output=output, error_code="scope_revised")
                return
            held = decisions.current(rid, output["read_version"], "fulltext")
            human = held is not None and held["decided_by"] == "human"
            self._write_fulltext_codes(run, step["id"], [(output["read_version"], output["code"])])
            now_held = decisions.current(rid, output["read_version"], "fulltext")
            output["code_written"] = (not human and now_held is not None
                                      and now_held["reason_code"] == output["code"])
            output["held_by"] = "human" if human else None
            self.store.finish_step(step["id"], "succeeded", output=output)
            self.store._event(rid, "fulltext_work_settled", {
                "run_id": run_id, "work_id": work_id, "head": output["head"], "read_version": output["read_version"],
                "code": output["code"] if output["code_written"] else None, "asset_id": output["asset_id"],
                "step_id": step["id"]}, run_id)

    async def _fulltext_adjudication(self, run: dict[str, Any], scope: dict[str, Any], *,
                                    batch_key: str | None = None, order: list[str] | None = None,
                                    read_limit: int | None = None,
                                    cutoff: Callable[[], bool] | None = None) -> None:
        """Two model runs per work, then a code decision from the pair (D85).

        The plan is frozen before any call. A work is sent only when every call it still owes fits in the run's
        budget; a work at the end of the plan that no longer fits is not read and gets no decision. Both runs of
        one work may be in flight together. The decision is written on the event loop, in one short transaction,
        and only while this run is still the active one at this scope revision. A response that arrives after the
        run stopped is stored as a step and writes nothing, because `_send_through_limiter` does not apply it.

        A repair is not reserved up front. With the limiter at one, the next work is pulled only after the call
        in flight has returned, so a repair already in `usage` keeps a later work from being sent. With a higher
        limit the generator can pull a later work before that repair returns; the end of the plan is then not
        guaranteed to be the part left unread.
        """
        run_id, revision = run["id"], run["scope_revision"]
        plan = self._adjudication_plan(run, scope, batch_key=batch_key, order=order, read_limit=read_limit)
        works = plan["works"]
        if plan.get("reason") == "no_criterion" or not works:
            self._adjudication_summary(run, plan, batch_key=batch_key)
            return
        spent_before = self.store.run(run_id)["usage"].get("model_calls", 0)
        submitted = 0
        collected: dict[str, dict[int, dict[str, Any] | None]] = {}
        closed: set[str] = set()
        cutoff_heads: set[str] = set()
        items = {item["head"]: item for item in works}
        answered = {s["operation_key"] for s in self.store.run_steps(run_id)
                    if s["kind"] == "model:fulltext_adjudication"
                    and (s["status"] == "succeeded" or s["error_code"] in ("invalid_model_output", "model_read_cutoff"))}

        def jobs() -> Iterator[_AdjudicationJob]:
            nonlocal submitted
            for item in works:
                head, read_version = item["head"], item["read_version"]
                if batch_key and head not in (order or []):
                    continue
                if not self._adjudication_member(run["research_id"], head, read_version):
                    continue
                if self._human_decided_fulltext(run["research_id"], head, read_version):
                    continue  # a person decided the work after the plan was frozen (slice 16)
                if not self._file_holds(item):
                    continue  # the file the plan froze is no longer in use as it was: not read here (slice 18b)
                owed = [run_no for run_no in range(1, FULLTEXT_RUNS + 1)
                        if f"fulltext_adjudication:{head}:{run_no}" not in answered]
                if owed and cutoff is not None and cutoff():
                    return
                if owed and not self._reserve_model_pair(run,
                        [f"fulltext_adjudication:{head}:{n}" for n in owed], submitted, spent_before):
                    return
                for run_no in range(1, FULLTEXT_RUNS + 1):
                    still_owed = run_no in owed
                    guard = getattr(self, "_small_batch_guard", None)
                    reserved = guard.get("reserved_calls") if guard and guard["run_id"] == run_id else None
                    if still_owed and reserved is None and not self._model_calls_left(run, 1, submitted, spent_before):
                        # A repair on an earlier call of this work used the room this call needed. The run
                        # finishes; this work is not given a decision from one run.
                        return
                    submitted += still_owed
                    yield _AdjudicationJob(f"fulltext_adjudication:{head}:{run_no}", head, read_version, run_no)

        async def call(job: _AdjudicationJob) -> dict[str, Any] | None:
            nonlocal submitted
            if job.key not in answered and cutoff is not None and cutoff():
                cutoff_heads.add(job.head)
                submitted -= 1
                return None
            if not self._adjudication_member(run["research_id"], job.head, job.read_version):
                return None
            # Checked again once the limiter let the call through: a person may have decided the work while it
            # waited. No step is opened and the call is not charged to the budget (slice 16). Checked once more before
            # every send, the first and each resend (`_model_step`).
            def undecided(rows: list[dict[str, Any]]) -> list[dict[str, Any]] | None:
                return None if self._human_decided_fulltext(run["research_id"], job.head, job.read_version) else rows

            # The file is checked once more before the call, as the plan froze it (slice 18b, decision 6).
            if undecided([]) is None or not self._file_holds(items[job.head]):
                submitted -= f"fulltext_adjudication:{job.head}:{job.run_no}" not in answered
                return {"human_decided": True}
            try:
                output = await self._adjudication_call(run, scope, plan, job, self.deps.limiter, undecided)
                if output is not None and output.get("cutoff"):
                    cutoff_heads.add(job.head)
                    return None
                return output
            except RunStopped:
                raise
            except Exception:
                if (run["budget"].get("inspection") or {}).get("runner_version", 1) >= 4:
                    raise
                # One work's unexpected failure is recorded by not deciding it. The rest of the run continues (D18).
                return None

        def close_ready(completed: list[tuple[dict[str, Any] | None, _AdjudicationJob]]) -> None:
            for output, job in completed:
                collected.setdefault(job.head, {})[job.run_no] = output
            for head in sorted(collected):
                if head in closed or len(collected[head]) < FULLTEXT_RUNS:
                    continue
                if head in cutoff_heads:
                    closed.add(head)
                    continue
                if any(self._unsent(run_id, f"fulltext_adjudication:{head}:{run_no}")
                       for run_no in range(1, FULLTEXT_RUNS + 1)):
                    # One run of the work was not sent: nothing is written from the other, even if the person's
                    # decision was taken back since. Read from the stored steps, as a resumed run reads them.
                    closed.add(head)
                    continue
                try:
                    self._checkpoint(run_id, revision)
                    self._close_adjudication(run, items[head], plan,
                                             [collected[head][run_no] for run_no in range(1, FULLTEXT_RUNS + 1)])
                except RunStopped:
                    raise
                except Exception:
                    if (run["budget"].get("inspection") or {}).get("runner_version", 1) >= 4:
                        raise
                    pass
                closed.add(head)

        stop = await self._send_through_limiter(run, jobs(), call, close_ready)
        if stop is not None:
            raise stop
        self._adjudication_summary(run, plan, batch_key=batch_key)

    def _human_decided_fulltext(self, research_id: str, head: str, read_version: str | None = None) -> bool:
        """Whether a person decided the full-text stage of this head's work, on any version of it (slice 16).

        A person's `human_pdf_wrong` on another version does not count while the version read carries a person's
        file asking to be read (slice 18b, decision 3); every other decision of theirs counts as before."""
        work_id = self.store.source(head)["work_id"]
        if work_id not in DecisionStore(self.store).human_decided_works(research_id, "fulltext"):
            return False
        asked = read_version is not None and read_version in self.store.person_files(research_id, work_id)
        if not asked:
            return True
        return any(row["reason_code"] != "human_pdf_wrong" or row["source_version_id"] == read_version
                   for row in self.store.conn.execute(
                       "SELECT d.reason_code, d.source_version_id FROM stage_decisions d"
                       " JOIN source_versions v ON v.id = d.source_version_id"
                       " JOIN corpus_memberships m ON m.research_id = d.research_id"
                       " AND m.source_version_id = d.source_version_id AND m.removed_at IS NULL"
                       " WHERE d.research_id = ? AND v.work_id = ? AND d.stage = 'fulltext' AND d.decided_by = 'human'"
                       " AND d.superseded_at IS NULL", (research_id, work_id)))

    def _adjudication_member(self, research_id: str, head: str, read_version: str) -> bool:
        """Whether both records are still in this research. A purged member is skipped, not crashed on."""
        return self.store.is_active_member(research_id, head) and self.store.is_active_member(research_id, read_version)

    def _adjudication_plan(self, run: dict[str, Any], scope: dict[str, Any], *,
                           batch_key: str | None = None, order: list[str] | None = None,
                           read_limit: int | None = None) -> dict[str, Any]:
        """Freeze which works are read, on which version, and which PDFs are not confirmed as the work's own.

        Identity is computed here, from the text and the work's versions, never from a retrieval run's step.
        An unconfirmed PDF is decided `pdf_identity_unconfirmed` with no model call and does not consume the
        read limit. A file the user supplied is confirmed without that check.
        """
        run_id, rid = run["id"], run["research_id"]
        key = f"{batch_key}:adjudication_plan" if batch_key else "adjudication_plan"
        step = self.store.step(run_id, key, "code:adjudication_plan")
        if step["status"] == "succeeded":
            return step["output"]
        self.store.start_step(step["id"])
        limit = run["budget"]["max_fulltext_reads"]
        if read_limit is not None:
            limit = read_limit
        frozen = self.store.frozen_criterion(rid, scope["question"], scope.get("steering"))
        if frozen is None:
            plan = {"limit": limit, "criterion": None, "works": [], "not_reached": 0,
                    "identity_unconfirmed": 0, "reason": "no_criterion"}
            self.store.finish_step(step["id"], "succeeded", output=plan)
            return plan
        parts = frozen["parts"] or []
        sent = ([{"name": "criterion", "definition": frozen["criterion"]}] if not parts
                else [{"name": part["name"], "definition": part["definition"],
                       **({"inclusion_role": part["role"]} if part.get("role") in ("core", "aspect") else {})}
                      for part in parts])
        # The part the question names as the comparator is marked, so the reading applies its comparator line to it
        # (slice 28). A criterion without that required role is sent exactly as before.
        sent = adjudication.mark_comparator(sent, frozen["question_elements"], frozen["required_roles"])
        criterion = {"criterion": frozen["criterion"], "parts": sent, "cue_phrases": frozen["cue_phrases"],
                     "protocol_revision": frozen["protocol_revision"]}
        # Chained works are read after the keyword order, in the chain's own order (D95); the limit is the same.
        chained, legacy_order, chain_order = self._chain_state(rid, run["scope_revision"])
        order = order if batch_key else legacy_order + chain_order
        corpus = self._fulltext_works(rid, chained)
        if batch_key:
            corpus = [work for work in corpus if work["head"] in (order or [])]
        by_head = {work["head"]: work for work in corpus}
        from deixis.workflow import late_revision
        late = late_revision.row_for_run(self.store, run)
        late_versions = ({item["head"]: item["source_version_id"] for item in json.loads(late["works_json"])}
                         if late else {})
        eligible = adjudication.read_plan(corpus, order, len(corpus))
        if batch_key:
            eligible["works"] = [head for head in order if head in eligible["works"]]
        readable: list[dict[str, Any]] = []
        unconfirmed: list[tuple[str, str]] = []
        for head in eligible["works"]:
            # A person's file not read yet is read on its own version (slice 18b, decision 8).
            person = adjudication.person_version(by_head[head]) or self._stale_person_version(rid, head)
            read = late_versions.get(head) or person or self._text_version(rid, head)
            versions = [head, *self.store.work_versions(rid, head)]
            if person == read or self._user_supplied_pdf(read):
                readable.append(self._plan_item(head, read))
                continue
            found = identity.check(self._pdf_head_text(read), [self.store.source(svid) for svid in versions])
            if found == "unconfirmed":
                unconfirmed.append((head, read))
            else:
                readable.append(self._plan_item(head, read))
        # What the reading's decisions rest on besides each work's file: the question revision and the criterion
        # digest, so a person's request is read only by a plan made under the same (slice 18b, decision 4).
        _, criterion_hash = DecisionStore(self.store).staleness_key(rid)
        plan = {"limit": limit, "criterion": criterion, "works": readable[:limit],
                "not_reached": len(readable) - len(readable[:limit]),
                "identity_unconfirmed": len(unconfirmed), "reason": None,
                "scope_revision": run["scope_revision"], "criterion_hash": criterion_hash}
        # The plan, the codes it writes and the person's requests it takes are one write (decision 4).
        with transaction(self.store.conn):
            self._write_adjudication_codes(run, step["id"], [(read, "pdf_identity_unconfirmed") for _, read in unconfirmed])
            self.store.finish_step(step["id"], "succeeded", output=plan)
            person_reading.plan_requests(self.store, run, plan)
        return plan

    def _text_version(self, rid: str, head: str) -> str:
        """The version whose PDF text a work's reading and retrieval look at: the answer's version when it has PDF text,
        else the first version with PDF text (a person's file the answer may not read yet), else the head (D48)."""
        read = self.store.answer_version(rid, head)
        if read is not None and self.store.has_pdf_text(read):
            return read
        return next((svid for svid in [head, *self.store.work_versions(rid, head)] if self.store.has_pdf_text(svid)),
                    head)

    def _stale_person_version(self, rid: str, head: str) -> str | None:
        """A version whose person's file was asked to be read under an older question or criterion and has not been
        read under this one: the reading reads it, in the group order, so the answer may use it after (decision 8)."""
        unread = self.store.unread_person_versions(rid, self.store.source(head)["work_id"])
        return next((svid for svid in [head, *self.store.work_versions(rid, head)]
                     if svid in unread and self.store.has_pdf_text(svid)), None)

    def _plan_item(self, head: str, read: str) -> dict[str, Any]:
        """One work of a reading plan: the version read, the file in use on it and its pages' digest (decision 6)."""
        asset_id = self._current_asset(read)
        return {"head": head, "read_version": read, "asset_id": asset_id,
                "page_digest": self.store.asset_page_digest(asset_id)}

    def _file_holds(self, item: dict[str, Any]) -> bool:
        """Whether the file a plan froze for this work is still the one in use, with the same pages (decision 6).

        A plan frozen before slice 18b names no file and is read as it always was."""
        if "asset_id" not in item:
            return True
        asset_id = self._current_asset(item["read_version"])
        return asset_id == item["asset_id"] and self.store.asset_page_digest(asset_id) == item["page_digest"]

    def _user_supplied_pdf(self, svid: str) -> bool:
        """A PDF the user added is the file they meant, and so is one a person confirmed from the queue (slice 16).
        Neither is held back for an identity check. The confirmation belongs to the file: a new file is checked."""
        if self.store.source(svid).get("origin") == "user_upload":
            return True
        asset_id = self._current_asset(svid)
        if not asset_id:
            return False
        asset = self.store.asset(asset_id)
        return asset.get("origin") == "user_upload" or bool(asset.get("identity_confirmed_at"))

    async def _adjudication_call(self, run: dict[str, Any], scope: dict[str, Any], plan: dict[str, Any],
                                 job: _AdjudicationJob, limiter: ModelCallLimiter | None,
                                 recheck: Callable[[list[dict[str, Any]]], list[dict[str, Any]] | None] | None = None,
                                 ) -> dict[str, Any] | None:
        """One run of one work. None when the output did not validate: that is an answer for this run, not a retry."""
        step = self.store.step(run["id"], job.key, "model:fulltext_adjudication")
        if step["status"] == "failed" and step["error_code"] == "invalid_model_output":
            return None
        if step["error_code"] == "model_read_cutoff":
            return {"cutoff": True}  # D258: a resumed run does not send it again
        passages = self._adjudication_passages(run["research_id"], scope, plan["criterion"], job.read_version)
        target = {"source_id": job.read_version, "criterion": plan["criterion"]["criterion"],
                  "parts": plan["criterion"]["parts"], "runs": FULLTEXT_RUNS, "run": job.run_no}
        output = await self._model_step(run, scope, job.key, "fulltext_adjudication", source_ids=[job.read_version],
                                        passage_rows=passages, adjudication_target=target, limiter=limiter,
                                        budget_short="skip", recheck=recheck)
        return None if output.get("invalid") else output

    def _adjudication_passages(self, research_id: str, scope: dict[str, Any], criterion: dict[str, Any],
                               svid: str) -> list[dict[str, Any]]:
        """The pages this call is shown, chosen when the call is sent and stored with its StepInput."""
        pages = [p for p in self.store.passages_for(svid) if p["kind"] == "pdf_page"]
        terms = self._topic_terms(research_id, scope)
        fts = " OR ".join(f'"{term}"' for term in terms)
        ranked = [p["id"] for p in self.store.search_passages([svid], fts, FULLTEXT_PASSAGES_PER_CALL * 3)]
        return adjudication.reading_list(pages, criterion, ranked, FULLTEXT_PASSAGES_PER_CALL,
                                         FULLTEXT_CRITERION_PASSAGES)["passages"]

    def _close_adjudication(self, run: dict[str, Any], item: dict[str, str], plan: dict[str, Any],
                            outputs: list[dict[str, Any] | None]) -> None:
        """Verify both runs' quotes on the pages they were shown and write one decision on the read version.

        A work a person decided while its calls were out gets neither a proposal nor a decision: the steps stay
        stored, and the person's answer stands (slice 16).
        """
        read = item["read_version"]
        if self._human_decided_fulltext(run["research_id"], item["head"], read):
            return
        parts = plan["criterion"]["parts"]
        decisions = DecisionStore(self.store)
        views: list[dict[str, Any] | None] = []
        last_step: str | None = None
        for run_no, output in enumerate(outputs, start=1):
            if not output or output.get("invalid") or not output.get("step_input_id"):
                views.append(None)
                continue
            payload = self.store.step_input_payload(output["step_input_id"])
            last_step = payload["step_id"]
            shown: dict[str, dict[str, Any]] = {}
            page_numbers: set[int] = set()
            for passage in payload["passages"]:
                page = (passage.get("locator") or {}).get("physical_page")
                shown[passage["passage_id"]] = {"physical_page": page}
                if isinstance(page, int):
                    page_numbers.add(page)
            stored = self.store.page_texts(read)
            pages = {page: stored[page] for page in page_numbers if page in stored}
            proposals = adjudication.proposals_of(parts, (output.get("result") or {}).get("parts") or [],
                                                  shown, pages, FULLTEXT_QUOTE_MIN_CHARS)
            for name, row in proposals.items():
                decisions.add_proposal(run["research_id"], read, "fulltext", payload["step_id"], run_no, row["label"],
                                       criterion_part=name, quote=row["quote"] or None,
                                       quote_verified=row["quote_verified"], quote_passage_id=row["passage_id"],
                                       quote_page=row["page"])
            views.append(adjudication.run_view(proposals, parts))
        code = adjudication.combine(views[0] if views else None, views[1] if len(views) > 1 else None)
        # On a criterion with a comparator part, two all-negative runs exclude nothing by themselves (slice 28).
        code, comparator_note = adjudication.with_comparator(code, adjudication.comparator_part(parts))
        # Two agreeing runs on a version whose own title names a study protocol decide nothing by themselves: the
        # work goes to the queue with the combined code in the note (slice 26).
        code, title_note = adjudication.with_title(code, self.store.source(read)["title"])
        note = title_note or comparator_note
        if code is None or not self._file_holds(item):
            # The file the plan froze moved while the calls were out: nothing is decided from its reading (decision 6).
            return
        # The same code read from other pages than the decision it would keep (a person's file extracted again and
        # read again) is a new reading, and is written as one (decision 6).
        earlier = decisions.current(run["research_id"], read, "fulltext")
        renew = ({read} if item.get("asset_id") and earlier is not None
                 and self.store.decision_read_file(earlier) != (item["asset_id"], item["page_digest"]) else set())
        with transaction(self.store.conn):
            self._write_adjudication_codes(run, last_step, [(read, code)], renew, {read: note} if note else None)
            # The decision and its person's request move together (decision 4).
            current = decisions.current(run["research_id"], read, "fulltext")
            if current is not None and current["step_id"] == last_step:
                person_reading.mark_read(self.store, run, item, plan, current["id"])
                # The work's outcome may now be the file's (decision 8): its selection is derived again.
                decisions.derive_selection(run["research_id"], self.store.source(read)["work_id"])

    def _write_adjudication_codes(self, run: dict[str, Any], step_id: str | None,
                                  writes: list[tuple[str, str]], renew: set[str] | None = None,
                                  notes: dict[str, str] | None = None) -> None:
        """Write these full-text decisions and derive each work's selection. The user's decision is left as it is;
        a version in `renew` is written even over the same code (slice 18b). A version in `notes` is written with
        that note (`protocol_title`, slice 26; `comparator_exclusion_withheld`, slice 28); every other decision carries
        none, as before."""
        rid = run["research_id"]
        decisions = DecisionStore(self.store)
        stale_key = decisions.staleness_key(rid)
        touched: set[str] = set()
        for svid, code in writes:
            held = decisions.current(rid, svid, "fulltext")
            if held is not None and held["decided_by"] == "human":
                continue
            if not adjudication.should_write(held, code, bool(held) and (decisions.is_stale(held, stale_key)
                                                                          or svid in (renew or ()))):
                continue
            try:
                decisions.record(rid, svid, code, step_id=step_id, note=(notes or {}).get(svid))
            except HumanDecisionStands:
                continue
            touched.add(self.store.source(svid)["work_id"])
        for work_id in sorted(touched):
            decisions.derive_selection(rid, work_id)

    def _adjudication_summary(self, run: dict[str, Any], plan: dict[str, Any], *,
                              batch_key: str | None = None) -> None:
        """What this run decided, totalled from its stored steps and decisions so a resumed run matches."""
        run_id = run["id"]
        key = f"{batch_key}:adjudication_summary" if batch_key else "adjudication_summary"
        step = self.store.step(run_id, key, "code:adjudication_summary")
        if step["status"] == "succeeded":
            return
        self.store.start_step(step["id"])
        steps = self.store.run_steps(run_id)
        planned = {item["head"]: item["read_version"] for item in plan["works"]}
        if batch_key:
            steps = [row for row in steps if row["operation_key"].startswith(f"{batch_key}:adjudication_")
                     or any(row["operation_key"].startswith(f"fulltext_adjudication:{head}:") for head in planned)]
        step_ids = [row["id"] for row in steps]
        model_heads: set[str] = set()
        for row in steps:
            if row["kind"] != "model:fulltext_adjudication":
                continue
            head, _, _run_no = row["operation_key"].removeprefix("fulltext_adjudication:").rpartition(":")
            model_heads.add(head)
        codes: dict[str, int] = {}
        if step_ids:
            marks = ",".join("?" * len(step_ids))
            for row in self.store.conn.execute(
                    f"SELECT source_version_id, reason_code FROM stage_decisions WHERE step_id IN ({marks})",
                    tuple(step_ids)):
                codes[row["reason_code"]] = codes.get(row["reason_code"], 0) + 1
        include = codes.get("all_parts_verified", 0)
        not_met = codes.get("criterion_absent", 0)
        unresolved = {code: count for code, count in sorted(codes.items())
                      if code not in ("all_parts_verified", "criterion_absent")}
        decided_versions = set()
        if step_ids:
            marks = ",".join("?" * len(step_ids))
            decided_versions = {row["source_version_id"] for row in self.store.conn.execute(
                f"SELECT source_version_id FROM stage_decisions WHERE step_id IN ({marks})"
                " AND reason_code != 'pdf_identity_unconfirmed'", tuple(step_ids))}
        # A work a person decided while this run was out is neither unsettled nor unreached (slice 16).
        decided_works = DecisionStore(self.store).human_decided_works(run["research_id"], "fulltext")
        work_of = self.store.work_ids(list(planned)) if decided_works else {}
        # A person's `human_pdf_wrong` on another version of a work read from their file does not count (slice 18b).
        human = {head for head, read in planned.items() if work_of.get(head) in decided_works
                 and self._human_decided_fulltext(run["research_id"], head, read)}
        # A work whose frozen file moved before its decision is not reached, even when its calls were out (slice 18b).
        moved = {item["head"] for item in plan["works"] if item["read_version"] not in decided_versions
                 and not self._file_holds(item)}
        not_settled = sum(1 for head, read in planned.items()
                          if head in model_heads and read not in decided_versions and head not in human
                          and head not in moved)
        not_reached = plan["not_reached"] + sum(1 for head in planned if (head not in model_heads or head in moved)
                                                and head not in human)
        whole_text = self._adjudication_whole_text(run_id)
        summary = {"read": include + not_met + sum(unresolved.values()) - unresolved.get("pdf_identity_unconfirmed", 0),
                   "include": include, "criterion_not_met": not_met, "unresolved": unresolved,
                   "not_settled": not_settled, "not_reached": not_reached,
                   "identity_unconfirmed": plan["identity_unconfirmed"], "whole_text": whole_text,
                   "model_calls": self.store.run(run_id)["usage"].get("model_calls", 0)}
        if human:
            # Written only when there is one, so a run no person decided during keeps its summary as it was.
            summary["human_decided"] = len(human)
        self.store.finish_step(step["id"], "succeeded", output=summary)

    def _adjudication_whole_text(self, run_id: str) -> int:
        """Works whose stored call was every pdf page, and that was fewer than a full call. Exactly 12 is not whole."""
        seen: set[str] = set()
        count = 0
        for row in self.store.conn.execute(
                "SELECT payload_json FROM step_inputs WHERE run_id = ? AND task_type = 'fulltext_adjudication' AND attempt = 0",
                (run_id,)):
            payload = json.loads(row["payload_json"])
            source = (payload.get("adjudication_target") or {}).get("source_id")
            if not source or source in seen:
                continue
            seen.add(source)
            shown = payload.get("passages") or []
            pdf_count = sum(1 for passage in self.store.passages_for(source) if passage["kind"] == "pdf_page")
            if len(shown) < FULLTEXT_PASSAGES_PER_CALL and len(shown) == pdf_count:
                count += 1
        return count


    # ---- a person's file and its reading (slice 18b) ---------------------------------------------
    def person_reading_on(self, research_id: str) -> bool:
        """Whether a person's file can be read here: reading is `auto` and the research has a frozen criterion."""
        scope = self.store.scope(research_id)
        return (scope.get("search_workflow") == "sw" and self.deps.settings.fulltext_adjudication == "auto"
                and self.store.frozen_criterion(research_id, scope["question"], scope.get("steering")) is not None)

    def attach_outcomes(self, research_id: str, work_ids: list[str]) -> dict[str, dict[str, str]]:
        """What a file with text would lead to on each version of these works, for the confirmation panel, by work
        and version; writes nothing."""
        works = {work["work_id"]: work for work in self._fulltext_works(research_id)}
        reading_on = self.person_reading_on(research_id)
        return {work_id: {version["id"]: person_reading.attach_outcome(works[work_id], version["id"], True, reading_on)
                          for version in works[work_id]["versions"]}
                for work_id in work_ids if work_id in works}

    def attach_person_file(self, research_id: str, svid: str, asset_id: str) -> str:
        """Write what a person's newly added file asks for: the code on its version and, when the work may be read, a
        waiting request (decisions 1, 3, 4 and 10). The caller holds the transaction the file was added in.

        The code is `not_read_yet`, or `text_unreadable` for a file with no text, noted with the file; the person's
        own decision is never written over and `human_pdf_wrong` is never withdrawn. Returns what the attach led to.
        """
        work_id = self.store.source(svid)["work_id"]
        work = next(work for work in self._fulltext_works(research_id) if work["work_id"] == work_id)
        has_text = self.store.has_pdf_text(svid)
        outcome = person_reading.attach_outcome(work, svid, has_text, self.person_reading_on(research_id))
        if outcome in (person_reading.DECISION_STANDS, person_reading.NOT_ELIGIBLE):
            return outcome
        decisions = DecisionStore(self.store)
        code, note = ("not_read_yet" if has_text else "text_unreadable"), person_reading.note_for(asset_id)
        with transaction(self.store.conn):
            if adjudication.person_should_write(decisions.current(research_id, svid, "fulltext"), code, note):
                decisions.record(research_id, svid, code, note=note)
            if outcome == person_reading.REQUESTED:
                person_reading.insert_request(self.store, research_id, svid, asset_id)
            decisions.derive_selection(research_id, work_id)
        return outcome

    def queue_person_reading(self, research_id: str) -> dict[str, Any] | None:
        """Open the reading run a person's waiting files ask for, or do nothing (decision 5).

        Nothing while no live request waits, while the research has an active or a paused run (a paused run is
        resumed or cancelled, never stepped around), or while reading is off. The run's key names the question
        revision, the criterion, the waiting files and the attempt; when a run with that key already ended — before
        its plan took them — those requests are `unread` and no run is opened again, so nothing loops.
        """
        if self.store.scope(research_id).get("search_workflow") != "sw" or not self.person_reading_on(research_id):
            return None
        with transaction(self.store.conn):
            waiting = person_reading.live_waiting(self.store, research_id)
            if not waiting:
                return None
            if self.store.conn.execute(
                    f"SELECT 1 FROM runs WHERE research_id = ? AND status IN ({','.join('?' * (len(ACTIVE_RUN_STATUSES) + 1))})"
                    " LIMIT 1", (research_id, *ACTIVE_RUN_STATUSES, "paused")).fetchone():
                return None
            revision, criterion_hash = self.store.criterion_key(research_id)
            files = canonical.sha256_hex(sorted(request["asset_id"] for request in waiting))
            attempt = max(request["attempt"] for request in waiting)
            key = f"fulltext_adjudication:person:{revision}:{criterion_hash}:{files}:{attempt}"
            existing = self.store.conn.execute("SELECT id, status FROM runs WHERE idempotency_key = ?", (key,)).fetchone()
            if existing is not None:
                why = {"cancelled": person_reading.RUN_CANCELLED, "failed": person_reading.RUN_FAILED}.get(
                    existing["status"], person_reading.NO_DECISION)
                person_reading.unread_waiting(self.store, research_id, waiting, why, existing["id"])
                return None
            return self.store.create_run(research_id, "fulltext_adjudication",
                                         adjudication.read_budget(self.store.scope(research_id)["effort"]),
                                         idempotency_key=key)

    def person_run_ended(self, run_id: str) -> dict[str, Any] | None:
        """After a run, whichever way it ended: its unread requests are closed and the waiting ones get their run."""
        person_reading.close_run(self.store, run_id)
        return self.queue_person_reading(self.store.run(run_id)["research_id"])

    def queue_person_readings(self) -> None:
        """At the worker's start: close what runs that ended in a crash left planned, and queue each `sw` research's
        waiting files (decision 5). A research whose run the recovery paused keeps waiting for the person."""
        for row in self.store.conn.execute(
                "SELECT DISTINCT run_id FROM person_pdf_requests WHERE status = 'planned' AND run_id IS NOT NULL").fetchall():
            person_reading.close_run(self.store, row[0])
        for row in self.store.conn.execute(
                "SELECT DISTINCT q.research_id FROM person_pdf_requests q JOIN researches r ON r.id = q.research_id"
                " WHERE q.status = 'waiting' AND r.trashed_at IS NULL").fetchall():
            self.queue_person_reading(row[0])


    async def _semantic_ranking(self, run: dict[str, Any], scope: dict[str, Any], included: list[str], query_text: str | None = None,
                                key: str = "semantic_retrieval") -> list[dict[str, Any]] | None:
        """Rank the included sources' passages by embedding similarity to the question, or to query_text (D27, D29).

        Uses the provider chosen in Settings; without a choice, Gemini when GEMINI_API_KEY is set. The query is always
        embedded (a stored passage vector is not a score); then the passages without a stored vector, batch by batch,
        each written before the next (slice 21). If the query cannot be embedded, or no passage has a vector, the step
        fails and the caller uses lexical retrieval alone. If a later batch fails, the passages that have a vector are
        returned ranked and the step is `partial`: the others come from the lexical ranking only. The built-in model
        without an English query records a skipped step and ranks nothing.
        """
        run_id = run["id"]
        step, embedder, identity_from = self._embedding_choice(run_id, key)
        if embedder is None:
            return None
        identity = self._identity(embedder, identity_from)
        query = self._embedding_query(scope, embedder, query_text)
        if query is None:
            # Recorded so the transcript can say why the built-in model did not rank these passages (D103).
            reason = "column_not_english" if query_text is not None else english_question.MISSING
            step = self.store.step(run_id, key, f"embedding:{embedder.stored_model}", output=identity)
            self.store.finish_step(step["id"], "succeeded", output=identity | {"skipped": True, "reason": reason})
            return None
        step = self.store.step(run_id, key, f"embedding:{embedder.stored_model}", output=identity)
        if identity_from:
            self._merge_step_output(step["id"], {}, identity)
        self.store.start_step(step["id"])
        passages = [p for svid in included for p in self.store.passages_for(svid)]
        stored = self.store.passage_embeddings([p["id"] for p in passages], embedder.stored_model)
        missing = [p for p in passages if p["id"] not in stored]
        uploads = self.store.user_upload_assets({p["asset_id"] for p in missing if p.get("asset_id")})
        query_text, origin = query
        # Counted for the whole step, across a resume: what was stored before it, what it embedded, and the text of a
        # person's uploaded files. "Attempted" means a request carrying the passage was issued (a reply came back, or
        # it failed after the connection was made; `Embedder.embed`'s `on_sent`), so a 429 or a 500 counts and a
        # connection never made does not; "confirmed" means vectors came back for it. Attempted but not confirmed:
        # whether the provider received the text is not known. The built-in model sends nothing and counts nothing.
        # The ids stay in the output so a file or passage is counted once, however often it is sent again.
        # A batch's uploaded ids are written as pending before its request is awaited (Sol r3, finding 3; r4, finding 2):
        # a task stopped before the reply leaves them pending, and whether the request even started is not known. They
        # are counted apart from attempted, as unknown, and a resume moves them to the unknown ids. A failure before any
        # connection clears them. An id later attempted is counted there, not as unknown.
        # `from_store` counts the stored vectors the similarity used (Sol r4, finding 1): those stored before this step,
        # less any of another dimension; vectors an earlier attempt of this step embedded are counted in `embedded`.
        prior = self.store.step_output(step["id"]) or {}
        progress = {"from_store": len(stored) - prior.get("embedded", 0), "embedded": prior.get("embedded", 0),
                    "uploaded_file_ids": prior.get("uploaded_file_ids", []),
                    "uploaded_passage_ids": prior.get("uploaded_passage_ids", []),
                    "uploaded_unknown_file_ids": sorted(set(prior.get("uploaded_unknown_file_ids", [])) | set(prior.get("uploaded_pending_file_ids", []))),
                    "uploaded_unknown_passage_ids": sorted(set(prior.get("uploaded_unknown_passage_ids", [])) | set(prior.get("uploaded_pending_passage_ids", []))),
                    "uploaded_pending_file_ids": [], "uploaded_pending_passage_ids": [],
                    "uploaded_confirmed_file_ids": prior.get("uploaded_confirmed_file_ids", []),
                    "uploaded_passages_confirmed": prior.get("uploaded_passages_confirmed", 0),
                    "stored_other_dimension": 0}

        def counts() -> dict[str, Any]:
            return {"model": embedder.stored_model, "passages": len(passages), **progress, "missing": len(missing),
                    "uploaded_files_attempted": len(progress["uploaded_file_ids"]),
                    "uploaded_passages_attempted": len(progress["uploaded_passage_ids"]),
                    "uploaded_files_unknown": len((set(progress["uploaded_unknown_file_ids"]) | set(progress["uploaded_pending_file_ids"]))
                                                  - set(progress["uploaded_file_ids"])),
                    "uploaded_passages_unknown": len((set(progress["uploaded_unknown_passage_ids"]) | set(progress["uploaded_pending_passage_ids"]))
                                                     - set(progress["uploaded_passage_ids"])),
                    "uploaded_files_confirmed": len(progress["uploaded_confirmed_file_ids"]),
                    "query_origin": origin, "query_sha256": english_question.query_sha256(query_text)}

        self._merge_step_output(step["id"], counts(), identity)
        # An answer run is not stopped by a newer scope revision; a table fill's calls are (as its limiter checks).
        revision = None if key == "semantic_retrieval" else run["scope_revision"]
        budget, stop = self._rate_budget(step["id"], identity), lambda: self._checkpoint(run_id, revision)
        vectors = {pid: embeddings.from_blob(blob) for pid, blob in stored.items()}
        failure = None
        try:
            (query_vector,) = await embedder.embed(self.deps.http, [query_text], "RETRIEVAL_QUERY", budget, stop)
            progress["dimensions"] = self._query_dimensions(query_vector, prior)
        except embeddings.EmbeddingError as exc:
            self._finish_embedding_step(step["id"], "failed", counts() | budget.counts(), identity,
                                        error_code="embedding_failed", error={"error": str(exc)})
            return None
        # A stored vector of another dimension than this query's (a local server that changed its model under the same
        # name) is left out of the similarity, counted, and its passage falls to the keyword side (Sol r3, finding 1).
        # It is not embedded again: the stored row would stay as it is.
        other = [pid for pid, vector in vectors.items() if len(vector) != progress["dimensions"]]
        for pid in other:
            del vectors[pid]
        progress["stored_other_dimension"] = len(other)
        progress["from_store"] -= len(other)
        self._merge_step_output(step["id"], counts(), identity)
        while missing:
            batch = missing[:embedder.batch]
            from_uploads = [p for p in batch if p.get("asset_id") in uploads]

            def attempted(from_uploads: list[dict[str, Any]] = from_uploads) -> None:
                """Recorded as the request is issued (D103, decision 10)."""
                if from_uploads:
                    progress["uploaded_file_ids"] = sorted(set(progress["uploaded_file_ids"]) | {p["asset_id"] for p in from_uploads})
                    progress["uploaded_passage_ids"] = sorted(set(progress["uploaded_passage_ids"]) | {p["id"] for p in from_uploads})
                    self._merge_step_output(step["id"], counts(), identity)
            if from_uploads and embedder.provider != "builtin":
                progress["uploaded_pending_file_ids"] = sorted({p["asset_id"] for p in from_uploads})
                progress["uploaded_pending_passage_ids"] = sorted(p["id"] for p in from_uploads)
                self._merge_step_output(step["id"], counts(), identity)
            try:
                fresh = await embedder.embed(self.deps.http, [p["text"] for p in batch], "RETRIEVAL_DOCUMENT", budget, stop,
                                             on_sent=attempted)
                embeddings.same_dimension(fresh, progress["dimensions"])
            except embeddings.EmbeddingError as exc:
                failure = exc
                progress["uploaded_pending_file_ids"], progress["uploaded_pending_passage_ids"] = [], []
                break
            progress["uploaded_pending_file_ids"], progress["uploaded_pending_passage_ids"] = [], []
            missing = missing[len(batch):]
            vectors.update({p["id"]: vector for p, vector in zip(batch, fresh)})
            progress["embedded"] += len(batch)
            progress["uploaded_passages_confirmed"] += len(from_uploads)
            progress["uploaded_confirmed_file_ids"] = sorted(set(progress["uploaded_confirmed_file_ids"]) | {p["asset_id"] for p in from_uploads})
            with transaction(self.store.conn):  # the batch and the step's counts in one short write
                self.store.save_passage_embeddings(embedder.stored_model, len(fresh[0]),
                                                   {p["id"]: vector.tobytes() for p, vector in zip(batch, fresh)})
                self._merge_step_output(step["id"], counts(), identity)
            self._checkpoint(run_id, revision)
        ranked = sorted((p for p in passages if p["id"] in vectors), key=lambda p: -embeddings.similarity(query_vector, vectors[p["id"]]))
        if failure is not None:
            self._finish_embedding_step(step["id"], "partial" if ranked else "failed", counts() | budget.counts(), identity,
                                        error_code="embedding_failed", error={"error": str(failure)})
            return ranked or None
        if other:
            # Some stored vectors could not be compared: the step is partial, or failed when none could, and the
            # passages without a comparable vector keep the keyword order (Sol r4, finding 1).
            self._finish_embedding_step(step["id"], "partial" if ranked else "failed", counts() | budget.counts(), identity,
                                        error_code="embedding_failed",
                                        error={"error": f"stored_other_dimension: {len(other)} stored vectors differ from "
                                                        f"the query's {progress['dimensions']} dimensions"})
            return ranked or None
        self._finish_embedding_step(step["id"], "succeeded", counts() | budget.counts(), identity)
        return ranked

    def _topic_terms(self, research_id: str, scope: dict[str, Any]) -> list[str]:
        """The words `_retrieve` and the full-text reading list both rank passages by.

        Moved out of `_retrieve` so the reading run uses the same terms and does not grow a second ranker.
        What `_retrieve` selects from them is unchanged. Claim words stay out: they are the criterion (slice 11).
        """
        terms = [t for t in re.findall(r"\w+", scope["question"].lower()) if len(t) > 2 and t not in STOPWORDS]
        # Only an already stored legacy plan can supply these answer-side concepts.
        plan = self.store.latest_step_output(research_id, "search_plan", scope["revision"])
        if plan and plan.get("output_type") == "SearchPlan":
            for concept in plan["result"]["concepts"]:
                for phrase in [concept["label"], *concept["synonyms"]]:
                    terms += [t for t in re.findall(r"\w+", phrase.lower()) if len(t) > 2 and t not in STOPWORDS]
        elif code_words := self.store.latest_step_output(research_id, "vocabulary", scope["revision"]):
            built = code_words["vocabulary"]
            queried = [t["root"] if t["in_query"] == "root" else t["phrase"] for t in built["terms"] if not t["dropped"]]
            for phrase in queried + built["outcome_terms"]:
                terms += [t for t in re.findall(r"\w+", phrase.lower()) if len(t) > 2 and t not in STOPWORDS]
        return list(dict.fromkeys(terms))[:40]

    def _retrieve(self, research_id: str, scope: dict[str, Any], included: list[str], limit: int,
                  semantic: list[dict[str, Any]] | None = None,
                  patterns: list[tuple[str, re.Pattern[str]]] | None = None) -> list[dict[str, Any]]:
        """Passages for the answer step. `patterns` is given by an sw run alone and may be empty (D84).

        Without it the selection is what it was before slice 11: the hand-written formulation quota. With it, part
        of the room is filled from the criterion order instead, and an empty list means the whole input comes from
        the topic order — an sw research never falls back to the topic-specific formulation list.

        Attached-source and D119 answers use this shared selector. Academic small-batch answers use
        `_small_batch_answer_passages` with their stored allocation policy.
        """
        # A short attached document can fit in the answer input in its entirety. Do not discard relevant later pages
        # merely because the multi-source six-passage cap was reached; keep that cap for larger or mixed corpora.
        if len(included) == 1 and scope.get("source_scope") in ("attached", "attached_and_academic"):
            all_passages = self.store.passages_for(included[0])
            pdf_passages = [p for p in all_passages if p["kind"] == "pdf_page"]
            asset_ids = {p["asset_id"] for p in pdf_passages}
            if (len(asset_ids) == 1 and len(all_passages) <= limit
                    and sum(len(p["text"]) for p in all_passages) <= MAX_SMALL_PDF_CHARS):
                asset = self.store.asset(next(iter(asset_ids)))
                if asset["page_count"] is not None and asset["page_count"] <= MAX_SMALL_PDF_PAGES:
                    return all_passages
        unique_terms = self._topic_terms(research_id, scope)
        fts = " OR ".join(f'"{t}"' for t in unique_terms)
        ranked = self.store.search_passages(included, fts, limit * 3)
        if semantic is not None:
            ranked = fuse_rankings(ranked, semantic)[: limit * 3]
        best = {}
        for p in ranked:
            best.setdefault(p["source_version_id"], p)
        selected: dict[str, dict[str, Any]] = {}
        passages_of = {svid: self.store.passages_for(svid) for svid in included}
        texts = {svid: " ".join([self.store.source(svid)["title"], *(p["text"] for p in passages_of[svid] if p["kind"] == "abstract")])
                 for svid in included}
        semantic_rank = None
        if semantic is not None:
            semantic_rank = {}
            for p in semantic:
                semantic_rank.setdefault(p["source_version_id"], len(semantic_rank))
        order = answer_source_order(included, self.store.answer_order_facts(research_id, included), texts, unique_terms, semantic_rank)
        with_text = [svid for svid in included if passages_of[svid]]
        with_pdf = [svid for svid in with_text if any(q["kind"] == "pdf_page" for q in passages_of[svid])]
        # Scored once per retrieval, in memory: the phrase score is a pure function of stored text and stored
        # phrases and belongs to no shared passage row, because phrases are this research's and passages are not.
        criterion_of = {svid: criterion_passages.criterion_order(
            [q for q in passages_of[svid] if q["kind"] == "pdf_page"], patterns) for svid in included
        } if patterns else {}
        if len(with_text) + PDF_PAGES_PER_SOURCE * len(with_pdf) > limit:
            # One passage per source would leave too little room for PDF pages (D55). A source with PDF text gives its
            # abstract and its best pages, and the sources at the end of the order are not given.
            position = {p["id"]: i for i, p in enumerate(ranked)}
            for svid in order:
                room = limit - len(selected)
                if room <= 0:
                    break
                passages = passages_of[svid]
                first = next((q for q in passages if q["kind"] == "abstract"), None) or best.get(svid) or next(iter(passages), None)
                pages = [q for q in passages if q["kind"] == "pdf_page" and q is not first]
                if pages:
                    matched = {q["id"]: i for i, q in enumerate(self.store.search_passages([svid], fts, MAX_PASSAGES_PER_SOURCE * 2))}
                    pages.sort(key=lambda q: (0, position[q["id"]]) if q["id"] in position else (1, matched[q["id"]]) if q["id"] in matched
                               else (2, q["physical_page"] if q["physical_page"] is not None else math.inf) if patterns is not None
                               else (2, -formulation_score(q["text"]), q["physical_page"] if q["physical_page"] is not None else math.inf))
                if patterns is not None and pages:
                    # The source still gives the same number of pages; one of them comes from the criterion order,
                    # and a source with no criterion page gives its second page from the topic order. The page
                    # already given as `first` is not offered again, or it would spend one of the two places.
                    offered = {q["id"] for q in pages}
                    pages = self._two_quota_pages(pages, [q for q in criterion_of.get(svid, []) if q["id"] in offered])
                for q in ([first] if first else []) + pages[:PDF_PAGES_PER_SOURCE]:
                    if len(selected) < limit:
                        selected[q["id"]] = q
        # Every included source is given first, in that order, up to the limit: its abstract, else its best-matching
        # passage, else its first passage. Formulation pages then get bounded room before the general FTS matches.
        for svid in order:
            if len(selected) >= limit:
                break
            passages = passages_of[svid]
            p = next((q for q in passages if q["kind"] == "abstract"), None) or best.get(svid) or next(iter(passages), None)
            if p:
                selected[p["id"]] = p
        taken = {svid: 1 for svid in {p["source_version_id"] for p in selected.values()}}
        if patterns is None:
            order_position = {svid: i for i, svid in enumerate(order)}
            formulation_pages = [p for svid in order for p in passages_of[svid]
                                 if p["kind"] == "pdf_page" and formulation_score(p["text"]) >= FORMULATION_SCORE_THRESHOLD]
            formulation_pages.sort(key=lambda p: (-formulation_score(p["text"]), order_position[p["source_version_id"]],
                                                   p["physical_page"] if p["physical_page"] is not None else math.inf))
            formulation_room = limit // 4
            formulations_added = 0
            for p in formulation_pages:
                if len(selected) >= limit or formulations_added >= formulation_room:
                    break
                svid = p["source_version_id"]
                if p["id"] not in selected and taken.get(svid, 0) < MAX_PASSAGES_PER_SOURCE:
                    selected[p["id"]] = p
                    taken[svid] = taken.get(svid, 0) + 1
                    formulations_added += 1
        else:
            # The criterion quota fills in rounds down the source order, so it is not spent on one source's pages
            # and every source holding a criterion page is represented before any source gives a second one.
            # A crowded pass that short sources left unfilled has already given a source up to three passages; the
            # cap counts them. The legacy branch keeps its count from one, as it always did (D84, limits).
            taken = dict(Counter(p["source_version_id"] for p in selected.values()))
            room = limit // criterion_passages.CRITERION_ROOM_DIVISOR
            added = 0
            for depth in range(max((len(ordered) for ordered in criterion_of.values()), default=0)):
                if len(selected) >= limit or added >= room:
                    break
                for svid in order:
                    if len(selected) >= limit or added >= room:
                        break
                    ordered = criterion_of.get(svid, [])
                    if depth >= len(ordered):
                        continue
                    p = ordered[depth]
                    if p["id"] not in selected and taken.get(svid, 0) < MAX_PASSAGES_PER_SOURCE:
                        selected[p["id"]] = p
                        taken[svid] = taken.get(svid, 0) + 1
                        added += 1
        for p in ranked:
            if len(selected) >= limit:
                break
            if p["id"] not in selected and taken.get(p["source_version_id"], 0) < MAX_PASSAGES_PER_SOURCE:
                selected[p["id"]] = p
                taken[p["source_version_id"]] = taken.get(p["source_version_id"], 0) + 1
        return list(selected.values())

    @staticmethod
    def _two_quota_pages(topic: list[dict[str, Any]], criterion: list[dict[str, Any]]) -> list[dict[str, Any]]:
        """The pages one source gives when the included sources outnumber the passage limit (D55, D84).

        The best topic page first, then the first criterion pages this source has, then the topic order again for
        whatever room is left. The count a source contributes does not change; which pages they are does.
        """
        picked = topic[:1]
        ids = {q["id"] for q in picked}
        for q in criterion[:criterion_passages.CRITERION_PAGES_PER_SOURCE]:
            if q["id"] not in ids:
                picked.append(q)
                ids.add(q["id"])
        return picked + [q for q in topic if q["id"] not in ids]

    # ---- evidence tables ----------------------------------------------------------------
    async def _table_fill(self, run: dict[str, Any], scope: dict[str, Any]) -> None:
        """Fill planned cells, sending several sources' calls at once (D37, P6 slice 0).

        A source's columns are asked together, at most MAX_COLUMNS_PER_CALL per call, and each call reads that source's
        passages only. A source without stored text gets 'inaccessible' from the system without a model call, written
        before any concurrent submission starts for it. Calls are sent through the run's shared limiter: at most its
        current limit are in flight, and the same operation key is never sent twice concurrently. A checkpoint still
        runs before each submission. Once it stops new submissions, calls already in flight finish and record their
        steps, but their cells are applied only while the run remains active on the revision for which they were sent.
        """
        run_id, target = run["id"], run["target"]
        tables = TableStore(self.store)
        await self._read_equations(run, [planned["source_version_id"] for planned in target["sources"]])
        limiter = self.deps.limiter

        async def call(job: _FillJob) -> dict[str, Any] | None:
            return await self._extraction(run, scope, job.key, job.svid, job.columns, MAX_FILL_PASSAGES, limiter)

        def apply(completed: list[tuple[dict[str, Any] | None, _FillJob]]) -> None:
            for output, job in completed:
                if output is not None and not self._fill_stopped(run_id, run["scope_revision"]):
                    self._save_cells(run, output, job.cell_versions, recheck=False)

        stop = await self._send_through_limiter(run, self._fill_jobs(run, tables, target), call, apply)
        if stop is not None:
            raise stop

    async def _send_through_limiter(self, run: dict[str, Any], jobs: Iterator[Any],
                                    call: Callable[[Any], Awaitable[Any]],
                                    applied: Callable[[list[tuple[Any, Any]]], None]) -> RunStopped | None:
        """Send `jobs` through the run's shared limiter, applying each round of results as they come back.

        The one submission loop table fill and the abstract stage both use (D37, D81). At most the limiter's
        current limit are in flight, the same operation key is never sent twice concurrently, and a checkpoint runs
        before each submission. Once something stops the run — a pause or cancel found at a checkpoint, or a call
        that recorded a pause of its own — no more are submitted, but the calls already in flight finish and record
        their steps; their results are not applied, and the stop is returned for the caller to raise after whatever
        it still owes the run. An unexpected exception is raised once every call in flight has returned.
        """
        run_id, limiter = run["id"], self.deps.limiter
        pending: dict[asyncio.Task[Any], Any] = {}
        stop: RunStopped | None = None
        failure: Exception | None = None

        async def guarded_call(job: Any) -> Any:
            try:
                return await call(job)
            except BaseException:
                small_batch.halt_pipeline(self, run)
                raise
            finally:
                guard = getattr(self, "_small_batch_guard", None)
                if guard and guard["run_id"] == run_id:
                    guard.get("reserved_calls", set()).discard(job.key)

        def submit_more() -> None:
            nonlocal stop
            while stop is None and failure is None and len(pending) < limiter.limit:
                try:
                    self._checkpoint(run_id, run["scope_revision"])
                    job = next(jobs, None)
                except RunStopped as exc:
                    stop = exc
                    return
                if job is None:
                    return
                pending[asyncio.ensure_future(limiter.run(job.key, lambda job=job: guarded_call(job)))] = job

        submit_more()
        while pending:
            done, _ = await asyncio.wait(pending.keys(), return_when=asyncio.FIRST_COMPLETED)
            completed: list[tuple[Any, Any]] = []
            for task in done:
                job = pending.pop(task)
                try:
                    output = task.result()
                except RunStopped as exc:
                    stop = stop or exc
                except Exception as exc:
                    failure = failure or exc
                else:
                    completed.append((output, job))
            if failure is None and stop is None:
                try:
                    applied(completed)
                except RunStopped as exc:
                    stop = exc
                except Exception as exc:
                    failure = exc
                    small_batch.halt_pipeline(self, run)
            submit_more()
        if failure is not None:
            raise failure
        return stop

    def _fill_jobs(self, run: dict[str, Any], tables: TableStore, target: dict[str, Any]) -> Iterator[_FillJob]:
        """Yield pending source and column jobs in table order, writing no-text cells as each source is reached."""
        for planned in target["sources"]:
            svid = planned["source_version_id"]
            columns = [c for c in self._live_columns(run, tables) if c["id"] in planned["column_ids"]]
            if not columns or svid not in tables.active_rows(target["table_id"]):
                continue  # the column or row was removed after the fill was requested
            if not self.store.passages_for(svid):
                step = self.store.step(run["id"], f"no_text:{svid}", "table_no_text")
                if step["status"] != "succeeded":
                    self.store.start_step(step["id"])
                    saved = [tables.save_no_text(run["research_id"], target["table_id"], c["id"], svid, column_revision=c["current_revision"],
                                                 run_id=run["id"], step_id=step["id"], scope_revision=run["scope_revision"]) for c in columns]
                    self.store.finish_step(step["id"], "succeeded", output={"source_version_id": svid, "cells": sum(s is not None for s in saved)})
                continue
            # Calls are cut from the planned column list, so a resumed run finds each call's stored step under the same key.
            for index in range(0, len(planned["column_ids"]), MAX_COLUMNS_PER_CALL):
                chunk = [c for c in columns if c["id"] in planned["column_ids"][index:index + MAX_COLUMNS_PER_CALL]]
                if chunk:
                    yield _FillJob(f"cell_extraction:{svid}:{index // MAX_COLUMNS_PER_CALL}", svid, chunk, planned["cell_versions"])

    def _fill_stopped(self, run_id: str, scope_revision: int) -> bool:
        """Whether a returned fill call must defer or permanently skip updating its cells."""
        run = self.store.run(run_id)
        if run["status"] in ("pause_requested", "paused", "cancelled", "failed"):
            return True
        return self.store.research(run["research_id"])["current_scope_revision"] != scope_revision

    async def _cell_recheck(self, run: dict[str, Any], scope: dict[str, Any]) -> None:
        """Ask again for one cell. The model never sees the cell's current value, and the result waits as a proposal (D37)."""
        run_id, target = run["id"], run["target"]
        tables = TableStore(self.store)
        svid = target["source_version_id"]
        columns = [c for c in self._live_columns(run, tables) if c["id"] == target["column_id"]]
        if not columns or svid not in tables.active_rows(target["table_id"]):
            self._fail(run_id, "cell_unavailable")
        await self._read_equations(run, [svid])
        self._checkpoint(run_id)
        output = await self._extraction(run, scope, "cell_recheck", svid, columns, MAX_RECHECK_PASSAGES)
        if output is None:
            self._fail(run_id, "no_text")
        self._checkpoint(run_id)
        if not self._save_cells(run, output, {target["column_id"]: target["cell_version"]}, recheck=True):
            self._fail(run_id, "invalid_model_output", {"step": "cell_recheck", "issues": output.get("issues")})

    async def _table_columns(self, run: dict[str, Any], scope: dict[str, Any]) -> None:
        """Suggest columns from the question and the rows' titles and abstracts; nothing is added to the table."""
        run_id, table_id = run["id"], run["target"]["table_id"]
        tables = TableStore(self.store)
        columns = self._live_columns(run, tables)
        rows = tables.active_rows(table_id)[:MAX_FILL_SOURCES]
        abstracts = [p for svid in rows for p in self.store.passages_for(svid) if p["kind"] == "abstract"]
        target = {"table_id": table_id, "source_id": None, "columns": [extraction_column(c) for c in columns], "passage_scope": None}
        self._checkpoint(run_id)
        output = await self._model_step(run, scope, "table_columns", "table_columns", source_ids=rows, passage_rows=abstracts,
                                        extraction_target=target)
        self._checkpoint(run_id)
        if output.get("invalid"):
            self._fail(run_id, "invalid_model_output", {"step": "table_columns", "issues": output["issues"]})

    def _live_columns(self, run: dict[str, Any], tables: TableStore) -> list[dict[str, Any]]:
        try:
            return tables.target_columns(run["research_id"], run["target"]["table_id"])
        except NotFound:
            self._fail(run["id"], "table_unavailable")
            raise

    async def _extraction(self, run: dict[str, Any], scope: dict[str, Any], key: str, svid: str, columns: list[dict[str, Any]],
                          limit: int, limiter: ModelCallLimiter | None = None) -> dict[str, Any] | None:
        """One cell extraction step for one source; None when the source has no stored text to give."""
        step = self.store.step(run["id"], key, "model:cell_extraction")
        if step["status"] == "succeeded":
            return step["output"]
        if step["status"] == "failed" and step["error_code"] == "invalid_model_output":
            # Its result was kept as unverified proposals; a resumed run does not ask again.
            return {"invalid": True, "step_input_id": step["output"]["step_input_id"], "issues": json.loads(step["error_json"] or "null")}
        available = self.store.passages_for(svid)
        if not available:
            return None
        given = await self._cell_passages(run, scope, key, svid, columns, available, limit)
        pages = {p["id"] for p in available if p["kind"] == "pdf_page"}
        target = {"table_id": run["target"]["table_id"], "source_id": svid, "columns": [extraction_column(c) for c in columns],
                  "passage_scope": {"given": len(given), "available": len(available),
                                    "all_pages_given": bool(pages) and pages <= {p["id"] for p in given}}}
        return await self._model_step(run, scope, key, "cell_extraction", source_ids=[svid], passage_rows=given,
                                      extraction_target=target, limiter=limiter)

    async def _cell_passages(self, run: dict[str, Any], scope: dict[str, Any], key: str, svid: str, columns: list[dict[str, Any]],
                             available: list[dict[str, Any]], limit: int) -> list[dict[str, Any]]:
        """Passages of one source for a cell extraction call (P5 slice 1 design, §5).

        A source within MAX_CELL_PASSAGES passages and MAX_SMALL_PDF_CHARS characters is given whole. Otherwise its
        abstract comes first, then passages matching the column names and instructions (fused with the semantic ranking
        when semantic search is on), then the remaining passages in page order, up to the limit.
        """
        if len(available) <= MAX_CELL_PASSAGES and sum(len(p["text"]) for p in available) <= MAX_SMALL_PDF_CHARS:
            return available
        text = " ".join(f"{c['name']} {c['instruction']}" for c in columns)
        terms = list(dict.fromkeys(t for t in re.findall(r"\w+", text.lower()) if len(t) > 2 and t not in STOPWORDS))[:40]
        ranked = self.store.search_passages([svid], " OR ".join(f'"{t}"' for t in terms), limit * 3)
        semantic = await self._semantic_ranking(run, scope, [svid], query_text=text, key=f"semantic:{key}")
        if semantic is not None:
            ranked = fuse_rankings(ranked, semantic)
        ordered = [p for p in available if p["kind"] == "abstract"] + ranked + available
        return list({p["id"]: p for p in ordered}.values())[:limit]

    def _save_cells(self, run: dict[str, Any], output: dict[str, Any], cell_versions: dict[str, int], recheck: bool) -> int:
        """Store one extraction step's answers as cell revisions. From an invalid output, what can be kept is kept as unverified."""
        payload = self.store.step_input_payload(output["step_input_id"])
        target = payload["extraction_target"]
        session = self.store.model_session(output["step_input_id"])
        if output.get("invalid"):
            raw = contracts.resolve_citation_handles(payload, session["raw_output"] or "")
            cells, status = contracts.storable_cells(payload, raw), "unverified_draft"
        else:
            cells, status = output["result"]["cells"], "structurally_valid"
        columns = {c["column_id"]: c for c in target["columns"]}
        # Reading depth follows the passages the step was given, never the model's words; no cell gets full_text (D37).
        depth = "abstract" if all(p["locator"]["kind"] == "abstract" for p in payload["passages"]) else "selected_sections"
        tables = TableStore(self.store)
        for cell in cells:
            column = columns[cell["column_id"]]
            tables.save_model_output(
                run["research_id"], target["table_id"], column["column_id"], target["source_id"], column_revision=column["revision"],
                state=cell["state"], value=check_value(column, cell["state"], cell["value"]), note=(cell["note"] or "").strip() or None,
                reading_depth=depth, output_status=status, links=contracts.cell_links(payload, cell), run_id=run["id"],
                step_id=payload["step_id"], step_input_id=payload["step_input_id"], model_connection=session["connection"],
                resolved_model=session["resolved_model"], scope_revision=payload["scope_revision"],
                cell_version_at_request=cell_versions.get(column["column_id"]), recheck=recheck,
            )
        return len(cells)

    # ---- candidates -------------------------------------------------------------------
    def _candidate_send_gate(self, run: dict[str, Any]) -> None:
        from deixis.workflow.candidates.store import CandidateStore, TERMINAL_OUTCOMES
        self._checkpoint(run["id"], run["scope_revision"])
        if self.store.run(run["id"])["status"] != "running":
            raise RunStopped
        if run["target"].get("skill_package_hash") != self.deps.package.package_hash:
            if run["kind"] == "kill_search":
                cs = CandidateStore(self.store)
                search = cs.search_for_run(run["id"])
                if search and search["outcome"] not in TERMINAL_OUTCOMES:
                    # Preserve the failure code before terminalisation for crash recovery.
                    self._kill_search_summary(run, search, {}, "skill_package_changed")
                    cs.finish_kill_search(search["id"], "failed")
            self._fail(run["id"], "skill_package_changed")
        try:
            candidate = CandidateStore(self.store)._pair(run["research_id"], run["target"]["candidate_id"])
        except NotFound:
            self._fail(run["id"], "candidate_unavailable")
        if candidate["trashed_at"] is not None:
            self._fail(run["id"], "candidate_unavailable")

    def _candidate_measure(self, run: dict, scope: dict, task: str, target: dict, rows: list[dict]) -> int:
        source_ids = list(dict.fromkeys(p["source_version_id"] for p in rows))
        model = tuple(run["target"]["model"][task]) if run["kind"] == "kill_search" else step_model(scope, task)
        payload = self._step_input(run, scope, new_id("stp"), task, [], source_ids, rows, [], model,
                                   candidate_target=target)
        return len(prompt.step_message(contracts.with_citation_handles(payload)))

    async def _candidate_model(self, run: dict, scope: dict, key: str, task: str,
                               target: dict, rows: list[dict], frozen_hit: dict | None = None, **kwargs) -> dict:
        from deixis.workflow.candidates.run import MAX_MESSAGE_CHARS, FrozenPassagesUnavailable, frozen_passages
        # Candidate calls are sequential; app.py's existing cancel path still
        # interrupts adapters for both claim_decomposition and kill_search.
        step = self.store.existing_step(run["id"], key)
        if step and step["status"] == "succeeded":
            return step["output"]
        if step and step["status"] == "failed" and step["error_code"] in ("invalid_model_output", "message_too_large"):
            return (step["output"] or {}) | {"invalid": True,
                    "issues": json.loads(step["error_json"] or "[]"),
                    "message_too_large": step["error_code"] == "message_too_large"}

        def gate() -> None:
            self._candidate_send_gate(run)
            if frozen_hit is not None:
                fresh = frozen_passages(frozen_hit, self.store.passages_for(frozen_hit["source_version_id"]))
                if fresh is None:
                    raise FrozenPassagesUnavailable
                rows[:] = fresh

        def resend() -> bool:
            gate()
            return self.store.run(run["id"])["usage"].get("model_calls", 0) < run["budget"]["max_model_calls"]

        model = tuple(run["target"]["model"][task]) if run["kind"] == "kill_search" else step_model(scope, task)
        return await self.deps.limiter.run(f"{run['id']}:{key}", lambda: self._model_step(
            run, scope, key, task, source_ids=list(dict.fromkeys(p["source_version_id"] for p in rows)),
            passage_rows=rows, candidate_target=target, model=model, limiter=self.deps.limiter,
            resend_guard=resend, send_gate=gate, max_message_chars=MAX_MESSAGE_CHARS,
            attempt_record=lambda payload: {"send_record": {"task": task}}, **kwargs))

    def _candidate_record(self, run: dict, key: str, output: dict) -> None:
        step = self.store.step(run["id"], key, key)
        self.store.start_step(step["id"])
        self.store.finish_step(step["id"], "succeeded", output=output)

    async def _claim_decomposition(self, run: dict, scope: dict) -> None:
        from deixis.workflow.candidates import run as candidates
        from deixis.workflow.candidates.store import CandidateStore, InvalidCandidateInput
        self._candidate_send_gate(run)
        cs = CandidateStore(self.store)
        candidate = cs.candidate(run["target"]["candidate_id"])
        view = json.loads(candidate["origin_basis_view_json"])
        current = {item["source_version_id"]: self.store.passages_for(item["source_version_id"])
                   for item in view.get("basis_passage_ids", []) if not item.get("missing")}
        built = candidates.pack_decomposition(candidates.decomposition_input(candidate, current),
            lambda target, rows: self._candidate_measure(run, scope, "claim_decomposition", target, rows))
        output = await self._candidate_model(run, scope, "decompose", "claim_decomposition", built["target"], built["passages"])
        self._candidate_send_gate(run)
        self._candidate_record(run, "claim_decomposition_summary", {"omitted": built["omitted"]})
        if output.get("invalid"):
            self._fail(run["id"], "invalid_model_output")
        result = output["result"]
        try:
            with transaction(self.store.conn):
                # No await between this post-call barrier and the guarded publication.
                self._candidate_send_gate(run)
                cs.add_version(run["research_id"], candidate["id"],
                    **{k: result[k] for k in ("claim_statement", "conditions", "elements", "nearest_simple_explanation",
                                             "critical_assumption", "validation_plan")},
                    origin="model_decomposition", step_input_id=output["step_input_id"], expected_version=0,
                    idempotency_key=f"decompose:{run['id']}")
        except RunStopped:
            self._candidate_send_gate(run)
            raise
        except RevisionConflict:
            self._fail(run["id"], "candidate_version_changed")
        except InvalidCandidateInput:
            self._fail(run["id"], "candidate_publication_failed")

    async def _kill_search_request(self, run: dict, query: dict) -> tuple[SearchOutcome | facade.Dispatched, dict]:
        """One logical query, no paging/enrichment; reservations survive uncertain delivery."""
        from deixis.workflow.candidates.run import KILL_RECORDS
        connector = CONNECTORS[query["provider_id"]]
        transport = next(t for t in run["target"]["transport"]["providers"] if t["provider"] == connector.provider_id)
        reserve = transport["requests_per_search"] * (1 + transport["rate_limit_retries"])
        record: dict = {}
        for attempt in range(transport["transient_attempts"]):
            self._candidate_send_gate(run)
            key = connector.api_key()
            if connector.key_required and not key:
                return SearchOutcome("not_configured", "before_send",
                                     f"{connector.provider_id} search not sent: access=not_configured", "not_configured"), record
            with transaction(self.store.conn):
                used = self.store.run(run["id"])["usage"].get("provider_requests", 0)
                if used + reserve > run["budget"]["max_provider_requests"]:
                    return SearchOutcome("transport_budget", "before_send", "unsent: transport budget", "api_key" if key else "keyless"), record
                # Conservatively charge the whole possible HTTP attempt, never refund it.
                self.store.add_usage(run["id"], "provider_requests", reserve)
            dispatched = await facade.dispatch_search(connector.provider_id, self.deps.http, query["query_text"], KILL_RECORDS,
                key, self.deps.settings.contact_email, **endpoint_options(query))
            outcome = dispatched.outcome
            actual = sum(entry["attempts"] for entry in dispatched.transport)
            sends = sum(entry["sends"] for entry in dispatched.transport)
            excess = max(0, actual - reserve)
            self.store.settle_usage(run["id"], None, excess, sends)
            record["reserved"] = record.get("reserved", 0) + reserve
            record["attempts"] = record.get("attempts", 0) + actual
            record["sends"] = record.get("sends", 0) + sends
            if excess:
                record["over_reservation"] = record.get("over_reservation", 0) + excess
            record.setdefault("dispatches", []).append({"subrequests": list(dispatched.transport)})
            if outcome.delivery_class != "before_send" or outcome.status != "failed" or attempt + 1 == transport["transient_attempts"]:
                return dispatched, record
            await asyncio.sleep(RATE_LIMIT_BACKOFF_SECONDS * (attempt + 1))
        raise AssertionError("bounded transport has no attempts")

    def _kill_search_record_query(self, run: dict, search: dict, step: dict, position: int,
                                  query: dict, outcome: SearchOutcome | facade.Dispatched,
                                  transport: dict | None = None) -> None:
        from deixis.workflow.candidates.store import CandidateStore, TERMINAL_OUTCOMES
        dispatched = outcome if isinstance(outcome, facade.Dispatched) else None
        outcome = dispatched.outcome if dispatched else outcome
        ok = outcome.status in ("completed", "zero_results")
        status = "succeeded" if ok else "outcome_unknown" if outcome.delivery_class == "after_send_unknown" else "failed"
        with transaction(self.store.conn):
            cs = CandidateStore(self.store)
            if cs.kill_search(search["id"])["outcome"] in TERMINAL_OUTCOMES:
                return
            # Delivery consumes its reservation even after a stop or scope revision.
            # Record it before the gate so resume cannot resend an uncertain query.
            path = digest = None
            if outcome.raw_payload is not None:
                self.deps.settings.payloads_dir.mkdir(parents=True, exist_ok=True)
                path = f"{step['id']}.json"
                (self.deps.settings.payloads_dir / path).write_text(json.dumps(outcome.raw_payload), encoding="utf-8")
                digest = canonical.sha256_hex(outcome.raw_payload)
            cs.record_query(search["id"], position=position, provider=query["provider_id"],
                query_text=query["query_text"], status=status, records=outcome.records if ok else [],
                error_code=None if ok else outcome.status, raw_payload_path=path, payload_sha256=digest, step_id=step["id"])
            output = {"status": outcome.status, "result_count": len(outcome.records) if ok else 0}
            if transport and transport.get("dispatches"):
                output["transport"] = transport
            if dispatched is not None and dispatched.dropped_records:
                output["dropped_records"] = dispatched.dropped_records
            self.store.finish_step(step["id"], status, output=output,
                error_code=None if ok else outcome.status, delivery_class=outcome.delivery_class,
                error=None if ok else {"error": outcome.error, "http_status": outcome.http_status}
                | ({"error_kind": outcome.error_kind} if outcome.error_kind is not None else {}))

    def _kill_search_summary(self, run: dict, search: dict, outcomes: dict, failure_code=None) -> dict:
        from deixis.workflow.candidates.run import search_summary
        summary = search_summary(self.store, search["id"], outcomes, failure_code)
        self._candidate_record(run, "kill_search_summary", summary)
        return summary

    def _kill_search_finish(self, run: dict, search: dict, outcomes: dict, failure_code=None) -> None:
        from deixis.workflow.candidates.store import CandidateStore
        self._candidate_send_gate(run)
        # Deliberately separate durable writes: recovery carries this exact failure code.
        self._kill_search_summary(run, search, outcomes, failure_code)
        CandidateStore(self.store).finish_kill_search(search["id"], "failed" if failure_code else "completed")
        if failure_code:
            self._fail(run["id"], failure_code)

    async def _kill_search(self, run: dict, scope: dict) -> None:
        from deixis.workflow.candidates import hits, run as candidates, terms
        from deixis.workflow.candidates.store import CandidateStore
        self._candidate_send_gate(run)
        cs = CandidateStore(self.store)
        plan = run["target"]
        candidate = cs.candidate(plan["candidate_id"])
        version = cs.version(plan["candidate_version_id"])
        # The model sees the frozen eligible providers, never a later access fallback.
        scope = dict(scope, providers=plan["providers"])
        search = cs.search_for_run(run["id"])
        if search:
            if search["outcome"] == "failed":
                summary = self.store.existing_step(run["id"], "kill_search_summary")
                self._fail(run["id"], (summary["output"] or {})["failure_code"] if summary else "search_failed")
            if search["outcome"] in ("completed", "stopped"):
                return
            if search["outcome"] == "paused":
                search = cs.set_kill_search_state(search["id"], "running")
        else:
            try:
                output = await self._candidate_model(run, scope, "query_terms", "kill_search_query",
                    candidates.candidate_target(candidate, version), [], optional=True)
            except OptionalStepFailed as exc:
                # Before the freeze no search was attempted; a connection failure
                # belongs to the run and cannot change the candidate's search status.
                self._candidate_send_gate(run)
                self._fail(run["id"], exc.reason, exc.detail)
            self._candidate_send_gate(run)
            if output.get("invalid"):
                self._fail(run["id"], "query_terms_invalid")
            blocks = output["result"]
            try:
                vocabulary = terms.block_vocabulary([t["term"] for t in blocks["setting"]], [t["term"] for t in blocks["task"]])
            except terms.InvalidTerms:
                self._fail(run["id"], "query_terms_invalid")
            compiled = terms.compile_queries(vocabulary, plan["providers"], candidates.KILL_QUERIES)
            search = cs.start_kill_search(run["research_id"], version["id"], run["id"],
                query_block={k: blocks[k] for k in ("setting", "task", "setting_backup", "task_backup")},
                rendered_queries=compiled, skipped_terms=[t for q in compiled for t in q.get("dropped_terms", [])],
                selection={k: plan[k] for k in ("model", "providers", "budget", "transport")})
        queries = json.loads(search["rendered_queries_json"])
        if not queries:
            self._kill_search_finish(run, search, {}, "no_query_compiled")
        for position, query in enumerate(queries, 1):
            self._candidate_send_gate(run)
            if any(q["position"] == position for q in cs.queries(search["id"])):
                continue
            step = self.store.step(run["id"], f"search:{position}", f"provider_search:{query['provider_id']}")
            if step["status"] == "outcome_unknown":
                outcome = SearchOutcome(step["error_code"] or "outcome_unknown", "after_send_unknown", "recovered delivery unknown", "unknown")
                transport = None
            else:
                self.store.start_step(step["id"])
                outcome, transport = await self._kill_search_request(run, query)
            self._kill_search_record_query(run, search, step, position, query, outcome, transport)
            self._candidate_send_gate(run)
        outcomes = {}
        if any(q["status"] == "succeeded" for q in cs.queries(search["id"])):
            stored_plan = self.store.existing_step(run["id"], "kill_search_plan")
            if stored_plan and stored_plan["status"] == "succeeded":
                assessment_plan = stored_plan["output"]
            else:
                merged = hits.merge_and_cut(cs.query_records(search["id"]), keep=candidates.KILL_KEEP)
                entries = []
                for hit in merged["kept"]:
                    svid = hit["source_version_id"]
                    target = candidates.candidate_target(candidate, version, svid)
                    shown = candidates.shown_passages(self.store.passages_for(svid),
                        lambda rows: self._candidate_measure(run, scope, "claim_assessment", target, rows))
                    entries.append({"source_version_id": svid,
                        **{k: shown[k] for k in ("reading_depth", "omitted", "message_too_large")},
                        "passages": [{"passage_id": p["id"], "text_sha256": candidates.text_sha256(p["text"])} for p in shown["passages"]]})
                assessment_plan = {"merged": merged, "hits": entries}
                self._candidate_send_gate(run)
                self._candidate_record(run, "kill_search_plan", assessment_plan)
            if not cs.kill_search(search["id"])["hits_recorded"]:
                self._candidate_send_gate(run)
                cs.record_hits(search["id"], assessment_plan["merged"],
                    {h["source_version_id"]: h["reading_depth"] for h in assessment_plan["hits"]})
            for hit in cs.hits(search["id"]):
                self._candidate_send_gate(run)
                if not hit["kept"] or hit["assessment_state"] != "pending":
                    continue
                svid = hit["source_version_id"]
                key = f"assess:{svid}"
                step = self.store.existing_step(run["id"], key)
                # A succeeded assessment is published from its stored input before
                # looking at live text, even if that text has since changed.
                output = step["output"] if step and step["status"] == "succeeded" else None
                if output is None:
                    frozen = next(h for h in assessment_plan["hits"] if h["source_version_id"] == svid)
                    rows = candidates.frozen_passages(frozen, self.store.passages_for(svid))
                    if rows is None or not rows or frozen["reading_depth"] == "metadata_only":
                        self._candidate_send_gate(run)
                        cs.publish_assessment(search["id"], svid, assessment_state="insufficient_access")
                        outcomes[svid] = {"outcome": "insufficient_access", "reason": "frozen_passage_unavailable"
                                          if rows is None else "no_shown_text"}
                        continue
                    if frozen["message_too_large"]:
                        outcomes[svid] = "message_too_large"
                        continue
                    try:
                        output = await self._candidate_model(run, scope, key, "claim_assessment",
                            candidates.candidate_target(candidate, version, svid), rows, frozen_hit=frozen, budget_short="skip")
                    except candidates.FrozenPassagesUnavailable:
                        self._candidate_send_gate(run)
                        step = self.store.existing_step(run["id"], key)
                        self.store.finish_step(step["id"], "cancelled", output=step["output"], error_code="frozen_passage_unavailable")
                        cs.publish_assessment(search["id"], svid, assessment_state="insufficient_access")
                        outcomes[svid] = {"outcome": "insufficient_access", "reason": "frozen_passage_unavailable"}
                        continue
                self._candidate_send_gate(run)
                if output.get("invalid"):
                    outcomes[svid] = "not_reached_budget" if output.get("not_reached") else "message_too_large" if output.get("message_too_large") else "invalid_output"
                    if output.get("not_reached") or self.store.run(run["id"])["usage"].get("model_calls", 0) >= run["budget"]["max_model_calls"]:
                        break
                    continue
                result = output["result"]
                payload = self.store.step_input_payload(output["step_input_id"])
                def quotes(items):
                    values = [contracts.claim_assessment_evidence(payload, item) for item in items]
                    if any(v is None for v in values):
                        outcomes[svid] = {"outcome": "invalid_output", "reason": "candidate_evidence_unlocated"}
                        self._kill_search_finish(run, search, outcomes, "candidate_evidence_unlocated")
                    return values
                cells = [{"element_id": c["element_ref"], "relation": c["relation"],
                          "condition_alignment": c["condition_alignment"], "note": c["note"], "quotes": quotes(c["evidence"])}
                         for c in result["cells"]]
                whole = quotes(result["whole_claim_evidence"])
                try:
                    with transaction(self.store.conn):
                        self._candidate_send_gate(run)
                        cs.publish_assessment(search["id"], svid, assessment_state="assessed",
                            work_relevance=result["work_relevance"], states_whole_claim=result["states_whole_claim"],
                            note=result["nearest_match_summary"], step_input_id=output["step_input_id"],
                            cells=cells, whole_claim_quotes=whole)
                except RunStopped:
                    self._candidate_send_gate(run)
                    raise
                outcomes[svid] = "assessed"
        refused = any(q["error_code"] == "transport_budget" for q in cs.queries(search["id"]))
        self._kill_search_finish(run, search, outcomes, "transport_budget" if refused else None)

    async def _watch_check(self, run: dict) -> None:
        from deixis.workflow.watch.store import WatchStore
        from deixis.workflow.watch.run import Callbacks, run as watch_run

        watches = WatchStore(self.store)
        check = watches.check(run["research_id"], run["target"]["check_id"])

        def gate():
            try:
                self._checkpoint(run["id"], run["scope_revision"])
            except RunStopped:
                return "stopped"
            except NotFound:
                watches.cancel_unavailable(run["id"])
                return "research_unavailable"
            current = self.store.run(run["id"])
            if current["status"] != "running":
                return "stopped"
            try:
                watch = watches.watch(run["research_id"], run["target"]["watch_id"])
            except NotFound:
                reason = "research_unavailable"
            else:
                reason = "watch_disabled" if not watch["enabled"] else watches.follows_old_scope(watch)
            if reason:
                if reason == "research_unavailable":
                    watches.cancel_unavailable(run["id"])
                else:
                    self.store.update_run(run["id"], event="run_cancelled", status="cancelled", pause_reason=reason)
                return reason
            return None

        async def send(request):
            return await self.deps.http.send(request, follow_redirects=False)

        callbacks = Callbacks(gate=gate, run=lambda: self.store.run(run["id"]),
            add_usage=lambda key, amount: self.store.add_usage(run["id"], key, amount),
            step=lambda key, kind: self.store.step(run["id"], key, kind),
            existing_step=lambda key: self.store.existing_step(run["id"], key),
            start_step=self.store.start_step, send=send, host_gate=fetch_module.host_gate,
            headers=self.deps.http.headers)
        await watch_run(watches, check, callbacks, self.deps.settings)

    # ---- owner-requested review ---------------------------------------------------------
    def _owner_review_send_gate(self, run: dict) -> None:
        from datetime import datetime
        from deixis.workflow.review.run import ReviewDeadlinePassed
        self._checkpoint(run["id"])
        if self.store.run(run["id"])["status"] != "running":
            raise RunStopped
        try:
            self.store.research(run["research_id"])
        except NotFound:
            self._fail(run["id"], "research_unavailable")
        if self.deps.package.package_hash != run["target"]["skill_package_hash"]:
            self._fail(run["id"], "skill_package_changed")
        if datetime.fromisoformat(now()) >= datetime.fromisoformat(run["target"]["deadline_at"]):
            raise ReviewDeadlinePassed

    async def _owner_review(self, run: dict) -> None:
        from deixis.workflow.review import run as reviews
        from deixis.workflow.review.reader import ReviewReader
        from deixis.workflow.review.store import ReviewStore, resolve_finding
        from deixis.workflow.report.store import ReportStore
        from deixis.workflow.report.review import REVIEW_BUDGET_TOKENS
        rs = ReviewStore(self.store.conn, ReviewReader(self.store, ReportStore(self.store)))
        row = self.store.conn.execute("SELECT * FROM owner_reviews WHERE run_id = ?", (run["id"],)).fetchone()
        if row is None:
            self._fail(run["id"], "review_unavailable")
        review = dict(row)
        try:
            snapshot = rs.snapshot(review["snapshot_id"])
        except NotFound:
            self._fail(run["id"], "research_unavailable")
        content = snapshot["content"]
        scope = content["scope"]
        model = (review["requested_connection"], review["requested_model"], review["requested_effort"])
        omitted = json.loads(review["sections_not_reviewed_json"])

        def not_reviewed(group, reason, output=None):
            output = output or {}
            for ref in group["claim_refs"]:
                claim = next(c for c in content["claims"] if c["claim_ref"] == ref)
                entry = {"group_index": group["group_index"], "claim_ref": ref, "section_ref": claim["section_ref"],
                         "reason": reason, "step_input_id": output.get("blocked_step_input_id") or output.get("step_input_id"),
                         "request_chars": output.get("request_chars")}
                if entry not in omitted:
                    omitted.append(entry)
            if not group["claim_refs"]:
                for source_id in group.get("source_ids", []) or [None]:
                    entry = {"group_index": group["group_index"], "claim_ref": None, "section_ref": None,
                             "source_id": source_id, "reason": reason,
                             "step_input_id": output.get("blocked_step_input_id") or output.get("step_input_id"),
                             "request_chars": output.get("request_chars")}
                    if entry not in omitted:
                        omitted.append(entry)
            rs.set_not_reviewed(review["id"], omitted)

        for group in run["target"]["plan"]["groups"]:
            self._checkpoint(run["id"])
            key = f"owner_review:{group['group_index']}"
            step = self.store.existing_step(run["id"], key)
            if step and step["status"] == "succeeded":
                output = step["output"]
            elif step and step["status"] == "failed" and step["error_code"] in ("invalid_model_output", "message_too_large"):
                output = (step["output"] or {}) | {"invalid": True}
                not_reviewed(group, output.get("size_failure_reason", step["error_code"]), output)
                continue
            else:
                def builder(step_id):
                    return reviews.review_step_input(snapshot["id"], content, review, group, run_id=run["id"],
                        step_id=step_id, research_id=run["research_id"], package_hash=run["target"]["skill_package_hash"],
                        capabilities=CAPABILITIES, budget=run["budget"], step_input_id=new_id("sti"), created_at=now())

                def gate():
                    self._owner_review_send_gate(run)

                def resend():
                    gate()
                    return self.store.run(run["id"])["usage"].get("model_calls", 0) < run["budget"]["max_model_calls"]

                try:
                    gate()
                    output = await self.deps.limiter.run(f"{run['id']}:{key}", lambda: self._model_step(
                        run, scope, key, "owner_review", model=model, limiter=self.deps.limiter,
                        send_gate=gate, resend_guard=resend, step_input_builder=builder,
                        max_request_chars=REVIEW_BUDGET_TOKENS * 4,
                        attempt_record=lambda payload: {"send_record": {"task": "owner_review", "group_index": group["group_index"]}}))
                except reviews.ReviewDeadlinePassed:
                    step = self.store.existing_step(run["id"], key)
                    if step and step["status"] == "running":
                        self.store.finish_step(step["id"], "failed", output=step["output"], error_code="deadline_passed")
                    not_reviewed(group, "deadline_passed")
                    continue
            if output.get("invalid"):
                not_reviewed(group, output.get("size_failure_reason", "invalid_model_output"), output)
                continue
            payload = self.store.step_input_payload(output["step_input_id"])
            resolved = [resolve_finding(content, payload, finding) for finding in output["result"]["findings"]]
            rs.add_group_findings(review["id"], payload["step_input_id"], resolved)

    # ---- model steps -------------------------------------------------------------------
    def _lineage_send_gate(self, run: dict[str, Any]) -> None:
        self._checkpoint(run["id"], run["scope_revision"])
        if self.store.run(run["id"])["status"] != "running":
            raise RunStopped

    async def _lineage_links(self, run: dict[str, Any], scope: dict[str, Any]) -> None:
        from deixis.workflow.lineage import run as lineage
        from deixis.workflow.lineage.store import LineageStore

        self._lineage_send_gate(run)
        plan = run["target"]

        def table_available() -> None:
            row = self.store.conn.execute("SELECT trashed_at FROM evidence_tables WHERE id = ?",
                                          (plan["table_id"],)).fetchone()
            if row is None or row["trashed_at"] is not None:
                self._fail(run["id"], "table_unavailable")

        table_available()
        publication = self.store.existing_step(run["id"], "lineage_publication")
        if publication and publication["status"] == "succeeded":
            return
        outputs: list[tuple[dict, lineage.LineageJob]] = []

        async def call(job: lineage.LineageJob) -> dict:
            # Stored successes are judged at publication even after exclusion or a human edit.
            step = self.store.existing_step(run["id"], job.key)
            if step and step["status"] == "succeeded":
                output = step["output"]
            elif step and step["status"] == "failed" and step["error_code"] in ("invalid_model_output", "message_too_large"):
                output = step["output"] | {"invalid": True,
                                           "issues": step["output"].get("issues", json.loads(step["error_json"] or "[]")),
                                           "message_too_large": step["error_code"] == "message_too_large"}
            else:
                try:
                    target, passages = lineage.refresh_job(self.store, plan["table_id"], job)

                    def gate() -> None:
                        self._lineage_send_gate(run)
                        # Health/repair awaits may change cells or passages. Refresh before the real payload is built.
                        fresh, rows = lineage.refresh_job(self.store, plan["table_id"], job)
                        target.clear()
                        target.update(fresh)
                        passages[:] = rows

                    def resend() -> bool:
                        self._lineage_send_gate(run)
                        return self.store.run(run["id"])["usage"].get("model_calls", 0) < run["budget"]["max_model_calls"]

                    output = await self._model_step(
                        run, scope, job.key, "lineage_links", source_ids=[job.chunk["to"], *job.chunk["from"]],
                        passage_rows=passages, lineage_target=target, limiter=self.deps.limiter,
                        model=tuple(plan["model"]), step_output_extra={"chunk_key": job.key},
                        max_message_chars=48_000, send_gate=gate, resend_guard=resend,
                        attempt_record=lambda payload: lineage.send_record(self.store, payload, plan["model"][2]),
                    )
                except lineage.ChunkSkipped as exc:
                    step = self.store.step(run["id"], job.key, "model:lineage_links")
                    output = (step["output"] or {}) | {"skipped": str(exc), "chunk_key": job.key}
                    self.store.finish_step(step["id"], "cancelled", output=output, error_code=str(exc))
            outputs.append((output, job))
            return output

        def jobs():
            for job in lineage.lineage_jobs(plan):
                self._lineage_send_gate(run)
                yield job

        stop = await self._send_through_limiter(run, jobs(), call, lambda completed: None)
        if stop is not None:
            raise stop
        self._lineage_send_gate(run)
        if len(outputs) != len(plan["chunks"]):
            self._fail(run["id"], "lineage_nonterminal")
        try:
            with transaction(self.store.conn):
                self._lineage_send_gate(run)
                table_available()
                proposals = lineage.publication_proposals(self.store, run, outputs, self.lineage_step_input)
                results = LineageStore(self.store).apply_model_proposals(
                    proposals, stale_revisions=lineage.stale_link_revisions(self.store, plan["table_id"]))
                record = lineage.publication_record(plan, outputs, proposals, results)
                step = self.store.step(run["id"], "lineage_publication", "lineage_publication")
                self.store.start_step(step["id"])
                self.store.finish_step(step["id"], "succeeded", output=record)
        except RunStopped:
            # A pause/cancel written inside a rolled-back transaction must still be recorded.
            self._lineage_send_gate(run)
            table_available()
            raise
        except Exception as exc:
            self._fail(run["id"], "lineage_publication_failed", {"error": f"{type(exc).__name__}: {exc}"})

    def lineage_step_input(self, research_id: str, scope_revision: int, lineage_target: dict[str, Any],
                           passage_rows: list[dict[str, Any]], max_model_calls: int) -> dict[str, Any]:
        scope = self.store.scope(research_id, scope_revision)
        run = {"id": new_id("run"), "research_id": research_id, "scope_revision": scope_revision,
               "budget": {"max_model_calls": max_model_calls, "max_provider_requests": 0}}
        source_ids = [lineage_target["to"]["source_id"],
                      *[c["from"]["source_id"] for c in lineage_target["candidates"]]]
        return self._step_input(run, scope, new_id("stp"), "lineage_links", [], source_ids, passage_rows, [],
                                step_model(scope, "lineage_links"), lineage_target=lineage_target)

    def lineage_message_chars(self, payload: dict[str, Any]) -> int:
        shown = contracts.with_citation_handles(payload)
        return len(prompt.step_message(shown))

    def _step_input(self, run: dict[str, Any], scope: dict[str, Any], step_id: str, task_type: str,
                    candidate_rows: list[dict[str, Any]], source_ids: list[str], passage_rows: list[dict[str, Any]],
                    claims: list[dict[str, Any]], model: tuple[str, str | None, str | None],
                    extraction_target: dict[str, Any] | None = None,
                    report_target: dict[str, Any] | None = None,
                    vocabulary_target: dict[str, Any] | None = None,
                    screening_target: dict[str, Any] | None = None,
                    suggestion_target: dict[str, Any] | None = None,
                    adjudication_target: dict[str, Any] | None = None,
                    lineage_target: dict[str, Any] | None = None,
                    candidate_target: dict[str, Any] | None = None,
                    advice_target: dict[str, Any] | None = None) -> dict[str, Any]:
        candidates = []
        for c in candidate_rows:
            source = self.store.source(c["source_version_id"])
            abstract = next((p for p in self.store.passages_for(source["id"]) if p["kind"] == "abstract"), None)
            candidates.append({
                "candidate_id": c["candidate_id"], "title": source["title"], "year": source["year"], "venue": source["venue"],
                "abstract": abstract["text"][:MAX_ABSTRACT_CHARS] if abstract else None,
                "abstract_origin": abstract["abstract_origin"] if abstract else None,
                "identifiers": {"doi": source["doi"]} if source["doi"] else {},
            })
        sources = []
        for svid in source_ids:
            source = self.store.source(svid)
            kinds = {p["kind"] for p in self.store.passages_for(svid)}
            if task_type == "grounded_answer" and fast_path.enforces(run["budget"], "answer"):
                kinds = {p["kind"] for p in passage_rows if p["source_version_id"] == svid}
            access = "pdf_available" if "pdf_page" in kinds else "abstract" if "abstract" in kinds else "metadata"
            sources.append({"source_id": svid, "work_id": source["work_id"], "title": source["title"], "year": source["year"],
                            "version_label": source["version_label"], "access_level": access})
        passages = [{
            "passage_id": p["id"], "source_id": p["source_version_id"],
            "reading_depth": "abstract" if p["kind"] == "abstract" else "selected_sections",
            "locator": {"kind": p["kind"], "physical_page": p["physical_page"], "printed_label": p["printed_label"]},
            "abstract_origin": p["abstract_origin"],
            "text_source": None if p["kind"] == "abstract" else p.get("text_source", "text_layer"), "text": p["text"],
        } for p in passage_rows]
        language = scope["language_hint"] if scope["language_hint"] and re.fullmatch(r"[a-z]{2,3}(-[A-Za-z0-9]{2,8})*", scope["language_hint"]) else None
        review = {"claims_under_review": claims} if task_type == "answer_review" else {}
        target = {}
        if extraction_target is not None:
            target["extraction_target"] = extraction_target
        if report_target is not None:
            target["report_target"] = {"validation_context": None, **report_target}
        if vocabulary_target is not None:
            target["vocabulary_target"] = vocabulary_target
        if screening_target is not None:
            target["screening_target"] = screening_target
        if suggestion_target is not None:
            target["suggestion_target"] = suggestion_target
        if adjudication_target is not None:
            target["adjudication_target"] = adjudication_target
        if lineage_target is not None:
            target["lineage_target"] = lineage_target
        if candidate_target is not None:
            target["candidate_target"] = candidate_target
        if advice_target is not None:
            target["advice_target"] = advice_target
        allowlist = {"candidate_ids": [c["candidate_id"] for c in candidates], "source_ids": [s["source_id"] for s in sources],
                     "passage_ids": [p["passage_id"] for p in passages]}
        if task_type == "claim_assessment" and candidate_target is not None and candidate_target["version"] is not None:
            allowlist["element_ids"] = [e["element_id"] for e in candidate_target["version"]["elements"]]
        if vocabulary_target is not None:
            # The allowlist for this step is the phrase list itself: it may label those phrases and name no other.
            allowlist["phrases"] = [entry["phrase"] for entry in vocabulary_target["phrases"]]
        if suggestion_target is not None:
            # The same rule for the suggestion step: a proposed name may be another name for one of these phrases
            # and for no other phrase (slice 08c).
            allowlist["phrases"] = [entry["phrase"] for entry in suggestion_target["phrases"]]
        if advice_target is not None:
            # Advice may name a warned phrase and no other (D232).
            allowlist["phrases"] = [entry["phrase"] for entry in advice_target["warnings"]]
        if task_type in contracts.REPORT_TASKS:
            report = report_target or {}
            cells, gaps = report.get("cells", []), report.get("gap_candidates", [])
            columns = [column["column_id"] for column in report.get("columns", [])]
            columns += [cell["column_id"] for cell in cells] + [gap["column_id"] for gap in gaps]
            columns += [axis["column_id"] for axis in (report.get("plan") or {}).get("axes", [])]
            allowlist |= {"column_ids": list(dict.fromkeys(columns)),
                          "cell_ids": [cell["cell_id"] for cell in cells],
                          "gap_ids": [gap["gap_id"] for gap in gaps]}
            if task_type == "report_section" and report.get("section_id") == "VII":
                allowlist["gap_ids"] = [g["gap_id"] for g in (report.get("validation_context") or {}).get("accepted_gaps", [])]
        return review | target | {
            "step_input_id": new_id("sti"), "research_id": run["research_id"], "run_id": run["id"], "step_id": step_id,
            "task_type": task_type, "scope_revision": run["scope_revision"],
            "skill_package_hash": self.deps.package.package_hash, "skill_files": list(RUNTIME_FILES[task_type]),
            "output_schema_versions": [contracts.SCHEMA_VERSIONS[o] for o in contracts.TASK_OUTPUTS[task_type]],
            "question": {"text": scope["question"], "language_hint": language},
            "user_steering": [scope["steering"]] if scope.get("steering") else [],
            # The providers a query may go to. A verification connector stays in the research's scope for the records
            # whose DOI is already known, and is never offered to the model as a place to search (D87).
            "capabilities": CAPABILITIES,
            "enabled_providers": search_providers(scope["providers"], scope.get("search_workflow")),
            "candidates": candidates, "sources": sources, "passages": passages,
            "allowlist": allowlist,
            "human_corrections": [],
            "budget": {"max_model_calls": small_batch.model_call_allowance(run["budget"]), "max_schema_repairs": schema_repairs(task_type),
                       "max_provider_requests": run["budget"]["max_provider_requests"]},
            "model": {"connection": model[0], "requested_model": model[1]},
            "created_at": now(),
        }

    def _model_result_checkpoint(self, session: str, result: ModelStepResult, run_id: str, rid: str,
                                 step_id: str, step_input_id: str, step_attempt: int) -> bool:
        """Record discarded transport results without changing a closed or superseded step."""
        fields = {"resolved_model": result.resolved_model, "external_thread_id": result.external_thread_id,
                  "raw_output": result.raw_text, "token_usage_json": result.token_usage,
                  "tool_item_types_json": result.tool_item_types}
        with transaction(self.store.conn):
            if not self.store.model_attempt_active(session, rid, run_id, step_id, step_input_id, step_attempt):
                row = self.store.conn.execute("SELECT raw_output, validation_json, finished_at FROM model_sessions WHERE id = ?", (session,)).fetchone()
                if row is not None:
                    validation = json.loads(row["validation_json"]) if row["validation_json"] else {}
                    validation.setdefault("discarded_results", []).append(fields | {"code": "model_attempt_inactive"})
                    self.store.finish_model_session(session, **(fields if row["raw_output"] is None else {}),
                                                    validation_json=validation)
                    self.store.conn.execute("UPDATE model_sessions SET finished_at = ? WHERE id = ?", (row["finished_at"], session))
                return False
        return True

    def _send_window(self, run_id: str) -> float | None:
        """Seconds a model answer of this run is still waited for (D258), or None when no read window bounds it."""
        send_by = getattr(self, "_send_by", {}).get(run_id)
        limit = send_by() if send_by is not None else None
        return None if limit is None else (limit - self.store.clock.now()).total_seconds()

    async def _call_adapter(self, run_id: str, rid: str, step_id: str, step_input_id: str, connection: str,
                            requested_model: str | None, adapter: ModelAdapter, base: str, developer: str, message: str,
                            schema: dict[str, Any], reasoning_effort: str | None,
                            limiter: ModelCallLimiter | None,
                            resend: Callable[[], bool] | None = None) -> tuple[str | None, ModelStepResult]:
        """Send one model call, resending under a lower ceiling after a rate-limit response.

        Resends reuse the stored StepInput because their model input is identical, and each gets its own model session.
        Passing no limiter keeps the existing one-attempt behavior for model steps outside table fill. `resend` is
        asked right before a resend: when it says no (a person decided a work of this input meanwhile, slice 16), the
        call returns no session and the rate-limited result, and the caller builds its next input itself.
        """
        attempts = 0
        while True:
            step_attempt = self.store.conn.execute("SELECT attempt FROM run_steps WHERE id = ?", (step_id,)).fetchone()[0]
            remaining = self._send_window(run_id)
            if remaining is not None and remaining <= 0:
                raise _ReadCutoff  # not sent, so no session is opened and nothing is charged
            session = self.store.start_model_session(rid, run_id, step_id, step_input_id, connection, requested_model)
            if remaining is None:
                result = await adapter.run_step(base, developer, message, schema, requested_model, reasoning_effort)
            else:
                try:
                    result = await asyncio.wait_for(
                        adapter.run_step(base, developer, message, schema, requested_model, reasoning_effort), remaining)
                except TimeoutError:
                    # D258: the read window's cutoff does not wait for this answer; it would arrive too late to count.
                    result = ModelStepResult("cutoff", error="read_cutoff", delivery_class="after_send_unknown")
            if not self._model_result_checkpoint(session, result, run_id, rid, step_id, step_input_id, step_attempt):
                raise RunStopped
            if (limiter is None or result.status == "completed" or attempts >= MAX_RATE_LIMIT_MODEL_RETRIES
                    or not is_rate_limited(result)):
                return session, result
            attempts += 1
            self.store.finish_model_session(
                session, status=result.status, resolved_model=result.resolved_model,
                external_thread_id=result.external_thread_id, raw_output=result.raw_text,
                token_usage_json=result.token_usage, tool_item_types_json=result.tool_item_types,
            )
            await limiter.reduce()
            self._checkpoint(run_id)
            window = self._send_window(run_id)
            if window is not None and window <= RATE_LIMIT_BACKOFF_SECONDS * attempts:
                raise _ReadCutoff  # D258: the resend would come after the read cutoff
            self.store.service_waiting(run_id, connection, attempts, RATE_LIMIT_BACKOFF_SECONDS * attempts)
            await asyncio.sleep(RATE_LIMIT_BACKOFF_SECONDS * attempts)
            self._checkpoint(run_id)
            guard = getattr(self, "_small_batch_guard", None)
            if guard and guard["run_id"] == run_id and not self._model_calls_left(
                    self.store.run(run_id), len(guard.get("reserved_calls", set())) + 1):
                return session, result
            if resend is not None and not resend():
                return None, result

    async def _cap_inference(self, run: dict[str, Any], scope: dict[str, Any], output: dict[str, Any],
                             key: str) -> tuple[dict[str, Any], str, dict[str, Any] | None]:
        """D260: a valid answer whose claims are mostly analyst_inference gets one rewrite call.

        The rewrite is published only when it is valid and no longer over the cap; otherwise the valid answer stands.
        It never makes an answer unpublished. A resumed run gets the stored step back, so nothing is sent twice.
        """
        labels = contracts.inference_cap_labels(output["result"])
        if not labels:
            return output, key, None
        run_id = run["id"]
        record = {"labels": labels, "claims": len(output["result"]["claims"])}
        if (self.store.existing_step(run_id, INFERENCE_CAP_KEY) is None
                and self.store.run(run_id)["usage"].get("model_calls", 0) >= run["budget"]["max_model_calls"]):
            self._checkpoint(run_id, run["scope_revision"])
            return output, key, record | {"outcome": "skipped_budget"}  # checked before the connection is touched
        frozen = self.store.step_input_payload(output["step_input_id"])
        # The accepted answer (after any D244 salvage or D259 relabelling) is quoted, in the handles the model was shown.
        seed = {"kind": "inference_cap", "labels": labels, "claim_count": len(output["result"]["claims"]),
                "raw_output": contracts.answer_with_handles(frozen, output["result"]), "step_input_id": output["step_input_id"],
                "issues": [{"code": "too_many_inference_claims", "path": "/claims",
                            "message": f"{len(labels)} of {len(output['result']['claims'])} claims are analyst_inference"}]}
        connection, requested, effort = step_model(scope, "grounded_answer")
        if frozen["model"]["requested_model"] is not None:
            connection, requested = frozen["model"]["connection"], frozen["model"]["requested_model"]

        def same_input(step_id: str, frozen=frozen) -> dict[str, Any]:
            return copy.deepcopy(frozen) | {"step_input_id": new_id("sti"), "step_id": step_id, "created_at": now()}
        try:
            # Optional: a connection or call failure keeps the valid answer instead of pausing the run; a stop or a
            # newer scope revision still stops it.
            second = await self._model_step(run, scope, INFERENCE_CAP_KEY, "grounded_answer", step_input_builder=same_input,
                                            model=(connection, requested, effort), optional=True,
                                            selection_revision=self.store.step_input_selection_revision(output["step_input_id"]),
                                            budget_short="skip", resplit=seed)
        except OptionalStepFailed as failed:
            self._checkpoint(run_id, run["scope_revision"])  # a question changed meanwhile stops the run, not publishes
            return output, key, record | {"outcome": "call_failed", "reason": failed.reason}
        self._checkpoint(run_id, run["scope_revision"])
        if second.get("repair_skipped"):
            return output, key, record | {"outcome": "skipped_budget"}
        stored = (self.store.existing_step(run_id, INFERENCE_CAP_KEY) or {}).get("output") or {}
        if (stored.get("inference_cap") or {}).get("relabelled"):
            record["relabelled"] = stored["inference_cap"]["relabelled"]
        if second.get("invalid"):
            return output, key, record | {"outcome": "kept_first"}
        record["rewrite"] = {"inference": len([c for c in second["result"]["claims"] if c["support_type"] == "analyst_inference"]),
                             "claims": len(second["result"]["claims"])}
        if contracts.over_inference_share(second["result"]):  # the share alone decides, whatever the claim count
            return output, key, record | {"outcome": "kept_first"}
        return second, INFERENCE_CAP_KEY, record | {"outcome": "published"}

    def _answer_repair_state(self, step_id: str, resplit: dict[str, Any] | None, max_repairs: int) -> tuple[int | None, dict[str, Any] | None, int, bool]:
        """D249: what an answer step's stored sessions say. (last attempt number, last failed session, repairs used, cap reached)

        The cap is one repair for the answer step and, for the extra-repair step, that one call after the repair it follows.
        """
        stored = self.store.conn.execute(
            "SELECT si.attempt, si.id, m.raw_output, m.validation_json FROM step_inputs si"
            " LEFT JOIN model_sessions m ON m.step_input_id = si.id WHERE si.step_id = ?"
            " ORDER BY si.rowid, m.rowid", (step_id,)).fetchall()
        failed = [r for r in stored if r["validation_json"] and json.loads(r["validation_json"]).get("ok") is False]
        attempt = max((r["attempt"] for r in stored), default=None)
        if not failed:
            return attempt, None, 0, False
        used = (max_repairs if resplit is not None else 0) + len({r["id"] for r in failed})
        return attempt, failed[-1], min(used, max_repairs), used > max_repairs

    async def _model_step(self, run: dict[str, Any], scope: dict[str, Any], operation_key: str, task_type: str,
                          candidate_rows: list[dict[str, Any]] | None = None, source_ids: list[str] | None = None,
                          passage_rows: list[dict[str, Any]] | None = None, selection_revision: int | None = None,
                          claims: list[dict[str, Any]] | None = None, model: tuple[str, str | None, str | None] | None = None,
                          optional: bool = False, extraction_target: dict[str, Any] | None = None,
                          report_target: dict[str, Any] | None = None, vocabulary_target: dict[str, Any] | None = None,
                          screening_target: dict[str, Any] | None = None,
                          suggestion_target: dict[str, Any] | None = None,
                          adjudication_target: dict[str, Any] | None = None,
                          limiter: ModelCallLimiter | None = None, budget_short: str = "pause",
                          recheck: Callable[[list[dict[str, Any]]], list[dict[str, Any]] | None] | None = None,
                          step_output_extra: dict[str, Any] | None = None,
                          lineage_target: dict[str, Any] | None = None,
                          max_message_chars: int | None = None,
                          resend_guard: Callable[[], bool] | None = None,
                          send_gate: Callable[[], None] | None = None,
                          attempt_record: Callable[[dict[str, Any]], dict[str, Any]] | None = None,
                          candidate_target: dict[str, Any] | None = None,
                          step_input_builder: Callable[[str], dict] | None = None,
                          max_request_chars: int | None = None,
                          advice_target: dict[str, Any] | None = None,
                          resplit: dict[str, Any] | None = None,
                          ) -> dict[str, Any]:
        """Run one model step on the model chosen for its role. An optional step raises OptionalStepFailed instead of
        pausing or failing the run; a user pause or cancel still stops the run. `budget_short="skip"` is the sw
        stages' rule (D86): a call the budget no longer holds is closed and returned as invalid instead of pausing
        the run, because those stages count what the budget did not reach and a later run reads it."""
        if report_target is not None:
            report_target = {"limitations_core": None, "review_sections": None, "validation_context": None, **report_target}
        run_id, rid = run["id"], run["research_id"]
        step = self.store.step(run_id, operation_key, f"model:{task_type}")
        if step["status"] == "succeeded":
            return step["output"]
        model = model or step_model(scope, task_type)
        connection, requested_model, reasoning_effort = model

        def halt(reason: str, detail: Any = None, fail: bool = False) -> None:
            if optional:
                raise OptionalStepFailed(reason, detail)
            (self._fail if fail else self._pause)(run_id, reason, detail)

        if task_type == "grounded_answer" and attempt_record is None:
            # D249: an answer already judged invalid by its stored sessions is recovered without the connection; the
            # run and revision guards still apply.
            _, last, _, capped = self._answer_repair_state(step["id"], resplit, schema_repairs(task_type))
            if capped:
                self._checkpoint(run_id, run["scope_revision"])
                relabelled = json.loads(last["validation_json"]).get("relabelled")  # D259: kept across the recovery
                output = {"step_input_id": last["id"]} | (
                    {resplit.get("kind", "resplit"): {"labels": resplit["labels"], "outcome": "rejected"}
                     | ({"relabelled": relabelled} if relabelled else {})}
                    if resplit is not None else {})
                self.store.start_step(step["id"])
                self.store.finish_step(step["id"], "failed", output=output, error_code="invalid_model_output",
                                       error=json.loads(last["validation_json"])["issues"])
                return {"invalid": True, "raw_output": last["raw_output"], "issues": json.loads(last["validation_json"])["issues"],
                        "step_input_id": last["id"]} | output
        adapter = self.deps.adapters.get(connection)
        if adapter is None:
            halt("model_connection_unavailable", {"connection": connection})

        def cut_before_send() -> dict[str, Any]:
            # D258: closed for good at the read cutoff; the abstract and full-text stages read it as not read in time.
            self.store.finish_step(step["id"], "cancelled", error_code="model_read_cutoff", error="read_cutoff")
            return {"cutoff": True}

        window = self._send_window(run_id)
        if window is not None:
            try:
                if window <= 0:
                    raise TimeoutError
                health = await asyncio.wait_for(adapter.health(), window)
            except TimeoutError:
                return cut_before_send()
        else:
            health = await adapter.health()
        if not health.get("ready"):
            halt("model_connection_not_ready", {"connection": connection, "reason": safe_error(health.get("reason")),
                 **({"error_kind": health["reason_code"]} if health.get("reason_code") else {}), "reset_at": health.get("reset_at")})
        self._checkpoint(run_id)  # a pause or cancel may have arrived while the connection was checked

        def unchanged() -> bool:
            """Whether a rate-limited call may be resent as it is: no work of its input was decided meanwhile."""
            if resend_guard is not None and not resend_guard():
                return False
            wanted = recheck(candidate_rows or []) if recheck is not None else candidate_rows or []
            return wanted is not None and len(wanted) == len(candidate_rows or [])

        self.store.start_step(step["id"])
        repair_issues: list[dict[str, Any]] | None = None
        output_text, invalid_raw, invalid_input = None, None, None
        max_repairs = schema_repairs(task_type)
        # `attempt` numbers every call this step sends; `repairs` counts only the schema repairs among them, so the
        # one resend after a turn timeout (slice 13e) takes nothing from the repairs the step is allowed.
        attempt, repairs, timeout_resent = -1, 0, False
        if resplit is not None:
            # D249: this step is the one extra repair of a failed answer, so its first call is a repair and it has
            # none left; the failed output and its issues come from the step before.
            repair_issues, invalid_raw, invalid_input, repairs = (
                resplit["issues"], resplit["raw_output"], resplit["step_input_id"], max_repairs)

        split_relabel: dict[str, list[str]] = {}

        def resplit_meta(outcome: str) -> dict[str, Any]:
            if resplit is None:
                return {}
            if resplit.get("kind") == "inference_cap" and outcome == "published":
                outcome = "valid"  # D260: whether the rewrite replaces the answer is decided by _cap_inference
            return {resplit.get("kind", "resplit"): {"labels": resplit["labels"], "outcome": outcome}
                    | ({"relabelled": split_relabel} if split_relabel else {})}
        extra = step_output_extra or {}
        sent_extra, sent_input = None, None
        attempt_records = {}
        if attempt_record is not None:
            # Opt-in recovery: session validation is durable even if a stop/crash precedes its repair.
            previous = self.store.conn.execute(
                "SELECT si.attempt, si.id, m.raw_output, m.validation_json FROM step_inputs si"
                " JOIN model_sessions m ON m.step_input_id = si.id WHERE si.step_id = ?"
                " ORDER BY si.rowid, m.rowid", (step["id"],)).fetchall()
            invalids = [r for r in previous if r["validation_json"] and json.loads(r["validation_json"]).get("ok") is False]
            repairs = len({r["id"] for r in invalids})
            attempt = self.store.conn.execute(
                "SELECT COALESCE(MAX(attempt), -1) FROM step_inputs WHERE step_id = ?", (step["id"],)).fetchone()[0]
            if invalids:
                last = invalids[-1]
                repair_issues = json.loads(last["validation_json"])["issues"]
                invalid_raw, invalid_input = last["raw_output"], last["id"]
            if step["output"]:
                attempt_records = dict(step["output"].get("attempt_records", {}))
                # Older outputs keep only one record. It still needs a session to count as sent.
                legacy_id = step["output"].get("step_input_id")
                if legacy_id and "send_record" in step["output"]:
                    attempt_records.setdefault(legacy_id, (step_output_extra or {}) |
                                               {"send_record": step["output"]["send_record"]})
                for row in reversed(previous):
                    if row["id"] in attempt_records:
                        sent_input = row["id"]
                        sent_extra = attempt_records[sent_input]
                        break

        used_up = False
        if task_type == "grounded_answer" and attempt_record is None:
            # D249: a resumed answer step keeps the repairs its stored sessions already used, so the cap (one repair,
            # and the one extra repair of the step after it) holds across a stop and a resume, and a failed answer is
            # recovered from its stored sessions instead of being asked for again.
            last_attempt, last, used, used_up = self._answer_repair_state(step["id"], resplit, max_repairs)
            if last_attempt is not None:
                attempt = last_attempt
            if last is not None:
                repairs = used
                repair_issues = json.loads(last["validation_json"])["issues"]
                invalid_raw, invalid_input = last["raw_output"], last["id"]

        def sent_output() -> dict[str, Any]:
            # finish_step clears output by default. Only the attempt-record hook preserves
            # provenance. A prepared input is sent only once it owns a model session.
            return {"output": (sent_extra or {}) | {"step_input_id": sent_input,
                    "attempt_records": attempt_records}} if attempt_record is not None else {}

        if used_up:
            output = {"step_input_id": invalid_input} | resplit_meta("rejected")
            self.store.finish_step(step["id"], "failed", output=output, error_code="invalid_model_output", error=repair_issues)
            return {"invalid": True, "raw_output": invalid_raw, "issues": repair_issues, "step_input_id": invalid_input} | output
        while True:
            attempt += 1
            # All opt-in gates, payload/record construction and session start share a synchronous
            # section: no await after health/limiter waits or between these checks and the send.
            if send_gate is not None:
                send_gate()
            if recheck is not None:
                # The last look before each send (slice 16), the first one and every resend: a person may have
                # decided a work while the connection was checked or while an earlier attempt was out. The candidates
                # still wanted are sent; with none, the step is closed unsent. That is a skip, not a failure: a resumed
                # run opens the step again, and sends it if the decision was taken back.
                wanted = recheck(candidate_rows or [])
                if wanted is None:
                    self.store.finish_step(step["id"], "cancelled", error_code="human_decided", **sent_output())
                    return {"invalid": True, "issues": [], "step_input_id": None, "human_decided": True}
                candidate_rows = wanted if candidate_rows is not None else candidate_rows
            guard = getattr(self, "_small_batch_guard", None)
            reserved = guard.get("reserved_calls", set()) if guard and guard["run_id"] == run_id else set()
            if (self.store.run(run_id)["usage"].get("model_calls", 0)
                    + len(reserved - {operation_key}) >= run["budget"]["max_model_calls"]):
                if repair_issues is not None and budget_short == "skip":
                    # A repair the budget no longer holds is skipped (D86): the invalid answer stands for this run,
                    # as an unrepaired one does, and the run goes on to what it can still afford.
                    output = sent_output().get("output", {"step_input_id": invalid_input}) | resplit_meta("skipped_budget")
                    self.store.finish_step(step["id"], "failed", output=output,
                                           error_code="invalid_model_output", error=repair_issues)
                    return {"invalid": True, "raw_output": invalid_raw, "issues": repair_issues,
                            "step_input_id": invalid_input, "repair_skipped": "budget_exhausted"} | output
                if budget_short == "skip":
                    # A concurrent sender checked the room before this call and a repair in flight took it. The
                    # work is not reached: no decision is written for it and the run finishes rather than pausing.
                    self.store.finish_step(step["id"], "failed", error_code="budget_exhausted", **sent_output())
                    return {"invalid": True, "issues": [], "step_input_id": None, "not_reached": True} | sent_output().get("output", {})
                self.store.finish_step(step["id"], "failed", error_code="budget_exhausted", **sent_output())
                # Resume keeps the counter and ceiling: cancel and request a new preview to progress.
                halt("budget_exhausted", {"limit": "model_calls"})
            payload = step_input_builder(step["id"]) if step_input_builder is not None else self._step_input(run, scope, step["id"], task_type, candidate_rows or [], source_ids or [], passage_rows or [],
                                       claims or [], model, extraction_target, report_target, vocabulary_target,
                                       screening_target, suggestion_target, adjudication_target, lineage_target, candidate_target,
                                       advice_target)
            if attempt_record is not None:
                extra = (step_output_extra or {}) | attempt_record(payload)
            if issues := contracts.check_step_input(payload):
                blocked = {"output": sent_output()["output"] | {"blocked_step_input_id": payload["step_input_id"],
                           "blocked_send_record": extra}} if attempt_record is not None else {}
                self.store.finish_step(step["id"], "failed", error_code="step_input_invalid", error=[vars(i) for i in issues], **blocked)
                halt("step_input_invalid", fail=True)
            anchor_context = []
            patch_base, patch_base_input = output_text, invalid_input
            first_anchor_issues = repair_issues
            if repair_issues is not None and task_type == "report_section":
                failed_input = self.store.step_input_payload(invalid_input)
                anchor_context = contracts.report_section_anchor_repair_context(failed_input, patch_base, repair_issues)
            anchor_patch = task_type == "report_section" and contracts.report_section_anchor_patch_eligible(
                repair_issues or [], anchor_context)
            schema = (contracts.report_section_anchor_patch_schema() if anchor_patch
                      else contracts.model_output_schema(task_type))
            base = prompt.BASE_INSTRUCTIONS
            sections = (phrasebank.REPORT_PHRASEBANK_SECTIONS[payload["report_target"]["section_id"]]
                        if task_type in ("report_section", "report_phrase_repair") else None)
            developer = prompt.developer_instructions(
                self.deps.package, task_type, phrasebank.frames_language(payload), sections=sections,
            )
            if not adapter.enforces_schema:
                developer = developer + "\n\n" + prompt.schema_appendix(task_type, schema)
            # Handled steps show short IDs; the stored StepInput keeps the record IDs they map back to.
            shown = contracts.with_citation_handles(payload) if task_type in HANDLE_TASKS else payload
            if repair_issues is None:
                message = prompt.step_message(shown)
            else:  # issues name records by ID; the model knows them only by the handles it was shown
                shown_context = json.loads(json.dumps(anchor_context))
                if shown_context:
                    handles = contracts.report_citation_handles(payload)
                    for pair in shown_context:
                        pair["cell_id"] = handles[pair["cell_id"]]
                shown_issues = contracts.issues_with_handles(payload, repair_issues) if shown is not payload else repair_issues
                if resplit is not None and resplit.get("kind") == "inference_cap":
                    message = prompt.inference_cap_message(shown, resplit["raw_output"], resplit["labels"], resplit["claim_count"])
                elif resplit is not None:
                    message = prompt.resplit_message(shown, shown_issues, resplit["raw_output"], resplit["labels"])
                elif task_type == "report_section":
                    message = prompt.repair_message(shown, shown_issues, shown_context,
                                                    failed_output=invalid_raw, anchor_patch=anchor_patch)
                else:
                    message = prompt.repair_message(shown, shown_issues, None)
            self.store.insert_step_input(step["id"], rid, run_id, attempt, payload, base, developer, message, schema, selection_revision)
            measured_chars = None
            if max_request_chars is not None:
                from deixis.workflow.review.run import request_chars
                measured_chars = request_chars(base, developer, message, schema, adapter.enforces_schema)
            if (max_message_chars is not None and len(message) > max_message_chars
                    or max_request_chars is not None and measured_chars > max_request_chars):
                # An oversized repair was never sent. Known-failed pairs keep the last sent
                # fingerprint; the blocked input remains stored separately for the size audit.
                output = {"invalid": True, "issues": [], "step_input_id": sent_input or payload["step_input_id"],
                          "message_too_large": True} | (sent_extra or extra)
                if attempt_record is not None:
                    output = {"invalid": True, "issues": [], "message_too_large": True} | sent_output()["output"]
                    output["blocked_step_input_id"] = payload["step_input_id"]
                    output["blocked_send_record"] = extra
                if max_request_chars is not None:
                    output["request_chars"] = measured_chars
                    output["size_failure_reason"] = "repair_message_too_large" if repair_issues is not None else "message_too_large"
                self.store.finish_step(step["id"], "failed", output=output, error_code="message_too_large",
                                       error=repair_issues)
                return output
            if attempt_record is not None:
                # A crash before session start leaves a prepared record, without replacing
                # the last sent attempt. Recovery selects only session-backed records.
                attempt_records[payload["step_input_id"]] = extra
                self.store.set_step_output(step["id"], sent_output()["output"])
            sent_extra, sent_input = extra, payload["step_input_id"]
            step_attempt = self.store.conn.execute("SELECT attempt FROM run_steps WHERE id = ?", (step["id"],)).fetchone()[0]
            reserved.discard(operation_key)
            try:
                session, result = await self._call_adapter(
                    run_id, rid, step["id"], payload["step_input_id"], connection, requested_model, adapter, base,
                    developer, message, schema, reasoning_effort, limiter,
                    unchanged if recheck is not None or resend_guard is not None else None,
                )
            except _ReadCutoff:
                return cut_before_send()
            if session is None:
                continue  # rate-limited, and a work of this input was decided since: the next attempt is built anew
            if not self._model_result_checkpoint(session, result, run_id, rid, step["id"], payload["step_input_id"], step_attempt):
                raise RunStopped

            def complete(status: str, **fields: Any) -> None:
                # No other writer may supersede the attempt between the last checkpoint and publication.
                accepted = self.store.complete_model_step(session, recorded, step["id"], status,
                    accept=lambda: self._model_result_checkpoint(session, result, run_id, rid, step["id"], payload["step_input_id"], step_attempt),
                    **fields)
                if accepted is False:
                    raise RunStopped

            recorded: dict[str, Any] = {
                "status": result.status, "resolved_model": result.resolved_model, "external_thread_id": result.external_thread_id,
                "raw_output": result.raw_text, "token_usage_json": result.token_usage, "tool_item_types_json": result.tool_item_types,
            }
            if result.status == "cutoff":
                # Closed without a pause or a resend: the read window records the work as not read at its cutoff.
                complete("outcome_unknown" if result.delivery_class == "after_send_unknown" else "cancelled",
                         error_code="model_read_cutoff", error=result.error, delivery_class=result.delivery_class,
                         **sent_output())
                return {"cutoff": True}
            if result.status == "isolation_violation" or result.tool_item_types:
                complete("failed", error_code="model_isolation_violation",
                                               error={"tool_item_types": result.tool_item_types, "error": result.error}, **sent_output())
                halt("model_isolation_violation", {"tool_item_types": result.tool_item_types, "error": result.error})
            if result.status != "completed":
                final = "outcome_unknown" if result.delivery_class == "after_send_unknown" else "failed"
                complete(final, error_code=f"model_{result.status}",
                         error=result.error, delivery_class=result.delivery_class,
                         service_detail={"service_kind": result.error_kind, "connection": connection,
                                         "http_status": result.http_status, "reset_at": retry_at(result.retry_after)}, **sent_output())
                self._checkpoint(run_id)
                if (task_type in TIMEOUT_RETRIED_TASKS and not timeout_resent and turn_timed_out(result)
                        and self.store.run(run_id)["usage"].get("model_calls", 0) < run["budget"]["max_model_calls"]):
                    # The step stays closed as `outcome_unknown` with this attempt on it, and is opened again for
                    # one more send of the same input; a second timeout pauses the run as the first used to. With
                    # no call left in the budget the step is not opened again: the resend would only be closed as
                    # `budget_exhausted`, hiding that a call was sent whose outcome is unknown.
                    timeout_resent = True
                    self.store.start_step(step["id"])
                    continue
                halt("model_call_failed", {"status": result.status, "error": safe_error(result.error),
                     "error_kind": service_error_kind(result.error_kind or result.http_status,
                         text=result.error or result.delivery_class or "", surface="model"),
                     "http_status": result.http_status, "retry_after": result.retry_after if retry_at(result.retry_after) else None,
                     "reset_at": retry_at(result.retry_after), "connection": connection, "requested_model": requested_model})
            if not requested_model or (result.resolved_model != requested_model and not result.requested_model_verified):
                # Output from any model other than the one chosen for this step's role is recorded but never used.
                mismatch = {"requested_model": requested_model, "resolved_model": result.resolved_model}
                complete("failed", error_code="model_mismatch", error=mismatch,
                                               **sent_output())
                halt("model_mismatch", mismatch)
            output_text = result.raw_text or ""
            patch_record = None
            normalised_changes = []
            if anchor_patch:
                output_text = contracts.normalise_output(task_type, output_text)[0]
                output_text, stamps = contracts.stamp_step_input_id(task_type, payload, output_text)
                normalised_changes.extend(stamps)
                report = contracts.validate_report_section_anchor_patch(payload, patch_base, anchor_context, output_text)
                if report.ok:
                    output_text, patch_changes = contracts.apply_report_section_anchor_patch(
                        payload, patch_base, anchor_context, report.result)
                    patch_record = {"base_step_input_id": patch_base_input, "changes": patch_changes}
                    # Repair envelopes name the new attempt; evidence and rules remain those of the original section.
                    original_output = dict(output_text, step_input_id=failed_input["step_input_id"])
                    report = contracts.validate_model_output(failed_input, original_output)
                    if report.ok:
                        report.result = output_text
            elif task_type in ("grounded_answer", "cell_extraction", "abstract_screening", "fulltext_adjudication") + contracts.REPORT_TASKS + contracts.LINEAGE_TASKS + contracts.CANDIDATE_TASKS + contracts.REVIEW_TASKS:
                output_text = contracts.resolve_citation_handles(payload, output_text)
            # Field names from the alias table are put right before validation and the renames recorded (D86).
            if not anchor_patch:
                output_text, normalised_changes = contracts.normalise_output(task_type, output_text)
                output_text, stamps = contracts.stamp_package_hash(task_type, payload, output_text)
                normalised_changes.extend(stamps)
                output_text, stamps = contracts.stamp_step_input_id(task_type, payload, output_text)
                normalised_changes.extend(stamps)
                if resplit is not None:
                    # D259: parts of a split claim that kept the offending label get new labels; nothing else changes.
                    output_text, relabelled = contracts.relabel_split_claims(output_text, resplit["labels"])
                    split_relabel.clear()
                    split_relabel.update(relabelled)
                report = contracts.validate_model_output(payload, output_text)
                if task_type == "report_section" and repair_issues is not None:
                    report.issues.extend(contracts.report_section_repair_issues(patch_base, output_text))
            salvage: list[contracts.Issue] = []
            if not report.ok and task_type == "grounded_answer" and isinstance(output_text, dict):
                # D244: preserve links and claims while a repair can still fix their quotes.
                salvaged, salvage = contracts.salvage_answer_draft(payload, output_text)
                if repairs < max_repairs and any(w.dropped != "anchor" for w in salvage):
                    salvage = []
                retry = contracts.validate_model_output(payload, salvaged) if salvage else report
                if retry.ok:
                    report = retry
                else:
                    salvage = []
            warnings = [vars(w) for w in salvage + report.warnings]
            recorded["validation_json"] = {"ok": report.ok, "issues": [vars(i) for i in report.issues], "warnings": warnings,
                                         "normalised": normalised_changes}
            if patch_record is not None:
                recorded["validation_json"]["anchor_patch"] = patch_record
            if split_relabel:
                recorded["validation_json"]["relabelled"] = dict(split_relabel)
            if report.ok:
                if task_type == "grounded_answer":
                    report.result = contracts.name_sources_in_prose(payload, report.result)
                output = {"output_type": report.output_type, "result": report.result,
                          "step_input_id": payload["step_input_id"], "resolved_model": result.resolved_model, "warnings": warnings}
                if patch_record is not None:
                    output["anchor_patch"] = patch_record
                if extra:
                    output = output | extra
                if attempt_record is not None:
                    output = output | sent_output()["output"]
                output = output | resplit_meta("published")
                complete("succeeded", output=output)
                return output
            repair_issues = [vars(i) for i in report.issues]
            if anchor_patch:
                repair_issues = first_anchor_issues + repair_issues
            invalid_raw, invalid_input = result.raw_text, payload["step_input_id"]
            if after_invalid_output(repairs, max_repairs) == "store_unverified_draft":
                provenance = (sent_output()["output"] if attempt_record is not None else {"step_input_id": payload["step_input_id"]}
                              ) | resplit_meta("rejected")
                complete("failed",
                                               output=provenance,
                                               error_code="invalid_model_output", error=repair_issues)
                return {"invalid": True, "raw_output": result.raw_text, "issues": repair_issues,
                        "step_input_id": payload["step_input_id"]} | (provenance if attempt_record else {})
            repairs += 1
            accepted = self.store.finish_model_session(session,
                accept=lambda: self._model_result_checkpoint(session, result, run_id, rid, step["id"], payload["step_input_id"], step_attempt),
                **recorded)
            if accepted is False:
                raise RunStopped
