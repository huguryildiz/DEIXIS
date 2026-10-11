# DEIXIS decisions

Durable decisions, newest first. Each entry is short: status, what was decided, and the main limit. An entry does not turn an unimplemented proposal into a working feature. Status values are `proposed`, `accepted`, `superseded`, `rejected`, and `deferred`.

The log restarted on 10 October 2026. D1 lists the decisions in force at that point; new decisions start at D2. The old entries (old D1 to D261) are in Git history: `docs/decisions.md` at commit `26c8214` is the last full copy. D numbers in code and test comments written before the restart point to that old log, not to the entries below.

## D5 — The interface takes the mockup's look
Status: accepted (owner 11 Oct 2026, after reviewing the clickable mockup) · Date: 2026-10-11 · Writer: Claude
Context: The owner reviewed the clickable mockup (claude.ai artifact, v24; local copy `.local/design/elicit-style-mockup/`) and asked for its look in the app. The mockup follows Elicit's layout; DEIXIS keeps its own ink blue (#3b5b9a light, #93acdf dark) where Elicit uses teal. The design guide said not to copy Elicit's visual style, so the guide changes with the code.
Decision:
- Colours keep the editorial token names in `index.css` and take the mockup's values: white page, lighter side, hover and selected surfaces, darker ink. New tokens `--ink-2`, `--faint`, `--accent-deep`, `--accent-tint`, `--accent-line`, `--bubble` and `--shadow-float` exist in both themes. `--primary` and `--accent` do not change.
- Contrast comes before the mockup: the requirement is at least 4.5:1 for text on the surfaces it sits on, so `--muted` stays #5b6475 in light, the include and uncertain tones and the abstract colour are a little darker than in the mockup, and `--faint` (icons and hairlines only) is held at 3:1.
- Inter (`--font-sans`) is the face for the interface and for reading text: claims, passages, source titles and headings. Source Serif 4 (`--font-serif`) is kept for the report title, emphasis inside the report, the report preview card and the PDF first-page text in the queue. Both are bundled npm packages at fixed versions, so the app still works offline. Math stays in KaTeX's own fonts.
- `.impeccable.md` describes the new look. Citation marks keep the accent tint, not the mockup's yellow.
- Structure stays: research tabs and their URLs, modal sheets, class names and DOM. Later slices restyle the shell and the screens on top of these tokens. Nothing from the mockup that lacks a backend is built.
Limits: This changes how the app looks, not what it does. The 4.5:1 requirement was checked for the token pairs, not for every rule: two pre-existing exceptions found in review were fixed with this change (the empty evidence-cell text and the dark PDF-page muted text); others may remain. Nobody tested whether the new look is easier to use. The mockup features without a backend listed in the port plan (follow-up chat turns, search-plan editing, usage meters, new export formats and the others) stay out.

