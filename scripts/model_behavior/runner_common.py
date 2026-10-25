"""Helpers the candidate and lineage case runners share: the stop rule for one model call and the results file writer."""
from __future__ import annotations

import json
import os
import re
import tempfile
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from deixis.models.adapter import is_rate_limited


def _stop_for_run(case_id: str, run: dict[str, Any], adapter_result: Any, model: str) -> str | None:
    error = run["error"] or ""
    if run["status"] == "isolation_violation":
        return f"{case_id}: isolation_violation: {error}"
    if run.get("tool_item_types"):
        return f"{case_id}: tool items: {run['tool_item_types']}"
    normalized_error = re.sub(r"[^a-z0-9]+", " ", error.lower())
    if is_rate_limited(adapter_result) or re.search(
        r"\b(?:quota|rate\s?limit\w*|429|usage\s?limit\w*|insufficient\s?quota|overload(?:ed)?|capacity)\b",
        normalized_error,
    ):
        return f"{case_id}: rate, quota, or capacity limit: {error}"
    if run["resolved_model"] is None and error:
        return f"{case_id}: {error}"
    if run["resolved_model"] != model:
        return f"{case_id}: resolved model {run['resolved_model']!r} differs from {model!r}"
    return None


def _write_results(out_dir: Path, payload: dict[str, Any], out_file: Path | None = None) -> Path:
    out_dir.mkdir(parents=True, exist_ok=True)
    body = json.dumps(payload, indent=2, ensure_ascii=False)
    if out_file is None:
        out_file = out_dir / "results.json"
        while True:
            try:
                with out_file.open("x"):
                    pass
                break
            except FileExistsError:
                now = datetime.now(timezone.utc)
                out_file = out_dir / f"results-{now:%H%M%S%f}.json"
    temp_path: Path | None = None
    try:
        with tempfile.NamedTemporaryFile(mode="w", encoding="utf-8", dir=out_dir,
                                         prefix=".results-", suffix=".tmp", delete=False) as stream:
            temp_path = Path(stream.name)
            stream.write(body)
        os.replace(temp_path, out_file)
    finally:
        if temp_path is not None:
            temp_path.unlink(missing_ok=True)
    return out_file
