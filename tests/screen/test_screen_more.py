"""UI parity S20, F12 and F13: the not-read list and the "Screen more" run. SYNTHETIC OpenAlex records and the fake
model, so these tests show the workflow (which works, in which order, two reads per batch, nothing included, budget,
resume, cancel, the refusals), not model quality or live provider access.
"""

import asyncio
import json
import time
from types import SimpleNamespace

import pytest

from deixis.config import Settings
from deixis.domain import skill
from deixis.storage import db
from deixis.storage.db import new_id, now
from deixis.workflow import answer as fast_answer, screen_more, small_batch
from deixis.workflow.views import research_view
from deixis.workflow.flow import FlowDeps, ResearchFlow
from deixis.workflow.store import Store
from deixis.workflow.worker import Worker
from fakes import FakeAdapter, valid_response
from test_fetch_overlap_flow import discover, output
from test_abstract_flow import HALF
from test_fulltext_flow import Transport, work
from test_small_batch_flow import app_for, client_of

ACTIVE = ("queued", "running", "pause_requested")


class Crash(BaseException):
    """The process stopping in the middle of a call."""


def settle(client, rid, timeout=60):
    """Wait until no run of the research is active (the discovery queues an answer and its review)."""
    deadline = time.time() + timeout
    while time.time() < deadline:
        view = client.get(f"/api/researches/{rid}").json()
        if all(run["status"] not in ACTIVE for run in view["runs"]):
            return view
        time.sleep(0.05)
    raise AssertionError("the research's runs did not settle")


def discovered(tmp_path, monkeypatch, n, preprints=False, no_abstract=()):
    """A quick discovery (read window N = 25) over `n` SYNTHETIC works the model reads, every run settled. With
    `preprints`, every record is a submitted version, so a published version added later heads its work; the records
    numbered in `no_abstract` come without one."""
    records = ([work(i, title=HALF, version="submittedVersion" if preprints else "publishedVersion",
                     **({"abstract": None} if i in no_abstract else {})) for i in range(n)]
               if preprints or no_abstract else None)
    app, _ = app_for(tmp_path, monkeypatch, n, model_works=True, transport=Transport(records) if records else None)
    with client_of(app) as client:
        rid, run_id, _, run = discover(client, effort="quick")
        assert run["status"] == "completed", run
        settle(client, rid)
    return rid, run_id


def harness(tmp_path, responder=valid_response):
    """The library the app wrote, driven by a flow of its own, so a test controls each run's execution."""
    store = Store(db.connect(tmp_path / "data" / "library.sqlite"))
    adapter = FakeAdapter(responder)
    flow = ResearchFlow(FlowDeps(Settings(data_dir=tmp_path / "data", port=8877), store, {"fake": adapter},
                                 skill.load_skill_package(), None))
    return SimpleNamespace(store=store, flow=flow, adapter=adapter)


def execute(h, run):
    h.store.update_run(run["id"], status="running")
    asyncio.run(h.flow.execute(run["id"]))
    return h.store.run(run["id"])


def listing(store, discovery_id):
    return output(store, discovery_id, small_batch.LIST_KEY)


def screening_steps(store, run_id):
    return {r["operation_key"]: r["status"] for r in store.conn.execute(
        "SELECT operation_key, status FROM run_steps WHERE run_id = ? AND kind = 'model:abstract_screening'", (run_id,))}


def sent_batches(h, run_id=None):
    """The records of every abstract-screening call the harness adapter answered, read from the stored StepInputs
    (the model sees short handles), oldest first; one run's calls when `run_id` is given."""
    ids = {c["candidate_id"]: c["source_version_id"] for c in h.store.candidates(rid_of(h))}
    rows = h.store.conn.execute(
        "SELECT i.payload_json FROM step_inputs i JOIN run_steps s ON s.id = i.step_id JOIN runs r ON r.id = s.run_id"
        " WHERE r.kind = 'screen_more' AND s.kind = 'model:abstract_screening'"
        f"{' AND r.id = ?' if run_id else ''} ORDER BY i.rowid", (run_id,) if run_id else ())
    return [[ids[c["candidate_id"]] for c in json.loads(row[0])["candidates"]] for row in rows]


