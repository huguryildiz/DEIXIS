"""One durable, bounded chain round for explicitly marked fast-path runs."""

from __future__ import annotations

import asyncio
import json
import re
from collections import defaultdict
from dataclasses import replace
from datetime import timedelta

from deixis.domain import canonical
from deixis.domain.rules import MAX_TRANSIENT_NETWORK_RETRIES
from deixis.documents import acquisition
from deixis.providers import facade
from deixis.providers.common import FIRST_PAGE
from deixis.providers.registry import CONNECTORS
from deixis.storage.db import transaction
from deixis.workflow.search import (chaining, date_scope, search as fast_search, ranking, search_plan,
                                    seed_match, small_batch)
from deixis.workflow.run import fast_path

RETRY_BACKOFF_SECONDS = 1.5  # wait before resending a request that never left, times the attempt number


def work_id(value):
    value = str(value).rsplit("/", 1)[-1]
    return value if re.fullmatch(r"W\d+", value) else None


def forward_pages(seeds, allowance, paged=True):
    """One entry per forward request: which seed it reads, and which page of that seed's citing works.

    Under the m2 method the plan names one to three works, so an allowance left over once every named work has been
    read once is spent on the next page of the same work rather than on a work the plan did not name. The pages are
    handed out round by round, so no seed is read twice before every seed has been read once.

    Without `paged` — every other method — each seed is read once and a leftover allowance stays unspent, exactly as
    it did before: those runs are the measurement's baseline and their requests are not to move.
    """
    if not paged:
        return [{"seed": seed, "seed_index": index, "page": 1} for index, seed in enumerate(seeds[:allowance])]
    pages = []
    for page in range(1, allowance + 1):
        for index, seed in enumerate(seeds):
            if len(pages) >= allowance:
                return pages
            pages.append({"seed": seed, "seed_index": index, "page": page})
    return pages


def request_plan(seeds, policy, held, prior=()):
    """Append-only numbering; direction allowances never restart at fallback.

    A run that bounds its years bounds the forward direction with them: asking which works cite a seed is a search
    of the literature, so it comes back inside the bound like every other request. The backward direction is not a
    date search — it asks OpenAlex for the records of the references a seed itself lists, by identifier — so it
    carries no bound and its step says so (`date_bound`), rather than reading as a request that lost one.
    """
    years = policy.get("date_scope")
    bound = date_scope.openalex_filter(years)
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
    # The plan names the chain's works, so a leftover allowance is spent on a further page.
    forward = forward_pages(seeds, max(0, policy["forward_requests"] - fwd_used), True)
    specs = []
    base = max((s["index"] for s in prior), default=-1) + 1
    for j in range(max(len(back), len(forward))):
        if j < len(back):
            specs.append({"direction": "backward", "batch": back[j], "cites": None,
                          "links": chaining.backward_links(seeds, back[j]), "limit": len(back[j]),
                          **({"date_bound": "not_a_date_search"} if years else {})})
        if j < len(forward):
            seed = forward[j]["seed"]
            specs.append({"direction": "forward", "batch": None, "cites": seed["openalex_id"],
                          "links": [seed["source_version_id"]], "limit": policy["forward_page_size"],
                          "page": forward[j]["page"], "seed_index": forward[j]["seed_index"],
                          **({"works_filter": bound, "date_bound": "applied"} if bound else {})})
    for i, spec in enumerate(specs, base):
        spec["index"] = i
        spec["key"] = f"chain:fast:{i}"
    # A page past the first continues the page before it, and is sent with the cursor that page's reply left: the
    # spec names that request, as the snowball's pages do, so a resumed run reads the cursor back from its step.
    last = {}
    for spec in specs:
        if spec["direction"] == "forward":
            spec["after"] = last.get(spec["seed_index"])
            last[spec["seed_index"]] = spec["key"]
    return {"requests": specs, "excluded": len(excluded), "excluded_hash": canonical.sha256_hex(excluded),
            "not_requested": len(refs) - sum(map(len, back)),
            "forward_not_requested": len(seeds) - len({page["seed_index"] for page in forward})}


