"""The probe set, the arm rows and the signal table of an `sw` research (slice 19).

Records, criteria, searches and ranking rows are SYNTHETIC and from two fields (diffusion channel scheduling,
greenhouse irrigation), written straight through the store the way the runs write them, without a model or a request.
Passing shows what the tables count and from which stored rows; it says nothing about whether a signal or an arm is
useful, and no number here judges one.
"""

from __future__ import annotations

import pytest

from deixis.storage import db
from deixis.workflow import probes, queue, views
from deixis.workflow.decisions import DecisionStore
from deixis.workflow.store import Store
from test_queue import Lib, provider_record, queued


@pytest.fixture
def store(tmp_path):
    connection = db.connect(tmp_path / "library.sqlite")
    db.migrate(connection)
    yield Store(connection)
    connection.close()


class Probe(Lib):
    """A `Lib` whose searches can be keyed, rounded and chained, and whose ranking steps carry rows and an output."""

    def keyed(self, key, records, provider="openalex", query="q", run=None, result_count=None):
        run = run or self.run
        revision = self.store.research(self.rid)["current_scope_revision"]
        kind = f"provider_chain:{provider}" if key.startswith("chain:") else f"provider_search:{provider}"
        step = self.store.step(run, key, kind)
        self.store.record_search(
            dict(research_id=self.rid, run_id=run, step_id=step["id"], scope_revision=revision, provider=provider,
                 query_text=query, request_description="GET test", access_mode="keyless", status="completed",
                 delivery_class=None, result_count=len(records) if result_count is None else result_count,
                 provider_total=len(records), page_limit=25, error_json=None, raw_payload_path=None),
            provider, records, None, step["id"], "succeeded", step_output={"status": "completed"})
        return [self.store.find_source_by_identifier(provider, r.provider_record_id) for r in records]

    def records(self, n, prefix="R"):
        self.n += 1
        return [provider_record(f"{prefix}{self.n}-{i}", f"SYNTHETIC {self.field['topic']} record {self.n}-{i}",
                                f"10.9999/p{self.n}.{i}") for i in range(n)]

    def card(self, queries, run=None):
        step = self.store.step(run or self.run, "protocol_approval", "code:protocol_approval")
        self.store.finish_step(step["id"], "succeeded", output={"approved": {"queries": queries}})

    def ranking(self, rows, output=None, run=None, key="ranking"):
        run = run or self.new_run("discovery")
        step = self.store.step(run, key, f"code:{key}")
        self.store.finish_step(step["id"], "succeeded", output=output or {})
        self.ds.save_ranks(step["id"], self.rid, rows)
        return run, step["id"]

    def include(self, svid):
        """Two agreeing runs included this record: the full-text decision a reading run writes."""
        self.ds.record(self.rid, svid, "all_parts_verified")
        self.ds.derive_selection(self.rid, self.work_of(svid))

    def probe(self):
        return probes.probe_set(queue.context(self.store, self.rid))

    def view(self):
        return views.research_view(self.store, self.rid)


def order_rows(svids, signal, available=True, start=1):
    return [{"source_version_id": svid, "signal": signal, "rank": float(i + start), "available": available}
            for i, svid in enumerate(svids)]


def answered(lib, answer):
    svid = queued(lib)
    queue.decide(lib.store, lib.rid, svid, answer, None, lib.row(svid)["row_token"])
    return svid


# ---- decision 1: the probe set ----------------------------------------------------------------------------------


@pytest.mark.parametrize("field", ["channels", "irrigation"])
def test_a_queue_answer_or_a_list_edit_makes_a_probe_with_its_kind(store, field):
    lib = Probe(store, field)
    queue_include, queue_not_met = answered(lib, "include"), answered(lib, "criterion_not_met")
    listed_in, listed_out = lib.work(), lib.work()
    lib.list_edit(listed_in, "included")
    lib.list_edit(listed_out, "excluded")
    found = lib.probe()
    work = lib.work_of
    assert set(found["verified"]) == {work(queue_include), work(listed_in)}
    assert found["verified"][work(queue_include)]["via"] == "queue"
    assert found["verified"][work(listed_in)]["via"] == "list"
    assert found["negatives"] == {work(queue_not_met): "criterion_not_met", work(listed_out): "not_recorded"}
    assert found["look_again"] == set() and found["included"] == {}
    shown = probes.probes_view(store, lib.rid, found)
    assert shown["negatives"] == {"criterion_not_met": 1, "not_recorded": 1, "out_of_scope": None}


