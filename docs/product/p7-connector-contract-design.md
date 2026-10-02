# P7 G1: scholarly connector contract design

**Date:** 3 October 2026. **Status:** proposal, design only. **Base inspected:**
`a4deebfd511993335dda4992e6e39151f40e3644` in the detached
`DEIXIS-g1plan` worktree; initial Git status was clean. This document does not
implement or close G1. Code and tests were read, not executed. No network,
provider or model call, application startup, or live-library access occurred.

Revision evidence: the cited G8 provider and workflow paths in the sibling
`DEIXIS-p7g` worktree were also read locally. Section 13 records an owner-reported
live access check from 3 October 2026; it was not rerun for this revision.

G1 should define a versioned internal adapter interface and a registry-driven
conformance suite. Existing provider functions remain behind compatibility
adapters. Application code continues to own source selection, budgets,
persistence, identity resolution and evidence publication. The contract consumes
the error classification produced by the concurrent G6/G8 work; it does not
create another classifier or retry loop.

The structure follows [the P8 design note](p8-review-watch-design.md): inspected
behavior, proposed boundaries, implementation batches, exit evidence, risks and
owner questions. The defaults below are recommendations, not accepted decisions
or a record of an external review.

## 1. What the documents require

These are exact quotations from repository files. The Turkish quotations remain
unchanged; the interpretation that follows is this proposal.

| Source | Exact wording |
|---|---|
| [Product README](README.md), accepted boundaries, line 13 | "Scholarly coverage includes Semantic Scholar, Crossref, arXiv, OpenAlex, Scopus, IEEE Xplore, SerpApi, bioRxiv, CORE and PubMed. The user may add further sources through a defined connector contract. Source selection and model selection are separate." |
| [Implementation plan](implementation-plan.md), section 5.3, line 201 | "Bağlantı sözleşmesi: arama, tekil kayıt, sayfalama/cursor, normalize kayıt, kaynak/erişim linkleri, isteğe bağlı atıf/fulltext yeteneği, hata ve limit bilgisi. Yeni veritabanı eklemek adapter veya desteklenen deklaratif eşleme ister; yalnız URL/anahtar bütün protokolleri tanımlamaz." |
| Implementation plan, P7 row, line 297: work | "Claude, DeepSeek, isteğe bağlı Ollama/embedding; IEEE/Scopus/SerpApi; eklenti sözleşmesi" |
| Implementation plan, P7 row: exit condition | "Her etkin bağlantı auth/model/kota/hata matrisiyle ayrı doğrulanmış; ürün kapsamındaki uygulanmamış bağlantılar açık listeli" |
| [API and data design](api-and-data.md), provider configuration, lines 52 to 57 | "Additional databases must be supported through an extensible connector contract: query translation, authentication, pagination, normalized publication records, source provenance, access links, capabilities and explicit error states. A URL and API key alone cannot describe every scholarly API; a new protocol needs an adapter or a supported declarative mapping. Citation lookup and full-text retrieval are optional capabilities, not assumptions shared by every source." |

[The P7 coverage note](p7-coverage-verification.md), section 5, records G1 as
"Eklenti sözleşmesi uygulanmadı" and cites the product promise and fixed
`CONNECTORS` registry. Its section 4 says that a loading point, schema and version
rule were not shown. That note describes older code and a separate D172 worktree;
the implementation inventory below comes from this checkout instead.

The requirement is an extension boundary for scholarly sources: an adapter must
describe more than an endpoint and key. The inspected product documents do not
promise installation of arbitrary external packages, a plugin marketplace,
runtime discovery, a sandbox, or a user-authored mapping editor. The word
"eklenti" in the P7 row does not establish those mechanisms. G1 therefore takes
the internal adapter route allowed by section 5.3. A contributor or user can add
a reviewed adapter in a DEIXIS checkout; installing an external plugin remains
unsupported. This narrower delivery interpretation must be explicit when G1 is
accepted (Q1).

## 2. What is in code today

All observations in this section are static reads on the base above. Existing
test cases are evidence of intended checks, not a passing test run in this task.

### 2.1 Shared structures and callers

| Surface | Observed behavior and limit |
|---|---|
| [`providers/registry.py`](../../backend/deixis/providers/registry.py), `Connector`, `CONNECTORS`, `reading` | Ten statically imported connectors; `search` is a broad `Callable[..., Awaitable[SearchOutcome]]`. Descriptors carry key requirements, routing flags, host, paging, page/depth limits, page gap, endpoint overrides, SW options and `requests_per_search`. There is no common scholarly `Protocol`, contract version or external loader here. |
| [`providers/common.py`](../../backend/deixis/providers/common.py) | Shared `ProviderRecord`, `OtherVersion`, `SearchOutcome`, DOI normalization, offset helpers and `send`. Outcome status and delivery class are strings, not closed types. `raw_payload` is optional; `rate_limit` holds selected headers. The module docstring's status list omits the implemented `not_configured` status. |
| [`providers/query_rules.py`](../../backend/deixis/providers/query_rules.py), [`query_compiler.py`](../../backend/deixis/providers/query_compiler.py) | Provider/endpoint syntax checks and rendering exist, but include named provider branches and a fixed name table. A new registry entry alone does not provide query translation. |
| [`credentials.py`](../../backend/deixis/credentials.py) | Managed source keys use environment, `.env` and keychain rules. Source keys have `testable=False`; saving or finding a source key is not an access probe. `OPENALEX_API_KEY` also serves bioRxiv. No secret value is part of the public status shape. |
| [`api/app.py`](../../backend/deixis/api/app.py), `/api/connections` | Provider rows report `implemented`, `access_mode`, `supplementary`, `key_env`, `role` and a note saying access/quota are not verified in advance. The route also calls model adapters' `health`; it is not a pure local scholarly-connector probe. `/api/connections/{connection}` is a model route. Neither route was invoked. |
| [`workflow/flow.py`](../../backend/deixis/workflow/flow.py), `_send_search`, `_record_search` | Calls the selected function, passes endpoint and SW options for pages, counts retries, and stores outcomes/cursors. Successful statuses are `completed` and `zero_results`. Host grouping and stored query semantics matter. Search persistence and workflow failure decisions belong here, not in adapters. |
| [`workflow/store.py`](../../backend/deixis/workflow/store.py), `upsert_provider_source`, `record_search` | Reuses provider identity first, then an eligible normalized DOI; preserves mappings and separate versions. `record_search` commits search rows, records, candidates and the step outcome in one SQLite transaction. Payload file writing happens outside that transaction. |

