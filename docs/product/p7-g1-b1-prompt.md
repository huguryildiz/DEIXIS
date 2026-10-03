<!-- PLAN-REVIEW-ROUNDS: r1 (gpt-6.1-sol medium): düzeltmeyle hazır, 1 high + 6 medium + 1 low, all folded in; r2 (gpt-6.1-sol medium): düzeltmeyle hazır, 4 medium + 1 low; r3 (gpt-6.1-sol medium): düzeltmeyle hazır, the same 4 medium + 1 low because the r2 edit had not been applied; applied after r3; r4 (gpt-6.1-sol medium): hazır, no new findings. Code: written by gpt-6.1-sol high; reviewed by Claude Opus 5.5, r1 düzeltmeyle hazır (2 medium + 4 low), r2 hazır -->

# Task: P7 G1 batch B1, freeze the scholarly connector boundary

Worktree: `/Users/huguryildiz/Documents/GitHub/DEIXIS-g1-b1`, detached at `1fb1743` (origin/main with D173 and D181).
Design: `docs/product/p7-connector-contract-design.md` (accepted as D174). Read all of it; sections 4, 4.1, 6.1, 6.2, 8,
8.1, 9, 10 (row B1) and 13 bind this batch. Also read `AGENTS.md`, `CLAUDE.md`, D174 and D173 in `docs/decisions.md`,
and `docs/product/p7-coverage-verification.md`. Venv: `PYTHONPATH=backend:. UV_CACHE_DIR=/tmp/deixis-uv-cache
.venv/bin/python -m pytest ...` (`.venv` is a symlink to the arm64 venv of the main checkout).

**No git state-changing commands** (no add, commit, stash, checkout, reset, branch, worktree). Leave every change
uncommitted. No real-model call, no provider call, no network, no DNS. Do not touch `../DEIXIS*` worktrees, `TODO.md`,
`.vscode/`, `scripts/local_index.py`, the live service on port 8765, or the live data directory.

Batch B1 only. B2 (the conformance suite and the dispatched missing-key fix in `flow.py`), B3a, B3b, B4 and B5 are
later batches; do not start them. The decision number is **D177** (one entry).

## Why

P7's exit condition and `docs/product/README.md:13` promise a connector contract. D174 accepted the design: an
internal, versioned interface for reviewed adapters with a registry-driven conformance suite; external plugins are not
offered. Today there is no contract type, no descriptor, no facade and no frozen record of what each connector sends and
returns. B1 creates the boundary and freezes the current behavior as a baseline, so B3a (search facades), B3b (query
rendering) and B4 (dispatch) can prove equivalence against fixed evidence instead of against a moving target. **B1
changes no runtime behavior**: no caller in `workflow/`, `api/` or `documents/` dispatches through the new code yet.

## What is and is not in code (checked on 1fb1743)

- `providers/registry.py:32-71`: `Connector` (frozen dataclass) with `search: Callable[..., Awaitable[SearchOutcome]]`,
  key fields, `searchable`, `sw_searchable`, `supplementary`, `paging`, `max_reachable`, `page_gap`, `sw_options`,
  `host`, `sw_query`, `endpoints: dict[str, Endpoint]`, `requests_per_search`; `api_key()` reads `os.environ` at call
  time; `access_mode()` returns `api_key` / `keyless` / `not_configured`. `Endpoint` (`:24-30`) has `paging`,
  `max_results`, `max_reachable`. `CONNECTORS` (`:78-105`) holds ten connectors in display order. `reading(query)`
  (`:140-151`) gives the endpoint view; `endpoint_options(query)` (`:154-156`) gives `endpoint`/`sort`.
- No `providers/contract.py`, no `ScholarlyConnector` protocol, no contract ID, no descriptor type, no facade, no
  `tests/fixtures/connectors/`, no onboarding note (`grep -rn "scholarly_connector\|ScholarlyConnector" backend tests
  docs --exclude=p7-g1-b1-prompt.md` finds only the design doc and D174).
- `providers/common.py:71-85` `SearchOutcome` (string `status`, `delivery_class`, `error_kind` since D173);
  `common.py:3-4` docstring lists eight statuses and omits the implemented `not_configured`. `send` (`:138-211`) owns
  the bounded 429 retry and calls `domain/limits.py::limit_kind` (returns `quota_exhausted`, `rate_limited` or None).
