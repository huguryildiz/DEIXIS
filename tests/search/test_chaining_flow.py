"""Synthetic citation-chain rules the fast chain (`fast_chain_v1`) shares with the record path: which linked works are
chained, which keep their keyword place, what a reference batch did not answer, and when a work stops being chain-only.

The old chain (seeds, paged citing requests, the Semantic Scholar arm, the chain abstract read and its summary)
is gone with the clean start (slice 3a); its tests went with it. These tests drive `fast_chain.Round` over an
isolated SQLite library with scripted OpenAlex answers, so they show workflow behaviour, not live provider access.
`work` and `OpenAlex` stay because other test modules build their mocked OpenAlex from them.
"""

import asyncio
from dataclasses import replace
from types import SimpleNamespace

import httpx
import pytest

from deixis.domain.rules import TEST_EFFORT_BUDGETS
from deixis.providers.common import SearchOutcome
from deixis.storage import db
from deixis.workflow.run import fast_path
from deixis.workflow.search import date_scope, ranking, small_batch
from deixis.workflow.screen.decisions import DecisionStore
from deixis.workflow.run.store import Store
from test_fast_path_chain import dispatch, scripted, search, setup as chain_setup
from test_fast_path_clock import FakeClock
from test_fast_path_search import record

IRRIGATION = "SYNTHETIC irrigation scheduling of an open field crop"
IRRIGATION_ABSTRACT = "We vary the irrigation scheduling of an open field crop and report the water it used."


def work(number, title=IRRIGATION, abstract=IRRIGATION_ABSTRACT, doi=None, references=(), authors=(), name=None):
    """One SYNTHETIC OpenAlex record with its own reference list."""
    inverted: dict[str, list[int]] = {}
    for position, word in enumerate((abstract or "").split()):
        inverted.setdefault(word, []).append(position)
    return {"id": f"https://openalex.org/W{number}", "doi": f"https://doi.org/{doi or f'10.1/oa.{number}'}",
            "display_name": name or f"{title} {number}", "publication_year": 2024, "type": "article",
            "authorships": [{"author": {"display_name": author}} for author in authors],
            "abstract_inverted_index": inverted or None,
            "referenced_works": [f"https://openalex.org/W{ref}" for ref in references],
            "referenced_works_count": len(references)}


class OpenAlex:
    """Mocked OpenAlex: count probes, one page of keyword records, and the chain's two requests.

    `citing` answers `filter=cites:W…` by cursor, `by_id` answers `filter=openalex:W1|W2…`; every chain request is
    recorded, so a test can ask what was sent and what a resumed run sent again.
    """

    def __init__(self, works, citing=None, by_id=None, fail_cites=(), on_chain=None, limited_cites=()):
        self.works, self.citing, self.by_id = works, citing or {}, by_id or {}
        self.fail_cites, self.on_chain, self.limited_cites = set(fail_cites), on_chain, set(limited_cites)
        self.chain: list[tuple] = []
        self.pages: list[int] = []

    def __call__(self, request):
        if request.url.host != "api.openalex.org":
            return httpx.Response(404)
        params = request.url.params
        found = params.get("filter") or ""
        if found.startswith("cites:"):
            wid, cursor = found.removeprefix("cites:"), params.get("cursor")
            self.chain.append(("forward", wid, cursor))
            if self.on_chain:
                self.on_chain(self)
            if wid in self.fail_cites:
                return httpx.Response(500, text="SYNTHETIC server error")
            if wid in self.limited_cites:
                return httpx.Response(429, headers={"Retry-After": "0"}, text="SYNTHETIC rate limit")
            works, size = self.citing.get(wid, []), int(params["per_page"])
            self.pages.append(size)
            start = 0 if cursor in (None, "*") else int(cursor)
            end = min(start + size, len(works))
            return httpx.Response(200, json={"meta": {"count": len(works),
                                                      "next_cursor": str(end) if end < len(works) else None},
                                             "results": works[start:end]})
        if found.startswith("openalex:"):
            ids = found.removeprefix("openalex:").split("|")
            self.chain.append(("backward", tuple(ids)))
            if self.on_chain:
                self.on_chain(self)
            results = [self.by_id[i] for i in ids if i in self.by_id]
            return httpx.Response(200, json={"meta": {"count": len(results)}, "results": results})
        query = params.get("search.title_abstract_keywords") or ""
        if params.get("per_page") == "1" and params.get("select") == "id":
            return httpx.Response(200, json={"meta": {"count": 1 if " AND " in query else 40}, "results": []})
        return httpx.Response(200, json={"meta": {"count": len(self.works), "next_cursor": None},
                                         "results": self.works})