### 2.2 Registered connectors and compatibility requirements

Page sizes below are code constants, not verified current provider entitlements.
"Lookup" means an inspected implementation, not a promise of universal lookup.

| Connector | Access / paging | Existing behavior to retain |
|---|---|---|
| OpenAlex | Optional key; cursor; 200/page | `search.title_and_abstract`; SW-only reference fields; primary and other PDF versions kept apart. `works_by_ids` and `citing_works` exist; count/field-distribution helpers are separate operations. |
| Semantic Scholar | Optional key; relevance offset 100/page, reachable 1,000; bulk cursor 1,000/batch | Stored endpoint and sort determine syntax and read semantics. Bulk total is an estimate. An oversized bulk batch keeps the requested prefix and returns `CUT = "cut"`, which must never be sent as a provider token. Shared pacing covers search and batch DOI lookup. |
| Crossref | Keyless; offset; 100/page | `searchable=False`: verification only in current dispatch. The search function still exists. JATS abstract conversion and posted-content version labels remain; DOI lookup is in `lookup.crossref_work`. |
| arXiv | Keyless; offset; 100/page | Atom parsing, three-second spacing and current 406/429 handling. Record IDs retain `vN`; the unversioned arXiv DOI has `merge_by_doi=False`. `published_doi` names another version. |
| bioRxiv | Optional OpenAlex key; OpenAlex cursor; 200/page | Delegates to OpenAlex with `locations.source.id:S4306402567`; records are attributed to bioRxiv, retrieval to OpenAlex. It is not independent corroboration of OpenAlex. |
| PubMed | Optional NCBI key; offset; 100/page | ESearch, then EFetch when IDs exist. Cursor advances by IDs served, not XML records parsed. Preserve structured abstracts and author keywords. Registry declares two requests/search; zero results need only ESearch. |
| IEEE Xplore | Required key; offset; 200/page | One-based `start_record`; no stamp-page PDF attachment; author terms distinct from controlled terms. Current 403 "Over Queries" becomes `rate_limited`, even for a daily limit; G8 owns correcting that classification. |
| Scopus | Required key; offset; 25/page | `STANDARD` search yields no abstract. New SW queries exclude it; stored SW queries can still name it. COMPLETE DOI abstract lookup and institutional-access probe remain separate. |
| CORE | Required key; offset; 100/page | New SW queries exclude it; earlier routed-false queries may retain it. Drop `fullText` from stored payloads; no version-labelled PDF in search records. PDF-location lookup is outside this module's search function. |
| SerpApi | Required key; one page; 20/page | Supplementary; new SW queries exclude it. Ignores its legacy cursor argument and has no continuation. SerpApi: `quota_exhausted` is never retried; other 429s follow G8's bounded policy; one page only. This is the inspected sibling G8 policy to retain when integrated. Snippets remain raw search excerpts, not abstracts; remove payload fields that repeat keyed request URLs. |

Every Python module under `backend/deixis/providers/` was read, including
`lookup`, `pacing`, `query_compiler`, `zotero` and the empty `__init__`.
`lookup.py` has a separate `LookupAnswer` with `found`, `not_found`, `failed` and
enrichment fields. Zotero is an explicit import path with its own local/web
permissions, not a registered scholarly search connector. It must not gain
generic connector access to local files. Unpaywall and PDF-location adapters also
remain acquisition capabilities rather than new `CONNECTORS` entries by default.

### 2.3 Decisions and tests that constrain G1

[D13 and D172](../decisions.md) require shared record semantics, source-specific
queries, secret-free provenance, bounded retries, supplementary SerpApi, and a
direct `not_configured/before_send` result for missing required keys. The four
search guards and registry-driven missing-key test are present here. D172's
recorded full-suite and live-Claude results were not reproduced.

The dispatched path has no access check before `_send_search` counts usage. If a
required key is removed after the protocol freezes, the adapter returns
`not_configured`, and `_record_search` passes that status to `search_runs`, whose
CHECK list excludes it. Dispatched `not_configured` is currently counted as a
request and violates the `search_runs` status CHECK. B2 owns the named
dispatched missing-key behavior change, independent of the facades: check access
before `add_usage` and either record the step without a `search_runs` row or
widen the CHECK via a new migration. B2 includes the key-removal-after-freeze
regression and must pass it before B3a begins; the fix is not deferred to B4.

Later decisions matter: D18 supersedes D13's original pause-on-any-search-failure
rule; D46 groups arXiv versions at work level while retaining source versions;
D29/D53 govern credentials; D31/D32 add CORE/PubMed; D67/D89 govern pacing and
host grouping; D87/D91/D93 govern verification, SW exclusions, stored endpoint
compatibility and source routing; D95 keeps citation chaining a separate bounded
workflow. G1 must preserve these distinctions instead of restoring D13's older
routing or retry defaults.

