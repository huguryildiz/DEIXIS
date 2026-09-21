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
from deixis.domain import survey
from deixis.domain.expansion import candidates as phrase_candidates
from deixis.domain.vocabulary import extract
from deixis.providers.common import ProviderRecord
from deixis.providers.query_compiler import compile_block_queries, compile_queries
from deixis.storage import db
from deixis.workflow.decisions import DecisionStore
from deixis.workflow import links
from deixis.workflow.expansion import expand
from deixis.workflow.flow import answer_source_order, fuse_rankings
from deixis.workflow import abstract_stage, fulltext, ranking, suggestions
from deixis.workflow.protocol import build_protocol
from deixis.workflow.store import Store
from deixis.workflow.approval import apply_criterion, canonical_edits, edited_extraction
from deixis.workflow.criterion import consensus
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
        ts = "2026-09-20T00:00:00.000+00:00"
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
        # The links a second source named, read after the search as the `external_links` step reads them. A record
        # naming a DOI is written before the reading, so the reading order is the one under test, not the writing.
        for row in sorted((r for r in rows if r.get("names")), key=lambda r: r["id"]):
            svid = store.find_source_by_identifier("openalex", row["id"])
            with db.transaction(conn):
                conn.execute("INSERT OR IGNORE INTO identifier_mappings (source_version_id, scheme, value, provider,"
                             " retrieved_at) VALUES (?, 'doi', ?, 'openalex', ?)", (svid, row["doi"], ts))
                for value in row["names"]:
                    conn.execute("INSERT OR IGNORE INTO identifier_mappings (source_version_id, scheme, value,"
                                 " provider, retrieved_at) VALUES (?, 'linked_doi', ?, 'semantic_scholar', ?)",
                                 (svid, value, ts))
        with db.transaction(conn):
            links.link_external(store, rid)
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


SURVEY_QUESTION_FORMS = ["release scheduling", "diffusion channel", "integer programming", "code review"]


def stage_survey_flags(rows: list[dict[str, Any]]) -> Any:
    """The survey signals of fixed SYNTHETIC records and the abstract-stage code each of them asks for (SW5, SW9.3).

    The records carry no order of their own — they are what the providers happened to return — so neither their
    order nor a set's iteration order may reach the flags, their evidence or the code. "code review" is among the
    question's own forms, so this research reads no title for the word "review".
    """
    kept, dropped = survey.title_words(SURVEY_QUESTION_FORMS)
    found = []
    for row in sorted(rows, key=lambda r: r["id"]):
        signals = survey.signals(row["title"], row["abstract"], row["reference_count"], kept)
        # The same rule `lookups._wanted_decision` applies, without the database it reads for the rest of it.
        code = ("survey_title_word" if any(s.flag == "survey_title_word" for s in signals)
                else "no_abstract" if row["abstract"] is None else None)
        found.append({"id": row["id"], "flags": [{"flag": s.flag, "evidence": s.evidence} for s in signals],
                      "code": code})
    return {"words": {"kept": list(kept), "dropped": list(dropped)}, "records": canonical_rows(found, "id")}


