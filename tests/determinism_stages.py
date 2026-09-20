"""Code stages of the workflow, run in their own process for the replay check (SW14.7).

Each stage takes the same fixed SYNTHETIC rows and returns a value whose canonical digest must not depend on the
process hash seed or on the order the rows arrived in. Where a row order is part of the input's meaning — the
selection order an answer reads (D17) — the stage keeps that order and shuffles only what carries no order.
Later slices add their own stage to STAGES (implementation plan §2.9).
"""

from __future__ import annotations

import argparse
import random
import sys
import tempfile
from pathlib import Path
from typing import Any, Callable

from deixis.config import Settings
from deixis.documents.pdf import chunk_page
from deixis.domain.canonical import canonical_rows, sha256_hex
from deixis.providers.query_compiler import compile_queries
from deixis.storage import db
from deixis.workflow.decisions import DecisionStore
from deixis.workflow.flow import answer_source_order, fuse_rankings
from deixis.workflow.protocol import build_protocol
from deixis.workflow.store import Store

CONCEPTS = [
    {"label": "diffusion channel", "role": "core", "synonyms": ["diffusion channel", "molecular channel"]},
    {"label": "scheduling", "role": "method", "synonyms": ["scheduling", "release schedule"]},
    {"label": "packet size", "role": "outcome", "synonyms": ["packet size"]},
]
SCOPE = {"question": "SYNTHETIC how is molecule release scheduling optimized?", "steering": None,
         "language_hint": None, "source_scope": "academic", "seed_mode": "question_only",
         "search_workflow": "legacy", "model_connection": "fake", "requested_model": "fake-model",
         "reasoning_effort": None, "literature_model": None, "review_mode": "off"}
PAGE_TEXT = ("SYNTHETIC molecule release schedule minimizes error. " * 40).strip()


def stage_compile_queries(rows: list[dict[str, Any]]) -> Any:
    # The queries are a set of provider requests, not a ranking, so they are compared by their canonical row order.
    queries = compile_queries({"concepts": rows, "providers": ["openalex", "crossref"]}, ["openalex", "crossref"], 12)
    return canonical_rows(queries, "query_text")


def stage_chunk_page(rows: list[dict[str, Any]]) -> Any:
    return {row["id"]: chunk_page(row["text"]) for row in rows}


def stage_fuse_rankings(rows: list[dict[str, Any]]) -> Any:
    """Rows in pairs, each pair held at the same two ranks in the two rankings, so every pair is a score tie.

    A ranking itself is a signal and is not shuffled; what shuffles is which ranking is passed first and where a row
    sits among the rows it ties with. Neither may reach the output (SW14.6).
    """
    arrival = {row["id"]: position for position, row in enumerate(rows)}
    ordered = sorted(rows, key=lambda row: row["id"])
    pairs = [ordered[i:i + 2] for i in range(0, len(ordered), 2)]
    first = [row for pair in pairs for row in sorted(pair, key=lambda row: arrival[row["id"]])]
    second = [row for pair in pairs for row in sorted(pair, key=lambda row: -arrival[row["id"]])]
    if arrival[ordered[0]["id"]] % 2:
        first, second = second, first
    return [row["id"] for row in fuse_rankings(first, second)]


def stage_answer_source_order(rows: list[dict[str, Any]]) -> Any:
    # Selection order is a measured signal, so `included` keeps its stable order; the lookups shuffle with the rows.
    included = [row["id"] for row in sorted(rows, key=lambda row: row["id"])]
    facts = {row["id"]: (False, 1) for row in rows}
    texts = {row["id"]: row["text"] for row in rows}
    return answer_source_order(included, facts, texts, ["molecule", "schedule"])


