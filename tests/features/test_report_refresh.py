"""A later file renews the report claims it fed: a new version over a newer answer's frozen evidence.

The refresh carries a section only when the model would be asked the same question, and it never overwrites or drops
a sentence the person wrote. Synthetic model output throughout, so these show workflow order, not writing quality.
"""

import json

import pytest
from fastapi.testclient import TestClient

from deixis.domain.rules import RevisionConflict
from deixis.storage import db
from deixis.workflow.features.report import report_refresh as refresh_mod
from deixis.workflow.features.report.report_store import ReportStore
from test_api_flow import create, include_sources, run_to_end, session, wait_run
from test_evidence_answer_view import answer_run_id, answered, settle
from test_study_table_opening import ColumnAdapter, app_for

# ---- the evidence diff ------------------------------------------------------------------------------------------

def view(rows=None, cells=None, columns=None, **extra):
    return {"table_id": "tbl_one", "table_revision": 1, "bound_to_answer": True, "answer_run_id": "run_one",
            "rows": rows if rows is not None else [{"source_version_id": "srv_one", "passage_ids": ["psg_a"],
                                                    "reading_depth": "abstract", "membership": "included"}],
            "columns": columns if columns is not None else [
                {"column_id": "col_one", "name": "Finding", "revision": 1, "answer_format": "text",
                 "instruction": "What did it find?"}],
            "cells": cells if cells is not None else [
                {"cell_id": "cel_one", "column_id": "col_one", "source_version_id": "srv_one", "state": "value",
                 "value": {"text": "a finding"}, "cell_revision_id": "crv_one", "reading_depth": "abstract",
                 "depth_narrowed": False, "compared_method": None, "condition": None, "direction": None,
                 "evidence": [{"passage_id": "psg_a", "quote": "SYNTHETIC sentence"}]}],
            "corpus": {"included": 1, "full_text": 0}, "reading": {"full_text": 0}, **extra}


def test_an_unchanged_view_is_no_change_at_all():
    assert refresh_mod.diff(view(), view())["any"] is False


@pytest.mark.parametrize("field, changed", [
    ("changed_cells", {"cells": [dict(view()["cells"][0], cell_revision_id="crv_two")]}),
    ("changed_cells", {"cells": [dict(view()["cells"][0], value={"text": "another finding"})]}),
    ("changed_cells", {"cells": [dict(view()["cells"][0],
                                      evidence=[{"passage_id": "psg_a", "quote": "SYNTHETIC other sentence"}])]}),
    ("changed_cells", {"cells": [dict(view()["cells"][0], condition="at 50 nodes")]}),
    ("added_rows", {"rows": [view()["rows"][0], {"source_version_id": "srv_two", "passage_ids": [],
                                                 "reading_depth": "metadata", "membership": "included"}]}),
    ("removed_rows", {"rows": []}),
    ("rows_read_differently", {"rows": [dict(view()["rows"][0], passage_ids=["psg_a", "psg_b"])]}),
    ("rows_read_differently", {"rows": [dict(view()["rows"][0], reading_depth="full_text")]}),
    ("rows_read_differently", {"rows": [dict(view()["rows"][0], membership="abstract_only")]}),
    ("revised_columns", {"columns": [dict(view()["columns"][0], revision=2)]}),
    ("revised_columns", {"columns": [dict(view()["columns"][0], instruction="Something else entirely")]}),
])
def test_the_diff_names_what_changed(field, changed):
    """Everything a section's question can be built from is measured, not only a cell's revision."""
    record = refresh_mod.diff(view(), view(**changed))
    assert record["any"] is True and record[field], record
    assert record["keys"], record


def test_a_changed_corpus_or_reading_record_is_a_change():
    assert refresh_mod.diff(view(), view(corpus={"included": 2, "full_text": 1}))["corpus_changed"] is True
    assert refresh_mod.diff(view(), view(reading={"full_text": 2}))["reading_changed"] is True


# ---- the fingerprint -------------------------------------------------------------------------------------------

def test_the_same_evidence_through_another_answer_run_is_the_same_fingerprint():
    """A second answer that freezes an equivalent view must not let the same evidence be published twice."""
    changes = refresh_mod.diff(view(), view(reading={"full_text": 2}))
    first = refresh_mod.fingerprint("rpt_base", view(reading={"full_text": 2}, answer_run_id="run_a"), changes)
    second = refresh_mod.fingerprint("rpt_base", view(reading={"full_text": 2}, answer_run_id="run_b"), changes)
    assert first == second


