""""Continue without PDF" on the waiting list (D46): the decision is stored, the work leaves every waiting count, it
can be undone, a file for it clears it, and the answer reads the work from its abstract.

Driven through the API with the fast-path discovery of `test_waiting_flow` (W1 has an open PDF, W2–W4 none). Records,
titles and files are SYNTHETIC, transports are mocked and the model is scripted. Passing shows the workflow behaves as
D46 says; it says nothing about whether a person finds the button, or about answer quality from abstracts alone.
"""

from deixis.workflow import fast_answer
from deixis.workflow import waiting as waiting_rules
from test_abstract_flow import records_of
from test_fulltext_flow import wait, wait_for_all
from test_waiting_flow import confirm, match, named, sw_research


def waiting(client, rid):
    return client.get(f"/api/researches/{rid}/waiting").json()


def skip(client, rid, work_id):
    return client.post(f"/api/researches/{rid}/waiting/skips", json={"work_id": work_id})


def awaiting_pdf(client, rid):
    return next(r for r in client.get("/api/researches").json() if r["id"] == rid)["awaiting"]["pdf"]


def work_of(view, head):
    return next(row["work_id"] for row in view["rows"] + view["skipped"] if row["head"] == head)


def test_a_skipped_work_leaves_the_list_and_every_waiting_count_and_undo_brings_it_back(tmp_path, monkeypatch):
    app, client, rid = sw_research(tmp_path, monkeypatch)
    try:
        store = app.state.store
        records = records_of(store, rid)
        wait_for_all(client, rid)
        before = waiting(client, rid)
        counts_before = client.get(f"/api/researches/{rid}").json()["counts"]
        pdf_before = awaiting_pdf(client, rid)
        w2 = work_of(before, records["W2"])
        runs_before = len(client.get(f"/api/researches/{rid}").json()["runs"])
        response = skip(client, rid, w2)
        after = waiting(client, rid)
        counts_after = client.get(f"/api/researches/{rid}").json()["counts"]
        pdf_after = awaiting_pdf(client, rid)
        stored = store.conn.execute("SELECT research_id, work_id FROM pdf_skips").fetchall()
        runs_after = len(client.get(f"/api/researches/{rid}").json()["runs"])
        again = skip(client, rid, w2)
        not_waiting = skip(client, rid, "wrk_not_on_the_list")
        undone = client.delete(f"/api/researches/{rid}/waiting/skips/{w2}")
        undone_twice = client.delete(f"/api/researches/{rid}/waiting/skips/{w2}")
        restored = waiting(client, rid)
        counts_restored = client.get(f"/api/researches/{rid}").json()["counts"]
        events = [row[0] for row in store.conn.execute("SELECT type FROM events WHERE research_id = ?", (rid,))]
    finally:
        client.__exit__(None, None, None)
    assert before["count"] == 3 and before["skipped"] == []
    assert response.status_code == 201, response.text
    # The endpoint answers with the list as the GET reads it.
    assert response.json()["count"] == after["count"] == 2
    assert w2 not in [row["work_id"] for row in after["rows"]]
    assert [row["place"] for row in after["rows"]] == [1, 2]
    [skipped] = after["skipped"]
    assert skipped["work_id"] == w2 and skipped["head"] == records["W2"] and skipped["skipped_at"]
    assert skipped["reason_code"] == "no_fulltext" and skipped["versions"] and skipped["place"] == 1
    assert skipped["answer_reads_abstract"] is (skipped["relevance"]["abstract"] == "candidate")
    assert [tuple(row) for row in stored] == [(rid, w2)]
    assert runs_after == runs_before  # skipping queues nothing
    # Every count of "waiting for your PDF" drops by one: the tab, the shell's awaiting count, the flow's five.
    assert counts_before["waiting_for_pdf"] == 3 and counts_after["waiting_for_pdf"] == 2
    assert pdf_before == 3 and pdf_after == 2
    flow_before, flow_after = counts_before["flow"], counts_after["flow"]
    assert flow_before["five"]["waiting_for_pdf"] == 3 and flow_after["five"]["waiting_for_pdf"] == 2
    assert flow_after["buckets"]["abstract_by_choice"] == 1 and flow_before["buckets"]["abstract_by_choice"] == 0
    assert sum(flow_after["buckets"].values()) == flow_after["works"]
    # The full text of a skipped work was still not retrieved.
    assert {b["key"]: b["count"] for b in counts_after["flow_boxes"]["boxes"]}["fulltext_not_retrieved"] == 3
    assert again.status_code == 409 and again.json()["detail"]["reason"] == "already_skipped"
    assert not_waiting.status_code == 409 and not_waiting.json()["detail"]["reason"] == "not_waiting"
    assert undone.status_code == 200 and undone.json()["count"] == 3 and undone.json()["skipped"] == []
    assert undone_twice.status_code == 404
    assert restored["count"] == 3 and counts_restored["waiting_for_pdf"] == 3
    assert {"waiting_pdf_skipped", "waiting_pdf_skip_undone"} <= set(events)


