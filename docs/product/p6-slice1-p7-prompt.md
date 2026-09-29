<!-- Plan review: gpt-6-sol high, round 1: hazır değil (3 high, 4 medium), folded in as R1-R7; round 2: hazır değil (2 high, 4 medium), folded in as R8-R13; round 3: hazır değil (2 high, 1 medium), folded in as R14-R16 with no fourth round (plan limit); PLAN_ROUNDS_PLACEHOLDER -->

# Task: P6 slice 1, batch P7: the other eight assembly rules, and rule 7 on structured numbers

Repo: the git worktree you are started in (`-C`). All paths are relative to it. Plan: `docs/product/p6-slice1-report-run.md`
section 1e, Task 4 (line ~2044, the 14-row table); design note `docs/product/p6-report-design.md` §6, §7, §8. Last batch:
D115 (`docs/product/p6-slice1-p6-prompt.md`), HEAD 7397963.

## What is in code today (checked on HEAD 7397963)

- `backend/deixis/workflow/report/assembly.py` has six checks: rule 1 `_check_duplicate_claim_keys`, 2 `_check_glossary_order`
  (warning), 3 `_check_body_refs`, 4 `_check_derived_strength`, 7 `_check_corpus_counts`, 10 `_check_word_budgets`.
  `_CHECKS` says "Rules 5, 6, 8, 9, and 11-14 are intentionally added in the next round." Each issue is
  `{"rule", "section_id", "detail"}`; warnings carry a `_warning` rule suffix and a `WARNING:` detail prefix.
- Rule 7 reads label words in the prose of `draft.text` of II and VIII (`_labeled_corpus_numbers`, `_CORPUS_LABELS`).
  P6 (D115) now stores the numbers those texts were rendered from in `report_sections.validation_json["numbers"]`
  (`ReportStore.section(...)["validation"]["numbers"]`):
  - II: `{"version": 1, "kind": "review_methodology", "corpus": {found, unique, screened, included, full_text},
    "full_text_ratio", "fetch_pdf", "pdf_other_copy"}` (`review_methodology.write_review_methodology`).
  - VIII: `{"version": 1, "kind": "limitations", "as_of": "before_viii", "corpus": {...}, "included", "full_text",
    "no_full_text_share", "analyst_inference_share", "phrase_repair_exceptions", "truncation", "items": [...], ...}`
    (`review_methodology.limitations_core`); its prose `draft["text"]` is `review_methodology.render_limitations(numbers, language)`
    (`" ".join(f"{n}. {text}")`, language-independent because item text is frozen with the numbers).
- `sections.py::run_report` calls `assembly.run_assembly_checks` after the last round; it treats an issue as a warning only
  if `rule == "glossary_term_before_definition_warning" and detail.startswith("WARNING:")`. Errors finalize the report as
  `draft` and put the issue list in the run's `error_json`.
- Stored data the rules read (all already written by earlier batches): `report_claims` (`claim_key, text, support_type,
  table_ref, equation_ref, axis_id, count_json, equation_origin_json`), `report_claim_refs` (`body_ref`, `gap_ref`),
  `report_citation_links` (`passage_id` xor `cell_id`, `source_version_id`, `step_input_id`, `anchor_text`, `anchor_match`
  in `exact|normalized|fuzzy` or NULL), `report_gaps` (`gap_id, kind, text, basis_json` = `{basis_claim_keys,
  basis_passage_ids, basis_cell_ids, nearest_match}`, `provenance_json` = `{origin: code|model, ...}`), `report_phrase_repairs`
  (`section_id, sentence_id, outcome` in `kept|reverted_exception|unframed_exception`, several rows per sentence possible,
  latest by `rowid` wins), the frozen snapshot (`reports.snapshot(report_id)`: `rows`, `cells` with `cell_id, column_id,
  source_version_id, state, value, reading_depth, evidence[{passage_id, quote}]`, `corpus`), the frozen plan
  (`reports.report(report_id)["plan"]`: `axes`, `limitations_column_id`, `future_work_column_id`, `glossary`), and the
  section's `draft` (`draft["gaps"]`, `draft["subsections"]` with `heading`, `draft["insufficient_evidence"]` with `reason`,
  `draft["text"]` for II and VIII).
