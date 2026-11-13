"""Search slots and page admission; no provider or model fallbacks."""

from __future__ import annotations

import asyncio
import json
import sys
from dataclasses import replace

from deixis.domain.rules import SOURCE_ROUTES
from deixis.providers import common, facade
from deixis.providers.common import FIRST_PAGE, SearchOutcome
from deixis.providers.registry import CONNECTORS, broad_index_providers, date_bound_form, reading
from deixis.storage.db import now, transaction
from deixis.providers import openalex, query_compiler
from deixis.workflow.search import mesh
from deixis.workflow.search import (completion, date_scope, english_question, routing, search_page, search_plan,
                                    search_query, seed_match, user_plan)
from deixis.workflow.run import fast_path
from deixis.workflow.search.search_page import Page
from deixis.workflow.search.expansion import queried_form

# At Detailed depth one Semantic Scholar bulk request reads up to this many records, taken off the keyword cap —
# and only when that request is really planned. A depth that reserves for a request it will not send spends the
# records on nothing: the share goes back to the keyword queries, which are the open-scope question's own.
S2_RESERVED_RECORDS = 500
KEYWORD_PAGE_SIZE = 100  # records one OpenAlex keyword page asks for
# The admission class of a field source's pages: behind the question's own requests (class 0) and the keyword pages
# (class 1), so a record two sources bring keeps the place the question's own index gave it.
FIELD_CLASS = 2
# The admission class of the second independent index's pages: behind the field source's, so a record both
# bring keeps the place the source the question's own distribution pointed at gave it.
BROAD_CLASS = 3
# The admission class of the short phrase searches' pages: behind every planned request, so a record a planned request
# also brings keeps the place that request gave it.
PHRASE_CLASS = 4
# The admission class of the plain phrase requests' pages: behind the semantic phrase requests, so a record both bring
# keeps the place the semantic request gave it.
PLAIN_PHRASE_CLASS = 5
# The step key of one short phrase request, by the phrase's place in the step's answer.
PHRASE_KEY = "search:fast:semantic:phrase:"
# The step key of the same phrase's plain request (`phrase_search_v2`), by the same place.
PLAIN_PHRASE_KEY = "search:fast:plain:phrase:"
# One more OpenAlex semantic request, its text the searched setting and task terms joined, sent after the
# question's. A plan frozen without `block_semantic`, or with one whose `query_text` is empty, sends none.
# The 6 Nov rules turned it off for new plans (113 works added, 3 in the top 50, no reference paper in that pilot): they
# freeze BLOCK_SEMANTIC_OFF and send no such request; a plan frozen under `block_terms_v1` still sends its
# request on resume.
BLOCK_SEMANTIC_KEY = "search:fast:semantic:blocks"
BLOCK_SEMANTIC_OFF = {"rule": "block_terms_off_v2", "query_text": None, "skipped": "turned_off"}


def with_date_scope(query, years):
    """`query` with this run's date scope in the bound its own route takes, or unchanged where it takes none.

    The route decides, not the provider: OpenAlex's keyword route takes the publication dates, its semantic route
    only `publication_year`, Semantic Scholar's bulk search and PubMed's ESearch a year range
    (`date_scope.provider_bound`, `registry.date_bound_form`). A route that takes no bound is searched unbounded;
    `sent_plan` says so for every planned request, so nothing reads a bound back that never left with one.

    An OpenAlex filter is joined to any the query already carries — a statement research's author filter — with a
    comma, which is OpenAlex's own AND, so both hold.
    """
    bound = date_scope.provider_bound(date_bound_form(query), years, query.get("endpoint"))
    if not bound:
        return query
    if "works_filter" in bound:
        bound = {"works_filter": date_scope.with_filter(query.get("works_filter"), bound["works_filter"])}
    return query | bound


def carried_bound(query):
    """The bound a planned request really carries, where its plan kept a copy of the query that holds one.

    A stored plan whose keyword entry names only its index keeps none, and the row then reads as the compiled
    query does: nothing is written in that the plan does not say.
    """
    return {key: query[key] for key in date_scope.BOUND_KEYS if (query or {}).get(key)} if query else {}


def date_bound(years, query):
    """How a planned request stands to this run's date scope, read from the request itself.

    `applied` means the request really carries the bound, so the provider never answered outside it.
    `not_supported` means its own route takes none, so it was sent unbounded and whatever it brought is bounded, if
    at all, only after the search. `not_applied` is a request whose route takes a bound that the plan does not
    carry — a plan frozen before this run's scope was read, resumed as it stands. A run that bounds no years
    records none of the three.
    """
    if not years:
        return {}
    expected = date_scope.provider_bound(date_bound_form(query), years, query.get("endpoint"))
    if not expected:
        return {"date_bound": "not_supported"}
    (key, value), = expected.items()
    return {"date_bound": "applied" if value in (query.get(key) or "") else "not_applied"}


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


def seed_requests(envelope, limit, years=None):
    """One OpenAlex semantic request per seed with text: the seed's own text (`seed_match.seed_text`) cut to what
    OpenAlex accepts, in seed order; a seed with no text sends nothing. `index` is the seed's place in the envelope.

    A seed's request is a search of the person's question like any other, so it carries the run's date scope too: a
    seed PDF says what to look for, not which years to look in.
    """
    specs = []
    for i, context in enumerate(envelope["seeds"]):
        text, origin = seed_match.seed_text(context)
        if text.strip():
            specs.append(with_date_scope(
                {"index": i, "source_version_id": context["source_version_id"], "origin": origin,
                 "provider_id": "openalex", "endpoint": "semantic",
                 "query_text": openalex.semantic_text(text), "limit": limit}, years))
    return specs


def seed_key(spec):
    return f"search:fast:semantic:seed:{spec['index']}"


def phrase_key(index):
    return f"{PHRASE_KEY}{index}"


def plain_phrase_key(index):
    return f"{PLAIN_PHRASE_KEY}{index}"


