"""Human API checks with CSRF, real persistence and synthetic evidence only."""

import json

import pytest

from deixis.workflow.lineage.run import LineagePlanner
from deixis.workflow.lineage.store import LineageStore
from fakes import FakeAdapter
from fakes import valid_response
from helpers import make_pdf
from test_api_flow import session
from test_lineage_plan import api as plan_api, fill
from test_lineage_flow import all_links, queue, execute, reextract, selection_edit
from test_lineage_view import model_decision, read, links, row


@pytest.fixture
def api(plan_api):
    api = plan_api
    api.conn = api.store.conn
    api.ids = {"b": api.sid}
    for i, key in enumerate(("a", "c", "d")):
        sid = api.store.create_upload_source(f"SYNTHETIC source {key}")
        api.conn.execute("UPDATE source_versions SET authors_json = ?, year = ? WHERE id = ?",
                         (json.dumps([f"SYNTHETIC Author{i:03d}"]), 2000 + i, sid))
        api.store.add_to_corpus(api.rid, sid, "user_upload", selection_state="included", selection_origin="user")
        api.tables.add_rows(api.rid, api.tid, [sid], api.tables._table(api.rid, api.tid)["version"])
        api.ids[key] = sid
    api.conn.execute("UPDATE source_versions SET year = 2005 WHERE id = ?", (api.sid,))
    asset = api.conn.execute("SELECT id FROM source_assets WHERE source_version_id = ? AND removed_at IS NULL", (api.sid,)).fetchone()[0]
    api.assets = {api.sid: asset}
    reextract(api, text="SYNTHETIC: Author000 (2000), Author001 (2001), Author002 (2002).")
    api.passages = {key: api.store._insert_passage(sid, None, "abstract", None, None, "synthetic_fixture", None, None, "SYNTHETIC")
                    for key, sid in api.ids.items()}
    api.passages["b"] = next(p["id"] for p in api.store.passages_for(api.sid) if p["asset_id"] == asset)
    api.lineage = LineageStore(api.store)
    generic = api.store.create_run(api.rid, "answer", {}, None)
    api.store.update_run(generic["id"], status="completed")
    api.run = generic["id"]
    api.flow = api.app.state.worker.flow
    api.fake = FakeAdapter()
    api.flow.deps.adapters["fake"] = api.fake
    api.planner = LineagePlanner(api.store, api.flow.lineage_step_input, api.flow.lineage_message_chars, api.flow.deps.package.package_hash)
    yield api


def body(api, a="a", b="b", **kw):
    pair = api.lineage.link(api.tid, api.ids[a], api.ids[b])
    return {"from_source_version_id": api.ids[a], "to_source_version_id": api.ids[b], "relation": "extends",
            "what_changed": "SYNTHETIC human change", "support_type": "source_stated",
            "evidence": [{"passage_id": api.passages[b], "quote": "SYNTHETIC"}], "note": None,
            "expected_version": pair["version"] if pair else 0} | kw


def add(api, a="a", b="b", **kw):
    response = api.client.post(api.url + "/links", json=body(api, a, b, **kw))
    assert response.status_code == 201, response.text
    return api.lineage.link(api.tid, api.ids[a], api.ids[b])


def edit_body(api, pair, **kw):
    value = body(api)
    value.pop("from_source_version_id")
    value.pop("to_source_version_id")
    return value | {"expected_version": pair["version"], "based_on_revision_id": pair["current_revision_id"]} | kw


def remove(api, pair, **kw):
    return api.client.delete(api.url + "/links/" + pair["id"], params={"expected_version": pair["version"],
                             "based_on_revision_id": pair["current_revision_id"]} | kw)


