# SW slice 26 — A trial protocol is not an include, and the code query stops welding a verb into a phrase

**Date:** 27 September 2026. **Status:** plan written; Sol r1 (high only) "hazır değil", 2 high findings addressed (last section). A1, B1, C1, D1, E1, F1 önerildiği gibi
(sahip soru sorulmadan ilerlenmesini istedi, 2026-09-27). **Review rule (owner, D105):** Sol (`gpt-6-sol` · high) blocks
only on a **high** finding; at most **3** plan rounds and **4** code rounds. Medium and low findings are fixed or left
with a reason and open no round; a high finding still open after the third plan round or the fourth code round goes to
the owner. **Prompt:** sw-slice26-prompt.md. **Main file:** [sw-status.md](sw-status.md).
**Decision:** D107 (highest today D106; if another slice has taken D107 by the time this one is built, the next free
number). **Migration:** none (highest stays `0055`; reason codes are not a database CHECK, see "What the code does
today"). **Prerequisite:** slice 25a closed (`1627b8e`). **Type:** build. **Implementer:** Opus · high. **Review:** full
(Sol · high, with the rule above): the slice changes when code includes a work, which is the kind of decision the
"Bir tur" section reviews in full. **Plan:** Opus 5.5 · high. **Scope:** SW26 and SW25 only.

**Measurement:** [.local/archive/sw/sw-slice26-plan-2026-09-27/](../local-runs.md#run-archive-sw-sw-slice26-plan-2026-09-27): `protocol_titles.py` → `protocol-titles.json`,
`protocol-titles.txt`; `replay_reading.py` → `replay-reading.json`, `replay-reading.txt`; `verb_split.py` →
`verb-split.json`, `verb-split.txt`. All read stored libraries with `immutable=1` URIs: slice 24a's 14 libraries
([.local/archive/sw/sw-slice24-campaign-2026-09-26-134050/data-*](../local-runs.md#run-archive-sw-sw-slice24-campaign-2026-09-26-134050)) and, for the wider title check, every other `library.sqlite`
under `.local/`. No model call, no provider request, no network. Port 8765 and the live library were not touched. One
M1 Pro, Python 3.12 arm64 through `uv`.

**Goal:** Two defects slice 24a found and slice 25 left open. (1) SW26: the full-text reading included three trial
protocols that report no results, because each run found "body weight" among the outcomes the trial *will* measure and
labelled the outcome part `present`. After this slice a planned measurement does not meet a part about a result: the
method file says so to the model, and code neither includes nor excludes a work whose title names a study protocol without a person;
it goes to the queue with its own question. (2) SW25: the code-built query searched `"time-restricted eating reduce body
weight"`, the question's words run together through a verb. After this slice code cuts such a phrase at the verb before
the block labelling sees it, in a clause the question inverted with an auxiliary. The British/American spelling gap and
OpenAlex's keyless daily budget get a written note, no code.

## What the code does today

Code read on 27 September 2026 at `86bfe9d` (slice 25a's `1627b8e` plus a status commit).

- **The reading method has a future-work rule but no result rule.** `methods/deixis-research/references/fulltext-adjudication.md:5`
  says "What the paper cites, surveys or plans as future work is not something the paper contains." Nothing says that a
  part about a result needs a reported result. A protocol's methods section lists its outcomes ("The primary outcomes,
  including changes in weight and body mass index (BMI), will be assessed weekly"), and both runs quoted exactly that
  as `present` for the part "body weight outcome" (`includes-tre.json` of the slice 25 plan; the PCOS protocol, runs 1
  and 2). The file's text is pinned by `tests/test_skill_package.py:83-89`.
- **Code includes on agreement alone.** `adjudication.verdict` (`backend/deixis/workflow/adjudication.py:264-275`) gives
  `include` when every label is `present`; `combine` (`:288-305`) turns two such runs with every quote verified into
  `all_parts_verified`. `flow._close_adjudication` (`backend/deixis/workflow/flow.py:3815-3868`, `combine` at `:3852`)
  writes that code on the read version through `_write_adjudication_codes` (`:3870`). Nothing reads the title or the
  kind of paper. `FRESH_MODEL_CODES` (`adjudication.py:30-38`) lists the codes this stage writes; a fresh one keeps
  the work out of the next reading plan.
- **Reason codes live in code, not in the database.** `stage_decisions.reason_code` is free `TEXT NOT NULL`; only
  `stage`, `outcome` and `decided_by` carry CHECKs (`storage/migrations`, schema read from a 24a library). The code
  table is `backend/deixis/domain/reason_codes.py:39-86`; `queue.QUEUE_CODES` (`workflow/queue.py:36`) and
  `flow_counts` read it, so a new `human_queue` code is listed by the queue without further wiring. `stage_decisions`
  has a `note` column. A new code therefore needs no migration.
- **The queue asks one question per row, by kind.** `KIND_OF` (`workflow/queue.py:39-43`) maps a code to a kind;
  `_kind` (`:210-215`) splits `part_without_evidence` into `confirm_absent` and `find_part`; `_question` (`:194-207`)
  names the first part the runs did not settle, and returns `None` when every part is settled. The screen writes the
  question from `row.question` or, for a row without one, by kind (`apps/web/src/HumanQueue.tsx:409-414`); a row with
  no question and an unknown kind falls through to "You decided this work under an earlier question", which would be
  wrong for a new kind. Kind and reason texts: `apps/web/src/labels.ts:294-311`; the kind type: `apps/web/src/api.ts:449`.
- **Phrase extraction splits only at function words, cue words and punctuation.** `domain/vocabulary.py::_phrases`
  (`:155-189`) collects the words between two splits as one phrase. A verb is neither a function word nor a cue, so
  "does time-restricted eating reduce body weight compared with …" yields the phrase `time-restricted eating reduce
  body weight`. The word lists are `domain/vocabulary_words.py` (lists only; its docstring says no field term may be
  added). Question frames that end in an auxiliary ("how does", "how do", "why does" …) are stripped before splitting
  (`_strip_frames`, `:135-143`; `QUESTION_FRAMES`, `vocabulary_words.py:26-31`), so the auxiliary is not among the
  tokens then. The block labelling (SW17, D74) may only label the phrases code gives it, never split them
  (`workflow/vocabulary.py:51-103`, `flow._vocabulary_labels`, `flow.py:800-836`).
- **The code query is searched beside the model's query** (D92). In all five medicine `sw` researches the code query's
  task block was `("time-restricted eating reduce body weight" OR "usual diet" OR unrestricted)` (stored `vocabulary`
  step of `qtre-sw-standard-r1`; `detailed-r1` the same phrase with `"unrestricted eating"`); the labelling put the
  welded phrase in `task` in 3 of 3 runs, because it may not split it.
- **Spelling.** No code writes a spelling variant. `randomised controlled trials` was labelled `exclusion` in
  `qtre-sw-standard-r1` (2 of 3 runs) and `setting` in `qtre-sw-detailed-r1`, where it entered the query in British
  spelling only.
- **OpenAlex without a key.** `OPENALEX_API_KEY` is optional (`docs/product/providers.env.example:6`, no comment);
  `openalex.search_works` sends it as a bearer token when set (`providers/openalex.py:134`). After slice 24a's
  campaign OpenAlex answered 429 with `x-ratelimit-remaining: 0` and a reset in about 8.4 h (campaign `ledger.jsonl`
  line 382); no product search in the campaign was refused.

## Numbers we have

All from stored data on one M1 Pro; the model behind the stored runs is `gpt-5.6-luna` · medium (slice 24a). A stored
run is one run.

1. **The three protocols** (slice 24a, `qtre-sw-detailed-r1`; the other four medicine `sw` researches did not include
   them). Their titles: "… in postmenopausal women with overweight or obesity: A study protocol", "… polycystic ovary
   syndrome: A randomized controlled trial study protocol", "… incipient fatty liver disease: protocol for the ENSATI
   randomized controlled parallel groups trial." In every stored run the outcome part was `present` on a planned
   outcome ("will be assessed weekly"; "The sample size calculation variable is the percentage of weight lost";
   "Secondary Outcomes: … body weight and composition"). A tense check on the quote would catch 1 of the 3 (only the
   PCOS quote says "will"); the title catches 3 of 3.
2. **The title rule** (`protocol-titles.txt`). The proposed rule (decision 2.2) on the current full-text decisions:
   - medicine, slice 24a's 7 libraries: flags **3 of 17** unique included works (unique by DOI, else by normalised title; the
     script's count by title gives the same 17 and 3), exactly the three protocols (3 of 30
     include rows); among all 574 stored full-text decisions it flags 42 rows, 30 unique titles, and every one of the
     30 reads as a trial protocol or a "rationale and design" paper (read by this plan session from the titles; one
     reader, a model, not a human check). Five read rows whose titles hold the word "protocol" but are results papers
     ("per-protocol analysis of a 3-month randomized clinical trial", "Mediterranean-Type Time-Restricted Feeding
     Protocol … A Randomised Controlled Trial", "(16/8 protocol)") are not flagged.
   - quantum, slice 24a's 7 libraries: **0 of 56** unique includes (by DOI, else normalised title), 0 of 737 decisions, 0 of 15,822 pool titles.
   - every other stored library under `.local/` (55 quantum, 15 packet, 12 other; slices 13–25): 0 of 73 unique quantum
     includes, 0 of 4 packet includes; one title in all their pools is flagged (a COVID-19 survey protocol in three
     pools).
   - For comparison, the bare word `protocol` flags 3 of 56 quantum includes and 1 of 4 packet includes
     ("Hybrid routing protocol for quantum network …", "An Energy-Efficient Link Layer Protocol …"); `protocol for the`
     without the trial anchor flags 4 quantum reading rows ("REDiP: Ranked Entanglement Distribution Protocol for the
     Quantum Internet").
3. **Replay of the reading's code** (`replay-reading.txt`). For the 10 `sw` libraries of slice 24a, every current
   full-text decision this stage wrote (455: quantum 304, medicine 151) was recomputed from its two runs' stored
   proposals (`model_proposals`) with the product's own `run_view` and `combine`: **455 of 455** equal the stored code.
   With the title rule on top, **3 change** (the three protocols, `all_parts_verified` → `protocol_title`, all in
   `qtre-sw-detailed-r1`), 0 in quantum, 0 elsewhere. None of the three is cited in its research's stored answer
   (`evidence_links`). `qtre-sw-detailed-r1` would have 13 included works instead of 16 and 3 more queue rows.
4. **The verb cut** (`verb-split.txt`). 13 English questions: SW17's 8 and the 5 stored in libraries (quantum twice,
   packet, sepsis, medicine). With the proposed cut 4 change and 9 stay byte-identical, both quantum questions among
   them:
   - medicine: `time-restricted eating reduce body weight [task]` → `time-restricted eating [task]` | `body weight
     [outcome]`;
   - SW17 Q2: `packet size affect energy consumption` → `packet size` | `energy consumption`;
   - SW17 Q5: `minimum wage increase affect youth employment` → `minimum wage increase` | `youth employment`;
   - SW17 Q7: `prescribed burns influence soil carbon storage` → `prescribed burns` | `soil carbon storage`.
   These are the 4 welds SW17's Limits and SW25 name (SW17 counted 3 of 28 phrases; the medicine one is the fourth).
   Six SYNTHETIC probes written for this plan behave as intended ("Does climate change affect crop yield …" →
   `climate change` | `crop yield`; "Does weight change predict mortality …" → `weight change` | `mortality`); a
   declarative clause ("studies report that caffeine intake reduces sleep quality") is not cut. Probes are not
   measurement.
5. **Spelling.** Of the 13 questions, two carry a British form (`randomised`, `labour`). Whether OpenAlex, Semantic
   Scholar or PubMed match the other spelling was not tested here (no network).

What the numbers cannot show: whether the new method sentence changes the model's labels (the dry run, decision 5.3,
measures 16 calls); how the labelling labels the new phrases (the dry run's 3 labelling calls); whether the cut phrases
find more relevant records (no search was run; a later medicine re-measurement measures that).

## SW items

- **SW26** (build): closes (D107), with the replay and the dry run.
- **SW25** (build, plus a note): closes (D107): the verb cut in code; the spelling gap and OpenAlex's keyless budget as
  written notes.
- Out of scope, waiting in order: SW18 and the medicine re-measurement (25b stopped, owner's decision), SW19 and SW20
  (24b task 11), SW24, slice 23, D96 (b)–(c), SW6.6.

## Decisions

1. **One slice, two independent parts.** Part 1 is SW26 (method sentence, title rule, queue kind). Part 2 is SW25
   (verb cut, notes). They share no file except `docs/decisions.md` and the tests' fixtures. One commit after Sol's
   review.

2. **SW26: a planned outcome is not a reported result (A1).**
   1. **Method file** (`fulltext-adjudication.md`). After the future-work sentence of line 5 add the meaning of: "A part
      about a result, an effect or a measured outcome is `present` when a passage reports that result or an analysis
      of it as a finding of this paper, whatever its source: the paper's own experiment or trial, a re-analysis, a
      pooled estimate in a review, a derivation or a simulation. A result the paper only plans to measure is not
      reported: a protocol, a trial registration or a design paper that says it will measure the outcome does not
      contain it. Label that part `absent` when the passages show the paper reports no result for it yet, and `unclear`
      when they cannot tell." The sentence does not say "own data" (Sol r1): a review's pooled result or a theoretical
      paper's derived result is reported. No field word (weight, trial names, quantum). The final wording is the
      implementer's; this meaning, the planned-versus-reported line and the `absent` / `unclear` split are kept. The file is a runtime file, so `skill_package_hash` changes.
      With the other parts `present`, an `absent` outcome part gives `partial` and the queue (`part_without_evidence`,
      kind `confirm_absent` when both runs say `absent`), which is D85's rule unchanged.
   2. **Title rule in code.** A pure function in `workflow/adjudication.py`, `protocol_title(title) -> str | None`,
      returns the matched words or `None`, with one compiled, case-insensitive pattern:
      `\b(?:study|trial|review|research|clinical|intervention)\s+protocol\b`
      `|\bprotocol\s+(?:for|of)\s+(?:a|an|the)\b[^:;.?]*\b(?:trial|study)\b`
      `|\bprotocol\s+overview\b`
      `|\brationale\s+and\s+design\b|\bdesign\s+and\s+rationale\b`
      (the measured "proposed" rule of `protocol_titles.py`, byte for byte). The trial/study anchor after "protocol
      for the" is what keeps "… swapping protocol for the quantum Internet" out. Like `vocabulary_words.py`, the
      pattern is English and hand-written; its coverage is what number 2 measured and nothing more.
   3. **Where it acts.** Only in `flow._close_adjudication`, only when `combine` returns `all_parts_verified` **or
      `criterion_absent`**, and only on the read version's own title (`store.source(read)["title"]`): then the code
      written is `protocol_title` with note `protocol_title:<combined code>:<matched words>` instead. Both paths are
      closed because the new method sentence can make a result part `absent` in both runs; with a criterion whose only
      part (or only `present`-able part) is a result, two `absent` runs give `not_met` and `criterion_absent`, which
      derives `excluded` (Sol r1). A protocol-titled work is therefore neither included nor excluded by code; a person
      answers. Every other code (`part_without_evidence`, `fulltext_runs_disagree`, `include_quote_unverified`,
      `fulltext_runs_agree_unresolved`, `pdf_identity_unconfirmed`) already goes to the queue and is written as today.
      `combine` stays pure and unchanged; the substitution is one small pure helper beside it
      (`with_title(code, title) -> (code, note)`) so the replay and the tests call the same function the flow calls. A
      person's decision is never overwritten (as today). A file the user supplied is read the same way; its title rule
      still applies, because the question is about the paper, not the file.
   4. **The code.** `ReasonCode("protocol_title", "fulltext", "unresolved", "code", "human_queue")` in
      `reason_codes.py`, with a comment: the two runs agreed (every part found, or the criterion absent), but the title
      names a study protocol, so code neither includes nor excludes the work; a person answers. `FRESH_MODEL_CODES` gains it (so a fresh one is not read again and a stale
      one is). `should_write` needs no change. It is never an exclusion: the work stays visible and the person decides
      (D85: only two `not_met` runs exclude).
   5. **The queue row.** `KIND_OF["protocol_title"] = "confirm_results"`; `_question` returns `None` for this kind
      (explicitly, like `confirm_pdf`). The screen: `QueueKind` gains `confirm_results`; `queueKindLabels`
      "Confirm the results"; `queueReasons.protocol_title` "The title names a study protocol, so the reading neither
      included nor excluded this work."; the question line in `HumanQueue.tsx` for this kind: "The title names a study protocol. Does this
      paper report its own results for every part?"; Turkish for all three in `i18n.ts`. The row's detail shows the
      two runs' parts and quotes as for any row. The four answers keep their meaning (`include` → `human_include`,
      `criterion_not_met` → `human_criterion_not_met`). Read `.impeccable.md` first; no new component, no new
      dependency.
   6. **What does not change.** The contract `deixis.fulltext_adjudication.v1`, its fixtures, the reading budget, the
      page selection, `verdict`, `combine`, the abstract stage, `legacy` (it has no reading run), and every stored
      decision (a stored `all_parts_verified` stays; the rule acts on the next reading only). No migration.

3. **SW25: cut a phrase at its verb before the labelling (B1), and two notes (C1, E1).**
   1. **The cut** (`domain/vocabulary.py::_phrases`, lists in `vocabulary_words.py`). Two new lists:
      `AUXILIARIES` (`does do did can could will would may might should must`, all already function words) and
      `EFFECT_VERBS` (base and third-person forms of `affect influence reduce increase decrease improve lower raise
      change alter enhance impair prevent cause promote predict modulate determine mitigate worsen delay extend shorten
      boost limit suppress induce inhibit accelerate slow protect outperform differ`, exactly the prototype's list in
      `verb_split.py`). A clause is *inverted* when one of its tokens is an auxiliary, or when the question frame
      stripped from its sentence ends in one ("how does", "how do", "how can", "why does", …); punctuation ends a
      clause. In an inverted clause a candidate phrase is cut once, at the **last** listed word that has a content word
      on each side: the verb is dropped, the left part keeps the phrase's position (its cue, else `task`), and the
      right part takes `outcome`. Phrases outside an inverted clause, and phrases with no listed word inside, are
      exactly what they are today. The rule is `verb_split.py::phrases_new` moved into the product; its output on the
      13 questions must equal `verb-split.json`'s `new` byte for byte.
   2. **Why this shape.** A listed word is also a noun in many phrases ("climate change", "weight change", "wage
      increase"), so an unconditional split would cut those. The auxiliary marks the one place where a listed word
      is almost always the question's main verb, and "last with content on both sides" keeps a noun compound on the
      left ("minimum wage increase" | "youth employment"). The right part is `outcome` because in "does X reduce Y" Y
      is what the question measures; the labelling (SW17) still decides every block, and when it does not answer, the
      outcome block is not queried (SW1.3), so the rule's fall-back searches the intervention, not the outcome.
   3. **What does not change.** SW17's rule that the labelling only labels; `apply_labels`; the probe and the query
      compiler; the model-written query (D92); the user's `key_terms` (they bypass extraction). Stored vocabularies stay
      as stored: a resumed run reuses its stored step. Tests whose SYNTHETIC questions contain an inverted clause with
      a listed verb ("How does irrigation scheduling affect marketable yield …", "How does packet size change the
      energy use …") get new expected phrases and queries; each such change must be exactly the cut and is listed in
      the implementer's final message. No migration, `skill_package_hash` unchanged by this part.
   4. **Spelling note (C1).** No code. SW25's status line and D107's Limits say that code writes no spelling variant,
      that a British form in the question ("randomised", "labour") reaches the code query only in that spelling, and
      that the model-written query (D92) is the only place another spelling can come from. Not measured: whether a
      provider matches the other spelling.
   5. **OpenAlex note (E1).** A comment above `OPENALEX_API_KEY` in `docs/product/providers.env.example`: optional; without
      a key, requests share OpenAlex's daily keyless budget; after one heavy measurement day (2026-09-26, 14 researches)
      it was spent (HTTP 429, `x-ratelimit-remaining: 0`, reset in about 8.4 hours); a key avoids that. Only what was
      observed; no number from OpenAlex's documentation unless read from it at build time with its date.

4. **Tests** (all SYNTHETIC, no network, no model).
   - `tests/test_adjudication.py`: `protocol_title` true for three SYNTHETIC titles of the three measured shapes
     ("…: a study protocol", "…: a randomized controlled trial study protocol", "…: protocol for the X randomized
     controlled trial") and for "Rationale and design of …"; false for "… per-protocol analysis of a randomized
     trial", "… Time-Restricted Feeding Protocol for Improving …: A Randomized Controlled Trial", "… swapping protocol
     for the quantum Internet", "An Energy-Efficient Link Layer Protocol for …", "(16/8 protocol)"; `with_title` turns
     `all_parts_verified` and `criterion_absent` into `protocol_title` for a protocol title, and passes every other code,
     and every code of a plain title, through.
   - `tests/test_adjudication_flow.py`: an all-present, all-verified reading of a version titled as a protocol writes
     `protocol_title` with its note, derives no inclusion, and is not read again on the next run while fresh; the same
     reading of a plain title still writes `all_parts_verified`; a person's include over a `protocol_title` stands.
     **Single result part (Sol r1):** a SYNTHETIC criterion with one part, a result part; both runs `absent` on a
     protocol-titled version writes `protocol_title` (queue, no `excluded` selection); the same two runs on a plain
     title still write `criterion_absent` and derive `excluded`. A two-part criterion where both runs say `absent` for
     every part of a protocol-titled version also writes `protocol_title`.
   - `tests/test_queue.py` / `tests/test_queue_api.py`: the row's kind is `confirm_results`, its question `None`, its
     answers work and undo as for any row.
   - `tests/test_skill_package.py:83-89`: the new method text.
   - `tests/test_vocabulary.py`: the four measured welds (as SYNTHETIC-equivalent questions of the same shape), the
     noun-compound probes ("climate change", "weight change", "minimum wage increase"), a clause without an auxiliary
     that is not cut, a listed word as a phrase's last word is no cut point (in "does X reduce weight change" the cut
     is at "reduce"), and the frame case ("How does X affect Y" with the auxiliary only in the stripped frame).
   - Every test that fails only because of the cut is updated to the cut's output, and nothing else in it.
   - Playwright: one case (1440 and 390 px) where the queue shows a `confirm_results` row with its question and
     reason; if the fixture server has no such scenario, the smallest SYNTHETIC one behind a question marker
     `[protocol-title]`.
   - The determinism replay stages (`tests/determinism_stages.py`) stay byte-identical for inputs without a protocol
     title and without an inverted verb clause.

5. **Acceptance** (scripts and outputs under [.local/sw-slice26-acceptance-<YYYY-MM-DD>/](../local-runs.md#historical-paths-absent-from-the-inspected-tree)).
   1. Full pytest (the known single failure apart:
      `tests/test_documents.py::test_extraction_is_stopped_when_it_exceeds_the_memory_limit`), `npm run build`,
      `npm run lint` (warnings not above 17), the full Playwright suite, `git diff --check`; highest migration `0055`;
      `uv.lock` unchanged; the new `skill_package_hash` written in the final message.
   2. **Replay** (offline, read-only). (a) Reading: for the 10 `sw` libraries of slice 24a, recompute every current
      full-text decision this stage wrote from its stored proposals, as `replay_reading.py` does but through the
      product's new `with_title` (both paths, `all_parts_verified` and `criterion_absent`): 455 of 455 reproduce the
      stored code before the title rule, and exactly the 3 protocols of `qtre-sw-detailed-r1` change, from
      `all_parts_verified` to `protocol_title`, with 0 changes in quantum. No stored `criterion_absent` carries a
      protocol title (measured with `replay_reading.py` after Sol r1: still 3 changes). (b) Phrases: the 13
      questions of `verb-split.json` through the product's `vocabulary.extract`: `new` byte for byte, 9 unchanged.
      Anything else: stop, row 26 `uygulanıyor: replay failed`, and write the difference.
   3. **Dry run (D1), 19 planned calls, at most 22 model sessions,** justified because neither the method sentence nor the labelling of new phrases
      can be replayed without a model, and both are what SW26's and SW25's "Return to" lines ask for. Connection
      `codex`, `gpt-5.6-luna`, effort `medium`, `DEIXIS_CODEX_HOME` from the live data directory, own data directories
      (copies of the two 24a libraries named below), no provider request, port 8765 untouched. **Attempt cap (Sol r1):**
      the script counts every model session it opens (a first call, a schema repair, a re-send after `client_timeout`
      or a rate limit), read from each data directory's stored steps and usage, and never opens a 23rd; reaching the
      cap before the 19 planned calls are answered is a stop (row 26 `uygulanıyor: dry run cap reached; sahip
      kararı`), with the count per call.
      - **Reading, 16 calls** (8 works × 2 runs) through the product's model boundary (`ResearchFlow._model_step` with
        `fulltext_adjudication`), each work shown the passages of its latest stored reading's StepInput and its
        stored criterion, with the new method text. Protocols (copy of `qtre-sw-detailed-r1`): the three of number 1.
        Medicine controls (same copy), results trials that the stored runs included: `10.1038/s41598-022-13904-9`,
        `10.1038/s41467-025-65678-z`, `10.1186/s12986-021-00613-9`. Quantum controls (copy of `q1-sw-standard-r1`):
        `10.1038/s41598-024-70114-1`, `10.1109/tqe.2021.3090532`. Each pair's code is computed with `combine` and
        `with_title` and reported beside the stored code.
      - **Labelling, 3 calls:** the medicine question's new phrase list through `flow._vocabulary_labels` (one
        vocabulary step, three runs). Report each phrase's votes and block.
      - **Stop rules (controls, Sol r1):** each of the five controls is compared with its stored decision, per part
        and combined. The stored state of all five is `all_parts_verified`: both runs `present` with a verified quote
        on every part. Any deviation in any control stops the dry run: a combined code other than
        `all_parts_verified` (after `with_title`), or in either run any part labelled other than `present` (`absent`
        or `unclear`, the outcome part or any other part), or a `present` quote that does not verify, or a run that
        returned no valid output. Stop means row 26 `uygulanıyor: dry run control changed; sahip kararı`, with each
        deviating part's labels, quotes and rationales beside the stored ones. The labelling falling back to the rule (`labelling_unsearchable` or too few runs) → stop the same
        way. A quota or rate-limit error → stop and write where; one `client_timeout` → resume once after 10 minutes;
        never another model.
      - **Reported, not a stop:** how many protocols the model alone keeps out of `all_parts_verified` (frozen
        expectation below); the title rule catches all three either way.
   4. The protocol's quote and the method's `absent` / `unclear` split are read by the implementer on the 6 protocol
      runs and written in the report (a model reading, not a human check).

6. **Documents.** D107 at the top of `docs/decisions.md` (decision, the replay and dry-run numbers, Limits). In
   `docs/archive/search-2026-09/search-workflow-review-2026-09-18.md`: SW25's and SW26's status lines ("implemented in slice 26
   (D107)"), SW25's with the spelling note. `docs/product/providers.env.example` (decision 3.5). Row 26 of
   `sw-status.md`: `uygulandı, inceleme bekliyor` with the headline numbers. Nothing else in `sw-status.md`.

7. **Interaction with 25b (F1).** Slice 25's Part B checks that `backend apps/web contracts methods` have not changed
   since the 25a commit (its task 12). Slice 26 changes all four, so 25b cannot run as written once 26 is committed.
   25b stopped before any research (row 25, |R| = 7) and waits for the owner's decision on the reference rule anyway;
   whoever re-plans the medicine re-measurement pins it to the slice 26 commit and re-freezes. Slice 25's prompt also
   names D107 for the re-measurement's decision; that decision takes the next free number. This slice does not edit
   slice 25's files.

## Frozen expectations

Written before any code. One machine, one model; the dry run is one run of each call.

- Replay (a): 455 of 455 reproduced; exactly 3 changes, all protocols, all in `qtre-sw-detailed-r1`; quantum 0. This
  is measured (number 3), so any other result means the product's function differs from the plan's prototype.
- Replay (b): 4 of 13 questions change, exactly as number 4; measured, same reading.
- Dry run, protocols: the model alone keeps **2 or 3 of 3** out of `all_parts_verified` (weak: a method sentence, not a
  code rule; slice 06's prompt fixes moved the model reliably, D78, but this sentence is untested).
- Dry run, controls: 5 of 5 unchanged, per part and combined (every part `present` with a verified quote in both
  runs; combined `all_parts_verified`). Any deviation is a stop.
- Dry run, labelling: `time-restricted eating` in `task` in at least 2 of 3 runs; `body weight` in `outcome` or
  `task`; no phrase with a listed verb anywhere.

## Owner choices (27 September 2026: A1, B1, C1, D1, E1, F1 önerildiği gibi)

Sahip soru sorulmadan ilerlenmesini istedi; every proposed option is taken. The alternatives stay for the record. None
needs the owner's money or hands.

- **A — SW26's mechanism.** Proposed **A1**: the method sentence plus the title rule that sends a would-be include to
  the queue as `protocol_title` (decision 2); no contract change, no migration. *A2*: the method sentence only; AGENTS.md
  says prompt wording alone is not a strict rule, and the replay cannot show it works. *A3*: contract
  `fulltext_adjudication.v2` with a label `planned` or a work-level "reports results" field the model fills and code
  checks; changes the contract, fixtures, `verdict`, the queue and the screen, and still rests on the model.
  *A4*: the title rule excludes (`criterion_not_met`) instead of asking; a results paper with such a title would be
  dropped by a regular expression, against D85 (only two `not_met` runs exclude).
- **B — SW25's cut.** Proposed **B1**: cut at the last listed verb in a clause inverted by an auxiliary (decision
  3.1). *B2*: also cut at a third-person listed verb in any clause and trim leading reporting verbs ("evaluate
  relay placement" → "relay placement"); more coverage, but "limits", "changes", "causes" are nouns in many titles and
  no stored question needs it. *B3*: let the labelling model split phrases; reverses SW17 point 1.
- **C — Spelling.** Proposed **C1**: a written note only (decision 3.4). *C2*: code adds the `-ize` / `-ise` form of a
  phrase word as an OR alternative; touches the probes, the counts and every provider's query syntax, for a gap no
  measurement has shown to lose a record.
- **D — Live check.** Proposed **D1**: the 19-call dry run of decision 5.3. *D2*: offline only; the method sentence and
  the new labelling stay unmeasured. *D3*: a full medicine research; that is the later re-measurement, not this slice.
- **E — OpenAlex's budget.** Proposed **E1**: a comment in `providers.env.example` and SW25's status line. *E2*: also a
  line in Settings › Connections under OpenAlex (UI string and Turkish). *E3*: read `x-ratelimit-remaining` and show
  it in the search summary; new code for an event the product has not met in a run.
- **F — 25b.** Proposed **F1**: build slice 26 now; the medicine re-measurement is re-planned against the slice 26
  commit (decision 7). *F2*: hold slice 26 until 25b has run; 25b waits for an owner decision with no date.

## What the owner does

Nothing is a question. Only if Luna's quota runs out during the 19-call dry run: wait for it to renew (no money).

## Global constraints

- **Behaviour changes in two places only:** the full-text reading's include (method sentence, title rule, queue kind)
  and phrase extraction (the verb cut). The abstract stage, ranking, fetching, the criterion, the query compiler, the
  model-written query, the answer, `legacy` and `pdf_collection` do not change. No migration.
- **The title rule never excludes** and never overrides a person's decision; it withholds an automatic include and an
  automatic exclusion alike (a protocol-titled work's two agreeing runs go to the queue either way).
- **Evidence contract.** No reading is invented or edited; the stored proposals and quotes stay as the runs wrote them.
- **Every number** with its sample size, machine and model; one run is one run; a model reading is not a human check.
- **Port 8765 and the live library are off limits.** Model never switched, no silent fallback.
- **The owner's files** (`TODO.md`, `.vscode/`, `scripts/local_index.py`) are not changed or staged. Rows 17, 24 and 25
  of `sw-status.md` are not touched.

## Task outline

1. Row 26 `uygulanıyor`.
2. Method sentence (decision 2.1) and its test.
3. `protocol_title`, `with_title`, `FRESH_MODEL_CODES`, the reason code, `_close_adjudication` (2.2–2.4).
4. Queue kind and screen: `queue.py`, `api.ts`, `labels.ts`, `HumanQueue.tsx`, `i18n.ts` (2.5).
5. The verb cut and its lists (3.1); update tests whose SYNTHETIC questions the cut changes.
6. Notes: `providers.env.example` (3.5).
7. Tests (decision 4); Playwright case.
8. Acceptance (decision 5): checks, replay, dry run.
9. Documents (decision 6); row 26 `uygulandı, inceleme bekliyor`.

## Acceptance conditions

Decision 5's four items; full pytest (known single failure apart), build, lint ≤ 17 warnings, Playwright, `git diff
--check`; highest migration `0055`; `uv.lock` unchanged; `skill_package_hash` changed and written; replay (a) 455/455
with exactly the 3 protocol changes; replay (b) 4 of 13 changed as measured; dry run within its stop rules.

## Not in this slice

- The medicine re-measurement, SW18, 24b; SW19, SW20, SW24, slice 23, D96 (b)–(c), SW6.6.
- Excluding a protocol by code; a `planned` label or a contract change (A3, A4).
- Reading a "protocol" publication type: the PubMed adapter keeps only the first type (`providers/pubmed.py:99`,
  usually "Journal Article"), OpenAlex says `article`; in `qtre-sw-detailed-r1` 2 of 5,228 versions carry a type
  naming a protocol, and none of the 47 versions whose titles say "study protocol" (or ENSATI's) do.
- A cut at declarative verbs or leading reporting verbs (B2); spelling variants in the query (C2); a Settings line or a
  rate-limit display for OpenAlex (E2, E3).
- Re-running any 24a research.

## Not measured

Whether the method sentence changes the model's labels beyond the 16 dry-run calls (8 works, one run each); whether the
title rule's precision holds outside medicine and quantum (two fields plus packet in the stored data; a field that uses
"study protocol" for something else was not seen); how many protocols without a protocol title the reading still
includes (none was found among the 17, but the 17 are one question); whether the cut phrases find more relevant
records, and how many queue rows the rule adds in a fresh research (the later re-measurement); how the labelling labels
cut phrases in other fields (the dry run labels one question); whether providers match the other spelling; OpenAlex's
documented keyless limit.

## Sol r1 findings and what changed

Sol (`gpt-6-sol` · high), plan round 1, 27 September 2026: "hazır değil", two high findings, two medium
([.local/archive/sw/sw-slice26-plan-2026-09-27/sol-plan-answer-r1.md](../local-runs.md#run-archive-sw-sw-slice26-plan-2026-09-27)).

- **High 1 — the method sentence and the exclusion path.** "The paper's own data" could make the model reject a
  result a review pools or a theoretical paper derives; and with the new sentence two runs can say `absent` for a result
  part, which on a criterion whose only part is a result gives `criterion_absent` and an automatic exclusion that the
  title rule, acting only on `all_parts_verified`, did not stop. **Changed:** decision 2.1 now reads "a result or an
  analysis of it reported as a finding of this paper, whatever its source" and draws the line at planned versus
  reported, not at whose data; decision 2.3 applies the title rule to `criterion_absent` as well, so a protocol-titled
  work is neither included nor excluded by code (note `protocol_title:<combined code>:<words>`); decision 2.4's
  comment and 2.5's reason text say so; decision 4 adds the single-result-part test and the all-absent two-part test;
  global constraints updated. `replay_reading.py` now applies both paths; the replay is unchanged (455 of 455, 3
  changes, 0 in quantum), because no stored `criterion_absent` carries a protocol title.
- **High 2 — the dry run's stop rule for controls.** It stopped only on a medicine outcome part leaving `present` or a
  quantum part turning `absent`, so a quantum `present → unclear` or a change in a medicine control's other parts could
  pass. **Changed:** decision 5.3 compares every control with its stored decision per part and combined, and stops on
  any deviation (label, quote verification, combined code, missing output); the frozen expectation says the same.
- **Medium — attempt cap.** Decision 5.3 caps the dry run at 22 model sessions in total (19 planned plus up to 3
  repairs or re-sends), counted from stored steps; reaching it is a stop. The prompt says the same.
- **Medium — "unique works".** Recounted by DOI, else normalised title, over the current `all_parts_verified`
  decisions: medicine 17 unique works, 3 flagged; quantum 56, 0 flagged; the same as the title count. Number 2 says so.
