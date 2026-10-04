<!-- PLAN-REVIEW-ROUNDS: r1 (gpt-6.1-sol medium): düzeltmeyle hazır, 3 medium + 1 low, all folded in; r2: düzeltmeyle hazır, 1 medium (retry-range rule named in the amendment), folded in; r3: hazır; agreed decision 8 (B3b not folded) and the decision 2 version-rule amendment. Code: written by gpt-6.1-sol high; reviewed by Claude Opus 5.5, r1 hazır (0 high, 0 medium). -->

# Task: P7 G1 batch B3a, search facades: request validation and measured equivalence

Worktree: `/Users/huguryildiz/Documents/GitHub/DEIXIS-g1-b3a`, detached at `18be383` (origin/main with D178, B2).
Design: `docs/product/p7-connector-contract-design.md` (accepted as D174). Read sections 4, 4.1, 6.2, 8.1, 9 and 10
(row B3a, around line 529, and the paragraph after the table). Also read `AGENTS.md`, `CLAUDE.md`, D178 and D177 in
`docs/decisions.md`, `docs/product/connector-onboarding.md` (its ledger is the list of known mismatches; rows
`option_types`, `g` and `d` concern this batch) and `docs/archive/p7/p7-g1-b2-prompt.md` (what B2 built). Venv:
`PYTHONPATH=backend:. UV_CACHE_DIR=/tmp/deixis-uv-cache .venv/bin/python -m pytest ...` (`.venv` is a symlink to the
arm64 venv of the main checkout).

**No git state-changing commands** (no add, commit, stash, checkout, reset, branch, worktree). Leave every change
uncommitted. No real-model call, no provider call, no network, no DNS. Do not touch `../DEIXIS*` worktrees, `TODO.md`,
`.vscode/`, `scripts/local_index.py`, the live service on port 8765, or the live data directory.

Batch B3a only. B3b (query rendering delegation), B4 (dispatch through the facade, provenance, lookup binding,
identity admission, payload sanitization) and B5 are later batches; do not start them. Application dispatch keeps
calling the registry callables; `workflow/` does not import or call the facade. The decision number is **D179** (one
entry).

## Why

D174 row B3a: "Wrap all ten connectors in `providers/`; keep registry dispatch unchanged". Exit: "Every registered
connector and S2 endpoint has request/output equivalence against integrated G8, including existing `ValueError`
paths; D172 direct no-send guards and B2 dispatched guard unchanged; no new provider enabled or legacy workflow
restored". D178 adds one gate: the facade must check option value types before send (`PENDING_B3A`), and B3a cannot
exit until it does. B4 will move dispatch onto the facade, so B3a must also show that every argument shape the
dispatcher builds today is representable as a `SearchRequest` and behaves identically through the facade.

## What is and is not in code (checked on 18be383)

Already met (do not rebuild):

- **All ten connectors are wrapped.** `providers/facade.py:39-41` `connectors()` builds one generic
  `CompatibilityConnector` per `registry.CONNECTORS` entry (`registry.py:88-121`), descriptors derived at call time
  (`facade.py:9-34`), no provider-ID literal (`tests/test_connector_boundary.py:153`). Both S2 endpoints are declared
  (`registry.py:94-97`). No per-provider facade module is needed; do not add one.
