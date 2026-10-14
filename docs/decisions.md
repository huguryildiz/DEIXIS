# DEIXIS decisions

Durable decisions, newest first. Each entry is short: status, what was decided, and the main limit. An entry does not turn an unimplemented proposal into a working feature. Status values are `proposed`, `accepted`, `superseded`, `rejected`, and `deferred`.

The log restarted on 10 October 2026. D1 lists the decisions in force at that point; new decisions start at D2. The old entries (old D1 to D261) are in Git history: `docs/decisions.md` at commit `26c8214` is the last full copy. D numbers in code and test comments written before the restart point to that old log, not to the entries below.

## D22 — Grok, GitHub Copilot, GLM, Muse Spark, Muse Glimmer and Ollama run research steps through the OpenAI-compatible adapter
Status: accepted · Date: 2026-10-14 · Writer: Claude
Context: Settings listed these six as "Planned model connections" with no adapter. The owner asked for them to work on macOS and Windows.
Decision:
- All six use `models/openai_compat.py`, with the same boundary as Qwen, Kimi and Mistral: no tools, JSON-object mode, one new request per step, the answering model checked against the requested one.
- Grok: `api.x.ai/v1`, `XAI_API_KEY`. GitHub Copilot: GitHub Models, `models.github.ai/inference`, model list from `/catalog/models`, `GITHUB_TOKEN` with `models:read`. GLM: Z.ai `api.z.ai/api/paas/v4`, `ZAI_API_KEY`; when the API lists no models, three known GLM models are offered and the key is first checked by a step. Muse Spark and Muse Glimmer: Meta Model API `api.meta.ai/v1`, one `MODEL_API_KEY`, each connection keeping only the listed models with its own name prefix. Ollama: `127.0.0.1:11434/v1` with no key, on macOS, Windows and Linux alike; 127.0.0.1 because Windows may resolve `localhost` to ::1.
- The four keys are managed keys (keychain, D19) and are tested by listing models. The "Planned model connections" group is gone.
Limits: Mocked transports only. No live request was sent to any of the six; endpoints and model names come from the providers' documentation, and the UI still says "not yet verified against the live API". Meta's Model API was in public preview for US developers when this was written.

## D20 — The built-in embedding model's packages are pinned with hashes; an installed copy that differs shows "Update available"
Status: accepted · Date: 2026-10-14 · Writer: Claude
Context: The built-in model's install pinned only `fastembed==0.8.1`; uv chose onnxruntime, numpy, tokenizers and the rest at install time, so two installs a month apart could differ. A changed pin never reached a copy that was already installed: `installed.json` was there, so it stayed "Ready".
Decision:
- `backend/deixis/documents/embedding-requirements.txt` lists every package of the environment with its version and hashes (`uv pip compile --universal --python-version 3.12 --generate-hashes`). Step 2 of the install is `uv pip sync` of that file, so packages not in it are removed.
- `installed.json` records the sha256 of the file's requirement lines (comments do not count) next to the model ID. When either differs from what this DEIXIS pins, or is missing (installs before D20), the status is `update_available`: Settings shows "Update available" with an Update button. The copy stays in use while its model files still match.
- An update is the same install job. After it passes, model folders of earlier revisions are deleted.
- Settings → Semantic search → This computer has a Check for updates button: it compares the installed copy with the pins and hashes the model files again, then says "No update" or shows "Update available". It fetches nothing.
- Updates are made by hand: regenerate the file (the command is in its header) or change `REVISION`/`MODEL_FILES`, run the tests, commit. DEIXIS never looks for new versions online.
Limits: The lock was generated on macOS arm64; Linux and Intel wheels are in it but no install on those machines was run. A real update (uv, PyPI, Hugging Face) was run once on the M1 Pro against a scratch data folder; the tests use a fake uv.

## D19 — API keys live in the system keychain; keys found in `.env` are moved there at startup
Status: accepted · Date: 2026-10-14 · Writer: Claude
Context: Before packaging, the owner asked that API keys not sit in a plain `.env` file but be stored encrypted where the app is installed. Keys saved in Settings already went to the system keychain (macOS Keychain, Windows Credential Locker, Secret Service); keys read from `.env` stayed there and were edited in that file.
Decision:
- At startup `credentials.move_dotenv_keys_to_keychain()` writes each managed key read from `.env` into the keychain under the service `DEIXIS` and deletes its line from `.env`. The line is deleted only after the keychain returns the same value; other lines and the file mode are kept.
- When no keychain is available, or it refuses a key, that key stays in `.env` and is still used and edited there.
- A key set in the shell still wins and is never moved.
Limits: Only the keys in `credentials.MANAGED_KEYS` move. `ZOTERO_API_KEY`, `TYPESAFE_API_KEY` and other variables stay in `.env`. The move was tested with an in-memory keychain; the real macOS Keychain was not exercised by the tests.

## D18 — Parity with mockup v24 is closed; the parity check and its exceptions file stay as the gate for UI changes
Status: accepted (UI parity S28, 14 Oct 2026) · Date: 2026-10-14 · Writer: Claude
Context: The parity campaign (slices S0–S28) brought the app to mockup v24 row by row. Each difference the app keeps on purpose is written in `apps/web/e2e/parity/exceptions.ts` with the rule behind it. S28 checked that every inventory row is compared with the mockup or covered by a behaviour test, and that every exception still describes a real difference.
Decision:
- The parity project (`npx playwright test --project=parity`) is part of the full Playwright run, and a UI change that breaks it is fixed, or it adds an exception with its rule. An exception is never added to make a gate pass when the app could match the mockup.
- `DEFERRED_TARGETS` stays empty: nothing in the mockup waits for a later slice.
- Each exception is as narrow as the measured difference: the pairs, axes and widths where it is needed. `DEIXIS_PARITY_AUDIT=<file>` with `e2e/parity/audit-summary.mjs` lists the entries a run never used or never needed, so stale ones can be found and removed.
- A completed run whose search requests a provider refused for its budget says how many were refused and how many finished, counted from the stored search steps and rows, with Retry failed searches and, for OpenAlex, a way to the OpenAlex key (R19).
- Tests never read the developer's `.env` (`tests/conftest.py`), so a local key or data folder cannot change a test's result.
Limits: Parity compares layout, type, colour and icons on SYNTHETIC fixture records at 1280 and 390 px (and the 1024 breakpoint). States the parity research cannot hold (live, paused or failed runs and others) are checked by behaviour specs, not against the mockup's pixels; `.local/design/parity-coverage.md` lists them. Model quality and live providers are not measured.

