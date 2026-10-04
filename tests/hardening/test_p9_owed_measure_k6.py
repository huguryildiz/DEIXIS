"""Synthetic, offline K6 evidence; no provider/model or live service calls."""
from copy import deepcopy
import json
from pathlib import Path
import random
import sqlite3
import subprocess

import httpx
import pytest

from scripts.p9_owed import measure_k6 as k


def labelled(wid, relation="some elements", text="mobile robot avoids obstacle"):
    return {"openalex_id": wid, "doi": "10.1/" + wid, "title": "mobile robot",
            "abstract": "avoids obstacle", "expected_relation": relation,
            "provider_abstract_sha256": k.sha(text), "supplied_text_sha256": k.sha(text)}


def hit(wid, *, kept=True, text="mobile robot avoids obstacle", whole=False):
    return {"source_version_id": "sid-" + wid, "work_id": wid, "kept": kept,
            "assessment_state": "assessed" if kept else None, "states_whole_claim": whole,
            "source": {"title": "mobile robot", "abstract": text, "doi": "10.1/" + wid},
            "passages": [{"id": "p-" + wid, "kind": "abstract", "text": text}] if kept else []}


def cell(wid, key="C1", eid="e1", quote="avoids obstacle"):
    return {"id": key + wid + eid, "claim_key": key, "kill_search_id": "ks-" + key,
            "work_id": wid, "source_version_id": "sid-" + wid, "element_id": eid,
            "element": {"id": eid, "text": "avoids obstacle", "kind": "outcome"},
            "relation": "explicit_support", "condition_alignment": "aligned",
            "quotes": [{"quote": quote}], "passages": hit(wid)["passages"], "published": True}


def claim(key="C1", ns=None, status="open", hits=None, cells=None):
    hits = hits if hits is not None else [hit("W1")]
    cells = cells if cells is not None else [cell("W1", key)]
    return {"key": key, "N": ns if ns is not None else [labelled("W1")],
            "claim_statement": "A robot avoids an obstacle.", "elements": [{"text": "avoids obstacle", "kind": "outcome"}],
            "conditions": [], "critical_assumption": "feasible", "nearest_simple_explanation": None,
            "validation_plan": "inspect", "status": status, "hits": hits, "cells": cells,
            "element_ids": ["e1"], "kill_search_id": "ks-" + key, "hits_complete": True,
            "S1_source": "synthetic stored hits", "records": [{"work_id": h["work_id"], "source": h["source"]} for h in hits],
            "matrix": {"evidence": [{"source_version_id": h["source_version_id"], "matrix_cell_id": None,
                                       "quote": "avoids obstacle"} for h in hits if h["states_whole_claim"]]},
            "blocks": {"setting": [{"term": "mobile robot"}], "task": [{"term": "avoids obstacle"}], "setting_backup": []},
            "queries": [{"provider": "openalex", "query_text": "mobile robot AND obstacle"}],
            "run": {"status": "completed", "usage": {"model_calls": 2, "provider_requests": 3},
                    "budget": {"max_model_calls": 54, "max_provider_requests": 90}}}


def snapshot(*claims):
    return {"frozen": {"claims": [{field: c[field] for field in (*k.FIELDS, "key", "N")} for c in claims]},
            "claims": [{field: value for field, value in c.items() if field not in {*k.FIELDS, "N"}} for c in claims],
            "series": {"elapsed_seconds": 90, "new_sessions": 2, "ended_at": 90, "session_source": "synthetic"}}


def test_plan_hashes_and_no_network(tmp_path, monkeypatch, capsys):
    monkeypatch.setattr(httpx.Client, "request", lambda *a, **kw: pytest.fail("network forbidden"))
    assert k.main(["plan"]) == 0
    assert len(json.loads(capsys.readouterr().out)["claims"]) == 6
    data = k.frozen()
    data["claims"][0]["claim_statement"] += " tamper"
    file = tmp_path / "tamper.json"
    k.write(file, data)
    with pytest.raises(k.Refused, match="payload_sha256"):
        k.frozen(file)


@pytest.mark.parametrize("base", ["http://127.0.0.1:8765", "http://localhost:8765", "http://[::1]:8765"])
def test_8765_refused(base):
    with pytest.raises(k.Refused, match="8765"):
        k.checked_base(base)


