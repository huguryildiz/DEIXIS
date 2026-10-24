# Follow-up search query

A person asked a follow-up question inside a research and chose to search for
works the research does not hold yet. `question.text` is that follow-up
question. `followup_search_context` says what the research already has:
`research_question` is the research's own question, `included_works` the works
it includes (title and year), `searched_queries` the queries its search
already sent, and `unanswered_aspects` and `answer_claims` what the answer to
the follow-up found and left open in the works it holds.

Write terms for what the follow-up asks that the included works do not cover.
Start from `unanswered_aspects` when there are any. The listed titles and
queries show what is already found: do not copy their words as terms unless
the follow-up needs them to stay in the research's field. Keep the research's
setting (its field, system or population) unless the follow-up changes it.

`setting` is the field, system or population; `task` is what the follow-up
looks for in it: the method, mechanism, measure or result. Each term is one to
four words an author of a matching work would write, in English. Use no
quotation marks, parentheses or Boolean operators. Choose at most six terms in
total and fill both blocks. Backups are other names for the same thing, at most
three per block, kept on record and never used to widen the search. Write no
query text: the application compiles the terms for each provider.

A search finds works to screen; it does not show that a work answers the
follow-up, and finding nothing does not show that no such work exists.
