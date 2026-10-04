<!-- PLAN-REVIEW-ROUNDS: r1 (gpt-6.1-sol medium): düzeltmeyle hazır, 1 high + 4 medium, all folded in; r2: düzeltmeyle hazır, 2 medium (facade undeclared checks only in the undeclared section; unchanged unregistered KeyErrors moved to the main replay), folded in; r3: hazır; agreed (a) decision 7 amendment, (b) compile_queries literals stay compiler policy, (c) NAMES compatibility dict, (d) registry declarations with strict/lenient resolution and lazy imports. Code: written by gpt-6.1-sol high; reviewed by Claude Opus 5.5, r1 düzeltmeyle hazır (1 medium + 3 low, fixed), r2 hazır. -->

# Task: P7 G1 batch B3b, query rendering delegation with a compiler byte-equality gate

Worktree: `/Users/huguryildiz/Documents/GitHub/DEIXIS-g1-b3b`, detached at `e19a7f7` (origin/main with D179, B3a).
Design: `docs/product/p7-connector-contract-design.md` (accepted as D174). Read sections 2.1 (the `query_rules.py` /
`query_compiler.py` row, line 65), 4 (the `QueryRendering` row, line 191), 8 (gate 3, line 437), 9 (lines 486-518) and
10 (row B3b, line 530, and the paragraph after the table). Also read `AGENTS.md`, `CLAUDE.md`, D179, D178 and D177 in
`docs/decisions.md`, `docs/product/connector-onboarding.md` (gate 3 and "Version and unsupported rules") and
`docs/archive/p7/p7-g1-b3a-prompt.md` (decision 8 there is why this batch exists). Venv:
`PYTHONPATH=backend:. UV_CACHE_DIR=/tmp/deixis-uv-cache .venv/bin/python -m pytest ...` (`.venv` is a symlink to the
arm64 venv of the main checkout).

**No git state-changing commands** (no add, commit, stash, checkout, reset, branch, worktree). Leave every change
uncommitted. No real-model call, no provider call, no network, no DNS. Do not touch `../DEIXIS*` worktrees, `TODO.md`,
`.vscode/`, `scripts/local_index.py`, the live service on port 8765, or the live data directory.

Batch B3b only. B4 (dispatch through the facade, provenance, lookup binding, identity admission, payload
sanitization) and B5 are later batches; do not start them. Search dispatch keeps calling the registry callables, and
`workflow/` keeps calling `query_compiler` exactly as today. The decision number is **D193** (one entry).

## Why

D174 row B3b: "Extract rendering/validation delegation behind the facade while preserving compiler allocation and
outputs; keep dispatch unchanged until B4". Exit: "Compiler byte equality for native query text, retained/dropped
terms, order and budgets; compiler/rule regression across every connector and endpoint". Section 2.1 names the gap:
the rules and the compiler "include named provider branches and a fixed name table. A new registry entry alone does
not provide query translation." Section 4: "Compiler owns trimming/order and query budgets; adapters supply
rendering/validation. Initial facades must reproduce existing compiler outputs exactly." D179 kept this batch separate
because it refactors the discovery hot path and needs its own byte-equality gate.

The goal is therefore a pure refactor: every provider-specific choice about how a query is written and checked moves
out of `if provider == ...` branches into a declaration the registry entry carries; the compiler keeps its trimming
loops, term order and budgets and asks the declaration only to render one candidate, to say how many terms that
candidate wrote, and to list its issues. Outputs stay byte-identical on every input that a registered connector and
endpoint can receive.

## What is and is not in code (checked on e19a7f7)

Provider branches and the name table (paths under `backend/deixis/providers/`):

- `query_rules.py:13-15` `NAMES`, a fixed ten-entry name table; its key order (openalex, semantic_scholar, crossref,
  arxiv, pubmed, biorxiv, ...) differs from the registry order (biorxiv before pubmed) and tests iterate it
  (`tests/test_query_compiler.py:16`, `tests/test_vocabulary.py:342,368`).
- `query_rules.py:33-39` `boolean_part`: OpenAlex, bioRxiv, IEEE Xplore and CORE expose the whole query to the
  OpenAlex-style boolean checks; Scopus exposes the inside of a balanced field group; others none. An unknown provider
  returns None.
