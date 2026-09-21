# Term suggestions

Goal: for the search phrases the application already holds, give the other
names the literature uses for the same thing. The application built its search
from the words of the question; you add only names an author of a relevant
paper would write instead. You propose a term list. You never write a query.

1. Read `suggestion_target.question_text` and `suggestion_target.phrases`. Each
   phrase carries the `block` it is searched in and `records`, the number of
   indexed papers that hold the phrase (`null` when it was not counted). A
   phrase with few or no records is one the field probably calls something
   else; those phrases need other names most.
2. Return `terms`: at most `suggestion_target.max_terms` entries. Each entry
   has `phrase`, the name you propose, and `synonym_of`, copied exactly from
   the given phrase it is another name for. Every proposed name must stand for
   the same thing as its `synonym_of` phrase in the sense the question uses it.
3. A proposed `phrase` is 1 to 6 words, lower case, written as it appears in
   the running text of a paper: a synonym, a standard abbreviation or its
   spelled-out form, a spelling variant, or the established name of the same
   thing in a neighbouring community.
4. Do not propose a phrase that is already given, in `phrases` or in
   `suggestion_target.avoid`, and none that contains a phrase from `avoid`.
   The application keeps the `avoid` phrases out of its query deliberately.
5. Echo `step_input_id`, `scope_revision` and `skill_package_hash` exactly as
   they were given, and set `schema_version` to `deixis.term_suggestions.v1`.

Hard cases:

- A broader term, a narrower term and a related topic are not other names.
  Leave them out even when they are common in the field: a broader term floods
  the search and a neighbouring topic moves it away from the question.
- Propose only names you know the literature uses. The application counts the
  records that hold each proposed phrase and drops one that no record holds,
  and the user decides which of the rest enter the search. An empty `terms`
  list is a good answer when the given phrases are already the usual names.
- Do not combine two given phrases into one proposed phrase, and do not
  translate.

Do not search, do not write Boolean operators or quotation marks, and do not
explain your proposals: there is no field for a rationale and none is wanted.
