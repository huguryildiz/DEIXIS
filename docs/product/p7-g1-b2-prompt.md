<!-- PLAN-REVIEW-ROUNDS: r1 (gpt-6.1-sol medium): düzeltmeyle hazır, 3 high + 7 medium + 1 low, all folded in; agreed decision 1. r2: düzeltmeyle hazır, 1 high + 3 medium + 1 low, all folded in; r3: düzeltmeyle hazır, 1 medium + 1 low, folded in; r4: hazır. approved item l as B4's third named change (raw_payload and record.raw, sanitized before persistence, hash of the sanitized form). Code: written by gpt-6.1-sol high; reviewed by Claude Opus 5.5, r1 düzeltmeyle hazır (5 medium + 1 low), r2 hazır -->

# Task: P7 G1 batch B2, the conformance suite and the dispatched missing-key fix

Worktree: `/Users/huguryildiz/Documents/GitHub/DEIXIS-g1-b2`, detached at `5990b02` (origin/main with D177, B1).
Design: `docs/product/p7-connector-contract-design.md` (accepted as D174). Read all of it; sections 2.3, 4.1, 6.1,
6.2, 6.3, 7, 8.1, 9, 10 (row B2 and the paragraph after the table) and 13 bind this batch. Also read `AGENTS.md`,
`CLAUDE.md`, D177, D174, D173 and D172 in `docs/decisions.md`, `docs/product/connector-onboarding.md` (its ledger is
the list of known mismatches), and `docs/product/p7-g1-b1-prompt.md` (what B1 built). Venv:
`PYTHONPATH=backend:. UV_CACHE_DIR=/tmp/deixis-uv-cache .venv/bin/python -m pytest ...` (`.venv` is a symlink to the
arm64 venv of the main checkout).

**No git state-changing commands** (no add, commit, stash, checkout, reset, branch, worktree). Leave every change
uncommitted. No real-model call, no provider call, no network, no DNS. Do not touch `../DEIXIS*` worktrees, `TODO.md`,
`.vscode/`, `scripts/local_index.py`, the live service on port 8765, or the live data directory.

Batch B2 only. B3a (search facades), B3b (query rendering), B4 (dispatch through the facade, provenance, lookup
binding) and B5 are later batches; do not start them. Application dispatch keeps calling the registry callables; the
facade stays unused by `workflow/`. The decision number is **D178** (one entry).

## Why

B1 froze the boundary and the current behavior. D174 says G1 needs a registry-driven conformance suite, and design
sections 2.3, 6.1 and 10 give B2 one named behavior change that cannot wait for B4: a required key removed after the
protocol froze is today counted as a request and then breaks the `search_runs` CHECK. B1 also assigned B2 two named
provider defects (ledger items i and j). B2 ships the suite, those fixes plus the defects plan review found (five named
behavior changes, each with a failing-first regression), and an updated ledger, so B3a and B3b start from a passing, registry-driven gate.

## What is and is not in code (checked on 5990b02)

- Dispatch: `workflow/flow.py:2032-2063` `_send_search`. Order today: quota-run guard (`:2044-2046`, D173), then
  `self.store.add_usage(run_id, "provider_requests", query=query_key)` (`:2047`), then `connector.search(...)`
  (`:2049-2052`) with `connector.api_key()`. There is **no access check**. If a key-required connector's key is gone,
  the module guard returns `not_configured/before_send` (D172: `ieee_xplore.py:66`, `scopus.py:84`, `core.py:72`,
  `serpapi.py:60`) after one request was already counted.
- Recording: `flow.py:2065-2129` `_record_search` always calls `store.record_search(search_fields, ...)`
  (`:2109`, `:2114`), which inserts a `search_runs` row. `search_runs.status` CHECK
  (`storage/migrations/0001_initial.sql:204`) does not allow `not_configured`, so that insert raises
  `sqlite3.IntegrityError` inside `_write_query`'s transaction (`flow.py:2289-2305`). Failure path returns
  `(f"provider_{outcome.status}", detail)` (`:2118-2120`); discovery pauses with it only when no search succeeded
  (`flow.py:501-503`, D18).
