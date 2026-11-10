"""The keyword query a model writes for an sw discovery run, and what code does with it (slice 13h).

The model chooses at most eight terms for the setting and task blocks, at most four in a block, with a kind, a short
reason and up to three backups per block (`references/search-query.md`; six in all before). Code counts every
chosen term twice, alone and together with the terms the other block is searched with. A term no record holds on its
own is replaced by the next backup of its block. A term that finds records alone but none together with the other
block stays, shown as a warning, and since that change the next unused backup of its block that does find records with the
other block is searched beside it, while the query stays within eight terms. No count removes a term for being large:
the one-million rule and the manageable-total narrowing of the code vocabulary do not apply to what the model wrote.
The counts are asked four at a time (`vocabulary.counts_in_flight`); which queries are asked, and the order of every
stored row, are those of asking them one by one.

The model's terms become the proposal's vocabulary, and the question's own words are kept whole beside them under
`question_vocabulary`. No query is compiled from those words: the only keyword queries sent are the model's and the
focused queries of its plan. They stay because the ranking, the abstract stage's code rules and the protocol read
them to say what the question itself asks for, so a record that names the question's own concepts in other words
than the plan's is not closed by code.
"""

from __future__ import annotations

from typing import Any, Awaitable, Callable

from deixis.domain.contracts import SEARCH_QUERY_MAX_TERMS
from deixis.domain.vocabulary import words
from deixis.providers import query_compiler
from deixis.providers.query_compiler import quoted
from deixis.workflow.search.approval import SIDE_LISTS
from deixis.workflow.search.criterion import norm
from deixis.workflow.search.vocabulary import GATE_BLOCKS, counts_in_flight

ASSIGNMENT = "search_query"  # the vocabulary's `block_assignment`, and the origin of the model's own terms
ATTEMPTS = 2  # the first call, and one more when the user asks for it after a failure
# Eight chosen terms and six backups, each counted alone and with the other block, the gate, and the recounts a
# backup used beside a term asks for. Was 24 for six chosen terms.
MAX_COUNT_REQUESTS = 40
ZERO_WITH_OTHER = "no_records_with_other_block"  # why a backup was tried beside a term, and why it was not kept
KINDS = ("topic", "method", "population", "other")
THRESHOLDS = {"attempts": ATTEMPTS, "max_count_requests": MAX_COUNT_REQUESTS}
# The providers whose keyword search takes an author filter (a statement research's named authors, R5). Semantic
# Scholar's bulk search, arXiv and the others are searched without one and named so in the vocabulary.
AUTHOR_FILTER_PROVIDERS = ("openalex",)


def _other(block: str) -> str:
    return GATE_BLOCKS[1] if block == GATE_BLOCKS[0] else GATE_BLOCKS[0]


def _group(phrases: list[str]) -> str:
    return "(" + " OR ".join(quoted(phrase) for phrase in phrases) + ")"


def _term(phrase: str, block: str, origin: str, count: int | None, dropped: str | None = None) -> dict[str, Any]:
    """A term in the shape every sw vocabulary holds (`vocabulary.TERM_FIELDS`), entered as its whole phrase."""
    return {"phrase": phrase, "block": block, "origin": origin, "root": phrase, "in_query": "phrase",
            "phrase_count": count, "root_count": None, "and_only": False, "dropped": dropped}


def answer_terms(answer: dict[str, Any]) -> tuple[dict[str, list[dict[str, str]]], dict[str, list[str]]]:
    """The chosen terms of each block, written one way and in the model's order, and each block's unused backups."""
    chosen: dict[str, list[dict[str, str]]] = {block: [] for block in GATE_BLOCKS}
    seen: set[str] = set()
    for block in GATE_BLOCKS:
        for row in answer[block]:
            if (phrase := norm(row["term"])) and phrase not in seen:
                seen.add(phrase)
                chosen[block].append({"phrase": phrase, "kind": row["kind"], "why": row["why"].strip()})
    backups: dict[str, list[str]] = {block: [] for block in GATE_BLOCKS}
    for block in GATE_BLOCKS:
        for row in answer[f"{block}_backup"]:
            if (phrase := norm(row["term"])) and phrase not in seen:
                seen.add(phrase)
                backups[block].append(phrase)
    return chosen, backups


