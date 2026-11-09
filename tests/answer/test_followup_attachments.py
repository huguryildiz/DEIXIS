"""What the person selected before they asked, bound to the source it came from.

SYNTHETIC records throughout; no model is asked. These show that code reads the work, the version and the place from
stored rows, that a selection the research can no longer read keeps its text instead of binding to the wrong thing,
and that a bound selection reaches the call even when the passage limits are full.
"""

import json

import pytest
from fastapi.testclient import TestClient

from deixis.domain.rules import RevisionConflict
from deixis.storage.db import new_id, now, transaction
from deixis.workflow.answer import followup, followup_attachments as attachments
from fakes import FakeAdapter
from test_api_flow import app_for, session
from test_fast_path_answer import answer_run, cutoff, setup
from test_followup_turns import QUESTION, research


def passages(lib, svid):
    return [row["id"] for row in lib.store.passages_for(svid)]


def quiet(lib):
    """The library's discovery run is left running by `setup`; a follow-up needs this research to have none active."""
    lib.store.update_run(lib.discovery["id"], status="completed")


def resolve(lib, kind, ref_id, text="SYNTHETIC selected text"):
    return attachments.resolve(lib.store, lib.rid, [{"kind": kind, "ref_id": ref_id, "text": text}])[0]


def work_of(lib, svid):
    return lib.store.conn.execute("SELECT work_id FROM source_versions WHERE id = ?", (svid,)).fetchone()[0]


# ---- one selection, one identity -------------------------------------------------------------------------------

def test_a_selected_passage_binds_to_its_own_work_and_version(tmp_path):
    lib = setup(tmp_path, n=2)
    svid = lib.sources[1]
    pid = passages(lib, svid)[0]
    item = resolve(lib, "passage", pid)
    assert item["unresolved_reason"] is None
    (binding,) = item["bindings"]
    assert binding["passage_id"] == pid and binding["source_version_id"] == svid
    assert binding["work_id"] == work_of(lib, svid)
    assert binding["locator"]["kind"] == "abstract"


def test_a_selected_answer_sentence_binds_to_the_passages_it_cites(tmp_path):
    import asyncio
    from deixis.workflow.answer import answer as fast_answer
    lib = setup(tmp_path, n=2)
    cutoff(lib)
    run = answer_run(lib)
    asyncio.run(fast_answer.answer(lib.flow, run, lib.store.scope(lib.rid)))
    claim = lib.store.conn.execute(
        "SELECT c.id FROM claims c JOIN answers a ON a.id = c.answer_id JOIN evidence_links l ON l.claim_id = c.id"
        " WHERE a.research_id = ? LIMIT 1", (lib.rid,)).fetchone()
    assert claim is not None, "the synthetic answer cited nothing"
    cited = [r[0] for r in lib.store.conn.execute(
        "SELECT passage_id FROM evidence_links WHERE claim_id = ? ORDER BY rowid", (claim["id"],))]
    item = resolve(lib, "answer_claim", claim["id"])
    assert [b["passage_id"] for b in item["bindings"]] == cited
    assert all(b["work_id"] for b in item["bindings"])


def test_a_selected_cell_binds_to_the_passages_its_current_value_cites(tmp_path):
    lib = setup(tmp_path, n=1)
    svid = lib.sources[0]
    pid = passages(lib, svid)[0]
    cell_id = cell(lib, svid, [pid])
    item = resolve(lib, "cell", cell_id)
    assert item["unresolved_reason"] is None
    (binding,) = item["bindings"]
    assert binding["passage_id"] == pid and binding["source_version_id"] == svid


def test_a_cell_with_no_located_quote_keeps_the_text_and_says_why(tmp_path):
    lib = setup(tmp_path, n=1)
    cell_id = cell(lib, lib.sources[0], [])
    item = resolve(lib, "cell", cell_id)
    assert item["bindings"] == [] and item["unresolved_reason"] == "cell_has_no_located_quote"
    assert item["text"] == "SYNTHETIC selected text"


def test_a_free_selection_is_context_and_names_no_source(tmp_path):
    lib = setup(tmp_path, n=1)
    item = resolve(lib, "text", None, "SYNTHETIC a sentence of my own")
    assert item == {"kind": "text", "ref_id": None, "text": "SYNTHETIC a sentence of my own",
                    "unresolved_reason": None, "bindings": []}


