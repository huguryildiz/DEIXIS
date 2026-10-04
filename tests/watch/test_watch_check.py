"""Bounded manual checks with mocked providers; no retrieval-quality claim."""

import json
from dataclasses import replace

import httpx
import pytest

from deixis.providers import common, registry
from deixis.storage import db
from deixis.workflow.watch import check as policy
from test_connector_contract import dispatch_flow
from tests.watch.watch_helpers import api, watch_offline, watch_api, create, now_check, turn, read, control, work, page, add_included


def test_baseline_and_second_check_announce_only_new_identities(api):
    first = create(api); turn(api)
    assert read(api, first)["state"] == "succeeded"
    assert api.conn.execute("SELECT origin FROM watch_seen").fetchone()[0] == "baseline"
    assert api.watches.items(api.rid) == []
    api.state.payload = page(work(), work("W2"))
    second = now_check(api, first["watch_id"]); turn(api)
    card = read(api, second)
    assert card["state"] == "succeeded" and card["counts"]["new"] == 1 and card["counts"]["already_seen"] == 1
    assert len(api.watches.items(api.rid)) == 1
    assert api.sent[-1].url.params["sort"] == "publication_date:desc"
    assert api.sent[-1].url.params["select"].endswith(",publication_date")
    row = api.watches.reads(api.watches.check(api.rid, second["check_id"]))[0]
    assert "sort=publication_date:desc select+publication_date" in row["request_description"]
    assert json.loads(row["connector_json"])["adapter_revision"] == 3
    assert card["observed"]["units"]["query:0"]["sort_sent"] == "publication_date:desc"


def test_failed_baseline_provider_is_silent_on_first_success(api):
    api.state.status = 500
    first = create(api); turn(api)
    assert read(api, first)["failure_reason"] == "no_provider_read"
    assert api.conn.execute("SELECT count(*) FROM watch_seen").fetchone()[0] == 0
    api.state.status = 200
    second = now_check(api, first["watch_id"]); turn(api)
    assert read(api, second)["counts"]["baseline"] == 1
    assert api.watches.items(api.rid) == []


def test_full_depth_baseline_nonnull_cursor_completes_window(api):
    api.state.payload = page(work(), cursor="next")
    command = create(api); turn(api)
    card = read(api, command)
    assert len(api.sent) == 2 and card["state"] == "succeeded"
    assert card["observed"]["units"]["query:0"]["cut_by_cap"]
    assert not card["observed"]["units"]["query:0"]["exhausted"]
    baseline = json.loads(api.watches.watch(api.rid, command["watch_id"])["baseline_json"])["query:0"]
    assert baseline["state"] == "complete" and baseline["pages_read"] == 2


def test_partial_baseline_continues_cursor_cut_and_lists_undated(api, monkeypatch):
    monkeypatch.setattr(policy, "WATCH_MAX_REQUESTS", 1)
    api.state.payload = page(work(), cursor="page-two")
    first = create(api); turn(api)
    old = json.loads(api.watches.watch(api.rid, first["watch_id"])["baseline_json"])["query:0"]
    assert old["state"] == "partial" and len(api.sent) == 1
    assert read(api, first)["state"] == "partial"
    api.state.payload = page(work("OLD", date="2025-01-01"), work("NEW", date="2099-01-01"), work("UNDATED", date=None), cursor="deeper")
    second = now_check(api, first["watch_id"]); turn(api)
    card = read(api, second)
    assert len(api.sent) == 2 and api.sent[-1].url.params["cursor"] == "page-two"
    assert card["counts"]["new"] == 1 and card["counts"]["baseline"] == 1 and card["counts"]["baseline_undated"] == 1
    assert card["baseline_undated"]["titles"] == ["SYNTHETIC paper UNDATED"]
    baseline = json.loads(api.watches.watch(api.rid, first["watch_id"])["baseline_json"])["query:0"]
    assert baseline["cut"] == old["cut"] and baseline["state"] == "complete"


