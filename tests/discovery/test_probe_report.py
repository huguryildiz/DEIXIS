"""The comparative report script against an outside reference set (slice 19, decision 7, `scripts/probe_report.py`).

Libraries and reference sets are SYNTHETIC and from two fields, written through the store. Passing shows the script
counts what the rows say, reads the library without writing it and refuses a reference set with no header; it says
nothing about any signal's worth.
"""

from __future__ import annotations

import hashlib
import json

import pytest

from deixis.storage import db
from deixis.workflow.store import Store
from scripts import probe_report
from test_probes import Probe, order_rows


def build(tmp_path, field):
    path = tmp_path / "library.sqlite"
    conn = db.connect(path)
    db.migrate(conn)
    store = Store(conn)
    lib = Probe(store, field)
    lib.card([{"provider_id": "openalex", "origin": "model"}, {"provider_id": "openalex", "origin": "code"}],
             run=lib.run)
    first = lib.keyed("search:0", lib.records(4), result_count=40)
    second = lib.keyed("search:1", lib.records(3), result_count=30)
    pool = first + second
    lib.include(first[0])
    # bm25 scores all; graph scores only the first three (the rest share the tail); two works tie in bm25 at 2.5.
    bm25 = order_rows(pool, "bm25")
    bm25[1]["rank"] = bm25[2]["rank"] = 2.5
    graph = order_rows(pool[:3], "graph") + [{"source_version_id": s, "signal": "graph", "rank": 5.5, "available": False}
                                             for s in pool[3:]]
    lib.ranking(bm25 + graph + order_rows(pool, "fused") + order_rows(pool, "inspection"), run=lib.run)
    titles = [store.source(s)["title"] for s in pool]
    dois = [store.source(s)["doi"] for s in pool]
    conn.execute("PRAGMA wal_checkpoint(TRUNCATE)")
    conn.close()
    return path, titles, dois


def reference(tmp_path, rows, header=True):
    path = tmp_path / "reference.jsonl"
    lines = ([json.dumps({"origin": "SYNTHETIC two labelling calls agreed", "completeness": "SYNTHETIC incomplete"})]
             if header else [])
    path.write_text("\n".join(lines + [json.dumps(r) for r in rows]) + "\n", encoding="utf-8")
    return path


@pytest.mark.parametrize("field", ["channels", "irrigation"])
def test_arm_and_signal_counts_match_a_hand_count_and_two_runs_are_byte_identical(tmp_path, field, capsys):
    library, titles, dois = build(tmp_path, field)
    ref = reference(tmp_path, [
        {"key": "a", "title": titles[0], "dois": [], "openalex_ids": []},          # by title; place 1
        {"key": "b", "title": None, "dois": [dois[1]], "openalex_ids": []},        # by DOI; tied 2–3 in bm25
        {"key": "c", "title": "SYNTHETIC by nobody", "dois": ["10.1/none"], "openalex_ids": []},  # not in the pool
        {"key": "d", "title": titles[5], "dois": [], "openalex_ids": [], "role": "negative"},
    ])
    assert probe_report.main([str(library), str(ref)]) == 0
    first = capsys.readouterr().out
    assert probe_report.main([str(library), str(ref)]) == 0
    assert capsys.readouterr().out == first
    (research,) = json.loads(first)["researches"]
    assert research["not_in_pool"] == ["c"]
    positives = {row["signal"]: row for row in research["positives"]["rows"]}
    assert research["positives"]["in_pool"] == 2
    assert (positives["bm25"]["top_100"], positives["bm25"]["median_place"]) == (2, 1.75)
    assert (positives["graph"]["top_100"], positives["fused"]["top_100"]) == (2, 2)
    negatives = {row["signal"]: row for row in research["negatives"]["rows"]}
    assert negatives["graph"]["top_100"] == 0 and negatives["bm25"]["top_100"] == 1  # unscored in graph: not counted
    arms = research["arms_reference_positives"]["rounds"][0]["sources"][0]
    assert arms["included"] == 2 and arms["by_origin"] == [{"origin": "code", "included": 0, "works": 3},
                                                           {"origin": "model", "included": 2, "works": 4}]
    assert research["arms"]["arms"]["rounds"][0]["sources"][0]["included"] == 1
    assert research["arms"]["arms"]["rounds"][0]["sources"][0]["rows"] == 70
    assert research["included_not_in_reference"] == 0
    loo = research["leave_one_out_top200"]
    assert set(loo) == {"bm25", "graph"} and all(v["condition"] == probe_report.CONDITION for v in loo.values())
    assert "not pooled across libraries" in json.loads(first)["condition"]