def sent_plan(body):
    """The requests a frozen protocol body plans to send, each with the step key its pages are stored under.

    A fast path body sends its `fast_path_search` plan: the semantic request, the block terms' semantic request when the
    plan froze one, one per seed at version 2, the OpenAlex keyword queries, the query of each field source the depth
    searches, the query of the second independent index a depth that pays for one plans, and, at Detailed depth,
    the Semantic Scholar bulk query; each short phrase request where the plan froze phrases, and its plain request
    under the second phrase rule. The plan's dropped
    queries are left out:
    they stand in `compiled_queries` but were never meant to be sent. A body without the plan sends every compiled
    query under `search:<index>`. A field source's query carries the text that is really sent, which is the
    compiled text with PubMed's own headings written in where the plan froze them. `arm` says which kind of
    request it is; `watchable` that a watch can follow it by
    date (a semantic request ranks by meaning, not by date); a watchable request names its `compiled_index`, the place in
    `compiled_queries` a watch's saved units are keyed by."""
    compiled = body.get("compiled_queries") or []
    plan = body.get("fast_path_search")
    if plan is None:
        return [dict(q, key=f"search:{i}", arm="keyword", watchable=q.get("origin") != "author", compiled_index=i)
                for i, q in enumerate(compiled)]
    semantic = plan["semantic"]
    # The years this run searches in, as its plan froze them, and for each request below how it stands to them
    # (`date_bound`): it carries the bound, its route takes none, or its plan was frozen before the years were
    # read. A plan frozen before the rule names no years and every row reads as it did.
    years = plan.get("date_scope")
    sent = [{"provider_id": "openalex", "endpoint": "semantic", "query_text": semantic.get("query_text"),
             "origin": semantic.get("query_origin"), "key": "search:fast:semantic", "arm": "semantic",
             "watchable": False, **date_bound(years, semantic)}]
    blocks = plan.get("block_semantic") or {}
    if blocks.get("query_text"):
        sent.append({"provider_id": "openalex", "endpoint": "semantic", "query_text": blocks["query_text"],
                     "origin": blocks["query_origin"], "key": BLOCK_SEMANTIC_KEY, "arm": "block_semantic",
                     "watchable": False, **date_bound(years, blocks)})
    sent += [{"provider_id": spec["provider_id"], "endpoint": "semantic", "query_text": spec["query_text"],
              "origin": spec["origin"], "key": seed_key(spec), "arm": "seed_semantic", "watchable": False,
              **date_bound(years, spec)}
             for spec in plan.get("seed_semantic") or []]
    # Each short phrase request the plan froze (`phrase_search`); a plan frozen before the rule, or whose phrase step
    # gave no phrases before the freeze, has none.
    sent += [{"provider_id": spec["provider_id"], "endpoint": "semantic", "query_text": spec["query_text"],
              "origin": "phrase", "key": phrase_key(spec["index"]), "arm": "phrase_semantic", "watchable": False,
              **date_bound(years, spec)}
             for spec in (plan.get("phrase_search") or {}).get("requests") or []]
    # The same phrases' plain requests, where the plan froze them under the second phrase rule.
    sent += [{"provider_id": spec["provider_id"], "endpoint": spec["endpoint"], "query_text": spec["query_text"],
              "origin": "phrase", "key": plain_phrase_key(spec["index"]), "arm": "phrase_plain", "watchable": False,
              **date_bound(years, spec)}
             for spec in (plan.get("phrase_search") or {}).get("plain_requests") or []]
    # An author query is not watchable: a watch sends the query text without the author filter. The bound the
    # plan's own copy carries is written in, so a recorded request reads with what it was really sent with.
    sent += [dict(compiled[item["index"]], key=f"search:{item['index']}", arm="keyword",
                  watchable=compiled[item["index"]].get("origin") != "author", compiled_index=item["index"],
                  **date_bound(years, item.get("query") or compiled[item["index"]]))
             | carried_bound(item.get("query"))
             for item in plan["keywords"]]
    # The field sources this depth pays for: one planned request each, under the page key its own walk writes. The
    # text here is the text the page really sends, expansion and all, because this list is what the PRISMA-S trace
    # and the Methods box read a recorded search back against; the plan's own word record reads the compiled text.
    sent += [dict(compiled[spec["index"]], key=f"search:{spec['index']}", arm="field",
                  watchable=compiled[spec["index"]].get("origin") != "author", compiled_index=spec["index"],
                  **date_bound(years, spec.get("query") or compiled[spec["index"]]))
             | mesh.sent_text(spec["query"])
             | carried_bound(spec.get("query"))
             for spec in plan.get("field") or []]
    # The second independent index, where the plan froze one: one planned request under its own page key. No watch
    # follows it — a watch asks its provider for what is new by date, and this index is searched for the breadth of
    # one run's first list.
    if plan.get("broad"):
        spec = plan["broad"]
        sent.append(dict(compiled[spec["index"]], key=f"search:{spec['index']}", arm="broad_index",
                         watchable=False, compiled_index=spec["index"],
                         **date_bound(years, spec.get("query") or compiled[spec["index"]]))
                    | carried_bound(spec.get("query")))
    # The one sub-topic search of that index, where the plan froze one: a planned request that goes out only if
    # its own condition still holds, so it is listed here (a cancelled step reads as `not_sent`) and no watch
    # follows it either.
    if plan.get("subtopic"):
        spec = plan["subtopic"]
        sent.append(dict(compiled[spec["index"]], key=f"search:{spec['index']}", arm="subtopic",
                         watchable=False, compiled_index=spec["index"],
                         **date_bound(years, spec.get("query") or compiled[spec["index"]]))
                    | carried_bound(spec.get("query")))
    if plan.get("s2_bulk"):
        sent.append(dict(plan["s2_bulk"], key="search:fast:s2_bulk", arm="s2_bulk", watchable=True,
                         compiled_index=plan["s2_bulk_index"],
                         **date_bound(years, plan["s2_bulk"])))
    # The completion arm, when the run froze one: a planned request that goes out only if its own condition holds, so
    # it is listed here (the PRISMA reader marks a cancelled step `not_sent`) and no watch follows it.
    if plan.get("s2_relevance"):
        sent.append(dict(plan["s2_relevance"], key=completion.RELEVANCE_KEY, arm="s2_relevance", watchable=False,
                         **date_bound(years, plan["s2_relevance"])))
    sent += [{k: v for k, v in spec.items() if k not in ("index", "focused")}
             | {"key": completion.snippet_key(position), "arm": "s2_snippet", "watchable": False}
             | date_bound(years, spec)
             for position, spec in enumerate(plan.get("s2_snippet") or [])]
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
    # The run's own date scope rides with this request, which is the first one sent: it goes out before anything
    # plans, so a bound read only at plan time would miss it (`fast_path.DATE_SCOPE_RULE`).
    return with_date_scope(
        {"provider_id": "openalex", "endpoint": "semantic",
         "query_text": openalex.semantic_text(question), "limit": policy["semantic_top"],
         "query_origin": "question",
         **({"seed_text": seed} if seed else {}),
         **({"seed_parts": parts} if seed_context and not seeded_question(seed_context) else {})},
        policy.get("date_scope"))


def first_request_plan(run, scope, seed_context=None):
    """What the question's semantic request needs before anything plans: the request itself, the plan version its
    record keeping reads (`keep_found` at version 2) and the providers a person's saved plan left out.

    It is not a frozen plan and nothing stores it: the protocol still freezes the whole plan `build_plan` builds,
    with this same request in it (Ç1)."""
    policy = run["budget"]["fast_path"]
    return {"version": 2 if seeded_question(seed_context) else 1,
            "semantic": semantic_spec(scope, policy, seed_context),
            **({"excluded_providers": user_plan.excluded(scope)} if user_plan.of(scope) is not None else {})}


def routing_record(store, run):
    """The routing record this run stored (`flow._source_routing`), or None where the step has not succeeded.

    A run whose routing step never ran — an older run, a research whose scope holds no domain source — has none,
    and a plan built without a record searches OpenAlex alone, as every plan did before the field sources were bound
    to this path.
    """
    step = store.existing_step(run["id"], "source_routing")
    return ((step or {}).get("output") or {}).get("routing") if step and step["status"] == "succeeded" else None


