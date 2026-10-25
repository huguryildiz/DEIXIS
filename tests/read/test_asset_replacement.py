"""P5 slice 2 (D45): replacing the PDF in use, its API, and model inputs after a replacement.

Records and model outputs are SYNTHETIC (scripted FakeAdapter). Passing these tests shows which passages later steps read
and that earlier evidence keeps its passages; it says nothing about extraction or model quality.
"""

from collections import Counter
from types import SimpleNamespace
import pytest
from deixis.workflow.store import RunInProgress, SameFile
from test_table_extraction import cell, execute, fill, library, recheck, stored_inputs


PAGES = ["SYNTHETIC page one: packets of 128 bytes minimize energy per bit.", "SYNTHETIC page two: a relay forwards each packet once."]


def extraction(pages):
    return SimpleNamespace(status="succeeded", error=None, page_count=len(pages),
                           pages=[SimpleNamespace(physical_page=n, printed_label=None, text=text) for n, text in enumerate(pages, 1)])


def replace(lib, pages, sha):
    (old,) = {p["asset_id"] for p in lib.store.passages_for(lib.published) if p["asset_id"]}
    new = lib.store.replace_asset(old, sha, 10, f"{sha}.pdf", "user_upload", None, "new.pdf", extraction(pages), "test-v1",
                                  lambda text: [(0, len(text), text)])
    return old, new


def test_replacing_keeps_old_evidence_and_later_steps_read_only_the_new_file(tmp_path):
    lib = library(tmp_path)
    assert execute(lib, fill(lib))["status"] == "completed"
    before = cell(lib, lib.published)["current"]
    cited = {e["passage_id"] for e in before["evidence"]}
    selection = lib.store.selection_revision(lib.rid)

    old, new = replace(lib, PAGES, "9" * 64)  # the same text in another file

    asset = lib.store.asset(old)
    assert (asset["removal_reason"], asset["replaced_by_asset_id"]) == ("replaced", new) and asset["removed_at"] is not None
    links = lambda view: [(e["passage_id"], e["anchor_text"]) for e in view["evidence"]]
    after = cell(lib, lib.published)["current"]
    assert (after["id"], links(after)) == (before["id"], links(before))
    assert all(lib.store.passage(pid)["asset_id"] == old for pid in cited)
    live = lib.store.passages_for(lib.published)
    assert {p["asset_id"] for p in live} == {new} and not cited & {p["id"] for p in live}
    assert lib.store.selection_revision(lib.rid) == selection  # the selection did not change
    assert [e["type"] for e in lib.store.events_after(lib.rid, 0)].count("asset_replaced") == 1

    run = recheck(lib, lib.published, cell(lib, lib.published)["version"])
    assert execute(lib, run)["status"] == "completed"
    (payload,) = stored_inputs(lib, run["id"])
    assert set(payload["allowlist"]["passage_ids"]) == {p["id"] for p in live}
    assert max(Counter(p["text"] for p in payload["passages"]).values()) == 1
    assert payload["extraction_target"]["passage_scope"] == {"given": 2, "available": 2, "all_pages_given": True}


def test_an_answer_input_after_a_replacement_has_each_text_once(tmp_path):
    lib = library(tmp_path)
    replace(lib, PAGES, "9" * 64)
    scope = lib.store.scope(lib.rid)
    given = lib.flow._retrieve(lib.rid, scope, [lib.published], 48)
    assert sorted(p["id"] for p in given) == sorted(p["id"] for p in lib.store.passages_for(lib.published))
    assert max(Counter(p["text"] for p in given).values()) == 1


def test_replacing_is_refused_for_the_same_file_a_removed_file_or_during_a_run(tmp_path):
    lib = library(tmp_path)
    (old,) = {p["asset_id"] for p in lib.store.passages_for(lib.published) if p["asset_id"]}
    sha = lib.store.asset(old)["sha256"]
    with pytest.raises(SameFile):
        lib.store.replace_asset(old, sha, 10, f"{sha}.pdf", "user_upload", None, "p.pdf", extraction(PAGES), "test-v1", lambda t: [(0, len(t), t)])
    fill(lib)  # queued
    with pytest.raises(RunInProgress):
        replace(lib, ["SYNTHETIC other"], "8" * 64)
    assert lib.store.asset(old)["removed_at"] is None


# ---- T15 part of slice 2: backup, restore and permanent deletion keep replaced files and both extractions --------