def test_adapter_revision_change_restarts_partial_baseline(api, monkeypatch):
    monkeypatch.setattr(policy, "WATCH_MAX_REQUESTS", 1)
    api.state.payload = page(work(), cursor="old-cursor")
    first = create(api); turn(api)
    connector = registry.CONNECTORS["openalex"]
    monkeypatch.setitem(registry.CONNECTORS, "openalex", replace(connector, adapter_revision=4))
    api.state.payload = page(work("LATER"))
    second = now_check(api, first["watch_id"]); turn(api)
    assert api.sent[-1].url.params["cursor"] == "*"
    assert read(api, second)["observed"]["units"]["query:0"]["baseline_restarted"] == "adapter_revision_changed"
    assert not api.watches.items(api.rid)


def test_exhaustion_and_reached_date_are_separate(api):
    first = create(api); turn(api)
    api.state.payload = page(work("W2", date="2099-01-01"), cursor="more")
    second = now_check(api, first["watch_id"]); turn(api)
    obs = read(api, second)["observed"]["units"]["query:0"]
    assert obs["coverage"] == "coverage_not_reached" and obs["oldest_publication_date"] == "2099-01-01"
    assert obs["exhausted"] is False
    api.state.payload = page(work("W3", date="2099-01-01"))
    third = now_check(api, first["watch_id"]); turn(api)
    assert read(api, third)["observed"]["units"]["query:0"]["coverage"] == "covered"


def test_no_date_sort_is_unknown_and_year_is_not_a_date(tmp_path):
    with watch_api(tmp_path, queries=[{"provider_id": "biorxiv", "query_text": "SYNTHETIC"}]) as api:
        first = create(api); turn(api)
        second = now_check(api, first["watch_id"]); turn(api)
        card = read(api, second)
        assert card["state"] == "partial" and "coverage_unknown" in card["partial_reasons"]
        assert "sort" not in api.sent[-1].url.params and "publication_date" not in api.sent[-1].url.params["select"]
        record = json.loads(api.conn.execute("SELECT record_json FROM watch_seen").fetchone()[0])
        assert record["year"] == 2026 and record["publication_date"] is None and record["version_time"] is None


def test_not_configured_and_not_searchable_units_send_nothing(tmp_path):
    with watch_api(tmp_path, queries=[{"provider_id": "core", "query_text": "SYNTHETIC"},
                                    {"provider_id": "crossref", "query_text": "SYNTHETIC"}]) as api:
        command = create(api); turn(api)
        card = read(api, command)
        assert api.sent == [] and card["state"] == "failed" and card["failure_reason"] == "no_provider_read"
        assert card["provider_status"]["query:0"]["status"] == "not_configured"
        assert card["provider_status"]["query:1"]["status"] == "skipped_not_searchable"


def test_mixed_provider_failure_and_quota_later_units(tmp_path):
    queries = [{"provider_id": "openalex", "query_text": text} for text in ("ok", "quota", "later")]
    with watch_api(tmp_path, queries=queries) as api:
        def handler(request):
            if request.url.params.get("search.title_and_abstract") == "ok":
                return httpx.Response(200, json=page(work()))
            return httpx.Response(429, json={"error": {"code": "insufficient_quota"}}, headers={"x-ratelimit-remaining-usd": "0"})
        api.state.handler = handler
        command = create(api); turn(api)
        card = read(api, command)
        assert len(api.sent) == 2 and card["state"] == "partial"
        assert card["provider_status"]["query:1"]["error_kind"] == "quota_exhausted"
        assert card["provider_status"]["query:2"]["status"] == "quota_deferred"


@pytest.mark.parametrize("returned,cap,overshoot", [(2950,3000,0), (105,100,5)])
def test_records_full_page_deferred_without_shrinking_and_overshoot(api, monkeypatch, returned, cap, overshoot):
    monkeypatch.setattr(policy, "WATCH_MAX_RECORDS", cap)
    api.state.payload = page(*(work(f"W{i}") for i in range(returned)), cursor="next")
    command = create(api); turn(api)
    assert len(api.sent) == 1 and api.sent[0].url.params["per_page"] == "100"
    card = read(api, command)
    assert card["counts"]["returned"] == returned and "budget_deferred" in card["partial_reasons"]
    # Every returned row is stored; an oversized response is not silently shortened.
    assert card["counts"]["records_over_threshold"] == overshoot


