# Isolated question-term and diverse-query comparison

**Status:** opt-in development experiment. This protocol changes neither the DEIXIS product search planner nor its default query compiler. The previous quantum run is a development case with known misses, not an independent benchmark. Its frozen evidence remains untouched.

## Question and arms

Use the exact quantum question and the five frozen OpenAlex queries from the 2026-09-18 500→1000 run as arm A. Arm B follows a hybrid division of labor:

1. Code extracts contiguous one- to three-word candidate terms from the question, recording their source spans. This immutable list is made before any model or provider call. It is a lexical candidate list, not a claim that each item is a useful search term.
2. The selected Gemini text model assigns literal candidates to `core`, `mechanism`, `method`, `operation`, `constraint`, and `context` families and may propose additional field terms. The model cannot change the recorded literal candidates. Its additions remain model proposals, with provenance distinct from literal terms. No control DOI, Elicit row, prior result, or known-paper title is supplied to the model.
3. Code validates literal references, safe term syntax, family cardinality, provider query shape, uniqueness and budgets. For this question's explicit `in …?` field phrase, it requires that exact question literal in the context family; it also requires a multiword core literal containing the one-word anchor. The broad one-word anchor is used in the method and operation arms, but is not allowed to displace the multiword core phrase in the first arm. The compiler then writes five OpenAlex title-and-abstract queries: core vocabulary; context with mechanism; a literal domain anchor with method; the same anchor with operation; context with constraints. Thus some arms do not require the narrow distribution/routing phrase. A malformed proposal fails before discovery; no silent model or provider fallback.

`prepare` freezes the code candidates, model output, accepted/rejected terms, compiled queries, model identity/effort, protocol hash and arm-A plan hash before any OpenAlex request. Both arms use `search.title_and_abstract`, the same `per_page=100`, five query slots and exactly two page requests per slot: **10 logical requests and at most 1,000 returned slots per arm**. A page may return fewer than 100 rows, so 500 returned records are not guaranteed. Calls are interleaved by page and slot. Errors and retries are logged; a failed call makes the comparison partial, never a zero-result success.

The experiment compares **text discovery only**. It does not run citation expansion, PDF fetching, embedding ranking, model screening, human screening, or an answer. This isolates the query change. Save each raw provider response and route, exact DOI/OpenAlex identities, suspected same-title versions, per-query marginal identities, returned and unique counts, request attempts, and wall-clock time in a new ignored `.local/` directory. No real DEIXIS library or port 8765 is used.

## Evaluation boundary

Only after both arms finish, inspect the six reused control DOIs and Elicit's included CSV in a separately labelled post-run comparison. Report exact DOI and independently checked title/version matches separately. These known papers have informed the proposed strategy and cannot measure independent recall. A product-default decision requires new questions, independently chosen controls, equal request/result and human-screening budgets, blinded human relevance labels, and per-query marginal included-study yield. Candidate counts, model proposals, and control overlap are not final include/exclude decisions.

## Commands

```sh
uv run python scripts/isolated_query_branches.py prepare --baseline-plan .local/quantum-hybrid-500-1000-2026-09-18-run-b/frozen-plan.json --model gemini-3.5-flash --reasoning-effort medium --plan-dir .local/quantum-query-branches-plan --env-file .env
uv run python scripts/isolated_query_branches.py run --plan .local/quantum-query-branches-plan/plan.json --output-dir .local/quantum-query-branches-run --env-file .env
```

Use new empty directories for each attempt. Keep credentials out of plans, logs, reports and version control. The CLI output and stored results must distinguish a prepared plan from a completed live comparison.
