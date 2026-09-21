"""The order an `sw` run inspects its records in: four code signals and an optional embedding, fused by rank (SW7, SW8).

The order is an inspection order and nothing else. It removes no record, writes no decision and changes no selection;
what it decides is which candidate the screening batches read first. No model is called here and no request is sent:
the four code signals are computed from what the search already stored, and the embedding signal is read from the
similarities `_source_similarity` wrote.

The signals are the ones measured in `.local/quantum-rank-fusion-2026-09-18/fuse.py` on one topic with 20 positives,
with four named deviations (D79): the product's own word splitter, a block score kept as a pair instead of a
weighted sum, matching at a word start, and a record without an abstract scored by BM25 on its title while only
TF-IDF counts it as missing. That measurement showed fusion is not worse than BM25 alone and protects against one
collapsed signal — not that it is better.

Ranks are fused, never raw scores (SW7.1): a tie inside a signal shares the mean rank, a missing signal is ranked
last in that signal and still enters the sum, and the final tie is broken by the record identifier, so no result
depends on set iteration, row order or the hash seed (SW14.6).
"""

from __future__ import annotations

import math
from collections import Counter
from typing import Any

from deixis.domain.vocabulary import words
from deixis.workflow.decisions import DecisionStore

BM25_K1 = 1.5  # fuse.py's values; not varied
BM25_B = 0.75
GRAPH_SEEDS = 15  # SW7 context: seeds code picks when the research has too few verified ones
RESCUE_OUTSIDE_TOP = 200  # SW8.1
RESCUE_EMBEDDING_TOP = 50  # SW8.1
THRESHOLDS = {"bm25_k1": BM25_K1, "bm25_b": BM25_B, "graph_seeds": GRAPH_SEEDS,
              "rescue_outside_top": RESCUE_OUTSIDE_TOP, "rescue_embedding_top": RESCUE_EMBEDDING_TOP}
CODE_SIGNALS = ("bm25", "blocks", "tfidf", "graph")
SIGNALS = (*CODE_SIGNALS, "embedding")
# The three rows a ranking stores beside the signals: the code-only order the rescue arm reads, the order of every
# signal that ran, and the inspection order screening follows.
ORDERS = ("fused_code", "fused", "inspection")


def _text(row: dict[str, Any]) -> list[str]:
    return words(f"{row['title']} {row['abstract'] or ''}")


def _padded(text: str) -> str:
    """The text as one space-padded run of words, so a form can be matched at a word start by substring search."""
    return " " + " ".join(words(text)) + " "


def bm25_scores(pool: list[dict[str, Any]], query_words: set[str]) -> dict[str, float]:
    """BM25 of title plus abstract against the question's and every queried term's words (fuse.py lines 17–21).

    Stop words are not removed: the inverse document frequency already discounts them, and the measurement did not
    remove them either. A record without an abstract is scored on its title (named deviation 4).
    """
    documents = {row["id"]: _text(row) for row in pool}
    count = len(documents) or 1
    average = sum(map(len, documents.values())) / count or 1.0
    frequency = Counter(word for document in documents.values() for word in set(document))
    scores: dict[str, float] = {}
    for rid, document in documents.items():
        tf, length = Counter(document), len(document)
        # Sorted, because a set's iteration order must not decide the order the floats are added in (SW14.6).
        scores[rid] = sum(
            math.log(1 + (count - frequency[word] + 0.5) / (frequency[word] + 0.5))
            * tf[word] * (BM25_K1 + 1) / (tf[word] + BM25_K1 * (1 - BM25_B + BM25_B * length / average))
            for word in sorted(query_words) if tf[word])
    return scores


def block_scores(pool: list[dict[str, Any]], blocks: dict[str, list[str]]) -> dict[str, tuple[int, int]]:
    """How many concept blocks the title hits, then how many distinct forms title and abstract hold.

    A pair, not fuse.py's `blocks * 100 + forms` (named deviation 2): the order is the same and no term count can
    overflow into the block count. A form matches at a word start, so a root catches its plural but not a word that
    merely contains it (named deviation 3); this is deliberately not `expansion.count_yields`'s two-ended match,
    which counts rather than ranks.
    """
    forms = {name: [f" {' '.join(words(form))}" for form in group if words(form)] for name, group in blocks.items()}
    scores: dict[str, tuple[int, int]] = {}
    for row in pool:
        title, whole = _padded(row["title"]), _padded(f"{row['title']} {row['abstract'] or ''}")
        in_title = sum(any(form in title for form in group) for group in forms.values())
        distinct = sum(form in whole for group in forms.values() for form in group)
        scores[row["id"]] = (in_title, distinct)
    return scores