# ---- the fast chain over a SYNTHETIC library ----------------------------------------------------

@pytest.fixture
def lib(tmp_path):
    """A quick fast-path discovery run in an isolated library, as tests/search/test_fast_path_clock.py builds it."""
    conn = db.connect(tmp_path / "library.sqlite")
    db.migrate(conn)
    clock = FakeClock()
    store = Store(conn, clock)
    clock.store = store
    rid = store.create_research("SYNTHETIC queue delay", "academic", "quick", ["openalex"], "fake", "fake-model", "en")
    budget = small_batch.freeze_budget(TEST_EFFORT_BUDGETS["quick"].__dict__, "quick", "off")
    budget["fast_path"] = fast_path.freeze_budget(budget, "quick")
    run = store.create_run(rid, "discovery", budget, None)
    store.update_run(run["id"], status="running")
    yield SimpleNamespace(store=store, conn=conn, clock=clock, rid=rid, run=store.run(run["id"]))
    conn.close()


def found(flow, lib, key, records):
    """One completed OpenAlex keyword search that returned these records, written as the fast search writes it."""
    step = lib.store.step(lib.run["id"], key, "provider_search:openalex")
    outcome = SearchOutcome("completed", None, "SYNTHETIC search", "keyless", records=list(records),
                            raw_payload={"results": [r.raw for r in records]})
    flow._record_search(lib.run, step, {"provider_id": "openalex", "query_text": f"SYNTHETIC {key}"}, outcome,
                        len(records))
    return [lib.store.find_source_by_identifier("openalex", r.provider_record_id) for r in records]


def ranked(lib, svids):
    """A keyword ranking whose inspection order is these records, as `_ranking` stores it."""
    step = lib.store.step(lib.run["id"], "ranking", "code:ranking")
    DecisionStore(lib.store).save_ranks(step["id"], lib.rid, [
        {"source_version_id": svid, "signal": "inspection", "rank": place + 1, "available": True}
        for place, svid in enumerate(svids)])


def chain(round_, monkeypatch, forward=(), backward=(), calls=None):
    """Run the chain's first plan to the end: every citing request answers `forward`, every reference batch the
    records of `backward` it names."""
    async def handler(direction, ids):
        if calls is not None:
            calls.append((direction, ids))
        if direction == "forward":
            return dispatch(list(forward))
        return dispatch([r for r in backward if r.provider_record_id in ids])
    scripted(monkeypatch, handler)

    async def run():
        round_.initial()
        round_.admit.set()
        await asyncio.gather(*round_.writers)
        await round_.stop()
    asyncio.run(run())


def links(lib):
    return [dict(row) for row in lib.conn.execute(
        "SELECT seed_source_version_id, linked_openalex_id, direction, origin, passed_filter, source_version_id"
        " FROM chain_links WHERE run_id = ? ORDER BY linked_openalex_id, direction", (lib.run["id"],))]


def test_a_chained_record_that_merges_into_a_keyword_work_is_not_chained(lib, tmp_path, monkeypatch):
    flow, _, round_ = chain_setup(lib, tmp_path)
    (w1,) = [lib.store.find_source_by_identifier("openalex", r.provider_record_id)
             for r in search(flow, lib, "search:fast:semantic", ["W1"])]
    (w4,) = found(flow, lib, "search:0", [replace(record("W4"), doi="10.1234/w4")])
    ranked(lib, [w1, w4])
    # W800 is W4 under another OpenAlex identifier: the same DOI makes it the same source version.
    chain(round_, monkeypatch, forward=[replace(record("W800"), doi="10.1234/w4"), record("W801")])
    chained = flow._chain_filter(lib.run)
    output = lib.store.existing_step(lib.run["id"], "chain_filter")["output"]
    assert lib.store.find_source_by_identifier("openalex", "W800") == w4
    assert chained == [lib.store.find_source_by_identifier("openalex", "W801")]
    assert output["in_keyword_pool"] == 1 and output["new_works"] == 1
    assert {row["linked_openalex_id"] for row in links(lib) if row["passed_filter"]} == {"W800", "W801"}