# One SYNTHETIC question and three SYNTHETIC proposals for it, from a field no other stage here uses. Two phrases
# stand in two runs, one in all three and one in a single run; two exclusion words are written twice.
CRITERION_QUESTION = "SYNTHETIC: which supervised exercise programmes reduce fatigue after chemotherapy?"
CRITERION_SOUGHT = ["supervised exercise", "supervised"]
CRITERION_RUNS = [
    {"criterion": "SYNTHETIC: the paper runs a supervised programme and reports a fatigue score.",
     "parts": [{"name": "programme", "definition": "SYNTHETIC: the paper delivers the programme.",
                "phrases": ["supervised exercise", "aerobic training", "resistance training", "training sessions",
                            "exercise programme", "training protocol"]},
               {"name": "fatigue", "definition": "SYNTHETIC: the paper reports fatigue.",
                "phrases": ["facit-f", "fatigue score", "fatigue severity", "validated scale", "fatigue outcome",
                            "we measured fatigue"]}],
     "exclusion_title_words": ["review", "protocol"]},
    {"criterion": "SYNTHETIC: the paper delivers exercise and measures fatigue.",
     "parts": [{"name": "exercise", "definition": "SYNTHETIC: the paper delivers the programme.",
                "phrases": ["supervised exercise", "aerobic training", "resistance training", "training sessions",
                            "exercise programme", "walking programme"]},
               {"name": "fatigue", "definition": "SYNTHETIC: the paper reports fatigue.",
                "phrases": ["facit-f", "fatigue questionnaire", "tiredness scale", "exhaustion", "vitality",
                            "energy level"]}],
     "exclusion_title_words": ["review", "editorial"]},
    {"criterion": "SYNTHETIC: the paper is about exercise.",
     "parts": [{"name": "something else", "definition": "SYNTHETIC: the paper is about activity.",
                "phrases": ["walking programme", "physical activity", "cycling", "step count", "activity monitor",
                            "gym visits"]},
               {"name": "fatigue", "definition": "SYNTHETIC: the paper reports fatigue.",
                "phrases": ["fatigue score", "fatigue severity", "validated scale", "tiredness", "brief fatigue",
                            "fatigue scale"]}],
     "exclusion_title_words": ["review", "editorial"]},
]


def stage_criterion(rows: list[dict[str, Any]]) -> Any:
    """What three fixed SYNTHETIC proposals agree on (SW15.2).

    The three runs are three answers to one question and have no order of their own; neither have the phrases inside
    a part or the exclusion words. So the row order decides which run arrives first and in which direction its
    phrases were written, and neither may reach the result (SW14.6). The order of the parts inside a run is that
    run's own and is kept: it decides which part a kept phrase is attached to.
    """
    runs: dict[int, dict[str, Any]] = {}
    for position, row in enumerate(rows):
        source = CRITERION_RUNS[row["run"] - 1]
        backwards = position % 2 == 1
        runs[row["run"]] = {
            "criterion": source["criterion"],
            "parts": [{"name": part["name"], "definition": part["definition"],
                       "phrases": list(reversed(part["phrases"])) if backwards else list(part["phrases"])}
                      for part in source["parts"]],
            "exclusion_title_words": (list(reversed(source["exclusion_title_words"])) if backwards
                                      else list(source["exclusion_title_words"])),
        }
    return consensus(CRITERION_QUESTION, runs, CRITERION_SOUGHT)


RANKING_BLOCKS = {"setting": ["diffusion channel", "sensor node"], "task": ["release scheduling", "repeater"]}
RANKING_QUERY_WORDS = {"diffusion", "channel", "release", "scheduling", "sensor", "node", "repeater"}


def stage_record_ranking(rows: list[dict[str, Any]]) -> Any:
    """The four code signals, their ranks and the fused order of a fixed SYNTHETIC pool (SW7, SW14.6).

    The records are what the providers happened to return and carry no order of their own, so neither their order,
    nor the iteration order of a reference set or of the query words, may reach a score, a rank or the order. Two
    pairs hold identical text and identical reference lists, so each pair is a tie that must share its mean rank;
    two records have no reference list and one has no abstract, so two signals are missing for them. The seeds are
    two of the records, which also fixes the "a record never seeds itself" rule in this digest.
    """
    pool = [{"id": row["id"], "work_id": row["work_id"], "title": row["title"], "abstract": row["abstract"],
             "own_ids": frozenset(row["own_ids"]), "references": None if row["references"] is None
             else frozenset(row["references"])}
            for row in sorted(rows, key=lambda row: row["id"])]
    arrival = {row["id"]: position for position, row in enumerate(rows)}
    # The seeds are named by identifier, but the order they are given in follows the shuffled rows: which seed comes
    # first must not change a score either.
    seeds = sorted((row for row in pool if row["id"] in ("R1", "R5")), key=lambda row: arrival[row["id"]])
    scores = {"bm25": ranking.bm25_scores(pool, RANKING_QUERY_WORDS),
              "blocks": ranking.block_scores(pool, RANKING_BLOCKS),
              "tfidf": ranking.tfidf_scores(pool, seeds), "graph": ranking.graph_scores(pool, seeds)}
    ranks = {name: ranking.mean_ranks(score, ranking.availability(pool, name)) for name, score in scores.items()}
    fused = ranking.fuse(ranks, ranking.CODE_SIGNALS)
    order, rescued = ranking.inspection_order(fused, fused, None)
    return {"scores": {name: {rid: list(value) if isinstance(value, tuple) else value
                              for rid, value in score.items()} for name, score in scores.items()},
            "ranks": {name: {rid: list(value) for rid, value in row.items()} for name, row in ranks.items()},
            "fused": fused, "order": order, "rescued": rescued}


