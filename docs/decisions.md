# DEIXIS decisions

Durable decisions, newest first. Each entry is short: status, what was decided, and the main limit. The full original text is in Git history at commit `d213395`. An entry does not turn an unimplemented proposal into a working feature. Status values are `accepted`, `superseded`, `rejected`, and `deferred`.

## D232 — The model advises on each term-inflation warning, and under `warn` its advice is applied
Status: accepted (Claude subagent wrote; no external review yet) · Date: 2026-10-05
Context: D227 opens the approval card when a term makes the gate query match at least 1,000 records and at least 10 times as many as it matches without the term. The rule is numeric and false-alarms. On the DBR/VBF question, "sensor networks" (18,369 with, 535 without, next to "underwater acoustic") is a right warning: alone it pulls in land-based sensor network papers. "routing protocols" (18,369 with, 190 without, next to "depth based routing" and "vector based routing") is the question's own subject, and taking it out would lose most relevant papers. The owner first wanted the model's advice shown in the card, then decided the user should not have to step in at all.
Decision: When the approval has at least one warning, nobody has submitted and no earlier person's approval covers the question, the run makes one optional model call, `term_advice` (operation key `term_advice:1`, contract `TermAdvice`, `deixis.term_advice.v1`, method file `references/term-advice.md`, literature model, no schema repair, no tools). The StepInput carries an `advice_target`: the question, the searched terms and each warning with its two counts. For every warned term the model returns `remove` or `keep` and one plain English sentence. A semantic check refuses a phrase that was not warned and a phrase given twice; the whole output is then not used. The step counts against the run's model-call budget, and the discovery budget gets one extra call (`ADVICE_CALLS`). The advice is stored in the approval step (`advice`, `advice_model`) so a resumed run calls nothing again.
Under the default `warn` mode with advice in hand, code applies it: each `remove` becomes the user's own remove operation (`approval.apply_advice`), with the guard a person meets, that a searched group is never left empty; a removal that would empty its group is not applied and the record says `last_term_of_group`. `keep` changes nothing. The protocol then freezes and the run goes on with no card and no pause. The approval record says `approved_by: "model_advice"`, `asked: false`, and lists per warned term the recommendation, reason, both counts and whether it was applied, with the model. Such a record is never taken back as a person's earlier approval. PRISMA-S item 10 says no person reviewed the vocabulary and names the terms the model removed. The transcript's search plan step shows one line per advised term with the model's icon and name ("removed “X” from the search (18,369 → 535 papers): reason", "kept “Y”: reason").
If the call fails, the budget is spent or the output is invalid, the card opens as it did before this decision, with no advice. `ask` mode still always shows the card, now with the advice beside each warning (the advised button filled, a keep recommendation softening the title). `as_proposed` is unchanged. The "paused" toast is no longer raised for `protocol_approval_needed`; the card says it.
Limits: Not measured on a live run: no real model has been asked, so whether it keeps "routing protocols" and removes "sensor networks" is unknown. The model may remove a term the question needs, and the user learns it only after the fact from the transcript line; the way back is a new revision or a correction in `ask` mode. One more model call for every approval that has a warning. The model sees the counts and the question only, not the records behind them. The method file carries no worked example, and the package hash changed with it.

