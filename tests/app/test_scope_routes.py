"""An earlier question revision, read back for the research page's "Show" (UI parity S8, R12).

Workflow behaviour only: SYNTHETIC questions, the fake adapter, no run. Passing shows the route returns the revision as
it was saved and refuses one that does not exist; it says nothing about how the page draws it.
"""

from fastapi.testclient import TestClient

from test_api_flow import app_for, create, session


def test_an_earlier_revision_reads_back_as_it_was_saved(tmp_path):
    with TestClient(app_for(tmp_path)) as client:
        session(client)
        rid = create(client, question="SYNTHETIC how is molecule release scheduling optimized?")
        version = client.get(f"/api/researches/{rid}").json()["research"]["version"]
        revised = client.post(f"/api/researches/{rid}/scope", json={"question": "SYNTHETIC a narrower molecule release question",
                                                                    "expected_version": version, "key_terms": "molecule release; scheduling"})
        assert revised.status_code == 200, revised.text

        first = client.get(f"/api/researches/{rid}/scope-revisions/1").json()
        assert (first["revision"], first["question"], first["source_scope"], first["key_terms"]) == (
            1, "SYNTHETIC how is molecule release scheduling optimized?", "academic", None)
        assert first["created_at"]
        second = client.get(f"/api/researches/{rid}/scope-revisions/2").json()
        assert (second["question"], second["key_terms"]) == ("SYNTHETIC a narrower molecule release question", "molecule release; scheduling")

        assert client.get(f"/api/researches/{rid}/scope-revisions/3").status_code == 404
        assert client.get("/api/researches/no-such-research/scope-revisions/1").status_code == 404
