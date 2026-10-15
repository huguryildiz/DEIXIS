"""The citation map's reading run (slice 2): OpenAlex only through a mocked transport, no model call. SYNTHETIC works;
passing shows the run's bookkeeping (resolution, lists, quota, resume), not OpenAlex coverage."""

import asyncio
import json

import httpx
import pytest
from fastapi.testclient import TestClient

from deixis.api.app import create_app
from deixis.config import Settings
from deixis.domain import skill
from deixis.domain.rules import RevisionConflict
from deixis.providers.common import ProviderRecord
from deixis.storage import db
from deixis.workflow import citation_map, citation_map_run
from deixis.workflow.flow import FlowDeps, ResearchFlow
from deixis.workflow.store import Store
from deixis.workflow.worker import Worker
from fakes import FakeAdapter
from test_api_flow import fake_fetch, session, sw_settings

QUOTA = {"x-ratelimit-remaining-usd": "0", "x-ratelimit-reset": "3600"}


class OpenAlex:
    """A mocked /works endpoint: `filter=openalex:W1|W2` or `filter=doi:a|b`, answered from `works`."""

    def __init__(self):
        self.works: dict[str, dict] = {}
        self.requests: list[tuple[str, list[str]]] = []
        self.quota: set[str] = set()  # request kinds ("openalex", "doi") answered with a spent daily budget
        self.on_request = None

    def work(self, oid, refs=None, doi=None, title=None, **extra):
        body = {"id": f"https://openalex.org/{oid}", "display_name": title or f"SYNTHETIC work {oid}",
                "publication_year": 2020, "doi": f"https://doi.org/{doi}" if doi else None,
                "authorships": [{"author": {"display_name": "Ada Lovelace"}}]} | extra
        if refs is not None:
            body["referenced_works"] = [f"https://openalex.org/{r}" for r in refs]
        self.works[oid] = body

    def handler(self, request):
        kind, _, values = request.url.params["filter"].partition(":")
        values = values.split("|")
        self.requests.append((kind, values))
        if self.on_request:
            self.on_request(kind, values)
        if kind in self.quota:
            return httpx.Response(429, headers=QUOTA, json={"error": "daily budget"})
        if kind == "openalex":
            found = [self.works[v] for v in values if v in self.works]
        else:
            found = [w for w in self.works.values() if w["doi"] and w["doi"].removeprefix("https://doi.org/") in values]
        return httpx.Response(200, json={"meta": {"count": len(found)}, "results": found})

    def sent(self, kind):
        return [values for k, values in self.requests if k == kind]


@pytest.fixture
def lib(tmp_path):
    conn = db.connect(tmp_path / "library.sqlite")
    db.migrate(conn)
    store = Store(conn)
    rid = store.create_research("SYNTHETIC citation question?", "attached", "quick", [], "fake", "fake-model", "en")
    api = OpenAlex()
    http = httpx.AsyncClient(transport=httpx.MockTransport(api.handler))
    adapter = FakeAdapter()
    flow = ResearchFlow(FlowDeps(Settings(data_dir=tmp_path / "data", port=8872), store, {"fake": adapter},
                                 skill.load_skill_package(), http))
    env = type("Env", (), {})()
    env.__dict__.update(conn=conn, store=store, rid=rid, api=api, http=http, adapter=adapter, flow=flow,
                        worker=Worker(store, flow, tmp_path / "unused.lock"))
    yield env
    assert adapter.calls == []  # the run never asks a model
    asyncio.run(http.aclose())
    conn.close()


def record(oid, refs=None, doi=None):
    return ProviderRecord(provider_record_id=oid, title=f"SYNTHETIC work {oid}", authors=["Ada Lovelace"], year=2020,
                          venue="Synthetic venue", publication_type="article", doi=doi, landing_url=None, oa_pdf_url=None,
                          oa_pdf_version=None, version_label=None, abstract=None, abstract_origin=None,
                          identifiers={"openalex": oid}, raw={}, references=None if refs is None else tuple(refs))


def provider(lib, oid, refs=None):
    svid, _ = lib.store.upsert_provider_source("openalex", record(oid, refs), None)
    lib.store.add_to_corpus(lib.rid, svid, "search", selection_state="pending", selection_origin="user")
    return svid