# The correction a user makes at the approval step, and the counts the proposal it corrects already read (SW2.6).
# The operations carry no order of their own: the user typed them in some order and nothing may follow from it.
APPROVAL_EDITS = [
    {"op": "remove", "phrase": "energy consumption"},
    {"op": "move", "phrase": "packet size", "block": "outcome"},
    {"op": "add", "phrase": "duty cycle", "block": "task"},
    {"op": "add", "phrase": "medium access", "block": "task"},
]
APPROVAL_COUNTS = {'"duty cycle"': 30_000, "duty": 400_000, "cycle": 2_000_000,
                   '"medium access"': 20_000, "medium": 6_000_000, "access": 8_000_000}
APPROVAL_CRITERION = {
    "criterion": "SYNTHETIC: the paper measures the energy a named packet size costs.",
    "parts": [{"name": "packet size", "definition": "SYNTHETIC: a size in bytes is named."},
              {"name": "energy", "definition": "SYNTHETIC: a joule figure is reported."}],
    "cue_phrases": [{"phrase": "energy per bit", "part": "energy"},
                    {"phrase": "payload length", "part": "packet size"}],
    "exclusion_title_words": ["editorial", "review"],
}


def stage_protocol_approval(rows: list[dict[str, Any]]) -> Any:
    """The vocabulary, the queries and the criterion a correction leaves behind (slice 08a, SW14.6).

    The rows are the providers and the correction's operations, neither of which carries an order of its own, so
    the order they arrive in must not reach the rebuilt vocabulary, its probe list or the compiled queries. The
    counts the proposal already read are given as known, so the stage sends no request for them either.
    """
    async def count(query: str) -> int | None:
        return APPROVAL_COUNTS.get(query, VOCABULARY_COUNTS.get(query, 6_000))

    providers = [row["id"] for row in rows if row.get("id")]
    edits = [APPROVAL_EDITS[row["edit"]] for row in rows if "edit" in row]
    labelled, records = apply_labels(extract(VOCABULARY_QUESTION), VOCABULARY_LABEL_RUNS)
    proposal = asyncio.run(build_vocabulary(labelled, count))
    proposal["labelling"] = {"runs_ok": len(VOCABULARY_LABEL_RUNS), "skipped": None, "failures": [],
                             "phrases": records}
    approved = asyncio.run(build_vocabulary(edited_extraction(proposal, edits), count,
                                            known={p["query"]: p["count"] for p in proposal["probes"]}))
    approved["labelling"] = proposal["labelling"]
    approved["user_edits"] = canonical_edits(edits)
    return {"vocabulary": approved, "user_edits": approved["user_edits"],
            "queries": canonical_rows(compile_block_queries(approved, providers, len(providers)), "provider_id"),
            # The criterion the user replaced is the one the three fixed proposals agreed on, so the phrases that
            # survive the replacement must keep the runs that wrote them.
            "criterion": apply_criterion(
                consensus(CRITERION_QUESTION, {number: CRITERION_RUNS[number - 1] for number in (1, 2, 3)},
                          CRITERION_SOUGHT),
                APPROVAL_CRITERION)}


