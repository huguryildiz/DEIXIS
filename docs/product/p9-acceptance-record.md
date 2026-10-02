# P9 acceptance record

**Date:** 2 to 3 October 2026. **Commit:** `17b8341` (main with D167) plus the uncommitted H8 files (this record, `scripts/p9/run_matrix.py`, `tests/test_p9_run_matrix.py`, a port variable in `scripts/p9/capacity.py`, status lines). **Written by** the H8 batch from three runs of `scripts/p9/run_matrix.sh --overlay-uncommitted` and from decisions D138 to D167. Raw output of each run (logs, junit files, `matrix.json`, `matrix.md`, Playwright and install results) is in `/tmp/h8-closing/run1` to `run3` and a small copy (logs, junit files, JSON, no test data) in the worktree's ignored `.local/p9-matrix/h8-closing-run1` to `run3`; nothing private is in this file.

**What this record shows and does not show.** It shows that every automatic row of the P9 matrix passed on one macOS arm64 machine, in two of three complete runs, with a scripted model and synthetic records, a real server process, real Chrome and real child processes. It does not show model quality, a live provider, a real model, a second user's install, a screen reader, another operating system or another machine (plan section 4 closing sentence and section 10). Where this record says "closes", it means the model-free matrix passed under the conditions in section 8; it does not say the product is verified.

## 1. Supported environment and baseline counts

Supported (plan section 2): macOS on Apple Silicon (arm64), native arm64 Python 3.12 from `uv`, Node 22 (`engines` `>=22.12.0 <23`, `.node-version` 22.23.2) with npm 10, system Google Chrome, loopback only. Observed in the closing runs: macOS 27.0.1, Python 3.12.13, uv 0.11.24, Node v22.23.2, npm 10.9.8. Older macOS, Intel, Linux and Windows are `desteklenmiyor`: not supported and not tested. The environment pin is declared, not enforced (`engine-strict` is off). `HOME` is the real home directory in every stage; only the keychain is isolated (`PYTHON_KEYRING_BACKEND` null backend, in-memory keyring in the fixture server).

Baseline (D139, clean export of `8091d62`, 1 October 2026): pytest 3,772 passed, 1 failed (the memory test, fixed in D138), 2 skipped; build ok; lint 17 warnings, 0 errors; Playwright 112 passed. Its timings were skewed by foreign load and are not a speed baseline.

Closing runs (this batch, `17b8341` plus overlay): default pytest 8,442 tests, 0 failed, 23 skipped (2 OCR tests: no `tesseract` on the isolated PATH; 19 LaTeX compile tests: no TeX on the isolated PATH; 2 opt-in F09 tests, run in their own stage); 36 process tests, 0 failed; build ok; lint 17 warnings, 0 errors; Playwright 170 specs (the whole suite including `a11y.spec.ts`), 0 failed in runs 2 and 3, 1 failed in run 1.

## 2. How the matrix was run

`scripts/p9/run_matrix.sh` (Python `run_matrix.py`, standard library only) runs eight stages in this order: preflight, F09 (the two production-threshold tests), the process tests (`-m process -n 0`), the install check (`install_check.py`: I01 to I05, I07, keychain and cleanup), the default pytest suite, build and lint, the whole Playwright suite, and the capacity measurement (`capacity.py`). It reads each stage's junit, JSON or summary file, maps tests to rows, and prints a table in which a row is `geçti` only when its evidence ran and passed; a skipped stage or test, a pattern that matches nothing, a missing file, a stale or failed build (browser and capacity rows depend on `apps/web/dist` built in the same run) and a Playwright port clash all give `ölçülmedi`. It adds one mandatory row per stage (`suite-*`) so a failing test that no matrix row names cannot pass. It uses ports 8950 to 8970 and the fixed Playwright fixture ports 8777 to 8824 (refusing to start when any answers), never port 8765 (read with `lsof` only), never the live data directory (`DEIXIS_DATA_DIR` points into the output folder; the output folder must not sit inside the live directory), no model CLI on the stage PATH, and `--basetemp` under the output folder so a leaked process or disk image can be found. The three wall-clock stages wait up to 10 minutes for a 1-minute load below 4 and at least 50 percent free memory and record what they started at.

Provenance by stage: the install stage exported `HEAD` and copied the uncommitted files over it (`--overlay-uncommitted`), with cold uv and npm caches; every other stage ran on the working tree of the worktree `DEIXIS-h8`, whose `.venv` and `apps/web/node_modules` were installed (`uv sync --offline`, `npm ci`) before the runs. A run without the overlay on the committed hash should be repeated after the commit (as H1 did).

