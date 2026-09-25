# Task: SW slice 22: equations from the arXiv LaTeX source

**Run this prompt only when row 22 of `docs/product/sw-status.md` names A1, B1, C1, D3, E1 and F1** (its status reads
`… A1, B1, C1, D3, E1, F1 önerildiği gibi …`). If row 22 names a different answer to any of A–F, or none, stop at once
and change nothing.

Repo: `/Users/huguryildiz/Documents/GitHub/DEIXIS`, branch `main`, main checkout. The plan is
`docs/product/sw-slice22-arxiv-latex-source.md` **as committed**: find the commit that last changed it with
`git log -1 --format=%H -- docs/product/sw-slice22-arxiv-latex-source.md` and check that
`git status --porcelain docs/product/sw-slice22-arxiv-latex-source.md docs/product/sw-slice22-prompt.md` prints nothing.
If the plan has no commit, or has uncommitted changes, stop and change nothing. Write that hash in your final message.
Do not pull, fetch or change branches to get it. The plan is the only source of truth for this slice. Where it
deliberately departs from SW10 (its section "SW10'dan sapmalar": prose not taken from the source; Marker's page selection
not narrowed and no page taken away from Marker; inline math not taken from the source; the route running only without
Marker; the order constraint that never overrules the letters; not running inside the full-text retrieval and reading
runs), the plan wins over `docs/README.md`'s rule that the review's text holds. Build decisions 1–9 and tasks 1–10 under
A1, B1, C1, D3, E1, F1. The measurement scripts in `.local/sw-slice22-plan-2026-09-25/` (`match_equations.py`,
`match_r2.py`, `foreign_words.py`, `fetch_sources.py`, `katex_check2.cjs`, `migration/draft_0054_passages.sql`) are the
prototype the plan measured; read them, but write the product code afresh under the plan's names and rules. List every
place where you used your own judgement.

## Rules

1. **Git: you never commit.** Do not run `git commit`, `git push`, `git pull`, `git fetch`, `git stash`, `git reset`,
   `git checkout`/`git switch` of another ref, `git rebase` or `git merge`, and create no branch. Leave every change
   uncommitted in the working tree; the coordinator reviews the diff and makes the single commit after code review.
   Existing unrelated working-tree changes stay untouched: `TODO.md`, `.vscode/`, `scripts/local_index.py` and anything
   else that is not the slice's. `git add` nothing. In your final message list every file you created or changed (from
   `git status --porcelain`, minus the pre-existing ones above).
2. **What writes.** Only with `DEIXIS_ARXIV_SOURCE=auto` (default `off`, F1), only on POSIX (`fcntl`; off on Windows,
   as in slice 21), only while Marker is neither installed nor installing, checked again with no `await` right before the
   write, and only for a PDF whose current extraction does not carry `+marker-` (D3, C1): the equation reading writes a new extraction
   under D45's rule through `store.reextract_asset`, with version `<text layer>[+ocr-…]+arxiv-latex-v1` (never combined
   with `+marker-`), chunks labelled `text_source = 'latex_source'` only when a placed `$$…$$ (n)` block lies inside the
   chunk's range, both in one offset space (`pdf.normalize_page_text`, the normalisation `chunk_page` already applies, on
   the page text after `remove_download_notices`), and the `source` block of `asset_extractions.math_json` with the
   placed blocks' offsets in that space; the source
   file goes to `<data dir>/arxiv-sources/<id>v<N>.src` through a `.part` file, `fsync` and `os.replace`, and only then one
   row per arXiv version to the new table `arxiv_sources`. Migration `0054_arxiv_latex_source.sql` is the only migration:
   it rebuilds `passages` from 0053's own DDL with only the `text_source` CHECK widened by `'latex_source'` (every column
   and `rowid` copied by an explicit column list; the `passages_source` index, the `passages_fts_insert` and
   `passages_no_update` triggers recreated; every trigger or view elsewhere that refers to `passages`, among them
   `cell_evidence_same_source`, dropped before and recreated verbatim after; `-- deixis:foreign-keys-off`) and creates
   `arxiv_sources` and `asset_arxiv_versions`. With the flag `off` no source is requested and no PDF extraction changes.
   Nothing is extracted from an archive to disk.
