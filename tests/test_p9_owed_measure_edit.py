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
        with kit.runtime_read(kit.PROTECTED, Path("/tmp")):
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
    plan = {"operations":[{"id":"A","api_call":{},"expected_stale_markers":expected,"invariants":[]}]}
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
                "invariants":{k:(i != 0 if k == "active_citation_set" else True) for k in op["invariants"]},
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
    assert kit.stop_reason(ids,old+[session("n"+str(i)) for i in range(10)],2) is None
    assert kit.stop_reason(ids,old+[session("n"+str(i)) for i in range(10)],2,launching_model=True) == "10 new sessions cap"
    assert kit.stop_reason(ids,old+[session("n"+str(i)) for i in range(11)],2) == "10 new sessions cap"
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
    plan['operations'].append(dict(id='E18',kind='backup_restore',api_call=None,requires=['C'],
        expected_target_link_ids=baseline['effective'][target['id']], expected_stale_markers=[],
        invariants=['active_citation_set','numbering','export','model_original_revision_bytes',
                    'foreign_keys','round_trip_equality']))
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
    ownership = []
    client=kit.Client("http://127.0.0.1:8873",tmp_path/"guard.jsonl",
                      transport=httpx.MockTransport(handler),guard=lambda log:None,
                      ownership=lambda:ownership.append('checked'))
    try:
        result=kit.execute(plan,lib["settings"].data_dir,client,tmp_path/"result.json")
    finally:
        client.http.close()
    assert result["stop_reason"] is None
    assert result["zero_started_verified"]
    assert len(result["operations"]) == 4
    for row in result["operations"]:
        assert row["status"] == "measured"
        assert all(v is True or v == "ölçülemedi" for v in row["invariants"].values())
        assert row["cost"]["new_sessions"] == row["cost"]["tokens"] == 0
    assert result["operations"][1]["view"]["edit_check"]["current"]
    assert not result["operations"][2]["view"]["edit_check"]["current"]
    assert len(ownership) >= 1 + 3 * 4 + 1  # start, before mutation, audit reads, final snapshot
    assert result['operations'][3]['invariants']['round_trip_equality'] is True


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
    sha=hashlib.sha256(ops.read_bytes()).hexdigest();out=tmp_path/"output"
    assert kit.main(["plan","--operations",str(ops),"--sha256",sha,"--data-dir",str(root),"--out",str(out)]) == 0
    attestation=json.loads((out/"plan.json").read_text())
    assert attestation["network_requests"] == 0
    assert attestation["data_dir"] == str(root)
    # Runtime locks change the manifest, but do not erase copy provenance.
    (root/"worker.lock").write_text("synthetic server lock")
    assert kit.verify_copy(root,plan,pristine=False) == root
    with pytest.raises(kit.MeasurementRefused,match="bytes changed"):
        kit.verify_copy(root,plan,pristine=True)


def test_cli_e18_real_offline_round_trip(sequence_library, tmp_path, monkeypatch):
    lib = sequence_library
    root = lib['settings'].data_dir
    before = kit.stored_snapshot(lib['store'].conn, lib)
    monkeypatch.setenv('DEIXIS_DATA_DIR', str(kit.LIVE))
    monkeypatch.setenv('OPENAI_API_KEY', 'synthetic-must-not-inherit')
    result = kit.round_trip(root, tmp_path / 'out')
    assert result['round_trip_equality'] is True
    assert set(result['report_tables']) == set(__import__('tests.test_report_edit_sequence', fromlist=['REPORT_TABLES']).REPORT_TABLES)
    assert {'runs', 'step_inputs', 'source_versions', 'cell_revisions'} <= set(result['linked_tables'])
    assert kit.stored_snapshot(lib['store'].conn, lib) == before
    for command, data in zip(result['commands'], (root, Path(result['restore_target']))):
        assert command['command'][:2] == ['/usr/bin/env', '-i']
        assert set(command['env']) == {'PATH', 'HOME', 'PYTHONPATH', 'DEIXIS_DATA_DIR', 'DEIXIS_REPO_ROOT',
                                      'PYTHON_KEYRING_BACKEND', 'PYTHONDONTWRITEBYTECODE'}
        assert command['env']['DEIXIS_DATA_DIR'] == str(data.resolve())
        assert not (Path(command['env']['DEIXIS_REPO_ROOT']) / '.env').exists()
        assert command['returncode'] == 0
    assert json.loads(Path(result['ledger']).read_text()) == result['commands']


