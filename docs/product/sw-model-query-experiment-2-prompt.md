# Task: model-written query, second measurement — revised prompt, "model only" against "model + code", then the slice plan

Repo: `/Users/huguryildiz/Documents/GitHub/DEIXIS`. A measurement first, then a slice file. No product code changes in
this task. Results go to `.local/sw-model-query-experiment-2026-09-24/`; nothing is written to `docs/` except the slice
file at the end, and that only after the owner says "uygun". Implementer: Opus · high. Written 2026-09-23 at the end of
the slice 13g conversation; read this whole file before anything else.

## Where things stand (2026-09-23)

- **Slice 13g is in `main`** (`c62eed0`, D90, D91): the query fits both blocks evenly, the second round keeps its task
  block and only adds, Scopus left the sw search (last abstract source on an institutional network), `detailed` reads
  1,000 per query. Its Task 3 (two code bounds on the block labelling) failed the live acceptance and was removed. The
  second acceptance (`.local/sw-slice13g-acceptance-2026-09-23b/result.md`) is the code baseline: quantum 20 verified
  works over two rounds, packet size 4, sepsis round two 482 records.
- **Owner's decision (2026-09-23): the model writes the query**, not the code rule. Elicit works this way on its keyword
  side (a model drafts the first Boolean query, the user corrects it); it also has an embedding search over its own
  138M-paper corpus, which DEIXIS does not have.
