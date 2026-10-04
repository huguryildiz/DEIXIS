# Local run archive

Inspected 4 October 2026, in repo tidy stage D part 1. This catalogue describes the read-only sibling tree `/Users/huguryildiz/Documents/GitHub/DEIXIS/.local`, which is ignored by Git. It records surviving summaries and result files, supplemented by explicitly identified tracked result/decision notes. It does not certify their scientific claims. Missing facts are **bilinmiyor**. No probe, model, provider request, database restore, or test campaign was executed for this catalogue.

## Sizes and evidence limits

Sizes below are current logical file bytes, recursively summed without following symlinks; they are not allocated disk blocks or the old INDEX.md sizes. File counts include metadata and generated environments. The original index lists 165 run directories plus design; the tree also contains final-pair, for 166 run-directory entries here. Nested attempts and copies remain under their parent entry. Large payloads, databases, PDFs, media and environment contents were inventoried by metadata only. Summary/result files were read; original scientific sources were not re-reviewed.

Many directories contain `OZET-SILINENLER.md`, `CACHE-OZET.md` or `PROVIDER-PAYLOADS-OZET.md`. These notes report earlier deletion and sometimes retain only the first 3,000 characters of selected JSON files. A preserved excerpt cannot reconstruct the full input, response, score or library. Their deletion counts are reported history, not evidence that this tidy task deleted anything.

On 4 Oct 2026 `.local/archive/p9-evidence.tar.gz` (833 MB, 71,323 entries, `gzip -t` and `tar tzf` clean) replaced the expanded p9-evidence folder (13 GB). All raw run directories listed below, plus `archive/early` and `archive/sw`, were moved to the macOS Trash as `~/.Trash/deixis-local-<name>-20261004` (recoverable until the Trash is emptied). This page and the tarball are what remain in `.local`.

## Directory groups

| Group | Contents and limits | Current bytes / files |
|---|---|---:|
| `archive/early` | 16 to 20 September search, screening, evidence-table, OCR and comparator diagnostics; 80 run directories plus loose Kurt/search-review files. Many raw artifacts already replaced by deletion notes. | 68,379,746 / 1,435 |
| `archive/sw` | Closed search-workflow development, 21 to 30 September; 71 run directories, handoffs and reviews. D114 closes the measured track; D117 changes the default by owner decision without changing failed medicine gates. | 2,500,986 / 830 |
| `archive/p9-evidence` | Five transferred evidence directories: H9, H9b, owed K6, owed L9 and final-pair; also README.txt, coordination note and mcheck-matrix-181b232.json. Tarball absent. | 14,114,203,102 / 37,111 |
| `design` | Three HTML mockups: deixis-app-prototype-2026-09-19.html, deixis-library-mockup.html, deixis-ui-proposals-2026-09-19.html. Visual proposals, not integrated behavior; deleting them loses those exact mockups. | 897,815 / 3 |

## Runs

<a id="run-p6-eval-2026-09-30"></a>

### `p6-eval-2026-09-30`

**What:** P6 P16 first table-fill/report-readiness attempt

**Phase/decision:** P6; cited under D124.

**Key result:** One fill used 36 model sessions; the table had 21/175 cells left and three failed rows. No report started; R1 to R11 were unmeasured (D124).

**Size:** 1,044,838 bytes (0.996 MiB), 24 files. **Read evidence:** `protocol.md`, `fill_run.json`, `table_after_fill.json`, `sol/a2.md`.

**Loss if dropped:** Dropping remaining evidence would remove the exact recorded inputs/outputs, per-case or per-work checks and replay/provenance needed to audit the reported result.

**Tracked context:** [docs/archive/p6/p6-slice1-report-results.md](p6/p6-slice1-report-results.md), [docs/archive/p6/p6-slice1-report-results-run3.md](p6/p6-slice1-report-results-run3.md), [docs/archive/p6/p6-slice1-report-results-run2.md](p6/p6-slice1-report-results-run2.md).

<a id="run-p6-eval-2026-09-30-run2"></a>

### `p6-eval-2026-09-30-run2`

**What:** P6 P16 second report attempt

**Phase/decision:** P6; cited under D126.

**Key result:** The second attempt stopped at section IV after seven sessions because of unknown_passage_id after one repair. Only R1 and R7 were measured (D126).

**Size:** 4,059,488 bytes (3.871 MiB), 40 files. **Read evidence:** `report/results.json`.

**Loss if dropped:** Dropping remaining evidence would remove the exact recorded inputs/outputs, per-case or per-work checks and replay/provenance needed to audit the reported result.

**Tracked context:** [docs/archive/p6/p6-slice1-report-results-run2.md](p6/p6-slice1-report-results-run2.md), [docs/archive/local-runs.md](local-runs.md), [docs/archive/p6/p6-slice1-report-expectations-addendum.md](p6/p6-slice1-report-expectations-addendum.md).

<a id="run-p6-eval-2026-09-30-run3"></a>

### `p6-eval-2026-09-30-run3`

**What:** P6 P16 third and final report attempt

**Phase/decision:** P6; cited under D128.

**Key result:** The last attempt stopped at section IV after eight sessions because of anchor_not_in_cell_evidence after one repair. Only R1 and R7 were measured (D128).

**Size:** 3,985,170 bytes (3.801 MiB), 42 files. **Read evidence:** `report.md`, `report/results.json`.

**Loss if dropped:** Dropping remaining evidence would remove the exact recorded inputs/outputs, per-case or per-work checks and replay/provenance needed to audit the reported result.

**Tracked context:** [docs/archive/p6/p6-slice1-report-results-run3.md](p6/p6-slice1-report-results-run3.md), [docs/archive/local-runs.md](local-runs.md), [docs/archive/p6/p6-slice1-report-expectations-addendum-2.md](p6/p6-slice1-report-expectations-addendum-2.md).

<a id="run-p6-slice2-l8"></a>

### `p6-slice2-l8`

**What:** P6 slice 2 L8 synthetic behavior and copied-library development trial

**Phase/decision:** P6; cited under D140.

**Key result:** Eight LB cases have true recorded automatic checks; human_judgement is null. README.txt identifies a separate seven-work copied-library development trial, whose corpus was excluded from L9.

**Size:** 198,957 bytes (0.190 MiB), 5 files. **Read evidence:** `README.txt`, `results.json`.

**Loss if dropped:** Dropping remaining evidence would remove the exact recorded inputs/outputs, per-case or per-work checks and replay/provenance needed to audit the reported result.

**Tracked context:** [docs/archive/local-runs.md](local-runs.md).

<a id="run-p6-slice2-l9"></a>

### `p6-slice2-l9`

**What:** P6 slice 2 L9 independent-corpus preparation

**Phase/decision:** P6; cited under D141.

**Key result:** gates.md records K0 passed, K1=1 PDF-text row, K2=1 complete node, K3=0 candidate pairs, all three corpus gates failed. No lineage run; R12 to R15 unmeasured.

**Size:** 559,336 bytes (0.533 MiB), 28 files. **Read evidence:** `protocol.md`, `gates.md`, `independence.json`.

**Loss if dropped:** Dropping remaining evidence would remove the exact recorded inputs/outputs, per-case or per-work checks and replay/provenance needed to audit the reported result.

**Tracked context:** [docs/archive/p6/p6-slice2-results.md](p6/p6-slice2-results.md), [docs/product/p9-owed-measurements-results.md](../product/p9-owed-measurements-results.md), [docs/archive/local-runs.md](local-runs.md).

<a id="run-p6-slice3-k5"></a>

### `p6-slice3-k5`

**What:** P6 slice 3 K5 synthetic claim-assessment behavior

**Phase/decision:** P6; cited under D154.

**Key result:** Seven CB cases have no false recorded automatic checks; CB07 has two not-applicable null checks. Human_judgement is null. This is synthetic claim-assessment behavior evidence.

**Size:** 128,013 bytes (0.122 MiB), 6 files. **Read evidence:** `results.json`.

**Loss if dropped:** Dropping remaining evidence would remove the exact recorded inputs/outputs, per-case or per-work checks and replay/provenance needed to audit the reported result.

**Tracked context:** [docs/archive/local-runs.md](local-runs.md).

<a id="run-p9-baseline"></a>

### `p9-baseline`

**What:** P9 H0 baseline and post-fix checks

**Phase/decision:** P9; cited under D139.

**Key result:** Baseline parallel pytest: 3,772 passed, one memory-limit failure, two skipped; serial: 3,771 passed, two failures, two skipped. after/pytest-final.out records 3,781 passed, three skipped. Both browser logs record 112 passed.

**Size:** 111,044 bytes (0.106 MiB), 16 files. **Read evidence:** `pytest-auto.out`, `pytest-serial.out`, `after/pytest-final.out`, `playwright.out`.

**Loss if dropped:** Dropping remaining evidence would remove the exact recorded inputs/outputs, per-case or per-work checks and replay/provenance needed to audit the reported result.

**Tracked context:** [docs/archive/local-runs.md](local-runs.md), [docs/product/p9-hardening-plan.md](../product/p9-hardening-plan.md).

<a id="run-p9-h0b"></a>

### `p9-h0b`

**What:** P9 H0b PDF child-process memory/deadline diagnosis

**Phase/decision:** P9; cited under D138.

**Key result:** test-runs.txt records 25 passed/one skipped in three serial runs and one parallel run, five individual memory-limit passes, and an opt-in production-threshold pass. gil-diagnosis.txt records the earlier extraction timeout.

**Size:** 18,661 bytes (0.018 MiB), 3 files. **Read evidence:** `gil-diagnosis.txt`, `test-runs.txt`, `runs.jsonl`.

**Loss if dropped:** Dropping remaining evidence would remove the exact recorded inputs/outputs, per-case or per-work checks and replay/provenance needed to audit the reported result.

**Tracked context:** [docs/ROADMAP.md](../ROADMAP.md), [docs/archive/local-runs.md](local-runs.md), [docs/product/p9-hardening-plan.md](../product/p9-hardening-plan.md).

<a id="run-p9-h0c"></a>

### `p9-h0c`

**What:** P9 H0c arXiv child-process memory probes

**Phase/decision:** P9; cited under D159.

**Key result:** runs.jsonl records three post-fix arXiv child terminations at the 1,024 MiB watcher threshold (31.33 to 32.38 s), a low-threshold stop, and a small case completing. These are bounded process probes.

**Size:** 14,432 bytes (0.014 MiB), 1 files. **Read evidence:** `runs.jsonl`.

**Loss if dropped:** Dropping remaining evidence would remove the exact recorded inputs/outputs, per-case or per-work checks and replay/provenance needed to audit the reported result.

**Tracked context:** [docs/ROADMAP.md](../ROADMAP.md), [docs/archive/local-runs.md](local-runs.md).

<a id="run-report-behavior-2026-09-30"></a>

### `report-behavior-2026-09-30`

**What:** P6 P15 report behavior and seeded-review cases

**Phase/decision:** P6; cited under D123.

**Key result:** 18 cases: RB02 structurally_valid=false; RB03 insufficient_evidence_present=false; the other recorded automatic checks are true. The seeded RS cases detect expected issues; RC01 is the control. Human judgements are null.

**Size:** 69,833 bytes (0.067 MiB), 1 files. **Read evidence:** `results.json`.

**Loss if dropped:** Dropping remaining evidence would remove the exact recorded inputs/outputs, per-case or per-work checks and replay/provenance needed to audit the reported result.

**Tracked context:** [docs/archive/local-runs.md](local-runs.md).

<a id="run-archive-early-answer-pdf-pages-2026-09-17"></a>

### `archive/early/answer-pdf-pages-2026-09-17`

**What:** Answer-input PDF-page selection experiment

**Phase/decision:** Early search/method development; cited under D56.

**Key result:** The complete run outcome is bilinmiyor from the surviving summary files. Deletion notes or scripts alone do not establish a successful run; linked tracked notes may preserve a bounded historical result.

**Size:** 18,109 bytes (0.017 MiB), 7 files. **Read evidence:** `OZET-SILINENLER.md`.

**Loss if dropped:** Deletion note already reports 8 dosya, 1.1 MB. Original raw reconstruction is unavailable from this directory alone. Dropping the remaining summaries/logs also loses the recorded excerpts, errors and audit trail.

**Tracked context:** [docs/archive/local-runs.md](local-runs.md), [docs/archive/search-2026-09/answer-pdf-pages-2026-09-17.md](search-2026-09/answer-pdf-pages-2026-09-17.md), [docs/archive/search-2026-09/search-recall-depth-2026-09-17.md](search-2026-09/search-recall-depth-2026-09-17.md).

<a id="run-archive-early-answer-salvage-2026-09-17"></a>

### `archive/early/answer-salvage-2026-09-17`

**What:** Grounded-answer salvage/repair experiment

**Phase/decision:** Early search/method development; exact decision attribution: bilinmiyor.

**Key result:** The complete run outcome is bilinmiyor from the surviving summary files. Deletion notes or scripts alone do not establish a successful run; linked tracked notes may preserve a bounded historical result.

**Size:** 41,754 bytes (0.040 MiB), 12 files. **Read evidence:** `OZET-SILINENLER.md`.

**Loss if dropped:** Deletion note already reports 11 dosya, 3.7 MB. Original raw reconstruction is unavailable from this directory alone. Dropping the remaining summaries/logs also loses the recorded excerpts, errors and audit trail.

**Tracked context:** [docs/archive/local-runs.md](local-runs.md), [docs/archive/search-2026-09/answer-pdf-pages-2026-09-17.md](search-2026-09/answer-pdf-pages-2026-09-17.md).

<a id="run-archive-early-answer-validity-2026-09-17"></a>

### `archive/early/answer-validity-2026-09-17`

**What:** Stored grounded-answer normalization simulation script

**Phase/decision:** Early search/method development; exact decision attribution: bilinmiyor.

**Key result:** The complete run outcome is bilinmiyor from the surviving summary files. Deletion notes or scripts alone do not establish a successful run; linked tracked notes may preserve a bounded historical result.

**Size:** 5,902 bytes (0.006 MiB), 1 files. **Read evidence:** `simulate.py`.

**Loss if dropped:** Dropping remaining evidence would remove the exact recorded inputs/outputs, per-case or per-work checks and replay/provenance needed to audit the reported result.

**Tracked context:** [docs/archive/local-runs.md](local-runs.md).

<a id="run-archive-early-bge-small-dev-probe-2026-09-20"></a>

### `archive/early/bge-small-dev-probe-2026-09-20`

**What:** Would `bge-small-en-v1.5` have scored on the dev set? Dev-only probe (2026-09-20)

**Phase/decision:** Early search/method development; exact decision attribution: bilinmiyor.

**Key result:** Dev-only, 72 records; re-embedding 20 records was bit-identical and the metric path reproduced the frozen campaign points. Test-set specificity was not measured.

**Size:** 33,935 bytes (0.032 MiB), 4 files. **Read evidence:** `REPORT.md`, `OZET-SILINENLER.md`.

**Loss if dropped:** Deletion note already reports 3 dosya, 0.0 MB. Original raw reconstruction is unavailable from this directory alone. Dropping the remaining summaries/logs also loses the recorded excerpts, errors and audit trail.

**Tracked context:** [docs/archive/local-runs.md](local-runs.md).

<a id="run-archive-early-citation-graph-elicit-2026-09-18"></a>

### `archive/early/citation-graph-elicit-2026-09-18`

**What:** Citation-graph example versus the saved Elicit audit

**Phase/decision:** Early search/method development; exact decision attribution: bilinmiyor.

**Key result:** The citation-graph result records 125 initial returned rows and 121 simple identities. The later pacing smoke records keyed search HTTP 200, references HTTP 429, and citations HTTP 200, with request starts 1.898 s apart. These follow-ups do not revise the frozen pilot.

**Size:** 69,475 bytes (0.066 MiB), 13 files. **Read evidence:** `result.md`, `OZET-SILINENLER.md`.

**Loss if dropped:** Deletion note already reports 39 dosya, 3.0 MB. Original raw reconstruction is unavailable from this directory alone. Dropping the remaining summaries/logs also loses the recorded excerpts, errors and audit trail.

**Tracked context:** [docs/archive/local-runs.md](local-runs.md), [docs/archive/search-2026-09/prisma-s-hybrid-search-design-2026-09-18.md](search-2026-09/prisma-s-hybrid-search-design-2026-09-18.md).

<a id="run-archive-early-depth-measure-2026-09-17"></a>

### `archive/early/depth-measure-2026-09-17`

**What:** Retrieval-depth comparison and answer review

**Phase/decision:** Early search/method development; cited under D60.

**Key result:** The complete run outcome is bilinmiyor from the surviving summary files. Deletion notes or scripts alone do not establish a successful run; linked tracked notes may preserve a bounded historical result.

**Size:** 273,772 bytes (0.261 MiB), 24 files. **Read evidence:** `OZET-SILINENLER.md`.

**Loss if dropped:** Deletion note already reports 32 dosya, 2.0 MB. Original raw reconstruction is unavailable from this directory alone. Dropping the remaining summaries/logs also loses the recorded excerpts, errors and audit trail.

**Tracked context:** [docs/archive/local-runs.md](local-runs.md), [docs/archive/search-2026-09/search-recall-depth-2026-09-17.md](search-2026-09/search-recall-depth-2026-09-17.md), [docs/archive/search-2026-09/search-adaptation-experiment-2026-09-17.md](search-2026-09/search-adaptation-experiment-2026-09-17.md).

<a id="run-archive-early-elicit-consensus-deixis-comparison-2026-09-17"></a>

### `archive/early/elicit-consensus-deixis-comparison-2026-09-17`

**What:** Initial Elicit/Consensus/DEIXIS saved-record comparison

**Phase/decision:** Early search/method development; exact decision attribution: bilinmiyor.

**Key result:** The complete run outcome is bilinmiyor from the surviving summary files. Deletion notes or scripts alone do not establish a successful run; linked tracked notes may preserve a bounded historical result.

**Size:** 235 bytes (0.000 MiB), 1 files. **Read evidence:** `OZET-SILINENLER.md`.

**Loss if dropped:** Deletion note already reports 19 dosya, 0.1 MB. Original raw reconstruction is unavailable from this directory alone. Dropping the remaining summaries/logs also loses the recorded excerpts, errors and audit trail.

**Tracked context:** [docs/archive/search-2026-09/elicit-consensus-deixis-comparison-results-2026-09-17.md](search-2026-09/elicit-consensus-deixis-comparison-results-2026-09-17.md), [docs/archive/local-runs.md](local-runs.md), [docs/archive/search-2026-09/search-strategy-external-scan-2026-09-18.md](search-2026-09/search-strategy-external-scan-2026-09-18.md).

<a id="run-archive-early-elicit-consensus-deixis-comparison-2026-09-17-v2"></a>

### `archive/early/elicit-consensus-deixis-comparison-2026-09-17-v2`

**What:** Second Elicit/Consensus/DEIXIS saved-record comparison

**Phase/decision:** Early search/method development; exact decision attribution: bilinmiyor.

**Key result:** The preserved score.json excerpt records zero of seven control hits and 50 deduplicated records. It is a truncated deletion-note copy, not a retained provider-response audit.

**Size:** 1,266 bytes (0.001 MiB), 1 files. **Read evidence:** `OZET-SILINENLER.md`.

**Loss if dropped:** Deletion note already reports 20 dosya, 0.2 MB. Original raw reconstruction is unavailable from this directory alone. Dropping the remaining summaries/logs also loses the recorded excerpts, errors and audit trail.

**Tracked context:** [docs/archive/search-2026-09/elicit-consensus-deixis-comparison-results-2026-09-17.md](search-2026-09/elicit-consensus-deixis-comparison-results-2026-09-17.md), [docs/archive/local-runs.md](local-runs.md), [docs/archive/search-2026-09/search-strategy-external-scan-2026-09-18.md](search-2026-09/search-strategy-external-scan-2026-09-18.md).

<a id="run-archive-early-elicit-consensus-deixis-short-query-rescue-2026-09-17"></a>

### `archive/early/elicit-consensus-deixis-short-query-rescue-2026-09-17`

**What:** Short-query rescue of the saved comparator controls

**Phase/decision:** Early search/method development; exact decision attribution: bilinmiyor.

**Key result:** The preserved score.json excerpt records one control hit from OpenAlex and three from Semantic Scholar, each out of seven controls; 162 deduplicated records. No field-recall claim follows.

**Size:** 3,337 bytes (0.003 MiB), 1 files. **Read evidence:** `OZET-SILINENLER.md`.

**Loss if dropped:** Deletion note already reports 18 dosya, 2.2 MB. Original raw reconstruction is unavailable from this directory alone. Dropping the remaining summaries/logs also loses the recorded excerpts, errors and audit trail.

**Tracked context:** [docs/archive/search-2026-09/elicit-consensus-deixis-comparison-results-2026-09-17.md](search-2026-09/elicit-consensus-deixis-comparison-results-2026-09-17.md), [docs/archive/local-runs.md](local-runs.md).