def test_transient_resend_is_budget_gated(api, monkeypatch):
    monkeypatch.setattr(policy, "WATCH_MAX_REQUESTS", 1)
    def fail(request):
        raise httpx.ConnectError("SYNTHETIC not sent", request=request)
    api.state.handler = fail
    command = create(api); turn(api)
    assert len(api.sent) == api.store.run(command["run_id"])["usage"]["provider_requests"] == 1
    assert "budget_deferred" in read(api, command)["partial_reasons"]
    assert api.watches.reads(api.watches.check(api.rid, command["check_id"]))[0]["status"] == "deferred_budget"


def test_page_size_frozen_at_baseline_does_not_shrink_on_later_check(api, monkeypatch):
    first = create(api); turn(api)
    monkeypatch.setattr(policy, "WATCH_PER_PAGE", 50)
    second = now_check(api, first["watch_id"]); turn(api)
    assert second["check"]["units"][0]["page_size"] == 100
    assert api.sent[-1].url.params["per_page"] == "100"


def test_pubmed_efetch_refused_after_esearch_last_request(tmp_path, monkeypatch):
    monkeypatch.setattr(policy, "WATCH_MAX_REQUESTS", 1)
    def handler(request):
        return httpx.Response(200, json={"esearchresult": {"count": "1", "idlist": ["17"]}})
    with watch_api(tmp_path, queries=[{"provider_id": "pubmed", "query_text": "SYNTHETIC"}], handler=handler) as api:
        command = create(api); turn(api)
        assert len(api.sent) == 1 and api.sent[0].url.path.endswith("esearch.fcgi")
        assert "budget_deferred" in read(api, command)["partial_reasons"]


def test_citing_roll_cap_wrap_and_partial_priority(api):
    for index in range(12):
        add_included(api, f"W{index:02}")
    first = create(api, "citing_works"); turn(api)
    card = read(api, first)
    assert len(api.sent) == 10 and card["observed"]["rolled_over"] == 2
    second = now_check(api, first["watch_id"]); turn(api)
    keys1 = {u["unit_key"] for u in card["units"]}
    keys2 = {u["unit_key"] for u in read(api, second)["units"]}
    assert len(keys1 | keys2) == 12
    units = [{"unit_key": f"cites:W{i}", "openalex_id": f"W{i}"} for i in range(12)]
    baseline = {u["unit_key"]: {"state": "partial"} for u in units[:11]}
    chosen, unread, position = policy.citing_roll(units, baseline, 11)
    assert chosen == units[:10] and unread == 2 and position == 11


def test_citing_roll_keeps_unread_work_and_unread_id_counts_separate(api, monkeypatch):
    source = add_included(api, "W1")
    api.conn.execute("INSERT INTO identifier_mappings (source_version_id,scheme,value,provider,retrieved_at)"
        " VALUES (?,'openalex','W2','SYNTHETIC',?)", (source, db.now()))
    monkeypatch.setattr(policy, "WATCH_CITING_SOURCES", 1)
    first = create(api, "citing_works"); turn(api)
    card = read(api, first)
    assert len(api.sent) == 1 and card["observed"]["rolled_over"] == 0
    assert card["observed"]["rolled_over_units"] == 1 and "rolled_over" in card["partial_reasons"]


def test_citing_admission_sanitizes_payload_raw_and_counts_drops(api, monkeypatch):
    add_included(api, "SEED")
    monkeypatch.setenv("OPENALEX_API_KEY", "SYNTHETIC-SECRET")
    invalid = [work(None), work(""), work("None"), work({"invalid": "id"})]
    api.state.payload = page(*invalid, work(17, echoed="SYNTHETIC-SECRET"))
    api.state.payload["echoed"] = "SYNTHETIC-SECRET"
    command = create(api, "citing_works"); turn(api)
    card = read(api, command)
    assert card["counts"]["returned"] == 5 and card["counts"]["dropped"] == 4 and card["counts"]["records_read"] == 1
    row = api.watches.reads(api.watches.check(api.rid, command["check_id"]))[0]
    content = (api.settings.payloads_dir / row["raw_payload_path"]).read_text()
    assert "SYNTHETIC-SECRET" not in content and "<redacted>" in content
    assert "SYNTHETIC-SECRET" not in row["records_json"]