def test_nonempty_restore_target_refused(tmp_path):
    out = tmp_path / 'out'; target = out / 'restored'; target.mkdir(parents=True)
    (target / 'unrelated.txt').write_text('keep')
    with pytest.raises(kit.MeasurementRefused, match='empty'):
        kit.empty_restore_target(out, target, tmp_path / 'data')


@pytest.mark.parametrize('path', [kit.LIVE, kit.LIVE / 'child', Path('/tmp/owner-backup/data'), Path.home()/'.local/share/deixis'])
def test_live_default_and_owner_data_refused(path):
    with pytest.raises(kit.MeasurementRefused):
        kit.safe_data(path)


def test_owner_backup_alias_is_refused_before_resolving(tmp_path):
    target = tmp_path / 'safe'; target.mkdir()
    alias = tmp_path / 'owner-backup'; alias.symlink_to(target,target_is_directory=True)
    with pytest.raises(kit.MeasurementRefused,match='owner-backup'):
        kit.safe_data(alias / 'data')


@pytest.mark.parametrize('kind', ['escape', 'symlink', 'data', 'live', 'owner', 'source', 'record'])
def test_output_and_guard_confinement(tmp_path, kind):
    out = tmp_path / 'out'; out.mkdir(); data = tmp_path / 'data'; data.mkdir()
    source = tmp_path / 'original'; source.mkdir(); record = tmp_path / 'copy.json'; record.write_text('{}')
    path = out / 'guard.jsonl'
    if kind == 'escape': path = tmp_path / 'guard.jsonl'
    elif kind == 'symlink':
        (out / 'link').symlink_to(source, target_is_directory=True); path = out / 'link/guard.jsonl'
    elif kind == 'data': out = data / 'out'; path = out / 'guard.jsonl'
    elif kind == 'live': out = kit.LIVE / 'out'; path = out / 'guard.jsonl'
    elif kind == 'owner': out = tmp_path / 'owner-backup/out'; path = out / 'guard.jsonl'
    elif kind == 'source': out = source / 'out'; path = out / 'guard.jsonl'
    elif kind == 'record': out = record; path = record / 'guard.jsonl'
    with pytest.raises(kit.MeasurementRefused):
        kit.output_path(out, path, data, source, record)


def test_runtime_sqlite_connects_only_private_copy(sequence_library, tmp_path, monkeypatch):
    root = sequence_library['settings'].data_dir
    out = tmp_path / 'out'
    original = kit.sqlite3.connect; connections = []
    def connect(database, **kwargs):
        assert str(root.resolve()) not in database
        assert str(out.resolve()) in database and database.endswith('?mode=ro')
        connections.append(database)
        return original(database, **kwargs)
    before = manifest(root)
    monkeypatch.setattr(kit.sqlite3, 'connect', connect)
    with kit.runtime_read(root, out) as conn:
        assert conn.execute('SELECT count(*) FROM reports').fetchone()[0] == 1
    assert connections and manifest(root) == before


def test_missing_frozen_invariant_is_unmeasured(frozen):
    op = frozen['operations'][0]
    record = dict(id=op['id'], status='measured', invariants={},
                  observed_stale_markers=op['expected_stale_markers'], cost={})
    result = kit.score(frozen, {'operations':[record]})
    assert result['R18']['value'] == kit.UNMEASURED
    assert result['R18']['denominator'] == 0
    assert result['excluded'][0]['status'] == kit.UNMEASURED
    assert result['excluded'][0]['missing_invariants'] == op['invariants']


def test_cli_operation_with_complete_invariants_is_scored(frozen):
    op = frozen['operations'][-1]
    record = dict(id=op['id'],status='measured',invariants={k:True for k in op['invariants']},
                  observed_stale_markers=op['expected_stale_markers'],cost={'new_sessions':0})
    result = kit.score(frozen,{'operations':[record]})
    assert result['R18'] == dict(numerator=0,denominator=1,value=0)
    assert result['operations'][0]['id'] == 'E18'