The primary test files read were [`test_providers.py`](../../tests/test_providers.py),
[`test_settings_connections.py`](../../tests/test_settings_connections.py),
[`test_provider_roles.py`](../../tests/test_provider_roles.py),
[`test_provider_records.py`](../../tests/test_provider_records.py) and
[`test_p9_faults_providers.py`](../../tests/test_p9_faults_providers.py).
Related lookup, paging, bulk, routing, pacing and compiler tests were inspected
for their applicable cases. The provider matrix uses a manually maintained
`SEARCH`/`ALL` list; adding to `CONNECTORS` does not automatically add a connector
to most of that matrix. The missing-key test already enumerates the registry.

Other extension constraints are concrete:
`contracts/research/common.schema.json` has a closed `provider_id` enum;
`record_lookups` has a provider CHECK list rebuilt in migration `0048`;
PDF discovery provenance has its own provider CHECK lists. These cannot be
bypassed by registration. No external plugin-loading or declarative-mapping
implementation was found in the inspected provider boundary or product docs.

## 3. Scope and authority

G1 covers scholarly search and capability-declared record operations, using
injected transports and local descriptors. It includes onboarding instructions,
compatibility tests, identifiers, limits, delivery semantics and payload ownership.
It does not add a provider, model connection, embedding adapter, search strategy,
PDF downloader, watch scheduler or external package installer.

The adapter translates a frozen request and provider response. Application code
decides whether that operation is in scope, schedules it, enforces its budget,
writes provenance, merges records and publishes evidence. A connector never
selects sources for the user, promotes a snippet to an abstract, infers a PDF
version, or treats metadata agreement as scientific verification.

## 4. Proposed internal interface

Proposed contract ID: `deixis.scholarly_connector.v1`. Place its Python types and
`ScholarlyConnector` protocol in a future `providers/contract.py`, with a small
compatibility facade for existing functions. These files do not exist as a result
of this design. Retain `ProviderRecord`, `OtherVersion` and `SearchOutcome` as the
initial data shapes; avoid moving them while G6/G8 changes `common.py`.

If these descriptors or outcomes later gain a serialized schema, keep it closed
(`additionalProperties: false`), with required properties and nullable unknowns.
The internal contract version does not silently change a model-step schema;
changes to required model I/O need their own schema version and fixture updates.

The following signatures are a design sketch, not runnable code or existing APIs:

```text
ScholarlyConnector
  descriptor: ConnectorDescriptor
  access(context: ConnectorContext) -> AccessState
  render_query(groups: QueryGroups, endpoint: EndpointId | None) -> QueryRendering
  query_issues(text: str, endpoint: EndpointId | None) -> list[str]
  async search(request: SearchRequest, context: ConnectorContext) -> SearchOutcome
  async lookup(request: LookupRequest, context: ConnectorContext) -> LookupOutcome
```

Every registered connector implements this surface, including a deterministic
unsupported result when lookup is unavailable. Every search-capable endpoint
passes search tests even if workflow policy currently excludes it. Workflow
dispatch still refuses search through a verification-only descriptor; a test
calling Crossref's function does not make it a discovery source.

| Type | Required meaning |
|---|---|
| `ConnectorDescriptor` | Stable `provider_id`, display name/order, contract ID, adapter revision; credential reference and requirement; current `searchable`, `sw_searchable`, `supplementary`; actual transport host/group and retrieval lineage; endpoint descriptors, capabilities, query-rule revision and declared request cost. No credentials, call at import time, filesystem paths or arbitrary executable names. |
| Endpoint descriptor | Stable endpoint ID, accepted option names/values, paging mode (`cursor`, `offset`, `single_page`), per-page maximum, known reachable depth or unknown, existing page gap/retry policy, total semantics (`reported`, `estimated`, `unknown`). Describe the default and S2 bulk separately. |
| `ConnectorContext` | Injected HTTP client/transport, only this connector's resolved credential, contact email and bounded call policy. Import, descriptor reads and `access` perform no network or credential-store mutation. The caller owns deadlines, cancellation and request reservations. Do not pass `Store`, a model adapter or the application-data path. |
| `SearchRequest` | Frozen query text, requested record limit, endpoint/sort/options, optional cursor and caller's retry allowance. Positive integer limit; unknown endpoint/options fail before sending. `cursor=None` preserves the unpaged request; `FIRST_PAGE` requests a paged first read. No automatic query rewrite at send time. |
| `QueryRendering` | Native query and the terms retained/dropped, with a rule revision. Compiler owns trimming/order and query budgets; adapters supply rendering/validation. Initial facades must reproduce existing compiler outputs exactly. |
| `LookupRequest` / `LookupOutcome` | Typed DOI or namespaced provider identifier and one-record operation. Result says `found`, `not_found`, `failed` or `unsupported`, with operation provenance and a record or explicit enrichment, not an invented complete record. A supported lookup may reuse an existing batch client for one ID. |

Lookup is mandatory as an interface method, but actual remote capability is
declared per connector. Initially bind the inspected Crossref and Semantic Scholar
lookup helpers, Scopus's existing DOI enrichment with its entitlement precondition,
and OpenAlex ID reads; other adapters return `unsupported` with no request until
an implementation is accepted. A found record without an abstract is different
from an absent record. Crossref lookup 404 remains `not_found` with its recorded
HTTP response; unsupported is never counted as a failed search or zero results.
Scopus enrichment cannot attach an abstract returned for another DOI.
`unsupported` is never written to `record_lookups`; persisting it needs a new
migration. Migration `0048` allows only `found`, `not_found` and `failed`.

Identity binding also needs a negative test for batch lookup. The current S2
client checks list length, then zips answers positionally with requested DOIs;
it does not reject a same-length reordered list merely because it is reordered.
An equal-length reordered response can therefore attach the wrong abstract and
record the wrong DOI as `linked_dois`. Its docstring is stronger than that code
path. A facade must not claim verified record binding from length alone. Preserve
the existing helper in the compatibility batch. B4 owns the identity-binding
behavior change: match answers by `externalIds` DOI/ArXiv to the request,
otherwise `failed`; reorder test. This fix must pass before declaring the lookup
capability fully conformant, including legitimate preprint-to-publication
relations.

