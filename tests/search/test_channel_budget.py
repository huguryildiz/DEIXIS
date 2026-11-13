"""The channel budget: what a depth reserves, when a ready page is recorded, and what each request is counted as.

Synthetic throughout — no live app, provider or model. What is guarded here is that nothing the person sees comes
from which reply happened to come back first: the record that heads a work, the search a candidate names and the
set the list is computed from are all read from places the requests themselves stored.
"""

from types import SimpleNamespace

import pytest

from deixis.providers.common import ProviderRecord
from deixis.storage import db
from deixis.workflow.run import fast_path
from deixis.workflow.run.store import Store
from deixis.workflow.search import search as fast_search, small_batch
from deixis.domain.rules import TEST_EFFORT_BUDGETS
from overlap_flow_helpers import discover, output
from test_fast_path_clock import FakeClock
from test_small_batch_flow import app_for, client_of

QUESTION = "SYNTHETIC channel budget question"
DOI = "10.9999/synthetic.1"


def _library(tmp_path, name, effort="detailed"):
    conn = db.connect(tmp_path / name)
    db.migrate(conn)
    clock = FakeClock()
    store = Store(conn, clock)
    clock.store = store
    rid = store.create_research(QUESTION, "academic", effort, ["openalex", "semantic_scholar"], "fake", "fake-model", "en")
    budget = small_batch.freeze_budget(TEST_EFFORT_BUDGETS[effort].__dict__, effort, "off")
    # Bulk reservations are exercised on the older Detailed policy that sent bulk requests.
    budget["fast_path"] = fast_path.freeze_budget(budget, effort, uniform_search=False)
    run = store.create_run(rid, "discovery", budget, None)
    store.update_run(run["id"], status="running")
    return SimpleNamespace(store=store, conn=conn, clock=clock, rid=rid, run=store.run(run["id"]))


@pytest.fixture
def lab(tmp_path):
    lib = _library(tmp_path, "library.sqlite")
    yield lib
    lib.conn.close()


def _record(identity, *, title=None, version="submittedVersion", doi=None, authors=None, abstract=None,
            scheme="openalex"):
    return ProviderRecord(provider_record_id=identity, title=title or f"SYNTHETIC {identity}", authors=authors or [],
                          year=2026, venue=None, publication_type="article", doi=doi, landing_url=None,
                          oa_pdf_url=None, oa_pdf_version=None, version_label=version,
                          abstract=abstract or f"SYNTHETIC abstract {identity}",
                          abstract_origin="provider_openalex_inverted_index", identifiers={scheme: identity},
                          raw={"id": identity})


def _write(lib, provider, records, *, key, page_limit=100, rank=0, step=None):
    """One answered request of this run, written the way `flow._record_search` writes it, with its admission place."""
    operation = step or f"search:{provider}:{key[1]}"
    row = lib.store.step(lib.run["id"], operation, f"provider_search:{provider}")
    lib.store.start_step(row["id"])
    return lib.store.record_search(
        dict(research_id=lib.rid, run_id=lib.run["id"], step_id=row["id"], scope_revision=lib.run["scope_revision"],
             provider=provider, query_text="SYNTHETIC query", request_description="SYNTHETIC request",
             access_mode="keyless", status="completed", delivery_class="rejected_not_executed",
             result_count=len(records), provider_total=len(records), page_limit=page_limit, error_json=None,
             raw_payload_path=None, request_class=key[0], request_index=key[1], returned_count=len(records)),
        provider, records, None, row["id"], "succeeded",
        step_output={"status": "completed", "result_count": len(records),
                     "fast_path_request": {"class": key[0], "request_index": key[1], "limit": page_limit}},
        first_rank=rank)


# --- what a depth reserves ------------------------------------------------------------------------------------

def test_a_depth_reserves_nothing_for_a_bulk_request_the_plan_does_not_name(lab):
    queries = [{"provider_id": "openalex", "query_text": "SYNTHETIC alpha"}]
    plan = fast_search.build_plan(lab.store, lab.run, lab.store.scope(lab.rid), queries)
    # The depth would pay for a bulk request, but this plan names none: the records stay with the keyword queries
    # and the reason is recorded, so a reservation that buys nothing is not kept quietly.
    assert plan["s2_reserved"] == 0 and plan["s2_skipped"] == "not_planned"
    assert plan["keyword_cap"] == lab.run["budget"]["fast_path"]["keyword_record_cap"]


