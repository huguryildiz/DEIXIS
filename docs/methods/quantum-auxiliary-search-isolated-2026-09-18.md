# Isolated survey and cited-paper vocabulary probes

**Status:** opt-in development diagnostics, separate from the frozen B-versus-C query-arm comparison. This question and the IEEE survey target were known before these auxiliary probes. Neither probe changes the product planner, screens studies, or validates recall.

## Survey lane

Run three fixed OpenAlex title-and-abstract queries, each with two pages of at most 100 records: **six logical requests, 600 returned slots maximum**. The queries combine subject phrases from the question with `survey`, `review`, or `taxonomy` wording. Save every raw response and route. A title containing `survey`, `review`, or `taxonomy` is only a provisional genre signal, not a verified publication type. Keep survey records in a separate candidate lane suitable for background reading and later reference mining; do not count them automatically as primary mathematical models. After the run, compare the already known IEEE survey DOI with this lane and the earlier pools.

## One-round cited-paper term lane

Select from the completed `c_feature_guard` pool by a frozen deterministic rule: exact-identity deduplication, nonempty title and abstract, non-survey title, `entanglement` plus at least one of `routing`, `distribution`, `optimization`, `resource allocation`, or `network` in the title, then descending OpenAlex citation count and distinct normalized title. Take the top **three**. Citation count is a selection heuristic, not a quality or relevance verdict. Record the ranked eligible set and selected records before any model call.

Give only the selected titles and abstracts to `gemini-3.5-flash` at medium effort. Request at most four additional technical phrases, each with a source identity and an exact contiguous title/abstract evidence phrase. Reject a proposal if a phrase cannot be located in its cited record, is a reporting label, is too long or syntactically unsafe, or is already an exact term in the existing query arms. Code compiles one `entanglement AND (term1 OR …)` OpenAlex query. Freeze the selected records, proposal, accepted terms, query, hashes, model identity/effort, and budget before calling OpenAlex. Run **one round only**, two pages of at most 100 records: **two logical requests, 200 returned slots maximum**. No model retry or fallback changes the search silently.

Report request failures as partial results, and distinguish returned, exact-identity, DOI, incremental-to-C, screened, and included counts. Post-run checks of known papers are descriptive because those papers informed development. No PDF or citation-graph round runs. Do not use the real DEIXIS library or port `8765`; write raw payloads and results under ignored `.local/` and never write credentials.
