"""The estimated cost of a research before it starts (pre-P10 F4).

A wide range, never one number: from the fewest calls with the smallest inputs and no reasoning, to the most calls the
depth allows with the largest inputs, a schema repair after every repairable call and the model's reasoning tokens. The
sizes that code knows are real (the method files and output schemas of each step are measured from the loaded package,
a passage is at most one chunk, the call counts are `fast_path.MODES` and `domain.rules`); the sizes the model and the
sources decide (an abstract's length, the answer's length, the reasoning) are assumptions, listed in the answer so the
screen can show them. Nothing here was measured on a real run; the provider's own bill is what counts.

Only the roles on a paid-API model are priced. A role on a subscription or a local model costs nothing per call. A role
on a model with no listed price has no estimate, and the answer says so instead of counting it as zero.
"""

from __future__ import annotations

import math
from typing import Any

from deixis.domain import contracts
from deixis.domain.rules import ABSTRACT_BATCH, ABSTRACT_RUNS, FULLTEXT_PASSAGES_PER_CALL, FULLTEXT_RUNS, TEST_EFFORT_BUDGETS
from deixis.models import prompt
from deixis.workflow import fast_path, spend

ROLES = ("literature", "answer", "reviewer")
CHARS = spend.CHARS_PER_TOKEN
# Characters of one stored passage in a step: a chunk is at most 1,400 characters (documents.pdf.CHUNK_CHARS), an abstract
# is shorter; the record around it adds about 500 characters of JSON.
PASSAGE_CHARS = (900, 1900)
ABSTRACT_RECORD_CHARS = (600, 2400)
# Reasoning tokens a call may add on top of its answer, by the reasoning effort chosen for the role. A model that lists
# no effort ("provider default") is assumed up to the middle figure.
REASONING_TOKENS = {"none": 0, "minimal": 500, "low": 1500, "medium": 4000, "high": 10000, "xhigh": 16000, "max": 16000}
REASONING_DEFAULT = 2000


