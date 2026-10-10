"""Synthetic citation-chain rules the fast chain (`fast_chain_v1`) shares with the record path: which linked works are
chained, which keep their keyword place, what a reference batch did not answer, and when a work stops being chain-only.

The old chain (D95: seeds, paged citing requests, the Semantic Scholar arm, the chain abstract read and its summary)
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
from deixis.workflow import fast_path, ranking, small_batch
from deixis.workflow.decisions import DecisionStore
from deixis.workflow.store import Store
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
        query = params.get("search.title_and_abstract") or ""
        if params.get("per_page") == "1" and params.get("select") == "id":
            return httpx.Response(200, json={"meta": {"count": 1 if " AND " in query else 40}, "results": []})
        return httpx.Response(200, json={"meta": {"count": len(self.works), "next_cursor": None},
                                         "results": self.works})




# ---- the fast chain over a SYNTHETIC library ----------------------------------------------------

@pytest.fixture
def lib(tmp_path):
    """A quick fast-path discovery run in an isolated library, as tests/hardening/test_fast_path_clock.py builds it."""
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
        "SELECT seed_source_version_id, linked_openalex_id, direction, passed_filter, source_version_id"
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


def test_a_published_version_the_chain_joins_to_a_keyword_preprint_keeps_the_keyword_place(lib, tmp_path,
                                                                                            monkeypatch):
    # W4 is a keyword preprint; the chain brings W804, its published version (same title, abstract and author). The
    # record path joins them into one work headed by the published record. That work is a keyword work: it is not
    # chained, and its new head takes the place the preprint had in the keyword order.
    flow, _, round_ = chain_setup(lib, tmp_path)
    (w1,) = [lib.store.find_source_by_identifier("openalex", r.provider_record_id)
             for r in search(flow, lib, "search:fast:semantic", ["W1"])]
    preprint = replace(record("W4"), doi="10.48550/arxiv.2601.00004", version_label="submittedVersion",
                       merge_by_doi=False, authors=["Ada Rainfield"])
    w4, w5 = found(flow, lib, "search:0", [preprint, record("W5")])
    ranked(lib, [w1, w4, w5])
    published = replace(preprint, provider_record_id="W804", identifiers={"openalex": "W804"}, doi="10.1234/pub.4",
                        version_label="publishedVersion", merge_by_doi=True, raw={"id": "W804"})
    chain(round_, monkeypatch, forward=[published, record("W801")])
    w804 = lib.store.find_source_by_identifier("openalex", "W804")
    w801 = lib.store.find_source_by_identifier("openalex", "W801")
    work_of = lib.store.work_ids([w4, w804])
    chained = flow._chain_filter(lib.run)
    output = lib.store.existing_step(lib.run["id"], "chain_filter")["output"]
    assert w804 != w4 and work_of[w4] == work_of[w804] and lib.store.work_heads(lib.rid)[work_of[w4]] == w804
    assert chained == [w801] and output["in_keyword_pool"] == 1
    assert flow._current_heads(lib.rid, [w1, w4, w5]) == [w1, w804, w5]


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


def test_a_backward_id_openalex_does_not_return_is_counted_unresolved(lib, tmp_path, monkeypatch):
    flow, _, round_ = chain_setup(lib, tmp_path)
    search(flow, lib, "search:fast:semantic", ["W1"],
           refs={"W1": ["https://openalex.org/W900", "https://openalex.org/W901", "https://openalex.org/W902"]})
    chain(round_, monkeypatch, backward=[record("W900"), record("W902")])
    outputs = [lib.store.step_output(s["id"]) for s in lib.store.run_steps(lib.run["id"])
               if s["operation_key"].startswith("chain:fast:")]
    (batch,) = [o for o in outputs if o["direction"] == "backward"]
    assert batch["unresolved"] == ["W901"]
    assert {row["linked_openalex_id"] for row in links(lib) if row["direction"] == "backward"} == {"W900", "W902"}


def chained_once(lib, tmp_path, monkeypatch):
    """A library whose chain brought one work, W700, that no keyword search found."""
    flow, _, round_ = chain_setup(lib, tmp_path)
    search(flow, lib, "search:fast:semantic", ["W1"])
    chain(round_, monkeypatch, forward=[record("W700")])
    w700 = lib.store.find_source_by_identifier("openalex", "W700")
    return flow, w700, lib.store.work_ids([w700])[w700]


def pool_works(lib):
    _, _, pool = ranking.pool_rows(lib.store, lib.rid, 1)
    return {row["work_id"] for row in pool}


def test_an_earlier_chained_work_stays_out_of_the_next_keyword_ranking(lib, tmp_path, monkeypatch):
    _, _, work = chained_once(lib, tmp_path, monkeypatch)
    w1 = lib.store.find_source_by_identifier("openalex", "W1")
    # The next discovery run ranks this pool: the chain's work is not a keyword record of it.
    assert work in lib.store.chain_only_works(lib.rid, 1)
    assert work not in pool_works(lib) and lib.store.work_ids([w1])[w1] in pool_works(lib)


def test_a_chained_work_a_later_keyword_search_finds_leaves_the_chain_group(lib, tmp_path, monkeypatch):
    flow, _, work = chained_once(lib, tmp_path, monkeypatch)
    assert work in lib.store.chain_only_works(lib.rid, 1)
    found(flow, lib, "search:1", [record("W700")])
    assert work not in lib.store.chain_only_works(lib.rid, 1) and work in pool_works(lib)
