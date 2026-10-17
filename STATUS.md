# DEIXIS status

**Last updated:** 18 October 2026. Decisions are in [docs/decisions.md](docs/decisions.md); old D numbers point to the old log in Git (commit 26c8214).

## Now

The owner is checking the app by eye, and the problems they find get fixed in order. P10 (the macOS package) waits until that check is done.

İkinci tam metin okuması artık ilk okumanın görmediği bölümleri okuyor (D76); modelsiz tekrar oynatmada makalelerin gösterilen bölüm payı %32'den %65'e çıktı, canlı Luna kabul testi (17 Eki, aynı 16 makale) test edilebilen dört koşulu geçti: kapsam ×1,77, negatiflerde yeni dahil yok, kısa makaleler değişmedi, çağrı ve token aynı; ama ilk 12 parçanın kaçırdığı ana kanıtı yakalama amacı bu sette ölçülemedi ve dışlama zorlaştı (bir negatif kuyruğa düştü).

17 Ekim kalite işleri (kickoff 1–7) bitti; açık karar: rapor tablosu yalnız tam metni okunan kaynakları alıyor, cevap ise özetten okunanları da atıflıyor, bu yüzden az tam metinli sorularda (pil, yükseköğretim) rapor tek kaynağa dayanıyor — özet kaynaklar da tabloya girsin mi, sahip karar verecek.

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
- Citation snowballing (D91): rounds the person starts from chosen works (research ⋯ menu, citation map); backward and forward OpenAlex reads, abstract screening with lexical exclusion off, nothing included; up to 3 rounds. Model-free tests only.
- Built-in models on llama.cpp (D90, 17 Oct): a pinned GGUF catalog (embedding: Qwen3 0.6B/4B/8B, bge-m3; reranking: Qwen3 0.6B/4B/8B, bge-reranker-v2-m3) shown as cards in Search & ranking with a memory-based recommendation; the PyTorch runner is gone. Live on an M1 Pro with the 0.6B pair and synthetic texts: 250 titles embedded in 6.2 s (PyTorch 52 s), 100 reranked in 4.3 s warm (32 s), reranker memory steady at 1.6 GB. Retrieval quality, the larger models and Windows are not checked. Search & ranking also gained Cohere embeddings and Cohere, Jina and ZeroEntropy rerankers (D89, mocked tests only).
- Reranker on BioASQ (D88, 17 Oct, 100 questions, stored candidate lists, title + abstract): Qwen3 and Voyage rerank-3-lite both raise recall@50 from 0.545, by about +0.03 reranking the first 100 and about +0.06 reranking the first 200 (every interval above zero, none reaching the +0.10 bar). The pool default is now 4× the papers read; the reranker stays off until turned on. Only record order was measured, not full product runs or answers (`.local/rerank-trial-2026-10-17/qwen-voyage-results.md`).
- Verify Citations V1–V2 (D86, D96): a draft's citations and bibliography are read by code and resolved on OpenAlex; each cited work gets its text (your PDF, a stored or open-access PDF, else the abstract), every PDF goes through the identity check, and each citation gets a frozen set of 6 passages (keyword ranking), with a 200-pair cap and a cost preview. No model call yet; nothing tried on a real draft. V3–V5 (plan `.local/plans/verify-citations-plan.md`) are open.

- Kill search retrieval (D94, D95, D97; parked 18 Oct): decomposition no longer fails on Anthropic (null note, "protocol" check narrowed); the eight kept works are ranked by concept-level BM25, block coverage and co-mention instead of a provider round-robin; each provider returns one full page; backup names reach the search. Three frozen live checks on the DBR/VBF claims plus one out-of-domain claim: v3 kept 3/4 (C1) and 4/4 (C2) targets, up from 1/4 and 2/4, but the knee-osteoarthritis PRP vs hyaluronic acid claim kept 0/3, same as the old code, so the gate failed (`.local/killsearch-live-v3/RESULT.md`). The owner had the "Next steps" entry built anyway (D98, 18 Oct): a topics disclosure with "Write a claim about this topic", a "Search earlier work for a claim" row, and a summary under the box with counts from stored rows and the caveat that finding no match is not evidence of originality. Tuning against these claims has stopped; whether kill search finds prior work in general is not shown.

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
- A follow-up that asks for works outside the research can search for them (D92, 17 Oct): a "Search for new works" button (emphasized when the model says the question asks for new works) starts a run of its own under the same question, sends model-written terms through the same bounded transport, marks each found work new, already here or removed before, screens up to 40 new works at the abstract stage and includes nothing. The first search's counts stay apart in the funnel, PRISMA-S and the Method box. Tested with fake models and one browser check on synthetic records; the terms' quality and the new works' relevance are not measured.

