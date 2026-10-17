"""Deterministic merge and cut; rank is a selection signal, not relevance.

`merge_and_cut` is the provider round-robin of plan version 1. `rank_and_cut` (plan version 2) orders the same
merged works by a local score against the claim before the cut: BM25, block coverage and joint co-mention of the
task terms, fused by reciprocal rank, with the round-robin position as the last key. No model, embedding or request
is used; the order is a priority signal for which works are read, never a relevance verdict.
"""
from __future__ import annotations

RANK_VERSION = "kill_rank.v1"
RANK_SIGNALS = ("bm25", "blocks", "joint")


def merge_and_cut(per_query: list[list[dict]], keep: int = 8) -> dict:
    if not isinstance(keep, int) or isinstance(keep, bool) or not 0 <= keep <= 8:
        raise ValueError("keep must be an integer from zero to eight")
    unique, seen, duplicates = [], set(), 0
    for rank in range(max((len(records) for records in per_query), default=0)):
        for records in per_query:
            if rank >= len(records):
                continue
            record = records[rank]
            key = ("work", record["work_id"]) if record.get("work_id") else ("source", record["source_version_id"])
            if key in seen:
                duplicates += 1
                continue
            seen.add(key)
            unique.append(dict(record, rank_key=len(unique) + 1))
    kept, cut = unique[:keep], unique[keep:]
    return {"kept": kept, "cut": cut, "found": sum(map(len, per_query)), "kept_count": len(kept),
            "rank_cut": len(cut), "duplicates": duplicates}


def rank_and_cut(per_query: list[list[dict]], documents: dict[str, dict], query: dict, keep: int = 8) -> dict:
    """The round-robin merge, reordered by a local score against the claim, then cut to `keep`.

    `documents` maps each source version to its stored `title` and `abstract`; `query` holds the claim's
    `text` (statement, conditions and elements) and the chosen `setting` and `task` terms. Every record keeps its
    round-robin position and its signal values, so the cut can be recomputed from the stored inputs.
    """
    from deixis.domain.vocabulary import words
    from deixis.workflow.ranking import block_scores, bm25_scores, fuse, joint_forms, joint_scores, mean_ranks

    if not isinstance(keep, int) or isinstance(keep, bool) or not 0 <= keep <= 8:
        raise ValueError("keep must be an integer from zero to eight")
    merged = merge_and_cut(per_query, keep=0)
    unique = merged["cut"]
    # A pool row is named by its zero-padded round-robin position, so `fuse`'s identifier tie-break is the
    # round-robin order and no result depends on source identifiers or provider order beyond that last key.
    rid = {r["source_version_id"]: f"{r['rank_key']:07d}" for r in unique}
    pool = [{"id": rid[r["source_version_id"]], "title": documents[r["source_version_id"]]["title"] or "",
             "abstract": documents[r["source_version_id"]]["abstract"]} for r in unique]
    setting, task = list(query["setting"]), list(query["task"])
    query_words = set(words(" ".join([query["text"], *setting, *task])))
    forms = joint_forms(task)
    scores = {"bm25": bm25_scores(pool, query_words),
              "blocks": block_scores(pool, {"setting": setting, "task": task}),
              "joint": joint_scores(pool, forms)}
    everywhere = {row["id"]: True for row in pool}
    order = fuse({signal: mean_ranks(values, everywhere) for signal, values in scores.items()},
                         RANK_SIGNALS)
    by_rid = {rid[r["source_version_id"]]: r for r in unique}
    ranked = []
    for position, row_id in enumerate(order, 1):
        record = by_rid[row_id]
        signals = {signal: list(scores[signal][row_id]) if isinstance(scores[signal][row_id], tuple)
                   else scores[signal][row_id] for signal in RANK_SIGNALS}
        ranked.append(dict(record, rank_key=position, round_robin_rank=record["rank_key"], rank_signals=signals))
    kept, cut = ranked[:keep], ranked[keep:]
    return {"kept": kept, "cut": cut, "found": merged["found"], "kept_count": len(kept), "rank_cut": len(cut),
            "duplicates": merged["duplicates"],
            "ranking": {"version": RANK_VERSION, "signals": list(RANK_SIGNALS),
                        "query_words": sorted(query_words), "setting": setting, "task": task, "joint_forms": forms}}