# The blocks, the read plan and the two model runs of the abstract stage (slice 09, SW9, SW14.6). One SYNTHETIC
# question and six SYNTHETIC records from a field no other stage here uses: a title holding both gate blocks, a
# notice, an artifact with a stored link, two records the model reads, and one whose two versions share a work and
# whose head carries no abstract of its own.
ABSTRACT_BLOCKS = {"setting": ["greenhouse tomato"], "task": ["irrigation scheduling"], "outcome": ["marketable yield"]}
ABSTRACT_ORDER = ["A1", "A2", "A4", "A6", "A7"]
# What each of the two runs proposed about each record, and whether its quote was found. The runs carry no order of
# their own beyond their number, and neither do the records.
ABSTRACT_PROPOSALS = {
    "A4": [{"label": "candidate", "quote_verified": True}, {"label": "candidate", "quote_verified": True}],
    "A6": [{"label": "out_of_scope", "quote_verified": True}, {"label": "candidate", "quote_verified": True}],
    "A7": [{"label": "out_of_scope", "quote_verified": False}, {"label": "out_of_scope", "quote_verified": True}],
}


def stage_abstract_stage(rows: list[dict[str, Any]]) -> Any:
    """What code settles, which works the model reads and what the two runs mean (slice 09).

    The records are what the providers happened to return and carry no order of their own, so neither their order
    nor a set's iteration order may reach a code, the batches or a combined decision. The reading order is the
    inspection order the ranking stored, which is an order and is therefore given, not shuffled.
    """
    records = {row["id"]: row for row in sorted(rows, key=lambda row: row["id"])}
    codes = {rid: abstract_stage.code_outcome(row, ABSTRACT_BLOCKS, {"A3"}) for rid, row in records.items()}
    by_work: dict[str, list[dict[str, Any]]] = {}
    for rid, row in records.items():
        by_work.setdefault(row["work_id"], []).append(
            {"id": rid, "has_abstract": bool(row["abstract"]), "code": codes[rid],
             "decision": row.get("decision"), "decided_by": row.get("decided_by"), "stale": False})
    works = [{"work_id": work_id, "head": min(v["id"] for v in versions), "versions": versions}
             for work_id, versions in sorted(by_work.items())]
    plan = abstract_stage.read_plan(ABSTRACT_ORDER, works, limit=4, batch=2)
    combined = {rid: abstract_stage.combine(*runs) for rid, runs in sorted(ABSTRACT_PROPOSALS.items())}
    return {"codes": codes, "reading": {work["work_id"]: abstract_stage.reading_version(work) for work in works},
            "plan": plan, "combined": combined}


def stage_term_suggestions(rows: list[dict[str, Any]]) -> Any:
    """The card rows the model's proposed names become, and the counts they carry over (slice 08c, SW14.6).

    The rows are one model's `terms` list, which carries no order of its own: the order it happened to write them
    in must reach neither the screened list nor the known counts the approval reuses. The vocabulary they are
    screened against is the corrected one of `stage_protocol_approval`, so the two stages agree on what "already
    present" means.
    """
    async def count(query: str) -> int | None:
        return APPROVAL_COUNTS.get(query, VOCABULARY_COUNTS.get(query, 6_000))

    labelled, _ = apply_labels(extract(VOCABULARY_QUESTION), VOCABULARY_LABEL_RUNS)
    proposal = asyncio.run(build_vocabulary(labelled, count))
    screened = suggestions.screen(proposal, [{"phrase": row["phrase"], "synonym_of": row["synonym_of"]}
                                             for row in rows])
    read = {row["phrase"]: row["count"] for row in rows}
    for row in screened:
        # The flow counts exactly the rows code did not drop; each proposal's count travels with it, not with its
        # place in the list.
        row["phrase_count"] = None if row["dropped"] else read[row["phrase"]]
    return {"target": suggestions.target(VOCABULARY_QUESTION, proposal), "rows": screened,
            "known": suggestions.known_counts(screened), "model": sorted(suggestions.model_phrases(screened))}


