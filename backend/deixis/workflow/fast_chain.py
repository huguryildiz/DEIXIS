"""One durable, bounded chain round for explicitly marked fast-path runs."""

from __future__ import annotations

import asyncio
import json
import re
from dataclasses import replace
from datetime import timedelta

from deixis.domain import canonical
from deixis.domain.rules import PROVIDER_WAIT, MAX_TRANSIENT_NETWORK_RETRIES
from deixis.documents import acquisition
from deixis.providers import facade
from deixis.providers.common import FIRST_PAGE
from deixis.providers.registry import CONNECTORS
from deixis.storage.db import transaction
from deixis.workflow import chaining, fast_path, ranking, small_batch


def work_id(value):
    value = str(value).rsplit("/", 1)[-1]
    return value if re.fullmatch(r"W\d+", value) else None


def request_plan(seeds, policy, held, prior=()):
    """Append-only numbering; direction allowances never restart at fallback."""
    seen = set(held)
    seen.update(ref for spec in prior for ref in (spec.get("batch") or []))
    refs, excluded = [], []
    for seed in seeds:
        for ref in seed["references"]:
            if ref in seen:
                excluded.append(ref)
            else:
                seen.add(ref)
                refs.append(ref)
    back_used = sum(s["direction"] == "backward" for s in prior)
    fwd_used = sum(s["direction"] == "forward" for s in prior)
    size = policy["backward_page_size"]
    batches = [refs[i:i + size] for i in range(0, len(refs), size)]
    back = batches[:max(0, policy["backward_requests"] - back_used)]
    forward = seeds[:max(0, policy["forward_requests"] - fwd_used)]
    specs = []
    base = max((s["index"] for s in prior), default=-1) + 1
    for j in range(max(len(back), len(forward))):
        if j < len(back):
            specs.append({"direction": "backward", "batch": back[j], "cites": None,
                          "links": chaining.backward_links(seeds, back[j]), "limit": len(back[j])})
        if j < len(forward):
            seed = forward[j]
            specs.append({"direction": "forward", "batch": None, "cites": seed["openalex_id"],
                          "links": [seed["source_version_id"]], "limit": policy["forward_page_size"]})
    for i, spec in enumerate(specs, base):
        spec["index"] = i
        spec["key"] = f"chain:fast:{i}"
    return {"requests": specs, "excluded": len(excluded), "excluded_hash": canonical.sha256_hex(excluded),
            "not_requested": len(refs) - sum(map(len, back)), "forward_not_requested": len(seeds) - len(forward)}


