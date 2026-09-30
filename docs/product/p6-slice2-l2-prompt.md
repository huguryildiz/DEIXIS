<!-- PLAN-REVIEW-ROUNDS: gpt-6.1-sol high, r1: hazır değil, 1 high (year rule limited to 19xx/20xx, narrower than the note) + 4 medium (import allow-list missing intra-package imports; packing default described two ways; unassessed_edges confused not-scanned with not-found; missing counter-example tests), all folded in; r2: hazır, 0 high; implementation by gpt-6.1-sol; code review rounds: see D132 -->

# Task: P6 slice 2, batch L2, model-free candidates, citation edges and field baseline (pure functions)

You work in the worktree `/Users/huguryildiz/Documents/GitHub/DEIXIS-l2` (detached at `7cd6820`, main with D131). Read
`AGENTS.md`, `CLAUDE.md`, `docs/decisions.md` D130 and D131 (top), and `docs/product/p6-slice2-chain-of-ideas.md`:
§3 (rules), §4.1, §4.3 ("Aday bulma", "Adaylar"), §4.4, §9 (first two bullets), §10, §12 "Aday bulma ve kenar" and "Alan
tabanı", §18 questions 2 and 3, §19 "L2". The scope below was decided by the main session and binds this prompt; where the
code differs from what this prompt says, report it. Also read `backend/deixis/workflow/source_keys.py` (you reuse its
`_ascii`, `_PARTICLES`, `_SUFFIXES`, `_TITLE_STOPWORDS`) and the `answer_versions` docstring in `workflow/store.py` (D48 order).

**No git state-changing commands** (no add, commit, stash, checkout, reset, branch, worktree). Leave every change
uncommitted. Do not invent; report what you could not find. **No real-model calls, no provider calls, no measurement.** Do
not touch `../DEIXIS`, `.local/`, `TODO.md`, `.vscode/`, `scripts/local_index.py`, `docs/product/sw-status.md`, ports 8765
and 8858-8864. Backend tests need `PYTHONPATH=backend:.` and `UV_CACHE_DIR=/tmp/deixis-uv-cache`. No web work in this batch.

## Why

Slice 2 links works by evidence in the later work's own passages. Before any model step exists, code has to (a) find which
earlier work a later work's passages mention (a candidate, never a link), (b) derive the stored-citation edge state of a pair,
and (c) compute the small field baseline from stored numbers. L2 builds these as **pure** functions over snapshots that the
caller hands in. L5 (flow) and L6 (assembly) read the database and call them later. Nothing in L2 reads or writes the
database, calls a model or a provider, or touches flow, API, storage or web.

## What is and is not in code (checked on 7cd6820)

- `backend/deixis/workflow/lineage/` does not exist. `workflow/tables.py` has `LINEAGE_ROLE_COLUMNS` (L1); L2 does not need it.
- `source_keys.py` has `family_name(author)` (joins hyphenated parts, drops particles/suffixes, **truncates to 10 characters**),
  `_ascii` (Unicode fold), `_PARTICLES`, `_SUFFIXES`, `_TITLE_STOPWORDS`. Authors are stored as a list of strings
  (`"Family, Given"` or `"Given Family"`).
- `Store.passages_for(svid)` returns dict rows with `id`, `kind` (`abstract`/`pdf_page`/`section`), `physical_page`, `text`.
  `record_references(source_version_id, referenced_id)` holds OpenAlex short ids (`W…`); `source_versions.references_read`
  says the list was read; OpenAlex ids live in `identifier_mappings(scheme='openalex', value='W…')`;
  `source_versions.cited_by_count`, `cited_by_count_at`, `publication_type` (OpenAlex `type`, e.g. `review`) exist.
- D48 order among the versions of one work: the head first, then the others with an active asset before those without, then by
  membership `created_at`.
- No lineage tables, runs, contracts or model step exist (L3-L5). L2 adds none.

## Decisions (already taken; do not reopen)