def test_a_bulk_request_the_plan_names_takes_its_records_off_the_keyword_cap(lab):
    queries = [{"provider_id": "openalex", "query_text": "SYNTHETIC alpha"},
               {"provider_id": "semantic_scholar", "query_text": "SYNTHETIC bulk", "endpoint": "bulk"}]
    plan = fast_search.build_plan(lab.store, lab.run, lab.store.scope(lab.rid), queries)
    assert plan["s2_reserved"] == fast_search.S2_RESERVED_RECORDS and "s2_skipped" not in plan
    assert plan["keyword_cap"] == (lab.run["budget"]["fast_path"]["keyword_record_cap"]
                                   - fast_search.S2_RESERVED_RECORDS)


def test_a_provider_the_person_left_out_reserves_nothing_and_says_so(lab):
    scope = dict(lab.store.scope(lab.rid))
    scope["user_plan"] = {"providers": ["openalex"]}
    queries = [{"provider_id": "openalex", "query_text": "SYNTHETIC alpha"},
               {"provider_id": "semantic_scholar", "query_text": "SYNTHETIC bulk", "endpoint": "bulk"}]
    plan = fast_search.build_plan(lab.store, lab.run, scope, queries)
    assert plan["s2_reserved"] == 0 and plan["s2_skipped"] == "excluded_by_user"


# --- the merge does not follow which reply came back first ----------------------------------------------------

@pytest.mark.parametrize("second_first", [False, True])
def test_the_candidate_names_the_search_admitted_first_whichever_was_written_first(tmp_path, second_first):
    """Two requests find the same record at the same place; the candidate names the one admitted first.

    Which reply came back first decided this before, and in Deep mode the order was held by making a ready keyword
    page wait for the Semantic Scholar slot. The page no longer waits, so the choice is read from the place each
    request was admitted at instead.
    """
    lib = _library(tmp_path, f"order-{second_first}.sqlite")
    early = ("openalex", (1, 1))
    late = ("openalex", (1, 2))
    first, second = (late, early) if second_first else (early, late)
    for provider, key in (first, second):
        _write(lib, provider, [_record("W1", doi=DOI)], key=key, step=f"search:openalex:{key[1]}")
    candidate = lib.conn.execute("SELECT search_run_id, rank FROM candidates WHERE research_id = ?",
                                 (lib.rid,)).fetchone()
    named = lib.conn.execute("SELECT request_index FROM search_runs WHERE id = ?",
                             (candidate["search_run_id"],)).fetchone()
    assert (named["request_index"], candidate["rank"]) == (1, 0)
    lib.conn.close()


def test_a_better_place_still_wins_over_the_request_admitted_first(tmp_path):
    """The admission place only breaks a tie: a request that found the record higher in its own query still wins."""
    lib = _library(tmp_path, "better-place.sqlite")
    _write(lib, "openalex", [_record("W0"), _record("W1", doi=DOI)], key=(1, 1), step="search:openalex:1")
    _write(lib, "openalex", [_record("W1", doi=DOI)], key=(1, 2), step="search:openalex:2")
    candidate = lib.conn.execute("SELECT search_run_id, rank FROM candidates c JOIN source_versions v"
                                 " ON v.id = c.source_version_id WHERE c.research_id = ? AND v.doi = ?",
                                 (lib.rid, DOI)).fetchone()
    named = lib.conn.execute("SELECT request_index FROM search_runs WHERE id = ?",
                             (candidate["search_run_id"],)).fetchone()
    # The second request found it first in its own query (place 0 against place 1), so it is the one named.
    assert (named["request_index"], candidate["rank"]) == (2, 0)
    lib.conn.close()


