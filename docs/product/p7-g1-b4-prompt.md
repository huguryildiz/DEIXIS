<!-- PLAN-REVIEW-ROUNDS: r1 (gpt-6.1-sol medium): düzeltmeyle hazır, 4 high + 4 medium + 1 low, all folded in; r2: düzeltmeyle hazır, 1 medium (branch databases and renumbering), folded in; r3: hazır; agreed decisions 8, 9 (with path correction), 10, 11, decision 5's usability rule and decision 6's storage choice. Code: written by gpt-6.1-sol high; reviewed by Claude Opus 5.5, r1 düzeltmeyle hazır (2 medium: Dispatched attribute fallback, repeated-DOI S2 binding; fixed), r2 hazır. -->

# Task: P7 G1 batch B4, search dispatch through the facade, with provenance and admission

Worktree: `/Users/huguryildiz/Documents/GitHub/DEIXIS-g1-b4`, detached at `98f651f` (origin/main with D193, B3b).
Design: `docs/product/p7-connector-contract-design.md` (accepted as D174). Read sections 2.3 (lines 109-131), 4 (the
lookup and identity-binding paragraphs, lines 199-228), 4.1, 5, 6.1, 6.2 (lines 312-371), 6.3, 7, 8.1, 9 and 10 (row
B4, line 531, and the two paragraphs after the table). Also read `AGENTS.md`, `CLAUDE.md`, D193, D179, D178 and D177
in `docs/decisions.md`, `docs/product/connector-onboarding.md` (its ledger is the list of known mismatches; rows b, c,
d, e, f, g, h, l, every `identity_*` row, `pause_text` and every `b4_*` row concern this batch),
`docs/product/p7-g1-b2-prompt.md` (the dispatched missing-key fix B4 must preserve) and
`docs/product/p7-g1-b3a-prompt.md` (`facade.search_request` and the dispatcher-shape equivalence). Read `.impeccable.md`
before the label edit. Venv: `PYTHONPATH=backend:. UV_CACHE_DIR=/tmp/deixis-uv-cache .venv/bin/python -m pytest ...`
(`.venv` is a symlink to the arm64 venv of the main checkout). Web: `apps/web/node_modules` is already installed by the
reviewer; run only `cd apps/web && npm run build && npm run lint` (no `npm ci`, no network).

**No git state-changing commands** (no add, commit, stash, checkout, reset, branch, worktree). Leave every change
uncommitted. No real-model call, no provider call, no network, no DNS. Do not touch `../DEIXIS*` worktrees, `TODO.md`,
`.vscode/`, `scripts/local_index.py`, the live service on port 8765, or the live data directory.

Batch B4 only. B5 (G1 acceptance record and product-document wording) is later; do not start it. The decision number
is **D194** (one entry). The migration number is **0067** (the highest on origin/main is `0066_asset_recovery.sql`).
`storage/db.py:232-250` identifies migrations by numeric prefix, so two branches must never ship the same prefix. The
coordinator reserves 0067 for B4; re-extraction R2b, running in parallel, takes the next number after whatever is on
origin/main when it pushes, and whichever batch pushes second renumbers at rebase. The reviewer verifies unique
prefixes and an upgrade from a database migrated to the then-highest number after the rebase. Databases migrated on a
pre-rebase branch are disposable by rule: only temporary test databases ever apply an unpushed migration (the live
library on port 8765 runs main and is never opened by this batch), so no reconciliation of a branch database is
supported. After any renumbering, the reviewer runs the migration tests on fresh databases and an upgrade from a
database migrated to origin/main's highest number with existing `search_runs` rows; if any non-temporary database is
found to have applied a renumbered migration, stop and report instead of migrating it.

## Why

D174 row B4: "Move dispatch to the equivalent facade; `workflow/flow.py`, `store.py`, lookup/capability bindings,
contract/adapter revision metadata; API projection and onboarding path." D178 and D179 then assigned B4 four named
behavior changes: (1) persist `error_kind` so quota and temporary rate-limit rows and pause reasons stay distinct;
(2) bind Semantic Scholar batch answers by `externalIds` DOI/ArXiv, not position; (3, ledger l) remove the
operation's key from stored provider payloads and hash the sanitized form; (4) drop and count records without a usable
provider identity (the 42 `IDENTITY_KNOWN_MISMATCHES` characterizations). B4 must also preserve B2's dispatched
key-removal regression, close or re-own every `PENDING_B4` case, and say whether the declared retry policy drives
dispatch or name the gap. After B4, G1 has only B5 left, and P8 B5-B7 wait for B4 because they share `providers/*`.

