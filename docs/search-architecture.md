# Search architecture

This document traces how a DEIXIS question becomes a set of sources that are ranked, read and answered. It describes the code at commit `8cbedaea` on 17 Oct 2026, under policy `fast_path_v1`, seed rule `seed_pdf_v2` (D3, D6) and ranking version 3. Every box names the function or module that does the work, so the diagrams can be checked against the code. Paths are relative to `backend/deixis/`.

A discovery run always takes the fast path. It has five stages, each on its own clock with a soft deadline: plan, search, ranking, read and answer. When a discovery run completes, an answer run is queued automatically, and an answer review run follows it. Full text that arrives after the read cutoff can produce one late revision of the answer. A person can start four more kinds of run on a finished research: follow-up questions, Screen more, snowball rounds and the citation map (section 7).

**Ranking in one sentence.** Several signals each rank the whole pool by themselves, and the ranks are fused, never the raw scores. BM25 is one of those signals. It is not a filter that runs before the embedding, and no signal removes a record (section 4).

## 1. Runs end to end

```mermaid
flowchart TD
    Q["Question (scope revision)"] --> D

    subgraph D["discovery run · flow._discovery"]
        direction TB
        P["Plan stage"] --> S["Search stage"]
        S --> R["Ranking stage<br/>(small_batch.execute)"]
        R --> RD["Read stage<br/>(fast_read.execute)"]
    end

    D -->|"run_completed → intent.after_discovery"| INT{"research intent"}
    INT -->|"answer"| A["answer run · fast_answer.auto_answer → answer"]
    INT -->|"table / compare"| TB["study table instead of an answer"]
    A -->|"fast_answer.after_answer"| AR["answer_review run · fast_answer.review"]
    A -->|"report_pipeline.after_answer<br/>(DEIXIS_STUDY_TABLE=auto)"| ST["study table chain"]
    A -->|"late_revision.schedule"| LW["late revision waits for background full text"]
    RD -->|"works without text at cutoff"| BG["background PDF fetch · background_fetch"]
    BG --> LW
    LW -->|"at most 1 revision"| LR["fulltext_adjudication run, then answer run<br/>(late_revision.advance → revision_plan)"]

    ATT["Attached PDFs only, no discovery"] --> INS["answer run · _inspect → _generate_answer<br/>(arXiv source and Mathpix formula readers on this path)"]

    D -.->|"person-started, section 7"| PS["followup_answer · screen_more · snowball · citation_map"]
```

`flow._execute_run` dispatches every run kind. The ranking and read stages run inside `small_batch.execute`, and `_discovery` has no separate read call. Under the `papers`, `table` and `compare` intents the budget sets `auto_answer: false`, so no answer is queued (`fast_path.py`).

## 2. Plan stage

Code picks the search words. Models only help: they sort the words into blocks, write the query and propose the inclusion criterion. The protocol and its search plan freeze before the first request that fetches results.

```mermaid
flowchart TD
    Q["question + language hint + key terms"] --> SM["_seed_match (seeded runs only, see 2a)"]
    SM --> UP{"saved search plan? (D12)"}
    UP -->|"yes"| USQ["_user_search_query<br/>the person's blocks replace model query,<br/>labels and criterion proposals"]
    USQ -->|"a block with no searchable term"| UPF(["fail: user_plan_unsearchable"])
    USQ --> SR
    UP -->|"no"| W["question_words.extract (code)"]
    W -->|"not English, no key terms"| KT(["pause: key_terms_needed"])
    W --> VL["3 × vocabulary_labels (model, optional)<br/>sort words into blocks, majority 2 of 3"]
    VL --> VB["vocabulary_rules.build_vocabulary<br/>OpenAlex count probes per term"]
    VB --> QC["query_compiler.compile_block_queries"]
    QC --> SQ["search_query (model, 1 call + repair)<br/>DEIXIS_SEARCH_QUERY=model (default) or code"]
    SQ -->|"call fails / empty block"| SQF(["pause: search_query_failed<br/>(code query only if the person picks it)"])
    SQ --> SR["_source_routing<br/>≤ 1 OpenAlex request: gate query → field distribution → providers"]
    SQ -.-> CHK
    SR -.-> CHK{"_searchable"}
    CHK -->|"no terms"| VE(["fail: vocabulary_empty"])
    CHK -->|"gate count too high"| VTB(["fail: vocabulary_too_broad"])
    SR --> CR["3 × criterion_proposal (model, optional)<br/>vote the inclusion criterion"]
    CR --> AP["_approval → unattended (user_edited for a saved plan)"]
    AP --> BP["fast_search.build_plan + plan_words"]
    BP --> FZ[["protocol:freeze<br/>protocol + fast_path_search plan + hash"]]
```

