"""The probe set, the arm rows and the signal table of an `sw` research (slice 19).

Records, criteria, searches and ranking rows are SYNTHETIC and from two fields (diffusion channel scheduling,
greenhouse irrigation), written straight through the store the way the runs write them, without a model or a request.
Passing shows what the tables count and from which stored rows; it says nothing about whether a signal or an arm is
useful, and no number here judges one.
"""

from __future__ import annotations

import pytest

from deixis.storage import db
from deixis.workflow import probes, queue, views
from deixis.workflow.decisions import DecisionStore
from deixis.workflow.store import Store
from test_queue import Lib, provider_record, queued


@pytest.fixture
def store(tmp_path):
    connection = db.connect(tmp_path / "library.sqlite")
    db.migrate(connection)
    yield Store(connection)
    connection.close()


class Probe(Lib):
    """A `Lib` whose searches can be keyed, rounded and chained, and whose ranking steps carry rows and an output."""

    def keyed(self, key, records, provider="openalex", query="q", run=None, result_count=None):
        run = run or self.run
        revision = self.store.research(self.rid)["current_scope_revision"]
        kind = f"provider_chain:{provider}" if key.startswith("chain:") else f"provider_search:{provider}"
        step = self.store.step(run, key, kind)
        self.store.record_search(
            dict(research_id=self.rid, run_id=run, step_id=step["id"], scope_revision=revision, provider=provider,
                 query_text=query, request_description="GET test", access_mode="keyless", status="completed",
                 delivery_class=None, result_count=len(records) if result_count is None else result_count,
                 provider_total=len(records), page_limit=25, error_json=None, raw_payload_path=None),
            provider, records, None, step["id"], "succeeded", step_output={"status": "completed"})
        return [self.store.find_source_by_identifier(provider, r.provider_record_id) for r in records]

    def records(self, n, prefix="R"):
        self.n += 1
        return [provider_record(f"{prefix}{self.n}-{i}", f"SYNTHETIC {self.field['topic']} record {self.n}-{i}",
                                f"10.9999/p{self.n}.{i}") for i in range(n)]

    def card(self, queries, run=None):
        step = self.store.step(run or self.run, "protocol_approval", "code:protocol_approval")
        self.store.finish_step(step["id"], "succeeded", output={"approved": {"queries": queries}})

    def ranking(self, rows, output=None, run=None, key="ranking"):
        run = run or self.new_run("discovery")
        step = self.store.step(run, key, f"code:{key}")
        self.store.finish_step(step["id"], "succeeded", output=output or {})
        self.ds.save_ranks(step["id"], self.rid, rows)
        return run, step["id"]

    def include(self, svid):
        """Two agreeing runs included this record: the full-text decision a reading run writes."""
        self.ds.record(self.rid, svid, "all_parts_verified")
        self.ds.derive_selection(self.rid, self.work_of(svid))

    def probe(self):
        return probes.probe_set(queue.context(self.store, self.rid))

    def view(self):
        return views.research_view(self.store, self.rid)


def order_rows(svids, signal, available=True, start=1):
    return [{"source_version_id": svid, "signal": signal, "rank": float(i + start), "available": available}
            for i, svid in enumerate(svids)]


def answered(lib, answer):
    svid = queued(lib)
    queue.decide(lib.store, lib.rid, svid, answer, None, lib.row(svid)["row_token"])
    return svid


# ---- decision 1: the probe set ----------------------------------------------------------------------------------


@pytest.mark.parametrize("field", ["channels"])
def test_a_queue_answer_or_a_list_edit_makes_a_probe_with_its_kind(store, field):
    lib = Probe(store, field)
    queue_include, queue_not_met = answered(lib, "include"), answered(lib, "criterion_not_met")
    listed_in, listed_out = lib.work(), lib.work()
    lib.list_edit(listed_in, "included")
    lib.list_edit(listed_out, "excluded")
    found = lib.probe()
    work = lib.work_of
    assert set(found["verified"]) == {work(queue_include), work(listed_in)}
    assert found["verified"][work(queue_include)]["via"] == "queue"
    assert found["verified"][work(listed_in)]["via"] == "list"
    assert found["negatives"] == {work(queue_not_met): "criterion_not_met", work(listed_out): "not_recorded"}
    assert found["look_again"] == set() and found["included"] == {}
    shown = probes.probes_view(store, lib.rid, found)
    assert shown["negatives"] == {"criterion_not_met": 1, "not_recorded": 1, "out_of_scope": None}


def test_model_agreement_is_its_own_column_and_never_a_persons_probe(store):
    lib = Probe(store)
    agreed, overruled = lib.work(), lib.work()
    for svid in (agreed, overruled):
        lib.include(svid)
    lib.list_edit(overruled, "excluded")  # the person's own edit takes the work out of the agreement column
    found = lib.probe()
    assert set(found["included"]) == {lib.work_of(agreed)}
    assert found["negatives"] == {lib.work_of(overruled): "not_recorded"}
    assert lib.work_of(agreed) not in found["verified"]


# ---- decision 5: the probes no arm found -------------------------------------------------------------------------


# ---- decisions 3–4: the arm rows ---------------------------------------------------------------------------------


# ---- decision 6: the signal table --------------------------------------------------------------------------------


# ---- decisions 10–11: one derivation, nothing written ------------------------------------------------------------


def test_the_view_derives_the_facts_once_calls_no_verified_records_and_changes_no_table(store, monkeypatch):
    lib = Probe(store)
    pool = lib.keyed("search:0", lib.records(3)) + lib.keyed("search:1", lib.records(2), provider="arxiv")
    lib.include(pool[0])
    answered(lib, "include")
    lib.list_edit(pool[1], "included")
    lib.ranking(order_rows(pool, "bm25") + order_rows(pool, "fused"), run=lib.run)
    tables = [row[0] for row in store.conn.execute("SELECT name FROM sqlite_master WHERE type = 'table'")]
    before = {t: store.conn.execute(f"SELECT COUNT(*) FROM {t}").fetchone()[0] for t in tables}
    changes = store.conn.total_changes
    calls = []
    real = DecisionStore.facts
    monkeypatch.setattr(DecisionStore, "facts", lambda self, *a, **k: calls.append(a) or real(self, *a, **k))
    monkeypatch.setattr(queue, "verified_records", lambda *a, **k: pytest.fail("the view reads no verified_records"))
    view = lib.view()
    assert len(calls) == 1
    assert {t: store.conn.execute(f"SELECT COUNT(*) FROM {t}").fetchone()[0] for t in tables} == before
    assert store.conn.total_changes == changes
    assert view["probes"]["verified"] == 2 and view["probes"]["included_by_agreement"] == 1
    (run,) = [r for r in view["runs"] if r["id"] == lib.run]
    assert run["signals"]["person"]["denominator"] == 1 and run["signals"]["person"]["status"] == "too_few"
    assert [s["included"] for s in run["source_counts"]["arms"]["sources"]] == [1, 0]
    assert view["counts"]["queue"] == 0