def field_plan(store, run, scope, queries, policy, excluded):
    """The field sources this depth searches, and why every other planned query is not sent.

    The depth's own numbers say how many sources it pays for and how many records each may read (`field_search` in
    the frozen policy); the stored routing record says which sources the question's own field distribution points
    at, and `routing.field_sources` puts them in order. One query per source: the main query compiled for it. A
    second query of the same source, a source the depth does not pay for and a source the distribution could not
    choose are each recorded with their own reason, so what was not sent is readable beside what was.
    """
    rule = policy.get("field_search") or {}
    chosen = routing.field_sources(routing_record(store, run), rule.get("sources", 0)) if rule else []
    # The research's own sources, read now rather than from the record: a source the person has since taken out of
    # the research is not searched, whatever the routing chose while it was in.
    in_scope = set(scope["providers"])
    first = {}
    for index, query in enumerate(queries):
        first.setdefault(query["provider_id"], index)
    specs, reasons = [], {}
    for row in chosen:
        if row["provider_id"] in excluded or row["provider_id"] not in in_scope:
            # The person's own scope outranks the stored record: a source they left out, or took out of the
            # research, is not searched, whatever the routing chose while it was in.
            continue
        index = first.get(row["provider_id"])
        if index is None:
            # The routing chose it and no query was compiled for it: recorded, never silently left out.
            reasons[row["provider_id"]] = "query_not_compiled"
            continue
        specs.append({"index": index, "query": queries[index], "records": rule["records"],
                      "request_index": len(specs), "share": row["share"], "independent": row["independent"]})
    sent = {spec["index"] for spec in specs}
    searched = {spec["query"]["provider_id"] for spec in specs}
    record = routing_record(store, run)
    read = bool(record) and record.get("status") == "read"
    dropped = []
    for index, query in enumerate(queries):
        provider = query["provider_id"]
        if provider == "openalex" or index in sent:
            continue
        if provider in excluded:
            reason = user_plan.EXCLUDED
        elif provider not in in_scope:
            # Out of the research's own sources, which is not the same as left out of a saved plan.
            reason = "not_in_scope"
        elif provider in searched:
            reason = "one_query_per_field_source"
        elif provider in SOURCE_ROUTES:
            reason = ("depth_searches_no_field_source" if not rule.get("sources")
                      else "field_share_not_read" if not read else "after_the_depth_s_field_source")
        else:
            reason = "openalex_only"
        dropped.append({"index": index, "query": query, "reason": reason})
    return specs, dropped, reasons


def broad_plan(run, scope, queries, excluded, field_specs):
    """The second independent index this depth searches, and why it searches none.

    The depth's own numbers say whether it pays for one and how many records it may read (`broad_index` in the
    frozen policy). The arm the run froze says when it is searched: `always` on every run of a depth that pays for
    one, `conditional` only where this run's plan names no independent field source of its own. A field source
    whose query goes through another provider's host is not an independent index, so a run whose only field source
    is such a source still searches this one; so does a run whose field distribution was never read, which has no
    share to choose a source by.

    Returns the spec and the provider, the compiled query it owns and why nothing is sent. The query is named
    even where nothing is sent, so it is not also reported as a field source that lost its place.
    """
    rule = fast_path.broad_index(run["budget"])
    if not rule:
        # Queued before the rule, or with the `off` arm: nothing planned and nothing to report.
        return None, None
    in_scope = [p for p in broad_index_providers() if p in scope["providers"]]
    provider = next(iter(in_scope or broad_index_providers()), None)
    if provider is None:
        return None, None
    # The one query this arm owns, whether or not it is sent: a connector gets one compiled query per provider.
    index = next((i for i, query in enumerate(queries) if query["provider_id"] == provider), None)
    told = {"provider_id": provider, "index": index}
    if not in_scope:
        return None, told | {"reason": "not_in_scope"}
    if not rule["records"]:
        return None, told | {"reason": "depth_pays_for_no_broad_index"}
    if rule["arm"] == "conditional" and any(spec.get("independent") for spec in field_specs):
        # This run already searches an index of its own beside OpenAlex, which is what the second one is for.
        return None, told | {"reason": "independent_field_source_planned"}
    if provider in excluded:
        return None, told | {"reason": user_plan.EXCLUDED}
    if CONNECTORS[provider].access_mode() == "not_configured":
        return None, told | {"reason": "not_configured"}
    if index is None:
        # The compiler's query limit left it none: recorded, never silently left out.
        return None, told | {"reason": "query_not_compiled"}
    # The records of one page, frozen here: the walk reserves what a page asked for, and a provider whose adapter
    # serves fewer records than the page asked for would spend the whole share on one page.
    page_size = (run["budget"]["fast_path"].get("uniform_search") or {}).get("keyword_page_size", KEYWORD_PAGE_SIZE)
    page_records = min(page_size, reading(queries[index]).max_results)
    return ({"index": index, "query": queries[index], "records": rule["records"], "page_records": page_records,
             "request_index": 0, "arm": rule["arm"]}, told)


def subtopic_plan(run, scope, queries, vocabulary, excluded, broad_spec, field_specs):
    """The one sub-topic search this depth sends of the broad index, and why it sends none.

    The design gives a depth that pays for no second index of its own one request instead: after its field source
    has been searched, a part of the question the plan named that the records found so far still do not carry is
    asked of that index on its own. Whether the gap is still open is read in the search stage, after the field
    source's last page; this plans the request and reserves its records.

    Three things must hold before a paid request is planned at all, and each is recorded when it does not.
    The depth must really search a field source, since the design's condition is what is still unmet **after**
    that source. The plan must have named the sub-topic — read from the plan's own answer, so a concept the
    compiler could not fit is not reported as a concept nobody named. And the sub-topic must be one the question
    itself names (`search_plan.question_subtopic`): the plan's concepts are a model's reading of the first page
    of results, and no money is spent on a sub-problem only the model inferred.

    The query is not written here: `search_plan.focused_queries` already renders a named concept beside the main
    query's terms for every searchable provider, this index included, so the request carries a compiled query like
    any other.

    Returns the spec and the provider, every compiled query this arm owns and why nothing is sent.
    """
    rule = fast_path.subtopic_search(run["budget"])
    if not rule:
        # Queued before the rule, or with the `off` arm: nothing planned and nothing to report.
        return None, None
    in_scope = [p for p in broad_index_providers() if p in scope["providers"]]
    provider = next(iter(in_scope or broad_index_providers()), None)
    if provider is None:
        return None, None
    # Every focused query compiled for that index: this depth sends at most one sub-topic search of it, so they
    # are all this arm's to report and none of them is a field source that lost its place.
    owned = [i for i, query in enumerate(queries)
             if query["provider_id"] == provider and query.get("role") == "focused"]
    told = {"provider_id": provider, "indexes": owned}
    if not in_scope:
        return None, told | {"reason": "not_in_scope"}
    if broad_spec is not None:
        # This depth already searches that index on its own; one query per source stands. Read before the depth's
        # own records, because on such a depth both hold and this is the one that says what really happened.
        return None, told | {"reason": "broad_index_planned"}
    if not rule["records"]:
        return None, told | {"reason": "depth_pays_for_no_subtopic_search"}
    if not field_specs:
        # No field source is searched, so there is no "after the field source" for the condition to be read at.
        return None, told | {"reason": "no_field_source_planned"}
    if provider in excluded:
        return None, told | {"reason": user_plan.EXCLUDED}
    if CONNECTORS[provider].access_mode() == "not_configured":
        return None, told | {"reason": "not_configured"}
    named = (search_plan.plan_answer(vocabulary).get("focused") or []) if vocabulary else []
    if not named:
        return None, told | {"reason": "no_subtopic_named"}
    terms = [entry["term"] for entry in named
             if search_plan.question_subtopic(scope["question"], vocabulary, entry["term"])]
    if not terms:
        # Every concept the plan named is the model's own reading, not a sub-topic the question states.
        return None, told | {"reason": "subtopic_not_in_question"}
    index = next((i for i in owned if queries[i]["focused"]["term"] in terms), None)
    if index is None:
        # The depth's Boolean plan budget or this provider's own rules left that concept without a query;
        # `focused_record` says which of the two.
        return None, told | {"reason": "query_not_compiled"}
    return ({"index": index, "query": queries[index], "records": rule["records"], "request_index": 0,
             "arm": rule["arm"], "focused": dict(queries[index]["focused"])}, told)


