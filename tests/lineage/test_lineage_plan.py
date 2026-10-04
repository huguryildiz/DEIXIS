"""L5a synthetic planning and API checks: no model or provider calls."""

import asyncio
import copy
import json
from dataclasses import replace
from types import SimpleNamespace

import httpx
import pytest
from fastapi.testclient import TestClient

from deixis.api.app import create_app
from deixis.config import Settings
from deixis.domain import contracts, skill
from deixis.domain.rules import MAX_RATE_LIMIT_MODEL_RETRIES, RevisionConflict, schema_repairs, step_model
from deixis.models import prompt
from deixis.storage import db
from deixis.workflow.flow import FlowDeps, ResearchFlow
from deixis.workflow.lineage import run as planning
from deixis.workflow.lineage.candidates import find_candidates
from deixis.workflow.lineage.mentions import PassageText, mention_rules
from deixis.workflow.lineage.store import InvalidLineageInput, LineageStore
from deixis.workflow.store import Store
from deixis.workflow.tables import TableStore
from fakes import FakeAdapter
from test_api_flow import session
from test_lineage_store import decision, human, model, proposal


class NeverAdapter(FakeAdapter):
    @property
    def messages(self):
        return self.calls

    async def run_step(self, *args, **kwargs):
        raise AssertionError("L5a must never call a model")

    async def health(self):
        raise AssertionError("L5a must never probe a model")


def attach(lib, sid, text, version="SYNTHETIC-v1"):
    extraction = SimpleNamespace(status="succeeded", error=None, page_count=1,
                                 pages=[SimpleNamespace(physical_page=1, printed_label="1", text=text)])
    aid = lib.store.add_asset_with_pages(sid, planning.text_sha256(sid + text + version), len(text), "synthetic.pdf",
                                         "user_upload", None, "synthetic.pdf", extraction, version,
                                         lambda value: [(0, len(value), value)])
    return aid


def make_env(tmp_path, n=8, *, mentions=(0,), only_target=False, all_pdf=False):
    conn = db.connect(tmp_path / "library.sqlite")
    db.migrate(conn)
    store = Store(conn)
    rid = store.create_research("SYNTHETIC development question?", "attached", "quick", [], "fake", "fake-model", "en")
    ids, passages, assets = {}, {}, {}
    order = []
    for i in range(n):
        sid = store.create_upload_source(f"SYNTHETIC source {i:03d}")
        conn.execute("UPDATE source_versions SET authors_json = ?, year = ? WHERE id = ?",
                     (json.dumps([f"SYNTHETIC Author{i:03d}"]), 2000 + i, sid))
        store.add_to_corpus(rid, sid, "user_upload", selection_state="included", selection_origin="user")
        ids[chr(97 + i) if i < 26 else str(i)] = sid
        order.append(sid)
        passages[sid] = store._insert_passage(sid, None, "abstract", None, None, "synthetic_fixture", None, None,
                                             "SYNTHETIC abstract with no mention.")
    lib = SimpleNamespace(conn=conn, store=store, rid=rid, ids=ids, order=order, assets=assets)
    for i, sid in enumerate(order):
        if all_pdf or i == 1 or (not only_target and 2 <= i <= 5):
            text = "SYNTHETIC: " + (" ".join(f"Author{j:03d} ({2000+j})" for j in mentions) if i == 1 else "no mentions here.")
            assets[sid] = attach(lib, sid, text)
            passages[sid] = next(p["id"] for p in store.passages_for(sid) if p["kind"] == "pdf_page")
    tables = TableStore(store)
    tid = tables.create_table(rid, "SYNTHETIC table", None, None, None)
    tables.add_development_columns(rid, tid, 1, None)
    generic = store.create_run(rid, "answer", {"max_model_calls": 1, "max_provider_requests": 0}, None)
    store.update_run(generic["id"], status="completed")
    seen = []

    def reject(request):
        seen.append(str(request.url))
        raise AssertionError("L5a must never call a provider")

    http = httpx.AsyncClient(transport=httpx.MockTransport(reject))
    adapter = NeverAdapter()
    flow = ResearchFlow(FlowDeps(Settings(data_dir=tmp_path / "data", port=8872), store, {"fake": adapter},
                                 skill.load_skill_package(), http))
    lib.__dict__.update(tables=tables, tid=tid, lineage=LineageStore(store), run=generic["id"], passages={
        key: passages[sid] for key, sid in ids.items()}, flow=flow, http=http, adapter=adapter, seen=seen)
    lib.planner = planning.LineagePlanner(store, flow.lineage_step_input, flow.lineage_message_chars, flow.deps.package.package_hash)
    return lib


@pytest.fixture
def factory(tmp_path):
    libraries = []

    def create(**kw):
        lib = make_env(tmp_path / str(len(libraries)), **kw)
        libraries.append(lib)
        return lib

    yield create
    for lib in libraries:
        assert lib.seen == [] and lib.adapter.messages == []
        asyncio.run(lib.http.aclose())
        lib.conn.close()


@pytest.fixture
def lib(factory):
    return factory()


def plan(lib, retry_failed=False):
    return lib.planner.build_plan(lib.rid, lib.tid, retry_failed)


def selected(plan, sid):
    return next(s for s in plan["selected"] if s["to"] == sid)


def pairs(plan):
    return {(s["to"], c["from"]): c["pair_fp"] for s in plan["selected"] for c in s["candidates"]}


