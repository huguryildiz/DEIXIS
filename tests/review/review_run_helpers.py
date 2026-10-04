"""Isolated synthetic API libraries and scripted review calls."""

import json
import time
from contextlib import contextmanager
from types import SimpleNamespace

import httpx
from fastapi.testclient import TestClient

from deixis.api.app import create_app
from deixis.config import Settings
from deixis.storage import db
from deixis.workflow.review.store import ReviewStore
from tests.fakes import FakeAdapter, valid_response
from tests.app.test_api_flow import session


def finding_response(payload):
    result = json.loads(valid_response(payload))
    part = payload["review_input"]
    result["findings"] = [{"finding_handle": "f1", "target_ref": {"kind": "claim", "ref": part["claims"][0]["claim_ref"]},
        "kind": "assumption_unstated", "evidence": [], "rationale": "SYNTHETIC rationale.",
        "possible_impact": "SYNTHETIC impact.", "suggested_fix": "SYNTHETIC suggested edit.", "uncertainty": "SYNTHETIC limit."}]
    return json.dumps(result)


@contextmanager
def review_api(lib, tmp_path, *, adapter=None, start_worker=False):
    adapter = adapter or FakeAdapter(responder=finding_response, models=["review-model", "fake-model"], efforts=["high"])
    directory = tmp_path / db.new_id("api")
    directory.mkdir()
    conn = db.connect(directory / "library.sqlite")
    lib["conn"].backup(conn)
    conn.close()

    def no_network(request):
        raise AssertionError(f"No HTTP allowed: {request.url.host}")

    http = httpx.AsyncClient(transport=httpx.MockTransport(no_network))
    app = create_app(Settings(data_dir=directory, port=8878, fulltext_fetch="off", citation_chaining="off"),
        adapters={"fake": adapter}, http_client=http, start_worker=start_worker, trusted_clients=("testclient",))
    with TestClient(app, base_url="http://127.0.0.1:8878", raise_server_exceptions=False) as client:
        session(client)
        api = SimpleNamespace(client=client, app=app, store=app.state.store, conn=app.state.store.conn,
            adapter=adapter, rid=lib["rid"], report_id=lib["report_id"], answer_id=lib["answer_id"],
            url=f"/api/researches/{lib['rid']}/reviews", lib=lib)
        yield api


def body(api, kind="report", **changes):
    return {"target_kind": kind, "target_id": getattr(api, kind + "_id"), "focus": "source_support", "owner_note": None,
            "connection": "fake", "model": "review-model", "reasoning_effort": "high"} | changes


def preview(api, data=None):
    response = api.client.post(api.url + "/preview", json=data or body(api))
    assert response.status_code == 200, response.text
    return response.json()


def start(api, data=None, key="SYNTHETIC-start"):
    data = data or body(api)
    shown = preview(api, data)
    command = data | {k: shown[k] for k in ("snapshot_sha256", "preview_fingerprint")}
    response = api.client.post(api.url, json=command, headers={"Idempotency-Key": key})
    assert response.status_code == 202, response.text
    return response.json(), command, shown


def read(api, review_id):
    response = api.client.get(api.url + "/" + review_id)
    assert response.status_code == 200, response.text
    return response.json()


def turn(api):
    async def guarded():
        try:
            await api.app.state.worker._turn()
        except BaseException as exc:
            if type(exc).__name__ != "Crash":
                raise
            return exc
    result = api.client.portal.call(guarded)
    if isinstance(result, BaseException):
        raise result


def terminal(api, review_id, statuses=("completed", "partial", "failed", "paused", "cancelled")):
    stop = time.monotonic() + 10
    while time.monotonic() < stop:
        card = read(api, review_id)
        if card["state"] in statuses:
            return card
        time.sleep(.01)
    raise AssertionError("synthetic review did not reach a terminal state")


def control(api, run_id, action):
    response = api.client.post(f"/api/runs/{run_id}/{action}")
    assert response.status_code == 200, response.text
    return response.json()


def resolved_rows(api, card):
    return ReviewStore(api.conn).findings(card["id"])


def two_groups(api, monkeypatch):
    from deixis.domain import skill
    from deixis.workflow.flow import CAPABILITIES
    from deixis.workflow.report.store import ReportStore
    from deixis.workflow.review import run as reviews
    from deixis.workflow.review.reader import ReviewReader
    from deixis.workflow.review.snapshot import build_snapshot
    saved, _ = build_snapshot(ReviewReader(api.store, ReportStore(api.store)), api.rid, "report", api.report_id)
    row = {"focus": "source_support", "owner_note": None, "requested_connection": "fake", "requested_model": "review-model"}
    sizes = []
    for claim in saved["claims"]:
        payload = reviews.review_step_input("rvs_" + "0" * 20, saved, row,
            {"claim_refs": [claim["claim_ref"]], "group_index": 2, "group_count": 2}, run_id="run_" + "0" * 20,
            step_id="stp_" + "0" * 20, research_id=api.rid, package_hash=skill.package_hash(), capabilities=CAPABILITIES,
            budget=reviews.review_budget(2), step_input_id="sti_" + "0" * 20, created_at=reviews.PLAN_TIME)
        sizes.append(reviews.first_request(payload, api.app.state.package, api.adapter.enforces_schema))
    monkeypatch.setattr(reviews, "REVIEW_GROUP_CHAR_LIMIT", max(sizes) + 50)