def build_plan(store, run, scope, queries, seed_context=None, vocabulary=None):
    """The frozen search plan. With `vocabulary` (every discovery run since `block_terms_v1`) it also freezes `block_semantic`:
    under `block_terms_v1` the block terms' semantic request, since the 6 Nov rules the record that it is off (`BLOCK_SEMANTIC_OFF`). A plan
    built without a vocabulary, as every plan before `block_terms_v1` was, has none."""
    policy = run["budget"]["fast_path"]
    if seeded_question(seed_context):
        # The question's request is the unseeded one; each seed asks OpenAlex on its own, after it.
        plan = build_plan(store, run, scope, queries, vocabulary=vocabulary)
        seed_top = (policy.get("uniform_search") or {}).get("seed_semantic_top", policy["semantic_top"] // 2)
        return plan | {"version": 2, "seed_semantic": seed_requests(seed_context, seed_top,
                                                                   policy.get("date_scope"))}
    deep = policy["mode"] == "deep" and "uniform_search" not in policy
    # The providers a person left out of a saved search plan get no request (S23a); OpenAlex cannot be left out.
    excluded = user_plan.excluded(scope)
    # The years this run searches in, frozen with the rest of the policy before the first request opened. Every
    # query below is bounded by it where its route takes a bound, so the plan is also the record of what each
    # request was sent with: `sent_plan` reads it back per request.
    years = policy.get("date_scope")
    keyword = [{"index": i, "query": with_date_scope(q, years)}
               for i, q in enumerate(queries) if q["provider_id"] == "openalex"]
    s2_index = next((i for i, q in enumerate(queries)
                     if deep and q["provider_id"] == "semantic_scholar" and q.get("endpoint") == "bulk"
                     and "semantic_scholar" not in excluded), None)
    s2 = queries[s2_index] if s2_index is not None else None
    # The completion arm's own records, taken off the keyword cap so that every arm of the measurement reads the same
    # total. A run whose policy froze no arm, and one whose saved plan leaves the provider out, reserves nothing and
    # keeps the whole cap.
    arm = fast_path.completion(run["budget"])
    completing = arm is not None and "semantic_scholar" not in excluded
    reserved = arm["records"] if completing else 0
    # The bulk request's own reservation, taken only for a request this plan really names. Why none, when the depth
    # would have paid for one, is recorded beside it: a reservation that buys nothing is not silently kept.
    s2_records = S2_RESERVED_RECORDS if (deep and s2 is not None) else 0
    s2_skipped = None if s2_records else (
        "uniform_search_off" if "uniform_search" in policy else
        "not_deep" if not deep else user_plan.EXCLUDED if "semantic_scholar" in excluded else "not_planned")
    # The field sources this depth searches, their records taken off the same keyword cap. A source the depth does
    # not send gives its records back to the keyword queries and keeps no admission place: the places belong to the
    # plan, so a source that fails later cannot move them either.
    field_specs, field_dropped, field_reasons = field_plan(store, run, scope, queries, policy, excluded)
    # A field source is bounded the same way as the question's own index, where its connector takes a bound; most
    # take none and are searched unbounded, which the request's own record says.
    field_specs = [spec | {"query": with_date_scope(spec["query"], years)} for spec in field_specs]
    field_records = sum(spec["records"] for spec in field_specs)
    # The second independent index this depth pays for, decided after the field sources because the conditional
    # arm's own condition is that this run plans none of its own. Its records come off the same keyword cap.
    broad_spec, broad_told = broad_plan(run, scope, queries, excluded, field_specs)
    broad_spec = broad_spec | {"query": with_date_scope(broad_spec["query"], years)} if broad_spec else None
    broad_records = broad_spec["records"] if broad_spec else 0
    # The one sub-topic search of that index, where this depth pays for no second index of its own. Decided after
    # the broad plan, because its own condition is that there is none. Its records are its own and come off no
    # cap: whether it is sent is decided after the keyword loop has ended, so records taken off that loop's cap
    # would be lost on every question where nothing is sent, and the arms could not be compared on one total.
    subtopic_spec, subtopic_told = subtopic_plan(run, scope, queries, vocabulary, excluded, broad_spec,
                                                field_specs)
    subtopic_spec = subtopic_spec | {"query": with_date_scope(subtopic_spec["query"], years)} if subtopic_spec else None
    # The queries those two arms own are reported on their own arms, with their own reasons: the field plan's list
    # of what was not sent does not also name them as field sources that lost their place.
    owned = {broad_told["index"]} if broad_told and broad_told["index"] is not None else set()
    owned |= set(subtopic_told["indexes"]) if subtopic_told else set()
    field_dropped = [row for row in field_dropped if row["index"] not in owned]
    return {"version": 1, "semantic": semantic_spec(scope, policy, seed_context),
            # The whole scope, in the plan a person reads as well as in the budget the run froze: the two come from
            # one reading, and the plan is what the search record and the Methods box are read back against.
            **({"date_scope": years} if years else {}),
            **({"block_semantic": dict(BLOCK_SEMANTIC_OFF)} if vocabulary is not None else {}),
            **({"completion": {"rule": arm["rule"], "arm": arm["arm"], "records": reserved,
                               # Where each request of the arm is admitted: the fallback waits for the keyword pages
                               # of the round, while a snippet request is admitted at its own concept's gate, which
                               # is inside the loop. The frozen plan says both, so neither is read as the other.
                               "order": {"relevance": "after_keywords", "snippet": "at_concept_gate"},
                               "snippet_requests": arm["snippet_requests"] if completing else 0,
                               **({"skipped": user_plan.EXCLUDED} if not completing else {})},
                "s2_relevance": completion.relevance_spec(scope["question"], reserved) if completing else None,
                # One snippet request per focused concept the plan named, each decided by that concept's own gate;
                # the control arm, which sends on every question, also asks about the question's own terms where the
                # plan named no concept. Quick writes neither, since its snippet budget is nothing.
                "s2_snippet": completion.snippet_specs(
                    queries, search_plan.main_terms(vocabulary) if vocabulary else [],
                    arm["snippet_requests"] if completing else 0, reserved, arm["arm"])}
               if arm is not None else {}),
            "keywords": keyword,
            "keyword_cap": policy["keyword_record_cap"] - s2_records - reserved - field_records - broad_records,
            "field": field_specs,
            **({"field_not_compiled": field_reasons} if field_reasons else {}),
            # The second index, and why none: a plan frozen before the rule names neither key, and a run resumed
            # under it sends what its own plan says, not what today's arm would say.
            **({"broad": broad_spec} if broad_spec else {}),
            **({"broad_not_sent": {"provider_id": broad_told["provider_id"], "reason": broad_told["reason"]}}
               if broad_told and "reason" in broad_told else {}),
            # The one sub-topic search of that index, and why none. Whether its gap was still open is on its own
            # step, not here: the plan freezes the request, the stage reads the condition.
            **({"subtopic": subtopic_spec} if subtopic_spec else {}),
            **({"subtopic_not_sent": {"provider_id": subtopic_told["provider_id"], "reason": subtopic_told["reason"]}}
               if subtopic_told and "reason" in subtopic_told else {}),
            "page_size": (policy.get("uniform_search") or {}).get("keyword_page_size", KEYWORD_PAGE_SIZE),
            "order": "page_then_query",
            # The bulk route takes a year range of its own, so the depth that pays for this request sends it
            # inside the same years as the question's own index.
            "s2_bulk": with_date_scope(s2, years) if deep and s2 is not None else None,
            "s2_bulk_index": s2_index,
            "s2_reserved": s2_records,
            **({"s2_skipped": s2_skipped} if s2_skipped else {}),
            "dropped": [row for row in field_dropped if row["index"] != s2_index],
            "expansion": "fast_path_frozen_plan",
            # Only a run of a revision with a saved plan names this, so every other plan freezes as before.
            **({"excluded_providers": excluded} if user_plan.of(scope) is not None else {})}


def written_blocks(vocabulary, query):
    """The block names and the terms this compiled query really wrote, or None when that cannot be told.

    The block compiler is pure, so its prefix allocation is computed again from the vocabulary that wrote the query
    (the code's beside a model-written one). Only when the text it gives is the stored text are its counts taken;
    any other text says nothing about what the stored query holds.
    """
    # `code` is the origin of the question's own query, which a research searched before that query was removed;
    # its words are read back from where that research kept them.
    source = (search_query.question_vocabulary(vocabulary) if query.get("origin") == "code" else None) or vocabulary
    groups, names = [], []
    for block in query_compiler.BLOCK_ORDER:
        forms = list(dict.fromkeys(queried_form(t) for t in source["terms"] if t["block"] == block and not t["dropped"]))
        if forms:
            groups.append(forms)
            names.append(block)
    # Under the forms rule the stored text also holds the other number forms, so it is compiled the same way.
    fitted = query_compiler.fit_with_forms(query["provider_id"], groups, query.get("endpoint"),
                                           variants=query_compiler.variants_of(source)) if groups else None
    if fitted is None or fitted[0] != query["query_text"]:
        return None
    return names, [group[:count] for group, count in zip(groups, fitted[1])]


def _carried(vocabulary, query):
    """The (block, form) pairs this compiled query really wrote, or None when that cannot be told.

    A statement research's author query (R5) holds the field's root word alone, which the query holding the field
    also carries, so it adds no pair."""
    if query.get("origin") == "author":
        return set()
    written = written_blocks(vocabulary, query)
    if written is None:
        return None
    names, groups = written
    return {(name, form) for name, group in zip(names, groups) for form in group}


def plan_words(vocabulary, plan):
    """Every setting and task word of the frozen vocabulary and whether a query the plan sends carries it.

    The queries sent are the OpenAlex keyword queries, the query of each field source the depth searches, the query
    of the second independent index where the plan froze one and, at
    Detailed depth, the Semantic Scholar bulk query; the
    semantic requests send the question's sentence and, in a plan frozen under `block_terms_v1` (no longer
    sent), these words joined
    (`block_semantic`), so they are not counted here. `searched` is false with `left_out` naming why:
    the word's own drop reason (a count of zero, too broad), `query_limit` when a sent query that held the word had no
    room for it, or `not_sent` when only a query the plan does not send held it. It is null when a sent query could
    not be read back (`_carried`), so an unknown is never shown as searched or as left out. A plan with
    `block_semantic` also records `semantic`: whether the word's phrase stands in the text of the block terms'
    semantic request it sends, so a word left out of every keyword query is not shown as never sent."""
    sent = ([spec["query"] for spec in plan["keywords"]] + [spec["query"] for spec in plan.get("field") or []]
            + ([plan["broad"]["query"]] if plan.get("broad") else [])
            + ([plan["subtopic"]["query"]] if plan.get("subtopic") else [])
            + ([plan["s2_bulk"]] if plan.get("s2_bulk") else []))
    semantic = (plan["block_semantic"].get("query_text") or "") if "block_semantic" in plan else None
    carried = [_carried(vocabulary, query) for query in sent]
    known = all(c is not None for c in carried)
    held = {(t["block"], queried_form(t)) for q in sent if q.get("origin") != "author" for t in
            ((search_query.question_vocabulary(vocabulary) if q.get("origin") == "code" else None)
             or vocabulary)["terms"]
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


def cancel_step(store, run_id, key, kind, reason, statuses=("pending",), extra=None):
    """Finish the step at `key` as cancelled with `reason` as its stop reason, when its status is one of `statuses`
    (any status when None); it sent no request and brought no record. `extra` is written into the step's output beside
    the reason, for a step whose own record says more than why it stopped."""
    step = store.step(run_id, key, kind)
    if statuses is None or step["status"] in statuses:
        store.finish_step(step["id"], "cancelled", error_code=reason,
                          output={"stop_reason": reason, "result_count": 0} | (extra or {}))
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


def page_sender(flow, run, scope, plan, retry_failed, shared, retry_cancels=("budget_exhausted",)):
    """The one function that sends a page of a search and records it, and the stop it reads.

    `shared` carries what the callers share: `failure` is the failure to report, `s2_task` the Semantic Scholar
    slot, which the stage waits for at its end and no page waits for in between. `first_semantic` and `execute`
    each build their own sender, so the question's request can go out before anything plans and the search stage
    can send the rest later (P2).
    `retry_cancels` are the stop reasons a cancelled page may be sent again for, and it is read only where
    `retry_failed` is set. `cap` is what the whole request may read when that is more than this page's limit."""
    store, run_id = flow.store, run["id"]
    effort = scope["effort"]

    def stopped():
        return flow._stop_requested(run_id, run["scope_revision"]) or fast_path.past_deadline(store, run, "search")

    excluded = plan.get("excluded_providers") or []

    async def send_page(query, key, *, limit, klass, index, number=0, cursor=FIRST_PAGE, before=0, total=None,
                        terminal=None, after=None, cap=None):
        if query["provider_id"] in excluded:
            # The frozen plan leaves this provider out (S23a): no request, whatever planned it.
            step = cancel_step(store, run_id, key, f"provider_search:{query['provider_id']}", user_plan.EXCLUDED)
            return store.step_output(step["id"]), 0
        connector = reading(query)
        allowance = search_page.page_allowance(query, effort, run["budget"])
        # The keyword read records its smaller per-query or arm cap; other requests keep their own limit.
        page_read_limit = plan["keyword_cap"] if klass == 1 else cap if cap is not None else limit
        if klass == 1 and cap is not None:
            page_read_limit = min(page_read_limit, cap)
        page = Page(number, cursor, before, total, page_read_limit,
                    fast_path.search_read(run["budget"].get("fast_path") or {}, effort, "provider_wait"),
                    key.split(":page:")[0], allowance)
        step = store.existing_step(run_id, key)
        old = (step or {}).get("output") or {}
        retry_cancelled = bool(step and step["status"] == "cancelled" and step["error_code"] in retry_cancels and retry_failed)
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
        # When this reply was written, against the moment the search stage's own time ran out. A request sent in
        # time whose reply arrives after it is recorded as late, the way a chain reply is, so what came in by the
        # cutoff and what came after it are told apart in the frozen list instead of being read as one set.
        arrived, cutoff = store.clock.now(), fast_path.stage_deadline(store, run, "search")
        admission = admission | {"returned_count": returned, "raw_returned_count": raw_count,
                                 "arrived_at": arrived.isoformat(timespec="milliseconds"),
                                 "cutoff_at": cutoff.isoformat(timespec="milliseconds") if cutoff else None,
                                 "late": bool(cutoff is not None and arrived >= cutoff)}
        ok = answer.status in ("completed", "zero_results")
        # A short reply has not reached a per-query read limit even when its page asked for the remainder.
        reason = "page_failed" if not ok else (None if terminal == "read_limit" and before + returned < page.read_limit
                                                 else terminal)
        if ok:
            if klass == 1 and fast_path.past_deadline(store, run, "search"):
                reason = "deadline"
            elif reason is None and (not answer.next_cursor or not returned):
                reason = "exhausted"
            elif reason is None and flow._query_requests(run_id, page.query_key) >= allowance:
                reason = "budget_exhausted"
            elif retry_page_only and reason is None:
                reason = "retry_page_only"
        with transaction(store.conn):
            step = store.step(run_id, key, f"provider_search:{connector.provider_id}")
            if step["status"] != "running":  # a short phrase request is marked running before it is sent
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
        # The links inside this page first: they cost no request, so every depth writes them, and a depth that
        # opens no citation request of its own (Quick) still records what the page itself shows.
        chain.pool_links()
        chain.initial()
    flow._checkpoint(run_id, run["scope_revision"])


async def first_semantic(flow, run, scope, seed_context=None, sent=None, handed=None):
    """The question's semantic request, sent before any step that plans (P2).

    The design's first step needs no translation, rewriting or model call, so this request goes out in whatever
    language the person wrote, right after the seed match, and every planning step runs while it is in flight. The
    step is opened before the request is sent, so it carries `protocol_hash = NULL` as the seed match's requests do
    (Ç1), and it keeps the `search:fast:semantic` key, so the search stage finds it succeeded and sends nothing
    twice. `sent` is set once the request is on its way, so the caller goes on without waiting for the reply.
    `handed` is set only once the request has passed the pacer and is with the HTTP client.

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
        # The plan step reads this page's records, so a request an earlier attempt of the same run left failed or
        # cancelled by a deadline is retried here: the plan cannot be written without that page, and a resume that
        # could not send it again would stop at the same place for ever.
        send_page = page_sender(flow, run, scope, plan, True, shared,
                                retry_cancels=("budget_exhausted", "deadline"))
    finally:
        if sent is not None:
            sent.set()
    # Only this request's own attempts set `handed`: the variable lives in this task's context.
    token = common.on_handed.set(handed.set) if handed is not None else None
    try:
        await question_semantic(flow, run, plan, send_page)
    finally:
        if token is not None:
            common.on_handed.reset(token)
    return shared["failure"]


async def execute(flow, run, scope, plan, retry_failed):
    store, run_id = flow.store, run["id"]
    shared = {"failure": None, "s2_task": None}
    send_page = page_sender(flow, run, scope, plan, retry_failed, shared)
    # A written slot retains its size and index even when it failed. Replay walks
    # the identical round-robin schedule rather than deriving order from timestamps.
    request_index = 0
    excluded = plan.get("excluded_providers") or []
    # The block terms' semantic request, after the question's (whose page alone chooses the first chain seeds);
    # a plan frozen without it, or one that skipped it, sends nothing and keeps its request indexes. Each seed's own
    # request follows, so every semantic request keeps the index the plan's order gives it.
    blocks = plan.get("block_semantic") or {}
    seed_start = 1 + int(bool(blocks.get("query_text")))
    seed_specs = plan.get("seed_semantic") or []

    # Each seed's own semantic request, after the chain chose its first seeds from the question's page; an unseeded
    # plan has none, so its indexes are unchanged. The requests start one pacer gap apart and their replies overlap
    # (`openalex.SEMANTIC_PACER`); each is written after the one before it, so admission and candidate order follow
    # seed order.
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

    async def semantic_requests():
        """The question's, the block terms' and each seed's semantic request, in the plan's order."""
        await question_semantic(flow, run, plan, send_page)
        if blocks.get("query_text"):
            result, _ = await send_page(blocks, BLOCK_SEMANTIC_KEY, limit=blocks["limit"], klass=0, index=1,
                                        terminal="single_page")
            if result is None and not flow._stop_requested(run_id, run["scope_revision"]):
                cancel_step(store, run_id, BLOCK_SEMANTIC_KEY, "provider_search:openalex", "deadline", None)
            consumer = flow._fast_consumers.get(run_id)
            if consumer:
                consumer.notify()
            flow._checkpoint(run_id, run["scope_revision"])
        seed_tasks = []
        for number, spec in enumerate(seed_specs):
            seed_tasks.append(asyncio.create_task(seed_request(spec, seed_start + number,
                                                               seed_tasks[-1] if seed_tasks else None)))
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

    request_index = seed_start + len(seed_specs)
    # Under the evidence minimum the keyword pages go out at once: the semantic requests run beside the keyword
    # loop instead of ahead of it, and the stage waits for them at its end. A run frozen before it sends them first.
    semantic_task = (asyncio.create_task(semantic_requests())
                     if fast_path.evidence_minimum(store, run) is not None else None)
    if semantic_task is None:
        await semantic_requests()

    async def s2_page():
        if plan["s2_bulk"] is not None:
            result, _ = await send_page(plan["s2_bulk"], "search:fast:s2_bulk", limit=plan["s2_reserved"], klass=1,
                                        index=1, terminal="single_page")
            if result is None and not flow._stop_requested(run_id, run["scope_revision"]):
                cancel_step(store, run_id, "search:fast:s2_bulk", "provider_search:semantic_scholar", "deadline", None)
        elif plan.get("s2_skipped") and plan["s2_skipped"] not in ("not_deep", "uniform_search_off"):
            # A depth that would have sent a bulk request records why it did not. The records it would have read are
            # already back with the keyword queries, so the step says what was skipped, not what was held.
            cancel_step(store, run_id, "search:fast:s2_bulk", "provider_search:semantic_scholar", plan["s2_skipped"])

    # The independent S2 slot (request 1), sent while the first keyword page is in flight. A ready keyword page no
    # longer waits for this slot's write: each page is recorded as it arrives, and what the list is computed from is
    # decided by the stored admission key, not by which reply came back first.
    s2_skipped = plan.get("s2_skipped")
    shared["s2_task"] = (asyncio.create_task(s2_page())
                         if plan["s2_bulk"] is not None or (s2_skipped and s2_skipped not in ("not_deep", "uniform_search_off")) else None)
    request_index += int(plan["s2_reserved"] > 0)
    # The completion arm's own sender, with its own failure slot: an arm that is sent only when OpenAlex could not
    # complete must not itself fail the search stage. Its failure is recorded on its own step and the run goes on with
    # what it has.
    arm_shared = {"failure": None, "s2_task": None}
    arm_send = page_sender(flow, run, scope, plan, retry_failed, arm_shared)
    # What the arm has read of its own reservation, counting what an earlier attempt of this run already read. Every
    # request of the arm shares it, so a run where the fallback and its snippet queries all fire cannot read more
    # records than the depth took off its keyword cap.
    arm_spent = {"records": completion.spent(store, run_id, plan) if plan.get("completion") else 0}
    snippet_specs = {spec["index"]: (position, spec) for position, spec in enumerate(plan.get("s2_snippet") or [])
                     if spec["index"] is not None}

    async def send_arm(spec, key, record):
        """Send one request of the completion arm inside its own reservation, and record what it found."""
        arm = plan["completion"]
        room = arm["records"] - arm_spent["records"]
        if room <= 0:
            cancel_step(store, run_id, key, "provider_search:semantic_scholar", completion.BUDGET, None, record)
            return
        result, _ = await arm_send(spec, key, limit=min(spec["limit"], room), klass=0, index=request_index,
                                   terminal="single_page")
        if result is None:
            cancel_step(store, run_id, key, "provider_search:semantic_scholar", completion.DEADLINE, None, record)
            return
        arm_spent["records"] += result.get("result_count") or 0
        store.set_step_output(store.existing_step(run_id, key)["id"], result | record)
        consumer = flow._fast_consumers.get(run_id)
        if consumer:
            consumer.notify()

    async def snippet_for(index, covered):
        """The snippet request of the concept whose focused query is at `index`, decided by that query's own gate."""
        if index not in snippet_specs:
            return
        position, spec = snippet_specs[index]
        key = completion.snippet_key(position)
        existing = store.existing_step(run_id, key)
        if existing is not None and existing["status"] != "pending":
            return
        arm_name = plan["completion"]["arm"]
        record = {"arm": arm_name, "focused": spec["focused"],
                  # What the gate read and decided, so the measurement can say whether the gate, and not the source,
                  # is what kept the request from going out. The control arm records the same reading and sends.
                  "gate": {"covered": covered, "query_index": index, "held": covered and arm_name != completion.ALWAYS}}
        if covered and arm_name != completion.ALWAYS:
            cancel_step(store, run_id, key, "provider_search:semantic_scholar", search_plan.GAP_ALREADY_MET,
                        None, record)
            return
        await send_arm(spec, key, record)

    async def resolve_completion(forced):
        """Record what this run observed about its OpenAlex requests and, when that observation allows it, send the
        fallback. Called at each ordinary end of the keyword loop, so the decision not to send is recorded too; a
        stop the person asked for ends the loop by raising, and that run is resumed, not completed.

        `forced` is the stage's own reason when the loop ended before the arm could be considered.
        """
        arm = plan.get("completion")
        if arm is None:
            return  # a run whose policy froze no arm has no step of its own and nothing to record
        # The fallback is settled first, and so reads the reservation first: a run where OpenAlex brought nothing at
        # all has more need of it than a passage query the control arm would send anyway.
        key = completion.RELEVANCE_KEY
        existing = store.existing_step(run_id, key)
        # Settled already: a replayed run reads its own decision back instead of deciding again.
        if existing is None or existing["status"] == "pending":
            observed = completion.openalex_outcome(store, run_id)
            record = {"openalex": observed, "arm": arm["arm"]}
            reason = arm.get("skipped") or forced
            if reason is None and observed["state"] != "technical_failure":
                reason = completion.OPENALEX_ANSWERED
            if reason is None and fast_path.past_deadline(store, run, "search"):
                reason = completion.DEADLINE
            if reason is None:
                await send_arm(plan["s2_relevance"], key, record)
            else:
                cancel_step(store, run_id, key, "provider_search:semantic_scholar", reason, None, record)
        # Each snippet request still open ends here: the question's own request of the control arm is sent now, since
        # no concept's gate decides it, and a concept's request whose gate the loop never reached stops with the
        # stage's own reason. Either way no step of the arm is left pending and the decision is readable.
        for position, spec in enumerate(plan.get("s2_snippet") or []):
            key = completion.snippet_key(position)
            step = store.existing_step(run_id, key)
            if step is not None and step["status"] != "pending":
                continue
            reason = arm.get("skipped") or forced
            if reason is None and fast_path.past_deadline(store, run, "search"):
                reason = completion.DEADLINE
            record = {"arm": arm["arm"], "focused": spec["focused"],
                      "gate": {"covered": None, "query_index": spec["index"], "held": reason is not None}}
            if spec["index"] is None and reason is None:
                await send_arm(spec, key, record)
                continue
            cancel_step(store, run_id, key, "provider_search:semantic_scholar",
                        reason or completion.DEADLINE, None, record)

    # The field sources this depth pays for, each inside its own record share and with its own sender: a source the
    # routing added is not the question's own index, so its failure is recorded on its own step and the run goes on
    # with what OpenAlex brought. Its pages are sent while the keyword pages are in flight, since they are other
    # hosts, and the stage waits for them at its end like the bulk slot.
    field_shared = {"failure": None, "s2_task": None}
    field_send = page_sender(flow, run, scope, plan, retry_failed, field_shared)
    broad_shared = {"failure": None, "s2_task": None}
    broad_send = page_sender(flow, run, scope, plan, retry_failed, broad_shared)

    async def paged_source(spec, send, klass, page_records):
        """One source's whole walk inside its own record share: a field source's, or the second independent
        index's. `page_records` is what one page of it asks for, which is not the keyword page size for a
        provider whose adapter serves fewer records than that."""
        provider = spec["query"]["provider_id"]
        state = {"number": 0, "cursor": FIRST_PAGE, "before": 0, "total": None}
        # The share is counted in the records each page reserved, which is the one measure a page this run already
        # recorded and a page sent now both report. A resume walks the same page keys again and reads the recorded
        # ones back, so the share is spent once however often the walk is repeated.
        spent = 0
        while spent < spec["records"]:
            key = f"search:{spec['index']}" + (f":page:{state['number']}" if state["number"] else "")
            if fast_path.past_deadline(store, run, "search"):
                cancel_step(store, run_id, key, f"provider_search:{provider}", "deadline")
                return
            limit = min(page_records, spec["records"] - spent)
            # The expanded text where the plan froze one (PubMed's headings), the compiled text otherwise. The
            # query keeps its compiled text, which is what the plan's own word record is read back against.
            result, reserved = await send(mesh.sent_query(spec["query"]), key, number=state["number"], cursor=state["cursor"],
                                          before=state["before"], total=state["total"], limit=limit,
                                          klass=klass, index=spec["request_index"], cap=spec["records"],
                                          terminal="record_cap" if spent + limit >= spec["records"] else None)
            if result is None:
                cancel_step(store, run_id, key, f"provider_search:{provider}", "deadline")
                return
            spent += reserved
            consumer = flow._fast_consumers.get(run_id)
            if consumer:
                consumer.notify()
            if result.get("stop_reason") or not result.get("next_cursor"):
                return
            state |= {"number": state["number"] + 1, "cursor": result.get("next_cursor"),
                      "before": result.get("read_total", state["before"]),
                      "total": result.get("provider_total") if result.get("provider_total") is not None
                      else state["total"]}

    field_tasks = [asyncio.create_task(paged_source(spec, field_send, FIELD_CLASS, plan["page_size"]))
                   for spec in plan.get("field") or []]
    # The second independent index, where the plan froze one: its own share, its own sender and its own pages, so
    # its failure is recorded on its own step and the run goes on with what the other sources brought.
    field_tasks += [asyncio.create_task(paged_source(plan["broad"], broad_send, BROAD_CLASS,
                                                     plan["broad"]["page_records"]))] if plan.get("broad") else []

    specs = plan["keywords"]
    states = {s["index"]: {"number": 0, "cursor": FIRST_PAGE, "before": 0, "total": None, "ended": False} for s in specs}
    # The main Boolean query's own pages: the plan the model wrote, or the person's saved one. A record only
    # another query of the round found leaves the main query's gap open.
    main_indexes = search_plan.main_plan_indexes(specs)

    async def finish_subtopic(forced):
        """The one sub-topic search of the broad index, settled at every ordinary end of the keyword loop.

        Its condition is the design's own: the sub-topic is still unmet **after** the field source was searched.
        So the field walk is waited for first — until its last page is in, what it found is not known — and the
        gap is then read over the main query's pages and the field source's together. The `always` arm sends
        whatever the gate read, which is what makes the two arms comparable. The reading is recorded either way,
        so the decision not to send can be read back instead of guessed at.

        `forced` is the stage's own reason when the loop ended before the request could be considered. The keyword
        record cap is not one of them: this request's records are its own reservation, so a keyword arm that spent
        its cap takes nothing from it and only the stage's own time can hold it back.
        """
        spec = plan.get("subtopic")
        if spec is None:
            return
        forced = forced if forced == "deadline" else None
        key = f"search:{spec['index']}"
        step = store.existing_step(run_id, key)
        if step is not None and step["status"] != "pending":
            # A decision already recorded stays recorded, so a replayed run reads its own back instead of deciding
            # again. A request that failed goes out again only where the person asked for the failed searches to be
            # retried, which is the same condition `page_sender` reads.
            if not (retry_failed and step["status"] in ("failed", "outcome_unknown")):
                return
        for task in field_tasks:
            if not task.done():
                await task
        provider = spec["query"]["provider_id"]
        read = main_indexes + [s["index"] for s in plan.get("field") or []]
        # Whether the field source answered at all. Its records are half of what the condition is read over, so a
        # source that never answered leaves the condition untested: the gap would look open because nothing came
        # back, and a paid request would go out on that. A page that answered with no record did answer, and a
        # later page that failed does not take back what the earlier ones brought; both are counted and recorded.
        pages = store.conn.execute(
            "SELECT status FROM search_runs WHERE run_id = ? AND request_class = ?",
            (run_id, FIELD_CLASS)).fetchall()
        answered = sum(1 for page in pages if page["status"] in ("completed", "zero_results"))
        covered = search_plan.pages_cover(store, run, spec["focused"]["term"], read)
        # Read before the gap, although either reason holds the request: a source that never answered leaves the
        # condition untested, and a gap the main query alone closed would hide that in the record.
        reason = forced or (None if answered else "field_source_did_not_answer")
        if reason is None and covered and spec["arm"] != completion.ALWAYS:
            reason = search_plan.GAP_ALREADY_MET
        if reason is None and fast_path.past_deadline(store, run, "search"):
            reason = "deadline"
        record = {"arm": spec["arm"], "focused": spec["focused"],
                  # What the gate read and over which queries' pages, so the measurement can say whether the gate
                  # or the source kept the request from going out, and how much of the field source it read.
                  "gate": {"covered": covered, "query_indexes": read, "held": reason is not None,
                           "field_pages_answered": answered, "field_pages_failed": len(pages) - answered}}
        statuses = ("pending", "failed", "outcome_unknown") if retry_failed else ("pending",)
        if reason is not None:
            cancel_step(store, run_id, key, f"provider_search:{provider}", reason, statuses, record)
            return
        result, _ = await broad_send(spec["query"], key, limit=spec["records"], klass=BROAD_CLASS,
                                     index=spec["request_index"], terminal="single_page")
        if result is None:
            cancel_step(store, run_id, key, f"provider_search:{provider}", "deadline", statuses, record)
            return
        store.set_step_output(store.existing_step(run_id, key)["id"], result | record)
        consumer = flow._fast_consumers.get(run_id)
        if consumer:
            consumer.notify()

    slots = 0
    policy = run["budget"].get("fast_path") or {}
    query_read_limit = (fast_path.search_read(policy, scope["effort"], "read_limit_per_query")
                        if (policy.get("uniform_search") or {}).get("rule") == fast_path.UNIFORM_SEARCH_RULE else None)
    try:
        # Each page is recorded when its own reply arrives, whatever another arm is still waiting for. Which record
        # heads a work, and which search a candidate names, are decided by the admission key the request stored, so
        # a page that came back first does not take a place from a request that was admitted before it.
        while any(not s["ended"] for s in states.values()):
            for spec in specs:
                state = states[spec["index"]]
                if state["ended"]:
                    continue
                focused = spec["query"].get("role") == "focused"
                if focused and state["number"] == 0 and any(not states[i]["ended"] for i in main_indexes):
                    # The condition is read against what the main query really brought, so it waits until that query
                    # has read its last page: a later page can carry the concept the first one did not.
                    continue
                if query_read_limit is not None and state["before"] >= query_read_limit:
                    close_queries(flow, run, [spec], "read_limit")
                    state["ended"] = True
                    continue
                key = f"search:{spec['index']}" + (f":page:{state['number']}" if state["number"] else "")
                old = store.existing_step(run_id, key)
                written = old is not None and (old["status"] in ("succeeded", "failed", "outcome_unknown")
                          or bool((old.get("output") or {}).get("fast_path_request")))
                reason = "deadline" if fast_path.past_deadline(store, run, "search") else "record_cap" if slots >= plan["keyword_cap"] else None
                if reason and not written:
                    close_queries(flow, run, specs, reason)
                    await resolve_completion(reason)
                    await finish_subtopic(reason)
                    return shared["failure"]
                if focused and state["number"] == 0 and not written:
                    # The recorded condition, read once and only for a query no page of which has been sent: a
                    # concept the main query's own records already carry is no gap, so the depth's plan is not spent
                    # on it. More terms in the plan never send a query by themselves, and a replayed run reads its
                    # own first page back instead of deciding again.
                    covered = search_plan.pages_cover(store, run, spec["query"]["focused"]["term"], main_indexes)
                    # The completion arm's snippet request reads the same gate: a part of the question the main
                    # query's own records already carry is no gap, for either query.
                    await snippet_for(spec["index"], covered)
                    if covered:
                        cancel_step(store, run_id, key, f"provider_search:{spec['query']['provider_id']}",
                                    search_plan.GAP_ALREADY_MET)
                        state["ended"] = True
                        continue
                flow._checkpoint(run_id, run["scope_revision"])
                limit = min(plan["page_size"], plan["keyword_cap"] - slots,
                            query_read_limit - state["before"] if query_read_limit is not None else plan["page_size"])
                old_admission = ((old or {}).get("output") or {}).get("fast_path_request")
                if old_admission:
                    limit = old_admission["limit"]
                terminal = ("record_cap" if slots + limit >= plan["keyword_cap"] else
                            "read_limit" if query_read_limit is not None and state["before"] + limit >= query_read_limit
                            else None)
                result, reserved = await send_page(spec["query"], key, number=state["number"], cursor=state["cursor"],
                                                   before=state["before"], total=state["total"], limit=limit, klass=1,
                                                   index=request_index, terminal=terminal, cap=query_read_limit)
                if result is None:
                    flow._checkpoint(run_id, run["scope_revision"])
                    close_queries(flow, run, specs, "deadline")
                    await resolve_completion("deadline")
                    await finish_subtopic("deadline")
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
        await resolve_completion(None)
        await finish_subtopic(None)
    finally:
        if semantic_task is not None:
            raising = sys.exc_info()[0] is not None
            if raising:
                semantic_task.cancel()  # the stage is already ending with an error or a stop
            outcome = (await asyncio.gather(semantic_task, return_exceptions=True))[0]
            if not raising and isinstance(outcome, BaseException):
                raise outcome
        if shared["s2_task"] and not shared["s2_task"].done():
            await shared["s2_task"]
        for task in field_tasks:
            if not task.done():
                await task
    return shared["failure"]