The refactor (dispatch moves from registry callables to the facade) and the four named changes are separate. Every
test and the decision entry must keep them apart: dispatch through the facade sends identical requests and receives
identical outcomes; admission, sanitization, provenance and the S2 binding change what is stored or decided after
that.

## What is and is not in code (checked on 98f651f)

Paths under `backend/deixis/` unless stated.

Dispatch still uses registry callables:

- `workflow/flow.py:2032-2067` `_send_search`: reads the key once per attempt (`:2044`), returns
  `not_configured/before_send` before quota suppression and `add_usage` for a key-required connector without one
  (`:2045-2047`, B2), suppresses an exhausted provider (`:2048-2050`), counts the request (`:2051`), then calls
  `connector.search(self.deps.http, query["query_text"], limit, key, email, **({"cursor": ..., "max_rate_limit_retries":
  ..., **connector.sw_options, **endpoint_options(query)} if page else {}))` (`:2053-2056`). Its only caller is the sw
  paged read, `_read_query` (`:2283`), which passes `connector = reading(read.query)` (`:2244`): a `dataclasses.replace`
  of the registry entry with the named endpoint's paging and depth (`providers/registry.py:201-212`), not the registry
  entry itself.
- `workflow/flow.py:4663-4687` `_kill_search_request`: the same key guard (key read at `:4671`), a reservation
  (`:4676-4680`), then `connector.search(..., KILL_RECORDS, key, email, **endpoint_options(query))` (`:4681-4682`).
- `providers/facade.py:56-59` `search_request` maps registry keywords to `contract.SearchRequest` without validation;
  `:61-111` `CompatibilityConnector.search` validates and forwards. B3a measured direct/facade equality for 566
  conformance cases and all 181 dispatcher keyword shapes (`tests/test_connector_facade.py`). `workflow/` imports
  neither.
- Citation chaining calls `openalex.citing_works` / `openalex.works_by_ids` directly (`workflow/flow.py:1700-1706`);
  record lookups call `lookup.semantic_scholar_batch`, `lookup.crossref_work` and `lookup.scopus_abstract` directly
  (`workflow/lookups.py:324,349,413`). Those helpers are listed in `registry.UNBOUND_HELPERS` (`registry.py:161-166`);
  every facade declares only `search` and `lookup` returns `unsupported` (`facade.py:113-116`).

Limit kinds (ledger c):

- `_record_search` (`flow.py:2069-2133`) already writes `error_kind` into the `search_runs.error_json`
  (`:2096-2101`), and the returned pause detail carries it (`:2130-2132`). The step error (`:2125-2126`,
  `{"error", "http_status"}`) does not, and the pause reason is `f"provider_{outcome.status}"`, so quota exhaustion and a
  temporary rate limit both pause as `provider_rate_limited` (`tests/test_p7_round2.py:225` pins that). Chaining's row
  and step error (`flow.py:1742-1743`, `:1762-1766`) and kill-search's step error (`flow.py:4708-4710`) omit
  `error_kind` too.

Semantic Scholar batch identity (ledger b):

- `providers/lookup.py:68-95` checks only that the answer is a list of the requested length (`:87-89`), then binds
  `zip(dois, payload)` (`:95`). An equal-length reordered answer attaches another record's abstract, reference count
  and `linked_dois`. `_s2_answer` (`:101-115`) turns a non-dict item into `not_found` and an `externalIds.DOI` different
  from the asked DOI into a `linked_dois` relation. The module docstring (`:9-14`) claims more than the code checks.

Payload secrecy (ledger l):

