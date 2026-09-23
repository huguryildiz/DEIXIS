# Search query

Goal: write the keyword query of a scholarly literature search for
`question.text`. You do not search and you do not answer the question. The
application counts every term you give and shows your query to the user before
anything is searched.

A paper is found when its title or abstract holds at least one term of EACH
block:

    (setting terms, joined by OR) AND (task terms, joined by OR)

- `setting`: where the work happens — the field, system, population or
  material the question is about.
- `task`: what the question looks for in that field — the problem,
  intervention or kind of method it asks about.

Write the query:

1. Pick the best query of AT MOST 6 terms in total, with at least 1 term in
   each block (for example 2 + 4 or 3 + 3). Fewer is fine when fewer terms
   describe the question well; never add a term just to fill a place.
2. The task block holds at least one term that names the topic or the work
   done — the problem, the object designed or optimised, the process studied —
   in words any relevant paper would use. Method, algorithm or model-family
   names come only beside such a term. Before answering, check: "would a
   relevant paper that names none of my method terms still be found?" If not,
   replace a method term with a topic term. Only a question that asks for one
   specific method may keep that method as a main term.
3. Every term, together with a term of the other block, should find papers
   worth screening. Prefer the terms authors of that field actually write in
   titles and abstracts, including common synonyms and abbreviations (e.g.
   "ILP" beside "integer linear programming").
4. Give every chosen term its `kind`: `topic` (the subject, problem, object or
   process), `method` (a method, algorithm or model family), `population` (the
   people, organisms or group studied) or `other`; and a short `why`, at most
   8 words.
5. Then add up to 3 backup terms per block (`setting_backup`, `task_backup`),
   in order, to be used if a chosen term finds nothing.
6. Order every list from the most important term to the least.

Leave out:

- what the question wants compared or reported about each paper: features,
  parameters, outcomes, metrics (e.g. "channel model", "objectives",
  "accuracy"). These are read from the papers found, not searched for;
- words about the answer itself: cite, verify, compare, full text;
- words so general that most papers of any field hold them (model, method,
  approach, system, optimization alone);
- a question term with a general word welded on ("X optimization" when authors
  write "X").

Do not list both the singular and the plural of a term; the search treats them
as one. Each term is 1 to 4 words, with no quotation marks, parentheses or
Boolean operators, and no term appears twice.

Echo `step_input_id`, `scope_revision` and `skill_package_hash` exactly as they
were given, and set `schema_version` to `deixis.search_query.v1`.
