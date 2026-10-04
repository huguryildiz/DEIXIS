"""K6 measurement kit; freeze §6 / Ek K and §1.3–1.9, §1.11.

Mapping (stored evidence, never a literature-absence verdict):
 C1 Lyapunov MPC + CBF; C2 deep-learning prediction + NMPC; C3 scenario trees;
 C4 10 ms condition; C5 ten physical robots condition; C6 nearest work unknown.
 S1: each N work absent / returned but cut / retained, independently.
 S2: open claims / claims with a retained assessed labelled element witness.
 S3: false closed / labelled claims without a whole-claim N witness; genuine
     non-N closing witnesses are counted separately. Every closing witness is read.
 S4a: located quotes / all published cell quotes (exact substring in actual
      supplied passages); changed frozen supplied-text hashes exclude works.
 S4b: supports / partial / not_supports on up to 20 published quoted cells,
      sorted (claim key, search id, work id, element id), Random(20261002).
 S5: first request to terminal + zero started sessions; 120 new sessions,
     180 minutes, unchanged per-claim preview model/transport caps.
 S6: model blocks and provider queries, all/some/no lexical block matches;
     NFKD → ASCII → casefold → [^\\W_]+; consecutive term-token matching.

plan/score/reader-packet are offline. setup/run mutate only the explicit local
API (8873 default; 8765 refused). No command starts a server or reader model.
run is single-use, never resumes, and cancels at most once only after the time
cap and a fresh still-running observation. Every API request is journalled;
POSTs and final snapshots require a fail-closed /usr/sbin/lsof port check.
The API has no complete session census: run requires --db, an explicitly given
isolated library.sqlite, read mode=ro in fresh transactions (including WAL).
Snapshot DB reads require funnel_counts.copy's verified byte-copy sidecar and
mode=ro&immutable=1; originals and nonempty WAL copies are refused.
reader.json is the single isolated reader page: fill answer boxes and pass it
to score --reader. key.json is separate and must never be given to the reader.
Partial/missing reader judgements and zero denominators are ölçülemedi.
Freeze review/push/coordinator gates are external prerequisites, not asserted
by this kit. Decomposition is not measured. No scientific validation is claimed.
"""

from __future__ import annotations

import argparse
from collections import Counter
from contextlib import contextmanager
import hashlib
import json
from pathlib import Path
import random
import re
import sqlite3
import subprocess
import sys
import time
import unicodedata
from urllib.parse import urlsplit

import httpx

if __package__ in (None, ""):
    sys.path.insert(0, str(Path(__file__).resolve().parents[2]))
    sys.path.insert(0, str(Path(__file__).resolve().parents[2] / "backend"))

from scripts.p9_owed import funnel_counts, prep_lookup

ROOT = Path(__file__).resolve().parents[2]
FROZEN = ROOT / "docs/product/p9-owed-k6-ek-k.json"
N_RECORDS = ROOT / ".local/p9-owed/prep/k6-n-ids.json"
UNMEASURED = "ölçülemedi"
TERMINAL = {"completed", "failed", "paused", "cancelled"}
ACTIVE = {"queued", "running", "pause_requested"}
FIELDS = ("claim_statement", "elements", "conditions", "critical_assumption",
          "nearest_simple_explanation", "validation_plan")
SUPPORT = {"supports", "partial", "not_supports"}
MODEL = {"connection": "codex", "requested_model": "gpt-5.6-luna", "reasoning_effort": "medium"}


class Refused(ValueError):
    """Evidence or safety precondition failed; do not continue the series."""


def sha(text):
    return hashlib.sha256(text.encode("utf-8")).hexdigest()


def load(path):
    return json.loads(Path(path).read_text(encoding="utf-8"))