## D231 — The second round searches the abbreviations the first round's abstracts define for the task terms
Status: accepted (Claude wrote, gpt-6.1-sol medium reviewed: two fixes adopted) · Date: 2026-10-05
Context: On the DBR/VBF benchmark Memon 2018 names the two protocols only as "DBR" and "VBF", so neither first-round query found it; the model's query ("underwater acoustic sensor networks" AND three routing phrases) found 0 of the 6 reference papers and the code's (`underwater AND ("depth-based" OR "vector-based")`) 5. A SPLADE query expansion was tried first and dropped: no tested model has "DBR", "VBF" or "forwarding" in its vocabulary, and its other additions were sonar, submarine, boat, diver. A method-package rule asking the model for the setting's other common names was measured on five questions with gpt-5.6-luna, two runs each, and dropped: it gave more setting terms (1.9 per answer against 1.4) but on this question the second name was "underwater wireless sensor networks", which none of the six papers use (1/6).
Decision: `vocabulary_expansion` reads every first-round record's abstract, the code query's records too, for "spelled-out words (ABBR)" whose initials match and whose words hold a task term of two words or more, or a three-word term without its last word ("vector-based forwarding (VBF)" for "vector-based routing"); terms of the model's and the code's query both count. An abbreviation at least 2 abstracts define, that is not a word of a task term, is counted once with the setting block and accepted at ≥ 20 (`MIN_FIELD_COUNT`); the share rule is not applied, since a short abbreviation means other things elsewhere ("DBR" is also a Bragg reflector). At most 4 are accepted. They get their own second-round query, origin `abbreviation`: the code query's setting where it was searched, the model's otherwise, AND the abbreviations alone. The phrase queries keep the model's setting, as measured, and the two arms share one second-round allowance of `max_provider_requests` queries, the abbreviation queries first. The accepted abbreviations join the searched task terms the ranking and the abstract stage read.
Limits: Replayed offline once, on a copy of today's DBR/VBF run (873 first-round records, 760 with an abstract): DBR (65 abstracts) and VBF (34) were accepted; VBVA, DMDBR and DSDBR were refused on their field counts; `underwater AND (DBR OR VBF)` matched 304 OpenAlex records and all 6 reference papers, so the two rounds together found 6/6 against 5/6 before. No discovery run was made with the change, and no other question was measured. Under a small allowance the abbreviation queries can take all of it, and the accepted phrases are then not searched (quick effort with many providers). English parenthesis convention only.
## D230 — A short answer in paragraphs, and a study table built after it
Status: accepted (Claude and a Claude subagent wrote, gpt-6.1-sol medium reviewed in three rounds; the owner chose the Elicit-like layout) · Date: 2026-10-05
Context: Elicit convergence plan step 4. The owner expected a sectioned answer; the grounded answer was told to write a "comprehensive report" (17 claims, 15 opening "It has been reported that"), and a sectioned report needed the Evidence-tab table by hand and wrote 11 IEEE-style sections at about 50 model calls. Elicit shows a few paragraphs, a method box and a linked study table. D227 recorded the choice of a background table; this replaces its report half.
Decision: `source-grounded-answer.md` asks for three to five paragraphs, one `section` each, labelled by a two-to-five-word topic that states no finding (the paragraph's first claim states its point), two to four claims per paragraph, at most twenty, the first paragraph answering the question with its numbers, and no reporting frame opening more than two claims. The Answer screen shows each section as a paragraph led by its label in bold. After an sw answer run ends with a structurally valid answer to the current question revision, `report_pipeline` opens a study table once per answer (`DEIXIS_STUDY_TABLE=auto`, default): `table_columns`, the proposed columns added with `accepted_by='automatic'` and an event saying no person reviewed them, then `table_fill` runs (25 sources each, at most 8). The chain stops on a newer question revision, refills cells of an edited column, and records sources beyond 200. The table card shows each source's access. The 11-section report stays, as "Write a manuscript draft" on the Evidence tab; the old Answer-tab report panel is gone. `POST /api/researches/{id}/study-table` rebuilds the table by hand.
Limits: No live run yet: whether the model keeps to the paragraph form, and what the automatic table costs per answer, are unmeasured. A crash between two runs of the chain leaves it stopped until the person rebuilds. Playwright specs were edited, not run. The method box is not built yet.

## D229 — Citation chaining also asks Semantic Scholar
Status: accepted (Claude subagent wrote; no external review yet) · Date: 2026-10-05
Context: D95's chain asks only OpenAlex for a seed's references and citing works, so a link OpenAlex lacks is never seen. Semantic Scholar's Academic Graph API lists both directions by DOI (`/paper/DOI:<doi>/references` and `/citations`, `limit` up to 1,000, paged by `offset`; API description read 2026-10-05).
Decision: After the OpenAlex requests, the chain asks Semantic Scholar once per seed that has a DOI and direction: references (limit 1,000, one page) and citing works (limit up to the 400 cap, one page). A seed without a DOI is skipped for this source and counted in the summary. Every request goes through `common.send` (the shared 2 s pacer and bounded 429 retries), is its own step (`chain:s2:<direction>:<seed>[:<page>]`, kind `provider_chain:semantic_scholar`) and its own `search_runs` row with a `chain:` query text, so resume never resends a succeeded one and the existing chain counters and views count it. Records map with the same `_record` as a Semantic Scholar search record, pass the same title/abstract filter, and merge by DOI, so a work both sources found is one record and is counted once. The request limit is shared, not split: OpenAlex runs first and Semantic Scholar gets whatever room is left under the same `max_chain_requests` (40); the limit is not raised. This was chosen over a fixed share because it changes nothing for OpenAlex's own budget and needs no new number. A 404 is an empty answer; a rate-limited answer ends the Semantic Scholar arm and is recorded as a failed request, and the run goes on. A resumed run ends the arm at a stored rate-limited step too. A DOI is percent-encoded as path data, `/` included (`DOI:10.1109%2FJSAC...`). The citing works are one page of up to the 400 cap, like the references: the answer's `next` is read for forward only, a non-integer is a parse_error, and a repeated or falling offset is no continuation. The arm is skipped, with the reason stored (`chain_s2_plan`), when Semantic Scholar is not in the research's sources or lacks the access it needs. The budget freezes `chain_sources` and `chain_rule_version`; `RULE_VERSION` is now `deixis.citation_chaining.v2`. A run queued before this change has neither, keeps rule version v1 and OpenAlex alone, and writes no Semantic Scholar step.
Limits: The recall gain is not measured: no live Semantic Scholar chain was run and no benchmark was repeated, so whether it adds relevant works is unknown. Tests use a mocked API and show only that the arm is bounded, resumable and counted. With the limit shared, a run whose OpenAlex arm uses all 40 requests asks Semantic Scholar nothing. Semantic Scholar's list order is not by relevance and `/citations` serves at most the first 400 here. A link that failed the filter from both sources is counted once per source (the two identifiers cannot be matched without a record), so `failed_filter` can count such a work twice. The Semantic Scholar rate limit (1 request per second with a key) makes each request cost about 2 s.

## D228 — A comparison across the literature is one thing sought, not a comparator
Status: accepted (Claude wrote, gpt-6.1-sol medium reviewed; Sol's wording adopted) · Date: 2026-10-05
Context: On the DBR/VBF question the criterion proposal made VBF a comparator part (rule 8), so papers on one protocol alone failed the criterion and the owner settled 24 of them by hand.
Decision: `criterion-proposal.md` gains a hard case: when the question compares named alternatives across the literature, they are one thing sought with one part that accepts a paper studying at least one of them and reporting what is asked; neither is listed as `comparator`. "Versus" or "compare" alone does not trigger it; an intervention against a stated control, or a question or steering that requires the comparison within one study, keeps rule 8's comparator part. The skill package hash changes.
Limits: Instruction text only; no real-model case was run, so whether the model applies it is unmeasured.

## D227 — The search approval opens only on a term-inflation warning
Status: accepted (Claude subagent wrote, gpt-6.1-sol medium reviewed in two rounds; owner delegated the step 4 choices, decided with Sol) · Date: 2026-10-05
Context: Elicit convergence plan step 4. The owner found the approval card confusing; on the DBR/VBF run the model put "sensor networks" alone beside "underwater acoustic" and the matches went from 535 to 18,369 without a warning. Steps 2 and 3 have not passed the benchmark: the end-to-end run is made after step 4, because step 4 removes most of the screens a person must answer (a named deviation from the plan's order).
Decision: The new default `DEIXIS_PROTOCOL_APPROVAL=warn`. Before the protocol freezes, each term that shares its block with another searched term gets one OpenAlex count without it (the existing count probe); a term warns when the gate query matches ≥ 1,000 and ≥ 10 × the count without it. No warning: the protocol freezes and the run goes on, recorded as `approved_by: no_warning, asked: false`; such a record is never reused as an earlier approval, and PRISMA-S item 10 says no person reviewed the vocabulary. A warning: the card opens with "N matches with this term, M without it". Every probe is stored per term as it returns, so a resumed run asks nothing again; an old card without the check is checked once. `ask` still always shows the card; `as_proposed` is unchanged. Step 4's other choices, decided with Sol: the sectioned report builds its evidence table in the background; Marker gets an "answer now with PDF text" button, no pause/resume.
Limits: Thresholds picked by hand from one live case. The probes are outside the provider budget, like the existing gate count probes, and run before the freeze (D80). Not measured on a live run yet.

## D226 — A comparison question ranks records that name its task terms together higher
Status: accepted (Claude wrote, gpt-6-sol medium reviewed in two rounds) · Date: 2026-10-05
Context: On the DBR/VBF benchmark the two direct comparisons sat at inspection ranks 237 and 188 (Maulana 2019, Hakim 2018), outside the ~112 works the full-text stage tries. Their titles name the protocols only as "DBR and VBF"; the approved task terms were "routing protocols", "depth-based routing" and "vector-based routing".
Decision: A sixth code signal, `joint`, enters the rank fusion as one more list. It runs only when the question, or its saved English sentence, holds a comparison word (`ranking.COMPARISON_WORDS`) and the approved vocabulary's own task terms are two or more (the code's query and second-round phrases are left out). Forms read hyphens as spaces and drop a last word another task term ends with ("vector-based routing" → "vector based"). A record scores the count of forms its title names when two or more, then the summed rarity log(N/df) of the forms title plus abstract name when two or more; a title names a form also through an abbreviation the abstract defines for it ("Depth Based Routing (DBR)", initials checked). Any other question ranks exactly as before; the step records `not_a_comparison` or `fewer_than_two_task_terms`.
Limits: Measured once, offline, on a library copy with today's verified seeds and stored similarities: Maulana 105 → 51, Hakim 233 → 73 (both in the joint signal's top 10; 10 titles name two terms, 116 records do anywhere). The first-50 target was missed: one list of six moves a record only so far. Both would now fall inside the full-text stage's ~112, but no new discovery run was made, so benchmark gate (a) is unmeasured after this change. The comparison words are English.

## D225 — Candidates without full text give their abstracts to an sw answer
Status: accepted (Claude wrote, gpt-6-sol medium reviewed in three rounds) · Date: 2026-10-05
Context: On the DBR/VBF benchmark question (`res_qqOHHl3hGsZWrihkkwBW`) the answer read only the 26 included works. The two direct DBR–VBF comparisons a reference tool answered from were abstract-stage candidates the full-text cap (~112) never tried, so the answer said no direct comparison was in the passages.
Decision: An sw answer run stores `code:answer_abstract_sources`: up to `max_candidates` works in the latest ranking order whose outcome under this question revision is an abstract `candidate` with no full-text decision, or full-text `unresolved/no_fulltext`; selection still pending and not the person's; an abstract and no PDF text in any version. A resumed run reuses the list, less works a person decided or that got PDF text since. `_retrieve` gives them `max_answer_passages // 4` places, abstracts only, ordered by relevance alone (BM25 plus semantic rank; provider count and user choice are left out); included works share the rest as before. `max_answer_passages` is unchanged. The method package asks that a number taken from an abstract say so.
Limits: One question, one answer run on a library copy (Sol answer model, Gemini embeddings): 24 sources and 48 passages went in, Maulana 2019 entered and was cited with its 33.6 % / 19.8 % figures, Hakim 2018 was in the 250-work pool but not among the 12 abstracts (lexical place 73: its abstract names the protocols only as DBR and VBF). Benchmark gate (a) still fails. The cited claim did not itself say "abstract"; the access limitation did. An sw answer with no included work still ends `no_evidence` (D106).

## D224 — Scopus abstracts are asked 25 DOIs per request
Status: accepted (Claude wrote, gpt-6.1-sol medium reviewed in three rounds) · Date: 2026-10-04
Context: D91 asked Scopus one DOI per request. Live check on 4 Oct over the university VPN with the configured key: one `view=COMPLETE` query of 25 DOIs joined with `OR` answered 200 in 0.8 s, 22 entries, each naming an asked DOI and each with an abstract; five single-DOI requests gave the same abstract presence.
Decision: `lookup.scopus_abstracts` asks up to 25 DOIs in one request and gives each entry only to the asked DOI it names, compared normalized and answered under every key the caller used. An asked DOI with no entry is `not_found`, or `failed` when `totalResults` exceeds the entries returned. A DOI outside `10.\d+/[A-Za-z0-9._;:/-]+` is asked alone. `plan_scopus` counts the lookup budget in requests. Each request's payload goes to its own create-only file, so a resumed step never overwrites the evidence an earlier answer points at.
Limits: One 25-DOI probe on one topic and one day. The safe-DOI pattern is ours, not Elsevier's documentation.

## D223 — The PDF is revalidated on every open; no viewer lock
Status: accepted (Claude wrote, gpt-6.1-sol medium reviewed) · Date: 2026-10-04
Context: R5 (D208) asked for a viewer lock or cache invalidation after a file restore.
Decision: The asset response sends `Cache-Control: no-cache`, so the browser checks Starlette's ETag (mtime and size) before reusing a copy and never shows one read before a restore. No lock: files are stored as `<sha256>.pdf` and a restore swaps them with `os.replace`, so a reader sees the old or the new file, never half of one.
Limits: A viewer already open during a restore keeps the document it loaded until it is closed and reopened. Atomic replacement does not promise one version across separate Range requests of one viewing session.

## D222 — Zotero notes are English templates the UI translates
Status: accepted (Claude wrote, gpt-6.1-sol medium reviewed) · Date: 2026-10-04
Context: R5 (D208) left the Zotero import and Zotero-PDF notes as fixed English sentences, so the Turkish UI showed them in English.
Decision: Each note is a template with `vars` (`PDF not added: {reason}`, `its PDF attachment has no file ({mode})`); the UI calls `t(note, vars)` in its three toasts and `i18n.ts` has the Turkish entries. A test reads `app.py` and `zotero.py` and fails if a note is an f-string or lacks a Turkish key.
Limits: `reason` is the exception text and stays English. The test checks keys, not what the screen shows.

## D221 — PRISMA-S marks every planned query sent, not sent or delivery unknown; the frozen protocol stays as it was
Status: accepted (Claude wrote, gpt-6.1-sol medium reviewed in four rounds) · Date: 2026-10-04
Context: The protocol freezes the compiled queries before the first provider request (SW14.1), so a stopped run left queries in it that were never sent, and the PRISMA-S export did not say which.
Decision: The frozen record is unchanged. `prisma_s._planned_queries` reads each planned query against the steps of the runs that froze that protocol hash, matched by index and by the stored search row's provider and query text. `sent` needs a recorded send; `not_sent` needs evidence on the query's own step (cancelled, pending, or failed before send with zero sends); everything else, including a query with no step at all, is `delivery_unknown`, because a cancel is written at once while a step is written only when its page returns. Item 8 is `incomplete` when any query is not sent, unknown, or sent without a stored search record. The JSON export and the Markdown carry the per-query table.
Limits: No migration, so a request in flight during a crash stays `delivery_unknown` rather than proven either way. Tested with store-level synthetic rows, not by cancelling a real discovery run.

## D220 — Open-item fixes of 4 Oct: provisional title from the question, PDF request headers, capacity tests isolated, arXiv zero not reproduced
Status: accepted (Claude wrote, gpt-6.1-sol medium reviewed) · Date: 2026-10-04
Context: STATUS listed four small model-free items. The owner-level title choice was made jointly with Sol.
Decision: A new research is named with the question's first 15 words, `…` when cut, until the model title replaces it (`store.provisional_title`); the scope keeps the full question. `fetch_pdf` sends `Accept: application/pdf, */*;q=0.1`, and every DEIXIS User-Agent adds `mailto:` when `DEIXIS_CONTACT_EMAIL` is set. Two capacity-script tests stub `guard_repo`, so a developer's repository `.env` no longer breaks them; the guard itself keeps its own test. arXiv: six run-like searches through the real connector on 4 Oct all returned records (five of 100, one of 5), so the earlier zeros are closed as not reproduced; no code changed.
Limits: The arXiv check is one burst on one day from one network, not a discovery run. No publisher was asked whether the new headers change PDF success rates.

## D219 — Other LLMs: nine command-line tools are detected only, and one OpenAI-compatible adapter serves Qwen, Kimi and Mistral
Status: accepted · Date: 2026-10-04
Context: Users with other models asked to use DEIXIS. Two separate things were done. Qwen Code, Kimi CLI, Mistral Vibe, GitHub Copilot CLI, OpenCode, Aider, Goose, Amp and Cline are listed under Settings › On this computer as `role="detected"`, each with one fixed install command (npm, uv or brew) and a plain statement that finding a tool is not support. None of them runs a step. Separately, `models/openai_compat.py` is one adapter parametrised by connection id, name, base URL and key variable, modeled on the DeepSeek adapter: no tools, `json_object` mode, `enforces_schema=False`, no `reasoning_effort` sent or offered, 402/429 handled as DeepSeek's are, and `resolved_model` returned so the flow's `model_mismatch` rule applies. Connections: `qwen` (DashScope international compatible mode, `DASHSCOPE_API_KEY`), `kimi` (api.moonshot.ai, `MOONSHOT_API_KEY`), `mistral` (api.mistral.ai, `MISTRAL_API_KEY`). Keys are tested by listing models.
Decision: The CLIs stay detected, not run. The three API connections are wired like DeepSeek (adapter map, managed keys, Settings, step-input `model.connection` enum, test key stripping, P9 key lists). `deepseek.py` is unchanged.
Limits: Nothing was verified against the live providers: the tests use mocked httpx transports, so request shape and error handling are shown, not that these APIs accept JSON mode, return the same `model` string, or list models at `/models`. Package names were looked up in npm, PyPI and Homebrew but nothing was installed or run; the CLIs are detected by name on PATH only, so a `goose` database-migration binary would be reported as Goose. No model-quality claim for Qwen, Kimi or Mistral.

## D218 — P9 exit
Status: accepted · Date: 2026-10-04
P9 exit is recorded criterion by criterion. Final matrix pair: two consecutive full runs on `0af3216` (pytest 14,265 collected, 0 failed; process 45/45; Playwright 212/212; capacity K rows passed). Open debts carry past P9: H9 quality failures, R6/R9/R10, slice 4 E06-E18, L9 R12-R15, the deferred K03 driver fix.
Limits: One macOS arm64 machine, synthetic records, scripted models; K-row passes ran under load. H9e closes report completion only. Authorizes no new run, push or publication.

## D217 — P9 owed batch closed: L9 stays an unmeasured named debt, and the queue-pass failure is a deferred driver fix, not a packaging blocker
Status: accepted · Date: 2026-10-04
No second L9 preparation: L9 closes as a named debt and R12-R15 stay unmeasured. The K03 queue pass `prompt_too_long` came from the driver `scripts/p9_owed/l9_run.py` (one `claude -p` call, 2.19 MB, no byte budget), not the product. A size budget with coverage and deferral records is deferred and needs a freeze amendment.
Limits: Nothing measures chain recall or lineage; slice 4 E06-E18 stay untested and D157 stays partly open.

## D216 — P9 owed L9: discovery on the diffusion topic included one of three chain works, the queue pass failed on prompt size, and the corpus condition was not met
Status: accepted (measured) · Date: 2026-10-04
One L9 preparation on the diffusion topic: 1,542 works, 121 model sessions, 1 included (Nichol's iDDPM); DDIM was not found. K1 failed (1 PDF-text row, 6 needed), so the lineage run never started. The K03 queue pass returned `prompt_too_long` and was not retried.
Limits: One topic, one run; no chain-recall or lineage claim. A second preparation needs a coordinator decision.

## D215 — P9 owed slice 4 rerun: five of eighteen operations measured on H9e's report with no invariant violated; the rest untested after an unusable model proposal
Status: accepted (measured) · Date: 2026-10-04
The single permitted rerun of the slice 4 edit sequence on H9e's report (product `7188ec8`) measured E01-E05: R18 0 violations in 5 operations, R19 0/17 false positives and 0/17 false negatives. E06 was skipped because the product's `cell_recheck` proposal was not structurally valid, so E07-E18 are untested.
Limits: Five of eighteen operations, one report; D157 stays partly open. Says nothing about semantic support.

## D214 — P9 owed slice 4: one rerun on a new copy is allowed after the kit's ownership defect, under a combined budget
Status: accepted (amendment Ek S2) · Date: 2026-10-04
Fix the kit so descendants of the API listener count as owned (ancestry proven by `ps`, fail closed otherwise), add `--prior-sessions` / `--prior-seconds`, and allow ONE rerun on a new verified copy of `e/data` inside the original budget minus the first attempt's use. The old record and the unscored E03 are not reused.
Limits: A recovery measurement after an instrument defect, not a replication; prior consumption is operator-supplied.

## D213 — P9 owed slice 4: the real-report edit sequence stopped after two operations because the kit's ownership check treated the server's own Codex child as a foreign process
Status: accepted (measured, stopped) · Date: 2026-10-04
The slice 4 run measured only E01 and E02 (no R18 violation) and stopped at E03 because the kit's ownership check counted the server's own `codex app-server` child as a foreign process. The same corpus is not re-run without a coordinator decision (freeze 1.6).
Limits: Two of eighteen operations, one report; D157 stays open.

## D212 — P9 owed K6: the kill-search measurement ran once on six claims and the nearest works were never retrieved; the query shape is not shown to be the cause
Status: accepted (measured) · Date: 2026-10-04
K6 kill-search ran once on six claims (44 of 120 sessions, 34 minutes): 7/7 labelled works were absent from the retained records (S1), no claim closed, S3 0/2, S4a 72/72, S4b 1 supports, 11 partial, 8 not supports of 20. Deviations (one manual resume after a client_timeout, a kit refusal after C2, a reader that altered one passage) are recorded.
Limits: One run, one model, small calibration sets; S1 and S6 do not show query shape caused the loss. A query-compiler change needs a new decision and an independent claim set.

## D211 — P9 RF6: the code stamps `step_input_id` on every fresh model output, and a result is accepted only for the attempt that is still active
Status: accepted (implemented) · Date: 2026-10-04
`contracts.stamp_step_input_id` sets the code's own `step_input_id` on every fresh model response; a differing echo is recorded in `validation_json.normalised`, stored drafts are never stamped. Because the echo no longer proves identity, `Store.model_attempt_active` accepts a result only for the latest still-`started` session of a `running` step.
Limits: A foreign echoed id cannot be told from a copying error, since adapters supply no request token. A response for an attempt recovery closed as `outcome_unknown` is discarded, costing one extra call. New `skill_package_hash` `sha256:ccff02a1...`.

## D210 — P9 matrix-fix: the F02 write hold and the capacity server stop followed old code, and report.spec still expected the pre-RF4 draft
Status: accepted (implemented) · Date: 2026-10-03
Harness fixes only, no product code. The F02 write hold in `tests/process/p9_driver.py` now holds `stage_bytes` (the real write point); `capacity.py` re-records the server identity (`Server.refresh_ident`) so stop signals reach the re-exec'd child; `report.spec.ts:341` now asserts D207's behavior (`banned_word` pause, report `in_progress`, no draft). Full matrix passed twice in a row on `be07c4c`.
Limits: K rows ran under parallel load; capacity numbers pass the frozen thresholds but are not a quiet-machine benchmark.

## D209 — P9 RF5: a rejected warnings-only phrase repair retains the valid model draft
Status: accepted (implemented) · Date: 2026-10-03
A phrase repair is validated as a whole candidate against the original section input. If any blocking rule fails, the whole candidate is rejected and the model's pre-repair draft is kept, recorded as `phrase_repair_rejected` / `report_phrase_repair_rejected` with flagged sentences as `unframed_exception`. Applies to report phrase repair (`workflow/report/sections.py`, `phrasing.py`). New `skill_package_hash` `sha256:098f1411...`.
Limits: Deterministic and FakeAdapter evidence only; a valid draft is not shown to be semantically supported.

## D208 — P9 re-extraction R5: compatibility regression and closing record; H7 finding 2 is closed for the explicit text-retry workflow, with named limits and no must-fix item
Status: accepted (record only) · Date: 2026-10-03
Compatibility regression and closing record for P9 re-extraction R5 on `dbec4fc`: full pytest 13,553 passed, 0 failed, 2 skipped; the focused recovery set 2,009 passed; Playwright for the related specs 101 passed. H7 finding 2 is closed for the explicit text-retry workflow with named limits and no must-fix item.
Limits: Synthetic records and a scripted model only. Windows locking, power-loss durability and real torn-file recovery are not shown.

## D189 — P8 B8b: a real model read candidate review inputs (4 of 4 planted faults found, 3 of 3 behavior cases passed, one run) and the P8 closing record is written; P8 exit conditionally met
Status: accepted, measured once · Date: 2026-10-03
Four frozen synthetic candidate cases ran once on `claude-sonnet-5-5` via `scripts/model_behavior/run_candidate_review_cases.py`: 4 of 4 planted faults found, 3 of 3 behavior cases passed, 0 repairs. Matrix rows T14 and T16 were added to `scripts/p9/run_matrix.py`. P8 exit is conditionally met on synthetic and scripted evidence.
Limits: One run per case, one reviewer model, short synthetic abstracts; counts, not rates. Spec, fault design and judging are one author's. Real candidates and repeatability are not shown.

## D188 — P8 B7: follow-up has its own tab that shows what each check read, what is new to the research, and when DEIXIS was not checking
Status: accepted, implemented · Date: 2026-10-03
Follow-up gets its own tab after Evidence and before Candidates, showing each check's coverage, new records, notices, dismissed items, turned-off watches and any missed-check gap. A single subquery adds `followup_new` to `Store.list_researches` for the sidebar count. Gap acknowledgement is in-session only (no migration, no localStorage). Fixture: `tests/acceptance/followup_fixture.py`, 15 Chrome cases on port 8838.
Limits: Synthetic records and a mocked provider; Chrome only. Nothing runs while DEIXIS is closed, and the sidebar refreshes every five seconds.

## D203 — P9 re-extraction R4: the web app offers one explicit text retry per click, shows file restores and retries as separate recorded outcomes with history, and an old citation opens its own extraction
Status: accepted (implemented) · Date: 2026-10-03
Read-only backend additions, no migration: `workflow/recovery_view.py::text_recovery` adds `file_checked` and a `password_protected` reason, and a guarded GET `.../assets/{id}/recovery-history` lists an asset's text retries. The source row shows the latest recorded result, one "Retry text extraction" button per click with a fresh idempotency key, a dated history, and an old citation opens its own extraction.
Limits: Synthetic records and a scripted model; the input relation compares the recorded parser input with the recorded hash, not the file served now. Full acceptance and a11y suites were not rerun. Windows untested.

## D207 — P9 RF4: every report rule the final assembly enforces that the model can cause is now also a section validation issue, and the H9 kit keeps R9 source keys
Status: accepted, implemented · Date: 2026-10-03
Every blocking report assembly rule is either a code-derived final assertion or model-correctable and also a blocking section validation issue (duplicate claim keys, derived references and strength, counts, banned wording, equations, gap bases, word budgets, phrase rules). `report_target.validation_context` carries the frozen count domain, capped at 262144 characters. Anchor patch and phrase repair results run the full validator and end `section_failed` when invalid. The H9 kit keeps R9 source keys.
Limits: Math checks show balanced delimiters, not correctness. Not measured on a real model; historical section inputs have no validation context, so restoring such a section can be refused.

## D200 — P9 X05: the run heading takes focus by run id, and the keyboard walk waits for real states instead of racing the report run and the toast timer
Status: accepted (implemented) · Date: 2026-10-03
Three causes of the X05 keyboard-walk flake: an app race where `toRunStatus` found the run heading by position in a ref that lagged the view (now by run id), and two test timing bugs (the walk raced the evidence report growing, and a helper waited for a toast that had left after 5 s). `dismissToastsByKeyboard` no longer spins until timeout.
Limits: Measures the flake on one machine under load; does not replace the two clean RR-B matrix runs. Resume from another tab still focuses the status line, and the 390 px layout was not judged.

## D206 — P9 RF3: an empty report section is a validation issue, so the existing single repair asks the model to write claims or name the missing evidence
Status: accepted, implemented · Date: 2026-10-03
`_check_report_section` adds `Issue("empty_section", "/claims", ...)` when a `report_section` output has neither claims nor insufficient-evidence entries, so the existing single full repair (`MAX_SCHEMA_REPAIRS = 1`) asks the model to write a supported claim or name the missing evidence. The message forbids inventing claims, passages, cells, gaps or quotes.
Limits: Synthetic tests only; whether `gpt-5.6-luna` writes a non-empty section VI is not measured. The repair can still come back empty, and the run then pauses as `section_failed`.

## D187 — P8 B6: interval watches are checked by an in-process scheduler while DEIXIS runs, and a closed or sleeping computer gets one bounded catch-up per research that says what was not checked
Status: accepted, implemented · Date: 2026-10-03
Migration 0070 adds `catch_up` and `schedule_version` to watches; interval watches (cadence 1, 7 or 30 UTC days) are checked by an in-process `WatchScheduler` ticking every 60 seconds. An opening is a first tick or a gap over 300 seconds. Each opening gets bounded catch-up: at most three researches, one watch per research, queued only when the library has no queued or running run, with a 1,800-second deadline.
Limits: No real provider or model. The 60 s tick, 300 s gap and three-research cap are unmeasured policy. Nothing runs while DEIXIS is closed; a missed due time cannot be told from one missed during a busy period.

## D204 — P9 RF2: the anchor-patch schema no longer puts `$ref` next to other keywords, and every schema the product can send is checked by a stricter offline guard
Status: accepted, implemented · Date: 2026-10-03
`reason` in `report-section-anchor-repair.schema.json` becomes `{"type": ["string","null"], "minLength": 1, "maxLength": 600, "pattern": "\\S"}` so no keyword sits beside `$ref`; `deixis.report_section_anchor_repair.v1` is unchanged. `strict_compatibility_issues` becomes a conservative offline OpenAI strict-mode guard, and `contracts.model_transport_schemas()` lists the 41 schemas a model can receive, all checked in `tests/test_strict_schema_rules.py`.
Limits: No live request; acceptance of the patch schema is H9b's first gate. The guard is stricter than any known API rule and does not check the Claude or Gemini adapters.

## D205 — P9 owed real-model measurements before P10: rules for five debts are frozen, run only after H9b, with 370 new Luna sessions at most
Status: accepted (rules frozen, nothing run) · Date: 2026-10-03
Rules for five owed measurements are frozen in `product/p9-owed-measurements-freeze.md`, to run only after H9b: D129 read from H9b counts, D141 as a model-free funnel count, D157 on one report, D154 as K6 (six claims in the Q2 field), D142 as L9 on one new topic. Order: D129, D141, slice 4, K6, L9; budget at most 370 new Luna sessions, 6 Claude requests, 60 preparation requests.
Limits: Nothing was run. Each measurement is one run on one model, with Claude readers, so none establishes population rates. The L9 independence check is weaker than the one it replaces.

## D201 — P7 G1-F1: existing lookups and OpenAlex citation chaining go through declared connector capabilities with collector-based accounting; P7 exit is met
Status: accepted, implemented · Date: 2026-10-03
`registry.Connector.capabilities` maps an operation to a `CapabilityBinding`: Crossref, Semantic Scholar and Scopus `doi_lookup`, OpenAlex `id_lookup` and `citing_works`. `facade.dispatch_lookup` and `dispatch_citing` use the D199 collector; reservations settle to observed sends into new usage keys `lookup_sends` and `chain_sends`. `CONTRACT_ID` stays v1. P7 exit is met on deterministic evidence.
Limits: Mocked transports and synthetic keys only; live error and quota formats are unmeasured. OpenAlex count and distribution probes, the Scopus entitlement probe, acquisition and Zotero stay direct.

## D202 — P9 H9b: the report path is measured again on a real model after RF, first on H9's own table (not independent) and then on a fresh corpus for Q3
Status: accepted (rules frozen before any run) · Date: 2026-10-03
H9b measures the report path again on a real model: arm A on H9's prepared table (not independent), arm B on a fresh corpus for Q3, one report run per arm with H9 stop rules. Amendments Ek C to G re-pinned the product after each fix (RF2 to RF6); the H9e run on `7188ec8` completed the first accepted report (R1c 1/1, 23 sessions, `envelope_mismatch` 0), with most quality rows out of range. The H9 report chain closes there, with no H9f before P10.
Limits: One run per arm on one model; no rate or causal effect of RF4-RF6. Reader assessments are model readings, not human verification.

## D197 — P9 re-extraction R3: an old citation opens its own extraction with its input stated, reports and owner reviews share one passage-dependency rule, new extractions record the bytes they read, and repair history is backed up and purged only by authorized purge
Status: accepted (implemented) · Date: 2026-10-03
`workflow/evidence_deps.py` owns the passage-dependency rule shared by reports and owner reviews; reports add `passage_freshness` and passage views add `occurrence` with `input_relation`. New extractions record the bytes they read (observations with `retained-<sha>.bin` files); migration 0069 adds `recovery_purge_authorizations`, so repair history is purged only by authorized purge. `deixis recovery-files [--delete]` lists and removes unreferenced retained files.
Limits: Synthetic PDFs and temporary libraries only. OCR, Marker and arXiv source reads record no observation; legacy extractions keep null input. Advisory locks cannot stop outside processes.

## D198 — P9 RF: code stamps the package hash, a failing cell anchor is repaired by a model-chosen patch that code applies, and a repaired section cannot lose a claim silently
Status: accepted, implemented · Date: 2026-10-03
Code stamps `skill_package_hash` (omitted from the model-facing schema). A `report_section` repair uses an anchor patch (`ReportSectionAnchorRepair` v1) only when every issue is `anchor_not_in_cell_evidence` with one matching cell pair, and code applies the model-selected quotes. A full repair sees the failed output, and a dropped claim key is rejected unless it stays or has an insufficiency context starting `<claim_key>: `.
Limits: Only synthetic and replayed outputs; whether the patch completes a real report is H9b's question. First-pass wrong-cell anchors and non-anchor issue codes are not covered.

## D186 — P8 B5: a research can be followed by a manual check that re-reads its frozen queries or the works citing its included sources and announces each new record once, apart from the library
Status: accepted, implemented · Date: 2026-10-03
Migration 0068 adds the `watch_check` run kind and six watch tables; `workflow/watch/{store,check,run,view}.py` provide a manual check that re-reads a research's frozen queries or the works citing its included sources and announces each new record once, apart from the library. Frozen caps: 100 records per page, 2 pages per unit, 10 citing units, 80 requests, 3,000 records, 1,800 seconds. OpenAlex moves to adapter revision 3 (`publication_date:desc`). Similarity never merges or suppresses a finding.
Limits: No network or real provider; caps and deadline are unmeasured. A bounded window can miss records, and cross-provider records without a shared DOI can be announced twice. No Add path to the library.

## D199 — P7-F2 and P7-F3: PubMed subrequests are counted and bounded, sends are counted apart from reservations, and the authenticated OpenAI embedding route is tested
Status: accepted (implemented) · Date: 2026-10-03
`common.send` writes one transport entry per call into a context-local collector that `facade.dispatch_search` returns as `Dispatched.transport`; the workflow counts only from it. Discovery reserves `requests_per_search × (1 + allowed 429 retries)` before sending and settles to observed attempts in one transaction (`Store.settle_usage`), adding a `provider_sends` counter. PubMed's per-page share is `2 × (1 + wait) + transient retries`; the authenticated OpenAI embedding route is tested.
Limits: Mocked transports and synthetic keys only. A stop during transient backoff loses that operation's trace; lookup and chain accounting stay as they were until D201. `provider_sends` has no UI label.

## D185 — P8 B8a: a candidate version with its finished kill-search can be reviewed by another model; the review reads a stored copy and is marked stale when the candidate, its search or its owner status changes
Status: accepted (implemented) · Date: 2026-10-03
A candidate review targets a candidate version that is current, outside the Trash and has a finished (completed, failed or stopped) latest kill-search; a newer paused or running search blocks the review. The review reads a stored snapshot copy of the statement, elements, search outcome, status, latest owner override and assessed-source matrix (validation plan excluded), with passages copied from each assessment's StepInput. New stale codes: `newer_candidate_version`, `newer_kill_search`, `kill_search_changed`, `owner_status_changed`.
Limits: No real model read a candidate input (that is B8b); tests use synthetic records and a scripted model.

## D196 — P7 G1 B5: G1 is accepted with conditions for the internal search connector contract; P7 exit is not met until three named batches land
Status: accepted with conditions (G1 accepted, P7 open) · Date: 2026-10-03
G1 is accepted for the internal, versioned search connector interface (`deixis.scholarly_connector.v1`) and its mocked conformance scope; lookup and citation chaining stay unbound. P7 exit is not met until three batches land: G1-F1 (bind lookup and OpenAlex chaining), P7-F2 (count actual sends and every PubMed subrequest and retry) and P7-F3 (test authenticated OpenAI embedding). P7 closes on deterministic matrices; live error and quota formats are recorded as unmeasured limits.
Limits: Mocked transports and SYNTHETIC records show application behavior, not provider truth, recall or availability.

## D195 — P9 re-extraction R2c: a recovery operation left running by an ended process is reconciled by whoever holds its file lock, never re-run; equation and arXiv readers take that lock; crash, limit and full-disk boundaries are tested
Status: accepted (implemented) · Date: 2026-10-03
`workflow/reconcile.py` treats exclusive ownership of the hash lock as liveness: whoever holds the lock reconciles an operation left running by an ended process (stale text retry becomes `interrupted/process_ended`), never re-runs it. It runs after worker recovery at startup, before each worker turn picks a run, and after a retry takes its lock; equation and arXiv readers take the same lock. Crash, limit and full-disk boundaries are tested.
Limits: Synthetic PDFs only; macOS process kills do not show power-loss recovery, and advisory locks cannot stop outside processes.

## D194 — P7 G1 B4: equivalent facade search dispatch, four named storage/admission changes, and recorded-page continuation refusal
Status: accepted (B4 implemented) · Date: 2026-10-03
Discovery and kill-search dispatch through `facade.dispatch_search` with the registry entry, the caller's snapshotted key and the unchanged `CompatibilityConnector.search`; a frozen `Dispatched` carries outcome, admission count and connector provenance. Four named storage/admission changes and refusal of continuation on a recorded page are separate from the equivalence claim.
Limits: Synthetic fixtures only; `RetryPolicy` stays descriptive and some ledger items remain unscheduled.

## D171 — P9 H9 phase 1: the owner slots K01 to K12 are closed on the owner's behalf, the H8 dependency gets a stated exception, and the pre-discovery rules of the fresh-corpus report measurement are frozen
Status: accepted (freeze point 1 of 2; no model run) · Date: 2026-10-03
Owner slots K01 to K12 are closed on the owner's behalf by Claude Opus 5.5 with gpt-6.1-sol medium: topic Q1 (EV charging scheduling optimization), at most 10 and at least 6 text-bearing works, at most 2 attempts within 300 sessions / 240 min, `codex` / `gpt-5.6-luna`, product commit `87cee0b`. H9 proceeds under a stated exception to its H8 dependency (H9 run and the matrix pair never overlap), and the pre-discovery rules of the fresh-corpus report measurement are frozen.
Limits: Nothing was run, so enough text-bearing sources, a signed-in Codex home and Luna quota are unverified.

## D184 — P8 B4: the owner review was run on a real model against frozen synthetic cases; nine of nine planted errors were found and no finding landed on an unplanted claim, in one run of one model
Status: accepted, measured once · Date: 2026-10-03
The owner review ran on a real model (Claude Code `sonnet`, resolved `claude-sonnet-5-5`, effort medium; targets written by Opus 5.5) over eight frozen synthetic cases through `scripts/model_behavior/run_review_cases.py`. It found 9 of 9 planted errors and 0 of 15 findings landed on an unplanted claim.
Limits: One run per case, one model, one effort, one focus (`source_support`); counts on short synthetic targets, not rates, and the judge is the case author.

## D192 — P9 re-extraction R2b: every PDF writer repairs a damaged stored file through one restore_file, under the file lock, after keeping the damaged bytes and with a receipt; the stored text stays until a person retries it
Status: accepted (implemented) · Date: 2026-10-03
Every PDF writer repairs a damaged stored file through `workflow/file_restore.py::restore_file`, under the shared hash lock (retry every 0.05 s up to `WRITER_LOCK_WAIT_SECONDS = 10.0`, else `FileBusy`), after keeping the damaged bytes and writing a receipt. The stored text stays until a person retries it.
Limits: No real library was repaired; retained bytes are not backed up until R3 and receipts survive source-extraction purge.

## D193 — P7 G1 B3b: registry query declarations preserve compiler output and allocation, with bounded undeclared-input refusals
Status: accepted (B3b implemented) · Date: 2026-10-03
Frozen `query_rules.QuerySyntax` declarations per registered connector supply candidate rendering and issues, and `query_compiler.fit_block_counts` owns the single allocation loop the facade shares. Compiler output stays byte-equal to the characterized behavior, with bounded refusals for undeclared inputs.
Limits: Byte equality is shown on an enumerated synthetic corpus only; search dispatch was not yet moved to facades.

## D183 — P8 B3: review screens: a review is requested, read and decided inside the target's own sheet, and a finding reaches report text only through the editor's checked apply save
Status: accepted (implemented) · Date: 2026-10-03
A review is a mode of the answer or evidence report's own sheet, keeping reading position; the request names target version, focus, listed model, effort and optional owner note, with a Preview of claims, passages, characters and send bounds. A finding reaches report text only through the editor's checked apply save.
Limits: No real model ran a review (that is B4); browser cases use SYNTHETIC records and a scripted model.

## D170 — P9 RR-B: the PDF extraction child gets a GIL-independent orphan guard, the matrix reads execution results, and the report-edit and capacity checks stop passing by accident
Status: accepted (implemented) · Date: 2026-10-03
`documents/child_guard.py` adds a GIL-independent guard process that SIGKILLs an orphaned extraction child past its memory limit. The matrix now reads execution results (skipped or empty is not a pass) with a mandatory `F04-orphan` row, and `report-edit.spec.ts` and the capacity checks stopped passing by accident.
Limits: P9 matrix exit not met in a clean pair on an idle machine; OCR and JATS keep only their in-child thread, and Windows is unsupported.

## D179 — P7 G1 B3a: the facade refuses invalid request values before send, with measured dispatcher and full-matrix equivalence
Status: accepted (B3a implemented) · Date: 2026-10-03
`CompatibilityConnector.search` now refuses invalid options before send: types must match the descriptor's exact `bool`/`str` and enumerated values, and a retry allowance must be an exact nonnegative `int`, raising `ContractViolation`. Dispatcher and a full 566-case matrix replay show identical requests and outcomes through direct and facade paths.
Limits: Synthetic fixtures only; dispatch still used registry callables.

## D191 — P9 re-extraction R2a: a person can retry a failed or partial extraction once per request, through the extraction endpoint or the CLI, on a hash-checked private copy under a per-file lock; runs wait for a live retry
Status: accepted (implemented) · Date: 2026-10-03
A person can retry a failed or partial extraction once per request through the extraction POST (`TextRetryRequest`, mode `retry_failed_or_partial`, expected current extraction id, idempotency key) or the CLI, both via `workflow/text_retry.py::execute_text_retry`, on a hash-checked private copy under a per-file lock; runs wait for a live retry.
Limits: Synthetic PDFs and isolated libraries only; page coverage does not establish word preservation or scientific support.

## D178 — P7 G1 B2: a registry-driven conformance suite exists, a key removed after the protocol froze no longer counts a request or breaks the search table, and four provider defects are fixed
Status: accepted (B2 implemented) · Date: 2026-10-03
A registry-driven conformance suite exists. A key-required connector without a key now returns `not_configured/before_send` before quota suppression, usage counting or kill-search reservation, and a key removed after the protocol froze no longer counts a request or breaks the search table. Four provider defects are fixed.
Limits: Synthetic fixtures only; facades are not yet dispatched and B4 owns four named changes.

## D190 — P9 re-extraction R1: a stored extraction has its own identity, a recovery attempt can be stored beside the old one, and one tested rule decides which is current; nothing starts a recovery yet
Status: accepted (implemented) · Date: 2026-10-03
A stored extraction gets its own identity: `extraction_version` is one immutable occurrence, `extractor_profile` its tools, and a text retry stores `<profile>+reextract-<operation_id>`. Migration `0066_asset_recovery.sql` lets a recovery attempt sit beside the old one, and one tested rule picks the current head.
Limits: R1 starts no recovery (no route, CLI, UI, lock or receipt); no real PDF was recovered.

## D177 — P7 G1 B1: freeze the internal scholarly connector boundary and current adapter behavior
Status: accepted (B1 implemented) · Date: 2026-10-03
`providers/contract.py` defines `deixis.scholarly_connector.v1` and `providers/facade.py` wraps adapters with call-time descriptors and pre-send refusals. A 111-case SYNTHETIC native-response freeze under `tests/fixtures/connectors/` pins current behavior of all eleven provider/endpoint pairs.
Limits: The facade is unused by dispatch; the baseline freezes current code, not provider truth.

## D182 — P8 B2: a review can be previewed, started, run in groups, read and decided; findings reach report text only through the checked editor save
Status: accepted (implemented) · Date: 2026-10-03
A review can be previewed, started, run in groups, read and decided. Planning lives in `workflow/review/run.py`; limits are `REVIEW_GROUP_CHAR_LIMIT = 96_000`, `REVIEW_REQUEST_CHAR_LIMIT = 120_000` and `REVIEW_MAX_PASSAGES = 48` per group. Findings reach report text only through the checked editor save.
Limits: No real model ran a review (B4); synthetic records and scripted adapters only.

## D173 — P7 gap batch: quota resends stop within a run, Gemini identity stays exact, local embedding errors are typed
Status: accepted (implemented) · Date: 2026-10-03
Model outcomes keep their status names but an in-memory `error_kind` separates `quota_exhausted` from `rate_limited`; DeepSeek 402 and exhausted-credit signals are not resent within a run. Gemini identity stays exact, and local embedding errors are typed.
Limits: Error fixtures are synthetic and show classification policy, not live error formats.

## D181 — P8 B1: the review contract, method file, snapshot, tables and stale rule exist; no review can be started yet
Status: accepted (implemented) · Date: 2026-10-03
The review contract `deixis.owner_review.v1` (task `owner_review`), its method file, snapshot, tables and stale rule exist; no review can be started yet. Quotes must be at least 12 characters and locate `exact` or `normalized` (fuzzy is `review_anchor_not_exact`); suggested fixes stay text and are never applied.
Limits: The contract has not met a real model (B4); a located anchor shows the quote occurs, not that the finding is right.

## D175 — Translate report export refusals and restore slice 31 test coverage
Status: accepted (implemented) · Date: 2026-10-03
Ordinary requests and report exports share `api.ts::responseError`, so Turkish refusals for Markdown and LaTeX exports are translated; `e2e/export-errors.spec.ts` and `test_legacy_removal.py` restore slice 31 test coverage (lexical ranking, scripted OCR, table fill, report generation).
Limits: Deterministic client and synthetic workflow checks only; the visible toast after a 507 export refusal is not tested.

## D176 — P9 H7 finding 2: a repaired file gets an evidence-preserving recovery path; old extractions and their passages stay, a recovered extraction is a new, visible head
Status: accepted (design only) · Date: 2026-10-03
A repaired file gets an evidence-preserving recovery path: every replacement of a not-whole file goes through one `restore_file(op)` that writes a receipt, keeps the damaged bytes and takes the lock. Old extractions and passages stay, a recovered extraction is a new visible head, and `UNIQUE(asset_id, extraction_version)` stays.
Limits: Design only, nothing tested; a legacy `partial` row whose page count changed is not recoverable.

## D174 — P7 G1: the connector contract is an internal, versioned interface for reviewed adapters with a registry-driven conformance suite; external plugins are not offered
Status: accepted (design only) · Date: 2026-10-03
The connector contract is internal and versioned: sources are added as reviewed adapters in the codebase, with no external plugins, backed by a registry-driven conformance suite. Six batches: B1 boundary, B2 conformance suite, B3a facades, B3b query delegation, B4 facade dispatch, B5 acceptance.
Limits: Design only; G1 closes only on its section 13 conditions and P7 stays open.

## D169 — P9 Sol re-review fixes A: B02 can no longer reach the live folder through a link, a staged restore is checked against its manifest hash, and five disk-full or startup paths end in a sentence instead of a traceback or a 400
Status: accepted (implemented) · Date: 2026-10-03
`scripts/p9/upgrade_check.py::check_work_tree` refuses symlinks, files sharing an inode with the live folder, multi-link files and escaping folders, so B02 cannot reach the live folder. A staged restore is checked against its manifest hash, and five disk-full or startup paths end in a sentence instead of a traceback or a 400.
Limits: Links swapped between check and use are not covered; results are on SYNTHETIC folders, not real data.

## D180 — P8 design: review by another model is a separate, immutable-snapshot record the user starts, and follow-up is a manual or opt-in bounded check that runs only while DEIXIS is running
Status: accepted (design only) · Date: 2026-10-03
Review by another model is a new `owner_review` task and `review` run kind with its own tables (`owner_review_snapshots`, `owner_reviews`, `owner_review_findings`, `owner_review_decisions`), working on an immutable stored snapshot the user starts. A finding reaches main text only through the existing editor save; follow-up is a manual or opt-in bounded check that runs only while DEIXIS is running.
Limits: No real model has read a snapshot, so finding, invention and miss rates are unknown until B4.

## D172 — P7: model adapters check the answering model, DeepSeek's empty balance counts as quota, and key-required providers send nothing without a key
Status: accepted (implemented) · Date: 2026-10-03
Model adapters check the answering model (Claude resolves the selector via `get_server_info` and sets `requested_model_verified` only on a match, a mismatch fails as `model_mismatch`), DeepSeek's empty balance counts as quota, and key-required providers send nothing without a key.
Limits: No live DeepSeek, IEEE, Scopus, CORE or SerpApi call was made; the Claude check trusts the CLI's own catalogue.

## D168 — P9 model-free hardening closes: one command runs every automatic matrix row, it passed in two of three complete runs, one browser spec failed once, and what was not measured is written down
Status: accepted (implemented) · Date: 2026-10-03
`scripts/p9/run_matrix.sh` and `run_matrix.py` run eight stages and print 61 rows; a row is `geçti` only when its evidence ran and passed, else `ölçülmedi`. It passed in two of three complete runs and one browser spec failed once.
Limits: The runs are not independent samples (same machine and day, runner changed between attempts); a pass shows workflow behavior only.

## D167 — P9 H6: an axe scan, a keyboard walk, a reduced-motion check and a 200% layout check now run on the interface; the scan found 80 serious or critical hits on the baseline, all fixed, the walk found two real failures and nine actions that dropped focus to the page body, all fixed
Status: accepted (implemented) · Date: 2026-10-02
`apps/web/e2e/a11y.spec.ts` (28 tests, ports 8820 to 8824) runs an axe scan (`@axe-core/playwright` 4.13.0, devDependency only) over 26 screens in light/dark and desktop/phone, a keyboard walk, a reduced-motion check and a 200% layout check. The scan found 80 serious or critical hits on the baseline, all fixed; the walk found two real failures and nine actions that dropped focus to the page body, all fixed.
Limits: Automated and Chrome only; axe cannot judge label wording, reading order or cognitive accessibility.

## D166 — P9 H5: capacity and performance are measured model-free against thresholds frozen before the first measurement

Status: accepted · Date: 2026-10-02
Capacity was measured against the real server and system Chrome on a synthetic library (100 to 10,000 works in one research, 3 repetitions per point), with thresholds frozen before the first measurement (`capacity.FROZEN`, `scripts/p9/capacity.py`, `capacity_browser.mjs`). The first run broke three mandatory rows (K01b, K02a, K02b) because four view lookups had no index; migration `0063_view_lookup_indexes.sql` (indexes only) fixed them, and at 10,000 works the screen is ready in about 1 s and the view API answers in 0.84 s.
Limits: Synthetic shape only: no answers, reports or model steps; measured under parallel load on one machine; Sources list is not virtualized (5.9 s to first paint at 10,000).

## D165 — P9 H7: six daily-use defects are closed, none of them reported from real daily use; a torn file under a hash name, a full disk hidden by a savepoint or a Zotero write, and a model stop that said too little now end in a whole file or one sentence

Status: accepted · Date: 2026-10-02
H7 closed six defects found by reading the code, not from daily use (the daily-use log does not exist): `pdf_files.file_is_whole` replaces a torn `papers/<sha>.pdf`, `db.rollback_savepoint` stops hiding a full disk, two Zotero routes and the import map ENOSPC to the 507 `disk_full` answer, the run line of a model stop says what to do and shows the connection's own words, and duplicate tests in `tests/test_api_flow.py` were removed with a guard against repeats.
Limits: Not a daily-use list; an asset row stored from a torn download keeps its `failed` status; password-protected PDFs from before D164 still read "no text layer".

## D164 — P9 H3: every fault class in F05 to F08 now has a named test or a stated reason; a full disk, a busy or damaged library and three kinds of unreadable PDF each end in one sentence and a code instead of a bare 500 or a traceback

Status: accepted · Date: 2026-10-02
Every fault class F05 to F08 now has a named test or stated reason. `storage/db.py::describe_failure` classifies SQLite codes and ENOSPC into `disk_full` 507, `database_busy` 503, `database_readonly` 503 and `database_damaged` 503, API handlers answer `{detail, code}`, the worker logs and retries instead of dying and stores `pause_reason = disk_full`, `serve` prints one sentence for an unusable library, and `documents/pdf.py` reports password-protected, no pages or unreadable PDFs as three distinct reasons.
Limits: One machine and one HFS+ image; ENOSPC on write paths no test hit stays a 500 because a global `OSError` handler was avoided.

## D163 — P9 H4: a backup restored into an empty folder matches the source in every table and file; a library written by a newer DEIXIS is refused before anything is written, a cut restore no longer leaves a half file, and a backup of a library the current code has not migrated yet no longer fails

Status: accepted · Date: 2026-10-02
`db.check_schema_known` refuses a library holding migration ids this build does not know, before anything is written, with one sentence (`backup` is deliberately unguarded). `restore_backup` places files atomically with a pre-pass and removes its own `.restoring-*.part` leftovers, no automatic backup before migration was added, and `scripts/p9/upgrade_check.py` backs up and restores a copy of the owner's library (counts only, with consent).
Limits: Single runs on one machine; shows tables, files and views reproduce here, not that a backup moves to another machine.

## D162 — P9 H2: real processes were killed and signalled; a held model call, a Ctrl-C during an extraction and an orphaned extraction child did not end in time and now do, and a torn download file under its final name is no longer possible

Status: accepted · Date: 2026-10-02
Real kill and signal tests found three hangs. `__main__.watch_shutdown` force-exits 6 s (`SHUTDOWN_EXIT_SECONDS`) after SIGINT/SIGTERM, so a model call in flight is resent on resume as after a crash. `pdf._watch_memory` children arm `signal.alarm` of 100 s (`DEIXIS_CHILD_LIFETIME_SECONDS`) so an orphan dies, and `store_pdf_file` writes a `.part` file and `os.replace`s it, so a torn download can no longer sit under its final name.
Limits: One shape per scenario on a loaded machine; SIGKILL is not power loss and `store_pdf_file` does not `fsync`; real `codex` not tested (H10).

## D161 — P9 H1: a clean export of the commit installs, builds, starts, serves the UI and stops with the README's own steps; an unwritable data directory now ends with one clear message instead of a traceback

Status: accepted · Date: 2026-10-02
`scripts/p9/install_check.py`, `shell_check.mjs` and `run_matrix.sh` export a commit with `git archive` and run the README steps (uv sync, npm ci, build, serve, UI check, stop) in an isolated environment. One product change: `__main__.data_dir_problem` makes an unwritable data directory print one clear message and exit 2 instead of a traceback; the README gained matching install notes.
Limits: One machine and macOS version; the UI check shows the question box renders, not that a research runs.

## D160 — P6 slice 5 X5: the report screen has a "Download LaTeX" button that saves the zip and reports the export note count in one toast; slice 5 is implemented, with no real-model measurement

Status: accepted · Date: 2026-10-02
The report screen has a third toolbar button "Download LaTeX" (`api.reportLatex`, `ReportView.tsx`) that saves the zip and shows one toast: success with zero export notes, a warning with the count (first 20 listed) otherwise. 404, 409 and 422 raise `ApiError` before any download; strings are bilingual. Slice 5 is implemented.
Limits: No real-model measurement; compile test measured on TeX Live 2021 only; Sol review pending after the Codex limit.

## D159 — P9 H0c: the 1 GiB memory limit on the arXiv source child did not work and now does; the OCR and JATS render children are stopped by their own in-child watchdog and are left as they are

Status: accepted · Date: 2026-10-02
Production-limit probes showed the OCR and JATS children are stopped, late (about 2.4 and 1.5 times 1 GiB), and left unchanged, while the arXiv source child was not stopped at all. `arxiv_source.run_child` now takes `max_memory` and a parent-side watcher kills it over 1 GiB (`memory_limit`) or when the watch is lost (`memory_watch_lost`); measured kernel peak 1024 MiB.
Limits: One input shape per child; OCR and JATS overshoot the limit and a parent watcher was not measured on them.

## D158 — P6 slice 5 X4: `format=latex` returns a zip of the `.tex` and the `.bib` read in one snapshot, with the note count in a header, and an optional compile test measures the committed goldens and wide tables when TeX is installed

Status: accepted · Date: 2026-10-02
`workflow/report/latex_export.py` (`export_latex`, `build_zip`, `read_bib_sources`) serves `format=latex` as a zip of `<stem>.tex` and `<stem>.bib`, built after one `queue._snapshot` read, deterministic bytes (fixed 1980-01-01 timestamp), note count in the `X-Deixis-Export-Notes` header. An optional compile test measures the committed goldens and wide tables when TeX is installed.
Limits: Synthetic reports and one TeX distribution (TeX Live 2021); without TeX the compile tests skip.

## D157 — P6 slice 4 E4: a scripted sequence runs edit, citation removal, cell change, source removal, check, restore, backup and purge in one order on synthetic rows; slice 4 is closed as implemented, the real-report measurement moves to P9

Status: accepted · Date: 2026-10-02
`tests/test_report_edit_sequence.py` runs one deterministic 15-step sequence (edit, citation removal, cell change, source removal, edit check, restore, backup, trash and purge) on synthetic rows with no model or network. Slice 4 is closed as implemented and the real-report measurement moves to P9.
Limits: Synthetic rows and a fake model: nothing about how often the edit check is right on real reports.

## D156 — P6 slice 4 E3: the report screen shows the edit check and citation removal as stored, and says "not checked" where the code did not check

Status: accepted · Date: 2026-10-02
The report screen renders the stored edit check (current, out of date, none) with a "Check edited text" button, the rules that ran and did not run, and a "Not checked" line. The edit form takes per-link citation choices by `link_id`, history offers Restore only when it changes something, and a claim with all citations removed reads "(no direct citation)".
Limits: Scripted model and synthetic data; "Current" means inputs match, not that text is correct; only four rule codes have plain labels.

## D155 — P6 slice 5 X3: `to_latex` assembles the IEEEtran report (`.tex` and `.bib`) from one recorded read model, `to_bibtex` gains `keys` and `latex_report`, and 188 golden pairs pin the output; no route calls it yet

Status: accepted · Date: 2026-10-02
`workflow/report/latex.py::to_latex(view, *, title, corpus, bib_sources)` builds the IEEEtran report (`LatexBundle` with `tex`, `bib`, `notes`) from one recorded view, with the fixed preamble, Turkish renewcommands, `MAX_DATA_COLUMNS = 7` and long-value thresholds 400/400/200, and 188 golden pairs pin the output. `to_bibtex` gained `keys` and `latex_report`; no route calls it yet.
Limits: Synthetic views only; compile shown on one TeX distribution; long D59 keys and wide words still overflow columns.

## D154 — P6 slice 3 K5: the candidate tasks were run once on seven synthetic cases and once end to end on a development claim with a real model; slice 3 is closed as implemented, the independent measurement (K6) moves to P9

Status: accepted · Date: 2026-10-02
`scripts/model_behavior/run_candidate_cases.py` ran cases CB01 to CB07 once through the production message path (one attempt, no repair, no fallback) and one end-to-end trial on a development claim with a real model. Slice 3 is closed as implemented (K1 to K5) and the independent measurement K6 moves to P9.
Limits: One attempt per case, easy synthetic cases; the trial shows the path runs, not that the search finds prior art.

## D153 — P6 slice 5 X1: the Markdown export is pinned byte for byte, then the shared bilingual report text moves to `export_text.py` with no output change

Status: accepted · Date: 2026-10-02
The Markdown export is pinned byte for byte by `tests/test_report_export_pin.py` (120 tests with literal outputs captured from the unmodified `export.py`), then the shared bilingual report text moved to `workflow/report/export_text.py` with no output change.
Limits: Identity is shown for the pinned and randomized views only; existing quirks ("1 sources") are pinned as they are.

## D152 — P6 slice 3 K4: the Candidates tab shows claim candidates, their versions, the kill-search run, the stored matrix and the evidence, and says "no match in the assessed subset", not novelty

Status: accepted · Date: 2026-10-02
A Candidates tab (`apps/web/src/candidate/*`) shows claim candidates, versions with human edit, kill-search plan preview, run controls, the stored matrix, an evidence sheet and the five derived statuses, and says "no match in the assessed subset", not novelty. Two narrow backend changes: read-only `GET .../reports/{report_id}/gaps` and a K3 fix refusing a start while a paused candidate run exists.
Limits: Scripted model and mocked providers only; screenshots at 1440 and 390 px, no screen reader check.

## D151 — P6 slice 5 X2: the pure LaTeX text and math conversion (escape, symbol table, closed math scan, fixed preamble, TeX-derived names file) is in place; nothing calls it yet

Status: accepted · Date: 2026-10-02
Pure LaTeX conversion lives in `workflow/report/` (`latex_preamble.py`, `latex_text.py`, `latex_math.py`, `latex_names.json`, `scripts/latex_export_names.py`): escape of the ten TeX specials, an 84-symbol table, a closed math scanner and the fixed IEEEtran XeLaTeX preamble. Nothing calls it yet.
Limits: Synthetic strings only; the scan is not a TeX sandbox and does not check argument counts.

## D150 — P6 slice 4 E2: a claim can lose citations reversibly, and every reader takes one recorded effective citation set

Status: accepted · Date: 2026-10-02
Migration `0062_report_claim_links.sql` adds `link_count`, `request_hash` and the append-only `report_claim_revision_links`, so a claim can lose citations reversibly. `ReportStore.edit_claim` takes `link_ids`, restore brings back text and citations together, and every reader uses `ReportStore.effective_links`.
Limits: Removing a citation says nothing about whether the remaining ones support the sentence.

## D149 — P6 slice 5 (IEEEtran LaTeX export of the report): accepted for implementation as five build batches with golden-file tests as the evidence; no migration, no model call, no measurement

Status: accepted (design) · Date: 2026-10-02
Slice 5 accepted as five build batches with golden-file tests: pure `to_latex` beside `to_markdown`, a zip of `.tex` and `.bib` through `format=latex`, XeLaTeX with `IEEEtran[journal]` and BibTeX, no `hyperref`, citation keys from `works.source_key` (D59), and stored math passing a closed scanner. No migration, model call or measurement.
Limits: A design, not a verified implementation; TeX measurements come from one distribution.

## D148 — P6 slice 4 E1: edited report text can be checked by code, with an append-only result whose currency follows its inputs

Status: accepted · Date: 2026-10-02
Migration `0061_report_edit_checks.sql` adds `report_edit_checks` (unique per report and input fingerprint, append-only). `assembly.run_current_checks` and `workflow/report/edit_check.py` (version `edit-check-1`) re-run code rules on edited text and mark the result current or historical by a fingerprint of every input read.
Limits: Structural and lexical checks only: no semantic support validation and no real-corpus hit rate.

## D147 — P6 slice 4 (edit check and citation removal, narrow version): accepted for implementation as four batches without any model call; publish, section rewrite, stable identity and the closing measurement are deferred

Status: accepted (design) · Date: 2026-10-02
Slice 4 accepted as four model-free batches: a read-only "check edits" action stored in an append-only record and shown as current or historical, and citation removal from an edited claim with each revision recording its effective citation set. Publish, section rewrite, stable identity and the closing measurement are deferred.
Limits: A design, not a verified implementation; coverage of real edits is unmeasured.

## D146 — P6 slice 3 K3: the flow and the API for claim candidates and the claim-specific kill-search run end to end with a fake model and mocked providers; no screen shows them yet

Status: accepted · Date: 2026-10-02
`workflow/candidates/run.py` and `ResearchFlow` dispatch `claim_decomposition` and `kill_search` end to end: one model step publishes a `model_decomposition` version, and kill-search asks for two term blocks, freezes the search, sends at most six provider queries of 20 records, cuts to eight works and assesses them one by one. API routes exist, no screen yet.
Limits: Fake adapter and mocked providers: nothing shows the terms find prior work or that eight works are enough.

## D145 — P6 slice 3 K2: the contracts, citation handles, validators and method file for the three candidate tasks are in place; nothing calls them yet

Status: accepted · Date: 2026-10-01
Three strict v1 output schemas (`claim-decomposition`, `kill-search-query`, `claim-assessment`), the `candidate_target` step-input shape, citation handles, validators (`_check_candidate_target`, `_check_claim_decomposition`, `_check_claim_assessment`) and the method file are in place; nothing builds a `candidate_target` yet.
Limits: Fake adapter only; validators check structure and quote location, not whether a quote supports the relation.

## D144 — P6 slice 3 K1: claim candidates, kill-search records and the status derivation have durable storage and pure code; nothing calls them from the flow yet

Status: accepted · Date: 2026-10-01
Migration `0060_candidates.sql` rebuilds `runs` with two new kinds and adds ten `WITHOUT ROWID` tables (`research_candidates`, `candidate_versions`, `claim_elements`, `kill_searches` and others), with append-only rules and trigger-enforced integrity. `workflow/candidates/status.py` derives the five statuses from stored rows; the flow does not use it yet.
Limits: Synthetic storage only; `upsert_provider_source` is the shared write path and may fill metadata of a source another research holds.

## D143 — P6 slice 3 (claim-specific kill-search and candidate card): accepted for implementation as four build batches, one development-behavior batch and one measurement batch; chain-end entry, report write-back, PDF reading and export are deferred

Status: accepted (design) · Date: 2026-10-01
Slice 3 accepted as four build batches, one behavior batch and one measurement batch: a versioned one-claim candidate opened from a `report_gaps` snapshot or the owner's sentence, kill-search that never touches the corpus (own hit table, `upsert_provider_source` only), three model tasks and two run kinds, queries as two term blocks via `compile_block_queries`.
Limits: A design; `open` is not evidence that nothing exists, and recall is unmeasured.

## D142 — P6 slice 2 closed as implemented, usefulness of link production on a real corpus not shown; two medium findings of the cross-batch review fixed (restore cannot re-activate a cycle, whitespace `what_changed` goes to repair)

Status: accepted · Date: 2026-10-01
Slice 2 is closed as implemented. Fix 1: `TableStore.restore_column` refuses a restore that would re-activate a link on a directed cycle. Fix 2: `domain/lineage.py::valid_what_changed` (non-whitespace, 1 to 500 characters) is used by L3 repair and L4, so whitespace `what_changed` goes to repair.
Limits: Usefulness of link production on a real corpus is not shown; only synthetic data, a fake model, eight synthetic real-model cases and one 7-work trial.

## D141 — P6 slice 2 L9: the fresh-corpus development-lines measurement stopped at the corpus gates after one preparation attempt; no lineage run was made and R12 to R15 are not measured

Status: accepted · Date: 2026-10-01
The L9 fresh-corpus development-lines measurement stopped at the corpus gates: the default flow included 1 of 99 works, so K1 to K3 failed and no lineage run was made. R12 to R15 are not measured.
Limits: One question, one run, one model; says nothing about the lineage task on an author-year corpus, and the corpus is burned.

## D140 — P6 slice 2 L8: the lineage task was run once on eight synthetic cases and once on a development corpus with a real model; every output was valid, nothing in either run shows that development lines are useful

Status: accepted · Date: 2026-10-01
`scripts/model_behavior/run_lineage_cases.py` ran the lineage task once on eight synthetic cases and once on a development corpus through the production message path (one attempt, no repair, no fallback). Every output was valid; nothing shows development lines are useful.
Limits: One attempt per case and one corpus; the cases are easy by construction.

## D139 — P9 H0a: baseline on a clean copy of `8091d62`, the supported environment written into the repository, a harness gap found, and the feature inventory

Status: accepted · Date: 2026-10-01
P9 H0a baseline on a clean export of `8091d62` with an environment allow-list: pytest 3,772 passed with 1 known failure, build and lint ok, Playwright 112 passed. The supported environment went into the repo (`engines` node >=22.12.0 <23, `.node-version` 22.23.2), `fixture_server.py` now installs an in-memory keyring, and a feature inventory was written.
Limits: One machine on macOS 27.0.1; timings are skewed by foreign load; the Node pin is declared, not enforced; a flaky L6 test was left untouched.

## D138 — P9 H0b: the 1 GiB memory limit on PDF text extraction did not work and now does; the watcher moved from the extraction child to its parent

Status: accepted · Date: 2026-10-01
The 1 GiB limit on PDF text extraction never worked because the in-child thread cannot run while PyMuPDF holds the interpreter lock. The watcher moved to the parent (`ctypes` on macOS, `/proc/<pid>/statm` on Linux), which SIGKILLs the child over the limit (code 3, `extraction exceeded the memory limit`) and fails visible after 20 unreadable turns; measured stop within about 1 MiB of 1 GiB.
Limits: Only `extract_pdf` was fixed; Windows has no memory limit; one input shape.

## D137 — P6 slice 2 L7: the Development lines screen shows the stored read model, starts the link-finding run with its call ceiling, and lets a human remove, edit and add links
Status: accepted (uncommitted) · Date: 2026-10-01
The Evidence tab gets a "Table | Development lines" switch (`apps/web/src/lineage/`) that renders the whole `GET .../lineage` read model with no list hidden and "None." for empty ones. "Find development links" shows the plan (works, calls, ceiling) and starts a run only from that plan's fingerprint; human remove, edit and add use the pair `version` from `pair_decisions` and show the server's 409/422 message.
Limits: Synthetic data and a scripted model only; nothing shows that real corpora give useful lines. A stored quote is located text, not proof of support. No report integration, no graph.

## D136 — P6 slice 2 L6: development lines are assembled and read from stored decisions, and a human can add, edit and remove links through the API; no screen exists yet
Status: accepted (uncommitted) · Date: 2026-10-01
`workflow/lineage/assembly.py` (pure) builds weakly connected components of links (roots, branches, merges, `has_cycle`) and maps each unplaced work to a closed reason list (`not_run`, `no_pdf_text`, `no_candidate`, `no_relation`, `insufficient_evidence`, `rejected`, `not_sent_budget`, `step_failed`, `human_removed`, `cross_relation_only`, `stale_only`). `workflow/lineage/view.py` reads stored decisions in one read-only transaction; the API lets a human add, edit and remove links with a CAS `version`. A changed head work only sets the display flag `not_head_ends`, it does not make a link stale.
Limits: Fake adapter only, no measurement; currency checks compare recorded inputs, so text changes under an unchanged passage id are unchecked.

## D135 — P6 slice 2 L5: the flow that scans, plans, asks and publishes development links runs end to end with a fake model; no route shows its results yet
Status: accepted (uncommitted) · Date: 2026-10-01
`workflow/lineage/run.py` snapshots the table's live rows and runs the scan, plan, ask and publish flow: at most 25 eligible targets (a live row with a current `pdf_page`), at most 8 candidates, 24 passages and 48,000 characters per call, three calls per target. Targets are classified by fingerprint (`new`, `changed`, `retry`, `settled`) and settled pairs are skipped.
Limits: Fake adapter only; whether the 25-work and 8-candidate bounds fit real papers, and the call count and time, are unmeasured. No route shows results yet.

## D134 — P6 slice 2 L4: development-link decisions, their evidence and the human edits have durable, append-only storage; nothing calls it from the flow yet
Status: accepted (uncommitted) · Date: 2026-10-01
Migration `0059_lineage_links.sql` adds `lineage_links`, `lineage_link_revisions` and `lineage_link_evidence` (`WITHOUT ROWID`, append-only, eleven triggers; evidence only from the later work) and adds `lineage_links` to the run kind CHECK. `workflow/lineage/store.py` (`LineageStore`) records proposals in a fixed rule order (same work, live endpoints, human precedence, stale input, located quotes, directed cycle); a rejected proposal changes nothing else.
Limits: Synthetic storage only; node-input staleness is not detected here and nothing in the flow calls the store yet.

## D133 — P6 slice 2 L3: the `lineage_links` contract, validator, per-field citation handles and method file are in place; nothing calls them yet
Status: accepted (uncommitted) · Date: 2026-10-01
New strict output schema `contracts/research/lineage-links-draft.schema.json` (`deixis.lineage_links_draft.v1`); `lineage_links` joins the `task_type` enum and the StepInput gains an optional `lineage_target`. `check_step_input` gets `_check_lineage_target` (same work never pairs, `to` and every `from` are shown and allowed), with per-field citation handles and a method file.
Limits: Nothing calls this path yet; no real model checked, so handle effect on copy errors is unknown. The validator checks structure, not that a quote supports the relation.

## D132 — P6 slice 2 L2: model-free mention candidates, citation-edge states and the field baseline are pure functions
Status: accepted (uncommitted) · Date: 2026-10-01
Pure functions in `workflow/lineage/{mentions,edges,candidates,baseline}.py`: model-free mention candidates (first author surname within 60 normalized characters of a four-digit year, or runs of matching title 5-grams), citation-edge states and the field baseline. No database, provider or model access.
Limits: Mention recall on real passages is unmeasured; numbered citations are missed and shared surnames give false candidates.

## D131 — P6 slice 2 L1: node columns carry a stable lineage role added only by an explicit action
Status: accepted (uncommitted) · Date: 2026-10-01
Migration `0058_lineage_role.sql` adds nullable `table_columns.lineage_role` (`problem`, `change`, `uncertainty`, at most one active column per role per table). `TableStore.add_development_columns` appends only the missing roles as ordinary `text` columns with `origin='user'`, in one transaction; if all roles exist it writes nothing.
Limits: The role feeds nothing yet; cell quality is unmeasured, and the three columns change `report_ready` and the snapshot (accepted in D130).

## D130 — P6 slice 2 (Chain of Ideas): evidence-linked development lines are accepted for implementation as a core of nine batches; the zero-continuation marker, forward check and report entry are deferred
Status: accepted (design only) · Date: 2026-09-30
Chain of Ideas is accepted as a core of nine batches named `lineage_*` (not D95's citation chaining): three node cells as `lineage_role` columns, a read-time citation edge with four states, an on-request field baseline, six relations with `independent_parallel` as a cross-relation, human links only with a located anchor, a list view under the table, and one run of at most 25 works. The zero-continuation marker, forward check and report entry are deferred.
Limits: Design, not a verified implementation; mention-finder recall and the 25/8/24/48,000 budgets are borrowed and unmeasured.

## D129 — Report sections: the one repair pairs each failing cell anchor with its own cell's quotes, and a failed section's reason is shown
Status: accepted (uncommitted) · Date: 2026-09-30
The single schema repair for `report_section` now builds per-anchor context in code: the failed quote, that cell's stored evidence quotes and passage IDs, with D127 handles and fixed guidance to rewrite an unsupported claim or drop its anchor. Code never picks, replaces or deletes a quote or claim; the timeline shows a failed section's first stored reason. `references/report.md` records the support boundary.
Limits: Fake models only; whether it lowers real anchor failures is unmeasured, and a later success on the known corpus would not be independent validation.

## D128 — The third and last P16 report run stopped at section IV after 8 sessions on a quote-anchor failure: only R1 and R7 measured, the series ends without a completed report
Status: accepted · Date: 2026-09-30
The third P16 run stopped at section IV after 3.3 minutes and 8 model sessions with `anchor_not_in_cell_evidence`, even after its one repair; the observer cancelled it and the series ends without a completed report. Only R1 (0 of 3 readable sections valid first try, 1 of 3 on R1b) and R7 (199,583 tokens) were measured; R2 to R6, R8, R9, R11 are `run_incomplete`.
Limits: One run, one table, one model; a development measurement conditional on a known corpus, not a failure rate and not evidence about D127.

## D127 — Show per-step citation handles in all four report tasks and reject output IDs outside the shown evidence
Status: accepted (uncommitted) · Date: 2026-09-30
`report_plan`, `report_section`, `report_phrase_repair` and `report_review` now show short per-step citation handles (`psg_P0000001`, `srv_S0000001`, `cel_L0000001`, `col_C0000001`) via mappings in `domain/contracts.py`, and output IDs outside the shown evidence are rejected. Stored input and evidence links keep real IDs.
Limits: This narrows scripted outputs: a count or match naming a frozen-snapshot source not shown in the step now fails; effect on real-model copy errors is unmeasured.

## D126 — The second P16 report run stopped at section IV after 7 sessions: only R1 and R7 measured, the three failed rows stayed out of the written sections
Status: accepted · Date: 2026-09-30
The second P16 run stopped at section IV after 3.7 minutes and 7 sessions: the model dropped two characters of a passage id (`unknown_passage_id`), before and after its repair. The run was not resumed because the frozen rules resume only `client_timeout`; only R1 (2 of 3 valid first try on R1b) and R7 (189,969 tokens) were measured.
Limits: One run and one section failure, not a failure rate; R2 to R6, R8, R9, R11 not measurable.

## D125 — A report can be written with recorded failed rows, only by an explicit choice, and those rows stay out of its evidence
Status: accepted · Date: 2026-09-30
`POST /reports` takes `continue_with_failed` (default false). Continuing is allowed only when every missing cell comes from a recorded failure and at least one included row is complete; the snapshot keeps failed rows in `rows`, drops their cells, and freezes `failed_rows` and `row_counts`, so selection, assembly and review never see them.
Limits: Fake and scripted models only; shows the choice and exclusion work, not what such a report is worth.

## D124 — The P16 report measurement stopped at the table: no report was started, R1 to R11 not measured
Status: accepted · Date: 2026-09-30
The first P16 measurement stopped at the table: one real fill ran 36 sessions in 3.3 minutes, 22 of 23 extraction steps succeeded, one failed with `anchor_not_in_passage`, two sources had no stored passages, so readiness said `ready: false` and no report was started. R1 to R11 are not measured.
Limits: One fill on one corpus, not a rate; says nothing about report quality, timing or cost.

## D123 — Report behavior cases and a seeded-fault review set, run once against gpt-5.6-luna
Status: accepted · Date: 2026-09-30
Eighteen synthetic report cases run once against gpt-5.6-luna: five `report_section` cases (RB) and twelve seeded-fault `report_review` cases plus one control (RS, RC01), via `scripts/model_behavior/run_report_cases.py` and `tests/model_behavior/report_cases.json`. The runner copies the production call shape and stops on the first quota, rate-limit, overload, tool-item or model-mismatch result.
Limits: Not R10: twelve small reports with one fault each, not one stored report with 12 to 14 faults; `assembly_would_catch` not measured.

## D122 — Scripted browser cases for assembly refusal and an empty report section
Status: accepted · Date: 2026-09-30
The scripted model gets two question markers, `[report-banned-word]` and `[report-empty-section]`, and two Playwright cases (ports 8802, 8803) check an assembly-refused draft report and a paused run with an empty section (`section_must_be_rewritten`), including disabled Copy/Download and a 409 from export.
Limits: Synthetic records and a scripted model: shows screen states, not report quality or a section rewritten after Resume.

## D121 — Report sections stop before applying late results, and run errors retain each section's stored reason
Status: accepted · Date: 2026-09-30
Each report section checks run and scope after its model call and after phrase repair, before applying the result, and a stop leaves the section `running`. The run `error_json` keeps `sections` and adds ordered `reasons` (`section_id`, `code`, `detail`, details capped at 300 characters).
Limits: Fake and scripted models only; the crash test simulates interrupted state and calls `Worker.recover()`, it does not kill a process. The UI still shows only a generic section message.

## D120 — The report exports as one Markdown file built from the screen's own read model, with the screen's "not checked" limits written into it
Status: accepted · Date: 2026-09-30
`report/export.py::to_markdown` is a pure function over `report_view`; `GET /api/researches/{id}/reports/{report_id}/export?format=markdown` serves it (409 while in progress, 404 for an unknown id), named `report-<slug>-v<n>.md` or `-draft.md`. The file carries the screen's own "not checked" sentences, a DRAFT line for drafts, numbered references and a corpus footer.
Limits: Fake and scripted models only: shows structure and carried limits, not report quality.

## D119 — Remove `legacy` discovery execution and preserve stored records
Status: accepted (uncommitted) · Date: 2026-09-30
`legacy` discovery execution is removed: new researches use `sw`, and the legacy `search_plan`/`screening` steps, unpaged `_search` and legacy contracts are gone (runtime `skill_package_hash` `sha256:08f1bdea...`). Stored `legacy` researches still answer; their discovery, fetch, scope-revision and seed-replacement calls return 409 `legacy_research_read_only`, and the owner cancels their queued discovery-side runs with a `legacy_workflow_removed` event after `Worker.recover`.

## D118 — The report is read once by a model after assembly, and only a `support_broken` finding on a kept repair can put original wording back
Status: accepted · Date: 2026-09-30
After assembly and `finalize`, one optional `report_review` model step reads the claims of sections that fit a 30,000-token estimate; the record is stored in `reports.review_json` (migration 0057) as `reviewed` or `not_reviewed` with reasons, and never changes report status or version. A `support_broken` finding restores a sentence's original wording only if its latest repair row is `kept` and assembly shows no error before and after.
Limits: Fake and scripted models only; code does not check that a passage supports its claim, and findings other than `support_broken` are shown, never acted on.

## D117 — `sw` is the default search workflow by the owner's decision, and `legacy` is to be removed
Status: accepted · Date: 2026-09-30
The owner chose `sw` as the default: `Settings.search_workflow` and `DEIXIS_SEARCH_WORKFLOW` default to `sw`. `legacy` stays selectable only until a removal slice (D119) takes it out; stored `legacy` researches keep opening and answering.
Limits: On medicine `sw` reached fewer reference trials (mostly for lack of open PDFs) and opened about 124 model sessions against `legacy`'s 10, so quota use rises.

## D114 — The last medicine measurement at `a04eaa0` passes only gate 3; the default stays `legacy` for good in this track, 24b closes undone and the SW track ends
Status: superseded by D117 · Date: 2026-09-30
Slice 30's medicine measurement at `a04eaa0` (898 counted sessions, `gpt-5.6-luna` medium) passed only gate 3: gate 1 failed (9 of 10 answered), gate 2 failed (cited mean `sw` 1.0 vs `legacy` 4.5), gate 4 unreadable (6 unique includes, 8 needed). The default stayed `legacy`, 24b closed undone and the SW track ended; D117 later reversed the default.
Limits: One run per research, one machine and model; the medicine reference rule was chosen after seeing numbers, so gate 2 is descriptive.

## D116 — The other eight assembly rules are in code, and rule 7 compares the stored numbers of II and VIII with the frozen corpus instead of reading label words in prose
Status: accepted · Date: 2026-09-30
The remaining eight assembly rules are in code (5 count fields, 6 banned words, 7, 8 citation source, 9 VII links and VI gap bases, and others). Rule 7 now compares the stored numbers of II and VIII (`found, unique, screened, included, full_text`) with the frozen snapshot (`corpus_count_mismatch`) and requires VIII's `draft["text"]` to equal `render_limitations(numbers)` (`limitations_text_drift`).
Limits: Structure, not meaning: a generic sentence is not shown to be a source's own limitation, and count words are not parsed.

## D115 — Section VIII's numbers are written by code from the frozen snapshot and stored as structured data; the model writes only claims around them
Status: accepted · Date: 2026-09-30
Code computes section VIII's numbers (`review_methodology.limitations_core`: recall `null`, open-access bias, `no_full_text_share`, analyst-inference share, kill-search `not_run`, phrase-repair outcomes, truncation, seven numbered items) from the frozen snapshot, sends them as `report_target.limitations_core`, and stores them in `report_sections.validation_json["numbers"]`; the model writes only claims around them. II stores its counts the same way.
Limits: Fake and scripted models only; a number written in words in a VIII claim is not caught, and phrase-repair counts are as of the VIII write.

## D113 — The report is on screen: written from a ready table, read as an article with numbered citations, edited by claim, marked when its evidence changed
Status: accepted · Date: 2026-09-29
The report is on screen: `report/ReportReadiness.tsx` on the Answer tab (readiness from the backend `report_ready`) offers one "Write report" button per ready table. A report opens as an "Evidence report · V{n}" card and sheet with IEEE-numbered citations, TABLE I from the frozen snapshot, per-claim editing, and an "Evidence changed after this report" band.
Limits: Synthetic data and fake models only; no real-model report was opened on this screen. Markdown export deferred (later D120).

## D112 — A finished report's claim can be edited with its history kept, and the report says which evidence changed after it was written
Status: accepted · Date: 2026-09-29
A finished report's claim is the editing unit: edits and restores are new rows in append-only `report_claim_revisions` (migration 0056), need `expected_version` (409 on mismatch) and honour `Idempotency-Key`. Staleness is computed at read time by comparing the frozen snapshot with live records (changed cells, removed and added rows).
Limits: Synthetic data and the fake model only; PDF re-extraction and passage changes are not detected.

## D111 — `standard` keeps its full-text limits of 100 fetched and 50 read works; 75% of the quantum gain is reached only at `detailed`'s limit, at about `detailed`'s cost (estimated)
Status: accepted · Date: 2026-09-28
`standard` keeps 100 works fetched and 50 read (`backend/deixis/domain/rules.py`). A model-free replay of 12 stored `sw` libraries showed that 75% of the quantum gain (9.7 reference works) needs 300 fetched, which adds about 17 minutes, about `detailed`'s cost; raising only the read limit adds none.
Limits: Measured: fetch plans replayed exactly. Estimated, not measured: which added works would get a PDF and their added time.

## D110 — The user-approved code gate (slice 23) is not built
Status: accepted · Date: 2026-09-27
The user-approved code gate (slice 23) is not built. Offline on 15 stored `sw` libraries the gate could open in 1 of 15 researches, and 24% of rules that pass on half the verified records close an `include` in the other half. SW16 stays a design direction without implementation.
Limits: Every "verified" record is a model reading; no library holds a human decision.

## D109 — The full-text reading judges a marked comparator part by what the comparison group receives, and code no longer excludes on a comparator criterion: kept by the owner's choice although the effect gate failed
Status: accepted · Date: 2026-09-27
`fulltext-adjudication.md` gets a line that a part marked `"role": "comparator"` is `present` only when a passage shows the comparison group receives what the part names. Code marks the part (`adjudication.mark_comparator`) and `adjudication.with_comparator` turns `criterion_absent` into `comparator_exclusion_withheld` (queue `confirm_absent`), so code no longer excludes on a comparator criterion. Kept by the owner's choice although the effect gate failed.
Limits: Measured in one dry run on one medicine question; the guard withholds every automatic full-text exclusion on such a criterion.

## D108 — The medicine re-measurement at `142dfa1` passes gates 1 and 3 and fails gates 2 and 4; the default still stays `legacy`
Status: accepted · Date: 2026-09-27
Medicine re-measurement at `142dfa1` (seven researches, `gpt-5.6-luna` medium): gates 1 and 3 pass; gate 2 fails (cited mean `sw` 1.0 vs `legacy` 3.5) and gate 4 fails (3 serious errors in 10 includes, all comparator). The default stayed `legacy` at this point; D117 later changed it.
Limits: The reference set R rests on two choices made after numbers were seen, and PubMed's backend was down from the second research on.

## D107 — A result part needs a reported result, a study-protocol title keeps a work for a person, and the code query cuts an inverted question at its verb
Status: accepted · Date: 2026-09-27
`fulltext-adjudication.md` says a result part is `present` only when a passage reports that result as a finding of this paper. `adjudication.protocol_title` (an English hand-written regex) turns `all_parts_verified` and `criterion_absent` into `protocol_title` (queue, never excluded). The code query cuts an inverted question at its verb (slice 26, `2c3acf2`).
Limits: English-only, hand-written title rule measured on two fields; a protocol whose title does not say so depends on the method sentence.

## D106 — The criterion names the question's population and comparator, an sw answer with nothing included says so, and Europe PMC's open text is drawn as a labelled PDF
Status: accepted · Date: 2026-09-26
`criterion_proposal` v2 lists `question_elements` (population, comparator; 0 to 2) checked by code, and the consensus makes a role required when at least two valid runs list it. An `sw` answer with no included work ends as `no_evidence` with reason `no_includable_source`, and Europe PMC's open text is drawn as a labelled PDF (slice 25a).
Limits: A proposal set where no run names population or comparator is not caught; only two roles, and the full-text reading queues a missing part rather than excluding.

## D105 — The default search workflow stays `legacy`: three of the four slice 24 gates did not pass
Status: accepted · Date: 2026-09-26
The default search workflow stays `legacy`: in the slice 24a campaign gate 1 (9 of 10 answered), gate 2 (TRE unreadable, |R| = 4) and gate 4 (3 serious errors in 8 TRE includes) did not pass; gate 3 passed. The common cause was a criterion without population and comparator parts (SW23). D117 later made `sw` the default.
Limits: One machine, one model, two questions; the reference sets are not ground truth.

## D104 — An arXiv PDF read without Marker takes its numbered display equations from the authors' LaTeX source, matched to the page by their numbers, behind a flag that is off
Status: accepted · Date: 2026-09-26
An arXiv PDF read without Marker takes its numbered display equations from the authors' LaTeX source, matched by equation number, behind `DEIXIS_ARXIV_SOURCE` (`auto` | `off`, off by default, POSIX only). It runs only when Marker is neither installed nor installing, never on a PDF Marker has read, and an answer run's `read_equations` step records the outcome without pausing.
Limits: One computer, one library, three fields; the rule was chosen after its image sample was seen and has no held-out set.

## D103 — Semantic search gets a keyless built-in model installed on request, embeds batch by batch with partial results and a bounded HTTP 429 wait, and reads an English sentence for a question not in English
Status: accepted · Date: 2026-09-25
Semantic search gets a keyless built-in model (`builtin:bge-small-en-v1.5@aa8f8b0:256`, `fastembed==0.8.1`) installed on request under `<data dir>/tools/`, outside DEIXIS's environment and POSIX only, run by `documents/embedding_runner.py`. It embeds batch by batch with partial results and a bounded HTTP 429 wait, and the person writes the English sentence for a non-English question.
Limits: One computer and one topic; passage-level retrieval with the local model was not measured.

## D102 — An sw research shows where each of its works stands, keeps the flow of an answer's start, counts how often the person changed a machine decision, draws a small audit sample, and exports its search against the PRISMA-S items
Status: accepted · Date: 2026-09-25
`workflow/flow_counts.py` puts every work of the current revision in one of 18 buckets (person's decision first, then outcome, reason code, next step) beside the five SW11.12 counts, and the PRISMA-2020-style boxes carry `flow_status: "incomplete_no_human_screening"` and draw no diagram. An `sw` answer run stores `code:answer_start_snapshot`; the view counts how often the person changed a machine decision, draws a small audit sample and exports the search against the PRISMA-S items.
Limits: A person's abstract-stage decision and "send back to full-text reading" remain an open requirement.

## D101 — An sw research shows what each search arm and ranking signal brought, counted against the person's own decisions; comparative signal contribution, the stopping rule and the costly-signal switch-off stay out of the product
Status: accepted · Date: 2026-09-25
The sw research report shows what each search arm and ranking signal brought, counted against the person's own decisions. The probe set is derived on read, never stored (`workflow/probes.py`); only a person's decision is a positive, two-run model agreement is a separate column, and `source_counts.arms` adds returned, included and confirmed counts per D93 round x source row. The signal table is descriptive; comparative signal contribution, a stopping rule and switching off costly signals stay out of the product.
Limits: with 0-1 confirmed works per research every signal row reads "too few to decide"; whether a person reads these lines and anything live were not measured.

## D100 — A PDF the person attaches in an sw research gets a code at once, a reading request that outlives runs, the front of the reading order, and once read it decides its work
Status: accepted · Date: 2026-09-24
A person's attached PDF in an sw research gets a full-text code at once (`not_read_yet` or `text_unreadable`), a row in `person_pdf_requests` (migration 0052: waiting, planned, read, unread), the front of the reading order, and once read it decides its work. `ResearchFlow.queue_person_reading` opens a reading run when a request waits and no run is active or paused; the person's own decisions are never overwritten and `human_pdf_wrong` speaks only for its version.
Limits: a work waiting because of its own unreadable or wrong file with no other version cannot take a new file; the strict-cue code gate is not built; live acceptance covered one publisher PDF.

## D99 — An sw research lists the works waiting for the person's PDF in reading order, opens their links through the institution's proxy in the browser, and attaches a dropped file only to the version the person picks
Status: accepted · Date: 2026-09-24
The works waiting for a PDF (codes `no_fulltext`, `text_unreadable`, `human_pdf_wrong`) are derived on each read (`workflow/waiting.py`), in the newest retrieval plan's order. Row links open in a new tab through the institution proxy stored in `app_settings.institution_proxy` (https only, `{url}` template or prefix), and a dropped file is attached only to the version the person picks (`identity.propose`; a first page naming several candidate DOIs lets the title decide).
Limits: no live acceptance with a real publisher PDF (machine off the institutional network); checked on a copy of a stored library only.

## D98 — The full-text fetch of an sw research runs inside its discovery run, from the abstract code step on, for the works already certain to be in the plan
Status: accepted · Date: 2026-09-24
An sw discovery run queued with setting `auto` fetches full text inside itself (`fulltext_fetch.mode = "overlap"`): after the abstract code step it writes `fetch_baseline` and starts a fetch arm beside the model arm, claiming only works whose abstract decision is final and that sit inside the plan (`fulltext.safe_to_fetch`). At most four works are in flight, `fulltext_plan` is written once when the model arm ends, and the run queues its reading run `fulltext_adjudication:after:<run>`; earlier runs keep D83's separate path.
Limits: two live quantum runs only; the work list's equality at the moment the plan was written was not measured.

## D97 — The human queue screen: its own tab, a list and one row's detail, the PDF opened on the row's page by one action, only the backend's anchor marked
Status: accepted · Date: 2026-09-24
The human queue screen is the tab "Awaiting your decision" after Sources (`HumanQueue.tsx`): a list in fused order with `look_again` rows last, filters, and one row's detail with the two runs side by side. Four answer buttons sit in a pinned footer, an answer is sent with the row token and only on a detail with the same token, a 200 removes the row and shows an Undo toast, and the PDF opens on the row's page with only the backend's anchor marked.
Limits: case J uses four SYNTHETIC works and a scripted model; `confirm_quote`, `confirm_pdf` and `choose_version` rows were seen only synthetically; no person's reading quality was measured.

## D96 — The human queue: rows derived from stored decisions, a person's answer written as a stage decision and the user's selection in one transaction, and no model call for a decided work
Status: accepted · Date: 2026-09-24
The human queue is derived on each read by `workflow/queue.py` from `DecisionStore.work_outcome`: one row per work routed to `human_queue` or `versions_disagree`, with a kind (`confirm_quote`, `choose_run`, `choose_version`, `confirm_pdf`, `confirm_absent`, `find_part`), one question and a `row_token`. A person's answer (`include`, `criterion_not_met`, `not_sure`, `pdf_wrong`) is a `human` stage decision plus the user's selection with an append-only `human_selection_links` row (migration 0051) in one transaction, and a decided work gets no model call.
Limits: replay of 11 libraries matched planned row counts and two live quantum quick runs passed K8; no person's use of the queue was measured.

## D95 — Citation chaining: 15 code seeds plus the user's, both directions through OpenAlex, its own abstract read and 12 places after the keyword plan
Status: accepted · Date: 2026-09-23
Citation chaining runs after the keyword abstract stage: the first 15 distinct non-user works of the BM25-and-blocks order plus every user seed, followed in both directions through OpenAlex (references, and `cites:` 200 per page, at most 400 per seed). A linked work is kept only if a setting or task form of the approved vocabulary appears in its title or abstract; chained works get their own ranking, an abstract read of 20 / 50 / 50 by effort, and a fourth full-text group of 12 places (`CHAIN_PLAN_ROOM`).
Limits: end-to-end runs were far over the 10 / 15 / 20-minute targets (quantum quick 12.9-14.0 min); the chain's own share was 1.3-2.1 min.

## D94 — Keep the full-text order, and give quick twice the full-text room: fetch 80 works, read 40
Status: accepted · Date: 2026-09-23
The full-text order stays as it is (D79 inspection order, D83 groups). `quick`'s limits double: `FULLTEXT_WORK_LIMIT["quick"]` 40 to 80 works fetched and `FULLTEXT_READ_LIMIT["quick"]` 20 to 40 works read; `standard` (100 / 50) and `detailed` (300 / 150) are unchanged, and a queued run keeps its old budget.
Limits: two topics only (quantum, packet size), against incomplete reference lists; it does not show the order is right in general or that the limit is the only loss.

## D93 — Route the sw search to its sources from one field distribution, search Semantic Scholar through its bulk endpoint, and count what each source brought
Status: accepted · Date: 2026-09-23
A `source_routing` step sends one OpenAlex request grouped by primary-topic field for the gate query and stores the answer; OpenAlex and Semantic Scholar are always searched, and a field-specific source is added when its fields (`SOURCE_ROUTES`) hold at least `ROUTE_SHARE` 0.25 of the records. CORE and SerpApi leave the sw search (`sw_searchable=False`), every sw Semantic Scholar query uses the bulk endpoint with `sort: citationCount:desc` (up to 1,000 papers a call), and the report counts what each source brought.
Limits: the share and table were set by hand with no test question near the threshold; the bulk sort rests on one topic; arXiv returned no page in either acceptance run (406).

## D92 — A model writes the sw search query once per scope revision, and the code's own query is searched beside it
Status: accepted · Date: 2026-09-23
A new model step `search_query` (`references/search-query.md`, `search-query.schema.json`) writes at most six terms per block with a kind and up to three backups, once per scope revision from the question alone. Code counts each term alone and with the other block, replaces a term no record holds with its backup, and sends per provider the model's query and then the code's own (each marked `origin`), so the OpenAlex pair survives every effort.
Limits: one model and three questions; only OpenAlex order was counted, and wall clock and `quick`/`standard` with two queries were not measured.

## D90 — Repair the sw search query: fit two blocks evenly, let the second round only add and keep its task block, and read 1,000 records per `detailed` query
Status: accepted · Date: 2026-09-23
`_fit_blocks` now trims the block holding the most terms (5 + 4 terms become 3 + 3, not 5 + 1), candidate phrases that differ from a queried, claim or exclusion sequence only by a final `s` are dropped (`domain/expansion.stem`), and the second round is built by `second_round_vocabulary` as either setting synonyms AND the first round's task terms, or the first round's setting block AND task additions, or no round. `SW_READ_LIMIT["detailed"]` falls from 2,000 to 1,000 records per query; `quick` 400 and `standard` 1,000 stay.
Limits: three questions, one run each; the count thresholds still refuse task words, and the block-labelling bounds (Task 3) failed live acceptance and are not part of this decision.

## D91 — Scopus leaves the sw search and becomes the last abstract source, asked only on an institutional network
Status: accepted · Date: 2026-09-23
A new connector field `sw_searchable` (Scopus: `False`) and `registry.search_providers(providers, workflow)` keep Scopus out of new sw queries; a legacy research searches it as before. In the lookup stage Scopus comes after Semantic Scholar and Crossref: one access-check request (`lookup_plan:scopus`), skipped without institutional entitlement, otherwise one `view=COMPLETE` request per DOI for records still without an abstract, counted within `MAX_LOOKUP_REQUESTS` (`abstract_origin = "lookup_scopus"`, migration 0048).
Limits: Scopus's search contribution was measured on one topic; how many abstracts it fills on an institutional network is not measured.

## D89 — Split the request allowance per sw query before the read starts, read discovery searches on several hosts at once, and write what they read in query order
Status: accepted · Date: 2026-09-22
Each sw query gets its own request allowance before its read starts (`page_allowance`: pages needed for the effort's read limit x requests per page, plus `retry_provider_requests`), counted under `usage["query_requests"]["search:<index>"]`. A query that spends its share ends its own read with `stop_reason: "budget_exhausted"` and the run no longer pauses on it. Queries are grouped by `Connector.host`, up to `SEARCH_PARALLEL_HOSTS = 4` hosts are read at once, and pages are written in query order so records match a sequential read.
Limits: the wall-clock gain, whether 4 hosts is right, and whether parallel hosts draw more 429/406 answers were not measured.

## D88 — Bound what an effort collects, not how long it runs: per-query read limits and provider waiting by effort, with 5 / 10 / 15 minute targets measured afterwards
Status: accepted · Date: 2026-09-22
Efforts bound what is collected by count, not wall-clock time: `SW_READ_LIMIT` is per effort (`quick` 400, `standard` 1,000, `detailed` 2,000 records per query), and the rate-limit wait is by effort (`quick` never waits, `standard` once, `detailed` as before). The 5 / 10 / 15 minute figures are targets only; no run is stopped at a time, because a wall-clock cut would change the record count of the same question.
Limits: the first measurement gave 12.1 / 29.9 / 55.5 min against 5 / 10 / 15, with fetch and provider overlap as the main costs; the constants were left unchanged and arXiv answered 406 throughout.

## D87 — Search academic sources through OpenAlex and Semantic Scholar; Crossref verifies a DOI's metadata and links but is no longer searched
Status: accepted · Date: 2026-09-22
Sw discovery searches OpenAlex and Semantic Scholar only. Crossref is no longer compiled a query or offered as a search provider; it stays for `record_lookup:crossref` and DOI checks, and remains registered for legacy researches and existing protocol records. No Crossref fallback was adopted, because a search that runs only on a bad day would make two runs of one question differ.
Limits: one topic, one run; the recall lost without Crossref was not measured.

## D86 — A model connection that cannot enforce the output schema is still usable: the step shows it the schema and a skeleton, code normalises a recorded alias table before validation, and repair no longer empties the run's budget
Status: accepted · Date: 2026-09-22
An adapter declares `enforces_schema`; for one that does not (DeepSeek), the step appends the output schema and a one-item skeleton to the developer instructions. Before validation code applies a small recorded alias table (`name` to `part`, `verdict`/`status` to `label`, label case) and notes it in `validation_json.normalised`; meaning-bearing fields are never changed. A step that fails its repair closes as `invalid_model_output` and the run goes on instead of pausing `budget_exhausted`.
Limits: whether DeepSeek follows a skeleton was not measured here.

## D85 — Follow an sw retrieval run with a full-text reading run: two model runs propose a label and a verbatim quote per criterion part, code checks every quote on the page, and only agreement with every quote verified includes a work
Status: accepted · Date: 2026-09-22
A completed sw `fulltext_fetch` run queues one `fulltext_adjudication` run (migration 0046): two model calls per work return a label and a verbatim quote per criterion part, and code checks each quote on the pages shown. A work is `included` (origin `code_rule`) only when both runs label every part `present` with every quote verified; two `not_met` runs write `criterion_absent`. The budget is 2N calls for N = 20 / 50 / 150 by effort, at most 12 pages per call, and the user's selection is never overwritten.
Limits: reading quality was not measured; legacy researches are refused this run kind.

## D84 — In an sw research, fill the answer input's criterion quota from the approved cue phrases, in rounds across sources, and fall back to the topic order when there are none
Status: accepted · Date: 2026-09-21
An sw answer run gains `code:criterion_phrases`, which compiles the approved criterion cue phrases from `protocol_records` (`store.frozen_criterion`) into literal patterns. `criterion_passages.criterion_order` ranks passages by (distinct phrases, total occurrences, page, id), a quota of `limit // 4` places is filled in rounds across sources, and the rest follows the topic order. With no phrases the whole input is topical, with no fallback to `FORMULATION_TERMS`, and nothing here decides or stores a score.

## D83 — Follow an sw discovery run with a full-text retrieval run that fetches once per work in rank order, records the version read, and leaves a work without text unresolved
Status: accepted · Date: 2026-09-21
A completed sw discovery run queues a `fulltext_fetch` run (migration 0045, `DEIXIS_FULLTEXT_FETCH` default `auto`, key `fulltext_fetch:after:{run_id}`) that makes one retrieval attempt per work and writes one reason code, with no model call. Eligible works go in three groups (user-included, abstract candidates, unresolved), limited by `FULLTEXT_WORK_LIMIT` 40 / 100 / 300; a route that did not answer writes no decision (`fetch_not_settled`), and the next run plans the work again.
Limits: the work limits are hand-picked and not measured; fetch starts after the whole discovery run, a named deviation from SW10.

## D82 — Let the user ask a model for other names of the search terms on the approval card; count every proposal, and let none into the query unless the user adds it
Status: accepted · Date: 2026-09-21
The approval card gains one button that asks a model once, via `POST /api/runs/{id}/term-suggestions`, for other names (`term_suggestions`, at most `MAX_SUGGESTED_TERMS` 12 of `{phrase, synonym_of}`) of the phrases already on it; no automatic trigger. Code drops what cannot enter a query with a reason (`too_long`, `already_present`, claim or exclusion word, `duplicate`, `zero_results`), and nothing proposed is searched unless the user adds it through D80's `add` operation (origin `model` if it matches a stored proposal).
Limits: one call, no repair and no vote; the threshold for an automatic trigger is left to later measurement.

## D81 — Screen abstracts in an `sw` run with a code stage, two batched model runs whose quotes code verifies, and a read limit that leaves the rest unread rather than dropped
Status: accepted · Date: 2026-09-21
An sw abstract stage has two steps: `code:abstract_stage` classifies records without a model (notice, `artifact_of_paper`, `blocks_in_title`, `both_blocks_missing`; a record without an abstract is never out of scope), and `model:abstract_screening` runs twice per batch of 20 records with one label and one quote each, verified by code (`ABSTRACT_QUOTE_MIN_CHARS` 12). Nothing is included from an abstract; an agreed `out_of_scope` sets `excluded` with origin `code_rule`, and the first N works (40 / 100 / 300 by effort) are read while the rest stay `abstract_not_read`.

## D80 — Stop an `sw` discovery run before its first search until the user has approved or corrected the vocabulary and the criterion, and freeze what was approved
Status: accepted · Date: 2026-09-21
An sw discovery run opens a `protocol_approval` step after the criterion step and before the protocol is frozen: it writes the proposal (vocabulary, compiled queries, criterion, `proposal_hash`), then pauses with `protocol_approval_needed`. Count probes run before approval, but no search request, candidate or protocol record exists yet. A correction is at most `MAX_TERM_EDITS` (40) operations (`remove`, `move`, `add`) plus an optional criterion replacement; faults return 422 with every fault listed, and what the user approved is frozen.

## D79 — Order the inspection list by rank fusion of four code signals and an optional embedding signal, store every record's rank in every signal, and never cut by it
Status: accepted · Date: 2026-09-21
In an sw discovery run `flow._ranking` (code only, no model call) orders records by RRF (k = 60, `flow.RRF_K`) over four signals: BM25 of title and abstract, concept blocks hit, TF-IDF cosine to verified seeds, and bibliographic coupling plus direct citation. Every record's rank in every signal is stored in `record_signal_ranks`, ties take the mean rank and the last tie breaks by `source_version_id`. The order removes and decides nothing; `max_candidates` still cuts by it.
Limits: TF-IDF runs only with a verified seed; the share of records without reference lists is reported but its effect was not measured.

## D78 — Let a model propose the inclusion criterion, its parts and cue phrases from the question alone, three times, and keep what two runs agree on
Status: accepted · Date: 2026-09-21
In an sw discovery run `flow._criterion` gives a model only the question and the user's steering and asks, up to three times, for a one-sentence criterion, 2 to 5 parts, 6 to 15 phrases of 1 to 4 words each and up to 30 exclusion words (`criterion-proposal.schema.json`). A phrase is kept when at least two runs wrote it; below two valid runs there is no criterion and the run still searches. The sentence and parts come from the single run closest to the consensus.
Limits: that single run's wording is the one place one run reaches the product.

## D77 — Flag surveys by title, abstract and reference count, ask a second source for a missing abstract by DOI, and let an external link confirm or block a merge
Status: accepted · Date: 2026-09-21
Three code steps run after both search rounds and before screening. `domain/survey.py` flags surveys by title word, abstract phrase or 150+ references (only a strong title word takes a record off the list, as `survey_title_word`); `providers/lookup.py` asks Semantic Scholar `paper/batch` then Crossref `works/{doi}` for a missing abstract; and an external link such as a version or artifact relation can confirm or block a merge.

## D76 — Widen the `sw` search from the first round's own titles and author keywords, probed by count, as a second arm that only adds
Status: accepted · Date: 2026-09-21
After the first round, one code step `vocabulary_expansion` takes candidate phrases from the candidates' title 2-3-grams and author keywords (`ProviderRecord.author_keywords`, migration 0042; only IEEE Xplore and PubMed fill them), keeps those with document frequency of at least 3, and probes the first 20 with two counts each. A phrase is accepted when `count(phrase AND setting block)` is at least 20 and at least 20% of `count(phrase)`; an unreadable count refuses it (`count_unknown`). The result is a second round that only adds.
Limits: thresholds come from one topic; the probe shows a phrase is used in this field, not that it is a synonym of the task block.

## D75 — Read an `sw` query page by page up to one named read limit, and count what was not read
Status: accepted · Date: 2026-09-21
Every provider search takes an optional `cursor` and returns `SearchOutcome.next_cursor`; `registry.Connector` records `paging`, `max_reachable` (Semantic Scholar 1,000) and `page_gap` (arXiv 3.0). `flow._search_pages` reads one sw query page by page, each page its own step, until `exhausted`, `read_limit` (`rules.SW_READ_LIMIT`, 2,000), `provider_cap`, `single_page` or `page_failed`, and writes `unread_count`. The legacy workflow is unchanged.
Limits: `SW_READ_LIMIT = 2,000` was picked by hand and not measured; screening was still cut at `max_candidates` (250).

## D74 — Let a model sort the extracted phrases into concept blocks, bounded to the list code found, and keep the rule as the fall-back
Status: accepted · Date: 2026-09-21
On an sw research `flow._vocabulary` runs an optional `vocabulary_labels` model step three times that labels each code-extracted phrase as `setting`, `task`, `outcome`, `claim`, `exclusion` or `not_a_term`, with the phrase list as its allowlist and no repair (`rules.NO_REPAIR_TASKS`). `apply_labels` keeps a label seen in at least two runs; with fewer than two runs the rule's assignment stands, and a phrase the runs disagree on enters no list.
Limits: measured on 8 questions and 28 phrases with one model and one annotator; a real claim leaking into the query is essentially unmeasured.

## D73 — Take the first search's vocabulary from the question by code, probe each term by count, and keep claim words out of the query
Status: accepted · Date: 2026-09-21
On an sw research a code `vocabulary` step replaces the `search_plan` model step: `domain/vocabulary.py` strips the asking frame, splits at function words and cue words, and assigns blocks by the cue before each phrase (setting, task, method as claim word, outcome stored but not queried). A non-English question without key terms returns nothing and the run pauses; `scope_revisions.key_terms` (migration 0040, 500 characters) carries the user's own English terms.
Limits: nothing measured; preposition-based block assignment is unreliable and English only.

## D72 — Link records of one work by title, authors and abstract together, merge only a preprint with its published record, and keep every link undoable
Status: accepted · Date: 2026-09-20
`domain/record_identity.py` decides what two records are to each other as a pure function: normalised-title trigram Jaccard, record kind (`preprint`, `published`, `artifact`, `notice`), and author surnames, walked through a sixteen-row table. An automatic merge needs title similarity of at least 0.85, agreeing authors, abstract similarity of at least 0.8, and preprint plus published or preprint pair; two published records never merge, and a year gap above five blocks a merge. Every link is stored (migration 0039) and undoable.
Limits: thresholds were set by hand on one topic of records that all had a DOI; records without a DOI were not measured.

## D71 — Store one decision per record and stage with a reason code, and derive the selection an answer reads from it
Status: accepted · Date: 2026-09-20
Migration 0038 adds `stage_decisions` (one current decision per research, record and stage `abstract` or `fulltext`, with outcome, reason code from `domain/reason_codes.py`, decider, next step), `model_proposals` and `record_signal_ranks`. Decisions are added, never edited: a new one closes the old via `superseded_at`, and `DecisionStore` refuses a code or model decision over a `human` one (`HumanDecisionStands`) and marks decisions stale when the scope revision or criterion hash moves. The selection an answer reads is derived from them.
Limits: no workflow step wrote these tables yet; the writers came in later slices.

## D70 — Freeze and hash one protocol record per research before the first search, and break ranking ties by a stable identifier
Status: accepted · Date: 2026-09-20
Before its first provider request a discovery run freezes one protocol record (`protocol_records`, migration 0037, built by `workflow/protocol.py::build_protocol`): question, vocabulary, compiled queries, providers, thresholds, model and effort per role, method package hash and code version. It is never edited; a changed body opens the next revision with a reason (`later_discovery_run`), and every later step carries `protocol_hash`. Audit digests use one canonical form (`domain/canonical.py`), and ranking ties break by a stable identifier.
Limits: criterion, cue phrases, blocks and signal list were null in the body until later slices filled them.

## D69 — Show the Library as project bands of record rows, not a fixed table
Status: accepted · Date: 2026-09-19
The Library is one page of project bands, each a sticky head over record rows (source key, serif title, byline, reading-depth pill, versions, date added, citation count), with a reading-depth rail, coverage bar and one command row (search, sort, depth filter, grouping, density). Every field the table showed is kept; selection, drag-to-project, grouping, pager, fold and persisted preferences are preserved.
Limits: verified only against synthetic records and a scripted model, not a large real library; table-header sort cycling, per-band paging and the work-details pane are gone.

## D68 — Let the user rename a research in place, as a title and not as evidence
Status: accepted · Date: 2026-09-18
A research can be renamed in place from its heading (double-click, Enter or F2) or the sidebar's `Rename` item, through `POST /api/researches/{id}/title` with `expected_version`, recording a `research_title_edited` event. A blank or unchanged title is a no-op, and the title is not a scope change, so answers and runs are untouched.
Limits: the next scope revision or valid answer renames it again (D36); a stale sidebar rename returns 409.

## D67 — Pace Semantic Scholar requests across endpoints
Status: accepted · Date: 2026-09-18
Every request to `api.semanticscholar.org` through the shared provider `send` path passes one process-wide serial gate that waits at least 2 seconds after the previous attempt finishes, including 429 retries, keyed or not. A persistent 429 stays visible as `rate_limited`; no provider is substituted.
Limits: 2 seconds reduces but does not remove 429s (live probe: 4 of 6 searches passed); the gate covers this process only.

## D66 — Bound arXiv rate-limit retries and retry failed searches without changing providers
Status: accepted · Date: 2026-09-18
The arXiv adapter honours a numeric `Retry-After` up to 30 s, otherwise waits at most twice (15 s and 30 s). A completed or paused discovery run with failed provider searches exposes `retry_failed`, which reuses the stored plan and retries only the failed search steps with a bounded extra request allowance; it is refused while another run is active.
Limits: live arXiv behaviour was not re-probed; `Retry-After` dates are not parsed.

## D65 — Let a removed source be deleted permanently from the Trash, but only while nothing cites it
Status: accepted · Date: 2026-09-17
The Trash offers "Delete permanently" per source and per research group (`POST /api/researches/{id}/sources/purge`). It removes this research's membership, screening, selection and lookup rows, and the library record, passages, embeddings and PDF only when no other research holds the source. It is refused with 409 when any evidence link, table row, cell or report citation cites the source, and the row carries a `cited` flag.
Limits: concurrent purges during an active run and the disk-failure path (`files_not_removed`) are not tested.

## D64 — Add an opt-in compact OpenAlex query strategy; retain the measured deep core search
Status: accepted as an opt-in diagnostic, not the default · Date: 2026-09-17
`DEIXIS_QUERY_STRATEGY=compact_openalex_v1` replaces only paired OpenAlex queries with a quoted last two content words of one core synonym plus the last content word of one concept-family synonym, keeping the core-only query at depth 100 and the same request count; the plan records `deixis.query_compiler.v3.compact_openalex_v1`. The default stays `legacy` (v2).
Limits: on six reused questions it found 3/17 controls against 0/17; the strategy was designed after seeing those cases, so this is not an independent recall estimate.

## D63 — Let one selected PDF guide a new Files + academic search
Status: accepted · Date: 2026-09-17
New Files + academic researches use `uploaded_seed` mode: the user picks one readable PDF, and DEIXIS freezes up to four passages (5,600 characters) with asset hash, extraction version and locators in a new scope revision, which the search planner receives with the question. A question edit or a changed or removed PDF requires a new selection; a scanned PDF without text cannot seed, and there is no silent fallback to the question. The default `question_only` mode is unchanged for existing researches.
Limits: tests show routing and evidence handling, not that a seed improves recall or precision.

## D62 — Keep the text layer on Marker pages and read only lines with math from the image, checking inline math against the text layer
Status: accepted · Date: 2026-09-17
On Marker pages with a text layer, the text layer is kept (`LineBuilder_disable_ocr`, `TableProcessor_disable_ocr`) and only lines with a math signal are read from the page image (`marker_runner.inline_math_builder`, at most 256 tokens). A segment is written only when `inline_math.rewrite` accepts it (prose matches the text layer in order, same letters and digits); otherwise the text layer stays. Pages without a text layer use Marker's defaults, and the extraction version stays `...+marker-1.10.2-math-v2`.
Limits: the check compares letters and digits only, so a changed operator or bracket is not caught; 31% of inline expressions stay unconverted; 4 papers from one field.

## D61 — Send table-fill cell extraction calls concurrently under a shared, adjustable limit
Status: accepted · Date: 2026-09-17
`ModelCallLimiter` (`backend/deixis/workflow/concurrency.py`) bounds concurrent model calls process-wide with per-`operation_key` single-flight and a `reduce()` that halves the limit (floor 1) on a rate limit. `_table_fill` submits its (source, column-chunk) jobs through it with a `_checkpoint` before each, resends a rate-limited call up to `MAX_RATE_LIMIT_MODEL_RETRIES = 2`, and applies a finished call's cells only while the run is active on its revision. The limit is `Settings.model_concurrency` (`DEIXIS_MODEL_CONCURRENCY`, default 6).
Limits: verified with FakeAdapter only; no real-model duration was measured, and the Codex and Claude Code adapters initially serialized calls under an internal lock.

## D60 — Read OpenAlex's core-only query 100 results deep; on one popular-topic question a narrow core phrase kept it from helping
Status: accepted (acceptance measurement incomplete) · Date: 2026-09-17
`query_compiler` v2 puts an OpenAlex query for the core group alone first, read `core_depth` = 100 results, within the same request count; `standard` and `detailed` read 100, with 250 candidates and 15 model calls for `standard`, 300 and 20 for `detailed`. Queries stored by v1 resume unchanged.
Limits: known works found rose on the development sets (S1 6-8 to 11, S2 4 to 7) but S3 (popular topic, 20,856 matches) gained only 0 to 2 and missed the +191 s time gate; included precision was not judged and recall on popular topics is not addressed.

## D59 — Give every work one short author–year key and show it wherever the work appears; a table row opens its source

Status: accepted (implemented) · Date: 2026-09-17
Each work gets one key (`works.source_key`, migration 33, built by `workflow/source_keys.py`): first author's family name folded to ASCII and cut at 10 letters, plus the year's last two digits (or `nd`); a collision adds `b`, `c`, … to the later work, so a stored key never changes. Keys show in the Sources list, answer citation chips, reports, source panel and evidence table; clicking a table row's reference opens the source details panel.
Limits: Not checked on real library metadata; names without a comma (double surnames, family-first East Asian names) can take the wrong part.

## D58 — Show the plain-text view of a PDF as a document: title, sections, tables, figures cut from the page, biographies and linked in-text references

Status: accepted (implemented) · Date: 2026-09-17
`documents/figures.py` finds figures from their captions and renders them from the page (`GET …/assets/{id}/figures`); nothing is stored and the model never sees the pictures. `PdfTextDocument.tsx` rebuilds the view from stored passages: joined title, contents for three or more headings, links from "Fig. n", "Table n", "Eq. (n)" and "[n]" to their targets, biographies split out, cut tables kept whole.
Limits: Figure recall not measured; the model still reads passage text as stored; author–year citations and footnotes are not linked.

## D57 — When a question asks how a method field is used in a domain, make the domain the search plan's core concept

Status: accepted · Date: 2026-09-17
Step 3 of the search-plan section in `references/source-grounded-answer.md` gains one rule: when a question asks how a broad method field is used in a domain, the domain is the core concept and the method terms are separate concepts. The query compiler is unchanged.
Limits: One question, one model, three attempts; not a recall measurement, and nothing in `contracts` checks which concept is the core.

## D56 — Keep the answer page quota, and publish a final answer draft after dropping only its unquoted, repeated or stray citations

Status: accepted (implemented) · Date: 2026-09-17
The answer page quota stays. `contracts.salvage_answer_draft` runs only when the last allowed attempt is still invalid: it keeps the first locatable quote of a repeated (claim, passage) pair, drops quotes for passages the claim does not cite, and drops an unquoted citation only if the claim keeps another quoted one; removals are stored as warnings. Handles in prose are replaced by source titles after validation, and `resolve_citation_handles` tolerates extra or missing leading zeros.
Limits: Three answers per arm on one question; salvage makes answers publishable, it does not make the model quote better; claim review was by Claude.

## D55 — Close P5 on a two-question real-model measurement, reviewed by Claude on the owner's delegation

Status: accepted · Date: 2026-09-17
P5 is closed on a two-question real-model measurement. The two largest problems found are carried forward as separate notes: answers on a large selection use no PDF page, and known-work recall on the held-out question is low.
Limits: Every judgment is Claude's, relevance was judged from titles, and answer pages were not labelled beforehand.

## D54 — Rebuild tables in PDF text with Marker and show them as tables

Status: accepted (implemented) · Date: 2026-09-17
`math_reader.table_pages` selects pages with a table caption at a line start ("TABLE 1 |", "Table 2.") and Marker reads them with math and OCR pages; `clean_markdown` keeps each table row on one line and `chunk_page` never cuts inside a row. The Marker version becomes `math-v2` and PDFs read by v1 are re-read in the background (older passages stay resolvable under D45); the plain-text view renders table rows as a table.
Limits: Table cells are not checked against the text layer; tables without a line-start caption or with the caption on another page are not read.

## D53 — Replace and remove API keys read from `.env` from Settings

Status: accepted · Date: 2026-09-17
A managed key comes from the keychain, `.env` or the shell; this supersedes D29's rule that a `.env` key cannot be changed in the app. A `.env` key is replaced or removed by rewriting only its `NAME=value` line atomically (file mode kept) and updating the process environment; a replaced model key is still tried with one short request. Shell-set keys are left alone.

## D52 — Read equations as LaTeX with Marker, an optional local component, before an answer uses the PDF

Status: accepted (implemented) · Date: 2026-09-16
Marker (`marker-pdf==1.10.2`) is an optional component installed from Settings or `python -m deixis equations install|status|remove` into `<data dir>/tools/marker`; DEIXIS never imports it, `documents/marker_runner.py` runs inside its environment. Only pages with at least 60 math-font characters or 12 math symbols are read; the result is a new extraction (`…+marker-1.10.2-math-v1`, D45 rule) and migration 0030 adds `passages.text_source`.
Limits: About 2% of display equations were wrong in the audit and wrong ones look right; the text-layer check misses operator and subscript errors, and its miss rate is unmeasured.

## D51 — Read scanned PDF pages with local OCR on request, label OCR text, and warn on numbers that rest on it

Status: accepted and implemented · Date: 2026-09-16
OCR runs only on request as a background `pdf_ocr` run (no model call) with local Tesseract via PyMuPDF, English and Turkish, on pages with an image and no text. The result is a new extraction under D45's rule with `passages.text_source` = `ocr` (migration 0031); OCR passages are labelled "OCR text · check against the page", and a claim or cell number resting only on OCR gets the warning `ocr_numbers_unchecked`.
Limits: Checked with English-only Tesseract data; the no-Tesseract state was not shown in the browser.

## D50 — Trash tables, templates and sources removed from a research; undo from a notification; start a table from selected sources

Status: accepted (implemented) · Date: 2026-09-16
The Trash page groups researches, evidence tables, sources removed from a research and table templates; nothing expires. Removing a source sets `corpus_memberships.removed_at` (row kept; library record, assets and passages unchanged); a table in trash is restored with its rows, columns, cells and edits. A later search that finds a removed source leaves it removed; re-uploading or adding it from the Library restores it.
Limits: Wrong-PDF undo and template/column restore were checked through the API, not the browser; no screen lists removed columns.

## D49 — Collect the included sources' PDFs before the answer, and let the user add the rest

Status: accepted · Date: 2026-09-16
A new run kind `pdf_collection` (migration 0028) fetches PDFs for every included work without the download cap and calls no model; the Answer tab shows a readiness panel with per-work rows and an upload per missing PDF. `POST /uploads/match` proposes the work for several dropped PDFs by DOI/arXiv id or exact title (at least four words), and the user confirms; `POST /zotero-pdfs` adds from Zotero.
Limits: Matching reads text, so scanned PDFs are not matched; answer quality with more full texts was not measured.

## D48 — A published record heads the work of its preprint, and an answer reads the preprint's open PDF when the record has none

Status: accepted · Date: 2026-09-16
A preprint and a published record join one work when the preprint names the published DOI, or title, first-author surname and at least half the shorter author list match. A work's head is its published record, else its first record, and screening sees heads only. An answer reads one version per work: the head if it has PDF text, else the first other version with PDF text, else the head's abstract.
Limits: Surname matching is weak for common surnames; title-only matches cannot be joined manually yet.

## D47 — Extract PDF text by layout blocks and re-extract every PDF in use

Status: accepted · Date: 2026-09-16
Extraction `pymupdf-<version>-layout-v1` (later `layout-v2`) builds page text from MuPDF blocks: it drops non-horizontal lines, page-number blocks and small-type running heads, keeps small-type blocks as their own paragraphs after the body, makes short numbered or standard headings their own paragraph, joins line-end hyphenation and keeps a numbered reference entry as one paragraph. `Store.reextract_asset` applies D45's rule (the new extraction becomes current only if status is not worse, page count equal, text pages not fewer) and refuses while a run on the source is active; `python -m deixis reextract [--dry-run]` re-extracts every PDF in use.
Limits: Rotated figure and table text is dropped, heading detection is a pattern, and equations stay garbled.

## D46 — Records of one arXiv preprint are versions of one work with one candidate

Status: accepted · Date: 2026-09-16
A new record whose DOI starts with `10.48550/arxiv.` joins the work of the earliest version with that DOI; versions stay stored separately. A work has one candidate per research: a later version counts as finding that candidate again and is not screened on its own. Migration 0026 merges existing versions into one work; published versions and title matches stay separate works with a suspected-duplicate flag (D13).
Limits: The record keeps whichever version was found first; older researches keep both copies' selections; other preprint servers' DOIs are not covered.

## D45 — A replaced PDF or a new text extraction adds passages and shadows the old ones; old evidence keeps pointing at what it read

Status: accepted · Date: 2026-09-16
A source version has at most one PDF in use; adding a second answers 409, replacing is a separate action that marks the old asset removed (`replaced` or `wrong_file`). Re-extraction writes under a new `extraction_version`, part of the passage key, so identical text gets a new passage ID; a new extraction is `current` only if status, page count and text pages do not get worse, else `rejected`. Shadowed passages are never given to a model again but still resolve by ID, and cell revisions, evidence links, answers and reviews keep what they recorded.
Limits: The new labels are covered by backend tests and a build, not a browser run; the equal-page check is an unmeasured default.

## D44 — Compile provider queries from the search plan's concepts instead of letting the model write them

Status: accepted · Date: 2026-09-16
`SearchPlan` becomes `deixis.search_plan.v2`: the model returns `question_interpretation`, `concepts`, `providers`, `scope_boundaries` and `search_rationale` and no queries; a concept's `synonyms` are searched, its `label` is display text only. `contracts._check_search_plan` asks for repair unless there is exactly one `core` concept with synonyms and a compilable query. `providers/query_compiler.py` (`deixis.query_compiler.v1`) builds `core group AND family group` per provider, using `adjacent_field` concepts only when no other family exists.
Limits: No recall measurement; this guards against queries that drop the core term but is not a shown improvement in recall.

## D43 — Let a cell quote one passage more than once, name the passage that holds a misplaced quote, and drop the IEEE download notice

Status: accepted · Date: 2026-09-16
A cell may give several evidence items for one passage when they quote different spans; `duplicate_evidence_quote` fires only when a quote locates the same words twice (migration 0024 rebuilds `cell_evidence_links` with a unique index on revision, passage and anchor text). When a quote is absent from the cited passage but present in another passage of the same source version, `anchor_not_in_passage` names up to three such passages; code never moves the item. `references/evidence-table.md` rule 5 is updated and the IEEE download notice is removed from extracted text.
Limits: One research, one model, one run each; the model's response to the new wording is not separated from run-to-run variation; quotes crossing a chunk boundary still fail.

## D42 — Name an older research on request with a research title run

Status: accepted · Date: 2026-09-16
A research can start a run of kind `research_title` (`POST /api/researches/{id}/runs`, migration 0022) with one model step, the same `research_title` contract as discovery's, on the question and the included sources' titles and abstracts. Budget is two model calls and no provider request; a failure pauses or fails the run visibly. The header offers "Suggest a short title" while the title is still the question.
Limits: The title is a model proposal used as a label, checked only against the 15-word and not-the-question rules.

## D41 — Group the Library by project and add a work to a research by dragging it

Status: accepted · Date: 2026-09-16
The Library groups works by project by default (toggle for a flat list); a row can be dragged onto a project, or added from the work details panel menu. `POST /api/researches/{id}/library-sources` with a `work_id` adds one version of the work, the one with the deepest stored reading (PDF text, then abstract, then metadata), with `added_by = 'library'` (migration 0021) and an `included` selection of origin `user`. A work already in the research answers 409.
Limits: Adding fetches, extracts and screens nothing; there is no remove action in the Library.

## D40 — The Library is a reading-depth table with a work details panel

Status: accepted · Date: 2026-09-16
The Library is a dense table (paper, authors, venue, reading depth, year, citations, projects, added). `library_view` reports reading depth per source version and per work (`pdf_available`, `abstract`, `metadata`), the same way as the evidence table's `access_level`, and it drives the toolbar filter. A row opens a details panel fed by `GET /api/library/works/{work_id}` that lists every stored version separately; versions are never merged.
Limits: Reading depth describes what is stored, not whether a passage supports a claim; the list is not virtualized.

## D39 — Cap research titles at 15 words and name the research during discovery

Status: accepted · Date: 2026-09-16
The grounded answer's `title` ceiling moves from 20 to 15 words. A new optional model step `research_title` (`deixis.research_title.v1`, title of at most 15 words, not copied from the question) runs at the end of discovery and writes through `set_research_title`, gated on the scope revision; a valid answer still renames the research later.
Limits: The discovery-time title is a model proposal; no real model had written one yet.

## D38 — Extract evidence table cells one source version at a time, from that version's passages only

Status: accepted · Date: 2026-09-16
`EvidenceCellDraft` v1 answers every target column once for one source version, with states limited to `value`, `unknown`, `not_applicable` and `not_found_in_inspected_scope`. The StepInput carries `extraction_target` and `check_step_input` refuses a cell StepInput holding anything but that version's sources and passages; it never carries a current cell value. Validation adds per-cell checks (`unknown_column_id`, `duplicate_column_answer`, `anchor_not_in_passage`, `value_without_evidence` and others) through the single repair; `TableColumnProposal` v1 suggests at most eight columns.
Limits: No real model had filled a cell; passage limits (48, 24, 16) are untested defaults.

## D37 — Keep evidence table cells as append-only revisions that only the user can change

Status: accepted · Date: 2026-09-16
A table belongs to one research with explicit rows (`table_rows`); columns carry a name, a human-annotator instruction and a format, and a changed definition is a new column revision (older values read as `stale_column`). A cell is an append-only list of revisions (`model_fill`, `model_proposal`, `system_fill`, `human_edit`, `accept_proposal`, `dismiss_proposal`); a model result becomes the value only of an empty cell, every other result waits as a proposal until the user accepts or dismisses it. A trigger refuses evidence from any other source version; human writes carry the cell version and get 409 on a stale one, and writes accept `Idempotency-Key`.
Limits: At the time no model had filled a cell; semantic support of cell evidence stays `not_checked`; no restore screen existed yet.

## D36 — Let the answer model replace the provisional question with a bounded report title

Status: accepted · Date: 2026-09-16
`GroundedAnswerDraft` v3 requires a `title` in the answer language (method asks 15–20 words; validation rejects more than 20 and uses the single repair). Only a structurally valid answer for the current scope revision replaces the question-as-title; the full question stays unchanged in the scope revision. D39 later lowers the cap to 15.

## D35 — Remember refused PDF links and look once for another open copy

Status: accepted · Date: 2026-09-15
A link that refused (HTTP error, not a PDF, too large, disallowed address) is not requested again in a later run; timeouts are retried. After a 403 or 404 the answer run looks the DOI up once per source in Unpaywall, OpenAlex, Crossref and CORE (step `pdf_other_copy`) and attaches only a DOI-verified copy of the same version (D4). DEIXIS does not try to get past bot protection.
Limits: Not measured on live providers; repository copies are often accepted manuscripts, so many refused sources still need a user upload.

## D34 — Close P4 on the packet-size re-run, reviewed by Claude on the owner's delegation

Status: accepted · Date: 2026-09-15
P4 is closed and later phases start now; the limits are carried forward, not fixed first.
Limits: The review is Claude's, not a person's; one question and one run per setting; recall is the weakest result, with about half the known works missed.

## D33 — Let the user confirm a version-uncertain PDF candidate before it is attached

Status: accepted · Date: 2026-09-15
Every PDF candidate offers Open file. A candidate with version `uncertain` whose DOI or exact title matched (`doi_verified` or `title_verified`) on a source without a PDF also offers "Same version, attach"; an `unverified` web result cannot be attached this way. Only that explicit request fetches the file through the bounded fetcher, and it is attached with origin `user_upload` and `retrieved_from` set, because the version claim is the user's.

## D32 — Add PubMed through NCBI E-utilities

Status: accepted · Date: 2026-09-15
A `pubmed` connector runs ESearch then EFetch as one provider operation and keeps PMID, DOI, title, authors, journal, year, abstract sections; it attaches no PDF. It works without a key (`NCBI_API_KEY` optional, never stored in request records), identifies as `DEIXIS` with the contact email, and the search plan uses native Entrez syntax.

## D31 — Add CORE as a search provider and a PDF-location lookup

Status: accepted · Date: 2026-09-15
A `core` connector searches CORE API v3 (`/v3/search/works/`) and requires `CORE_API_KEY` (keyless use hit 429 in 4 of 12 requests). Unbalanced queries, quoted phrases without AND and field prefixes are sent back for repair, based on live probes. The PDF resolver queries CORE after Unpaywall, OpenAlex and Crossref with `doi:"<doi>"`, records DOI-matched PDFs as `doi_verified` but version `uncertain` (listed for review, not auto-downloaded under D4); `fullText` is not stored.

## D30 — Order "Most relevant" sources by similarity to the question after the screening verdict

Status: accepted · Date: 2026-09-15
After screening, each candidate's title and abstract are embedded with the Settings semantic provider (D29) and the cosine similarity is stored per research, question revision and model (`source_similarities`). "Most relevant" orders by screening verdict, then similarity, then search position; a neutral pill shows the score to two decimals. Only this order reads the score, and a failed embedding does not stop the run.
Limits: The score is an ordering signal, not a relevance judgment, and is off when semantic search is off.

## D29 — Manage keys, local tools and the semantic search provider in Settings

Status: accepted · Date: 2026-09-15
Connections becomes a Settings tab (`#/settings/connections`). Gemini, OpenAI and scholarly source keys are saved to the system keychain under service `DEIXIS`, never returned by the API; Gemini and OpenAI keys are tried with one short request first, and a key from the shell or `.env` wins (D53 later relaxes this for `.env`). The tab shows Claude Code, Codex CLI, Gemini CLI, Ollama and LM Studio and installs a missing tool with one fixed command after confirmation; semantic retrieval uses the Settings provider (Gemini `gemini-embedding-2`, OpenAI `text-embedding-3-small`, a local embedding model, or off).
Limits: Only the Codex CLI runs research steps at this point; Ollama and LM Studio do not.

## D28 — Choose each step role's model from any model connection

Status: accepted · Date: 2026-09-15
A question revision stores `literature_connection` and `review_connection` next to `model_connection` (migration 0016; NULL means use `model_connection`). `POST /api/researches` checks each role's model and effort against its own connection and refuses unlisted models without substitution. The picker groups models by connection, and cancel interrupts the current call of every connection.

## D27 — Rank answer passages semantically as well as lexically

Status: accepted · Date: 2026-09-15
When `GEMINI_API_KEY` is set, the answer step embeds the included sources' passages (`gemini-embedding-2`, 768 dimensions; vectors stored once per passage and model, migration 0015) and the question. Reciprocal rank fusion (k = 60) combines lexical and semantic passage rankings and each source's BM25 rank with its best semantic passage rank; user-chosen sources and provider counts still come first (D17). Recorded as a `semantic_retrieval` step; if embedding fails the answer uses lexical retrieval alone.
Limits: Passage text and the question are sent to Google whenever the key is set.

## D27 — Every published citation must have a highlightable source anchor

Status: accepted · Date: 2026-09-15
`missing_citation_anchor` and `anchor_not_in_passage` are validation issues that trigger the single bounded repair naming the claim-passage pair; if repair fails the draft stays unverified and is not shown as source-linked. The UI highlights only backend-located, source-owned text and never guesses a span. This supersedes D24.
Limits: Stored answers are immutable and may keep anchors missing under D24; regenerating is needed to get highlights.

## D26 — Connect Gemini through the Gemini API, not the Gemini CLI

Status: accepted · Date: 2026-09-15
The `gemini` model connection calls `generativelanguage.googleapis.com` directly with `GEMINI_API_KEY`: one request per step with a system instruction, the step message and `responseJsonSchema`, no tools. `minItems`/`maxItems` are removed from the sent schema (the API rejects them) and enforced by DEIXIS validation; aliases such as `gemini-flash-latest` are not offered. The Gemini CLI is only reported by the health check and runs no steps.

## D25 — Extract PDF text with PyMuPDF and license DEIXIS under AGPL-3.0-or-later

Status: accepted · Date: 2026-09-15
New PDF text is extracted with PyMuPDF (`pymupdf-1.28.2-chunks-v1`, ligatures expanded, text outside the page box dropped) and pypdf is removed; passages already extracted keep their pypdf `extraction_version`. DEIXIS is licensed AGPL-3.0-or-later (`LICENSE`, `pyproject.toml`), as chosen by the owner.

## D24 — Citation anchors locate text; they do not reject answers

Status: superseded by D27 · Date: 2026-09-15
A quote that cannot be located, or a missing quote, was a warning (`anchor_not_in_passage`, `missing_citation_anchor`), and the citation opened without a highlight. `locate_anchor` compares case-folded NFKC word characters with spaces and punctuation removed and accepts one contiguous near match with ratio ≥ 0.9; the highlight uses the passage's own words and stores the match kind (`exact`, `normalized`, `fuzzy`).

## D23 — Query Unpaywall before other PDF-location providers

Status: accepted · Date: 2026-09-15
The PDF resolver queries Unpaywall first with `DEIXIS_CONTACT_EMAIL`, keeps every `oa_locations[].url_for_pdf` candidate, then still queries OpenAlex and Crossref. The same DOI and version gates apply before retrieval; a missing contact e-mail is stored as `auth_required`. Web Search stays the labelled final fallback.

## D22 — Preserve PDF candidates and make acquisition failures visible

Status: accepted · Date: 2026-09-15
A source retains every PDF candidate from OpenAlex `locations` and Crossref `link` with provider, DOI identity state, version state, license, URL and retrieval outcome. Only a DOI-verified candidate whose version equals the source record is downloaded and attached. If none qualifies, a labelled SerpApi Google Scholar search by exact title records candidates that stay version-uncertain; the Sources UI shows the searches, HTTP status and outcome and offers Open at publisher and Attach PDF.

## D21 — Read short attached PDFs fully and inspect same-version OA locations

Status: accepted · Date: 2026-09-15
When exactly one source is included in an attached-file scope and all its passages fit within 48 passages, 12 pages and 60,000 characters, all passages go to the answer in page order; larger corpora keep bounded ranking and the six-passages-per-source cap. The OpenAlex adapter reads `locations` and prefers an OA PDF whose version equals the primary record's.

## D20 — Reserve bounded answer room for formulation pages and warn about unsupported math

Status: accepted · Date: 2026-09-15
After the first passage per source, qualifying `pdf_page` passages (lexical score 3 or more: 2 points per optimization phrase, 1 per math symbol capped at 6) get up to a quarter of the answer-passage limit. Validation adds non-blocking warnings `math_not_well_formed` (unbalanced `$`, braces or environments) and `math_without_full_text` (mathematical claim citing only abstract-level passages).

## D19 — Write the answer as a sectioned report with LaTeX math; phrasing checks only warn

Status: accepted · Date: 2026-09-15
`GroundedAnswerDraft` allows up to 60 claims, each with a required `section` (1–120 chars; migration 0009 adds `claims.section`), claim text up to 2000 characters, at most 5 cited passages per claim; `AnswerReview` allows 60 reviews. Math is written as LaTeX (`$…$`, `$$…$$`) only as a cited passage states it and rendered with KaTeX 0.16. D15's phrasebank checks (`sentence_without_phrasebank_frame`, `own_work_phrase_in_claim`, `plural_sources_for_one_source`) become warnings that never trigger repair.

## D18 — Continue discovery when a provider search fails

Status: accepted · Date: 2026-09-15
A failed search is recorded and its step marked `failed` or `outcome_unknown`, but `_search` returns the failure instead of pausing; discovery continues with the remaining queries and screening. The run pauses only when no search succeeded, and resuming retries failed searches only in that case (so a timed-out SerpApi request is not paid twice). No provider replaces another; the Answer tab lists incomplete searches and "Search again" retries all.

## D17 — Order included sources for the answer step by user choice, provider agreement and text match

Status: accepted · Date: 2026-09-15
`flow.answer_source_order` puts user-chosen sources first, then sources returned by more distinct providers (bioRxiv counts as OpenAlex), then BM25 (k1 1.2, b 0.75) of title plus abstract against the question and search-plan terms, then selection order. `Store.answer_order_facts` supplies the flags.

## D16 — Export bibliographies as BibTeX/RIS and import a Zotero collection read-only

Status: accepted · Date: 2026-09-15
`GET /api/researches/{id}/bibliography?format=bibtex|ris&sources=included|cited` (`workflow/bibliography.py`) exports the included or cited sources, with the read source version in `note`/`N1`. `GET /api/zotero/collections?source=local|web` and `POST /api/researches/{id}/zotero-imports` import one collection's own items (at most 100, `providers/zotero.py`) using only GET requests: local API on 127.0.0.1:23119 without a key, or api.zotero.org with `ZOTERO_API_KEY` and `ZOTERO_LIBRARY_ID`.

## D15 — Write answer prose on Academic Phrasebank frames and check every sentence

Status: accepted · Date: 2026-09-15
`methods/deixis-research/references/academic-phrasebank/phrases.txt` holds 1618 frames from the 2015 enhanced edition, each followed by a `tr:` Turkish rendering; only the answer step loads it. Validation required each sentence to keep at least 70% of a frame's fixed words (`sentence_without_phrasebank_frame`) and rejected own-work phrases and plural-source phrases for a one-source claim. D19 turns these checks into warnings.

## D14 — Choose separate literature and reviewer models; review answers in the background

Status: accepted · Date: 2026-09-14
A research stores a literature model and effort with its question revision (migration 0007); the search plan and screening run on it, the answer on the research model. The reviewer is set app-wide (`PUT /api/settings/reviewer`) and per research as `default`, `custom` or `off`; a valid answer triggers an `answer_review` step that returns one verdict per claim (`supported`, `partially_supported`, `not_supported`, `cannot_assess`), stored in `answer_reviews` and never changing the answer. Settings defaults only prefill the composer.

## D13 — Connect all scholarly providers with per-provider query rules and DOI merging

Status: accepted · Date: 2026-09-14
Adapters for Semantic Scholar, Crossref, arXiv, IEEE Xplore, Scopus and SerpApi join OpenAlex in `backend/deixis/providers/`, sharing one record shape and `common.send` (a 429 is retried at most twice; other 4xx is `rejected_not_executed`; 5xx leaves delivery unknown). Budgets: quick 3 queries; standard 8 queries, 150 candidates, 12 model calls; detailed 12 queries, 200 candidates, 14 model calls. Per-provider query rules follow live probes, and the same normalized DOI from several providers is one source version.

## D12 — Show the answer step short citation handles instead of record IDs

Status: accepted · Date: 2026-09-14
The grounded-answer step message shows per-step handles (`psg_P0000001`, `srv_S0000001`) instead of record IDs; the StepInput keeps the real IDs and `contracts.with_citation_handles` / `resolve_citation_handles` (called in `flow._model_step`) map them back before validation.
Limits: Model copy errors of identifiers were reduced but not eliminated.

## D11 — Limit OpenAlex query shape and measure known-source recall by stratum

Status: accepted · Date: 2026-09-14
Search-plan validation rejects an OpenAlex query with more than two AND-joined parts, more than five operators or three unquoted words in a row, and a plan with no quoted multiword phrase (`provider_query_shape`). The measurement kit groups known sources by `# stratum:` lines, reports found, included, given and cited per stratum and compares runs (`measure.py compare`). No code-built base query is added.
Limits: Stratum classification was a draft; with 48 sources in one answer step, two of four live answers stayed unverified because the model mis-copied long IDs (solved later by D12).

## D10 — Remove the browser-only UI prototype

Status: accepted · Date: 2026-09-14
`prototypes/` is deleted (recoverable from commit `84ba12d`). This supersedes the prototype placement in D1 and the "stays untouched" clause in D2.

## D9 — Read more search results, give every included source to the answer, show citation counts

Status: accepted · Date: 2026-09-14
Results read per query are set by depth (quick 10, standard and detailed 25), separate from candidate limits (20, 100, 150); screening runs in batches of 40; model-call limits are 6, 10, 12. The answer first gives every included source one passage, then fills with best-matching passages (at most 6 per source; passage limits 16, 48, 80). OpenAlex `cited_by_count` is stored with its retrieval date (migration 0005) and shown, not given to the model.

## D8 — Check locators in claim text and OpenAlex OR syntax; record A–G acceptance and P4 measurement

Status: accepted · Date: 2026-09-14
Answer validation rejects claim text with a page, equation, table, figure, section or DOI locator (`locator_in_claim_text`), and search-plan validation rejects OpenAlex queries mixing OR with other terms outside parentheses (`provider_query_syntax`). A Playwright suite (`apps/web/e2e`, fixture server in `tests/acceptance/`) records A–G acceptance; `scripts/p4_eval/measure.py` covers link checks, a Crossref identity check and a human review sheet.
Limits: The locator check is a pattern match; the suite uses synthetic data and a scripted model, so it tests handling, not model quality.

## D7 — Let the user choose the model's reasoning effort

Status: accepted · Date: 2026-09-14
A research stores an optional `reasoning_effort` with its question revision (migration 0004); the API accepts only efforts the connection lists for the model, and the Codex adapter sends it with every turn.
Limits: Codex does not echo the applied effort, so it is sent but not verified.

## D6 — Close P4 technical gaps: backup, resource bounds, versions and revision labels

Status: accepted · Date: 2026-09-14
`deixis backup` writes an SQLite snapshot plus referenced PDFs and payloads with a SHA-256 manifest (never the Codex home); `deixis restore` verifies hashes and restores only into an empty data directory. PDF extraction caps text at 3 M characters and kills the child above 1 GB resident memory; uploads are refused above the declared length; PDF fetches connect to the checked public address and ignore proxies. An OpenAlex OA location with a different version label becomes a separate version of the same work; Cmd/Ctrl+K searches titles, questions and source titles.
Limits: No memory cap on Windows yet; locator assertions in claim text were left to the method rule (later D8).

## D5 — Enforce the chosen model, result applicability and local boundaries

Status: accepted · Date: 2026-09-14
A research requires an explicit model the connection lists; output from another model is recorded and the run pauses (`model_mismatch`). Runs check pause and cancel after every external call; search runs and candidates carry the question revision; a selection revision stored with answers marks them `stale_selection` when selections change (migration 0003). The Codex process gets an allowlisted environment without provider keys, and the API accepts only loopback peers.

## D4 — Attach an open-access PDF only to the source version it belongs to

Status: accepted · Date: 2026-09-14
The OA location's version is stored as `source_versions.oa_pdf_version` (migration 0002) and the PDF is fetched only when it equals the record's `version_label`; otherwise it shows as "different version · not used". Search uses OpenAlex `search.title_and_abstract`, since plain `search=` also matches full text and returned off-topic records.
Limits: Records from before migration 0002 have no stored OA version, so attached PDFs were not re-checked.

## D3 — Run Codex in a DEIXIS-owned Codex home with explicit models

Status: accepted · Date: 2026-09-14
The Codex adapter uses `CODEX_HOME` under the DEIXIS data directory (separate sign-in), disables tools, connectors, skills and instruction files via config overrides, starts one ephemeral read-only thread per step, rejects any thread reporting instruction sources or output with tool items, and always sends the research's chosen model.
Limits: `skills/list` still discovers host skills, although none were injected into probed prompts.

## D2 — Place the first-slice application code

Status: accepted · Date: 2026-09-14
Python 3.12 backend (FastAPI, SQLite) in `backend/deixis/`; React UI in `apps/web/`; JSON Schema contracts in `contracts/research/`; method package in `methods/deixis-research/`; tests in `tests/`; probes and runners in `scripts/`. Run with `PYTHONPATH=backend uv run python -m deixis serve`, since macOS hides `.pth` files in iCloud-synced folders.

## D1 — Separate current design drafts from the dated handoff

Status: accepted · Date: 2026-09-14
`docs/desktop/` stays the dated handoff and reference index; active product/API drafts go in `docs/product/` and method designs in `docs/methods/`, with `docs/layout.md` as the placement contract. No empty application directories are created and no stack is chosen by reorganizing files.
