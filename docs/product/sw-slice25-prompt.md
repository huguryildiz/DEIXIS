# Task: SW slice 25: population and comparator in the criterion, an answer when nothing is included, Europe PMC full text, the medicine re-measurement

**Run this prompt only when row 25 of `docs/product/sw-status.md` names G2 as the owner's choice and A1, B1, C1, D1, E1,
F1, H1** (its status reads `… G2 sahibin seçimi …; A1, B1, C1, D1, E1, F1, H1 önerildiği gibi …`). If row 25 names a
different answer to any of A–H, or none, stop at once and change nothing.

Repo: `/Users/huguryildiz/Documents/GitHub/DEIXIS`, branch `main`, main checkout. The plan is
`docs/product/sw-slice25-pico-criterion.md` **as committed**: find the commit that last changed it with
`git log -1 --format=%H -- docs/product/sw-slice25-pico-criterion.md` and check that
`git status --porcelain docs/product/sw-slice25-pico-criterion.md docs/product/sw-slice25-prompt.md` prints nothing. If
the plan has no commit, or has uncommitted changes, stop and change nothing. Write that hash in your final message. Do not
pull, fetch or change branches to get it. The plan is the only source of truth for this slice. Where it departs from SW21,
SW22 and SW23's "Return to" lines (only two roles; the reading's `partial` rule unchanged; an explicit answer with no model
call instead of an abstract-level answer; Europe PMC's `fullTextXML` rendered to a PDF instead of a PMC PDF, and only after
the four existing lookups) or from slice 24's frozen protocol (the widened reference rule, the gate 1 reading of
decision 9), the plan wins. List every place where you used your own judgement.

**Which part to run.** Read rows 25, 24 and 17.
- Row 25 is `plan`, `dosya hazır` or names the owner's answers without `uygulanıyor`, `uygulandı` or `kapandı`: run
  **Part A** (build).
- Row 25 is `uygulanıyor (25a)`: an earlier Part A stopped; read the working tree, finish Part A, never start over by
  discarding changes.
- Row 25 is `uygulandı, inceleme bekliyor (25a)`: stop and change nothing; the coordinator runs the Sol review.
- Row 25 is `kapandı` (25a reviewed and committed) and row 24 still reads `24a bitti; kapı 1, 2, 4 geçmedi; …`: run
  **Part B** (re-measurement). If row 25 reads `uygulanıyor (25b)` or `25b durdu: …`, resume or restart Part B under the
  plan's decision 7.3 (slice 24's decision 13, with `.local/sw-slice25-active`).
- Row 24 reads `24a bitti; dört kapı geçti (tıp 25b'nin yeniden ölçümüyle)` and row 17 reads `kapandı`: run **Part C**
  (24b). If row 17 is not `kapandı`, stop: Sol · high's final check of row 17 comes first.
- Anything else: stop and change nothing.

## Rules

1. **Git: you never commit.** Do not run `git commit`, `git push`, `git pull`, `git fetch`, `git stash`, `git reset`,
   `git checkout`/`git switch` of another ref, `git rebase` or `git merge`, and create no branch. `git add` nothing. The
   owner's working-tree files stay untouched: `TODO.md`, `.vscode/`, `scripts/local_index.py`, and anything else that is
   not this slice's. In your final message list every file you created or changed (from `git status --porcelain`, minus
   those).
2. **Review rule (owner, D105).** Sol (`gpt-6-sol` · high) blocks only on high-severity findings: at most 3 plan rounds
   and 4 code rounds. You do not run the review; you leave the tree ready for it.
3. **Port 8765 and the live library are off limits.** Every server you start (dry run, Part B) uses its own
   `DEIXIS_DATA_DIR` under `.local/` and its own port; from the live data directory only `codex-home` is used, through
   `DEIXIS_CODEX_HOME`.
4. **Model.** Every live call: connection `codex`, `requested_model` `gpt-5.6-luna`, `reasoning_effort` `medium`. On a
   quota or rate-limit error stop and write where; on `client_timeout` resume once after 10 minutes; never switch model
   or connection.
