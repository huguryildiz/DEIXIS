"""Slice 13e: the full-text retrieval run fetches several works at once, one request per host, and decides the same.

Three things are checked, all without a network. Equality: the same research fetched one work at a time and several
at a time leaves the same work steps, the same decisions, the same selections and the same lookup rows. Politeness
and bound: through the real downloader, no host is asked twice at once and no more than
`fulltext.FULLTEXT_FETCH_PARALLEL` works are in flight. Stopping: a pause lets the works in flight finish and write
their steps, opens no new one, and the resumed run ends where an uninterrupted one does.

Records are SYNTHETIC and from two fields (irrigation, and the reading run's second field through
`test_abstract_flow.QUESTION`); every transport is mocked and the model is scripted. Passing shows the run behaves as
the slice says, not how much faster it is on real publishers or whether one request per host is polite enough for
them: neither was measured here.
"""

import asyncio
import functools
import json
import random

import httpx

from deixis.documents import fetch as fetch_module
from deixis.storage import db
from deixis.workflow import fulltext
from helpers import make_pdf
from test_abstract_flow import client_of
from test_fulltext_flow import (
    REFUSED, TIMED_OUT, Fetcher, Transport, app_for, discover, named_pdf, ok, step_output, unpaywall, wait,
    wait_for_retrieval, work, work_steps,
)


# ---- a research whose eight works take every route a work can take -----------------------------

def _works():
    """Eight works on three hosts: an open link, a named file, an open preprint of a closed record, a refused link
    whose DOI lookup opens another version, no link at all, a refused link beside an open preprint, and a timeout."""
    preprint = work(3, pdf_url="https://c.example.org/w3-pre.pdf", pdf_version="submittedVersion")
    beside = work(7, pdf_url="https://b.example.org/w7-pre.pdf", pdf_version="submittedVersion")
    beside["locations"] = [{"is_oa": True, "pdf_url": "https://a.example.org/w7.pdf", "version": "publishedVersion"}]
    return [
        work(1, pdf_url="https://a.example.org/w1.pdf"),
        work(2, pdf_url="https://b.example.org/w2.pdf"),
        preprint,
        work(4, pdf_url="https://a.example.org/w4.pdf"),
        work(5),
        work(6, pdf_url="https://c.example.org/w6.pdf"),
        beside,
        work(8, pdf_url="https://b.example.org/w8.pdf"),
    ]


ANSWERS = {
    "https://a.example.org/w1.pdf": ok(),
    "https://b.example.org/w2.pdf": ok(named_pdf("10.1/oa.2")),
    "https://c.example.org/w3-pre.pdf": ok(),
    "https://a.example.org/w4.pdf": REFUSED,
    "https://b.example.org/w4-accepted.pdf": ok(),
    "https://c.example.org/w6.pdf": ok(),
    "https://a.example.org/w7.pdf": REFUSED,
    "https://b.example.org/w7-pre.pdf": ok(),
    "https://b.example.org/w8.pdf": TIMED_OUT,
}
# Longer waits for the works planned first, so works fetched side by side finish in another order than planned.
DELAYS = {url: 0.01 * (len(ANSWERS) - position) for position, url in enumerate(ANSWERS)}


class SlowFetcher(Fetcher):
    """The scripted fetcher, with a wait per URL before it answers."""

    async def __call__(self, url):
        await asyncio.sleep(DELAYS.get(url, 0.005))
        return await super().__call__(url)


def _transport():
    return Transport(_works(), unpaywall("10.1/oa.4", "https://b.example.org/w4-accepted.pdf", "acceptedVersion"))


# ---- what a run leaves behind, with every generated identifier replaced by a stable name --------

