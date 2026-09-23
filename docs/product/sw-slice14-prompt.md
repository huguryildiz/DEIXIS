# Task: SW slice 14: source routing, Semantic Scholar bulk search, two numbers per source (D93)

Repo: `/Users/huguryildiz/Documents/GitHub/DEIXIS`. The master file is `docs/product/sw-status.md`, and the
line-level plan is `docs/product/sw-slice14-source-routing.md`. The owner approved the five decisions in that file on
23 September 2026. The slice writes D93. The slice file is the only source of truth; this prompt sets the rules of
the session. The implementer is Opus · medium. The review is a full one (Codex `gpt-6-sol` · high), so list every
place where you used your own judgement.

## Ground rules

1. **Git.** Run `git pull --ff-only` first and work in the main checkout on `main`. At the end make ONE commit and
   run `git push origin main`. No branch, no PR, no AI attribution, no co-author. Never stash or reset. Leave
   untracked files and the owner's uncommitted `TODO.md` edits alone. If the slice is not finished, or Task 6's
   acceptance fails, commit nothing: write what remains into row 14 of `sw-status.md` and say so.
2. **No model is added.** The method package and the contracts stay untouched, so `skill_package_hash` must be the
   same at the end. Check it before and after with
   `PYTHONPATH=backend uv run python -c "from deixis.domain.skill import package_hash; print(package_hash())"`.
3. **No topic word in product code.** The routing table names OpenAlex fields (Computer Science, Medicine …), never
   words from a question. Fixtures are SYNTHETIC and come from at least two fields.
4. **`legacy` does not change.** `compile_queries`, the legacy Semantic Scholar `/paper/search` request and the
   legacy protocol body stay byte-identical. CORE and SerpApi leave only the sw search (`sw_searchable=False`), as
   Scopus did in D91.
5. **Frozen protocols stand.** A resumed run searches its stored queries on the endpoint each query names. A stored
   Semantic Scholar query with no `endpoint` goes to `/paper/search`. The new routing applies to new scope revisions
   only.
6. **Semantic Scholar pacing stays.** Bulk requests pass through the same D67 gate and the same bounded 429 retries
   as today.
7. **Existing tests.** Change only what the slice file names, and list each change in the final message. The 13f,
   13g and 13h tests keep passing (`test_search_parallelism.py`, `test_search_paging.py`, `test_query_compiler.py`,
   `test_search_query.py`, `test_expansion*.py`, `test_lookup_flow.py`). Tests use no network and no live model.
   Do not start, stop or query the service on port 8765, and do not open the product database.
8. **Live steps.** Only two steps touch the network. Task 1 compares bulk sort orders (at most 18 Semantic Scholar
   requests). Task 6 runs the acceptance. Keep a request ledger for both and pace politely. On repeated 429s, stop
   and report. In the final message, say how many OpenAlex and Semantic Scholar requests each step cost.
9. **Live model.** Task 6 uses `gpt-5.6-luna` · medium over the Codex connection, passed explicitly. If Luna fails,
   for quota or anything else, stop and report. Do not switch models.
10. **Python.** Run it as `PYTHONPATH=backend:. uv run ...` from the repo root. The suite runs in parallel by
    default, in about 2 minutes. These are known and not this slice's: the failure of
    `tests/test_documents.py::test_extraction_is_stopped_when_it_exceeds_the_memory_limit`, and the import errors
    of `test_isolated_pdf_prefetch.py` and `test_p4_eval.py`.

## Read first

- `AGENTS.md`, `CLAUDE.md` and `.impeccable.md` (Task 5 touches the approval card).
- `docs/product/sw-status.md`: rows 13f, 13g, 13h, 13ö and 14, and the review rows dated 2026-09-23.
- The slice file, in full.
- `docs/product/search-workflow-review-2026-09-18.md`, SW3.
- `docs/decisions.md`: D67, D87, D89, D90, D91 and D92.
- The measurements behind the slice:
  - `.local/sw-s2-bulk-probe-2026-09-23/` (`result.md`, `probe.py`, `swagger.json`);
  - `.local/sw-slice14-fields-probe-2026-09-23/` (`fields.py`, `fields.json`);
  - `.local/sw-measure-2026-09-24/` (`result.md`, `quality.py`, `bysource.py`, `quality-*.json`);
  - `.local/sw-slice13h-acceptance-2026-09-23/accept.py`, the acceptance setup to reuse;
  - `.local/sw-vocabulary-experiment-2026-09-23/common.py`, for the three questions and their answer lists.
