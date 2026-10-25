"""Deterministic merge and cut; rank is a selection signal, not relevance.

`merge_and_cut` is the provider round-robin of plan version 1. `rank_and_cut` (plan version 2) orders the same
merged works by a local score against the claim before the cut: BM25, block coverage and joint co-mention of the
task terms, fused by reciprocal rank, with the round-robin position as the last key. No model, embedding or request
is used; the order is a priority signal for which works are read, never a relevance verdict.

`rank_concepts_and_cut` (plan version 3, `kill_rank.v2`) keeps BM25 as it is but counts concepts, not name forms, in
the block and co-mention signals: a long name and its abbreviation are one concept when the term list, the claim or
the record itself defines the abbreviation unambiguously, and blocks and co-mention read text through one
normalisation (hyphens as spaces, a plural -s dropped, whole words; abbreviations case-sensitive). A backup joins a
chosen term's concept only through such an abbreviation link; otherwise it shows the block is present and is
searched and read by BM25, but never counts as a concept of its own.
Each ranked record carries the hashes of the text it was scored on, its raw signals, its signal ranks and its fused
rank (`rank_key`), so a later run can explain its position.
"""
from __future__ import annotations

import hashlib
import math
import re
from collections import Counter

from deixis.domain.vocabulary import words

RANK_VERSION = "kill_rank.v1"
RANK_SIGNALS = ("bm25", "blocks", "joint")
CONCEPT_RANK_VERSION = "kill_rank.v2"


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


# ---- plan version 3: concept-level block and co-mention signals (kill_rank.v2) ------------------------------

_HYPHENS = re.compile(r"[-\u2010\u2011\u2012\u2013]")
_TOKEN = re.compile(r"[^\W_]+(?:['’][^\W_]+)*", re.UNICODE)
# A name spelled out and abbreviated in parentheses, "Platelet-Rich Plasma (PRP)": the abbreviation is 2–6 letters or
# digits starting with a capital, and its letters must be the initials of the words right before the parenthesis.
_DEFINED = re.compile(r"((?:[\w'’-]+\s+){0,5}[\w'’-]+)\s*\(([A-Z][A-Za-z0-9]{1,5})\)")


def _stem(word: str) -> str:
    """A plural -s dropped, so "networks" and "network" are one word; "-ss", "-us" and "-is" endings are kept."""
    if len(word) > 3 and word.endswith("ies"):
        return word[:-3] + "y"
    if len(word) > 3 and word.endswith("s") and not word.endswith(("ss", "us", "is")):
        return word[:-1]
    return word


def _core(token: str) -> str:
    """An abbreviation without its plural -s: "UWSNs" is UWSN."""
    return token[:-1] if len(token) > 2 and token.endswith("s") and token[:-1].isupper() else token


def concept_text(text: str) -> str:
    """The one normalisation names are matched with: lower case, hyphens as spaces, a plural -s dropped, words padded
    by spaces so a name matches whole words only."""
    return " " + " ".join(_stem(w) for w in words(_HYPHENS.sub(" ", text or ""))) + " "


def _form(term: str) -> str:
    return concept_text(term).strip()


def _initials(term: str) -> str:
    return "".join(w[0] for w in words(_HYPHENS.sub(" ", term)))


def _abbreviation(term: str) -> str | None:
    """A single capitalised token of 2–6 characters ("DBR", "UWSNs"), as its case-sensitive core; else None."""
    tokens = _TOKEN.findall(term.strip())
    if len(tokens) != 1 or not 2 <= len(tokens[0]) <= 6:
        return None
    core = _core(tokens[0])
    return core if core.isupper() and sum(c.isalpha() for c in core) >= 2 else None


def _definitions(text: str) -> list[tuple[str, str]]:
    """(spelled form, abbreviation) pairs the text defines, only where the abbreviation's letters are the initials
    of the words right before its parenthesis ("depth-based routing (DBR)", not "routing (VBF)"). The abbreviation
    keeps its case."""
    pairs = []
    for match in _DEFINED.finditer(text or ""):
        short = _core(match.group(2))
        tail = words(_HYPHENS.sub(" ", match.group(1)))[-len(short):]
        if len(tail) == len(short) and "".join(w[0] for w in tail) == short.lower():
            pairs.append((" ".join(_stem(w) for w in tail), short))
    return pairs