Citation/reference enumeration and full-text *location* may have separate typed
capability protocols. Register only implemented operations: OpenAlex's existing
citing-work/ID functions are candidates for a facade, not proof that every
connector supports chaining. Acquisition keeps responsibility for download,
version checks, URL protections and parsing. G1 supplies no new citation or
full-text request solely to fill a capability box.

### 4.1 Pagination and continuation

The caller persists each successful page before using its continuation. A cursor
belongs to `(provider_id, endpoint, query/options, adapter compatibility revision)`;
it is never decoded as a URL or used with a different query or endpoint. Offset
adapters translate decimal cursors locally; IEEE adds one only on the wire.
Preserve the current raw cursor representation and step keys during migration.

An additive continuation view may describe `next_page`, `exhausted`, `single_page`
or `truncated`, but must retain existing `next_cursor` and stop reasons. S2's
`cut` sentinel means a batch was truncated and continuation is unavailable, not
that all matches were read. Empty pages stop the current read even when a token
is present, as current workflow code does. A read limit, provider cap, failed
page or single-page policy never becomes a claim of complete retrieval.

Repeated tokens or malformed offsets need a bounded, recorded stop rather than
an unbounded loop. That is a conformance failure if current code cannot enforce
it; any required behavior fix must be named separately from the compatibility
refactor. Resume reuses stored cursors and terminal steps; a failed page is
retried only under the existing workflow's retry rules.

Bad offsets in `common.page_offset`, unknown S2 endpoints and a reused S2 `CUT`
raise `ValueError` today. The facade preserves raising for equivalence;
conversion to a contract outcome is a named behavior change.

## 5. Identifiers, records and DOI merging

Adapters return source-owned identifiers, normalized DOI using `normalize_doi`,
and nullable metadata. `provider_record_id` identifies the provider's record;
its namespace is `provider_id`. It is neither a DEIXIS work ID nor a passage ID.
Retain case/version significance for non-DOI IDs. Normalizing a DOI is syntactic
cleanup, not verification that the DOI exists or matches the title.

Use the current `ProviderRecord` fields without speculative completion. Keep
abstract text/origin, primary version label, PDF version, other versions and raw
record provenance distinct. `None` citation/reference counts mean unknown;
zero means a supplied count of zero. `references=None` differs from an explicitly
empty list. A placeholder such as `(untitled)` is display fallback, not a verified
source title. Fixtures must exercise missing and malformed identities; fabricated
IDs must not make a malformed new response publishable. Historical stored records
are not rewritten by a new validator.

The store, not the connector, performs merging:

1. Reuse the mapping for the same provider record; otherwise reuse an eligible
   normalized DOI under the current store rules. Preserve each provider mapping
   and its retrieval provenance.
2. Preserve `merge_by_doi=False`. arXiv's DOI groups a work, not a file version:
   versioned and unversioned records retain separate source-version rows (D46).
   A `published_doi` is a relation to another version, not permission to copy its
   DOI or passages into the preprint.
3. Retain existing application identity/link rules. Similar titles alone do not
   collapse two source versions; SW work linking and notice handling remain in
   their existing modules. G1 introduces no similarity threshold or new merge rule.
4. Enrichment keeps the source/origin of the supplied abstract and other fields.
   A different-version PDF stays a separate version; a provider offering a URL
   does not establish reading depth or acquisition success.
5. Count found hits, unique works, selected versions, inspected passages and
   cited sources separately. OpenAlex and its bioRxiv projection share retrieval
   lineage and cannot count as two independent confirmations.

The facade must pass the existing store/identity tests without changing selections,
evidence links, source/work IDs, heads, candidate ranks or version grouping.

## 6. Access, errors, quota and rate-limit signals

### 6.1 Access before any request

Resolve the key at call time using existing credential ownership. For a
key-required connector, a missing or empty key returns
`status=not_configured`, `delivery_class=before_send`,
`access_mode=not_configured`, no records/payload/HTTP status, and zero retries.
This guard applies to direct adapter calls and every declared protected operation,
not merely registry filtering. Optional-key providers remain keyless-capable.
Construction, access inspection and unsupported operations spend zero requests.

This is the required contract, not the current dispatched behavior. Dispatched
`not_configured` is currently counted as a request and violates the `search_runs`
status CHECK. B2 implements the dispatched missing-key guard before `add_usage`
and resolves the CHECK disposition in the same batch: either record the step
without a `search_runs` row or widen the CHECK via a new migration. This is a
named behavior change independent of the facades. Its B2 regression removes
the key after the protocol freezes and checks zero usage, zero sends and a
valid recorded step; B2 cannot exit with that regression failing.

Keep configuration and observed access separate. A configured key does not imply
valid authentication, institutional entitlement, available quota or successful
search. A facade must not probe on import, registration, source-key save, or a
local access read. Existing explicit institutional checks retain their operation
and budget; Scopus route detection is not invoked by descriptor inspection.

### 6.2 Error contract and composition with G6/G8

Keep operation status, delivery class and limit evidence separate. Close the
types around the integrated vocabulary, without silently renaming persisted
history. G6 owns model errors; G8 owns scholarly HTTP/body classification and
its retry decision. The inspected sibling G8 code uses
`SearchOutcome.error_kind=quota_exhausted` while status stays `rate_limited`;
temporary rate limits use `error_kind=rate_limited`. Its `_record_search` does
not persist `error_kind` in `error_json`, and both currently return the pause
reason `provider_rate_limited`. B4 must persist the distinction and test both
stored rows and pause reasons without silently renaming historical statuses.

