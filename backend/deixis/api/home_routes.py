"""Home's suggestions (UI parity S5a, F5): the stored `unanswered_aspects` of the latest current, valid answers.

No model is asked and nothing is written. An unanswered aspect is the answer model's note of what the given passages
did not cover; it is not a proven gap in the literature, so Home labels these only as suggestions.
"""

from __future__ import annotations

import json
from typing import Any

from fastapi import Request

from deixis.workflow.store import Store

MAX_SUGGESTIONS = 2


def suggestions(store: Store, limit: int = MAX_SUGGESTIONS) -> list[dict[str, Any]]:
    """Newest first, at most `limit`: each research's latest structurally valid answer, kept only while it was made for
    the research's current question (an answer to an earlier revision is stale and gives nothing)."""
    rows = store.conn.execute(
        "SELECT a.id, a.research_id, a.draft_json, a.created_at, r.title FROM answers a"
        " JOIN researches r ON r.id = a.research_id"
        " WHERE r.trashed_at IS NULL AND a.status = 'structurally_valid' AND a.scope_revision = r.current_scope_revision"
        " AND a.rowid = (SELECT b.rowid FROM answers b WHERE b.research_id = a.research_id"
        " AND b.status = 'structurally_valid' ORDER BY b.created_at DESC, b.rowid DESC LIMIT 1)"
        " ORDER BY a.created_at DESC, a.rowid DESC").fetchall()
    found: list[dict[str, Any]] = []
    for row in rows:
        draft = json.loads(row["draft_json"]) if row["draft_json"] else {}
        for text in draft.get("unanswered_aspects") or []:
            if isinstance(text, str) and text.strip():
                found.append({"text": text.strip(), "research_id": row["research_id"], "research_title": row["title"],
                              "answer_id": row["id"], "created_at": row["created_at"]})
                if len(found) == limit:
                    return found
    return found


def register_home_routes(app) -> None:
    @app.get("/api/suggestions")
    async def get_suggestions(request: Request) -> dict[str, Any]:
        return {"suggestions": suggestions(request.app.state.store)}
