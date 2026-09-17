# Report

Read this after SKILL.md. It applies only to the four report task types (`report_plan`, `report_section`,
`report_phrase_repair`, `report_review`); an ordinary `grounded_answer` step never sees this file.

## What a report is

A report is a fixed-skeleton document written section by section, from the same evidence table and passages
the research already has. You never write the whole report in one call. Each call writes one part: the plan,
one section's claims, a targeted repair of a few flagged sentences, or a review of already-written sections.
The report never invents a related-work table in prose: Section IV's table is the evidence table itself,
given to you as rows and cited cells, and you discuss it — you do not restate it as a bullet list.

## Shared rules for every report step

- Everything in "Authority and data boundaries" and "Evidence rules" in [SKILL.md](../SKILL.md) applies unchanged.
  Follow [source-grounded answer, rules 2, 5–7 and 9](source-grounded-answer.md#grounded-answer) for reading
  depth, source support, exact contiguous anchors, LaTeX and `text_source` handling.
- Write in the question's language (`question.language_hint`, or the question's own script if absent).
- A claim's `claim_key` is a label you assign once per call, matching `^[A-Za-z_]+\.[0-9]{1,3}$` (for example
  `IV.3`). Reuse the section identifier as the prefix.
- Cite only passage_ids and cell_ids from the allowlist. For a cell_id, anchor to one of that cell's stored
  evidence quotes; for a passage_id, apply [the shared citation rule](source-grounded-answer.md#grounded-answer).
- Apply [the shared mathematics and `text_source` rule](source-grounded-answer.md#grounded-answer) to equations.
- `paragraph` groups claims that belong in one flowing paragraph of the finished report; number them in the
  order they should read, starting at 1.
- Do not write a page, equation, table, figure or section number into claim text; use `table_ref`/`equation_ref`
  and the application inserts the printed number.
- A `count` claim ("4 of the 6 full-text sources...") must give the exact source_ids of the numerator and the
  denominator in the `count` field; the sentence's own numbers must match those counts, and every member you
  name must actually carry the column value and reading depth your sentence claims — the application checks
  this and rejects a count claim whose members do not match.
- If a plan glossary term, axis or budget's required evidence was not given to you (for example no definition
  passage for a term this section needed), do not force a claim. Write an `insufficient_evidence` entry
  instead, naming the missing context and why.
- The phrasebank frames you receive are limited to this section's own categories. A sentence in `claims[].text`
  or `insufficient_evidence[].reason` that keeps none of one frame's fixed words in order goes to a targeted
  repair call; write plainly and re-use frames rather than inventing new phrasing, since a sentence you cannot
  fit to a frame becomes an exception that is recorded and measured.

## Report plan (`report_plan`)

Write `scope_statement` (one paragraph, in the question's language, describing what the report covers and
why), `research_questions` (2 to 5, each a short `RQ`-numbered question the report's sections answer),
`glossary` (terms the report will define, each with a definition and the one passage_id it comes from — do not
invent a term without a defining passage in the allowlist) and `axes` (classification dimensions, each tied to
one evidence-table column_id from the allowlist; an axis without a matching column is rejected). Do not write
`corpus`, `section_budgets` or `allowed_support`: the application fills those from the evidence table and a
fixed policy after your plan is accepted. Do not repeat the whole question as `scope_statement`; write your own
one-paragraph account of its scope.

## Section instructions (`report_section`)

`report_target.section_id` tells you which section you are writing. Its evidence is in `sources`/`passages`
and, for table-grounded sections, in the selected evidence-table records supplied with the step; write only
that section, in fixed-skeleton order, and do not invent a section this report does not have.

- **III (Background and Taxonomy):** define the plan's glossary terms and axes using only their sourced
  definitions and axis-relevant passages. Use `subsections` for axis-organized theme groups when the plan has
  more than a couple of axes; give each subsection an `axis_id` matching the plan. Displayed equations belong
  here only when the question or plan's axes ask for a formulation; otherwise keep III definitional.
- **IV (Literature Synthesis):** discuss the evidence table's rows and cells; every claim that turns a cell
  value into a sentence cites that cell_id and quotes its stored evidence. Use `subsections` grouped by axis
  the same way as III. One claim with `table_ref: "TABLE_I"` and no other content may introduce the table
  itself before the discussion.
  - A `not_found_in_inspected_scope` cell of a full-text-read row may be described as "not reported in the
    inspected text". Never write "the study did not consider this" for a summary-only row; only a denominator
    sentence may mention summary-only rows in aggregate ("2 of 6 summary-only sources could not be assessed").
  - A cell whose extraction failed technically is not a `not_found` value and never enters a denominator.
  - Never infer a method or result from the gap between two unrelated cells.
- **V (Comparative Findings):** compare cells of one column across sources. A conflict claim requires the
  compared sources to share the same concept, condition and metric; when conditions differ, write "different
  conditions, different outcomes", not a conflict. Distinguish `demonstrated` findings from `modelled` or
  `proposed` ones in your wording; a modelled result and a demonstrated result are not equal-weight agreement
  or disagreement.
- **VI (Candidate Unanswered Aspects):** write the `gaps` array, not ordinary prose claims. For a
  `corpus_absence` gap given to you (its candidate and basis are already prepared), write only its `text` in
  the fixed pattern the application's basis describes, citing the given basis. For a `stated_limitation` gap,
  cite the source's own stated limitation (a "limitations" column cell or a passage) and mint a new `gap_id`.
  For a `conflicting_evidence` gap, cite the V claim_key it comes from. Every gap text ends with the sentence
  that it is a candidate and no kill-search was run; never use "gap", "open problem", "novel" or "first" (or
  their Turkish equivalents) anywhere, including implicitly restating them in other words.
- **VII (Future Directions):** every claim has a non-empty `gap_refs` pointing at a VI gap, OR cites a cell of
  the evidence table's "proposed future work" column (if the plan's axes include one). A future-work claim
  drawn from a source's own stated proposal is `source_stated`, cites that cell or passage, and is written as
  the source's own proposal, not the report's. An `analyst_inference` future-work claim must trace to a VI
  `gap_id`.
- **VIII (Limitations and Threats to Validity):** the application writes the numeric core (search/PDF/model
  counts) before your call; write only the prose sentences the application asks for (recall measurement
  caveats when one exists, open-access/upload bias, summary-vs-full-text ratio, share of analyst inference,
  absence of kill-search). Do not restate the numbers in different words that could drift from the code-written
  ones; reference them by the section's own numbered list, given in your input.
- **I (Introduction), IX (Conclusion), abstract, index_terms:** every claim has non-empty `body_refs` pointing
  at claim_keys of III-VIII already written; you receive only their one-line code-written summaries (claim_key,
  first sentence, support type, weakest reading depth), never their full text. Do not write a claim here that
  is not traceable to a body claim; do not generalize beyond what the summaries say. `index_terms` are chosen
  only from the given D44 concept vocabulary list; do not add a term that is not in that list.

## Phrase repair (`report_phrase_repair`)

You receive a small list of flagged sentences (their `sentence_id`, original text, support type, up to three
nearest phrasebank frames, and the sentence immediately before and after each). Rewrite only the flagged
sentences, each into one that keeps a frame's fixed words in order. Preserve every number, every citation
target implied by the sentence, every qualifier ("may", "some", "in the inspected text") and every negation.
Do not touch neighboring sentences. If none of the three given frames can honestly carry the sentence's
meaning, write the clearest plain sentence you can rather than distorting it — the application checks whether
your rewrite still reads as valid and may keep the original if your rewrite changes what is claimed.

## Report review (`report_review`)

Read one or more already-written sections against their cited passages and cells. Return a flat list of
findings; you never edit the report yourself. Use `support_broken` only for a repaired sentence (its
`sentence_id` set) whose meaning no longer matches what its citations support — the application reverts that
one sentence to its pre-repair text when you use this code. Use `count_error`, `terminology_inconsistent`,
`abstract_body_mismatch`, `equation_mismatch` or `comparability_error` for the corresponding semantic problems
named in this file's IV/V/VIII rules above that the application's own checks cannot see (word choice, whether
a compared pair is truly comparable, whether an equation reads as the passage states it, whether the abstract
says more than the body). Everything else is `other`. Passing structural checks earlier is not evidence that
meaning is correct; read for meaning.
