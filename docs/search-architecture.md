# Search architecture

How a DEIXIS question becomes a ranked, read and answered set of sources, as the code stands on 11 Oct 2026 at commit `0566682` (policy `fast_path_v1`, seed rule `seed_pdf_v1`). Every box names the function or module that does the work, so the diagrams can be checked against the code.

A discovery run always takes the fast path. It moves through five clocked stages (plan, search, ranking, read, answer), each with a soft deadline. When it completes, an answer run is queued automatically, then an answer review run. Full text that arrives after the read cutoff can produce one late answer revision.

## 1. Runs end to end

```mermaid
flowchart TD
    Q["Question (scope revision)"] --> D

    subgraph D["discovery run · flow._discovery"]
        direction TB
        P["Plan stage"] --> S["Search stage"]
        S --> R["Ranking stage"]
        R --> RD["Read stage"]
    end

    D -->|"run_completed → fast_answer.auto_answer"| A["answer run · fast_answer.answer"]
    A -->|"fast_answer.after_answer"| AR["answer_review run · fast_answer.review"]
    A -->|"late_revision.schedule"| LW["late revision waits for background full text"]
    RD -->|"works without text at cutoff"| BG["background PDF fetch · background_fetch"]
    BG --> LW
    LW -->|"at most 1 revision"| LR["answer run (late_revision.revision_plan)"]

    ATT["Attached PDFs only, no discovery"] --> INS["answer run · inspection → grounded_answer"]
```

## 2. Plan stage

Code picks the search words; models only help sort them, write the query and propose the criterion. The protocol, with its search plan, freezes before the first request that fetches search results.

```mermaid
flowchart TD
    Q["question + language hint + key terms"] --> SM["_seed_match (seeded runs only, see 2a)"]
    SM --> W["vocabulary.extract (code)<br/>question_words"]
    W -->|"not English, no key terms"| KT(["pause: key_terms_needed"])
    W --> VL["3 × vocabulary_labels (model, optional)<br/>sort words into blocks"]
    VL --> VB["vocabulary_rules.build_vocabulary<br/>OpenAlex count probes per term"]
    VB --> QC["query_compiler.compile_block_queries"]
    QC --> SQ["search_query (model, 1 call + repair)<br/>DEIXIS_SEARCH_QUERY=model"]
    SQ -->|"call fails / empty block"| SQF(["pause: search_query_failed"])
    SQ --> SR["_source_routing<br/>≤ 1 OpenAlex request: gate query → field distribution → providers"]
    SR -->|"no terms"| VE(["fail: vocabulary_empty"])
    SR -->|"gate count too high"| VTB(["fail: vocabulary_too_broad"])
    SR --> CR["3 × criterion_proposal (model, optional)<br/>vote the inclusion criterion"]
    CR --> AP["_approval → recorded as unattended"]
    AP --> BP["fast_search.build_plan"]
    BP --> FZ[["protocol:freeze<br/>protocol + fast_path_search plan + hash"]]
```

## 2a. Seed PDF (optional, `seed_pdf_v1`, D2)

The user can pick one of their own PDFs as a seed. This needs the "Files + academic search" source scope. `store.set_seed` freezes a bounded reading of the PDF in a new scope revision: the first two pages plus the pages that share the most words with the question. Before anything else in the plan stage, `_seed_match` looks up which OpenAlex work the PDF is. The protocol freezes that answer, and later steps read it only from the protocol.