def test_get_lineage_and_baseline_404_for_missing_table_and_foreign_research(api):
    other = api.store.create_research("SYNTHETIC foreign research?", "attached", "quick", [], "fake", "fake-model", "en")
    for suffix in ("", "/baseline"):
        assert api.client.get(api.url + suffix).status_code == 200
        assert api.client.get(api.url.replace(api.tid, "tbl_missing") + suffix).status_code == 404
        assert api.client.get(api.url.replace(api.rid, other) + suffix).status_code == 404
    pair = add(api)
    for method, suffix, kwargs in (("put", "/links/" + pair["id"], {"json": edit_body(api, pair)}),
                                    ("delete", "/links/" + pair["id"], {"params": {"expected_version": pair["version"], "based_on_revision_id": pair["current_revision_id"]}})):
        assert getattr(api.client, method)(api.url.replace(api.rid, other) + suffix, **kwargs).status_code == 404


def test_human_add_needs_a_placed_quote_in_a_passage_of_the_later_work(api):
    for evidence in ([{"passage_id": api.passages["a"], "quote": "SYNTHETIC"}],
                     [{"passage_id": api.passages["b"], "quote": "This text is absent"}],
                     [{"passage_id": "psg_unknown", "quote": "SYNTHETIC"}]):
        response = api.client.post(api.url + "/links", json=body(api, evidence=evidence))
        assert response.status_code == 422, response.text
    response = api.client.post(api.url + "/links", json=body(api))
    assert response.status_code == 201 and len(response.json()["components"]) == 1


def test_human_add_expected_version_zero_for_a_new_pair_and_409_for_a_wrong_one(api):
    assert api.client.post(api.url + "/links", json=body(api, expected_version=1)).status_code == 409
    add(api, expected_version=0)
    assert api.client.post(api.url + "/links", json=body(api, expected_version=0)).status_code == 409


@pytest.mark.parametrize("decision", ["no_relation", "insufficient_evidence", "removed", "new"])
def test_get_then_post_adds_a_human_link_with_the_read_version(api, decision):
    if decision in ("no_relation", "insufficient_evidence"):
        model_decision(api, decision=decision)
    elif decision == "removed":
        pair = add(api)
        assert remove(api, pair).status_code == 200
    value = api.client.get(api.url).json()
    pairs = [p for p in value["pair_decisions"] if p["from"] == api.ids["a"] and p["to"] == api.ids["b"]]
    expected = pairs[0]["version"] if pairs else 0
    response = api.client.post(api.url + "/links", json=body(api, expected_version=expected))
    assert response.status_code == 201 and links(response.json())[0]["author"] == "human"


def test_stale_version_read_from_an_earlier_get_returns_409(api):
    model_decision(api, decision="no_relation")
    old = api.client.get(api.url).json()["pair_decisions"][0]
    model_decision(api, decision="insufficient_evidence")
    assert api.client.post(api.url + "/links", json=body(api, expected_version=old["version"])).status_code == 409


def test_human_edit_and_remove_use_expected_version_and_based_on_revision(api):
    pair = add(api)
    url = api.url + "/links/" + pair["id"]
    for kw in ({"expected_version": 0}, {"based_on_revision_id": "llr_not_current"}):
        assert api.client.put(url, json=edit_body(api, pair, **kw)).status_code == 409
        assert remove(api, pair, **kw).status_code == 409
    response = api.client.put(url, json=edit_body(api, pair, relation="changes_method"))
    assert response.status_code == 200 and links(response.json())[0]["relation"] == "changes_method"
    assert remove(api, pair).status_code == 409
    pair = api.lineage.link_by_id(pair["id"])
    response = remove(api, pair)
    assert response.status_code == 200 and "human_removed" in row(api, value=response.json())["reasons"]


def test_human_remove_is_listed_as_human_removed_and_never_reactivated_by_a_run(api):
    pair = add(api)
    assert remove(api, pair).status_code == 200
    api.fake.responder = all_links
    execute(api, queue(api))
    current = api.lineage._current(api.lineage.link_by_id(pair["id"]))
    assert current["kind"] == "human_remove" and "human_removed" in row(api, "a")["reasons"]
    assert all(api.ids["a"] not in [c["from"]["source_id"] for c in api.store.step_input_payload(si["step_input_id"])["lineage_target"]["candidates"]] for si in api.fake.calls)