<a id="run-archive-early-elicit-query-intents-2026-09-17"></a>

### `archive/early/elicit-query-intents-2026-09-17`

**What:** Independent-intent query probe: result

**Phase/decision:** Early search/method development; exact decision attribution: bilinmiyor.

**Key result:** run2/RESULT.md reports a four-question, eight-control, question-only intent comparison, conditioned on controls already confirmed indexed. This is an isolated search probe, not Elicit reproduction.

**Size:** 44,752 bytes (0.043 MiB), 6 files. **Read evidence:** `OZET-SILINENLER.md`, `run2/RESULT.md`.

**Loss if dropped:** Deletion note already reports 262 dosya, 16.3 MB. Original raw reconstruction is unavailable from this directory alone. Dropping the remaining summaries/logs also loses the recorded excerpts, errors and audit trail.

**Tracked context:** [docs/archive/local-runs.md](local-runs.md), [docs/archive/search-2026-09/search-strategy-critical-review-2026-09-18.md](search-2026-09/search-strategy-critical-review-2026-09-18.md).

<a id="run-archive-early-fable-query-diversity-2026-09-18"></a>

### `archive/early/fable-query-diversity-2026-09-18`

**What:** Fable query-diversity consultation

**Phase/decision:** Early search/method development; exact decision attribution: bilinmiyor.

**Key result:** The complete run outcome is bilinmiyor from the surviving summary files. Deletion notes or scripts alone do not establish a successful run; linked tracked notes may preserve a bounded historical result.

**Size:** 5,287 bytes (0.005 MiB), 3 files. **Read evidence:** `OZET-SILINENLER.md`.

**Loss if dropped:** Deletion note already reports 3 dosya, 0.0 MB. Original raw reconstruction is unavailable from this directory alone. Dropping the remaining summaries/logs also loses the recorded excerpts, errors and audit trail.

**Tracked context:** [docs/archive/local-runs.md](local-runs.md).

<a id="run-archive-early-findpapers-entanglement-2026-09-18"></a>

### `archive/early/findpapers-entanglement-2026-09-18`

**What:** Findpapers entanglement search: exploratory result

**Phase/decision:** Early search/method development; exact decision attribution: bilinmiyor.

**Key result:** Two Findpapers searches returned 51 and 43 merged rows, 89 DOI-or-title union entries, and zero of six known DOI controls. The pinned library sorted recent works first; this is an in-sample diagnostic.

**Size:** 19,366 bytes (0.018 MiB), 5 files. **Read evidence:** `result.md`, `OZET-SILINENLER.md`.

**Loss if dropped:** Deletion note already reports 4 dosya, 0.3 MB. Original raw reconstruction is unavailable from this directory alone. Dropping the remaining summaries/logs also loses the recorded excerpts, errors and audit trail.

**Tracked context:** [docs/archive/local-runs.md](local-runs.md).

<a id="run-archive-early-gate-calibration-2026-09-20"></a>

### `archive/early/gate-calibration-2026-09-20`

**What:** Result, 2026-09-20 (`run.py`, `result.json`; no request, no model call; no deviation from the protocol)

**Phase/decision:** Early search/method development; exact decision attribution: bilinmiyor.

**Key result:** On 70 model-adjudicated works (51 formulation positives, 19 in-scope negatives), the hand gate closed 27 positives and no negative. Zero-error rules fitted on small calibration sets still falsely closed held-out negatives.

**Size:** 10,719 bytes (0.010 MiB), 4 files. **Read evidence:** `result.md`, `OZET-SILINENLER.md`.

**Loss if dropped:** Deletion note already reports 1 dosya, 0.0 MB. Original raw reconstruction is unavailable from this directory alone. Dropping the remaining summaries/logs also loses the recorded excerpts, errors and audit trail.

**Tracked context:** [docs/archive/local-runs.md](local-runs.md), [docs/archive/search-2026-09/search-workflow-review-2026-09-18.md](search-2026-09/search-workflow-review-2026-09-18.md).

<a id="run-archive-early-gemini-embedding-probe-2026-09-17"></a>

### `archive/early/gemini-embedding-probe-2026-09-17`

**What:** Gemini embedding reranking probe

**Phase/decision:** Early search/method development; exact decision attribution: bilinmiyor.

**Key result:** The complete run outcome is bilinmiyor from the surviving summary files. Deletion notes or scripts alone do not establish a successful run; linked tracked notes may preserve a bounded historical result.

**Size:** 18,920 bytes (0.018 MiB), 7 files. **Read evidence:** `OZET-SILINENLER.md`.

**Loss if dropped:** Deletion note already reports 3 dosya, 0.0 MB. Original raw reconstruction is unavailable from this directory alone. Dropping the remaining summaries/logs also loses the recorded excerpts, errors and audit trail.

**Tracked context:** [docs/archive/local-runs.md](local-runs.md).

<a id="run-archive-early-generalized-criterion-2026-09-20"></a>

### `archive/early/generalized-criterion-2026-09-20`

**What:** Result, 2026-09-20 (`run.py` → `result.json`; exploratory: `consensus.py` → `consensus.json`, `v2.py` → `v2.json`)

**Phase/decision:** Early search/method development; cited under D84.

**Key result:** Generated cue lists varied across three prompts; the second-prompt consensus placed verified quotes in the top two/top six for 40/48 of 53 papers. This uses the existing adjudicated corpus, not independent human labels.

**Size:** 24,079 bytes (0.023 MiB), 7 files. **Read evidence:** `result.md`, `OZET-SILINENLER.md`.

**Loss if dropped:** Deletion note already reports 11 dosya, 0.1 MB. Original raw reconstruction is unavailable from this directory alone. Dropping the remaining summaries/logs also loses the recorded excerpts, errors and audit trail.

**Tracked context:** [docs/archive/local-runs.md](local-runs.md), [docs/archive/sw/sw-slice11-criterion-passages.md](sw/sw-slice11-criterion-passages.md), [docs/archive/search-2026-09/search-workflow-review-2026-09-18.md](search-2026-09/search-workflow-review-2026-09-18.md).

<a id="run-archive-early-jev-gemini-screening-2026-09-20"></a>

### `archive/early/jev-gemini-screening-2026-09-20`

**What:** REPORT : literature screening: Jev vs Gemini embeddings

**Phase/decision:** Early search/method development; exact decision attribution: bilinmiyor.

**Key result:** REPORT.md records 594 test works with model/adjudicated labels A=78, B=93, C=423. Jev M2 has recall 0.7692 and specificity 0.9244 at its dev-frozen point. C means unusable/not applicable full text; labels are not human ground truth.

**Size:** 37,626,583 bytes (35.884 MiB), 680 files. **Read evidence:** `REPORT.md`, `OZET-SILINENLER.md`.

**Loss if dropped:** Deletion note already reports 5038 dosya, 113.2 MB. Original raw reconstruction is unavailable from this directory alone. Dropping the remaining summaries/logs also loses the recorded excerpts, errors and audit trail.

**Tracked context:** [docs/archive/local-runs.md](local-runs.md).

<a id="run-archive-early-jev-screening-2026-09-19"></a>

### `archive/early/jev-screening-2026-09-19`

**What:** Jev vs embedding vs the product's screening label, abstract stage (SW13 measurement)

**Phase/decision:** Early search/method development; exact decision attribution: bilinmiyor.

**Key result:** 72 work groups, referenced to model full-text adjudication; Jev formulation-score AUC is 0.891. Later code-cue and bootstrap analyses are marked post-hoc, and no human gold standard is established.

**Size:** 71,123 bytes (0.068 MiB), 11 files. **Read evidence:** `REPORT.md`, `OZET-SILINENLER.md`.

**Loss if dropped:** Deletion note already reports 156 dosya, 2.7 MB. Original raw reconstruction is unavailable from this directory alone. Dropping the remaining summaries/logs also loses the recorded excerpts, errors and audit trail.

**Tracked context:** [docs/archive/local-runs.md](local-runs.md).

<a id="run-archive-early-jev-screening-utility-2026-09-19"></a>

### `archive/early/jev-screening-utility-2026-09-19`

**What:** Recall-constrained screening utility at the abstract stage (SW13-B measurement)

**Phase/decision:** Early search/method development; exact decision attribution: bilinmiyor.

**Key result:** At the 95% target-recall bootstrap operating rule, the typed-probability arm records out-of-bag recall 0.947 and specificity 0.286; the other arms remove zero negatives under that constraint. Reference labels are from the earlier model adjudication.

**Size:** 225,373 bytes (0.215 MiB), 15 files. **Read evidence:** `REPORT.md`, `OZET-SILINENLER.md`.

**Loss if dropped:** Deletion note already reports 1243 dosya, 11.6 MB. Original raw reconstruction is unavailable from this directory alone. Dropping the remaining summaries/logs also loses the recorded excerpts, errors and audit trail.

**Tracked context:** [docs/archive/local-runs.md](local-runs.md).

<a id="run-archive-early-kurt-deixis-eval-2026-09-16"></a>

### `archive/early/kurt-deixis-eval-2026-09-16`

**What:** Kurt packet-size: Luna medium DEIXIS evaluation

**Phase/decision:** Early search/method development; exact decision attribution: bilinmiyor.

**Key result:** An OpenAlex-only Luna-medium run returned 150 records, 128 unique; 89 included, 23 excluded, 18 pending as reported. The PDF and known-source list were withheld from search planning; the report preserves separate funnel counts.

**Size:** 29,906 bytes (0.029 MiB), 9 files. **Read evidence:** `REPORT.md`, `OZET-SILINENLER.md`.

**Loss if dropped:** Deletion note already reports 7 dosya, 0.5 MB. Original raw reconstruction is unavailable from this directory alone. Dropping the remaining summaries/logs also loses the recorded excerpts, errors and audit trail.

**Tracked context:** [docs/archive/local-runs.md](local-runs.md), [docs/product/p5-slice5-measurement.md](../product/p5-slice5-measurement.md).

<a id="run-archive-early-litllm-inspect-2026-09-17"></a>

### `archive/early/litllm-inspect-2026-09-17`

**What:** LitLLM source-inspection snapshot (five Python files)

**Phase/decision:** Early search/method development; exact decision attribution: bilinmiyor.

**Key result:** The complete run outcome is bilinmiyor from the surviving summary files. Deletion notes or scripts alone do not establish a successful run; linked tracked notes may preserve a bounded historical result.

**Size:** 59,126 bytes (0.056 MiB), 5 files. **Read evidence:** `deep_research.py`.

**Loss if dropped:** Dropping remaining evidence would remove the exact recorded inputs/outputs, per-case or per-work checks and replay/provenance needed to audit the reported result.

**Tracked context:** [docs/archive/local-runs.md](local-runs.md).

<a id="run-archive-early-live-backup"></a>

### `archive/early/live-backup`

**What:** Historical server-log backup (two logs; no library backup survives)

**Phase/decision:** Early search/method development; exact decision attribution: bilinmiyor.

**Key result:** The complete run outcome is bilinmiyor from the surviving summary files. Deletion notes or scripts alone do not establish a successful run; linked tracked notes may preserve a bounded historical result.

**Size:** 359,187 bytes (0.343 MiB), 2 files. **Read evidence:** `server-20260917-0014.log`, `server-1552.log`.

**Loss if dropped:** Dropping remaining evidence would remove the exact recorded inputs/outputs, per-case or per-work checks and replay/provenance needed to audit the reported result.

**Tracked context:** [docs/archive/local-runs.md](local-runs.md).

<a id="run-archive-early-math-ocr"></a>

### `archive/early/math-ocr`

**What:** Math OCR extraction and timing experiment

**Phase/decision:** Early search/method development; cited under D62.

**Key result:** The complete run outcome is bilinmiyor from the surviving summary files. Deletion notes or scripts alone do not establish a successful run; linked tracked notes may preserve a bounded historical result.

**Size:** 896,564 bytes (0.855 MiB), 87 files. **Read evidence:** `times.txt`, `OZET-SILINENLER.md`.

**Loss if dropped:** Deletion note already reports 125 dosya, 10.6 MB. Original raw reconstruction is unavailable from this directory alone. Dropping the remaining summaries/logs also loses the recorded excerpts, errors and audit trail.

**Tracked context:** [docs/archive/local-runs.md](local-runs.md).

<a id="run-archive-early-openalex-allfield-2026-09-17"></a>

### `archive/early/openalex-allfield-2026-09-17`

**What:** OpenAlex all-field comparison

**Phase/decision:** Early search/method development; exact decision attribution: bilinmiyor.

**Key result:** Same-query field comparison: both scopes found nine of 12 DOI controls. All-field returned 723 vs 660 rows and had 23/60 vs 30/60 first-ten clear-relevance labels. This is a reused-case component test.

**Size:** 16,939 bytes (0.016 MiB), 4 files. **Read evidence:** `RESULT.md`, `OZET-SILINENLER.md`.

**Loss if dropped:** Deletion note already reports 128 dosya, 25.7 MB. Original raw reconstruction is unavailable from this directory alone. Dropping the remaining summaries/logs also loses the recorded excerpts, errors and audit trail.

**Tracked context:** [docs/archive/local-runs.md](local-runs.md).

<a id="run-archive-early-p5-luna-2026-09-16"></a>

### `archive/early/p5-luna-2026-09-16`

**What:** P5 slice 1 sub-step 5 : real-model evidence table trial (2026-09-16)

**Phase/decision:** P5; cited under D43.

**Key result:** First fill: 23 model steps, 13 valid, ten invalid after repair, 40 calls; 104 valid cells, 16 inaccessible, 80 unverified proposals. Rerun has its own REPORT.md. The cell sample was read by a model, not a human.

**Size:** 71,399 bytes (0.068 MiB), 13 files. **Read evidence:** `REPORT.md`, `OZET-SILINENLER.md`, `rerun/REPORT.md`.

**Loss if dropped:** Deletion note already reports 14 dosya, 0.8 MB. Original raw reconstruction is unavailable from this directory alone. Dropping the remaining summaries/logs also loses the recorded excerpts, errors and audit trail.

**Tracked context:** [docs/archive/local-runs.md](local-runs.md).

<a id="run-archive-early-p5-measure-2026-09-17"></a>

### `archive/early/p5-measure-2026-09-17`

**What:** P5 evidence-table and follow-up measurement

**Phase/decision:** P5; cited under D55.

**Key result:** The complete run outcome is bilinmiyor from the surviving summary files. Deletion notes or scripts alone do not establish a successful run; linked tracked notes may preserve a bounded historical result.

**Size:** 338,929 bytes (0.323 MiB), 17 files. **Read evidence:** `OZET-SILINENLER.md`.

**Loss if dropped:** Deletion note already reports 34 dosya, 7.0 MB. Original raw reconstruction is unavailable from this directory alone. Dropping the remaining summaries/logs also loses the recorded excerpts, errors and audit trail.

**Tracked context:** [docs/archive/local-runs.md](local-runs.md), [docs/product/p5-slice5-measurement.md](../product/p5-slice5-measurement.md).

<a id="run-archive-early-p6-p5-2026-09-18"></a>

### `archive/early/p6-p5-2026-09-18`

**What:** Early report-generation snapshots

**Phase/decision:** P6; exact decision attribution: bilinmiyor.

**Key result:** Four report snapshots survive. rapor-2-kalip-sikilastirmasi-sonrasi.md explicitly labels an incomplete report, paused after three written sections with section_must_be_rewritten. A filename containing TAM does not by itself establish completion or quality.

**Size:** 50,212 bytes (0.048 MiB), 4 files. **Read evidence:** `rapor-2-kalip-sikilastirmasi-sonrasi.md`, `rapor-4-dokuz-bolum.md`, `rapor-7-TAM.md`.

**Loss if dropped:** Dropping remaining evidence would remove the exact recorded inputs/outputs, per-case or per-work checks and replay/provenance needed to audit the reported result.

**Tracked context:** [docs/archive/local-runs.md](local-runs.md), [docs/archive/p6/p6-slice1-handoff.md](p6/p6-slice1-handoff.md).

<a id="run-archive-early-passage-selection-2026-09-16"></a>

### `archive/early/passage-selection-2026-09-16`

**What:** Passage selection replay (offline, 2026-09-16)

**Phase/decision:** Early search/method development; exact decision attribution: bilinmiyor.

**Key result:** Offline 48-passage lexical MMR proxy: PDF-source coverage 7 to 9; mean pairwise Jaccard 0.0804 to 0.0545. No provider/model call or semantic relevance measurement; sensitivity reports are separate.

**Size:** 45,816 bytes (0.044 MiB), 10 files. **Read evidence:** `REPORT.md`, `OZET-SILINENLER.md`, `sensitivity-l1.00/REPORT.md`, `second-case/REPORT.md`, `sensitivity-l0.85/REPORT.md`.

**Loss if dropped:** Deletion note already reports 7 dosya, 0.0 MB. Original raw reconstruction is unavailable from this directory alone. Dropping the remaining summaries/logs also loses the recorded excerpts, errors and audit trail.

**Tracked context:** [docs/archive/local-runs.md](local-runs.md), [docs/product/p5-slice5-measurement.md](../product/p5-slice5-measurement.md), [docs/archive/search-2026-09/answer-pdf-pages-2026-09-17.md](search-2026-09/answer-pdf-pages-2026-09-17.md).

<a id="run-archive-early-prisma-s-design-review-2026-09-18"></a>

### `archive/early/prisma-s-design-review-2026-09-18`

**What:** PRISMA-S hybrid-design model review

**Phase/decision:** Early search/method development; exact decision attribution: bilinmiyor.

**Key result:** Surviving material is a plan/review or implementation hand-back. A separate executed measurement outcome is bilinmiyor; consult the linked tracked record for later disposition.

**Size:** 18,902 bytes (0.018 MiB), 3 files. **Read evidence:** `OZET-SILINENLER.md`.

**Loss if dropped:** Deletion note already reports 1 dosya, 0.0 MB. Original raw reconstruction is unavailable from this directory alone. Dropping the remaining summaries/logs also loses the recorded excerpts, errors and audit trail.

**Tracked context:** [docs/archive/local-runs.md](local-runs.md), [docs/archive/sw/sw-implementation-plan.md](sw/sw-implementation-plan.md), [docs/archive/search-2026-09/prisma-s-design-review-2026-09-18.md](search-2026-09/prisma-s-design-review-2026-09-18.md).

<a id="run-archive-early-prisma-s-elicit-misses-diagnostic-2026-09-18"></a>

### `archive/early/prisma-s-elicit-misses-diagnostic-2026-09-18`

**What:** Post-hoc diagnosis of Elicit works missing from the frozen candidate pool

**Phase/decision:** Early search/method development; exact decision attribution: bilinmiyor.

**Key result:** The complete run outcome is bilinmiyor from the surviving summary files. Deletion notes or scripts alone do not establish a successful run; linked tracked notes may preserve a bounded historical result.

**Size:** 1,810 bytes (0.002 MiB), 2 files. **Read evidence:** `OZET-SILINENLER.md`.

**Loss if dropped:** Deletion note already reports 1 dosya, 0.0 MB. Original raw reconstruction is unavailable from this directory alone. Dropping the remaining summaries/logs also loses the recorded excerpts, errors and audit trail.

**Tracked context:** [docs/archive/local-runs.md](local-runs.md).

<a id="run-archive-early-prisma-s-pdf-diagnostic-2026-09-18"></a>

### `archive/early/prisma-s-pdf-diagnostic-2026-09-18`

**What:** Post-hoc PDF availability diagnostic

**Phase/decision:** Early search/method development; exact decision attribution: bilinmiyor.

**Key result:** Elicit-informed post-hoc three-version PDF diagnosis: the Nguyen published version had no eligible PDF in the bounded routes; an accepted-version candidate was retained separately. No human full-text assessment or independent retrieval comparison.

**Size:** 11,538 bytes (0.011 MiB), 4 files. **Read evidence:** `result.md`, `OZET-SILINENLER.md`.

**Loss if dropped:** Deletion note already reports 3 dosya, 0.1 MB. Original raw reconstruction is unavailable from this directory alone. Dropping the remaining summaries/logs also loses the recorded excerpts, errors and audit trail.

**Tracked context:** [docs/archive/local-runs.md](local-runs.md).

<a id="run-archive-early-prisma-s-quantum-nguyen-diagnostic-2026-09-18"></a>

### `archive/early/prisma-s-quantum-nguyen-diagnostic-2026-09-18`

**What:** Post-hoc Nguyen DOI/work-id retrieval diagnosis

**Phase/decision:** Early search/method development; exact decision attribution: bilinmiyor.

**Key result:** The complete run outcome is bilinmiyor from the surviving summary files. Deletion notes or scripts alone do not establish a successful run; linked tracked notes may preserve a bounded historical result.

**Size:** 11,099 bytes (0.011 MiB), 4 files. **Read evidence:** `OZET-SILINENLER.md`.

**Loss if dropped:** Deletion note already reports 2 dosya, 0.0 MB. Original raw reconstruction is unavailable from this directory alone. Dropping the remaining summaries/logs also loses the recorded excerpts, errors and audit trail.