def test_a_queue_include_gone_stale_is_no_probe_and_looks_again_until_a_new_list_edit(store):
    lib = Probe(store)
    svid = answered(lib, "include")
    lib.revise()
    # (i) The selection is still the user's `included`, and its link names that very version: the decision rules.
    assert lib.selection(svid) == ("included", "user")
    found = lib.probe()
    assert found["verified"] == {} and found["look_again"] == {lib.work_of(svid)}
    assert lib.view()["probes"]["look_again"] == 1
    # (ii) Under the new revision the person sets it again from the list: a new selection version with no link.
    lib.list_edit(svid, "included")
    found = lib.probe()
    assert set(found["verified"]) == {lib.work_of(svid)} and found["look_again"] == set()
    assert found["verified"][lib.work_of(svid)]["via"] == "list"


def test_not_sure_and_pdf_wrong_are_no_probe(store):
    lib = Probe(store, "irrigation")
    answered(lib, "not_sure")
    answered(lib, "pdf_wrong")
    found = lib.probe()
    assert found["verified"] == {} and found["negatives"] == {} and found["look_again"] == set()


def test_model_agreement_is_its_own_column_and_never_a_persons_probe(store):
    lib = Probe(store)
    agreed, overruled = lib.work(), lib.work()
    for svid in (agreed, overruled):
        lib.include(svid)
    lib.list_edit(overruled, "excluded")  # the person's own edit takes the work out of the agreement column
    found = lib.probe()
    assert set(found["included"]) == {lib.work_of(agreed)}
    assert found["negatives"] == {lib.work_of(overruled): "not_recorded"}
    assert lib.work_of(agreed) not in found["verified"]


def test_versions_that_disagree_are_in_no_column_and_a_read_person_file_decides_the_work(store):
    lib = Probe(store, "irrigation")
    published, preprint = lib.published("10.9999/synth.pair"), lib.preprint("10.9999/synth.pair")
    work = lib.work_of(published)
    assert lib.work_of(preprint) == work
    asset = lib.text(published, [lib.field["page"]])
    lib.ds.record(lib.rid, published, "all_parts_verified")
    lib.ds.record(lib.rid, preprint, "criterion_absent")
    found = lib.probe()
    assert work not in found["included"] and work not in found["verified"] and work not in found["negatives"]
    # The person's file on the published version was read and still holds (D100): its decision is the work's.
    revision, criterion_hash = store.criterion_key(lib.rid)
    store.conn.execute(
        "INSERT INTO person_pdf_requests (id, research_id, source_version_id, asset_id, scope_revision, criterion_hash,"
        " status, page_digest, created_at, updated_at) VALUES (?, ?, ?, ?, ?, ?, 'read', ?, ?, ?)",
        (db.new_id("ppr"), lib.rid, published, asset, revision, criterion_hash, store.asset_page_digest(asset),
         db.now(), db.now()))
    assert set(lib.probe()["included"]) == {work}


def test_the_scope_seed_and_a_users_file_are_brought_works_and_not_positives(store):
    lib = Probe(store)
    uploaded = store.create_upload_source("SYNTHETIC my own diffusion notes")
    store.add_to_corpus(lib.rid, uploaded, "user_upload", candidate=False)
    seed = lib.work()
    store.conn.execute("UPDATE scope_revisions SET seed_snapshot_json = ? WHERE research_id = ?",
                       (db.dumps({"source_version_id": seed, "passages": []}), lib.rid))
    found = lib.probe()
    assert found["brought"] == {lib.work_of(uploaded), lib.work_of(seed)}
    assert found["verified"] == {}


# ---- decision 5: the probes no arm found -------------------------------------------------------------------------


def test_a_brought_work_no_search_found_is_listed_and_one_the_chain_found_is_not(store):
    lib = Probe(store)
    lib.keyed("search:0", lib.records(2))
    uploaded = store.create_upload_source("SYNTHETIC my own diffusion notes")
    store.add_to_corpus(lib.rid, uploaded, "user_upload", candidate=False)
    (chained,) = lib.keyed("chain:backward:0", lib.records(1), query="chain:backward:W1")
    store.add_to_corpus(lib.rid, chained, "user_upload", candidate=False)  # the person also brought it
    missing = probes.not_found(store, lib.rid, lib.probe())
    assert missing["status"] == "counted"
    assert [(w["work_id"], w["reasons"], w["found"]) for w in missing["works"]] == [
        (lib.work_of(uploaded), ["brought"], "no")]


