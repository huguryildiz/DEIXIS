"""Exact aliases, version relations and announcement history."""

import json
import sqlite3

import pytest

from deixis.providers import openalex
from deixis.storage import db
from deixis.workflow.watch import check as policy
from tests.watch_helpers import api, watch_offline, create, now_check, turn, read, page, work, record, add_included


@pytest.mark.parametrize("value,expected", [("2026-02-28", "2026-02-28"), ("2026-02-30", None),
    ("2026", None), (2026, None), (None, None), ("2026-2-01", None), ("2026-02-28T00:00:00Z", None)])
def test_publication_date_exact_real_iso(value, expected):
    assert openalex.publication_date_of({"publication_date": value}) == expected


def test_aliases_never_name_titles_or_family_dois():
    first = record("arxiv", "2301.00001v1", doi="10.48550/arxiv.2301.00001", merge_by_doi=False,
                   identifiers={"published_doi": "https://doi.org/10.1000/published"})
    second = record("arxiv", "2301.00001v2", doi=first["doi"], merge_by_doi=False)
    assert set(first["aliases"]).isdisjoint(second["aliases"])
    assert first["aliases"] == ["arxiv:2301.00001v1"]
    assert {r["relation"] for r in first["relations"]} == {"version_family_doi", "names_published_doi"}
    oa = record("openalex", "W1", doi=first["doi"])
    assert oa["aliases"] == ["openalex:W1"] and oa["relations"][0]["relation"] == "version_family_doi"
    assert record("biorxiv", "W1")["aliases"] == ["biorxiv:W1", "openalex:W1"]


def inject(api, command, records):
    # Completion applies already-normalized records exactly as a provider read would supply them.
    # No immutability trigger is relaxed: this creates a new immutable read before completion.
    from deixis.providers.common import SearchOutcome
    check = api.watches.check(api.rid, command["check_id"])
    unit = json.loads(check["config_json"])["units"][0]
    step = api.store.step(command["run_id"], "watch:0:page:1", "watch_read")
    api.store.start_step(step["id"])
    api.watches.record_read(check, unit, 1, step, SearchOutcome("completed", None, "SYNTHETIC injected read", "keyless"),
        records, len(records), 0, {"contract_id": unit["contract_id"], "adapter_revision": unit["adapter_revision"]}, None, None, None)
    turn(api)


def test_doi_arrives_later_no_reannouncement(api):
    first = create(api); turn(api)
    api.state.payload = page(work(doi="https://doi.org/10.1000/late"))
    second = now_check(api, first["watch_id"]); turn(api)
    assert read(api, second)["counts"]["new"] == 0 and not api.watches.items(api.rid)
    assert api.conn.execute("SELECT count(*) FROM watch_seen").fetchone()[0] == 1
    assert api.conn.execute("SELECT alias FROM watch_seen_alias WHERE alias='doi:10.1000/late'").fetchone()


def test_same_record_found_by_both_kinds_announced_once(api):
    add_included(api, "SEED")
    api.state.payload = page()
    query_watch = create(api); turn(api)
    citing_watch = create(api, "citing_works"); turn(api)
    api.state.payload = page(work("NEW"))
    query_check = now_check(api, query_watch["watch_id"]); turn(api)
    citing_check = now_check(api, citing_watch["watch_id"]); turn(api)
    items = api.watches.items(api.rid)
    assert len(items) == 1 and read(api, citing_check)["counts"]["new"] == 0
    assert {f["kind"] for f in json.loads(items[0]["found_by_json"])} == {"protocol_queries", "citing_works"}


