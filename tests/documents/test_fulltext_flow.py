"""Synthetic small-batch PDF routes, source-version identity and shared fetch test helpers."""

import json
import time

import httpx
import pytest

from deixis.api.app import create_app
from deixis.config import Settings
from deixis.documents.fetch import FetchResult
from deixis.providers.registry import CONNECTORS
from deixis.workflow import fulltext
from deixis.workflow.decisions import DecisionStore
from fakes import FakeAdapter, valid_response
from helpers import make_pdf
from test_abstract_flow import QUESTION, client_of, records_of

# A file whose first page names nothing, and one that names the work it was asked for (SW10.2).
PDF = make_pdf(["SYNTHETIC page one: irrigation scheduling of a greenhouse tomato crop."])


def named_pdf(doi):
    return make_pdf([f"SYNTHETIC first page https://doi.org/{doi} irrigation scheduling of a greenhouse crop."])


HALF = "SYNTHETIC irrigation scheduling of an open field crop"
HALF_ABSTRACT = "We vary the irrigation scheduling of an open field crop and report the water it used."


def work(number, *, pdf_url=None, pdf_version=None, version="publishedVersion", doi=None, title=HALF,
         abstract=HALF_ABSTRACT):
    """One SYNTHETIC OpenAlex record. `pdf_version` other than `version` makes the file another version's (D48)."""
    inverted: dict[str, list[int]] = {}
    for position, word in enumerate((abstract or "").split()):
        inverted.setdefault(word, []).append(position)
    best = {"pdf_url": pdf_url, "version": pdf_version or version} if pdf_url else None
    return {"id": f"https://openalex.org/W{number}", "doi": f"https://doi.org/{doi or f'10.1/oa.{number}'}",
            "display_name": f"{title} {number}", "publication_year": 2024, "type": "article", "authorships": [],
            "primary_location": {"version": version, "source": {"display_name": "SYNTHETIC J"}},
            "best_oa_location": best, "abstract_inverted_index": inverted or None}


class Transport:
    """Mocked OpenAlex (count probes and one page of records) plus a scripted Unpaywall. No other host answers."""

    def __init__(self, works, unpaywall=None):
        self.works, self.unpaywall = works, unpaywall or {}
        self.probes, self.searches, self.lookups = [], [], []

    def __call__(self, request):
        host, path = request.url.host, request.url.path
        if host == "api.unpaywall.org":
            doi = path.split("/v2/", 1)[1]
            self.lookups.append(doi)
            payload = self.unpaywall.get(doi)
            return httpx.Response(200, json=payload) if payload else httpx.Response(404)
        if host != "api.openalex.org" or not path.endswith("/works"):
            return httpx.Response(404)  # a DOI lookup answers "no result", which is an answer
        params = request.url.params
        query = params.get("search.title_and_abstract") or ""
        if params.get("per_page") == "1" and params.get("select") == "id":
            self.probes.append(query)
            return httpx.Response(200, json={"meta": {"count": 1 if " AND " in query else 40}, "results": []})
        self.searches.append(query)
        return httpx.Response(200, json={"meta": {"count": len(self.works), "next_cursor": None},
                                         "results": self.works})


class Fetcher:
    """A scripted PDF fetcher: every URL answers as the test says, and every request is counted."""

    def __init__(self, answers, hook=None):
        self.answers, self.hook, self.calls = answers, hook, []

    async def __call__(self, url):
        self.calls.append(url)
        if self.hook is not None:
            self.hook(self, url)
        answer = self.answers.get(url, FetchResult("http_error", final_url=url, http_status=404))
        return answer(url) if callable(answer) else answer


def ok(data=PDF):
    return lambda url: FetchResult("ok", data=data, final_url=url, http_status=200)


REFUSED = FetchResult("http_error", final_url=None, http_status=403)
TIMED_OUT = FetchResult("timeout", final_url=None, error="ReadTimeout")