def concepts(blocks: dict[str, list[str]], claim_text: str = "", backups: dict[str, list[str]] | None = None) -> list[dict]:
    """The names of each block, grouped by evidence that two names are one thing, never by similar wording.

    Two names join only when one is an abbreviation of the other: its letters are the initials of exactly one
    multi-word name of the block, or the claim defines it for that name. A group holding a chosen term is a
    counted concept; an abbreviation whose letters fit several long names joins none and, alone, is not one. Backups that join no chosen term are kept together as the block's uncounted other names: they
    show that the block is present but never count as a concept of their own, so one thing under two names never
    reads as two. A claim definition that contradicts the term list is ignored. Long names (`forms`) are matched on
    `concept_text`'s words, abbreviations (`short`) case-sensitively on the same words with their case kept (`_held`).
    """
    backups = backups or {}
    found: list[dict] = []
    for block in blocks:
        nodes: list[dict] = []
        for chosen, terms in ((True, blocks[block]), (False, backups.get(block, []))):
            for term in terms:
                short = _abbreviation(term)
                key = short if short else _form(term)
                if not key or any(key in (*n["forms"], *n["short"]) for n in nodes):
                    continue
                nodes.append({"chosen": chosen, "term": term, "forms": [] if short else [key],
                              "short": [short] if short else []})
        parent = list(range(len(nodes)))

        def root(i: int) -> int:
            while parent[i] != i:
                i = parent[i]
            return i

        def longs(i: int) -> set[str]:
            return {f for j, n in enumerate(nodes) if root(j) == root(i) for f in n["forms"] if " " in f}

        initials: dict[str, list[int]] = {}
        for i, node in enumerate(nodes):
            if node["forms"] and " " in node["forms"][0]:
                initials.setdefault(_initials(node["term"]), []).append(i)
        for i, node in enumerate(nodes):
            # A lower-case single word ("uwsn") is an abbreviation only when its letters name exactly one long name.
            letters = node["short"][0].lower() if node["short"] else (
                node["forms"][0] if 2 <= len(node["forms"][0]) <= 6 and " " not in node["forms"][0] else None)
            owners = initials.get(letters, []) if letters else []
            if len(owners) > 1 and (node["short"] or node["forms"] == [letters]):
                # Its letters fit several long names: it names none of them until something resolves it.
                if not node["short"]:
                    node["forms"], node["short"] = [], [letters.upper()]
                node["ambiguous"] = True
            if len(owners) == 1 and root(owners[0]) != root(i):
                if not node["short"]:
                    node["forms"], node["short"] = [], [letters.upper()]
                parent[root(i)] = root(owners[0])
        for spelled, short in _definitions(claim_text):
            by_short = next((i for i, n in enumerate(nodes) if short in n["short"]), None)
            by_long = next((i for i, n in enumerate(nodes) if spelled in n["forms"]), None)
            if by_short is not None and longs(by_short) and spelled not in longs(by_short):
                continue  # the claim spells this abbreviation differently from the term list
            if by_short is not None:
                nodes[by_short]["ambiguous"] = False  # the claim says which long name it is
            if by_short is not None and by_long is not None:
                parent[root(by_short)] = root(by_long)
            elif by_short is not None:
                nodes[by_short]["forms"].append(spelled)
            elif by_long is not None:
                nodes[by_long]["short"].append(short)
        groups: dict[int, list[int]] = {}
        for i in range(len(nodes)):
            groups.setdefault(root(i), []).append(i)
        counted, other = [], {"forms": [], "short": []}
        for members in sorted(groups.values()):
            names = {"forms": [f for i in members for f in nodes[i]["forms"]],
                     "short": [a for i in members for a in nodes[i]["short"]]}
            if any(nodes[i]["chosen"] and not nodes[i].get("ambiguous") for i in members):
                counted.append(names)
            else:
                other["forms"] += names["forms"]
                other["short"] += names["short"]
        found += [{"id": f"{block}:{n}", "block": block, "counted": True, **names} for n, names in enumerate(counted, 1)]
        if other["forms"] or other["short"]:
            found.append({"id": f"{block}:other", "block": block, "counted": False, **other})
    return found


