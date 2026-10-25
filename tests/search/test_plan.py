"""Plan step: the words code picks from the question, the protocol proposal and the frozen protocol record.

Records and questions are SYNTHETIC; no model, no network. Passing shows how the plan is built and frozen, not that
the chosen words are good ones.
"""

from deixis.providers import query_compiler
from deixis.workflow.search import search as fast_search
import asyncio
from deixis.providers.query_compiler import compile_block_queries
from deixis.workflow.search.vocabulary import build_vocabulary
from deixis.domain.vocabulary import Extraction
import json
import sqlite3
import pytest
from deixis.config import Settings
from deixis.domain.canonical import sha256_hex
from deixis.storage import db
from deixis.workflow.run.store import Store


# ---- from tests__discovery__test_plan_words.py ------------------------------------------------------------

# The [parity] research's code vocabulary: OpenAlex has room for five task words, so the sixth is cut from its query,
# while the Semantic Scholar bulk query holds all six.
TASK = ["parity", "relationship", "k-connectivity", "network", "energy", "modeled"]


def term(phrase, block, dropped=None, origin="question"):
    return {"phrase": phrase, "block": block, "origin": origin, "root": phrase, "in_query": "phrase",
            "phrase_count": None, "root_count": None, "and_only": False, "dropped": dropped}


def vocabulary(extra=()):
    return {"terms": [term("synthetic", "setting"), *(term(w, "task") for w in TASK), *extra]}


def plan_for(vocab, *, deep):
    queries = query_compiler.compile_block_queries(vocab, ["openalex", "semantic_scholar"], 4)
    openalex = [{"index": i, "query": q} for i, q in enumerate(queries) if q["provider_id"] == "openalex"]
    s2 = next(q for q in queries if q["provider_id"] == "semantic_scholar")
    return {"keywords": openalex, "s2_bulk": s2 if deep else None}, queries


def by_term(words):
    return {w["term"]: (w["searched"], w["left_out"]) for w in words}


def test_a_word_the_sent_bulk_query_holds_is_searched():
    vocab = vocabulary()
    plan, _ = plan_for(vocab, deep=True)
    assert by_term(fast_search.plan_words(vocab, plan))["modeled"] == (True, None)


def test_a_word_only_an_unsent_query_holds_is_not_sent():
    """No OpenAlex keyword query is sent and the bulk query is not sent either: every word was held only by queries the
    plan leaves out."""
    vocab = vocabulary()
    words = fast_search.plan_words(vocab, {"keywords": [], "s2_bulk": None})
    assert {(w["searched"], w["left_out"]) for w in words} == {(False, "not_sent")}


def test_the_panel_names_the_plan_words_as_the_plan_writes_them():
    """The Search plan panel lists the plan's own words the frozen search records as not searched, matched one way
    written; a protocol frozen before the record lists nothing rather than guessing."""
    from deixis.workflow.search import user_plan

    plan = {"setting": [{"term": "Synthetic"}], "task": [{"term": "energy"}, {"term": "Modeled"}]}
    words = [{"block": "setting", "term": "synthetic", "searched": True, "left_out": None},
             {"block": "task", "term": "energy", "searched": None, "left_out": None},
             {"block": "task", "term": "modeled", "searched": False, "left_out": "query_limit"}]
    assert user_plan._unsearched(plan, {"fast_path_search": {"words": words}}) == [
        {"block": "task", "term": "Modeled", "left_out": "query_limit"}]
    assert user_plan._unsearched(plan, {"fast_path_search": {"version": 1}}) is None
    assert user_plan._unsearched(plan, {}) is None


# ---- from tests__discovery__test_protocol_approval.py ------------------------------------------------------------

# SYNTHETIC: a soil science question and a clinical one, so no product rule can be tuned to one field.


COUNTS = {
    '"arable soils"': 900, '"biochar addition"': 400, '"nitrous oxide emissions"': 700,
    "arable": 4_000, "soils": 60_000, "biochar": 1_200, "addition": 90_000,
    "nitrous": 2_000, "oxide": 80_000, "emissions": 150_000,
    "(arable) AND (biochar OR nitrous)": 300,
    '"cover crops"': 800, "cover": 70_000, "crops": 50_000,
    "(arable) AND (biochar OR nitrous OR cover)": 420,
    "(arable) AND (nitrous)": 260, "(arable) AND (biochar)": 180,
    "(arable OR biochar) AND (nitrous)": 520,
    '"no such phrase anywhere"': 0,
}


class Probe:
    """A count probe that answers from a fixed table and records every query it was really asked."""

    def __init__(self, counts=None):
        self.asked, self.counts = [], counts if counts is not None else COUNTS

    async def __call__(self, query):
        self.asked.append(query)
        return self.counts.get(query)


