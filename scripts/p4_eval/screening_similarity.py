"""Would question–source embedding similarity order screened sources better than search position?

Usage: PYTHONPATH=backend uv run --no-sync python scripts/p4_eval/screening_similarity.py [--db path] --out dir

Read-only on the database. For every research with model screening proposals, the question of the scope revision the
proposal was made under and each proposed source's title plus stored abstract are embedded with the product's Gemini
model; vectors are cached in --out and never written to the database. Two orderings are compared within each research:
search position (candidates.rank, lower first) and similarity to the question (higher first).

A. Agreement with the screening verdict: AUC separating proposed include from proposed exclude.
B. Among proposed includes of researches with an answer: AUC separating sources cited in the latest answer from the rest.
Neither is a human relevance judgment: the verdict is the model's, and citation depends on lexical passage retrieval
and the answer's passage limit. AUCs pool within-research pairs; intervals resample researches.

Pre-registered before the first run: A similarity >= 0.80, search position 0.55-0.65. Worth adding as the tie-breaker
after the verdict if similarity beats position by >= 0.10 on A and is not lower on B.
"""

from __future__ import annotations

import argparse
import asyncio
import hashlib
import json
import random
import sqlite3
from pathlib import Path

import httpx

from deixis.config import load_settings
from deixis.documents import embeddings

PROPOSALS = (
    "SELECT s.research_id, s.source_version_id, s.proposal, s.proposal_basis, c.rank, sv.title, sr.question,"
    " (SELECT p.text FROM passages p WHERE p.source_version_id = s.source_version_id AND p.kind = 'abstract'"
    "  ORDER BY p.created_at DESC LIMIT 1) AS abstract"
    " FROM selections s"
    " JOIN candidates c ON c.research_id = s.research_id AND c.source_version_id = s.source_version_id"
    " JOIN source_versions sv ON sv.id = s.source_version_id"
    " JOIN run_steps st ON st.id = s.proposal_step_id JOIN runs r ON r.id = st.run_id"
    " JOIN scope_revisions sr ON sr.research_id = s.research_id AND sr.revision = r.scope_revision"
    " WHERE s.proposal IS NOT NULL AND c.rank IS NOT NULL"
)
CITED = (
    "SELECT a.research_id, el.source_version_id FROM answers a"
    " JOIN claims cl ON cl.answer_id = a.id JOIN evidence_links el ON el.claim_id = cl.id"
    " WHERE a.id = (SELECT a2.id FROM answers a2 WHERE a2.research_id = a.research_id"
    "  AND EXISTS (SELECT 1 FROM claims c2 WHERE c2.answer_id = a2.id) ORDER BY a2.created_at DESC LIMIT 1)"
)


def pairs(pos: list[float], neg: list[float]) -> tuple[float, int]:
    """Pairs where the positive scores higher (ties count half), and the pair count."""
    wins = sum(1.0 if p > n else 0.5 if p == n else 0.0 for p in pos for n in neg)
    return wins, len(pos) * len(neg)


def pooled(rows: list[tuple[float, float, int]]) -> tuple[float, float]:
    total = sum(r[2] for r in rows)
    return sum(r[0] for r in rows) / total, sum(r[1] for r in rows) / total


def interval(rows: list[tuple[float, float, int]], seed: int = 7, draws: int = 2000) -> dict[str, list[float]]:
    rng = random.Random(seed)
    sims, ranks, diffs = [], [], []
    for _ in range(draws):
        sample = [rng.choice(rows) for _ in rows]
        if sum(r[2] for r in sample) == 0:
            continue
        s, r = pooled(sample)
        sims.append(s), ranks.append(r), diffs.append(s - r)
    q = lambda xs: [round(sorted(xs)[int(0.025 * len(xs))], 3), round(sorted(xs)[int(0.975 * len(xs)) - 1], 3)]
    return {"similarity": q(sims), "search_position": q(ranks), "difference": q(diffs)}


async def embed_cached(cache: sqlite3.Connection, client: httpx.AsyncClient, texts: list[str], task: str) -> list:
    keys = [hashlib.sha256(f"{embeddings.MODEL}|{task}|{t}".encode()).hexdigest() for t in texts]
    have = dict(cache.execute(f"SELECT key, vector FROM vectors WHERE key IN ({','.join('?' * len(keys))})", keys))
    missing = list(dict.fromkeys((k, t) for k, t in zip(keys, texts) if k not in have))
    if missing:
        fresh = await embeddings.Embedder("gemini", embeddings.MODEL).embed(client, [t for _, t in missing], task)
        cache.executemany("INSERT INTO vectors VALUES (?, ?)", [(k, v.tobytes()) for (k, _), v in zip(missing, fresh)])
        cache.commit()
        have |= {k: v.tobytes() for (k, _), v in zip(missing, fresh)}
    return [embeddings.from_blob(have[k]) for k in keys]


