# DEIXIS product design

DEIXIS is the current product name. The [14 September handoff](../desktop/README.md) preserves earlier Quaestio wording as history; the sibling Quaestio repository remains a separate methodological skill. This page is a navigation summary, not a replacement for the detailed accepted decisions in the handoff.

The [implementation plan](implementation-plan.md) is the comprehensive proposal for the working mechanism, DEIXIS research skill, technical architecture, staged implementation and acceptance tests. The owner requested plan preparation and Claude Fable 5.1 High review before application installation. Technical defaults in that plan remain proposals until their stated decisions and checks are resolved.

The [completed plan review](plan-review-2026-09-14.md) records `ready_with_changes` for draft 1 and the disposition applied in draft 2. No application installation or live research validation is implied.

## Accepted boundaries

- First release: a single-user, local web application with a browser UI and local backend. Tauri packaging for macOS and Windows is a later stage, not a shortcut around backend packaging and process management.
- Start with a question. Academic discovery, user-visible source selection, accessible evidence inspection, source-linked answer and recoverable session form the first narrow workflow. PDF upload is optional; evidence tables build on this foundation.
- Scholarly coverage includes Semantic Scholar, Crossref, arXiv, OpenAlex, Scopus, IEEE Xplore and SerpApi, implemented in stages. The user may add further sources through a defined connector contract. Source selection and model selection are separate.
- One main research agent suffices. Deterministic retrieval, parsing, provenance, persistence and budget checks belong to application code. Missing full text, source errors, model inference and unsupported claims must stay visible.
- The synthesis method is Chain of Ideas adapted with purpose–mechanism–evaluation candidate framing and a distinct claim-specific kill-search. A model's assessment is not scientific validation.
- Preserve user corrections, source and version IDs, citation-to-passage links, and completed work across reopening. Do not silently switch model or academic provider after a failure.

The [API, evidence and local-data design](api-and-data.md) remains a draft. [Research-method detail](../methods/research-methods.md) and the [user-supplied domain example](../methods/domain-example.md) are separate from runtime requirements. [Provider variable names](providers.env.example) contain no credentials.

The [first-slice design and acceptance plan](first-slice-plan.md) defines the question-to-citation-to-resume sequence before a new DEIXIS method instruction, backend adapter, or live research run is attempted.

## Integration evidence and open choices

On 14 September 2026, local Codex and Claude Code installations, signed-in account states, and one temporary tool-free model response from each were observed. Codex App Server also returned account type and a model catalog. This verifies local access on that machine at that time, not DEIXIS adapters, subscription terms for all integration patterns, source-grounded answers, or cross-platform support. Neither model is connected to the UI or backend.

The owner prioritized Codex, then the Claude account, then DeepSeek API. The DeepSeek key posted in conversation must be revoked and replaced before testing; no value belongs in this repository or the UI prototype. Frontend/backend stack, first academic connector, persistence schema, adapter boundaries, model selection policy and evaluation fixture remain implementation decisions to make before or during the first vertical slice. No real scholarly search or source-grounded answer has been demonstrated here.