5. **Python:** `PYTHONPATH=backend uv run pytest …` and `PYTHONPATH=backend:. uv run --no-sync python …`, native arm64.
   Scripts that read stored libraries use `immutable=1` URIs.
6. **Words.** Every number with its sample size, machine and model; one run is one run. An analyst reading is a model
   reading, never a human verification. A reference set and Elicit are lists to compare against, never ground truth.

## Part A — build (25a)

1. **Row.** `sw-status.md` row 25: `uygulanıyor (25a)`.
2. **Method file** (plan decision 2.1): `methods/deixis-research/references/criterion-proposal.md`. Take "population" out of
   rule 4's setting and add its closing sentence; narrow rule 6; add rule 8 (population and comparator parts,
   `question_elements`) and renumber the echo rule to 9 with `deixis.criterion_proposal.v2`; add the two hard cases. Keep
   rule 5 and every count bound. No field name (TRE, quantum) in the text. The plan's sentences are the meaning to keep;
   the final wording is yours.
3. **Contract** (2.2): `contracts/research/criterion-proposal.schema.json` → `const` `deixis.criterion_proposal.v2`,
   required `question_elements` (0–2 items, `role` enum `population` / `comparator`, `words` 1–300, `part` 1–60, closed),
   the new `parts` description; `backend/deixis/domain/contracts.py` `SCHEMA_VERSIONS` (`:60`).
4. **Checks** (2.3): `_check_criterion_proposal(step_input, draft, report)` (`contracts.py:898`, called at `:495-496`) with
   `question_element_unknown_part`, `question_element_not_in_question` (normalised `words` at a word boundary in the
   normalised question text or a `user_steering` entry, with `criterion.norm`), `duplicate_question_element`,
   `question_elements_share_part`. All errors.