class Round:
    def __init__(self, flow, run, scope, vocabulary):
        self.flow, self.store, self.run, self.scope = flow, flow.store, run, scope
        self.policy = run["budget"]["fast_path"]
        self.vocabulary = vocabulary
        self.forms = flow._chain_forms(run, scope, vocabulary)
        self.semaphore = asyncio.Semaphore(self.policy["chain_in_flight"])
        self.admit = asyncio.Event()
        if self.store.existing_step(run["id"], "fast_chain:plan_fallback"):
            self.admit.set()
        self.tasks = []
        self.writers = []
        self.replies = {}
        self.closed = bool(self.store.existing_step(run["id"], small_batch.LIST_KEY)
                           or self.store.existing_step(run["id"], "fast_chain:summary"))

    def cutoff(self):
        deadline = fast_path.stage_deadline(self.store, self.run, "ranking")
        return deadline - timedelta(milliseconds=self.policy["arrival_margin_ms"]) if deadline else None

    def past_cutoff(self):
        cutoff = self.cutoff()
        return cutoff is not None and self.store.clock.now() >= cutoff

    def save(self, key, build):
        if not self.store.conn.in_transaction:
            self.flow._checkpoint(self.run["id"], self.run["scope_revision"])
        step = self.store.step(self.run["id"], key, "code:fast_chain")
        if step["status"] == "succeeded":
            return step["output"]
        output = small_batch.json_value(build())
        with transaction(self.store.conn):
            self.store.start_step(step["id"])
            self.store.finish_step(step["id"], "succeeded", output=output)
        return output

    def payload(self, path):
        if not path:
            return {}, None
        try:
            payload = json.loads((self.flow.deps.settings.payloads_dir / path).read_text())
        except (OSError, ValueError):
            return {}, None
        digest = canonical.sha256_hex(payload)
        stored = self.store.conn.execute("SELECT payload_sha256 FROM search_runs WHERE raw_payload_path = ?", (path,)).fetchone()
        if stored and stored[0] and stored[0] != digest:
            return {}, None
        return payload, digest

    def choose(self, identities, origin, previous=()):
        chosen = []
        seen = {key for seed in previous for key in (seed["work_id"], "title:" + seed["title_key"])}
        for svid in ranking.verified_seeds(self.store, self.run["research_id"], self.scope):
            source = self.store.source(svid)
            seen |= {source["work_id"], "title:" + chaining.norm_title(source["title"])}
        for oid, raw, digest in identities:
            svid = self.store.find_source_by_identifier("openalex", oid)
            if not svid:
                continue
            source = self.store.source(svid)
            title = chaining.norm_title(source["title"])
            keys = {source["work_id"], "title:" + title}
            if keys & seen:
                continue
            seen |= keys
            refs = list(dict.fromkeys(ref for value in raw.get("referenced_works", []) if (ref := work_id(value))))
            chosen.append({"rank": len(previous) + len(chosen), "source_version_id": svid,
                           "work_id": source["work_id"], "title_key": title, "openalex_id": oid,
                           "references": refs, "references_read": "referenced_works" in raw,
                           "origin": origin, "payload_sha256": digest})
            if len(previous) + len(chosen) >= self.policy["chain_seeds"]:
                break
        return chosen

    def initial(self):
        if self.closed:
            self.close_open("list_frozen")
            return
        def snapshot():
            step = self.store.existing_step(self.run["id"], "search:fast:semantic")
            row = self.store.conn.execute("SELECT raw_payload_path FROM search_runs WHERE step_id = ?", (step["id"],)).fetchone() if step else None
            payload, digest = self.payload(row[0] if row else None)
            identities = [(oid, raw, digest) for raw in payload.get("results", []) if (oid := work_id(raw.get("id")))]
            seeds = self.choose(identities, "semantic")
            return {"seeds": seeds, "missing": self.policy["chain_seeds"] - len(seeds),
                    "semantic_status": step["status"] if step else "missing", "payload_sha256": digest}
        seeds = self.save("fast_chain:seeds", snapshot)["seeds"]
        plan = self.save("fast_chain:plan", lambda: request_plan(seeds, self.policy, self.held()))
        self.launch(plan["requests"])

    def held(self):
        return {r[0] for r in self.store.conn.execute(
            "SELECT i.value FROM identifier_mappings i JOIN corpus_memberships m ON m.source_version_id = i.source_version_id"
            " WHERE m.research_id = ? AND m.removed_at IS NULL AND i.scheme = 'openalex'", (self.run["research_id"],))}

    def fallback(self):
        if self.closed:
            return
        initial = self.store.existing_step(self.run["id"], "fast_chain:seeds")["output"]["seeds"]
        def snapshot():
            if len(initial) >= self.policy["chain_seeds"]:
                return {"seeds": [], "not_needed": True}
            versions, by_work, pool = ranking.pool_rows(self.store, self.run["research_id"], self.run["scope_revision"])
            model, reason = self.flow._ranking_embedding(self.run, self.scope)
            scores = fast_path.ranking_similarities(self.store, self.run, model) if model else {}
            query, blocks = ranking.query_vocabulary(self.scope, self.vocabulary, {})
            verified = [ranking._seed_row(svid, versions) for svid in ranking.verified_seeds(self.store, self.run["research_id"], self.scope)]
            ranked = ranking.rank_pool(pool, [r for r in verified if r], query, blocks, model, scores, reason,
                                       ranking.joint_terms(self.store, self.scope, self.vocabulary))
            identities = []
            for svid in ranked["fused"]:
                for version in sorted(by_work[versions[svid]["work_id"]], key=lambda v: (v["id"] != svid, v["id"])):
                    source = self.store.source(version["id"])
                    payload, digest = self.payload(source.get("provider_payload_path"))
                    found = set()
                    for raw in payload.get("results", []):
                        oid = work_id(raw.get("id"))
                        if oid and self.store.find_source_by_identifier("openalex", oid) == version["id"]:
                            identities.append((oid, raw, digest))
                            found.add(oid)
                    for oid in sorted(version["own_ids"] - found):
                        if work_id(oid):
                            identities.append((oid, {}, None))
            return {"seeds": self.choose(identities, "fallback", initial),
                    "order_hash": canonical.sha256_hex(ranked["fused"]), "top100": ranked["fused"][:100],
                    "embedded": sum(row["id"] in scores for row in pool), "pool": len(pool)}
        seeds = self.save("fast_chain:seeds_fallback", snapshot)["seeds"]
        prior = self.store.existing_step(self.run["id"], "fast_chain:plan")["output"]["requests"]
        plan = self.save("fast_chain:plan_fallback", lambda: request_plan(seeds, self.policy, self.held(), prior))
        self.launch(plan["requests"])

    def launch(self, specs):
        previous = self.writers[-1] if self.writers else None
        tasks = [asyncio.create_task(self.fetch(spec)) for spec in specs]
        self.tasks.extend(tasks)
        async def write():
            if previous:
                await previous
            # Keyword admissions and the fallback snapshot precede chain writes.
            await self.admit.wait()
            for spec, task in zip(specs, tasks):
                await task
                self.write_reply(spec)
        self.writers.append(asyncio.create_task(write()))

    async def fetch(self, spec):
        step = self.store.step(self.run["id"], spec["key"], chaining.STEP_KIND)
        if step["status"] != "pending":
            return
        async with self.semaphore:
            if self.flow._stop_requested(self.run["id"], self.run["scope_revision"]):
                return
            if self.past_cutoff() or self.flow._openalex_budget_of(self.run["id"]).exhausted:
                reason = "cutoff" if self.past_cutoff() else "openalex_budget"
                self.store.finish_step(step["id"], "cancelled", output={"unsent": reason, "returned": 0})
                return
            self.store.start_step(step["id"])
            attempts = 0
            while True:
                limit = self.run["budget"].get("max_chain_requests",
                    (self.policy["backward_requests"] + self.policy["forward_requests"])
                    * (1 + PROVIDER_WAIT[self.scope["effort"]]) * (1 + MAX_TRANSIENT_NETWORK_RETRIES))
                left = limit - self.store.run(self.run["id"])["usage"].get("chain_requests", 0)
                if left <= 0 or self.past_cutoff() or self.flow._openalex_budget_of(self.run["id"]).exhausted:
                    self.store.finish_step(step["id"], "cancelled", output={"unsent": "request_budget" if left <= 0 else "cutoff" if self.past_cutoff() else "openalex_budget", "returned": 0})
                    return
                retries = max(0, min(PROVIDER_WAIT[self.scope["effort"]], left - 1))
                self.store.add_usage(self.run["id"], "chain_requests", 1 + retries)
                key = CONNECTORS["openalex"].api_key()
                if spec["direction"] == "forward":
                    dispatched = await facade.dispatch_citing("openalex", self.flow.deps.http, spec["cites"], FIRST_PAGE,
                        spec["limit"], key, self.flow.deps.settings.contact_email, retries)
                else:
                    dispatched = await facade.dispatch_lookup("openalex", "id_lookup", self.flow.deps.http,
                        tuple(spec["batch"]), key, self.flow.deps.settings.contact_email, retries)
                from deixis.workflow import lookups
                lookups.settle_dispatch(self.store, self.run["id"], step, dispatched, 1 + retries, "chain_requests", "chain_sends")
                outcome = dispatched.outcome
                if outcome.error_kind == "quota_exhausted":
                    reset = acquisition._reset_at(outcome.rate_limit)
                    with transaction(self.store.conn):
                        self.store._note_openalex_budget(self.run["research_id"], self.run["id"], reset, skipped=False)
                if outcome.delivery_class == "before_send" and attempts < MAX_TRANSIENT_NETWORK_RETRIES:
                    attempts += 1
                    await asyncio.sleep(1.5 * attempts)
                    continue
                break
            arrived = self.store.clock.now()
            cutoff = self.cutoff()
            late = cutoff is not None and arrived >= cutoff
            # Returned records are capped before filtering; a provider overflow
            # cannot expand this direction's frozen admission allowance.
            dispatched = replace(dispatched, outcome=replace(outcome, records=outcome.records[:spec["limit"]]))
            self.replies[spec["index"]] = (dispatched, arrived.isoformat(timespec="milliseconds"),
                                          cutoff.isoformat(timespec="milliseconds") if cutoff else None, late,
                                          len(outcome.records))

    def write_reply(self, spec):
        reply = self.replies.pop(spec["index"], None)
        if reply is None:
            return
        dispatched, arrived, cutoff, late, raw_returned = reply
        current = self.store.run(self.run["id"])
        if (current["status"] not in ("running", "pause_requested", "paused")
                or self.store.research(self.run["research_id"])["current_scope_revision"] != self.run["scope_revision"]):
            return
        step = self.store.existing_step(self.run["id"], spec["key"])
        self.flow._record_chain(self.run, step, spec["key"], spec["direction"], dispatched, self.forms,
            spec["links"], cites=spec["cites"], page=1 if spec["cites"] else None,
            batch=spec["batch"], per_page=spec["limit"], fast_request=spec["index"],
            fast_arrival={"arrived_at": arrived, "cutoff": cutoff, "late": late,
                          "raw_returned": raw_returned, "admitted_returned": len(dispatched.outcome.records) if not late else 0})
        consumer = self.flow._fast_consumers.get(self.run["id"])
        if consumer:
            consumer.notify()

    def done(self):
        for writer in self.writers:
            if writer.done() and not writer.cancelled() and writer.exception():
                raise writer.exception()
        return all(t.done() for t in self.writers)

    async def stop(self):
        for task in self.tasks + self.writers:
            if not task.done():
                task.cancel()
        await asyncio.gather(*self.tasks, *self.writers, return_exceptions=True)
        if not self.admit.is_set():
            return
        # A returned reply waiting behind a slower request is still evidence
        # from its recorded arrival, even if the slower request was cancelled.
        for key in ("fast_chain:plan", "fast_chain:plan_fallback"):
            plan = self.store.existing_step(self.run["id"], key)
            for spec in ((plan or {}).get("output") or {}).get("requests", []):
                self.write_reply(spec)

    def close_open(self, reason):
        for step in self.store.run_steps(self.run["id"]):
            if step["operation_key"].startswith("chain:fast:") and step["status"] in ("pending", "running"):
                sent = step["status"] == "running"
                self.store.finish_step(step["id"], "outcome_unknown" if sent else "cancelled",
                    output={"unsent": None if sent else reason, "unknown": sent, "returned": 0},
                    error_code="interrupted" if sent else None)

    def summary(self):
        def build():
            outputs = [(self.store.step_output(s["id"]) or {}) | {"step_status": s["status"]} for s in self.store.run_steps(self.run["id"])
                       if s["operation_key"].startswith("chain:fast:")]
            reasons = {o["unsent"] for o in outputs if o.get("unsent")}
            return {"sent": sum(not o.get("unsent") for o in outputs),
                    "accepted": sum(o["step_status"] == "succeeded" and "late" in o and not o["late"] for o in outputs),
                    "returned": sum(o.get("returned", 0) for o in outputs),
                    "raw_returned": sum(o.get("raw_returned", 0) for o in outputs),
                    "admitted_returned": sum(o.get("admitted_returned", 0) for o in outputs),
                    "failed": sum(o["step_status"] == "failed" for o in outputs),
                    "passed_filter": sum(o.get("passed_filter", 0) for o in outputs if not o.get("late")),
                    "late_records": sum(o.get("returned", 0) for o in outputs if o.get("late")),
                    "unknown": sum(o["step_status"] == "outcome_unknown" for o in outputs),
                    "unsent": {r: sum(o.get("unsent") == r for o in outputs) for r in sorted(reasons)}}
        return self.save("fast_chain:summary", build)


