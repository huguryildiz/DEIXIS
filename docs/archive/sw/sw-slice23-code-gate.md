# SW slice 23 — A code gate the user approves: it only closes, only after a check on verified records, and switches off on the first false close found

**Date:** 27 September 2026. **Status:** not built: the owner chose A3 on 2026-09-27 after reading this plan's measurement (D110); the plan stays as the record of that measurement. A1, B1, C1, D1, E1, F1 önerildiği gibi (sahip soru sorulmadan
ilerlenmesini istedi, 2026-09-27). No Sol plan round has run yet: this session was not allowed a model call. **Review
rule (owner, D105):** Sol (`gpt-6-sol` · high) blocks only on a **high** finding; at most **3** plan rounds and **4**
code rounds. Medium and low findings are fixed or left with a reason and open no round; a high finding still open after
the third plan round or the fourth code round goes to the owner. The plan rounds come before the plan is committed.
**Main file:** [sw-status.md](sw-status.md). **Decision:**
the next free number (D108 is the highest at HEAD `d5a78ef`; slice 28's uncommitted D109 is in the working tree, so
this slice takes D109 if slice 28 has not landed and D110 if it has; the implementer checks). **Migration:** `0056`
(highest at HEAD `0055`; slice 28 adds none). **Prerequisite:** slices 16 and 20 closed (row 23 of the main plan);
slice 26 closed (`142dfa1`), whose `protocol_title` the gate respects. Slice 28 may land first; decision 9 says what
changes then. **Type:** build, optional (main plan §23). **Implementer:** Opus · high. **Review:** full (Sol · high,
with the rule above): the slice lets code exclude a work without a model reading, the kind of decision the "Bir tur"
section reviews in full. **Plan:** Opus 5.5 · high. **Scope:** SW15.6, SW16.2–4.

