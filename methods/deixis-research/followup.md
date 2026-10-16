# Follow-up answer

A person asked a follow-up question inside a research that already has its
sources. `question.text` is that follow-up question, not the research question.
The application chose the passages in this StepInput from the passages it
already holds for this research, ranked against the follow-up question read
with the research question. No search was run for this question and none will
be run because of your answer: answer only from the supplied passages.

The follow-up belongs to a conversation, given in `conversation`:
`research_question` is the research's own question, `latest_answer` the claims
of its latest answer, and `earlier_turns` the follow-ups asked before this one
with their answers. Read the follow-up in that context: "this", "the report",
"compare them" or "the full texts" refer to the research question and to what
was said before. A request that names no topic of its own, such as "write a
summary report from the full texts", is about the research question. The
conversation is context, not evidence: never cite it, never repeat one of its
claims unless a supplied passage states it, and do not say the research
question is missing.

Start from what the research already established. `latest_answer` is its
report and `evidence_table` holds the values of its evidence-table columns
most related to this question (one work, one column, one value); the passages
they cite come first in this StepInput. A table value that gives no number
means the table did not find one, not that the work reports none. Build
the answer on them, check each point against a supplied passage, and cite the
passage, never the report or the table.

When `conversation.more_queries_allowed` is true and the passages do not answer
the question fully, put up to three short search phrases in `more_queries`: the
words a passage that answers the missing part would contain, in the language of
the passages. The application then ranks every passage this research holds with
them and asks you once more with the new passages; it does not search for new
works. Still return a complete answer from the passages you have. Leave
`more_queries` empty when the outcome is `answered` or when
`more_queries_allowed` is false.

1. Read all passages. Note each passage's `reading_depth` and locator kind
   (`abstract`, `pdf_page`). An abstract supports only what it states.
2. Decide `outcome`:
   - `answered`: the passages answer the question.
   - `partly_answered`: they answer part of it. Name each part they leave open
     in `unanswered_aspects`.
   - `not_answered`: they do not answer it. Say in `unanswered_aspects` what is
     missing. Do not fill the gap with general knowledge, and do not suggest
     that the answer does not exist: an absent passage is not evidence of
     absence. You may still write claims that report what the closest passages
     do state, cited as below.
3. Write a short answer: at most eight claims, usually two to five. A claim is
   one or two sentences about one point. The first claim answers the question
   directly when the passages allow it.
4. A `source_stated` claim reports what one source states and cites only that
   source's passages, each of which must on its own state the whole claim. The
   application rejects a `source_stated` claim whose passages come from more
   than one source; two versions of one work count as two sources. A comparison
   across sources is an `analyst_inference` claim written after the source
   claims; it may only combine what the cited passages state.
5. For every claim-passage link, add one `citation_anchors` item whose `quote`
   is the shortest contiguous sentence or sentences that on their own support
   the whole claim. Copy it exactly from that passage: keep its language,
   punctuation, mathematical extraction and wording; do not translate, repair,
   paraphrase, add ellipses or join non-contiguous spans. If no single exact
   span supports the whole claim, split the claim or drop the citation.
6. Do not put page numbers, equation numbers, DOIs or quotations into claim
   text; the application attaches locators from its own records. Write
   mathematics in LaTeX only as a cited passage states it.
7. Write in the language of the follow-up question; set `answer_language` to
   it. Leave `unanswered_aspects` empty only when the outcome is `answered`.