- `query_rules.py:42-70` `syntax_issues`: S2 + `endpoint == "bulk"` → `_bulk_issues`; S2/Crossref → plain-word
  issues naming the provider through `NAMES` (an unknown provider raises `KeyError` here, line 43); otherwise the
  balance check with provider-specific suffixes for IEEE and CORE, then CORE, Scopus, SerpApi and arXiv rules.
  Any endpoint other than S2's `"bulk"` (including undeclared strings) is checked as the default.
- `query_rules.py:191-202` `query_issues`: syntax issues, then OR-ambiguity and shape checks on `boolean_part`.
- `query_compiler.py:30` `PLAIN_PROVIDERS = ("semantic_scholar", "crossref")`, also imported by
  `workflow/expansion.py:181-184`.
- `query_compiler.py:69-92` `_render`: `endpoint == "bulk"` selects S2's bulk syntax **for any provider**; plain
  words for `PLAIN_PROVIDERS` (eight-word cap, at least one family word); SerpApi's first core term then an OR chain;
  arXiv `abs:` and PubMed `[Title/Abstract]` operands; Scopus `TITLE-ABS-KEY(...)` wrapper.
- `query_compiler.py:126-134` `_rendered`: plain providers count one term per block only when `endpoint is None`;
  SerpApi counts one term of the first block; everything else counts all kept terms. For S2 with an undeclared
  endpoint string this says every kept term was written while `_render` wrote plain words, so the dropped list is
  wrong on that (unreachable) input.
- `query_compiler.py:205-253` `compile_queries` (legacy and `compact_openalex_v1` strategies) names `"openalex"` for
  the core-depth query (line 231) and the compact probe (lines 241-250) and `"serpapi"` for its one-query cap (line
  239); `_compact_openalex` (line 123) checks with `query_issues("openalex", ...)`. These are strategy and budget
  choices, not rendering. `compile_queries` has no caller in `backend/` since D119; scripts and tests call it.

Allocation the compiler owns (keep exactly): `_fit` (95-108: family first, then core, from the end), `_fit_blocks`
(137-154: largest block first, last block on a tie, every block keeps one term), `MAX_QUERY_CHARS`, `MAX_TERMS`,
`CORE_TERMS`, `compile_block_queries` (157-188: block order, de-duplication, `limit`, routed endpoint and sort from
`CONNECTORS[provider].sw_query`), `_round_robin`, `compile_queries`'s seen-set, limit and SerpApi cap, `_terms`,
`quoted`, and the version strings `VERSION`, `COMPACT_VERSION`, `BLOCKS_VERSION` (stored in protocols, `flow.py:608,
720,1074,2362`, and in PRISMA-S, `workflow/prisma_s.py:79-80,333`).

Production callers (do not edit them): `workflow/flow.py:606,1043,1117,1123,2353`, `workflow/search_query.py:224`,
`workflow/candidates/terms.py:39` call `compile_block_queries`; `quoted` is imported by `flow.py`, `search_query.py`,
`suggestions.py`, `routing.py`, `expansion.py`, `vocabulary.py`; `expansion.py:181` imports `PLAIN_PROVIDERS`. No
`backend/` code outside `providers/` calls `query_rules`. Scripts import `query_rules.query_issues`, `_fit`, `_terms`,
`compile_queries` (`scripts/search_*.py`, `scripts/isolated_*.py`); their names and signatures stay.

Facade (B1): `facade.py:40` takes `display_name` from `query_rules.NAMES`; `facade.py:119-120` `query_issues` calls the
module function with any endpoint; `facade.py:122-141` `render_query` re-runs the compiler's trimming loop on private
compiler functions to recover retained occurrences and raises `RuntimeError` when it disagrees with `_fit_blocks`
(pinned by `tests/test_connector_boundary.py:363-384`). Neither refuses an endpoint the connector does not declare,
although `search` does (`facade.py:77-81`).