def test_a_different_corpus_or_reading_record_is_a_different_fingerprint():
    changes = refresh_mod.diff(view(), view(corpus={"included": 2, "full_text": 1}))
    one = refresh_mod.fingerprint("rpt_base", view(corpus={"included": 2, "full_text": 1}), changes)
    two = refresh_mod.fingerprint("rpt_base", view(corpus={"included": 3, "full_text": 1}), changes)
    three = refresh_mod.fingerprint("rpt_base", view(corpus={"included": 2, "full_text": 1}, reading={"full_text": 9}),
                                    changes)
    assert len({one, two, three}) == 3
    assert refresh_mod.fingerprint("rpt_other", view(corpus={"included": 2, "full_text": 1}), changes) != one


# ---- the carried plan ------------------------------------------------------------------------------------------

def test_a_plan_pointing_outside_the_new_view_is_named():
    """A carried plan may not name a column or a passage the new evidence does not hold."""
    plan = {"axes": [{"axis_id": "AX1", "label": "Method", "column_id": "col_gone"}],
            "glossary": [{"term": "DBR", "definition": "d", "passage_id": "psg_gone"}],
            "limitations_column_id": "col_one", "future_work_column_id": None}
    missing = refresh_mod.plan_references_missing(plan, view())
    assert sorted(missing) == ["axis:AX1", "glossary:DBR"]
    ok = {"axes": [{"axis_id": "AX1", "label": "Method", "column_id": "col_one"}],
          "glossary": [{"term": "DBR", "definition": "d", "passage_id": "psg_a"}],
          "limitations_column_id": None, "future_work_column_id": None}
    assert refresh_mod.plan_references_missing(ok, view()) == []


def test_the_carried_plan_takes_its_corpus_and_budgets_from_the_new_evidence():
    base_plan = {"scope_statement": "s", "axes": [], "glossary": [], "corpus": {"included": 9},
                 "section_budgets": {"III": {"max_words": 1}}, "allowed_support": {}}
    snapshot = view() | {"corpus": {"included": 2, "full_text": 1}, "row_counts": {"completed": 2}}
    carried = refresh_mod.carried_plan(base_plan, snapshot)
    assert carried["corpus"] == {"included": 2, "full_text": 1}
    assert carried["section_budgets"]["III"]["max_words"] > 1
    assert carried["scope_statement"] == "s"  # the question and the scope are the ones already read
    assert base_plan["corpus"] == {"included": 9}  # the earlier version's own plan is untouched


# ---- the question ----------------------------------------------------------------------------------------------

def test_two_inputs_of_different_runs_ask_the_same_question():
    """Only what names the run is taken out; everything the model is shown is compared."""
    payload = {"step_input_id": "sti_one", "run_id": "run_one", "step_id": "stp_one", "created_at": "t1",
               "task_type": "report_section", "scope_revision": 1, "skill_package_hash": "h",
               "report_target": {"report_id": "rpt_one", "section_id": "III", "cells": [], "columns": []},
               "sources": [], "passages": [], "candidates": [], "allowlist": {"column_ids": []}}
    other = dict(payload, step_input_id="sti_two", run_id="run_two", step_id="stp_two", created_at="t2",
                 report_target={"report_id": "rpt_two", "section_id": "III", "cells": [], "columns": []})
    assert refresh_mod.question_text(payload) == refresh_mod.question_text(other)
    assert refresh_mod.question_text(dict(other, skill_package_hash="h2")) != refresh_mod.question_text(payload)
    assert refresh_mod.question_text(
        dict(other, report_target={"report_id": "rpt_two", "section_id": "IV", "cells": [], "columns": []})
    ) != refresh_mod.question_text(payload)


# ---- citations -------------------------------------------------------------------------------------------------

def payload_for(passages=(), cells=(), allow_passages=None, allow_cells=None):
    """A section's stored input: the records that section was given, and nothing else."""
    return {"passages": [{"passage_id": pid, "text": text} for pid, text in passages],
            "report_target": {"section_id": "III", "cells": list(cells)},
            "allowlist": {"passage_ids": list(allow_passages if allow_passages is not None else [p for p, _ in passages]),
                          "cell_ids": list(allow_cells if allow_cells is not None else [c["cell_id"] for c in cells])}}


