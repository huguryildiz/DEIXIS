"""Execution of discovery and answer runs.

Discovery: search plan (model) → OpenAlex searches → screening proposal (model).
Answer: fetch accessible PDFs for included sources → text retrieval → grounded answer (model).
Completed steps are skipped on resume. A connection or provider failure pauses the
run with its reason; nothing is silently substituted.
"""

from __future__ import annotations

import asyncio
import hashlib
import json
import re
from dataclasses import dataclass
from typing import Any, Awaitable, Callable

import httpx

from deixis.config import Settings
from deixis.documents import fetch as fetch_module
from deixis.documents import pdf
from deixis.domain import contracts
from deixis.domain.rules import MAX_SCHEMA_REPAIRS, MAX_TRANSIENT_NETWORK_RETRIES, after_invalid_output
from deixis.domain.skill import RUNTIME_FILES, SkillPackage
from deixis.models import prompt
from deixis.models.adapter import ModelAdapter
from deixis.providers import openalex
from deixis.storage.db import dumps, new_id, now
from deixis.workflow.store import Store

CAPABILITIES = {
    "supported_tasks": ["search_plan", "screening", "grounded_answer"],
    "unsupported_tasks": ["synthesis", "candidate_development", "claim_check", "experiment"],
}
MAX_DOWNLOADS_PER_RUN = 8
MAX_ABSTRACT_CHARS = 2500
STOPWORDS = set(
    "the and for with what which how are was were from that this into about does using used use their there have has "
    "not but can our its them they than then also between within over under nasıl nedir neler olan için ile gibi veya "
    "ve bir bu şu hangi mı mi mu mü midir var yok daha çok".split()
)


class RunStopped(Exception):
    """The run ended early (pause, cancel or recorded failure); state is already persisted."""


