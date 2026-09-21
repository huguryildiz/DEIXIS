"""Candidate phrases taken from a first round's own records, and the field probe that decides them (slice 04b).

Records, titles and keywords are SYNTHETIC and from two fields; no request is sent. A passing test shows the rules
of the code — which phrase becomes a candidate, which one is refused and why — not that the phrases it accepts are
good search terms for any real question.
"""

import asyncio
import json

import pytest

from deixis.domain.expansion import MAX_PROBED_PHRASES, MIN_DOCUMENT_FREQUENCY, Candidate, candidates
from deixis.providers.common import ProviderRecord
from deixis.storage import db
from deixis.workflow.expansion import (MAX_EXPANSION_TERMS, MIN_FIELD_COUNT, count_yields, expand,
                                       second_round_vocabulary, term_yields)
from deixis.workflow.store import Store

# Two fields: sensor networks and molecular communication. The phrases are the ones the rules are read against.
SENSOR_TITLES = [
    "Duty cycle scheduling for packet size selection in wireless sensor networks",
    "Energy aware duty cycle scheduling of a sensor field",
    "A study of duty cycle scheduling under the radio model",
]
MOLECULAR_TITLES = [
    "Release scheduling in molecular communication channels",
    "Molecular communication with an absorbing receiver",
]


def records(titles, keywords=None, work_ids=None):
    rows = []
    for index, title in enumerate(titles):
        rows.append({"work_id": (work_ids or {}).get(index, f"wrk_{index}"), "title": title,
                     "author_keywords": (keywords or {}).get(index, [])})
    return rows


def phrases(found):
    return [candidate.phrase for candidate in found]


def test_an_ngram_may_not_begin_or_end_in_a_function_word_or_a_general_word():
    found = candidates(records(["Energy of the packet size approaches in sensor nodes"] * 3), [], [])
    # "energy of", "of the", "size approaches" and "the packet" all end or begin outside the content words.
    assert "packet size" in phrases(found)
    assert not any(phrase.split()[0] in ("energy", "the", "of") and " of " in phrase for phrase in phrases(found))
    assert not any(phrase.endswith(" approaches") or phrase.startswith("approaches ") for phrase in phrases(found))
    assert not any(phrase.startswith("the ") or phrase.endswith(" the") for phrase in phrases(found))


def test_a_word_shorter_than_three_letters_keeps_its_ngram_out():
    found = candidates(records(["Packet size in 5g sensor networks"] * 3), [], [])
    assert "sensor networks" in phrases(found) and not any("5g" in phrase for phrase in phrases(found))


def test_a_phrase_that_holds_a_queried_form_is_dropped():
    """The first query already returns everything that holds its own term, so such a phrase widens nothing."""
    found = candidates(records(SENSOR_TITLES), ["scheduling"], [])
    assert "duty cycle" in phrases(found)
    assert not any("scheduling" in phrase for phrase in phrases(found))


def test_a_queried_phrase_is_matched_at_a_word_boundary_only():
    found = candidates(records(["Duty cycle scheduling of the sensor network"] * 3), ["net"], [])
    assert "sensor network" in phrases(found)


def test_a_phrase_that_holds_a_claim_word_or_an_exclusion_word_is_dropped():
    """SW1.3: the claim under test never enters a query, by any route."""
    titles = ["Duty cycle scheduling by integer programming in a survey of sensors"] * 3
    found = candidates(records(titles), [], ["integer programming", "survey"])
    assert "duty cycle" in phrases(found)
    assert not any("integer programming" in phrase or "survey" in phrase for phrase in phrases(found))


def test_a_phrase_under_the_document_frequency_stays_out():
    found = candidates(records(SENSOR_TITLES + MOLECULAR_TITLES), [], [])
    assert "duty cycle" in phrases(found)  # in all three sensor titles
    assert "molecular communication" not in phrases(found)  # in two of them, below the threshold
    assert all(candidate.document_frequency >= MIN_DOCUMENT_FREQUENCY for candidate in candidates(
        records(SENSOR_TITLES + MOLECULAR_TITLES), [], []))


def test_two_versions_of_one_work_are_counted_once():
    titles = SENSOR_TITLES + [SENSOR_TITLES[0]]
    one_work = {0: "wrk_one", 3: "wrk_one"}  # the preprint and the published record of the same work
    counted = {c.phrase: c.document_frequency for c in candidates(records(titles, work_ids=one_work), [], [])}
    assert counted["duty cycle"] == 3