def test_remove_has_no_live_end_or_cycle_condition_and_re_adding_over_an_active_link_is_409(api, monkeypatch):
    pair = add(api)
    assert api.client.post(api.url + "/links", json=body(api)).status_code == 409
    selection_edit(api)
    monkeypatch.setattr(LineageStore, "_cycle", lambda *args: pytest.fail("remove must not check cycles"))
    assert remove(api, pair).status_code == 200
    pair = api.lineage.link_by_id(pair["id"])
    assert remove(api, pair).status_code == 409
    assert api.client.put(api.url + "/links/" + pair["id"], json=edit_body(api, pair)).status_code == 409


def test_human_routes_require_csrf(api):
    pair = add(api)
    api.client.headers.pop("x-deixis-csrf")
    assert api.client.post(api.url + "/links", json=body(api, "c")).status_code == 403
    assert api.client.put(api.url + "/links/" + pair["id"], json=edit_body(api, pair)).status_code == 403
    assert remove(api, pair).status_code == 403
    assert api.client.get(api.url).status_code == 200


@pytest.mark.parametrize("kind", ["add", "edit", "remove"])
def test_idempotency_key_replays_the_same_write(api, kind):
    key = {"Idempotency-Key": "SYNTHETIC-" + kind}
    if kind == "add":
        call = lambda: api.client.post(api.url + "/links", json=body(api, expected_version=0), headers=key)
    else:
        pair = add(api)
        url = api.url + "/links/" + pair["id"]
        payload = edit_body(api, pair)
        call = (lambda: api.client.put(url, json=payload, headers=key)) if kind == "edit" else (
            lambda: api.client.delete(url, params={"expected_version": pair["version"], "based_on_revision_id": pair["current_revision_id"]}, headers=key))
    first = call()
    count = api.conn.execute("SELECT COUNT(*) FROM lineage_link_revisions").fetchone()[0]
    second = call()
    assert first.status_code == second.status_code == (201 if kind == "add" else 200)
    assert first.json() == second.json()
    assert api.conn.execute("SELECT COUNT(*) FROM lineage_link_revisions").fetchone()[0] == count


def test_cycle_is_422_and_a_stale_edge_does_not_block_a_closing_human_link(api):
    model_decision(api)
    response = api.client.post(api.url + "/links", json=body(api, "b", "a"))
    assert response.status_code == 422
    fill(api)
    pair = add(api, "b", "a")
    value = api.client.get(api.url).json()
    assert value["history"]["stale"] and any(l["link_id"] == pair["id"] for l in links(value))


def test_edit_of_a_stale_link_is_allowed_and_makes_it_current_again_when_the_evidence_is_current(api):
    model_decision(api)
    fill(api)
    pair = api.lineage.link(api.tid, api.ids["a"], api.ids["b"])
    assert api.client.get(api.url).json()["history"]["stale"]
    response = api.client.put(api.url + "/links/" + pair["id"], json=edit_body(api, pair))
    assert response.status_code == 200 and links(response.json())[0]["author"] == "human" and not response.json()["history"]["stale"]


@pytest.mark.parametrize("kw", [{"relation": "unknown"}, {"what_changed": ""}, {"what_changed": "x" * 501},
    {"evidence": []}, {"evidence": [{"passage_id": "p", "quote": "q"}] * 6}, {"note": "x" * 2001},
    {"expected_version": True}, {"support_type": "unknown"}, {"relation": "independent_parallel", "support_type": "analyst_inference"}])
def test_human_request_validation_errors_are_422(api, kw):
    assert api.client.post(api.url + "/links", json=body(api, **kw)).status_code == 422
    pair = add(api)
    assert api.client.put(api.url + "/links/" + pair["id"], json=edit_body(api, pair, **kw)).status_code == 422


