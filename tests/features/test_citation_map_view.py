"""The citation map read model: links from stored OpenAlex reference lists only, no provider or model call."""

import pytest

from deixis.providers.common import ProviderRecord
from deixis.storage import db
from deixis.workflow import citation_map
from deixis.workflow.store import Store


@pytest.fixture
def lib(tmp_path):
    conn = db.connect(tmp_path / "library.sqlite")
    db.migrate(conn)
    store = Store(conn)
    rid = store.create_research("Synthetic question?", "attached", "quick", [], "fake", "fake-model", "en")
    yield store, rid
    conn.close()


def record(oid, refs=None, year=2020, title=None):
    # SYNTHETIC records; `refs=None` means the list was never read.
    return ProviderRecord(provider_record_id=oid, title=title or f"Work {oid}", authors=["Ada Lovelace", "B. Babbage"],
                          year=year, venue="Synthetic venue", publication_type="article", doi=None, landing_url=None,
                          oa_pdf_url=None, oa_pdf_version=None, version_label=None, abstract=None, abstract_origin=None,
                          identifiers={"openalex": oid}, raw={}, references=None if refs is None else tuple(refs))


def add(store, rid, oid, refs=None, state="pending", **kw):
    svid, _ = store.upsert_provider_source("openalex", record(oid, refs, **kw), None)
    store.add_to_corpus(rid, svid, "user_upload", selection_state=state, selection_origin="user")
    return svid


def work(store, svid):
    return store.conn.execute("SELECT work_id FROM source_versions WHERE id = ?", (svid,)).fetchone()["work_id"]


def test_links_come_only_from_read_lists(lib):
    store, rid = lib
    a = add(store, rid, "W1", refs=["W2", "W9"])
    b = add(store, rid, "W2")                      # never read
    c = add(store, rid, "W3", refs=[])             # read, empty
    m = citation_map.build(store, rid)
    assert m["edges"] == [{"from": work(store, a), "to": work(store, b)}]
    read = {n["source_version_id"]: n["references_read"] for n in m["nodes"]}
    assert read == {a: True, b: False, c: True}
    assert m["counts"]["unread_references"] == 1


def test_excluded_stays_a_node_but_does_not_count_outside_works(lib):
    store, rid = lib
    add(store, rid, "W1", refs=["W50"])
    add(store, rid, "W2", refs=["W50", "W60"], state="excluded")
    add(store, rid, "W3", refs=["W60"])
    m = citation_map.build(store, rid)
    assert {n["state"] for n in m["nodes"]} == {"pending", "excluded"}
    # W50 and W60 each have one counting citer; the threshold is two with more than one counting work.
    assert m["outside"] == [] and m["counts"]["outside_threshold"] == 2


def test_two_versions_of_a_work_are_one_node_with_both_lists(lib):
    store, rid = lib
    head = add(store, rid, "W1", refs=["W2"])
    other, _ = store.upsert_provider_source("openalex", record("W1b", refs=["W3"]), None)
    store.conn.execute("UPDATE source_versions SET work_id = ? WHERE id = ?", (work(store, head), other))
    store.add_to_corpus(rid, other, "search", candidate=False)
    add(store, rid, "W2")
    add(store, rid, "W3")
    m = citation_map.build(store, rid)
    assert len(m["nodes"]) == 3
    [node] = [n for n in m["nodes"] if n["source_version_id"] == head]
    assert node["openalex_ids"] == ["W1", "W1b"]
    assert {e["to"] for e in m["edges"] if e["from"] == node["work_id"]} == {work(store, s) for s in (
        store.find_source_by_identifier("openalex", "W2"), store.find_source_by_identifier("openalex", "W3"))}


def test_build_writes_nothing(lib):
    store, rid = lib
    add(store, rid, "W1", refs=["W2"])
    add(store, rid, "W2", refs=["W1"])
    before = store.conn.total_changes
    citation_map.build(store, rid)
    assert store.conn.total_changes == before


def test_another_research_does_not_leak_in(lib):
    store, rid = lib
    other = store.create_research("Another question?", "attached", "quick", [], "fake", "fake-model", "en")
    add(store, other, "W1", refs=["W50"])
    add(store, other, "W2", refs=["W50"])
    add(store, rid, "W3", refs=[])
    m = citation_map.build(store, rid)
    assert len(m["nodes"]) == 1 and m["outside"] == [] and m["edges"] == []
