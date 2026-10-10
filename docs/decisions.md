# DEIXIS decisions

Durable decisions, newest first. Each entry is short: status, what was decided, and the main limit. An entry does not turn an unimplemented proposal into a working feature. Status values are `proposed`, `accepted`, `superseded`, `rejected`, and `deferred`.

The log restarted on 10 October 2026. D1 lists the decisions in force at that point; new decisions start at D2. The old entries (old D1 to D261) are in Git history: `docs/decisions.md` at commit `26c8214` is the last full copy. D numbers in code and test comments written before the restart point to that old log, not to the entries below.

## D1 — Baseline (10 Eki 2026)
Status: accepted (owner decision 10 Oct 2026: clean start, today's fast path is the baseline) · Date: 2026-10-10 · Writer: Claude
Context: The owner chose a clean start. The fast path (old D250 to D260) became the only search path, and the old search rounds, the second-round term expansion, the old citation chain, the old answer assembly, the interactive term approval and all support for libraries written by earlier versions were deleted (commits 5a30689 to 8637fa3). The migrations were squashed into one baseline (old D261). This entry records what the code does now, so that later entries have one starting point.
Decision:

Architecture
- A FastAPI backend (`backend/deixis`) serves a React UI (`apps/web`) on loopback only. The API checks Host and Origin against an allowlist, and every mutation needs the double-submit CSRF token (`deixis_csrf` cookie, `x-deixis-csrf` header).
- A research has scope revisions. Each run is a list of steps keyed by `operation_key`. A step that already succeeded returns its stored output, so pause, resume and crash recovery never repeat a model call or a provider request that finished.
- A run stops at its next checkpoint on pause, cancel or a newer scope revision.
- One worker owns execution through an OS advisory lock (`flock`). At startup it marks half-finished steps and model sessions `outcome_unknown` and the runs that held them `paused`; it does not retry them on its own. The user resumes.

Model boundary
- Each model step gets a stored `StepInput` (records, allowlisted IDs, `step_input_id`, `scope_revision`, `skill_package_hash`) and a strict JSON output schema. Everything sent is stored before the call.
- The model has no tools. A tool item in the output fails the step with `model_isolation_violation`.
- Output from a model other than the requested one is recorded and never used (`model_mismatch`). No other model or connection is tried in its place.
- Schema repair is bounded: one repair call (`MAX_SCHEMA_REPAIRS = 1`), none for `vocabulary_labels` and `abstract_screening`. If repair fails, the answer is stored as an unverified draft and is not shown as a cited answer.
- Answer and review steps see short citation handles instead of record IDs (old D12). Code resolves them back to record IDs before validation.
- Editing a runtime file of `methods/deixis-research/` changes `skill_package_hash`. The app refuses to start when the package fails its integrity check.

Evidence rules
- Every published claim cites passages that were given to that model step, and each claim-passage link needs a contiguous anchor that code locates in the stored passage text. The UI highlights only that located anchor.
- A `source_stated` claim cites one source; two versions of one work count as two sources and are not independent evidence. When more than half of at least four claims are `analyst_inference`, the answer step makes one optional rewrite call.
- `structurally_valid` means the answer passed these deterministic checks. It does not mean each cited passage supports its claim. The `answer_review` run is a separate recorded model assessment and never edits the answer.
- Reading depth stays visible: metadata, abstract, selected PDF passages and full text are different evidence levels. Abstract screening never includes a source by itself, and a user's own inclusion or exclusion overrides the model's.

Fast-path policy (`fast_path.py`, `fast_path_v1`)
- Every new discovery run freezes this policy into its budget, with a `policy_hash`. Later code changes do not rewrite a frozen policy.
- The numbers per depth, from `fast_path.MODES` (stage seconds for plan, search, ranking, read and answer):
  - Quick: 30/30/30/60/30 (180 s); N 25, K 10; keyword record cap 450; 10 chain seeds, 2 backward and 2 forward chain requests.
  - Standard: 30/45/60/120/45 (300 s); N 50, K 20; cap 1000; 20 seeds, 4 backward, 8 forward.
  - Detailed (policy mode `deep`): 45/90/120/270/75 (600 s); N 100, K 40; cap 2000, of which 500 are reserved for Semantic Scholar; 30 seeds, 8 backward, 16 forward.
- N is how many works of the frozen list are screened and looked up; K is how many of them can reach full text.
- Stage time is active wall time that survives pauses and restarts. Unused time carries to the next stage, overrun is recorded as debt, and each stage keeps at least 25% of its base.
- Search, ranking, read and answer have soft deadlines. Submitted model calls drain; a read-stage call still out 5 s after the deadline is cut (`model_read_cutoff`).
- Plan:
  - code takes search words from the question, and three optional `vocabulary_labels` calls sort them into blocks;
  - a `search_query` model call writes the query blocks (`DEIXIS_SEARCH_QUERY=model` by default); if it fails, the run stops with `search_query_failed`;
  - one OpenAlex request routes the sources;
  - three optional `criterion_proposal` calls vote the inclusion criterion;
  - the approval is recorded as `unattended`, and nobody is asked.
- The protocol, with its search plan, freezes before the first provider request.
- An empty vocabulary (`vocabulary_empty`) or a too-broad one (`vocabulary_too_broad`) ends the run with that message. There is no approval card; the user rewrites the question, which makes a new scope revision.
- Search: one OpenAlex semantic page (up to 50 records) and OpenAlex keyword pages of 100, read page by page across queries under the keyword cap. Detailed also sends one Semantic Scholar bulk query. No other provider is searched and there is no second search round.
- Chain: one round, OpenAlex only (backward references and the first cited-by page per seed), overlapping the search and cut off before the ranking deadline.
- Ranking embeds the pool and freezes the list.
- Read: Semantic Scholar and Crossref look up the top N, and each batch of abstracts is screened by two model calls. At most K works get full text; a slot whose work found no text passes to the next work in list order.
- PDF retrieval uses 12 slots. Works still waiting at the read cutoff go to a background fetch queue that runs at most 4 at a time.
- When discovery completes, one answer run starts on its own. It answers from the evidence the read stage owned at its cutoff, then queues a separate `answer_review` run.
- Late full text can produce one new answer revision (`max_revisions: 1`). The first answer stays as it was.
- An answer over attached PDFs only (no completed discovery) uses the inspection route: PDF fetch, lexical and semantic passage ranking, then `grounded_answer`.

Providers
- All connectors in `providers/registry.py` stay: OpenAlex, Semantic Scholar, Crossref (lookup only), arXiv, bioRxiv (through OpenAlex), PubMed, IEEE Xplore, Scopus, CORE, SerpApi (supplementary), plus the Zotero collection import. Keys come from the untracked `.env` or the system keychain.
- The research search uses only OpenAlex and Semantic Scholar, and abstract lookups use Semantic Scholar and Crossref. The other connectors stay registered and configurable.

Storage
- One SQLite connection is shared by the API and the worker on the event-loop thread. Writes are short synchronous transactions with no `await` inside, and a UI-visible event is written in the same transaction as the state it describes.
- The schema starts from `storage/migrations/0001_baseline.sql`. A schema change is a new numbered file from `0002_` on. A migration that has been applied is never edited, the baseline included, and tables are not dropped.
- Runtime data (database, PDFs, provider payloads, Codex home) lives in `DEIXIS_DATA_DIR`, never in the repository.

One-time reset (old D261)
- The 77 old migrations were squashed once into the baseline, and the code that kept earlier libraries working was removed. A library written before the reset is refused at startup, and its app data folder is to be deleted. This reset is not repeated.

Limits:
- This entry restates decisions made, reviewed and tested under their old numbers. It adds no behavior; the commit that wrote it only removed two method files no step loaded.
- The tests run on synthetic records and a scripted model. They show workflow behavior, not answer quality or live latency. Live measurements are in STATUS.md and the old log.
- The anchor locator accepts a near match at a provisional 0.9 ratio over one contiguous region.
- Stage deadlines are soft, so a run can exceed its target time.
- The startup refusal of an old library says "newer DEIXIS", which is misleading for an older library (old D261).