- Search, chain and kill-search payloads are written with `json.dumps(outcome.raw_payload)` and hashed with
  `canonical.sha256_hex(outcome.raw_payload)` (`flow.py:2088-2093`, `:1728-1733`, `:4700-4704`); lookup payloads are
  written with `dumps(payload)` and no digest (`workflow/lookups.py:434-440`). Chaining reads the key inside
  `_chain_request` (`flow.py:1703-1707`), and `_record_chain` does not receive it. Nothing removes a key a provider echoed inside a successful body:
  `PENDING_B4["l"]` (`tests/test_connector_contract.py:143-144`) reproduces it for OpenAlex. `ProviderRecord.raw` is not
  persisted by the store today (no read of `.raw` in `workflow/`), but the ledger asks for both representations to be
  sanitized before persistence.

Identity admission (ledger `identity_*`):

- `tests/test_connector_contract.py:94-137` pins 42 cases in which a record with an empty, `"None"`, numeric-text or
  stringified-object provider ID is admitted as `completed`; `:352-356` asserts every other identity case either fails
  to parse or yields no such ID. `store.record_search` (`workflow/store.py:2172-2196`) writes whatever the outcome
  carries.

Provenance and stored revisions (`b4_stored_revision`):

- `contract.py:1-8` and `connector-onboarding.md` ("Version and unsupported rules") defer recorded-operation revision
  checks to B4. No search row or step records the contract ID, adapter revision or query-rule revision that produced
  it. A resumed sw read continues from the stored `next_cursor` of the last succeeded page (`flow.py:2251-2259`)
  whatever revision wrote it.

Other facts:

- `api/app.py:899-915` `/api/connections` lists providers with `implemented`, `access_mode`, `supplementary`, `key_env`,
  `role` and a note that access and quota are not verified in advance; it reads `CONNECTORS`, not the facade.
- `apps/web/src/labels.ts:32-71` has pause texts for `provider_rate_limited`, `provider_auth_required`, ... but none for
  `provider_not_configured` (D178 limit; ledger `pause_text`); `pauseReasonText` (`:83`) falls back to the raw code.
  Turkish strings live in `apps/web/src/i18n.ts` keyed by the English text (`:1190` for the rate-limit text).
- `RetryPolicy` is descriptive (`contract.py:51-61`); modules set their own retry/wait/timeout inside `send` calls
  (ledger g). D179's agreement tests (`tests/test_connector_facade.py`) pin descriptor equals module behavior.
- Local `ValueError` paths (bad offsets, unknown S2 endpoint, reused `CUT`; ledger d) are unscheduled; the facade's
  pre-send refusal is `ContractViolation`, a `ValueError` subclass.

## Decisions taken where the design is open (use these; never ask)

Decisions 8-11 are owner-level choices proposed by the prompt author and put to gpt-6.1-sol medium in plan review
round 1; the review record states whether Sol agreed. Implement them as written here unless this file is revised.

1. **Dispatch moves to the facade (refactor, no behavior change).** Add to `providers/facade.py` one dispatch entry
   point, for example `async def dispatch_search(provider_id, http, query_text, limit, api_key, contact_email,
   **registry_kwargs) -> Dispatched`. It builds the request with `search_request(query_text, limit, **registry_kwargs)`,
   a `contract.ConnectorContext(http, api_key, contact_email)` with the **caller's snapshotted key** (not
   `context_for`, which reads the environment again; B2's rule is that the key checked is the key sent), obtains the
   `CompatibilityConnector` for `registry.CONNECTORS[provider_id]` (the registry entry, never the `reading()` view), and
   awaits its `search`. `_send_search` and `_kill_search_request` pass `connector.provider_id` (several existing tests
   build queries without `provider_id`). `Dispatched` is a small frozen dataclass in `facade.py` carrying the outcome (after decisions 4
   and 5), the number of dropped records and the provenance of decision 6. `SearchOutcome`, `common.py`, `contract.py`
   and every provider module are unchanged; `CompatibilityConnector.search` itself is unchanged, so B3a's direct/facade
   equalities still hold. `_send_search` and `_kill_search_request` call `dispatch_search` in place of
   `connector.search`, with the same keywords they pass today; everything before the call (key snapshot, B2 guard,
   quota suppression, `add_usage`, reservation, transient retry loop) stays where it is. Carry `Dispatched` to the
   writers (for example a field on `_PageRead`); flow-made outcomes (`not_configured`, quota suppression,
   `transport_budget`) carry no provenance and drop nothing. After B4, `workflow/` contains no `connector.search(`
   call (a static test asserts it). Chaining and record lookups keep their direct helper calls (decision 10).
