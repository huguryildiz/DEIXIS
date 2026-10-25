"""POST /api/researches/{id}/outside-works: an outside work of the citation map joins the research undecided.

Stored records only: any provider request or file fetch fails the test. Records are SYNTHETIC.
"""

import httpx
import pytest
from fastapi.testclient import TestClient

from deixis.api.app import create_app
from deixis.providers.common import ProviderRecord
from fakes import FakeAdapter
from test_api_flow import session, sw_settings


def refuse(request):
    raise AssertionError(f"no provider request is allowed: {request.url}")


async def no_fetch(*args, **kwargs):
    raise AssertionError("no file fetch is allowed")


def record(oid, refs=None, doi=None, other_versions=()):
    return ProviderRecord(provider_record_id=oid, title=f"Work {oid}", authors=["Ada Lovelace"], year=2020,
                          venue="Synthetic venue", publication_type="article", doi=doi, landing_url=None,
                          oa_pdf_url=None, oa_pdf_version=None, version_label=None, abstract=None, abstract_origin=None,
                          identifiers={"openalex": oid}, raw={}, references=None if refs is None else tuple(refs),
                          other_versions=list(other_versions))


@pytest.fixture
def api(tmp_path):
    app = create_app(sw_settings(tmp_path), adapters={"fake": FakeAdapter()},
                     http_client=httpx.AsyncClient(transport=httpx.MockTransport(refuse)), fetcher=no_fetch,
                     extra_hosts=("testserver",), trusted_clients=("testclient",), start_worker=False)
    with TestClient(app) as client:
        session(client)
        rid = client.post("/api/researches", json={"question": "SYNTHETIC citation question?", "model_connection": "fake",
                                                   "requested_model": "fake-model", "effort": "quick"}).json()["research"]["id"]
        store = app.state.store
        for run in store.conn.execute("SELECT id FROM runs WHERE research_id = ?", (rid,)).fetchall():
            store.update_run(run[0], status="cancelled")
        # One included work citing W50 and W60: with one counting work, both are outside works.
        cited, _ = store.upsert_provider_source("openalex", record("W1", refs=["W50", "W60"]), None)
        store.add_to_corpus(rid, cited, "library", selection_state="included", selection_origin="user")
        yield client, store, rid


def outside(client, rid):
    return {o["openalex_id"]: o for o in client.get(f"/api/researches/{rid}/citation-map").json()["outside"]}


def node(client, rid, oid):
    return next((n for n in client.get(f"/api/researches/{rid}/citation-map").json()["nodes"] if oid in n["openalex_ids"]), None)


def source(client, rid, svid):
    return next((s for s in client.get(f"/api/researches/{rid}").json()["sources"] if s["source_version_id"] == svid), None)


def test_a_described_outside_work_joins_undecided_as_the_persons(api):
    client, store, rid = api
    stored, _ = store.upsert_provider_source("openalex", record("W50"), None)  # as the map run's metadata step stores it
    assert outside(client, rid)["W50"]["source_version_id"] == stored
    client.headers.pop("x-deixis-csrf")
    assert client.post(f"/api/researches/{rid}/outside-works", json={"openalex_id": "W50"}).status_code == 403
    session(client)
    added = client.post(f"/api/researches/{rid}/outside-works", json={"openalex_id": "https://openalex.org/w50"})
    assert added.status_code == 201, added.text
    body = added.json()
    assert body["source_version_id"] == stored and body["restored"] is False and "sources" in body
    row = source(client, rid, stored)
    assert row["added_by"] == "library" and row["version_role"] == "record" and row["found_in_revision"] is None
    assert row["selection"]["state"] == "pending" and row["selection"]["origin"] == "user"
    assert "W50" not in outside(client, rid) and node(client, rid, "W50")["state"] == "pending"
    event = store.conn.execute("SELECT type, payload_json FROM events WHERE research_id = ? ORDER BY id DESC LIMIT 1",
                               (rid,)).fetchone()
    assert event["type"] == "source_added" and stored in event["payload_json"]


def test_add_undo_add_restores_the_earlier_choice(api):
    client, store, rid = api
    stored, _ = store.upsert_provider_source("openalex", record("W50"), None)
    first = client.post(f"/api/researches/{rid}/outside-works", json={"openalex_id": "W50"}).json()
    version = source(client, rid, stored)["selection"]["version"]
    chosen = client.patch(f"/api/researches/{rid}/selections/{stored}",
                          json={"state": "included", "expected_version": version, "reason": "SYNTHETIC: on topic"})
    assert chosen.status_code == 200, chosen.text
    undo = client.request("DELETE", f"/api/researches/{rid}/sources", json={"source_version_ids": [first["source_version_id"]]})
    assert undo.status_code == 200 and undo.json()["changed_source_version_ids"] == [stored]
    assert source(client, rid, stored) is None and outside(client, rid)["W50"]["removed_from_research"] is True

    again = client.post(f"/api/researches/{rid}/outside-works", json={"openalex_id": "W50"})
    assert again.status_code == 201, again.text
    assert again.json()["restored"] is True and again.json()["changed_source_version_ids"] == [stored]
    selection = source(client, rid, stored)["selection"]
    assert (selection["state"], selection["origin"], selection["user_reason"]) == ("included", "user", "SYNTHETIC: on topic")
    assert "W50" not in outside(client, rid) and node(client, rid, "W50")["state"] == "included"
    assert store.conn.execute("SELECT type FROM events WHERE research_id = ? ORDER BY id DESC LIMIT 1",
                              (rid,)).fetchone()["type"] == "source_restored"


def resolve(store, svid, oid):
    # As the map run records an upload it found in OpenAlex (migration 0015); no identifier mapping is written.
    store.conn.execute("INSERT INTO citation_map_resolutions (source_version_id, method, status, openalex_id, doi,"
                       " run_id, resolved_at) VALUES (?, 'record_match', 'resolved', ?, NULL, NULL, '2026-10-16')",
                       (svid, oid))


def upload(client, store, rid, title, reason):
    svid = store.create_upload_source(title)
    store.add_to_corpus(rid, svid, "user_upload", selection_state="excluded", selection_origin="user")
    version = source(client, rid, svid)["selection"]["version"]
    assert client.patch(f"/api/researches/{rid}/selections/{svid}",
                        json={"state": "included", "expected_version": version, "reason": reason}).status_code == 200
    return svid


def test_adding_changes_no_search_count(api):
    from deixis.workflow import prisma_s

    client, store, rid = api
    store.upsert_provider_source("openalex", record("W50"), None)

    def counts():
        data = prisma_s.export(store, rid)
        tables = {t: store.conn.execute(f"SELECT COUNT(*) FROM {t} WHERE research_id = ?", (rid,)).fetchone()[0]
                  for t in ("candidates", "candidate_hits", "search_runs")}
        items = {i["number"]: i["values"] for i in data["items"]}
        # Item 16 counts the research's members and works apart from what searches returned.
        dedup = {k: v for k, v in items[16].items() if k not in ("active_members", "works")}
        return (tables, data["search_table"], [(n, v) for n, v in items.items() if n not in (7, 16)], dedup,
                items[7]["brought"], items[16]["active_members"], items[16]["works"])

    before = counts()
    assert client.post(f"/api/researches/{rid}/outside-works", json={"openalex_id": "W50"}).status_code == 201
    after = counts()
    assert after[:4] == before[:4]
    assert before[4] == {"library": 1} and after[4] == {"library": 2}  # PRISMA-S item 7: brought by the person
    assert after[5:] == (before[5] + 1, before[6] + 1)
