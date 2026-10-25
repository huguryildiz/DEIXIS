"""An `sw` discovery run that asks a second source for the abstracts it is missing, then labels what it found.

Records, titles and provider answers are SYNTHETIC and from two fields; the transport is mocked and the model is
scripted. Passing shows workflow behavior — who is asked, what is stored, what a resumed run repeats and which
records reach the screening model — not how often a second source really holds a missing abstract, and not that the
survey rule is right about real literature. A `legacy` research is exercised too, because nothing about it may change.
"""

import json
import time
from dataclasses import replace

import httpx
import pytest
from fastapi.testclient import TestClient

from deixis.api.app import create_app
from deixis.config import Settings
from deixis.documents.fetch import FetchResult
from deixis.models.adapter import ModelStepResult
from deixis.workflow.search import lookups
from deixis.providers import common
from deixis.providers.registry import CONNECTORS
from deixis.workflow.screen.decisions import DecisionStore
from fakes import FakeAdapter, envelope, valid_response

QUESTION = "What is the effect of packet size on energy consumption in wireless sensor networks?"
# A second field, so the fixtures are not one topic: the survey title is molecular, the rest is wireless sensing.
SURVEY_TITLE = "SYNTHETIC survey of molecular release scheduling"
PLAIN_TITLE = "SYNTHETIC relay scheduling in a sensor node"
ABSTRACT = "We measure SYNTHETIC packet sizes and report the energy each one costs a relay node."
PAGE = 20


@pytest.fixture(autouse=True)
def no_gate(monkeypatch):
    """Open the Semantic Scholar gate so a test does not wait two seconds for a mocked answer (D67).

    Only the gate: `asyncio.sleep` itself is left alone, because the worker loop runs on it. Every SYNTHETIC 429
    below names `retry-after: 0`, so the bounded backoff costs nothing either.
    """
    monkeypatch.setattr(common.SEMANTIC_SCHOLAR_PACER, "interval_seconds", 0.0)


def DeadAdapter():
    return FakeAdapter(fail=lambda si: ModelStepResult("failed", error="SYNTHETIC model connection is down"))


def excluding(step_input):
    """A scripted model that puts every record it is shown out of scope.

    It is the sharpest test of SW5.5: a record this model never sees cannot be excluded by it, and a record without
    an abstract must never be excluded by anything. Since slice 09 the model's word is a proposal only; the code
    stage turns two agreeing runs into the decision, so the quote is copied from the abstract it was shown.
    """
    if step_input["task_type"] == "abstract_screening":
        return json.dumps(envelope(step_input, "deixis.abstract_screening.v1") | {"records": [
            {"candidate_id": c["candidate_id"], "label": "out_of_scope",
             "quote": " ".join((c["abstract"] or "").split())[:60],
             "rationale": "SYNTHETIC: another setting."} for c in step_input["candidates"]]})
    if step_input["task_type"] != "screening":
        return valid_response(step_input)
    return json.dumps(envelope(step_input, "deixis.screening_proposal.v1") | {
        "decisions": [{"candidate_id": c["candidate_id"], "proposal": "exclude", "reason": "SYNTHETIC exclude",
                       "evidence_basis": "title_and_abstract"} for c in step_input["candidates"]],
        "notes": "SYNTHETIC screening notes.",
    })


def work(number, title=PLAIN_TITLE, abstract=None, doi=None, references=None):
    record = {"id": f"https://openalex.org/W{number}", "doi": f"https://doi.org/{doi or f'10.1/oa.{number}'}",
              "display_name": f"{title} {number}", "publication_year": 2024, "type": "article", "authorships": [],
              "abstract_inverted_index": None}
    if abstract:
        record["abstract_inverted_index"] = {word: [i] for i, word in enumerate(abstract.split())}
    if references is not None:
        record["referenced_works_count"] = references
    return record