- **Baseline equivalence, 111 cases.** `tests/test_connector_boundary.py:327-334` replays every frozen case
  (`tests/fixtures/connectors/baseline.json`, `base_commit` `5990b02`) through the registry callable and through the
  facade and requires identical requests, waits and outcomes, including the existing `ValueError` paths (offset
  providers' `bad_offset_-1`/`bad_offset_x`, S2 `cut_cursor`). The one declared difference is an unknown S2 endpoint:
  module `ValueError` versus the facade's pre-send `ContractViolation` (a `ValueError` subclass, `contract.py:47`).
  G8 (D173) is integrated: the freeze contains quota/rate-limit cases (`ieee_per_second`, `ieee_per_day`,
  `serpapi_exhausted`, `openalex_zero_usd`, `pubmed_efetch_quota`, `quota_exhausted`, `retry_then_success`).
- **Guards.** D172 direct guards (`ieee_xplore.py:66`, `scopus.py:84`, `core.py:72`, `serpapi.py:60`) and B2's
  dispatched guards (`workflow/flow.py:2044-2047`, `:4671-4674`) are tested by `tests/test_providers.py:423-438`,
  `tests/test_connector_contract.py:408-423` (direct and facade, `None` and `""`) and the four dispatched regressions
  (`test_connector_contract.py:473-660`). B3a touches none of their code.
- **Descriptor retry policy partly checked by behavior.** `check_case` (`test_connector_contract.py:340-348`) derives
  expected waits for `rate_*` cases from the descriptor's `unstated_wait`, `min_interval` and `shared_gate`; static
  checks at `test_connector_boundary.py:95-145`.

Missing:

- **Option value types (ledger `option_types`).** `facade.py:72-81` checks only that option names are declared, then
  forwards any value. `OptionDescriptor.value_type` (`contract.py:66-69`; `bool` for OpenAlex `reference_count` and
  `references`, `str` for S2 bulk `sort`, `facade.py:19-20`) is never consulted. `PENDING_B3A`
  (`test_connector_contract.py:140-144`) names the three cases; `test_pending_and_existing_evidence` (`:433-443`)
  checks them against the ledger but runs nothing. `max_rate_limit_retries` is forwarded unchecked as well
  (`facade.py:77-80`).
- **Conformance matrix only through the facade.** The B2 suite's 566 cases (`test_conformance_case`, `:373-374`) call
  `replay_case(..., direct=False)` (`:246`, `:299-305`); the registry callable is replayed only for the 111 baseline
  cases and the access cases. Direct/facade equality over the full error, paging and identity matrix is not measured.
- **Dispatcher argument shapes.** `flow.py:2053-2056` calls `connector.search(http, query_text, limit, key, email,
  **({"cursor": page.cursor, "max_rate_limit_retries": page.rate_limit_retries, **connector.sw_options,
  **endpoint_options(query)} if page else {}))`; kill-search (`flow.py:4681-4682`) passes `**endpoint_options(query)`
  only (`registry.py:181-183`: `endpoint` and `sort` when not None). No test maps these exact keyword shapes to a
  `SearchRequest`; the only mapping is inline in `tests/connector_baseline.py:175-178`. Whether every shape is
  representable (for example an `sw_options` key that a named endpoint does not declare) is unchecked.
- **Retry policy agreement (ledger `g`, B3a part).** Not checked by behavior: the module default
  `max_rate_limit_retries` when a request omits it, which statuses are retried (`rate_limit_statuses`; arXiv 406,
  `common.py:153-157`, `:196`), and the `timeout` each request carries (`common.py:141`, `:167-168`; SerpApi passes
  60.0, `serpapi.py:68`).

## Decisions taken where the design is open (use these; never ask)

1. **One named behavior change: request field validation in the facade.** In `CompatibilityConnector.search`, after
   the endpoint is resolved and option names are checked, and before any call: every supplied option value must match
   its `OptionDescriptor.value_type`, with `bool` meaning `type(value) is bool` and `str` meaning `type(value) is str`
   (so `1`, `0`, `"true"`, `None` are not bool; `17`, `True`, `None`, `b"x"` are not str). An empty string is a valid
   `str` (S2 bulk reads `""` as its default sort today, `semantic_scholar.py:77-78`; refusing it would be a second
   change). When `OptionDescriptor.values` is not None, the value must also be one of them (no registered option
   declares values today; test it with a synthetic connector or a monkeypatched descriptor). `max_rate_limit_retries`,
   when supplied (not None; `SearchRequest` uses None for omission, `contract.py:125-127`), must satisfy
   `type(value) is int and value >= 0`. A violation raises `ContractViolation` with a
   message naming the field, never a provider ID; zero requests. Generic code only (no provider literal). The registry
   callables, provider modules and `workflow/` are unchanged, so direct calls behave exactly as before; dispatch never
   builds such values (decision 4 proves the shapes it builds pass).
2. **Revisions and freeze: an explicit, bounded amendment of the version rules.** The onboarding rule
   (`../../product/connector-onboarding.md:53-59`, `contract.py:3-7`) bumps `adapter_revision` for request semantics. Refusing values
   the facade used to forward does change which facade requests are accepted, so the exception must be written down,
   not inferred. Amend the "Version and unsupported rules" section of `../../product/connector-onboarding.md` and the
   `contract.py`-equivalent wording in the `facade.py` module docstring (not `contract.py` itself) with this rule:
   *enforcing, in the facade before any send, an input constraint the descriptor already declares (option names,
   option value types and values, request field types), plus one expressly adopted facade rule that no descriptor
   declared before B3a (`max_rate_limit_retries`: None means omission; otherwise an exact, nonnegative `int`; today
   `-1` is forwarded and `common.py:198` reads it as no retries), is not an adapter semantic change and needs no
   `adapter_revision` bump, provided every request it still accepts produces the same requests and outcomes as
   before and the registry callables are unchanged; any change to what an accepted request sends or returns still
   needs the bump.* Under that rule there is no `adapter_revision` bump, no `CONTRACT_ID` change, no
   `QUERY_RULES_REVISION` change, and `baseline.json` stays byte-identical (prove it: run `capture()` into a scratch
   file outside the repo and compare it with the checked-in file; do not use `--write`; if the comparison shows a
   difference, stop and report). D179 records the amendment and that gpt-6.1-sol medium accepted it in plan review
   round 1 as the alternative to bumping all affected revisions.
3. **One request mapping.** Add a pure function `facade.search_request(query_text, limit, **kwargs) ->
   contract.SearchRequest` that maps a registry-call keyword set to a request: `cursor`, `max_rate_limit_retries` and
   `endpoint` go to their fields (absent means None), every other keyword goes to `options`. It validates nothing (the
   facade's `search` does) and names no provider. `tests/connector_baseline.py` `replay` uses it in place of its inline
   mapping (`:175-178`), behavior-identical. `workflow/` does not use it in B3a; B4 will.
4. **Dispatcher-shape equivalence.** New test module `tests/test_connector_facade.py`. It has its own autouse fixture
   that blocks `socket.socket.connect`, `socket.getaddrinfo` and HTTPX's real transports
   (`httpx.AsyncHTTPTransport.handle_async_request`, `httpx.HTTPTransport.handle_request`) and supplies only synthetic
   credentials (design section 8.1, `../../product/p7-connector-contract-design.md:472-475`); importing the guards of
   `test_connector_contract.py`/`test_connector_boundary.py` does not activate them. For every registered connector
   and every declared endpoint, enumerate the keyword shapes `flow.py` builds, derived only from registry fields
   (`sw_options`, `sw_query`, `endpoints`, `paging`) and `registry.endpoint_options`, never from a provider literal:
   (a) unpaged legacy search: `{}`; (b) kill-search: `endpoint_options(q)` for a stored query naming no endpoint and
   for one naming each declared endpoint, with `sort` taken from `connector.sw_query` when that names the same
   endpoint; (c) paged read: `cursor` in {`FIRST_PAGE`, the first page's `next_cursor` (or `"ignored"` for
   `single_page`)}, `max_rate_limit_retries` in {0, 2}, `**connector.sw_options`, and `**endpoint_options(q)` for a
   pre-D93 stored query (no endpoint) and for a routed compiled query (`connector.sw_query`). Each shape is sent
   direct and as `facade.search(facade.search_request(...))` on the same native positive script from the B2
   conformance fixtures; for (c) also against a 429 without Retry-After, so the forwarded retry allowance is visible.
   Compare as in decision 5. Every shape must be representable (no `ContractViolation`); a future connector whose
   `sw_options` a named endpoint does not declare must fail this test by name (add a synthetic-connector case proving
   that). Cite `flow.py:2053-2056` and `:4681-4682` in the test docstring; replicate the expressions, do not import
   private flow code.
5. **Full-matrix direct/facade equivalence.** For every `CASES` entry of `tests/test_connector_contract.py`
   (import it; do not copy the case list), replay the case direct and through the facade with the same fixture, key
   and fake clock, and require equality of: recorded requests (`baseline.recorded_request`, plus each request's
   `extensions["timeout"]`), waits, and the whole `SearchOutcome` (`dataclasses.asdict`, including records, `raw`,
   `raw_payload`, `rate_limit`, `retries`, `error_kind`, `next_cursor`). Compare structures directly; do not route
   through `baseline.recorded_outcome`, whose secrecy assertions belong to other tests (keyless cases may echo the
   synthetic string as provider text, B2 decision 2c). If `replay_case` needs a parameter to expose what is compared,
   add it without changing its default behavior. No exception list: none of the 566 conformance cases sends an
   invalid request, so every case must compare equal; if any case differs, stop and report.
6. **Retry descriptor agreement (ledger `g`, B3a part).** For every registered provider/endpoint pair, through the
   facade and direct: (a) `inspect.signature(connector.search).parameters["max_rate_limit_retries"].default` equals
   the descriptor's `retry.max_rate_limit_retries`, and a request that omits the field, scripted with 429s without
   Retry-After, ends `rate_limited` with `retries` equal to that value and waits from `unstated_wait` (as `check_case`
   computes them); (b) every status in `retry.rate_limit_statuses` is retried once and then succeeds, and 406 for a
   pair whose statuses exclude it is `failed`/`rejected_not_executed` with zero retries (generic: derived from the
   descriptor, no provider literal); (c) every request's `extensions["timeout"]` (connect, read, write, pool) equals
   `retry.timeout`, including both PubMed requests. `RetryPolicy` still does not drive `send`; policy-driven
   dispatch stays unscheduled. If a pair disagrees with its descriptor, stop and report (a descriptor fix would need
   the reviewer's decision).
7. **`PENDING_B3A` closes.** Remove `PENDING_B3A` and its assertion lines in `test_pending_and_existing_evidence`.
   Replace them with `test_option_value_types_refused_before_send` in `tests/test_connector_facade.py`, parametrized
   from the facade descriptors (every declared option of every pair, so a new declared option is covered without a
   new branch) over the wrong values of decision 1, plus the three named D178 cases (integer 17 as OpenAlex
   `reference_count`, `references`, and S2 bulk `sort`) asserted explicitly by ID; each: `ContractViolation`, zero
   requests (deny-network transport). Also: invalid `max_rate_limit_retries` (`-1`, `True`, `1.0`, `"2"`) refused
   with zero requests. Positive side, each compared direct against facade for equal requests and outcomes: every
   declared `bool` option with both `True` and `False`, every declared `str` option with a nonempty value and with
   `""` (for S2 bulk `sort=""` this pins the module's default-sort fallback, `semantic_scholar.py:77-79`);
   `max_rate_limit_retries` 0 and 2. Exact-type edges: a `str` subclass instance is refused for a `str` option. Enumerated values: a synthetic connector (or monkeypatched
   descriptor) declaring an option with `values=("a", "b")` accepts `"a"` and refuses `"c"` with zero requests.
   The ledger row `option_types` becomes fixed by B3a (D179) with the new file:line; keep the existing test that
   checks ledger rows against test tables working (adjust it to the new owner text if needed).
8. **B3b is not folded in.** B3b (design row around line 530) extracts provider rendering and validation out of the
   named-provider branches in `query_rules.py:33-73` and `:191-202` and `query_compiler.py:69-155` behind per-connector delegation,
   with compiler byte equality for every strategy (`compile_queries` with `_fit` and `compact_openalex_v1`, and
   `compile_block_queries`). That is a refactor of the discovery hot path with its own equivalence evidence, larger
   than B3a. B3a does not touch `query_rules.py`, `query_compiler.py` or `facade.render_query`. gpt-6.1-sol medium
   agreed in plan review round 1 ("agree": separate deliverable and compiler-equivalence gate); D179 records it.

## Files

- Allowed: `backend/deixis/providers/facade.py` (decisions 1 and 3; module docstring may say B3a validates option
  types); new `tests/test_connector_facade.py`; `tests/test_connector_contract.py` (decision 7, and an optional
  default-preserving parameter in `replay_case` for decision 5); `tests/connector_baseline.py` (decision 3 only);
  `docs/product/connector-onboarding.md` (ledger rows `option_types` and `g`; the version-rule amendment of decision
  2; the sentence "The only intentional direct/facade exception difference is an unknown S2 endpoint" is restricted to
  the 111 frozen cases, and a new sentence lists the facade's pre-send refusals separately: invalid limit, query and
  cursor types, unknown endpoint, undeclared option, and from B3a option value types/values and invalid
  `max_rate_limit_retries`; the intro paragraph may say B3a is done); `docs/decisions.md` (D179 at the top only); `STATUS.md` (one line under
  "Şu an çalışanlar").
- Forbidden: `providers/contract.py`, `providers/registry.py`, every provider module, `providers/common.py`,
  `providers/query_rules.py`, `providers/query_compiler.py`, `providers/lookup.py`, `providers/pacing.py`,
  `workflow/*`, `api/*`, `storage/*` and migrations (none expected), `documents/*`, `models/*`, `domain/*`,
  `contracts/research/*`, `methods/*`, `apps/web/*`, `scripts/*`, `tests/fixtures/connectors/baseline.json`,
  conformance fixtures, and other existing tests. Parallel worktrees: P8 B3 (`../DEIXIS-p8b3`, `apps/web`, maybe
  `workflow/views.py`), re-extraction R2a (`../DEIXIS-reextract-r2a`, `store.py`, `api/app.py`, `documents/*`). If
  B3a seems to need a forbidden file, stop and report.

## Evidence that the tests bite

On a temporary copy of `18be383` (not this tree) with only the new and changed test files copied in (no `facade.py`
change; if `search_request` is missing there, copy only that function so tests collect), run
`test_option_value_types_refused_before_send` and the `max_rate_limit_retries` cases: each must fail because a
request was sent or no `ContractViolation` was raised. Report that the equivalence and agreement tests pass on old
code as well, because they characterize unchanged behavior; that is expected, not a gap. Then, each on a temporary
copy of the B3a tree: (a) removing the value-type check fails the option tests; (b) dropping
`max_rate_limit_retries` from `search_request`'s field mapping fails the dispatcher-shape test; (c) a facade that
forwards a fixed `max_rate_limit_retries=2` when the request omits it fails decision 6a for a provider whose default
differs if one exists, otherwise state that no registered default differs and mutate instead by forwarding `0`;
(d) setting SerpApi's registry `retry` timeout override to 30.0 fails decision 6c; (e) a synthetic connector whose
`sw_options` include a key its named endpoint does not declare fails decision 4 by name; (f) removing the
enumerated-values membership check fails the synthetic `values` case; (g) replacing `type(value) is str` with
`isinstance(value, str)` fails the `str`-subclass case. Leave the tree clean.

## Run and records

- Focused: `tests/test_connector_facade.py`, `tests/test_connector_contract.py`, `tests/test_connector_boundary.py`,
  `tests/test_providers.py`, `tests/test_provider_records.py`, `tests/test_search_paging.py`,
  `tests/test_search_parallelism.py`, `tests/test_p7_round2.py`, `tests/test_p7_error_classification.py`. Then the
  full default suite; your sandbox cannot bind sockets or list processes, so report failure names and compare them with
  the sandbox-only names recorded for D173 (`/tmp/p7g-round3-full.log`, if present); the reviewer runs the full suite
  outside the sandbox. Run `git diff --check`.
- Write D179 at the top of `docs/decisions.md` (`## D179 — P7 G1 B3a: ...`; Status with writer gpt-6.1-sol high and
  reviewer pending; Date 2026-10-03; Context; Decision; Evidence; Limits). Decision lists the one named behavior change
  separately from the equivalence evidence, decision 2's revision interpretation, and the B3b disposition with who
  agreed. Evidence gives case counts per test group and per provider/endpoint. Limits: synthetic fixtures establish
  application behavior on the enumerated cases, not provider truth or availability; no live call; dispatch still uses
  the registry callables; `RetryPolicy` remains descriptive; B4's named changes and `PENDING_B4` cases remain; ledger
  `d` (`ValueError` conversions) stays unscheduled; G1 stays open. One Turkish line in `STATUS.md`.
- Report to `/tmp/g1b3a-impl-report.md`: files changed, each decision's implementation with file:line, test counts per
  group, the baseline byte comparison, exact commands with counts and times, the bite evidence, anything you could
  not do or measure. Do not invent.