def frozen_forms(flow, run):
    """The admission forms this run's protocol froze, checked against their digest. A body without them, or
    one whose forms no longer match the digest, stops the run: the chain never admits with forms other than frozen."""
    store = flow.store
    step = store.existing_step(run["id"], "protocol")
    revision = ((step or {}).get("output") or {}).get("protocol_revision")
    row = store.conn.execute(
        "SELECT body_json FROM protocol_records WHERE research_id = ? AND scope_revision = ?"
        + (" AND protocol_revision = ?" if revision is not None else "") + " ORDER BY protocol_revision DESC LIMIT 1",
        (run["research_id"], run["scope_revision"], *((revision,) if revision is not None else ()))).fetchone()
    frozen = (json.loads(row[0]).get("citation_chaining") or {}) if row else {}
    forms = frozen.get("admission_forms")
    if forms is None or chaining.forms_digest(forms) != frozen.get("admission_forms_sha256"):
        flow._fail(run["id"], "chain_forms_unverified", {"rule": run["budget"]["fast_path"]["chain_rule"]})
    return forms


class Round:
    def __init__(self, flow, run, scope, vocabulary):
        self.flow, self.store, self.run, self.scope = flow, flow.store, run, scope
        self.policy = run["budget"]["fast_path"]
        self.vocabulary = vocabulary
        # The chain admits with the forms this run's protocol froze, never with forms computed now.
        self.forms = frozen_forms(flow, run)
        self.semaphore = asyncio.Semaphore(self.policy["chain_in_flight"])
        self.admit = asyncio.Event()
        if self.store.existing_step(run["id"], "fast_chain:plan_fallback"):
            self.admit.set()
        self.tasks = []
        self.writers = []
        # Set once a request's reply has been written, however it ended: the next page of the same seed waits here.
        self.written = defaultdict(asyncio.Event)
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
            payload = json.loads((self.flow.deps.settings.payloads_dir / path).read_text(encoding="utf-8"))
        except (OSError, ValueError):
            return {}, None
        digest = canonical.sha256_hex(payload)
        stored = self.store.conn.execute("SELECT payload_sha256 FROM search_runs WHERE raw_payload_path = ?", (path,)).fetchone()
        if stored and stored[0] and stored[0] != digest:
            return {}, None
        return payload, digest

    def pdf_seeds(self):
        """The seed PDFs' matched works as the first chain seeds, in canonical order and once per OpenAlex work, read
        only from the protocol; one seed PDF is that seed 0."""
        envelope = seed_match.frozen(self.store, self.run)
        seeds, seen = [], set()
        for context in envelope["seeds"] if envelope else []:
            # Read before the seed is added, so a depth whose allowance is zero keeps none (Quick opens no request).
            if len(seeds) >= self.policy["chain_seeds"]:
                break
            if context["status"] != "matched" or context["openalex_id"] in seen:
                continue
            seen.add(context["openalex_id"])
            seeds.append({"rank": len(seeds), "source_version_id": context["source_version_id"],
                          "work_id": context["work_id"], "title_key": context["title_key"],
                          "openalex_id": context["openalex_id"], "references": context["referenced_works"],
                          "references_read": context["references_read"], "origin": "seed_pdf",
                          "payload_sha256": context["lookups"][-1]["payload_sha256"]})
        return seeds

    def choose(self, identities, origin, previous=(), accepted=None):
        """With `accepted` (a version 2 plan's first choice), a work counts only through a version the question's
        request itself accepted."""
        chosen = []
        # An OpenAlex identity is a key too, so the seed PDF's own record is never chosen again under another title.
        seen = {key for seed in previous for key in (seed["work_id"], "title:" + seed["title_key"], "oa:" + seed["openalex_id"])}
        for svid in ranking.verified_seeds(self.store, self.run["research_id"], self.scope):
            source = self.store.source(svid)
            seen |= {source["work_id"], "title:" + chaining.norm_title(source["title"])}
        for oid, raw, digest in identities:
            # Read before the work is chosen, as `pdf_seeds` does: a zero allowance chooses none.
            if len(previous) + len(chosen) >= self.policy["chain_seeds"]:
                break
            svid = self.store.find_source_by_identifier("openalex", oid)
            if not svid or (accepted is not None and svid not in accepted):
                continue
            source = self.store.source(svid)
            title = chaining.norm_title(source["title"])
            keys = {source["work_id"], "title:" + title, "oa:" + oid}
            if keys & seen:
                continue
            seen |= keys
            refs = list(dict.fromkeys(ref for value in raw.get("referenced_works", []) if (ref := work_id(value))))
            chosen.append({"rank": len(previous) + len(chosen), "source_version_id": svid,
                           "work_id": source["work_id"], "title_key": title, "openalex_id": oid,
                           "references": refs, "references_read": "referenced_works" in raw,
                           "origin": origin, "payload_sha256": digest})
        return chosen

    def named_identities(self, named, identities):
        """The works the plan named, in its order, as chain identities.

        A named work this page returned is taken from that page, with its references and the page's digest. One the
        page does not hold is read from the record this research already keeps for it: its own stored provider
        payload, or, where that payload no longer holds it, the identity alone — then the chain can follow it
        forward and has no references to follow back, which is what is known about it.
        """
        page = {row[0]: row for row in identities}
        found = []
        for oid in named:
            if oid in page:
                found.append(page[oid])
                continue
            svid = self.store.find_source_by_identifier("openalex", oid)
            if not svid:
                continue
            payload, digest = self.payload(self.store.source(svid).get("provider_payload_path"))
            raw = next((row for row in payload.get("results", []) if work_id(row.get("id")) == oid), None)
            found.append((oid, raw or {}, digest if raw else None))
        return found

    def initial(self):
        if self.closed:
            self.close_open("list_frozen")
            return
        def snapshot():
            step = self.store.existing_step(self.run["id"], "search:fast:semantic")
            row = self.store.conn.execute("SELECT raw_payload_path FROM search_runs WHERE step_id = ?", (step["id"],)).fetchone() if step else None
            payload, digest = self.payload(row[0] if row else None)
            identities = [(oid, raw, digest) for raw in payload.get("results", []) if (oid := work_id(raw.get("id")))]
            previous = self.pdf_seeds()
            accepted = None
            if fast_search.plan_version(self.store, self.run) == 2:
                # Only what the question's request accepted, never a record beyond its limit that the library
                # already held, nor one a seed's own request brought.
                accepted = set(((step or {}).get("output") or {}).get("accepted_source_version_ids") or []
                               if step and step["status"] == "succeeded" else [])
            rows = search_plan.plan_named(self.store, self.run)
            named = None if rows is None else [row["openalex_id"] for row in rows if row["openalex_id"]]
            if named is not None:
                # The plan step named the works the chain starts from (P3): only those, in its order. The page's own
                # order adds nothing beside them, and a plan that named none leaves the chain to the Boolean results.
                # A work the plan named but this page does not hold — a plan a later run of the same scope revision
                # reused — is read from its own stored record instead, so the chain still starts where the plan says.
                identities = self.named_identities(named, identities)
                # What this page accepted no longer decides: the plan named these works, and a reused plan's works
                # were accepted by the page it was written from.
                accepted = None
            seeds = previous + self.choose(identities, "semantic", previous, accepted)
            return {"seeds": seeds, "missing": self.policy["chain_seeds"] - len(seeds),
                    "semantic_status": step["status"] if step else "missing", "payload_sha256": digest,
                    **({"plan_seeds": named} if named is not None else {}),
                    # A named work with no OpenAlex id cannot be asked for; it is named here rather than passed over.
                    **({"plan_seeds_unresolved": search_plan.unresolved_seeds(rows)}
                       if rows and search_plan.unresolved_seeds(rows) else {})}
        seeds = self.save("fast_chain:seeds", snapshot)["seeds"]
        plan = self.save("fast_chain:plan", lambda: request_plan(seeds, self.policy, self.held()))
        self.launch(plan["requests"])

    def pool_links(self):
        """Write the citation links that stand inside the first semantic page, without a request of its own.

        Every record of that page arrives with its own bibliography (`referenced_works`), stored as it is read
        (`store._store_references`). Where the page holds both A and B and B's bibliography names A, B cites A, and
        that is seen for nothing: the link is written as B's backward link to A. No work is admitted by it, because
        both records are in the pool already, so the gate has nothing to decide and the link is written as passing.
        Every depth writes these links, Quick included, which opens no citation request of its own.

        The links are written before the step closes, so a crash in between leaves rows a resumed run writes again;
        the primary key makes the second write a no-op.
        """
        if self.closed:
            return
        run_id, rid, revision = self.run["id"], self.run["research_id"], self.run["scope_revision"]

        def snapshot():
            step = self.store.existing_step(run_id, "search:fast:semantic")
            row = self.store.conn.execute("SELECT raw_payload_path FROM search_runs WHERE step_id = ?",
                                          (step["id"],)).fetchone() if step else None
            payload, digest = self.payload(row[0] if row else None)
            # Each record's bibliography is read from this reply, not from what earlier reads of the same work left
            # in the library: the link this step records is one this page itself shows.
            page = [(oid, raw) for raw in payload.get("results", [])[:self.policy["semantic_top"]]
                    if (oid := work_id(raw.get("id")))]
            # Only the records the page's works really have here: a work the page named and the record path did not
            # write has no record to link, and the link would name a source version that does not exist.
            inside = {oid: svid for oid, _ in page if (svid := self.store.find_source_by_identifier("openalex", oid))}
            links = []
            for oid, raw in page:
                if oid not in inside:
                    continue
                cited = {ref for value in raw.get("referenced_works") or [] if (ref := work_id(value))}
                links += [(inside[oid], ref) for ref in sorted(cited & set(inside)) if ref != oid]
            with transaction(self.store.conn):
                self.store.conn.executemany(
                    "INSERT OR IGNORE INTO chain_links (research_id, scope_revision, run_id, seed_source_version_id,"
                    " linked_openalex_id, direction, origin, passed_filter, source_version_id)"
                    " VALUES (?, ?, ?, ?, ?, 'backward', 'pool', 1, ?)",
                    [(rid, revision, run_id, seed, ref, inside[ref]) for seed, ref in links])
            return {"page": len(page), "in_pool": len(inside), "links": len(links),
                    "cited_works": len({ref for _, ref in links}),
                    "citing_records": len({seed for seed, _ in links}),
                    "semantic_status": step["status"] if step else "missing", "payload_sha256": digest}

        self.save("fast_chain:pool_links", snapshot)

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
            if search_plan.plan_seeds(self.store, self.run):
                # The plan named the works the chain starts from (P3), so the ranked pool fills no place beside
                # them: naming one work means one work, not one work and nine the plan did not name. A plan whose
                # named works the chain cannot ask for — none resolved to an OpenAlex id — is the design's
                # "no suitable work" case, and this round then supplies a seed from the keyword results as before.
                return {"seeds": [], "not_needed": True, "named_by_plan": True}
            versions, by_work, pool = ranking.pool_rows(self.store, self.run["research_id"], self.run["scope_revision"])
            query, blocks = ranking.query_vocabulary(self.scope, self.vocabulary)
            verified = ranking.seed_rows(self.store, self.run, self.scope, versions, {})
            ranked = ranking.rank_pool(pool, verified, query, blocks, None, {}, None,
                                       ranking.joint_terms(self.store, self.scope, self.vocabulary),
                                       fast_search.graph_rule(self.store, self.run))
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
                    "pool": len(pool)}
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
                self.written[spec["key"]].set()
        self.writers.append(asyncio.create_task(write()))

    async def fetch(self, spec):
        step = self.store.step(self.run["id"], spec["key"], chaining.STEP_KIND)
        if step["status"] != "pending":
            return
        if spec.get("after"):
            # This page is asked for with the cursor the page before it left, which is written when that reply is
            # written, so it waits for that write. Waited for outside the semaphore: a request that has not been
            # sent holds no in-flight place.
            await self.written[spec["after"]].wait()
        async with self.semaphore:
            if self.flow._stop_requested(self.run["id"], self.run["scope_revision"]):
                return
            if self.past_cutoff() or self.flow._openalex_budget_of(self.run["id"]).exhausted:
                reason = "cutoff" if self.past_cutoff() else "openalex_budget"
                self.store.finish_step(step["id"], "cancelled", output={"unsent": reason, "returned": 0})
                return
            cursor = FIRST_PAGE
            if spec.get("after"):
                before = self.store.existing_step(self.run["id"], spec["after"])
                cursor = (before["output"] or {}).get("next_cursor") if before and before["status"] == "succeeded" else None
                if not cursor:
                    # The page before it left no cursor: it was not sent, it failed, or the provider had no more to
                    # give. There is no next page to ask for, and nothing is asked in its place.
                    self.store.finish_step(step["id"], "cancelled", output={"unsent": "no_cursor", "returned": 0})
                    return
            self.store.start_step(step["id"])
            attempts = 0
            while True:
                limit = chaining.attempt_limit(self.policy, self.scope["effort"])
                left = limit - self.store.run(self.run["id"])["usage"].get("chain_requests", 0)
                if left <= 0 or self.past_cutoff() or self.flow._openalex_budget_of(self.run["id"]).exhausted:
                    self.store.finish_step(step["id"], "cancelled", output={"unsent": "request_budget" if left <= 0 else "cutoff" if self.past_cutoff() else "openalex_budget", "returned": 0})
                    return
                retries = max(0, min(fast_path.search_read(self.policy, self.scope["effort"], "provider_wait"), left - 1))
                self.store.add_usage(self.run["id"], "chain_requests", 1 + retries)
                key = CONNECTORS["openalex"].api_key()
                if spec["direction"] == "forward":
                    dispatched = await facade.dispatch_citing("openalex", self.flow.deps.http, spec["cites"], cursor,
                        spec["limit"], key, self.flow.deps.settings.contact_email, retries,
                        **({"works_filter": spec["works_filter"]} if spec.get("works_filter") else {}))
                else:
                    dispatched = await facade.dispatch_lookup("openalex", "id_lookup", self.flow.deps.http,
                        tuple(spec["batch"]), key, self.flow.deps.settings.contact_email, retries)
                from deixis.workflow.search import lookups
                lookups.settle_dispatch(self.store, self.run["id"], step, dispatched, 1 + retries, "chain_requests", "chain_sends")
                outcome = dispatched.outcome
                if outcome.error_kind == "quota_exhausted":
                    reset = acquisition.budget_reset_at(outcome.rate_limit)
                    with transaction(self.store.conn):
                        self.store.note_openalex_budget(self.run["research_id"], self.run["id"], reset, skipped=False)
                if outcome.delivery_class == "before_send" and attempts < MAX_TRANSIENT_NETWORK_RETRIES:
                    attempts += 1
                    await asyncio.sleep(RETRY_BACKOFF_SECONDS * attempts)
                    continue
                break
            arrived = self.store.clock.now()
            cutoff = self.cutoff()
            late = cutoff is not None and arrived >= cutoff
            # Returned records are capped before filtering; a provider overflow
            # cannot expand this direction's frozen admission allowance.
            dispatched = replace(dispatched, outcome=replace(outcome, records=outcome.records[:spec["limit"]]),
                                 kept_positions=dispatched.kept_positions[:spec["limit"]])
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
            spec["links"], cites=spec["cites"], page=spec.get("page", 1) if spec["cites"] else None,
            date_bound=spec.get("date_bound"),
            batch=spec["batch"], per_page=spec["limit"], fast_request=spec["index"],
            fast_arrival={"arrived_at": arrived, "cutoff": cutoff, "late": late,
                          "raw_returned": raw_returned, "admitted_returned": len(dispatched.outcome.records) if not late else 0},
            normalised=True)

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
                    # The records no gate form reached that the run's quota wrote all the same, counted apart from
                    # the ones a form admitted: a run whose budget froze no quota reports zero.
                    "rescued": sum(o.get("rescued", 0) for o in outputs if not o.get("late")),
                    "late_records": sum(o.get("returned", 0) for o in outputs if o.get("late")),
                    "unknown": sum(o["step_status"] == "outcome_unknown" for o in outputs),
                    "unsent": {r: sum(o.get("unsent") == r for o in outputs) for r in sorted(reasons)}}
        return self.save("fast_chain:summary", build)


