"""Follow-up questions of a research (UI parity S22a, F17); the application middleware enforces CSRF.

A question is answered by one `followup_answer` run from passages this research already holds; no search is started.
Pause, resume and cancel are the run controls every run has (`/api/runs/{run_id}/{action}`), and the research's
one-active-run rule answers 409. "Search for new works on this" is a new scope revision with the turn's `question`,
saved through the existing scope route.
"""

from fastapi import Header, HTTPException, Request
from pydantic import BaseModel, ConfigDict, Field

from deixis.workflow import followup


class Ask(BaseModel):
    model_config = ConfigDict(extra="forbid")
    question: str = Field(min_length=1, max_length=followup.MAX_QUESTION_CHARS)
    expected_scope_revision: int = Field(ge=1, strict=True)  # the question revision the person is looking at


def register_followup_turns_routes(app):
    root = "/api/researches/{research_id}/followup-turns"

    @app.post(root, status_code=202)
    async def ask(research_id: str, body: Ask, request: Request,
                  idempotency_key: str | None = Header(default=None, max_length=200)):
        store = request.app.state.store
        try:
            row = followup.request_turn(store, research_id, body.question, body.expected_scope_revision, idempotency_key)
        except followup.FollowupRefused as exc:
            raise HTTPException(422, str(exc)) from exc
        request.app.state.worker.wake()
        return followup.turn_view(store, row)

    @app.get(root)
    async def listing(research_id: str, request: Request):
        return followup.turns(request.app.state.store, research_id)

    @app.get(root + "/{turn_id}")
    async def one(research_id: str, turn_id: str, request: Request):
        return followup.turn(request.app.state.store, research_id, turn_id)
