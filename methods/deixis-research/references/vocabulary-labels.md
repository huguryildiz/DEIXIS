# Vocabulary labels

Goal: sort the search phrases the application has already taken from the question
into the concept blocks its query is built from. The application extracts the
phrases. This step only labels them; it proposes no terms of its own.

1. Read `vocabulary_target.question_text` and `vocabulary_target.phrases`. Each
   phrase carries `rule_block`, where a crude code rule put it. That rule reads
   the word standing in front of the phrase and is often wrong, so treat it as
   context, not as an answer to confirm.
2. Return one `labels` entry for every given phrase, with `phrase` copied exactly
   as it was given. Never add a phrase, never split, merge or reword one, and
   never leave one out. A phrase that welds two ideas together is still one
   phrase and gets one label.
3. Give each phrase exactly one block:

| `block` | The phrase names |
|---|---|
| `setting` | who or where the work happens: the population, domain, system, material, corpus, environment or period the question restricts itself to. |
| `task` | what is studied, done or varied: the intervention, the factor, the operation. |
| `outcome` | the quantity measured or the result reported. |
| `claim` | the particular method, model or assertion the question puts under test. |
| `exclusion` | what the question rules out. |
| `not_a_term` | nothing searchable on its own: a leftover relational or role word that names no subject matter. |

4. Echo `step_input_id`, `scope_revision` and `skill_package_hash` exactly as
   they were given, and set `schema_version` to `deixis.vocabulary_labels.v1`.

Hard cases:

- The word in front of a phrase does not decide its block; the meaning of the
  phrase does. A phrase introduced by "with", "using" or "through" is a `setting`
  when all it says is where, or in whom, the work happens.
- Use `claim` only when the question asks whether the literature uses that
  particular method or makes that particular assertion. A method named only to
  narrow the setting is a `setting`. The application keeps `claim` phrases out of
  the query deliberately: work doing the same thing may name it differently, so
  requiring the name would hide it.
- A phrase that welds two concepts together takes the block of its leading
  concept.

Do not translate the phrases, do not search, and do not explain your labels:
there is no field for a rationale and none is wanted.
