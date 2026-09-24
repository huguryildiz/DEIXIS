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
from test_queue import Lib

PREFIX = "https://login.proxy.synthetic.edu/login?url="
UNRELATED = make_pdf(["SYNTHETIC notes on river gauges and flood stage readings."])


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
    row = store.conn.execute(
        "SELECT s.output_json FROM run_steps s JOIN runs r ON r.id = s.run_id WHERE r.research_id = ?"
        " AND s.operation_key = 'fulltext_plan' AND s.status = 'succeeded'", (rid,)).fetchone()
    return json.loads(row[0])["works"]


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
        view = client.get(f"/api/researches/{rid}/waiting").json()
        counts = client.get(f"/api/researches/{rid}").json()["counts"]
        order = plan_heads(store, rid)
        runs_before = [r["id"] for r in client.get(f"/api/researches/{rid}").json()["runs"]]
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
    assert len(runs_before) == 1  # reading the list opened nothing


def test_a_legacy_research_has_no_list_and_its_match_answers_as_it_did(tmp_path, monkeypatch):
    app, client, rid = sw_research(tmp_path, monkeypatch, workflow="legacy")
    try:
        refused = client.get(f"/api/researches/{rid}/waiting")
        counts = client.get(f"/api/researches/{rid}").json()["counts"]
        found = match(client, rid, ("a.pdf", named("10.1/oa.2")))
    finally:
        client.__exit__(None, None, None)
    assert refused.status_code == 422 and "waiting_for_pdf" not in counts
    assert list(found) == ["matches"] and [set(m) for m in found["matches"]] == [{"filename", "source_version_id", "basis"}]


def test_links_open_through_the_proxy_once_one_is_set_and_a_bad_address_is_refused(tmp_path, monkeypatch):
    app, client, rid = sw_research(tmp_path, monkeypatch)
    try:
        assert client.get("/api/institution-proxy").json() == {"address": None}
        saved = client.put("/api/institution-proxy", json={"address": PREFIX})
        view = client.get(f"/api/researches/{rid}/waiting").json()
        refused = client.put("/api/institution-proxy", json={"address": "https://reader:pw@proxy.synthetic.edu/?url="})
        kept = client.get("/api/institution-proxy").json()
        cleared = client.put("/api/institution-proxy", json={"address": "  "}).json()
        direct = client.get(f"/api/researches/{rid}/waiting").json()
    finally:
        client.__exit__(None, None, None)
    assert saved.json() == {"address": PREFIX} and view["via_proxy"]
    assert {row["links"]["doi"] for row in view["rows"]} == {f"{PREFIX}https://doi.org/10.1/oa.{n}" for n in (2, 3, 4)}
    assert refused.status_code == 422 and kept == {"address": PREFIX}
    assert cleared == {"address": None} and not direct["via_proxy"]
    assert direct["rows"][0]["links"]["doi"].startswith("https://doi.org/")


# ---- the match -------------------------------------------------------------------------------------------------

def test_a_dropped_file_is_proposed_by_doi_or_title_with_its_work_s_versions_and_nothing_is_attached(tmp_path, monkeypatch):
    app, client, rid = sw_research(tmp_path, monkeypatch)
    try:
        records = records_of(app.state.store, rid)
        title3 = app.state.store.source(records["W3"])["title"]
        found = match(client, rid, ("doi.pdf", named("10.1/oa.2")), ("title.pdf", make_pdf([title3, "SYNTHETIC body."])),
                      ("none.pdf", UNRELATED))
        after = client.get(f"/api/researches/{rid}").json()
    finally:
        client.__exit__(None, None, None)
    by_doi, by_title, none = found["matches"]
    assert (by_doi["basis"], by_doi["source_version_id"]) == ("doi", records["W2"])
    assert by_doi["work"]["versions"] == [dict(by_doi["work"]["versions"][0], source_version_id=records["W2"],
                                               proposed=True, has_pdf=False)]
    assert by_doi["page_count"] == 1 and by_doi["has_text_layer"] is True and len(by_doi["sha256"]) == 64
    assert found["scope_revision"] == 1
    assert (by_title["basis"], by_title["source_version_id"]) == ("title", records["W3"])
    assert (none["basis"], none["source_version_id"], none["work"]) == (None, None, None)
    # Nothing proposed: every work a file may go to comes back, the listed ones and the plan's, with its versions.
    assert {w["head"] for w in none["candidates"]} >= {records["W1"], records["W2"], records["W3"], records["W4"]}
    assert all(w["versions"] and w["versions_digest"] for w in none["candidates"])
    assert "candidates" not in by_doi
    assert after["counts"]["waiting_for_pdf"] == 3
    assert not any(s["access"]["assets"] for s in after["sources"] if s["source_version_id"] != records["W1"])


