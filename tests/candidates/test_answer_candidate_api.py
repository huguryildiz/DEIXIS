"""SYNTHETIC API plumbing of candidates written from an answer (D98); FakeAdapter only, no live request."""
import json

from deixis.storage import db
from test_candidate_api import api  # noqa: F401  (fixture)

ASPECTS = ["SYNTHETIC aspect one.", "SYNTHETIC aspect two."]


def answer(api):
    run = api.store.create_run(api.rid, "answer", {}, None)
    id_ = db.new_id("ans")
    api.conn.execute(
        "INSERT INTO answers (id, research_id, run_id, scope_revision, status, draft_json, validation_json, report_version,"
        " created_at) VALUES (?, ?, ?, 1, 'structurally_valid', ?, '{}', 1, 'now')",
        (id_, api.rid, run["id"], json.dumps({"title": "SYNTHETIC", "unanswered_aspects": ASPECTS})))
    return f"/api/researches/{api.rid}/answers/{id_}/candidates"


def test_create_reuse_and_list(api):
    url = answer(api)
    first = api.client.post(url, json={"aspect_index": 1, "text": "  SYNTHETIC claim.  "}, headers={"Idempotency-Key": "a"})
    assert first.status_code == 201, first.text
    body = first.json()
    assert body["reused"] is False and body["replayed"] is False and body["card"]["origin"] == "answer_thread"
    assert body["card"]["origin_text"] == "SYNTHETIC claim."
    assert body["card"]["origin_provenance"]["aspect_text"] == ASPECTS[1]
    again = api.client.post(url, json={"aspect_index": 1, "text": "SYNTHETIC other."})
    assert again.status_code == 201 and again.json()["reused"] is True and again.json()["card"]["id"] == body["card"]["id"]
    assert again.json()["replayed"] is False
    generic = api.client.post(url, json={"text": "SYNTHETIC generic claim."}, headers={"Idempotency-Key": "g"})
    assert generic.status_code == 201 and generic.json()["card"]["origin"] == "answer_thread"
    # The same submission again (its response was lost): the same candidate and no second link.
    retry = api.client.post(url, json={"text": "SYNTHETIC generic claim."}, headers={"Idempotency-Key": "g"})
    assert retry.status_code == 201 and retry.json()["replayed"] is True and retry.json()["card"]["id"] == generic.json()["card"]["id"]
    listed = api.client.get(url)
    assert listed.status_code == 200, listed.text
    rows = listed.json()["candidates"]
    assert [(r["aspect_index"], r["origin_text"]) for r in rows] == [(1, "SYNTHETIC claim."), (None, "SYNTHETIC generic claim.")]
    assert all(r["search"] is None and r["run"] is None for r in rows)
    decompose = listed.json()["decompose"]
    assert decompose["model"] == "fake-model" and decompose["max_provider_requests"] == 0
    # The research's candidate list shows them too; nothing was searched.
    assert {c["origin"] for c in api.client.get(api.url).json()} == {"answer_thread"}
    assert api.requests == []


def test_text_safety_and_refusals(api):
    url = answer(api)
    for body in ({"text": "SYNTHETIC\x00"}, {"text": "   "}, {"text": "x" * 2001}, {"text": "ok", "aspect_index": True},
                 {"text": "ok", "aspect_index": "0"}, {"text": "ok", "aspect_index": -1}, {"text": "ok", "extra": 1},
                 {"text": "ok", "aspect_index": 2}, {"text": "\ud800"}):
        response = api.client.post(url, content=json.dumps(body), headers={"content-type": "application/json"})
        assert response.status_code == 422, (body, response.text)
    assert api.client.post(url.replace("/answers/", "/answers/x"), json={"text": "ok"}).status_code == 404
    assert api.client.get(url.replace("/answers/", "/answers/x")).status_code == 404
    assert api.client.get(url).json()["candidates"] == []
