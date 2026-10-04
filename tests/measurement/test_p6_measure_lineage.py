"""The L9 kit reads a real synthetic lineage run (fake adapter) through a saved view and a SQLite copy; it calls no model."""

from __future__ import annotations

import hashlib
import json
from pathlib import Path

import pytest

from scripts.p6_eval import measure_lineage as kit
from test_lineage_flow import execute, factory, lib, queue  # noqa: F401  (fixtures)
from test_lineage_plan import fill
from test_lineage_view import read

G = {"works": [{"key": "a", "match": "synthetic source 000", "first_author": "author000", "years": [2000]},
               {"key": "b", "match": "synthetic source 001", "first_author": "author001", "years": [2001]},
               {"key": "z", "match": "synthetic source 099", "first_author": "nobody", "years": [2099]}],
     "pairs": [["a", "b"], ["b", "z"]]}


def db_path(lib) -> Path:
    return Path(lib.conn.execute("PRAGMA database_list").fetchone()[2])


@pytest.fixture
def finished(lib, tmp_path):
    fill(lib)
    run = queue(lib)
    assert execute(lib, run)["status"] == "completed"
    out = tmp_path / "kit"
    view = tmp_path / "view.json"
    view.write_text(json.dumps(read(lib)))
    g = tmp_path / "g.json"
    g.write_text(json.dumps(G))
    lib.conn.execute("PRAGMA wal_checkpoint(FULL)")
    return lib, run, out, view, g


def snapshot_args(finished, **kw):
    lib, run, out, view, g = finished
    parts = ["snapshot", "--run", run["id"], "--db", str(db_path(lib)), "--g", str(g), "--view-file", str(view), "--out", str(out)]
    for k, v in kw.items():
        parts += [f"--{k}", str(v)]
    return parts


def run_cli(monkeypatch, parts):
    monkeypatch.setattr("sys.argv", ["measure_lineage.py", *parts])
    kit.main()


def test_snapshot_reads_the_run_and_never_writes_the_library(finished, monkeypatch):
    lib = finished[0]
    before = hashlib.sha256(db_path(lib).read_bytes()).hexdigest()
    run_cli(monkeypatch, snapshot_args(finished))
    out = finished[2]
    snap = json.loads((out / "snapshot.json").read_text())
    assert hashlib.sha256(db_path(lib).read_bytes()).hexdigest() == before
    s = snap["structure"]
    assert s["candidates_found"] >= 1 and s["candidates_sent"] == s["candidates_found"] and s["decided"] >= 1
    assert s["human_edited_links_current"] == 0 and s["usage"]["started_left_open"] == 0
    assert s["intervention_audit"] == {"human_link_revisions": 0, "human_cell_revisions": 0, "scope_revisions": 1, "non_terminal_runs": 0}
    assert s["usage"]["sessions"] >= 1 and s["max_model_calls"] >= 1
    pairs = snap["R14"]["pairs"]
    assert pairs["a->b"]["status"] == "won" and pairs["b->z"] == {"status": "not_in_table", "missing": ["z"], "identity_unverified": []}
    assert snap["R14"]["value"] == 1 and snap["R14"]["denominator"] == 2
    assert snap["R15"]["denominator"] == snap["structure"]["table_status"]["pdf_text_rows"] == 5 and "reasons" in snap["R15"]
    sheet = (out / "reader.md").read_text()
    assert "### L01" in sheet and "Part 2" in sheet and "SYNTHETIC" in sheet
    key = json.loads((out / "key.json").read_text())
    assert list(key["links"]) == ["L01"] and key["mentions"] and key["material_missing"] == []