class Sources:
    """OpenAlex serving one page of works, Semantic Scholar answering a batch, Crossref answering single DOIs.

    Every request is recorded, so a resumed run can be asked what it sent again. `s2` and `crossref` map a DOI to
    the answer that source gives for it; a DOI neither names is `not_found`.
    """

    def __init__(self, works, s2=None, crossref=None, s2_status=200, crossref_status=200):
        self.works, self.s2, self.crossref = works, s2 or {}, crossref or {}
        self.s2_status, self.crossref_status = s2_status, crossref_status
        self.pages, self.batches, self.lookups, self.probes = [], [], [], []

    def __call__(self, request):
        host = request.url.host
        params = request.url.params
        if host == "api.openalex.org":
            if params.get("per_page") == "1" and params.get("select") == "id":
                self.probes.append(params.get("search.title_and_abstract"))
                return httpx.Response(200, json={"meta": {"count": 8}, "results": []})
            self.pages.append(params.get("select"))
            return httpx.Response(200, json={"meta": {"count": len(self.works), "next_cursor": None},
                                             "results": self.works})
        if host == "api.semanticscholar.org":
            if not request.url.path.endswith("/batch"):
                return httpx.Response(200, json={"total": 0, "data": []})  # every record here comes from OpenAlex
            ids = json.loads(request.content)["ids"]
            self.batches.append(ids)
            if self.s2_status != 200:
                return httpx.Response(self.s2_status, text="SYNTHETIC rate limit", headers={"retry-after": "0"})
            return httpx.Response(200, json=[self.s2.get(_doi_of(paper_id)) for paper_id in ids])
        if host == "api.crossref.org":
            if "rows" in params:
                return httpx.Response(200, json={"message": {"total-results": 0, "items": []}})
            doi = request.url.raw_path.decode().split("?")[0][len("/works/"):].replace("%2F", "/").lower()
            self.lookups.append(doi)
            if self.crossref_status != 200:
                return httpx.Response(self.crossref_status, text="SYNTHETIC outage", headers={"retry-after": "0"})
            if doi not in self.crossref:
                return httpx.Response(404, text="Resource not found.")
            return httpx.Response(200, json={"status": "ok", "message": {"DOI": doi, **self.crossref[doi]}})
        return httpx.Response(404)


def _doi_of(paper_id):
    return paper_id.split(":", 1)[1].lower()


def paper(abstract=None, doi=None, references=None, paper_id="s2abc"):
    return {"paperId": paper_id, "externalIds": {"DOI": doi} if doi else {}, "abstract": abstract,
            "referenceCount": references}


async def no_fetch(url):
    return FetchResult("http_error", final_url=url, http_status=404)


def app_for(tmp_path, monkeypatch, handler, workflow="sw", adapter=None):
    for connector in CONNECTORS.values():
        if connector.key_env:
            monkeypatch.delenv(connector.key_env, raising=False)
    monkeypatch.setitem(CONNECTORS, "openalex", replace(CONNECTORS["openalex"], max_results=PAGE))
    monkeypatch.setenv("DEIXIS_SEARCH_WORKFLOW", workflow)
    return create_app(Settings(data_dir=tmp_path / "data", port=8765, search_query="code",
                               fulltext_fetch="off"),
                      adapters={"fake": adapter or DeadAdapter()},
                      http_client=httpx.AsyncClient(transport=httpx.MockTransport(handler)), fetcher=no_fetch,
                      extra_hosts=("testserver",), trusted_clients=("testclient",))


def wait(client, rid, run_id):
    deadline = time.time() + 30
    while time.time() < deadline:
        view = client.get(f"/api/researches/{rid}").json()
        run = next(r for r in view["runs"] if r["id"] == run_id)
        if run["status"] in ("completed", "failed", "paused"):
            return view, run
        time.sleep(0.05)
    raise AssertionError("the run did not settle")


def client_of(app):
    client = TestClient(app)
    client.__enter__()
    client.headers["x-deixis-csrf"] = client.get("/api/session").json()["csrf_token"]
    return client


def discover(client, question=QUESTION, **body):
    payload = {"question": question, "model_connection": "fake", "requested_model": "fake-model", "effort": "quick",
               "providers": ["openalex", "semantic_scholar", "crossref"], **body}
    rid = client.post("/api/researches", json=payload).json()["research"]["id"]
    run_id = client.post(f"/api/researches/{rid}/runs", json={"kind": "discovery"}).json()["id"]
    return rid, run_id, *wait(client, rid, run_id)


