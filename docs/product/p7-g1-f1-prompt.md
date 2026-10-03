<!-- PLAN-REVIEW-ROUNDS: r1 (gpt-6.1-sol medium): düzeltmeyle hazır, 2 high + 6 medium + 1 low, all folded in (lookup answer redaction O8, chain paging from returned counts, Scopus whole-envelope sanitization, settlement exit rules, binding call contract, validation tests, malformed-200 characterization, purity test split, citations); O1-O7 agreed. r2: düzeltmeyle hazır, 2 high + 5 medium + 1 low, all folded in (repeated S2 identifiers allowed, single sanitization of the Scopus envelope, per-chunk key snapshot, omitted retry keyword, citing limit clamping, trace persisted after each settlement, two assertion stages, citations); O1-O8 agreed. r3: düzeltmeyle hazır, 1 high + 3 medium, all folded in (settlement and trace in one transaction, accumulator resumed from stored output, citing error text untouched so O7 holds, collector-accounting tests with rebuilt outcomes); O7 agreed after O8 was restricted to lookup dispatch. r4: düzeltmeyle hazır, 1 medium + 1 low (Scopus missing-key terminal states, freeze statement in the acceptance record), folded in by the orchestrator without a fifth round; O1-O8 agreed. Code: written by gpt-6.1-sol high; reviewed by Claude Opus 5.5, r1 düzeltmeyle hazır (1 medium: citing ceiling 100 vs 200 in docs; 3 low: orphan import and parameter, empty trace on an unsent chunk), all fixed; r2 hazır. -->

# Task: P7 follow-up batch G1-F1, lookup and OpenAlex citation chaining bound through versioned connector capabilities

Worktree: `/Users/huguryildiz/Documents/GitHub/DEIXIS-g1-f1`, detached at `bbcf575` (origin/main with D186, P8 B5).
Read first: `AGENTS.md`, `CLAUDE.md`; in `docs/decisions.md` D196, D199, D194 (decision 10 and the four named
changes), D186 (OpenAlex adapter revision 3, the watch citing read), D174 (Q3; the design is
`docs/product/p7-connector-contract-design.md`, section 4 lines 170-221 and section 4.1); `docs/product/p7-acceptance-record.md`
section 6 items 3 and 6 and section 7's G1-F1 row (line 168); `docs/product/connector-onboarding.md` (gates,
version rules, ledger row `b4_resume_lookup`). Venv: `PYTHONPATH=backend:. UV_CACHE_DIR=/tmp/deixis-uv-cache
.venv/bin/python -m pytest ...` (`.venv` is a symlink to the arm64 venv of the main checkout).

**No git state-changing commands** (no add, commit, stash, checkout, reset, branch, worktree). Leave every change
uncommitted. No real-model call, no provider call, no network, no DNS, no real key (synthetic keys only). Do not touch
`../DEIXIS*` worktrees, `TODO.md`, `.vscode/`, `scripts/local_index.py`, port 8765 or the live data directory. The
decision number is **D201**; the reviewer writes the decision entry and `STATUS.md`, you do not. No migration.

## Why

G1 was accepted for search only (D196). Item 3: every descriptor declares only `search`; the workflow's Crossref,
Semantic Scholar batch and Scopus lookups call provider helpers directly (`registry.UNBOUND_HELPERS`), so a new adapter
can add search through the contract but not lookup, and D174 Q3's default ("Every facade implements `lookup`;
unavailable remote lookup returns `unsupported` without a request. Enable existing bindings only") is unmet. Item 6:
citation chaining calls `openalex.citing_works` and `openalex.works_by_ids` directly. D199 left `lookup_requests` and
`chain_requests` counted as before (one up front plus `outcome.retries` afterwards), outside the transport collector
and the reserve-then-settle rule. D186 added a third direct caller: the watch citing read hand-builds the admission,
sanitization and provenance that `facade.dispatch_search` gives a search. G1-F1 is the last batch blocking P7's exit.

## What is and is not in code (checked on bbcf575)

Paths under `backend/deixis/` unless stated.

- `providers/contract.py`: `CAPABILITIES = {search, doi_lookup, id_lookup, citing_works}` (`:44`); `LookupRequest`
  (exactly one DOI or provider record id, `:144-156`); `LookupOutcome(status, operation, answer, outcome)` (`:159-163`);
  `ScholarlyConnector.lookup` is a protocol method (`:174`). No batch or citing request type exists.
- `providers/facade.py`: `descriptor_for` hard-codes `frozenset({"search"})` (`:58`); `CompatibilityConnector.lookup`
  validates and returns `unsupported` for every connector with no request (`:184-187`); `dispatch_search` (`:115-131`)
  opens `common.collect_transport()`, admits records with `usable_identity`, sanitizes record `raw` and `raw_payload`
  with the sent key and returns `Dispatched(outcome, dropped_records, connector, transport)`.