def test_success_boundary_does_not_move_on_failed_or_deferred_unit(api, monkeypatch):
    first = create(api); turn(api)
    old = json.loads(api.watches.watch(api.rid, first["watch_id"])["baseline_json"])["query:0"]["success_boundary"]
    last_success = api.watches.watch(api.rid, first["watch_id"])["last_success_at"]
    api.state.status = 500
    second = now_check(api, first["watch_id"]); turn(api)
    baseline = json.loads(api.watches.watch(api.rid, first["watch_id"])["baseline_json"])
    assert baseline["query:0"]["success_boundary"] == old
    assert read(api, second)["observed"]["units"]["query:0"]["unread_window"] == {"from": old, "to": second["check"]["requested_to"]}
    monkeypatch.setattr(policy, "WATCH_MAX_REQUESTS", 0)
    third = now_check(api, first["watch_id"]); turn(api)
    assert json.loads(api.watches.watch(api.rid, first["watch_id"])["baseline_json"])["query:0"]["success_boundary"] == old
    assert api.watches.watch(api.rid, first["watch_id"])["last_success_at"] == last_success
    assert read(api, third)["observed"]["units"]["query:0"]["sort_sent"] is None


def test_citing_units_all_versions_work_order_dedup_and_missing_id(api):
    from tests.watch.watch_helpers import record
    head = add_included(api, "W9", doi="10.1000/work")
    api.store.upsert_provider_source("openalex", registry.openalex._record(work("W8", doi="10.1000/work")), None)
    # A distinct included work with no OpenAlex mapping is visibly skipped.
    unknown = api.store.create_upload_source("SYNTHETIC no OpenAlex id")
    api.store.add_to_corpus(api.rid, unknown, "user_upload", selection_state="included", selection_origin="user")
    preview = api.client.post(api.url + "/preview", json={"kind": "citing_works"}).json()
    assert preview["no_openalex_id"] == 1
    units = preview["units"]
    assert [u["openalex_id"] for u in units if u["openalex_id"]] == ["W8", "W9"]
    assert len({u["work_id"] for u in units}) == 2
    first = create(api, "citing_works"); turn(api)
    card = read(api, first)
    assert card["state"] == "partial" and "no_openalex_id" in card["partial_reasons"]
    assert len(api.sent) == 2 and [r.url.params["filter"] for r in api.sent] == ["cites:W8", "cites:W9"]


def test_page_gap_wait_and_units_and_record_order_persist(tmp_path, monkeypatch):
    from deixis.workflow.watch import run as watch_run
    connector = registry.CONNECTORS["openalex"]
    monkeypatch.setitem(registry.CONNECTORS, "openalex", replace(connector, page_gap=.25))
    waits = []
    callbacks = watch_run.Callbacks
    async def sleep(seconds):
        waits.append(seconds)
    monkeypatch.setattr(watch_run, "Callbacks", lambda **kwargs: callbacks(**kwargs, sleep=sleep))
    with watch_api(tmp_path, queries=[{"provider_id": "openalex", "query_text": "first"},
                                    {"provider_id": "openalex", "query_text": "second"}]) as api:
        api.state.payload = page(work("B"), work("A"), cursor="next")
        command = create(api); turn(api)
        assert waits == [.25, .25]
        rows = api.watches.reads(api.watches.check(api.rid, command["check_id"]))
        assert [(r["unit_key"], r["page_number"]) for r in rows] == [("query:0",1),("query:0",2),("query:1",1),("query:1",2)]
        assert all([r["provider_record_id"] for r in json.loads(row["records_json"])] == ["B","A"] for row in rows)


def test_discovery_revision_two_continuation_refused_after_watch_adapter_bump(dispatch_flow, monkeypatch):
    from deixis.providers.contract import CONTRACT_ID
    from tests.providers.test_connector_dispatch import test_resume_provenance as assert_resume
    assert_resume(dispatch_flow, monkeypatch, json.dumps({"contract_id": CONTRACT_ID, "adapter_revision": 2}), "adapter_revision_changed")