def test_an_author_keyword_is_a_candidate_whole_and_carries_both_sources_with_a_title():
    keywords = {0: ["duty cycle", "Energy Harvesting"], 1: ["energy harvesting"], 2: ["energy harvesting"]}
    found = {c.phrase: c for c in candidates(records(SENSOR_TITLES, keywords=keywords), [], [])}
    assert found["energy harvesting"].sources == ("author_keyword",)
    assert found["energy harvesting"].document_frequency == 3
    # One phrase, found both ways, is one candidate that names both.
    assert found["duty cycle"].sources == ("title", "author_keyword")


def test_a_single_word_author_keyword_that_is_a_general_word_is_not_a_candidate():
    keywords = {index: ["methodology", "telemetry"] for index in range(3)}
    found = phrases(candidates(records(SENSOR_TITLES, keywords=keywords), [], []))
    assert "telemetry" in found and "methodology" not in found


def test_a_longer_author_keyword_is_not_a_candidate():
    long_one = "energy aware duty cycle scheduling policy"
    keywords = {index: [long_one] for index in range(3)}
    assert long_one not in phrases(candidates(records(SENSOR_TITLES, keywords=keywords), [], []))


def test_the_candidates_are_ordered_by_frequency_then_alphabetically_and_capped():
    rows = records(SENSOR_TITLES + MOLECULAR_TITLES + SENSOR_TITLES[:1])
    found = candidates(rows, [], [])
    assert found == sorted(found, key=lambda c: (-c.document_frequency, c.phrase))
    assert len(found) <= MAX_PROBED_PHRASES


def test_the_order_does_not_follow_the_order_the_records_arrived_in():
    rows = records(SENSOR_TITLES + MOLECULAR_TITLES)
    assert candidates(rows, [], []) == candidates(list(reversed(rows)), [], [])


# ---- the field probe ------------------------------------------------------------------
def vocabulary(setting=("sensor network",), task=("packet size",)):
    terms = [{"phrase": phrase, "block": "setting", "origin": "question", "root": phrase, "in_query": "phrase",
              "phrase_count": 100, "root_count": None, "and_only": False, "dropped": None} for phrase in setting]
    terms += [{"phrase": phrase, "block": "task", "origin": "question", "root": phrase, "in_query": "phrase",
               "phrase_count": 100, "root_count": None, "and_only": False, "dropped": None} for phrase in task]
    return {"terms": terms, "claim_words": [], "exclusion_words": []}


def counter(values, seen=None):
    async def count(query):
        if seen is not None:
            seen.append(query)
        return values.get(query, 0)
    return count


def probe_queries(phrase):
    return f'"{phrase}"', f'"{phrase}" AND ("sensor network")'


def found(*pairs):
    return [Candidate(phrase, frequency, ("title",)) for phrase, frequency in pairs]


def test_a_phrase_used_in_the_field_is_accepted():
    alone, scoped = probe_queries("duty cycle")
    result = asyncio.run(expand(vocabulary(), found(("duty cycle", 5)), counter({alone: 100, scoped: 40})))
    assert result["terms"] == ["duty cycle"]
    row = result["candidates"][0]
    assert (row["phrase_count"], row["field_count"], row["accepted"], row["reason"]) == (100, 40, True, None)
    assert [probe["query"] for probe in result["probes"]] == [alone, scoped]


def test_too_few_records_in_the_field_refuse_the_phrase():
    alone, scoped = probe_queries("duty cycle")
    result = asyncio.run(expand(vocabulary(), found(("duty cycle", 5)), counter({alone: 30, scoped: MIN_FIELD_COUNT - 1})))
    assert result["terms"] == [] and result["candidates"][0]["reason"] == "below_field_count"


def test_a_phrase_the_field_holds_only_a_small_share_of_is_refused():
    alone, scoped = probe_queries("duty cycle")
    result = asyncio.run(expand(vocabulary(), found(("duty cycle", 5)), counter({alone: 10_000, scoped: 100})))
    assert result["terms"] == [] and result["candidates"][0]["reason"] == "below_field_share"


def test_a_count_that_could_not_be_read_refuses_the_phrase():
    """A phrase from the data is not the user's own words: an unknown count is no evidence for it."""
    async def count(query):
        return None

    result = asyncio.run(expand(vocabulary(), found(("duty cycle", 5)), count))
    assert result["terms"] == [] and result["candidates"][0]["reason"] == "count_unknown"


def test_a_vocabulary_with_only_one_queried_block_is_skipped_without_a_single_count():
    seen = []
    one_block = vocabulary(task=())
    result = asyncio.run(expand(one_block, found(("duty cycle", 5)), counter({}, seen)))
    assert result["skipped"] == "single_block" and result["terms"] == [] and seen == []