- `providers/registry.py:162-168`: `UNBOUND_HELPERS` names `lookup.crossref_work`, `lookup.semantic_scholar_batch`,
  `lookup.scopus_abstract`, `openalex.works_by_ids`, `openalex.citing_works`. `facade.py:32` re-exports it; only
  tests read it (`tests/test_connector_boundary.py:122`).
- `providers/lookup.py`: `semantic_scholar_batch(client, dois, api_key, max_rate_limit_retries)` (`:69`, one POST for
  the whole list, D194 identifier binding, no length limit of its own; the docstring records the documented 500 ids);
  `crossref_work(client, doi, contact_email)` (`:152`, keyless, no retry parameter so `send`'s default 2, 404 is
  `not_found` with `zero_results`); `scopus_abstract(client, doi, api_key, max_rate_limit_retries)` (`:186`, answers
  only for an entry naming the asked DOI). `providers/openalex.py`: `citing_works(client, work_id, cursor, per_page,
  api_key, contact_email, max_rate_limit_retries, *, sort, publication_date)` (`:183`), `works_by_ids(client, ids,
  api_key, contact_email, max_rate_limit_retries)` (`:217`, 1-100 ids else `ValueError`). Every one of them sends
  through `common.send`, so the D199 collector already records them when one is open.
- `workflow/lookups.py`: `_semantic_scholar_step` (`:307-335`), `_crossref_step` (`:338-361`), `_scopus_step`
  (`:401-424`) each `add_usage(run, "lookup_requests")` before the call and `add_usage(..., outcome.retries)` after;
  S2 and Scopus sanitize the payload with `facade.sanitize`; Crossref is keyless. `_scopus_plan` (`:364-398`) probes
  `scopus.complete_view_entitled` (a bare `client.get`, not `send`) and counts it as one `lookup_requests`. The Scopus
  step passes `CONNECTORS["scopus"].api_key() or ""`, so a key removed after planning sends with an empty header.
- `workflow/flow.py:1658-1724`: `_chain_requests_left`, `_chain_requests`, `_chain_request`: per attempt
  `add_usage("chain_requests")`, then `left = max - used`, `retries = min(PROVIDER_WAIT[effort], left)`, call the
  helper inside `fetch_module.host_gate(openalex.WORKS_URL)`, add `outcome.retries`; a transient `failed/before_send` is
  resent only while `_chain_requests_left`. `_record_chain` (`:1726-1787`) sanitizes `raw_payload` with the snapshotted
  key, but not record `raw`; every returned record is written (no identity admission); `search_runs.connector_json`
  stays NULL; `unresolved` backward ids come from `outcome.records`. Forward pages continue from the previous step's
  stored `next_cursor` with no provenance check. `_continuation_error` (`:2276-2293`) is the discovery check.
- `workflow/watch/run.py:185-197`: the citing branch calls `openalex.citing_works(...)` directly, then admits,
  sanitizes and builds `facade.Dispatched` by hand with the unit's contract id and adapter revision (already checked
  equal to the current descriptor at `:150-153`). Watch accounting is the `GatedTransport` (`:42-57`), one
  `provider_requests` per actual HTTP send, independent of any collector.
- `workflow/store.py:911-922` `settle_usage` settles only `provider_requests`/`query_requests` and `provider_sends`.
- `api/app.py:920-937` `/api/connections` already projects `sorted(descriptor.capabilities)`; no web code reads it.
- Count and distribution probes (`flow.py:584`, `:1096`), the Scopus entitlement probe, PDF-location calls in
  `documents/acquisition.py` and Zotero are not connector capabilities in this batch.

## Owner-level decisions (agreed jointly in plan review with gpt-6.1-sol medium; the reviewer records it)

- **O1. `CONTRACT_ID` stays `deixis.scholarly_connector.v1`.** The v1 vocabulary already names the four
  capabilities and the v1 protocol already has `lookup`. The batch and citing request types and their optional
  protocols are additive; `ScholarlyConnector`'s methods, required fields and closed vocabularies do not change. A
  contract bump would refuse every stored discovery continuation and restart every watch baseline for no change in
  what a search sends or returns.
- **O2. No `adapter_revision` bump; a bounded amendment to the version rule instead.** The rule says capability
  semantics bump the revision. Binding an *existing* helper as a declared capability is exempt when (a) the helper is
  unchanged and every capability case gives identical HTTP requests, waits and adapter-level results directly and
  through the facade, and (b) every search request and outcome stays byte-identical (the 112-case freeze replays
  unchanged). The freeze's descriptors change only in `capabilities`. Any later change to what a bound capability
  sends or returns bumps `adapter_revision` as usual. Rejected alternative: bump OpenAlex 3→4, Semantic Scholar 2→3,
  Crossref 2→3, Scopus 2→3; that would refuse paused OpenAlex and S2 bulk discovery pages and restart OpenAlex watch
  baselines although no search changed.
