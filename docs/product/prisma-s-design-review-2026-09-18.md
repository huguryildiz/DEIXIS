# PRISMA-S hybrid-search design: Fable review and disposition

**Date:** 2026-09-18. **Status:** design review, not an implemented workflow or scientific validation. Reviewed document: [PRISMA-S hybrid-search design](prisma-s-hybrid-search-design-2026-09-18.md), before the revisions below.

A read-only, tool-free Claude CLI call requested `claude-fable-5-1` at `medium` effort. It returned `subtype=success`, `is_error=false`, and `modelUsage` named `claude-fable-5-1`; a `claude-haiku-4-5-20251001` usage entry also appeared, with role undetermined. No fallback model was requested. Prompt SHA-256: `299ffffe605cef771f479acc3b11ee7e2b4ba595ba64e77e44f487b0713c4b62`; response JSON SHA-256: `d93c1f50d421177e42c89b4d1170962027c64dd60548e1bd867445ccc7569a94`. The complete prompt and response remain in ignored `.local/prisma-s-design-review-2026-09-18/`. Fable saw the supplied document, not the repository or live providers.

| Finding | Disposition in the revised design |
|---|---|
| B1: PRISMA 2020 other-methods branch lacks a title/abstract screening box. | Accepted. Citation preliminary screening is an accompanying table; the branches meet at included studies. An incomplete selection ledger does not produce a complete flow. |
| B2: Term-feedback was inconsistently called an “other method.” | Accepted. It is a database-search iteration under PRISMA-S items 1, 8 and 13. |
| B3: Request states mixed valid zero results with failures. | Accepted. `completed` plus zero returned is distinct from invalid request, entitlement, rate limit, timeout and server error. |
| B4: A single discovery-route label hides overlap. | Accepted. Store all timestamped routes; report first-route and any-route counts separately. |
| B5: The second-round yield rule was undefined. | Accepted. Require at least one newly confirmed relevant first-round work and a remaining per-seed edge-request budget; freeze the screening cap in the run protocol. |
| B6: Known controls could also be seeds. | Accepted in part. Do not prohibit scientifically plausible seeds based on a development answer set; mark such seeds and exclude them from **marginal graph gain**. |
| B7: Model exclusions could vanish from PRISMA counts. | Accepted in part. Keep unseen model-ranked records `unassessed` and the diagram incomplete. Count an automation removal only if the workflow actually removes records before screening under a recorded rule. |
| B8: Elicit inclusion may follow different criteria. | Accepted. Overlap remains descriptive unless Elicit rows receive human reassessment under the same frozen criteria. |
| B9: `unsupported` mixed absence with contradiction. | Accepted. Separate `contradicted`, `not_found_at_depth` and `uncertain`; freeze feature columns. |
| O1–O6: Edge hydration, unavailable totals, seed thresholds, term method, baseline definition, and ledger fields. | Accepted as protocol or schema requirements; the design now distinguishes raw edge counts from hydrated records and specifies the remaining fields to freeze. |
| O7: The supplied design allegedly ended with a Python script. | Rejected. The reviewed document contained no script. This is a model observation error. |

This disposition is an analyst assessment of a model review. It does not mean PRISMA compliance or literature-search quality was externally verified.