def _vectors(documents: dict[str, list[str]], frequency: Counter, count: int) -> dict[str, dict[str, float]]:
    """Unit-length (1 + log tf) · log(N / df) vectors (fuse.py lines 27–30); a word the pool does not hold is dropped."""
    vectors: dict[str, dict[str, float]] = {}
    for rid, document in documents.items():
        vector = {word: (1 + math.log(times)) * math.log(count / frequency[word])
                  for word, times in Counter(document).items() if 0 < frequency[word] < count}
        norm = math.sqrt(sum(value * value for value in vector.values())) or 1.0
        vectors[rid] = {word: value / norm for word, value in vector.items()}
    return vectors


def tfidf_scores(pool: list[dict[str, Any]], seeds: list[dict[str, Any]]) -> dict[str, float]:
    """The largest cosine to a seed that is not a version of the record's own work (fuse.py line 47).

    Document frequency is counted from the pool alone, so a seed from outside it contributes only the words the pool
    knows. The signal is missing for a record with no abstract (SW7.4), which `availability` records.
    """
    documents = {row["id"]: _text(row) for row in pool}
    count = len(documents) or 1
    frequency = Counter(word for document in documents.values() for word in set(document))
    vectors = _vectors(documents, frequency, count)
    seed_vectors = _vectors({seed["id"]: _text(seed) for seed in seeds}, frequency, count)

    def cosine(a: dict[str, float], b: dict[str, float]) -> float:
        small, large = (a, b) if len(a) < len(b) else (b, a)
        return sum(value * large.get(word, 0.0) for word, value in small.items())

    scores = {}
    for row in pool:
        others = [seed for seed in seeds if seed["work_id"] != row["work_id"]]
        scores[row["id"]] = max((cosine(vectors[row["id"]], seed_vectors[seed["id"]]) for seed in others), default=0.0)
    return scores


def graph_scores(pool: list[dict[str, Any]], seeds: list[dict[str, Any]]) -> dict[str, float]:
    """Bibliographic coupling with the seeds plus a direct citation in either direction (fuse.py lines 48–49).

    Co-citation is not part of this: it would need a request for the works that cite each record (SW7 Limits). A
    record never counts a version of its own work as a seed.
    """
    scores = {}
    for row in pool:
        mine, own = row["references"] or frozenset(), row["own_ids"]
        total = 0.0
        for seed in seeds:
            if seed["work_id"] == row["work_id"]:
                continue
            theirs = seed["references"] or frozenset()
            if mine and theirs:
                total += len(mine & theirs) / math.sqrt(len(mine) * len(theirs))
            total += bool(seed["own_ids"] & mine) + bool(own & theirs)
        scores[row["id"]] = total
    return scores


def availability(pool: list[dict[str, Any]], signal: str) -> dict[str, bool]:
    """Whether each record has the signal at all. The embedding's own availability is the stored similarity, which
    is not in the pool row, so `rank_records` builds that one.

    BM25 and the blocks read the title, which every record has. TF-IDF needs an abstract and the graph needs a
    reference list that was read and is not empty (SW7.4).
    """
    if signal in ("bm25", "blocks"):
        return {row["id"]: True for row in pool}
    if signal == "tfidf":
        return {row["id"]: bool(row["abstract"]) for row in pool}
    if signal == "graph":
        return {row["id"]: bool(row["references"]) for row in pool}
    raise ValueError(f"no availability rule for {signal!r}")