- **O3. Separate observed-send counters.** Lookups add observed sends to run usage `lookup_sends`, chaining to
  `chain_sends`. `provider_sends` stays search-only so D199's `provider_sends <= provider_requests` still holds; the
  same holds per pair (`lookup_sends <= lookup_requests`, `chain_sends <= chain_requests`).
- **O4. A key-required lookup with no key sends nothing** (named change, D172's rule extended to lookup): the facade
  returns a `failed` answer with a `not_configured/before_send` outcome, no request, no usage beyond what decision 5
  says.
- **O5. Chain records pass the shared admission and record sanitization** (named change, D194 changes 3 and 4 applied
  to chaining, as the watch citing read already does): records without a usable identity are dropped and counted;
  record `raw` is sanitized with the operation's key.
- **O6. Chain cursor continuation checks recorded provenance** (new refusal, D174 4.1: a cursor belongs to the
  adapter revision that issued it). Chain rows now record `connector_json`, so a later revision change would
  otherwise continue a cursor silently.
- **O7. The watch citing read goes through the same capability dispatch**, with byte-identical stored rows; watch
  accounting stays the gated transport (stricter than settlement: it gates each actual send).
- **O8. Lookup answers are sanitized with the sent key** (named change, plan review r1). Payload sanitization alone
  leaves an echoed key in `LookupAnswer.abstract` (S2 copies the reply's abstract at `providers/lookup.py:143`, and
  `workflow/lookups.py:214` stores it as a passage) and in adapter-built error text such as Scopus's "answer names
  another DOI" (`lookup.py:210`). `dispatch_lookup` therefore also sanitizes `LookupAnswer` string fields
  (`abstract`, `paper_id`, every entry of `linked_dois` and `has_preprint`) and `outcome.error` with the sent key.
  `dispatch_citing` does not touch `outcome.error` (`common.send` already redacts HTTP error text, and a second pass
  is not idempotent: with a key equal to `redacted` it would turn `<redacted>` into `<<redacted>>` and break O7's
  byte-identical watch rows); `dispatch_search`'s output stays exactly as it is.

O1-O7 were agreed by gpt-6.1-sol medium in plan review round 1, O8 in round 2 and restricted to lookup dispatch in
round 3; O2 with the proviso that adapter equivalence is
kept apart from the named admission, redaction, accounting and refusal changes, and that OpenAlex, Semantic Scholar,
Crossref and Scopus keep revisions 3, 2, 2 and 2.

## Decisions

1. **Declarations live in the registry, not in provider branches.** Add to `registry.Connector` a field
   `capabilities: Mapping[str, CapabilityBinding]` (frozen dataclass: `call`, `max_batch`, `accepts_retry_allowance`,
   declared `options`). `call` is a registry-owned wrapper with one uniform signature per operation, so generic facade
   code never branches on a provider:
   - `doi_lookup`: `async call(client, identifiers: tuple[str, ...], api_key, contact_email, max_rate_limit_retries)
     -> tuple[dict[str, LookupAnswer], SearchOutcome]` (one answer per asked DOI). The Crossref and Scopus wrappers
     take exactly one identifier and wrap their single answer; the S2 wrapper passes the tuple through. Crossref's
     wrapper ignores `api_key` (keyless, `key_env` None) and calls the helper without a retry argument.
   - `id_lookup`: `async call(client, identifiers, api_key, contact_email, max_rate_limit_retries) -> SearchOutcome`.
     The facade derives per-id answers generically: `found` when a record's `provider_record_id` equals the asked id,
     `not_found` when the outcome is `completed`/`zero_results` without it, `failed` otherwise. Adapter-level methods
     derive them from the returned records; `dispatch_lookup` recomputes them from the admitted records.
   - `citing_works`: `async call(client, work_id, cursor, limit, api_key, contact_email, max_rate_limit_retries,
     **options) -> SearchOutcome`.
   A wrapper that does not accept a retry allowance gets `None` only (a non-None value is a `ContractViolation`
   before send). For every wrapper, an allowance of `None` means the helper keyword is omitted, so the helper's
   default applies (passing `None` through would reach `retries < None` in `common.send`); the reservation then uses
   `MAX_RATE_LIMIT_RETRIES`, the helpers' default. Bind exactly: Crossref `doi_lookup` → `lookup.crossref_work` (max_batch 1, no
   retry allowance: `None` only, the helper's default 2 applies); Semantic Scholar `doi_lookup` →
   `lookup.semantic_scholar_batch` (max_batch 500, the documented endpoint limit); Scopus `doi_lookup` →
   `lookup.scopus_abstract` (max_batch 1); OpenAlex `id_lookup` → `openalex.works_by_ids` (max_batch
   `openalex.MAX_IDS_PER_REQUEST`) and `citing_works` → `openalex.citing_works` (cursor paging, `per_page <=
   openalex.MAX_RESULTS`, options `sort: str` and `publication_date: bool`). bioRxiv and the other five declare
   nothing beyond search. `descriptor_for` derives `capabilities = {"search"} | set(connector.capabilities)` with no
   provider branch. Remove `UNBOUND_HELPERS` (registry and facade); tests iterate the bindings instead. Lookup
   helpers and `openalex.py` stay unchanged.
2. **Contract types (additive, O1).** In `contract.py`: frozen `LookupBatchRequest(operation, identifiers:
   tuple[str, ...], max_rate_limit_retries: int | None = None)` validating at construction a `doi_lookup`/`id_lookup`
   operation, an exact nonempty tuple of nonempty strings (repeated identifiers are allowed and sent at their own
   positions, as S2's repeated-DOI binding requires; nothing is deduplicated), and the B3a retry rule (None or exact
   nonnegative int); frozen `LookupBatchOutcome(operation, answers: Mapping[str, LookupAnswer], outcome:
   SearchOutcome)`; frozen `CitingWorksRequest(work_id, limit, cursor=FIRST_PAGE, max_rate_limit_retries=None,
   options=Mapping)` requiring a nonempty string `work_id`, an exact positive int `limit` (the binding caps it at its
   per-page maximum by clamping, exactly as `openalex.citing_works` does today at `openalex.py:188`; a limit above
   `MAX_RESULTS` is clamped, not refused, unlike a lookup batch above `max_batch`, which is refused), a nonempty string `cursor` and read-only options; two
   `runtime_checkable` optional protocols `BatchLookupCapable` and `CitingWorksCapable`. `ScholarlyConnector` is
   unchanged. Align the version-rule docstrings at `contract.py:3-8` and `facade.py:1-24` with O2.
3. **Facade behavior.**
   - `CompatibilityConnector.lookup(LookupRequest)`: an undeclared operation (for example Crossref `id_lookup`,
     OpenAlex `doi_lookup`, anything on bioRxiv) returns `unsupported` with no request, answer or outcome, exactly as
     today. A declared one calls its binding with a one-identifier tuple and returns `LookupOutcome(status,
     operation, answer, outcome)` where status is that answer's `found`/`not_found`/`failed` (for `id_lookup` derived
     from the returned records as in decision 1; the record stays in `outcome.records`).
   - `lookup_batch(LookupBatchRequest, context)` and `citing_works(CitingWorksRequest, context)`: an undeclared
     operation, more identifiers than `max_batch`, a non-None retry allowance for a binding that does not accept one,
     or an undeclared or wrong-type option raises `ContractViolation` before any send and before any collector entry.
     Options are validated against the binding's declared options exactly as `search` validates endpoint options.
     The capability ceiling (S2 500) does not change the workflow's own S2 batch of 200 (`lookup.S2_LOOKUP_BATCH`).
   - These `CompatibilityConnector` methods return the adapter-level result: no admission, no sanitization. That is
     what decision 4 compares with the direct helper.
   - Key handling (O4): a connector with `key_required` and no key returns, for each asked identifier, a `failed`
     answer and a `not_configured/before_send` outcome without a request and without a collector entry.
   - Module functions mirroring `dispatch_search`: `dispatch_lookup(provider_id, operation, http, identifiers,
     api_key, contact_email, max_rate_limit_retries=None) -> DispatchedLookup` and `dispatch_citing(provider_id, http,
     work_id, cursor, limit, api_key, contact_email, max_rate_limit_retries=None, **options) -> Dispatched`. Each opens
     `common.collect_transport()` around the call and returns its entries. Application post-processing, after the
     adapter-level call: records (id lookup, citing) are admitted with `usable_identity`; record `raw` and
     `raw_payload` are sanitized with the sent key; O8's answer and error fields are sanitized with it (lookup dispatch only). The provenance
     dict has the same keys and values as a search's (`contract_id`, `adapter_revision`, `query_rules_revision`,
     `payload`, `dropped_records`). `DispatchedLookup` carries `operation`, `answers`, `outcome`, `returned_count`
     (records before admission), `dropped_records`, `connector`, `transport`; `Dispatched.returned_count` already
     counts records before admission. Share one provenance helper with `dispatch_search`; `dispatch_search`'s output
     stays identical.
