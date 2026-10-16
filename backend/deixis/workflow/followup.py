"""Follow-up questions answered from this research's stored passages (UI parity S22a, F17).

A person asks a question inside a research; one `followup_answer` run answers it. No search is started: the run reads
only passages this research already holds, ranks them against the turn's question with the inspection ranking
(lexical and semantic, fused by RRF), and sends the best of them in one model call with its one schema repair. The
StepInput's allowlist is the passages that call was sent, so a citation can only name one of them, with an anchor the
backend locates in its text (the grounded answer's rules). The answer is published with its turn row in one
transaction. "Search for new works on this" is not here: it is a new scope revision the person asks for with the
turn's question, through the existing scope-revision route.

Which passages a research holds for a follow-up (its pool):
- `answer_input`: the latest answer of the turn's question revision froze its evidence (D253): each work's abstract
  and, for a work read in full, the pages of the file it was read from. A work the person has excluded or marked not
  sure since then gives nothing, and one whose file the person marked wrong gives its abstract only. A work whose full
  text was read and included after that answer's run started adds its abstract and pages too (D49): a follow-up reads
  the research as it has grown, not only as the answer saw it.
- `included_works`: otherwise (an answer over attached files, or none yet), the text of each included work's
  answer version (D48), as the attached-file answer reads it.
Only passages still current are used: an active source of the research and the extraction of the file in use.
"""

from __future__ import annotations

import json
import re
from typing import Any

from deixis.domain import contracts
from deixis.documents.jats import RENDITION_SQL
from deixis.domain.rules import TEST_EFFORT_BUDGETS, RevisionConflict, check_expected_version
from deixis.storage.db import dumps, new_id, now, transaction
from deixis.workflow import fast_answer, small_batch
from deixis.workflow.decisions import DecisionStore
from deixis.workflow.evidence_deps import EVIDENCE_STATUS_SQL
from deixis.workflow.late_revision import REVISION_INPUT

TASK = "followup_answer"
POOL_KEY = "followup:pool"
SEMANTIC_KEY = "followup_semantic"
SELECTION_KEY = "followup:passages"
CONVERSATION_KEY = "followup:conversation"
CALLS = 4  # two rounds (D50), each a call and its one schema repair; the turn's own budget, apart from the research's runs
MAX_QUESTION_CHARS = 2000
PUBLISHED = ("answered", "partly_answered", "not_answered")
MAX_TERMS = 40
MAX_EARLIER_TURNS = 3  # the published turns before this one that the model reads as conversation context
MAX_CONTEXT_CLAIMS = 12  # claim texts kept from the latest answer and from each earlier turn
MAX_TABLE_VALUES = 60  # evidence-table values the model reads as context (D50)
MAX_MORE_QUERIES = 3  # search phrases one follow-up may ask the library with (D50)
MORE_KEY = "followup_answer:more"
MORE_SELECTION_KEY = "followup:more_passages"
MORE_SEMANTIC_KEY = "followup_more_semantic"
# Why a follow-up stops unpublished when what its pool was frozen from changed (the run fails; the person asks again).
SELECTION_CHANGED = "followup_selection_changed"
SOURCES_CHANGED = "followup_sources_changed"
LANGUAGE_TAG = re.compile(r"[a-z]{2,3}(-[A-Za-z0-9]{2,8})*")  # common.schema.json#/$defs/language_tag


class FollowupRefused(Exception):
    """A follow-up request that cannot be queued as asked (an empty or too long question, a reused key)."""


def _clean(question: str) -> str:
    return " ".join(question.split())


def request_turn(store: Any, research_id: str, question: str, expected_scope_revision: int,
                 idempotency_key: str | None) -> dict[str, Any]:
    """Queue one follow-up: the turn row and its run in one transaction. The research's one-active-run rule holds."""
    text = _clean(question)
    if not text:
        raise FollowupRefused("Type a follow-up question first")
    if len(text) > MAX_QUESTION_CHARS:
        raise FollowupRefused(f"A follow-up question has at most {MAX_QUESTION_CHARS} characters")
    key = f"followup:{research_id}:{idempotency_key}" if idempotency_key else None
    with transaction(store.conn):
        research = store.research(research_id)
        if key:
            replayed = store.conn.execute("SELECT id, kind FROM runs WHERE idempotency_key = ?", (key,)).fetchone()
            if replayed:
                turn = store.conn.execute("SELECT * FROM followup_turns WHERE run_id = ?", (replayed["id"],)).fetchone()
                if replayed["kind"] != TASK or turn is None or turn["question"] != text:
                    raise RevisionConflict("This idempotency key was used for another request")
                return dict(turn)
        check_expected_version(expected_scope_revision, research["current_scope_revision"])
        scope = store.scope(research_id, research["current_scope_revision"])
        turn_id = new_id("fut")
        # The passage limit is the research's answer limit, frozen with the run as every budget is.
        budget = {"max_model_calls": CALLS, "max_provider_requests": 0,
                  "max_followup_passages": TEST_EFFORT_BUDGETS[scope["effort"]].max_answer_passages}
        run = store.create_run(research_id, TASK, budget, key, target={"turn_id": turn_id, "question": text})
        store.conn.execute(
            "INSERT INTO followup_turns (id, research_id, scope_revision, question, run_id, status, created_at)"
            " VALUES (?, ?, ?, ?, ?, 'pending', ?)",
            (turn_id, research_id, run["scope_revision"], text, run["id"], now()))
        store._event(research_id, "followup_asked", {"turn_id": turn_id}, run["id"])
        return dict(store.conn.execute("SELECT * FROM followup_turns WHERE id = ?", (turn_id,)).fetchone())


