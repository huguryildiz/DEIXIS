# Scholarly connector onboarding

The B1 boundary is `deixis.scholarly_connector.v1` in
[`contract.py`](../../backend/deixis/providers/contract.py). D174 Q1/Q2 restrict
registration to reviewed adapters in the codebase. Packaged builds cannot add
sources. No runtime import path, URL, key or API request can register code.
The compatibility facade validates request fields and declared option values
before send (B3a, D179), but application dispatch still uses the old registry
callables. G1 remains open; the equivalence evidence uses synthetic fixtures.

## Five onboarding gates

1. Specify endpoint, authentication, query syntax, paging, identities and limit
   evidence in the new provider module. Verify current compatibility against
   authoritative provider documentation in a separately authorized task; B1
   used no network and establishes no current provider truth.
2. Register the adapter in `backend/deixis/providers/registry.py:88` and supply
   default/endpoint metadata (`registry.py:25`, `registry.py:37`). Derive its
   descriptor through `facade.descriptor_for`; declare actual capabilities,
   retrieval lineage, host and request cost. Declare non-default retry/wait
   policy in `Connector.retry` (`registry.py:72`), using the provider's constants;
   `facade.descriptor_for` reads `common.send` defaults and merges those overrides
   without provider branches. Add managed keys if needed in
   `backend/deixis/credentials.py:39`; source keys remain `testable=False`
   (`credentials.py:36`). Do not emulate unsupported remote operations.
3. Check all admission surfaces: `providers/query_rules.py:13,46,191`,
   `providers/query_compiler.py:67,126,137`, `domain/rules.py:56,60`,
   `workflow/routing.py:88`, `contracts/research/common.schema.json:36`,
   `methods/deixis-research/SKILL.md:10`, `api/app.py:807-822`, and connection labels
   in `apps/web/src/labels.ts:206`. Lookup persistence has closed provider and
   status lists in `storage/migrations/0048_record_lookups_scopus.sql:5,6`;
   PDF persistence has closed lists in `0055_europepmc_pdf_provider.sql:8,25`.
   A new supported persistence route needs a new migration, never an edit to
   those migrations. Version required model contracts and update their methods,
   adapters and fixtures together. Unknown searchable sources route as
   `no_route`, so explicitly decide their SW admission and request cost.
4. Add native SYNTHETIC response files under `tests/fixtures/connectors/responses/`
   and replay scripts in `tests/connector_baseline.py`. Every registered
   provider/endpoint must have all required shapes; coverage fails for an
   unrepresented synthetic registration. Run `tests/test_connector_boundary.py`
   and the relevant integration tests with mocked HTTP, fake credentials,
   temporary storage and fail-closed network guards. B2 adds full conformance.
5. Record exact commands, results, mismatches and limits in `docs/decisions.md`
   before release admission. Synthetic checks establish application behavior.
   A live probe needs separate authorization; access and quota stay unverified
   until observed. B5 owns G1 acceptance and product-document wording.

Paths abbreviated as `providers/`, `workflow/`, `domain/`, `storage/` and `api/`
above are under `backend/deixis/`. Admission citations describe the inspected
`1fb1743` code; registry citations describe the B1 working tree.

## Version and unsupported rules

Change `CONTRACT_ID` only for a protocol method, required field or vocabulary
change. Bump `adapter_revision` for request, mapping, cursor, retry/wait or
capability semantics. Bump `QUERY_RULES_REVISION` for rendering or rule output.
Regenerating changed contract, adapter or query-rule semantics without the
relevant revision bump is a review failure. Added synthetic coverage and
library-default header normalization alone do not change those semantics;
verify that prior cases otherwise remain unchanged. An omitted endpoint means
the historical default. Incompatible descriptor contracts/revisions raise
`ContractViolation`; stored-operation
revision enforcement belongs to B4, with no page-one restart or provider swap.