4. **Equivalence and named changes kept apart.** For every capability case (decision 10), the HTTP requests (method,
   URL, params, headers, body), waits and the adapter-level answers and outcome of the `CompatibilityConnector` call
   equal those of the direct helper call with the same arguments. The `dispatch_*` result is compared with an explicit
   projection: the direct result after admission and O8/payload/record sanitization. Identity rules stay: S2
   identifier binding (D194), Scopus's own-DOI rule, Crossref 404 as `not_found`, OpenAlex batching of up to 100 ids.
   `unsupported` is never written to `record_lookups`.
5. **Lookup accounting: reserve, then settle (the D199 rule).** In the three lookup steps, call
   `facade.dispatch_lookup` instead of the helpers. Per dispatch: reserve `R = 1 × (1 + allowance)` on
   `lookup_requests` before the call (allowance: the step's `waits` for S2 and Scopus, `MAX_RATE_LIMIT_RETRIES` for
   Crossref); after it, in one transaction, add `attempts − R` to `lookup_requests` and `sends` to `lookup_sends`,
   where `attempts = Σ entry.attempts` and `sends = Σ entry.sends` over the dispatch's collector entries. An O4
   refusal has no entries, so it reserves and then refunds all of `R` (net zero requests, zero sends). Generalize
   `Store.settle_usage` with keyword arguments for the two usage keys (defaults keep D199's behavior and every
   existing caller unchanged). Settled `lookup_requests` equals today's `1 + retries` on every sequence that today
   sends (connect failure: attempt charged, no send); an adapter exceeding its declared cost is charged and recorded
   as `over_reservation`. Each lookup step's output gains `transport` as in D199 (`reserved`, `attempts`, `sends`,
   `over_reservation` when nonzero, `dispatches` with their subrequests), accumulated over every dispatch of the step
   and kept on every exit; a step that dispatched nothing omits it. D199's limits are inherited unchanged: a crash in
   flight keeps the reservation; an adapter that raises keeps its reservation and loses its collected entries
   (ledger d). Persistence of the trace: each settlement and the merge of the accumulated `transport` into the step's
   stored output (keeping its other fields) happen in **one** transaction (`storage.db.transaction` joins an outer
   transaction; no `await` inside it), immediately after the dispatch returns and before any payload write, answer
   write or backoff. A later payload-write failure, exception or crash therefore leaves the trace of every settled
   dispatch on the step, and a crash can never leave settled counters without their trace. The accumulator starts
   from the step's stored `output.transport` when one exists (a resumed chunk appends only its new dispatches), and
   every `finish_step` output, including the S2 step's zero-asking exit and chunks whose remaining records were
   already answered, carries the accumulated `transport` forward instead of dropping it. Payload files, each sanitized exactly once: S2 writes the facade's
   sanitized payload (old code sanitized the raw payload once with the same key and function, so bytes are equal);
   Scopus builds its DOI-keyed chunk envelope from the facade's already-sanitized per-reply payloads and then sanitizes
   only the envelope's top-level keys with the chunk's snapshotted key, replacing the whole envelope with
   `{"<omitted>": "secret_key_collision"}` when redacted keys collide. That equals today's single recursive
   `sanitize(envelope)` byte for byte, because `sanitize` cleans each subtree independently; never apply `sanitize` a
   second time to an already sanitized value (it is not idempotent: a key equal to `redacted` turns `<redacted>` into
   `<<redacted>>`). Crossref's keyless payload files stay byte-identical. The Scopus entitlement probe
   stays direct, counted as one `lookup_requests` as today, and is outside `lookup_sends` (recorded limit). The Scopus
   step keeps its one key snapshot per chunk (`lookups.py:409`) but passes the real value (`api_key()`, possibly
   None) instead of `or ""`, so O4 applies to the whole chunk; a key removed during a chunk affects the next chunk,
   not the remaining requests of the current one.