def candidate(lib):
    snapshot = planning.build_snapshot(lib.store, lib.tid)
    works = tuple(replace(r.work, passages=tuple(PassageText(p["id"], p["kind"], p["text"], p["physical_page"])
                                               for p in lib.store.passages_for(r.work.source_version_id))) for r in snapshot.rows)
    c = next(c for c in find_candidates(works, excluded_pairs=snapshot.human_pairs).candidates
             if c.to_source_version_id == lib.ids["b"])
    target = planning.build_lineage_target(snapshot, (c,))
    rows = [lib.store.passage(pid) for pid in c.mention_passage_ids]
    payload = lib.flow.lineage_step_input(lib.rid, snapshot.scope_revision, target, rows, planning.PLAN_MODEL_CALL_BOUND)
    return snapshot, c, payload


def fill(lib, letter="a", role="problem", *, text="SYNTHETIC current value", quotes=None, recheck=False, status="structurally_valid"):
    sid = lib.ids[letter]
    column = next(c for c in lib.tables._columns(lib.tid) if c["lineage_role"] == role)
    step = lib.store.step(lib.run, db.new_id("op"), "model:cell_extraction")
    sti = db.new_id("sti")
    lib.store.insert_step_input(step["id"], lib.rid, lib.run, 0,
                               {"step_input_id": sti, "task_type": "cell_extraction", "scope_revision": 1,
                                "skill_package_hash": "sha256:SYNTHETIC"}, "base", "developer", "SYNTHETIC", {})
    cell = lib.tables._cell(lib.tid, column["id"], sid, create=True)
    links = [{"passage_id": lib.passages[letter], "source_version_id": sid, "anchor_text": q, "anchor_match": "exact"}
             for q in (quotes if quotes is not None else ["SYNTHETIC"])]
    return lib.tables.save_model_output(lib.rid, lib.tid, column["id"], sid,
        column_revision=column["current_revision"], state="value", value={"text": text}, note=None,
        reading_depth="selected_sections" if sid in lib.assets else "abstract", output_status=status, links=links,
        run_id=lib.run, step_id=step["id"], step_input_id=sti, model_connection="fake", resolved_model="fake-model",
        scope_revision=1, cell_version_at_request=cell["version"], recheck=recheck)


def edit_instruction(lib):
    col = lib.tables._columns(lib.tid)[0]
    lib.tables.revise_column(lib.rid, lib.tid, col["id"], {"instruction": "SYNTHETIC edited instruction"}, None, col["version"])


def record_publication(lib, frozen=None, *, outcomes=None, failed=()):
    """Store synthetic planning history without executing a model."""
    frozen = frozen or plan(lib)
    run = lib.store.create_run(lib.rid, "lineage_links", {"max_model_calls": frozen["max_model_calls"], "max_provider_requests": 0},
                                None, frozen)
    step = lib.store.step(run["id"], "lineage_publication", "lineage_publication")
    lib.store.finish_step(step["id"], "succeeded", {"targets": [
        {"to": s["to"], "target_fp": s["target_fp"], "outcome": (outcomes or {}).get(s["to"], s["outcome"]),
         "no_candidate": s["no_candidate"]} for s in frozen["selected"]], "failed_pairs": list(failed)})
    lib.store.update_run(run["id"], status="completed")
    return run, step


def assess(lib, fp, *, a="a", b="b", **kw):
    return model(lib, a, b, input_fingerprint=fp, decision=decision(lib, b, value="no_relation"), **kw)


def test_node_cells_read_only_the_current_revision(lib):
    current = fill(lib)
    pending = fill(lib, text="SYNTHETIC pending proposal", recheck=True)
    cell = planning.build_node(lib.store, lib.tid, lib.ids["a"])["cells"][0]
    assert current != pending and cell["cell_revision_id"] == current
    assert cell["value"] == "SYNTHETIC current value"


def test_node_cells_missing_role_and_missing_cell(lib):
    fill(lib, recheck=True)
    column = lib.tables._columns(lib.tid)[2]
    lib.tables.remove_column(lib.rid, lib.tid, column["id"], column["version"])
    cells = planning.build_node(lib.store, lib.tid, lib.ids["a"])["cells"]
    for cell in cells:
        assert cell["state"] == "missing" and cell["cell_id"] is None
        assert all(cell[k] is None for k in ("cell_revision_id", "column_revision", "value", "reading_depth", "output_status"))
        assert not any(cell["flags"].values()) and cell["evidence_quotes"] == []
    assert cells[0]["instruction_revision"] == 1 and cells[0]["instruction"]
    assert cells[2]["instruction"] is None and cells[2]["instruction_revision"] is None


@pytest.mark.parametrize("flag", ["pdf_removed", "pdf_replaced", "text_superseded"])
def test_node_cells_flags_and_stale_column(lib, flag):
    fill(lib, "b")
    edit_instruction(lib)
    aid = lib.assets[lib.ids["b"]]
    if flag == "text_superseded":
        lib.conn.execute("UPDATE source_assets SET extraction_version = 'SYNTHETIC-v2' WHERE id = ?", (aid,))
    else:
        lib.conn.execute("UPDATE source_assets SET removed_at = 'now', removal_reason = ? WHERE id = ?",
                         ("replaced" if flag == "pdf_replaced" else "wrong_file", aid))
    cell = planning.build_node(lib.store, lib.tid, lib.ids["b"])["cells"][0]
    assert cell["column_revision"] == 1 and cell["instruction_revision"] == 2
    assert cell["flags"][flag] and cell["flags"]["stale_column"]
    col = lib.tables._columns(lib.tid)[1]
    lib.tables.edit_cell(lib.rid, lib.tid, col["id"], lib.ids["b"], "not_verified", {"text": "SYNTHETIC unverified"},
                         None, None, 0, None)
    assert planning.build_node(lib.store, lib.tid, lib.ids["b"])["cells"][1]["flags"]["not_verified"]