- Precedent for a step without a `search_runs` row: `_skip_unsearchable` (`flow.py:2016-2030`, D87) finishes the step
  `cancelled` with `provider_not_searchable` and writes nothing to `search_runs`; the views already render such steps.
- Kill-search: `flow.py:4648-4667` `_kill_search_request` computes the reservation (`:4652-4653`), checks the budget
  (`:4656-4658`) and charges it (`:4661`) before
  `connector.search` (`:4662`), also with no access check. `_kill_search_record_query` (`:4669-4692`) writes
  `kill_search_queries` (`0060_candidates.sql:83-93`: status `succeeded`/`failed`/`outcome_unknown`, free
  `error_code`), so a `not_configured` outcome records fine there but has spent its reservation.
- Planning already excludes unconfigured key-required providers (`workflow/routing.py:46-47`,
  `workflow/candidates/run.py:69-71`, `registry._configured`), so the failure only appears when the key disappears
  after planning, e.g. after the protocol freeze.
- PubMed (ledger j): `providers/pubmed.py:170-177` copies status, delivery class, HTTP status, rate-limit headers and
  error from the EFetch outcome, not `error_kind`; an EFetch daily-quota refusal after a successful ESearch returns
  `rate_limited` with `error_kind=None`, so the D173 run guard (`flow.py:2053-2054`) does not stop later PubMed
  searches. B1 froze this as baseline case `pubmed_efetch_quota`.
- Wrong-root 200 (ledger i): `semantic_scholar.py:97-104` (relevance) and `:136-143` (bulk) call `payload.get(...)`
  and `ieee_xplore.py:82-87` calls `payload.get("articles")`; their `except` tuples omit `AttributeError`, so a JSON
  body `[]` raises `AttributeError` out of `search`. OpenAlex (`openalex.py:155`), Crossref (`crossref.py:101`), CORE
  (`core.py:92`), Scopus (`scopus.py:105`), PubMed ESearch (`pubmed.py:155`) and SerpApi (`serpapi.py:78`) have their
  own tuples; whether each of them survives every wrong-root shape below is **not known**; the suite finds out.
- B1 test assets: `tests/connector_baseline.py` (`capture()`, `--write`, `SYNTHETIC_KEY`, `response_spec`,
  `deny_network`), `tests/fixtures/connectors/baseline.json` (111 cases, `base_commit` `1fb1743`, frozen
  `descriptors`), `tests/fixtures/connectors/responses/*` (native SYNTHETIC bodies), `tests/test_connector_boundary.py`
  (`test_baseline_equivalence`, `test_baseline_coverage`, `test_new_registry_pair_requires_fixtures`, purity, static
  vocabulary scan; `:291` asserts `base_commit == "1fb1743"`). Facade: `providers/facade.py` (`connectors()`,
  `descriptor_for`, `context_for`, `CompatibilityConnector.search` forwards only what the request sets, no
  not-configured guard of its own). Existing specialized tests stay: `tests/test_providers.py` (including
  `test_key_required_search_without_a_key_sends_no_request`, `:423-438`), `test_provider_records.py`,
  `test_provider_roles.py`, `test_search_paging.py`, `test_search_parallelism.py`, `test_p7_round2.py`,
  `test_p7_error_classification.py`, `test_lookup_flow.py`, `test_settings_connections.py`.
- Full-discovery harness with a key-required provider: `tests/test_search_parallelism.py:185-240` (`setup`, `Session`,
  `run_discovery`; `FIRST_ROUND` at `:41-43` includes a `serpapi` query and `setup` sets `SERPAPI_API_KEY`). Run-level
  harness: `tests/test_p7_round2.py:88-108` (`quota_flow`, fake connectors).
- UI: `apps/web/src/labels.ts:32-71` has pause texts for `provider_rate_limited`, `provider_auth_required`, ... but
  none for `provider_not_configured`; `pauseReasonText` falls back to the raw code.

## Decisions taken where the design is open (use these; never ask)


B2 has **five named behavior changes** (decisions 2-8; change 1 spans decisions 2-4). Each is listed separately from the suite in D178 and the ledger,
each has a regression that fails on `5990b02`, and none is described as facade equivalence.

