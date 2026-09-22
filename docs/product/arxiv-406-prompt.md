# Task: find out why arXiv answers the product's searches with HTTP 406, and propose the smallest fix

Repo: `/Users/huguryildiz/Documents/GitHub/DEIXIS`. This is an investigation, not a slice: **no product code is changed in this session.** The result is a findings file and, if the cause is shown, a proposed fix for the owner to approve. Suggested model: Fable · high (hard debugging).

## What is known

- In both measurement campaigns of 2026-09-22 (`docs/product/sw-measure-2026-09-22.md`), **every** arXiv search of every run failed: 12 of 12 searches across six runs (two per run), HTTP 406, empty body, no `Retry-After`. arXiv contributed zero records. After D87 removed Crossref from search, arXiv is one of the three academic search channels, so this is a real recall loss.
- A replay the same afternoon (D88, "Also found"): the stored query sent through the product's own client got 406, while `curl` with the same User-Agent and the same URL got 200 **in the same second**; a minute later the product's client got 200 too; the encoding of the query made no difference. So it is intermittent and client-dependent, not a plain per-IP limit. Cause unknown.
- Since then `providers/common.py::send` reads 406 as a rate limit for arXiv (`arxiv.RATE_LIMIT_STATUSES = (429, 406)`). In the re-measurement after 13e the retries also got 406: all six searches ended `rate_limited`. **Treating 406 as a rate limit did not recover arXiv.**
- Code: `backend/deixis/providers/arxiv.py` (`search`: module-level lock, `MIN_INTERVAL_SECONDS = 3.0`, `send(..., headers={})`), `providers/common.py::send`, `providers/registry.py` (arXiv `page_gap=3.0`). The shared client is built in `api/app.py` (`httpx.AsyncClient(headers={"User-Agent": fetch_module.USER_AGENT})`); httpx 0.28.1. Since slice 13f (D89) discovery reads up to four hosts at once through that one client.
- Measurement data (read-only): `.local/sw-measure-2026-09-22/` and `.local/sw-measure-2026-09-22b/`, one `data-<effort>-luna/` directory per run (`library.sqlite`, `provider-payloads/`), plus `server-*.log`. The stored arXiv query texts, request descriptions and error payloads are in `run_steps` / `search_runs` of those databases.

## Questions to answer, in this order

1. **Is arXiv asked anything else during a run?** List every request a run sends to `export.arxiv.org` (search pages, count probes of the vocabulary expansion, lookups, anything else) with its time, from the measurement databases. If arXiv receives several requests within a few seconds before the search, say so; this is the first hypothesis to rule in or out.
2. **What differs between the product's request and curl's?** Capture both requests exactly (a local echo server or httpx event hooks; not a proxy that changes them): method, URL and its encoding, HTTP version, every header (`Accept`, `Accept-Encoding`, `Connection`, `User-Agent`, anything httpx adds), TLS/connection reuse. Write the diff down.
3. **Which difference produces the 406?** Change one variable at a time against arXiv and record status per attempt. Candidates, none of them assumed: request headers (especially `Accept` / `Accept-Encoding`), a reused keep-alive connection vs a fresh one, the length or shape of the boolean query, the request rate (a request within N seconds of the previous one), concurrency with other hosts on the same client. Repeat each condition enough times to tell intermittent from systematic; report counts, not impressions.
4. **What is the smallest fix**, and what does it cost (extra waiting, a separate client, a header)? Name the file and the lines.

## Rules

- **Be polite to arXiv:** at least 3 s between any two requests from this session, at most ~60 requests in total, and stop for 10 minutes on any sign of blocking (a run of 406/429/503). Use the arXiv API only (`export.arxiv.org/api/query`), small `max_results`.
- No product code change, no commit of code. Scripts and raw results go to `.local/arxiv-406-2026-09-23/` (untracked). Do not start, stop or query the service on port 8765, do not open the product database under `~/Library/Application Support/DEIXIS`, do not write into the `.local/sw-measure-*` folders.
- Measure, don't reason from memory: every claim about the cause carries the attempt counts that support it. If the cause cannot be shown within the request budget, say "not found" and list what was ruled out.
- Python: `PYTHONPATH=backend uv run --no-sync python ...` from the repo root (native arm64 venv).

## Deliverables

1. `docs/product/arxiv-406-findings-2026-09-23.md` (Turkish, plain language first, like `sw-measure-2026-09-22.md`): what was tried, the table of conditions × attempts × statuses, the cause if shown (or what was ruled out), the proposed fix with file and lines, and what is **ölçülmedi**.
2. Commit **only that file** to `main` and push (no branch, no PR, no AI attribution, no co-author; the owner's `TODO.md`, `.vscode/`, `scripts/local_index.py` are not staged).
3. Final message: the cause in one sentence (or "not found"), the evidence counts, the proposed fix, and whether it needs a decision record (a change in what the product sends is a behaviour change; the owner approves before it becomes a slice).
