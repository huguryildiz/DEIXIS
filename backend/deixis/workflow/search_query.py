"""The keyword query a model writes for an sw discovery run, and what code does with it (D92, slice 13h).

The model chooses at most six terms for the setting and task blocks, with a kind, a short reason and up to three
backups per block (`references/search-query.md`). Code counts every chosen term twice, alone and together with the
terms the other block is searched with. A term no record holds on its own is replaced by the next backup of its block; a term
that finds nothing together with the other block stays and is shown as a warning, because an automatic swap there
was not measured. No count removes a term for being large: the one-million rule of the code vocabulary does not
apply to what the model wrote.

The model's terms become the proposal's vocabulary and the code's own query (slice 13g) is searched beside it, as
the second measurement's "model + code" arm did (`.local/sw-model-query-experiment-2026-09-24/`). The code vocabulary
is kept whole under `code_query`, so the ranking, the abstract stage's code rules and the protocol can read the terms
of both queries, while the second round and the approval card's corrections read the model's alone.
"""

from __future__ import annotations

from typing import Any, Awaitable, Callable

from deixis.providers import query_compiler
from deixis.providers.query_compiler import quoted
from deixis.workflow.approval import SIDE_LISTS, canonical_edits
from deixis.workflow.criterion import norm
from deixis.workflow.vocabulary import GATE_BLOCKS, TERM_FIELDS

ASSIGNMENT = "search_query"  # the vocabulary's `block_assignment`, and the origin of the model's own terms
ATTEMPTS = 2  # the first call, and one more when the user asks for it after a failure
MAX_COUNT_REQUESTS = 24  # six chosen terms and six backups, each counted alone and with the other block
KINDS = ("topic", "method", "population", "other")
THRESHOLDS = {"attempts": ATTEMPTS, "max_count_requests": MAX_COUNT_REQUESTS}


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

    def __init__(self, count: Callable[[str], Awaitable[int | None]], known: dict[str, int | None] | None = None):
        self.count, self.known, self.asked, self.skipped = count, dict(known or {}), 0, 0
        self.probes: list[dict[str, Any]] = []

    async def __call__(self, query: str) -> int | None:
        if query in self.known:
            value = self.known[query]
        elif self.asked >= MAX_COUNT_REQUESTS:
            self.skipped += 1
            return None
        else:
            self.asked += 1
            value = self.known[query] = await self.count(query)
        self.probes.append({"query": query, "count": value})
        return value


async def _with_other(phrase: str, alone: int | None, other: list[str], counter: _Counter) -> int | None:
    """The count of a term together with the terms the other block is searched with, once no swap changes them."""
    return await counter(f"{quoted(phrase)} AND {_group(other)}") if other and alone != 0 else None


def _queried(terms: list[dict[str, Any]]) -> dict[str, list[str]]:
    return {block: [t["phrase"] for t in terms if t["block"] == block and not t["dropped"]] for block in GATE_BLOCKS}


def _warnings(row: dict[str, Any]) -> list[str]:
    if row["alone"] is None:
        return ["count_unknown"]
    if row["with_other_block"] == 0:
        return ["no_records_with_other_block"]
    return []


async def check(answer: dict[str, Any], count: Callable[[str], Awaitable[int | None]]) -> dict[str, Any]:
    """Count the answer's chosen terms and put a backup in place of each one no record holds (D92).

    Every term is counted alone first, so every swap is made before any term is counted with the other block; the
    count with the other block then reads the terms that block is really searched with. Every count, every
    replacement and every warning is returned, so the approval card and the protocol show the numbers that decided
    the query. A block left with no term is returned as it is: the caller treats that answer as one that cannot be
    searched.
    """
    chosen, backups = answer_terms(answer)
    counter = _Counter(count)
    meta = {row["phrase"]: {"kind": row["kind"], "why": row["why"], "backup_for": None}
            for block in GATE_BLOCKS for row in chosen[block]}
    terms: list[dict[str, Any]] = []
    checks: list[dict[str, Any]] = []
    for block in GATE_BLOCKS:
        spare = list(backups[block])
        for row in chosen[block]:
            phrase, replaced = row["phrase"], None
            while True:
                alone = await counter(quoted(phrase))
                checks.append({"phrase": phrase, "block": block, "alone": alone, "with_other_block": None,
                               "backup_for": replaced})
                if alone != 0:
                    terms.append(_term(phrase, block, ASSIGNMENT, alone))
                    break
                terms.append(_term(phrase, block, ASSIGNMENT, 0, "zero_results"))
                if not spare:
                    break
                replaced, phrase = phrase, spare.pop(0)
                meta[phrase] = {"kind": None, "why": None, "backup_for": replaced}
        backups[block] = spare
    queried = _queried(terms)
    for row in checks:
        row["with_other_block"] = await _with_other(row["phrase"], row["alone"], queried[_other(row["block"])], counter)
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


