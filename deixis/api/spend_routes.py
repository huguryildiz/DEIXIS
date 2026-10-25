"""Settings → Usage → Estimated spending, and the estimate shown before a research starts (pre-P10 F4).

The daily threshold is an estimated-spend stopping threshold, not a hard limit: a run pauses before its next paid-API
call once the day's estimate has reached it, and a call already sent is never cut. The estimate comes from the usage the
provider returned and a dated static price table; the provider's own bill is what counts.
"""

from __future__ import annotations

from typing import Any, Literal

from fastapi import Request
from pydantic import BaseModel, ConfigDict, Field

from deixis.documents import embeddings, rerankers
from deixis.workflow.run import spend, spend_estimate


class SpendingChange(BaseModel):
    model_config = ConfigDict(extra="forbid")
    daily_threshold_usd: float | None = Field(gt=0, le=100_000)  # required; null turns the threshold off


class RoleChoice(BaseModel):
    model_config = ConfigDict(extra="forbid")
    connection: str = Field(max_length=100)
    model: str = Field(max_length=200)
    reasoning_effort: str | None = Field(default=None, max_length=50)


class EstimateRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")
    effort: Literal["quick", "standard", "detailed"]
    literature: RoleChoice | None = None
    answer: RoleChoice | None = None
    reviewer: RoleChoice | None = None


def register_spend_routes(app) -> None:
    def view(request: Request) -> dict[str, Any]:
        store = request.app.state.store
        table = spend.price_table()
        return {"daily_threshold_usd": spend.threshold(store), "today": spend.day_total(store.conn, spend.day_of(store.clock)),
                "prices": {"version": table["version"], "as_of": table["as_of"]}}

    @app.get("/api/settings/spending")
    async def get_spending(request: Request) -> dict[str, Any]:
        return view(request)

    @app.put("/api/settings/spending")
    async def put_spending(body: SpendingChange, request: Request) -> dict[str, Any]:
        request.app.state.store.set_setting(spend.THRESHOLD_SETTING, body.daily_threshold_usd)
        return view(request)

    @app.post("/api/spend/estimate")
    async def estimate(body: EstimateRequest, request: Request) -> dict[str, Any]:
        state = request.app.state
        provider, _ = embeddings.chosen(state.store.setting("semantic_search"))
        roles = {role: (getattr(body, role).model_dump() if getattr(body, role) else None) for role in spend_estimate.ROLES}
        rerank = rerankers.chosen(state.store.setting(rerankers.SETTING))
        return spend_estimate.estimate(state.package, body.effort, roles, reading_on=state.settings.fulltext_adjudication == "auto",
                                       embedding_provider=provider, rerank_provider=rerank.provider if rerank else None)
