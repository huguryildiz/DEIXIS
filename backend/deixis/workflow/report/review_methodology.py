"""Write Review Methodology from immutable workflow records and the frozen corpus snapshot."""

from __future__ import annotations

import json
from typing import Any

from deixis.providers.registry import CONNECTORS
from deixis.workflow.report.store import ReportStore
from deixis.workflow.store import Store


_TEMPLATES = {
    "en": (
        "The recorded search used {providers}: {queries}; the compiled query version was {compiler_versions}. "
        "The frozen corpus contained {found} found, {unique} unique, {screened} screened, and {included} included "
        "sources; PDF acquisition recorded {fetch_pdf} direct-fetch and {pdf_other_copy} other-copy steps, full text "
        "was available for {full_text}/{included} included sources ({full_text_ratio:.1%}), and screening used "
        "{screening_models} with {screening_criteria}."
    ),
    "tr": (
        "Kayıtlı arama {providers} sağlayıcılarını kullandı: {queries}; derlenmiş sorgu sürümü "
        "{compiler_versions} idi. Dondurulmuş korpus {found} bulunan, {unique} tekil, {screened} taranan ve "
        "{included} dahil kaynaktan oluştu; PDF ediniminde {fetch_pdf} doğrudan indirme ve {pdf_other_copy} diğer "
        "kopya adımı kaydedildi, {included} dahil kaynağın {full_text} tanesinde tam metin vardı "
        "({full_text_ratio:.1%}) ve tarama {screening_criteria} ile {screening_models} modelini kullandı."
    ),
}


# Citation searching (PRISMA-S item 5), written only when a discovery run of this revision chained citations (D95).
_CHAIN_TEMPLATES = {
    "en": (" Citation searching followed the references and the citing works of {seeds} seed works in OpenAlex: "
           "{requests} requests ({failed} did not complete), {new_works} new works kept by the gate-term filter, "
           "{read} of them read at the abstract stage."),
    "tr": (" Atıf taraması {seeds} tohum eserin referanslarını ve onlara atıf yapan eserleri OpenAlex'te izledi: "
           "{requests} istek ({failed} tamamlanmadı), kapı terimi süzgecinin tuttuğu {new_works} yeni eser, bunların "
           "{read} tanesi özet aşamasında okundu."),
}


def _chain_provenance(steps: list[dict[str, Any]], language: str) -> str:
    summaries = [step["output"] for step in steps
                 if step["kind"] == "code:chain_summary" and step["status"] == "succeeded" and step["output"]]
    if not summaries:
        return ""
    total = {"seeds": sum(sum((out.get("seeds") or {}).get(key, 0) for key in ("code", "user")) for out in summaries),
             "requests": sum((out.get("requests") or {}).get("sent", 0) for out in summaries),
             "failed": sum((out.get("requests") or {}).get("failed", 0) for out in summaries),
             "new_works": sum(out.get("new_works", 0) for out in summaries),
             "read": sum(out.get("read_by_model", 0) for out in summaries)}
    return _CHAIN_TEMPLATES["tr" if language.startswith("tr") else "en"].format(**total)


def _all_steps(store: Store, research_id: str, scope_revision: int) -> list[dict[str, Any]]:
    run_ids = [row["id"] for row in store.conn.execute(
        "SELECT id FROM runs WHERE research_id = ? AND scope_revision = ? ORDER BY created_at, id",
        (research_id, scope_revision),
    )]
    return [step | {"run_id": run_id} for run_id in run_ids for step in store.run_steps(run_id)]


