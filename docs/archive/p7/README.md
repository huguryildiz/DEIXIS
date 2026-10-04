# P7 closed-batch records

P7 measured model/provider coverage and the internal scholarly connector
contract, including admission, request accounting, query dispatch, DOI lookup
and citation chaining. This directory holds completed task prompts. The
[design](../../product/p7-connector-contract-design.md),
[onboarding procedure](../../product/connector-onboarding.md),
[coverage ledger](../../product/p7-coverage-verification.md) and
[acceptance record](../../product/p7-acceptance-record.md) remain current records.

[D196](../../decisions.md#d196--p7-g1-b5-g1-is-accepted-with-conditions-for-the-internal-search-connector-contract-p7-exit-is-not-met-until-three-named-batches-land) accepted search coverage conditionally; P7 exit
still required G1-F1, P7-F2 and P7-F3.
[D199](../../decisions.md#d199--p7-f2-and-p7-f3-pubmed-subrequests-are-counted-and-bounded-sends-are-counted-apart-from-reservations-and-the-authenticated-openai-embedding-route-is-tested) closed PubMed subrequest accounting and the
authenticated OpenAI embedding test route.
[D201](../../decisions.md#d201--p7-g1-f1-existing-lookups-and-openalex-citation-chaining-go-through-declared-connector-capabilities-with-collector-based-accounting-p7-exit-is-met)
closed lookup/chaining coverage and recorded P7 exit. Its reviewer reported
13,006 passing backend tests and two skips after fixes, plus 2,912 passing
connector tests. These are recorded historical checks, not checks rerun here.

The contract remains internal to reviewed adapters; external plugins are not
offered ([D174](../../decisions.md#d174--p7-g1-the-connector-contract-is-an-internal-versioned-interface-for-reviewed-adapters-with-a-registry-driven-conformance-suite-external-plugins-are-not-offered)). Deterministic fixtures do not establish
live provider error formats, entitlements or quota behavior. The acceptance
record retains those limits and the owner-reported live evidence separately.
