<div align="center">

<img src="apps/web/public/deixis-icon.svg" alt="DEIXIS source mark" width="176">

<h1>DEIXIS</h1>

<h3>Every cell points to its source.</h3>

<p>A local research workspace for scientific literature, evidence tables, and answers traceable to source passages.</p>

<p>
  <img alt="Python 3.12" src="https://img.shields.io/badge/Python-3.12-3776ab">
  <a href="LICENSE"><img alt="License: AGPL-3.0-or-later" src="https://img.shields.io/badge/license-AGPL--3.0--or--later-3b5b9a"></a>
  <img alt="Status: local development" src="https://img.shields.io/badge/status-local%20development-68737d">
</p>

<p><a href="#quickstart">Quickstart</a> · <a href="#how-it-works">How it works</a> · <a href="#architecture">Architecture</a> · <a href="#commands">Commands</a> · <a href="#scope-and-limits">Scope and limits</a></p>

</div>

---

## What it does

You ask a research question. DEIXIS searches the scholarly literature, reads abstracts and full texts, and writes an answer in which every claim links to the passage it came from. You can open that passage, see the PDF page, and check whether the source says what the answer claims.

Everything runs on your computer. The app is a Python backend with a React interface on `127.0.0.1`. Researches, sources, answers and evidence tables are stored in a local SQLite database; PDFs and provider responses are separate files next to it. Searches and model calls still go out to the providers you connect.

DEIXIS helps you read the literature. It does not decide whether a result is true or new. Code checks that each citation points to a real passage in a source the answer was allowed to use; it does not check that the passage supports the claim. That judgement stays with you.

## How it works

1. **Ask.** Type a question, pick a depth (Quick, Standard or Detailed) and a model connection. You can attach PDFs or import a Zotero collection: up to five of them guide the search, the rest stay attached. You can also ask about attached PDFs alone.
2. **Plan.** Code takes search words from the question, the model sorts them and writes the query, and the plan is frozen before any search result comes back. A question whose words come out empty or too broad stops here with a message; rewrite it and try again.
3. **Search.** OpenAlex is searched by meaning and by keyword, and one round of OpenAlex citation links runs alongside. Detailed adds one Semantic Scholar query. The results are ranked by similarity to the question and the list is frozen.
4. **Read.** Within the time budget, the model screens abstracts from the frozen list of up to 25, 50 or 100 works (missing abstracts are fetched from Semantic Scholar and Crossref, and from Scopus when you have access). Abstract screening alone never includes a source. The model then inspects selected PDF passages from up to 10, 20 or 40 works; this is not a reading of every page. The remaining PDFs keep downloading in the background.
5. **Answer.** For a question that asks for an answer, DEIXIS writes it from the evidence it holds when reading stops. If a reviewer model is set, a separate step checks the claims against their cited passages and records its finding without changing the answer. If full text arrives later, one revised answer may follow; the earlier one is kept.
6. **Decide.** You can include or exclude any source yourself, and your decision overrides the model's screening. Earlier answers and table cell revisions are kept, and results built on an older question or selection are marked as stale.

Quick, Standard and Detailed aim at about 3, 5 and 10 minutes. With a model running on your own computer (Ollama, LM Studio), the read and answer stages have no time limit.

Beyond the answer, you can build evidence tables with quoted values and revision history, and write reports and export them to LaTeX. Other tools draw a citation map from OpenAlex reference lists, trace development lines between sources and search against a claim you saved as a candidate. The library exports to BibTeX or RIS.

## How PDFs are found

DEIXIS only downloads open copies on its own. For each work it tries these routes in order and stops at the first PDF that passes the checks below:

1. **The search record's own link.** The open PDF link OpenAlex, Crossref or arXiv gave with the record, used only when it is for the same version of the work (published, accepted or preprint).
2. **Another version already in the research.** If an arXiv preprint or another version of the same work is in the source list and has a file, that one is used.
3. **A lookup by DOI.** Unpaywall, then OpenAlex's list of locations, then Crossref's links, then CORE (with a CORE key). Every answer is stored, and the first candidate whose DOI and version match is downloaded.
4. **Europe PMC.** For an open-access article with a PMCID, the full-text XML is rendered to a PDF.
5. **A verified copy of another version.** If the published version has no open copy, an accepted manuscript or preprint is attached to its own version row and labelled as such, never as the published article.

What these routes do not find goes on the waiting list. From there you can:

