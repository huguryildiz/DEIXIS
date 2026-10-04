"""Synthetic measurement-kit evidence; no sockets, provider, model or server."""
import copy
import hashlib
import json
from pathlib import Path
from types import SimpleNamespace

import httpx
import pytest

from scripts.p9_owed import measure_edit as kit
from scripts.p9_owed.funnel_counts import canonical, copy_record_path, manifest
from tests.test_report_edit_sequence import sequence_library


@pytest.fixture(autouse=True)
def no_network(monkeypatch):
    def refuse(*args, **kwargs):
        raise AssertionError("offline tests cannot connect sockets")
    monkeypatch.setattr("socket.socket.connect", refuse)
    monkeypatch.setattr("socket.create_connection", refuse)


@pytest.fixture
def frozen():
    path = Path("docs/product/p9-owed-s4-ek-e.json")
    sha = hashlib.sha256(path.read_bytes()).hexdigest()
    return kit.load_plan(path, sha)


def test_plan_hash_tamper(tmp_path, frozen):
    path = tmp_path / "plan.json"
    path.write_bytes(canonical(frozen))
    sha = hashlib.sha256(path.read_bytes()).hexdigest()
    assert kit.load_plan(path, sha)["report_id"] == frozen["report_id"]
    path.write_bytes(path.read_bytes() + b" ")
    with pytest.raises(kit.MeasurementRefused, match="hash mismatch"):
        kit.load_plan(path, sha)


@pytest.mark.parametrize("url", ["http://127.0.0.1:8765", "http://localhost:8873",
    "http://127.0.0.1:8873@evil.example", "https://127.0.0.1:8873", "http://127.0.0.1:8873/api",
    "http://127.0.0.1:8873?x=8765"])
def test_port_and_origin_refusal(url, tmp_path):
    with pytest.raises(kit.MeasurementRefused):
        kit.Client(url, tmp_path / "guard.jsonl")


def test_copy_record_refusal_and_hash(tmp_path):
    root = tmp_path / "copy"
    root.mkdir()
    (root / "library.sqlite").write_bytes(b"synthetic DB bytes")
    plan = {"library_sqlite_sha256": hashlib.sha256((root / "library.sqlite").read_bytes()).hexdigest()}
    with pytest.raises(OSError):
        kit.verify_copy(root, plan)
    m = manifest(root)
    record = {"usable": True, "destination": str(root), "source": str(tmp_path / "original"),
              "source_manifest": m, "copy_manifest": m, "source_after_manifest": m}
    copy_record_path(root).write_text(json.dumps(record))
    assert kit.verify_copy(root, plan) == root
    record["source"] = str(root)
    copy_record_path(root).write_text(json.dumps(record))
    with pytest.raises(kit.MeasurementRefused, match="usable copy"):
        kit.verify_copy(root, plan)
    record["source"] = str(tmp_path / "original")
    copy_record_path(root).write_text(json.dumps(record))
    (root / "library.sqlite").write_bytes(b"tampered")
    with pytest.raises(kit.MeasurementRefused, match="bytes changed"):
        kit.verify_copy(root, plan)


def test_protected_library_cannot_be_execution_target():
    with pytest.raises(kit.MeasurementRefused, match="immutable"):
        with kit.runtime_read(kit.PROTECTED):
            pytest.fail("opened protected fixture")


def test_client_csrf_and_guard_before_every_mutation(tmp_path):
    sequence = []
    def guard(log):
        sequence.append("guard")
    def handler(request):
        sequence.append(request.method)
        if request.url.path == "/api/session":
            return httpx.Response(200, json={"csrf_token": "synthetic"},
                                  headers={"set-cookie": "deixis_csrf=synthetic; Path=/"})
        assert request.headers["x-deixis-csrf"] == "synthetic"
        assert request.headers["origin"] == "http://127.0.0.1:8873"
        assert "deixis_csrf=synthetic" in request.headers["cookie"]
        return httpx.Response(200, json={})
    client = kit.Client("http://127.0.0.1:8873", tmp_path / "guard.jsonl",
                        transport=httpx.MockTransport(handler), guard=guard)
    try:
        client.session()
        for method in ("POST", "PUT", "DELETE"):
            client.call(method, "/api/synthetic", {})
        assert sequence == ["GET", "guard", "POST", "guard", "PUT", "guard", "DELETE"]
    finally:
        client.http.close()


