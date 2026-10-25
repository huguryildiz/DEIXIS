"""The PRISMA-S export of an `sw` research and the depth text's limits (slice 20, decisions 8–9).

Searches, records and protocol bodies are SYNTHETIC and from two fields (diffusion channel scheduling, greenhouse
irrigation), written the way the discovery run writes them, without a model or a request. Passing shows which stored
row each item reads and how its status is decided; it says nothing about whether a journal or a librarian would find
the export sufficient, which was not checked.
"""

from __future__ import annotations

import json
import re

import pytest

from deixis.storage import db
from deixis.workflow.search import prisma_s
from deixis.workflow.run.store import Store
from test_probes import Probe
from test_queue import body
from test_queue_api import quiet_app


@pytest.fixture
def store(tmp_path):
    connection = db.connect(tmp_path / "library.sqlite")
    db.migrate(connection)
    yield Store(connection)
    connection.close()


class Search(Probe):
    """A `Probe` whose search pages carry the paging columns an sw read stores (slice 04c)."""

    def page(self, key, records, provider="openalex", query="SYNTHETIC query", status="completed", number=0,
             stop=None, unread=None, total=None, limit=400, run=None, description=None):
        run = run or self.run
        revision = self.store.research(self.rid)["current_scope_revision"]
        step = self.store.step(run, f"{key}:page:{number}", f"provider_search:{provider}")
        return self.store.record_search(
            dict(research_id=self.rid, run_id=run, step_id=step["id"], scope_revision=revision, provider=provider,
                 query_text=query, request_description=description or f"GET https://api.example.org/works search={query!r}"
                 f" filter=type:article sort=relevance per_page=25", access_mode="keyless", status=status,
                 delivery_class=None, result_count=len(records), provider_total=total, page_limit=25, error_json=None,
                 raw_payload_path=None, page_number=number, read_limit=limit, read_total=len(records),
                 stop_reason=stop, unread_count=unread),
            provider, records, None, step["id"], "succeeded", step_output={"status": status})

    def export(self):
        return prisma_s.export(self.store, self.rid)


def item(data, number):
    return next(i for i in data["items"] if i["number"] == number)


def searched(lib):
    """Two keyword queries, one of them paged; nothing incomplete."""
    lib.page("search:0", lib.records(2), number=0, stop=None)
    lib.page("search:0", lib.records(1), number=1, stop="read_limit", unread=40, total=43)
    lib.page("search:1", lib.records(1), provider="arxiv", query="SYNTHETIC second", stop="exhausted")


def resolve(store, entry):
    table, _, key = entry.partition(":")
    if table == "corpus_memberships":
        research_id, _, svid = key.partition("/")
        return store.conn.execute("SELECT COUNT(*) FROM corpus_memberships WHERE research_id = ? AND source_version_id = ?",
                                  (research_id, svid)).fetchone()[0]
    assert table in ("protocol_records", "search_runs", "run_steps", "record_links"), entry
    return store.conn.execute(f"SELECT COUNT(*) FROM {table} WHERE id = ?", (key,)).fetchone()[0]


# ---- the items, their statuses and their traces ------------------------------------------------------------------


@pytest.mark.parametrize("field", ["channels"])
def test_all_sixteen_items_are_filled_with_a_status_and_every_trace_resolves_to_one_row(store, field):
    lib = Search(store, field)
    searched(lib)
    data = lib.export()
    assert data["checklist"] == "PRISMA-S" and data["citation"]["doi"] == "10.1186/s13643-020-01542-z"
    assert [i["number"] for i in data["items"]] == list(range(1, 17))
    assert all(i["status"] in prisma_s.STATUSES and i["text"] and i["name"] == prisma_s.NAMES[i["number"]]
               for i in data["items"])
    for entry in (e for i in data["items"] for e in i["trace"]):
        assert re.fullmatch(r"(protocol_records|search_runs|run_steps|record_links):\S+|corpus_memberships:\S+/\S+",
                            entry)
        assert resolve(store, entry) == 1, entry
    for group in data["search_table"]:
        assert all(resolve(store, f"search_runs:{sid}") == 1 for sid in group["search_run_ids"])
    # Not recorded is never not performed: these four are outside DEIXIS and not recorded.
    assert {i["number"]: i["status"] for i in data["items"] if i["number"] in (4, 6, 11, 14)} == {
        4: "not_recorded", 6: "not_recorded", 11: "not_recorded", 14: "not_recorded"}
    for number in (i["number"] for i in data["items"] if i["status"] == "not_performed"):
        found = item(data, number)
        assert found["trace"] or found["code_source"], number  # a protocol row or a code fact says so


def test_the_endpoint_gives_both_formats(tmp_path, monkeypatch):
    app, client = quiet_app(tmp_path, monkeypatch)
    try:
        store = app.state.store
        lib = Search(store)
        searched(lib)
        as_json = client.get(f"/api/researches/{lib.rid}/prisma-s?format=json")
        as_md = client.get(f"/api/researches/{lib.rid}/prisma-s?format=md")
    finally:
        client.__exit__(None, None, None)
    assert as_json.status_code == 200 and len(as_json.json()["items"]) == 16
    assert as_json.headers["content-disposition"].startswith('attachment; filename="DEIXIS - SYNTHETIC ')
    assert as_json.headers["content-disposition"].endswith("%20-%20PRISMA-S%20-%20r1.json")
    assert as_md.status_code == 200 and as_md.headers["content-type"].startswith("text/markdown")
    assert as_md.text.splitlines()[2] == prisma_s.STATEMENT