1. **Package.** New `backend/deixis/workflow/lineage/` with `__init__.py` (docstring only, no re-export logic beyond plain
   imports), `mentions.py`, `edges.py`, `candidates.py`, `baseline.py`. Plain frozen dataclasses and functions. No class holds
   state. Imports allowed: standard library, `deixis.workflow.source_keys` and the other modules of `deixis.workflow.lineage` (for example `candidates` imports `PassageText` from `mentions` and `edge_state` from `edges`). **Forbidden imports** (a test asserts it by
   reading the module source with `ast`): `sqlite3`, `httpx`, `deixis.providers`, `deixis.models`, `deixis.workflow.store`,
   `deixis.workflow.flow`, `deixis.storage`, `deixis.api`. Every function is deterministic: same input, same output, no clock,
   no randomness, no I/O, no mutation of its arguments.
2. **Text normalization (`mentions.py`).** `NORMALIZATION_VERSION = "lineage-mentions-v1"`. One function turns any text
   (passage, surname, title) into tokens: `source_keys._ascii`, `casefold`, split on every run of non-alphanumeric characters
   (hyphens, en dashes, dots, commas, brackets are separators). The **normalized text** is the tokens joined by one space;
   **the 60-character gap is measured in that string** (record this in a module constant `MENTION_TEXT_DEFINITION`). Surname
   and passage go through the same function; matching is on whole tokens (a token inside a longer token never matches:
   `Li` does not match `Lin`).
3. **Surname.** A function `surname_tokens(author: str) -> tuple[str, ...]` mirrors `family_name`'s rules **without the
   10-character truncation**: `"Family, Given"` takes the part before the comma, else the last token after dropping
   `_SUFFIXES`; the family part is split on hyphens; `_PARTICLES` are dropped (kept if that would leave nothing); each word
   goes through the token function, so `Smith-Jones` gives `("smith", "jones")` (matched as that consecutive token sequence),
   `de la Cruz` gives `("cruz",)`, `Müller` gives `("muller",)`. The surname used is the **first author with a non-empty
   surname** of the `from` record. No authors or no usable surname: no surname search, only the title search.
4. **Surname plus year mention.** A hit is an occurrence of the surname token sequence followed by a year token whose start
   lies at most 60 characters after the surname's end (gap = characters strictly between them in the normalized string; the
   year must **follow** the surname: this is a recorded judgement, `Smith (2015)`, `Smith et al., 2015`, `(Smith and Jones,
   2015)` are the target forms, year-before-surname is not searched). A year token is **any four digits** (no century limit, `1873` counts) optionally
   followed by one lowercase letter (`2015a`); the accepted set is `{year} ∪ years`: the `from` record's own year plus the
   years of other versions of the same work, both passed in (`year` and `years` are separate parameters; `years` may be empty). `et al.` is not required and not penalised (tokens `et al` are just text in the
   gap). Each surname occurrence that has a matching year within the gap counts once.
5. **Title fragment.** Title and passage tokens with `_TITLE_STOPWORDS` removed (from both sides, order kept); a hit is a
   maximal run of **at least five consecutive** tokens of the title sequence appearing consecutively in the passage sequence
   (implement with 5-grams; count maximal runs, not windows). A title with fewer than five significant tokens never produces a
   title hit (recorded limit: short titles are not searched). Works without a usable surname are searched by title only.
6. **Mention result.** `find_mentions(prepared_passages, target) -> Mention | None` (None when no passage has a hit).
   `Mention` carries `from_source_version_id`, `total` (sum of all hits over all passages), `hits` (every passage with at least
   one hit: `passage_id`, `surname_year`, `title_fragment`, `count` = their sum, `physical_page`), `basis` (subset of
   `("surname_year", "title_fragment")`, fixed order) and `mention_passage_ids`: at most 3, **never empty**, ordered by `count`
   descending, then `physical_page` ascending with `None` (abstract) first, then `passage_id` ascending. Passages are prepared
   once per later work (`prepare_passages`) so the `from` loop does not renormalize. A reference-list passage can match: L2
   does not filter it (the model step, L3, is told not to count it as relation evidence). Numbered citations (`[12]`) are a
   known blind spot; a test documents that they are missed.
7. **Rules record.** `mention_rules() -> dict` returns a JSON-serialisable dict: `normalization_version`, `text_definition`,
   `gap_chars` (60), `min_title_tokens` (5), `max_mention_passages` (3), `year_position` (`"after_surname"`), the sorted
   stopword list. L5 will store it in the run plan. A test pins the keys and the values above.
