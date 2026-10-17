"""Citation snowballing rounds (plan .local/plans/snowballing-plan.md). SYNTHETIC OpenAlex records through a mocked
transport and the fake model: these show the round's bookkeeping (identity, admissions, links, pause, resume, refusals,
the screening hand-off), not OpenAlex coverage or model quality."""

import asyncio
import json
from types import SimpleNamespace

import httpx
import pytest

from deixis.config import Settings
from deixis.domain import skill
from deixis.domain.rules import RevisionConflict
from deixis.providers.registry import CONNECTORS
from deixis.storage import db
from deixis.storage.db import now
from deixis.workflow import snowball
from deixis.workflow.flow import FlowDeps, ResearchFlow
from deixis.workflow.store import Store
from fakes import FakeAdapter, valid_response
from test_fulltext_flow import work
from test_screen_more import discovered, included, new_answer

QUOTA = {"x-ratelimit-remaining-usd": "0", "x-ratelimit-reset": "3600"}
ON_TOPIC = "SYNTHETIC irrigation scheduling field crop"


class OpenAlex:
    """`filter=openalex:W1|W2`, `filter=doi:…` and `filter=cites:W…` (with a cursor) answered from `works`."""

    def __init__(self):
        self.works: dict[str, dict] = {}
        self.citing: dict[str, list[list[str]]] = {}  # seed id → pages of citing ids
        self.requests: list[dict] = []
        self.quota: set[str] = set()
        self.short_count: set[str] = set()  # id lookups answered with a count larger than the page

    def add(self, number, refs=None, title=ON_TOPIC, **extra):
        body = work(number, title=title) | extra
        if refs is not None:
            body["referenced_works"] = [f"https://openalex.org/{r}" for r in refs]
        self.works[f"W{number}"] = body

    def __call__(self, request):
        params = dict(request.url.params)
        kind, _, values = params.get("filter", "").partition(":")
        self.requests.append(params)
        if kind in self.quota:
            return httpx.Response(429, headers=QUOTA, json={"error": "daily budget"})
        if kind == "cites":
            pages = self.citing.get(values, [[]])
            page = 0 if params.get("cursor") == "*" else int(params["cursor"].removeprefix("c"))
            ids = pages[page] if page < len(pages) else []
            nxt = f"c{page + 1}" if page + 1 < len(pages) else None
            return httpx.Response(200, json={"meta": {"count": sum(map(len, pages)), "next_cursor": nxt},
                                             "results": [self.works[i] for i in ids]})
        ids = values.split("|")
        if kind == "openalex":
            found = [self.works[v] for v in ids if v in self.works]
            count = len(found) + (1 if kind in self.short_count else 0)
        else:
            found = [w for w in self.works.values() if w["doi"].removeprefix("https://doi.org/") in ids]
            count = len(found)
        return httpx.Response(200, json={"meta": {"count": count}, "results": found})

    def sent(self, kind):
        return [r for r in self.requests if r.get("filter", "").startswith(kind + ":")]


@pytest.fixture
def lib(tmp_path, monkeypatch):
    rid, discovery_id = discovered(tmp_path, monkeypatch, 5)
    store = Store(db.connect(tmp_path / "data" / "library.sqlite"))
    api = OpenAlex()
    http = httpx.AsyncClient(transport=httpx.MockTransport(api))
    adapter = FakeAdapter(valid_response)
    flow = ResearchFlow(FlowDeps(Settings(data_dir=tmp_path / "data", port=8879), store, {"fake": adapter},
                                 skill.load_skill_package(), http))
    heads = store.work_heads(rid)
    by_oid = {}
    for head in heads.values():
        for row in store.conn.execute("SELECT value FROM identifier_mappings WHERE scheme = 'openalex'"
                                      " AND source_version_id = ?", (head,)):
            by_oid[row[0].rsplit("/", 1)[-1]] = head
    yield SimpleNamespace(store=store, rid=rid, discovery_id=discovery_id, api=api, flow=flow, adapter=adapter,
                          by_oid=by_oid)
    asyncio.run(http.aclose())
    store.conn.close()


def execute(lib, run):
    lib.store.update_run(run["id"], status="running")
    asyncio.run(lib.flow.execute(run["id"]))
    return lib.store.run(run["id"])


def admissions(lib, run_id):
    return {row[0]: row[1] for row in lib.store.conn.execute(
        "SELECT openalex_id, outcome FROM snowball_admissions WHERE run_id = ?", (run_id,))}


def step(lib, run_id, key):
    row = lib.store.conn.execute("SELECT status, output_json FROM run_steps WHERE run_id = ? AND operation_key = ?",
                                 (run_id, key)).fetchone()
    return None if row is None else (row[0], json.loads(row[1] or "null"))