**Tracked context:** [docs/archive/local-runs.md](local-runs.md).

<a id="run-archive-early-prisma-s-quantum-run-2026-09-18"></a>

### `archive/early/prisma-s-quantum-run-2026-09-18`

**What:** PRISMA-S-grounded quantum search: isolated development result

**Phase/decision:** Early search/method development; exact decision attribution: bilinmiyor.

**Key result:** result.md labels a completed bounded search diagnostic and source-reading example. Automatic seed/term selections lacked human approval; it is not a completed systematic review or equal-budget Elicit benchmark.

**Size:** 816,553 bytes (0.779 MiB), 12 files. **Read evidence:** `result.md`, `OZET-SILINENLER.md`.

**Loss if dropped:** Deletion note already reports 26 dosya, 7.3 MB. Original raw reconstruction is unavailable from this directory alone. Dropping the remaining summaries/logs also loses the recorded excerpts, errors and audit trail.

**Tracked context:** [docs/archive/local-runs.md](local-runs.md).

<a id="run-archive-early-prismaid-quantum-trial-2026-09-18"></a>

### `archive/early/prismaid-quantum-trial-2026-09-18`

**What:** prismAId trial for the quantum optimization-model question

**Phase/decision:** Early search/method development; exact decision attribution: bilinmiyor.

**Key result:** An isolated prismAId v0.17.1 screening/review trial over frozen DEIXIS candidates. No new discovery or user-approved inclusion; retained screened CSVs and result.md describe the trial, not a systematic review.

**Size:** 6,355,924 bytes (6.061 MiB), 23 files. **Read evidence:** `result.md`, `OZET-SILINENLER.md`.

**Loss if dropped:** Deletion note already reports 5 dosya, 0.0 MB. Original raw reconstruction is unavailable from this directory alone. Dropping the remaining summaries/logs also loses the recorded excerpts, errors and audit trail.

**Tracked context:** [docs/archive/local-runs.md](local-runs.md).

<a id="run-archive-early-quantum-abstract-disagreement-2026-09-19"></a>

### `archive/early/quantum-abstract-disagreement-2026-09-19`

**What:** Repeated abstract-screening disagreement check

**Phase/decision:** Early search/method development; exact decision attribution: bilinmiyor.

**Key result:** The preserved result.json block records both runs completed on 100 records, zero failed calls, six label disagreements, and two non-verbatim quotes among 198. This measures consistency, not accuracy.

**Size:** 25,656 bytes (0.024 MiB), 6 files. **Read evidence:** `OZET-SILINENLER.md`.

**Loss if dropped:** Deletion note already reports 202 dosya, 0.3 MB. Original raw reconstruction is unavailable from this directory alone. Dropping the remaining summaries/logs also loses the recorded excerpts, errors and audit trail.

**Tracked context:** [docs/archive/local-runs.md](local-runs.md), [docs/archive/search-2026-09/search-workflow-review-2026-09-18.md](search-2026-09/search-workflow-review-2026-09-18.md).

<a id="run-archive-early-quantum-author-keywords-2026-09-18-plan-a"></a>

### `archive/early/quantum-author-keywords-2026-09-18-plan-a`

**What:** Author-keyword round preparation, plan A

**Phase/decision:** Early search/method development; exact decision attribution: bilinmiyor.

**Key result:** Surviving material is a plan/review or implementation hand-back. A separate executed measurement outcome is bilinmiyor; consult the linked tracked record for later disposition.

**Size:** 229 bytes (0.000 MiB), 1 files. **Read evidence:** `OZET-SILINENLER.md`.

**Loss if dropped:** Deletion note already reports 3 dosya, 0.0 MB. Original raw reconstruction is unavailable from this directory alone. Dropping the remaining summaries/logs also loses the recorded excerpts, errors and audit trail.

**Tracked context:** [docs/archive/local-runs.md](local-runs.md).

<a id="run-archive-early-quantum-chain-precision-2026-09-18"></a>

### `archive/early/quantum-chain-precision-2026-09-18`

**What:** Quantum citation-chain precision experiment

**Phase/decision:** Early search/method development; exact decision attribution: bilinmiyor.

**Key result:** The complete run outcome is bilinmiyor from the surviving summary files. Deletion notes or scripts alone do not establish a successful run; linked tracked notes may preserve a bounded historical result.

**Size:** 151,319 bytes (0.144 MiB), 16 files. **Read evidence:** `OZET-SILINENLER.md`.

**Loss if dropped:** Deletion note already reports 463 dosya, 9.0 MB. Original raw reconstruction is unavailable from this directory alone. Dropping the remaining summaries/logs also loses the recorded excerpts, errors and audit trail.

**Tracked context:** [docs/archive/local-runs.md](local-runs.md), [docs/archive/search-2026-09/search-workflow-review-2026-09-18.md](search-2026-09/search-workflow-review-2026-09-18.md).

<a id="run-archive-early-quantum-chunk-rerank-2026-09-19"></a>

### `archive/early/quantum-chunk-rerank-2026-09-19`

**What:** Quantum passage chunk/reranker and circularity probes

**Phase/decision:** Early search/method development; exact decision attribution: bilinmiyor.

**Key result:** The complete run outcome is bilinmiyor from the surviving summary files. Deletion notes or scripts alone do not establish a successful run; linked tracked notes may preserve a bounded historical result.

**Size:** 36,673 bytes (0.035 MiB), 9 files. **Read evidence:** `OZET-SILINENLER.md`.

**Loss if dropped:** Deletion note already reports 57 dosya, 0.1 MB. Original raw reconstruction is unavailable from this directory alone. Dropping the remaining summaries/logs also loses the recorded excerpts, errors and audit trail.

**Tracked context:** [docs/archive/local-runs.md](local-runs.md), [docs/archive/search-2026-09/search-workflow-review-2026-09-18.md](search-2026-09/search-workflow-review-2026-09-18.md).

<a id="run-archive-early-quantum-cited-terms-2026-09-18-plan-k"></a>

### `archive/early/quantum-cited-terms-2026-09-18-plan-k`

**What:** Cited-paper term preparation, plan K

**Phase/decision:** Early search/method development; exact decision attribution: bilinmiyor.

**Key result:** Surviving material is a plan/review or implementation hand-back. A separate executed measurement outcome is bilinmiyor; consult the linked tracked record for later disposition.

**Size:** 225 bytes (0.000 MiB), 1 files. **Read evidence:** `OZET-SILINENLER.md`.

**Loss if dropped:** Deletion note already reports 2 dosya, 0.0 MB. Original raw reconstruction is unavailable from this directory alone. Dropping the remaining summaries/logs also loses the recorded excerpts, errors and audit trail.

**Tracked context:** [docs/archive/local-runs.md](local-runs.md).

<a id="run-archive-early-quantum-cited-terms-2026-09-18-run-k"></a>

### `archive/early/quantum-cited-terms-2026-09-18-run-k`

**What:** Isolated cited-paper term round

**Phase/decision:** Early search/method development; exact decision attribution: bilinmiyor.

**Key result:** Two completed OpenAlex calls returned seven identities, zero incremental to arm C. No PDF, graph, second term round, human screening, or inclusion.

**Size:** 6,857 bytes (0.007 MiB), 3 files. **Read evidence:** `result.md`, `OZET-SILINENLER.md`.

**Loss if dropped:** Deletion note already reports 5 dosya, 0.1 MB. Original raw reconstruction is unavailable from this directory alone. Dropping the remaining summaries/logs also loses the recorded excerpts, errors and audit trail.

**Tracked context:** [docs/archive/local-runs.md](local-runs.md).

<a id="run-archive-early-quantum-dedup-2026-09-18"></a>

### `archive/early/quantum-dedup-2026-09-18`

**What:** Quantum work/version deduplication diagnostics

**Phase/decision:** Early search/method development; cited under D72.

**Key result:** The complete run outcome is bilinmiyor from the surviving summary files. Deletion notes or scripts alone do not establish a successful run; linked tracked notes may preserve a bounded historical result.

**Size:** 66,485 bytes (0.063 MiB), 9 files. **Read evidence:** `OZET-SILINENLER.md`.

**Loss if dropped:** Deletion note already reports 7 dosya, 1.0 MB. Original raw reconstruction is unavailable from this directory alone. Dropping the remaining summaries/logs also loses the recorded excerpts, errors and audit trail.

**Tracked context:** [docs/archive/local-runs.md](local-runs.md), [docs/archive/sw/sw-slice03-record-kind-and-version-links.md](sw/sw-slice03-record-kind-and-version-links.md), [docs/archive/search-2026-09/search-workflow-review-2026-09-18.md](search-2026-09/search-workflow-review-2026-09-18.md).

<a id="run-archive-early-quantum-determinism-2026-09-20"></a>

### `archive/early/quantum-determinism-2026-09-20`

**What:** Result, 2026-09-20 (`run.py`, `result.json`; no request, no model call)

**Phase/decision:** Early search/method development; cited under D70.

**Key result:** Nine decision-file canonical hashes matched across four hash-seed/row-order conditions. Byte ordering differed in some files; this establishes tested decision determinism, not byte-identical serialization everywhere.

**Size:** 14,214 bytes (0.014 MiB), 4 files. **Read evidence:** `result.md`, `OZET-SILINENLER.md`.

**Loss if dropped:** Deletion note already reports 1 dosya, 0.0 MB. Original raw reconstruction is unavailable from this directory alone. Dropping the remaining summaries/logs also loses the recorded excerpts, errors and audit trail.

**Tracked context:** [docs/archive/local-runs.md](local-runs.md), [docs/archive/search-2026-09/search-workflow-review-2026-09-18.md](search-2026-09/search-workflow-review-2026-09-18.md).

<a id="run-archive-early-quantum-entanglement-search-2026-09-17"></a>

### `archive/early/quantum-entanglement-search-2026-09-17`

**What:** DEIXIS quantum-network question: isolated measurement (2026-09-17)

**Phase/decision:** Early search/method development; exact decision attribution: bilinmiyor.

**Key result:** result.md records an isolated actual standard discovery/answer workflow, Luna medium, legacy compiler, eight model sessions including one bounded answer repair. Six hidden known works were diagnostic controls, not a representative relevance set.

**Size:** 66,403 bytes (0.063 MiB), 13 files. **Read evidence:** `result.md`, `OZET-SILINENLER.md`.

**Loss if dropped:** Deletion note already reports 72 dosya, 6.2 MB. Original raw reconstruction is unavailable from this directory alone. Dropping the remaining summaries/logs also loses the recorded excerpts, errors and audit trail.

**Tracked context:** [docs/archive/local-runs.md](local-runs.md), [docs/archive/search-2026-09/search-query-structure-design-2026-09-18.md](search-2026-09/search-query-structure-design-2026-09-18.md), [docs/archive/search-2026-09/search-strategy-critical-review-2026-09-18.md](search-2026-09/search-strategy-critical-review-2026-09-18.md).

<a id="run-archive-early-quantum-evidence-pilot-2026-09-18"></a>

### `archive/early/quantum-evidence-pilot-2026-09-18`

**What:** Bounded evidence-aware screening pilot

**Phase/decision:** Early search/method development; exact decision attribution: bilinmiyor.

**Key result:** Of 12 provisionally inspected groups: five supported the four abstract scope criteria, six were ambiguous, one had no abstract. The 160-group ledger and user selection were not changed.

**Size:** 71,578 bytes (0.068 MiB), 12 files. **Read evidence:** `result.md`, `OZET-SILINENLER.md`.

**Loss if dropped:** Deletion note already reports 4 dosya, 0.0 MB. Original raw reconstruction is unavailable from this directory alone. Dropping the remaining summaries/logs also loses the recorded excerpts, errors and audit trail.

**Tracked context:** [docs/archive/local-runs.md](local-runs.md).

<a id="run-archive-early-quantum-feature-filter-2026-09-18-plan-c"></a>

### `archive/early/quantum-feature-filter-2026-09-18-plan-c`

**What:** Technical-feature filter preparation, plan C

**Phase/decision:** Early search/method development; exact decision attribution: bilinmiyor.

**Key result:** Surviving material is a plan/review or implementation hand-back. A separate executed measurement outcome is bilinmiyor; consult the linked tracked record for later disposition.

**Size:** 228 bytes (0.000 MiB), 1 files. **Read evidence:** `OZET-SILINENLER.md`.

**Loss if dropped:** Deletion note already reports 1 dosya, 0.0 MB. Original raw reconstruction is unavailable from this directory alone. Dropping the remaining summaries/logs also loses the recorded excerpts, errors and audit trail.

**Tracked context:** [docs/archive/local-runs.md](local-runs.md).

<a id="run-archive-early-quantum-feature-filter-2026-09-18-run-c"></a>

### `archive/early/quantum-feature-filter-2026-09-18-run-c`

**What:** Isolated technical-feature query comparison

**Phase/decision:** Early search/method development; exact decision attribution: bilinmiyor.

**Key result:** Twenty completed calls, ten per arm: B replay 953 rows/895 identities, feature guard 953/887; 726 shared identities. Discovery counts only; no relevance or inclusion judgement.

**Size:** 10,946 bytes (0.010 MiB), 4 files. **Read evidence:** `result.md`, `OZET-SILINENLER.md`.

**Loss if dropped:** Deletion note already reports 25 dosya, 19.2 MB. Original raw reconstruction is unavailable from this directory alone. Dropping the remaining summaries/logs also loses the recorded excerpts, errors and audit trail.

**Tracked context:** [docs/archive/local-runs.md](local-runs.md).

<a id="run-archive-early-quantum-fulltext-timing-2026-09-18"></a>

### `archive/early/quantum-fulltext-timing-2026-09-18`

**What:** Quantum full-text acquisition, arXiv-source and timing diagnostics

**Phase/decision:** Early search/method development; exact decision attribution: bilinmiyor.

**Key result:** The complete run outcome is bilinmiyor from the surviving summary files. Deletion notes or scripts alone do not establish a successful run; linked tracked notes may preserve a bounded historical result.

**Size:** 6,982,514 bytes (6.659 MiB), 45 files. **Read evidence:** `OZET-SILINENLER.md`.

**Loss if dropped:** Deletion note already reports 15 dosya, 5.0 MB. Original raw reconstruction is unavailable from this directory alone. Dropping the remaining summaries/logs also loses the recorded excerpts, errors and audit trail.

**Tracked context:** [docs/archive/local-runs.md](local-runs.md), [docs/archive/sw/sw-slice10-background-fulltext-fetch.md](sw/sw-slice10-background-fulltext-fetch.md), [docs/archive/search-2026-09/search-workflow-review-2026-09-18.md](search-2026-09/search-workflow-review-2026-09-18.md).

<a id="run-archive-early-quantum-human-queue-2026-09-18"></a>

### `archive/early/quantum-human-queue-2026-09-18`

**What:** First human review queue (offline)

**Phase/decision:** Early search/method development; exact decision attribution: bilinmiyor.

**Key result:** An offline first queue of 40 groups; 113 non-selected/non-excluded groups remain deferred and seven retain provisional exclusion. No PDF reading and no final included-study count.

**Size:** 26,646 bytes (0.025 MiB), 5 files. **Read evidence:** `result.md`, `OZET-SILINENLER.md`.

**Loss if dropped:** Deletion note already reports 1 dosya, 0.1 MB. Original raw reconstruction is unavailable from this directory alone. Dropping the remaining summaries/logs also loses the recorded excerpts, errors and audit trail.

**Tracked context:** [docs/archive/local-runs.md](local-runs.md).

<a id="run-archive-early-quantum-hybrid-500-1000-2026-09-18-plan-a"></a>

### `archive/early/quantum-hybrid-500-1000-2026-09-18-plan-a`

**What:** Preparation rejected before discovery

**Phase/decision:** Early search/method development; exact decision attribution: bilinmiyor.

**Key result:** Preparation rejected before discovery: two compact queries ended in generic terms. No OpenAlex search, graph, PDF, or Elicit comparison from plan A.

**Size:** 772 bytes (0.001 MiB), 2 files. **Read evidence:** `OZET-SILINENLER.md`.

**Loss if dropped:** Deletion note already reports 1 dosya, 0.0 MB. Original raw reconstruction is unavailable from this directory alone. Dropping the remaining summaries/logs also loses the recorded excerpts, errors and audit trail.

**Tracked context:** [docs/archive/local-runs.md](local-runs.md).

<a id="run-archive-early-quantum-hybrid-500-1000-2026-09-18-plan-b"></a>

### `archive/early/quantum-hybrid-500-1000-2026-09-18-plan-b`

**What:** Hybrid 500/1000 discovery preparation, plan B

**Phase/decision:** Early search/method development; exact decision attribution: bilinmiyor.

**Key result:** Surviving material is a plan/review or implementation hand-back. A separate executed measurement outcome is bilinmiyor; consult the linked tracked record for later disposition.

**Size:** 229 bytes (0.000 MiB), 1 files. **Read evidence:** `OZET-SILINENLER.md`.

**Loss if dropped:** Deletion note already reports 1 dosya, 0.0 MB. Original raw reconstruction is unavailable from this directory alone. Dropping the remaining summaries/logs also loses the recorded excerpts, errors and audit trail.

**Tracked context:** [docs/archive/local-runs.md](local-runs.md).

<a id="run-archive-early-quantum-hybrid-500-1000-2026-09-18-run-b"></a>

### `archive/early/quantum-hybrid-500-1000-2026-09-18-run-b`

**What:** Isolated 500→1000 quantum search: execution ledger

**Phase/decision:** Early search/method development; exact decision attribution: bilinmiyor.

**Key result:** Discovery completed with partial PDF acquisition: 962 all-route rows, 674 exact identities, 20 PDFs selected, five readable, zero human-assessed. Sixteen OpenAlex logical calls completed.

**Size:** 455,211 bytes (0.434 MiB), 13 files. **Read evidence:** `result.md`, `OZET-SILINENLER.md`.

**Loss if dropped:** Deletion note already reports 45 dosya, 12.2 MB. Original raw reconstruction is unavailable from this directory alone. Dropping the remaining summaries/logs also loses the recorded excerpts, errors and audit trail.

**Tracked context:** [docs/archive/local-runs.md](local-runs.md), [docs/methods/quantum-query-branches-isolated-2026-09-18.md](../methods/quantum-query-branches-isolated-2026-09-18.md).

<a id="run-archive-early-quantum-model-screen-2026-09-18-run-d"></a>

### `archive/early/quantum-model-screen-2026-09-18-run-d`

**What:** DEIXIS isolated quantum-network model screen : 18 September 2026

**Phase/decision:** Early search/method development; exact decision attribution: bilinmiyor.

**Key result:** The result distinguishes candidate identities from studies: 1,104 prior and 1,475 expanded identities; at least 19 provisional same-title version pairs. Model screening is provisional and no user inclusion approval occurred.

**Size:** 846,643 bytes (0.807 MiB), 25 files. **Read evidence:** `result.md`, `OZET-SILINENLER.md`.

**Loss if dropped:** Deletion note already reports 69 dosya, 13.1 MB. Original raw reconstruction is unavailable from this directory alone. Dropping the remaining summaries/logs also loses the recorded excerpts, errors and audit trail.

**Tracked context:** [docs/archive/local-runs.md](local-runs.md).

<a id="run-archive-early-quantum-openalex-keywords-2026-09-18-plan-o"></a>

### `archive/early/quantum-openalex-keywords-2026-09-18-plan-o`

**What:** OpenAlex-assigned keyword preparation, plan O

**Phase/decision:** Early search/method development; exact decision attribution: bilinmiyor.

**Key result:** Surviving material is a plan/review or implementation hand-back. A separate executed measurement outcome is bilinmiyor; consult the linked tracked record for later disposition.

**Size:** 231 bytes (0.000 MiB), 1 files. **Read evidence:** `OZET-SILINENLER.md`.

**Loss if dropped:** Deletion note already reports 3 dosya, 0.0 MB. Original raw reconstruction is unavailable from this directory alone. Dropping the remaining summaries/logs also loses the recorded excerpts, errors and audit trail.

**Tracked context:** [docs/archive/local-runs.md](local-runs.md).

<a id="run-archive-early-quantum-openalex-keywords-2026-09-18-run-o"></a>

### `archive/early/quantum-openalex-keywords-2026-09-18-run-o`

**What:** Isolated OpenAlex-assigned keyword round

**Phase/decision:** Early search/method development; exact decision attribution: bilinmiyor.

**Key result:** Two completed calls returned 200 identities, 103 incremental to C. Keywords were OpenAlex-assigned, not author-supplied; no downstream reading or inclusion.

**Size:** 720 bytes (0.001 MiB), 2 files. **Read evidence:** `result.md`, `OZET-SILINENLER.md`.

**Loss if dropped:** Deletion note already reports 5 dosya, 2.0 MB. Original raw reconstruction is unavailable from this directory alone. Dropping the remaining summaries/logs also loses the recorded excerpts, errors and audit trail.

**Tracked context:** [docs/archive/local-runs.md](local-runs.md).