6. **Chaining through the capability.** `_chain_request` calls `facade.dispatch_citing` (forward) or
   `facade.dispatch_lookup(..., "id_lookup", ...)` (backward) inside the same host gate, with the snapshotted key.
   Accounting: before each attempt, `left = max_chain_requests − chain_requests`, `retries = max(0,
   min(PROVIDER_WAIT[effort], left − 1))`, reserve `R = 1 + retries` on `chain_requests`, dispatch with `retries`,
   then settle to attempts and add `chain_sends` in one transaction (same sums as decision 5). This gives today's
   settled totals and per-request retry allowance; the chain stays within `max_chain_requests` as long as each
   binding honors its declared cost, and an excess is charged and recorded as `over_reservation`. The transient
   resend rule stays (`_chain_requests_left`); the step's `transport` accumulates every dispatch, including transient
   resends, is merged into the step's stored output in the same transaction as each settlement (before the payload
   write and before any transient backoff, as in decision 5), and is written on succeeded and failed steps alike (the failed branch of `_record_chain`, `flow.py:1772-1776`,
   currently writes no step output and must). A nonzero drop count adds `dropped_records`. `_record_chain` writes the
   facade's admitted, sanitized records (O5) and payload (its own `facade.sanitize` call goes), `connector_json` from
   the dispatch on the chain's `search_runs` row (O6; flow-made outcomes keep NULL), keeps `error_kind` (D194), and
   computes backward `unresolved` from admitted records. Paging keeps using provider-returned counts (D194): the
   step output's `returned`, the row's `error_json.returned` and the `CHAIN_CITING_CAP` arithmetic in
   `_chain_requests` (`flow.py:1674-1680`) use `Dispatched.returned_count`, so dropped identities never cause an
   extra page; `passed_filter` counts admitted records.