- Handoff decision 1: since D113 a citation anchor that cannot be located is already rejected while the section is written
  (`anchor_not_in_passage` / `anchor_not_in_cell_evidence`), but older or hand-built links may still hold
  `anchor_match = NULL`. Rule 12 turns that into an error at assembly.
- Nothing in the repo holds the banned-word list (`grep -rn "open problem" backend` finds only prose in `methods/`).

## Plan review round 1: binding additions (they override anything below that they contradict)

- R1 (fixtures, rule 9). The scripted VI gap in `tests/test_report_flow.py` (`gap9`, `stated_limitation`, three empty basis
  lists) is a fixture that violates rule 9 as specified. Change that fixture, not the rule: give `gap9` a real basis, the
  scripted VI input's limitations-column cell id (`step_input["report_target"]["cells"][0]["cell_id"]`, which is the plan's
  `limitations_column_id` column) in `basis_cell_ids`. `test_report_flow.py` may therefore change in three places: this
  fixture, the rule-7 tests, and nothing else without a reported reason.
- R2 (fixtures, rule 14 and language). Language for rule 14 is read with `phrasebank.frames_language(payload)` only when the
  payload has a `question` key; a payload without one falls back to the report language, then the scope `language_hint`,
  then `"en"` (documented in the decision, not a silent guess: it is the same order `write_review_methodology` uses). The
  assembly test fixture's step-input payloads gain a real `question` (`{"text": ..., "language_hint": "en"}`), and every
  claim text stored by that fixture either follows a phrasebank frame for its section (check with
  `phrasing.flagged_sentences`) or gets a matching `report_phrase_repairs` exception row; the clean report must return `[]`.
- R3 (rule 9, `corpus_absence`). Recompute from the snapshot, do not trust the stored basis: the gap's column is the one
  column shared by its basis cells; the set of `basis_cell_ids` must EQUAL the set of all snapshot cells of that column with
  `reading_depth == "full_text"` and `state != "not_applicable"` (so a fourth applicable full-text cell holding a `value`, or
  a `not_found` cell left out of the basis, is an error), there must be at least 3, and every one of them must be in state
  `not_found_in_inspected_scope`. Same error code `gap_absence_basis_invalid`; test with a counter-example (a fourth
  applicable full-text `value` cell in the column).
- R4 (rule 6 scope, code-written text). II's and VIII's code-written prose (`draft["text"]`) is exempt from the word list:
  the VIII template itself says "research gaps" / "Araştırma boşluğu" when it reports that no kill search ran, and II quotes
  search queries. The word list reads only model-written text (claims, subsection headings, gap texts, insufficient-evidence
  reasons). Record this exemption and the template wording as a Limit of the decision; do not change `review_methodology.py`.
- R5 (stored JSON). `count_json`, `equation_origin_json`, `basis_json`, `provenance_json` come out of SQLite as text; parse
  them with `json.loads` through one helper and check the type (dict, and for lists the element types the rule needs). A value
  that fails to parse or has the wrong shape yields one issue `stored_record_malformed` (`section_id` of the record, detail
  naming table, key and field) and skips only the dependent check of that one record; it never raises.
- R6 (rule 7, VIII items). Before calling `render_limitations`, verify `numbers["items"]` is a list of dicts with an int
  `number` and a str `text`; otherwise issue `corpus_numbers_missing` (detail: items malformed) and skip the text comparison.
- R7 (rule 9, `stated_limitation` basis). Beyond "exists": every basis passage must belong to a source version that is a row
  of the frozen snapshot, and every basis cell must be a snapshot cell of the plan's `limitations_column_id` column; a
  passage outside the frozen rows or a cell in another column: `gap_basis_foreign`. Add tests for a foreign passage and for a
  cell of an unrelated column.

### Plan review round 2: binding additions (R8-R13; they override anything above or below that they contradict)