3. **Unchanged:** every contract except the ones the plan names (`text_source` in the StepInput schema;
   `equation_origin.text_source` in `report-section-draft.schema.json`, whose version becomes
   `deixis.report_section_draft.v2`; the new `equation_origin` check in `_check_report_section`: the passage is in the
   StepInput, is among the claim's own `passage_ids`, and its `text_source` equals the passage's). Under B1,
   `skill_package_hash` changes from `sha256:7d4e238c3e9feebd451c77fb997aff717a3617008bd4165be56f9fba46bf6fca` because
   `references/source-grounded-answer.md` and `references/evidence-table.md` gain the plan's `latex_source` paragraph;
   write the new hash into D104. Also unchanged: the whole Marker path while Marker is installed (D52, D54, D62,
   `check_equations`, page selection; D3), `answer_version` (D48, slice 18b), the retrieval, reading and discovery runs
   (D83, D85, D98; E1), `pyproject.toml` and `uv.lock` (no new dependency), the text-layer page text of an extraction that
   places nothing (byte for byte), and Marker-read PDFs (C1: never read by the route, even after Marker is removed).
4. **A gain, never a requirement.** No outcome of the route pauses or stops a run: a missing, refused, waiting,
   permanently absent, unreadable or unmatched source, nothing placed, a D45 rejection and `RunInProgress` all finish the
   `read_equations` step `succeeded` with the state in its output. A run tries a PDF's source at most once. A placement
   that does not pass the plan's decision 4 is never written. The source of another version, or for a record that is not
   the same preprint version (decision 1's table), is never used. Nothing is attached to another record (D4).
5. **Words.** "matched to the page by its number", "the authors' LaTeX source", "arXiv source (v2)". No text says
   "verified", "exact", "reliable" or "correct" of a source equation, and no text claims a speed gain. Downloaded,
   matched (passed the threshold) and placed are separate states and separate counts. The passage notice names the
   equation numbers of that chunk and says the rest of the passage is the PDF's own text.
6. **Tests** use no network and no real Marker: `httpx.MockTransport`, archives built in memory with `tarfile` / `gzip`,
   synthetic PDFs built with PyMuPDF, the existing fake Marker reader, a fake clock. In every new test module add an
   autouse guard that fails the test on any `httpx` request not served by a mock transport and on any `socket.connect`
   to a non-loopback address. Claim only that the new tests make no network request; do not claim it for the existing
   suite. Existing pytest tests must pass unchanged with the flag `off` and with Marker installed, except the fixtures and
   hash tests B1 changes by design and report-section tests that the new `equation_origin` check changes (list each); if
   another cannot pass, stop and write why into row 22. A Playwright scenario may gain assertions; none may lose one. Every
   decision is fixed by a test (the plan's tasks 1–8 name them, including crash, cancel, concurrent fetch of one version,
   two processes fetching different versions with server-observed arrivals 3 s apart, D45 rejection, flag on→off→on,
   Marker installed later, Marker becoming available mid-reading (both race orders), a second connection changing the
   record or the current extraction just before the guarded write, the crash between inspection and write, conflicting
   record ids, 1 MB of stderr before stdout, the whitespace offset test and `equation_origin_not_cited`).
7. **Port 8765 and the product database are off limits.** Acceptance runs on a copy of the live library made with
   SQLite's backup API and migrated to 0054 under the session's scratch directory, never on the original (open it
   read-only), with a scratch `DEIXIS_DATA_DIR` into whose `arxiv-sources/` the plan's 53 files from
   `.local/sw-slice22-plan-2026-09-25/src/` are copied. The one network access allowed is acceptance (d): three fetches
   from `arxiv.org` through the product's own path, 3 s apart. No request carries the user's e-mail or any identity.
8. **Python:** `PYTHONPATH=backend:. uv run ...`, native arm64. The known unrelated failure is
   `tests/test_documents.py::test_extraction_is_stopped_when_it_exceeds_the_memory_limit`.
9. **UI:** read `.impeccable.md` before touching `apps/web`; strings go through `i18n.ts` / `labels.ts` (Turkish too).
   Verify the source row, the passage notice, the rendered equation and the citation badge yourself with a screenshot at
   desktop and phone width.

## Build

Tasks 1–10 of the plan, in order:

1. `documents/arxiv_source.py`, the archive (decision 3), run in its own subprocess `python -m
   deixis.documents.arxiv_source` started with `asyncio.create_subprocess_exec` (1 GB memory watch in the pattern of
   `pdf.py:198-210`; the parent drains stdout and stderr concurrently in two tasks so a full pipe never stalls the child,
   reads stdout in pieces and kills the child the moment it passes 5 MB, reads stderr to the end but keeps only its last
   4,000 characters, and kills it after 60 s, cancelling both tasks; test: a child writing 1 MB to stderr before any stdout
   finishes well inside the limit; any of these makes `content = 'unreadable'`): reading in memory only (regular files only; links, devices and FIFOs
   skipped; member names never used as paths); the gzip stream through a counting reader, at most 64 MB unpacked; at most
   1,000 members; one text member at most 5 MB and all text members at most 5 MB; else `too_large`; `pdf_only`, `no_tex`,
   `unreadable`; the main file (the one with `\begin{document}`, the longest if several), `\input` / `\include` /
   `\subfile` inlined to depth 5, comments stripped; macros from `\newcommand`, `\renewcommand`, `\providecommand`
   (optional default argument), `\def` (`#n` arguments) and `\DeclareMathOperator`, the archive's `.sty` / `.def`
   included, expanded to depth 8, at most 20,000 expander calls per paper (`macro_limit` drops only the group that hits
   it), a group over 4,000 characters after expansion not placed (`too_long`); groups as the plan lists, with the
   "continues after its number" mark; the cleanup and the seven-rule rewrite table; `&` or `\\` wrapped in `aligned`; a
   group with `\ref`, `\eqref`, `\pageref` or `\cite` (marked before cleanup) not placed; `scripts/katex_commands.mjs`
   writes `backend/deixis/documents/katex_commands.json` from the web app's KaTeX 0.16.47 (with its version), and a group
   with a command or environment outside it is not placed (`katex_unknown`).
2. Version and fetch (decisions 1, 2): the file's own arXiv version from `retrieved_from` and the page-1/2 stamp; decision
   1's table in order (`version_conflict`, `no_version`, `record_identity_conflict` (permanent, no request, never retried)
   when the record's DOI, `landing_url` and `oa_pdf_url` carry different arXiv ids, `record_identity_unknown` when they
   carry none, `record_version_conflict` for another arXiv id or any record label other than
   `arXiv vN` with the same N or `submittedVersion`, `version_mismatch` from `Content-Disposition`), the record's ids and label read
   again inside the write's own transaction by task 5's guard (`record_version_changed`); `Settings.arxiv_source` (`DEIXIS_ARXIV_SOURCE`, `off`
   | `auto`, default `off` in the dataclass and in `load_settings`); `fetch.fetch_file(url, media_types)` sharing
   `fetch_pdf`'s address checks, pinned connection, redirects, 30 MB and 30 s limits, User-Agent and `host_gate`,
   accepting `application/gzip` and `application/pdf` only; the address `https://arxiv.org/e-print/<id>v<N>` (never
   `export.arxiv.org`); HTTP requests at least 3 s apart as the server sees them, across every process using the same
   data directory, **every redirect hop counting as a request** (`fetch_file` calls the route's gate before and after
   each hop, `fetch_pdf` does not; the lock is held across all hops of one fetch, the wait and both stamps are per hop): an exclusive `fcntl.flock` on `<data dir>/arxiv-sources/.rate.lock` tried with `LOCK_EX | LOCK_NB` and
   `await asyncio.sleep(0.1)` between tries (no `asyncio.to_thread`, so a cancelled wait never acquires the lock later;
   the pattern of `local_embedding_service.py:48-76`), waited for at most 120 s, one budget: a single `asyncio.timeout(120)` around acquiring the in-process per-version
   `asyncio.Lock`, the per-version `<key>.lock` and this lock (then no request, no row, no attempt
   counted, step output `rate_gate_busy`, state stays `pending`), held for the whole request and released with the file
   descriptor in `finally`, also on cancellation and timeout; `.rate` holds `{"started_at", "ended_at"}`: under the lock
   wait with `asyncio.sleep` until `ended_at + 3 s`, or `started_at + 33 s` when `ended_at` is empty (a crashed or
   cancelled previous request), never more than 33 s; write `{"started_at": now, "ended_at": null}` durably (temp file,
   `fsync`, `os.replace`) **before** sending; write `ended_at` the same way in `finally`; the whole fetch (address check,
   every redirect, the body read and the 3 s waits between hops; not the wait before the first hop) inside one
   `asyncio.timeout(30)` in `fetch_file`'s path only (`fetch_pdf` unchanged),
   expiry → `not_settled`; the per-version `<key>.lock` taken the same way; tests with a local server recording arrival
   times: two processes, first reply delayed 2 s; the first process `SIGKILL`ed while its request is at the server;
   the first fetch task cancelled while its request is at the server; a task cancelled while waiting for the lock never
   holds it; a slow body with four redirects ends at 30 s; an `/e-print/` → `/src/` redirect, with the process killed between
   the two hops; server-seen arrivals at least 3 s apart in every case, redirect hops included
   (other data directories and the arXiv search provider are outside this count; say so, claim nothing more); `status`
   (download: `downloaded`, `version_mismatch`, `too_large`, `unreadable`, `not_settled`) and `content` (inspection:
   `tex`, `pdf_only`, `no_tex`, `too_large`, `unreadable`) as separate columns with decision 2's transition table, 403 as
   `not_settled`; the source used only when `downloaded` and `tex`; per-version `asyncio.Lock` plus `fcntl.flock` on
   `<key>.lock`; the row re-read under the lock; only after both locks are held and the first rate wait is over, just before the first HTTP
   request (the gate's first "before" call), a normal fetch attempt writes `attempts` + 1, the repair attempt `repairs`
   1 → 2 with `attempts` unchanged, `last_attempt_at` in both, so a budget timeout counts nothing; bytes →
   sha256 → `.part-<pid>` → `fsync` → `os.replace` → row; sha256 checked on every read (missing or wrong, first time: `not_settled`,
   `repairs` = 1, an `arxiv_source_corrupt` event; the repair is one extra fetch attempt per version, separate from the
   three normal attempts: sent regardless of `attempts`, never incrementing it, setting `repairs` = 2; `attempts` counts
   normal fetch attempts only, so at most 3 + 1 fetch attempts per version, each of which may be several HTTP requests
   with its redirects (at most 6), every one through the rate gate; the worst wait per PDF is 120 s (both locks) + 33 s
   (first rate wait) + 30 s (the fetch) = 183 s, the archive subprocess's 60 s apart; a second corruption: permanent `unreadable`
   (`cache_corrupt`); the person's retry resets `attempts` and `repairs`; `repairs INTEGER NOT NULL DEFAULT 0` in `arxiv_sources`; tested after a third-attempt
   download); `.part` files older than one hour removed at service start;
   permanent states never retried, `not_settled` (timeout, lost connection, 406, 429, 5xx) at most
   `SOURCE_MAX_ATTEMPTS = 3` times, `RETRY_AFTER` apart, then permanent. `enrich_source` (`store.py:1206-1218`, the only path that changes a record id
   field after insert, filling an empty `landing_url`) recomputes, in its own transaction and without opening a PDF, the
   eligibility of each non-removed PDF of that source version that has a row; a refusal on a PDF whose current extraction
   is `+arxiv-latex-v1` withdraws that reading in the same transaction, in this order because of the one-current index
   (`0027_asset_extractions.sql:24`): the route's row `superseded` first, then the row current just before it `current`,
   with `source_assets.extraction_version`, `extraction_status`, `extraction_error` and `page_count` set together from
   that row (the fields `store.py:1405` writes), tested, passages kept and shadowed as
   `text_superseded`, an `arxiv_source_withdrawn` event); tests both ways (`record_identity_unknown` → `eligible` then
   read; a read PDF whose new `landing_url` names another arXiv id → `record_identity_conflict`, reading withdrawn, its
   passages absent from search and StepInput; the same id changes nothing). The eligibility is written once per PDF into
   `asset_arxiv_versions`, so `equation_state` never opens a PDF.