7. **Chain continuation (O6).** Before forward page `n > 1` of a seed is sent, check the stored search row of page
   `n − 1` with the discovery rule (reuse `_continuation_error`; NULL means legacy and continues; malformed or missing
   → `connector_provenance_invalid`; unsupported contract or changed adapter revision → `adapter_revision_changed`).
   On refusal: finish page `n`'s step `failed` with that error code, no request, no usage, no `search_runs` row; that
   seed's forward read ends; the chain and the run go on (D18). `_chain_summary` reports these as
   `requests.continuation_refused` and leaves them out of `forward`, `backward` and `sent`.
8. **Watch citing read (O7).** Replace the hand-built path at `watch/run.py:185-197` with `facade.dispatch_citing(...,
   sort="publication_date:desc", publication_date=True)`. For the same transport replies the stored watch read rows,
   records, `connector_json` (including `sort_sent`), payload bytes and both digests, returned and dropped counts are
   byte-identical to bbcf575, for successful replies and for 401, exhausted 429 and malformed 200 replies (error
   text included). Watch accounting, gates, deadline and revision check are unchanged; the collector's
   entries are not used there. Touch nothing else in `workflow/watch/`.
9. **Version rule text.** Add O2's bounded amendment to `connector-onboarding.md` beside the B3a/B3b amendments, and
   to the onboarding gates: declare capabilities through `Connector.capabilities`; every capability request goes
   through `common.send`; supply capability conformance cases (decision 10).
10. **Registry-driven capability conformance.** In each `tests/fixtures/connectors/conformance/<pid>.json`, add
    SYNTHETIC `capability_cases: {capability: [cases]}` for every declared lookup or citing capability and point
    `capabilities[capability]` proofs at them; `check_coverage` checks proofs against capability cases (search proofs
    keep pointing at endpoint cases) and that undeclared capabilities stay `"unsupported"`. Required per declared
    capability: `positive`, `not_found` (lookups) or `empty` (citing), `http_401`, `http_500`, `rate_unstated` (429
    then 200), `rate_exhausted`, `quota`, `connect`, `read_timeout`, `key_echo` where the connector has a key, and
    malformed 200 replies enumerated per helper with their current outcome: non-JSON, wrong root type, wrong container
    type, and for S2 a wrong-length list and a matched answer whose `abstract` is not a string. Where today's helper
    raises (the S2 matched-answer parser calls `.strip()` outside its bounded catch, `providers/lookup.py:88-95`,
    `:135-148`), the case characterizes the exception directly and through the facade, the workflow keeps the
    reservation (ledger d), and the report and onboarding ledger record it as a limit; do not convert the exception
    under O2's equivalence exemption; plus S2 `reordered` and `repeated_doi`, Scopus `other_doi`, Crossref `http_404`, OpenAlex
    citing `next_cursor` and `last_page`, OpenAlex id lookup `partial` (some ids unresolved) and `bad_identity` (a
    record whose id is unusable is dropped and counted). A registry-driven test replays every case directly and
    through the facade (single `lookup` where `max_batch` is 1 or for a batch of one, `lookup_batch`/`citing_works`,
    and `dispatch_lookup`/`dispatch_citing`). Two separate assertion stages: (a) the adapter-level results equal the
    direct helper's (unsanitized, unadmitted); (b) the `dispatch_*` results equal decision 4's projection and contain
    no synthetic key in collector entries, outcome text, answers, payload or records. For every case that returns,
    collected `Σ attempts` equals the mock transport's request count, `Σ sends` equals it minus scripted connect
    failures, `Σ retries == outcome.retries`, `len(entries) == 1`; a case that raises asserts its exception and the
    requests it sent. Every retry-capable binding also replays 429 then 200 with the allowance omitted (helper
    default). S2 repeated identifiers: equal, conflicting and null repeated answers, wire positions kept, batch size
    counted with repeats. A synthetic registry-only connector declaring `doi_lookup` with a binding that sends through `send`
    passes through generic facade code with no provider branch. Boundary: a batch of exactly `max_batch` identifiers is
    accepted and sends one scripted request; a citing limit of `MAX_RESULTS + 1` is clamped and sends. Validation
    cases, each refused with zero requests and no collector entry: `max_batch + 1` identifiers for every binding;
    an empty tuple, empty and non-string identifiers; empty or non-string `work_id`; non-int, bool and nonpositive `limit`;
    non-string cursor; negative, bool and non-int retry allowances; a non-None allowance on Crossref; undeclared and
    wrong-type options. For every connector and every undeclared operation:
    single `lookup` is `unsupported` with zero requests; `lookup_batch`/`citing_works`/`dispatch_*` raise
    `ContractViolation` with zero requests and no collector entry. Report case counts. The existing 566 search cases
    stay as they are.
