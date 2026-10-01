"""Deterministic provider-order merge; rank is a selection signal, not relevance."""
from __future__ import annotations


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