# The retrieval plan of the full-text stage (slice 10, SW10, SW14.6). One SYNTHETIC field, eight works: one the
# user included, two code candidates, one the abstract stage routed here unresolved, one it routed back to the
# model, one out of scope, one the user excluded, one whose text is already here and one already carrying a fresh
# code of this stage. The attempts below are the four rows of the result table.
FULLTEXT_ORDER = ["F2", "F1", "F4", "F8"]
FULLTEXT_ATTEMPTS = [
    {"has_text": True, "has_asset": True, "unanswered": 0},
    {"has_text": False, "has_asset": True, "unanswered": 0},
    {"has_text": False, "has_asset": False, "unanswered": 0},
    {"has_text": False, "has_asset": False, "unanswered": 2},
]


def stage_fulltext_plan(rows: list[dict[str, Any]]) -> Any:
    """Which works a retrieval run fetches, in which order, and what one attempt settles (slice 10).

    The records are what the providers happened to return and carry no order of their own, so neither their order
    nor a set's iteration may reach the groups, the plan or a code. The reading order is the inspection order the
    ranking stored, which is an order and is therefore given, not shuffled.
    """
    by_work: dict[str, list[dict[str, Any]]] = {}
    for row in sorted(rows, key=lambda row: row["id"]):
        by_work.setdefault(row["work_id"], []).append(row)
    works = [{"work_id": work_id, "head": min(v["id"] for v in versions), "selection": versions[0].get("selection"),
              "versions": [{"id": v["id"], "has_text": bool(v.get("has_text")),
                            "abstract": v.get("abstract"), "fulltext": v.get("fulltext")} for v in versions]}
             for work_id, versions in sorted(by_work.items())]
    return {"groups": {work["head"]: fulltext.group_of(work) for work in works},
            "plan": fulltext.fetch_plan(works, FULLTEXT_ORDER, limit=3),
            "whole": fulltext.fetch_plan(works, FULLTEXT_ORDER, limit=99),
            "codes": [fulltext.settled_code(attempt) for attempt in FULLTEXT_ATTEMPTS]}


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
    "survey_flags": stage_survey_flags,
    "criterion": stage_criterion,
    "protocol_approval": stage_protocol_approval,
    "term_suggestions": stage_term_suggestions,
    "record_ranking": stage_record_ranking,
    "abstract_stage": stage_abstract_stage,
    "fulltext_plan": stage_fulltext_plan,
}

