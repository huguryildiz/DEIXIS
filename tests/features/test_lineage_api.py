"""Human API checks with CSRF, real persistence and synthetic evidence only."""

import json

import pytest

from deixis.workflow.lineage_run import LineagePlanner
from deixis.workflow.lineage_store import LineageStore
from fakes import FakeAdapter
from fakes import valid_response
from test_lineage_plan import api as plan_api
from test_lineage_flow import all_links, queue, execute, reextract
from test_lineage_view import model_decision, links, row


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


def test_human_add_needs_a_placed_quote_in_a_passage_of_the_later_work(api):
    for evidence in ([{"passage_id": api.passages["a"], "quote": "SYNTHETIC"}],
                     [{"passage_id": api.passages["b"], "quote": "This text is absent"}],
                     [{"passage_id": "psg_unknown", "quote": "SYNTHETIC"}]):
        response = api.client.post(api.url + "/links", json=body(api, evidence=evidence))
        assert response.status_code == 422, response.text
    response = api.client.post(api.url + "/links", json=body(api))
    assert response.status_code == 201 and len(response.json()["components"]) == 1


@pytest.mark.parametrize("decision", ["new"])
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


def test_human_remove_is_listed_as_human_removed_and_never_reactivated_by_a_run(api):
    pair = add(api)
    assert remove(api, pair).status_code == 200
    api.fake.responder = all_links
    execute(api, queue(api))
    current = api.lineage._current(api.lineage.link_by_id(pair["id"]))
    assert current["kind"] == "human_remove" and "human_removed" in row(api, "a")["reasons"]
    assert all(api.ids["a"] not in [c["from"]["source_id"] for c in api.store.step_input_payload(si["step_input_id"])["lineage_target"]["candidates"]] for si in api.fake.calls)


def test_human_routes_require_csrf(api):
    pair = add(api)
    api.client.headers.pop("x-deixis-csrf")
    assert api.client.post(api.url + "/links", json=body(api, "c")).status_code == 403
    assert api.client.put(api.url + "/links/" + pair["id"], json=edit_body(api, pair)).status_code == 403
    assert remove(api, pair).status_code == 403
    assert api.client.get(api.url).status_code == 200


@pytest.mark.parametrize("decision", ["link"])
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
