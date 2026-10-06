# Search measurement tools

These tools implement the frozen 6 October 2026 protocol, §7 step 2. They do not run the product, call a model, open the live library, or implement a production search feature. All acceptance evidence in `tests/measurement/test_search_measurement.py` is synthetic.

The four benchmark JSON files preserve 6/18/23/32 target rows, the English question hashes, frozen labels and 2/3/3/3 keys. Labels come from model agreement and the delegated §9 decisions, not independent human source verification. Unverified alternate DOIs remain separate identity candidates. A title match needs adjudication. IRS is an untuned validation set for this round, not a guaranteed unseen test.

## Pinned SQLite measurement

Use an authorized isolated snapshot with its `provider-payloads/` directory. The script refuses a missing `DEIXIS_DATA_DIR`, opens SQLite with `mode=ro` and `query_only`, and holds one read transaction. It never opens a default library. Supply an answer ID and output path explicitly:

```sh
DEIXIS_DATA_DIR=/tmp/authorized-isolated-snapshot PYTHONPATH=backend uv run python scripts/benchmark/check.py RESEARCH_ID --answer ANSWER_ID --ranking-step RANKING_STEP_ID --benchmark scripts/benchmark/kurt2017.json --output /tmp/kurt-measurement.json
```

For a WAL-mode library, use a consistent, checkpointed snapshot copy (for example, an authorized SQLite backup); copying only `library.sqlite` while committed pages remain in WAL loses records. Checkpoint the isolated copy before measurement, not the live service. Existing output files are refused unless `--force` is supplied.

The backend does not record `ranking_step_id` in answer StepInput. By default, the tool selects the last successful ranking in the same research and scope revision completed at or before the answer input, including discovery runs, and labels the binding `inferred_by_time`. This is a temporal inference, not a recorded answer-to-ranking link. A legacy input reference is retained when present; an audited `--ranking-step` overrides either binding. Every selection must have succeeded in the same research/revision before the input. No eligible ranking leaves coverage unmeasurable. Work ranks collapse versions at their first appearance; all source versions remain in the report. Target rows retain their identifiers as `target_key` after sanitization.

Raw counts come from retained, hash-checked provider bodies or explicit returned-count telemetry. Filtered `result_count` and provider estimates are separate. Retries whose bodies were not retained cannot be reconstructed as raw records. Older cache and actual send telemetry is reported as `ölçülemiyor`, never inferred as zero. Transport traces, when retained, show sends, retries, endpoint and purpose; mutable run budget counters remain separately labelled. Model sessions count adapter invocations, which do not establish actual provider sends. Embedding, waits, PDF sends and the requested final-state duration remain unmeasurable where there is no sufficient record.

PDF lookup, recorded download attempt, available asset and full-text decision are separate. PDF candidates preserve only their latest attempt, so the recorded count is not a complete attempt history. Only the pinned StepInput's nonempty passage text establishes passage delivery. A published citation also needs a stored evidence link, a supplied passage and a contiguous source-owned anchor. These checks do not establish semantic support; the owner still assesses the frozen answer elements and numeric claims.

`frozen_pool` is an exportable A-pool object. Save that object as a separate JSON file for the survey experiment. Its records preserve versions and query origins; ordering uses the pinned inspection ranking, then recorded search order. `ranked_records` can supply one arm to the blind-form input described below.

## Blind relevance forms

The input file contains `{"question": "...", "arms": {"A": [records in ranking order], "C": [...]}}`. Each record needs a verified work ID, DOI or provider ID, title and optional abstract. Identity is resolved before ranks are assigned. Identical work labels are reused across arms.

```sh
PYTHONPATH=backend uv run python scripts/benchmark/labels.py forms /tmp/ranked-arms.json /tmp/blind-forms
PYTHONPATH=backend uv run python scripts/benchmark/labels.py merge /tmp/blind-forms/model_1.json /tmp/blind-forms/model_2.json /tmp/merged.json
PYTHONPATH=backend uv run python scripts/benchmark/labels.py score /tmp/blind-forms/private_key.json /tmp/blind-forms/owner.json /tmp/merged.json /tmp/precision.json
```