def link(**extra):
    return {"id": "rln_one", "claim_id": "rcl_one", "claim_key": "C1", "section_id": "III", "passage_id": "psg_a",
            "cell_id": None, "source_version_id": "srv_one", "step_input_id": "sti_old",
            "anchor_text": "SYNTHETIC sentence", "anchor_match": "exact", **extra}


PAGE = (("psg_a", "A paragraph with a SYNTHETIC sentence in it."), ("psg_b", "Another page."))


def test_a_citation_holds_only_where_its_own_step_was_given_the_text():
    """Not "somewhere in the new evidence": the record must be one this section was given, and the quote in it."""
    given = payload_for(passages=PAGE[:1])
    assert refresh_mod.relocate(None, [link()], {}, given) == {"rln_one": "exact"}
    # A page this section was not given is no basis, whatever it says.
    assert refresh_mod.relocate(None, [link(passage_id="psg_b")], {}, payload_for(passages=PAGE)) is None
    # Given to the step but kept out of its allowlist: still no basis.
    assert refresh_mod.relocate(None, [link()], {}, payload_for(passages=PAGE, allow_passages=[])) is None
    assert refresh_mod.relocate(None, [link(anchor_text="a sentence nobody wrote")], {}, given) is None
    assert refresh_mod.relocate(None, [link(anchor_text=None)], {}, given) is None


def test_a_cell_citation_is_relocated_in_the_quotes_the_step_was_given():
    cell = {"cell_id": "cel_one", "state": "value", "value": {"text": "a finding"},
            "evidence": [{"passage_id": "psg_a", "quote": "SYNTHETIC sentence"}]}
    given = payload_for(cells=[cell])
    held = link(passage_id=None, cell_id="cel_one")
    assert refresh_mod.relocate(None, [held], {}, given) == {"rln_one": "exact"}
    assert refresh_mod.relocate(None, [dict(held, cell_id="cel_gone")], {}, given) is None
    assert refresh_mod.relocate(None, [dict(held, anchor_text="not in the quote")], {}, given) is None


def test_the_match_kind_is_read_from_where_the_quote_is_found_now():
    """The earlier version's match kind is never copied; it is what locating the quote in this text gives."""
    from deixis.domain import contracts

    text = "A paragraph with a SYNTHETIC-\nsentence in it."
    found = contracts.locate_anchor("SYNTHETIC sentence", text)
    assert found is not None and found.kind != "exact"  # a hyphenated line break is not an exact match
    assert refresh_mod.relocate(None, [link(anchor_match="exact")], {},
                                payload_for(passages=(("psg_a", text),))) == {"rln_one": found.kind}


def test_an_equivalent_view_frozen_at_another_time_is_the_same_evidence():
    """Two answers that bound the same rows, text and cells are one state of the evidence, whenever they ran."""
    changes = refresh_mod.diff(view(), view(reading={"full_text": 2}))
    early = view(reading={"full_text": 2}, answer_run_id="run_a", cutoff_at="2026-11-01T00:00:00Z",
                 basis={"note": "one"})
    late = view(reading={"full_text": 2}, answer_run_id="run_b", cutoff_at="2026-11-09T00:00:00Z",
                basis={"note": "another"})
    assert refresh_mod.fingerprint("rpt_base", early, changes) == refresh_mod.fingerprint("rpt_base", late, changes)


# ---- the library -----------------------------------------------------------------------------------------------