def test_chain_links_are_written_once_on_resume(lib, tmp_path, monkeypatch):
    flow, scope, round_ = chain_setup(lib, tmp_path)
    search(flow, lib, "search:fast:semantic", ["W1"],
           refs={"W1": ["https://openalex.org/W900", "https://openalex.org/W901"]})
    calls = []
    chain(round_, monkeypatch, forward=[record("W700")], backward=[record("W900"), record("W901")], calls=calls)
    first, sent = links(lib), list(calls)
    # A restarted worker builds a new round over the same run: every request already answered stays answered.
    again = type(round_)(flow, lib.run, scope, round_.vocabulary)
    flow._fast_chains[lib.run["id"]] = again
    chain(again, monkeypatch, forward=[record("W700")], backward=[record("W900"), record("W901")], calls=calls)
    assert calls == sent and {d for d, _ in sent} == {"forward", "backward"}
    assert links(lib) == first and len(first) == len({(r["seed_source_version_id"], r["linked_openalex_id"],
                                                         r["direction"]) for r in first})
    assert {"W700", "W900", "W901"} == {row["linked_openalex_id"] for row in first}


def pool_works(lib):
    _, _, pool = ranking.pool_rows(lib.store, lib.rid, 1)
    return {row["work_id"] for row in pool}


# ---- the chain admission rule a run froze -------------------------------------------------------------

GATE = {"task": ["state of health"], "setting": []}
QUERY_STEP = {"terms": [{"phrase": "soh estimation", "block": "task", "dropped": "zero_results"}],
              "search_query": {"backups_left": {"task": ["capacity fade"], "setting": []}}}
LINKED = [replace(record("W700"), title="SYNTHETIC State-of-Health estimates"),
          replace(record("W701"), title="SYNTHETIC capacity fades of cells"),
          replace(record("W702"), title="SYNTHETIC unrelated pumps")]


def method_run(lib, method):
    """A second quick discovery run in its own research, queued under `method`."""
    rid = lib.store.create_research("SYNTHETIC battery ageing", "academic", "quick", ["openalex"], "fake",
                                    "fake-model", "en")
    budget = small_batch.freeze_budget(TEST_EFFORT_BUDGETS["quick"].__dict__, "quick", "off")
    budget["fast_path"] = fast_path.freeze_budget(budget, "quick", method=method)
    run = lib.store.create_run(rid, "discovery", budget, None)
    lib.store.update_run(run["id"], status="running")
    return SimpleNamespace(store=lib.store, conn=lib.conn, clock=lib.clock, rid=rid, run=lib.store.run(run["id"]))


def frozen(lib, forms, digest=None):
    """The protocol a v2 run froze before its first request, with the admission forms and their digest."""
    from deixis.workflow.search import chaining

    body = {"citation_chaining": {"rule_version": "fast_chain_v2", "admission_forms": forms,
                                  "admission_forms_sha256": digest or chaining.forms_digest(forms)}}
    record_ = lib.store.freeze_protocol(lib.rid, 1, body)
    step = lib.store.step(lib.run["id"], "protocol", "protocol:freeze")
    lib.store.start_step(step["id"])
    lib.store.finish_step(step["id"], "succeeded", output={"protocol_revision": record_["protocol_revision"]})


def round_for(lib, tmp_path, refs=None, page=("W1",), **numbers):
    flow, scope, _ = chain_setup(lib, tmp_path, **numbers)
    flow._chain_forms = lambda *args: ranking.block_forms(GATE)
    round_ = type(_)(flow, lib.run, scope, QUERY_STEP)
    flow._fast_chains[lib.run["id"]] = round_
    search(flow, lib, "search:fast:semantic", list(page), refs=refs)
    return flow, scope, round_