def test_score_needs_a_complete_valid_reading_and_writes_r12_r13(finished, monkeypatch):
    run_cli(monkeypatch, snapshot_args(finished))
    out = finished[2]
    key = json.loads((out / "key.json").read_text())
    snap = json.loads((out / "snapshot.json").read_text())
    good = {"links": {"L01": {"support": "partial", "chronology_only": False}}, "mentions": {m: "body" for m in key["mentions"]}}
    result = kit.score(snap, key, good)
    assert result["R12"]["value"] == 0 and result["R12"]["partial"] == 1 and result["R12"]["denominator"] == 1
    assert result["R13"]["value"] == 0 and result["mention_form"]["body_present"] == result["mention_form"]["pairs_sent"] >= 1
    assert result["R12"]["reader"] == "model"
    for broken in ({"links": {}, "mentions": good["mentions"]},
                   {"links": {"L01": {"support": "yes", "chronology_only": False}}, "mentions": good["mentions"]},
                   {"links": good["links"], "mentions": {}}):
        with pytest.raises(SystemExit):
            kit.score(snap, key, broken)
    (out / "reader.json").write_text(json.dumps(good))
    run_cli(monkeypatch, ["score", "--out", str(out)])
    assert json.loads((out / "results.json").read_text())["R12"]["denominator"] == 1


def test_all_reference_list_mentions_are_reported_apart(finished, monkeypatch):
    run_cli(monkeypatch, snapshot_args(finished))
    out = finished[2]
    key = json.loads((out / "key.json").read_text())
    snap = json.loads((out / "snapshot.json").read_text())
    answers = {"links": {"L01": {"support": "supports", "chronology_only": True}}, "mentions": {m: "reference_list" for m in key["mentions"]}}
    result = kit.score(snap, key, answers)
    assert result["mention_form"]["reference_list_only"] == result["mention_form"]["pairs_sent"]
    assert "not classified" in result["mention_form"]["scope"] and result["R13"]["value"] == 1


def test_sample_is_all_links_up_to_twenty_and_seeded_above(monkeypatch):
    links = [{"link_id": f"lnk_{i:02d}"} for i in range(30)]
    first, again = kit.choose_sample(links, 20261001), kit.choose_sample(links[::-1], 20261001)
    assert first == again and len(first) == 20 and first != kit.choose_sample(links, 7)
    assert kit.choose_sample(links[:5], 1) == sorted(l["link_id"] for l in links[:5])


def view_with(**kw):
    base = {"nodes": {}, "components": [], "cross_relations": [], "not_accepted": [], "pair_decisions": [], "not_sent_budget": [],
            "failed_pairs": [], "unassessed_edges": []}
    return base | kw


def link(frm, to, relation="extends", author="model"):
    return {"from": frm, "to": to, "relation": relation, "author": author}


@pytest.mark.parametrize("view,expected", [
    (view_with(components=[{"links": [link("A", "B")]}]), "won"),
    (view_with(components=[{"links": [link("A", "B", author="human")]}]), "human_only"),
    (view_with(components=[{"links": [link("B", "A")]}]), "reverse_link"),
    (view_with(cross_relations=[link("A", "B", "independent_parallel")]), "independent_parallel_only"),
    (view_with(not_accepted=[{"from": "A", "to": "B", "rejection_code": "cycle"}]), "rejected"),
    (view_with(pair_decisions=[{"from": "A", "to": "B", "decision": "no_relation"}]), "no_relation"),
    (view_with(pair_decisions=[{"from": "A", "to": "B", "decision": "insufficient_evidence"}]), "insufficient_evidence"),
    (view_with(not_sent_budget=[{"from": "A", "to": "B"}]), "not_sent_budget"),
    (view_with(failed_pairs=[{"from": "A", "to": "B"}]), "step_failed"),
    (view_with(), "no_candidate"),
])
def test_g_pair_status_order(view, expected):
    assert kit.g_status(["A"], ["B"], ("a", "b"), view, {"selected": []})["status"] == expected
    plan = {"selected": [{"to": "B", "candidates": [{"from": "A"}]}]}
    if expected == "no_candidate":
        assert kit.g_status(["A"], ["B"], ("a", "b"), view, plan)["status"] == "candidate_unassessed"
        assert kit.g_status(["A"], ["B"], ("a", "b"), view_with(unassessed_edges=[{"from": "A", "to": "B"}]), {})["edge"] == "present"


