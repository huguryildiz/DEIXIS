"""The full-text retrieval run inside a real `sw` research, driven through the API (slice 10, SW10, D83).

What is checked here is workflow behavior: that a completed `sw` discovery run is followed by one retrieval run and
that a `legacy` research and the `off` setting get none; that a work is fetched once, through the routes an answer
run already uses, and records the version that was read; that nothing is included or excluded and no model is
called; that a work no route answered for is left undecided and tried again; that a resumed run finishes the whole
plan, requests nothing twice and reports the same numbers as an uninterrupted one; and that `legacy`, `answer` and
`pdf_collection` runs are what they were.

Records, titles and abstracts are SYNTHETIC and from two fields, every transport is mocked and the model is
scripted. Passing shows the run behaves as the slice says, not that real papers are reachable: what share of a
literature has an open full text, how long a sequential run takes and how much of a wrong PDF the identity check
catches were not measured here or anywhere else in this slice.
"""

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
    return create_app(Settings(data_dir=tmp_path / "data", port=8765, search_workflow=workflow, search_query="code",
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


def retrieval_runs(client, rid):
    return [r for r in client.get(f"/api/researches/{rid}").json()["runs"] if r["kind"] == "fulltext_fetch"]


def wait_for_retrieval(client, rid, index=0):
    """The index-th retrieval run of this research, once it has settled. It is queued by the discovery run itself."""
    deadline = time.time() + 30
    while time.time() < deadline:
        runs = sorted(retrieval_runs(client, rid), key=lambda r: r["created_at"])
        if len(runs) > index and runs[index]["status"] in SETTLED:
            return wait(client, rid, runs[index]["id"])
        time.sleep(0.05)
    raise AssertionError("no retrieval run settled")


def step_output(store, run_id, key):
    row = store.conn.execute("SELECT output_json FROM run_steps WHERE run_id = ? AND operation_key = ?",
                             (run_id, key)).fetchone()
    return None if row is None or row[0] is None else json.loads(row[0])


def work_steps(store, run_id):
    """Every work step of a retrieval run, by the head it was opened for."""
    return {row["operation_key"].split(":", 1)[1]: dict(row) for row in store.conn.execute(
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


# ---- a retrieval run follows a discovery run, and only where it should -------------------------

def test_a_completed_sw_discovery_run_is_followed_by_one_retrieval_run(tmp_path, monkeypatch):
    fetcher = Fetcher({"https://example.org/w1.pdf": ok()})
    app = app_for(tmp_path, monkeypatch, Transport([work(1, pdf_url="https://example.org/w1.pdf"), work(2)]), fetcher)
    client = client_of(app)
    try:
        rid, run_id, _, discovery = discover(client)
        view, run = wait_for_retrieval(client, rid)
        store = app.state.store
        codes, kinds = fulltext_codes(store, rid), {s["kind"] for s in store.run_steps(run["id"])}
        summary = step_output(store, run["id"], "fulltext_summary")
        # A second discovery run of the same question must not open a second retrieval run for the first one.
        again = client.post(f"/api/researches/{rid}/runs", json={"kind": "discovery"}).json()["id"]
        wait(client, rid, again)
        wait_for_retrieval(client, rid, index=1)
        after = len(retrieval_runs(client, rid))
    finally:
        client.__exit__(None, None, None)
    assert discovery["status"] == "completed" and run["status"] == "completed"
    assert run["budget"] == fulltext.fetch_budget("quick") and run["usage"].get("model_calls", 0) == 0
    assert kinds == {"code:fulltext_plan", "code:fulltext_work", "code:fulltext_summary", "fetch_pdf", "pdf_other_copy"}
    assert codes == {"W1": "not_read_yet", "W2": "no_fulltext"}
    assert summary["fetched"] == 1 and summary["no_fulltext"] == 1 and summary["not_settled"] == 0
    assert after == 2  # one per discovery run, never two for the same one


def test_no_retrieval_run_follows_when_the_setting_is_off_or_the_research_is_legacy(tmp_path, monkeypatch):
    app = app_for(tmp_path, monkeypatch, Transport([work(1)]), Fetcher({}), setting="off")
    client = client_of(app)
    try:
        rid, _, _, run = discover(client)
        off = retrieval_runs(client, rid)
    finally:
        client.__exit__(None, None, None)
    assert run["status"] == "completed" and off == []

    legacy = app_for(tmp_path / "legacy", monkeypatch, Transport([work(1)]), Fetcher({}), workflow="legacy")
    client = client_of(legacy)
    try:
        rid, _, _, run = discover(client)
        assert run["status"] == "completed" and retrieval_runs(client, rid) == []
        refused = client.post(f"/api/researches/{rid}/runs", json={"kind": "fulltext_fetch"})
    finally:
        client.__exit__(None, None, None)
    assert refused.status_code == 422


def test_a_paused_discovery_run_queues_nothing(tmp_path, monkeypatch):
    """Only a run that really completed leaves work behind; one waiting for the user is still theirs to resume."""
    app = app_for(tmp_path, monkeypatch, Transport([work(1)]), Fetcher({}), approval="ask")
    client = client_of(app)
    try:
        rid, _, _, run = discover(client)
        queued = retrieval_runs(client, rid)
    finally:
        client.__exit__(None, None, None)
    assert run["status"] == "paused" and run["pause_reason"] == "protocol_approval_needed"
    assert queued == []


# ---- what one work's single attempt does -------------------------------------------------------

def test_no_selection_is_included_or_excluded_and_no_model_session_is_opened(tmp_path, monkeypatch):
    """SW1.2: the three codes a retrieval run writes are all `unresolved`, which is the `pending` already there."""
    fetcher = Fetcher({"https://example.org/w1.pdf": ok()})
    app = app_for(tmp_path, monkeypatch, Transport([work(1, pdf_url="https://example.org/w1.pdf"), work(2)]), fetcher)
    client = client_of(app)
    try:
        rid, _, _, _ = discover(client)
        _, run = wait_for_retrieval(client, rid)
        store = app.state.store
        states = selections_of(store, rid)
        inputs = store.conn.execute("SELECT COUNT(*) FROM step_inputs i JOIN run_steps s ON s.id = i.step_id"
                                    " WHERE s.run_id = ?", (run["id"],)).fetchone()[0]
    finally:
        client.__exit__(None, None, None)
    assert states == {"pending"} and inputs == 0
    assert run["usage"].get("model_calls", 0) == 0 and run["budget"]["max_model_calls"] == 0


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
        store = app.state.store
        head = records_of(store, rid)["W1"]
        output = json.loads(work_steps(store, run["id"])[head]["output_json"])
        decision = DecisionStore(store).current(rid, output["read_version"], "fulltext")
    finally:
        client.__exit__(None, None, None)
    assert output["route"] == "work_version" and output["read_version"] != head
    assert output["version_label"] == "submittedVersion" and output["code"] == "not_read_yet"
    # The decision is written on the version that was read, not on the published record (D4, D48).
    assert decision["reason_code"] == "not_read_yet" and decision["source_version_id"] == output["read_version"]


def test_a_work_every_route_answered_for_is_left_unresolved_as_no_fulltext(tmp_path, monkeypatch):
    fetcher = Fetcher({"https://example.org/w1.pdf": REFUSED})
    app = app_for(tmp_path, monkeypatch, Transport([work(1, pdf_url="https://example.org/w1.pdf")]), fetcher)
    client = client_of(app)
    try:
        rid, _, _, _ = discover(client)
        _, run = wait_for_retrieval(client, rid)
        store = app.state.store
        codes, states = fulltext_codes(store, rid), selections_of(store, rid)
        summary = step_output(store, run["id"], "fulltext_summary")
    finally:
        client.__exit__(None, None, None)
    assert codes == {"W1": "no_fulltext"} and states == {"pending"}
    assert summary["no_fulltext"] == 1 and summary["routes"] == {"none": 1}


def test_a_work_whose_route_did_not_answer_is_decided_by_nothing_and_is_tried_by_the_next_run(tmp_path, monkeypatch):
    """A timeout is not a refusal (D35): the work stays undecided and the next retrieval run plans it again."""
    fetcher = Fetcher({"https://example.org/w1.pdf": TIMED_OUT})
    app = app_for(tmp_path, monkeypatch, Transport([work(1, pdf_url="https://example.org/w1.pdf")]), fetcher)
    client = client_of(app)
    try:
        rid, _, _, _ = discover(client)
        _, first = wait_for_retrieval(client, rid)
        store = app.state.store
        head = records_of(store, rid)["W1"]
        step = work_steps(store, first["id"])[head]
        codes = fulltext_codes(store, rid)
        # A second retrieval run, started by hand, plans the same work again and asks the link again.
        second = client.post(f"/api/researches/{rid}/runs", json={"kind": "fulltext_fetch"}).json()["id"]
        wait(client, rid, second)
        replanned = step_output(store, second, "fulltext_plan")["works"]
        summary = step_output(store, first["id"], "fulltext_summary")
    finally:
        client.__exit__(None, None, None)
    assert step["status"] == "failed" and step["error_code"] == "fetch_not_settled"
    assert codes == {"W1": None}
    assert replanned == [head] and fetcher.calls.count("https://example.org/w1.pdf") == 2
    assert summary["not_settled"] == 1


def test_a_link_that_refused_is_not_requested_again_by_a_later_run(tmp_path, monkeypatch):
    """D35, and "the next run continues where the first stopped": a fresh `no_fulltext` is not tried twice."""
    fetcher = Fetcher({"https://example.org/w1.pdf": REFUSED})
    app = app_for(tmp_path, monkeypatch, Transport([work(1, pdf_url="https://example.org/w1.pdf")]), fetcher)
    client = client_of(app)
    try:
        rid, _, _, _ = discover(client)
        wait_for_retrieval(client, rid)
        asked = list(fetcher.calls)
        second = client.post(f"/api/researches/{rid}/runs", json={"kind": "fulltext_fetch"}).json()["id"]
        wait(client, rid, second)
        replanned = step_output(app.state.store, second, "fulltext_plan")
    finally:
        client.__exit__(None, None, None)
    assert asked == ["https://example.org/w1.pdf"] and fetcher.calls == asked
    assert replanned["works"] == [] and replanned["groups"] == {"user": 0, "candidate": 0, "unresolved": 0}


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
        store = app.state.store
        records, steps = records_of(store, rid), work_steps(store, run["id"])
        checks = {key: json.loads(steps[svid]["output_json"])["identity"] for key, svid in records.items()}
        codes = fulltext_codes(store, rid)
        summary = step_output(store, run["id"], "fulltext_summary")
    finally:
        client.__exit__(None, None, None)
    assert checks == {"W1": "doi", "W2": "unconfirmed"}
    assert codes == {"W1": "not_read_yet", "W2": "not_read_yet"}  # neither file is set aside
    assert summary["identity"] == {"doi": 1, "unconfirmed": 1}


# ---- a copy of another version lands on its own row --------------------------------------------

def test_a_verified_copy_of_another_version_opens_its_own_row_under_the_work(tmp_path, monkeypatch):
    """SW10.3 and D4: the published record keeps no file it does not have; the submitted copy carries its own label."""
    copy = "https://example.org/w1-submitted.pdf"
    transport = Transport([work(1)], unpaywall("10.1/oa.1", copy, "submittedVersion"))
    fetcher = Fetcher({copy: ok()})
    app = app_for(tmp_path, monkeypatch, transport, fetcher)
    client = client_of(app)
    try:
        rid, _, _, _ = discover(client)
        _, run = wait_for_retrieval(client, rid)
        store = app.state.store
        head = records_of(store, rid)["W1"]
        output = json.loads(work_steps(store, run["id"])[head]["output_json"])
        opened = store.source(output["read_version"])
        candidates = [c["source_version_id"] for c in store.candidates(rid)]
        text = (store.has_pdf_text(opened["id"]), store.has_pdf_text(head))
        reads, heads = store.answer_version(rid, head), store.work_heads(rid)[opened["work_id"]]
        # A second retrieval run must not open the row twice nor ask for the file again.
        second = client.post(f"/api/researches/{rid}/runs", json={"kind": "fulltext_fetch"}).json()["id"]
        wait(client, rid, second)
        rows = store.conn.execute("SELECT COUNT(*) FROM source_versions WHERE work_id = ?",
                                  (opened["work_id"],)).fetchone()[0]
    finally:
        client.__exit__(None, None, None)
    assert output["route"] == "lookup_version" and output["code"] == "not_read_yet"
    assert opened["id"] != head and opened["version_label"] == "submittedVersion" and opened["doi"] is None
    assert text == (True, False) and reads == opened["id"]
    assert opened["id"] not in candidates  # a member of the research, never a candidate screened on its own
    assert heads == head  # the head of the work does not change
    assert rows == 2 and fetcher.calls.count(copy) == 1


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


# ---- what the plan holds, and what it leaves out -----------------------------------------------

def test_the_user_s_own_works_come_first_and_the_works_they_excluded_are_not_fetched(tmp_path, monkeypatch):
    fetcher = Fetcher({f"https://example.org/w{n}.pdf": ok() for n in (1, 2, 3)})
    works = [work(n, pdf_url=f"https://example.org/w{n}.pdf") for n in (1, 2, 3)]
    app = app_for(tmp_path, monkeypatch, Transport(works), fetcher, setting="off")
    client = client_of(app)
    try:
        rid, _, view, _ = discover(client)
        store = app.state.store
        records = records_of(store, rid)
        for key, state in (("W3", "included"), ("W1", "excluded")):
            source = next(s for s in view["sources"] if s["source_version_id"] == records[key])
            client.patch(f"/api/researches/{rid}/selections/{records[key]}",
                         json={"state": state, "expected_version": source["selection"]["version"]})
        run_id = client.post(f"/api/researches/{rid}/runs", json={"kind": "fulltext_fetch"}).json()["id"]
        wait(client, rid, run_id)
        plan = step_output(store, run_id, "fulltext_plan")
        codes = fulltext_codes(store, rid)
    finally:
        client.__exit__(None, None, None)
    assert plan["works"] == [records["W3"], records["W2"]]  # the user's work first, then code's candidate
    assert plan["groups"] == {"user": 1, "candidate": 1, "unresolved": 0}
    assert codes["W1"] is None and "https://example.org/w1.pdf" not in fetcher.calls


def test_the_limit_stops_the_run_and_the_next_one_takes_the_works_it_did_not_reach(tmp_path, monkeypatch):
    monkeypatch.setattr(fulltext, "FULLTEXT_WORK_LIMIT", dict(fulltext.FULLTEXT_WORK_LIMIT, quick=1))
    fetcher = Fetcher({f"https://example.org/w{n}.pdf": ok() for n in (1, 2)})
    works = [work(n, pdf_url=f"https://example.org/w{n}.pdf") for n in (1, 2)]
    app = app_for(tmp_path, monkeypatch, Transport(works), fetcher)
    client = client_of(app)
    try:
        rid, _, _, _ = discover(client)
        _, first = wait_for_retrieval(client, rid)
        store = app.state.store
        first_plan = step_output(store, first["id"], "fulltext_plan")
        first_summary = step_output(store, first["id"], "fulltext_summary")
        second = client.post(f"/api/researches/{rid}/runs", json={"kind": "fulltext_fetch"}).json()["id"]
        wait(client, rid, second)
        second_plan = step_output(store, second, "fulltext_plan")
        codes = fulltext_codes(store, rid)
    finally:
        client.__exit__(None, None, None)
    assert len(first_plan["works"]) == 1 and first_plan["not_reached"] == 1 and first_summary["not_reached"] == 1
    assert second_plan["works"] and second_plan["works"] != first_plan["works"]
    assert set(codes.values()) == {"not_read_yet"}


def test_a_work_whose_text_is_already_here_is_not_requested_and_still_gets_its_code(tmp_path, monkeypatch):
    fetcher = Fetcher({"https://example.org/w1.pdf": ok()})
    app = app_for(tmp_path, monkeypatch, Transport([work(1, pdf_url="https://example.org/w1.pdf")]), fetcher)
    client = client_of(app)
    try:
        rid, _, _, _ = discover(client)
        wait_for_retrieval(client, rid)
        store = app.state.store
        asked = list(fetcher.calls)
        # The code is already written, so the next run neither asks for the file nor closes and reopens the row.
        rows = store.conn.execute("SELECT COUNT(*) FROM stage_decisions WHERE research_id = ? AND stage = 'fulltext'",
                                  (rid,)).fetchone()[0]
        second = client.post(f"/api/researches/{rid}/runs", json={"kind": "fulltext_fetch"}).json()["id"]
        wait(client, rid, second)
        plan = step_output(store, second, "fulltext_plan")
        after = store.conn.execute("SELECT COUNT(*) FROM stage_decisions WHERE research_id = ? AND stage = 'fulltext'",
                                   (rid,)).fetchone()[0]
    finally:
        client.__exit__(None, None, None)
    assert plan["already_text"] == 1 and plan["works"] == []
    assert fetcher.calls == asked and rows == after == 1


# ---- a resumed run finishes the whole plan and counts nothing twice ----------------------------

def paused_after(app, n):
    """A fetcher that asks the running retrieval run to pause once it has answered n requests."""
    def hook(fetcher, url):
        if len(fetcher.calls) != n:
            return
        row = app.state.store.conn.execute(
            "SELECT id FROM runs WHERE kind = 'fulltext_fetch' AND status = 'running'").fetchone()
        if row:
            app.state.store.update_run(row["id"], status="pause_requested", pause_reason="user_requested")
    return hook


def test_a_run_paused_in_the_middle_finishes_the_whole_plan_when_it_is_resumed(tmp_path, monkeypatch):
    """Lesson 1 of slice 09's review, in the shape that hid it: the plan is exactly as long as the limit.

    A work read back from the store must not be charged to the limit again; if it were, the resumed run would
    stop after the works it had already fetched and leave the rest of its own frozen plan undone.
    """
    monkeypatch.setattr(fulltext, "FULLTEXT_WORK_LIMIT", dict(fulltext.FULLTEXT_WORK_LIMIT, quick=3))
    urls = {f"https://example.org/w{n}.pdf": ok() for n in (1, 2, 3)}
    works = [work(n, pdf_url=f"https://example.org/w{n}.pdf") for n in (1, 2, 3)]
    fetcher = Fetcher(urls)
    app = app_for(tmp_path, monkeypatch, Transport(works), fetcher)
    fetcher.hook = paused_after(app, 2)
    client = client_of(app)
    try:
        rid, _, _, _ = discover(client)
        _, paused = wait_for_retrieval(client, rid)
        assert paused["status"] == "paused", paused
        plan = step_output(app.state.store, paused["id"], "fulltext_plan")
        fetcher.hook = None
        client.post(f"/api/runs/{paused['id']}/resume")
        _, resumed = wait(client, rid, paused["id"])
        store = app.state.store
        summary = step_output(store, resumed["id"], "fulltext_summary")
        codes = fulltext_codes(store, rid)
        done = work_steps(store, resumed["id"])
    finally:
        client.__exit__(None, None, None)
    assert resumed["status"] == "completed"
    assert len(plan["works"]) == plan["limit"] == 3
    assert sorted(done) == sorted(plan["works"]) and {s["status"] for s in done.values()} == {"succeeded"}
    assert set(codes.values()) == {"not_read_yet"}
    # Nothing was requested twice, and the summary reports the whole run, not the half that was in memory.
    assert sorted(fetcher.calls) == sorted(urls)
    assert summary == {"fetched": 3, "unreadable": 0, "no_fulltext": 0, "not_settled": 0, "already_text": 0,
                       "not_reached": 0, "identity": {"unconfirmed": 3}, "routes": {"record_link": 3}}


def test_a_resumed_run_keeps_the_limit_it_was_queued_with_after_the_effort_limit_changes(tmp_path, monkeypatch):
    """D94 raised quick's limit; a run queued before that finishes with the room it was given, not the new one."""
    monkeypatch.setattr(fulltext, "FULLTEXT_WORK_LIMIT", dict(fulltext.FULLTEXT_WORK_LIMIT, quick=2))
    urls = {f"https://example.org/w{n}.pdf": ok() for n in (1, 2, 3)}
    works = [work(n, pdf_url=f"https://example.org/w{n}.pdf") for n in (1, 2, 3)]
    fetcher = Fetcher(urls)
    app = app_for(tmp_path, monkeypatch, Transport(works), fetcher)
    fetcher.hook = paused_after(app, 1)
    client = client_of(app)
    try:
        rid, _, _, _ = discover(client)
        _, paused = wait_for_retrieval(client, rid)
        assert paused["status"] == "paused", paused
        monkeypatch.setattr(fulltext, "FULLTEXT_WORK_LIMIT", dict(fulltext.FULLTEXT_WORK_LIMIT, quick=3))
        fetcher.hook = None
        client.post(f"/api/runs/{paused['id']}/resume")
        _, resumed = wait(client, rid, paused["id"])
        plan = step_output(app.state.store, resumed["id"], "fulltext_plan")
    finally:
        client.__exit__(None, None, None)
    assert resumed["status"] == "completed"
    assert resumed["budget"]["max_fulltext_works"] == 2
    assert plan["limit"] == 2 and len(plan["works"]) == 2 and plan["not_reached"] == 1
    assert len(fetcher.calls) == 2


def test_an_uninterrupted_run_of_the_same_plan_reports_the_same_numbers(tmp_path, monkeypatch):
    monkeypatch.setattr(fulltext, "FULLTEXT_WORK_LIMIT", dict(fulltext.FULLTEXT_WORK_LIMIT, quick=3))
    urls = {f"https://example.org/w{n}.pdf": ok() for n in (1, 2, 3)}
    fetcher = Fetcher(urls)
    app = app_for(tmp_path, monkeypatch, Transport([work(n, pdf_url=f"https://example.org/w{n}.pdf") for n in (1, 2, 3)]),
                  fetcher)
    client = client_of(app)
    try:
        rid, _, _, _ = discover(client)
        _, run = wait_for_retrieval(client, rid)
        summary = step_output(app.state.store, run["id"], "fulltext_summary")
    finally:
        client.__exit__(None, None, None)
    assert run["status"] == "completed"
    assert summary == {"fetched": 3, "unreadable": 0, "no_fulltext": 0, "not_settled": 0, "already_text": 0,
                       "not_reached": 0, "identity": {"unconfirmed": 3}, "routes": {"record_link": 3}}


def test_a_run_paused_inside_one_work_resumes_it_without_asking_the_same_link_again(tmp_path, monkeypatch):
    """The pause falls between a work's `fetch_pdf` step and the rest of that work, so its work step is unfinished."""
    monkeypatch.setattr(fulltext, "FULLTEXT_WORK_LIMIT", dict(fulltext.FULLTEXT_WORK_LIMIT, quick=2))
    # The published record has an open link of its own that refuses, and the work also has an open preprint.
    record = work(1, pdf_url="https://example.org/w1-preprint.pdf", pdf_version="submittedVersion")
    record["locations"] = [{"is_oa": True, "pdf_url": "https://example.org/w1.pdf", "version": "publishedVersion"}]
    fetcher = Fetcher({"https://example.org/w1.pdf": REFUSED, "https://example.org/w1-preprint.pdf": ok()})
    app = app_for(tmp_path, monkeypatch, Transport([record, work(2)]), fetcher)
    fetcher.hook = paused_after(app, 1)
    client = client_of(app)
    try:
        rid, _, _, _ = discover(client)
        _, paused = wait_for_retrieval(client, rid)
        store = app.state.store
        head = records_of(store, rid)["W1"]
        halfway = work_steps(store, paused["id"]).get(head, {}).get("status")
        fetcher.hook = None
        client.post(f"/api/runs/{paused['id']}/resume")
        _, resumed = wait(client, rid, paused["id"])
        output = json.loads(work_steps(store, resumed["id"])[head]["output_json"])
    finally:
        client.__exit__(None, None, None)
    assert paused["status"] == "paused" and halfway == "running"
    assert resumed["status"] == "completed" and output["code"] == "not_read_yet"
    assert output["route"] == "work_version"
    # The link that refused is not asked a second time (D35), and the preprint is fetched once.
    assert fetcher.calls.count("https://example.org/w1.pdf") == 1
    assert fetcher.calls.count("https://example.org/w1-preprint.pdf") == 1


# ---- failures, revisions and the runs that came before -----------------------------------------

def test_one_work_s_failure_does_not_stop_the_others(tmp_path, monkeypatch):
    def explode(url):
        raise RuntimeError("SYNTHETIC failure inside one work")

    fetcher = Fetcher({"https://example.org/w1.pdf": explode, "https://example.org/w2.pdf": ok()})
    works = [work(n, pdf_url=f"https://example.org/w{n}.pdf") for n in (1, 2)]
    app = app_for(tmp_path, monkeypatch, Transport(works), fetcher)
    client = client_of(app)
    try:
        rid, _, _, _ = discover(client)
        _, run = wait_for_retrieval(client, rid)
        store = app.state.store
        records, steps = records_of(store, rid), work_steps(store, run["id"])
        codes = fulltext_codes(store, rid)
    finally:
        client.__exit__(None, None, None)
    assert run["status"] == "completed"
    assert steps[records["W1"]]["error_code"] == "fulltext_work_failed"
    assert steps[records["W2"]]["status"] == "succeeded" and codes["W2"] == "not_read_yet"


def test_a_question_revision_cancels_the_run_and_makes_its_decisions_stale(tmp_path, monkeypatch):
    """A result of an older question is kept but not applied as current (SW11.10)."""
    monkeypatch.setattr(fulltext, "FULLTEXT_WORK_LIMIT", dict(fulltext.FULLTEXT_WORK_LIMIT, quick=3))
    fetcher = Fetcher({f"https://example.org/w{n}.pdf": ok() for n in (1, 2, 3)})
    app = app_for(tmp_path, monkeypatch,
                  Transport([work(n, pdf_url=f"https://example.org/w{n}.pdf") for n in (1, 2, 3)]), fetcher)
    fetcher.hook = paused_after(app, 1)
    client = client_of(app)
    try:
        rid, _, _, _ = discover(client)
        _, paused = wait_for_retrieval(client, rid)
        store = app.state.store
        research = client.get(f"/api/researches/{rid}").json()["research"]
        client.post(f"/api/researches/{rid}/scope", json={"question": f"{QUESTION} under a SYNTHETIC drip line",
                                                          "expected_version": research["version"]})
        fetcher.hook = None
        client.post(f"/api/runs/{paused['id']}/resume")
        _, run = wait(client, rid, paused["id"])
        decisions = DecisionStore(store)
        stale = [decisions.is_stale(dict(row)) for row in store.conn.execute(
            "SELECT * FROM stage_decisions WHERE research_id = ? AND stage = 'fulltext' AND superseded_at IS NULL",
            (rid,))]
    finally:
        client.__exit__(None, None, None)
    assert paused["status"] == "paused"
    assert run["status"] == "cancelled" and run["pause_reason"] == "scope_revised"
    assert stale and all(stale)


def test_an_answer_run_waits_for_the_retrieval_run_and_is_free_once_it_is_paused(tmp_path, monkeypatch):
    """One worker, one active run per research: the way out of a long retrieval is to pause it (open point)."""
    # More works than are fetched at once (slice 13e), so the resumed run still has works of its own to fetch.
    numbers = range(1, fulltext.FULLTEXT_FETCH_PARALLEL + 3)
    monkeypatch.setattr(fulltext, "FULLTEXT_WORK_LIMIT", dict(fulltext.FULLTEXT_WORK_LIMIT, quick=len(numbers)))
    fetcher = Fetcher({f"https://example.org/w{n}.pdf": ok() for n in numbers})
    app = app_for(tmp_path, monkeypatch, Transport([work(n, pdf_url=f"https://example.org/w{n}.pdf") for n in numbers]),
                  fetcher)
    fetcher.hook = paused_after(app, 1)
    client = client_of(app)
    try:
        rid, _, view, _ = discover(client)
        _, paused = wait_for_retrieval(client, rid)
        head = records_of(app.state.store, rid)["W1"]
        source = next(s for s in client.get(f"/api/researches/{rid}").json()["sources"]
                      if s["source_version_id"] == head)
        client.patch(f"/api/researches/{rid}/selections/{head}",
                     json={"state": "included", "expected_version": source["selection"]["version"]})
        fetcher.hook = None
        client.post(f"/api/runs/{paused['id']}/resume")
        blocked = client.post(f"/api/researches/{rid}/runs", json={"kind": "answer"})
        wait(client, rid, paused["id"])
        allowed = client.post(f"/api/researches/{rid}/runs", json={"kind": "answer"})
    finally:
        client.__exit__(None, None, None)
    assert paused["status"] == "paused"
    assert blocked.status_code == 409 and allowed.status_code == 202


def test_an_answer_run_and_a_pdf_collection_run_keep_the_steps_they_had(tmp_path, monkeypatch):
    """Neither gains a retrieval step, the wider other-copy trigger, nor a version row of its own (byte for byte)."""
    fetcher = Fetcher({"https://example.org/w1.pdf": ok()})
    transport = Transport([work(1, pdf_url="https://example.org/w1.pdf"), work(2)],
                          unpaywall("10.1/oa.2", "https://example.org/w2-submitted.pdf", "submittedVersion"))
    app = app_for(tmp_path, monkeypatch, transport, fetcher, setting="off")
    client = client_of(app)
    try:
        rid, _, view, _ = discover(client)
        store = app.state.store
        records = records_of(store, rid)
        for key in ("W1", "W2"):
            source = next(s for s in view["sources"] if s["source_version_id"] == records[key])
            client.patch(f"/api/researches/{rid}/selections/{records[key]}",
                         json={"state": "included", "expected_version": source["selection"]["version"]})
        collection = client.post(f"/api/researches/{rid}/runs", json={"kind": "pdf_collection"}).json()["id"]
        wait(client, rid, collection)
        kinds = {s["kind"] for s in store.run_steps(collection)}
        rows = store.conn.execute("SELECT COUNT(*) FROM source_versions").fetchone()[0]
        codes = fulltext_codes(store, rid)
        answer = client.post(f"/api/researches/{rid}/runs", json={"kind": "answer"}).json()["id"]
        _, answered = wait(client, rid, answer)
        answer_kinds = {s["kind"] for s in store.run_steps(answer)}
    finally:
        client.__exit__(None, None, None)
    assert kinds <= {"fetch_pdf", "pdf_other_copy"}
    assert not any(kind.startswith("code:fulltext") for kind in kinds | answer_kinds)
    # W2 has no open link at all, so a collection run opens no lookup for it and no version row is added.
    assert rows == 2 and "https://example.org/w2-submitted.pdf" not in fetcher.calls
    assert codes == {"W1": None, "W2": None}  # a collection run writes no full-text decision
    assert answered["status"] in ("completed", "paused")


def test_a_stale_non_human_fulltext_decision_yields_to_a_newer_abstract_decision(tmp_path, monkeypatch):
    """A stale full-text code no longer speaks for the work (slice 12). The abstract decision under the question
    the research is now asking does. A stale human full-text decision still speaks; that case is in
    `test_adjudication.py`.
    """
    fetcher = Fetcher({"https://example.org/w1.pdf": ok()})
    app = app_for(tmp_path, monkeypatch, Transport([work(1, pdf_url="https://example.org/w1.pdf")]), fetcher)
    client = client_of(app)
    try:
        rid, _, _, _ = discover(client)
        _, run = wait_for_retrieval(client, rid)
        store = app.state.store
        head = records_of(store, rid)["W1"]
        research = client.get(f"/api/researches/{rid}").json()["research"]
        client.post(f"/api/researches/{rid}/scope", json={"question": f"{QUESTION} under a SYNTHETIC drip line",
                                                          "expected_version": research["version"]})
        decisions = DecisionStore(store)
        held = decisions.current(rid, head, "fulltext")
        # The abstract stage now says the record is out of scope under the question the research is really asking.
        decisions.record(rid, head, "both_blocks_missing")
        outcome = decisions.work_outcome(rid, store.source(head)["work_id"])
        stale = decisions.is_stale(held)
    finally:
        client.__exit__(None, None, None)
    assert run["status"] == "completed" and held["reason_code"] == "not_read_yet" and stale
    assert outcome["stage"] == "abstract" and outcome["reason_code"] == "both_blocks_missing"


# ---- review: a lookup that did not answer ----------------------------------------------------------------

def test_a_lookup_that_did_not_answer_is_asked_again_by_the_next_run_and_the_work_can_settle(tmp_path, monkeypatch):
    """The lookup rows are the research's history, not the run's: an old 429 must neither stop the next run from
    looking the DOI up again nor keep the work undecided for ever."""
    doi = "10.1/oa.1"

    class Limited(Transport):
        limited = True

        def __call__(self, request):
            if request.url.host == "api.unpaywall.org" and self.limited:
                self.lookups.append(doi)
                return httpx.Response(429)
            return super().__call__(request)

    transport = Limited([work(1)])  # a closed record: no open link, so the DOI lookup is its only route
    app = app_for(tmp_path, monkeypatch, transport, Fetcher({}))
    client = client_of(app)
    try:
        rid, _, _, _ = discover(client)
        _, first = wait_for_retrieval(client, rid)
        store = app.state.store
        head = records_of(store, rid)["W1"]
        undecided = (work_steps(store, first["id"])[head]["error_code"], fulltext_codes(store, rid))
        transport.limited = False  # Unpaywall answers now: it holds no copy
        second = client.post(f"/api/researches/{rid}/runs", json={"kind": "fulltext_fetch"}).json()["id"]
        wait(client, rid, second)
        codes = fulltext_codes(store, rid)
    finally:
        client.__exit__(None, None, None)
    assert undecided == ("fetch_not_settled", {"W1": None})
    assert transport.lookups == [doi, doi], "the next run did not look the DOI up again"
    assert codes == {"W1": "no_fulltext"}


def test_a_record_whose_own_link_refused_still_gets_the_verified_copy_of_another_version(tmp_path, monkeypatch):
    """A 403 on the record's own link opens the DOI lookup inside `_acquire_pdf`; the retrieval run's lookup must be
    the one that may open a row for another version there too, or the owner's decision 3 never applies to the
    records most likely to need it."""
    own, copy = "https://example.org/w1.pdf", "https://example.org/w1-submitted.pdf"
    transport = Transport([work(1, pdf_url=own)], unpaywall("10.1/oa.1", copy, "submittedVersion"))
    fetcher = Fetcher({own: REFUSED, copy: ok()})
    app = app_for(tmp_path, monkeypatch, transport, fetcher)
    client = client_of(app)
    try:
        rid, _, _, _ = discover(client)
        _, run = wait_for_retrieval(client, rid)
        store = app.state.store
        head = records_of(store, rid)["W1"]
        output = json.loads(work_steps(store, run["id"])[head]["output_json"])
        opened = store.source(output["read_version"])
        text = (store.has_pdf_text(opened["id"]), store.has_pdf_text(head))
    finally:
        client.__exit__(None, None, None)
    assert output["route"] == "lookup_version" and output["code"] == "not_read_yet"
    assert opened["id"] != head and opened["version_label"] == "submittedVersion"
    assert text == (True, False) and transport.lookups == ["10.1/oa.1"]


def test_a_work_read_through_its_own_link_leaves_no_lookup_step_that_never_runs(tmp_path, monkeypatch):
    fetcher = Fetcher({"https://example.org/w1.pdf": ok()})
    app = app_for(tmp_path, monkeypatch, Transport([work(1, pdf_url="https://example.org/w1.pdf")]), fetcher)
    client = client_of(app)
    try:
        rid, _, _, _ = discover(client)
        _, run = wait_for_retrieval(client, rid)
        kinds = [row["kind"] for row in app.state.store.run_steps(run["id"])]
    finally:
        client.__exit__(None, None, None)
    assert "pdf_other_copy" not in kinds, kinds


def test_a_second_research_with_the_same_record_reads_the_version_row_the_first_one_opened(tmp_path, monkeypatch):
    """Records are shared by every research; a row one research's lookup opened has to join the next research too, or
    that research says `no_fulltext` about a work whose text is in the library."""
    copy = "https://example.org/w1-submitted.pdf"
    transport = Transport([work(1)], unpaywall("10.1/oa.1", copy, "submittedVersion"))
    fetcher = Fetcher({copy: ok()})
    app = app_for(tmp_path, monkeypatch, transport, fetcher)
    client = client_of(app)
    try:
        first, _, _, _ = discover(client)
        wait_for_retrieval(client, first)
        second, _, _, _ = discover(client)
        _, run = wait_for_retrieval(client, second)
        store = app.state.store
        plan = step_output(store, run["id"], "fulltext_plan")
        outputs = [json.loads(row["output_json"]) for row in work_steps(store, run["id"]).values()]
    finally:
        client.__exit__(None, None, None)
    # Either the plan already saw the text or the work step found the row; in neither case is the work without text.
    assert plan["already_text"] == 1 or [o["code"] for o in outputs] == ["not_read_yet"], (plan, outputs)
    assert fetcher.calls.count(copy) == 1