Several steps are skipped when there is nothing for them to do:

- The vocabulary labels are skipped for a saved plan, for key terms the person typed, or when there are no phrases or more than 40.
- The query step is skipped when the person gave key terms. A query that an earlier run already wrote for the same scope revision is reused.
- The criterion proposals are skipped for a saved plan. A criterion that is already frozen for the same question is reused.
- Routing marks providers the person left out of a saved plan as `excluded_by_user`. OpenAlex cannot be left out.

## 2a. Seed PDFs (optional, `seed_pdf_v2`, D3 and D6; one seed behaves as D2)

The person's own PDFs guide the search. There can be up to five, and uploaded files count the same as Zotero or library PDFs. Seeds need the "Files + academic search" source scope.

- `store.seed_candidates` decides which sources can be seeds.
- `store.set_seeds` freezes them, in order, into a new scope revision with a bounded reading of each: four passages and 5,600 characters in all, split evenly across the seeds.
- With more than five candidates, the five that share the most words with the question are taken.
- Changing the seeds drops a saved search plan.

The first step of the plan stage is `_seed_match`, which looks up which OpenAlex work each PDF is. The protocol freezes the answers, and later steps read them only from the protocol. A run that started under `seed_pdf_v1` finishes under v1.

```mermaid
flowchart TD
    PDF["uploads + Zotero/library PDFs<br/>store.set_seeds → seeds[] (new scope revision)"] --> ST{"seed_status ready?<br/>(every seed)"}
    ST -->|"missing / stale"| SU(["pause: seed_unavailable"])
    ST -->|"ready"| M["_seed_match (first step of the plan)"]

    subgraph M2["seed_match: at most 1 + n OpenAlex lookups"]
        direction TB
        DOI["1. one works_by_dois for all seeds:<br/>DOIs on pages 1–2 + Zotero record DOIs<br/>(incomplete reply = failed)"]
        REC{"record DOI: one work, record title,<br/>title at the head of the first page with text?"}
        RULE{"exactly one work whose title<br/>(≥ 4 words) stands at the head of page 1?"}
        SEMQ["2. per undecided seed: one semantic search<br/>with the head of pages 1–2"]
        DOI --> REC
        REC -->|"no"| RULE
        RULE -->|"no decision"| SEMQ
        SEMQ --> RULE
    end
    M --> M2
    REC -->|"yes"| MATCH["matched: OpenAlex id, title, abstract, references"]
    RULE -->|"yes"| MATCH
    RULE -->|"no / lookup failed"| NOM["not matched: first-page text only"]

    MATCH --> CTX[["seed contexts, frozen in the protocol"]]
    NOM --> CTX

    CTX --> U1["search_query model reads every seed excerpt"]
    CTX --> U2["one OpenAlex semantic request per seed with text,<br/>top 25 each (D6); the question's own request stays unseeded"]
    CTX -->|"matched only"| U3["chain seeds 0.. in seed order (fast_chain.pdf_seeds)"]
    CTX --> U4["ranking: seeds count as verified seeds for TF-IDF and graph;<br/>graph rule seed_max_v2 scores each record against its nearest seed PDF;<br/>a seed never scores against its own OpenAlex copy"]
```

## 3. Search stage (chain and embedding run alongside)

Three things run at once: the search requests, one round of the citation chain, and an embedding consumer that embeds records as they arrive. Each one stops at its stage cutoff.

