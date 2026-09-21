"""Code stages of the workflow, run in their own process for the replay check (SW14.7).

Each stage takes the same fixed SYNTHETIC rows and returns a value whose canonical digest must not depend on the
process hash seed or on the order the rows arrived in. Where a row order is part of the input's meaning — the
selection order an answer reads (D17) — the stage keeps that order and shuffles only what carries no order.
Later slices add their own stage to STAGES (implementation plan §2.9).
"""

from __future__ import annotations

import argparse
import asyncio
import random
import sys
import tempfile
from pathlib import Path
from typing import Any, Callable

from deixis.config import Settings
from deixis.documents.pdf import chunk_page
from deixis.domain.canonical import canonical_rows, sha256_hex
from deixis.domain.expansion import candidates as phrase_candidates
from deixis.domain.vocabulary import extract
from deixis.providers.common import ProviderRecord
from deixis.providers.query_compiler import compile_block_queries, compile_queries
from deixis.storage import db
from deixis.workflow.decisions import DecisionStore
from deixis.workflow.expansion import expand
from deixis.workflow.flow import answer_source_order, fuse_rankings
from deixis.workflow.protocol import build_protocol
from deixis.workflow.store import Store
from deixis.workflow.vocabulary import apply_labels, build_vocabulary

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


LINK_AUTHORS = ["Aydin, Mert", "Zhao, Li"]
LINK_TITLES = {
    "one": "SYNTHETIC release scheduling for diffusion channels",
    "two": "SYNTHETIC receiver architectures in molecular communication",
    "three": "SYNTHETIC energy budgets of nanoscale transmitters",
    "three_retitled": "SYNTHETIC energy budget of a nanoscale transmitter",  # title similarity 0.81 to "three"
    "four": "SYNTHETIC coding gain under drift and turbulence",
    "five": "SYNTHETIC bit error rate of optical wireless links",
    "six": "SYNTHETIC multi hop relaying in vascular networks",
}
LINK_ABSTRACTS = {
    "one": "We schedule SYNTHETIC molecule releases and report the packet size that minimises the error rate.",
    "two": "We compare SYNTHETIC receiver architectures for molecular links under a fixed sampling budget.",
    "three": "We derive the SYNTHETIC energy a nanoscale transmitter spends per emitted molecule.",
    "three_other": "We measure SYNTHETIC turbulence in a vascular channel and fit a drift model to it.",
    "four": "We bound the SYNTHETIC coding gain of a drifting channel with a turbulent boundary layer.",
}


def stage_link_records(rows: list[dict[str, Any]]) -> Any:
    """One search of SYNTHETIC records, recorded in a shuffled order: the works and links must not depend on it.

    The set deliberately leaves out the one case whose outcome does depend on arrival order — two published records
    asking for the same preprint, where the first one to arrive takes it — which is named in the decision's Limits.
    Random `srv_` and `wrk_` identifiers and the head of a work stay out of the output; records are named by the
    identifier the provider gave them.
    """
    with tempfile.TemporaryDirectory() as directory:
        conn = db.connect(Path(directory) / "library.sqlite")
        db.migrate(conn)
        store = Store(conn)
        rid = store.create_research("SYNTHETIC question?", "academic", "quick", ["openalex"], "fake", "fake-model",
                                    None, search_workflow="sw")
        run = store.create_run(rid, "discovery", {"max_model_calls": 1, "max_provider_requests": 1,
                                                  "max_candidates": 50, "max_answer_passages": 8}, None)
        records = [ProviderRecord(
            provider_record_id=row["id"], title=row["title"], authors=list(LINK_AUTHORS), year=2026, venue=None,
            publication_type=None, doi=row["doi"], landing_url=None, oa_pdf_url=None, oa_pdf_version=None,
            version_label="submittedVersion" if row["preprint"] else "publishedVersion", abstract=row["abstract"],
            abstract_origin="provider" if row["abstract"] else None, identifiers={}, raw={},
            merge_by_doi=not row["preprint"]) for row in rows]
        step = store.step(run["id"], "search:0", "provider_search:openalex")
        store.record_search(
            dict(research_id=rid, run_id=run["id"], step_id=step["id"], scope_revision=1, provider="openalex",
                 query_text="q", request_description="GET test", access_mode="keyless", status="completed",
                 delivery_class=None, result_count=len(records), provider_total=len(records), page_limit=25,
                 error_json=None, raw_payload_path=None),
            "openalex", records, None, step["id"], "succeeded", step_output={"status": "completed"})
        named = {r[0]: r[1] for r in conn.execute(
            "SELECT source_version_id, value FROM identifier_mappings WHERE scheme = 'openalex'")}
        grouped: dict[str, list[str]] = {}
        for svid, work_id in conn.execute("SELECT id, work_id FROM source_versions"):
            grouped.setdefault(work_id, []).append(named[svid])
        works = [{"work": " ".join(sorted(ids))} for ids in grouped.values()]
        stored = [{"pair": " ".join(sorted((named[r["source_version_id"]], named[r["other_source_version_id"]]))),
                   "link_kind": r["link_kind"], "rule": r["rule"], "merged": r["merged"],
                   "parent": named.get(r["parent_source_version_id"])}
                  for r in conn.execute("SELECT * FROM record_links WHERE closed_at IS NULL")]
        conn.close()
    return {"works": canonical_rows(works, "work"), "links": canonical_rows(stored, "pair")}