Give the owner only `owner.json`; give the two models their independent files. Keep `private_key.json` private: it contains arm/rank mapping and the deterministic shuffle seed. Public forms omit arms, positions, scores and target/key flags, and show items in shuffled order. Each evaluator fills `label` (`relevant`, `irrelevant`, `uncertain`), `reason` and `reading_depth` (`metadata`, `title_only`, `abstract`, `selected_pdf_passage`, `full_text`). A relevant work provides a method or result for at least one frozen answer subquestion; general topic similarity is insufficient. DBR/VBF does not require both protocols in every work.

The merger checks form IDs, item sets, evaluator identity and evidence equality. Disagreements go to `owner_disagreements`; unresolved disagreements remain uncertain and stay in the denominator. The optional `--adjudications` file is a list of those item IDs with an owner label, reason and reading depth. P@20 uses owner labels. P@50 is explicitly a mixture of owner and model assessment, not human verification. Short lists use their actual length; an empty list has no precision value.

## Model-free survey experiment

`survey.run(pool, set_name, send, output, mode=...)` accepts a frozen pool and an injected transport. `send(request)` must perform exactly one HTTP send and return `Response(status_code, body_bytes)`, with all hidden retries, pagination, resolution and fallback disabled. The repository supplies no network transport. The CLI only replays a supplied response file:

```sh
PYTHONPATH=backend uv run python scripts/benchmark/survey.py --pool /tmp/frozen-A.json --set dbr_vbf --responses /tmp/scripted-responses.json --output /tmp/survey-replay
```

Replay format is an ordered list of `{"request": {...}, "status_code": 200, "body": {...}}` entries; `timeout: true` simulates timeout. The request has exactly `provider`, `endpoint` (`search`, `references`, `citations`, `resolve`), `seed`, `query`, `ids`, `offset`, `limit`. Bodies may have normalized `records`, OpenAlex `results` / `referenced_works`, or Semantic Scholar `data` / `citedPaper` / `citingPaper`. OpenAlex reference IDs are resolved in batches of 50, each charged to the same budget. Unsupported pagination remains explicitly truncated. Semantic Scholar references always stop at the first page; next offset, total and limit remain recorded even for an empty return.

B takes the first eight A titles containing survey/review/tutorial, using at most 10 requests. C reuses that exact B prefix and its cost, then spends the remaining allowance on fixed queries and up to eight new survey seeds. OpenAlex precedes Semantic Scholar. N uses A's first eight unique resolvable works for backward/forward chaining, up to 20 requests. All arms allow at most 100 additional unique works, and retries spend the request allowance. A 429 is retried at most twice; other failures remain explicit. A retained oversized page is preserved while only the remaining capacity is admitted. Every resolved link is retained; relevance is assessed separately from retrieval, so no title/abstract similarity heuristic is presented as a relevance judgment. This all-links filter is recorded before scoring.

Bodies are sanitized before persistence: credential fields, bearer values and credential-bearing URL components are removed. SHA-256 refers to the retained sanitized body. Invalid JSON bodies are omitted because they may echo credentials; their failure status remains. Keep output directories outside Git and supply a new or empty directory. Replay request counts measure original request positions, not new HTTP sends.

`report.json` records A/B/C/N pools, seeds, requests, identities, version aliases, truncation, unavailable references, partial failures and the N prefix at B/C's request count. The CLI scores frozen targets only after traversal, writing `target-score.json` with per-layer/key coverage and B−A/C−A/C−B/N−A target differences. Targets never select seeds. Known-target coverage is not recall over the literature; a naturally retrieved source tutorial can make survey coverage circular.

The fixed request allocation is B ≤ 10, C including B ≤ 20, and N ≤ 20; `allocation` records B's actual cost and C's remaining allowance. A survey already in A is never counted as a new C seed, even if B did not select it. Same-DOI duplicates and verified versions with different DOIs are reported separately. Target scoring shares the SQLite tool's DOI/verified-work identity rule.

`equal_send_comparisons` scores B−N and C−N at equal request prefixes, with gains, losses, net target gain and key counts. The §4 preference requires at least one net additional relevant target and no fewer key targets; the latter must hold for every question when results are combined. If N did not reach the comparator's cost, the shorter equal prefix is shown but `preference_rule_met` remains null. These per-question reports do not establish the aggregate four-question decision.

## Verification

```sh
PYTHONPATH=backend uv run pytest tests/measurement/test_search_measurement.py
PYTHONPATH=backend uv run pytest
git diff --check
```

If the sandbox cannot write the normal uv cache, prefix the same commands with `UV_CACHE_DIR=/tmp/deixis-measurement-uv-cache`. No new test directory or Python path change is needed.