11. **Freeze.** Regenerate `tests/fixtures/connectors/baseline.json` with the documented command. Only
    `descriptors[*].capabilities` of OpenAlex, Semantic Scholar, Crossref and Scopus may change; prove it in the report
    with a JSON comparison that deletes those four fields and finds the files equal, and state the byte size and
    SHA-256. `query_baseline.json` stays byte-identical.
12. **Out of scope, recorded limits:** the OpenAlex count and distribution probes, the Scopus entitlement probe,
    acquisition's Crossref and CORE PDF-location calls, Zotero; `RetryPolicy` stays descriptive (ledger g); ledger d;
    OpenAlex ids are sent as stored (no id-shape validation in `works_by_ids`); no UI label for `lookup_sends` or
    `chain_sends`; live formats unmeasured.

Purity tests (plan review r1): `tests/test_connector_boundary.py:197` (cold import), `:223` (local purity) and
`tests/test_connector_contract.py:395-405` (registration purity) call `lookup` under a transport that forbids every
request. Split them: descriptor and access purity stay fail-closed for all ten; the zero-request lookup checks there run
only for undeclared operations; bound operations are covered by decision 10's scripted transports. Keep every
fail-closed network guard.

## Files

Allowed: `providers/contract.py`, `providers/facade.py`, `providers/registry.py` (capability bindings, removing
`UNBOUND_HELPERS`); `workflow/lookups.py` (the three lookup steps and the Scopus key snapshot); `workflow/flow.py`
limited to `_chain_requests_left`, `_chain_requests`, `_chain_request`, `_record_chain`, `_chain_summary` and imports
(`_continuation_error` may be reused, not changed); `workflow/store.py` (`settle_usage` keywords only);
`workflow/watch/run.py` (the citing branch only); tests: a new `tests/test_capability_binding.py` (or a name you
choose), `tests/test_connector_boundary.py`, `tests/test_connector_contract.py` (coverage and ledger row),
`tests/test_connector_dispatch.py` (projection at `:712`, chain/lookup expectations), conformance fixtures, the freeze
via the regeneration command, and other existing tests only where a named change requires it (list each with the
reason). Docs: `docs/product/connector-onboarding.md` (preamble, gate 2, version amendment, unsupported paragraph,
ledger: row `b4_resume_lookup` owner becomes exactly `G1-F1 fixed (D201)` with the new evidence, and
`tests/test_connector_contract.py`'s pin of that cell changes with it; add rows for O4, O5, O6, O8 and the S2
malformed-answer exception limit),
`docs/product/p7-acceptance-record.md` (items 3 and 6, section 3.4 capability table, section 7 G1-F1 row, section 8,
section 10's connectors row, line 101's freeze statement (it still says "unchanged since D179/D193", gives the old size and digest and says all ten
connectors are at revision 2; at bbcf575 the freeze has 112 cases, 412,913 bytes and OpenAlex at revision 3): keep the
historical B5 measurement labelled as such and add the regenerated G1-F1 freeze with its full size and SHA-256,
line 144's list of version amendments, and section 5's named-change ledger for O4, O5, O6 and O8; leave both
verdicts to the reviewer; the G1-F1 row is at `:168`), `docs/product/README.md:13` and
`docs/product/api-and-data.md:52-62` (the sentences saying the contract covers search only),
`docs/product/p7-coverage-verification.md` G1 row (Turkish).

Forbidden: migrations, `contracts/`, `methods/`, `domain/contracts.py`, provider modules (`lookup.py`,
`openalex.py`, `crossref.py`, `scopus.py`, `semantic_scholar.py` and the rest), model steps and every other part of
`flow.py` (parallel batch P9 RF), `api/app.py` and the watch scheduler or app lifespan (parallel batch P8 B6), the rest
of `workflow/watch/`, `apps/web` (parallel X05), `documents/`, `query_baseline.json`, `docs/decisions.md`,
`STATUS.md`.

## Tests that must fail on the old code (name each in your report with the old failure)