- Search function signatures: every module has `search(client, query, limit, api_key=None, contact_email=None,
  cursor=None, max_rate_limit_retries=...)` except OpenAlex `search_works(client, query, per_page, api_key=None,
  contact_email=None, works_filter=None, cursor=None, reference_count=False, references=False, ...)` (positional
  argument 6 is `works_filter`, not `cursor`) and Semantic Scholar `search(..., endpoint=None, sort=None)`, which raises
  `ValueError` on an unknown endpoint and delegates `endpoint="bulk"` to `search_bulk`, which raises `ValueError` on a
  reused `CUT`. `common.page_offset` raises `ValueError` on a bad offset. IEEE Xplore, Scopus, CORE and SerpApi return
  `not_configured/before_send` without a key (D172; `ieee_xplore.py:66`, `scopus.py:84`, `core.py:72`, `serpapi.py:60`).
  SerpApi ignores `cursor` (`serpapi.py:62-64`). bioRxiv delegates to OpenAlex with a source filter.
- Three call shapes exist today, none to change in B1: legacy unpaged `flow.py:2045` with `page=None` (positional
  `query_text, limit, api_key, contact_email`, no keyword arguments); sw page `flow.py:2045-2048` (`cursor` (always
  passed, possibly None), `max_rate_limit_retries`, `**connector.sw_options`, `**endpoint_options(query)`); kill-search
  `flow.py:4658-4659` (`**endpoint_options(query)`, no cursor).
- PubMed loses G8's classification on an EFetch failure: `pubmed.py:170-177` copies status, delivery class, HTTP
  status, rate-limit headers and error from the EFetch outcome but not `error_kind`, so an ESearch success followed by
  an EFetch daily-quota refusal returns `rate_limited` with `error_kind=None`, and `flow.py:2049-2050` does not
  suppress further PubMed searches in that run (found in plan review; a D173 gap). B1 freezes this behavior as it is and
  lists it in the ledger; it does not fix it.
- Lookup helpers exist outside the search functions: `lookup.py::crossref_work` (`:118`), `semantic_scholar_batch`
  (`:68`, positional `zip` at `:95`, a known identity-binding defect owned by B4), `scopus_abstract` (`:152`);
  `openalex.works_by_ids` (`:186`) and `citing_works` (`:169`). None is reached through a connector object.
- Query rules: `query_rules.NAMES` (`:13`), `query_rules.query_issues(provider_id, text, endpoint)` (`:191`);
  `query_compiler._fit_blocks(provider, groups, endpoint)` (`:137`) returns `(text, dropped_terms)` or None.
- Admission surfaces with closed provider lists: `contracts/research/common.schema.json:36-39` (`provider_id` enum, the
  same ten IDs); `record_lookups` CHECK (`0048_record_lookups_scopus.sql:5`: `semantic_scholar`, `crossref`,
  `scopus`); PDF provider CHECK (`0055_europepmc_pdf_provider.sql:8`); `search_runs.status` CHECK
  (`0001_initial.sql:204`, no `not_configured`).
- Test seams: `tests/test_providers.py:101-110` `no_waits` (patches `common.asyncio.sleep`,
  `SEMANTIC_SCHOLAR_PACER.interval_seconds`, `arxiv.MIN_INTERVAL_SECONDS`); `tests/conftest.py` `memory_keychain`
  (autouse in-memory keyring). Provider key variables are **not** cleared by conftest; tests must set or delete every
  key variable they depend on.

## Decisions taken where the design is open (use these; never ask)

1. **Files.** New `backend/deixis/providers/contract.py` (types, vocabularies, protocol; it may import the shared
   type `SearchOutcome` from `common` and, under `TYPE_CHECKING` only, `LookupAnswer` from `lookup` (importing
   `lookup` at runtime would import concrete adapters); it imports no concrete adapter module and not `registry`) and new `backend/deixis/providers/facade.py` (the compatibility facade over `Connector`, descriptor
   derivation). Registry metadata stays in `registry.py` (design section 8: registration is a reviewed source change
   there).