def test_node_cells_evidence_quotes_order_and_no_truncation(lib):
    quotes = ["SYNTHETIC z " + "z" * 1200, None, "SYNTHETIC a " + "a" * 800]
    fill(lib, quotes=quotes)
    cell = planning.build_node(lib.store, lib.tid, lib.ids["a"])["cells"][0]
    assert cell["evidence_quotes"] == [quotes[0], quotes[2]]
    assert "passage_id" not in json.dumps(cell)


def test_node_cells_value_is_cut_at_500(lib):
    fill(lib, text="SYNTHETIC " + "x" * 700)
    assert planning.build_node(lib.store, lib.tid, lib.ids["a"])["cells"][0]["value"] == ("SYNTHETIC " + "x" * 700)[:500]


def test_built_target_passes_check_step_input(lib):
    fill(lib)
    _, _, payload = candidate(lib)
    assert contracts.check_step_input(payload) == []
    shown = contracts.with_citation_handles(payload)
    assert contracts.check_step_input(shown) == []


def test_only_current_pdf_text_makes_a_target_eligible(lib):
    assert lib.ids["a"] not in [s["to"] for s in plan(lib)["selected"]]
    aid = lib.assets[lib.ids["b"]]
    lib.conn.execute("UPDATE source_assets SET extraction_version = 'SYNTHETIC-v2' WHERE id = ?", (aid,))
    assert lib.ids["b"] not in [s["to"] for s in plan(lib)["selected"]]
    assert any(p["kind"] == "pdf_page" for p in [lib.store.passage(lib.passages["b"])])


def test_excluded_pairs_are_the_human_decided_ones(lib):
    human(lib, evidence=[{"passage_id": lib.passages["b"], "quote": "Author000 (2000)"}])
    snap = planning.build_snapshot(lib.store, lib.tid)
    assert snap.human_pairs == frozenset(lib.lineage.human_decided_pairs(lib.tid))
    assert (lib.ids["b"], lib.ids["a"]) not in pairs(plan(lib))


def test_nine_candidates_make_two_calls(factory):
    lib = factory(n=10, mentions=(0, *range(2, 10)), only_target=True)
    p = plan(lib)
    assert [len(c["from"]) for c in p["chunks"]] == [8, 1]


def test_message_over_48000_splits_a_chunk(factory):
    lib = factory(n=4, mentions=(0, 2, 3), only_target=True)
    for letter in ("a", "c", "d"):
        fill(lib, letter, quotes=["SYNTHETIC " + "x" * 16000])
    p = plan(lib)
    assert len(p["chunks"]) == 2 and all(c["message_chars"] <= 48000 for c in p["chunks"])
    assert p["not_sent_budget"] == []


def test_single_candidate_too_large_is_recorded_not_sent_budget(lib):
    fill(lib, quotes=["SYNTHETIC " + "x" * 48000])
    p = plan(lib)
    assert p["chunks"] == []
    assert p["not_sent_budget"] == [{"to": lib.ids["b"], "from": lib.ids["a"], "reason": "too_large_for_one_call",
                                      "pair_fingerprint": pairs(p)[lib.ids["b"], lib.ids["a"]]}]
    assert selected(p, lib.ids["b"])["outcome"] == "settled"


def test_beyond_three_calls_is_recorded(factory):
    lib = factory(n=28, mentions=(0, *range(2, 28)), only_target=True)
    p = plan(lib)
    assert len(p["chunks"]) == 3 and len(p["not_sent_budget"]) == 3
    assert {c["reason"] for c in p["not_sent_budget"]} == {"beyond_call_limit"}
    assert selected(p, lib.ids["b"])["outcome"] == "incomplete"


def test_pack_fits_uses_the_handle_message(lib, monkeypatch):
    seen = []
    original = contracts.with_citation_handles

    def handles(payload):
        result = original(payload)
        seen.append(result)
        return result

    monkeypatch.setattr(contracts, "with_citation_handles", handles)
    p = plan(lib)
    assert seen and all(s["sources"][0]["source_id"] == "srv_S0000001" for s in seen)
    assert p["chunks"][0]["message_chars"] == len(prompt.step_message(seen[-1]))


def test_measured_message_is_an_upper_bound_of_the_real_first_message(lib):
    p = plan(lib)
    _, _, payload = candidate(lib)
    run = lib.planner.request_run(lib.rid, lib.tid, p["preview_fingerprint"])
    scope = lib.store.scope(lib.rid)
    actual = lib.flow._step_input(run, scope, db.new_id("stp"), "lineage_links", [],
                                 [s["source_id"] for s in payload["sources"]],
                                 [lib.store.passage(q["passage_id"]) for q in payload["passages"]], [],
                                 step_model(scope, "lineage_links"), lineage_target=payload["lineage_target"])
    assert actual["budget"]["max_model_calls"] == 6
    assert lib.flow.lineage_message_chars(actual) <= p["chunks"][0]["message_chars"]
    assert payload["budget"]["max_model_calls"] == 450


def test_twenty_five_target_limit_and_classes_order(factory):
    lib = factory(n=30, all_pdf=True, mentions=())
    first = plan(lib)
    assert len(first["selected"]) == 25 and len(first["not_selected"]) == 5
    # Record one changed, one unchanged incomplete, and otherwise settled targets.
    first["selected"][1]["target_fp"] = "SYNTHETIC old target"
    first["selected"][2]["outcome"] = "incomplete"
    record_publication(lib, first)
    p = plan(lib)
    assert [s["class"] for s in p["selected"]] == ["new"] * 5 + ["changed", "retry"]
    assert [s["position"] for s in p["selected"]] == list(range(25, 30)) + [1, 2]


