<!-- PLAN-REVIEW-ROUNDS: r1 (Opus 5.5 high): düzeltmeyle hazır, 0 high + 4 medium + 3 low, all folded in (the round ran after the first implementation draft, not before it); code review r1 (Opus 5.5 high): düzeltmeyle hazır, 0 high + 2 medium + 3 low, all folded in; implementation by Sonnet 5.5 (the batch orchestrator itself, no claude -p call); reviewer: Opus 5.5 high (Sol quota out), Sol re-review pending (gpt-6.1-sol answered with a usage-limit error until 3 October 2026 20:39 when tried once on 2 October 2026) -->

# Task: P9 batch H7, daily-use fixes (at most 10 items, none from real daily use)

Worktree: `/Users/huguryildiz/Documents/GitHub/DEIXIS-h7`, detached at `565c430` (main with D164). Plan: `docs/product/p9-hardening-plan.md` section 3.6
("Günlük kullanım açıkları") and the H7 section of section 5. Also read `AGENTS.md`, `CLAUDE.md`, D161 to D164 in `docs/decisions.md`, and
`docs/product/p9-h2-prompt.md` (style model). Venv: `.venv` in this worktree (arm64, `uv sync --offline` done). Run tests with
`PYTHONPATH=backend:. UV_CACHE_DIR=/tmp/deixis-uv-cache .venv/bin/python -m pytest ...`. Web: `apps/web/node_modules` is a symlink to the main
checkout's folder, to be removed when the batch ends.

**No git state-changing commands.** Leave every change uncommitted. No real-model call, no provider call, no network. Do not touch `../DEIXIS`,
`../DEIXIS-h5`, `../DEIXIS-h6`, `TODO.md`, `.vscode/`, `scripts/local_index.py`, `docs/product/sw-status.md`, the live service on port 8765, the live data
directory, or ports 8858 to 8864. Servers of this batch use ports 8930 to 8940. No migration, contract or `methods/` change (`skill_package_hash`
unchanged). Do not invent; report what could not be measured. Python native arm64.

## The owner's daily-use log does not exist

The plan's source for H7 is the owner's log `.local/p9-daily-use-log.md` (owner question S9). **The file does not exist** (checked in the main
checkout on 2 October 2026). No item below comes from real daily use. The list is built from section 3.6, from the findings and "left open" lines of
D161 (H1), D162 (H2), D163 (H4) and D164 (H3), from `TODO.md` "Carried over from slice 31" (read, not edited), and from five items the main session named.
The decision says so, and says that what the log would have shown is not covered.

H5 (capacity) and H6 (accessibility) were still running on 2 October 2026 and no decision of theirs was on `origin/main` when the list was frozen.
Their findings are left to H8.

## Ranking and rules