def test_a_work_is_identified_by_title_start_year_and_first_author():
    run = "roberta a robustly optimized bert pretraining approach"
    g = {"works": [{"key": "r", "match": run, "first_author": "liu", "years": [2019, 2020]}]}
    title = "RoBERTa: A Robustly Optimized BERT Pretraining Approach"
    nodes = {"ok": {"live": True, "title": title, "year": 2019}, "gone": {"live": False, "title": title, "year": 2019},
             "longer": {"live": True, "title": "A replication of " + title, "year": 2019},
             "year": {"live": True, "title": title, "year": 2015}, "author": {"live": True, "title": title, "year": 2020},
             "unknown": {"live": True, "title": title, "year": 2020}}
    authors = {"ok": ["Yinhan Liu", "Myle Ott"], "year": ["Yinhan Liu"], "author": ["Someone Else"]}
    found, rejected = kit.g_nodes(g, {"nodes": nodes}, authors)
    assert found == {"r": ["ok"]} and rejected == {"r": ["author", "unknown", "year"]}
    result = kit.r14({"works": g["works"] + [{"key": "x", "match": "zzz", "first_author": "z", "years": [1]}], "pairs": [["x", "r"]]},
                     view_with(nodes=nodes), {}, authors)
    assert result["pairs"]["x->r"]["status"] == "not_in_table" and result["pairs"]["x->r"]["identity_unverified"] == []
    only_rejected = kit.r14({"works": g["works"] + [{"key": "x", "match": "zzz", "first_author": "z", "years": [1]}], "pairs": [["r", "x"]]},
                            view_with(nodes={"a": nodes["author"]}), {}, authors)
    assert only_rejected["pairs"]["r->x"]["identity_unverified"] == ["r"] and only_rejected["value"] == 0
    assert kit.r14({"works": [], "pairs": []}, view_with(), {}, {})["status"] == "not_measurable"


def test_usage_is_the_nested_total_and_missing_usage_is_reported():
    assert kit.usage_numbers({"total": {"inputTokens": 10, "outputTokens": 2}, "last": {"inputTokens": 4}}) == {"inputTokens": 10, "outputTokens": 2}
    assert kit.usage_numbers({"input_tokens": 3, "ok": True}) == {"input_tokens": 3}
    assert kit.usage_numbers(None) is None and kit.usage_numbers({}) is None


def test_independence_follows_every_version_of_a_work_and_every_identifier_scheme(tmp_path):
    import sqlite3

    def library(path, versions, mappings):
        c = sqlite3.connect(path)
        c.execute("CREATE TABLE source_versions (id TEXT, work_id TEXT, title TEXT, doi TEXT)")
        c.execute("CREATE TABLE identifier_mappings (source_version_id TEXT, scheme TEXT, value TEXT)")
        c.executemany("INSERT INTO source_versions VALUES (?, ?, ?, ?)", versions)
        c.executemany("INSERT INTO identifier_mappings VALUES (?, ?, ?)", mappings)
        c.commit()
        c.close()
        return path

    new = library(tmp_path / "new.sqlite", [("n1", "w1", "New preprint", None), ("n2", "w1", "New published", "10.5/Z"), ("n3", "w2", "Lone", None)],
                  [("n1", "arxiv", "2001.00001"), ("n3", "openalex", "https://openalex.org/W9")])
    ref = library(tmp_path / "ref.sqlite", [("r1", "x", "Owner copy", None), ("r2", "y", "Other owner work", "10.5/z")],
                  [("r1", "arxiv", "2001.00001")])
    found = kit.independence(kit.identifiers(new, ["n1", "n3"]), kit.identifiers(ref))
    assert found["overlapping"] == ["n1"] and found["sources"]["n1"]["matches"] == ["Other owner work", "Owner copy"]
    assert found["unverified"] == [] and found["sources"]["n3"]["matches"] == []