```mermaid
flowchart TD
    PDF["user picks a PDF they added<br/>store.set_seed → seed_snapshot (new scope revision)"] --> ST{"seed_status ready?"}
    ST -->|"missing / stale"| SU(["pause: seed_unavailable"])
    ST -->|"ready"| M["_seed_match (first step of the plan)"]

    subgraph M2["seed_match: at most 2 OpenAlex lookups"]
        direction TB
        DOI["1. DOIs named on pages 1–2 → works_by_dois"]
        SEMQ["2. only if no DOI matched: one semantic search<br/>with the head of page 1"]
        RULE{"exactly one work whose title<br/>(≥ 4 words) stands at the head of page 1?"}
        DOI --> RULE
        SEMQ --> RULE
    end
    M --> M2
    RULE -->|"yes"| MATCH["matched: OpenAlex id, title, abstract, references"]
    RULE -->|"no / lookup failed"| NOM["not matched: first-page text only"]

    MATCH --> CTX[["seed context, frozen in the protocol"]]
    NOM --> CTX

    CTX --> U1["search_query model reads the seed excerpt"]
    CTX --> U2["semantic query = question + seed text<br/>(match abstract, or title + PDF excerpt)"]
    CTX -->|"matched only"| U3["chain seed 0 (fast_chain.pdf_seed)"]
    CTX --> U4["ranking: seed counts as a verified seed<br/>for TF-IDF and citation-graph signals,<br/>never scores against its own OpenAlex copy"]
```

## 3. Search stage (with chain and embedding running alongside)

Three things run at once: the search requests, one citation-chain round, and an embedding consumer that embeds records as they arrive. All three stop at their stage cutoffs.

```mermaid
flowchart TD
    FZ[["frozen search plan"]] --> SEM

    subgraph SEARCH["fast_search.execute"]
        direction TB
        SEM["request 0: OpenAlex semantic<br/>one page, top 50, English question sentence<br/>(+ seed PDF text when seeded)"]
        SEM --> S2["request 1 (Detailed only): Semantic Scholar /paper/search/bulk<br/>one page, ≤ 500 records"]
        SEM --> KW["requests 1..n: OpenAlex keyword queries<br/>pages of 100, round-robin across queries"]
        KW --> STOP{"record cap reached<br/>or search deadline?"}
        STOP -->|"no"| KW
        STOP -->|"yes"| CLOSE["close_queries: record_cap / deadline / exhausted"]
    end

    SEM -->|"chain.initial()"| CH
    subgraph CH["fast_chain.Round (OpenAlex only)"]
        direction TB
        SEEDS["seeds: seed PDF's work first (if matched),<br/>then semantic page results<br/>(skipping verified seeds and duplicates)"] --> BK["backward: referenced works, batches of 50"]
        SEEDS --> FW["forward: works citing a seed, 25 each"]
        FB["fallback at search close: top up seeds<br/>from the fused ranking if too few"] --> BK
        FB --> FW
    end

    SEM --> EMB
    KW --> EMB
    S2 --> EMB
    CH --> EMB
    EMB["fast_embedding.Consumer<br/>embeds new records as they land;<br/>unembedded at cutoff → left out of similarity"]

    CLOSE --> POOL[("candidate pool<br/>records merged by DOI into works")]
    CH --> POOL
```

## 4. Ranking stage

Ranking is code only. It orders the pool for reading; it removes nothing and decides nothing.

```mermaid
flowchart LR
    POOL[("pool: one head version per work")] --> DR["Consumer.drain + _source_similarity"]
    DR --> RK["_ranking → ranking.rank_records"]

    subgraph SIG["signals, fused by rank (RRF), never raw scores"]
        direction TB
        B["BM25 on title + abstract"]
        BL["concept-block hits"]
        TF["TF-IDF cosine to seeds<br/>(user-included works + seed PDF)"]
        G["citation graph: coupling + direct citation"]
        E["embedding similarity (optional)"]
    end

    RK --- SIG
    RK --> FL[["small_batch.freeze_list<br/>frozen ranked list + manifest hash<br/>user-included works first"]]
```

## 5. Read stage

Only the top N of the frozen list is read. Abstract screening never includes a source; inclusion needs a full-text read. At most K works get full text before the cutoff; the rest go to the background fetch queue.