<a id="run-archive-early-quantum-probe-stopping-2026-09-20"></a>

### `archive/early/quantum-probe-stopping-2026-09-20`

**What:** Result, 2026-09-20 (`run.py`, `result.json`; no request, no model call)

**Phase/decision:** Early search/method development; exact decision attribution: bilinmiyor.

**Key result:** Offline stopping/probe comparison uses 31 high-confidence positives, 51 confirmed positives, 19 in-scope negatives, and no verified out-of-scope negative in the ledger. It cannot estimate out-of-scope specificity.

**Size:** 31,269 bytes (0.030 MiB), 5 files. **Read evidence:** `result.md`, `OZET-SILINENLER.md`.

**Loss if dropped:** Deletion note already reports 5 dosya, 3.0 MB. Original raw reconstruction is unavailable from this directory alone. Dropping the remaining summaries/logs also loses the recorded excerpts, errors and audit trail.

**Tracked context:** [docs/archive/local-runs.md](local-runs.md), [docs/archive/search-2026-09/search-workflow-review-2026-09-18.md](search-2026-09/search-workflow-review-2026-09-18.md).

<a id="run-archive-early-quantum-query-branches-2026-09-18-eval-b"></a>

### `archive/early/quantum-query-branches-2026-09-18-eval-b`

**What:** Post-run control and Elicit identity comparison

**Phase/decision:** Early search/method development; exact decision attribution: bilinmiyor.

**Key result:** Post-run comparison: frozen vs hybrid finds four vs six of six control DOIs; six vs eight of eight Elicit DOIs, plus the DOI-less title in both. Development-known controls, not independent recall.

**Size:** 8,228 bytes (0.008 MiB), 3 files. **Read evidence:** `result.md`, `OZET-SILINENLER.md`.

**Loss if dropped:** Deletion note already reports 1 dosya, 0.0 MB. Original raw reconstruction is unavailable from this directory alone. Dropping the remaining summaries/logs also loses the recorded excerpts, errors and audit trail.

**Tracked context:** [docs/archive/local-runs.md](local-runs.md).

<a id="run-archive-early-quantum-query-branches-2026-09-18-plan-a"></a>

### `archive/early/quantum-query-branches-2026-09-18-plan-a`

**What:** Rejected prepared plan before any OpenAlex discovery request

**Phase/decision:** Early search/method development; exact decision attribution: bilinmiyor.

**Key result:** Plan A rejected before provider discovery: the model assigned a reporting feature to the context branch. This is a semantic planning defect, not zero search results.

**Size:** 1,139 bytes (0.001 MiB), 2 files. **Read evidence:** `OZET-SILINENLER.md`.

**Loss if dropped:** Deletion note already reports 1 dosya, 0.0 MB. Original raw reconstruction is unavailable from this directory alone. Dropping the remaining summaries/logs also loses the recorded excerpts, errors and audit trail.

**Tracked context:** [docs/archive/local-runs.md](local-runs.md).

<a id="run-archive-early-quantum-query-branches-2026-09-18-plan-b"></a>

### `archive/early/quantum-query-branches-2026-09-18-plan-b`

**What:** Plan B preflight before OpenAlex requests

**Phase/decision:** Early search/method development; exact decision attribution: bilinmiyor.

**Key result:** Plan B passed the preflight query-shape and request-budget checks, with imperfect mechanism/constraint grouping left frozen. Preparation alone establishes no discovery outcome.

**Size:** 1,094 bytes (0.001 MiB), 2 files. **Read evidence:** `OZET-SILINENLER.md`.

**Loss if dropped:** Deletion note already reports 1 dosya, 0.0 MB. Original raw reconstruction is unavailable from this directory alone. Dropping the remaining summaries/logs also loses the recorded excerpts, errors and audit trail.

**Tracked context:** [docs/archive/local-runs.md](local-runs.md), [docs/methods/quantum-feature-filter-isolated-2026-09-18.md](../methods/quantum-feature-filter-isolated-2026-09-18.md).

<a id="run-archive-early-quantum-query-branches-2026-09-18-run-b"></a>

### `archive/early/quantum-query-branches-2026-09-18-run-b`

**What:** Isolated query-branch comparison

**Phase/decision:** Early search/method development; exact decision attribution: bilinmiyor.

**Key result:** Twenty calls completed: frozen arm 842 rows/599 identities; hybrid 953/895; shared 174. No graph, PDF, human screening, inclusion, or exclusion.

**Size:** 953 bytes (0.001 MiB), 2 files. **Read evidence:** `result.md`, `OZET-SILINENLER.md`.

**Loss if dropped:** Deletion note already reports 25 dosya, 18.5 MB. Original raw reconstruction is unavailable from this directory alone. Dropping the remaining summaries/logs also loses the recorded excerpts, errors and audit trail.

**Tracked context:** [docs/archive/local-runs.md](local-runs.md).

<a id="run-archive-early-quantum-queue-design-2026-09-19"></a>

### `archive/early/quantum-queue-design-2026-09-19`

**What:** Offline application of the quantum human-queue design

**Phase/decision:** Early search/method development; exact decision attribution: bilinmiyor.

**Key result:** The complete run outcome is bilinmiyor from the surviving summary files. Deletion notes or scripts alone do not establish a successful run; linked tracked notes may preserve a bounded historical result.

**Size:** 32,398 bytes (0.031 MiB), 3 files. **Read evidence:** `OZET-SILINENLER.md`.

**Loss if dropped:** Deletion note already reports 1 dosya, 0.0 MB. Original raw reconstruction is unavailable from this directory alone. Dropping the remaining summaries/logs also loses the recorded excerpts, errors and audit trail.

**Tracked context:** [docs/archive/local-runs.md](local-runs.md), [docs/archive/search-2026-09/search-workflow-review-2026-09-18.md](search-2026-09/search-workflow-review-2026-09-18.md).

<a id="run-archive-early-quantum-rank-fusion-2026-09-18"></a>

### `archive/early/quantum-rank-fusion-2026-09-18`

**What:** Quantum rank fusion, embeddings and abstract code-stage experiments

**Phase/decision:** Early search/method development; cited under D79.

**Key result:** The complete run outcome is bilinmiyor from the surviving summary files. Deletion notes or scripts alone do not establish a successful run; linked tracked notes may preserve a bounded historical result.

**Size:** 387,700 bytes (0.370 MiB), 12 files. **Read evidence:** `OZET-SILINENLER.md`.

**Loss if dropped:** Deletion note already reports 16 dosya, 21.0 MB. Original raw reconstruction is unavailable from this directory alone. Dropping the remaining summaries/logs also loses the recorded excerpts, errors and audit trail.

**Tracked context:** [docs/archive/local-runs.md](local-runs.md), [docs/archive/sw/sw-slice07-record-ranking.md](sw/sw-slice07-record-ranking.md), [docs/archive/sw/sw-slice04b-data-expansion.md](sw/sw-slice04b-data-expansion.md).

<a id="run-archive-early-quantum-seed-hist-abane-2026-09-18-run-e"></a>

### `archive/early/quantum-seed-hist-abane-2026-09-18-run-e`

**What:** Seed + histogram versus Abane term search: frozen run E

**Phase/decision:** Early search/method development; exact decision attribution: bilinmiyor.

**Key result:** Six OpenAlex calls and six Gemini screening batches completed. Two histogram terms added no agent-supported new on-task work in the first 50 targeted results. This is a bounded negative result.

**Size:** 71,091 bytes (0.068 MiB), 14 files. **Read evidence:** `result.md`, `OZET-SILINENLER.md`.

**Loss if dropped:** Deletion note already reports 24 dosya, 9.1 MB. Original raw reconstruction is unavailable from this directory alone. Dropping the remaining summaries/logs also loses the recorded excerpts, errors and audit trail.

**Tracked context:** [docs/archive/local-runs.md](local-runs.md).

<a id="run-archive-early-quantum-seed-hist-abane-2026-09-18-run-f"></a>

### `archive/early/quantum-seed-hist-abane-2026-09-18-run-f`

**What:** Adaptive sensitivity run F: isolated ILP and Abane terms

**Phase/decision:** Early search/method development; exact decision attribution: bilinmiyor.

**Key result:** Post-run-E adaptive sensitivity analysis, four completed OpenAlex calls. Seed/histogram selected 50 work slots; Abane bibliography terms selected 46. Survey acquisition was an unmatched setup cost; no independent confirmation.

**Size:** 29,814 bytes (0.028 MiB), 9 files. **Read evidence:** `result.md`, `OZET-SILINENLER.md`.

**Loss if dropped:** Deletion note already reports 18 dosya, 2.0 MB. Original raw reconstruction is unavailable from this directory alone. Dropping the remaining summaries/logs also loses the recorded excerpts, errors and audit trail.

**Tracked context:** [docs/archive/local-runs.md](local-runs.md).

<a id="run-archive-early-quantum-source-comparison-2026-09-18"></a>

### `archive/early/quantum-source-comparison-2026-09-18`

**What:** Quantum provider, seed and citation-chain source comparisons

**Phase/decision:** Early search/method development; cited under D76.

**Key result:** The complete run outcome is bilinmiyor from the surviving summary files. Deletion notes or scripts alone do not establish a successful run; linked tracked notes may preserve a bounded historical result.

**Size:** 43,061 bytes (0.041 MiB), 11 files. **Read evidence:** `OZET-SILINENLER.md`.

**Loss if dropped:** Deletion note already reports 15 dosya, 1.0 MB. Original raw reconstruction is unavailable from this directory alone. Dropping the remaining summaries/logs also loses the recorded excerpts, errors and audit trail.

**Tracked context:** [docs/archive/local-runs.md](local-runs.md), [docs/archive/sw/sw-slice04b-data-expansion.md](sw/sw-slice04b-data-expansion.md), [docs/archive/sw/sw-slice05-survey-flag-abstract-lookup-links.md](sw/sw-slice05-survey-flag-abstract-lookup-links.md).

<a id="run-archive-early-quantum-survey-2026-09-18-plan-s"></a>

### `archive/early/quantum-survey-2026-09-18-plan-s`

**What:** Survey discovery preparation, plan S

**Phase/decision:** Early search/method development; exact decision attribution: bilinmiyor.

**Key result:** Surviving material is a plan/review or implementation hand-back. A separate executed measurement outcome is bilinmiyor; consult the linked tracked record for later disposition.

**Size:** 220 bytes (0.000 MiB), 1 files. **Read evidence:** `OZET-SILINENLER.md`.

**Loss if dropped:** Deletion note already reports 1 dosya, 0.0 MB. Original raw reconstruction is unavailable from this directory alone. Dropping the remaining summaries/logs also loses the recorded excerpts, errors and audit trail.

**Tracked context:** [docs/archive/local-runs.md](local-runs.md).

<a id="run-archive-early-quantum-survey-2026-09-18-run-s"></a>

### `archive/early/quantum-survey-2026-09-18-run-s`

**What:** Isolated survey discovery

**Phase/decision:** Early search/method development; exact decision attribution: bilinmiyor.

**Key result:** Six completed calls: 127 rows, 119 exact identities, 114 DOI identities; 23 title survey/review/taxonomy signals. Signals remain provisional; no full-text screening or inclusion.

**Size:** 621 bytes (0.001 MiB), 2 files. **Read evidence:** `result.md`, `OZET-SILINENLER.md`.

**Loss if dropped:** Deletion note already reports 10 dosya, 1.9 MB. Original raw reconstruction is unavailable from this directory alone. Dropping the remaining summaries/logs also loses the recorded excerpts, errors and audit trail.

**Tracked context:** [docs/archive/local-runs.md](local-runs.md).

<a id="run-archive-early-quantum-work-adjudication-2026-09-18"></a>

### `archive/early/quantum-work-adjudication-2026-09-18`

**What:** D-run provisional includes: work-level audit

**Phase/decision:** Early search/method development; exact decision attribution: bilinmiyor.

**Key result:** The audit groups 182 provisional identities into a 160-group ledger; REPORT.md records per-feature reading depth and a contradictory heuristic-only finding. Model-selected passages and model judgements do not supply final human-approved inclusion.

**Size:** 11,163,681 bytes (10.647 MiB), 147 files. **Read evidence:** `result.md`, `REPORT.md`, `OZET-SILINENLER.md`.

**Loss if dropped:** Deletion note already reports 732 dosya, 16.4 MB. Original raw reconstruction is unavailable from this directory alone. Dropping the remaining summaries/logs also loses the recorded excerpts, errors and audit trail.

**Tracked context:** [docs/archive/local-runs.md](local-runs.md), [docs/archive/sw/sw-slice19-probe-tables.md](sw/sw-slice19-probe-tables.md), [docs/archive/sw/sw-slice24-measurement-campaign.md](sw/sw-slice24-measurement-campaign.md).

<a id="run-archive-early-recall-probe-2026-09-17"></a>

### `archive/early/recall-probe-2026-09-17`

**What:** Known-source rank/depth recall probes

**Phase/decision:** Early search/method development; exact decision attribution: bilinmiyor.

**Key result:** The complete run outcome is bilinmiyor from the surviving summary files. Deletion notes or scripts alone do not establish a successful run; linked tracked notes may preserve a bounded historical result.

**Size:** 6,804 bytes (0.006 MiB), 4 files. **Read evidence:** `OZET-SILINENLER.md`.

**Loss if dropped:** Deletion note already reports 1 dosya, 0.0 MB. Original raw reconstruction is unavailable from this directory alone. Dropping the remaining summaries/logs also loses the recorded excerpts, errors and audit trail.

**Tracked context:** [docs/archive/local-runs.md](local-runs.md), [docs/archive/search-2026-09/search-recall-depth-2026-09-17.md](search-2026-09/search-recall-depth-2026-09-17.md).

<a id="run-archive-early-search-adaptation-2026-09-17"></a>

### `archive/early/search-adaptation-2026-09-17`

**What:** Initial adaptive-search development experiment

**Phase/decision:** Early search/method development; exact decision attribution: bilinmiyor.

**Key result:** The complete run outcome is bilinmiyor from the surviving summary files. Deletion notes or scripts alone do not establish a successful run; linked tracked notes may preserve a bounded historical result.

**Size:** 8,673 bytes (0.008 MiB), 1 files. **Read evidence:** `OZET-SILINENLER.md`.

**Loss if dropped:** Deletion note already reports 41 dosya, 5.5 MB. Original raw reconstruction is unavailable from this directory alone. Dropping the remaining summaries/logs also loses the recorded excerpts, errors and audit trail.

**Tracked context:** [docs/archive/search-2026-09/search-adaptation-development-results-2026-09-17.md](search-2026-09/search-adaptation-development-results-2026-09-17.md), [docs/archive/local-runs.md](local-runs.md), [docs/archive/search-2026-09/search-adaptation-experiment-2026-09-17.md](search-2026-09/search-adaptation-experiment-2026-09-17.md).

<a id="run-archive-early-search-adaptation-2026-09-17-v2"></a>

### `archive/early/search-adaptation-2026-09-17-v2`

**What:** Second adaptive-search development experiment

**Phase/decision:** Early search/method development; exact decision attribution: bilinmiyor.

**Key result:** The complete run outcome is bilinmiyor from the surviving summary files. Deletion notes or scripts alone do not establish a successful run; linked tracked notes may preserve a bounded historical result.

**Size:** 8,815 bytes (0.008 MiB), 1 files. **Read evidence:** `OZET-SILINENLER.md`.

**Loss if dropped:** Deletion note already reports 41 dosya, 6.1 MB. Original raw reconstruction is unavailable from this directory alone. Dropping the remaining summaries/logs also loses the recorded excerpts, errors and audit trail.

**Tracked context:** [docs/archive/search-2026-09/search-adaptation-development-results-2026-09-17.md](search-2026-09/search-adaptation-development-results-2026-09-17.md), [docs/archive/local-runs.md](local-runs.md), [docs/archive/search-2026-09/search-adaptation-experiment-2026-09-17.md](search-2026-09/search-adaptation-experiment-2026-09-17.md).

<a id="run-archive-early-search-compact-development-2026-09-17"></a>

### `archive/early/search-compact-development-2026-09-17`

**What:** Compact-query development experiment

**Phase/decision:** Early search/method development; exact decision attribution: bilinmiyor.

**Key result:** The complete run outcome is bilinmiyor from the surviving summary files. Deletion notes or scripts alone do not establish a successful run; linked tracked notes may preserve a bounded historical result.

**Size:** 3,028 bytes (0.003 MiB), 1 files. **Read evidence:** `OZET-SILINENLER.md`.

**Loss if dropped:** Deletion note already reports 38 dosya, 10.1 MB. Original raw reconstruction is unavailable from this directory alone. Dropping the remaining summaries/logs also loses the recorded excerpts, errors and audit trail.

**Tracked context:** [docs/archive/local-runs.md](local-runs.md), [docs/archive/experiments.md](experiments.md), [docs/archive/search-2026-09/search-compact-development-2026-09-17.md](search-2026-09/search-compact-development-2026-09-17.md).

<a id="run-archive-early-search-diverse-query-development-2026-09-17"></a>

### `archive/early/search-diverse-query-development-2026-09-17`

**What:** Diverse-query development experiment

**Phase/decision:** Early search/method development; exact decision attribution: bilinmiyor.

**Key result:** The complete run outcome is bilinmiyor from the surviving summary files. Deletion notes or scripts alone do not establish a successful run; linked tracked notes may preserve a bounded historical result.

**Size:** 1,803 bytes (0.002 MiB), 1 files. **Read evidence:** `OZET-SILINENLER.md`.

**Loss if dropped:** Deletion note already reports 53 dosya, 1.2 MB. Original raw reconstruction is unavailable from this directory alone. Dropping the remaining summaries/logs also loses the recorded excerpts, errors and audit trail.

**Tracked context:** [docs/archive/search-2026-09/search-diverse-query-development-results-2026-09-17.md](search-2026-09/search-diverse-query-development-results-2026-09-17.md), [docs/archive/local-runs.md](local-runs.md).

<a id="run-archive-early-search-equal-budget-2026-09-17"></a>

### `archive/early/search-equal-budget-2026-09-17`

**What:** Equal-budget search and secondary Gemini embedding result

**Phase/decision:** Early search/method development; exact decision attribution: bilinmiyor.

**Key result:** Equal-budget six-question search component: compiler arm found zero of 12 controls; diverse short-query arm found nine of 12. 42 provider calls and 18 Luna proposal calls completed; reused controls and secondary embedding analysis limit interpretation.

**Size:** 29,336 bytes (0.028 MiB), 7 files. **Read evidence:** `RESULT.md`, `OZET-SILINENLER.md`.

**Loss if dropped:** Deletion note already reports 137 dosya, 11.5 MB. Original raw reconstruction is unavailable from this directory alone. Dropping the remaining summaries/logs also loses the recorded excerpts, errors and audit trail.

**Tracked context:** [docs/archive/local-runs.md](local-runs.md).

<a id="run-archive-early-search-fable-short-query-2026-09-17"></a>

### `archive/early/search-fable-short-query-2026-09-17`

**What:** Fable consultation and isolated compact-query diagnostic

**Phase/decision:** Early search/method development; cited under D64.

**Key result:** Reused-case compact-query comparison: zero vs three of 17 selected DOI controls, 375 vs 577 returned rows. Fable advice was advisory and the comparison was not independent validation.

**Size:** 14,278 bytes (0.014 MiB), 5 files. **Read evidence:** `RESULT.md`, `OZET-SILINENLER.md`.

**Loss if dropped:** Deletion note already reports 93 dosya, 9.9 MB. Original raw reconstruction is unavailable from this directory alone. Dropping the remaining summaries/logs also loses the recorded excerpts, errors and audit trail.

**Tracked context:** [docs/archive/local-runs.md](local-runs.md).

<a id="run-archive-early-search-flow-diagram-2026-09-18"></a>

### `archive/early/search-flow-diagram-2026-09-18`

**What:** İzole arama kolları ve aday uzlaştırması

**Phase/decision:** Early search/method development; exact decision attribution: bilinmiyor.

**Key result:** The surviving Mermaid diagram describes isolated arm union into 1,104 unscreened candidate identities. The PNG is listed as deleted; a diagram is not a executed screening result.

**Size:** 2,916 bytes (0.003 MiB), 2 files. **Read evidence:** `OZET-SILINENLER.md`.

**Loss if dropped:** Deletion note already reports 1 dosya, 0.3 MB. Original raw reconstruction is unavailable from this directory alone. Dropping the remaining summaries/logs also loses the recorded excerpts, errors and audit trail.

**Tracked context:** [docs/archive/local-runs.md](local-runs.md).

<a id="run-archive-early-search-method-holdout-2026-09-17"></a>

### `archive/early/search-method-holdout-2026-09-17`

**What:** Search-method holdout experiment

**Phase/decision:** Early search/method development; exact decision attribution: bilinmiyor.

**Key result:** The complete run outcome is bilinmiyor from the surviving summary files. Deletion notes or scripts alone do not establish a successful run; linked tracked notes may preserve a bounded historical result.