def _record_names(concept_list: list[dict], text: str) -> tuple[dict[str, list[str]], list[str]]:
    """What the record itself defines: an abbreviation it gives a concept's long name (also one the term list left
    unresolved), used for that record only, and the abbreviations it spells as something else than the term list does, which it then never matches
    ("Mass spectrometry (MS)" in a record blocks MS as multiple sclerosis)."""
    owner_of = {form: c["id"] for c in concept_list for form in c["forms"]}
    short_of = {short: c for c in concept_list for short in c["short"]}
    blocked: set[str] = set()
    found: dict[str, set[str]] = {}
    for spelled, short in _definitions(text):
        if short in short_of and not short_of[short]["counted"]:
            # An unresolved abbreviation the record spells as one counted concept's long name is that concept here;
            # spelled as anything else (a backup's name included) it is blocked in this record.
            if spelled in owner_of and next(c for c in concept_list if c["id"] == owner_of[spelled])["counted"]:
                found.setdefault(short, set()).add(owner_of[spelled])
            else:
                blocked.add(short)
        elif short in short_of:
            if spelled not in short_of[short]["forms"]:
                blocked.add(short)
        elif spelled in owner_of:
            found.setdefault(short, set()).add(owner_of[spelled])
    extra: dict[str, list[str]] = {}
    for short, owners in sorted(found.items()):
        if len(owners) == 1:
            extra.setdefault(next(iter(owners)), []).append(short)
    return extra, sorted(blocked)


def _held(concept_list: list[dict], extra: dict[str, list[str]], blocked: list[str], text: str) -> set[str]:
    """The names the text holds.

    Counted concepts are read leftmost-longest within their own block: every span of a counted long name or
    abbreviation is found, the longest at each position wins and a span overlapping one already taken in the same
    block is dropped, so "non-small cell lung cancer" is never also "small cell lung cancer". Blocks never compete:
    a setting name inside a task name still shows the setting. Uncounted names (unlinked backups, unresolved
    abbreviations) only show their block is present; they take no span and never hide a counted concept.
    """
    tokens = _TOKEN.findall(_HYPHENS.sub(" ", text or ""))
    lower = [_stem(t.lower()) for t in tokens]
    cased = [_core(t) for t in tokens]

    def spans(c: dict) -> list[tuple[int, int]]:
        names = [(f.split(), lower) for f in c["forms"]]
        names += [([a], cased) for a in [*c["short"], *extra.get(c["id"], [])] if a not in blocked]
        return [(i, -len(name)) for name, seq in names for i in range(len(seq) - len(name) + 1)
                if seq[i:i + len(name)] == name]

    held = {c["id"] for c in concept_list if not c["counted"] and spans(c)}
    for block in dict.fromkeys(c["block"] for c in concept_list):
        found = sorted((start, negative, c["id"]) for c in concept_list if c["block"] == block and c["counted"]
                       for start, negative in spans(c))
        taken_to = 0
        for start, negative, cid in found:
            if start >= taken_to:
                held.add(cid)
                taken_to = start - negative
    return held


def concept_scores(pool: list[dict], concept_list: list[dict]) -> dict[str, dict]:
    """Per record: blocks named in the title (any name, counted or not) and distinct counted concepts in title plus
    abstract; and co-mention of the counted task concepts: how many the title names (0 below two) and their summed
    rarity log(N / records holding the concept) when the record names two or more anywhere."""
    count = len(pool) or 1
    counted = {c["id"] for c in concept_list if c["counted"]}
    task = [c["id"] for c in concept_list if c["block"] == "task" and c["counted"]]
    block_of = {c["id"]: c["block"] for c in concept_list}
    rows: dict[str, dict] = {}
    for row in pool:
        whole_text = f"{row['title']} {row['abstract'] or ''}"
        extra, blocked = _record_names(concept_list, whole_text)
        rows[row["id"]] = {"title": _held(concept_list, extra, blocked, row["title"]),
                           "whole": _held(concept_list, extra, blocked, whole_text), "extra": extra, "blocked": blocked}
    frequency = Counter(cid for found in rows.values() for cid in found["whole"] if cid in counted)
    scores = {}
    for rid, found in rows.items():
        named = [cid for cid in task if cid in found["title"]]
        held = sorted(cid for cid in task if cid in found["whole"])
        scores[rid] = {"blocks": (len({block_of[cid] for cid in found["title"]}), len(found["whole"] & counted)),
                       "joint": (len(named) if len(named) >= 2 else 0,
                                 sum(math.log(count / frequency[cid]) for cid in held) if len(held) >= 2 else 0.0),
                       "concepts": {"title": sorted(found["title"]), "text": sorted(found["whole"]),
                                    "record_abbreviations": {k: v for k, v in sorted(found["extra"].items())},
                                    "blocked_abbreviations": found["blocked"]}}
    return scores