def upload(lib, title, doi=None, match=None):
    svid = lib.store.create_upload_source(title)
    lib.store.add_to_corpus(lib.rid, svid, "user_upload", selection_state="included", selection_origin="user")
    lib.conn.execute("UPDATE source_versions SET doi = ?, record_match_json = ? WHERE id = ?",
                     (doi, json.dumps({"provider": "openalex", "work_id": match, "basis": "doi_title"}) if match else None, svid))
    return svid


def refs(lib, svid):
    read = lib.conn.execute("SELECT references_read FROM source_versions WHERE id = ?", (svid,)).fetchone()[0]
    return bool(read), {r[0] for r in lib.conn.execute(
        "SELECT referenced_id FROM record_references WHERE source_version_id = ?", (svid,))}


def queue(lib):
    run = citation_map_run.request_run(lib.store, lib.rid)
    lib.store.update_run(run["id"], status="running")
    return run


def execute(lib, run):
    asyncio.run(lib.flow.execute(run["id"]))
    return lib.store.run(run["id"])


def resume(lib, run):
    lib.store.update_run(run["id"], status="running", pause_reason=None)
    return execute(lib, run)


def mixed(lib):
    """An identified upload, an upload with a DOI only, an upload with neither, and two provider sources."""
    a = upload(lib, "SYNTHETIC identified upload", doi="10.1/a", match="W10")
    b = upload(lib, "SYNTHETIC upload with a DOI", doi="10.1/b")
    c = upload(lib, "SYNTHETIC upload without DOI")
    d = provider(lib, "W20")
    e = provider(lib, "W30", refs=["W99"])
    lib.api.work("W10", refs=["W50", "W51"], doi="10.1/a")
    lib.api.work("W11", refs=["W50"], doi="10.1/b")
    lib.api.work("W20", refs=["W50", "W10"])
    lib.api.work("W50", refs=[], title="SYNTHETIC often cited work")
    return a, b, c, d, e


def test_prepare_counts_without_a_request(lib):
    mixed(lib)
    assert citation_map_run.prepare(lib.store, lib.rid) == {
        "works_to_resolve": 2, "sources_to_read": 2, "outside_to_describe": 0, "requests": 3,
        "unresolvable_without_doi": 1}
    assert lib.api.requests == []


def test_the_worker_runs_it_to_completion_and_the_map_shows_the_result(lib):
    a, b, c, d, _ = mixed(lib)
    memberships = lib.conn.execute("SELECT COUNT(*) FROM corpus_memberships").fetchone()[0]
    run = citation_map_run.request_run(lib.store, lib.rid)
    assert run["kind"] == "citation_map" and run["status"] == "queued"
    asyncio.run(lib.worker._turn())
    run = lib.store.run(run["id"])
    assert run["status"] == "completed", run
    assert [k for k, _ in lib.api.requests] == ["doi", "openalex", "openalex"]
    assert lib.api.sent("doi") == [["10.1/b"]] and lib.api.sent("openalex") == [["W10", "W20"], ["W50"]]
    resolutions = {r["source_version_id"]: (r["method"], r["status"], r["openalex_id"]) for r in lib.conn.execute(
        "SELECT * FROM citation_map_resolutions")}
    assert resolutions == {a: ("record_match", "resolved", "W10"), b: ("doi", "resolved", "W11")}
    assert refs(lib, a) == (True, {"W50", "W51"}) and refs(lib, b) == (True, {"W50"})
    assert refs(lib, d) == (True, {"W50", "W10"}) and refs(lib, c) == (False, set())
    m = citation_map.build(lib.store, lib.rid)
    work = {n["source_version_id"]: n["work_id"] for n in m["nodes"]}
    assert {"from": work[d], "to": work[a]} in m["edges"]
    [w50] = [o for o in m["outside"] if o["openalex_id"] == "W50"]
    assert w50["title"] == "SYNTHETIC often cited work" and w50["in_count"] == 3
    # The outside work is stored, and joins no research.
    assert lib.conn.execute("SELECT COUNT(*) FROM corpus_memberships").fetchone()[0] == memberships
    assert len(m["nodes"]) == 5 and m["counts"]["no_openalex_id"] == 1
    assert run["usage"]["provider_sends"] == 3
    assert lib.store.provider_request_counts(run["id"]) == {"api.openalex.org": {"sent": 3, "refused": 0, "unknown": 0}}
    # Everything is read now: a second request finds nothing to do and sends nothing.
    with pytest.raises(RevisionConflict, match="Nothing is missing"):
        citation_map_run.request_run(lib.store, lib.rid)
    assert len(lib.api.requests) == 3


