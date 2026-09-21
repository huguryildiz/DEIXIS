"""The extracted phrases tried against the literature and narrowed by their record counts (SW2.2, SW3.5).

Each phrase and each of its distinctive words is counted with one count-only request. A phrase no record holds is
dropped; every term then enters the query by its root word, and a root is replaced by its phrase only when the gate
query — the setting block AND the task block — returns more records than the run can read. The counts decide, nothing
else. A count that could not be read is not a small count: the term stays and enters as the whole phrase, which is
the narrow and safe side.

The counts are read once. A resumed run reuses the stored step output rather than probing again, so a number here is
what the literature held on the day of the first run, not today.
"""

from __future__ import annotations

from collections import Counter
from dataclasses import replace
from typing import Any, Awaitable, Callable

from deixis.domain.vocabulary import BLOCK_NAMES, ENGLISH_FUNCTION_WORD_SHARE, LONG_QUESTION_WORDS, Extraction
from deixis.domain.vocabulary_words import GENERAL_WORDS
from deixis.providers.query_compiler import quoted

MAX_PROBES = 40  # count requests one vocabulary step may send
LABEL_RUNS = 3  # SW17.3: the block labelling is asked this many times
LABEL_MAJORITY = 2  # and a label is kept when it appears in at least this many runs
MAX_LABELLED_PHRASES = 40  # a longer phrase list is not sent: the rule's assignment stands
LABELS = ("setting", "task", "outcome", "claim", "exclusion", "not_a_term")
VERY_LARGE_COUNT = 1_000_000  # SW2.2: a term this frequent is usable only inside an AND
MANAGEABLE_TOTAL = 5_000  # SW3.5: above this the gate query is narrowed from a root word to its phrase
THRESHOLDS = {
    "english_function_word_share": ENGLISH_FUNCTION_WORD_SHARE,
    "long_question_words": LONG_QUESTION_WORDS,
    "max_probes": MAX_PROBES,
    "very_large_count": VERY_LARGE_COUNT,
    "manageable_total": MANAGEABLE_TOTAL,
}
# Only these two blocks are queried. The method block stays empty (its phrases are claim words) and the outcome block
# is kept for ranking, so the gate is setting AND task (SW1.3).
GATE_BLOCKS = ("setting", "task")
TERM_FIELDS = ("phrase", "block", "origin", "root", "in_query", "phrase_count", "root_count", "and_only", "dropped")


def _distinctive(phrase: str) -> list[str]:
    return [word for word in phrase.split() if word not in GENERAL_WORDS]


def _or_group(forms: list[str]) -> str:
    return "(" + " OR ".join(forms) + ")"


def labelling_phrases(extraction: Extraction) -> list[dict[str, str]]:
    """The phrases the labelling step is given, each with the block the code rule put it in.

    The order is block by block and, inside a block, the order the question gave: an `Extraction` keeps the order
    within a block and not the order across blocks, so this is the closest stable order to the question's own. It
    is fixed, which is what the step needs; no set iteration reaches the model or the result.
    """
    rows = [{"phrase": phrase, "rule_block": block} for block in BLOCK_NAMES for phrase in extraction.blocks[block]]
    rows += [{"phrase": phrase, "rule_block": "claim"} for phrase in extraction.claim_words]
    rows += [{"phrase": phrase, "rule_block": "exclusion"} for phrase in extraction.exclusion_words]
    return rows


def apply_labels(extraction: Extraction, runs: list[dict[str, str]]) -> tuple[Extraction, list[dict[str, Any]]]:
    """The extraction with the model's block for each phrase, and the per-phrase record of how it was decided (SW17).

    Only runs that produced a valid output are passed in. Below `LABEL_MAJORITY` of them no majority can form at all,
    so the rule's whole assignment stands and the result is what slice 04a would have searched: the first search
    never depends on the model being reachable. With enough runs, a phrase the runs disagree about keeps the rule's
    label in its record but enters no list, because the rule is the thing this step exists to correct (SW17.3).
    A labelling that leaves no gate term at all is not applied either: the rule's assignment is the floor.
    """
    applied = len(runs) >= LABEL_MAJORITY
    blocks: dict[str, list[str]] = {name: [] for name in BLOCK_NAMES}
    claim_words: list[str] = []
    exclusion_words: list[str] = []
    records: list[dict[str, Any]] = []
    for row in labelling_phrases(extraction):
        phrase, rule_block = row["phrase"], row["rule_block"]
        votes = [run.get(phrase) for run in runs]
        counted = Counter(vote for vote in votes if vote in LABELS)
        agreed = sorted(label for label, count in counted.items() if count >= LABEL_MAJORITY)
        decided = agreed[0] if applied and len(agreed) == 1 else None
        block = decided or rule_block
        place = block if decided or not applied else None
        if place in blocks:
            blocks[place].append(phrase)
        elif place == "claim":
            claim_words.append(phrase)
        elif place == "exclusion":
            exclusion_words.append(phrase)
        # The runs are three answers to one question and have no order of their own, so what each of them said is
        # recorded in canonical order (SW14.6); which step said which is in that step's own stored output.
        records.append({"phrase": phrase, "rule_block": rule_block, "runs": sorted(v for v in votes if v is not None),
                        "block": block, "origin": "model" if decided else "rule"})
    if applied and not any(blocks[name] for name in GATE_BLOCKS) and any(extraction.blocks[name] for name in GATE_BLOCKS):
        # The labelling left nothing to search with while the rule has a gate term: runs that agree on nothing, or
        # that call every phrase a claim. It may correct the rule's query, never take the first search away (SW17.5),
        # so the rule's whole assignment stands, as it does when too few runs arrive. The votes stay on record.
        return extraction, [record | {"block": record["rule_block"], "origin": "rule"} for record in records]
    labelled = replace(extraction, blocks=blocks, claim_words=claim_words, exclusion_words=exclusion_words,
                       block_assignment="model" if applied else extraction.block_assignment)
    return labelled, records