- R8 (rule 7, numeric fields). Every number rule 7 reads must be checked for presence, type and finiteness before use: the
  five corpus counts and `included`/`full_text` are `int` and not `bool`; `full_text_ratio` and `no_full_text_share` are
  `int` or `float`, not `bool`, and `math.isfinite`. A missing or wrong-typed field is one `corpus_numbers_missing` issue
  (detail names the field) and that comparison is skipped; nothing raises.
- R9 (rule 9, basis must come from what VI saw). For a VI gap, resolve the stored step input of the VI section
  (`SELECT payload_json FROM step_inputs WHERE step_id = <VI section step_id> ORDER BY rowid DESC LIMIT 1`, or
  `store.step_input_payload` on a link's `step_input_id`; fixtures decide which is available; if the VI section has no stored
  step input, that is a `gap_basis_missing` issue, not a pass). `basis_passage_ids` must be in that payload's `passages`,
  `basis_cell_ids` in its `report_target.cells`; anything else: `gap_basis_foreign`. The source-ownership (R7) and
  limitations-column conditions apply in addition, not instead. The check is structural: a fixture cell that holds a generic
  sentence is not shown to be a source's own stated limitation; say so in the decision's Limits.
- R10 (rule 9, `corpus_absence` and the code candidate). Besides R3, match the gap to the code candidate that VI's stored
  step input carried: `payload["report_target"]["gap_candidates"]` must contain an entry with the same `gap_id`, its
  `column_id` must equal the gap's column, and `set(candidate["basis_cell_ids"])` must equal `set(basis_cell_ids)`; otherwise
  `gap_absence_basis_invalid`. `basis_cell_ids` must contain at least 3 UNIQUE ids (a repeated id counts once, and a
  repeated id is itself `gap_absence_basis_invalid`).
- R11 (rule 14, an exception belongs to the sentence it was recorded for). A flagged sentence is excused only when the latest
  `report_phrase_repairs` row for `(section, sentence_id)` has outcome `unframed_exception` or `reverted_exception` AND the
  current sentence text equals that row's `after` (for `reverted_exception` also accepted: equals `before`). Otherwise
  `unframed_sentence_not_recorded`. Test: an exception row whose `after` no longer matches the stored sentence.
- R12 (existing tests, not only the base fixture). Review every existing test in `tests/test_report_assembly.py` and
  `tests/test_report_flow.py` that adds claims or sections after the fixture (for example the duplicate-key test that adds
  an IV claim "A duplicate key.") and its expected full rule set (`{issue["rule"] ...} == {...}`); rules 6, 8, 12, 14 may now
  fire on those added claims (unframed text, missing anchor, ...). Fix the test data (framed text, a real anchor, an
  exception row) so each keeps testing only its own rule; do not loosen an equality to a subset.
- R13 (R5 made exact). A stored JSON field is malformed unless: `count_json` is a dict with `numerator_source_ids` and
  `denominator_source_ids` non-empty lists of str and `column_id` a str; `equation_origin_json` is a dict with a str
  `passage_id` and `text_source` one of `text_layer|ocr|marker|latex_source`; `basis_json` is a dict with
  `basis_claim_keys`, `basis_passage_ids`, `basis_cell_ids` lists of str (a missing key or `null` there is malformed);
  `provenance_json` is a dict whose `origin` is `code` or `model`. SQL NULL in a nullable column (`count_json`,
  `equation_origin_json`) means "absent", not malformed. Add one non-crashing test per field (`{}`, a list, a wrong element
  type, invalid JSON text).

### Plan review round 3: binding additions (R14-R16; last plan round, they override anything above that they contradict)

- R14 (rule 9, scope of the VI-input check). The "basis must come from what VI saw" test of R9 (payload `passages` /
  `report_target.cells`) applies to `stated_limitation` gaps only. A `corpus_absence` gap is checked against the snapshot (R3)
  and the code candidate in the payload's `report_target.gap_candidates` (R10, matching `gap_id`, `column_id`,
  `basis_cell_ids`); it is NOT required that its basis cells are in the payload's `cells` (VI's evidence selection carries the
  limitations column only, and the candidate columns come from the plan axes; whether that selection can carry every
  candidate's basis cell is a separate question outside this batch: do not touch `selection.py` or `contracts.py`, list it as
  open in your final message if you can confirm it from the code).
