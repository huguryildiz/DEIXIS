"""What a benchmark measurement may count as found, as lost, and as neither.

A measurement that cannot identify a reference can say nothing about it: whether the search found it is a
question nobody can answer. The rules here hold that apart from a verified loss — a reference that carries a DOI
and was not found — because mixing the two reads the ratio as better than it is. They also hold apart the two
questions the design asks separately: whether the work is in the pool, and whether the version the reference
itself names was the one read.
"""

import sys
from pathlib import Path

sys.path.append(str(Path(__file__).resolve().parents[2] / "scripts" / "benchmark"))
from check import identity_state, paper_match  # noqa: E402
from common import matching_records, measurable, reference_identity, requested_records, unverified_alternates  # noqa: E402

# One work, two versions: the preprint the reference was written with and the publisher record, linked under one
# stored work. The third row is another work that happens to carry the same title.
PREPRINT = {"id": "v-arxiv", "doi": "10.48550/arXiv.2401.00001", "work_id": "w1", "title": "SYNTHETIC switch policy"}
PUBLISHER = {"id": "v-journal", "doi": "10.1117/12.2616950", "work_id": "w1", "title": "SYNTHETIC switch policy"}
NAMESAKE = {"id": "v-other", "doi": "10.9999/other", "work_id": "w2", "title": "SYNTHETIC switch policy"}
POOL = [PREPRINT, PUBLISHER, NAMESAKE]


def test_whether_a_reference_can_be_measured_is_read_from_the_reference_alone():
    """Not from any pool: a reference that carries a DOI and was not found is a verified loss, and taking it out
    of the denominator would report the search as better than it is."""
    assert reference_identity({"doi": "10.1/x"}) == "doi"
    assert reference_identity({"verified_work_ids": ["w1"]}) == "verified_work"
    assert reference_identity({"doi": "", "alternate_dois": ["10.2/y"],
                               "alternate_identity_status": "verified"}) == "verified_alternate"
    # A title is not a work identity, and neither is an alternate nobody verified.
    assert reference_identity({"title": "SYNTHETIC paper"}) is None
    assert reference_identity({"alternate_dois": ["10.2/y"]}) is None
    assert measurable({"doi": "10.1/x"}) and not measurable({"title": "SYNTHETIC paper"})
    # A DOI that does not survive normalisation is no identity either.
    assert reference_identity({"doi": "   "}) is None


def test_an_unverified_alternate_is_named_but_never_matched_on():
    """So a person can verify it and the next reading of the same snapshot counts the version it points at."""
    paper = {"doi": "10.48550/arXiv.2401.00001", "alternate_dois": ["10.1117/12.2616950"]}
    assert unverified_alternates(paper) == ["10.1117/12.2616950"]
    assert [r["id"] for r in requested_records(POOL, paper)] == ["v-arxiv"]
    verified = paper | {"alternate_identity_status": "verified"}
    assert unverified_alternates(verified) == []
    assert [r["id"] for r in requested_records(POOL, verified)] == ["v-arxiv", "v-journal"]


def test_the_work_in_the_pool_and_the_version_the_reference_asks_for_are_two_measurements():
    """The design's Iñesta case: the reference carries the preprint's DOI and the pool holds both versions of
    the same work, so the work was found while the version asked for may not be the one read."""
    paper = {"key": "k", "doi": "10.48550/arXiv.2401.00001", "title": "SYNTHETIC switch policy"}
    matched, possible, asked = paper_match(POOL, paper)
    assert matched == ["v-arxiv", "v-journal"] and asked == ["v-arxiv"] and possible == []
    # The publisher record alone answers the work, not the version the reference names.
    matched, possible, asked = paper_match([PUBLISHER], paper)
    assert matched == [] and asked == [] and possible == ["v-journal"]
    assert identity_state(paper, matched, possible) == "title_match_requires_adjudication"


def test_a_reference_with_no_identity_is_counted_as_neither_found_nor_lost():
    nameless = {"key": "k", "title": "SYNTHETIC switch policy"}
    matched, possible, asked = paper_match([], nameless)
    assert identity_state(nameless, matched, possible) == "unresolvable"
    # With a title candidate it is the adjudication state, which is still not a loss.
    matched, possible, asked = paper_match([NAMESAKE], nameless)
    assert possible == ["v-other"] and identity_state(nameless, matched, possible) == \
        "title_match_requires_adjudication"
    # A reference that carries a DOI and matched nothing is a verified loss, which a denominator must keep.
    lost = {"key": "k", "doi": "10.5555/missing"}
    matched, possible, asked = paper_match(POOL, lost)
    assert matched == [] and identity_state(lost, matched, possible) == "not_found" and measurable(lost)


def test_a_title_only_candidate_is_never_a_work_match():
    """`matching_records` answers "is this work in the pool", and a namesake title is not an answer to it."""
    assert matching_records([NAMESAKE], {"title": "SYNTHETIC switch policy"}) == []
    assert matching_records(POOL, {"doi": "10.1117/12.2616950"}) == [PREPRINT, PUBLISHER]