def rid_of(h):
    return h.store.conn.execute("SELECT id FROM researches ORDER BY created_at LIMIT 1").fetchone()[0]


def included(store, rid):
    return store.conn.execute("SELECT COUNT(*) FROM selections WHERE research_id = ? AND state = 'included'",
                              (rid,)).fetchone()[0]


# ---- F13: the run ------------------------------------------------------------------------------------------------


def test_screen_more_resumes_after_a_crash_without_resending_a_finished_call(tmp_path, monkeypatch):
    rid, _ = discovered(tmp_path, monkeypatch, 90)
    h = harness(tmp_path)
    run = screen_more.request(h.store, rid, None)

    revision = h.store.selection_revision(rid)
    earlier = [a["id"] for a in research_view(h.store, rid)["answers"] if a["applicability"] == "current"]
    assert earlier
    seen = []

    def crash_on_third(si):
        if len(h.adapter.calls) == 3:
            # The first batch's candidates and the revision move were committed together, before anything else ran.
            seen.append(h.store.selection_revision(rid))
            h.adapter.before = None
            raise Crash

    h.adapter.before = crash_on_third
    with pytest.raises(Crash):
        execute(h, run)
    assert seen == [revision + 1]
    assert Worker.recover(SimpleNamespace(store=h.store))["runs"] == 1
    assert h.store.selection_revision(rid) == revision + 1
    answers = {a["id"]: a["applicability"] for a in research_view(h.store, rid)["answers"]}
    assert all(answers[aid] == "stale_selection" for aid in earlier)  # no stored candidate behind a "current" answer
    assert h.store.run(run["id"])["pause_reason"] == "backend_restarted"
    steps = screening_steps(h.store, run["id"])
    assert sorted(steps.values()) == ["outcome_unknown", "succeeded", "succeeded"]

    h.store.resume_run(run["id"])
    assert execute(h, run)["status"] == "completed"
    batches = sent_batches(h)
    assert len(batches) == 5 and batches[2] == batches[3] == batches[4]  # only the unfinished calls went again
    assert len(h.store.existing_step(run["id"], screen_more.SUMMARY_KEY)["output"]["candidates"]) == 40
    assert included(h.store, rid) == 0


def test_a_work_the_person_already_decided_is_neither_listed_nor_planned(tmp_path, monkeypatch):
    rid, discovery_id = discovered(tmp_path, monkeypatch, 60)
    h = harness(tmp_path)
    head = listing(h.store, discovery_id)["items"][25]["head"]  # the first work below the read window
    version = h.store.conn.execute("SELECT version FROM selections WHERE research_id = ? AND source_version_id = ?",
                                   (rid, head)).fetchone()[0]
    h.store.set_user_selection(rid, head, "excluded", version, "SYNTHETIC not this one")
    page = screen_more.unscreened(h.store, rid, 0, 100)
    assert page["total"] == 34 and head not in {i["source_version_id"] for i in page["items"]}
    run = screen_more.request(h.store, rid, None)
    assert head not in run["target"]["heads"] and len(run["target"]["heads"]) == 34
    pending = run["target"]["heads"][0]  # a selection the person set back to pending is the person's too
    version = h.store.conn.execute("SELECT version FROM selections WHERE research_id = ? AND source_version_id = ?",
                                   (rid, pending)).fetchone()[0]
    h.store.set_user_selection(rid, pending, "pending", version, "SYNTHETIC not sure")
    assert pending not in {i["source_version_id"] for i in screen_more.unscreened(h.store, rid, 0, 100)["items"]}