8. **Edges (`edges.py`).** `EDGE_STATES = ("present", "absent_in_read_list", "unresolved", "not_read")`. Input snapshots:
   `EdgeTo(source_version_id, work_id, references_read, referenced_ids)` and `EdgeFrom(source_version_id, work_id,
   openalex_ids)`. `edge_state(to, frm) -> str`: `not_read` when `references_read` is false (whatever the set holds);
   else `unresolved` when `frm` has no OpenAlex id; else `present` when any of `frm`'s ids is in `referenced_ids`; else
   `absent_in_read_list`. OpenAlex ids are normalized before comparing (strip, keep the part after the last `/`, upper-case
   the leading letter, so `https://openalex.org/w123` equals `W123`). `unexpected_no_citation_edge(state) -> bool` is true
   **only** for `absent_in_read_list`. `derive_edges(tos, froms)` returns `Edge(to_source_version_id, from_source_version_id,
   state)` for every ordered pair in input order (to-major), skipping the same version and the **same work**; `edge_counts(edges)`
   returns the four counts (all four keys always present, zero included). `unassessed_edges(edges, candidate_pairs,
   scanned_targets, excluded_pairs=frozenset())` returns the edges with state `present` whose later work **was scanned**
   (`to_source_version_id in scanned_targets`) and whose `(from, to)` is neither a candidate pair nor an excluded pair,
   preserving order. An edge whose later work was not scanned (no PDF text, or not among the chosen targets) is **not
   found-without-mention**: it is not unassessed here, and L2 does not decide how L5/L6 show it. An edge never creates a candidate or a link: no function in `edges.py` returns anything
   usable as one.
9. **Candidates (`candidates.py`).** Snapshot `LineageWork(source_version_id, work_id, position, title, authors, year, years,
   references_read, referenced_ids, openalex_ids, passages)` with `passages` a tuple of `PassageText(passage_id, kind, text,
   physical_page)` (defined in `mentions.py`). `eligible_targets(works)`: works with at least one `pdf_page` passage, in
   `position` order (this is the "PDF text stored" rule; it says nothing about the text having been reviewed).
   `find_candidates(works, targets=None, excluded_pairs=frozenset())` returns a `CandidateSet(candidates, no_candidate_targets, scanned_targets)` (`scanned_targets` = the source version ids of the targets actually scanned):
   for each target (default `eligible_targets`) in `position` order, every other work of a **different work id** whose pair is
   not in `excluded_pairs` (the pair key is `(from_source_version_id, to_source_version_id)`; the parameter is the human-decided
   hook, empty for now) and that the mention finder matches becomes a `Candidate(to_source_version_id,
   from_source_version_id, to_position, from_position, total_matches, basis, mention_passage_ids, edge_state,
   year_order_warning)`. `edge_state` comes from `edges.edge_state`. `year_order_warning` is true when both record years
   are known and the later work's year is before the earlier's; the candidate is still produced (a warning, never a rejection).
   **Priority key, one only:** within a target, `total_matches` descending, then `from_position` ascending, then
   `from_source_version_id`; the packing uses the same order. A target with no candidate is listed in
   `no_candidate_targets` (it is never sent to the model). The same pair in two separate calls (tables are separate) is
   independent because the function has no shared state; a duplicate work row in the input (same `source_version_id` twice) is
   dropped after its first occurrence.