| Condition | Contract meaning / action |
|---|---|
| Successful nonempty/empty search | `completed` / `zero_results`, no failure delivery class. Zero results requires a successfully parsed provider result, never auth failure or malformed HTTP 200. |
| Missing required configuration | `not_configured/before_send`; no request, no retry. |
| Authentication or entitlement refusal | Preserve `auth_required` / `entitlement_missing` and provider evidence. Present common keyed 401/403 mapping as existing classification, not proof of why the account failed; do not retry without an access change. |
| Temporary rate limit | G8's rate-limit category and bounded wait policy, with supplied headers/body signal and delivery class. Wait/retry only when that provider policy and remaining caller budget allow it. |
| Exhausted daily/monthly/credit quota | G8's quota category, distinct from temporary pacing. No automatic short backoff retry; preserve reset/remaining information only when reported. SerpApi: `quota_exhausted` is never retried; other 429s follow G8's bounded policy; one page only. |
| Ambiguous limit refusal | Record the refusal and uncertain kind; do not invent daily quota or a reset time. G8 decides the conservative retry rule. An HTTP status alone does not prove quota versus pacing. |
| Timeout / transport / other HTTP failure | Preserve `timeout` or `failed` and `before_send`, `rejected_not_executed` or `after_send_unknown`. A read timeout or 5xx does not establish that the request was unprocessed. |
| Parse or contract failure | `parse_error` for invalid provider output, no successful records from an invalid page. Local invalid endpoint/options/offset fail before send; bad offsets, unknown S2 endpoints and `CUT` currently raise `ValueError`. The facade preserves raising for equivalence; conversion to a contract outcome is a named behavior change. Never report these as zero matches. |
| Partial operation | Retain successful earlier pages/suboperations and the failed/deferred part separately. `partial` is a coverage/aggregate condition, not a substitute for the actual page failure class. The current workflow need not acquire a new success status. |

Limit observations retain raw, sanitized allowlisted header/body signals, their
provider/endpoint and observation time. Optional normalized fields are limit kind,
remaining amount, unit/window, reset time and retry delay, each nullable with its
source. Missing values stay unknown. Numeric quota constants from historical
docstrings are not a current account balance. Validated delays must be finite
and nonnegative; a wait beyond policy ends the bounded attempt rather than
blocking indefinitely. Additional date-form parsing or provider reset formats
are enabled only by G8's documented/tested mapping.

Classification must happen before a quota response could enter the rate-limit
retry branch. The facade passes the caller's retry allowance into the same
`common.send` path and preserves the resulting category, HTTP status, delivery,
retry count and signals. It never retries around `send` or replaces G8's result
using a message regex. Existing workflow transient-before-send retry remains
separate. Unknown delivery for a paid/side-effectful operation is never
automatically replayed by the facade.

Integration sequence: establish G8's names and semantics, use that merged code as
the behavioral baseline, then freeze facade equivalence fixtures. G1's wrappers
must be behavior-equivalent to that baseline. G8's intended correction of IEEE
daily quota and related outcomes is recorded as G8 behavior change, not hidden
inside G1. Tests deliberately cover daily and per-second IEEE messages, SerpApi
quota and ordinary retryable 429. If G8 is not available, these rows remain
pending and G1 cannot claim its limit contract fully conforms. The cited sibling
G8 paths were inspected for this revision; final integration, batch completion
and test results were not verified.

### 6.3 Logical operations and transport cost

A search page and an HTTP attempt are different units. A descriptor declares the
maximum base sends per operation (`requests_per_search`, two for PubMed), and
each subrequest reports its actual attempts/retries. PubMed zero results must not
be recorded as two observed sends; EFetch failure must retain the successful
ESearch provenance. Reservations and observed counts are separate.

Static inspection shows the distinction is only partly represented today:
`_send_search` increments one base provider request plus `outcome.retries`,
while PubMed can send two base requests. The kill-search path uses
`requests_per_search` for its conservative reservation; `page_allowance` does
not multiply by that field. This is a code observation, not a measured budget
overrun. G1's compatibility refactor must preserve current public counters.
Accurate per-attempt enforcement across all callers needs a separately named
budget integration change; do not call an additive transport trace a fix for it.
The contract makes actual subrequest reporting mandatory, while its enforcement
gate remains explicit debt until that change passes tests (Q4).

## 7. Payload and provenance ownership

Adapters return a sanitized, JSON-serializable payload representation and normalized
records; they do not choose storage paths or write files. Current payloads are
not uniformly raw wire bytes: CORE drops full text, arXiv stores a feed projection,
and PubMed stores ESearch JSON and, when available, EFetch XML. Describe the
representation and any omissions rather than calling all of them complete raw
responses. Parse-error outcomes may currently lack a payload; do not invent one.

The application persists each operation/page with provider, retrieval lineage,
query/options without secrets, access mode, timestamps, cursor/limit, status,
HTTP/delivery information, limit observations, retries and payload reference.
Add contract ID, adapter/query-rule revision and payload representation as
versioned provenance, without altering historical protocol bodies. Use existing
search/step JSON extension points where suitable; any required persistent-column
change uses a new migration. Backup and purge must retain/protect any newly
referenced payload. Runtime files belong only to the configured app-data directory.

Preserve `_record_search`'s payload reference and canonical payload digest and
`record_search`'s atomic SQLite publication. The digest covers the stored payload
object under existing canonicalization, not necessarily the original HTTP bytes.
The file and SQLite write are not one atomic transaction today. Tests must show
that a storage failure publishes no new source/step success; do not claim G1's
facade resolves orphan-file or crash behavior without separate evidence.

Sanitize descriptions, errors, headers, normalized `record.raw` and success/error
payloads before persistence. Synthetic tests inject key values and keyed URLs
into nested provider bodies and errors; persistence must not leak them. Do not
persist authorization headers, cookies, signed access tokens or request URL key
parameters. A diagnostic body omitted for safety carries an explicit omission
reason. Existing redaction is not a measured universal guarantee; a failure in
these tests requires a named fix, not weaker assertions. Payload text remains
untrusted data and cannot change the selected provider, model or budget.

