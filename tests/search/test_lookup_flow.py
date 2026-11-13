"""An `sw` discovery run that asks a second source for the abstracts it is missing, then labels what it found.

Records, titles and provider answers are SYNTHETIC and from two fields; the transport is mocked and the model is
scripted. Passing shows workflow behavior — who is asked, what is stored, what a resumed run repeats and which
records reach the screening model — not how often a second source really holds a missing abstract, and not that the
survey rule is right about real literature. A `legacy` research is exercised too, because nothing about it may change.
"""

import asyncio
import json
import time
from dataclasses import replace

import httpx
import pytest
from fastapi.testclient import TestClient

from deixis.api.app import create_app
from deixis.runtime.config import Settings
from deixis.documents.fetch import FetchResult
from deixis.workflow.search import lookups
from deixis.providers import common
from deixis.providers.registry import CONNECTORS
from deixis.workflow.screen.decisions import DecisionStore
from fakes import FakeAdapter, PlanOnlyAdapter, envelope, valid_response
from windows_env import WAIT_FACTOR

QUESTION = "What is the effect of packet size on energy consumption in wireless sensor networks?"
# A second field, so the fixtures are not one topic: the survey title is molecular, the rest is wireless sensing.
SURVEY_TITLE = "SYNTHETIC survey of molecular release scheduling"
PLAIN_TITLE = "SYNTHETIC relay scheduling in a sensor node"
ABSTRACT = "We measure SYNTHETIC packet sizes and report the energy each one costs a relay node."
PAGE = 20