def test_the_library_records_a_refresh_and_whose_words_a_carried_claim_is(tmp_path):
    conn = db.connect(tmp_path / "library.sqlite")
    db.migrate(conn)
    reports = {row[1] for row in conn.execute("PRAGMA table_info(reports)")}
    assert {"refreshed_from_report_id", "refresh_answer_run_id", "refresh_fingerprint"} <= reports
    assert "carried_from_section_id" in {row[1] for row in conn.execute("PRAGMA table_info(report_sections)")}
    claims = {row[1] for row in conn.execute("PRAGMA table_info(report_claims)")}
    assert {"carried_from", "carried_text_origin"} <= claims
    assert "carried_from_step_input_id" in {row[1] for row in conn.execute("PRAGMA table_info(report_citation_links)")}
    # Any number of ordinary reports hold no fingerprint; one state of the evidence is published once.
    conn.execute("INSERT INTO researches (id, title, created_at, updated_at)"
                 " VALUES ('res_one', 'SYNTHETIC research', 'n', 'n')")
    for name in ("run_one", "run_two", "run_three"):
        conn.execute("INSERT INTO runs (id, research_id, scope_revision, kind, status, stage, budget_json,"
                     " created_at, updated_at) VALUES (?, 'res_one', 1, 'report', 'completed', 'extraction', '{}',"
                     " 'n', 'n')", (name,))
    rows = [("rpt_one", "run_one", None), ("rpt_two", "run_two", None), ("rpt_three", "run_three", "fp")]
    for report_id, run_id, stamp in rows:
        conn.execute("INSERT INTO reports (id, research_id, run_id, scope_revision, status, created_at, updated_at,"
                     " refresh_fingerprint) VALUES (?, 'res_one', ?, 1, 'valid', 'n', 'n', ?)",
                     (report_id, run_id, stamp))
    with pytest.raises(Exception):
        conn.execute("INSERT INTO reports (id, research_id, run_id, scope_revision, status, created_at, updated_at,"
                     " refresh_fingerprint) VALUES ('rpt_four', 'res_one', 'run_one', 1, 'valid', 'n', 'n', 'fp')")


# ---- end to end ------------------------------------------------------------------------------------------------

def report_of(client, rid, table_id):
    started = client.post(f"/api/researches/{rid}/reports", json={"table_id": table_id})
    assert started.status_code == 202, started.text
    report_id = started.json()["target"]["report_id"]
    _, run = wait_run(client, rid, started.json()["id"])
    return report_id, run


def change_a_cell(client, rid, table_id):
    """A person's own reading of one cell: the row's finding changes, as a later file changes it."""
    table = client.get(f"/api/researches/{rid}/tables/{table_id}").json()
    for cell in table["cells"]:
        url = (f"/api/researches/{rid}/tables/{table_id}/cells/{cell['column_id']}"
               f"/{cell['source_version_id']}")
        answer = client.put(url, json={"state": "not_reported", "note": "SYNTHETIC later reading.",
                                       "expected_version": cell["version"]})
        if answer.status_code == 200:
            return True
    return False


def test_a_refresh_stands_on_the_chosen_answer_and_keeps_the_earlier_version(tmp_path):
    """The new version is written from the newer answer's view; the earlier report keeps everything it had."""
    with TestClient(app_for(tmp_path, ColumnAdapter())) as client:
        store = client.app.state.store
        session(client)
        rid = create(client)
        _, first_view = answered(client, store, rid)
        table_id = first_view["table_id"]
        base_id, base_run = report_of(client, rid, table_id)
        assert base_run["status"] in ("completed", "failed")
        base = client.get(f"/api/researches/{rid}/reports/{base_id}").json()
        if base["status"] != "valid":
            pytest.skip("the synthetic report did not finalize as valid in this run")

        assert change_a_cell(client, rid, table_id)
        run_to_end(client, rid, "answer")
        settle(client, rid)
        second = answer_run_id(store, rid)

        offer = client.get(f"/api/researches/{rid}/reports/{base_id}/refresh-offer").json()
        assert offer["can_refresh"] is True and offer["answer_run_id"] == second
        started = client.post(f"/api/researches/{rid}/reports/{base_id}/refresh",
                              json={"answer_run_id": second})
        assert started.status_code == 202, started.text
        new_id = started.json()["target"]["report_id"]
        _, run = wait_run(client, rid, started.json()["id"])
        settle(client, rid)

        # The new version rests on that answer's frozen view, and says which report and answer it came from.
        saved = json.loads(store.conn.execute(
            "SELECT snapshot_json FROM report_snapshot WHERE report_id = ?", (new_id,)).fetchone()["snapshot_json"])
        assert saved["answer_run_id"] == second and saved["bound_to_answer"] is True
        fresh = client.get(f"/api/researches/{rid}/reports/{new_id}").json()
        assert fresh["refreshed_from_report_id"] == base_id and fresh["refresh_answer_run_id"] == second
        assert "refresh_fingerprint" not in fresh
        # No plan was asked: the earlier version's plan is the one in it.
        assert store.existing_step(run["id"], "report_plan") is None
        reports = ReportStore(store)
        assert reports.report(new_id)["plan"]["scope_statement"] == reports.report(base_id)["plan"]["scope_statement"]
        # The decision is a record of its own, taken before anything was sent.
        decision = store.existing_step(run["id"], refresh_mod.DECISION_KEY)
        assert decision is not None and decision["status"] == "succeeded"
        assert set(decision["output"]["carried"]) | set(decision["output"]["rewritten"]) == set(refresh_mod.CARRYABLE)

        # Everything of the earlier version is where it was.
        again = client.get(f"/api/researches/{rid}/reports/{base_id}").json()
        assert again["report_version"] == base["report_version"] and again["status"] == base["status"]
        assert [section["claims"] for section in again["sections"]] == [s["claims"] for s in base["sections"]]
        if fresh["status"] == "valid":
            assert fresh["report_version"] == base["report_version"] + 1
            # Every citation of the new version locates in the evidence it was written from.
            assert refresh_mod.citations_not_located(store, reports, new_id) == []
        # A derived section is never carried, whatever the evidence did.
        carried = {section["section_id"] for section in fresh["sections"] if section["carried"]}
        assert carried <= set(refresh_mod.CARRYABLE)
        # The same evidence cannot be published again.
        with pytest.raises(RevisionConflict, match="already_refreshed"):
            reports.request_refresh(rid, base_id, second, None)