- **First measurement** (`.local/sw-model-query-experiment-2026-09-23/`: `prompt_p.md`, `schema_p.json`, `run.py`,
  `result.md`): the model picks at most 6 terms plus backups; code counts each term and swaps in a backup on a zero or
  on a setting term above 1M records. 9 `gpt-5.6-luna` calls, 426 OpenAlex requests.
  - Packet size: the model found the 4 findable works in 846 records (code: 2,669; code's first round 1 of 6 because
    the labelling put "channel" in the setting block). The model never wrote "channel".
  - Quantum: the model alone found 2, 17 and 12 (three calls) against the code's 20; it wrote the task block as method
    names only (integer / linear / mixed-integer programming) and missed papers that do not name the method in their
    abstract. Code + model together: 23 (g009, g014, g030 came only from the model's query).
  - Sepsis (no ground truth): the model's pools are far smaller (95–1,137 records against 3,192).
- **Reviews** by `gpt-5.6-sol` and `gpt-6-sol` (high) agree on: the model writes the query; the prompt must make every
  task block hold at least one term naming the topic or the work done, with method names as additions; one model call
  per scope revision, stored, no majority vote; counts are warnings, not verdicts (drop the 1M setting rule); code
  enforces the at-most-6 total, both blocks filled, syntax, duplicates. They differ on whether the code query is always
  searched beside the model's: `gpt-6-sol` says not yet — the 23 came from picking good calls after the fact — and
  wants it as an option on the approval card, decided by a measurement with a fixed budget. This task is that
  measurement.

## Step 1: revise the prompt

Copy `prompt_p.md` / `schema_p.json` to the new folder as `prompt_p2.md` / `schema_p2.json` and change only this:

1. The task block holds at least one term that names the topic or the work done (the problem, the object designed or
   optimised, the process studied) in words any relevant paper would use; method, algorithm or model-family names
   come only beside such a term. Before answering, the model checks: "would a relevant paper that names none of my
   method terms still be found?" If not, it replaces a method term with a topic term. A question that asks for one
   specific method may keep that method as a main term.
2. Soften "every term must be enough on its own" to: every term, together with a term of the other block, should find
   papers worth screening.
3. Each chosen term carries `kind`: `topic` | `method` | `population` | `other`, plus the short `why`.
4. The schema holds no domain word. Code (the experiment script) enforces the 6-term total and both blocks non-empty;
   an answer that breaks them is one repair call at most, then recorded as failed.

Keep everything else of `prompt_p.md` (what to leave out: compared features, answer words, general words, welded "X
optimization", singular/plural). No topic word may appear in the prompt's rules or examples beyond the generic ones
already there; the examples must not come from the three test questions.

## Step 2: measure

Same three questions and ground truth as `.local/sw-vocabulary-experiment-2026-09-23/common.py`, same paced OpenAlex
client and ledger, `gpt-5.6-luna` · medium through `CodexAdapter.run_step` (as `run.py` does), `detailed` budget,
the product's 13g code for fitting (`compile_block_queries`) and the second round (`expand`,
`second_round_vocabulary`). Code checks: a term with zero records alone is replaced by the next backup; nothing else
is replaced (the 1M rule is gone); every count is recorded.

Three calls per question, each scored on its own (the product will make one call; the spread says how much one call
can miss). Arms, per call:

- **M — model only:** round 1 and round 2 of the model's query.
- **MK — model + code, same budget:** the model's query and the code's 13g first-round query
  (`.local/sw-slice13g-acceptance-2026-09-23b/raw/qN-vocabulary.json`), each read to 1,000 records (so the two
  together read what one query read in the baseline), then the second round of the model's query to 1,000.
- Baseline **A13g** read from its raw files, reported both at 2,000 per query (as accepted) and cut to the first 1,000
  per query, so the budgets compare.

A query already read by any earlier experiment is taken from its raw file (see `run.py::read`).

Report per question, call and arm: the queries, counts, verified works in the first 1,000 / 2,000, distinct records,
and the terms by `kind`; for sepsis the first 25 titles of each round. Say how many OpenAlex requests and model calls
it cost (expected: 9–12 calls, 300–500 requests; stop and report on repeated 429s; the free daily budget ran out on
2026-09-23).

**Decision rule, fixed before running:**
- If **M** reaches, on **every** one of its three calls, quantum ≥ 18 and packet ≥ 4 at the equal budget, the slice is
  "model only", with the code query offered as an option on the approval card.
- Else if **MK** reaches quantum ≥ 20 and packet ≥ 4 on every call, the slice is "model + code by default".
- Else neither; stop and report what failed, with no slice file.

Say what is **ölçülmedi**: one model, three questions, a weak packet-size answer list (6 works, 2 not findable by the
question's words), sepsis unlabelled, OpenAlex order only (not what the model later reads or includes).

## Step 3: the slice file (only if a rule above passed, and only after "uygun")

Write `docs/product/sw-slice14?-model-query.md` in the style of `sw-slice13g-query-repair.md` (Turkish, Tasks with
tests first) and a row in `docs/product/sw-status.md`. It must cover: a new model step (method package reference file,
contract and schema under `contracts/research/`, `RUNTIME_FILES`, `skill_package_hash` changes and is recorded), one
call per scope revision stored with its StepInput, at most one repair, no silent fallback to the code query when the
call fails (the run pauses or the user chooses on the card); code checks (6-term total, both blocks, syntax,
duplicates, zero-count backup swap, counts shown as warnings); the approval card (`apps/web/src/ProtocolApproval.tsx`)
showing the model's query, kinds, backups, counts and the code query as an option; the protocol body recording the
prompt version, the model's answer and the query really searched (a new field needs a version note in the decision);
`legacy` unchanged; frozen protocols stand. Decision number: the next free one after D91.

## Rules

- `git pull --ff-only` first; work on `main`; no branch, no PR, no AI attribution. This task commits nothing but the
  slice file (after "uygun"); experiment files stay in `.local/`.
- No product code, method package or contract change in steps 1–2; `skill_package_hash` unchanged.
- Do not start, stop or query the service on port 8765 and do not open the product database.
- Sol reviews: `gpt-6-sol` · high through the real Codex binary (`/Applications/ChatGPT.app/Contents/Resources/codex
  exec -m gpt-6-sol -c model_reasoning_effort="high" -s read-only --skip-git-repo-check -C "$PWD" -o answer.md - <
  prompt.md`); the `~/.local/bin/codex` symlink cannot start its shell and the reviewer then reads no file.
- Write to the owner in plain Turkish first, codes after (CLAUDE.md "Anlatım Dili").
