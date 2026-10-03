"""Sequential provider reads through an HTTP gate; publication belongs to WatchStore."""

import asyncio
from contextlib import asynccontextmanager
from dataclasses import asdict, dataclass
import hashlib
import json

import httpx

from deixis.domain import canonical
from deixis.domain.rules import MAX_TRANSIENT_NETWORK_RETRIES
from deixis.providers import facade, openalex, registry
from deixis.providers.common import SearchOutcome
from deixis.storage.db import now
from . import check as policy


class WatchSendRefused(httpx.ConnectError):
    """A watch gate refused delivery; common.send classifies it as before_send."""


@dataclass
class Callbacks:
    gate: object
    run: object
    add_usage: object
    step: object
    existing_step: object
    start_step: object
    send: object
    host_gate: object
    headers: object = None
    clock: object = None
    sleep: object = asyncio.sleep

    def __post_init__(self):
        if self.clock is None:
            self.clock = now


class GatedTransport(httpx.AsyncBaseTransport):
    def __init__(self, callbacks, config):
        self.callbacks, self.config, self.reason, self.sent = callbacks, config, None, 0

    async def handle_async_request(self, request):
        reason = self.callbacks.gate()
        run = self.callbacks.run()
        if reason is None and run["usage"].get("provider_requests", 0) >= run["budget"]["max_provider_requests"]:
            reason = "deferred_budget"
        if reason is None and policy.deadline_passed(self.callbacks.clock(), self.config["deadline_at"]):
            reason = "deferred_deadline"
        if reason:
            self.reason = reason
            raise WatchSendRefused(reason, request=request)
        self.callbacks.add_usage("provider_requests", 1)
        self.sent += 1
        return await self.callbacks.send(request)


@asynccontextmanager
async def no_gate():
    yield


def observations(config, rows):
    observed = {"units": {}, "partial_reasons": [], "rolled_over": config["rolled_over"],
                "rolled_over_units": config["rolled_over_units"],
                "skipped_units": config["skipped_units"]}
    statuses = {}
    quota = set()
    deferred = None
    for unit in config["units"]:
        key, provider = unit["unit_key"], unit["provider_id"]
        reads = [r for r in rows if r["unit_key"] == key]
        successes = [r for r in reads if r["status"] in ("completed", "zero_results")]
        dates = [r["oldest_publication_date"] for r in successes if r["oldest_publication_date"]]
        newest = [r["newest_publication_date"] for r in successes if r["newest_publication_date"]]
        exhausted = bool(successes and successes[-1]["next_cursor"] is None)
        remaining = config["caps"]["pages"] - unit["pages_read"] if unit["baseline"] else config["caps"]["pages"]
        finished = bool(successes and len(successes) == len(reads) and (exhausted or len(successes) >= remaining))
        state = unit["status"]
        if reads:
            state = "completed" if finished else reads[-1]["status"]
            if not finished and state in ("completed", "zero_results"):
                state = "baseline_incomplete" if unit["baseline"] else "coverage_not_reached"
            if any(r["error_kind"] == "quota_exhausted" for r in reads):
                quota.add(provider)
            if state in ("deferred_budget", "deferred_deadline"):
                deferred = state
        elif state == "ready":
            state = deferred or ("quota_deferred" if provider in quota else "outcome_unknown")
        obs = {"pages_read": len(successes), "pages_answered": len(reads), "exhausted": exhausted,
            "cut_by_cap": bool(finished and not exhausted), "sort_sent": next((json.loads(r["connector_json"]).get("sort_sent")
                for r in reads if r["connector_json"] and json.loads(r["connector_json"]).get("sort_sent")), None),
            "oldest_publication_date": min(dates) if dates else None, "newest_publication_date": max(newest) if newest else None,
            "next_cursor": successes[-1]["next_cursor"] if successes else unit["cursor"], "finished": finished,
            "requested_from": unit["requested_from"], "requested_to": unit["requested_to"],
            "baseline_restarted": unit["baseline_restarted"]}
        obs["coverage"] = policy.coverage(unit, obs)
        obs["unread_window"] = None if finished else {"from": unit["requested_from"], "to": unit["requested_to"]}
        observed["units"][key] = obs
        statuses[key] = {"provider": provider, "status": state,
            "error_kind": reads[-1]["error_kind"] if reads else None,
            "returned": sum(r["returned_count"] for r in reads), "dropped": sum(r["dropped_count"] for r in reads)}
        reason = {"deferred_budget": "budget_deferred", "deferred_deadline": "deadline_deferred"}.get(state)
        if state in policy.PARTIAL_REASONS:
            reason = state
        elif state not in ("ready", "completed", "zero_results") and reason is None:
            reason = "provider_failed"
        if reason:
            observed["partial_reasons"].append(reason)
        if obs["coverage"] not in ("covered", "baseline_complete"):
            observed["partial_reasons"].append(obs["coverage"])
    if config["rolled_over_units"]:
        observed["partial_reasons"].append("rolled_over")
    if config["skipped_units"]:
        observed["partial_reasons"].append("no_openalex_id")
    observed["partial_reasons"] = list(dict.fromkeys(observed["partial_reasons"]))
    return observed, statuses


