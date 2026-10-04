"""The frozen protocol record of a research, and the audit digests of what a step sent and received (SW14).

Fixture records are SYNTHETIC: these tests show workflow behavior, not model quality or live provider access.
"""

import json
import sqlite3

import pytest

from deixis.config import Settings, load_settings
from deixis.domain.canonical import sha256_hex
from deixis.storage import db
from deixis.workflow.store import Store


def store_for(tmp_path):
    conn = db.connect(tmp_path / "library.sqlite")
    db.migrate(conn)
    return Store(conn)


def test_the_protocol_migration_adds_the_record_table_and_the_hash_columns(tmp_path):
    store = store_for(tmp_path)
    columns = lambda table: {row[1] for row in store.conn.execute(f"PRAGMA table_info({table})")}
    assert columns("protocol_records") >= {"id", "research_id", "scope_revision", "protocol_revision", "reason",
                                           "body_json", "body_sha256", "created_at"}
    assert "search_workflow" in columns("scope_revisions")
    assert "protocol_hash" in columns("run_steps")
    assert "payload_sha256" in columns("step_inputs")
    assert "output_sha256" in columns("model_sessions")
    assert "payload_sha256" in columns("search_runs")


def test_a_frozen_protocol_record_can_be_neither_changed_nor_removed(tmp_path):
    store = store_for(tmp_path)
    rid = store.create_research("SYNTHETIC question", "academic", "quick", ["openalex"], "fake", "fake-model", None)
    store.freeze_protocol(rid, 1, {"schema": "deixis.protocol.v1"})
    with pytest.raises(sqlite3.IntegrityError):
        store.conn.execute("UPDATE protocol_records SET reason = 'x'")
    with pytest.raises(sqlite3.IntegrityError):
        store.conn.execute("DELETE FROM protocol_records")


def test_an_obsolete_search_workflow_setting_warns_without_selecting_it(monkeypatch):
    monkeypatch.setenv("DEIXIS_SEARCH_WORKFLOW", "bogus")
    with pytest.warns(UserWarning, match="DEIXIS_SEARCH_WORKFLOW is ignored"):
        assert not hasattr(load_settings(), "search_workflow")


def test_the_default_search_workflow_is_sw(tmp_path):
    store = store_for(tmp_path)
    rid = store.create_research("SYNTHETIC question", "academic", "quick", ["openalex"], "fake", "fake-model", None)
    assert store.scope(rid)["search_workflow"] == "sw"


def test_the_workflow_a_research_was_opened_with_survives_a_scope_revision(tmp_path):
    store = store_for(tmp_path)
    rid = store.create_research("SYNTHETIC question", "academic", "quick", ["openalex"], "fake", "fake-model", None,
                                search_workflow="sw")
    assert store.scope(rid)["search_workflow"] == "sw"
    revision = store.revise_scope(rid, store.research(rid)["version"], "SYNTHETIC question, narrowed", None)
    assert store.scope(rid, revision)["search_workflow"] == "sw"
    other = store.create_research("SYNTHETIC other", "academic", "quick", ["openalex"], "fake", "fake-model", None)
    assert store.scope(other)["search_workflow"] == "sw"


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