def _tasks(effort: str, reading_on: bool) -> list[dict[str, Any]]:
    """Each step type the fast path may call: its role, how many calls (fewest, most), the characters its input adds to
    the fixed instructions (smallest, largest), the output tokens of one call (smallest, largest), and whether an invalid
    answer is repaired once."""
    _, n, k, *_ = fast_path.MODES[effort]
    batches = math.ceil(n / ABSTRACT_BATCH)
    passages = TEST_EFFORT_BUDGETS[effort].max_answer_passages
    answer_chars = (passages // 2 * PASSAGE_CHARS[0], passages * PASSAGE_CHARS[1])
    tasks = [
        ("research_title", "answer", (1, 1), (1000, 6000), (30, 150), True),
        ("vocabulary_labels", "literature", (0, 3), (500, 2000), (100, 600), False),
        ("search_query", "literature", (1, 2), (1000, 4000), (200, 1200), True),
        ("criterion_proposal", "literature", (0, 3), (500, 2500), (150, 800), True),
        ("abstract_screening", "literature", (ABSTRACT_RUNS, ABSTRACT_RUNS * batches),
         (ABSTRACT_BATCH * ABSTRACT_RECORD_CHARS[0], ABSTRACT_BATCH * ABSTRACT_RECORD_CHARS[1]), (ABSTRACT_BATCH * 25, ABSTRACT_BATCH * 100), False),
    ]
    if reading_on:
        reading = (FULLTEXT_PASSAGES_PER_CALL * PASSAGE_CHARS[0], FULLTEXT_PASSAGES_PER_CALL * PASSAGE_CHARS[1])
        tasks.append(("fulltext_adjudication", "literature", (0, FULLTEXT_RUNS * k), reading, (150, 900), True))
    # The answer, a rewrite when too many claims are inference, and one late revision when full text arrives after it.
    tasks.append(("grounded_answer", "answer", (1, 3), answer_chars, (800, 6000), True))
    tasks.append(("answer_review", "reviewer", (0, 1), (answer_chars[0], answer_chars[1] + 8000), (300, 3000), True))
    return [dict(zip(("task", "role", "calls", "variable_chars", "output_tokens", "repairable"), t)) for t in tasks]


def _fixed_tokens(package: Any, task: str) -> int:
    """The tokens every call of a step type carries: base instructions, the method files and the output schema, measured."""
    chars = len(prompt.BASE_INSTRUCTIONS) + len(prompt.developer_instructions(package, task)) + len(str(contracts.model_output_schema(task)))
    return chars // CHARS


def estimate(package: Any, effort: str, roles: dict[str, dict[str, Any] | None], *, reading_on: bool,
             embedding_provider: str, rerank_provider: str | None = None) -> dict[str, Any]:
    """`roles` maps each of literature, answer and reviewer to `{connection, model, reasoning_effort}` or None (no
    reviewer). The answer holds the range in US dollars over the priced roles, what each role and step type contributes,
    and the assumptions behind it, as numbers for the screen to word."""
    tasks = _tasks(effort, reading_on)
    rows, role_totals = [], {role: {"low": 0.0, "high": 0.0, "calls_low": 0, "calls_high": 0} for role in ROLES}
    for task in tasks:
        choice = roles.get(task["role"])
        if not choice or spend.kind_of(choice["connection"]) != "api":
            continue
        prices = spend.price_for(choice["connection"], choice["model"])
        fixed = _fixed_tokens(package, task["task"])
        low_in, high_in = fixed + task["variable_chars"][0] // CHARS, fixed + task["variable_chars"][1] // CHARS
        low_out, high_out = task["output_tokens"]
        high_out += REASONING_TOKENS.get(choice.get("reasoning_effort") or "", REASONING_DEFAULT)
        calls_low, calls_high = task["calls"]
        repairs = calls_high if task["repairable"] else 0
        row = {"task": task["task"], "role": task["role"], "calls": [calls_low, calls_high + repairs],
               "input_tokens": [low_in, high_in], "output_tokens": [low_out, high_out], "repairable": task["repairable"],
               "usd": None}
        if prices is not None:
            def dollars(calls: int, tokens_in: int, tokens_out: int) -> float:
                return calls * spend.cost_of(prices, {"input": tokens_in, "cached_input": 0, "cache_write": 0, "output": tokens_out})
            low = dollars(calls_low, low_in, low_out)
            # A repair sends the input again with the failed output after it.
            high = dollars(calls_high, high_in, high_out) + dollars(repairs, high_in + high_out, high_out)
            row["usd"] = [low, high]
            role_totals[task["role"]]["low"] += low
            role_totals[task["role"]]["high"] += high
        role_totals[task["role"]]["calls_low"] += calls_low
        role_totals[task["role"]]["calls_high"] += calls_high + repairs
        rows.append(row)
    role_rows = []
    for role in ROLES:
        choice = roles.get(role)
        kind = spend.kind_of(choice["connection"] if choice else None)
        priced = kind == "api" and spend.price_for(choice["connection"], choice["model"]) is not None
        role_rows.append({"role": role, "connection": choice["connection"] if choice else None,
                          "model": choice["model"] if choice else None, "kind": kind, "priced": priced,
                          "usd": [role_totals[role]["low"], role_totals[role]["high"]] if priced else None,
                          "calls": [role_totals[role]["calls_low"], role_totals[role]["calls_high"]] if kind == "api" else None})
    paid = [r for r in role_rows if r["kind"] == "api"]
    priced = [r for r in paid if r["priced"]]
    table = spend.price_table()
    return {
        "applies": bool(paid), "effort": effort,
        "usd": [sum(r["usd"][0] for r in priced), sum(r["usd"][1] for r in priced)] if priced else None,
        "complete": bool(paid) and len(priced) == len(paid),
        "roles": role_rows, "tasks": rows,
        "embedding": {"provider": embedding_provider, "paid": embedding_provider in ("gemini", "openai", "voyage", "cohere"), "included": False},
        # The record reranker in force (Voyage by default, D104): billed by its provider, not in this range.
        "reranking": {"provider": rerank_provider, "paid": rerank_provider not in (None, "builtin"), "included": False},
        "prices": {"version": table["version"], "as_of": table["as_of"]},
        "assumptions": {"chars_per_token": CHARS, "passage_chars": list(PASSAGE_CHARS), "abstract_chars": list(ABSTRACT_RECORD_CHARS),
                        "reasoning_tokens": REASONING_TOKENS, "reasoning_default": REASONING_DEFAULT,
                        "cached_input_discount": False, "repair": "once per repairable call, in the high figure only"},
    }
