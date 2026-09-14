# DEIXIS decisions

Accepted product decisions from the 14 September 2026 conversation are recorded in the [dated handoff](desktop/README.md). This file records subsequent durable decisions; an entry does not turn an unimplemented proposal into a working feature. New entries go above older ones. Status values are `accepted`, `superseded`, `rejected`, and `deferred`.

## D20 — Reserve bounded answer room for formulation pages and warn about unsupported math

**Status**: accepted  
**Date**: 2026-09-15

**Context**: D19 asks for equations and model details, but retrieval previously selected an abstract per source before other PDF passages. A retrieved formulation page could be omitted even when it stated variables or constraints. Abstract-only evidence cannot establish an equation that appears only in full text.

**Decision**: After the first passage per included source, retrieval gives qualifying `pdf_page` passages up to one quarter of the answer-passage limit before filling remaining room by text match. A passage qualifies at lexical score 3 or above: 2 points per optimization phrase and 1 per math symbol (symbols capped at 6); the six-passages-per-source cap still applies. Validation adds non-blocking `math_not_well_formed` warnings for unbalanced dollar delimiters, braces or LaTeX environments in claims, limitations and unanswered aspects, and `math_without_full_text` for a mathematical claim whose cited passages are all abstract-level. The warnings appear with the other answer checks.

**Evidence**: Focused tests place an explicit formulation page before a better full-text-match page and cover malformed math and abstract-only mathematical claims. The 2026-09-15 backend suite passed 262 tests, the web build succeeded, and Playwright passed 15 tests. The three UWSN report runs below predate this retrieval/check change and read no PDFs. In the later packet-size live test (`.local/p4-eval-2026-09-15-packet/analysis.md`), two academic PDFs were downloaded but all 48 answer-input passages and all 57 cited links were abstracts: the first-passage-per-source loop filled the budget before the formulation-page reservation. A separate attached-only Kurt PDF test did pass six PDF-page chunks, including Figure 1 on page 4, but missed the requested packet-size choices and power-selection procedure on page 5. These observations test the feature's limits, not semantic claim correctness. No screenshot of the math-warning display was captured.

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