Severity: (a) data loss or broken evidence meaning, (b) blocks the workflow, (c) misleading or unclear text, (d) cosmetic or test hygiene. At most 10
items are closed. No new feature, and no product decision that changes existing behavior; making an existing message clearer is in scope. Each closed
item has a reproduction, a fix and a focused test that fails on the old code (item 04: only the Playwright E line and the source check fail on the old code; its two backend tests describe data the old code already stored). One patch file per item in `.h7-patches/NN-name.patch` (`git diff` over that
item's files only), and the whole change also stays uncommitted in the worktree.

## Candidates

### Closed (checked against 565c430 by running code, not by reading alone)

| NN | Severity | Item | Reproduction on the old code | Fix |
|---|---|---|---|---|
| 01 | (a) | An upload trusts any file already under `papers/<sha>.pdf` (D162 Limits: "an upload only checks `exists()`"). A torn file left by a version before D162 is kept; the asset row names the hash of the whole file, extraction runs on the torn bytes (`failed`) and `deixis backup` refuses it. | Torn half-file under the hash name, upload the whole PDF: asset `failed`, file still half. | `pdf_files.file_is_whole` (size and hash) used by `store_upload` and `store_pdf_file`; a file that is not whole is replaced by the upload's own `.partial` through `os.replace`. **Limit:** an asset row that already exists for that hash (an earlier torn download that was extracted from the torn bytes, `failed`) keeps its stored text and status: neither route extracts again for a known hash and re-extraction answers "unchanged" for the same `EXTRACTION_VERSION`. The file becomes whole, so `deixis backup` accepts it; the row's text is not repaired. |
| 02 | (c) | The `ROLLBACK TO` of the candidate and lineage savepoint helpers runs unconditionally (D164 Limits); after a statement-level SQLITE_FULL SQLite has ended the transaction, `ROLLBACK TO` raises "no such savepoint" and hides the full disk (the API would answer 500 instead of 507 `disk_full`). | Real `max_page_count` limit inside the helper: `no such savepoint: sp1` replaces `database or disk is full`. | `db.rollback_savepoint` rolls back and releases only while the connection is still in a transaction. |
| 03 | (c) | The two Zotero routes write a PDF and the import writes its payload file without the `DiskFull` mapping; a full disk there is a bare 500 (D164 Limits "ENOSPC on a write path that no test hit stays a 500"). | `OSError(ENOSPC)` from `store_pdf_file` or from the payload `write_text`: 500. | `disk_full_refused()` around those three writes; an unrelated `OSError` stays a 500. |
| 04 | (c) | Two open items of D163 and D164 share one place, the run line of a paused run: after a restore the line says only "The selected model connection is not ready. Nothing was sent to another model." with no way forward (D163), and a model quota stop and a rate-limit stop read the same, as the generic "The model call did not complete" (D164). | `Run.error` holds the connection's reason and the model's own error text, the screen shows neither. | A second line under the unchanged reason line: "Open Settings, connect it again, then resume this run." plus the connection's reason; for `model_call_failed` "The connection reported: <its own words, one line, 240 characters>". DEIXIS does not classify the text. English and Turkish. **Gap:** the fixture's connection is always ready, so Playwright covers only the `model_call_failed` line; the not-ready line was looked at once through a mocked response (screenshots, not a committed test) and is otherwise pinned by a source check and by the backend test that the run carries the reason. |
| 05 | (d) | `tests/test_api_flow.py` defined 35 test names twice (D164 / D119 leftovers); the first copies never ran. The 34 first copies are identical to the second ones (AST compared), the 35th is a stale older version that fails if renamed and run. No coverage is lost. | AST scan. | The first copies are deleted; a test fails when any test module defines a test name twice. |
| 06 | (d) | `CLAUDE.md` says the README status paragraph is out of date; README (H1, D161) names the providers and the model connections correctly. | Read. | The sentence is replaced. |

### Not closed, with the reason

- **Password-protected PDFs stored before D164 stay `no_text`** and the screen says "PDF has no text layer" (D164 Limits). Not closable here: `EXTRACTION_VERSION`
  is unchanged so re-extraction answers "unchanged", and `reextract_asset` ranks `failed` below `no_text`. Either a version bump (re-reading every PDF of a
  library) or a change of the D45 rule would be a product decision. Severity (c).
- **Quota versus rate limit is not classified** (item 04 shows the connection's own words instead). A classifier needs measured error strings of the real
  connections; real-model calls are not allowed in this batch and the existing `adapter.RATE_LIMIT_ERROR_RE` merges both.
- **`User-Agent` contact email** (severity (c)) (TODO, plan 3.6): `DEIXIS_CONTACT_EMAIL` exists and is sent only as a query parameter (`mailto` to OpenAlex and Crossref, `email` to PubMed) and never in the PDF fetcher's `User-Agent`; sending it to every
  publisher is a new disclosure of the person's address, a product decision. Not in code today.
- **arXiv 406** (D88, severity (b) for that provider): needs measurement against arXiv; the investigation prompt exists (`docs/product/arxiv-406-prompt.md`). Network use is out of this batch. Severity (b) for provider coverage.
- **`sw` discovery-time short title** (D39, D119 Limits): changes what the product shows; owner decision. Severity (c).
- **Slice 31 test debt** (four items, severity (d)): each is a test to design and write against D119's replacements (a legacy answer test with several long PDFs, a legacy pdf/ocr/table/report end-to-end test, the evidence-table acceptance test including sources through the UI); that is more than a small fix and would take this batch beyond its S-M size. **The report on a real model** (D124 to D129, severity (b) for the report path): needs a real-model measurement, not allowed here.
- (d) Leftover `tmp*.part` files of a cut download and `.restoring-*.part` of a cut restore (D162, D163 Limits): removing files in the data directory is a new behavior.
- (c) ENOSPC on write paths no test hit beyond item 03, and the missing UI text for CSRF and Host refusals (D164 Limits): a global handler was avoided on purpose.
- (d) Deferred items of `TODO.md` (memory-like context, intent chips, Playwright PDF acquisition): "not planned".
- H5 and H6 findings: not on `origin/main` when the list was frozen; left to H8.

## Tests and checks

- New files `tests/test_p9_h7_*.py` (one per item; the numbers NN are those of the table). Item 03 also has an AST test that both `store_pdf_file` calls in `api/app.py` sit inside `disk_full_refused()`, because the second Zotero route has no data of its own in a test.
- Patches: items 01 and 03 both change `backend/deixis/api/app.py` in different hunks; `01-*.patch` holds the `store_upload` hunk and `03-*.patch` is made against the file as 01 leaves it, so they apply in order 01, 02, 03, 04, 05, 06, 07. Each fix test is run once on the old behavior (a monkeypatch back to the old
  function for 01, 02, 03; the HEAD file for 05) and fails there.
- Full `pytest` (baseline on 565c430: 8,343 passed, 2 skipped), `-m process -n 0` is not required (no process-level change).
- Web: `npm run build`, `npm run lint` (17 warnings baseline, none new), full Playwright against a fresh build (`DEIXIS_ACCEPTANCE_DIR=/tmp/deixis-acceptance-h7`),
  one added assertion in the E case. Screenshots at 1440 and 390 px, light and dark, looked at.
- `git diff --check`.
