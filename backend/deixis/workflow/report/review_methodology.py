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


def render_review_methodology(numbers: dict[str, Any], language: str, *, providers: str, queries: str,
                              compiler_versions: str, screening_models: str,
                              screening_criteria: str, chain_provenance: str) -> str:
    return _TEMPLATES["tr" if language.startswith("tr") else "en"].format(
        **numbers["corpus"], full_text_ratio=numbers["full_text_ratio"],
        fetch_pdf=numbers["fetch_pdf"], pdf_other_copy=numbers["pdf_other_copy"],
        providers=providers, queries=queries, compiler_versions=compiler_versions,
        screening_models=screening_models, screening_criteria=screening_criteria,
    ) + chain_provenance


def render_limitations(numbers: dict[str, Any], language: str) -> str:
    del language  # Item text was frozen in the report language with the numbers.
    return " ".join(f"{item['number']}. {item['text']}" for item in numbers["items"])


def limitations_core(store: Store, reports: ReportStore, report_id: str,
                     snapshot: dict[str, Any]) -> dict[str, Any]:
    corpus = dict(snapshot["corpus"])
    included, full_text = corpus["included"], corpus["full_text"]
    sections = {section["section_id"]: section for section in reports.sections(report_id)
                if section["section_id"] in ("III", "IV", "V", "VI", "VII")}
    valid_ids = [section["id"] for section in sections.values() if section["status"] == "valid"]
    counts = {"analyst_inference": 0, "total": 0, "share": None}
    if valid_ids:
        marks = ",".join("?" for _ in valid_ids)
        for row in store.conn.execute(
            f"SELECT support_type, COUNT(*) AS n FROM report_claims WHERE report_section_id IN ({marks})"
            " GROUP BY support_type", valid_ids,
        ):
            counts["total"] += row["n"]
            if row["support_type"] == "analyst_inference":
                counts["analyst_inference"] = row["n"]
    if counts["total"]:
        counts["share"] = counts["analyst_inference"] / counts["total"]

    latest = {}
    for row in store.conn.execute(
        "SELECT section_id, sentence_id, outcome FROM report_phrase_repairs WHERE report_id = ?"
        " AND section_id IN ('III','IV','V','VI','VII') ORDER BY rowid", (report_id,),
    ):
        latest[(row["section_id"], row["sentence_id"])] = row["outcome"]
    repairs = {"repaired": 0, "reverted_exception": 0, "unframed_exception": 0}
    for outcome in latest.values():
        repairs["repaired" if outcome == "kept" else outcome] += 1

    by_section = {}
    for section_id in ("III", "IV", "V", "VI", "VII"):
        section = sections.get(section_id)
        kinds = {"passage": 0, "cell": 0, "cell_missing_evidence": 0}
        for record in ((section or {}).get("validation") or {}).get("truncated", []):
            if record["record_kind"] in kinds:
                kinds[record["record_kind"]] += 1
        if any(kinds.values()):
            by_section[section_id] = kinds
    truncation = {
        "budget_cut": sum(k["passage"] + k["cell"] for k in by_section.values()),
        "missing_evidence": sum(k["cell_missing_evidence"] for k in by_section.values()),
        "by_section": by_section,
    }
    report = reports.report(report_id)
    language = (report["language"] or store.scope(report["research_id"], report["scope_revision"])
                .get("language_hint") or "en").lower()
    tr = language.startswith("tr")
    share = (included - full_text) / included if included else 0.0
    section_cuts = ", ".join(
        (f"{key}: {value['passage']} pasaj, {value['cell']} hücre, "
         f"{value['cell_missing_evidence']} eksik kanıt" if tr else
         f"{key}: {value['passage']} passage, {value['cell']} cell, {value['cell_missing_evidence']} missing")
        for key, value in by_section.items()
    ) or ("yok" if tr else "none")
    texts = (
        [
            "Bilinen bir kaynak kümesiyle geri çağırma ölçümü yapılmadı.",
            f"Dondurulmuş korpusta {corpus['found']} bulunan, {corpus['unique']} tekil, "
            f"{corpus['screened']} taranan, {included} dahil kaynak vardı; {included} dahil kaynağın "
            f"{full_text} tanesinde tam metin vardı ve açık erişim kaynaklara yönelme olasılığı vardır.",
            f"{included} dahil kaynağın {included - full_text} tanesinde PDF metni yoktu ({share:.1%}).",
            f"Geçerli III–VII bölümlerindeki {counts['total']} iddianın {counts['analyst_inference']} tanesi "
            f"analist çıkarımıydı ({counts['share']:.1%})." if counts["share"] is not None else
            "Geçerli III–VII bölümlerinde payı hesaplanacak iddia yoktu.",
            "Araştırma boşluğu için kill-search çalıştırılmadı.",
            f"VIII yazılmadan önceki cümle onarımları: {repairs['repaired']} korundu, "
            f"{repairs['reverted_exception']} geri alındı, {repairs['unframed_exception']} kalıpsız kaldı.",
            f"Bütçe nedeniyle {truncation['budget_cut']} kayıt kesildi; {truncation['missing_evidence']} hücrenin "
            f"kanıt pasajı bulunamadı (bölümler: {section_cuts}).",
        ] if tr else [
            "Recall was not measured against a known source set.",
            f"The frozen corpus had {corpus['found']} found, {corpus['unique']} unique, "
            f"{corpus['screened']} screened, and {included} included sources; full text was available "
            f"for {full_text}/{included} included sources and may favor open access sources.",
            f"{included - full_text} of {included} included sources had no PDF text ({share:.1%}).",
            f"In valid sections III–VII, {counts['analyst_inference']} of {counts['total']} claims were analyst "
            f"inferences ({counts['share']:.1%})." if counts["share"] is not None else
            "No claims in valid sections III–VII were available for an inference share.",
            "A kill search for research gaps was not run.",
            f"Before VIII was written, phrase repairs kept {repairs['repaired']}, reverted "
            f"{repairs['reverted_exception']}, and left {repairs['unframed_exception']} unframed.",
            f"{truncation['budget_cut']} records were cut for the budget; a cell's evidence passage was not found "
            f"for {truncation['missing_evidence']} cells (by section: {section_cuts}).",
        ]
    )
    keys = ("recall_measurement", "open_access_bias_note", "no_full_text_share", "analyst_inference_share",
            "kill_search_status", "phrase_repair_exceptions", "truncation")
    return {"version": 1, "kind": "limitations", "as_of": "before_viii", "corpus": corpus,
            "recall_measurement": None, "open_access_bias_note": True, "included": included,
            "full_text": full_text, "no_full_text_share": share,
            "analyst_inference_share": counts, "kill_search_status": "not_run",
            "phrase_repair_exceptions": repairs, "truncation": truncation,
            "items": [{"number": i, "key": key, "text": sentence}
                      for i, (key, sentence) in enumerate(zip(keys, texts), 1)]}


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
    numbers = {"version": 1, "kind": "review_methodology", "corpus": dict(corpus),
               "full_text_ratio": corpus["full_text"] / included if included else 0.0,
               "fetch_pdf": sum(step["kind"] == "fetch_pdf" for step in steps),
               "pdf_other_copy": sum(step["kind"] == "pdf_other_copy" for step in steps)}
    text = render_review_methodology(
        numbers, language, providers=providers, queries=queries, compiler_versions=compiler_versions,
        screening_models=screening_models, screening_criteria=screening_criteria,
        chain_provenance=_chain_provenance(steps, language),
    )
    section_id = reports.create_section(report_id, "II", 2)
    reports.save_section_draft(
        section_id, None, "valid", {"text": text}, {"ok": True, "issues": [], "numbers": numbers}, len(text.split())
    )