def mean_ranks(scores: dict[str, Any], available: dict[str, bool]) -> dict[str, tuple[float, bool]]:
    """Place each record in one signal: 1 is best, equal scores share the mean rank (fuse.py `ranks`).

    A record the signal is missing for goes to the end whatever its score, and the records there share that tail's
    mean rank, so nothing inside the tail is ordered by a number the signal never produced.
    """
    have = [rid for rid in scores if available.get(rid, True)]
    missing = sorted(rid for rid in scores if not available.get(rid, True))
    ranked: dict[str, tuple[float, bool]] = {}
    ordered = sorted(have, key=lambda rid: scores[rid], reverse=True)
    start = 0
    while start < len(ordered):
        end = start
        while end + 1 < len(ordered) and scores[ordered[end + 1]] == scores[ordered[start]]:
            end += 1
        shared = (start + end) / 2 + 1
        for rid in ordered[start:end + 1]:
            ranked[rid] = (shared, True)
        start = end + 1
    if missing:
        tail = (len(have) + len(scores) - 1) / 2 + 1
        for rid in missing:
            ranked[rid] = (tail, False)
    return ranked


def fuse(ranks: dict[str, dict[str, tuple[float, bool]]], signals: tuple[str, ...],
         k: int | None = None) -> list[str]:
    """Reciprocal rank fusion over the signals that ran; a missing signal enters at its last place, never dropped.

    `missing_signal.py` measured dropping it and the median got worse (158 → 171), so the term stays in the sum.
    """
    # Imported here rather than at the top: flow loads this module, and k is read from its one definition (D27).
    from deixis.workflow.flow import RRF_K

    constant = RRF_K if k is None else k
    running = [ranks[signal] for signal in signals if signal in ranks]
    ids = sorted({rid for row in running for rid in row})
    scores = {rid: sum(1 / (constant + row[rid][0]) for row in running) for rid in ids}
    # An equal sum is broken by the record identifier, never by which signal was fused first (SW14.6).
    return sorted(ids, key=lambda rid: (-scores[rid], rid))


def inspection_order(fused: list[str], fused_code: list[str],
                     embedding_ranks: dict[str, tuple[float, bool]] | None) -> tuple[list[str], list[str]]:
    """The order screening reads, and the records the embedding arm brought to its front (SW8.1).

    A record outside the top `RESCUE_OUTSIDE_TOP` of the four code signals' own fused order but inside the embedding's
    top `RESCUE_EMBEDDING_TOP` goes to the front, in embedding order. Everything else keeps its fused place. A record
    the embedding never scored cannot be rescued by the tail rank it shares with the other unscored records: the
    embedding has no authority and adds nothing it did not measure (SW8.2).
    """
    if embedding_ranks is None:
        return list(fused), []
    place = {rid: position + 1 for position, rid in enumerate(fused_code)}
    rescued = [rid for rid in fused
               if place.get(rid, len(fused_code) + 1) > RESCUE_OUTSIDE_TOP
               and embedding_ranks.get(rid, (0.0, False))[1]
               and embedding_ranks[rid][0] <= RESCUE_EMBEDDING_TOP]
    rescued.sort(key=lambda rid: (embedding_ranks[rid][0], rid))
    lifted = set(rescued)
    return rescued + [rid for rid in fused if rid not in lifted], rescued


# ---- the pool, the seeds and the one store-driven entry point ----------------------------------

def _versions(store: Any, research_id: str) -> dict[str, dict[str, Any]]:
    """Every record still in the research, with its own text, its own provider identifiers and its own references.

    Read in a few whole-research queries rather than one query per record: `held_from_screening` cost a second on
    2,000 candidates when it asked per record (slice 05 review).
    """
    rows = {row["id"]: {"id": row["id"], "work_id": row["work_id"], "title": row["title"],
                        "abstract": row["abstract"], "references_read": bool(row["references_read"]),
                        "own_ids": set(), "references": set()}
            for row in store.conn.execute(
                "SELECT v.id, v.work_id, v.title, v.references_read,"
                " (SELECT group_concat(p.text, ' ') FROM passages p WHERE p.source_version_id = v.id"
                "  AND p.kind = 'abstract') AS abstract"
                " FROM corpus_memberships m JOIN source_versions v ON v.id = m.source_version_id"
                " WHERE m.research_id = ? AND m.removed_at IS NULL", (research_id,))}
    member = ("JOIN corpus_memberships m ON m.source_version_id = r.source_version_id"
              " AND m.research_id = ? AND m.removed_at IS NULL")
    for field, query in (
        ("own_ids", f"SELECT r.source_version_id AS svid, r.value AS value FROM identifier_mappings r {member}"
                    " WHERE r.scheme = 'openalex'"),
        ("references", f"SELECT r.source_version_id AS svid, r.referenced_id AS value FROM record_references r {member}"),
    ):
        for row in store.conn.execute(query, (research_id,)):
            if row["svid"] in rows:
                rows[row["svid"]][field].add(row["value"])
    return rows


