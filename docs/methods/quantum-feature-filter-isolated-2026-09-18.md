# Isolated question-feature query arm

**Status:** opt-in, post-hoc development experiment. This does not change the DEIXIS product search planner or default. The quantum question, the six control DOIs, the Elicit rows, and two additional IEEE papers were already inspected before this arm was designed. Consequently, none is an independent evaluation target.

## Frozen comparison before provider requests

Arm `b_replay` replays the five queries in the frozen Gemini-assisted Plan B. Arm `c_feature_guard` keeps its first four queries byte-for-byte and replaces only the fifth query. The two arms use OpenAlex `search.title_and_abstract`, five queries, two pages per query, `per_page=100`, at most 1,000 returned slots, and ten logical requests each. Requests are interleaved by page and query slot. A provider failure is reported as partial, not zero results. No citation expansion, PDF extraction, embedding, or study screening runs.

The replacement query is compiled in code from the same frozen question and Gemini proposal, without another model call. Code separates the first question sentence (research target) from its later comparison/reporting instructions. Bare reporting labels `decision variables`, `objectives`, and `constraints` are ineligible for the replacement search branch. It extracts the question's technical `treatment of` facets, excludes `routing` and `scheduling` already represented in the unchanged operation branch, and retains `memory capacity`, `fidelity`, and `decoherence`. The existing Gemini proposal contributes `quantum memory` because it shares the question-owned `memory` word; its model-expansion provenance remains visible. The branch requires the question-owned `entanglement` anchor, at least two technical question facets, and at least one domain-linked model expansion. It fails closed if this question structure or the source plan changes. The resulting fifth query is:

```text
entanglement AND ("memory capacity" OR fidelity OR decoherence OR "quantum memory")
```

This term choice is informed by known misses. It is a diagnostic intervention, not a preregistered general search strategy. No known DOI or paper title enters the compiler.

## Measurements and interpretation

Before looking at new results, save a plan with source, protocol, and script hashes; both exact query lists; term provenance; and the rejected reporting terms. After the run, report request outcomes, returned and exact-identity counts, overlap, and each fifth query's marginal identities. Inspect the already known control and user-supplied IEEE DOIs only in a labelled post-run diagnostic. Preserve exact DOI and work-version distinctions. Candidate counts and control hits cannot establish relevance, inclusion, recall, or superiority. A default-product decision needs fresh questions, equal returned-record and screening budgets, and independent human relevance decisions.

The live DEIXIS library and port `8765` are out of scope. Keep raw provider payloads and evaluation results under ignored `.local/`; do not store credentials.

## Commands

```sh
uv run python scripts/isolated_feature_query_arm.py prepare --source-plan .local/quantum-query-branches-2026-09-18-plan-b/plan.json --plan-dir .local/quantum-feature-filter-2026-09-18-plan
uv run python scripts/isolated_feature_query_arm.py run --plan .local/quantum-feature-filter-2026-09-18-plan/plan.json --output-dir .local/quantum-feature-filter-2026-09-18-run --env-file .env
```

Use new empty plan and run directories. Post-run DOI checks are separate from the completed provider ledger.
