"""GET /api/researches/{id}/citation-map: read only, 404 for an unknown research."""

from fastapi.testclient import TestClient

from test_api_flow import app_for, create, session


def test_citation_map_route(tmp_path):
    with TestClient(app_for(tmp_path)) as client:
        session(client)
        rid = create(client)
        body = client.get(f"/api/researches/{rid}/citation-map")
        assert body.status_code == 200, body.text
        data = body.json()
        assert set(data) == {"nodes", "edges", "outside", "counts"} and data["nodes"] == []
        assert client.get("/api/researches/res_missing/citation-map").status_code == 404
