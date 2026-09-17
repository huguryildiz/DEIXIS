# Elicit–Consensus–DEIXIS comparison protocol

**Status:** frozen before the new DEIXIS search. **Date:** 2026-09-17.

This is an isolated retrieval comparison for the algae-specific OR question. The
two external reports are comparison outputs, not a gold standard. No claim about
field-wide recall, scientific novelty, or product superiority follows from this
run.

## Question

Which algae-specific signalling or molecular-communication research gap can be
translated into a defensible LP/MIP problem, considering quorum sensing, VOC,
electrical, optical signalling, channel modelling, controllability, biological
constraints, and resource allocation?

## DEIXIS procedure

- One tool-free `gpt-5.6-luna` medium call proposes a validated SearchPlan.
- The current DEIXIS compiler uses the available academic providers in fixed
  order and at most eight requests; OpenAlex core search is read to 100 and
  other requests to 25 where the compiler specifies it.
- Every query, provider status, requested limit, returned count, provider total,
  raw payload hash, model identity and token usage is retained in ignored
  `.local/` output.
- Records are deduplicated by DOI where available, otherwise provider identity.
- A small control set consists of DOI-identified papers cited by both external
  reports or central to their stated comparison. It is incomplete and measures
  known-work coverage, not recall.

## Comparison dimensions

Compare the external reports and DEIXIS on source overlap, distinct works,
evidence status, algae-specific versus generic transfer, model-admission
conditions, citation/DOI integrity, and unsupported or unresolved claims.
Source counts remain separate from found, unique, screened, included, inspected,
given-to-model and cited counts.

## Limits

Elicit and Consensus used opaque product workflows and their historical corpus
and model settings are not reconstructed here. Their numerical claims and
citations require independent verification. DEIXIS discovery results alone do
not establish passage-level support; a later answer/passage run is needed for
that question.