B3a's bounded amendment exempts facade enforcement, before any send, of an
input constraint already declared by the descriptor: option names, value types
and values, and request field types. It also expressly adopts one facade rule
not previously declared by a descriptor: `max_rate_limit_retries=None` means
omission; otherwise it must be an exact nonnegative `int`. Previously `-1` was
forwarded and `common.py:198` read it as no retries. These refusals do not require
an `adapter_revision` bump only if registry callables stay unchanged and every
still-accepted request produces identical requests and outcomes. Any change to
what an accepted request sends or returns still requires the bump. B3a changes
neither `CONTRACT_ID` nor `QUERY_RULES_REVISION`, and retains the byte-identical
111-case freeze. gpt-6.1-sol medium accepted this alternative to bumping affected
adapter revisions in plan review round 1 (D179).

All B1 facades declare only `search`. Lookup returns `unsupported` without a
request, answer or `SearchOutcome`. It is neither `failed` nor `zero_results`
and is never persisted to `record_lookups`. Existing helper names are recorded
in `facade.UNBOUND_HELPERS` for B4; they are not bound capabilities.

Explicit regeneration command from the repository root:

```sh
PYTHONPATH=backend:. UV_CACHE_DIR=/tmp/deixis-uv-cache .venv/bin/python tests/connector_baseline.py --write
```

Tests read the freeze; they do not regenerate it. The frozen descriptors pin
metadata independently of `reading()`. Replays compare HTTP requests, waits,
normalized records, canonical payload/record hashes and exceptions.
Library-default headers are normalized only for the HTTPX default user-agent:
`python-httpx/<version>` replaces its installed version. Custom user-agents and
all other headers retain their values, apart from synthetic-key redaction.
The freeze requires `non_json_200` (`<SYNTHETIC not json`) at every JSON search
endpoint, plus PubMed `efetch_malformed` after a successful ESearch. Within the
111 frozen cases, the only intentional direct/facade exception difference is an unknown S2 endpoint:
module `ValueError` versus pre-send `ContractViolation`.
The facade separately refuses invalid limit, query and cursor types, unknown
endpoints, undeclared options, and (B3a) invalid option value types/values and
invalid `max_rate_limit_retries`, all before any request.

## Conformance mismatch ledger

B1 observations below refer to `1fb1743`; rows marked B2 fixed cite the current
B2 tree. B2 synthetic conformance does not verify provider documentation.

