"""D252 search slots and page admission; no provider or model fallbacks."""

from __future__ import annotations

import asyncio
import json
from dataclasses import replace

from deixis.domain.rules import PROVIDER_WAIT
from deixis.providers import facade
from deixis.providers.common import FIRST_PAGE, SearchOutcome
from deixis.providers.registry import CONNECTORS, reading
from deixis.storage.db import now, transaction
from deixis.providers import openalex, query_compiler
from deixis.workflow import english_question, fast_path, search_page, seed_match, user_plan
from deixis.workflow.search_page import Page
from deixis.workflow.expansion import queried_form

# At Detailed depth one Semantic Scholar bulk request reads up to this many records, taken off the keyword cap.
S2_RESERVED_RECORDS = 500
KEYWORD_PAGE_SIZE = 100  # records one OpenAlex keyword page asks for


def seed_query(question, envelope):
    """The semantic query with the seed PDFs' text behind the question, which is never cut, and what of each seed went
    in (D2, D3). One seed: D2's string. Several: the room the question leaves, less one separator per seed, shared
    equally; a seed whose share is empty adds nothing. Returns (query, seed_text, seed_parts)."""
    texts = [(c["source_version_id"], *seed_match.seed_text(c)) for c in envelope["seeds"]]
    limit = openalex.SEMANTIC_MAX_CHARS
    q = question[:limit]
    if len(texts) == 1:
        svid, text, origin = texts[0]
        if not text.strip():
            return question, None, []
        chars = max(0, min(len(text), limit - len(q) - 1))
        return (q + " " + text)[:limit], origin, [{"source_version_id": svid, "origin": origin, "chars": chars}] if chars else []
    share = max(0, limit - len(q) - len(texts)) // len(texts)
    parts = [(svid, origin, text[:share]) for svid, text, origin in texts if text[:share].strip()]
    origins = [origin for _, text, origin in texts if text.strip()]
    query = (q + " " + " ".join(part for _, _, part in parts))[:limit] if parts else q
    return query, origins or None, [{"source_version_id": svid, "origin": origin, "chars": len(part)}
                                    for svid, origin, part in parts]


def seed_requests(envelope, limit):
    """One OpenAlex semantic request per seed with text (D6): the seed's own text (`seed_match.seed_text`) cut to what
    OpenAlex accepts, in seed order; a seed with no text sends nothing. `index` is the seed's place in the envelope."""
    specs = []
    for i, context in enumerate(envelope["seeds"]):
        text, origin = seed_match.seed_text(context)
        if text.strip():
            specs.append({"index": i, "source_version_id": context["source_version_id"], "origin": origin,
                          "provider_id": "openalex", "endpoint": "semantic",
                          "query_text": openalex.semantic_text(text), "limit": limit})
    return specs


def seed_key(spec):
    return f"search:fast:semantic:seed:{spec['index']}"


def sent_plan(body):
    """The requests a frozen protocol body plans to send, each with the step key its pages are stored under.

    A fast path body sends its `fast_path_search` plan: the semantic request, one per seed at version 2, the OpenAlex
    keyword queries and, at Detailed depth, the Semantic Scholar bulk query. The plan's dropped queries are left out:
    they stand in `compiled_queries` but were never meant to be sent. A body without the plan sends every compiled
    query under `search:<index>`. `arm` says which kind of request it is; `watchable` that a watch can follow it by
    date (a semantic request ranks by meaning, not by date); a watchable request names its `compiled_index`, the place in
    `compiled_queries` a watch's saved units are keyed by."""
    compiled = body.get("compiled_queries") or []
    plan = body.get("fast_path_search")
    if plan is None:
        return [dict(q, key=f"search:{i}", arm="keyword", watchable=True, compiled_index=i) for i, q in enumerate(compiled)]
    semantic = plan["semantic"]
    sent = [{"provider_id": "openalex", "endpoint": "semantic", "query_text": semantic.get("query_text"),
             "origin": semantic.get("query_origin"), "key": "search:fast:semantic", "arm": "semantic",
             "watchable": False}]
    sent += [{"provider_id": spec["provider_id"], "endpoint": "semantic", "query_text": spec["query_text"],
              "origin": spec["origin"], "key": seed_key(spec), "arm": "seed_semantic", "watchable": False}
             for spec in plan.get("seed_semantic") or []]
    sent += [dict(compiled[item["index"]], key=f"search:{item['index']}", arm="keyword", watchable=True,
                  compiled_index=item["index"]) for item in plan["keywords"]]
    if plan.get("s2_bulk"):
        sent.append(dict(plan["s2_bulk"], key="search:fast:s2_bulk", arm="s2_bulk", watchable=True,
                         compiled_index=plan["s2_bulk_index"]))
    return sent