def seed_world(lib):
    """W0 (a discovery work) cites W900, W901 and W1 (already in the research); W902 and W903 cite W0."""
    lib.api.add(0, refs=["W900", "W901", "W1"])
    for n in (900, 901, 902, 903):
        lib.api.add(n)
    lib.api.citing["W0"] = [["W902", "W903"]]
    lib.store.conn.execute("UPDATE source_versions SET references_read = 0 WHERE id = ?", (lib.by_oid["W0"],))
    lib.store.conn.execute("DELETE FROM record_references WHERE source_version_id = ?", (lib.by_oid["W0"],))


def test_round_admits_new_works_links_the_held_one_screens_and_includes_nothing(lib):
    seed_world(lib)
    before = included(lib.store, lib.rid)
    run = snowball.request(lib.store, lib.rid, seeds=[lib.by_oid["W0"]])
    assert run["kind"] == "snowball" and run["stage"] == "screening" and run["target"]["round"] == 1
    done = execute(lib, run)
    assert done["status"] == "completed", done
    seen = admissions(lib, run["id"])
    assert {k for k, v in seen.items() if v == "new"} == {"W900", "W901", "W902", "W903"}
    # W1 was held: never asked for, but its link is written and it is not new.
    assert all("W1" not in r["filter"].split("|") for r in lib.api.sent("openalex") if "W900" in r["filter"])
    held = lib.store.conn.execute("SELECT source_version_id FROM chain_links WHERE run_id = ? AND linked_openalex_id = 'W1'",
                                  (run["id"],)).fetchone()
    assert held is not None and held[0] == lib.by_oid["W1"]
    cites = lib.api.sent("cites")
    assert len(cites) == 1 and cites[0]["sort"] == snowball.SORT and cites[0]["cursor"] == "*"
    summary = step(lib, run["id"], "snowball:summary")[1]
    assert summary["new_works"] == 4 and summary["held"] == 1 and summary["planned_for_screening"] == 4
    assert lib.adapter.calls  # the four new works were screened by the abstract stage
    assert included(lib.store, lib.rid) == before  # nothing is included by a round
    # Resuming a finished round sends nothing again.
    sent = len(lib.api.requests)
    lib.store.update_run(run["id"], status="running")
    asyncio.run(lib.flow.execute(run["id"]))
    assert len(lib.api.requests) == sent


def test_a_resolved_upload_is_not_a_new_work_and_keeps_the_persons_choice(lib):
    seed_world(lib)
    upload = lib.store.create_upload_source("SYNTHETIC uploaded paper")
    lib.store.add_to_corpus(lib.rid, upload, "user_upload", selection_state="excluded", selection_origin="user")
    lib.store.conn.execute("INSERT INTO citation_map_resolutions (source_version_id, method, status, openalex_id, doi,"
                           " run_id, resolved_at) VALUES (?, 'doi', 'resolved', 'W900', '10.1/up', NULL, ?)", (upload, now()))
    run = snowball.request(lib.store, lib.rid, seeds=[lib.by_oid["W0"]])
    execute(lib, run)
    assert admissions(lib, run["id"]).get("W900") is None  # held through the resolution: not asked, not admitted
    assert lib.store.find_source_by_identifier("openalex", "W900") is None  # no second work was written
    state = lib.store.conn.execute("SELECT state FROM selections WHERE research_id = ? AND source_version_id = ?",
                                   (lib.rid, upload)).fetchone()[0]
    assert state == "excluded"


def test_lexical_exclusion_is_off_so_an_off_vocabulary_abstract_reaches_the_model(lib):
    lib.api.add(0, refs=["W910"])
    lib.api.add(910, title="SYNTHETIC unrelated wording", abstract_inverted_index={"Other": [0], "words": [1]})
    lib.store.conn.execute("UPDATE source_versions SET references_read = 0 WHERE id = ?", (lib.by_oid["W0"],))
    run = snowball.request(lib.store, lib.rid, seeds=[lib.by_oid["W0"]], directions=["backward"])
    execute(lib, run)
    plan = step(lib, run["id"], "snowball:abstract_stage")[1]
    assert plan["lexical_exclusion"] is False and plan["works_needing_model"] == 1
    codes = [r[0] for r in lib.store.conn.execute(
        "SELECT reason_code FROM stage_decisions d JOIN run_steps s ON s.id = d.step_id WHERE s.run_id = ?", (run["id"],))]
    assert "both_blocks_missing" not in codes


