# Task: SW slice 18b: what follows a PDF the person adds

Repo: `/Users/huguryildiz/Documents/GitHub/DEIXIS`. The plan is `docs/product/sw-slice18-waiting-for-pdf.md` and it is
the only source of truth. Build only its section "Dilim 18b" (decisions 1–10). The master file is
`docs/product/sw-status.md`, row 18b. List every place where you used your own judgement.

## Before you start

18b builds on 18a (D99). If `git log` does not show the 18a commit, stop and write "18a is not committed" into row
18b; do not start.

## Rules

1. **Git.** Start with `git pull --ff-only` and work on `main` in the main checkout. Make one commit and run
   `git push origin main`. No branch, no PR, no AI attribution, no co-author. Before the push, run
   `git log origin/main..HEAD --format=%B | grep -i co-authored-by`. Never stash or reset. Leave `TODO.md`, `.vscode/`
   and `scripts/local_index.py` alone. If the slice is not finished, commit nothing: write what remains into row 18b.
2. **Unchanged:** the model contract (`skill_package_hash` stays
   `sha256:7d4e238c3e9feebd451c77fb997aff717a3617008bd4165be56f9fba46bf6fca`), `legacy`, `identity.check`, the fetch
   run, D4's rules for "Find PDF", and D45 / D50's replace and remove actions (18b neither calls nor suggests them). No
   new reason code. One migration, `0052_person_pdf_requests.sql` (the highest today is `0051`).
3. **Nothing is read or decided without a trace.** Every request state change is written in the same transaction as
   what caused it (the attach, the frozen plan, the reading decision). The person's own decisions are never overwritten;
   `human_pdf_wrong` is never withdrawn by this slice (decision 3).
4. **Tests** use no network and no live model. Change an existing test only where the plan's decisions force it
   (the `work_outcome` / `answer_version` rule for works with a person's file, and `read_plan`'s front), and list each
   change with its reason. Playwright A–K must pass, plus a new scenario L and its failure script.
5. **Port 8765 and the product database are off limits.** Live runs go under `.local/`, on another port with their own
   `DEIXIS_DATA_DIR`. The owner supplies the publisher PDF; the live reading model is `gpt-5.6-luna`, or
   `deepseek-flash` if Luna's quota is out.
6. **Python:** `PYTHONPATH=backend:. uv run ...`, native arm64. The known unrelated failure is
   `tests/test_documents.py::test_extraction_is_stopped_when_it_exceeds_the_memory_limit`.
7. **UI:** read `.impeccable.md` before touching `apps/web`; UI strings go through `i18n.ts` / `labels.ts`. Verify
   the new section yourself with a screenshot at desktop and phone width.

## Build

Tasks 1–6 of the plan's "Task taslağı (18b)", in order:

1. The code on attach: a note naming the file, a new row when the file changes, `human_pdf_wrong` speaking only for its
   version, the same helper on the source-row upload with the eligibility check.
2. The reading request: migration `0052`, the states, `queue_person_reading` and all of its callers (attach, worker
   return, worker start, the API's pause and cancel), retry with `attempt`.
3. The plan and the outcome: the front of `read_plan`, asset and page digest in the frozen plan, the checks before the
   call and before the write, the person's-file rule in `work_outcome`, `answer_version` and `answer_versions`.
4. The UI: the "Your files" section with its states, the confirmation panel's new texts, resume / cancel for a paused
   run; Playwright L and its failure script.
5. Acceptance: in the 18a acceptance library, the owner's publisher PDF is confirmed and read live; write the time from
   confirmation to the start of reading and to the result, and the result itself (one work; not a generalisation).
6. Close.

Every decision (1–10) is fixed by a test.

## Close

Write a new D number at the top of `docs/decisions.md` (it names D48's exception for a person's file and the two limits
the plan records: no new file for a single-version work waiting because of its own file, and D50's answer revision
after a library-wide removal). Update the SW11 status line (point 9: the front of the reading order, the response
states, version precedence; no code gate) and row 18b. Run the full pytest suite, `npm run build`, `npm run lint`
(17 warnings), Playwright A–L; check `git diff --check` and the hash. The final message, in Turkish, gives what was
done, the judgement calls, the changed tests, the test counts, and the live measurement next to what was not measured.
