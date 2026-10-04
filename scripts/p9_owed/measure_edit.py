"""Frozen D157 API sequence. Preparation/scoring are offline; run is operator-only.

Never serve the immutable report fixture. Run requires a separately recorded byte
copy and a server already owned by the operator. No adapter, provider, or server
is created by this module. Section stale marks have no claim ids in the API;
their frozen claim witnesses are descriptive, not additional observations.
"""
from __future__ import annotations

import argparse
from contextlib import contextmanager
import hashlib
import json
from pathlib import Path
import re
import sqlite3
import subprocess
import sys
import time
from urllib.parse import urlsplit

import httpx

if __package__ in (None, ""):
    sys.path.insert(0, str(Path(__file__).resolve().parents[2]))
from scripts.p9_owed.funnel_counts import (
    MeasurementRefused, canonical, checked_dir, copy_record_path, manifest,
    open_readonly, outside, write_json,
)

PROTECTED = Path(__file__).resolve().parents[2] / ".local/p9-owed/s4/e-data"
UNMEASURED = "ölçülemedi"
UNTESTED = "sınanmadı"
MAX_SECONDS = 3600
MAX_SESSIONS = 10


def digest(value):
    return hashlib.sha256(canonical(value)).hexdigest()


def load_plan(path: Path, sha256: str) -> dict:
    raw = path.read_bytes()
    if hashlib.sha256(raw).hexdigest() != sha256:
        raise MeasurementRefused("operation file hash mismatch")
    plan = json.loads(raw)
    if plan.get("version") != 1 or plan.get("product_commit") != "7188ec8":
        raise MeasurementRefused("unsupported frozen plan")
    ids = [o["id"] for o in plan["operations"]]
    if len(ids) != len(set(ids)):
        raise MeasurementRefused("duplicate operation ids")
    for op in plan["operations"]:
        for key in ("api_call", "target_ids", "expected_stale_markers", "rule_basis", "invariants"):
            if key not in op:
                raise MeasurementRefused(f"missing {key}: {op['id']}")
    return plan


def verify_copy(root: Path, plan: dict, *, pristine=True):
    root = checked_dir(root)
    record = json.loads(copy_record_path(root).read_text())
    if (record.get("usable") is not True or record.get("destination") != str(root)
            or record.get("source") == str(root)
            or record.get("source_manifest") != record.get("copy_manifest")
            or record.get("source_after_manifest") != record.get("copy_manifest")):
        raise MeasurementRefused("copy record does not establish a usable copy")
    entries = record["copy_manifest"]["files"]
    db_entry = next((r for r in entries if r["path"] == "library.sqlite"), {})
    if db_entry.get("sha256") != plan["library_sqlite_sha256"]:
        raise MeasurementRefused("copy is not the frozen report library")
    if pristine and manifest(root) != record["copy_manifest"]:
        raise MeasurementRefused("copy bytes changed before first operation")
    return root


def validate_url(url: str) -> str:
    parsed = urlsplit(url)
    if (parsed.scheme != "http" or parsed.hostname != "127.0.0.1"
            or parsed.port not in (8873, 8874) or parsed.username or parsed.password
            or parsed.path not in ("", "/") or parsed.query or parsed.fragment):
        raise MeasurementRefused("only http://127.0.0.1:8873 or :8874 allowed; port 8765 refused")
    return url.rstrip("/")


def port_guard(log: Path):
    try:
        result = subprocess.run(["lsof", "-nP", "-iTCP:8765", "-sTCP:LISTEN", "-F", "p"],
                                capture_output=True, text=True, check=False)
        record = {"event": "port_8765", "time_ns": time.time_ns(), "returncode": result.returncode,
                  "stdout": result.stdout, "stderr": result.stderr}
    except OSError as exc:
        record = {"event": "port_8765", "time_ns": time.time_ns(), "returncode": None,
                  "stdout": "", "stderr": str(exc)}
    with log.open("a", encoding="utf-8") as stream:
        stream.write(json.dumps(record) + "\n")
    if record["returncode"] != 1 or record["stdout"].strip() or record["stderr"].strip():
        raise MeasurementRefused("port 8765 not established free; see guard JSONL")