def _sha(text: str | None) -> str | None:
    return hashlib.sha256(text.encode("utf-8")).hexdigest() if text else None


def rank_concepts_and_cut(per_query: list[list[dict]], documents: dict[str, dict], query: dict, keep: int = 8) -> dict:
    """Plan version 3's cut: the round-robin merge, reordered by BM25 and the concept-level block and co-mention
    signals, then cut to `keep`. `query` holds the claim `text` and the `setting`, `task`, `setting_backup` and
    `task_backup` terms; backups are read as further names of their block's concepts."""
    from deixis.workflow.ranking import bm25_scores, fuse, mean_ranks

    if not isinstance(keep, int) or isinstance(keep, bool) or not 0 <= keep <= 8:
        raise ValueError("keep must be an integer from zero to eight")
    merged = merge_and_cut(per_query, keep=0)
    unique = merged["cut"]
    rid = {r["source_version_id"]: f"{r['rank_key']:07d}" for r in unique}
    pool = [{"id": rid[r["source_version_id"]], "title": documents[r["source_version_id"]]["title"] or "",
             "abstract": documents[r["source_version_id"]]["abstract"]} for r in unique]
    chosen = {name: list(query[name]) for name in ("setting", "task")}
    backups = {name: list(query.get(f"{name}_backup", [])) for name in ("setting", "task")}
    concept_list = concepts(chosen, query["text"], backups)
    query_words = set(words(" ".join([query["text"], *chosen["setting"], *chosen["task"], *backups["setting"],
                                      *backups["task"]])))
    detail = concept_scores(pool, concept_list)
    scores = {"bm25": bm25_scores(pool, query_words),
              "blocks": {r: d["blocks"] for r, d in detail.items()},
              "joint": {r: d["joint"] for r, d in detail.items()}}
    everywhere = {row["id"]: True for row in pool}
    ranks = {signal: mean_ranks(values, everywhere) for signal, values in scores.items()}
    order = fuse(ranks, RANK_SIGNALS)
    by_rid = {rid[r["source_version_id"]]: r for r in unique}
    text_of = {row["id"]: row for row in pool}
    ranked = []
    for position, row_id in enumerate(order, 1):
        record, row = by_rid[row_id], text_of[row_id]
        ranked.append(dict(record, rank_key=position, round_robin_rank=record["rank_key"],
                           rank_signals={s: list(v) if isinstance(v := scores[s][row_id], tuple) else v
                                         for s in RANK_SIGNALS},
                           signal_ranks={s: ranks[s][row_id][0] for s in RANK_SIGNALS},
                           rank_inputs={"title_sha256": _sha(row["title"]), "abstract_sha256": _sha(row["abstract"]),
                                        "abstract_chars": len(row["abstract"] or "")},
                           concepts=detail[row_id]["concepts"]))
    kept, cut = ranked[:keep], ranked[keep:]
    return {"kept": kept, "cut": cut, "found": merged["found"], "kept_count": len(kept), "rank_cut": len(cut),
            "duplicates": merged["duplicates"],
            "ranking": {"version": CONCEPT_RANK_VERSION, "signals": list(RANK_SIGNALS),
                        "query_words": sorted(query_words), **{k: list(query.get(k, [])) for k in
                        ("setting", "task", "setting_backup", "task_backup")}, "concepts": concept_list}}
