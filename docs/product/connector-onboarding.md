# Scholarly connector onboarding

The B1 boundary is `deixis.scholarly_connector.v1` in
[`contract.py`](../../backend/deixis/providers/contract.py). D174 Q1/Q2 restrict
registration to reviewed adapters in the codebase. Packaged builds cannot add
sources. No runtime import path, URL, key or API request can register code.
The compatibility facade validates request fields and declared option values
before send (B3a, D179) and delegates query rendering/rules to registry declarations
(B3b, D193), and application search dispatch now uses the facade (B4, D194). Admission and
payload sanitization run after the equivalent adapter call; stored page revisions
are checked before continuation. G1 is accepted with conditions for the search capability
(B5, D196, [acceptance record](../../.local/docs/archive/p7/p7-acceptance-record.md)). G1-F1 binds existing DOI
lookups (Crossref, Semantic Scholar, Scopus), OpenAlex ID lookup and citing reads,
including the watch citing read. The implementation and equivalence evidence use
synthetic fixtures (D201).

## Five onboarding gates

1. Specify endpoint, authentication, query syntax, paging, identities and limit
   evidence in the new provider module. Verify current compatibility against
   authoritative provider documentation in a separately authorized task; B1
   used no network and establishes no current provider truth.
2. Register the adapter in `backend/deixis/providers/registry.py:88` and supply
   default/endpoint metadata (`registry.py:25`, `registry.py:37`). Derive its
   descriptor through `facade.descriptor_for`; declare lookup and citing bindings
   through `Connector.capabilities` with their batch ceiling, retry-allowance support
   and typed options. Declare retrieval lineage, host and request cost. Every HTTP request of an adapter capability
   must go through `providers/common.py::send`; the registry-driven conformance
   replay compares collected attempts and sends with its mock transport and treats
   bypassing `send` as a conformance failure. Supply `capability_cases` and proofs
   for every declared lookup or citing operation, including direct/adapter equivalence,
   dispatch admission/redaction, errors, malformed replies, ceiling and zero-request
   refusal cases (`tests/test_capability_binding.py`). Declare non-default retry/wait
   policy in `Connector.retry` (`registry.py:72`), using the provider's constants;
   `facade.descriptor_for` reads `common.send` defaults and merges those overrides
   without provider branches. Add managed keys if needed in
   `backend/deixis/credentials.py:39`; source keys remain `testable=False`
   (`credentials.py:36`). Do not emulate unsupported remote operations.
3. Declare a display name and default/endpoint `query_syntax` in
   `providers/registry.py:36,76,77`; `resolve_query_syntax` (`registry.py:142`)
   refuses missing declarations. Reuse pure kinds in `providers/query_rules.py:219`;
   construction checks their vocabularies and unused parameters (`query_rules.py:235`).
   Add query freeze coverage in `tests/query_baseline.py:90` and
   `tests/test_query_delegation.py:37`. `NAMES` is a compatibility dictionary,
   not an admission surface. Check compiler delegation/allocation
   (`providers/query_compiler.py:70,106,122`) and facade rendering/rules
   (`providers/facade.py:126,130`), plus `domain/rules.py:56,60`,
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
   until observed. B5 (D196) recorded G1 acceptance and the product-document wording.

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
`ContractViolation`. B4 writes contract, adapter and query-rule revisions to
`search_runs.connector_json` for dispatched searches. Before continuing from the
last succeeded page, SQL NULL retains legacy compatibility; malformed provenance
or a missing search row refuses with `connector_provenance_invalid`, and a changed
adapter revision or unsupported contract refuses with `adapter_revision_changed`.
The next page fails without a send, usage, search row, page-one restart or provider
swap. Query-rule revision is recorded, not compared. Kill-search is terminal and
records no `connector_json`. These application checks change no adapter revision.

P8 B5 adds optional OpenAlex `sort` and `publication_date` search options and
bumps its adapter revision from 2 to 3. Default requests and outcomes retain the
prior replay domain unchanged. A discovery query paused under revision 2 refuses
its next OpenAlex page with `adapter_revision_changed`, without a send; additive
options are not exempted from the version rule. bioRxiv remains at revision 2
with no new declared options. The freeze adds one `sorted_first_page` case,
replayed directly and through the facade, beyond the unchanged required shapes.

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