def test_a_complete_answer_says_no_record_and_a_short_one_says_unresolved(lib):
    lib.api.add(0, refs=["W920", "W921"])
    lib.api.add(920)
    lib.store.conn.execute("UPDATE source_versions SET references_read = 0 WHERE id = ?", (lib.by_oid["W0"],))
    run = snowball.request(lib.store, lib.rid, seeds=[lib.by_oid["W0"]], directions=["backward"])
    execute(lib, run)
    assert admissions(lib, run["id"])["W921"] == "no_record"

    # W1's list is stored, so the only request is the batch, and OpenAlex counts more than it returned.
    lib.store.conn.execute("DELETE FROM record_references WHERE source_version_id = ?", (lib.by_oid["W1"],))
    lib.store.conn.executemany("INSERT INTO record_references (source_version_id, referenced_id) VALUES (?, ?)",
                               [(lib.by_oid["W1"], "W930"), (lib.by_oid["W1"], "W931")])
    lib.store.conn.execute("UPDATE source_versions SET references_read = 1 WHERE id = ?", (lib.by_oid["W1"],))
    lib.api.add(930)
    lib.api.short_count.add("openalex")
    second = snowball.request(lib.store, lib.rid, seeds=[lib.by_oid["W1"]], directions=["backward"])
    execute(lib, second)
    assert admissions(lib, second["id"])["W931"] == "unresolved"
    assert admissions(lib, second["id"])["W930"] == "new"


def test_a_spent_budget_pauses_and_resume_sends_only_what_was_not_sent(lib):
    seed_world(lib)
    lib.api.quota.add("cites")
    run = snowball.request(lib.store, lib.rid, seeds=[lib.by_oid["W0"]])
    paused = execute(lib, run)
    assert paused["status"] == "paused" and paused["pause_reason"] == "openalex_budget_exhausted"
    backward = len([r for r in lib.api.sent("openalex") if "W900" in r["filter"]])
    assert backward == 1 and set(admissions(lib, run["id"]).values()) >= {"new"}
    lib.api.quota.clear()
    # The reset time passed: the run's memory and the stored note both say the budget is back.
    lib.flow._openalex_budget.clear()
    lib.store.openalex_budget_reset = lambda: None
    lib.store.update_run(run["id"], status="running", pause_reason=None)
    asyncio.run(lib.flow.execute(run["id"]))
    assert lib.store.run(run["id"])["status"] == "completed"
    assert len([r for r in lib.api.sent("openalex") if "W900" in r["filter"]]) == 1  # the answered batch is not resent
    assert {k for k, v in admissions(lib, run["id"]).items() if v == "new"} == {"W900", "W901", "W902", "W903"}


def test_a_second_forward_page_waits_for_the_first_pages_cursor(lib, monkeypatch):
    monkeypatch.setenv(CONNECTORS["openalex"].key_env, "synthetic-key")
    lib.api.add(0, refs=[])
    for n in (940, 941):
        lib.api.add(n)
    lib.api.citing["W0"] = [["W940"], ["W941"]]
    run = snowball.request(lib.store, lib.rid, seeds=[lib.by_oid["W0"]], directions=["forward"])
    assert run["target"]["keyed"] is True
    execute(lib, run)
    cursors = [r["cursor"] for r in lib.api.sent("cites")]
    assert cursors == ["*", "c1"]
    assert {k for k, v in admissions(lib, run["id"]).items() if v == "new"} == {"W940", "W941"}


def test_refusals(lib, tmp_path):
    with pytest.raises(snowball.SnowballRefused) as no_dir:
        snowball.request(lib.store, lib.rid, seeds=[lib.by_oid["W0"]], directions=[])
    assert no_dir.value.code == "no_direction"
    upload = lib.store.create_upload_source("SYNTHETIC upload without identity")
    lib.store.add_to_corpus(lib.rid, upload, "user_upload", selection_state="included", selection_origin="user")
    with pytest.raises(snowball.SnowballRefused) as unusable:
        snowball.request(lib.store, lib.rid, seeds=[upload])
    assert unusable.value.code == "no_usable_seed"
    with pytest.raises(snowball.SnowballRefused) as many:
        snowball.request(lib.store, lib.rid, dois=[f"10.9/{i}" for i in range(snowball.MAX_SEEDS + 1)])
    assert many.value.code == "too_many_seeds"
    other = lib.store.create_research("SYNTHETIC unsearched question?", "attached", "quick", [], "fake", "fake-model", "en")
    with pytest.raises(snowball.SnowballRefused) as unsearched:
        snowball.request(lib.store, other, seeds=[])
    assert unsearched.value.code == "no_approved_search"
    first = snowball.request(lib.store, lib.rid, seeds=[lib.by_oid["W0"]])
    with pytest.raises(RevisionConflict):
        snowball.request(lib.store, lib.rid, seeds=[lib.by_oid["W1"]])
    lib.store.update_run(first["id"], status="cancelled")