def app_for(tmp_path, monkeypatch, transport, fetcher, workflow="sw", setting="auto", adapter=None,
            approval="as_proposed"):
    for connector in CONNECTORS.values():
        if connector.key_env:
            monkeypatch.delenv(connector.key_env, raising=False)
    monkeypatch.delenv("GEMINI_API_KEY", raising=False)
    monkeypatch.setenv("DEIXIS_SEARCH_WORKFLOW", workflow)
    monkeypatch.setenv("DEIXIS_CONTACT_EMAIL", "synthetic@example.org")
    return create_app(Settings(data_dir=tmp_path / "data", port=8765, search_query="code",
                               protocol_approval=approval, fulltext_fetch=setting, fulltext_adjudication="off"),
                      adapters={"fake": adapter or FakeAdapter(valid_response)},
                      http_client=httpx.AsyncClient(transport=httpx.MockTransport(transport)), fetcher=fetcher,
                      extra_hosts=("testserver",), trusted_clients=("testclient",))


SETTLED = ("completed", "failed", "paused", "cancelled")


def wait(client, rid, run_id):
    """Like the abstract stage's waiter, with `cancelled`: a question revision cancels a retrieval run."""
    deadline = time.time() + 30
    while time.time() < deadline:
        view = client.get(f"/api/researches/{rid}").json()
        run = next(r for r in view["runs"] if r["id"] == run_id)
        if run["status"] in SETTLED:
            return view, run
        time.sleep(0.05)
    raise AssertionError("the run did not settle")


def discover(client, question=QUESTION, effort="quick", **body):
    payload = {"question": question, "model_connection": "fake", "requested_model": "fake-model", "effort": effort,
               **body}
    rid = client.post("/api/researches", json=payload).json()["research"]["id"]
    run_id = client.post(f"/api/researches/{rid}/runs", json={"kind": "discovery"}).json()["id"]
    view, run = wait(client, rid, run_id)
    return rid, run_id, view, run


def wait_for_retrieval(client, rid, index=0):
    """Automatic retrieval is part of the indexed small-batch discovery run."""
    runs = sorted((r for r in client.get(f"/api/researches/{rid}").json()["runs"] if r["kind"] == "discovery"),
                  key=lambda r: r["created_at"])
    return wait(client, rid, runs[index]["id"])


def wait_for_all(client, rid):
    """Every run of the research settled, with the fast path's own: the answer its discovery queues (D254) and a
    late revision that reads the files the answer did not (D255)."""
    deadline = time.time() + 30
    while time.time() < deadline:
        view = client.get(f"/api/researches/{rid}").json()
        late = {(a.get("late_revision_status") or {}).get("status") for a in view["answers"]}
        if all(r["status"] in SETTLED for r in view["runs"]) and not late & {"waiting_fetch", "reading", "answering"}:
            return view
        time.sleep(0.05)
    raise AssertionError("the runs did not settle")


def step_output(store, run_id, key):
    row = store.conn.execute("SELECT output_json FROM run_steps WHERE run_id = ? AND operation_key = ?",
                             (run_id, key)).fetchone()
    return None if row is None or row[0] is None else json.loads(row[0])


def work_steps(store, run_id):
    """Every work step of a retrieval run, by the head it was opened for."""
    return {json.loads(row["output_json"])["head"]: dict(row) for row in store.conn.execute(
        "SELECT * FROM run_steps WHERE run_id = ? AND kind = 'code:fulltext_work' ORDER BY rowid", (run_id,))}


def fulltext_codes(store, rid):
    """Every record's open full-text reason code, by its OpenAlex identifier."""
    decisions = DecisionStore(store)
    return {key: (decisions.current(rid, svid, "fulltext") or {}).get("reason_code")
            for key, svid in records_of(store, rid).items()}


def selections_of(store, rid):
    return {row["state"] for row in store.conn.execute(
        "SELECT state FROM selections WHERE research_id = ?", (rid,))}


def unpaywall(doi, url, version):
    return {doi: {"doi": doi, "oa_locations": [{"url_for_pdf": url, "version": version, "url": f"{url}#landing"}]}}


def test_the_open_link_of_the_record_itself_is_the_first_route_and_the_version_read_is_stored(tmp_path, monkeypatch):
    fetcher = Fetcher({"https://example.org/w1.pdf": ok()})
    app = app_for(tmp_path, monkeypatch, Transport([work(1, pdf_url="https://example.org/w1.pdf")]), fetcher)
    client = client_of(app)
    try:
        rid, _, _, _ = discover(client)
        _, run = wait_for_retrieval(client, rid)
        store = app.state.store
        head = records_of(store, rid)["W1"]
        output = work_steps(store, run["id"])[head]
        output = json.loads(output["output_json"])
    finally:
        client.__exit__(None, None, None)
    assert output["route"] == "record_link" and output["read_version"] == head
    assert output["version_label"] == "publishedVersion" and output["asset_id"]
    assert output["code"] == "not_read_yet" and output["requests_unanswered"] == 0