@pytest.mark.parametrize("base", ["https://example.com", "http://user:secret@localhost:8873", "http://localhost:8873/path"])
def test_nonlocal_or_credential_url_refused(base):
    with pytest.raises(k.Refused):
        k.checked_base(base)


@pytest.mark.parametrize("code,out,err,free", [(1, "", "", True), (0, "p42\n", "", False), (2, "", "", False), (1, "", "error", False)])
def test_port_check_fail_closed_records(tmp_path, code, out, err, free):
    def runner(cmd, **kw):
        assert cmd == ["/usr/sbin/lsof", "-nP", "-iTCP:8765", "-sTCP:LISTEN", "-Fp"]
        return subprocess.CompletedProcess(cmd, code, out, err)
    if free:
        k.port_check(tmp_path, runner)
    else:
        with pytest.raises(k.Refused):
            k.port_check(tmp_path, runner)
    assert json.loads((tmp_path / "port-checks.jsonl").read_text())["free"] is free


def test_sample_exact_seed_sort_and_quote_free():
    cells = [cell("W" + str(i), "C2" if i % 2 else "C1", "e" + str(i)) for i in range(29, -1, -1)]
    c = claim(ns=[], cells=cells)
    snap = snapshot(c)
    actual = k.sample_cells(snap)
    assert actual == random.Random(20261002).sample(sorted(cells, key=k.cell_key), 20)
    cells[0]["quotes"] = []
    assert cells[0] not in k.sample_cells(snap)


def test_s1_categories_separate_and_s2():
    ns = [labelled("W1"), labelled("W2"), labelled("W3")]
    snap = snapshot(claim(ns=ns, hits=[hit("W1"), hit("W2", kept=False)]))
    score = k.score(snap, unread="no reader")
    assert [w["state"] for w in score["S1"]["C1"]["works"]] == ["retained", "returned but cut", "absent"]
    assert all(v["value"] == 1 / 3 for v in score["S1"]["C1"]["categories"].values())
    assert score["S2"]["count"] == score["S2"]["denominator"] == 1
    assert all(w["source"] == "synthetic stored hits" for w in score["S1"]["C1"]["works"])


def test_failed_merge_is_not_rank_cut_or_absent():
    snap = snapshot(claim(hits=[], cells=[]))
    snap["claims"][0]["hits_complete"] = False
    snap["claims"][0]["records"] = [{"work_id": "W1"}]
    result = k.score(snap)
    assert result["S1"]["C1"]["works"][0]["state"] == k.UNMEASURED


def test_s3_false_closed_and_unlabelled_witness():
    c = claim(status="closed", hits=[hit("W9", whole=True)], cells=[cell("W9")])
    snap = snapshot(c)
    witness_id = k.closing_witnesses(snap["claims"][0])[0]["id"]
    r = {"S3": [{"id": witness_id, "answer": "states_whole_claim"}]}
    good = k.score(snap, r)
    assert good["S3"]["denominator"] == 1
    assert good["S3"]["count"] == 0
    assert good["S3_unlabelled_witnesses"] == 1
    r["S3"][0]["answer"] = "does_not_state_whole_claim"
    assert k.score(snap, r)["S3"]["value"] == 1
    assert k.score(snap)["S3"]["value"] == k.UNMEASURED
    assert len(good["S3_closing_quotes"]) == 1


def test_s3_every_closed_read_including_whole_labelled():
    snap = snapshot(claim(ns=[labelled("W1", "whole claim")], status="closed", hits=[hit("W1", whole=True)]))
    assert len(k.score(snap)["S3_closing_quotes"]) == 1
    assert k.score(snap)["S3"]["value"] == k.UNMEASURED  # zero denominator
    snap["claims"][0]["element_ids"].append("missing-element")
    assert k.closing_witnesses(snap["claims"][0]) == []


