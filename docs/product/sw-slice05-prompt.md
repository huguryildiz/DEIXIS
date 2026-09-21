# Task: SW slice 05 — survey flags, missing abstracts from a second source, and external version links

Repo: `/Users/huguryildiz/Documents/GitHub/DEIXIS`. This is slice 05 of the search workflow build. The master file is `docs/product/sw-status.md`; the line-level plan for this slice is `docs/product/sw-slice05-survey-flag-abstract-lookup-links.md`. That file is the single source of truth for what to build. This prompt only sets the rules of the session. Recommended model: Opus, effort high.

## Ground rules

1. Git: start with `git pull --ff-only`. After that, read-only until the slice is finished. When every task is done and the full test run is green except the one known failure, run `git pull --ff-only` again, then make ONE commit and `git push origin main`. No branch, no PR, no AI attribution, no co-author. Never stash, reset, rebase or check out files. If the slice is not finished, commit nothing: leave the tree passing and write what remains into row 05 of `sw-status.md`. The one sanctioned split is in the slice file ("Bölünme noktası"): Task 6 may be left out, and only Task 6. `TODO.md` and `scripts/local_index.py` may show as the owner's uncommitted work: leave them alone and do not stage them. If any other file you did not touch shows as modified, another session is writing here: stop and report.
2. **Do not touch** `apps/web/`, `contracts/research/`, `methods/deixis-research/`, or any existing migration file. `skill_package_hash` must not change. No model call is added.
3. **The `legacy` workflow must behave exactly as before, and so must its provider requests.** `openalex.SELECT`, `crossref.SELECT` and `semantic_scholar.FIELDS` stay as they are; the reference count is asked for only through `Connector.sw_options` on a paged `sw` read. A legacy protocol body and its digest stay the same. No existing test expectation may change. An existing `sw` test whose SYNTHETIC records have no abstract may be given one in its fixture, because a record without an abstract is now held from screening; name every such fixture change in the final message. If any other existing test fails, the change is wrong or the slice file is; stop and report.
4. **This is the first slice that writes `stage_decisions`.** A flag removes nothing and changes no selection. `derive_selection` is not called. A selection whose origin is `user` is never changed, and a decision row is written only when it differs from the record's current one: a second run must not close a row and write the same one again.
5. **A record without an abstract is never out of scope, by any route.** In an `sw` run it does not reach the screening model, and it stays `pending`.
6. **Only a strong title word takes a record off the screening list.** A self-describing abstract or 150 or more references sets a flag and the record is still screened. The seed pool is not built here.
7. **No topic word in product code.** The word lists are the ones in the slice file, field-independent. OpenAlex `type`, venue names and Semantic Scholar `publicationTypes` are not survey signals. If a test seems to need a field's term in a list, the rule is wrong for that case: report it, do not add the word.
8. **A failed lookup never stops or pauses the run (D18), and this slice opens no `budget_exhausted` path.** Lookup requests, retries included, are counted under `lookup_requests`, never under `provider_requests`. Every Semantic Scholar request goes through the D67 gate in `common.send`.
9. **Slice 03's rules stand.** The sixteen rows of `classify_pair`, the guard that keeps two published records out of one work, the `undone` memory and `undo_json` are not changed; rows are added. A merged link is never split by code.
10. **Do not invent.** The flag rule, the lookup order, the request limit, the wanted-decision table and the two new link rows are complete in the slice file. If a case falls between them, stop and report instead of choosing a workaround. A justified deviation that protects existing behavior is welcome, but name it.
11. No network in tests. The one live step is required, not optional: the count of Task 8 over the two pools under `.local/` (about 235 requests to Semantic Scholar and Crossref), run through `providers/lookup.py` alone, with its output kept under `.local/`. Do not tune a threshold, a batch size or the limit to its result; if the result is poor, say so at the top of the final message. Do not start, stop or restart the service on port 8765, and do not open the product database.
12. Match the surrounding style: comment density, naming, short synchronous SQLite transactions, no `await` inside a transaction. The stored plan step is what makes a resumed run ask nothing twice; `record_lookups` is what makes a second run ask nothing twice.
13. Python runs as `PYTHONPATH=backend:. uv run ...` from the repo root, on the native arm64 venv.
14. Fixture records and questions are SYNTHETIC and from at least two fields. A passing test shows workflow behavior, not the quality of the survey rule or of the links.

## Read first

