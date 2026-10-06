# Term advice

Goal: the approval card warns that one search term multiplies the number of
matches. For each warned term, say whether the user should remove it or keep it,
and give one plain sentence why. Your advice is shown as information. Nothing
is removed because of it: under the default mode every term is kept and the
search runs as proposed, and a person who is asked decides for themselves. You
write no query.

1. Read `advice_target.question_text`, `advice_target.searched_terms` and
   `advice_target.warnings`. Each warning gives a `phrase`, its `block`,
   `matches` (the records the search matches as it stands) and
   `matches_without_term` (the records it would match with that one term taken
   out). The two blocks are both required in a paper: a record must match at
   least one term of each.
2. Return `advice`: exactly one entry for every warned term, none twice and none
   for a phrase that is not in `warnings`; if one warned phrase is missing, the
   whole answer is not used. Each entry has `phrase`, copied exactly, `recommendation`
   and `reason`.
3. Recommend `remove` when the term is broad and stands for something the
   question does not ask about, so papers from other fields match only because
   of it. Recommend `keep` when the term names what the question asks about, so
   a paper that answers the question would normally say it: taking it out would
   drop those papers and leave a flood of near matches in their place. A term
   that sits next to more specific terms in its block and is also the question's
   own subject is usually `keep`; a general word for the setting that the other
   terms of the search already narrow is usually `remove`.
4. Write `reason` as one sentence in English for a reader who is not an expert.
   Say what the term does to the search and why that helps or hurts, in
   everyday words. Do not use the words block, setting, task, gate, query,
   schema or token, and do not quote the counts as the whole reason: the counts
   show the term widens the search, they do not say whether the widening is
   wanted.
5. Echo `step_input_id` and `scope_revision` exactly as given, following the
   envelope rule in [SKILL.md](../SKILL.md), and set `schema_version` to
   `deixis.term_advice.v1`.

Hard cases:

- A term that is both broad and central to the question: keep it, and say that
  the question is about it.
- A warned term you cannot judge from the question alone: give `keep`, because
  removing a term loses papers silently and keeping one only widens the list
  the user already screens.

Do not search, do not write operators or quotation marks, and do not propose
new terms.
