"""What a search plan was written from, as one fingerprint, and what changed between two plans (P4).

Pure: no database, no clock, no network, no model. Everything here is a function of the stored StepInput payload the
plan step sent and of the record the step kept, so the same stored run always gives the same fingerprint.

A plan is a model's answer, so the same question can give different terms on different days. To tell a changed plan
from a changed input, the run stores a fingerprint of everything that decided the plan:

- **what it read**: the whole payload the call was sent, as it was sent, except the fields that are not a reading —
  this call's own id, and the writer (the model asked and the instruction package), which the other half holds. The
  payload's order is part of it, because the call reads the records in the order they were sent.
- **what wrote it**: the plan rule, the answer's schema, the instruction package, and the model asked and resolved
  with the effort it was asked at.

The two halves are hashed apart as well as together, so a second plan over the same records with a newer model is
told from a plan over different records. `difference` then says, between two plans, which terms were added, which
were dropped, which stayed but changed place, and where a block's own order changed.
"""

from __future__ import annotations

import re
from typing import Any

from deixis.domain import canonical

RULE = "plan_identity_v1"
# Where a plan may put a term: the two blocks the main query joins, and each block's backups — the alternatives for
# the same concept, used in order when a chosen term of that block finds nothing. A term that changes place is
# neither added nor dropped: the plan still holds it, in another part of the query.
BLOCKS = ("setting", "task", "setting_backup", "task_backup")
# Fields of the payload that are not part of what the call read: the id of this very call, and the writer, which the
# fingerprint's other half names. Everything else the step sent is a reading and is hashed as it was sent.
NOT_READ = ("step_input_id", "model", "skill_package_hash")


def read_inputs(payload: dict[str, Any]) -> dict[str, Any]:
    """The payload as the call read it: every field the step sent except the ones `NOT_READ` names."""
    return {key: value for key, value in payload.items() if key not in NOT_READ}



def fingerprint(payload: dict[str, Any], record: dict[str, Any], plan_rule: str,
                schema_version: str | None = None) -> dict[str, Any]:
    """The fingerprint of one plan: the hash of what it read, the hash of what wrote it, and the two together.

    `payload` is the stored StepInput the step sent, `record` what the step kept of the call (`skill_package_hash`,
    `resolved_model`). Two runs whose plans have the same `sha256` were written from the same payload by the same
    model under the same instructions, so their plans may be compared term by term; the same `inputs_sha256` with
    another `versions_sha256` is the same reading answered by another writer.
    """
    model = payload.get("model") or {}
    versions = {"plan_rule": plan_rule, "task_type": payload.get("task_type"),
                "schema_version": schema_version or (record.get("answer") or {}).get("schema_version"),
                "skill_package_hash": record.get("skill_package_hash"),
                "requested_model": model.get("requested_model"),
                "reasoning_effort": model.get("reasoning_effort"),
                "resolved_model": record.get("resolved_model")}
    inputs_sha = canonical.sha256_hex(read_inputs(payload))
    versions_sha = canonical.sha256_hex(versions)
    return {"rule": RULE, "inputs_sha256": inputs_sha, "versions_sha256": versions_sha,
            "records": len(payload.get("sources") or []), "versions": versions,
            "sha256": canonical.sha256_hex({"rule": RULE, "inputs": inputs_sha, "versions": versions_sha})}


def key_of(term: str) -> str:
    """The text two plans are compared by: case and runs of whitespace do not make a term another term."""
    return re.sub(r"\s+", " ", term).strip().casefold()


def terms_of(answer: dict[str, Any]) -> dict[str, str]:
    """Each term of a plan's answer and where it was put, by the term's comparison key.

    A term written twice in one place is one term; a term in two places keeps the first `BLOCKS` names, so a chosen
    term that became its block's backup reads as a move rather than as an addition and a removal.
    """
    found: dict[str, str] = {}
    for block in BLOCKS:
        for term in (answer.get(block) or []):
            text = term.get("term") if isinstance(term, dict) else term
            if isinstance(text, str) and key_of(text) not in found:
                found[key_of(text)] = block
    return found


def order_of(answer: dict[str, Any]) -> dict[str, list[str]]:
    """Each place's own order of terms: a backup list is used in order, so its order is part of the plan."""
    return {block: [key_of(term["term"] if isinstance(term, dict) else term)
                    for term in (answer.get(block) or [])
                    if isinstance(term.get("term") if isinstance(term, dict) else term, str)]
            for block in BLOCKS}


def difference(before: dict[str, Any], after: dict[str, Any]) -> dict[str, Any]:
    """What changed between two plan answers: the terms `after` adds, the ones it drops, the ones it keeps in another
    place, and the places whose own order changed. Each list is sorted, so the same pair always gives the same
    report; a term is named by its comparison key."""
    first, second = terms_of(before), terms_of(after)
    moved = [{"term": term, "from": first[term], "to": second[term]}
             for term in sorted(first.keys() & second.keys()) if first[term] != second[term]]
    one, two = order_of(before), order_of(after)
    reordered = {block: {"before": one[block], "after": two[block]} for block in BLOCKS if one[block] != two[block]}
    return {"added": sorted(second.keys() - first.keys()), "removed": sorted(first.keys() - second.keys()),
            "moved": moved, "kept": len(first.keys() & second.keys()) - len(moved), "reordered": reordered}