def _work_row(head: str, versions: list[dict[str, Any]]) -> dict[str, Any]:
    """One pool row for a work: the head's title, its own abstract or another version's, and the union of the rest.

    A preprint's reference list and a published record's abstract belong to the same work, so the signals read both
    (D79). The union only ranks; no version logic, no selection and no identity rule is touched by it.
    """
    by_id = {version["id"]: version for version in versions}
    own = by_id[head]
    # A head without an abstract of its own borrows one from another version of the work, smallest identifier first,
    # so which version the search happened to return first cannot change the score.
    abstract = own["abstract"] or next((v["abstract"] for v in sorted(versions, key=lambda v: v["id"]) if v["abstract"]), None)
    read = [version for version in versions if version["references_read"]]
    return {"id": head, "work_id": own["work_id"], "title": own["title"], "abstract": abstract,
            "own_ids": frozenset().union(*[frozenset(v["own_ids"]) for v in versions]),
            "references": frozenset().union(*[frozenset(v["references"]) for v in read]) if read else None}


def _seed_row(svid: str, versions: dict[str, dict[str, Any]]) -> dict[str, Any] | None:
    """A seed that is not in the pool: its own title and abstract, its own identifiers and its own references."""
    version = versions.get(svid)
    if version is None:
        return None
    return {"id": svid, "work_id": version["work_id"], "title": version["title"], "abstract": version["abstract"],
            "own_ids": frozenset(version["own_ids"]),
            "references": frozenset(version["references"]) if version["references_read"] else None}


def verified_seeds(store: Any, research_id: str, scope: dict[str, Any]) -> list[str]:
    """The records this research has verified: what the user included, and the scope's own seed (SW7.5).

    A record the model included is not verified. Order is the record identifier, so nothing here depends on which
    row the database returned first.
    """
    chosen = {row[0] for row in store.conn.execute(
        "SELECT s.source_version_id FROM selections s JOIN corpus_memberships m"
        " ON m.research_id = s.research_id AND m.source_version_id = s.source_version_id AND m.removed_at IS NULL"
        " WHERE s.research_id = ? AND s.origin = 'user' AND s.state = 'included'", (research_id,))}
    seed = (scope.get("seed_snapshot") or {}).get("source_version_id")
    if seed:
        chosen.add(seed)
    return sorted(chosen)


def query_vocabulary(scope: dict[str, Any], vocabulary: dict[str, Any],
                     expansion_terms: list[str]) -> tuple[set[str], dict[str, list[str]]]:
    """The words BM25 reads and the block forms the block signal reads: the question and every queried term."""
    from deixis.workflow.expansion import TASK_BLOCK, queried_form, queried_terms, term_rows
    from deixis.workflow.vocabulary import GATE_BLOCKS

    query_words = set(words(scope["question"]))
    for row in term_rows(vocabulary["terms"], {"terms": list(expansion_terms)}):
        query_words |= set(words(row["phrase"])) | set(words(row["form"]))
    blocks = {block: [queried_form(term) for term in queried_terms(vocabulary, block)] for block in GATE_BLOCKS}
    # The second round's accepted phrases were searched as the task block, so that is where they rank (slice 04b).
    blocks[TASK_BLOCK] = blocks[TASK_BLOCK] + list(expansion_terms)
    return query_words, blocks


