"""L5a synthetic planning and API checks: no model or provider calls."""

import asyncio
import json
from dataclasses import replace
from types import SimpleNamespace

import httpx
import pytest
from fastapi.testclient import TestClient

from deixis.api.app import create_app
from deixis.config import Settings
from deixis.domain import skill
from deixis.domain.rules import MAX_RATE_LIMIT_MODEL_RETRIES, RevisionConflict, schema_repairs
from deixis.storage import db
from deixis.workflow.run.flow import FlowDeps, ResearchFlow
from deixis.workflow.features.lineage import lineage_run as planning
from deixis.workflow.features.lineage.lineage_candidates import find_candidates
from deixis.workflow.features.lineage.lineage_mentions import PassageText, mention_rules
from deixis.workflow.features.lineage.lineage_store import LineageStore
from deixis.workflow.run.store import Store
from deixis.workflow.features.tables.tables import TableStore
from fakes import FakeAdapter
from test_api_flow import session
from test_lineage_store import decision, human, model


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


def test_excluded_pairs_are_the_human_decided_ones(lib):
    human(lib, evidence=[{"passage_id": lib.passages["b"], "quote": "Author000 (2000)"}])
    snap = planning.build_snapshot(lib.store, lib.tid)
    assert snap.human_pairs == frozenset(lib.lineage.human_decided_pairs(lib.tid))
    assert (lib.ids["b"], lib.ids["a"]) not in pairs(plan(lib))


def test_settled_target_is_skipped_and_changed_target_is_reselected(lib):
    record_publication(lib)
    assert plan(lib)["selected"] == []
    lib.conn.execute("UPDATE source_versions SET version_label = 'SYNTHETIC changed' WHERE id = ?", (lib.ids["b"],))
    assert selected(plan(lib), lib.ids["b"])["class"] == "changed"


def fp(lib, payload, selection=None, effort=None):
    return planning.pair_fp(payload, lib.store.selection_revision(lib.rid) if selection is None else selection,
                            lib.ids["a"], effort)


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


def test_preview_equals_stored_plan_fingerprint(lib):
    preview = lib.planner.preview(lib.rid, lib.tid)
    queued = lib.planner.request_run(lib.rid, lib.tid, preview["preview_fingerprint"])
    assert queued["target"] == plan_before_queue(lib, queued)
    assert preview["preview_fingerprint"] == queued["target"]["preview_fingerprint"]
    assert preview["calls"] == len(queued["target"]["chunks"])


def plan_before_queue(lib, queued):
    return json.loads(lib.conn.execute("SELECT target_json FROM runs WHERE id = ?", (queued["id"],)).fetchone()[0])


def test_request_run_replays_an_idempotency_key_first(lib):
    p = plan(lib)
    run = lib.planner.request_run(lib.rid, lib.tid, p["preview_fingerprint"], idempotency_key="SYNTHETIC-key")
    lib.store.update_run(run["id"], status="paused")
    edit_instruction(lib)
    replay = lib.planner.request_run(lib.rid, lib.tid, "stale", True, "SYNTHETIC-key")
    assert replay["id"] == run["id"] and replay["target"] == p


def test_paused_lineage_run_blocks_a_new_one(lib):
    p = plan(lib)
    run = lib.planner.request_run(lib.rid, lib.tid, p["preview_fingerprint"])
    lib.store.update_run(run["id"], status="paused")
    with pytest.raises(RevisionConflict, match="Resume or cancel"):
        lib.planner.request_run(lib.rid, lib.tid, plan(lib)["preview_fingerprint"])


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
                              url=f"/api/researches/{rid}/tables/{tid}/lineage", adapter=adapter, seen=seen)
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


def test_flow_dispatch_keeps_a_queued_lineage_run_unsent(lib):
    run = lib.planner.request_run(lib.rid, lib.tid, plan(lib)["preview_fingerprint"])
    asyncio.run(lib.flow.execute(run["id"]))
    assert lib.store.run(run["id"])["status"] == "queued"