2. **Named change 1: limit kinds are persisted and paused apart.** In `_record_search`, the step error becomes
   `{"error", "http_status"} | {"error_kind": ...}` when `outcome.error_kind` is not None, and the pause reason is
   `provider_quota_exhausted` when `outcome.error_kind == "quota_exhausted"`, otherwise `f"provider_{outcome.status}"`
   as today (a temporary limit stays `provider_rate_limited`). Statuses are not renamed: the row and step keep
   `status`/`error_code` `rate_limited` for both kinds; `search_runs.error_json` keeps its existing `error_kind`.
   Quota suppression (`flow.py:2048-2050`) therefore also pauses as `provider_quota_exhausted`. Apply the same
   `error_kind` addition to the chaining row and step error and to the kill-search step error; kill-search keeps its
   candidate `error_code` (`outcome.status`) unchanged. Historical rows are not rewritten. Update
   `tests/test_p7_round2.py:225` to the new reason (named change, not a weakened assertion).
3. **Named change 2: S2 batch answers bind by identifier.** In `lookup.semantic_scholar_batch`, keep the request, the
   length check and the `parse_error` path. Then decide in this order:
   (a) *Names.* A non-null answer names a request when its identifiers match it: a `DOI:` request when
   `normalize_doi(externalIds.DOI)` equals the asked DOI; an `ARXIV:` request when `externalIds.ArXiv`, stripped,
   case-folded and without a trailing `vN`, equals the asked arXiv id (the part after `10.48550/arxiv.`, case-folded).
   A non-dict `externalIds`, or a `DOI`/`ArXiv` value that is not a nonempty string, names nothing (no exception).
   (b) *Unique identifier match wins.* A request named by exactly one answer is answered by that answer through
   `_s2_answer`, wherever it sits in the list, so an arXiv request whose answer carries a different `externalIds.DOI`
   still records that DOI in `linked_dois` (the legitimate preprint-to-publication relation). A request named by two or
   more answers is `failed`. An answer's position never overrides a unique identifier match: for requests `[A, B]`
   and answers `[X, A]`, A is `found` from the second answer.
   (c) *Position only for an order-consistent null.* A request named by no answer is `not_found` only if the answer at
   its own position is null **and** the response is order-consistent: every non-null answer names exactly the request
   at its own position. Otherwise it is `failed`. A non-null answer that names no request is never attached to anyone
   and makes the response inconsistent.
   The outcome status stays `completed`; `outcome.error` names how many answers were unbound or ambiguous (bounded
   text, counts only). `raw_payload` is unchanged. Correct the module docstring (`:9-14`) to describe this rule.
   `workflow/lookups.py` needs no change for binding: a `failed` answer is asked again by a later run
   (`lookups.py:76-82`).
4. **Named change 3: stored payloads carry no operation key.** In `facade.py`, a pure function (for example
   `sanitize(value, secrets)`) returns a deep copy of a JSON-like value in which every occurrence of each nonempty
   secret inside any string, dictionary key included, is replaced by `<redacted>` (the marker `common.redact` already
   uses). If replacement inside dictionary keys makes two keys of one dictionary equal, that whole dictionary is
   replaced by `{"<omitted>": "secret_key_collision"}` instead of silently keeping one value (test it).
   `dispatch_search` applies it with the snapshotted key to `outcome.raw_payload` and to every `record.raw`
   before returning; a keyless operation has nothing to redact (B2 decision 2c). The flow then writes and hashes the
   sanitized payload exactly as before, so `payload_sha256` covers the sanitized form. Apply the same function, with
   the key that operation sent, at the chain write (`flow.py:1728-1733`; `_chain_request` snapshots the key once per
   attempt, passes that snapshot to the helper, and hands the final attempt's key to `_record_chain`; a test changes
   the environment key between send and write and finds neither value in the file) and in `workflow/lookups.py`'s
   `_write_payload` callers for Semantic Scholar and Scopus (the only keyed lookups). Redaction of a value that is not
   the operation's own key is out of scope (name it).