# ---- the report sentence reads the report's own frozen evidence -------------------------------------------------

def step_input(lib):
    """One stored StepInput row, which a report citation must name."""
    step_id, sid = new_id("stp"), new_id("sti")
    with transaction(lib.store.conn):
        lib.store.conn.execute(
            "INSERT INTO run_steps (id, run_id, operation_key, kind, status) VALUES (?, ?, ?, ?, 'succeeded')",
            (step_id, lib.discovery["id"], f"SYNTHETIC:{sid}", "model:report_section"))
        lib.store.conn.execute(
            "INSERT INTO step_inputs (id, step_id, research_id, run_id, attempt, task_type, scope_revision,"
            " skill_package_hash, payload_json, base_instructions, developer_instructions, user_message,"
            " output_schema_json, created_at) VALUES (?, ?, ?, ?, 1, 'report_section', 1, 'sha', '{}', '', '', '',"
            " '{}', ?)", (sid, step_id, lib.rid, lib.discovery["id"], now()))
    return sid


def cell(lib, svid, evidence_ids, state="value"):
    """One evidence cell with a current revision citing these passages."""
    table_id, column_id, cell_id, revision_id = new_id("tbl"), new_id("col"), new_id("cel"), new_id("cev")
    with transaction(lib.store.conn):
        lib.store.conn.execute(
            "INSERT INTO evidence_tables (id, research_id, title, created_at, updated_at) VALUES (?, ?, ?, ?, ?)",
            (table_id, lib.rid, "SYNTHETIC table", now(), now()))
        lib.store.conn.execute(
            "INSERT INTO table_columns (id, table_id, position, origin, created_at) VALUES (?, ?, 1, 'user', ?)",
            (column_id, table_id, now()))
        lib.store.conn.execute(
            "INSERT INTO evidence_cells (id, table_id, column_id, source_version_id, created_at, updated_at)"
            " VALUES (?, ?, ?, ?, ?, ?)", (cell_id, table_id, column_id, svid, now(), now()))
        lib.store.conn.execute(
            "INSERT INTO cell_revisions (id, cell_id, kind, author, column_revision, state, value_json, created_at)"
            " VALUES (?, ?, 'human_edit', 'human', 1, ?, ?, ?)",
            (revision_id, cell_id, state, json.dumps({"text": "SYNTHETIC finding"}), now()))
        for pid in evidence_ids:
            lib.store.conn.execute(
                "INSERT INTO cell_evidence_links (cell_revision_id, passage_id, source_version_id, anchor_text,"
                " anchor_match) VALUES (?, ?, ?, 'SYNTHETIC', 'exact')", (revision_id, pid, svid))
        lib.store.conn.execute("UPDATE evidence_cells SET current_revision_id = ? WHERE id = ?", (revision_id, cell_id))
    return cell_id


def report_claim_citing_cell(lib, cell_id, svid, frozen_passage_ids):
    """A report sentence whose citation names a cell, with the cell's evidence as that report froze it."""
    report_id, section_id, claim_id = new_id("rep"), new_id("rsc"), new_id("rcl")
    table_id = lib.store.conn.execute("SELECT table_id FROM evidence_cells WHERE id = ?", (cell_id,)).fetchone()[0]
    sid = step_input(lib)
    with transaction(lib.store.conn):
        lib.store.conn.execute(
            "INSERT INTO reports (id, research_id, run_id, scope_revision, status, report_version, created_at,"
            " updated_at) VALUES (?, ?, ?, 1, 'valid', 1, ?, ?)",
            (report_id, lib.rid, lib.discovery["id"], now(), now()))
        lib.store.conn.execute(
            "INSERT INTO report_sections (id, report_id, section_id, status, ordinal, created_at, updated_at)"
            " VALUES (?, ?, 'IV', 'valid', 1, ?, ?)", (section_id, report_id, now(), now()))
        lib.store.conn.execute(
            "INSERT INTO report_claims (id, report_section_id, claim_key, ordinal, paragraph, text, support_type)"
            " VALUES (?, ?, 'IV.1', 1, 1, 'SYNTHETIC. The method lowered the delay.', 'source_stated')",
            (claim_id, section_id))
        lib.store.conn.execute(
            "INSERT INTO report_citation_links (id, claim_id, cell_id, source_version_id, step_input_id, anchor_text,"
            " anchor_match) VALUES (?, ?, ?, ?, ?, 'SYNTHETIC', 'exact')",
            (new_id("rcx"), claim_id, cell_id, svid, sid))
        lib.store.conn.execute(
            "INSERT INTO report_snapshot (report_id, table_id, table_revision, snapshot_json, created_at)"
            " VALUES (?, ?, 1, ?, ?)",
            (report_id, table_id, json.dumps({"cells": [
                {"cell_id": cell_id, "evidence": [{"passage_id": pid, "quote": "SYNTHETIC"}
                                                  for pid in frozen_passage_ids]}]}), now()))
    return claim_id