def test_the_library_is_opened_read_only_and_left_byte_for_byte_as_it_was(tmp_path, capsys):
    library, titles, _ = build(tmp_path, "channels")
    ref = reference(tmp_path, [{"key": "a", "title": titles[0]}])
    before = hashlib.sha256(library.read_bytes()).hexdigest()
    library.chmod(0o444)  # a write would fail loudly
    try:
        assert probe_report.main([str(library), str(ref)]) == 0
    finally:
        library.chmod(0o644)
    capsys.readouterr()
    assert hashlib.sha256(library.read_bytes()).hexdigest() == before


def test_a_reference_set_without_its_origin_and_completeness_is_refused(tmp_path, capsys):
    library, titles, _ = build(tmp_path, "irrigation")
    ref = reference(tmp_path, [{"key": "a", "title": titles[0]}], header=False)
    assert probe_report.main([str(library), str(ref)]) == 2
    assert "origin and its completeness" in capsys.readouterr().err
    with pytest.raises(probe_report.ReferenceSetRefused):
        probe_report.read_reference(ref)


def test_same_role_entries_matching_one_work_are_merged_and_reported_whatever_the_row_order(tmp_path, capsys):
    """Review finding 3: the dedup rule names the merge and does not depend on which row came last."""
    library, titles, dois = build(tmp_path, "channels")
    rows = [{"key": "z-published", "title": titles[0], "dois": [], "openalex_ids": []},
            {"key": "a-preprint", "title": None, "dois": [dois[0]], "openalex_ids": []},
            {"key": "m", "title": titles[1], "dois": [], "openalex_ids": []}]
    outputs = []
    for order in (rows, list(reversed(rows))):
        ref = reference(tmp_path, order)
        assert probe_report.main([str(library), str(ref)]) == 0
        outputs.append(json.loads(capsys.readouterr().out)["researches"][0])
    first, second = outputs
    assert first["positives"] == second["positives"] and first["not_in_pool"] == second["not_in_pool"] == []
    assert first["merged_reference_entries"] == second["merged_reference_entries"]
    (merge,) = first["merged_reference_entries"]
    assert merge["unit"] == "a-preprint" and merge["keys"] == ["a-preprint", "z-published"] and len(merge["works"]) == 1
    assert first["positives"]["in_pool"] == 2


def test_entries_of_opposite_roles_matching_one_work_are_refused_with_the_keys_named(tmp_path, capsys):
    library, titles, dois = build(tmp_path, "irrigation")
    for rows in ([{"key": "p", "title": titles[0]}, {"key": "n", "dois": [dois[0]], "role": "negative"}],
                 [{"key": "n", "dois": [dois[0]], "role": "negative"}, {"key": "p", "title": titles[0]}]):
        ref = reference(tmp_path, rows)
        assert probe_report.main([str(library), str(ref)]) == 2
        err = capsys.readouterr().err
        assert "opposite roles" in err and "n (negative)" in err and "p (positive)" in err


def test_a_key_given_twice_is_refused_whatever_the_row_order(tmp_path, capsys):
    """Review 2, finding 2: a positive and a negative under one key cannot hide each other."""
    library, titles, _ = build(tmp_path, "channels")
    rows = [{"key": "k", "title": titles[0]}, {"key": "k", "title": titles[1], "role": "negative"}]
    for order in (rows, list(reversed(rows))):
        ref = reference(tmp_path, order)
        assert probe_report.main([str(library), str(ref)]) == 2
        assert "gives the key 'k' twice" in capsys.readouterr().err
