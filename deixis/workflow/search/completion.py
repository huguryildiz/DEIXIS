"""Completing OpenAlex with Semantic Scholar: what the run observed, and the request each observation allows.

The design names three observable states and one action each. The first — a work whose DOI is known and whose abstract
is missing — is the batch abstract lookup that `lookups.py` already does, and nothing here touches it. The other two
are this arm:

* OpenAlex could not complete **for a technical reason** → send a short text from the question to the relevance search.
* OpenAlex answered, but a part of the question the plan named is not met in what the main query found → send a
  snippet query for that part.

Both are conditional, and both record what they observed even when they send nothing, so the decision not to send can
be read back instead of guessed at.
"""

from __future__ import annotations

import json
from typing import Any

from deixis.providers import semantic_scholar

RELEVANCE_KEY = "search:fast:s2_relevance"
SNIPPET_KEY = "search:fast:s2_snippet"  # one step per concept: `search:fast:s2_snippet:<n>`

# What a run observed about its own OpenAlex requests, read from the statuses those requests recorded.
# `records`: at least one request brought a record, so nothing is missing and the fallback is not sent.
# `valid_zero`: every request that was sent answered, and at least one answered with no record. A valid zero is not a
#   failure, so it sends nothing either.
# `technical_failure`: no request brought a record and at least one that was sent failed for a technical reason.
# `not_sent`: no OpenAlex request of this run was sent at all, so there is nothing to call a failure.
OPENALEX_OUTCOMES = ("records", "valid_zero", "technical_failure", "not_sent")
# The statuses `search_runs.status` is closed to. Two of them are an answer; every other one is the provider failing to
# answer, whether it refused, timed out or answered unreadably.
ANSWERED = ("completed", "zero_results")

# Why the arm sent nothing. `gap_already_met` is the snippet arm's own gate (`search_plan.GAP_ALREADY_MET` says the
# same about the focused query); the rest are shared.
ALWAYS = "always"  # the arm that sends on every question of the depth, whatever the gate read

NOT_FROZEN = "not_frozen"  # the run's policy froze no completion arm
EXCLUDED = "excluded"  # the person's saved plan leaves Semantic Scholar out
OPENALEX_ANSWERED = "openalex_answered"  # the fallback's own condition did not hold
BUDGET = "budget"  # the arm's record reservation or the keyword cap is spent
DEADLINE = "deadline"  # the search stage's deadline, or the depth's handover, passed first


def relevance_spec(question: str, records: int) -> dict[str, Any]:
    """The fallback's frozen request: a short text from the person's own question, in whatever language they wrote it.

    No model writes it and nothing translates it, exactly as the question's own semantic request is written by code
    alone. `semantic_scholar.query_text` cuts it and takes the hyphens out, which that endpoint needs.
    """
    return {"provider_id": "semantic_scholar", "query_text": semantic_scholar.query_text(question),
            "limit": records, "query_origin": "question"}


def snippet_specs(queries: list[dict[str, Any]], main_terms: list[str], allowance: int, records: int,
                  arm: str) -> list[dict[str, Any]]:
    """One snippet request per focused concept the plan named, inside the depth's allowance.

    The `always` arm is the measurement's control, so it must send on every question of the depth: its requests are
    not held back by the gate, and where the plan named no concept at all it asks for the question's own main terms
    (`index` None: no concept's gate decides it). Without that, `always` would send nothing on exactly the questions
    `conditional` sends nothing on, and the two arms could not be told apart.

    The text asks for the concept and the main query's terms **together**, as plain words: this endpoint supports no
    syntax, so the three stand in one relevance query instead of a Boolean constraint, which is the design's own
    example — when each protocol appears but their comparison does not, ask for both protocols and the comparison
    together. The concept's `gap` sentence is not in the text: the contract says it is shown to the person and never
    read by a rule, and a query is read by a rule.

    `index` is the place in the compiled queries of the focused query whose gate decides this one: the condition is
    the record that query already writes, so no second trigger is invented.
    """
    specs: list[dict[str, Any]] = []
    seen: set[str] = set()
    for index, query in enumerate(queries):
        if query.get("role") != "focused" or query["provider_id"] != "openalex":
            continue
        term = (query.get("focused") or {}).get("term")
        if not term or term in seen:
            continue
        seen.add(term)
        if len(specs) >= allowance:
            break
        specs.append({"provider_id": "semantic_scholar", "endpoint": semantic_scholar.SNIPPET_ENDPOINT,
                      "query_text": semantic_scholar.query_text(" ".join([term, *main_terms])),
                      "limit": min(records, semantic_scholar.SNIPPET_MAX_RESULTS),
                      "index": index, "focused": dict(query["focused"])})
    if arm == ALWAYS and len(specs) < allowance and main_terms:
        specs.append({"provider_id": "semantic_scholar", "endpoint": semantic_scholar.SNIPPET_ENDPOINT,
                      "query_text": semantic_scholar.query_text(" ".join(main_terms)),
                      "limit": min(records, semantic_scholar.SNIPPET_MAX_RESULTS),
                      "index": None, "focused": None})
    return specs