def test_a_first_page_naming_two_candidate_works_lets_the_title_decide(tmp_path, monkeypatch):
    app, client, rid = sw_research(tmp_path, monkeypatch)
    try:
        records = records_of(app.state.store, rid)
        title4 = app.state.store.source(records["W4"])["title"]
        two = "https://doi.org/10.1/oa.2 and https://doi.org/10.1/oa.4"
        found = match(client, rid, ("titled.pdf", make_pdf([f"{title4}\n{two}"])),
                      ("untitled.pdf", make_pdf([f"SYNTHETIC cover\n{two}"])))
    finally:
        client.__exit__(None, None, None)
    titled, untitled = found["matches"]
    assert (titled["basis"], titled["source_version_id"]) == ("title", records["W4"])
    assert (untitled["basis"], untitled["source_version_id"]) == (None, None)


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
    # 18a writes no code and queues no reading: the work keeps the code the fetch wrote (slice 18b decides).
    assert code == "no_fulltext" and len(after["runs"]) == runs_before
    assert "waiting_pdf_attached" in events


@pytest.mark.parametrize("change, reason", [
    ("file", "file_changed"), ("digest", "versions_changed"), ("revision", "scope_revised"),
    ("removed", "not_a_member"), ("in_use", "pdf_in_use"),
])
def test_a_confirmation_is_refused_with_its_reason_when_what_the_match_showed_moved(tmp_path, monkeypatch, change,
                                                                                     reason):
    app, client, rid = sw_research(tmp_path, monkeypatch)
    try:
        store = app.state.store
        records = records_of(store, rid)
        data = named("10.1/oa.2")
        found = match(client, rid, ("doi.pdf", data))["matches"][0]
        override, sent = {}, data
        if change == "file":
            sent = named("10.1/oa.2", "SYNTHETIC another printing")
        elif change == "digest":
            override = {"versions_digest": "0" * 64}
        elif change == "revision":
            research = client.get(f"/api/researches/{rid}").json()["research"]
            revised = client.post(f"/api/researches/{rid}/scope",
                                  json={"question": research["title"] + " in cold frames", "expected_version": research["version"]})
            assert revised.status_code == 200, revised.text
        elif change == "removed":
            removed = client.request("DELETE", f"/api/researches/{rid}/sources", json={"source_version_ids": [records["W2"]]})
            assert removed.status_code == 200, removed.text
        elif change == "in_use":
            # Between the match and the confirmation another file reaches the same version (here the source list's
            # own upload); the confirmation sent with the earlier match is refused.
            other = named("10.1/oa.2", "SYNTHETIC second copy")
            first = client.post(f"/api/researches/{rid}/sources/{records['W2']}/uploads",
                                files={"file": ("other.pdf", other, "application/pdf")})
            assert first.status_code == 201, first.text
        response = confirm(client, rid, sent, found, records["W2"], **override)
        assets = store.conn.execute("SELECT COUNT(*) FROM source_assets WHERE source_version_id = ?"
                                    " AND removed_at IS NULL", (records["W2"],)).fetchone()[0]
        attached_events = store.conn.execute("SELECT COUNT(*) FROM events WHERE research_id = ?"
                                             " AND type = 'waiting_pdf_attached'", (rid,)).fetchone()[0]
    finally:
        client.__exit__(None, None, None)
    assert response.status_code == 409, response.text
    assert response.json()["detail"]["reason"] == reason
    assert assets == (1 if change == "in_use" else 0) and attached_events == 0


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


def test_the_candidates_are_the_plan_s_works_the_list_and_the_works_included_after_the_plan(store):
    lib = Lib(store, "irrigation")
    planned, waiting_one, before, after, other = (lib.work() for _ in range(5))
    lib.list_edit(before, "included")
    time.sleep(0.01)
    step = write_plan(lib, [planned])
    lib.ds.record(lib.rid, waiting_one, "no_fulltext", step_id=step)  # settled by an earlier plan
    time.sleep(0.01)
    lib.list_edit(after, "included")
    candidates = waiting.candidate_works(store, lib.rid)
    assert set(candidates) == {lib.work_of(svid) for svid in (planned, waiting_one, after)}
    assert lib.work_of(before) not in candidates and lib.work_of(other) not in candidates
    # Included in the plan's own millisecond: the clock cannot say it came first, so it is the person's to choose.
    finished = store.conn.execute("SELECT finished_at FROM run_steps WHERE id = ?", (step,)).fetchone()[0]
    lib.list_edit(other, "included")
    store.conn.execute("UPDATE selections SET updated_at = ? WHERE research_id = ? AND source_version_id = ?",
                       (finished, lib.rid, other))
    assert lib.work_of(other) in waiting.candidate_works(store, lib.rid)