@pytest.mark.parametrize("returncode,stdout,stderr,allowed", [(1,"","",True),
    (0,"p123\n","",False),(1,"","lsof error",False),(2,"","",False)])
def test_port_guard_json_fail_closed(tmp_path, monkeypatch, returncode, stdout, stderr, allowed):
    monkeypatch.setattr(kit.subprocess, "run", lambda *a, **k: SimpleNamespace(
        returncode=returncode, stdout=stdout, stderr=stderr))
    log = tmp_path / "guard.jsonl"
    if allowed:
        kit.port_guard(log)
    else:
        with pytest.raises(kit.MeasurementRefused, match="8765"):
            kit.port_guard(log)
    assert json.loads(log.read_text())["returncode"] == returncode


def marker(target="c1"):
    return {"operation":"A", "section_id":"V", "claim_id":None,
            "reason_code":"cell_changed", "via":"citation", "target_id":target}


@pytest.mark.parametrize("expected,observed,fp,fn", [([],[],(0,0),(0,0)),
    ([marker()],[],(0,0),(1,1)), ([],[marker()],(1,1),(0,0)),
    ([marker()],[marker("other")],(1,1),(1,1)),
    ([marker()],[marker()],(0,1),(0,1))])
def test_r19_denominators(expected, observed, fp, fn):
    plan = {"operations":[{"id":"A","api_call":{},"expected_stale_markers":expected}]}
    snapshot = {"operations":[{"id":"A","status":"measured", "observed_stale_markers":observed,
                               "invariants":{}, "cost":{}}]}
    scores = kit.score(plan, snapshot)["R19"]
    for key, pair in [("false_positive",fp),("false_negative",fn)]:
        assert (scores[key]["numerator"], scores[key]["denominator"]) == pair
        if pair[1] == 0:
            assert scores[key]["value"] == "ölçülemedi"


def test_score_synthetic_snapshot(frozen):
    snapshot = {"operations":[], "zero_started_verified":True, "total_wall_seconds":34}
    for i, op in enumerate(frozen["operations"]):
        if op["api_call"] is None:
            snapshot["operations"].append({"id":op["id"],"status":"sınanmadı","reason":op["reason"]})
        else:
            snapshot["operations"].append({"id":op["id"],"status":"measured",
                "observed_stale_markers":copy.deepcopy(op["expected_stale_markers"]),
                "invariants":{"active_citation_set":i != 0,"round_trip_equality":"ölçülemedi"},
                "cost":{"wall_seconds":2,"new_sessions":0,"tokens":0}})
    result = kit.score(frozen, snapshot)
    assert result["R18"] == {"numerator":1,"denominator":17,"value":1/17}
    assert result["R19"]["false_positive"]["numerator"] == 0
    assert result["R19"]["false_negative"]["numerator"] == 0
    assert len(result["excluded"]) == 1
    assert result["excluded"][0]["id"] == "E18"
    assert result["R21_total_wall_seconds"] == 34


def session(id, **extra):
    return {"id":id,"kind":"cell_recheck","connection":"codex","requested_model":"gpt-5.6-luna",
            "resolved_model":"gpt-5.6-luna","status":"completed","tool_item_types_json":"[]",**extra}


def test_stop_cap_only_new_sessions():
    old = [session("old"+str(i)) for i in range(50)]
    ids = {s["id"] for s in old}
    assert kit.stop_reason(ids,old+[session("n"+str(i)) for i in range(9)],2,launching_model=True) is None
    assert kit.stop_reason(ids,old+[session("n"+str(i)) for i in range(10)],2) == "10 new sessions cap"
    assert kit.stop_reason(ids,old,3600) == "60 minute clock exhausted"


@pytest.mark.parametrize("changes,reason", [({"kind":"report"},"forbidden model"),
    ({"resolved_model":"other"},"model mismatch"), ({"tool_item_types_json":"[\"command\"]"},"tool violation"),
    ({"status":"failed"},"terminal model error")])
def test_stop_failures(changes,reason):
    assert reason in kit.stop_reason(set(),[session("new",**changes)],3)


