# Question translation

Goal: the research question as one English sentence. The application picks its
search words from that sentence, so the sentence must ask exactly what the
question asks. Every other step still reads the question as the person wrote it.

1. Read `question.text`. `question.language_hint`, when present, names the
   language the person said the question is in.
2. Write `english_question`: one faithful English sentence that asks the same
   question.
3. Use the English terms the field itself uses for each concept, as authors in
   that field would write them in a title or an abstract. Keep a technical term,
   a model name, an abbreviation or a proper name as it is when English writing
   uses it unchanged.
4. Add nothing, narrow nothing and explain nothing. Do not add a population, a
   method, a period or a qualifier the question does not state, do not drop one
   it does state, and do not turn the question into a different one.
5. Echo `step_input_id` and `scope_revision` exactly as given, following the
   envelope rule in [SKILL.md](../SKILL.md), and set `schema_version` to
   `deixis.question_translation.v1`.

Write the sentence only: there is no field for a rationale, a note or a second
version, and none is wanted. Do not answer the question and do not search.