def vocabulary(code_vocabulary: dict[str, Any], code_queries: list[dict[str, Any]], checked: dict[str, Any],
               record: dict[str, Any]) -> dict[str, Any]:
    """The proposal's vocabulary: the model's terms, the question's side lists, and the code's query kept whole.

    A side-list phrase the model also chose is left out of the side list, so no phrase stands in two blocks of the
    card at once. `record` is what the step keeps of the call (`step_input_id`, the answer, the attempts).
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
        # A code query that cannot be searched on its own (none compiled, or too broad) is not offered beside it.
        "code_query": {"vocabulary": code_vocabulary, "queries": code_queries,
                       "searched": bool(code_queries) and not code_vocabulary["too_broad"]},
    }


def is_model_written(vocabulary: dict[str, Any] | None) -> bool:
    return bool(vocabulary) and vocabulary["block_assignment"] == ASSIGNMENT


def code_searched(vocabulary: dict[str, Any]) -> bool:
    """Whether the code's query is really searched beside the model's: switched on, and at least one of its queries
    compiled within the request limit (`with_compiled`). A vocabulary stored before `compiled` was written reads the
    switch alone, as it did then."""
    code = vocabulary.get("code_query") or {}
    return bool(code.get("searched")) and code.get("compiled", True)


def with_compiled(vocabulary: dict[str, Any], queries: list[dict[str, Any]]) -> dict[str, Any]:
    """The vocabulary with `code_query.compiled` set from the first round's compiled queries. The switch the user
    sees (`searched`) is left as it is."""
    if "code_query" not in vocabulary:
        return vocabulary
    compiled = any(query.get("origin") == "code" for query in queries)
    return vocabulary | {"code_query": vocabulary["code_query"] | {"compiled": compiled}}


def code_terms(vocabulary: dict[str, Any]) -> list[dict[str, Any]]:
    """The code query's terms when that query is searched beside the model's, otherwise none."""
    return list(vocabulary["code_query"]["vocabulary"]["terms"]) if code_searched(vocabulary) else []


def compile_queries(vocabulary: dict[str, Any], providers: list[str], limit: int) -> list[dict[str, Any]]:
    """The first round: per provider the model's query and then the code's, until `limit` queries.

    Interleaving keeps the pair the measurement read — both queries on OpenAlex — on every effort, however few
    queries it allows. A code query whose text is the model's own is not sent twice. Every query says where it came
    from (`origin`).
    """
    model = {q["provider_id"]: q | {"origin": "model"}
             for q in query_compiler.compile_block_queries(vocabulary, providers, limit)}
    code = {q["provider_id"]: q | {"origin": "code"} for q in vocabulary["code_query"]["queries"]} \
        if vocabulary["code_query"]["searched"] else {}
    ordered: list[dict[str, Any]] = []
    for provider in dict.fromkeys([*model, *code]):
        ordered += [model[provider]] if provider in model else []
        if provider in code and (provider not in model or code[provider]["query_text"] != model[provider]["query_text"]):
            ordered.append(code[provider])
    return ordered[:limit]


def model_queries(queries: list[dict[str, Any]]) -> list[dict[str, Any]]:
    """The first round's queries the model's terms wrote; all of them for a vocabulary with no origin marks."""
    return [query for query in queries if query.get("origin", "model") == "model"]


async def rebuild(vocabulary: dict[str, Any], term_edits: list[dict[str, Any]], code_query: bool | None,
                  count: Callable[[str], Awaitable[int | None]], model_phrases: frozenset[str] | set[str] = frozenset()
                  ) -> dict[str, Any]:
    """The model-written vocabulary after the user's correction on the approval card.

    The operations act on the model's terms and the side lists, never on the code's query, which the user can only
    switch off (`code_query=False`). A phrase the user adds or moves into a block is counted like the model's own:
    no record alone and it enters as dropped; nothing with the other block and it carries the warning. A count this
    vocabulary already read is not asked again. The code vocabulary's forms (roots, gate narrowing) are not applied:
    the model's terms enter the query as whole phrases, as they were measured.
    """
    operations = {edit["phrase"]: edit for edit in canonical_edits(term_edits)}
    counter = _Counter(count, {probe["query"]: probe["count"] for probe in vocabulary["probes"]})
    meta = dict(vocabulary["search_query"]["meta"])
    rows: list[tuple[str, str, str]] = []  # (phrase, block, origin) in the vocabulary's order
    for term in vocabulary["terms"]:
        edit = operations.get(norm(term["phrase"]))
        if edit is None:
            rows.append((term["phrase"], term["block"], term["origin"]))
        elif edit["op"] == "move":
            rows.append((term["phrase"], edit["block"], term["origin"]))
    for block, field in SIDE_LISTS.items():
        for phrase in vocabulary.get(field) or []:
            edit = operations.get(norm(phrase))
            if edit is None:
                rows.append((phrase, block, "question"))
            elif edit["op"] == "move":
                rows.append((phrase, edit["block"], "question"))
    rows +=[(edit["phrase"], edit["block"], "model" if edit["phrase"] in model_phrases else "user")
             for edit in operations.values() if edit["op"] == "add"]
    before = {term["phrase"]: term for term in vocabulary["terms"]}
    terms: list[dict[str, Any]] = []
    checks = list(vocabulary["search_query"]["checks"])
    counted_here: list[dict[str, Any]] = []
    for phrase, block, origin in rows:
        if block not in GATE_BLOCKS:
            continue
        kept = before.get(phrase)
        if kept is not None and kept["block"] == block:
            terms.append(kept)
            continue
        alone = await counter(quoted(phrase))
        counted_here.append({"phrase": phrase, "block": block, "alone": alone, "with_other_block": None,
                             "backup_for": None})
        terms.append(_term(phrase, block, origin, alone, "zero_results" if alone == 0 else None))
        meta.setdefault(phrase, {"kind": None, "why": None, "backup_for": None})
    # Every searched term is counted again with the other block as corrected, the kept ones too: a warning read
    # against a block the user changed would describe a query that is no longer sent. A count already read is not
    # asked again, and a kept term's count is written again only where it changed.
    queried = _queried(terms)
    last = {c["phrase"]: c for c in checks}
    warnings: list[dict[str, Any]] = []
    for term in terms:
        if term["dropped"]:
            continue
        phrase, block = term["phrase"], term["block"]
        row = next((c for c in counted_here if c["phrase"] == phrase), None)
        fresh = row is not None
        row = row or {"phrase": phrase, "block": block, "alone": term["phrase_count"], "with_other_block": None,
                      "backup_for": None}
        row["with_other_block"] = await _with_other(phrase, row["alone"], queried[_other(block)], counter)
        if not fresh and (phrase not in last or last[phrase]["with_other_block"] != row["with_other_block"]):
            counted_here.append(row)
        warnings += [{"phrase": phrase, "block": block, "warning": w} for w in _warnings(row)]
    checks += counted_here
    gate_query = f"{_group(queried['setting'])} AND {_group(queried['task'])}" if all(queried.values()) else None
    code = dict(vocabulary["code_query"])
    if code_query is not None:
        code["searched"] = bool(code_query)
    return vocabulary | {
        "terms": [{field: term[field] for field in TERM_FIELDS} for term in terms],
        **{field: [phrase for phrase, b, _ in rows if b == block] for block, field in SIDE_LISTS.items()},
        "gate_count": await counter(gate_query) if gate_query else None,
        "probes": vocabulary["probes"] + [p for p in counter.probes if p["query"] not in
                                          {q["query"] for q in vocabulary["probes"]}],
        "search_query": vocabulary["search_query"] | {
            "meta": {phrase: row for phrase, row in meta.items() if any(t["phrase"] == phrase for t in terms)},
            "warnings": warnings, "checks": checks},
        "code_query": code,
        "user_edits": canonical_edits(term_edits),
    }