def test_no_more_than_the_maximum_terms_are_accepted_and_the_rest_are_not_probed():
    pool = found(*[(f"phrase {index:02d}", 10) for index in range(MAX_EXPANSION_TERMS + 3)])
    values = {query: 100 for candidate in pool for query in probe_queries(candidate.phrase)}
    seen = []
    result = asyncio.run(expand(vocabulary(), pool, counter(values, seen)))
    assert len(result["terms"]) == MAX_EXPANSION_TERMS
    assert [row["reason"] for row in result["candidates"][MAX_EXPANSION_TERMS:]] == ["not_probed"] * 3
    assert len(seen) == 2 * MAX_EXPANSION_TERMS


def test_the_second_round_vocabulary_keeps_the_setting_block_and_replaces_the_task_block():
    built = second_round_vocabulary(vocabulary(), ["duty cycle"])
    assert [(term["phrase"], term["block"], term["in_query"]) for term in built["terms"]] == [
        ("sensor network", "setting", "phrase"), ("duty cycle", "task", "phrase")]


# ---- the stored column ----------------------------------------------------------------
@pytest.fixture
def store(tmp_path):
    connection = db.connect(tmp_path / "library.sqlite")
    db.migrate(connection)
    yield Store(connection)
    connection.close()


def provider_record(keywords, doi="10.1/synth.1"):
    return ProviderRecord(
        provider_record_id=f"rec-{doi}", title="SYNTHETIC duty cycle scheduling", authors=[], year=2026, venue=None,
        publication_type=None, doi=doi, landing_url=None, oa_pdf_url=None, oa_pdf_version=None, version_label=None,
        abstract=None, abstract_origin=None, identifiers={}, raw={}, author_keywords=keywords,
    )


def stored_keywords(store, svid):
    row = store.conn.execute("SELECT author_keywords_json FROM source_versions WHERE id = ?", (svid,)).fetchone()
    return json.loads(row[0]) if row[0] else None


def test_the_author_keywords_of_a_new_record_are_stored(store):
    svid, _ = store.upsert_provider_source("ieee_xplore", provider_record(["duty cycle", "energy harvesting"]), None)
    assert stored_keywords(store, svid) == ["duty cycle", "energy harvesting"]


def test_a_second_provider_does_not_overwrite_a_filled_column(store):
    svid, _ = store.upsert_provider_source("ieee_xplore", provider_record(["duty cycle"]), None)
    again, created = store.upsert_provider_source("pubmed", provider_record(["release scheduling"]), None)
    assert (again, created) == (svid, False)
    assert stored_keywords(store, svid) == ["duty cycle"]


def test_a_provider_without_author_keywords_leaves_the_column_empty_for_a_later_one(store):
    svid, _ = store.upsert_provider_source("openalex", provider_record([]), None)
    assert stored_keywords(store, svid) is None
    store.upsert_provider_source("pubmed", provider_record(["release scheduling"]), None)
    assert stored_keywords(store, svid) == ["release scheduling"]


def test_a_research_with_no_expansion_step_yields_nothing(store):
    rid = store.create_research("SYNTHETIC question?", "academic", "standard", ["openalex"], "fake", "m", "en",
                                search_workflow="sw")
    assert term_yields(store, rid, 1) == []


# ---- what each term brought in ---------------------------------------------------------
def candidate_record(number, title, keywords=(), doi=None):
    return ProviderRecord(
        provider_record_id=f"W{number}", title=title, authors=[], year=2026, venue=None, publication_type=None,
        doi=doi or f"10.1/synth.{number}", landing_url=None, oa_pdf_url=None, oa_pdf_version=None,
        version_label=None, abstract=None, abstract_origin=None, identifiers={}, raw={},
        author_keywords=list(keywords),
    )


def searched(store, rid, run_id, records):
    step = store.step(run_id, "search:0", "provider_search:openalex")
    store.record_search(dict(
        research_id=rid, run_id=run_id, step_id=step["id"], scope_revision=1, provider="openalex", query_text="q",
        request_description="GET test", access_mode="keyless", status="completed", delivery_class=None,
        result_count=len(records), provider_total=len(records), page_limit=25, error_json=None, raw_payload_path=None,
    ), "openalex", records, None, step["id"], "succeeded", step_output={"status": "completed"})


def research_with_records(store, records):
    rid = store.create_research("SYNTHETIC packet size in sensor networks?", "academic", "standard", ["openalex"],
                                "fake", "m", "en", search_workflow="sw")
    run = store.create_run(rid, "discovery", {"max_model_calls": 4, "max_provider_requests": 4, "max_candidates": 50,
                                              "max_answer_passages": 8}, None)
    searched(store, rid, run["id"], records)
    return rid


def yields_of(store, rid, rows):
    return {row["phrase"]: (row["records"], row["included"]) for row in count_yields(store, rid, 1, rows)}


