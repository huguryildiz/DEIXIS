# Task: SW slice 21: built-in local embedding

**Run this prompt only when row 21 of `docs/product/sw-status.md` names A1, B1 and C1** (its status reads
`plan hazır; A1, B1, C1 önerildiği gibi …`). If row 21 names a different answer to any of A, B or C, or none, stop at
once and change nothing.

Repo: `/Users/huguryildiz/Documents/GitHub/DEIXIS`. The plan is `docs/product/sw-slice21-builtin-local-embedding.md`
as committed on `main`: after `git pull --ff-only`, find the commit that last changed it with
`git log -1 --format=%H -- docs/product/sw-slice21-builtin-local-embedding.md`, write that hash in your final message,
and read the plan from the working tree at that commit. If the file is missing on `main`, stop and change nothing. The
plan is the only source of truth for this slice. Where it deliberately departs from SW8 (its section "SW8'den
sapmalar": Off last, no "Recommended" badge, no model proposal, the 256-token cut, the measured sizes instead of "about
130 MB", the conditional free-tier and uploaded-PDF lines), the plan wins over `docs/README.md`'s rule that the
review's text holds. Build decisions 1–12 (with 4a) and tasks 1–10 under A1, B1 and C1. List every place where you used
your own judgement.

## Rules

1. **Git.** Start with `git pull --ff-only` and work on `main` in the main checkout. Make one commit and run
   `git push origin main`. No branch, no PR, no AI attribution, no co-author. Before the push, run
   `git log origin/main..HEAD --format=%B | grep -i co-authored-by`. Never stash or reset. Stage only the slice's own
   files, each by explicit path (never `git add -A` or `git add .`); existing unrelated working-tree changes stay out of
   the commit and untouched: `TODO.md`, `.vscode/`, `scripts/local_index.py` and anything else that is not the slice's.
   Check `git diff --cached --name-only` before committing. If the slice is not finished, commit nothing: write what
   remains into row 21.
2. **What writes.** The embedding steps write what they write today (`source_similarities`, `passage_embeddings`,
   `run_steps`), now after every batch. The new `PUT /api/researches/{id}/english-question` writes one row of the new
   table `scope_english_questions` (migration `0053_english_questions.sql`, the only migration) for the current scope
   revision, once; `revise_scope` copies that row into the new revision in the same transaction when the question
   text is unchanged. The install job writes only under `<data dir>/tools/embedding`, `<data dir>/tools/embedding-models`
   `<data dir>/tools/embedding-hf-home`, `<data dir>/tools/uv-cache` `<data dir>/tools/uv-python`, the job file `<data dir>/tools/embedding-job.json` and the two lock files
   `<data dir>/tools/embedding-install.lock` and `<data dir>/tools/embedding-in-use.lock` (the `uv` steps run
with `UV_CACHE_DIR`, `UV_PYTHON_INSTALL_DIR` and `UV_PYTHON_PREFERENCE=only-managed` set there); `installed.json` is
written last. Nothing is written to the repository, to `~/.cache` or anywhere else outside
   the data directory. Writing the English sentence opens no scope revision and makes no decision stale; it raises the
   research's `version` and writes `english_question_saved` in the same transaction.
3. **Unchanged:** the model contract (under A1, `skill_package_hash` stays
   `sha256:7d4e238c3e9feebd451c77fb997aff717a3617008bd4165be56f9fba46bf6fca`; schemas, method package, fixtures,
   `tests/fakes.py::valid_response`), the reason-code table, the protocol body's shape (only the embedding entry's
   `model` string names the built-in model), `chosen()`'s default (the built-in model is never chosen automatically),
   D79's four code signals and rescue rule, D101's tables, D88's provider waits. Under B1, `pyproject.toml` and
   `uv.lock` are unchanged and the DEIXIS process never imports `fastembed`, `onnxruntime` or `numpy`.
4. **No authority, no substitution.** The embedding removes nothing, includes nothing and is no threshold. Off,
   missing, partial or failing, the four code signals rank the same and the run neither stops nor pauses because of
   it. A provider that cannot run is recorded as failed or partial; no other provider is used in its place.
5. **Words.** Similarity orders; no text calls it relevance or quality. The built-in model's text says "no text leaves
   the computer", never "private", and names the one download. Downloaded, checked and ready are separate states. The
   free-tier sentence says "may" and says DEIXIS cannot tell which tier a key is on. No "Recommended" badge on Gemini.
   Rate-limit waits and partial results are shown, never hidden. "No text leaves the computer" is said only of semantic
   search, never of the research as a whole. Sizes are disk sizes ("about 145 MB installed"), not download sizes; times
   are "measured on one Apple M1 Pro". The uploaded-PDF line is conditional and promises no count.