def test_s4a_all_quotes_exact_no_cross_passage_splicing_and_s4b():
    c = claim(ns=[], cells=[cell("W1"), cell("W1", eid="e2", quote="not supplied")])
    c["cells"][0]["quotes"].append({"quote": "robot\n\navoids"})
    c["cells"][0]["passages"] = [{"text": "mobile robot"}, {"text": "avoids obstacle"}]
    snap = snapshot(c)
    read = {"S4b": [{"id": "sample-1", "answer": "supports"}, {"id": "sample-2", "answer": "partial"}]}
    result = k.score(snap, read)
    assert result["S4a"]["count"] == 1
    assert result["S4a"]["denominator"] == 3
    assert result["S4b"]["judgements"]["supports"]["value"] == .5
    assert result["S4b"]["judgements"]["partial"]["value"] == .5
    assert result["S4b"]["judgements"]["not_supports"]["value"] == 0
    read["S4b"].pop()
    assert k.score(snap, read)["S4b"]["judgements"]["supports"]["value"] == k.UNMEASURED


def test_hash_mismatch_excludes_not_mutates_product_or_denominators():
    snap = snapshot(claim(hits=[hit("W1", text="changed")]))
    before = deepcopy(snap)
    result = k.score(snap)
    assert len(result["excluded_text_hash_mismatches"]) == 1
    assert result["S2"]["denominator"] == result["S3"]["denominator"] == 0
    assert result["S1"]["C1"]["categories"]["retained"]["value"] == k.UNMEASURED
    assert result["S4a"]["excluded_cells"] == 1
    assert k.sample_cells(snap) == []
    assert before == snap


def test_supplied_text_uses_prep_lookup_cap():
    h = hit("W1", text="x" * 3000)
    _, digest = k.supplied(h)
    assert digest == k.prep_lookup.supplied_text({"abstract": "x" * 3000})["supplied_text_sha256"]


def test_zero_denominators_unmeasurable():
    result = k.score(snapshot(claim(ns=[], hits=[], cells=[])))
    assert result["S2"]["value"] == result["S3"]["value"] == result["S4a"]["value"] == k.UNMEASURED
    assert all(m["value"] == k.UNMEASURED for m in result["S4b"]["judgements"].values())
    assert all(m["value"] == k.UNMEASURED for m in result["S6"]["C1"]["returned_records"].values())


def test_s6_consecutive_normalization_all_some_none_and_missing():
    c = claim(ns=[labelled("W8")], hits=[], cells=[])
    c["records"] = [{"work_id": "X", "source": {"title": "Móbile robot", "abstract": "avoids obstacle"}},
                    {"work_id": "Y", "source": {"title": "mobile big robot", "abstract": "avoids obstacle"}},
                    {"work_id": "Z", "source": {"title": "other", "abstract": "unrelated"}},
                    {"work_id": "A", "source": {"title": "robot", "abstract": None}}]
    result = k.score(snapshot(c))["S6"]["C1"]
    assert result["number_of_blocks"] == 2
    assert result["terms_per_block"] == {"setting": 1, "task": 1}
    assert all(m["count"] == 1 and m["denominator"] == 3 for m in result["returned_records"].values())
    assert result["missing_title_or_abstract"] == 1
    assert result["absent_N"][0]["missing_blocks"] == []
    assert k.tokens("Crème_AB Ç 2.0") == ("creme", "ab", "c", "2", "0")
    assert not k.term_matches("robot mobile", k.tokens("mobile robot"))


def test_s5_against_product_and_series_caps():
    snap = snapshot(claim())
    snap["series"].update(elapsed_seconds=10815, new_sessions=122)
    snap["claims"][0]["run"]["usage"].update(model_calls=55, provider_requests=91)
    result = k.score(snap)["S5"]
    assert result["time_cap_exceeded"] is result["session_cap_exceeded"] is True
    assert result["claims"][0]["model_cap_exceeded"] is result["claims"][0]["provider_cap_exceeded"] is True


def test_reader_packet_has_no_hidden_labels_and_score_reads_filled_page(tmp_path):
    snap = snapshot(claim(ns=[labelled("W1", "SECRET_EXPECTATION")], status="closed", hits=[hit("W1", whole=True)]))
    page = k.reader_packet(snap, tmp_path)
    encoded = (tmp_path / "reader.json").read_text()
    assert "expected_relation" not in encoded and "SECRET_EXPECTATION" not in encoded
    assert "nearest_work_unknown" not in encoded and "payload_sha256" not in encoded
    assert "SECRET_EXPECTATION" in (tmp_path / "key.json").read_text()
    page["S3"][0]["answer"] = "does_not_state_whole_claim"
    page["S4b"][0]["answer"] = "supports"
    k.write(tmp_path / "reader.json", page)
    k.write(tmp_path / "snapshot.json", snap)
    assert k.main(["score", "--snapshot", str(tmp_path / "snapshot.json"), "--reader", str(tmp_path / "reader.json"), "--out", str(tmp_path / "score")]) == 0
    result = k.load(tmp_path / "score/results.json")
    assert result["S3"]["value"] == result["S4b"]["judgements"]["supports"]["value"] == 1