B3b's bounded amendment exempts the intentional refusal, before rendering or
checking, of an endpoint the connector does not declare or a provider the registry
does not hold from a `QUERY_RULES_REVISION` bump. This requires byte-identical
rendering, written counts and validation for every registered provider with None
or a declared endpoint, and byte-identical module-level rule outputs for every
input. Any other rendered-query or issue-list change still requires the bump.
The module-level rule functions retain their historical lenient endpoint behavior;
compiler rendering and the facade resolve strictly. gpt-6.1-sol medium agreed to
this amendment in plan review round 1 (D193). The query freeze retains the old
undeclared-input outputs separately from its unchanged replay domain.

G1-F1's bounded amendment exempts binding an existing, unchanged helper as a declared
capability from an `adapter_revision` bump only when every capability case has
identical HTTP requests, waits and adapter-level results directly and through the
facade, and all 112 search replays remain unchanged. Only the four affected
descriptors' capabilities change in the search freeze. OpenAlex stays at revision 3;
Semantic Scholar, Crossref and Scopus stay at revision 2. Any later change to what
a bound capability sends or returns requires the usual bump. The additive batch
and citing types leave the v1 required protocol and vocabularies unchanged, so
`CONTRACT_ID` stays `deixis.scholarly_connector.v1` (O1/O2, D201).
Admission, redaction, accounting and continuation refusal are separately named
application changes, not adapter-equivalence claims.