- Semantic Scholar's own API description (`swagger.json` above, `/paper/search/bulk`). Read it before any live
  request.
- Code:
  - `providers/registry.py`, `providers/semantic_scholar.py`, `providers/common.py` (`send`, the D67 gate),
    `providers/pacing.py`, `providers/query_compiler.py` (`_render`, `_rendered`, `_fit_blocks`,
    `compile_block_queries`, `PLAIN_PROVIDERS`), `providers/query_rules.py`, `providers/openalex.py`
    (`count_works`);
  - `workflow/flow.py` (`_discovery`, `_search_query`, `_approval`, `_approved_vocabulary`, `_search_round`,
    `_read_query`, `_write_query`, `_record_search`, `_expansion`);
  - `workflow/search_query.py` (`compile_queries`), `workflow/expansion.py` (`first_round_records`,
    `searched_additions`), `workflow/protocol.py`, `workflow/views.py`, `workflow/store.py` (candidate writes);
  - `apps/web/src/ProtocolApproval.tsx`, `Transcript.tsx`, `api.ts`, `i18n.ts`, `labels.ts`;
  - `storage/migrations/` (the highest file is `0048`);
  - `domain/rules.py`.
- Tests: `test_provider_roles.py`, `test_search_paging.py`, `test_search_parallelism.py`, `test_query_compiler.py`,
  `test_search_query.py`, `test_expansion_flow.py`, `test_protocol*.py`, `apps/web/e2e/protocol-approval.spec.ts`,
  `apps/web/e2e/model-query.spec.ts`.

## What to build

Build Tasks 1–6 of the slice file in that order. For each task, write its tests before its code.

Task 1 adds no product code. Freeze its rule before sending any request, and write the chosen sort into D93.

## Procedure

1. Run `git pull --ff-only` and `git status --short`. Run the baseline `PYTHONPATH=backend:. uv run pytest -q` and
   record the count. Record `skill_package_hash`.
2. Set row 14 to `uygulanıyor`.
3. Task 1: the sort comparison in `.local/sw-slice14-bulk-sort-<date>/`, with the rule written down before the first
   request.
4. Tasks 2–5, tests first and then code. Run the suite after each task and keep it green.
5. Run `npm run build`, `npm run lint` and the Playwright acceptance suite
   (`DEIXIS_ACCEPTANCE_DIR=/tmp/deixis-acceptance npm run test:acceptance`).
6. Task 6: the live acceptance. If it passes:
   - write D93 at the top of `docs/decisions.md`;
   - run the full test suite and `git diff --check`;
   - check that `skill_package_hash` is unchanged;
   - set row 14 to `uygulandı, inceleme bekliyor`;
   - commit and push.

   If it fails, commit nothing.

## Final message

- Files changed, with the migration number.
- Baseline and final test counts.
- The names of the new tests, and every changed expectation with its reason.
- Task 1's table: sort × effort × origin, verified works in the first 400 and 1,000, and the chosen sort.
- For each question, the routing: probe query, total, field shares, sources chosen and left out.
- For each question and effort:
  - the compiled first-round queries, with the Semantic Scholar bulk text;
  - requests per provider;
  - the two numbers per source;
  - verified works in the pool, against the third measurement's 19 / 25 / 30.
- Discovery time next to the third measurement's.
- Every place where you used your own judgement, with the rule you applied.
- Every deviation from the slice file, with its reason.
- What was "ölçülmedi".
- The live request counts of Task 1 and Task 6.
- Confirmation that the live service and the product database were not touched.
- The commit hash, or why there is none.