ROWS: dict[str, list[dict[str, Any]]] = {
    "compile_queries": CONCEPTS,
    "chunk_page": [{"id": f"pg{i}", "text": PAGE_TEXT} for i in range(4)],
    "fuse_rankings": [{"id": f"psg_{i}", "text": "SYNTHETIC passage"} for i in range(6)],
    "answer_source_order": [{"id": f"svr_{i}", "text": "SYNTHETIC molecule release schedule"} for i in range(6)],
    "build_protocol": [{"id": p} for p in ("openalex", "crossref", "arxiv", "pubmed")],
    "code_vocabulary": [{"id": p} for p in ("openalex", "crossref", "arxiv", "pubmed", "scopus")],
    "criterion": [{"run": number} for number in (1, 2, 3)],
    # Five providers and the four operations of one correction, shuffled together: neither the provider order nor
    # the order the operations arrive in may reach the approved vocabulary or its queries.
    "protocol_approval": ([{"id": p} for p in ("openalex", "crossref", "arxiv", "pubmed", "scopus")]
                          + [{"edit": index} for index in range(4)]),
    # The names one model proposed on the approval card. The list carries no order of its own, and it holds every
    # row code drops: a repeat, a phrase the proposal already has, one carrying a claim phrase, one carrying an
    # exclusion phrase, and one over the word bound. `count` is what the flow would have read for the row.
    "term_suggestions": [
        {"phrase": "wsn", "synonym_of": "wireless sensor networks", "count": 60_000},
        {"phrase": "payload length", "synonym_of": "packet size", "count": 8_000},
        {"phrase": "frame size", "synonym_of": "packet size", "count": 5_000},
        {"phrase": "payload length", "synonym_of": "packet size", "count": 8_000},
        {"phrase": "integer programming of payload length", "synonym_of": "packet size", "count": 40},
        {"phrase": "energy consumption", "synonym_of": "packet size", "count": 40_000},
        {"phrase": "one two three four five six seven", "synonym_of": "wireless sensor networks", "count": 5},
        {"phrase": "surveys of payload length", "synonym_of": "packet size", "count": 60},
    ],
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
    # Six SYNTHETIC records from two fields: a title survey, a title word the question itself uses (so it is not a
    # signal here), an abstract that names itself a survey, a record at the reference threshold, a record just under
    # it, and one with no signal and no abstract. They show the rule's behavior, not its accuracy.
    "survey_flags": [
        {"id": "R1", "title": "SYNTHETIC survey of relay scheduling in wireless sensor networks",
         "abstract": "We collect SYNTHETIC scheduling results.", "reference_count": 20},
        {"id": "R2", "title": "SYNTHETIC code review at scale in industrial practice",
         "abstract": "We measure SYNTHETIC defect density.", "reference_count": 30},
        {"id": "R3", "title": "SYNTHETIC release scheduling for diffusion channels",
         "abstract": "This review collects SYNTHETIC scheduling results and compares them.", "reference_count": 40},
        {"id": "R4", "title": "SYNTHETIC energy budgets of nanoscale transmitters",
         "abstract": "We derive the SYNTHETIC energy a transmitter spends.", "reference_count": 150},
        {"id": "R5", "title": "SYNTHETIC bit error rate of optical wireless links",
         "abstract": "We bound the SYNTHETIC error rate.", "reference_count": 149},
        {"id": "R6", "title": "SYNTHETIC multi hop relaying in vascular networks", "abstract": None,
         "reference_count": None},
    ],
    # Six SYNTHETIC records of two fields. R1/R2 and R3/R4 are two pairs of identical text and identical reference
    # lists, so each pair ties in every signal; R5 has no reference list, R6 has neither a list nor an abstract.
    "record_ranking": [
        {"id": "R1", "work_id": "wrk_one", "title": "SYNTHETIC release scheduling in a diffusion channel",
         "abstract": "We schedule releases in a diffusion channel and bound the error.",
         "own_ids": ["W1"], "references": ["W90", "W91", "W92"]},
        {"id": "R2", "work_id": "wrk_two", "title": "SYNTHETIC release scheduling in a diffusion channel",
         "abstract": "We schedule releases in a diffusion channel and bound the error.",
         "own_ids": ["W2"], "references": ["W92", "W91", "W90"]},
        {"id": "R3", "work_id": "wrk_three", "title": "SYNTHETIC repeater placement for a sensor node",
         "abstract": "Repeaters are placed along the link of a sensor node.",
         "own_ids": ["W3"], "references": ["W90", "W93"]},
        {"id": "R4", "work_id": "wrk_four", "title": "SYNTHETIC repeater placement for a sensor node",
         "abstract": "Repeaters are placed along the link of a sensor node.",
         "own_ids": ["W4"], "references": ["W93", "W90"]},
        {"id": "R5", "work_id": "wrk_five", "title": "SYNTHETIC bakery logistics of a small town",
         "abstract": "We deliver bread to the market every morning.", "own_ids": ["W5"], "references": None},
        {"id": "R6", "work_id": "wrk_six", "title": "SYNTHETIC diffusion channel capacity",
         "abstract": None, "own_ids": ["W6"], "references": []},
    ],
    # Eight SYNTHETIC works of the full-text retrieval plan: F1 the user included, F2 and F4 code candidates (F4 in
    # two versions, only one of them decided), F3 unresolved and routed here, F5 unresolved but routed back to the
    # model, F6 out of scope, F7 excluded by the user, F8 already carrying a fresh code of this stage, and F9 whose
    # text is already here.
    "fulltext_plan": [
        {"id": "F1", "work_id": "wrk_1", "selection": {"state": "included", "origin": "user"},
         "abstract": {"reason_code": "runs_agree_out_of_scope", "decided_by": "model_agreement", "stale": False}},
        {"id": "F2", "work_id": "wrk_2",
         "abstract": {"reason_code": "runs_agree_candidate", "decided_by": "model_agreement", "stale": False}},
        {"id": "F3", "work_id": "wrk_3",
         "abstract": {"reason_code": "abstract_not_found", "decided_by": "code", "stale": False}},
        {"id": "F4", "work_id": "wrk_4",
         "abstract": {"reason_code": "blocks_in_title", "decided_by": "code", "stale": False}},
        {"id": "F4b", "work_id": "wrk_4"},
        {"id": "F5", "work_id": "wrk_5",
         "abstract": {"reason_code": "abstract_not_read", "decided_by": "code", "stale": False}},
        {"id": "F6", "work_id": "wrk_6",
         "abstract": {"reason_code": "both_blocks_missing", "decided_by": "code", "stale": False}},
        {"id": "F7", "work_id": "wrk_7", "selection": {"state": "excluded", "origin": "user"},
         "abstract": {"reason_code": "runs_agree_candidate", "decided_by": "model_agreement", "stale": False}},
        {"id": "F8", "work_id": "wrk_8",
         "abstract": {"reason_code": "runs_agree_candidate", "decided_by": "model_agreement", "stale": False},
         "fulltext": {"reason_code": "no_fulltext", "decided_by": "code", "stale": False}},
        {"id": "F9", "work_id": "wrk_9", "has_text": True,
         "abstract": {"reason_code": "runs_agree_unresolved", "decided_by": "model_agreement", "stale": False}},
    ],
    # Six SYNTHETIC records of five works from one field: A1 holds both gate blocks in its title, A2 is a
    # correction notice, A3 an artifact with a stored link, A4 and A6 are read by the model, and A7 shares a work
    # with A5, whose head carries no abstract of its own.
    "abstract_stage": [
        {"id": "A1", "work_id": "wrk_a", "doi": "10.1/syn.1", "version_label": None,
         "title": "SYNTHETIC irrigation scheduling of a greenhouse tomato crop",
         "abstract": "We schedule the irrigation of a greenhouse tomato crop."},
        {"id": "A2", "work_id": "wrk_b", "doi": "10.1/syn.2", "version_label": None,
         "title": "Publisher Correction: SYNTHETIC irrigation scheduling of a greenhouse tomato crop",
         "abstract": "This corrects the SYNTHETIC article on irrigation scheduling."},
        {"id": "A3", "work_id": "wrk_c", "doi": "10.5281/zenodo.9", "version_label": None,
         "title": "SYNTHETIC irrigation scheduling data of a greenhouse tomato crop",
         "abstract": "The SYNTHETIC measurements behind the irrigation study."},
        {"id": "A4", "work_id": "wrk_d", "doi": "10.1/syn.4", "version_label": None,
         "title": "SYNTHETIC irrigation scheduling of an open field crop",
         "abstract": "We vary the irrigation scheduling of an open field crop and report the water it used."},
        {"id": "A5", "work_id": "wrk_e", "doi": "10.1/syn.5", "version_label": None,
         "title": "SYNTHETIC drip lines in a greenhouse tomato row", "abstract": None},
        {"id": "A7", "work_id": "wrk_e", "doi": "10.48550/arxiv.7", "version_label": "submittedVersion",
         "title": "SYNTHETIC drip lines in a greenhouse tomato row (preprint)",
         "abstract": "We place drip lines along a greenhouse tomato row and report the water each one carries."},
        {"id": "A6", "work_id": "wrk_f", "doi": "10.1/syn.6", "version_label": None,
         "title": "SYNTHETIC bakery delivery rounds of a small town",
         "abstract": "We measure the irrigation scheduling of the bakery garden between two delivery rounds."},
    ],
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
         "abstract": LINK_ABSTRACTS["three"], "preprint": True,
         # Two sources naming two different published versions: this confirms nothing, whatever the row order.
         "names": ["10.1109/synth.2026.4", "10.1109/synth.2026.6"]},
        # A preprint whose title shares nothing with the published record a source names as its version: only the
        # external link can join them.
        {"id": "RF", "title": LINK_TITLES["three_retitled"], "doi": "10.48550/arxiv.2601.00003",
         "abstract": LINK_ABSTRACTS["three_other"], "preprint": True, "names": ["10.1109/synth.2026.2"]},
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
