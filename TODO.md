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
