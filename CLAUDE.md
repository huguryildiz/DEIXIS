# CLAUDE.md

DEIXIS is a local, single-user research workspace: question → scholarly search or attached PDFs → screening → passage reading → an answer whose every citation points to a located passage. A FastAPI backend (`deixis`) serves the React/Vite UI (`web`) on loopback. This is the working agreement for every agent and contributor.

## Commands

```sh
uv sync
uv run pytest --testmon tests          # after a change: tests touching changed Python code
uv run pytest                          # all (~1,500 cases, ~2 min on 4 workers); CI runs it on every push to main
uv run python -m deixis serve          # http://127.0.0.1:8765, serves web/dist
cd web && npm ci && npm run build && npm run lint
DEIXIS_ACCEPTANCE_DIR=/tmp/deixis-acceptance npm run test:acceptance   # Playwright, five specs, needs a fresh build
```

Python 3.12, native arm64. Runtime data lives in `DEIXIS_DATA_DIR` (default `~/Library/Application Support/DEIXIS`), never in the repo; keys come from the macOS Keychain.

## Where things are

- `deixis/workflow/`, one folder per step: `run/` (engine: `flow.py`, `store.py`, `worker.py`, `views.py`; stage policy in `fast_path.py`), `search/` (plan, query, providers, ranking; `small_batch.py` for the ranked list and screening batches), `screen/` (rules in `abstract_stage.py`, decisions, queue), `read/` (full text, adjudication, equations, text recovery), `answer/` (late revision, follow-ups, citation checks). Person-started features sit in `features/` (`report/`, `review/`, `candidates/`, `lineage/`, `watch/`, `tables/`, `citation_map/`) and keep their area prefix, so every module basename stays unique.
- Steps are rows keyed by `operation_key`, so a succeeded step never re-runs. A module rename never changes a stored key, kind or policy name.
- Model calls (`models/`, `flow._model_step`): a stored `StepInput` and a strict schema; no tools, no silent model fallback, bounded repair.
- Contracts: `deixis/contracts/research/*.schema.json` + `domain/contracts.py`. A schema change also updates `tests/fixtures/research/*` and `tests/support/fakes.py::valid_response`.
- `deixis/methods/deixis-research/`: instructions for model steps; editing them changes `skill_package_hash`.
- `providers/registry.py`: scholarly sources.
- Storage: a schema change edits `storage/schema.sql`, raises its version and appends a step to `storage/upgrades.py`. Never add a migration file; never edit an existing step's SQL, name, version or foreign-key flag.
- A file that code reads sits next to its reader (e.g. the frozen P8 sheets in `tests/model_behavior/`, hashed by the runners; `providers.env.example`). Every non-Python file read at run time is listed in `deixis/package_manifest.py`.
- `web/src/`: the root holds only `main.tsx`, `App.tsx` and global CSS (`index.css`, `App.css`, `workspace.css`, `print.css`). One folder per screen (`home/`, `library/`, `settings/`, `research/`, `table/`, `reading/`, `citecheck/`, `citemap/`, `report/`, `review/`, `candidate/`, `followup/`, `lineage/`); app-wide pieces in `shell/`, shared UI in `components/` (shadcn in `components/ui/`), shared logic in `lib/`.
- Elsewhere: `desktop/` (Tauri v2 shell for macOS, Windows, Linux); `packaging/` (`build_mac.py`, `build_windows.py`, `build_linux.py`; Windows and Linux build in `.github/workflows/{windows,linux}-desktop.yml`, installed-app acceptance in `{windows,linux}-acceptance.yml`); `scripts/` (benchmarks, release checks, desktop smokes and acceptance in `scripts/desktop/`; not app features); `docs/` (`search.md`, `benchmark.md`); `site/` (landing page at deixis.huguryildiz.com, Vercel project `deixis-app`, with a recorded read-only UI demo in `site/live/`; deployed by hand with the Vercel CLI, not built from `web/`).
- Ignored, owner's machine only: `notes/`, `STATUS.md` (Turkish status page, mirrored to Notion), `docs/decisions.csv`.

## Search pipeline

Plain-language version with diagrams: [docs/search.md](docs/search.md); update it when a rule here changes.