- upload the PDF, or attach it from your Zotero library (matched by DOI or title)
- press **Find PDF**, which adds a Google Scholar search through SerpApi (needs a key) and accepts only results whose title matches
- confirm a candidate the code was not sure about; DEIXIS never attaches one by itself
- open the work through your institution: with an institutional proxy set in Settings, the waiting list shows proxy links that you open in your own browser. DEIXIS does not download through the proxy.

PDFs not read before the time budget runs out keep downloading in the background, a few at a time.

**Checks on every download.** A file counts as a PDF only if its first bytes say so, whatever the server's content type. The limits are 30 MB, two minutes, five redirects and public addresses only, with one request at a time per host. After the download, the first page is compared with the work's DOI and title. A file that matches neither is kept but marked unconfirmed and is not read. Files you upload or confirm skip this comparison.

arXiv papers can also take their equations from the authors' LaTeX source. That source only supplies equations; the text is still read from the PDF.

## Sources and models

**Scholarly sources.** OpenAlex, Semantic Scholar, Crossref, arXiv, bioRxiv (through OpenAlex), PubMed, IEEE Xplore, Scopus, CORE and SerpApi have connectors. The research search itself only queries OpenAlex and Semantic Scholar; Crossref and Scopus fill in abstracts. The other connectors can be configured in Settings but the search does not call them. Some need an API key or an institutional entitlement.

**Model connections.** Codex (ChatGPT account), Claude Code, GitHub Copilot CLI and Gemini CLI run through their own sign-in. Gemini, DeepSeek, Anthropic, OpenAI, Qwen, Kimi, Mistral, Grok, GLM, Meta Muse, Xiaomi MiMo and OpenRouter take an API key. Ollama, LM Studio and any OpenAI-compatible server on `localhost` run models on your computer. Codex is the connection used for most live runs; many of the others have been tested only with fake responses.

Every model step is sent with no tools, a fixed JSON schema and an allowlist of record IDs. Output from a model other than the one requested is recorded but not used, and there is no silent fallback to another model.

## Quickstart