- R15 (rule 14, R11 corrected). An exception excuses a flagged sentence when the latest row's outcome is `unframed_exception`
  or `reverted_exception` and the current sentence text equals that row's `after` OR its `before` (a repair the code refused,
  for a changed number or math span, keeps the original sentence while `after` holds the refused proposal). A row whose
  `after` and `before` both differ from the current text does not excuse. Tests: `after` matches, `before` matches (refused
  repair), neither matches.
- R16 (assembly-fixture tests for rules 9 and 10). The base fixture has no VI section and its one step input has no
  `report_target`. For the rule 9/10 tests build, in the tests, a VI section with a real stored step input whose payload has
  `report_target.cells` (the limitations-column snapshot cell(s)), `report_target.gap_candidates` (built with
  `gaps.generate_corpus_absence_candidates` from a snapshot that has three applicable full-text `not_found_in_inspected_scope`
  cells in one column), `passages` and a `question`, attach it to the VI section through its `step_id`, and save gaps with
  `reports.save_gaps` (`provenance = {"origin": "code" | "model", ...}`). Passing and failing cases for each code in rule 9
  come from this setup.

## What this batch builds

All in `backend/deixis/workflow/report/assembly.py` (plus the small `sections.py` filter change below). No model call.
One private `_check_*` function per rule, added to `_CHECKS`, using the existing `_issue`, `_claims`, `_section_texts` helpers.
Update the module docstring (all 14 rules are implemented). Fail closed: missing or malformed stored data is an error, never
a silent pass. Which sections are "model-written": every section except II (II and VIII's `draft["text"]` are code-written
from records; the II text quotes search queries verbatim, so no word-list or phrase rule ever reads it).

### Rule 7 (changed): compare the structured numbers, not the prose

Replace `_check_corpus_counts`, `_labeled_corpus_numbers` and `_CORPUS_LABELS` (delete them; nothing else uses them).
For each of II and VIII that exists in `reports.sections(report_id)`:

- `validation["numbers"]` missing, not a dict, `version != 1`, wrong `kind` (`review_methodology` for II, `limitations`
  for VIII), or `corpus` missing or not a dict with the five keys: error `corpus_numbers_missing`.
- each of `found, unique, screened, included, full_text`: stored `numbers["corpus"][key]` differs from
  `reports.snapshot(report_id)["corpus"][key]`: error `corpus_count_mismatch` (keep this rule name), one issue per key.
- II: `full_text_ratio` must equal `full_text / included` (0.0 when `included` is 0) within 1e-9; VIII: top-level
  `included` and `full_text` must equal the snapshot's, and `no_full_text_share` must equal `(included - full_text) / included`
  (0.0 when `included` is 0) within 1e-9. A mismatch is `corpus_count_mismatch` too.
- VIII only: `draft["text"]` must equal `review_methodology.render_limitations(numbers, language)` exactly (the language
  argument is ignored by that function; pass the report language). Otherwise error `limitations_text_drift`. II's prose
  cannot be re-rendered here (it needs search provenance strings), so II's text is not compared; say so in the decision.

### Rule 5: count fields (design §6)

For every claim with `count_json` (`{numerator_source_ids, denominator_source_ids, column_id}`), against the frozen snapshot
(members are source version ids; a cell is found by `(source_version_id, column_id)`):
- duplicate ids in either list, or numerator not a subset of the denominator: `count_members_invalid`;
- a member that is not a row of the snapshot, or `column_id` that is not a snapshot column, or a member without a snapshot
  cell in that column, or a denominator cell whose state is `not_applicable`: `count_member_not_in_snapshot`;
- denominator members with more than one `reading_depth` (summary cells and full-text cells never share one count):
  `count_depth_mixed`;
- numerator members with more than one `state`, or, when the state is `value`, more than one value (compare the stored
  `value` dicts after `json.dumps(sort_keys=True)`; a numerator must all carry the same value): `count_value_mixed`;