async def build_vocabulary(extraction: Extraction, count: Callable[[str], Awaitable[int | None]],
                           known: dict[str, int | None] | None = None) -> dict[str, Any]:
    """Probe the extraction's setting and task phrases and decide the form each one enters the query in.

    The probe order is fixed so that two runs of the same question spend the budget on the same terms: the setting
    block then the task block, each in the order the question gave, phrases before their words, gate queries last.

    `known` holds counts a proposal of this same run already read (slice 08a): a query answered from it is recorded
    as the probe it was and asks nothing, and it spends none of the budget, so the requests a correction is allowed
    go to the terms the correction added.
    """
    origin = "key_terms" if extraction.block_assignment == "user" else "question"
    known = known or {}
    probes: list[dict[str, Any]] = []
    skipped = asked = 0

    async def probe(query: str) -> int | None:
        """One count request, or nothing once the budget is spent. An unspent answer is never invented."""
        nonlocal skipped, asked
        if query in known:
            probes.append({"query": query, "count": known[query]})
            return known[query]
        if asked >= MAX_PROBES:
            skipped += 1
            return None
        asked += 1
        value = await count(query)
        probes.append({"query": query, "count": value})
        return value

    terms: list[dict[str, Any]] = []
    for block in GATE_BLOCKS:
        for phrase in extraction.blocks[block]:
            terms.append({"phrase": phrase, "block": block, "origin": extraction.origins.get(phrase, origin),
                          "root": phrase, "in_query": "phrase", "phrase_count": None, "root_count": None,
                          "and_only": False, "dropped": None})
    words_of = {term["phrase"]: _distinctive(term["phrase"]) for term in terms}

    for term in terms:
        term["phrase_count"] = await probe(quoted(term["phrase"]))
        if term["phrase_count"] == 0:
            term["dropped"] = "zero_results"

    # A dropped phrase never enters the query, so its words are not probed: the budget belongs to terms that can.
    word_counts: dict[str, int | None] = {}
    for term in terms:
        if term["dropped"] or len(words_of[term["phrase"]]) <= 1:
            continue
        for word in words_of[term["phrase"]]:
            if word not in word_counts:
                word_counts[word] = await probe(word)

    for term in terms:
        if term["dropped"]:
            continue
        words = words_of[term["phrase"]]
        rooted = True
        if len(words) == 1:
            term["root"], term["root_count"] = words[0], term["phrase_count"]
        elif usable := [(word_counts[w], position, w) for position, w in enumerate(words)
                        if isinstance(word_counts.get(w), int) and word_counts[w] > 0]:
            # The most distinctive word of the phrase is the one the fewest records hold; a tie keeps the earlier word.
            term["root_count"], _, term["root"] = min(usable)
        else:
            rooted = False  # no word of the phrase was counted, or every word was counted zero
        # SW3.5: a term starts in the query as its root word. A phrase whose own count could not be read, or whose
        # words gave no usable root, enters whole instead.
        term["in_query"] = "root" if rooted and term["phrase_count"] is not None else "phrase"

    def gate_query() -> str | None:
        groups = [_or_group([quoted(t["root"] if t["in_query"] == "root" else t["phrase"]) for t in group])
                  for block in GATE_BLOCKS
                  if (group := [t for t in terms if t["block"] == block and not t["dropped"]])]
        return " AND ".join(groups) if groups else None

    gate_count = await probe(query) if (query := gate_query()) else None
    while gate_count is not None and gate_count > MANAGEABLE_TOTAL:
        wide = [t for t in terms if not t["dropped"] and t["in_query"] == "root"
                and len(words_of[t["phrase"]]) > 1 and isinstance(t["root_count"], int)]
        if not wide:
            break
        # The widest root goes first, so the narrowing stops as soon as the result set is readable (SW3.5).
        max(wide, key=lambda t: (t["root_count"], -terms.index(t)))["in_query"] = "phrase"
        gate_count = await probe(gate_query())

    for term in terms:
        form_count = term["root_count"] if term["in_query"] == "root" else term["phrase_count"]
        term["and_only"] = isinstance(form_count, int) and form_count > VERY_LARGE_COUNT

    queried = [t for t in terms if not t["dropped"]]
    return {
        "language": extraction.language,
        "block_assignment": extraction.block_assignment,
        "terms": [{field: term[field] for field in TERM_FIELDS} for term in terms],
        "claim_words": list(extraction.claim_words),
        "exclusion_words": list(extraction.exclusion_words),
        "outcome_terms": list(extraction.blocks["outcome"]),
        "gate_count": gate_count,
        "probes": probes,
        "probes_skipped": skipped,
        # One block of terms that are all too frequent to stand alone cannot be narrowed by an AND with another block.
        "too_broad": bool(queried) and len({t["block"] for t in queried}) == 1 and all(t["and_only"] for t in queried),
    }
