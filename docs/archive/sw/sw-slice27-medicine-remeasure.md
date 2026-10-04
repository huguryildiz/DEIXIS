# SW slice 27 — The medicine re-measurement, with BMI counted as body weight

**Date:** 27 September 2026. **Status:** plan written; Sol r1 (high only) "hazır değil": 1 high and 1 medium finding addressed (last section). The (b) widening is the owner's decision
(2026-09-27); A1, B1, C1, D1, E1, F1 önerildiği gibi (sahip soru sorulmadan ilerlenmesini istedi, 2026-09-27).
**Prompt:** sw-slice27-prompt.md. **Main file:** [sw-status.md](sw-status.md). **Decision:**
D108 (highest today D107). **Migration:** none (highest stays `0055`). **Prerequisite:** 25a closed (`1627b8e`), 26
closed (`142dfa1`), 25b stopped before any research (row 25). **Type:** measure; no product file changes.
**Implementer:** Fable · high, as 25b (a long-running script may go to a Sonnet background agent). **Review:** the result
goes to the owner, as 25b's did. **Plan:** Opus 5.5 · high. **Pre-work:** [.local/archive/sw/sw-slice27-plan-2026-09-27/](../local-runs.md#run-archive-sw-sw-slice27-plan-2026-09-27)
(read-only PubMed requests, no model call, no server).

## What this is

This slice is 25b run again. Its protocol is slice 25's plan decisions 7, 8 and 9 and slice 25's prompt, Part B (tasks
12–17), with the six changes below and nothing else. Where this file is silent, those texts apply as written, and slice
24's plan and prompt give the method wherever they say "the same". There is no build part, and the part keeps 25b's
letter, Part B. Slice 25's Part C (24b) is not part of this slice: whatever the gates say, the run ends with the results
document and D108, and the default goes to the owner (change 6).