@pytest.fixture(autouse=True)
def no_gate(monkeypatch):
    """Open the Semantic Scholar gate so a test does not wait two seconds for a mocked answer.

    Only the gate: `asyncio.sleep` itself is left alone, because the worker loop runs on it. Every SYNTHETIC 429
    below names `retry-after: 0`, so the bounded backoff costs nothing either.
    """
    monkeypatch.setattr(common.SEMANTIC_SCHOLAR_PACER, "interval_seconds", 0.0)



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
                self.probes.append(params.get("search.title_abstract_keywords"))
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
    return create_app(Settings(data_dir=tmp_path / "data", port=8765,
                               fulltext_fetch="off"),
                      adapters={"fake": adapter or PlanOnlyAdapter()},
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


def test_a_batch_skipped_in_the_cooldown_leaves_its_records_as_a_refused_batch_does(tmp_path, monkeypatch):
    """During a Semantic Scholar 429 cooldown the read stage's lookup sends it nothing; its records are stored
    `failed`, as after a refused batch. With the shared retry allowance, Quick leaves them as `no_abstract` for a
    later lookup. The step says why and for how many."""
    sources = Sources(works=[work(1, doi="10.1/a"), work(2, doi="10.1/b")],
                      s2={"10.1/a": paper(abstract=ABSTRACT, doi="10.1/a")})
    monkeypatch.delattr(common.SEMANTIC_SCHOLAR_PACER, "cool_down")  # the real cooldown, off elsewhere in the suite
    common.SEMANTIC_SCHOLAR_PACER.cool_down(60)
    app = app_for(tmp_path, monkeypatch, sources)
    client = client_of(app)
    try:
        rid, run_id, view, run = discover(client)
        store = app.state.store
        by_id = records_of(store, rid)
        s2_step = step_output(store, run_id, "record_lookup:semantic_scholar:0")
        rows = {r[0]: r[1] for r in store.conn.execute(
            "SELECT source_version_id, status FROM record_lookups WHERE provider = 'semantic_scholar'")}
        codes = {n: decision_of(store, rid, by_id[n])["reason_code"] for n in ("W1", "W2")}
        event = next(json.loads(e[0]) for e in store.conn.execute(
            "SELECT payload_json FROM events WHERE run_id = ? AND type = 'step_finished'", (run_id,))
            if json.loads(e[0])["operation_key"] == "record_lookup:semantic_scholar:0")
    finally:
        client.__exit__(None, None, None)
    assert run["status"] == "completed" and sources.batches == []  # nothing reached Semantic Scholar
    assert (s2_step["skipped"], s2_step["not_asked"], s2_step["failed"]) == ("s2_cooldown", 2, 2)
    assert rows == {by_id["W1"]: "failed", by_id["W2"]: "failed"}
    assert sorted(sources.lookups) == ["10.1/a", "10.1/b"]  # Crossref was asked about both
    assert codes == {"W1": "no_abstract", "W2": "no_abstract"}
    assert (event["skipped"], event["skipped_count"]) == ("s2_cooldown", 2)


def test_a_resumed_run_asks_no_doi_twice(tmp_path, monkeypatch):
    """Acceptance 3: the stored plan and the stored answers together keep every request to one.

    One record carries an abstract, so the run reaches the screening model and pauses there; without it every
    record would be held and the run would finish with nothing to resume.
    """
    from fakes import without_evidence_minimum
    # A failed abstract read pauses only a run frozen before the evidence minimum, which is the pause this test uses.
    without_evidence_minimum(monkeypatch)
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


@pytest.mark.parametrize("in_flight", [1, 4])
def test_a_crossref_chunk_stopped_between_two_answers_keeps_the_first_answer_s_evidence(tmp_path, monkeypatch, in_flight):
    """The worker stops after Crossref answered one record of a chunk and before the other; the resumed
    chunk asks only the other, and the first stored abstract's payload file still holds its own answer (one after
    another as at the read stage and before that change, and 4 in flight as before the rerank)."""
    crossref = {"10.1/7": {"abstract": "<jats:p>SYNTHETIC seven.</jats:p>"},
                "10.1/8": {"abstract": "<jats:p>SYNTHETIC eight.</jats:p>"}}
    sources = Sources(works=[work(0, abstract=ABSTRACT, doi="10.1/0"), work(7, doi="10.1/7"), work(8, doi="10.1/8")],
                      crossref=crossref, crossref_status=500)
    app = app_for(tmp_path, monkeypatch, sources)
    client = client_of(app)
    rid, run_id, _, _ = discover(client)  # Crossref fails for the run itself, so both records are still to ask
    store, settings = app.state.store, app.state.settings
    sources.crossref_status, sources.lookups = 200, []
    by_id = records_of(store, rid)
    chunk = [{"source_version_id": by_id[f"W{n}"], "doi": f"10.1/{n}"} for n in (7, 8)]
    dispatch = lookups.facade.dispatch_lookup
    stopped = []

    async def stopping(provider, operation, http, dois, *args, **kwargs):
        if dois == ("10.1/8",) and not stopped:
            await asyncio.sleep(0.05)  # the other answer is in by then
            stopped.append(True)
            raise RuntimeError("SYNTHETIC worker stopped")
        return await dispatch(provider, operation, http, dois, *args, **kwargs)
    monkeypatch.setattr(lookups.facade, "dispatch_lookup", stopping)


    async def chunk_step():
        async with httpx.AsyncClient(transport=httpx.MockTransport(sources)) as http:
            await lookups._crossref_step(store, http, settings, store.run(run_id), 0, chunk, "test:", in_flight)
    try:
        with pytest.raises(RuntimeError, match="SYNTHETIC worker stopped"):
            asyncio.run(chunk_step())
        asyncio.run(chunk_step())  # the resume
        stored = {n: abstract_of(store, by_id[f"W{n}"]) for n in (7, 8)}
    finally:
        client.__exit__(None, None, None)
    assert sources.lookups == ["10.1/7", "10.1/8"]  # each record was asked once
    for n, word in ((7, "seven"), (8, "eight")):
        payload = json.loads((settings.payloads_dir / stored[n]["payload_ref"]).read_text(encoding="utf-8"))
        assert stored[n]["text"] == f"SYNTHETIC {word}."
        assert payload[f"10.1/{n}"]["abstract"] == crossref[f"10.1/{n}"]["abstract"]


@pytest.mark.parametrize("how", ["deadline", "pause", "before_the_rule"])
def test_a_stop_inside_a_crossref_chunk_sends_no_further_request(tmp_path, monkeypatch, how):
    """Under the evidence minimum the read stage's deadline, or a pause, that arrives after the first reply of a
    chunk stops the chunk there: the other records are not asked and the step is closed as stopped (a pause leaves it
    open for the resume). A run frozen before the rule passes no in-step stop and asks every record as before."""
    from deixis.workflow.run.flow import RunStopped
    sources = Sources(works=[work(0, abstract=ABSTRACT, doi="10.1/0")] + [work(n, doi=f"10.1/{n}") for n in (7, 8, 9)],
                      crossref_status=500)
    app = app_for(tmp_path, monkeypatch, sources)
    client = client_of(app)
    rid, run_id, _, _ = discover(client)  # Crossref fails for the run itself, so every record is still to ask
    store, settings = app.state.store, app.state.settings
    sources.crossref_status, sources.lookups = 200, []
    by_id = records_of(store, rid)
    chunk = [{"source_version_id": by_id[f"W{n}"], "doi": f"10.1/{n}"} for n in (7, 8, 9)]
    dispatch = lookups.facade.dispatch_lookup
    passed = {"now": False}

    async def first_reply_then_stop(*args, **kwargs):
        result = await dispatch(*args, **kwargs)
        passed["now"] = True  # the deadline passes, or the pause arrives, once the first reply is in
        return result
    monkeypatch.setattr(lookups.facade, "dispatch_lookup", first_reply_then_stop)

    def halt():
        if how == "pause" and passed["now"]:
            raise RunStopped
        return passed["now"]

    async def chunk_step():
        async with httpx.AsyncClient(transport=httpx.MockTransport(sources)) as http:
            await lookups._crossref_step(store, http, settings, store.run(run_id), 0, chunk, "test:", 1,
                                         halt=None if how == "before_the_rule" else halt)
    try:
        if how == "deadline":
            with pytest.raises(lookups._Stopped):
                asyncio.run(chunk_step())
        elif how == "pause":
            with pytest.raises(RunStopped):
                asyncio.run(chunk_step())
        else:
            asyncio.run(chunk_step())
        step = store.existing_step(run_id, "test:record_lookup:crossref:0")
        unasked = {n for n in (8, 9) if not lookups.answered(store, by_id[f"W{n}"], "crossref")}
    finally:
        client.__exit__(None, None, None)
    if how == "before_the_rule":
        assert sources.lookups == ["10.1/7", "10.1/8", "10.1/9"] and step["status"] == "succeeded"
        return
    assert sources.lookups == ["10.1/7"] and unasked == {8, 9}
    assert (step["status"], step["error_code"]) == (
        ("failed", "lookup_time_ceiling") if how == "deadline" else ("running", None))


@pytest.mark.parametrize("how", ["deadline", "pause"])
def test_a_stop_cancels_a_semantic_scholar_lookup_in_flight(tmp_path, monkeypatch, how):
    """A Semantic Scholar batch still out when the deadline passes or a pause arrives is cancelled at once."""
    from deixis.workflow.run.flow import RunStopped
    # Semantic Scholar refuses during the run itself, so the record is still to ask.
    sources = Sources(works=[work(0, abstract=ABSTRACT, doi="10.1/0"), work(7, doi="10.1/7")], s2_status=500)
    app = app_for(tmp_path, monkeypatch, sources)
    client = client_of(app)
    rid, run_id, _, _ = discover(client)
    store, settings = app.state.store, app.state.settings
    batch = [{"source_version_id": records_of(store, rid)["W7"], "doi": "10.1/7"}]
    out = {"sent": None, "cancelled": False}

    async def hanging(*args, **kwargs):
        out["sent"] = time.monotonic()
        try:
            await asyncio.sleep(3600)
        except asyncio.CancelledError:
            out["cancelled"] = True
            raise
    monkeypatch.setattr(lookups.facade, "dispatch_lookup", hanging)

    def halt():
        late = out["sent"] is not None and time.monotonic() - out["sent"] > 0.3
        if late and how == "pause":
            raise RunStopped
        return late

    async def batch_step():
        async with httpx.AsyncClient(transport=httpx.MockTransport(sources)) as http:
            await lookups._semantic_scholar_step(store, http, settings, store.run(run_id), 0, batch, 0, "test:",
                                                 halt=halt)
    begun = time.monotonic()
    try:
        with pytest.raises(lookups._Stopped if how == "deadline" else RunStopped):
            asyncio.run(batch_step())
        step = store.existing_step(run_id, "test:record_lookup:semantic_scholar:0")
    finally:
        client.__exit__(None, None, None)
    assert out["cancelled"] and time.monotonic() - begun < 5
    assert (step["status"], step["error_code"]) == (
        ("failed", "lookup_time_ceiling") if how == "deadline" else ("running", None))


async def headers_out(request):
    """What a real connection reports once the request's own headers are written to it: httpcore's trace."""
    import httpcore
    if (trace := request.extensions.get("trace")) is not None:
        await trace("http11.send_request_headers.started", {"request": httpcore.Request(request.method, str(request.url))})
        await trace("http11.send_request_headers.complete", {})


async def headers_back(request):
    """What it reports once the response headers came back."""
    if (trace := request.extensions.get("trace")) is not None:
        await trace("http11.receive_response_headers.complete", {})


def written(request, reply=None):
    """A reply the way a real connection gives it: headers out, then the answer's headers back. `reply` None never
    answers."""
    async def answer():
        await headers_out(request)
        if reply is None:
            await asyncio.sleep(3600)
        await headers_back(request)
        return reply
    return answer()


@pytest.mark.parametrize("case", ["connects", "never_connects", "proxy_tunnel_stalls", "retry_wait"])
def test_a_lookup_request_counts_as_out_only_while_its_own_headers_are_written_and_unanswered(case):
    """Through httpx and httpcore themselves: a request still waiting for its connection, or whose HTTPS proxy
    answered CONNECT but whose own request never went out, was never sent; one whose headers went out is, until its
    response headers come back, so a 429 waiting for its retry is not out."""
    import httpcore

    class NeverConnects(httpcore.AsyncNetworkBackend):
        async def connect_tcp(self, *args, **kwargs):
            await asyncio.sleep(3600)

    class StallingTls(httpcore.AsyncMockStream):
        async def start_tls(self, *args, **kwargs):
            await asyncio.sleep(3600)

    class Tunnel(httpcore.AsyncMockBackend):
        async def connect_tcp(self, *args, **kwargs):
            return StallingTls(list(self._buffer))

    ok = [b"HTTP/1.1 200 OK\r\n", b"Content-Length: 2\r\n\r\n", b"{}"]
    events = []

    async def one():
        transport = httpx.AsyncHTTPTransport()
        if case == "proxy_tunnel_stalls":
            transport._pool = httpcore.AsyncHTTPProxy("http://proxy.invalid:3128",
                                                      network_backend=Tunnel([b"HTTP/1.1 200 OK\r\n\r\n"]))
        else:
            backend = {"connects": httpcore.AsyncMockBackend(ok), "never_connects": NeverConnects(),
                       "retry_wait": httpcore.AsyncMockBackend([b"HTTP/1.1 429 Too Many Requests\r\n",
                                                                b"Retry-After: 5\r\nContent-Length: 0\r\n\r\n"])}[case]
            transport._pool = httpcore.AsyncConnectionPool(network_backend=backend)
        token = common.on_send.set(events.append)
        try:
            async with httpx.AsyncClient(transport=transport) as http:
                return await asyncio.wait_for(common.send(http, "https://api.crossref.org/works/10.1/7", {}, {},
                                                          "SYNTHETIC lookup", "public"),
                                              (5.0 if case == "connects" else 0.3) * WAIT_FACTOR)
        finally:
            common.on_send.reset(token)
    if case == "connects":
        response, _ = asyncio.run(one())
        assert response.status_code == 200 and events == ["sent", "answered"]
        return
    with pytest.raises(TimeoutError):
        asyncio.run(one())  # cut short: still connecting, in the tunnel, or waiting out the 429
    assert events == (["sent", "answered"] if case == "retry_wait" else [])


def test_a_retry_after_resume_cut_short_keeps_its_record_open_whatever_the_earlier_attempt_answered(tmp_path, monkeypatch):
    """Crossref fails for 7 while 8 is still out, the round stops, and the resumed chunk asks 7 again; that
    retry is still out when the round's time ends. 7 is open: its latest request went out and has no answer, even
    though an earlier attempt of the same step stored a failure for it. A record whose request never went out is not,
    nor one whose 429 came back and whose retry wait the round cut short."""
    from deixis.workflow.search import small_batch
    sources = Sources(works=[work(0, abstract=ABSTRACT, doi="10.1/0"), work(7, doi="10.1/7"), work(8, doi="10.1/8"),
                             work(9, doi="10.1/9"), work(6, doi="10.1/6")], crossref_status=500)
    app = app_for(tmp_path, monkeypatch, sources)
    client = client_of(app)
    rid, run_id, _, _ = discover(client)
    store, settings = app.state.store, app.state.settings
    by_id = records_of(store, rid)
    chunk = [{"source_version_id": by_id[f"W{n}"], "doi": f"10.1/{n}"} for n in (7, 8, 9, 6)]
    phase = []

    def crossref(request):
        doi = request.url.path.removeprefix("/works/").replace("%2F", "/")
        if doi == "10.1/9":  # never connects: no headers are written, nothing is sent
            async def hang():
                await asyncio.sleep(3600)
            return hang()
        if doi == "10.1/6":  # answered with a 429; its retry wait is cut short, so nothing of it is out
            return written(request, httpx.Response(429, headers={"retry-after": "2"}, text="SYNTHETIC rate limit"))
        if doi == "10.1/7" and not phase:
            return written(request, httpx.Response(500, text="SYNTHETIC failure"))
        return written(request)  # 8 both times, and 7's retry: out until the round's time ends

    async def round_():
        async with httpx.AsyncClient(transport=httpx.MockTransport(crossref)) as http:
            with pytest.raises(TimeoutError):
                await asyncio.wait_for(lookups._crossref_step(store, http, settings, store.run(run_id), 0, chunk,
                                                              small_batch.PRERANK_PREFIX, 8, record_sent=True),
                                       0.3 * WAIT_FACTOR)
    try:
        asyncio.run(round_())  # 7 fails, 8 is out: the run stops
        failed = store.conn.execute("SELECT status FROM record_lookups WHERE source_version_id = ? AND provider = ?",
                                    (by_id["W7"], "crossref")).fetchone()["status"]
        phase.append("resumed")
        asyncio.run(round_())  # the resume retries 7 and asks 8 again; both are out at the ceiling
        open_ = small_batch.lookup_open(store, store.run(run_id), [by_id[f"W{n}"] for n in (7, 8, 9, 6)])
        step = store.existing_step(run_id, f"{small_batch.PRERANK_PREFIX}record_lookup:crossref:0")
    finally:
        client.__exit__(None, None, None)
    assert failed == "failed"
    assert sorted(step["output"]["sent"]) == sorted(by_id[f"W{n}"] for n in (7, 8, 6))
    assert sorted(open_) == sorted(by_id[f"W{n}"] for n in (7, 8))


# ---- the flags and what they route ------------------------------------------------------------


# ---- slice 13g Task 4: Scopus is the last abstract source, on an institutional network only ---------------