def test_second_plan_reaches_targets_beyond_the_first_25(factory):
    lib = factory(n=28, all_pdf=True, mentions=())
    p = plan(lib)
    record_publication(lib, p)
    second = plan(lib)
    assert [s["position"] for s in second["selected"]] == [25, 26, 27]
    assert all(s["reason"] == "settled" for s in second["not_selected"])


def test_unchanged_too_large_candidate_does_not_block_new_work(factory):
    lib = factory(n=28, all_pdf=True)
    fill(lib, quotes=["SYNTHETIC " + "x" * 50000])
    p = plan(lib)
    assert p["not_sent_budget"][0]["reason"] == "too_large_for_one_call"
    record_publication(lib, p)
    assert [s["position"] for s in plan(lib)["selected"]] == [25, 26, 27]


def test_settled_target_is_skipped_and_changed_target_is_reselected(lib):
    record_publication(lib)
    assert plan(lib)["selected"] == []
    lib.conn.execute("UPDATE source_versions SET version_label = 'SYNTHETIC changed' WHERE id = ?", (lib.ids["b"],))
    assert selected(plan(lib), lib.ids["b"])["class"] == "changed"


@pytest.mark.parametrize("edit", ["cell", "instruction"])
def test_a_cell_or_instruction_edit_anywhere_reopens_targets_but_asks_only_pending_pairs(factory, edit):
    lib = factory(mentions=(0, 6))
    p = plan(lib)
    for (to, frm), fp in pairs(p).items():
        letter = next(k for k, sid in lib.ids.items() if sid == frm)
        assess(lib, fp, a=letter)
    record_publication(lib, p)
    assert plan(lib)["selected"] == []
    if edit == "cell":
        fill(lib, "a")
    else:
        edit_instruction(lib)
    p = plan(lib)
    assert len(p["selected"]) == 5 and {s["class"] for s in p["selected"]} == {"changed"}
    assert set(pairs(p)) == ({(lib.ids["b"], lib.ids["a"])} if edit == "cell" else
                            {(lib.ids["b"], lib.ids["a"]), (lib.ids["b"], lib.ids["g"])})


def test_no_candidate_target_is_recorded_and_not_asked(lib):
    p = plan(lib)
    assert lib.ids["c"] in p["no_candidate"] and lib.ids["c"] in p["scanned_targets"]
    assert not any(c["to"] == lib.ids["c"] for c in p["chunks"])


def test_zero_call_plan_is_allowed_and_nothing_selected_is_refused(factory):
    lib = factory(mentions=())
    p = plan(lib)
    run = lib.planner.request_run(lib.rid, lib.tid, p["preview_fingerprint"])
    assert run["budget"] == {"max_model_calls": 0, "max_provider_requests": 0}
    lib.store.update_run(run["id"], status="completed")
    # Merely completing is not publication; record the synthetic terminal result.
    step = lib.store.step(run["id"], "lineage_publication", "lineage_publication")
    lib.store.finish_step(step["id"], "succeeded", {"targets": [{"to": s["to"], "outcome": "settled"}
                                                                for s in p["selected"]]})
    p = plan(lib)
    with pytest.raises(InvalidLineageInput, match="nothing to assess"):
        lib.planner.request_run(lib.rid, lib.tid, p["preview_fingerprint"])


@pytest.mark.parametrize("code,assessed", [(None, True), ("cycle", True), ("anchor_not_found", True), ("same_work", True),
                                          ("stale_input", False), ("endpoint_not_included", False), ("superseded_by_human", False)])
def test_assessed_pair_uses_the_latest_revision_only(lib, code, assessed):
    fp = pairs(plan(lib))[lib.ids["b"], lib.ids["a"]]
    p = proposal(lib, input_fingerprint=fp)
    pair = lib.lineage.ensure_link(lib.tid, lib.ids["a"], lib.ids["b"])

    def revision(value, rejection=None):
        return lib.lineage._insert_revision(pair, kind="model_propose", author="model", decision="no_relation",
            disposition="rejected" if rejection else "accepted", rejection_code=rejection, origin="mention",
            inputs_json={"fingerprint": value, "inputs": {}}, output_status="structurally_valid", step_input_id=p["step_input_id"])

    revision(fp)
    revision("SYNTHETIC B")
    assert (lib.ids["b"], lib.ids["a"]) in pairs(plan(lib))
    revision(fp, code)
    assert ((lib.ids["b"], lib.ids["a"]) not in pairs(plan(lib))) == assessed


def test_known_failed_pairs_are_left_out_until_the_fingerprint_changes_or_retry_failed(factory):
    lib = factory(n=28, mentions=(0, *range(2, 28)), only_target=True)
    p = plan(lib)
    first_froms = {frm for chunk in p["chunks"] for frm in chunk["from"]}
    failed = [{"to": to, "from": frm, "pair_fp": fp, "reason": "invalid_model_output"}
              for (to, frm), fp in pairs(p).items() if frm in first_froms]
    record_publication(lib, p, failed=failed)
    p2 = plan(lib)
    assert len(p2["failed_unchanged"]) == 24 and len(p2["chunks"]) == 1
    assert len(p2["chunks"][0]["from"]) == 3  # earlier failures cannot starve the remainder
    record_publication(lib, p2, outcomes={lib.ids["b"]: "settled"})
    assert plan(lib)["selected"] == []
    # The latest plan confirmed these older failures at the same pair inputs.
    assert selected(plan(lib, True), lib.ids["b"])["class"] == "retry"
    record_publication(lib, p2, outcomes={lib.ids["b"]: "settled"}, failed=failed)
    retried = plan(lib, True)
    assert selected(retried, lib.ids["b"])["class"] == "retry" and retried["chunks"]
    assert retried["failed_unchanged"] == []
    edit_instruction(lib)
    assert len(plan(lib)["failed_unchanged"]) == 0