def test_non_live_and_same_work_endpoints_are_422(api):
    selection_edit(api)
    assert api.client.post(api.url + "/links", json=body(api)).status_code == 422
    api.conn.execute("UPDATE selections SET state = 'included' WHERE research_id = ? AND source_version_id = ?", (api.rid, api.ids["a"]))
    api.conn.execute("UPDATE source_versions SET work_id = ? WHERE id = ?", (api.store.source(api.ids["a"])["work_id"], api.ids["b"]))
    assert api.client.post(api.url + "/links", json=body(api)).status_code == 422


def test_evidence_created_by_the_post_route_protects_the_pdf(api):
    response = api.client.post(f"/api/researches/{api.rid}/uploads", files={"file": ("synthetic.pdf", make_pdf(["SYNTHETIC route evidence"]), "application/pdf")})
    assert response.status_code == 201, response.text
    asset = api.conn.execute("SELECT * FROM source_assets WHERE original_filename = 'synthetic.pdf' ORDER BY rowid DESC").fetchone()
    # Resolve the upload by its real extraction passage, avoiding synthetic paths.
    later = asset["source_version_id"]
    api.conn.execute("UPDATE selections SET state = 'included' WHERE research_id = ? AND source_version_id = ?", (api.rid, later))
    api.tables.add_rows(api.rid, api.tid, [later], api.tables._table(api.rid, api.tid)["version"])
    pid = next(p["id"] for p in api.store.passages_for(later) if p["asset_id"] == asset["id"])
    response = api.client.post(api.url + "/links", json=body(api, to_source_version_id=later, evidence=[{"passage_id": pid, "quote": "SYNTHETIC"}]))
    assert response.status_code == 201, response.text
    assert not api.conn.execute("SELECT * FROM evidence_links").fetchall() and not api.conn.execute("SELECT * FROM cell_evidence_links").fetchall()
    base = f"/api/researches/{api.rid}/sources/{later}/assets/{asset['id']}"
    assert api.client.delete(base).status_code == 200
    assert api.store.research_cites_asset(api.rid, asset["id"])
    assert api.client.get(f"/api/researches/{api.rid}/assets/{asset['id']}").status_code == 404
    assert api.client.post(base + "/restore").status_code == 200
    assert api.client.put(base, files={"file": ("new.pdf", make_pdf(["SYNTHETIC replacement"]), "application/pdf")}).status_code == 200
    assert api.client.get(f"/api/researches/{api.rid}/assets/{asset['id']}").status_code == 200


@pytest.mark.parametrize("decision", ["link", "no_relation"])
def test_a_model_run_does_not_overwrite_a_human_decision(api, decision):
    pair_a = add(api)
    pair_c = add(api, "c")
    assert remove(api, pair_c).status_code == 200
    run = queue(api)
    assert all(api.ids["a"] not in c["from"] and api.ids["c"] not in c["from"] for c in run["target"]["chunks"])
    seen = []
    def respond(si):
        payload = api.store.step_input_payload(si["step_input_id"])
        asked = [c["from"]["source_id"] for c in payload["lineage_target"]["candidates"]]
        seen.extend(asked)
        assert asked == [api.ids["d"]]
        # A human writes after this chunk's send record, before its result arrives.
        add(api, "d")
        if decision == "link":
            return all_links(si)
        output = json.loads(valid_response(si))
        for d in output["decisions"]:
            d.update(decision="no_relation", relation=None, what_changed=None, support_type=None, evidence=[])
        return json.dumps(output)
    api.fake.responder = respond
    execute(api, run)
    assert seen == [api.ids["d"]]
    rejected = [dict(r) for r in api.conn.execute("SELECT * FROM lineage_link_revisions WHERE author = 'model'")]
    assert len(rejected) == 1 and rejected[0]["rejection_code"] == "superseded_by_human"
    value = api.client.get(api.url).json()
    assert any(l["link_id"] == pair_a["id"] and l["revision_id"] == pair_a["current_revision_id"] for l in links(value))
    assert "human_removed" in row(api, "c", value)["reasons"]
    assert all(p["author"] == "human" for p in value["pair_decisions"])
