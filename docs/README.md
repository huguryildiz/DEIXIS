# Documentation map

Start with the [product decisions and open technical choices](product/README.md), then the [repository layout](layout.md). [D1](decisions.md) records why the documents are separated.

The [implementation plan](product/implementation-plan.md) consolidates the proposed working mechanism, skill package, architecture, milestones and acceptance tests. Its status records the requested Claude Fable 5.1 High review; it is not a claim of implemented features.

The [plan review and finding disposition](product/plan-review-2026-09-14.md) preserves the Fable verdict, reviewed hashes, original report and subsequent corrections. The revised plan has not received a second model review.

| Location | Authority and purpose |
|---|---|
| [Product](product/README.md) | Current concise map of accepted product constraints, proposed contracts, and unresolved choices. The [first-slice plan](product/first-slice-plan.md) and [API and data design](product/api-and-data.md) are drafts, not implemented features. |
| [Methods](methods/research-methods.md) | Research-method comparison and proposed workflow; [domain example](methods/domain-example.md) is illustrative, not the product's fixed scope. The [isolated quantum 500/1000 protocol](methods/quantum-hybrid-500-1000-protocol-2026-09-18.md) is an opt-in development experiment, not the product default. |
| [Dated handoff](desktop/README.md) | Detailed record of the 14 September 2026 conversation and accepted user decisions. Historical names and unimplemented proposals are preserved. |
| [Reference index](desktop/reference-index.md) | Provenance and limits of the private transfer package, screenshots, and inspected design references. |
| [Design prompt](desktop/design-prompt.md) | Historical continuation prompt, not an instruction to execute automatically or the canonical implementation plan. |
| [Decisions](decisions.md) | Durable decisions made after the handoff. An accepted decision is distinct from verified implementation. |
| [Search workflow review](product/search-workflow-review-2026-09-18.md) | Accepted design direction for search and screening (`SW1`…), measured on one topic in isolated runs and not implemented; an entry moves to Decisions when it is. |
| [Search workflow build](product/sw-status.md) | Master file for building `SW1`–`SW16` into the product: slice status, the slice file and prompt to use next, and open owner decisions. Scope and acceptance conditions are in the [implementation plan](product/sw-implementation-plan.md). A plan, not implemented behavior; where it differs from the review, the review's text holds. |

The [root bibliography](../README.md#research-workspace-methodological-references) holds the transferred methodological references. The sibling Quaestio repository is a separate methodological skill, not a DEIXIS runtime dependency already wired in.