10. **Packing (`candidates.py`).** `pack_candidates(candidates, fits=None, max_per_chunk=8, max_chunks=3) -> Packing(chunks,
    not_sent)` over **one target's** candidates in priority order: fill the current chunk strictly in order while it has fewer
    than `max_per_chunk` candidates and `fits(chunk_plus_candidate)` (when given) is true; when the next candidate does not
    fit, close the chunk and open the next one; when it does not fit **alone** in an empty chunk, it goes to `not_sent` with
    reason `too_large_for_one_call` and packing continues with the next candidate; once `max_chunks` chunks exist and are
    closed, every remaining candidate goes to `not_sent` with reason `beyond_call_limit`. `NotSent(candidate, reason)`;
    constants `NOT_SENT_REASONS`. Nothing is dropped silently: `sum(len(chunk)) + len(not_sent) == len(candidates)` always, and
    the concatenation of the chunks plus the not-sent keeps the input order within each group. With `fits=None` packing is **count-only** (8 per chunk, 3 chunks), which the docstring says. `passage_budget_fits(passage_chars,
    max_passages=24, max_chars=48_000)` returns a `fits` predicate the caller passes explicitly counting **unique** mention passages and their total text
    length from the `passage_chars` mapping (passage id to character count); constants `MAX_CANDIDATES_PER_CHUNK = 8`,
    `MAX_CHUNKS_PER_TARGET = 3`, `MAX_PASSAGES_PER_CHUNK = 24`, `MAX_CHARS_PER_CHUNK = 48_000` live here. L5 will supply its own
    `fits` built from the real StepInput message size (the 48,000 limit applies to the message there, not to this proxy);
    say so in the docstring. `NotSent` results become the recorded `not_sent_budget` state in L5 (the code names `too_large_for_one_call` and `beyond_call_limit` are the reasons kept). No 25-work limit here: L5 owns run planning.
11. **Field baseline (`baseline.py`).** Snapshots: `BaselineVersion(source_version_id, work_id, is_head, has_active_asset,
    created_at, cited_by_count, cited_by_count_at, publication_type, references_read, referenced_ids, openalex_ids)` (all the
    **current included** versions of the table; the caller has already applied inclusion). `field_baseline(versions) ->
    FieldBaseline`. Per work, the **representative** is the first version in this order: `is_head` first, then
    `has_active_asset` first, then `created_at` ascending, then `source_version_id`. Count, count date and type come **only**
    from the representative; no gap is filled from another version. `representatives`: for every work, `(work_id,
    source_version_id, reason, versions_considered)` with `reason` `"head"` when the representative is the head else
    `"other_version"`, ordered by `work_id`. Two lists, each a full ordered tuple of `BaselineEntry` plus `SHOWN = 5` and
    properties `shown` (first five) and `total`:
    - `most_cited_in_corpus`: representatives with a **known** (not None) count, `cited_by_count` descending then `work_id`
      ascending. `unknown_count_works`: how many works have a representative with no count; unknown is never zero and never
      enters the sort.
    - `review_in_corpus`: representatives whose `publication_type` equals `review` ignoring case, `work_id` ascending. The
      module constant `REVIEW_NOTE` reads exactly: `Registered type: review. Which provider wrote the type is not stored.`
    `BaselineEntry(work_id, source_version_id, cited_by_count, cited_by_count_at, publication_type, cited_by_included)` with
    `cited_by_included: IncludedCitations(count, other_works, lists_read, target_resolved)` for **every** entry of both lists:
    the target's identity is the union of the OpenAlex ids of all its included versions (identity, not a gap fill; say so in the
    docstring); `other_works` = included works other than the target; `lists_read` = other works with at least one version whose
    list was read; `count` = number of distinct other works with a read version whose `referenced_ids` contain any target id;
    `target_resolved` = the target has at least one OpenAlex id. `count` is `None` when the target is not resolved **or**
    `lists_read == 0` (a missing or unread list is never read as zero); otherwise an int over the read lists only. Versions
    count once per work (never inflate by versions). The word `foundational` and the Turkish `kurucu` appear in no string
    constant, field name, docstring, or return value of the package (a test scans the module sources and the repr of a full
    result). The baseline never calls a model, a provider or the database, and does not rank or score quality.
12. **No other files.** No edit of any existing source file. `backend/deixis/workflow/lineage/__init__.py` is new.

## Files allowed

`backend/deixis/workflow/lineage/{__init__,mentions,edges,candidates,baseline}.py` (new),
`tests/test_lineage_mentions.py`, `tests/test_lineage_edges.py`, `tests/test_lineage_candidates.py`,
`tests/test_lineage_baseline.py` (all new; the plan names three files, the candidates and packing tests get their own file
as a recorded judgement), `docs/decisions.md` (D132 at the top, see below), `docs/product/p6-slice2-chain-of-ideas.md` (only the L2
heading line, see below), and this prompt's comment line.

## Files NOT allowed

Everything else, in particular `backend/deixis/workflow/tables.py`, `store.py`, `flow.py`, `workflow/report/*`, `api/*`,
`domain/*`, `methods/**`, `contracts/**`, `storage/**`, `tests/fakes.py`, `tests/fixtures/`, `apps/web/**`, `scripts/`. If the
work needs one of these, stop and report.

