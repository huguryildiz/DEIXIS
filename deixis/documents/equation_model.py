"""A model as the reader of one numbered display equation from its page crop (D113): the equations model set in
Settings, else the answer model (D136).

Only the crop's PNG and the fixed instruction below are sent: never the PDF, its text or anything about the paper. The
answer is used only when the call completed, carried no tool item, parses to exactly `{"latex": <text>}` and was given by
the model that was asked (or its own dated snapshot); anything else is stored and refused, never placed. The reading then
goes through the same gate as Mathpix's (`equation_regions.gate`), without the confidence check: a model gives none.

Measured 20 Oct 2026 (`notes/2026-10-20-equation-bench`, 204 numbered equations of 34 arXiv papers, the authors' LaTeX as
the reference): Claude Sonnet 5.5 at medium effort 78% exact and 93% within 0.1 normalized edit distance, about 2 s per
equation; the gate was not part of that measurement.
"""

from __future__ import annotations

import json
from typing import Any

from deixis.models.adapter import ModelStepResult, is_dated_snapshot

ENGINE = "model"
VERSION = "model-eq-v1"
PROMPT_VERSION = "eq-prompt-v1"  # part of the key an answer is reused under
INSTRUCTION = ("The image is a crop of one displayed equation from a scientific PDF. Transcribe that one equation into "
               "LaTeX. Give the LaTeX only: no $ or \\[ delimiters, no explanation, and leave out the equation number and "
               "any \\tag. If the equation spans several lines, separate them with \\\\.")
MESSAGE = "Transcribe the equation in the image."
SCHEMA: dict[str, Any] = {"type": "object", "additionalProperties": False, "required": ["latex"],
                          "properties": {"latex": {"type": "string"}}}


def choice(store: Any) -> dict[str, Any] | None:
    """The equations model in Settings ({connection, model, reasoning_effort}), else the default answer model, or None
    when neither is named."""
    for role in ("equations", "answer"):
        saved = store.setting(role) or {}
        if isinstance(saved, dict) and saved.get("model_connection") and saved.get("model"):
            return {"connection": saved["model_connection"], "model": saved["model"],
                    "reasoning_effort": saved.get("reasoning_effort") or None}
    return None


def accept(result: ModelStepResult, requested_model: str) -> tuple[str | None, str | None]:
    """(latex, None) for an answer that may be placed, else (None, why it is refused)."""
    if result.tool_item_types or result.status == "isolation_violation":
        return None, "tool_item"
    if result.status != "completed":
        return None, "not_completed"
    resolved = result.resolved_model
    if not resolved or not (resolved == requested_model or is_dated_snapshot(requested_model, resolved)):
        return None, "model_mismatch"
    try:
        parsed = json.loads(result.raw_text or "")
    except ValueError:
        return None, "invalid_output"
    if not (isinstance(parsed, dict) and set(parsed) == {"latex"} and isinstance(parsed["latex"], str)):
        return None, "invalid_output"
    return parsed["latex"], None
