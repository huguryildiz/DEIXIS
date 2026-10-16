"""P5 slice 2 (D45): what earlier cell evidence and answer quotes show after a PDF is removed, replaced or re-extracted.

Records and model outputs are SYNTHETIC (scripted FakeAdapter). Passing shows the recorded evidence keeps resolving and is
marked; it says nothing about whether the new text supports the old value.
"""

import time
from types import SimpleNamespace

from fastapi.testclient import TestClient

from deixis.workflow import table_refresh
from deixis.workflow.tables import TableStore
from fakes import valid_response
from helpers import make_pdf
from test_api_flow import app_for, create, session, wait_run
from test_asset_replacement import PAGES, extraction, replace
from test_table_extraction import add_pdf, cell, execute, fill, library, recheck, table_version

CHUNK = lambda text: [(0, len(text), text)]  # noqa: E731


def filled(tmp_path):
    lib = library(tmp_path)
    assert execute(lib, fill(lib))["status"] == "completed"
    return lib


def statuses(view):
    return {e["evidence_status"] for e in view["current"]["evidence"]}


def test_cell_evidence_is_marked_by_what_happened_to_its_file(tmp_path):
    lib = filled(tmp_path / "current")
    assert statuses(cell(lib, lib.published)) == {"current"} and cell(lib, lib.published)["flags"] == []
    assert statuses(cell(lib, lib.preprint)) == {"current"}  # abstracts have no file

    lib = filled(tmp_path / "removed")
    (asset,) = {p["asset_id"] for p in lib.store.passages_for(lib.published) if p["asset_id"]}
    lib.store.remove_asset(lib.rid, lib.published, asset)
    view = cell(lib, lib.published)
    assert statuses(view) == {"pdf_removed"} and "pdf_removed" in view["flags"]

    lib = filled(tmp_path / "replaced")
    replace(lib, PAGES, "9" * 64)
    view = cell(lib, lib.published)
    assert statuses(view) == {"pdf_replaced"} and "pdf_replaced" in view["flags"]

    lib = filled(tmp_path / "reextracted")
    (asset,) = {p["asset_id"] for p in lib.store.passages_for(lib.published) if p["asset_id"]}
    assert lib.store.reextract_asset(asset, extraction([p.upper() for p in PAGES]), "test-v2", CHUNK)["outcome"] == "current"
    view = cell(lib, lib.published)
    assert statuses(view) == {"text_superseded"} and "text_superseded" in view["flags"]
    assert view["current"]["evidence"][0]["physical_page"] in (1, 2)


def test_a_stale_fill_proposes_for_cells_whose_evidence_is_shadowed(tmp_path):
    lib = filled(tmp_path)
    current = cell(lib, lib.published)["current"]
    replace(lib, PAGES, "9" * 64)

    assert lib.published not in {s["source_version_id"] for s in lib.tables.fill_plan(lib.rid, lib.tid)["sources"]}
    planned = {s["source_version_id"] for s in lib.tables.fill_plan(lib.rid, lib.tid, include_stale=True)["sources"]}
    assert planned == {lib.published}  # the preprint's abstract evidence is still current

    assert execute(lib, fill(lib, include_stale=True))["status"] == "completed"
    view = cell(lib, lib.published)
    assert view["current"]["id"] == current["id"]
    assert view["pending_proposal"] is not None and statuses({"current": view["pending_proposal"]}) == {"current"}


def test_the_recheck_estimate_counts_shadowed_cells_until_a_proposal_waits(tmp_path):
    lib = filled(tmp_path)
    assert lib.tables.table_view(lib.rid, lib.tid)["recheck_estimate"]["cells"] == 0
    replace(lib, PAGES, "9" * 64)
    assert lib.tables.table_view(lib.rid, lib.tid)["recheck_estimate"]["cells"] == 1

    assert execute(lib, fill(lib, include_stale=True))["status"] == "completed"
    assert lib.tables.table_view(lib.rid, lib.tid)["recheck_estimate"]["cells"] == 0  # asking again would repeat the waiting proposal


def test_a_value_read_before_pdf_text_arrived_is_offered_for_a_recheck(tmp_path):
    lib = filled(tmp_path)
    before = cell(lib, lib.preprint)
    assert before["current"] and "newer_text" not in before["flags"]
    add_pdf(lib.store, lib.preprint, ["SYNTHETIC preprint full text: packets of 96 bytes were best."], "7" * 64)

    view = cell(lib, lib.preprint)
    assert "newer_text" in view["flags"] and statuses(view) == {"current"}  # the abstract it cites is still current
    assert lib.tables.table_view(lib.rid, lib.tid)["recheck_estimate"]["cells"] == 1
    assert execute(lib, fill(lib, include_stale=True))["status"] == "completed"
    view = cell(lib, lib.preprint)
    assert view["current"]["id"] == before["current"]["id"] and view["pending_proposal"] is not None


