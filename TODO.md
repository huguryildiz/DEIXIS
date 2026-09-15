# TODO

## Memory (deferred, 2026-09-15)

Chat-style "memory" (hidden context learned from past conversations, as in Claude/ChatGPT) is **not** planned.
It would inject context that no StepInput records, which breaks the "every cell points to its source" rule
and the model boundary that keeps instruction files out of model steps.

What it would add: not re-explaining field, language, citation style and preferred providers; continuity
across research ("you already excluded this source").

What it would break: auditability of answers, cross-research leakage of unsourced claims, a new confound
before the P4 evaluation is done.

Auditable alternatives, in order:

- [ ] Keep user preferences as explicit, editable Settings (already there); do not model them as memory.
- [ ] Cross-research continuity from the library, not the model: deterministic hints such as
      "this source was included in research X" computed from the database.
- [ ] If a model-facing note is ever wanted: a user-written, versioned, visible "research brief" field that
      enters the StepInput hash. Name it "brief", not "memory".

## Intent chips / mode tabs (deferred, 2026-09-15)

Chat-style "Ask the agent to…" intent hints and mode tabs ("Deep search / Write report / Organize"), as seen
in agent chat products, are **not** planned.

- Mode tabs: DEIXIS does one thing, a source-grounded answer. Scope (academic / attached / both) and model
  roles already cover the real choices; tabs for modes that do not exist would be empty promises.
- Intent hint: wraps the user's question in a hidden pre-instruction that no StepInput records. Same
  objection as memory above: unaudited context injection. It also assumes a chat loop; DEIXIS is
  question → run → answer.

The real need behind it is the empty-box problem (user does not know what to type). Auditable, cheap answer
if ever wanted, after the P4 evaluation:

- [ ] 2–3 clickable example questions under the question box that only fill the box; nothing is added to
      the model input beyond what the user sees and the StepInput hashes.