@dataclass
class FlowDeps:
    settings: Settings
    store: Store
    adapters: dict[str, ModelAdapter]
    package: SkillPackage
    http: httpx.AsyncClient
    fetch_pdf: Callable[[str], Awaitable[fetch_module.FetchResult]] = fetch_module.fetch_pdf


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
            else:
                await self._answer(run, scope)
        except RunStopped:
            return
        if self.store.run(run_id)["status"] == "running":
            self.store.update_run(run_id, event="run_completed", status="completed", pause_reason=None)

    # ---- run control ---------------------------------------------------------------
    def _checkpoint(self, run_id: str) -> None:
        status = self.store.run(run_id)["status"]
        if status == "pause_requested":
            self.store.update_run(run_id, event="run_paused", status="paused", pause_reason="user_requested")
            raise RunStopped
        if status == "cancelled":
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
        run_id, rid = run["id"], run["research_id"]
        if scope["source_scope"] == "attached":
            return
        self._checkpoint(run_id)
        output = await self._model_step(run, scope, "search_plan", "search_plan")
        if output.get("invalid"):
            self._fail(run_id, "invalid_model_output", {"step": "search_plan", "issues": output["issues"]})
        if output["output_type"] == "ClarificationRequest":
            self.store.save_answer(rid, run_id, None, output["step_input_id"], run["scope_revision"], "clarification",
                                   output["result"], {"ok": True, "issues": []})
            return
        plan = output["result"]
        budget = run["budget"]
        queries = [q for q in plan["queries"] if q["provider_id"] in scope["providers"]][: budget["max_provider_requests"]]
        per_query = max(5, min(25, budget["max_candidates"] // max(1, len(queries))))
        for index, query in enumerate(queries):
            self._checkpoint(run_id)
            await self._search(run, index, query, per_query)

        self._checkpoint(run_id)
        self.store.update_run(run_id, stage="screening")
        candidates = [c for c in self.store.candidates(rid)[: budget["max_candidates"]] if c["origin"] != "user"]
        if not candidates:
            return
        output = await self._model_step(run, scope, "screening", "screening", candidate_rows=candidates)
        if output.get("invalid"):
            self._fail(run_id, "invalid_model_output", {"step": "screening", "issues": output["issues"]})
        by_candidate = {c["candidate_id"]: c["source_version_id"] for c in candidates}
        step = self.store.step(run_id, "screening", "model:screening")
        for decision in output["result"]["decisions"]:
            self.store.apply_screening_proposal(
                rid, by_candidate[decision["candidate_id"]], decision["proposal"], decision["reason"],
                decision["evidence_basis"], step["id"],
            )

    async def _search(self, run: dict[str, Any], index: int, query: dict[str, Any], per_query: int) -> None:
        run_id, rid = run["id"], run["research_id"]
        step = self.store.step(run_id, f"search:{index}", "provider_search:openalex")
        if step["status"] == "succeeded":
            return
        if self.store.run(run_id)["usage"].get("provider_requests", 0) >= run["budget"]["max_provider_requests"] + MAX_TRANSIENT_NETWORK_RETRIES:
            self._pause(run_id, "budget_exhausted", {"limit": "provider_requests"})
        self.store.start_step(step["id"])
        settings = self.deps.settings
        attempts = 0
        while True:
            self.store.add_usage(run_id, "provider_requests")
            outcome = await openalex.search_works(
                self.deps.http, query["query_text"], per_query, settings.openalex_api_key, settings.contact_email
            )
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
        search_run_id = self.store.add_search_run(
            research_id=rid, run_id=run_id, step_id=step["id"], provider=openalex.PROVIDER_ID,
            query_text=query["query_text"], request_description=outcome.request_description,
            access_mode=outcome.access_mode, status=outcome.status, delivery_class=outcome.delivery_class,
            result_count=len(outcome.records), provider_total=outcome.provider_total, page_limit=per_query,
            error_json=dumps({"error": outcome.error, "http_status": outcome.http_status, "rate_limit": outcome.rate_limit}),
            raw_payload_path=payload_path,
        )
        for rank, record in enumerate(outcome.records):
            svid, _ = self.store.upsert_provider_source(openalex.PROVIDER_ID, record, payload_path)
            self.store.add_to_corpus(rid, svid, "search", search_run_id, rank)
        if outcome.status in ("completed", "zero_results"):
            self.store.finish_step(step["id"], "succeeded", output={"search_run_id": search_run_id, "status": outcome.status,
                                                                    "result_count": len(outcome.records)})
            return
        final = "outcome_unknown" if outcome.delivery_class == "after_send_unknown" else "failed"
        self.store.finish_step(step["id"], final, error_code=outcome.status,
                               error={"error": outcome.error, "http_status": outcome.http_status}, delivery_class=outcome.delivery_class)
        self._pause(run_id, f"provider_{outcome.status}", {"provider": "openalex", "http_status": outcome.http_status,
                                                          "retry_after": outcome.rate_limit.get("retry-after")})

    # ---- answer ---------------------------------------------------------------------
    async def _answer(self, run: dict[str, Any], scope: dict[str, Any]) -> None:
        run_id, rid = run["id"], run["research_id"]
        included = self.store.included_sources(rid)
        if not included:
            self._fail(run_id, "no_included_sources")
        self.store.update_run(run_id, stage="inspection")
        downloads = 0
        for svid in included:
            self._checkpoint(run_id)
            source = self.store.source(svid)
            # A PDF from a different version (e.g. a submitted manuscript for a published record) is not attached.
            same_version = source["oa_pdf_version"] is not None and source["oa_pdf_version"] == source["version_label"]
            if (source["origin"] == "provider" and source["oa_pdf_url"] and same_version and not self.store.has_asset(svid)
                    and downloads < MAX_DOWNLOADS_PER_RUN):
                downloads += 1
                await self._fetch_pdf(run, source)

        self._checkpoint(run_id)
        self.store.update_run(run_id, stage="answer")
        passages = self._retrieve(rid, scope, included, run["budget"]["max_answer_passages"])
        if not passages:
            self.store.save_answer(rid, run_id, None, None, run["scope_revision"], "no_evidence", None,
                                   {"ok": True, "issues": [], "note": "No accessible passages for the included sources."})
            return
        source_ids = list(dict.fromkeys(p["source_version_id"] for p in passages))
        output = await self._model_step(run, scope, "grounded_answer", "grounded_answer", source_ids=source_ids, passage_rows=passages)
        step = self.store.step(run_id, "grounded_answer", "model:grounded_answer")
        if output.get("invalid"):
            try:
                draft = json.loads(output["raw_output"] or "")
                draft = draft if isinstance(draft, dict) else None
            except json.JSONDecodeError:
                draft = None
            self.store.save_answer(rid, run_id, step["id"], output["step_input_id"], run["scope_revision"], "unverified_draft",
                                   draft, {"ok": False, "issues": output["issues"]})
            return
        payload = self.store.step_input_payload(output["step_input_id"])
        links = contracts.derive_evidence_links(payload, output["result"])
        self.store.save_answer(rid, run_id, step["id"], output["step_input_id"], run["scope_revision"], "structurally_valid",
                               output["result"], {"ok": True, "issues": []}, links)

    async def _fetch_pdf(self, run: dict[str, Any], source: dict[str, Any]) -> None:
        step = self.store.step(run["id"], f"fetch:{source['id']}", "fetch_pdf")
        if step["status"] in ("succeeded", "failed"):
            return
        self.store.start_step(step["id"])
        self.store.add_usage(run["id"], "downloads")
        result = await self.deps.fetch_pdf(source["oa_pdf_url"])
        if result.status != "ok":
            self.store.finish_step(step["id"], "failed", error_code=f"fetch_{result.status}",
                                   error={"http_status": result.http_status, "error": result.error})
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
                                                          "page_count": extraction.page_count},
                               error_code=None if status == "succeeded" else f"extraction_{extraction.status}")

    def _retrieve(self, research_id: str, scope: dict[str, Any], included: list[str], limit: int) -> list[dict[str, Any]]:
        terms = [t for t in re.findall(r"\w+", scope["question"].lower()) if len(t) > 2 and t not in STOPWORDS]
        plan = self.store.latest_step_output(research_id, "search_plan")
        if plan and plan.get("output_type") == "SearchPlan":
            for concept in plan["result"]["concepts"]:
                for phrase in [concept["label"], *concept["synonyms"]]:
                    terms += [t for t in re.findall(r"\w+", phrase.lower()) if len(t) > 2 and t not in STOPWORDS]
        unique_terms = list(dict.fromkeys(terms))[:40]
        fts = " OR ".join(f'"{t}"' for t in unique_terms)
        selected: dict[str, dict[str, Any]] = {}
        per_source = {svid: self.store.passages_for(svid) for svid in included}
        for svid in included:
            for p in per_source[svid]:
                if p["kind"] == "abstract" and len(selected) < max(1, limit // 2):
                    selected[p["id"]] = p
        for p in self.store.search_passages(included, fts, limit * 2):
            if len(selected) >= limit:
                break
            selected.setdefault(p["id"], p)
        for svid in included:
            if len(selected) >= limit:
                break
            if not any(p["source_version_id"] == svid for p in selected.values()):
                for p in per_source[svid][:2]:
                    selected.setdefault(p["id"], p)
        return list(selected.values())[:limit]

    # ---- model steps -------------------------------------------------------------------
    def _step_input(self, run: dict[str, Any], scope: dict[str, Any], step_id: str, task_type: str,
                    candidate_rows: list[dict[str, Any]], source_ids: list[str], passage_rows: list[dict[str, Any]]) -> dict[str, Any]:
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
            access = "pdf_available" if "pdf_page" in kinds else "abstract" if "abstract" in kinds else "metadata"
            sources.append({"source_id": svid, "work_id": source["work_id"], "title": source["title"], "year": source["year"],
                            "version_label": source["version_label"], "access_level": access})
        passages = [{
            "passage_id": p["id"], "source_id": p["source_version_id"],
            "reading_depth": "abstract" if p["kind"] == "abstract" else "selected_sections",
            "locator": {"kind": p["kind"], "physical_page": p["physical_page"], "printed_label": p["printed_label"]},
            "abstract_origin": p["abstract_origin"], "text": p["text"],
        } for p in passage_rows]
        language = scope["language_hint"] if scope["language_hint"] and re.fullmatch(r"[a-z]{2,3}(-[A-Za-z0-9]{2,8})*", scope["language_hint"]) else None
        return {
            "step_input_id": new_id("sti"), "research_id": run["research_id"], "run_id": run["id"], "step_id": step_id,
            "task_type": task_type, "scope_revision": run["scope_revision"],
            "skill_package_hash": self.deps.package.package_hash, "skill_files": list(RUNTIME_FILES[task_type]),
            "output_schema_versions": [contracts.SCHEMA_VERSIONS[o] for o in contracts.TASK_OUTPUTS[task_type]],
            "question": {"text": scope["question"], "language_hint": language},
            "user_steering": [scope["steering"]] if scope.get("steering") else [],
            "capabilities": CAPABILITIES, "enabled_providers": scope["providers"],
            "candidates": candidates, "sources": sources, "passages": passages,
            "allowlist": {"candidate_ids": [c["candidate_id"] for c in candidates], "source_ids": [s["source_id"] for s in sources],
                          "passage_ids": [p["passage_id"] for p in passages]},
            "human_corrections": [],
            "budget": {"max_model_calls": run["budget"]["max_model_calls"], "max_schema_repairs": MAX_SCHEMA_REPAIRS,
                       "max_provider_requests": run["budget"]["max_provider_requests"]},
            "model": {"connection": scope["model_connection"], "requested_model": scope["requested_model"]},
            "created_at": now(),
        }

    async def _model_step(self, run: dict[str, Any], scope: dict[str, Any], operation_key: str, task_type: str,
                          candidate_rows: list[dict[str, Any]] | None = None, source_ids: list[str] | None = None,
                          passage_rows: list[dict[str, Any]] | None = None) -> dict[str, Any]:
        run_id, rid = run["id"], run["research_id"]
        step = self.store.step(run_id, operation_key, f"model:{task_type}")
        if step["status"] == "succeeded":
            return step["output"]
        adapter = self.deps.adapters.get(scope["model_connection"])
        if adapter is None:
            self._pause(run_id, "model_connection_unavailable", {"connection": scope["model_connection"]})
        health = await adapter.health()
        if not health.get("ready"):
            self._pause(run_id, "model_connection_not_ready", {"connection": scope["model_connection"], "reason": health.get("reason")})
        self.store.start_step(step["id"])
        repair_issues: list[dict[str, Any]] | None = None
        for attempt in range(MAX_SCHEMA_REPAIRS + 1):
            if self.store.run(run_id)["usage"].get("model_calls", 0) >= run["budget"]["max_model_calls"]:
                self.store.finish_step(step["id"], "failed", error_code="budget_exhausted")
                self._pause(run_id, "budget_exhausted", {"limit": "model_calls"})
            payload = self._step_input(run, scope, step["id"], task_type, candidate_rows or [], source_ids or [], passage_rows or [])
            if issues := contracts.check_step_input(payload):
                self.store.finish_step(step["id"], "failed", error_code="step_input_invalid", error=[vars(i) for i in issues])
                self._fail(run_id, "step_input_invalid")
            schema = contracts.step_output_schema(task_type)
            base = prompt.BASE_INSTRUCTIONS
            developer = prompt.developer_instructions(self.deps.package, task_type)
            message = prompt.step_message(payload) if repair_issues is None else prompt.repair_message(payload, repair_issues)
            self.store.insert_step_input(step["id"], rid, run_id, attempt, payload, base, developer, message, schema)
            session = self.store.start_model_session(rid, run_id, step["id"], payload["step_input_id"],
                                                     scope["model_connection"], scope["requested_model"])
            result = await adapter.run_step(base, developer, message, schema, scope["requested_model"])
            report = contracts.validate_model_output(payload, result.raw_text or "") if result.status == "completed" else None
            self.store.finish_model_session(
                session, status=result.status, resolved_model=result.resolved_model, external_thread_id=result.external_thread_id,
                raw_output=result.raw_text, token_usage_json=result.token_usage, tool_item_types_json=result.tool_item_types,
                validation_json={"ok": report.ok, "issues": [vars(i) for i in report.issues]} if report else None,
            )
            if result.status == "isolation_violation" or result.tool_item_types:
                self.store.finish_step(step["id"], "failed", error_code="model_isolation_violation",
                                       error={"tool_item_types": result.tool_item_types, "error": result.error})
                self._pause(run_id, "model_isolation_violation", {"tool_item_types": result.tool_item_types, "error": result.error})
            if result.status != "completed":
                final = "outcome_unknown" if result.delivery_class == "after_send_unknown" else "failed"
                self.store.finish_step(step["id"], final, error_code=f"model_{result.status}", error=result.error,
                                       delivery_class=result.delivery_class)
                self._checkpoint(run_id)
                self._pause(run_id, "model_call_failed", {"status": result.status, "error": result.error})
            if report.ok:
                output = {"output_type": report.output_type, "result": report.result,
                          "step_input_id": payload["step_input_id"], "resolved_model": result.resolved_model}
                self.store.finish_step(step["id"], "succeeded", output=output)
                return output
            repair_issues = [vars(i) for i in report.issues]
            if after_invalid_output(attempt) == "store_unverified_draft":
                self.store.finish_step(step["id"], "failed", output={"step_input_id": payload["step_input_id"]},
                                       error_code="invalid_model_output", error=repair_issues)
                return {"invalid": True, "raw_output": result.raw_text, "issues": repair_issues, "step_input_id": payload["step_input_id"]}
        raise AssertionError("unreachable")