def manifest(store, run):
    steps = [step for step in store.run_steps(run["id"]) if step["operation_key"].startswith("fast_chain:")]
    return {"steps": [{"id": step["id"], "key": step["operation_key"],
                       "sha256": canonical.sha256_hex(store.step_output(step["id"]))} for step in steps],
            "summary": (store.existing_step(run["id"], "fast_chain:summary") or {}).get("output"),
            "cutoff_at": None, "unembedded": []}


def read_versions(flow, run, listing, items=None, key="fast_chain:read_versions", with_order=False):
    """Freeze sanctioned lookup enrichment without rewriting the ranking input.

    `items` defaults to the read window's first N items; the deeper screening freezes its own window's items under
    a key of its own, after its own lookups, and with `with_order` also freezes the heads still unchanged then, so a
    resumed run screens and guards exactly those."""
    window = listing["items"][:run["budget"]["fast_path"]["N"]] if items is None else items

    def build():
        from deixis.workflow.search.lookups import ABSTRACT_ORIGINS
        current = ranking._versions(flow.store, run["research_id"])
        frozen = listing["manifest"]["versions"]
        versions = dict(frozen)
        enriched = []
        for item in window:
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
        unchanged = small_batch.unchanged_heads(flow.store, run["research_id"], view, window)
        return small_batch.json_value({"versions": versions, "lookup_enriched": enriched,
                "changed_items": len(window) - len(unchanged),
                "ranking_manifest_hash": listing["manifest_hash"]} | ({"order": unchanged} if with_order else {}))
    return small_batch.save_code(flow, run, key, "code:fast_chain_read_versions", build)