- the integers in the claim text, read outside math spans (use `contracts._without_math`; years are not special-cased):
  every integer in the text must be one of `{len(numerator), len(denominator)}`, and if the
  text has any integer, both must appear: `count_number_mismatch`.
Words are not parsed ("four of six" is not checked; say so in the decision). Claims without `count_json` are not read.

### Rule 6: banned words, everywhere in model-written text

Search, case-insensitively, the claim texts (`report_claims.text`), the `draft["subsections"][*]["heading"]`,
`draft["gaps"][*]["text"]` and `report_gaps.text`, `draft["insufficient_evidence"][*]["reason"]` of every model-written
section, with math spans removed. One fixed module-level list `_BANNED`, two languages, applied to both (a report may quote
either): English `gaps?` (not after `band`, `energy`, `spectral`, `optical`, `mass`), `open problems?`, `open questions?`,
`novel`, `novelty`, `first-ever`, and novelty uses of "first": `the first (?:study|work|paper|survey|review|attempt|to|time)`,
`first of its kind`, `for the first time`; Turkish `araştırma boşluğ\w*`, `boşluk` and `boşluğ\w*` (not after `bant`, `enerji`),
`açık problem\w*`, `açık soru\w*`, `özgün\w*`, `yenilik\w*`, `ilk kez`, `ilk defa`, `bir ilk`, `ilk çalışma\w*`. Use `\b` word
boundaries (mind that `\b` and IGNORECASE treat Turkish letters oddly; the Turkish patterns must match `Boşluğu` and
`ARAŞTIRMA BOŞLUĞU`-style text acceptably, and a test proves it for one lowercase and one capitalized form). Error
`banned_word` with the matched text and where it was found (`claim III.2`, `heading`, `gap gap3`, `insufficient_evidence`).
The word "first" alone is deliberately NOT banned (too common: "first-order", "the first author"); this is a judgement, record it.

### Rule 8: bibliography parity

The bibliography is derived from the citation links (`views.report_view` numbers sources by first citation), so "every
reference is cited" holds by construction. What can break is the other direction and the record behind a reference. For every
`report_citation_links` row of the report: `source_version_id` must be a row of the frozen snapshot (`snapshot["rows"]`), else
`citation_source_not_in_corpus`; it must resolve to a `source_versions` row with a non-empty `title` joined to a `works` row
with a non-empty `source_key`, else `reference_record_incomplete`; the linked passage (or, for a cell link, the snapshot cell)
must belong to that same source version, else `citation_source_mismatch`.

### Rule 9: gap bases (VI) and future-work links (VII)

- VII: every claim needs either at least one `gap_ref` that names a `report_gaps.gap_id` of this report, or a citation link to
  a cell that is in the snapshot and whose column is the plan's `future_work_column_id`. A claim with neither:
  `vii_claim_without_basis`. A `gap_ref` that names no stored gap: `gap_ref_unknown` (also for VI claims). An
  `analyst_inference` VII claim must have a valid `gap_ref` (a cell alone is not enough): `vii_inference_without_gap`.
- VI, per stored gap by kind. `stated_limitation`: at least one of `basis_passage_ids` / `basis_cell_ids`, every basis passage
  exists and every basis cell is a snapshot cell (else `gap_basis_missing`). `conflicting_evidence`: see rule 13.
  `corpus_absence`: `provenance.origin` must be `code`; `basis_cell_ids` has at least 3 cells; every cell is a snapshot cell
  of one column, `reading_depth == "full_text"`, state `not_found_in_inspected_scope`; and none is `not_applicable`; errors
  `gap_absence_basis_invalid` (any failure), with a detail naming which check failed. A kind outside `contracts.GAP_KINDS`:
  `gap_kind_unknown`. Issues carry `section_id` "VI" (or "VII" for the VII checks).

### Rule 11: equations and math