1. Descriptor capabilities per decision 1, `/api/connections` capabilities, bindings replacing `UNBOUND_HELPERS`.
2. Bound single lookups: Crossref found, 404 `not_found`, 500 `failed`; S2 single; Scopus found and other-DOI;
   OpenAlex id found and not found (old: `unsupported`). Undeclared operations stay `unsupported` with zero requests
   (preservation, passes on both).
3. Decision 10's capability conformance and equivalence matrix (interface failures on old code are not behavioral
   evidence; say which failures are which).
4. A static AST scan of `backend/deixis/workflow/` finds no call of the five bound helpers (old: lookups, flow and
   watch call them).
5. Lookup accounting: during flight the reservation is visible (block the mock transport on an event); S2 429 then 200
   settles `lookup_requests` 2 and `lookup_sends` 2; a connect failure 1 and 0; exhausted 429 retries; a transient
   failure then success inside a Crossref chunk of three with one 429 settles to today's count; atomic settlement
   (inject a failure, nothing half written); step `transport` record accumulated over the chunk and present on every
   exit; payload bytes unchanged for S2, Scopus and Crossref replies, including a Scopus envelope whose DOI keys
   collide after redaction (`secret_key_collision`, as today).
6. Scopus with the key removed after planning and before the chunk's snapshot sends nothing for the chunk, stores
   `record_lookups.status = 'failed'` for each asked record, finishes the chunk step `succeeded` (as every lookup
   step does whatever the source answered), and nets zero requests and sends after settlement (O4); assert all three; a key removed partway through a chunk leaves that chunk's remaining
   requests on the snapshotted key and the next chunk unsent. Trace persistence: a payload-write failure after a
   settled lookup and a chain stop during transient backoff leave the settled dispatches' `transport` on the step.
   Scopus envelope bytes, including a synthetic key equal to `redacted` (no double redaction).
6b. Accounting through the collector, not the outcome: synthetic capability bindings (a `doi_lookup` and a
   `citing_works`, registered only in the test's registry copy) that make two `common.send` calls each scripted 429
   then 200 and return a rebuilt outcome with `retries` reset to 0 are charged by the lookup step and by the chain
   for all four attempts, record four sends, `over_reservation` against their declared cost, and persist both
   subrequests in the step's `transport`. Report which old-code failures are interface failures and which are
   behavioral.
6c. Fault injection between settlement and the trace write rolls both back together; an interrupted Crossref or
   Scopus chunk resumed later appends to its stored `transport`; an S2 step whose batch was already answered keeps
   its stored `transport`.
6a. O8: an S2 reply whose abstract echoes the synthetic key and a Scopus other-DOI reply whose `prism:doi` echoes it:
   the stored passage text, `record_lookups` row and step output carry no key (old: the S2 passage stores it).
7. Chaining: `chain_sends` and reservation visibility; `max_chain_requests` never exceeded (existing caps tests keep
   their numbers); an unusable identity in a citing page is dropped and counted, never a source (O5); record `raw`
   echoing the key is sanitized; chain rows carry `connector_json`; a backward batch's dropped record counts as
   unresolved; with `CHAIN_CITING_CAP` and `CHAIN_CITING_PAGE` lowered and a citing page holding dropped identities,
   the requests sent and the cursors asked for are the same as with the identities usable; a failed chain step keeps
   its `transport` record.
8. Chain continuation: a forward page whose previous page recorded another adapter revision, or malformed provenance,
   sends nothing, fails with the code, the next seed is still read, the run is not paused, the summary reports
   `continuation_refused`; legacy NULL continues.
9. Watch citing: a spy shows `facade.dispatch_citing` is used, and a fixed synthetic citing transport gives stored
   watch reads identical to bbcf575's output (compare against values captured from `git show bbcf575:...` run in a
   temporary copy, or explain).
10. `tests/test_connector_contract.py` ledger pin and the existing unsupported-lookup tests updated together with the
    code; the freeze test passes with the regenerated descriptors.

Run in the sandbox: the new file, `tests/test_connector_boundary.py`, `tests/test_connector_contract.py`,
`tests/test_connector_facade.py`, `tests/test_connector_dispatch.py`, `tests/test_query_delegation.py`,
`tests/test_transport_accounting.py`, `tests/test_lookup_flow.py`, `tests/test_record_lookups.py`,
`tests/test_chaining_flow.py`, `tests/test_watch_*.py`. You cannot bind sockets; the reviewer runs the full pytest
outside the sandbox.

## Report

Write `/tmp/g1f1-impl-report.md`: changed files with line ranges; each decision and owner-level decision with where
it is implemented; every existing test you changed and why; each new test with the old-code failure you observed (run
new tests against a copy built with `git show bbcf575:<path>` into a temporary directory, not with stash or
checkout); capability case counts; the freeze comparison; focused test counts; anything you did not do or could not
verify.
