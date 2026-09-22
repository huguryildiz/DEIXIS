# Task: SW slice 13g — repair the sw search query, take Scopus out of the search, `detailed` reads 1,000 per query (D90, D91)

Repo: `/Users/huguryildiz/Documents/GitHub/DEIXIS`. The master file is `docs/product/sw-status.md`; the line-level
plan is `docs/product/sw-slice13g-query-repair.md`; the measurement that motivates it is
`.local/sw-vocabulary-experiment-2026-09-23/result.md`. The slice writes decisions D90 and D91. The slice file is
the single source of truth; this prompt only sets the rules of the session. Implementer: Opus · high. The review is
a full one (Fable), so list every place you used your own judgement.

## Ground rules

1. Git: `git pull --ff-only` first, work in the main checkout on `main`, read-only until the slice is finished; then
   ONE commit and `git push origin main`. No branch, no PR, no AI attribution, no co-author. Never stash or reset.
   If the slice is not finished or Task 5's acceptance fails, commit nothing: write what remains into row 13g of
   `sw-status.md` and say so.
2. **The code keeps the word list.** Words come from the question by code, blocks by the rule, the model reviews
   labels (SW17). This slice gives the model no new power; it only bounds two of its label decisions in code.
3. **No topic word in product code.** Every rule reads the question's form and counts. Fixtures are SYNTHETIC and
   from at least two fields.
4. **The method package and the contracts are not touched;** `skill_package_hash` must be unchanged at the end
   (`PYTHONPATH=backend uv run python -c "from deixis.domain.skill import package_hash; print(package_hash())"`,
   before and after). If the labelling instructions in `methods/deixis-research/references/vocabulary-labels.md`
   would have to change, STOP AND REPORT.
5. **`legacy` unchanged:** `compile_queries` and the legacy search path give byte-identical output.
6. **Frozen protocols stand:** a resumed run searches its stored queries; the new rules apply to new runs only.
7. Existing tests: only the changes the slice file names, each listed in the final message. The 13f tests
   (`tests/test_search_parallelism.py` and `tests/fixtures/search_parallelism/`) keep passing. No network in tests,
   no live model. Do not start, stop or query the service on port 8765 and do not open the product database.
8. The only live step is Task 5's acceptance: OpenAlex count and page requests through the vocabulary experiment's
   scripts, a request ledger, polite pacing; stop and report on repeated 429s. The OpenAlex free daily budget ran out
   during the experiment; say how many requests the acceptance cost.
9. Python runs as `PYTHONPATH=backend:. uv run ...` from the repo root; the suite runs in parallel by default
   (about 2 min; `-n 0` for serial). The known failure `tests/test_documents.py::test_extraction_is_stopped_when_it_exceeds_the_memory_limit`
   is not this slice's.

## Read first

- `AGENTS.md`, `CLAUDE.md`; `docs/product/sw-status.md` (rows 04b, 05, 13f, 13g); the slice file whole;
  `.local/sw-vocabulary-experiment-2026-09-23/result.md`, `protocol.md`, `arm_a.py`, `arm_c.py`, `common.py`,
  `score.py`; `docs/decisions.md` D77, D87, D88, D89; `docs/product/search-workflow-review-2026-09-18.md` SW2 and SW3.
- Code: `providers/query_compiler.py` (`_fit_blocks`, `compile_block_queries`), `workflow/expansion.py`
  (`expand`, `second_round_vocabulary`), `domain/expansion.py` (`candidates`, `_holds_any`), `domain/vocabulary.py`
  (`extract`), `workflow/vocabulary.py` (`build_vocabulary`, the labelling application), `flow._vocabulary_labels`,
  `workflow/lookups.py` (`ask_second_sources`), `providers/lookup.py`, `providers/scopus.py`
  (`complete_view_entitled`), `providers/registry.py`, `domain/rules.py` (`SW_READ_LIMIT`); tests:
  `test_query_compiler.py`, `test_expansion.py`, `test_expansion_flow.py`, `test_vocabulary.py`,
  `test_vocabulary_flow.py`, `test_vocabulary_labels.py`, `test_lookup_flow.py`, `test_record_lookups.py`,
  `test_provider_roles.py`, `test_effort_limits.py`.

## What to build

Tasks 1–5 of the slice file, in that order; each task's tests come before its code.

## Procedure

1. `git pull --ff-only`; `git status --short`; baseline `PYTHONPATH=backend:. uv run pytest -q` (record the count);
   record `skill_package_hash`.
2. Set row 13g to `uygulanıyor`.
3. Tasks 1–4: tests first, then code; all green after each.
4. Task 5: the live acceptance on the three questions; if it passes, D90 and D91, full test run, `git diff --check`,
   `skill_package_hash` unchanged, row 13g → `uygulandı, inceleme bekliyor`, commit, push. If it fails, no commit.

## Final message

Files changed; baseline and final test counts; the names of the new tests and every changed expectation with its
reason; per question, today's and the new compiled OpenAlex queries of both rounds, their counts and the verified
works found in the first 1,000 and 2,000 (acceptance: quantum at least 19, packet size at least 4); which question
forms Task 3 recognises; how the Scopus lookup behaves with and without institutional access; every place you used
your own judgement, with the rule you applied; every deviation from the slice file with its reason; what is
"ölçülmedi"; the OpenAlex requests the acceptance cost; confirmation that the live service and the product database
were not touched; the commit hash (or why there is none).