async def run(watches, check, callbacks, settings):
    config = json.loads(check["config_json"])
    complete = callbacks.existing_step("watch_complete")
    if complete and complete["status"] == "succeeded":
        return
    if callbacks.run()["status"] not in ("running", "pause_requested"):
        return
    quota = set()
    deferred = None
    for unit in config["units"]:
        if unit["status"] != "ready":
            continue
        rows = watches.reads(check)
        prior = [r for r in rows if r["unit_key"] == unit["unit_key"]]
        quota.update(r["provider"] for r in rows if r["error_kind"] == "quota_exhausted")
        if unit["provider_id"] in quota:
            continue
        if any(r["status"] not in ("completed", "zero_results") for r in prior):
            if prior[-1]["status"] in ("deferred_budget", "deferred_deadline"):
                deferred = prior[-1]["status"]
            continue
        if deferred:
            continue
        cursor = prior[-1]["next_cursor"] if prior else unit["cursor"]
        if prior and cursor is None:
            continue
        page_limit = config["caps"]["pages"] - unit["pages_read"] if unit["baseline"] else config["caps"]["pages"]
        connector = registry.reading(unit)
        if (unit["contract_id"], unit["adapter_revision"]) != (facade.contract.CONTRACT_ID, connector.adapter_revision):
            watches.refuse_revision(check["run_id"])
            return
        for page in range(len(prior) + 1, page_limit + 1):
            reason = callbacks.gate()
            if reason:
                return
            operation = f"watch:{unit['index']}:page:{page}"
            step = callbacks.step(operation, "watch_read")
            if step["status"] in ("failed", "outcome_unknown"):
                outcome = SearchOutcome("outcome_unknown" if step["status"] == "outcome_unknown" else "failed",
                    "after_send_unknown", "Stored page not sent again.", "unknown", error=step.get("error_code"))
                watches.record_read(check, unit, page, step, outcome, [], 0, 0, None, None, None, None, finish=False)
                break
            if step["status"] == "succeeded":
                raise RuntimeError("A succeeded watch page has no immutable read row")
            returned = sum(r["returned_count"] for r in watches.reads(check))
            callbacks.start_step(step["id"])
            key = connector.api_key()
            transport = GatedTransport(callbacks, config)
            if returned + unit["page_size"] > config["caps"]["max_records"]:
                transport.reason = "deferred_budget"
                outcome = SearchOutcome("failed", "before_send", "Frozen page does not fit the records left.", "unknown")
                dispatched = None
            elif connector.key_required and not key:
                outcome = SearchOutcome("not_configured", "before_send", "Provider key is no longer configured.", "not_configured")
                dispatched = None
            else:
                async with httpx.AsyncClient(transport=transport, headers=callbacks.headers) as http:
                    for attempt in range(MAX_TRANSIENT_NETWORK_RETRIES + 1):
                        left = callbacks.run()["budget"]["max_provider_requests"] - callbacks.run()["usage"].get("provider_requests", 0)
                        options = {"cursor": cursor, "max_rate_limit_retries": max(0, min(config["caps"]["rate_limit_retries"], left-1))}
                        gate = callbacks.host_gate(openalex.WORKS_URL) if unit["provider_id"] == "openalex" else no_gate()
                        async with gate:
                            if unit["kind"] == "citing_works":
                                dispatched = await facade.dispatch_citing(unit["provider_id"], http, unit["openalex_id"], cursor,
                                    unit["page_size"], key, settings.contact_email, **{k: v for k, v in options.items() if k != "cursor"},
                                    sort="publication_date:desc", publication_date=True)
                                outcome = dispatched.outcome
                            else:
                                options.update(connector.sw_options, **registry.endpoint_options(unit))
                                if unit["date_sorted"]:
                                    options.update(sort="publication_date:desc", publication_date=True)
                                dispatched = await facade.dispatch_search(unit["provider_id"], http, unit["query_text"],
                                    unit["page_size"], key, settings.contact_email, **options)
                                outcome = dispatched.outcome
                        if transport.reason or outcome.status != "failed" or outcome.delivery_class != "before_send" or attempt == MAX_TRANSIENT_NETWORK_RETRIES:
                            break
                        await callbacks.sleep(1.5 * (attempt + 1))
            records = [policy.normalize_record(unit["provider_id"], asdict(record), callbacks.clock(),
                        openalex.publication_date_of(record.raw) if unit["date_sorted"] else None) for record in outcome.records]
            payload_path = payload_digest = file_digest = None
            if outcome.raw_payload is not None:
                payload_path = step["id"] + ".json"
                encoded = (json.dumps(outcome.raw_payload, ensure_ascii=False, indent=2) + "\n").encode("utf-8")
                settings.payloads_dir.mkdir(parents=True, exist_ok=True)
                (settings.payloads_dir / payload_path).write_bytes(encoded)
                payload_digest = canonical.sha256_hex(outcome.raw_payload)
                file_digest = hashlib.sha256(encoded).hexdigest()
            watches.record_read(check, unit, page, step, outcome, records,
                dispatched.returned_count if dispatched else len(records), dispatched.dropped_records if dispatched else 0,
                dispatched.connector | {"sort_sent": ("publication_date:desc" if unit["date_sorted"] else unit.get("sort"))
                    if transport.sent else None} if dispatched else None,
                payload_path, payload_digest, file_digest, transport.reason)
            if transport.reason:
                if transport.reason not in ("deferred_budget", "deferred_deadline"):
                    return
                deferred = transport.reason
                break
            if outcome.error_kind == "quota_exhausted":
                quota.add(unit["provider_id"])
            if outcome.status not in ("completed", "zero_results") or outcome.next_cursor is None:
                break
            cursor = outcome.next_cursor
            if page < page_limit and unit["page_gap"]:
                await callbacks.sleep(unit["page_gap"])
    observed, statuses = observations(config, watches.reads(check))
    watches.complete_check(check, observed, statuses)
