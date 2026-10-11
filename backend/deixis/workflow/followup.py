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
  sure since then gives nothing, and one whose file the person marked wrong gives its abstract only.
- `included_works`: otherwise (an answer over attached files, or none yet), the text of each included work's
  answer version (D48), as the attached-file answer reads it.
Only passages still current are used: an active source of the research and the extraction of the file in use.
"""

from __future__ import annotations

import json
import re
from typing import Any

from deixis.domain import contracts
from deixis.domain.rules import TEST_EFFORT_BUDGETS, RevisionConflict, check_expected_version
from deixis.storage.db import dumps, new_id, now, transaction
from deixis.workflow import fast_answer
from deixis.workflow.late_revision import REVISION_INPUT

TASK = "followup_answer"
POOL_KEY = "followup:pool"
SEMANTIC_KEY = "followup_semantic"
SELECTION_KEY = "followup:passages"
CALLS = 2  # the call and its one schema repair; the turn's own budget, apart from the research's runs
MAX_QUESTION_CHARS = 2000
PUBLISHED = ("answered", "partly_answered", "not_answered")
MAX_TERMS = 40


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


def pool(store: Any, research_id: str, scope_revision: int) -> dict[str, Any]:
    """The passages this research holds for a follow-up, by source in order (see the module text)."""
    current = {svid: [p["id"] for p in rows] for svid, rows in fast_answer.current_pools(store, research_id).items()}
    sources: dict[str, list[str]] = {}
    frozen = _answer_input(store, research_id, scope_revision)
    if frozen is not None:
        selections, humans = fast_answer.user_choices(store, research_id)
        for item in frozen["plan"]["items"]:
            svid = item["source_version_id"]
            user = selections.get(item.get("head")) or humans.get(item["work_id"])
            state = user["state"] if user else None
            if state in ("excluded", "pending"):
                continue
            ids = list(item["abstract_ids"])
            if item["route"] == "fulltext" and state != "pdf_wrong":
                ids += item["fulltext_ids"]
            have = set(current.get(svid, []))
            kept = [pid for pid in dict.fromkeys(ids) if pid in have and pid not in sources.get(svid, [])]
            if kept:
                sources.setdefault(svid, []).extend(kept)
        return {"basis": "answer_input", "answer_run_id": frozen["run_id"], "sources": sources}
    for head in store.included_works(research_id):
        svid = store.answer_version(research_id, head)
        if svid is not None and current.get(svid):
            sources[svid] = list(current[svid])
    return {"basis": "included_works", "answer_run_id": None, "sources": sources}


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


async def _selection(flow: Any, run: dict[str, Any], scope: dict[str, Any], question: str,
                     frozen_pool: dict[str, Any]) -> dict[str, Any]:
    """The passages sent: the pool ranked against the question (lexical and semantic, fused by RRF), then the rest of
    the pool breadth-first by source, under a per-source cap, up to the research's answer passage limit."""
    saved = flow.store.existing_step(run["id"], SELECTION_KEY)
    if saved and saved["status"] == "succeeded":
        return saved["output"]
    from deixis.workflow.flow import MAX_PASSAGES_PER_SOURCE, _reference_list, fuse_rankings
    store, limit = flow.store, run["budget"]["max_followup_passages"]
    sources = frozen_pool["sources"]
    svids = list(sources)
    ids = {pid for pid_list in sources.values() for pid in pid_list}
    words = terms(question)
    fts = " OR ".join(f'"{t}"' for t in words)
    everything = sum(len(store.passages_for(svid)) for svid in svids)
    lexical = [p for p in store.search_passages(svids, fts, max(everything, 1)) if p["id"] in ids]
    semantic = await flow._semantic_ranking(run, scope, svids, query_text=question, key=SEMANTIC_KEY,
                                            query_origin="followup", only=ids)
    semantic = [p for p in semantic or [] if p["id"] in ids]
    ranked = fuse_rankings(lexical, semantic) if semantic else lexical
    # A reference-list passage goes to the end: a misread one is ranked lower, not lost.
    ranked = sorted(ranked, key=lambda p: _reference_list(p["text"]))
    ranked_ids = [p["id"] for p in ranked]
    # The passages no ranking matched, breadth-first: each source's first passage (its abstract when it has one),
    # then each source's second, and so on. A question in another language than the passages matches no word, and
    # the model, not the word match, says whether the passages answer it.
    seen, fill = set(ranked_ids), []
    for depth in range(max((len(v) for v in sources.values()), default=0)):
        fill += [sources[svid][depth] for svid in svids if depth < len(sources[svid]) and sources[svid][depth] not in seen]
    per_source = max(MAX_PASSAGES_PER_SOURCE, limit // max(1, len(svids)))
    owner = {pid: svid for svid, pid_list in sources.items() for pid in pid_list}
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
              "from_ranking": from_ranking, "from_fill": len(chosen) - from_ranking}
    return _code_step(flow, run, SELECTION_KEY, "code:followup_passages", lambda: output)


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
                             lambda: pool(store, run["research_id"], turn["scope_revision"]))
    considered = sum(len(v) for v in frozen_pool["sources"].values())
    if not considered:
        flow._checkpoint(run_id, run["scope_revision"])
        publish(store, run, turn, "no_passages", considered=0, given=0,
                validation={"ok": True, "issues": [], "reason": "no_stored_passages",
                            "note": "This research held no passage to give; no model was asked and no search was run."})
        return
    selected = await _selection(flow, run, scope, turn["question"], frozen_pool)
    flow._checkpoint(run_id, run["scope_revision"])
    passages = [store.passage(pid) for pid in selected["passage_ids"]]
    source_ids = list(dict.fromkeys(p["source_version_id"] for p in passages))
    output = await flow._model_step(run, scope, TASK, TASK, source_ids=source_ids, passage_rows=passages)
    # No await from this check to the publication: a pause, cancel or newer question revision stops it unpublished.
    flow._checkpoint(run_id, run["scope_revision"])
    step = store.existing_step(run_id, TASK)
    if output.get("invalid"):
        try:
            draft = json.loads(output.get("raw_output") or "")
            draft = draft if isinstance(draft, dict) else None
        except json.JSONDecodeError:
            draft = None
        publish(store, run, turn, "unverified_draft", considered=considered, given=len(passages), step_id=step["id"],
                step_input_id=output["step_input_id"], draft=draft, validation={"ok": False, "issues": output["issues"]})
        return
    payload = store.step_input_payload(output["step_input_id"])
    result = output["result"]
    links = contracts.derive_evidence_links(payload, result)
    if any(link["anchor_text"] is None for link in links):
        # Validation locates every anchor; one that does not locate now is never published as a citation.
        publish(store, run, turn, "unverified_draft", considered=considered, given=len(passages), step_id=step["id"],
                step_input_id=output["step_input_id"], draft=result,
                validation={"ok": False, "issues": [{"code": "anchor_not_in_passage", "path": "/citation_anchors",
                                                     "message": "an anchor no longer locates in its passage"}]})
        return
    publish(store, run, turn, result["outcome"], considered=considered, given=len(passages), step_id=step["id"],
            step_input_id=output["step_input_id"], draft=result,
            validation={"ok": True, "issues": [], "warnings": output.get("warnings", [])}, links=links)