def test_a_doi_resolution_leaves_identity_and_dedupe_alone(lib):
    b = upload(lib, "SYNTHETIC upload with a DOI", doi="10.1/b")
    lib.api.work("W11", refs=["W50"], doi="10.1/b")
    assert execute(lib, queue(lib))["status"] == "completed"
    assert lib.conn.execute("SELECT 1 FROM identifier_mappings WHERE source_version_id = ?", (b,)).fetchone() is None
    assert lib.store.find_source_by_identifier("openalex", "W11") is None
    # A later search hit of the same OpenAlex work keeps its own source version, as D37 has it.
    hit, created = lib.store.upsert_provider_source("openalex", record("W11", refs=["W50"], doi="10.1/b"), None)
    assert created and hit != b


def test_a_doi_naming_two_works_or_none_resolves_nothing_and_is_not_asked_again(lib):
    two = upload(lib, "SYNTHETIC preprint and article", doi="10.1/two")
    none = upload(lib, "SYNTHETIC unknown DOI", doi="10.1/none")
    lib.api.work("W60", refs=[], doi="10.1/two")
    lib.api.work("W61", refs=[], doi="10.1/two")
    assert execute(lib, queue(lib))["status"] == "completed"
    status = {r[0]: r[1] for r in lib.conn.execute("SELECT source_version_id, status FROM citation_map_resolutions")}
    assert status == {two: "ambiguous", none: "not_found"}
    assert refs(lib, two) == (False, set())
    assert citation_map_run.prepare(lib.store, lib.rid)["requests"] == 0


def test_more_than_a_hundred_ids_are_split_and_a_bad_list_stays_unread(lib):
    ids = [f"W{1000 + i}" for i in range(150)]
    svids = {oid: provider(lib, oid) for oid in ids}
    for oid in ids[3:]:
        lib.api.work(oid, refs=[])
    lib.api.work("W1000")                                # no referenced_works field
    lib.api.work("W1001", referenced_works="SYNTHETIC")  # malformed
    # W1002 is not answered at all
    assert citation_map_run.prepare(lib.store, lib.rid)["requests"] == 3
    assert execute(lib, queue(lib))["status"] == "completed"
    assert [len(values) for values in lib.api.sent("openalex")] == [100, 50]
    for oid in ("W1000", "W1001", "W1002"):
        assert refs(lib, svids[oid]) == (False, set())
    assert all(refs(lib, svids[oid])[0] for oid in ids[3:])


def test_a_spent_budget_stops_the_run_and_keeps_what_was_stored(lib):
    b = upload(lib, "SYNTHETIC upload with a DOI", doi="10.1/b")
    d = provider(lib, "W20")
    lib.api.work("W11", refs=["W50"], doi="10.1/b")
    lib.api.work("W20", refs=["W50"])
    lib.api.quota.add("openalex")
    run = execute(lib, queue(lib))
    assert (run["status"], run["pause_reason"]) == ("paused", "openalex_budget_exhausted")
    assert refs(lib, b) == (True, {"W50"}) and refs(lib, d) == (False, set())
    budget = lib.conn.execute("SELECT refused, skipped FROM openalex_budget_runs WHERE run_id = ?", (run["id"],)).fetchone()
    assert tuple(budget) == (1, 0)
    events = [r[0] for r in lib.conn.execute("SELECT type FROM events WHERE run_id = ? ORDER BY id", (run["id"],))]
    assert "openalex_budget_exhausted" in events and events[-1] == "run_paused"
    # Resumed while the budget is still spent: nothing is sent, the run pauses again.
    sent = len(lib.api.requests)
    run = resume(lib, run)
    assert (run["status"], run["pause_reason"], len(lib.api.requests)) == ("paused", "openalex_budget_exhausted", sent)