def test_a_refresh_refuses_what_it_cannot_honestly_do(tmp_path, monkeypatch):
    """Each refusal by name: nothing changed, no newer answer, and a person's words in a rewritten section."""
    with TestClient(app_for(tmp_path, ColumnAdapter())) as client:
        store = client.app.state.store
        session(client)
        rid = create(client)
        _, first_view = answered(client, store, rid)
        table_id = first_view["table_id"]
        base_id, _ = report_of(client, rid, table_id)
        base = client.get(f"/api/researches/{rid}/reports/{base_id}").json()
        if base["status"] != "valid":
            pytest.skip("the synthetic report did not finalize as valid in this run")
        reports = ReportStore(store)
        first_answer = answer_run_id(store, rid)

        # The answer this report was written from is not a newer one.
        with pytest.raises(RevisionConflict, match="refresh_needs_a_new_answer"):
            reports.request_refresh(rid, base_id, first_answer, None)
        assert client.get(f"/api/researches/{rid}/reports/{base_id}/refresh-offer").json()["reason"] \
            == "refresh_needs_a_new_answer"

        run_to_end(client, rid, "answer")
        settle(client, rid)
        second = answer_run_id(store, rid)
        # A newer answer over evidence that did not change is nothing to refresh from.
        monkeypatch.setattr(refresh_mod, "diff", lambda base, view: {"any": False, "keys": []})
        with pytest.raises(RevisionConflict, match="nothing_changed"):
            reports.request_refresh(rid, base_id, second, None)
        assert client.get(f"/api/researches/{rid}/reports/{base_id}/refresh-offer").json()["reason"] \
            == "nothing_changed"
        monkeypatch.undo()

        # A sentence the person wrote in a section every refresh writes again stops the refresh before it starts.
        derived = next((section for section in base["sections"]
                        if section["section_id"] not in refresh_mod.CARRYABLE and section["claims"]), None)
        assert derived is not None
        claim = derived["claims"][0]
        edited = client.put(f"/api/researches/{rid}/reports/{base_id}/claims/{claim['id']}",
                            json={"text": "A sentence the person wrote.", "expected_version": claim["version"]})
        assert edited.status_code < 300, edited.text
        assert change_a_cell(client, rid, table_id)
        run_to_end(client, rid, "answer")
        settle(client, rid)
        third = answer_run_id(store, rid)
        with pytest.raises(RevisionConflict, match="person_edited_derived_section"):
            reports.request_refresh(rid, base_id, third, None)
        offer = client.get(f"/api/researches/{rid}/reports/{base_id}/refresh-offer").json()
        assert offer["can_refresh"] is False and offer["reason"] == "person_edited_derived_section"
        assert offer["sections"]["person_edited"] == [derived["section_id"]]