# ---- decision 9: the depth text's limits --------------------------------------------------------------------------


# ---- what the frozen protocol planned against what was sent -------------------------------------------------------


def plan(lib, count=4, run=None, provider="openalex"):
    """Freeze `count` planned queries and let `run` name the record the way the discovery run's freeze step does."""
    planned = [{"provider_id": provider, "query_text": f"SYNTHETIC planned {n}"} for n in range(count)]
    record = lib.store.freeze_protocol(lib.rid, 1, body(lib.field) | {"compiled_queries": planned}, reason="SYNTHETIC planned")
    step = lib.store.step(run or lib.run, "protocol", "protocol:freeze")
    lib.store.finish_step(step["id"], "succeeded", output={"protocol_hash": record["hash"]})
    return planned


def dispatches(lib):
    return [(q["query_text"][-1], q["dispatch"]) for q in item(lib.export(), 8)["values"]["planned_queries"]]


def test_a_planned_query_that_was_never_sent_is_marked_not_sent_and_an_unknown_delivery_is_marked_so(store):
    """The protocol freezes every compiled query before the first request; a run stopped after that keeps them all."""
    lib = Search(store)
    planned = plan(lib)
    lib.page("search:0", lib.records(1), query="SYNTHETIC planned 0", stop="exhausted")
    unknown = store.step(lib.run, "search:1", "provider_search:openalex")
    store.finish_step(unknown["id"], "outcome_unknown", error_code="timeout", delivery_class="after_send_unknown")
    refused = store.step(lib.run, "search:2", "provider_search:openalex")
    store.finish_step(refused["id"], "failed", error_code="not_configured", delivery_class="before_send")
    # search:3 has no step of its own: a cancel is written at once while a request may still be on the network.
    data = lib.export()
    values = item(data, 8)["values"]
    assert dispatches(lib) == [("0", "sent"), ("1", "delivery_unknown"), ("2", "not_sent"), ("3", "delivery_unknown")]
    assert values["planned_dispatch"] == {"planned": 4, "sent": 1, "delivery_unknown": 2, "not_sent": 1,
                                         "sent_without_record": 0}
    assert "1 of 4 planned queries" in item(data, 8)["text"]
    assert item(data, 8)["status"] == "incomplete"
    assert "SYNTHETIC planned 3" in prisma_s.markdown(data) and "not_sent" in prisma_s.markdown(data)
    # The frozen record itself is untouched.
    assert [q["query_text"] for q in store.current_protocol(lib.rid, 1)["body"]["compiled_queries"]] == [
        q["query_text"] for q in planned]


def test_a_failed_run_or_one_paused_by_a_restart_never_turns_a_missing_step_into_not_sent(store):
    failed = Search(store)
    plan(failed, 1)
    failed.store.update_run(failed.run, status="failed", pause_reason="disk_full")  # the request may have gone out
    assert dispatches(failed) == [("0", "delivery_unknown")]
    restarted = Search(store)
    plan(restarted, 1)
    restarted.store.update_run(restarted.run, status="paused", pause_reason="backend_restarted")
    restarted.store._event(restarted.rid, "run_paused", {"status": "paused", "pause_reason": "backend_restarted"},
                           restarted.run)
    restarted.store.update_run(restarted.run, status="cancelled", pause_reason=None)  # cancelled after the restart pause
    assert dispatches(restarted) == [("0", "delivery_unknown")]


# ---- item 10 and the vocabulary nobody reviewed -----------------------------------------------------------------


def test_a_fast_path_plan_lists_the_requests_it_sends_by_their_step_keys_and_leaves_its_dropped_queries_out(store):
    """The semantic and Semantic Scholar bulk requests are stored under their own keys, not `search:<index>`; a query
    the fast plan dropped was never meant to be sent and is not a planned request."""
    lib = Search(store)
    compiled = [{"provider_id": "openalex", "query_text": "SYNTHETIC planned 0"},
                {"provider_id": "crossref", "query_text": "SYNTHETIC planned 1"},
                {"provider_id": "semantic_scholar", "query_text": "SYNTHETIC planned 2", "endpoint": "bulk", "sort": "x"}]
    fast = {"version": 1, "semantic": {"provider_id": "openalex", "endpoint": "semantic",
                                       "query_text": "SYNTHETIC planned S", "query_origin": "question"},
            "keywords": [{"index": 0, "query": compiled[0]}], "s2_bulk": compiled[2], "s2_bulk_index": 2,
            "dropped": [{"index": 1, "query": compiled[1], "reason": "openalex_only"}]}
    record = store.freeze_protocol(lib.rid, 1, body(lib.field) | {"compiled_queries": compiled, "fast_path_search": fast},
                                   reason="SYNTHETIC fast")
    step = store.step(lib.run, "protocol", "protocol:freeze")
    store.finish_step(step["id"], "succeeded", output={"protocol_hash": record["hash"]})
    lib.page("search:fast:semantic", lib.records(1), query="SYNTHETIC planned S", stop="exhausted")
    lib.page("search:0", lib.records(1), query="SYNTHETIC planned 0", stop="exhausted")
    lib.page("search:fast:s2_bulk", lib.records(1), provider="semantic_scholar", query="SYNTHETIC planned 2",
             stop="exhausted")
    planned = item(lib.export(), 8)["values"]["planned_queries"]
    assert [(q["arm"], q["query_text"][-1], q["dispatch"], q["recorded"]) for q in planned] == [
        ("semantic", "S", "sent", True), ("keyword", "0", "sent", True), ("s2_bulk", "2", "sent", True)]
    assert item(lib.export(), 8)["status"] == "reported"