**Size:** 5,097 bytes (0.005 MiB), 1 files. **Read evidence:** `OZET-SILINENLER.md`.

**Loss if dropped:** Deletion note already reports 111 dosya, 6.7 MB. Original raw reconstruction is unavailable from this directory alone. Dropping the remaining summaries/logs also loses the recorded excerpts, errors and audit trail.

**Tracked context:** [docs/archive/local-runs.md](local-runs.md).

<a id="run-archive-early-search-method-validation-2026-09-17"></a>

### `archive/early/search-method-validation-2026-09-17`

**What:** Search-method validation experiment

**Phase/decision:** Early search/method development; exact decision attribution: bilinmiyor.

**Key result:** The complete run outcome is bilinmiyor from the surviving summary files. Deletion notes or scripts alone do not establish a successful run; linked tracked notes may preserve a bounded historical result.

**Size:** 3,217 bytes (0.003 MiB), 1 files. **Read evidence:** `OZET-SILINENLER.md`.

**Loss if dropped:** Deletion note already reports 63 dosya, 10.1 MB. Original raw reconstruction is unavailable from this directory alone. Dropping the remaining summaries/logs also loses the recorded excerpts, errors and audit trail.

**Tracked context:** [docs/archive/search-2026-09/search-method-validation-results-2026-09-17.md](search-2026-09/search-method-validation-results-2026-09-17.md), [docs/archive/local-runs.md](local-runs.md), [docs/archive/search-2026-09/search-diverse-query-development-2026-09-17.md](search-2026-09/search-diverse-query-development-2026-09-17.md).

<a id="run-archive-early-search-plan-core-2026-09-17"></a>

### `archive/early/search-plan-core-2026-09-17`

**What:** Core-concept search-plan trial

**Phase/decision:** Early search/method development; cited under D57.

**Key result:** Surviving material is a plan/review or implementation hand-back. A separate executed measurement outcome is bilinmiyor; consult the linked tracked record for later disposition.

**Size:** 3,234 bytes (0.003 MiB), 2 files. **Read evidence:** `OZET-SILINENLER.md`.

**Loss if dropped:** Deletion note already reports 3 dosya, 0.1 MB. Original raw reconstruction is unavailable from this directory alone. Dropping the remaining summaries/logs also loses the recorded excerpts, errors and audit trail.

**Tracked context:** [docs/archive/local-runs.md](local-runs.md).

<a id="run-archive-early-search-provider-complement-2026-09-17"></a>

### `archive/early/search-provider-complement-2026-09-17`

**What:** Search-provider complement experiment

**Phase/decision:** Early search/method development; exact decision attribution: bilinmiyor.

**Key result:** The complete run outcome is bilinmiyor from the surviving summary files. Deletion notes or scripts alone do not establish a successful run; linked tracked notes may preserve a bounded historical result.

**Size:** 2,183 bytes (0.002 MiB), 1 files. **Read evidence:** `OZET-SILINENLER.md`.

**Loss if dropped:** Deletion note already reports 19 dosya, 1.5 MB. Original raw reconstruction is unavailable from this directory alone. Dropping the remaining summaries/logs also loses the recorded excerpts, errors and audit trail.

**Tracked context:** [docs/archive/local-runs.md](local-runs.md), [docs/archive/search-2026-09/search-provider-complement-development-2026-09-17.md](search-2026-09/search-provider-complement-development-2026-09-17.md).

<a id="run-archive-early-search-workflow-pilot-2026-09-17"></a>

### `archive/early/search-workflow-pilot-2026-09-17`

**What:** One-question underwater-routing retrieval pilot

**Phase/decision:** Early search/method development; exact decision attribution: bilinmiyor.

**Key result:** Underwater-routing pilot: current search found two of three known DOIs; four extra short queries added HydroCast for three of three. The closest equal-record comparison uses different request counts.

**Size:** 24,314 bytes (0.023 MiB), 4 files. **Read evidence:** `REPORT.md`, `OZET-SILINENLER.md`.

**Loss if dropped:** Deletion note already reports 40 dosya, 5.7 MB. Original raw reconstruction is unavailable from this directory alone. Dropping the remaining summaries/logs also loses the recorded excerpts, errors and audit trail.

**Tracked context:** [docs/archive/local-runs.md](local-runs.md).

<a id="run-archive-early-second-topic-packet-size-2026-09-20"></a>

### `archive/early/second-topic-packet-size-2026-09-20`

**What:** Result : second-topic generalisation check (packet size in WSNs)

**Phase/decision:** Early search/method development; exact decision attribution: bilinmiyor.

**Key result:** Second-topic WSN check used DeepSeek model labels, not human truth. Three criterion calls completed; 978 returned rows include one duplicate. It is a design repeat on a second topic, not validated generalization.

**Size:** 66,044 bytes (0.063 MiB), 10 files. **Read evidence:** `result.md`, `OZET-SILINENLER.md`.

**Loss if dropped:** Deletion note already reports 35 dosya, 9.7 MB. Original raw reconstruction is unavailable from this directory alone. Dropping the remaining summaries/logs also loses the recorded excerpts, errors and audit trail.

**Tracked context:** [docs/archive/local-runs.md](local-runs.md), [docs/archive/sw/sw-implementation-plan.md](sw/sw-implementation-plan.md), [docs/archive/sw/sw-slice03-record-kind-and-version-links.md](sw/sw-slice03-record-kind-and-version-links.md).

<a id="run-archive-sw-sw-abstract-batch-2026-09-21"></a>

### `archive/sw/sw-abstract-batch-2026-09-21`

**What:** Abstract-stage proposal: records per call, and a topic-free prompt (K3, slice 09) : 21 September 2026

**Phase/decision:** SW; cited under D81.

**Key result:** 408 DeepSeek calls, no failed call or handle error. Single-record and batched abstract proposals differ in disagreement and quote counts; the experiment measures consistency, not accuracy.

**Size:** 13,265 bytes (0.013 MiB), 5 files. **Read evidence:** `result.md`, `OZET-SILINENLER.md`.

**Loss if dropped:** Deletion note already reports 416 dosya, 1.4 MB. Original raw reconstruction is unavailable from this directory alone. Dropping the remaining summaries/logs also loses the recorded excerpts, errors and audit trail.

**Tracked context:** [docs/archive/local-runs.md](local-runs.md), [docs/archive/sw/sw-status.md](sw/sw-status.md), [docs/archive/sw/sw-slice09-abstract-screening.md](sw/sw-slice09-abstract-screening.md).

<a id="run-archive-sw-sw-abstract-lookup-2026-09-21"></a>

### `archive/sw/sw-abstract-lookup-2026-09-21`

**What:** SW abstract lookup dry run

**Phase/decision:** SW; cited under D77.

**Key result:** The complete run outcome is bilinmiyor from the surviving summary files. Deletion notes or scripts alone do not establish a successful run; linked tracked notes may preserve a bounded historical result.

**Size:** 217 bytes (0.000 MiB), 1 files. **Read evidence:** `OZET-SILINENLER.md`.

**Loss if dropped:** Deletion note already reports 2 dosya, 0.0 MB. Original raw reconstruction is unavailable from this directory alone. Dropping the remaining summaries/logs also loses the recorded excerpts, errors and audit trail.

**Tracked context:** [docs/archive/local-runs.md](local-runs.md), [docs/archive/sw/sw-status.md](sw/sw-status.md), [docs/archive/search-2026-09/search-workflow-review-2026-09-18.md](search-2026-09/search-workflow-review-2026-09-18.md).

<a id="run-archive-sw-sw-block-labelling-2026-09-21"></a>

### `archive/sw/sw-block-labelling-2026-09-21`

**What:** Blok atamasını modele sordurma denemesi : 21 Eylül 2026

**Phase/decision:** SW; exact decision attribution: bilinmiyor.

**Key result:** Eight questions, 28 extracted phrases, three label runs; all 24 model calls passed first try. Model labels filled four outcome blocks missed by code; failures/unavailability were not tested.

**Size:** 10,336 bytes (0.010 MiB), 2 files. **Read evidence:** `REPORT.md`, `OZET-SILINENLER.md`.

**Loss if dropped:** Deletion note already reports 7 dosya, 0.1 MB. Original raw reconstruction is unavailable from this directory alone. Dropping the remaining summaries/logs also loses the recorded excerpts, errors and audit trail.

**Tracked context:** [docs/archive/local-runs.md](local-runs.md), [docs/archive/sw/sw-status.md](sw/sw-status.md), [docs/archive/sw/sw-implementation-plan.md](sw/sw-implementation-plan.md).

<a id="run-archive-sw-sw-criterion-dry-run-2026-09-21"></a>

### `archive/sw/sw-criterion-dry-run-2026-09-21`

**What:** Slice 06 dry run : the criterion step on the live DeepSeek connection

**Phase/decision:** SW; cited under D78.

**Key result:** The product criterion path made six DeepSeek calls on two questions; all six passed schema and contract first try. Zero provider requests; count probes were unknown because OpenAlex was not selected.

**Size:** 6,990 bytes (0.007 MiB), 2 files. **Read evidence:** `result.md`, `OZET-SILINENLER.md`.

**Loss if dropped:** Deletion note already reports 1 dosya, 0.0 MB. Original raw reconstruction is unavailable from this directory alone. Dropping the remaining summaries/logs also loses the recorded excerpts, errors and audit trail.

**Tracked context:** [docs/archive/local-runs.md](local-runs.md), [docs/archive/sw/sw-status.md](sw/sw-status.md), [docs/archive/sw/sw-slice25-pico-criterion.md](sw/sw-slice25-pico-criterion.md).

<a id="run-archive-sw-sw-criterion-prompt-fix-2026-09-21"></a>

### `archive/sw/sw-criterion-prompt-fix-2026-09-21`

**What:** Result : SW15.1 prompt fix, before slice 06 is built (2026-09-21)

**Phase/decision:** SW; cited under D78.

**Key result:** Thirty model calls completed. The packet-size criterion fix was explored, but result.md explicitly records a failed quantum regression. No second reader independently judged these prompts.

**Size:** 15,677 bytes (0.015 MiB), 3 files. **Read evidence:** `result.md`, `OZET-SILINENLER.md`.

**Loss if dropped:** Deletion note already reports 35 dosya, 0.1 MB. Original raw reconstruction is unavailable from this directory alone. Dropping the remaining summaries/logs also loses the recorded excerpts, errors and audit trail.

**Tracked context:** [docs/archive/local-runs.md](local-runs.md), [docs/archive/sw/sw-status.md](sw/sw-status.md), [docs/archive/sw/sw-implementation-plan.md](sw/sw-implementation-plan.md).

<a id="run-archive-sw-sw-expansion-dry-run-2026-09-21"></a>

### `archive/sw/sw-expansion-dry-run-2026-09-21`

**What:** SW data-expansion dry run

**Phase/decision:** SW; cited under D76.

**Key result:** The complete run outcome is bilinmiyor from the surviving summary files. Deletion notes or scripts alone do not establish a successful run; linked tracked notes may preserve a bounded historical result.

**Size:** 219 bytes (0.000 MiB), 1 files. **Read evidence:** `OZET-SILINENLER.md`.

**Loss if dropped:** Deletion note already reports 1 dosya, 0.0 MB. Original raw reconstruction is unavailable from this directory alone. Dropping the remaining summaries/logs also loses the recorded excerpts, errors and audit trail.

**Tracked context:** [docs/archive/local-runs.md](local-runs.md), [docs/archive/sw/sw-status.md](sw/sw-status.md), [docs/archive/sw/sw-slice04b-data-expansion.md](sw/sw-slice04b-data-expansion.md).

<a id="run-archive-sw-sw-measure-2026-09-22"></a>

### `archive/sw/sw-measure-2026-09-22`

**What:** D88 ölçümü : sonuç (22 Eylül 2026)

**Phase/decision:** SW; cited under D88.

**Key result:** D88 Luna timing: quick 12.1 min, standard 29.9 min, detailed partial 55.5 min. All answers structurally_valid; detailed reading paused on client_timeout after 119 calls. Structural validity is not semantic verification.

**Size:** 38,785 bytes (0.037 MiB), 15 files. **Read evidence:** `result.md`, `OZET-SILINENLER.md`.

**Loss if dropped:** Deletion note already reports 22 dosya, 0.7 MB. Original raw reconstruction is unavailable from this directory alone. Dropping the remaining summaries/logs also loses the recorded excerpts, errors and audit trail.

**Tracked context:** [docs/ROADMAP.md](../ROADMAP.md), [docs/archive/local-runs.md](local-runs.md), [docs/archive/sw/sw-status.md](sw/sw-status.md).

<a id="run-archive-sw-sw-measure-2026-09-22b"></a>

### `archive/sw/sw-measure-2026-09-22b`

**What:** Yeniden ölçüm (13e sonrası, 22 Eylül 2026)

**Phase/decision:** SW; cited under D88.

**Key result:** 13e remeasurement: quick 9.1 min and standard 26.2 min; detailed finished after one timeout resend. Fetch shortening and no detailed pause held; the standard timing expectation did not.

**Size:** 28,294 bytes (0.027 MiB), 11 files. **Read evidence:** `result.md`, `OZET-SILINENLER.md`.

**Loss if dropped:** Deletion note already reports 14 dosya, 0.5 MB. Original raw reconstruction is unavailable from this directory alone. Dropping the remaining summaries/logs also loses the recorded excerpts, errors and audit trail.

**Tracked context:** [docs/archive/local-runs.md](local-runs.md), [docs/archive/sw/sw-status.md](sw/sw-status.md), [docs/archive/sw/sw-measure-2026-09-22.md](sw/sw-measure-2026-09-22.md).

<a id="run-archive-sw-sw-measure-2026-09-24"></a>

### `archive/sw/sw-measure-2026-09-24`

**What:** D88 üçüncü ölçümü (13f + 13g + 13h sonrası, 23 Eylül 2026)

**Phase/decision:** SW; cited under D94, D93, D88.

**Key result:** Third D88 measurement: quick 7.5, standard 17.9, detailed 39.7 min; all completed with structurally_valid answers. Only quick met the new 10/15/20-minute targets.

**Size:** 35,588 bytes (0.034 MiB), 9 files. **Read evidence:** `result.md`, `OZET-SILINENLER.md`.

**Loss if dropped:** Deletion note already reports 15 dosya, 0.6 MB. Original raw reconstruction is unavailable from this directory alone. Dropping the remaining summaries/logs also loses the recorded excerpts, errors and audit trail.

**Tracked context:** [docs/archive/local-runs.md](local-runs.md), [docs/archive/sw/sw-status.md](sw/sw-status.md), [docs/archive/sw/sw-measure-2026-09-22.md](sw/sw-measure-2026-09-22.md).

<a id="run-archive-sw-sw-model-query-experiment-2026-09-23"></a>

### `archive/sw/sw-model-query-experiment-2026-09-23`

**What:** Sonuç: sorguyu model yazar (P kolu), 2026-09-23

**Phase/decision:** SW; cited under D92.

**Key result:** Only the P query-writing arm ran: nine completed Luna calls and 426 HTTP-200 OpenAlex requests. Other prompt arms did not run; the result does not compare all proposed arms.

**Size:** 8,257 bytes (0.008 MiB), 3 files. **Read evidence:** `result.md`, `OZET-SILINENLER.md`.

**Loss if dropped:** Deletion note already reports 40 dosya, 1.7 MB. Original raw reconstruction is unavailable from this directory alone. Dropping the remaining summaries/logs also loses the recorded excerpts, errors and audit trail.

**Tracked context:** [docs/archive/local-runs.md](local-runs.md), [docs/archive/sw/sw-status.md](sw/sw-status.md), [docs/archive/sw/sw-slice13h-model-query.md](sw/sw-slice13h-model-query.md).

<a id="run-archive-sw-sw-model-query-experiment-2026-09-24"></a>

### `archive/sw/sw-model-query-experiment-2026-09-24`

**What:** Sonuç: model yazılı sorgu, ikinci ölçüm (2026-09-23 gecesi)

**Phase/decision:** SW; exact decision attribution: bilinmiyor.

**Key result:** Second query trial: model-only failed the quantum gate (one run found 17, threshold 18); model+code passed (23 in all quantum runs, four in all packet runs). Product default adoption was still an owner decision in this result.

**Size:** 10,873 bytes (0.010 MiB), 3 files. **Read evidence:** `result.md`, `OZET-SILINENLER.md`.

**Loss if dropped:** Deletion note already reports 42 dosya, 3.1 MB. Original raw reconstruction is unavailable from this directory alone. Dropping the remaining summaries/logs also loses the recorded excerpts, errors and audit trail.

**Tracked context:** [docs/archive/local-runs.md](local-runs.md), [docs/archive/sw/sw-status.md](sw/sw-status.md), [docs/archive/sw/sw-slice13h-model-query.md](sw/sw-slice13h-model-query.md).

<a id="run-archive-sw-sw-paging-timing-2026-09-21"></a>

### `archive/sw/sw-paging-timing-2026-09-21`

**What:** SW provider paging timing probe

**Phase/decision:** SW; exact decision attribution: bilinmiyor.

**Key result:** The complete run outcome is bilinmiyor from the surviving summary files. Deletion notes or scripts alone do not establish a successful run; linked tracked notes may preserve a bounded historical result.

**Size:** 215 bytes (0.000 MiB), 1 files. **Read evidence:** `OZET-SILINENLER.md`.

**Loss if dropped:** Deletion note already reports 1 dosya, 0.0 MB. Original raw reconstruction is unavailable from this directory alone. Dropping the remaining summaries/logs also loses the recorded excerpts, errors and audit trail.

**Tracked context:** [docs/archive/local-runs.md](local-runs.md), [docs/archive/sw/sw-status.md](sw/sw-status.md), [docs/archive/sw/sw-slice04c-paging-and-read-budget.md](sw/sw-slice04c-paging-and-read-budget.md).

<a id="run-archive-sw-sw-ranking-replay-2026-09-21"></a>

### `archive/sw/sw-ranking-replay-2026-09-21`

**What:** SW slice 07 ranking replay

**Phase/decision:** SW; cited under D79.

**Key result:** The preserved replay-result.json records 1,369 records, 0.487 s pure computation, median positive rank 145.5 and eight of 20 positives in top 100. TF-IDF did not run because no verified seed existed.

**Size:** 3,508 bytes (0.003 MiB), 2 files. **Read evidence:** `OZET-SILINENLER.md`.

**Loss if dropped:** Deletion note already reports 2 dosya, 0.0 MB. Original raw reconstruction is unavailable from this directory alone. Dropping the remaining summaries/logs also loses the recorded excerpts, errors and audit trail.

**Tracked context:** [docs/archive/local-runs.md](local-runs.md), [docs/archive/sw/sw-status.md](sw/sw-status.md), [docs/archive/sw/sw-slice07-record-ranking.md](sw/sw-slice07-record-ranking.md).

<a id="run-archive-sw-sw-review-13bcd-2026-09-22"></a>

### `archive/sw/sw-review-13bcd-2026-09-22`

**What:** Purpose beyond the directory name is bilinmiyor; only the listed surviving files establish its contents.

**Phase/decision:** SW; exact decision attribution: bilinmiyor.

**Key result:** The review could not inspect code because the local command host was missing. It explicitly refuses to claim no findings. No verified code-review outcome.

**Size:** 1,234 bytes (0.001 MiB), 1 files. **Read evidence:** `answer-attempt1-no-tools.md`.

**Loss if dropped:** Dropping this material loses the exact review findings, response/disposition history and implementation hand-back; a plan or review cannot substitute for execution evidence.

**Tracked context:** [docs/archive/local-runs.md](local-runs.md).

<a id="run-archive-sw-sw-review-14-2026-09-23"></a>

### `archive/sw/sw-review-14-2026-09-23`

**What:** Purpose beyond the directory name is bilinmiyor; only the listed surviving files establish its contents.

**Phase/decision:** SW; exact decision attribution: bilinmiyor.

**Key result:** Read-only slice-14 review verdict: ready after fixes, not ready to commit. High findings concerned unsearched-source display and mutation of a waiting approval endpoint; live acceptance remained failed at that review time.

**Size:** 11,624 bytes (0.011 MiB), 2 files. **Read evidence:** `answer.md`.

**Loss if dropped:** Dropping this material loses the exact review findings, response/disposition history and implementation hand-back; a plan or review cannot substitute for execution evidence.

**Tracked context:** [docs/archive/local-runs.md](local-runs.md), [docs/archive/sw/sw-status.md](sw/sw-status.md).

<a id="run-archive-sw-sw-review-fixes-13fgh-2026-09-23"></a>

### `archive/sw/sw-review-fixes-13fgh-2026-09-23`

**What:** Purpose beyond the directory name is bilinmiyor; only the listed surviving files establish its contents.

**Phase/decision:** SW; exact decision attribution: bilinmiyor.

**Key result:** Read-only fixes review: ready after fixes, with unresolved stop, query-provenance and Scopus-quota cases. Reported test results were not independently rerun by the reviewer.