6. **Tests** use no network, no live model, no real `uv` and no real `fastembed`: `httpx.MockTransport`, a fake runner
   script run with `sys.executable`, a fake `uv` script and an injected local embedder (`create_app(local_embedder=...)`,
   `FlowDeps.local_embedder`). Add one autouse guard for the new tests' modules that fails the test on any subprocess
   call to the real `uv` binary and on any `httpx` request that does not go through a mock transport, and a test that the DEIXIS process has not imported `fastembed`, `onnxruntime` or `numpy`. Existing pytest tests must pass unchanged; if one cannot, stop and write why into row
   21. A Playwright scenario may gain assertions; none may lose one. Every decision is fixed by a test (the plan names
   them per task).
7. **Port 8765 and the product database are off limits.** The acceptance runs on copies of the stored libraries, made
   with SQLite's backup API and migrated under the session's scratch directory, never on the originals (open the
   originals read-only), and installs the built-in model into a scratch `DEIXIS_DATA_DIR`. The one network access
   allowed is acceptance (a)'s download from the pinned Hugging Face revision.
8. **Python:** `PYTHONPATH=backend:. uv run ...`, native arm64. The known unrelated failure is
   `tests/test_documents.py::test_extraction_is_stopped_when_it_exceeds_the_memory_limit`.
9. **UI:** read `.impeccable.md` before touching `apps/web`; strings go through `i18n.ts` / `labels.ts` (Turkish too).
   Verify the Settings section, the download confirmation and progress, the research view's English-sentence line and
   the uploaded-PDF line yourself with a screenshot at desktop and phone width.

## Build

Tasks 1–10 of the plan, in order:

1. `documents/local_embedding.py`: the pinned repository `Qdrant/bge-small-en-v1.5-onnx-Q`, revision
   `aa8f8b060edb00e03bfdd08813a2949946c8ba55`, the five files with their byte counts and sha256 digests as the plan's
   measurement recorded them (`.local/sw-slice21-plan-2026-09-25/download.json`; `model_optimized.onnx` is 66,465,124
   bytes, sha256 `51f1bd0addd6e859e42c2c8021a5e5461385bb676a649f4b269aa445449f2431`), `RUNTIME_BYTES_ESTIMATE`,
   `LOCAL_BATCH = 64`, `LOCAL_MAX_TOKENS = 256`, `LOCAL_IDLE_SECONDS = 300`, all five files in one manifest
   (`MODEL_FILES`) that the download, the runner, `options()` and the status endpoint all read; `download_model` writing
   `*.part`, checking size and digest, moving into place, deleting a mismatch; stale `*.part` removed at service start
   and at every install start; an environment without `installed.json` counts as half-built and is reinstalled.
2. `documents/embedding_runner.py` (runs inside the built-in environment, imports only the standard library and
   `fastembed`; loads with `specific_model_path`, `local_files_only=True`, `HF_HUB_OFFLINE=1`, the data directory's own
   `HF_HOME`; checks the model digest before `ready`; cuts at `LOCAL_MAX_TOKENS`; one JSON request per line) and
   `LocalEmbedder` on `MathReader`'s pattern: one process, one lock, idle shutdown, one restart after a crash,
   `builtin_unavailable` / `builtin_timeout` / `builtin_stopped`; every reply checked (same id, one vector per text, 384
   dimensions, finite values), else `builtin_bad_reply` and the process is closed; the runner checks all five files
   before `ready`.