| Item | Current evidence and consequence | Owner |
|---|---|---|
| a. Missing key on dispatch | B2 fixed: `workflow/flow.py:2044-2047` snapshots the key before quota/accounting; `:2080-2087` records a failed step only; `:4668-4671` guards kill-search before reservation. No migration or `search_runs` row for missing configuration; other unsent outcomes retain their rows. | B2 (D178) |
| b. S2 batch identity | `providers/lookup.py:95` binds answers positionally after only a length check (`:89`); equal-length reordered answers can attach another record's evidence. | B4 |
| c. Limit presentation | `workflow/flow.py:2114` returns `provider_rate_limited` for both limit kinds; the step error at `:2111` lacks `error_kind`, although search-row `error_json` at `:2084` and pause detail at `:2115` preserve it. | B4 |
| d. Raising local errors | `providers/common.py:88-98`, `semantic_scholar.py:80-81,121-122` raise `ValueError` for bad offsets, unknown endpoints and `CUT`. B1 preserves those paths; converting them requires a named behavior change. | Unscheduled |
| e. Logical/transport accounting | `workflow/flow.py:2043,2052` counts one base send plus retries; `providers/pubmed.py:135,162` can send ESearch and EFetch, while `:158-160` returns empty results after one send. Kill-search reserves by declared cost (`flow.py:4656-4657`). | Q4 debt; target accounting batch not scheduled |
| f. Flow-only outcomes | `workflow/flow.py:4655` creates `transport_budget`; quota suppression at `:2040-2042` creates `rate_limited/before_send` without sending. These are workflow outcomes outside the adapter's production paths; `transport_budget` is excluded from its vocabulary. | B4 provenance; accounting enforcement remains Q4 debt |
| g. Descriptive retries | B3a compatibility measured (D179): `tests/test_connector_facade.py:176,199,218` compare omitted retry allowances, retry statuses (including rejected 406) and all four HTTPX timeout fields for every provider/endpoint, direct and facade, including both PubMed requests. `providers/common.py:138-143`, `arxiv.py:91-95`, `semantic_scholar.py:93-95`, `serpapi.py:68-69` still set policy inside module calls. `RetryPolicy` describes them; it does not drive `send`. | B3a compatibility fixed (D179); policy-driven dispatch unscheduled |
| h. Closed admission | `common.schema.json:36-39`, migrations `0048_record_lookups_scopus.sql:5-6` and `0055_europepmc_pdf_provider.sql:8,25` close schema/persistence lists; `workflow/routing.py:88` admits unknown searchable sources as `no_route`. Registry insertion alone is insufficient. | B4 integration; each future connector's onboarding |
| i. Malformed 200 raises | B2 fixed: narrow object/list/item checks and bounded catches in each search parser (`providers/semantic_scholar.py:98,142`, `ieee_xplore.py:83`, `openalex.py:150`, `crossref.py:96`, `scopus.py:100`, `core.py:88`, `serpapi.py:77`, `pubmed.py:151`); XML root checks at `arxiv.py:100`, `pubmed.py:122`. Native malformed shapes return `parse_error`, without mapping or request changes. | B2 (D178) |
| j. PubMed EFetch quota | B2 fixed: `providers/pubmed.py:183` copies `fetch_outcome.error_kind`; `tests/test_connector_contract.py::test_pubmed_efetch_quota_stops_later_searches` proves later dispatch sends nothing. Discovery's one-base-request accounting remains item e. | B2 (D178) |
| cursor_empty. Empty/non-string cursor | B2 fixed: `providers/openalex.py:159-160` and `semantic_scholar.py:151-152` return None for empty/non-string tokens; bioRxiv inherits OpenAlex. Relevance offsets remain numeric and S2 CUT remains separate. | B2 (D178) |
| header_wait. Header secrecy and invalid waits | B2 fixed: `providers/common.py:180` redacts allowlisted values using only the operation's supplied credential; `:223` rejects negative and non-finite Retry-After. Keyless operations have no credential to redact. | B2 (D178) |
| k. Empty object / absent or null result container | Characterization only: `{}` is `zero_results` for SerpApi/default and S2/bulk; absent or explicit-null containers are `zero_results` for S2/default, S2/bulk, IEEE/default, Scopus/default, SerpApi/default and PubMed/default. OpenAlex/default, bioRxiv/default, Crossref/default and CORE/default still return `parse_error` for null, as their previous parsers did. Ten `container_null` fixtures pin these outcomes alongside the eight accepted empty-object/absent cases. Other malformed container types remain rejected. This preserves prior parser behavior and establishes no provider-documented empty-result syntax. | Unscheduled; needs provider documentation |
| l. Successful-body key echo | OpenAlex `raw_payload` and record `raw` retain an injected `results[0].SYNTHETIC_nested.key` on `5990b02`. B2 tracks the reproduction in `PENDING_B4` and runs no leak assertion. Design amendment: B4 gains a third named behavior change, sanitizing both representations before persistence and hashing the sanitized payload. Agreed with gpt-6.1-sol medium in plan-review round 2. | B4 |
| identity_openalex | Null/empty/numeric/object id becomes `None`, empty, numeric text or object text (`providers/openalex.py:80`); `IDENTITY_KNOWN_MISMATCHES` pins four cases. | B4 |
| identity_biorxiv | The same four identity shapes inherit OpenAlex stringification. Same retrieval lineage, not independent evidence. | B4 |
| identity_semantic_scholar | Null/empty/numeric/object paperId stringifies (`providers/semantic_scholar.py:54`) on both endpoints; eight characterization cases, with both records inside the bulk read limit. Missing identity fails parsing. | B4 |
| identity_crossref | Missing/null/empty DOI without a URL becomes `None` text (`providers/crossref.py:53`); three characterization cases. Number/object DOI now raises caught AttributeError and returns `parse_error` under decision 6. | B4 |
| identity_arxiv | Missing/null/empty Atom id becomes an empty provider record ID (`providers/arxiv.py:47,56`); three characterization cases. XML has text/elements rather than JSON scalar types; JSON number/object type cases are inapplicable here. | B4 |
| identity_ieee_xplore | Missing/null/empty article_number becomes empty; number/object stringifies (`providers/ieee_xplore.py:39`); five characterization cases. | B4 |
| identity_scopus | Missing/null/empty dc:identifier without eid becomes empty; number/object stringifies (`providers/scopus.py:38`); five characterization cases. | B4 |
| identity_core | Missing/null/empty id becomes empty; number/object stringifies (`providers/core.py:43`); five characterization cases. Valid numeric CORE identities remain usable under the B4 admission amendment; the native positive fixture is already numeric. | B4 |
| identity_serpapi | Missing/null result_id becomes `None` text; empty stays empty; number/object stringifies (`providers/serpapi.py:38`); five characterization cases. | B4 |
| scopus_count_unmapped. Unmapped count | Scopus's STANDARD mapping does not read `citedby-count`; `ProviderRecord.cited_by_count=None` means unknown, including when the synthetic body supplies zero. Group 3's zero-preservation rule applies only where the adapter maps a count. The `counts_zero` case asserts None; adding the mapping is an enhancement, not a defect. No mapping change in B2. | Unscheduled enhancement |
| pubmed_scan. Source-owned classification copy | Round 1 fixed: exactly one `SCAN_ALLOWLIST` entry in `tests/test_connector_boundary.py` permits `fetch_outcome.error_kind`, because EFetch copies the already-classified `SearchOutcome.error_kind` unchanged. Other unresolved expressions still fail closed. | B2 (D178) |
| option_types. Value-type validation | B3a fixed (D179): `providers/facade.py:94-104` validates exact option types, declared values and an exact nonnegative retry allowance before send. `tests/test_connector_facade.py:266` covers every declared option, explicitly including integer 17 for OpenAlex reference_count/references and S2 bulk sort, with ContractViolation and zero requests; exact str-subclass and synthetic enumerated-value cases are included. `PENDING_B3A` is closed; direct registry behavior stays unchanged. | B3a fixed (D179) |
| pause_text. Missing configuration label | `apps/web/src/labels.ts:32-71` has no `provider_not_configured` pause text; the fallback displays the raw code. No web edit is authorized in B2. | Next web batch |
| b4_merge_version | Section 8.1 records/integration: temp-store merge/version through the dispatched facade. Existing registry/store tests are separate evidence. | B4 |
| b4_resume_paging | Section 8.1 paging: resumed paging through the dispatched facade. | B4 |
| b4_resume_lookup | Section 8.1 paging/integration: resumed lookup through the dispatched facade. | B4 |
| b4_payload_write | Sections 7 and 8.1 integration: failed payload write publishes no source/step success. | B4 |
| b4_limit_provenance | Sections 6.2 and 8.1 errors: quota versus temporary limit in step error and pause reason. | B4 |
| b4_s2_binding | Sections 4 and 8.1 identity: equal-length reordered S2 batches bind by externalIds, not position. | B4 |
| b4_stored_revision | Sections 9 and 8.1 integration: incompatible stored adapter revision refuses visibly. | B4 |

Round 1 owner-level dispositions 1-4 were agreed jointly by reviewer Claude
Opus 5.5 and gpt-6.1-sol medium, as recorded in D178.
All 42 `IDENTITY_KNOWN_MISMATCHES` characterizations belong to B4. The B4
design amendment adds identity admission as its fourth named behavior change:
drop and count a record without a usable provider identity rather than admit
it. Define usability per provider; valid numeric native identities such as
CORE's remain valid. Stringification alone is not a defect; empty identities,
`"None"` and stringified objects are unusable. G1 cannot be accepted until
this gate passes. These current-outcome characterizations do not imply that
all 42 shapes must be rejected.

The B2 suite is registry-driven. Identity and k characterizations are not
conformance claims; option value-type validation is deferred to B3a. B2 changes
five behaviors separately from the suite. The B1 freeze retains revision 2 for
all ten existing connectors; new connectors default to revision 1. Facades
remain unused by workflow dispatch. No live call, model call, service restart
or scientific validation is part of this evidence; G1 remains open.