**Supported:** macOS on Apple Silicon with a native arm64 Python 3.12 from [uv](https://docs.astral.sh/uv/), Node 22.12 or newer within major version 22 (`.node-version` pins 22.23.2) with npm 10, and Google Chrome for the browser tests. Intel Macs, Linux, Windows and other Node versions are untested.

```sh
uv sync
cd apps/web && npm ci && npm run build && cd ../..
PYTHONPATH=backend uv run python -m deixis serve
```

The app opens at <http://127.0.0.1:8765/>. If that port already serves DEIXIS, open that instance instead of starting another. The app starts without any model connection; you need one only to run a research.

**Connect a model and sources.** Open Settings in the app. Keys entered there normally go into the system keychain. Keys found in an untracked `.env` at startup are moved there only after the keychain write is verified; if that fails, they stay in `.env`. The `.env` file is a development-mode convenience for a run from this repository; an installed app never reads it and keeps keys in the system keychain only. [`docs/product/providers.env.example`](docs/product/providers.env.example) lists the variable names. Codex signs in to its own home folder inside the data directory, separate from your normal Codex setup.

**Where data lives.** The library, PDFs, provider responses and model homes are stored in `~/Library/Application Support/DEIXIS`, never in the repository. Set `DEIXIS_DATA_DIR` to use another folder, for example a throwaway one for experiments. Settings → This computer can move the library to another folder. Libraries written before the clean start of 10 October 2026 do not open.

## Commands

From the repository root:

```sh
PYTHONPATH=backend uv run python -m deixis serve --dev --no-browser   # backend for UI work
(cd apps/web && npm run dev)                                           # Vite on :5178, proxies /api
PYTHONPATH=backend uv run pytest                                       # quick run, slow tests left out
PYTHONPATH=backend uv run pytest -m "slow or not slow"                 # slow tests too; run before a push
PYTHONPATH=backend uv run pytest -m process -n 0                       # process tests (real servers, wall clock)
(cd apps/web && npm run build && npm run lint)
(cd apps/web && DEIXIS_ACCEPTANCE_DIR=/tmp/deixis-acceptance npm run test:acceptance -- --project acceptance)
```

The Vite proxy expects the backend on port 8765. Playwright also has a `parity` project that compares the app with the design mockup; it needs that mockup, which is not in the repository, through `DEIXIS_PARITY_MOCKUP`.

The pytest suite and the Playwright browser suite use fake models, mocked providers and synthetic records. Passing them shows that the workflow behaves as designed. It says nothing about model quality or live provider access.

Library maintenance:

```sh
PYTHONPATH=backend uv run python -m deixis backup /path/to/backup-parent
DEIXIS_DATA_DIR=/path/to/empty-dir PYTHONPATH=backend uv run python -m deixis restore /path/to/backup-folder
PYTHONPATH=backend uv run python -m deixis reextract --dry-run
PYTHONPATH=backend uv run python -m deixis equations install
```

A backup holds a consistent database snapshot, the PDFs in use, provider responses and a SHA-256 manifest. It does not hold keys. Restore checks the hashes and only writes into a data directory that has no library yet. Back up before you update the checkout.

`reextract` re-reads the PDFs in use whose stored text came from an older extractor version; `--dry-run` only reports what would change. `equations install` adds the optional Marker equation reader (about 4.4 GB); without it, arXiv papers take their equations from the authors' LaTeX source, and Mathpix can be switched on in Settings.

Two release checks live in `scripts/p9/`. `install_check.py --port 8871` installs `HEAD` into a temporary folder and starts it with its own port, data directory and keychain. `run_matrix.sh` runs the whole model-free acceptance matrix (30 to 50 minutes, including the parity check, so it needs the mockup too) and refuses to start while a `.env` exists. Both leave a running instance and your library alone.

## Architecture

| Part | Where |
|---|---|
| Local API, research workflow, storage, provider connectors, model adapters | [`backend/deixis/`](backend/deixis) |
| React interface, built and served by the backend | [`apps/web/`](apps/web) |
| JSON Schemas for every model step | [`contracts/research/`](contracts/research) |
| Method instructions loaded into model steps | [`methods/deixis-research/`](methods/deixis-research) |
| Tests and fixtures; browser tests | [`tests/`](tests) · [`apps/web/e2e/`](apps/web/e2e) |
| Measurement and probe scripts (not app features) | [`scripts/`](scripts) |

A research runs as a sequence of stored steps. Each step is saved with its input before the model is called, and a finished step returns its saved output when asked again. That is what lets a research pause, resume and recover after a crash without repeating model calls. Half-finished work found at startup is marked as unknown or paused, not retried blindly.

Before an answer is published, code checks the cited source IDs, reading depth, passage IDs and the exact quoted anchor in the passage text. An answer that fails these checks stays an unverified draft.

[`docs/layout.md`](docs/layout.md) says where each kind of file belongs, [`docs/search-architecture.md`](docs/search-architecture.md) maps the search pipeline, and [`docs/decisions.md`](docs/decisions.md) records the decisions in force. [`CLAUDE.md`](CLAUDE.md) is the working agreement for contributors, human or AI.

## Scope and limits

- A search covers what OpenAlex and Semantic Scholar return within a time and request budget. Not finding a paper is not evidence that it does not exist, and DEIXIS never reports a question or idea as novel.
- Found, screened, inspected in full text, given to the model and cited are different counts, and the app shows them separately. An answer built from abstracts says so; abstracts cannot back claims about methods, equations or detailed results.
- PDF text extraction, OCR and equation reading can fail or be partial, and the app shows those states.
- Search and answer quality have been measured only on small fixed question sets, with model judges and no human review. Treat those numbers as development checks, not as general performance. Reports have had little live testing and showed known failures; the quality of development lines and of claim-specific search is unmeasured. [`STATUS.md`](STATUS.md) records the measurements and open limits.
- The install, crash, restore, capacity and accessibility checks ran on one macOS arm64 machine with a scripted model. They have not run on another user's machine, another OS or with a screen reader.
- DEIXIS does not propose research questions on its own and does not design or run experiments.

## Background

DEIXIS grew out of the earlier Quaestio design work. The method references carried over from it (scoping reviews, snowballing, research-gap frameworks, Chain of Ideas and related AI research systems) were in this README until October 2026; they are in Git history at [`README.md` @ `ebe8ddda`](https://github.com/huguryildiz/DEIXIS/blob/ebe8ddda/README.md#historical-method-and-reference-record). The development lines feature adapts the chain-building idea from Chain of Ideas ([Li et al., 2024](https://arxiv.org/abs/2410.13185)).

## License

[AGPL-3.0-or-later](LICENSE). PDF text extraction uses PyMuPDF, which is also AGPL-licensed. The badges above do not stand for a CI result, a published package or a hosted site.