3. `workflow/local_embedding_service.py` `EmbeddingService` on `EquationService`'s pattern: the four-step install job
   (environment, `fastembed==0.8.1`, model files, a start check), cancel, remove, status with step, bytes and output
   tail, the `uv` and Hugging Face directories under the data directory; the job tracked on disk in
   `<data dir>/tools/embedding-job.json` (atomic writes); ownership by `fcntl.flock` on
   `<data dir>/tools/embedding-install.lock`, held for the whole job and passed to the `uv` children with `pass_fds`;
   recovery at service start cleans up (job marked failed, "stopped when DEIXIS closed", `*.part` and a half-built
   environment removed) only when it can take that lock and also `LOCK_EX | LOCK_NB` on the in-use lock (a ready-check
   runner of a dead install may still hold it; then nothing is deleted, the job file is untouched and recovery is tried
   again at the next start or install), and otherwise deletes nothing and shows the job as running in
   another process; removal takes the same lock (409 if it cannot), sets `LocalEmbedder.removing` before any `await` so
   new requests get `builtin_unavailable` without starting a process, closes the runner after its current request,
   takes `LOCK_EX | LOCK_NB` on `<data dir>/tools/embedding-in-use.lock` (the runner of every DEIXIS process holds
   `LOCK_SH` on it, taken before start and passed with `pass_fds`; a request that cannot take `LOCK_SH` gets
   `builtin_unavailable`), returns 409 `in_use_by_another_process` ("in use by another DEIXIS process") and deletes
   nothing if it cannot, else deletes `installed.json` and then the files, and only then clears `removing` and releases
   the locks; install takes the same two locks; only the install-lock owner writes the job file; `cancel` stops only a
   job this process owns (409 `in_use_by_another_process` with the job file untouched when another process holds the
   lock, 409 `no_install_running` when none runs here); POSIX only in this slice: on `os.name != "posix"` the built-in
   option is `available: false` with `unsupported_platform`, and every built-in endpoint checks the platform before any
   lock (`GET …/builtin` 200 with status `unsupported_platform`; install, cancel and `DELETE` 409 `unsupported_platform`;
   the local embedder `builtin_unavailable` without opening a lock file); install's lock order: install lock, close
   this process's own runner, `LOCK_EX` on the in-use lock for the file-writing steps, then `flock(LOCK_SH)` on the same
   descriptor before the ready-check runner, which inherits it through `pass_fds`, then `installed.json` and release; full sha256 checks
   at service start, after install and at every runner start (the gate); `available` means "passed the last full check
   and unchanged in size, mtime_ns and inode since", reported with `last_full_check {at, passed}`, and a failed gate
   turns it false; `GET /api/semantic-search/builtin`, `POST …/builtin/install` (409 while running), `POST …/builtin/cancel`,
   `DELETE …/builtin`.
4. `embeddings.py` and `app.py`: `"builtin"` in `PROVIDERS` and `SemanticChoice`; `stored_model`
   `builtin:bge-small-en-v1.5@aa8f8b0:256`; `options()` in the order Gemini, built-in, OpenAI, Ollama, LM Studio, off,
   the built-in one available only when installed and verified; `Embedder.embed` routes the built-in provider to the
   injected local embedder (`RETRIEVAL_QUERY` → `query`).
5. `flow.py` `_source_similarity` and `_semantic_ranking`: the query vector first, then batches. Sources: when nothing is missing the query is not
   embedded either, no model call is made and the step succeeds on the stored similarities (they are scores).
   Passages (answer and table column): the query is always embedded, even when every passage vector is stored; if the
   model is unavailable the passage path falls back to keyword ranking as today and the step ends `failed` with its
   reason. Each batch is written in its
   own short transaction followed by `_checkpoint`; `partial` when a later batch fails; step output `model`, counts,
   `embedded`, `missing`, `from_store`, `query_origin`, `query_sha256`, `rate_limited_waits`, `waited_seconds`,
   `uploaded_files_sent`, `uploaded_passages_sent`. Decision 4a: whenever a provider is chosen (and, for the built-in model, a query
   text exists) the discovery run opens its `source_similarity` step even when nothing is missing; the provider and
   `stored_model` are written into the step's opening output, every finish (succeeded, partial, failed) goes through
   one helper that writes `latest stored output | counts | identity` (and the per-second wait writes merge the same
   way), so neither `finish_step` nor `set_step_output` drops the identity or `waited_seconds`, and a resumed run reads them from the
   step, not from Settings; `_ranking` reads the model from that step. Decision 5: stored similarities of the same revision and `stored_model`
   are read even when the built-in model is not installed now; nothing new is embedded; "four code signals only" (no
   stored similarity) and "stored fifth signal" are separate outcomes. A partial passage ranking
   returns the passages that have vectors (answer and table column alike). `embeddings.py`: `Embedder.embed` takes one
   batch, the step's shared `RateBudget` and a `stop` callable; HTTP 429 wait from `Retry-After`, else Gemini's
   `RetryInfo.retryDelay`, else 10 / 20 / 40 s; at most `EMBED_RATE_LIMIT_RETRIES = 3` per batch and
   `EMBED_MAX_WAIT_SECONDS = 180` shared across the step's batches and kept in the step output (`waited_seconds`
   written after each 1 s slice, also for a wait cut short by a pause); a resumed step starts with what is left; the
   wait sleeps in 1 s slices and calls `stop` after each, so pause, cancel and a new scope revision take effect within
   a second. D79's existing test passes unchanged.
