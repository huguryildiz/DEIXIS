"""A work the person includes after the read cutoff reaches a new answer and a follow-up, one version per work.

SYNTHETIC data only: records, abstracts, pages and model outputs are made up by the fixtures."""

import asyncio
import json

import pytest

from deixis.providers.common import ProviderRecord
from deixis.workflow import fast_answer, followup
from deixis.workflow.decisions import DecisionStore
from deixis.workflow.flow import RunStopped
from test_criterion_passage_flow import TOPIC_PAGE, page_source
from test_fast_path_answer import answer_run, candidate, cutoff, setup, user


def later_work(lib, name="later"):
    """A SYNTHETIC work that joins the research after the cutoff (as a follow-up search would add it)."""
    return candidate(lib.store, lib.rid, name, f"SYNTHETIC {name} exercise improves fatigue.", "runs_agree_candidate")


def published_version(lib, svid, name="published"):
    """A SYNTHETIC published version (its own DOI) of `svid`'s work; it heads the work."""
    record = ProviderRecord(provider_record_id=name, title=f"SYNTHETIC {name}", authors=[], year=None, venue=None,
                            publication_type=None, doi=f"10.5555/synthetic.{name}", landing_url=None, oa_pdf_url=None,
                            oa_pdf_version=None, version_label=None, abstract=f"SYNTHETIC {name} exercise.",
                            abstract_origin="provider", identifiers={}, raw={})
    new, _ = lib.store.upsert_provider_source("known_list", record, None)
    work = lib.store.source(svid)["work_id"]
    lib.store.conn.execute("UPDATE source_versions SET work_id = ? WHERE id = ?", (work, new))
    lib.store.add_to_corpus(lib.rid, new, "search")
    assert lib.store.work_heads(lib.rid)[work] == new
    return new


def read_pdf(lib, svid):
    """Two SYNTHETIC model readings of `svid`'s file in use that include the work (as `inspected_pdf`)."""
    item = lib.flow._plan_item(svid, svid)
    plan = lib.store.step(lib.discovery["id"], f"synthetic:adjudication_plan:{svid}", "code:adjudication_plan")
    lib.store.finish_step(plan["id"], "succeeded", output={"works": [item]})
    target = {"source_id": svid, "criterion": "SYNTHETIC model", "parts": [
        {"name": "model", "definition": "SYNTHETIC model"}], "runs": 2, "run": 1}

    async def read():
        for n in (1, 2):
            await lib.flow._model_step(lib.discovery, lib.store.scope(lib.rid),
                f"fulltext_adjudication:{svid}:{n}", "fulltext_adjudication", source_ids=[svid],
                passage_rows=[p for p in lib.store.passages_for(svid) if p["kind"] == "pdf_page"],
                adjudication_target=target | {"run": n})
    asyncio.run(read())
    step = lib.store.existing_step(lib.discovery["id"], f"fulltext_adjudication:{svid}:2")
    DecisionStore(lib.store).record(lib.rid, svid, "all_parts_verified", step_id=step["id"])
    return item


def pdf_work(lib, name="pdfwork"):
    """A SYNTHETIC work with an abstract and a three-page file, joined after the cutoff and included by the person."""
    svid = page_source(lib.store, lib.rid, name, [TOPIC_PAGE] * 3, "SYNTHETIC exercise.")
    DecisionStore(lib.store).record(lib.rid, svid, "runs_agree_candidate")
    return svid


def pages_of(lib, svid):
    return [p["id"] for p in lib.store.passages_for(svid) if p["kind"] == "pdf_page"]


def abstract_of(lib, svid):
    return [p["id"] for p in lib.store.passages_for(svid) if p["kind"] == "abstract"][:1]


def plan_of(lib, run=None):
    return fast_answer.input_plan(lib.flow, run or answer_run(lib), lib.store.scope(lib.rid))


def test_a_work_included_after_the_cutoff_is_one_row_read_from_its_answer_version(tmp_path):
    lib = setup(tmp_path)
    cutoff(lib)
    preprint = later_work(lib)
    head = published_version(lib, preprint)
    user(lib, head, "included")
    run = answer_run(lib)
    plan = plan_of(lib, run)
    work = lib.store.source(head)["work_id"]
    rows = [r for r in plan["items"] if r["work_id"] == work]
    assert len(rows) == 1 and len(plan["items"]) == 2
    (row,) = rows
    assert row["added_after_cutoff"] is True and row["head_after_cutoff"] == head
    assert row["source_version_id"] == lib.store.answer_version(lib.rid, head)
    assert row["route"] == "abstract" and row["user_priority"] and row["reason"] is None
    assert set(row["abstract_ids"]) <= set(plan["passage_ids"]) and row["abstract_ids"]
    assert preprint not in {lib.store.passage(pid)["source_version_id"] for pid in plan["passage_ids"]}
    fast_answer.check_input(lib.flow, run["id"], plan)
    assert fast_answer.added_after_cutoff_view(lib.store, run["id"]) == [
        {"work_id": work, "source_version_id": row["source_version_id"], "head_after_cutoff": head, "route": "abstract"}]