**Measurement:** `.local/archive/sw/sw-slice23-plan-2026-09-27/`: `gate_measure.py` → `gate-measure.json`, `gate-measure.txt`;
`gate_split.py` → `gate-summary.txt`; `closed_titles.py` → `closed-titles.txt`. All read stored libraries with
`immutable=1` URIs: slice 24a's ten `sw` libraries (`.local/archive/sw/sw-slice24-campaign-2026-09-26-134050/data-*-sw-*`) and
slice 27's five (`.local/archive/sw/sw-slice27-remeasure-2026-09-27-043237/data-qtre-sw-*`). The scripts import the product's pure
`criterion_passages.compile_phrases` and `score` at HEAD (slice 28's working-tree changes do not touch that module). No
model call, no provider request, no network. Port 8765 and the live library were not touched. One M1 Pro, Python 3.12
arm64 through `uv`.

**Goal:** SW16 lets a research switch on a code gate only with a rule the user wrote and approved, after that rule
closed nothing it should not have closed on the research's own verified records; the gate is never learned and is off
by default. This slice builds the smallest gate that meets that: one rule shape (a criterion part and a list of literal
phrases; a work whose PDF text holds none of them is closed as `criterion_not_met` with no model call), a check against
the research's verified records with a minimum sample and zero false closes, an approval that freezes a new protocol
revision, a fifth audit stratum for the works the gate closed, and a switch-off that reopens every one of them. With no
rule approved nothing changes, byte for byte.

**What the measurement says first.** On the 15 stored `sw` researches a gate under this plan's conditions could open in
**1**, and there it would close **0** works still waiting to be read. The check needs verified records, and verified
records exist only after reading, so the gate can save calls only in reading runs that come after the approval. Stored
data cannot show how many those are. Building the slice is still what the brief asks for, and SW16.1 already says that a
gate that never opens is a normal outcome; option A3 (do not build) is written out below for the owner.

## Departure from SW15.6 and SW16 as written

SW15.6 and SW16 measured a gate that closes works as **included** (SW1 point 5's strict-cue gate: "26 closed by the code
gate alone" of SW11's context; SW16.3's "closed no in-scope negative"). The brief for this slice is a gate that **never
includes and only closes**, as `criterion_not_met`. The error the check guards against therefore flips: a false close is
a work that meets the criterion and was closed. The SW16 rules keep their form: never learned (SW16.2), the user writes
and approves the rule, zero false closes on verified records not used to write it (SW16.3, decision 4), gate closes in
the audit sample and one false close switches it off (SW16.4). SW16.5 (budget planned without the gate's saving) is
unchanged. Why not an include gate is option A2 below.

## What the code does today

Code read at HEAD `d5a78ef` (slice 26's `142dfa1` plus plan commits); the working tree's slice 28 changes are not
relied on.

- **Every full text goes to two model runs.** `flow._fulltext_adjudication` (`backend/deixis/workflow/flow.py:3563`)
  freezes a plan in `_adjudication_plan` (`:3688-3748`), sends two runs per planned work and closes each pair in
  `_close_adjudication` (`:3815-3871`): `combine` → `with_title` → `_write_adjudication_codes` (`:3873-3896`).
  `_adjudication_plan` already decides one kind of work without a model call: a PDF whose first pages do not confirm the
  work gets `pdf_identity_unconfirmed` in the same transaction as the plan and does not use the read limit (`:3740-3747`).
  That is the place and the pattern for a gate close.
- **Which works a plan reads.** `adjudication.read_plan` (`backend/deixis/workflow/adjudication.py`) takes works with a
  retrieval group, PDF text and no fresh decision of this stage (`FRESH_MODEL_CODES`, `_fresh_model`). A person's
  unread file comes first (slice 18b). A stale decision re-enters.
- **Reason codes live in code.** `backend/deixis/domain/reason_codes.py`; the database checks only stage, outcome and
  decider (`storage/migrations/0038_stage_decisions.sql`), and `('fulltext', 'criterion_not_met', 'code')` is allowed. A
  `criterion_not_met` outcome derives the selection `excluded` (`decisions.SELECTION_STATE`, `decisions.py:25`). D85:
  today only two agreeing `not_met` runs exclude.
- **The protocol.** `protocol_records` (migration `0037`) holds one immutable row per protocol revision, keyed by
  research and scope revision; `store.freeze_protocol` (`store.py:556`) writes a new revision only with a reason and
  returns the stored one for the same body. A later discovery run rebuilds the body from scratch (`flow.py:488-499`,
  reason `later_discovery_run`) and so does the data expansion (`_freeze_expansion`, `:2433`), which carries the
  criterion and the approval over by hand so that no decision goes stale. Staleness reads only
  `decisions.CRITERION_FIELDS` (`inclusion_criterion`, `criterion_parts`, `cue_phrases`; `decisions.py:22`,
  `staleness_key` `:145`). Every decision records the current protocol hash (`decisions.py:44`).
- **Verified records.** `probes.probe_set(ctx)` (`workflow/probes.py:46`) returns the person's confirmed positives
  (queue answer or list edit), the person's negatives (with their kind, `criterion_not_met` or `not_recorded`), and,
  kept apart, the works included by two agreeing runs (`included`). `queue.verified_records` (`queue.py:382`) lists the
  person's decisions. The model's agreeing `criterion_absent` outcomes come from `ctx.outcome`.
- **The audit sample.** `workflow/audit.py`: four strata (`STRATA = ("F1", "F2", "A1", "A2")`, `:31`), three works each
  (`AUDIT_PER_STRATUM`, `:30`), drawn by digest, stateless; F1 and F2 are answered through the audit branch of
  `queue.py`, and `STRATUM_OF_CODE` (`:39`) reads the machine decision an answer closed. The screen is `AuditSample.tsx`,
  shown on the queue screen (`HumanQueue.tsx:391`).
- **No gate exists.** No table, code, route or screen. SW15 point 4's phrases order passages and decide nothing (D84,
  D85).

## Numbers we have

All from the 15 stored libraries on one M1 Pro; the stored readings are `gpt-5.6-luna` · medium (slices 24a and 27). A
stored run is one run. "Verified" below means a model-agreement decision: **no stored library holds a single person
decision** (0 `human_*` rows in all 15), so every validation number here rests on two agreeing model runs, not on a
person.

1. **What exists to validate on** (`gate-summary.txt`). 775 works with PDF text and a full-text code of the reading
   stage: 182 `all_parts_verified` (positives), 44 `criterion_absent` (negatives), 523 queue codes, 26 `not_read_yet`.
   Per research: positives 0 to 42 (q1: 13, 15, 11, 42, 22; medicine 24a: 7, 4, 3, 16, 0; medicine 27: 9, 9, 9, 15, 7),
   negatives 0 to 8. 7 of 15 researches have at least 10 positives, 2 at least 20, 1 at least 30.
2. **A plausible rule, one per criterion part** (`gate-measure.txt`). The candidate for what a user would write is the
   part's own frozen cue phrases (proposed 2 of 3 runs before any record was read, so every record is held out with
   respect to them): "close when none of this part's phrases occurs anywhere in the PDF text". 55 part rules over the
   15 researches (2 to 5 parts each):
   - **19 of 55 close at least one verified include** (83 such closes counted rule by rule). The worst: q1 `detailed`,
     part "mathematical optimization model" with 4 phrases, closes 32 of its 42 includes; "optimization problem" and
     "linear program" were proposed without a part, so the part's list misses the words most includes use. In all 5
     slice 27 researches the comparator part ("unrestricted eating or usual diet comparator") closes 2 to 6 includes.
   - 36 of 55 close no include; only **15 of them close anything at all**.
   - The union "any part has no phrase" closes an include in 9 of 15 researches.
   - A guard of at least 4 text pages changes almost nothing: 8 of 775 texts are shorter (2 of them verified includes,
     both in slice 27 `standard-r2`); it moves one rule's close count by one and no result in number 4.
3. **Choosing a rule after seeing results** (`gate-summary.txt`, split check). In the 7 researches with at least 10
   positives, the verified records were split 50/50, 300 seeded draws each. Where a part rule that closes something
   passed the seen half with zero false closes (2,762 rule-draw pairs), it closed an include of the unseen half in
   **662 (24%)**. SW16's learner result holds for hand-picked phrase lists too: zero errors on 5 to 20 verified includes
   is not zero errors on the next ones.
4. **Opening conditions** (zero false closes on all the research's verified includes, and the rule closes at least one
   verified negative):

   | minimum includes / negatives | researches that could open (of 15) | works waiting to be read it would close |
   |---|---|---|
   | 10 / 1 | 3 | 1 |
   | 10 / 5 | 2 | 0 |
   | **20 / 5 (proposed, C1)** | **1** | **0** |
   | 30 / 5 | 0 | 0 |

   The one: slice 24a `q1-sw-standard-emb-r1`, part "primary model proposal" (8 phrases, "we propose", "problem
   formulation", …): closes 6 of 7 verified negatives and 5 queue works (3 `fulltext_runs_disagree`, 1
   `fulltext_runs_agree_unresolved`, 1 `part_without_evidence`), 0 of 22 includes. With 0 of 22 the exact one-sided 95%
   bound on its false-close share is 12.7%.
5. **What the closing rules close** (`closed-titles.txt`, read from titles by this plan session; one reader, a model,
   not a human check). The medicine intervention-part rules close works whose titles name another intervention
   (bariatric surgery, semaglutide, meal replacement, low-carbohydrate diets) or adipose-tissue biology; those read as
   right closes. The quantum rule of `q1-sw-standard-r1` (part "mathematical optimization model", 9 phrases, 0 of 13
   includes closed) closes 11 works including "A throughput optimal scheduling policy for a quantum switch" and "Multi-
   tree Quantum Routing in Realistic Topologies", whose correctness cannot be told from a title.
6. **Savings.** Each work the gate closes before reading saves two calls (SW16.5 still plans without it). In stored
   data only the 26 `not_read_yet` works were left for a later reading; under C1 the gate closes none of them. The
   saving shows up only in reading runs after the approval (a raised read limit, chained works, a later discovery run),
   which stored data does not contain.

What the numbers cannot show: how many works a gate closes in a research that keeps reading after the approval; whether
a person's rule is better or worse than the part's frozen phrases (no user wrote a rule); the false-close rate of any
rule beyond the 95% bound its sample gives; anything about person-verified records, of which there are none.

## SW items

- **SW15.6** (build): the gate opens per research only with enough verified records of both kinds and a rule that closes
  no work of the forbidden kind on them (here: no verified include), stored with the protocol revision. Closes (next
  free D), in the closing-only form above.
- **SW16.2–4** (build): never learned, user-approved after a zero-false-close check, gate closes audited and one false
  close switches it off. Close (next free D).
- **SW16.1 and 16.5** stay as D85 built them: off by default; budgets without the saving.
- **SW11.9's "the code gate runs at once" on a person's file** is not built (option E1); it stays open.
- **SW13.1's gate row in the probe table** is not built; the gate panel shows the same two numbers (verified includes and
  negatives it closed). It stays open.

## Decisions

1. **One slice, back end and screen, one commit after Sol's review.** No model step, no contract change, no method-file
   change (`skill_package_hash` unchanged). One migration.

2. **The rule (A1, B1).** A rule is a JSON body, schema `deixis.code_gate_rule.v1`:
   `{"schema", "kind": "part_phrases_absent", "part": <criterion part name>, "phrases": [<literal phrase>, …],
   "min_pages": 4}`.
   - `part` must be a part of the research's frozen criterion (`store.frozen_criterion`). A criterion with no parts
     (read as one part named `criterion`, `_adjudication_plan`) accepts `criterion`.
   - `phrases`: 1 to 30 strings from the user, each through `criterion.norm` and `criterion_passages.compile_phrases`
     (literal patterns, never a regular expression; too short or repeated phrases are refused, not silently dropped).
     The screen fills the list with the part's frozen cue phrases as a starting point; the user edits it.
   - `min_pages` is a code constant (`code_gate.MIN_PAGES = 4`), written into the body, not a user field.
   - **Meaning:** the rule closes a work when the PDF text of its read version (`store.page_texts(read)`: the file in
     use at its current extraction) has at least `min_pages` pages and none of the phrases occurs in it
     (`score(text, patterns)[0] == 0` over the pages in page order joined with `"\n"`, NFKC as `score` reads it; this is
     `gate_measure.py`'s test, which reads the same passages as `page_texts`, so the replay can compare byte for
     byte). Nothing else closes: no count threshold, no second condition, no learned value.
   - A pure module `backend/deixis/workflow/code_gate.py`: `validate(rule, criterion) -> rule` (raises a named error),
     `closes(rule, page_texts) -> bool`, `check(rule, records) -> dict`, `upper95(n) -> float` (`1 - 0.05 ** (1 / n)`),
     constants `MIN_POSITIVES = 20`, `MIN_NEGATIVES = 5`, `MAX_FAILED_CHECKS = 3`, `MIN_PAGES = 4`. No clock, no store,
     no randomness; record lists sorted by work id before hashing (SW14.6).

3. **Verified records (C1).** At check time, from one queue context (`queue.context`, `probes.probe_set`):
   - **positives:** the person's confirmed includes (`probe["verified"]`, by queue answer or list edit) and the works two
     agreeing runs included with every quote verified (`probe["included"]`, `all_parts_verified`), each not stale;
   - **negatives:** the person's negatives (`probe["negatives"]`, both kinds) and the works whose current outcome is
     `criterion_absent` by model agreement, not stale.
   - Not verified, never counted: `include_quote_unverified`, every queue code, `protocol_title`, `code_gate_closed`,
     stale decisions, `human_not_sure`, `human_pdf_wrong`, and (if slice 28 has landed) `comparator_exclusion_withheld`.
   - The text a record is checked on is the version its decision was made on; for a person's list edit, which names no
     version, the version the reading would read (`flow._text_version`). A record whose text has fewer than
     `MIN_PAGES` pages is listed as "no text to check" and not counted.
   - The screen shows person and model counts apart ("22 verified includes: 0 by you, 22 by two agreeing readings with
     checked quotes"). Both count toward the minimum; the protocol records the split.

4. **The check (C1, D1).** `POST /api/researches/{id}/code-gate/check` with a rule body.
   - **Refused without evaluating** (422, nothing stored, no attempt used): not an `sw` research; no frozen criterion;
     an invalid rule; fewer than `MIN_POSITIVES` verified positives or `MIN_NEGATIVES` verified negatives (the answer
     says how many exist of each); no checks left.
   - Otherwise the rule is evaluated on every verified record and the result stored (decision 6): positives and
     negatives by origin, **false closes** (each verified include it closes: work, title, code, who decided), verified
     negatives it closes, the one-sided 95% bound when it closes none, and, for information only, how many works
     currently waiting to be read or in the queue it would close. **Passed** means zero false closes and at least one
     verified negative closed.
   - **Held out.** The rule is fixed before its check; the records are every verified record the research has then. A
     check that fails uses one of `MAX_FAILED_CHECKS = 3` per research and criterion digest; a passing check uses none.
     After three failed checks no further check runs until the criterion changes. Every check, failed or passed, stays
     stored with its rule, records and result, and the approval names the attempt it rests on and the failed attempts
     before it. The failed checks show which includes were closed, because a user cannot correct a rule blind; the cap
     and the stored history are what stop tuning against the same records from going unseen (number 3 measured what
     unlimited tuning costs).
   - Nothing else: a check writes no decision and changes no protocol.

5. **Approval (C1).** `POST /api/researches/{id}/code-gate/approve` with the id of a passed check.
   - Refused (409) when the check did not pass, when the criterion digest or the verified-record digest differs from the
     one checked (new verified records arrived; the user checks again, which uses no attempt if it passes), when a gate
     is already on, or when no criterion is frozen.
   - One transaction: an `approved` event (decision 6) and a new protocol revision, reason `code_gate_approved`, whose
     body is the current revision's body with one key added:
     `"code_gate": {"status": "on", "rule_id", "rule", "rule_sha256", "check_id", "check_sha256", "attempt",
     "failed_checks_before", "positives": {"person", "model"}, "negatives": {"person", "model"}}`. Every other key is
     byte-identical, so `CRITERION_FIELDS` and every decision's staleness are untouched; a test checks both.
   - `protocol.build_protocol` gains an optional `code_gate` argument and writes the key only when it is given. The flow
     passes the research's current gate state (`store.code_gate_state`) on every later freeze (`later_discovery_run`,
     `data_expansion`), so a rebuilt body does not drop the gate; a research with no gate row passes `None` and freezes
     the body it froze before.

6. **Storage (migration `0056_code_gate.sql`).** Two append-only tables, immutable like `protocol_records` (no UPDATE;
   DELETE only under `research_purge_authorizations`):
   - `code_gate_checks (id, research_id, scope_revision, criterion_hash, rule_json, rule_sha256, records_sha256,
     result_json, passed CHECK (passed IN (0, 1)), attempt, created_at)`; `attempt` counts failed checks per research and
     criterion digest.
   - `code_gate_events (id, research_id, check_id REFERENCES code_gate_checks(id), kind CHECK (kind IN ('approved',
     'switched_off')), reason, protocol_revision, created_at)`.
   - A gate is **on** for a research when its latest event is `approved` and that check's `criterion_hash` equals the
     current `staleness_key` criterion digest. A changed criterion therefore turns the gate off by itself (the rule was
     checked against another criterion, SW11.10); the screen says so and the user may check a rule again.
   - The purge path of a research deletes both tables' rows with the rest.

7. **Where the gate acts (E1).** Only in `_adjudication_plan`, only when a gate is on, after the identity check, for
   each work the plan would read:
   - skipped (read as today): a work whose read version carries a person's unread file or a user-supplied PDF (E1: the
     person asked for a reading); a work whose read version's title names a study protocol (`adjudication.protocol_title`,
     slice 26: code neither includes nor excludes it); a text shorter than `MIN_PAGES` pages;
   - closed: when `code_gate.closes(rule, store.page_texts(read))`, the version gets `code_gate_closed` with note
     `code_gate:<check_id>:<part>`, written through `_write_adjudication_codes` in the same transaction as the plan, and
     the work is not in `works` and does not use the read limit (the `pdf_identity_unconfirmed` pattern).
   - `ReasonCode("code_gate_closed", "fulltext", "criterion_not_met", "code", "none")` with the comment: the research's
     approved gate rule found none of its phrases in the text; no model read the work; the user approved the rule after a
     check on verified records (slice 23). `adjudication.OWNED_CODES` gains it; `read_plan` treats a fresh
     `code_gate_closed` like a fresh reading code (the work is not read again while it holds), through a second tuple
     `FRESH_GATE_CODES` so `FRESH_MODEL_CODES` keeps its meaning.
   - The plan output gains `"gate_closed": <n>` and the summary `"gate_closed": <n>` **only when a gate is on**; the
     summary's `read` and `unresolved` do not count `code_gate_closed`. A plan made with no gate on is byte-identical.
   - The gate never runs on a work already decided (a fresh decision keeps it out of `read_plan`), never writes over a
     person's decision (`_write_adjudication_codes` already skips it), never includes, and never runs on a research
     without an approved rule or on a `legacy` research.