def test_carried_failure_is_cleared_by_a_model_revision_after_the_original_failure(lib):
    first = plan(lib)
    fp = pairs(first)[lib.ids["b"], lib.ids["a"]]
    _, failure_step = record_publication(lib, first, outcomes={lib.ids["b"]: "incomplete"}, failed=[
        {"to": lib.ids["b"], "from": lib.ids["a"], "pair_fp": fp, "reason": "invalid_model_output"}])
    carried = plan(lib)
    assert carried["failed_unchanged"] == [{"to": lib.ids["b"], "from": lib.ids["a"], "pair_fp": fp}]
    assert assess(lib, fp)["disposition"] == "accepted"
    _, carrier_step = record_publication(lib, carried)
    # The model revision follows the failure but precedes the carrier's publication.
    lib.conn.execute("UPDATE run_steps SET finished_at = '2000-01-01T00:00:00Z' WHERE id = ?", (failure_step["id"],))
    lib.conn.execute("UPDATE run_steps SET finished_at = '2100-01-01T00:00:00Z' WHERE id = ?", (carrier_step["id"],))
    assert plan(lib, True)["selected"] == []


def test_retry_failed_does_not_reopen_a_target_settled_at_a_new_fingerprint_with_an_oversized_pair(lib):
    a = plan(lib)
    failed = [{"to": lib.ids["b"], "from": lib.ids["a"],
               "pair_fp": pairs(a)[lib.ids["b"], lib.ids["a"]], "reason": "invalid_model_output"}]
    record_publication(lib, a, failed=failed)
    assert selected(plan(lib, True), lib.ids["b"])["class"] == "retry"
    fill(lib, quotes=["SYNTHETIC " + "x" * 50000])
    b = plan(lib)
    assert selected(b, lib.ids["b"])["class"] == "changed"
    assert b["chunks"] == [] and b["not_sent_budget"][0]["reason"] == "too_large_for_one_call"
    record_publication(lib, b)
    for _ in range(2):
        preview = plan(lib, True)
        assert preview["selected"] == [] and preview["chunks"] == []
        assert preview["failed_unchanged"] == []
        assert next(s for s in preview["not_selected"] if s["to"] == lib.ids["b"])["reason"] == "settled"


def test_successful_retry_ends_an_old_failure_even_after_input_returns_to_a(lib):
    p = plan(lib)
    fp = pairs(p)[lib.ids["b"], lib.ids["a"]]
    _, step = record_publication(lib, p, failed=[{"to": lib.ids["b"], "from": lib.ids["a"], "pair_fp": fp, "reason": "invalid_model_output"}])
    assert plan(lib, True)["chunks"]
    result = assess(lib, fp)
    # Synthetic chronology is explicit, avoiding a wall-clock sleep or millisecond tie.
    lib.conn.execute("UPDATE run_steps SET finished_at = '2000-01-01T00:00:00Z' WHERE id = ?", (step["id"],))
    assert result["disposition"] == "accepted"
    original_title = lib.store.source(lib.ids["a"])["title"]
    lib.conn.execute("UPDATE source_versions SET title = 'SYNTHETIC input B' WHERE id = ?", (lib.ids["a"],))
    b = plan(lib)
    assess(lib, pairs(b)[lib.ids["b"], lib.ids["a"]])
    record_publication(lib, b)
    lib.conn.execute("UPDATE source_versions SET title = ? WHERE id = ?", (original_title, lib.ids["a"]))
    returned = plan(lib)
    assert returned["failed_unchanged"] == [] and returned["chunks"]


def test_first_pdf_attached_to_a_from_work_reopens_targets_without_any_revision_counter_moving(lib):
    p = plan(lib)
    assess(lib, pairs(p)[lib.ids["b"], lib.ids["a"]])
    record_publication(lib, p)
    before = lib.store.research(lib.rid)
    cell_ids = [tuple(r) for r in lib.conn.execute("SELECT current_revision_id, version FROM evidence_cells")]
    attach(lib, lib.ids["a"], "SYNTHETIC first attached PDF without mentions")
    after = lib.store.research(lib.rid)
    assert after["current_scope_revision"] == before["current_scope_revision"]
    assert after["selection_revision"] == before["selection_revision"]
    assert [tuple(r) for r in lib.conn.execute("SELECT current_revision_id, version FROM evidence_cells")] == cell_ids
    updated = plan(lib)
    assert selected(updated, lib.ids["b"])["class"] == "changed"
    assert pairs(updated)[lib.ids["b"], lib.ids["a"]] != pairs(p)[lib.ids["b"], lib.ids["a"]]


def fp(lib, payload, selection=None, effort=None):
    return planning.pair_fp(payload, lib.store.selection_revision(lib.rid) if selection is None else selection,
                            lib.ids["a"], effort)


def test_pair_fp_changes_with_instruction_text_when_cell_id_is_unchanged(lib):
    fill(lib)
    _, _, before = candidate(lib)
    edit_instruction(lib)
    _, _, after = candidate(lib)
    assert before["lineage_target"]["candidates"][0]["from"]["cells"][0]["cell_id"] == after["lineage_target"]["candidates"][0]["from"]["cells"][0]["cell_id"]
    assert fp(lib, before) != fp(lib, after)


