# Task: model-written query experiment — the model writes the sw search blocks, code only checks them, on three fields

Repo: `/Users/huguryildiz/Documents/GitHub/DEIXIS`. A measurement, not a slice: no product code changes. Results go to
`.local/sw-model-query-experiment-2026-09-23/`; nothing is written to `docs/` until the owner says "uygun".
Implementer: Opus · high. Written 2026-09-23 at the end of the slice 13g conversation.

## Why

The owner decided (2026-09-23) that the model, not the code rule, should write the sw query: the words, the two blocks
and which words matter most. Elicit's keyword search works this way: a model drafts the first Boolean query from the
question and the user corrects it. Before the product changes, this measures whether a model-written query, checked by
code and fitted by slice 13g's rules, finds at least as many verified works as today's code list.

What is already known:

- **Arm B of the vocabulary experiment** (`.local/sw-vocabulary-experiment-2026-09-23/result.md`) let the model
  propose the blocks and lost to the code list (quantum 9 against 18 verified works, packet size 0 against 1). The
  loss came from the set-up, not from the model's words: three runs with a 2-of-3 majority threw out most proposed
  terms, since every run spelled them differently (14 of 18 packet-size task terms appeared in one run only), and the
  old fitting cut the task block to one term. Both are gone or avoidable now.
- **Slice 13g** (D90) fits the two blocks evenly (3 + 3, 2 + 4), and its second round keeps the task block and only
  adds. Its acceptance (`.local/sw-slice13g-acceptance-2026-09-23b/`) is the baseline here: quantum 20 verified works
  in two rounds, packet size 4, sepsis round two 482 records.
- **The code list's known faults** that a model could fix: on the packet-size question the labelling put "channel"
  and "error model" (features the question wants compared) in the setting block, and the first round found 1 of 6
  works; on the quantum question "mathematical optimization models" was labelled `claim` and never searched, and
  which four task words fit was decided by their order in the question.

## Arms

Same three questions as the vocabulary experiment (`common.QUESTIONS`), same ground truth (`common.positives`), same
paced OpenAlex client and ledger pattern, `detailed` budget. Every arm is compiled by the product's
`compile_block_queries` (13g fitting) and its second round by the product's `expand` + `second_round_vocabulary`.

- **A13g — baseline.** Read from `.local/sw-slice13g-acceptance-2026-09-23b/raw/`; nothing re-run.
- **M1, M2, M3 — one model call each, no vote.** The three stored B runs (`raw/qN-B-runs.json` of the vocabulary
  experiment) taken one at a time: the model's own order in each block is the priority the fitting cuts by (from the
  end). No new model call. This shows how much one call's query varies.
- **MU — the three calls merged, no vote.** Each block is the union of the three runs, ordered by the best rank a
  term got in any run, ties by how many runs named it. No new model call.
- **MC — code checks, on MU.** Each term is counted alone and with the other block (the field probe's two counts,
  `workflow/expansion.py`): a term with a zero field count is dropped; a term whose field count is under
  `MIN_FIELD_SHARE` of its own count is dropped as too broad ("channel" is the case to watch). Record every dropped
  term with its counts. Order is otherwise the model's.

If the stored B runs cannot serve (a field missing, an order not recoverable), stop and report before calling a
model. A new prompt is out of scope: `prompt_b.md` already asks for the most central term first and leaves out
compared features and answer words.

## Scoring

Per question and arm: the compiled OpenAlex queries of both rounds, their counts, the verified works in the first
1,000 and 2,000 records of each round and of the two together, and the distinct records read. For sepsis (no ground
truth) the first 25 titles of each round side by side. Also: how many of each arm's terms came from the question and
how many the model proposed, and which terms the fitting cut.

A model-written arm **passes** when, on both labelled questions, its two-round total is at least A13g's (quantum 20,
packet size 4) and its second-round count is not larger than A13g's. Say which arm passed and whether the answer
would change with a different single call (M1–M3 spread).

## Rules

- No product code, method package or contract change; `skill_package_hash` unchanged. Do not start, stop or query the
  service on port 8765 and do not open the product database; throwaway libraries go under the experiment's `work/`.
- A query the vocabulary experiment or the 13g acceptance already read is taken from its raw file, not read again.
- OpenAlex only; polite pacing; stop and report on repeated 429s. The free daily budget ran out on 2026-09-23; say
  how many requests this cost. Expected: 150–250.
- The result says what is measured and what is **ölçülmedi**: three questions, one run each, the weak packet-size
  answer list (6 works, 2 not findable by the question's words), no model call made here (so the prompt's quality is
  inherited from arm B), OpenAlex's order only (not what the model later reads or includes).

## Final message

Per question and arm: the queries, counts and verified-work numbers; which arm passed; the M1–M3 spread; the terms the
code checks dropped and why; the requests spent; a recommendation for the slice that would make the product's query
model-written (what the model is asked, what code checks, what the user sees on the approval card), marked as a
recommendation, not a decision.