## D17 — The Library counts from the stored list and reports only what the server did
Status: accepted (UI parity S25, 14 Oct 2026) · Date: 2026-10-14 · Writer: Claude
Context: The mockup's Library page (L1–L10) shows fixed counts, a reading-depth bar and import and "New from selection" results that no route produced. A work can have several versions, and each version can belong to different researches, so "Remove from this research" needed a rule for which versions it touches.
Decision:
- Every count on the page (All works, each research, the PDF filter groups, the reading-depth box) is counted from the stored `/api/library` list. Reading depth uses the stored access level: PDF text, abstract only, metadata only.
- `library_view` lists, for each version, the researches it actively belongs to (`research_ids`). "Add to a research" shows "Already in it" from that membership. "Remove from this research" removes only the versions that research holds, after a confirmation, keeps the work in All works, and offers Undo.
- Upload PDF reports, per file, saved, already saved (`already_saved` in the upload answer) or refused with the server's reason. A Zotero import reports the import answer's counts.
- New from selection: Ask creates a research with the chosen works as attached sources and starts its answer; Start evidence table creates one and starts its column suggestions. Both name the models they will use before starting and report only the steps the server confirmed. Export writes a real .bib or .ris file and says how many records it holds.
- One version counter guards every Library read: a read started before or during a change never replaces the change's result, and a failed stale read shows no error. An Undo across several researches waits for every restore to settle, reports the ones that failed beside the ones that worked, and then reads the list again.
- A failed read never stands for an empty or negative answer. A Zotero import error says the result could not be confirmed and that some items may have been saved, because the import saves item by item. A failed study table read keeps the created research and says no column suggestions were requested. A failed Settings read stays visible, and Start waits for a retry or for the person to choose the connections' default models. A started run is reported by the status the server returned ("queued").
- The earlier Library's row density, By project grouping and empty-state "Start a research" stay: density and grouping in a View options menu in the table head's actions column (All works is the default; the left pane chooses one research), Start a research under the empty state's box.
Limits: Tested on SYNTHETIC fixture records with mocked Zotero answers (e2e/library.spec.ts, parity surfaces library and library-empty) and a pytest on the upload and membership fields (tests/app/test_library_routes.py). No real model answered the Ask or table runs, and no real Zotero library was read.

## D16 — Settings shows only what was stored or measured, and a key is never shown again
Status: accepted (UI parity S24, 14 Oct 2026) · Date: 2026-10-14 · Writer: Claude
Context: The mockup's Settings page (ST1–ST11) marks every tile "Connected", says the proxy test "opened a test article", and offers a Save step for semantic search. The app has no route that opens an article through the proxy, and several tiles have nothing a page visit could test.
Decision:
- A tile's pill and a sheet's state line name the stored state: signed in or not, installed or not, key configured, no key needed, not set up, planned. Opening Settings tests nothing. Test, Save and test, and Find it on this computer report only the server's answer, with the time it was checked.
- The proxy line and the Scopus line are two facts. The proxy line says whether the proxy host answered ("Proxy reachable · article access not checked", "Proxy did not answer", "Checking", "Not set up"). The Scopus line says whether Scopus confirmed its full view on this network. The words "Working", "VPN required" and "institutional network" are not used. Test saves a changed address and then asks its host once. One proxy test runs at a time, shared with the sidebar.
- A semantic search choice saves when it is chosen, as in the mockup. A "Needs …" pill comes from the provider's real readiness.
- A key field is always empty. Its placeholder says where the key is stored (keychain or .env), and keys go through credentials.py. A stored key is replaced or removed, never shown. Remove asks inline first.
- Usage this month counts the calls in stored model sessions by role. A bar is the role's share of the month's calls. OpenAlex today is its last stored response, shown with that response's time. A figure that is not stored reads "not known", never 0.
Limits: Tested on SYNTHETIC fixture records with route-simulated proxy, usage and credential answers (e2e/settings.spec.ts, builtin-embedding.spec.ts, parity surfaces settings and settings-sheet). No live proxy, Scopus or OpenAlex key was used. A keyless provider has no test route, so its sheet only saves the contact email.

## D15 — A stopped model is replaced only by the person, and the stopped step waits for Retry
Status: accepted (UI parity S27, 14 Oct 2026) · Date: 2026-10-14 · Writer: Claude
Context: The model-down notice (mockup R20) offers "Retry this step" and "Choose another model". The route that changes a research role's model (`PUT /api/researches/{id}/models`, S17) records the change and makes the next model steps use it. The notice needed a rule for what the choice does to the stopped run and what the page says about it.
Decision:
- On a run paused because its model did not answer (`model_call_failed`, `model_connection_not_ready`, `model_connection_unavailable`, `model_mismatch`), Resume run reads "Retry this step"; it sends the stopped step again through the existing resume. Cancel run stays.
- "Choose another model" opens a dialog with the role of the stopped step preselected and the models the connections list as ready. Saving records the change and does nothing else: the run stays paused until the person presses Retry this step. Finished steps keep the model they ran on.
- The toast names the change the server returned (role, from, to), and the notice lists every change made since the stop until the run moves on.
- A review by another model keeps the model it was requested with (`owner_reviews.requested_model`), so a role change never moves it. On a stopped review the button reads "Review again with another model" and opens the review request flow (Preview, then Start review) for the same target with the stopped review's focus and note; a new review is started beside the stopped one, which stays as it was. A change notice on any run says where Retry sends the stopped step: to the new model only when the changed role is the stopped step's own.
- The run turn's model line names, for each model phase, the models its steps' stored sessions went to (`model_sessions`, each model once), so a run that moved a role names both models. While the run can still send, a phase not finished also names the role's model set now, labelled "set for the next calls".
Limits: Reasoning effort is not stored per call, so a model named from stored sessions carries no effort; only the "set for the next calls" entry shows one, from the current setting. Tested on SYNTHETIC fixture records with a second listed model (e2e/steps.spec.ts, `DEIXIS_FIXTURE_SECOND_MODEL`) and a pytest on the view's step models; no real model was asked.