class _Counter:
    """Count requests with a ceiling, each query asked once. A count past the ceiling is unknown, never invented."""

    def __init__(self, count: Callable[[str], Awaitable[int | None]]):
        self.count, self.known, self.asked, self.skipped = count, {}, 0, 0
        self.probes: list[dict[str, Any]] = []

    async def many(self, queries: list[str]) -> list[int | None]:
        """The counts of `queries` in their order, the new ones asked at once. The ceiling, the cache and the
        probe record follow the list's order, as asking them one by one would."""
        plan: list[str | None] = []
        asking: list[str] = []
        for query in queries:
            if query in self.known or query in asking:
                plan.append(query)
            elif self.asked >= MAX_COUNT_REQUESTS:
                self.skipped += 1
                plan.append(None)
            else:
                self.asked += 1
                asking.append(query)
                plan.append(query)
        self.known.update(zip(asking, await counts_in_flight(self.count, asking)))
        values = [None if query is None else self.known[query] for query in plan]
        self.probes += [{"query": query, "count": value} for query, value in zip(plan, values) if query is not None]
        return values

    async def __call__(self, query: str) -> int | None:
        return (await self.many([query]))[0]


def _with_other(phrase: str, alone: int | None, other: list[str]) -> str | None:
    """The query that counts a term together with the terms the other block is searched with, or None when it is not
    asked (the term finds nothing alone, or the other block has no term)."""
    return f"{quoted(phrase)} AND {_group(other)}" if other and alone != 0 else None


def _queried(terms: list[dict[str, Any]]) -> dict[str, list[str]]:
    return {block: [t["phrase"] for t in terms if t["block"] == block and not t["dropped"]] for block in GATE_BLOCKS}


def _warnings(row: dict[str, Any]) -> list[str]:
    if row["alone"] is None:
        return ["count_unknown"]
    if row["with_other_block"] == 0:
        return ["no_records_with_other_block"]
    return []