25b stopped on 2026-09-26 before any research: the frozen reference rule (slice 25 decision 8) read only two
included-studies tables in 30 candidates and gave |R| = 7 < 10 (decision 8.7). Four eligible reviews had no open table
(two OUP 403, the Cochrane review's PMC copy embargoed and its site 403, one ScienceDirect 403). Its folder is
[.local/archive/sw/sw-slice25-remeasure-2026-09-26-224554/](../local-runs.md#run-archive-sw-sw-slice25-remeasure-2026-09-26-224554). Since then slice 26 (`142dfa1`, D107) changed `backend`, `methods`,
`contracts` and `apps/web`, so 25b's "no diff since the 25a commit" check can no longer hold, and the decision number 25b
would have written (D107) is taken.

## The widening is post hoc

Slice 24's condition (b), kept by slice 25, reads "body weight is one of the pooled outcomes". 25b applied it literally
and excluded rank 25 (PMID 41346676, PMC12672340), a review of 11 RCTs of TRE against unrestricted feeding that pools BMI
but names no body-weight outcome. After R was written, 25b read that review's table once, outside the rule, and estimated
|R| of about 12–15 under a BMI reading (`whatif/rank25-bmi-reading.md`). The owner then decided to count BMI as body
weight in (b).

This widening was chosen after seeing that the frozen rule failed and roughly what the widened rule would give. It is not
a rule fixed before the data. The protocol, the reference file headers and the results document all say so in those
words, and the results document repeats it next to every number that depends on R (gate 2 and the reference tables).

## Changes

1. **Reference rule: (b) accepts BMI; only that ground is re-decided.**
   1. *The rule.* Slice 25 decision 8 as written, except (b): "body weight or body mass index (BMI) is one of the pooled
      outcomes". The trial-level step "body weight not reported → out" (slice 24 decision 6 step 5) is not widened (D1).
   2. *Kept from 25b, copied, not redone.* The literal esearch of 2026-09-26 (Entrez date 2023/01/01–2026/09/26, 90
      hits), its order (B1); every candidate decision for ranks 1–30 except rank 25; the two tables read (rank 9, PMID
      42221753, PMC13215861; rank 30, PMID 41036194, PMC12479299) with the decisions of their 30 rows; the four
      `table_unavailable` candidates (ranks 1, 18, 27, 28). The run copies these files from 25b's folder and checks them
      against the sha256 values below before using them.

      | 25b file | sha256 |
      |---|---|
      | `ledger.jsonl` | `244f641b9fc3526d79a770a5522aebde3d1be2741aa26b7846459f5716c361be` |
      | `tre-candidates.json` | `2324e2070bf4f458467188234618d7701c17cc891ba8e864a1bb640ce92e276c` |
      | `tre-table-rows-resolved.json` | `b72763c6fa893bec1ed072046bc28e3cfeedfdd0211caaa5a6b06dce44f5117d` |
      | `tre_decisions25.py` | `fcc33ae121abd8e5ef5a0d7db3fc63abea976261962c00e89fd6b31e3586f8b1` |
      | `reference-tre.jsonl` (25b's R, |R| = 7) | `714dccb911962bd39d4d2d41fc126b8468a5abbee02cbe2ef4694c8ad09d893b` |
      | `comparator-differs-tre.jsonl` | `e3ba9d4a92bee60fd511cb1a2f1a4f190b0d5700c4f8a80ab2e256efe8b66c39` |
      | `unknown-tre.jsonl` | `fcb0f14b4e78e17cdc850fd6b62ae8e9b04b2548484b151b2f85be0ed34eedbc` |
      | `tre-fulltext/PMC13215861.xml` | `8aeaa478774c3696a5ab4a7dd3a00afd456bab51584e86bc09e73b587a04c391` |
      | `tre-fulltext/PMC12479299.xml` | `2ac168d6d61c86c75c862ada6a18b96cce439e809ececfc4de60a52a3f543b43` |

   3. *Re-decided (A1).* Only candidates 25b excluded for (b) alone, and only on the BMI ground. 25b's (b) exclusions are
      ranks 6, 7, 24, 25 and 26. The abstracts of 6 (reproductive hormones), 7 (training adaptations; (f) also fails), 24
      (glucose and lipid markers) and 26 (sleep) name neither body weight nor BMI among the pooled outcomes, so they stay
      excluded. Rank 25 names BMI (WMD −1.59 kg/m²) and becomes eligible: (a), (c), (f) non-diabetic adults, (g) TRE
      against unrestricted feeding on an identical diet, all from the abstract; (d) RCTs only and (e) population per study,
      from its Table 1.
   4. *Rank 25's table (C1).* Table 1 of PMC12672340 (11 rows) was read, and each row resolved in PubMed, at plan time
      (pre-work below). The run copies the pre-work files, checks their sha256 and rebuilds R from them; it does not read
      the table or the abstracts a second time.
   5. *Stop rule, re-applied.* Tables in rank order 9, 25, 30. After each finished table: stop once at least three tables
      are read and |R| ≥ 10. The candidate cap (30) is reached at rank 30 either way. Then the paper check (slice 25
      decision 8.7): |R| < 10 or an unknown share above 25% stops the slice before any research, with row 27 set to
      `27 durdu: |R| = <n>, bilinmiyor <share>`.
   6. *Headers.* The three reference files' headers say: an analyst set built by a model session, not verified by a
      person; the rule is slice 25 decision 8 with slice 27's (b) widening, **chosen after 25b's stop**; tables read and
      unavailable; unknown count; Cienfuegos 2020 counted as two units (E1).
2. **Code under test: `142dfa1`** (slices 25a and 26). At freeze `git diff --stat 142dfa1 -- backend apps/web contracts
   methods` is empty. `skill_package_hash` comes from a dry server start and must equal D107's
   `sha256:a633e9c7091ed3338b0a51d3c7bdb99e524678f5cc4bdb60e1049d8b4a68028a`; any other value stops the slice before any
   research. `protocol.md` names this plan's commit, `142dfa1` and the hash.
3. **Decision D108, always written by Part B.** It records the four verdicts, gate 2's two readings (change 6), the
   post-hoc widening and the two commits. If a gate fails: "the default still stays `legacy`". If all four pass: the
   owner may switch the default in 24b on this evidence, within the stated limits; this run does not switch it. D105,
   D106 and D107 are not edited.
4. **Quantum stays from slice 24 (F1).** Every quantum number the gates use is read from
   [.local/archive/sw/sw-slice24-campaign-2026-09-26-134050/](../local-runs.md#run-archive-sw-sw-slice24-campaign-2026-09-26-134050), measured on `65a7ec8` (hash `sha256:1700eb6e…`). The medicine
   numbers will come from `142dfa1`. Two code versions therefore meet in one gate verdict. What is known about the gap:
   - *Measured on stored quantum data, code side:* slice 25a's criterion consensus reproduced all 10 stored 24a criteria
     byte for byte (quantum included), and its dry run gave quantum `required_roles = []` in 2 of 2 consensus results.
     Slice 26's title rule changes 0 of 304 stored quantum reading codes and matches 0 of 56 quantum includes, and its
     verb cut leaves both quantum questions' phrases byte-identical.
   - *Tested only in small dry runs, model side:* the new criterion-proposal text (quantum: 6 single proposals, 0 with an
     element) and slice 26's sentence on result parts (2 quantum controls, each read once by both reading runs, all unchanged).
   - *Not measured:* a full quantum research at `142dfa1`. Europe PMC (25a) could add full text to a quantum work in
     the open-access subset; no quantum research has run with it.

   So the quantum half of each gate is a statement about `65a7ec8`, carried over on the evidence that the later code
   changes are no-ops on stored quantum data and moved nothing in the small dry runs. The results document says this
   next to each gate. If the owner wants a default switch that rests on both fields at the same commit, F2 applies (the owner's call, after this run).
5. **Everything else as in 25b.** Tracked edits are limited to `sw-status.md`, the results document,
   `search-workflow-review-2026-09-18.md` (SW18's status line) and, after the gates, D108 in `decisions.md`. The question byte for
   byte; the 7 medicine researches in slice 24's order, one at a time, 2 minutes apart, ports 8858–8864; server
   environment and stop rules of slice 24's `protocol.md`; Codex `gpt-5.6-luna` · medium in every role; nobody approves,
   edits, answers the queue or adds a PDF. The run folder is [.local/sw-slice27-remeasure-<YYYY-MM-DD>-<HHMMSS>/](../local-runs.md#historical-paths-absent-from-the-inspected-tree) with
   the marker [.local/sw-slice27-active](../local-runs.md#historical-paths-absent-from-the-inspected-tree), written only after `protocol.md`; resume and restart follow slice 24 decision 13
   with this folder and marker. The scripts `measure25.py`, `gates25.py`, `post25.py` and `gates25_selftest.py` are
   written, self-tested and frozen as slice 25 decision 9 describes (25b never wrote them). Their diffs against 24a's
   `measure.py`, `gates.py` and `post.py` are frozen beside them. Also unchanged: the analyst sample and second reading
   of slice 24 decision 10 with seed `2409261`, drawn from the union of this campaign's two `sw` `standard` runs; the
   gates as slice 25 decision 7.5 re-reads them, with decision 9's reading of a no-include answer.
6. **What a pass means.** Two choices behind R were made after the numbers were seen: BMI as body weight, and Cienfuegos
   2020 as two units (E1); counted once, the paper check would have stopped at 26.7%. So the run cannot change the default
   by itself.
   - *Gate 2 (medicine) depends on R.* Its verdict is recorded as descriptive, conditional on the post-hoc rule, and is
     always reported beside the one-unit reading (|R| = 11, the same threshold 2, each run's found and cited R units with
     Cienfuegos' two publications as one). A pass there is "passes under the chosen rule", never a plain pass.
   - *Gates 1, 3 and 4 do not depend on R.* Gate 1 is completion, gate 3 is evidence integrity, and gate 4 is the
     analyst sample of includes and claims. They are reported as usual.
   - *The default.* No part of this slice runs 24b. Row 24 records the verdicts in words that slice 24's prompt does not
     read as a pass (`24a bitti; 27 kapıları kaydedildi …; varsayılan kararı sahipte`, or `… kapı N geçmedi (27);
     varsayılan legacy kalır`), and the owner decides. If the owner switches, 24b is written as a new prompt then, from
     slice 24's Part B tasks 10–14 with the next free D, the hash `a633e9c7…`, migration `0055`, and SW21–SW23 and
     SW25–SW26 left out of both lists.

## Pre-work (plan time, measured)

Scripts and outputs in [.local/archive/sw/sw-slice27-plan-2026-09-27/](../local-runs.md#run-archive-sw-sw-slice27-plan-2026-09-27): `rank25_rows.py`, `rank25_rows_fix.py`,
`rank25_rows_doi.py` → `rank25-rows-resolved.json`; `rank25_decisions.py` → `rank25-decisions.json`, `r-estimate.json`;
every step in `ledger.jsonl`. There were 40 read-only requests to NCBI E-utilities (esearch, esummary, efetch), all HTTP
200. They went to one host, with at least 1.05 s between request starts and the product's User-Agent, and each is logged
in `net-log.jsonl`. No model call, no server. The table XML is 25b's single efetch of PMC12672340, copied.

**Row resolution.** 9 of 11 rows resolved with the same two searches 25b used (title; then first author, year and title
words). For Zhou 2024 and Lin 2023 both searches returned nothing, so a third PubMed search used the DOI that the
review's own reference list gives (`<doi>[aid]`). That third search was a judgement call of this session; 25b never had
such a row.

| Row (rank 25, Table 1) | PMID | Decision | Why (table and PubMed abstract only) |
|---|---|---|---|
| Zhou 2024 | 38886740 | unknown | stage 1 hypertension; no BMI in table or abstract |
| Cienfuegos 2020 | 32673591 | R | obesity; 4-/6-h TRF vs no timing restriction; weight; NCT03867773 |
| Oldenburg 2025 | 39973006 | R | BMI 36.2; TRE vs unrestricted eating; weight primary |
| Chow 2020 | 32270927 | R | already in 25b's R (merges) |
| Haganes 2022 | 36198292 | R | already in 25b's R (merges) |
| Lowe 2020 | 32986097 | R | BMI 27–43; TRE vs consistent meal timing, no restriction; weight primary |
| Cui 2025 | 40108888 | R | overweight/obesity; TRE vs regular lifestyle; weight reported |
| Suthutvoravut 2023 | 37836517 | unknown | impaired fasting glucose; no BMI in table or abstract |
| Lin 2023 | 37364268 | R | obesity; TRE vs control eating ≥ 10 h; weight (Elicit's Lin 2023) |
| Manoogian 2024 | 39348690 | unknown | metabolic syndrome, mean BMI 31.2; body weight not named in abstract or table |
| Dote-Montero 2025 | 39775037 | unknown | overweight/obesity; body weight not named in abstract or table |

**Result (a model reading, not a person's).** Tables read after rank 9, 25 and 30: |R| 2 → 8 → 12, with the stop at
rank 30 (3 tables, |R| ≥ 10). Across the three tables there are **|R| = 12** unique trials, 8 comparator-differs and
**4 unknown**, which gives an unknown share of 4 / 16 = **25.0%**. The paper check passes, because the limit is "more
than 25%", but it passes with no margin: one more unknown, or one fewer R unit, stops the slice.

**The same trial counted twice (E1).** 25b's R holds Cienfuegos 2020 through its sleep report (PMID 33759620), whose
abstract carries no registration number. Rank 25's row resolves to the main report (PMID 32673591, NCT03867773). Slice
24's reference-unit rule keeps two publications of one trial apart when no registration number links them, so they are
two units. Counted once, |R| = 11 and the unknown share is 4 / 15 = 26.7%, which stops the slice. Gate 2's pool
threshold is max(2, ⌈0.1 × |R|⌉) = 2 for both 11 and 12, so the double count moves only the paper check, not gate 2's
threshold. A research that finds one of the two publications matches only that unit. The results document reports
gate 2's reference numbers both ways.

The pre-work files the run copies, with their sha256:

| File | sha256 |
|---|---|
| `PMC12672340.xml` | `24bffbbfce5856bb0ace6ca99e8deaca6ed6bfac0097828e1fea953ed720144e` |
| `rank25-rows-resolved.json` | `6f8f1ca35c0bb7d283c664bfe1dd5e6fa352540f2f04b5ab9f536a34070da1fe` |
| `rank25-decisions.json` | `bed7b3c1cc59c1ce3f2d344144114b0342c370b5d1005ac9a5e1dc94e40b4da0` |
| `r-estimate.json` | `4ddc6b26b6440bc10b4c9c567ab7071d81dc4ba56c8db6b78814e56cb3ea0884` |
| `rank25_decisions.py` | `adf5270700bdc31d1025e96398fda72da65b3dc3ace6e6cea535ad0dc3fa61ae` |

The two `tre-trial-abstracts/` directories the run copies hold exactly these files (no more, no fewer). The run keeps
them apart (25b's as `tre-trial-abstracts/`, the pre-work's as `tre-trial-abstracts-rank25/`) and checks each file and
the file lists before anything else. Two PMIDs appear in both with identical bytes.

25b's `tre-trial-abstracts/` (25 files):

| File | sha256 |
|---|---|
| `27550719.txt` | `2318ea9f0ea0130aa4d872ef3ed9bbe310754e3952f60a0a0f263f1afb095f94` |
| `27737674.txt` | `a4b41ea8bd97aa80f1642d5e019a1d45e31c2455bf66f4eb31cf0be59afb6028` |
| `32270927.txt` | `d1c74d2c54db53f2e86092542dadc6752aef10bc9b55a970f0c43c7bb379c546` |
| `32316561.txt` | `8140ee2c3a4e16be9223f336fc7a38f97b56f5bc722bd7e1e6c7c02c74ce7197` |
| `32531956.txt` | `df1844bcf81dce1a05d26aa0b92656fbff0d0e384d0f419fcc3462137aacb137` |
| `32713721.txt` | `67dc2ae1c8c1bc81bf7d71e63c93b4b1ab0fd58f46b7cb3e35d4750a8e500848` |
| `33308259.txt` | `29aaa2f19380adc9d1f99c51f2b78fc96c3bdaaa1ca79e612a4b5178e4c6329b` |
| `33759620.txt` | `9e5ddec365e0a378dbf4c6e33ec47c11f56e3252e301d7e9fb5c7e435f5f0b35` |
| `34042299.txt` | `51cb41a59fc470bb7adc7f7e83074780cf73ec53a2b3a39c8fdc0d9813a743b7` |
| `34299702.txt` | `ebefbaced29884b391bb0f85a6dc4d036e1693a76f7b601f926b926dad410637` |
| `34578819.txt` | `73745f247a43ff0bec88fe7970f88c7f623b039cd36129fe013b090006b363fa` |
| `34578999.txt` | `7df6ff59e88fb6b55c0881ea350bb5969724c129a7b4d5a7202dce097efa0110` |
| `34649266.txt` | `07d9c6098577247ef140c7fe21bf8bf3463f8b85093b1bd6bb0948ddb702928f` |
| `34763309.txt` | `ae3bdd5a1d0bf41bc9ba45a011752a723f5446c9e5dd6d76a13e4bc6df685baa` |
| `35470974.txt` | `4d68f383ea8d0769a52e3a353bf14081aa944ae0eb9f8bee89ef56da2b927ad8` |
| `35614845.txt` | `2d76739fcebdf6371c9535aee8a91514308991c545ea20a515eb76a39b454e80` |
| `36198292.txt` | `c7d9fdd45029bb85fbd9e587c6be32d5f2460811458f5089c3dfb3fd363ec219` |
| `36571891.txt` | `12e1357310011cf71adc304f494df052f0e9f8f363fd00b0288c4fc891594f33` |
| `36678156.txt` | `034f8165743ecbeacd35fad76a9e59b0fa860f2a9211c452522ecfeca86966dc` |
| `36739795.txt` | `c63cfdb1effcf58df3d6e6ce8f548caaf59d482bbf021c1c8d487e700ad51f03` |
| `36839342.txt` | `3ae166e81a1be1aa153f8c4abdfb6bd98553a19ed683f29f4f177af6d0c8d068` |
| `37275490.txt` | `4e7be7afb4fd8beabe0bc1e69b9f53a95690946fc5990a2d4bedff800a38ecec` |
| `37436939.txt` | `c2db5f6b2611cbb38a58d470cfc406ace5421b2dbeebef553a4547b777308f1a` |
| `38242204.txt` | `c0e15f6694253c290de15b2c9082ac7379fd63e51231ec8e119042fb87223ca4` |
| `38639542.txt` | `8115b07a31f86b83afcd52c6334a050e130317eab877812d91254b431fe3180b` |

Pre-work `tre-trial-abstracts/` (11 files):

| File | sha256 |
|---|---|
| `32270927.txt` | `d1c74d2c54db53f2e86092542dadc6752aef10bc9b55a970f0c43c7bb379c546` |
| `32673591.txt` | `8d15675d0e117666e48066ac6c76ec3aabb712a41baa2ba897aca33c80d5e34c` |
| `32986097.txt` | `50d118984fcf5ac08579c083603c298c3a273c8cdb818f6acf72fde091b2972c` |
| `36198292.txt` | `c7d9fdd45029bb85fbd9e587c6be32d5f2460811458f5089c3dfb3fd363ec219` |
| `37364268.txt` | `ca37a9310f7839e90b3e8ff6227c8e5a05732e912d34fe01d3e4ea4570d8c831` |
| `37836517.txt` | `94322ebcea32f388244aaff45a1f1a9fcf0d5f387072d5cba9cc0ddce0421f2f` |
| `38886740.txt` | `162da9832879086e40ec0e39df1d9b1c9b85baac6cd64a8082d2534d6198848e` |
| `39348690.txt` | `fc3da230a4041d7a5f7b2d27d1ba547d8a89ed6c62a5467f3f3a3e2659f52654` |
| `39775037.txt` | `26d08c3d536ed741af71b90d72698e00aa22669ce02e053d0c90cde5c57a0e61` |
| `39973006.txt` | `3335c3b0c79750e2170edcf42491a5790a3c9e7d69fffb888693580cbe9fa24c` |
| `40108888.txt` | `f1ce20972fcfc19b9ce81ad22bb5dbc5ddb34c432f8a3c37a46a5924e751127d` |

## Frozen expectations (slice 25 decision 7.7, updated for slice 26)

These are frozen by this file's commit. "Weak" means no stored measurement backs the number.

- **Unchanged from 7.7:** all 5 medicine `sw` consensus results carry population and comparator parts, their words
  taken from the question; Europe PMC gives full text to 20–40% of the PDF-less planned works in a `standard` run;
  `include` per `standard` run 3–9 and 5–12 unique across the two (weak); serious PICO errors in the drawn includes 0–1;
  0–2 of 5 `sw` researches end with no include, each with the explicit answer; `part_without_evidence` larger than 24a's
  8–28 (weak); gates 1 and 3 pass, gates 2 and 4 uncertain; time and calls within ±30% of 24a's medicine rows (slice 26
  adds no model call).
- **Replaced:** "|R| 10–30, unknown ≤ 25% (weak)" becomes the pre-work's measured |R| = 12 and unknown 4 (25.0%). The run
  must reproduce these exactly from the copied files; any difference stops it before any research.
- **New (slice 26):** in all 5 `sw` researches the code query carries `time-restricted eating` and `body weight` as
  separate phrases, never `time-restricted eating reduce body weight` (replay (b) measured this on the question; the dry
  run labelled them task and outcome in 3 of 3 runs). None of 24a's three medicine protocol works ends as an include in
  any research that reads it: each one ends as `protocol_title` (queue, `confirm_results`) or as the model's
  non-inclusion. The `detailed` research's include count is therefore expected below 24a's (weak). The effect of the
  split phrases on pool size is not predicted.
- **Gate 2 (weak):** R changed from 25b's 7 to 12, and 5 of the new units (Oldenburg, Lowe, Cui, Lin, Cienfuegos' main
  report) were never in 24a's R. Whether 24a's pools held them was not checked at plan time, so the pool half stays
  uncertain. The citation half is harder than under 25b's R: both 24a `legacy` runs cited Lin 2023 from its abstract
  (slice 25, number 6), and Lin 2023 is now in R. If `legacy` cites it again, its mean is ≥ 1 and gate 2 asks for at
  least one R citation in both `sw` `standard` runs, which 24a never reached. Lin 2023 is also an author manuscript that
  Europe PMC does not serve (slice 25, number 8), so an `sw` citation of it needs another open copy.

## Owner decision and owner choices (27 September 2026)

**Owner's decision (given, 2026-09-27, "continue as appropriate", recommended option taken):** in (b), BMI counts as
body weight. It was taken after 25b's stop and after seeing the what-if estimate. *Alternatives on record:* a
registry-based rule (slice 25's E3); leaving medicine out of the gates.

A1, B1, C1, D1, E1, F1 önerildiği gibi (sahip soru sorulmadan ilerlenmesini istedi, 2026-09-27). None needs the owner's
money or hands.

- **A — What is re-decided.** Proposed **A1**: only candidates 25b excluded for (b) alone, on the BMI ground; only rank 25
  changes. *A2*: re-read all 30 candidates under the new (b); it gives the same result (no other (b) exclusion names BMI)
  and reopens every analyst judgement 25b already made.
- **B — Query day.** Proposed **B1**: keep 25b's esearch (2026-09-26, 90 hits, same order). *B2*: re-run it with the run
  day as the end of `edat`; newer reviews would enter at the top, shift every rank and reopen the whole candidate reading.
- **C — Who reads rank 25's table.** Proposed **C1**: the plan's pre-work, frozen by sha256 in this file; the run copies,
  checks and rebuilds, and does no second reading. *C2*: the run reads the table and abstracts again. At a 25.0% unknown
  share, a second reading could move the stop by one row after the numbers are known.
- **D — Trial-level "body weight reported".** Proposed **D1**: unchanged; the widening is in (b) only. *D2*: BMI also
  counts at trial level. In the pre-work D2 changes nothing: two of the four unknowns are population questions, and the
  other two abstracts name neither body weight nor BMI.
- **E — Two publications of one trial without a shared registration number (Cienfuegos 2020).** Proposed **E1**: slice 24's
  reference-unit rule as written, two units, |R| = 12, unknown 25.0%, and the paper check passes. *E2*: count the trial
  once, |R| = 11, unknown 26.7%, and the slice stops. This is the second choice that decides pass or stop, and it too was
  made after the numbers were seen. E1 is proposed because it changes no frozen rule, but it counts a trial the session
  knows is the same twice. The results document says so, and gives gate 2 both ways.
- **F — Quantum.** Proposed **F1**: keep slice 24's quantum results (change 4). *F2*: also re-run the 7 quantum
  researches at `142dfa1`, so both halves of every gate rest on one commit. Cost from 24a: its 1,230 calls minus the
  medicine rows' 453 leaves about 780 Luna calls, and its 4 h 27 min minus medicine's ~1 h 53 min leaves roughly 2.5
  hours, set-up included.

## Not in this slice

A product change of any kind; a new reference rule beyond (b); re-reading any 25b decision other than rank 25; a new
esearch; the quantum re-run (F2); 24b and the default switch (change 6); SW19, SW20 (24b's task 11), SW24, slice 23, D96 (b)–(c), SW6.6.

## Not measured

Whether 24a's medicine pools held the 5 new R units; how many of the 12 are in Europe PMC's open-access subset; a
second reader's agreement with the 11 rank-25 row decisions or with 25b's 30; a quantum research at `142dfa1`; the pool
effect of slice 26's split phrases.

## Sol r1 findings and what changed

Sol (`gpt-6-sol` · high) round 1: "hazır değil", one high and one medium finding. Sol confirmed from the local records
that 12 R, 4 unknown and 25.0% hold and that the listed sha256 values match.

1. **High: a pass was read too strongly for a default change.** The BMI reading and the two-unit count were both chosen
   after the results were seen, the one-unit count stops the paper check at 26.7%, and yet the prompt sent four passes
   straight to 24b. *Changed (coordinator's choice of Sol's options):* gate 2's medicine verdict is descriptive and
   conditional on the post-hoc rule, always beside the one-unit reading; gates 1, 3 and 4 do not depend on R and are
   reported as usual; 24b no longer runs from this slice, D108 always records the verdicts, and the default decision goes
   to the owner (changes 3 and 6; the prompt's Part C is removed and row 24's wording cannot trigger slice 24's Part B).
2. **Medium: the copied abstracts were not pinned.** *Changed:* the file lists and sha256 of both `tre-trial-abstracts/`
   directories are frozen in the pre-work section, and the run checks them first.