def test_a_version_included_after_the_plan_and_then_removed_does_not_make_its_work_a_candidate(store):
    lib = Lib(store, "channels")
    planned = lib.work()
    published = lib.published("10.9999/synth.gone")
    preprint = lib.preprint("10.9999/synth.gone")
    write_plan(lib, [planned])
    time.sleep(0.01)
    lib.list_edit(preprint, "included")
    assert lib.work_of(preprint) in waiting.candidate_works(store, lib.rid)
    store.remove_sources(lib.rid, [preprint], "SYNTHETIC removal")
    assert store.is_active_member(lib.rid, published)
    assert lib.work_of(published) not in waiting.candidate_works(store, lib.rid)


def test_a_malformed_landing_page_is_left_out_and_the_list_still_reads(store):
    lib = Lib(store, "channels")
    svid = lib.work()
    step = write_plan(lib, [svid])
    store.conn.execute("UPDATE source_versions SET landing_url = 'https://[bad' WHERE id = ?", (svid,))
    lib.ds.record(lib.rid, svid, "no_fulltext", step_id=step)
    row = waiting.waiting_view(store, lib.rid)["rows"][0]
    assert row["links"]["landing"] is None and row["links"]["doi"].startswith("https://doi.org/")


def test_a_work_that_is_not_a_candidate_is_refused_at_the_store(store):
    lib = Lib(store, "channels")
    planned, other = lib.work(), lib.work()
    write_plan(lib, [planned])
    digest = waiting.work_view(store, lib.rid, lib.work_of(other), other)["versions_digest"]
    with pytest.raises(waiting.AttachRefused) as refused:
        waiting.check_attach(store, lib.rid, work_id=lib.work_of(other), source_version_id=other, scope_revision=1,
                             versions_digest=digest, sha256="a" * 64, uploaded_sha256="a" * 64)
    assert refused.value.reason == "not_a_candidate"
    # The plan's own work passes every check.
    good = waiting.work_view(store, lib.rid, lib.work_of(planned), planned)["versions_digest"]
    waiting.check_attach(store, lib.rid, work_id=lib.work_of(planned), source_version_id=planned, scope_revision=1,
                         versions_digest=good, sha256="a" * 64, uploaded_sha256="a" * 64)


def test_a_version_found_after_the_match_changes_the_digest(store):
    lib = Lib(store, "channels")
    published = lib.published("10.9999/synth.pub")
    write_plan(lib, [published])
    work_id = lib.work_of(published)
    before = waiting.work_view(store, lib.rid, work_id, published)
    preprint = lib.preprint("10.9999/synth.pub")  # the preprint joins the published work after the match
    assert lib.work_of(preprint) == work_id and lib.head(preprint) == published
    with pytest.raises(waiting.AttachRefused) as refused:
        waiting.check_attach(store, lib.rid, work_id=work_id, source_version_id=published, scope_revision=1,
                             versions_digest=before["versions_digest"], sha256="a" * 64, uploaded_sha256="a" * 64)
    assert refused.value.reason == "versions_changed"
    now = waiting.work_view(store, lib.rid, work_id, published)
    assert [v["source_version_id"] for v in now["versions"]] == [published, preprint]


def test_the_proposal_marks_the_matched_version_among_the_work_s_versions(store):
    lib = Lib(store, "channels")
    published = lib.published("10.9999/synth.pub")
    preprint = lib.preprint("10.9999/synth.pub")
    write_plan(lib, [published])
    found = waiting.propose(store, lib.rid, f"SYNTHETIC https://doi.org/{store.source(preprint)['doi']} first page")
    assert (found["basis"], found["source_version_id"]) == ("doi", preprint)
    assert {v["source_version_id"]: v["proposed"] for v in found["work"]["versions"]} == {published: False, preprint: True}


def test_a_landing_page_is_offered_only_when_it_is_an_http_page_other_than_the_doi(store):
    lib = Lib(store, "irrigation")
    dup, page, hostile = lib.work(), lib.work(), lib.work()
    step = write_plan(lib, [dup, page, hostile])
    landing = {dup: f"https://doi.org/{store.source(dup)['doi']}", page: "https://publisher.synthetic.org/abs?id=1&v=2",
               hostile: "javascript:alert(1)"}
    for svid, url in landing.items():
        store.conn.execute("UPDATE source_versions SET landing_url = ? WHERE id = ?", (url, svid))
        lib.ds.record(lib.rid, svid, "no_fulltext", step_id=step)
    store.set_setting("institution_proxy", PREFIX)
    rows = {row["head"]: row for row in waiting.waiting_view(store, lib.rid)["rows"]}
    assert [row["head"] for row in rows.values()] == [dup, page, hostile]
    assert rows[dup]["links"]["landing"] is None and rows[hostile]["links"]["landing"] is None
    assert rows[page]["links"]["landing"] == PREFIX + "https%3A%2F%2Fpublisher.synthetic.org%2Fabs%3Fid%3D1%26v%3D2"
    assert rows[hostile]["links"]["doi"] == f"{PREFIX}https://doi.org/{store.source(hostile)['doi']}"
