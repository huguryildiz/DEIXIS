# Task: P6 slice 1, batch P5.5 — make the section instruction require phrasebank frames

Repo: `/Users/huguryildiz/Documents/GitHub/DEIXIS`.

This batch is **not in the plan**. It comes from the first real-model report run (18 September, recorded in
`docs/product/p6-slice1-handoff.md` under **P5**), which paused after round A because sections III, IV and V
each contained sentences that follow no phrasebank frame.

## What the measurement showed (do not re-litigate it, build on it)

- The Turkish phrasebank is complete: 1618 of 1618 frames have a `tr:` rendering and they read correctly.
- The eleven flagged sentences are **not near-misses**. Their best frame score is between −0.40 and −0.70 and
  they share **0 or 1** fixed words with the nearest frame. The model wrote natural prose and used no frame.
- `references/report.md` currently says, in the shared section-instruction preamble: "write plainly and re-use
  frames rather than inventing new phrasing" — an invitation, not a requirement.
- `phrasebank.REPORT_PHRASEBANK_SECTIONS` already narrows the frames each section receives, and the rendered
  frames do reach the model (they are in the stored `developer_instructions`, ~47 KB).

## What to change

**File:** `methods/deixis-research/references/report.md` only (plus `provenance.json`, see below).
**Do not change any Python.** This batch is a method-package text change.

1. In the `report_section` instruction, replace the soft sentence with a **requirement**, in the file's own
   voice and register (read the surrounding text and match it — short, declarative, no marketing):
   - every sentence of `claims[].text` and `insufficient_evidence[].reason` must follow one of the frames
     supplied for that section: keep that frame's fixed words, in the frame's order, and put your own content
     in the slots;
   - the frames are given in the answer's language; a Turkish section uses the Turkish rendering;
   - choosing a frame is a phrasing decision, never an evidence decision — **never** pick a frame that says
     more than the cited passage supports, and never change what a claim asserts to make a frame fit
     (this rule must be explicit and must outrank the frame requirement; `AGENTS.md`'s evidence contract wins);
   - if no supplied frame can carry the sentence honestly, keep the sentence plain and expect it to be
     recorded as an exception, rather than distorting the claim.
2. Say plainly what happens to an unframed sentence today: the section is not marked valid and the run stops
   for repair. Do not promise a repair step that does not exist yet.
3. Do **not** paste frames into `report.md`. The frames are already delivered per section; duplicating them
   would fork the phrasebank.

## Also fix one stale record

`provenance.json`'s `phrasebank.use` says the phrasebank is "loaded into grounded_answer steps only". That is
no longer true: report steps receive it too (`domain/skill.py::RUNTIME_FILES` lists the phrasebank for
`report_section` and `report_phrase_repair`). Correct that sentence to match the code, and add one sentence to
the `references/report.md` entry in `adaptations` recording this change with the date **2026-09-18** and why
(the first real-model run produced no framed sentences). Keep the file's existing style; change nothing else
in it.

## Ground rules

1. **Run NO state-changing git command.** `git status` / `git diff` / `git log` are fine. The reviewing session
   commits.
2. **Do not touch** anything under `apps/web/`, `backend/`, `docs/decisions.md`, `tests/test_corpus_removal.py`,
   `tests/test_provider_flow.py`, `tests/test_providers.py`, `.gitignore`, `.impeccable.md`, or the
   `Elicit - *.csv` files. Several carry another session's uncommitted edits.
3. Editing a runtime file changes `skill_package_hash`. That is expected. The app refuses to start if the
   package integrity check fails: frontmatter `name` must match the directory, relative links must resolve,
   `provenance.json` must keep its required keys. **Verify integrity after your edit** with
   `PYTHONPATH=backend:. uv run --no-sync python -c "from deixis.domain import skill; print(skill.integrity_issues())"`
   and paste the output.
4. **Do not invent.** If something cannot be written as specified, stop and report it.

## Read first

- `methods/deixis-research/references/report.md` — the whole file, especially the shared section preamble and
  `## Section instructions (report_section)`.
- `methods/deixis-research/SKILL.md` — the evidence rules your wording must not weaken.
- `backend/deixis/domain/phrasebank.py` — `REPORT_PHRASEBANK_SECTIONS`, `render`, and `_follows`/`_score`, so
  your wording describes the check that actually runs (fixed words, in order, per frame).
- `AGENTS.md` — the evidence contract.
- `docs/product/p6-slice1-handoff.md` — the **P5** entry.

## Procedure

1. Read everything above.
2. Make the edit.
3. Run the integrity check and paste its output.
4. Run `PYTHONPATH=backend:. uv run --no-sync pytest -q`. Expect `1 failed, 664 passed`; the only acceptable
   failure is `tests/test_documents.py::test_extraction_is_stopped_when_it_exceeds_the_memory_limit`.
   **If a test fails because the package hash changed, say exactly which test and why — do not "fix" it by
   loosening the test.**

## Final message

- the exact wording you put in, quoted;
- integrity-check output and test counts;
- whether any test depends on the package hash, and what happened;
- every place this brief could not be followed as written, and what you did instead;
- anything new you found missing, contradictory or already broken;
- what you did NOT do.