The fast path searches only OpenAlex, plus Semantic Scholar in Detailed. The registry also holds IEEE Xplore, Scopus, PubMed, Crossref, arXiv, bioRxiv, CORE and SerpAPI. Planned queries for those providers are dropped with the reason `openalex_only`, or marked `excluded` when the person left them out. Crossref, Semantic Scholar and Scopus come back later only to look up abstracts (section 5).

```mermaid
flowchart TD
    FZ[["frozen search plan"]] --> SEM

    subgraph SEARCH["fast_search.execute"]
        direction TB
        SEM["request 0: OpenAlex semantic<br/>one page, top 50, English question sentence"]
        SEM --> SS["seed_semantic (seeded v2 runs):<br/>one OpenAlex semantic request per seed, top 25"]
        SS --> KW["OpenAlex keyword queries<br/>pages of 100, round-robin across queries"]
        SEM --> S2["Detailed only: Semantic Scholar /paper/search/bulk<br/>one page, ≤ 500 records (taken off the keyword cap)"]
        KW --> STOP{"record cap reached<br/>or search deadline?"}
        STOP -->|"no"| KW
        STOP -->|"yes"| CLOSE["close_queries: record_cap / deadline / exhausted"]
    end

    SEM -->|"chain.initial()"| CH
    subgraph CH["fast_chain.Round (OpenAlex only, 5 requests in flight)"]
        direction TB
        SEEDS["seeds: seed PDFs' works first (if matched),<br/>then semantic page results<br/>(skipping verified seeds and duplicates)"] --> BK["backward: referenced works, batches of 50"]
        SEEDS --> FW["forward: works citing a seed, 25 each"]
        FB["fallback at search close (if seeds < chain_seeds):<br/>rank the pool now with ranking.rank_pool,<br/>top up seeds from that fused order"] --> BK
        FB --> FW
    end

    SEM --> EMB
    KW --> EMB
    S2 --> EMB
    CH --> EMB
    EMB["fast_embedding.Consumer<br/>embeds title + abstract of each work as it lands;<br/>unembedded at cutoff → left out of similarity"]

    CLOSE --> POOL[("candidate pool<br/>keyword records + chain heads, merged by DOI into works")]
    CH --> POOL
```

The embedding providers are listed in `documents/embeddings.py`: Gemini, OpenAI, Voyage, Cohere, Ollama, LM Studio, the built-in model and off. The built-in model runs in llama.cpp from a pinned GGUF catalog in `documents/builtin_catalog.py`, which holds Qwen3 Embedding 0.6B, 4B and 8B and BGE-M3 (D90). The embedding query is the question's English sentence.

## 4. Ranking stage

The ranking stage decides the order in which works are read. It removes nothing and decides nothing. Code computes every signal. The one model-like step is the optional reranker, and it changes only the order.

```mermaid
flowchart TD
    POOL[("pool: one head version per work")] --> DR["Consumer.drain + flow._source_similarity"]
    DR --> RK["flow._ranking → ranking.rank_records → rank_pool"]

    subgraph SIG["each signal ranks the whole pool on its own"]
        direction TB
        B["bm25: BM25 on title + abstract"]
        BL["blocks: concept-block hits"]
        TF["tfidf: cosine to verified seeds<br/>(user-included works + seed PDFs; off without seeds)"]
        G["graph: bibliographic coupling + direct citation<br/>(off when no seed has references)"]
        J["joint: comparison questions only<br/>records naming ≥ 2 task terms together"]
        E["embedding: similarity to the question<br/>(off without an embedding model)"]
    end

    RK --- SIG
    SIG --> F["fuse by rank (RRF, k = 60)<br/>a missing signal ranks last, still counted;<br/>ties broken by record id"]
    F --> RP["small_batch.replay (ranking version 3)<br/>2nd graph pass from the fused top, + cites signal;<br/>places 21–500 re-fused, graph and cites weigh 2;<br/>the fused top 20 stays first"]
    RP --> RR{"reranker on in Settings?"}
    RR -->|"no"| FL
    RR -->|"yes"| RRK["small_batch.rerank_list<br/>first N × pool factor records (1×/2×/4×, default 4×, ≤ 400),<br/>user-included works left out;<br/>question + title + abstract → scores"]
    RRK -->|"failure / timeout"| FUSED["step failed, fallback: fused_order<br/>(no other reranker is tried)"]
    RRK --> FL
    FUSED --> FL
    FL[["small_batch.freeze_list<br/>frozen ranked list + manifest hash<br/>user-included works first"]]
```