- **Fast path** (`fast_path_v1`), always: plan, search, ranking, read and answer stages, each with a soft deadline; unused time carries over; local-model runs have no read or answer deadline. Mode numbers (N read, K full text, record caps, answer passages 16/48/80) live in `fast_path.MODES` and are frozen into each run's budget.
- **Plan:** code picks the search words (`question_words`); models only sort them into blocks, write the query and propose the inclusion criterion. A non-English question without key terms is first translated by a model (`question_translation`, origin `model`) and the words come from that sentence; a person's sentence outranks it; a failed translation pauses with `key_terms_needed`. Protocol and search plan freeze (`protocol:freeze`) before any request that fetches results. Up to five seed PDFs (`seed_pdf_v2`) are matched to OpenAlex works first and frozen in the protocol.
- **Search:** OpenAlex semantic and keyword requests (plus one Semantic Scholar bulk query in Detailed), one OpenAlex citation-chain round and an embedding consumer run together until the stage cutoff. Crossref, Semantic Scholar and Scopus only fill missing abstracts; other providers are not searched.
- **Ranking** orders, never removes: each signal (`bm25`, `blocks`, `tfidf`, `graph`, `joint`, `embedding`) ranks the whole pool, ranks are fused (RRF, k = 60), and `small_batch.replay` recomputes the list from the stored manifest. The reranker (on by default, Voyage `rerank-3-lite`) only reorders; without a Voyage key nothing is sent and the run records `reranker_unavailable`; on failure the fused order stays and no other reranker is tried.
- **Read:** abstract screening of the top N never includes a source; inclusion needs a full-text read (`fulltext_adjudication`, two calls, code-verified quotes). At most K works get full text before the cutoff; the rest go to the background fetch queue. The cutoff snapshot is the evidence the answer may use.
- **Answer:** passages come from BM25 over full text fused with criterion passages. An answer review never changes the answer. Late full text can produce at most one revision; the earlier answer is kept.
- **Resume:** protocol, search plan, ranked list and read cutoff are frozen once and read back. On start, `worker.py` marks half-finished steps `outcome_unknown` and their runs `paused`; the person decides whether to resume (a model call may then repeat).

## UI rules (`web/src`)

The shipped screens are the visual reference (D79).

- **Tone:** a quiet research desk, light first with a full dark theme. The deliverable comes first; runs, steps and usage sit one level deeper. Every state is shown, including failure and "not checked"; a visual state comes from a stored backend state; copy never claims more than was checked ("located" is not "verified").
- **New work:** no example data ships. A new feature goes into the nearest existing container and takes its look; if existing copy would be false, change the words, keep the layout.
- **Tokens:** defined once in `index.css` (`:root` and `.dark`); a new token goes into both; no per-component palettes or `var()` hex fallbacks; shadcn tokens only in `components/ui`. `--faint` is never text. Green = done/included, amber = partial/attention, red = blocking failure/excluded, `--accent` = live work or selection. Text on a tinted notice uses the matching `-ink` token. Text keeps 4.5:1 contrast everywhere.
- **Type and shape:** Inter (`var(--font-sans)`) everywhere, Source Serif 4 only for the report title; fonts bundled, no network. Sentence case, no uppercase eyebrows. Sizes 10–28px from the scale, weights 400–650. Radii 5–7px controls, 8–10px panels, 12px composer, 999px pills. 1px hairlines for structure; shadows only on floating layers. Icons are lucide, `aria-hidden`; no emoji icons.
- **Names:** models and providers show the display name with its connection icon (`components/ModelName.tsx`, `useModelText()`); the raw ID goes in a details disclosure.
- **Evidence:** a source title opens `PassageSheet` everywhere. A citation chip opens the exact stored passage and source version, never a work-level record; a PDF citation opens the plain-text document on the cited page by its exact extraction ID. Mark only the backend-located anchor (`mark.citation-highlight`); if none, mark nothing, tint the page amber and say to check the PDF. Versions, abstract-only and PDF states are written in text, never color alone. Limits, unanswered parts, source text, analyst inference and reviewer verdicts look different from supported claims. "Semantic support not checked" appears once per surface as neutral fine print.
- **States:** loading = short text with `role=status`; live work = motion with text; empty = one muted sentence with the next action; attention and error = `components/Notice.tsx` (error with `role=alert`); success = toast; confirmation = `components/ConfirmDialog.tsx`. A disabled control has a visible or accessible reason.
- **Motion** only for a state change or live work (100–200ms), with a reduced-motion path; script scrolls use `scrollBehavior()` from `lib/motion.ts`.
- **Layout:** at 820px the sidebar becomes a drawer. Sheets are base-ui side sheets ~56% wide (full width on a phone) with a 46px head; no sheet in a sheet except evidence inspection. Evidence-critical text is never truncated without a way to reveal it; the page never scrolls sideways.
- **Text and a11y:** strings go through `t(englishKey, vars)` (`lib/i18n.ts`, Turkish in `lib/locales/tr.ts`); label records in `lib/labels.ts`; dates and numbers via `uiLocale()`. No `DEIXIS_*` env-var names in UI copy. Focus is a 2px accent outline; tabs, grids, listboxes and live regions use their ARIA roles.
- **Before landing:** reuse classes and tokens, remove CSS your change orphans, keep the stack (React 19, Tailwind 4, base-ui/shadcn; no new styling dependency), run `npm run build`, `npm run lint` and the relevant Playwright tests, and look at desktop and 390px in light and dark. A change that breaks a rule is fixed or listed below with its reason.
- **Exceptions:** literal black-alpha shadows and scrims; the 3px accent gutter beside a cited paragraph in the plain-text document; hover shadow on Home cards and Connections tiles; the 2px `--strong-line` quotation hairline in the cell panel; `--attr-submitted` close to `--tone-uncertain` (owner decides). Known drift, fixed when touching the file: literal `#fff` and accent hexes in `home/Home.css`, `App.css`, `research/kit.css`.