5. **Consensus** (2.4): `backend/deixis/workflow/criterion.py` `consensus`: `required_roles` from a 2-of-valid-runs majority;
   the base run chosen by today's rule among the runs that hold every required role (`assert` that one exists); output
   `question_elements` (the base run's, sorted by role) and `required_roles` (sorted); a run without the field reads as
   `[]`. With no required role, every other output field must equal today's byte for byte. Update the module docstring.
6. **Record** (2.5): `CRITERION_ORIGIN_FIELDS` (`workflow/protocol.py:27`) gains both names; `store.frozen_criterion`
   (`workflow/store.py:612-621`) returns both from `origin` with `[]` defaults; `approval.apply_criterion`
   (`workflow/approval.py:282-287`) carries both from the proposal. `decisions.CRITERION_FIELDS` unchanged.
7. **SW22** (plan decision 3): `backend/deixis/api/app.py:956-957`: `pdf_collection` and `legacy` keep the 422; an `sw`
   `answer` with no included work is accepted when the current scope revision has a `completed` `discovery` run, else the
   same 422. `backend/deixis/workflow/flow.py` `_answer` (`:2457`): for `sw`, right after `_answer_start_snapshot` and
   before `_inspect`, with no included head save `no_evidence` with validation `{"ok": true, "issues": [], "reason":
   "no_includable_source", "note": "No work was included at full text when this answer started; no model was asked."}`
   and return. `apps/web/src/api.ts` (`validation.reason?`), `apps/web/src/ResearchView.tsx` (the button at `:491` enabled
   for such an `sw` research when no run is active; the `no_evidence` block at `:631` shows the plan's notice for this
   reason, worded as "No work was included at full text when this answer started", never as "no source met the
   criterion", then `AnswerFlowNote`; the toast at `:211`), `apps/web/src/i18n.ts` (Turkish for both new strings). Read
   `.impeccable.md` first; no new component, no new dependency.
7a. **SW21** (plan decision 3a; the owner's choice G2, route H1). In `backend/deixis/documents/acquisition.py`: a new
   `europepmc_lookup` beside `core_lookup` (`:174`) with the plan's candidate rules (DOI equal, PMCID, `isOpenAccess = Y`,
   `inEPMC = Y`, `authMan = N`; `publishedVersion`; `_version_status`), asked in `acquire_for_source` (`:253`) only after
   the existing verified-candidate loop (`:281-296`) left the record without an asset; its candidates recorded and tried
   by the same rule (`doi_verified` + `match`, `different` only through `_attach_other_version` with `other_versions`), each
   fetched with an injectable `xml_fetcher` (default `fetch.fetch_file(url, ("application/xml", "text/xml"))`,
   `documents/fetch.py:154`), rendered by the new `backend/deixis/documents/jats.py` (`render_pdf`, `is_rendition`; refuse
   `<!ENTITY`; stdlib `xml.etree`; PyMuPDF `Story`; bounded as below) and attached through `_attach_pdf` (`:358`) with
   `retrieved_from` = the `fullTextXML` URL and `original_filename` `<PMCID>.europepmc.pdf` (`_attach_pdf` gains a
   `filename` parameter passed to `add_asset_with_pages`; today it passes `None`). A `wrong_type` fetch result is recorded
   as `wrong_type`; `<!ENTITY` and render failures are recorded as `failed` with error codes `jats_entity_refused` and
   `jats_render_failed`; none of them raises, and the next candidate is tried.
   **Render bounds** (plan decision 3a.5), mirroring `pdf.extract_pdf` (`documents/pdf.py:48-52`, `:256-300`): refuse XML
   over `MAX_XML_BYTES = 5 MiB` in the parent before any parsing (`jats_too_large`); parse and render in a child process
   (`python -m deixis.documents.jats <in.xml> <out.pdf> <max_memory> <max_pages> <max_output>`, temp files, env
   `PYTHONPATH` only) called through `asyncio.to_thread`; `RENDER_TIMEOUT_SECONDS = 60` via `subprocess.run(timeout=)`
   (`jats_render_timeout`); 1 GiB through `pdf._watch_memory` and `MEMORY_EXIT_CODE` 3, `MemoryError` also exiting 3
   (`jats_render_memory`); `MAX_RENDER_PAGES = 200`, the child stops with exit 4 before placing page 201
   (`jats_render_pages`); `MAX_RENDER_BYTES = 30 MiB`, checked by the child (exit 5) and again by the parent on the file
   (`jats_render_output_too_large`); any other non-zero exit, or empty output or output not starting `%PDF-`,
   `jats_render_failed`. Each is recorded as `failed` with that error code; no exception, no asset, temp files removed,
   next candidate tried. `render_pdf` takes the limits as keyword parameters so tests can lower them. `FlowDeps` and
   `flow._find_other_copy` (`workflow/flow.py:2790-2815`) pass `xml_fetcher`; `create_app`'s test seam gets it too.
   Migration `backend/deixis/storage/migrations/0055_europepmc_pdf_provider.sql`: rebuild `pdf_discovery_runs` and
   `pdf_candidates` as `0018_core_pdf_provider.sql` did, with today's columns (`0025`'s `other_title_count` included),
   `europepmc` added to both provider CHECKs and `wrong_type` added to `pdf_candidates.access_status`; copy every row;
   recreate the indexes. Rendition provenance (plan decision 3a.6): one `jats.RENDITION_SQL` recognising the asset by
   `origin = 'download'`, the `fullTextXML` URL pattern and the file name together; every view field that carries a page
   (answer evidence, passage and PDF text document, queue row detail, audit sample, waiting-for-PDF quotes) carries the
   passage's own asset's `rendition`, removed or replaced assets included. In `apps/web/src`, `labels.ts`'s `locatorText`
   becomes the one formatter `pageLocator(page, rendition, printed?)` ("PDF p. {page}" or "Europe PMC text, rendered p.
   {page}"), and every surface that writes a page uses it, messages taking `{locator}` instead of `{page}`:
   `ResearchView.tsx:641-644` (citation label and its Markdown export), `PdfTextDocument.tsx:134-144`,
   `HumanQueue.tsx:56-64`, `:456`, `:464`, `:479`, `AuditSample.tsx:95`, `WaitingForPdf.tsx:225`, the passage sheet and
   the PDF viewer title; Turkish in `i18n.ts`. No search connector, no query arm, no
   change to `providers/registry.py`.
8. **Fixtures and fakes.** `tests/fakes.py:75-90` → v2 envelope with `"question_elements": []`;
   `tests/fixtures/research/step-inputs.json` `E_criterion_proposal` → `output_schema_versions` v2;
   `tests/fixtures/research/fake-outputs.json` (`:764-960`) → the five cases to v2, plus one valid case with both elements
   and one case per new issue code. Every fixture stays SYNTHETIC and field-independent.
9. **Tests** (plan decision 4): contract, method text, `consensus` (i)–(v), flow (origin fields, frozen criterion, approval),
   SW22 API and flow (202 and `no_evidence` + reason + `start_snapshot.included = 0` + no `grounded_answer` call; 422 for
   an `sw` research without a completed discovery, for `legacy` and for `pdf_collection`), and one Playwright case at
   1440 and 390 px (if the fixture server has no `sw` research that reads to zero includes, add the smallest SYNTHETIC
   scenario behind a question marker). Update every test that asserted v1 (`tests/test_criterion_proposal.py:44`, `:110`,
   `tests/test_criterion_flow.py:56`, and whatever else fails for the version or the two origin fields). SW21's tests as
   the plan's decision 4 lists them, with `httpx.MockTransport` and a fake `xml_fetcher` over SYNTHETIC JATS; no test
   touches the network; one test per render bound (5 MiB input refused before the child starts; `timeout=0.001`;
   `max_memory` 100 MiB with a synthetic expanding document, finishing within 30 s like `tests/test_documents.py:112-119`;
   `max_pages=2` with a long body; a small `max_output`; malformed XML), each asserting the candidate row and error code,
   no asset, no temp file left and the next candidate tried; the migration test in `tests/test_migrations.py` (old rows kept, `europepmc` and `wrong_type`
   accepted); one test per locator surface above, a rendered and a plain page each, the Markdown export and an old answer
   citing a removed Europe PMC asset included.
10. **Acceptance** (plan decision 5), scripts and outputs under `.local/sw-slice25-acceptance-<YYYY-MM-DD>/`:
    - Full pytest (report "the known single failure apart, the rest of the full run passed" with counts; the known one is
      `tests/test_documents.py::test_extraction_is_stopped_when_it_exceeds_the_memory_limit`), `npm run build`,
      `npm run lint` (warnings not above 17), the full Playwright suite, `git diff --check`; highest migration
      `0055`; `uv.lock` unchanged; the new `skill_package_hash` written in your final message.
    - **Replay:** for each of the 10 `sw` libraries of `.local/sw-slice24-campaign-2026-09-26-134050/data-*-sw-*`, the three
      stored `criterion_proposal_N` outputs through the new `consensus` give `criterion`, `parts`, `cue_phrases`,
      `exclusion_title_words`, `base_run`, `runs_ok`, `sought_term_in_criterion` byte-identical to the stored `criterion`
      step output, and both new fields `[]`. Anything but 10/10: stop, row 25 `uygulanıyor (25a): replay failed`.
    - **Dry run** (F1): the product's criterion step through `ResearchFlow._criterion`, following
      `.local/sw-criterion-dry-run-2026-09-21/run.py` but with the Codex adapter (`DEIXIS_CODEX_HOME`), Luna medium, its
      own data directory, no provider request; each of the two question texts of slice 24 (byte for byte, from
      `.local/sw-slice24-campaign-2026-09-26-134050/protocol.md`) twice: 12 calls. Pass: medicine `required_roles ==
      ["comparator", "population"]` in both consensus results, both elements' `words` taken from the question, both parts'
      definitions about the paper's own participants and own comparison group. Quantum: `required_roles == []` in both
      results, and then slice 24's quantum results stand; otherwise stop and write row 25 `uygulanıyor (25a): quantum
      criterion names <roles>; sahip kararı` with the proposals. Count and report quantum single runs that list any element.
    - **Europe PMC live check** (plan decision 5.4): the frozen sample of
      `.local/sw-slice25-plan-2026-09-26/epmc-sample.json` (PMC7262456, PMC10609268, PMC8308240, PMC11279456,
      PMC6682944, PMC8157764, PMC10708421; all pass the candidate rule), each by its DOI through the product's lookup,
      fetch, render and extraction in an empty data directory; read-only requests to Europe PMC only, one at a time. Pass
      7/7 (asset, page passages, title and first abstract sentence found in the rendered text, "rendered" on every
      locator, one page image read at 1440 px); any failure stops with its cause written.
11. **Documents.** D106 at the top of `docs/decisions.md` (plan decision 6: decision, the replay and dry-run numbers,
    Limits). In `docs/product/search-workflow-review-2026-09-18.md`: SW21's, SW22's and SW23's status lines ("implemented in slice
    25 (D106); measured live in 25b"); a new SW26 after SW25 (plan's number 3: study protocols without results read as
    `include`; 3 of 17 unique medicine includes; return to the full-text reading's outcome part). Row 25:
    `uygulandı, inceleme bekliyor (25a)` with the headline numbers. Nothing else in `sw-status.md`.

## Part B — the medicine re-measurement (25b)

Follow the plan's decisions 7, 8 and 9 exactly; slice 24's plan (`docs/product/sw-slice24-measurement-campaign.md`) and
prompt (`docs/product/sw-slice24-prompt.md`, Part A tasks 3–8) give the method wherever the plan says "the same".

12. **Row and folder.** Row 25 `uygulanıyor (25b)`. Create `.local/sw-slice25-remeasure-<YYYY-MM-DD>-<HHMMSS>/` (a name that
    never existed). Copy from `.local/sw-slice24-campaign-2026-09-26-134050/` the files decision 7.1 lists and check every
    one listed in its `frozen-sha256.json` against that file; stop on any mismatch. The copies include `post.py`,
    `missed.py`, `net.py`, `measure.py` and `gates.py`; `post.py`, `measure.py` and `gates.py` are only the base of the
    diffs and are never run in 25b. Start `ledger.jsonl`. Check
    `git diff --stat <25a commit> -- backend apps/web contracts methods` is empty; the 25a commit is the one that closed
    row 25.
13. **Reference set** (decision 8): the literal query with this day as the end of `edat`, paging, `esummary`, order; (a)–(g)
    per candidate with each decision and reason in the ledger; tables only from PMC open full text or the publisher's open
    page, `table_unavailable` otherwise; no reference-list fallback; the trial decision tree and the glossary's merge; stop
    after a finished table once at least three tables are read and |R| ≥ 10, or at 30 candidates. Write
    `reference-tre.jsonl`, `comparator-differs-tre.jsonl`, `unknown-tre.jsonl` with the header of decision 8.6. If |R| < 10
    or unknown > 25%: stop before any research, row 25 `25b durdu: |R| = <n>`, and write why.
14. **Freeze** (decisions 7.4, 7.5, 9): `measure25.py` as slice 24's `measure.py` plus `validation_reason` on every
    answer, and `gates25.py` as slice 24's `gates.py` with one shared `answered`/`finished` check (accepts
    `structurally_valid`, or `no_evidence` with `validation_reason = no_includable_source` on an `sw` research only) used
    by gates 1 and 2, citations counted as measured (0 without evidence links), quantum read from the slice 24 folder and
    medicine from this one; nothing else changes; `measure25.diff`, `gates25.diff`, and `gates25_selftest.py` run on fake
    measurement files for five cases (valid, `sw` no-include, `legacy` `no_evidence`, `sw` `no_evidence` with another
    reason, and an answer without the `validation_reason` key, which must stop `gates25.py` by name) before the freeze;
    `post25.py` as slice 24's `post.py` with exactly three changes (plan decision 9): it runs `measure25.py` instead of
    `measure.py`; right after the measurement is written, before `probe_report.py` and `missed.py`, it reads
    `m-<slug>.json` and exits non-zero if any entry of `misc.answers` lacks the `validation_reason` key (an empty list is
    not an error); `HERE` is the new folder (same code, the copy's location). The self-test also runs `post25.py`'s check
    on a keyless measurement and expects a non-zero exit. Freeze `post25.diff` beside `measure25.diff` and `gates25.diff`; `protocol.md` (this plan's commit, the 25a commit, the `skill_package_hash` from a dry
    server start, the question, matrix, ports 8858–8864, server environment, stop rules, gates as re-read, seed `2409261`,
    every frozen file's sha256); ledger entry; only then write `.local/sw-slice25-active` (folder path and plan commit).
15. **Runs:** the seven medicine researches in slice 24's order, one at a time, 2 minutes apart, with slice 24's server
    environment and driver; the embedding research installs the built-in model in its own data directory first. Start the
    answer run once the reading run has finished, as slice 24 did; with 25a a zero-include `sw` research now ends with the
    explicit answer. After each research save its view, PRISMA-S export, queue rows and server log; stop the server.
16. **Measure** each research with `post25.py <slug>` (which runs `measure25.py`, `probe_report.py` for `sw` and
    `missed.py`), then `gates25.py` once all seven are measured; nothing runs slice 24's `post.py` or `measure.py`. Against
    the new R and Elicit's five: stage counts by the glossary, query origin,
    `probe_report.py`, missed-work diagnosis (PubMed only if OpenAlex's keyless budget is spent; write it), K3, time, calls,
    tokens, queue, waiting-for-PDF, Europe PMC count, routing; plus decision 7.6's items (each consensus's `required_roles`;
    what became of the plan's 17 works; zero-include researches; `part_without_evidence` beside slice 24's). The analyst
    sample and second reading exactly as slice 24's decision 10 with seed `2409261`, from the union of this campaign's two
    `sw` `standard` runs.
17. **Gates and result.** `gates25.py` → `gates.json`. `docs/product/sw-slice25-remeasure-results.md` in Turkish: a short
    plain summary first, then every table beside the plan's frozen expectation (decision 7.7), every deviation from
    `protocol.md`, the gates' verdicts, what was not measured. SW18's status line (the rule used, |R|). Row 25 `kapandı;
    25b bitti` with the headline numbers. Row 24 (replace only its leading status phrase and keep the rest of the cell,
    including `A1, B1, C1, D1, E1, F1, G1, H1, I1 önerildiği gibi`, which slice 24's prompt checks):
    `24a bitti; dört kapı geçti (tıp 25b'nin yeniden ölçümüyle)` if all four pass; otherwise
    `24a bitti; kapı N geçmedi (25b); sahip kararı bekliyor` and D107 at the top of `docs/decisions.md`
    ("the default still stays `legacy`", the gate, the numbers, Limits). If gates 2 or 4 fail on medicine and the loss is
    at the PDF stage, write where the loss sits (not in the Europe PMC open subset, author manuscript, or later) and leave the next step to
    the owner.

## Part C — 24b

18. Run tasks 10–14 of `docs/product/sw-slice24-prompt.md` (Part B) as written, with three changes (plan decision 10): the
    decision written at the top of `docs/decisions.md` is the next free number (D107 when 25b passed; D105 stays as it
    is); the medicine numbers come from `docs/product/sw-slice25-remeasure-results.md`; SW21, SW22 and SW23 are closed by D106
    and go into neither the closing nor the open list. Its own checks apply, `skill_package_hash` is the one
    25a set, and the highest migration is `0055`, not `0054`.

## Close

Commit nothing. The final message, in Turkish, gives: the plan's commit hash; which part ran; for Part A the changed files,
the test counts, the new `skill_package_hash`, the replay result, the dry run's roles per question and the Europe PMC
live check; for Part B the
reference rule's |R| and tables, what ran and where it stopped if it stopped, the headline numbers next to the frozen
expectation, the gates' verdicts, and what was not measured; for Part C the changed files, the test counts and the decision
summary; in every part, each judgement call and every file created or changed.