**Size:** 12,082 bytes (0.012 MiB), 2 files. **Read evidence:** `answer.md`.

**Loss if dropped:** Dropping this material loses the exact review findings, response/disposition history and implementation hand-back; a plan or review cannot substitute for execution evidence.

**Tracked context:** [docs/archive/local-runs.md](local-runs.md).

<a id="run-archive-sw-sw-s2-bulk-probe-2026-09-23"></a>

### `archive/sw/sw-s2-bulk-probe-2026-09-23`

**What:** Semantic Scholar bulk denemesi (23 Eylül 2026)

**Phase/decision:** SW; cited under D93, D88.

**Key result:** An isolated keyed Semantic Scholar bulk probe translates recorded OpenAlex queries to bulk syntax. Its result records limits and sorting effects; provider totals are estimates, not relevance or recall.

**Size:** 6,781 bytes (0.006 MiB), 2 files. **Read evidence:** `result.md`, `OZET-SILINENLER.md`.

**Loss if dropped:** Deletion note already reports 8 dosya, 1.3 MB. Original raw reconstruction is unavailable from this directory alone. Dropping the remaining summaries/logs also loses the recorded excerpts, errors and audit trail.

**Tracked context:** [docs/archive/local-runs.md](local-runs.md), [docs/archive/sw/sw-status.md](sw/sw-status.md), [docs/archive/sw/sw-measure-2026-09-22.md](sw/sw-measure-2026-09-22.md).

<a id="run-archive-sw-sw-slice13g-acceptance-2026-09-23"></a>

### `archive/sw/sw-slice13g-acceptance-2026-09-23`

**What:** Dilim 13g kabul ölçümü (2026-09-23): tutmadı

**Phase/decision:** SW slice 13g; cited under D90.

**Key result:** First 13g acceptance did not meet the recorded gate; 193 OpenAlex requests all HTTP 200, no new model calls. Labels came from the existing experimental library.

**Size:** 6,008 bytes (0.006 MiB), 2 files. **Read evidence:** `result.md`, `OZET-SILINENLER.md`.

**Loss if dropped:** Deletion note already reports 13 dosya, 1.5 MB. Original raw reconstruction is unavailable from this directory alone. Dropping the remaining summaries/logs also loses the recorded excerpts, errors and audit trail.

**Tracked context:** [docs/archive/local-runs.md](local-runs.md), [docs/archive/sw/sw-status.md](sw/sw-status.md), [docs/archive/sw/sw-slice13g-query-repair.md](sw/sw-slice13g-query-repair.md).

<a id="run-archive-sw-sw-slice13g-acceptance-2026-09-23b"></a>

### `archive/sw/sw-slice13g-acceptance-2026-09-23b`

**What:** Dilim 13g kabul ölçümü, ikinci koşu (2026-09-23): tuttu

**Phase/decision:** SW slice 13g; cited under D90.

**Key result:** Second 13g acceptance met its revised scope after Task 3 was removed by owner decision; 170 OpenAlex requests all HTTP 200. It does not erase the first failed attempt.

**Size:** 5,132 bytes (0.005 MiB), 2 files. **Read evidence:** `result.md`, `OZET-SILINENLER.md`.

**Loss if dropped:** Deletion note already reports 13 dosya, 1.6 MB. Original raw reconstruction is unavailable from this directory alone. Dropping the remaining summaries/logs also loses the recorded excerpts, errors and audit trail.

**Tracked context:** [docs/archive/local-runs.md](local-runs.md).

<a id="run-archive-sw-sw-slice13h-acceptance-2026-09-23"></a>

### `archive/sw/sw-slice13h-acceptance-2026-09-23`

**What:** Dilim 13h kabul ölçümü (2026-09-23): tuttu

**Phase/decision:** SW slice 13h; cited under D92.

**Key result:** 13h acceptance met the gate: nine of nine Luna calls valid first try, 447 HTTP-200 requests; quantum union found 23 in each call, packet four in each. Reused acceptance libraries limit independence.

**Size:** 4,593 bytes (0.004 MiB), 2 files. **Read evidence:** `result.md`, `OZET-SILINENLER.md`.

**Loss if dropped:** Deletion note already reports 46 dosya, 4.3 MB. Original raw reconstruction is unavailable from this directory alone. Dropping the remaining summaries/logs also loses the recorded excerpts, errors and audit trail.

**Tracked context:** [docs/archive/local-runs.md](local-runs.md), [docs/archive/sw/sw-status.md](sw/sw-status.md).

<a id="run-archive-sw-sw-slice14-acceptance-2026-09-23"></a>

### `archive/sw/sw-slice14-acceptance-2026-09-23`

**What:** Dilim 14 kabulü, 23 Eylül 2026 : GEÇMEDİ

**Phase/decision:** SW slice 14; cited under D93.

**Key result:** Slice-14 acceptance failed. Semantic Scholar rate limits, shortfall against quantum targets, and a request-count excess remain visible; q1 standard passed its work-count gate.

**Size:** 16,759 bytes (0.016 MiB), 12 files. **Read evidence:** `result.md`, `OZET-SILINENLER.md`.

**Loss if dropped:** Deletion note already reports 17 dosya, 0.1 MB. Original raw reconstruction is unavailable from this directory alone. Dropping the remaining summaries/logs also loses the recorded excerpts, errors and audit trail.

**Tracked context:** [docs/archive/local-runs.md](local-runs.md), [docs/archive/sw/sw-status.md](sw/sw-status.md).

<a id="run-archive-sw-sw-slice14-acceptance-2026-09-23b"></a>

### `archive/sw/sw-slice14-acceptance-2026-09-23b`

**What:** Dilim 14 kabulü, ikinci koşu (Sol düzeltmelerinden sonra), 23 Eylül 2026 14:07to14:48 : GEÇMEDİ

**Phase/decision:** SW slice 14; cited under D93.

**Key result:** Second slice-14 acceptance also failed despite no q1 Semantic Scholar 429s. Quantum quick/detailed and packet detailed missed their recorded count thresholds.

**Size:** 17,417 bytes (0.017 MiB), 12 files. **Read evidence:** `result.md`, `OZET-SILINENLER.md`.

**Loss if dropped:** Deletion note already reports 17 dosya, 0.1 MB. Original raw reconstruction is unavailable from this directory alone. Dropping the remaining summaries/logs also loses the recorded excerpts, errors and audit trail.

**Tracked context:** [docs/archive/local-runs.md](local-runs.md).

<a id="run-archive-sw-sw-slice14-bulk-sort-2026-09-23"></a>

### `archive/sw/sw-slice14-bulk-sort-2026-09-23`

**What:** Dilim 14, Task 1: bulk kesim sırası : sonuç (23 Eylül 2026)

**Phase/decision:** SW slice 14; exact decision attribution: bilinmiyor.

**Key result:** Across six queries, citationCount:desc kept 76 reference-work occurrences in the first 400 vs 38 for paperId. Publication-date sorting was tested in only one query. This chooses a cut order on known development works.

**Size:** 4,249 bytes (0.004 MiB), 3 files. **Read evidence:** `result.md`, `OZET-SILINENLER.md`.

**Loss if dropped:** Deletion note already reports 7 dosya, 1.4 MB. Original raw reconstruction is unavailable from this directory alone. Dropping the remaining summaries/logs also loses the recorded excerpts, errors and audit trail.

**Tracked context:** [docs/archive/local-runs.md](local-runs.md).

<a id="run-archive-sw-sw-slice14-fields-probe-2026-09-23"></a>

### `archive/sw/sw-slice14-fields-probe-2026-09-23`

**What:** SW slice 14 provider-field probe

**Phase/decision:** SW slice 14; cited under D93.

**Key result:** The complete run outcome is bilinmiyor from the surviving summary files. Deletion notes or scripts alone do not establish a successful run; linked tracked notes may preserve a bounded historical result.

**Size:** 222 bytes (0.000 MiB), 1 files. **Read evidence:** `OZET-SILINENLER.md`.

**Loss if dropped:** Deletion note already reports 1 dosya, 0.0 MB. Original raw reconstruction is unavailable from this directory alone. Dropping the remaining summaries/logs also loses the recorded excerpts, errors and audit trail.

**Tracked context:** [docs/archive/local-runs.md](local-runs.md), [docs/archive/sw/sw-slice14-source-routing.md](sw/sw-slice14-source-routing.md).

<a id="run-archive-sw-sw-slice14a-acceptance-2026-09-23"></a>

### `archive/sw/sw-slice14a-acceptance-2026-09-23`

**What:** Dilim 14a canlı kabulü: sonuç

**Phase/decision:** SW slice 14a; cited under D94.

**Key result:** K8 quick acceptance passed: quantum 9.8 min, four verified works read, two cited; packet 8.4 min. These are single bounded live runs.

**Size:** 23,988 bytes (0.023 MiB), 8 files. **Read evidence:** `result.md`, `OZET-SILINENLER.md`.

**Loss if dropped:** Deletion note already reports 9 dosya, 0.2 MB. Original raw reconstruction is unavailable from this directory alone. Dropping the remaining summaries/logs also loses the recorded excerpts, errors and audit trail.

**Tracked context:** [docs/archive/local-runs.md](local-runs.md), [docs/archive/sw/sw-status.md](sw/sw-status.md), [docs/archive/sw/sw-slice15-citation-chaining.md](sw/sw-slice15-citation-chaining.md).

<a id="run-archive-sw-sw-slice14a-order-replay-2026-09-23"></a>

### `archive/sw/sw-slice14a-order-replay-2026-09-23`

**What:** Dilim 14a yeniden oynatma: tam metin sırası (model çağrısız)

**Phase/decision:** SW slice 14a; cited under D94.

**Key result:** Offline replay reproduced stored full-text plans. None of the tested alternate orders consistently exceeded the current order; that does not establish optimality.

**Size:** 14,859 bytes (0.014 MiB), 3 files. **Read evidence:** `result.md`, `OZET-SILINENLER.md`.

**Loss if dropped:** Deletion note already reports 2 dosya, 0.0 MB. Original raw reconstruction is unavailable from this directory alone. Dropping the remaining summaries/logs also loses the recorded excerpts, errors and audit trail.

**Tracked context:** [docs/archive/local-runs.md](local-runs.md), [docs/archive/sw/sw-status.md](sw/sw-status.md), [docs/archive/sw/sw-slice14a-fulltext-order.md](sw/sw-slice14a-fulltext-order.md).

<a id="run-archive-sw-sw-slice15-acceptance-2026-09-23"></a>

### `archive/sw/sw-slice15-acceptance-2026-09-23`

**What:** Dilim 15 canlı kabulü: sonuç

**Phase/decision:** SW slice 15; cited under D95.

**Key result:** Three separately frozen attempts; the last passed the recorded benefit condition (g036, g087). The 40-request cap was never exhausted and not_reached=0. The two earlier failures are retained separately.

**Size:** 119,813 bytes (0.114 MiB), 43 files. **Read evidence:** `result.md`, `OZET-SILINENLER.md`, `task7/result.md`.

**Loss if dropped:** Deletion note already reports 69 dosya, 2.5 MB. Original raw reconstruction is unavailable from this directory alone. Dropping the remaining summaries/logs also loses the recorded excerpts, errors and audit trail.

**Tracked context:** [docs/archive/local-runs.md](local-runs.md), [docs/archive/sw/sw-status.md](sw/sw-status.md), [docs/archive/sw/sw-slice15-citation-chaining.md](sw/sw-slice15-citation-chaining.md).

<a id="run-archive-sw-sw-slice15-chain-replay-2026-09-23"></a>

### `archive/sw/sw-slice15-chain-replay-2026-09-23`

**What:** Dilim 15 yeniden oynatma: atıf zinciri neye ulaşıyor, neye mal oluyor, okunuyor mu

**Phase/decision:** SW slice 15; cited under D95.

**Key result:** Read-only chain replay made 407 OpenAlex requests (zero failures) and one Semantic Scholar request; no model call. Seed-selection trade-offs and later diagnostics are recorded separately, not a causal benefit measurement.

**Size:** 32,673 bytes (0.031 MiB), 5 files. **Read evidence:** `result.md`, `OZET-SILINENLER.md`.

**Loss if dropped:** Deletion note already reports 6 dosya, 0.3 MB. Original raw reconstruction is unavailable from this directory alone. Dropping the remaining summaries/logs also loses the recorded excerpts, errors and audit trail.

**Tracked context:** [docs/archive/local-runs.md](local-runs.md), [docs/archive/sw/sw-status.md](sw/sw-status.md), [docs/archive/sw/sw-slice15-citation-chaining.md](sw/sw-slice15-citation-chaining.md).

<a id="run-archive-sw-sw-slice16-acceptance-2026-09-24"></a>

### `archive/sw/sw-slice16-acceptance-2026-09-24`

**What:** Dilim 16 kabulü: sonuç (24 Eylül 2026)

**Phase/decision:** SW slice 16; cited under D96.

**Key result:** Slice-16 acceptance passed. Queue counts matched all 11 stored slice-15 libraries; the recorded full pytest had 1,869 passes plus the known memory-limit failure. Rule-3 replay reports zero differing tables.

**Size:** 63,435 bytes (0.060 MiB), 17 files. **Read evidence:** `result.md`, `OZET-SILINENLER.md`.

**Loss if dropped:** Deletion note already reports 13 dosya, 2.6 MB. Original raw reconstruction is unavailable from this directory alone. Dropping the remaining summaries/logs also loses the recorded excerpts, errors and audit trail.

**Tracked context:** [docs/archive/local-runs.md](local-runs.md), [docs/archive/sw/sw-slice17-human-queue-screen.md](sw/sw-slice17-human-queue-screen.md).

<a id="run-archive-sw-sw-slice16-queue-measure-2026-09-24"></a>

### `archive/sw/sw-slice16-queue-measure-2026-09-24`

**What:** Dilim 16 kuyruk ölçümü: sonuç

**Phase/decision:** SW slice 16; cited under D96.

**Key result:** Offline queue measurement over 16 libraries: no eligible work was left unread by the reading limit in these copies. It does not establish that inaccessible full texts were read.

**Size:** 33,528 bytes (0.032 MiB), 12 files. **Read evidence:** `result.md`, `OZET-SILINENLER.md`.

**Loss if dropped:** Deletion note already reports 19 dosya, 2.4 MB. Original raw reconstruction is unavailable from this directory alone. Dropping the remaining summaries/logs also loses the recorded excerpts, errors and audit trail.

**Tracked context:** [docs/archive/local-runs.md](local-runs.md), [docs/archive/sw/sw-status.md](sw/sw-status.md), [docs/archive/sw/sw-slice16-human-queue.md](sw/sw-slice16-human-queue.md).

<a id="run-archive-sw-sw-slice17-acceptance-2026-09-24"></a>

### `archive/sw/sw-slice17-acceptance-2026-09-24`

**What:** Dilim 17 kabulü : görsel denetim ve karar turu (24 Eylül 2026)

**Phase/decision:** SW slice 17; cited under D97.

**Key result:** Visual/decision-round acceptance used a copied library, four completed runs and no model call. Queue had 16 rows; several decision kinds were absent in this corpus and only synthetic fixtures covered them.

**Size:** 44,072 bytes (0.042 MiB), 11 files. **Read evidence:** `result.md`.

**Loss if dropped:** Dropping remaining evidence would remove the exact recorded inputs/outputs, per-case or per-work checks and replay/provenance needed to audit the reported result.

**Tracked context:** [docs/archive/local-runs.md](local-runs.md), [docs/archive/sw/sw-status.md](sw/sw-status.md).

<a id="run-archive-sw-sw-slice17-plan-2026-09-24"></a>

### `archive/sw/sw-slice17-plan-2026-09-24`

**What:** SW slice 17 human-queue screen plan review

**Phase/decision:** SW slice 17; cited under D97.

**Key result:** Surviving material is a plan/review or implementation hand-back. A separate executed measurement outcome is bilinmiyor; consult the linked tracked record for later disposition.

**Size:** 14,220 bytes (0.014 MiB), 5 files. **Read evidence:** `OZET-SILINENLER.md`.

**Loss if dropped:** Deletion note already reports 1 dosya, 0.2 MB. Original raw reconstruction is unavailable from this directory alone. Dropping the remaining summaries/logs also loses the recorded excerpts, errors and audit trail.

**Tracked context:** [docs/archive/local-runs.md](local-runs.md), [docs/archive/sw/sw-slice17-human-queue-screen.md](sw/sw-slice17-human-queue-screen.md).

<a id="run-archive-sw-sw-slice17a-acceptance-2026-09-24"></a>

### `archive/sw/sw-slice17a-acceptance-2026-09-24`

**What:** Dilim 17a kabulü (24 Eylül 2026)

**Phase/decision:** SW slice 17a; cited under D98.

**Key result:** Overlap acceptance completed quick and standard discovery+reading, 7.9/14.0 min; early/final entitlement sets 92/112, no recorded deviation. Counterfactual separate-path estimates do not prove causal speedup.

**Size:** 6,902 bytes (0.007 MiB), 6 files. **Read evidence:** `result.md`, `OZET-SILINENLER.md`.

**Loss if dropped:** Deletion note already reports 4 dosya, 0.0 MB. Original raw reconstruction is unavailable from this directory alone. Dropping the remaining summaries/logs also loses the recorded excerpts, errors and audit trail.

**Tracked context:** [docs/archive/local-runs.md](local-runs.md), [docs/archive/sw/sw-status.md](sw/sw-status.md), [docs/archive/sw/sw-slice17a-fetch-overlap.md](sw/sw-slice17a-fetch-overlap.md).

<a id="run-archive-sw-sw-slice17a-impl-2026-09-24"></a>

### `archive/sw/sw-slice17a-impl-2026-09-24`

**What:** SW slice 17a fetch-overlap implementation review

**Phase/decision:** SW slice 17a; exact decision attribution: bilinmiyor.

**Key result:** Surviving material is a plan/review or implementation hand-back. A separate executed measurement outcome is bilinmiyor; consult the linked tracked record for later disposition.

**Size:** 11,331 bytes (0.011 MiB), 6 files. **Read evidence:** `sol-final.md`, `sol-fix.md`, `sol-impl.md`.

**Loss if dropped:** Dropping this material loses the exact review findings, response/disposition history and implementation hand-back; a plan or review cannot substitute for execution evidence.

**Tracked context:** [docs/archive/local-runs.md](local-runs.md).

<a id="run-archive-sw-sw-slice17a-plan-2026-09-24"></a>

### `archive/sw/sw-slice17a-plan-2026-09-24`

**What:** SW slice 17a fetch-overlap plan and contract reviews

**Phase/decision:** SW slice 17a; cited under D98.

**Key result:** Surviving material is a plan/review or implementation hand-back. A separate executed measurement outcome is bilinmiyor; consult the linked tracked record for later disposition.

**Size:** 31,656 bytes (0.030 MiB), 13 files. **Read evidence:** `OZET-SILINENLER.md`.

**Loss if dropped:** Deletion note already reports 2 dosya, 0.0 MB. Original raw reconstruction is unavailable from this directory alone. Dropping the remaining summaries/logs also loses the recorded excerpts, errors and audit trail.

**Tracked context:** [docs/archive/local-runs.md](local-runs.md), [docs/archive/sw/sw-status.md](sw/sw-status.md), [docs/archive/sw/sw-slice17a-fetch-overlap.md](sw/sw-slice17a-fetch-overlap.md).

<a id="run-archive-sw-sw-slice18-plan-2026-09-24"></a>

### `archive/sw/sw-slice18-plan-2026-09-24`

**What:** SW slice 18 waiting-for-PDF plan review

**Phase/decision:** SW slice 18; cited under D99.

**Key result:** Surviving material is a plan/review or implementation hand-back. A separate executed measurement outcome is bilinmiyor; consult the linked tracked record for later disposition.

**Size:** 9,424 bytes (0.009 MiB), 3 files. **Read evidence:** `OZET-SILINENLER.md`.

**Loss if dropped:** Deletion note already reports 1 dosya, 0.0 MB. Original raw reconstruction is unavailable from this directory alone. Dropping the remaining summaries/logs also loses the recorded excerpts, errors and audit trail.

**Tracked context:** [docs/archive/local-runs.md](local-runs.md), [docs/archive/sw/sw-status.md](sw/sw-status.md), [docs/archive/sw/sw-slice18-waiting-for-pdf.md](sw/sw-slice18-waiting-for-pdf.md).

<a id="run-archive-sw-sw-slice18a-acceptance-2026-09-24"></a>

### `archive/sw/sw-slice18a-acceptance-2026-09-24`

**What:** SW slice 18a waiting-for-PDF acceptance

**Phase/decision:** SW slice 18a; cited under D99.

**Key result:** The complete run outcome is bilinmiyor from the surviving summary files. Deletion notes or scripts alone do not establish a successful run; linked tracked notes may preserve a bounded historical result.

**Size:** 1,007 bytes (0.001 MiB), 2 files. **Read evidence:** `OZET-SILINENLER.md`.