def frozen_body(store, run):
    """The protocol body this run froze, or None when its protocol step has not succeeded or names no record."""
    step = store.existing_step(run["id"], "protocol")
    if step is None or step["status"] != "succeeded" or not step["output"]:
        return None
    row = store.conn.execute(
        "SELECT body_json FROM protocol_records WHERE research_id = ? AND protocol_revision = ?",
        (run["research_id"], step["output"]["protocol_revision"])).fetchone()
    return json.loads(row[0]) if row else None


def plan_version(store, run):
    """The `fast_path_search` version this run's protocol froze: 1 when it froze none or no protocol is frozen yet."""
    body = frozen_body(store, run)
    return (body.get("fast_path_search") or {}).get("version", 1) if body else 1


def graph_rule(store, run):
    """The graph rule the ranking reads, chosen by the frozen plan, never by live code (D6): a version 2 plan ranks the
    seed PDFs by their nearest one (`seed_max_v2`), every other run as before (`sum_v1`)."""
    return "seed_max_v2" if plan_version(store, run) == 2 else "sum_v1"


def build_plan(store, run, scope, queries, seed_context=None):
    policy = run["budget"]["fast_path"]
    sentence = english_question.embedding_query(store, scope)
    if seed_context and seed_context.get("rule") == seed_match.RULE:
        # D6: the question's request is the unseeded one; each seed asks OpenAlex on its own, after it.
        plan = build_plan(store, run, scope, queries)
        return plan | {"version": 2, "seed_semantic": seed_requests(seed_context, policy["semantic_top"] // 2)}
    seed, parts = None, []
    if sentence and seed_context:
        # The seed PDFs' text rides behind the question (D2, D3); the ranking keeps the question alone.
        query, seed, parts = seed_query(sentence[0], seed_context)
        sentence = (query, sentence[1])
    deep = policy["mode"] == "deep"
    # The providers a person left out of a saved search plan get no request (S23a); OpenAlex cannot be left out.
    excluded = user_plan.excluded(scope)
    keyword = [{"index": i, "query": q} for i, q in enumerate(queries) if q["provider_id"] == "openalex"]
    s2_index = next((i for i, q in enumerate(queries)
                     if deep and q["provider_id"] == "semantic_scholar" and q.get("endpoint") == "bulk"
                     and "semantic_scholar" not in excluded), None)
    s2 = queries[s2_index] if s2_index is not None else None
    return {"version": 1, "semantic": {"provider_id": "openalex", "endpoint": "semantic",
            "query_text": openalex.semantic_text(sentence[0]) if sentence else None, "limit": policy["semantic_top"],
            "query_origin": sentence[1] if sentence else english_question.MISSING,
            **({"seed_text": seed} if seed else {}), **({"seed_parts": parts} if seed_context else {})},
            "keywords": keyword, "keyword_cap": policy["keyword_record_cap"] - (S2_RESERVED_RECORDS if deep else 0),
            "page_size": KEYWORD_PAGE_SIZE, "order": "page_then_query", "s2_bulk": s2 if deep else None,
            "s2_bulk_index": s2_index,
            "s2_reserved": S2_RESERVED_RECORDS if deep else 0,
            "dropped": [{"index": i, "query": q,
                         "reason": user_plan.EXCLUDED if q["provider_id"] in excluded else "openalex_only"}
                        for i, q in enumerate(queries) if q["provider_id"] != "openalex" and i != s2_index],
            "expansion": "fast_path_frozen_plan",
            # Only a run of a revision with a saved plan names this, so every other plan freezes as before.
            **({"excluded_providers": excluded} if user_plan.of(scope) is not None else {})}


def _carried(vocabulary, query):
    """The (block, form) pairs this compiled query really wrote, or None when that cannot be told.

    The block compiler is pure, so its prefix allocation is computed again from the vocabulary that wrote the query
    (the code's beside a model-written one, D92). Only when the text it gives is the stored text are its counts taken;
    any other text says nothing about what the stored query holds."""
    source = vocabulary["code_query"]["vocabulary"] if query.get("origin") == "code" else vocabulary
    groups, names = [], []
    for block in query_compiler.BLOCK_ORDER:
        forms = list(dict.fromkeys(queried_form(t) for t in source["terms"] if t["block"] == block and not t["dropped"]))
        if forms:
            groups.append(forms)
            names.append(block)
    fitted = query_compiler.fit_block_counts(query["provider_id"], groups, query.get("endpoint")) if groups else None
    if fitted is None or fitted[0] != query["query_text"]:
        return None
    return {(name, form) for name, group, count in zip(names, groups, fitted[1]) for form in group[:count]}


def plan_words(vocabulary, plan):
    """Every setting and task word of the frozen vocabulary and whether a query the plan sends carries it (D26).

    The queries sent are the OpenAlex keyword queries and, at Detailed depth, the Semantic Scholar bulk query; the
    semantic request sends the question's sentence, not these words. `searched` is false with `left_out` naming why:
    the word's own drop reason (a count of zero, too broad), `query_limit` when a sent query that held the word had no
    room for it, or `not_sent` when only a query the plan does not send held it. It is null when a sent query could
    not be read back (`_carried`), so an unknown is never shown as searched or as left out."""
    sent = [spec["query"] for spec in plan["keywords"]] + ([plan["s2_bulk"]] if plan.get("s2_bulk") else [])
    carried = [_carried(vocabulary, query) for query in sent]
    known = all(c is not None for c in carried)
    held = {(t["block"], queried_form(t)) for q in sent for t in
            (vocabulary["code_query"]["vocabulary"] if q.get("origin") == "code" else vocabulary)["terms"]
            if not t["dropped"]}
    words, seen = [], set()
    for term in vocabulary["terms"]:
        key = (term["block"], queried_form(term))
        if term["block"] not in query_compiler.BLOCK_ORDER or key in seen:
            continue
        seen.add(key)
        if term["dropped"]:
            searched, left_out = False, term["dropped"]
        elif any(c is not None and key in c for c in carried):
            searched, left_out = True, None
        elif not known:
            searched, left_out = None, None
        else:
            searched, left_out = False, "query_limit" if key in held else "not_sent"
        words.append({"block": key[0], "term": key[1], "searched": searched, "left_out": left_out})
    return words


def frozen_words(store, run_id):
    """The plan words this run's frozen protocol recorded (`plan_words`), or None for a run that froze none or whose
    plan was frozen before the record existed."""
    body = frozen_body(store, store.run(run_id))
    return (body.get("fast_path_search") or {}).get("words") if body else None


def stored_plan(store, run):
    body = frozen_body(store, run)
    if body is None:
        raise LookupError(f"run {run['id']}: no frozen protocol holds a fast-path search plan")
    return body["fast_path_search"]


def cancel_step(store, run_id, key, kind, reason, statuses=("pending",)):
    """Finish the step at `key` as cancelled with `reason` as its stop reason, when its status is one of `statuses`
    (any status when None); it sent no request and brought no record."""
    step = store.step(run_id, key, kind)
    if statuses is None or step["status"] in statuses:
        store.finish_step(step["id"], "cancelled", error_code=reason, output={"stop_reason": reason, "result_count": 0})
    return step


def close_queries(flow, run, specs, reason):
    """Close only unfinished queries; source exhaustion/failure remains its own outcome."""
    with transaction(flow.store.conn):
        for spec in specs:
            key = f"search:{spec['index']}"
            rows = flow.store.conn.execute(
                "SELECT s.id, s.output_json, sr.id AS srid, sr.provider_total, sr.read_total, sr.stop_reason"
                " FROM run_steps s JOIN search_runs sr ON sr.step_id = s.id"
                " WHERE s.run_id = ? AND (s.operation_key = ? OR s.operation_key LIKE ?)"
                " ORDER BY sr.page_number DESC, sr.rowid DESC",
                (run["id"], key, key + ":page:%")).fetchall()
            if rows:
                row = rows[0]
                if row["stop_reason"] is not None:
                    continue
                output = json.loads(row["output_json"] or "{}")
                if not output.get("next_cursor"):
                    continue
                total = row["provider_total"]
                if total is None:
                    total = next((r["provider_total"] for r in rows if r["provider_total"] is not None), None)
                unread = max(0, total - row["read_total"]) if total is not None else None
                flow.store.conn.execute(
                    "UPDATE search_runs SET stop_reason = ?, unread_count = ? WHERE id = ? AND stop_reason IS NULL",
                    (reason, unread, row["srid"]))
                flow.store.set_step_output(row["id"], output | {"stop_reason": reason})
            else:
                cancel_step(flow.store, run["id"], key, "provider_search:openalex", reason, ("pending", "running"))


async def execute(flow, run, scope, plan, retry_failed):
    store, run_id = flow.store, run["id"]
    effort = scope["effort"]
    failure = None
    # A written slot retains its size and index even when it failed. Replay walks
    # the identical round-robin schedule rather than deriving order from timestamps.
    request_index = 0
    s2_task = None

    def stopped():
        return flow._stop_requested(run_id, run["scope_revision"]) or fast_path.past_deadline(store, run, "search")

    excluded = plan.get("excluded_providers") or []

    async def send_page(query, key, *, limit, klass, index, number=0, cursor=FIRST_PAGE, before=0, total=None,
                        terminal=None, after=None):
        nonlocal failure
        if query["provider_id"] in excluded:
            # The frozen plan leaves this provider out (S23a): no request, whatever planned it.
            step = cancel_step(store, run_id, key, f"provider_search:{query['provider_id']}", user_plan.EXCLUDED)
            return store.step_output(step["id"]), 0
        connector = reading(query)
        allowance = search_page.page_allowance(query, effort, run["budget"])
        page = Page(number, cursor, before, total, plan["keyword_cap"] if klass == 1 else limit,
                    PROVIDER_WAIT[effort], key.split(":page:")[0], allowance)
        step = store.existing_step(run_id, key)
        old = (step or {}).get("output") or {}
        retry_cancelled = bool(step and step["status"] == "cancelled" and step["error_code"] == "budget_exhausted" and retry_failed)
        retry_page_only = bool(step and retry_failed and (step["status"] in ("failed", "outcome_unknown") or retry_cancelled))
        admission = old.get("fast_path_request") or {"class": klass, "request_index": index, "limit": limit}
        limit = admission["limit"]
        if step and step["status"] == "succeeded":
            return old, limit
        if step and step["status"] in ("failed", "outcome_unknown") and not retry_failed:
            return old | {"stop_reason": "page_failed"}, limit
        if step and step["status"] == "cancelled" and not retry_cancelled:
            return old, admission["limit"] if old.get("fast_path_request") else 0
        if stopped():
            return None, 0
        if flow._query_requests(run_id, page.query_key) >= allowance:
            step = store.step(run_id, key, f"provider_search:{connector.provider_id}")
            store.finish_step(step["id"], "cancelled", error_code="budget_exhausted",
                              output={"stop_reason": "budget_exhausted", "result_count": 0,
                                      "fast_path_request": admission})
            return store.step_output(step["id"]), limit
        if number:
            previous_key = page.query_key if number == 1 else f"{page.query_key}:page:{number - 1}"
            error = flow._continuation_error(store.existing_step(run_id, previous_key), connector)
            if error:
                outcome = SearchOutcome(error, "before_send", "Continuation refused", "keyless", error=error)
            else:
                outcome = None
        else:
            outcome = None
        started = now()
        transport = {}
        if outcome is None:
            outcome = await flow._send_search(run_id, connector, query, limit, page, stop=stopped, transport=transport)
        if outcome is None:
            return None, 0
        finished = now()
        if query["provider_id"] == "openalex" and klass == 1 and s2_task:
            await s2_task
        if after is not None:
            # An earlier request in admission order writes first, whichever reply came back first.
            await after
        dispatched = outcome if isinstance(outcome, facade.Dispatched) else None
        answer = dispatched.outcome if dispatched else outcome
        returned = dispatched.returned_count if dispatched else len(answer.records)
        if len(answer.records) > limit:
            overflow = len(answer.records) - limit
            answer = replace(answer, records=answer.records[:limit])
            outcome = replace(dispatched, outcome=answer, dropped_records=dispatched.dropped_records + overflow) if dispatched else answer
            dispatched = outcome if isinstance(outcome, facade.Dispatched) else None
        # The S2 adapter caps locally, since its bulk API has no page-size option.
        raw_count = len((answer.raw_payload or {}).get("data", [])) if klass == 1 and query["provider_id"] == "semantic_scholar" else returned
        admission = admission | {"returned_count": returned, "raw_returned_count": raw_count}
        ok = answer.status in ("completed", "zero_results")
        reason = "page_failed" if not ok else terminal
        if ok:
            if klass == 1 and fast_path.past_deadline(store, run, "search"):
                reason = "deadline"
            elif terminal is None and (not answer.next_cursor or not returned):
                reason = "exhausted"
            elif terminal is None and flow._query_requests(run_id, page.query_key) >= allowance:
                reason = "budget_exhausted"
            elif retry_page_only and terminal is None:
                reason = "retry_page_only"
        with transaction(store.conn):
            step = store.step(run_id, key, f"provider_search:{connector.provider_id}")
            store.start_step(step["id"], started_at=started)
            # A version 2 plan keeps the versions the question's request accepted, the only ones its first chain
            # seeds may come from (D6).
            failure = flow._record_search(run, step, query, outcome, limit, page, reason,
                                         finished, dispatched, transport, admission,
                                         keep_found=key == "search:fast:semantic" and plan.get("version") == 2) or failure
            # Failed steps also retain terminal/cursor accounting for slot replay.
            if not ok:
                store.set_step_output(step["id"], (store.step_output(step["id"]) or {}) | {
                    "stop_reason": reason, "read_total": before + returned, "provider_total": answer.provider_total})
        consumer = flow._fast_consumers.get(run_id)
        if consumer:
            consumer.notify()
        return store.step_output(step["id"]), limit

    sem = plan["semantic"]
    if sem["query_text"] is None:
        cancel_step(store, run_id, "search:fast:semantic", "provider_search:openalex", english_question.MISSING)
    else:
        result, _ = await send_page(sem, "search:fast:semantic", limit=sem["limit"], klass=0, index=0,
                                    terminal="single_page")
        if result is None and not flow._stop_requested(run_id, run["scope_revision"]):
            cancel_step(store, run_id, "search:fast:semantic", "provider_search:openalex", "deadline", None)
        consumer = flow._fast_consumers.get(run_id)
        if consumer:
            consumer.notify()
    request_index += 1
    chain = flow._fast_chains.get(run_id)
    if chain:
        chain.initial()
    flow._checkpoint(run_id, run["scope_revision"])
    # D6: each seed's own semantic request, after the chain chose its first seeds from the question's page and before
    # the keyword pages; an unseeded plan has none, so its indexes are unchanged. The requests start one pacer gap
    # apart and their replies overlap (`openalex.SEMANTIC_PACER`); each is written after the one before it, so
    # admission and candidate order follow seed order.
    async def seed_request(spec, index, previous):
        key = seed_key(spec)
        result, _ = await send_page(spec, key, limit=spec["limit"], klass=0, index=index, terminal="single_page",
                                    after=previous)
        if result is None and not flow._stop_requested(run_id, run["scope_revision"]):
            # No reply, so `send_page` never waited for the seed before this one: wait here, before writing.
            if previous is not None:
                await previous
            cancel_step(store, run_id, key, "provider_search:openalex", "deadline", ("pending", "running"))
        consumer = flow._fast_consumers.get(run_id)
        if consumer:
            consumer.notify()

    seed_tasks = []
    for spec in plan.get("seed_semantic") or []:
        seed_tasks.append(asyncio.create_task(seed_request(spec, request_index, seed_tasks[-1] if seed_tasks else None)))
        request_index += 1
    try:
        for task in seed_tasks:
            await task
    finally:
        for task in seed_tasks:
            if not task.done():
                task.cancel()
        await asyncio.gather(*seed_tasks, return_exceptions=True)
    if seed_tasks:
        flow._checkpoint(run_id, run["scope_revision"])

    async def s2_page():
        if plan["s2_bulk"] is not None:
            result, _ = await send_page(plan["s2_bulk"], "search:fast:s2_bulk", limit=plan["s2_reserved"], klass=1,
                                        index=1, terminal="single_page")
            if result is None and not flow._stop_requested(run_id, run["scope_revision"]):
                cancel_step(store, run_id, "search:fast:s2_bulk", "provider_search:semantic_scholar", "deadline", None)
        elif plan["s2_reserved"]:
            reason = user_plan.EXCLUDED if "semantic_scholar" in excluded else "not_planned"
            cancel_step(store, run_id, "search:fast:s2_bulk", "provider_search:semantic_scholar", reason)

    # Finish the independent S2 slot before admitting keyword pages (request 1).
    # Its transport overlaps the first keyword page; writes keep admission order.
    s2_task = asyncio.create_task(s2_page()) if plan["s2_reserved"] else None
    request_index += int(bool(plan["s2_reserved"]))
    specs = plan["keywords"]
    states = {s["index"]: {"number": 0, "cursor": FIRST_PAGE, "before": 0, "total": None, "ended": False} for s in specs}
    slots = 0
    try:
        # S2 writes its own earlier slot first. Different host scheduling remains
        # bounded; later keyword results cannot acquire first-admission identities.
        while any(not s["ended"] for s in states.values()):
            for spec in specs:
                state = states[spec["index"]]
                if state["ended"]:
                    continue
                key = f"search:{spec['index']}" + (f":page:{state['number']}" if state["number"] else "")
                old = store.existing_step(run_id, key)
                written = old is not None and (old["status"] in ("succeeded", "failed", "outcome_unknown")
                          or bool((old.get("output") or {}).get("fast_path_request")))
                reason = "deadline" if fast_path.past_deadline(store, run, "search") else "record_cap" if slots >= plan["keyword_cap"] else None
                if reason and not written:
                    close_queries(flow, run, specs, reason)
                    return failure
                flow._checkpoint(run_id, run["scope_revision"])
                limit = min(plan["page_size"], plan["keyword_cap"] - slots)
                old_admission = ((old or {}).get("output") or {}).get("fast_path_request")
                if old_admission:
                    limit = old_admission["limit"]
                terminal = "record_cap" if slots + limit >= plan["keyword_cap"] else None
                result, reserved = await send_page(spec["query"], key, number=state["number"], cursor=state["cursor"],
                                                   before=state["before"], total=state["total"], limit=limit, klass=1,
                                                   index=request_index, terminal=terminal)
                if result is None:
                    flow._checkpoint(run_id, run["scope_revision"])
                    close_queries(flow, run, specs, "deadline")
                    return failure
                slots += reserved
                consumer = flow._fast_consumers.get(run_id)
                if consumer:
                    consumer.notify()
                request_index += int(reserved > 0)
                state["ended"] = bool(result.get("stop_reason")) or not result.get("next_cursor")
                state["before"] = result.get("read_total", state["before"])
                state["total"] = result.get("provider_total") if result.get("provider_total") is not None else state["total"]
                state["cursor"] = result.get("next_cursor")
                state["number"] += 1
            await asyncio.sleep(0)
        if slots >= plan["keyword_cap"]:
            close_queries(flow, run, specs, "record_cap")
        elif fast_path.past_deadline(store, run, "search"):
            close_queries(flow, run, specs, "deadline")
    finally:
        if s2_task and not s2_task.done():
            await s2_task
    return failure