def test_costs_missing_tokens_are_not_zero():
    before={"sessions":[session("historical",token_usage_json='{"total":{"totalTokens":999}}')]}
    after={"sessions":before["sessions"]+[session("new",token_usage_json="{}")]}
    assert kit.costs(before,after,2)["tokens"] == "ölçülemedi"
    assert kit.costs(before,after,2)["new_sessions"] == 1


@pytest.mark.parametrize("run_root,step_root,resumed,status,expected", [
    ({"error":"client_timeout"},"client_timeout",False,"paused",True),
    ({"error":"client_timeout"},"client_timeout",True,"paused",False),
    ({"error":"client_timeout"},"quota_exhausted",False,"paused",False),
    ({"error":"quota_exhausted"},"client_timeout",False,"paused",False),
    ({"error":"client_timeout"},"client_timeout",False,"failed",False),
    ({"code":"unknown"},"client_timeout",False,"paused",False)])
def test_bounded_timeout_resume_roots(run_root,step_root,resumed,status,expected):
    import sqlite3
    conn=sqlite3.connect(":memory:")
    try:
        conn.execute("CREATE TABLE run_steps (run_id TEXT,status TEXT,error_json TEXT)")
        conn.execute("INSERT INTO run_steps VALUES ('run','failed',?)",(json.dumps(step_root),))
        run={"status":status,"error_json":json.dumps(run_root)}
        assert kit.timeout_resume_eligible(conn,"run",run,resumed) is expected
    finally:
        conn.close()


def test_failed_send_is_not_terminal_root_while_product_retries():
    assert kit.stop_reason(set(),[session("new",status="failed")],2,terminal_failures=False) is None
    assert kit.stop_reason(set(),[session("new",model_step_kind="model:report_review")],2,terminal_failures=False) == "forbidden model step"


def test_lsof_missing_is_recorded(tmp_path,monkeypatch):
    def missing(*a,**k):
        raise FileNotFoundError("lsof unavailable")
    monkeypatch.setattr(kit.subprocess,"run",missing)
    log=tmp_path/"guard.jsonl"
    with pytest.raises(kit.MeasurementRefused):
        kit.port_guard(log)
    assert json.loads(log.read_text())["returncode"] is None


def test_score_records_missing_operations(frozen):
    result=kit.score(frozen,{"operations":[]})
    assert result["R18"]["value"] == "ölçülemedi"
    assert len(result["excluded"]) == len(frozen["operations"])


def test_frozen_case_coverage_and_rule_lines(frozen):
    assert frozen["targets"]["claim_key"] == "V.1"
    assert len(frozen["targets"]["original_link_ids"]) >= 2
    assert frozen["library_sqlite_sha256"] == "ff37c851b59d592013fc8410c1e19b07b74b5093d0396d2938eaa01c86d9b63a"
    assert sum(op["kind"] == "recheck" for op in frozen["operations"]) == 3
    for op in frozen["operations"]:
        for basis in op["rule_basis"]:
            filename, loc=basis.rsplit(":",1)
            start=int(loc.split("-")[0])
            assert 0 < start <= len(Path(filename).read_text().splitlines())
        assert all(m["operation"] == op["id"] for m in op["expected_stale_markers"])
    assert all(m["reason_code"] != "edit_check_stale" for m in frozen["operations"][7]["expected_stale_markers"])
    assert any(m["reason_code"] == "edit_check_stale" for m in frozen["operations"][8]["expected_stale_markers"])