# ---- D52: an automatic re-read when PDF text arrives ------------------------------------------------------------
def arrive(lib, svid, text="SYNTHETIC preprint full text: packets of 96 bytes were best.", sha="7"):
    time.sleep(0.005)  # timestamps have millisecond resolution; the text must come after the value it is compared with
    return add_pdf(lib.store, svid, [text], sha * 64)


def citing(kind):
    """A scripted model that quotes the first given passage of one kind: the PDF page or the abstract."""
    def respond(si):
        first = [p for p in si["passages"] if (p["locator"]["kind"] == "abstract") == (kind == "abstract")]
        return valid_response(si | {"passages": first + [p for p in si["passages"] if p not in first]})
    return respond


def once(action):
    done = []

    def before(si):
        if si["task_type"] == "cell_extraction" and not done:
            done.append(True)
            action()
    return before


def runs(lib):
    return lib.conn.execute("SELECT COUNT(*) FROM runs").fetchone()[0]


def test_a_model_value_read_from_the_abstract_is_read_again_by_itself_when_pdf_text_arrives(tmp_path):
    lib = filled(tmp_path)
    lib.adapter.responder = citing("pdf")
    before = cell(lib, lib.preprint)
    assert before["current"]["reading_depth"] == "abstract" and table_refresh.advance(lib.store) == []
    arrive(lib, lib.preprint)
    assert {"newer_text", "newer_text_auto"} <= set(cell(lib, lib.preprint)["flags"])

    (run,) = table_refresh.advance(lib.store)
    assert run["kind"] == "table_fill" and run["target"]["auto_refresh"] is True
    assert [s["source_version_id"] for s in run["target"]["sources"]] == [lib.preprint]
    assert execute(lib, run)["status"] == "completed"
    view = cell(lib, lib.preprint)
    current = view["current"]
    assert (current["kind"], current["author"], current["reading_depth"]) == ("model_fill", "model", "selected_sections")
    assert current["based_on_revision_id"] == before["current"]["id"] and view["pending_proposal"] is None
    assert [r["id"] for r in view["revisions"]] == [before["current"]["id"], current["id"]]  # the old reading stays in history
    assert "newer_text" not in view["flags"] and table_refresh.advance(lib.store) == []


def test_a_system_placeholder_for_a_source_without_text_is_read_once_its_pdf_arrives(tmp_path):
    lib = filled(tmp_path)
    assert cell(lib, lib.no_text)["current"]["kind"] == "system_fill"
    arrive(lib, lib.no_text, "SYNTHETIC scanned report text: packets of 32 bytes.", "8")
    (run,) = table_refresh.advance(lib.store)
    assert execute(lib, run)["status"] == "completed"
    current = cell(lib, lib.no_text)["current"]
    assert (current["kind"], current["state"], current["reading_depth"]) == ("model_fill", "value", "selected_sections")


def test_a_value_a_person_wrote_is_not_read_again_by_itself(tmp_path):
    lib = filled(tmp_path)
    version = cell(lib, lib.preprint)["version"]
    human = lib.tables.edit_cell(lib.rid, lib.tid, lib.cid, lib.preprint, "not_verified", {"number": 70, "unit": "byte"}, None, None,
                                 version, None)
    arrive(lib, lib.preprint)
    view = cell(lib, lib.preprint)
    assert "newer_text" in view["flags"] and "newer_text_auto" not in view["flags"]
    count = runs(lib)
    assert table_refresh.advance(lib.store) == [] and runs(lib) == count
    assert cell(lib, lib.preprint)["current"]["id"] == human


def plans(monkeypatch):
    """Count the fill plans the sweep makes: an idle sweep over cells it has nothing to do for must make none."""
    made = []
    original = TableStore.fill_plan
    monkeypatch.setattr(TableStore, "fill_plan", lambda self, *a, **k: made.append(1) or original(self, *a, **k))
    return made