def test_export_rejects_consistently_wrong_view_and_text(sequence_library):
    from deixis.workflow.views import report_view
    from deixis.workflow.report.export import export_markdown
    lib = sequence_library; plan = dict(lib, targets={})
    view = report_view(lib['store'], lib['research_id'], lib['report_id'])
    claim = next(c for c in kit.claims_of(view).values() if c['text'])
    plan['targets'] = dict(claim_id=claim['id'], original_text='Frozen required text')
    op = dict(id='E', kind='export', api_call={'body':{}}); plan['operations'] = [op]
    state = kit.stored_snapshot(lib['store'].conn, plan); plan['base_sha256'] = state['base_sha256']
    export = export_markdown(lib['store'],lib['research_id'],lib['report_id'])[0]
    assert kit.invariants(plan,op,state,view,export)['export'] is False


@pytest.mark.parametrize('problem', ['other-library', 'other-owner', 'error'])
def test_listener_exclusive_ownership_and_record(tmp_path, monkeypatch, problem):
    root = tmp_path / 'data'; root.mkdir(); log = tmp_path / 'guard.jsonl'
    outputs = ['p123\n', f'p123\nn{root}/library.sqlite\n', 'p123\n']
    if problem == 'other-library': outputs[1] += 'n/tmp/other/library.sqlite\n'
    if problem == 'other-owner': outputs[2] += 'p456\n'
    def run(*args, **kwargs):
        return SimpleNamespace(returncode=2 if problem == 'error' else 0,
                               stdout=outputs.pop(0), stderr='')
    monkeypatch.setattr(kit.subprocess,'run',run)
    with pytest.raises(kit.MeasurementRefused):
        kit.server_owns_copy(root,'http://127.0.0.1:8873',log)
    assert json.loads(log.read_text())['event'] == 'exclusive_ownership'


@pytest.mark.parametrize('listing_index,returncode,empty_stdout,stderr,allowed', [
    (2, 0, False, '', True),
    (2, 1, False, '', True),
    (2, 1, True, '', False),
    (2, 2, False, '', False),
    (2, 1, False, 'lsof error', False),
    (0, 1, False, '', False),
    (1, 1, False, '', False),
    (0, 0, False, 'lsof error', False),
    (1, 0, False, 'lsof error', False),
])
def test_ownership_lsof_status_by_listing(tmp_path, monkeypatch, listing_index,
                                         returncode, empty_stdout, stderr, allowed):
    root = tmp_path / 'data'; root.mkdir(); log = tmp_path / 'guard.jsonl'
    commands = [
        ['lsof', '-nP', '-F', 'pn', '-iTCP:8873', '-sTCP:LISTEN'],
        ['lsof', '-nP', '-F', 'pn', '-p', '123'],
        ['lsof', '-nP', '-F', 'pn', '+D', str(root)],
    ]
    outputs = ['p123\n', f'p123\nn{root}/library.sqlite\n',
               f'p123\nn{root}/library.sqlite\n']
    calls = []
    def run(command, **kwargs):
        index = len(calls)
        assert command == commands[index]
        calls.append(command)
        return SimpleNamespace(
            returncode=returncode if index == listing_index else 0,
            stdout='' if index == listing_index and empty_stdout else outputs[index],
            stderr=stderr if index == listing_index else '')
    monkeypatch.setattr(kit.subprocess, 'run', run)
    if allowed:
        kit.server_owns_copy(root, 'http://127.0.0.1:8873', log)
    else:
        with pytest.raises(kit.MeasurementRefused):
            kit.server_owns_copy(root, 'http://127.0.0.1:8873', log)
    record = json.loads(log.read_text())
    assert record['exclusive'] is allowed
    assert record['records'][listing_index]['returncode'] == returncode


