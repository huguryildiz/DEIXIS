# Follow-up answer

A person asked a follow-up question inside a research that already has its
sources. `question.text` is that follow-up question, not the research question.
The application chose the passages in this StepInput from the passages it
already holds for this research, ranked against the follow-up question. No
search was run for this question and none will be run because of your answer:
answer only from the supplied passages.

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
