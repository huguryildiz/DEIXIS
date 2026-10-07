"""Read stored batch records for shared-stage assertions; never execute an old policy."""
import json
from collections import Counter


def stage_output(store, run_id, key):
    rows = store.conn.execute(
        "SELECT output_json FROM run_steps WHERE run_id = ? AND status = 'succeeded'"
        " AND (operation_key = ? OR operation_key LIKE ?) ORDER BY rowid",
        (run_id, key, f"small_batch:v1:%:{key}")).fetchall()
    outputs = [json.loads(r[0]) for r in rows if r[0]]
    if not outputs:
        return None
    result = dict(outputs[0])
    for field in result:
        values = [o[field] for o in outputs if field in o]
        if isinstance(result[field], list):
            result[field] = [item for value in values for item in value]
        elif isinstance(result[field], dict) and all(isinstance(v, (int, float)) for value in values for v in value.values()):
            total = Counter()
            for value in values:
                total.update(value)
            result[field] = dict(total)
        elif isinstance(result[field], int) and field not in ("limit", "batch", "runs"):
            result[field] = sum(values)
    if key == "abstract_stage":
        result["limit"] = store.run(run_id)["budget"].get("inspection", {}).get("abstract_limit", result["limit"])
    return result