def test_the_sweep_queues_one_run_waits_for_other_runs_and_does_not_retry_a_failed_one(tmp_path, monkeypatch):
    lib = filled(tmp_path)
    asset = arrive(lib, lib.preprint)
    other = lib.tables.request_recheck(lib.rid, lib.tid, lib.cid, lib.published, cell(lib, lib.published)["version"], None)
    count = runs(lib)
    assert table_refresh.advance(lib.store) == [] and runs(lib) == count  # another run of the research is queued
    lib.store.update_run(other["id"], status="cancelled")

    (first,) = table_refresh.advance(lib.store)
    assert table_refresh.advance(lib.store) == [] and runs(lib) == count + 1  # its own run is now the queued one
    lib.store.update_run(first["id"], status="failed")
    made = plans(monkeypatch)
    assert table_refresh.advance(lib.store) == [] and made == [] and runs(lib) == count + 1  # not retried, not even planned
    view = cell(lib, lib.preprint)
    assert view["current"]["reading_depth"] == "abstract"
    assert "newer_text_auto_stopped" in view["flags"] and "newer_text_auto" not in view["flags"]  # a person rechecks it now

    lib.store.remove_asset(lib.rid, lib.preprint, asset)  # the person swaps in another file
    arrive(lib, lib.preprint, "SYNTHETIC preprint second file: packets of 80 bytes.", "9")  # new text: the cell is due again
    assert "newer_text_auto" in cell(lib, lib.preprint)["flags"]
    (second,) = table_refresh.advance(lib.store)
    assert second["id"] != first["id"] and runs(lib) == count + 2


def test_a_table_with_more_due_sources_than_one_run_reads_moves_on_after_a_failed_run(tmp_path, monkeypatch):
    lib = library(tmp_path)
    extra = [lib.store.create_upload_source(f"D SYNTHETIC scanned report {n:02d}") for n in range(26)]
    for svid in extra:
        lib.store.add_to_corpus(lib.rid, svid, "user_upload", selection_state="included", selection_origin="user")
    lib.tables.add_rows(lib.rid, lib.tid, extra, table_version(lib))
    while lib.tables.fill_plan(lib.rid, lib.tid)["sources"]:  # 29 rows: two fills of at most 25 sources
        assert execute(lib, fill(lib))["status"] == "completed"
    time.sleep(0.005)
    due = [lib.no_text, *extra]
    for n, svid in enumerate(due):  # 27 placeholders get their PDF text
        add_pdf(lib.store, svid, [f"SYNTHETIC scanned report {n}: packets of {n} bytes."], f"{n + 16:064x}")

    (first,) = table_refresh.advance(lib.store)
    planned = [s["source_version_id"] for s in first["target"]["sources"]]
    assert len(planned) == 25
    lib.store.update_run(first["id"], status="failed")
    (second,) = table_refresh.advance(lib.store)  # the next sources, not the 25 the failed run covered
    assert sorted(s["source_version_id"] for s in second["target"]["sources"]) == sorted(set(due) - set(planned))
    lib.store.update_run(second["id"], status="failed")
    count, made = runs(lib), plans(monkeypatch)
    assert table_refresh.advance(lib.store) == [] and made == [] and runs(lib) == count  # nothing new: no plan at all


def test_a_person_who_edits_the_cell_before_the_re_read_is_saved_gets_a_proposal(tmp_path):
    lib = filled(tmp_path)
    lib.adapter.responder = citing("pdf")
    arrive(lib, lib.preprint)
    (run,) = table_refresh.advance(lib.store)
    human = lib.tables.edit_cell(lib.rid, lib.tid, lib.cid, lib.preprint, "not_verified", {"number": 70, "unit": "byte"}, None, None,
                                 cell(lib, lib.preprint)["version"], None)
    assert execute(lib, run)["status"] == "completed"
    view = cell(lib, lib.preprint)
    assert view["current"]["id"] == human and view["pending_proposal"]["reading_depth"] == "selected_sections"


def test_a_cell_with_a_waiting_proposal_is_left_to_the_person(tmp_path, monkeypatch):
    lib = filled(tmp_path)
    arrive(lib, lib.preprint)
    checked = lib.tables.request_recheck(lib.rid, lib.tid, lib.cid, lib.preprint, cell(lib, lib.preprint)["version"], None)
    assert execute(lib, checked)["status"] == "completed"
    view = cell(lib, lib.preprint)
    assert view["pending_proposal"] is not None and "newer_text_auto" not in view["flags"]
    count, made = runs(lib), plans(monkeypatch)
    assert table_refresh.advance(lib.store) == [] and made == [] and runs(lib) == count