def passed(run_lib):
    return {row["linked_openalex_id"]: row["passed_filter"] for row in links(run_lib)}


def test_a_legacy_run_keeps_the_first_admission_rule_and_its_requests_on_resume(lib, tmp_path, monkeypatch):
    # A `legacy` run (every run's default) keeps `fast_chain_v1`: the hyphenated variant and the query's backup are
    # not the searched form, and a resumed round sends nothing again and admits the same.
    assert lib.run["budget"]["fast_path"]["chain_rule"] == "fast_chain_v1"
    flow, scope, round_ = round_for(lib, tmp_path)
    calls = []
    chain(round_, monkeypatch, forward=LINKED, calls=calls)
    assert passed(lib) == {"W700": 0, "W701": 0, "W702": 0}
    again = type(round_)(flow, lib.run, scope, QUERY_STEP)
    flow._fast_chains[lib.run["id"]] = again
    sent = list(calls)
    chain(again, monkeypatch, forward=LINKED, calls=calls)
    assert calls == sent and passed(lib) == {"W700": 0, "W701": 0, "W702": 0}


def test_an_m1_run_admits_word_variants_and_query_synonyms_with_the_forms_it_froze(lib, tmp_path, monkeypatch):
    from deixis.workflow.search import chaining

    m1 = method_run(lib, "m1")
    assert m1.run["budget"]["fast_path"]["chain_rule"] == "fast_chain_v2"
    frozen(m1, chaining.admission_forms(GATE, QUERY_STEP))
    _, _, round_ = round_for(m1, tmp_path)
    chain(round_, monkeypatch, forward=LINKED)
    assert passed(m1) == {"W700": 1, "W701": 1, "W702": 0}


def test_frozen_forms_that_no_longer_match_their_digest_stop_an_m1_run(lib, tmp_path):
    from deixis.workflow.run.flow import RunStopped

    tampered = method_run(lib, "m1")
    frozen(tampered, {"task": [" pumps"]}, digest="sha256:0")
    with pytest.raises(RunStopped):
        round_for(tampered, tmp_path)
    stopped = lib.store.run(tampered.run["id"])
    assert stopped["status"] == "failed" and stopped["pause_reason"] == "chain_forms_unverified"


# A chained record whose text never holds a gate term, one with the term among the keywords OpenAlex's classifier
# gave it and one with an unrelated keyword.
KEYWORDED = [replace(record("W710"), index_keywords=["battery state of health", "cell ageing"]),
             replace(record("W711"), index_keywords=["thermal runaway"])]


def test_the_gate_reads_openalex_keywords_and_still_drops_a_record_without_one(lib, tmp_path, monkeypatch):
    # v1, the default rule: neither record names the gate block in its title or abstract, so only the keyword admits.
    assert lib.run["budget"]["fast_path"]["chain_rule"] == "fast_chain_v1"
    _, _, round_ = round_for(lib, tmp_path)
    chain(round_, monkeypatch, forward=KEYWORDED)
    assert passed(lib) == {"W710": 1, "W711": 0}


def test_an_m1_run_reads_openalex_keywords_with_the_forms_it_froze(lib, tmp_path, monkeypatch):
    from deixis.workflow.search import chaining

    m1 = method_run(lib, "m1")
    frozen(m1, chaining.admission_forms(GATE, QUERY_STEP))
    _, _, round_ = round_for(m1, tmp_path)
    chain(round_, monkeypatch, forward=KEYWORDED)
    assert passed(m1) == {"W710": 1, "W711": 0}


# ---- the mode's scope, the links inside the first page and the rescue quota ----------------------

