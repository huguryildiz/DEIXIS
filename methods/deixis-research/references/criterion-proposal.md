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
   **setting** is the system, domain, material or environment the question is
   asked about. The search already restricts papers to it. Make no part out of
   the setting and give no phrase that only names the setting. The people,
   patients or animals a study must be done in are not setting: see rule 8.
5. The **thing sought** is the specific intervention, method, quantity, object
   or kind of result whose presence makes a paper an answer to the question. It
   is not the setting, even when it is a common term of the field. Name it in
   the criterion sentence, give it a part of its own, and give that part the
   phrases an author uses when writing about it, its synonyms and standard
   abbreviations included.
6. The aspects the question asks to compare across the papers (their
   variables, methods or results) are not parts; a comparator the question
   names for the thing sought is (rule 8). The remaining parts cover what kind
   of study or content the paper must contain.
7. Give `exclusion_title_words`: title words of papers that are about the topic
   but are not primary studies of this kind. Give an empty list when none apply.
8. When the question names the **population** a study must be done in
   (people, patients or animals with a stated characteristic) or the
   **comparator** the thing sought must be compared with (no intervention,
   usual care, a placebo or another named alternative), give each its own part.
   Its `definition` says what the paper must state about its own participants
   or its own comparison group, so that a study done in other participants, or
   compared with something else, does not meet it. The comparator part's
   `definition` names what the comparison group must receive, in the
   question's words, not only that it does not receive the thing sought, and
   adds no alternative the question does not name (no "or a comparable ...").
   It says that a comparison group that also receives an addition making it
   something other than the named comparator, such as the same restriction
   the intervention group follows, does not meet it. List each such part in
   `question_elements`: its `role` (`population` or `comparator`), the
   question's own `words` that name it, copied exactly, and the `part` name.
   Give an empty list when the question names neither. Apply the comparison
   distinction under Hard cases before you assign roles: for a comparison
   across the literature, list neither alternative nor their combined part as
   `comparator`; keep any `population` entry the question requires.
9. Echo `step_input_id` and `scope_revision` exactly as given, following the
   envelope rule in [SKILL.md](../SKILL.md), and set `schema_version` to
   `deixis.criterion_proposal.v2`.

Hard cases:

- A term can be both a common term of the field and the thing the question asks
  for. It is then still the thing sought, not the setting: it is named in the
  criterion sentence and has its own part.
- A paper that only mentions a part has not met it. Write each `definition` so
  that a reader can see, on the page, whether the paper itself does or states
  the thing.
- A phrase may be the words a sentence uses or the standard abbreviation or
  notation the field writes instead. Both are forms that stand in the text.
- What the question asks to be compared across papers, reported or varied
  describes the answer it wants, not a condition of inclusion, so it is not a
  part.
- When the question seeks a comparison across the literature of named
  methods or alternatives, rather than a comparison within each study, treat
  the alternatives as one thing sought. A question asking how depth-based and
  vector-based routing protocols compare in packet delivery and energy does not
  require every paper to study both. Give them one part whose `definition`
  accepts a paper that studies at least one named alternative and reports what
  the question asks to compare; its phrases cover each alternative. Do not
  infer this reading from "versus" or "compare" alone. When the question asks
  for the effect of an intervention against a stated control (a placebo, no
  intervention, usual care or a named active treatment), keep rule 8's
  separate comparator part. Keep it too whenever the question or the user's
  steering requires the alternatives to be compared within the same study.
  These study-level requirements take precedence over the across-literature
  reading.
- A system, network, material or device the question is about is setting, not
  a population, even when the question says "in".
- A comparator named as no treatment, usual care or an unrestricted
  alternative is not met by a comparison group that receives something the
  question's comparator does not name, such as another active treatment,
  another variant of the same one, or the same added treatment or restriction
  as the intervention group.

Do not search and do not explain your proposal: there is no field for a
rationale and none is wanted.