VOCABULARY_QUESTION = ("SYNTHETIC: what is the effect of packet size on energy consumption in wireless sensor "
                       "networks, using integer programming, not surveys?")
# A fixed answer per probe query, so the stage reads counts without a network. The numbers are invented: they make
# the gate exceed MANAGEABLE_TOTAL once, which is the branch the replay has to pin down.
VOCABULARY_COUNTS = {
    '"packet size"': 900, "packet": 2_400_000, "size": 9_000_000,
    '"energy consumption"': 40_000, "energy": 3_100_000, "consumption": 1_200_000,
    '"wireless sensor networks"': 50_000, "wireless": 800_000, "networks": 7_000_000,
}


# SYNTHETIC answers of three block-labelling runs over the phrases the question above gives (SW17). Two runs agree
# that the second phrase is a setting and that the method phrase is a claim; the third dissents, and all three
# disagree about "effect", which is the branch where no majority forms and the rule's label stands.
VOCABULARY_LABEL_RUNS = [
    {"energy consumption": "outcome", "wireless sensor networks": "setting", "synthetic": "not_a_term",
     "effect": "not_a_term", "packet size": "task", "integer programming": "claim", "surveys": "exclusion"},
    {"energy consumption": "outcome", "wireless sensor networks": "setting", "synthetic": "not_a_term",
     "effect": "task", "packet size": "task", "integer programming": "claim", "surveys": "exclusion"},
    {"energy consumption": "task", "wireless sensor networks": "setting", "synthetic": "not_a_term",
     "effect": "outcome", "packet size": "task", "integer programming": "setting", "surveys": "exclusion"},
]


def stage_code_vocabulary(rows: list[dict[str, Any]]) -> Any:
    """The question read by code, labelled by three runs, probed against fixed counts and compiled (SW2, SW17).

    The rows are the providers, which carry no order of their own; the question is one string, so the phrase order
    inside the vocabulary is the question's and is not shuffled. The three labelling runs carry no order of their
    own either, so the row order decides which one arrives first and must not reach the result.
    """
    async def count(query: str) -> int | None:
        return VOCABULARY_COUNTS.get(query, 6_000)  # an unlisted query is over MANAGEABLE_TOTAL, so the gate narrows

    providers = [row["id"] for row in rows]
    turn = providers.index("openalex") % len(VOCABULARY_LABEL_RUNS)
    labelled, records = apply_labels(extract(VOCABULARY_QUESTION), VOCABULARY_LABEL_RUNS[turn:] + VOCABULARY_LABEL_RUNS[:turn])
    vocabulary = asyncio.run(build_vocabulary(labelled, count))
    vocabulary["labelling"] = {"runs_ok": len(VOCABULARY_LABEL_RUNS), "skipped": None, "failures": [],
                               "phrases": records}
    queries = compile_block_queries(vocabulary, providers, len(providers))
    return {"vocabulary": vocabulary, "queries": canonical_rows(queries, "provider_id")}


EXPANSION_VOCABULARY = {
    "terms": [
        {"phrase": "wireless sensor networks", "block": "setting", "origin": "question", "root": "wireless",
         "in_query": "root", "phrase_count": 900, "root_count": 900, "and_only": False, "dropped": None},
        {"phrase": "packet size", "block": "task", "origin": "question", "root": "packet", "in_query": "root",
         "phrase_count": 700, "root_count": 700, "and_only": False, "dropped": None},
    ],
    "claim_words": ["integer programming"], "exclusion_words": ["surveys"],
}
# Fixed SYNTHETIC counts: "duty cycle" is used in the field, "sensor node" is not used enough of the time.
EXPANSION_COUNTS = {'"duty cycle"': 400, '"duty cycle" AND (wireless)': 120,
                    '"cycle scheduling"': 300, '"cycle scheduling" AND (wireless)': 90,
                    '"sensor node"': 5_000, '"sensor node" AND (wireless)': 30}