def refresh_with_a_carried_section(client, store, rid, base_id, answer_run_id, monkeypatch, only="III"):
    """Run a refresh with the question comparison stubbed to hold for one section.

    What is under test here is the carrying itself - the claims, the citations and the record of whose words they
    are. Whether two inputs ask the same question is tested on its own, over the text a model is sent.
    """
    monkeypatch.setattr(refresh_mod, "same_question",
                        lambda base_row, payload, base, developer, schema:
                        payload["report_target"]["section_id"] == only)
    started = client.post(f"/api/researches/{rid}/reports/{base_id}/refresh", json={"answer_run_id": answer_run_id})
    assert started.status_code == 202, started.text
    _, run = wait_run(client, rid, started.json()["id"])
    settle(client, rid)
    return started.json()["target"]["report_id"], run


def test_a_carried_section_is_the_sentences_the_reader_read_with_their_own_citations(tmp_path, monkeypatch):
    """A section whose question did not change is copied: same text, same effective links, no model call."""
    with TestClient(app_for(tmp_path, ColumnAdapter())) as client:
        store = client.app.state.store
        session(client)
        rid = create(client)
        _, first_view = answered(client, store, rid)
        table_id = first_view["table_id"]
        base_id, _ = report_of(client, rid, table_id)
        base = client.get(f"/api/researches/{rid}/reports/{base_id}").json()
        if base["status"] != "valid":
            pytest.skip("the synthetic report did not finalize as valid in this run")
        base_three = next(section for section in base["sections"] if section["section_id"] == "III")
        if not base_three["claims"]:
            pytest.skip("the synthetic III has no claim to carry")

        assert change_a_cell(client, rid, table_id)
        run_to_end(client, rid, "answer")
        settle(client, rid)
        second = answer_run_id(store, rid)
        new_id, run = refresh_with_a_carried_section(client, store, rid, base_id, second, monkeypatch)

        decision = store.existing_step(run["id"], refresh_mod.DECISION_KEY)["output"]
        assert decision["carried"] == ["III"] and sorted(decision["rewritten"]) == ["IV", "V"]
        fresh = client.get(f"/api/researches/{rid}/reports/{new_id}").json()
        three = next(section for section in fresh["sections"] if section["section_id"] == "III")
        assert three["carried"] is True
        assert [claim["text"] for claim in three["claims"]] == [c["text"] for c in base_three["claims"]]
        assert [claim["claim_key"] for claim in three["claims"]] == [c["claim_key"] for c in base_three["claims"]]
        assert [len(claim["evidence"]) for claim in three["claims"]] == [len(c["evidence"]) for c in base_three["claims"]]
        assert all(claim["carried_from"] for claim in three["claims"])
        assert {claim["carried_text_origin"] for claim in three["claims"]} == {"model"}
        # The record says what carrying checked, and what it did not.
        carried = three["validation"]["carried"]
        assert carried["from_report_id"] == base_id and carried["input_identical"] is True
        assert carried["citations_relocated"] is True and carried["not_checked"] == ["semantic_support"]
        # No section of the new report is bound to another run's input record, and the earlier one is kept.
        links = [dict(row) for row in store.conn.execute(
            "SELECT l.step_input_id, l.carried_from_step_input_id FROM report_citation_links l"
            " JOIN report_claims c ON c.id = l.claim_id JOIN report_sections s ON s.id = c.report_section_id"
            " WHERE s.report_id = ? AND s.section_id = 'III'", (new_id,))]
        assert links and all(link["carried_from_step_input_id"] for link in links)
        own = {row["id"] for row in store.conn.execute(
            "SELECT si.id FROM step_inputs si JOIN run_steps st ON st.id = si.step_id WHERE st.run_id = ?",
            (run["id"],))}
        assert all(link["step_input_id"] in own for link in links)
        assert all(link["carried_from_step_input_id"] not in own for link in links)
        # A carried section asks nothing: its step succeeded without a model session.
        step = store.existing_step(run["id"], "report_section:III")
        assert step["status"] == "succeeded" and step["output"]["carried_from_report_id"] == base_id
        assert store.conn.execute(
            "SELECT COUNT(*) FROM model_sessions m JOIN step_inputs si ON si.id = m.step_input_id"
            " WHERE si.step_id = ?", (step["id"],)).fetchone()[0] == 0


