"""Synthetic measurement attribution; no live model or provider evidence."""

import hashlib
import json
import sqlite3

from scripts.benchmark.compare_small_batch_sessions import collect, packed_calls, carried_calls, seconds


def test_packing_counts_sparse_windows_instead_of_assuming_twenty_plus_ten():
    positions = [*range(1, 11), *range(31, 41), *range(61, 71)]
    assert packed_calls(positions, 30) == 6
    assert packed_calls(positions, 40) == 4
    assert packed_calls([], 40) == 0
    assert carried_calls(positions) == 4
    assert carried_calls(range(41)) == 6
    assert carried_calls([]) == 0
    assert seconds(10.0, 21.5) == 11.5
    assert seconds("2026-10-07T10:00:00+00:00", "2026-10-07T10:00:20+00:00") == 20


def test_recorded_sessions_count_repairs_exclude_table_calls_and_leave_snapshot_unchanged(tmp_path):
    db = tmp_path / "library.sqlite"
    conn = sqlite3.connect(db)
    conn.executescript("""
        CREATE TABLE model_sessions(id,step_id,step_input_id,run_id,research_id,started_at,finished_at,status);
        CREATE TABLE step_inputs(id,task_type,attempt,payload_json,research_id,created_at);
        CREATE TABLE runs(id,research_id,kind);
        CREATE TABLE run_steps(id,run_id,operation_key,kind,started_at,finished_at,output_json);
        CREATE TABLE search_runs(step_id,research_id,provider,query_text,status,result_count,page_number);
    """)
    conn.executemany("INSERT INTO runs VALUES (?,?,?)", [("d", "r", "discovery"), ("a", "r", "answer"), ("t", "r", "table_fill")])
    start, end = "2026-10-07T10:00:00+00:00", "2026-10-07T10:00:20+00:00"
    for i, run, task, attempt in [(1, "d", "criterion_proposal", 1), (2, "a", "grounded_answer", 1),
                                  (3, "a", "grounded_answer", 2), (4, "t", "cell_extraction", 1)]:
        conn.execute("INSERT INTO run_steps VALUES (?,?,?,?,?,?,?)", (i, run, str(i), "model:" + task, start, end, None))
        conn.execute("INSERT INTO step_inputs VALUES (?,?,?,?,?,?)", (i, task, attempt, "{}", "r", start))
        conn.execute("INSERT INTO model_sessions VALUES (?,?,?,?,?,?,?,?)", (i, i, i, run, "r", start, end, "completed"))
    conn.commit()
    conn.close()
    (tmp_path / "drive.json").write_text(json.dumps({"research_id": "r", "discovery_started": start, "answer_done": end}))
    before = hashlib.sha256(db.read_bytes()).hexdigest()
    result = collect(tmp_path)
    assert result["calls"] == 3
    assert result["tasks"]["grounded_answer"] == {"calls": 2, "session_seconds": 40, "attempt_gt1": 1}
    assert result["tasks"]["criterion_proposal"]["calls"] == 1
    assert "cell_extraction" not in result["tasks"]
    assert result["elapsed_seconds"] == 20
    assert result["unchanged"] and result["snapshot_sha256"] == before == hashlib.sha256(db.read_bytes()).hexdigest()
