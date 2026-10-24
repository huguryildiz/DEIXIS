"""The search plan panel's routes (UI parity S23a, F18); the application middleware enforces CSRF.

`GET .../search-plan` returns the plan the panel shows: the current revision's saved plan, or the plan the newest run
of the same question searched (model-made or code-made), with Query 1 and Query 2 as read-only strings and the
providers. `POST .../search-plan` saves an edited plan as the research's next scope revision and returns the new
view; it starts no run (the person's "Search again" then starts one through the runs route). A plan that breaks a
rule is refused with 422 and every reason (`invalid_search_plan`, one issue per broken rule, `openalex_required`
among them); a stale `expected_version` is 409.
"""

from typing import Any

from fastapi import Request
from fastapi.responses import JSONResponse
from pydantic import BaseModel, ConfigDict, Field

from deixis.workflow import user_plan


class SavePlan(BaseModel):
    model_config = ConfigDict(extra="forbid")
    expected_version: int = Field(strict=True)
    plan: dict[str, Any]  # checked against deixis/contracts/research/user-search-plan.schema.json and the term rules


def register_search_plan_routes(app):
    root = "/api/researches/{research_id}/search-plan"

    @app.get(root)
    async def current(research_id: str, request: Request):
        return user_plan.view(request.app.state.store, research_id)

    @app.post(root)
    async def save(research_id: str, body: SavePlan, request: Request):
        store = request.app.state.store
        try:
            user_plan.save(store, research_id, body.expected_version, body.plan)
        except user_plan.PlanRefused as exc:
            return JSONResponse({"detail": "The search plan was not saved", "code": exc.code, "issues": exc.issues},
                                status_code=422)
        return user_plan.view(store, research_id)