def test_a_run_that_did_not_finish_is_refused_unless_it_is_recorded_as_stopped(finished, monkeypatch):
    lib, run, out, view, g = finished
    lib.conn.execute("UPDATE runs SET status = 'paused' WHERE id = ?", (run["id"],))
    lib.conn.execute("PRAGMA wal_checkpoint(FULL)")
    with pytest.raises(SystemExit, match="run_status_paused"):
        run_cli(monkeypatch, snapshot_args(finished))
    run_cli(monkeypatch, snapshot_args(finished, stopped="quota"))
    result = json.loads((out / "results.json").read_text())
    assert result["stopped"] == "quota" and not (out / "reader.md").exists()
    assert all(result[m] == {"value": None, "denominator": None, "status": "not_measurable", "reason": "run_incomplete"} for m in ("R12", "R13", "R14", "R15"))
    assert result["structure"]["usage"]["sessions"] >= 1


def test_a_started_session_or_a_foreign_run_blocks_a_normal_snapshot(finished):
    lib, run = finished[0], finished[1]
    path = db_path(lib)
    assert kit.verify_run(path, run["id"], None, None) == []
    assert kit.verify_run(path, run["id"], "res_other", "tbl_other") == ["run_belongs_to_another_research", "run_belongs_to_another_table"]
    assert kit.verify_run(path, "run_missing", None, None) == ["run_not_found"]
    lib.conn.execute("UPDATE model_sessions SET status = 'started' WHERE run_id = ?", (run["id"],))
    lib.conn.execute("PRAGMA wal_checkpoint(FULL)")
    assert kit.verify_run(path, run["id"], None, None) == ["started_session_left_open"]


def test_the_reading_must_name_exactly_the_expected_ids_in_a_closed_shape(tmp_path):
    key = {"links": {"L01": "lnk_1"}, "mentions": {"M01": {"passage_id": "p", "from": "a", "to": "b"}}}
    snap = {"links_active_model": 1, "seed": 1, "R14": {}, "R15": {}, "structure": {}}
    good = {"links": {"L01": {"support": "supports", "chronology_only": False}}, "mentions": {"M01": "body"}}
    assert kit.score(snap, key, good)["R12"]["value"] == 1
    bad = [good | {"extra": 1},
           {"links": good["links"] | {"L999": good["links"]["L01"]}, "mentions": good["mentions"]},
           {"links": good["links"], "mentions": good["mentions"] | {"M99": "body"}},
           {"links": {"L01": {"support": "supports", "chronology_only": False, "why": "x"}}, "mentions": good["mentions"]},
           {"links": {"L01": {"support": "supports"}}, "mentions": good["mentions"]}]
    for answers in bad:
        with pytest.raises(SystemExit):
            kit.score(snap, key, answers)
    path = tmp_path / "reader.json"
    path.write_text('{"links": {"L01": {"support": "supports", "chronology_only": false}, "L01": {"support": "partial", "chronology_only": false}}, "mentions": {}}')
    with pytest.raises(SystemExit, match="duplicate"):
        kit.load_reading(path)


def test_stopped_mode_relaxes_completion_only(finished):
    lib, run = finished[0], finished[1]
    path = db_path(lib)
    lib.conn.execute("UPDATE runs SET status = 'paused' WHERE id = ?", (run["id"],))
    lib.conn.execute("PRAGMA wal_checkpoint(FULL)")
    assert kit.verify_run(path, run["id"], None, None, stopped=True) == []
    assert kit.verify_run(path, "run_missing", None, None, stopped=True) == ["run_not_found"]
    assert kit.verify_run(path, run["id"], "res_other", None, stopped=True) == ["run_belongs_to_another_research"]
    lib.conn.execute("UPDATE runs SET status = 'running' WHERE id = ?", (run["id"],))
    lib.conn.execute("PRAGMA wal_checkpoint(FULL)")
    assert kit.verify_run(path, run["id"], None, None, stopped=True) == ["run_not_drained_running", "executing_run_present"]
    lib.conn.execute("UPDATE runs SET status = 'paused' WHERE id = ?", (run["id"],))
    lib.conn.execute("UPDATE model_sessions SET status = 'started' WHERE run_id = ?", (run["id"],))
    lib.conn.execute("PRAGMA wal_checkpoint(FULL)")
    assert kit.verify_run(path, run["id"], None, None, stopped=True) == ["started_session_left_open"]