class FakeAPI:
    base = "http://127.0.0.1:8873"

    def __init__(self, states):
        self.states = iter(states)
        self.run = None
        self.posts = []

    def get(self, path):
        if path.endswith("/kill-search/plan"):
            return {"version": 1, "preview_fingerprint": "a" * 64,
                    "model": {"kill_search_query": ["codex", "gpt-5.6-luna", "medium"], "claim_assessment": ["codex", "gpt-5.6-luna", "medium"]}}
        if "/candidates/" in path:
            return {"searches": [], "current_version": 1}
        if self.run:
            self.run = {"id": "run1", "status": next(self.states)}
        return {"runs": [self.run] if self.run else []}

    def post(self, path, body, key):
        self.posts.append(path)
        if path.endswith("/kill-search"):
            self.run = {"id": "run1", "status": "queued"}
        return self.run


def census(*args):
    return {"sessions": [], "active": [], "started": [], "source": "synthetic session census"}


@pytest.mark.parametrize("terminal", ["failed", "paused", "cancelled"])
def test_stop_series_noncompleted_no_resume_or_cancel(tmp_path, terminal):
    api = FakeAPI([terminal])
    state = {"research_id": "r1", "claims": [{"key": "C1", "candidate_id": "c1"}, {"key": "C2", "candidate_id": "c2"}]}
    with pytest.raises(k.Refused, match=f"terminal run {terminal}"):
        k.run_series(api, tmp_path, state, None, census=census, sleep=lambda _: pytest.fail("terminal must stop"))
    assert api.posts == ["/api/researches/r1/candidates/c1/kill-search"]
    record = k.load(tmp_path / "run.json")
    assert record["cancel_requests"] == 0 and record["ended_at"] is not None
    with pytest.raises(k.Refused, match="already attempted"):
        k.run_series(api, tmp_path, state, None, census=census)


@pytest.mark.parametrize("fresh,cancels", [("running", 1), ("paused", 0), ("completed", 0)])
def test_time_cap_fresh_state_before_single_cancel(tmp_path, fresh, cancels):
    api = FakeAPI(["running", fresh])
    times = iter([0, 0, 10801, 10801, 10801])
    state = {"research_id": "r1", "claims": [{"key": "C1", "candidate_id": "c1"}]}
    with pytest.raises(k.Refused, match="time cap"):
        k.run_series(api, tmp_path, state, None, census=census, clock=lambda: next(times))
    assert sum(p.endswith("/cancel") for p in api.posts) == cancels
    assert not any(p.endswith("/resume") for p in api.posts)


def test_api_mock_transport_csrf_ledger_and_post_guard(tmp_path):
    seen = []
    guards = []
    def handler(request):
        seen.append(request)
        if request.url.path == "/api/session":
            return httpx.Response(200, json={"csrf_token": "private-csrf"}, headers={"set-cookie": "deixis_csrf=private-csrf"})
        assert request.headers["x-deixis-csrf"] == "private-csrf"
        assert request.headers["idempotency-key"] == "step-key"
        assert "deixis_csrf=private-csrf" in request.headers["cookie"]
        return httpx.Response(201, json={"ok": True})
    api = k.API("http://127.0.0.1:8873", tmp_path, transport=httpx.MockTransport(handler), port_guard=lambda out: guards.append(out))
    try:
        assert api.post("/api/test", {"claim": "test"}, "step-key") == {"ok": True}
    finally:
        api.close()
    assert len(guards) == 1 and len(seen) == 2
    log = (tmp_path / "ledger.jsonl").read_text()
    assert "private-csrf" not in log
    assert len(log.splitlines()) == 4


def test_counter_requires_db_before_model_request(tmp_path):
    with pytest.raises(k.Refused, match="--db required"):
        k.session_rows(None, "rid")