## 8. Adding a connector and checking conformance

Registration is a reviewed source change in `providers/registry.py`, with a
stable ID and versioned descriptor. Keep the current ordered registry and its
policy helpers. A contributor supplies an adapter, pure query rules/rendering,
capability declarations, synthetic fixtures and usage notes. No runtime import
path, arbitrary URL or key from an API request can register executable code.

Onboarding has five gates:

1. Specify the actual endpoint, authentication, syntax, paging, identifier and
   quota/error evidence. Future implementation work must read authoritative
   provider documentation before claiming current API compatibility. This task
   did not do that online; existing docstrings are historical evidence only.
2. Add the facade/descriptor, explicit default and endpoint options, transport
   lineage, credential reference and bounded request costs. Add managed source
   key metadata only when needed, retaining `testable=False` by default. Declare
   unsupported lookup/citation/full-text operations without remote emulation.
3. Check every admission surface: query compiler/rules, routing policy,
   `common.schema.json` provider enum, method provider references, fixtures,
   connection labels, lookup/acquisition constraints and persistence. A schema
   change updates versioned contracts, methods, adapters and tests together;
   unsupported capabilities need no fictional migration. Existing migrations
   are never edited. New SW routing defaults must be explicit: current unknown
   sources route as `no_route`, which can otherwise add request cost unnoticed.
4. Run the registry-driven suite and applicable integration tests with mocked
   transports, temporary storage, fake credentials and fail-closed network
   guards. Registration without fixture/capability coverage fails collection
   or the coverage assertion; it cannot disappear from a manually kept list.
5. Record the exact evidence and limits before enabling the adapter in a release.
   A synthetic registration proves extensibility inside a test, not access to
   a new scholarly database. Any later live access probe requires separate
   authorization and remains separate from deterministic conformance.

### 8.1 Proposed conformance suite

Future location: `tests/test_connector_contract.py` and
`tests/fixtures/connectors/` with synthetic, secret-free cases. These are planned
files, not additions in this task. Parameterize from `CONNECTORS`, its declared
endpoints and capabilities. Assert exact equality between registry IDs and
fixture IDs; also require a case for every declared endpoint. Tests call the
registered facade, not a second search-function dictionary. Unsupported
capabilities still pass explicit no-request tests; supported ones cannot skip
their positive/failure cases.

| Case group | Required evidence |
|---|---|
| Registration and purity | Unique stable IDs, supported contract revision, descriptor completeness and option validation, schema enum coverage; descriptor/access reads send nothing and write nothing. A deliberately added synthetic connector without fixtures fails; a complete synthetic connector needs no new branch in the generic dispatcher or suite. |
| Access and query | Required `None`/empty key sends nothing for every protected operation, direct and dispatched; removal after protocol freeze spends zero usage and records a valid step (B2 implements the guard before `add_usage`, resolves the `search_runs` CHECK disposition and passes the regression, independently of the facades); optional keys retain keyless requests; correct auth placement; compiled queries/endpoint syntax and dropped terms match the baseline; invalid options fail before send, with existing `ValueError` behavior retained for equivalence; no provider substitution. |
| Records and identity | Positive mapping, absent optional values, normalized DOI and stable namespaced IDs; missing/malformed identity is visible; abstract versus snippet; version-labelled versus uncertain PDF links; unknown/zero counts; duplicate hits merge by eligible DOI in the store and retain mappings; arXiv versions and same-title different-DOI records remain distinct source versions. |
| Paging and subrequests | Unpaged bytes/parameters preserved; first and later page translation, exhaustion, caps, null/empty/repeated token, offsets and one-based IEEE, S2 bulk token/sort/CUT and estimated total; SerpApi stays one page. PubMed success/empty/fetch failure retain suboperation trace, actual send counts and ESearch cursor basis. Stored resume repeats no succeeded page. |
| Error, retry, payload and integration | Empty/malformed 200, 400, 401/403, 5xx, connect/read timeout; G8 quota versus rate-limit fixtures and unknown signals; bounded wait/retries with fake clock and injected failure. Secrets embedded in nested payloads/errors never reach storage. Temp-store page publication, digest/reference, failed payload write and compatibility replay preserve existing rows/counts/selection; actual sends never escape the mocked client. |

Use `httpx.MockTransport`, the existing in-memory credential seam and a fake
clock/sleeper. Add a test-level guard against unmocked HTTP and DNS/socket access;
the constructor must not create another client. Conformance never starts a server
or calls `/api/connections` with real model adapters. API projection tests use
`create_app(..., adapters=fakes, http_client=mocked, start_worker=False)` in process
with temporary data, only in a future implementation task authorized to do so.

Keep existing specialized tests as regression evidence. A broad suite passing
because every provider returns generic JSON is insufficient: synthetic XML,
two-stage PubMed, S2 bulk and provider-specific auth/quota bodies must reach
their real parser paths. A discovered pre-existing defect is recorded by name
and fixed in an identified batch before its applicable gate passes. No blanket
`xfail` or fixture omission can establish universal conformance.

## 9. Migration without behavior change

First wrap each existing search function and expose a typed facade while keeping
the current `Connector.search` callable and all default arguments available.
The facade forwards only declared options; it does not add select fields, sort,
cursor or retries to an unpaged request. Move dispatch to that facade only after
equivalence tests pass. Extract query rendering/rules behind the same interface
without changing their outputs or compiler allocation. Avoid reformatting
provider modules while the G6/G8 batch owns their error branches.