## Tests to add (name them so the limit is readable; all synthetic, no database, no network)

`tests/test_lineage_mentions.py`:
1. `test_surname_year_mention_found_in_common_citation_forms`: `Smith (2015)`, `(Smith et al., 2015)`, `Smith and Jones, 2015`
   (first author Smith), `Smith 2015a`; gap of exactly 60 found and 61 not found (build the text to the character; assert on
   the defined normalized string).
2. `test_year_must_follow_surname_and_match_a_known_year`: `2015 Smith` alone is not a hit; a year in neither `year` nor `years`
   is not a hit; a year of another version of the same work (`years`) is; `year=2015, years=()` and `year=1873, years=()`
   (`Waals 1873`) both hit through the record's own year.
3. `test_surname_normalization_particles_suffixes_hyphen_and_accents`: `de la Cruz`, `van der Berg`, `Smith Jr.`, `Smith-Jones`
   (matches only as the consecutive pair), `Müller` vs `Muller`, `Nakano, H.`, an author longer than ten letters matches in
   full (not truncated): `Wojciechowski (2019)`.
4. `test_token_boundaries_no_inside_token_matches`: `Li` does not match `Lin 2015` or `Liu`; `Smith` does not match `Smithson 2015`.
5. `test_title_fragment_five_consecutive_significant_tokens`: a five-token run found; four not; stopwords ignored on both
   sides (a title with `of`/`the` inside is found when the passage has them at different places or not at all); a title with
   fewer than five significant tokens never matches; a run longer than five counts once.
6. `test_work_without_authors_is_searched_by_title_only_and_without_surname_by_no_surname_search`.
7. `test_numbered_citations_are_missed`: a passage `as shown in [12]` with the reference list elsewhere gives `None`
   (documents the known blind spot).
8. `test_mention_passages_are_at_most_three_never_empty_and_stably_ordered`: five matching passages, equal counts, pages
   and ids decide; `None` page first; ties reproducible under shuffled input order; `total` is the sum over all hits.
9. `test_mention_rules_record_is_pinned`: `mention_rules()` keys and values of decision 7, JSON round-trip equal.
10. `test_package_imports_no_database_provider_or_model`: `ast`-read every module of `deixis.workflow.lineage` and assert none
    of the forbidden imports (decision 1) appears (also `import x.y`/`from x import y` forms).
11. `test_functions_do_not_mutate_inputs_and_are_deterministic`: run twice on the same snapshot, equal results, inputs equal to
    deep copies taken before.

`tests/test_lineage_edges.py`: `test_edge_four_states` (each state, including `references_read` false with a set that would
match, and several ids on the earlier work), `test_openalex_id_normalization_in_edges` (URL and lower-case forms),
`test_unexpected_no_citation_edge_only_for_absent_in_read_list`, `test_derive_edges_skips_same_version_and_same_work_in_input_order`,
`test_edge_counts_always_carry_all_four_keys`, `test_present_edge_without_mention_is_unassessed_and_never_a_candidate`,
`test_unassessed_edges_skip_candidate_and_excluded_pairs`, `test_unscanned_target_edge_is_not_unassessed_but_scanned_without_mention_is`, `test_edge_alone_creates_no_candidate` (a work pair with state
`present` and no mention produces no `Candidate` from `find_candidates`; the F case of §13).