def stage_expansion(rows: list[dict[str, Any]]) -> Any:
    """The candidate phrases of a first round and the field probe's verdict on each (SW2.4).

    The records carry no order of their own — they are what the providers happened to return — so neither their
    order nor a set's iteration order may reach the candidate list, the probe order or the accepted terms.
    """
    async def count(query: str) -> int | None:
        return EXPANSION_COUNTS.get(query)  # an unlisted query is unknown, which refuses its phrase

    found = phrase_candidates(rows, ["wireless", "packet"], EXPANSION_VOCABULARY["claim_words"])
    return {"candidates": [{"phrase": c.phrase, "document_frequency": c.document_frequency,
                            "sources": list(c.sources)} for c in found],
            "expansion": asyncio.run(expand(EXPANSION_VOCABULARY, found, count))}


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
    "link_records": stage_link_records,
    "code_vocabulary": stage_code_vocabulary,
    "expansion": stage_expansion,
}

ROWS: dict[str, list[dict[str, Any]]] = {
    "compile_queries": CONCEPTS,
    "chunk_page": [{"id": f"pg{i}", "text": PAGE_TEXT} for i in range(4)],
    "fuse_rankings": [{"id": f"psg_{i}", "text": "SYNTHETIC passage"} for i in range(6)],
    "answer_source_order": [{"id": f"svr_{i}", "text": "SYNTHETIC molecule release schedule"} for i in range(6)],
    "build_protocol": [{"id": p} for p in ("openalex", "crossref", "arxiv", "pubmed")],
    "code_vocabulary": [{"id": p} for p in ("openalex", "crossref", "arxiv", "pubmed", "scopus")],
    # Five records of four works: two versions of one work, so a phrase both of them hold is counted once. The
    # titles are SYNTHETIC and hold phrases the question's own terms do not cover.
    "expansion": [
        {"work_id": "wrk_one", "title": "SYNTHETIC duty cycle scheduling in a sensor node",
         "author_keywords": ["duty cycle", "energy harvesting"]},
        {"work_id": "wrk_one", "title": "SYNTHETIC duty cycle scheduling in a sensor node (preprint)",
         "author_keywords": ["duty cycle"]},
        {"work_id": "wrk_two", "title": "SYNTHETIC cycle scheduling of a sensor node under integer programming",
         "author_keywords": []},
        {"work_id": "wrk_three", "title": "SYNTHETIC duty cycle scheduling for a sensor node",
         "author_keywords": ["duty cycle"]},
        {"work_id": "wrk_four", "title": "SYNTHETIC duty cycle policy of a sensor node",
         "author_keywords": ["energy harvesting"]},
    ],
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
    # One merging pair (a preprint and its published record), one extended_version pair of two published records,
    # one suspected pair of two preprints whose abstracts disagree, a correction notice with its paper, and two
    # records nothing links to. SYNTHETIC; they show link behavior, not identity accuracy.
    "link_records": [
        # PA and RA are the merging pair, placed so that both shuffles the test runs put RA first instead.
        {"id": "PA", "title": LINK_TITLES["one"], "doi": "10.1109/synth.2026.1", "abstract": LINK_ABSTRACTS["one"],
         "preprint": False},
        {"id": "PC", "title": LINK_TITLES["two"], "doi": "10.1109/synth.2026.2", "abstract": LINK_ABSTRACTS["two"],
         "preprint": False},
        {"id": "PD", "title": LINK_TITLES["two"], "doi": "10.1145/synth.2026.3", "abstract": LINK_ABSTRACTS["two"],
         "preprint": False},
        {"id": "RA", "title": LINK_TITLES["one"], "doi": "10.48550/arxiv.2601.00001",
         "abstract": LINK_ABSTRACTS["one"], "preprint": True},
        {"id": "RE", "title": LINK_TITLES["three"], "doi": "10.48550/arxiv.2601.00002",
         "abstract": LINK_ABSTRACTS["three"], "preprint": True},
        {"id": "RF", "title": LINK_TITLES["three_retitled"], "doi": "10.48550/arxiv.2601.00003",
         "abstract": LINK_ABSTRACTS["three_other"], "preprint": True},
        {"id": "PG", "title": LINK_TITLES["four"], "doi": "10.1109/synth.2026.4", "abstract": LINK_ABSTRACTS["four"],
         "preprint": False},
        {"id": "NG", "title": f"Publisher Correction: {LINK_TITLES['four']}", "doi": "10.1109/synth.2026.5",
         "abstract": None, "preprint": False},
        {"id": "PH", "title": LINK_TITLES["five"], "doi": "10.1109/synth.2026.6", "abstract": None,
         "preprint": False},
        {"id": "PI", "title": LINK_TITLES["six"], "doi": "10.1109/synth.2026.7", "abstract": None,
         "preprint": False},
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