def test_build_protocol_is_repeatable_and_reads_its_thresholds_from_their_definitions():
    from deixis.documents.pdf import CHUNK_CHARS
    from deixis.domain.rules import SCREENING_BATCH
    from deixis.workflow import criterion_passages, flow, protocol

    scope = {"question": "SYNTHETIC question", "steering": None, "language_hint": None, "source_scope": "academic",
             "seed_mode": "question_only", "search_workflow": "sw", "providers": ["openalex", "crossref"],
             "model_connection": "fake", "requested_model": "fake-model", "reasoning_effort": None,
             "literature_model": None, "review_mode": "off", "effort": "quick"}
    plan = {"concepts": [{"label": "diffusion channel", "role": "core", "synonyms": ["diffusion channel"]}]}
    queries = [{"provider_id": "openalex", "query_text": "diffusion channel", "results": 25}]
    settings = Settings(data_dir=None)
    body = protocol.build_protocol(scope, {"max_candidates": 20}, plan, queries, "pkg_hash", settings)
    assert sha256_hex(body) == sha256_hex(protocol.build_protocol(scope, {"max_candidates": 20}, plan, queries, "pkg_hash", settings))
    assert body["schema"] == protocol.PROTOCOL_SCHEMA and body["search_workflow"] == "sw"
    assert body["thresholds"]["screening_batch"] == SCREENING_BATCH
    assert body["thresholds"]["chunk_chars"] == CHUNK_CHARS
    assert body["thresholds"]["rrf_k"] == flow.RRF_K
    assert body["thresholds"]["max_passages_per_source"] == flow.MAX_PASSAGES_PER_SOURCE
    assert body["thresholds"]["pdf_pages_per_source"] == flow.PDF_PAGES_PER_SOURCE
    assert body["thresholds"]["max_abstract_chars"] == flow.MAX_ABSTRACT_CHARS
    assert "formulation_score_threshold" not in body["thresholds"]
    assert body["thresholds"]["criterion_passages"] == criterion_passages.THRESHOLDS
    # Crossref is in the scope for DOI verification and is not a searched database (D87, slice 13b review).
    assert body["providers"] == ["openalex"] and body["verification_providers"] == ["crossref"]
    assert body["arms"] == ["keyword_search"]
    assert body["compiled_queries"] == [{"provider_id": "openalex", "query_text": "diffusion channel", "results": 25}]
    assert body["vocabulary"] is None and body["inclusion_criterion"] is None
    assert protocol.build_protocol(scope, {}, None, [], "pkg_hash", settings)["vocabulary"] is None


def test_sw_protocol_carries_its_current_thresholds():
    from deixis.domain.record_identity import THRESHOLDS
    from deixis.domain.rules import ABSTRACT_BATCH, ABSTRACT_READ_LIMIT, PROVIDER_WAIT, SW_READ_LIMIT
    from deixis.workflow import protocol

    scope = {"question": "SYNTHETIC question", "steering": None, "language_hint": None, "source_scope": "academic",
             "seed_mode": "question_only", "providers": ["openalex"], "model_connection": "fake",
             "requested_model": "fake-model", "reasoning_effort": None, "literature_model": None,
             "review_mode": "off", "effort": "quick"}
    body = protocol.build_protocol(scope, {}, None, [], "pkg_hash", Settings(data_dir=None))
    assert body["search_workflow"] == "sw"
    assert body["rule_table_version"] == "sw"
    assert body["thresholds"]["record_identity"] == THRESHOLDS
    assert body["thresholds"]["search_read"] == {"read_limit_per_query": SW_READ_LIMIT["quick"],
                                                  "rate_limit_retries": PROVIDER_WAIT["quick"]}
    assert body["thresholds"]["abstract_screening"]["read_limit"] == ABSTRACT_READ_LIMIT["quick"]
    assert body["thresholds"]["abstract_screening"]["batch"] == ABSTRACT_BATCH
    assert "formulation_score_threshold" not in body["thresholds"]
    assert body["verification_providers"] == []
    assert [signal["signal"] for signal in body["signals"]] == ["bm25", "blocks", "tfidf", "graph", "embedding"]


def test_an_sw_body_carries_the_chain_policy_its_budget_froze():
    """D95: the setting is read from the run's budget, so both revisions of one run carry the same block."""
    from deixis.workflow import protocol

    scope = {"question": "SYNTHETIC question", "steering": None, "language_hint": None, "source_scope": "academic",
             "seed_mode": "question_only", "providers": ["openalex"], "model_connection": "fake",
             "requested_model": "fake-model", "reasoning_effort": None, "literature_model": None,
             "review_mode": "off", "effort": "standard"}
    settings = Settings(data_dir=None)
    auto = {"citation_chaining": "auto", "max_chain_requests": 40}
    sw = protocol.build_protocol(scope | {"search_workflow": "sw"}, auto, None, [], "pkg_hash", settings)
    assert sw["citation_chaining"] == {
        "enabled": True, "rule_version": "deixis.citation_chaining.v1", "seeds": 15, "user_seeds": "every_verified",
        "seed_order": "bm25_blocks_fused", "directions": ["backward", "forward"], "source": "openalex",
        "citing_cap": 400, "backward_batch": 100, "request_limit": 40,
        "filter": "gate_block_form_in_title_or_abstract", "abstract_read": 50, "plan_room": 12}
    assert sw["thresholds"]["chain"] == {"seeds": 15, "citing_cap": 400, "backward_batch": 100, "request_limit": 40,
                                         "abstract_read": 50, "plan_room": 12}
    off = protocol.build_protocol(scope | {"search_workflow": "sw"}, {"citation_chaining": "off"}, None, [],
                                  "pkg_hash", settings)
    assert off["citation_chaining"] == {"enabled": False} and "chain" not in off["thresholds"]
    before = protocol.build_protocol(scope | {"search_workflow": "sw"}, {}, None, [], "pkg_hash", settings)
    assert "citation_chaining" not in before and "chain" not in before["thresholds"]








