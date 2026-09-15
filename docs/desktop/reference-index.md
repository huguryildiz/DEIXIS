# Reference index — 14 September 2026

Start with the [current product map](../product/README.md) and the [dated handoff](README.md). The owner selected our
own local web application, with Tauri packaging later. Alternatives below remain
design references, not a prerequisite build-versus-buy decision.

For methodological sources, see the [focused research-method comparison](../methods/research-methods.md)
and the [root bibliography](../../README.md#extended-method-comparison-and-product-recommendations).
They record accepted CoI design, proposed complements, reading limits and the
user-supplied patent papers reviewed by Luna. These records are separate from the
historical local evidence package below.

## Local evidence package

[Open the package](../../local-reference/2026-09-14/README.md).
It contains 49 unchanged source-file copies (47 initial files and two later UI
screenshots), plus its own README and transfer index.
The [CSV index](../../local-reference/2026-09-14/transfer-index.csv) records original
absolute path, package-relative destination and SHA-256 for every copied file.
Source files were not removed. This is a local snapshot; later changes to the
original files will not automatically update these copies.

| Group | Count | Location and purpose |
|---|---:|---|
| Original skill drafts | 4 | [Drafts](../../local-reference/2026-09-14/original-skill-drafts/): design history, not active instructions |
| Method PDFs | 9 | [Research methods](../../local-reference/2026-09-14/algae-reference/literature/pdfs/03_research_methods/): methodological source material |
| Existing method reading notes | 9 | [Source notes](../../local-reference/2026-09-14/algae-reference/literature/source_notes/): historical secondary aids, not fresh verification |
| Domain PDFs linked by HTML reports | 10 | `algae-reference/literature/pdfs/01_core_mc_optimization/` and `02_algae_biology_and_channel_transfer/` |
| Reports | 4 | [Reports](../../local-reference/2026-09-14/algae-reference/reports/): 2 HTML examples, methods bibliography, external Elicit-style output |
| Existing related prompts | 3 | [Prompts](../../local-reference/2026-09-14/algae-reference/prompts/): skill-suite, methods search and NotebookLM cross-check |
| Screenshots | 10 | [Screenshots](../../local-reference/2026-09-14/screenshots/): 9 UI references plus Finder diagnostic |

## Important examples

- [Literature-search HTML](../../local-reference/2026-09-14/algae-reference/reports/2026-09-13-lit-search-biological-molecular-communication-or-milp-models.html)
- [Research-gap HTML](../../local-reference/2026-09-14/algae-reference/reports/2026-09-13-research-gap-operations-research-molecular-communication.html)
- [Methods literature report](../../local-reference/2026-09-14/algae-reference/reports/2026-09-13-top10-research-gap-papers.md)
- [External Elicit-style evidence assessment](../../local-reference/2026-09-14/algae-reference/reports/external_ai/2026-09-14-elicit-evidence-gated-gap-assessment.md)

The two HTML reports were read during this conversation. They report constrained
API access and bounded local-corpus coverage. Their figures, scores and recommendations
are historical output, not a validated novelty/admission decision. The external
assessment includes numerical rankings, model-admission wording and citation
metadata that require independent checking; do not inherit them as facts.

All direct relative PDF hrefs in the two HTML reports are copied with the original
directory relationships. External DOI/arXiv links still require network access.
The HTML retains external fonts and, in one report, a Chart.js CDN dependency;
an offline chart rendering is not guaranteed. The full algae research repository
was not copied. Text-only filenames in external reports can refer to other papers
outside this bounded package. Historical notes/prompts can likewise mention source
files outside it; consult the transfer index and original project when necessary.

The nine method PDFs were located and transferred, not all newly read in this
conversation. Do not claim fresh full-text review of them. The local folder does
not include every name mentioned earlier: Swanson and ResearchAgent, for example,
were mentioned as literature leads but have no method PDF in this transferred set.

## How to use the original four drafts

Retain useful closest-work comparison, source anchoring and falsification ideas.
Reconsider the field-specific OR assumptions, prohibition on AI-generated questions,
blanket rejection of CSV/corpus creation, mandatory pilot-before-synthesis rule,
fixed three-day/shape-difference gate, and collaborator requirements imposed on
every field. These conflict with the general application brief when treated as
universal rules. Their file contents do not override the user's selected scope.

## UI references

At the owner's request, the nine initial UI images are also stored in
[docs/desktop/screenshots/](screenshots/), the working UI-reference location.
This directory is gitignored because the images include private account context.
The original local-reference package and its transfer hashes are preserved.
The Finder diagnostic remains only in that package.

1. [01-consensus-home-attach.png](screenshots/01-consensus-home-attach.png): entry field and attach/source menu.
2. [02-consensus-source-scope.png](screenshots/02-consensus-source-scope.png): corpus selector.
3. [03-consensus-library.png](screenshots/03-consensus-library.png): library table and scoped chat.
4. [04-elicit-home.png](screenshots/04-elicit-home.png): quiet light layout and research entry.
5. [05-elicit-command-search.png](screenshots/05-elicit-command-search.png): global command/search panel.
6. [06-elicit-recents.png](screenshots/06-elicit-recents.png): session history.
7. [07-elicit-library.png](screenshots/07-elicit-library.png): collections, metadata gaps and duplicate review.
8. `08-finder-hidden-files-diagnostic.png`: troubleshooting evidence only.
9. [09-elicit-research-progress-artifacts.png](screenshots/09-elicit-research-progress-artifacts.png): light research conversation, compact source-check status, inline citations, artifact access and persistent composer.
10. [10-consensus-research-references-panel.png](screenshots/10-consensus-research-references-panel.png): dark split workspace, collapsible search steps, right-hand reference cards, supporting-quote links and PDF access.

The last two screenshots were supplied after the progressive-results UI discussion.
Their counts, study labels, scientific claims and model-admission conclusions are
unverified screen content, not Quaestio requirements or established evidence.
Record observable interaction patterns only; do not infer hidden product behavior.

Screenshots include private account/desktop context and third-party branding.
They are local design references, not prepared public assets.

## Live Chrome UI inspection

Inspected 2026-09-14 in the user's existing signed-in Chrome tabs, read-only.
No new research query was submitted and no upload, subscription change or model
execution was initiated. Observations apply to this account/session, not every tier.

- Elicit home: distinct Research agent, Report, Systematic review, Find papers,
  Chat with papers and Extract data choices. The Report corpus menu showed
  research papers and clinical trials.
- Existing Elicit research: one timeline item said 43 public sources checked.
  Expanding it showed indexing 43 sources, three searches and named reading steps.
  The later final response in the same research offered 17 cited sources. Neither
  the timeline label nor those counts demonstrate full reading of every source.
- Existing Consensus response: References showed 20 results. Corpus choices
  distinguished All, Medical and My Library; library access was upgrade-gated in
  this account. These observed counts are not global product limits.
- Opening a Consensus reference exposed Overview, Snapshot, Attachment, Evidence
  and Metadata. Evidence (8) showed passages with abstract/body/conclusion labels
  and links to show them in abstract/full text. Scientific claims were not audited.

On 2026-09-15 the owner shared three screenshots of their Elicit Library for P5
design. They are not stored in the repository. The observations below come from them:

- **Library list.** "Library / All" showed 25 sources and one personal collection.
  The toolbar held filters, two row densities, collections, tags, export, delete
  and search, with "Connect Zotero" and "Upload" above it. Two rows read
  "No title found".
- **Paper details.** Selecting a row opened a "Paper details" panel. It listed
  authors, year, the PDF file name and a "Full text" status, followed by an edit
  control, "Replace PDF", "View" and the abstract.
- **Reader.** "View" opened the paper with a "Source" link and a "Plain text / PDF"
  toggle. The plain text showed an extraction artifact: "MOLECULAR" had become
  "M OLECULAR" because of a drop capital.
- **Metadata editing.** A fourth screenshot showed the edit control in use, opening
  "Edit paper details". The form had "Name", "Authors" with an "Add" button,
  "Abstract", and "Cancel" and "Update" buttons; "Update" was greyed out while no
  field had changed. No DOI, year or venue field appeared in the visible part of
  the form.

The extraction table was not seen live. Its description in the P5 plan comes from
Elicit's help articles. The owner asked the Claude in Chrome extension to look for
one read-only in the same account. Its report said:

- **No extraction table.** The account had no extraction table or systematic review.
  Recents held three "Session" items: report or agent-chat conversations with
  inline citations, a "View N cited sources" control and "Follow-ups" suggestions,
  but no row/column grid.
- **"New from selection".** Selecting papers in Library opened a "New from selection"
  panel with "Review duplicates", "Start systematic review" and "Extract data".
  These actions were not clicked.
- **Other.** The IoNBT collection was empty. The "New systematic review" card looked
  greyed out next to "New search" and "New research report"; the report did not
  confirm whether that was a plan limit.

The owner then shared two screenshots of their Consensus library, also on
2026-09-15 and not stored in the repository:

- **Navigation.** The page was titled "My Library" and had three tabs:
  "Items (25)", "Threads" and "Suggested". A banner read "20 suggested papers since
  you last checked" and had a "View" button. The sidebar listed "Back Home",
  "My Library", "Collections" (one: IoNBT), "Zotero Import", "Learn", "Contact" and
  "API & MCP", followed by a remaining Pro-message count and "Upgrade".
- **Table.** Columns were Title, Type ("Journal Article" or "Preprint"), Authors and
  Journal; preprints showed "—" for Journal. Above the table sat "Search items in
  My Library", a citation icon and a download icon. Hovering a row showed "Ask",
  "Save" (with a menu), a related-papers-style icon, a citation icon and a link icon.
- **Composer.** A persistent "Ask the research..." box at the bottom had "+",
  "Corpus", "Deep" and "Filter" controls.
- **Item panel.** Selecting a row opened a panel headed by the item type
  ("Preprint"), with tabs "Overview", "Snapshot", "Attachment" and "Metadata".
  Metadata was a Field/Value table: Name, Attachment (a check mark and "PDF"),
  Type, Year, Authors (2) and Accessed (Sep 14, 2026). "Ask", "Save", citation,
  link and download actions sat at the bottom.

The screenshots do not show whether the "Preprint" type label is correct for that
paper, what "Suggested" is based on, or how "Ask" on one row limits the corpus.

The owner accepted question/scope/depth/budget-led corpus growth rather than a
mandatory paper count. Quaestio should distinguish retrieved, screened-in,
inspected and answer-cited sources; fixed counts do not establish sufficiency.

Separately inspected official product documentation describes Consensus Pro as
up to 20 papers and Deep as 50–100 papers, while Elicit's pricing page distinguishes
screening capacity from report data-source capacity. These are vendor-described
workflow limits, not observed comparative performance or Quaestio defaults:
[Consensus search modes](https://help.consensus.app/en/articles/9922660-how-to-search-best-practices),
[Elicit plans](https://elicit.com/pricing).

## Official web references inspected during the conversation

Accessed 2026-09-14. These links capture the basis of earlier discussion; features,
prices, authentication and distribution requirements must be rechecked when used.
No competing application was installed or benchmarked. Later live Chrome UI
inspection is recorded above; it is separate from the original document review.

- [AnythingLLM](https://anythingllm.com/) — desktop document/agent workflow.
- [Open Notebook](https://github.com/lfnovo/open-notebook) — self-hosted notebooks,
  model providers, PDF sources and extensible application structure.
- [AI Notebook](https://github.com/lukoplt/AI-notebook) — desktop PDF/source chat reference.
- [GPT Researcher](https://github.com/assafelovic/gpt-researcher) — local/web report pipeline.
- [Elicit plans](https://elicit.com/pricing) — free and paid feature boundaries;
  do not freeze the earlier discussion into permanent quota/price claims.
- [Electron introduction](https://www.electronjs.org/docs/latest) — earlier desktop alternative.
- [Tauri distribution](https://tauri.app/distribute/) — selected later packaging direction.
- [Agent Skills specification](https://agentskills.io/specification) — modular skill format.

Consensus UI requirements come from the user's screenshots and the later live UI check;
product-wide Consensus pricing or capabilities were not comprehensively audited.