def test_quick_opens_no_citation_request_and_the_deeper_modes_take_one_and_three_seed_works():
    """The design's per-mode scope: Quick none, Standard one starting work, Deep at most three."""
    from deixis.workflow.search import chaining

    for effort, seeds in (("quick", 0), ("standard", 1), ("detailed", 3)):
        policy = fast_path.freeze_budget({}, effort)
        requests = (policy["backward_requests"], policy["forward_requests"])
        assert (policy["chain_seeds"], requests == (0, 0)) == (seeds, effort == "quick")
        read = chaining.policy({"fast_path": policy}, effort)
        assert read["request_limit"] == sum(requests) and read["directions"] == ["backward", "forward"]
    # Quick spends no HTTP attempt on the chain at all, retries included.
    assert chaining.attempt_limit(fast_path.freeze_budget({}, "quick"), "quick") == 0


def test_the_links_inside_the_first_page_are_written_without_a_request_even_in_quick(lib, tmp_path, monkeypatch):
    """W2's bibliography names W1 and both are on the page, so W2 cites W1 for nothing: no request is sent, and
    Quick's own numbers (no seed, no request) do not keep the link from being written."""
    flow, scope, round_ = chain_setup(lib, tmp_path, chain_seeds=0, backward_requests=0, forward_requests=0)
    search(flow, lib, "search:fast:semantic", ["W1", "W2"],
           refs={"W2": ["https://openalex.org/W1", "https://openalex.org/W999"]})
    calls = []
    round_.pool_links()
    chain(round_, monkeypatch, calls=calls)
    w1, w2 = (lib.store.find_source_by_identifier("openalex", oid) for oid in ("W1", "W2"))
    assert calls == []
    # The link is the page's own, so it is written as such: no citation request asked for it and no word filter
    # judged it, because both of its records are in the pool already.
    assert links(lib) == [{"seed_source_version_id": w2, "linked_openalex_id": "W1", "direction": "backward",
                           "origin": "pool", "passed_filter": 1, "source_version_id": w1}]
    output = lib.store.existing_step(lib.run["id"], "fast_chain:pool_links")["output"]
    # W999 is named by the bibliography but not on the page, so it is no link: nothing was asked for it.
    assert (output["page"], output["in_pool"], output["links"], output["cited_works"]) == (2, 2, 1, 1)
    # A restarted worker's round finds the step succeeded and writes no second row.
    again = type(round_)(flow, lib.run, scope, round_.vocabulary)
    again.pool_links()
    assert len(links(lib)) == 1
    # The chain filter keeps these links apart from what a request's word filter decided: Quick asked nothing, so
    # it reports no work as having passed that filter.
    ranked(lib, [w1, w2])
    flow._chain_filter(lib.run)
    counts = lib.store.existing_step(lib.run["id"], "chain_filter")["output"]
    assert (counts["pool_links"], counts["passed_filter"], counts["failed_filter"]) == (1, 0, 0)


def test_a_reference_list_read_earlier_writes_no_link_this_page_does_not_show(lib, tmp_path, monkeypatch):
    """The link a page shows is read from that page's own reply. A bibliography the library learned some other way
    is not a link this run saw, so it is not written as one."""
    flow, _, round_ = chain_setup(lib, tmp_path, chain_seeds=0, backward_requests=0, forward_requests=0)
    search(flow, lib, "search:fast:semantic", ["W1", "W2"])
    w1, w2 = (lib.store.find_source_by_identifier("openalex", oid) for oid in ("W1", "W2"))
    with db.transaction(lib.conn):
        lib.conn.execute("INSERT OR IGNORE INTO record_references (source_version_id, referenced_id)"
                         " VALUES (?, 'W1')", (w2,))
    round_.pool_links()
    assert links(lib) == []
    assert lib.store.existing_step(lib.run["id"], "fast_chain:pool_links")["output"]["links"] == 0


def test_one_work_two_seeds_cite_keeps_one_candidate_and_both_links(lib, tmp_path, monkeypatch):
    flow, _, round_ = chain_setup(lib, tmp_path)
    search(flow, lib, "search:fast:semantic", ["W1", "W2"],
           refs={"W1": ["https://openalex.org/W900"], "W2": ["https://openalex.org/W900"]})
    chain(round_, monkeypatch, backward=[record("W900")])
    rows = [row for row in links(lib) if row["linked_openalex_id"] == "W900"]
    svid = lib.store.find_source_by_identifier("openalex", "W900")
    assert len(rows) == 2 and {row["direction"] for row in rows} == {"backward"}
    assert {row["seed_source_version_id"] for row in rows} == {
        lib.store.find_source_by_identifier("openalex", oid) for oid in ("W1", "W2")}
    assert {row["source_version_id"] for row in rows} == {svid}
    assert lib.conn.execute("SELECT count(*) FROM candidates WHERE source_version_id = ?", (svid,)).fetchone()[0] == 1


