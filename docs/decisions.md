# DEIXIS decisions

Accepted product decisions from the 14 September 2026 conversation are recorded in the [dated handoff](desktop/README.md). This file records subsequent durable decisions; an entry does not turn an unimplemented proposal into a working feature. New entries go above older ones. Status values are `accepted`, `superseded`, `rejected`, and `deferred`.

## D42 — Name an older research on request with a research title run

**Status**: accepted
**Date**: 2026-09-16

**Context**: D39 names a research at the end of discovery, but every research created before it still carried its question (cut to 160 characters) as its title, and none of their answers predates D36's answer title. In the Library's project groups and drop panel (D41) these titles look alike once truncated. The owner asked for short titles for them.

**Decision**:

- A research can start a run of kind `research_title` (`POST /api/researches/{id}/runs`, migration 0022 widens the `runs` kind CHECK by rebuilding the table as 0019 did). It has one model step, the same `research_title` step and contract as discovery's, on the question and the currently included sources' titles and abstracts; a research with no included source is named from its question alone. Its budget is two model calls (one call and its single repair) and no provider request; its stage is `intake`.
- Unlike discovery's optional step, a failure here pauses or fails this run visibly. A valid title goes through `set_research_title` for the run's scope revision, so a later valid answer still renames the research.
- The research header offers "Suggest a short title" while the title is still the question, no run is active and the latest run is not paused (a newer run would hide that run's Resume in the run strip). The conversation timeline does not show these runs; the run strip and Activity do.

**Evidence**: `tests/test_library.py` runs the step with the synthetic fake adapter for a research with an included source and one without. On the live library, 14 of the 16 active researches were named by `gpt-5.6-luna` (their own research model) on 2026-09-16; the two whose latest discovery run is paused were left unchanged.

**Limits**: A title is a model proposal used as a label, not an answer claim; nothing checks it against the sources beyond the 15-word and not-the-question rules.

## D41 — Group the Library by project and add a work to a research by dragging it

**Status**: accepted
**Date**: 2026-09-16

**Context**: With 959 works the D40 table rendered every row at once and gave no way to reuse a work found in one research inside another. The owner asked for draggable rows, pagination and a per-project view, and chose drag-to-project (adding the work as a source) and grouping by project over a project filter.

**Decision**:

- The Library groups works by project by default (a toggle switches to one flat list; the choice is remembered per browser). Every active research is a collapsible group, including one with no source yet; a work used by several researches appears in each group. Groups page at 10 works, the flat list at 25; search, filter, sort or grouping changes return to the first page.
- A row can be dragged onto a project group, or, in the flat list, onto a project in a drop panel that appears during the drag. A project that already holds any version of the work is not a drop target. The work details panel offers the same action as an "Add to a project" menu, so it does not depend on a pointer.
- `POST /api/researches/{id}/library-sources` with a `work_id` adds **one** stored version of that work to the research: the one with the deepest stored reading (PDF text, then abstract, then metadata), and among equals the richer bibliographic record. Other versions are not added; they are different evidence. The version joins with `added_by = 'library'` (migration 0021 widens the CHECK) and a selection `included` with origin `user`, which bumps the selection revision like any user inclusion. A work already in the research answers 409, an unknown work or trashed research 404.

**Evidence**: `tests/test_library.py` covers the group list including an empty research, the deepest-version choice on a synthetic work whose published record has no text and whose preprint has an abstract, the membership and selection rows written, and the 409, 404 and CSRF refusals. The drag, drop highlight, pagination and drop panel were checked in Chrome against a copy of the live library on a separate port and data directory (one work added there); the live library was not changed.

**Limits**: Adding does not fetch, extract or screen anything, and it does not start a run; the research's next answer run sees the new included source. There is no remove action in the Library; the user excludes the source inside the research. The drop panel lists research titles, which older researches still carry as long questions and can look alike when truncated.

## D40 — The Library is a reading-depth table with a work details panel

**Status**: accepted
**Date**: 2026-09-16

**Context**: The Library page listed works as stacked rows inside a centred 1100px column, so its heading sat further right than every other workspace view and the page never showed what DEIXIS had actually stored for a work. The owner asked for the density and interaction of Elicit's library, keeping DEIXIS terminology and provenance.

**Decision**:

- The Library keeps the shared page frame of the other views (`.collection`: eyebrow, serif heading, subtitle, same gutter) and then runs a dense fixed-layout table across the full workspace width: paper, authors, venue, reading depth, year, citations, projects, added. Paper, year, citations and added are sortable; a density toggle switches between a two-line and a one-line title and is remembered per browser.
- `library_view` now reports a **reading depth** per source version and rolled up per work — `pdf_available` (a stored PDF with extracted text), `abstract`, or `metadata` — computed the same way as the evidence table's `access_level`. It is labelled as what DEIXIS stored, never as quality, and it drives the one filter in the toolbar.
- Selecting a row opens a details panel beside the list, fed by a new `GET /api/library/works/{work_id}` (`library_work_view`). The panel lists every stored version separately with its own reading depth, PDF filename and page count, and shows the abstract of the first version that has one, naming that version and saying when the text was rebuilt from the OpenAlex index. Versions are never merged.
- A version with a stored PDF opens in the existing DEIXIS PDF viewer, in the full workspace, through the research-scoped asset route that already enforces membership.

**Limits**: the panel reads stored records only — it neither fetches nor re-extracts anything. Reading depth describes what is stored, not whether the passage supports any claim. The list renders every work at once; it is not virtualized.

## D39 — Cap research titles at 15 words and name the research during discovery

**Status**: accepted
**Date**: 2026-09-16

**Context**: D36 derived the research title only from a structurally valid grounded answer, and let the model write 15–20 words. Until a valid answer existed the header showed the full question, which could be long. The owner asked for a shorter header title, a smaller font, and a full-width header.

**Decision**:

- The grounded answer's `title` ceiling moves from 20 to 15 words; validation rejects more than 15 Unicode words with one bounded repair.
- A new single-output model step `research_title` runs at the end of discovery, after screening and source similarity, on the question and the included sources' titles and abstracts. Its output `ResearchTitle` v1 (`deixis.research_title.v1`) carries only a `title` of at most 15 words, not copied verbatim from the question. It is optional: a failure keeps the provisional question-as-title and the run continues.
- The step writes the title through `set_research_title`, gated on the current scope revision. A structurally valid answer later still renames the research via `save_answer`, so the discovery-time title never outranks answer evidence.
- The header title spans the research view's full width (the `max-width:30ch` cap is removed) and renders at a smaller size.

**Evidence**: `tests/test_contracts.py` covers the 15-word ceiling and the `research_title` empty, too-long and verbatim-question rejections; the synthetic fake adapter returns a valid short title for the new task. The acceptance trash test now finds the research by that discovery-time title. Backend suite (2026-09-16, with D40–D41): 405 passed, 1 failed (`test_extraction_is_stopped_when_it_exceeds_the_memory_limit`, which times out before the memory limit on this machine and is outside this change); acceptance suite 21 passed.

**Limits**: The discovery-time title is a model proposal shown as the header label, not an evidence-bound answer claim. No real model has written one yet.

## D38 — Extract evidence table cells one source version at a time, from that version's passages only

**Status**: accepted
**Date**: 2026-09-16

**Context**: D37 left the cell extraction and column suggestion model steps, and the fill, recheck and suggestion endpoints, to a second sub-step of P5 slice 1 (`docs/product/p5-slice1-evidence-table.md` §5).

**Decision**:

- `EvidenceCellDraft` v1 answers every target column once for one source version: a state, a value shaped by the column's format, a note and evidence items of passage plus exact quote. Its state enum holds only `value`, `unknown`, `not_applicable` and `not_found_in_inspected_scope`, so a structured-output model cannot produce `inaccessible`, `not_verified` or `not_reported`, and validation rejects them as schema errors. `TableColumnProposal` v1 suggests at most eight columns that `column_spec` accepts, with names distinct from each other and from the table's columns.
- A StepInput for these tasks carries `extraction_target`: the table, the source version (`cell_extraction` only), the columns with their revision and definition, and `passage_scope` (passages given, passages available, whether every extracted PDF passage was given). `check_step_input` refuses a cell StepInput whose sources or passages include anything but that source version. It never carries a cell value, so a recheck does not show the model the current value.
- Validation adds per-cell checks that go through the single repair: `unknown_column_id`, `duplicate_column_answer`, `column_without_answer`, `invalid_cell_value`, `unknown_passage_id`, `duplicate_passage_id`, `anchor_not_in_passage`, `value_without_evidence`, `unknown_without_evidence`, `evidence_for_not_found`, `not_applicable_without_note` and `locator_in_note`. The step shows short handles for passages, the source and columns (as D12). After a failed repair, each answer that still has a model state and a value its format accepts is kept as an `unverified_draft` proposal with its allowlisted evidence only; it cannot be accepted.
- A fill request needs the table's `expected_version`, plans its cells (empty cells, and with `include_stale` values from an earlier column revision) for at most 25 sources, and stores the plan in `runs.target_json`, so a resumed run reads the same sources and step keys. The budget is two calls per planned call. A source with no retained passage gets `inaccessible` without a model call. A source within 48 passages and 60,000 characters is given whole; otherwise its abstract, then passages matching the column names and instructions (fused with semantic ranking when it is on), then the remaining passages in page order, up to 24 for a fill and 16 for a recheck. Reading depth is `abstract` when only abstracts were given, else `selected_sections`.
- A recheck request needs the cell's `expected_version`; a row outside the table or a source without text answers 422, another active run 409. Column suggestions run as a `table_columns` run on the question and the rows' titles and abstracts; the table view shows the latest suggestions, and adding one records `origin = model_suggestion` with its step.

**Evidence**: `tests/test_table_extraction.py` covers each cell check and a model-written person or system state, handle resolution, one-source StepInputs, which answers of an invalid output are kept, column proposal checks, a fill that links each cell to its own version's passages and skips the model for a source without text, a resumed fill and recheck that add no revision or call, eight columns per call, a spent budget pausing the fill, the 25-source plan, a stale fill that only proposes, T09 m (no human value in the recheck StepInput or message), a recheck whose model cites the preprint of the same work (rejected, kept as an invalid proposal without that evidence, not acceptable), the fill and suggestion API, T09 g and j, and T09 k (a restart during a recheck resumes into one proposal). Model outputs come from the scripted fake adapter. Backend suite: 402 passed.

**Limits**: No real model has filled a cell; the Luna trial is sub-step 5. The passage limits (48, 24, 16) and the page-order padding are untested defaults. The Evidence tab is not built, and the current run card labels table runs as answer runs. Semantic support of cell evidence stays `not_checked`.

## D37 — Keep evidence table cells as append-only revisions that only the user can change

**Status**: accepted
**Date**: 2026-09-16

**Context**: P5 requires an editable evidence table where a human edit is never overwritten, "Recheck this cell" produces a new proposal tied to the right source, version and passage, and version or index changes do not break earlier evidence (implementation plan §6.2, §9; api-and-data "Priority requirement"). The design note `docs/product/p5-slice1-evidence-table.md` left six questions open. The owner asked Claude to answer them (2026-09-16).

**Decision**:

- A table belongs to one research. Its rows are listed explicitly (`table_rows`): a new table starts with the included sources, and the user adds or removes the research's sources. Narrowing the Sources selection, as in D34, does not shrink the table.
- Columns carry a short name, an instruction written for a human annotator and an answer format: options, number and unit, yes/no, or short text (at most 500 characters). A changed definition is a new column revision; values made under an earlier revision stay and read as `stale_column`. Columns can be saved as a library-wide template.
- A cell is an append-only list of revisions (`model_fill`, `model_proposal`, `system_fill`, `human_edit`, `accept_proposal`, `dismiss_proposal`) and points at the revision it shows. Revisions, their evidence links and column revisions are immutable; only permanent deletion of the research removes them. A trigger refuses evidence from any source version other than the cell's own, including another version of the same work.
- A model result becomes the value only of an empty cell and only when it is structurally valid. Every other model result, including every recheck result, waits as a proposal; only the user's accept or dismiss decides it. Accepting copies the proposal's value, reading depth and evidence (with the StepInput that gave each passage) into a revision authored by the user.
- Human writes carry the cell version their screen showed and are refused with 409 when it changed. Creates and cell writes accept an `Idempotency-Key`; a replay returns the same record.
- Cell states stay distinct: `value` (with linked evidence), `not_verified` (a value without linked evidence), `unknown`, `not_reported`, `not_applicable`, `inaccessible`, `not_found_in_inspected_scope`. A source with no stored text gets `inaccessible` from the system without a model call.
- For the model step still to be built: a recheck does not show the model the current human value; no cell gets `full_text` reading depth and the model may not write `not_reported` until OCR and page checks exist (T10); fills run one call per source, at most 25 sources and 8 columns per call.
- Table work runs as runs of kind `table_columns`, `table_fill` and `cell_recheck` (stage `extraction`). Migration 0019 rebuilds `runs` for the new kinds; `db.migrate` runs a file whose first line is `-- deixis:foreign-keys-off` with foreign keys off and checks them before the commit.

**Evidence**: `tests/test_evidence_tables.py` (20 tests) covers the `runs` rebuild on a database at migration 18 (rows, idempotency key and foreign keys kept), rollback of a foreign-keys-off migration that leaves an orphan, T09 scenarios a–i and l with synthetic model outputs, superseded and invalid proposals, immutability and the same-source trigger, explicit rows, a withdrawn PDF whose evidence still resolves, answer-format validation, the API (versions, idempotency, CSRF, cross-research 404, templates, trash), permanent deletion and backup/restore of a table with a human edit. Backend suite: 363 passed.

**Limits**: The cell extraction and column suggestion model steps, the fill and recheck endpoints and the Evidence tab are not built, so no model has filled a cell and T09 j, k and m are not yet tested. Semantic support of cell evidence stays `not_checked`. Tables have no restore screen yet (trash is P5 slice 3).

## D36 — Let the answer model replace the provisional question with a bounded report title

**Status**: accepted
**Date**: 2026-09-16

**Context**: A research initially used the first 160 characters of the question as its title. Long multipart questions therefore occupied most of the research header and were copied unchanged into the report title and export filename. The owner asked the answer model to write a title of at most about 15–20 words and requested a typewriter reveal.

**Decision**: `GroundedAnswerDraft` v3 requires `title` in the answer language. The method asks for 15–20 words; deterministic validation rejects more than 20 Unicode words and sends the draft through the existing single repair attempt. Only a structurally valid answer for the current scope revision replaces the provisional question-as-title. The full question remains unchanged in the scope revision and revision form. When the title changes in an open research view, it is revealed once with a capped 450–900 ms typewriter effect; reduced-motion users receive the complete title immediately.

**Impact**: New valid answers provide the research header, report heading and export filename. Existing answers and researches retain their stored titles until a new answer is generated. A failed, unverified or no-evidence answer cannot rename the research.

## D35 — Remember refused PDF links and look once for another open copy

**Status**: accepted
**Date**: 2026-09-15

**Context**: In the local library, 62 of 121 open-access PDF downloads failed: 51 with HTTP 403 (MDPI, ScienceDirect, ACM, TechRxiv, Wiley) and 11 with HTTP 404 (an IEEE `ielx7` link and one arXiv version). The 403 sites refused a browser user agent as well, so they block automated clients rather than DEIXIS in particular. Each answer run requested the same links again (2 TechRxiv sources: 16 requests), and the timeline showed the raw code `fetch_http_error`.

**Decision**:

- A link that refused (HTTP error, not a PDF, too large, address not allowed) is not requested again in a later run. A timeout or lost connection is retried.
- After a 403 or 404, the answer run looks the DOI up once per source in Unpaywall, OpenAlex, Crossref and CORE (step `pdf_other_copy`). It attaches only a DOI-verified copy of the same version (D4). Web search stays the user's "Find PDF" action, and a copy of uncertain version still waits for the user to confirm it.
- The interface gives the reason in plain words with the HTTP status. When no other copy is found, the source says the user has to attach the PDF.
- DEIXIS does not try to get past bot protection.

**Limits**: Not measured on live providers yet. Repository copies are often an accepted manuscript, which D4 does not attach automatically, so many refused sources will still need a user upload. Activity rows recorded before this change have no HTTP status and show only "server refused".

## D34 — Close P4 on the packet-size re-run, reviewed by Claude on the owner's delegation

**Status**: accepted
**Date**: 2026-09-15

**Context**: The P4 gate (implementation plan §10) asks for a human check of one real source's identity, version and passage. It also asks for a measurement on a small source set the user knows: wrong citations, missed evidence, reading depth, correction time and reopen success. Restart and backup/restore tests are part of it as well. The owner chose the question of their co-authored paper, Kurt et al., "Packet Size Optimization in Wireless Sensor Networks for Smart Grid Applications" (IEEE TIE 2017, DOI 10.1109/tie.2016.2619319). They delegated the whole test to Claude, including the review judgments and the decision to close. All model roles ran GPT-5.6 Luna at medium effort. The known set was the target paper plus 18 packet-size works from its reference list.

**Decision**: P4 is closed. Later phases start now. The limits below are carried forward, not fixed first.

**Evidence** (research `res_IXBsnzhYZsKByEdTpSJo`; review packet from `scripts/p4_eval/measure.py`):

- **Discovery.** 110 unique records. The target and 9 of the 18 known works were found and included; the other 9 known works were found by no search.
- **Answer 1.** An unverified draft after its one repair: handle copy errors (`unknown_passage_id`) and one duplicate citation anchor.
- **Correction 1.** 13 user exclusions (off-topic works and one duplicate record). 9 published PDFs from IEEE Xplore were attached, using institutional access. This took 5.13 minutes in the app plus about 8 minutes to get the files.
- **Answer 2.** Valid: 14 claims, 105/105 link checks. It used 35 abstracts and no PDF page. With 51 included sources, the answer input gives each source its abstract first, and the 48-passage limit left no room for pages.
- **Correction 2.** 26 included sources set to Undecided, leaving 25 core works. This took 0.40 minutes.
- **Answer 3.**
  - Valid: 15 claims and 46 evidence links (32 abstracts, 14 PDF pages).
  - 152/152 link checks passed, and all 13 checked DOI titles matched Crossref.
  - It cited the target and 6 of the 18 known works. 3 more known works were given to the model but not cited.
- **Link check.** For Kurt 2017, the identity and the "published version" label were confirmed against the IEEE PDF, and so were the cited passages on pages 2 and 4. The same page check passed for Dong 2014 p. 8, Akbas 2014 pp. 3–4 and Vuran 2008 pp. 1, 4, 5 and 9.
- **Claim review of answer 3.** 13 supported and 2 partly supported: c10 turns one smart grid study into plural studies, and c15's inference relies on factors its own passages do not show. There were no wrong citations or wrong reading depths. The in-app reviewer marked all 15 as supported. All 25 included sources were judged relevant (included precision 1.0).
- **Restart.** The live backend was stopped and started again. The question, answer, selections and all 46 cited passages reopened unchanged. An earlier low-effort run (`res_IhQ9TI2QWmxjWsa8CodN`) had passed the same check (23/23).
- **Backup and restore.** A `deixis backup` of the live library was restored into an empty data directory.
  - Row counts matched in all 30 tables.
  - All 65 PDFs matched their SHA-256 names, and no asset file was missing.
  - The research view returned by the API was identical.
  - The 13 user exclusions, 26 user Undecided selections and 9 `user_upload` PDFs were present.
  - The reopen check also passed on the restored copy (46/46).

**Limits**:

- **Reviewer.** The review is Claude's, not an independent person's, and the owner did not re-check it. Correction times are an agent's; a person would need longer, especially for 26 selection changes.
- **Sample.** One question, one stochastic run per setting. The low-effort run found 6 of the 18 known works and the medium run found 9, but that difference is not a measured effect.
- **Recall.** This is the weakest result: half of the known works were not found, and 6 of 18 were cited.
- **Answer input.** An answer uses no PDF page once 48 or more sources are included. A user has to narrow the selection to get full-text evidence.
- **Model output.** Handle copy errors (D12) recurred in answer 1.
- **In-app reviewer.** It was more lenient than the delegated review.
- **PDF access.** The PDFs came from institutional access outside DEIXIS; the stored web candidates were not usable for these works.

**Impact**: The P4 gate is met, and its limits are recorded. Four problems stay open for later phases: recall of known works, abstract-only answers on large selections, handle copy errors, and the effort of narrowing a selection.

## D33 — Let the user confirm a version-uncertain PDF candidate before it is attached

**Status**: accepted
**Date**: 2026-09-15

**Context**: During the P4 packet-size re-run the owner saw Sources rows reading "Web Search · version uncertain · not attempted" and asked whether those PDFs should still be shown. Each candidate was named but had no link, so it could be neither checked nor used. D4 and the PDF-location decision forbid automatic attachment because a repository or Google Scholar copy may be a preprint, an author copy or another work.

**Decision**:

- Every PDF candidate row offers **Open file** for its URL.
- A candidate whose version is `uncertain` and whose DOI or exact title matched the source (`doi_verified` or `title_verified`), on a source without an attached PDF, also offers **Same version, attach**. A web result whose title did not match (`unverified`) is labelled "title does not match" and cannot be attached this way; the user can still download it and use **Attach PDF**.
- Only that explicit request retrieves the file, through the existing bounded, private-network-protected fetcher. The outcome is recorded on the candidate; a failure attaches nothing. A retrieved file is attached with origin `user_upload` and the candidate URL as `retrieved_from`, because the version claim is the user's, not a provider's. Automatic rules for `match` and `different` candidates are unchanged.

**Evidence**: An API test covers refusal of a different-version and of a title-unmatched candidate without a fetch, a recorded HTTP 403 without attachment, a successful `user_upload` attachment, 409 once a PDF exists, and an unknown candidate. The backend suite passed 338 tests and the web build succeeded. On an isolated copy of the local library served on another port, one web candidate returned HTML (recorded `not_pdf`), one returned HTTP 403, and a title-verified arXiv candidate was attached with eight extracted pages. In the live library, 6 of 7 stored web candidates were `unverified`; in the P4 packet-size research one of them linked to a different paper.

**Impact**: PDF coverage can rise only through a user's check, and each such file depends on that judgment; the source's version label is not changed. Most current web candidates are not eligible because their titles do not match. D4 is narrowed for user-confirmed files, not reversed.

## D32 — Add PubMed through NCBI E-utilities

**Status**: accepted
**Date**: 2026-09-15

**Context**: The owner noticed that PubMed was absent from the scholarly sources and asked to add it, including its API key in the local `.env` configuration.

**Decision**:

- A `pubmed` connector uses NCBI E-utilities: ESearch retrieves relevance-ranked PMIDs and the total match count, then EFetch retrieves PubMed XML for those PMIDs. The two calls form one provider search operation.
- Records keep PMID, DOI when present, title, authors, journal, publication year/type, volume, issue, pages and structured abstract sections. PubMed does not identify a version-labelled PDF, so the connector attaches no file.
- PubMed is available without a key. `NCBI_API_KEY` is an optional managed source key and may be set in `.env` or Settings. Requests identify the application as `DEIXIS` and include the configured contact email; the key is never written to the stored request description or payload.
- Search-plan instructions use native Entrez syntax, including quoted phrases, Boolean operators and optional field tags. PubMed joins the provider enum, default enabled-provider list and Connections UI.

**Evidence**: Mocked provider and integration tests cover the ESearch-to-EFetch sequence, XML mapping, zero results, bounded rate-limit retries, auth/error classes, result caps, secret redaction and the enabled-provider list. A live one-record request through the adapter with the configured key returned `completed`, a PMID, DOI and abstract, with no key in the request description. NCBI's official E-utilities documentation defines ESearch for UID discovery and EFetch for full records.

**Impact**: Changes the method package hash and `provider_id` contract enum. One logical PubMed query makes two HTTP requests. Biomedical coverage should improve, but recall and precision against a user-known set have not been measured.

## D31 — Add CORE as a search provider and a PDF-location lookup

**Status**: accepted
**Date**: 2026-09-15

**Context**: The owner asked (2026-09-15) whether CORE (core.ac.uk) was among the scholarly sources; it was not. They chose to add it both as a search provider and to the PDF resolver, because CORE aggregates open-access copies held by institutional repositories that the other providers may not list.

**Decision**:

- A `core` connector searches CORE API v3 (`/v3/search/works/`, `Authorization: Bearer`) with `CORE_API_KEY`, which can be saved in Settings like the other source keys (D29). It requires a key: without one CORE allows 10 requests per window, and 4 of 12 rapid keyless requests answered 429.
- Query rules follow live probes: the OpenAlex form and limits apply; an unbalanced query is sent back for repair (CORE returned 7 other records instead of an error); a quoted phrase without AND is sent back (`"molecular communication"` and `"a" OR "b"` answered HTTP 500, `"molecular communication" AND scheduling` matched 7); field prefixes are sent back (`title:"molecular communication"` matched 1,565,728 works, `("molecular communication")` 1,889). The method reference tells the search-plan step the same.
- Records keep DOI, authors, year, journal and abstract. CORE labels no file version, so no PDF is attached to a search record, and `fullText` is not stored.
- The PDF resolver queries CORE after Unpaywall, OpenAlex and Crossref with `doi:"<doi>"`, keeps only works whose DOI matches, and records their CORE-hosted PDFs as `doi_verified` but version `uncertain`. Under D4 such a candidate is listed for review and not downloaded automatically. Without a key the lookup is recorded as `auth_required` (`missing_core_key`) and sends no request.

**Evidence**: Backend tests: 321 passed (`tests/test_p4_eval.py` excluded). New mocked tests cover the record mapping, key redaction, dropped full text, CORE query rules, same-DOI filtering, the missing-key path, and that a CORE candidate is not downloaded. Live through the adapter (2026-09-15): the example query returned 10 of 10 records (5 with DOI, 8 with abstract) and no key appeared in the description or payload; the DOI lookup for `10.1371/journal.pone.0082935` returned one CORE-hosted PDF, and a closed IEEE DOI returned none.

**Impact**: Migration `0018_core_pdf_provider` adds `core` to PDF discovery provenance. Changes the method package hash and the `provider_id` contract enum. CORE PDF candidates do not raise automatic PDF recall because their version is unknown; they give the user an open copy to check and upload. Recall effect on search was not measured.

## D30 — Order "Most relevant" sources by similarity to the question after the screening verdict

**Status**: accepted
**Date**: 2026-09-15

**Context**: The owner asked (2026-09-15) whether text embeddings affect the source list's "Most relevant" order. They did not: it ordered by the model's screening verdict, then search position, and search position is not comparable across providers and queries. Before a change, an offline measurement ran on the stored library (`scripts/p4_eval/screening_similarity.py`; expectations were written into the script before the first run). Over 19 researches (35,567 include–exclude pairs), the similarity of title and abstract to the question (`gemini-embedding-2`) separated the model's include proposals from its exclude proposals with AUC 0.885 (95% interval over researches 0.818–0.934); search position gave 0.531 (0.497–0.562). Among proposed includes, sources cited in the latest answer were separated with 0.596 by similarity and 0.697 by search position (difference interval −0.22 to 0.06). That citation measure favours search position by construction: the answer orders sources partly by how many providers returned them (AUC 0.677 on its own), and sources returned by four providers have a median search position of 2, against about 10 for the rest. The owner approved the change after these results.

**Decision**:

- After screening, each screened candidate's title and stored abstract (the title alone when there is none) is embedded with the semantic search provider chosen in Settings (D29). Its similarity to the question is stored per research, question revision and model (`source_similarities`) and is not requested again for the same three. With semantic search off, nothing is sent and no score is shown.
- "Most relevant" orders by screening verdict, then similarity (highest first; sources without a score after scored ones), then search position. Without scores the order is as before.
- A neutral pill on each scored source shows the cosine similarity to two decimal places. Its tooltip states whether the score used the title and abstract or the title alone, and that the score is an ordering signal rather than a relevance judgment. Scores are not shown as percentages or qualitative bands because their scale depends on the embedding model.
- Only this order reads the score. Screening decisions and answer retrieval do not. It shows closeness to the question, not that a source is relevant or supports a claim.
- A failed embedding request is recorded as a failed `similarity:<model>` step and does not stop the run.

**Evidence**: Backend tests: 308 passed (`tests/test_p4_eval.py` excluded). A new test with a mocked Gemini endpoint checks that title and abstract are embedded together, that scores reach the research view, that a second call sends nothing, and that turning semantic search off hides the scores. The web build passed. On a copy of the library, one research was scored through the flow method (161 sources, one succeeded step), and in the app running on that copy the "Most relevant" order of all 161 records and of the 36 undecided ones matched the expected order. Not measured: whether this order helps a person screen. The library holds 2 user selection decisions out of 2,639, so there is no human judgment to compare against; 14 of the 19 researches repeat one question; and 270 of the 356 undecided sources have no abstract, so their score comes from the title alone. Existing researches get scores only at their next search run.

**Impact**: The title and abstract of every screened source, not only included ones, go to the chosen semantic search provider (Google or OpenAI when a cloud provider is chosen). Adds migration `0017_source_similarities.sql`.

## D29 — Manage keys, local tools and the semantic search provider in Settings

**Status**: accepted
**Date**: 2026-09-15

**Context**: The owner asked (2026-09-15) for a place in Settings that shows cloud APIs and models that can run on this computer, in the style of the Connections page, and approved a mockup. While it was being built they added that installed tools such as Claude Code and Codex should be detected, with an install button when they are missing. Keys could only be set in `.env`, and semantic retrieval could only use Gemini (D27).

**Decision**:

- The Connections page becomes the Connections tab of Settings (`#/settings/connections`; `#/connections` opens it). The sidebar no longer lists Connections.
- API keys for Gemini, OpenAI and the scholarly sources can be saved from Settings. They are stored in the system keychain under the service `DEIXIS`, loaded into the environment at startup, and never returned by the API. A key set in the shell or `.env` wins and cannot be changed or removed from the app. A Gemini or OpenAI key is tried with one short request before it is saved (Gemini lists models; OpenAI embeds one word), and a refused key is not saved. A key without credit is saved with that result. A provider's refusal message is not passed on, because it can quote part of the key. Source keys are not tried in advance, as before.
- The tab shows Claude Code, the Codex CLI and the Gemini CLI (path and version), and Ollama and LM Studio (whether they are installed, whether their loopback server answers, and their models, marking embedding models). Only the Codex CLI runs research steps. Ollama and LM Studio do not run steps in this version, and no citation test for local models exists yet. A missing tool can be installed after confirmation. The install runs the one command fixed for that tool (`npm install -g` for the three CLIs, `brew install ollama`, `brew install --cask lm-studio`), never a command from the request, and shows its output.
- Semantic retrieval uses the provider saved in Settings: Gemini `gemini-embedding-2`, OpenAI `text-embedding-3-small`, an embedding model on Ollama or LM Studio, or off. A provider that cannot be used now is refused, not replaced. Without a saved choice, D27's behaviour stays: Gemini when its key is set. Vectors are stored per provider and model, so changing the provider embeds passages again and keeps earlier vectors. If the chosen provider cannot run at answer time, the `semantic_retrieval` step is recorded as failed and the answer uses lexical retrieval.
- Claude and DeepSeek API keys are not offered, because no step adapter uses them.

**Evidence**: Backend tests: 305 passed (`tests/test_p4_eval.py` excluded; it does not collect). The new tests use an in-memory keychain and mocked APIs and servers, and cover: key test-then-save, removal, a refused key, a key without credit, `.env` precedence, loading at startup, unmanaged names such as `PATH` being refused, detection with a running Ollama, an install through a stub script that succeeds and one that fails, and refused semantic choices. They also cover a local embedding model ranking passages, and semantic search turned off or unable to run. The web build passed. On this computer, the Python keyring round-tripped a dummy item through the macOS Keychain. The live tab showed Claude Code 2.1.270, codex-cli 0.154.0 and Gemini CLI 0.59.0 with their paths, reported Ollama and LM Studio as not installed, and showed every key as coming from `.env`. Not verified: saving a real key through the app, a real `npm` or `brew` install, embedding through OpenAI (the key has no credit), Ollama or LM Studio (neither is installed), and LM Studio's model-type endpoint (`/api/v0/models`, with an id-based fallback).

**Impact**: Adds the `keyring` dependency (MIT). The local API can now start a package-manager install on this computer; it is limited to the fixed commands above and to loopback requests with the CSRF token. Passage text goes to OpenAI when OpenAI is chosen for semantic search.

## D28 — Choose each step role's model from any model connection

**Status**: accepted
**Date**: 2026-09-15

**Context**: The owner asked why Gemini models did not appear in the composer's model pickers while the Gemini connection was ready (D26). The web client read only the Codex model list and always sent `model_connection: 'codex'`, and a research stored one connection for all step roles, so the answer, literature and reviewer models had to come from one connection. The owner chose (2026-09-15) a connection per role over one connection switch per research. The step input contract also did not list `gemini`, so every Gemini model step in the application would have stopped with `step_input_invalid`.

**Decision**:

- A question revision stores `literature_connection` and `review_connection` next to `model_connection`, which stays the answer model's connection (migration 0016). NULL, as in every earlier research, means the role uses `model_connection`. A new research stores the literature connection whenever it has a literature model, and the review connection when its reviewer is `custom`. A revision keeps both.
- `POST /api/researches` checks each role's model and effort against that role's own connection. A role connection without its model, and a model its connection does not list, are refused; nothing is substituted.
- The composer and Settings list the models of every connection in one picker, grouped by connection. The research page and the run transcript show each role's connection.
- Cancel interrupts the current call of every connection, because the running step may be on any of them.
- The step input contract lists `gemini`.

**Evidence**: A mocked API test runs the literature and reviewer models on a second connection and the answer on the first. It checks which connection received each step, that a question revision keeps the connections, and that a model on the wrong connection, an unknown connection and a connection without a model are refused. Backend tests: 296 passed (`tests/test_p4_eval.py` does not collect, `No module named 'scripts'`). The web type check passed. Acceptance tests: 15 of 16 passed; the connections page test expects 12 planned model connections and finds 11, because Gemini left the planned list in D26. On a separate instance with temporary data, the composer listed 5 Codex and 14 Gemini models under their connection names. `POST /api/researches` stored `gpt-6-astra` on Codex for the answer and `gemini-3-flash-preview` on Gemini for literature and review, and refused the Gemini model on Codex. No model step ran with mixed connections.

**Impact**: Settings defaults already stored a connection per role and now keep the chosen one instead of always `codex`. The `model_mismatch` message no longer names Codex. Researches may now send literature or review passages to Google when a Gemini model is chosen for that role.

## D27 — Rank answer passages semantically as well as lexically

**Status**: accepted
**Date**: 2026-09-15

**Context**: Answer passages were chosen by SQLite FTS (BM25) on words from the question and the search plan, and included sources were ordered by BM25 on title and abstract. A question worded differently from the sources, or asked in another language, matches fewer words.

**Decision**: When `GEMINI_API_KEY` is set, the answer step embeds the included sources' passages (`gemini-embedding-2`, 768 dimensions, `RETRIEVAL_DOCUMENT`) and the question (`RETRIEVAL_QUERY`). Passage vectors are stored once per passage and model (migration 0015). Reciprocal rank fusion (k = 60) combines the lexical and semantic passage rankings, and each source's BM25 rank with its best semantic passage rank. User-chosen sources and provider counts still come first (D17). The work is recorded as a `semantic_retrieval` run step. If embedding fails, the step is recorded as failed and the answer uses lexical retrieval alone. Passage text and the question are sent to Google whenever the key is set.

**Evidence**: In a probe, a Turkish and an English query about underwater routing energy scored 0.825 and 0.884 against a matching English sentence, and 0.336 and 0.386 against an unrelated one. On a copy of stored research `res_4FxDPeGkCoCq4DgQTUi8` (84 included sources, 157 passages, 48-passage limit), the passages selected for the Turkish question and its English translation overlapped 0.548 (Jaccard) with lexical retrieval and 0.684 with hybrid retrieval. Hybrid changed the selection by about a quarter (overlap 0.745 and 0.811 with lexical). The first embedding pass took 4.8 s; later passes took 0.4 s. A first version fused passage rankings only and changed nothing on this research, because every source contributes its abstract before ranked passages are used, which is why source order is fused too. Nobody judged whether the selected passages are more relevant, and D17's known-paper count was not rerun. `scripts/p4_eval/semantic_retrieval.py`; results in `.local/semantic-retrieval-2026-09-15/`.

**Impact**: Retrieval without a key is unchanged. OpenAI `text-embedding-3-small` was suggested as an alternative; it is not implemented and was not compared.

## D27 — Every published citation must have a highlightable source anchor

**Status**: accepted
**Date**: 2026-09-15

**Context**: The Elicit-like source panel defaults to extracted PDF text and retains the original document in a separate PDF tab. A live answer contained citations with `anchor_text: null`; opening one showed the cited page text but could not identify or highlight the exact supporting span. Highlighting the whole page would overstate precision and could misrepresent support.

**Decision**: `missing_citation_anchor` and `anchor_not_in_passage` are validation issues. They trigger the existing single bounded repair attempt, whose message names the exact claim-passage pair. If repair still fails, the draft remains unverified and is not displayed as a source-linked answer. The UI highlights only backend-located, source-owned text; it never guesses a span from the claim. Source details open on `Plain text`; `PDF` uses DEIXIS's full-width viewer rather than the browser's embedded PDF interface.

**Impact**: Newly generated source-linked answers either provide a visible highlight for every citation or fail closed as an unverified draft. Existing stored answers are immutable and may retain anchors missing under D24; regenerating an answer is required to obtain highlights for those citations.

## D26 — Connect Gemini through the Gemini API, not the Gemini CLI

**Status**: accepted
**Date**: 2026-09-15

**Context**: The owner asked to connect Gemini Flash and to add a Gemini CLI check. On this computer Gemini CLI 0.59.0 is installed, but its Google sign-in answered `IneligibleTierError` ("no longer supported for Gemini Code Assist for individuals"). With an API key and a separate home it answered, but it adds its own agent instructions and tools (about 8,500 input tokens for a one-word prompt), and it has no response schema option.

**Decision**: The `gemini` model connection calls `generativelanguage.googleapis.com` directly with `GEMINI_API_KEY` from `.env`. Each step is one request with a system instruction, the step message and `responseJsonSchema`; no tools or instruction files are sent. Gemini 3 models offer thinking levels low, medium and high. `minItems` and `maxItems` are removed from the response schema because the API rejects them, and DEIXIS validation still enforces them. The health check reports the key, the API model list, and whether the Gemini CLI is installed with its version. The CLI does not run steps. Aliases such as `gemini-flash-latest` are not offered, because the answering model would differ from the requested id.

**Evidence**: Mocked tests cover health without a key, model filtering, a rejected key, the request body, and truncated, rate-limited and timed-out answers. The anchor measurement (D24) with `gemini-3.8-flash` at low thinking completed all six runs. Of 102 anchors, 99 were exact, 2 fuzzy at ratio 0.98 and 1 not located (ratio 0.42), with no missing anchors. None of the six answers had a validation issue; the whitespace-only anchor rule would have rejected three. Results are in `.local/anchor-measure-2026-09-15-gemini-3.8-flash-low/`.

**Impact**: The key was pasted into a conversation before it was stored in the untracked `.env`; rotate it. Pause and cancel take effect after the current Gemini request returns.

## D25 — Extract PDF text with PyMuPDF and license DEIXIS under AGPL-3.0-or-later

**Status**: accepted
**Date**: 2026-09-15

**Context**: pypdf split sub- and superscripts, kept ligature characters and was slow on long papers. PyMuPDF (MuPDF) is faster and also exposes word positions on the page, but it is AGPL-3.0 licensed (or commercial). DEIXIS had no license.

**Decision**: New PDF text is extracted with PyMuPDF (`pymupdf-1.28.2-chunks-v1`), with ligatures expanded and text outside the page box dropped. Bytes that MuPDF does not recognise as PDF still fail extraction. pypdf is removed. Passages already extracted keep their pypdf `extraction_version` and are not re-extracted. DEIXIS is licensed AGPL-3.0-or-later (`LICENSE`, `pyproject.toml`), as chosen by the project owner.

**Evidence**: On three stored papers (8, 10 and 15 pages), extraction took 0.05–0.11 s instead of 0.27–0.69 s, and ligature characters fell from 75 and 90 to 0. Single-letter words, a sign of split sub- and superscripts, fell from 21.7% to 17.6% on the 15-page paper and were unchanged (±0.3 points) on the others. MuPDF also produced U+FFFD replacement characters where pypdf had none: 37 and 335 on two papers, mostly large delimiters from TeX CMEX fonts in displayed equations, and in one paper the √ sign was not extracted. The `TEXT_CID_FOR_UNKNOWN_UNICODE` alternative replaced them with control characters, so it was not used. Hyphenated line ends were unchanged. The effect on retrieval, anchor location and answer quality was not measured.

**Impact**: Displayed equations remain garbled with either extractor. The formula rules in `PassageMathText.tsx` were written against pypdf output and may not match PyMuPDF text. Word positions are available for exact highlighting but are not used yet.

## D24 — Citation anchors locate text; they do not reject answers

**Status**: superseded by D27
**Date**: 2026-09-15

**Context**: Grounded answer schema v2 asks the model for one exact quote per claim-passage link, and the first implementation rejected the answer (repair, then unverified draft) when a quote was not a whitespace-normalized substring of the passage. pypdf text splits sub- and superscripts, hyphenates at line breaks and uses ligatures, so faithful copies can fail that check. The check also proves nothing about support: a verbatim but irrelevant sentence passes it. Semantic support is the reviewer's job.

**Decision**: A quote aimed at an uncited passage, an unknown claim, or a repeated claim-passage pair remains a validation issue. A quote that cannot be located, or a missing quote, is a warning (`anchor_not_in_passage`, `missing_citation_anchor`), listed with the answer, and the citation opens without a highlight. `locate_anchor` compares case-folded NFKC word characters with spaces and punctuation removed, then accepts one contiguous near match with ratio ≥ 0.9. The highlight uses the passage's own words, not the model's quote, stored with the evidence link together with the match kind (`exact`, `normalized`, `fuzzy`). The model instruction still asks for an exact copy.

**Evidence**: Unit tests cover exact, extraction-damaged and near quotes, and rejection of translated and spliced quotes. On 20 stored PDF pages, a lookup takes about 1 ms. Live measurement with `scripts/model_behavior/anchor_measure.py` used three stored StepInputs (44 PDF pages, 6 PDF pages, 48 abstracts), two runs each, one attempt without repair, all six completed. With gpt-5.6-luna, every call returned Codex `usageLimitExceeded`, so Luna remains unmeasured. With Claude Sonnet 5 at low effort through `claude -p` (no tools, settings, MCP or skills), the model returned 144 anchors. The whitespace-only substring check found 137 (95%). The locator found 143 (99%): 137 exact, 1 normalized (a displayed equation), and 5 fuzzy at ratio 0.99, where the model wrote "we derive" and the abstract says "and derive". The one quote not located (ratio 0.78) started before the cited passage's first word, so it crossed a passage boundary. Separately, 23 claim-passage links had no anchor, 18 of them in one abstract-only run. The old rule would have rejected 3 of the 6 answers for anchor reasons; the new rule rejected none, but one answer still failed on `duplicate_citation_anchor`. Four answers also failed `locator_in_claim_text`, which is unrelated to anchors. No observed ratio fell between 0.78 and 0.99, so the 0.9 threshold is not yet calibrated. Results and raw outputs are in `.local/anchor-measure-2026-09-15-sonnet-low/results.json`.

**Impact**: Migration 0014 adds `anchor_text` and `anchor_match` to `evidence_links`. Answers are no longer downgraded for quote copying errors. The Sonnet result does not transfer to Luna; run the same measurement with gpt-5.6-luna when Codex usage is available.

## D23 — Query Unpaywall before other PDF-location providers

**Status**: accepted
**Date**: 2026-09-15

**Context**: OpenAlex and Crossref exposed candidate URLs for 14 of the 16 direct packet-size sources, but none produced a validated PDF. Unpaywall is a free DOI lookup service that requires a contact e-mail rather than an API key and can expose repository copies that the other metadata responses omit.

**Decision**: The PDF resolver queries Unpaywall first with `DEIXIS_CONTACT_EMAIL`, retains every `oa_locations[].url_for_pdf` candidate, and then still queries OpenAlex and Crossref so provider evidence is complete. The same DOI and version gates apply before retrieval. A missing contact e-mail is stored as `auth_required`; HTTP, rate-limit, parse and retrieval failures remain visible. Search-result rows identify Unpaywall with a green open-lock icon. Web Search remains the final, explicitly labelled fallback.

**Evidence**: Mocked tests cover all PDF locations, duplicate removal, DOI identity, version matching, and the missing-email path. In the fresh 16-source Kurt measurement, Unpaywall returned same-version candidates for two sources; both URLs returned HTTP 403 and duplicated locations already known through OpenAlex. Crossref again exposed 12 URLs that returned HTML rather than PDF. The validated result therefore remained 0/16. Evidence is retained locally in `.local/p4-eval-2026-09-15-packet/pdf-coverage-v4.json`.

**Impact**: Migration 0013 extends discovery provenance with `unpaywall`. No API key is stored. Unpaywall improved provenance for this set but did not improve PDF recall; institutional browser access or a user-supplied PDF is still required for the two gated copies.

## D22 — Preserve PDF candidates and make acquisition failures visible

**Status**: accepted
**Date**: 2026-09-15

**Context**: A source version previously stored one `oa_pdf_url`. Alternative locations, the provider that supplied each location, and failed attempts such as HTTP 403 or an HTML response at a `.pdf` URL were lost. In the Kurt direct packet-size set, that made metadata-only records look as if no PDF acquisition had been attempted.

**Decision**: A source can now retain every PDF candidate reported by OpenAlex `locations` and Crossref `link`, with provider, DOI identity state, version state, license, URL and retrieval outcome. Only a DOI-verified candidate whose version equals the source record is downloaded and attached. If those candidates yield no verified PDF, a separately labelled SerpApi Google Scholar Web Search uses the exact title and records PDF resources as candidates; web candidates remain version-uncertain and are not attached automatically. Discovery and zero/failure outcomes are stored even when they produce no candidate. The Sources UI shows the provider searches, HTTP status, version state and retrieval status; it offers **Open at publisher** and a per-source **Attach PDF** action for a user-obtained copy.

**Evidence**: Mocked tests cover all OpenAlex locations, Crossref `vor`/`am` mapping, a first same-version URL returning HTTP 403 followed by a successful second URL, web fallback after metadata candidates fail, the ban on automatically downloading a version-uncertain web candidate, API visibility and attaching a user PDF to the existing source. In the live 16-source Kurt measurement, OpenAlex/Crossref listed candidate URLs for 14 sources. None yielded a validated PDF: 12 IEEE Crossref links returned HTTP 200 with non-PDF content, and two publisher links returned HTTP 403. The exact-title Web Search produced candidate PDFs for six sources; their versions were not established, so none was attached. The verified-PDF result is therefore 0/16. The first over-constrained title+DOI+`filetype:pdf` probe and its 0/16 result are retained locally as diagnostic evidence; the corrected run is `.local/p4-eval-2026-09-15-packet/pdf-coverage-v3.json`.

**Impact**: Migration 0011. A listed link and a found, validated PDF are separate states. Web candidates can still include unrelated works and require user inspection. Institutional browser access remains manual; the app does not manage publisher credentials or claim that HTTP 403 proves a subscription requirement. Unpaywall and Semantic Scholar are sensible later resolver stages, and structured extraction/OCR remains P5 work.

## D21 — Read short attached PDFs fully and inspect same-version OA locations

**Status**: accepted
**Date**: 2026-09-15

**Context**: In the attached-only Kurt packet-size test, 44 extracted PDF chunks from ten physical pages fit under the standard 48-passage limit, yet the six-passages-per-source cap supplied only six chunks and omitted page 5. That page explains the separate link-power minimization and the selection of packet size by comparing MIP solves. In academic search, the OpenAlex adapter read only `best_oa_location`, which may not be a PDF of the source record's version.

**Decision**: When exactly one source is included in an attached-file scope and all its extracted passages fit within 48 passages, 12 physical pages and 60,000 characters, supply all passages in page order. Larger and mixed corpora retain the existing bounded ranking and six-passages-per-source cap. The OpenAlex search adapter also reads `locations` and prefers an OA PDF whose version equals the primary record's version; a different-version `best_oa_location` remains a separate version. The answer method now explicitly distinguishes variables in the displayed formulation from local precomputation and candidate values compared across repeated solves.

**Evidence**: The read-only replay of the stored Kurt research changed its answer input from six chunks on pages 1, 2, 4 and 8 to all 44 chunks on pages 1–10, including all five on page 5. A fresh isolated Luna answer cited page 5 and described the separate link-power minimization and packet-size comparison, but also contained claims implying that the MIP itself selects power levels. A second answer after the method change cited page 5 and named the local power problem, but still described packet size as directly optimized by the MIP and omitted the repeated-solve selection rule. These are two stochastic, in-sample answer runs, not a semantic correctness pass. An OpenAlex live query returned `locations` (two entries); mocked tests cover same-version selection. The prior four-DOI probe for included direct packet-size works found no PDF URL, so this adapter change does not resolve those four works. The backend suite passed 267 tests.

**Impact**: No migration. Short uploaded PDFs can substantially increase answer input size. Supplying all extracted text does not verify math extraction or the model's interpretation. Subscription PDFs still require an authenticated/user-provided path; an unverified web result must not be attached to a publication record. P5 needs a provenance-preserving candidate resolver with explicit DOI, version, access and failure states, plus an evidence-level check that the final answer distinguishes separate optimization stages.

## D20 — Reserve bounded answer room for formulation pages and warn about unsupported math

**Status**: accepted  
**Date**: 2026-09-15

**Context**: D19 asks for equations and model details, but retrieval previously selected an abstract per source before other PDF passages. A retrieved formulation page could be omitted even when it stated variables or constraints. Abstract-only evidence cannot establish an equation that appears only in full text.

**Decision**: After the first passage per included source, retrieval gives qualifying `pdf_page` passages up to one quarter of the answer-passage limit before filling remaining room by text match. A passage qualifies at lexical score 3 or above: 2 points per optimization phrase and 1 per math symbol (symbols capped at 6); the six-passages-per-source cap still applies. Validation adds non-blocking `math_not_well_formed` warnings for unbalanced dollar delimiters, braces or LaTeX environments in claims, limitations and unanswered aspects, and `math_without_full_text` for a mathematical claim whose cited passages are all abstract-level. The warnings appear with the other answer checks.

**Evidence**: Focused tests place an explicit formulation page before a better full-text-match page and cover malformed math and abstract-only mathematical claims. The 2026-09-15 backend suite passed 262 tests, the web build succeeded, and Playwright passed 15 tests. The three UWSN report runs below predate this retrieval/check change and read no PDFs. In the later packet-size live test (`.local/p4-eval-2026-09-15-packet/analysis.md`), two academic PDFs were downloaded but all 48 answer-input passages and all 57 cited links were abstracts: the first-passage-per-source loop filled the budget before the formulation-page reservation. A separate attached-only Kurt PDF test did pass six PDF-page chunks, including Figure 1 on page 4, but missed the requested packet-size choices and power-selection procedure on page 5. These observations test the feature's limits, not semantic claim correctness. No screenshot of the math-warning display was captured.

**Follow-up measurement**: In an isolated copy of the packet-size research, reserving one PDF formulation page per source gave the model 46 abstracts and two PDF pages instead of 48 abstracts. Neither PDF page was cited, and direct packet-size coverage stayed at 8 found, 4 given, 3 cited of 16; the experimental answer cited 18 works versus 25 in the preceding answer. This single stochastic comparison does not prove a regression, but gives no reason to keep unconditional reservation, so the code change was reverted. Only four of 84 included source versions had a matching-version open PDF URL; two downloaded and two returned HTTP 403. A separate four-DOI OpenAlex `locations` probe found no PDF URL for the four included direct packet-size works. Evidence and exact limits are in `.local/p4-eval-2026-09-15-packet/analysis.md`.

**Impact**: No migration. This is a lexical preference, not verification that a page contains a correct or complete model. The `s.t.` pattern was tightened after review so it no longer matches bare `st`; one occurrence of “constraint” plus `=` still reaches the threshold, so false positives can use reserved room. When included abstracts fill the passage limit, the reservation has no effect even if PDF pages exist; within one PDF the lexical score can also crowd out a different page needed by the question. The balance check does not establish that LaTeX renders or that the cited page supports the equation. Warning messages remain English even when their UI labels are translated.

## D19 — Write the answer as a sectioned report with LaTeX math; phrasing checks only warn

**Status**: accepted  
**Date**: 2026-09-15

**Context**: The user found live answers too short. They had five claims of one sentence each, and each claim cited up to eight sources under "Çeşitli çalışmalar". The user asked for a comprehensive report with equations shown as LaTeX. Four rules produced the short form:

- The method asked for "a small number of claims", each "one statement".
- D15's per-sentence frame check allowed one repair, then rejected the answer. That favoured few, safe sentences.
- The several-sources rule and the eight-citation cap rewarded lumping sources together.
- Answers were a flat list of claims with no sections.

The checks also cost answers. In D17's runs, two of three answers failed D15's checks after the repair, and so did the first UWSN run. The user decided on a comprehensive report, and that the phrasing check warns without rejecting.

**Decision**:

- `GroundedAnswerDraft` allows up to 60 claims (was 20). Each claim now requires `section`, the heading of its report section (1–120 characters). Claim text allows up to 2000 characters (was 1200), and each claim cites at most 5 passages (was 8). `AnswerReview` allows up to 60 reviews. The schema version stays `v1`.
- Migration 0009 adds `claims.section`. The research view returns it, and the Answer tab shows consecutive claims with the same heading as one section.
- The method asks for a comprehensive report. It opens with an overview that answers the question, gives one section to each part of the question and closes with a comparison or open issues when the passages support one. The report covers each relevant source instead of a few representative claims. A claim is one to three sentences about one point and cites its specific passages.
- Mathematical content is written in LaTeX, `$…$` inline and `$$…$$` displayed, and only as a cited passage states it. Equation numbers are still locators, and `locator_in_claim_text` still rejects them. The Answer tab renders math with KaTeX 0.16 without `trust`; an expression KaTeX cannot parse is drawn in red, not thrown.
- D15's `sentence_without_phrasebank_frame`, `own_work_phrase_in_claim` and `plural_sources_for_one_source` are now warnings. They are stored with the answer's validation, listed under the answer, and never trigger a repair. Before the check, each math span counts as one slot word. The frames remain the writing guidance; D15's rejection rule is superseded.

**Evidence**: At implementation, all 255 backend tests passed, including math counted as one slot word, the three phrasing findings as warnings, and fixtures and fakes updated with sections. Three later live `gpt-5.6-luna` runs on the same UWSN question (`.local/p4-eval-2026-09-15-report-run{1,2,3}`) produced structurally valid answers with 18, 14 and 14 claims and no validation issues. They cited 2, 3 and 3 of the 33 reference-list sources, respectively. Their cited evidence links were all to abstracts (31, 20 and 23 links; no PDF pages), so these runs establish report generation and structural validity, not equation-level grounding or claim correctness. The reference-list strata are a draft, and the human claim/relevance review is still open.

**Impact**: Migration 0009. Answers, their model calls and review inputs are longer. Answers saved earlier have no sections and show as one untitled section. Structural checks, including citation, locator and schema checks, still send an answer to repair and can leave an unverified draft. A sentence that follows no frame can now be shown. Text holding two literal dollar signs on one line renders as math.

## D18 — Continue discovery when a provider search fails

**Status**: accepted  
**Date**: 2026-09-15

**Context**: Under case E, a failed provider search paused the whole run, and no other provider was used in its place. With eight providers, one provider's outage stopped every search. On 2026-09-15 arXiv refused all requests for about 7.5 minutes: first HTTP 429 "Rate exceeded.", then read timeouts. Two measurement runs stalled on arXiv, and a third used up its provider-request budget on arXiv retries. The user decided that the search continues with the other providers.

**Decision**: A failed search is still recorded with its status, and its step is still marked `failed` or `outcome_unknown`. `_search` now returns the failure instead of pausing, and discovery goes on to the remaining queries and screening. The run pauses on a provider failure only when none of its searches succeeded. Resuming such a run retries its failed searches. A run with at least one successful search does not retry failed ones on resume, so a timed-out SerpApi request is not paid twice unasked. No provider replaces another. The Answer tab lists the searches that did not complete, with provider and status, and says that the other searches' results are used; "Search again" retries all of them.

**Evidence**: A mocked-HTTP test covers one run where Crossref returns 429 and OpenAlex succeeds. The run completes, keeps the rate-limited search run and screens the OpenAlex record. A single rate-limited query still pauses the run (`test_provider_rate_limit_pauses_without_fallback`).

**Impact**: No migration. A completed discovery run can lack a provider's results. The answer step is not told which searches failed, so its limitations do not mention them; only the Answer tab does.

## D17 — Order included sources for the answer step by user choice, provider agreement and text match

**Status**: accepted  
**Date**: 2026-09-15

**Context**: After D13, standard-depth runs included 80–84 sources, but the answer step takes one passage per source up to `max_answer_passages` (48) in selection-time order. In the three all-provider runs, 7–8 of the 12 known direct-or papers were found and 6 included, but only 3–4 reached the model. An offline check on those runs compared five orderings of the included sources. Selection time put 3, 3 and 4 known papers into the first 48, text match 5, 5 and 4, and best search rank 3, 3 and 4. Ordering by the number of providers that returned a source, then text match, put 6, 6 and 5.

**Decision**: `flow.answer_source_order` orders included sources before the first-passage loop of `_retrieve`. Sources the user chose come first, then sources returned by more distinct providers (bioRxiv counts as OpenAlex, since it is searched through OpenAlex). Ties are broken by BM25 (k1 1.2, b 0.75) of title plus abstract against the question and search-plan terms, then by selection order. `Store.answer_order_facts` supplies the user-choice flag and provider count. The remaining-room loop by best match is unchanged.

**Evidence**: Unit tests cover the facts query and the order. Three live `gpt-5.6-luna` runs with the P4 question (`.local/p4-eval-2026-09-15-order-run{1,2,3}`) gave 9, 7 and 6 of the 12 direct-or papers to the model, against 3, 3 and 4 before. Only run 3's answer was valid; it cited 6. Runs 1 and 2 failed D15's phrasing checks after one repair (`plural_sources_for_one_source`, `own_work_phrase_in_claim`), so they cite nothing. Runs 1 and 2 first stalled on arXiv 429s and timeouts for about 7.5 minutes and were rerun.

**Impact**: No migration. Preprints from a single provider (arXiv, bioRxiv) and sources only one provider found move down. In the offline check, arXiv/bioRxiv sources in the first 48 fell from 10–11 to 5–6. The provider count rewards overlap between indexes, not relevance, and is a weak signal in a scope with few providers. Cited counts in these runs are not comparable with runs before D15, which added a stricter answer check.

## D16 — Export bibliographies as BibTeX/RIS and import a Zotero collection read-only

**Status**: accepted  
**Date**: 2026-09-15

**Context**: The implementation plan names BibTeX/RIS as the bibliography export, and the dated handoff kept Zotero out of the first release's required scope. On 2026-09-14 the user decided to finish the export first and then, before the P4 evaluation, add a read-only import of a Zotero collection, through both the Zotero desktop app and zotero.org. Zotero is not installed on the development machine.

**Decision**:

- `GET /api/researches/{id}/bibliography?format=bibtex|ris&sources=included|cited` downloads the included sources or the sources cited in the latest answer (`workflow/bibliography.py`). Entry types follow Zotero's import translators (journal `@article`/`JOUR`, proceedings `@inproceedings`/`CONF`, chapter `@incollection`/`CHAP`; preprints and unknown types `@misc`/`GEN`); arXiv records add `eprint` with `eprinttype = {arxiv}`; the source version DEIXIS read goes into `note`/`N1`, since neither format has a version field. The Sources tab offers the included set and the answer's reference list the cited set.
- `GET /api/zotero/collections?source=local|web` lists collections by path; `POST /api/researches/{id}/zotero-imports` imports one collection's own items, not its subcollections, at most 100 (`providers/zotero.py`). `local` reads Zotero's local API on 127.0.0.1:23119 without a key once the user turns it on in Zotero; `web` reads api.zotero.org with `ZOTERO_API_KEY` and `ZOTERO_LIBRARY_ID`, the names pyzotero uses (`ZOTERO_LIBRARY_TYPE=group` reads a group library). Only GET requests are sent; the local path reads only the signed-in user's library. The home composer's "Add sources" menu can choose a collection before the research exists (switching "Academic search" to "Files + academic search"); it is imported right after the research is created, before the search starts. On a research page the same panel is under Sources.
- An imported item is handled like an attachment: accepted only when the source scope includes attached files, included with origin `user`, added as `zotero_import` (migration 0008 rebuilds `corpus_memberships` for the new value) and never screened. Its metadata becomes a source version with a `zotero` mapping (`local:<key>` or `web:<key>`), its abstract note an abstract passage, and its first readable PDF an asset read page by page. Importing again reuses the source version and adds no second PDF.
- Zotero records no paper version, so an imported source has no version label ("version not stated") and never merges with a provider record of the same DOI. A local PDF is read from the file:// path Zotero names (linked files included, at most 50 MB, must start with `%PDF-`); a zotero.org PDF is downloaded from the storage redirect through the public-address fetch without the key, and a linked file is reported as not stored there. The raw Zotero rows are kept as a provider payload; the key never enters them.

**Evidence**: Mocked API tests cover the BibTeX and RIS mapping, escaping and unique keys, the export download and its empty cited set, a local import with three PDFs and an idempotent repeat, zotero.org paging with the key sent only to api.zotero.org and a linked file reported, and the not-running, turned-off, unconfigured and wrong-scope refusals. A keyless live run of the web code path against the public library users/475425 (2026-09-15) listed 15 collections with nested names, read one collection in two pages (30 rows, 20 items with authors and DOIs) and downloaded a 329 KB PDF through the storage redirect. The local path was checked only against Zotero's `server_localAPI.js` and its documentation. No import from a real desktop Zotero or a keyed zotero.org account, and no exported file opened in Zotero, has been run.

**Impact**: Migration 0008. A research used to measure known-source recall in P4 should not import the known set from Zotero: imported items are included by the user, not found by search. The same item imported both locally and from zotero.org appears twice, and a Zotero item and a search result with the same DOI stay separate sources without a suspected-duplicate flag. BibTeX authors are written as stored display names, so reference managers may split organization names.

## D15 — Write answer prose on Academic Phrasebank frames and check every sentence

**Status**: accepted  
**Date**: 2026-09-15

**Context**: The user asked that the report, the grounded answer, be written strictly with Manchester Academic Phrasebank frames, that Turkish answers use literal translations of those frames, and that the frames be versioned in the repository so no user depends on the PDF. Under written rules alone, a live `gpt-5.6-luna` answer described a cited source as "this study", and Turkish answers did not render the frames consistently.

**Decision**: `methods/deixis-research/references/academic-phrasebank/phrases.txt` holds 1618 frames converted once from the 2015 enhanced edition (one frame per line under section headings, `{a | b}` alternatives). Nine frames damaged by the conversion were repaired by hand. Each frame is followed by a `tr:` line, a literal Turkish rendering written by Claude Sonnet subagents and checked by script for equal alternative groups and slots. Only the answer step loads the file, with the Turkish renderings for a Turkish question. Validation checks every sentence of claims, limitations, unanswered aspects and the capability notice. A sentence must keep, in order, at least 70% of the fixed words of the alternatives it uses from one frame (`sentence_without_phrasebank_frame`). The writer's own-work words ("this study", "bu çalışma") are not required frame words, since answers write "this answer" or "the supplied passages" instead. A claim that uses them is rejected (`own_work_phrase_in_claim`), and so is a one-source claim that speaks of several sources, such as "previous studies" or "önceki çalışmalar" (`plural_sources_for_one_source`). A Turkish -DIK participle counts as a frame's "olduğu". Failures use the existing single repair. An answer in a language without frames gets the `phrasing_not_checked` warning.

**Evidence**: Offline, none of 13 free-form English and Turkish sentences passed. Of the sentences in the live answers, 19 of 20 English and 29 of 35 Turkish passed; the rest follow no frame. With one repair, two English answers on package `sha256:3f69a9a6de0…` were valid on the first attempt. Two Turkish answers on the preceding revision, which differs only in one English example of the Phrasing rules, were valid after one repair and on the first attempt. Behavior cases MB01–MB07 on `sha256:3f69a9a6de0…` passed every automatic check on their single attempt. Earlier on the same day, before a misleading "One study … examined …" example was removed from the rules, 4 of 8 first attempts failed the frame check. Evidence files are in `.local/phrasebank-check-2026-09-14/` and `.local/model-behavior-2026-09-15/` (local, not versioned).

**Impact**: The answer step's input grows from about 5,000 to about 39,000 tokens, and Turkish answer calls used about 55,000 tokens. More answers need a repair call. The check is formal: it does not decide whether a chosen frame fits what a passage says. For example, one live English limitation kept "The study is limited by …" instead of "This answer …". The Turkish renderings have not been reviewed by a native translator. The phrasebank text is copyrighted by The University of Manchester and is versioned at the user's decision in a public repository; `distribution_review` remains `not_done`.

## D14 — Choose separate literature and reviewer models; review answers in the background

**Status**: accepted  
**Date**: 2026-09-14

**Context**: One chosen model ran every model step. The user asked to choose, on the home page, a separate model for the literature search (a "subagent" model), and a reviewer model that reviews work in the background when it completes, set once for all researches and overridable per research. The user chose (2026-09-14) that the literature model runs the search plan and screening, and that the reviewer checks an answer's claims against their cited passages. The earlier method design kept one main agent and started another model's review only on a separate user request ([research methods](methods/research-methods.md), implementation plan §2).

**Decision**:

- A research stores a literature model and reasoning effort with its question revision (migration 0007). The search plan and screening run on it; the answer runs on the research model. Researches created earlier have none and keep searching with the research model. Steps still run one at a time: this is a model per step role, not concurrent agents.
- The reviewer is set app-wide in Settings (`app_settings`, `PUT /api/settings/reviewer`) and per research as `default` (the app-wide setting when the review starts), `custom` (its own model) or `off`. With no app-wide model set, `default` reviews nothing.
- Settings also keeps optional answer and literature defaults (`PUT /api/settings/answer|literature`). They only prefill the composer while Codex still lists the model; a research stores the models it was created with, so changing a default never changes an existing research. The composer shows the three choices as one "Models" button that opens the per-research pickers.
- When an answer run saves a structurally valid answer and a reviewer applies, the same run adds an `answer_review` step. The reviewer receives the claims and only the passages they cite, and returns one verdict per claim (`supported`, `partially_supported`, `not_supported`, `cannot_assess`) with a reason (`AnswerReview` schema, `references/answer-review.md`). The result is stored in `answer_reviews` and shown next to each claim as an additional model assessment. It never changes the answer, its claims or its evidence links.
- A review failure (connection, model mismatch, budget, invalid output after one repair) is recorded as a failed review with its reason and does not pause the run; a user pause or cancel still stops it. Every chosen model and effort must be listed by the connection; nothing is substituted.

**Evidence**: Mocked API tests cover the model and effort sent per step role, the fallback for a research without a literature model, refusal of unlisted or incomplete choices, per-role defaults in Settings, the app-wide default with `custom` and `off` overrides, and a failed review that leaves the run completed and the answer unchanged; a contract test covers AnswerReview coverage rules. A browser run against the fixture server showed the three pickers, the Connections default and per-claim verdicts. One live `answer_review` turn with `gpt-5.6-luna` (2026-09-15) on the synthetic A fixtures plus one planted claim its passage does not state returned schema-valid output with no tool items, marked the three fixture claims `supported` and the planted claim `not_supported`. That is one execution on synthetic records; the reviewer's behavior on real answers is not measured.

**Impact**: For answers, supersedes the rule that another model's review starts only on a separate user request; the user-started review of candidates and reports stays as designed. Changes the method package hash (new runtime file). An answer run makes up to two more model calls within the same budget. A reviewer verdict is not semantic verification: `semantic_review` on evidence links stays `not_checked`.

## D13 — Connect all scholarly providers with per-provider query rules and DOI merging

**Status**: accepted  
**Date**: 2026-09-14

**Context**: Under D9 and D11, six live `gpt-5.6-luna` runs with OpenAlex alone found at most 4 of the 12 user-known direct optimization papers; 20 of the 22 known papers are IEEE publications. The user decided to connect every provider in product scope. The implementation plan requires a recorded, secret-free request per call, distinct failure statuses, bounded retries inside the budget, SerpApi only as supplementary coverage, and title matches recorded as `suspected_duplicate` without automatic merging.

**Decision**:

- Adapters for Semantic Scholar, Crossref, arXiv, IEEE Xplore, Scopus and SerpApi join OpenAlex (`backend/deixis/providers/`). They share one record shape, the existing status vocabulary and one HTTP path (`common.send`): a 429 is retried at most twice when the provider's wait is unstated or at most 10 seconds, and each retry counts as a provider request; another 4xx is `rejected_not_executed`; a 5xx leaves delivery unknown. Key values never enter request descriptions, errors or stored payloads. A failed search still pauses the run.
- A new research enables every provider with the access it needs (OpenAlex, Semantic Scholar, Crossref and arXiv always; IEEE Xplore, Scopus and SerpApi when their key is set), and the model chooses which to query. Budgets: quick 3 queries; standard 8 queries, 150 candidates, 12 model calls; detailed 12 queries, 200 candidates, 14 model calls. A SearchPlan may hold 12 queries.
- Query rules follow live probes and send a malformed query back for repair: OpenAlex's D11 limits also apply to IEEE Xplore (which answers an unbalanced query with zero records instead of an error) and inside a required Scopus field group such as `TITLE-ABS-KEY(...)`; arXiv terms need a field prefix and explicit AND/OR/ANDNOT (`abs:molecular communication` matched 199,262 records, `abs:"molecular communication"` 476); Semantic Scholar and Crossref take at most eight plain words (Crossref ranked quoted and unquoted forms identically); SerpApi gets at most one query per plan and never the only one.
- The same normalized DOI from several providers is one source version with a mapping per provider, since a DOI names one registered version. arXiv's DataCite DOI names every version of a preprint, so arXiv records never merge. A preprint naming a record's DOI (`published_doi`) or an equal normalized title records a `suspected_duplicates` pair (migration 0006) that the Sources tab shows; nothing is merged. A record found by several searches keeps its best rank, and candidates interleave by rank so the candidate limit keeps every query's first results.
- bioRxiv is added at the user's request as an eighth provider. Its own API has no keyword search (`api.biorxiv.org/search/...` answered 404; `/details` looks up by DOI or date), so the `biorxiv` connector searches OpenAlex restricted to works with a bioRxiv location (`locations.source.id:S4306402567`) under OpenAlex's query rules. It adds a dedicated slot for bioRxiv records, not an index independent of OpenAlex.
- Access stays version-safe: arXiv PDFs attach to their own version (`arXiv vN`); Semantic Scholar PDFs (no version label), IEEE Xplore sign-in pages and Google Scholar links are not attached. Scopus records carry no abstract (`view=COMPLETE` answered 401 for the configured key). SerpApi snippets are search-page excerpts and are not stored as abstracts. Citation counts still come only from OpenAlex.

**Evidence**: One live search per connector through the adapters (2026-09-14) returned `completed` for all seven, keyed for OpenAlex, Semantic Scholar, IEEE Xplore, Scopus and SerpApi and keyless for Crossref and arXiv; no key value appeared in the recorded description, error or payload. Keyless Semantic Scholar answered 429 to two probes in a row. The SerpApi account showed 213 of 250 monthly searches left before two probe searches. Mocked tests cover each connection's record mapping, zero results, retried and unretried 429s, auth, rejected, unknown, parse and network outcomes, result caps, key redaction, query rules, DOI merging, suspected duplicates and a two-provider discovery run.

**Measurement** (three live `gpt-5.6-luna` runs on the same question with the seven providers, before bioRxiv was added; `.local/p4-eval-2026-09-14-providers-run{1,2,3}`, compared with `measure.py compare`): every plan was valid on its first attempt, every search completed (8 per run, 7 providers in runs 1 and 2, 6 in run 3), and every answer was structurally valid on its first attempt. Of the 12 direct optimization papers, the runs found 8, 8 and 7 (the six earlier OpenAlex-only runs: 2 to 4), included 6 in each (earlier 2 to 4), gave 3, 3 and 4 to the answer model and cited 3, 1 and 3 (earlier 0 to 3). None of the 10 related or adjacent papers was found (earlier runs found at most 1). Unique works rose to 159–169 and included sources to 80–84. The answer step takes at most 48 passages, so about half of the included sources, and half of the included known papers, never reached the answer model. The live identity check matched 20 of 26, 20 of 26 and 14 of 19 DOIs; every miss was an arXiv DataCite DOI that Crossref does not hold, except one `10.5555/2442691.2442703` DOI in each run. Three runs, no relevance or claim judgements yet.

**Impact**: Changes the method package hash and the search-plan contract's query limit. A provider outage or exhausted SerpApi quota pauses a run that queries it. Scopus-only and SerpApi-only records are screened on titles. The recall limit has moved from search to the answer input: found and included known papers now outnumber those given to the answer model. The P4 identity check needs a DataCite lookup for arXiv DOIs.

## D12 — Show the answer step short citation handles instead of record IDs

**Status**: accepted  
**Date**: 2026-09-14

**Context**: D11's open issue: with 48 sources and 48 passages, Luna mis-copied long record IDs. On `res_oDmOBhdosiLgHYr0taJc` both answer attempts before this change failed validation (`unknown_passage_id` 3 and 1, `envelope_mismatch`, `duplicate_passage_id`) and the answer stayed an unverified draft.

**Decision**: The grounded-answer step message shows per-step handles (`psg_P0000001`, `srv_S0000001`) in place of passage and source IDs. The stored StepInput keeps the record IDs; the application maps handles in the model output back to them before validation (`contracts.with_citation_handles`, `contracts.resolve_citation_handles`, called in `flow._model_step`). Text that is not a handle is left for validation to report.

**Evidence** (live `gpt-5.6-luna`, same research, 48 sources and 48 passages, a step message of about 86,000 characters): the first run with handles (20:10 UTC) had no ID or envelope issue in either attempt; both failed only on the then-new `sentence_without_phrasebank_frame` check (12 and 13 issues). After that check's work was finished, a re-run (20:19 UTC) was structurally valid on its first attempt: 7 claims, 43 evidence links to 28 passages of 28 sources, and no record ID in the raw output. This is one research and three attempts, not a measured rate. The Turkish answer was not phrasing-checked: validation gives a `phrasing_not_checked` warning until Turkish frames exist, and stored `validation_json` keeps issues but not warnings.

**Impact**: Closes D11's open issue for this case. Stored StepInputs, evidence links and the UI still use record IDs. Larger answer inputs remain to be measured.

## D11 — Limit OpenAlex query shape and measure known-source recall by stratum

**Status**: accepted  
**Date**: 2026-09-14

**Context**: Three live `gpt-5.6-luna` runs under D9 on the same question found 4, 2 and 4 of the 12 user-known direct optimization papers (none of 10 related or adjacent ones). The run that found 2 used queries such as `"molecular communication" routing scheduling optimization`, where every unquoted word is required (1 result). Offline, a broad `"molecular communication" AND (optimization OR …)` query placed 1 of 22 known papers in its first 25 results, while focused two-part queries (the core phrase AND one family of specific terms) placed 5 each. A read-only consultation with Codex `gpt-5.6-sol` (medium) ranked query shape as the dominant cause and advised stratified measurement (`.local/consult-search-recall-*`, local, not versioned). The third run's answer, given 48 sources and 48 passages, cited an ID it was not given twice and stayed an unverified draft.

**Decision**: Search-plan validation rejects an OpenAlex query with more than two AND-joined parts, more than five AND/OR/NOT operators or three unquoted words in a row, and a plan whose OpenAlex queries quote no multiword phrase (`provider_query_shape`); the method reference states the focused form. The measurement kit groups known sources with `# stratum:` lines, reports found, included, given and cited per stratum, measures runs without a citable answer, adds per-source relevance boxes for included precision, and compares runs (`measure.py compare`). A code-built base query is not added: the ranking evidence showed a broad query does not bring known papers into the results that are read.

**Impact**: Changes the method package hash. More search plans need a repair call. The shape limits are OpenAlex-specific; other providers need their own rules. The stratum classification of the known set is a draft pending the user's confirmation, and included precision needs the user's relevance marks.

**Open issue (recorded, not yet addressed)**: since D9 gives the answer step every included source (48 sources and 48 passages, a step message of about 89,000 characters), two of four such live answers stayed unverified drafts because Luna mis-copied identifiers in both attempts: it cited a source's random suffix with the passage prefix (`psg_7WiQ…` for source `srv_7WiQ…`), dropped a character from a passage ID, and truncated the package hash. The answers that succeeded had 26 and 48 sources. Likely cause: too many long opaque identifiers in one step. To be solved separately, for example with short per-step citation handles mapped back by the application, or smaller answer inputs.

## D10 — Remove the browser-only UI prototype

**Status**: accepted  
**Date**: 2026-09-14

**Context**: D2 started `apps/web/` from a copy of `prototypes/shadcn-ui/` and kept the prototype untouched. The working UI now lives in `apps/web/` with its own icons and styles; no code, test, script or build step reads the prototype.

**Decision**: Delete `prototypes/`. It remains recoverable from commit `84ba12d`. This supersedes the prototype placement in D1 and the "stays untouched" clause in D2.

**Impact**: Live docs no longer link to it. The dated handoff (`docs/desktop/`) and `docs/product/plan-review-2026-09-14.md` keep their historical prototype references, which now point to a removed path.

## D9 — Read more search results, give every included source to the answer, show citation counts

**Status**: accepted  
**Date**: 2026-09-14

**Context**: The P4 known-source check on a live `gpt-5.6-luna` research (22 user-known papers) found 3 and cited none. The four OpenAlex queries matched 12 of the 22, but standard depth read only the first 7 results of each (of 295, 33, 45 and 49), and the answer step received 11 of the 19 included sources because half its 14-passage limit went to abstracts in selection order. The user also asked to see each paper's citation count.

**Decision**: Each depth sets results read per query (quick 10, standard and detailed 25) separately from the candidate limit (20, 100, 150). Screening asks for proposals in batches of 40 candidates per model call; the model-call limits (6, 10, 12) cover the search plan, the batches and the answer with one repair each. The answer step first gives every included source one passage (its abstract, else its best-matching passage), then fills the remaining room with the best-matching passages, at most 6 per source; the passage limits are 16, 48 and 80. OpenAlex `cited_by_count` is stored with its retrieval date (migration 0005), replaced when a record is found again, and shown on source rows and in source details as an OpenAlex count. It is not given to the model.

**Impact**: Discovery costs more model tokens and time. Runs created earlier keep their stored budgets, split across their queries as before. When more sources are included than the passage limit, sources beyond it are still not given, and the answer's "provided" count shows this. Citation counts differ between indexes and are absent for records found before this change until they are found again.

## D8 — Check locators in claim text and OpenAlex OR syntax; record A–G acceptance and P4 measurement

**Status**: accepted  
**Date**: 2026-09-14

**Context**: D6 left locator assertions inside claim text unchecked (case B). A live P4 run with `gpt-5.6-luna` produced four OpenAlex queries of the form `"molecular communication" optimization OR scheduling`; OpenAlex silently ignores terms beside an unparenthesized OR, so every query returned the same seven generic works (probe: the count equalled the phrase-only count). P4 needs a recorded browser-level A–G run and a measurement on a user-known source set.

**Decision**: Answer validation rejects claim text containing a page, equation, table, figure, section or DOI locator (`locator_in_claim_text`); the draft goes through the existing repair step and, if repeated, stays an unverified draft. Search-plan validation rejects an OpenAlex query that mixes OR with other terms outside parentheses (`provider_query_syntax`) and tells the model the parenthesized form. A Playwright suite (`apps/web/e2e`, system Chrome, fixture server in `tests/acceptance/` with mocked OpenAlex, fixed PDFs and a scripted `codex` adapter) records screenshots for cases A–G, including a backend restart. `scripts/p4_eval/measure.py` separates automated link and reopen checks, a live Crossref identity check, and a human review sheet (claim verdicts, missed evidence, known-source coverage, correction minutes). Excluding a source can carry a user reason, answer references show the cited version, and opening a source from quick find scrolls to the Sources tab.

**Impact**: No migration. The locator check is a pattern match: it can refuse a claim that mentions a page for another reason, and it does not detect a wrong locator written without those words. Answers already stored are not re-checked. The acceptance suite uses synthetic data and a scripted model, so it tests the product's handling, not model quality; the P4 exit still needs the human review.

## D7 — Let the user choose the model's reasoning effort

**Status**: accepted  
**Date**: 2026-09-14

**Context**: The composer offered a research depth (a call and candidate budget) but no way to set how long the chosen model reasons. Codex `model/list` reports each model's supported reasoning efforts and its default, and `turn/start` accepts an `effort` value.

**Decision**: A research stores an optional `reasoning_effort` with its question revision (migration 0004); revisions keep it. The API accepts only an effort that the connection lists for the chosen model. The Codex adapter sends it with every model step's turn. The composer preselects the model's own default and resets it when the model changes. Research depth and reasoning effort stay separate controls.

**Impact**: Researches created earlier have no stored effort, so Codex uses the model default for them. Codex does not echo the effort applied to a turn, so unlike the model it is sent but not verified.

## D6 — Close P4 technical gaps: backup, resource bounds, versions and revision labels

**Status**: accepted  
**Date**: 2026-09-14

**Context**: The P4 exit condition requires a restore test; the plan bounds PDF work and private-network fetches in P2–P4 (T07/G, §7.1); case C requires one work with separate versions; T18 requires older-revision results to carry their revision; §8 requires Cmd/Ctrl+K on real data. D5 left the version model, memory limits and DNS rebinding open.

**Decision**: `deixis backup` writes an SQLite backup-API snapshot plus every referenced PDF and provider payload with a SHA-256 manifest, never the Codex home; `deixis restore` verifies all hashes and restores only into a data directory without a library. PDF extraction caps total text (3 M characters) and stops the child when its peak resident memory passes 1 GB (a watchdog, since macOS does not enforce `RLIMIT_AS`; no memory cap on Windows yet). Uploads are refused above the declared length before parsing and copied in chunks while hashing. PDF fetches connect to the address that passed the public-address check (Host header and TLS server name keep the host) and ignore environment proxies. An OpenAlex open-access location with a different version label becomes a separate source version of the same work (no DOI or abstract copied, not screened separately, included only by the user); counts of unique, included, given and cited sources count works. Search results show the question revision they were found for. Cmd/Ctrl+K searches research titles, questions and source titles (not passage text).

**Impact**: No migration. Records found before this change get their other version when found again; PDFs already attached under D4's earlier behavior are not re-checked. Changed provider metadata for an existing record is still not re-recorded (P5 version history). Locator assertions inside claim text remain unchecked by code (case B relies on the method rule and model behavior case MB01).

## D5 — Enforce the chosen model, result applicability and local boundaries

**Status**: accepted  
**Date**: 2026-09-14

**Context**: A read-only review of the initial commit by Codex `gpt-5.6-sol` (high reasoning effort) found that runs could apply results after pause, cancel or a question revision; that a research could start without a model and accept output from another model; that answers stayed "current" after source-selection changes; that a crash between a completed model call or search and its step record could repeat work or duplicate answers; that the package hash covered `provenance.json`; and that `.env` secrets reached the Codex process. Evidence: `.local/review-gpt-5.6-sol-high-2026-09-14.md` (local, not versioned).

**Decision**: A research requires an explicit model that the connection lists; output whose resolved model differs is recorded and the run pauses (`model_mismatch`). Runs check pause and cancel after every external call and before applying results; discovery also stops (`cancelled`, `scope_revised`) when the question is revised. Search runs and candidates carry the question revision, and screening uses only the current revision. A research-level selection revision is stored with answer StepInputs and answers, so later selection changes mark answers `stale_selection`. Model-session and search results commit in the same transaction as their step outcome, and answers and screening proposals are applied at most once per step. The package hash covers only the instruction files loaded into model steps. The Codex process receives an allowlisted environment without provider keys. The API accepts only loopback peers, and attachments only when the source scope includes them.

**Impact**: Migration 0003. Answers created before it keep question-only applicability. The version-family source model, locator assertions inside claim text, upload/extraction memory limits and DNS-rebinding protection remained open review items (see D6).

## D4 — Attach an open-access PDF only to the source version it belongs to

**Status**: accepted  
**Date**: 2026-09-14

**Context**: In the first live run, OpenAlex described a record's primary location as `publishedVersion` while its best open-access PDF was a `submittedVersion` manuscript. DEIXIS attached that manuscript to the published record, so a PDF page citation was labeled with the wrong version.

**Decision**: Store the open-access location's version (`source_versions.oa_pdf_version`, migration 0002) separately and fetch the PDF only when it equals the record's `version_label`. A PDF of another version is shown as "different version · not used" until separate version records exist. Search uses OpenAlex `search.title_and_abstract`; plain `search=` also matches full text and returned off-topic records in probing.

**Impact**: Fewer PDFs are retrieved. Records created before migration 0002 have no stored OA version, so their already-attached PDFs are not re-checked.

## D3 — Run Codex in a DEIXIS-owned Codex home with explicit models

**Status**: accepted  
**Date**: 2026-09-14

**Context**: Probing showed that the user's `~/.codex/AGENTS.md` was loaded into app-server threads despite `project_doc_max_bytes=0`, and that the resolved default model differed between runs.

**Decision**: The Codex adapter uses `CODEX_HOME` under the DEIXIS data directory (the user signs in there once), disables tools, connectors, skills and instruction files through config overrides, starts one ephemeral read-only thread per step, rejects any thread reporting instruction sources and any output accompanied by tool items, and always sends the model chosen for the research. Evidence: `.local/codex-boundary-2026-09-14/report-deixis-home.json` (local, not versioned).

**Impact**: Codex readiness requires a separate sign-in. `skills/list` still discovers host skills, although none were injected into the probed prompts; this is recorded as a residual boundary.

## D2 — Place the first-slice application code

**Status**: accepted  
**Date**: 2026-09-14

**Context**: Implementation of the first slice began after D1 deliberately left app directories undecided.

**Decision**: Python 3.12 backend (FastAPI, SQLite) in `backend/deixis/`; React UI in `apps/web/` (started from a copy of the prototype, which stays untouched); language-neutral JSON Schema contracts in `contracts/research/`; the app-loaded method package in `methods/deixis-research/`; tests in `tests/`; isolated probes and real-model case runners in `scripts/`. Run with `PYTHONPATH=backend uv run python -m deixis serve`; the explicit `PYTHONPATH` is needed because macOS marks files in iCloud-synced folders hidden and Python skips hidden `.pth` files.

**Impact**: `docs/layout.md` lists the new homes. Local data stays outside the repository (`~/Library/Application Support/DEIXIS` on macOS).

## D1 — Separate current design drafts from the dated handoff

**Status**: accepted  
**Date**: 2026-09-14

**Context**: The repository arrived with a long dated continuation record, active API and research-method drafts, a UI-only prototype, and a private local evidence package. The `docs/desktop/` name reflects the transfer history rather than the selected local-web first release. Moving the entire handoff would break its supplied path and private screenshot references.

**Decision**: Keep `docs/desktop/` as the dated handoff and reference index. Place active product/API drafts in `docs/product/` and methodological design and domain examples in `docs/methods/`. Keep the UI prototype under `prototypes/shadcn-ui/` and the private transfer package under ignored `local-reference/`. Use `docs/README.md` as the authority map and `docs/layout.md` as the placement contract. Do not create empty application directories or select a frontend/backend stack by reorganizing files.

**Impact**: Update internal links and root navigation. No research behavior, model adapter, academic API connector, or UI runtime changes. The handoff remains the historical source for accepted user decisions; product drafts retain their proposal status.