def test_a_skip_needs_the_csrf_header(tmp_path, monkeypatch):
    app, client, rid = sw_research(tmp_path, monkeypatch)
    try:
        w2 = waiting(client, rid)["rows"][0]["work_id"]
        token = client.headers.pop("x-deixis-csrf")
        refused = skip(client, rid, w2)
        refused_undo = client.delete(f"/api/researches/{rid}/waiting/skips/{w2}")
        client.headers["x-deixis-csrf"] = token
        stored = app.state.store.conn.execute("SELECT COUNT(*) FROM pdf_skips").fetchone()[0]
    finally:
        client.__exit__(None, None, None)
    assert refused.status_code == 403 and refused_undo.status_code == 403 and stored == 0


def test_a_file_for_a_skipped_work_clears_the_skip_and_normal_reading_applies(tmp_path, monkeypatch):
    app, client, rid = sw_research(tmp_path, monkeypatch)
    try:
        store = app.state.store
        records = records_of(store, rid)
        w2 = work_of(waiting(client, rid), records["W2"])
        assert skip(client, rid, w2).status_code == 201
        data = named("10.1/oa.2")
        found = match(client, rid, ("doi.pdf", data))["matches"][0]
        response = confirm(client, rid, data, found, records["W2"])
        view = waiting(client, rid)
        in_force = waiting_rules.skipped(store, rid)
        counts = client.get(f"/api/researches/{rid}").json()["counts"]
    finally:
        client.__exit__(None, None, None)
    # The skipped work is still one a file may be added for, and is proposed by its DOI.
    assert found["work"]["work_id"] == w2
    assert response.status_code == 201, response.text
    assert in_force == {} and view["skipped"] == [] and counts["flow"]["buckets"]["abstract_by_choice"] == 0
    assert w2 not in [row["work_id"] for row in view["rows"]]  # its PDF text is in hand now


def test_a_skipped_work_is_given_to_the_answer_from_its_abstract(tmp_path, monkeypatch):
    app, client, rid = sw_research(tmp_path, monkeypatch)
    try:
        store = app.state.store
        wait_for_all(client, rid)
        view = waiting(client, rid)
        row = next(r for r in view["rows"] if r["relevance"]["abstract"] == "candidate")
        assert skip(client, rid, row["work_id"]).status_code == 201
        assert waiting(client, rid)["skipped"][0]["answer_reads_abstract"] is True
        run_id = client.post(f"/api/researches/{rid}/runs", json={"kind": "answer"}).json()["id"]
        research, run = wait(client, rid, run_id)
        plan = store.existing_step(run_id, fast_answer.INPUT)["output"]
        kinds = {r["id"]: r["kind"] for r in store.conn.execute(
            "SELECT id, kind FROM passages WHERE source_version_id = ?", (row["head"],))}
        answer = next(a for a in research["answers"] if a["run_id"] == run_id)
    finally:
        client.__exit__(None, None, None)
    assert run["status"] == "completed", run
    item = next(i for i in plan["items"] if i["work_id"] == row["work_id"])
    # Routed to its abstract, not left out, and only its abstract passage goes to the model.
    assert item["route"] == "abstract" and not item["reason"] and item["abstract_ids"]
    given = [pid for pid in plan["passage_ids"] if pid in kinds]
    assert given and {kinds[pid] for pid in given} == {"abstract"}
    assert row["head"] in answer["inputs_given"]["source_ids"]
    assert answer["inputs_given"]["depth"]["abstract"] >= 1
    # A claim that cites only abstract passages is labelled "From abstract" (`evidence_basis` = "abstract").
    for claim in answer["claims"]:
        if claim["evidence"] and {e["kind"] for e in claim["evidence"]} == {"abstract"}:
            assert claim["evidence_basis"] == "abstract"
