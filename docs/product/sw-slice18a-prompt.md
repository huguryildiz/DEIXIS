# Task: SW slice 18a: waiting-for-PDF list, institution proxy, confirmed match

Repo: `/Users/huguryildiz/Documents/GitHub/DEIXIS`. The plan is `docs/product/sw-slice18-waiting-for-pdf.md` and it is
the only source of truth. Build only its section "Dilim 18a" (decisions 1–6); section "Dilim 18b" is out of scope. The
master file is `docs/product/sw-status.md`, row 18a. List every place where you used your own judgement.

## Rules

1. **Git.** Start with `git pull --ff-only` and work on `main` in the main checkout. Make one commit and run
   `git push origin main`. No branch, no PR, no AI attribution, no co-author. Before the push, run
   `git log origin/main..HEAD --format=%B | grep -i co-authored-by`. Never stash or reset. Leave `TODO.md`, `.vscode/`
   and `scripts/local_index.py` alone. If the slice is not finished, commit nothing: write what remains into row 18a.
2. **Unchanged:** the model contract (`skill_package_hash` stays
   `sha256:7d4e238c3e9feebd451c77fb997aff717a3617008bd4165be56f9fba46bf6fca`), `legacy` (its `/uploads/match` answers
   with today's candidates and today's shape, and its `PdfReadiness` flow stays), `identity.check`, the fetch and
   reading runs, their codes and plans, and D4's rules for "Find PDF". No new reason code. No code or reading run is
   written on attach (that is 18b). No migration expected (the highest is `0051`); the proxy address lives in
   `app_settings`.
3. **Nothing is attached without the person.** The match proposes a work; the person picks the version and confirms.
   The app never sends a request through the proxy and never downloads in bulk.
4. **Tests** use no network and no live model. Change an existing test only where the plan names it, and list each
   change. Playwright A–J must pass, plus a new scenario K (waiting work → drop a file → pick the version → confirm →
   the work leaves the list).
5. **Port 8765 and the product database are off limits.** Live runs go under `.local/`, on another port with their own
   `DEIXIS_DATA_DIR`. The owner chooses the model and supplies the real publisher PDF for acceptance.
6. **Python:** `PYTHONPATH=backend:. uv run ...`, native arm64. The known unrelated failure is
   `tests/test_documents.py::test_extraction_is_stopped_when_it_exceeds_the_memory_limit`.
7. **UI:** read `.impeccable.md` before touching `apps/web`; UI strings go through `i18n.ts` / `labels.ts`. Verify
   the new view yourself with a screenshot at desktop and phone width.

## Build

Tasks 1–6 of the plan's "Task taslağı (18a)", in order:

1. The list: `fulltext.waiting(works, plan)` and its view.
2. The proxy setting and link builder (both forms, the `&` / `#` / DOI special-character cases, the rejected addresses).
3. The match: the `sw` candidate set, the versioned answer, the multi-DOI rule, the file bound from match to
   confirmation (`sha256`, scope revision, membership, a PDF already in use).
4. The UI: the "PDF bekliyor" view beside the human queue, rows, links, drop, version-picking confirmation.
5. Acceptance: one `sw` run, the owner's publisher PDF dropped and confirmed; rerun
   `.local/sw-slice18-plan-2026-09-24/waiting.py` after the multi-DOI rule and report the two measured wrong matches.
6. Close.

Every decision (1–6) is fixed by a test.

## Close

Write a new D number at the top of `docs/decisions.md`; update the SW10 status line (points 4–5 in part), the SW11
status line (point 9: matching here, the rest in 18b) and row 18a. Run the full pytest suite, `npm run build`,
`npm run lint` (17 warnings) and Playwright A–K; check `git diff --check` and the hash. The final message, in Turkish,
gives what was done, the judgement calls, the changed tests, the test counts, and the live measurement next to what
was not measured (the proxy login at least).