def test_a_read_file_gives_its_pages_and_an_unread_file_only_its_abstract(tmp_path):
    lib = setup(tmp_path)
    cutoff(lib)
    read, unread = pdf_work(lib, "read"), pdf_work(lib, "unread")
    item = read_pdf(lib, read)
    plan = plan_of(lib)
    rows = {r["source_version_id"]: r for r in plan["items"] if r.get("added_after_cutoff")}
    assert rows[read]["route"] == "fulltext" and rows[read]["asset_id"] == item["asset_id"]
    assert rows[read]["fulltext_ids"] == pages_of(lib, read)
    assert rows[unread]["route"] == "abstract" and rows[unread]["fulltext_ids"] == []
    assert not set(pages_of(lib, unread)) & set(plan["passage_ids"])


@pytest.mark.parametrize("trigger", [{"trigger": "auto_after_discovery"},
                                     {"trigger": "late_fulltext", "late_revision_id": "SYNTHETIC"}])
def test_an_automatic_answer_or_a_late_revision_adds_no_row(tmp_path, trigger):
    lib = setup(tmp_path)
    cutoff(lib)
    user(lib, later_work(lib), "included")
    run = answer_run(lib)
    lib.store.conn.execute("UPDATE runs SET budget_json = json_patch(budget_json, ?) WHERE id = ?",
                           (json.dumps(trigger), run["id"]))
    plan = plan_of(lib, lib.store.run(run["id"]))
    assert not any(r.get("added_after_cutoff") for r in plan["items"]) and len(plan["items"]) == 1


@pytest.mark.parametrize("choice", ["excluded", "pending", "human_only", "model_only"])
def test_only_the_persons_inclusion_of_the_head_adds_a_row(tmp_path, choice):
    lib = setup(tmp_path)
    cutoff(lib)
    svid = later_work(lib)
    if choice in ("excluded", "pending"):
        user(lib, svid, choice)
    elif choice == "human_only":
        DecisionStore(lib.store).record(lib.rid, svid, "human_include")
    plan = plan_of(lib)
    assert not any(r.get("added_after_cutoff") for r in plan["items"]) and len(plan["items"]) == 1


def test_a_choice_on_another_version_than_the_head_adds_no_row(tmp_path):
    lib = setup(tmp_path)
    cutoff(lib)
    preprint = later_work(lib)
    user(lib, preprint, "included")
    published_version(lib, preprint)
    assert not any(r.get("added_after_cutoff") for r in plan_of(lib)["items"])


def test_a_work_without_a_text_version_is_listed_and_gives_no_row(tmp_path, monkeypatch):
    lib = setup(tmp_path)
    cutoff(lib)
    svid = later_work(lib)
    user(lib, svid, "included")
    monkeypatch.setattr(lib.store, "answer_version", lambda rid, head: None)
    plan = plan_of(lib)
    assert not any(r.get("added_after_cutoff") for r in plan["items"])
    assert {"work_id": lib.store.source(svid)["work_id"], "source_version_id": svid,
            "reason": "no_text_version"} in plan["excluded"]
    assert plan["excluded_reasons"]["no_text_version"] == 1


def test_a_work_held_by_the_cutoff_under_a_merged_record_gets_no_second_row(tmp_path):
    lib = setup(tmp_path, n=2)
    cutoff(lib)
    # The cutoff's second record joins a work found later; the person includes that work's head.
    svid = later_work(lib)
    lib.store.conn.execute("UPDATE source_versions SET work_id = ? WHERE id = ?",
                           (lib.store.source(svid)["work_id"], lib.sources[1]))
    user(lib, svid, "included")
    assert not any(r.get("added_after_cutoff") for r in plan_of(lib)["items"])


def test_check_input_pauses_when_the_head_changes(tmp_path):
    lib = setup(tmp_path)
    cutoff(lib)
    svid = later_work(lib)
    user(lib, svid, "included")
    run = answer_run(lib)
    plan = plan_of(lib, run)
    fast_answer.check_input(lib.flow, run["id"], plan)
    published_version(lib, svid)
    with pytest.raises(RunStopped):
        fast_answer.check_input(lib.flow, run["id"], plan)
    assert lib.store.run(run["id"])["pause_reason"] == "source_changed"