**Signals.** `ranking.CODE_SIGNALS` holds `bm25`, `blocks`, `tfidf`, `graph` and `joint`, and `SIGNALS` adds `embedding`. A signal that cannot run is recorded with a reason, such as `no_verified_seeds`, `not_a_comparison` or `no_stored_similarity`. The ranking still uses the signals that did run.

The `joint` signal applies only when the question asks for a comparison. Code checks for this from words in the question or its English sentence, such as "compare", "versus", "between" or "than". Records that name two or more of the task block's terms together score higher, and a term counts more when it is rarer in the pool.

**Fusion.** Each record's score is the sum of `1/(60 + rank)` over its signals. `fused_code` is the order from the code signals alone. `fused` is the order from every signal that ran, and screening follows it.

**Replay.** The frozen list is computed again from the stored manifest by `small_batch.replay`, so it never depends on live code or on set order. Ranking version 3 adds two things on top of `rank_pool`:

- A second graph pass whose seeds come from the fused top, not from the keyword top. A seed's citation of a record counts twice.
- A `cites` signal: the logarithm of the OpenAlex cited-by count.

Places 21 to 500 are then fused again, with graph and cites weighted twice. The original top 20 stays in front.

**Reranker** (D88, D89, D90). It is off by default. When it is on, it scores the first `N × pool factor` records of the fused order, so it decides which records fall above the read cutoff, not only their order within it. It is sent the original question with each record's title and abstract, and an item over 20,000 characters is refused, not cut. It waits for the shorter of its own time limit (default 180 s) and what is left of the ranking stage.

A reranker that fails or runs out of time ends the step as `failed`, with a reason and `fallback: fused_order`. The list keeps the fused order, and no other reranker is tried. If a person's include moved the head of the list during the request, the scores are not applied (`candidates_changed`).

The available rerankers are the built-in model, Voyage, Cohere, Jina and ZeroEntropy. The built-in catalog holds Qwen3 Reranker 0.6B, 4B and 8B and BGE Reranker v2 M3, all running in llama.cpp. The step `rerank:v1:list` stores the provider, model, candidates, scores and what was sent, and the listing's `reranker` block shows the outcome.

## 5. Read stage

Only the top N of the frozen list is read. Abstract screening never includes a source, because inclusion needs a full-text read. At most K works get full text before the cutoff, and the rest go to the background fetch queue.

```mermaid
flowchart TD
    FL[["frozen list"]] --> TOPN["top N works"]
    TOPN --> SS["flow._second_sources → lookups.ask_second_sources<br/>abstract lookups for DOI records without an abstract:<br/>Semantic Scholar, then Crossref, then Scopus<br/>(in scope, configured, COMPLETE view, in budget); ≤ 200 requests"]
    SS --> FR

    subgraph FR["fast_read.execute (one loop until the read deadline)"]
        direction TB
        AB["abstract_stage<br/>2 model reads per batch of 20, no include outcome"]
        SEL["fast_read.selected: admit up to K works in list order;<br/>a work with no text, or an unconfirmed PDF identity,<br/>gives its slot away (D60)"]
        FE["fetch full text (12 slots)<br/>documents.acquisition / fetch"]
        FA["fulltext_adjudication (model, 2 calls, rule split_v1, D76)<br/>call 2 sees the passages call 1 did not;<br/>a part stands on a code-verified quote from the call that saw it;<br/>a part both calls saw must agree"]
        AB --> SEL
        SEL --> FE --> FA
    end

    FR --> CUT[["read cutoff · small_batch:…:fast:close<br/>selected_work_ids, not_screened_at_cutoff,<br/>fulltext_after_cutoff, screened counts, k_short_reason"]]
    CUT -->|"freeze_cutoff"| SNAP[["fast_path:v1:cutoff snapshot<br/>the evidence the answer may use"]]
    CUT -->|"works still without text"| BG["background_fetch.enqueue (4 slots, yield to foreground)"]
```