For every model-written claim: unbalanced `$` (count of unescaped `$`), or a span from `contracts._math_spans` that
`contracts._math_span_is_well_formed` rejects: error `math_not_well_formed`. A claim is an equation claim if it has
`equation_ref`, `equation_origin_json`, or a `$$…$$` span. An equation claim without `equation_origin_json`:
`equation_origin_missing`. With one: the origin `passage_id` must be one of the payload passages of the step input of the
claim's own citation links (`store.step_input_payload(link["step_input_id"])["passages"]`, the same input the section saw),
else `equation_origin_not_in_input`; it must be a stored passage whose `text` holds a math span (`contracts._math_spans(text)`
non-empty), else `equation_origin_without_math`. When the stored `equation_origin.text_source` is `ocr` or `marker`, add a
non-blocking issue with rule `equation_text_source_warning` and detail starting `WARNING:` (a `latex_source` or `text_layer`
origin gets none). Mathematical correctness is not checked (design §8; say so in the decision).

### Rule 12: anchors (handoff decision 1)

For every citation link: `anchor_match` NULL or `anchor_text` empty: error `citation_anchor_unmatched` (this is the change from
the old `NULL` write). Then re-locate: a passage link's `anchor_text` must be found in that stored passage's `text` with
`contracts.locate_anchor`; a cell link's `anchor_text` must be found (`locate_anchor`) in at least one `quote` of that cell's
frozen `evidence` in the snapshot, and the cell must be in the snapshot. Failures: `anchor_not_in_passage`,
`anchor_not_in_cell_evidence`, and `cell_not_in_snapshot` (same names the section-level validation uses; issue `section_id`
is the claim's section).

### Rule 13: conflict links

Every stored gap of kind `conflicting_evidence` must have a non-empty `basis_claim_keys` and each key must be the `claim_key`
of a claim in section V: else `conflict_gap_without_v_claim` (section_id "VI").

### Rule 14: phrase frames and the two non-exception codes

For each model-written section whose `phrasebank.REPORT_PHRASEBANK_SECTIONS[section_id]` is non-empty, recompute the sentences
that follow no frame with `phrasing.flagged_sentences(section_id, [*claims, *draft["insufficient_evidence"]], phrasebank_text,
language)` (claims as dicts with `claim_key, text, support_type`). Each flagged `sentence_id` must have a latest
`report_phrase_repairs` row for that section with outcome `unframed_exception` or `reverted_exception`; if there is none, or
the latest outcome is `kept` (a kept rewrite that still follows no frame), error `unframed_sentence_not_recorded`. Exceptions
are accepted (design §8, §2 decision 12), not errors. Separately, for every model-written claim: a phrase from
`phrasebank.own_work_phrases(_without_math(text), language)` is error `own_work_phrase_in_claim`; a phrase from
`plural_source_phrases` is error `plural_sources_for_one_source` when the claim's citation links all belong to one source
version (and there is at least one link). These two cannot be exceptions. Phrasebank text: `contracts._phrasebank_text()` (the
skill package's `references/phrases.md`). Language: derive it as `sections.py` does, `phrasebank.frames_language(payload)`,
from the payload of the section's own step input (`SELECT payload_json FROM step_inputs WHERE step_id = ? ORDER BY rowid DESC
LIMIT 1` with the section's `step_id`); when the section has no step input, use the report language / scope `language_hint`
the way `review_methodology.write_review_methodology` does. If the language has no frames (`phrasebank.checked_language` is
None or `has_frames` is False), the frame part of this rule is skipped for that section and the own-work/plural parts still run
with `en`. Record that choice.

### `sections.py` filter (the only other code change)

`run_report` currently names the glossary rule when separating warnings from errors. Change it to
`issue["rule"].endswith("_warning") and issue["detail"].startswith("WARNING:")`, so the new
`equation_text_source_warning` does not finalize a report as `draft`. Nothing else in `sections.py` changes.

## Decisions taken (the plan's own default; do not reopen)

1. Rule 7 reads structured numbers, not prose (owner's request; the handoff's durable fix). Its old regexes are deleted.
2. Rule 12: unmatched anchor is an error (handoff decision 1).
3. Every new rule is an error except `equation_text_source_warning` (design: OCR/Marker equations "carry a warning").
4. The word "first" alone, and Turkish "yeni", are not banned (false positives); the list is narrow-phrase for those.
5. Rule 8 checks the citation-to-corpus direction and the reference record; the reverse ("every reference is cited") is true
   by construction because references are built from links.
6. No migration, no schema change, no `methods/` change (`skill_package_hash` must not move), no UI change.
7. II's prose is not re-rendered; VIII's is.

## Files

Allowed to change: `backend/deixis/workflow/report/assembly.py`, the one-line filter in
`backend/deixis/workflow/report/sections.py`, `tests/test_report_assembly.py`, `tests/test_report_flow.py` (only the tests that
must follow rule 7, see below), a new test file `tests/test_report_assembly_rules.py` if `test_report_assembly.py` gets too
long (prefer extending the existing fixture `report_with_sections`), `docs/decisions.md` (do NOT edit it; the orchestrator
writes the decision), the handoff (do NOT edit; orchestrator does).
Do not touch: `apps/web/`, `api/app.py`, `workflow/store.py`, `workflow/views.py`, `contracts/`, `methods/`, migrations,
`docs/decisions.md`, `docs/product/*.md`, `TODO.md`, `.vscode/`, `scripts/`, `.local/`.

## Tests to add or change

In `tests/test_report_assembly.py` (extend the existing `report_with_sections` fixture minimally; the fixture's II and VIII
sections must now store `validation["numbers"]` in the D115 shape, e.g. built with the real `review_methodology`
helpers or by hand with the snapshot's corpus, and VIII's `draft["text"]` from `render_limitations`; the clean report must
still return `[]`). One test per rule name, each proving the rule fires and a nearest passing case does not:
`test_rule7_*`: numbers missing, wrong kind, one key mismatching (II and VIII), derived ratio/share wrong, VIII text drift,
and "prose is no longer read" (a wrong number written into II's or VIII's prose alone while `numbers` is right raises
nothing for II and `limitations_text_drift` for VIII); rule 5: each of the five codes plus a matching count passing; rule 6:
English claim, heading, gap text, insufficient-evidence reason, Turkish capitalized form, math span ignored, `band gap`
exempt, "first-order" and "the first author" pass; rule 8: three codes; rule 9: every code, plus a future-work cell
citation passing, and a corpus_absence gap with 3 full-text `not_found` cells passing; rule 11: not-well-formed, missing
origin, origin not in input, origin passage without math, the OCR/Marker warning (a report with only that warning has
`run_assembly_checks` return it and `sections.py`'s filter treat it as non-blocking); rule 12: NULL match, anchor moved so it
is not in the passage, cell anchor not in frozen quotes; rule 13: gap without V claim and gap with a V claim key passing;
rule 14: an unframed sentence with no repair row errors, with `unframed_exception` row passes, `kept` row still unframed
errors, own-work phrase, plural-source phrase on a one-source claim (and not on a two-source claim).
In `tests/test_report_flow.py`: the test near line 352 (`test_assembly_still_catches_a_wrong_corpus_count_in_viii_text`)
must be rewritten for rule 7 (tamper `validation["numbers"]["corpus"]["included"]`, expect `corpus_count_mismatch`; and a
second test that a text-only change raises `limitations_text_drift`). Nothing else in that file may need to change; if a
flow test now fails because a new rule fires on the scripted fake model's output, report which rule and why, and fix the
FIXTURE only if the fake output is really wrong; do not weaken a rule to make a test pass.

## Checks to run (before and after; report both counts)

`PYTHONPATH=backend:. uv run pytest` in full (the known memory-limit failure is the only accepted failure; a test that fails
under parallel load and passes alone: rerun it alone and say so). Also `PYTHONPATH=backend:. uv run pytest
tests/test_report_assembly.py tests/test_report_flow.py -n 0`. Possibly `UV_CACHE_DIR=/tmp/deixis-uv-cache`. No web build is
needed (no web change).

## Rules of engagement

- No git state-changing commands (no add, commit, stash, checkout, reset, worktree). Codex cannot write `.git/index.lock`.
- No real-model calls; FakeAdapter and the synthetic fixtures only.
- Do not invent; report what you could not find. If a stored field a rule needs is not there, say so instead of guessing.
- Final message: files changed, per-rule summary of what fires and the error codes, before/after test counts, every place you
  used your own judgement, and anything left open.
