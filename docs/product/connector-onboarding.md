# Scholarly connector onboarding

The B1 boundary is `deixis.scholarly_connector.v1` in
[`contract.py`](../../backend/deixis/providers/contract.py). D174 Q1/Q2 restrict
registration to reviewed adapters in the codebase. Packaged builds cannot add
sources. No runtime import path, URL, key or API request can register code.
The compatibility facade exists, but application dispatch still uses the old
registry callables. G1 remains open; B1 is a synthetic behavior freeze.

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
endpoint, plus PubMed `efetch_malformed` after a successful ESearch. The only
intentional direct/facade exception difference is an unknown S2 endpoint:
module `ValueError` versus pre-send `ContractViolation`.

## Conformance mismatch ledger

All citations in this ledger are to the unchanged code on `1fb1743`.

| Item | Current evidence and consequence | Owner |
|---|---|---|
| a. Missing key on dispatch | `workflow/flow.py:2043-2048` counts before calling; `storage/migrations/0001_initial.sql:204` excludes `not_configured`. Four module guards return without sending; the generic guard and valid dispatched recording remain pending. | B2 |
| b. S2 batch identity | `providers/lookup.py:95` binds answers positionally after only a length check (`:89`); equal-length reordered answers can attach another record's evidence. | B4 |
| c. Limit presentation | `workflow/flow.py:2114` returns `provider_rate_limited` for both limit kinds; the step error at `:2111` lacks `error_kind`, although search-row `error_json` at `:2084` and pause detail at `:2115` preserve it. | B4 |
| d. Raising local errors | `providers/common.py:88-98`, `semantic_scholar.py:80-81,121-122` raise `ValueError` for bad offsets, unknown endpoints and `CUT`. B1 preserves those paths; converting them requires a named behavior change. | Unscheduled |
| e. Logical/transport accounting | `workflow/flow.py:2043,2052` counts one base send plus retries; `providers/pubmed.py:135,162` can send ESearch and EFetch, while `:158-160` returns empty results after one send. Kill-search reserves by declared cost (`flow.py:4656-4657`). | Q4 debt; target accounting batch not scheduled |
| f. Flow-only outcomes | `workflow/flow.py:4655` creates `transport_budget`; quota suppression at `:2040-2042` creates `rate_limited/before_send` without sending. These are workflow outcomes outside the adapter's production paths; `transport_budget` is excluded from its vocabulary. | B4 provenance; accounting enforcement remains Q4 debt |
| g. Descriptive retries | `providers/common.py:138-143`, `arxiv.py:91-95`, `semantic_scholar.py:93-95`, `serpapi.py:68-69` still set policy inside module calls. `RetryPolicy` describes them; it does not drive `send`. | B3a compatibility; policy-driven dispatch unscheduled |
| h. Closed admission | `common.schema.json:36-39`, migrations `0048_record_lookups_scopus.sql:5-6` and `0055_europepmc_pdf_provider.sql:8,25` close schema/persistence lists; `workflow/routing.py:88` admits unknown searchable sources as `no_route`. Registry insertion alone is insufficient. | B4 integration; each future connector's onboarding |
| i. Malformed 200 raises | The native wrong-root JSON fixture `[]` raises `AttributeError` at `providers/semantic_scholar.py:98,138` and `providers/ieee_xplore.py:83`; their catches (`:104,143`, IEEE `:87`) omit it. Both S2 endpoints and IEEE are frozen as exceptions, not zero results or `parse_error`. | B2 named parser fixes with regressions |
| j. PubMed EFetch quota | `providers/pubmed.py:170-177` copies failure fields except `error_kind`; the EFetch quota fixture returns `rate_limited` with `error_kind=None`. The run guard at `workflow/flow.py:2049-2050` therefore does not suppress later PubMed requests. Copy `fetch_outcome.error_kind` with a regression as a named one-line fix. | B2 |

The ten `non_json_200` cases return `parse_error`, including both S2 endpoints
and IEEE; their existing wrong-root `[]` exceptions remain item i, owned by B2.
PubMed's broken EFetch XML also returns `parse_error` (`providers/pubmed.py:178-183`)
and retains the successful ESearch payload and reported total. These eleven
added cases expose no new mismatch; no parser behavior was changed.

B1 fixes none of these behaviors. No live call, model call, service restart or
scientific validation is part of this freeze.
