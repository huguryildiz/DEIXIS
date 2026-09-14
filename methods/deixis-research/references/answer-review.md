# Answer review

Goal: an additional reading of an answer that another model step wrote. For each
claim in `claims_under_review`, say whether the passages that claim cites support
it. The review is shown next to the answer as an additional model assessment. It
does not change the answer, and it is not peer review or independent verification.

In this step you review; you do not answer the question again, add claims, or
suggest new sources.

1. For each claim, read only the passages listed in its `passage_ids`. Other
   passages in the StepInput do not count as support for that claim.
2. Choose one verdict per claim:
   - `supported`: the cited passages state what the claim says. For an
     `analyst_inference` claim, the inference follows from them without adding
     facts they do not contain.
   - `partially_supported`: part of the claim is supported, or the claim is
     stronger, broader or more certain than the passages.
   - `not_supported`: the cited passages do not say this, or they contradict it.
   - `cannot_assess`: the passages are too short, garbled or ambiguous to judge.
3. Check reading depth. A claim about methods, equations, constraints or results
   that cites only an abstract is supported only as far as the abstract states it.
4. Check `support_type`. A `source_stated` claim that is only an inference from
   its passages is at most `partially_supported`; say so in the reason.
5. Write the reason in one or two sentences: name what the passages do or do not
   state. Do not quote page numbers or DOIs; the application shows locators.
6. Review every claim exactly once, using its `claim_label`. Use `notes` for an
   observation about the answer as a whole, such as two claims that contradict
   each other; otherwise leave it empty.

Write reasons and notes in the question's language unless the StepInput says
otherwise.
