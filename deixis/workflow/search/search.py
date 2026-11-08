"""Search slots and page admission; no provider or model fallbacks."""

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
from deixis.workflow.search import english_question, search_page, seed_match, user_plan
from deixis.workflow.run import fast_path
from deixis.workflow.search.search_page import Page
from deixis.workflow.search.expansion import queried_form

# At Detailed depth one Semantic Scholar bulk request reads up to this many records, taken off the keyword cap.
S2_RESERVED_RECORDS = 500
KEYWORD_PAGE_SIZE = 100  # records one OpenAlex keyword page asks for
# One more OpenAlex semantic request, its text the searched setting and task terms joined, sent after the
# question's. A plan frozen without `block_semantic`, or with one whose `query_text` is empty, sends none.
# The 6 Nov rules turned it off for new plans (113 works added, 3 in the top 50, no reference paper in that pilot): they
# freeze BLOCK_SEMANTIC_OFF and send no such request; a plan frozen under `block_terms_v1` still sends its
# request on resume.
BLOCK_SEMANTIC_KEY = "search:fast:semantic:blocks"
BLOCK_SEMANTIC_OFF = {"rule": "block_terms_off_v2", "query_text": None, "skipped": "turned_off"}


def seed_query(question, envelope):
    """The semantic query with the seed PDFs' text behind the question, which is never cut, and what of each seed went
    in. One seed: the `seed_pdf_v1` string. Several: the room the question leaves, less one separator per seed, shared
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
    """One OpenAlex semantic request per seed with text: the seed's own text (`seed_match.seed_text`) cut to what
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

    A fast path body sends its `fast_path_search` plan: the semantic request, the block terms' semantic request when the
    plan froze one, one per seed at version 2, the OpenAlex keyword queries and, at Detailed depth, the Semantic
    Scholar bulk query. The plan's dropped queries are left out:
    they stand in `compiled_queries` but were never meant to be sent. A body without the plan sends every compiled
    query under `search:<index>`. `arm` says which kind of request it is; `watchable` that a watch can follow it by
    date (a semantic request ranks by meaning, not by date); a watchable request names its `compiled_index`, the place in
    `compiled_queries` a watch's saved units are keyed by."""
    compiled = body.get("compiled_queries") or []
    plan = body.get("fast_path_search")
    if plan is None:
        return [dict(q, key=f"search:{i}", arm="keyword", watchable=q.get("origin") != "author", compiled_index=i)
                for i, q in enumerate(compiled)]
    semantic = plan["semantic"]
    sent = [{"provider_id": "openalex", "endpoint": "semantic", "query_text": semantic.get("query_text"),
             "origin": semantic.get("query_origin"), "key": "search:fast:semantic", "arm": "semantic",
             "watchable": False}]
    blocks = plan.get("block_semantic") or {}
    if blocks.get("query_text"):
        sent.append({"provider_id": "openalex", "endpoint": "semantic", "query_text": blocks["query_text"],
                     "origin": blocks["query_origin"], "key": BLOCK_SEMANTIC_KEY, "arm": "block_semantic",
                     "watchable": False})
    sent += [{"provider_id": spec["provider_id"], "endpoint": "semantic", "query_text": spec["query_text"],
              "origin": spec["origin"], "key": seed_key(spec), "arm": "seed_semantic", "watchable": False}
             for spec in plan.get("seed_semantic") or []]
    # An author query (R5) is not watchable: a watch sends the query text without the author filter.
    sent += [dict(compiled[item["index"]], key=f"search:{item['index']}", arm="keyword",
                  watchable=compiled[item["index"]].get("origin") != "author", compiled_index=item["index"])
             for item in plan["keywords"]]
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


def frozen_protocol_hash(store, run):
    """The hash of the protocol record this run froze, read from the record its protocol step names.

    The step's own output holds the hash too, but a step written before that output carried it names only the
    revision; the record is the one place the hash always is. None when this run froze no protocol.
    """
    step = store.existing_step(run["id"], "protocol")
    if step is None or step["status"] != "succeeded" or not step["output"]:
        return None
    row = store.conn.execute(
        "SELECT body_sha256 FROM protocol_records WHERE research_id = ? AND protocol_revision = ?",
        (run["research_id"], step["output"]["protocol_revision"])).fetchone()
    return row[0] if row else None


def plan_version(store, run):
    """The `fast_path_search` version this run's protocol froze: 1 when it froze none or no protocol is frozen yet."""
    body = frozen_body(store, run)
    return (body.get("fast_path_search") or {}).get("version", 1) if body else 1


