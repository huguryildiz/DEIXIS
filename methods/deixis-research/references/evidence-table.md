# Evidence table

An evidence table compares sources field by field. Each row is one source
version; each column is a field the user defined, with a short name, an
instruction written as for a human annotator, and an answer format. The
application stores every answer as a new revision of its cell and never lets a
model answer replace a value the user chose.

## Cell extraction

Goal: answer every column in `extraction_target.columns` for the one source
`extraction_target.source_id`, from the supplied passages of that source only.

1. Follow each column's `instruction` as a careful human annotator would. Read
   every supplied passage before answering. `extraction_target.passage_scope`
   says how many of the source's stored passages you were given; you did not see
   the rest, and extracted text can miss figures, tables and equations.
2. Return exactly one item in `cells` for each column, with its `column_id`.
3. Choose the state:
   - `value`: the passages state the answer. Cite them in `evidence`.
   - `unknown`: the passages address the column but do not settle it, for
     example they are ambiguous or give conflicting figures. Cite the passages
     that show this.
   - `not_applicable`: the column does not apply to this source, for example a
     column about measured results for a purely analytical paper. Say why in
     `note`.
   - `not_found_in_inspected_scope`: the supplied passages do not address the
     column. Cite nothing. This says nothing about the parts of the publication
     you were not given.

   There is no state for "not reported", "inaccessible" or "not verified" in
   your output. Whether a publication reports something takes more than the
   passages you were given; the user decides that, and the application records
   sources without text.
4. Shape `value` by the column's `answer_format`, and use null for every state
   other than `value`:
   - `choice`: `{"option_ids": [...]}` with ids from the column's `options`; one
     id unless `allow_multiple` is true.
   - `number_unit`: `{"number": ..., "unit": ..., "as_stated": ...}`. Give the
     number and unit as the source states them and never convert units, even
     when the column has a `unit_hint`. Put the source's own wording, such as
     "128 bytes", in `as_stated`. When the source gives several numbers or a
     range and the instruction does not say which to take, the state is
     `unknown`.
   - `yes_no`: `{"answer": "yes"}` or `{"answer": "no"}`. An unclear answer is
     `unknown`, not a guess.
   - `text`: `{"text": ...}`, at most 500 characters, close to the source's own
     words. Do not add interpretation the passages do not state.
5. For each cited passage add one `evidence` item. Its `quote` is the shortest
   exact, contiguous span of that passage that supports the answer. Copy it
   exactly: keep its language, punctuation, symbols and extraction damage; do not
   translate, repair, paraphrase, add ellipses or join separate spans. If no exact
   span supports the answer, that passage does not support it and is not cited.
6. Keep `note` to a short reason, or null. Do not put page, equation, table,
   figure or section numbers in it; the application shows locators from its own
   records.
7. An abstract cannot support method details, equations, constraints or results
   it does not state.

Write notes in the question's language unless the StepInput says otherwise.

## Column suggestions

Goal: up to eight columns the user could add to compare the table's sources on
the question. You receive the question, the table's current columns and the
titles and abstracts of its rows. A suggestion is shown to the user and added
only if the user chooses it.

- Suggest fields the question needs compared across sources, such as the
  method, the setting, a key parameter or the main result. Do not repeat a
  current column, and do not give two columns the same name.
- Write `instruction` as for a human annotator reading one source: what to look
  for, which answer to take when a source gives several, and when the column
  does not apply.
- Choose the narrowest format that fits: `choice` with 2 to 20 distinct option
  labels when answers fall into known categories (`allow_multiple` when one
  source can have several), `number_unit` with a `unit_hint` for one quantity,
  `yes_no` for a yes-or-no property, and `text` otherwise. Formats that do not
  use them take null `options`, false `allow_multiple` and null `unit_hint`.
- Give a one-sentence `rationale` that ties the column to the question. Use
  `notes` for anything about the suggestions as a whole, or leave it empty.

Write names, instructions, option labels, rationales and notes in the question's
language unless the StepInput says otherwise.
