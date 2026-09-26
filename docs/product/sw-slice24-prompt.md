# Task: SW slice 24: measurement campaign, then the default and the close

**Run this prompt only when row 24 of `docs/product/sw-status.md` names A1, B1, C1, D1, E1, F1, G1, H1 and I1** (its
status reads `… A1, B1, C1, D1, E1, F1, G1, H1, I1 önerildiği gibi …`). If row 24 names a different answer to any of A–I,
or none, stop at once and change nothing.

Repo: `/Users/huguryildiz/Documents/GitHub/DEIXIS`, branch `main`, main checkout. The plan is
`docs/product/sw-slice24-measurement-campaign.md` **as committed**: find the commit that last changed it with
`git log -1 --format=%H -- docs/product/sw-slice24-measurement-campaign.md` and check that
`git status --porcelain docs/product/sw-slice24-measurement-campaign.md docs/product/sw-slice24-prompt.md` prints nothing.
If the plan has no commit, or has uncommitted changes, stop and change nothing. Write that hash in your final message and
in the campaign's `protocol.md`: the plan's section "Dondurulmuş beklentiler" is the frozen expectation, and it is frozen
by that commit. Do not pull, fetch or change branches to get it. The plan is the only source of truth for this slice;
where it departs from the implementation plan or SW10 (its section "SW10'dan ve ana plandan sapmalar": no Europe PMC arm,
half of SW10's open-access idea, Luna instead of `deepseek-flash`, repeats only for gate 2's two cells), the plan wins.
Its section "Ölçüm sözlüğü" defines every stage, match and denominator you report; use its names.

**Which part to run.** Read row 24's status.
- If it says nothing about 24a, run **Part A** from the start and stop after it.
- The active campaign folder is the one named in `.local/sw-slice24-active` (plan decision 13); every resume check below
  reads only that folder, never another `sw-slice24-campaign-*` folder. If the file is missing or its folder has no
  `protocol.md`, run Part A from the start.