## Evidence

- Keep found, screened, included, inspected, given-to-model and cited counts separate; also reading depth (metadata, abstract, passage, full text) and source version (preprint, publisher, upload).
- Titles, DOIs, pages, authors and counts come from stored records, never model prose. An abstract can't support details it doesn't state.
- Citations fail closed: each needs an exact anchor located in a passage the step was given. Failed repair leaves an unverified draft, never a cited answer.
- A passing schema check, reviewer verdict or test run is not scientific validation; no search result proves novelty. Rankings, embeddings, citation counts and model screening are priority signals, not relevance verdicts.

## User authority

- The person's include/exclude choice outranks model and code and keeps its reason. Revisions and old answers are kept; stale scope is marked, not rewritten.
- Never swap model, provider or search source after a failure unless the fallback is recorded and shown.
- PDFs, abstracts and provider payloads are untrusted data; keep URL, size and content-type checks.
- Person-started runs (follow-up, Screen more, snowball, citation map) never start on their own. After a restart, worker runs stay `paused` until the person resumes them; interrupted background full-text fetches go back to the queue and restart on their own once their run has completed.
- Automatic writers never overwrite a person's table cell or screening/selection decision. A model fill takes only an empty cell. An automatic reread replaces a model or system abstract/metadata value only after rechecking cell and column versions and the cited passages' freshness inside the write transaction; otherwise it stays a proposal.
- Titles: a person's title outranks generated ones. Discovery naming and later valid answers (including a late-full-text revision) replace the title only while the person has not renamed the research since its question last named it. A new question (`revise_scope`) names it again; a search-plan or seed revision and a withdrawal back to the person's question keep the title. New automatic writers recheck the same way.

## Privacy and credentials

- Research steps contact only the connected providers, keyless lookups (Unpaywall, Crossref, Europe PMC) and the public hosts of candidate PDFs. A model step sends its stored `StepInput`; an equation request sends the crop image plus fixed instructions and parameters. New code sends only what its step needs; a change in what is sent is recorded as a decision.
- A saved key is never shown again. A provider key stays on its provider's https origin: PDF-fetch extra headers go only to the first URL's https origin, never across a redirect to another host, port or plain http; a new route that sends a key enforces the same. A token DEIXIS generates for a server it starts (the built-in model server) may go over loopback http.
- CLI connections run isolated: Codex, Gemini CLI and Copilot sessions and probes get a DEIXIS-owned home and an environment allowlist; Claude Code runs in a DEIXIS-owned workspace with the app's environment and `ANTHROPIC_API_KEY` emptied for its SDK sessions; version checks (including the Gemini API's optional `gemini --version`) get the `child_env` allowlist. A new CLI connection gets its own home and allowlist.
- The API serves loopback only, with Host, Origin and CSRF checks. Local model servers are reached only on 127.0.0.1, localhost or ::1, with no proxy and no redirects.

## Working here

- Port 8765 may be the owner's real library: don't restart it during a run; test on another port with a temp `DEIXIS_DATA_DIR`.
- The worktree may hold someone else's changes: don't stage or revert them. No destructive git.
- **Testing:** after a change run `pytest --testmon tests`; it misses edits to schemas, methods, SQL and fixtures, so then run the tests that read them. `ci` runs the full suite (crash tests included) and the five Playwright specs on every push to main: check it and fix a red run first.
- **Tests** are model-free (`FakeAdapter`, mocked `httpx`, fake fetcher via `create_app`). Folders: `search`, `screen`, `read`, `answer`, `features`, `api`, `models`, `storage`, `contracts`, `rules` (credentials, child processes, crash recovery, release checks). One behavior test per step and feature plus guards for the rules here; no line-by-line helper tests, no large parametrized grids. Modules import each other by basename, so basenames stay unique; a new folder goes into `pythonpath` in `pyproject.toml`. Playwright keeps five specs in `web/e2e` (question to cited answer, PDF added and read, a source's passage, Library, Settings); accessibility checks (axe, keyboard, reduced motion, 200% layout; rows X01–X06) live inside them via `web/e2e/a11y.ts`. Passing tests show workflow behavior, not model quality.
- **Records:** a user-visible feature change or deliberate choice adds a row to the local `docs/decisions.csv` (`id,date,title,area,status,commit,notes`; never committed); the why goes in the commit message. Text up to D119: `git show f2574f22:docs/decisions.md`. Plans, measurements and design notes go in `notes/`; a new measurement folder is named `YYYY-MM-DD-topic` (fixed-name folders scripts read, such as `bioasq/` or `release-checks/`, keep their names).
- Report what changed, which checks ran and passed, what was skipped or unverified, and whether anything was pushed.