def graph_rule(store, run):
    """The graph rule the ranking reads, chosen by the frozen plan, never by live code: a version 2 plan ranks the
    seed PDFs by their nearest one (`seed_max_v2`), every other run as before (`sum_v1`)."""
    return "seed_max_v2" if plan_version(store, run) == 2 else "sum_v1"


def seeded_question(seed_context):
    """Whether the seed PDFs ask OpenAlex on their own (`seed_pdf_v2`), which leaves the question's request unseeded."""
    return bool(seed_context) and seed_context.get("rule") == seed_match.RULE


def semantic_spec(scope, policy, seed_context=None):
    """The question's own semantic request, written by code alone: no translation, no rewriting, no model call.

    It carries the person's own sentence, in whatever language they wrote it. The revision's English sentence is read
    by the ranking signals that need English (`ranking.comparison`, the built-in embedding); it no longer decides
    whether this request is sent, so a question in another language waits for no translation. At version 2 each seed
    PDF asks on its own, so the question's request is unseeded; at version 1 a seed's text rides behind the question
    and the ranking keeps the question alone. `build_plan` freezes exactly this spec, and `first_semantic` sends it
    before anything plans, so the two cannot drift apart (P2)."""
    question = scope["question"]
    seed, parts = None, []
    if seed_context and not seeded_question(seed_context):
        question, seed, parts = seed_query(question, seed_context)
    return {"provider_id": "openalex", "endpoint": "semantic",
            "query_text": openalex.semantic_text(question), "limit": policy["semantic_top"],
            "query_origin": "question",
            **({"seed_text": seed} if seed else {}),
            **({"seed_parts": parts} if seed_context and not seeded_question(seed_context) else {})}


def first_request_plan(run, scope, seed_context=None):
    """What the question's semantic request needs before anything plans: the request itself, the plan version its
    record keeping reads (`keep_found` at version 2) and the providers a person's saved plan left out.

    It is not a frozen plan and nothing stores it: the protocol still freezes the whole plan `build_plan` builds,
    with this same request in it (Ç1)."""
    policy = run["budget"]["fast_path"]
    return {"version": 2 if seeded_question(seed_context) else 1,
            "semantic": semantic_spec(scope, policy, seed_context),
            **({"excluded_providers": user_plan.excluded(scope)} if user_plan.of(scope) is not None else {})}