def _names(store, rid):
    """A stable name for every identifier the snapshot meets: records by title and version, the rest by owner."""
    conn, names = store.conn, {}
    versions = conn.execute(
        "SELECT s.id, s.work_id, s.title, s.version_label FROM source_versions s JOIN corpus_memberships m"
        " ON m.source_version_id = s.id WHERE m.research_id = ?", (rid,)).fetchall()
    for row in versions:
        names[row["id"]] = f"{row['title']}|{row['version_label']}"
    for row in versions:
        names.setdefault(row["work_id"], "work|" + min(r["title"] for r in versions if r["work_id"] == row["work_id"]))
    for row in conn.execute("SELECT s.id, s.operation_key, r.kind FROM run_steps s JOIN runs r ON r.id = s.run_id"
                            " WHERE r.research_id = ?", (rid,)):
        names[row["id"]] = f"{row['kind']}:{_key(row['operation_key'], names)}"
    svids = [row["id"] for row in versions]
    marks = ",".join("?" * len(svids))
    for row in conn.execute(f"SELECT id, source_version_id, sha256 FROM source_assets WHERE source_version_id IN ({marks})",
                            svids):
        names[row["id"]] = f"asset|{names[row['source_version_id']]}|{row['sha256']}"
    for row in conn.execute("SELECT id, source_version_id, provider FROM pdf_discovery_runs WHERE research_id = ?"
                            " ORDER BY rowid", (rid,)):
        names[row["id"]] = f"lookup|{names[row['source_version_id']]}|{row['provider']}"
    for row in conn.execute(f"SELECT id, source_version_id, provider, candidate_url FROM pdf_candidates"
                            f" WHERE source_version_id IN ({marks})", svids):
        names[row["id"]] = f"candidate|{names[row['source_version_id']]}|{row['provider']}|{row['candidate_url']}"
    names[rid] = "research"
    return names


def _key(operation_key, names):
    """An operation key with the record identifiers inside it named, as in `fulltext_work:<head>`."""
    return ":".join(names.get(part, part) for part in operation_key.split(":"))


def _canonical(value, names):
    if isinstance(value, str):
        if value in names:
            return names[value]
        if value[:1] in "{[":
            try:
                return _canonical(json.loads(value), names)
            except ValueError:
                return value
        return value
    if isinstance(value, dict):
        return {key: _canonical(item, names) for key, item in value.items()
                if key != "id" and not key.endswith("_at") and key != "rowid"}
    if isinstance(value, list):
        return [_canonical(item, names) for item in value]
    return value


def _rows(store, sql, args, names):
    rows = [_canonical(dict(row), names) for row in store.conn.execute(sql, args)]
    for row in rows:
        if "operation_key" in row:
            row["operation_key"] = _key(row["operation_key"], names)
    return rows


def _by_record(rows):
    """Rows sorted by the record they belong to, keeping the order in which each record's own rows were written."""
    return sorted(rows, key=lambda row: json.dumps(row.get("source_version_id"), sort_keys=True))


def snapshot(store, rid, run_id):
    """Everything a retrieval run wrote, identifiers made stable, in an order that does not depend on timing.

    A record's own rows keep the order they were written in; rows of different records are sorted, because two
    works fetched side by side may finish in either order and nothing one work writes depends on another's.
    """
    names = _names(store, rid)
    steps = {row["operation_key"]: row for row in _rows(
        store, "SELECT kind, operation_key, status, error_code, output_json, error_json FROM run_steps"
               " WHERE run_id = ?", (run_id,), names)}
    return {
        "steps": steps,
        "decisions": _by_record(_rows(
            store, "SELECT source_version_id, stage, outcome, reason_code, decided_by, next_step, note, scope_revision,"
                   " step_id, superseded_at IS NULL AS open FROM stage_decisions WHERE research_id = ? ORDER BY rowid",
            (rid,), names)),
        "selections": _by_record(_rows(
            store, "SELECT source_version_id, state, origin, proposal, version FROM selections WHERE research_id = ?"
                   " ORDER BY rowid", (rid,), names)),
        "lookups": _by_record(_rows(
            store, "SELECT source_version_id, provider, query_text, status, result_count, http_status, error_code"
                   " FROM pdf_discovery_runs WHERE research_id = ? ORDER BY rowid", (rid,), names)),
        "candidates": sorted(_rows(
            store, "SELECT c.* FROM pdf_candidates c JOIN corpus_memberships m ON m.source_version_id ="
                   " c.source_version_id WHERE m.research_id = ?", (rid,), names), key=lambda r: json.dumps(r, sort_keys=True)),
        "versions": sorted(_rows(
            store, "SELECT s.work_id, s.title, s.version_label, s.doi, s.oa_pdf_url, s.oa_pdf_version FROM source_versions s"
                   " JOIN corpus_memberships m ON m.source_version_id = s.id WHERE m.research_id = ?", (rid,), names),
            key=lambda r: json.dumps(r, sort_keys=True)),
        "events": sorted(json.dumps(row, sort_keys=True) for row in _rows(
            store, "SELECT type, payload_json FROM events WHERE research_id = ? AND run_id = ?", (rid, run_id), names)),
    }