def test_pair_fp_changes_with_pdf_extraction(lib):
    _, _, before = candidate(lib)
    text = "SYNTHETIC Author000 (2000) after extraction"
    extraction = SimpleNamespace(status="succeeded", error=None, page_count=1,
                                 pages=[SimpleNamespace(physical_page=1, printed_label="1", text=text)])
    lib.store.reextract_asset(lib.assets[lib.ids["b"]], extraction, "SYNTHETIC-v2", lambda t: [(0, len(t), t)], None)
    _, _, after = candidate(lib)
    assert fp(lib, before) != fp(lib, after)


def test_pair_fp_changes_with_scope_revision(lib):
    _, _, payload = candidate(lib)
    changed = copy.deepcopy(payload)
    changed["scope_revision"] += 1
    assert fp(lib, payload) != fp(lib, changed)


def test_pair_fp_changes_with_selection_revision(lib):
    _, _, payload = candidate(lib)
    assert fp(lib, payload, 1) != fp(lib, payload, 2)


def test_pair_fp_changes_with_cell_revision(lib):
    _, _, before = candidate(lib)
    fill(lib)
    _, _, after = candidate(lib)
    assert fp(lib, before) != fp(lib, after)


def test_pair_fp_changes_with_edge_state(lib):
    _, _, payload = candidate(lib)
    changed = copy.deepcopy(payload)
    changed["lineage_target"]["candidates"][0]["edge_state"] = "present"
    assert fp(lib, payload) != fp(lib, changed)


@pytest.mark.parametrize("field", ["title", "version_label"])
def test_pair_fp_changes_with_source_title_or_version_label(lib, field):
    _, _, payload = candidate(lib)
    changed = copy.deepcopy(payload)
    changed["sources"][1][field] = "SYNTHETIC changed metadata"
    assert fp(lib, payload) != fp(lib, changed)


def test_pair_fp_ignores_timestamps_and_new_ids(lib):
    _, _, a = candidate(lib)
    _, _, b = candidate(lib)
    assert a["step_input_id"] != b["step_input_id"] and a["run_id"] != b["run_id"]
    b["created_at"] = "SYNTHETIC another time"
    b["research_id"] = db.new_id("res")
    assert fp(lib, a) == fp(lib, b)


def test_pair_fp_ignores_the_other_candidates_in_the_call(factory):
    lib = factory(mentions=(0, 2))
    _, _, payload = candidate(lib)
    other = copy.deepcopy(payload)
    snap = planning.build_snapshot(lib.store, lib.tid)
    extra = copy.deepcopy(other["lineage_target"]["candidates"][0])
    extra["from"] = json.loads(next(r.node_json for r in snap.rows if r.work.source_version_id == lib.ids["c"]))
    other["lineage_target"]["candidates"].append(extra)
    other["sources"].append(json.loads(next(r.source_json for r in snap.rows if r.work.source_version_id == lib.ids["c"])))
    other["passages"].append({"passage_id": "psg_SYNTHETICOTHER01", "text": "SYNTHETIC other passage"})
    assert fp(lib, payload) == fp(lib, other)
    assert fp(lib, payload, effort="low") != fp(lib, payload, effort="high")


def test_target_fp_changes_with_any_node_snapshot_and_with_model_or_skill(lib):
    snap = planning.build_snapshot(lib.store, lib.tid)
    row = snap.rows[1]
    m = step_model(lib.store.scope(lib.rid), "lineage_links")
    a = planning.target_fp(snap, row, "sha256:SYNTHETIC", m)
    assert a != planning.target_fp(snap, row, "sha256:other", m)
    assert a != planning.target_fp(snap, row, "sha256:SYNTHETIC", (m[0], "other", m[2]))
    for r in snap.rows:
        node = json.loads(r.node_json)
        node["cells"][0]["instruction"] = "SYNTHETIC changed node"
        replacement = replace(r, node_json=json.dumps(node))
        changed = replace(snap, rows=tuple(replacement if v is r else v for v in snap.rows))
        target = next(v for v in changed.rows if v.work.source_version_id == row.work.source_version_id)
        assert a != planning.target_fp(changed, target, "sha256:SYNTHETIC", m)


def test_preview_fingerprint_is_stable_across_two_builds(lib):
    assert plan(lib) == plan(lib)


def test_stored_plan_content(lib):
    p = plan(lib)
    assert p["plan_version"] == 1 and p["table_id"] == lib.tid
    assert {k: p["rules"][k] for k in mention_rules()} == mention_rules()
    assert p["rules"]["max_schema_repairs"] == schema_repairs("lineage_links")
    assert p["rules"]["max_rate_limit_model_retries"] == MAX_RATE_LIMIT_MODEL_RETRIES
    assert p["rules"]["max_lineage_targets"] == 25 and p["rules"]["max_message_chars"] == 48000
    assert {"not_sent_budget", "failed_unchanged", "retry_failed", "unassessed_edges", "scanned_targets"} <= p.keys()
    assert p["counts"]["development_columns"] == 3 and p["counts"]["missing_cells"] == 24
    for c in p["chunks"]:
        assert c["key"] == f"lineage_links:{c['to']}:{c['index']}:{c['chunk_fp'][:16]}"
        assert c["message_chars"] <= 48000 and c["shown_passage_ids"]
    assert all(c["link_version"] is None and c["current_revision_id"] is None for s in p["selected"] for c in s["candidates"])
    assess(lib, "SYNTHETIC previous fingerprint")
    updated = plan(lib)
    pair = selected(updated, lib.ids["b"])["candidates"][0]
    link = lib.lineage.link(lib.tid, lib.ids["a"], lib.ids["b"])
    assert pair["link_version"] == link["version"] and pair["current_revision_id"] == link["current_revision_id"]


