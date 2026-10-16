# DEIXIS status

**Last updated:** 16 October 2026. Decisions are in [docs/decisions.md](docs/decisions.md); old D numbers point to the old log in Git (commit 26c8214).

## Now

The owner is checking the app by eye, and the problems they find get fixed in order. P10 (the macOS package) waits until that check is done.

## Next

1. The owner's visual check and the fixes it turns up.
2. P10: the macOS package (plan in `.local/plans/p10-plan.md`), then the search work listed under "Search" below.

## Done

Most of this was tested with fake models and synthetic data only; "Not measured" below lists what still needs a real model or real use.

### Search and seed PDFs

- Clean start (10–11 Oct): the fast path is the only search path, the old search and answer paths and old data support are gone, and the schema starts from one baseline.
- Seed PDFs steer the search (D2, D3, D6): up to 5 uploaded or Zotero PDFs feed the citation chain and similar-paper requests without pushing out the question's own results.
- OpenAlex similar-paper requests now overlap, starting 1.5 s apart with 100 records per page (D10).
- PRISMA-S, the Method box and Watch now read the requests the fast plan really sends, including its semantic and Semantic Scholar requests, and Watch keeps each query's saved position.
- Citation map (D42): a panel draws the sources by year or as a network from OpenAlex reference lists, and a work cited by two or more sources can be added as a candidate.

### Reading and answers

- An answer over attached PDFs only now spreads its 48-passage limit across all PDFs instead of taking 6 from each (D4).
- The reading stage reads late PDFs of undecided works, passes a failed PDF's full-text slot to the next work, and splits the "screened" count by reason (D60).
- The line above the answer says how many cited sources were read in full and how many from the abstract only, and table cells filled from an abstract are re-read when the PDF arrives (D52).
- The full-text label says how many text chunks and pages the model actually saw (D62).
- Formula questions put each source's most formula-heavy page into the answer input (D56).
- Works the survey title rule set aside are labeled `code_decided` in the answer input, not `not_screened_at_cutoff` (D69).
- Raw LaTeX outside `$…$` in answers, follow-ups and report sections sends the step to repair (D61).

### Follow-up questions

- Follow-ups read the question, the last answer, earlier follow-ups and the evidence table, and can run a second pass over the research's own passages with up to 3 search phrases (D49, D50, D53).
- A follow-up gives one passage per work named in the table before the rest, so cross-work questions reach more works (D64).
- A follow-up that counts or groups works has the model classify each work with a quote, and the app does the counting (D66).
- A follow-up no longer opens a new question revision, and an unused revision can be withdrawn (D67).

### Evidence tables and reports

- A table cell gets a "Check the number" flag when its number appears in none of its quotes (D54).
- Report sections follow new writing rules (no synonym paraphrase, link sources, no simulation called an experiment), with two non-blocking warnings that check them (D51, D55).
- Report versions go up only when the person asks; the app's own updates show as V1.1 (D57).
- The model instructions were checked against the code with GPT Astra High: wrong or missing references were fixed (index terms, future-work citations, answer title length, follow-up second pass), and every instruction file is still in use.
- Report sections see every table cell, drop the lowest-priority column instead of rows when over budget, and are reviewed in 30k-token chunks (D58).
- A table opened from included sources adds a row when a source is included later (D63).
- A report section gets a second repair before the report pauses (D65).
- Table cells that fail their quote check no longer stop a report; they are retried once and otherwise marked not verified (D68).

### Models and settings

- API keys, including Zotero and TypeSafe, live in the system keychain, and `.env` keys move there on startup (D19, D29).
- Settings › Models has one card per company with both account sign-in and API key, plus new connections such as Claude and OpenAI API, OpenRouter and MiMo (D20–D24, D34).
- Ollama and LM Studio cards install the app, start the server and download recommended models, and local models finish a full Quick research (qwen3.5:9b, about 32 min) (D39).
- Users without a key get the downloaded built-in embedding model automatically (D7).
- arXiv formulas come from the authors' LaTeX source by default, with Mathpix as an option (D36, D40).
- Models that return 404 or answer as another model are hidden for 30 days, and GitHub Copilot connects only through the account (D59).
- Settings › This computer shows the library folder and its size and can move it (D32).

### App

- The UI moved to the mockup v24 design, and the 17 bugs found against the mockup are fixed (D5).
- Post-parity cleanup and small features (P0–P5, D25–D33) are done: unused CSS removed, search-plan strike-through, request counts, stored thinking level, proxy name, "Try" for keyless sources.
- Pre-P10 readiness is done in code: the packaged app finds its files, tools work when opened from the desktop, Windows CLIs start, a Linux fallback holds keys for the session, and cost estimates are shown.
- An open PDF viewer now loads the restored file after a file restore.
- A GitHub Actions workflow runs the quick tests and the web build on every push to main; it is informational and blocks nothing.
- The P9 upgrade check's 15 teardown errors are fixed (385b4511), and the arXiv source-archive test that used to fail now passes.
- Answers no longer overuse "It has been reported that…": the phrasebank is gone, and a live check on 16 Oct found no formula openings (D43).

### Code audit (16 Oct)

- GPT Astra (high) audited the code read-only and found five defects; all five are fixed, each with a test that fails without the fix, and Sol reviewed them in two rounds. A table run's completion and the next run of its chain are now one write, so a crash between them cannot stop the chain. Every answer, not only the fast path's, checks the question revision just before it is published. A Gemini answer with a tool part (a function call) is refused as an isolation violation. A PDF link whose host resolves to any non-public address (for example 100.64.0.0/10) is refused. Overlapping reloads of a research page never show an older view, and a failed newer reload falls back to the older one it held. Full pytest 15,763 passed; the browser test for the reloads passed, the full Playwright suite was not run.