def test_the_rescue_quota_writes_what_the_gate_turned_away_and_never_more_than_its_place(lib, tmp_path, monkeypatch):
    """An `m2` run freezes `fast_chain_v3`: the gate's verdict is recorded as before, and the first record no gate
    form reaches is written as a ranked candidate all the same. The quota is the run's, so the next request that
    asks finds it spent."""
    from deixis.workflow.search import chaining

    m2 = method_run(lib, "m2")
    assert m2.run["budget"]["fast_path"]["chain_rule"] == "fast_chain_v3"
    frozen(m2, chaining.admission_forms(GATE, QUERY_STEP))
    # The seed names one work, so this round sends a reference batch beside its citing request: two requests ask,
    # and between them the quota has one place.
    _, _, round_ = round_for(m2, tmp_path, refs={"W1": ["https://openalex.org/W703"]}, chain_rescue=1)
    off_topic = replace(record("W703"), title="SYNTHETIC unrelated valves")
    chain(round_, monkeypatch, forward=LINKED, backward=[off_topic])
    # W702 names neither block: the gate still turns it away, and it has a record because the quota took it.
    assert passed(m2) == {"W700": 1, "W701": 1, "W702": 0, "W703": 0}
    rescued = [row for row in links(m2) if not row["passed_filter"] and row["source_version_id"]]
    # One place, so one of the two records the gate turned away has a record and the other has none; which one
    # depends on which request answered first, and the quota is spent either way.
    assert len(rescued) == 1 and rescued[0]["linked_openalex_id"] in ("W702", "W703")
    assert m2.store.find_source_by_identifier("openalex", rescued[0]["linked_openalex_id"]) \
        == rescued[0]["source_version_id"]
    # The rescued record is a ranked candidate: that is what taking a place means.
    assert m2.conn.execute("SELECT count(*) FROM candidates WHERE source_version_id = ?",
                           (rescued[0]["source_version_id"],)).fetchone()[0] == 1
    # The run's own requests say the same: two records passed the gate and the quota was spent once in all.
    steps = [step for n in range(0, 4) if (step := m2.store.existing_step(m2.run["id"], f"chain:fast:{n}"))
             and step["status"] == "succeeded"]
    assert len(steps) == 2 and sum(step["output"]["rescued"] for step in steps) == 1
    assert sum(step["output"]["passed_filter"] for step in steps) == 2


def test_a_run_whose_budget_froze_no_quota_writes_no_record_the_gate_turned_away(lib, tmp_path, monkeypatch):
    # The default (`legacy`, `fast_chain_v1`) freezes no quota, so the chain writes what it always wrote.
    assert "chain_rescue" not in lib.run["budget"]["fast_path"]
    _, _, round_ = round_for(lib, tmp_path)
    chain(round_, monkeypatch, forward=LINKED)
    assert passed(lib) == {"W700": 0, "W701": 0, "W702": 0}
    assert [row for row in links(lib) if row["source_version_id"]] == []


def test_both_directions_ask_while_the_boolean_search_is_still_running(lib, tmp_path, monkeypatch):
    """Standard's two directions run beside the Boolean queries, not after them: the round sends its requests as
    soon as the first page is read and holds only the writing until the search stage closes (`admit`)."""
    flow, _, round_ = chain_setup(lib, tmp_path)
    search(flow, lib, "search:fast:semantic", ["W1"], refs={"W1": ["https://openalex.org/W900"]})
    calls = []

    async def handler(direction, ids):
        calls.append(direction)
        return dispatch([record("W900")] if direction == "backward" else [record("W700")])
    scripted(monkeypatch, handler)

    async def run():
        round_.initial()
        await asyncio.gather(*round_.tasks)
        # The search stage has not closed, so nothing is written yet; both directions have already asked.
        assert set(calls) == {"backward", "forward"} and links(lib) == []
        round_.admit.set()
        await asyncio.gather(*round_.writers)
        await round_.stop()
    asyncio.run(run())
    assert {row["linked_openalex_id"] for row in links(lib)} == {"W700", "W900"}