**Loss if dropped:** Deletion note already reports 1 dosya, 0.0 MB. Original raw reconstruction is unavailable from this directory alone. Dropping the remaining summaries/logs also loses the recorded excerpts, errors and audit trail.

**Tracked context:** [docs/archive/local-runs.md](local-runs.md), [docs/archive/sw/sw-status.md](sw/sw-status.md).

<a id="run-archive-sw-sw-slice18a-impl-2026-09-24"></a>

### `archive/sw/sw-slice18a-impl-2026-09-24`

**What:** SW slice 18a waiting-for-PDF implementation review

**Phase/decision:** SW slice 18a; exact decision attribution: bilinmiyor.

**Key result:** Surviving material is a plan/review or implementation hand-back. A separate executed measurement outcome is bilinmiyor; consult the linked tracked record for later disposition.

**Size:** 12,171 bytes (0.012 MiB), 9 files. **Read evidence:** `sol-review-1.md`, `sol-review-2.md`, `sol-review-3.md`.

**Loss if dropped:** Dropping this material loses the exact review findings, response/disposition history and implementation hand-back; a plan or review cannot substitute for execution evidence.

**Tracked context:** [docs/archive/local-runs.md](local-runs.md).

<a id="run-archive-sw-sw-slice18b-acceptance-2026-09-24"></a>

### `archive/sw/sw-slice18b-acceptance-2026-09-24`

**What:** Slice 18b acceptance (task 5), 2026-09-24

**Phase/decision:** SW slice 18b; cited under D100.

**Key result:** A user-supplied IEEE PDF produced fulltext_runs_disagree and a human queue. The first run had a missing Codex-home setup pause; the result also records a second uninterrupted trial. Neither establishes correctness of the model decision.

**Size:** 4,904 bytes (0.005 MiB), 4 files. **Read evidence:** `result.md`, `OZET-SILINENLER.md`.

**Loss if dropped:** Deletion note already reports 2 dosya, 0.0 MB. Original raw reconstruction is unavailable from this directory alone. Dropping the remaining summaries/logs also loses the recorded excerpts, errors and audit trail.

**Tracked context:** [docs/archive/local-runs.md](local-runs.md), [docs/archive/sw/sw-status.md](sw/sw-status.md).

<a id="run-archive-sw-sw-slice18b-impl-2026-09-24"></a>

### `archive/sw/sw-slice18b-impl-2026-09-24`

**What:** Slice 18b implementation report (2026-09-24, implementer: Opus subagent)

**Phase/decision:** SW slice 18b; exact decision attribution: bilinmiyor.

**Key result:** Surviving material is a plan/review or implementation hand-back. A separate executed measurement outcome is bilinmiyor; consult the linked tracked record for later disposition.

**Size:** 39,552 bytes (0.038 MiB), 9 files. **Read evidence:** `report.md`.

**Loss if dropped:** Dropping this material loses the exact review findings, response/disposition history and implementation hand-back; a plan or review cannot substitute for execution evidence.

**Tracked context:** [docs/archive/local-runs.md](local-runs.md), [docs/archive/sw/sw-status.md](sw/sw-status.md).

<a id="run-archive-sw-sw-slice18b-plan-2026-09-24"></a>

### `archive/sw/sw-slice18b-plan-2026-09-24`

**What:** SW slice 18b person-PDF plan reviews

**Phase/decision:** SW slice 18b; exact decision attribution: bilinmiyor.

**Key result:** Surviving material is a plan/review or implementation hand-back. A separate executed measurement outcome is bilinmiyor; consult the linked tracked record for later disposition.

**Size:** 27,696 bytes (0.026 MiB), 10 files. **Read evidence:** `sol-plan-2.md`, `sol-plan-3.md`, `sol-plan-4.md`.

**Loss if dropped:** Dropping this material loses the exact review findings, response/disposition history and implementation hand-back; a plan or review cannot substitute for execution evidence.

**Tracked context:** [docs/archive/local-runs.md](local-runs.md), [docs/archive/sw/sw-slice18-waiting-for-pdf.md](sw/sw-slice18-waiting-for-pdf.md).

<a id="run-archive-sw-sw-slice19-acceptance-2026-09-25"></a>

### `archive/sw/sw-slice19-acceptance-2026-09-25`

**What:** SW slice 19 probe-table acceptance

**Phase/decision:** SW slice 19; exact decision attribution: bilinmiyor.

**Key result:** The complete run outcome is bilinmiyor from the surviving summary files. Deletion notes or scripts alone do not establish a successful run; linked tracked notes may preserve a bounded historical result.

**Size:** 220 bytes (0.000 MiB), 1 files. **Read evidence:** `OZET-SILINENLER.md`.

**Loss if dropped:** Deletion note already reports 3 dosya, 0.0 MB. Original raw reconstruction is unavailable from this directory alone. Dropping the remaining summaries/logs also loses the recorded excerpts, errors and audit trail.

**Tracked context:** [docs/archive/local-runs.md](local-runs.md), [docs/archive/sw/sw-status.md](sw/sw-status.md).

<a id="run-archive-sw-sw-slice19-impl-2026-09-25"></a>

### `archive/sw/sw-slice19-impl-2026-09-25`

**What:** Slice 19 implementation report (2026-09-25, Opus subagent) : condensed by the coordinator

**Phase/decision:** SW slice 19; exact decision attribution: bilinmiyor.

**Key result:** Implementation hand-back describes probe tables, work counts and signal views. It is an implementer report, not a new scientific measurement.

**Size:** 19,045 bytes (0.018 MiB), 7 files. **Read evidence:** `report.md`.

**Loss if dropped:** Dropping this material loses the exact review findings, response/disposition history and implementation hand-back; a plan or review cannot substitute for execution evidence.

**Tracked context:** [docs/archive/local-runs.md](local-runs.md), [docs/archive/sw/sw-status.md](sw/sw-status.md).

<a id="run-archive-sw-sw-slice19-plan-2026-09-25"></a>

### `archive/sw/sw-slice19-plan-2026-09-25`

**What:** Result, 2026-09-25 (`measure.py` → `measure.json`, `summary.py` → `summary.md`, `timing.py` → `timing.txt`)

**Phase/decision:** SW slice 19; cited under D101.

**Key result:** Read-only plan measurement excludes three copied researches from 46, leaving 43; arms attributable in 25, 17 with reading runs. Only one person-verified work in two researches; selection bias remains material.

**Size:** 63,300 bytes (0.060 MiB), 10 files. **Read evidence:** `result.md`, `OZET-SILINENLER.md`.

**Loss if dropped:** Deletion note already reports 2 dosya, 0.3 MB. Original raw reconstruction is unavailable from this directory alone. Dropping the remaining summaries/logs also loses the recorded excerpts, errors and audit trail.

**Tracked context:** [docs/archive/local-runs.md](local-runs.md), [docs/archive/sw/sw-slice19-probe-tables.md](sw/sw-slice19-probe-tables.md).

<a id="run-archive-sw-sw-slice20-acceptance-2026-09-25"></a>

### `archive/sw/sw-slice20-acceptance-2026-09-25`

**What:** SW slice 20 flow/audit/PRISMA-S acceptance

**Phase/decision:** SW slice 20; cited under D102.

**Key result:** The complete run outcome is bilinmiyor from the surviving summary files. Deletion notes or scripts alone do not establish a successful run; linked tracked notes may preserve a bounded historical result.

**Size:** 220 bytes (0.000 MiB), 1 files. **Read evidence:** `OZET-SILINENLER.md`.

**Loss if dropped:** Deletion note already reports 2 dosya, 0.1 MB. Original raw reconstruction is unavailable from this directory alone. Dropping the remaining summaries/logs also loses the recorded excerpts, errors and audit trail.

**Tracked context:** [docs/archive/local-runs.md](local-runs.md), [docs/archive/sw/sw-status.md](sw/sw-status.md).

<a id="run-archive-sw-sw-slice20-impl-2026-09-25"></a>

### `archive/sw/sw-slice20-impl-2026-09-25`

**What:** Slice 20 implementation report (2026-09-25, Opus subagent)

**Phase/decision:** SW slice 20; exact decision attribution: bilinmiyor.

**Key result:** Implementation hand-back describes flow counts, overrides, audit strata and PRISMA-S export. Its initial status was awaiting model review; this file alone does not establish current deployment.

**Size:** 28,168 bytes (0.027 MiB), 9 files. **Read evidence:** `report.md`.

**Loss if dropped:** Dropping this material loses the exact review findings, response/disposition history and implementation hand-back; a plan or review cannot substitute for execution evidence.

**Tracked context:** [docs/archive/local-runs.md](local-runs.md), [docs/archive/sw/sw-status.md](sw/sw-status.md).

<a id="run-archive-sw-sw-slice20-plan-2026-09-25"></a>

### `archive/sw/sw-slice20-plan-2026-09-25`

**What:** Slice 20 plan measurement : result (2026-09-25)

**Phase/decision:** SW slice 20; cited under D102.

**Key result:** Plan measurement uses 43 distinct copied researches, 40 with works and 30 with full-text reading. No network/model call or live-library read; counts describe stored behavior.

**Size:** 45,164 bytes (0.043 MiB), 16 files. **Read evidence:** `result.md`, `OZET-SILINENLER.md`.

**Loss if dropped:** Deletion note already reports 3 dosya, 0.2 MB. Original raw reconstruction is unavailable from this directory alone. Dropping the remaining summaries/logs also loses the recorded excerpts, errors and audit trail.

**Tracked context:** [docs/archive/local-runs.md](local-runs.md), [docs/archive/sw/sw-status.md](sw/sw-status.md), [docs/archive/sw/sw-slice20-flow-audit-prisma.md](sw/sw-slice20-flow-audit-prisma.md).

<a id="run-archive-sw-sw-slice21-impl-2026-09-25"></a>

### `archive/sw/sw-slice21-impl-2026-09-25`

**What:** SW slice 21, built-in local embedding: implementation report (2026-09-25)

**Phase/decision:** SW slice 21; exact decision attribution: bilinmiyor.

**Key result:** Local-embedding hand-back records 2,238 pytest passes plus the known memory-limit failure, 17 lint warnings and browser acceptance. These are recorded implementation checks, not a retrieval-quality validation.

**Size:** 199,500 bytes (0.190 MiB), 54 files. **Read evidence:** `report.md`, `OZET-SILINENLER.md`.

**Loss if dropped:** Deletion note already reports 106 dosya, 2.9 MB. Original raw reconstruction is unavailable from this directory alone. Dropping the remaining summaries/logs also loses the recorded excerpts, errors and audit trail.

**Tracked context:** [docs/archive/local-runs.md](local-runs.md), [docs/archive/sw/sw-status.md](sw/sw-status.md).

<a id="run-archive-sw-sw-slice21-plan-2026-09-25"></a>

### `archive/sw/sw-slice21-plan-2026-09-25`

**What:** SW slice 21 built-in embedding plan review and cache notes

**Phase/decision:** SW slice 21; cited under D103.

**Key result:** Surviving material is a plan/review or implementation hand-back. A separate executed measurement outcome is bilinmiyor; consult the linked tracked record for later disposition.

**Size:** 97,269 bytes (0.093 MiB), 35 files. **Read evidence:** `OZET-SILINENLER.md`.

**Loss if dropped:** Deletion note already reports 13 dosya, 1.2 MB. Original raw reconstruction is unavailable from this directory alone. Dropping the remaining summaries/logs also loses the recorded excerpts, errors and audit trail.

**Tracked context:** [docs/archive/local-runs.md](local-runs.md), [docs/archive/sw/sw-status.md](sw/sw-status.md), [docs/archive/sw/sw-slice21-builtin-local-embedding.md](sw/sw-slice21-builtin-local-embedding.md).

<a id="run-archive-sw-sw-slice22-acceptance-2026-09-25"></a>

### `archive/sw/sw-slice22-acceptance-2026-09-25`

**What:** SW slice 22 arXiv-source acceptance

**Phase/decision:** SW slice 22; cited under D104.

**Key result:** The complete run outcome is bilinmiyor from the surviving summary files. Deletion notes or scripts alone do not establish a successful run; linked tracked notes may preserve a bounded historical result.

**Size:** 45,972 bytes (0.044 MiB), 1 files. **Read evidence:** `OZET-SILINENLER.md`.

**Loss if dropped:** Deletion note already reports 66 dosya, 12.4 MB. Original raw reconstruction is unavailable from this directory alone. Dropping the remaining summaries/logs also loses the recorded excerpts, errors and audit trail.

**Tracked context:** [docs/archive/local-runs.md](local-runs.md), [docs/archive/sw/sw-status.md](sw/sw-status.md).

<a id="run-archive-sw-sw-slice22-impl-2026-09-25"></a>

### `archive/sw/sw-slice22-impl-2026-09-25`

**What:** Slice 22 implementation report (implementer hand-back, saved by coordinator, 2026-09-25)

**Phase/decision:** SW slice 22; exact decision attribution: bilinmiyor.

**Key result:** arXiv-source hand-back records 2,370 pytest passes plus the known memory-limit failure, with version, archive and matching checks. Source-matching thresholds are implementation rules, not independently measured correctness.

**Size:** 75,834 bytes (0.072 MiB), 29 files. **Read evidence:** `report.md`.

**Loss if dropped:** Dropping this material loses the exact review findings, response/disposition history and implementation hand-back; a plan or review cannot substitute for execution evidence.

**Tracked context:** [docs/archive/local-runs.md](local-runs.md), [docs/archive/sw/sw-status.md](sw/sw-status.md).

<a id="run-archive-sw-sw-slice22-plan-2026-09-25"></a>

### `archive/sw/sw-slice22-plan-2026-09-25`

**What:** Purpose beyond the directory name is bilinmiyor; only the listed surviving files establish its contents.

**Phase/decision:** SW slice 22; cited under D104.

**Key result:** The preserved summary-r2-final.json records 43 versions, 1,520 numbered lines, 873 final-rule placements and 246 pages with a placement. These are retained truncated-summary figures, not a fresh PDF audit.

**Size:** 72,057 bytes (0.069 MiB), 19 files. **Read evidence:** `OZET-SILINENLER.md`.

**Loss if dropped:** Deletion note already reports 24 dosya, 3.5 MB. Original raw reconstruction is unavailable from this directory alone. Dropping the remaining summaries/logs also loses the recorded excerpts, errors and audit trail.

**Tracked context:** [docs/archive/local-runs.md](local-runs.md), [docs/archive/sw/sw-slice22-arxiv-latex-source.md](sw/sw-slice22-arxiv-latex-source.md).

<a id="run-archive-sw-sw-slice23-plan-2026-09-27"></a>

### `archive/sw/sw-slice23-plan-2026-09-27`

**What:** SW slice 23 code-gate plan review

**Phase/decision:** SW slice 23; cited under D110.

**Key result:** Surviving material is a plan/review or implementation hand-back. A separate executed measurement outcome is bilinmiyor; consult the linked tracked record for later disposition.

**Size:** 214 bytes (0.000 MiB), 1 files. **Read evidence:** `OZET-SILINENLER.md`.

**Loss if dropped:** Deletion note already reports 1 dosya, 0.3 MB. Original raw reconstruction is unavailable from this directory alone. Dropping the remaining summaries/logs also loses the recorded excerpts, errors and audit trail.

**Tracked context:** [docs/archive/local-runs.md](local-runs.md), [docs/archive/sw/sw-status.md](sw/sw-status.md), [docs/archive/sw/sw-slice23-code-gate.md](sw/sw-slice23-code-gate.md).

<a id="run-archive-sw-sw-slice24-campaign-2026-09-26-134050"></a>

### `archive/sw/sw-slice24-campaign-2026-09-26-134050`

**What:** Purpose beyond the directory name is bilinmiyor; only the listed surviving files establish its contents.

**Phase/decision:** SW slice 24; cited under D105.

**Key result:** SW24 campaign has separate quantum and medicine results in tracked slice24-results.md: the quantum campaign passed four gates; the medicine result failed. g1 summaries survive only as deletion-note excerpts; no generalization claim.

**Size:** 369,376 bytes (0.352 MiB), 114 files. **Read evidence:** `OZET-SILINENLER.md`.

**Loss if dropped:** Deletion note already reports 317 dosya, 11.6 MB. Original raw reconstruction is unavailable from this directory alone. Dropping the remaining summaries/logs also loses the recorded excerpts, errors and audit trail.

**Tracked context:** [docs/archive/sw/sw-slice24-results.md](sw/sw-slice24-results.md), [docs/archive/sw/sw-slice26-protocol-results-and-phrases.md](sw/sw-slice26-protocol-results-and-phrases.md), [docs/archive/local-runs.md](local-runs.md).

<a id="run-archive-sw-sw-slice24-plan-2026-09-26"></a>

### `archive/sw/sw-slice24-plan-2026-09-26`

**What:** SW slice 24 campaign preparation and comparator snapshots

**Phase/decision:** SW slice 24; exact decision attribution: bilinmiyor.

**Key result:** Surviving material is a plan/review or implementation hand-back. A separate executed measurement outcome is bilinmiyor; consult the linked tracked record for later disposition.

**Size:** 58,276 bytes (0.056 MiB), 22 files. **Read evidence:** `OZET-SILINENLER.md`.

**Loss if dropped:** Deletion note already reports 5 dosya, 0.1 MB. Original raw reconstruction is unavailable from this directory alone. Dropping the remaining summaries/logs also loses the recorded excerpts, errors and audit trail.

**Tracked context:** [docs/archive/local-runs.md](local-runs.md), [docs/archive/sw/sw-status.md](sw/sw-status.md), [docs/archive/sw/sw-slice24-measurement-campaign.md](sw/sw-slice24-measurement-campaign.md).

<a id="run-archive-sw-sw-slice25-acceptance-2026-09-26"></a>

### `archive/sw/sw-slice25-acceptance-2026-09-26`

**What:** SW slice 25 question-element acceptance

**Phase/decision:** SW slice 25; exact decision attribution: bilinmiyor.

**Key result:** Acceptance raw JSON/screenshots were removed according to the deletion note; detailed outcome must be read from the tracked slice-25 record. Independent reconstruction from this directory is bilinmiyor.

**Size:** 12,469 bytes (0.012 MiB), 1 files. **Read evidence:** `OZET-SILINENLER.md`.

**Loss if dropped:** Deletion note already reports 6 dosya, 0.3 MB. Original raw reconstruction is unavailable from this directory alone. Dropping the remaining summaries/logs also loses the recorded excerpts, errors and audit trail.

**Tracked context:** [docs/archive/local-runs.md](local-runs.md), [docs/archive/sw/sw-slice28-comparator-reading.md](sw/sw-slice28-comparator-reading.md).

<a id="run-archive-sw-sw-slice25-impl-2026-09-26"></a>

### `archive/sw/sw-slice25-impl-2026-09-26`

**What:** Slice 25a implementation report (2026-09-26)

**Phase/decision:** SW slice 25; exact decision attribution: bilinmiyor.

**Key result:** Slice-25a implementation hand-back covers question-element roles and consensus; part B and 24b had not run at that hand-back.

**Size:** 10,733 bytes (0.010 MiB), 3 files. **Read evidence:** `report.md`.

**Loss if dropped:** Dropping this material loses the exact review findings, response/disposition history and implementation hand-back; a plan or review cannot substitute for execution evidence.

**Tracked context:** [docs/archive/local-runs.md](local-runs.md), [docs/archive/sw/sw-status.md](sw/sw-status.md).

<a id="run-archive-sw-sw-slice25-plan-2026-09-26"></a>

### `archive/sw/sw-slice25-plan-2026-09-26`

**What:** SW slice 25 question-element plan review

**Phase/decision:** SW slice 25; exact decision attribution: bilinmiyor.

**Key result:** Surviving material is a plan/review or implementation hand-back. A separate executed measurement outcome is bilinmiyor; consult the linked tracked record for later disposition.

**Size:** 13,786 bytes (0.013 MiB), 7 files. **Read evidence:** `OZET-SILINENLER.md`.

**Loss if dropped:** Deletion note already reports 8 dosya, 0.2 MB. Original raw reconstruction is unavailable from this directory alone. Dropping the remaining summaries/logs also loses the recorded excerpts, errors and audit trail.

**Tracked context:** [docs/archive/local-runs.md](local-runs.md), [docs/archive/sw/sw-status.md](sw/sw-status.md), [docs/archive/sw/sw-slice25-pico-criterion.md](sw/sw-slice25-pico-criterion.md).

<a id="run-archive-sw-sw-slice25-remeasure-2026-09-26-224554"></a>

### `archive/sw/sw-slice25-remeasure-2026-09-26-224554`

**What:** SW slice 25 medicine remeasurement

**Phase/decision:** SW slice 25; exact decision attribution: bilinmiyor.

**Key result:** Tracked medicine remeasurement remains a development result; this directory now has a deletion stub and two commentary files, not the original machine ledger. Reconstruction from retained local files is bilinmiyor.