def test_next_round_suggests_candidates_and_person_includes_never_an_exclusion(lib):
    seed_world(lib)
    run = snowball.request(lib.store, lib.rid, seeds=[lib.by_oid["W0"]])
    execute(lib, run)
    new = {k: lib.store.work_heads(lib.rid)[lib.store.source(lib.store.find_source_by_identifier("openalex", k))["work_id"]]
           for k, v in admissions(lib, run["id"]).items() if v == "new"}
    lib.store.conn.execute("UPDATE selections SET state = 'excluded', origin = 'user' WHERE research_id = ?"
                           " AND source_version_id = ?", (lib.rid, new["W900"]))
    suggested = snowball.suggested_seeds(lib.store, lib.store.run(run["id"]))
    assert new["W900"] not in suggested
    view = snowball.view(lib.store, lib.rid)
    assert view["available"] and view["series"][0]["can_continue"]
    second = snowball.request(lib.store, lib.rid, seeds=suggested or [new["W901"]], series_id=run["id"])
    assert second["target"]["round"] == 2 and second["target"]["series_id"] == run["id"]


def test_screen_more_reads_on_from_a_round_list_with_lexical_exclusion_off(lib, monkeypatch):
    from deixis.workflow import screen_more
    monkeypatch.setattr(snowball, "SCREEN_LIMIT", 1)
    seed_world(lib)
    run = snowball.request(lib.store, lib.rid, seeds=[lib.by_oid["W0"]])
    execute(lib, run)
    summary = step(lib, run["id"], "snowball:summary")[1]
    assert summary["planned_for_screening"] == 1 and summary["not_screened_limit"] == 3
    more = screen_more.request(lib.store, lib.rid, None, run["id"])
    assert more["target"]["source_run_id"] == run["id"] and more["target"]["lexical_exclusion"] is False
    assert more["target"]["discovery_run_id"] == lib.discovery_id and len(more["target"]["heads"]) == 3
    execute(lib, more)
    plan = step(lib, more["id"], "screen_more:abstract_stage")[1]
    assert plan["lexical_exclusion"] is False


def test_0003_keeps_every_run_and_accepts_the_snowball_kind(tmp_path, monkeypatch):
    import shutil
    import sqlite3
    first_two = tmp_path / "migrations"
    first_two.mkdir()
    for name in ("0001_schema.sql", "0002_citation_check.sql"):
        shutil.copy(db.MIGRATIONS_DIR / name, first_two)
    path = tmp_path / "library.sqlite"
    with monkeypatch.context() as patch:
        patch.setattr(db, "MIGRATIONS_DIR", first_two)
        conn = db.connect(path)
        assert db.migrate(conn) == [1, 2]
    conn.execute("INSERT INTO researches (id, title, created_at, updated_at) VALUES ('res_1', 'SYNTHETIC', 'now', 'now')")
    conn.execute("INSERT INTO runs (id, research_id, scope_revision, kind, status, stage, budget_json, created_at, updated_at)"
                 " VALUES ('run_1', 'res_1', 1, 'citation_check', 'completed', 'intake', '{}', 'now', 'now')")
    with pytest.raises(sqlite3.IntegrityError):
        conn.execute("INSERT INTO runs (id, research_id, scope_revision, kind, status, stage, budget_json, created_at, updated_at)"
                     " VALUES ('run_2', 'res_1', 1, 'snowball', 'queued', 'screening', '{}', 'now', 'now')")
    conn.close()
    shutil.copy(db.MIGRATIONS_DIR / "0003_snowball.sql", first_two)  # later migrations (0004 on) are their own tests
    with monkeypatch.context() as patch:
        patch.setattr(db, "MIGRATIONS_DIR", first_two)
        conn = db.connect(path)
        assert db.migrate(conn) == [3]
    assert [tuple(r) for r in conn.execute("SELECT id, kind FROM runs")] == [("run_1", "citation_check")]
    conn.execute("INSERT INTO runs (id, research_id, scope_revision, kind, status, stage, budget_json, created_at, updated_at)"
                 " VALUES ('run_2', 'res_1', 1, 'snowball', 'queued', 'screening', '{}', 'now', 'now')")
    assert {r[0] for r in conn.execute("SELECT name FROM sqlite_master WHERE type = 'trigger'")} >= {
        "kill_searches_run_guard", "owner_reviews_run_guard", "watch_checks_run_guard"}
    conn.close()