def test_a_work_an_older_discovery_run_of_the_revision_found_is_not_listed(store):
    lib = Probe(store, "irrigation")
    (early,) = lib.keyed("search:0", lib.records(1))
    lib.list_edit(early, "included")
    for _ in range(11):  # more than the view's ten latest runs
        run = lib.new_run("discovery")
        lib.keyed("search:0", lib.records(1), run=run)
    assert lib.view()["probes"]["not_found"] == {"status": "counted", "works": []}


def test_a_revision_with_a_run_before_the_hit_table_says_unknown_and_with_none_after_it_not_counted(store):
    lib = Probe(store)
    uploaded = store.create_upload_source("SYNTHETIC my own irrigation notes")
    store.add_to_corpus(lib.rid, uploaded, "user_upload", candidate=False)
    lib.keyed("search:0", lib.records(1))
    old = lib.run
    store.conn.execute("DELETE FROM candidate_hits WHERE search_run_id IN (SELECT id FROM search_runs WHERE run_id = ?)",
                       (old,))
    assert probes.not_found(store, lib.rid, lib.probe()) == {"status": "not_counted", "works": []}
    later = lib.new_run("discovery")
    lib.keyed("search:0", lib.records(1), run=later)
    missing = probes.not_found(store, lib.rid, lib.probe())
    assert missing["status"] == "partial"
    assert [(w["work_id"], w["found"]) for w in missing["works"]] == [(lib.work_of(uploaded), "unknown")]


def test_a_stored_hit_in_a_run_that_kept_only_some_hits_is_still_a_find(store):
    """Review finding 1: an old run with one search whose hits were not kept still found what its other search kept."""
    lib = Probe(store, "irrigation")
    (confirmed,) = lib.keyed("search:0", lib.records(1))
    lib.list_edit(confirmed, "included")
    lib.keyed("search:1", lib.records(2), provider="arxiv")
    store.conn.execute("DELETE FROM candidate_hits WHERE search_run_id IN (SELECT id FROM search_runs WHERE run_id = ?"
                       " AND provider = 'arxiv')", (lib.run,))
    uploaded = store.create_upload_source("SYNTHETIC my own greenhouse notes")
    store.add_to_corpus(lib.rid, uploaded, "user_upload", candidate=False)
    later = lib.new_run("discovery")
    lib.keyed("search:0", lib.records(1), run=later)  # a fully kept run that did not find the confirmed work
    missing = probes.not_found(store, lib.rid, lib.probe())
    assert missing["status"] == "partial"
    assert [(w["work_id"], w["found"]) for w in missing["works"]] == [(lib.work_of(uploaded), "unknown")]


def test_a_confirmed_work_found_only_by_the_citation_chain_leaves_the_view_list_empty(store):
    """Review finding 4: the screen's empty-list sentence names the search or the chain, so the view must hold none."""
    lib = Probe(store)
    lib.keyed("search:0", lib.records(2))
    (chained,) = lib.keyed("chain:backward:0", lib.records(1), query="chain:backward:W1")
    lib.list_edit(chained, "included")
    shown = lib.view()["probes"]
    assert shown["verified"] == 1 and shown["not_found"] == {"status": "counted", "works": []}


def test_a_legacy_research_has_no_probe_set_no_arms_and_no_signal_table(store):
    lib = Probe(store, workflow="legacy")
    lib.keyed("search:0", lib.records(2))
    view = lib.view()
    assert view["probes"] is None
    (run,) = [r for r in view["runs"] if r["id"] == lib.run]
    assert run["signals"] is None and run["source_counts"]["arms"] is None
    assert run["source_counts"]["rounds"] == views.source_counts(store, lib.run)["rounds"]


# ---- decisions 3–4: the arm rows ---------------------------------------------------------------------------------


def arms_of(lib, run=None):
    return views.source_counts(lib.store, run or lib.run, lib.probe())