5. **Named change 4: records without a usable provider identity are dropped and counted.** In `facade.py`, one pure
   predicate decides usability for every provider (no provider literal): a `provider_record_id` is unusable when it is
   not a `str`, is empty after stripping, equals `"None"`, or is the text of a stringified container (starts with `{`
   or `[` after stripping). Numeric text stays usable for every provider: the adapter's string does not reveal whether
   it came from a JSON number, and CORE's and IEEE's native identities are numeric (D178 disposition 4: stringification
   alone is not a defect). `dispatch_search` removes unusable records from `outcome.records` and reports how many it
   removed in `Dispatched`. The provider-returned count still drives paging: `_stop_reason`, `read_total` and the
   empty-page stop use the records the provider returned (so a page whose records are all dropped does not end the read
   early), while `result_count`, candidates and sources use the admitted records. When the count is nonzero, the step
   output gains `dropped_records` and the search row's provenance (decision 6) holds it; when it is zero, step outputs
   are byte-identical to today. Kill-search applies the same admission. The 42 characterizations become dispositions:
   for each, a dispatched test states whether the record is dropped or admitted and why (under this rule the `"17"`
   cases of OpenAlex, bioRxiv and Semantic Scholar stay admitted; name that as a limit). Direct and `facade.search`
   outcomes keep their current characterization, so `IDENTITY_KNOWN_MISMATCHES` stays as evidence of adapter output
   with its owner changed to "B4 admission (D194)".
6. **Provenance and stored-revision refusal.** New migration `0067_search_run_connector.sql` adds
   `search_runs.connector_json TEXT` (nullable; NULL on every earlier row and on flow-made rows). For a dispatched
   outcome, `_record_search` writes `{"contract_id", "adapter_revision", "query_rules_revision", "payload":
   "sanitized_json" | null, "dropped_records": n}` from the descriptor and `Dispatched`. `store.py` is not edited:
   `add_search_run` inserts any column it is given. In `_read_query`, when a succeeded stored page supplies the
   `next_cursor` the read would continue from, read that page's `connector_json` (one SQL read through
   `self.store.conn`, as `flow.py` does elsewhere). SQL NULL on an existing row (written before B4) continues under the
   compatibility facade. A non-NULL value is validated before continuation: it must be a JSON object whose
   `contract_id` is a string in `contract.SUPPORTED_CONTRACTS` and whose `adapter_revision` is an exact `int` equal to
   the current descriptor's. A revision or contract mismatch refuses with `error_code="adapter_revision_changed"`;
   invalid JSON, a non-object, a missing field, a wrong type, or a succeeded page step with no search row refuses with
   `error_code="connector_provenance_invalid"`. Either refusal is visible: the next page's step ends `failed` with that
   error code,
   output `{"status": <error code>, "result_count": 0}`, no request, no usage, no `search_runs` row, no
   page-one restart and no provider change; the query's read ends, and `_record_search`'s caller returns the pause
   reason `provider_adapter_revision_changed` exactly as other failed pages return theirs (D18 decides whether the run
   pauses). Kill-search is single-request and terminal and records no `connector_json` (name it). Update the
   `contract.py`-equivalent wording in the `facade.py` docstring and the onboarding "Version and unsupported rules"
   section; `contract.py` itself stays unchanged.
7. **Pause labels (web).** Add pause texts in `apps/web/src/labels.ts` for `provider_quota_exhausted`, 
   `provider_not_configured` and `provider_adapter_revision_changed`, each with its Turkish entry in `i18n.ts`, in the
   voice of the existing provider texts (what happened, that completed searches are kept, that no other provider was
   used in its place where true). The revision text covers both refusals of decision 6 (a changed or unreadable
   record of the connector version that read the earlier pages). For quota: no automatic retry in this run; resuming or retrying resets the guard
   (D173). Nothing else in `apps/web` changes.
8. **Retry policy stays descriptive; the gap is named.** Dispatch passes exactly the retry allowance the flow passes
   today (decision 1). `RetryPolicy` does not drive `send`: making it drive behavior means editing every provider
   module's `send` call (ledger g), which P8 B5-B7 also wait to touch. D179's agreement tests remain the guard that the
   descriptor matches module behavior. D194 and ledger g name this as unscheduled.