def new_answer(h, rid, **extra):
    scope = h.store.scope(rid, h.store.research(rid)["current_scope_revision"])
    budget = fast_answer.answer_run_budget(h.store, rid, scope) | extra
    run = execute(h, h.store.create_run(rid, "answer", budget, None))
    assert run["status"] == "completed", run
    h.store.conn.execute("UPDATE runs SET status = 'cancelled' WHERE research_id = ? AND status = 'queued'", (rid,))
    return output(h.store, run["id"], fast_answer.INPUT)


# ---- F12 and the routes ------------------------------------------------------------------------------------------


def test_unscreened_and_screen_more_routes(tmp_path, monkeypatch):
    app, _ = app_for(tmp_path, monkeypatch, 60, model_works=True)
    with client_of(app) as client:
        assert client.get("/api/researches/res_missing/unscreened").status_code == 404
        rid, discovery_id, _, run = discover(client, effort="quick")
        view = settle(client, rid)
        store = app.state.store
        frozen = listing(store, discovery_id)
        answer = next(a for a in view["answers"] if a["run_id"])
        assert answer["applicability"] == "current"

        page = client.get(f"/api/researches/{rid}/unscreened", params={"offset": 10, "limit": 5}).json()
        assert page["total"] == 35 and page["screenable"] == 35 and page["list_size"] == 60
        assert [i["source_version_id"] for i in page["items"]] == [i["head"] for i in frozen["items"][35:40]]
        assert [i["signals"]["rank"] for i in page["items"]] == [36, 37, 38, 39, 40]
        assert "prioritization signals" in page["signals_note"] and page["items"][0]["title"].startswith("SYNTHETIC")
        assert set(page["items"][0]["signals"]) == {"rank", "similarity"}
        everything = client.get(f"/api/researches/{rid}/unscreened", params={"limit": 100}).json()["items"]
        assert [i["signals"]["rank"] for i in everything] == list(range(26, 61))
        assert client.get(f"/api/researches/{rid}/unscreened", params={"limit": 101}).status_code == 422
        assert client.get(f"/api/researches/{rid}/unscreened", params={"offset": -1}).status_code == 422

        url = f"/api/researches/{rid}/screen-more"
        assert client.post(url, headers={"x-deixis-csrf": "wrong"}).status_code == 403
        store.conn.execute("INSERT INTO runs (id, research_id, scope_revision, kind, status, stage, budget_json, created_at,"
                           " updated_at) VALUES ('run_ACTIVE00000001', ?, 1, 'answer', 'running', 'answer', '{}', 'now', 'now')",
                           (rid,))
        assert client.post(url).status_code == 409
        store.conn.execute("UPDATE runs SET status = 'cancelled' WHERE id = 'run_ACTIVE00000001'")
        first = client.post(url, headers={"Idempotency-Key": "s1"})
        assert first.status_code == 202, first.text
        assert first.json()["kind"] == "screen_more" and len(first.json()["target"]["heads"]) == 35
        assert client.post(url, headers={"Idempotency-Key": "s1"}).json()["id"] == first.json()["id"]
        view = settle(client, rid)
        assert next(r for r in view["runs"] if r["id"] == first.json()["id"])["status"] == "completed"
        assert client.get(f"/api/researches/{rid}/unscreened").json()["total"] == 0
        refused = client.post(url)
        assert refused.status_code == 422 and refused.json()["code"] == "nothing_left"
        assert next(a for a in view["answers"] if a["id"] == answer["id"])["applicability"] == "stale_selection"

        # The next answer reads the works Screen more made candidates, from their abstracts; nothing is included.
        again = client.post(f"/api/researches/{rid}/runs", json={"kind": "answer"})
        assert again.status_code == 202, again.text
        settle(client, rid)
        plan = output(store, again.json()["id"], "fast_path:v1:answer_input")
        later = [row for row in plan["items"] if row.get("screened_after_cutoff") == first.json()["id"]]
        assert len(later) == 35 and all(row["route"] == "abstract" for row in later)
        assert plan["excluded_reasons"].get("outside_read_window", 0) == 0
        assert included(store, rid) == 0

        other = client.post("/api/researches", json={"question": "SYNTHETIC attached question", "model_connection": "fake",
                                                      "requested_model": "fake-model", "effort": "quick",
                                                      "source_scope": "attached"}).json()["research"]["id"]
        assert client.get(f"/api/researches/{other}/unscreened").status_code == 422
        refused = client.post(f"/api/researches/{other}/screen-more")
        assert refused.status_code == 422 and refused.json()["code"] == "no_completed_discovery"