def turn_for_run(store: Any, run_id: str) -> dict[str, Any] | None:
    row = store.conn.execute("SELECT * FROM followup_turns WHERE run_id = ?", (run_id,)).fetchone()
    return dict(row) if row else None


def terms(question: str) -> list[str]:
    """The question's words the lexical ranking matches, by the rule the answer's topic terms use for its question."""
    from deixis.workflow.flow import STOPWORDS
    words = [t for t in re.findall(r"\w+", question.lower()) if len(t) > 2 and t not in STOPWORDS]
    return list(dict.fromkeys(words))[:MAX_TERMS]


def _answer_input(store: Any, research_id: str, scope_revision: int) -> dict[str, Any] | None:
    row = store.conn.execute(
        "SELECT s.run_id, s.output_json FROM run_steps s JOIN runs r ON r.id = s.run_id"
        " WHERE r.research_id = ? AND r.kind = 'answer' AND r.scope_revision = ? AND s.status = 'succeeded'"
        " AND s.operation_key IN (?, ?) ORDER BY r.created_at DESC, s.rowid DESC LIMIT 1",
        (research_id, scope_revision, fast_answer.INPUT, REVISION_INPUT)).fetchone()
    return {"run_id": row["run_id"], "plan": json.loads(row["output_json"])} if row else None


def _person_states(store: Any, research_id: str) -> tuple[dict[str, str], dict[str, str]]:
    """Every choice the person made: their selection of a version in any state, `pending` included, and the state
    their latest queue decision on a work stands for (`fast_answer.human_choice`)."""
    selections = {r["source_version_id"]: r["state"] for r in store.conn.execute(
        "SELECT source_version_id, state FROM selections WHERE research_id = ? AND origin = 'user'", (research_id,))}
    _, humans = fast_answer.user_choices(store, research_id)
    return selections, {work_id: choice["state"] for work_id, choice in humans.items()}


def _current(store: Any, research_id: str) -> dict[str, list[str]]:
    """Passage ids a model step may read now, by active source: the abstract, and pages of the file in use from its
    current extraction (`fast_answer.current_pools`)."""
    return {svid: [p["id"] for p in rows] for svid, rows in fast_answer.current_pools(store, research_id).items()}


def pool(store: Any, research_id: str, scope_revision: int, flow: Any = None) -> dict[str, Any]:
    """The passages this research holds for a follow-up, by source in order (see the module text), frozen with the
    selection state it was read under: what `changed` compares at the send, at a resume and at publication. `flow`
    checks that a full text read after the answer was read on the file still in use; without it none is added."""
    current = _current(store, research_id)
    sources: dict[str, list[str]] = {}
    base = {"selection_revision": store.selection_revision(research_id),
            "user_signature": small_batch.user_signature(store, research_id)}
    frozen = _answer_input(store, research_id, scope_revision)
    if frozen is not None:
        selections, humans = _person_states(store, research_id)
        # The person's choice is read on the work's head now, not the head the answer froze: a version published
        # since heads the work, and excluding or setting it pending takes the work's frozen passages out too.
        heads = store.work_heads(research_id)
        for item in frozen["plan"]["items"]:
            svid = item["source_version_id"]
            head = heads.get(item["work_id"], item.get("head"))
            state = selections.get(head) or humans.get(item["work_id"])
            if state in ("excluded", "pending"):
                continue
            ids = list(item["abstract_ids"])
            if item["route"] == "fulltext" and state != "pdf_wrong":
                ids += item["fulltext_ids"]
            have = set(current.get(svid, []))
            kept = [pid for pid in dict.fromkeys(ids) if pid in have and pid not in sources.get(svid, [])]
            if kept:
                sources.setdefault(svid, []).extend(kept)
        # The research kept growing after that answer (D49): a work whose full text was read since the answer's run
        # started gives its abstract and the pages it was read from, the rule the answer view counts its "new full
        # texts" by (`fulltext_read_since`). The read must be on the file still in use (`fast_answer.read_file`), so
        # a replaced or re-extracted file gives nothing unread; a read that found the criterion not met counts only
        # when the person included the work, as in the answer (`fast_answer.apply_user`).
        if flow is not None:
            records, pools = fast_answer.reading_records(store, research_id), fast_answer.current_pools(store, research_id)
            for row in store.conn.execute(
                    "SELECT d.*, v.work_id FROM stage_decisions d JOIN runs r ON r.id = ?"
                    " JOIN source_versions v ON v.id = d.source_version_id WHERE d.research_id = r.research_id"
                    " AND d.stage = 'fulltext' AND d.decided_by IN ('model_agreement', 'human')"
                    " AND d.outcome IN ('include', 'criterion_not_met') AND d.superseded_at IS NULL"
                    " AND d.created_at > r.created_at ORDER BY d.created_at, d.rowid", (frozen["run_id"],)):
                svid = row["source_version_id"]
                state = selections.get(heads.get(row["work_id"], svid)) or humans.get(row["work_id"])
                if state in ("excluded", "pending", "pdf_wrong") or (row["outcome"] != "include" and state != "included"):
                    continue
                asset = fast_answer.read_file(flow, dict(row), svid, records)
                if not asset and row["decided_by"] == "human":
                    # A person's queue decision carries no reading of its own: the latest current reading before it
                    # gives the file, as in the answer (`fast_answer.cutoff_snapshot`).
                    decisions = DecisionStore(store)
                    for previous in reversed(records["history"].get(svid, [])):
                        if previous["stage"] == "fulltext" and not decisions.is_stale(previous):
                            if asset := fast_answer.read_file(flow, previous, svid, records):
                                break
                if not asset:
                    continue
                read = [p["id"] for p in pools.get(svid, [])
                        if p["kind"] == "abstract" or p["asset_id"] == asset]
                kept = [pid for pid in read if pid not in sources.get(svid, [])]
                if kept:
                    sources.setdefault(svid, []).extend(kept)
        return _with_reserve(store, research_id, current, base | {
            "basis": "answer_input", "answer_run_id": frozen["run_id"], "sources": sources})
    return _with_reserve(store, research_id, current, base | {
        "basis": "included_works", "answer_run_id": None, "sources": _included(store, research_id, current)})