Single lookup returns `unsupported` without a request, answer or `SearchOutcome`
only for an undeclared operation. It is neither `failed` nor `zero_results` and is
never persisted to `record_lookups`. Unsupported batch/citing dispatch raises
`ContractViolation` before send. Bound DOI lookups are Crossref (one), Semantic
Scholar (up to 500, with the workflow retaining batches of 200) and Scopus (one);
OpenAlex binds ID batches (up to 100) and cursor-paged citing works (clamped to 200
per page, `openalex.MAX_RESULTS`). Other connectors retain search alone. Chain
continuation records and checks the same provenance as discovery; legacy SQL NULL
continues.

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
| watch_options. Optional OpenAlex date sort | P8 B5 declares `sort` and `publication_date`, adapter revision 3. `test_watch_old_entrypoints` checks direct requests and facade admission; `test_connector_boundary` replays all prior requests/results unchanged and the extra sorted-page case; option-type conformance iterates both new declarations. `test_watch_check::test_discovery_revision_two_continuation_refused_after_watch_adapter_bump` proves the revision-2 continuation refusal. No provider probe. | P8 B5 (D186) |
| a. Missing key on dispatch | B2 fixed: `workflow/flow.py:2044-2047` snapshots the key before quota/accounting; `:2080-2087` records a failed step only; `:4668-4671` guards kill-search before reservation. No migration or `search_runs` row for missing configuration; other unsent outcomes retain their rows. | B2 (D178) |
| b. S2 batch identity | `providers/lookup.py::semantic_scholar_batch` binds normalized DOI/ArXiv identifiers regardless of position. Repeated DOI request positions share an answer when all answers naming that identifier are JSON-equal; conflicting answers fail all its positions. Unbound answers fail, and only order-consistent nulls are not_found. `test_connector_dispatch::test_s2_binding` includes four repeated-DOI cases; `test_s2_workflow_reordered_abstracts` exercises persistence. | B4 fixed (D194) |
| c. Limit presentation | Search and chain row/step errors retain error_kind; kill-search step errors retain it. Quota pauses as provider_quota_exhausted; temporary limits keep provider_rate_limited, with rate_limited status for both. Synthetic discovery and suppression: `test_connector_dispatch::test_limit_discovery_and_suppression`. | B4 fixed (D194) |
| d. Raising local errors | Local ValueError conversion remains unscheduled. A removed endpoint in paged reading raises KeyError before usage; S2 kill-search reserves first, then the facade raises ContractViolation (a ValueError subclass). Both accounting paths are pinned in `test_connector_dispatch`. | Unscheduled |
| e. Logical/transport accounting | `common.collect_transport` and `facade.dispatch_search` retain every `send` subrequest independently of adapter outcomes. Discovery reserves declared worst-case cost, then `Store.settle_usage` atomically settles run/query counts to attempts and adds observed `provider_sends`; kill-search keeps reservations and charges excess. PubMed empty results observe one send; EFetch failure retains completed ESearch provenance. `test_transport_accounting` covers stages, in-flight reservations, atomic settlement, the discovery bound `share - 1 + R`, and excess cost; `test_connector_contract::test_conformance_case` checks all 566 cases directly and through dispatch. | P7-F2 fixed (D199) |
| f. Flow-only outcomes | Missing configuration, quota suppression, continuation refusal and transport_budget dispatch nothing and add no usage. Wholly unsent operations omit transport. A later refusal retains earlier dispatches in the same operation's step output; discovery carries the record through `_PageRead` to the ordered writer. `test_transport_accounting::test_missing_key_after_dispatch_keeps_trace_on_failed_page`, `test_kill_later_refusal_keeps_earlier_dispatch` and `test_wholly_unsent_discovery_has_no_transport_or_usage` pin these boundaries. No migration or connector_json change. | P7-F2 fixed (D199) |
| g. Descriptive retries | D179 descriptor/module agreement tests remain the guard. B4 forwards the unchanged flow retry allowance; RetryPolicy does not drive send. Policy-driven dispatch would require provider-module changes and remains unscheduled (D194 decision 8). | B3a compatibility fixed (D179); policy-driven dispatch unscheduled |
| h. Closed admission | `test_connector_dispatch::test_synthetic_registry_dispatch_and_record` proves registry-only synthetic search dispatch and recording without a provider branch. Closed model schemas, lookup/PDF persistence and unknown-source routing still require each future connector's onboarding; this synthetic search does not open them. | B4 integration fixed (D194); each future connector's onboarding |
| i. Malformed 200 raises | B2 fixed: narrow object/list/item checks and bounded catches in each search parser (`providers/semantic_scholar.py:98,142`, `ieee_xplore.py:83`, `openalex.py:150`, `crossref.py:96`, `scopus.py:100`, `core.py:88`, `serpapi.py:77`, `pubmed.py:151`); XML root checks at `arxiv.py:100`, `pubmed.py:122`. Native malformed shapes return `parse_error`, without mapping or request changes. | B2 (D178) |
| j. PubMed EFetch quota | `providers/pubmed.py` keeps the B2 error_kind copy and frozen top-level classification. `test_connector_contract::test_pubmed_efetch_quota_stops_later_searches` now pins both ESearch and EFetch attempts/sends and zero later quota-suppressed sends. The collector preserves completed ESearch independently of EFetch failure (`test_transport_accounting::test_pubmed_collector_keeps_stages`, `test_discovery_pubmed_counts_and_step_provenance`). | P7-F2 fixed (D199) |
| cursor_empty. Empty/non-string cursor | B2 fixed: `providers/openalex.py:159-160` and `semantic_scholar.py:151-152` return None for empty/non-string tokens; bioRxiv inherits OpenAlex. Relevance offsets remain numeric and S2 CUT remains separate. | B2 (D178) |
| header_wait. Header secrecy and invalid waits | B2 fixed: `providers/common.py:180` redacts allowlisted values using only the operation's supplied credential; `:223` rejects negative and non-finite Retry-After. Keyless operations have no credential to redact. | B2 (D178) |
| k. Empty object / absent or null result container | Characterization only: `{}` is `zero_results` for SerpApi/default and S2/bulk; absent or explicit-null containers are `zero_results` for S2/default, S2/bulk, IEEE/default, Scopus/default, SerpApi/default and PubMed/default. OpenAlex/default, bioRxiv/default, Crossref/default and CORE/default still return `parse_error` for null, as their previous parsers did. Ten `container_null` fixtures pin these outcomes alongside the eight accepted empty-object/absent cases. Other malformed container types remain rejected. This preserves prior parser behavior and establishes no provider-documented empty-result syntax. | Unscheduled; needs provider documentation |
| l. Successful-body key echo | `facade.dispatch_search` sanitizes raw_payload and each admitted record.raw with the sent key, then flow writes and hashes the sanitized payload. Chain and keyed lookup writers use the operation snapshot too. Redacted-key collisions omit that dictionary with secret_key_collision. Only the operation's own key is in scope. | B4 fixed (D194) |
| identity_openalex | Null/empty/numeric/object id becomes `None`, empty, numeric text or object text (`providers/openalex.py:80`); `IDENTITY_KNOWN_MISMATCHES` pins four cases. Dispatched tests drop unusable identities and retain numeric text under the shared rule; counts are stored. | B4 admission (D194) |
| identity_biorxiv | The same four identity shapes inherit OpenAlex stringification. Same retrieval lineage, not independent evidence. Dispatched tests drop unusable identities and retain numeric text under the shared rule; counts are stored. | B4 admission (D194) |
| identity_semantic_scholar | Null/empty/numeric/object paperId stringifies (`providers/semantic_scholar.py:54`) on both endpoints; eight characterization cases, with both records inside the bulk read limit. Missing identity fails parsing. Dispatched tests drop unusable identities and retain numeric text under the shared rule; counts are stored. | B4 admission (D194) |
| identity_crossref | Missing/null/empty DOI without a URL becomes `None` text (`providers/crossref.py:53`); three characterization cases. Number/object DOI now raises caught AttributeError and returns `parse_error` under decision 6. Dispatched tests drop unusable identities and retain numeric text under the shared rule; counts are stored. | B4 admission (D194) |
| identity_arxiv | Missing/null/empty Atom id becomes an empty provider record ID (`providers/arxiv.py:47,56`); three characterization cases. XML has text/elements rather than JSON scalar types; JSON number/object type cases are inapplicable here. Dispatched tests drop unusable identities and retain numeric text under the shared rule; counts are stored. | B4 admission (D194) |
| identity_ieee_xplore | Missing/null/empty article_number becomes empty; number/object stringifies (`providers/ieee_xplore.py:39`); five characterization cases. Dispatched tests drop unusable identities and retain numeric text under the shared rule; counts are stored. | B4 admission (D194) |
| identity_scopus | Missing/null/empty dc:identifier without eid becomes empty; number/object stringifies (`providers/scopus.py:38`); five characterization cases. Dispatched tests drop unusable identities and retain numeric text under the shared rule; counts are stored. | B4 admission (D194) |
| identity_core | Missing/null/empty id becomes empty; number/object stringifies (`providers/core.py:43`); five characterization cases. Valid numeric CORE identities remain usable under the B4 admission amendment; the native positive fixture is already numeric. Dispatched tests drop unusable identities and retain numeric text under the shared rule; counts are stored. | B4 admission (D194) |
| identity_serpapi | Missing/null result_id becomes `None` text; empty stays empty; number/object stringifies (`providers/serpapi.py:38`); five characterization cases. Dispatched tests drop unusable identities and retain numeric text under the shared rule; counts are stored. | B4 admission (D194) |
| scopus_count_unmapped. Unmapped count | Scopus's STANDARD mapping does not read `citedby-count`; `ProviderRecord.cited_by_count=None` means unknown, including when the synthetic body supplies zero. Group 3's zero-preservation rule applies only where the adapter maps a count. The `counts_zero` case asserts None; adding the mapping is an enhancement, not a defect. No mapping change in B2. | Unscheduled enhancement |
| pubmed_scan. Source-owned classification copy | Round 1 fixed: exactly one `SCAN_ALLOWLIST` entry in `tests/test_connector_boundary.py` permits `fetch_outcome.error_kind`, because EFetch copies the already-classified `SearchOutcome.error_kind` unchanged. Other unresolved expressions still fail closed. | B2 (D178) |
| option_types. Value-type validation | B3a fixed (D179): `providers/facade.py:94-104` validates exact option types, declared values and an exact nonnegative retry allowance before send. `tests/test_connector_facade.py:266` covers every declared option, explicitly including integer 17 for OpenAlex reference_count/references and S2 bulk sort, with ContractViolation and zero requests; exact str-subclass and synthetic enumerated-value cases are included. `PENDING_B3A` is closed; direct registry behavior stays unchanged. | B3a fixed (D179) |
| query_delegation. Rendering/rule admission | B3b (D193): registry declarations and `resolve_query_syntax` (`providers/registry.py:142`) drive pure candidate rendering, written counts and issue lists (`query_rules.py:218`); shared compiler allocation (`query_compiler.py:122`) drives both block compilation and the facade (`facade.py:130`). `tests/test_query_delegation.py:37` replays the pre-edit query freeze; undeclared compiler/facade endpoints are named refusal changes under the bounded revision amendment. Module-level rules stay lenient. Query translation through a synthetic registry-only connector is covered; other closed admission surfaces remain in ledger h. | B3b fixed (D193); dispatch remains B4 |
| pause_text. Missing configuration label | English pause labels and Turkish entries now cover provider_not_configured, provider_quota_exhausted and provider_adapter_revision_changed (including unreadable provenance). Completed searches remain; quota retries require resume/retry. Build and lint passed with existing warnings; the new pause texts were not inspected in a rendered browser (D194). | B4 fixed (D194) |
| b4_merge_version | `test_connector_dispatch::test_merge_and_arxiv_versions`: two dispatched providers retain both mappings for one DOI source; arXiv versions remain separate. | B4 fixed (D194) |
| b4_resume_paging | `test_connector_dispatch::test_resume_provenance`: legacy NULL/current continuation asks the next page once, and the subsequent resume asks no succeeded page twice. | B4 fixed (D194) |
| b4_resume_lookup | Registry-owned existing-helper bindings, single/batch lookup, OpenAlex citing dispatch and watch citing dispatch; `tests/test_capability_binding.py` replays capability equivalence, unsupported/no-request operations, atomic reserve/settle traces, chunk resume and chain continuation. D174 Q3's default is met (D201). | G1-F1 fixed (D201) |
| g1f1_o4 | A missing required lookup key returns failed answers with not_configured/before_send, zero requests and zero collector entries. Scopus chunks snapshot once; settlement refunds the whole reservation. `test_scopus_missing_key_chunk`, `test_scopus_key_snapshot_per_chunk`. | G1-F1 fixed (D201) |
| g1f1_o5 | Chaining drops/counts unusable identities and sanitizes each admitted record.raw; paging uses returned counts and backward unresolved IDs use admitted records. `test_chain_admission_raw_redaction_and_provenance`, `test_chain_drop_does_not_extend_paging`. | G1-F1 fixed (D201) |
| g1f1_o6 | Chain search rows record connector_json; incompatible or unreadable prior-page provenance refuses only that seed's next page, without usage or search row. SQL NULL continues. `test_chain_continuation_refuses_only_that_seed`. | G1-F1 fixed (D201) |
| g1f1_o8 | Lookup dispatch sanitizes abstract, paper_id, linked_dois, has_preprint and outcome.error with the sent key, separately from payload/record redaction. `test_capability_equivalence`, `test_echoed_key_absent_from_stored_lookup`. Citing error text is left as send produced it to preserve watch bytes. | G1-F1 fixed (D201) |
| g1f1_s2_malformed_answer | A matched S2 answer with a truthy non-string abstract raises AttributeError outside the helper's bounded catch. Direct and facade characterization preserves this exception; the workflow keeps its reservation and loses collected entries (ledger d). `abstract_not_string`, `test_malformed_answer_keeps_reservation`. | Recorded limit; helper change requires adapter revision |
| b4_payload_write | `test_connector_dispatch::test_payload_write_failure_publishes_nothing`: OSError publishes no source, candidate, search row or succeeded step. Filesystem and database are still separate writes. | B4 fixed (D194) |
| b4_limit_provenance | `test_connector_dispatch::test_limit_record_and_pause`, `test_limit_discovery_and_suppression`, `test_chain_limit_error`, `test_kill_limit_error` distinguish recorded limit kinds. | B4 fixed (D194) |
| b4_s2_binding | `test_connector_dispatch::test_s2_binding` and `test_s2_arxiv_publication_relation` check identifier ownership, including preprint-to-publication links. | B4 fixed (D194) |
| b4_stored_revision | Migration 0067 adds nullable connector_json without changing earlier rows. `test_connector_dispatch::test_resume_provenance` and `test_resume_changed_descriptor` refuse incompatible/malformed continuation with no send, usage or search row. | B4 fixed (D194) |

## Historical B2 status (D178, before B3a–B5)

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