def test_max_model_calls_formula_and_zero_provider_requests(lib):
    p = plan(lib)
    assert p["max_model_calls"] == len(p["chunks"]) * (1 + schema_repairs("lineage_links")) * (1 + MAX_RATE_LIMIT_MODEL_RETRIES)
    assert p["max_provider_requests"] == 0


def test_preview_equals_stored_plan_fingerprint(lib):
    preview = lib.planner.preview(lib.rid, lib.tid)
    queued = lib.planner.request_run(lib.rid, lib.tid, preview["preview_fingerprint"])
    assert queued["target"] == plan_before_queue(lib, queued)
    assert preview["preview_fingerprint"] == queued["target"]["preview_fingerprint"]
    assert preview["calls"] == len(queued["target"]["chunks"])


def plan_before_queue(lib, queued):
    return json.loads(lib.conn.execute("SELECT target_json FROM runs WHERE id = ?", (queued["id"],)).fetchone()[0])


def test_request_run_409_when_the_plan_changed(lib):
    preview = lib.planner.preview(lib.rid, lib.tid)
    edit_instruction(lib)
    with pytest.raises(RevisionConflict, match="plan changed"):
        lib.planner.request_run(lib.rid, lib.tid, preview["preview_fingerprint"])
    assert lib.conn.execute("SELECT COUNT(*) FROM runs WHERE kind = 'lineage_links'").fetchone()[0] == 0


def test_request_run_replays_an_idempotency_key_first(lib):
    p = plan(lib)
    run = lib.planner.request_run(lib.rid, lib.tid, p["preview_fingerprint"], idempotency_key="SYNTHETIC-key")
    lib.store.update_run(run["id"], status="paused")
    edit_instruction(lib)
    replay = lib.planner.request_run(lib.rid, lib.tid, "stale", True, "SYNTHETIC-key")
    assert replay["id"] == run["id"] and replay["target"] == p


def test_idempotency_key_of_another_table_of_the_same_research_is_refused(factory):
    lib = factory()
    p = plan(lib)
    run = lib.planner.request_run(lib.rid, lib.tid, p["preview_fingerprint"], idempotency_key="SYNTHETIC-key")
    tid2 = lib.tables.create_table(lib.rid, "SYNTHETIC second table", None, None, None)
    with pytest.raises(RevisionConflict, match="another lineage request"):
        lib.planner.request_run(lib.rid, tid2, "ignored", idempotency_key="SYNTHETIC-key")
    rid2 = lib.store.create_research("SYNTHETIC other question?", "attached", "quick", [], "fake", "fake-model", "en")
    for sid in lib.order:
        lib.store.add_to_corpus(rid2, sid, "user_upload", selection_state="included", selection_origin="user")
    tid3 = lib.tables.create_table(rid2, "SYNTHETIC other research table", None, None, None)
    p3 = lib.planner.build_plan(rid2, tid3)
    independent = lib.planner.request_run(rid2, tid3, p3["preview_fingerprint"], idempotency_key="SYNTHETIC-key")
    assert independent["id"] != run["id"]
    assert independent["idempotency_key"] == f"lineage:{rid2}:SYNTHETIC-key"


def test_paused_lineage_run_blocks_a_new_one(lib):
    p = plan(lib)
    run = lib.planner.request_run(lib.rid, lib.tid, p["preview_fingerprint"])
    lib.store.update_run(run["id"], status="paused")
    with pytest.raises(RevisionConflict, match="Resume or cancel"):
        lib.planner.request_run(lib.rid, lib.tid, plan(lib)["preview_fingerprint"])


def test_active_run_of_another_kind_blocks(lib):
    p = plan(lib)
    lib.store.create_run(lib.rid, "table_fill", {}, None)
    with pytest.raises(RevisionConflict, match="still active"):
        lib.planner.request_run(lib.rid, lib.tid, p["preview_fingerprint"])


@pytest.fixture
def api(tmp_path):
    seen = []

    def reject(request):
        seen.append(str(request.url))
        raise AssertionError("No provider call permitted")

    adapter = NeverAdapter()
    http = httpx.AsyncClient(transport=httpx.MockTransport(reject))
    app = create_app(Settings(data_dir=tmp_path / "api-data", port=8873), adapters={"fake": adapter},
                     http_client=http, start_worker=False, trusted_clients=("testclient",))
    with TestClient(app, base_url="http://127.0.0.1:8873") as client:
        session(client)
        store = app.state.store
        rid = store.create_research("SYNTHETIC API question?", "attached", "quick", [], "fake", "fake-model", "en")
        sid = store.create_upload_source("SYNTHETIC API source")
        store.add_to_corpus(rid, sid, "user_upload", selection_state="included", selection_origin="user")
        lib = SimpleNamespace(store=store)
        attach(lib, sid, "SYNTHETIC API PDF without mention")
        tables = TableStore(store)
        tid = tables.create_table(rid, "SYNTHETIC API table", None, None, None)
        tables.add_development_columns(rid, tid, 1, None)
        yield SimpleNamespace(client=client, app=app, store=store, tables=tables, rid=rid, tid=tid, sid=sid,
                              url=f"/api/researches/{rid}/tables/{tid}/lineage", adapter=adapter)
    assert seen == [] and adapter.messages == []


