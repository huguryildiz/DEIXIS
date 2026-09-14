# Providers, evidence and storage — design draft

Date: 2026-09-14. Requirements and proposals, not implemented capabilities.

## Execution boundary

The user does not want a multi-agent architecture. The first version should use
one main research agent with method files and tools; discovery, synthesis,
candidate development and kill-search are responsibilities, not agent instances.
No standing generator/reviewer pair is required. A separately requested bounded
review may use an additional agent, but the core workflow must complete without it.
Multiple available model connections do not imply simultaneous agent execution.

Retrieval, parsing, persistence, schema checks, source/version references and
budget enforcement belong to application/tool code. These checks do not establish
semantic support, mathematical correctness or scientific novelty. Preserve original
page/section locations for decisive equations, tables and algorithms; parser output
must remain inspectable against the source. See [the method specification](../methods/research-methods.md)
for lightweight feasibility checks, bounded revision and human decision points.

### Optional user-selected review

Proposed UI: select a candidate, claim assessment or report, choose an available
model connection and start a bounded review. Show scope, outgoing content and
available cost/budget information before starting. The start action authorizes
that review; do not add repeated routine approvals. Default to supplied evidence;
additional retrieval is an explicit option. Never silently substitute models.

Create an immutable review input snapshot with artifact/source versions and known
access limits. The reviewer has no write access to the main research state and
does not start an automatic debate. Store a separate report with findings linked
to claims and evidence, reasoning, implications, proposed changes and uncertainty.
Record requested/resolved model, timestamps, tools and available usage/cost.
An incomplete input or failed run is not a successful review.

