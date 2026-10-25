"""The PDF waiting list of a real `sw` research, a dropped file's match and its confirmation (slice 18a).

Driven through the API with the retrieval run of slice 10 (inside discovery, D98): works no route found a PDF for are
left `no_fulltext`, and that is what the list reads. Records, titles and files are SYNTHETIC and from two fields,
every transport is mocked and the model is scripted. The store-level cases write the plan and the decisions the way
the runs write them. Passing shows the list, the match and the refusals behave as the slice says; it says nothing
about how often a publisher's PDF names its own DOI, or whether an institution's proxy login works (not tried).
"""

import json
import time

import pytest

from deixis.storage import db
from deixis.workflow import waiting
from deixis.workflow.decisions import DecisionStore
from deixis.workflow.store import Store
from helpers import make_pdf
from test_abstract_flow import client_of, records_of
from test_fulltext_flow import Fetcher, Transport, app_for, discover, ok, work

PREFIX = "https://login.proxy.synthetic.edu/login?url="


def named(doi, title=""):
    """A publisher-like first page: the title, then the DOI line."""
    return make_pdf([f"{title}\nhttps://doi.org/{doi}\nSYNTHETIC body text of the paper.".strip()])


def sw_research(tmp_path, monkeypatch, workflow="sw"):
    """Four SYNTHETIC works: W1 has an open PDF, W2–W4 have none, so the fetch leaves them `no_fulltext`."""
    fetcher = Fetcher({"https://example.org/w1.pdf": ok()})
    works = [work(1, pdf_url="https://example.org/w1.pdf"), work(2), work(3), work(4)]
    app = app_for(tmp_path, monkeypatch, Transport(works), fetcher, workflow=workflow)
    client = client_of(app)
    rid, _, view, run = discover(client)
    assert run["status"] == "completed", run
    return app, client, rid


def plan_heads(store, rid):
    from deixis.workflow import small_batch
    run_id = store.conn.execute("SELECT id FROM runs WHERE research_id = ? AND kind = 'discovery'"
                                " ORDER BY created_at DESC LIMIT 1", (rid,)).fetchone()[0]
    return store.existing_step(run_id, small_batch.LIST_KEY)["output"]["order"]


def settled_runs(client, rid):
    deadline = time.time() + 30
    while time.time() < deadline:
        runs = client.get(f"/api/researches/{rid}").json()["runs"]
        if all(r["status"] in ("completed", "failed", "paused", "cancelled") for r in runs):
            return [r["id"] for r in runs]
        time.sleep(0.05)
    raise AssertionError("the queued runs did not settle")


def match(client, rid, *files):
    response = client.post(f"/api/researches/{rid}/uploads/match",
                           files=[("files", (name, data, "application/pdf")) for name, data in files])
    assert response.status_code == 200, response.text
    return response.json()


def confirm(client, rid, data, found, version, **override):
    fields = {"work_id": found["work"]["work_id"], "source_version_id": version, "scope_revision": found["scope_revision"],
              "versions_digest": found["work"]["versions_digest"], "sha256": found["sha256"]} | override
    return client.post(f"/api/researches/{rid}/waiting/uploads", data=fields,
                       files={"file": ("dropped.pdf", data, "application/pdf")})


# ---- the list through the API -----------------------------------------------------------------------------------

def test_the_list_holds_the_works_no_route_found_a_pdf_for_in_the_plan_s_order(tmp_path, monkeypatch):
    app, client, rid = sw_research(tmp_path, monkeypatch)
    try:
        store = app.state.store
        records = records_of(store, rid)
        # The runs the fast-path discovery queued (its answer, the answer's review, a background read) settle first.
        runs_before = settled_runs(client, rid)
        view = client.get(f"/api/researches/{rid}/waiting").json()
        counts = client.get(f"/api/researches/{rid}").json()["counts"]
        order = plan_heads(store, rid)
        runs_after = [r["id"] for r in client.get(f"/api/researches/{rid}").json()["runs"]]
    finally:
        client.__exit__(None, None, None)
    waiting_heads = [row["head"] for row in view["rows"]]
    assert set(waiting_heads) == {records["W2"], records["W3"], records["W4"]}
    assert waiting_heads == [head for head in order if head in waiting_heads]
    assert [row["place"] for row in view["rows"]] == [1, 2, 3]
    assert {row["reason_code"] for row in view["rows"]} == {"no_fulltext"}
    assert counts["waiting_for_pdf"] == view["count"] == 3 and view["has_plan"] and not view["via_proxy"]
    row = next(row for row in view["rows"] if row["head"] == records["W2"])
    assert row["doi"] == "10.1/oa.2" and row["links"]["doi"] == "https://doi.org/10.1/oa.2"
    assert row["find_pdf_source_version_id"] == records["W2"]
    assert [v["source_version_id"] for v in row["versions"]] == [records["W2"]] and row["versions_digest"]
    assert runs_after == runs_before  # reading the list opened nothing
    # Each row says why it is here: its place in the frozen ranking, where the search found it, the abstract verdict.
    for waiting_row in view["rows"]:
        rel = waiting_row["relevance"]
        assert isinstance(rel["rank"], int) and 1 <= rel["rank"] <= rel["ranked"]
        assert rel["origin"] in ("search", "chain", "user") and rel["abstract"] in ("candidate", "unresolved", "out_of_scope")


# ---- the match -------------------------------------------------------------------------------------------------


# ---- the confirmation --------------------------------------------------------------------------------------------

def test_a_confirmed_file_goes_to_the_chosen_version_and_the_work_leaves_the_list(tmp_path, monkeypatch):
    app, client, rid = sw_research(tmp_path, monkeypatch)
    try:
        store = app.state.store
        records = records_of(store, rid)
        data = named("10.1/oa.2")
        found = match(client, rid, ("doi.pdf", data))["matches"][0]
        runs_before = len(client.get(f"/api/researches/{rid}").json()["runs"])
        response = confirm(client, rid, data, found, records["W2"])
        view = client.get(f"/api/researches/{rid}/waiting").json()
        after = client.get(f"/api/researches/{rid}").json()
        code = DecisionStore(store).current(rid, records["W2"], "fulltext")["reason_code"]
        asset = store.conn.execute("SELECT origin, original_filename FROM source_assets WHERE source_version_id = ?"
                                   " AND removed_at IS NULL", (records["W2"],)).fetchone()
        events = [row[0] for row in store.conn.execute("SELECT type FROM events WHERE research_id = ?", (rid,))]
    finally:
        client.__exit__(None, None, None)
    assert response.status_code == 201, response.text
    assert response.json()["attached"]["source_version_id"] == records["W2"]
    assert records["W2"] not in [row["head"] for row in view["rows"]] and view["count"] == 2
    assert after["counts"]["waiting_for_pdf"] == 2
    assert tuple(asset) == ("user_upload", "dropped.pdf")
    # Slice 18b: the chosen version gets the code the file asks for; with reading off here no reading is queued.
    assert code == "not_read_yet" and len(after["runs"]) == runs_before
    assert response.json()["attached"]["reading"] == "model_off"
    assert "waiting_pdf_attached" in events


# ---- the candidate set and the refusals at the store ---------------------------------------------------------------

@pytest.fixture
def store(tmp_path):
    connection = db.connect(tmp_path / "library.sqlite")
    db.migrate(connection)
    yield Store(connection)
    connection.close()


def write_plan(lib, heads):
    run = lib.new_run("fulltext_fetch")
    step = lib.store.step(run, "fulltext_plan", "code:fulltext_plan")
    lib.store.finish_step(step["id"], "succeeded", output={"works": heads})
    return step["id"]


