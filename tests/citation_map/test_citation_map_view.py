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


def test_outside_works_rank_by_citers_and_respect_the_limit(lib, monkeypatch):
    store, rid = lib
    monkeypatch.setattr(citation_map, "OUTSIDE_LIMIT", 2)
    add(store, rid, "W1", refs=["W50", "W60", "W70"])
    add(store, rid, "W2", refs=["W50", "W60", "W70"])
    add(store, rid, "W3", refs=["W60"], state="included")
    m = citation_map.build(store, rid)
    assert [(o["openalex_id"], o["in_count"]) for o in m["outside"]] == [("W60", 3), ("W50", 2)]
    assert m["counts"]["outside_total"] == 3 and m["counts"]["outside_without_metadata"] == 2


def test_a_single_work_shows_its_whole_list(lib):
    store, rid = lib
    add(store, rid, "W1", refs=["W50", "W60"], state="included")
    m = citation_map.build(store, rid)
    assert m["counts"]["outside_threshold"] == 1
    assert [o["openalex_id"] for o in m["outside"]] == ["W50", "W60"]


def test_removed_source_is_no_node_and_is_marked_as_once_held(lib):
    store, rid = lib
    add(store, rid, "W1", refs=["W2"])
    add(store, rid, "W3", refs=["W2"])
    gone = add(store, rid, "W2")
    store.remove_sources(rid, [gone], None)
    m = citation_map.build(store, rid)
    assert gone not in {n["source_version_id"] for n in m["nodes"]} and m["edges"] == []
    [outside] = m["outside"]
    assert outside["openalex_id"] == "W2" and outside["removed_from_research"] is True
    assert outside["title"] == "Work W2"


def test_outside_metadata_comes_from_the_library(lib):
    store, rid = lib
    store.upsert_provider_source("openalex", record("W50", year=1998, title="Quantum repeaters"), None)
    add(store, rid, "W1", refs=["W50"])
    add(store, rid, "W2", refs=["W50"])
    [outside] = citation_map.build(store, rid)["outside"]
    assert (outside["title"], outside["year"], outside["removed_from_research"]) == ("Quantum repeaters", 1998, False)


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


def test_a_work_citing_its_own_version_has_no_self_link(lib):
    store, rid = lib
    add(store, rid, "W1", refs=["W1"])
    assert citation_map.build(store, rid)["edges"] == []


def test_build_writes_nothing(lib):
    store, rid = lib
    add(store, rid, "W1", refs=["W2"])
    add(store, rid, "W2", refs=["W1"])
    before = store.conn.total_changes
    citation_map.build(store, rid)
    assert store.conn.total_changes == before


def test_node_and_edge_shape(lib):
    store, rid = lib
    a = add(store, rid, "W1", refs=["W2"])
    add(store, rid, "W2")
    m = citation_map.build(store, rid)
    assert set(m["nodes"][0]) == {"work_id", "source_version_id", "openalex_ids", "title", "authors", "authors_short",
                                  "year", "venue", "doi", "cited_by_count", "state", "references_read"}
    assert m["edges"][0]["from"] == work(store, a) and set(m["edges"][0]) == {"from", "to"}
    assert next(n for n in m["nodes"] if n["source_version_id"] == a)["authors_short"] == "Lovelace et al."


def test_excluded_work_keeps_its_links(lib):
    store, rid = lib
    a = add(store, rid, "W1", refs=["W2"], state="excluded")
    b = add(store, rid, "W2", refs=["W1"])
    assert citation_map.build(store, rid)["edges"] == sorted(
        [{"from": work(store, a), "to": work(store, b)}, {"from": work(store, b), "to": work(store, a)}],
        key=lambda e: (e["from"], e["to"]))


def test_another_research_does_not_leak_in(lib):
    store, rid = lib
    other = store.create_research("Another question?", "attached", "quick", [], "fake", "fake-model", "en")
    add(store, other, "W1", refs=["W50"])
    add(store, other, "W2", refs=["W50"])
    add(store, rid, "W3", refs=[])
    m = citation_map.build(store, rid)
    assert len(m["nodes"]) == 1 and m["outside"] == [] and m["edges"] == []


def test_the_outside_list_stops_at_forty(lib):
    store, rid = lib
    refs = [f"W{1000 + i}" for i in range(41)]
    add(store, rid, "W1", refs=refs)
    add(store, rid, "W2", refs=refs)
    m = citation_map.build(store, rid)
    assert len(m["outside"]) == 40 and m["counts"]["outside_total"] == 41