def test_d93s_fields_stay_as_they_were_and_the_arm_rows_count_rows_included_and_confirmed(store):
    lib = Probe(store)
    lib.card([{"provider_id": "openalex", "origin": "model"}, {"provider_id": "arxiv", "origin": "model"}])
    a = lib.keyed("search:0", lib.records(3), result_count=25)
    b = lib.keyed("search:1", lib.records(2) + [provider_record("dup", "SYNTHETIC shared", "10.9999/p1.0")],
                  provider="arxiv", result_count=10)
    lib.include(a[0])  # found by both sources
    lib.include(a[1])  # openalex alone
    lib.list_edit(b[0], "included")  # arxiv alone, confirmed by the person
    counts = arms_of(lib)
    plain = views.source_counts(store, lib.run)
    assert {k: v for k, v in counts.items() if k != "arms"} == plain
    arms = counts["arms"]
    assert arms["rounds"] == [{"round": 1, "sources": [
        {"provider_id": "openalex", "rows": 25, "included": 2, "included_only": 1, "verified": 0, "verified_only": 0},
        {"provider_id": "arxiv", "rows": 10, "included": 1, "included_only": 0, "verified": 1, "verified_only": 1}]}]


def test_only_is_d93s_universe_a_keyword_work_the_chain_also_found_is_still_the_sources_own(store):
    lib = Probe(store, "irrigation")
    (work,) = lib.keyed("search:0", lib.records(1))
    lib.keyed("chain:backward:0", [provider_record("Rx", "SYNTHETIC again", store.source(work)["doi"])],
              query="chain:backward:W1")
    lib.include(work)
    arms = arms_of(lib)["arms"]
    assert arms["rounds"][0]["sources"][0]["included_only"] == 1  # no other source's search found it
    assert arms["chain"]["included"] == 1 and arms["chain"]["included_only"] == 0  # a search found it


def test_the_origin_is_read_by_the_step_index_so_a_second_round_query_with_the_same_text_is_expansion(store):
    lib = Probe(store)
    lib.card([{"provider_id": "openalex", "query_text": "same", "origin": "model"},
              {"provider_id": "openalex", "query_text": "other", "origin": "code"}])
    model = lib.keyed("search:0", lib.records(2), query="same")
    code = lib.keyed("search:1", lib.records(1), query="other")
    second = lib.keyed("search:2", lib.records(3), query="same")
    lib.include(model[0])
    lib.include(second[0])
    arms = arms_of(lib)["arms"]
    first, expansion = arms["rounds"]
    assert first["sources"][0]["by_origin"] == [{"origin": "code", "works": 1, "included": 0},
                                                {"origin": "model", "works": 2, "included": 1}]
    assert expansion["round"] == 2 and "by_origin" not in expansion["sources"][0]
    assert [k["kind"] for k in arms["kinds"]] == ["keyword", "expansion", "chain"]
    keyword, expanded, chain = arms["kinds"]
    assert keyword == {"kind": "keyword", "ran": True, "works": 3, "new_works": 3, "included": 1, "new_included": 1,
                       "verified": 0, "new_verified": 0}
    assert expanded == {"kind": "expansion", "ran": True, "works": 3, "new_works": 3, "included": 1,
                        "new_included": 1, "verified": 0, "new_verified": 0}
    assert chain == {"kind": "chain", "ran": False}
    assert len(code) == 1


def test_a_card_that_names_no_origin_gives_no_split(store):
    lib = Probe(store)
    lib.card([{"provider_id": "openalex"}, {"provider_id": "openalex"}])
    lib.keyed("search:0", lib.records(1))
    lib.keyed("search:1", lib.records(1))
    assert "by_origin" not in arms_of(lib)["arms"]["rounds"][0]["sources"][0]


def test_the_kind_line_counts_what_each_kind_found_that_no_earlier_kind_did(store):
    lib = Probe(store, "irrigation")
    lib.card([{"provider_id": "openalex", "origin": "code"}])
    (first,) = lib.keyed("search:0", lib.records(1))
    again = provider_record("Ry", "SYNTHETIC again", store.source(first)["doi"])
    lib.keyed("search:1", [again] + lib.records(1))
    (chained,) = lib.keyed("chain:backward:0", lib.records(1), query="chain:backward:W1")
    lib.include(chained)
    lib.list_edit(first, "included")
    keyword, expansion, chain = arms_of(lib)["arms"]["kinds"]
    assert (keyword["new_works"], keyword["new_verified"]) == (1, 1)
    assert (expansion["works"], expansion["new_works"], expansion["verified"], expansion["new_verified"]) == (2, 1, 1, 0)
    assert (chain["ran"], chain["new_works"], chain["new_included"]) == (True, 1, 1)


