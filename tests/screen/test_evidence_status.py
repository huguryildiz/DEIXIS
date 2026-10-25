"""P5 slice 2 (D45): what earlier cell evidence and answer quotes show after a PDF is removed, replaced or re-extracted.

Records and model outputs are SYNTHETIC (scripted FakeAdapter). Passing shows the recorded evidence keeps resolving and is
marked; it says nothing about whether the new text supports the old value.
"""

import time


from deixis.workflow.features.tables import table_refresh
from deixis.workflow.features.tables.tables import TableStore
from fakes import valid_response
from test_asset_replacement import PAGES, extraction, replace
from test_table_extraction import add_pdf, cell, execute, fill, library

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


def test_a_pdf_removed_while_the_model_reads_it_leaves_the_re_read_a_proposal(tmp_path):
    before, view = refreshed_after(tmp_path, during=lambda lib, asset: lib.store.remove_asset(lib.rid, lib.preprint, asset))
    assert view["current"]["id"] == before["id"] and view["pending_proposal"] is not None


def test_a_column_edited_while_the_model_reads_leaves_the_re_read_a_proposal(tmp_path):
    def edit(lib, asset):
        column = lib.tables.table_view(lib.rid, lib.tid)["columns"][0]
        lib.tables.revise_column(lib.rid, lib.tid, lib.cid, {"instruction": "Report the largest packet size."}, None, column["version"])

    before, view = refreshed_after(tmp_path, during=edit)
    assert view["current"]["id"] == before["id"] and view["pending_proposal"]["column_revision"] == 1