def _included(store: Any, research_id: str, current: dict[str, list[str]]) -> dict[str, list[str]]:
    """Each included work's current passages from the version an answer reads (D48), in the research's order."""
    sources: dict[str, list[str]] = {}
    for head in store.included_works(research_id):
        svid = store.answer_version(research_id, head)
        if svid is not None and current.get(svid):
            sources[svid] = list(current[svid])
    return sources


def _with_reserve(store: Any, research_id: str, current: dict[str, list[str]], frozen: dict[str, Any]) -> dict[str, Any]:
    """The pool with its reserve and its priority passages (D50). The reserve is the rest of the library this research
    holds: every included work's current passages the pool does not already give, which a second round reads when
    the model asks for more. Priority passages are the ones the research's latest answer and its evidence table's
    current values cite; they go first in the selection, so the follow-up starts from what the answer and the table
    stand on."""
    given = {pid for ids in frozen["sources"].values() for pid in ids}
    reserve = {}
    for svid, ids in _included(store, research_id, current).items():
        rest = [pid for pid in ids if pid not in given]
        if rest:
            reserve[svid] = rest
    if not frozen["sources"] and reserve:
        # The answer's evidence left the research (excluded since, say) while other included works hold text: those
        # are the pool, not a reason to answer that there is nothing to read.
        frozen, reserve = frozen | {"sources": reserve}, {}
    held = given | {pid for ids in reserve.values() for pid in ids} | {
        pid for ids in frozen["sources"].values() for pid in ids}
    cited = [r[0] for r in store.conn.execute(
        "SELECT l.passage_id FROM evidence_links l JOIN claims c ON c.id = l.claim_id WHERE c.answer_id ="
        " (SELECT id FROM answers WHERE research_id = ? AND status = 'structurally_valid'"
        "  ORDER BY created_at DESC, rowid DESC LIMIT 1) ORDER BY c.ordinal, l.rowid", (research_id,))]
    cited += [row["passage_id"] for row in _table_values(store, research_id) if row["passage_id"]]
    return frozen | {"reserve": reserve, "priority": [pid for pid in dict.fromkeys(cited) if pid in held]}


def _table_values(store: Any, research_id: str) -> list[dict[str, Any]]:
    """The current values of this research's evidence tables, one row per value and cited passage (or one with no
    passage), in table, row and column order: a trashed table, a removed row or column and a cell without a value
    give nothing."""
    return [dict(r) for r in store.conn.execute(
        "SELECT t.id AS table_id, c.id AS cell_id, c.source_version_id, v.title, v.year, cr.name AS column_name, cr.options_json, r.value_json,"
        " l.passage_id FROM evidence_cells c"
        " JOIN evidence_tables t ON t.id = c.table_id AND t.research_id = ? AND t.trashed_at IS NULL"
        " JOIN table_columns col ON col.id = c.column_id AND col.removed_at IS NULL"
        " JOIN column_revisions cr ON cr.column_id = col.id AND cr.revision = col.current_revision"
        " JOIN table_rows tr ON tr.table_id = c.table_id AND tr.source_version_id = c.source_version_id"
        "  AND tr.removed_at IS NULL"
        " JOIN cell_revisions r ON r.id = c.current_revision_id AND r.state = 'value'"
        " JOIN source_versions v ON v.id = c.source_version_id"
        " LEFT JOIN cell_evidence_links l ON l.cell_revision_id = r.id"
        " ORDER BY t.created_at, tr.created_at, col.position, l.rowid", (research_id,))]


