<!-- PLAN-REVIEW-ROUNDS: r1 (gpt-6.1-sol medium): düzeltmeyle hazır, 1 high + 6 medium + 1 low, all folded in (collector at the dispatch boundary, accumulator across exits, atomic settlement, scoped equivalence, conformance matrix coverage, excess test sizing, 429 redaction, flow seam); r2: hazır (0 findings). Code: written by gpt-6.1-sol high; reviewed by Claude Opus 5.5, r1 düzeltmeyle hazır (1 high: six existing tests failing in the full run; 1 medium: kill-search trace as hidden instance state), both fixed; r2 hazır. -->

# Task: P7 follow-up batch P7-F, transport accounting (P7-F2) and authenticated OpenAI embeddings (P7-F3)

Worktree: `/Users/huguryildiz/Documents/GitHub/DEIXIS-p7f`, detached at `41495a8` (origin/main with D196, G1 B5).
Read first: `AGENTS.md`, `CLAUDE.md`; in `docs/decisions.md` D196, D194, D174 (Q4 and its section 6.3 in
`docs/product/p7-connector-contract-design.md`, lines 366-383), D173 (G11 embedding errors), D89 (per-query request
shares; `workflow/flow.py:208-237`); `docs/product/p7-acceptance-record.md` section 6 items 7 and 8 and
section 7 rows P7-F2 and P7-F3 (lines 153-165); `docs/product/connector-onboarding.md` ledger rows e, f and j
(lines 134-150). Venv: `PYTHONPATH=backend:. UV_CACHE_DIR=/tmp/deixis-uv-cache .venv/bin/python -m pytest ...`
(`.venv` is a symlink to the arm64 venv of the main checkout).

**No git state-changing commands** (no add, commit, stash, checkout, reset, branch, worktree). Leave every change
uncommitted. No real-model call, no provider call, no network, no DNS, no real key (tests use synthetic keys only).
Do not touch `../DEIXIS*` worktrees, `TODO.md`, `.vscode/`, `scripts/local_index.py`, port 8765 or the live data
directory. The decision number is **D199**; the reviewer writes the decision entry and `STATUS.md`, you do not.
No migration (decision 9).

## Why

D196 left P7's exit unmet until three batches land. This batch is two of them:

- **P7-F2 (item 7, ledger e, D174 Q4).** Discovery counts one base request plus retries per search
  (`workflow/flow.py:2058`, `:2068`), while PubMed sends ESearch and then, when ESearch returned identifiers, EFetch
  (`providers/pubmed.py:143`, `:170`). The EFetch base request is never counted, so a PubMed page that reads records
  costs two requests and charges one, and its query share (D89) does not bound what PubMed sends. Kill-search reserves
  `requests_per_search * (1 + rate_limit_retries)` per transient attempt (`flow.py:4749-4761`), which covers PubMed's
  worst case, but records no observed sends, so reservation and use cannot be told apart. D174 6.3: "each subrequest
  reports its actual attempts/retries. PubMed zero results must not be recorded as two observed sends; EFetch failure
  must retain the successful ESearch provenance. Reservations and observed counts are separate."
- **P7-F3 (item 8).** The OpenAI embedding route (`documents/embeddings.py:284-289` choosing
  `embed_openai_compatible` at `:218` with `OPENAI_URL` and the `OPENAI_API_KEY` key) has no test of its own: D173
  tests the shared function through Ollama and LM Studio (no key, no `Authorization` header), the credential probe has
  Bearer and 401 tests, and missing-key cases exist (`tests/test_settings_connections.py:225`,
  `tests/test_semantic_retrieval.py:151`). Nothing sends an authenticated OpenAI embedding batch and checks the URL,
  model, Bearer placement, a success and a 401.

## What is and is not in code (checked on 41495a8)

Paths under `backend/deixis/` unless stated.