- If it says `24a durdu`, resume Part A under the plan's decision 13: same campaign folder and frozen protocol, only if
  every frozen file's sha256 still matches `protocol.md` and `git diff --stat <protocol commit> -- backend apps/web
  contracts methods` is empty; otherwise restart Part A in a new campaign folder, keeping the old one untouched, and
  point `.local/sw-slice24-active` at the new folder only once that folder's `protocol.md` is written (end of task 5).
- If it still says `uygulanıyor (24a)`, an earlier run crashed before it could write `24a durdu`. Treat it as a stop:
  find where it ended from the last entries of the active campaign folder's `ledger.jsonl` and `log-*.md`, then check the frozen
  files' sha256 against `protocol.md` and the same `git diff --stat`, and resume or restart exactly as for `24a durdu`
  (plan decision 13).
- If it says `24a bitti; dört kapı geçti` **and** row 17 says `kapandı`, run **Part B** (the default and the close).
- If it says `24a bitti` with any gate failed, or row 17 is not `kapandı`, stop and change nothing: Part B does not run.

List every place where you used your own judgement.

## Rules

1. **Git: you never commit.** Do not run `git commit`, `git push`, `git pull`, `git fetch`, `git stash`, `git reset`,
   `git checkout`/`git switch` of another ref, `git rebase` or `git merge`, and create no branch. `git add` nothing. The
   owner's working-tree files stay untouched: `TODO.md`, `.vscode/`, `scripts/local_index.py`, and anything else that is
   not this slice's. In your final message list every file you created or changed (from `git status --porcelain`, minus
   those).
2. **Part A changes no product file.** Its only tracked edits are `docs/product/sw-status.md`,
   `docs/product/sw-slice24-results.md` (new), new SW entries in `docs/product/search-workflow-review-2026-09-18.md`
   (SW18 onward) and, only if a gate fails, D105 at the top of `docs/decisions.md`. If Part A stops part-way (quota,
   `model_call_failed`, machine), write row 24 as `24a durdu: <where>` and nothing else tracked. Every script, server, data directory and raw output lives under
   `.local/sw-slice24-campaign-<YYYY-MM-DD>-<HHMMSS>/` (untracked; `.local/` is in `.gitignore`), a name that never already exists; a restart opens a new one and moves `.local/sw-slice24-active` to it only at the end of task 5, after the new folder's `protocol.md` is written, so a crash before that move leaves the pointer on the old folder. Nothing goes into `scripts/`.
3. **Port 8765 and the live library are off limits.** Every research runs in its own empty `DEIXIS_DATA_DIR` inside the
   campaign folder, on its own port from 8851 up, one server at a time, stopped when its research is done. From the live
   data directory (`~/Library/Application Support/DEIXIS`) only `codex-home` is used, through `DEIXIS_CODEX_HOME`; its
   `library.sqlite` is never opened.
4. **Nobody decides for the product.** `DEIXIS_PROTOCOL_APPROVAL=as_proposed`; no term, criterion, block or selection is
   edited; the human queue is not answered; no PDF is dropped in. The plan's decision 10 sample is read by you and
   written as an analyst reading, never as a human verification.
5. **Model (B1).** Every role of every research: connection `codex`, `requested_model` `gpt-5.6-luna`,
   `reasoning_effort` `medium`. `adapter.health` only shows that the CLI and the login exist; it says nothing about
   quota. The quota is read from the first real model call: if the first research's first model step ends with a quota
   or rate-limit error, stop and write it into row 24 (the owner's list item 1 in the plan). If a later call hits the quota
   or a run pauses with `model_call_failed`: for `client_timeout` resume it once after 10 minutes; for anything else stop
   the campaign and write where it stopped; a research left half done is reported as half done. Never switch model or
   connection, never let a fallback run.
6. **Freeze before the first research.** In this order, and before the first `POST /api/researches`: copy the Elicit
   files and check their hashes (Part A task 2), build the medicine reference set and the Elicit scope labels (tasks 3,
   4), write `protocol.md` (task 5), and append every frozen file's sha256 to `ledger.jsonl`. A frozen file is never
   edited afterwards; a deviation is written into the result.
7. **Network.** Allowed: the product's own traffic from the campaign servers; the built-in embedding download (D103)
   through the product's install endpoint; read-only lookups by the campaign scripts to PubMed (E-utilities), Crossref,
   OpenAlex and Europe PMC's REST API, at most one request per second per host, with the product's User-Agent, never with
   the user's e-mail or any key written to a log, ledger or result. No other network use.
8. **Python:** `PYTHONPATH=backend:. uv run --no-sync python ...`, native arm64. Scripts that only read SQLite use
   `immutable=1` URIs on stopped data directories.
9. **Words.** "found", "missed", "both found"; never "correct" or "wrong" about a reference set or about Elicit. A work
   Elicit included that our screen puts out on the comparator is a **scope difference, not a miss**. Every number carries
   its sample size, the machine and the model; one run is written as one run.

## Part A — the campaign

1. **Rows.** In `sw-status.md`: 18a `kapandı` (publisher-PDF acceptance done by 18b's acceptance; proxy not measured),
   18b and 19 `kapandı` (reviews finished; commits `926e01d` + `4a3354c`, `d96e41d`), 17 gets the note "24b'den önce Sol ·
   high son kontrolü (`80caa75`'in düzeltmeleri)"; row 24 `uygulanıyor (24a)`; K4's row: "dilim 24: Luna · medium (B1)".
   Nothing else in those rows changes.
2. **Set-up.** Create the campaign folder. Copy `.local/sw-slice24-plan-2026-09-26/elicit-quantum/` and `elicit-tre/`
   into it and check each file against the plan folder's `SHA256SUMS`; stop on any mismatch. Check `adapter.health` (CLI and login only; the quota is read from the first real call, rule 5).
   Start `ledger.jsonl` (one JSON object per line: time, kind, what, sha256 or status). Do not touch
   `.local/sw-slice24-active` here; it is written only at the end of task 5.
3. **Reference sets** (plan decision 6). `reference-q1.jsonl`: the 31 works of
   `.local/quantum-work-adjudication-2026-09-18/adjudication.jsonl` with `model_status = confirmed_mathematical_model` and
   `confidence = high`, in `scripts/probe_report.py`'s format (header `origin`, `completeness`; one line per work with
   `key`, `title`, `dois`, `openalex_ids`, `role`). `elicit-q1.jsonl`: Elicit's 9, same format. For the medicine question
   follow the plan's decision 6 steps 1–6 exactly: the `esearch` query byte for byte with the campaign day as the end of
   the `edat` range, `retmax=200`, paging with `retstart` while fewer PMIDs than `count` are in hand (stop if the total
   does not reach `count`), every PMID read with `esummary`; order by Entrez date, newest first, same day larger PMID
   first; (a)–(c) from each abstract (drop a candidate only if the abstract clearly fails (a) or (b); if it cannot
   decide (c), keep the candidate and decide (c) from the table too), then (d)–(e) from that review's included-studies table (PMC's open full text or the
   publisher's open page; if it cannot be opened, `table_unavailable`), each decision and reason in the ledger; stop at
   three tables read or ten candidates examined. **Never use a review's reference
   list** as a source of trials. Each table row resolved to PMID and DOI with one PubMed search and put through the
   decision tree into `reference-tre.jsonl` (R), `comparator-differs-tre.jsonl` or `unknown-tre.jsonl`, each with one
   sentence of reason. Merge rows into unique trials by PMID, then DOI, then registration number, then normalised title,
   but never merge two rows that carry different registration numbers, even if they share a PMID or DOI: that shared
   publication goes into both trials' publication lists;
   one line per trial listing its reviews and every PMID and DOI merged into it (its publications); |R| is the number
   of unique trials. The header of R says this is an analyst set
   built by a model session, not verified by a person, which tables could not be read and how many trials are unknown.
   If |R| < 10, or unknown trials are more than 25% of R plus unknown, write it: gate 2 cannot be read for the medicine
   question and counts as not passed.
4. **Elicit, medicine** (plan decision 7). `elicit-tre.jsonl` from `elicit-included-2026-09-26.csv` (DOI, NCT, title).
   Fetch each of the five abstracts with one read-only request and label each work `in_scope`, `comparator_differs` or,
   when the abstract cannot decide, `unclear` by the same PICO rule, with the sentence that decides it. Write in the ledger that this set is the five works Elicit
   returned in its "balanced" setting on exactly our question (the owner's statement), with no query or workflow trail.
5. **Scripts, then freeze.** First write every measurement script task 7 needs and run each once on a stored library
   (e.g. `.local/sw-slice17a-acceptance-2026-09-24/data-q1-standard-luna`, `immutable=1`) to see it works. Then
   `protocol.md`: the plan's commit hash and that its "Dondurulmuş beklentiler" section is the expectation;
   the two question texts byte for byte (plan decision 5); the run matrix and order (decision 3); every server's
   environment; the stop rules (rule 5); the gate rules (decision 11) and G1's rule (decision 12); the sha256 of every
   frozen file (reference sets, Elicit copies and labels, the measurement scripts of task 7 as they stand before the first
   run); the analyst-sample seed and the G1 image-sample seed. Ledger entry. Only then write `.local/sw-slice24-active`
   (one line: the folder's path and the plan commit recorded in `protocol.md`); this is the only place it is written.
   A crash before this point leaves the pointer absent (a rerun starts Part A over) or on the previous folder (a rerun
   repeats the resume-or-restart check for that folder). No
   research exists before this line. Freezing
   limits tuning to DEIXIS's results; it does not remove the bias of having seen Elicit's answer, and the result says so.
6. **Runs** (plan decision 3). Fourteen researches, one at a time, in this order for the quantum question and then the
   same for the medicine question: `sw` `standard` r1, `legacy` `standard` r1, `sw` `quick`, `sw` `detailed`, `sw`
   `standard` with the built-in embedding, `sw` `standard` r2, `legacy` `standard` r2. Embedding off everywhere else. Both
   `standard` cells run twice whatever the first run shows; no other research is repeated and no run is added after a
   result is seen. For the embedding research, install through `POST /api/semantic-search/builtin/install`, then
   `PUT /api/semantic-search` `builtin`, in that research's own data directory; its time is written apart. Server
   environment for `sw`: `DEIXIS_SEARCH_WORKFLOW=sw`, `DEIXIS_PROTOCOL_APPROVAL=as_proposed`, `DEIXIS_SEARCH_QUERY=model`,
   `DEIXIS_FULLTEXT_FETCH=auto`, `DEIXIS_FULLTEXT_ADJUDICATION=auto`, `DEIXIS_CITATION_CHAINING=auto`,
   `DEIXIS_ARXIV_SOURCE=auto`, `DEIXIS_CODEX_HOME`; for `legacy` `DEIXIS_SEARCH_WORKFLOW=legacy` and the same model. Create
   the research with `source_scope: academic`, the effort, and the model of rule 5; start discovery; let the fetch and
   reading run; start the answer run once the reading run has finished; wait for it. The drivers of
   `.local/sw-measure-2026-09-24/campaign.py` and `.local/sw-slice17a-acceptance-2026-09-24/live.py` show the calls; write
   your own driver in the campaign folder. After each research save its view, PRISMA-S export
   (`GET /api/researches/{id}/prisma-s?format=json`), queue rows, and the server log; stop the server; wait 2 minutes.
   Every call, status change and pause goes to `log-<slug>.md` and the ledger.
7. **Measure** (plan decisions 9, 10, 12 and the two tables of "Ölçülecekler"). Per research and per reference list:
   the stage counts with the plan glossary's stages (pool, abstract candidate, routed to full text, not read for N,
   planned, with PDF, read, `include`, cited) and denominators (n / |R| for every stage; transition shares only along
   pool → routed → read → `include` → cited, as |later ∩ earlier| / |earlier|), matching and counting as the glossary
   says (each publication of a unit matched by DOI, then PMID, then normalised title; a unit is found if any of its
   publications' works is in the stage; the count is always of units, never of works: one work matching two units
   counts for both, two works of one unit count once; conflicts, split and shared works listed); which query origin found each
   reference work (model, code, second round, chain), from the stored raw provider pages; `scripts/probe_report.py` for
   each `sw` library against its reference set; the missed-work diagnosis (for every reference work not in the pool: in
   OpenAlex by DOI or not; for each stored OpenAlex query, the same search parameter plus `filter=doi:<doi>`; for each
   stored PubMed query, `<query> AND <PMID>[uid]`; written as "covered today", never as what the run saw); K3's N and the open-access idea with the three measures of
   `.local/sw-slice24-plan-2026-09-26/k3_oa.py`; time per stage and parallelism by `.local/sw-measure-2026-09-24/stages.py`'s
   method, calls and tokens by `.local/sw-slice24-plan-2026-09-26/cost_time.py`'s method; queue size from the API next to the
   version-level count of `queue.txt`, and the waiting-for-PDF list; the criterion (does the searched thing stay in it;
   topic parts; `part_without_evidence` share); the answer input's criterion and topic quota; routing (fields, shares,
   chosen, left out) and per-source counts; the Europe PMC count (one read-only request per medicine reference work the
   product found no PDF for: does PMC hold an open full text); the thresholds table's margins; for the arXiv source, the
   downloaded / matched / placed counts, placed blocks KaTeX 0.16.47 cannot render (any one fails G1), and 40 placements
   drawn with the frozen seed (at most 2 per paper, none from slice 22's acceptance sample) rendered with the region drawn
   and read by eye (wrong = another group, or the region deletes a text line; if 40 eligible blocks cannot be drawn,
   G1 is unreadable and the verdict is `off`); with exactly one wrong, read that paper's
   other placements too (at most 10). Report, outside the rule: unplaced blocks by reason with 20 of them read, unmatched
   numbered equations, and how wrong ones spread over papers. The
   Elicit comparison (plan decision 7): E∩D at every stage, the place of loss for every E∖D work, our verified quote for
   every D∖E `include`, E against R; `standard` is the headline column, `quick` and `detailed` beside it; scope
   differences in their own column; Elicit ran "Balanced" in both questions, and `standard` is only the headline column,
   never "the same budget". The decision 10 sample per question, drawn with the frozen seed from the union of the two
   `sw` `standard` runs: 10 `include` decisions, 10 `criterion_not_met` decisions and 10 cited claims; and 10 cited claims
   from the two `legacy` runs. Read each on the PDF page against its stored quotes or anchor and mark serious errors by
   the plan's gate 4 definitions. Units are unique (a work `include`d in both runs is read once, r1's decision). Write
   one line per unit to `analyst-reading.jsonl` (unit, run, page, quote or anchor, verdict, serious or not, one sentence of
   reason). Then a second, separate model session that is not shown the first verdicts reads every unit marked serious and
   5 seeded non-serious units per question; both verdicts go on the line; where the two disagree on "serious", the unit
   counts as serious and the disagreement is listed. Report `probe_report.py`'s arm and signal rows in their own table,
   labelled as its any-of-DOI/OpenAlex-id/title matching; never mix them into the glossary's stage counts or the gates.
8. **Gates** (plan decision 11). Write each of the four gates' verdict with its numbers: gate 1 completion of the ten
   `sw` researches; gate 2 the workflow comparison, readable only when all four `standard` runs of that question finished
   with an answer (pool: `sw` mean ≥ `legacy` mean − max(2, ceil(0.1 × |R|)); cited: `sw` mean ≥ `legacy` mean − 1, and
   when `legacy`'s mean is at least 1, both `sw` runs cite at least one R unit; unreadable when a run is missing, |R| < 10
   or unknown > 25%, and unreadable counts as not passed; written as a descriptive decision rule, never as a statistical
   non-inferiority result); gate 3 evidence integrity; gate 4 the analyst reading (at least 8 unique `include`s and 8
   unique claims per question, else not passed; 2 or more serious errors in either sample of a question stops Part B). No
   extra run for any gate. Write beside them, outside the gates: time against 10 / 15 / 20 minutes, whether PubMed was
   routed and returned records, queue size and the waiting-for-PDF list.
9. **Result.** `docs/product/sw-slice24-results.md`, in Turkish: a short plain summary first (what was run, what came out,
   what it means for the default), then every table next to the plan's frozen expectation, every deviation from
   `protocol.md`, the gates' verdicts, and what was not measured. Each threshold or rule that needs changing becomes a new
   SW entry in `search-workflow-review-2026-09-18.md` (SW18 onward: finding, numbers, the slice to return to), and so do the
   plan's two code findings (the block-labelling constants missing from `thresholds`; the unread `routing.THRESHOLDS`).
   Row 24: `24a bitti; dört kapı geçti` or `24a bitti; kapı N geçmedi; sahip kararı bekliyor` with the headline numbers
   (both keep `24a bitti`, so Part A never runs again); K5's row: the medicine question. If a gate failed, also write D105
   at the top of `docs/decisions.md` ("the default stays `legacy`", the gate, the numbers, Limits).

## Part B — the default and the close

10. `Settings.search_workflow` defaults to `sw` in the dataclass and in `load_settings` (`backend/deixis/config.py:28`,
    `:114`); if G1's rule held in Part A, `arxiv_source` defaults to `auto` in both places (`config.py:54`, `:132`). Update
    the tests and fixtures that assert the old defaults (list each). An existing `legacy` research keeps opening and
    answering as `legacy` (the flag is stored per scope revision).
11. The plan's two code findings: add `LABEL_RUNS`, `LABEL_MAJORITY` and `MAX_LABELLED_PHRASES` to the protocol's
    vocabulary thresholds; make `routing.route()` read `routing.THRESHOLDS` or delete the dict. Protocol-body tests follow.
    No migration, no contract change, `skill_package_hash` unchanged.
12. Documents: README (what `sw` is, `DEIXIS_SEARCH_WORKFLOW`, how to get `legacy`; and correct the stale sentence at
    `README.md:238`, "Real model execution, evidence review and production persistence are not implemented", to what is
    built today), CLAUDE.md's "Runs and steps" (the `sw`
    run kinds and the default), `docs/README.md:17-18`, one line in `docs/product/implementation-plan.md` §9 on the switch,
    and each SW entry's status line in `search-workflow-review-2026-09-18.md`.
13. D105 at the top of `docs/decisions.md`: the default switch, the four gates and their numbers, the plan's four
    departures, and Limits (one machine, one model, two questions, one run per cell except gate 2's two, reference sets not
    ground truth, the medicine set an analyst set, Elicit not a correctness criterion and "Balanced" not an equal budget,
    analyst readings not human verification, G1's image sample not a general reliability bound). Then the remaining SW items: read every SW entry's
    status line; an implemented item that no D carries goes into D105's closing list, an unimplemented one into its "open"
    list. Removing `legacy` is not part of this.
14. Checks: full pytest (report "the known single failure apart, the rest of the full run passed" with counts; the known
    one is `tests/test_documents.py::test_extraction_is_stopped_when_it_exceeds_the_memory_limit`), `npm run build`,
    `npm run lint` (warnings not above 17), Playwright A–O, `git diff --check`, the highest migration still `0054`,
    `skill_package_hash` unchanged, `uv.lock` unchanged. Row 24: `uygulandı, inceleme bekliyor (24b)`.

## Close

Commit nothing. The final message, in Turkish, gives: the plan's commit hash; which part ran; for Part A, what ran and
where it stopped if it stopped, the headline numbers next to the frozen expectations, the gates' verdicts, the new SW
entries, and what was not measured; for Part B, the changed files, the test counts and the D105 summary; in both, every
judgement call and every file created or changed.