def test_read_is_false_before_any_reading_and_the_counts_move_with_a_reading_without_a_write(store):
    lib = Probe(store)
    (svid,) = lib.keyed("search:0", lib.records(1))
    lib.ds.record(lib.rid, svid, "no_fulltext")  # a retrieval outcome is not a reading
    arms = arms_of(lib)["arms"]
    assert arms["read"] is False and arms["rounds"][0]["sources"][0]["included"] == 0
    tables = [row[0] for row in store.conn.execute("SELECT name FROM sqlite_master WHERE type = 'table'")]
    lib.include(svid)
    before = {t: store.conn.execute(f"SELECT COUNT(*) FROM {t}").fetchone()[0] for t in tables}
    changes = store.conn.total_changes
    arms = arms_of(lib)["arms"]
    assert arms["read"] is True and arms["rounds"][0]["sources"][0]["included"] == 1
    assert {t: store.conn.execute(f"SELECT COUNT(*) FROM {t}").fetchone()[0] for t in tables} == before
    assert store.conn.total_changes == changes


def test_a_run_whose_counts_were_not_kept_gets_no_arms(store):
    lib = Probe(store)
    lib.keyed("search:0", lib.records(1))
    store.conn.execute("DELETE FROM candidate_hits")
    assert arms_of(lib) == {"counted": False, "rounds": []}


# ---- decision 6: the signal table --------------------------------------------------------------------------------


def verified_works(lib, n):
    svids = lib.keyed("search:0", lib.records(n))
    for svid in svids:
        lib.list_edit(svid, "included")
    return svids


def test_a_signal_that_did_not_run_says_why(store):
    lib = Probe(store)
    svids = lib.keyed("search:0", lib.records(2))
    output = {"pool": 2, "signals": {"bm25": {"ran": True, "available": 2}, "blocks": {"ran": True, "available": 2},
                                     "tfidf": {"ran": False, "reason": "no_verified_seeds", "available": 0},
                                     "graph": {"ran": False, "reason": "no_seed_with_references", "available": 0},
                                     "embedding": {"ran": False, "reason": "embedding_off", "available": 0}}}
    run, _ = lib.ranking(order_rows(svids, "bm25") + order_rows(svids, "blocks") + order_rows(svids, "fused"), output)
    table = probes.signal_table(store, run, lib.probe())
    reasons = {row["signal"]: (row["ran"], row["reason"]) for row in table["signals"]}
    assert reasons["tfidf"] == (False, "no_verified_seeds") and reasons["embedding"] == (False, "embedding_off")
    assert reasons["bm25"] == (True, None)
    assert [row["signal"] for row in table["person"]["rows"]] == ["bm25", "blocks", "fused", "inspection"]
    assert table["embedding"] is None  # the embedding did not run: nothing was moved up


@pytest.mark.parametrize("n, status", [(29, "too_few"), (30, "descriptive")])
def test_the_denominator_is_the_confirmed_works_in_the_step_and_below_thirty_it_is_too_few(store, n, status):
    lib = Probe(store, "irrigation")
    confirmed = verified_works(lib, n)
    absent = verified_works(lib, 1)  # confirmed, but not in this ranking step
    run, _ = lib.ranking(order_rows(confirmed, "bm25") + order_rows(confirmed, "fused"))
    person = probes.signal_table(store, run, lib.probe())["person"]
    assert person["denominator"] == n and person["status"] == status
    assert absent[0] not in confirmed
    assert {row["signal"]: row["top_100"] for row in person["rows"]}["bm25"] == n


def test_a_record_the_signal_did_not_score_is_not_captured_although_its_tail_place_is_inside_the_cut(store):
    lib = Probe(store)
    pool = lib.keyed("search:0", lib.records(6))
    target = pool[0]
    lib.list_edit(target, "included")
    rows = (order_rows(pool, "bm25")
            + order_rows(pool[1:], "graph") + [{"source_version_id": target, "signal": "graph", "rank": 6.0,
                                                 "available": False}]
            + order_rows(pool, "fused"))
    run, _ = lib.ranking(rows)
    captured = {row["signal"]: row["top_100"] for row in probes.signal_table(store, run, lib.probe())["person"]["rows"]}
    assert captured["bm25"] == 1 and captured["graph"] == 0