def snippet_key(position: int) -> str:
    return f"{SNIPPET_KEY}:{position}"


def arm_keys(plan: dict[str, Any]) -> list[str]:
    """Every step key of the arm in this plan: the fallback and one per frozen snippet request."""
    return [RELEVANCE_KEY] + [snippet_key(position) for position, _ in enumerate(plan.get("s2_snippet") or [])]


def spent(store: Any, run_id: str, plan: dict[str, Any]) -> int:
    """Records the arm has already read in this run, counted from the requests it really sent.

    A resumed run reads this back before it sends anything: `arm_spent` starts at zero in a new process, so without
    it an earlier attempt's records would be free and the reservation could be read twice over.
    """
    keys = arm_keys(plan)
    marks = ", ".join("?" for _ in keys)
    row = store.conn.execute(
        f"SELECT COALESCE(SUM(sr.result_count), 0) AS records FROM search_runs sr JOIN run_steps s ON s.id = sr.step_id"
        f" WHERE sr.run_id = ? AND s.operation_key IN ({marks})", (run_id, *keys)).fetchone()
    return int(row["records"] or 0)


def view(store: Any, research_id: str, revision: int, until: str | None = None) -> dict[str, Any] | None:
    """What the completion arm came to in this question revision, or None where no run of it froze an arm.

    The repo rule is that a source searched in another's place after a failure is recorded **and shown**, so this is
    what the method box reads: the arm, what the run observed about OpenAlex, whether the request went out, what it
    answered and, where it did not go out, the recorded reason. `until` is the answer's own time bound: the latest
    discovery run **at or before** the answer answers for it, so a later run can never change what an earlier answer
    says it did. Omitted, the latest run of the revision answers.

    Whether the request was sent is read from the search run the request itself recorded, never from the step's
    status: a request that reached the provider and was refused is a request that went out, and a failed step would
    otherwise be reported as if nothing had been sent.
    """
    row = store.conn.execute(
        "SELECT s.status, s.error_code, s.output_json, sr.status AS request_status, sr.result_count"
        " FROM run_steps s JOIN runs r ON r.id = s.run_id"
        " LEFT JOIN search_runs sr ON sr.step_id = s.id"
        " WHERE r.research_id = ? AND r.scope_revision = ? AND r.kind = 'discovery' AND s.operation_key = ?"
        " AND (? IS NULL OR r.created_at <= ?)"
        " ORDER BY r.created_at DESC, s.rowid DESC LIMIT 1",
        (research_id, revision, RELEVANCE_KEY, until, until)).fetchone()
    if row is None:
        return None
    output = json.loads(row["output_json"] or "{}")
    observed = output.get("openalex") or {}
    sent = row["request_status"] is not None
    return {"arm": output.get("arm"), "state": observed.get("state"), "sent": sent,
            "records": (row["result_count"] or 0) if sent else 0,
            # A request that went out and was refused says so; one that never went out gives the recorded reason.
            "request_status": row["request_status"],
            "reason": None if sent else (row["error_code"] or output.get("stop_reason")),
            # The per-status counts behind the state, so the sentence can name what OpenAlex actually did.
            "failures": observed.get("failures") or {}}


def openalex_outcome(store: Any, run_id: str) -> dict[str, Any]:
    """What this run's own OpenAlex requests came to, and the statuses behind it.

    Every OpenAlex request of the run counts: the question's semantic request, the block terms' request, each seed's
    request and every keyword page. A step that was cancelled or never sent recorded no search run, so it is none of
    these states and is counted apart (`not_sent`): a request that never went out can never make a run look as if
    OpenAlex had failed.
    """
    rows = store.conn.execute(
        "SELECT sr.status, sr.result_count FROM search_runs sr JOIN run_steps s ON s.id = sr.step_id"
        " WHERE sr.run_id = ? AND sr.provider = 'openalex' AND s.kind LIKE 'provider_search:%'", (run_id,)).fetchall()
    statuses: dict[str, int] = {}
    records = 0
    for row in rows:
        statuses[row["status"]] = statuses.get(row["status"], 0) + 1
        records += row["result_count"] or 0
    failures = {status: count for status, count in statuses.items() if status not in ANSWERED}
    if not rows:
        state = "not_sent"
    elif records:
        state = "records"
    elif failures:
        state = "technical_failure"
    else:
        state = "valid_zero"
    return {"state": state, "requests": len(rows), "records": records, "statuses": statuses,
            # Recorded even where it decides nothing: a run with records and a failure beside them sends no fallback,
            # and the pilot still needs to see that OpenAlex half failed.
            "failures": failures}
