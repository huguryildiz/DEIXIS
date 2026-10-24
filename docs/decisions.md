# DEIXIS decisions

Decisions in force, newest first, five lines each. The full long-form text up to D119 is in git: `git show f2574f22:docs/decisions.md`. The entries before the 10 Oct 2026 clean start (old D1 to D261) are at commit `26c8214`; D numbers in code comments written before that date point to the old log. `notes/` paths resolve only on the owner's machine.

## D119 — One schema file with numbered upgrade steps replaces the 16 migration files (2026-10-25)
Decision: `deixis/storage/schema.sql` makes a new library in one transaction at version 16, and `deixis/storage/upgrades.py` holds the work of 0002 to 0016 unchanged as steps under the same version numbers and names; an older library still upgrades on its own at start-up.
Why: The schema was a chain of 16 SQL files, six of which rebuild tables, and the owner asked for one schema file with no change for users.
Limit: A failure while making a new library now leaves only the empty `schema_migrations` table, and the owner's library was checked on one copy, at version 13.
Evidence: commit a62ab5ed, f2574f22 · reviewer gpt-6.1-sol high, round 2 hazır
## D118 — Equation finder: more numbered displays cropped cleanly, unclear regions refused (2026-10-24)
Decision: Region growth now stops at lead-in sentences, prose rows and other equations' rows, and a region whose neighbouring lines are not text, a heading or another equation is refused (`region_unclear`). The crop also checks foreign text up to its edge.
Why: D113's finder cropped 25 of 210 sent equations together with other lines.
Limit: The 368 sends outside the reference were checked only by a 42-crop visual sample and a text-line audit, and many refusals are deliberate, so recall stays limited; the live check was one run on three papers.
Evidence: notes/2026-10-24-equation-finder · commit 543a65f6
## D117 — PDF fetch: 403s counted per host, Elsevier article API for open-access PDFs (2026-10-24)
Decision: The PDF fetch sends the Settings email in its User-Agent, and the run card counts 401/403 refusals per host. Elsevier's article API, with the Scopus key, is a new PDF route for 10.1016 DOIs, used only when the record is marked open access.
Why: Open-access PDFs from MDPI, SAGE and ScienceDirect failed with 403 on the owner's network, and the email changed none of the refusals.
Limit: The Elsevier result is 7 open-access articles on one network and one day, not checked page by page, with no live research run yet; MDPI and SAGE still have no automatic publisher route.
Evidence: notes/2026-10-24-pdf-403/RESULT.md, notes/2026-10-24-pdf-gap/RESULT.md · commit 8fbbf7f7, f1582ec5
## D116 — Check a statement: the claim's field and named authors reach the search (2026-10-24)
Decision: A person can type the claim's field under "Check a statement"; without one the query model names it (SearchQuery v2). Code queries drop "X et al." mentions, claim verbs and bare numbers, and each work the sentence names gets an OpenAlex author query.
Why: In D109's pilot the search never found 5 of 13 known supporters because statements without the field's key word drifted to other fields.
Limit: The live pilot found 12 of 13 known supporters but lost one (ceran2026) to the field narrowing the query; the model-named field path was not run live, and it covered one paper's sentences and one field.
Evidence: notes/2026-10-24-reverse-citation-r5/RESULT.md · commit 1173ee50, 4a36896b
## D115 — Equation-reader requests are booked in the spend ledger (2026-10-24)
Decision: When an equation request's result is stored, the same transaction writes a spend-ledger row for it (`spend.record_equation_request`); older requests are booked on the next start. The day's total, the daily threshold and Settings → Usage now count them.
Why: These requests wrote no model session, so the day's estimate, the threshold and the per-connection dollars left them out, and the tile D113 relied on had been removed on 20 Oct.
Limit: The equation reader still sends while the day's estimate is over the threshold, and no live equation request was checked against a provider bill.
Evidence: commit a1424deb
## D114 — Works read from abstracts only join evidence tables and reports, each marked (2026-10-18)
Decision: Works that passed the abstract stage but have no readable full text become abstract-only rows in new evidence tables and their reports, one row per work, marked "from abstract" in the UI, Markdown, DOCX and LaTeX. Landed on main 2026-10-24; written as D99 on the `abstract-rows` branch and renumbered.
Why: A table made after an answer held only full-text includes, so on battery_soh (1 include, 16 cited) the table and report rested on one source.
Limit: Only model-free tests ran; the live measurement in the plan is open, nothing checks that a value follows from its quote, and existing tables are unchanged.
Evidence: notes/plans/abstract-rows-plan.md · commit fd4d37bf
## D113 — Marker removed; the answer model reads numbered equations from page crops (2026-10-20)
Decision: Marker is deleted. A third crop route finds numbered display equations with the D40 detector and has the default answer model read each crop, accepting the LaTeX only through the D40 gate. Image input exists on the Anthropic, OpenAI and Gemini API connections.
Why: Marker needed 5–7.7 GB of memory, 4.4 GB on disk and 3–7 minutes a paper; on 204 equations Sonnet 5.5 got 78% exact against 37% for PyMuPDF alone.
Limit: In a live check on 3 arXiv PDFs only 10 of 24 reference equations were sent; the other 14 were refused by the detector, so recall is bounded by the D40 detector, and 19 placed equations outside the reference were not checked.
Evidence: notes/2026-10-20-equation-bench, notes/model-equation-reader-plan-2026-10-20.md · commit d99ec273, 2f6276c6
## D112 — Heralded-memory run losses: repeated phrase no longer voids a proposal (2026-10-20)
Decision: A criterion phrase written twice in one part counts once. At the cutoff, a work whose answer version has no screened abstract takes the abstract of another version that was screened a candidate (`fast_answer.abstract_sibling`), marked `abstract_of_unread_pdf_version`.
Why: Two of three criterion proposals failed `duplicate_criterion_phrase`, so no criterion existed and no full text was read, and two works left the answer because their PDF sat on a sibling version.
Limit: Not measured on a live run; the fallback gives abstract evidence only, and full text still depends on a criterion and the read window.
Evidence: commit 2b43e564
## D111 — Spend ledger: unpriced calls are priced once a price list names the model (2026-10-18)
Decision: On every start, `spend.reprice_unpriced` rewrites each unpriced row whose model the current price list names. Migration 0012 adds `repriced_at` and `repriced_price_list`, and Settings shows how many calls were priced later.
Why: Settings showed Anthropic API as "not known" with 89 unpriced calls on `claude-opus-5-5`, which the 16 October price list did not name.
Limit: The cost uses today's list for earlier calls, which is wrong if a provider changed its price; the provider's bill is what counts.
Evidence: commit 743aae58
## D110 — Review queue: one answer to several ticked rows (2026-10-18)
Decision: Each queue card except a PDF identity row has a tick, and a floating bar gives the ticked rows one answer (include, does not meet the criterion, or not sure) through `POST /api/researches/{id}/queue/decisions`. Rows that changed or left the queue are refused and named, the rest are written, and undo stays per decision.
Why: The owner found answering a long queue one card at a time tedious.
Limit: A bulk answer counts as the person's decision for every row even if they did not open each card, and the bar has no note field yet.
Evidence: commit 0ae2dbb9
## D109 — Reverse citation search R4b: pilot meets the bar; R4 closes, R5 stays blocked (2026-10-18)
Decision: R4 is closed with D108's rule kept, under which a result with no `stated` part is not counted as support. R5 (challenges) stays blocked and needs its own plan and pilot gate.
Why: The re-run on the same 10 statements met D108's bar: both readers found 0 positive errors on 24 support results and none on the one `found_whole`.
Limit: This is a 10-statement pilot with one run and model readers, not an accuracy measure; only 1 of 7 checked known supporters counts as support, and 5 of 13 were never found.
Evidence: notes/2026-10-18-reverse-citation-r4b-pilot/ · commit 9551dd27
## D108 — Reverse citation search R4: the pilot fails on partial support; R4b counts support only with a stated part (2026-10-18)
Decision: R4b changes the statement check only: a completed result with no `stated` part goes to its own group ("support not shown well enough"), not to support. The same 10 statements are re-run under a new lock; R5 stays blocked.
Why: The live pilot failed the bar: positive errors were 10/50 (Sol) and 11/50 (Opus), all on `found_partial` results for abstract-only works.
Limit: 30 results leave the support groups and the readers judged 19–20 of them supportive, so known-supporter capture would fall from 3/6 to 1/6; ten statements are a pilot, not an accuracy measure.
Evidence: notes/2026-10-18-reverse-citation-r4-pilot/, notes/plans/reverse-citation-search-plan.md · commit 1068863c
## D107 — Reverse citation search R3: a Home mode and a statement-check panel (2026-10-18)
Decision: Home gets a fifth mode, "Check a statement" (one sentence, at most 600 characters), and the research view gets a panel with the check's currency, counts, results grouped by outcome and backend-located quotes. A stale check offers "Check again"; no "challenges" wording exists.
Why: R1 (D100) and R2 (D103) built the statement check without a screen.
Limit: Only the fixture model was used, with no real model or search; the running and resumed states are not seen in the browser, and Turkish strings were not read by a native speaker.
Evidence: notes/plans/reverse-citation-search-plan.md · commit 1068863c
## D106 — The reranker leaves chain-only records in their fused place (2026-10-18)
Decision: Within the rerank window, a record that only citation chaining brought is not sent to the reranker and keeps its fused place; other records are reordered among their own places. The step stores these as `kept_in_place`.
Why: On the EE survey set the reranker lowered recall@50 from 0.129 to 0.091, because a survey's chained papers look far from the question in title and abstract.
Limit: BioASQ was not checked and no new benchmark run was made; the offline check gave EE 0.111, still below the fused order, and the product may keep fewer records in place than the simulation did.
Evidence: commit 86263ec5
## D105 — Verify Citations after the V5 pilot: table rows, plain claims, negation phrases, freeze waits (2026-10-18)
Decision: Table citations are checked against their row only, each marker stores a plain-text `claim`, three phrases no longer count as negation, and a freeze is refused while background re-extraction is pending. The citation-check method text gains a table-row paragraph and a baseline paragraph.
Why: The V5 live pilot sent 68 pairs and 31 ended `could_not_check`, 17 of them Table 1 citations whose "sentence" was the whole tabular.
Limit: Model-free tests only; the re-run of the pilot (`RESULT-r2.md`) passes its thresholds with 9 `could_not_check`, but it is one run, so part of the gain may be run-to-run variation, and the `reextraction_pending` freeze path was not exercised live.
Evidence: notes/2026-10-18-verify-citations-v5-pilot/RESULT-r2.md, notes/2026-10-18-verify-citations-v5-pilot/RESULT.md · commit b0817990
## D104 — The record reranker is on by default with Voyage rerank-3-lite (2026-10-18)
Decision: With no reranking setting saved, the setting in force is Voyage `rerank-3-lite`, pool factor 4. A saved setting, including "off", always wins, and without a usable Voyage key the list keeps its fused order and the research says so.
Why: The 18 Oct benchmark raised recall@50 from 0.546 to 0.618 on BioASQ and from 0.636 to 0.700 on LitSearch, with both interval lower bounds above zero.
Limit: Only search order was measured, not reading or answers, and the gain may differ outside biomedicine and ML/NLP; a keyless person sees the notice on every search.
Evidence: commit bc7e668a
## D103 — Reverse citation search R2: how a statement check starts, resumes and goes stale (2026-10-18)
Decision: `statement_check.request()` opens a revision with the model frozen at request time, and `POST /api/researches/{id}/runs` accepts `statement_check`. At discovery end the check starts automatically, attached-scope checks pause while files extract, and a revision is marked `stale` when the question, a choice or a source changes.
Why: R1 (D100) built the check with only a private constructor.
Limit: Model-free tests only; no real model or search has run a statement check, and whether the claim note keeps screening on topic is not measured.
Evidence: notes/plans/reverse-citation-search-plan.md · commit 8c358455
## D102 — A reranked record past 20,000 characters is cut and counted, not refused (2026-10-18)
Decision: Every reranker receives each title and abstract cut to its first 20,000 characters, and the step records how many were cut (`cut_documents`).
Why: A BioASQ record whose OpenAlex "abstract" held the whole article (23,753 characters) made the rerank fail with `reranker_failed`, so none of the 200 records was reranked.
Limit: A cut record is scored on its title and opening only, Cohere's per-document token check still refuses the whole request, and how often this happened earlier is not counted.
Evidence: commit 38db53d4
## D101 — Verify Citations V4: the screen and a Library tool showing counts, status and result apart (2026-10-18)
Decision: A "Verify citations" button in the Library opens its own page, where a person pastes or uploads a draft and walks through look up, get the text, freeze, preview and start. The table shows each citation's sentence, work, what was given, the result and the status apart, and a located quote opens its passage alone.
Why: The V1–V3 routes existed but there was no screen.
Limit: Checked only with the fixture server and its scripted model; nothing was run on a real draft or model, a 200-pair table was not tried, and two evidence-table cases of `acceptance.spec.ts` fail the same way on origin/main.
Evidence: notes/plans/verify-citations-plan.md · commit d35d3672
## D100 — Reverse citation search R1: a pasted statement is checked against the works its search read (2026-10-18)
Decision: A research may have the intent `statement`; its sentence is checked against the works the fast path read, using V3's output schema and checks, and only support is reported. Migration 0009 adds the `statement_checks` tables and run kinds, with per-work caps of 12, 24 or 40 by depth.
Why: The owner wants to paste one statement and get the works that support it; "challenges" was moved to R5 because every code rule against a wrong one had a counterexample.
Limit: Model-free tests only, with no real model reading the method text and no start route, screen or live pilot yet; "not found in the given passages" does not mean the work disagrees.
Evidence: notes/plans/reverse-citation-search-plan.md · commit d35d3672
## D99 — Verify Citations V3: a model step per planned pair, and the code decides the result (2026-10-18)
Decision: Each planned (citation, cited work) pair goes to a model step with a strict schema, and the code decides the result (`found_whole`, `found_partial`, `not_found_in_given`) from quotes it locates itself. Many structural checks (quote location, number, unit and negation rules) send an answer to one repair, and a still-invalid one is `could_not_check`.
Why: V2 froze which passages each pair is given, and V3 turns a model's answer into a result without trusting the model's own claims.
Limit: Model-free tests only; no real model has read the method text, nothing measures the false positive rate, and the rules are structural screens that deliberately refuse many valid quotes.
Evidence: notes/plans/verify-citations-plan.md · commit 1af5e83e
## D98 — Kill search gets an entry in the answer's Next steps box, although its live gate failed (2026-10-18)
Decision: Next steps gets a "Topics the answer did not answer (n)" row and an always-enabled "Search earlier work for a claim" row. Both open a dialog that saves a candidate claim; the search still starts only from the Candidates panel, and a summary under the box shows each candidate's result with the caveat that missing a match is not evidence of originality.
Why: The owner decided on 18 Oct to build it anyway, so the guard against reading an unanswered aspect as "nobody did this" sits where that reading starts.
Limit: The v3 live gate failed (the knee-osteoarthritis claim kept 0/3 targets) and was not run again; nothing here changes what kill search finds, and tests are model-free.
Evidence: notes/design/kill-search-next-steps.md, notes/killsearch-live-v3/RESULT.md · commit dae4dac7
## D97 — Kill search plan v3: backups are searched and the ranked cut counts concepts (2026-10-18)
Decision: Plan version 3 adds backup terms to each provider's query, with overflow going into at most one alternative query per provider. The ranked cut (`kill_rank.v2`) counts concepts, joining abbreviations only through an unambiguous link.
Why: The v2 live check failed its gate (C1 R 2/4, K@8 1/4), because backup terms never reached the search or ranking and name forms were counted instead of concepts.
Limit: Model-free tests only; the frozen live rule (C1, C2 and the out-of-domain C3) decides acceptance and had not been run, and real synonyms that are not abbreviations add no concept.
Evidence: notes/killsearch-live-v2/RESULT.md, notes/killsearch-live-v3/RULE.md · commit af76e51c
## D96 — Verify Citations V2: entry text, a frozen passage plan per pair, 200-pair cap and cost preview (2026-10-17)
Decision: Each resolved entry gets its text decided once (person's PDF, stored PDF, open-access path, abstract, or nothing). `POST …/plan` freezes 6 ranked passages per pair, the first 200 pairs with text are planned, and a preview gives a cost range. Identity checks run on every PDF used and a missing one reads as unconfirmed.
Why: V3's model step and the preview need to read one frozen plan of what text each citation is given.
Limit: Tests are model-free with mocked services; nothing ran on a real draft or PDF, and how well BM25 over one sentence finds the supporting passage was not measured.
Evidence: notes/plans/verify-citations-plan.md · commit 0db4fd6d
## D95 — Kill search ranks its pool before the eight-work cut and asks for stricter terms (2026-10-17)
Decision: Plan version 2: the query model must pair one setting term with one task term, the merged pool is ordered by BM25, block coverage and co-mention before the cut to eight, and each provider returns the most one request can. Version 1 plans keep the old window and cut.
Why: The 17 Oct live check failed: Maulana 2019, Hakim 2018 and Memon 2018 were never retrieved, and a relevant 2023 comparison was cut at merged rank 18.
Limit: Model-free tests only; whether the targets are now retrieved was to be decided by the frozen live rule, not yet run, and ranking is a priority signal, not a relevance verdict.
Evidence: notes/killsearch-live-2026-10-17/RESULT.md, notes/killsearch-live-v2/RULE.md · commit ea17db26
## D94 — The Anthropic schema says how to give null; a bare "protocol" is no design term (2026-10-17)
Decision: `anthropic_schema` adds a sentence to every optional field: leave the field out to give null, never write an empty string or "null". The transport record becomes `anthropic_schema.v3`, and the design-term screen no longer matches a bare "protocol".
Why: The live check lost three of four `claim_decomposition` runs because the model wrote `""` or `"null"` for a nullable field (7 of 8 calls) and a routing-protocol claim failed the design-term screen.
Limit: Model-free tests only; whether the model now leaves the field out was not checked live, and retrieval, which failed the live check, is not changed here.
Evidence: notes/killsearch-live-2026-10-17/RESULT.md · commit 2916d2bb
## D93 — The Anthropic API gets required nullable fields as optional and patterns as descriptions (2026-10-17)
Decision: For the Anthropic connection, `anthropic_schema` sends each required nullable field as optional and moves each pattern and array bound into the field's description. The adapter puts null back into fields the model left out and stores a transport record with the schema digest.
Why: Every `report_section` call failed with HTTP 400, first on a type-list enum and then on a compiled grammar that was too large.
Limit: Checked live only up to the first content event; no full section or answer was generated, so whether the model writes as well without enforced patterns is not measured, and the size limit is undocumented.
Evidence: commit cf061be0
## D92 — A follow-up can search for new works, from a button, as a run of its own (2026-10-17)
Decision: A follow-up answer can offer "Search for new works", which starts a `followup_search` run under the same question revision. It writes terms, sends bounded requests, screens at most 40 new works with the discovery criterion, and includes nothing.
Why: A follow-up answered only from passages already held, and the owner wanted it to query OpenAlex and other sources for works outside the research.
Limit: Tests are model-free plus one browser check on the fixture server; term quality and relevance of the new works are unmeasured, and the answer and report are not rewritten until the person includes them.
Evidence: commit 45fea567
## D91 — Citation snowballing: rounds the person starts from chosen works, nothing included (2026-10-17)
Decision: A `snowball` run is one round started by the person from chosen seed works: at most 3 rounds, 10 seeds and 80 works screened. Found works pass the abstract stage, nothing is included, and the page is a side panel opened from the research menu and the citation map.
Why: Snowballing existed only as one bounded round inside each fast-path search, and the owner asked for a mode that starts from named papers and can go a second round.
Limit: Tests use synthetic records and a fake model; no live round has run, so whether snowballing finds works a search missed is unmeasured, and the Playwright case is not written.
Evidence: notes/plans/snowballing-plan.md · commit 019bea39
## D90 — Built-in models run on llama.cpp from a pinned GGUF catalog (2026-10-17)
Decision: DEIXIS downloads llama.cpp build b11711 and a catalog of eight sha256-pinned GGUF embedding and reranker files, each downloaded, removed and chosen on its own. Each chosen model runs in its own `llama-server`, stopped after 300 s idle, and Settings shows the catalogs as cards with a recommended model.
Why: The D88 PyTorch model needed a 2.4 GB download plus about 600 MB of packages, one model per kind, and a reranker that reloaded on every request.
Limit: One live check with only the two 0.6B files and synthetic texts, so retrieval quality and the 4B/8B and bge models were not run; memory figures behind the recommendation are estimates, and Windows is unsupported.
Evidence: notes/plans/llamacpp-local-models-plan.md · commit 0009b9b6
## D89 — Search & ranking as model-style cards, with Cohere, Jina and ZeroEntropy (2026-10-17)
Decision: Each embedding and reranker choice is a card that opens a sheet with its key, a "Model files" section and a save button. Adds Cohere `embed-v5.0-fast` for embedding and Cohere `rerank-v4.0-fast`, Jina `jina-reranker-v3.5` and ZeroEntropy `zerank-2` for reranking.
Why: The owner wanted the Search & ranking tab to look like the Language models tab and asked for four popular API choices each for embedding and reranking.
Limit: Tests are model-free with mocked endpoints; no key of the three new providers was tried live, and the retrieval quality of all four choices is unmeasured.
Evidence: commit a868f463
## D88 — Qwen3 replaces bge-small as the built-in model; a reranker and Voyage are added (2026-10-17)
Decision: Superseded by D90 for the runtime and files; the reranker layer, pool factor and Voyage stay. The built-in install downloads `Qwen3-Embedding-0.6B` and `Qwen3-Reranker-0.6B`; an optional reranker (off by default) reorders the first records of an `sw` run's fused order, and Voyage is offered beside Gemini and OpenAI.
Why: The owner asked to move the built-in embedding to Qwen3, add a separate reranking layer and offer Voyage, choosing the cheapest pair, `voyage-4-lite` and `rerank-3-lite`.
Limit: On 100 BioASQ questions both rerankers raised recall@50 from 0.545 by +0.032 to +0.064, none reaching the +0.10 bar, and the product runner's memory growth is not yet fixed.
Evidence: notes/rerank-trial-2026-10-17/qwen-voyage-results.md · commit a868f463
## D87 — A repair may reword an insufficient-evidence reason only for a banned word or word budget (2026-10-17)
Decision: A repaired report section may change an old `insufficient_evidence` reason only to remove a banned word or to cut it under the section's word budget; old entries are matched one-to-one by maximum bipartite matching. `report.md` VI now says the banned words apply to gap text, claim text and every such reason.
Why: Live, 4 of 5 reports paused at section VI because the repair check demanded the old reason back while the reason still held a banned word, so the loop never ended.
Limit: A reworded reason is not checked to say the same thing, a reason can still say `gap_candidates`, and the five reports were re-run live with the round-2 version, not with this last matching change.
Evidence: commit fb977b90
## D86 — Verify Citations V1: code reads a draft's markers, bibliography and pairs (2026-10-17)
Decision: `domain/citation_check.py` fixes the pair and result contract, and migration 0002 adds the citation-check tables. `documents/draft_parse.py` reads pasted text, `.txt`, `.md`, `.tex` and `.docx`, finds the citation markers and bibliography, and a resolve route looks entries up on OpenAlex. No model is called in V1.
Why: Verify Citations checks a draft's citations against the cited works, and this is slice V1 of the 5-slice plan.
Limit: Tests are model-free with mocked OpenAlex answers and nothing ran on a real draft; the 200-pair cap is not applied yet, and an entry whose DOI does not resolve is not tried by title.
Evidence: notes/plans/verify-citations-plan.md · commit 0123e93d
## D85 — The Anthropic API connection streams its answer, with a 64,000-token output limit (2026-10-17)
Decision: `models/anthropic_api.py` now sends the request with `"stream": true` over the shared httpx client and reads the server-sent events itself, returning the same `ModelStepResult`. `MAX_TOKENS` rises from 16,000 to 64,000.
Why: On the DBR/VBF K copy with `claude-sonnet-5-5` medium, a schema-repair call used 15,271 and 14,225 thinking tokens and hit `max_tokens` twice, so no answer was saved.
Limit: Tests are model-free with mocked SSE bodies; the 300 s `turn_timeout` still governs answer calls, so a 64,000-token turn would end as a timeout, and the live three-run acceptance was not run.
Evidence: notes/plans/anthropic-streaming-plan.md · commit 1894bd5f
## D84 — A full-text source's first answer-input slot goes to its most result-dense passage (2026-10-17)
Decision: New module `workflow/result_passages.py` scores passages by reported values near outcome terms and comparison words. The most result-dense passage takes a full text's slot 1 when it scores at least `MIN_SCORE` = 2, and passages with at least 6 citation marks and no outcome term go last.
Why: On one research, topic ranking gave each full text's first slot to its title page, introduction or related work, though 13 of 20 full-text pools held a result passage.
Limit: Tuned on one research and one question; cue words and units are English and outcome terms match as written, so only 5 of 13 pools reach the floor, and the live answer-level gain is not separated from model variance.
Evidence: notes/plans/result-passage-plan.md · commit 5893d1c4
## D83 — A valid answer that leaves given works unaccounted gets one coverage rewrite (2026-10-17)
Decision: After D260's `_cap_inference`, a valid `grounded_answer` with unaccounted works in its ledger gets one rewrite call, `grounded_answer_ledger_coverage`. The rewrite is published only if it is valid, leaves fewer works unaccounted and keeps every first claim and still-valid exclusion; if it changed a first claim, the code merges instead.
Why: D80's acceptance failed: with 41 works given, the model returned an empty `excluded_sources`, 29 works were unaccounted, and a prototype second call raised cited works from 15 to 26.
Limit: Measured on one question, one research and one prototype run; the first three-run acceptance published no rewrite, this version's publish rule was not re-run live, and an answer with unaccounted works takes about four times as long.
Evidence: notes/plans/ledger-coverage-plan.md · commit 7a9fa43f
## D82 — The run card: screening readings, full-text gaps and anchor matches in step panels (2026-10-17)
Decision: The research view adds `runs[].screening_passes`, `runs[].fulltext_gaps` and `evidence[].anchor_match`, and the timeline shows each run in one card. The step panels list disagreeing readings, one reason per unread work, and how each anchor was located.
Why: The owner's run-timeline draft showed per-step data that the research view did not carry, though it was stored.
Limit: Checked with model-free tests and the steps acceptance spec, not on a live run; a run that froze no cutoff snapshot has no record of works outside its window, and there is no "rerun with deeper reading" button.
Evidence: commit fd31f4fb
## D81 — Measured values a cited passage states are set in bold in the answer (2026-10-17)
Decision: Each claim in the research view gets `quoted_measures`: spans of a number with a percent sign or a unit whose number a cited passage states. The thread sets these in bold with the tooltip "This value appears in the cited passage".
Why: The owner asked whether the answer should bold its important parts, and letting the model choose would make bold a model verdict on importance.
Limit: It matches the number, not its meaning or unit, so a passage saying `450 kJ` still marks `25%` if it contains 25; only the thread answer uses it.
Evidence: commit e4612400
## D80 — Every work given to an answer is cited or left out with a reason (2026-10-17)
Decision: `deixis.grounded_answer_draft.v4` adds a required `excluded_sources` list with a reason and, for three reasons, a located quote. The code works out which sources are cited, stores `validation_json.evidence_ledger`, and the answer view shows a count line and a closed list of left-out works.
Why: On a Standard DBR/VBF run the answer cited 10 of 40 given works and gave no reason for the other 30, though 5 of the 25 uncited works had a number or formula for the question.
Limit: Model-free tests only, no live run, so whether answers cite more works is not measured; a reason is the model's judgment, and follow-ups, reports and works that never reached the answer input are not covered.
Evidence: notes/plans/answer-coverage-2026-10-17.md, notes/plans/evidence-ledger-plan.md · commit e4046042
## D79 — The mockup parity check is removed; the mockup stays as a reference (2026-10-17)
Decision: Supersedes the gate part of D8. `apps/web/e2e/parity/` and the `parity` Playwright project are deleted, and behaviour stays covered by the acceptance specs and pytest. Later the mockup itself was deleted at the owner's request, and the shipped screens are the visual reference.
Why: The check compared 487 element pairs and took about 40 minutes, and nine surfaces failed with the same messages before and after D77, so it no longer guarded anything.
Limit: Visual drift from the mockup is now caught only by eye and by the screenshots the acceptance specs write.
Evidence: notes/design/elicit-style-mockup/ · commit 8952db05
## D78 — Settings → Usage shows spend and subscription limits per connection, not call counts (2026-10-17)
Decision: `GET /api/usage/models` gives one row per model connection: estimated dollars for API-key connections, Codex's live limit windows, Claude Code's last reported window with its call time, and a note for other subscriptions and local models.
Why: The old Usage box counted model calls per role, which tells the owner nothing since a model has no call limit.
Limit: Codex was read live once (one weekly window, 87%) and Claude's event shape from one live call; Claude's figure is as old as the last call, and spend uses the dated price table, not the provider's bill.
Evidence: commit de39c347
## D77 — Mockup v25: question chip, counts strip and ringed phase steps (2026-10-17)
Decision: Mockup v25 changes CSS only: the question's scope becomes a tinted chip, each phase sits on a 24px ringed icon joined by a 1px rail, and phase details sit in a bordered panel. The four counts move into one strip, `.research-counts`, and the app copies this in `research/thread.css`.
Why: The owner asked for a more premium look at the top of the research thread, and the spec was mockup v24, so the spec changed first.
Limit: Visual only; the per-step data the owner's draft showed (both screening passes, anchor match type, why a full text was not read) is not in this change.
Evidence: notes/design/elicit-style-mockup/ · commit 0b55d0fe
## D76 — The second full-text read sees the parts the first did not; shared parts must be agreed (2026-10-16)
Decision: Under read rule `split_v1`, call 1 keeps today's passage list and call 2 gets the passages call 1 did not see, then fills with call 1's. Parts only one call saw are merged by code: one call's verified quote from a passage only it saw is enough for a criterion part.
Why: Both calls saw the same 12 passages and gave the same label on 239 of 245 parts (97.6%), so the second call added no text.
Limit: The rule's main purpose, core evidence missing from the first 12 passages, is still unmeasured, and exclusion is now harder; the replay set has one topic and one labeller, Claude.
Evidence: notes/second-read-replay/, notes/second-read-replay/live/ · commit 10e3e014
## D75 — Migrations 0001–0022 squashed into one schema file (2026-10-16)
Decision: `storage/migrations/0001_schema.sql` holds the whole schema, and the old 22 files move to `tests/fixtures/storage/pre_squash_migrations/`. A library that recorded all 22 gets its rows folded into one on its next start; later changes start at `0002_`.
Why: Six days after the clean start the schema had 22 migration files again, and the owner asked for one file.
Limit: Checked by `tests/storage/test_squashed_baseline.py` and once on a copy of the owner's library; the live library itself is folded on its next start, not yet.
Evidence: commit f0beb493
## D74 — Running headers and footers repeated across pages leave the PDF text (2026-10-16)
Decision: `layout-v6` in `documents/pdf.py` drops a block in the top or bottom 8% of a page whose lowercased, digit-masked text recurs on at least 3 pages and at least 40% of the pages. Older passages keep their extraction version until re-extracted.
Why: The owner saw "J. Mar. Sci. Eng. 2023, 11, 1567 17 of 23" as a passage of an MDPI paper, because layout-v5 dropped only small-type blocks in the top 7%.
Limit: Checked on the 35 PDFs in the owner's library; a head that MuPDF merges with a neighbouring line stays, and PDFs under 3 pages, OCR pages and Marker pages are not covered.
Evidence: commit 99a9a6f4
## D73 — PRISMA-S, the Method box and Watch read the requests the fast plan sent (2026-10-16)
Decision: `fast_search.sent_plan(body)` returns what a frozen protocol sends, with each request's step key and arm. PRISMA-S and the Method box use it, and Watch follows only keyword and S2 bulk requests.
Why: They still read `compiled_queries`, which on the fast path holds dropped queries and omits the semantic, seed and Semantic Scholar bulk requests.
Limit: Workflow tests with SYNTHETIC records only, not looked at in the app or on a live run; how a watch created before this change picks up its new units is not tested.
Evidence: commit 74aedae9
## D70 — Method package review: one routing table, no clarification questions (2026-10-16)
Decision: SKILL.md routes every `task_type` through one table, and a step states its interpretation in a limits or notes field instead of asking a question. `capability_notice` is named only for `grounded_answer`, and `skill_package_hash` changes.
Why: A review with GPT Astra High found routing and wording that no longer matched the steps, such as a missing `research_title` route and a clarification question no step can ask.
Limit: Wording only, checked against the code paths each file names; no real-model run, so the effect on answers and reports is not measured.
Evidence: commit 74aedae9
## D69 — A work the survey-title rule set aside is labelled code-decided (2026-10-16)
Decision: The cutoff gives a work set aside by the survey-title rule the reason `code_decided`, and `work_state` gives it the blocker `code_decided` instead of `budget_deferred`. Only the labels change.
Why: The cutoff labelled such works `not_screened_at_cutoff` and the closure `budget_deferred`, but a code rule decided them and no budget touched them.
Limit: Workflow tests with the fake adapter and SYNTHETIC records, no live run; stored cutoffs from earlier runs keep their old labels, and the UI does not show these two values.
Evidence: commit 7fb51119
## D68 — Failed table cells no longer stop a report (2026-10-16)
Decision: When a cell extraction fails only on single answers, the passing answers are kept and the failing columns are asked once more; a column that still fails is stored as `not_verified`. `report_ready` no longer needs `continue_with_failed`, and every included row stays in the report with a `basis` note on PDF versus abstract-only rows.
Why: In a live Luna run, `anchor_not_in_passage` failures emptied whole batches (7 of 49 cells in one research, 16 of 40 in the other) and starting a report returned 409.
Limit: Workflow tests with the fake adapter and SYNTHETIC records plus the Playwright report spec, no live model run, so how often the retry fixes a quote is not measured.
Evidence: commit 8a973c0b
## D67 — A follow-up opens no question revision, and an unused revision can be withdrawn (2026-10-16)
Decision: The follow-up turn's "Search for new works on this" button is removed, and the revise form now says what saving does. Migration 0021 adds `parent_revision`, `title_before` and `withdrawn_at`, and `withdraw_revision` moves the research back to the parent while nothing was made under the revision.
Why: On the owner's DBR/VBF research a report request became revision 2 in one click, and answers then read 8 of the 33 included works because the 25 uploaded files counted as unread.
Limit: Checked on a copy of the live library only (withdrawing revision 2 raised the works read from 8 to 33 of 33); the live library is unchanged, and revisions opened before 0021 keep the current title on withdrawal.
Evidence: commit e6fe78d8
## D66 — A follow-up that counts or groups works classifies each work, and the application counts (2026-10-16)
Decision: `deixis.followup_answer.v4` adds `work_classifications`, one record per work sent with groups backed by an exact quote. The application counts unique works per group and freezes the result in `followup_turns.work_groups_json` (migration 0022); the turn view shows a block per group.
Why: D64's limit: a count the model writes in claims needs an anchor per work and is not checked, and the old code published 1 of 2 such answers.
Limit: With gpt-5.6-luna (medium), 3 of 4 counting runs published, small samples show the change runs, not that it is better; a located quote does not show the work was put in the right group.
Evidence: commit f49e2625
## D65 — A report section gets a second repair before the report pauses (2026-10-16)
Decision: A report run's budget freezes `max_report_section_repairs: 2`, and each repair is built from the latest failed attempt. A repaired draft must keep the claims and insufficient-evidence entries of every earlier failed draft.
Why: In the live Luna run of 16 Oct, one section in each of two researches failed after its one repair and passed on the next attempt after a manual resume.
Limit: Workflow tests with the fake adapter and SYNTHETIC records only; whether the second repair passes as often as a manual resume did is not measured.
Evidence: notes/live-2026-10-16-review-fixes.json · commit 60c7a19e
## D64 — A follow-up puts one passage per work its table values name first, within its priority share (2026-10-16)
Decision: `priority_passages` keeps the answer's passages first (at most a quarter of the limit), then one held passage per work not yet given among the chosen table values. The total stays at half the 48-passage limit.
Why: Several values of one work could take the priority share, so a question across the works reached about 20 of the 31 works the table holds.
Limit: Ten runs per arm on one research (this rule published 10 of 10 against 8 of 10) show counts, not general quality; the counting question ended without a valid answer in 3 of its 6 runs.
Evidence: commit 4618a58a
## D63 — A table that follows the included sources adds and marks rows itself (2026-10-16)
Decision: Migration 0019 adds `evidence_tables.follows_included` and the row origin `included_later`. A sweep gives each following table a row for every included source that was never its row, queues one `table_fill` per table, and marks a later-excluded source's row "Excluded in Sources · not in the report".
Why: A source included later got no row, so `report_ready` counted it missing and refused the report (`table_not_ready`); on 16 Oct res_Ui3g… had 33 included sources and four tables of 31 rows.
Limit: Workflow tests with the fake adapter and SYNTHETIC records only; on a copy of the owner's library the sweep added the missing rows but the fills were not run, so whether the report then starts is not measured.
Evidence: commit 0c477ae4
## D62 — A full-text reading records how much of the extracted text it showed (2026-10-16)
Decision: Migration 0018 adds `stage_decisions.read_coverage`, and every decision carries `adjudication.coverage`. The Sources list shows lines like "12 of 40 text parts read, from 7 of 15 pages · two reads", and the report snapshot adds `reading`, with one sentence in sections II and VIII.
Why: A reading shows the model at most 12 passages per call of a paper with 25–40 or more, but only a run-level count was kept, and report steps labelled sources `pdf_available` regardless.
Limit: Tests use the fake adapter and SYNTHETIC records, no live run; decisions written before 0018 have no coverage, and no wording check stops a report from saying a whole paper was read.
Evidence: commit b401d5e1
## D61 — LaTeX outside $…$ in an answer, a follow-up or a report section is refused (2026-10-16)
Decision: `contracts.LATEX_OUTSIDE_MATH` makes a LaTeX command, escaped brace or script mark, or braced subscript or superscript outside delimited math a blocking issue, `math_without_delimiters`. The bounded repair asks the model to rewrite it between `$…$`.
Why: A follow-up on the DBR/VBF research (16 Oct, claude-opus-5-5) showed five formulas as raw LaTeX, because the answer view renders math only between `$…$` or `$$…$$`.
Limit: A regex escape such as `\bword` and a Windows path also match and cannot pass repair, and the corpus is small and mostly one research with only one model (Opus) run after the change.
Evidence: commit 31af2420
## D60 — Read-stage counts and slots say what was read (2026-10-16)
Decision: The cutoff gives a screened work routed to full text but not yet read the reason `unresolved_without_fulltext`, and a work whose PDF fails the identity check releases its slot. The closure adds six counts that add up to `screened_count`, and budget-stopped records are stored as `not_screened_model_budget`.
Why: A code audit of the fast-path read stage found a late PDF never read, `k_selected` saying 10 while 9 works were read, and unscreened works counted as screened.
Limit: Workflow tests with the fake adapter and SYNTHETIC records only, no live run; the UI does not read the new counts, and policies frozen before slot refill keep the old slot rule.
Evidence: commit 276bb91e
## D59 — GitHub Models removed; a model found gone is no longer offered (2026-10-16)
Decision: The `copilot` key connection is removed; the GitHub Copilot card connects with an account only. When a real step on a provider API fails with `model_unavailable` or `model_mismatch`, that model is recorded in `unusable_models` and hidden from every model choice for 30 days; Settings has Show again.
Why: GitHub retired GitHub Models on 30 Jul 2026, and Google lists Gemini models it no longer serves or answers with a newer model.
Limit: A model is hidden only after one real step has failed on it, and no real Gemini step was run with the change (fake adapter tests only).
Evidence: commit 0241c6b8
## D58 — A report section gets every table cell with its quotes before page text (2026-10-16)
Decision: A section's cells come first with their stored quotes; cells whose page is not supplied are quote-only and cannot be cited as passages. Budgets are `max(base, cells + reserve)` up to a ceiling, whole columns are dropped over it, and the review packs sections into batches of at most 30k tokens.
Why: Row-order admission gave section IV only 12–15 of 248 cells on the owner's DBR/VBF tables.
Limit: One live run (16 Oct, gpt-5.6-luna, copy of the owner's library) was valid on its first try, but it is not a quality measurement; a quote-only cell cannot back an equation claim.
Evidence: commit e98e59f5
## D57 — A report version is opened by the person; an automatic update keeps the number (2026-10-16)
Decision: A late full-text answer keeps its version and takes the next revision, shown as V2.1 (`answers.report_revision`, migration 0017). Every other valid answer opens the next version. A follow-up that asks for the report to change queues an answer run (`deixis.followup_answer.v3`, `report_change_requested`).
Why: Every valid answer took a new version, so one research collected V1–V4 and the artifact list kept growing.
Limit: Whether a follow-up asks for a report change is the model's judgment, tested only with the fake adapter's marker; the new version is a whole new answer, not an edit.
Evidence: commit 55789afe
## D56 — A formula question brings each full-text source's formula page into the answer input (2026-10-16)
Decision: When the question or an approved criterion cue asks for formulas, each full-text source keeps its first-ranked passage and moves its most formula-dense passage to second place (`formula_passages.py`, score of at least 8). Late full text follows the base answer input's recorded rule.
Why: On the DBR vs VBF research the answer said no passage held DBR's holding-time equation, though both papers were read in full.
Limit: Constants were set on this one research and the answer was not regenerated or judged with the change; the trigger is English-only.
Evidence: commit 9344c695
## D55 — D51's report rules are checked by two warnings and four behavior cases (2026-10-16)
Decision: Section validation adds two non-blocking warnings, `claim_copies_anchor` (12 or more shared consecutive words) and `experiment_wording_for_simulation`. `run_report_cases.py` adds cases RW01–RW04, one per D51 rule, each with an automatic screen.
Why: The owner asked how we know the model follows D51's rules; a check can be enforced only if it has no false alarms.
Limit: Three runs per arm with gpt-5.6-luna, read by hand, showed no measurable effect of D51 at this size, and neither warning is enforced.
Evidence: commit d350febb
## D54 — A table value whose number none of its quotes state is flagged (2026-10-16)
Decision: A value written by the model or system whose numbers appear in none of its located quotes gets the `number_not_in_quote` flag. The table shows "Check number" and the Excel export lists the warning. Values a person typed are not flagged.
Why: An audit found quotes were located but never compared with the value, so 3 dB quoting a sentence that says 2 dB was accepted.
Limit: It is a flag, not a rejection; signs, number words, `10^{-6}` forms and space-grouped thousands are not matched, non-numeric values are not checked, and the report does not read the flag yet.
Evidence: commit 116a23b3
## D53 — A follow-up reads the evidence-table columns its question is about (2026-10-16)
Decision: Each follow-up scores table values by the best rank their cited passages reached in its own passage ranking, scores columns by mean value score, and takes up to 120 values from the three best columns, each at most 400 characters. Their passages come first in the selection, up to half the limit.
Why: D50 sent the first 60 values in table order, which on the DBR/VBF research was only the first table's first seven or eight works.
Limit: Workflow tests with the fake adapter only, not yet tried with a real model; a value the table read without a number still gives none.
Evidence: commit 8b29ce10
## D52 — A table value read from the abstract is read again when the PDF arrives (2026-10-16)
Decision: A sweep (`workflow/table_refresh.py`) queues one automatic `table_fill` run per table for model-made cells read from the abstract before PDF text arrived. A valid result citing PDF text becomes the current value and the old revision stays in history; values a person wrote keep the manual recheck.
Why: Cells read from the abstract only got a `newer_text` flag and a person had to start each recheck and accept it by hand.
Limit: Tested with the scripted fake model only, and the UI notes were not checked in a browser; a paused run of the research holds every automatic re-read until resumed or cancelled.
Evidence: commit d1e30e4d
## D51 — Report sections paraphrase, relate sources and keep the kind of evidence (2026-10-16)
Decision: The shared rules of `report.md` add four writing rules: claim text is a new sentence while anchor quotes stay exact; a paragraph relates its allowlisted sources; wording keeps the evidence kind (simulation versus experiment); a method moved to another setting does not take its original guarantees.
Why: A PDF-grounded writing skill from another repository was checked, and most of it already existed in `report.md` or code; these four rules were missing.
Limit: One live report pair on the DBR/VBF research (gpt-5.6-luna, medium) is not a quality measurement, and completion is noisy under both rule sets.
Evidence: commit a766b6d4
## D50 — A follow-up starts from the answer and evidence table and may ask the library once more (2026-10-16)
Decision: The `conversation` input adds `evidence_table` (up to 60 current values), a `reserve` of included works' passages, and `priority` passages that go first. `followup_answer` v2 adds `more_queries`: up to three phrases rank the pool again for a second call, within a budget of four calls.
Why: After D49 a follow-up did not read the evidence table and could not look past the passages the first ranking chose.
Limit: Workflow tests with the fake adapter only; whether a real model asks for more at the right time, or answers better from the table, is unmeasured.
Evidence: commit 5381808a
## D49 — A follow-up is read in its conversation and over the research as it has grown (2026-10-16)
Decision: The `followup_answer` input carries `conversation`: the research question, the latest valid answer's claim texts, and the last three turns' claims, labelled context, never evidence. The pool adds works whose full text was read and included after the answer's run started.
Why: A follow-up was sent as its own question with no research question or earlier turn, and the model replied that the earlier question was not given.
Limit: Workflow tests with the fake adapter only, so whether answers to general requests are useful is unmeasured; earlier turns' claims are passed without citations.
Evidence: commit f4666355
## D48 — Lines of unmapped PDF symbols are marked, not guessed (2026-10-16)
Decision: Extraction `layout-v5` replaces a line whose visible characters are at least 30% U+FFFD with `[symbols not readable in the PDF]`; the passage view shows it as a note. No OCR text enters a text-layer page.
Why: On the owner's library 19 of 35 PDFs had 204 passages of "�" rows, and Tesseract changed numbers (`10−2T2` → `10-77?`).
Limit: The symbols are lost, not recovered; a line under 30% keeps its "�", only 6 affected PDFs were re-extracted, and Mathpix (D40) is still untried live.
Evidence: commit 97862dec
## D47 — The Library shows the works a research kept, and all works on request (2026-10-16)
Decision: `library_view` gives each work `relevant_research_ids`, and the new Scope filter defaults to Relevant (user-added, included on full text, or abstract candidate without a failed full-text criterion). All works lists everything as before; nothing is deleted.
Why: One research held 742 works in the Library, of which 31 were included and about 530 were never read.
Limit: Unresolved works appear only under All, the choice is not remembered between visits, and it was measured only on the owner's library (47 relevant of 743).
Evidence: commit bc5dad2f
## D46 — "Continue without PDF": a work with no findable PDF is read from its abstract (2026-10-16)
Decision: On a `no_fulltext` row, "Continue without PDF" replaces "Find PDF". The choice is stored in `pdf_skips` (migration 0016), the work leaves the waiting counts and goes to `abstract_by_choice`, and it can be undone or given a PDF later.
Why: A work no route found an open copy for stayed on "Waiting for your PDF" for good, and Find PDF repeated a failed search.
Limit: Shown with SYNTHETIC records and a scripted model, not run on a live model or seen by the owner in the app; a skipped work without a passing abstract is still left out of the answer.
Evidence: commit 94b25138
## D45 — An equation pass after a reading leaves the person's file read (2026-10-16)
Decision: `Store.page_digest_holds` accepts the digest of the current extraction or of the extraction the equation pass was laid on (suffix `+marker-`, `+arxiv-latex-` or `+mathpix-` removed). OCR and a new base extraction still make a different file.
Why: The equation reader writes a new extraction after the reading, so 8 files the model had read showed as "Your PDF, not read yet" and the answer left them out.
Limit: Tested with SYNTHETIC records and on the library copy (8 unread → 0); the reading saw the text without the equations, and nothing reads the file again for them.
Evidence: commit c0e25cd0
## D44 — A work that late full text excluded stays out of later answers (2026-10-15)
Decision: `late_revision.excluded_works` lists works a late read excluded; every answer except the late revision drops them with reason `fulltext_excluded_after_cutoff`. A person who includes the work again overrides this.
Why: With all late PDFs excluding their work, no revision was written and a new answer rebuilt its input from the cutoff and read the excluded work from its abstract again.
Limit: Shown with SYNTHETIC records and a scripted model, not a live model; the exclusion reason is not shown in the UI and other full-text exclusions are not covered.
Evidence: commit 99b06eb6
## D43 — Answers and reports use plain prose; the phrasebank leaves the package (2026-10-15)
Decision: `references/phrases.md`, the frame check and the `report_phrase_repair` step are removed, and the prompt asks for plain sentences in the model's own words. `domain/phrasebank.py` became `domain/wording.py` and keeps language detection and the own-work and plural-source checks.
Why: With every sentence built on a phrasebank frame, the DBR/VBF report opened almost every claim with "It has been reported that …", which the owner found forced.
Limit: Not measured on a live model run; removing frames also removes the only check on certainty wording, which now rests on the prompt and answer review.
Evidence: commit b0bd4754
## D42 — The citation map reads stored OpenAlex reference lists and fills gaps only when asked (2026-10-15)
Decision: `GET /api/researches/{id}/citation-map` links works whose stored reference lists name each other, plus up to 40 outside works, with no provider request or model call. A `citation_map` run (migration 0015), started by the person, fills missing lists through OpenAlex only; outside works can be added as undecided sources.
Why: The development-lines panel stayed empty with one or two sources, and the owner wanted a citation map.
Limit: Live check on one research (Zeng 2022 single-PDF) only; a work without a DOI and without an upload match stays unresolved, and a link shows only that a list names the other work, not what it says.
Evidence: notes/citation-map-plan.md · commit df0e77bb
## D41 — Text drawn inside a vector plot stays out of the page text (layout-v3) (2026-10-15)
Decision: `pdf._mark_plot_labels` finds drawing clusters with at least 10 sloped lines or curves, widens each by 22 pt, and drops small-type blocks inside (at most 8 lines and 60 characters, not captions or headings). Extraction version becomes `layout-v3`.
Why: On a paper with eight vector plots, every tick value, axis title and panel mark appeared as its own paragraph in the page text.
Limit: Measured on that paper and on 60 random PDFs (366 dropped blocks); raster-figure labels, labels set at body size and labels beyond 22 pt are not caught, and tables drawn only with rules are kept.
Evidence: commit 566c01ed
## D40 — Mathpix can read numbered display equations from page images, behind a switch that starts off (2026-10-15)
Decision: Settings gets a Mathpix tile and a switch (`mathpix_equations`, default off) with a monthly budget of 500 and 60 requests per PDF. Equation crops go out as images only, and an answer is kept only if it is one equation, confidence at least 0.5, and its letters, scripts and signs match the PDF text layer. Model inputs get `equation_fallbacks`.
Why: Without Marker, a PDF with no arXiv LaTeX source keeps its display equations as broken text layer, and Marker needs 4.4 GB.
Limit: No Mathpix call was made while building; tests use a scripted transport and SYNTHETIC PDFs, and the misread rate is unmeasured (a wrong digit passes the gate).
Evidence: notes/equation-reader-plan-2026-10-15.md · commit 1f3da5bf
## D39 — A local model gets calls one at a time and no read or answer deadline (2026-10-15)
Decision: A keyless connection (Ollama, LM Studio) sends one call at a time with a 1,200 s limit. Ollama steps use `/api/chat` with `think: false`, the schema as `format` and a sized `num_ctx`; an input over that length fails before sending. Local runs freeze `no_deadline_stages = ["read", "answer"]`.
Why: A Quick research on qwen3.5:9b through Ollama passed 1 of 10 model calls, and the owner chose no time limit for local models.
Limit: LM Studio's thinking and context length cannot be set through the API, a local Quick run can take an hour or more, and Home's depth text still shows the hosted minutes.
Evidence: commit 83fb2162
## D38 — Work keys read as first author, four-digit year and first title word (2026-10-15)
Decision: `source_keys.key_stem` builds keys like `zeng2022multiparty`: first author's family name, four-digit year or `nd`, first non-stopword title word, each part cut at 20 letters. Collisions add `b`, `c`; migration 0013 clears every key and startup reassigns them.
Why: Keys were the family name cut to 10 letters plus a two-digit year ("Nakano13"); the owner wants the Google Scholar / BibTeX form.
Limit: Keys in frozen report snapshots and in files exported earlier keep the old form.
Evidence: commit c06e42f2
## D37 — An uploaded PDF takes its title, authors and abstract from the OpenAlex record it matches (2026-10-15)
Decision: On upload, `documents/upload_record.py` matches the file to OpenAlex by DOIs on the first two pages, else one meaning search on the head of page 1; a work counts only if its title (four words or more) stands in that head. A match fills authors, year, venue, DOI, abstract and more; no match changes nothing.
Why: An uploaded PDF became a source with only a file-name title, no authors, and sometimes a wrong title.
Limit: The title route takes whichever record OpenAlex holds under that title (the owner's preprint got the INFOCOM 2022 record), checked live on one file only; the match rate on real uploads was not measured.
Evidence: commit 1808f603
## D36 — arXiv PDFs take their numbered equations from the authors' LaTeX source by default (2026-10-15)
Decision: `load_settings` now defaults `DEIXIS_ARXIV_SOURCE` to `auto`, so the arXiv source route runs whenever Marker is neither installed nor installing (POSIX only). `off` still turns it off.
Why: Without Marker, display equations show as broken text layer, and the route needs no model and took a median 0.47 s per paper, with 40 of 40 sampled placements right by eye.
Limit: Only arXiv versions with `.tex` source and numbered display equations benefit, each PDF costs one or two arxiv.org requests, and nothing was measured again for this change.
Evidence: commit b41a3ee9
## D35 — OpenAI API reasoning efforts come from a fixed per-model table (2026-10-15)
Decision: `models/openai_api.py::EFFORTS` lists efforts per model, read off a live probe where the API refuses an unsupported effort with HTTP 400. The chosen effort is sent as `reasoning.effort`; GPT-4o and GPT-4.1 are offered none.
Why: D34 offered no effort on the OpenAI connection because `/v1/models` does not say which efforts a model takes.
Limit: The table is fixed and goes stale for new models, the Codex models are not in it, and no paid answer was received with an effort set.
Evidence: commit 5a809603
## D34 — Direct API keys for Claude and OpenAI; OpenRouter, MiMo and a generic local server (2026-10-15)
Decision: Adds `anthropic` and `openai` API-key connections (one tool-free request per step, structured outputs, `model_mismatch` on a different answering model), `openrouter` and `mimo` entries, and a keyless `local_server` limited to loopback addresses. Account sign-in paths stay; loopback calls bypass proxies.
Why: The approved Settings redesign offers an account or an API key per company, but Claude ran only through the CLI and `OPENAI_API_KEY` served only embeddings.
Limit: Every test uses mocked transports; no request was sent to the Anthropic, OpenAI, OpenRouter or MiMo APIs or a real local server, and MiMo's model ids are fixed in code.
Evidence: commit af41a88
## D33 — A keyless source's Test sends one request without a key and reports only whether it answered (2026-10-15)
Decision: `POST /api/providers/{id}/test` sends one one-record read to the connector's endpoint without a key (20 s time-out, no retry) and reports answered with HTTP status, or the failure reason. Only connectors in keyless mode are tested; nothing is stored.
Why: The mockup gives Crossref, arXiv and the OpenAlex sheet a Test button, and Settings had none for a source used without a key.
Limit: Tested with mocked transports and the fixture server only, and an HTTP 200 does not show that a search would return records.
Evidence: commit 135ebf5a
## D32 — The library's folder can be changed in Settings; the move happens at the next start (2026-10-15)
Decision: Settings → This computer → Data location shows the folder, size by part and free space, and Change location. The new folder is stored in `location.json`, and `deixis serve` moves the old folder's entries at the next start, the database last.
Why: The owner asked for a "Data location" card like Claude Science's; until now only `DEIXIS_DATA_DIR` could move the library.
Limit: Tests use temp folders and a fake cross-disk failure; no move to a real external disk was run, the macOS folder chooser was not tested, and a moved Marker or built-in model install may need reinstalling.
Evidence: commit 29f83fb9
## D31 — A run's OpenAlex and Semantic Scholar requests are stored one row each and counted in Usage (2026-10-15)
Decision: Migration 0011 adds `provider_requests`: one row per attempt of `providers.common.send` for a run, and per OpenAlex PDF lookup by DOI. The run's Usage box shows OpenAlex and Semantic Scholar counts with refused and not-known-whether-sent attempts named apart.
Why: The Usage box gave OpenAlex's day budget but no count of the run's own requests, and retried searches and planning requests kept no trace.
Limit: Hosts other than OpenAlex and Semantic Scholar are stored but not shown, and tests use fake transports; no live run was counted.
Evidence: commit 398badef
## D30 — Settings is split into four tabs; the mockup stays one page (2026-10-15)
Decision: Settings has four tabs, Models, Sources, Usage and General, opened by `#/settings/models|sources|usage|general`. Each section is rendered once so connection state survives tab changes. Tabs are in the app only; parity compares with every tab shown.
Why: Settings had grown to eleven sections on one page and the owner found it hard to scan.
Limit: The tab bar has no `role=tabpanel` element, and checks ran on SYNTHETIC fixtures at 1280 and 390 px only.
Evidence: commit d05fa01f
## D29 — A key saved in Settings wins over the same key in the shell (2026-10-15)
Decision: Supersedes D19's "a key set in the shell still wins". Saving a key stores it in the keychain and puts it into the process environment over the shell value; Remove key deletes only the keychain copy and restores the remembered shell value. DEIXIS never changes or removes the shell key itself.
Why: The owner found Semantic Scholar's card with no way to enter a key, and a saved key that is silently not used reads as a bug.
Limit: Tested with an in-memory keychain and fake shell values; the real macOS Keychain and a real shell override were checked only by hand in the browser.
Evidence: commit 608477ed
## D28 — Answer step: organize by topic, give trade-offs, match certainty to evidence (2026-10-15)
Decision: The answer instructions now group paragraphs by topic, answer questions that name alternatives with the conditions under which each does better, and state a contradicted or unshown premise in the first paragraph. The answer review notes three new failures in its existing `notes` field. No schema or validator change.
Why: Some writing rules of an outside literature-review skill were missing from `references/source-grounded-answer.md`, and its tools do not fit DEIXIS.
Limit: Instruction text only; the application does not check these rules, and answers on a real model were not compared.
Evidence: commit 93e05301
## D27 — A paper OpenAlex flags as retracted gets a "Retracted" mark (2026-10-15)
Decision: OpenAlex searches and chain reads now ask for `is_retracted`; the flag is stored per version (migration 0010) and per work, shown as a "Retracted" mark in the UI, and passed to model steps as "OpenAlex flags this work as retracted".
Why: DEIXIS dropped retraction notices by title but never noticed when a paper it found had itself been retracted.
Limit: Only OpenAlex supplies the flag, and it is as of the read date; the mark was checked by eye only, no real model was run, and how often retracted papers reach answers was not measured.
Evidence: commit 3f1f0ba1
## D26 — A plan word that no sent query carried is shown as not searched (2026-10-14)
Decision: When the protocol freezes, the plan records for each search word whether a sent query carries it and, if not, why (`query_limit`, `not_sent` or its own drop reason). The plan step and the Search plan panel strike through such words and list them with the reason.
Why: A word of the frozen vocabulary can be cut from every query; in the [parity] research the sixth task word "modeled" does not fit the OpenAlex keyword query.
Limit: Measured on synthetic vocabularies and the fixture's [parity] research only; the record says what the plan sends, not whether a request was answered, and no live provider was asked.
Evidence: commit 0e139199
## D25 — A model session stores its reasoning effort; the model line names only that (2026-10-14)
Decision: Migration 0009 adds `model_sessions.reasoning_effort`; the Codex, Claude, Gemini and DeepSeek adapters store the effort they sent, and an OpenAI-compatible connection stores null. The model line names a stored effort, or the model alone when none was stored.
Why: D15's model line named no effort because sessions kept none, and the page fell back to the model's listed default.
Limit: Tested on synthetic records and a scripted second model only; whether a service honoured the effort is not checked, and an answer's or review's own model record still carries no effort.
Evidence: commit ab32fcbf
## D24 — GitHub Copilot CLI runs research steps with every Copilot tool off (2026-10-14)
Decision: New connection `copilot_cli` runs one `copilot -p --output-format json` call per step in its own `COPILOT_HOME`, using the signed-in account, with tools denied and checked in the event stream. Qwen Code, OpenCode, Goose, Kimi, Mistral Vibe, Aider, Cline and Amp stay detected only.
Why: The owner asked for the coding CLIs to run steps on macOS and Windows; only Gemini CLI and Copilot CLI met the headless, no-tools and model-reporting checks.
Limit: Live checks ran once on the M1 Pro (Copilot CLI 1.0.98, gpt-5-mini); Windows was not run, and no reasoning efforts are offered.
Evidence: commit d2807c72
## D23 — Gemini CLI connection with a Google account (2026-10-14)
Decision: New connection `gemini_cli` runs each step through the `gemini` CLI in a throwaway home, with no tools, MCP servers or user settings, and fails closed on any tool event or a different answering model. The CLI uses the person's own sign-in, which DEIXIS never reads or copies.
Why: People without an API key or a paid subscription should still be able to run DEIXIS.
Limit: Google refused the owner's account on 14 and 15 Oct with UNSUPPORTED_CLIENT before any model request, so no real step has run through this connection; the model check and answers are tested only with a fake CLI.
Evidence: commit d0892a70
## D22 — Six more model connections run through the OpenAI-compatible adapter (2026-10-14)
Decision: Grok, GitHub Copilot (GitHub Models), GLM, Muse Spark, Muse Glimmer and Ollama use `models/openai_compat.py` with no tools, JSON-object mode and a check of the answering model. The "Planned model connections" group is gone.
Why: Settings listed these six as planned with no adapter, and the owner asked for them to work on macOS and Windows.
Limit: Mocked transports only; no live request was sent to any of the six, and the UI still says "not yet verified against the live API".
Evidence: commit 73e448bb
## D21 — Sign in to Codex and Claude Code from Settings (2026-10-14)
Decision: The Codex and Claude Code cards get a Sign in button that opens a visible terminal on the person's computer and runs the tool's own login command. DEIXIS does not read the terminal; it polls the tool's health check and never reads or stores the tool's credentials.
Why: The cards only showed a command to copy, and Codex runs in DEIXIS's own Codex home, so it read "Not signed in" until a login was made there by hand.
Limit: Tested with a fake launcher and fake health check only; no real Terminal, cmd.exe, Linux terminal or login command was run.
Evidence: commit d6acf4b0
## D20 — Built-in embedding packages are pinned with hashes; a differing copy shows "Update available" (2026-10-14)
Decision: `embedding-requirements.txt` lists every package with version and hashes, and the install syncs exactly that file. `installed.json` records the file's sha256; a mismatch shows "Update available" with an Update button, and Settings gains a Check for updates button that fetches nothing.
Why: The install pinned only `fastembed==0.8.1`, so installs a month apart could differ, and a changed pin never reached an already installed copy.
Limit: The lock was generated on macOS arm64; no install on Linux or Intel was run, and a real update was run once on the M1 Pro against a scratch folder.
Evidence: commit 73e448bb
## D19 — API keys live in the system keychain; keys found in `.env` move there at startup (2026-10-14)
Decision: At startup each managed key read from `.env` is written to the keychain under service `DEIXIS`, and its `.env` line is deleted only after the keychain returns the same value. With no keychain, the key stays in `.env`. The shell-key rule was later superseded by D29.
Why: Before packaging, the owner asked that API keys not sit in a plain `.env` file but be stored encrypted where the app is installed.
Limit: Only keys in `credentials.MANAGED_KEYS` move, and the move was tested with an in-memory keychain, not the real macOS Keychain.
Evidence: commit 73e448bb
## D18 — Parity with mockup v24 is closed; the parity check stays as the UI gate (2026-10-14)
Decision: The Playwright parity project is part of the full run, and a UI change that breaks it is fixed or adds a narrow exception with its rule in `exceptions.ts`. `DEFERRED_TARGETS` stays empty, and tests never read the developer's `.env`.
Why: The parity campaign (S0–S28) brought the app to mockup v24, and S28 checked that every inventory row and exception is still real.
Limit: Parity compares layout, type, colour and icons on synthetic records at 1280 and 390 px; live, paused and failed run states are checked by behaviour specs, and model quality and live providers are not measured.
Evidence: notes/design/parity-coverage.md · commit 180f4b89
## D17 — The Library counts from the stored list and reports only what the server did (2026-10-14)
Decision: Every Library count comes from the stored `/api/library` list, "Remove from this research" removes only that research's versions with Undo, and uploads, Zotero imports, New from selection and export report only the server's answers. One version counter stops stale reads from replacing a change.
Why: The mockup's Library showed fixed counts and results that no route produced, and versions can belong to several researches.
Limit: Tested on synthetic records with mocked Zotero answers; no real model answered the Ask or table runs, and no real Zotero library was read.
Evidence: commit f3188d47
## D16 — Settings shows only what was stored or measured; a key is never shown again (2026-10-14)
Decision: Settings pills and state lines name the stored state, and opening Settings tests nothing. The proxy line and the Scopus line are separate facts, key fields are always empty, and usage figures come from stored model sessions, with "not known" for anything not stored.
Why: The mockup marked every tile "Connected" and said the proxy test opened a test article, but the app has no such route.
Limit: Tested on synthetic records with route-simulated answers; no live proxy, Scopus or OpenAlex key was used, and a keyless provider has no test route.
Evidence: commit 240c2d97
## D15 — A stopped model is replaced only by the person, and the stopped step waits for Retry (2026-10-14)
Decision: On a run paused because its model did not answer, Resume reads "Retry this step". "Choose another model" records the change only, and the run stays paused until Retry; finished steps keep their model, and a stopped review is redone as a new review beside it.
Why: The model-down notice needed a rule for what choosing another model does to the stopped run and what the page says.
Limit: Reasoning effort was not stored per call at this point (superseded by D25 from migration 0009); tested on synthetic records with a second listed model, and no real model was asked.
Evidence: commit 025adfec
## D14 — A run can be bound to the question revision the screen showed (2026-10-14)
Decision: `POST /api/researches/{id}/runs` takes an optional `expected_scope_revision` and creates the run only while that revision is current, otherwise it answers 409 and writes nothing. The Search plan panel always sends it and shows a conflict that keeps the draft.
Why: Another window could save a newer revision between the panel's save and its search request, so the run would search a plan the panel did not show.
Limit: Only the Search plan panel sends the field so far; other ways to start a run take the current revision.
Evidence: commit 1eac60f4
## D13 — "Search for new works on this" saves the follow-up as a revision without old key terms (2026-10-13)
Decision: The button saves the turn's question as the next question revision without starting a run, and clears its English key terms so the next search reads the new question alone. The turn is marked as asked under the earlier revision.
Why: A revision left without key terms keeps the previous ones, so the new question would be searched with blocks written for the old one.
Limit: Key terms the person wanted to keep are not carried over; tested on synthetic records in the fixture server only, and whether follow-ups make better searches is not measured.
Evidence: commit 3b366c92
## D12 — A person can edit the search plan; a saved plan replaces the three planning calls (2026-10-12)
Decision: An edited plan is checked with SearchQuery's term rules and saved as a new scope revision (`user_plan_json`, migration 0008). A run of that revision skips `vocabulary_labels`, `search_query` and `criterion_proposal`, searches only the plan's words, and treats an unchecked provider as `excluded_by_user`. OpenAlex is required.
Why: The mockup's Search plan panel lets a person change the search words, criterion and optional providers, then search again.
Limit: Full-text acquisition still asks Crossref for PDF links whatever is unchecked; tested with synthetic records and the fake model only, and whether edited plans find better works is not measured.
Evidence: commit 7b47fef0
## D11 — Follow-up questions are answered only from passages the research already holds (2026-10-12)
Decision: Each follow-up is one `followup_answer` run over the latest answer's frozen evidence (or the included works), ranked by word match and meaning. Every quote must be found in its passage; an invalid answer after one repair becomes an unverified draft with no citations.
Why: The follow-up box must not start a search or cite anything the research has not read.
Limit: Whether a question counts as answered is the model's call, and a found quote does not prove support; tested with synthetic records and the fake model only, and one live gpt-5.6-luna run is still owed.
Evidence: commit cd59303d
## D10 — OpenAlex semantic requests overlap behind a 1.5 s start gate; pages hold 100 records (2026-10-12)
Decision: Every OpenAlex semantic attempt waits at one process-wide start gate (`openalex.SEMANTIC_PACER`, 1.5 s between starts) while replies may overlap, and seed requests of a version 2 plan run concurrently and are written in seed order. `openalex.MAX_RESULTS` is 100.
Why: D6's live check found each seed's semantic request took 5–6 s and ran one after another, taking time from the keyword pages.
Limit: 1.5 s comes from one live probe of 6 overlapping requests (1.0 s drew one 429); other keys, load and networks were not measured, and the time saved per seeded run is not measured live.
Evidence: commit aae001f9
## D9 — An answer the person starts may read works screened after the cutoff (2026-10-12)
Decision: A new person-started answer may read works that a Screen more run of the same revision made candidates through two agreeing abstract reads. Each such row carries `screened_after_cutoff` and `evidence_basis: abstract_screening`, and `selection_revision` rises so earlier answers read `stale_selection`.
Why: Without a change, works screened by "Screen more" would never reach an answer, and regenerating would give the same text.
Limit: Abstract-based evidence only, and only works left out as `outside_read_window` or `not_screened_at_cutoff` qualify; measured on synthetic fixtures with a fake model, and usefulness to a researcher is not measured.
Evidence: commit e1f943d2
## D8 — The interface matches the mockup; mockup-only elements become real features (2026-10-11)
Decision: Every screen matches mockup v24 in layout, order, sizes, wording and icons; elements without a backend are built as small real features and no placeholder data ships. Copy that claims something the app does not do changes. This overturns parts of D5, and a Playwright parity check with an exceptions file guards it.
Why: After the D5 port the owner compared the app with the mockup and asked for the same screens ("make everything real").
Limit: The parity check and acceptance suite run on synthetic fixtures, so they show layout and behaviour, not model quality or live provider access; follow-up answers, Screen more and the edited plan each still need one live run.
Evidence: notes/design/elicit-style-mockup/index.html, notes/design/parity-plan.md · commit de294f88
## D7 — A downloaded built-in model is used when nothing else is chosen (2026-10-11)
Decision: With nothing saved, semantic search uses Gemini when its key is set, else the built-in model when it is downloaded and its files check out, else it is off; a saved choice always wins. Home shows an info notice with a download button when it is off only for that reason, and the protocol names the model the run froze.
Why: A person without a key started with keyword ranking only and was not told why.
Limit: Whether ranking with the built-in model or Gemini gives better lists was not measured; a person with only an OpenAI key still starts with semantic search off, and the built-in model reads English only.
Evidence: commit 7784cb15
## D6 — Seeds widen the search, the question decides the order (fast_path_search version 2) (2026-10-11)
Decision: A `seed_pdf_v2` run sends the question's unseeded semantic request plus one OpenAlex semantic request per seed, and ranks with `seed_max_v2` so seed PDFs push no code graph seed out and score by the nearest seed. An unseeded run is unchanged.
Why: Under D3 about two thirds of the one semantic request was seed text, and each seed PDF pushed a question-chosen graph seed out.
Limit: Live check (3 questions, two runs per arm, leaky target seeds): share of remaining targets in the top 50 was 0.51 with 1 seed vs 0.42 without, and 0.47 vs 0.39 with 3 seeds, but one target moves a share by 0.07–0.33.
Evidence: notes/seed-live-2026-10-12/RULE.md · commit c896e00
## D5 — The interface takes the mockup's look (2026-10-11)
Decision: Colours, tokens and fonts take the mockup's values (Inter for the interface and reading text, Source Serif 4 kept for the report), with DEIXIS's ink blue kept. Contrast of at least 4.5:1 for text comes before the mockup, and structure and class names stay.
Why: The owner reviewed the clickable mockup (v24) and asked for its look in the app.
Limit: This changes how the app looks, not what it does; the 4.5:1 check covered token pairs, not every rule, and nobody tested whether the new look is easier to use.
Evidence: notes/design/elicit-style-mockup/ · commit 0c90edc8
## D4 — An answer over attached PDFs reads them in full width (2026-10-11)
Decision: When the research uses attached files only, the per-source passage cap is `max(6, limit // number of sources)`, and a passage that reads as a numbered reference list is ranked after every other passage but never dropped.
Why: A live attached-only answer gave the model 12 of 77 passages, two were reference-list chunks, and the second paper's result pages never reached the answer.
Limit: Four live runs, one each (gpt-5.6-luna, 11 Oct), with no person checking the claims; the detector misses author-year reference lists and was checked on two IEEE papers only.
Evidence: commit 8b924ffe
## D3 — Up to five seed PDFs, uploads and Zotero through one gate (seed_pdf_v2) (2026-10-11)
Decision: The seed is an ordered set of at most five PDFs from uploads, Zotero or the library through one function; the excerpt budget splits across seeds, each seed is matched in OpenAlex, and matched seeds become the first chain seeds. The semantic query is cut to 1,500 characters, the limit the live API accepts.
Why: With several PDFs Home made the user pick one, and a Zotero collection alone started no search.
Limit: Live check (11 Oct, one run per arm, leaky target seeds): 1 seed gave 0.55 vs 0.46 without, but 2–3 seeds gave 0.42 vs 0.44; the frozen rule's verdict was "help not shown", and single runs may be noise.
Evidence: notes/seed-live-2026-10-11/RULE.md · commit fbdaa8e5
## D2 — The seed PDF guides the search (seed_pdf_v1) (2026-10-11)
Decision: A discovery run with a ready seed looks the PDF up in OpenAlex (`seed_match` step) by DOI and then a semantic request, freezes the result in the protocol, and uses it in the chain, the semantic query and the ranking. The query-writing model also receives the seed excerpt.
Why: The UI said the seed PDF's passages "guided the search", but no search step read them.
Limit: How often the matcher picks the right work, and whether seeding raises the targets in the top 20, were not measured; tests use synthetic records, and PDFs with a cover page match nothing.
Evidence: commit 05666829
## D1 — Baseline: decisions in force at the 10 Oct 2026 clean start (2026-10-10)
Decision: Today's fast path became the only search path (old D250–D260), and the old search rounds, term expansion, old chain, interactive term approval and support for older libraries were deleted. The entry restates what the code does: stored model-step inputs and no model tools, evidence and citation rules, the `fast_path_v1` policy and its depth numbers, providers, and storage.
Why: The owner chose a clean start and wanted one starting point for later entries.
Limit: It adds no behavior; tests use synthetic records and a scripted model, so they show workflow behavior, not answer quality or live latency, and the anchor locator's 0.9 match ratio is provisional.
Evidence: commit 5a30689, 8637fa3