async def check(answer: dict[str, Any], count: Callable[[str], Awaitable[int | None]]) -> dict[str, Any]:
    """Count the answer's chosen terms, put a backup in place of each one no record holds, and search a backup
    beside a term that finds nothing together with the other block.

    Every term is counted alone first, so every swap is made before any term is counted with the other block; the
    count with the other block then reads the terms that block is really searched with. A backup is then tried beside
    each kept term whose count with the other block is 0, setting block first, in order: it is searched when it finds
    records together with the other block and the query has room (SEARCH_QUERY_MAX_TERMS), and otherwise left out with
    its reason. Since a backup only adds records, a count read before it was added is read again against the final
    query. Every count, every replacement and every warning is returned, so the approval card and the protocol show
    the numbers that decided the query. A block left with no term is returned as it is: the caller treats that answer
    as one that cannot be searched.
    """
    chosen, backups = answer_terms(answer)
    counter = _Counter(count)
    meta = {row["phrase"]: {"kind": row["kind"], "why": row["why"], "backup_for": None}
            for block in GATE_BLOCKS for row in chosen[block]}
    terms: list[dict[str, Any]] = []
    checks: list[dict[str, Any]] = []
    counted = iter(await counter.many([quoted(row["phrase"]) for block in GATE_BLOCKS for row in chosen[block]]))
    for block in GATE_BLOCKS:
        spare = list(backups[block])
        for row in chosen[block]:
            phrase, replaced, alone = row["phrase"], None, next(counted)
            while True:
                checks.append({"phrase": phrase, "block": block, "alone": alone, "with_other_block": None,
                               "backup_for": replaced, **({"used_because": "zero_results"} if replaced else {})})
                if alone != 0:
                    terms.append(_term(phrase, block, ASSIGNMENT, alone))
                    break
                terms.append(_term(phrase, block, ASSIGNMENT, 0, "zero_results"))
                if not spare:
                    break
                replaced, phrase = phrase, spare.pop(0)
                meta[phrase] = {"kind": None, "why": None, "backup_for": replaced, "used_because": "zero_results"}
                alone = await counter(quoted(phrase))
        backups[block] = spare
    queried = _queried(terms)
    against: dict[int, str | None] = {}  # the query each row's count with the other block was read with

    async def pair(rows: list[dict[str, Any]]) -> None:
        queries = [_with_other(row["phrase"], row["alone"], queried[_other(row["block"])]) for row in rows]
        asked = [query for query in queries if query is not None]
        found = iter(await counter.many(asked))
        for row, query in zip(rows, queries):
            row["with_other_block"], against[id(row)] = (next(found) if query is not None else None), query

    def kept(row: dict[str, Any]) -> bool:
        return any(t["phrase"] == row["phrase"] and not t["dropped"] for t in terms)

    await pair(checks)
    for block in GATE_BLOCKS:
        spare = backups[block]
        for row in [r for r in checks if r["block"] == block and kept(r)]:
            if row["with_other_block"] != 0 or not spare:
                continue
            if _with_other(row["phrase"], row["alone"], queried[_other(block)]) != against[id(row)]:
                await pair([row])  # the other block gained a backup since this count was read
                if row["with_other_block"] != 0:
                    continue
            while spare and sum(map(len, queried.values())) < SEARCH_QUERY_MAX_TERMS:
                backup = spare[0]
                alone = await counter(quoted(backup))
                entry = {"phrase": backup, "block": block, "alone": alone, "with_other_block": None,
                         "backup_for": row["phrase"], "used_because": ZERO_WITH_OTHER}
                await pair([entry])
                if alone is None or (alone != 0 and entry["with_other_block"] is None):
                    break  # a count that could not be read decides nothing: the backup stays unused
                spare.pop(0)
                checks.append(entry)
                found = isinstance(entry["with_other_block"], int) and entry["with_other_block"] > 0
                terms.append(_term(backup, block, ASSIGNMENT, alone,
                                   None if found else "zero_results" if alone == 0 else ZERO_WITH_OTHER))
                if found:
                    meta[backup] = {"kind": None, "why": None, "backup_for": row["phrase"], "used_because": ZERO_WITH_OTHER}
                    queried = _queried(terms)
                    break
    # A backup searched beside a term only adds records, so a count read before it was added is read again.
    await pair([row for row in checks if kept(row)
                and _with_other(row["phrase"], row["alone"], queried[_other(row["block"])]) != against[id(row)]])
    gate = f"{_group(queried['setting'])} AND {_group(queried['task'])}" if all(queried.values()) else None
    return {
        "terms": terms,
        "meta": meta,
        "backups_left": backups,
        "checks": checks,
        "warnings": [{"phrase": c["phrase"], "block": c["block"], "warning": w}
                     for c in checks for w in _warnings(c)
                     if not any(t["phrase"] == c["phrase"] and t["dropped"] for t in terms)],
        "gate_count": await counter(gate) if gate else None,
        "probes": counter.probes,
        "probes_skipped": counter.skipped,
        "searchable": all(queried.values()),
    }


def vocabulary(code_vocabulary: dict[str, Any], checked: dict[str, Any],
               record: dict[str, Any], question_words: bool = True) -> dict[str, Any]:
    """The proposal's vocabulary: the model's terms and the question's side lists.

    A side-list phrase the model also chose is left out of the side list, so no phrase stands in two blocks of the
    card at once. `record` is what the step keeps of the call (`step_input_id`, the answer, the attempts).
    `code_vocabulary` is read for the question's own language, counts and probes, which the model's terms are checked
    against; the query code once compiled from it is gone, and no run sends one.

    Without `question_words` the question's own words are not kept beside the terms: a person's saved plan is the
    whole keyword search, and a word they removed returns in no query, no ranking block and no screening block (F18).
    """
    mine = {term["phrase"] for term in checked["terms"]}
    side = {field: [phrase for phrase in code_vocabulary.get(field) or [] if norm(phrase) not in mine]
            for field in SIDE_LISTS.values()}
    return {
        "language": code_vocabulary["language"],
        "block_assignment": ASSIGNMENT,
        "terms": checked["terms"],
        **side,
        "gate_count": checked["gate_count"],
        "probes": checked["probes"],
        "probes_skipped": checked["probes_skipped"],
        # The one-million rule does not apply to the model's terms, so nothing here is too broad to search.
        "too_broad": False,
        "search_query": {"meta": checked["meta"], "backups_left": checked["backups_left"], "checks": checked["checks"],
                         "warnings": checked["warnings"], **record},
        # The question's own words, kept whole: nothing searches them, and the gate and the ranking read them.
        **({"question_vocabulary": code_vocabulary} if question_words else {}),
    }