## D4 — An answer over attached PDFs reads them in full width
Status: accepted (owner 11 Oct 2026: "uygun") · Date: 2026-10-11 · Writer: Claude · Reviewer: gpt-6.1-sol medium (code 6 rounds)
Context: A live attached-only answer (gpt-5.6-luna, two IEEE PDFs, 77 passages, limit 48) gave the model 12 passages: every source was capped at six (`MAX_PASSAGES_PER_SOURCE`), two of the twelve were reference-list chunks, and the second paper's result pages never reached the answer, which then said its key number was missing.
Decision:
- When the research uses attached files only (`source_scope = attached`), the cap per source is `max(6, limit // number of sources)`, so one to eight PDFs share the whole limit. Other scopes keep six.
- A passage that reads as a numbered reference list (`_reference_list` in `workflow/flow.py`: three entries such as "[4] H. U. Yildiz," with three years, starting near the top, after nothing or after the end of a previous entry) is ranked after every other passage in the topic order, a crowded source's pages and the criterion order. It is never dropped, so a misread conclusion is only ranked lower.
Limits: Four live runs, one each (gpt-5.6-luna, 11 Oct): the same two PDFs again (48 passages, 6 claims, the second paper's ">50% lifetime" result now cited), one 24-page review alone (48 passages, 10 claims), three directional-antenna papers (16 each, 9 claims, all three cited), two other papers (24 each, 7 claims). All four answers `structurally_valid`; the run's own reviewer marked 28 claims supported and 4 partly supported. No person checked the claims. The detector misses author-year reference lists and was checked on two IEEE papers only.

## D3 — Up to five seed PDFs, uploads and Zotero through one gate (seed_pdf_v2)
Status: accepted (owner 11 Oct 2026: "PDF veya PDF'ler seed olarak verilirse sorun olmasın, Zotero entegrasyonu da aynı şekilde çalışsın") · Date: 2026-10-11 · Writer: Claude · Reviewer: gpt-6.1-sol medium (plan 3 rounds, code 2 rounds)
Context: D2 let one PDF guide the search. With several PDFs, Home made the user pick one with a radio button. A research started from a Zotero collection alone chose no seed and did not start its search. A Zotero record's own DOI was not used, so a PDF with a blank cover page never matched.
Decision:
- The seed is an ordered set of at most five PDFs (`seed_snapshot_json` version 2, with a `seed_key` fingerprint). Uploaded files and Zotero or library PDFs go through the same function (`store.set_seeds`), and one function decides which sources can be seeds (`store.seed_candidates`); the page lists exactly those. Order is the request's order, or the candidate order for `all_eligible`. With more than five eligible PDFs, the five whose first two pages share the most question words are taken; the rest are listed as `not_selected`. The old single-seed format is read as a one-element set without rebuilding its excerpt.
- The excerpt budget is split across seeds: one seed keeps D2's excerpt exactly; with n seeds each gets `max(1, 4 // n)` passages and `5600 // n` characters. The passage cap becomes `max(4, n)`, so five seeds give five passages; the 5,600-character cap stands.
- Matching keeps D2's rules per seed, with one DOI request for all seeds and one meaning search for each undecided seed (at most 1 + 5 requests). The DOI request asks for up to 100 works and counts as failed when OpenAlex reports more matches than it returned, so two works sharing a DOI are never cut to one; for a single uploaded seed this is the only change from D2's requests (`per_page=100` instead of the DOI count). A Zotero or library seed may also match by its record DOI (`record_doi`): exactly one OpenAlex work with that DOI, whose title equals the record's title and stands in the first 1,500 characters of the first page that has text (page 1, or page 2 when page 1 is blank). A citation on page 2 of a page-1-text PDF never counts. The result of that check is kept as `record_check`.
- Matched seeds are the first chain seeds in seed order, deduplicated by OpenAlex work, within the policy's seed count. The semantic query is the question followed by equal shares of each seed's text within 1,500 characters, the longest `search.semantic` OpenAlex accepts (one seed: D2's string, cut at 1,500); the parts that went in are kept as `seed_parts`. D2 assumed 2,000 from the help page; the live API refuses more than 1,500 with HTTP 400, which a live run on 11 Oct showed on every seeded run until this was fixed, and also failed the seed lookup's meaning search. A run whose seed lookup failed does not pass that failure to the next run of the revision. The query writer sees every seed's excerpt. The ranking reads each seed through its frozen context.
- A run that opened the D2 seed step, or froze a D2 protocol, finishes under D2; no finished lookup is sent again.
- The research page shows one line per seed: what OpenAlex matched, and which of query writing, the similar-paper search and the citation chain actually used it, read from stored steps (a chain request counts only when it was sent). Home makes every added PDF a seed and starts the search, also when only a Zotero collection was added. Repeating an identical seed request changes nothing and returns 200; a 409 is a real conflict and Home then does not start the search.
Limits: Live check (11 Oct, gpt-5.6-luna, Standard, one run per arm, rule frozen beforehand in `.local/seed-live-2026-10-11/RULE.md`): 3 questions × none / 1 seed / 2–3 seeds, the seeds being target papers (a leaky test). All 10 seed PDFs that matched went to the right OpenAlex work (9 of 10 matched, none wrong). Share of the remaining targets in the top 50: 1 seed 0.55 vs 0.46 without; 2–3 seeds 0.42 vs 0.44, falling on uwsn_kconn2022 (2/12 vs 5/12) and battery_soh (1/12 vs 3/12) and rising on dbr_vbf. The frozen rule's verdict is "help not shown" (one 3-seed run was 86 s slower than the 60 s allowance). Single runs; the drops may be noise. Tests use SYNTHETIC records and a scripted OpenAlex and Zotero. With five seeds the query writer sees about 1,100 characters of each first page. The top-five choice for a large collection uses question-word overlap only; the user can change it on the research page. The quick chain budget may not cover every seed's reference list. `search-query.md` changed, so `skill_package_hash` and protocol hashes change for every run.

## D2 — The seed PDF guides the search (seed_pdf_v1)
Status: accepted (owner 11 Oct 2026: "planı yaz ve Sol'a inceletip kodla") · Date: 2026-10-11 · Writer: Claude · Reviewer: gpt-6.1-sol medium (plan 3 rounds, code 2 rounds)
Context: In a "Files + academic search" research the UI always picks a seed PDF and said its passages "guided the search", but no search step read them. The semantic query was the question alone, the chain seeds were the top semantic results, and the ranking saw the upload with a file-name title, no abstract and no references.
Decision:
- Before anything else plans, a discovery run with a ready seed looks the PDF up in OpenAlex (`workflow/seed_match.py`, step `seed_match`): the DOIs on physical pages 1–2 in one `filter=doi:` request, then, only if no DOI record decides, one semantic request with the head of page 1. A work is taken only when its title (4+ words) stands in the first 1,500 characters of page 1 and exactly one work does; two or more is `no_match`. A DOI alone never decides. Each lookup is its own step, so a resumed run does not send it again; a failed lookup is recorded (`lookup_failed`) and the run goes on.
- The protocol freezes the full context (`seed_match`: status, identifiers, title, abstract, reference list, the first 2,000 characters of page 1). The chain, the semantic query and the ranking read it only from the protocol. A run whose protocol froze before this rule finishes without it.
- Matched: the PDF is chain seed 0 (it takes one of the policy's seed places; the request caps are unchanged), and the same OpenAlex work is never chosen again. The ranking reads the PDF seed with the matched title, abstract, references and OpenAlex identity, and never scores the PDF against its own OpenAlex copy or takes that copy as a second seed.
- The OpenAlex semantic query is the question followed by the matched title and abstract, or the PDF's first page when unmatched, cut at 2,000 characters; the ranking's embedding query stays the question.
- The query-writing model (`search_query`) receives the frozen seed excerpt as passages; `search-query.md` tells it to take field terms from it but let the question decide. A query another run wrote without the same seed pages is not reused.
- The research page says what the seed did, from the protocol (`scope.seed_use`).
Limits: How often the matcher picks the right work, and whether seeding raises the targets in the top 20, were not measured; all tests use SYNTHETIC records and a scripted OpenAlex. PDFs with a cover page match nothing (fail closed). An unseeded run is unchanged except for `skill_package_hash` (and so the protocol hash), because `search-query.md` changed. Backlog from review: the page sentence uses the past tense once the protocol freezes, before the chain has run, and says "query writing" even when `DEIXIS_SEARCH_QUERY=code`; the transcript does not count the PDF seed apart; no Playwright case for the seeded path.

## D1 — Baseline (10 Eki 2026)
Status: accepted (owner decision 10 Oct 2026: clean start, today's fast path is the baseline) · Date: 2026-10-10 · Writer: Claude
Context: The owner chose a clean start. The fast path (old D250 to D260) became the only search path, and the old search rounds, the second-round term expansion, the old citation chain, the old answer assembly, the interactive term approval and all support for libraries written by earlier versions were deleted (commits 5a30689 to 8637fa3). The migrations were squashed into one baseline (old D261). This entry records what the code does now, so that later entries have one starting point.
Decision:

Architecture
- A FastAPI backend (`backend/deixis`) serves a React UI (`apps/web`) on loopback only. The API checks Host and Origin against an allowlist, and every mutation needs the double-submit CSRF token (`deixis_csrf` cookie, `x-deixis-csrf` header).
- A research has scope revisions. Each run is a list of steps keyed by `operation_key`. A step that already succeeded returns its stored output, so pause, resume and crash recovery never repeat a model call or a provider request that finished.
- A run stops at its next checkpoint on pause, cancel or a newer scope revision.
- One worker owns execution through an OS advisory lock (`flock`). At startup it marks half-finished steps and model sessions `outcome_unknown` and the runs that held them `paused`; it does not retry them on its own. The user resumes.

Model boundary
- Each model step gets a stored `StepInput` (records, allowlisted IDs, `step_input_id`, `scope_revision`, `skill_package_hash`) and a strict JSON output schema. Everything sent is stored before the call.
- The model has no tools. A tool item in the output fails the step with `model_isolation_violation`.
- Output from a model other than the requested one is recorded and never used (`model_mismatch`). No other model or connection is tried in its place.
- Schema repair is bounded: one repair call (`MAX_SCHEMA_REPAIRS = 1`), none for `vocabulary_labels` and `abstract_screening`. The answer step has one exception: when only the several-sources rule for a `source_stated` claim (and anchor defects code may salvage) still fails after that repair, it makes one more call, `grounded_answer_resplit` (old D249), if the model-call budget still allows it. If repair fails, the answer is stored as an unverified draft and is not shown as a cited answer.
- Answer and review steps see short citation handles instead of record IDs (old D12). Code resolves them back to record IDs before validation.
- Editing a runtime file of `methods/deixis-research/` changes `skill_package_hash`. The app refuses to start when the package fails its integrity check.

Evidence rules
- Every published claim cites passages that were given to that model step, and each claim-passage link needs a contiguous anchor that code locates in the stored passage text. The UI highlights only that located anchor.
- A `source_stated` claim cites one source; two versions of one work count as two sources and are not independent evidence. When more than half of at least four claims are `analyst_inference`, the answer step makes one optional rewrite call.
- `structurally_valid` means the answer passed these deterministic checks. It does not mean each cited passage supports its claim. The `answer_review` run is a separate recorded model assessment and never edits the answer.
- Reading depth stays visible: metadata, abstract, selected PDF passages and full text are different evidence levels. Abstract screening never includes a source by itself, and a user's own inclusion or exclusion overrides the model's.

Fast-path policy (`fast_path.py`, `fast_path_v1`)
- Every new discovery run freezes this policy into its budget, with a `policy_hash`. Later code changes do not rewrite a frozen policy.
- The numbers per depth, from `fast_path.MODES` (stage seconds for plan, search, ranking, read and answer):
  - Quick: 30/30/30/60/30 (180 s); N 25, K 10; keyword record cap 450; 10 chain seeds, 2 backward and 2 forward chain requests.
  - Standard: 30/45/60/120/45 (300 s); N 50, K 20; cap 1000; 20 seeds, 4 backward, 8 forward.
  - Detailed (policy mode `deep`): 45/90/120/270/75 (600 s); N 100, K 40; cap 2000, of which 500 are reserved for Semantic Scholar; 30 seeds, 8 backward, 16 forward.
- N is how many works of the frozen list are screened and looked up; K is how many of them can reach full text.
- Stage time is active wall time that survives pauses and restarts. Unused time carries to the next stage, overrun is recorded as debt, and each stage keeps at least 25% of its base.
- Search, ranking, read and answer have soft deadlines. Submitted model calls drain; a read-stage call still out 5 s after the deadline is cut (`model_read_cutoff`).
- Plan:
  - code takes search words from the question, three optional `vocabulary_labels` calls sort them into blocks, and OpenAlex count requests check the terms;
  - a `search_query` model call writes the query blocks (`DEIXIS_SEARCH_QUERY=model` by default); if it fails, the run stops with `search_query_failed`;
  - at most one OpenAlex request routes the sources (none when no domain source needs it);
  - three optional `criterion_proposal` calls vote the inclusion criterion;
  - the approval is recorded as `unattended`, and nobody is asked.
- The protocol, with its search plan, freezes after these planning requests and before the first request that fetches search results.
- An empty vocabulary (`vocabulary_empty`) or a too-broad one (`vocabulary_too_broad`) ends the run with that message. There is no approval card; the user rewrites the question, which makes a new scope revision.
- Search: one OpenAlex semantic page (up to 50 records) and OpenAlex keyword pages of 100, read page by page across queries under the keyword cap. Detailed also sends one Semantic Scholar bulk query. No other provider is searched and there is no second search round.
- Chain: one round, OpenAlex only (backward references and the first cited-by page per seed), overlapping the search and cut off before the ranking deadline.
- Ranking embeds the pool and freezes the list.
- Read: Semantic Scholar and Crossref look up missing abstracts for the top N; when Scopus is in scope, configured, its institutional COMPLETE view is confirmed (`complete_view_entitled`) and the lookup budget allows, it completes the abstracts still missing. Each batch of abstracts is screened by two model calls. At most K works get full text; a slot whose work found no text passes to the next work in list order.
- PDF retrieval uses 12 shared slots. At the read cutoff, fetches already running are handed to the background lane and go on; queued works start from the background queue only while fewer than 4 background fetches run.
- When discovery completes, one answer run starts on its own. It answers from the evidence the read stage owned at its cutoff, then queues a separate `answer_review` run.
- Late full text can produce one new answer revision (`max_revisions: 1`). The first answer stays as it was.
- An answer over attached PDFs only (no completed discovery) uses the inspection route: PDF fetch, lexical and semantic passage ranking, then `grounded_answer`.

Providers
- All connectors in `providers/registry.py` stay: OpenAlex, Semantic Scholar, Crossref (lookup only), arXiv, bioRxiv (through OpenAlex), PubMed, IEEE Xplore, Scopus, CORE, SerpApi (supplementary), plus the Zotero collection import. Keys come from the untracked `.env` or the system keychain.
- The research search uses only OpenAlex and Semantic Scholar. Abstract lookups use Semantic Scholar and Crossref, then Scopus under the conditions above. The other connectors stay registered and configurable.

Storage
- One SQLite connection is shared by the API and the worker on the event-loop thread. Writes are short synchronous transactions with no `await` inside, and a UI-visible event is written in the same transaction as the state it describes.
- The schema starts from `storage/migrations/0001_baseline.sql`. A schema change is a new numbered file from `0002_` on. A migration that has been applied is never edited, the baseline included, and tables are not dropped.
- Runtime data (database, PDFs, provider payloads, Codex home) lives in `DEIXIS_DATA_DIR`, never in the repository.

One-time reset (old D261)
- The 77 old migrations were squashed once into the baseline, and the code that kept earlier libraries working was removed. A library written before the reset is refused at startup, and its app data folder is to be deleted. This reset is not repeated.

Limits:
- This entry restates decisions made, reviewed and tested under their old numbers and adds no behavior. The commit that wrote it also removed two method files no step loaded and corrected method and project docs to match the code.
- The tests run on synthetic records and a scripted model. They show workflow behavior, not answer quality or live latency. Live measurements are in STATUS.md and the old log.
- The anchor locator accepts a near match at a provisional 0.9 ratio over one contiguous region.
- Stage deadlines are soft, so a run can exceed its target time.
- The startup refusal of an old library says "newer DEIXIS", which is misleading for an older library (old D261).