2. **Contract ID** `CONTRACT_ID = "deixis.scholarly_connector.v1"`. **Closed vocabularies** as module constants
   (`frozenset`s, plus `Literal` aliases for typing):
   - `SEARCH_STATUSES`: `completed`, `zero_results`, `not_configured`, `auth_required`, `entitlement_missing`,
     `rate_limited`, `timeout`, `parse_error`, `failed`. `partial` (in the `search_runs` CHECK) is an aggregate
     condition, not an adapter status, and is not in this set. Flow-produced outcomes (`transport_budget`, the
     quota-suppression outcome) are not adapter outcomes; list them in the ledger.
   - `DELIVERY_CLASSES`: `before_send`, `rejected_not_executed`, `after_send_unknown` (and None for success).
   - `ERROR_KINDS`: `quota_exhausted`, `rate_limited` (and None), exactly what `limit_kind` and `send` produce. G8's
     classification is consumed, never re-derived: no regex or classifier in the new modules.
   - `PAGING_MODES`: `cursor`, `offset`, `single_page`. `TOTAL_SEMANTICS`: `reported`, `estimated`, `unknown`.
   - `LOOKUP_STATUSES`: `found`, `not_found`, `failed`, `unsupported`. `CAPABILITIES`: `search`, `doi_lookup`,
     `id_lookup`, `citing_works`.
3. **Types** (frozen dataclasses in `contract.py`; no credential value in any `repr`):
   - `EndpointDescriptor(endpoint_id: str | None, paging, max_results, max_reachable: int | None, page_gap: float,
     total, options: tuple[OptionDescriptor, ...], retry: RetryPolicy)`.
   - `OptionDescriptor(name, value_type: str ("bool" | "str"), values: tuple | None)`: `values=None` means the module
     accepts any value of that type and the facade does not restrict it (S2 bulk `sort` is free text in code; OpenAlex
     `reference_count`/`references` are `bool`). Declaring an option never tightens what a current caller sends.
   - `RetryPolicy(rate_limit_statuses: tuple[int, ...], unstated_wait: float, max_retry_wait: float,
     max_rate_limit_retries: int, min_interval: float, shared_gate: str | None)`: a **description** of what each
     module passes to `send` today (arXiv: statuses 429/406, unstated 15 s, maximum 30 s, 3 s spacing; S2: unstated
     15 s, the shared 2 s `SEMANTIC_SCHOLAR_PACER` gate covering search and batch lookup; the others `send`'s defaults;
     SerpApi timeout 60 s if you add a `timeout` field, which you should). It is not read by `send` in B1; a test
     checks each value against the module constants, and the wait-trace baseline cases below check it in behavior. `endpoint_id=None` is the connector's default endpoint, exactly as stored
     queries name it (`reading()` treats a missing endpoint the same way). `options` are the keyword names a request
     may pass for that endpoint, besides the base fields below.
   - `ConnectorDescriptor(provider_id, display_name, order, contract_id, adapter_revision: int, key_env, key_required,
     searchable, sw_searchable, supplementary, host, lineage: str | None, requests_per_search, capabilities:
     frozenset[str], query_rules_revision: str, endpoints: tuple[EndpointDescriptor, ...])`; default endpoint first.
     No key value, file path, executable name, `Store`, model adapter or callable.
   - `ConnectorContext(http: httpx.AsyncClient, api_key: str | None (repr=False), contact_email: str | None)`. The
     context is never serialized: `repr=False` hides the key from `repr` only, `dataclasses.asdict` would still hold
     it, so no code or fixture calls `asdict` on a context, and the context is not a field of any descriptor, request,
     access state or outcome.
   - `AccessState(provider_id, access_mode, key_required)`; its docstring says a configured key is not verified
     access, entitlement or quota (design 6.1).
   - `SearchRequest(query_text: str, limit: int, endpoint: str | None = None, cursor: str | None = None,
     max_rate_limit_retries: int | None = None, options: Mapping[str, Any] = empty)`; `options` stored read-only.
   - `QueryRendering(native_query: str, retained: tuple[str, ...], dropped: tuple[str, ...], rule_revision: str)`.
   - `SUPPORTED_CONTRACTS = frozenset({CONTRACT_ID})`. Version rules (in the module docstring and the onboarding note):
     the contract ID changes only when the shared boundary's shape changes (a protocol method, a type's required field
     or a vocabulary value); an adapter's `adapter_revision` changes when its request, mapping, cursor, retry/wait or
     capability semantics change; a stored query that names no endpoint keeps meaning the historical default endpoint;
     a descriptor whose `contract_id` is not supported, or an operation recorded under an adapter revision the code no
     longer has, is refused visibly (a `ContractViolation`), never restarted at page one or sent to another provider.
     B1 records no revision on any operation (B4 does), so the last rule is stated and statically checked, not yet
     exercised by dispatch.
   - `LookupRequest(doi: str | None = None, provider_record_id: str | None = None)` (exactly one set, else
     `ContractViolation`); `LookupOutcome(status, operation: str, answer: LookupAnswer | None = None, outcome:
     SearchOutcome | None = None)`.
   - `class ContractViolation(ValueError)`: a request the contract refuses before any send. Subclassing `ValueError`
     keeps the design's rule that current `ValueError` paths stay raising (sections 4.1 and 6.2).
   - `ScholarlyConnector` (`typing.Protocol`, `runtime_checkable`): `descriptor`; `access(context) -> AccessState`;
     `query_issues(text, endpoint=None) -> list[str]`; `render_query(groups, endpoint=None) -> QueryRendering | None`;
     `async search(request, context) -> SearchOutcome`; `async lookup(request, context) -> LookupOutcome`.