@pytest.mark.parametrize('failure', ['http', 'db', 'safety', 'unprocessable'])
def test_acceptance_skips_only_unprocessable(tmp_path, monkeypatch, failure):
    from contextlib import contextmanager
    @contextmanager
    def read(root, out): yield None
    baseline = dict(active_runs=[], sessions=[], base_sha256='base', scope_sha256='scope')
    monkeypatch.setattr(kit,'runtime_read',read)
    monkeypatch.setattr(kit,'stored_snapshot',lambda conn,plan:baseline)
    view = dict(id='report', sections=[dict(claims=[dict(id='claim',edited=False,version=1)])])
    plan = dict(file_sha256='synthetic', report_api_path='/api/report', targets={'claim_id':'claim'},
                base_sha256='base', scope_sha256='scope', operations=[
        dict(id='accept', kind='accept', cell_api_path='/api/cell', proposal_from='recheck',
             api_call=dict(method='POST',path='/api/accept',body={'expected_version':'current'})),
        dict(id='later',kind='export',api_call=None,reason='cannot be expressed')])
    def handler(request):
        if request.url.path == '/api/session': return httpx.Response(200,json={'csrf_token':'synthetic'})
        if request.url.path == '/api/cell':
            if failure == 'http': return httpx.Response(500)
            if failure == 'db': raise kit.sqlite3.DatabaseError('synthetic database failure')
            if failure == 'safety': raise kit.MeasurementRefused('synthetic safety refusal')
            return httpx.Response(200,json={'version':1,'pending_proposal':None})
        return httpx.Response(200,json={} if request.url.path == '/api/health' else view)
    client = kit.Client('http://127.0.0.1:8873',tmp_path/'guard.jsonl',
                        transport=httpx.MockTransport(handler),guard=lambda log:None)
    try: result = kit.execute(plan,tmp_path/'data',client,tmp_path/'result.json')
    finally: client.http.close()
    assert (result['stop_reason'] is None) == (failure == 'unprocessable')
    assert result['operations'][0]['status'] == (kit.UNTESTED if failure == 'unprocessable' else kit.UNMEASURED)


def test_tenth_session_is_observed_before_cancellation(tmp_path, monkeypatch):
    from contextlib import contextmanager
    import sqlite3
    conn = sqlite3.connect(':memory:'); conn.row_factory = sqlite3.Row
    conn.execute('CREATE TABLE runs(id TEXT,status TEXT,error_json TEXT,pause_reason TEXT)')
    conn.execute("INSERT INTO runs VALUES ('run','completed',NULL,NULL)")
    @contextmanager
    def read(root, out): yield conn
    fresh = [session(str(i),token_usage_json='{"total":{"totalTokens":1}}') for i in range(10)]
    states = iter([[],fresh[:9],fresh[:9],fresh,fresh,fresh])
    monkeypatch.setattr(kit,'runtime_read',read)
    monkeypatch.setattr(kit,'stored_snapshot',lambda c,p:dict(
        active_runs=[],sessions=next(states),base_sha256='base',scope_sha256='scope'))
    monkeypatch.setattr(kit,'invariants',lambda *args:{'observed':True})
    op = dict(id='tenth',kind='recheck',api_call=dict(method='POST',path='/api/recheck'),
              expected_stale_markers=[],invariants=['observed'])
    plan = dict(file_sha256='synthetic',report_api_path='/api/report',base_sha256='base',
                scope_sha256='scope',operations=[op])
    mutations = []
    def handler(request):
        if request.url.path == '/api/session': return httpx.Response(200,json={'csrf_token':'synthetic'})
        if request.method != 'GET': mutations.append(request.url.path)
        if request.url.path == '/api/recheck': return httpx.Response(200,json={'id':'run'})
        if request.url.path.endswith('/export'): return httpx.Response(200,text='synthetic')
        return httpx.Response(200,json={'id':'report','sections':[]})
    client = kit.Client('http://127.0.0.1:8873',tmp_path/'guard.jsonl',
                        transport=httpx.MockTransport(handler),guard=lambda log:None)
    try: result = kit.execute(plan,tmp_path/'data',client,tmp_path/'result.json')
    finally: client.http.close(); conn.close()
    assert result['stop_reason'] is None
    assert mutations == ['/api/recheck']
    assert result['operations'][0]['status'] == 'measured'
    assert result['operations'][0]['cost']['session_ids'] == ['9']
    assert kit.score(plan,result)['R18']['denominator'] == 1


