"""Follow-up questions of a research (UI parity S22a, F17); the application middleware enforces CSRF.

A question is answered by one `followup_answer` run from passages this research already holds; no search is started.
Pause, resume and cancel are the run controls every run has (`/api/runs/{run_id}/{action}`), and the research's
one-active-run rule answers 409. "Search for new works" (D92) is the turn's own `followup_search` run, started only by
the person's click (`POST .../{turn_id}/search`); it opens no question revision.
"""

from fastapi import Header, HTTPException, Request
from fastapi.responses import JSONResponse
from pydantic import BaseModel, ConfigDict, Field

from deixis.workflow.answer import followup
from deixis.workflow.search import followup_search


class Ask(BaseModel):
    model_config = ConfigDict(extra="forbid")
    question: str = Field(min_length=1, max_length=followup.MAX_QUESTION_CHARS)
    expected_scope_revision: int = Field(ge=1, strict=True)  # the question revision the person is looking at


class Search(BaseModel):
    model_config = ConfigDict(extra="forbid")
    expected_scope_revision: int = Field(ge=1, strict=True)


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

    @app.post(root + "/{turn_id}/search", status_code=202)
    async def search(research_id: str, turn_id: str, body: Search, request: Request,
                     idempotency_key: str | None = Header(default=None, max_length=200)):
        store = request.app.state.store
        try:
            run = followup_search.request(store, research_id, turn_id, body.expected_scope_revision, idempotency_key)
        except followup_search.SearchRefused as exc:
            return JSONResponse({"detail": exc.detail, "code": exc.code}, status_code=422)
        request.app.state.worker.wake()
        return followup.turn(store, research_id, turn_id) | {"search_run_id": run["id"]}
