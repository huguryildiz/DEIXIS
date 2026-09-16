# TODO

## Memory (deferred, 2026-09-15)

Chat-style "memory" (hidden context learned from past conversations, as in Claude/ChatGPT) is **not** planned.
It would inject context that no StepInput records, which breaks the "every cell points to its source" rule
and the model boundary that keeps instruction files out of model steps.

What it would add: not re-explaining field, language, citation style and preferred providers; continuity
across research ("you already excluded this source").

What it would break: auditability of answers, cross-research leakage of unsourced claims, a new confound
before the P4 evaluation is done.

Auditable alternatives, in order:

- [ ] Keep user preferences as explicit, editable Settings (already there); do not model them as memory.
- [ ] Cross-research continuity from the library, not the model: deterministic hints such as
      "this source was included in research X" computed from the database.
- [ ] If a model-facing note is ever wanted: a user-written, versioned, visible "research brief" field that
      enters the StepInput hash. Name it "brief", not "memory".

## Intent chips / mode tabs (deferred, 2026-09-15)

Chat-style "Ask the agent to…" intent hints and mode tabs ("Deep search / Write report / Organize"), as seen
in agent chat products, are **not** planned.

- Mode tabs: DEIXIS does one thing, a source-grounded answer. Scope (academic / attached / both) and model
  roles already cover the real choices; tabs for modes that do not exist would be empty promises.
- Intent hint: wraps the user's question in a hidden pre-instruction that no StepInput records. Same
  objection as memory above: unaudited context injection. It also assumes a chat loop; DEIXIS is
  question → run → answer.

The real need behind it is the empty-box problem (user does not know what to type). Auditable, cheap answer
if ever wanted, after the P4 evaluation:

- [ ] 2–3 clickable example questions under the question box that only fill the box; nothing is added to
      the model input beyond what the user sees and the StepInput hashes.

## Playwright PDF retrieval diagnosis (deferred, 2026-09-16)

Some sites return HTML or 403 to the PDF fetcher. Getting past bot protection with a headless browser or a
scraping service is **not** planned. It would break publisher terms and TDM licences, and systematic
downloading through the institutional VPN can get the whole university's publisher access blocked.

In the live library, 59 of 68 PDFs were downloaded automatically and 9 were attached by hand during P4.
Of the 12 stored PDF candidates:

- 5 Crossref links returned HTML instead of a PDF.
- 7 web candidates were not attempted because their titles did not match.

The P4 gap was paywalled IEEE papers with no legal open copy.

- [ ] Diagnostic run: no product code, open-access or publisher-free URLs only.
  - Pick at most 20 cases where `fetch_pdf` got HTML or 403.
  - Open them with plain Chromium through Playwright: no stealth plugin, no spoofed identity, no CAPTCHA
    solving, a few seconds between requests.
  - A bot challenge is recorded as "blocked" and skipped.
  - Classify each failure:
    - a `citation_pdf_url` meta tag the fetcher does not follow
    - a PDF link that appears only after JavaScript runs
    - a cookie wall or redirect chain
    - a real bot challenge
    - a login requirement
- [ ] Decide from the counts:
  - If `citation_pdf_url` explains most cases, add it to the fetcher instead of a browser.
  - Browser retrieval enters the product only if JavaScript-only pages are a meaningful share, and then only
    for one source the user clicks, with the D4 version check. Playwright is currently a dev/e2e dependency,
    not a runtime one.
  - If bot challenges dominate, the bot route is closed; keep the user's own browser: open link and attach,
    Zotero Connector import, or a later DEIXIS browser extension.
- [ ] Independent of the run: give the fetcher an honest identity: a contact email in `User-Agent` (now only
      `DEIXIS/0.1 (local research workspace)`) and `Accept: application/pdf`.

## Search query generation (deferred, 2026-09-16)

The `search_plan` model step writes every provider query itself; the code only checks provider syntax
(`providers/query_rules.py`, `domain/contracts.py::_check_search_plan`) and sends the rest back for repair.
The model's `concepts` vocabulary is not used to build queries, only for BM25 ordering of sources. A live plan
(k-connectivity / underwater WSN question) showed the cost: 8 queries that were pairwise combinations of the
same 4 concepts, so the same first-ranked records came back from several queries.

Elicit and Consensus skip query writing: they own an embedding index over the Semantic Scholar corpus and use
the question as the vector query, then rerank the top few hundred with an LLM. DEIXIS cannot copy that (no
own index, ~190 GB of vectors and days of embedding for 250M abstracts; OpenAlex and Semantic Scholar offer
no public vector search). Screening already plays the rerank role.

Decision for now: **do nothing** to the discovery layer. The only measurement (D13 follow-up) put the recall
limit at the 48-passage answer input, not at discovery, and no case has shown a relevant paper missing from
the search results.

Trigger: the first real research where the user says a known relevant paper did not appear. Then check where
that paper ranked in the provider results (`provider_search` payloads):

- Ranked below `results_per_query`: do **wide fetch, local rank**. Raise `results_per_query` to a few hundred,
  run the D30 title+abstract similarity (Gemini `gemini-embedding-2`, D29 provider choice) *before* screening
  and feed screening batches from the similarity order. No new model, index or contract; Scopus records are
  scored on title only. Measure before/after with `scripts/p4_eval` on the three all-provider runs.
- Not returned at all: the query is the problem. Then move query composition into code: the model keeps
  producing concept families and synonyms, the code builds each provider's `core AND (synonyms OR …)` query
  from them (one query per concept family, no duplicate term pairs), and the repair round for syntax goes away.
  Free-text model queries stay only as an optional extra.
- Cheap and independent of the trigger: a warning (not a repair) in `_check_search_plan` when two queries'
  term sets largely overlap.

Not planned: a per-field local index (OpenAlex subset embedded with a local Ollama/LM Studio model) and a
citation/recommendation snowball step. Both need a measured recall gap first.