The adjudication decides each part of the criterion on its own:

- A part is included only when every part has a verified quote.
- An unverified quote gives `include_quote_unverified`, which goes to the person's queue.
- A verified quote set against an "absent" from a call that saw the same text gives `fulltext_runs_disagree`.
- A work is excluded only when both calls say absent.

The abstract stage sets aside survey-titled works by code (`code_decided`, D69).

## 6. Answer, review and late revision

```mermaid
flowchart TD
    SNAP[["cutoff snapshot"]] --> IP["fast_answer.input_plan"]
    IP --> PSG["full-text passages: passages_fts BM25 on the question terms,<br/>fused (RRF) with criterion passages;<br/>no semantic passage search on this path<br/>(semantic_retrieval: skipped: fast_path_lexical)"]
    PSG --> ORD["result_passages.order: slot 1 = most result-dense passage (D84),<br/>formula passage on formula questions (D56), reference lists last"]
    ORD --> ALLOC["small_batch.allocate: breadth first, ≤ 6 per source,<br/>limit 16 / 48 / 80 passages (Quick / Standard / Detailed)"]
    ALLOC -->|"no passages"| NE(["answer: no_evidence"])
    ALLOC --> GA["_generate_answer (model)<br/>citation handles → record IDs → contract checks;<br/>every given work cited or left out with a reason (D80)"]
    GA -->|"given works unaccounted"| COV["one coverage rewrite (D83)<br/>published only if it keeps the answer and covers more"]
    GA --> ANS[("answer revision 1")]
    COV --> ANS
    ANS --> REV["answer_review run (1 model step, ≤ 2 calls)<br/>never changes the answer"]
    ANS --> LS["late_revision.schedule<br/>selected works answered from abstract only"]
    BG["background full text arrives"] --> LS
    LS --> LA["fulltext_adjudication run (late)"]
    LA --> LRP["answer run with late_revision_id<br/>late_revision.revision_plan"]
    LRP --> ANS2[("answer revision 2 (max 1 late revision)")]
```

The answer's passages come from BM25 and fusion with the criterion passages. No embedding is used at this step. A person-started answer can also read works that Screen more or a snowball round screened after the cutoff, as abstract-based evidence (D9). Automatic answers and late revisions leave those works out. A work that a late full-text read excluded stays out of later answers and follow-ups (D44). A late revision waits while a newer question revision is still unused and can be withdrawn (D67).

The arXiv LaTeX source reader (D36) and the Mathpix formula reader (D40) are not on this path. They run for attached-PDF answers and for study tables.

## 7. Person-started runs on a finished research

None of these runs is part of the automatic chain. A person starts each one from the interface.

```mermaid
flowchart TD
    DONE[("completed discovery + answer")]

    DONE --> FU["followup_answer · followup.py<br/>no search, stored passages only"]
    FU --> FUP["pool = latest answer's evidence (D49)<br/>priority: latest answer's passages ≤ ¼,<br/>chosen table values (D53), total ≤ ½ (D64)"]
    FUP --> FUR["rest: BM25 (passages_fts) + semantic ranking,<br/>fused by RRF (fuse_rankings); breadth first"]
    FUR --> FUA["answer (model); if not answered:<br/>round 2 with ≤ 3 model phrases re-ranks pool + reserve (D50)"]

    DONE --> SM["screen_more · screen_more.py (D9)<br/>next 40 unscreened works of the frozen list<br/>(or of a snowball round's list)"]
    SM --> SMA["abstract_stage, 2 reads per batch, nothing included"]

    DONE --> SB["snowball · snowball.py (D91)<br/>≤ 3 rounds, ≤ 10 chosen seeds with an OpenAlex id"]
    SB --> SBR["OpenAlex backward (≤ 10 requests) +<br/>forward (≤ 20 requests of 100, newest first)"]
    SBR --> SBL["admissions ledger (migration 0003):<br/>new / seen / existing / ambiguous / no_record / unresolved"]
    SBL --> SBS["round list: gate-block match, linking seeds, arrival;<br/>abstract_stage on ≤ 80 works, lexical_exclusion off;<br/>nothing included"]

    DONE --> CM["citation_map · citation_map_run.py (D42)<br/>fills OpenAlex ids and reference lists, no model call"]
    CM -.->|"resolutions count as OpenAlex identity"| SB
```