The user can feed selected findings back into the main workflow for revision;
preserve provenance and previous versions. Mark the review as referring to an older
version when its dependencies change. No automatic repeat review or verdict by
majority. A different model is another assessment, not proof of independence or
scientific correctness. The [UI prototype](../../prototypes/shadcn-ui/README.md#optional-model-review-prototype)
demonstrates the interaction with fictional models, fixed sample findings and
in-memory session-scoped state. Production schema, persisted snapshots/history,
actual model/tool execution and revision handling remain to be implemented.

## Provider configuration

All seven providers are in product scope: Semantic Scholar, Crossref, arXiv,
OpenAlex, Scopus, IEEE Xplore and SerpApi. This is a support requirement, not a
claim of implemented connectors or a requirement to query all providers every time.
Users choose enabled sources and supply their own access where required.

Additional databases must be supported through an extensible connector contract:
query translation, authentication, pagination, normalized publication records,
source provenance, access links, capabilities and explicit error states. A URL and
API key alone cannot describe every scholarly API; a new protocol needs an adapter
or a supported declarative mapping. Citation lookup and full-text retrieval are
optional capabilities, not assumptions shared by every source.

The owner supplied credentials in the conversation. Their VALUES ARE OMITTED from
this handoff and all copied configuration. No live requests using those credentials
were executed during this consolidation. Rotate exposed credentials before use;
configure replacement values locally. Do not assume environment variables exist.

| Provider | Environment variable | Intended role | Authentication detail supplied by owner |
|---|---|---|---|
| Semantic Scholar | `S2_API_KEY` | Discovery, paper metadata and citation relationships | Check current official header requirements |
| Crossref | Not specified | DOI metadata, publication matching and deposited full-text links | Verify selected public/service access mode; no credential supplied |
| arXiv | Not specified | Preprint discovery, version records and PDF links | Verify API/download requirements; no credential supplied |
| OpenAlex | `OPENALEX_API_KEY` | Cross-disciplinary discovery and bibliometric metadata | Check current official authentication requirements |
| Scopus | `SCOPUS_API_KEY` | Indexed search and citation metadata within entitlements | `X-ELS-APIKey` header |
| IEEE Xplore | `IEEE_API_KEY` | Relevant engineering/computing searches | `apikey` query parameter; redact URLs |
| SerpApi | `SERPAPI_API_KEY` | Supplementary Google Scholar discovery | `engine=google_scholar`, `api_key` query parameter |

Owner-reported SerpApi allowance: 250 searches/month shared across uses. Remaining
quota and current terms were not verified. Verify provider docs and entitlements
before implementation; do not interpret this table as tested access.

Use relevant direct scholarly APIs for primary retrieval and SerpApi for supplementary
coverage. Do not force IEEE into unrelated fields. Translate concept families into
each API's syntax. Include method-side and adjacent-field vocabulary and backward/
forward citation searches where useful. Do not AND every desired novelty feature.

Cache responses and keep query/run records. Distinguish zero results, failed auth,
missing entitlement, rate limits, exhausted quota and pagination truncation. Retry
with bounded backoff; do not silently substitute providers or increase spending.
Citation counts retain provider and retrieval date; they are not summed into a
single number. A metadata record does not establish PDF/full-text access.

Raw URLs, logs, error messages, cache keys and exported data must omit credentials.
The future app should use an OS credential store where suitable. Each distributed
installation supplies its own credentials; do not ship the owner's keys.

Model access is separate: agent/CLI adapter, cloud model API, or local model server.
Detect installation, authentication, supported interface and usable models separately.
An installed app or subscription is not a verified API integration. Model selection
and literature-source selection must be separate UI controls.

The selected user experience is automatic discovery of supported Claude Code/Codex
installations and optional local services such as Ollama, plus manually configured
cloud API connections. Inspect installation, session state and actual availability
separately using supported interfaces. A detected executable alone is not a ready
connection. Preserve agent-managed credentials rather than extracting tokens into
an unrelated model API client. Verify subscription integration support per adapter.

Refresh model catalogs through each connection where supported, with a manual model
identifier option otherwise. Preserve user selection and record the requested and,
when reported, resolved model identifier for each run. New catalog entries do not
silently change ongoing work. Kimi/GLM are model families, not universal connection
protocols. Ollama remains optional, including for embeddings.

See also the accepted research-workspace, table, export and language decisions in
[the continuation brief](../desktop/README.md#sonraki-soru-cevap-kararları--14-eylül-2026).

## Context, quotas and resumable work

Accepted behavior: save progress and pause on exhausted quota or model-connection
failure; ask before switching models. Do not silently fall back to a paid API or
another provider. Automatic fallback remains unapproved.

Track three separate quantities through supported provider/agent interfaces:

- Effective model/session context capacity and current context usage, when exposed.
  Otherwise label the local token estimate as an estimate and the capacity source
  explicitly. Cumulative billed tokens are not current context occupancy.
- Account quota windows with actual duration, scope, remaining/used values, reset
  time and last successful refresh. Do not force every provider into daily/weekly
  labels or infer account-wide consumption from this research alone. Unavailable
  or stale quota information must remain visibly unavailable or stale.
- This research's API spending/usage and user-defined budget, separate from the
  account subscription quota. Distinguish measured charges from local estimates.

Proposed refresh policy: at connection and research start, at a bounded provider-
appropriate interval while active, via supported update events, and after quota
errors or user refresh. A previous successful check cannot guarantee the next call
will succeed because other clients may consume the account quota concurrently.

Context exhaustion needs separate handling from daily/weekly quota exhaustion.
Persist completed evidence, source IDs and pending work before a new model step.
Bound retrieved passages and reserve output capacity. Context compaction/resumption
is accepted as automatic near the context boundary, with a visible transition,
preserved source links and completed work, and retrieval of omitted details from
stored evidence when needed. Adapter details remain to be designed; never claim a
summary preserves all original detail.
Research budget enforcement should consider pending calls and estimates before
starting work rather than merely discovering an overshoot afterward.

Codex documentation inspected in this discussion exposes account rate-limit reads
and update events; comparable support must be verified independently per adapter:
[Codex App Server](https://developers.openai.com/codex/app-server/).

## Candidate processing components

Do not request a mandatory corpus size at intake. Retrieve candidates and screen
within the chosen sources/scope/budget, then inspect relevant papers in batches.
Use unresolved questions to guide further work and report resource/search limits
as stopping reasons, not proof of completeness. Count retrieved, screened-in,
inspected and answer-cited sources separately, defining the deduplication/version
unit. Provider result totals, indexed candidates, full-text access and actual
inspection are different quantities. Quick/Standard/Detailed are effort presets;
their numerical budgets require testing and are not fixed paper-count guarantees.

These are candidates discussed by the owner, not installed dependencies or a final
stack decision:

- LangChain: reusable loaders, splitters, retrieval and model integrations. Keep
  Quaestio's source provenance and workflow rules independent of this library.
  Claude Code/Codex agent connections require their own adapters; a generic chat
  model integration does not establish access to an agent subscription. Evaluate
  dependency/abstraction cost against the code saved by the selected components.
- ChromaDB: a persistent local passage/vector index managed by the backend, without
  a separately administered database for the user. Retain stable passage IDs and
  source/page links. Its documented single-node layout includes SQLite and vector
  index files; do not assume that copying one SQLite file backs up the index.
  Verify the layout and backup behavior for the version eventually selected.
- Ollama: optional local generation and embedding provider. `llama3`, `mistral`
  and `nomic-embed-text` are examples, not pinned defaults or quality recommendations.

Generation and embedding providers are separate capabilities. A subscription-based
agent connection need not expose embeddings. If no embedding connection is configured,
the application can retain text search and section-based reading, while explicitly
showing vector search as unavailable. Chroma cannot generate useful embeddings
without an embedding model; any bundled/default embedding download must be made
explicit. Record embedding model/revision, dimensions and chunking/extraction
versions; reindex when the representation changes. Do not mix incompatible vectors.

Documentation inspected for this discussion (2026-09-14; no runtime tests):
[LangChain retrieval](https://docs.langchain.com/oss/python/deepagents/retrieval),
[Chroma storage layout](https://cookbook.chromadb.dev/core/storage-layout/),
[Ollama embeddings](https://docs.ollama.com/capabilities/embeddings).

## Proposed storage behavior

Selected runtime direction: local browser UI plus local backend for version one;
Tauri packaging later. The backend owns filesystem, provider requests and secret
access. Use loopback binding, origin checks and scoped paths; do not expose arbitrary
filesystem or shell execution to browser content. Local storage and research logic
remain independent of the UI framework. shadcn/ui is only a candidate.

The user chooses a library directory. Import copies PDFs there and preserves the
original file. Shared papers link to multiple projects without redundant copies.
Use a file hash for identical bytes and publication/version identifiers for scholarly
identity; different editions must not be merged merely because titles are similar.

Proposed layout, not an existing runtime:

```text
Quaestio Library/
  library.sqlite
  papers/
  extracted/
  indexes/                  # Rebuildable indexes; Chroma is a candidate
  projects/<project-id>/reports/
  projects/<project-id>/exports/
```

The proposed application SQLite database owns library metadata, conversations,
evidence and user corrections. A candidate Chroma index is a separate derived
store; it does not replace the application database or original PDFs. Reindexing
must preserve user corrections and existing source-linked evidence records.

Keep page locations when extracting text; record extraction/OCR failures and version.
Support corrections, durable sessions, recoverable deletion and export/backup.
Local storage does not imply encryption or automatic backup. Cloud models can receive
selected passages even when the PDFs remain local; local inference can avoid that.
External literature searching still requires connectivity.

## Proposed output contract

These are initial schemas to refine with examples, not frozen database migrations.

**papers.csv:** `paper_id`, full citation, title, authors, year, venue, DOI/other
identifier, publication type, version/family ID, discovery sources, retrieval date,
metadata verification, citation counts with source/date, PDF path, full-text access,
reading depth, screening decision and rationale.

**evidence.csv:** `evidence_id`, `paper_id`, `question_id`, field/claim, extracted
value, short source passage or faithful paraphrase, PDF physical page, printed page,
section/equation/table, inspected version, reading depth, evidence type, author claim
versus analyst inference, verification state, reviewer correction and uncertainty.
Keep excerpts proportionate; do not export entire copyrighted texts by default.

Priority requirement: each evidence-table cell exposes "Show evidence" and
"Recheck this cell". Persist cell/revision identifiers, linked evidence and source
version/location, actual calculation inputs/units/operations when applicable,
run/model identity and timestamp, uncertainty and user edits. These are inspectable
source and operation records, not private model reasoning or a post-hoc explanation
presented as an execution trace. A linked quote does not alone prove the claim.
Missing provenance must be explicit, never reconstructed as if it were recorded.

Recheck only the selected cell within the active research/source scope; retain the
previous revision and present proposed changes without overwriting user edits.
Mark dependent report claims for review when their underlying evidence changes.
Acceptance example: selecting a calculated cell reveals the recorded inputs and
source locations; rechecking proposes a new revision while preserving the user's
version. A cell lacking full text must display that limit rather than a fabricated
PDF citation. This is a requirement, not an implemented or tested feature.

**research_questions.csv:** `question_id`, question, motivation/value, assumptions,
closest precedents, overlap, potential contribution, feasibility requirements,
falsification/undermining evidence, prior-work assessment, linked evidence IDs,
search scope/date and next informative step.

Generate the user-facing wide evidence matrix and HTML/Markdown reports from these
linked records. Allow domain-specific fields: e.g. population/intervention/comparator
for experiments; variables/objective/constraints/guarantees for optimization.
Never fabricate a formulation for a descriptive study.

Keep the following dimensions separate:

- Reading depth: metadata, abstract, selected sections, full text inspected.
- Evidence type: empirical observation, simulation, mathematical result, proposal,
  analyst inference. In the supplied example: DEMONSTRATED / MODELLED / PROPOSED /
  INFERRED, interpreted at claim level rather than as a blanket paper rating.
- Answer assessment: supported, partial, contradicted, unclear, insufficient evidence.
- Prior-work overlap: PRIOR_WORK_MATCH, PARTIAL_OVERLAP,
  NO_MATCH_FOUND_WITHIN_SEARCH_SCOPE, INSUFFICIENT_EVIDENCE.

Earlier KILLED/WOUNDED/CLEAR/OPEN vocabulary is historical shorthand. Do not use
“CLEAR” or “OPEN” as proof of novelty. Applicability, overlap, correctness, value
and parameter availability answer different questions.

Unknown, not reported, not verified and not applicable must remain distinct.
Numerical corpus summaries need explicit denominators and reproducible calculations.
Do not equate paper counts with consensus or an empty matrix cell with a worthwhile
gap. Similarity/embedding scores may prioritize reading; they do not certify novelty.
Quantitative synthesis requires compatible designs and outcomes, not merely CSV data.