def test_private_read_refuses_changing_source(sequence_library, tmp_path, monkeypatch):
    root = sequence_library['settings'].data_dir
    original = kit.shutil.copyfile
    def changing(source, target):
        result = original(source,target)
        if Path(source).name == 'library.sqlite':
            Path(source).touch()
        return result
    monkeypatch.setattr(kit.shutil,'copyfile',changing)
    with pytest.raises(kit.MeasurementRefused,match='changed during'):
        with kit.runtime_read(root,tmp_path/'out'): pytest.fail('read changing source')


@pytest.mark.parametrize('protection', ['keyring', 'bytecode'])
def test_e18_subprocess_isolation(sequence_library, tmp_path, monkeypatch, protection):
    original = kit.subprocess.run
    seen = []
    def run(command, **kwargs):
        if protection == 'keyring':
            assert 'PYTHON_KEYRING_BACKEND=keyring.backends.null.Keyring' in command
        else:
            assert 'PYTHONDONTWRITEBYTECODE=1' in command
            assert command[command.index(kit.sys.executable) + 1] == '-B'
        assert kwargs['env'] == {}
        seen.append(command)
        return original(command, **kwargs)
    monkeypatch.setattr(kit.subprocess, 'run', run)
    assert kit.round_trip(sequence_library['settings'].data_dir, tmp_path / 'out')['round_trip_equality']
    assert len(seen) == 2


def test_e18_timeout_records_termination(sequence_library, tmp_path, monkeypatch):
    monkeypatch.setattr(kit.time, 'monotonic', lambda: 3599.25)
    calls = []
    def blocked(command, **kwargs):
        calls.append(kwargs)
        assert kwargs['timeout'] == pytest.approx(.75)
        raise kit.subprocess.TimeoutExpired(command, kwargs['timeout'], output=b'partial', stderr=b'blocked')
    monkeypatch.setattr(kit.subprocess, 'run', blocked)
    out = tmp_path / 'out'
    with pytest.raises(kit.MeasurementRefused, match='product CLI timeout'):
        kit.round_trip(sequence_library['settings'].data_dir, out, deadline=3600)
    commands = json.loads(next(out.glob('e18-*/commands.json')).read_text())
    assert len(calls) == len(commands) == 1
    assert commands[0]['status'] == 'timed_out'
    assert commands[0]['termination'] == 'child killed and waited by subprocess.run'
    assert commands[0]['stdout'] == 'partial'


def test_e18_remaining_deadline_shrinks_for_restore(sequence_library, tmp_path, monkeypatch):
    original = kit.subprocess.run
    clock = iter([3590, 3599])
    monkeypatch.setattr(kit.time, 'monotonic', lambda: next(clock))
    timeouts = []
    def run(command, **kwargs):
        timeouts.append(kwargs['timeout'])
        return original(command, **kwargs)
    monkeypatch.setattr(kit.subprocess, 'run', run)
    result = kit.round_trip(sequence_library['settings'].data_dir, tmp_path / 'out', deadline=3600)
    assert result['round_trip_equality']
    assert timeouts == [10, 1]


def test_e18_timeout_reaps_actual_child(sequence_library, tmp_path, monkeypatch):
    import os
    original = kit.subprocess.run
    def blocked(command, **kwargs):
        # Exercise run()'s termination with a harmless child, never the product CLI.
        assert kwargs['timeout'] > 0
        kwargs['timeout'] = .5
        return original([kit.sys.executable, '-B', '-c',
                         'import os,time; print(os.getpid(),flush=True); time.sleep(30)'], **kwargs)
    monkeypatch.setattr(kit.subprocess, 'run', blocked)
    out = tmp_path / 'out'
    with pytest.raises(kit.MeasurementRefused, match='product CLI timeout'):
        kit.round_trip(sequence_library['settings'].data_dir, out)
    record = json.loads(next(out.glob('e18-*/commands.json')).read_text())[0]
    assert record['status'] == 'timed_out'
    pid = int(record['stdout'].strip())
    with pytest.raises(ProcessLookupError):
        os.kill(pid, 0)


