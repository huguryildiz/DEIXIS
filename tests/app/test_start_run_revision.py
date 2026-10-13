"""A run bound to the question revision the screen showed (UI parity S23b, D14).

The Search plan panel saves a plan as a revision and then starts its search; another window can save a newer revision
in between. `expected_scope_revision` makes the run route create the run only while that revision is still current,
checked inside the transaction that creates it. Workflow behavior only: the worker is not started, records are
SYNTHETIC and no model is asked.
"""

from fastapi.testclient import TestClient

from deixis.api.app import create_app
from fakes import FakeAdapter
from test_api_flow import create, fake_fetch, openalex_client, session, sw_settings


def client_for(tmp_path):
    app = create_app(sw_settings(tmp_path), adapters={"fake": FakeAdapter()}, http_client=openalex_client(200),
                     fetcher=fake_fetch, extra_hosts=("testserver",), trusted_clients=("testclient",), start_worker=False)
    return app, TestClient(app)


def revise(client, rid, question):
    version = client.get(f"/api/researches/{rid}").json()["research"]["version"]
    response = client.post(f"/api/researches/{rid}/scope", json={"question": question, "expected_version": version, "key_terms": None})
    assert response.status_code == 200, response.text
    return response.json()["research"]["current_scope_revision"]


def test_a_run_for_an_older_revision_is_refused_and_nothing_is_created(tmp_path):
    app, client = client_for(tmp_path)
    with client:
        session(client)
        rid = create(client)
        newer = revise(client, rid, "How is SYNTHETIC molecule release scheduling compared?")
        assert newer == 2
        response = client.post(f"/api/researches/{rid}/runs", json={"kind": "discovery", "expected_scope_revision": 1},
                               headers={"Idempotency-Key": "older"})
        assert response.status_code == 409
        assert "question revision 2, not 1" in response.json()["detail"]
        assert client.get(f"/api/researches/{rid}").json()["runs"] == []
        assert app.state.store.conn.execute("SELECT COUNT(*) FROM runs WHERE research_id = ?", (rid,)).fetchone()[0] == 0


def test_a_run_for_the_current_revision_is_created_on_it(tmp_path):
    _, client = client_for(tmp_path)
    with client:
        session(client)
        rid = create(client)
        revision = revise(client, rid, "How is SYNTHETIC molecule release scheduling compared?")
        response = client.post(f"/api/researches/{rid}/runs", json={"kind": "discovery", "expected_scope_revision": revision},
                               headers={"Idempotency-Key": "current"})
        assert response.status_code == 202, response.text
        assert (response.json()["kind"], response.json()["scope_revision"]) == ("discovery", revision)


def test_without_the_field_the_run_takes_the_current_revision_as_before(tmp_path):
    _, client = client_for(tmp_path)
    with client:
        session(client)
        rid = create(client)
        revision = revise(client, rid, "How is SYNTHETIC molecule release scheduling compared?")
        response = client.post(f"/api/researches/{rid}/runs", json={"kind": "discovery"}, headers={"Idempotency-Key": "plain"})
        assert response.status_code == 202, response.text
        assert response.json()["scope_revision"] == revision


def test_a_repeated_request_returns_the_run_it_created_even_after_a_newer_revision(tmp_path):
    _, client = client_for(tmp_path)
    with client:
        session(client)
        rid = create(client)
        first = client.post(f"/api/researches/{rid}/runs", json={"kind": "discovery", "expected_scope_revision": 1},
                            headers={"Idempotency-Key": "repeat"}).json()
        client.post(f"/api/runs/{first['id']}/cancel")
        revise(client, rid, "How is SYNTHETIC molecule release scheduling compared?")
        again = client.post(f"/api/researches/{rid}/runs", json={"kind": "discovery", "expected_scope_revision": 1},
                            headers={"Idempotency-Key": "repeat"})
        assert again.status_code == 202
        assert again.json()["id"] == first["id"]