def changed(store: Any, research_id: str, frozen_pool: dict[str, Any]) -> str | None:
    """Why the frozen pool no longer describes the research, or None. A person's selection or queue decision changed
    since (any state, `pending` included), or a pooled passage is no longer current: its source left the research,
    or its file was removed, replaced or extracted again."""
    if (store.selection_revision(research_id) != frozen_pool["selection_revision"]
            or small_batch.user_signature(store, research_id) != frozen_pool["user_signature"]):
        return SELECTION_CHANGED
    current = _current(store, research_id)
    for part in ("sources", "reserve"):
        for svid, ids in frozen_pool.get(part, {}).items():
            if not set(ids) <= set(current.get(svid, [])):
                return SOURCES_CHANGED
    return None


def _guard(flow: Any, run: dict[str, Any], frozen_pool: dict[str, Any]) -> None:
    # The send gate is the last look before each call, the repair's included: a pause, a cancel or a newer question
    # revision that arrived while the connection was checked or the first output came back stops the call unsent.
    flow._checkpoint(run["id"], run["scope_revision"])
    if reason := changed(flow.store, run["research_id"], frozen_pool):
        flow._fail(run["id"], reason, {"note": "Ask the follow-up again to answer it from the research as it is now."})


def _code_step(flow: Any, run: dict[str, Any], key: str, kind: str, build: Any) -> dict[str, Any]:
    """A frozen code step: a resumed run reads what the first execution stored and computes nothing again."""
    step = flow.store.step(run["id"], key, kind)
    if step["status"] == "succeeded":
        return step["output"]
    with transaction(flow.store.conn):
        output = build()
        flow.store.start_step(step["id"])
        flow.store.finish_step(step["id"], "succeeded", output=output)
    return output


def conversation(store: Any, research_id: str, question: str, turn: dict[str, Any]) -> dict[str, Any]:
    """What the conversation so far says, so the model reads the follow-up in its context (D49): the research question,
    the claim texts of the research's latest valid answer, and the last published turns asked before this one. It is
    context, never evidence: the texts carry no passage, and a claim may cite only the passages of this StepInput."""
    answer = store.conn.execute(
        "SELECT id FROM answers WHERE research_id = ? AND status = 'structurally_valid'"
        " ORDER BY created_at DESC, rowid DESC LIMIT 1", (research_id,)).fetchone()
    latest = [r["text"] for r in store.conn.execute(
        "SELECT text FROM claims WHERE answer_id = ? ORDER BY ordinal LIMIT ?",
        (answer["id"], MAX_CONTEXT_CLAIMS))] if answer else []
    rows = store.conn.execute(
        f"SELECT question, draft_json FROM followup_turns WHERE research_id = ? AND id != ? AND created_at <= ?"
        f" AND status IN ({', '.join('?' * len(PUBLISHED))}) ORDER BY created_at DESC, rowid DESC LIMIT ?",
        (research_id, turn["id"], turn["created_at"], *PUBLISHED, MAX_EARLIER_TURNS)).fetchall()
    earlier = []
    for row in reversed(rows):
        draft = json.loads(row["draft_json"] or "{}")
        claims = [c["text"] for c in draft.get("claims", []) if isinstance(c, dict) and isinstance(c.get("text"), str)]
        earlier.append({"question": row["question"], "answer": claims[:MAX_CONTEXT_CLAIMS]})
    values: dict[str, dict[str, str]] = {}
    for row in _table_values(store, research_id):
        key = row["cell_id"]  # one value per cell: a row per cited passage, tables with the same column names apart
        if key not in values and len(values) < MAX_TABLE_VALUES:
            work = f"{row['title']} ({row['year']})" if row["year"] else row["title"]
            values[key] = {"work": work, "column": row["column_name"],
                           "value": _value_text(json.loads(row["value_json"]), row["options_json"])}
    return {"research_question": question, "latest_answer": latest, "earlier_turns": earlier,
            "evidence_table": list(values.values())}


def _value_text(value: Any, options_json: str | None) -> str:
    """One evidence-table value as the table shows it: option labels, a number as stated, yes or no, or the text."""
    if "option_ids" in value:
        labels = {o["id"]: o["label"] for o in json.loads(options_json or "[]")}
        return ", ".join(labels.get(i, i) for i in value["option_ids"])
    if "number" in value:
        return value.get("as_stated") or " ".join(str(v) for v in (value["number"], value.get("unit")) if v is not None)
    return value.get("answer") or value.get("text") or json.dumps(value, ensure_ascii=False)