def extraction(origins=None):
    return Extraction(language="en",
                      blocks={"setting": ["arable soils"], "task": ["biochar addition", "nitrous oxide emissions"],
                              "outcome": []},
                      claim_words=[], exclusion_words=[], block_assignment="rule", origins=origins or {})


def proposal(probe=None, criterion=None):
    """The vocabulary a first round would have built for the soil question, with a criterion beside it."""
    built = asyncio.run(build_vocabulary(extraction(), probe or Probe()))
    built["labelling"] = {"runs_ok": 3, "skipped": None, "failures": [], "phrases": [
        {"phrase": "arable soils", "rule_block": "setting", "runs": ["setting"] * 3, "block": "setting",
         "origin": "model"},
        {"phrase": "biochar addition", "rule_block": "task", "runs": ["task"] * 3, "block": "task",
         "origin": "model"},
        {"phrase": "nitrous oxide emissions", "rule_block": "task", "runs": ["task"] * 2, "block": "task",
         "origin": "rule"},
    ]}
    return {"vocabulary": built, "queries": compile_block_queries(built, ["openalex"], 4),
            "criterion": criterion, "criterion_failures": []}


# ---- from tests__discovery__test_protocol_record.py ------------------------------------------------------------

def store_for(tmp_path):
    conn = db.connect(tmp_path / "library.sqlite")
    db.migrate(conn)
    return Store(conn)


def test_a_frozen_protocol_record_can_be_neither_changed_nor_removed(tmp_path):
    store = store_for(tmp_path)
    rid = store.create_research("SYNTHETIC question", "academic", "quick", ["openalex"], "fake", "fake-model", None)
    store.freeze_protocol(rid, 1, {"schema": "deixis.protocol.v1"})
    with pytest.raises(sqlite3.IntegrityError):
        store.conn.execute("UPDATE protocol_records SET reason = 'x'")
    with pytest.raises(sqlite3.IntegrityError):
        store.conn.execute("DELETE FROM protocol_records")


def test_a_second_freeze_of_the_same_body_keeps_one_record_and_a_changed_body_needs_a_reason(tmp_path):
    store = store_for(tmp_path)
    rid = store.create_research("SYNTHETIC question", "academic", "quick", ["openalex"], "fake", "fake-model", None)
    first = store.freeze_protocol(rid, 1, {"schema": "deixis.protocol.v1", "arms": ["keyword_search"]})
    again = store.freeze_protocol(rid, 1, {"schema": "deixis.protocol.v1", "arms": ["keyword_search"]})
    assert (again["id"], again["protocol_revision"]) == (first["id"], 1)
    assert first["hash"] == sha256_hex(first["body"])
    with pytest.raises(ValueError):
        store.freeze_protocol(rid, 1, {"schema": "deixis.protocol.v1", "arms": []})
    changed = store.freeze_protocol(rid, 1, {"schema": "deixis.protocol.v1", "arms": []}, reason="vocabulary approved")
    assert changed["protocol_revision"] == 2
    assert store.current_protocol(rid, 1)["hash"] == changed["hash"]
    row = store.conn.execute("SELECT body_json, body_sha256 FROM protocol_records WHERE id = ?", (changed["id"],)).fetchone()
    assert row["body_sha256"] == sha256_hex(json.loads(row["body_json"]))


SW_SCOPE = {"question": "SYNTHETIC question", "steering": None, "language_hint": None, "source_scope": "academic",
            "seed_mode": "question_only", "providers": ["openalex"], "model_connection": "fake",
            "requested_model": "fake-model", "reasoning_effort": None, "literature_model": None, "review_mode": "off",
            "search_workflow": "sw", "effort": "quick"}


def vocabulary_for(*phrases, claim_words=(), exclusion_words=()):
    """The shape `build_protocol` reads: one queried term per phrase, plus the two side lists."""
    return {"terms": [{"phrase": phrase, "block": "task", "origin": "question", "root": phrase.split()[0],
                       "in_query": "phrase", "phrase_count": 100, "root_count": 100, "and_only": False,
                       "dropped": None} for phrase in phrases],
            "claim_words": list(claim_words), "exclusion_words": list(exclusion_words),
            "block_assignment": "rule"}


def sw_body(vocabulary):
    from deixis.workflow.search import protocol
    return protocol.build_protocol(SW_SCOPE, {}, None, [], "pkg_hash", Settings(data_dir=None),
                                   vocabulary=vocabulary)


def test_a_word_the_question_itself_uses_is_recorded_as_dropped():
    """The list stays field-independent; what leaves it for this research is written into its protocol."""
    body = sw_body(vocabulary_for("code review", claim_words=["static analysis"]))
    assert body["survey"]["dropped_title_words"] == ["review"]
    assert "review" not in body["survey"]["title_words"] and "survey" in body["survey"]["title_words"]