@pytest.mark.parametrize("second_first", [False, True])
def test_two_versions_of_one_work_give_the_same_head_whichever_reply_came_back_first(tmp_path, second_first):
    """Two arms bring two versions of one work; the version the research shows for it is the same either way.

    The versions have their own DOIs, so they are stored apart and the identity rule joins them into one work. Both
    are candidates of the research, and which of them heads the work was the order they were written in before: the
    request's admitted place decides it now, so a slow arm answering first changes nothing the person reads.
    """
    lib = _library(tmp_path, f"two-versions-{second_first}.sqlite")
    title = "SYNTHETIC acoustic routing in an underwater sensor network"
    abstract = "SYNTHETIC abstract shared by both stored versions of this one work."
    early = ("openalex", (1, 1), _record("W1", title=title, abstract=abstract, authors=["Yildiz, H."],
                                         doi="10.9999/synthetic.early"))
    late = ("semantic_scholar", (1, 2), _record("S1", title=title, abstract=abstract, authors=["Yildiz, H."],
                                                doi="10.9999/synthetic.late", scheme="semantic_scholar"))
    for provider, key, record in ((late, early) if second_first else (early, late)):
        _write(lib, provider, [record], key=key, step=f"search:{provider}")
    versions = [r[0] for r in lib.conn.execute(
        "SELECT v.id FROM candidates c JOIN source_versions v ON v.id = c.source_version_id WHERE c.research_id = ?",
        (lib.rid,))]
    works = {lib.store.source(svid)["work_id"] for svid in versions}
    # Two stored versions, each a candidate, joined into the one work: the choice this test is about is real.
    assert len(versions) == 2 and len(works) == 1
    (head,) = lib.store.work_heads(lib.rid).values()
    assert lib.store.source(head)["doi"] == "10.9999/synthetic.early"
    counted = [row["works_new"] for row in lib.conn.execute("SELECT works_new FROM search_runs")]
    # One work, counted once however the two replies were ordered: the identity rule joins the two versions, and
    # the request that found the second one is recorded as having added nothing. Which of the two is credited is
    # the one that wrote first, which is what "what this request brought the pool" means.
    assert sorted(counted) == [0, 1]
    lib.conn.close()


def test_a_record_the_person_added_keeps_its_place_when_a_search_finds_it_later(tmp_path):
    """A member no search brought is placed by when it was added, and a later search does not move it.

    Two versions of one work are in the research before any search: the first added heads the work. The place a
    search request was admitted at decides between records a search brought, so finding one of these again must
    leave the head where the person's own order put it.
    """
    lib = _library(tmp_path, "added-by-hand.sqlite")
    first = _record("U1", title="SYNTHETIC uploaded version", doi="10.9999/synthetic.first")
    second = _record("U2", title="SYNTHETIC uploaded version", doi="10.9999/synthetic.second",
                     scheme="semantic_scholar")
    svids = []
    for record in (first, second):
        svid, _ = lib.store.upsert_provider_source("openalex" if record is first else "semantic_scholar", record, None)
        svids.append(svid)
        lib.clock.advance(10)
    with db.transaction(lib.conn):  # the two are one work, as the identity rule would have left them
        lib.store._join_works(lib.store.source(svids[0])["work_id"], lib.store.source(svids[1])["work_id"])
    for minute, svid in enumerate(svids):
        lib.store.add_to_corpus(lib.rid, svid, "user_upload")
        # The person added one and then the other; the written times say so whatever the machine's clock did
        # inside one millisecond.
        lib.conn.execute("UPDATE corpus_memberships SET created_at = ? WHERE research_id = ? AND source_version_id = ?",
                         (f"2026-11-10T10:0{minute}:00", lib.rid, svid))
    before = lib.store.work_heads(lib.rid)
    assert before == {lib.store.source(svids[0])["work_id"]: svids[0]}
    _write(lib, "semantic_scholar", [second], key=(1, 1), step="search:semantic_scholar")
    assert lib.store.work_heads(lib.rid) == before
    lib.conn.close()


# --- what each request is counted as --------------------------------------------------------------------------