async def _selection(flow: Any, run: dict[str, Any], scope: dict[str, Any], question: str,
                     frozen_pool: dict[str, Any]) -> dict[str, Any]:
    """The passages sent: the pool ranked against the question read with the research question (lexical and semantic,
    fused by RRF), then the rest of the pool breadth-first by source, under a per-source cap, up to the research's
    answer passage limit. A follow-up such as "write a report from the full texts" names no topic of its own, so the
    research question gives the ranking one (D49): it is part of the semantic query, and its words rank the pool
    lexically only when the follow-up's own words match nothing and no semantic ranking came back. A specific
    follow-up in another language than the passages is then not outranked by the research question's words."""
    saved = flow.store.existing_step(run["id"], SELECTION_KEY)
    if saved and saved["status"] == "succeeded":
        return saved["output"]
    from deixis.workflow.flow import MAX_PASSAGES_PER_SOURCE, _reference_list, fuse_rankings
    store, limit = flow.store, run["budget"]["max_followup_passages"]
    sources = frozen_pool["sources"]
    svids = list(sources)
    ids = {pid for pid_list in sources.values() for pid in pid_list}
    everything = sum(len(store.passages_for(svid)) for svid in svids)

    def matches(words: list[str]) -> list[dict[str, Any]]:
        fts = " OR ".join(f'"{t}"' for t in words)
        return [p for p in store.search_passages(svids, fts, max(everything, 1)) if p["id"] in ids] if words else []
    words = terms(question)
    lexical = matches(words)
    semantic = await flow._semantic_ranking(run, scope, svids, query_text=f"{question}\n{scope['question']}",
                                            key=SEMANTIC_KEY, query_origin="followup", only=ids)
    semantic = [p for p in semantic or [] if p["id"] in ids]
    if not lexical and not semantic:
        # Neither ranking has a topic: the research question's words rank the pool, not the fill's source order.
        words = terms(scope["question"])
        lexical = matches(words)
    ranked = fuse_rankings(lexical, semantic) if semantic else lexical
    # A reference-list passage goes to the end: a misread one is ranked lower, not lost.
    ranked = sorted(ranked, key=lambda p: _reference_list(p["text"]))
    ranked_ids = [p["id"] for p in ranked]
    # The passages no ranking matched, breadth-first: each source's first passage (its abstract when it has one),
    # then each source's second, and so on. A question in another language than the passages matches no word, and
    # the model, not the word match, says whether the passages answer it.
    # The passages the latest answer and the evidence table cite go first, up to half the limit (D50).
    # A table value may cite a passage of the reserve; it is read in this round too.
    ranked_ids = frozen_pool.get("priority", [])[:limit // 2] + ranked_ids
    seen, fill = set(ranked_ids), []
    for depth in range(max((len(v) for v in sources.values()), default=0)):
        fill += [sources[svid][depth] for svid in svids if depth < len(sources[svid]) and sources[svid][depth] not in seen]
    per_source = max(MAX_PASSAGES_PER_SOURCE, limit // max(1, len(svids)))
    owner = {pid: svid for part in (sources, frozen_pool.get("reserve", {})) for svid, pid_list in part.items()
             for pid in pid_list}
    taken: dict[str, int] = {}
    chosen: list[str] = []
    for pid in ranked_ids + fill:
        if len(chosen) >= limit:
            break
        if pid not in chosen and taken.get(owner[pid], 0) < per_source:
            chosen.append(pid)
            taken[owner[pid]] = taken.get(owner[pid], 0) + 1
    from_ranking = len(set(chosen) & seen)
    semantic_step = store.existing_step(run["id"], SEMANTIC_KEY)
    output = {"basis": frozen_pool["basis"], "answer_run_id": frozen_pool["answer_run_id"],
              "pool_size": len(ids), "pool_sources": len(svids), "terms": words, "lexical_matches": len(lexical),
              "semantic_matches": len(semantic), "semantic_step": semantic_step["status"] if semantic_step else None,
              "limit": limit, "per_source": per_source, "passage_ids": chosen,
              "from_ranking": from_ranking, "from_fill": len(chosen) - from_ranking,
              "from_priority": len(set(chosen) & set(frozen_pool.get("priority", [])))}
    return _code_step(flow, run, SELECTION_KEY, "code:followup_passages", lambda: output)


async def _call(flow: Any, run: dict[str, Any], scope: dict[str, Any], key: str, passages: list[dict[str, Any]],
                context: dict[str, Any], frozen_pool: dict[str, Any], budget_short: str = "pause") -> dict[str, Any]:
    """One round's model call over these passages, with the conversation as context. The send gate runs right before
    each call is built and sent, the repair's included. The second round skips (returns invalid) rather than pausing
    when transport retries spent the turn's calls, so the first round's valid answer is published."""
    from deixis.workflow.flow import step_model
    source_ids = list(dict.fromkeys(p["source_version_id"] for p in passages))

    def step_input(step_id: str) -> dict[str, Any]:
        return flow._step_input(run, scope, step_id, TASK, [], source_ids, passages, [], step_model(scope, TASK)) | {
            "conversation": context}
    return await flow._model_step(run, scope, key, TASK, source_ids=source_ids, passage_rows=passages,
                                  send_gate=lambda: _guard(flow, run, frozen_pool), step_input_builder=step_input,
                                  budget_short=budget_short)


async def _more_selection(flow: Any, run: dict[str, Any], scope: dict[str, Any], queries: list[str],
                          first: dict[str, Any], frozen_pool: dict[str, Any]) -> dict[str, Any]:
    """The second round's passages (D50): the model's phrases rank the pool and its reserve (lexical and semantic,
    fused by RRF); up to half the limit of passages the first round did not send take the place of the first round's
    last ones. A phrase that matches nothing new leaves the first round's passages as they were."""
    saved = flow.store.existing_step(run["id"], MORE_SELECTION_KEY)
    if saved and saved["status"] == "succeeded":
        return saved["output"]
    from deixis.workflow.flow import _reference_list, fuse_rankings
    store, limit = flow.store, run["budget"]["max_followup_passages"]
    held: dict[str, list[str]] = {}
    for part in ("sources", "reserve"):
        for svid, ids in frozen_pool.get(part, {}).items():
            held.setdefault(svid, []).extend(ids)
    svids = list(dict.fromkeys(held))
    ids = {pid for pid_list in held.values() for pid in pid_list}
    sent = set(first["passage_ids"])
    words = list(dict.fromkeys(t for q in queries for t in terms(q)))[:MAX_TERMS]
    fts = " OR ".join(f'"{t}"' for t in words)
    everything = sum(len(store.passages_for(svid)) for svid in svids)
    lexical = [p for p in store.search_passages(svids, fts, max(everything, 1)) if p["id"] in ids] if words else []
    semantic = await flow._semantic_ranking(run, scope, svids, query_text="\n".join(queries), key=MORE_SEMANTIC_KEY,
                                            query_origin="followup", only=ids)
    semantic = [p for p in semantic or [] if p["id"] in ids]
    ranked = fuse_rankings(lexical, semantic) if semantic else lexical
    ranked = sorted(ranked, key=lambda p: _reference_list(p["text"]))
    new = [p["id"] for p in ranked if p["id"] not in sent][:limit // 2]
    kept = first["passage_ids"][:max(0, limit - len(new))]
    output = {"queries": queries, "terms": words, "lexical_matches": len(lexical), "semantic_matches": len(semantic),
              "new_passages": len(new), "limit": limit, "passage_ids": kept + new}
    return _code_step(flow, run, MORE_SELECTION_KEY, "code:followup_more_passages", lambda: output)


async def answer(flow: Any, run: dict[str, Any], scope: dict[str, Any]) -> None:
    store, run_id = flow.store, run["id"]
    turn = turn_for_run(store, run_id)
    if turn is None:
        flow._fail(run_id, "followup_turn_missing")
    if turn["status"] != "pending":
        return  # published before a restart; the run completes without asking again
    flow._checkpoint(run_id, run["scope_revision"])
    store.update_run(run_id, stage="answer")
    frozen_pool = _code_step(flow, run, POOL_KEY, "code:followup_pool",
                             lambda: pool(store, run["research_id"], turn["scope_revision"], flow))
    _guard(flow, run, frozen_pool)  # a resumed run: the person's choices or the files may have changed meanwhile
    considered = sum(len(v) for v in frozen_pool["sources"].values())
    if not considered:
        flow._checkpoint(run_id, run["scope_revision"])
        publish(flow, run, turn, frozen_pool, "no_passages", considered=0, given=0,
                validation={"ok": True, "issues": [], "reason": "no_stored_passages",
                            "note": "This research held no passage to give; no model was asked and no search was run."})
        return
    selected = await _selection(flow, run, scope, turn["question"], frozen_pool)
    flow._checkpoint(run_id, run["scope_revision"])
    context = _code_step(flow, run, CONVERSATION_KEY, "code:followup_conversation",
                         lambda: conversation(store, run["research_id"], scope["question"], turn))
    passages = [store.passage(pid) for pid in selected["passage_ids"]]
    key, output = TASK, await _call(flow, run, scope, TASK, passages, context | {"more_queries_allowed": True}, frozen_pool)
    queries = [] if output.get("invalid") else [q for q in output["result"].get("more_queries", []) if q.strip()]
    if queries and output["result"]["outcome"] != "answered":
        # The model asked the library for more (D50): its phrases rank everything this research holds, and a second
        # call answers from the first round's passages with the new ones. No search runs and no provider is asked.
        flow._checkpoint(run_id, run["scope_revision"])
        more = await _more_selection(flow, run, scope, queries[:MAX_MORE_QUERIES], selected, frozen_pool)
        if more["passage_ids"] != selected["passage_ids"]:
            more_passages = [store.passage(pid) for pid in more["passage_ids"]]
            second = await _call(flow, run, scope, MORE_KEY, more_passages,
                                 context | {"more_queries_allowed": False}, frozen_pool, budget_short="skip")
            # A second round that ends invalid leaves the first round's valid answer to be published.
            if not second.get("invalid"):
                key, output, passages = MORE_KEY, second, more_passages
    # No await from this check to the publication: a pause, cancel or newer question revision stops it unpublished,
    # and `publish` checks the frozen pool again inside its transaction.
    flow._checkpoint(run_id, run["scope_revision"])
    considered = sum(len(v) for part in ("sources", "reserve") for v in frozen_pool.get(part, {}).values())
    step = store.existing_step(run_id, key)
    if output.get("invalid"):
        try:
            draft = json.loads(output.get("raw_output") or "")
            draft = draft if isinstance(draft, dict) else None
        except json.JSONDecodeError:
            draft = None
        publish(flow, run, turn, frozen_pool, "unverified_draft", considered=considered, given=len(passages), step_id=step["id"],
                step_input_id=output["step_input_id"], draft=draft, validation={"ok": False, "issues": output["issues"]})
        return
    payload = store.step_input_payload(output["step_input_id"])
    result = output["result"]
    links = contracts.derive_evidence_links(payload, result)
    if any(link["anchor_text"] is None for link in links):
        # Validation locates every anchor; one that does not locate now is never published as a citation.
        publish(flow, run, turn, frozen_pool, "unverified_draft", considered=considered, given=len(passages), step_id=step["id"],
                step_input_id=output["step_input_id"], draft=result,
                validation={"ok": False, "issues": [{"code": "anchor_not_in_passage", "path": "/citation_anchors",
                                                     "message": "an anchor no longer locates in its passage"}]})
        return
    publish(flow, run, turn, frozen_pool, result["outcome"], considered=considered, given=len(passages), step_id=step["id"],
            step_input_id=output["step_input_id"], draft=result,
            validation={"ok": True, "issues": [], "warnings": output.get("warnings", [])}, links=links)


def _language_tag(value: Any) -> str | None:
    """A language tag for the typed column, or None: an invalid draft's raw value (an object, a list, a malformed
    string) stays only in its stored JSON."""
    return value if isinstance(value, str) and LANGUAGE_TAG.fullmatch(value) else None


def publish(flow: Any, run: dict[str, Any], turn: dict[str, Any], frozen_pool: dict[str, Any], status: str, *,
            considered: int, given: int, validation: dict[str, Any], step_id: str | None = None,
            step_input_id: str | None = None, draft: dict[str, Any] | None = None,
            links: list[dict[str, Any]] | None = None) -> None:
    """The turn's answer and its evidence links in one transaction; a turn already published is left as it is.

    The frozen pool is checked inside the same transaction, so nothing a person changed can slip in between the check
    and the write; a change fails the run (outside the transaction, which then writes nothing)."""
    store = flow.store
    with transaction(store.conn):
        reason = changed(store, run["research_id"], frozen_pool)
        updated = 0 if reason else store.conn.execute(
            "UPDATE followup_turns SET status = ?, step_id = ?, step_input_id = ?, answer_language = ?, draft_json = ?,"
            " validation_json = ?, passages_considered = ?, passages_given = ?, selection_revision = ?,"
            " user_signature = ?, published_at = ? WHERE id = ? AND status = 'pending'",
            (status, step_id, step_input_id, _language_tag((draft or {}).get("answer_language")),
             dumps(draft) if draft is not None else None, dumps(validation), considered, given,
             frozen_pool["selection_revision"], frozen_pool["user_signature"], now(), turn["id"]),
        ).rowcount
        if updated:
            for link in links or []:
                store.conn.execute(
                    "INSERT INTO followup_turn_links (id, turn_id, claim_label, passage_id, source_version_id,"
                    " step_input_id, support_type, anchor_text, anchor_match) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)",
                    (new_id("ful"), turn["id"], link["claim_label"], link["passage_id"], link["source_id"],
                     step_input_id, link["support_type"], link["anchor_text"], link["anchor_match"]))
            store.conn.execute("UPDATE researches SET updated_at = ? WHERE id = ?", (now(), run["research_id"]))
            store._event(run["research_id"], "followup_answered", {"turn_id": turn["id"], "status": status}, run["id"])
    if reason:
        flow._fail(run["id"], reason, {"note": "Ask the follow-up again to answer it from the research as it is now."})


def turn_view(store: Any, row: dict[str, Any]) -> dict[str, Any]:
    """One turn as the UI reads it. Claims and citations are shown only for a valid published answer; an unverified
    draft shows its issues and no claim (fail-closed). `question` is what "Search for new works on this" revises to."""
    run = store.run(row["run_id"])
    research = store.conn.execute("SELECT current_scope_revision, selection_revision FROM researches WHERE id = ?",
                                  (row["research_id"],)).fetchone()
    current = research["current_scope_revision"]
    # Published under an older source selection: the person included, excluded or set a source pending since. Apart
    # from `stale_scope`, which is about the question.
    stale_selection = row["status"] != "pending" and (
        row["selection_revision"] != research["selection_revision"]
        or row["user_signature"] != small_batch.user_signature(store, row["research_id"]))
    answer = None
    if row["status"] in PUBLISHED:
        draft = json.loads(row["draft_json"])
        cited: dict[str, list[dict[str, Any]]] = {}
        # As the answer view marks its quotes (D45, D50, SW21): a quote of a source removed from this research, of a
        # removed or replaced PDF, or of a superseded text extraction still opens what was read, and says so.
        removed = {r[0] for r in store.conn.execute(
            "SELECT source_version_id FROM corpus_memberships WHERE research_id = ? AND removed_at IS NOT NULL",
            (row["research_id"],))}
        for link in store.conn.execute(
                "SELECT l.*, p.kind, p.physical_page, p.printed_label, p.text_source, v.title, v.year, v.version_label,"
                f" v.work_id, {EVIDENCE_STATUS_SQL} AS evidence_status, {RENDITION_SQL} AS rendition"
                " FROM followup_turn_links l JOIN passages p ON p.id = l.passage_id"
                " JOIN source_versions v ON v.id = l.source_version_id LEFT JOIN source_assets a ON a.id = p.asset_id"
                " WHERE l.turn_id = ? ORDER BY l.rowid", (row["id"],)):
            cited.setdefault(link["claim_label"], []).append({
                "passage_id": link["passage_id"], "source_version_id": link["source_version_id"],
                "work_id": link["work_id"], "title": link["title"], "year": link["year"],
                "version_label": link["version_label"],
                "reading_depth": "abstract" if link["kind"] == "abstract" else "selected_sections",
                "locator": {"kind": link["kind"], "physical_page": link["physical_page"],
                            "printed_label": link["printed_label"]},
                "anchor_text": link["anchor_text"], "anchor_match": link["anchor_match"],
                "evidence_status": link["evidence_status"], "text_source": link["text_source"],
                "removed_from_research": link["source_version_id"] in removed, "rendition": bool(link["rendition"])})
        answer = {"answer_language": draft["answer_language"], "outcome": draft["outcome"],
                  "claims": [{"label": c["claim_label"], "text": c["text"], "support_type": c["support_type"],
                              "citations": cited.get(c["claim_label"], [])} for c in draft["claims"]],
                  "unanswered_aspects": draft["unanswered_aspects"]}
    validation = json.loads(row["validation_json"]) if row["validation_json"] else None
    # The turn's live steps (UI parity S22b) from its stored step rows: how many passages the stored selection sends
    # (the call's allowlist, never an estimate) once that step has succeeded, and the state of the answer's model step.
    steps = {r["operation_key"]: r for r in store.conn.execute(
        "SELECT operation_key, status, error_code, output_json FROM run_steps WHERE run_id = ? AND operation_key IN (?, ?, ?, ?)",
        (row["run_id"], SELECTION_KEY, TASK, MORE_SELECTION_KEY, MORE_KEY))}
    selection = steps.get(SELECTION_KEY)
    chosen = (json.loads(selection["output_json"]) if selection is not None and selection["status"] == "succeeded"
              and selection["output_json"] else None)
    more = steps.get(MORE_SELECTION_KEY)
    more = json.loads(more["output_json"]) if more is not None and more["status"] == "succeeded" and more["output_json"] else None
    # The second round (D50): how many passages the model's own phrases brought in, and the state of its call.
    progress = {"passages_selected": len(chosen["passage_ids"]) if chosen else None,
                "answer_step": steps[TASK]["status"] if TASK in steps else None,
                "more_passages": more["new_passages"] if more else None,
                "more_step": steps[MORE_KEY]["status"] if MORE_KEY in steps else None,
                # A second round that failed validation was read; one the spent budget skipped was never sent.
                "more_error": steps[MORE_KEY]["error_code"] if MORE_KEY in steps else None}
    if answer is not None:
        # The validation warnings stored with the answer (math, several sources), as the answer view's `validation`.
        answer["warnings"] = (validation or {}).get("warnings", [])
    return {
        "id": row["id"], "research_id": row["research_id"], "scope_revision": row["scope_revision"],
        "question": row["question"], "status": row["status"], "created_at": row["created_at"],
        "published_at": row["published_at"], "stale_scope": row["scope_revision"] != current,
        "stale_selection": stale_selection,
        "passages_considered": row["passages_considered"], "passages_given": row["passages_given"],
        "progress": progress,
        "run": {"id": run["id"], "status": run["status"], "stage": run["stage"], "pause_reason": run["pause_reason"],
                "error": run["error"]},
        "answer": answer,
        "issues": validation["issues"] if row["status"] == "unverified_draft" and validation else [],
    }


def turns(store: Any, research_id: str) -> list[dict[str, Any]]:
    store.research(research_id)
    return [turn_view(store, dict(row)) for row in store.conn.execute(
        "SELECT * FROM followup_turns WHERE research_id = ? ORDER BY created_at, rowid", (research_id,))]


def turn(store: Any, research_id: str, turn_id: str) -> dict[str, Any]:
    from deixis.workflow.store import NotFound
    store.research(research_id)
    row = store.conn.execute("SELECT * FROM followup_turns WHERE id = ? AND research_id = ?",
                             (turn_id, research_id)).fetchone()
    if row is None:
        raise NotFound(turn_id)
    return turn_view(store, dict(row))