## Latest live check (16 Oct)

One run per mode with gpt-5.6-luna on the DBR/VBF question, on a library copy.

- Quick (25/10) and Detailed (100/40) limits held; full text filled 10 of 10 slots in Quick but 24 of 40 in Detailed, because 48 of 72 candidates had no PDF.
- The model saw a median 41–46% of each read work's text chunks, and the second reading saw the same chunks as the first.
- Answers cited only 3 of 23 and 4 of 70 works in their input.

## Open work

### Claude code audit (16 Oct, not fixed yet)

- A second read-only audit by Claude (four areas Astra did not cover) found 15 defects, none fixed yet; the table with file, line and failure scenario is in `.local/audit-2026-10-16/claude-audit.md`. The most serious: a PDF link sent gzip twice over can take gigabytes of the server's memory before the size limit applies; figure rendering runs on untrusted PDFs inside the server with no size limit; one unexpected error in the late full-text step stops the worker, so no queued run starts until a restart; a failed D68 retry can drop the first call's cell value; follow-ups still read works the late full-text read excluded.

### Left over from the clean start

- The search stage can look finished while chain requests are still running, because those requests count toward screening.
- Test gaps: the Playwright rate-limit cases do not match each failed OpenAlex request to its own row, and the fast-answer flow has no pause/resume test.

### Answer coverage (grounding audit, 16 Oct)

A model-free check of the 8 stored answers found all 171 citation links sound: each anchor sits word for word in a passage of that answer's own input. The gap is coverage, not integrity (`.local/plans/grounding-audit-2026-10-16.md`).

1. The latest DBR/VBF answer cites 14 of 20 full-text works and none of 24 abstract-only works. Relevant works go uncited, for example "Light-weight depth-based routing" and the Q-learning DBR paper (both full text), and "Adaptive Holding time and DBR" (abstract only, though the question asks for holding-time formulas).
2. Target: every input work with a passage that answers the question is cited, or the answer says why it is left out. Not every input work: surveys, MAC and security papers are in the input too. Rough guess for this question: 20–25 such works against about 14 cited (not measured).
3. Possible causes, not measured: the answer length limit (9 Oct: 48→120 passages barely raised citations), abstracts that give no numbers or formulas, and claims tied to only one source each.
4. Next: measure it. For each uncited input work, say whether it had an answering passage, then find which cause applies.
5. Chain of Ideas–style idea generation waits until this is fixed, and it needs its own contract: premises cited, speculation marked as unsourced.

### Search (after P10)

1. In broad questions, known key papers are not near the top (battery_soh: 3 of 15 targets in the top 50), and the answer score does not measure this.
2. dbr_vbf is the weakest question (69–79): the answer misses aspects a human reviewer would cover, and Quick misses the key paper Maulana 2019.
3. Full text of paywalled papers cannot be read, so most engineering papers come in from the abstract.
4. The value of survey papers is not measured, and papers with "survey" in the title are dropped.
5. In Standard, 7 of 20 runs took over 5 minutes (cause not checked), Detailed citation accuracy was not re-measured after the fixes, and the sample is small (10 questions × 2).
6. The free OpenAlex daily quota runs out after about 20 researches (the app now stops sending once it is used up, D173), and the answer call sometimes times out (1 in 21 runs).
7. The full-text limits (10/20/40 works for Quick/Standard/Detailed) were never chosen by measurement; the 16 Oct check only showed they hold. Raising them is unlikely to help yet: Detailed filled 24 of 40 slots for lack of PDFs, and answers cite few of the works they already get. Measure after the answer-coverage work.

### Not measured (needs a real model or real use)

- Seed PDFs were measured only with the targets themselves as seeds, not with a real related paper the user has.
- Report quality: in the one scored real report (H9e) most measures were out of range; on 16 Oct two live reports finished after one resume each, but nobody scored them.
- Equations, lineage, kill-search finding the closest works, and crash recovery with real Codex; 5 of 18 report-edit actions; the owner's daily use.
- Most features above (follow-up changes, table and report changes, new model connections, Mathpix, data move) have not been tried with a real model or provider.
- Windows and Linux have not been run, the package has not been built with real PyInstaller, and OpenAI, Gemini and DeepSeek prices must be checked before release (P10 acceptance rows K1–K15).

### Platform

- Not measured: a second installed user, screen readers, capacity on a quiet machine, power loss and a full disk; older macOS, Intel, Linux and Windows are not supported.

### Code

- The re-extraction background reader is not tested in the matrix.
- UI: the sticky answer area in the queue grew to about 300 px at 1280×900, the selected tab may not scroll into view after a TR/EN switch, and report icon buttons on phones have no visible hint.
- The first answer draft often breaks citation-anchor rules and repair adds 1–2 minutes per answer; CI runs on every push but is not required, and parallel tests fail now and then. On 16 Oct the quick run gave 143 failed and 65 errors at machine load 150–215 (another session was running tests); the failing review tests pass alone (27/27). Re-run on a quiet machine with `-rfE` to get the list.

### Live findings (4–5 Oct)

- MDPI, SAGE and ScienceDirect PDFs return 403 from the ULAKBİM network; not rechecked on the fast path.

### Parked ideas (owner decides)

- Use Jev (the TypeSafe classifier) to rank which sources get full-text slots; speed, price and accuracy not measured.
- Fixed example questions (the home page only suggests questions from earlier answers), "this source was included in research X" hints, classifying why open-access PDFs return 403, a landing page (after P10), fast answers reading equations from arXiv source, more kill-search signals, and a warning when two queries share most terms.