8. **Audit, reversal and switch-off (F1).**
   - **Audit stratum G1** in `audit.py`: works whose current decision is `code_gate_closed`, drawn like the others
     (`DIGEST_LABEL["G1"] = "G1_not_met_by_code_gate"`, three works), answered through the audit branch
     (`STRATUM_OF_CODE["code_gate_closed"] = "G1"`, `KIND_OF_STRATUM["G1"] = "audit_gate"`, the question as F2's). The
     stratum is present in the audit view only for a research that has ever had a gate approved; every other research's
     audit view is byte-identical.
   - **A false close found by a person switches the gate off.** When a person's include is written on a version whose
     machine decision just before it is `code_gate_closed` (an audit answer `include`, or the person setting that work's
     selection to included in the source list), the same transaction writes a `switched_off` event with reason
     `false_close:<work_id>`. The user can also switch the gate off at any time (`POST …/code-gate/switch-off`, reason
     `user`).
   - **Switching off reopens every gate close.** In the same transaction: a protocol revision, reason
     `code_gate_switched_off`, whose `code_gate` key reads `{"status": "off", "rule_id", "reason", "closed": <n>}`; and
     each version whose current decision is `code_gate_closed` from this rule (never a person's) gets `not_read_yet` with
     note `code_gate_off:<check_id>`, and its selection is derived again (pending). Those works re-enter the next reading
     plan and get two model runs. Nothing is deleted; the superseded rows stay.
   - **Undo.** A person's audit answer is undone as today (the version returns to `code_gate_closed` only if the gate is
     still on; if the answer switched it off, the undo takes back the answer, not the switch-off, and says so). A
     switched-off gate is not switched on again by an undo; the user checks and approves again.
   - Flow counts: a `code_gate_closed` work sits in the `not_met` bucket with its own reason code, which the flow block
     already shows by code (`flow_counts.work_buckets`); no new bucket, so every research without a gate is unchanged.
     The overruling count (`overrides.py`) counts a person's include over a gate close as overruling code, as it
     already does for any code decision.

9. **If slice 28 lands first.** Its comparator marker exists: a rule naming a part with `role: comparator` is refused
   (`comparator_part`), because slice 28 found that the comparator's absence is the reading's least reliable call and
   number 2 shows the comparator part closing includes in all 5 slice 27 researches; `comparator_exclusion_withheld` is
   not a verified record (decision 3). If slice 28 has not landed, the comparator part is not refused by marker (no
   marker exists), and the check will reject a comparator rule that closes an include, as it did in all 5 stored cases.

10. **The screen** (`CodeGate.tsx`, on the queue screen below the audit sample; read `.impeccable.md` first; existing
    components and tokens, no new dependency; Turkish for every string in `i18n.ts`). Collapsed by default. States:
    - **Off.** One sentence: "The code gate is off. Every full text is read twice by the model. Never switching it on is
      normal." The current verified counts against the minimum ("22 of 20 verified includes, 7 of 5 verified not met;
      checks left: 3"). A form: part (select), phrases (one per line, filled from the part's cue phrases), and "Check
      against verified records". Below the minimum the form says what is missing and the button is disabled.
    - **Checked.** The rule in words ("Close a work as 'criterion not met', with no model reading, when none of these
      phrases appears anywhere in its PDF text"); verified includes closed (must be 0; each listed with title, and who
      verified it); verified negatives closed; the bound in words ("With 0 of 22 wrongly closed, the share of includes
      this rule would close could still be as high as 13%, 95% bound"); works it would close now among those waiting to
      be read; attempt number and checks left. "Approve and switch on" only when passed, behind a confirm dialog that
      repeats the rule and says what it does.
    - **On.** The rule, the protocol revision, how many works it closed, the G1 audit note ("three of them are in the
      audit sample; answering 'meets the criterion' switches the gate off"), and "Switch off".
    - **Switched off.** Why (`user`, a false close with the work named, or "the criterion changed"), how many works were
      reopened, and the form again.

11. **API** (`api/app.py`; loopback, CSRF on mutations as every route): `GET /api/researches/{id}/code-gate` (state,
    minimums, verified counts now, checks left, every stored check and event, parts with their cue phrases),
    `POST …/code-gate/check`, `POST …/code-gate/approve`, `POST …/code-gate/switch-off`. The typed client in
    `apps/web/src/api.ts`; labels in `labels.ts`.

12. **Tests** (all SYNTHETIC, no network, no model beyond `FakeAdapter`).
    - `tests/test_code_gate.py` (pure): `validate` refuses an unknown part, an empty or oversized list, a too-short or
      repeated phrase, a comparator part when marked; `closes` true on a text without the phrases and at least 4 pages,
      false with one phrase present, false under 4 pages, plural and case as `score` reads them; `check` counts person
      and model records apart, lists false closes, passes only with 0 false closes and at least one negative closed,
      `upper95(22) = 0.127` to three places, and is independent of record order.
    - `tests/test_code_gate_api.py`: refusals without a stored row (legacy, no criterion, below minimum, invalid rule, no
      checks left); a failed check uses an attempt and a passed one does not; the fourth failed check is refused; approve
      refused on a failed check, on a changed record digest and on a changed criterion; approve writes one protocol
      revision with only `code_gate` added, `CRITERION_FIELDS` equal, and no decision stale; CSRF required.
    - `tests/test_code_gate_flow.py`: with a gate on, a reading plan closes the matching works with `code_gate_closed`
      and its note, sends no model call for them, keeps them out of the read limit, derives `excluded`; skips a person's
      file, a user upload, a protocol-titled version and a short text; never writes over a person's decision; a
      resumed run reuses its stored plan; a later discovery run's protocol keeps `code_gate`; a changed criterion turns the
      gate off and the next plan reads everything; with no gate the plan, summary, protocol body and audit view are
      byte-identical to a run without this slice's code (compare against stored expectations written before the change).
    - `tests/test_audit.py` additions: G1 appears only after an approval; an audit `include` on a G1 work switches the
      gate off, writes the protocol revision and reopens every gate close as `not_read_yet`; undo of that answer; a list
      edit to included on a gate-closed work does the same.
    - `tests/test_protocol_record.py` addition: `build_protocol(..., code_gate=None)` gives the same body and digest as
      before.
    - Playwright `apps/web/e2e/code-gate.spec.ts` (1440 and 390 px, keyboard and focus): below-minimum state; a failing
      check with its listed includes and checks left; a passing check, the confirm dialog, the "on" state; switch-off
      and the reopened count. The fixture server gets the smallest SYNTHETIC scenario behind a question marker
      `[code-gate]` that yields at least 20 verified includes and 5 not met with tiny PDFs (`tests/helpers.py::make_pdf`);
      the minimums are not lowered for the fixture.
    - Every existing test passes unchanged; no expected value in an existing test is edited.

13. **Acceptance** (scripts and outputs under `.local/sw-slice23-acceptance-<YYYY-MM-DD>/`).
    1. Full pytest (the known single failure apart:
       `tests/test_documents.py::test_extraction_is_stopped_when_it_exceeds_the_memory_limit`), `npm run build`,
       `npm run lint` (warnings not above 17), the full Playwright suite, `git diff --check`; highest migration `0056`;
       `uv.lock` unchanged; `skill_package_hash` unchanged.
    2. **Replay (a), default unchanged.** Slice 26's reading replay (`.local/archive/sw/sw-slice26-plan-2026-09-27/replay_reading.py`
       logic, product functions) still reproduces 455 of 455 stored codes on slice 24a, and the same recomputation on
       slice 27's five `sw` libraries reproduces every stored reading code (the slice 28 plan counted 294); no product
       function this replay calls changed behaviour.
    3. **Replay (b), the product's evaluator equals the plan's prototype.** For the 15 libraries, the product's
       `code_gate.closes` and `code_gate.check` (with decision 3's record selection, which equals the prototype's on
       these libraries because none holds a person decision or a stale current decision; the script asserts both) on
       each part's frozen cue phrases reproduce `gate-measure.json`'s `|pages>=4` entries rule by rule (closes by group
       and false closes, 55 part rules; records under 4 pages not counted, `gate-summary.txt`'s last table) and the
       opening table of number 4: exactly 1 of 15 passes under C1, `q1-sw-standard-emb-r1`'s
       "primary model proposal", 6 negatives and 5 queue works closed, 0 of 22 includes, bound 0.127.
    4. **Replay (c), the routes on a copy.** On a copy of `data-q1-sw-standard-emb-r1` in its own directory (migrations
       applied by the product on open; `create_app(..., start_worker=False)`), `check` on that rule passes at attempt 1;
       `approve` writes protocol revision 3 with reason `code_gate_approved`, the criterion digest equals revision 2's,
       0 decisions become stale, no decision is written; `switch-off` writes revision 4 and reopens 0 works (none was
       closed: no reading ran). On the same copy, `check` on the part "explicit optimization formulation" fails with 3
       false closes and leaves 2 checks.
    5. No live model call: the gate makes none, and every behaviour above is code over stored text and decisions.

14. **Documents.** The decision (next free number) at the top of `docs/decisions.md`: decision, the replay numbers,
    Limits (decision below). In `docs/archive/search-2026-09/search-workflow-review-2026-09-18.md`: SW15's and SW16's status lines
    ("points 6 / 2–4 implemented in slice 23 (Dnnn), as a gate that only closes"), SW11's point 9 note (the gate does not
    run on a person's file). Row 23 of `sw-status.md`: `uygulandı, inceleme bekliyor` with the headline numbers.
    Nothing else in `sw-status.md`.

## Frozen expectations

Written before any code. One machine; the numbers are stored model readings, not person checks.

- Replay (a): 455 of 455 on slice 24a; every slice 27 reading code reproduced. Any change is a regression.
- Replay (b): exactly `gate-measure.json` and the opening table; measured, so any other result means the product's
  evaluator or record selection differs from the prototype.
- Replay (c): passes at attempt 1, revision 3, criterion digest unchanged, 0 stale; the second rule fails with 3 false
  closes.
- In use: on stored data the gate opens in 1 of 15 researches and closes nothing still waiting to be read. The slice's
  value is the guarded mechanism, not a measured saving.

## Owner choices (27 September 2026: A1, B1, C1, D1, E1, F1 önerildiği gibi)

Sahip soru sorulmadan ilerlenmesini istedi; every proposed option is taken. The alternatives stay for the record. None
needs the owner's money or hands.

- **A — What the gate does.** Proposed **A1**: it only closes, as `criterion_not_met`, never includes (the brief;
  decision 2). *A2*: an include gate as SW1 point 5 and SW16's measurement describe it; an include would enter the
  answer on a phrase count without a verified quote per part (SW11.1), and slice 24a/27 found serious errors even in
  two agreeing readings with verified quotes (D105, D108). *A3*: do not build; record in a decision that SW16's gate
  stays off because on stored data it could open in 1 of 15 researches and would close 0 works still to be read.
- **B — The rule's form.** Proposed **B1**: one part and literal phrases, closed when none occurs in the whole text,
  with a fixed 4-page guard. *B2*: SW16's learner family (counts, two conditions); SW16 showed its selections fail
  held-out records in 57–93% of draws. *B3*: let the gate also close works already in the queue; relieves the person
  (the C1 rule would close 5 queue works) but overrules a model reading that asked for a person, beyond SW16.
- **C — Verified records and the minimum.** Proposed **C1**: person decisions plus two-run agreements with verified
  quotes (positives) and agreeing `criterion_absent` (negatives), shown apart; at least 20 positives and 5 negatives, 0
  false closes, at least one negative closed (1 of 15 stored researches could open). *C2*: person decisions only; no
  stored research has one, so the gate would not open until people answer at least 25 queue or audit rows. *C3*: at
  least 30 positives (0 of 15 could open; bound 9.5%). *C4*: at least 10 positives (2 to 3 of 15; bound up to 26%).
- **D — Keeping the check held out.** Proposed **D1**: all verified records at check time, the rule fixed before its
  check, at most 3 failed checks per criterion, every check stored and named by the approval, a check below the minimum
  refused without evaluating. *D2*: only records verified after the rule was written count (clean, but in stored data no
  research reads enough after the fact to open). *D3*: a fixed hash split into a visible half and a held-out half;
  halves the sample, and number 3 shows a visible half does not predict the other.
- **E — A person's file.** Proposed **E1**: the gate never closes a person's file or a user-supplied PDF; a person who
  adds a file asked for a reading (departs from SW11.9's "the code gate runs at once"). *E2*: as SW11.9; touches slice
  18b's request states (`person_reading.mark_read`) and closes a file the person just gave by a phrase list.
- **F — Switch-off.** Proposed **F1**: a person's include over a gate close (audit or list) or the user's switch turns
  the gate off, freezes a revision and reopens every gate close as `not_read_yet`. *F2*: off, but closed works stay
  closed until a person looks; a false close found once would leave its siblings excluded.

## What the owner does

Nothing is a question. No model quota is used.

## Global constraints

- **With no rule approved, behaviour is byte-identical:** reading plans, summaries, decisions, protocol bodies and
  digests, the audit view, flow counts and every existing test's expectations.
- **The gate never includes,** never writes over a person's decision, never acts on a work already decided, never runs
  on a research without an approved rule, on a `legacy` research, on a person's file, a user upload or a protocol-titled
  version.
- **Evidence contract.** A gate close says what it is: code found none of the approved phrases; no model read the work.
  Every close carries the check it rests on (note and protocol hash) and can be reopened.
- **Every number** with its sample size; stored readings are model readings; the 95% bound is the only error statement
  a check makes.
- **Port 8765 and the live library are off limits.** No model call, no provider request.
- **The owner's files** (`TODO.md`, `.vscode/`, `scripts/local_index.py`) are not changed or staged. Slice 28's
  uncommitted files are not touched, reverted or staged; rows other than 23 of `sw-status.md` are not touched.

## Task outline

1. Row 23 `uygulanıyor`.
2. Migration `0056_code_gate.sql`; store methods (`code_gate_state`, check and event writes, purge).
3. `workflow/code_gate.py` (decisions 2–4) and `tests/test_code_gate.py`.
4. Reason code, `adjudication` tuples, `_adjudication_plan`, `_adjudication_summary` (decision 7).
5. `build_protocol(code_gate=)` and the flow's freezes (decision 5).
6. Audit stratum G1, switch-off and reopen (decision 8).
7. API routes (decision 11) and their tests.
8. Screen `CodeGate.tsx`, `api.ts`, `labels.ts`, `i18n.ts`; Playwright scenario and spec.
9. Acceptance (decision 13): checks and the three replays.
10. Documents (decision 14); row 23 `uygulandı, inceleme bekliyor`.

## Acceptance conditions

Decision 13's five items; full pytest (known single failure apart), build, lint ≤ 17 warnings, Playwright, `git diff
--check`; highest migration `0056`; `uv.lock` and `skill_package_hash` unchanged; replay (a) unchanged, (b) equal to the
plan's measurement, (c) as frozen.

## Not in this slice

- An include gate (A2), count or two-condition rules (B2), closing queue rows (B3).
- The gate on a person's file (E2, SW11.9's remainder); SW13.1's gate row in the probe table.
- A frozen audit cohort (slice 20's open requirement); an audit sample larger than three per stratum.
- Any change to the reading's method, contract, budget or page selection; `legacy`.
- Re-running any stored research.

## Not measured

How many works a gate closes in a research that keeps reading after approval (the only place it saves calls); whether
rules people write differ from the frozen phrases this plan used as a stand-in; any person-verified record (there are
none stored); the false-close share of an approved rule beyond its 95% bound; whether three works in G1 find a false
close before it matters; the screen's clarity to a user; fields other than quantum and medicine.

## Limits for the decision

One rule family, measured on two questions (quantum, medicine) in 15 stored researches with model-verified records only;
a gate opened under C1 in one of them. Zero false closes on 20 or more includes bounds the false-close share at about 14%
or less at 95%, it does not show it is zero. The held-out rule is a cap on failed checks, not a sealed test set. The
gate's saving is unmeasured.