def test_a_tie_group_across_the_cut_is_tied_at_the_cut_and_one_inside_it_is_captured(store):
    lib = Probe(store, "irrigation")
    pool = lib.keyed("search:0", lib.records(110))
    across, inside = pool[100], pool[10]  # places 98–103 share 100.5; places 10–12 share 11
    lib.list_edit(across, "included")
    lib.list_edit(inside, "included")
    rows = []
    for position, svid in enumerate(pool, start=1):
        rank = 100.5 if 98 <= position <= 103 else 11.0 if 10 <= position <= 12 else float(position)
        rows.append({"source_version_id": svid, "signal": "bm25", "rank": rank, "available": True})
    run, _ = lib.ranking(rows + order_rows(pool, "fused") + order_rows(pool, "inspection"))
    table = {row["signal"]: row for row in probes.signal_table(store, run, lib.probe())["person"]["rows"]}
    assert (table["bm25"]["top_100"], table["bm25"]["tied_100"]) == (1, 1)
    assert (table["bm25"]["top_200"], table["bm25"]["tied_200"]) == (2, 0)
    # The two orders are exact places (D79): pool[100] is place 101, outside the top 100.
    assert (table["fused"]["top_100"], table["fused"]["tied_100"]) == (1, 0)
    assert table["inspection"]["top_200"] == 2


def test_a_confirmed_work_whose_head_changed_after_the_ranking_is_still_found_through_its_version(store):
    lib = Probe(store)
    preprint = lib.preprint("10.9999/synth.later")
    run, _ = lib.ranking(order_rows([preprint], "bm25") + order_rows([preprint], "fused"))
    published = lib.published("10.9999/synth.later")
    assert lib.head(preprint) == published  # the published record heads the work now
    lib.list_edit(published, "included")
    person = probes.signal_table(store, run, lib.probe())["person"]
    assert person["denominator"] == 1
    assert {row["signal"]: row["top_100"] for row in person["rows"]}["bm25"] == 1


def test_model_agreement_has_its_own_row_with_its_note_and_is_not_added_to_the_persons(store):
    lib = Probe(store, "irrigation")
    agreed, confirmed = lib.keyed("search:0", lib.records(2))
    lib.include(agreed)
    lib.list_edit(confirmed, "included")
    run, _ = lib.ranking(order_rows([agreed, confirmed], "bm25") + order_rows([agreed, confirmed], "fused"))
    table = probes.signal_table(store, run, lib.probe())
    assert table["person"]["denominator"] == 1 and table["agreement"]["denominator"] == 1
    assert table["agreement"]["note"] == "read_because_ranked" and "status" not in table["agreement"]


def moved_up_case(lib, decide):
    """A record the embedding moved up, then decided by `decide`; the ranking step's end is set around the decision."""
    pool = lib.keyed("search:0", lib.records(3))
    target = pool[2]
    rows = order_rows(pool, "bm25") + order_rows(pool, "embedding") + order_rows(pool, "fused")
    run, step = lib.ranking(rows, {"rescued": [target]})
    at = decide(target)
    return run, step, at


def included_at(lib):
    def decide(svid):
        lib.include(svid)
        return lib.ds.current(lib.rid, svid, "fulltext")["created_at"]
    return decide


def confirmed_at(lib):
    def decide(svid):
        lib.list_edit(svid, "included")
        # The time the table reads: the list edit's own history row (review finding 2), not `selections.updated_at`.
        return lib.store.conn.execute("SELECT MAX(created_at) FROM selection_history WHERE research_id = ?"
                                      " AND source_version_id = ? AND origin = 'user'", (lib.rid, svid)).fetchone()[0]
    return decide


def queue_confirmed_at(lib):
    def decide(svid):
        lib.text(svid, [lib.field["page"], lib.field["cue"]])
        lib.read(svid, "part_without_evidence",
                 labels={lib.parts[0]: ("present", "present"), lib.parts[1]: ("absent", "absent")})
        result = queue.decide(lib.store, lib.rid, svid, "include", None, lib.row(svid)["row_token"])
        return lib.ds.current(lib.rid, svid, "fulltext")["created_at"] if result else None
    return decide