def _retrieve(tmp_path, monkeypatch, parallel):
    monkeypatch.setattr(fulltext, "FULLTEXT_FETCH_PARALLEL", parallel, raising=False)
    # The same identifiers for the same discovery run, so ties the ranking breaks by identifier fall the same way
    # in both researches and the two retrieval plans are the same list in the same order.
    monkeypatch.setattr(db, "secrets", random.Random(13))
    fetcher = SlowFetcher(ANSWERS)
    app = app_for(tmp_path, monkeypatch, _transport(), fetcher, overlap=False)
    client = client_of(app)
    try:
        rid, _, _, _ = discover(client)
        _, run = wait_for_retrieval(client, rid)
        return run, snapshot(app.state.store, rid, run["id"]), sorted(fetcher.calls)
    finally:
        client.__exit__(None, None, None)


def test_works_fetched_side_by_side_leave_what_works_fetched_one_by_one_leave(tmp_path, monkeypatch):
    """Equality (a): the same research, one work at a time and four at a time, writes the same rows."""
    one_run, one, one_calls = _retrieve(tmp_path / "one", monkeypatch, 1)
    four_run, four, four_calls = _retrieve(tmp_path / "four", monkeypatch, 4)
    assert one_run["status"] == four_run["status"] == "completed"
    # The scenario reaches every route it was built for, so the comparison below is not of two empty runs.
    summary = one["steps"]["fulltext_summary"]["output_json"]
    assert summary["routes"] == {"lookup_version": 1, "none": 1, "record_link": 3, "work_version": 2}
    assert summary["not_settled"] == 1 and summary["no_fulltext"] == 1 and summary["fetched"] == 6
    assert one_calls == four_calls
    for part in one:
        assert one[part] == four[part], part


# ---- one request per host, at most the bound in flight, through the real downloader ------------

HOSTS = ("h1.example.org", "h2.example.org", "h3.example.org", "h4.example.org", "h5.example.org", "h6.example.org")


class Hosts:
    """A mocked web behind the real downloader: counts what is in flight per host and overall."""

    def __init__(self, delay=0.05):
        self.delay, self.now, self.most, self.total, self.most_total = delay, {}, {}, 0, 0
        self.requests = []

    async def __call__(self, request):
        host = request.headers["host"]
        self.requests.append(host)
        self.now[host] = self.now.get(host, 0) + 1
        self.most[host] = max(self.most.get(host, 0), self.now[host])
        self.total += 1
        self.most_total = max(self.most_total, self.total)
        try:
            await asyncio.sleep(self.delay)
            if request.url.path == "/moved.pdf":
                # A redirect to another host takes that host's gate, not the first one's.
                return httpx.Response(302, headers={"location": "https://h3.example.org/landed.pdf"})
            return httpx.Response(200, content=make_pdf([f"SYNTHETIC page of {host}{request.url.path}"]))
        finally:
            self.now[host] -= 1
            self.total -= 1


