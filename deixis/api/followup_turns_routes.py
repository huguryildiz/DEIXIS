"""Follow-up questions of a research (UI parity S22a, F17); the application middleware enforces CSRF.

A question is answered by one `followup_answer` run from passages this research already holds; no search is started.
Pause, resume and cancel are the run controls every run has (`/api/runs/{run_id}/{action}`), and the research's
one-active-run rule answers 409. "Search for new works" is the turn's own `followup_search` run: the person
either asks for it with the question (`search` in the body, which runs it after the answer and answers the question
again over what it found) or starts it afterwards themselves (`POST .../{turn_id}/search`). Neither opens a
question revision.
"""

from fastapi import Header, HTTPException, Request
from fastapi.responses import JSONResponse
from pydantic import BaseModel, ConfigDict, Field

from deixis.workflow.answer import followup, followup_attachments
from deixis.workflow.search import followup_search


class Attachment(BaseModel):
    """What the person selected before they asked. The text travels here, outside the question's own budget, and the
    id says what it was selected from; the work, the version and the page are read from stored rows, never from here.
    """

    model_config = ConfigDict(extra="forbid")
    kind: str = Field(min_length=1, max_length=32)
    ref_id: str | None = Field(default=None, max_length=64)
    text: str = Field(min_length=1, max_length=followup_attachments.MAX_TEXT_CHARS)


class Ask(BaseModel):
    model_config = ConfigDict(extra="forbid")
    question: str = Field(min_length=1, max_length=followup.MAX_QUESTION_CHARS)
    expected_scope_revision: int = Field(ge=1, strict=True)  # the question revision the person is looking at
    attachments: list[Attachment] = Field(default_factory=list, max_length=followup_attachments.MAX_ATTACHMENTS)
    # The person asked for works this research does not hold. The turn is answered from what it holds first; the
    # search runs next, and what it finds is answered in a turn of its own (`followup_revision`).
    search: bool = False


class Search(BaseModel):
    model_config = ConfigDict(extra="forbid")
    expected_scope_revision: int = Field(ge=1, strict=True)


class Branch(BaseModel):
    """A research of its own for a question that moved to another setting. The question is the person's, editable
    before they accept; everything else about how the research is run comes from the one it was opened from, and
    nothing about what that research screened, included, read or concluded comes with it."""

    model_config = ConfigDict(extra="forbid")
    question: str = Field(min_length=3, max_length=4000)
    expected_scope_revision: int = Field(ge=1, strict=True)
    # The new question's own language, as the home screen sends it for any research; the old one's does not carry.
    language_hint: str | None = Field(default=None, pattern=r"^[a-z]{2,3}(-[A-Za-z0-9]{2,8})*$")


def register_followup_turns_routes(app):
    root = "/api/researches/{research_id}/followup-turns"

    @app.post(root, status_code=202)
    async def ask(research_id: str, body: Ask, request: Request,
                  idempotency_key: str | None = Header(default=None, max_length=200)):
        store = request.app.state.store
        try:
            row = followup.request_turn(store, research_id, body.question, body.expected_scope_revision,
                                        idempotency_key,
                                        [item.model_dump() for item in body.attachments], body.search)
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

    @app.post(root + "/{turn_id}/report", status_code=202)
    async def report(research_id: str, turn_id: str, body: Search, request: Request):
        """Add this answer to the report: the person's own action, which opens the next report version.

        Their second try after a run that wrote nothing is a request of its own; a run still going or paused is the
        same try and answers 409 (`followup.request_report_change`).
        """
        store = request.app.state.store
        try:
            run = followup.request_report_change(store, research_id, turn_id, body.expected_scope_revision)
        except followup.ReportChangeRefused as exc:
            return JSONResponse({"detail": str(exc), "code": exc.code}, status_code=422)
        request.app.state.worker.wake()
        return followup.turn(store, research_id, turn_id) | {"report_run_id": run["id"]}

    @app.post(root + "/{turn_id}/branch", status_code=201)
    async def branch(research_id: str, turn_id: str, body: Branch, request: Request):
        """Open a research of its own for this question, written by the same path as any new research.

        The scope settings come from the research this question was asked in; its criterion, screening, selections,
        works, seeds, search plan and report do not (`branch_research`).
        """
        from deixis.api.app import CreateResearch, checked_research_models, create_research_row, research_view
        from deixis.workflow.features.branch import branch_research

        store = request.app.state.store
        scope = store.scope(research_id)
        # Read first so the refusal reaches the person before any model list is fetched; read again inside the
        # write, because the question may be revised while that fetch is in flight (`branch_research.opened`).
        try:
            branch_research.check(store, research_id, turn_id, body.expected_scope_revision)
        except branch_research.BranchRefused as exc:
            return JSONResponse({"detail": str(exc), "code": exc.code}, status_code=422)
        asked = CreateResearch(
            question=body.question, language_hint=body.language_hint,
            source_scope=scope["source_scope"], effort=scope["effort"],
            model_connection=scope["model_connection"], requested_model=scope["requested_model"],
            reasoning_effort=scope["reasoning_effort"], literature_model=scope["literature_model"],
            literature_reasoning_effort=scope["literature_reasoning_effort"],
            literature_connection=scope["literature_connection"], review_mode=scope["review_mode"],
            review_model=scope["review_model"], review_connection=scope["review_connection"],
            review_reasoning_effort=scope["review_reasoning_effort"],
            # The field a sentence is checked in belongs to the sentence: the new one is about something else, so
            # the branch leaves it for the query model to name, as a research the person starts without one does.
            intent=store.research(research_id)["intent"], field=None)
        # The models are checked before anything is written, as on the home screen; the await is outside the write.
        connections = await checked_research_models(store, request.app.state.adapters, asked)
        try:
            branch_id = branch_research.opened(
                store, research_id, turn_id, lambda: create_research_row(store, asked, *connections),
                body.expected_scope_revision)
        except branch_research.BranchRefused as exc:
            return JSONResponse({"detail": str(exc), "code": exc.code}, status_code=422)
        return research_view(store, branch_id)