## D14 — A run can be bound to the question revision the screen showed
Status: accepted (decided with Sol over S23b's review, 14 Oct 2026) · Date: 2026-10-14 · Writer: Claude
Context: The Search plan panel (D12, slice S23b) saves a plan as a new question revision and then asks for its search. Another window can save a newer revision between those two requests; a run made then would search that other plan while the panel says its own plan is being searched.
Decision:
- `POST /api/researches/{id}/runs` takes an optional `expected_scope_revision`. The run is created only while that revision is still the current one, checked in the transaction that creates the run; otherwise the route answers 409 and writes nothing.
- A request without the field behaves as before and takes the current revision. A repeated idempotency key returns the run it created, whatever the revision is now.
- The Search plan panel always sends the revision that holds the plan it searches, reports the revision of the run the server returns, and on a 409 shows the newer revision as a conflict that keeps the draft.
Limits: Only the Search plan panel sends the field so far; the other ways to start a run still take whatever revision is current. Tested in pytest (tests/app/test_start_run_revision.py) and on SYNTHETIC fixture records (e2e/search-plan.spec.ts).

## D13 — "Search for new works on this" saves the follow-up question as a new revision without the old English key terms
Status: accepted (decided with Sol over S22b's review, 13 Oct 2026) · Date: 2026-10-13 · Writer: Claude
Context: A follow-up the passages do not answer (D11; R31, slice S22b) offers "Search for new works on this". It saves the turn's question as the next question revision, which the person then searches. A revision left without key terms keeps the previous revision's, and key terms go into the search ahead of the question, so the new question would be searched with blocks written for the old one.
Decision:
- The new revision's question is the turn's question as asked, saved only when the person presses the button; no run starts, and the message names the saved revision and says no search has started.
- Its English key terms are cleared (sent as an empty value), so the next search reads the new question alone. A question that needs key terms (one not read as English) stops that search with `key_terms_needed`, as a newly typed question does, and the person gives them in the revise form.
- The turn that asked it is kept and marked as asked under the earlier revision; it no longer offers the button.
Limits: Key terms the person would have wanted to keep are not carried over; they type them again. Tested on SYNTHETIC records in the fixture server only (e2e/followup-turns.spec.ts); whether follow-up questions make better searches is not measured.

## D12 — A person can edit the search plan; a saved plan replaces the three planning calls for its revision
Status: accepted (decided with Sol over S23a's review rounds, 12 Oct 2026) · Date: 2026-10-12 · Writer: Claude
Context: The mockup's Search plan panel (P42, F18, slice S23a) lets a person change the search words, the criterion and the optional providers, then search again.
Decision:
- The plan is checked with SearchQuery's term rules and saved as a new scope revision (`user_plan_json`, migration 0008), never edited in place.
- A run of that revision skips `vocabulary_labels`, `search_query` and `criterion_proposal` and builds their outputs from the plan (origin `user`). It counts the plan's terms on OpenAlex with backups as before, records the approval as `user_edited` and freezes the plan in the protocol before the first result fetch.
- The plan's words alone make the keyword queries and the ranking and screening blocks; the question's own query is not searched beside them.
- Its criterion, or its explicit absence, holds for that revision only: every reader takes the criterion that revision froze, and no other revision takes it back. The criterion's population and comparator mapping is carried with it, applies only while its part is unchanged, and is never added by a person.
- OpenAlex is required. A Semantic Scholar, Crossref or Scopus left out gets no search or abstract-lookup request, recorded `excluded_by_user`.
Limits: Full-text acquisition still asks Crossref for PDF links whatever is unchecked; the panel must say so (S23b). The query shown before a run is a preview, compiled again at run time. Tested on SYNTHETIC records with the fake model only; whether edited plans find better works is not measured, and D8's live run is still owed.

## D11 — Follow-up questions are answered only from passages the research already holds
Status: accepted (decided with Sol over S22a's review rounds, 12 Oct 2026) · Date: 2026-10-12 · Writer: Claude
Context: The mockup's follow-up box (R30, R31; F17, slice S22a) asks a further question inside a research. It must not start a search or cite anything the research has not read.
Decision:
- Each question is one `followup_answer` run. Its passages come from the latest answer's frozen evidence for the current question revision, or from the included works when there is no answer yet. Sources the person excluded or set to pending, read on the work's current head, are left out. Passages are ranked by word match and meaning, fused by RRF, and only the passages sent in that call can be cited.
- Every quote must be found in its passage. After one repair, an invalid answer is stored as an unverified draft with no citations; the same happens when the two-call budget runs out on invalid output. The outcome is "not answered" when the passages do not say.
- Pause, cancel, a newer question revision, the person's source choices and the stored files are checked before each call, on resume and inside the publish transaction. A turn and its citation links are published together and never edited. A published turn shows `stale_scope` or `stale_selection` when the question or the selection changed later.
- "Search for new works on this" saves a new question revision, which the person starts.
Limits: Whether a question counts as answered is the model's call, and a quote found in its passage does not prove the passage supports the claim. Without semantic ranking (no embedding model, or a question not in English) only word-match ranking runs. Tested with SYNTHETIC records and the fake model only; one live gpt-5.6-luna run in its own data directory is still owed, and whether these answers help a researcher is not measured.

## D10 — OpenAlex semantic requests overlap behind a 1.5 s start gate; pages hold 100 records
Status: accepted (owner approved both, 12 Oct 2026; code reviewed by Sol over four rounds) · Date: 2026-10-12 · Writer: Claude
Context: D6's live check (11–12 Oct) found each seed's semantic request took 5–6 s and ran one after another, taking search time from the keyword pages. OpenAlex documents semantic search at one request per second and `per_page` at most 100 (200 is deprecated; help.openalex.org, read 12 Oct).
Decision:
- Every OpenAlex semantic attempt, retries included, waits at one process-wide start gate (`openalex.SEMANTIC_PACER`, 1.5 s between starts); replies may overlap. A start is claimed when the caller wakes, so callers that overslept together still start 1.5 s apart.
- A version 2 plan's seed requests run concurrently; each is written after the one before it, so search rows, events, request indexes and first admission keep seed order.
- After its gate wait a request sends nothing when the run's OpenAlex quota ran out meanwhile (recorded `quota_exhausted`, as before) or the run stopped or passed its search deadline (page left unwritten; the seed is cancelled `deadline`). Such an attempt counts as no request.
- `openalex.MAX_RESULTS` is 100. The fast path already asked 100 a page; the old page-allowance formula now allows twice the pages for the same read depth.
Limits:
- 1.5 s comes from one live probe (12 Oct, 6 overlapping requests): 1.0 s drew one 429, 1.25 s and 1.5 s none. Not measured under other keys, load or networks.
- If an earlier seed task raises (a code or database fault, not a provider error), or the process dies while a later reply waits for its turn, that reply is lost and the request is sent again on resume (one paid request). Writing it out of order was rejected because it changes first admission.
- The time saved per seeded run is not measured live.

## D9 — An answer the person starts may read works screened after the cutoff
Status: accepted (decided with Sol over S20's review rounds, 12 Oct 2026) · Date: 2026-10-12 · Writer: Claude
Context: A discovery-bound answer reads only the evidence the read stage held at its cutoff (old D253). "Screen more" (F13, slice S20, run kind `screen_more`) screens works below the read window later, so without a change its candidates would never reach an answer, and regenerating the answer would give the same text.
Decision:
- A new answer the person starts may read works that a Screen more run of the same question revision made candidates through two agreeing abstract reads. Only the version both runs read is taken, with its stored abstract, while it still has exactly the title, abstract, DOI, year and venue they were shown.
- Each such row carries `screened_after_cutoff` (the Screen more run) and `evidence_basis: abstract_screening` in the answer input and the answer view, so the interface can label it "screened after the cutoff (abstract screening)".
- Every batch's candidates raise `selection_revision` in the same transaction as the decisions, so an earlier answer reads `stale_selection` and stays as it was.
Limits:
- Abstract-based evidence only; nothing is included automatically, and only works the cutoff left out as `outside_read_window` or `not_screened_at_cutoff` qualify.
- A work counts as screened, and is never planned again, when a person decided it at any stage or set the selection of any of its versions (included, excluded or pending); when it has a current full-text stage decision of any code; or when it has a current abstract decision other than `abstract_not_read`, `abstract_not_proposed`, `no_abstract` or `abstract_not_found`.
- Screen more plans only works the abstract stage can send: the current head is a search candidate of the revision and some search-candidate version has its own abstract and no lookup code. A (work, head) pair a completed run planned without a decision is not planned again. No abstract is fetched.
- A work stays out of the answer when it left the research; when its outcome is `criterion_not_met`, `out_of_scope` or `versions_disagree`; when the person's selection of its current head is not included or, with none on the head, any person selection on another version is not included; or when the version read changed.
- One version per work (the admitted head, else the smallest record id) replaces the cutoff's record and is marked `cutoff_source_version_id`. Automatic answers and late revisions do not add these works; a late revision of a person-started answer keeps the rows it had.
- Measured on SYNTHETIC fixtures with a fake model only. Whether these answers help a researcher is not measured; D8's live-run limit covers it.

## D8 — The interface matches the mockup; mockup-only elements become real features
Status: accepted (owner 11 Oct 2026, evening: "it should have been exactly the same as the mockup", option "make everything real") · Date: 2026-10-11 · Writer: Claude
Context: D5 took the mockup's colours and fonts but kept the old structure (research tabs, modal sheets) and left out every mockup element without a backend. After the port the owner compared the app with the mockup (v24, `.local/design/elicit-style-mockup/index.html`) and asked for the same screens. The work is planned in `.local/design/parity-plan.md` as slices S0 to S28. D6 and D7 were taken by other sessions the same day, so this entry is D8.
Decision:
- Every screen matches the mockup: layout, order, sizes, wording and icons. Elements that map to stored data are wired to it. Elements with no backend are built as small real features. No placeholder data ships.
- Fixed UI is copied exactly; example data is not. Labels, headings, button text, menu rows, hints, empty states, icons, sizes and order come from the mockup. Paper titles, counts such as 412 or 50, model names, the institution and the person's name come from real records, and a list has as many rows as the data has.
- Controls that exist only to operate the mockup are not built: the "Mockup states" switcher, the "Mockup · example data" tags, "Use the example setup", "Open the worked example", "Reset the mockup", the "N more works … are not shown in this mockup" rows and every foot note that starts with "Mockup:".
- A sentence names only the operation that was done and measured. Where mockup copy claims something the app does not do, that sentence changes and the layout stays. Examples: "Read in full" becomes the live label "Full text read" (the reading step reads selected pages); the proxy line says "Proxy reachable · article access not checked" or "Proxy did not answer", and the Scopus full-view check is its own line; the composer box reads "PDFs guiding the search · their titles, abstracts and references shape the query." Each slice checks the copy of its screens against this rule and notes additions in its commit.
- Contrast beats colour match. Three mockup pairs fail 4.5:1 (`--muted` on the chip surface, `--faint` used as text, the warning tone on its tint). They keep D5's values and are declared exceptions in the parity check (`apps/web/e2e/parity/exceptions.ts`), listed by selector, CSS property and use. D5's abstract colour `--attr-abstract` is approved for dots and icons, not as a text colour; abstract labels use `--muted`, and text that uses `--faint` in the mockup uses `--muted` in the app. The check computes each exception's actual foreground and background, colour mixing and alpha included, in hover and selected states and both themes: text needs 4.5:1, an icon or dot that carries meaning 3:1. Keeping a token never waives that check.
- Every live feature keeps working. A live feature with no mockup element goes into the nearest mockup container (panel, menu, step detail, rail box) in mockup style; the placement table is §2.2 of the plan. Disabled "Later" rows ("Systematic review", "Import BibTeX or RIS", "Add by DOI") ship disabled, as drawn.
- Owner questions, decided with Sol: (Q1) keep every live feature, placed per the plan's table; (Q2) change every false sentence by the rule above, not only a fixed list; (Q3) keep D3: the composer shows a check row for each eligible PDF, up to five, all guiding the search; (Q4) the "Suggested" cards on Home come from the stored `unanswered_aspects` of current, valid answers, with no model call, and say "Suggested" and nothing more.
- This overturns three parts of D5: "Structure stays" (the research tabs become the mockup's thread, artifacts rail and side panel; old URL segments stay as aliases), "Nothing from the mockup that lacks a backend is built", and the citation highlight colour (D5 kept the accent tint; the highlight now uses the mockup's yellow `--mark`, #fdf1b8 light and #5a4d17 dark, with the class name `citation-highlight` kept).
- Evidence rules are unchanged: counts stay separate (found, screened, passed the abstract stage, included, full text read, given, cited), abstract screening never includes a source alone, versions are never merged, and anchors come from the backend.
- A parity check (`apps/web/e2e/parity/`, Playwright project `parity`) compares the app with the mockup per screen: presence and order, chrome geometry, typography, colour and icons, within the plan's tolerances. A difference passes only when `exceptions.ts` lists it with its rule. Screens a later slice still has to change are listed as pending pairs, counted and printed, and turned on by that slice.
Limits: The parity check and the acceptance suite run on SYNTHETIC fixtures. They show layout and behaviour, not model quality, live provider access, or whether the new screens help a researcher. Follow-up answers, "Screen more" and the user-edited search plan each need one live run (gpt-5.6-luna, own data directory) before this entry's limits are closed. Pixel diffs are written for review only and do not fail the check.

## D7 — A downloaded built-in model is used when nothing else is chosen
Status: accepted (owner asked for it on 11 Oct 2026) · Date: 2026-10-11 · Writer: Claude
Context: With nothing saved under Settings → Semantic search, `embeddings.chosen` used Gemini when its key was set and otherwise turned semantic search off. Old D103 added the built-in model (bge-small-en-v1.5) as an install on request and never chose it by itself, and nothing outside Settings said that semantic search was off. A person without a key, the main audience of the built-in model, therefore started with keyword ranking only and was not told why.
Decision:
- With nothing saved: Gemini when its key is set, else the built-in model when it is downloaded and its files check out (`local_embedding.builtin_available`), else off. A saved choice, Off included, always wins. Nothing downloads the model without the person's click.
- Home shows one info notice under the composer when semantic search is off only for that reason (nothing saved, no Gemini key, model not downloaded): what it means, the disk sizes worded as in Settings, and "Download the built-in model". While the download runs it shows the step; when the model is ready the notice goes away and the rule above uses the model. The notice saves no setting, so a choice made in another tab is never overwritten; it checks again when the window regains focus. Not shown after the person chose Off, while a removal is under way or failed, or on Windows.
- A discovery run's similarity step freezes its model when it opens, before planning, as before. The protocol now names that frozen model (`flow._protocol_embedding_model`) instead of reading the current choice at freeze time, so a setting saved or a download that finished while the run planned changes neither the ranking nor the protocol of that run; the next run uses the new choice.
Limits: Whether ranking with the built-in model or with Gemini gives better lists was not measured; the 10 Oct baseline used the built-in model. A person with only an OpenAI key still starts with semantic search off and sees the notice. The built-in model reads English only, so a non-English question asks for one English sentence on the Sources tab, as with an explicit built-in choice.

## D6 — Seeds widen the search, the question decides the order (fast_path_search version 2)
Status: accepted (owner 11 Oct 2026: "planı yaz, Sol'a inceletin, yeni chat'te kodlansın") · Date: 2026-10-11 · Writer: Claude · Reviewer: gpt-6.1-sol medium (plan 3 rounds, code 2 rounds)
Context: Under D3 one OpenAlex semantic request carried the question and every seed's text within 1,500 characters, so with three seeds about two thirds of it was seed text; the first chain seeds were taken from that page. In the ranking each seed PDF pushed one question-chosen code seed out of the graph's 15, and nearness to several seed PDFs was added up. The live check of 11 Oct (D3 Limits) saw 2–3 seeds fall behind no seed on two of three questions; the cause was read from the code, not measured.
Decision:
- A run whose seed envelope is `seed_pdf_v2` freezes `fast_path_search` version 2. The question's semantic request is the unseeded one. `seed_semantic` holds one OpenAlex semantic request per seed with text (`seed_match.seed_text`, cut to 1,500 characters, `limit = semantic_top // 2`), sent in seed order after the question's request and `chain.initial()` and before the keyword pages (`search:fast:semantic:seed:<i>`, class 0, request index 1..n). They go through the fast path's own page path: same admission, quota suppression, retries and search-stage deadline (`cancelled`, `deadline`). Their records enter the pool as search candidates.
- The question's request keeps the source versions it wrote (`accepted_source_version_ids`, version 2 only). The first chain choice takes a semantic seed only through one of them: a record past the request's limit that the library already held, or one only a seed's request found, is never a first chain seed. The fallback choice still ranks the whole pool, seed finds included.
- The graph rule is read from the frozen plan, never from live code (`fast_search.graph_rule`): version 2 ranks with `seed_max_v2` in the keyword ranking, the chain fallback and the frozen list (the manifest names it; one without it replays as before). Under it the seed PDFs come after the user's and the code's graph seeds and push none out, a record scores the nearest seed PDF only (`max`), and in the list's second graph pass a seed PDF's OpenAlex copy is never a further seed. TF-IDF already took the nearest seed and is unchanged.
- A seeded model-written query records `seed_terms`: its searched terms with no word of the question (or its saved English sentence) and some word of the seed excerpts, with their block. A diagnosis only; nothing reads it.
- The research page counts a seed as having guided the semantic search when its own request succeeded.
- An unseeded run freezes the same plan as before, byte for byte, and ranks as before. A run whose protocol froze D2's or D3's plan finishes under it.
Limits: Live check (11–12 Oct, gpt-5.6-luna, Standard, rule frozen beforehand in `.local/seed-live-2026-10-12/RULE.md`): 3 questions × none / 1 seed / 3 seeds × 2 runs, the seeds being target papers (a leaky test). Share of the remaining targets in the top 50: 1 seed 0.51 vs 0.42 without (higher on dbr_vbf and uwsn_kconn2022, one target lower on battery_soh), +40 s on average; 3 seeds 0.47 vs 0.39 (higher on dbr_vbf, equal on uwsn_kconn2022, one target lower on battery_soh), +29 s. The frozen rule's verdict: 1 seed "no harm shown; a sign of help", 3 seeds "no harm shown". Two runs per arm with 3–14 targets per question: one target moves a share by 0.07–0.33. Each seed request took 5–6 s, serially, out of the search stage's time; when the plan stage overruns its 30 s the search stage gets less (also unseeded), and in one 3-seed run no keyword page was sent. The check found that OpenAlex counts the 1,500-character limit in UTF-16 units (fixed in c896e00). Tests use SYNTHETIC records and a scripted OpenAlex. The OpenAlex quota guard stays in memory and resets on restart, as before. Ties in the ranking break by record identifier. OpenAlex `related_works` is left for a separate check.

## D5 — The interface takes the mockup's look
Status: accepted (owner 11 Oct 2026, after reviewing the clickable mockup) · Date: 2026-10-11 · Writer: Claude
Context: The owner reviewed the clickable mockup (claude.ai artifact, v24; local copy `.local/design/elicit-style-mockup/`) and asked for its look in the app. The mockup follows Elicit's layout; DEIXIS keeps its own ink blue (#3b5b9a light, #93acdf dark) where Elicit uses teal. The design guide said not to copy Elicit's visual style, so the guide changes with the code.
Decision:
- Colours keep the editorial token names in `index.css` and take the mockup's values: white page, lighter side, hover and selected surfaces, darker ink. New tokens `--ink-2`, `--faint`, `--accent-deep`, `--accent-tint`, `--accent-line`, `--bubble` and `--shadow-float` exist in both themes. `--primary` and `--accent` do not change.
- Contrast comes before the mockup: the requirement is at least 4.5:1 for text on the surfaces it sits on, so `--muted` stays #5b6475 in light, the include and uncertain tones and the abstract colour are a little darker than in the mockup, and `--faint` (icons and hairlines only) is held at 3:1.
- Inter (`--font-sans`) is the face for the interface and for reading text: claims, passages, source titles and headings. Source Serif 4 (`--font-serif`) is kept for the report title, emphasis inside the report, the report preview card and the PDF first-page text in the queue. Both are bundled npm packages at fixed versions, so the app still works offline. Math stays in KaTeX's own fonts.
- `.impeccable.md` describes the new look. Citation marks keep the accent tint, not the mockup's yellow.
- Structure stays: research tabs and their URLs, modal sheets, class names and DOM. Later slices restyle the shell and the screens on top of these tokens. Nothing from the mockup that lacks a backend is built.
Limits: This changes how the app looks, not what it does. The 4.5:1 requirement was checked for the token pairs, not for every rule: two pre-existing exceptions found in review were fixed with this change (the empty evidence-cell text and the dark PDF-page muted text); others may remain. Nobody tested whether the new look is easier to use. The mockup features without a backend listed in the port plan (follow-up chat turns, search-plan editing, usage meters, new export formats and the others) stay out.

## D4 — An answer over attached PDFs reads them in full width
Status: accepted (owner 11 Oct 2026: "uygun") · Date: 2026-10-11 · Writer: Claude · Reviewer: gpt-6.1-sol medium (code 6 rounds)
Context: A live attached-only answer (gpt-5.6-luna, two IEEE PDFs, 77 passages, limit 48) gave the model 12 passages: every source was capped at six (`MAX_PASSAGES_PER_SOURCE`), two of the twelve were reference-list chunks, and the second paper's result pages never reached the answer, which then said its key number was missing.
Decision:
- When the research uses attached files only (`source_scope = attached`), the cap per source is `max(6, limit // number of sources)`, so one to eight PDFs share the whole limit. Other scopes keep six.
- A passage that reads as a numbered reference list (`_reference_list` in `workflow/flow.py`: three entries such as "[4] H. U. Yildiz," with three years, starting near the top, after nothing or after the end of a previous entry) is ranked after every other passage in the topic order, a crowded source's pages and the criterion order. It is never dropped, so a misread conclusion is only ranked lower.
Limits: Four live runs, one each (gpt-5.6-luna, 11 Oct): the same two PDFs again (48 passages, 6 claims, the second paper's ">50% lifetime" result now cited), one 24-page review alone (48 passages, 10 claims), three directional-antenna papers (16 each, 9 claims, all three cited), two other papers (24 each, 7 claims). All four answers `structurally_valid`; the run's own reviewer marked 28 claims supported and 4 partly supported. No person checked the claims. The detector misses author-year reference lists and was checked on two IEEE papers only.

## D3 — Up to five seed PDFs, uploads and Zotero through one gate (seed_pdf_v2)
Status: accepted (owner 11 Oct 2026: "PDF veya PDF'ler seed olarak verilirse sorun olmasın, Zotero entegrasyonu da aynı şekilde çalışsın") · Date: 2026-10-11 · Writer: Claude · Reviewer: gpt-6.1-sol medium (plan 3 rounds, code 2 rounds)
Context: D2 let one PDF guide the search. With several PDFs, Home made the user pick one with a radio button. A research started from a Zotero collection alone chose no seed and did not start its search. A Zotero record's own DOI was not used, so a PDF with a blank cover page never matched.
Decision:
- The seed is an ordered set of at most five PDFs (`seed_snapshot_json` version 2, with a `seed_key` fingerprint). Uploaded files and Zotero or library PDFs go through the same function (`store.set_seeds`), and one function decides which sources can be seeds (`store.seed_candidates`); the page lists exactly those. Order is the request's order, or the candidate order for `all_eligible`. With more than five eligible PDFs, the five whose first two pages share the most question words are taken; the rest are listed as `not_selected`. The old single-seed format is read as a one-element set without rebuilding its excerpt.
- The excerpt budget is split across seeds: one seed keeps D2's excerpt exactly; with n seeds each gets `max(1, 4 // n)` passages and `5600 // n` characters. The passage cap becomes `max(4, n)`, so five seeds give five passages; the 5,600-character cap stands.
- Matching keeps D2's rules per seed, with one DOI request for all seeds and one meaning search for each undecided seed (at most 1 + 5 requests). The DOI request asks for up to 100 works and counts as failed when OpenAlex reports more matches than it returned, so two works sharing a DOI are never cut to one; for a single uploaded seed this is the only change from D2's requests (`per_page=100` instead of the DOI count). A Zotero or library seed may also match by its record DOI (`record_doi`): exactly one OpenAlex work with that DOI, whose title equals the record's title and stands in the first 1,500 characters of the first page that has text (page 1, or page 2 when page 1 is blank). A citation on page 2 of a page-1-text PDF never counts. The result of that check is kept as `record_check`.
- Matched seeds are the first chain seeds in seed order, deduplicated by OpenAlex work, within the policy's seed count. The semantic query is the question followed by equal shares of each seed's text within 1,500 characters, the longest `search.semantic` OpenAlex accepts (one seed: D2's string, cut at 1,500); the parts that went in are kept as `seed_parts`. D2 assumed 2,000 from the help page; the live API refuses more than 1,500 with HTTP 400, which a live run on 11 Oct showed on every seeded run until this was fixed, and also failed the seed lookup's meaning search. A run whose seed lookup failed does not pass that failure to the next run of the revision. The query writer sees every seed's excerpt. The ranking reads each seed through its frozen context.
- A run that opened the D2 seed step, or froze a D2 protocol, finishes under D2; no finished lookup is sent again.
- The research page shows one line per seed: what OpenAlex matched, and which of query writing, the similar-paper search and the citation chain actually used it, read from stored steps (a chain request counts only when it was sent). Home makes every added PDF a seed and starts the search, also when only a Zotero collection was added. Repeating an identical seed request changes nothing and returns 200; a 409 is a real conflict and Home then does not start the search.
Limits: Live check (11 Oct, gpt-5.6-luna, Standard, one run per arm, rule frozen beforehand in `.local/seed-live-2026-10-11/RULE.md`): 3 questions × none / 1 seed / 2–3 seeds, the seeds being target papers (a leaky test). All 10 seed PDFs that matched went to the right OpenAlex work (9 of 10 matched, none wrong). Share of the remaining targets in the top 50: 1 seed 0.55 vs 0.46 without; 2–3 seeds 0.42 vs 0.44, falling on uwsn_kconn2022 (2/12 vs 5/12) and battery_soh (1/12 vs 3/12) and rising on dbr_vbf. The frozen rule's verdict is "help not shown" (one 3-seed run was 86 s slower than the 60 s allowance). Single runs; the drops may be noise. Tests use SYNTHETIC records and a scripted OpenAlex and Zotero. With five seeds the query writer sees about 1,100 characters of each first page. The top-five choice for a large collection uses question-word overlap only; the user can change it on the research page. The quick chain budget may not cover every seed's reference list. `search-query.md` changed, so `skill_package_hash` and protocol hashes change for every run.

## D2 — The seed PDF guides the search (seed_pdf_v1)
Status: accepted (owner 11 Oct 2026: "planı yaz ve Sol'a inceletip kodla") · Date: 2026-10-11 · Writer: Claude · Reviewer: gpt-6.1-sol medium (plan 3 rounds, code 2 rounds)
Context: In a "Files + academic search" research the UI always picks a seed PDF and said its passages "guided the search", but no search step read them. The semantic query was the question alone, the chain seeds were the top semantic results, and the ranking saw the upload with a file-name title, no abstract and no references.
Decision:
- Before anything else plans, a discovery run with a ready seed looks the PDF up in OpenAlex (`workflow/seed_match.py`, step `seed_match`): the DOIs on physical pages 1–2 in one `filter=doi:` request, then, only if no DOI record decides, one semantic request with the head of page 1. A work is taken only when its title (4+ words) stands in the first 1,500 characters of page 1 and exactly one work does; two or more is `no_match`. A DOI alone never decides. Each lookup is its own step, so a resumed run does not send it again; a failed lookup is recorded (`lookup_failed`) and the run goes on.
- The protocol freezes the full context (`seed_match`: status, identifiers, title, abstract, reference list, the first 2,000 characters of page 1). The chain, the semantic query and the ranking read it only from the protocol. A run whose protocol froze before this rule finishes without it.
- Matched: the PDF is chain seed 0 (it takes one of the policy's seed places; the request caps are unchanged), and the same OpenAlex work is never chosen again. The ranking reads the PDF seed with the matched title, abstract, references and OpenAlex identity, and never scores the PDF against its own OpenAlex copy or takes that copy as a second seed.
- The OpenAlex semantic query is the question followed by the matched title and abstract, or the PDF's first page when unmatched, cut at 2,000 characters; the ranking's embedding query stays the question.
- The query-writing model (`search_query`) receives the frozen seed excerpt as passages; `search-query.md` tells it to take field terms from it but let the question decide. A query another run wrote without the same seed pages is not reused.
- The research page says what the seed did, from the protocol (`scope.seed_use`).
Limits: How often the matcher picks the right work, and whether seeding raises the targets in the top 20, were not measured; all tests use SYNTHETIC records and a scripted OpenAlex. PDFs with a cover page match nothing (fail closed). An unseeded run is unchanged except for `skill_package_hash` (and so the protocol hash), because `search-query.md` changed. Backlog from review: the page sentence uses the past tense once the protocol freezes, before the chain has run, and says "query writing" even when `DEIXIS_SEARCH_QUERY=code`; the transcript does not count the PDF seed apart; no Playwright case for the seeded path.

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
- Schema repair is bounded: one repair call (`MAX_SCHEMA_REPAIRS = 1`), none for `vocabulary_labels` and `abstract_screening`. The answer step has one exception: when only the several-sources rule for a `source_stated` claim (and anchor defects code may salvage) still fails after that repair, it makes one more call, `grounded_answer_resplit` (old D249), if the model-call budget still allows it. If repair fails, the answer is stored as an unverified draft and is not shown as a cited answer.
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
  - code takes search words from the question, three optional `vocabulary_labels` calls sort them into blocks, and OpenAlex count requests check the terms;
  - a `search_query` model call writes the query blocks (`DEIXIS_SEARCH_QUERY=model` by default); if it fails, the run stops with `search_query_failed`;
  - at most one OpenAlex request routes the sources (none when no domain source needs it);
  - three optional `criterion_proposal` calls vote the inclusion criterion;
  - the approval is recorded as `unattended`, and nobody is asked.
- The protocol, with its search plan, freezes after these planning requests and before the first request that fetches search results.
- An empty vocabulary (`vocabulary_empty`) or a too-broad one (`vocabulary_too_broad`) ends the run with that message. There is no approval card; the user rewrites the question, which makes a new scope revision.
- Search: one OpenAlex semantic page (up to 50 records) and OpenAlex keyword pages of 100, read page by page across queries under the keyword cap. Detailed also sends one Semantic Scholar bulk query. No other provider is searched and there is no second search round.
- Chain: one round, OpenAlex only (backward references and the first cited-by page per seed), overlapping the search and cut off before the ranking deadline.
- Ranking embeds the pool and freezes the list.
- Read: Semantic Scholar and Crossref look up missing abstracts for the top N; when Scopus is in scope, configured, its institutional COMPLETE view is confirmed (`complete_view_entitled`) and the lookup budget allows, it completes the abstracts still missing. Each batch of abstracts is screened by two model calls. At most K works get full text; a slot whose work found no text passes to the next work in list order.
- PDF retrieval uses 12 shared slots. At the read cutoff, fetches already running are handed to the background lane and go on; queued works start from the background queue only while fewer than 4 background fetches run.
- When discovery completes, one answer run starts on its own. It answers from the evidence the read stage owned at its cutoff, then queues a separate `answer_review` run.
- Late full text can produce one new answer revision (`max_revisions: 1`). The first answer stays as it was.
- An answer over attached PDFs only (no completed discovery) uses the inspection route: PDF fetch, lexical and semantic passage ranking, then `grounded_answer`.

Providers
- All connectors in `providers/registry.py` stay: OpenAlex, Semantic Scholar, Crossref (lookup only), arXiv, bioRxiv (through OpenAlex), PubMed, IEEE Xplore, Scopus, CORE, SerpApi (supplementary), plus the Zotero collection import. Keys come from the untracked `.env` or the system keychain.
- The research search uses only OpenAlex and Semantic Scholar. Abstract lookups use Semantic Scholar and Crossref, then Scopus under the conditions above. The other connectors stay registered and configurable.

Storage
- One SQLite connection is shared by the API and the worker on the event-loop thread. Writes are short synchronous transactions with no `await` inside, and a UI-visible event is written in the same transaction as the state it describes.
- The schema starts from `storage/migrations/0001_baseline.sql`. A schema change is a new numbered file from `0002_` on. A migration that has been applied is never edited, the baseline included, and tables are not dropped.
- Runtime data (database, PDFs, provider payloads, Codex home) lives in `DEIXIS_DATA_DIR`, never in the repository.

One-time reset (old D261)
- The 77 old migrations were squashed once into the baseline, and the code that kept earlier libraries working was removed. A library written before the reset is refused at startup, and its app data folder is to be deleted. This reset is not repeated.

Limits:
- This entry restates decisions made, reviewed and tested under their old numbers and adds no behavior. The commit that wrote it also removed two method files no step loaded and corrected method and project docs to match the code.
- The tests run on synthetic records and a scripted model. They show workflow behavior, not answer quality or live latency. Live measurements are in STATUS.md and the old log.
- The anchor locator accepts a near match at a provisional 0.9 ratio over one contiguous region.
- Stage deadlines are soft, so a run can exceed its target time.
- The startup refusal of an old library says "newer DEIXIS", which is misleading for an older library (old D261).