def test_check_input_pauses_when_the_file_in_use_changes(tmp_path, monkeypatch):
    lib = setup(tmp_path)
    cutoff(lib)
    svid = pdf_work(lib)
    item = read_pdf(lib, svid)
    run = answer_run(lib)
    plan = plan_of(lib, run)
    assert next(r for r in plan["items"] if r.get("added_after_cutoff"))["route"] == "fulltext"
    fast_answer.check_input(lib.flow, run["id"], plan)
    # The pages read are still current, but the record's file in use is no longer the one read.
    current = lib.flow._current_asset
    monkeypatch.setattr(lib.flow, "_current_asset",
                        lambda v: "SYNTHETIC newer file" if v == svid else current(v))
    assert lib.flow._current_asset(svid) != item["asset_id"]
    with pytest.raises(RunStopped):
        fast_answer.check_input(lib.flow, run["id"], plan)
    assert lib.store.run(run["id"])["pause_reason"] == "source_changed"


def answered(lib):
    run = answer_run(lib)
    asyncio.run(fast_answer.answer(lib.flow, run, lib.store.scope(lib.rid)))
    return run


def test_a_work_included_after_the_answer_gives_the_follow_up_what_an_answer_row_would(tmp_path):
    lib = setup(tmp_path)
    cutoff(lib)
    answered(lib)
    plain, read, unread = later_work(lib), pdf_work(lib, "read"), pdf_work(lib, "unread")
    user(lib, plain, "included")
    read_pdf(lib, read)
    frozen = followup.pool(lib.store, lib.rid, 1, lib.flow)
    assert frozen["sources"][plain] == abstract_of(lib, plain)
    assert frozen["sources"][read] == abstract_of(lib, read) + pages_of(lib, read)
    assert frozen["sources"][unread] == abstract_of(lib, unread)
    # Without the flow no reading can be checked against the file in use: the abstract only.
    assert followup.pool(lib.store, lib.rid, 1)["sources"][read] == abstract_of(lib, read)
    user(lib, plain, "excluded")
    assert plain not in followup.pool(lib.store, lib.rid, 1, lib.flow)["sources"]


def test_a_work_the_answer_holds_under_another_version_adds_nothing_and_has_no_reserve(tmp_path):
    lib = setup(tmp_path)
    cutoff(lib)
    answered(lib)
    held = lib.sources[0]
    head = published_version(lib, held)
    user(lib, head, "included")
    frozen = followup.pool(lib.store, lib.rid, 1, lib.flow)
    assert held in frozen["sources"] and head not in frozen["sources"]
    assert head not in frozen["reserve"] and held not in frozen["reserve"]
    # An included work the pool does not give still makes up the reserve, as before.
    other = later_work(lib, "other")
    lib.store.conn.execute("UPDATE selections SET state = 'included' WHERE source_version_id = ?", (other,))
    frozen = followup.pool(lib.store, lib.rid, 1, lib.flow)
    assert other in frozen["sources"] or other in frozen["reserve"]


def test_late_full_text_pages_are_appended_to_the_same_version(tmp_path):
    lib = setup(tmp_path, pdf=True)
    pdf = lib.sources[-1]
    user(lib, pdf, "included")
    cutoff(lib)
    run = answered(lib)
    row = next(r for r in lib.store.existing_step(run["id"], fast_answer.INPUT)["output"]["items"]
               if r["source_version_id"] == pdf)
    assert row["route"] == "abstract"
    read_pdf(lib, pdf)
    frozen = followup.pool(lib.store, lib.rid, 1, lib.flow)
    assert frozen["sources"][pdf] == abstract_of(lib, pdf) + pages_of(lib, pdf)
    assert list(frozen["sources"]).count(pdf) == 1 and pdf not in frozen["reserve"]


def test_two_frozen_records_merged_since_give_the_follow_up_one_version(tmp_path):
    lib = setup(tmp_path, n=2)
    cutoff(lib)
    answered(lib)
    first, second = lib.sources
    lib.store.conn.execute("UPDATE source_versions SET work_id = ? WHERE id = ?",
                           (lib.store.source(first)["work_id"], second))
    frozen = followup.pool(lib.store, lib.rid, 1, lib.flow)
    assert len({lib.store.source(svid)["work_id"] for svid in frozen["sources"]}) == len(frozen["sources"]) == 1
    works = {lib.store.source(svid)["work_id"] for svid in frozen["sources"]}
    assert not works & {lib.store.source(svid)["work_id"] for svid in frozen["reserve"]}