def test_a_spent_budget_in_the_metadata_step_keeps_the_lists_and_resumes(lib):
    d = provider(lib, "W20")
    e = provider(lib, "W30")
    lib.api.work("W20", refs=["W50"])
    lib.api.work("W30", refs=["W50"])
    lib.api.work("W50", refs=[], title="SYNTHETIC often cited work")

    def spend(kind, values):
        if values == ["W50"]:
            lib.api.quota.add("openalex")
    lib.api.on_request = spend
    run = execute(lib, queue(lib))
    assert (run["status"], run["pause_reason"]) == ("paused", "openalex_budget_exhausted")
    assert refs(lib, d) == (True, {"W50"}) and refs(lib, e) == (True, {"W50"})
    assert citation_map.build(lib.store, lib.rid)["outside"][0]["title"] is None
    # The day's budget returns; the resumed run asks only for the metadata.
    lib.api.quota.clear()
    lib.api.on_request = None
    lib.conn.execute("UPDATE openalex_budget_runs SET reset_at = '2000-01-01T00:00:00+00:00'")
    lib.flow._openalex_budget.pop(run["id"], None)
    assert resume(lib, run)["status"] == "completed"
    assert lib.api.sent("openalex") == [["W20", "W30"], ["W50"], ["W50"]]
    assert citation_map.build(lib.store, lib.rid)["outside"][0]["title"] == "SYNTHETIC often cited work"


def test_pause_and_resume_do_not_repeat_a_succeeded_request(lib):
    upload(lib, "SYNTHETIC upload with a DOI", doi="10.1/b")
    provider(lib, "W20")
    lib.api.work("W11", refs=["W50"], doi="10.1/b")
    lib.api.work("W20", refs=["W50"])
    run = queue(lib)

    def pause(kind, values):
        if kind == "doi":
            lib.store.update_run(run["id"], event="run_pause_requested", status="pause_requested", pause_reason="user_requested")
    lib.api.on_request = pause
    run = execute(lib, run)
    assert (run["status"], run["pause_reason"]) == ("paused", "user_requested")
    assert lib.api.sent("doi") == [["10.1/b"]] and lib.api.sent("openalex") == []
    lib.api.on_request = None
    assert resume(lib, run)["status"] == "completed"
    assert lib.api.sent("doi") == [["10.1/b"]]  # sent once
    assert lib.api.sent("openalex")[0] == ["W20"]


def test_two_versions_of_one_work_keep_their_own_lists(lib):
    head = provider(lib, "W1")
    other, _ = lib.store.upsert_provider_source("openalex", record("W1b"), None)
    lib.conn.execute("UPDATE source_versions SET work_id = (SELECT work_id FROM source_versions WHERE id = ?) WHERE id = ?",
                     (head, other))
    lib.store.add_to_corpus(lib.rid, other, "search", candidate=False)
    lib.api.work("W1", refs=["W50"])
    lib.api.work("W1b", refs=["W60"])
    assert execute(lib, queue(lib))["status"] == "completed"
    assert refs(lib, head) == (True, {"W50"}) and refs(lib, other) == (True, {"W60"})


def test_a_queued_run_is_returned_again_and_a_paused_one_must_be_resumed(lib):
    provider(lib, "W20")
    first = citation_map_run.request_run(lib.store, lib.rid)
    assert citation_map_run.request_run(lib.store, lib.rid)["id"] == first["id"]
    lib.store.update_run(first["id"], status="paused", pause_reason="user_requested")
    with pytest.raises(RevisionConflict, match="Resume or cancel"):
        citation_map_run.request_run(lib.store, lib.rid)


def test_the_routes(tmp_path):
    api = OpenAlex()
    app = create_app(sw_settings(tmp_path), adapters={"fake": FakeAdapter()},
                     http_client=httpx.AsyncClient(transport=httpx.MockTransport(api.handler)), fetcher=fake_fetch,
                     extra_hosts=("testserver",), trusted_clients=("testclient",), start_worker=False)
    with TestClient(app) as client:
        assert client.post("/api/researches/res_missing/citation-map/prepare").status_code == 403  # no CSRF token
        session(client)
        rid = client.post("/api/researches", json={"question": "SYNTHETIC citation question?", "model_connection": "fake",
                                                   "requested_model": "fake-model", "effort": "quick"}).json()["research"]["id"]
        for run in app.state.store.conn.execute("SELECT id FROM runs WHERE research_id = ?", (rid,)).fetchall():
            app.state.store.update_run(run[0], status="cancelled")
        assert client.post("/api/researches/res_missing/citation-map/prepare").status_code == 404
        assert client.post(f"/api/researches/{rid}/citation-map/run").status_code == 409  # nothing to fill
        svid, _ = app.state.store.upsert_provider_source("openalex", record("W20"), None)
        app.state.store.add_to_corpus(rid, svid, "search", selection_state="pending", selection_origin="user")
        prepared = client.post(f"/api/researches/{rid}/citation-map/prepare")
        assert prepared.status_code == 200 and prepared.json()["requests"] == 2 and prepared.json()["sources_to_read"] == 1
        first = client.post(f"/api/researches/{rid}/citation-map/run")
        assert first.status_code == 202 and first.json()["kind"] == "citation_map"
        assert client.post(f"/api/researches/{rid}/citation-map/run").json()["id"] == first.json()["id"]
        assert api.requests == []