A follow-up question is the one place where embeddings rank passages. Its lexical BM25 ranking and its semantic ranking are fused by RRF. When the follow-up's own words match nothing, it falls back to the research question's words.

In a snowball round the abstract stage runs with `lexical_exclusion=False`. The rule that sets aside a record naming neither gate block is off, because the round's works came from citations of seeds the person chose. A round's works reach a later answer only after the person includes them.

## Mode numbers

The numbers come from `fast_path.MODES` and are frozen into each run's budget by `fast_path.freeze_budget`. Stage times are soft deadlines in seconds. Time a stage leaves unused carries over to the next one. Runs on a local model have no read or answer deadline.

| Mode | plan / search / ranking / read / answer (s) | N read | K full text | keyword record cap | chain seeds | backward / forward requests | answer passages |
|---|---|---|---|---|---|---|---|
| Quick | 30 / 30 / 30 / 60 / 30 | 25 | 10 | 450 | 10 | 2 / 2 | 16 |
| Standard | 30 / 45 / 60 / 120 / 45 | 50 | 20 | 1000 | 20 | 4 / 8 | 48 |
| Detailed | 45 / 90 / 120 / 270 / 75 | 100 | 40 | 2000 (1500 OpenAlex + 500 S2) | 30 | 8 / 16 | 80 |

Other frozen numbers:

- OpenAlex semantic top: 50
- Backward and forward page sizes: 50 and 25
- Chain requests in flight: 5
- Embedding threads: 4
- Fetch slots: 12, background slots: 4
- Arrival margin: 5,000 ms

## What makes it resumable

Every step is a `run_steps` row keyed by `operation_key`. A step that already `succeeded` returns its stored output, so pause, resume and crash recovery repeat no model call and no provider request. A finished rerank, whether it succeeded or failed, is not asked again. A coverage call that was already sent is recovered from its own sessions.

Four things are each frozen once and read back on resume: the protocol, the search plan, the ranked list with its manifest, and the read cutoff. `_checkpoint` stops a run on pause, on cancel, or when a newer scope revision appears. On start, `worker.py` marks half-finished work `outcome_unknown` or `paused` instead of retrying it, and `background_fetch.recover` re-queues running fetches.

## Where to look

| Part | Code |
|---|---|
| Run dispatch, discovery orchestration | `workflow/flow.py` (`_execute_run`, `_discovery`) |
| Policy, mode numbers, stage clock | `workflow/fast_path.py` |
| Seed PDF match | `workflow/seed_match.py`, `flow._seed_match`, `store.set_seeds`, `store.seed_candidates` |
| Saved search plan | `flow._user_search_query`, `workflow/user_plan.py` |
| Search requests | `workflow/fast_search.py` |
| Citation chain round | `workflow/fast_chain.py` |
| Embedding during search | `workflow/fast_embedding.py`, `documents/embeddings.py`, `documents/builtin_catalog.py` |
| Ranking signals | `workflow/ranking.py` |
| Replay, reranker, frozen list, read entry | `workflow/small_batch.py`, `documents/rerankers.py` |
| Second-source abstracts | `workflow/lookups.py` |
| Abstract screening, full-text rule | `workflow/abstract_stage.py`, `workflow/adjudication.py` |
| Read window, K admission, cutoff | `workflow/fast_read.py` |
| Full-text fetch | `documents/acquisition.py`, `documents/fetch.py` |
| Answer, review | `workflow/fast_answer.py`, `workflow/result_passages.py`, `workflow/formula_passages.py` |
| Late full text and revision | `workflow/background_fetch.py`, `workflow/late_revision.py` |
| Follow-up questions | `workflow/followup.py` |
| Screen more, snowball, citation map | `workflow/screen_more.py`, `workflow/snowball.py`, `workflow/citation_map_run.py` |
| Restart recovery | `workflow/worker.py` |
| Providers and query rules | `providers/` (`registry.py`, `query_rules.py`) |
