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

from deixis.domain import rules
from deixis.storage import db
from deixis.workflow import prisma_s
from deixis.workflow.store import Store
from test_probes import Probe
from test_queue import body, provider_record
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


@pytest.mark.parametrize("field", ["channels", "irrigation"])
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


def test_the_search_table_holds_each_group_once_with_every_page_and_the_chain_apart(store):
    lib = Search(store)
    searched(lib)
    lib.page("chain:backward:0", lib.records(1), query="chain:backward:W1", stop="exhausted")
    data = lib.export()
    table = data["search_table"]
    assert [(g["kind"], g["provider"], g["query_text"], g["pages"]) for g in table] == [
        ("keyword", "openalex", "SYNTHETIC query", 2), ("keyword", "arxiv", "SYNTHETIC second", 1),
        ("chain", "openalex", "chain:backward:W1", 1)]
    pages = store.conn.execute("SELECT id FROM search_runs WHERE research_id = ?", (lib.rid,)).fetchall()
    assert sorted(sid for g in table for sid in g["search_run_ids"]) == sorted(row[0] for row in pages)
    assert table[0]["request"]["filter"] == "type:article" and table[0]["unread_by_limit"] == 40
    assert item(data, 15)["status"] == "reported"  # a read limit leaves records unread; it is a limit, not a failure
    assert item(data, 9)["values"]["unread_by_read_limit"] == 40


def test_a_groups_end_is_its_highest_pages_even_when_the_clock_says_otherwise(store):
    # Page 1 failed and page 0 completed, but page 0's stamp is the later one: the group still ended on page 1, so item
    # 15 is incomplete; the first and last read are the earliest and latest stamps.
    lib = Search(store)
    first = lib.page("search:0", lib.records(2), number=0)
    second = lib.page("search:0", [], number=1, status="rate_limited", stop="page_failed")
    store.conn.execute("UPDATE search_runs SET retrieved_at = ? WHERE id = ?", ("2026-09-25T10:00:05.000Z", first))
    store.conn.execute("UPDATE search_runs SET retrieved_at = ? WHERE id = ?", ("2026-09-25T10:00:01.000Z", second))
    data = lib.export()
    (group,) = data["search_table"]
    assert (group["end_status"], group["stop_reason"], group["search_run_ids"]) == ("rate_limited", "page_failed",
                                                                                     [first, second])
    assert (group["first_retrieved_at"], group["last_retrieved_at"]) == ("2026-09-25T10:00:01.000Z",
                                                                         "2026-09-25T10:00:05.000Z")
    assert item(data, 15)["status"] == "incomplete"
    assert item(data, 15)["values"]["keyword"]["read_then_stopped"] == 1


def test_the_markdown_names_every_stored_page_of_each_group_as_the_json_does(store):
    lib = Search(store)
    searched(lib)
    lib.page("chain:backward:0", lib.records(1), query="chain:backward:W1", stop="exhausted")
    data = lib.export()
    text = prisma_s.markdown(data)
    listed = {int(m.group(1)): re.findall(r"`search_runs:(\S+?)`", m.group(2))
              for m in re.finditer(r"^- Group (\d+): (.*)$", text, re.M)}
    assert listed == {g["group"]: g["search_run_ids"] for g in data["search_table"]}
    assert all(resolve(store, f"search_runs:{sid}") == 1 for ids in listed.values() for sid in ids)
    assert sum(len(ids) for ids in listed.values()) == store.conn.execute(
        "SELECT COUNT(*) FROM search_runs WHERE research_id = ?", (lib.rid,)).fetchone()[0]


def test_a_group_that_read_nothing_and_one_that_stopped_after_reading_make_item_15_incomplete(store):
    lib = Search(store, "irrigation")
    searched(lib)
    lib.page("search:2", [], query="SYNTHETIC limited", status="rate_limited", stop="page_failed")
    lib.page("search:3", lib.records(2), query="SYNTHETIC stopped", number=0)
    lib.page("search:3", [], query="SYNTHETIC stopped", number=1, status="rate_limited", stop="page_failed")
    found = item(lib.export(), 15)
    assert found["status"] == "incomplete"
    keyword = found["values"]["keyword"]
    assert (keyword["not_complete"], keyword["nothing_read"], keyword["read_then_stopped"]) == (2, 1, 1)
    assert keyword["read_then_stopped_records"] == 2
    assert keyword["nothing_read_by_status"] == {"rate_limited": 1}
    assert "1 read nothing" in found["text"] and "stopped after reading 2 records" in found["text"]