def server_owns_copy(root: Path, url: str):
    def pids(args):
        result = subprocess.run(["lsof", "-nP", "-F", "p", *args], capture_output=True, text=True)
        if result.returncode != 0 or result.stderr.strip():
            raise MeasurementRefused("cannot establish server/copy ownership with lsof")
        return {line[1:] for line in result.stdout.splitlines() if re.fullmatch(r"p\d+", line)}
    listeners = pids([f"-iTCP:{urlsplit(url).port}", "-sTCP:LISTEN"])
    holders = pids([str(root / "library.sqlite")])
    if len(listeners) != 1 or not listeners <= holders:
        raise MeasurementRefused("API listener does not own the recorded execution copy")


@contextmanager
def runtime_read(root: Path):
    if root.resolve() == PROTECTED.resolve():
        raise MeasurementRefused("immutable report fixture cannot be an execution target")
    path = root / "library.sqlite"
    if path.is_symlink() or not path.is_file() or path.stat().st_nlink != 1:
        raise MeasurementRefused("unsafe execution database")
    conn = sqlite3.connect(path.resolve().as_uri() + "?mode=ro", uri=True)
    conn.row_factory = sqlite3.Row
    try:
        conn.execute("PRAGMA query_only=ON")
        conn.execute("BEGIN")
        yield conn
    finally:
        conn.close()


def stored_snapshot(conn, plan):
    report = plan["report_id"]
    claims = [dict(r) for r in conn.execute(
        "SELECT c.* FROM report_claims c JOIN report_sections s ON s.id=c.report_section_id"
        " WHERE s.report_id=? ORDER BY s.ordinal,c.ordinal", (report,))]
    sections = [dict(r) for r in conn.execute(
        "SELECT * FROM report_sections WHERE report_id=? ORDER BY ordinal", (report,))]
    links = [dict(r) for r in conn.execute(
        "SELECT l.* FROM report_citation_links l JOIN report_claims c ON c.id=l.claim_id"
        " JOIN report_sections s ON s.id=c.report_section_id WHERE s.report_id=? ORDER BY l.rowid", (report,))]
    # Hash text/draft strings as stored, without JSON parsing or prose rewriting.
    base = {"claims": [{k: c[k] for k in c if k not in ("version", "current_revision_id")} for c in claims],
            "sections": sections, "links": links,
            "report": {k: v for k, v in dict(conn.execute("SELECT * FROM reports WHERE id=?", (report,)).fetchone()).items()
                       if k != "updated_at"}}
    sessions = [dict(r) for r in conn.execute(
        "SELECT m.id,m.run_id,m.status,m.connection,m.requested_model,m.resolved_model,"
        "m.token_usage_json,m.tool_item_types_json,r.kind,s.kind AS model_step_kind FROM model_sessions m"
        " JOIN runs r ON r.id=m.run_id JOIN run_steps s ON s.id=m.step_id ORDER BY m.rowid")]
    active = [dict(r) for r in conn.execute(
        "SELECT id,kind,status,error_json,pause_reason FROM runs WHERE status IN ('queued','running','pause_requested')")]
    effective = {}
    for claim in claims:
        revision = conn.execute("SELECT * FROM report_claim_revisions WHERE id=?", (claim["current_revision_id"],)).fetchone()
        original = [l["id"] for l in links if l["claim_id"] == claim["id"]]
        effective[claim["id"]] = original if revision is None or revision["link_count"] is None else [
            r[0] for r in conn.execute("SELECT link_id FROM report_claim_revision_links WHERE revision_id=?", (revision["id"],))]
    scope = dict(conn.execute("SELECT s.* FROM scope_revisions s JOIN researches r ON r.id=s.research_id"
                              " AND r.current_scope_revision=s.revision WHERE r.id=?", (plan["research_id"],)).fetchone())
    edit_state = {table: sorted((tuple(r) for r in conn.execute(f'SELECT * FROM "{table}"')), key=canonical)
                  for table in ("evidence_cells", "corpus_memberships", "selections", "table_rows", "table_columns",
                                "report_claim_revisions", "report_claim_revision_links", "report_edit_checks",
                                "report_stale_acknowledgements")}
    return {"base_sha256": digest(base), "scope_sha256": digest(scope), "effective": effective, "sessions": sessions,
            "edit_state_sha256": digest(edit_state),
            "active_runs": active, "foreign_key_violations": [tuple(r) for r in conn.execute("PRAGMA foreign_key_check")]}


