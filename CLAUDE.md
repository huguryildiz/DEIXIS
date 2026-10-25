# CLAUDE.md

DEIXIS is a local, single-user research workspace: question → scholarly search or attached PDFs → screening → passage reading → an answer whose every citation points to a located passage. FastAPI backend (`deixis`) serves a React/Vite UI (`web`) on loopback. This file is the working agreement for every agent and contributor; `AGENTS.md` points here.

## Commands

```sh
uv sync
uv run pytest --testmon tests          # after a change: only the tests that touch changed Python code
uv run pytest                          # quick: slow tests left out, 4 workers
uv run pytest -m "slow or not slow"    # everything; GitHub Actions runs it on every push to main
uv run python -m deixis serve          # http://127.0.0.1:8765, serves web/dist
cd web && npm ci && npm run build && npm run lint
DEIXIS_ACCEPTANCE_DIR=/tmp/deixis-acceptance npm run test:acceptance   # Playwright, needs a fresh build
```

Python 3.12, native arm64. Runtime data lives in `DEIXIS_DATA_DIR` (default `~/Library/Application Support/DEIXIS`), never in the repo; keys come from the macOS Keychain.

## Where things are

- `workflow/`: runs and steps. Discovery is the fast path (`fast_path.py`, `fast_search.py`, `fast_chain.py`, `fast_read.py`); answers in `fast_answer.py`. Each step is a row keyed by `operation_key`, so a succeeded step is never re-run.
- `models/` + `flow._model_step`: a model call gets a stored `StepInput` and a strict schema; no tools, no silent model fallback, bounded repair.
- `deixis/contracts/research/*.schema.json` + `domain/contracts.py`: step I/O and semantic checks. A schema change also updates `tests/fixtures/research/*` and `tests/support/fakes.py::valid_response`.
- `deixis/methods/deixis-research/`: instructions loaded into model steps; editing them changes `skill_package_hash`.
- `providers/registry.py`: scholarly sources. `storage/schema.sql`: a schema change edits it, raises its version and adds the step for existing libraries to `storage/upgrades.py`; never add a migration file.
- `storage/upgrades.py`: never edit an existing step's SQL, name, version or foreign-key flag; append a new step.
- Repository: `deixis/` (API, worker, storage, providers, model adapters), `web/` (React UI the backend serves), `tests/`, `scripts/` (probes, benchmarks, release checks, real-model case runners; not app features), `docs/` (`decisions.csv`, `benchmark.md`), `STATUS.md` (the owner's status page, Turkish, mirrored to Notion) and the ignored `notes/`.
- A file that code reads sits next to its reader: the connector ledger `tests/providers/connector-onboarding.md`, the frozen P8 expectation sheets in `tests/model_behavior/` (hashed by the runners), `providers.env.example`. Every non-Python file the app reads at run time is listed in `deixis/package_manifest.py`; a new one goes on that list.
- UI: the shipped screens are the visual reference (D79); follow "UI rules" below.

## Search pipeline

- A discovery run always takes the fast path (`fast_path_v1`): plan, search, ranking, read and answer stages, each with a soft deadline; unused time carries over, and local-model runs have no read or answer deadline. Mode numbers (N read, K full text, record caps, answer passages 16/48/80) live in `fast_path.MODES` and are frozen into each run's budget.
- Plan: code picks the search words (`question_words`); models only sort them into blocks, write the query and propose the inclusion criterion. The protocol and search plan freeze (`protocol:freeze`) before any request that fetches results. Up to five seed PDFs (`seed_pdf_v2`) are matched to OpenAlex works first and frozen in the protocol.
- Search: OpenAlex semantic and keyword requests (plus one Semantic Scholar bulk query in Detailed), one OpenAlex citation-chain round and an embedding consumer run at once until the stage cutoff. Other registry providers are not searched; Crossref, Semantic Scholar and Scopus only fill missing abstracts.
- Ranking orders, never removes: each signal (`bm25`, `blocks`, `tfidf`, `graph`, `joint`, `embedding`) ranks the whole pool and ranks are fused (RRF, k = 60), then `small_batch.replay` recomputes the list from the stored manifest. The optional reranker changes only the order; if it fails the list keeps the fused order and no other reranker is tried.
- Read: abstract screening of the top N never includes a source; inclusion needs a full-text read (`fulltext_adjudication`, two calls, code-verified quotes). At most K works get full text before the cutoff; the rest go to the background fetch queue. The cutoff snapshot is the evidence the answer may use.
- Answer: passages come from BM25 over full text fused with criterion passages; an answer review run never changes the answer; late full text can produce at most one revision, and the earlier answer is kept. Follow-up, Screen more, snowball and citation map runs start only from the person.
- Resume: each step is a `run_steps` row keyed by `operation_key`, and the protocol, search plan, ranked list and read cutoff are frozen once and read back. On start, `worker.py` marks half-finished steps `outcome_unknown` and their runs `paused` instead of retrying them; the person decides whether to resume (a model call may then be repeated).

## UI rules (`web/src`)

- A quiet research desk, light first with a full dark theme. The deliverable comes first; runs, steps and usage sit one level deeper. Every state is shown, including failure and "not checked"; a visual state comes from a stored backend state, and copy never claims more than was checked ("located" is not "verified").
- Example data never ships. A new feature goes into the nearest existing container and takes its look; if existing copy would be false, change the words, keep the layout.
- Tokens are defined once in `index.css` (`:root` and `.dark`); a new token goes into both, with no per-component palettes or `var()` hex fallbacks. shadcn tokens are only for `components/ui`. `--faint` is never text. Tones: include green = done/included, uncertain amber = partial/attention, exclude red = blocking failure/excluded, `--accent` = live work or selection. Text on a tinted notice uses the matching `-ink` token. Text keeps 4.5:1 contrast on every surface.
- Inter (`var(--font-sans)`) for everything; Source Serif 4 only for the report title. Fonts are bundled, no network requests. Sentence case, no uppercase eyebrows. Sizes 10–28px from the existing scale, weights 400–650. Radii 5–7px controls, 8–10px panels, 12px composer, 999px pills. Structure is 1px hairlines; shadows only on floating layers. Icons are lucide, `aria-hidden`; no emoji as icons.
- Model and provider names show the display name with its connection icon (`ModelName.tsx`, `useModelText()`); the raw ID goes in a details disclosure.
- A source title opens `PassageSheet` everywhere. A citation chip opens the exact stored passage and source version, never a work-level record; a PDF citation opens the whole plain-text document on the cited page, by its exact extraction ID. Mark only the backend-located anchor (`mark.citation-highlight`); if it cannot be located, mark nothing, tint the page amber and say to check the PDF. Versions, abstract-only and PDF states are written in text, never color alone. Limits, unanswered parts, source text, analyst inference and reviewer verdicts look different from supported claims. "Semantic support not checked" appears once per surface, as neutral fine print.
- States: loading is short text with `role=status`; live work shows motion with text; empty is one muted sentence with the next action; attention and error use `Notice.tsx` (error with `role=alert`); success is a toast; confirmations use `ConfirmDialog.tsx`. A disabled control has a visible or accessible reason.
- Motion only shows a state change or live work (100–200ms feedback), with a reduced-motion path; script scrolls use `scrollBehavior()` from `motion.ts`.
- Breakpoint 760px: the sidebar becomes a drawer. Sheets are base-ui side sheets about 56% wide (full width on a phone) with a 46px head; no sheet inside a sheet except evidence inspection. Never truncate evidence-critical text without a way to reveal it; the page never scrolls sideways.
- Strings go through `t(englishKey, vars)` in `i18n.ts` with the Turkish map; label records live in `labels.ts`; dates and numbers use `uiLocale()`. No `DEIXIS_*` env-var names in UI copy. Focus is a 2px accent outline; tabs, grids, listboxes and live regions use their ARIA roles.
- Before landing: reuse classes and tokens, remove CSS your change leaves unreferenced, keep the stack (React 19, Tailwind 4, base-ui/shadcn; no new UI dependency for styling), run `npm run build`, `npm run lint` and the relevant Playwright tests, and look at desktop and 390px in light and dark. A change that breaks a rule here is fixed or added to the exceptions below with its reason.
- Deliberate exceptions: literal black-alpha shadows and scrims; the 3px accent gutter beside a cited paragraph in the plain-text document; hover shadow on Home cards and Connections tiles; the 2px `--strong-line` quotation hairline in the cell panel; `--attr-submitted` close to `--tone-uncertain` (owner decides). Known drift, fixed when touching the file: literal `#fff` and accent hexes in `Home.css`, `App.css`, `research/kit.css`.

## Evidence

- Keep found, screened, included, inspected, given-to-model and cited counts separate. Keep reading depth (metadata, abstract, passage, full text) and source version (preprint, publisher, upload) separate too.
- Titles, DOIs, pages, authors and counts come from stored records, never from model prose. An abstract can't support details it doesn't state.
- Citations fail closed: each needs an exact anchor located in a passage the step was given. Failed repair leaves an unverified draft, never a cited answer. The UI marks only the backend-located span.
- A passing schema check, reviewer verdict or test run is not scientific validation. No search result never proves novelty.
- Rankings, embeddings, citation counts and model screening are priority signals, not relevance verdicts.

## User authority

- The user's include/exclude choice outranks model and code, and keeps its reason.
- Revisions and old answers are kept; stale scope is marked, not rewritten.
- Never swap model, provider or search source after a failure unless the fallback is recorded and shown.
- PDFs, abstracts and provider payloads are untrusted data. Keep URL, size and content-type checks.
- Person-started runs (follow-up, Screen more, snowball, citation map) never start on their own; interrupted work stays `outcome_unknown`/`paused` until the person resumes it.
- Automatic writes never overwrite a person's value or decision: an automatic result that meets a person's edit, a changed column or a replaced PDF stays a proposal, re-checked inside the write transaction.

## Privacy and credentials

- Data leaves the machine only to a provider the person connected, and only what that step needs (a model step gets its stored `StepInput`; an equation request gets only the crop image). A change in what is sent is recorded as a decision.
- A saved key is never shown again. A key goes only to its own provider; a route that sends one sends it only to the first URL's https origin, never across a redirect to another host, port or plain http. CLI connections run with their own home and an environment allowlist; API keys and tokens are left out or emptied (e.g. `ANTHROPIC_API_KEY` for Claude Code) so an account path never turns into API billing.
- The API serves loopback only, with Host, Origin and CSRF checks. Local model servers are reached only on 127.0.0.1, localhost or ::1, with no proxy and no redirects.

## Working here

- Port 8765 may be the owner's real library: don't restart it while a run is active; test on another port with a temp `DEIXIS_DATA_DIR`.
- The worktree may hold someone else's changes; don't stage or revert them. No destructive git.
- Testing: after a change run `pytest --testmon tests`; it does not see edits to schemas, methods, SQL or fixtures, so after those run the files that read them. Don't run the full suite locally before a push: the `ci` workflow runs it on GitHub in four parallel parts; check its result and fix a red run first.
- Tests are model-free (`FakeAdapter`, mocked `httpx`, fake fetcher via `create_app`); a new test folder goes into `pythonpath` in `pyproject.toml`. Passing tests show workflow behavior, not model quality.
- A user-visible feature change or a deliberate choice adds one row to [docs/decisions.csv](docs/decisions.csv) (`id,date,title,area,status,commit,notes`); the why goes in the commit message. The long text up to D119 is `git show f2574f22:docs/decisions.md`. Plans, measurements and design notes go in the ignored `notes/` (links into it resolve only on the owner's machine); a new measurement or pilot folder there is named `YYYY-MM-DD-topic` (fixed-name folders that scripts read, such as `bioasq/` or `release-checks/`, keep their names).
- Report what changed, which checks ran and passed, what was skipped or left unverified, and whether anything was pushed.