def test_a_term_is_counted_in_the_form_it_entered_the_query_in(store):
    rid = research_with_records(store, [
        candidate_record(1, "Duty cycle scheduling in wireless sensor networks"),
        candidate_record(2, "A sensor network survey", keywords=["duty cycle"]),
    ])
    rooted = {"phrase": "wireless sensor networks", "form": "sensor", "origin": "question", "block": "setting"}
    whole = {"phrase": "wireless sensor networks", "form": "wireless sensor networks", "origin": "question",
             "block": "setting"}
    from_data = {"phrase": "duty cycle", "form": "duty cycle", "origin": "data", "block": "task"}
    counted = yields_of(store, rid, [rooted, whole, from_data])
    assert counted["wireless sensor networks"] == (1, 0)  # the whole phrase is in one title only
    assert yields_of(store, rid, [rooted])["wireless sensor networks"] == (2, 0)  # the root word is in both
    assert counted["duty cycle"] == (2, 0)  # a title and an author keyword


def test_two_versions_of_one_work_count_once_and_a_term_no_record_holds_stays_at_zero(store):
    title = "Duty cycle scheduling in wireless sensor networks"
    rid = research_with_records(store, [candidate_record(1, title, doi="10.1/a"),
                                        candidate_record(2, title, doi="10.1/a")])  # one DOI: one work
    rows = [{"phrase": "duty cycle", "form": "duty cycle", "origin": "data", "block": "task"},
            {"phrase": "molecular channel", "form": "molecular channel", "origin": "data", "block": "task"}]
    assert yields_of(store, rid, rows) == {"duty cycle": (1, 0), "molecular channel": (0, 0)}


def test_including_a_record_raises_the_included_count_of_the_terms_it_holds(store):
    rid = research_with_records(store, [candidate_record(1, "Duty cycle scheduling in wireless sensor networks"),
                                        candidate_record(2, "A sensor network survey")])
    row = {"phrase": "duty cycle", "form": "duty cycle", "origin": "data", "block": "task"}
    assert yields_of(store, rid, [row])["duty cycle"] == (1, 0)
    svid = store.candidates(rid, 1)[0]["source_version_id"]
    store.set_user_selection(rid, svid, "included", 1, "SYNTHETIC decision")
    assert yields_of(store, rid, [row])["duty cycle"] == (1, 1)


def test_the_yield_rows_are_the_terms_the_frozen_protocol_names(store):
    rid = research_with_records(store, [candidate_record(1, "Duty cycle scheduling in wireless sensor networks")])
    built = vocabulary(setting=("wireless sensor networks",), task=("packet size",))
    store.freeze_protocol(rid, 1, {"search_workflow": "sw", "vocabulary": built["terms"],
                                   "expansion": {"terms": ["duty cycle"]}})
    rows = term_yields(store, rid, 1)
    assert [(row["phrase"], row["origin"], row["block"]) for row in rows] == [
        ("wireless sensor networks", "question", "setting"), ("packet size", "question", "task"),
        ("duty cycle", "data", "task")]
    assert [row["records"] for row in rows] == [1, 0, 1]


def test_a_later_run_does_not_learn_from_the_records_an_earlier_expansion_brought_in(store):
    """A second discovery run of the same scope reads the same candidate pool. Were the expansion arm's own records
    in it, each run would learn from what the last one added and the search would drift away from the question."""
    from deixis.workflow.expansion import first_round_records
    rid = research_with_records(store, [candidate_record(1, "SYNTHETIC first round record")])
    run_id = store.conn.execute("SELECT id FROM runs WHERE research_id = ?", (rid,)).fetchone()["id"]
    expansion = store.step(run_id, "vocabulary_expansion", "code:vocabulary_expansion")
    store.finish_step(expansion["id"], "succeeded", output={
        "expansion": {"terms": ["SYNTHETIC phrase"]}, "queries": [{"provider_id": "openalex", "query_text": "second round q"}]})
    step = store.step(run_id, "search:1", "provider_search:openalex")
    store.record_search(dict(
        research_id=rid, run_id=run_id, step_id=step["id"], scope_revision=1, provider="openalex",
        query_text="second round q", request_description="GET test", access_mode="keyless", status="completed",
        delivery_class=None, result_count=1, provider_total=1, page_limit=25, error_json=None, raw_payload_path=None,
    ), "openalex", [candidate_record(2, "SYNTHETIC record only the expansion arm found")], None, step["id"], "succeeded",
        step_output={"status": "completed"})
    assert [r["title"] for r in first_round_records(store, rid, 1)] == ["SYNTHETIC first round record"]
