"""Citation snowballing rounds (plan notes/plans/snowballing-plan.md). SYNTHETIC OpenAlex records through a mocked
transport and the fake model: these show the round's bookkeeping (identity, admissions, links, pause, resume, refusals,
the screening hand-off), not OpenAlex coverage or model quality."""

import asyncio
import json
from types import SimpleNamespace

import httpx
import pytest

from deixis.runtime.config import Settings
from deixis.domain import skill
from deixis.storage import db
from deixis.storage.db import now
from deixis.workflow.features.citation_map import snowball
from deixis.workflow.run.flow import FlowDeps, ResearchFlow
from deixis.workflow.run.store import Store
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


def test_a_hit_keeps_the_place_the_provider_gave_it_even_when_the_round_writes_only_some_records(lib):
    """The round writes only the records it admits, so their places among themselves are not the provider's places.
    Here the citing page answers with W1, which the research already holds, before the new W902."""
    seed_world(lib)
    lib.api.add(1)  # the provider answers about W1 too; the research already holds it, so the round writes no record
    lib.api.citing["W0"] = [["W1", "W902"]]
    run = snowball.request(lib.store, lib.rid, seeds=[lib.by_oid["W0"]])
    assert execute(lib, run)["status"] == "completed"
    svid = lib.store.find_source_by_identifier("openalex", "W902")
    rank = lib.store.conn.execute(
        "SELECT h.rank FROM candidate_hits h JOIN search_runs sr ON sr.id = h.search_run_id"
        " WHERE sr.run_id = ? AND sr.query_text LIKE '%forward%' AND h.source_version_id = ?",
        (run["id"], svid)).fetchone()
    assert rank is not None and rank[0] == 1  # second in the provider's page, not first among the written ones


def test_the_place_in_a_forward_read_counts_over_the_pages_the_query_already_took(lib):
    """A forward read is one query served page by page; a record's place is its place in its page plus everything the
    earlier pages returned. A page that was cancelled or never sent returned nothing."""
    store, run_id = lib.store, "run_SYNTHETIC_pages"
    store.conn.execute("INSERT INTO runs (id, research_id, scope_revision, kind, status, stage, budget_json,"
                       " usage_json, created_at, updated_at) VALUES (?, ?, 1, 'snowball', 'running', 'screening',"
                       " '{}', '{}', ?, ?)", (run_id, lib.rid, now(), now()))
    # The first page took 100; the second was never sent; the third took 40 and admission dropped one more the
    # provider had counted in its list.
    for index, output in ((0, {"returned": 100}), (1, {"unsent": "no_cursor"}),
                          (2, {"returned": 40, "dropped_records": 1})):
        step = store.step(run_id, snowball._key(index), snowball.REQUEST_KIND)
        store.start_step(step["id"])
        store.finish_step(step["id"], "succeeded", output=output)
    assert snowball._read_before(store, run_id, {"index": 0, "page": 1}) == 0
    assert snowball._read_before(store, run_id, {"index": 1, "page": 2}) == 100
    assert snowball._read_before(store, run_id, {"index": 2, "page": 3}) == 100  # the unsent page took nothing
    assert snowball._read_before(store, run_id, {"index": 3, "page": 4}) == 141  # the dropped record is counted
    # A backward batch is one request and starts at 0, whatever came before it in the plan.
    assert snowball._read_before(store, run_id, {"index": 3}) == 0


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


def test_0003_keeps_every_run_and_accepts_the_snowball_kind(tmp_path, monkeypatch):
    import sqlite3

    from deixis.storage import upgrades
    from old_library import old_library, steps_through
    path = tmp_path / "library.sqlite"
    conn = old_library(path, 2)
    conn.execute("INSERT INTO researches (id, title, created_at, updated_at) VALUES ('res_1', 'SYNTHETIC', 'now', 'now')")
    conn.execute("INSERT INTO runs (id, research_id, scope_revision, kind, status, stage, budget_json, created_at, updated_at)"
                 " VALUES ('run_1', 'res_1', 1, 'citation_check', 'completed', 'intake', '{}', 'now', 'now')")
    with pytest.raises(sqlite3.IntegrityError):
        conn.execute("INSERT INTO runs (id, research_id, scope_revision, kind, status, stage, budget_json, created_at, updated_at)"
                     " VALUES ('run_2', 'res_1', 1, 'snowball', 'queued', 'screening', '{}', 'now', 'now')")
    conn.close()
    with monkeypatch.context() as patch:  # later steps (4 on) are their own tests
        patch.setattr(upgrades, "STEPS", steps_through(3))
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


def test_a_round_orders_its_list_with_the_first_chain_matcher_even_after_an_m1_discovery(lib, monkeypatch):
    """The `m1` method changes only the discovery chain's admission: a person-started round still orders its list with
    `chaining.passes` over the searched gate forms, so a hyphenated variant of a gate form does not count as naming it."""
    seed_world(lib)
    lib.api.add(900, title="SYNTHETIC State-of-Health of irrigation pumps")
    budget = lib.store.run(lib.discovery_id)["budget"]
    budget["fast_path"] |= {"search_method": "m1", "chain_rule": "fast_chain_v2"}
    lib.store.conn.execute("UPDATE runs SET budget_json = ? WHERE id = ?", (json.dumps(budget), lib.discovery_id))
    monkeypatch.setattr(lib.flow, "_chain_forms", lambda *args: {"task": [" state of health"], "setting": []})
    run = snowball.request(lib.store, lib.rid, seeds=[lib.by_oid["W0"]])
    assert execute(lib, run)["status"] == "completed"
    listing = step(lib, run["id"], "snowball:list")[1]
    head = lib.store.find_source_by_identifier("openalex", "W900")
    (item,) = [i for i in listing["items"] if i["head"] == head]
    assert item["names_gate_block"] is False


def test_a_round_reads_the_stored_provider_keywords_when_it_orders_its_list(lib, monkeypatch):
    """A work names a gate block through its title, its abstract or a keyword OpenAlex's own classifier gave it.
    The keywords only move a work up the screening order; every admitted work is still listed."""
    seed_world(lib)
    lib.api.add(904, title="SYNTHETIC unrelated pumps",
                keywords=[{"id": "https://openalex.org/keywords/state-of-health", "display_name": "state of health",
                           "score": 0.97}])
    lib.api.add(905, title="SYNTHETIC unrelated pumps",
                keywords=[{"id": "https://openalex.org/keywords/thermal-runaway",
                           "display_name": "thermal runaway", "score": 0.5}])
    lib.api.citing["W0"] = [["W902", "W903", "W904", "W905"]]
    monkeypatch.setattr(lib.flow, "_chain_forms", lambda *args: {"task": [" state of health"], "setting": []})
    run = snowball.request(lib.store, lib.rid, seeds=[lib.by_oid["W0"]])
    assert execute(lib, run)["status"] == "completed"
    listing = step(lib, run["id"], "snowball:list")[1]
    named = {}
    for oid in ("W904", "W905"):
        head = lib.store.find_source_by_identifier("openalex", oid)
        (item,) = [i for i in listing["items"] if i["head"] == head]
        named[oid] = (item["names_gate_block"], item["position"])
    assert named["W904"][0] is True and named["W905"][0] is False
    assert named["W904"][1] < named["W905"][1]