def test_copy_original_refused_verified_copy_accepted(tmp_path, monkeypatch):
    monkeypatch.setattr(k, "ROOT", tmp_path)
    root = tmp_path / "copy"
    root.mkdir()
    db = root / "library.sqlite"
    with sqlite3.connect(db) as conn:
        conn.execute("CREATE TABLE sample (id INTEGER)")
        conn.execute("INSERT INTO sample VALUES (1)")
    before = db.read_bytes()
    with pytest.raises(FileNotFoundError):
        with k.copy_db(db):
            pytest.fail("original opened")
    manifest = k.funnel_counts.manifest(root)
    record = {"source": str(tmp_path / "original"), "destination": str(root), "usable": True,
              "source_manifest": manifest, "source_after_manifest": manifest, "copy_manifest": manifest}
    k.write(k.funnel_counts.copy_record_path(root), record)
    with k.copy_db(db) as conn:
        assert conn.execute("SELECT id FROM sample").fetchone()[0] == 1
        with pytest.raises(sqlite3.OperationalError):
            conn.execute("INSERT INTO sample VALUES (2)")
    assert db.read_bytes() == before
    record["source"] = str(root)
    k.write(k.funnel_counts.copy_record_path(root), record)
    with pytest.raises(k.Refused, match="byte copy"):
        with k.copy_db(db):
            pass


def test_frozen_prep_records_hashes_and_tamper(tmp_path):
    c = labelled("W1")
    data = {"claims": [{"N": [c]}]}
    path = tmp_path / "records.json"
    k.write(path, {"records": [{"openalex_id": "W1", "title": "mobile robot", "abstract": "mobile robot avoids obstacle"}]})
    assert k.n_texts(data, path)["W1"]["supplied_text_sha256"] == c["supplied_text_sha256"]
    changed = k.load(path)
    changed["records"][0]["abstract"] = "tamper"
    k.write(path, changed)
    with pytest.raises(k.Refused, match="frozen hashes"):
        k.n_texts(data, path)


def test_setup_exact_frozen_fields_no_decomposition_and_no_truncation(tmp_path):
    data = k.frozen()
    posts = []
    cards = {}
    def handler(request):
        path = request.url.path
        if request.method == "GET":
            if path == "/api/session":
                return httpx.Response(200, json={"csrf_token": "test"})
            if path == "/api/researches":
                return httpx.Response(200, json=[])
            return httpx.Response(200, json={"runs": []})
        body = json.loads(request.content)
        posts.append((path, body, request.headers["idempotency-key"]))
        if path == "/api/researches":
            assert body["requested_model"] == "gpt-5.6-luna" and body["reasoning_effort"] == "medium"
            assert body["review_mode"] == "off" and body["model_connection"] == "codex"
            assert body["question"] == data["question"]
            return httpx.Response(201, json={"research": {"id": "r1"}})
        if path.endswith("/candidates"):
            cid = "c" + str(len(cards) + 1)
            cards[cid] = {"id": cid, "current_version": 0, "active_run": None}
            assert body == {"origin": "owner_text", "text": data["claims"][len(cards) - 1]["claim_statement"]}
            return httpx.Response(201, json=cards[cid])
        cid = path.split("/")[-2]
        index = int(cid[1:]) - 1
        assert body == {f: data["claims"][index][f] for f in k.FIELDS} | {"expected_version": 0}
        assert "origin" not in body
        return httpx.Response(201, json={"id": cid, "current_version": 1, "active_run": None,
            "current_version_id": "v-" + cid, "versions": [{"id": "v-" + cid, "origin": "human_edit"}]})
    api = k.API(FakeAPI.base, tmp_path, transport=httpx.MockTransport(handler), port_guard=lambda _: None)
    try:
        result = k.setup(api, tmp_path, data)
        with pytest.raises(k.Refused, match="already attempted"):
            k.setup(api, tmp_path, data)
    finally:
        api.close()
    assert len(result["claims"]) == 6 and len(posts) == 13
    assert len({key for _, _, key in posts}) == 13
    assert not any("decompose" in path for path, _, _ in posts)