1. **CHECK disposition: no `search_runs` row, no migration.** A search the dispatcher refuses because the source's
   required configuration is unavailable is recorded as a step only, following D87's `_skip_unsearchable` precedent
   for a search that is not admissible at send time. This is not a rule for every unsent operation: other
   `before_send` outcomes (transport failures, quota suppression) keep their `search_runs` rows. Widening the CHECK
   would mean rebuilding `search_runs` (SQLite cannot alter a CHECK) under the `candidates`/`candidate_hits` foreign
   keys while parallel batches also add migrations, and would add a retrieval row for a request that never existed.
   So `0001`'s CHECK stays and B2 adds no migration. Owner-level choice, agreed by gpt-6.1-sol medium in plan review
   round 1 ("I agree with no `search_runs` row and no migration"); record that in D178.
2. **Dispatched guard (change 1).** In `_send_search`, each attempt starts with one credential snapshot:
   `key = connector.api_key()`. If `connector.key_required and not key`, return
   `SearchOutcome("not_configured", "before_send", f"{connector.provider_id} search not sent: access=not_configured",
   "not_configured")` (no records, payload, HTTP status, retries, error_kind) **before** the quota-run guard and before
   `add_usage`. Otherwise the same `key` is the one passed to `connector.search` (no second `api_key()` read in that
   attempt). Generic: no provider ID; `Connector.api_key()` already maps `""` to None. It does not enter the
   transient-retry loop and does not touch `_quota_out`. Every transient-retry attempt takes a fresh snapshot and
   repeats the check before counting.