def observed_markers(view):
    result = []
    for section in view["sections"]:
        for mark in section["evidence_changes"]["open"]:
            result.append({"section_id": section["section_id"], "claim_id": None,
                           "reason_code": mark["kind"], "via": mark["via"],
                           "target_id": mark.get("cell_id") or mark["source_version_id"]})
        for claim in section["claims"]:
            for basis in claim["edited_basis"]:
                result.append({"section_id": section["section_id"], "claim_id": claim["id"],
                               "reason_code": "edited_basis", "via": "claim_ref", "target_id": basis})
    if view.get("edit_check") and not view["edit_check"]["current"]:
        result.append({"section_id": None, "claim_id": None, "reason_code": "edit_check_stale",
                       "via": "fingerprint", "target_id": view["id"]})
    return result


def marker_key(mark):
    return tuple(mark.get(k) for k in ("section_id", "claim_id", "reason_code", "via", "target_id"))


def rate(numerator, denominator):
    return {"numerator": numerator, "denominator": denominator,
            "value": numerator / denominator if denominator else UNMEASURED}


def score(plan, snapshot):
    expected_by_id = {o["id"]: o for o in plan["operations"]}
    rows, excluded = [], []
    records = {r["id"]: r for r in snapshot["operations"]}
    if len(records) != len(snapshot["operations"]) or not records.keys() <= expected_by_id.keys():
        raise MeasurementRefused("duplicate or unknown snapshot operations")
    for op in plan["operations"]:
        record = records.get(op["id"], {"id": op["id"], "status": UNTESTED, "reason": "no recorded observation"})
        op = expected_by_id[record["id"]]
        if record["status"] != "measured" or op["api_call"] is None:
            excluded.append({"id": op["id"], "status": UNTESTED, "reason": record.get("reason", op.get("reason")),
                             "R21": record.get("cost", UNMEASURED)})
            continue
        expected = {marker_key(m) for m in op["expected_stale_markers"]}
        observed = {marker_key(m) for m in record["observed_stale_markers"]}
        checks = record["invariants"]
        rows.append({"id": op["id"], "R18": {"violated": [k for k, v in checks.items() if v is False],
                     "unmeasured": [k for k, v in checks.items() if v == UNMEASURED]},
                     "R19": {"false_positive": rate(len(observed - expected), len(observed)),
                             "false_negative": rate(len(expected - observed), len(expected))},
                     "R21": record["cost"]})
    return {"scope": "Single report and corpus; code behavior, not semantic support.",
            "R18": rate(sum(len(r["R18"]["violated"]) for r in rows), len(rows)),
            "R19": {key: rate(sum(r["R19"][key]["numerator"] for r in rows),
                               sum(r["R19"][key]["denominator"] for r in rows))
                    for key in ("false_positive", "false_negative")},
            "operations": rows, "excluded": excluded, "stop_reason": snapshot.get("stop_reason"),
            "R21_total_wall_seconds": snapshot.get("total_wall_seconds", UNMEASURED),
            "zero_started_verified": snapshot.get("zero_started_verified", False)}


def stop_reason(baseline_ids, sessions, elapsed, *, launching_model=False, terminal_failures=True):
    fresh = [s for s in sessions if s["id"] not in baseline_ids]
    if elapsed >= MAX_SECONDS:
        return "60 minute clock exhausted"
    if len(fresh) >= MAX_SESSIONS:
        return "10 new sessions cap"
    for s in fresh:
        if s["kind"] != "cell_recheck":
            return "forbidden model step"
        if s.get("model_step_kind", "model:cell_extraction") != "model:cell_extraction":
            return "forbidden model step"
        if s["connection"] != "codex" or s["requested_model"] != "gpt-5.6-luna" or (
                s["resolved_model"] not in (None, "gpt-5.6-luna")):
            return "model mismatch"
        if json.loads(s["tool_item_types_json"] or "[]"):
            return "tool violation"
        if terminal_failures and s["status"] not in ("started", "completed"):
            return f"terminal model error: {s['status']}"
    return None