def test_a_proposal_older_than_the_value_does_not_wait_or_block_the_re_read(tmp_path):
    lib = library(tmp_path)
    # A recheck of the empty cell proposes; a fill then gives the cell its abstract value, newer than that proposal.
    assert execute(lib, recheck(lib, lib.preprint, 0))["status"] == "completed"
    assert execute(lib, fill(lib))["status"] == "completed"
    view = cell(lib, lib.preprint)
    assert view["current"]["reading_depth"] == "abstract" and view["pending_proposal"] is None and "proposal_before_edit" not in view["flags"]
    assert lib.tables.table_view(lib.rid, lib.tid)["counts"]["pending_proposals"] == 0

    lib.adapter.responder = citing("pdf")
    arrive(lib, lib.preprint)
    (run,) = table_refresh.advance(lib.store)
    assert execute(lib, run)["status"] == "completed"
    view = cell(lib, lib.preprint)
    assert view["current"]["reading_depth"] == "selected_sections" and view["pending_proposal"] is None
    assert lib.tables.table_view(lib.rid, lib.tid)["counts"]["pending_proposals"] == 0
    assert [r["decision"] for r in view["revisions"] if r["kind"] == "model_proposal"] == ["superseded"]


def test_an_older_proposal_left_after_the_latest_was_dismissed_does_not_wait_or_block_the_re_read(tmp_path):
    lib = filled(tmp_path)
    for _ in range(2):  # proposal A, then proposal B
        assert execute(lib, recheck(lib, lib.preprint, cell(lib, lib.preprint)["version"]))["status"] == "completed"
    a, b = [r["id"] for r in cell(lib, lib.preprint)["revisions"] if r["kind"] == "model_proposal"]
    lib.tables.decide_proposal(lib.rid, lib.tid, lib.cid, lib.preprint, b, False, cell(lib, lib.preprint)["version"], None)
    view = cell(lib, lib.preprint)
    assert view["pending_proposal"] is None and lib.tables.table_view(lib.rid, lib.tid)["counts"]["pending_proposals"] == 0
    assert [(r["id"], r["decision"]) for r in view["revisions"] if r["kind"] == "model_proposal"] == [(a, "superseded"), (b, "dismissed")]

    lib.adapter.responder = citing("pdf")
    arrive(lib, lib.preprint)
    assert "newer_text_auto" in cell(lib, lib.preprint)["flags"]
    (run,) = table_refresh.advance(lib.store)  # the sweep reads A as the view does: nothing waits
    assert execute(lib, run)["status"] == "completed"
    assert cell(lib, lib.preprint)["current"]["reading_depth"] == "selected_sections"


def test_a_proposal_newer_than_the_value_still_waits(tmp_path):
    lib = filled(tmp_path)
    assert execute(lib, recheck(lib, lib.preprint, cell(lib, lib.preprint)["version"]))["status"] == "completed"
    view = cell(lib, lib.preprint)
    assert view["pending_proposal"] is not None and "proposal_before_edit" not in view["flags"]
    assert [r["decision"] for r in view["revisions"] if r["kind"] == "model_proposal"] == ["pending"]
    assert lib.tables.table_view(lib.rid, lib.tid)["counts"]["pending_proposals"] == 1


def test_answer_quotes_and_passages_show_a_replaced_pdf_and_the_old_file_opens_only_where_cited(tmp_path):
    app = app_for(tmp_path)
    with TestClient(app) as raw:
        client = session(raw)
        rid = create(client, source_scope="attached")
        store = app.state.store
        client.post(f"/api/researches/{rid}/uploads", files={"file": ("notes.pdf", make_pdf(["SYNTHETIC uploaded molecule schedule notes."]), "application/pdf")})
        view, run = wait_run(client, rid, client.post(f"/api/researches/{rid}/runs", json={"kind": "answer"}).json()["id"])
        assert run["status"] == "completed", run
        answer = view["answers"][0]
        evidence = answer["claims"][0]["evidence"][0]
        assert evidence["evidence_status"] == "current" and answer["source_text_changed"] is False
        svid = evidence["source_version_id"]
        (old,) = store.conn.execute("SELECT id FROM source_assets WHERE source_version_id = ?", (svid,)).fetchone()

        replaced = client.put(f"/api/researches/{rid}/sources/{svid}/assets/{old}",
                              files={"file": ("better.pdf", make_pdf(["SYNTHETIC uploaded molecule schedule notes, full scan."]), "application/pdf")})
        answer = replaced.json()["answers"][0]
        assert answer["claims"][0]["evidence"][0]["evidence_status"] == "pdf_replaced"
        assert answer["claims"][0]["evidence"][0]["passage_id"] == evidence["passage_id"]
        assert answer["source_text_changed"] is True and answer["applicability"] == "current"

        passage = client.get(f"/api/researches/{rid}/passages/{evidence['passage_id']}").json()
        assert (passage["evidence_status"], passage["asset_id"]) == ("pdf_replaced", old)
        assert client.get(f"/api/researches/{rid}/assets/{old}").status_code == 200  # cited here: read-only old PDF

        other = create(client, question="SYNTHETIC research B", source_scope="attached")
        store.add_to_corpus(other, svid, "user_upload", selection_state="included", selection_origin="user")
        assert client.get(f"/api/researches/{other}/assets/{old}").status_code == 404  # nothing in B cites the old file

        (new,) = store.conn.execute("SELECT id FROM source_assets WHERE source_version_id = ? AND removed_at IS NULL", (svid,)).fetchone()
        client.delete(f"/api/researches/{rid}/sources/{svid}/assets/{new}")
        assert client.get(f"/api/researches/{rid}/assets/{new}").status_code == 404  # a mistaken file stays closed


