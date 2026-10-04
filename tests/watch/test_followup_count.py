"""SYNTHETIC counts: surviving records, not notices, checks or watch state."""

from tests.watch.watch_helpers import api, watch_offline, create, now_check, turn, page, work


def counts(api):
    return {row["id"]: row["followup_new"] for row in api.store.list_researches()}


def test_followup_new_is_zero_without_watches(api):
    assert counts(api)[api.rid] == 0
    listing = api.client.get("/api/researches")
    assert listing.status_code == 200
    assert listing.json()[0]["followup_new"] == 0


def test_followup_new_counts_only_this_researchs_new_records_even_when_disabled(api):
    api.state.payload = page()
    command = create(api); turn(api)
    api.state.payload = page(*(work(f"W{i}") for i in range(5)),
                             work("WN", title="Correction: SYNTHETIC paper W0"))
    now_check(api, command["watch_id"]); turn(api)
    items = api.watches.items(api.rid)
    records = [item for item in items if item["kind"] == "new_record"]
    assert len(records) == 5 and len(items) == 6
    assert counts(api)[api.rid] == 5
    api.watches.dismiss(api.rid, records[0]["id"], {"expected_status": "new", "reason": "SYNTHETIC"}, "dismiss-count")
    api.conn.execute("UPDATE watch_items SET status='merged',merged_into_item_id=? WHERE id=?",
                     (records[2]["id"], records[1]["id"]))
    other = api.store.create_research("SYNTHETIC other", "academic", "standard", ["openalex"], "fake", "fake-model", "en")
    # The parent trigger requires the check/seen rows to belong to the item's research.
    api.store.freeze_protocol(other, 1, {"compiled_queries": [{"provider_id": "openalex", "query_text": "SYNTHETIC other"}]})
    api.state.payload = page()
    second = api.watches.create(other, {"kind": "protocol_queries", "mode": "manual", "expected_scope_revision": 1}, "other-count")
    turn(api)
    api.state.payload = page(work("WOTHER"))
    api.watches.check_now(other, second["watch_id"],
                          {"expected_state_version": api.watches.watch(other, second["watch_id"])["state_version"]}, "other-check-count")
    turn(api)
    assert counts(api) == {api.rid: 3, other: 1}
    api.watches.disable(api.rid, command["watch_id"],
                        {"expected_state_version": api.watches.watch(api.rid, command["watch_id"])["state_version"]}, "disable-count")
    assert counts(api) == {api.rid: 3, other: 1}


def test_followup_list_remains_one_query_per_call(api):
    for i in range(6):
        api.store.create_research(f"SYNTHETIC {i}", "academic", "standard", ["openalex"], "fake", "fake-model", "en")
    queries = []
    api.conn.set_trace_callback(queries.append)
    try:
        rows = api.store.list_researches()
    finally:
        api.conn.set_trace_callback(None)
    assert len(rows) == 7
    assert all(row["followup_new"] == 0 for row in rows)
    assert len(queries) == 1
