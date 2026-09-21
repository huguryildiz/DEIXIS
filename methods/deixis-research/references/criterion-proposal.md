# Criterion proposal

Goal: from the research question alone, state what a paper must contain to be
included, as a criterion a reader can check in the full text, and name the words
an author would write in a paper that contains it. You are given the question and
the user's steering and nothing else: no records, no search words, no concept
blocks.

1. Read `question.text` and `user_steering`. Write `criterion` as one sentence
   that says what a paper must contain to be included.
2. Give 2 to 5 `parts`. Each part is something the paper itself must do or
   state, not a topic it mentions. Give it a short `name` and a `definition`
   that says what must be present in the paper for the part to be met.
3. Give 6 to 15 `phrases` per part: 1 to 4 words each, lower case, written as
   they appear in running text or as standard abbreviations or notation. A
   phrase is what an author of such a paper would literally write.
4. Separate two things in the question before you write the parts. The
   **setting** is the population, system, domain, material or environment the
   question is asked about. The search already restricts papers to it. Make no
   part out of the setting and give no phrase that only names the setting.
5. The **thing sought** is the specific intervention, method, quantity, object
   or kind of result whose presence makes a paper an answer to the question. It
   is not the setting, even when it is a common term of the field. Name it in
   the criterion sentence, give it a part of its own, and give that part the
   phrases an author uses when writing about it, its synonyms and standard
   abbreviations included.
6. The aspects the question wants compared or reported are not parts. The
   remaining parts cover what kind of study or content the paper must contain.
7. Give `exclusion_title_words`: title words of papers that are about the topic
   but are not primary studies of this kind. Give an empty list when none apply.
8. Echo `step_input_id`, `scope_revision` and `skill_package_hash` exactly as
   they were given, and set `schema_version` to
   `deixis.criterion_proposal.v1`.

Hard cases:

- A term can be both a common term of the field and the thing the question asks
  for. It is then still the thing sought, not the setting: it is named in the
  criterion sentence and has its own part.
- A paper that only mentions a part has not met it. Write each `definition` so
  that a reader can see, on the page, whether the paper itself does or states
  the thing.
- A phrase may be the words a sentence uses or the standard abbreviation or
  notation the field writes instead. Both are forms that stand in the text.
- What the question asks to be compared, reported or varied describes the
  answer it wants, not a condition of inclusion, so it is not a part.

Do not search and do not explain your proposal: there is no field for a
rationale and none is wanted.
