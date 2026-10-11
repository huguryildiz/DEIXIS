"""Change the model one role of a research uses (UI parity S17, F10); the application middleware enforces CSRF.

The route serves the model-down notice's "Choose another model" (R20): a model that is down or refused is never
replaced by the app, so the way on is the person's explicit choice, which is recorded (`research_model_changes`) and
shown (`model_changes` in the research view). The new model must be listed by its connection, as at creation.
"""

from typing import Literal

from fastapi import HTTPException, Request
from pydantic import BaseModel, ConfigDict, Field

from deixis.workflow.views import research_view


class ModelChange(BaseModel):
    model_config = ConfigDict(extra="forbid")
    role: Literal["answer", "literature", "reviewer"]
    connection: str = Field(min_length=1, max_length=40)
    model: str = Field(min_length=1, max_length=120)
    reasoning_effort: str | None = Field(default=None, min_length=1, max_length=40)
    # Why the person changed it, e.g. the pause reason of the notice it came from; stored as given.
    reason: str | None = Field(default=None, min_length=1, max_length=200)
    expected_version: int = Field(ge=1, strict=True)


def register_research_model_routes(app):
    from deixis.api.app import check_offered

    @app.put("/api/researches/{research_id}/models")
    async def change_research_model(research_id: str, body: ModelChange, request: Request):
        store = request.app.state.store
        store.research(research_id)
        adapter = request.app.state.adapters.get(body.connection)
        if adapter is None:
            raise HTTPException(422, f"Model connection '{body.connection}' is not available")
        check_offered((await adapter.health()).get("models"), body.connection, body.model, body.reasoning_effort)
        try:
            store.change_role_model(research_id, body.role, body.connection, body.model, body.reasoning_effort,
                                    body.expected_version, body.reason)
        except ValueError as exc:
            raise HTTPException(422, str(exc)) from exc
        return research_view(store, research_id)
