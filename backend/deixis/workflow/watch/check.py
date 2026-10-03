"""Pure watch planning, version identities and observed coverage."""

from datetime import datetime

from deixis.domain.record_identity import ARXIV_DOI_PREFIX, classify_pair, notice_type

WATCH_PER_PAGE = 100
WATCH_PAGES = 2
WATCH_CITING_SOURCES = 10
WATCH_MAX_REQUESTS = 80
WATCH_MAX_RECORDS = 3000
WATCH_RATE_LIMIT_RETRIES = 2
WATCH_DEADLINE_SECONDS = 1800
PARTIAL_REASONS = frozenset({"provider_failed", "not_configured", "quota_deferred", "budget_deferred",
    "deadline_deferred", "outcome_unknown", "coverage_unknown", "coverage_not_reached", "baseline_incomplete",
    "rolled_over", "no_openalex_id", "skipped_not_searchable"})


def caps():
    return {"per_page": WATCH_PER_PAGE, "pages": WATCH_PAGES, "citing_sources": WATCH_CITING_SOURCES,
            "max_provider_requests": WATCH_MAX_REQUESTS, "max_records": WATCH_MAX_RECORDS,
            "rate_limit_retries": WATCH_RATE_LIMIT_RETRIES, "deadline_seconds": WATCH_DEADLINE_SECONDS}


def normalized_doi(value):
    if not isinstance(value, str):
        return None
    value = value.strip().lower()
    for prefix in ("https://doi.org/", "http://doi.org/", "https://dx.doi.org/", "doi:"):
        if value.startswith(prefix):
            value = value[len(prefix):]
    return value or None


def aliases(record):
    provider, native = record["provider"], record["provider_record_id"]
    found = [f"{provider}:{native}"]
    # bioRxiv uses the same OpenAlex record namespace, as the library does.
    if provider == "biorxiv":
        found.append(f"openalex:{native}")
    doi = normalized_doi(record.get("doi"))
    if doi and record.get("merge_by_doi", True) and not doi.startswith(ARXIV_DOI_PREFIX):
        found.append("doi:" + doi)
    for scheme in ("openalex", "pmid", "pmcid"):
        value = record.get("identifiers", {}).get(scheme)
        if isinstance(value, str) and value.strip():
            found.append(f"{scheme}:{value.rstrip('/').rsplit('/', 1)[-1]}")
    return list(dict.fromkeys(found))


def normalize_record(provider, record, retrieved_at, publication_date=None):
    names = ("provider_record_id", "merge_by_doi", "title", "authors", "year", "version_label",
             "publication_type", "abstract", "identifiers", "landing_url")
    result = {name: record[name] for name in names}
    result.update(provider=provider, doi=normalized_doi(record.get("doi")), publication_date=publication_date,
        publication_date_source="openalex.publication_date" if publication_date else "not_returned",
        version_time=None, retrieved_at=retrieved_at)
    result["aliases"] = aliases(result)
    result["relations"] = []
    doi = result["doi"]
    if doi and (not result["merge_by_doi"] or doi.startswith(ARXIV_DOI_PREFIX)):
        result["relations"].append({"relation": "version_family_doi", "doi": doi})
    published = normalized_doi(result["identifiers"].get("published_doi"))
    if published:
        result["relations"].append({"relation": "names_published_doi", "doi": published})
    return result


def identity_uncertain(record):
    return record["aliases"] == [f"{record['provider']}:{record['provider_record_id']}"]


def relation_to(a, b, against, identifier, check_id):
    names = any(r["relation"] == "names_published_doi" and r["doi"] == b.get("doi")
                for r in a.get("relations", [])) or any(
        r["relation"] == "names_published_doi" and r["doi"] == a.get("doi") for r in b.get("relations", []))
    verdict = classify_pair(a, b, names_published_doi=names)
    family_a = {r["doi"] for r in a.get("relations", []) if r["relation"] == "version_family_doi"}
    family_b = {r["doi"] for r in b.get("relations", []) if r["relation"] == "version_family_doi"}
    if verdict is None and family_a & family_b:
        return {"relation": "may_be_version", "against": against, "id": identifier, "title": b["title"],
                "link_kind": "probable_version", "rule": "version_family_doi", "check_id": check_id}
    if verdict is None:
        return None
    relation = verdict.link_kind if verdict.link_kind in ("notice_of", "artifact_of") else "may_be_version"
    return {"relation": relation, "against": against, "id": identifier, "title": b["title"],
            "link_kind": verdict.link_kind, "rule": verdict.rule, "check_id": check_id}


def baseline_origin(unit, record):
    if not unit["baseline"]:
        return None
    if unit.get("continuation"):
        if record["publication_date"] is None:
            return "baseline_undated"
        if record["publication_date"] > unit["cut"][:10]:
            return None
    return "baseline"


def citing_roll(units, baseline, position, limit=WATCH_CITING_SOURCES):
    readable = [u for u in units if u.get("openalex_id")]
    if not readable:
        return [], 0, 0
    position %= len(readable)
    partial = [u for u in readable if baseline.get(u["unit_key"], {}).get("state") == "partial"]
    rolled = readable[position:] + readable[:position]
    chosen = []
    next_position = position
    for unit in partial + rolled:
        if any(u["unit_key"] == unit["unit_key"] for u in chosen):
            continue
        if len(chosen) == limit:
            break
        chosen.append(unit)
    roll_chosen = [u for u in rolled if u in chosen and u not in partial]
    if roll_chosen:
        next_position = (readable.index(roll_chosen[-1]) + 1) % len(readable)
    return chosen, len(readable) - len(chosen), next_position


def unit_plan(units, baseline, requested_to):
    result = []
    for unit in units:
        unit = dict(unit)
        saved = baseline.get(unit["unit_key"], {})
        restart = bool(saved.get("state") == "partial" and
            (saved.get("contract_id"), saved.get("adapter_revision")) !=
            (unit["contract_id"], unit["adapter_revision"]))
        continuation = saved.get("state") == "partial" and not restart
        is_baseline = saved.get("state", "pending") != "complete"
        unit.update(baseline=is_baseline, continuation=continuation,
            cut=saved.get("cut") if continuation else requested_to,
            cursor=saved.get("cursor") if continuation else unit["first_cursor"],
            pages_read=saved.get("pages_read", 0) if continuation else 0,
            page_size=saved.get("page_size", unit["page_size"]),
            requested_from=saved.get("success_boundary") if not is_baseline else None,
            requested_to=requested_to, baseline_restarted="adapter_revision_changed" if restart else None)
        result.append(unit)
    return result


def coverage(unit, observed):
    if unit["baseline"]:
        return "baseline_complete" if observed["finished"] else "baseline_incomplete"
    if not unit["date_sorted"]:
        return "coverage_unknown"
    if observed["exhausted"] or (observed["oldest_publication_date"] and unit["requested_from"] and
            observed["oldest_publication_date"] <= unit["requested_from"][:10]):
        return "covered"
    return "coverage_not_reached"


def check_state(run, check):
    unknown = bool(check.get("outcome_unknown"))
    state = run["status"]
    reasons = list(check.get("partial_reasons", []))
    if state == "completed":
        state = "partial" if reasons else "succeeded"
    return {"state": state, "pause_reason": run.get("pause_reason"),
        "failure_reason": ((run.get("error") or {}).get("code") or run.get("pause_reason")) if state == "failed" else None,
        "outcome_unknown": unknown,
        "partial_reasons": reasons}


def deadline_passed(current, deadline):
    return datetime.fromisoformat(current) >= datetime.fromisoformat(deadline)