3. Matching (decision 4): lines from `pdf.py`'s own `_blocks` (same flags and filters), each also carrying its
   `inline_math.line_text` masked text and its box; number lines; prose lines (`PROSE_WORDS = 3`); candidate regions
   (`MAX_REGION_LINES = 12`); letter multisets through `math_reader.latex_letters` / `_letters`; the order-constrained
   assignment over the whole PDF maximising the sum of `F1 − 0.5`; the window margin and the paper margin; passes when
   recall ≥ `MIN_RECALL = 0.90` and (paper margin ≥ `MIN_MARGIN = 0.20`, or window margin ≥ 0.20 and paper margin ≥ 0);
   region trimming to the shortest run reaching the group's best recall, then absorbing the vertically overlapping,
   non-prose, non-number lines of the same equation back to the previous number line; `foreign_text`;
   `continues_after_number`; the constants and every not-placed reason written into `math_json.source`.
4. Placement (decision 5): the extraction subprocess takes the placements as a JSON file of `(page, block, line)` keys
   and LaTeX and replaces the trimmed-and-absorbed region's lines with `$$\n<latex>\n$$ (n)` at the number line before
   `_page_text` joins them; a region with a line that never reaches the page text is not placed; each placed block's page
   offsets recorded in the `normalize_page_text` space after `remove_download_notices`, a block not found exactly once
   refusing the reading (`offsets_unresolved`); `chunk_page` calling `normalize_page_text` with byte-identical output; the
   plan's whitespace test; `chunk_page` does not cut inside a `$$…$$` block in `+arxiv-latex-v1` extractions only; no placement
   on table-caption or OCR pages. No page is removed from Marker's selection (D3).