def seed_terms(terms: list[dict[str, Any]], question_texts: list[str], passages: list[dict[str, Any]]) -> list[dict[str, str]]:
    """The searched terms the seeds brought rather than the question (a diagnosis that changes nothing): a term
    none of whose words stands in the question texts (the question and its saved English sentence) and some of whose
    words stand in the seed excerpts the query writer read, with its block, in the terms' order."""
    asked = {word.casefold() for text in question_texts for word in words(text)}
    seeded = {word.casefold() for passage in passages for word in words(passage["text"])}
    found = []
    for term in terms:
        mine = {word.casefold() for word in words(term["phrase"])}
        if not term.get("dropped") and mine and not mine & asked and mine & seeded:
            found.append({"phrase": term["phrase"], "block": term["block"]})
    return found


def is_model_written(vocabulary: dict[str, Any] | None) -> bool:
    return bool(vocabulary) and vocabulary["block_assignment"] == ASSIGNMENT


def question_vocabulary(vocabulary: dict[str, Any]) -> dict[str, Any] | None:
    """The question's own words beside the model's terms, or None in a vocabulary that is itself the question's.

    A research searched before the code query was removed kept the same words under that query's own record; they
    are read back from there, and only when that query really was searched, so what gated and ordered its records
    does not change under it.
    """
    own = vocabulary.get("question_vocabulary")
    if own is not None:
        return own
    code = vocabulary.get("code_query") or {}
    if code.get("searched") and code.get("compiled", True):
        return code["vocabulary"]
    return None


def with_authors_compiled(vocabulary: dict[str, Any], queries: list[dict[str, Any]]) -> dict[str, Any]:
    """A statement research's vocabulary with the named works whose author query was compiled (`compiled`) and those
    the request limit left out (`query_limit`), read from `queries` (R5). Any other vocabulary is returned as it is."""
    author = (vocabulary.get("statement") or {}).get("author_query")
    if author is None:
        return vocabulary
    sent = [query["authors"] for query in queries if query.get("origin") == "author"]
    cut = [group for group in author["groups"] if group not in sent] if author.get("search") and author["providers"] else []
    return vocabulary | {"statement": vocabulary["statement"] | {
        "author_query": author | {"compiled": sent, "query_limit": cut}}}


def with_compiled(vocabulary: dict[str, Any], queries: list[dict[str, Any]]) -> dict[str, Any]:
    """The vocabulary with a statement research's author record read from the first round's compiled queries
    (`with_authors_compiled`), and, for a research searched with the question's own code query, whether that query
    really was compiled within the request limit. Nothing writes that query now; this keeps reading it."""
    vocabulary = with_authors_compiled(vocabulary, queries)
    if "code_query" not in vocabulary:
        return vocabulary
    compiled = any(query.get("origin") == "code" for query in queries)
    return vocabulary | {"code_query": vocabulary["code_query"] | {"compiled": compiled}}


def settled(vocabulary: dict[str, Any] | None, queries: list[dict[str, Any]]) -> dict[str, Any] | None:
    """A stored vocabulary of a research searched with the question's own code query, with that query's `compiled`
    read back from its stored queries when it was written before that field existed (second review of 13h,
    2026-09-23). A vocabulary without that query, which is every one written since, is returned as it is."""
    if not is_model_written(vocabulary) or "compiled" in (vocabulary.get("code_query") or {"compiled": None}):
        return vocabulary
    return with_compiled(vocabulary, queries)