async def main(args: argparse.Namespace) -> None:
    load_settings()
    out = Path(args.out)
    out.mkdir(parents=True, exist_ok=True)
    with sqlite3.connect(f"file:{args.db}?mode=ro", uri=True) as conn:
        conn.row_factory = sqlite3.Row
        rows = [dict(r) for r in conn.execute(PROPOSALS)]
        cited: dict[str, set[str]] = {}
        for rid, svid in conn.execute(CITED):
            cited.setdefault(rid, set()).add(svid)
    cache = sqlite3.connect(out / "vectors.sqlite")
    cache.execute("CREATE TABLE IF NOT EXISTS vectors (key TEXT PRIMARY KEY, vector BLOB)")
    docs = [f"{r['title']}\n\n{r['abstract']}" if r["abstract"] else r["title"] for r in rows]
    questions = sorted({r["question"] for r in rows})
    async with httpx.AsyncClient() as client:
        doc_vectors = await embed_cached(cache, client, docs, "RETRIEVAL_DOCUMENT")
        query_vectors = dict(zip(questions, await embed_cached(cache, client, questions, "RETRIEVAL_QUERY")))
    for r, v in zip(rows, doc_vectors):
        r["similarity"] = embeddings.similarity(query_vectors[r["question"]], v)

    by_research: dict[str, list[dict]] = {}
    for r in rows:
        by_research.setdefault(r["research_id"], []).append(r)
    report, a_rows, b_rows, a_abs_rows = [], [], [], []
    for rid, items in sorted(by_research.items()):
        score = {"sim": lambda r: r["similarity"], "pos": lambda r: -r["rank"]}
        inc = [r for r in items if r["proposal"] == "include"]
        exc = [r for r in items if r["proposal"] == "exclude"]
        entry = {"research": rid, "question": items[0]["question"][:80], "include": len(inc), "exclude": len(exc),
                 "uncertain": sum(r["proposal"] == "uncertain" for r in items),
                 "uncertain_with_abstract": sum(r["proposal"] == "uncertain" and bool(r["abstract"]) for r in items)}
        (ws, n), (wp, _) = (pairs([score[k](r) for r in inc], [score[k](r) for r in exc]) for k in ("sim", "pos"))
        a_rows.append((ws, wp, n))
        entry["A_similarity"], entry["A_position"] = (round(ws / n, 3), round(wp / n, 3)) if n else (None, None)
        inc_abs, exc_abs = [r for r in inc if r["abstract"]], [r for r in exc if r["abstract"]]
        (ws2, n2), (wp2, _) = (pairs([score[k](r) for r in inc_abs], [score[k](r) for r in exc_abs]) for k in ("sim", "pos"))
        a_abs_rows.append((ws2, wp2, n2))
        if rid in cited:
            yes = [r for r in inc if r["source_version_id"] in cited[rid]]
            no = [r for r in inc if r["source_version_id"] not in cited[rid]]
            (ws, n), (wp, _) = (pairs([score[k](r) for r in yes], [score[k](r) for r in no]) for k in ("sim", "pos"))
            b_rows.append((ws, wp, n))
            entry["cited"], entry["B_similarity"], entry["B_position"] = len(yes), *((round(ws / n, 3), round(wp / n, 3)) if n else (None, None))
        report.append(entry)

    summary = {"model": embeddings.MODEL, "researches": len(by_research), "proposals": len(rows),
               "with_abstract": sum(bool(r["abstract"]) for r in rows),
               "uncertain": sum(r["proposal"] == "uncertain" for r in rows),
               "uncertain_with_abstract": sum(r["proposal"] == "uncertain" and bool(r["abstract"]) for r in rows)}
    for name, data in (("A_include_vs_exclude", a_rows), ("A_with_abstract_only", a_abs_rows), ("B_cited_among_includes", b_rows)):
        used = [d for d in data if d[2]]
        if not used:
            continue
        sim, pos = pooled(used)
        summary[name] = {"researches": len(used), "pairs": sum(d[2] for d in used), "similarity": round(sim, 3),
                         "search_position": round(pos, 3), "similarity_wins_in": sum(d[0] > d[1] for d in used),
                         "interval_95": interval(used)}
    print(json.dumps(summary, indent=1, ensure_ascii=False))
    for e in report:
        print(json.dumps(e, ensure_ascii=False))
    (out / "screening-similarity.json").write_text(json.dumps({"summary": summary, "researches": report}, indent=1, ensure_ascii=False))


if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("--db", default=str(Path.home() / "Library" / "Application Support" / "DEIXIS" / "library.sqlite"))
    parser.add_argument("--out", required=True)
    asyncio.run(main(parser.parse_args()))