9. **Ledger d stays unscheduled.** B4 converts no local `ValueError`. B3a measured that every dispatcher shape is
   representable, so dispatch through the facade raises nothing new for stored queries the registry still declares.
   Two paths behave differently for a stored query naming an endpoint the registry no longer declares, and each is
   pinned by its own test with its accounting: the paged sw read calls `reading()` first (`flow.py:2244`), whose
   `connector.endpoints[endpoint]` (`registry.py:211`) raises `KeyError` before any usage, unchanged by B4; S2
   kill-search reaches the module after its reservation (`flow.py:4676-4682`), where the old module raised
   `ValueError` (`semantic_scholar.py:80-81`) and the facade now raises `ContractViolation` (a subclass) after the same
   reservation. D194 names both.
10. **Lookup capability binding is not in B4.** Workflow lookups are batched (one S2 request for up to 200 DOIs,
    `lookups.py:324`); routing them through the single-record `lookup` method would multiply requests, and a batch
    method changes `CONTRACT_ID`. Binding single-record facade lookups that no caller uses adds conformance fixtures
    without integration. B4 keeps `lookup` `unsupported` with zero requests and the helpers in `UNBOUND_HELPERS`; the
    S2 identity fix (decision 3) lands in the helper the workflow uses. `PENDING_B4["b4_resume_lookup"]` is re-owned
    to a named, unscheduled "lookup capability binding" row in the ledger, with D174 Q3's default recorded as not yet
    met. B5 must state this when it records G1.
11. **API projection.** Each provider row of `/api/connections` gains `contract_id`, `adapter_revision` and
    `capabilities` (sorted list from the facade descriptor; `["search"]` today). Wording and every existing field stay;
    no access claim is added. The frontend does not read the new fields (no type change needed unless `tsc` requires
    it).

## Files

- Allowed: `backend/deixis/providers/facade.py` (decisions 1, 4, 5, 6 docstring), `backend/deixis/providers/lookup.py`
  (decision 3), `backend/deixis/workflow/flow.py` (decisions 1, 2, 4, 5, 6, only in `_send_search`, `_record_search`,
  `_read_query`, `_write_query`, `_PageRead`, `_chain_request` (key snapshot only), `_record_chain`, `_kill_search_request`, `_kill_search_record_query` and
  their direct helpers), `backend/deixis/workflow/lookups.py` (decision 4 only), new
  `backend/deixis/storage/migrations/0067_search_run_connector.sql`, `backend/deixis/api/app.py` (decision 11, the
  connections route only), `apps/web/src/labels.ts` and `apps/web/src/i18n.ts` (decision 7 only); new
  `tests/test_connector_dispatch.py`; `tests/test_connector_contract.py` (close `PENDING_B4`, re-own identity rows and
  `b4_resume_lookup`, keep the ledger-consistency test working); `tests/test_p7_round2.py:225` (decision 2); other
  existing tests only where a named change alters an asserted value (list every such edit with its reason in the
  report; never weaken an assertion to make it pass). Existing tests whose doubles bypass the registry
  (`tests/test_connector_contract.py:541-574` passes standalone `SimpleNamespace` connectors; `tests/test_p7_round2.py:103-108,195-211`
  supplies incomplete descriptor doubles) may convert their fixtures only, to `dataclasses.replace` of the registry
  entry installed with `monkeypatch.setitem(registry.CONNECTORS, ...)`, keeping every behavioral assertion; `docs/product/connector-onboarding.md` (ledger rows b, c, d, f, g,
  h, l, every `identity_*`, `pause_text`, every `b4_*`, the version section and the intro paragraph);
  `docs/decisions.md` (D194 at the top only); `STATUS.md` (one line under "Şu an çalışanlar").
- Forbidden: `providers/contract.py`, `providers/common.py`, `providers/registry.py`, every provider search module,
  `providers/query_rules.py`, `providers/query_compiler.py`, `providers/pacing.py`, `workflow/store.py`,
  `workflow/views.py`, every other `workflow/*` file, `api/*` outside the connections route, `storage/db.py` and every
  existing migration, `documents/*`, `models/*`, `domain/*`, `contracts/research/*`, `methods/*`, `apps/web/*` outside
  the two label files, `scripts/*`, `tests/fixtures/connectors/baseline.json`,
  `tests/fixtures/connectors/query_baseline.json` and the conformance fixtures. Parallel worktrees: re-extraction R2b
  (`../DEIXIS-reextract-r2b`: `documents/`, file writers, `store.py` file paths; it may also add a migration), P8 B4
  (`scripts/model_behavior`, docs), H9 (docs). If B4 seems to need a forbidden file, stop and report.