Existing evidence: `tests/fixtures/connectors/baseline.json` holds 33 rendering and 44 rule entries (three tiny block
sets, four texts; `tests/connector_baseline.py:26-31,274-286`), replayed by `test_connector_boundary.py:337-351`. That
is too thin to call a refactor of these branches byte-equal; this batch adds a broad freeze before touching code.
`registry.py` already carries per-connector `sw_query`, `endpoints` (`Endpoint`, 24-33) and `retry`; `Connector` has no
display name and no query declaration. `PRISMA-S` pins the SHA-256 of `registry.py` and `query_compiler.py` at import
(`prisma_s.py:69-75`); a new report will cite new digests, which is code provenance, not an output change.

## Decisions taken where the design is open (use these; never ask)

1. **Freeze first, on unchanged code.** Before editing any production file, add `tests/query_baseline.py` (capture
   script, `--write` required, mirroring `tests/connector_baseline.py`) and generate
   `tests/fixtures/connectors/query_baseline.json` from the untouched `e19a7f7` code. Record its SHA-256 and size in
   the report. Serialize with `json.dumps(..., indent=2, ensure_ascii=False)` without `sort_keys`, so the key order of
   compiled query dictionaries is part of the comparison. Exceptions are recorded as `{"raised": {"type": ...,
   "message": str(exc)}}`. Deterministic enumeration only (a seeded `random.Random` is acceptable for sampling, with the
   seed in the file). Use your own JSON conversion in `tests/query_baseline.py`; do not route values through
   `connector_baseline.json_value`, which canonicalizes them (`tests/connector_baseline.py:34-35`). Keep the file under
   4 MB. Never regenerate it after the refactor; tests read it. The capture must
   only use names that exist both before and after (`query_compiler._render`, `_rendered`, `_fit`, `_fit_blocks`,
   `_compact_openalex`, `_terms`, `quoted`, `compile_queries`, `compile_block_queries`, `PLAIN_PROVIDERS`;
   `query_rules.syntax_issues`, `boolean_part`, `query_issues`, `NAMES`; the facade's `render_query`, `query_issues`
   and descriptor `display_name`), so the reviewer can regenerate it on a clean `e19a7f7` copy and compare bytes.
   Required coverage, every class present and counted in the report:
   - **Terms**: single words; multiword phrases; hyphenated; alphanumeric (`5G`); non-ASCII (`naïve`, `μ-wave`);
     terms holding `*`, `~`, `|`, `+`, a leading `-`, a colon (`title:x`), an apostrophe; boolean words as terms and
     inside phrases (`AND`, `or`, `rock and roll`); stop-word-heavy phrases (`of the art`); medium (60-120 chars) and
     over-limit (>300 chars) terms; case-variant and exact duplicates; for `_terms`, synonyms holding quotes,
     parentheses, brackets, and empty or whitespace-only synonyms.
   - **Domain A (declared)**: every registered provider × (None and every endpoint it declares in `registry.py`):
     `_render` and `_rendered` on core/family pairs (each 0-8 terms where the function accepts it, core never empty),
     `_fit_blocks` on one- and two-block groups (sizes 1-8, unbalanced, ties, duplicates), the facade's `render_query`
     on the same groups (`native_query`, `retained`, `dropped`, `rule_revision`, or None); `_fit` for every registered
     provider (it takes no endpoint).
   - **Rules**: `syntax_issues`, `boolean_part`, `query_issues` (and the facade's `query_issues` for declared pairs
     only: None and declared endpoints) over a text corpus that
     holds every rendered output above plus hand-written texts reaching each rule branch (empty string; unbalanced
     quote, open and close parenthesis; field prefix; quoted phrase without AND; Scopus group, no group, unbalanced
     inner group; SerpApi parentheses, AND, NOT; arXiv NOT, adjacency, missing prefix, six operators; OpenAlex OR
     ambiguity, six operators, three required parts, three unquoted words; each bulk operator; nine plain words), for
     every registered provider × (None, every declared endpoint, `"bulk"`, `"nope"`), and for an unknown provider ID
     `"unregistered"` with None.
   - **Undeclared inputs (section `undeclared`, kept apart from the rest)**: `_render`, `_rendered`, `_fit_blocks`,
     the facade's `render_query` and `query_issues`, for every registered provider × (`"bulk"` where not declared,
     `"nope"`), and `_render`, `_rendered` for `"unregistered"`; record today's results. Every facade check with an
     undeclared endpoint lives only here. These are the only entries whose new behavior differs (decision 7).
     `_fit("unregistered", ...)` and `_fit_blocks("unregistered", ...)` already raise `KeyError` today (through
     `NAMES`); they belong to the main replay as unchanged refusals, with type and message compared.
   - **Boundaries**: rendered lengths of exactly 299, 300 and 301 characters for every pair; plain-word candidates of
     7, 8 and 9 words; 4, 5 and 6 boolean operators (OpenAlex-style and arXiv); texts that violate two or more rules at
     once, so the order of issues is pinned; an empty block inside `_fit_blocks` groups; three-block groups for
     `_fit_blocks` and the facade's `render_query` (the contract does not restrict the count, `contract.py:172`, while
     `query_compiler.py:148` renders only the first two blocks). Characterize all of these as they are; do not correct
     any of them.
   - **Compilers**: `compile_queries` over plans with a core only; families of every role; `adjacent_field` alone and
     beside other roles; a core with no usable synonym; family terms repeating core terms; provider lists in registry
     order, reversed, with duplicates, as a subset, holding Crossref (dropped as non-searchable), and SerpApi with
     several families; `limit` 0, 1, 2, 5, 100; `core_depth` 0 and 50 with and without OpenAlex; both strategies; an
     unknown strategy (its `ValueError`). `compile_block_queries` over vocabularies with setting, task and outcome
     terms, `in_query` root and phrase, dropped terms, duplicate forms, no terms, task only; provider lists as above;
     `limit` 0, 1, 3, 100; `routed` true and false. `_compact_openalex` on its pair corpus; `_terms`; `quoted`.
   The report gives, per function and per provider/endpoint, the count of successful outputs and the count of
   recorded exceptions, so a corpus that mostly raises cannot pass as broad.