6. Migration `0053_english_questions.sql`, `workflow/english_question.py` (`embedding_query`: the question when
   `detect_language(question, language_hint) == "en"`, else the revision's row, else none; built-in only), the store
   methods, the carry-over in `revise_scope`, `PUT /api/researches/{id}/english-question` (409 when a row exists or the
   version is stale, 422 when empty, over 500 characters or not English by `detect_language(text, None)`; the "question
   is already English" path is its own body `{"use_question": true, "expected_version"}`, takes no text from the
   client, skips the language check and writes the current revision's question with `origin 'question'`; both writes
   raise `version` and write `english_question_saved`); without a query the built-in steps do not
   embed, the ranking reason is `english_question_missing` and `semantic_retrieval` records
   `{"reason": "english_question_missing"}`. Gemini, OpenAI, Ollama and LM Studio take the question as written. A
   table column whose text is not English is ranked lexically under the built-in model.
7. `views.py`: the `semantic` field of decision 10 (`provider`, `stored_model`, `arm`, `english_question`,
   `needs_english_question`), inside `research_view`'s existing single snapshot. No count of uploaded PDFs to send.
8. The UI of decisions 9–11: `Connections.tsx` (order, built-in row with download confirmation showing disk sizes (with the extra
   Python 3.12 and uv cache space) and
   place, progress, ready, failed with output, remove; Gemini's free-key path and free-tier sentence), `ResearchView.tsx`
   (the Sources tab line and inline form; the conditional uploaded-PDF line under the answer and table buttons whenever
   Gemini or OpenAI is the provider), `Transcript.tsx` (`builtin` in `embeddingOf`, laptop icon, the unavailable /
   partial / from-store / rate-limited / uploaded-text-sent lines), `labels.ts`
   (`english_question_missing`). Playwright N (`builtin-embedding.spec.ts`) with
   `DEIXIS_FIXTURE_BUILTIN_EMBEDDING=fake` in `tests/acceptance/fixture_server.py`, as the plan lists.
9. Acceptance (a)–(e) of the plan in `.local/sw-slice21-acceptance-<date>/`: the real install into a scratch data
   directory (sizes and digests equal the constants; nothing new or changed under `~/.cache/huggingface`, `~/.cache/uv`,
   `~/.local/share/uv/python` or elsewhere outside the data directory, by file lists and mtimes before and after; an
   install killed in the middle of the model download and restarted leaves no `*.part` and completes without
   downloading the finished files again); the real runner on the SW7 pool text and on the migrated copy of the largest stored pool, against the
   plan's numbers (SW7 pool 51 s and largest pool 251 s at 256 tokens on an M1 Pro; ±30%, else say why), with
   `GET /api/health` latency during the embedding (p95 and max) and the runner's peak memory; the ranking rebuilt with
   built-in similarities on the migrated copies of the plan's two libraries with the four code signals' rows byte for
   byte equal to the ranking without the embedding, and the rescued records listed and counted (no claim that they are
   better); pause in the middle of the embedding and resume, only the missing records embedded; a synthetic Turkish
   question before and after its English sentence. A full research on a Gemini key without billing is not part of this
   acceptance unless the owner provides such a key; if it is not run, write it into D103 and row 21 as an open
   acceptance limit.
10. Close.

## Close

Write D103 at the top of `docs/decisions.md` (the highest today is D102), with A1, B1 and C1 and the plan's named
departures from SW8. Its Limits name: one computer (Apple M1 Pro) and one topic; the 256-token cut chosen on one pool of 1,369 records with 20
positives; passage-level retrieval with the local model not measured, so the answer-step use is a design intention;
the free tier's rate limit and 429 behaviour not measured live, the wait constants picked by hand; no stored research
had ever run the embedding (all 46 stored `sw` libraries had semantic search off); the language rule's two failure
modes (an unaccented non-English question read as English and embedded; an English question full of accented names
read as not English, with the "already English" way out); the arm's switch-off (SW8.7) still open; that DEIXIS cannot
tell a free-tier key from a paid one; the full research on a no-billing Gemini key, if not run, as an open acceptance
limit (the 429 rule then tested only against a fake endpoint). Update SW8's status line in `docs/product/search-workflow-review-2026-09-18.md`
(points 3, 4 and 6 built with their limits, point 6's model proposal as A leaves it; the partial result and the 429 wait
closed) and row 21. Run the full pytest suite, `npm run build`, `npm run lint` (17 warnings), Playwright A–N; check
`git diff --check`, the hash, the highest migration (`0053`) and, under B1, that `uv.lock` is unchanged. Report the test
run as "the known single failure apart, the rest of the full run passed" with the counts. The final message, in
Turkish, gives what was done, the judgement calls, the test counts, the acceptance numbers next to the plan's, and what
was not measured.