def test_a_closed_published_record_is_read_through_the_open_preprint_of_the_same_work(tmp_path, monkeypatch):
    """D48: the published record's own link is closed, so the work is read through its submitted version."""
    record = work(1, pdf_url="https://example.org/w1-preprint.pdf", pdf_version="submittedVersion")
    fetcher = Fetcher({"https://example.org/w1-preprint.pdf": ok()})
    app = app_for(tmp_path, monkeypatch, Transport([record]), fetcher)
    client = client_of(app)
    try:
        rid, _, _, _ = discover(client)
        _, run = wait_for_retrieval(client, rid)
        wait_for_all(client, rid)
        store = app.state.store
        head = records_of(store, rid)["W1"]
        output = json.loads(work_steps(store, run["id"])[head]["output_json"])
        decision = DecisionStore(store).current(rid, output["read_version"], "fulltext")
    finally:
        client.__exit__(None, None, None)
    assert output["route"] == "work_version" and output["read_version"] != head
    assert output["version_label"] == "submittedVersion" and output["code"] == "not_read_yet"
    # The decision is written on the version that was read, not on the published record (D4, D48). The file names no
    # work and nothing read it (no read in this run, and the fast path's late revision did not take it up).
    assert decision["reason_code"] == "not_read_yet" and decision["source_version_id"] == output["read_version"]


def test_a_file_that_names_the_work_is_recorded_as_confirmed_and_one_that_does_not_is_kept_anyway(tmp_path, monkeypatch):
    """SW10.2: the check is recorded and counted; an `unconfirmed` file is neither set aside nor deleted."""
    fetcher = Fetcher({"https://example.org/w1.pdf": ok(named_pdf("10.1/oa.1")),
                       "https://example.org/w2.pdf": ok()})
    works = [work(n, pdf_url=f"https://example.org/w{n}.pdf") for n in (1, 2)]
    app = app_for(tmp_path, monkeypatch, Transport(works), fetcher)
    client = client_of(app)
    try:
        rid, _, _, _ = discover(client)
        _, run = wait_for_retrieval(client, rid)
        wait_for_all(client, rid)
        store = app.state.store
        records, steps = records_of(store, rid), work_steps(store, run["id"])
        checks = {key: json.loads(steps[svid]["output_json"])["identity"] for key, svid in records.items()}
        codes = fulltext_codes(store, rid)
    finally:
        client.__exit__(None, None, None)
    assert checks == {"W1": "doi", "W2": "unconfirmed"}
    # The fast path's late revision (D255) reads both files after the answer: the confirmed one is read by the model,
    # the unconfirmed one is kept and waits for the person, with no model call.
    assert codes == {"W1": "all_parts_verified", "W2": "pdf_identity_unconfirmed"}


@pytest.mark.parametrize("version,identity_status", [("submittedVersion", "mismatch"), (None, "doi_verified")])
def test_an_uncertain_or_mismatched_copy_is_never_attached_by_code(tmp_path, monkeypatch, version, identity_status):
    """A copy whose version nobody declared, or whose DOI is another work's, keeps waiting for the user."""
    copy = "https://example.org/w1-other.pdf"
    doi = "10.1/oa.1" if identity_status == "doi_verified" else "10.1/other"
    payload = {"10.1/oa.1": {"doi": doi, "oa_locations": [{"url_for_pdf": copy, "version": version}]}}
    fetcher = Fetcher({copy: ok()})
    app = app_for(tmp_path, monkeypatch, Transport([work(1)], payload), fetcher)
    client = client_of(app)
    try:
        rid, _, _, _ = discover(client)
        _, run = wait_for_retrieval(client, rid)
        store = app.state.store
        head = records_of(store, rid)["W1"]
        output = json.loads(work_steps(store, run["id"])[head]["output_json"])
        rows = store.conn.execute("SELECT COUNT(*) FROM source_versions WHERE work_id = ?",
                                  (store.source(head)["work_id"],)).fetchone()[0]
    finally:
        client.__exit__(None, None, None)
    assert output["code"] == "no_fulltext" and output["route"] is None
    assert rows == 1 and copy not in fetcher.calls