def test_intervention_counters_block_a_measurement():
    clean = {"human_link_revisions": 0, "human_cell_revisions": 0, "scope_revisions": 1, "non_terminal_runs": 0}
    assert kit.intervention_problems(clean) == []
    assert kit.intervention_problems(clean | {"human_link_revisions": 1, "scope_revisions": 2}) == ["human_link_revisions", "scope_revised"]


def test_publication_dois_and_arxiv_versions_are_one_identity(tmp_path):
    import sqlite3

    def library(path, versions, mappings):
        c = sqlite3.connect(path)
        c.execute("CREATE TABLE source_versions (id TEXT, work_id TEXT, title TEXT, doi TEXT)")
        c.execute("CREATE TABLE identifier_mappings (source_version_id TEXT, scheme TEXT, value TEXT)")
        c.executemany("INSERT INTO source_versions VALUES (?, ?, ?, ?)", versions)
        c.executemany("INSERT INTO identifier_mappings VALUES (?, ?, ?)", mappings)
        c.commit()
        c.close()
        return path

    new = library(tmp_path / "n.sqlite", [("n1", "w1", "A preprint", None), ("n2", "w2", "Another", None)],
                  [("n1", "published_doi", "https://doi.org/10.9/Pub"), ("n2", "arxiv", "2002.00002v3")])
    ref = library(tmp_path / "r.sqlite", [("r1", "x", "The published paper", "10.9/pub"), ("r2", "y", "Other preprint", None)],
                  [("r2", "arxiv", "arXiv:2002.00002v1")])
    found = kit.independence(kit.identifiers(new, ["n1", "n2"]), kit.identifiers(ref))
    assert found["overlapping"] == ["n1", "n2"]
    assert found["sources"]["n1"]["matches"] == ["The published paper"] and found["sources"]["n2"]["matches"] == ["Other preprint"]


def test_unavailable_reading_material_gets_no_score_and_unread_keeps_r14_and_r15(finished, monkeypatch):
    run_cli(monkeypatch, snapshot_args(finished))
    out = finished[2]
    key = json.loads((out / "key.json").read_text())
    snap = json.loads((out / "snapshot.json").read_text())
    answers = {"links": {"L01": {"support": "supports", "chronology_only": False}}, "mentions": {m: "body" for m in key["mentions"]}}
    with pytest.raises(SystemExit, match="unavailable"):
        kit.score(snap, key | {"material_missing": ["L01"]}, answers)
    run_cli(monkeypatch, ["score", "--out", str(out), "--unread", "reader_incomplete"])
    result = json.loads((out / "results.json").read_text())
    assert result["R12"]["reason"] == result["R13"]["reason"] == "reader_incomplete" and result["R14"] == snap["R14"] and result["R15"] == snap["R15"]


def test_the_sheet_uses_the_input_of_the_accepted_revision(finished):
    lib, run = finished[0], finished[1]
    view = json.loads(finished[3].read_text())
    link = kit.active_links(view)[0]
    payload = kit.accepted_input(db_path(lib), link["revision_id"])
    info = kit.collect_sent([payload])[(link["from"], link["to"])]
    assert all(ev["passage_id"] in info["passages"] for ev in link["evidence"])
    assert kit.accepted_input(db_path(lib), "lrv_missing") is None


def test_stopped_mode_allows_only_the_target_to_stay_paused(finished):
    lib, run = finished[0], finished[1]
    path = db_path(lib)
    lib.conn.execute("UPDATE runs SET status = 'paused' WHERE id = ?", (run["id"],))
    other = lib.store.create_run(lib.rid, "answer", {"max_model_calls": 1, "max_provider_requests": 0}, None)
    lib.store.update_run(other["id"], status="paused", pause_reason="user_requested")
    lib.conn.execute("PRAGMA wal_checkpoint(FULL)")
    assert kit.verify_run(path, run["id"], None, None, stopped=True) == ["other_nonterminal_run_present"]
    lib.store.update_run(other["id"], status="cancelled")
    lib.conn.execute("PRAGMA wal_checkpoint(FULL)")
    assert kit.verify_run(path, run["id"], None, None, stopped=True) == []