def test_no_host_is_asked_twice_at_once_and_no_more_than_the_bound_are_in_flight(tmp_path, monkeypatch):
    """Parallelism (b): several hosts at once, never two requests to one host, never more than the bound."""
    async def public(host, port):
        return ["93.184.216.34"]

    monkeypatch.setattr(fetch_module, "_resolve", public)
    web = Hosts()
    downloader = httpx.AsyncClient(transport=httpx.MockTransport(web))
    fetcher = functools.partial(fetch_module.fetch_pdf, client=downloader)
    # Nine works on six hosts: three on h1, two on h2, one link that is moved from h4 to h3.
    urls = ["https://h1.example.org/a.pdf", "https://h1.example.org/b.pdf", "https://h1.example.org/c.pdf",
            "https://h2.example.org/a.pdf", "https://h2.example.org/b.pdf", "https://h3.example.org/a.pdf",
            "https://h4.example.org/moved.pdf", "https://h5.example.org/a.pdf", "https://h6.example.org/a.pdf"]
    monkeypatch.setattr(fulltext, "FULLTEXT_WORK_LIMIT", dict(fulltext.FULLTEXT_WORK_LIMIT, quick=len(urls)))
    app = app_for(tmp_path, monkeypatch, Transport([work(n + 1, pdf_url=url) for n, url in enumerate(urls)]), fetcher, overlap=False)
    client = client_of(app)
    try:
        rid, _, _, _ = discover(client)
        _, run = wait_for_retrieval(client, rid)
        summary = step_output(app.state.store, run["id"], "fulltext_summary")
    finally:
        client.__exit__(None, None, None)
    assert run["status"] == "completed" and summary["fetched"] == len(urls)
    assert sorted(web.requests) == sorted([*(url.split("/")[2] for url in urls), "h3.example.org"])
    assert max(web.most.values()) == 1, web.most
    parallel = getattr(fulltext, "FULLTEXT_FETCH_PARALLEL", 1)
    assert web.most_total <= parallel
    assert parallel == 1 or web.most_total > 1


# ---- a pause lets the works in flight finish and opens no new one -------------------------------

def test_a_pause_lets_the_works_in_flight_finish_and_the_resumed_run_ends_like_an_uninterrupted_one(tmp_path, monkeypatch):
    """Stopping (c): the pause is seen before the next work is sent; what was sent finishes and writes its step."""
    urls = [f"https://{'abc'[n % 3]}.example.org/w{n}.pdf" for n in range(1, 9)]
    answers = {url: ok() for url in urls}
    monkeypatch.setattr(fulltext, "FULLTEXT_WORK_LIMIT", dict(fulltext.FULLTEXT_WORK_LIMIT, quick=len(urls)))

    def run_once(path, pause_at):
        fetcher = SlowFetcher(answers)
        app = app_for(path, monkeypatch, Transport([work(n, pdf_url=url) for n, url in enumerate(urls, 1)]), fetcher, overlap=False)

        def hook(fetcher, url):
            if pause_at and len(fetcher.calls) == pause_at:
                row = app.state.store.conn.execute(
                    "SELECT id FROM runs WHERE kind = 'fulltext_fetch' AND status = 'running'").fetchone()
                if row:
                    app.state.store.update_run(row["id"], status="pause_requested", pause_reason="user_requested")

        fetcher.hook = hook
        client = client_of(app)
        try:
            rid, _, _, _ = discover(client)
            _, first = wait_for_retrieval(client, rid)
            store = app.state.store
            at_pause = {head: step["status"] for head, step in work_steps(store, first["id"]).items()}
            asked = len(fetcher.calls)
            if first["status"] == "paused":
                fetcher.hook = None
                client.post(f"/api/runs/{first['id']}/resume")
                _, first_after = wait(client, rid, first["id"])
            else:
                first_after = first
            summary = step_output(store, first["id"], "fulltext_summary")
            return first, first_after, at_pause, asked, summary, sorted(fetcher.calls)
        finally:
            client.__exit__(None, None, None)

    paused, resumed, at_pause, asked, summary, calls = run_once(tmp_path / "paused", pause_at=2)
    _, whole, _, _, uninterrupted, whole_calls = run_once(tmp_path / "whole", pause_at=None)
    assert paused["status"] == "paused" and paused["pause_reason"] == "user_requested"
    # Every work that was sent finished and wrote its step, and no work was opened after the pause was seen.
    assert set(at_pause.values()) == {"succeeded"} and len(at_pause) == asked
    assert asked <= max(2, getattr(fulltext, "FULLTEXT_FETCH_PARALLEL", 1))
    assert resumed["status"] == whole["status"] == "completed"
    # The resumed run asked nothing twice and reports what an uninterrupted run reports.
    assert calls == whole_calls == sorted(urls)
    assert summary == uninterrupted