### Evidence tables and reports

- A table cell gets a "Check the number" flag when its number appears in none of its quotes (D54).
- Report sections follow new writing rules (no synonym paraphrase, link sources, no simulation called an experiment), with two non-blocking warnings that check them (D51, D55).
- Report versions go up only when the person asks; the app's own updates show as V1.1 (D57).
- The model instructions were checked against the code with GPT Astra High: wrong or missing references were fixed (index terms, future-work citations, answer title length, follow-up second pass), and every instruction file is still in use.
- Report sections see every table cell, drop the lowest-priority column instead of rows when over budget, and are reviewed in 30k-token chunks (D58).
- A table opened from included sources adds a row when a source is included later (D63).
- A report section gets a second repair before the report pauses (D65).
- Table cells that fail their quote check no longer stop a report; they are retried once and otherwise marked not verified (D68).
- Reports work on the Anthropic API: the section schema no longer gets HTTP 400 (D93), and a repair may reword an insufficient-evidence reason to drop a banned word or meet the word budget, so section VI and index terms no longer loop to `section_failed` (D87). 17 Oct: five reports on the five evaluation questions, all valid.
- D68 cell retry measured on 7 live table fills with Sonnet 5.5 (17 Oct): 15 of 608 cells failed first, the older whole-call repair fixed 14, the D68 retry ran once and fixed it. Kept; no fix rate can be given from one case.

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

### Kill search (v3 live check failed on C3; Next steps entry built anyway, D98)

The Next steps entry is on main with model-free tests only; it was not tried on a live answer. Whether kill search finds prior work in general still needs a new, unseen claim set and a frozen live check.