def build_plan(store, run, scope, queries, seed_context=None, vocabulary=None):
    """The frozen search plan. With `vocabulary` (every discovery run since `block_terms_v1`) it also freezes `block_semantic`:
    under `block_terms_v1` the block terms' semantic request, since the 6 Nov rules the record that it is off (`BLOCK_SEMANTIC_OFF`). A plan
    built without a vocabulary, as every plan before `block_terms_v1` was, has none."""
    policy = run["budget"]["fast_path"]
    if seeded_question(seed_context):
        # The question's request is the unseeded one; each seed asks OpenAlex on its own, after it.
        plan = build_plan(store, run, scope, queries, vocabulary=vocabulary)
        return plan | {"version": 2, "seed_semantic": seed_requests(seed_context, policy["semantic_top"] // 2)}
    deep = policy["mode"] == "deep"
    # The providers a person left out of a saved search plan get no request (S23a); OpenAlex cannot be left out.
    excluded = user_plan.excluded(scope)
    keyword = [{"index": i, "query": q} for i, q in enumerate(queries) if q["provider_id"] == "openalex"]
    s2_index = next((i for i, q in enumerate(queries)
                     if deep and q["provider_id"] == "semantic_scholar" and q.get("endpoint") == "bulk"
                     and "semantic_scholar" not in excluded), None)
    s2 = queries[s2_index] if s2_index is not None else None
    return {"version": 1, "semantic": semantic_spec(scope, policy, seed_context),
            **({"block_semantic": dict(BLOCK_SEMANTIC_OFF)} if vocabulary is not None else {}),
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
    (the code's beside a model-written one). Only when the text it gives is the stored text are its counts taken;
    any other text says nothing about what the stored query holds. A statement research's author query (R5) holds
    the field's root word alone, which the code query holding the field also carries, so it adds no pair."""
    if query.get("origin") == "author":
        return set()
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
    """Every setting and task word of the frozen vocabulary and whether a query the plan sends carries it.

    The queries sent are the OpenAlex keyword queries and, at Detailed depth, the Semantic Scholar bulk query; the
    semantic requests send the question's sentence and, in a plan frozen under `block_terms_v1` (no longer
    sent), these words joined
    (`block_semantic`), so they are not counted here. `searched` is false with `left_out` naming why:
    the word's own drop reason (a count of zero, too broad), `query_limit` when a sent query that held the word had no
    room for it, or `not_sent` when only a query the plan does not send held it. It is null when a sent query could
    not be read back (`_carried`), so an unknown is never shown as searched or as left out. A plan with
    `block_semantic` also records `semantic`: whether the word's phrase stands in the text of the block terms'
    semantic request it sends, so a word left out of every keyword query is not shown as never sent."""
    sent = [spec["query"] for spec in plan["keywords"]] + ([plan["s2_bulk"]] if plan.get("s2_bulk") else [])
    semantic = (plan["block_semantic"].get("query_text") or "") if "block_semantic" in plan else None
    carried = [_carried(vocabulary, query) for query in sent]
    known = all(c is not None for c in carried)
    held = {(t["block"], queried_form(t)) for q in sent if q.get("origin") != "author" for t in
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
        words.append({"block": key[0], "term": key[1], "searched": searched, "left_out": left_out,
                      **({"semantic": not term["dropped"] and term["phrase"] in semantic} if semantic is not None else {})})
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


def page_sender(flow, run, scope, plan, retry_failed, shared):
    """The one function that sends a page of a search and records it, and the stop it reads.

    `shared` carries what the callers share: `failure` is the failure to report, `s2_task` the Semantic Scholar slot
    whose write comes before the first keyword page. `first_semantic` and `execute` each build their own sender, so
    the question's request can go out before anything plans and the search stage can send the rest later (P2)."""
    store, run_id = flow.store, run["id"]
    effort = scope["effort"]

    def stopped():
        return flow._stop_requested(run_id, run["scope_revision"]) or fast_path.past_deadline(store, run, "search")

    excluded = plan.get("excluded_providers") or []

    async def send_page(query, key, *, limit, klass, index, number=0, cursor=FIRST_PAGE, before=0, total=None,
                        terminal=None, after=None):
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
        if query["provider_id"] == "openalex" and klass == 1 and shared["s2_task"]:
            await shared["s2_task"]
        if after is not None:
            # An earlier request in admission order writes first, whichever reply came back first.
            await after
        dispatched = outcome if isinstance(outcome, facade.Dispatched) else None
        answer = dispatched.outcome if dispatched else outcome
        returned = dispatched.returned_count if dispatched else len(answer.records)
        if len(answer.records) > limit:
            overflow = len(answer.records) - limit
            answer = replace(answer, records=answer.records[:limit])
            # The cap keeps the first records, so the places admission reported are cut the same way; a dispatch whose
            # places outnumbered its records would say nothing about which record stood where.
            outcome = (replace(dispatched, outcome=answer, dropped_records=dispatched.dropped_records + overflow,
                               kept_positions=dispatched.kept_positions[:limit]) if dispatched else answer)
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
            # seeds may come from.
            shared["failure"] = flow._record_search(
                run, step, query, outcome, limit, page, reason, finished, dispatched, transport, admission,
                keep_found=key == "search:fast:semantic" and plan.get("version") == 2) or shared["failure"]
            # Failed steps also retain terminal/cursor accounting for slot replay.
            if not ok:
                store.set_step_output(step["id"], (store.step_output(step["id"]) or {}) | {
                    "stop_reason": reason, "read_total": before + returned, "provider_total": answer.provider_total})
        consumer = flow._fast_consumers.get(run_id)
        if consumer:
            consumer.notify()
        return store.step_output(step["id"]), limit

    return send_page


async def question_semantic(flow, run, plan, send_page):
    """Send the question's own semantic request, then let the chain read its page.

    A run calls this twice: once before anything plans (`first_semantic`) and once from the search stage, which finds
    the step `succeeded` and sends nothing more. The step key is `search:fast:semantic` in both, so the request goes
    out once; semantic search is single-page, so there is no second page to continue (P2, Argon's blocker). The chain
    is seeded here only when it exists, which is after the protocol froze: the early call finds none, and the search
    stage's call seeds it from the stored page."""
    store, run_id = flow.store, run["id"]
    sem = plan["semantic"]
    if sem["query_text"] is None:
        # A plan frozen before the request carried the person's own sentence has no text when the question is not
        # English and no sentence was stored. A resumed run reads that plan back, so this branch stays for it; a plan
        # built now always has the question.
        cancel_step(store, run_id, "search:fast:semantic", "provider_search:openalex", english_question.MISSING)
    else:
        result, _ = await send_page(sem, "search:fast:semantic", limit=sem["limit"], klass=0, index=0,
                                    terminal="single_page")
        if result is None and not flow._stop_requested(run_id, run["scope_revision"]):
            cancel_step(store, run_id, "search:fast:semantic", "provider_search:openalex", "deadline", None)
        consumer = flow._fast_consumers.get(run_id)
        if consumer:
            consumer.notify()
    chain = flow._fast_chains.get(run_id)
    if chain:
        chain.initial()
    flow._checkpoint(run_id, run["scope_revision"])


async def first_semantic(flow, run, scope, seed_context=None, sent=None):
    """The question's semantic request, sent before any step that plans (P2).

    The design's first step needs no translation, rewriting or model call, so this request goes out in whatever
    language the person wrote, right after the seed match, and every planning step runs while it is in flight. The
    step is opened before the request is sent, so it carries `protocol_hash = NULL` as the seed match's requests do
    (Ç1), and it keeps the `search:fast:semantic` key, so the search stage finds it succeeded and sends nothing
    twice. `sent` is set once the request is on its way, so the caller goes on without waiting for the reply.

    A request that failed here is not reported: the search stage retries it, as it retries a resumed run's failures
    (`retry_failed`), which is why this call never asks for a retry of its own."""
    shared = {"failure": None, "s2_task": None}
    try:
        # Everything that can fail before the request is sent sits inside this block, so `sent` is set on the way
        # out whatever happens and the planning arm waiting on it raises instead of waiting forever.
        # A run whose own protocol is already frozen sends what that protocol holds, never a freshly built request:
        # on a resume the frozen plan is the record of what this run searches, and a plan frozen before the request
        # carried the person's own sentence holds a different one (its own English sentence, or no text at all, which
        # cancels the request). Building a new one here would send what the protocol does not name.
        frozen = frozen_body(flow.store, run)
        plan = (frozen.get("fast_path_search") or first_request_plan(run, scope, seed_context)) if frozen \
            else first_request_plan(run, scope, seed_context)
        # The step belongs to the protocol whose plan is being sent: this run's own, or none when it has frozen none.
        # The research's current protocol would be the wrong answer in both directions — a later run of the same scope
        # revision may have frozen a newer one since, and a run that has frozen nothing would take that one's hash.
        hash_of = frozen_protocol_hash(flow.store, run) if frozen else None
        # Opened here whether or not there is text to send, so the row carries the protocol this call decided on: a
        # plan with no text is cancelled a moment later, and `cancel_step` would otherwise open the row itself and
        # take the research's current protocol. Opened before this run's freeze it carries no hash, whatever an
        # earlier run of the same scope revision froze (Ç1); on a resume after this run's own freeze, that hash.
        flow.store.step(run["id"], "search:fast:semantic", "provider_search:openalex", protocol_hash=hash_of)
        send_page = page_sender(flow, run, scope, plan, False, shared)
    finally:
        if sent is not None:
            sent.set()
    await question_semantic(flow, run, plan, send_page)
    return shared["failure"]


async def execute(flow, run, scope, plan, retry_failed):
    store, run_id = flow.store, run["id"]
    shared = {"failure": None, "s2_task": None}
    send_page = page_sender(flow, run, scope, plan, retry_failed, shared)
    # A written slot retains its size and index even when it failed. Replay walks
    # the identical round-robin schedule rather than deriving order from timestamps.
    request_index = 0
    excluded = plan.get("excluded_providers") or []
    await question_semantic(flow, run, plan, send_page)
    request_index += 1
    # The block terms' semantic request, after the question's (whose page alone chooses the first chain seeds);
    # a plan frozen without it, or one that skipped it, sends nothing and keeps its request indexes.
    blocks = plan.get("block_semantic") or {}
    if blocks.get("query_text"):
        result, _ = await send_page(blocks, BLOCK_SEMANTIC_KEY, limit=blocks["limit"], klass=0, index=request_index,
                                    terminal="single_page")
        if result is None and not flow._stop_requested(run_id, run["scope_revision"]):
            cancel_step(store, run_id, BLOCK_SEMANTIC_KEY, "provider_search:openalex", "deadline", None)
        consumer = flow._fast_consumers.get(run_id)
        if consumer:
            consumer.notify()
        request_index += 1
        flow._checkpoint(run_id, run["scope_revision"])
    # Each seed's own semantic request, after the chain chose its first seeds from the question's page and before
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
    shared["s2_task"] = asyncio.create_task(s2_page()) if plan["s2_reserved"] else None
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
                    return shared["failure"]
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
                    return shared["failure"]
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
        if shared["s2_task"] and not shared["s2_task"].done():
            await shared["s2_task"]
    return shared["failure"]