Version interface shape separately from adapter semantics. Contract v1 describes
the shared boundary; an adapter revision changes when request, mapping, cursor
or capability semantics change. A frozen operation records both for new work.
Stored queries with no revision use the documented compatibility facade: no
endpoint means the historical default, never the new preferred endpoint. An
incompatible or removed revision stops visibly; it cannot silently restart at
page one or select another provider. Adapter provenance added for new operations
does not retroactively re-label old results or recompute their protocol hashes.

The equivalence baseline is the integrated G8 code. Compare old function and
facade on the same mocked sequence: method, URL/params, headers/body, call order,
wait policy, retries, records, payload, statuses, delivery and cursor. Compare
stored outcomes and counts after deterministic integration replay; timestamps
and generated IDs use controlled clocks/ID seams or an explicit comparison
mapping. A previously stored search/lookup stays terminal on resume. Preserve
Crossref's verification role, SW exclusions, routed-false behavior, old S2
relevance queries and all user choices.

An internal contract refactor can be compatible while adding diagnostic
metadata. Changing public accounting, admission of malformed records, retry
policy or error status is behavior change and must be identified and justified
separately. If strict conformance exposes such a mismatch, the report names it
and does not claim both complete compatibility and a corrected behavior.

## 10. Implementation batches and exit evidence

All batches below are future work. No batch, pytest command, build or live probe
was executed for this design.

| Batch | Deliverable and likely surfaces | Model-free evidence required to exit | Dependency / real call |
|---|---|---|---|
| B1: freeze the boundary | Future `providers/contract.py`, compatibility facade and descriptors; preserve `common.py` shapes and `Connector.search`; onboarding notes and explicit version/unsupported rules | Static descriptor/registry checks; no-request construction/access; baseline fixtures per registered ID/endpoint; list any conformance mismatch before refactoring | G8 classification names agreed; no real call |
| B2: establish conformance and fix dispatched missing-key behavior | Future `tests/test_connector_contract.py`, synthetic per-provider fixtures and mocked/fail-closed transports; keep specialized tests. Named behavior change independent of the facades in `workflow/flow.py` and persistence: check access before `add_usage`; either record the missing-key step without a `search_runs` row or widen its status CHECK via a new migration; add the key-removal-after-freeze regression from sections 2.3 and 6.1 with the fix | Registry and fixture sets equal; every endpoint/capability accounted for; section 8.1 case groups run with exact command/log and B4-specific integration cases tracked for B4; intentional missing-fixture and unsupported-capability tests; dispatched `not_configured` regression passes with zero usage/sends and a valid recorded step under the chosen CHECK disposition; full backend pytest passes before B3a | B1; no deliberately failing regression carried into B3a/B3b, no `xfail`; remaining B4 defects and unintegrated G8 limit cases stay named pending gates; no real call |
| B3a: search facades | Wrap all ten connectors in `providers/`; keep registry dispatch unchanged | Every registered connector and S2 endpoint has request/output equivalence against integrated G8, including existing `ValueError` paths; D172 direct no-send guards and B2 dispatched guard unchanged; no new provider enabled or legacy workflow restored | B2 passing tests and integrated G8; B4-specific integration gates remain pending; avoid overlapping provider error edits; no real call |
| B3b: query rendering delegation | Extract rendering/validation delegation behind the facade while preserving compiler allocation and outputs; keep dispatch unchanged until B4 | Compiler byte equality for native query text, retained/dropped terms, order and budgets; compiler/rule regression across every connector and endpoint | B3a; no real call |
| B4: integrate provenance and admission | Move dispatch to the equivalent facade; `workflow/flow.py`, `store.py`, lookup/capability bindings, contract/adapter revision metadata; API projection and onboarding path. Only two named behavior changes remain in B4: persist `error_kind` in `error_json`, keeping quota and rate-limit rows and pause reasons distinct, with tests for both; match S2 answers by `externalIds` DOI/ArXiv to the request, otherwise `failed`, with a reorder test | Preserve the already-passing B2 dispatched-key-removal regression through facade integration; quota/rate-limit rows and pause reasons are distinct; equal-length reordered S2 answers bind correctly and unbound answers fail; temporary-store merge/version/payload tests, resumed paging and lookup, source routing, kill-search regression; API returns configured/unsupported facts without access claims; new internal synthetic connector dispatches through generic code | B3b; the two fixes are named behavior changes, distinct from facade equivalence; budget enforcement debt in section 6.3 remains a separately owned gate; no real call |
| B5: record G1 acceptance | Future P7 connector acceptance record and decision entry, coverage note update in the implementation worktree; compatibility and exception ledger; update `docs/product/README.md:13` and `docs/product/api-and-data.md:52-57` to say sources are added as reviewed adapters in the codebase; packaged builds cannot add sources | Full backend checks, exact conformance coverage counts by connector/endpoint/capability, warnings/skips, no unintended behavior changes; authoritative product documents and release scope state internal extension only; unresolved P7 gaps retained | B4; no real call required for internal conformance; owner-reported live access shown for four connectors in section 13, live per-connector error/quota formats remain open |

Batches touching `common.py`, provider modules, `flow.py`, connection projection
or migrations must integrate sequentially with G6/G8. Re-read that batch's final
tests and decision before editing; retain its classification instead of resolving
conflicts to the older base. Do not copy any migration number from this note.
If a future API/UI shape needs frontend changes, read `.impeccable.md` first and
run the web/build/render checks required by `AGENTS.md`; this proposal requires
no `apps/web` edit.

B2 ships the dispatched missing-key fix and its regression together on the
existing dispatch path. B3a and B3b preserve that behavior while adding facades
and query delegation. B4 adds its error-kind and S2 identity regressions with
their fixes; their pending gates do not require deliberately failing tests in
B2, B3a or B3b. Each batch exits with the full backend pytest passing, without
using `xfail` or omitting fixtures to conceal a failure.

