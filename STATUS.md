# DEIXIS status

**Last updated:** 17 October 2026. Decisions are in [docs/decisions.md](docs/decisions.md); old D numbers point to the old log in Git (commit 26c8214).

## Now

The owner is checking the app by eye, and the problems they find get fixed in order. P10 (the macOS package) waits until that check is done.

İkinci tam metin okuması artık ilk okumanın görmediği bölümleri okuyor (D76); modelsiz tekrar oynatmada makalelerin gösterilen bölüm payı %32'den %65'e çıktı, canlı Luna kabul testi (17 Eki, aynı 16 makale) test edilebilen dört koşulu geçti: kapsam ×1,77, negatiflerde yeni dahil yok, kısa makaleler değişmedi, çağrı ve token aynı; ama ilk 12 parçanın kaçırdığı ana kanıtı yakalama amacı bu sette ölçülemedi ve dışlama zorlaştı (bir negatif kuyruğa düştü).

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
- Every work given to an answer is cited or left out with a reason (D80). One answer call left the reason list empty (29 of 41 works without a reason), so a valid answer with unaccounted works gets one coverage rewrite that keeps its claims (D83). Live on the DBR/VBF question, 3 runs: 0 unaccounted, cited works 12 → 27–28, 12–13 of 13 content-bearing works cited and the rest left out with a confirmed reason; the answer takes about 100 s instead of 22 s and the rewrite's output is 13–15k tokens against a 16k limit (`.local/plans/evidence-ledger-acceptance-2026-10-17.md`).
- A full text's first answer-input slot goes to its most result-dense passage, formula passages keep the second, reference lists go last (D84). On the DBR/VBF copy, content-bearing works in the input rose 13 → 15 of 41; with D83, 15/15 were cited in two of three runs (8/15 in the third, where a repair wrote the ledger). Tuned on one research; outcome terms match only as the vocabulary writes them.

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

- The Anthropic API connection streams its answer, so a call may write up to 64,000 tokens, thinking included; the whole turn is still bounded by 300 s (D85). Before it, three answer calls on 17 Oct stopped at the old 16,000 limit and two of those runs paused with no answer; in the three runs after it, a 19,240-token repair completed.
- API keys, including Zotero and TypeSafe, live in the system keychain, and `.env` keys move there on startup (D19, D29).
- Settings › Models has one card per company with both account sign-in and API key, plus new connections such as Claude and OpenAI API, OpenRouter and MiMo (D20–D24, D34).
- Ollama and LM Studio cards install the app, start the server and download recommended models, and local models finish a full Quick research (qwen3.5:9b, about 32 min) (D39).
- Users without a key get the downloaded built-in embedding model automatically (D7).
- arXiv formulas come from the authors' LaTeX source by default, with Mathpix as an option (D36, D40).
- Models that return 404 or answer as another model are hidden for 30 days, and GitHub Copilot connects only through the account (D59).
- Settings › This computer shows the library folder and its size and can move it (D32).
- Settings › Usage shows, per model connection, this month's estimated spend (API key) or the subscription's own 5-hour and weekly limit (Codex live, Claude Code from the last call) instead of call counts (D78).

### App

- The UI moved to the mockup v24 design, and the 17 bugs found against the mockup are fixed (D5).
- Mockup v25 (D77): the question shows its scope as a chip, the four evidence counts sit in one strip, and each run phase has a ringed icon on a rail with its details in a panel. The citation line no longer says "N of N" (only located anchors are stored), and the chain rows say "kept after the term filter". The mockup parity check and the mockup itself are removed (D79); the shipped screens are the reference.
- Run card (D82): each run is one card; the step panels show the two abstract readings that disagreed, why each passed work was not read in full text (with Add PDFs), and how each citation anchor matched; a "No full text" badge marks a run that read none. Not tried on a live run yet.
- Post-parity cleanup and small features (P0–P5, D25–D33) are done: unused CSS removed, search-plan strike-through, request counts, stored thinking level, proxy name, "Try" for keyless sources.
- Pre-P10 readiness is done in code: the packaged app finds its files, tools work when opened from the desktop, Windows CLIs start, a Linux fallback holds keys for the session, and cost estimates are shown.
- An open PDF viewer now loads the restored file after a file restore.
- A GitHub Actions workflow runs the full test suite, split over four machines (4–8 min instead of 19), and the web build on every push to main; it is informational and blocks nothing.
- Tests take less of the Mac (17 Oct): the quick run uses 4 workers and leaves out the ~2,000 tests of 0.2 s or more (about 2 min and 316 CPU-seconds, down from 1,250), and `pytest --testmon tests` reruns only the tests that touch changed Python code. Compiled files are cached outside the repository, test apps share FastAPI's type adapters, and record matching caches its title work. Measured under heavy load from other sessions, not on a quiet machine.
- Two CI failures fixed (17 Oct): `test_connector_dispatch` failed when a background thread left by an earlier test spun on the test clock's fake 60 s sleep (the fake clock now applies only to its own thread), and the static `os.replace` guard now allows `models/quota.py`, which saves the last Claude Code limit reading (D78).
- The P9 upgrade check's 15 teardown errors are fixed (385b4511), and the arXiv source-archive test that used to fail now passes.
- Answers no longer overuse "It has been reported that…": the phrasebank is gone, and a live check on 16 Oct found no formula openings (D43).

