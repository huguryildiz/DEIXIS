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
from deixis.documents import acquisition, embeddings, math_reader, ocr, pdf
from deixis.domain import contracts, phrasebank
from deixis.domain.rules import (MAX_RATE_LIMIT_MODEL_RETRIES, MAX_SCHEMA_REPAIRS, MAX_TRANSIENT_NETWORK_RETRIES,
                                 SCREENING_BATCH, after_invalid_output, effective_reviewer, step_model)
from deixis.domain.skill import RUNTIME_FILES, SkillPackage
from deixis.models import prompt
from deixis.models.adapter import ModelAdapter, ModelStepResult, is_rate_limited
from deixis.providers import query_compiler
from deixis.providers.common import MAX_RATE_LIMIT_RETRIES, normalize_doi
from deixis.providers.registry import CONNECTORS
from deixis.storage.db import dumps, new_id, now
from deixis.workflow.concurrency import ModelCallLimiter
from deixis.workflow.equations import equation_state
from deixis.workflow.store import NotFound, RunInProgress, Store
from deixis.workflow.tables import MAX_COLUMNS_PER_CALL, MAX_FILL_SOURCES, TableStore, check_value

CAPABILITIES = {
    "supported_tasks": ["search_plan", "screening", "grounded_answer", "answer_review", "cell_extraction", "table_columns", "research_title"],
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


def formulation_score(text: str) -> int:
    """Favor explicit optimization language and notation over narrative mentions of a model."""
    return 2 * len(FORMULATION_TERMS.findall(text)) + min(6, len(FORMULATION_SYMBOLS.findall(text)))


def fuse_rankings(*rankings: list[dict[str, Any]], k: int = 60) -> list[dict[str, Any]]:
    """Reciprocal rank fusion: a passage ranked high lexically or semantically comes first (D27)."""
    scores: dict[str, float] = {}
    rows: dict[str, dict[str, Any]] = {}
    for ranking in rankings:
        for position, row in enumerate(ranking):
            scores[row["id"]] = scores.get(row["id"], 0.0) + 1 / (k + position + 1)
            rows.setdefault(row["id"], row)
    return sorted(rows.values(), key=lambda row: -scores[row["id"]])


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
    return sorted(included, key=lambda s: (not facts.get(s, (False, 0))[0], -facts.get(s, (False, 0))[1], -relevance[s], position[s]))


class RunStopped(Exception):
    """The run ended early (pause, cancel or recorded failure); state is already persisted."""


class OptionalStepFailed(Exception):
    """An optional model step could not produce a result; the run continues without it."""

    def __init__(self, reason: str, detail: Any = None):
        super().__init__(reason)
        self.reason, self.detail = reason, detail


@dataclass
class _FillJob:
    key: str
    svid: str
    columns: list[dict[str, Any]]
    cell_versions: dict[str, int]


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
        budget = run["budget"]
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
        for index, query in enumerate(queries):
            self._checkpoint(run_id, revision)
            failure = await self._search(run, index, query, per_query, retry_failed) or failure
        if failure and not searched():
            self._pause(run_id, *failure)

        self._checkpoint(run_id, revision)
        self.store.update_run(run_id, stage="screening")
        # A work is screened once, through its head; its other versions follow the head's selection (D46, D48).
        heads = set(self.store.work_heads(rid).values())
        candidates = [c for c in self.store.candidates(rid, revision)
                      if c["origin"] != "user" and c["source_version_id"] in heads][: budget["max_candidates"]]
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
        await self._source_similarity(run, scope, candidates)

        # Derive a short title from the question and the included sources once screening is done. A structurally valid
        # answer later replaces it (store.save_answer). Optional: the run continues with the provisional title on failure.
        if self.store.included_works(rid):
            try:
                await self._research_title(run, scope, optional=True)
            except OptionalStepFailed:
                return

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

    async def _search(self, run: dict[str, Any], index: int, query: dict[str, Any], per_query: int,
                      retry_failed: bool = True) -> tuple[str, dict[str, Any]] | None:
        """Run one provider query. A failure is recorded and returned as (pause reason, detail) for the caller to weigh."""
        run_id, rid = run["id"], run["research_id"]
        connector = CONNECTORS[query["provider_id"]]
        provider = connector.provider_id
        step = self.store.step(run_id, f"search:{index}", f"provider_search:{provider}")
        if step["status"] == "succeeded" or (step["status"] in ("failed", "outcome_unknown") and not retry_failed):
            return None
        # Bounded network and rate-limit retries are requests too and count against the same allowance.
        allowance = (run["budget"]["max_provider_requests"] + run["budget"].get("retry_provider_requests", 0)
                     + MAX_TRANSIENT_NETWORK_RETRIES + MAX_RATE_LIMIT_RETRIES)
        if self.store.run(run_id)["usage"].get("provider_requests", 0) >= allowance:
            self._pause(run_id, "budget_exhausted", {"limit": "provider_requests"})
        self.store.start_step(step["id"])
        settings = self.deps.settings
        limit = min(query.get("results") or per_query, connector.max_results)  # a deep core query carries its own depth
        attempts = 0
        while True:
            self.store.add_usage(run_id, "provider_requests")
            outcome = await connector.search(self.deps.http, query["query_text"], limit, connector.api_key(), settings.contact_email)
            if outcome.retries:
                self.store.add_usage(run_id, "provider_requests", outcome.retries)
            if outcome.status == "failed" and outcome.delivery_class == "before_send" and attempts < MAX_TRANSIENT_NETWORK_RETRIES:
                attempts += 1
                await asyncio.sleep(1.5 * attempts)
                continue
            break
        payload_path = None
        if outcome.raw_payload is not None:
            settings.payloads_dir.mkdir(parents=True, exist_ok=True)
            payload_path = f"{step['id']}.json"
            (settings.payloads_dir / payload_path).write_text(json.dumps(outcome.raw_payload), encoding="utf-8")
        search_fields = dict(
            research_id=rid, run_id=run_id, step_id=step["id"], scope_revision=run["scope_revision"], provider=provider,
            query_text=query["query_text"], request_description=outcome.request_description,
            access_mode=outcome.access_mode, status=outcome.status, delivery_class=outcome.delivery_class,
            result_count=len(outcome.records), provider_total=outcome.provider_total, page_limit=limit,
            error_json=dumps({"error": outcome.error, "http_status": outcome.http_status, "rate_limit": outcome.rate_limit}),
            raw_payload_path=payload_path,
        )
        if outcome.status in ("completed", "zero_results"):
            self.store.record_search(search_fields, provider, outcome.records, payload_path, step["id"], "succeeded",
                                     step_output={"status": outcome.status, "result_count": len(outcome.records)})
            return None
        final = "outcome_unknown" if outcome.delivery_class == "after_send_unknown" else "failed"
        self.store.record_search(search_fields, provider, outcome.records, payload_path, step["id"], final,
                                 error_code=outcome.status, error={"error": outcome.error, "http_status": outcome.http_status},
                                 delivery_class=outcome.delivery_class)
        return f"provider_{outcome.status}", {"provider": provider, "http_status": outcome.http_status,
                                              "retry_after": outcome.rate_limit.get("retry-after")}

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
        passages = self._retrieve(rid, scope, included, run["budget"]["max_answer_passages"], semantic)
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

    async def _acquire_pdf(self, run: dict[str, Any], svid: str, downloads: int, limit: int | None) -> int:
        """Retrieve the source's open PDF of the same version, if it has none yet; returns the downloads it counted."""
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
            await self._find_other_copy(run, source)
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

    async def _find_other_copy(self, run: dict[str, Any], source: dict[str, Any]) -> None:
        """Look the DOI up in Unpaywall, OpenAlex, Crossref and CORE and retrieve a copy of the same version.

        Web search stays the user's "Find PDF" action, and a copy of uncertain version waits for the user to confirm it.
        """
        step = self.store.step(run["id"], f"other_copy:{source['id']}", "pdf_other_copy")
        self.store.start_step(step["id"])
        settings = self.deps.settings
        found = await acquisition.acquire_for_source(
            self.store, run["research_id"], source["id"], self.deps.http, settings.papers_dir, settings.contact_email, None,
            self.deps.fetch_pdf, core_key=CONNECTORS["core"].api_key(), web_search=False,
        )
        if found["asset_id"] is None:
            self.store.finish_step(step["id"], "failed", error_code="no_other_copy", error={"candidates": found["candidates"]})
            return
        asset = self.store.asset(found["asset_id"])
        status = "succeeded" if asset["extraction_status"] in ("succeeded", "partial") else "partial"
        self.store.finish_step(step["id"], status, output={"asset_id": asset["id"], "extraction_status": asset["extraction_status"],
                                                          "page_count": asset["page_count"],
                                                          "passage_count": self.store.asset_passage_count(asset["id"])},
                               error_code=None if status == "succeeded" else f"extraction_{asset['extraction_status']}")

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

    def _retrieve(self, research_id: str, scope: dict[str, Any], included: list[str], limit: int,
                  semantic: list[dict[str, Any]] | None = None) -> list[dict[str, Any]]:
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
        terms = [t for t in re.findall(r"\w+", scope["question"].lower()) if len(t) > 2 and t not in STOPWORDS]
        plan = self.store.latest_step_output(research_id, "search_plan", scope["revision"])
        if plan and plan.get("output_type") == "SearchPlan":
            for concept in plan["result"]["concepts"]:
                for phrase in [concept["label"], *concept["synonyms"]]:
                    terms += [t for t in re.findall(r"\w+", phrase.lower()) if len(t) > 2 and t not in STOPWORDS]
        unique_terms = list(dict.fromkeys(terms))[:40]
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
                               else (2, -formulation_score(q["text"]), q["physical_page"] if q["physical_page"] is not None else math.inf))
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
        for p in ranked:
            if len(selected) >= limit:
                break
            if p["id"] not in selected and taken.get(p["source_version_id"], 0) < MAX_PASSAGES_PER_SOURCE:
                selected[p["id"]] = p
                taken[p["source_version_id"]] = taken.get(p["source_version_id"], 0) + 1
        return list(selected.values())

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
        job_iter = self._fill_jobs(run, tables, target)
        pending: dict[asyncio.Task[dict[str, Any] | None], _FillJob] = {}
        stop: RunStopped | None = None
        failure: Exception | None = None

        def submit_more() -> None:
            nonlocal stop
            while stop is None and failure is None and len(pending) < limiter.limit:
                try:
                    self._checkpoint(run_id, run["scope_revision"])
                    job = next(job_iter, None)
                except RunStopped as exc:
                    stop = exc
                    return
                if job is None:
                    return

                async def call(job: _FillJob = job) -> dict[str, Any] | None:
                    return await self._extraction(run, scope, job.key, job.svid, job.columns, MAX_FILL_PASSAGES, limiter)

                pending[asyncio.ensure_future(limiter.run(job.key, call))] = job

        submit_more()
        while pending:
            done, _ = await asyncio.wait(pending.keys(), return_when=asyncio.FIRST_COMPLETED)
            completed: list[tuple[dict[str, Any] | None, _FillJob]] = []
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
            if failure is None:
                for output, job in completed:
                    if output is not None and not self._fill_stopped(run_id, run["scope_revision"]):
                        self._save_cells(run, output, job.cell_versions, recheck=False)
            submit_more()
        if failure is not None:
            raise failure
        if stop is not None:
            raise stop

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
                    report_target: dict[str, Any] | None = None) -> dict[str, Any]:
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
        allowlist = {"candidate_ids": [c["candidate_id"] for c in candidates], "source_ids": [s["source_id"] for s in sources],
                     "passage_ids": [p["passage_id"] for p in passages]}
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
            "capabilities": CAPABILITIES, "enabled_providers": scope["providers"],
            "candidates": candidates, "sources": sources, "passages": passages,
            "allowlist": allowlist,
            "human_corrections": [],
            "budget": {"max_model_calls": run["budget"]["max_model_calls"], "max_schema_repairs": MAX_SCHEMA_REPAIRS,
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
                          report_target: dict[str, Any] | None = None,
                          limiter: ModelCallLimiter | None = None) -> dict[str, Any]:
        """Run one model step on the model chosen for its role. An optional step raises OptionalStepFailed instead of
        pausing or failing the run; a user pause or cancel still stops the run."""
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
        for attempt in range(MAX_SCHEMA_REPAIRS + 1):
            if self.store.run(run_id)["usage"].get("model_calls", 0) >= run["budget"]["max_model_calls"]:
                self.store.finish_step(step["id"], "failed", error_code="budget_exhausted")
                halt("budget_exhausted", {"limit": "model_calls"})
            payload = self._step_input(run, scope, step["id"], task_type, candidate_rows or [], source_ids or [], passage_rows or [],
                                       claims or [], model, extraction_target, report_target)
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
            # Answer, review and cell steps show short handles; the stored StepInput keeps the record IDs they map back to.
            shown = contracts.with_citation_handles(payload) if task_type in ("grounded_answer", "answer_review", "cell_extraction") else payload
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
                halt("model_call_failed", {"status": result.status, "error": result.error})
            if not requested_model or (result.resolved_model != requested_model and not result.requested_model_verified):
                # Output from any model other than the one chosen for this step's role is recorded but never used.
                mismatch = {"requested_model": requested_model, "resolved_model": result.resolved_model}
                self.store.complete_model_step(session, recorded, step["id"], "failed", error_code="model_mismatch", error=mismatch)
                halt("model_mismatch", mismatch)
            output_text = result.raw_text or ""
            if task_type in ("grounded_answer", "cell_extraction"):
                output_text = contracts.resolve_citation_handles(payload, output_text)
            report = contracts.validate_model_output(payload, output_text)
            salvage: list[contracts.Issue] = []
            if (not report.ok and task_type == "grounded_answer" and isinstance(output_text, dict)
                    and after_invalid_output(attempt) == "store_unverified_draft"):
                # The repair did not fix the draft: drop only citations that lack a quote before giving up on it.
                salvaged, salvage = contracts.salvage_answer_draft(payload, json.loads(json.dumps(output_text)))
                retry = contracts.validate_model_output(payload, salvaged) if salvage else report
                if retry.ok:
                    report = retry
                else:
                    salvage = []
            warnings = [vars(w) for w in salvage + report.warnings]
            recorded["validation_json"] = {"ok": report.ok, "issues": [vars(i) for i in report.issues], "warnings": warnings}
            if report.ok:
                if task_type == "grounded_answer":
                    report.result = contracts.name_sources_in_prose(payload, report.result)
                output = {"output_type": report.output_type, "result": report.result,
                          "step_input_id": payload["step_input_id"], "resolved_model": result.resolved_model, "warnings": warnings}
                self.store.complete_model_step(session, recorded, step["id"], "succeeded", output=output)
                return output
            repair_issues = [vars(i) for i in report.issues]
            if after_invalid_output(attempt) == "store_unverified_draft":
                self.store.complete_model_step(session, recorded, step["id"], "failed", output={"step_input_id": payload["step_input_id"]},
                                               error_code="invalid_model_output", error=repair_issues)
                return {"invalid": True, "raw_output": result.raw_text, "issues": repair_issues, "step_input_id": payload["step_input_id"]}
            self.store.finish_model_session(session, **recorded)
        raise AssertionError("unreachable")
