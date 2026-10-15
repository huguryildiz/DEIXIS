# Source-grounded answer

The application supplies bounded passages for the answer step and stores its validated draft.


## Grounded answer

Goal: a short answer in a few paragraphs that answers the question from the
supplied passages. Every claim is linked to the passages that support it, and
access and scope limits are stated. The application shows a study table and the
search method beside the answer, so the answer need not list what each source
did.

1. Write `title` as a concise descriptive title in the answer language. Aim for
   12–15 words and never exceed 15 words. Do not copy the full question, end the
   title with a question mark, or add claims that the supplied passages do not
   support.
2. Read all passages. Note each passage's `reading_depth` and locator kind
   (`abstract`, `pdf_page`, `section`).
3. Write three to five paragraphs. Each paragraph is one `section`: put in each
   claim's `section`, in the answer language, a label of two to five words that
   names the paragraph's topic (for example "Direct comparisons" or "Network
   density"), which the application shows in bold at the start of the
   paragraph. The label names a topic and states no finding; the paragraph's
   first claim states its main point. The claims of one section are
   consecutive and in reading order. The first paragraph answers the question
   directly, with the numbers the passages give for it.
   Later paragraphs give what the answer depends on (conditions, settings,
   disagreements between sources) and its main qualification.
   Organize paragraphs by topic, not by source. Read in order, the first claims
   of the sections should make the answer's argument on their own; if they read
   as a list of sources, regroup the claims. Grouping by topic does not change
   rule 5: each source's finding stays its own claim, and a statement across
   sources is an `analyst_inference` after them. When the question names
   alternatives to compare, give the conditions under which the passages show
   each doing better, not one summary per alternative; when the passages report
   the alternatives in settings that cannot be compared, say that the comparison
   cannot be made from them. When the question takes something as given that
   the supplied passages contradict, say so in the first paragraph; when they
   do not show it, say that the supplied passages do not show it. These rules
   stay within the claim limit of rule 4 and the Phrasing rules below.
4. Keep the answer short: two to six claims per paragraph, at most thirty
   claims in all. Choose the passages that bear most directly on the question,
   above all those that compare the alternatives the question names or report
   the quantities it asks about. A claim is one or two sentences about one
   point and cites the specific passages that state it, at most five. Do not open
   more than two claims with the same reporting frame.
5. A `source_stated` claim reports what one source states: one finding in one
   setting. Cite only that source's passage or passages, each of which must on
   its own state the whole claim. The application rejects a `source_stated`
   claim whose passages come from more than one source; two versions of one
   work, such as a preprint and its published article, count as two sources
   and are not independent evidence. When several sources
   report the same finding, write one claim per source; never assemble a claim
   from parts stated by different passages.
   An overview of what several sources used or studied follows the same rule:
   write one claim per source naming what it used, studied or found. Do not write
   "approaches include A, B and C" citing different sources for A, B and C.
   For a comparison across sources, write the source claims first, then, if
   useful, an `analyst_inference` claim citing their passages. It must read as an
   interpretation and may only combine what those passages state; it adds no
   condition, cause, setting or factor that none of them states.
   Use several-sources wording such as "previous studies" or "studies have" only
   in such an `analyst_inference` claim, and only for a finding that each cited
   passage states; a relation between the studies is the interpretation.
6. Do not add a condition, number, comparison, evaluation or scope that the cited
   passage does not state. Drop the extra part or move it to a separate claim
   with its own passage. Do not put page numbers, equation numbers, DOIs or
   quotations into claim text; the application displays locators from its records.
   For every claim-passage link, also add one `citation_anchors` item containing
   the shortest contiguous sentence or sentences that on their own support the
   whole claim, not just one part. Copy `quote` exactly from that passage: keep
   its language, punctuation, mathematical extraction and wording; do not
   translate, repair, paraphrase, add ellipses or join non-contiguous spans.
   If no single exact contiguous span in a passage supports the whole claim,
   split the claim. Cite that passage only for a claim the span supports in full.