- `AGENTS.md` — whole file.
- `docs/product/sw-status.md` (rows 02, 03, 04b, 04c and the review log), then `docs/product/sw-implementation-plan.md` §2 and the slice 05 entry.
- `docs/product/sw-slice05-survey-flag-abstract-lookup-links.md` — whole file.
- `docs/product/search-workflow-review-2026-09-18.md` — `## SW5` whole entry including Limits; SW9 point 3 and point 4; SW6 point 4, point 5 and Limits; SW11 points 1 to 3.
- `docs/decisions.md` — D71, D72, D67, D46, D48, D18, D75, D76.
- `.local/quantum-source-comparison-2026-09-18/survey_metadata.py`, if present: the probe the word lists and the 150 threshold come from.
- Code, before editing:
  - `backend/deixis/workflow/flow.py`: `_discovery` whole, `_search`, `_search_pages`, `_expansion`, `_count_probe`, `_checkpoint`.
  - `backend/deixis/workflow/decisions.py` whole and `backend/deixis/domain/reason_codes.py` whole.
  - `backend/deixis/workflow/links.py` whole and `backend/deixis/domain/record_identity.py` (`classify_pair`, `record_kind`, `comparable_title`).
  - `backend/deixis/workflow/store.py`: `upsert_provider_source`, `_store_author_keywords`, `_has_column`, `_insert_mappings`, `_insert_passage`, `candidates`, `work_heads`, `add_usage`, `step`, `finish_step`, `purge_research`, `purge_sources`, `apply_screening_proposal`.
  - `backend/deixis/providers/common.py` (`send`, `ProviderRecord`), `providers/pacing.py`, `providers/registry.py`, `providers/openalex.py`, `providers/semantic_scholar.py`, `providers/crossref.py` (`strip_markup`), `providers/arxiv.py` (`published_doi`).
  - `backend/deixis/storage/migrations/0038_*.sql` (how `selections` was rebuilt for a CHECK), `0039_record_links.sql`, `0042_author_keywords.sql`.
  - `backend/deixis/workflow/protocol.py::build_protocol`.
  - Tests: `tests/test_expansion_flow.py` (how an `sw` run is driven with a mocked transport), `tests/test_record_links.py`, `tests/test_stage_decisions.py`, `tests/test_semantic_scholar_pacing.py`, `tests/test_protocol_record.py`, `tests/determinism_stages.py`.

## What to build

Tasks 1–8 of the slice file, in that order.

## Procedure

1. `git pull --ff-only`, `git status --short`, `ls backend/deixis/storage/migrations | tail -1` (expect `0042_author_keywords.sql`) and `grep -n '^## D' docs/decisions.md | head -1` (expect D76). This slice takes `0043` and D77; if either differs, use the next free number and say so.
2. Baseline: `PYTHONPATH=backend:. uv run pytest -q 2>&1 | tail -3`. Record the numbers; the one expected failure is `tests/test_documents.py::test_extraction_is_stopped_when_it_exceeds_the_memory_limit`, known on this machine and unrelated.
3. Set `sw-status.md` row 05 to `uygulanıyor`.
4. For each task: failing tests first, see them fail, implement, run them.
5. For every function that writes or calls out, ask and cover with a test: what happens when the same call is repeated (a resumed run in the middle of a Crossref chunk; a second discovery run of the same scope: no request for an answered record, no new decision row, no new flag row, no new link row); what happens when a source fails, is rate limited on every attempt, or is out of the research's scope; how the request count behaves with retries; what happens to a record the user already included, excluded, or whose merge the user undid; does the result depend on the order rows or providers arrive in.
6. Task 8: the live count, full test run, `git diff --check`, the `D<NN>` entry, the three SW status lines, row 05, the second pull, then the commit and push.

If the session is running long, use the split the slice file allows and nothing else: finish Tasks 1–5, 7 and 8, leave Task 6 out, say so in row 05 and add a `05b` row for the external links.

## Final message

- Files created and changed.
- Baseline and final test counts, and the exact command used.
- If the live count shows a source answering nothing, or filling almost nothing, say that first.
- The live count for both topics: asked, filled by Semantic Scholar, filled by Crossref, still without an abstract, failed, requests and retries, elapsed time; how many of the 304 arXiv records name another DOI; how many of the 23 `extended_version` pairs resolve to one `paperId`.
- How the Semantic Scholar batch endpoint and the Crossref `relation` and `reference-count` fields were verified.
- Every point where the slice file could not be followed as written, and every deviation you chose, with its reason. Every existing `sw` test fixture you gave an abstract.
- What you did NOT do.
- Which evidence boundaries were touched (expected: two new abstract origins; merges are library-wide and show in legacy researches too, as in D72; the list that reaches the screening model narrows in `sw`).
- Confirmation that the live service and the product database were not touched, and the commit hash.
