# Search phrases

Goal: from the research question alone, write short plain phrases that a search
engine reading by meaning can match against paper titles and abstracts. Each
phrase is sent as one semantic search of its own, beside the search plan. You
are given the question, the English sentence for it where the application has
one (`phrase_target.english_question`), and the number of phrases to write
(`phrase_target.count`). You get no records, no search terms and no blocks.

1. Read `question.text` and `phrase_target.english_question` when it is not
   null. Nothing else in the input is for this step.
2. Write exactly `phrase_target.count` phrases in `phrases`. Each `text` has
   three to seven words, counted by the spaces between them.
3. Word each phrase the way a paper's title or abstract would word it. Write
   plain text only: no `AND`, `OR` or `NOT`, no quotation marks, no `*` or `?`.
4. Make the phrases different from each other. Give each a `kind`:
   - `subject`: what the question is about, in its most common wording.
   - `method`: a method, model or technique the question names or implies.
   - `task`: what the question wants done, found or measured.
   - `synonym`: the same subject or task in other words authors use.
   - `title_wording`: the words a paper answering the question would likely
     have in its title.
   - `detail`: one specific condition, quantity or setting the question
     states.
   Use each kind at least once when the count allows it.
5. Write the phrases in English. Only when the question itself is not in
   English may you write at most two phrases in the question's own language.
   The application counts a phrase with a letter outside ASCII as not English.
6. Two phrases that are the same after lower case and single spaces are one
   phrase: the application refuses the later one. Do not repeat a phrase in
   other capitals or spacing.
7. Add no subject the question does not ask about, and narrow nothing it
   leaves open.
8. Echo `step_input_id` and `scope_revision` exactly as given, following the
   envelope rule in [SKILL.md](../SKILL.md), and set `schema_version` to
   `deixis.search_phrases.v1`.

Do not search and do not explain your phrases: there is no field for a
rationale and none is wanted.