@pytest.mark.parametrize("decider, column", [(included_at, "moved_up_then_included"),
                                             (confirmed_at, "moved_up_then_verified"),
                                             (queue_confirmed_at, "moved_up_then_verified")])
@pytest.mark.parametrize("when, expected", [("before", "moved_up_already_decided"), ("same", "moved_up_time_unknown"),
                                            ("after", None), ("unknown", "moved_up_time_unknown")])
def test_what_was_decided_about_a_moved_up_record_is_counted_only_after_the_ranking_ended(store, decider, column,
                                                                                         when, expected):
    lib = Probe(store)
    run, step, at = moved_up_case(lib, decider(lib))
    ended = {"before": "2999-01-01T00:00:00.000+00:00", "same": at, "after": "2000-01-01T00:00:00.000+00:00",
             "unknown": None}[when]
    store.conn.execute("UPDATE run_steps SET finished_at = ? WHERE id = ?", (ended, step))
    embedding = probes.signal_table(store, run, lib.probe())["embedding"]
    assert embedding["moved_up"] == 1
    columns = ("moved_up_then_included", "moved_up_then_verified", "moved_up_already_decided", "moved_up_time_unknown")
    expected = expected or column
    assert {c: embedding[c] for c in columns} == {c: int(c == expected) for c in columns}


def test_the_chains_ranking_step_is_not_read(store):
    lib = Probe(store)
    (svid,) = lib.keyed("search:0", lib.records(1))
    lib.list_edit(svid, "included")
    run, _ = lib.ranking(order_rows([svid], "bm25") + order_rows([svid], "fused"), key="chain_ranking")
    assert probes.signal_table(store, run, lib.probe()) is None


# ---- decisions 10–11: one derivation, nothing written ------------------------------------------------------------


def test_the_view_derives_the_facts_once_calls_no_verified_records_and_changes_no_table(store, monkeypatch):
    lib = Probe(store)
    pool = lib.keyed("search:0", lib.records(3)) + lib.keyed("search:1", lib.records(2), provider="arxiv")
    lib.include(pool[0])
    answered(lib, "include")
    lib.list_edit(pool[1], "included")
    lib.ranking(order_rows(pool, "bm25") + order_rows(pool, "fused"), run=lib.run)
    tables = [row[0] for row in store.conn.execute("SELECT name FROM sqlite_master WHERE type = 'table'")]
    before = {t: store.conn.execute(f"SELECT COUNT(*) FROM {t}").fetchone()[0] for t in tables}
    changes = store.conn.total_changes
    calls = []
    real = DecisionStore.facts
    monkeypatch.setattr(DecisionStore, "facts", lambda self, *a, **k: calls.append(a) or real(self, *a, **k))
    monkeypatch.setattr(queue, "verified_records", lambda *a, **k: pytest.fail("the view reads no verified_records"))
    view = lib.view()
    assert len(calls) == 1
    assert {t: store.conn.execute(f"SELECT COUNT(*) FROM {t}").fetchone()[0] for t in tables} == before
    assert store.conn.total_changes == changes
    assert view["probes"]["verified"] == 2 and view["probes"]["included_by_agreement"] == 1
    (run,) = [r for r in view["runs"] if r["id"] == lib.run]
    assert run["signals"]["person"]["denominator"] == 1 and run["signals"]["person"]["status"] == "too_few"
    assert [s["included"] for s in run["source_counts"]["arms"]["rounds"][0]["sources"]] == [1, 0]
    assert view["counts"]["queue"] == 0