def manifest(store, run):
    steps = [s for s in store.run_steps(run["id"]) if s["operation_key"].startswith("fast_chain:")]
    return {"steps": [{"id": s["id"], "key": s["operation_key"], "sha256": canonical.sha256_hex(store.step_output(s["id"]))} for s in steps],
            "summary": (store.existing_step(run["id"], "fast_chain:summary") or {}).get("output"),
            "cutoff_at": ((store.existing_step(run["id"], "source_similarity") or {}).get("output") or {}).get("cutoff_at"),
            "unembedded": [r[0] for r in store.conn.execute("SELECT source_version_id FROM fast_path_embedding_queue"
                " WHERE run_id = ? AND status = 'unembedded_at_cutoff' ORDER BY class, request_index, position", (run["id"],))]}


def read_versions(flow, run, listing):
    """Freeze sanctioned lookup enrichment without rewriting the ranking input."""
    def build():
        from deixis.workflow.lookups import ABSTRACT_ORIGINS
        current = ranking._versions(flow.store, run["research_id"])
        frozen = listing["manifest"]["versions"]
        versions = dict(frozen)
        enriched = []
        for item in listing["items"][:run["budget"]["fast_path"]["N"]]:
            for svid in item["versions"]:
                before, after = frozen[svid], current.get(svid)
                if (not after or before.get("abstract") or not after.get("abstract")
                        or any(before.get(k) != after.get(k) for k in ("work_id", "title", "doi", "version_label"))):
                    continue
                origins = [r[0] for r in flow.store.conn.execute(
                    "SELECT abstract_origin FROM passages WHERE source_version_id = ? AND kind = 'abstract'", (svid,))]
                if origins and all(origin in ABSTRACT_ORIGINS.values() for origin in origins):
                    versions[svid] = after
                    enriched.append(svid)
        view = listing | {"manifest": listing["manifest"] | {"versions": versions}}
        unchanged = small_batch.unchanged_heads(flow.store, run["research_id"], view,
                                              listing["items"][:run["budget"]["fast_path"]["N"]])
        return small_batch.json_value({"versions": versions, "lookup_enriched": enriched,
                "changed_items": len(listing["items"][:run["budget"]["fast_path"]["N"]]) - len(unchanged),
                "ranking_manifest_hash": listing["manifest_hash"]})
    return small_batch.save_code(flow, run, "fast_chain:read_versions", "code:fast_chain_read_versions", build)