def error_roots(value):
    if isinstance(value, str):
        return {value}
    if isinstance(value, list):
        return set().union(*(error_roots(item) for item in value)) if value else {"unreadable_root"}
    if isinstance(value, dict):
        for key in ("root_cause", "error", "cause"):
            if key in value:
                return error_roots(value[key])
    return {"unreadable_root"}


def timeout_resume_eligible(conn, run_id, run, resumed):
    if resumed or run["status"] != "paused":
        return False
    failed = conn.execute("SELECT error_json FROM run_steps WHERE run_id=?"
                          " AND status IN ('failed','outcome_unknown')", (run_id,)).fetchall()
    roots = error_roots(json.loads(run["error_json"] or "null"))
    for row in failed:
        roots |= error_roots(json.loads(row[0] or "null"))
    return bool(failed) and roots == {"client_timeout"}


class Client:
    def __init__(self, base_url, log, *, transport=None, guard=port_guard):
        self.base_url = validate_url(base_url)
        self.log, self.guard = log, guard
        self.http = httpx.Client(base_url=self.base_url, transport=transport, timeout=30, trust_env=False,
                                 follow_redirects=False)

    def session(self):
        response = self.http.get("/api/session")
        response.raise_for_status()
        self.http.headers["x-deixis-csrf"] = response.json()["csrf_token"]
        self.http.headers["Origin"] = self.base_url

    def call(self, method, path, body=None, *, key=None, expected_status=200):
        if not path.startswith("/api/") or ".." in path or "?" in path:
            raise MeasurementRefused("unsafe API path")
        if method != "GET":
            self.guard(self.log)
        response = self.http.request(method, path, json=body if method != "GET" else None,
                                     headers={"Idempotency-Key": key} if key else {})
        if response.status_code != expected_status:
            raise MeasurementRefused(f"{method} {path}: expected {expected_status}, got {response.status_code}")
        return response


def claims_of(view):
    return {c["id"]: c for s in view["sections"] for c in s["claims"]}


def invariants(plan, op, state, view, export):
    claims = claims_of(view)
    effective = all(set(state["effective"][cid]) == {e["link_id"] for e in c["evidence"]}
                    for cid, c in claims.items())
    target = op.get("expected_target_link_ids")
    if target is not None:
        effective &= {e["link_id"] for e in claims[plan["targets"]["claim_id"]]["evidence"]} == set(target)
    for cid, expected in plan.get("baseline_effective", {}).items():
        if cid != plan["targets"]["claim_id"]:
            effective &= {e["link_id"] for e in claims[cid]["evidence"]} == set(expected)
    numbers = {}
    valid_numbers = True
    for s in view["sections"]:
        for c in s["claims"]:
            for e in c["evidence"]:
                number = numbers.setdefault(e["source_version_id"], len(numbers) + 1)
                valid_numbers &= e["ref_number"] == number
    valid_numbers &= [(r["source_version_id"], r["number"]) for r in view["references"]] == list(numbers.items())
    from deixis.workflow.report.export import _md
    from deixis.workflow.report import export_text
    export_ok = True
    tr = export_text.is_turkish(view)
    for section in view["sections"]:
        heading = "## " + _md(export_text.heading(section["section_id"], tr)) + "\n"
        body = export.split(heading, 1)[1].split("\n## ", 1)[0] if heading in export else ""
        export_ok &= heading in export
        for c in section["claims"]:
            if c["text"]:
                suffix = ", ".join(f"[{n}]" for n in dict.fromkeys(e["ref_number"] for e in c["evidence"]))
                pattern = re.escape(_md(c["text"])) + (r" \([^\n]*?\)" if c.get("equation_ref") else "")
                pattern += re.escape(" " + suffix if suffix else "")
                export_ok &= re.search(pattern, body) is not None
    heading = "## " + export_text.references_heading(tr) + "\n"
    bibliography = export.split(heading, 1)[1] if heading in export else ""
    export_ok &= [int(n) for n in re.findall(r"^\[(\d+)\] ", bibliography, re.MULTILINE)] == [
        r["number"] for r in view["references"]]
    return {"active_citation_set": bool(effective), "numbering": bool(valid_numbers),
            "export": bool(export_ok), "model_original_revision_bytes": state["base_sha256"] == plan["base_sha256"],
            "foreign_keys": not state["foreign_key_violations"], "round_trip_equality": UNMEASURED}