def test_a_list_with_a_malformed_entry_stays_unread_on_both_paths(lib):
    by_id = provider(lib, "W40")
    by_doi = upload(lib, "SYNTHETIC upload with a DOI", doi="10.1/c")
    empty = provider(lib, "W41")
    lib.api.work("W40", referenced_works=["https://openalex.org/W50", None, {}, "garbage"])
    lib.api.work("W42", referenced_works=["W50", "garbage"], doi="10.1/c")
    lib.api.work("W41", refs=[])
    assert execute(lib, queue(lib))["status"] == "completed"
    assert refs(lib, by_id) == (False, set()) and refs(lib, by_doi) == (False, set())
    assert refs(lib, empty) == (True, set())  # a valid empty list is read


def test_a_cancel_during_the_request_survives_a_budget_answer(lib, monkeypatch):
    svid = provider(lib, "W40")
    run = queue(lib)
    real = citation_map_run._budget_stop

    def cancelled_first(flow, run_, step, reset_at, *, skipped):
        lib.store.update_run(run_["id"], event="run_cancelled", status="cancelled", pause_reason="user_cancelled")
        real(flow, run_, step, reset_at, skipped=skipped)

    monkeypatch.setattr(citation_map_run, "_budget_stop", cancelled_first)
    lib.api.quota.add("openalex")
    assert execute(lib, run)["status"] == "cancelled"
    assert refs(lib, svid) == (False, set())


def test_an_outside_work_openalex_does_not_return_is_not_asked_again(lib):
    provider(lib, "W40", refs=["W77", "W78"])
    provider(lib, "W41", refs=["W77", "W78"])
    lib.api.work("W78", refs=[], title="SYNTHETIC described work")  # W77 is unknown to OpenAlex
    assert citation_map_run.prepare(lib.store, lib.rid)["outside_to_describe"] == 2
    assert execute(lib, queue(lib))["status"] == "completed"
    after = citation_map_run.prepare(lib.store, lib.rid)
    assert after["outside_to_describe"] == 0 and after["requests"] == 0
    sent = len(lib.api.sent("openalex"))
    with pytest.raises(RevisionConflict):
        citation_map_run.request_run(lib.store, lib.rid)  # nothing left to fill
    assert len(lib.api.sent("openalex")) == sent


def test_an_answer_without_a_count_is_asked_again(lib):
    provider(lib, "W40", refs=["W77"])
    provider(lib, "W41", refs=["W77"])
    lib.api.on_request = None
    real = lib.api.handler

    def no_meta(request):
        response = real(request)
        if request.url.params["filter"].startswith("openalex:W77"):
            return httpx.Response(200, json={"results": []})
        return response

    lib.http._transport = httpx.MockTransport(no_meta)
    assert execute(lib, queue(lib))["status"] == "completed"
    assert citation_map_run.prepare(lib.store, lib.rid)["outside_to_describe"] == 1


def test_an_empty_answer_in_one_research_does_not_skip_the_work_in_another(lib):
    provider(lib, "W40", refs=["W77"])
    provider(lib, "W41", refs=["W77"])
    assert execute(lib, queue(lib))["status"] == "completed"
    other = lib.store.create_research("SYNTHETIC second question?", "attached", "quick", [], "fake", "fake-model", "en")
    for oid in ("W40", "W41"):
        svid = lib.store.find_source_by_identifier("openalex", oid)
        lib.store.add_to_corpus(other, svid, "library", selection_state="pending", selection_origin="user")
    assert citation_map_run.prepare(lib.store, other)["outside_to_describe"] == 1