def test_a_report_sentence_reads_the_cell_as_that_report_froze_it(tmp_path):
    """The cell was filled again after the report. The report's citation still means what the report rests on."""
    lib = setup(tmp_path, n=1, pdf=True)
    svid = lib.sources[-1]  # the source with a PDF: an abstract and pages, so two passages of one work
    abstract, later, *_ = passages(lib, svid)
    cell_id = cell(lib, svid, [abstract])
    claim_id = report_claim_citing_cell(lib, cell_id, svid, [abstract])
    # The cell is filled again from another source's passage; the report's own snapshot is untouched.
    with transaction(lib.store.conn):
        revision_id = new_id("cev")
        lib.store.conn.execute(
            "INSERT INTO cell_revisions (id, cell_id, kind, author, column_revision, state, value_json, created_at)"
            " VALUES (?, ?, 'human_edit', 'human', 1, 'value', ?, ?)",
            (revision_id, cell_id, json.dumps({"text": "SYNTHETIC other finding"}), now()))
        lib.store.conn.execute(
            "INSERT INTO cell_evidence_links (cell_revision_id, passage_id, source_version_id, anchor_text,"
            " anchor_match) VALUES (?, ?, ?, 'SYNTHETIC', 'exact')", (revision_id, later, svid))
        lib.store.conn.execute("UPDATE evidence_cells SET current_revision_id = ? WHERE id = ?", (revision_id, cell_id))
    item = resolve(lib, "report_claim", claim_id)
    assert [b["passage_id"] for b in item["bindings"]] == [abstract]
    # The live cell now cites the other passage; selecting the cell itself reads that one.
    assert [b["passage_id"] for b in resolve(lib, "cell", cell_id)["bindings"]] == [later]


def test_a_citation_the_person_removed_from_a_report_sentence_is_not_read_again(tmp_path):
    lib = setup(tmp_path, n=1)
    svid = lib.sources[0]
    pid = passages(lib, svid)[0]
    cell_id = cell(lib, svid, [pid])
    claim_id = report_claim_citing_cell(lib, cell_id, svid, [pid])
    # The person edited the sentence and kept none of its citations.
    with transaction(lib.store.conn):
        revision_id = new_id("rcr")
        lib.store.conn.execute(
            "INSERT INTO report_claim_revisions (id, claim_id, kind, text, created_at, link_count)"
            " VALUES (?, ?, 'human_edit', 'SYNTHETIC. My own sentence.', ?, 0)", (revision_id, claim_id, now()))
        lib.store.conn.execute("UPDATE report_claims SET current_revision_id = ? WHERE id = ?", (revision_id, claim_id))
    item = resolve(lib, "report_claim", claim_id)
    assert item["bindings"] == [] and item["unresolved_reason"] == "claim_has_no_citation"


# ---- what this research can no longer read ---------------------------------------------------------------------

def test_a_passage_of_a_source_removed_from_the_research_is_unresolved_not_misbound(tmp_path):
    lib = setup(tmp_path, n=2)
    svid = lib.sources[1]
    pid = passages(lib, svid)[0]
    with transaction(lib.store.conn):
        lib.store.conn.execute("UPDATE corpus_memberships SET removed_at = ? WHERE research_id = ? AND"
                               " source_version_id = ?", (now(), lib.rid, svid))
    item = resolve(lib, "passage", pid)
    assert item["bindings"] == [] and item["unresolved_reason"] == "source_removed"


def test_a_passage_of_an_extraction_read_again_is_unresolved(tmp_path):
    lib = setup(tmp_path, n=1, pdf=True)
    svid = lib.sources[-1]
    page = next(row["id"] for row in lib.store.passages_for(svid) if row["kind"] == "pdf_page")
    with transaction(lib.store.conn):
        lib.store.conn.execute(
            "UPDATE source_assets SET extraction_version = COALESCE(extraction_version, 0) + 1"
            " WHERE source_version_id = ?", (svid,))
    item = resolve(lib, "passage", page)
    assert item["bindings"] == [] and item["unresolved_reason"] == "passage_not_current"


