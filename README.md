# DEIXIS

**Every cell points to its source.**

A research workspace for source-linked literature synthesis, evidence comparison,
and candidate-question development. Product name: **DEIXIS** (uppercase).
A first local-web development slice is implemented: question → OpenAlex search or attached PDF →
source selection → passage inspection → source-linked answer → reopen after restart. It has been
exercised manually with live OpenAlex and Codex, a backup/restore test is automated, and a browser-level
A–G acceptance suite runs against synthetic sources and a scripted model. P4 is still open: the
evaluation on a user-known source set (human citation review, coverage, correction time) has not been done.
Only OpenAlex and the Codex model connection are implemented; the other providers and model
connections remain planned.

## Run the first slice

Requires Python 3.12 with `uv`, Node.js, and the Codex CLI signed in to the DEIXIS Codex home.

```sh
uv sync
(cd apps/web && npm ci && npm run build)
CODEX_HOME="$HOME/Library/Application Support/DEIXIS/codex-home" codex login   # once
PYTHONPATH=backend uv run python -m deixis serve                                  # opens http://127.0.0.1:8765/
PYTHONPATH=backend uv run pytest                                                   # deterministic tests
(cd apps/web && npm run build && DEIXIS_ACCEPTANCE_DIR=/tmp/deixis-acceptance npm run test:acceptance)  # A–G in Chrome
PYTHONPATH=backend uv run python scripts/p4_eval/measure.py snapshot --research res_… --out eval-dir  # P4 measurement
PYTHONPATH=backend uv run python -m deixis backup ~/DEIXIS-backups                # safe while serving
DEIXIS_DATA_DIR=/new/empty/dir PYTHONPATH=backend uv run python -m deixis restore ~/DEIXIS-backups/deixis-backup-…
```

Backups hold the database snapshot, referenced PDFs and provider payloads with a SHA-256 manifest; the
DEIXIS Codex home (model sign-in) is never copied. Restore verifies every hash and refuses a data
directory that already has a library. Press Cmd/Ctrl+K in the UI to find research, source titles or pages.
The acceptance suite starts its own fixture server (mocked OpenAlex, fixed PDFs, a scripted model) and
writes screenshots and `results.json` to `DEIXIS_ACCEPTANCE_DIR`; it needs Google Chrome installed. The
measurement kit checks every citation link, looks up each DOI on Crossref, and writes `review.md` for
the person who knows the literature; `measure.py reopen` and `measure.py score` complete it. A `--known` list
may group its entries with `# stratum: name` lines, and `measure.py compare` puts several measured runs side by side.

Optional keys go in an untracked `.env` (see [providers.env.example](docs/product/providers.env.example)).
The Sources tab exports the included sources, and an answer's reference list its cited sources, as BibTeX or RIS.
A research with attached files can import one Zotero collection read-only, from the Zotero app on this computer (its
local API turned on) or from zotero.org with `ZOTERO_API_KEY` and `ZOTERO_LIBRARY_ID` (D16).

## Start here

- [Working mechanism, skill and implementation plan](docs/product/implementation-plan.md)
- [Documentation map](docs/README.md) and [repository layout](docs/layout.md)
- [Product decisions and integration boundary](docs/product/README.md)
- [Dated handoff and accepted conversation decisions](docs/desktop/README.md)
- [API and data design draft](docs/product/api-and-data.md)
- [Research methods](docs/methods/research-methods.md)
- [Reference index](docs/desktop/reference-index.md)
- [Historical design prompt](docs/desktop/design-prompt.md)
- [DEIXIS SVG icon](apps/web/public/deixis-icon.svg)

## Project separation

On 14 September 2026, design documents, the prototype and local reference evidence
were moved from the adjacent Quaestio repository into this directory. The product
bibliography and design decisions below were transferred from its README.
Historical Quaestio names and revision identifiers in the records are retained.
Quaestio remains the separate methodological skill: links to `../quaestio/` require
that sibling checkout. They do not indicate an implemented integration.