def publish(store: Any, run: dict[str, Any], turn: dict[str, Any], status: str, *, considered: int, given: int,
            validation: dict[str, Any], step_id: str | None = None, step_input_id: str | None = None,
            draft: dict[str, Any] | None = None, links: list[dict[str, Any]] | None = None) -> None:
    """The turn's answer and its evidence links in one transaction; a turn already published is left as it is."""
    with transaction(store.conn):
        updated = store.conn.execute(
            "UPDATE followup_turns SET status = ?, step_id = ?, step_input_id = ?, answer_language = ?, draft_json = ?,"
            " validation_json = ?, passages_considered = ?, passages_given = ?, published_at = ?"
            " WHERE id = ? AND status = 'pending'",
            (status, step_id, step_input_id, (draft or {}).get("answer_language"),
             dumps(draft) if draft is not None else None, dumps(validation), considered, given, now(), turn["id"]),
        ).rowcount
        if not updated:
            return
        for link in links or []:
            store.conn.execute(
                "INSERT INTO followup_turn_links (id, turn_id, claim_label, passage_id, source_version_id, step_input_id,"
                " support_type, anchor_text, anchor_match) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)",
                (new_id("ful"), turn["id"], link["claim_label"], link["passage_id"], link["source_id"], step_input_id,
                 link["support_type"], link["anchor_text"], link["anchor_match"]))
        store.conn.execute("UPDATE researches SET updated_at = ? WHERE id = ?", (now(), run["research_id"]))
        store._event(run["research_id"], "followup_answered", {"turn_id": turn["id"], "status": status}, run["id"])


def turn_view(store: Any, row: dict[str, Any]) -> dict[str, Any]:
    """One turn as the UI reads it. Claims and citations are shown only for a valid published answer; an unverified
    draft shows its issues and no claim (fail-closed). `question` is what "Search for new works on this" revises to."""
    run = store.run(row["run_id"])
    current = store.conn.execute("SELECT current_scope_revision FROM researches WHERE id = ?",
                                 (row["research_id"],)).fetchone()[0]
    answer = None
    if row["status"] in PUBLISHED:
        draft = json.loads(row["draft_json"])
        cited: dict[str, list[dict[str, Any]]] = {}
        for link in store.conn.execute(
                "SELECT l.*, p.kind, p.physical_page, p.printed_label, v.title, v.year, v.version_label, v.work_id"
                " FROM followup_turn_links l JOIN passages p ON p.id = l.passage_id"
                " JOIN source_versions v ON v.id = l.source_version_id WHERE l.turn_id = ? ORDER BY l.rowid",
                (row["id"],)):
            cited.setdefault(link["claim_label"], []).append({
                "passage_id": link["passage_id"], "source_version_id": link["source_version_id"],
                "work_id": link["work_id"], "title": link["title"], "year": link["year"],
                "version_label": link["version_label"],
                "reading_depth": "abstract" if link["kind"] == "abstract" else "selected_sections",
                "locator": {"kind": link["kind"], "physical_page": link["physical_page"],
                            "printed_label": link["printed_label"]},
                "anchor_text": link["anchor_text"], "anchor_match": link["anchor_match"]})
        answer = {"answer_language": draft["answer_language"], "outcome": draft["outcome"],
                  "claims": [{"label": c["claim_label"], "text": c["text"], "support_type": c["support_type"],
                              "citations": cited.get(c["claim_label"], [])} for c in draft["claims"]],
                  "unanswered_aspects": draft["unanswered_aspects"]}
    validation = json.loads(row["validation_json"]) if row["validation_json"] else None
    return {
        "id": row["id"], "research_id": row["research_id"], "scope_revision": row["scope_revision"],
        "question": row["question"], "status": row["status"], "created_at": row["created_at"],
        "published_at": row["published_at"], "stale_scope": row["scope_revision"] != current,
        "passages_considered": row["passages_considered"], "passages_given": row["passages_given"],
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