def test_chaining_switched_off_is_not_performed_and_a_bioRxiv_query_is_still_a_separate_search(store):
    lib = Search(store)
    store.freeze_protocol(lib.rid, 1, body(lib.field) | {"citation_chaining": {"enabled": False}}, reason="SYNTHETIC")
    lib.page("search:0", lib.records(1), provider="biorxiv", stop="exhausted")
    data = lib.export()
    five, two = item(data, 5), item(data, 2)
    assert five["status"] == "not_performed" and five["trace"][-1].startswith("protocol_records:")
    assert two["status"] == "not_performed" and "each database was queried separately" in two["text"].lower()
    assert "OpenAlex" in two["values"]["biorxiv"]
    assert item(data, 1)["values"]["databases"] == [{"provider": "biorxiv", "access": "direct API", "through": "openalex"}]


def test_a_chain_that_ran_is_reported_from_its_summary_step(store):
    lib = Search(store, "irrigation")
    lib.page("search:0", lib.records(1), stop="exhausted")
    lib.page("chain:backward:0", lib.records(1), query="chain:backward:W1", stop="exhausted")
    step = store.step(lib.run, "chain_summary", "code:chain_summary")
    store.finish_step(step["id"], "succeeded", output={"seeds": {"code": 1}, "requests": {"failed": 0}, "new_works": 1})
    five = item(lib.export(), 5)
    assert five["status"] == "reported" and f"run_steps:{step['id']}" in five["trace"]


def test_brought_works_are_other_methods_and_the_expansion_round_is_a_search_round(store):
    lib = Search(store)
    lib.card([{"provider_id": "openalex", "query_text": "SYNTHETIC query", "origin": "model"}])
    lib.page("search:0", lib.records(1), stop="exhausted")
    lib.page("search:1", lib.records(1), query="SYNTHETIC expanded", stop="exhausted")  # second round
    data = lib.export()
    assert item(data, 7)["status"] == "not_recorded" and item(data, 7)["text"] == "No other source was recorded in DEIXIS."
    assert [(g["round"], g["origin"]) for g in data["search_table"]] == [(1, "model"), (2, "expansion")]
    assert item(data, 8)["values"]["rounds"] == [1, 2]
    uploaded = store.create_upload_source("SYNTHETIC my own notes")
    store.add_to_corpus(lib.rid, uploaded, "user_upload", candidate=False)
    seven = item(lib.export(), 7)
    assert seven["status"] == "reported" and seven["values"]["brought"] == {"user_upload": 1}
    assert seven["trace"] == [f"corpus_memberships:{lib.rid}/{uploaded}"]


def test_limits_are_listed_without_a_justification_and_one_run_is_no_update(store):
    lib = Search(store, "irrigation")
    searched(lib)
    data = lib.export()
    nine, twelve = item(data, 9), item(data, 12)
    assert nine["status"] == "incomplete" and "justification is not recorded" in nine["text"]
    assert nine["values"]["read_limit_per_query"] == [400]
    assert twelve["status"] == "not_recorded" and "not updated" not in twelve["text"].lower()
    assert twelve["text"] == "No update run was recorded in DEIXIS."
    lib.revise()
    lib.page("search:0", lib.records(1), stop="exhausted", run=lib.new_run("discovery"))
    twelve = item(lib.export(), 12)
    assert twelve["status"] == "incomplete" and "1 earlier question revisions" in twelve["text"]


def test_deduplication_counts_rows_hits_and_leaves_distinct_provider_records_not_recorded(store):
    lib = Search(store)
    same = [provider_record("W-a", "SYNTHETIC one paper", "10.9999/dedup.1"),
            provider_record("W-b", "SYNTHETIC one paper again", "10.9999/dedup.1")]
    lib.page("search:0", same, stop="exhausted")
    sixteen = item(lib.export(), 16)
    assert sixteen["status"] == "reported"
    values = sixteen["values"]
    assert values["rows_returned"] == 2 and values["tracked_candidate_hits"] == 1
    assert values["distinct_returned_provider_records"] is None and "not recorded" in sixteen["text"]
    assert all(rule in sixteen["text"] for rule in ("D46", "D48", "D72"))
    # Each aggregate is a re-runnable count.
    by_table = {a["table"]: a["count"] for a in sixteen["aggregates"]}
    assert by_table["corpus_memberships"] == store.conn.execute(
        "SELECT COUNT(*) FROM corpus_memberships WHERE research_id = ? AND removed_at IS NULL", (lib.rid,)).fetchone()[0]
    assert by_table["candidate_hits"] == store.conn.execute(
        "SELECT COUNT(*) FROM candidate_hits WHERE research_id = ? AND scope_revision = 1", (lib.rid,)).fetchone()[0]