Private PDFs, raw reports and screenshots remain local and ignored by Git.

## Research-workspace methodological references

Recorded on 14 September 2026 from the Luna **Literature method check** review.
These references inform the proposed product's AI-assisted literature discovery,
synthesis and hypothesis development. They support individual methodological
components; they do not validate Quaestio's combined workflow, AI performance,
or ability to establish scientific originality.

| Reference | Relevant contribution | Boundary when used in Quaestio |
|---|---|---|
| Levac, D., Colquhoun, H., and O'Brien, K. K. (2010). [Scoping studies: advancing the methodology](https://doi.org/10.1186/1748-5908-5-69). *Implementation Science*, 5, 69. | Connect the purpose to the research question; iteratively select and chart studies; synthesize themes and refine the scope. | Health-research methodology. A conversational exploration is not automatically a formal scoping review; evidence quality also matters when identifying gaps. |
| Wohlin, C. (2014). [Guidelines for snowballing in systematic literature studies and a replication in software engineering](https://doi.org/10.1145/2601248.2601268). *EASE '14*, article 38, pp. 1–10. [Author manuscript](https://www.wohlin.eu/ease14.pdf). | Search reference lists backward and citing publications forward from relevant seed studies, iterating as needed. | A software-engineering replication supports the technique, not universal completeness. Using it alongside database queries is our workflow choice. |
| Robinson, K. A., et al. (2013). [Framework for Determining Research Gaps During Systematic Review: Evaluation](https://www.ncbi.nlm.nih.gov/books/NBK126708/). AHRQ Methods Research Report, no. 13-EHC019-EF. | Describe where evidence cannot support a conclusion and why: insufficient/imprecise, biased, inconsistent, or not the right information; characterize the gap using PICOS. | Developed for health systematic reviews. Engineering comparison dimensions require adaptation; neither an empty search nor a future-work statement establishes novelty. |
| Grant, M. J., and Booth, A. (2009). [A typology of reviews: an analysis of 14 review types and associated methodologies](https://doi.org/10.1111/j.1471-1842.2009.00848.x). *Health Information & Libraries Journal*, 26(2), 91–108. | Distinguish review approaches through Search, Appraisal, Synthesis and Analysis (SALSA), including their strengths and limitations. | A descriptive typology, not a single prescribed protocol or evidence that one AI workflow is superior. |
| Nyanchoka, L., et al. (2019). [A scoping review describes methods used to identify, prioritize and display gaps in health research](https://doi.org/10.1016/j.jclinepi.2019.01.005). *Journal of Clinical Epidemiology*, 109, 99–110. [PubMed](https://pubmed.ncbi.nlm.nih.gov/30708176/). | Surveys methods for identifying, prioritizing and displaying research gaps; reports the lack of standard methods at the time of the review. | A historical health-research finding, not proof that no standards exist today or that arbitrary gap scoring is valid. |

The proposed source groups (foundational work, reviews, and close recent studies),
user checkpoints, candidate cards and claim-specific kill-search are product
adaptations. Their usefulness and failure modes need separate evaluation. Record
search scope and access limits, distinguish author statements from inference,
and report an unsuccessful overlap search as **no match found within the searched
scope**, not as a novelty verdict. See the [product evidence contract](docs/product/api-and-data.md#proposed-output-contract)
and the existing [skill evidence register](../quaestio/references/evidence-base.md).

## AI research systems and evaluation references

Collected during the 14 September 2026 Luna repository review and Claude Opus 5
(medium) literature search. PaperLens, AI-Scientist and AI-Researcher received
bounded source-code inspection. CoI-Agent subsequently received a bounded code
review at `ac94317` on the same date; the other entries are paper or README
references. Code inspection is not runtime verification. None was installed or benchmarked in Quaestio.
These references complement the methodological sources above and the extended
method comparison below.

| Reference and source links | Relevance to Quaestio | Inspection boundary |
|---|---|---|
| **Chain of Ideas**, Li et al. (2024), *Chain of Ideas: Revolutionizing Research Via Novel Idea Development with LLM Agents*. [Paper, v5](https://arxiv.org/abs/2410.13185v5); [official CoI-Agent repository](https://github.com/DAMO-NLP-SG/CoI-Agent). | **Selected methodological basis** for organizing literature into research-development chains and using that synthesis to develop candidate questions. | Bounded code review at `ac94317`: chain construction, novelty loop, prompts and selected search/text functions. Runtime behavior, retrieval coverage and reported evaluation results have not been reproduced. |
| **Scideator**, Radensky et al., *Human-LLM Compound System for Scientific Ideation through Facet Recombination and Novelty Evaluation*. [Paper, v7, 2026 revision of the 2024 preprint](https://arxiv.org/abs/2409.14634v7). | Purpose/mechanism/evaluation facets, user-guided recombination, distance-controlled retrieval and facet-based comparison with prior work. | A complementary design reference, not a selected replacement for CoI. No verified code repository recorded; novelty classification is not conclusive proof of originality. |
| **ResearchAgent**, Baek et al. (2025), *ResearchAgent: Iterative Research Idea Generation over Scientific Literature with Large Language Models*. [NAACL paper](https://aclanthology.org/2025.naacl-long.342/); [PDF](https://aclanthology.org/2025.naacl-long.342.pdf); [preprint](https://arxiv.org/abs/2404.07738); [official repository](https://github.com/JinheonBaek/ResearchAgent). | Start from a core paper, retrieve related publications and concepts, and iteratively develop problems, methods and experiment designs. | Paper and repository identity checked; code not audited. Reviewing-agent feedback does not replace original-source verification. |
| **SciMON**, Wang et al. (2024), *SciMON: Scientific Inspiration Machines Optimized for Novelty*. [ACL paper](https://aclanthology.org/2024.acl-long.18/); [preprint](https://arxiv.org/abs/2305.14259); [code/resource link supplied by the paper](https://github.com/eaglew/clbd). | Literature-grounded inspiration retrieval and iterative comparison of candidate ideas with prior papers. | Paper-level reference; code not audited. Rewriting an idea to reduce similarity does not establish a substantive contribution. |
| **AI-Researcher**, Tang et al. (2025), *AI-Researcher: Autonomous Scientific Innovation*. [Paper](https://arxiv.org/abs/2505.18705); [PDF](https://arxiv.org/pdf/2505.18705); [repository](https://github.com/HKUDS/AI-Researcher); [inspected survey handoff](https://github.com/HKUDS/AI-Researcher/blob/f9a6f8480860c193afff600eeffe3defcee8a978/research_agent/inno/agents/inno_agent/survey_agent.py). | Structured handoffs between concepts, paper analysis, code analysis and research planning. | Bounded inspection at `f9a6f84`; selected entry points and memory/survey code. Benchmark/ML implementation workflows do not establish general question-first discovery performance. |
| **The AI Scientist**, Lu et al. (2024), *The AI Scientist: Towards Fully Automated Open-Ended Scientific Discovery*. [Paper](https://arxiv.org/abs/2408.06292); [repository](https://github.com/SakanaAI/AI-Scientist); [inspected idea/novelty code](https://github.com/SakanaAI/AI-Scientist/blob/1de1dbc1f4ee2c5f61e9c94348d55eb51d7fa2eb/ai_scientist/generate_ideas.py). | Separate idea generation, literature comparison, experiments and reporting. | Bounded inspection at `1de1dbc`. The abstract-based search and binary `novel` outcome are insufficient for Quaestio's claim-specific kill-search. |
| **PaperLens**. [Repository](https://github.com/vanthree31/PaperLens); [inspected AI analysis](https://github.com/vanthree31/PaperLens/blob/736af5af98c659153182ceefa5aee46e166055cb/routes/ai.py); [citation graph](https://github.com/vanthree31/PaperLens/blob/736af5af98c659153182ceefa5aee46e166055cb/routes/graph.py). | Natural-language paper discovery, comparison and citation-graph navigation. | Bounded inspection at `736af5a`; selected search/analysis/graph routes. The inspected analysis prompt uses abstracts; a complete claim-to-passage kill-search was not established. No associated paper is asserted here. |
| **Human evaluation of AI research ideas**, Si, Yang and Hashimoto (2024), *Can LLMs Generate Novel Research Ideas? A Large-Scale Human Study with 100+ NLP Researchers*. [Paper](https://arxiv.org/abs/2409.04109). | Evaluation design and the distinction between perceived novelty, feasibility and eventual research outcomes. | Abstract-level check. Quantitative results were not independently audited; this is not evidence of Quaestio's effectiveness. |

### CoI-Agent implementation inspection

The inspected [novelty check](https://github.com/DAMO-NLP-SG/CoI-Agent/blob/ac94317ff2d1997f362747edc2c9e5f0fdc9c450/agents.py#L467-L493)
returns `True` when no papers are retrieved and treats a parsed similarity value
other than `"1"` as novel. The [comparison prompt](https://github.com/DAMO-NLP-SG/CoI-Agent/blob/ac94317ff2d1997f362747edc2c9e5f0fdc9c450/prompts/deep_research_agent_prompts.py#L330-L360)
uses titles and abstracts. Its [idea-regeneration loop](https://github.com/DAMO-NLP-SG/CoI-Agent/blob/ac94317ff2d1997f362747edc2c9e5f0fdc9c450/agents.py#L424-L455)
has no explicit attempt cap in that loop. These are code observations, not executed
failure demonstrations. Quaestio's adaptation needs explicit unknown/error states,
validated output schemas, bounded retries and claim-specific original-source
checking; it must not inherit these automatic novelty decisions.

## Selected synthesis method: Chain of Ideas

**User decision, 14 September 2026: use Chain of Ideas for Quaestio's literature
synthesis and candidate-question development.** The selection adopts the method;
it does not mean the upstream software has been integrated or tested.

**Accepted design sequence:** construct the field map through research-development
trajectories; make candidates concrete through **purpose, mechanism and
evaluation**; then apply **kill-search to each candidate's specific claim**.
CoI provides the development-chain basis; the facet structure draws on Scideator,
and claim-specific adversarial checking follows Quaestio's evidence requirements.

Quaestio will adapt the method to its question-first workflow:

1. Interpret the question and retrieve foundational work, relevant reviews and
   close recent primary studies, explaining selection beyond citation counts.
2. Build evidence-linked development chains: what problem each study addressed,
   what it established or changed, and which uncertainty the next study pursued.
   Preserve competing branches and cross-links; chronology or a citation alone
   does not demonstrate an intellectual dependency.
3. Synthesize the remaining uncertainties and plausible research directions from
   these chains. Preserve source versions, passages and reading-depth limits.
4. Let the user steer the research direction, then describe each candidate's
   purpose (question or outcome), mechanism (proposed explanation or method),
   and evaluation (comparator and evidence needed to assess the claim). Make its
   claim specific enough to compare with prior work. Scale chains and candidates
   to the question, coverage and budget rather than enforcing fixed counts.
5. Apply a distinct **kill-search** to each candidate's specific claim: inspect the strongest prior
   work in the field, methodological neighbors and adjacent applications. Report
   established overlap, partial overlap, no match within scope, or insufficient
   evidence; an empty search is not a novelty verdict.
6. Present surviving or narrowed questions with conditional hypotheses,
   assumptions and an informative validation plan. Revise chains and claims when
   new evidence changes them; experiments remain a separately scoped activity.

This is Quaestio's adaptation of CoI, including its own provenance and kill-search
requirements, not a verbatim reproduction of the paper. The existing modular
skill remains the source-audit foundation. See the [continuation brief](docs/desktop/README.md#araştırma-yöntemi-kararı--chain-of-ideas)
for the accepted product decision.

## Extended method comparison and product recommendations

The [detailed research-methods document](docs/methods/research-methods.md)
records the focused 14 September 2026 review: established methods and books,
AI systems, existing repository coverage, proposed additions, guardrail ownership,
candidate/claim evidence structures, future evaluation and search/access limits.
It distinguishes accepted choices from recommendations and implemented behavior.
This is a bounded design review, not an exhaustive literature review or a measured
ranking of the most popular methods. Book inspection was limited to publisher
descriptions and contents; source-specific reading levels are in that document.

**Recommendation:** retain the selected CoI → purpose/mechanism/evaluation →
claim-specific kill-search design. Make concept comparison, assumption analysis,
conditional cross-literature bridges, competing explanations and informative
checks explicit inside the workflow. Add a claim-element-to-passage matrix to
kill-search. These are internal methods, not additional user-facing skills.
The suggested four internal responsibilities remain an architecture proposal;
this documentation does not implement CoI or scientific decision gates.

**Latest architecture constraint:** the user does not want a multi-agent system.
The first version should complete research workflows with one main agent using
method files and tools. An additional bounded review is optional and separately
user-requested; no standing generator/reviewer pair is required. Deterministic
record, retrieval-state and budget checks are application functions. Keep brief
feasibility assessment inside candidate development, begin with a concise field
map before focused synthesis, and reserve human decisions for meaningful direction,
scope, experiment or cost changes. Revision may end in closure or deferral.
Structured PDF extraction does not by itself establish mathematical understanding.

The user also proposed an optional model-selected review: choose a candidate or
report, select an available model and receive a separate evidence-linked assessment
of a versioned snapshot. Findings may be fed back into the main work by the user;
the reviewer does not automatically edit it. Existing evidence is the default,
with extra retrieval explicitly selected. See the [review design](docs/methods/research-methods.md#isteğe-bağlı-başka-modelle-inceleme)
for scope, provenance and budget boundaries. A browser-only UI prototype once demonstrated model/focus selection, a separate
sample report and staged feedback; it was removed ([D10](docs/decisions.md)).
Real model execution, evidence review and production persistence are not implemented.

The identifiers below match the detailed document. Existing references above
and the [E1–E12 skill evidence register](../quaestio/references/evidence-base.md) are retained;
different versions of the same work are not independent evidence.

| ID | Reference | Contribution and boundary |
|---|---|---|
| M1 | Booth, W. C., Colomb, G. G., Williams, J. M., Bizup, J., and FitzGerald, W. T. (2024). [The Craft of Research, fifth edition](https://press.uchicago.edu/ucp/books/book/chicago/C/bo215874008.html). University of Chicago Press. | Question, problem and significance framing; publisher/contents inspection, not whole-book review or efficacy evidence. |
| M2 | Webster, J., and Watson, R. T. (2002). [Analyzing the Past to Prepare for the Future: Writing a Literature Review](https://aisel.aisnet.org/misq/vol26/iss2/3/). MIS Quarterly, 26(2), xiii–xxiii. | Concept-centric comparison; already represented in E5. Current metadata check and dated prior reading record. |
| M3 | Alvesson, M., and Sandberg, J. (2011). [Generating Research Questions Through Problematization](https://doi.org/10.5465/amr.2009.0188). Academy of Management Review, 36(2), 247–271. [Original PDF](https://fenix.iseg.ulisboa.pt/downloadFile/563083097454984/4.pdf). | Challenge consequential assumptions; conceptual methodology, adapted beyond management theory. |
| M4 | Alvesson, M., and Sandberg, J. (2024). [Constructing Research Questions: Doing Interesting Research, second edition](https://in.sagepub.com/en-in/ind/constructing-research-questions/book286538). SAGE. | Book treatment of problematization; publisher/contents inspection. Same method family as M3. |
| M5 | Swanson, D. R., and Smalheiser, N. R. (1996). [Undiscovered Public Knowledge: a Ten-Year Update](https://cdn.aaai.org/KDD/1996/KDD96-051.pdf). KDD, 295–298. | Connections between separate literatures suggest hypotheses; they do not prove the inferred relationship. |
| M6 | Gentner, D. (1983). [Structure-Mapping: A Theoretical Framework for Analogy](https://doi.org/10.1207/s15516709cog0702_3). Cognitive Science, 7(2), 155–170. [Author-hosted PDF](https://groups.psych.northwestern.edu/gentner/papers/Gentner83.2b.pdf). | Relational mapping rather than surface resemblance; transfer still needs domain validation. |
| M7 | Ritchey, T. (2018). [General morphological analysis as a basic scientific modelling method](https://www.swemorph.com/pdf/tfsc-gma-basic.pdf). Technological Forecasting & Social Change, 126, 81–91. | Optional combination-space and consistency analysis; not a new default stage or novelty test. |
| M8 | Platt, J. R. (1964). [Strong Inference](https://doi.org/10.1126/science.146.3642.347). Science, 146(3642), 347–353. [Original article scan](https://worthylab.org/wp-content/uploads/2019/05/platt1964.pdf). | Competing hypotheses and discriminating tests; historical methodological argument, not universal efficacy evidence. |
| M9 | Shaw, M. (2003). [Writing Good Software Engineering Research Papers](https://www.cs.cmu.edu/~Compose/shaw-icse03.pdf). ICSE, 726–736. | Match evidence to the contribution; retained E11 reading record, not a new full-text inspection. |
| M10 | Gottweis, J., et al. (2026 revision of the 2025 preprint). [Accelerating scientific discovery with Co-Scientist, v2](https://arxiv.org/abs/2502.18864v2). [Linked Nature publication](https://doi.org/10.1038/s41586-026-10644-y). | Iterative hypothesis generation/critique; abstract and official overview checked. Biomedical validation is not a cross-domain guarantee. No code audit. |
| M11 | Liu, H., Zhou, Y., Li, M., Yuan, C., and Tan, C. (2025 revision). [Literature Meets Data: A Synergistic Approach to Hypothesis Generation, v3](https://arxiv.org/abs/2410.17309v3). [HypoGeniC/HypoRefine repository](https://github.com/ChicagoHAI/hypothesis-generation). | Optional future data-supported mode; abstract/README review, no code audit. |
| M12 | Liu, H., Huang, S., Hu, J., Zhou, Y., and Tan, C. (2026 revision). [HypoBench: Towards Systematic and Principled Benchmarking for Hypothesis Generation, v2](https://arxiv.org/abs/2504.11524v2). | Real and synthetic hypothesis-generation tasks; abstract-level evaluation reference, not a benchmark already run here. |
| M13 | Si, C., Hashimoto, T., and Yang, D. (2025). [The Ideation–Execution Gap: Execution Outcomes of LLM-Generated versus Human Research Ideas](https://arxiv.org/abs/2506.20803v1). | Separate proposal ratings from execution outcomes; complements the earlier Si study and E12. |
| M14 | Ikoma, H., and Mitamura, T. (2025). [Can AI Examine Novelty of Patents?: Novelty Evaluation Based on the Correspondence between Patent Claim and Prior Art](https://arxiv.org/abs/2502.06316v1). | Claim-to-passage correspondence for kill-search; patent-specific labels do not establish scientific originality. Luna inspected the PDF and appendices. |
| M15 | Jeevan M. and Manjunatha B. N. (2026). [AI-Based Patent Novelty Checker and Prior-Art Analysis Using Transformer Embeddings and FAISS](https://ijsrem.com/uploads/articles/1785000922694-05d18bacb5dd-Research-Paper-Pdf.pdf). IJSREM, 10(07). | Retrieval/reporting prototype; dataset, accuracy and novelty-score calibration evidence insufficient for core-method adoption. Luna inspected the five-page PDF; article DOI not supplied. |

No upstream system was installed or benchmarked in this follow-up. Semantic
matching and model critique provide evidence to inspect; they do not certify
novelty. Deterministic checks can enforce records, schemas, versions and budgets,
while semantic support and scientific value require substantive assessment.