def test_a_round_candidate_reaches_a_new_answer_only_after_the_person_includes_it(lib):
    seed_world(lib)
    run = snowball.request(lib.store, lib.rid, seeds=[lib.by_oid["W0"]])
    execute(lib, run)
    lib.store.conn.execute("UPDATE runs SET status = 'cancelled' WHERE research_id = ? AND status = 'queued'", (lib.rid,))
    before = new_answer(lib, lib.rid)
    assert not [r for r in before["items"] if r.get("screened_after_cutoff") == run["id"]]
    head = lib.store.work_heads(lib.rid)[lib.store.source(lib.store.find_source_by_identifier("openalex", "W900"))["work_id"]]
    version = lib.store.conn.execute("SELECT version FROM selections WHERE research_id = ? AND source_version_id = ?",
                                     (lib.rid, head)).fetchone()[0]
    lib.store.set_user_selection(lib.rid, head, "included", version, "SYNTHETIC relevant")
    after = new_answer(lib, lib.rid)
    rows = [r for r in after["items"] if r.get("screened_after_cutoff") == run["id"]]
    assert [r["head"] for r in rows] == [head] and rows[0]["evidence_basis"] == "abstract_screening"
    assert rows[0]["route"] == "abstract" and len(rows[0]["abstract_ids"]) == 1


def test_two_local_works_naming_one_openalex_work_are_one_seed(lib):
    upload = lib.store.create_upload_source("SYNTHETIC second copy of W0")
    lib.store.add_to_corpus(lib.rid, upload, "user_upload", selection_state="included", selection_origin="user")
    lib.store.conn.execute("INSERT INTO citation_map_resolutions (source_version_id, method, status, openalex_id, doi,"
                           " run_id, resolved_at) VALUES (?, 'doi', 'resolved', 'W0', '10.1/copy', NULL, ?)", (upload, now()))
    run = snowball.request(lib.store, lib.rid, seeds=[lib.by_oid["W0"], upload])
    assert len(run["target"]["seeds"]) == 1


def test_a_research_with_rounds_can_be_purged(lib):
    seed_world(lib)
    run = snowball.request(lib.store, lib.rid, seeds=[lib.by_oid["W0"]])
    execute(lib, run)
    lib.store.conn.execute("UPDATE runs SET status = 'cancelled' WHERE research_id = ? AND status = 'queued'", (lib.rid,))
    lib.store.conn.execute("UPDATE researches SET trashed_at = ? WHERE id = ?", (now(), lib.rid))
    lib.store.purge_research(lib.rid)
    assert lib.store.conn.execute("SELECT COUNT(*) FROM snowball_admissions").fetchone()[0] == 0


def test_a_round_work_screened_by_screen_more_also_reaches_an_answer_once_included(lib, monkeypatch):
    from deixis.workflow import screen_more
    monkeypatch.setattr(snowball, "SCREEN_LIMIT", 1)
    seed_world(lib)
    run = snowball.request(lib.store, lib.rid, seeds=[lib.by_oid["W0"]])
    execute(lib, run)
    more = screen_more.request(lib.store, lib.rid, None, run["id"])
    execute(lib, more)
    lib.store.conn.execute("UPDATE runs SET status = 'cancelled' WHERE research_id = ? AND status = 'queued'", (lib.rid,))
    last = lib.store.work_heads(lib.rid)[lib.store.source(lib.store.find_source_by_identifier("openalex", "W903"))["work_id"]]
    version = lib.store.conn.execute("SELECT version FROM selections WHERE research_id = ? AND source_version_id = ?",
                                     (lib.rid, last)).fetchone()[0]
    lib.store.set_user_selection(lib.rid, last, "included", version, "SYNTHETIC relevant")
    rows = [r for r in new_answer(lib, lib.rid)["items"] if r.get("screened_after_cutoff") == more["id"]]
    assert [r["head"] for r in rows] == [last]


def test_a_new_work_without_an_abstract_counts_as_no_abstract_not_unread(lib):
    lib.api.add(0, refs=["W950"])
    lib.api.add(950, abstract_inverted_index=None)
    lib.store.conn.execute("UPDATE source_versions SET references_read = 0 WHERE id = ?", (lib.by_oid["W0"],))
    run = snowball.request(lib.store, lib.rid, seeds=[lib.by_oid["W0"]], directions=["backward"])
    execute(lib, run)
    summary = step(lib, run["id"], "snowball:summary")[1]
    assert summary["screening"]["no_abstract"] == 1 and summary["screening"]["not_read"] == 0