## Tests (new module `tests/test_connector_dispatch.py`, plus the edits above)

The module installs its own autouse fail-closed guard (block `socket.socket.connect`, `socket.getaddrinfo` and
HTTPX's real transports), supplies only synthetic credentials and uses temporary storage. Group them by decision:

- **Dispatch equivalence (refactor).** For every registered provider and declared endpoint, every dispatcher keyword
  shape from B3a (reuse its enumeration; do not copy it) sent through `dispatch_search` with a key, a positive native
  script and a 429-without-Retry-After script: requests, waits and the whole outcome equal the registry callable's,
  except the named post-processing (records with usable IDs only; sanitized payload), which these positive scripts do
  not trigger, so equality is exact. A spy shows `_send_search` and `_kill_search_request` reach
  `CompatibilityConnector.search` once per attempt with the snapshotted key; a static scan shows no
  `connector.search(` in `backend/deixis/workflow/`. A synthetic connector inserted into `registry.CONNECTORS` (with
  its own transport) is dispatched and recorded by the generic flow code with no provider branch.
- **B2 preserved.** The four dispatched missing-key regressions in `tests/test_connector_contract.py` pass unchanged,
  and one new case removes the key after the freeze while the spy proves the facade was never reached.
- **Named change 1.** Through `_record_search` and through a full dispatched discovery with mocked transports: a quota
  refusal and a temporary 429 produce rows and steps with the same `rate_limited` status but `error_kind` in both the
  row error and the step error, and pause reasons `provider_quota_exhausted` and `provider_rate_limited`; quota
  suppression pauses as `provider_quota_exhausted`; chaining and kill-search step errors carry `error_kind`.
- **Named change 2.** A two- and a three-DOI batch: equal-length reordered answers bind each abstract to its own DOI;
  an answer naming an unrequested DOI makes its position `failed` unless that request is uniquely named elsewhere
  (requests `[A, B]`, answers `[X, A]`: A `found`, B `failed`); malformed `externalIds` names nothing without raising; a duplicate makes the request `failed`; a null in an
  order-consistent response is `not_found` and in a reordered response is `failed`; an `ARXIV:` request whose answer
  carries a journal DOI keeps that DOI as `linked_dois`, with ArXiv ids compared case-insensitively and without `vN`.
  Through `workflow/lookups.py` with a temp store, a reordered batch writes the right abstract to each source version.
- **Named change 3.** The `PENDING_B4["l"]` reproduction dispatched and recorded: the stored payload file, the record
  `raw` and `payload_sha256` contain no key and the digest equals the digest of the sanitized object; a key used as a
  dictionary key is redacted; a key collision omits that dictionary with its reason; a keyless operation's payload is byte-identical; chaining and the keyed lookups write
  no key.
- **Named change 4.** Each of the 42 characterizations dispatched: dropped or admitted per decision 5, the count in
  the step output and `connector_json`, `result_count` equal to admitted records, read paging driven by returned
  records (a page whose records are all dropped does not end the read).
- **Provenance and revision.** New rows carry `connector_json` with the current revisions; earlier rows and flow-made
  rows hold NULL; a resumed read whose stored page has NULL continues; a stored page whose adapter revision differs
  from the descriptor's (monkeypatch the registry entry's revision and descriptor together) ends that read with the
  `adapter_revision_changed` step, no request, no usage and no row; an unsupported contract ID refuses the same way;
  invalid JSON, a non-object, missing fields, wrong types and a missing search row each end with
  `connector_provenance_invalid`; the migration applies on a database migrated to
  0066 with existing rows untouched and the migration-list tests stay strict.
- **Integration closures.** `b4_merge_version`: two dispatched providers returning the same DOI give one source with
  both mappings; arXiv versions stay separate source versions. `b4_resume_paging`: a resumed dispatched sw read asks no
  page twice. `b4_payload_write`: a payload write that raises `OSError` publishes no source, candidate, search row or
  succeeded step. `b4_s2_binding`, `b4_limit_provenance`, `b4_stored_revision` and `l` close into the groups above.
  `PENDING_B4` is removed; the ledger-consistency test checks the new owners.