def test_an_id_of_another_research_or_of_nothing_is_refused(tmp_path):
    lib = setup(tmp_path, n=2)
    stranger = passages(lib, lib.sources[1])[0]
    with transaction(lib.store.conn):  # the source is in the library but not in this research
        lib.store.conn.execute("DELETE FROM corpus_memberships WHERE research_id = ? AND source_version_id = ?",
                               (lib.rid, lib.sources[1]))
    with pytest.raises(attachments.AttachmentRefused):
        resolve(lib, "passage", stranger)
    with pytest.raises(attachments.AttachmentRefused):
        resolve(lib, "passage", "psg_nothing")
    with pytest.raises(attachments.AttachmentRefused):
        resolve(lib, "cell", "cel_nothing")
    with pytest.raises(attachments.AttachmentRefused):
        resolve(lib, "report_claim", "rcl_nothing")
    with pytest.raises(attachments.AttachmentRefused):
        resolve(lib, "answer_claim", "clm_nothing")
    with pytest.raises(attachments.AttachmentRefused):
        resolve(lib, "followup_claim", "fut_nothing:c1")


@pytest.mark.parametrize("item,note", [
    ({"kind": "elsewhere", "ref_id": "x", "text": "t"}, "unknown kind"),
    ({"kind": "text", "ref_id": "psg_one", "text": "t"}, "a free selection carries no id"),
    ({"kind": "passage", "ref_id": None, "text": "t"}, "every other selection carries one"),
    ({"kind": "text", "ref_id": None, "text": ""}, "no text"),
    ({"kind": "text", "ref_id": None, "text": "x" * 801}, "too long"),
])
def test_a_malformed_selection_is_refused(tmp_path, item, note):
    lib = setup(tmp_path, n=1)
    with pytest.raises(attachments.AttachmentRefused):
        attachments.resolve(lib.store, lib.rid, [item])


def test_more_than_four_selections_are_refused(tmp_path):
    lib = setup(tmp_path, n=1)
    one = {"kind": "text", "ref_id": None, "text": "SYNTHETIC"}
    with pytest.raises(attachments.AttachmentRefused):
        attachments.resolve(lib.store, lib.rid, [one] * 5)


# ---- the question, the turn and the call -----------------------------------------------------------------------

def test_the_question_holds_no_quote_and_the_selection_is_stored_beside_it(tmp_path):
    adapter = FakeAdapter()
    app = app_for(tmp_path, adapter)
    with TestClient(app) as client:
        session(client)
        rid, (svid,) = research(client)
        store = app.state.store
        pid = store.passages_for(svid)[0]["id"]
        response = client.post(f"/api/researches/{rid}/followup-turns", json={
            "question": QUESTION, "expected_scope_revision": 1,
            "attachments": [{"kind": "passage", "ref_id": pid, "text": "SYNTHETIC quoted sentence"}]})
        assert response.status_code == 202, response.text
        turn = response.json()
        assert turn["question"] == QUESTION  # the quote is not in it
        (item,) = turn["attachments"]
        assert item["kind"] == "passage" and item["selected_text"] == "SYNTHETIC quoted sentence"
        (binding,) = item["bindings"]
        assert binding["passage_id"] == pid and binding["source_version_id"] == svid


def test_a_selection_naming_nothing_is_refused_by_the_route(tmp_path):
    adapter = FakeAdapter()
    app = app_for(tmp_path, adapter)
    with TestClient(app) as client:
        session(client)
        rid, _ = research(client)
        response = client.post(f"/api/researches/{rid}/followup-turns", json={
            "question": QUESTION, "expected_scope_revision": 1,
            "attachments": [{"kind": "passage", "ref_id": "psg_nothing", "text": "SYNTHETIC"}]})
        assert response.status_code == 422, response.text