For implementation, focused pytest runs iterate on the new suite and the existing
provider, identity, paging, lookup, routing and connections files. The required
backend completion command remains `uv run python -m pytest -q`, in an isolated
test environment with no live credentials or data access. Record any collection
failure and the justified subset instead of reporting a full pass. Commands in
this paragraph are future gates, not commands run for this document.

## 11. Limits and risks

No provider documentation was refreshed online. This revision measured no live
entitlement, quota, response format, third-party packaging compatibility,
retrieval quality or performance. The owner-reported access check in section 13
establishes successful searches for four connectors at that time; reported limit
headers do not establish live error/quota formats or remaining quota. The P7
coverage note and old decisions report other runs; those results are not evidence
produced here. A conformance pass with
mocked transports would establish application behavior on the enumerated cases,
not provider availability, recall, scientific support or complete coverage.

| Risk | Preferred treatment |
|---|---|
| G1 and G8 diverge on errors/retries | G8 owns classification; freeze its integrated result as the compatibility baseline. Test classification before retry and preserve its public status through every facade. |
| Strict tests expose existing defects | Keep the failing case and name the fix/dependency. Close neither that gate nor G1 on omitted fixtures; distinguish a repair from the refactor. |
| A descriptor overstates capabilities or independent coverage | Require positive and negative capability cases; preserve bioRxiv/OpenAlex lineage and source-version boundaries. |
| In-process contributed code is treated as isolated | Limit registration to reviewed code distributed with the application or a user-maintained checkout. A Python protocol is not a security sandbox. |
| Extension changes routing, budgets or historical queries | Admit the new provider across schemas/rules explicitly; preserve old endpoints/revisions and selections. Keep the PubMed accounting limitation visible until a separate enforcement change passes. |

## 12. Owner questions and proposed defaults

These choices do not block writing the design. Adoption belongs to the owner;
no default below was approved through a model or provider call.

| # | Question | Proposed default | Alternative / consequence |
|---|---|---|---|
| Q1 | Does G1 mean internal source extension or externally installable plugins? | Internal, reviewed adapter registration with a documented contributor path; explicitly state that end-user plugin installation is unsupported | External plugins require a separate loading, trust/isolation, credential, distribution and compatibility design; this document cannot close that broader requirement |
| Q2 | Should URL/key-only declarative mappings ship in G1? | No. Use the adapter route already allowed by section 5.3 | A bounded declarative DSL needs its own schema, auth/paging/transform limits and tests; no arbitrary evaluation or URL-derived imports |
| Q3 | Must every source implement remote single-record lookup now? | Every facade implements `lookup`; unavailable remote lookup returns `unsupported` without a request. Enable existing bindings only | Requiring a new remote implementation for all ten expands API research and provider scope; unsupported operations stay explicitly listed until accepted |
| Q4 | May G1 close while discovery's multi-request accounting is unchanged? | Close only the internal interface/conformance item, with actual-send reporting tested and the separate enforcement gap named, owned and linked to a target batch; P7 overall remains open | If G1 acceptance includes strict budget enforcement for every subrequest, require a separate accounting/enforcement batch before closure and report its deliberate counter/budget change |
| Q5 | What evidence is required before calling a new connector usable? | Deterministic conformance permits release inclusion; connection state says implemented/configured, with access and quota unverified until an explicit probe/request | Requiring a live probe for release is a separate owner-authorized access check; no probe follows from registration or saving a key |

## 13. Acceptance for G1 and its relation to P7

G1 can be recorded as implemented only when:

1. A versioned internal interface, explicit loading/registration path and complete
   onboarding procedure exist. The owner accepts the internal extension
   interpretation; the record and the B5 updates to the product README and
   API/data design state that sources are added as reviewed adapters in the
   codebase and packaged builds cannot add sources.
2. Every registered connector, endpoint and declared capability passes the
   registry-driven mocked suite, including unsupported/no-request cases. The
   evidence records exact commands, case counts, failures and skips; test
   existence alone is insufficient.
3. Existing connectors preserve the integrated G8 request/output behavior,
   selected source, stored query semantics, DOI/version identity, payload
   provenance and user choices, with every intentional exception named.
4. Error/limit evidence reaches storage without leaking credentials; quota and
   temporary rate limits consume G8's distinct classification. Missing required
   keys send nothing and spend zero usage, including removal after protocol
   freeze. B2 has passed the dispatched regression with an access check before
   `add_usage` and a valid recorded step under its explicit `search_runs` CHECK
   disposition; facade integration preserves that result. B4 has passed the
   error-kind persistence and S2 identity-binding regressions. Logical operations
   and actual subrequests remain distinct; any remaining enforcement debt has
   the explicit Q4 disposition.
5. The acceptance record lists unsupported operations, observed live access and
   remaining unmeasured live behavior, and carries unresolved P7 work forward.
   G1 acceptance does not satisfy model, embedding, entitlement or live-provider
   rows of the wider P7 exit condition.

Owner-reported evidence: on 3 October 2026 at 02:48, an owner-approved live check
sent one search to each of IEEE Xplore, Scopus, CORE and SerpApi using the owner's
keys. All four returned `completed`, HTTP 200 and three records each. Scopus
reported `x-ratelimit-limit: 20000`; CORE reported `x-ratelimit-limit: 150`.
Live error/quota formats were not measured. This revision records the supplied
fact without inspecting keys, accessing the live library or repeating the calls.

| P7 item | G1 batch / evidence disposition |
|---|---|
| G1 | B5 records acceptance only after the implementation and conformance gates above pass. |
| G10 | Live access shown on 3 October 2026 at 02:48 for IEEE Xplore, Scopus, CORE and SerpApi as reported above; live per-connector error/quota formats still open. Successful searches and limit headers do not close that remaining evidence requirement. |

The next implementation action is B1: agree the internal-extension scope and G8
classification vocabulary, then freeze descriptors and equivalence fixtures on
their integrated base.