- [ ] Query: the model's setting terms can miss how a target names the setting (Filardo 2015's abstract never says "knee osteoarthritis"); not found by any provider.
- [ ] Synonym counting: synonyms that are not abbreviations ("knee OA", "viscosupplementation") count as separate concepts, so records that pile them up outrank direct comparisons (Cerza 2012 OpenAlex #7 → kept rank 25; with the old 20-record window it would have been 6th).
- [ ] Window: OpenAlex and PubMed match Sánchez 2012 only past their first 100 records; it arrived only as a Semantic Scholar record without abstract (rank 737).
- [ ] UI wording "1000 records each" hides the per-provider windows; ranking text is hashed, not snapshotted.

### Left over from the clean start

- [ ] The search stage can look finished while chain requests still run, because they count toward screening.
- [ ] Playwright rate-limit cases do not match each failed OpenAlex request to its own row.
- [ ] The fast-answer flow has no pause/resume test.

### Answer coverage (`.local/plans/grounding-audit-2026-10-16.md`)

All 171 citation links in 8 stored answers are sound; the gap is coverage: answers leave relevant input works uncited.

- [x] Before/after run on one frozen answer input: done 17 Oct (D80 + D83, see Done).
- [ ] Every D83 run hit the 30-claim limit; 12–13 works per run are left out under `claim_limit`. Not measured on other questions.
- [ ] Chain of Ideas–style idea generation waits for this, with its own contract (premises cited, speculation marked unsourced).

### Consensus-style modes

- [ ] Citation snowballing (D91): first live round on a copy of the DBR/VBF research (17 Oct, Sonnet 5.5 medium, seeds: the 2023 VBF/DBR comparison and Xie 2010) ran cleanly (79 new, 51 model reads, 6 candidates, nothing included) but brought neither missed comparison: no seed links to Maulana 2019 or Hakim 2018 in OpenAlex. A second round from Hakim 2018 forward (pending, never screened; chosen after seeing that Maulana cites it) brought Maulana 2019 back as new and both model reads made it a candidate (6 citing works, 4 new, nothing included). So a known link goes through, but the result depends on choosing the right seed; two rounds are not quality evidence. Seed-suggestion measurement (17 Oct, code only, no model): a title rule (both question blocks in the title) puts Hakim 2nd of 868 pending works, and one hop from its top 10 brings Maulana back (only through Hakim; no other new DBR/VBF comparison). The larger gap is screening order: the read window took 50 of 877 works, and all four known direct comparisons in the research (Hakim, Memon 2018, which is in the research after all, and two more) sit at positions 152 to 602, never screened. Voyage reranking of all 877 puts all four in the first 50 (Memon 1st), but the app reranks only the first 200 (N × 4). A new run on a copy with the pool at 400 (pool_factor 8, set in the copy's database; the UI caps it at 4) read Memon 1st and included it, and read Hakim 3rd (both model reads: candidate; no open full text). Memon was 247th before reranking, outside a 200 pool. One run, no 200-pool control, no answer generated. Next: compare pool 200 and 400 on another question before raising the cap; seed suggestion waits. Playwright case: `apps/web/e2e/snowball.spec.ts` (SYNTHETIC `[snowball]` fixture: one round from the menu, card counts match the stored summary, nothing included, a second round offered; workflow behaviour, not live data). Notes: `.local/snowball-live-2026-10-18/`, `.local/seed-suggest-2026-10-18/`.
- [ ] Snowballing results depend entirely on the chosen seed: round 1 from two obvious seeds (an included comparison, Xie 2010) reached neither target; round 2 reached Maulana 2019 only because we picked Hakim 2018, which a person would not choose (pending, never screened). The app gives no help choosing seeds; whether it should suggest them waits for the read-window fix above.
- [ ] Reverse citation search: paste a statement and get works whose passages support or challenge it; waits for Verify Citations V3, whose claim-vs-passage step it reuses.
- [ ] Gap finder (not designed): from a research's included works, list topics, settings or comparisons the read passages leave open, each with the passages that show the gap and the reading depth it rests on. A gap is a lead to check, not proof that no work exists (no search result proves novelty); it would hand a gap to kill search to look for earlier work. Overlaps with report Section VI gap candidates, whose reading depth is not stored yet (Code audit leftovers).

### Search (after P10)

- [ ] Broad questions: known key papers are not near the top (battery_soh: 3 of 15 targets in the top 50), and the answer score does not measure it.
- [ ] dbr_vbf is the weakest question (69–79); Quick misses the key paper Maulana 2019.
- [ ] Paywalled full text cannot be read, so most engineering papers come in from the abstract.
- [x] Survey papers as citation-chain sources: measured offline 17 Oct on 10 runs, no checkable target reachable only through survey references; as extra ranking seeds recall@50 fell 57 → 53. Not adopted.
- [x] Joint-signal weight ×2/×3 in the 21–500 ranking: 14 runs, J3 +6 relevant in the top 50, all from DBR/VBF; it loses on uwsn and clinical_imaging. Not adopted (17 Oct). Maulana 2019 is found but ranks ~147.
- [ ] Standard: 7 of 20 runs took over 5 minutes (cause not checked); Detailed citation accuracy not re-measured after the fixes.
- [ ] Free OpenAlex daily quota runs out after about 20 researches (D173 stops sending); the answer call times out in about 1 of 21 runs.
- [ ] Full-text limits (10/20/40) were never chosen by measurement; measure after the answer-coverage work.
- [ ] BioASQ: 107 of 480 gold papers never retrieved, all in OpenAlex. Semantic search is capped at 50 records (`semantic_top`); test whether a deeper read closes the gap.
- [ ] LitSearch (597 ML/NLP queries): tooling ready (9c0fd3dd), not run. Next: `litsearch_run.py prepare --n 50`, then OpenAlex and DEIXIS runs on a temp data folder and a port other than 8765.

### Not measured (needs a real model or real use)

- [x] Seed PDF with a real related paper (Kulla & Elmazi 2023, owner's library), 17 Oct: same 3 of 4 targets given and cited as without seed; only order improved (Hakim 2018 141 → 83). Found: an uploaded seed that is already a library record is read twice; that run's table_columns proposed 9 columns (bound now in the Anthropic schema description, D93).
- [ ] Report quality: evaluation set of five fixed questions and a 6-criterion rubric (`.local/plans/report-eval-set.md`); 17 Oct reports scored by GPT-6.1 Sol high (model score, not a human score): totals 15–20 of 30, overall 2–6 of 10; weakest writing (2 everywhere) and coverage on battery_soh and higher_ed_ai, whose tables hold one full-text include each. Owner score not taken.
- [ ] Evidence table rows are full-text includes only, while the answer cites abstract-read works: with little full text (battery_soh, higher_ed_ai) the report rests on one source. Product decision.
- [ ] review_mode "off" in the create body still ran answer_review on all five 17 Oct researches; not looked into.
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

- [ ] Fixed example questions on the home page and "included in research X" hints.
- [ ] Classify why open-access PDFs return 403.
- [ ] Landing page (after P10).
- [ ] Fast answers read equations from arXiv source; more kill-search signals; warn when two queries share most terms.