def test_asked_returned_and_works_new_are_counted_apart(lab):
    srid = _write(lab, "openalex", [_record("W1"), _record("W2")], key=(1, 1), page_limit=100)
    row = dict(lab.conn.execute("SELECT * FROM search_runs WHERE id = ?", (srid,)).fetchone())
    # Asked for a hundred, two came back, two works were new: three different numbers, none standing for another.
    assert (row["page_limit"], row["returned_count"], row["result_count"]) == (100, 2, 2)
    assert (row["works_new"], row["works_found_removed"]) == (2, 0)
    # A second request that brings the same works adds none: the counter is works, not records.
    again = _write(lab, "openalex", [_record("W1"), _record("W2")], key=(1, 2), step="search:openalex:again")
    row = dict(lab.conn.execute("SELECT * FROM search_runs WHERE id = ?", (again,)).fetchone())
    assert (row["result_count"], row["works_new"]) == (2, 0)


def test_a_work_the_person_removed_is_counted_apart_from_a_new_one(lab):
    _write(lab, "openalex", [_record("W1")], key=(1, 1))
    svid = lab.conn.execute("SELECT source_version_id FROM corpus_memberships WHERE research_id = ?",
                            (lab.rid,)).fetchone()[0]
    lab.store.update_run(lab.run["id"], status="completed")
    lab.store.remove_sources(lab.rid, [svid], note="SYNTHETIC removal")
    srid = _write(lab, "openalex", [_record("W1"), _record("W2")], key=(1, 2), step="search:openalex:again")
    row = dict(lab.conn.execute("SELECT * FROM search_runs WHERE id = ?", (srid,)).fetchone())
    # One work the person had removed and found again, one really new: the two are never added together.
    assert (row["works_new"], row["works_found_removed"]) == (1, 1)


def test_a_request_that_did_not_answer_counts_nothing(lab):
    row = lab.store.step(lab.run["id"], "search:openalex:failed", "provider_search:openalex")
    lab.store.start_step(row["id"])
    srid = lab.store.record_search(
        dict(research_id=lab.rid, run_id=lab.run["id"], step_id=row["id"], scope_revision=1, provider="openalex",
             query_text="SYNTHETIC query", request_description="SYNTHETIC request", access_mode="keyless",
             status="timeout", delivery_class="after_send_unknown", result_count=0, provider_total=None,
             page_limit=100, error_json=None, raw_payload_path=None, request_class=1, request_index=1),
        "openalex", [], None, row["id"], "outcome_unknown", step_output={"status": "timeout", "result_count": 0})
    stored = dict(lab.conn.execute("SELECT * FROM search_runs WHERE id = ?", (srid,)).fetchone())
    # Nothing came back, so there is no count to keep: the columns stay empty rather than reading as zero returned.
    assert stored["returned_count"] is None
    assert (stored["works_new"], stored["works_found_removed"]) == (0, 0)


# --- what the list was computed after --------------------------------------------------------------------------

def test_the_cutoff_record_names_the_requests_the_pool_was_read_after(lab):
    srid = _write(lab, "openalex", [_record("W1")], key=(1, 1))
    pending = lab.store.step(lab.run["id"], "search:openalex:page:1", "provider_search:openalex")
    lab.store.start_step(pending["id"])
    record = small_batch.cutoff_record(lab.store, lab.run)
    # What the list is made of is this set; a request still unwritten at that moment is named, not counted in.
    assert record == {"searches": [srid], "late": [], "unfinished": ["search:openalex:page:1"]}


def test_the_frozen_list_carries_the_cutoff_it_was_read_after(tmp_path, monkeypatch):
    """A whole synthetic run: the list the run froze keeps the set its pool was read after, not a recomputed one."""
    app, _ = app_for(tmp_path, monkeypatch, 3, reading="off")
    with client_of(app) as client:
        _, run_id, _, run = discover(client, effort="quick")
        assert run["status"] == "completed", run
        manifest = output(app.state.store, run_id, small_batch.LIST_KEY)["manifest"]
        rows = sorted(row[0] for row in app.state.store.conn.execute(
            "SELECT sr.id FROM search_runs sr JOIN run_steps s ON s.id = sr.step_id"
            " WHERE sr.run_id = ? AND s.kind LIKE 'provider_search:%'", (run_id,)))
    assert rows and manifest["cutoff"] == {"searches": rows, "late": [], "unfinished": []}