def test_an_output_that_is_not_json_is_digested_as_text(tmp_path):
    store = store_for(tmp_path)
    rid = store.create_research("SYNTHETIC question", "academic", "quick", ["openalex"], "fake", "fake-model", None)
    run = store.create_run(rid, "discovery", {}, None)
    step = store.step(run["id"], "search_plan", "model:search_plan")
    store.insert_step_input(step["id"], rid, run["id"], 0,
                            {"step_input_id": "sti_x", "task_type": "search_plan", "scope_revision": 1,
                             "skill_package_hash": "pkg"}, "base", "dev", "msg", {})
    session_id = store.start_model_session(rid, run["id"], step["id"], "sti_x", "fake", "fake-model")
    store.finish_model_session(session_id, status="completed", raw_output="not json at all")
    digest = store.conn.execute("SELECT output_sha256 FROM model_sessions WHERE id = ?", (session_id,)).fetchone()[0]
    assert digest == "text:" + sha256_hex("not json at all")
    assert store.conn.execute("SELECT payload_sha256 FROM step_inputs WHERE id = 'sti_x'").fetchone()[0] == sha256_hex(
        {"step_input_id": "sti_x", "task_type": "search_plan", "scope_revision": 1, "skill_package_hash": "pkg"})






# ---- the survey rule the body records (slice 05) --------------------------------------------

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
    from deixis.workflow import protocol
    return protocol.build_protocol(SW_SCOPE, {}, None, [], "pkg_hash", Settings(data_dir=None),
                                   vocabulary=vocabulary)


def test_an_sw_body_records_the_survey_words_the_thresholds_and_the_lookup_limits():
    from deixis.domain.survey import REFERENCE_COUNT_SURVEY
    from deixis.domain.survey_words import ABSTRACT_SELF_DESCRIPTIONS, STRONG_TITLE_WORDS
    from deixis.workflow.lookups import MAX_LOOKUP_REQUESTS

    body = sw_body(vocabulary_for("molecular communication"))
    assert body["survey"] == {"title_words": list(STRONG_TITLE_WORDS), "dropped_title_words": [],
                              "abstract_patterns": list(ABSTRACT_SELF_DESCRIPTIONS)}
    assert body["thresholds"]["survey"] == {"reference_count": REFERENCE_COUNT_SURVEY}
    assert body["thresholds"]["lookup"]["max_requests"] == MAX_LOOKUP_REQUESTS
    # Retries are requests too, so the worst case one run can send is written down beside the limit.
    assert body["thresholds"]["lookup"]["max_requests_with_retries"] > MAX_LOOKUP_REQUESTS


def test_a_word_the_question_itself_uses_is_recorded_as_dropped():
    """The list stays field-independent; what leaves it for this research is written into its protocol."""
    body = sw_body(vocabulary_for("code review", claim_words=["static analysis"]))
    assert body["survey"]["dropped_title_words"] == ["review"]
    assert "review" not in body["survey"]["title_words"] and "survey" in body["survey"]["title_words"]


def test_a_word_only_the_exclusion_list_uses_is_dropped_too():
    body = sw_body(vocabulary_for("packet size", exclusion_words=["survey"]))
    assert body["survey"]["dropped_title_words"] == ["survey"]


def test_a_plural_in_the_question_does_not_drop_the_singular_word():
    """The match is at a word boundary and nothing is stemmed, so "not surveys" leaves the rule its word.

    This is the rule as written, not a measured choice: a question that excludes surveys still wants them routed to
    the seed pool, but a question whose *subject* is written in the plural would keep a word it should drop.
    """
    body = sw_body(vocabulary_for("packet size", exclusion_words=["surveys"]))
    assert body["survey"]["dropped_title_words"] == []


def test_the_same_research_freezes_one_survey_record_twice():
    first, second = sw_body(vocabulary_for("code review")), sw_body(vocabulary_for("code review"))
    assert sha256_hex(first) == sha256_hex(second)