- **Ledger d and API.** Both stored-unknown-endpoint paths of decision 9 with their usage and reservation; `/api/connections` returns the new
  fields through `create_app(..., adapters=fakes, http_client=mocked, start_worker=False)` with temporary data.

## Evidence that the tests bite

Old-code harness: a temporary copy of `98f651f` (not this tree) with the new and changed test files copied in, plus
only this setup scaffolding: `0067_search_run_connector.sql` (so the column exists) and nothing else. Behavioral bite
must come through entry points that exist there: named change 1 through `_record_search` and a dispatched discovery
(pause reason and step error); named change 2 through `lookup.semantic_scholar_batch` (wrong abstract bound); named
change 3 through `_send_search` + `_record_search` reading the payload file (key present); named change 4 through a
recorded discovery (unusable record admitted); the revision refusal by inserting a mismatched and a malformed
`connector_json` on a stored page (old code sends the next page). Each must fail for that stated reason. List
separately the tests that fail only because an interface is absent (`dispatch_search`, `Dispatched`, the spy and
static tests): they are not behavioral evidence. List the tests expected to pass on old code (dispatch equivalence of
registry callables with `facade.search`, numeric-identity admissions, B2 regressions). Then, each on a temporary copy
of the B4 tree: (a) reverting `_send_search` to `connector.search` fails the spy and static tests; (b) zipping S2
answers by position fails the reorder and `[X, A]` tests; (c) skipping sanitization of `record.raw` only fails a named
case; (d) admitting `"None"` fails the identity disposition; (e) driving `_stop_reason` from admitted records fails
the all-dropped-page test; (f) skipping the revision comparison fails the refusal test; (g) reading the key again
inside the facade fails the key-snapshot test; (h) accepting malformed provenance as NULL fails the malformed test;
(i) keeping the last value on a redacted-key collision fails the collision test. Leave this tree clean.

## Run and records

- Focused: `tests/test_connector_dispatch.py`, `tests/test_connector_contract.py`, `tests/test_connector_facade.py`,
  `tests/test_connector_boundary.py`, `tests/test_query_delegation.py`, `tests/test_providers.py`,
  `tests/test_provider_records.py`, `tests/test_search_paging.py`, `tests/test_search_parallelism.py`,
  `tests/test_p7_round2.py`, `tests/test_p7_error_classification.py`, `tests/test_record_lookups.py`,
  `tests/test_lookup_flow.py`, `tests/test_api_flow.py`, the kill-search and chaining tests you touch, and the
  migration tests. Then the full default suite; your sandbox cannot bind sockets or list processes, so report failure
  names and compare them with the sandbox-only names recorded for D179/D193 (the reviewer runs the full suite outside
  the sandbox). `cd apps/web && npm run build && npm run lint` (the reviewer checks the rendered pause texts in the browser).
  `git diff --check`. The original `baseline.json` and
  `query_baseline.json` must stay byte-identical (compare a scratch capture outside the repo; never `--write`).
- Write D194 at the top of `docs/decisions.md` (`## D194 — P7 G1 B4: ...`; Status with writer gpt-6.1-sol high, plan
  reviewer and reviewer pending; Date 2026-10-03; Context; Decision; Evidence; Limits). Decision lists the refactor
  separately from the four named changes and from provenance/refusal, plus decisions 8-11 and who agreed; it states that decision 10 amends D174's B4 row (lookup/capability binding moves out of B4 to a named unscheduled owner) and that D174 Q3's default is not yet met, so B5 cannot record the original binding as done. Evidence
  gives counts per test group, the old-code failures and the mutations. Limits: synthetic fixtures establish
  application behavior on the enumerated cases, not provider truth or availability; no live call; `RetryPolicy` stays
  descriptive; ledger d unscheduled; lookup capability binding and chaining dispatch unbound; numeric-text identities
  admitted; only the operation's own key is redacted; kill-search records no `connector_json`; transport accounting
  (Q4, ledger e) unchanged; G1 stays open until B5. One Turkish line in `STATUS.md`.
- Report to `/tmp/g1b4-impl-report.md`: files changed, each decision's implementation with file:line, test counts per
  group, the baseline byte comparisons, exact commands with counts and times, the bite evidence, and anything you
  could not do or measure. Do not invent.