7. Write mathematical content (decision variables, objective functions,
   constraints, channel or energy models) in LaTeX, between `$…$` inside a
   sentence or `$$…$$` for a displayed expression. Write an expression only as a
   cited passage states it; do not invent notation or turn a verbal description
   into a formula the passage does not give. When a passage gives a formulation,
   present it so a reader can learn it: first the decision variables with their
   symbols and meaning, then the objective, then each constraint or constraint
   group with what it enforces. PDF text often loses sub- and superscripts
   (`f kl ij` for $f^{kl}_{ij}$); restore them only where the passage's own
   definitions make the reading unambiguous, and otherwise describe the
   expression in words.
   Report sections additionally require balanced math and a supplied origin passage containing recognized
   math, cited by this claim's own passage anchor, with matching `text_source`; a cell anchor alone is insufficient.
   A passage's `text_source` says how its text was obtained. `text_layer` is the
   PDF's own text. `marker` text was read from the page image by a model that
   writes equations as LaTeX; its equations are usually exact, but a symbol or
   subscript can be misread while the expression still looks correct. `ocr` text
   comes from a scanned page and often misreads numbers, symbols and equations.
   Copy numbers and equations from `marker` or `ocr` passages as written, and
   when a claim rests on an equation or number from such a passage, say in the
   claim that it should be checked against the PDF page.
   `latex_source` is the PDF's own text of a passage in which one or
   more displayed equations numbered on the page were replaced by the authors'
   LaTeX from the arXiv source of the same version; code matched each one to the
   page by its number and letters and did not check that the source compiles to
   this page. Copy those equations as written. Everything else in the passage,
   including other mathematics, is the PDF's text layer.
   `equation_ocr` is the PDF's own text of a passage in which one or more
   displayed equations numbered on the page were replaced by LaTeX that Mathpix
   read from an image of the page. Code checked that its letters, digits,
   sub- and superscripts, signs and fraction bars agree with the PDF's own
   text; a symbol can still be read in the wrong place. Quote a symbol from
   such an equation only with the page as the check, and say so in the claim.
   `equation_fallbacks` gives the PDF's raw text of the same equation for
   comparison; it is not part of the passage and cannot be cited.
   Distinguish variables optimized inside a displayed formulation from fixed
   inputs, choices computed by a separate local problem, and candidates
   compared by solving the formulation repeatedly. A source's title or abstract
   may describe the overall framework as "joint" or "cross-layer"; that wording
   alone does not establish that every choice is a decision variable of one MIP.
   When the supplied equations and procedure show separate stages, state those
   stages explicitly and do not attribute their choices to the MIP itself.
8. Write for a reader new to the topic. Define each technical term from the
   passages the first time it is used, for example in a key-concepts section after
   the overview. Say what a formulation or result means and how approaches differ;
   when that explanation is your reading of the passages rather than their
   statement, make it an `analyst_inference` claim.
9. When a source is available only as an abstract, restrict claims to what the
   abstract states and add an `access` limitation naming that source. When you
   report a number from an abstract, say in the claim that it comes from the
   abstract. If every supplied passage is an abstract, state in an `access`
   limitation that the answer is based only on abstracts.
10. When passages disagree, say so and add a `conflicting_evidence` limitation.
   Match certainty to the evidence. A finding one source reports is that
   source's finding, not an established result. When a passage states the
   setting of a result (simulation, testbed, field trial, clinical trial,
   cohort), say it in the claim; never name a setting the passage does not
   state. Three record fields may be used in claim text without a passage
   stating them: a source's `year`, its `is_retracted` flag (rule below), and a
   `version_label` of
   `submittedVersion`, written as "the submitted version" or "a preprint
   version" and never as unpublished or not peer reviewed. No finding, setting
   or relation between sources may come from record fields. When one source
   refines or contradicts another, write each source's claim separately, with
   its year when the record gives one, then the relation as an
   `analyst_inference`. Only when one source's passage itself states the
   relation to another work is that a `source_stated` claim citing that
   passage alone. A later year alone does not show that one result replaced
   another.
   A source marked `is_retracted` belongs to a work that OpenAlex flags as
   retracted in at least one of its versions, which may be another version than
   the one supplied. Cite it only together with saying in the claim that
   OpenAlex flags this work as retracted, never that this version was
   retracted, and never as support for a claim on its own.
11. Put parts of the question the passages do not answer in `unanswered_aspects`.
   An empty claim list with a clear statement of what is missing is a valid answer.
12. A structured report of what the supplied passages state is supported. If the
   question requests an unsupported mode (synthesis chains that derive new
   findings across sources, candidate questions, kill-search, experiments), set
   `capability_notice` and add an `unsupported_request` limitation; still answer
   the supported part.
13. Word every text field as set out in Phrasing below.

### Phrasing

Claim text, limitation text, unanswered aspects and the capability notice are
plain academic prose in the answer language.

- Write each sentence in your own words. Do not open sentences with a fixed
  reporting formula ("It has been reported that …", "… bildirilmiştir.") and do
  not repeat one sentence opening across claims. Name the finding directly, for
  example "DBR saved more energy than VBF in a 500-node simulation." The
  citation already says who reported it.
- Certainty follows the evidence: state plainly what a passage states plainly,
  and hedge `analyst_inference` claims ("may", "suggests") without overstating.
- Words that name the writer's own work ("this study", "the present study",
  "this paper", "bu çalışma") refer to this answer and its supplied passages,
  never to a cited source; write "this answer" or "the supplied passages"
  ("bu cevap", "sağlanan pasajlar"). In report claims, own-work wording is a
  blocking issue; ordinary answers get a warning.
- "Previous studies", "several studies" and the like need several cited
  sources; for a one-source claim, speak of that one source.
- Gap and novelty statements ("This is the first study …", "Very little is
  known about …") describe a whole field. Use them only when a cited passage
  says so, and attribute it to that source; never for what the supplied
  passages happen not to report.
- Use author names and years only as they appear in the StepInput records;
  never invent them. Do not point to a table, figure, page or section number,
  such as "As shown in Figure 1"; the application rejects locators in claim
  text.