def test_the_same_key_with_other_selections_is_another_request(tmp_path):
    lib = setup(tmp_path, n=2)
    first = passages(lib, lib.sources[0])[0]
    second = passages(lib, lib.sources[1])[0]
    quiet(lib)
    pick = [{"kind": "passage", "ref_id": first, "text": "SYNTHETIC one"}]
    turn = followup.request_turn(lib.store, lib.rid, QUESTION, 1, "key-one", pick)
    # The same key and the same selections is the same request.
    assert followup.request_turn(lib.store, lib.rid, QUESTION, 1, "key-one", pick)["id"] == turn["id"]
    with pytest.raises(RevisionConflict):
        followup.request_turn(lib.store, lib.rid, QUESTION, 1, "key-one",
                              [{"kind": "passage", "ref_id": second, "text": "SYNTHETIC one"}])
    with pytest.raises(RevisionConflict):
        followup.request_turn(lib.store, lib.rid, QUESTION, 1, "key-one", [])


def test_each_selection_keeps_a_passage_in_the_call_with_the_limits_full(tmp_path):
    """Four selections of four works, a limit of one passage per work and a total of two: both reserved slots hold."""
    import asyncio
    from test_fast_path_answer import user
    lib = setup(tmp_path, n=4)
    for svid in lib.sources:
        user(lib, svid, "included")
    quiet(lib)
    picks = [{"kind": "passage", "ref_id": passages(lib, svid)[0], "text": f"SYNTHETIC {i}"}
             for i, svid in enumerate(lib.sources)]
    turn = followup.request_turn(lib.store, lib.rid, QUESTION, 1, None, picks)
    run = lib.store.run(turn["run_id"])
    lib.store.update_run(run["id"], status="running")
    run = lib.store.run(run["id"])
    run["budget"]["max_followup_passages"] = 2  # the limit is full before the ranking is reached
    frozen = followup.pool(lib.store, lib.rid, 1)
    selected = asyncio.run(followup._selection(lib.flow, run, lib.store.scope(lib.rid), QUESTION, frozen))
    chosen = selected["passage_ids"]
    assert len(chosen) == 2, chosen
    # The two that fit are the first two selections' own passages, and the record says which were given.
    assert chosen == [picks[0]["ref_id"], picks[1]["ref_id"]]
    given = {aid: item["given"] for aid, item in selected["attachments"].items()}
    assert sorted(pid for ids in given.values() for pid in ids) == sorted(chosen)
    # Two selections were bound but not given: the record says so instead of hiding them.
    assert sum(1 for ids in given.values() if not ids) == 2
    assert selected["from_attachments"] == 2
    # Three counts, kept apart: what the pool held, what the ranking saw, what the call was given.
    assert selected["pool_held"] == 4 and selected["given_to_model"] == 2
    # The ranking's own count is what it saw, not what was put in front of it.
    assert selected["ranked_considered"] <= selected["pool_held"]


def test_a_selection_outside_the_pool_is_context_and_not_added_to_it(tmp_path):
    """The person set the source pending after they selected it: their choice stands above the selection."""
    import asyncio
    from test_fast_path_answer import user
    lib = setup(tmp_path, n=2)
    svid = lib.sources[1]
    pid = passages(lib, svid)[0]
    user(lib, svid, "included")
    quiet(lib)
    turn = followup.request_turn(lib.store, lib.rid, QUESTION, 1, None,
                                [{"kind": "passage", "ref_id": pid, "text": "SYNTHETIC"}])
    user(lib, svid, "pending")
    run = lib.store.run(turn["run_id"])
    lib.store.update_run(run["id"], status="running")
    run = lib.store.run(run["id"])
    frozen = followup.pool(lib.store, lib.rid, 1)
    assert svid not in frozen["sources"]
    selected = asyncio.run(followup._selection(lib.flow, run, lib.store.scope(lib.rid), QUESTION, frozen))
    assert pid not in selected["passage_ids"]
    assert all(not item["in_pool"] and not item["given"] for item in selected["attachments"].values())


def test_the_conversation_gives_the_selection_as_the_persons_quote(tmp_path):
    lib = setup(tmp_path, n=1)
    svid = lib.sources[0]
    pid = passages(lib, svid)[0]
    quiet(lib)
    turn = followup.request_turn(lib.store, lib.rid, QUESTION, 1, None,
                                [{"kind": "passage", "ref_id": pid, "text": "SYNTHETIC quoted sentence"},
                                 {"kind": "text", "ref_id": None, "text": "SYNTHETIC my own words"}])
    context = followup.conversation(lib.store, lib.rid, "SYNTHETIC question", turn)
    bound, free = context["attachments"]
    assert bound["bound"] is True and bound["text"] == "SYNTHETIC quoted sentence"
    assert bound["bindings"][0]["version_label"] == lib.store.conn.execute(
        "SELECT version_label FROM source_versions WHERE id = ?", (svid,)).fetchone()[0]
    assert free == {"ordinal": 2, "kind": "text", "text": "SYNTHETIC my own words", "bound": False,
                    "unresolved": None, "bindings": [], "more_bindings": 0}
    # Nothing in the record carries a passage id: it is context, never evidence.
    assert "passage_id" not in json.dumps(context["attachments"])