def test_snapshot_real_api_passage_shape_stored_cut_hits_and_product_work_ids(tmp_path, monkeypatch):
    monkeypatch.setattr(k, "ROOT", tmp_path)
    root = tmp_path / "data-copy"
    root.mkdir()
    db = root / "library.sqlite"
    text = "mobile robot avoids obstacle"
    passage = {"passage_id": "p1", "source_id": "sid-W1", "reading_depth": "abstract",
               "locator": {"kind": "abstract", "physical_page": None, "printed_label": None}, "text": text}
    search = {"id": "ks1", "run_id": "run1", "outcome": "completed", "found": 2, "kept": 1,
              "rank_cut": 1, "hits_recorded": 1, "query_block": {"setting": [{"term": "mobile robot"}], "task": [{"term": "avoids obstacle"}]}}
    with sqlite3.connect(db) as conn:
        for ddl in (
            "CREATE TABLE model_sessions (id TEXT, status TEXT, run_id TEXT)",
            "CREATE TABLE runs (id TEXT,status TEXT)",
            "CREATE TABLE kill_searches (id TEXT,run_id TEXT,outcome TEXT,found INT,kept INT,rank_cut INT,hits_recorded INT)",
            "CREATE TABLE source_versions (id TEXT,title TEXT,work_id TEXT,doi TEXT,year INT,version_label TEXT)",
            "CREATE TABLE identifier_mappings (source_version_id TEXT,scheme TEXT,value TEXT)",
            "CREATE TABLE passages (id TEXT,source_version_id TEXT,kind TEXT,text TEXT,created_at TEXT)",
            "CREATE TABLE step_inputs (id TEXT,payload_json TEXT)",
            "CREATE TABLE kill_search_hits (kill_search_id TEXT,source_version_id TEXT,work_id TEXT,rank_key INT,kept INT,assessment_state TEXT,states_whole_claim INT,step_input_id TEXT)",
            "CREATE TABLE kill_search_query_records (kill_search_id TEXT,position INT,rank INT,source_version_id TEXT,work_id TEXT)",
        ):
            conn.execute(ddl)
        conn.execute("INSERT INTO kill_searches VALUES ('ks1','run1','completed',2,1,1,1)")
        conn.execute("INSERT INTO step_inputs VALUES (?,?)", ("input1", json.dumps({"passages": [passage]})))
        for i in (1, 2):
            conn.execute("INSERT INTO source_versions VALUES (?,?,?,?,?,?)", (f"sid-W{i}", "mobile robot", f"wrk-{i}", f"10.1/W{i}", 2025, "published"))
            conn.execute("INSERT INTO identifier_mappings VALUES (?,?,?)", (f"sid-W{i}", "openalex", f"W{i}"))
            conn.execute("INSERT INTO passages VALUES (?,?,?,?,?)", (f"p{i}", f"sid-W{i}", "abstract", text, "2026"))
            conn.execute("INSERT INTO kill_search_hits VALUES (?,?,?,?,?,?,?,?)", ("ks1", f"sid-W{i}", f"wrk-{i}", i, int(i == 1), "assessed" if i == 1 else None, 0 if i == 1 else None, "input1" if i == 1 else None))
            conn.execute("INSERT INTO kill_search_query_records VALUES (?,?,?,?,?)", ("ks1", 1, i, f"sid-W{i}", f"wrk-{i}"))
    manifest = k.funnel_counts.manifest(root)
    k.write(k.funnel_counts.copy_record_path(root), {"usable": True, "source": str(tmp_path / "original"),
            "destination": str(root), "source_manifest": manifest, "copy_manifest": manifest, "source_after_manifest": manifest})
    prep = tmp_path / "n-records.json"
    k.write(prep, {"records": [{"openalex_id": f"W{i}", "title": "mobile robot", "abstract": text} for i in (1, 2, 3)]})
    c = claim(ns=[labelled(f"W{i}") for i in (1, 2, 3)])
    data = snapshot(c)["frozen"]
    state = {"research_id": "r1", "claims": [{"key": "C1", "candidate_id": "c1"}]}
    matrix = {"search": search, "search_status": {"status": "open"}, "queries": [],
              "cells": {"sid-W1": {"e1": {"id": "cell1", "source_version_id": "sid-W1", "element_id": "e1", "relation": "explicit_support", "condition_alignment": "aligned"}}},
              "evidence": [{"source_version_id": "sid-W1", "matrix_cell_id": "cell1", "quote": "avoids obstacle"}]}
    def handler(request):
        path = request.url.path
        if path.endswith("/hits/sid-W1"):
            return httpx.Response(200, json={"passages": [passage]})
        if path.endswith("/kill-searches/ks1"):
            return httpx.Response(200, json=matrix)
        if path.endswith("/candidates/c1"):
            return httpx.Response(200, json={"current_version": 1, "searches": [{"id": "ks1", "run_id": "run1"}],
                "versions": [{"version": 1, "elements": [{"id": "e1", "text": "avoids obstacle"}]}]})
        return httpx.Response(200, json={"runs": [{"id": "run1", "status": "completed"}]})
    out = tmp_path / "out"
    api = k.API(FakeAPI.base, out, transport=httpx.MockTransport(handler), port_guard=lambda _: None)
    try:
        snap = k.snapshot(api, out, state, data, db, prep)
    finally:
        api.close()
    result = k.score(snap, unread="synthetic")
    assert [w["state"] for w in result["S1"]["C1"]["works"]] == ["retained", "returned but cut", "absent"]
    assert result["S4a"]["value"] == 1
    assert k.sample_cells(snap)[0]["work_id"] == "wrk-1"
    assert result["S6"]["C1"]["absent_N"][0]["missing_blocks"] == []
    assert not result["excluded_text_hash_mismatches"]