def question_terms(vocabulary: dict[str, Any]) -> list[dict[str, Any]]:
    """The question's own words as terms, beside the model's: what the gate and the ranking read (`question_vocabulary`)."""
    own = question_vocabulary(vocabulary)
    return list(own["terms"]) if own else []


def compile_queries(vocabulary: dict[str, Any], providers: list[str], limit: int,
                    *, broad: bool = False) -> list[dict[str, Any]]:
    """The first round: the question's own plan, one query per provider, until `limit` queries.

    One plan is searched here, the one the model wrote or the one a person saved, and every query says which
    (`origin`: `model`, or `user` for a saved plan). A statement research's author queries follow them
    (`with_authors`), and the focused queries of an `m2` plan are added after this round (`search_plan.with_focused`).

    `broad` also compiles one query for a connector searched only as a depth's second independent index
    (`registry.broad_index`); whether that query is sent is the frozen plan's own decision. Every other caller
    leaves it alone, so a follow-up search and a candidate's kill queries compile exactly what they did before.

    A research searched before the question's own code query was removed holds that query's own compiled queries in
    its stored vocabulary; they are placed here as they were sent then, one after the plan's query of the same
    provider, so a run of that research resumed under this version searches the round its protocol froze and not a
    shorter one. Nothing writes that query any more, so a research searched since has none.
    """
    # The terms of a person's saved search plan (S23a) take the model's place and say so.
    origin = "user" if vocabulary["search_query"].get("origin") == "user" else "model"
    plan = {q["provider_id"]: q | {"origin": origin}
            for q in query_compiler.compile_block_queries(vocabulary, providers, limit, broad=broad)}
    stored = vocabulary.get("code_query") or {}
    code = {q["provider_id"]: q | {"origin": "code"} for q in stored.get("queries") or []} if stored.get("searched") else {}
    ordered: list[dict[str, Any]] = []
    for provider in dict.fromkeys([*plan, *code]):
        ordered += [plan[provider]] if provider in plan else []
        # The same text was never sent twice: a code query whose text is the plan's own was left out then too.
        if provider in code and (provider not in plan or code[provider]["query_text"] != plan[provider]["query_text"]):
            ordered.append(code[provider])
    return with_authors(vocabulary, ordered, providers, limit)


def with_authors(vocabulary: dict[str, Any], queries: list[dict[str, Any]], providers: list[str],
                 limit: int) -> list[dict[str, Any]]:
    """`queries` with a statement research's author queries (R5) after the last query of each provider that takes
    them, cut to `limit`. A research with no author query gets its queries back cut as before; `with_compiled`
    records which named works the limit left without a query."""
    out: list[dict[str, Any]] = []
    for index, query in enumerate(queries):
        out.append(query)
        provider = query["provider_id"]
        if all(later["provider_id"] != provider for later in queries[index + 1:]):
            out += author_queries(vocabulary, provider, providers)
    return out[:limit]


def author_queries(vocabulary: dict[str, Any], provider: str, providers: list[str]) -> list[dict[str, Any]]:
    """A statement research's author queries for `provider` (R5): one per work the sentence names, the field's root
    word under that work's author filter, for a provider that takes one and is planned. None for any other research.
    A field whose words were not counted has no root: its words go unquoted, so OpenAlex asks for each of them (AND)
    rather than for the exact phrase ("quantum networks" would miss "quantum repeater networks")."""
    author = (vocabulary.get("statement") or {}).get("author_query") or {}
    if provider not in AUTHOR_FILTER_PROVIDERS or provider not in providers or not author.get("search"):
        return []
    from deixis.providers import openalex

    search = author["search"]
    return [{"provider_id": provider, "query_text": search if " " in search else quoted(search),
             "works_filter": openalex.author_filter(names), "authors": names, "origin": "author",
             "rationale": "Authors the sentence names, within its field"} for names in author["groups"]]