**Size:** 4,204 bytes (0.004 MiB), 3 files. **Read evidence:** `OZET-SILINENLER.md`.

**Loss if dropped:** Deletion note already reports 123 dosya, 1.1 MB. Original raw reconstruction is unavailable from this directory alone. Dropping the remaining summaries/logs also loses the recorded excerpts, errors and audit trail.

**Tracked context:** [docs/archive/local-runs.md](local-runs.md), [docs/archive/sw/sw-status.md](sw/sw-status.md), [docs/archive/sw/sw-slice27-medicine-remeasure.md](sw/sw-slice27-medicine-remeasure.md).

<a id="run-archive-sw-sw-slice26-acceptance-2026-09-27"></a>

### `archive/sw/sw-slice26-acceptance-2026-09-27`

**What:** SW slice 26 protocol/results/phrases acceptance and code review

**Phase/decision:** SW slice 26; exact decision attribution: bilinmiyor.

**Key result:** The complete run outcome is bilinmiyor from the surviving summary files. Deletion notes or scripts alone do not establish a successful run; linked tracked notes may preserve a bounded historical result.

**Size:** 9,201 bytes (0.009 MiB), 3 files. **Read evidence:** `OZET-SILINENLER.md`.

**Loss if dropped:** Deletion note already reports 4 dosya, 0.2 MB. Original raw reconstruction is unavailable from this directory alone. Dropping the remaining summaries/logs also loses the recorded excerpts, errors and audit trail.

**Tracked context:** [docs/archive/local-runs.md](local-runs.md).

<a id="run-archive-sw-sw-slice26-plan-2026-09-27"></a>

### `archive/sw/sw-slice26-plan-2026-09-27`

**What:** SW slice 26 protocol/results/phrases plan review

**Phase/decision:** SW slice 26; exact decision attribution: bilinmiyor.

**Key result:** Surviving material is a plan/review or implementation hand-back. A separate executed measurement outcome is bilinmiyor; consult the linked tracked record for later disposition.

**Size:** 6,697 bytes (0.006 MiB), 5 files. **Read evidence:** `OZET-SILINENLER.md`.

**Loss if dropped:** Deletion note already reports 3 dosya, 0.1 MB. Original raw reconstruction is unavailable from this directory alone. Dropping the remaining summaries/logs also loses the recorded excerpts, errors and audit trail.

**Tracked context:** [docs/archive/sw/sw-slice26-protocol-results-and-phrases.md](sw/sw-slice26-protocol-results-and-phrases.md), [docs/archive/local-runs.md](local-runs.md), [docs/archive/sw/sw-status.md](sw/sw-status.md).

<a id="run-archive-sw-sw-slice27-plan-2026-09-27"></a>

### `archive/sw/sw-slice27-plan-2026-09-27`

**What:** SW slice 27 medicine remeasurement plan review

**Phase/decision:** SW slice 27; exact decision attribution: bilinmiyor.

**Key result:** Surviving material is a plan/review or implementation hand-back. A separate executed measurement outcome is bilinmiyor; consult the linked tracked record for later disposition.

**Size:** 6,630 bytes (0.006 MiB), 5 files. **Read evidence:** `OZET-SILINENLER.md`.

**Loss if dropped:** Deletion note already reports 43 dosya, 0.2 MB. Original raw reconstruction is unavailable from this directory alone. Dropping the remaining summaries/logs also loses the recorded excerpts, errors and audit trail.

**Tracked context:** [docs/archive/local-runs.md](local-runs.md), [docs/archive/sw/sw-status.md](sw/sw-status.md), [docs/archive/sw/sw-slice27-medicine-remeasure.md](sw/sw-slice27-medicine-remeasure.md).

<a id="run-archive-sw-sw-slice27-remeasure-2026-09-27-043237"></a>

### `archive/sw/sw-slice27-remeasure-2026-09-27-043237`

**What:** SW slice 27 medicine remeasurement

**Phase/decision:** SW slice 27; cited under D108.

**Key result:** Tracked slice27-remeasure-results.md retains the medicine gate result; local machine result files are removed. Logs/protocol remain, so recomputation against the original library is unavailable.

**Size:** 147,404 bytes (0.141 MiB), 58 files. **Read evidence:** `OZET-SILINENLER.md`.

**Loss if dropped:** Deletion note already reports 109 dosya, 4.4 MB. Original raw reconstruction is unavailable from this directory alone. Dropping the remaining summaries/logs also loses the recorded excerpts, errors and audit trail.

**Tracked context:** [docs/archive/sw/sw-slice27-remeasure-results.md](sw/sw-slice27-remeasure-results.md), [docs/archive/local-runs.md](local-runs.md), [docs/archive/sw/sw-status.md](sw/sw-status.md).

<a id="run-archive-sw-sw-slice28-acceptance-2026-09-27"></a>

### `archive/sw/sw-slice28-acceptance-2026-09-27`

**What:** SW slice 28 comparator-reading acceptance/code review

**Phase/decision:** SW slice 28; cited under D109.

**Key result:** The complete run outcome is bilinmiyor from the surviving summary files. Deletion notes or scripts alone do not establish a successful run; linked tracked notes may preserve a bounded historical result.

**Size:** 26,677 bytes (0.025 MiB), 5 files. **Read evidence:** `OZET-SILINENLER.md`.

**Loss if dropped:** Deletion note already reports 21 dosya, 0.7 MB. Original raw reconstruction is unavailable from this directory alone. Dropping the remaining summaries/logs also loses the recorded excerpts, errors and audit trail.

**Tracked context:** [docs/archive/local-runs.md](local-runs.md).

<a id="run-archive-sw-sw-slice28-plan-2026-09-27"></a>

### `archive/sw/sw-slice28-plan-2026-09-27`

**What:** SW slice 28 comparator-reading plan review

**Phase/decision:** SW slice 28; exact decision attribution: bilinmiyor.

**Key result:** Surviving material is a plan/review or implementation hand-back. A separate executed measurement outcome is bilinmiyor; consult the linked tracked record for later disposition.

**Size:** 10,219 bytes (0.010 MiB), 7 files. **Read evidence:** `OZET-SILINENLER.md`.

**Loss if dropped:** Deletion note already reports 6 dosya, 0.0 MB. Original raw reconstruction is unavailable from this directory alone. Dropping the remaining summaries/logs also loses the recorded excerpts, errors and audit trail.

**Tracked context:** [docs/archive/local-runs.md](local-runs.md), [docs/archive/sw/sw-status.md](sw/sw-status.md), [docs/archive/sw/sw-slice28-comparator-reading.md](sw/sw-slice28-comparator-reading.md).

<a id="run-archive-sw-sw-slice29-fetch-limit-replay-2026-09-28"></a>

### `archive/sw/sw-slice29-fetch-limit-replay-2026-09-28`

**What:** Slice 29 replay: `standard`'s full-text fetch limit : result

**Phase/decision:** SW slice 29; cited under D111.

**Key result:** Offline replay reproduced the full-text-plan work list in all 12 libraries. The quantum fetch limit bottleneck was diagnosed; no model/network call and no live improvement experiment.

**Size:** 13,307 bytes (0.013 MiB), 3 files. **Read evidence:** `result.md`, `OZET-SILINENLER.md`.

**Loss if dropped:** Deletion note already reports 1 dosya, 0.1 MB. Original raw reconstruction is unavailable from this directory alone. Dropping the remaining summaries/logs also loses the recorded excerpts, errors and audit trail.

**Tracked context:** [docs/archive/local-runs.md](local-runs.md), [docs/archive/sw/sw-status.md](sw/sw-status.md), [docs/archive/sw/sw-slice29-fetch-limit.md](sw/sw-slice29-fetch-limit.md).

<a id="run-archive-sw-sw-slice30-medicine-final-2026-09-28"></a>

### `archive/sw/sw-slice30-medicine-final-2026-09-28`

**What:** SW slice 30 final medicine campaign

**Phase/decision:** SW slice 30; cited under D114.

**Key result:** D114 and sw-slice30-results.md record only gate 3 passed in the final medicine run. D117 later selects sw by owner decision; that choice does not change the measured failed gates.

**Size:** 249,626 bytes (0.238 MiB), 108 files. **Read evidence:** `OZET-SILINENLER.md`.

**Loss if dropped:** Deletion note already reports 145 dosya, 6.7 MB. Original raw reconstruction is unavailable from this directory alone. Dropping the remaining summaries/logs also loses the recorded excerpts, errors and audit trail.

**Tracked context:** [docs/archive/sw/sw-slice30-results.md](sw/sw-slice30-results.md), [docs/archive/local-runs.md](local-runs.md), [docs/archive/sw/sw-slice30-medicine-final.md](sw/sw-slice30-medicine-final.md).

<a id="run-archive-sw-sw-slice31-impl"></a>

### `archive/sw/sw-slice31-impl`

**What:** SW slice 31 legacy-removal implementation reviews

**Phase/decision:** SW slice 31; exact decision attribution: bilinmiyor.

**Key result:** Surviving material is a plan/review or implementation hand-back. A separate executed measurement outcome is bilinmiyor; consult the linked tracked record for later disposition.

**Size:** 12,287 bytes (0.012 MiB), 4 files. **Read evidence:** `cr1-answer.md`, `cr2-answer.md`, `fix1-answer.md`.

**Loss if dropped:** Dropping this material loses the exact review findings, response/disposition history and implementation hand-back; a plan or review cannot substitute for execution evidence.

**Tracked context:** [docs/archive/local-runs.md](local-runs.md).

<a id="run-archive-sw-sw-slice31-plan-review"></a>

### `archive/sw/sw-slice31-plan-review`

**What:** SW slice 31 legacy-removal plan reviews

**Phase/decision:** SW slice 31; exact decision attribution: bilinmiyor.

**Key result:** Surviving material is a plan/review or implementation hand-back. A separate executed measurement outcome is bilinmiyor; consult the linked tracked record for later disposition.

**Size:** 22,091 bytes (0.021 MiB), 13 files. **Read evidence:** `r3-answer.md`, `r3.md`, `r4-answer.md`.

**Loss if dropped:** Dropping this material loses the exact review findings, response/disposition history and implementation hand-back; a plan or review cannot substitute for execution evidence.

**Tracked context:** [docs/archive/local-runs.md](local-runs.md), [docs/archive/sw/sw-slice31-legacy-removal.md](sw/sw-slice31-legacy-removal.md).

<a id="run-archive-sw-sw-smoke-2026-09-22"></a>

### `archive/sw/sw-smoke-2026-09-22`

**What:** SW dilim 13 : uçtan uca duman testi: sonuç

**Phase/decision:** SW; cited under D88.

**Key result:** First three smoke attempts failed before the full workflow; attempt four reached answer but reading exhausted its budget; result-run5.md records the acceptance expectations met. Separate attempts are not one uninterrupted success.

**Size:** 71,358 bytes (0.068 MiB), 14 files. **Read evidence:** `result.md`, `OZET-SILINENLER.md`.

**Loss if dropped:** Deletion note already reports 22 dosya, 0.1 MB. Original raw reconstruction is unavailable from this directory alone. Dropping the remaining summaries/logs also loses the recorded excerpts, errors and audit trail.

**Tracked context:** [docs/archive/local-runs.md](local-runs.md), [docs/archive/sw/sw-status.md](sw/sw-status.md), [docs/archive/sw/sw-slice13-smoke-test.md](sw/sw-slice13-smoke-test.md).

<a id="run-archive-sw-sw-vocabulary-experiment-2026-09-23"></a>

### `archive/sw/sw-vocabulary-experiment-2026-09-23`

**What:** Sonuç: arama sözcük listesi deneyi (2026-09-23)

**Phase/decision:** SW; cited under D90.

**Key result:** Model-proposed vocabulary did not beat the code list on the known quantum/packet works; q1 best nine of 31 vs code 18, q2 zero. q3 relevance counts are analyst title judgements without labels.

**Size:** 18,994 bytes (0.018 MiB), 4 files. **Read evidence:** `result.md`, `OZET-SILINENLER.md`.

**Loss if dropped:** Deletion note already reports 35 dosya, 3.6 MB. Original raw reconstruction is unavailable from this directory alone. Dropping the remaining summaries/logs also loses the recorded excerpts, errors and audit trail.

**Tracked context:** [docs/archive/local-runs.md](local-runs.md), [docs/archive/sw/sw-status.md](sw/sw-status.md), [docs/archive/sw/sw-slice13h-model-query.md](sw/sw-slice13h-model-query.md).

<a id="run-archive-p9-evidence-deixis-h9b-run"></a>

### `archive/p9-evidence/DEIXIS-h9b-run`

**What:** P9 H9b/RF report follow-up evidence from removed measurement worktree

**Phase/decision:** P9; cited under D202.

**Key result:** Retained H9b deletion-note excerpts show A/A2 incomplete, B2 draft, C/D incomplete, E valid. Tracked p9r-report-results.md preserves the separately dated RF follow-ups. Valid assembly alone is not a scientific quality verdict.

**Size:** 10,002,113 bytes (9.539 MiB), 248 files. **Read evidence:** `OZET-SILINENLER.md`.

**Loss if dropped:** Deletion note already reports 287 dosya, 68.3 MB. Original raw reconstruction is unavailable from this directory alone. Dropping the remaining summaries/logs also loses the recorded excerpts, errors and audit trail.

**Tracked context:** [docs/product/p9r-report-results.md](../product/p9r-report-results.md), [docs/product/p9-owed-measurements-results.md](../product/p9-owed-measurements-results.md), [docs/archive/local-runs.md](local-runs.md).

<a id="run-archive-p9-evidence-deixis-h9run"></a>

### `archive/p9-evidence/DEIXIS-h9run`

**What:** P9 H9 new-corpus report run evidence

**Phase/decision:** P9; cited under D171.

**Key result:** H9 report stopped at IV after repair: envelope_mismatch and citation_anchor_target_count. Only R1, R7 and P19 recorded; reader and other quality ranges unmeasured (tracked p9r-report-results.md).

**Size:** 623,352 bytes (0.594 MiB), 35 files. **Read evidence:** `OZET-SILINENLER.md`.

**Loss if dropped:** Deletion note already reports 42 dosya, 17.3 MB. Original raw reconstruction is unavailable from this directory alone. Dropping the remaining summaries/logs also loses the recorded excerpts, errors and audit trail.

**Tracked context:** [docs/product/p9r-report-results.md](../product/p9r-report-results.md), [docs/archive/local-runs.md](local-runs.md), [docs/archive/p9/p9-rf-prompt.md](p9/p9-rf-prompt.md).

<a id="run-archive-p9-evidence-deixis-owed-k6"></a>

### `archive/p9-evidence/DEIXIS-owed-k6`

**What:** P9 owed K6 kill-search assessment evidence

**Phase/decision:** P9; exact decision attribution: bilinmiyor.

**Key result:** Deletion-note score/results.json excerpt covers one series/six claims/evaluated supplied text only. Early C1 to C4 entries have absent reference works; decomposition unmeasured and open does not mean a literature gap.

**Size:** 91,397 bytes (0.087 MiB), 13 files. **Read evidence:** `OZET-SILINENLER.md`.

**Loss if dropped:** Deletion note already reports 55 dosya, 3.4 MB. Original raw reconstruction is unavailable from this directory alone. Dropping the remaining summaries/logs also loses the recorded excerpts, errors and audit trail.

**Tracked context:** [docs/product/p9-owed-measurements-results.md](../product/p9-owed-measurements-results.md), [docs/archive/local-runs.md](local-runs.md), [docs/product/p9-owed-measurements-freeze.md](../product/p9-owed-measurements-freeze.md).

<a id="run-archive-p9-evidence-deixis-owed-l9"></a>

### `archive/p9-evidence/DEIXIS-owed-l9`

**What:** P9 owed L9 independence launcher

**Phase/decision:** P9; exact decision attribution: bilinmiyor.

**Key result:** Only launch-l9.sh survives; it specifies the independent L9 launcher. Execution and measurements in this directory are bilinmiyor. Tracked owed-measurements results must be consulted separately.

**Size:** 1,387 bytes (0.001 MiB), 1 files. **Read evidence:** `launch-l9.sh`.

**Loss if dropped:** Dropping the launcher loses its exact environment and launch command. No executed result or raw run data is present here to recover.

**Tracked context:** [docs/product/p9-owed-measurements-results.md](../product/p9-owed-measurements-results.md), [docs/archive/local-runs.md](local-runs.md), [docs/product/p9-owed-measurements-freeze.md](../product/p9-owed-measurements-freeze.md).

<a id="run-archive-p9-evidence-final-pair"></a>

### `archive/p9-evidence/final-pair`

**What:** P9 final paired acceptance matrices and their capacity/install environments

**Phase/decision:** P9; cited under D218.

**Key result:** Two matrix.md records on 0af32162aa9b with dirty trees: each reports 14,265 pytest tests, zero failed, 23 skipped; 45 process tests; 212 browser specs; lint 16 warnings. Optional I08/B02 unmeasured; capacity at 10,000 works ready in 1.01/1.02 s on one machine under load. These are historical results, not tests run by this tidy task.

**Size:** 14,103,431,674 bytes (13450.081 MiB), 36,810 files. **Read evidence:** `20261004T122132Z/matrix.md`, `20261004T122132Z/install/results.json`, `20261004T130443Z/matrix.md`, `20261004T130443Z/install/results.json`.

**Loss if dropped:** Dropping logs/XML/matrix/capacity outputs loses per-test failure and skip accounting, timing/load observations and measured capacity evidence. Generated install/virtual environments account for much of the size and are distinct from result evidence; exact rebuild equivalence is bilinmiyor.

**Tracked context:** [docs/product/p9-acceptance-record.md](../product/p9-acceptance-record.md), [docs/archive/local-runs.md](local-runs.md).

## Historical paths absent from the inspected tree

These documentation path prefixes have no matching run-directory entry in the current tree. Their original result, raw size and recoverability are bilinmiyor here; retain the dated tracked record and Git history rather than pretending a replacement raw artifact exists. Wildcards and brace expressions are recorded as written.

- `.local/'`
- `.local/INDEX.md`
- `.local/anchor-measure-2026-09-15-gemini-3.8-flash-low`
- `.local/anchor-measure-2026-09-15-sonnet-low`
- `.local/codex-boundary-2026-09-14`
- `.local/consult-search-recall-*`
- `.local/model-behavior-2026-09-15`
- `.local/p4-eval-2026-09-14-providers-run{1,2,3}`
- `.local/p4-eval-2026-09-15-order-run{1,2,3}`
- `.local/p4-eval-2026-09-15-packet`
- `.local/p4-eval-2026-09-15-report-run{1,2,3}`
- `.local/p5-measure-`
- `.local/p6-eval-`
- `.local/p6-slice0-fill`
- `.local/p8-b4-`
- `.local/p8-b4-2026-10-03`
- `.local/p8-b8b-`
- `.local/p8-b8b-2026-10-03`
- `.local/p9-`
- `.local/p9-*`
- `.local/p9-daily-use-log.md`
- `.local/p9-h1`
- `.local/p9-h10`
- `.local/p9-h5`
- `.local/p9-h6`
- `.local/p9-matrix`
- `.local/p9-owed`
- `.local/p9r-*`
- `.local/p9r-h9`
- `.local/p9r-h9b`
- `.local/phrasebank-check-2026-09-14`
- `.local/plan-review-2026-09-14`
- `.local/quantum-500-plan`
- `.local/quantum-500-run`
- `.local/quantum-feature-filter-2026-09-18-plan`
- `.local/quantum-feature-filter-2026-09-18-run`
- `.local/quantum-query-branches-plan`
- `.local/quantum-query-branches-run`
- `.local/report-behavior-`
- `.local/review-gpt-5.6-sol-high-2026-09-14.md`
- `.local/search-design-review-*`
- `.local/semantic-retrieval-2026-09-15`
- `.local/sw-abstract-lookup-`
- `.local/sw-code-stage-2026-09-22`
- `.local/sw-slice03-pairs-2026-09-20`
- `.local/sw-slice13h-acceptance-`
- `.local/sw-slice14-acceptance-`
- `.local/sw-slice14-bulk-sort-`
- `.local/sw-slice14a-acceptance-`
- `.local/sw-slice15-acceptance-`
- `.local/sw-slice16-acceptance-`
- `.local/sw-slice17-acceptance-`
- `.local/sw-slice19-acceptance-`
- `.local/sw-slice20-acceptance-`
- `.local/sw-slice21-acceptance-`
- `.local/sw-slice22-acceptance-`
- `.local/sw-slice23-acceptance-`
- `.local/sw-slice24-active`
- `.local/sw-slice24-campaign-`
- `.local/sw-slice25-acceptance-`
- `.local/sw-slice25-active`
- `.local/sw-slice25-remeasure-`
- `.local/sw-slice26-acceptance-`
- `.local/sw-slice27-active`
- `.local/sw-slice27-remeasure-`
- `.local/sw-slice28-acceptance-`
- `.local/sw-slice29-acceptance-`
- `.local/sw-slice30-active`
- `.local/…`
