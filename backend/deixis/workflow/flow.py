"""Execution of discovery and answer runs.

Discovery: search plan (model) → compiled provider queries → provider searches → screening proposal (model).
Answer: fetch accessible PDFs for included sources → text retrieval → grounded answer (model)
→ claim review (reviewer model, when one is set).
The literature model runs the search plan and screening; the research model writes the answer.
Completed steps are skipped on resume. A connection or provider failure is recorded
with its reason; discovery continues when another provider search succeeds, and nothing is silently substituted. A review failure is recorded
on the review and does not pause the run: the answer never depends on its review.
"""

from __future__ import annotations

import asyncio
import hashlib
import json
import math
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
                                 PROVIDER_WAIT, SCREENING_BATCH, SEARCH_PARALLEL_HOSTS, SW_READ_LIMIT,
                                 after_invalid_output, effective_reviewer, schema_repairs, step_model)
from deixis.domain.skill import RUNTIME_FILES, SkillPackage
from deixis.domain.vocabulary import Extraction
from deixis.models import prompt
from deixis.models.adapter import ModelAdapter, ModelStepResult, is_rate_limited
from deixis.providers import openalex, query_compiler
from deixis.providers.common import FIRST_PAGE, MAX_RATE_LIMIT_RETRIES, SearchOutcome, normalize_doi
from deixis.providers.registry import CONNECTORS, Connector, endpoint_options, reading, search_providers
from deixis.storage.db import dumps, new_id, now, transaction
from deixis.workflow.concurrency import ModelCallLimiter
from deixis.workflow import abstract_stage
from deixis.workflow import adjudication
from deixis.workflow import approval as approval_rules
from deixis.workflow import chaining
from deixis.workflow import criterion as criterion_rules
from deixis.workflow import criterion_passages
from deixis.workflow import expansion as expansion_rules
from deixis.workflow import fulltext
from deixis.workflow import lookups
from deixis.workflow import protocol
from deixis.workflow import ranking as ranking_rules
from deixis.workflow import routing as routing_rules
from deixis.workflow import search_query as search_query_rules
from deixis.workflow import suggestions as suggestion_rules
from deixis.workflow import vocabulary as vocabulary_rules
from deixis.workflow.decisions import DecisionStore, HumanDecisionStands
from deixis.workflow.equations import equation_state
from deixis.workflow.store import NotFound, RunInProgress, Store
from deixis.workflow.tables import MAX_COLUMNS_PER_CALL, MAX_FILL_SOURCES, TableStore, check_value

CAPABILITIES = {
    "supported_tasks": ["search_plan", "screening", "grounded_answer", "answer_review", "cell_extraction", "table_columns", "research_title"],
    # `abstract_screening` is deliberately not listed: adding it would change every stored StepInput, including a
    # `legacy` run's, and this field tells the model what the product can do, not which step it is running.
    "unsupported_tasks": ["synthesis", "candidate_development", "claim_check", "experiment"],
}
MAX_DOWNLOADS_PER_RUN = 8
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
                "fulltext_adjudication")
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
    per_page = 1 + PROVIDER_WAIT[effort] + MAX_TRANSIENT_NETWORK_RETRIES
    connector = reading(query)  # the endpoint the query names pages its own way (D93)
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


@dataclass
class _QueryRead:
    """What one sw query read in this round, in page order, and whether its read has ended (D89)."""

    index: int
    query: dict[str, Any]
    pages: list[_PageRead] = field(default_factory=list)
    allowance_ended: str | None = None  # the step key of a page not asked because the query's share was spent
    ended: bool = False


def _stop_reason(connector: Connector, outcome: SearchOutcome, ok: bool, read_total: int, read_limit: int) -> str | None:
    """Why this page ends the query's read, or None while another page follows."""
    if not ok:
        return "page_failed"
    if connector.paging == "single_page":
        return "single_page"
    if outcome.next_cursor is None or not outcome.records:
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
class FlowDeps:
    settings: Settings
    store: Store
    adapters: dict[str, ModelAdapter]
    package: SkillPackage
    http: httpx.AsyncClient
    fetch_pdf: Callable[[str], Awaitable[fetch_module.FetchResult]] = fetch_module.fetch_pdf
    equations: Any = None  # workflow.equations.EquationService when the equation reader is set up (D52)
    limiter: ModelCallLimiter = field(default_factory=lambda: ModelCallLimiter(1))