5. `workflow/equations.py` and `flow.py` (decision 6): `target_version` and `equation_state` by decision 6's four
   precedence rules in order (Marker present or installing → today's code unchanged; no Marker and a current
   `+arxiv-latex-v1` → `read`; rule 3's table; else today's), all from stored rows; rule 3's table includes `downloaded` + `tex`
   with no extraction row for the source target yet (crash between inspection and write) as `pending`, re-matched from
   the stored file with no request; **the last-write guard runs inside the write's transaction:** `store.reextract_asset`
   (`store.py:1353`) gains an optional `guard(conn)` called right after `with transaction(self.conn)` opens
   (`store.py:1391`, `BEGIN IMMEDIATE` at `db.py:47`) and before the first write; the route's guard re-reads the
   `source_versions` row and re-applies decision 1's id and label rows, checks `source_assets.extraction_version` equals
   the value at reading start and has no `+marker-`, and checks the flag is `auto` and Marker neither `available()` nor
   `installing()`; the guard first checks `source_assets.removed_at IS NULL` (today checked before the transaction, `store.py:1362`;
   removal is its own transaction, `store.py:1491-1499`), refusal `asset_removed` writes nothing; on a refusal no passage
   is written and the current extraction version is unchanged, it returns
   `{"outcome": "refused", "reason": …}`: a changed record updates the `asset_arxiv_versions` row and adds a passage-less
   reject row (`record_version_changed`) in the same transaction, a changed extraction writes nothing (`superseded`),
   Marker writes nothing (`superseded_by_marker`); calls without `guard` behave as today; test with a second connection in
   another process removing the PDF, changing the record or changing the extraction just before the guard, and both
   Marker race orders; rule 3 covers eligibility refusals too: `no_version`, `version_conflict`,
   `record_identity_unknown`, `record_identity_conflict` and `record_version_conflict` show `no_source` with the value as
   reason, never `pending`, and neither the background reader nor the run step looks at them; view test for each with no
   Marker and flag `auto` (and today's `pending` with the flag `off`); `run_forever` and `next_asset` serve route-target PDFs while Marker is not installed and
   the flag is `auto`; `_read_equations` opens its step for route-target PDFs without Marker and never pauses for a route
   outcome; `_write_extraction` takes the label per chunk; the views' rejected-extraction field leaves out
   `+arxiv-latex-` versions, which are reported as the equation state; C1; flag on→off keeps stored readings shown as
   `read`; Marker installed later reads the PDF through today's path; not called from the retrieval, reading or discovery
   runs (E1).
6. Migration `0054_arxiv_latex_source.sql` (rule 2; take the DDL and every dependent trigger or view from a copy migrated
   to 0053), the StepInput and report-section-draft schemas (`v2`), `domain/contracts.py` (the version and the
   `equation_origin` check: passage in the StepInput, `unknown_passage_id`; passage in the claim's own `passage_ids`,
   `equation_origin_not_cited`; `text_source` equal to that passage's, `equation_origin_mismatch`; for every value, with
   a test for each of the three codes including a draft whose `equation_origin` names a StepInput passage the claim does
   not cite), the two method files with the plan's paragraph,
   `tests/fixtures/research/*.json`, `tests/fakes.py::valid_response`.
7. `views.py` and the passage payload (`api/app.py:1544-1548`): the `math_json.source` summary on the asset (`version`,
   `version_from`, `record_label`, placed count, pages, not-placed reasons, state); per chunk the source equation
   numbers from the `placed` offsets inside its `payload_ref` range; the record's `version_label` never rewritten; the D4
   test of the plan's task 7.
8. The UI of decisions 8–9: `labels.ts` (the source row's states `read`, `source_waiting`, `no_source`, `failed`),
   `PassageSheet.tsx` (the `latex_source` notice naming the chunk's equation numbers), `ResearchView.tsx` (the
   "arXiv source" badge beside the OCR badge), `api.ts` (`text_source` type and the new states), `i18n.ts`. Playwright O
   (`arxiv-source.spec.ts`) with `DEIXIS_FIXTURE_ARXIV_SOURCE=fake` in `tests/acceptance/fixture_server.py`, Marker
   absent, as the plan lists.
9. Acceptance (a)–(f) of the plan in `.local/sw-slice22-acceptance-<date>/`: (a) `scripts/arxiv_source_report.py`, the
   product's own code in a dry run over every eligible stored arXiv PDF of the migrated copy (the 0053 → 0054 step
   repeating the plan's item 16 checks and writing them down), counting apart the candidates that pass the matching rule,
   compared with the plan's 873 candidates of 1,520 number lines (43 versions, all pages; ±10%, else say why), the blocks
   really placed (the plan has no placed count to compare with; say so), and every not-placed reason (KaTeX, `\ref` /
   `\cite`, length, table or OCR page, `not_in_page_text`, `offsets_unresolved`); agreement with Marker's stored reading as a comparison, not a ground truth; (b) every placed group
   rendered with Node and the web app's KaTeX, 0 errors or each one listed; (c) a real reading without Marker on three PDFs
   of the copy (version, chunk labels, `math_json.source`, old passages and their evidence still resolve); (d) three live
   fetches through the product's path, 3 s apart, with file name and sha256; (e) subprocess time per paper (median, max);
   (f) after code and constants are frozen, 40 placements from (a) (seed written down, at most 3 per paper, 20 by paper
   margin and 20 decided by the order) rendered with the region drawn and read by eye: group right or wrong, region
   deleting other text or not. More than one wrong placement means the slice is not finished: write them and their causes
   into row 22.
10. Close.

## Close

Write D104 at the top of `docs/decisions.md` (the highest today is D103), with A1, B1, C1, D3, E1, F1 and the plan's six
named departures from SW10. Its Limits name: one computer (Apple M1 Pro), one library, three fields; the rule chosen on
this data after its image sample was seen, no held-out set, one reader of the images (the plan's author, then you), and the image sample's 77/77 not an accuracy bound for other
data or readers; 873 is a count of prototype candidates, not of placements; POSIX only; the 3 s rate counted only across
processes of one data directory; no
check of the r1 complete pages (not used under D3); Marker's reading is a reference, not a ground truth; no speed gain
(D3); the product's placement measured only in acceptance (a) and (f); `export.arxiv.org`'s 406 to httpx and its unknown
cause; the flag off by default, so the live library did not change. Update SW10's status line in
`docs/product/search-workflow-review-2026-09-18.md` (point 6 (a)'s equation part, 7's matching part and 8 built behind
the flag and only for people without Marker; D85's reading run sees these equations only once the PDF was read in the
background or by an answer; 6 (a)'s prose, 6 (c), SW10.7's speed point and E2 left open) and row 22 (status
"uygulandı, commit edilmedi; kod incelemesi bekliyor", with the acceptance numbers next to the plan's). Run the full
pytest suite, `npm run build`, `npm run lint` (17 warnings), Playwright A–O; check `git diff --check`, the new hash, the
highest migration (`0054`) and that `uv.lock` is unchanged. Report the test run as "the known single failure apart, the
rest of the full run passed" with the counts. Commit nothing. The final message, in Turkish, gives the plan's commit
hash, what was done, the changed files, the judgement calls, the test counts, the acceptance numbers next to the plan's,
and what was not measured.