def test_an_answer_counts_the_works_whose_full_text_was_read_after_it_started(tmp_path):
    app = app_for(tmp_path)
    with TestClient(app) as raw:
        client = session(raw)
        rid = create(client, source_scope="attached")
        store = app.state.store
        client.post(f"/api/researches/{rid}/uploads", files={"file": ("notes.pdf", make_pdf(["SYNTHETIC uploaded molecule schedule notes."]), "application/pdf")})
        view, run = wait_run(client, rid, client.post(f"/api/researches/{rid}/runs", json={"kind": "answer"}).json()["id"])
        assert view["answers"][0]["fulltext_read_since"] == 0
        svid = view["answers"][0]["claims"][0]["evidence"][0]["source_version_id"]

        def decide(outcome, by, created_at, superseded_at=None):  # one current decision per work: the last one stands
            store.conn.execute("UPDATE stage_decisions SET superseded_at = ? WHERE research_id = ? AND source_version_id = ?"
                               " AND stage = 'fulltext' AND superseded_at IS NULL", (created_at, rid, svid))
            store.conn.execute(
                "INSERT INTO stage_decisions (id, research_id, source_version_id, stage, outcome, reason_code, decided_by,"
                " next_step, scope_revision, superseded_at, created_at) VALUES (?, ?, ?, 'fulltext', ?, 'SYNTHETIC', ?, 'none', 1, ?, ?)",
                (f"sd_{outcome}_{by}_{created_at}", rid, svid, outcome, by, superseded_at, created_at))
        decide("include", "model_agreement", "2000-01-01T00:00:00+00:00")  # read before the answer: not counted
        decide("unresolved", "code", "2999-01-01T00:00:00+00:00")  # code saying the file was not read: not counted
        decide("include", "model_agreement", "2999-01-01T00:00:01+00:00", superseded_at="2999-01-02")  # superseded
        assert client.get(f"/api/researches/{rid}").json()["answers"][0]["fulltext_read_since"] == 0
        decide("criterion_not_met", "model_agreement", "2999-01-01T00:00:02+00:00")  # a reading that excluded it counts
        assert client.get(f"/api/researches/{rid}").json()["answers"][0]["fulltext_read_since"] == 1


def refreshed_after(tmp_path, responder=None, during=None):
    """Arrive PDF text for the preprint, run its automatic re-read and return the cell's value before and its view after."""
    lib = filled(tmp_path)
    lib.adapter.responder = responder or citing("pdf")
    asset = arrive(lib, lib.preprint)
    before = cell(lib, lib.preprint)["current"]
    if during:
        lib.adapter.before = once(lambda: during(lib, asset))
    (run,) = table_refresh.advance(lib.store)
    assert execute(lib, run)["status"] == "completed"
    return before, cell(lib, lib.preprint)


def test_a_re_read_that_still_cites_only_the_abstract_waits_as_a_proposal(tmp_path):
    before, view = refreshed_after(tmp_path, responder=citing("abstract"))
    assert view["current"]["id"] == before["id"] and view["pending_proposal"] is not None
    assert {e["kind"] for e in view["pending_proposal"]["evidence"]} == {"abstract"}


def test_a_pdf_removed_while_the_model_reads_it_leaves_the_re_read_a_proposal(tmp_path):
    before, view = refreshed_after(tmp_path, during=lambda lib, asset: lib.store.remove_asset(lib.rid, lib.preprint, asset))
    assert view["current"]["id"] == before["id"] and view["pending_proposal"] is not None


def test_a_column_edited_while_the_model_reads_leaves_the_re_read_a_proposal(tmp_path):
    def edit(lib, asset):
        column = lib.tables.table_view(lib.rid, lib.tid)["columns"][0]
        lib.tables.revise_column(lib.rid, lib.tid, lib.cid, {"instruction": "Report the largest packet size."}, None, column["version"])

    before, view = refreshed_after(tmp_path, during=edit)
    assert view["current"]["id"] == before["id"] and view["pending_proposal"]["column_revision"] == 1