def test_exact_doi_merges_seen_rows_keeps_item_and_dismissal(api):
    api.state.payload = page()
    first = create(api); turn(api)
    second = now_check(api, first["watch_id"])
    inject(api, second, [record("openalex", "A", doi="10.1000/join"), record("openalex", "B")])
    items = api.watches.items(api.rid)
    oldest = min(items, key=lambda i: (i["created_at"], i["id"]))
    api.watches.dismiss(api.rid, oldest["id"], {"expected_status": "new", "reason": "SYNTHETIC dismissed"}, "dismiss-merge")
    third = now_check(api, first["watch_id"])
    inject(api, third, [record("openalex", "B", doi="10.1000/join")])
    saved = api.watches.items(api.rid, None)
    assert len(saved) == 2 and {i["status"] for i in saved} == {"dismissed", "merged"}
    survivor = api.watches.item(api.rid, oldest["id"])
    assert survivor["status"] == "dismissed" and survivor["dismissed_reason"] == "SYNTHETIC dismissed"
    merged = next(i for i in saved if i["status"] == "merged")
    assert merged["merged_into_item_id"] == oldest["id"]
    assert api.conn.execute("SELECT count(*) FROM watch_seen WHERE merged_into IS NULL").fetchone()[0] == 1
    assert read(api, third)["counts"]["new"] == 0
    # Following the newly added DOI again never revives the dismissed item.
    fourth = now_check(api, first["watch_id"])
    inject(api, fourth, [record("biorxiv", "B", doi="10.1000/join")])
    assert len(api.watches.items(api.rid, None)) == 2 and not api.watches.items(api.rid)


def test_arxiv_versions_and_named_publication_stay_separate_with_relations(api):
    first = create(api)
    v1 = record("arxiv", "2301.00001v1", doi="10.48550/arxiv.2301.00001", merge_by_doi=False)
    inject(api, first, [v1])
    second = now_check(api, first["watch_id"])
    v2 = record("arxiv", "2301.00001v2", doi=v1["doi"], merge_by_doi=False,
                identifiers={"published_doi": "10.1000/published"})
    inject(api, second, [v2, record("openalex", "PUBLISHED", doi="10.1000/published")])
    assert api.conn.execute("SELECT count(*) FROM watch_seen WHERE merged_into IS NULL").fetchone()[0] == 3
    items = api.watches.items(api.rid)
    assert len(items) == 2
    assert all(any(r["relation"] == "may_be_version" for r in json.loads(i["relations_json"])) for i in items)
    assert any(r.get("rule") == "preprint_names_published_doi" for i in items for r in json.loads(i["relations_json"]))


def test_suspected_similarity_announces_without_merge(api):
    first = create(api)
    title = "SYNTHETIC communication scheduling experiment"
    inject(api, first, [record("openalex", "OLD", title=title, doi="10.1000/old")])
    second = now_check(api, first["watch_id"])
    inject(api, second, [record("openalex", "NEW", title=title, doi="10.1000/new")])
    assert api.conn.execute("SELECT count(*) FROM watch_seen WHERE merged_into IS NULL").fetchone()[0] == 2
    items = api.client.get(f"/api/researches/{api.rid}/watch-items").json()
    assert len(items) == 1 and items[0]["may_be_version_json"]


def test_library_exact_only_records_all_matching_versions(api):
    # The mapping set, rather than source_versions.doi, is the authority for exact matching.
    for label in ("v1", "v2"):
        source = api.store.create_upload_source("SYNTHETIC " + label)
        api.conn.execute("INSERT INTO identifier_mappings (source_version_id,scheme,value,provider,retrieved_at)"
            " VALUES (?,'doi','10.1000/exact','SYNTHETIC',?)", (source, db.now()))
    first = create(api)
    inject(api, first, [record("openalex", "EXACT", doi="10.1000/exact")])
    seen = api.conn.execute("SELECT origin,record_json FROM watch_seen").fetchone()
    assert seen["origin"] == "in_library" and len(json.loads(seen["record_json"])["source_version_ids"]) == 2
    assert api.watches.items(api.rid) == []