def test_a_work_the_quota_already_rescued_takes_no_second_place(lib, tmp_path, monkeypatch):
    """The quota is counted by work: the second request's place goes to a work no place was spent on yet, not again
    to the one the first request rescued."""
    from deixis.workflow.search import chaining

    m2 = method_run(lib, "m2")
    frozen(m2, chaining.admission_forms(GATE, QUERY_STEP))
    _, _, round_ = round_for(m2, tmp_path, page=("W1", "W2"), chain_rescue=2)
    valves = replace(record("W704"), title="SYNTHETIC unrelated valves")

    async def handler(direction, seed):
        # One forward request per seed work, answered in the plan's order: the first brings W702 alone, the second
        # brings it again beside a work no place was spent on.
        return dispatch([record("W702")] if seed == "W1" else [record("W702"), valves])
    scripted(monkeypatch, handler)

    async def run():
        round_.initial()
        round_.admit.set()
        await asyncio.gather(*round_.writers)
        await round_.stop()
    asyncio.run(run())
    rescued = {row["linked_openalex_id"] for row in links(m2) if not row["passed_filter"] and row["source_version_id"]}
    assert rescued == {"W702", "W704"}
    steps = [step for n in range(0, 4) if (step := m2.store.existing_step(m2.run["id"], f"chain:fast:{n}"))
             and step["status"] == "succeeded"]
    # Two places, two works: the repeat is written again (it gains its link) but spends no place.
    assert sum(step["output"]["rescued"] for step in steps) == 2


def test_a_chained_record_outside_the_run_s_years_is_not_carried_into_the_pool(tmp_path, monkeypatch):
    """`chain_links` keeps every link the chain wrote, so a record the run's years set aside would still reach the
    pool through the chain although it is no candidate. The step says how many works that cost, and the link's own
    counts are left alone: what the chain found and what the word gate decided are records of their own."""
    conn = db.connect(tmp_path / "bounded.sqlite")
    db.migrate(conn)
    clock = FakeClock()
    store = Store(conn, clock)
    clock.store = store
    rid = store.create_research("SYNTHETIC queue delay since 2020", "academic", "quick", ["openalex"], "fake",
                                "fake-model", "en")
    budget = small_batch.freeze_budget(TEST_EFFORT_BUDGETS["quick"].__dict__, "quick", "off")
    budget["fast_path"] = fast_path.freeze_budget(budget, "quick",
                                                  date_scope=date_scope.given(2020, None))
    run = store.create_run(rid, "discovery", budget, None)
    store.update_run(run["id"], status="running")
    lib = SimpleNamespace(store=store, conn=conn, clock=clock, rid=rid, run=store.run(run["id"]))
    flow, _, round_ = chain_setup(lib, tmp_path)
    (w1,) = [lib.store.find_source_by_identifier("openalex", r.provider_record_id)
             for r in search(flow, lib, "search:fast:semantic", ["W1"])]
    ranked(lib, [w1])
    # One chained record inside the years and one outside them, both admitted by the word gate.
    chain(round_, monkeypatch, forward=[replace(record("W801"), year=2024), replace(record("W802"), year=2015)])
    chained = flow._chain_filter(lib.run)
    output = lib.store.existing_step(lib.run["id"], "chain_filter")["output"]
    inside = lib.store.find_source_by_identifier("openalex", "W801")
    outside = lib.store.find_source_by_identifier("openalex", "W802")
    assert chained == [inside] and outside is not None
    assert output["set_aside_for_year"] == 1
    # The link the chain wrote is still there and still counted as having passed the word gate.
    assert {row["linked_openalex_id"] for row in links(lib) if row["passed_filter"]} == {"W801", "W802"}
    conn.close()