def test_routes_get_plan_and_post_run_202_and_error_codes(api):
    preview = api.client.get(api.url + "/plan?retry_failed=true")
    assert preview.status_code == 200 and preview.json()["retry_failed"] is True
    body = {"preview_fingerprint": preview.json()["preview_fingerprint"], "retry_failed": True}
    api.client.headers.pop("x-deixis-csrf")
    assert api.client.post(api.url + "/runs", json=body).status_code == 403
    session(api.client)
    assert api.client.post(api.url + "/runs", json={"preview_fingerprint": "0" * 64}).status_code == 409
    assert api.client.post(api.url + "/runs", json={"preview_fingerprint": "invalid"}).status_code == 422
    run = api.client.post(api.url + "/runs", json=body, headers={"Idempotency-Key": "SYNTHETIC"})
    assert run.status_code == 202 and run.json()["kind"] == "lineage_links"
    assert api.client.post(api.url + "/runs", json=body, headers={"Idempotency-Key": "SYNTHETIC"}).json()["id"] == run.json()["id"]
    assert api.client.get(api.url.replace(api.tid, "tbl_missing") + "/plan").status_code == 404
    api.store.update_run(run.json()["id"], status="completed")
    step = api.store.step(run.json()["id"], "lineage_publication", "lineage_publication")
    api.store.finish_step(step["id"], "succeeded", {"targets": [{"to": api.sid, "outcome": "settled"}]})
    empty = api.client.get(api.url + "/plan").json()
    refusal = api.client.post(api.url + "/runs", json={"preview_fingerprint": empty["preview_fingerprint"]})
    assert refusal.status_code == 422 and refusal.json()["detail"] == "nothing to assess"


@pytest.mark.parametrize("status", ["queued", "running", "pause_requested", "paused", "completed", "failed", "cancelled"])
def test_stage_is_synthesis_and_research_view_still_loads(api, status):
    preview = api.client.get(api.url + "/plan").json()
    run = api.client.post(api.url + "/runs", json={"preview_fingerprint": preview["preview_fingerprint"]}).json()
    assert run["stage"] == "synthesis"
    api.store.update_run(run["id"], status=status)
    response = api.client.get(f"/api/researches/{api.rid}")
    assert response.status_code == 200
    assert next(r for r in response.json()["runs"] if r["id"] == run["id"])["status"] == status


def test_cancel_route_does_not_cancel_the_adapter_for_lineage(api):
    preview = api.client.get(api.url + "/plan").json()
    run = api.client.post(api.url + "/runs", json={"preview_fingerprint": preview["preview_fingerprint"]}).json()
    api.store.update_run(run["id"], status="running")
    api.app.state.worker.current_run_id = run["id"]
    calls = []

    async def cancel():
        calls.append(True)

    api.adapter.cancel = cancel
    response = api.client.post(f"/api/runs/{run['id']}/cancel")
    assert response.status_code == 200 and response.json()["status"] == "cancelled"
    assert calls == []


def test_plan_building_calls_no_model_and_no_provider(lib):
    preview = lib.planner.preview(lib.rid, lib.tid)
    lib.planner.request_run(lib.rid, lib.tid, preview["preview_fingerprint"])
    assert lib.adapter.messages == [] and lib.seen == []
    assert lib.conn.execute("SELECT COUNT(*) FROM model_sessions").fetchone()[0] == 0


def test_flow_dispatch_keeps_a_queued_lineage_run_unsent(lib):
    run = lib.planner.request_run(lib.rid, lib.tid, plan(lib)["preview_fingerprint"])
    asyncio.run(lib.flow.execute(run["id"]))
    assert lib.store.run(run["id"])["status"] == "queued"


def test_snapshot_is_frozen_and_loads_no_passage_texts_before_selection(lib, monkeypatch):
    def forbid(*args):
        raise AssertionError("Classification must not load texts")

    monkeypatch.setattr(lib.store, "passages_for", forbid)
    snap = planning.build_snapshot(lib.store, lib.tid)
    assert all(r.work.passages == () for r in snap.rows)
    assert len(snap.rows) == 8 and snap.rows[1].eligible


def test_stale_link_revisions_uses_current_evidence_and_node_snapshots(lib):
    snap, c, payload = candidate(lib)
    inputs = {"to": planning.node_snapshot(payload["lineage_target"]["to"]),
              "from": planning.node_snapshot(payload["lineage_target"]["candidates"][0]["from"]),
              "mention_passage_ids": list(c.mention_passage_ids), "edge_state": c.edge_state, "year_order_warning": False}
    result = model(lib, input_fingerprint=fp(lib, payload), inputs=inputs,
                   decision=decision(lib, evidence=[{"passage_id": lib.passages["b"], "quote": "Author000 (2000)"}]))
    assert lib.planner.stale_link_revisions(lib.tid) == {}
    lib.conn.execute("UPDATE researches SET selection_revision = selection_revision + 1 WHERE id = ?", (lib.rid,))
    assert lib.planner.stale_link_revisions(lib.tid) == {}
    fill(lib)
    assert lib.planner.stale_link_revisions(lib.tid) == {result["link_id"]: result["revision_id"]}


def test_human_stale_evidence_leaves_the_cycle_graph_without_rewriting_it(lib):
    revision = human(lib, evidence=[{"passage_id": lib.passages["b"], "quote": "Author000 (2000)"}])
    link = lib.lineage.link(lib.tid, lib.ids["a"], lib.ids["b"])
    edit_instruction(lib)
    assert lib.planner.stale_link_revisions(lib.tid) == {}
    lib.conn.execute("UPDATE source_assets SET extraction_version = 'SYNTHETIC-v2' WHERE id = ?", (lib.assets[lib.ids["b"]],))
    assert lib.planner.stale_link_revisions(lib.tid) == {link["id"]: revision}
    assert lib.lineage.link(lib.tid, lib.ids["a"], lib.ids["b"])["current_revision_id"] == revision