def test_provider_transport_counts_not_reserved_budget():
    snap = snapshot(claim())
    snap["claims"][0]["run"]["steps"] = [{"kind": "provider_search:openalex", "output": {"transport": {"attempts": 1, "sends": 1, "reserved": 3}}}]
    row = k.score(snap)["S5"]["claims"][0]
    assert row["provider_requests"] == row["provider_sends"] == 1
    assert row["budget_charged_provider_requests"] == 3


def test_reader_evidence_binding_and_partial_answer_boxes(tmp_path):
    snap = snapshot(claim())
    page = k.reader_packet(snap, tmp_path)
    assert k.checked_reader(snap, page) == page
    page["S4b"][0]["quotes"] = ["altered evidence"]
    with pytest.raises(k.Refused, match="differs"):
        k.checked_reader(snap, page)


def test_new_sessions_count_repairs_resends_not_historical():
    historical = {"id": "old", "connection": "another", "requested_model": "historical"}
    fresh = [{"id": f"new{i}", "connection": "codex", "requested_model": "gpt-5.6-luna",
              "resolved_model": "gpt-5.6-luna", "tool_item_types_json": "[]"} for i in range(3)]
    data = {"sessions": [historical, *fresh]}
    assert k.check_sessions(data, ["old"]) == 3
    fresh[-1]["resolved_model"] = "other-model"
    with pytest.raises(k.Refused, match="mismatch"):
        k.check_sessions(data, ["old"])
    fresh[-1]["resolved_model"] = "gpt-5.6-luna"
    fresh[-1]["tool_item_types_json"] = '["web_search"]'
    with pytest.raises(k.Refused, match="tool violation"):
        k.check_sessions(data, ["old"])


def test_clock_waits_for_zero_started_sessions_at_15_second_poll(tmp_path):
    api = FakeAPI(["completed", "completed"])
    now = [100]
    waits = []
    counts = iter([census(), dict(census(), started=[{"id": "inflight"}]), census(), census()])
    def wait(seconds):
        waits.append(seconds)
        now[0] += seconds
    state = {"research_id": "r1", "claims": [{"key": "C1", "candidate_id": "c1"}]}
    result = k.run_series(api, tmp_path, state, None, census=lambda *args: next(counts), clock=lambda: now[0], sleep=wait)
    assert waits == [15]
    assert result["started_at"] == 100 and result["ended_at"] == 115
    assert result["elapsed_seconds"] == 15 and result["stop_reason"] is None


def test_exclusion_uses_n_identity_but_sample_uses_product_work_id():
    snap = snapshot(claim(hits=[hit("W1", text="changed")]))
    h = snap["claims"][0]["hits"][0]
    h.update(work_id="internal-work", match_id="W1")
    snap["claims"][0]["cells"][0]["work_id"] = "internal-work"
    result = k.score(snap)
    assert result["excluded_text_hash_mismatches"][0]["work_id"] == "internal-work"
    assert result["S2"]["denominator"] == 0 and k.sample_cells(snap) == []