def test_code_facts_carry_their_pinned_source_and_a_changed_file_is_not_verified(store, tmp_path, monkeypatch):
    lib = Search(store, "irrigation")
    searched(lib)
    data = lib.export()
    for number in (3, 10):
        found = item(data, number)
        assert found["status"] == "not_performed" and found["trace"] == []
        source = found["code_source"]
        assert source["verified"] is True and re.fullmatch(r"[0-9a-f]{64}", source["sha256"])
        assert source["code_version"].startswith("deixis/") and source["source"].startswith("backend/deixis/")
    assert item(data, 3)["code_source"]["fact"] == "no_registry_connector"
    # A module loaded from a file that changed on disk afterwards: its code origin is no longer shown as verified.
    copy = tmp_path / "registry_copy.py"
    copy.write_text("SYNTHETIC = 1\n")
    monkeypatch.setitem(prisma_s.CODE_SOURCES, "registry", prisma_s._pin(copy, "no_registry_connector"))
    copy.write_text("SYNTHETIC = 2\n")
    three = item(lib.export(), 3)
    assert three["code_source"]["verified"] is False and "not verified" in three["text"]


def test_the_markdown_opens_with_the_statement_and_says_not_performed_and_not_recorded_apart(store, monkeypatch):
    monkeypatch.setenv("OPENALEX_API_KEY", "SYNTHETIC-SECRET-KEY-123")
    lib = Search(store)
    searched(lib)
    data = lib.export()
    text = prisma_s.markdown(data)
    assert text.splitlines()[2] == prisma_s.STATEMENT
    assert text.count("PRISMA-compliant") == 1 and "This is not a PRISMA-compliant review" in text
    assert "Not performed by DEIXIS" in text and "**Status:** Not recorded" in text
    assert text.count("## ") == 16 + 2  # the items, the search table and the flow counts
    assert "SYNTHETIC-SECRET-KEY-123" not in text and "SYNTHETIC-SECRET-KEY-123" not in json.dumps(data)
    # Two exports of the same state differ only in when they were made.
    again = lib.export()
    assert {**data, "generated_at": None} == {**again, "generated_at": None}
    strip = lambda md: "\n".join(line for line in md.splitlines() if not line.startswith("- Generated:"))
    assert strip(prisma_s.markdown(data)) == strip(prisma_s.markdown(again))


def test_the_endpoint_gives_both_formats_and_refuses_a_legacy_research(tmp_path, monkeypatch):
    app, client = quiet_app(tmp_path, monkeypatch)
    try:
        store = app.state.store
        lib = Search(store)
        searched(lib)
        as_json = client.get(f"/api/researches/{lib.rid}/prisma-s?format=json")
        as_md = client.get(f"/api/researches/{lib.rid}/prisma-s?format=md")
        legacy = Search(store, workflow="legacy")
        refused = client.get(f"/api/researches/{legacy.rid}/prisma-s?format=md")
    finally:
        client.__exit__(None, None, None)
    assert as_json.status_code == 200 and len(as_json.json()["items"]) == 16
    assert as_json.headers["content-disposition"].endswith('.json"')
    assert as_md.status_code == 200 and as_md.headers["content-type"].startswith("text/markdown")
    assert as_md.text.splitlines()[2] == prisma_s.STATEMENT
    assert refused.status_code == 422


# ---- decision 9: the depth text's limits --------------------------------------------------------------------------


def test_effort_limits_come_from_the_rules_and_follow_a_changed_constant(tmp_path, monkeypatch):
    app, client = quiet_app(tmp_path, monkeypatch)
    try:
        first = client.get("/api/effort-limits").json()
        monkeypatch.setitem(rules.SW_READ_LIMIT, "quick", 123)
        changed = client.get("/api/effort-limits").json()
    finally:
        client.__exit__(None, None, None)
    assert first["search_workflow"] == "sw"
    assert first["efforts"]["standard"] == {
        "read": rules.SW_READ_LIMIT["standard"], "abstracts": rules.ABSTRACT_READ_LIMIT["standard"],
        "fetch": rules.FULLTEXT_WORK_LIMIT["standard"], "reads": rules.FULLTEXT_READ_LIMIT["standard"],
        "runs": rules.FULLTEXT_RUNS, "chain_seeds": rules.CHAIN_SEEDS,
        "chain_abstracts": rules.CHAIN_ABSTRACT_READ["standard"],
        "passages": rules.TEST_EFFORT_BUDGETS["standard"].max_answer_passages}
    assert changed["efforts"]["quick"]["read"] == 123


def test_a_legacy_server_says_so_and_gives_no_sw_numbers(tmp_path, monkeypatch):
    assert rules.effort_limits("legacy") == {"search_workflow": "legacy", "efforts": None}