def costs(before, after, elapsed):
    ids = {s["id"] for s in before["sessions"]}
    fresh = [s for s in after["sessions"] if s["id"] not in ids]
    tokens, missing = 0, []
    for s in fresh:
        usage = json.loads(s["token_usage_json"] or "null")
        total = (usage or {}).get("total", {}).get("totalTokens")
        if not isinstance(total, int):
            missing.append(s["id"])
        else:
            tokens += total
    return {"wall_seconds": elapsed, "new_sessions": len(fresh),
            "tokens": UNMEASURED if missing else tokens, "missing_token_sessions": missing,
            "session_ids": [s["id"] for s in fresh]}


def execute(plan, root, client, output):
    """Write evidence after each operation; never retry a proposal or repair it."""
    report_path = plan["report_api_path"]
    result = {"version": 1, "plan_sha256": plan["file_sha256"], "operations": [],
              "zero_started_verified": False, "stop_reason": None}
    started, resumed = None, False
    def read():
        with runtime_read(root) as conn:
            return stored_snapshot(conn, plan)
    baseline = read()
    if baseline["active_runs"] or any(s["status"] == "started" for s in baseline["sessions"]):
        raise MeasurementRefused("execution copy has active work")
    if baseline["base_sha256"] != plan["base_sha256"]:
        raise MeasurementRefused("report base bytes differ from freeze")
    if baseline["scope_sha256"] != plan["scope_sha256"]:
        raise MeasurementRefused("scope/model/effort differs from freeze")
    if plan.get("edit_state_sha256") and baseline["edit_state_sha256"] != plan["edit_state_sha256"]:
        raise MeasurementRefused("execution copy has pre-existing cell/source/edit changes")
    if plan.get("execution_baseline") and {s["id"] for s in baseline["sessions"]} != {
            s["id"] for s in plan["execution_baseline"]["sessions"]}:
        raise MeasurementRefused("new model sessions appeared before the first operation")
    ids = {s["id"] for s in baseline["sessions"]}
    client.session()
    health = client.call("GET", "/api/health").json()
    if plan.get("skill_package_hash") and health.get("skill_package_hash") != plan["skill_package_hash"]:
        raise MeasurementRefused("server method package differs from freeze")
    initial_view = client.call("GET", report_path).json()
    if any(c["edited"] for c in claims_of(initial_view).values()):
        raise MeasurementRefused("server report already edited")
    outcomes, revisions, proposal_runs = {}, {}, {}
    for op in plan["operations"]:
        row = {"id": op["id"], "status": UNTESTED}
        if op["api_call"] is None or any(outcomes.get(dep) != "measured" for dep in op.get("requires", [])):
            row["reason"] = op.get("reason", "prerequisite unprocessable")
        elif result["stop_reason"]:
            row["reason"] = result["stop_reason"]
        else:
            before = read()
            reason = stop_reason(ids, before["sessions"], 0 if started is None else time.monotonic()-started,
                                 launching_model=op["kind"] == "recheck", terminal_failures=False)
            if reason:
                result["stop_reason"] = row["reason"] = reason
            elif before["scope_sha256"] != plan["scope_sha256"]:
                result["stop_reason"] = row["reason"] = "scope/model/effort changed during sequence"
            else:
                tick = time.monotonic()
                operation_run = None
                try:
                    method, path = op["api_call"]["method"], op["api_call"]["path"]
                    body = dict(op["api_call"].get("body", {}))
                    view = client.call("GET", report_path).json()
                    if "expected_version" in body:
                        if op["kind"] in ("recheck", "accept"):
                            cell = client.call("GET", op["cell_api_path"]).json()
                            body["expected_version"] = cell["version"]
                        else:
                            body["expected_version"] = claims_of(view)[plan["targets"]["claim_id"]]["version"]
                    if op["kind"] == "accept":
                        proposal = cell["pending_proposal"]
                        if (proposal is None or proposal.get("output_status") != "structurally_valid"
                                or proposal["run_id"] != proposal_runs[op["proposal_from"]]):
                            raise MeasurementRefused("unusable proposal; no manual correction or regeneration")
                        path = path.replace("{proposal_id}", proposal["id"])
                    if body.get("restore_from") == "{revision_id}":
                        body["restore_from"] = revisions[op["revision_from"]]
                    if op["kind"] == "acknowledge":
                        section = next(s for s in view["sections"] if s["section_id"] == op["target_ids"]["section_id"])
                        expected_keys = {marker_key(m) for m in op["acknowledge_markers"]}
                        located = {}
                        for m in section["evidence_changes"]["open"]:
                            key = marker_key({"section_id": section["section_id"], "claim_id": None,
                                              "reason_code": m["kind"], "via": m["via"],
                                              "target_id": m.get("cell_id") or m["source_version_id"]})
                            if key in expected_keys:
                                located[key] = m["key"]
                        if not expected_keys or located.keys() != expected_keys:
                            raise MeasurementRefused("frozen acknowledgement keys are not all observable")
                        body["change_keys"] = sorted(located.values())
                    if op["kind"] == "purge_refusal":
                        with runtime_read(root) as conn:
                            purge_before = digest({table: sorted((tuple(r) for r in conn.execute(f'SELECT * FROM "{table}"')), key=canonical)
                                                   for table in ("events", "source_versions", "source_assets", "passages",
                                                                 "corpus_memberships", "selections", "cell_revisions")})
                    if started is None:
                        started = time.monotonic()
                    reason = stop_reason(ids, read()["sessions"], time.monotonic()-started,
                                         launching_model=op["kind"] == "recheck", terminal_failures=False)
                    if reason:
                        raise MeasurementRefused(reason)
                    response = client.call(method, path, body, key="d157:"+op["id"],
                                           expected_status=op["api_call"].get("expected_status", 200))
                    if op["kind"] == "recheck":
                        run_id = response.json()["id"]
                        operation_run = run_id
                        proposal_runs[op["id"]] = run_id
                        while True:
                            state = read()
                            reason = stop_reason(ids, state["sessions"], time.monotonic()-started, terminal_failures=False)
                            if reason:
                                raise MeasurementRefused(reason)
                            with runtime_read(root) as conn:
                                run = dict(conn.execute("SELECT status,error_json,pause_reason FROM runs WHERE id=?", (run_id,)).fetchone())
                            if run["status"] not in ("queued", "running", "pause_requested"):
                                if run["status"] != "completed":
                                    with runtime_read(root) as conn:
                                        eligible = timeout_resume_eligible(conn, run_id, run, resumed)
                                    if not eligible:
                                        raise MeasurementRefused(f"terminal run error: {run}")
                                    if any(s["status"] == "started" for s in state["sessions"]):
                                        raise MeasurementRefused("timeout resume refused while sessions remain started")
                                    wake = time.monotonic() + 600
                                    row["resume"] = {"reason": "all terminal roots client_timeout", "wait_seconds": 600}
                                    while time.monotonic() < wake:
                                        state = read()
                                        reason = stop_reason(ids, state["sessions"], time.monotonic()-started,
                                                             launching_model=True, terminal_failures=False)
                                        if reason:
                                            raise MeasurementRefused(reason)
                                        time.sleep(min(15, max(0, wake-time.monotonic())))
                                    client.call("POST", f"/api/runs/{run_id}/resume")
                                    resumed = True
                                    continue
                                if not any(s["status"] == "started" for s in state["sessions"]):
                                    break
                            time.sleep(15)
                    client.guard(client.log)
                    after = read()
                    view = client.call("GET", report_path).json()
                    if op["kind"] in ("edit", "restore_revision"):
                        revisions[op["id"]] = claims_of(view)[plan["targets"]["claim_id"]]["revisions"][-1]["id"]
                    export = client.call("GET", report_path+"/export").text
                    reason = stop_reason(ids, after["sessions"], time.monotonic()-started, terminal_failures=False)
                    cost = costs(before, after, time.monotonic()-tick)
                    if cost["missing_token_sessions"]:
                        reason = reason or "unreadable token counters"
                    row.update(status="measured", observed_stale_markers=observed_markers(view),
                               invariants=invariants(plan, op, after, view, export), cost=cost,
                               before=before, after=after, view=view, export=export)
                    if op["kind"] == "purge_refusal":
                        with runtime_read(root) as conn:
                            purge_after = digest({table: sorted((tuple(r) for r in conn.execute(f'SELECT * FROM "{table}"')), key=canonical)
                                                  for table in ("events", "source_versions", "source_assets", "passages",
                                                                "corpus_memberships", "selections", "cell_revisions")})
                        row["invariants"]["refusal_no_change"] = before == after and purge_before == purge_after
                    if op["id"] == "E12":
                        current = client.call("GET", op["cell_api_path"]).json()["current"]["id"]
                        marks = next(s for s in view["sections"] if s["section_id"] == plan["targets"]["section_id"])["evidence_changes"]["open"]
                        row["invariants"]["acknowledge_new_change"] = any(
                            m["key"] == f"cell:{plan['targets']['retained_cell']['id']}:{current}" for m in marks)
                    if reason:
                        result["stop_reason"] = reason
                except (MeasurementRefused, httpx.HTTPError, OSError, ValueError, KeyError, sqlite3.DatabaseError) as exc:
                    row["reason"] = str(exc)
                    # An unusable acceptance is a skipped case, not a new model attempt.
                    if op["kind"] != "accept":
                        result["stop_reason"] = str(exc)
                    if operation_run:
                        try:
                            client.call("POST", f"/api/runs/{operation_run}/cancel")
                            row["stop_control"] = "cancel requested; zero-started verification still required"
                        except (MeasurementRefused, httpx.HTTPError, OSError) as cancel_error:
                            row["stop_control"] = str(cancel_error)
                    try:
                        row["cost"] = costs(before, read(), time.monotonic()-tick)
                    except (OSError, ValueError, sqlite3.DatabaseError):
                        row["cost"] = UNMEASURED
        outcomes[op["id"]] = row["status"]
        result["operations"].append(row)
        write_json(output, result)
    client.guard(client.log)
    final = read()
    result["zero_started_verified"] = not any(s["status"] == "started" for s in final["sessions"])
    result["total_wall_seconds"] = 0 if started is None else time.monotonic()-started
    result["final"] = final
    reason = stop_reason(ids, final["sessions"], result["total_wall_seconds"], terminal_failures=False)
    result["stop_reason"] = result["stop_reason"] or reason
    if not result["zero_started_verified"]:
        result["stop_reason"] = result["stop_reason"] or "started sessions remain; operator must stop and verify exit"
    write_json(output, result)
    return result


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    sub = parser.add_subparsers(dest="command", required=True)
    for command in ("plan", "run", "snapshot", "score"):
        p = sub.add_parser(command)
        p.add_argument("--operations", type=Path, required=True)
        p.add_argument("--sha256", required=True)
        p.add_argument("--out", type=Path, required=True)
        if command in ("plan", "run", "snapshot"):
            p.add_argument("--data-dir", type=Path, required=True)
        if command in ("run", "snapshot"):
            p.add_argument("--base-url", default="http://127.0.0.1:8873")
            p.add_argument("--guard-log", type=Path, required=True)
        if command == "run":
            p.add_argument("--operator-go", action="store_true", help="attest frozen reviews and coordinator go")
            p.add_argument("--baseline", type=Path, required=True, help="offline plan output for this execution copy before server startup")
            p.add_argument("--baseline-sha256", required=True)
        if command == "score":
            p.add_argument("--snapshot", type=Path, required=True)
    args = parser.parse_args(argv)
    try:
        plan = load_plan(args.operations, args.sha256)
        plan["file_sha256"] = args.sha256
        if args.command == "score":
            snapshot = json.loads(args.snapshot.read_text())
            if snapshot["plan_sha256"] != args.sha256:
                raise MeasurementRefused("snapshot plan hash mismatch")
            out = outside(args.out, args.snapshot, args.operations, PROTECTED)
            write_json(out, score(plan, snapshot))
            return 0
        root = verify_copy(args.data_dir, plan, pristine=args.command == "plan")
        out = outside(args.out, root, PROTECTED, args.operations)
        if args.command == "plan":
            with open_readonly(root) as conn:
                state = stored_snapshot(conn, plan)
            if state["base_sha256"] != plan["base_sha256"]:
                raise MeasurementRefused("frozen original bytes mismatch")
            write_json(out, {"status": "planned", "plan_sha256": args.sha256,
                             "data_dir": str(root),
                             "copy_record_sha256": hashlib.sha256(copy_record_path(root).read_bytes()).hexdigest(),
                             "operations": plan["operations"], "baseline": state, "network_requests": 0})
            return 0
        if root == PROTECTED.resolve():
            raise MeasurementRefused("protected e-data must remain immutable; use a separately recorded execution copy")
        if args.command == "run" and not args.operator_go:
            raise MeasurementRefused("frozen reviews and coordinator go must be attested with --operator-go")
        if args.command == "run":
            raw = args.baseline.read_bytes()
            if hashlib.sha256(raw).hexdigest() != args.baseline_sha256:
                raise MeasurementRefused("baseline attestation hash mismatch")
            attestation = json.loads(raw)
            if (attestation.get("status") != "planned" or attestation.get("data_dir") != str(root)
                    or attestation.get("plan_sha256") != args.sha256
                    or attestation.get("copy_record_sha256") != hashlib.sha256(copy_record_path(root).read_bytes()).hexdigest()
                    or attestation.get("network_requests") != 0):
                raise MeasurementRefused("baseline attestation does not identify this pristine execution copy")
            plan["execution_baseline"] = attestation["baseline"]
            out = outside(out, args.baseline)
            if args.guard_log.resolve() == args.baseline.resolve():
                raise MeasurementRefused("guard log cannot overwrite baseline attestation")
        pin = subprocess.run(["git", "diff", "--quiet", "7188ec8", "--", "backend", "methods", "contracts"],
                             cwd=Path(__file__).resolve().parents[2], capture_output=True)
        if pin.returncode != 0:
            raise MeasurementRefused("product files differ from 7188ec8 or Git pin cannot be checked")
        log = outside(args.guard_log, root, PROTECTED, args.operations)
        if log == out:
            raise MeasurementRefused("guard log and output must differ")
        log.parent.mkdir(parents=True, exist_ok=True)
        url = validate_url(args.base_url)
        port_guard(log)
        server_owns_copy(root, url)
        client = Client(url, log)
        try:
            if args.command == "run":
                result = execute(plan, root, client, out)
                return 1 if result["stop_reason"] else 0
            client.session()
            with runtime_read(root) as conn:
                state = stored_snapshot(conn, plan)
            view = client.call("GET", plan["report_api_path"]).json()
            write_json(out, {"plan_sha256": args.sha256, "state": state, "view": view, "operations": [],
                             "note": "Read-only capture; no operation executed, so score denominators are empty.",
                             "observed_stale_markers": observed_markers(view)})
            return 0
        finally:
            client.http.close()
    except (OSError, ValueError, KeyError, sqlite3.DatabaseError, httpx.HTTPError) as exc:
        print(f"{UNMEASURED}: {exc}", file=sys.stderr)
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