def test_a_carried_claim_keeps_the_persons_own_sentence_and_says_so(tmp_path, monkeypatch):
    """The person's wording outranks the model's, and the new version records whose words it carries."""
    with TestClient(app_for(tmp_path, ColumnAdapter())) as client:
        store = client.app.state.store
        session(client)
        rid = create(client)
        _, first_view = answered(client, store, rid)
        table_id = first_view["table_id"]
        base_id, _ = report_of(client, rid, table_id)
        base = client.get(f"/api/researches/{rid}/reports/{base_id}").json()
        if base["status"] != "valid":
            pytest.skip("the synthetic report did not finalize as valid in this run")
        base_three = next(section for section in base["sections"] if section["section_id"] == "III")
        if not base_three["claims"]:
            pytest.skip("the synthetic III has no claim to carry")
        claim = base_three["claims"][0]
        mine = "The person's own sentence about this evidence."
        edited = client.put(f"/api/researches/{rid}/reports/{base_id}/claims/{claim['id']}",
                            json={"text": mine, "expected_version": claim["version"]})
        assert edited.status_code < 300, edited.text

        assert change_a_cell(client, rid, table_id)
        run_to_end(client, rid, "answer")
        settle(client, rid)
        second = answer_run_id(store, rid)
        new_id, run = refresh_with_a_carried_section(client, store, rid, base_id, second, monkeypatch)

        fresh = client.get(f"/api/researches/{rid}/reports/{new_id}").json()
        three = next(section for section in fresh["sections"] if section["section_id"] == "III")
        carried = next(item for item in three["claims"] if item["claim_key"] == claim["claim_key"])
        assert carried["text"] == mine and carried["carried_text_origin"] == "human_edit"
        assert three["validation"]["carried"]["person_edited_claims"] == [claim["claim_key"]]
        # The sentence the assembly checks read is the person's, not the model's.
        assert store.conn.execute(
            "SELECT text FROM report_claims WHERE id = ?", (carried["id"],)).fetchone()["text"] == mine


def test_a_person_edited_section_that_must_be_written_again_pauses_the_run(tmp_path):
    """Nobody's sentence is replaced in silence: the run stops with the section named and the decision left open."""
    with TestClient(app_for(tmp_path, ColumnAdapter())) as client:
        store = client.app.state.store
        session(client)
        rid = create(client)
        _, first_view = answered(client, store, rid)
        table_id = first_view["table_id"]
        base_id, _ = report_of(client, rid, table_id)
        base = client.get(f"/api/researches/{rid}/reports/{base_id}").json()
        if base["status"] != "valid":
            pytest.skip("the synthetic report did not finalize as valid in this run")
        base_three = next(section for section in base["sections"] if section["section_id"] == "III")
        if not base_three["claims"]:
            pytest.skip("the synthetic III has no claim to edit")
        claim = base_three["claims"][0]
        assert client.put(f"/api/researches/{rid}/reports/{base_id}/claims/{claim['id']}",
                          json={"text": "A sentence the person wrote.",
                                "expected_version": claim["version"]}).status_code < 300

        assert change_a_cell(client, rid, table_id)
        run_to_end(client, rid, "answer")
        settle(client, rid)
        second = answer_run_id(store, rid)
        started = client.post(f"/api/researches/{rid}/reports/{base_id}/refresh", json={"answer_run_id": second})
        assert started.status_code == 202, started.text
        _, run = wait_run(client, rid, started.json()["id"])

        assert run["status"] == "paused" and run["pause_reason"] == "person_edited_section_must_be_rewritten"
        # The earlier version is whole, and nothing was published.
        again = client.get(f"/api/researches/{rid}/reports/{base_id}").json()
        assert again["status"] == "valid" and again["report_version"] == base["report_version"]
        new_id = started.json()["target"]["report_id"]
        assert client.get(f"/api/researches/{rid}/reports/{new_id}").json()["status"] == "in_progress"