def test_a_record_a_scripted_similarity_moved_up_and_later_included_is_moved_up_then_included(tmp_path, monkeypatch):
    """The ranking itself, not a written output: `rank_records` with a stored similarity lifts one record (SW8.1, the
    arm's limits lowered as in `test_ranking_flow`), and what the table reads of it follows the decision's time."""
    import test_ranking_flow as flow_tests
    from deixis.workflow import ranking

    monkeypatch.setattr(ranking, "RESCUE_OUTSIDE_TOP", 2)
    monkeypatch.setattr(ranking, "RESCUE_EMBEDDING_TOP", 1)
    records = [flow_tests.provider_record(i, f"SYNTHETIC wireless sensor networks packet size study {i}") for i in range(3)]
    records += [flow_tests.provider_record(i, f"SYNTHETIC sourdough bakery {i}") for i in range(3, 6)]
    store, rid, run = flow_tests.stored_research(tmp_path, records)
    svids = [store.find_source_by_identifier("openalex", f"W{i}") for i in range(6)]
    target = svids[5]
    store.save_source_similarities(rid, 1, "scripted-embedding", {s: 0.9 if s == target else 0.1 for s in svids})
    output = flow_tests.rank(store, rid, run, "scripted-embedding")
    assert output["rescued"] == [target]
    step = store.step(run["id"], "ranking", "code:ranking")
    store.finish_step(step["id"], "succeeded", output=output)
    store.conn.execute("UPDATE run_steps SET finished_at = ? WHERE id = ?", ("2000-01-01T00:00:00.000+00:00", step["id"]))
    DecisionStore(store).record(rid, target, "all_parts_verified")
    probe = probes.probe_set(queue.context(store, rid))
    embedding = probes.signal_table(store, run["id"], probe)["embedding"]
    assert (embedding["moved_up"], embedding["moved_up_then_included"]) == (1, 1)
    store.conn.close()


def test_a_list_confirmation_made_before_the_ranking_stays_before_it_when_a_new_head_copies_the_selection(store):
    """Review finding 2: the published version becomes the head after the ranking and takes the preprint's selection
    over with a new time; the person decided before the ranking, so the moved-up work is not `then_verified`."""
    lib = Probe(store, "irrigation")
    preprint = lib.preprint("10.9999/synth.copied")
    lib.list_edit(preprint, "included")
    rows = order_rows([preprint], "bm25") + order_rows([preprint], "embedding") + order_rows([preprint], "fused")
    run, step = lib.ranking(rows, {"rescued": [preprint]})
    published = lib.published("10.9999/synth.copied")
    assert lib.head(preprint) == published and lib.selection(published) == ("included", "user")
    store.conn.execute("UPDATE selection_history SET created_at = '2001-01-01T00:00:00.000+00:00'"
                       " WHERE research_id = ? AND origin = 'user' AND reason = 'SYNTHETIC list edit'", (lib.rid,))
    store.conn.execute("UPDATE run_steps SET finished_at = '2002-01-01T00:00:00.000+00:00' WHERE id = ?", (step,))
    embedding = probes.signal_table(store, run, lib.probe())["embedding"]
    assert (embedding["moved_up_then_verified"], embedding["moved_up_already_decided"]) == (0, 1)


def test_a_persons_reason_may_not_be_the_copy_marker_so_the_history_tells_a_copy_from_an_edit(tmp_path):
    """Review 2, finding 1: the copy row is known by its reason text alone (no migration), so the API refuses a
    person's reason equal to it (422); any other reason, even one that contains it, is a real edit the table reads."""
    from fastapi.testclient import TestClient
    from helpers import make_pdf
    from test_api_flow import app_for, create, session
    from deixis.workflow.store import COPIED_SELECTION_REASON

    with TestClient(app_for(tmp_path)) as raw:
        client = session(raw)
        rid = create(client, source_scope="attached")
        upload = client.post(f"/api/researches/{rid}/uploads",
                             files={"file": ("notes.pdf", make_pdf(["SYNTHETIC greenhouse notes."]), "application/pdf")})
        assert upload.status_code == 201
        (source,) = client.get(f"/api/researches/{rid}").json()["sources"]
        url = f"/api/researches/{rid}/selections/{source['source_version_id']}"
        version = source["selection"]["version"]
        refused = client.patch(url, json={"state": "excluded", "expected_version": version, "reason": COPIED_SELECTION_REASON})
        assert refused.status_code == 422
        kept = client.patch(url, json={"state": "excluded", "expected_version": version,
                                       "reason": f"{COPIED_SELECTION_REASON}, I checked"})
        assert kept.status_code == 200
        store = raw.app.state.store
        reasons = [r[0] for r in store.conn.execute(
            "SELECT reason FROM selection_history WHERE research_id = ? AND origin = 'user'", (rid,))]
        assert COPIED_SELECTION_REASON not in reasons and f"{COPIED_SELECTION_REASON}, I checked" in reasons