# ---- a late full-text revision of an answer that read a Screen more row on another version --------------------------


def admitted_row_on_another_version(lib):
    """Put into the base answer's stored input the row Screen more admission writes when the runs read version B of a
    work whose head is A (SYNTHETIC; the same fields `fast_answer.input_plan` sets)."""
    from test_fast_path_late_revision import row as late_row

    head = lib.store.create_upload_source("SYNTHETIC admitted work, record A")
    lib.store.add_to_corpus(lib.rid, head, "user_upload")
    other = new_id("srv")
    lib.store.conn.execute("INSERT INTO source_versions (id, work_id, title, origin, version_label, created_at)"
                           " VALUES (?, ?, 'SYNTHETIC admitted work, version B', 'provider', 'acceptedVersion', ?)",
                           (other, lib.store.source(head)["work_id"], now()))
    lib.store.add_to_corpus(lib.rid, other, "search", candidate=False)
    passage = lib.store._insert_passage(other, None, "abstract", None, None, "provider", None, None,
                                        "SYNTHETIC exercise improves fatigue in the admitted version B.")
    assert lib.store.answer_versions(lib.rid)[head] == head  # the work's answer version is A, the row reads B
    step_id = late_row(lib)["base_input_step_id"]
    base = json.loads(lib.store.conn.execute("SELECT output_json FROM run_steps WHERE id = ?", (step_id,)).fetchone()[0])
    source = lib.store.source(other)
    base["items"].append({
        "work_id": source["work_id"], "head": head, "position": None, "source_version_id": other, "route": "abstract",
        "decision_id": None, "abstract_decision_id": None, "fulltext_decision_id": None, "asset_id": None,
        "abstract_ids": [passage], "fulltext_ids": [], "reason": None, "base_reason": "outside_read_window",
        "base_route": "abstract", "file_unverified": False, "user_priority": False, "override_reason": None,
        "version": {k: source.get(k) for k in fast_answer.VERSION_FIELDS}, "screened_after_cutoff": "run_SYNTHETIC",
        "evidence_basis": "abstract_screening", "cutoff_source_version_id": head})
    base["passage_ids"].append(passage)
    lib.store.conn.execute("UPDATE run_steps SET output_json = ? WHERE id = ?", (json.dumps(base), step_id))
    return other


def late_revision_of(lib):
    from deixis.workflow import late_revision
    from test_fast_path_late_revision import read_late, row as late_row

    read_late(lib)
    late_revision.advance(lib.flow, lib.rid)
    revision = lib.store.run(late_row(lib)["answer_run_id"])
    lib.store.update_run(revision["id"], status="running")
    asyncio.run(lib.flow.execute(revision["id"]))
    return lib.store.run(revision["id"]), late_row(lib)


def test_a_late_revision_keeps_a_screen_more_row_on_another_version(tmp_path):
    from deixis.workflow import late_revision
    from test_fast_path_late_revision import prepared

    lib = prepared(tmp_path)
    other = admitted_row_on_another_version(lib)
    revision, late = late_revision_of(lib)
    assert (revision["status"], late["status"]) == ("completed", "published"), revision
    plan = lib.store.existing_step(revision["id"], late_revision.REVISION_INPUT)["output"]
    kept = [i for i in plan["items"] if i["source_version_id"] == other]
    assert len(kept) == 1 and kept[0]["screened_after_cutoff"] == "run_SYNTHETIC" and kept[0]["route"] == "abstract"