### Code audit (16–17 Oct)

Three read-only audits (GPT Astra twice, Claude once) found 33 defects in areas such as chain crash safety, PDF and URL limits, keychain handling, background workers and stale question revisions. 27 are fixed, each with a test that fails without the fix and a Sol review; the six low items left are under Open work.

## Latest live check (16 Oct)

One run per mode with gpt-5.6-luna on the DBR/VBF question, on a library copy.

- Quick (25/10) and Detailed (100/40) limits held; full text filled 10 of 10 slots in Quick but 24 of 40 in Detailed, because 48 of 72 candidates had no PDF.
- The model saw a median 41–46% of each read work's text chunks, and the second reading saw the same chunks as the first.
- Answers cited only 3 of 23 and 4 of 70 works in their input.

## Open work

### Code audit leftovers (low)

- [ ] Stale-cell recheck estimate stops at 25 sources.
- [ ] Study-table chain can run out of rounds after a failed source without saying so.
- [ ] Section VI gap candidates need a reading depth that is never stored.
- [ ] Follow-up context can take an answer of an earlier question revision; follow-up table values include removed sources.
- [ ] PDF child process has no memory limit on Windows (P10 Job Object item in `.local/plans/p10-plan.md`).
- [ ] Not checked: a kill search may spend two of its eight slots on a preprint and its published version when the library has not joined them.

### Left over from the clean start

- [ ] The search stage can look finished while chain requests still run, because they count toward screening.
- [ ] Playwright rate-limit cases do not match each failed OpenAlex request to its own row.
- [ ] The fast-answer flow has no pause/resume test.

### Answer coverage (`.local/plans/grounding-audit-2026-10-16.md`)

All 171 citation links in 8 stored answers are sound; the gap is coverage: answers leave relevant input works uncited.

- [x] Before/after run on one frozen answer input: done 17 Oct (D80 + D83, see Done).
- [ ] Every D83 run hit the 30-claim limit; 12–13 works per run are left out under `claim_limit`. Not measured on other questions.
- [ ] Chain of Ideas–style idea generation waits for this, with its own contract (premises cited, speculation marked unsourced).

### Search (after P10)

- [ ] Broad questions: known key papers are not near the top (battery_soh: 3 of 15 targets in the top 50), and the answer score does not measure it.
- [ ] dbr_vbf is the weakest question (69–79); Quick misses the key paper Maulana 2019.
- [ ] Paywalled full text cannot be read, so most engineering papers come in from the abstract.
- [ ] Survey papers are dropped by title; their value is not measured.
- [ ] Standard: 7 of 20 runs took over 5 minutes (cause not checked); Detailed citation accuracy not re-measured after the fixes.
- [ ] Free OpenAlex daily quota runs out after about 20 researches (D173 stops sending); the answer call times out in about 1 of 21 runs.
- [ ] Full-text limits (10/20/40) were never chosen by measurement; measure after the answer-coverage work.
- [ ] BioASQ: 107 of 480 gold papers never retrieved, all in OpenAlex. Semantic search is capped at 50 records (`semantic_top`); test whether a deeper read closes the gap.
- [ ] LitSearch (597 ML/NLP queries): tooling ready (9c0fd3dd), not run. Next: `litsearch_run.py prepare --n 50`, then OpenAlex and DEIXIS runs on a temp data folder and a port other than 8765.

### Not measured (needs a real model or real use)

- [ ] Seed PDFs with a real related paper, not the targets themselves.
- [ ] Report quality: the one scored report (H9e) was mostly out of range; two 16 Oct live reports were never scored.
- [ ] Equations, lineage, kill search, crash recovery with real Codex, 5 of 18 report-edit actions, and the owner's daily use.
- [ ] Follow-up, table and report changes, new model connections, Mathpix and data move with a real model or provider.
- [ ] Windows, Linux and a real PyInstaller build; OpenAI, Gemini and DeepSeek prices before release (P10 rows K1–K15).

### Platform

- [ ] Not measured: a second installed user, screen readers, a quiet-machine capacity run, power loss and a full disk.

### Code

- [ ] The re-extraction background reader is not tested in the matrix.
- [ ] UI: the sticky answer area grew to about 300 px at 1280×900; the selected tab may not scroll into view after a TR/EN switch; report icon buttons on phones have no hint.
- [ ] The first answer draft often breaks anchor rules; repair adds 1–2 minutes per answer.
- [ ] Parallel tests fail now and then under load; re-run on a quiet machine with `-rfE`. `tests/app/test_reference_import_parser.py` fails 3 tests under full serial `--testmon`, passes alone.

### Live findings (4–5 Oct)

- [ ] MDPI, SAGE and ScienceDirect PDFs return 403 from the ULAKBİM network; not rechecked on the fast path.

### Parked ideas (owner decides)

- [ ] Rank full-text slots with Jev (the TypeSafe classifier); speed, price and accuracy not measured.
- [ ] Fixed example questions on the home page and "included in research X" hints.
- [ ] Classify why open-access PDFs return 403.
- [ ] Landing page (after P10).
- [ ] Fast answers read equations from arXiv source; more kill-search signals; warn when two queries share most terms.