def test_a_version_with_a_citation_that_does_not_locate_is_not_published(tmp_path, monkeypatch):
    """A carried sentence is no way for an unlocated citation to reach a delivered report."""
    with TestClient(app_for(tmp_path, ColumnAdapter())) as client:
        store = client.app.state.store
        session(client)
        rid = create(client)
        _, first_view = answered(client, store, rid)
        table_id = first_view["table_id"]
        base_id, _ = report_of(client, rid, table_id)
        if client.get(f"/api/researches/{rid}/reports/{base_id}").json()["status"] != "valid":
            pytest.skip("the synthetic report did not finalize as valid in this run")
        assert change_a_cell(client, rid, table_id)
        run_to_end(client, rid, "answer")
        settle(client, rid)
        second = answer_run_id(store, rid)

        monkeypatch.setattr(refresh_mod, "citations_not_located",
                            lambda store_, reports_, report_id_: [
                                {"claim_key": "C1", "section_id": "III", "passage_id": "psg_gone", "cell_id": None}])
        started = client.post(f"/api/researches/{rid}/reports/{base_id}/refresh", json={"answer_run_id": second})
        assert started.status_code == 202, started.text
        new_id = started.json()["target"]["report_id"]
        _, run = wait_run(client, rid, started.json()["id"])
        settle(client, rid)

        fresh = client.get(f"/api/researches/{rid}/reports/{new_id}").json()
        assert fresh["status"] == "draft" and fresh["report_version"] is None
        assert store.conn.execute(
            "SELECT 1 FROM events WHERE run_id = ? AND type = 'refresh_citation_not_located'",
            (run["id"],)).fetchone() is not None


def test_rebuilding_a_sections_input_over_the_same_evidence_asks_the_same_question(tmp_path):
    """The comparison on the real path with nothing stubbed: the same evidence is the same question.

    The summaries of the sections written before it are taken from the stored input, because they depend on how far
    the report had got when the section was written and a finished report cannot say that any more. Everything else -
    the plan, the columns and their instructions, the selected cells with their quotes, the passages, the corpus and
    reading records, the count domain, the instructions and the output schema - is rebuilt and compared. Without
    this, a field a model step fills in on its own (`review_sections`) makes every section look changed and the
    refresh carries nothing.
    """
    from deixis.domain.rules import step_model
    from deixis.workflow.features.report import report_sections as sections_mod

    with TestClient(app_for(tmp_path, ColumnAdapter())) as client:
        store = client.app.state.store
        session(client)
        rid = create(client)
        _, first_view = answered(client, store, rid)
        base_id, base_run = report_of(client, rid, first_view["table_id"])
        if client.get(f"/api/researches/{rid}/reports/{base_id}").json()["status"] != "valid":
            pytest.skip("the synthetic report did not finalize as valid in this run")
        flow = client.app.state.worker.flow
        reports = ReportStore(store)
        snapshot, plan = reports.snapshot(base_id), reports.report(base_id)["plan"]
        scope, model = store.scope(rid), step_model(scope := store.scope(rid), "report_section")
        run = dict(store.run(base_run["id"]))
        compared = 0
        for section_id in refresh_mod.CARRYABLE:
            section = reports.section(base_id, section_id)
            stored = refresh_mod._base_step_input(store, section["step_id"])
            if stored is None or section["status"] != "valid":
                continue
            target, evidence, _ = sections_mod.section_target(flow, reports, base_id, plan, snapshot, section_id)
            target["validation_context"] = sections_mod._validation_context(flow, base_id, snapshot, section_id)
            target["prior_summaries"] = json.loads(stored["payload_json"])["report_target"]["prior_summaries"]
            source_ids = list(dict.fromkeys([p["source_version_id"] for p in evidence["passages"]]
                                            + [c["source_version_id"] for c in evidence["cells"]]))
            payload = flow._step_input(run, scope, "stp_rebuilt", "report_section", [], source_ids,
                                       evidence["passages"], [], model, report_target=target)
            base_text, developer, schema = refresh_mod._instructions(flow, model)
            assert refresh_mod.same_question(stored, payload, base_text, developer, schema), section_id
            # A changed question is seen as one: the count domain is part of the input.
            changed = dict(target, validation_context=dict(target["validation_context"], source_ids=[]))
            other = flow._step_input(run, scope, "stp_rebuilt", "report_section", [], source_ids,
                                     evidence["passages"], [], model, report_target=changed)
            assert not refresh_mod.same_question(stored, other, base_text, developer, schema), section_id
            compared += 1
        assert compared, "no section of the synthetic report had a stored input to compare"