`tests/test_lineage_candidates.py`: `test_candidates_for_synthetic_corpus` (six synthetic works A to F as in §13: A the
foundation, B and C mention A in one sentence, D mentions B but shares a surname with another author so a false candidate
appears and is kept as a candidate, E mentions nobody, F cites A only by number and has a stored edge to A; assert the exact
candidate pairs, edge states, `no_candidate_targets`, `unassessed_edges`), `test_same_work_two_versions_never_pair`,
`test_same_pair_in_two_separate_calls_is_independent`, `test_duplicate_candidate_pairs_are_not_repeated`,
`test_human_decided_pair_is_excluded_by_parameter`, `test_year_order_warning_is_a_warning_not_a_rejection`,
`test_only_pdf_text_works_are_targets` (abstract-only work is not a target but can still be an earlier work),
`test_priority_key_total_matches_then_from_position`, `test_pack_nine_candidates_makes_two_chunks_of_eight_and_one`,
`test_pack_respects_chunk_count_limit_and_records_beyond_call_limit` (25 candidates: 24 sent over three chunks, 1 not sent),
`test_pack_candidate_too_large_alone_is_recorded_and_does_not_block_others`,
`test_pack_never_drops_a_candidate_and_keeps_order` (property over several sizes; every candidate identity appears exactly once across chunks and not-sent, no duplicates), `test_pack_splits_fewer_than_eight_candidates_when_size_exceeds_budget` (e.g. five candidates that together exceed 48,000 characters make two chunks), `test_pack_never_makes_empty_chunks_or_spends_call_quota_on_them`, `test_passage_budget_counts_unique_passages`
(two candidates sharing one passage count it once; 24 unique passage limit; 48,000 characters limit),
`test_no_model_or_provider_call_is_possible` (the functions run with `socket` and `subprocess` patched to raise).

`tests/test_lineage_baseline.py`: `test_most_cited_from_stored_counts_with_work_id_ties`, `test_unknown_count_is_not_zero_and_is_counted_separately`,
`test_review_list_uses_registered_type_and_note`, `test_representative_follows_d48_order_and_fills_no_gap` (head has no count,
another version has one: the work is unknown, not filled), `test_representative_reason_and_versions_considered`,
`test_first_five_shown_and_total_reported`, `test_cited_by_included_counts_distinct_works_not_versions`,
`test_cited_by_included_excludes_target_from_denominator`, `test_unread_or_unresolved_is_never_zero` (count `None`, `lists_read`
and `other_works` reported), `test_partially_read_corpus_reports_zero_with_its_denominators` (target plus two other works, only one list read, no match: `count=0, lists_read=1, other_works=2`), `test_references_of_an_unread_version_are_not_counted_and_a_read_non_representative_version_counts_once_per_work`, `test_target_identity_is_union_of_its_versions_ids`, `test_no_forbidden_word_anywhere`
(`foundational`/`kurucu` absent from sources and from the repr of a full result), `test_baseline_uses_no_quality_score`
(entries carry no score field), `test_baseline_is_deterministic_under_shuffled_input`.

## Checks to run

1. `PYTHONPATH=backend:. UV_CACHE_DIR=/tmp/deixis-uv-cache uv run pytest tests/test_lineage_mentions.py tests/test_lineage_edges.py
   tests/test_lineage_candidates.py tests/test_lineage_baseline.py -n 0`, then the full
   `PYTHONPATH=backend:. UV_CACHE_DIR=/tmp/deixis-uv-cache uv run pytest` (one known failure:
   `tests/test_documents.py::test_extraction_is_stopped_when_it_exceeds_the_memory_limit`; a test that fails under parallel
   load but passes alone: rerun it alone and say so). Baseline on this checkout: 3,150 passed + that failure.
2. `git diff --check`; `git status --short` shows only the allowed files. Report every count; if a tool cannot run in your
   sandbox say so and do not call an unrun check verified.

## Decision record

`## D132 — P6 slice 2 L2: model-free mention candidates, citation-edge states and the field baseline are pure functions` at the top of
`docs/decisions.md` (above D131), with Status/Date/Context/Decision/Limits; check that D131 is still the highest. Status
`accepted (implemented, uncommitted)`, Date `2026-10-01, P6 slice 2 batch L2`. Limits must say: nothing reads these functions yet
(L5 and L6); synthetic data only, no real-model or provider call, no measurement, so the mention finder's recall on real passages
is unmeasured and numbered citations are missed; a candidate is not a link and a citation edge creates no candidate; the 60-character
gap is measured in the normalized text and a year must follow the surname (judgement); a title with fewer than five significant
tokens is never searched; the packing default is count-only, `passage_budget_fits` is an explicit proxy on mention-passage text, the real 48,000-character limit on the
StepInput message is L5's; `O(|T|·P·R)` cost unmeasured; "review" is the registered type and its provider is not stored; counts are
stored numbers, not quality; no "foundational" claim. In the slice 2 note's L2 heading line append ` ✅ commit: bu satırı ekleyen commit`
(no other edit of the note).