| Run | Started (UTC) | Load average at start | Result |
|---|---|---|---|
| 1 | 2026-10-02 19:14 | 3.99 4.55 5.74 | one mandatory row not `geçti`: `suite-playwright` (1 failed spec) |
| 2 | 2026-10-02 19:41 | 4.23 4.16 4.37 (before its first gate wait) | every mandatory row `geçti` |
| 3 | 2026-10-02 20:18 | 6.14 6.20 5.93 | every mandatory row `geçti` |

Loads at the start of the wall-clock stages are in each run's `matrix.md`. Runs 2 and 3 started under a heavier machine than run 1; run 3 waited the full 10 minutes twice (f09 at load 7.9, process at load 5.5) and then ran above the gate's limit.

Four earlier attempts at a closing run are not counted. Two had a runner defect found by them (a blocked-signal inheritance that made children unkillable: 17 process tests and I02 failed; a bind check that refused the second run on a TIME_WAIT socket). Two failed F09 when the machine was loaded or short of memory (swap in use; `extraction timed out` at 90 s and `exit_-14`, the child's 100 s lifetime alarm, before the child reached 1 GiB); F09 passed in 26 to 57 s when run alone and in all three closing runs after the gate was added. Their failures are kept in `/tmp/h8-closing-old/` and are described here so the runs that count are not read as the first tries.

## 3. Matrix result, row by row

Result words as in the plan: `geçti`, `geçmedi`, `ölçülmedi`, `desteklenmiyor`. Class: `zorunlu` (mandatory), `isteğe bağlı` (optional), `yalnız ölçüm` (measure only). Kind: S automatic test with scripted model or synthetic records, G real process, A real network without a model, E by hand, M real model. Execution type and data reality are two fields (plan section 4 rule 4): every row below used a **scripted model and synthetic records** unless it says otherwise; G rows used real server and child processes; the install rows used an empty library; the E and M rows were not run and are linked to their earlier record. Rows `suite-*`, `install-keyring`, `install-cleanup` and `cleanup` are added by H8 and have no plan id.

| Row | Class | Kind | Run 1 | Run 2 | Run 3 | Evidence (run 3) | Earlier record | Does not show |
|---|---|---|---|---|---|---|---|---|
| I01 | zorunlu | G | geçti | geçti | geçti | install_check 17b834127b | D161, H1 (cold caches 33 s: uv sync 13.7, npm ci 11.3, build 8.0; closing run on `6fd7a49` without overlay, `30ce8c8`) | Another user account, another network, older macOS. |
| I02 | zorunlu | G | geçti | geçti | geçti | install_check 17b834127b | D161 | The live instance on 8765 (never touched); that a research can run (the UI check proves the question box renders). |
| I03 | zorunlu | G | geçti | geçti | geçti | install_check 17b834127b | D161 | Two workers on one data directory (that is I06). |
| I04 | zorunlu | G | geçti | geçti | geçti | install_check 17b834127b | D161 |  |
| I05 | zorunlu | G | geçti | geçti | geçti | install_check 17b834127b | D161; the commit failed here before the `__main__.py` fix (traceback, exit 3) | A full disk (F05), a read-only `library.sqlite` inside a writable directory. |
| I06 | zorunlu | G | geçti | geçti | geçti | 1 tests (1 passed) | D162: second process `owner` 1.03 s after the SIGKILL | Real `codex` children; power loss. |
| I07 | zorunlu | G | geçti | geçti | geçti | install_check 17b834127b | D161 | That a model account works. |
| I08 | isteğe bağlı | E | ölçülmedi | ölçülmedi | ölçülmedi |  E row, not run by the script; not done in H1, so no second-user claim | Not done (D161): no second user | Everything about a non-developer install. **No second-user claim is made.** |
| install-keyring | zorunlu | G | geçti | geçti | geçti | install_check 17b834127b | D161: keyring 25.7.0 honours `PYTHON_KEYRING_BACKEND` | Other keyring versions. |
| install-cleanup | zorunlu | G | geçti | geçti | geçti | install_check 17b834127b | D161 |  |
| F01 | zorunlu | G | geçti | geçti | geçti | 2 tests (2 passed) | D162: held `grounded_answer` and held 2nd `abstract_screening`; resend exactly once, `model_calls` 2, one answer | Whether a real provider charged the first call (R02). |
| F02 | zorunlu | G | geçti | geçti | geçti | 3 tests (3 passed) | D162: a torn `<sha>.pdf` under the old code (329 bytes, backup refused), fixed with `store_pdf_file` | Power loss, `fsync` order; the Zotero routes by process. |
| F03 | zorunlu | G | geçti | geçti | geçti | 4 tests (4 passed) | D162 (kill part), D163 (restore part) | Another machine. |
| F04 | zorunlu | G | geçti | geçti | geçti | 6 tests (6 passed) | D162: held model call and Ctrl-C extraction took 40 s before; 6.05 to 6.13 s with the watchdog; other cases 3.2 to 3.4 s | A loaded machine can push a slow graceful shutdown into the forced path; real `codex`; Windows. |
| F05 | isteğe bağlı | G | geçti | geçti | geçti | 10 tests (10 passed) | D164: 16 MiB HFS+ image; create and upload refused 507 `disk_full`; PDF download half partial | The user's APFS volume; a half-written file under its final name (fixture PDFs are about 600 bytes). |
| F06 | zorunlu | G | geçti | geçti | geçti | 8 tests (8 passed) | D164 (corrupt and cut library), D163 (unknown migration id) | A hand-edited schema with known ids; truncated data pages only. |
| F07 | zorunlu | S | geçti | geçti | geçti | 48 tests (48 passed) | D164 inventory table | Real provider behaviour; quota and rate limit read the same on screen. |
| F08 | zorunlu | S | geçti | geçti | geçti | 15 tests (15 passed) | D164 | A real 50 MB body (the limit was patched to 10 kB); PDF classes MuPDF accepts that were not generated. |
| F09 | zorunlu | G | geçti | geçti | geçti | 2 tests (2 passed) | D138 (extraction child, 3 of 3 runs, 27 to 36 s, kernel peak 1024 MiB), D159 (arXiv source child) | Windows (no limit); OCR and JATS children are stopped late by their own watchdog; how often real arXiv sources hit it. Timing- and memory-pressure-sensitive (section 3, F09 note). |
| F10 | zorunlu | G | geçti | geçti | geçti | 1 tests (1 passed) | D163: three backups taken while a run was held and a writer wrote, 11 / 21 / 30 researches | Another machine. |
| B01 | zorunlu | S+G | geçti | geçti | geçti | 2 tests (2 passed) | D163: 85 tables (67 with rows, 18 empty by fixture design), 7 file hashes, 52 view JSONs and 5 citation anchors equal | A move to another machine; the owner's library beyond opening and equal counts; model credentials (not in a backup). |
| B01n | zorunlu | S | geçti | geçti | geçti | 25 tests (25 passed) | D163: a cut restore used to change the target (middle-file conflict); fixed |  |
| B02 | isteğe bağlı | G | ölçülmedi | ölçülmedi | ölçülmedi |  needs the owner's library and consent; not opened by this script (tooling tests run in the pytest stage) | D163: measured once on a copy of the owner's stopped-service backup (36 of 62 migrations applied, 26 applied on open; 20 researches, 1,206 source versions, 17,448 passages equal before and after; counts only) | Not re-run here. A copy of a running service (non-empty `-wal`) is tested on synthetic folders only. |
| B03 | zorunlu | G | geçti | geçti | geçti | 14 tests (14 passed) | D163: ids 0063, 9999, 0000 and one only in the `-wal` refused by `db.connect`, `serve` (exit 2) and `reextract`; main, `-wal`, `-shm` hashes equal | The guard compares ids only. |
| D01-D06 | isteğe bağlı | S | geçti | geçti | geçti | 14 tests (14 passed) | D165 | Not daily-use findings: the owner's log does not exist. |
| suite-pytest | zorunlu | S | geçti | geçti | geçti | 8442 tests, 0 failed, 23 skipped | D165: 8,357 passed, 2 skipped at its base | Model quality or live providers. |
| suite-process | zorunlu | G | geçti | geçti | geçti | 36 tests, 0 failed, 0 skipped | D162, D163, D164: 36 process tests |  |
| suite-web | zorunlu | S | geçti | geçti | geçti | lint 17 warnings, 0 errors (baseline 17) | D167: build clean, lint 17 warnings (baseline) |  |
| suite-playwright | zorunlu | S | geçmedi | geçti | geçti | 170 specs, 0 failed, 0 skipped | D167: 170 passed |  |
| suite-capacity | zorunlu | G | geçti | geçti | geçti |  | D166 |  |
| K01a | zorunlu | G | geçti | geçti | geçti | capacity summary, pass | D166: 0.24 s UI, 0.08 s first API (N=1,000) | Real model and provider latency; real research screen refetch while a run is active. |
| K01b | zorunlu | G | geçti | geçti | geçti | capacity summary, pass | D166: 0.62 s and 0.43 s (N=5,000); first run 12.0 s before migration 0063 |  |
| K01c | yalnız ölçüm | G | geçti | geçti | geçti | capacity summary, measured | D166: N=100 0.18 s, N=7,769 0.89 s |  |
| K01d | yalnız ölçüm | G | geçti | geçti | geçti | capacity summary, measured | D166: 10,000 works ready in 1.1 s (3 of 3) |  |
| K02a | zorunlu | G | geçti | geçti | geçti | capacity summary, pass | D166: worst 0.055 s (limit 0.5 s) |  |
| K02b | zorunlu | G | geçti | geçti | geçti | capacity summary, pass | D166: worst 0.40 s (limit 1.0 s); first run 7.97 s before 0063 |  |
| K02c | yalnız ölçüm | G | ölçülmedi | ölçülmedi | ölçülmedi | capacity summary, incomplete verdict incomplete | D166: 7,769 works 0.62 s; 10,000 works 0.83 s |  |
| K03a | zorunlu | G | geçti | geçti | geçti | capacity summary, pass | D166: worst 208 MB (limit below 2,000,000,000 bytes) |  |
| K03b | yalnız ölçüm | G | geçti | geçti | geçti | capacity summary, measured | D166: 10,000 works: database 40 MB, data directory 41 MB |  |
| K03c | yalnız ölçüm | G | geçti | geçti | geçti | capacity summary, measured | D166: 232 MB at 10,000 works |  |
| K04a | yalnız ölçüm | G | geçti | geçti | geçti | capacity summary, measured | D166: 0.14 / 0.16 / 0.93 s at 1,000 / 5,000 / 10,000 |  |
| K04b | yalnız ölçüm | G | geçti | geçti | geçti | capacity summary, measured | D166: 0.6 / 2.7 / 5.9 s | The Sources list is not virtualised. |
| K04c | yalnız ölçüm | G | geçti | geçti | geçti | capacity summary, measured | D166: 0.4 to 0.7 / 2.7 to 3.6 / 7.1 to 7.9 s |  |
| K05 | yalnız ölçüm | G | geçti | geçti | geçti | capacity summary, measured | D166: first page 1.07 s worst, page 400 in 0.43 s (45 MiB, 500 pages) | Other PDF kinds. |
| K06a | zorunlu | G | geçti | geçti | geçti | capacity summary, pass | D166: 5,000 works 1.4 s (limit 120 s) |  |
| K06b | yalnız ölçüm | G | geçti | geçti | geçti | capacity summary, measured | D166: backup 21 MB; large-PDF library 48 MB; worst health request 0.035 s with the server running |  |
| K07 | zorunlu | G | geçti | geçti | geçti | capacity summary, pass | D166: measured peak column filled (RSS 232 MB, 10,000 works loaded, 45 MiB PDF viewed); other cells "not measured" with reason | Upload, download, extraction and `model_concurrency` limits under load. |
| A | zorunlu | S | geçti | geçti | geçti | 1 specs (1 passed) | D129, D167 | Open time on a large library is K04c. |
| B | zorunlu | S | geçti | geçti | geçti | 2 specs (2 passed) | D129, D167 |  |
| C | zorunlu | S | geçti | geçti | geçti | 2 specs (2 passed) | D129, D167 |  |
| D | zorunlu | S | geçti | geçti | geçti | 1 specs (1 passed) | D129, D167 | The real model's resistance to misleading keywords (P2 cases). |
| E | zorunlu | S | geçti | geçti | geçti | 2 specs (2 passed) | D129, D167 | A real provider outage. |
| F | zorunlu | G | geçti | geçti | geçti | 2 specs (2 passed) | D129, D162 (SIGKILL is F01 to F03) |  |
| G | zorunlu | S | geçti | geçti | geçti | 2 specs (2 passed) | D129, D167 | A real model's resistance to instructions in a PDF (P2 cases). |
| X01-X04 | zorunlu | G | geçti | geçti | geçti | 14 specs (14 passed) | D167: 80 serious or critical hits on the baseline, 0 after the fixes; 104 scans stable | Label wording, reading order, focus order sense, cognitive accessibility; Chrome only; 128 of 440 contrast nodes unmeasured. |
| X05 | zorunlu | S | geçti | geçti | geçti | 10 specs (10 passed) | D167: 597 focus records, 0 failures; nine focus drops to `body` fixed | Real user habits; the focus items in section 4. |
| X06 | zorunlu | S | geçti | geçti | geçti | 3 specs (3 passed) | D167: reduced motion; 200% as a 640 x 450 layout at scale 2 | Chrome's own zoom; text-only zoom; 400% is recorded only. |
| X07 | isteğe bağlı | E | ölçülmedi | ölçülmedi | ölçülmedi |  E row (VoiceOver), not run by the script; not measured in H6 | Not run (D167) | VoiceOver and every other screen reader. |
| R01 | isteğe bağlı | M | ölçülmedi | ölçülmedi | ölçülmedi |  M row, H9 not run | Not run (H9) | Anything about a report on a real model. |
| R02 | isteğe bağlı | M | ölçülmedi | ölçülmedi | ölçülmedi |  M row, H10 not run | Not run (H10) | Whether the first send was charged. |
| cleanup | zorunlu | G | geçti | geçti | geçti |  |  | Processes started by other chats in the same minutes may be flagged. |



**Row notes.**
- Only `suite-playwright` differs between the runs (run 1 `geçmedi`, runs 2 and 3 `geçti`); every other row has the same result in all three runs.
- `F09`: the two production-threshold tests are timing- and memory-sensitive. The child grows about 30 MiB/s unloaded and the product's own 90 s extraction clock and the child's 100 s alarm end it first when it grows slower. Four attempts failed under load or swap, three runs after the quiet gate passed. A F09 failure with a recorded load above the gate's limit carries a note saying a timeout can be load, not the watcher; it stays `geçmedi`.
- `B02` is `ölçülmedi` in the matrix because it needs the owner's library and consent; it was measured once with consent in H4 (D163, counts only). `I08`, `X07`, `R01`, `R02` are E or M rows that need a person or a real model.
- `K02c` reads `ölçülmedi` because one of its three repetitions at N=100 recorded no health sample (section 4); it is a measure-only row.
- `D01-D06` are the six H7 items (D165). None came from daily use.
- Capacity numbers of the closing runs (run 2 and run 3 summary files under `.local/p9-h5/matrix-*`; run 2 values here, three repetitions per point, worst of three): research screen ready at 1,000 works 0.245 s (limit 2 s), at 5,000 works 0.579 s (limit 10 s), at 10,000 works 0.964 s; longest health request during the first view call 0.078 s at 1,000 (limit 0.5 s) and 0.355 s at 5,000 (limit 1 s), 0.701 s at 10,000; server RSS peak 209,158,144 bytes over the judged points (limit below 2,000,000,000), 233,734,144 at 10,000 works; backup of 5,000 works 0.918 s (limit 120 s), 21,078,347 bytes; 45 MiB, 500-page PDF: first page 0.749 s, page 400 in 0.225 s. These ran under parallel load (the load average was above 4 at some repetition, which the capacity script labels).
- A load note: the run-1 Playwright stage started at 1-minute load 4.8; the failing spec is described in section 4.

## 4. Known bugs, limits and open observations

Severity uses the H7 scale: (a) data loss or a broken evidence meaning, (b) blocks work, (c) misleading or unclear text, (d) cosmetic. "Defect" means the code does something it should not; "limit" means the behaviour is understood and documented; "observation" means read from code or seen once, not reproduced. No item below is a severity (a) defect that is known and unfixed (check made for the closing rule, section 8).

### Defects known and not fixed

| Item | Source | Sev. | What is known |
|---|---|---|---|
| Password-protected PDFs stored before D164 stay `no_text` and read "PDF has no text layer"; OCR is still offered | D164, D165 | c | Fixing it needs a version bump that re-reads every PDF, or a change of the D45 rank rule: a product decision. |
| arXiv answers 406 for some requests and the provider is treated as failed | D165 | b (that provider) | Needs a measurement against arXiv; no real-network probe was allowed. |
| Quota stop and rate-limit stop read the same on screen; a model `client_timeout` reads as "The model call did not complete" | D164, D165 | c | After D165 item 04 the run line shows the connection's own words; DEIXIS does not classify them. A classifier needs measured error strings of real connections. |
| The contact e-mail in the PDF fetcher's `User-Agent` | D165 | c | Adding the owner's address is a new disclosure; owner decision. |
| The `sw` discovery-time short title | D165 | c | Changes what is shown; not decided. |
| ENOSPC on a write path no test hit stays a 500; no useful UI text for CSRF and Host refusals | D164, D165 | c | A global `OSError` handler was avoided (Starlette wraps an exception raised after the response started). |
| A `sqlite3.DatabaseError` raised after a streamed response has started is wrapped by Starlette in a `RuntimeError` | D164 | c | The connection closes either way. |
| A cut download leaves its `tmp….part` file, a cut restore leaves `.restoring-*.part` files | D162, D163, D165 | d | Removing files in the data directory is a new behaviour; a later restore removes its own leftovers. |
| A cut upload leaves a source row without asset or membership | D161, D162 | d | Explained in D161. |
| A JATS render leaves its temporary folder, a PDF request its placements file, when the parent is killed | D162 | d | The Marker runner and the Claude and Gemini CLI children are not covered. |
| `failed` asset rows stored before H3 carry a MuPDF traceback tail in `extraction_error`; the view now exposes it and the UI does not show it | D164 | d | |
| Four slice 31 test-debt items | D165 | d | Each is a test to design. |
| Helpers `attached_research` and `run_to_end` are still defined twice in `tests/test_api_flow.py`; the guard looks at test functions only | D165 | d | |
| `--attr-submitted` and `--tone-uncertain` are nearly the same amber in light (Lab distance about 2.5); in dark identical | D167 | c | Two pairs of different meaning sit side by side (version pill and OCR pill; `.source-fact` pair). Both carry their meaning in text. Owner may want them apart. |
| `--tone-uncertain` as raw text colour is 4.17:1 on white in `workspace.css` at six selectors not on the frozen screens | D167 | c | Not on a scanned screen, so axe did not see them; not changed. |
| Extraction children are time-bounded after their parent dies (100 s alarm) but not memory-bounded | D162 | d | An orphaned extraction can pass 1 GiB until it ends. |
| OCR and JATS children are stopped late (about 2.4 and 1.5 times the limit on the shapes measured) | D159 | d | The in-child watchdog is a second guard; a parent watcher was not measured on them. |
| An arXiv source child that a loaded machine could not watch (`memory_watch_lost`, `timed_out`) is stored `unreadable` until reset | D159 | d | Accepted; the PDF path retries automatically. |
| The F09 production-threshold tests depend on machine load and memory pressure | this batch, D138 | d (test) | See section 3, F09. |

| A matrix run leaves about 3 to 4 GB under its output folder (the pytest base temp of the process and default stages, Playwright artifacts) | this batch | d | The runner does not delete it; remove the `*-tmp` folders after reading a run. |
| `report-edit.spec.ts:338` ("conflicting save preserves the typed draft...") failed once in the first of three closing runs, at 1-minute load 4.8 to 5.5 | this batch | d (test) | The failing page snapshot shows the edit form already closed, which suggests the save went through instead of conflicting, so the test's own "other tab" write and the save raced; this reading was not confirmed. It passed 5 of 5 alone and 3 of 3 with its whole file (16 specs). Not fixed; it is the reason run 1 differs from runs 2 and 3. |
| K02c at N=100: one of three repetitions had no health request inside the first view call's window, so the row reads `incomplete` (counted `ölçülmedi`) in all three runs | this batch, D166 | d | A measure-only row; at 100 works the view call takes about 15 ms, shorter than the poller's 25 ms interval. |
| The default pytest suite runs with a PATH that holds no `tesseract` and no TeX, so 2 OCR tests and 19 LaTeX compile tests skip (the plan's isolation rule 5) | this batch | d | They are measured by their own opt-in runs (D158); the isolated matrix does not run them. |

### Limits and observations

- Focus (D167, read from code, not reproduced): the route-change focus loop in `App.tsx` stays armed up to 5 s; `focus.ts` gives up after 2.5 s and can expire before a slow API answers; `ResearchView.tsx::act` does not rethrow, so after a failed Generate answer the focus goes to the previous run's heading; the tab list has two Tab stops; focus drops after Include, Undecided, the other Resume buttons and a Settings tab change were not walked. The last `focus.ts` fix after code review round 4 was not reviewed.
- Accessibility measurement limits (D167): Chrome only; synthetic records; the 200% case is the 640 px layout equivalent, not Chrome's zoom; text-only zoom is not measured; 128 of 440 contrast "incomplete" nodes are `ölçülmedi` (120 sit behind an open sheet, 8 are decorative thumbnails); gradient and motion-only styles are not measured; tabs not on the list (Activity, Candidates, Artifacts, Waiting for your PDF) were not scanned; the evidence-report table scroll region is a Tab stop even when nothing scrolls; the 400% layout is recorded, not mandatory.
- Markup read, not heard (D167): `mark` carries `aria-label` and `div.queue-detail` carries `aria-labelledby` without a role (axe: needs review); label wording and reading order were not judged by anyone.
- Backup and restore (D163): paths are file names only, so a move to another machine is manual and unmeasured; the guard compares migration ids only (a hand-edited schema with known ids is not detected); `backup` on a database with no `schema_migrations` or `source_assets` produces a database-only backup that restore refuses; the schema precheck reads the whole library into a temporary folder when a `-wal` is present (0.23 s on 211 MB, more on a cold disk); the B01 library is synthetic and 18 of its 85 tables are empty by design; B02 ran once on a library with 36 of 62 migrations applied, on a copy of a stopped service; a copy from a running service is tested on synthetic folders only; model credentials are not in a backup, and a restored library shows its connections as not ready.
- Crash and shutdown (D162): SIGKILL is not power loss (WAL durability and `fsync` order are not shown; `store_pdf_file` does not `fsync`); the real `codex` child is not tested (H10), and a child that ignores stdin EOF is stopped by nothing in DEIXIS; the 6 s forced-exit watchdog leaves a margin of about 2.6 s over a 3.2 to 3.4 s graceful shutdown, so a loaded machine can turn a healthy slow shutdown into the forced path; the watchdog starts only after uvicorn's Python-level signal handler runs; the Zotero routes and the rendition path are covered by a unit test and code reading, not a process test; a SIGKILL during a model call resends once as a new model session and a new budget use (expected, not a bug), and whether the provider charged the first call is unknown (R02).
- Faults (D164): a PDF cut in half is repaired by MuPDF and comes back `partial`, not `failed`; truncating only the data pages of a populated library can open without error (only `integrity_check` sees it); after a database error mid-step the stale `running` step rows are left to restart recovery; `db.open_problem` on a missing file creates and migrates a fresh library; no test uses a provider delay near the real 30 s limit; one HFS+ disk image, not the user's APFS volume; the disk-full PDF download half is partial (the fixture PDFs are about 600 bytes, so a half-written file under its final name could not appear).
- Install (D161): one machine, one macOS version; `HOME` is real (only the keychain is isolated); `uv` user configuration would be recorded, not blocked; the UI check proves the question box renders, not that a research runs; outbound requests are trapped for the app's own httpx client and observed at four instants, not blocked by a firewall; I02's stop is SIGTERM to the top process; I05 covers a read-only directory and parent, not a read-only `library.sqlite` inside a writable directory.
- Environment pin (D139): `engines` and `.node-version` are declared, not enforced (`engine-strict` is not set). The lineage view test that depended on generated-id order was fixed in `6e85654`.
- Isolation (D139): before D139 the Playwright fixture server could reach the system keychain; fixed in `fixture_server.py::main` with an in-memory keyring. Other Playwright children that might touch the keychain are not claimed.
- Process-test and Playwright port sharing (D165): a full Playwright run once failed `human-queue.spec.ts:265` with `route.fetch: socket hang up` while other worktrees may have used the same fixed ports; it passed alone. Specs other than `a11y.spec.ts` do not refuse a port that already answers.

## 5. Capacity limits

Measured by `scripts/p9/capacity.py` (D166), against thresholds frozen before the first measurement (S7); synthetic libraries (no answers, reports, evidence tables or model steps), one machine, Apple Silicon, system Chrome, cold server process on a warm file cache. The closing runs' numbers are in section 3 (rows K01 to K07) and in the capacity table below.

- Supported upper size (as measured): **10,000 works in one research** (11,000 source versions); the research screen was ready in 1.1 s at the D166 measurement.
- A research view call grows linearly with the number of works and holds the event loop for its duration (0.83 s at 10,000, D166). A second tab or the live event stream waits during that time.
- The Sources list is not virtualised: first row at 5,000 works after 2.7 s and at 10,000 after 5.9 s (D166).
- Opening a passage from that list takes 7 to 8 s at 10,000 works (D166).
- A 45 MiB, 500-page PDF opens its first page in about 1 s and jumps to page 400 in under half a second (D166).
- Hard limits (from `capacity.py limits`, read from code): upload 50 MiB, download 30 MiB, extraction 400 pages, 3,000,000 characters and 90 s; memory watcher at 1 GiB (stops after the size crosses it); `model_concurrency` default 6. The server's resident size peaked at 232 MB with 10,000 works. Model concurrency and the upload, download and extraction limits were not measured under load.
- Backup of 5,000 works took 1.4 s and 21 MiB; the 45 MiB library 48 MiB.
- Not measured: real model and provider latency, the real research screen's refetch on every recorded event during a run, a library of real texts and mixed PDFs, a quiet machine (D166 ran under foreign load of 3 to 13).

## 6. Not measured

- The report on a real model on a fresh corpus (H9, row R01) and the repeat of a real model call after SIGKILL (H10, row R02): not run; both need a real model and the owner's decision (S10, S11).
- I08, a second user installing from the README on a clean macOS account: not done, so **no second-user claim is made**. The only install evidence is this developer's machine.
- VoiceOver (X07) and every other screen reader; reading order and label wording; cognitive accessibility.
- Older macOS, Intel Macs, Linux and Windows are `desteklenmiyor` (plan section 2; Windows and macOS packages are P10). Windows has no memory limit on extraction at all.
- Power loss, kernel panic and file-system faults beyond a full disk.
- A second machine, a corporate proxy, a machine without `uv` or Node, the user's APFS disk.
- A quiet-machine re-run of H5: D166 and the closing runs ran under foreign load. The verdicts are expected to hold on a quiet machine because load makes timings worse, but it was not re-measured.
- B02 on the owner's library was measured once (D163) and is not re-run by this matrix.
- The owner's daily-use log (S9) does not exist, so the H7 list is not a list of real daily use.
- Text-only zoom, 400% layout as a requirement, other tabs and states not on the frozen screen list.
- Sol review of any batch from H0c on (section 7).

## 7. Sol re-review debt

gpt-6.1-sol answered with a usage-limit error until 3 October 2026 20:39 (tried once in an earlier batch; not tried again in H8). Every batch below was reviewed by Claude Opus 5.5 at high effort, not by GPT, and its commit message says "Sol re-review pending". The GPT pass should read these in order:

| Commit | Batch / decision | Review state |
|---|---|---|
| `129791a` | H0a, H0b (D138, D139) | **reviewed by gpt-6.1-sol** (plan 2 rounds, code 1 round); no debt |
| `fef9b6e` | H0c (D159) | **self-reviewed by Claude only** (no Sol, no Opus round); the largest gap in the chain |
| `4050a94` | H0d follow-up to H0c | Opus 5.5 high |
| `6fd7a49`, `30ce8c8` | H1 (D161), closing install run | Opus 5.5 high (plan 3 rounds, code 2); `30ce8c8` docs only |
| `7c197b7` | H2 (D162) | Opus 5.5 high (plan 2 rounds, code 2) |
| `1cb88b1` | H4 (D163) | Opus 5.5 high (plan 2, code 1) |
| `565c430` | H3 (D164) | Opus 5.5 high (plan 2, code 2) |
| `5b4e9ec`, `24b9b88`, `6675646`, `85efa36`, `468f653`, `0046eda`, `5b616e5` | H7 (D165), six items and the record | Opus 5.5 high (plan 1 round, code 1) |
| `5df9b9e` | H5 (D166) | Opus 5.5 high (plan 3 rounds, code 4) |
| `17b8341` | H6 (D167) | Opus 5.5 high (plan 2, code 4); **the last `focus.ts` fix after round 4 was not reviewed** |
| this batch | H8 (D168) | Opus 5.5 high, implemented by Sonnet |



## 8. P9 exit condition, item by item

The P9 row of `docs/product/implementation-plan.md` section 9: *a repeatable install and an acceptance matrix in the supported environment; known bugs and capacity limits open.* Plan section 4 rule 2 adds: no data loss, no broken evidence meaning, no unenforced security limit (F09 included) and no serious or critical accessibility defect may be open.

1. **Repeatable install in the supported environment.** I01 to I05 and I07, the keychain row and the cleanup row passed in all three closing runs (cold caches: uv sync 16.3 to 46.7 s, npm ci 9.8 to 13.4 s, build 7.4 to 8.3 s) and in H1 on the committed hash without overlay (`30ce8c8`). I08, a second user on a clean account, was not done. **So the install is repeatable on this developer's machine; no second-user claim is made.**
2. **Acceptance matrix.** `scripts/p9/run_matrix.sh` runs every automatic row and prints it row by row (section 3). Run 2 and run 3 gave the same pass/fail result on every row and every mandatory row passed. **Run 1 differs in one mandatory row** (`suite-playwright`, one spec of `report-edit.spec.ts` that races its own second write; it passes alone 5 of 5 and with its file 3 of 3). The plan asks for two runs with the same result; that holds for runs 2 and 3, and it does not hold for the first of the three runs. This is stated here, not resolved by choosing a run. The owner can decide whether one flaky spec outside the A to G and X rows blocks the close; the batch did not fix the spec (outside H8's files).
3. **Known bugs open.** Section 4 lists them with source, kind and severity. Rule 2 check: no severity (a) item is known and unfixed (the one (a) found in H7, a torn file under a hash name, is fixed, D165 item 01, with the limit that a row stored before the fix stays `failed`); the memory limit is enforced for the PDF extraction child and the arXiv source child (F09, D138, D159) and by their own watchdog for OCR and JATS (stopped late, section 4); F09 itself is timing-sensitive; no serious or critical axe finding is open on the scanned screens (D167: 0 in 104 scans), with the measurement limits in section 4.
4. **Capacity limits open.** Section 5.
5. **What the model-free close does not cover.** Section 6: the report and a repeated call on a real model, a second user, a screen reader, other systems, power loss, another machine, a quiet-machine re-run of H5.

Result: the model-free matrix passed in two of three complete runs with the single difference above, on one machine, with the Sol re-review debt of section 7 and the open owner decisions of section 9.

## 9. Owner decisions still open

- S8: who does I08 (clean-account install) and when; until it is done there is no second-user claim.
- S9: the seven-day daily-use log (`.local/p9-daily-use-log.md`); until it exists H7-type findings come from tests and reading only.
- S10, S11: whether to run H9 (report on a fresh corpus, real model) and H10 (real call after SIGKILL).
- The contact e-mail in the PDF fetcher's `User-Agent`, the two nearly identical amber colours, and the product choice for pre-D164 password-protected PDFs (section 4).
- Whether to add CI (S12) and a quiet-machine H5 re-run.