def rank_records(store: Any, run: dict[str, Any], scope: dict[str, Any], vocabulary: dict[str, Any],
                 expansion_terms: list[str], embedding_model: str | None = None) -> dict[str, Any]:
    """Rank this revision's records and store every rank; returns the step output.

    The pool is the work heads the search offered, the records slice 05 holds back from screening included: they are
    ranked like the rest and only the screening list leaves them out. Nothing here removes a record, writes a
    decision or changes a selection.
    """
    research_id, revision = run["research_id"], run["scope_revision"]
    heads = set(store.work_heads(research_id).values())
    versions = _versions(store, research_id)
    by_work: dict[str, list[dict[str, Any]]] = {}
    for version in versions.values():
        by_work.setdefault(version["work_id"], []).append(version)
    pool = [_work_row(candidate["source_version_id"], by_work[versions[candidate["source_version_id"]]["work_id"]])
            for candidate in store.candidates(research_id, revision)
            if candidate["origin"] != "user" and candidate["source_version_id"] in heads
            and candidate["source_version_id"] in versions]
    query_words, blocks = query_vocabulary(scope, vocabulary, expansion_terms)
    in_pool = {row["id"]: row for row in pool}

    verified = [row for svid in verified_seeds(store, research_id, scope)
                if (row := in_pool.get(svid) or _seed_row(svid, versions)) is not None]
    scores = {"bm25": bm25_scores(pool, query_words), "blocks": block_scores(pool, blocks)}
    ranks = {name: mean_ranks(score, availability(pool, name)) for name, score in scores.items()}
    # Code seeds fill the graph's seed list up to GRAPH_SEEDS, taken from the top of BM25 plus blocks (fuse.py seedsB).
    verified_works = {row["work_id"] for row in verified}
    code = [in_pool[rid] for rid in fuse(ranks, ("bm25", "blocks")) if in_pool[rid]["work_id"] not in verified_works]
    graph_seeds = verified + code[: max(0, GRAPH_SEEDS - len(verified))]

    reasons: dict[str, str] = {}
    if verified:
        scores["tfidf"] = tfidf_scores(pool, verified)
    else:
        reasons["tfidf"] = "no_verified_seeds"  # SW7.5: with unverified seeds the signal is left out entirely
    if any(seed["references"] for seed in graph_seeds):
        scores["graph"] = graph_scores(pool, graph_seeds)
    else:
        reasons["graph"] = "no_seed_with_references"
    similarities = store.source_similarities(research_id, revision, embedding_model) if embedding_model else {}
    scored = {row["id"]: similarities[row["id"]] for row in pool if row["id"] in similarities}
    if not embedding_model:
        reasons["embedding"] = "embedding_off"
    elif not scored:
        reasons["embedding"] = "no_stored_similarity"
    else:
        scores["embedding"] = {row["id"]: scored.get(row["id"], 0.0) for row in pool}

    ranks = {name: mean_ranks(score, availability(pool, name) if name in CODE_SIGNALS
                              else {row["id"]: row["id"] in scored for row in pool})
             for name, score in scores.items()}
    fused_code = fuse(ranks, CODE_SIGNALS)
    fused = fuse(ranks, SIGNALS)
    order, rescued = inspection_order(fused, fused_code, ranks.get("embedding"))

    step = store.step(run["id"], "ranking", "code:ranking")
    rows = [{"source_version_id": rid, "signal": name, "rank": rank, "available": available}
            for name in SIGNALS if name in ranks for rid, (rank, available) in sorted(ranks[name].items())]
    rows += [{"source_version_id": rid, "signal": name, "rank": position + 1, "available": True}
             for name, listing in zip(ORDERS, (fused_code, fused, order))
             for position, rid in enumerate(listing)]
    DecisionStore(store).save_ranks(step["id"], research_id, rows)
    no_references = [row["id"] for row in pool if not row["references"]]
    return {
        "pool": len(pool),
        "signals": {name: {"ran": name in ranks, **({"reason": reasons[name]} if name in reasons else {}),
                           "available": sum(available for _, available in ranks.get(name, {}).values())}
                    for name in SIGNALS},
        "seeds": sorted(([{"source_version_id": seed["id"], "kind": "verified"} for seed in verified]
                         + [{"source_version_id": seed["id"], "kind": "code"} for seed in graph_seeds[len(verified):]]),
                        key=lambda seed: seed["source_version_id"]),
        # SW7.4 asks for this share with every ranking: more than half the measured pool had no list at all.
        "no_reference_list": len(no_references),
        "no_reference_list_share": round(len(no_references) / len(pool), 4) if pool else None,
        "no_abstract": sum(not row["abstract"] for row in pool),
        "embedding_model": embedding_model,
        "rescued": sorted(rescued),
    }