def write(path, data):
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(data, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")


def frozen(path=FROZEN):
    data = load(path)
    if [c["key"] for c in data["claims"]] != [f"C{i}" for i in range(1, 7)]:
        raise Refused("Ek K requires C1–C6 in frozen order")
    for c in data["claims"]:
        payload = {k: v for k, v in c.items() if k not in {"key", "payload_sha256", "N", "nearest_work_unknown"}}
        if sha(json.dumps(payload, sort_keys=True, ensure_ascii=False)) != c["payload_sha256"]:
            raise Refused(f"{c['key']}: payload_sha256 mismatch")
        if not 0 < len(c["claim_statement"]) <= 2000:
            raise Refused(f"{c['key']}: owner text exceeds 2000 characters; truncation forbidden")
    if data["s4b_seed"] != 20261002:
        raise Refused("S4b seed differs from freeze")
    return data


def checked_base(base):
    p = urlsplit(base)
    if p.port == 8765:
        raise Refused("port 8765 is forbidden")
    if (p.scheme != "http" or p.hostname not in {"127.0.0.1", "localhost", "::1"}
            or p.username or p.password or p.query or p.fragment or p.path not in {"", "/"}):
        raise Refused("base must be a local HTTP origin without credentials or path")
    return base.rstrip("/")


def port_check(out, runner=subprocess.run):
    command = ["/usr/sbin/lsof", "-nP", "-iTCP:8765", "-sTCP:LISTEN", "-Fp"]
    record = {"time": time.time(), "command": command}
    try:
        r = runner(command, capture_output=True, text=True, timeout=10)
        record.update(returncode=r.returncode, stdout=r.stdout, stderr=r.stderr)
        record["free"] = r.returncode == 1 and not r.stdout and not r.stderr
    except (OSError, subprocess.SubprocessError) as exc:
        record.update(free=False, error=type(exc).__name__)
    with (Path(out) / "port-checks.jsonl").open("a", encoding="utf-8") as f:
        f.write(json.dumps(record) + "\n")
    if not record["free"]:
        raise Refused("lsof did not establish port 8765 free; see port-checks.jsonl")
    return record


class API:
    def __init__(self, base, out, *, transport=None, port_guard=port_check):
        self.base = checked_base(base)
        self.out = Path(out)
        self.out.mkdir(parents=True, exist_ok=True)
        self.client = httpx.Client(base_url=self.base, timeout=60, transport=transport,
                                   trust_env=False, follow_redirects=False)
        self.guard = port_guard
        self.csrf = None
        self.before_post = None

    def close(self):
        self.client.close()

    def request(self, method, path, body=None, key=None):
        if method == "POST":
            if not self.csrf:
                self.csrf = self.get("/api/session")["csrf_token"]
            self.guard(self.out)
        row = {"time": time.time(), "method": method, "path": path,
               "base": self.base, "idempotency_key": key, "body": body}
        if method == "POST" and self.before_post is not None:
            self.before_post()
        # Persist intent before send, including uncertain deliveries. CSRF is never logged.
        self._log(dict(row, event="request"))
        try:
            headers = {}
            if method == "POST":
                headers["x-deixis-csrf"] = self.csrf
                headers["Idempotency-Key"] = key
            response = self.client.request(method, path, json=body, headers=headers)
            self._log(dict(row, event="response", status_code=response.status_code))
            response.raise_for_status()
            return response.json()
        except (httpx.HTTPError, ValueError) as exc:
            self._log(dict(row, event="error", error=type(exc).__name__))
            raise Refused("API request failed; no automatic retry; see ledger.jsonl") from exc

    def _log(self, row):
        with (self.out / "ledger.jsonl").open("a", encoding="utf-8") as f:
            f.write(json.dumps(row, ensure_ascii=False) + "\n")
            f.flush()

    def get(self, path):
        return self.request("GET", path)

    def post(self, path, body, key):
        return self.request("POST", path, body, key)


def candidate_path(state, claim):
    return f"/api/researches/{state['research_id']}/candidates/{claim['candidate_id']}"


def view_runs(api, rid):
    view = api.get(f"/api/researches/{rid}")
    if "runs" not in view:
        raise Refused("API lacks run state")
    return view["runs"]


def assert_idle(api, rid):
    if any(r["status"] in ACTIVE for r in view_runs(api, rid)):
        raise Refused("unexpected active run")


def setup(api, out, data):
    out = Path(out)
    target = out / "setup.json"
    if target.exists() or (out / "setup-started.json").exists():
        raise Refused("setup already attempted; inspect saved ids/ledger, do not recreate research")
    if api.get("/api/researches"):
        raise Refused("K6 setup requires an empty isolated library")
    write(out / "setup-started.json", {"base": api.base, "time": time.time()})
    body = {"question": data["question"], "language_hint": data["language"],
            "model_connection": "codex", "requested_model": "gpt-5.6-luna",
            "reasoning_effort": "medium", "source_scope": "academic",
            "seed_mode": "question_only", "effort": "standard", "review_mode": "off"}
    created = api.post("/api/researches", body, "k6-research")
    state = {"base": api.base, "research_id": created["research"]["id"],
             "frozen_sha256": hashlib.sha256(FROZEN.read_bytes()).hexdigest(), "claims": []}
    write(target, state)
    assert_idle(api, state["research_id"])
    for c in data["claims"]:
        path = f"/api/researches/{state['research_id']}/candidates"
        card = api.post(path, {"origin": "owner_text", "text": c["claim_statement"]}, f"k6-{c['key']}-candidate")
        entry = {"key": c["key"], "candidate_id": card["id"]}
        state["claims"].append(entry)
        write(target, state)
        assert_idle(api, state["research_id"])
        if card["current_version"] != 0 or card["active_run"]:
            raise Refused("new candidate must be version 0 with no active run")
        card = api.post(candidate_path(state, entry) + "/versions",
                        {k: c[k] for k in FIELDS} | {"expected_version": 0}, f"k6-{c['key']}-version")
        assert_idle(api, state["research_id"])
        if card["current_version"] != 1 or card["active_run"]:
            raise Refused("candidate must be version 1 with no active run")
        current = next(v for v in card["versions"] if v["id"] == card["current_version_id"])
        if current["origin"] != "human_edit":
            raise Refused("version origin differs from human_edit")
        entry["version_id"] = current["id"]
        write(target, state)
    return state


def safe_db(path):
    p = Path(path).absolute()
    # Never follow a link into another checkout or the owner's application data.
    if p.is_symlink() or any(parent.is_symlink() for parent in p.parents):
        raise Refused("database path contains a symlink")
    p = p.resolve()
    temporary = p.is_relative_to(Path("/tmp").resolve())
    if not (p.is_relative_to(ROOT) or temporary) or p.name != "library.sqlite" or p.stat().st_nlink != 1:
        raise Refused("--db must be an isolated library.sqlite in this checkout or /tmp")
    return p


@contextmanager
def copy_db(path):
    p = safe_db(path)
    root = p.parent
    record = load(funnel_counts.copy_record_path(root))
    if (record.get("usable") is not True or record.get("destination") != str(root)
            or record.get("source") == str(root)
            or record.get("source_manifest") != record.get("copy_manifest")
            or record.get("source_after_manifest") != record.get("copy_manifest")
            or funnel_counts.manifest(root) != record.get("copy_manifest")):
        raise Refused("copy record/manifest does not establish a usable byte copy")
    with funnel_counts.open_readonly(root) as conn:
        yield conn


def rows(conn, sql, args=()):
    return [dict(r) for r in conn.execute(sql, args)]


def session_rows(db, rid):
    if db is None:
        raise Refused("API has no complete session census; --db required for read-only SQLite counting")
    p = safe_db(db)
    with sqlite3.connect(p.as_uri() + "?mode=ro", uri=True) as conn:
        conn.row_factory = sqlite3.Row
        conn.execute("PRAGMA query_only=ON")
        conn.execute("BEGIN")
        found = rows(conn, "SELECT * FROM model_sessions WHERE research_id = ?", (rid,))
        active = rows(conn, "SELECT id FROM runs WHERE status IN ('queued','running','pause_requested')")
        started = rows(conn, "SELECT id FROM model_sessions WHERE status = 'started'")
    return {"sessions": found, "active": active, "started": started, "source": "SQLite mode=ro"}


def check_sessions(census, baseline):
    new = [s for s in census["sessions"] if s["id"] not in baseline]
    for s in new:
        if (s["connection"] != "codex" or s["requested_model"] != "gpt-5.6-luna"
                or s.get("resolved_model") not in {None, "gpt-5.6-luna"}
                or json.loads(s.get("tool_item_types_json") or "[]")):
            raise Refused("session model mismatch or tool violation")
    return len(new)


def run_series(api, out, state, db, *, clock=time.time, sleep=time.sleep, census=session_rows):
    out = Path(out)
    path = out / "run.json"
    if path.exists():
        raise Refused("series already attempted; rerun/resume forbidden")
    first = census(db, state["research_id"])
    if first["active"] or first["started"]:
        raise Refused("active runs or started sessions before series")
    baseline = [s["id"] for s in first["sessions"]]
    result = {"started_at": None, "ended_at": None, "baseline_session_ids": baseline,
              "new_sessions": 0, "session_source": first["source"], "claims": [],
              "cancel_requests": 0, "stop_reason": None}
    write(path, result)
    try:
        for c in state["claims"]:
            assert_idle(api, state["research_id"])
            if result["started_at"] is not None and (clock() - result["started_at"] >= 10800 or result["new_sessions"] >= 120):
                raise Refused("series cap reached before next claim")
            cp = candidate_path(state, c)
            card = api.get(cp)
            if card["searches"] or card["current_version"] != 1:
                raise Refused("candidate was already searched or edited")
            preview = api.get(cp + "/kill-search/plan")
            if preview["version"] != 1 or any(m != ["codex", "gpt-5.6-luna", "medium"] for m in preview["model"].values()):
                raise Refused("preview version/model differs from freeze")
            entry = {"key": c["key"], "preview": preview, "requested_at": clock()}
            result["claims"].append(entry)
            def start_clock():
                entry["requested_at"] = clock()
                if result["started_at"] is None:
                    result["started_at"] = entry["requested_at"]
                write(path, result)
            if isinstance(api, API):
                # CSRF acquisition and lsof are preparation. Start the K6
                # clock at POST admission, after both, immediately before send.
                api.before_post = start_clock
            elif result["started_at"] is None:
                result["started_at"] = entry["requested_at"]
            write(path, result)
            try:
                run = api.post(cp + "/kill-search", {"preview_fingerprint": preview["preview_fingerprint"]}, f"k6-{c['key']}-kill-search")
            finally:
                if isinstance(api, API):
                    api.before_post = None
            entry["run_id"] = run["id"]
            write(path, result)
            while True:
                found = view_runs(api, state["research_id"])
                known = {e.get("run_id") for e in result["claims"]}
                if any(r["id"] not in known for r in found):
                    raise Refused("unexpected run appeared during the series")
                run = next(r for r in found if r["id"] == entry["run_id"])
                entry["run"] = run
                current = census(db, state["research_id"])
                result["new_sessions"] = check_sessions(current, baseline)
                entry["observed_at"] = clock()
                write(path, result)
                if any(r["status"] in ACTIVE and r["id"] != run["id"] for r in found):
                    raise Refused("unexpected concurrent run")
                if run["status"] in TERMINAL:
                    if not current["started"] and not current["active"]:
                        if c == state["claims"][-1] or run["status"] != "completed":
                            result["ended_at"] = clock()
                    if run["status"] != "completed":
                        raise Refused(f"terminal run {run['status']}; stop series, never resume/cancel paused")
                    if result["new_sessions"] > 120:
                        raise Refused("120 new session cap exceeded at terminal observation")
                    if not current["started"] and not current["active"]:
                        break
                elapsed = clock() - result["started_at"]
                if elapsed >= 10800:
                    fresh = next(r for r in view_runs(api, state["research_id"]) if r["id"] == run["id"])
                    if fresh["status"] == "running" and result["cancel_requests"] == 0:
                        result["cancel_requests"] = 1
                        write(path, result)
                        api.post(f"/api/runs/{run['id']}/cancel", {}, "k6-time-cap-cancel")
                    raise Refused("180 minute series time cap; cancellation is not proof of drain")
                if result["new_sessions"] >= 120:
                    raise Refused("120 new session stop threshold; in-flight overshoot remains recorded")
                sleep(15)
        final = census(db, state["research_id"])
        result["new_sessions"] = check_sessions(final, baseline)
        if final["started"] or final["active"]:
            raise Refused("final run/session census is not drained")
        result["ended_at"] = clock()
        result["elapsed_seconds"] = result["ended_at"] - result["started_at"]
    except (Refused, OSError, sqlite3.Error, KeyError, StopIteration) as exc:
        result["stop_reason"] = str(exc) or type(exc).__name__
        result["stopped_at"] = clock()
        result["elapsed_seconds"] = (result["ended_at"] or result["stopped_at"]) - result["started_at"] if result["started_at"] is not None else None
        write(path, result)
        raise Refused(result["stop_reason"]) from exc
    write(path, result)
    return result


def identity(source, labelled):
    ids = source.get("identifiers", [])
    doi = (source.get("doi") or "").casefold().removeprefix("https://doi.org/")
    for n in labelled:
        if doi and doi == (n.get("doi") or "").casefold():
            return n["openalex_id"]
        if any(i["scheme"] == "openalex" and i["value"].rstrip("/").split("/")[-1] == n["openalex_id"] for i in ids):
            return n["openalex_id"]
    return source.get("work_id") or source["source_version_id"]


def db_source(conn, sid):
    source = rows(conn, "SELECT * FROM source_versions WHERE id = ?", (sid,))[0]
    source["source_version_id"] = sid
    source["identifiers"] = rows(conn, "SELECT scheme,value FROM identifier_mappings WHERE source_version_id = ?", (sid,))
    abstracts = rows(conn, "SELECT text FROM passages WHERE source_version_id = ? AND kind = 'abstract' ORDER BY created_at,id", (sid,))
    source["abstract"] = abstracts[0]["text"] if abstracts else None
    return source


def n_texts(data, path):
    """Hashes alone cannot produce S6 tokens; load only hash-verified prep records."""
    found = {}
    records = load(path)["records"]
    for c in data["claims"]:
        for n in c["N"]:
            matches = [r for r in records if r.get("openalex_id") == n["openalex_id"]]
            if len(matches) != 1:
                raise Refused(f"N preparation text missing/ambiguous: {n['openalex_id']}")
            r = prep_lookup.supplied_text(matches[0])
            if (r["provider_abstract_sha256"] != n["provider_abstract_sha256"]
                    or r["supplied_text_sha256"] != n["supplied_text_sha256"]):
                raise Refused(f"N preparation text differs from frozen hashes: {n['openalex_id']}")
            found[n["openalex_id"]] = {"title": r["title"], "abstract": r["abstract"],
                                         "source": str(path), "supplied_text_sha256": r["supplied_text_sha256"]}
    return found


def snapshot(api, out, state, data, db=None, n_records=N_RECORDS):
    out = Path(out)
    api.guard(out)
    assert_idle(api, state["research_id"])
    if db is None:
        raise Refused("API lacks rank-cut hits, returned abstracts and global started-session census; --db verified byte copy required")
    with copy_db(db) as conn:
        if rows(conn, "SELECT id FROM model_sessions WHERE status='started'") or rows(conn, "SELECT id FROM runs WHERE status IN ('queued','running','pause_requested')"):
            raise Refused("snapshot requires zero started sessions and zero active runs")
        snap = {"kind": "K6 snapshot v1", "frozen": data, "claims": [],
                "N_texts": n_texts(data, n_records),
                "series": load(out / "run.json") if (out / "run.json").exists() else {},
                "copy_record": load(funnel_counts.copy_record_path(Path(db).resolve().parent)),
                "session_source": "verified byte-copy SQLite", "captured_at": time.time()}
        if snap["series"]:
            sessions = rows(conn, "SELECT * FROM model_sessions WHERE research_id=?", (state["research_id"],))
            total = check_sessions({"sessions": sessions}, snap["series"]["baseline_session_ids"])
            snap["series"]["new_sessions_at_snapshot"] = total
            snap["series"]["in_flight_overshoot_sessions"] = max(0, total - snap["series"].get("new_sessions", 0))
            snap["series"]["new_sessions"] = total
        for c, expected in zip(state["claims"], data["claims"], strict=True):
            if c["key"] != expected["key"]:
                raise Refused("setup claim order differs from freeze")
            cp = candidate_path(state, c)
            card = api.get(cp)
            if card["current_version"] != 1:
                raise Refused("candidate changed after setup")
            if not card["searches"]:
                snap["claims"].append({"key": c["key"], "unmeasured_reason": "not run"})
                continue
            if len(card["searches"]) != 1:
                raise Refused("multiple searches violate single-series freeze")
            search = card["searches"][0]
            kid = search["id"]
            matrix = api.get(cp + f"/kill-searches/{kid}")
            stored = rows(conn, "SELECT * FROM kill_searches WHERE id=?", (kid,))
            if not stored or any(stored[0][k] != matrix["search"][k] for k in ("run_id", "outcome", "found", "kept", "rank_cut", "hits_recorded")):
                raise Refused("copy/API search state differs; take a fresh verified copy")
            hits = []
            for hit in rows(conn, "SELECT * FROM kill_search_hits WHERE kill_search_id=? ORDER BY rank_key", (kid,)):
                source = db_source(conn, hit["source_version_id"])
                hit.update(source=source, work_id=source.get("work_id") or hit["source_version_id"],
                           match_id=identity(source, expected["N"]))
                if hit["kept"]:
                    ev = api.get(cp + f"/kill-searches/{kid}/hits/{hit['source_version_id']}")
                    hit["passages"] = ev["passages"]
                    if hit["assessment_state"] == "assessed":
                        payload = rows(conn, "SELECT payload_json FROM step_inputs WHERE id=?", (hit["step_input_id"],))
                        if not payload or json.loads(payload[0]["payload_json"])["passages"] != ev["passages"]:
                            raise Refused("API/copy supplied passages differ")
                hits.append(hit)
            records = []
            for r in rows(conn, "SELECT * FROM kill_search_query_records WHERE kill_search_id=? ORDER BY position,rank", (kid,)):
                source = db_source(conn, r["source_version_id"])
                records.append(dict(r, source=source, match_id=identity(source, expected["N"])))
            cells = []
            elements = {e["id"]: e for v in card["versions"] if v["version"] == 1 for e in v["elements"]}
            for sid, by_element in matrix["cells"].items():
                hit = next(h for h in hits if h["source_version_id"] == sid)
                for eid, cell in by_element.items():
                    quotes = [e for e in matrix["evidence"] if e["matrix_cell_id"] == cell["id"]]
                    cells.append(dict(cell, claim_key=c["key"], kill_search_id=kid, work_id=hit["work_id"],
                                      source=hit["source"],
                                      element=elements[eid], quotes=quotes, passages=hit["passages"], published=True))
            run = next(r for r in view_runs(api, state["research_id"]) if r["id"] == search["run_id"])
            all_sessions = rows(conn, "SELECT id FROM model_sessions WHERE run_id=?", (run["id"],))
            baseline = set(snap["series"].get("baseline_session_ids", []))
            run["measured_new_sessions"] = (sum(s["id"] not in baseline for s in all_sessions)
                                            if "baseline_session_ids" in snap["series"] else UNMEASURED)
            snap["claims"].append({"key": c["key"], "kill_search_id": kid, "matrix": matrix,
                                   "element_ids": list(elements),
                                   "status": matrix["search_status"]["status"], "hits": hits, "records": records,
                                   "cells": cells, "hits_complete": bool(stored[0]["hits_recorded"]),
                                   "S1_source": "verified byte-copy kill_search_hits + kill_search_query_records",
                                   "blocks": matrix["search"]["query_block"], "queries": matrix["queries"], "run": run})
        assert_idle(api, state["research_id"])
    write(out / "snapshot.json", snap)
    return snap


def tokens(text):
    folded = unicodedata.normalize("NFKD", text or "").encode("ascii", "ignore").decode().casefold()
    return tuple(re.findall(r"[^\W_]+", folded))


def term_matches(term, sequence):
    term = tokens(term)
    return bool(term) and any(sequence[i:i + len(term)] == term for i in range(len(sequence) - len(term) + 1))


def metric(n, d, reason=None):
    return {"count": n, "denominator": d, "value": n / d if d and not reason else UNMEASURED,
            "reason": reason or ("zero denominator" if not d else None)}


def supplied(hit):
    passages = hit.get("passages", [])
    if passages:
        # The abstract path is exactly prep_lookup.supplied_text; actual PDF
        # passages are already frozen/capped by the application. Never join
        # passages when locating a quote (a spliced quote must not pass).
        texts = [p["text"] for p in passages]
        kind = passages[0].get("kind", passages[0].get("locator", {}).get("kind"))
        if len(passages) == 1 and kind == "abstract":
            text = prep_lookup.supplied_text({"abstract": texts[0]})["supplied_text"]
        else:
            text = "\n\n".join(texts)
        return texts, sha(text)
    abstract = hit.get("source", {}).get("abstract")
    if abstract is not None:
        text = prep_lookup.supplied_text({"abstract": abstract})["supplied_text"]
        # Returned/cut records were not delivered to the model. This hash can
        # check frozen provider text but is never quote-location evidence.
        return [], sha(text) if text is not None else None
    return [], None


def exclusions(snap):
    out = []
    for c in snap["claims"]:
        nset = next(e["N"] for e in snap["frozen"]["claims"] if e["key"] == c["key"])
        for hit in c.get("hits", []):
            n = next((n for n in nset if n["openalex_id"] == hit.get("match_id", hit["work_id"])), None)
            if n:
                _, digest = supplied(hit)
                if digest != n["supplied_text_sha256"]:
                    out.append({"claim_key": c["key"], "work_id": hit["work_id"],
                                "match_id": hit.get("match_id", hit["work_id"]),
                                "actual_hash": digest, "frozen_hash": n["supplied_text_sha256"]})
    return out


def cell_key(cell):
    return (cell["claim_key"], cell["kill_search_id"], cell["work_id"], cell["element_id"])


def sample_cells(snap):
    excluded = {(e["claim_key"], e["work_id"]) for e in exclusions(snap)}
    universe = sorted((cell for c in snap["claims"] for cell in c.get("cells", [])
                       if cell.get("published") and cell["quotes"]
                       and (c["key"], cell["work_id"]) not in excluded), key=cell_key)
    return random.Random(20261002).sample(universe, min(20, len(universe)))


def closing_witnesses(c):
    if c.get("status") != "closed":
        return []
    # Only genuinely closing hits: all elements explicit and aligned, plus
    # whole-claim evidence. Merely states_whole_claim is insufficient.
    result = []
    for h in c.get("hits", []):
        cells = [cell for cell in c.get("cells", []) if cell["source_version_id"] == h["source_version_id"]]
        required = set(c.get("element_ids", [cell["element_id"] for cell in cells]))
        if (h.get("states_whole_claim") and cells and required == {cell["element_id"] for cell in cells}
                and all(cell["relation"] == "explicit_support" and cell["condition_alignment"] == "aligned" for cell in cells)):
            evidence = [e for e in c["matrix"]["evidence"] if e["source_version_id"] == h["source_version_id"] and e["matrix_cell_id"] is None]
            result.append({"id": f"{c['key']}:{c['kill_search_id']}:{h['source_version_id']}", "work_id": h["work_id"],
                           "match_id": h.get("match_id", h["work_id"]),
                           "source": h["source"], "quotes": evidence, "passages": h.get("passages", [])})
    return result


def reader_page(snap):
    sample = sample_cells(snap)
    page = {"instructions": "Model reading, not human verification. Read only this page. Fill S3 answer with states_whole_claim / does_not_state_whole_claim / unclear; fill S4b with supports / partial / not_supports. Judge supplied quotes jointly against claim, relation and conditions. Do not use outside knowledge.",
            "S3": [], "S4b": []}
    for c in snap["claims"]:
        claim = next(e for e in snap["frozen"]["claims"] if e["key"] == c["key"])
        for w in closing_witnesses(c):
            page["S3"].append({"id": w["id"], "claim": {k: claim[k] for k in FIELDS},
                               "title": w["source"]["title"], "quotes": [q["quote"] for q in w["quotes"]],
                               "supplied_passages": [p["text"] for p in w["passages"]],
                               "answer": "", "reason": ""})
    for i, cell in enumerate(sample):
        claim = next(e for e in snap["frozen"]["claims"] if e["key"] == cell["claim_key"])
        page["S4b"].append({"id": f"sample-{i + 1}", "claim": claim["claim_statement"],
                            "source": {k: v for k, v in cell.get("source", {}).items() if k in {"title", "year", "version_label", "source_version_id"}},
                            "conditions": claim["conditions"], "element": cell["element"],
                            "relation": cell["relation"], "condition_alignment": cell["condition_alignment"],
                            "quotes": [q["quote"] for q in cell["quotes"]],
                            "supplied_passages": [p["text"] for p in cell["passages"]],
                            "answer": "", "reason": ""})
    return page


def reader_packet(snap, out):
    page = reader_page(snap)
    sample = sample_cells(snap)
    write(Path(out) / "reader.json", page)
    write(Path(out) / "key.json", {"frozen": snap["frozen"], "snapshot_sha256": sha(json.dumps(snap, sort_keys=True, ensure_ascii=False)),
                                  "sample": {f"sample-{i + 1}": cell_key(c) for i, c in enumerate(sample)}})
    return page


def checked_reader(snap, page):
    expected = reader_page(snap)
    # The isolated page contains its own answer boxes. Bind the answers to the
    # exact evidence page rather than accepting a different sample's ids.
    stripped = json.loads(json.dumps(page))
    for section in ("S3", "S4b"):
        for row in stripped.get(section, []):
            row["answer"] = ""
            row["reason"] = ""
    if stripped != expected:
        raise Refused("reader page evidence/sample differs from this snapshot")
    return page


def s6(c, absent):
    raw = c.get("blocks")
    if raw is None:
        return {"status": UNMEASURED, "reason": "model blocks unavailable"}
    blocks = {k: v for k, v in raw.items() if k in {"setting", "task"}}
    if not blocks or any(not terms for terms in blocks.values()):
        return {"status": UNMEASURED, "reason": "model blocks missing or empty", "blocks": raw}
    def missing(source):
        sequence = tokens((source.get("title") or "") + " " + (source.get("abstract") or ""))
        return [k for k, terms in blocks.items() if not any(term_matches(t["term"], sequence) for t in terms)]
    counts = Counter()
    for r in c.get("records", []):
        source = r.get("source", {})
        if not source.get("title") or not source.get("abstract"):
            counts["missing_title_or_abstract"] += 1
        else:
            no = missing(source)
            counts["all_blocks" if not no else "no_blocks" if len(no) == len(blocks) else "some_blocks"] += 1
    denom = sum(counts[k] for k in ("all_blocks", "some_blocks", "no_blocks"))
    return {"blocks": raw, "compiled_queries": c.get("queries", []), "number_of_blocks": len(blocks),
            "terms_per_block": {k: len(v) for k, v in blocks.items()},
            "returned_records": {k: metric(counts[k], denom) for k in ("all_blocks", "some_blocks", "no_blocks")},
            "missing_title_or_abstract": counts["missing_title_or_abstract"],
            "absent_N": [{"work_id": n["openalex_id"], "missing_blocks": missing(n) if n.get("title") and n.get("abstract") else UNMEASURED,
                          "reason": None if n.get("title") and n.get("abstract") else "frozen input has no abstract text; hash cannot be tokenized"} for n in absent],
            "limit": "lexical diagnostic, not provider-index reproduction or causal evidence"}


def score(snap, reader=None, unread=None):
    excluded = exclusions(snap)
    removed = {(e["claim_key"], e["work_id"]) for e in excluded}
    removed_labels = {(e["claim_key"], e["match_id"]) for e in excluded}
    reading3 = {r["id"]: r.get("answer") for r in (reader or {}).get("S3", [])}
    reading4 = {r["id"]: r.get("answer") for r in (reader or {}).get("S4b", [])}
    result = {"scope": "Single series, six claims, one model; evaluated subset and supplied text only. Decomposition unmeasured; open means no match in assessed supplied text.",
              "excluded_text_hash_mismatches": excluded, "S1": {}, "S6": {}, "S3_closing_quotes": []}
    s2n = s2d = s3n = s3d = unlabelled = 0
    s3_missing = False
    witness_reading_missing = False
    located = total = quote_free = 0
    excluded_cells = 0
    for c in snap["claims"]:
        expected = next(e for e in snap["frozen"]["claims"] if e["key"] == c["key"])
        nset = [n for n in expected["N"] if (c["key"], n["openalex_id"]) not in removed_labels]
        states = []
        for n in nset:
            hits = [h for h in c.get("hits", []) if h.get("match_id", h["work_id"]) == n["openalex_id"]]
            returned = any(r.get("match_id", r["work_id"]) == n["openalex_id"] for r in c.get("records", [])) or bool(hits)
            value = "retained" if any(h["kept"] for h in hits) else "returned but cut" if hits else "absent"
            if not c.get("hits_complete") and not hits:
                value = UNMEASURED
            if returned and not hits:
                value = UNMEASURED  # merge not published, never infer rank-cut
            states.append({"work_id": n["openalex_id"], "state": value, "source": c.get("S1_source", UNMEASURED)})
        counts = Counter(r["state"] for r in states)
        result["S1"][c["key"]] = {"works": states, "categories": {k: metric(counts[k], len(states), "incomplete hit evidence" if counts[UNMEASURED] else None) for k in ("absent", "returned but cut", "retained")}}
        assessed = {h.get("match_id", h["work_id"]) for h in c.get("hits", []) if h["kept"] and h["assessment_state"] == "assessed"}
        if any(n["expected_relation"] in {"whole claim", "some elements"} and n["openalex_id"] in assessed for n in nset):
            s2d += 1
            s2n += c.get("status") == "open"
        eligible3 = bool(nset) and bool(c.get("status")) and not any(n["expected_relation"] == "whole claim" for n in nset)
        witnesses = closing_witnesses(c)
        result["S3_closing_quotes"].extend(witnesses)
        if c.get("status") == "closed" and (not witnesses or any(reading3.get(w["id"]) not in {"states_whole_claim", "does_not_state_whole_claim"} for w in witnesses)):
            witness_reading_missing = True
        valid = [w for w in witnesses if (c["key"], w["work_id"]) not in removed]
        genuine = [w for w in valid if reading3.get(w["id"]) == "states_whole_claim"]
        unlabelled += sum(w["match_id"] not in {n["openalex_id"] for n in expected["N"]} for w in genuine)
        if eligible3:
            s3d += 1
            if c.get("status") == "closed":
                complete = bool(valid) and all(reading3.get(w["id"]) in {"states_whole_claim", "does_not_state_whole_claim"} for w in valid)
                if not complete:
                    s3_missing = True
                elif not genuine:
                    s3n += 1
        for cell in c.get("cells", []):
            if not cell.get("published"):
                continue
            if (c["key"], cell["work_id"]) in removed:
                excluded_cells += 1
                continue
            quote_free += not bool(cell["quotes"])
            for q in cell["quotes"]:
                total += 1
                located += bool(q["quote"]) and any(q["quote"] in p["text"] for p in cell["passages"])
        result["S6"][c["key"]] = s6(c, [dict(n, **{k: v for k, v in snap.get("N_texts", {}).get(n["openalex_id"], {}).items() if k not in n}) for n in nset if any(r["work_id"] == n["openalex_id"] and r["state"] == "absent" for r in states)])
    sample = sample_cells(snap)
    answers = [reading4.get(f"sample-{i + 1}") for i in range(len(sample))]
    reason4 = unread or ("incomplete reader page" if any(a not in SUPPORT for a in answers) else None)
    result.update(S2=metric(s2n, s2d), S3=metric(s3n, s3d, unread or ("incomplete closing-witness reading" if s3_missing else None)),
                  S3_unlabelled_witnesses=unlabelled if not unread and not witness_reading_missing else UNMEASURED,
                  S3_all_closing_witnesses_read=not unread and not witness_reading_missing,
                  S4a=metric(located, total) | {"quote_free_cells": quote_free, "excluded_cells": excluded_cells},
                  S4b={"sample": [cell_key(c) for c in sample], "judgements": {a: metric(answers.count(a), len(sample), reason4) for a in sorted(SUPPORT)},
                       "reading": "model assessment, not human verification"})
    series = snap.get("series", {})
    elapsed = series.get("elapsed_seconds")
    sessions = series.get("new_sessions")
    result["S5"] = {"elapsed_seconds": elapsed if elapsed is not None else UNMEASURED,
                    "clock_complete": series.get("ended_at") is not None,
                    "time_cap_seconds": 10800, "time_cap_exceeded": elapsed > 10800 if elapsed is not None else UNMEASURED,
                    "new_sessions": sessions if sessions is not None else UNMEASURED, "session_cap": 120,
                    "session_cap_exceeded": sessions > 120 if sessions is not None else UNMEASURED,
                    "session_source": series.get("session_source", UNMEASURED), "claims": [],
                    "in_flight_overshoot_sessions": series.get("in_flight_overshoot_sessions", UNMEASURED),
                    "preparation": {"K6_requests": 9, "shared_requests": 13, "shared_cap": 60, "source": "Ek K / Ek L1 frozen preparation ledger counts"},
                    "stop_reason": series.get("stop_reason")}
    for c in snap["claims"]:
        run = c.get("run", {})
        usage, budget = run.get("usage", {}), run.get("budget", {})
        timing = next((e for e in series.get("claims", []) if e["key"] == c["key"]), {})
        duration = timing["observed_at"] - timing["requested_at"] if "observed_at" in timing and "requested_at" in timing else UNMEASURED
        transport = [s.get("output", {}).get("transport") for s in run.get("steps", [])
                     if s["kind"].startswith("provider_search:") and s.get("output")]
        attempts = sum(t["attempts"] for t in transport if t) if transport and all(transport) else UNMEASURED
        sends = sum(t["sends"] for t in transport if t) if transport and all(transport) else UNMEASURED
        result["S5"]["claims"].append({"key": c["key"], "status": run.get("status", "not run"),
            "observed_elapsed_seconds": duration, "new_sessions": run.get("measured_new_sessions", UNMEASURED),
            "model_attempts": usage.get("model_calls", UNMEASURED), "model_cap": budget.get("max_model_calls", UNMEASURED),
            "provider_requests": attempts, "provider_sends": sends,
            "provider_count_source": "stored provider-search step transport" if attempts != UNMEASURED else "transport census incomplete",
            "budget_charged_provider_requests": usage.get("provider_requests", UNMEASURED), "provider_cap": budget.get("max_provider_requests", UNMEASURED),
            "model_cap_exceeded": usage["model_calls"] > budget["max_model_calls"] if "model_calls" in usage and "max_model_calls" in budget else UNMEASURED,
            "provider_cap_exceeded": usage["provider_requests"] > budget["max_provider_requests"] if "provider_requests" in usage and "max_provider_requests" in budget else UNMEASURED})
    return result


def parser():
    p = argparse.ArgumentParser(description=__doc__)
    commands = p.add_subparsers(dest="command", required=True)
    commands.add_parser("plan")
    for name in ("setup", "run", "snapshot"):
        cmd = commands.add_parser(name)
        cmd.add_argument("--base", default="http://127.0.0.1:8873")
        cmd.add_argument("--out", type=Path, required=True)
        if name != "setup":
            cmd.add_argument("--db", type=Path)
        if name == "snapshot":
            cmd.add_argument("--n-records", type=Path, default=N_RECORDS,
                             help="hash-verified preparation records for absent-N S6 matching")
    for name in ("score", "reader-packet"):
        cmd = commands.add_parser(name)
        cmd.add_argument("--snapshot", type=Path, required=True)
        cmd.add_argument("--out", type=Path, required=True)
        if name == "score":
            group = cmd.add_mutually_exclusive_group(required=True)
            group.add_argument("--reader", type=Path)
            group.add_argument("--unread")
    return p


def main(argv=None):
    args = parser().parse_args(argv)
    try:
        data = frozen()
        if args.command == "plan":
            print(json.dumps({"question": data["question"], "model": MODEL,
                              "claims": [{"key": c["key"], "payload": {k: c[k] for k in FIELDS},
                                          "owner_text_chars": len(c["claim_statement"]), "payload_sha256": c["payload_sha256"]} for c in data["claims"]]}, ensure_ascii=False, indent=2))
        elif args.command == "reader-packet":
            reader_packet(load(args.snapshot), args.out)
        elif args.command == "score":
            snap = load(args.snapshot)
            page = checked_reader(snap, load(args.reader)) if args.reader else None
            write(args.out / "results.json", score(snap, page, args.unread))
        else:
            api = API(args.base, args.out)
            try:
                if args.command == "setup":
                    setup(api, args.out, data)
                else:
                    state = load(args.out / "setup.json")
                    if state["base"] != api.base or state["frozen_sha256"] != hashlib.sha256(FROZEN.read_bytes()).hexdigest():
                        raise Refused("base/frozen input changed since setup")
                    if ([c["key"] for c in state["claims"]] != [c["key"] for c in data["claims"]]
                            or any(not c.get("version_id") for c in state["claims"])):
                        raise Refused("setup incomplete; all six frozen version-1 claims are required")
                    if args.command == "run":
                        run_series(api, args.out, state, args.db)
                    else:
                        snapshot(api, args.out, state, data, args.db, args.n_records)
            finally:
                api.close()
        return 0
    except (Refused, OSError, ValueError, KeyError, TypeError, sqlite3.Error) as exc:
        print(f"K6 refused: {exc}", file=sys.stderr)
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