class ResearchFlow:
    def __init__(self, deps: FlowDeps):
        self.deps = deps
        self.store = deps.store

    async def execute(self, run_id: str) -> None:
        run = self.store.run(run_id)
        scope = self.store.scope(run["research_id"], run["scope_revision"])
        try:
            if run["kind"] == "discovery":
                await self._discovery(run, scope)
            elif run["kind"] == "answer":
                await self._answer(run, scope)
            elif run["kind"] == "pdf_collection":
                await self._inspect(run, limit=None)
            elif run["kind"] == "fulltext_fetch":
                await self._fulltext_fetch(run, scope)
            elif run["kind"] == "fulltext_adjudication":
                await self._fulltext_adjudication(run, scope)
            elif run["kind"] == "pdf_ocr":
                await self._pdf_ocr(run)
            elif run["kind"] == "table_fill":
                await self._table_fill(run, scope)
            elif run["kind"] == "cell_recheck":
                await self._cell_recheck(run, scope)
            elif run["kind"] == "research_title":
                await self._research_title(run, scope)
            elif run["kind"] == "report":
                await self._report(run, scope)
            else:
                await self._table_columns(run, scope)
        except RunStopped:
            return
        if self.store.run(run_id)["status"] in ("running", "pause_requested"):
            # Nothing is left to pause once the last step's result has been applied.
            self.store.update_run(run_id, event="run_completed", status="completed", pause_reason=None)
            if run["kind"] == "discovery":
                # An sw discovery run is followed by the retrieval of the open full text of the works it ranked
                # (D83). Nothing is queued for a `legacy` research, for a run that did not complete, or when the
                # setting is off.
                self._queue_fulltext_fetch(run, scope)
            elif run["kind"] == "fulltext_fetch":
                # The reading run is queued in this same turn, with no await between the two (D85).
                self._queue_fulltext_adjudication(run, scope)

    # ---- run control ---------------------------------------------------------------
    def _checkpoint(self, run_id: str, scope_revision: int | None = None) -> None:
        run = self.store.run(run_id)
        if run["status"] == "pause_requested":
            self.store.update_run(run_id, event="run_paused", status="paused", pause_reason="user_requested")
            raise RunStopped
        if run["status"] == "cancelled":
            raise RunStopped
        if scope_revision is not None and self.store.research(run["research_id"])["current_scope_revision"] != scope_revision:
            # Results of an older question revision stay recorded under this run but are not applied.
            self.store.update_run(run_id, event="run_cancelled", status="cancelled", pause_reason="scope_revised")
            raise RunStopped

    def _pause(self, run_id: str, reason: str, detail: Any = None) -> None:
        if self.store.run(run_id)["status"] == "cancelled":
            raise RunStopped
        self.store.update_run(run_id, event="run_paused", status="paused", pause_reason=reason, error_json=detail)
        raise RunStopped

    def _fail(self, run_id: str, reason: str, detail: Any = None) -> None:
        self.store.update_run(run_id, event="run_failed", status="failed", pause_reason=reason, error_json=detail)
        raise RunStopped

    # ---- discovery -----------------------------------------------------------------
    async def _discovery(self, run: dict[str, Any], scope: dict[str, Any]) -> None:
        run_id, rid, revision = run["id"], run["research_id"], run["scope_revision"]
        if scope["source_scope"] == "attached":
            return
        self._checkpoint(run_id, revision)
        seed = scope["seed_snapshot"]
        if scope["seed_mode"] == "uploaded_seed" and self.store.seed_status(rid, scope) != "ready":
            self._pause(run_id, "seed_unavailable")
        budget = run["budget"]
        plan = vocabulary = criterion = approval = None
        if scope.get("search_workflow") == "sw":
            # The sw workflow takes the first search's words from the question by code, so no model runs before the
            # search and a broken model connection does not stop it (SW2.3). Screening still goes to the model.
            vocabulary, queries = await self._vocabulary(run, scope)
            # A model writes the query from the question and the code's query is searched beside it (D92). With the
            # setting on `code`, or with the user's own key terms, the code's query stands alone as it did in 13g.
            vocabulary, queries = await self._search_query(run, scope, vocabulary, queries)
            # Which domain sources are searched is read from the field distribution of the gate query, and the
            # queries are compiled for those sources alone, before the user sees them (D93).
            vocabulary, queries = await self._source_routing(run, scope, vocabulary, queries)
            # The criterion is proposed before the protocol is frozen, so the body this research searches under
            # already carries it. It orders nothing and decides nothing yet (SW15.4 is slice 11).
            criterion = await self._criterion(run, scope, vocabulary)
            # Nothing above has left this machine except count probes. The user sees what would be searched and
            # under which criterion, corrects it, and only then is the protocol frozen and a search sent (SW2.6).
            vocabulary, queries, criterion, approval = await self._approval(run, scope, vocabulary, queries, criterion)
        else:
            output = await self._model_step(run, scope, "search_plan", "search_plan",
                                            source_ids=[seed["source_version_id"]] if seed else None,
                                            passage_rows=seed["passages"] if seed else None)
            self._checkpoint(run_id, revision)
            if output.get("invalid"):
                self._fail(run_id, "invalid_model_output", {"step": "search_plan", "issues": output["issues"]})
            if output["output_type"] == "ClarificationRequest":
                self.store.save_answer(rid, run_id, None, output["step_input_id"], revision, "clarification",
                                       output["result"], {"ok": True, "issues": []})
                return
            plan = output["result"]
            if "queries" in plan:  # a SearchPlan v1 from before D44 carries the queries the model wrote
                queries = [q for q in plan["queries"] if q["provider_id"] in scope["providers"]][: budget["max_provider_requests"]]
            elif "queries" in output:
                queries = output["queries"]
            else:
                # Compiled once and stored with the plan, so a resumed run searches the same queries even after a compiler change.
                queries = query_compiler.compile_queries(plan, scope["providers"], budget["max_provider_requests"],
                                                       budget.get("core_depth", 0), self.deps.settings.query_strategy)
                self.store.set_step_output(self.store.step(run_id, "search_plan", "model:search_plan")["id"],
                                           output | {"queries": queries, "query_compiler": (
                                               query_compiler.COMPACT_VERSION if self.deps.settings.query_strategy == "compact_openalex_v1"
                                               else query_compiler.VERSION)})
        # The protocol is frozen before the first provider request and every step opened after it carries its hash (SW14.1).
        protocol_step = self.store.step(run_id, "protocol", "protocol:freeze")
        if protocol_step["status"] != "succeeded":
            self.store.start_step(protocol_step["id"])
            # A later discovery run of the same scope revision may plan other queries; that is a new protocol revision
            # with its reason, never an edit of the first one (SW14.2).
            reason = "later_discovery_run" if self.store.current_protocol(rid, revision) else None
            record = self.store.freeze_protocol(rid, revision, protocol.build_protocol(
                scope, budget, plan if plan and plan.get("concepts") else None, queries,
                self.deps.package.package_hash, self.deps.settings, vocabulary=vocabulary, criterion=criterion,
                approval=approval, embedding_model=self._embedding_model(), routing=self._routing(run_id),
            ), reason=reason)
            self.store.finish_step(protocol_step["id"], "succeeded",
                                   output={"protocol_revision": record["protocol_revision"], "protocol_hash": record["hash"]})

        # Runs created before results_per_query existed split the candidate limit across their queries.
        per_query = budget.get("results_per_query") or max(5, min(25, budget["max_candidates"] // max(1, len(queries))))
        # A failed search is recorded and shown, and the other searches go on (D18). The run pauses on a failure only when
        # none of its searches succeeded; resuming it then retries the failed searches.
        def searched() -> bool:
            return any(s["kind"].startswith("provider_search") and s["status"] == "succeeded" for s in self.store.run_steps(run_id))

        # A deliberate retry action reuses the stored plan and retries only failed provider searches. A normal resume
        # retries failures only when the whole search stage had no successful query (D18).
        retry_failed = bool(run["budget"].get("retry_failed_searches_only")) or not searched()
        failure = None
        # An sw query is read page by page up to this effort's read limit; a legacy query reads its one page as it always has.
        effort = scope["effort"]
        if scope.get("search_workflow") == "sw":
            self._checkpoint(run_id, revision)
            failure = await self._search_round(run, list(enumerate(queries)), retry_failed, effort)
        else:
            for index, query in enumerate(queries):
                self._checkpoint(run_id, revision)
                if self._skip_unsearchable(run, index, query):
                    continue
                failure = await self._search(run, index, query, per_query, retry_failed) or failure
        if failure and not searched():
            self._pause(run_id, *failure)
        if not searched() and self._allowance_ended_searches(run_id):
            # No search succeeded and none failed: every query's share was spent before it asked (a run resumed after
            # a crash). Going on would screen a round that searched nothing (D18); asked to search again, the retry
            # adds to every query's share (review of 13f, 2026-09-23).
            self._pause(run_id, "budget_exhausted", {"limit": "query_requests"})
        if scope.get("search_workflow") == "sw":
            # A second arm that only adds: phrases the first round's own records offered, each kept by a count
            # probe (SW2.4). The first round's query is not sent again.
            more = await self._expansion(run, scope, vocabulary, queries, criterion, approval)
            # A failed second-round search is recorded and left there: this run already has a search that succeeded,
            # so nothing here can pause it (D18). The round starts only once the first is written: the expansion
            # read the first round's records.
            await self._search_round(run, list(enumerate(more, start=len(queries))), retry_failed, effort)

        if scope.get("search_workflow") == "sw":
            # Both rounds are done and nothing here feeds the search: a second source is asked for the abstracts
            # that are missing, the links it names are read, and the survey labels are written (slice 05).
            await self._second_sources(run, scope, vocabulary)

        self._checkpoint(run_id, revision)
        # A work is screened once, through its head; its other versions follow the head's selection (D46, D48).
        heads = set(self.store.work_heads(rid).values())
        pool = [c for c in self.store.candidates(rid, revision)
                if c["origin"] != "user" and c["source_version_id"] in heads]
        if scope.get("search_workflow") == "sw":
            # The whole pool is embedded and then ranked before screening reads anything (SW7, SW8, slice 07). The
            # records slice 05 holds back are ranked too; only the read plan leaves them out.
            await self._source_similarity(run, scope, pool)
            order = await self._ranking(run, scope, vocabulary)
            self.store.update_run(run_id, stage="screening")
            # Slice 09: code classifies every record and the model is asked, twice, only about the works code left
            # open and the read limit reaches. Nothing is included from an abstract and `max_candidates` does not
            # cut here any more: what the model does not read stays `abstract_not_read` for the next run.
            await self._abstract_stage(run, scope, vocabulary, order)
            # Citation chaining, after the keyword works were read and never before (D95). A run queued before D95,
            # or with the setting off, has no chain in its budget and sends nothing here.
            if chaining.enabled(budget):
                await self._chaining(run, scope, vocabulary)
        else:
            self.store.update_run(run_id, stage="screening")
            # A record an earlier run screened goes last, as it does in the candidate order. One this run screened
            # keeps its place: a batch is keyed by where it starts, so a run resumed between two batches must find
            # the same list, or the places the first batch held are read again and the next ones never are.
            own = {s["id"] for s in self.store.run_steps(run_id)}

            def earlier(c: dict[str, Any]) -> bool:
                return bool(c["proposed"]) and c["proposal_step_id"] not in own

            # The candidate order itself, with this run's own proposals left where they were.
            screenable = sorted(pool, key=lambda c: (earlier(c), c["rank"] is not None, c["rank"] or 0, c["created_at"]))
            candidates = screenable[: budget["max_candidates"]]
            # Map through all candidates: a resumed run may apply a proposal made for an earlier candidate list.
            by_candidate = {c["candidate_id"]: c["source_version_id"] for c in self.store.candidates(rid)}
            for start in range(0, len(candidates), SCREENING_BATCH):
                # The first batch keeps the single-call key so a run from before batching resumes without screening again.
                key = "screening" if start == 0 else f"screening:{start // SCREENING_BATCH}"
                output = await self._model_step(run, scope, key, "screening", candidate_rows=candidates[start:start + SCREENING_BATCH])
                self._checkpoint(run_id, revision)
                if output.get("invalid"):
                    self._fail(run_id, "invalid_model_output", {"step": key, "issues": output["issues"]})
                step = self.store.step(run_id, key, "model:screening")
                for decision in output["result"]["decisions"]:
                    self.store.apply_screening_proposal(
                        rid, by_candidate[decision["candidate_id"]], decision["proposal"], decision["reason"],
                        decision["evidence_basis"], step["id"],
                    )
            # An sw run scored the whole pool before it ranked it; a legacy run scores its screened candidates here,
            # exactly where it always did.
            await self._source_similarity(run, scope, candidates)

        # Derive a short title from the question and the included sources once screening is done. A structurally valid
        # answer later replaces it (store.save_answer). Optional: the run continues with the provisional title on failure.
        if self.store.included_works(rid):
            try:
                await self._research_title(run, scope, optional=True)
            except OptionalStepFailed:
                return

    async def _second_sources(self, run: dict[str, Any], scope: dict[str, Any],
                              vocabulary: dict[str, Any] | None) -> None:
        """The three code steps of slice 05 (SW5, SW9.3).

        No model is called and no selection is written here. A failed lookup is recorded on the record and the run
        carries on (D18); a resumed run reads the stored plan and asks nothing twice. Which records stay away from
        the model is no longer read here: since slice 09 the abstract stage's own read plan decides that, and
        `lookups.held_from_screening` is what `record_flags` counts with.
        """
        run_id, revision = run["id"], run["scope_revision"]
        words, _ = lookups.title_words(vocabulary)
        await lookups.ask_second_sources(self.store, self.deps.http, self.deps.settings, run, scope, words,
                                         lambda: self._checkpoint(run_id, revision))
        lookups.external_links(self.store, run)
        lookups.flag_and_decide(self.store, run, scope, words)

    def _count_probe(self, scope: dict[str, Any]) -> Callable[[str], Awaitable[int | None]]:
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
        built = await vocabulary_rules.build_vocabulary(extraction, self._count_probe(scope))
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
                checked = await search_query_rules.check(answer["result"], self._count_probe(scope))
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
        if self.deps.settings.protocol_approval == "ask":
            return built, queries
        return self._searchable(run_id, built, queries)

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
        for index in range(vocabulary_rules.LABEL_RUNS):
            self._checkpoint(run_id, revision)  # a pause or cancel is honoured between the calls, not only after them
            key = f"vocabulary_labels_{index + 1}"
            try:
                output = await self._model_step(run, scope, key, "vocabulary_labels", optional=True, vocabulary_target=target)
            except OptionalStepFailed as failure:
                failures.append({"step": key, "reason": failure.reason})
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
            for index in range(criterion_rules.PROPOSAL_RUNS):
                self._checkpoint(run_id, revision)  # a pause or cancel is honoured between the calls
                key = f"criterion_proposal_{index + 1}"
                try:
                    proposal = await self._model_step(run, scope, key, "criterion_proposal", optional=True)
                except OptionalStepFailed as failure:
                    failures.append({"step": key, "reason": failure.reason})
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
        if step["status"] == "succeeded":
            approved = step["output"]["approved"]
            return (search_query_rules.settled(approved["vocabulary"], approved["queries"]), approved["queries"],
                    approved["criterion"], step["output"]["approval"])
        asked_for = {"question": scope["question"], "steering": scope.get("steering"),
                     "key_terms": scope.get("key_terms")}
        # The newest approval this research closed for the same question, steering and key terms. It is both what a
        # correction is reapplied from and what a re-asked card takes its suggestions back from.
        earlier = next((row for row in self.store.approvals_of(rid)
                        if row["output"]["asked_for"] == asked_for), None)
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
        if criterion is not None and proposed_now:
            earlier = None
        if output["submitted"] is not None:
            edits, source, by = output["submitted"], "submitted", "user"
        elif earlier is not None:
            # Only the term operations are reapplied. The criterion this run holds already came back from the
            # protocol the earlier approval froze, so correcting it a second time would rewrite what was agreed.
            done = earlier["output"]["edits"]
            edits, source, by = ({"terms": done["terms"], "criterion": None, "note": done.get("note"),
                                  "code_query": done.get("code_query")}, "earlier", "earlier_approval")
        elif self.deps.settings.protocol_approval == "as_proposed":
            # A run nobody attends: the proposal is approved as it stands and the protocol says so by name, so a body
            # approved by a setting is never read as a body a user approved.
            edits, source, by = {"terms": [], "criterion": None, "note": None}, "setting", "setting"
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
            "mode": self.deps.settings.protocol_approval, "approved_by": by,
            "edited": bool(kept or edits.get("criterion") or code_off),
            "proposal_hash": output["proposal_hash"], "term_edits": len(kept),
            "criterion_edited": edits.get("criterion") is not None,
            "exclusion_word_in_question": approval_rules.exclusion_words_in_question(scope["question"], agreed),
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
        probe = self._count_probe(scope)
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
                self._count_probe(scope), suggestion_rules.model_phrases(proposals or []))
            built, compiled = self._compiled(built, providers, run["budget"], routed=routed)
            return built, compiled, built["user_edits"], skipped
        if not kept:
            return vocabulary, queries, [], skipped
        proposals = proposals or []
        extraction = approval_rules.edited_extraction(
            vocabulary, kept, model_phrases=suggestion_rules.model_phrases(proposals))
        built = await vocabulary_rules.build_vocabulary(
            extraction, self._count_probe(scope),
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
        output = ranking_rules.rank_records(self.store, run, scope, vocabulary, terms, self._embedding_model())
        self.store.finish_step(step["id"], "succeeded", output=output)
        return decisions.ranking_order(step["id"])

    # ---- the abstract stage of an sw run (slice 09, SW9, SW1, SW11) ----------------------
    async def _abstract_stage(self, run: dict[str, Any], scope: dict[str, Any], vocabulary: dict[str, Any],
                              order: list[str], chain: list[str] | None = None) -> None:
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
        plan = self._abstract_code_stage(run, scope, vocabulary, order, chain)
        batches, runs = plan["batches"], plan["runs"]
        by_svid = {c["source_version_id"]: c for c in self.store.candidates(run["research_id"])}
        spent_before = self.store.run(run_id)["usage"].get("model_calls", 0)
        unread: list[str] = []
        submitted = 0
        collected: dict[int, dict[int, dict[str, Any] | None]] = {}
        rows_of: dict[int, list[dict[str, Any]]] = {}
        closed: set[int] = set()

        # Read, not opened: a batch the budget never reaches must not be left with a pending step of its own.
        answered = {s["operation_key"] for s in self.store.run_steps(run_id)
                    if s["kind"] == "model:abstract_screening"
                    and (s["status"] == "succeeded" or s["error_code"] == "invalid_model_output")}

        def jobs() -> Iterator[_AbstractJob]:
            """The (batch, run) calls in plan order, up to the batch the budget no longer holds whole."""
            nonlocal submitted
            for number, batch in enumerate(batches):
                # A call whose step is already stored is read back and costs nothing, so a resumed run charges the
                # budget only for the calls it still has to make; counting the stored ones too left paid-for
                # answers unused and later batches unread while the budget still held them.
                owed = [run_no for run_no in range(1, runs + 1)
                        if f"{prefix}:{number}:{run_no}" not in answered]
                if owed and not self._model_calls_left(run, len(owed), submitted, spent_before):
                    # The budget stopped short of this batch. Its records are unread, which is a state the workflow
                    # already has, so the run finishes rather than pausing on something a later run will pick up.
                    unread.extend(svid for later in batches[number:] for svid in later)
                    return
                rows_of[number] = [by_svid[svid] for svid in batch if svid in by_svid]
                for run_no in range(1, runs + 1):
                    submitted += run_no in owed
                    yield _AbstractJob(f"{prefix}:{number}:{run_no}", number, run_no, rows_of[number])

        async def call(job: _AbstractJob) -> dict[str, Any] | None:
            return await self._abstract_call(run, scope, job.number, job.run_no, job.rows, self.deps.limiter, prefix)

        def close_ready(completed: list[tuple[dict[str, Any] | None, _AbstractJob]]) -> None:
            """Close every batch both of whose runs have come back, on the event loop, one short transaction each."""
            for output, job in completed:
                collected.setdefault(job.number, {})[job.run_no] = output
            for number in sorted(collected):
                if number in closed or len(collected[number]) < runs:
                    continue
                self._checkpoint(run_id, revision)
                closed.add(number)
                self._close_abstract_batch(run, number, rows_of[number],
                                           [collected[number][run_no] for run_no in range(1, runs + 1)], runs, prefix)

        stop = await self._send_through_limiter(run, jobs(), call, close_ready)
        if unread and stop is None:
            key = "chain_abstract_stage" if chain is not None else "abstract_stage"
            step_id = self.store.step(run_id, key, f"code:{key}")["id"]
            self._write_abstract_codes(run, step_id, [(svid, "abstract_not_read") for svid in unread])
        if stop is not None:
            raise stop

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

    async def _abstract_call(self, run: dict[str, Any], scope: dict[str, Any], number: int, run_no: int,
                             rows: list[dict[str, Any]], limiter: ModelCallLimiter | None = None,
                             prefix: str = "abstract_screening") -> dict[str, Any] | None:
        """One run of one batch; None when the model's output did not validate.

        An invalid output does not stop the run and is not repaired: its records stay `abstract_not_proposed` and
        a later discovery run reads them. A resumed run does not call the step again either (the guard
        `_extraction` uses), so an unusable answer is paid for once.
        """
        key = f"{prefix}:{number}:{run_no}"
        step = self.store.step(run["id"], key, "model:abstract_screening")
        if step["status"] == "failed" and step["error_code"] == "invalid_model_output":
            return None
        output = await self._model_step(run, scope, key, "abstract_screening", candidate_rows=rows,
                                        screening_target={"runs": ABSTRACT_RUNS, "run": run_no}, limiter=limiter,
                                        budget_short="skip")
        return None if output.get("invalid") else output

    def _abstract_code_stage(self, run: dict[str, Any], scope: dict[str, Any], vocabulary: dict[str, Any],
                             order: list[str], chain: list[str] | None = None) -> dict[str, Any]:
        """Write what code decides about every record, then freeze the read plan in this step's output.

        With `chain`, only the chained works are classified and planned, with the chain's own read limit (D95).
        """
        run_id, rid, revision = run["id"], run["research_id"], run["scope_revision"]
        key = "chain_abstract_stage" if chain is not None else "abstract_stage"
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
        chained = set(chain) if chain is not None else None
        for candidate in self.store.candidates(rid, revision):
            svid = candidate["source_version_id"]
            if candidate["origin"] == "user" or svid not in versions or heads.get(versions[svid]["work_id"]) != svid:
                continue
            if chained is not None and svid not in chained:
                continue
            rows = []
            for version in sorted(by_work[versions[svid]["work_id"]], key=lambda v: v["id"]):
                held = current.get(version["id"])
                record = dict(version, decision=held["reason_code"] if held else None)
                code = abstract_stage.code_outcome(record, blocks, links)
                stale = bool(held) and decisions.is_stale(held, stale_key)
                if code and (held is None or held["decided_by"] != "human") and abstract_stage.should_write(held, code, stale):
                    writes.append((version["id"], code))
                    held, stale = {"reason_code": code, "decided_by": "code"}, False
                rows.append({"id": version["id"], "has_abstract": bool(version["abstract"]), "code": code,
                             "decision": held["reason_code"] if held else None,
                             "decided_by": held["decided_by"] if held else None, "stale": stale})
            works.append({"work_id": versions[svid]["work_id"], "head": svid, "versions": rows})

        limit = (CHAIN_ABSTRACT_READ if chain is not None else ABSTRACT_READ_LIMIT)[scope["effort"]]
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
    async def _chaining(self, run: dict[str, Any], scope: dict[str, Any], vocabulary: dict[str, Any]) -> None:
        """Chain citations from the seeds the keyword ranking puts first, then read the new works on their own (D95).

        Runs after the keyword abstract stage, and only on a run whose budget froze the setting `auto`: the keyword
        ranking, its abstract read and the first three groups of the full-text plan are the same as without it. The
        seeds, the links, the chained works and their read plan are frozen in step outputs and rows, so a resumed run
        reads them back and asks OpenAlex nothing it already asked. A failed chain request is recorded and the others
        go on (D18), and reaching the chain's own request limit ends the chain, never the run.
        """
        run_id, revision = run["id"], run["scope_revision"]
        self._checkpoint(run_id, revision)
        forms = self._chain_forms(run, scope, vocabulary)
        seeds = self._chain_seeds(run, scope)
        await self._chain_requests(run, scope, seeds, forms)
        self._checkpoint(run_id, revision)
        chained = self._chain_filter(run)
        order = self._chain_ranking(run, scope, vocabulary, chained)
        if chained:
            works = set(self.store.work_ids(chained).values())
            words, _ = lookups.title_words(vocabulary)
            lookups.flag_and_decide(self.store, run, scope, words, works=works, key="chain_record_flags")
            await self._abstract_stage(run, scope, vocabulary, order, chain=chained)
        self._chain_summary(run)

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
                                                 of, cites=work_id, cursor=cursor, page=page)
                if done is None:
                    break
                cursor, read, page = done.get("next_cursor"), read + done.get("returned", 0), page + 1

    async def _chain_request(self, run: dict[str, Any], scope: dict[str, Any], key: str, direction: str,
                             forms: dict[str, list[str]], links: list[Any], *, batch: list[str] | None = None,
                             cites: str | None = None, cursor: str | None = None,
                             page: int | None = None) -> dict[str, Any] | None:
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
        if not self._chain_requests_left(run):
            return None  # counted `not_reached` by the summary
        self.store.start_step(step["id"])
        connector = CONNECTORS["openalex"]
        retries = PROVIDER_WAIT[scope["effort"]]
        attempts = 0
        while True:
            self.store.add_usage(run_id, "chain_requests")
            async with fetch_module.host_gate(openalex.WORKS_URL):
                if cites is not None:
                    outcome = await openalex.citing_works(self.deps.http, cites, cursor or FIRST_PAGE, CHAIN_CITING_PAGE,
                                                          connector.api_key(), self.deps.settings.contact_email, retries)
                else:
                    outcome = await openalex.works_by_ids(self.deps.http, batch or [], connector.api_key(),
                                                          self.deps.settings.contact_email, retries)
            if outcome.retries:
                self.store.add_usage(run_id, "chain_requests", outcome.retries)
            if (outcome.status == "failed" and outcome.delivery_class == "before_send"
                    and attempts < MAX_TRANSIENT_NETWORK_RETRIES and self._chain_requests_left(run)):
                attempts += 1
                await asyncio.sleep(1.5 * attempts)
                continue
            break
        self._record_chain(run, step, key, direction, outcome, forms, links, cites=cites, page=page)
        return self.store.step(run_id, key, chaining.STEP_KIND)["output"] if outcome.status in ("completed", "zero_results") else None

    def _record_chain(self, run: dict[str, Any], step: dict[str, Any], key: str, direction: str, outcome: SearchOutcome,
                      forms: dict[str, list[str]], links: list[Any], *, cites: str | None, page: int | None) -> None:
        """Write one answered chain request: the filter runs first, and only the records that pass are written, as a
        search writes them (normalised, merged by DOI, linked, a candidate with its hit). Every link is kept, passing
        or not, in `chain_links`."""
        run_id, rid, revision = run["id"], run["research_id"], run["scope_revision"]
        settings = self.deps.settings
        payload_path = payload_digest = None
        if outcome.raw_payload is not None:
            settings.payloads_dir.mkdir(parents=True, exist_ok=True)
            payload_path = f"{step['id']}.json"
            (settings.payloads_dir / payload_path).write_text(json.dumps(outcome.raw_payload), encoding="utf-8")
            payload_digest = canonical.sha256_hex(outcome.raw_payload)
        passed = [record for record in outcome.records if chaining.passes(forms, record.title, record.abstract)]
        ok = outcome.status in ("completed", "zero_results")
        search_fields = dict(
            research_id=rid, run_id=run_id, step_id=step["id"], scope_revision=revision, provider="openalex",
            query_text=key.rpartition(":")[0] if cites is not None else key,
            request_description=f"citation chaining, {direction}: {outcome.request_description}",
            access_mode=outcome.access_mode, status=outcome.status, delivery_class=outcome.delivery_class,
            result_count=len(passed), provider_total=outcome.provider_total, page_limit=CHAIN_CITING_PAGE,
            error_json=dumps({"error": outcome.error, "http_status": outcome.http_status, "rate_limit": outcome.rate_limit,
                              "returned": len(outcome.records), "passed_filter": len(passed)}),
            raw_payload_path=payload_path, payload_sha256=payload_digest,
            **({"page_number": page} if page is not None else {}),
        )
        output = {"status": outcome.status, "direction": direction, "returned": len(outcome.records),
                  "passed_filter": len(passed), "next_cursor": outcome.next_cursor if cites is not None else None,
                  "provider_total": outcome.provider_total}
        with transaction(self.store.conn):
            if ok:
                # A chained record ranks after every keyword record: a record a keyword query already found keeps the
                # rank and the search its candidate row names, and only gains a hit (D93's `candidate_hits`).
                self.store.record_search(search_fields, "openalex", passed, payload_path, step["id"], "succeeded",
                                         step_output=output, first_rank=CHAIN_RANK_BASE)
            else:
                final = "outcome_unknown" if outcome.delivery_class == "after_send_unknown" else "failed"
                self.store.record_search(search_fields, "openalex", [], payload_path, step["id"], final,
                                         error_code=outcome.status,
                                         error={"error": outcome.error, "http_status": outcome.http_status},
                                         delivery_class=outcome.delivery_class)
                return
            became = {record.provider_record_id: self.store.find_source_by_identifier("openalex", record.provider_record_id)
                      for record in passed}
            returned = {record.provider_record_id for record in outcome.records}
            pairs = ([(seed, linked) for seed, linked in links if linked in returned] if direction == "backward"
                     else [(seed, linked) for seed in links for linked in sorted(returned)])
            self.store.conn.executemany(
                "INSERT OR IGNORE INTO chain_links (research_id, scope_revision, run_id, seed_source_version_id,"
                " linked_openalex_id, direction, passed_filter, source_version_id) VALUES (?, ?, ?, ?, ?, ?, ?, ?)",
                [(rid, revision, run_id, seed, linked, direction, int(linked in became), became.get(linked))
                 for seed, linked in pairs])

    def _chain_filter(self, run: dict[str, Any]) -> list[str]:
        """Freeze the chained works: the heads of the records that passed, after the record path merged them, that
        the keyword pool does not hold (slice 15, Task 3.5)."""
        run_id, rid = run["id"], run["research_id"]
        step = self.store.step(run_id, "chain_filter", "code:chain_filter")
        if step["status"] == "succeeded":
            return step["output"]["chained"]
        self.store.start_step(step["id"])
        linked = [dict(row) for row in self.store.conn.execute(
            "SELECT linked_openalex_id, direction, passed_filter, source_version_id FROM chain_links WHERE run_id = ?",
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
        output = {"chained": chained,
                  "links": {direction: sum(row["direction"] == direction for row in linked)
                            for direction in chaining.DIRECTIONS},
                  "linked_works": len({row["linked_openalex_id"] for row in linked}),
                  "passed_filter": len({row["linked_openalex_id"] for row in linked if row["passed_filter"]}),
                  "failed_filter": len({row["linked_openalex_id"] for row in linked if not row["passed_filter"]}),
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
        model = self._embedding_model()
        similarities = self.store.source_similarities(rid, revision, model) if model else {}
        ranked = ranking_rules.rank_pool(pool, verified, query_words, blocks, model, similarities)
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
        sent = [s for s in steps if s["status"] != "pending"]
        forward_seeds = {work_id for seed in seeds.get("seeds") or [] for work_id in seed["openalex_ids"]}
        reached = {s["operation_key"].split(":")[2] for s in sent if s["operation_key"].startswith("chain:forward:")}
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
                         "failed": sum(s["status"] in ("failed", "outcome_unknown") for s in sent),
                         "sent": self.store.run(run_id)["usage"].get("chain_requests", 0),
                         "limit": run["budget"].get("max_chain_requests"),
                         "not_reached_batches": len(seeds.get("backward_batches") or [])
                         - sum(s["operation_key"].startswith("chain:backward:") for s in sent),
                         "not_reached_seeds": len(forward_seeds - reached)},
            "links": filtered.get("links") or {}, "passed_filter": filtered.get("passed_filter", 0),
            "failed_filter": filtered.get("failed_filter", 0), "in_keyword_pool": filtered.get("in_keyword_pool", 0),
            "new_works": len(chained),
            "read_by_model": sum(len(batch) for batch in plan.get("batches") or []),
            "not_read": plan.get("not_read", 0),
            "outcomes": dict(sorted(outcomes.items())),
        }
        self.store.finish_step(step["id"], "succeeded", output=summary)

    async def _source_similarity(self, run: dict[str, Any], scope: dict[str, Any], candidates: list[dict[str, Any]]) -> None:
        """Score screened sources by the similarity of their title and abstract to the question (D30).

        Uses the semantic search provider (D29). Only the source list's "Most relevant" order reads the score. A failed
        request is recorded as a failed step, and the list then orders by search position as before.
        """
        provider, model = embeddings.chosen(self.store.setting("semantic_search"))
        if provider == "off" or not model:
            return
        embedder = embeddings.Embedder(provider, model)
        rid, revision = run["research_id"], run["scope_revision"]
        scored = self.store.scored_sources(rid, revision, embedder.stored_model)
        missing = [c["source_version_id"] for c in candidates if c["source_version_id"] not in scored]
        if not missing:
            return
        step = self.store.step(run["id"], "source_similarity", f"similarity:{embedder.stored_model}")
        self.store.start_step(step["id"])
        texts = ["\n\n".join([self.store.source(svid)["title"], *(p["text"] for p in self.store.passages_for(svid) if p["kind"] == "abstract")])
                 for svid in missing]
        try:
            vectors = await embedder.embed(self.deps.http, texts, "RETRIEVAL_DOCUMENT")
            (query,) = await embedder.embed(self.deps.http, [scope["question"]], "RETRIEVAL_QUERY")
        except embeddings.EmbeddingError as exc:
            self.store.finish_step(step["id"], "failed", error_code="embedding_failed", error={"error": str(exc)})
            return
        self.store.save_source_similarities(rid, revision, embedder.stored_model,
                                            {svid: embeddings.similarity(query, v) for svid, v in zip(missing, vectors)})
        self.store.finish_step(step["id"], "succeeded", output={"model": embedder.stored_model, "sources": len(missing)})

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

    async def _search(self, run: dict[str, Any], index: int, query: dict[str, Any], per_query: int,
                      retry_failed: bool = True) -> tuple[str, dict[str, Any]] | None:
        """Run one legacy provider query: one unpaged request, as the legacy workflow has always sent it.

        A failure is recorded and returned as (pause reason, detail). The sw workflow reads its queries through
        `_search_round` instead.
        """
        run_id = run["id"]
        connector = CONNECTORS[query["provider_id"]]
        step = self.store.step(run_id, f"search:{index}", f"provider_search:{connector.provider_id}")
        if step["status"] == "succeeded" or (step["status"] in ("failed", "outcome_unknown") and not retry_failed):
            return None
        # Bounded network and rate-limit retries are requests too and count against the same allowance.
        allowance = (run["budget"]["max_provider_requests"] + run["budget"].get("retry_provider_requests", 0)
                     + MAX_TRANSIENT_NETWORK_RETRIES + MAX_RATE_LIMIT_RETRIES)
        if self.store.run(run_id)["usage"].get("provider_requests", 0) >= allowance:
            self._pause(run_id, "budget_exhausted", {"limit": "provider_requests"})
        self.store.start_step(step["id"])
        limit = min(query.get("results") or per_query, connector.max_results)  # a deep core query carries its own depth
        outcome = await self._send_search(run_id, connector, query, limit)
        return self._record_search(run, step, query, outcome, limit)

    async def _send_search(self, run_id: str, connector: Connector, query: dict[str, Any], limit: int,
                           page: Page | None = None, stop: Callable[[], bool] | None = None) -> SearchOutcome | None:
        """Send one search request, with its bounded retries, counting each against the run and, for an sw page,
        against the query's own count too (D89). Nothing but the counts is written here.

        With `stop`, a stop asked during the wait before a network retry sends nothing more and returns None: the
        page is left unwritten and a resumed run asks for it again (second review of 13f, 2026-09-23). The 429 waits
        inside a connector's own `send` are not interrupted."""
        query_key = page.query_key if page else None
        attempts = 0
        while True:
            self.store.add_usage(run_id, "provider_requests", query=query_key)
            # A paged read is the sw workflow's, and only it asks for the extra fields the connector names; the
            # unpaged legacy request keeps the parameters it has always sent.
            outcome = await connector.search(self.deps.http, query["query_text"], limit, connector.api_key(),
                                             self.deps.settings.contact_email,
                                             **({"cursor": page.cursor, "max_rate_limit_retries": page.rate_limit_retries,
                                                 **connector.sw_options, **endpoint_options(query)} if page else {}))
            if outcome.retries:
                self.store.add_usage(run_id, "provider_requests", outcome.retries, query=query_key)
            if outcome.status == "failed" and outcome.delivery_class == "before_send" and attempts < MAX_TRANSIENT_NETWORK_RETRIES:
                attempts += 1
                await asyncio.sleep(1.5 * attempts)
                if stop is not None and stop():
                    return None
                continue
            return outcome

    def _record_search(self, run: dict[str, Any], step: dict[str, Any], query: dict[str, Any], outcome: SearchOutcome,
                       limit: int, page: Page | None = None, stop_reason: str | None = None,
                       finished_at: str | None = None) -> tuple[str, dict[str, Any]] | None:
        """Write one answered request: its payload, its search run, its records and its step's ending together.

        For an sw page, `stop_reason` is the one the read decided when the page arrived (`_read_query`).
        A failure is returned as (pause reason, detail).
        """
        run_id, rid = run["id"], run["research_id"]
        settings = self.deps.settings
        provider = CONNECTORS[query["provider_id"]].provider_id
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
                             # How many 429s this effort was willing to wait out here: a skipped wait is on the row,
                             # never silent (D88).
                             | ({"rate_limit_retries": page.rate_limit_retries} if page else {})),
            raw_payload_path=payload_path, payload_sha256=payload_digest,
        )
        ok = outcome.status in ("completed", "zero_results")
        read_total = None
        if page is not None:
            read_total = page.read_before + len(outcome.records)
            # The total a later page did not repeat is the one an earlier page reported; unknown stays NULL, not zero.
            total = outcome.provider_total if outcome.provider_total is not None else page.known_total
            search_fields |= dict(
                page_number=page.number, read_limit=page.read_limit, read_total=read_total, stop_reason=stop_reason,
                unread_count=max(0, total - read_total) if stop_reason and total is not None else None,
            )
        if ok:
            output = {"status": outcome.status, "result_count": len(outcome.records)}
            if page is not None:
                output |= {"page": page.number, "next_cursor": outcome.next_cursor, "read_total": read_total,
                           "provider_total": outcome.provider_total, "stop_reason": stop_reason}
            self.store.record_search(search_fields, provider, outcome.records, payload_path, step["id"], "succeeded",
                                     step_output=output, first_rank=page.read_before if page else 0,
                                     finished_at=finished_at)
            return None
        final = "outcome_unknown" if outcome.delivery_class == "after_send_unknown" else "failed"
        self.store.record_search(search_fields, provider, outcome.records, payload_path, step["id"], final,
                                 error_code=outcome.status, error={"error": outcome.error, "http_status": outcome.http_status},
                                 delivery_class=outcome.delivery_class, first_rank=page.read_before if page else 0,
                                 finished_at=finished_at)
        return f"provider_{outcome.status}", {"provider": provider, "http_status": outcome.http_status,
                                              "retry_after": outcome.rate_limit.get("retry-after")}

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
        while True:
            key = query_key if number == 0 else f"{query_key}:page:{number}"
            step = self.store.existing_step(run_id, key)
            status = step["status"] if step else "pending"
            if status == "succeeded" or (status in ("failed", "outcome_unknown") and not retry_failed):
                output = (step["output"] or {}) if status == "succeeded" else {}
                if status != "succeeded" or output.get("stop_reason") or not output.get("next_cursor"):
                    return False
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
            outcome = await self._send_search(
                run_id, connector, read.query, limit, page,
                stop=lambda: (abort is not None and abort.is_set()) or self._stop_requested(run_id, revision))
            if outcome is None:
                return True
            ok = outcome.status in ("completed", "zero_results")
            read_total = before + len(outcome.records)
            stop_reason = _stop_reason(connector, outcome, ok, read_total, page.read_limit)
            if stop_reason is None and self._query_requests(run_id, query_key) >= allowance:
                stop_reason = "budget_exhausted"  # the next page would need a request the query no longer has (D89)
            read.pages.append(_PageRead(key, page, outcome, limit, stop_reason, started, now()))
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
                                              held.stop_reason, held.finished_at) or failure
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
            found = phrase_candidates.candidates(
                expansion_rules.first_round_records(
                    self.store, rid, revision,
                    {(q["provider_id"], q["query_text"]) for q in own} if len(own) < len(queries) else None),
                [expansion_rules.queried_form(term) for term in expansion_rules.queried_terms(vocabulary)],
                [*vocabulary["claim_words"], *vocabulary["exclusion_words"]])
            self.store.start_step(step["id"])
            result = await expansion_rules.expand(vocabulary, found, self._count_probe(scope))
            second = expansion_rules.second_round_vocabulary(vocabulary, result["terms"], own)
            # Where each accepted phrase went (D90); the protocol body keeps the compiled queries, not this.
            result["second_round"] = {key: second[key] for key in ("setting_synonyms", "task_additions", "setting_width")}
            # A run from before D93 compiles its second round as its first was (review of slice 14, 2026-09-23).
            more = query_compiler.compile_block_queries(
                second, self._providers(run_id, scope), budget["max_provider_requests"],
                routed=self._routing(run_id) is not None) if second["terms"] else []
            result["searched"] = expansion_rules.searched_additions(result, more)
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
        heads = self.store.included_works(rid)  # one per included work
        selection_revision = self.store.selection_revision(rid)  # read together with the included set it describes
        await self._inspect(run, limit=MAX_DOWNLOADS_PER_RUN)
        included = [self.store.answer_version(rid, head) for head in heads]
        await self._read_equations(run, included)

        self._checkpoint(run_id)
        self.store.update_run(run_id, stage="answer")
        semantic = await self._semantic_ranking(run, scope, included)
        # An sw research fills part of the input from the cue phrases its criterion was approved with (D84); a
        # legacy research passes nothing and keeps the hand-written formulation quota it had.
        patterns = self._criterion_phrases(run, scope) if scope.get("search_workflow") == "sw" else None
        passages = self._retrieve(rid, scope, included, run["budget"]["max_answer_passages"], semantic, patterns)
        if not passages:
            self.store.save_answer(rid, run_id, None, None, run["scope_revision"], "no_evidence", None,
                                   {"ok": True, "issues": [], "note": "No accessible passages for the included sources."},
                                   selection_revision=selection_revision)
            return
        source_ids = list(dict.fromkeys(p["source_version_id"] for p in passages))
        output = await self._model_step(run, scope, "grounded_answer", "grounded_answer", source_ids=source_ids, passage_rows=passages,
                                        selection_revision=selection_revision)
        self._checkpoint(run_id)
        step = self.store.step(run_id, "grounded_answer", "model:grounded_answer")
        # The revision recorded with the StepInput the output came from; a resumed run may reuse an earlier output.
        step_selection = self.store.step_input_selection_revision(output["step_input_id"])
        if output.get("invalid"):
            try:
                draft = json.loads(output["raw_output"] or "")
                draft = draft if isinstance(draft, dict) else None
            except json.JSONDecodeError:
                draft = None
            self.store.save_answer(rid, run_id, step["id"], output["step_input_id"], run["scope_revision"], "unverified_draft",
                                   draft, {"ok": False, "issues": output["issues"]}, selection_revision=step_selection)
            return
        payload = self.store.step_input_payload(output["step_input_id"])
        links = contracts.derive_evidence_links(payload, output["result"])
        answer_id = self.store.save_answer(rid, run_id, step["id"], output["step_input_id"], run["scope_revision"], "structurally_valid",
                                           output["result"], {"ok": True, "issues": [], "warnings": output.get("warnings", [])}, links,
                                           selection_revision=step_selection)
        await self._review(run, scope, answer_id, output["result"])

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
        """
        service = self.deps.equations
        if service is None or not service.available():
            return
        run_id = run["id"]
        assets = [r[0] for svid in svids for r in self.store.conn.execute(
            "SELECT id FROM source_assets WHERE source_version_id = ? AND removed_at IS NULL", (svid,))]
        for asset_id in assets:
            step = self.store.step(run_id, f"equations:{asset_id}", "read_equations")
            if step["status"] in ("succeeded", "failed") or equation_state(self.store, asset_id)["state"] in ("read", "no_math"):
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
            if state["state"] == "failed":
                self.store.finish_step(step["id"], "failed", error_code="equations_failed", error={"asset_id": asset_id, **state})
                self._pause(run_id, "equations_failed", {"asset_id": asset_id, **state})
            self.store.finish_step(step["id"], "succeeded", output={"asset_id": asset_id, **state})

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
        path = papers / f"{sha}.pdf"
        if not path.exists():
            path.write_bytes(result.data)
        extraction = await asyncio.to_thread(pdf.extract_pdf, path)
        asset_id = self.store.add_asset_with_pages(
            source["id"], sha, len(result.data), path.name, "download", result.final_url, None,
            extraction, pdf.EXTRACTION_VERSION, pdf.chunk_page,
        )
        status = "succeeded" if extraction.status in ("succeeded", "partial") else "partial"
        self.store.finish_step(step["id"], status, output={"asset_id": asset_id, "extraction_status": extraction.status,
                                                          "page_count": extraction.page_count,
                                                          "passage_count": self.store.asset_passage_count(asset_id)},
                               error_code=None if status == "succeeded" else f"extraction_{extraction.status}")

    def _needs_other_copy(self, research_id: str, source: dict[str, Any], refusal: dict[str, Any]) -> bool:
        """A blocked (403) or missing (404) link leads to one lookup per source; "Find PDF" repeats it on request."""
        return (refusal["http_status"] in (403, 404) and normalize_doi(source["doi"]) is not None
                and not self.store.pdf_discoveries(research_id, source["id"]))

    async def _find_other_copy(self, run: dict[str, Any], source: dict[str, Any],
                               other_versions: bool = False) -> dict[str, Any]:
        """Look the DOI up in Unpaywall, OpenAlex, Crossref and CORE and retrieve a copy of the same version.

        Web search stays the user's "Find PDF" action, and a copy of uncertain version waits for the user to confirm it.
        `other_versions` is the full-text retrieval run's addition (D83): a verified copy of a different declared
        version is attached to its own row under the work. An answer run and a PDF collection run never pass it.
        """
        step = self.store.step(run["id"], f"other_copy:{source['id']}", "pdf_other_copy")
        self.store.start_step(step["id"])
        settings = self.deps.settings
        found = await acquisition.acquire_for_source(
            self.store, run["research_id"], source["id"], self.deps.http, settings.papers_dir, settings.contact_email, None,
            self.deps.fetch_pdf, core_key=CONNECTORS["core"].api_key(), web_search=False, other_versions=other_versions,
        )
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

    # ---- the full-text retrieval run of an sw research (slice 10, SW10, D83) --------------
    async def _fulltext_fetch(self, run: dict[str, Any], scope: dict[str, Any]) -> None:
        """Retrieve the open full text of this research's ranked works, one attempt per work, and record what came back.

        No model is called and nothing is included or excluded: the three codes this run writes are all
        `unresolved` (SW1.2), and the user's own decision is skipped rather than overwritten. The plan is frozen in
        the first step's output, so a resumed run finishes the same list instead of one that moved under it, and a
        work whose step is already stored is skipped without touching any counter (slice 09's review, lesson 1).

        Up to `fulltext.FULLTEXT_FETCH_PARALLEL` works are fetched at once (slice 13e), bounded here and not by the
        run's limiter, which is sized for model calls. No host is asked two things at once (`fetch.host_gate`), so
        works fetched side by side never arrive at one publisher together. Nothing one work writes is read by
        another, so which of them finishes first changes no decision.
        """
        run_id, revision = run["id"], run["scope_revision"]
        self._checkpoint(run_id, revision)
        self.store.update_run(run_id, stage="inspection")
        plan = self._fulltext_plan(run, scope)
        await self._fetch_works(run, plan["works"])
        self._fulltext_summary(run, plan)

    async def _fetch_works(self, run: dict[str, Any], heads: list[str]) -> None:
        """Send the planned works to `_fulltext_work`, at most `FULLTEXT_FETCH_PARALLEL` in flight, in plan order.

        `_send_through_limiter`'s loop, with one difference: the stop is looked at before each work is sent, but it
        is written on the run (`_checkpoint`) only once the works in flight have finished. Each work writes its own
        decision as it ends, so a run that already read as paused while works were still writing would let the
        user revise the question under decisions that are still arriving. A pause therefore reads as paused when
        nothing is left in flight, as it did when the works were fetched one by one. A work's own stop check
        (`_stop_work_if_requested` in `_fetch_work_text`) stops that work where it stands without writing the
        pause either, and the others finish.
        """
        run_id, revision = run["id"], run["scope_revision"]
        works = iter(heads)
        pending: set[asyncio.Task[None]] = set()
        stopping, stopped, failure = False, None, None
        while True:
            while not stopping and failure is None and len(pending) < fulltext.FULLTEXT_FETCH_PARALLEL:
                if self._stop_requested(run_id, revision):
                    stopping = True
                    break
                head = next(works, None)
                if head is None:
                    break
                pending.add(asyncio.ensure_future(self._fulltext_work(run, head)))
            if not pending:
                break
            done, pending = await asyncio.wait(pending, return_when=asyncio.FIRST_COMPLETED)
            for task in done:
                try:
                    task.result()
                except RunStopped as exc:
                    stopping, stopped = True, stopped or exc
                except Exception as exc:  # _fulltext_work closes its own step on any other failure
                    failure = failure or exc
        if failure is not None:
            raise failure
        self._checkpoint(run_id, revision)
        if stopped is not None:
            raise stopped

    def _stop_requested(self, run_id: str, revision: int) -> bool:
        """Whether `_checkpoint` would stop the run now, without writing the stop: a pause, a cancellation or a newer
        question revision."""
        run = self.store.run(run_id)
        return (run["status"] in ("pause_requested", "cancelled")
                or self.store.research(run["research_id"])["current_scope_revision"] != revision)

    def _stop_work_if_requested(self, run: dict[str, Any]) -> None:
        """Stop this work where it stands when a stop is requested, leaving the pause for `_fetch_works` to write once
        the works in flight beside it have finished (the same stop `_checkpoint` writes; slice 13e review)."""
        if self._stop_requested(run["id"], run["scope_revision"]):
            raise RunStopped

    def _fulltext_plan(self, run: dict[str, Any], scope: dict[str, Any]) -> dict[str, Any]:
        """Freeze which works this run fetches, and write the code of the works whose text is already here.

        A step that already succeeded returns its stored plan: the eligible works are a different list once this
        run has written its first decisions, and a plan derived again would skip what it had already fetched and
        fetch what it had not (the bug slice 07's review found, in the shape slice 09 kept it out of).
        """
        run_id, rid, revision = run["id"], run["research_id"], run["scope_revision"]
        step = self.store.step(run_id, "fulltext_plan", "code:fulltext_plan")
        if step["status"] == "succeeded":
            return step["output"]
        self.store.start_step(step["id"])
        chained, order, chain_order = self._chain_state(rid, revision)
        works = self._fulltext_works(rid, chained)
        limit = run["budget"]["max_fulltext_works"]
        # The chain group's own room (D95); a run queued before D95 has none and plans the three keyword groups alone.
        room = run["budget"].get("chain_room", 0)
        plan = fulltext.fetch_plan(works, order, limit, chain_order, room)
        by_head = {work["head"]: work for work in works}
        # Nothing is requested for a work whose text is already here; the code it asks for is written straight away,
        # on the version an answer would read (D48).
        written = self._write_fulltext_codes(
            run, step["id"], [(self.store.answer_version(rid, head), "not_read_yet") for head in plan["already_text"]])
        groups = Counter(fulltext.group_of(by_head[head])
                         for head in plan["works"] + plan["not_reached"] + plan["already_text"])
        output = {"limit": limit, "works": plan["works"], "not_reached": len(plan["not_reached"]),
                  "already_text": len(plan["already_text"]), "decisions": written,
                  # A research nothing was chained for reads as it did before D95: three groups, no chain room.
                  "groups": {name: groups.get(name, 0) for name in (fulltext.GROUPS if chained
                                                                     else fulltext.KEYWORD_GROUPS)}}
        if chained:
            output |= {"chain_room": room,
                       "chain_works": sum(fulltext.group_of(by_head[head]) == "chain" for head in plan["works"]),
                       "chain_not_reached": sum(fulltext.group_of(by_head[head]) == "chain"
                                                for head in plan["not_reached"])}
        self.store.finish_step(step["id"], "succeeded", output=output)
        return output

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
        return (set(stored.get("chained") or []), self._current_heads(research_id, order),
                decisions.latest_chain_ranking(research_id, revision))

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

        by_work: dict[str, list[str]] = {}
        for version in versions.values():
            by_work.setdefault(version["work_id"], []).append(version["id"])

        def decision(svid: str, stage: str) -> dict[str, Any] | None:
            row = held.get((svid, stage))
            return None if row is None else {"reason_code": row["reason_code"], "decided_by": row["decided_by"],
                                             "stale": decisions.is_stale(row, stale_key)}

        return [{"work_id": work_id, "head": head, "selection": selections.get(head), "chained": head in chained,
                 "versions": [{"id": svid, "has_text": svid in with_text,
                               "abstract": decision(svid, "abstract"), "fulltext": decision(svid, "fulltext")}
                              for svid in sorted(by_work.get(work_id, []))]}
                for work_id, head in sorted(heads.items())]

    async def _fulltext_work(self, run: dict[str, Any], head: str) -> None:
        """One work's single retrieval attempt, its identity check and the code it settles on.

        A work whose step is already stored is skipped before anything is counted, so a resumed run charges its
        limit only for the work it still has to do. One work's unexpected failure closes that work's step and the
        next work goes on (D18): the run stops only where `_checkpoint` sees a pause, a cancellation or a newer
        question revision.
        """
        run_id, rid = run["id"], run["research_id"]
        step = self.store.step(run_id, f"fulltext_work:{head}", "code:fulltext_work")
        if step["status"] in ("succeeded", "failed"):
            return
        self.store.start_step(step["id"])
        try:
            output = await self._fetch_work_text(run, head)
        except RunStopped:
            raise
        except Exception as exc:  # noqa: BLE001 - one work's failure must not end the run
            self.store.finish_step(step["id"], "failed", error_code="fulltext_work_failed",
                                   error={"head": head, "error": f"{type(exc).__name__}: {exc}"})
            return
        if output["code"] is None:
            # Not every route answered, so nothing is decided; the next retrieval run plans this work again.
            self.store.finish_step(step["id"], "failed", output=output, error_code="fetch_not_settled",
                                   error={"head": head, "requests_unanswered": output["requests_unanswered"]})
            return
        self._write_fulltext_codes(run, step["id"], [(output["read_version"], output["code"])])
        self.store.finish_step(step["id"], "succeeded", output=output)

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
        read = self.store.answer_version(rid, head) if has_text else head
        asset_id = self._current_asset(read) if has_text else None
        return {"work_id": source["work_id"], "head": head, "read_version": read,
                "version_label": self.store.source(read)["version_label"], "asset_id": asset_id, "route": route,
                "identity": identity.check(self._pdf_head_text(read), [self.store.source(s) for s in versions])
                            if has_text else None,
                "code": fulltext.settled_code({"has_text": has_text, "has_asset": has_asset, "unanswered": unanswered}),
                "requests_unanswered": unanswered}

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
        latest = {d["provider"]: d["status"] for d in self.store.pdf_discoveries(research_id, svid)}
        return (sum(1 for status in latest.values() if status in UNANSWERED_LOOKUP_STATUSES)
                + sum(1 for c in self.store.pdf_candidates(svid) if c["access_status"] in UNANSWERED_LOOKUP_STATUSES))

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

    def _fulltext_summary(self, run: dict[str, Any], plan: dict[str, Any]) -> None:
        """What this run retrieved, totalled from its stored work steps rather than from a live counter.

        A resumed run read its earlier works back without counting them, so the counter in memory knows only the
        second half; the steps know the whole run, and an uninterrupted run and a resumed one report the same
        numbers because of it (slice 09's review, lesson 1).
        """
        run_id = run["id"]
        step = self.store.step(run_id, "fulltext_summary", "code:fulltext_summary")
        if step["status"] == "succeeded":
            return
        self.store.start_step(step["id"])
        codes: Counter[str] = Counter()
        identities: Counter[str] = Counter()
        routes: Counter[str] = Counter()
        not_settled = 0
        for row in self.store.run_steps(run_id):
            if row["kind"] != "code:fulltext_work":
                continue
            output = row["output"] or {}
            if row["status"] != "succeeded" or not output.get("code"):
                not_settled += 1
                continue
            codes[output["code"]] += 1
            routes[output["route"] or "none"] += 1
            if output.get("identity"):
                identities[output["identity"]] += 1
        summary = {"fetched": codes["not_read_yet"], "unreadable": codes["text_unreadable"],
                   "no_fulltext": codes["no_fulltext"], "not_settled": not_settled,
                   "already_text": plan["already_text"], "not_reached": plan["not_reached"],
                   "identity": dict(sorted(identities.items())), "routes": dict(sorted(routes.items()))}
        self.store.finish_step(step["id"], "succeeded", output=summary)

    async def _fulltext_adjudication(self, run: dict[str, Any], scope: dict[str, Any]) -> None:
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
        plan = self._adjudication_plan(run, scope)
        works = plan["works"]
        if plan.get("reason") == "no_criterion" or not works:
            self._adjudication_summary(run, plan)
            return
        spent_before = self.store.run(run_id)["usage"].get("model_calls", 0)
        submitted = 0
        collected: dict[str, dict[int, dict[str, Any] | None]] = {}
        closed: set[str] = set()
        items = {item["head"]: item for item in works}
        answered = {s["operation_key"] for s in self.store.run_steps(run_id)
                    if s["kind"] == "model:fulltext_adjudication"
                    and (s["status"] == "succeeded" or s["error_code"] == "invalid_model_output")}

        def jobs() -> Iterator[_AdjudicationJob]:
            nonlocal submitted
            for item in works:
                head, read_version = item["head"], item["read_version"]
                if not self._adjudication_member(run["research_id"], head, read_version):
                    continue
                owed = [run_no for run_no in range(1, FULLTEXT_RUNS + 1)
                        if f"fulltext_adjudication:{head}:{run_no}" not in answered]
                if owed and not self._model_calls_left(run, len(owed), submitted, spent_before):
                    return
                for run_no in range(1, FULLTEXT_RUNS + 1):
                    still_owed = run_no in owed
                    if still_owed and not self._model_calls_left(run, 1, submitted, spent_before):
                        # A repair on an earlier call of this work used the room this call needed. The run
                        # finishes; this work is not given a decision from one run.
                        return
                    submitted += still_owed
                    yield _AdjudicationJob(f"fulltext_adjudication:{head}:{run_no}", head, read_version, run_no)

        async def call(job: _AdjudicationJob) -> dict[str, Any] | None:
            if not self._adjudication_member(run["research_id"], job.head, job.read_version):
                return None
            try:
                return await self._adjudication_call(run, scope, plan, job, self.deps.limiter)
            except RunStopped:
                raise
            except Exception:
                # One work's unexpected failure is recorded by not deciding it. The rest of the run continues (D18).
                return None

        def close_ready(completed: list[tuple[dict[str, Any] | None, _AdjudicationJob]]) -> None:
            for output, job in completed:
                collected.setdefault(job.head, {})[job.run_no] = output
            for head in sorted(collected):
                if head in closed or len(collected[head]) < FULLTEXT_RUNS:
                    continue
                try:
                    self._checkpoint(run_id, revision)
                    self._close_adjudication(run, items[head], plan,
                                             [collected[head][run_no] for run_no in range(1, FULLTEXT_RUNS + 1)])
                except RunStopped:
                    raise
                except Exception:
                    pass
                closed.add(head)

        stop = await self._send_through_limiter(run, jobs(), call, close_ready)
        if stop is not None:
            raise stop
        self._adjudication_summary(run, plan)

    def _adjudication_member(self, research_id: str, head: str, read_version: str) -> bool:
        """Whether both records are still in this research. A purged member is skipped, not crashed on."""
        return self.store.is_active_member(research_id, head) and self.store.is_active_member(research_id, read_version)

    def _adjudication_plan(self, run: dict[str, Any], scope: dict[str, Any]) -> dict[str, Any]:
        """Freeze which works are read, on which version, and which PDFs are not confirmed as the work's own.

        Identity is computed here, from the text and the work's versions, never from a retrieval run's step.
        An unconfirmed PDF is decided `pdf_identity_unconfirmed` with no model call and does not consume the
        read limit. A file the user supplied is confirmed without that check.
        """
        run_id, rid = run["id"], run["research_id"]
        step = self.store.step(run_id, "adjudication_plan", "code:adjudication_plan")
        if step["status"] == "succeeded":
            return step["output"]
        self.store.start_step(step["id"])
        limit = run["budget"]["max_fulltext_reads"]
        frozen = self.store.frozen_criterion(rid, scope["question"], scope.get("steering"))
        if frozen is None:
            plan = {"limit": limit, "criterion": None, "works": [], "not_reached": 0,
                    "identity_unconfirmed": 0, "reason": "no_criterion"}
            self.store.finish_step(step["id"], "succeeded", output=plan)
            return plan
        parts = frozen["parts"] or []
        sent = ([{"name": "criterion", "definition": frozen["criterion"]}] if not parts
                else [{"name": part["name"], "definition": part["definition"]} for part in parts])
        criterion = {"criterion": frozen["criterion"], "parts": sent, "cue_phrases": frozen["cue_phrases"],
                     "protocol_revision": frozen["protocol_revision"]}
        # Chained works are read after the keyword order, in the chain's own order (D95); the limit is the same.
        chained, order, chain_order = self._chain_state(rid, run["scope_revision"])
        order = order + chain_order
        corpus = self._fulltext_works(rid, chained)
        eligible = adjudication.read_plan(corpus, order, len(corpus))
        readable: list[dict[str, str]] = []
        unconfirmed: list[tuple[str, str]] = []
        for head in eligible["works"]:
            read = self.store.answer_version(rid, head)
            versions = [head, *self.store.work_versions(rid, head)]
            if self._user_supplied_pdf(read):
                readable.append({"head": head, "read_version": read})
                continue
            found = identity.check(self._pdf_head_text(read), [self.store.source(svid) for svid in versions])
            if found == "unconfirmed":
                unconfirmed.append((head, read))
            else:
                readable.append({"head": head, "read_version": read})
        plan = {"limit": limit, "criterion": criterion, "works": readable[:limit],
                "not_reached": len(readable) - len(readable[:limit]),
                "identity_unconfirmed": len(unconfirmed), "reason": None}
        self._write_adjudication_codes(run, step["id"], [(read, "pdf_identity_unconfirmed") for _, read in unconfirmed])
        self.store.finish_step(step["id"], "succeeded", output=plan)
        return plan

    def _user_supplied_pdf(self, svid: str) -> bool:
        """A PDF the user added is the file they meant. It is not held back for an identity check."""
        if self.store.source(svid).get("origin") == "user_upload":
            return True
        asset_id = self._current_asset(svid)
        return bool(asset_id) and self.store.asset(asset_id).get("origin") == "user_upload"

    async def _adjudication_call(self, run: dict[str, Any], scope: dict[str, Any], plan: dict[str, Any],
                                 job: _AdjudicationJob, limiter: ModelCallLimiter | None) -> dict[str, Any] | None:
        """One run of one work. None when the output did not validate: that is an answer for this run, not a retry."""
        step = self.store.step(run["id"], job.key, "model:fulltext_adjudication")
        if step["status"] == "failed" and step["error_code"] == "invalid_model_output":
            return None
        passages = self._adjudication_passages(run["research_id"], scope, plan["criterion"], job.read_version)
        target = {"source_id": job.read_version, "criterion": plan["criterion"]["criterion"],
                  "parts": plan["criterion"]["parts"], "runs": FULLTEXT_RUNS, "run": job.run_no}
        output = await self._model_step(run, scope, job.key, "fulltext_adjudication", source_ids=[job.read_version],
                                        passage_rows=passages, adjudication_target=target, limiter=limiter,
                                        budget_short="skip")
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
        """Verify both runs' quotes on the pages they were shown and write one decision on the read version."""
        read = item["read_version"]
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
            views.append(adjudication.run_view(proposals))
        code = adjudication.combine(views[0] if views else None, views[1] if len(views) > 1 else None)
        if code is not None:
            self._write_adjudication_codes(run, last_step, [(read, code)])

    def _write_adjudication_codes(self, run: dict[str, Any], step_id: str | None,
                                  writes: list[tuple[str, str]]) -> None:
        """Write these full-text decisions and derive each work's selection. The user's decision is left as it is."""
        rid = run["research_id"]
        decisions = DecisionStore(self.store)
        stale_key = decisions.staleness_key(rid)
        touched: set[str] = set()
        for svid, code in writes:
            held = decisions.current(rid, svid, "fulltext")
            if held is not None and held["decided_by"] == "human":
                continue
            if not adjudication.should_write(held, code, bool(held) and decisions.is_stale(held, stale_key)):
                continue
            try:
                decisions.record(rid, svid, code, step_id=step_id)
            except HumanDecisionStands:
                continue
            touched.add(self.store.source(svid)["work_id"])
        for work_id in sorted(touched):
            decisions.derive_selection(rid, work_id)

    def _adjudication_summary(self, run: dict[str, Any], plan: dict[str, Any]) -> None:
        """What this run decided, totalled from its stored steps and decisions so a resumed run matches."""
        run_id = run["id"]
        step = self.store.step(run_id, "adjudication_summary", "code:adjudication_summary")
        if step["status"] == "succeeded":
            return
        self.store.start_step(step["id"])
        steps = self.store.run_steps(run_id)
        step_ids = [row["id"] for row in steps]
        planned = {item["head"]: item["read_version"] for item in plan["works"]}
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
        not_settled = sum(1 for head, read in planned.items() if head in model_heads and read not in decided_versions)
        not_reached = plan["not_reached"] + sum(1 for head in planned if head not in model_heads)
        whole_text = self._adjudication_whole_text(run_id)
        summary = {"read": include + not_met + sum(unresolved.values()) - unresolved.get("pdf_identity_unconfirmed", 0),
                   "include": include, "criterion_not_met": not_met, "unresolved": unresolved,
                   "not_settled": not_settled, "not_reached": not_reached,
                   "identity_unconfirmed": plan["identity_unconfirmed"], "whole_text": whole_text,
                   "model_calls": self.store.run(run_id)["usage"].get("model_calls", 0)}
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

    def _queue_fulltext_adjudication(self, run: dict[str, Any], scope: dict[str, Any]) -> None:
        """Queue the reading run that follows a completed `sw` retrieval run (D85).

        Only when the setting is `auto`, a criterion is frozen, and the read plan holds at least one work.
        The budget is the one function the API route calls too. The idempotency key keeps one retrieval run
        from opening two reading runs. Called in the same turn that marks the retrieval run completed.
        """
        if scope.get("search_workflow") != "sw" or self.deps.settings.fulltext_adjudication != "auto":
            return
        rid, revision = run["research_id"], run["scope_revision"]
        if self.store.frozen_criterion(rid, scope["question"], scope.get("steering")) is None:
            return
        budget = adjudication.read_budget(scope["effort"])
        chained, order, chain_order = self._chain_state(rid, revision)
        plan = adjudication.read_plan(self._fulltext_works(rid, chained), order + chain_order,
                                      budget["max_fulltext_reads"])
        if not plan["works"]:
            return
        self.store.create_run(rid, "fulltext_adjudication", budget,
                              idempotency_key=f"fulltext_adjudication:after:{run['id']}")


    def _queue_fulltext_fetch(self, run: dict[str, Any], scope: dict[str, Any]) -> None:
        """Queue the full-text retrieval run that follows a completed `sw` discovery run (D83, SW10.1).

        Only after a run that really completed: a paused, cancelled or failed discovery run queues nothing, and the
        idempotency key keeps one discovery run from ever opening two retrieval runs. Nothing is queued when the
        plan holds no work. The budget comes from the one function the API route calls too, so a run the user
        starts and a run left behind here can never be given different room.

        Named deviation from SW10.1: the retrieval does not start "right after the code stage" but after the whole
        discovery run, model screening included, because the worker runs one run at a time and a research cannot
        hold two active runs.
        """
        if scope.get("search_workflow") != "sw" or self.deps.settings.fulltext_fetch != "auto":
            return
        rid, revision = run["research_id"], run["scope_revision"]
        budget = fulltext.fetch_budget(scope["effort"])
        chained, order, chain_order = self._chain_state(rid, revision)
        plan = fulltext.fetch_plan(self._fulltext_works(rid, chained), order, budget["max_fulltext_works"],
                                   chain_order, budget["chain_room"])
        if not plan["works"] and not plan["already_text"]:
            return
        self.store.create_run(rid, "fulltext_fetch", budget, idempotency_key=f"fulltext_fetch:after:{run['id']}")

    async def _semantic_ranking(self, run: dict[str, Any], scope: dict[str, Any], included: list[str], query_text: str | None = None,
                                key: str = "semantic_retrieval") -> list[dict[str, Any]] | None:
        """Rank the included sources' passages by embedding similarity to the question, or to query_text (D27, D29).

        Uses the provider chosen in Settings; without a choice, Gemini when GEMINI_API_KEY is set. A failed or
        unavailable embedding request is recorded as a failed step, and the caller then uses lexical retrieval alone.
        """
        provider, model = embeddings.chosen(self.store.setting("semantic_search"))
        if provider == "off" or not model:
            return None
        embedder = embeddings.Embedder(provider, model)
        step = self.store.step(run["id"], key, f"embedding:{embedder.stored_model}")
        self.store.start_step(step["id"])
        passages = [p for svid in included for p in self.store.passages_for(svid)]
        stored = self.store.passage_embeddings([p["id"] for p in passages], embedder.stored_model)
        missing = [p for p in passages if p["id"] not in stored]
        try:
            fresh = await embedder.embed(self.deps.http, [p["text"] for p in missing], "RETRIEVAL_DOCUMENT") if missing else []
            (query,) = await embedder.embed(self.deps.http, [query_text or scope["question"]], "RETRIEVAL_QUERY")
        except embeddings.EmbeddingError as exc:
            self.store.finish_step(step["id"], "failed", error_code="embedding_failed", error={"error": str(exc)})
            return None
        if fresh:
            self.store.save_passage_embeddings(embedder.stored_model, len(fresh[0]),
                                               {p["id"]: vector.tobytes() for p, vector in zip(missing, fresh)})
        vectors = {pid: embeddings.from_blob(blob) for pid, blob in stored.items()} | {p["id"]: v for p, v in zip(missing, fresh)}
        ranked = sorted(passages, key=lambda p: -embeddings.similarity(query, vectors[p["id"]]))
        self.store.finish_step(step["id"], "succeeded",
                               output={"model": embedder.stored_model, "passages": len(passages), "embedded": len(missing)})
        return ranked

    def _topic_terms(self, research_id: str, scope: dict[str, Any]) -> list[str]:
        """The words `_retrieve` and the full-text reading list both rank passages by.

        Moved out of `_retrieve` so the reading run uses the same terms and does not grow a second ranker.
        What `_retrieve` selects from them is unchanged. Claim words stay out: they are the criterion (slice 11).
        """
        terms = [t for t in re.findall(r"\w+", scope["question"].lower()) if len(t) > 2 and t not in STOPWORDS]
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
                pending[asyncio.ensure_future(limiter.run(job.key, lambda job=job: call(job)))] = job

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

    # ---- model steps -------------------------------------------------------------------
    def _step_input(self, run: dict[str, Any], scope: dict[str, Any], step_id: str, task_type: str,
                    candidate_rows: list[dict[str, Any]], source_ids: list[str], passage_rows: list[dict[str, Any]],
                    claims: list[dict[str, Any]], model: tuple[str, str | None, str | None],
                    extraction_target: dict[str, Any] | None = None,
                    report_target: dict[str, Any] | None = None,
                    vocabulary_target: dict[str, Any] | None = None,
                    screening_target: dict[str, Any] | None = None,
                    suggestion_target: dict[str, Any] | None = None,
                    adjudication_target: dict[str, Any] | None = None) -> dict[str, Any]:
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
            seed = scope.get("seed_snapshot") if task_type == "search_plan" else None
            if seed and seed["source_version_id"] == svid:
                source = source | {field: seed[field] for field in ("title", "year", "version_label")}
            kinds = {p["kind"] for p in self.store.passages_for(svid)}
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
            target["report_target"] = report_target
        if vocabulary_target is not None:
            target["vocabulary_target"] = vocabulary_target
        if screening_target is not None:
            target["screening_target"] = screening_target
        if suggestion_target is not None:
            target["suggestion_target"] = suggestion_target
        if adjudication_target is not None:
            target["adjudication_target"] = adjudication_target
        allowlist = {"candidate_ids": [c["candidate_id"] for c in candidates], "source_ids": [s["source_id"] for s in sources],
                     "passage_ids": [p["passage_id"] for p in passages]}
        if vocabulary_target is not None:
            # The allowlist for this step is the phrase list itself: it may label those phrases and name no other.
            allowlist["phrases"] = [entry["phrase"] for entry in vocabulary_target["phrases"]]
        if suggestion_target is not None:
            # The same rule for the suggestion step: a proposed name may be another name for one of these phrases
            # and for no other phrase (slice 08c).
            allowlist["phrases"] = [entry["phrase"] for entry in suggestion_target["phrases"]]
        if task_type in contracts.REPORT_TASKS:
            report = report_target or {}
            cells, gaps = report.get("cells", []), report.get("gap_candidates", [])
            columns = [column["column_id"] for column in report.get("columns", [])]
            columns += [cell["column_id"] for cell in cells] + [gap["column_id"] for gap in gaps]
            columns += [axis["column_id"] for axis in (report.get("plan") or {}).get("axes", [])]
            allowlist |= {"column_ids": list(dict.fromkeys(columns)),
                          "cell_ids": [cell["cell_id"] for cell in cells],
                          "gap_ids": [gap["gap_id"] for gap in gaps]}
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
            "budget": {"max_model_calls": run["budget"]["max_model_calls"], "max_schema_repairs": schema_repairs(task_type),
                       "max_provider_requests": run["budget"]["max_provider_requests"]},
            "model": {"connection": model[0], "requested_model": model[1]},
            "created_at": now(),
        }

    async def _call_adapter(self, run_id: str, rid: str, step_id: str, step_input_id: str, connection: str,
                            requested_model: str | None, adapter: ModelAdapter, base: str, developer: str, message: str,
                            schema: dict[str, Any], reasoning_effort: str | None,
                            limiter: ModelCallLimiter | None) -> tuple[str, ModelStepResult]:
        """Send one model call, resending under a lower ceiling after a rate-limit response.

        Resends reuse the stored StepInput because their model input is identical, and each gets its own model session.
        Passing no limiter keeps the existing one-attempt behavior for model steps outside table fill.
        """
        attempts = 0
        while True:
            session = self.store.start_model_session(rid, run_id, step_id, step_input_id, connection, requested_model)
            result = await adapter.run_step(base, developer, message, schema, requested_model, reasoning_effort)
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
            await asyncio.sleep(RATE_LIMIT_BACKOFF_SECONDS * attempts)

    async def _model_step(self, run: dict[str, Any], scope: dict[str, Any], operation_key: str, task_type: str,
                          candidate_rows: list[dict[str, Any]] | None = None, source_ids: list[str] | None = None,
                          passage_rows: list[dict[str, Any]] | None = None, selection_revision: int | None = None,
                          claims: list[dict[str, Any]] | None = None, model: tuple[str, str | None, str | None] | None = None,
                          optional: bool = False, extraction_target: dict[str, Any] | None = None,
                          report_target: dict[str, Any] | None = None, vocabulary_target: dict[str, Any] | None = None,
                          screening_target: dict[str, Any] | None = None,
                          suggestion_target: dict[str, Any] | None = None,
                          adjudication_target: dict[str, Any] | None = None,
                          limiter: ModelCallLimiter | None = None, budget_short: str = "pause") -> dict[str, Any]:
        """Run one model step on the model chosen for its role. An optional step raises OptionalStepFailed instead of
        pausing or failing the run; a user pause or cancel still stops the run. `budget_short="skip"` is the sw
        stages' rule (D86): a call the budget no longer holds is closed and returned as invalid instead of pausing
        the run, because those stages count what the budget did not reach and a later run reads it."""
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

        adapter = self.deps.adapters.get(connection)
        if adapter is None:
            halt("model_connection_unavailable", {"connection": connection})
        health = await adapter.health()
        if not health.get("ready"):
            halt("model_connection_not_ready", {"connection": connection, "reason": health.get("reason")})
        self._checkpoint(run_id)  # a pause or cancel may have arrived while the connection was checked
        self.store.start_step(step["id"])
        repair_issues: list[dict[str, Any]] | None = None
        max_repairs = schema_repairs(task_type)
        # `attempt` numbers every call this step sends; `repairs` counts only the schema repairs among them, so the
        # one resend after a turn timeout (slice 13e) takes nothing from the repairs the step is allowed.
        attempt, repairs, timeout_resent = -1, 0, False
        while True:
            attempt += 1
            if self.store.run(run_id)["usage"].get("model_calls", 0) >= run["budget"]["max_model_calls"]:
                if repair_issues is not None and budget_short == "skip":
                    # A repair the budget no longer holds is skipped (D86): the invalid answer stands for this run,
                    # as an unrepaired one does, and the run goes on to what it can still afford.
                    self.store.finish_step(step["id"], "failed", output={"step_input_id": invalid_input},
                                           error_code="invalid_model_output", error=repair_issues)
                    return {"invalid": True, "raw_output": invalid_raw, "issues": repair_issues,
                            "step_input_id": invalid_input, "repair_skipped": "budget_exhausted"}
                if budget_short == "skip":
                    # A concurrent sender checked the room before this call and a repair in flight took it. The
                    # work is not reached: no decision is written for it and the run finishes rather than pausing.
                    self.store.finish_step(step["id"], "failed", error_code="budget_exhausted")
                    return {"invalid": True, "issues": [], "step_input_id": None, "not_reached": True}
                self.store.finish_step(step["id"], "failed", error_code="budget_exhausted")
                halt("budget_exhausted", {"limit": "model_calls"})
            payload = self._step_input(run, scope, step["id"], task_type, candidate_rows or [], source_ids or [], passage_rows or [],
                                       claims or [], model, extraction_target, report_target, vocabulary_target,
                                       screening_target, suggestion_target, adjudication_target)
            if issues := contracts.check_step_input(payload):
                self.store.finish_step(step["id"], "failed", error_code="step_input_invalid", error=[vars(i) for i in issues])
                halt("step_input_invalid", fail=True)
            schema = contracts.step_output_schema(task_type)
            base = prompt.BASE_INSTRUCTIONS
            sections = (phrasebank.REPORT_PHRASEBANK_SECTIONS[report_target["section_id"]]
                        if task_type in ("report_section", "report_phrase_repair") else None)
            developer = prompt.developer_instructions(
                self.deps.package, task_type, phrasebank.frames_language(payload), sections=sections,
            )
            if not adapter.enforces_schema:
                developer = developer + "\n\n" + prompt.schema_appendix(task_type, schema)
            # Answer, review and cell steps show short handles; the stored StepInput keeps the record IDs they map back to.
            shown = contracts.with_citation_handles(payload) if task_type in HANDLE_TASKS else payload
            if repair_issues is None:
                message = prompt.step_message(shown)
            else:  # issues name records by ID; the model knows them only by the handles it was shown
                message = prompt.repair_message(shown, contracts.issues_with_handles(payload, repair_issues) if shown is not payload else repair_issues)
            self.store.insert_step_input(step["id"], rid, run_id, attempt, payload, base, developer, message, schema, selection_revision)
            session, result = await self._call_adapter(
                run_id, rid, step["id"], payload["step_input_id"], connection, requested_model, adapter, base, developer,
                message, schema, reasoning_effort, limiter,
            )
            recorded: dict[str, Any] = {
                "status": result.status, "resolved_model": result.resolved_model, "external_thread_id": result.external_thread_id,
                "raw_output": result.raw_text, "token_usage_json": result.token_usage, "tool_item_types_json": result.tool_item_types,
            }
            if result.status == "isolation_violation" or result.tool_item_types:
                self.store.complete_model_step(session, recorded, step["id"], "failed", error_code="model_isolation_violation",
                                               error={"tool_item_types": result.tool_item_types, "error": result.error})
                halt("model_isolation_violation", {"tool_item_types": result.tool_item_types, "error": result.error})
            if result.status != "completed":
                final = "outcome_unknown" if result.delivery_class == "after_send_unknown" else "failed"
                self.store.complete_model_step(session, recorded, step["id"], final, error_code=f"model_{result.status}",
                                               error=result.error, delivery_class=result.delivery_class)
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
                halt("model_call_failed", {"status": result.status, "error": result.error})
            if not requested_model or (result.resolved_model != requested_model and not result.requested_model_verified):
                # Output from any model other than the one chosen for this step's role is recorded but never used.
                mismatch = {"requested_model": requested_model, "resolved_model": result.resolved_model}
                self.store.complete_model_step(session, recorded, step["id"], "failed", error_code="model_mismatch", error=mismatch)
                halt("model_mismatch", mismatch)
            output_text = result.raw_text or ""
            if task_type in ("grounded_answer", "cell_extraction", "abstract_screening", "fulltext_adjudication"):
                output_text = contracts.resolve_citation_handles(payload, output_text)
            # Field names from the alias table are put right before validation and the renames recorded (D86).
            output_text, normalised_changes = contracts.normalise_output(task_type, output_text)
            report = contracts.validate_model_output(payload, output_text)
            salvage: list[contracts.Issue] = []
            if (not report.ok and task_type == "grounded_answer" and isinstance(output_text, dict)
                    and after_invalid_output(repairs, max_repairs) == "store_unverified_draft"):
                # The repair did not fix the draft: drop only citations that lack a quote before giving up on it.
                salvaged, salvage = contracts.salvage_answer_draft(payload, json.loads(json.dumps(output_text)))
                retry = contracts.validate_model_output(payload, salvaged) if salvage else report
                if retry.ok:
                    report = retry
                else:
                    salvage = []
            warnings = [vars(w) for w in salvage + report.warnings]
            recorded["validation_json"] = {"ok": report.ok, "issues": [vars(i) for i in report.issues], "warnings": warnings,
                                         "normalised": normalised_changes}
            if report.ok:
                if task_type == "grounded_answer":
                    report.result = contracts.name_sources_in_prose(payload, report.result)
                output = {"output_type": report.output_type, "result": report.result,
                          "step_input_id": payload["step_input_id"], "resolved_model": result.resolved_model, "warnings": warnings}
                self.store.complete_model_step(session, recorded, step["id"], "succeeded", output=output)
                return output
            repair_issues = [vars(i) for i in report.issues]
            invalid_raw, invalid_input = result.raw_text, payload["step_input_id"]
            if after_invalid_output(repairs, max_repairs) == "store_unverified_draft":
                self.store.complete_model_step(session, recorded, step["id"], "failed", output={"step_input_id": payload["step_input_id"]},
                                               error_code="invalid_model_output", error=repair_issues)
                return {"invalid": True, "raw_output": result.raw_text, "issues": repair_issues, "step_input_id": payload["step_input_id"]}
            repairs += 1
            self.store.finish_model_session(session, **recorded)
