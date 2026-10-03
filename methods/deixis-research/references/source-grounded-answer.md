# Source-grounded answer

The application supplies bounded passages for the answer step and stores its validated draft.


## Grounded answer

Goal: a comprehensive report in sections that answers the question from the
supplied passages. Every claim is linked to the passages that support it, and
access and scope limits are stated.

1. Write `title` as a concise descriptive title in the answer language. Aim for
   12–15 words and never exceed 15 words. Do not copy the full question, end the
   title with a question mark, or add claims that the supplied passages do not
   support.
2. Read all passages. Note each passage's `reading_depth` and locator kind
   (`abstract`, `pdf_page`, `section`).
3. Organise the report in sections. Put the section heading in each claim's
   `section`, in the answer language; the claims of one section are consecutive
   and in reading order. Open with an overview section that answers the question
   directly. Then give one section to each part the question asks about (for
   example the decision variables, objectives, constraints and validation of
   published models), and close with a comparison or open-issues section when
   the passages support one.
4. Cover the supplied evidence thoroughly. Report what each relevant source
   states instead of a few representative claims, and do not shorten the report
   to keep it simple. A claim is one to three sentences about one point and cites
   the specific passages that state it, at most five. Prefer several specific
   claims, each saying what one source or a small group of sources did, over one
   claim that lists many sources.
5. `source_stated` claims cite at least one passage that states the claim.
   `analyst_inference` claims cite the passages the inference draws on and the
   text should read as an interpretation.
6. Do not cite a passage for something it does not say. Do not put page numbers,
   equation numbers, DOIs or quotations into claim text; the application displays
   locators from its records.
   For every claim-passage link, also add one `citation_anchors` item containing
   the shortest contiguous sentence or sentences that directly support the
   claim. Copy `quote` exactly from that passage: keep its language, punctuation,
   mathematical extraction and wording; do not translate, repair, paraphrase,
   add ellipses or join non-contiguous spans. If no exact contiguous span supports
   the claim, the passage does not support that claim and must not be cited.
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
   abstract states and add an `access` limitation naming that source.
10. When passages disagree, say so and add a `conflicting_evidence` limitation.
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
written with the Academic Phrasebank frames in
[phrases.md](phrases.md).

- Build each sentence on one phrasebank frame where one fits. Replace only its slots (`X`, `Y`,
  `Z`, `…` and the example content words such as topic nouns, author names and
  years) with content from the cited passages; keep the frame's other words, word
  order and tense. In a substitution table a frame is one stem plus one
  continuation. A sentence may open with a linking phrase that is itself in the
  phrasebank, for example "However," or "In contrast,".
- Do not add framing, hedging, linking or evaluative wording that is not in the
  phrasebank. A frame that changes who did what, what a source reports, or why
  something is limited is the wrong frame; pick another, never change the
  statement to fit a frame.
- The evidence rules decide which frames are allowed. A frame's certainty must
  match the support: "It is now well established that …" or "… conclusively
  shown that …" need passages that state it that strongly, and
  `analyst_inference` claims use cautious frames such as those under Being
  Cautious or Suggesting general hypotheses.
- Choose frames by what the sentence does:
  - What a cited source did or reported: frames for referring to single
    investigations or previous research, for example "It has been reported that
    …" or "In an analysis of X, … found …". Example content in a frame, such as
    the author and topic in "One study by Smith (2014) examined the trend in …",
    still counts as frame wording, so a frame whose example words you would have
    to drop is not a fit; choose one with open slots.
  - Words that name the writer's own work ("this study", "the present study",
    "this paper", "the current investigation") refer to this answer and its
    supplied passages, never to a cited source; write them as "this answer" or
    "the supplied passages". For example, "The study is limited by the lack of
    information on …" becomes "This answer is limited by the lack of information
    on …".
    In report claims, own-work wording is a blocking issue, including after phrase repair; use a supported
    source-reporting frame or wording about the report. Ordinary answers retain their warning policy.
  - Access, scope and unanswered parts: frames about what could not be assessed
    or addressed, for example "It was not possible to assess X; therefore, it is
    unknown if …", "An issue that was not addressed in the supplied passages was
    whether …", "It is beyond the scope of this answer to examine …".
  - Gap and novelty frames ("This is the first study …", "No previous study has
    …", "There is a paucity of …", "Very little is known about …", "It is still
    not known whether …") state something about a whole field. Use them only when
    a cited passage says so, and attribute it to that source; never for what the
    supplied passages happen not to report.
- Use author names and years only as they appear in the StepInput records; never
  invent them. Do not use frames that point to a table, figure, page or section
  number, such as "As shown in Figure 1"; the application rejects locators in
  claim text.
- For a Turkish question the frames you receive are already literal Turkish
  renderings; use them as written, adding only the endings a filled slot needs.
  Their own-work words ("bu çalışma", "mevcut çalışma", "bu makale") become
  "bu cevap" or "sağlanan pasajlar", as in English, and never name a cited
  source; "Önceki çalışmalar" needs several cited sources. To report what one
  source states, turn the reported verb into its participle inside a reporting
  frame, for example "Röle konumlarının sezgisel bir yöntemle seçilmiş olduğu
  bildirilmiştir." or "… tarafından yapılan bir çalışma, …'i incelemiştir."; for
  an unanswered part, "Sağlanan pasajlarda ele alınmayan bir konu, modellerin
  doğrulanmış olup olmadığıydı."
  For another non-English language, translate the chosen English frame literally,
  keeping its structure, certainty and hedging. Do not write a sentence that has
  no frame behind it, and do not replace a frame with a freer idiomatic phrase.
- The application checks every sentence of these fields against the frames and
  flags sentences without a frame, claims that use the writer's own-work words
  ("this study", "bu çalışma") and several-sources wording for a one-source
  claim. The flags are shown with the answer and never reject it; do not drop
  evidence or shorten the report to avoid one. LaTeX math counts as one slot.