# ---- deletion --------------------------------------------------------------------------------------------------

def test_a_selection_keeps_its_source_from_being_deleted_and_a_purge_removes_it(tmp_path):
    lib = setup(tmp_path, n=2)
    svid = lib.sources[1]
    pid = passages(lib, svid)[0]
    quiet(lib)
    turn = followup.request_turn(lib.store, lib.rid, QUESTION, 1, None,
                                [{"kind": "passage", "ref_id": pid, "text": "SYNTHETIC"}])
    assert svid in lib.store.cited_source_versions([svid])
    lib.store.update_run(turn["run_id"], status="cancelled")
    with transaction(lib.store.conn):
        lib.store.conn.execute("UPDATE researches SET trashed_at = ? WHERE id = ?", (now(), lib.rid))
    lib.store.purge_research(lib.rid)
    assert lib.store.conn.execute("SELECT COUNT(*) FROM followup_turn_attachments").fetchone()[0] == 0
    assert lib.store.conn.execute("SELECT COUNT(*) FROM followup_turn_attachment_bindings").fetchone()[0] == 0


def test_a_follow_up_sentence_that_turn_never_wrote_is_refused(tmp_path):
    lib = setup(tmp_path, n=1)
    quiet(lib)
    turn = followup.request_turn(lib.store, lib.rid, QUESTION, 1, None, [])
    with transaction(lib.store.conn):
        lib.store.conn.execute(
            "UPDATE followup_turns SET status = 'no_passages', draft_json = ?, published_at = ?,"
            " selection_revision = 0, user_signature = 'x' WHERE id = ?",
            (json.dumps({"claims": [{"claim_label": "c1", "text": "SYNTHETIC."}]}), now(), turn["id"]))
    assert resolve(lib, "followup_claim", f"{turn['id']}:c1")["unresolved_reason"] == "claim_has_no_citation"
    with pytest.raises(attachments.AttachmentRefused):
        resolve(lib, "followup_claim", f"{turn['id']}:c999")


def test_the_model_reads_at_most_eight_places_of_one_selection_and_is_told_the_rest(tmp_path):
    lib = setup(tmp_path, n=1, pdf=True)
    svid = lib.sources[-1]
    ids = passages(lib, svid)
    item = {"id": "fua_one", "ordinal": 1, "kind": "cell", "selected_text": "SYNTHETIC", "unresolved_reason": None,
            "bindings": [{"passage_id": pid, "source_version_id": svid, "work_id": work_of(lib, svid),
                          "version_label": None, "locator": None} for pid in ids]}
    # Every binding reached the call, so all of them count; only the first eight are listed.
    (record,) = attachments.context(lib.store, [item], [pid for pid in ids])
    assert len(record["bindings"]) == min(len(ids), attachments.MAX_CONTEXT_BINDINGS)
    assert record["more_bindings"] == max(0, len(ids) - attachments.MAX_CONTEXT_BINDINGS)
    assert record["bound"] is True
    # None of them reached the call: the text stays and the record says it was not given.
    (none_given,) = attachments.context(lib.store, [item], [])
    assert none_given["bound"] is False and none_given["unresolved"] == "not_given"
    assert none_given["text"] == "SYNTHETIC"


def test_before_an_answer_is_published_it_is_not_known_what_the_model_was_given(tmp_path):
    lib = setup(tmp_path, n=1)
    svid = lib.sources[0]
    pid = passages(lib, svid)[0]
    quiet(lib)
    turn = followup.request_turn(lib.store, lib.rid, QUESTION, 1, None,
                                [{"kind": "passage", "ref_id": pid, "text": "SYNTHETIC"}])
    view = followup.turn_view(lib.store, dict(lib.store.conn.execute(
        "SELECT * FROM followup_turns WHERE id = ?", (turn["id"],)).fetchone()))
    (item,) = view["attachments"]
    assert [b["given"] for b in item["bindings"]] == [None]