def step_output(store, run_id, key):
    row = store.conn.execute("SELECT output_json FROM run_steps WHERE run_id = ? AND operation_key = ?",
                             (run_id, key)).fetchone()
    return None if row is None or row[0] is None else json.loads(row[0])


def records_of(store, rid):
    """Every candidate of the research by its OpenAlex identifier."""
    return {row[1]: row[0] for row in store.conn.execute(
        "SELECT m.source_version_id, m.value FROM identifier_mappings m JOIN candidates c"
        " ON c.source_version_id = m.source_version_id WHERE c.research_id = ? AND m.scheme = 'openalex'", (rid,))}


def abstract_of(store, svid):
    row = store.conn.execute(
        "SELECT text, abstract_origin, payload_ref FROM passages WHERE source_version_id = ? AND kind = 'abstract'",
        (svid,)).fetchone()
    return None if row is None else dict(row)


def decision_of(store, rid, svid):
    return DecisionStore(store).current(rid, svid, "abstract")


def selection_of(store, rid, svid):
    row = store.conn.execute("SELECT state, origin, version FROM selections WHERE research_id = ?"
                             " AND source_version_id = ?", (rid, svid)).fetchone()
    return None if row is None else dict(row)


# ---- what a second source fills ------------------------------------------------------------


def test_semantic_scholar_fills_one_abstract_and_crossref_the_one_it_did_not(tmp_path, monkeypatch):
    """Acceptance 1: each filled abstract carries the origin of the source that gave it, and its payload file."""
    sources = Sources(
        works=[work(1, doi="10.1/a"), work(2, doi="10.1/b")],
        s2={"10.1/a": paper(abstract=ABSTRACT, doi="10.1/a"), "10.1/b": paper(doi="10.1/b")},
        crossref={"10.1/b": {"abstract": "<jats:p>We measure SYNTHETIC relay energy.</jats:p>"}})
    app = app_for(tmp_path, monkeypatch, sources)
    client = client_of(app)
    try:
        rid, run_id, view, run = discover(client)
        store = app.state.store
        by_id = records_of(store, rid)
        first, second = abstract_of(store, by_id["W1"]), abstract_of(store, by_id["W2"])
        s2_step = step_output(store, run_id, "record_lookup:semantic_scholar:0")
        cr_step = step_output(store, run_id, "record_lookup:crossref:0")
        payloads = {path.name for path in (tmp_path / "data" / "provider-payloads").glob("*.json")}
    finally:
        client.__exit__(None, None, None)
    assert first["text"] == ABSTRACT and first["abstract_origin"] == "lookup_semantic_scholar"
    assert second["text"] == "We measure SYNTHETIC relay energy." and second["abstract_origin"] == "lookup_crossref_jats"
    assert first["payload_ref"] in payloads and second["payload_ref"] in payloads
    assert (s2_step["asked"], s2_step["abstracts_filled"]) == (2, 1)
    assert (cr_step["asked"], cr_step["abstracts_filled"]) == (1, 1)
    assert sources.lookups == ["10.1/b"]  # the record Semantic Scholar answered is not asked again


def test_a_resumed_run_asks_no_doi_twice(tmp_path, monkeypatch):
    """Acceptance 3: the stored plan and the stored answers together keep every request to one.

    One record carries an abstract, so the run reaches the screening model and pauses there; without it every
    record would be held and the run would finish with nothing to resume.
    """
    sources = Sources(works=[work(0, abstract=ABSTRACT, doi="10.1/0")]
                      + [work(i, doi=f"10.1/{i}") for i in range(1, 4)])
    app = app_for(tmp_path, monkeypatch, sources)
    client = client_of(app)
    try:
        rid, run_id, view, run = discover(client)
        assert run["status"] == "paused"
        asked_batches, asked_lookups = list(sources.batches), list(sources.lookups)
        client.post(f"/api/runs/{run_id}/resume")
        view, run = wait(client, rid, run_id)
    finally:
        client.__exit__(None, None, None)
    assert sources.batches == asked_batches and sources.lookups == asked_lookups
    assert len(asked_lookups) == 3


# ---- the flags and what they route ------------------------------------------------------------


# ---- slice 13g Task 4: Scopus is the last abstract source, on an institutional network only (D91) ---------------