def test_e18_run_deadline_and_timeout_failure_record(tmp_path, monkeypatch):
    from contextlib import contextmanager
    @contextmanager
    def read(root, out):
        yield None
    baseline = dict(active_runs=[], sessions=[], base_sha256='base', scope_sha256='scope')
    monkeypatch.setattr(kit, 'runtime_read', read)
    monkeypatch.setattr(kit, 'stored_snapshot', lambda *args: baseline)
    monkeypatch.setattr(kit.time, 'monotonic', lambda: 123)
    def timeout(root, out, *, deadline):
        assert deadline == 123 + kit.MAX_SECONDS
        raise kit.MeasurementRefused('60 minute clock exhausted: product CLI timeout')
    monkeypatch.setattr(kit, 'round_trip', timeout)
    plan = dict(file_sha256='synthetic', report_api_path='/api/report', base_sha256='base',
                scope_sha256='scope', operations=[dict(id='E18', kind='backup_restore', api_call=None)])
    client = kit.Client('http://127.0.0.1:8873', tmp_path / 'guard.jsonl',
                        transport=httpx.MockTransport(lambda request: httpx.Response(200,
                            json={'csrf_token': 'synthetic', 'sections': []})), guard=lambda log: None)
    try:
        result = kit.execute(plan, tmp_path / 'data', client, tmp_path / 'result.json')
    finally:
        client.http.close()
    assert result['operations'][0]['status'] == kit.UNMEASURED
    assert result['operations'][0]['reason'] == result['stop_reason']
    assert 'product CLI timeout' in result['stop_reason']
    assert result['final_verification']['status'] == 'recorded'
    assert result['zero_started_verified'] is True


@pytest.mark.parametrize('stage', ['initial', 'pre-operation', 'final'])
@pytest.mark.parametrize('failure', ['ownership', 'database', 'changing-source'])
def test_audit_read_failure_is_persisted(tmp_path, monkeypatch, stage, failure):
    from contextlib import contextmanager
    baseline = dict(active_runs=[], sessions=[], base_sha256='base', scope_sha256='scope')
    count = 0
    error = (kit.sqlite3.DatabaseError if failure == 'database' else kit.MeasurementRefused)
    def fail():
        raise error('synthetic ' + failure)
    @contextmanager
    def read(root, out):
        if failure != 'ownership' and count >= (1 if stage == 'initial' else 2):
            fail()
        yield None
    def ownership():
        nonlocal count
        count += 1
        if failure == 'ownership' and count >= (1 if stage == 'initial' else 2):
            fail()
    monkeypatch.setattr(kit, 'runtime_read', read)
    monkeypatch.setattr(kit, 'stored_snapshot', lambda *args: baseline)
    plan = dict(file_sha256='synthetic', report_api_path='/api/report', base_sha256='base',
                scope_sha256='scope', operations=[dict(id='audit', kind='export',
                    api_call=dict(method='GET', path='/api/report') if stage == 'pre-operation' else None)])
    def handler(request):
        return httpx.Response(200, json={'csrf_token': 'synthetic', 'sections': []})
    client = kit.Client('http://127.0.0.1:8873', tmp_path / 'guard.jsonl',
                        transport=httpx.MockTransport(handler), guard=lambda log: None, ownership=ownership)
    output = tmp_path / 'result.json'
    try:
        result = kit.execute(plan, tmp_path / 'data', client, output)
    finally:
        client.http.close()
    assert json.loads(output.read_text()) == result
    assert result['stop_reason'] == 'synthetic ' + failure
    assert result['operations'][0]['id'] == 'audit'
    if stage in {'initial', 'pre-operation'}:
        assert result['operations'][0]['status'] == kit.UNMEASURED
        assert result['operations'][0]['reason'] == result['stop_reason']
    assert result['final_verification']['status'] == kit.UNMEASURED
    assert result['final_verification']['reason'] == result['stop_reason']
    assert result['zero_started_verified'] is False