3. **Recording `not_configured`.** In `_record_search`, any outcome with status `not_configured` (from the guard; a
   module guard can no longer see a different key in the same attempt, but the branch is kept so the CHECK can never be
   reached) takes a branch before the payload write: no payload file, no `search_runs` row, no records or candidates;
   `self.store.finish_step(step["id"], "failed", output={"status": "not_configured", "result_count": 0},
   error_code="not_configured", error={"error": outcome.request_description, "http_status": None},
   delivery_class="before_send", finished_at=finished_at)` for paged and unpaged steps alike (no page diagnostics;
   today's failure path stores `output=None`, `flow.py:2114-2117`, `store.py:1856-1857`); return
   `("provider_not_configured", {"provider": provider, "http_status": None, "error_kind": None, "retry_after": None})`.
   The step ends `failed`, so "retry failed searches" (and a resume of an all-failed round) sends it again once the key
   is back. `_stop_reason` already ends the query's read with `page_failed`.
4. **Kill-search guard (change 1, second dispatch path).** In `_kill_search_request`, each attempt takes one snapshot
   `key = connector.api_key()`; if `connector.key_required and not key`, return the same outcome **before** the
   reservation transaction; otherwise pass that `key` to `connector.search`. `_kill_search_record_query` already records
   a `failed` query with `error_code="not_configured"`; no change there. Nothing else in `flow.py` changes.
5. **PubMed EFetch `error_kind` (change 2, ledger j).** `pubmed.py:170-177`: copy `fetch_outcome.error_kind` with the
   other failure fields.
6. **Malformed 200 reads as `parse_error` (change 3, ledger i and what the suite finds).** The malformed group of the
   suite (group 5) defines the shapes. For each search parser that raises on one of them, or returns
   `completed`/`zero_results` for one, fix it inside that provider's parse code only, by these means and no other:
   (a) add the missing class (`AttributeError`; `ValueError` where an `int()`/`float()` conversion is involved) to the
   existing `except` tuple; (b) a narrow container type check: the JSON root must be an object, and the provider's
   result container, **when present**, must be a list (a dict/str/number there is `parse_error`; an absent key keeps
   today's behavior, see decision 9); each item must have the container's declared item type (an object for record
   lists; a string for PubMed ESearch's `esearchresult.idlist`, whose valid items are identifiers, `pubmed.py:150`); (c) for XML a root-element check: arXiv's root must
   be the Atom `feed`, PubMed EFetch's root must be `PubmedArticleSet` (in `records_from_xml`, `pubmed.py:120-122`,
   which is allowed for this). Nested paths matter: name the container path per provider in its conformance fixture
   (e.g. OpenAlex `results`, S2 `data`, IEEE `articles`, Crossref `message.items`, Scopus `search-results.entry`, CORE
   `results`, SerpApi `organic_results`, PubMed ESearch `esearchresult.idlist`; verify each in code). Never a bare or
   broad `except Exception`; never a change to field mapping, request bytes or paging.
7. **Empty cursor token (change 4).** `openalex.py:154` returns `meta.next_cursor` unchanged, so `""` reaches the flow
   as a cursor and `_stop_reason` (`flow.py:270`) does not stop on it. Normalize an empty or non-string cursor token to
   `None` in OpenAlex's page parser (bioRxiv inherits it through delegation). Check S2 bulk's token (`str(token) if
   token else None` already) and any other cursor path the suite exposes; same rule.
8. **Header and wait evidence (change 5).** `providers/common.py` is allowed for exactly two edits: (a) the
   allowlisted rate-limit header values copied at `common.py:180` pass through `redact(value, *secrets)`; (b)
   `_retry_wait` (`common.py:215-223`) treats a Retry-After that is negative, NaN or infinite like an unparseable one
   (returns None: no wait, no retry). Nothing else in `common.py` changes.
9. **Recorded, not fixed:**
   - **Empty object / absent container (`{}` or the container key missing).** Whether a provider omits its result
     list on a genuine empty result is provider-documentation knowledge this batch cannot check offline. The suite
     records each pair's current outcome; every pair that returns `zero_results`/`completed` is ledger item k, owner
     **unscheduled, needs provider documentation**. The case asserts the recorded outcome with a comment naming k; it
     never claims the behavior is correct.
   - **A key echoed inside a successful provider body.** Plan review reproduced that OpenAlex keeps an injected nested
     key in `raw_payload` (`openalex.py:159`); other adapters likely do the same. Removing it needs a payload
     sanitization step at persistence, which changes stored payload digests and is not one of B4's two named changes.
     Ledger item l: a **new named behavior change, owner B4 (design amendment recorded in D178: B4 gains a third
     named change, agreed with gpt-6.1-sol medium in plan review round 2; its scope is `raw_payload` and
     record `raw`, sanitized before persistence, with the payload digest computed over the sanitized form)**. B2 has
     no test asserting the leak; the case is in `PENDING_B4` with the reproduction.
   - **Identity mismatches the suite finds that are not decision-6 shaped** (group 3; e.g. identities stringified by
     `semantic_scholar.py:54` or `openalex.py:80`): these are *characterization* cases, kept apart from the
     *enforced* identity cases. Each names its ledger item, owner and expected current outcome in a
     `IDENTITY_KNOWN_MISMATCHES` table that a test checks against the ledger; D178 and the report must not claim
     identity conformance for those (provider, shape) pairs.
10. **No facade guard and no facade change.** D177's "generic and dispatched guard belongs to B2" is decision 2. The
    facade keeps forwarding; the suite checks that every key-required connector, direct **and** through its facade,
    returns `not_configured/before_send` with zero requests for `None` and `""`, so a future key-required adapter
    without its own guard fails the suite. `facade.py`, `contract.py` stay unchanged; if a case cannot be written
    without changing them, stop and report.
11. **Suite placement and shape.** New `tests/test_connector_contract.py` and per-provider fixtures
    `tests/fixtures/connectors/conformance/<provider_id>.json` (one per registered connector). Parameterize from
    `registry.CONNECTORS` and `facade.connectors()` at collection time. Cases call the registered facade
    (`facade.connectors()[pid].search(SearchRequest, context)`) and, where a case is about the module path, the
    registry callable in the shape `flow.py` uses; never a second search-function dictionary. Reuse
    `tests/connector_baseline.py` by import (`SYNTHETIC_KEY`, `deny_network`, `response_spec`). The fake clock and
    sleeper are local to `replay` today (`connector_baseline.py:138-142`): extract them into a module-level helper
    (context manager) in that file, behavior-preserving; the regenerated baseline must show that extraction changed no
    case. `httpx.MockTransport` failing on any unscripted request, plus a test-level guard patching
    `socket.socket.connect` and `socket.getaddrinfo` to fail. Fixtures are SYNTHETIC, hold no real key, and declare per
    provider: `auth` (`{"param": name}` or `{"header": name, "prefix": ...}`; `null` for providers that send no key),
    the result-container path, endpoints covered, record-mapping expectations for the positive page, identity and
    malformed bodies, case-specific expectations. Each container declares its item type (`object` or `string`).
12. **Coverage is exact.** Conformance fixture IDs equal registry IDs; every declared endpoint has every applicable
    case group; every declared capability has positive and failure cases (today only `search`; `lookup` is
    `unsupported` for all ten and gets the explicit no-request case). A synthetic connector monkeypatched into
    `CONNECTORS` without a fixture makes the coverage function report it (no xfail, no skip). A complete synthetic
    connector (tiny in-test search function plus in-test fixture dict) passes the per-connector checks with no new
    branch: checks are plain functions taking `(provider_id, endpoint_id, fixture)`.
13. **B4 cases are tracked, not run.** A module-level `PENDING_B4` mapping names each section 8.1 case that needs
    dispatch through the facade or persistence provenance (temp-store merge/version through the facade, resumed paging
    and lookup through the facade, ledger item l, failed payload write publishing no success, quota versus rate limit
    in the step error and pause reason, S2 batch reorder binding, stored adapter-revision refusal) with design section
    and owner. A test asserts every entry appears in the onboarding ledger. Cases covered by existing tests go in
    `COVERED_ELSEWHERE` as `module::function`; a test imports each and asserts it exists. Check that each named test
    really proves the case before listing it.
14. **Revisions and baseline.** Changes 2-5 reach every adapter (change 5 goes through `send`, used by all ten), so
    every connector's `adapter_revision` becomes 2 in `registry.py` (one bump covers all B2 changes and both S2
    endpoints). Regenerate `baseline.json` with the documented command. Every case's `adapter_revision` and the frozen
    descriptor table change with the bump; apart from that metadata, the only cases whose requests, waits or outcomes
    change must be the ones the fixes target (`malformed_200` of S2/IEEE and any other fixed parser,
    `pubmed_efetch_quota`, and any case whose recorded `rate_limit` contained the key or whose cursor was `""`). Set
    `base_commit` to `5990b02` (the literal at `connector_baseline.py:278` and the assertion at
    `test_connector_boundary.py:291`). Report a diff summary: case IDs whose non-metadata fields changed, with the
    field. No `QUERY_RULES_REVISION` change; rendering and query issues byte-identical.

## The suite (section 8.1 groups; every applicable case for every `(provider_id, endpoint_id)`)

Expectations are derived from the effective access mode of the case (`api_key`, `keyless`, `not_configured`), never
from a blanket rule. A key-required connector without a key returns `not_configured` and never reaches a mocked HTTP
response; keyless-only connectors (arXiv, Crossref: no `key_env`) send no key even if one is in the environment.

1. **Registration and purity.** Unique IDs in display order; contract ID supported; closed-vocabulary descriptor
   fields (import B1's checks; do not duplicate the frozen descriptor table); `common.schema.json` enum equals the
   registry; building descriptors, facades and contexts and calling `access` and `lookup` send nothing and write
   nothing (environment and in-memory keyring snapshot). Coverage tests of decision 12.
2. **Access and query.**
   (a) Key-required connectors, key unset and `""`, direct and facade: `not_configured/before_send`, access mode
   `not_configured`, zero requests, no records/payload/HTTP status, zero retries.
   (b) Auth placement for **every connector that has a `key_env`** (key-required and optional): with the synthetic key,
   the request carries it exactly where `auth` says, once, and nowhere else (URL path, other params, other headers,
   body). Optional-key connectors without a key send no key parameter or header at all. Keyless-only connectors send
   no key with the synthetic key set in every candidate environment variable.
   (c) The synthetic key never appears in the outcome's `request_description`, `error` or `rate_limit` for a success
   and for every failure class of group 5, including a key echoed in an error body and in an allowlisted header value
   (after change 5). `raw_payload`/record `raw` are checked only for bodies that do not echo the key (ledger l covers
   echo). Redaction assertions are bound to the credential **actually supplied to the operation**: they apply
   only when the case's effective access mode is `api_key`. For keyless and keyless-only cases no credential exists, so
   an echoed string in a provider body is provider text, not a secret; those cases assert instead that the request
   carries no key (2b) and make no redaction claim.
   (d) Invalid limit/endpoint/option/cursor fail before send with `ContractViolation`; B1's `ValueError` paths still
   raise (reuse B1 tests, do not duplicate).
   (e) No provider substitution: every request goes to that connector's declared `host`.
   (f) **Dispatched regressions (fail on 5990b02):**
   - `test_dispatched_missing_key_after_freeze_sends_nothing_and_records_a_step`: the `test_search_parallelism`
     harness (its `FIRST_ROUND` has a `serpapi` query, `setup` sets `SERPAPI_API_KEY`); delete the key right after the
     protocol freezes (wrap `Store.freeze_protocol` so the variable is deleted after it returns; parametrize unset and
     `""`). Assert: no request reached SerpApi's host; run `provider_requests` and that query's `query_requests` did not
     count it; its step is `failed`, `error_code="not_configured"`, `delivery_class="before_send"`, output
     `{"status": "not_configured", "result_count": 0}`; no `search_runs` row for it; the other providers' searches
     succeeded with their rows and candidates (compare with a run whose compiled queries omit SerpApi if that is
     stable; otherwise assert presence and success, and say which); the run did not fail with an internal error.
   - `test_dispatched_missing_key_alone_pauses_then_retry_sends_once`: use the full discovery harness, or a
     `_discovery` replacement that runs `_search_round` and, when it returns a failure and no search step succeeded,
     calls `self._pause(run_id, *failure)` exactly as `flow.py:501-503` does. The only query goes to a key-required
     provider without a key: `execute` ends with the run `paused`, reason `provider_not_configured`, usage 0, no
     request. Then set the key, `queue_failed_search_retry`, `execute` again: the same step ID is sent exactly once
     (mock transport) and succeeds.
   - `test_dispatch_reads_the_key_once_per_attempt`: a connector whose `api_key` is instrumented (first call returns a
     key, later calls None, or the reverse): one attempt calls it once; the key passed to `search` is the one checked;
     a `None` snapshot sends nothing and counts nothing. Same for `_kill_search_request`.
   - `test_kill_search_missing_key_charges_no_reservation`: `_kill_search_request` with the key removed returns
     `not_configured/before_send`, `provider_requests` unchanged, connector not called, and `_kill_search_record_query`
     records a `failed` query with `error_code="not_configured"`.
3. **Records and identity.** On the positive page: normalized DOI, `provider_record_id` exactly as the fixture
   expects, abstract versus snippet (SerpApi's snippet is never an abstract; assert the field the code uses), `None`
   counts stay `None` and a supplied 0 stays 0 where the provider supplies counts, PDF version labels as the code sets
   them. Identity cases, each on a page with one good and one bad record: identity field missing, `null`, `""`, and a
   wrong type (number, object). Enforced unless the pair is in `IDENTITY_KNOWN_MISMATCHES` (decision 9): `parse_error`, or the bad record
   absent; never a record whose `provider_record_id` is empty, `None`, `"None"`, or a stringified object. Fix only if
   it is decision-6 shaped; otherwise decision 9. Store-level merge (duplicate DOI keeps both mappings, arXiv versions separate, same title and
   different DOI separate) goes to `COVERED_ELSEWHERE` if existing tests prove it; otherwise add one temp-store test
   through `Store.upsert_provider_source`.
4. **Paging and subrequests.** Unpaged requests send exactly the B1 `unpaged` parameters (reuse the baseline; arXiv's
   `start=0` and IEEE's `start_record=1` are expected); first and second page translation (offset providers send the
   cursor's offset, IEEE `offset + 1`, cursor providers the token); a short last page gives `next_cursor=None`;
   `null`, `""`, absent and non-string tokens on cursor endpoints give `None` (change 4); a repeated token is returned
   as given, and the workflow bound for a non-advancing cursor goes to `COVERED_ELSEWHERE` if a paging test proves it
   stops within the read limit (otherwise one `_read_query` test with a fake connector); S2 relevance `max_reachable`,
   S2 bulk `CUT` when a batch exceeds the limit and estimated total; SerpApi one page, cursor ignored. PubMed: zero
   hits sends only ESearch; success sends ESearch then EFetch; EFetch failure keeps the ESearch payload, total and
   description, EFetch's failure class and (change 2) its `error_kind`; ESearch failure sends no EFetch.
5. **Errors, retries and payload.** For every pair, through the real parser path: non-JSON 200 (B1, reuse); JSON root
   `[]`, `null`, `"SYNTHETIC"`, `1`; result container present as `{}`, `"x"`, `1`; a record container holding a non-object
   item (`[1]`, `["x"]`); PubMed's `idlist` holding a non-string (`[1]`, `[{}]`) or not a list; for arXiv and PubMed EFetch a well-formed foreign root (`<html><body>SYNTHETIC</body></html>`).
   Required: `parse_error`, no records, never an exception, never `zero_results`/`completed` (decision 6). `{}` root and
   absent container: decision 9. HTTP 400 (`failed`, `rejected_not_executed`); 401 and 403 with a key
   (`entitlement_missing`) and, only for providers that can send without a key, without one (`auth_required`); IEEE's
   `Over Queries` 403 keeps its mapping; 500 and 503 (`failed`, `after_send_unknown`); connect error (`failed`,
   `before_send`); read timeout (`timeout`, `after_send_unknown`). Limits with the fake clock: 429 without Retry-After
   retried up to the request's `max_rate_limit_retries`, then `rate_limited`/`error_kind=rate_limited` with `retries`
   equal to it and the waits recorded; Retry-After `1` waits 1 s; Retry-After beyond the policy maximum, malformed
   (`"soon"`), negative (`"-5"`), `"nan"`, `"inf"` and `"-inf"`: no wait, zero retries, `rate_limited` (change 5b);
   a quota body (`insufficient_quota`/daily wording): `error_kind=quota_exhausted`, no retry; arXiv uses 406. Every
   error body and one allowlisted header echo the synthetic key: the outcome carries none (group 2c). For PubMed run
   the failure classes at ESearch and at EFetch.

Any case whose current outcome contradicts the contract and is not covered by decisions 2-9 must not be weakened or
xfailed: stop, write it in the report with file:line, and leave the case asserting the contract (the reviewer decides).

## Files

- Allowed: `backend/deixis/workflow/flow.py` (only `_send_search`, `_record_search`, `_kill_search_request`);
  `backend/deixis/providers/common.py` (decision 8 only); `backend/deixis/providers/pubmed.py` (decision 5, and
  decision 6 in its parse code and `records_from_xml`); `backend/deixis/providers/openalex.py` (decisions 6 and 7 in
  `_works_page` only); every other provider search module (decision 6 only, in its parse code; decision 7 only where
  the suite exposes the same cursor defect); `backend/deixis/providers/registry.py` (`adapter_revision` values only);
  new `tests/test_connector_contract.py`; new `tests/fixtures/connectors/conformance/*.json` and new bodies under
  `tests/fixtures/connectors/responses/`; `tests/connector_baseline.py` (the fake clock extraction of decision 11, the
  `base_commit` literal, and case-script additions the freeze needs; existing cases built the same way);
  `tests/fixtures/connectors/baseline.json` (regenerated only); existing connector test doubles that lack the
  attribute decision 2 reads (e.g. `tests/test_p7_round2.py:103-108`): add `key_required=False` only, nothing else,
  each listed in the report; `tests/test_connector_boundary.py` (the `base_commit`
  line; any line that hard-codes adapter revision 1; and `test_constructor_refuses_incompatible_descriptor`
  (`:84`), whose mismatch value must become `connector.adapter_revision + 1` instead of the literal 2); `docs/product/connector-onboarding.md`
  (ledger: a, i, j marked fixed in B2 with new file:line; new fixed items for decisions 7 and 8, new open items k and l and any group 3 item from decision 9, the missing
  `provider_not_configured` pause text, and the `PENDING_B4` cases; version section unchanged except the revision
  values); `docs/decisions.md` (D178 at the top only); `STATUS.md` (one line).
- Forbidden: `providers/facade.py`, `providers/contract.py`, `providers/query_rules.py`, `providers/query_compiler.py`,
  `providers/lookup.py`, `providers/pacing.py`, every other part of `workflow/` (including `store.py`, `views.py`,
  `routing.py`, `lookups.py`), `api/*`, `storage/*` and migrations, `documents/*`, `models/*`, `domain/*`,
  `contracts/research/*`, `methods/*`, `apps/web/*` (P8 B3 owns it; the missing pause text is a ledger follow-up),
  `scripts/*`, and existing tests and fixtures other than the lines named above. Parallel worktrees: P8 B3
  (`apps/web`, maybe `workflow/views.py`), re-extraction R1 (`store.py`, `api/app.py`, `documents/acquisition.py`,
  `fetch.py`, migration 0066), RR-B (`scripts/p9/*`, `tests/process/*`, `documents/*`, `workflow/views.py`). If B2
  seems to need a forbidden file, stop and report.

## Evidence that the tests bite

On a temporary copy of `5990b02` (not this tree) with the new test file, fixtures and the behavior-preserving clock
extraction of `tests/connector_baseline.py` copied in (no production fix copied), so that the tests collect and fail
in their assertions, not at import, run the dispatched
regressions, the PubMed `error_kind` case, the wrong-root cases of S2 and IEEE, the OpenAlex `""` cursor case, the
header-redaction case and the negative Retry-After case: each must fail for its stated reason (IntegrityError or a
counted request; charged reservation; `error_kind` None and a second PubMed send; `AttributeError`; `""` cursor; key in
`rate_limit`; a retry after a negative wait). Then, each on a temporary copy of the B2 tree: (a) removing the dispatched
guard fails the dispatched regressions; (b) removing the `_record_search` branch fails them with the IntegrityError;
(c) deleting one conformance fixture fails coverage naming that provider; (d) moving IEEE's key from its param to a
header in its fixture's `auth` fails group 2b; (e) disabling the actual validation mechanism the fix uses for one provider (the added `except` class, or the
root/container check, whichever rejects the shape first) fails its malformed case; (f) a second `api_key()` read in `_send_search` fails the snapshot test. Leave the tree clean.

## Run and records

- Focused: `tests/test_connector_contract.py`, `tests/test_connector_boundary.py`, `tests/test_providers.py`,
  `tests/test_provider_records.py`, `tests/test_provider_roles.py`, `tests/test_search_paging.py`,
  `tests/test_search_parallelism.py`, `tests/test_p7_round2.py`, `tests/test_p7_error_classification.py`,
  `tests/test_candidate_run.py`, `tests/test_settings_connections.py`. Then the full default suite; your sandbox cannot
  bind sockets or list processes, so report failure names and compare them with the 17 sandbox-only names of D173
  (`/tmp/p7g-round3-full.log`); the reviewer runs the full suite outside the sandbox. Run `git diff --check`.
- Write the D178 entry at the top of `docs/decisions.md` (`## D178 — P7 G1 B2: ...`; Status with writer gpt-6.1-sol
  high and reviewer pending; Date 2026-10-03; Context; Decision; Limits) and one Turkish line in `STATUS.md` under
  "Şu an çalışanlar". Decision must list the five named behavior changes separately from the suite, with the
  disposition of decision 1 and who agreed it. Limits must say: synthetic fixtures establish application behavior on
  the enumerated cases, not provider truth, availability or recall; no live call; facades still undispatched; the
  pending B4 cases and the design amendment that gives B4 ledger item l as a third named change; decision 9 items unverified against provider documentation; the pause text shows the raw code
  until a web batch adds it; G1 stays open.
- Report to `/tmp/g1b2-impl-report.md`: files changed, each decision's implementation with file:line, the case count
  per group and per connector/endpoint, every mismatch the suite found and its disposition, the baseline diff summary,
  exact commands with counts and times, the bite evidence, anything you could not do or measure. Do not invent.