def _search_provenance(store: Store, research_id: str, scope_revision: int) -> tuple[str, str, str]:
    discovery_runs = [row["id"] for row in store.conn.execute(
        "SELECT id FROM runs WHERE research_id = ? AND scope_revision = ? AND kind = 'discovery'"
        " ORDER BY created_at, id", (research_id, scope_revision),
    )]
    steps = [step for run_id in discovery_runs for step in store.run_steps(run_id)]
    search_step_ids = [step["id"] for step in steps if step["kind"].startswith("provider_search:")]
    searches = []
    if search_step_ids:
        marks = ",".join("?" for _ in search_step_ids)
        searches = list(store.conn.execute(
            f"SELECT provider, query_text, retrieved_at FROM search_runs WHERE step_id IN ({marks})"
            " ORDER BY retrieved_at, id", search_step_ids,
        ))
    recorded = {row["provider"] for row in searches}
    providers = [provider for provider in CONNECTORS if provider in recorded]
    providers.extend(sorted(recorded - set(CONNECTORS)))
    query_text = "; ".join(
        f"{row['provider']} — {row['query_text']} ({row['retrieved_at'][:10]})" for row in searches
    ) or "none recorded"

    versions = []
    if discovery_runs:
        marks = ",".join("?" for _ in discovery_runs)
        for row in store.conn.execute(
            f"SELECT output_json FROM run_steps WHERE run_id IN ({marks}) AND operation_key = 'search_plan'"
            " AND output_json IS NOT NULL ORDER BY rowid", discovery_runs,
        ):
            version = json.loads(row["output_json"]).get("query_compiler")
            if version and version not in versions:
                versions.append(version)
    return ", ".join(providers) or "none recorded", query_text, ", ".join(versions) or "not recorded"


def _screening_provenance(store: Store, research_id: str, scope_revision: int) -> tuple[str, str]:
    payloads = [json.loads(row["payload_json"]) for row in store.conn.execute(
        "SELECT payload_json FROM step_inputs WHERE research_id = ? AND scope_revision = ?"
        " AND task_type = 'screening' ORDER BY created_at, id", (research_id, scope_revision),
    )]
    models, criteria = [], []
    for payload in payloads:
        model = payload.get("model", {})
        identity = model.get("requested_model") or model.get("connection")
        if identity and identity not in models:
            models.append(identity)
        supported = payload.get("capabilities", {}).get("supported_tasks", [])
        limit = payload.get("budget", {}).get("max_model_calls")
        criterion = f"screening capability; max_model_calls={limit}" if "screening" in supported \
            else f"recorded screening input; max_model_calls={limit}"
        if criterion not in criteria:
            criteria.append(criterion)
    return ", ".join(models) or "not recorded", ", ".join(criteria) or "no screening input recorded"


def write_review_methodology(store: Store, reports: ReportStore, report_id: str, research_id: str,
                             snapshot: dict[str, Any]) -> None:
    """Persist Section II without a model step; all corpus counts come from the supplied frozen snapshot."""
    report = reports.report(report_id)
    if report["research_id"] != research_id:
        raise ValueError("The report and research do not match")
    scope_revision = report["scope_revision"]
    providers, queries, compiler_versions = _search_provenance(store, research_id, scope_revision)
    steps = _all_steps(store, research_id, scope_revision)
    screening_models, screening_criteria = _screening_provenance(store, research_id, scope_revision)
    corpus = snapshot["corpus"]
    included = corpus["included"]
    language = (report["language"] or store.scope(research_id, scope_revision).get("language_hint") or "en").lower()
    template = _TEMPLATES["tr" if language.startswith("tr") else "en"]
    text = template.format(
        providers=providers,
        queries=queries,
        compiler_versions=compiler_versions,
        found=corpus["found"],
        unique=corpus["unique"],
        screened=corpus["screened"],
        included=included,
        fetch_pdf=sum(step["kind"] == "fetch_pdf" for step in steps),
        pdf_other_copy=sum(step["kind"] == "pdf_other_copy" for step in steps),
        full_text=corpus["full_text"],
        full_text_ratio=corpus["full_text"] / included if included else 0.0,
        screening_models=screening_models,
        screening_criteria=screening_criteria,
    ) + _chain_provenance(steps, language)
    section_id = reports.create_section(report_id, "II", 2)
    reports.save_section_draft(
        section_id, None, "valid", {"text": text}, {"ok": True, "issues": []}, len(text.split())
    )
