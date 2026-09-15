"""Compare lexical and hybrid (lexical + Gemini embedding) answer-passage selection on a copy of a stored research (D27).

Usage: PYTHONPATH=backend uv run --no-sync python scripts/p4_eval/semantic_retrieval.py --db path/library.sqlite
       --research res_… --translated "same question in another language" [--out dir]

The research database is copied first; embeddings are written only to the copy. For the original question and its
translation, the selected passages are compared. Agreement between the two languages shows robustness to the
question's language, not relevance: nobody judged whether the selected passages answer the question.
"""

from __future__ import annotations

import argparse
import asyncio
import json
import sqlite3
import tempfile
import time
from pathlib import Path
from types import SimpleNamespace

import httpx

from deixis.config import load_settings
from deixis.storage import db
from deixis.workflow.flow import ResearchFlow
from deixis.workflow.store import Store


def overlap(a: list[dict], b: list[dict]) -> float:
    ids_a, ids_b = {p["id"] for p in a}, {p["id"] for p in b}
    return round(len(ids_a & ids_b) / max(1, len(ids_a | ids_b)), 3)


async def main(args: argparse.Namespace) -> None:
    load_settings()  # GEMINI_API_KEY from .env
    work = Path(tempfile.mkdtemp(prefix="deixis-semantic-")) / "library.sqlite"
    with sqlite3.connect(f"file:{args.db}?mode=ro", uri=True) as source, sqlite3.connect(work) as target:
        source.backup(target)
    conn = db.connect(work)
    db.migrate(conn)
    store = Store(conn)
    scope, included = store.scope(args.research), store.included_sources(args.research)
    run = store.create_run(args.research, "answer", {}, None)
    report: dict = {"research": args.research, "included_sources": len(included), "limit": args.limit, "questions": {}}
    async with httpx.AsyncClient() as client:
        flow = object.__new__(ResearchFlow)
        flow.store, flow.deps = store, SimpleNamespace(http=client)
        selected = {}
        for label, question in (("original", scope["question"]), ("translated", args.translated)):
            asked = dict(scope, question=question)
            lexical = flow._retrieve(args.research, asked, included, args.limit)
            started = time.monotonic()
            semantic = await flow._semantic_ranking(run, asked, included)
            if semantic is None:
                raise SystemExit("semantic ranking unavailable: set GEMINI_API_KEY or see the failed step")
            hybrid = flow._retrieve(args.research, asked, included, args.limit, semantic)
            selected[label] = {"lexical": lexical, "hybrid": hybrid}
            report["questions"][label] = {
                "question": question, "semantic_seconds": round(time.monotonic() - started, 2),
                "ranked_passages": len(semantic),
                "lexical_vs_hybrid_overlap": overlap(lexical, hybrid),
                "lexical": [(p["id"], p["source_version_id"], p["kind"], p["physical_page"]) for p in lexical],
                "hybrid": [(p["id"], p["source_version_id"], p["kind"], p["physical_page"]) for p in hybrid],
            }
    report["cross_language_overlap"] = {mode: overlap(selected["original"][mode], selected["translated"][mode]) for mode in ("lexical", "hybrid")}
    print(json.dumps({k: v for k, v in report.items() if k != "questions"}, indent=1))
    for label, q in report["questions"].items():
        print(label, "lexical_vs_hybrid_overlap", q["lexical_vs_hybrid_overlap"], "semantic_seconds", q["semantic_seconds"],
              "ranked_passages", q["ranked_passages"])
    if args.out:
        Path(args.out).mkdir(parents=True, exist_ok=True)
        (Path(args.out) / "semantic-retrieval.json").write_text(json.dumps(report, indent=1, ensure_ascii=False))


if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("--db", required=True)
    parser.add_argument("--research", required=True)
    parser.add_argument("--translated", required=True)
    parser.add_argument("--limit", type=int, default=48)
    parser.add_argument("--out")
    asyncio.run(main(parser.parse_args()))