def test_the_whole_report_is_built_on_a_snapshot_and_says_what_it_could_not_measure(tmp_path):
    """One pass over a SYNTHETIC snapshot: the work is in the pool through its publisher version while the
    reference names the preprint, and a second reference carries no identity at all. The report must build, keep
    the two apart, and read its ratio over the references it can identify."""
    import json
    import sqlite3

    from deixis.storage import db

    import check

    path = tmp_path / "library.sqlite"
    conn = db.connect(path)
    db.migrate(conn)
    question = "SYNTHETIC switch policy question"
    now = "2026-11-10T00:00:00Z"
    payload = {"question": {"text": question}, "sources": [{"source_id": "v-journal"}],
               "passages": [{"passage_id": "p1", "source_id": "v-journal", "text": "SYNTHETIC passage",
                             "reading_depth": "fulltext"}]}
    with conn:
        conn.execute("INSERT INTO researches (id, title, created_at, updated_at) VALUES ('r1', ?, ?, ?)",
                     (question, now, now))
        conn.execute("INSERT INTO runs (id, research_id, scope_revision, kind, status, stage, budget_json,"
                     " created_at, updated_at) VALUES ('run1', 'r1', 1, 'answer', 'completed', 'answer', '{}',"
                     " ?, ?)", (now, now))
        conn.execute("INSERT INTO run_steps (id, run_id, operation_key, kind, status) VALUES"
                     " ('s1', 'run1', 'answer', 'model_step', 'succeeded')")
        conn.execute("INSERT INTO step_inputs (id, step_id, research_id, run_id, attempt, task_type,"
                     " scope_revision, skill_package_hash, payload_json, base_instructions,"
                     " developer_instructions, user_message, output_schema_json, created_at)"
                     " VALUES ('i1', 's1', 'r1', 'run1', 1, 'answer', 1, 'SYNTHETIC', ?, '', '', '', '{}', ?)",
                     (json.dumps(payload), now))
        conn.execute("INSERT INTO answers (id, research_id, run_id, step_id, step_input_id, scope_revision,"
                     " status, draft_json, validation_json, created_at)"
                     " VALUES ('a1', 'r1', 'run1', 's1', 'i1', 1, 'structurally_valid', '{\"claims\": []}',"
                     " '{}', ?)", (now,))
        conn.execute("INSERT INTO works (id, created_at) VALUES ('w1', ?)", (now,))
        conn.execute("INSERT INTO source_versions (id, work_id, title, year, doi, origin, created_at)"
                     " VALUES ('v-journal', 'w1', 'SYNTHETIC switch policy', 2024, '10.1117/12.2616950',"
                     " 'provider', ?)", (now,))
        conn.execute("INSERT INTO candidates (id, research_id, source_version_id, rank, created_at,"
                     " scope_revision) VALUES ('c1', 'r1', 'v-journal', 1, ?, 1)", (now,))
    conn.close()

    bench = {"question": question, "name": "SYNTHETIC", "question_sha256": "SYNTHETIC",
             "papers": [{"key": "asked-as-preprint", "label": "ilgili", "doi": "10.48550/arXiv.2401.00001",
                         "title": "SYNTHETIC switch policy",
                         "alternate_dois": ["10.1117/12.2616950"]},
                        {"key": "nameless", "label": "ilgili", "title": "SYNTHETIC other paper"}]}
    read = sqlite3.connect(path.resolve().as_uri() + "?mode=ro", uri=True)
    read.row_factory = sqlite3.Row
    report = check.measure(read, "r1", "a1", bench)
    read.close()
    rows = {r["target_key"]: r for r in report["papers"]}

    preprint = rows["asked-as-preprint"]
    # Its unverified alternate is named, never matched on: without a verified link the publisher record is only a
    # title candidate, so nothing is claimed as found.
    assert preprint["unverified_alternates"] == ["10.1117/12.2616950"]
    assert preprint["identity_status"] == "title_match_requires_adjudication"
    assert preprint["found"] is False and preprint["requested_version_in_pool"] is False
    assert preprint["measurable"] is True and preprint["identity_source"] == "doi"

    nameless = rows["nameless"]
    assert nameless["identity_status"] == "unresolvable" and nameless["measurable"] is False

    layer = report["coverage"]["all"]
    # Both references are relevant, but only one can be measured at all, and the report says so rather than
    # reading one loss as two.
    assert layer["denominator"] == 2 and layer["measurable_denominator"] == 1
    assert layer["counts"]["identity_unresolved"] == 1 and layer["counts"]["measurable"] == 1
    assert layer["counts"]["title_match_requires_adjudication"] == 1
    assert layer["measurable_ratios"]["found"] == 0.0


def test_an_identity_that_does_not_survive_normalisation_matches_nothing():
    """A blank DOI would otherwise match every version that stores no DOI, so a reference nobody can identify
    would be reported as found."""
    pool = [{"id": "v-no-doi", "doi": None, "work_id": "w9", "title": "SYNTHETIC other"},
            {"id": "v-doi", "doi": "10.2/b", "work_id": "w9", "title": "SYNTHETIC other"}]
    blank = {"key": "k", "doi": "   ", "title": "SYNTHETIC target"}
    matched, possible, asked = paper_match(pool, blank)
    assert matched == [] and asked == [] and not measurable(blank)
    assert identity_state(blank, matched, possible) == "unresolvable"


def test_a_reference_that_names_a_doi_asks_for_that_record_not_every_sibling():
    """Its work identity covers the siblings, which is the other question; reading only a sibling is not reading
    the version the reference asked for."""
    pool = [{"id": "v-sibling", "doi": "10.1/a", "work_id": "w9", "title": "SYNTHETIC other"},
            {"id": "v-asked", "doi": "10.2/b", "work_id": "w9", "title": "SYNTHETIC other"}]
    both = {"key": "k", "doi": "10.2/b", "verified_work_ids": ["w9"]}
    matched, possible, asked = paper_match(pool, both)
    assert matched == ["v-sibling", "v-asked"] and asked == ["v-asked"]
    # With no DOI of its own, the work identity is the only thing it names, so every version of it is asked for.
    work_only = {"key": "k", "verified_work_ids": ["w9"]}
    assert [r["id"] for r in requested_records(pool, work_only)] == ["v-sibling", "v-asked"]