```mermaid
flowchart TD
    FL[["frozen list"]] --> TOPN["top N works"]
    TOPN --> SS["_second_sources: abstract lookups<br/>Semantic Scholar, Crossref (then Scopus if in scope, configured, COMPLETE view, in budget)"]
    SS --> FR

    subgraph FR["fast_read.execute (one loop until the read deadline)"]
        direction TB
        AB["abstract_screening<br/>2 model reads per batch, no include outcome"]
        SEL["fast_read.selected: admit up to K works<br/>in list order; a work whose fetch found no text gives its slot away"]
        FE["fetch full text (12 slots)<br/>documents.acquisition / fetch"]
        FA["fulltext_adjudication (model)<br/>include only when both reads agree and quotes are on the page"]
        AB --> SEL
        SEL --> FE --> FA
    end

    FR --> CUT[["read cutoff · small_batch:…:fast:close<br/>selected_work_ids, not_screened_at_cutoff,<br/>fulltext_after_cutoff"]]
    CUT -->|"freeze_cutoff"| SNAP[["fast_path:v1:cutoff snapshot<br/>the evidence the answer may use"]]
    CUT -->|"works still without text"| BG["background_fetch.enqueue (4 slots)"]
```

## 6. Answer, review and late revision

```mermaid
flowchart TD
    SNAP[["cutoff snapshot"]] --> IP["fast_answer.input_plan<br/>breadth-first passages from cutoff-owned evidence"]
    IP -->|"no passages"| NE(["answer: no_evidence"])
    IP --> GA["_generate_answer (model)<br/>citation handles → record IDs → contract checks"]
    GA --> ANS[("answer revision 1")]
    ANS --> REV["answer_review run (model, 2 calls)"]
    ANS --> LS["late_revision.schedule<br/>selected works answered from abstract only"]
    BG["background full text arrives"] --> LS
    LS --> LA["fulltext_adjudication run (late)"]
    LA --> LRP["answer run with late_revision_id<br/>late_revision.revision_plan"]
    LRP --> ANS2[("answer revision 2 (max 1 late revision)")]
```

## Mode numbers

From `fast_path.MODES`, frozen into each run's budget by `fast_path.freeze_budget`. Stage times are soft deadlines in seconds; time a stage leaves unused carries over to the next one.

| Mode | plan / search / ranking / read / answer (s) | N read | K full text | keyword record cap | chain seeds | backward / forward requests |
|---|---|---|---|---|---|---|
| Quick | 30 / 30 / 30 / 60 / 30 | 25 | 10 | 450 | 10 | 2 / 2 |
| Standard | 30 / 45 / 60 / 120 / 45 | 50 | 20 | 1000 | 20 | 4 / 8 |
| Detailed | 45 / 90 / 120 / 270 / 75 | 100 | 40 | 2000 (1500 OpenAlex + 500 S2) | 30 | 8 / 16 |

## What makes it resumable

Every step is a `run_steps` row keyed by `operation_key`. A step that already `succeeded` returns its stored output, so pause, resume and crash recovery repeat no model call and no provider request. The protocol, the search plan, the ranked list and the read cutoff are each frozen once and read back on resume. `_checkpoint` stops a run on pause, cancel or a newer scope revision; `worker.py` marks half-finished work `outcome_unknown` or `paused` on start instead of retrying it.

## Where to look

| Part | Code |
|---|---|
| Run dispatch, discovery orchestration | `backend/deixis/workflow/flow.py` (`_execute_run`, `_discovery`) |
| Policy, mode numbers, stage clock | `workflow/fast_path.py` |
| Seed PDF match | `workflow/seed_match.py`, `flow._seed_match`, `store.set_seed` |
| Search requests | `workflow/fast_search.py` |
| Citation chain round | `workflow/fast_chain.py` |
| Embedding during search | `workflow/fast_embedding.py` |
| Ranking signals | `workflow/ranking.py` |
| Frozen list, read entry | `workflow/small_batch.py` |
| Read window, K admission, cutoff | `workflow/fast_read.py` |
| Answer, review | `workflow/fast_answer.py` |
| Late full text and revision | `workflow/background_fetch.py`, `workflow/late_revision.py` |
| Providers and query rules | `backend/deixis/providers/` (`registry.py`, `query_rules.py`) |