2. **Declarations live on the registry entry.** `registry.Connector` gains `display_name: str | None = None` and
   `query_syntax: <declaration> | None = None`; `registry.Endpoint` gains `query_syntax: <declaration> | None = None`.
   The ten registered connectors and S2's `bulk` endpoint declare them explicitly; display names equal today's `NAMES`
   values. A declaration is a pure, frozen object (no I/O, no registry import) defined next to the rule primitives in
   `query_rules.py`, with exactly three operations the compiler and facade use: render one candidate from kept core
   and family terms; count the leading terms of each kept block that the candidate wrote; list the issues of a query
   text (syntax, then the OpenAlex-style boolean checks on its boolean part, in today's order). Parameterize a small
   number of declaration kinds (plain words; S2 bulk; boolean with operand, wrapper, unbalanced-message suffix and
   extra rules; arXiv; SerpApi; Scopus; CORE) rather than one class per provider; how you factor them is your
   choice, but every provider-specific literal (operand, wrapper, message suffix, message text) is a parameter set in
   `registry.py` or a constant of a kind. Every issue message stays byte-identical. Only the messages that today read
   `NAMES` (the plain-word kind, `query_rules.py:43,49,51`) take the name from the connector's `display_name`; every
   other message keeps its exact current text as a declaration parameter or kind constant, never derived from
   `display_name` (SerpApi's message says "Google Scholar", `query_rules.py:67`, while its display name is "SerpApi").
   `registry.py` remains the only providers file that names provider IDs in this path.
3. **One resolver, two strictness levels.** Add one registry function that resolves `(provider_id, endpoint)` to the
   declaration. Strict resolution (compiler rendering, facade): None → the connector's declaration; a declared
   endpoint → that endpoint's declaration; an undeclared endpoint → `ContractViolation` naming the endpoint; a
   connector or declared endpoint with no declaration → `ContractViolation` naming the connector and endpoint; an
   unknown provider → `KeyError` (as `CONNECTORS[...]`). Lenient resolution (only the module-level
   `query_rules.syntax_issues`, `boolean_part`, `query_issues`): an undeclared endpoint string resolves to the
   connector's default declaration, which reproduces today's results for every such input; an unknown provider keeps
   today's results (`KeyError` for `syntax_issues` and `query_issues`, None for `boolean_part`). The module-level rule
   functions keep their names, signatures and outputs for every input in the freeze. Because `registry.py` will import
   `query_rules.py` for the declaration kinds, `query_rules.py` must not import `registry` at module level: the
   provider-keyed wrappers import it lazily inside the function body.
4. **The compiler keeps allocation and asks the declaration.** `_render(provider, core, family, endpoint=None)` and
   `_rendered(provider, kept, endpoint=None)` keep their signatures and delegate to the strictly resolved
   declaration; `_fit` and `_fit_blocks` keep their loops, order, tie-break and limits unchanged and call
   `query_issues` through the same declaration. Add one compiler function that returns the fitted text and the
   per-block written counts; `_fit_blocks` becomes a wrapper returning today's `(text, dropped)` tuple, and the facade
   uses the counts. `PLAIN_PROVIDERS` stays exported with the value `("semantic_scholar", "crossref")`, derived from
   the registry (connectors whose default declaration is the plain-word kind, in registry order), not a literal.
   `compile_queries`, `_compact_openalex` and `_round_robin` are unchanged apart from going through the delegated
   `_fit`/`query_issues`; their OpenAlex/SerpApi strategy and budget literals stay, as named compiler policy (the
   design assigns budgets and order to the compiler; moving them would add descriptor fields for a path with no
   backend caller). Do not change any version string or `QUERY_RULES_REVISION`.
5. **The facade delegates; no second loop.** `CompatibilityConnector.render_query` and `query_issues` resolve the
   endpoint against the descriptor first (undeclared endpoint → `ContractViolation`, as `search` does), then call the
   compiler function of decision 4 and the declaration. Delete the facade's copy of the trimming loop and its
   `RuntimeError` cross-check: with one allocation function there is nothing to cross-check. Replace
   `test_rendering_mismatch_raises_even_with_optimized_python` (`test_connector_boundary.py:363-384`) with a test that
   monkeypatches the new compiler function and shows both `compile_block_queries` and `facade.render_query` change
   (one source). `descriptor_for` takes `display_name` from `connector.display_name`, falling back to `provider_id`
   when it is None (only test-built connectors lack one). Keep `from deixis.providers import ... query_rules` in
   `facade.py`; existing tests read `facade.query_rules.NAMES`.
6. **`NAMES` becomes a compatibility export.** Keep `query_rules.NAMES` as an ordinary mutable `dict` (existing tests
   `monkeypatch.setitem` it, `tests/test_connector_boundary.py:162,309`) whose initial keys, values and insertion order
   are today's. No rule, compiler or facade code reads it. A test asserts `list(NAMES.items())` equals today's ten
   ordered pairs and that each value equals the connector's `display_name`; a new connector is not required to appear
   in it.
7. **Named output difference, bounded amendment.** The only intended output differences are refusals on inputs no
   production caller produces: the compiler's `_render`, `_rendered`, `_fit_blocks` and the new compiler function
   raise `ContractViolation` for an endpoint the connector does not declare (today `_render` writes bulk syntax for
   any provider given `"bulk"`, and `_rendered` miscounts plain providers given any endpoint string), `KeyError` for an
   unregistered provider (today `_render` writes the default boolean form), and the facade's `render_query` and
   `query_issues` refuse undeclared endpoints. `compile_block_queries` takes endpoints only from registry `sw_query`
   (add a registry test that every `sw_query` endpoint is declared), so no compiled query changes. These are
   intentional refusal changes, exempted by a bounded amendment rather than called "no change". Amend "Version and
   unsupported rules" in `../../product/connector-onboarding.md` and the facade module docstring: *refusing, before rendering or
   checking, an endpoint the connector does not declare, or a provider the registry does not hold, is an intentional
   refusal change exempted from a `QUERY_RULES_REVISION` bump, provided every registered provider × (None, declared
   endpoint) renders, counts and validates byte-identically, and the module-level rule functions stay byte-identical
   for every input; any other change to a rendered query or an issue list still needs the bump.* gpt-6.1-sol medium
   agreed to this amendment in plan review round 1. The `undeclared` section of the freeze keeps the old values as the
   record of what changed; a separate refusal test (below) asserts the new behavior for each of its entries. If you
   find any other difference, stop and report; do not widen the amendment.
8. **No adapter behavior change.** `contract.py`, every provider module, `common.py`, `lookup.py`, `pacing.py`,
   `workflow/*` and search dispatch are unchanged. `adapter_revision`, `CONTRACT_ID`, `QUERY_RULES_REVISION` and the
   compiler version strings stay. `tests/fixtures/connectors/baseline.json` stays byte-identical: run
   `connector_baseline.capture()` into a scratch file outside the repo before and after the edits and compare bytes
   with the checked-in file (do not use `--write`). If either comparison differs, stop and report.

## Tests

New module `tests/test_query_delegation.py` with its own autouse fixture blocking `socket.socket.connect`,
`socket.getaddrinfo` and HTTPX's real transports, as `tests/test_connector_facade.py` does.

- **Freeze replay.** Every entry of `query_baseline.json` outside the `undeclared` section replayed on the current
  code: byte-equal (compare the re-serialized JSON value of each result, including key order and exception type and
  message) for domain A, the boundaries, the rules and both compilers. This test must pass on old and new code alike.
  Parametrize by function and provider/endpoint so
  the report can count per pair. A coverage test derived from `registry.CONNECTORS` requires entries for every
  registered provider × (None ∪ declared endpoints) for `_render`, `_rendered`, `_fit_blocks`, `render_query`, the
  rule functions and `compile_block_queries`; registering a synthetic connector without freeze entries fails it by
  name.
- **Declarations complete.** Every registered connector has a non-empty `display_name` and a declaration; every
  declared endpoint has one; every `sw_query` endpoint is declared; `NAMES` matches as in decision 6;
  `PLAIN_PROVIDERS == ("semantic_scholar", "crossref")`.
- **No provider branches.** Using `provider_id_literals` from `test_connector_boundary.py`: `query_rules.py` has none
  outside the `NAMES` literal; `query_compiler.py` has none outside `compile_queries` and `_compact_openalex`
  (assert the exact allowed set of `(function, literal)` pairs); `facade.py` stays at none.
- **A new registry entry gets query translation.** A synthetic connector registered only in `CONNECTORS` (monkeypatch;
  not in `NAMES`), with a display name and a declaration built from existing kinds and a declared extra endpoint,
  compiles through `compile_block_queries` (routed and not), passes `query_issues`, and renders through the facade,
  with no edit to rules or compiler; its plain-kind messages carry its own display name. A searchable synthetic
  connector without a declaration makes `compile_block_queries` raise `ContractViolation` naming it (fail closed,
  never a silent default syntax), and so does a declared endpoint without one.
- **Refusals** of decision 7: one case per entry of the `undeclared` section, asserting the exact new exception
  type (`ContractViolation` for an undeclared endpoint, `KeyError` for `"unregistered"`) and that the message names
  the endpoint or provider. Every entry of that section recorded a non-refusal result on old code, so each of these
  cases fails there; if capture shows an `undeclared` entry that already raised the same exception type, move it to
  the main replay instead.
- Tests reach new symbols (the resolver, declaration kinds, the new compiler function, `display_name`) inside test
  bodies or fixtures, never at module import, so old code yields named test failures, not one collection error.
- **Import order.** In a fresh interpreter per module (subprocess, as the replaced boundary test did), importing each
  of `query_rules`, `query_compiler`, `registry`, `facade` first succeeds, and then a module-level `query_issues`, a
  `compile_block_queries` call and a facade `render_query` each resolve a declaration.
- Keep every other existing test unchanged and passing, apart from the boundary test replaced in decision 5.

## Evidence that the tests bite

On a temporary copy of `e19a7f7` (not this tree) with only the new test module, `tests/query_baseline.py` and the
freeze copied in, run `tests/test_query_delegation.py`: the declaration, no-branch, synthetic-connector and refusal
tests must fail; the freeze replay passes there because it characterizes unchanged behavior (expected, not a gap).
Then, each on a temporary copy of the B3b tree: (a) change PubMed's operand suffix; (b) give S2's `bulk` endpoint the
plain-word declaration; (c) make SerpApi's written count return every kept term; (d) break the `_fit_blocks` tie toward
the first block; (e) let strict resolution fall back to the default for an undeclared endpoint; (f) let a connector
without a declaration fall back to the boolean kind; (g) put a provider-ID literal back into `query_rules.py`. Each must
fail a named test. Leave this tree clean.

## Files

- Allowed: `backend/deixis/providers/query_rules.py`, `backend/deixis/providers/query_compiler.py`,
  `backend/deixis/providers/registry.py` (the new fields, declarations and resolver only; no change to any existing
  field value, order or policy helper), `backend/deixis/providers/facade.py`; new `tests/test_query_delegation.py`, new
  `tests/query_baseline.py`, new `tests/fixtures/connectors/query_baseline.json`; `tests/test_connector_boundary.py`
  (decision 5's replaced test only); `docs/product/connector-onboarding.md` (intro sentence, gate 3 admission surfaces
  with new file:line, the decision 7 amendment, a ledger row for B3b); `docs/decisions.md` (D193 at the top only);
  `STATUS.md` (one line under "Şu an çalışanlar").
- Forbidden: `providers/contract.py`, every provider module, `common.py`, `lookup.py`, `pacing.py`, `zotero.py`,
  `workflow/*`, `api/*`, `storage/*` and migrations (none expected), `documents/*`, `models/*`, `domain/*`,
  `contracts/research/*`, `methods/*`, `apps/web/*`, `scripts/*`, `tests/fixtures/connectors/baseline.json`,
  conformance fixtures, `tests/connector_baseline.py`, and every other existing test. Parallel worktrees: P8 B3
  (`../DEIXIS-p8b3`, `apps/web`, maybe `workflow/views.py`) and re-extraction R2b (`../DEIXIS-reextract-r2b`,
  `documents/*`, `workflow/store.py`, file writers). If B3b seems to need a forbidden file, stop and report.

## Run and records

- Focused: `tests/test_query_delegation.py`, `tests/test_query_compiler.py`, `tests/test_s2_bulk.py`,
  `tests/test_vocabulary.py`, `tests/test_vocabulary_flow.py`, `tests/test_provider_records.py`,
  `tests/test_contracts.py`, `tests/test_candidate_status.py`, `tests/test_expansion.py`, `tests/test_search_query.py`,
  `tests/test_protocol_approval.py`, `tests/test_prisma_s.py`, `tests/test_term_suggestions.py`,
  `tests/test_isolated_feature_query_arm.py`, `tests/test_isolated_hybrid_search.py`,
  `tests/test_isolated_query_branches.py`, `tests/test_connector_boundary.py`, `tests/test_connector_contract.py`,
  `tests/test_connector_facade.py`, `tests/test_providers.py`. Then the full default suite; your sandbox cannot bind
  sockets or list processes, so report failure names and compare them with the sandbox-only names recorded for D179
  (`/tmp/g1b3a-full.log`, if present); the reviewer runs the full suite outside the sandbox. Run `git diff --check`.
- Write D193 at the top of `docs/decisions.md` (`## D193 — P7 G1 B3b: ...`; Status with writer gpt-6.1-sol high and
  reviewer pending; Date 2026-10-03; Context; Decision; Evidence; Limits). Decision separates the refactor (with its
  byte-equality evidence) from the named refusals of decision 7 and the amendment, says who agreed to the amendment,
  and states that `compile_queries`' OpenAlex/SerpApi strategy literals remain compiler policy. Evidence gives freeze
  size, SHA-256, entry counts per function and per provider/endpoint, and the `baseline.json` byte comparison. Limits:
  synthetic inputs establish byte equality on the enumerated corpus, not on every possible vocabulary; no live call;
  search dispatch still uses the registry callables; PRISMA-S cites new file digests for `registry.py` and
  `query_compiler.py`; B4's named changes and `PENDING_B4` cases remain; G1 stays open. One Turkish line in
  `STATUS.md`.
- Report to `/tmp/g1b3b-impl-report.md`: files changed, each decision's implementation with file:line, the freeze
  SHA-256 taken before the first production edit, test counts per group, the baseline byte comparisons, exact commands
  with counts and times, the bite evidence, anything you could not do or measure. Do not invent.