def stage_work_outcome(rows: list[dict[str, Any]]) -> Any:
    """Decisions written in a shuffled order must still give each work the same outcome (SW9.4).

    The rows are decisions, not a ranking, so the order they arrive in carries nothing. Each work here has at most one
    human decision, so no outcome depends on which of two same-millisecond writes landed last.
    """
    with tempfile.TemporaryDirectory() as directory:
        conn = db.connect(Path(directory) / "library.sqlite")
        db.migrate(conn)
        store = Store(conn)
        rid = store.create_research("SYNTHETIC question?", "academic", "quick", ["openalex"], "fake", "fake-model",
                                    None, search_workflow="sw")
        ts = "2026-09-20T00:00:00.000+00:00"
        with db.transaction(conn):
            for work_id in sorted({row["work_id"] for row in rows}):
                conn.execute("INSERT INTO works (id, created_at) VALUES (?, ?)", (work_id, ts))
            for source_version_id in sorted({row["id"] for row in rows}):
                conn.execute(
                    "INSERT INTO source_versions (id, work_id, title, origin, created_at)"
                    " VALUES (?, ?, 'SYNTHETIC record', 'provider', ?)",
                    (source_version_id, next(r["work_id"] for r in rows if r["id"] == source_version_id), ts),
                )
                conn.execute(
                    "INSERT INTO corpus_memberships (research_id, source_version_id, added_by, created_at)"
                    " VALUES (?, ?, 'search', ?)", (rid, source_version_id, ts),
                )
        decisions = DecisionStore(store)
        for row in rows:
            decisions.record(rid, row["id"], row["reason_code"])
        outcomes = [{"work_id": work_id, **decisions.work_outcome(rid, work_id)}
                    for work_id in sorted({row["work_id"] for row in rows})]
        conn.close()
    return canonical_rows(outcomes, "work_id")


def stage_build_protocol(rows: list[dict[str, Any]]) -> Any:
    scope = SCOPE | {"providers": [row["id"] for row in rows]}
    return build_protocol(scope, {"max_candidates": 20}, {"concepts": CONCEPTS},
                          [{"provider_id": "openalex", "query_text": "diffusion channel"}],
                          "SYNTHETIC_package_hash", Settings(data_dir=None))


STAGES: dict[str, Callable[[list], Any]] = {
    "compile_queries": stage_compile_queries,
    "chunk_page": stage_chunk_page,
    "fuse_rankings": stage_fuse_rankings,
    "answer_source_order": stage_answer_source_order,
    "build_protocol": stage_build_protocol,
    "work_outcome": stage_work_outcome,
}

ROWS: dict[str, list[dict[str, Any]]] = {
    "compile_queries": CONCEPTS,
    "chunk_page": [{"id": f"pg{i}", "text": PAGE_TEXT} for i in range(4)],
    "fuse_rankings": [{"id": f"psg_{i}", "text": "SYNTHETIC passage"} for i in range(6)],
    "answer_source_order": [{"id": f"svr_{i}", "text": "SYNTHETIC molecule release schedule"} for i in range(6)],
    "build_protocol": [{"id": p} for p in ("openalex", "crossref", "arxiv", "pubmed")],
    # Four works: one still a candidate on the abstract stage, one whose two versions disagree on the full text, one
    # the user decided, and one whose two versions reached the same outcome, so the version named for the work must
    # not be the one decided first. SYNTHETIC decisions; they show merge behavior, not screening quality.
    "work_outcome": [
        # First in the list: both shuffles the test runs reverse this pair.
        {"id": "srv_four_a", "work_id": "wrk_four", "reason_code": "blocks_in_title"},
        {"id": "srv_four_b", "work_id": "wrk_four", "reason_code": "runs_agree_candidate"},
        {"id": "srv_one_a", "work_id": "wrk_one", "reason_code": "both_blocks_missing"},
        {"id": "srv_one_b", "work_id": "wrk_one", "reason_code": "blocks_in_title"},
        {"id": "srv_two_a", "work_id": "wrk_two", "reason_code": "all_parts_verified"},
        {"id": "srv_two_b", "work_id": "wrk_two", "reason_code": "criterion_absent"},
        {"id": "srv_three_a", "work_id": "wrk_three", "reason_code": "criterion_absent"},
        {"id": "srv_three_b", "work_id": "wrk_three", "reason_code": "human_include"},
    ],
}


def run(stage: str, shuffle: int | None) -> str:
    rows = [dict(row) for row in ROWS[stage]]
    if shuffle is not None:
        random.Random(shuffle).shuffle(rows)
    return sha256_hex(STAGES[stage](rows))


def main() -> None:
    parser = argparse.ArgumentParser(description="Print the canonical digest of one code stage.")
    parser.add_argument("stage", choices=sorted(STAGES))
    parser.add_argument("--shuffle", type=int, default=None, help="seed the input rows are shuffled with")
    args = parser.parse_args()
    print(run(args.stage, args.shuffle))


if __name__ == "__main__":
    sys.exit(main())