- `providers/common.py:73-86` `SearchOutcome` has `retries` but no per-request record. `send` (`:139-212`) loops: each
  iteration is one HTTP attempt; a 429 (or the provider's rate-limit status) within the allowance increments `retries`
  and loops; every other ending returns. `ConnectError`/`ConnectTimeout` return `failed/before_send` (`:174-175`);
  other `TimeoutException` and `HTTPError` return `after_send_unknown` (`:176-179`). So one `send` call makes
  `1 + retries` attempts, and every attempt except a final `before_send` failure left the client.
- `providers/pubmed.py:127-194`: ESearch through `send` (`:143-146`); zero identifiers return `zero_results` after one
  `send` (`:165-167`); EFetch through a second `send` (`:170-174`); the EFetch outcome's `retries` are added
  (`:176`), and on EFetch failure its `status`, `delivery_class`, `http_status`, `rate_limit`, `error`, `error_kind`
  overwrite the outcome (`:177-185`), so the stored row no longer says ESearch succeeded except through
  `raw_payload["search"]`. An EFetch `ConnectError` makes the whole operation `failed/before_send` although ESearch was
  sent. No other search adapter calls `send` twice for one search (`openalex.py`'s five `send` calls are five
  functions; `semantic_scholar.py`'s two are two endpoints).
- `providers/facade.py:113-126` `dispatch_search` rebuilds the outcome with `dataclasses.replace` (fields kept).
  Adapters' own `not_configured` returns (`core.py:73`, `ieee_xplore.py:67`, `scopus.py:85`, `serpapi.py:61`) send
  nothing.
- `workflow/flow.py:222-237` `page_allowance`: `per_page = 1 + PROVIDER_WAIT[effort] + MAX_TRANSIENT_NETWORK_RETRIES`,
  independent of `requests_per_search`. `PROVIDER_WAIT` is 0/1/2 for quick/standard/detailed
  (`domain/rules.py:41`); `MAX_TRANSIENT_NETWORK_RETRIES = 2` (`rules.py:16`).
- `workflow/flow.py:2039-2073` `_send_search`: per attempt, key guard, quota suppression, then
  `add_usage(run_id, "provider_requests", query=query_key)` before dispatch (`:2058`), dispatch, then
  `add_usage(..., outcome.retries, ...)` (`:2068`). A `failed/before_send` outcome is re-dispatched up to
  `MAX_TRANSIENT_NETWORK_RETRIES` times with no allowance check (`:2069-2073`).
- `workflow/flow.py:2278-2358` `_read_query`: a page is sent only while `_query_requests(run_id, query_key) < allowance`
  (`:2312`); after a page, a used-up share sets `stop_reason = "budget_exhausted"` (`:2350-2351`). Pages are held as
  `_PageRead` (`:241-251`) and written later by `_write_query` (`:2360-2380`) through `_record_search`
  (`:2077-2160`), whose step output carries no transport facts; a failed page's step output is only
  `dropped_records`.
- `workflow/store.py:888-902` `add_usage` adds to `usage[key]` and, with `query`, to `usage["query_requests"][query]`
  in one transaction. `store.py:879` adds one `retry_provider_requests` per failed or budget-exhausted search on a
  retry action; `page_allowance` adds that to every query's share.
- `workflow/flow.py:4744-4767` `_kill_search_request`: per transient attempt, checks
  `used + reserve > max_provider_requests` and charges `reserve` before dispatch, never refunded;
  `_kill_search_record_query` (`:4770-4798`) writes a step output `{"status", "result_count", "dropped_records"?}`.
  `workflow/candidates/run.py:60-66` plans `per_query = requests_per_search * (1 + MAX_RATE_LIMIT_RETRIES) * (1 +
  MAX_TRANSIENT_NETWORK_RETRIES)`; kill-search dispatches with the default `MAX_RATE_LIMIT_RETRIES` (2).
- The UI shows `run.usage.provider_requests` against `run.budget.max_provider_requests`
  (`apps/web/src/Transcript.tsx:542`). Lookups (`lookup_requests`) and chaining (`chain_requests`) are out of scope
  (G1-F1).
- `documents/embeddings.py`: `_send` (`:114-147`) issues one batch with bounded 429 waits; a non-200 raises
  `EmbeddingError(f"HTTP {status}: {error_message(response)}")` (`:209`, `:230`) where `error_message`
  (`models/gemini.py:45-49`) returns the body's `error.message` or text, unredacted. The flow stores `str(exc)` in the
  step error (`flow.py:1960-1962`, `:4207-4209`, `:4256`, `:4262`).

## Decisions

### P7-F2

1. **The dispatch boundary collects every subrequest; adapters cannot drop it** (plan review r1, high). A transport
   collector lives in `providers/common.py`: a `contextvars.ContextVar` holding a list (or None). `common.send` appends
   exactly one entry to the active collector on every return path (success and each failure), before returning:
   `{"url": <scheme://host/path of the request URL, no query, redacted with secrets>, "attempts": retries + 1, "sends":
   attempts minus 1 when the final attempt ended before_send (ConnectError/ConnectTimeout) else attempts, "retries":
   retries, "status": the returned status, "http_status": ..., "delivery_class": ...}`. `facade.dispatch_search` opens a
   fresh collector around the adapter call (reset in `finally`, also when the adapter raises) and returns its entries
   on `Dispatched` as a new field `transport` (a tuple; default empty). The workflow accounts only from
   `Dispatched.transport`, never from anything the adapter returns, so an adapter that rebuilds or drops its outcome
   cannot refund work it sent. `SearchOutcome`, its classification, `retries`, every frozen field and
   `tests/connector_baseline.py::recorded_outcome` stay unchanged; `tests/fixtures/connectors/baseline.json` and
   `query_baseline.json` stay byte-identical. The onboarding rule becomes: every request of a search adapter goes
   through `common.send`; a request that bypasses it is a conformance failure (test 1 catches it against the mock
   transport's request count).
2. **PubMed's two stages are two entries.** No change to `pubmed.py` is needed: ESearch and EFetch each go through
   `send`, so zero identifiers or an ESearch failure or parse error yield one entry, and an attempted EFetch a second.
   On an EFetch failure the top-level outcome keeps its current (frozen) overwrite, while the ESearch entry keeps its
   own `completed`/200: that is the retained ESearch provenance D174 6.3 asks for. Change `pubmed.py` only if a test
   proves an entry is missing, and say why.
3. **Definitions used by both workflow paths.** For one dispatch: `attempts = Σ entry.attempts`, `sends = Σ
   entry.sends`. Worst case of one dispatch: `R = requests_per_search × (1 + max_rate_limit_retries passed to that
   dispatch)` (in discovery `page.rate_limit_retries`, or `MAX_RATE_LIMIT_RETRIES` without a page; in kill-search the
   stored transport row's `rate_limit_retries`). A new run usage key `provider_sends` counts observed sends in both
   paths; it never touches `query_requests`. Flow-made outcomes (missing key, quota suppression, transport budget,
   continuation refusal) dispatch nothing and add nothing. A dispatch that raises (ledger d: `ContractViolation`,
   `KeyError`) keeps whatever was charged before it and propagates as today; its collector entries are lost with the
   exception and that stays a recorded limit of ledger d.
4. **Discovery reconciliation: reserve, then settle to attempts.** In `_send_search`, per dispatch attempt: charge `R`
   to `provider_requests` and the query's `query_requests` before dispatch (write-ahead reservation, so a crash in
   flight leaves a conservative count, never an undercount); after dispatch settle in **one transaction** that adds
   `attempts - R` to both `provider_requests` and the query's `query_requests` (normally negative; positive only if an
   adapter exceeded its declared cost, which must be charged, not hidden) and adds `sends` to `provider_sends`. Add one
   `store` method for that settlement (for example `settle_usage(run_id, query, request_delta, sends)`); `add_usage`
   keeps its meaning for existing callers. A test injects a failure between the updates and shows nothing is half
   written. After settlement `provider_requests` equals the attempts discovery made, which is today's `1 + retries`
   for a single-request connector on every dispatch sequence that decision 5c does not cut short; PubMed now charges
   ESearch and EFetch attempts. A connect failure still charges its attempt (today's rule) but adds no send.
5. **Discovery bound.** (a) `page_allowance` uses `per_page = requests_per_search × (1 + PROVIDER_WAIT[effort]) +
   MAX_TRANSIENT_NETWORK_RETRIES`, unchanged for every connector with `requests_per_search = 1`; PubMed's share now
   covers its two subrequests per page. (b) D89's send rule stays: a page is sent while the query's settled count is
   below its share. (c) New: `_send_search` re-dispatches a transient `failed/before_send` outcome only while the
   query's settled count is below `page.allowance`; otherwise it returns that failed outcome (the page fails as any
   failed page does, D18). (d) The resulting bound, to be stated in the decision and pinned by a test: a query starts
   no dispatch once its settled count reaches its share, and one dispatch charges at most `R` (more only if an adapter
   exceeds its declaration, which decision 4 charges and decision 7 records), so a query's settled count never
   exceeds `share - 1 + R`. A strict "worst case must fit" pre-check is not adopted for discovery: the retry action
   adds only one request per failed search to each share (`store.py:879`), and a strict check would stop retried
   PubMed and 429-heavy reads that today send one more page.
6. **Kill-search reconciliation: reservation never refunded, sends observed.** Keep the per-attempt reservation check
   and charge (`flow.py:4757-4761`) and the plan (`candidates/run.py:60-66`). After each dispatch, in one transaction,
   add `sends` to `provider_sends` and, if `attempts > reserve`, charge the excess to `provider_requests`. So for
   kill-search `provider_requests` is reserved cost (an upper bound, plus any recorded excess), `provider_sends` is
   observed, and `provider_sends <= provider_requests` always.
7. **Per-operation transport record, kept across every exit** (plan review r1, medium). One accumulator per logical
   operation (a discovery page, a kill-search query) spans all its dispatch attempts and survives every exit of the
   retry loop, including a missing key or a transport-budget refusal after an earlier dispatch (the key-refresh case
   of `tests/test_connector_contract.py:564-580`). The step written for that operation (discovery: succeeded, failed or
   `outcome_unknown`; kill-search: any) gets `output["transport"] = {"reserved": Σ R charged, "attempts": Σ, "sends":
   Σ, "over_reservation": Σ max(0, attempts - R) (only when nonzero), "dispatches": [{"subrequests": [...]} per
   dispatch attempt, transient re-dispatches included]}`; it is omitted only when the whole operation dispatched
   nothing. For a discovery step whose final outcome is flow-made after an earlier dispatch (missing key), the record
   is written on that same failed step (`_record_search`'s `not_configured` branch included). Carry it from the host
   task to `_write_query` on `_PageRead` (a new field); do not write steps from the host task (D89's write boundary).
   Existing exception, documented, not changed: a stop during transient backoff returns `None` and a crash in flight
   loses the in-memory page, so no step carries that operation's transport record; the usage counters (reservation or
   settlement) are already written. No `search_runs` column, no `connector_json` change, no change to rows written
   before this batch.
8. **Out of scope, stays as recorded limits:** lookup and chaining accounting (`lookup_requests`, `chain_requests`,
   G1-F1); `RetryPolicy` driving retries (ledger g); the OpenAlex count and distribution probes; PubMed's top-level
   `before_send` class on an EFetch connect failure (frozen; the subrequest entries now show ESearch was sent); the
   retry action's one-per-failed-search share (D89/13f); any UI label for `provider_sends`.
9. **No migration.** Everything new lives in run usage JSON and step output JSON.

### P7-F3

10. **Provider-specific tests on the authenticated route,** not only the shared-path argument: with
    `OPENAI_API_KEY` set to a synthetic key in the test's environment and an `httpx.MockTransport`, `Embedder("openai",
    OPENAI_MODEL).embed(...)` must send `POST https://api.openai.com/v1/embeddings`, header
    `Authorization: Bearer <synthetic key>` exactly once and no `x-goog-api-key`, JSON `{"model":
    "text-embedding-3-small", "input": [...]}` with inputs truncated to `MAX_CHARS`, batches of `BATCH`; a 200 reply
    with shuffled `index` values returns unit vectors in input order; a 401 raises `EmbeddingError` starting
    `HTTP 401:` after exactly one request with no retry; a missing key sends nothing; Ollama and LM Studio through the
    same function send no `Authorization` header (the shared-path contrast).
11. **Own-key redaction in embedding errors (named behavior change).** If a reply body echoes the request key,
    `EmbeddingError` text must not contain it: redact the sent key (only that key, as the provider modules do with
    `common.redact`) in every `EmbeddingError` message built from a reply, including the exhausted-429 messages raised
    inside `_send` (`embeddings.py:140-141`) before either wrapper's non-200 check; give `_send` the secret or wrap its
    raise, whichever is smaller. Test, for OpenAI and for Gemini, a 401 body and an exhausted-429 body that echo the
    synthetic key.
12. **One workflow-level case each way,** through the direct flow seam that `tests/test_semantic_retrieval.py:75-81`
    uses (a `ResearchFlow` with an injected `httpx.AsyncClient` on a mock transport), with the `semantic_search`
    setting `{"provider": "openai", "model": "text-embedding-3-small"}` and a synthetic key: a success stores
    similarities under stored model `openai:text-embedding-3-small`; a 401 ends the embedding step with
    `embedding_failed`, an error starting `HTTP 401`, and the synthetic key (echoed in the 401 body) absent from every
    stored row, step output, event and payload file the test can read.

## Files

Allowed: `providers/common.py` (the collector and `send` only), `providers/facade.py` (`Dispatched.transport` and
`dispatch_search` only), `providers/pubmed.py` only under decision 2's condition, `workflow/flow.py` limited to `page_allowance`,
`_PageRead`, `_send_search`, `_record_search`'s step outputs, `_read_query`/`_write_query` plumbing of the transport
record, `_kill_search_request`, `_kill_search_record_query`; `workflow/store.py` (the settlement method),
`documents/embeddings.py` (redaction only), new test files `tests/test_transport_accounting.py` and
`tests/test_openai_embedding.py`, and existing tests only where a named change requires it (list each with the reason
in your report). Docs: `docs/product/connector-onboarding.md` (ledger rows e, f, j: owner "P7-F2 fixed (D199)" with
the new evidence; add to the onboarding procedure that every request of a search adapter goes
through `common.send`), `docs/product/p7-acceptance-record.md` (items 7 and 8 dispositions, the P7-F2 and P7-F3 rows of
section 7, section 10's embeddings and connectors rows; leave the verdict to the reviewer),
`docs/product/p7-coverage-verification.md` (the OpenAI row of the embeddings table, line 43, whose last cell says no
OpenAI-specific error test is shown).

Forbidden: migrations, `contracts/`, `methods/`, `domain/contracts.py`, `providers/openalex.py` and
`providers/registry.py` (parallel batch P8 B5 owns OpenAlex; `requests_per_search` is already declared), every other
provider module, model steps and `watch_check` dispatch in `flow.py` (parallel batches P9 RF and P8 B5), `apps/web`,
the frozen fixtures, `docs/decisions.md`, `STATUS.md`.

## Tests that must fail on the old code (name each in your report with the old failure)

1. **Registry-driven conformance** (inside the existing registry-driven conformance replay, the 566-case matrix of
   `tests/test_connector_contract.py`, directly and through `facade.dispatch_search`, so a new connector must pass it;
   keep the baseline equality checks and serializer separate and unchanged): for every case that returns an outcome,
   `Σ attempts` over the collected entries equals the requests the mock transport received, `Σ sends` equals that
   minus the scripted connect failures, `Σ retries == outcome.retries`, `len(entries) <= requests_per_search`, each
   entry's `retries` is within the allowance the call passed, and no entry contains the synthetic key; cases that raise
   before sending assert zero entries explicitly. The matrix must include connect failure, read timeout, retry
   exhaustion and both PubMed stages; add cases where it lacks one. Two synthetic adapters that send through `send`
   and then return a fresh outcome (one dropping everything, one dropping its second stage) are still charged in full
   by discovery and kill-search. Report the case count.
2. **PubMed through the collector:** zero identifiers → one ESearch entry, attempts 1, sends 1; ESearch 200 + EFetch
   200 → two entries; ESearch 429,200 + EFetch 429,429,200 → attempts 5, retries 3; EFetch 500 → ESearch entry
   completed/200 kept, EFetch entry failed/500; EFetch ConnectError → EFetch entry attempts 1 sends 0, ESearch entry
   sends 1; ESearch ConnectError → one entry, sends 0.
3. **Discovery:** a PubMed page reading records charges `provider_requests == query_requests == 2` and
   `provider_sends == 2` (old: 1, no sends); zero results → 1 and 1; EFetch 429s counted; a page's step output carries
   the transport record, including on an EFetch failure (ESearch entry present) and on a missing key after an earlier
   dispatch; during flight the reservation `R` is visible in usage (block the mock transport on an event) and settles
   to attempts after; the settlement is atomic (decision 4); a single-request page with 429 retries and a
   connect-failure-then-success sequence keeps today's `provider_requests` and adds the right `provider_sends`;
   with an allowance spent by earlier attempts, a transient `before_send` failure is not re-dispatched (decision 5c,
   a named change for every connector); a PubMed read stops with `budget_exhausted` where the corrected count says so,
   and no query's settled count exceeds `share - 1 + R`; `page_allowance` for PubMed versus a single-request connector
   at each effort. Existing exact comparisons that now see a `transport` output (for example
   `tests/test_search_parallelism.py:302-339`) compare the original fields unchanged and assert `transport` separately;
   synthetic adapters in existing tests that manufacture outcomes without `send` (for example
   `tests/test_connector_contract.py:550-552,571-573`) keep their assertions and are adjusted only as needed.
4. **Kill-search:** PubMed with full ESearch+EFetch, zero results and 429s: `provider_requests` stays the
   reservations, `provider_sends` is observed, `provider_sends <= provider_requests`, step output transport has
   `reserved`; a transport-budget refusal after an earlier dispatch keeps that dispatch's record; a synthetic
   registry-only connector declaring `requests_per_search=1` whose adapter makes two `send` calls each scripted
   `429,200` (four attempts against a reservation of three) is charged four and records `over_reservation` 1; discovery
   gets its own excess case with its actual retry allowance.
5. **Embeddings:** decision 11's echoed-key redaction, 401 and exhausted 429, for OpenAI and Gemini (fails on old code); decisions 10 and 12
   (characterization, may pass on old code; say so).

Run the focused files and `tests/test_connector_contract.py`, `tests/test_connector_dispatch.py`,
`tests/test_connector_facade.py`, `tests/test_candidate_run.py`, `tests/test_search_paging.py`,
`tests/test_search_parallelism.py`, `tests/test_semantic_retrieval.py` in the sandbox. You cannot bind sockets; the
reviewer runs the full pytest outside the sandbox.

## Report

Write `/tmp/p7f-impl-report.md`: changed files with line ranges, each decision with where it is implemented, every
existing test you changed and why, each new test with the old-code failure you observed (run the new tests against a
`git stash`-free copy: `git show 41495a8:<path>` into a temporary directory, or explain why you could not), focused
test counts, anything you did not do or could not verify.