4. **Registry metadata** (`registry.py`, new fields with defaults; every existing field value and every existing
   function stays byte-for-byte the same in behavior):
   - `Connector.adapter_revision: int = 1`; `Connector.lineage: str | None = None` (bioRxiv: `"openalex"`, the API that
     serves its records; D13/D89); `Connector.total: str = "reported"` for the default endpoint;
     `Endpoint.total: str = "reported"`, `Endpoint.options: tuple[str, ...] = ()`, `Endpoint.page_gap: float | None =
     None` (None inherits the connector's).
   - Values: Semantic Scholar bulk `Endpoint(..., total="estimated", options=("sort",))`; SerpApi
     `total="estimated"` (Google Scholar's "about N results"). Check every other connector's `provider_total` source in
     code and use `unknown` wherever the code sets none; report the value chosen per connector with file:line.
   - The default endpoint's `options` are `tuple(connector.sw_options)` (OpenAlex: `reference_count`, `references`;
     every other connector: none). Do not add a registry field for that.
   - Display names come from `query_rules.NAMES` (read, not moved). `QUERY_RULES_REVISION =
     "deixis.query_rules.r1"` in `contract.py`, one value shared by all connectors in B1; the rendering baseline below
     is what pins it.
   - Capabilities in B1 are what the facade performs now: `frozenset({"search"})` for all ten. The existing lookup and
     chaining helpers are **not** bound in B1 (B4 binds them). `facade.UNBOUND_HELPERS` maps provider ID to the dotted
     names of those helpers (`crossref` → `lookup.crossref_work`; `semantic_scholar` → `lookup.semantic_scholar_batch`;
     `scopus` → `lookup.scopus_abstract`; `openalex` → `openalex.works_by_ids`, `openalex.citing_works`), so the
     ledger and B4 know what exists without any capability being overstated.
5. **Facade** (`facade.py`): `CompatibilityConnector(connector: Connector, descriptor: ConnectorDescriptor | None =
   None)` implements `ScholarlyConnector`; a given descriptor must name the same provider, a supported contract and
   the wrapped connector's `adapter_revision`, else `ContractViolation` with no request. Checks of revisions stored on
   operations belong to B4.
   `descriptor_for(connector, order) -> ConnectorDescriptor` and `connectors() -> dict[str, CompatibilityConnector]`
   derive from `CONNECTORS` at call time (no import-time construction that reads environment, keyring or network; a
   test that monkeypatches `CONNECTORS` sees its change). `context_for(connector, http, contact_email)` resolves the key
   with `connector.api_key()` at call time.
   - `access(context)`: `api_key` if `context.api_key`, else `not_configured` if key-required, else `keyless`; no
     request, no keyring or environment write. Equals `Connector.access_mode()` when the context comes from
     `context_for`.
   - `search(request, context)`: validate first, then forward **only what the request sets**:
     `connector.search(context.http, request.query_text, request.limit, context.api_key, context.contact_email,
     **kwargs)` with `cursor` only when not None, `max_rate_limit_retries` only when not None, `endpoint` only when not
     None, then `request.options`. It never adds `sw_options`, a sort, a cursor or a retry count on its own (design
     section 9). Validation raises `ContractViolation` before any send for: `limit` not a positive `int` (a `bool` is
     refused); `query_text` not a `str`; `cursor` not None/`str`; an `endpoint` not declared by the descriptor; an option
     name not in that endpoint's `options`. Everything else passes through, so the module's own `ValueError` paths
     (bad offset, reused `CUT`) still raise from the module. No not-configured guard is added in the facade: the four
     key-required modules already return `not_configured/before_send` (D172); B2 adds the generic guard with the
     conformance suite. Record this split in D177.
   - `lookup(request, context)`: validates the request, returns `LookupOutcome("unsupported", operation=...)` for every
     connector in B1, with zero requests and no `SearchOutcome`. `unsupported` is never a failed search, never
     `zero_results`, and is never written anywhere (`record_lookups` CHECK allows only `found`/`not_found`/`failed`).
   - `query_issues(text, endpoint)`: `query_rules.query_issues(provider_id, text, endpoint)`.
   - `render_query(groups, endpoint)`: `query_compiler._fit_blocks(provider_id, [list(g) for g in groups], endpoint)`;
     None stays None; otherwise `QueryRendering(text, retained, dropped, QUERY_RULES_REVISION)` where `retained` is
     exactly the occurrences the compiler kept: the leading terms of each block, block by block, as `_fit_blocks` and
     `_rendered` count them (`query_compiler.py:126-154`); never by value matching or multiplicity subtraction.
     Regressions: `[['alpha','alpha'],['beta']]` and `[['alpha','beta','gamma','delta','epsilon','zeta','alpha'],
     ['eta']]` (the leading `alpha` is kept, in its position). If `_fit_blocks` does not expose the kept counts,
     recompute them with the same rule the compiler uses and assert equality with its text; do not edit the compiler.
     The compiler keeps calling its own functions (B3b moves it).
   - `facade.py` imports `registry`, `query_rules`, `query_compiler` and `contract` only; `UNBOUND_HELPERS` holds dotted
     name strings, resolved by the test, not imported by the facade.
   - Equivalence is of HTTP requests, waits and outcomes, not of Python keyword presence: the facade omits a None
     `cursor` where the sw shape passes `cursor=None` explicitly; both send the same request.
6. **Baseline fixtures** (the B1 freeze). New `tests/fixtures/connectors/`:
   - `responses/`: hand-written SYNTHETIC native bodies per connector and endpoint (JSON; Atom XML for arXiv; ESearch
     JSON plus EFetch XML for PubMed), titles marked SYNTHETIC, no real key. Reuse shapes from `tests/test_providers.py`
     where they exist. Each paged endpoint has a first page that yields a next cursor and a second page.
   - `baseline.json`: generated by a helper module `tests/connector_baseline.py` (`capture()` builds every case;
     `python tests/connector_baseline.py --write` rewrites the file; the test only reads). Top level: `contract_id`,
     `query_rules_revision`, `base_commit` (`1fb1743`), `cases`, `rendering`, `query_issues`.
   - Search cases, for every `(provider_id, endpoint_id)` the descriptors declare (ten defaults plus S2 `bulk`): shape
     `unpaged` (the legacy call: positional only; for S2 bulk use shape `kill_search` instead: `endpoint` and `sort`, no
     cursor); `first_page` (sw shape: `cursor=FIRST_PAGE`, `max_rate_limit_retries=2`, the connector's `sw_options`,
     the endpoint options; for S2 bulk `sort=BULK_SORT`; `cursor=None` is never passed here); `next_page` (the cursor the first page returned; SerpApi
     records that it ignores the cursor); `malformed_200` (HTTP 200 with a body the parser cannot read); for
     optional-key connectors an extra `unpaged_keyless`; for the four key-required connectors `missing_key` (zero
     requests). Each case records `adapter_revision`, the request sequence (method, URL without query, params as a
     sorted list of pairs, header names with values, JSON body; every occurrence of the synthetic key replaced by
     `<key>`), and either `outcome` (status, delivery_class, access_mode, http_status, provider_total, next_cursor,
     retries, error_kind, error, request_description, rate_limit, `records` as `dataclasses.asdict` without `raw` plus
     `raw_sha256`, `payload_sha256 = canonical.sha256_hex(raw_payload)` or None) or `raised` (exception type and
     message). Use a fixed synthetic key that is asserted absent from every recorded description, error and payload.
     Waits are recorded, not just zeroed: `asyncio.sleep` in `common`, `arxiv` and `pacing` is replaced by a fake that
     appends the requested seconds to a trace and advances a fake `time.monotonic` used by `arxiv` and `pacing`; the
     arXiv `_last_request` and the S2 pacer's `_last_finished` are reset before every replay (direct and facade) and
     restored afterwards, so a replay does not depend on test order. Each case stores its `waits` trace. The transport
     is an `httpx.MockTransport` that fails the test on any request the case does not script.
   - Limit sequences (selected integrated-G8 cases, not the B2 matrix): for every `(provider_id, endpoint_id)`:
     `retry_then_success` (one 429 without Retry-After, then the success page, `max_rate_limit_retries=2`; arXiv
     uses 406), `quota_exhausted` (429 with a body carrying `insufficient_quota`/daily wording, no retry), plus the
     provider-specific cases D173 named: IEEE 403 `Over Queries Per Second` (retried) and per-day 403 (not retried),
     SerpApi exhausted-search body, OpenAlex `x-ratelimit-remaining-usd: 0`, and PubMed ESearch success followed by an
     EFetch daily-quota refusal (frozen as today: `error_kind` None).
   - Spacing sequences: within one replay starting at fake `time.monotonic() = 1000.0` with pacing state reset, two
     consecutive successful arXiv searches (the trace shows the 3 s spacing) and, for Semantic Scholar, a relevance
     search, a bulk search and a second relevance search (the trace shows the shared 2 s gate across endpoints).
     Direct and facade replays each run the whole sequence and must produce the same trace.
   - Exception cases: offset providers with cursor `"-1"` and `"x"` (`common.page_offset`, `common.py:88-98`), S2
     bulk with cursor `CUT` (`semantic_scholar.py:121-122`), S2 with endpoint `"nope"` called directly; each records
     the exception type and message and zero requests, for the direct call and for the facade (the facade raises
     `ContractViolation` for the unknown endpoint before the module does; record both and say so; for the other paths
     the facade lets the module's own `ValueError` through with the same message).
   - `rendering`: for every `(provider_id, endpoint_id)`, `_fit_blocks` output on three fixed block sets (fits whole;
     must drop terms; cannot fit, None). `query_issues`: for every pair, the issues for four fixed texts (plain, boolean,
     unbalanced, over-long).
7. **Onboarding note and ledger.** New `docs/product/connector-onboarding.md` (English, short): what the contract is
   (internal, reviewed adapters in the codebase; packaged builds cannot add sources; no runtime import path, URL or API
   request can register code: D174 Q1/Q2), the five onboarding gates of design section 8 made concrete for this code
   (which files and closed lists a new connector touches, with file:line), version rules (`CONTRACT_ID`; bump
   `adapter_revision` when request, mapping, cursor or capability semantics change; bump `QUERY_RULES_REVISION` when
   rendering or rule output changes; a baseline regeneration without a revision bump is a review failure), the
   unsupported rule, the regeneration command, and a **conformance mismatch ledger** listing every known mismatch
   between current code and the contract with the owning batch: at least (a) dispatched missing key counted before
   the call and `not_configured` not allowed by `search_runs.status` (B2); (b) S2 batch answers bound by position (B4);
   (c) quota and temporary rate limit share the pause reason `provider_rate_limited` and the step error lacks
   `error_kind` although `search_runs.error_json` has it (B4); (d) existing `ValueError` paths (kept; converting them
   is a named behavior change, unscheduled); (e) `_send_search` counts one base request per search while PubMed may
   send two, and zero results send one (Q4 debt); (f) flow-level outcomes outside the adapter vocabulary
   (`transport_budget`, quota suppression); (g) retry policy is described by `RetryPolicy` but still set inside each
   module's `send` call (not driven by the descriptor); (j) PubMed drops `error_kind` on an EFetch failure
   (`pubmed.py:170-177`), so a quota exhausted at EFetch does not stop later PubMed searches in the run: a one-line
   named fix with a regression, owner **B2** (it composes with D173's guard; B1 freezes the current behavior); (h) new providers need the schema enum and, for lookup or PDF
   persistence, a new migration; unknown sources route as `no_route` (`workflow/routing.py:88`); (i) whatever the
   `malformed_200` cases reveal (any case that raises instead of returning `parse_error` is a mismatch, named, not
   fixed in B1). Each item cites file:line on `1fb1743`.
8. **`common.py` docstring only**: add `not_configured` to the status list (`common.py:3-4`). No other `common.py`
   change.

## Files

- Allowed: new `backend/deixis/providers/contract.py`, new `backend/deixis/providers/facade.py`,
  `backend/deixis/providers/registry.py` (decision 4 only), `backend/deixis/providers/common.py` (decision 8 only), new
  `tests/test_connector_boundary.py`, new `tests/connector_baseline.py`, new `tests/fixtures/connectors/**`, new
  `docs/product/connector-onboarding.md`, `docs/decisions.md` (D177 at the top only), `STATUS.md` (one line).
- Forbidden: every provider module other than `registry.py`/`common.py` (no behavior or format change), `workflow/*`
  (including `flow.py`: the dispatched guard is B2), `api/*`, `storage/*` and migrations, `documents/*`, `models/*`,
  `domain/*`, `contracts/research/*`, `methods/*`, `apps/web/*`, `scripts/*`, existing tests and fixtures. P8 B2,
  re-extraction R1 and RR-B run in parallel worktrees on `flow.py`, `rules.py`, `prompt.py`, `api/app.py`,
  `workflow/review/*`, `store.py`, `documents/*`, `workflow/views.py`, `scripts/p9/*`, `tests/process/*`. If B1 seems
  to need a forbidden file, stop and say so in the report instead.

## Tests (`tests/test_connector_boundary.py`)

1. Vocabulary and types: the sets in decision 2; frozen dataclasses; `ContractViolation` is a `ValueError`; every
   facade passes `isinstance(f, ScholarlyConnector)`; every descriptor's `contract_id` is in `SUPPORTED_CONTRACTS`;
   endpoint IDs are unique per connector; a supplied descriptor with an unsupported `contract_id`, another provider ID
   or another `adapter_revision` is refused by the facade constructor with `ContractViolation` and zero requests.
2. Descriptors: one per `CONNECTORS` entry, same order; `provider_id` set equals the `common.schema.json` enum exactly;
   display names from `query_rules.NAMES`; `contract_id`, `query_rules_revision`, closed values; default endpoint first;
   each endpoint's paging, `max_results`, `max_reachable` equal `reading({"provider_id": p, "endpoint": e})`; a
   frozen `descriptors` table in `baseline.json` (every descriptor field except callables) equals the derived
   descriptors, so a registry or derivation change fails here until the fixture and the revision are updated;
   `RetryPolicy` values equal the module constants; bioRxiv
   lineage `openalex` and its host equals OpenAlex's; capabilities `{"search"}`; `UNBOUND_HELPERS` names resolve to
   real attributes.
3. Purity: a cold import in a subprocess (`python -c` with `PYTHONPATH`, a `sitecustomize`-free environment and a
   socket guard installed before import) of `deixis.providers.contract` and `deixis.providers.facade`, building every
   descriptor and facade and calling `access` and `lookup`, opens no socket and exits 0. In process, with a fail-closed
   `MockTransport`, `socket.socket.connect` and `socket.getaddrinfo` patched to fail, the in-memory keyring snapshotted
   and `os.environ` snapshotted, the same calls send nothing and change neither. A synthetic key set in the environment
   appears in no `repr` or `asdict` of a descriptor or access state, and in no `repr` of a context.
4. Access: `access(context_for(...))` equals `Connector.access_mode()` for every connector with its key set and unset.
5. Validation: `limit` 0, -1, `True`, `"5"`; unknown endpoint (`"bulk"` on OpenAlex, `"nope"` on S2); option `sort`
   on S2's default endpoint; option `references` on bioRxiv; non-string cursor; `LookupRequest` with both or neither
   field. Each raises `ContractViolation` with zero requests.
6. Lookup: every facade returns `unsupported`, zero requests, no `SearchOutcome`.
7. Baseline equivalence: for every case in `baseline.json`, the direct module call in that case's shape (as
   `flow.py` issues it) **and** the facade (via `SearchRequest`) each reproduce the recorded requests and outcome
   exactly. Coverage: the set of `(provider_id, endpoint_id)` in the baseline equals the descriptors' set, and every
   required shape is present for each pair; the coverage function reports the missing pair when a synthetic connector
   is monkeypatched into `CONNECTORS` without fixtures (no new branch is needed for it). Every recorded status,
   delivery class and error kind is in the closed vocabularies; the synthetic key appears nowhere in the baseline file.
8. Rendering: `render_query` and `query_issues` equal the baseline for every pair and fixed input; `retained` +
   `dropped` is a multiset partition of the input terms; the duplicate-term case of decision 5 is a named regression.
9. Static scan: an `ast` pass over `backend/deixis/providers/*.py` finds every string literal that reaches a
   status, delivery class or error kind: `SearchOutcome(...)` positional and keyword arguments, `.status =` /
   `.delivery_class =` assignments including tuple targets (`serpapi.py:84`), both branches of conditional
   expressions (`common.send`'s `status = "entitlement_missing" if ... else "auth_required"`, `delivery = ...`), and
   `error_kind=` keywords; all are in the closed vocabularies (lookup's `LookupAnswer` statuses are checked against
   `LOOKUP_STATUSES` minus `unsupported`). A non-literal value the scan cannot resolve fails the scan with its
   location unless it is listed in an explicit allowlist in the test with a reason. Unit fixtures for the scanner
   cover each of these syntactic forms.

**Evidence that the tests bite.** B1 changes no behavior, so the baseline half of test 7 passes on old code by design;
say so. The missing-module import failure on old code is an existence check, not behavior evidence; report it as such.
Show instead, each on a temporary copy: (a) one param of one case changed in `baseline.json` fails test 7 for that
case; (b) one recorded wait changed fails it; (c) one `Endpoint.max_results` changed in `registry.py` fails test 2
through the frozen `descriptors` table (not through `reading()`, which moves with it); (d) a `retained` computation by
value membership fails the duplicate-term regression of test 8; (e) a `.status = "partial"` line added to a scratch
provider module fails test 9. Leave the tree clean.

## Run and records

- Focused: the new file plus `tests/test_providers.py`, `tests/test_provider_roles.py`,
  `tests/test_provider_records.py`, `tests/test_settings_connections.py`, `tests/test_search_paging.py`,
  `tests/test_p7_round2.py`, `tests/test_p7_error_classification.py`. Then the full default suite; your sandbox cannot
  bind sockets or list processes, so report the failure names and compare them with the 17 known sandbox-only names
  of D173; the reviewer runs the full suite outside the sandbox. Run `git diff --check`.
- Baseline before B1 (this worktree at `1fb1743`, measured by the reviewer outside the sandbox, `.venv`):
  **8,935 passed, 2 skipped, 0 failed** in 399 s.
- Write the D177 entry at the top of `docs/decisions.md` (`## D177 — P7 G1 B1: ...`; Status with writer
  gpt-6.1-sol high and reviewer pending; Date 2026-10-03; Context; Decision; Limits) and one Turkish line in
  `STATUS.md` under "Şu an çalışanlar". Limits must say: no behavior change and no dispatch through the facade; the
  baseline is synthetic and freezes current code, not provider truth; no live call; capabilities other than search
  are unbound; G1 stays open; the ledger items and their owners.
- Report to `/tmp/g1b1-impl-report.md`: files changed, each decision's implementation with file:line, the ledger, the
  per-connector `total` values with evidence, exact commands with counts and times, the bite evidence, anything you
  could not do or measure. Do not invent.