def test_execute_scripted_api_sequence(sequence_library, tmp_path):
    """Real report storage/view/export over MockTransport; no server or model."""
    from deixis.workflow.views import report_view
    from deixis.workflow.report.export import export_markdown
    lib=sequence_library
    rid, report=lib["research_id"],lib["report_id"]
    rp=f"/api/researches/{rid}/reports/{report}"
    view=report_view(lib["store"],rid,report)
    target=next(c for s in view["sections"] for c in s["claims"] if c["claim_key"] == "III.1")
    baseline=kit.stored_snapshot(lib["store"].conn,{"report_id":report,"research_id":rid})
    plan={"report_id":report,"research_id":rid,"report_api_path":rp,"file_sha256":"synthetic",
          "base_sha256":baseline["base_sha256"],"scope_sha256":baseline["scope_sha256"],
          "baseline_effective":baseline["effective"],"targets":{"claim_id":target["id"]},"operations":[]}
    for id,kind,method,path,body in [
        ("A","edit","PUT",rp+"/claims/"+target["id"],{"text":"Resource allocation is novel.","expected_version":"current"}),
        ("B","check","POST",rp+"/check-edits",{}),
        ("C","edit","PUT",rp+"/claims/"+target["id"],{"text":"Resource allocation has a second edit.","expected_version":"current"})]:
        plan["operations"].append({"id":id,"kind":kind,"api_call":{"method":method,"path":path,"body":body},
                                    "expected_target_link_ids":baseline["effective"][target["id"]],
                                    "target_ids":{},"expected_stale_markers":[]})
    def handler(request):
        if request.url.path == "/api/session":
            return httpx.Response(200,json={"csrf_token":"synthetic"})
        if request.method == "PUT":
            body=json.loads(request.content)
            lib["reports"].edit_claim(rid,report,target["id"],text=body["text"],restore_from=None,
                                     note=None,expected_version=body["expected_version"],idempotency_key=request.headers.get("Idempotency-Key"))
        elif request.method == "POST":
            assert request.url.path.endswith("/check-edits")
            lib["reports"].check_edits(rid,report)
        if request.url.path.endswith("/export"):
            return httpx.Response(200,text=export_markdown(lib["store"],rid,report)[0])
        return httpx.Response(200,json=report_view(lib["store"],rid,report))
    client=kit.Client("http://127.0.0.1:8873",tmp_path/"guard.jsonl",
                      transport=httpx.MockTransport(handler),guard=lambda log:None)
    try:
        result=kit.execute(plan,lib["settings"].data_dir,client,tmp_path/"result.json")
    finally:
        client.http.close()
    assert result["stop_reason"] is None
    assert result["zero_started_verified"]
    assert len(result["operations"]) == 3
    for row in result["operations"]:
        assert row["status"] == "measured"
        assert all(v is True or v == "ölçülemedi" for v in row["invariants"].values())
        assert row["cost"]["new_sessions"] == row["cost"]["tokens"] == 0
    assert result["operations"][1]["view"]["edit_check"]["current"]
    assert not result["operations"][2]["view"]["edit_check"]["current"]


def test_offline_plan_attests_pristine_copy_before_server_start(sequence_library,tmp_path):
    import shutil
    lib=sequence_library
    source=lib["settings"].data_dir
    # Only this test's synthetic library is checkpointed. The protected fixture
    # is never opened writable or checkpointed by the kit or its tests.
    lib["store"].conn.execute("PRAGMA wal_checkpoint(TRUNCATE)")
    root=tmp_path/"execution-copy"
    shutil.copytree(source,root)
    m=manifest(root)
    copy_record_path(root).write_text(json.dumps({"usable":True,"source":str(source),"destination":str(root),
        "source_manifest":m,"copy_manifest":m,"source_after_manifest":m}))
    plan={"version":1,"product_commit":"7188ec8","report_id":lib["report_id"],
          "research_id":lib["research_id"],"operations":[],
          "library_sqlite_sha256":hashlib.sha256((root/"library.sqlite").read_bytes()).hexdigest()}
    plan["base_sha256"]=kit.stored_snapshot(lib["store"].conn,plan)["base_sha256"]
    ops=tmp_path/"operations.json";ops.write_text(json.dumps(plan))
    sha=hashlib.sha256(ops.read_bytes()).hexdigest();out=tmp_path/"attestation.json"
    assert kit.main(["plan","--operations",str(ops),"--sha256",sha,"--data-dir",str(root),"--out",str(out)]) == 0
    attestation=json.loads(out.read_text())
    assert attestation["network_requests"] == 0
    assert attestation["data_dir"] == str(root)
    # Runtime locks change the manifest, but do not erase copy provenance.
    (root/"worker.lock").write_text("synthetic server lock")
    assert kit.verify_copy(root,plan,pristine=False) == root
    with pytest.raises(kit.MeasurementRefused,match="bytes changed"):
        kit.verify_copy(root,plan,pristine=True)