def test_family_doi_is_relation_to_seen_and_library_never_exact(api):
    from dataclasses import replace
    family = "10.48550/arxiv.2301.00001"
    for label in ("v1", "v2"):
        source = api.store.upsert_provider_source("arxiv", replace(openalex._record(work(label, doi=family)),
              provider_record_id="2301.00001" + label, merge_by_doi=False), None)[0]
        api.store.add_to_corpus(api.rid, source, "library", selection_state="included", selection_origin="user")
    first = create(api)
    inject(api, first, [record("arxiv", "2301.00001v1", doi=family, merge_by_doi=False),
                         record("arxiv", "2301.00001v2", doi=family, merge_by_doi=False)])
    second = now_check(api, first["watch_id"])
    inject(api, second, [record("openalex", "FAMILY", doi=family)])
    assert read(api, second)["counts"]["new"] == 1 and read(api, second)["counts"]["already_in_library"] == 0
    relations = json.loads(api.watches.items(api.rid)[0]["relations_json"])
    assert {r.get("against") for r in relations if r["relation"] == "may_be_version"} == {"seen", "library"}
    assert api.conn.execute("SELECT count(*) FROM watch_seen WHERE merged_into IS NULL").fetchone()[0] == 3


def test_notice_separate_and_counterpart_relation_reconciles_after_dismissal(api):
    api.state.payload = page()
    first = create(api); turn(api)
    title = "SYNTHETIC communication scheduling experiment"
    second = now_check(api, first["watch_id"])
    inject(api, second, [record("openalex", "NOTICE", title="Retraction: " + title, doi="10.1000/notice")])
    notice = api.watches.items(api.rid)[0]
    assert notice["kind"] == "notice" and read(api, second)["counts"]["new"] == 0 and read(api, second)["counts"]["notices"] == 1
    api.watches.dismiss(api.rid, notice["id"], {"expected_status": "new", "reason": "SYNTHETIC reason"}, "notice-dismiss")
    third = now_check(api, first["watch_id"])
    inject(api, third, [record("openalex", "PAPER", title=title, doi="10.1000/paper")])
    notice_now = api.watches.item(api.rid, notice["id"])
    assert notice_now["status"] == "dismissed" and notice_now["dismissed_reason"] == "SYNTHETIC reason"
    assert any(r["relation"] == "notice_of" and r["check_id"] == third["check_id"] for r in json.loads(notice_now["relations_json"]))
    paper = api.watches.items(api.rid)[0]
    assert any(r["relation"] == "notice_of" for r in json.loads(paper["relations_json"]))


def test_late_notice_metadata_keeps_first_copy_status_and_kind_history(api):
    api.state.payload = page()
    first = create(api); turn(api)
    second = now_check(api, first["watch_id"])
    inject(api, second, [record("openalex", "LATE", title="SYNTHETIC initial title")])
    item = api.watches.items(api.rid)[0]
    api.watches.dismiss(api.rid, item["id"], {"expected_status": "new", "reason": "SYNTHETIC"}, "late-dismiss")
    third = now_check(api, first["watch_id"])
    inject(api, third, [record("openalex", "LATE", title="Retraction: SYNTHETIC initial title")])
    changed = api.watches.item(api.rid, item["id"])
    assert changed["kind"] == "notice" and changed["status"] == "dismissed"
    assert json.loads(changed["kind_history_json"])[0]["from"] == "new_record"
    assert json.loads(changed["record_json"])["title"] == "SYNTHETIC initial title"
    assert len(api.watches.items(api.rid, None)) == 1


def test_unique_item_blocks_duplicate_and_identity_uncertain_visible(api):
    api.state.payload = page()
    first = create(api); turn(api)
    api.state.payload = page(work("NATIVE"))
    second = now_check(api, first["watch_id"]); turn(api)
    item = api.watches.items(api.rid)[0]
    with pytest.raises(sqlite3.IntegrityError):
        api.conn.execute("INSERT INTO watch_items SELECT 'wit_duplicate',research_id,check_id,seen_id,record_json,kind,"
            "found_by_json,relations_json,kind_history_json,status,merged_into_item_id,dismissed_reason,dismissed_at,"
            "dismiss_key,dismiss_hash,created_at FROM watch_items LIMIT 1")
    shown = api.client.get(f"/api/researches/{api.rid}/watch-items").json()[0]
    assert shown["identity_uncertain"] and shown["first_seen_at"] != shown["record"]["publication_date"]
    assert shown["doi"] is None and shown["landing_url"] and shown["identity_notice"]
