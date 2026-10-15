"""Settings → General → Research: the default depth of a new research and three background behaviors.

Each value is stored in `app_settings` and comes before the value DEIXIS started with (its environment variable or
default). The full-text fetch is read when a discovery run is queued, so a run already queued keeps its mode; the
arXiv route and the model-call ceiling change at once.
"""

from __future__ import annotations

from typing import Any, Literal

from fastapi import Request
from pydantic import BaseModel, ConfigDict, Field

from deixis.config import (ARXIV_SOURCE_SETTING, DEFAULT_EFFORT_SETTING, FULLTEXT_FETCH_SETTING, MODEL_CONCURRENCY_MAX,
                           MODEL_CONCURRENCY_SETTING)
from deixis.documents import arxiv_source

EFFORTS = ("quick", "standard", "detailed")


class Preferences(BaseModel):
    model_config = ConfigDict(extra="forbid")
    default_effort: Literal["quick", "standard", "detailed"] | None = None
    fulltext_fetch: Literal["auto", "off"] | None = None
    arxiv_source: Literal["auto", "off"] | None = None
    model_concurrency: int | None = Field(default=None, ge=1, le=MODEL_CONCURRENCY_MAX)


def register_preference_routes(app) -> None:
    def view(request: Request) -> dict[str, Any]:
        state = request.app.state
        settings, store = state.settings, state.store
        effort = store.setting(DEFAULT_EFFORT_SETTING)
        equations = getattr(state, "equations", None)
        return {
            "default_effort": effort if effort in EFFORTS else "standard",
            "fulltext_fetch": settings.effective_fulltext_fetch(),
            "arxiv_source": settings.effective_arxiv_source(),
            # The arXiv route runs only on POSIX and only while Marker (the equation reader) is not installed.
            "arxiv_route_possible": arxiv_source.posix_available(),
            "marker_present": bool(equations and equations.marker_present()),
            "model_concurrency": settings.effective_model_concurrency(),
            "model_concurrency_max": MODEL_CONCURRENCY_MAX,
        }

    @app.get("/api/settings/preferences")
    async def get_preferences(request: Request) -> dict[str, Any]:
        return view(request)

    @app.put("/api/settings/preferences")
    async def put_preferences(body: Preferences, request: Request) -> dict[str, Any]:
        state = request.app.state
        store = state.store
        changes = body.model_dump(exclude_none=True)
        keys = {"default_effort": DEFAULT_EFFORT_SETTING, "fulltext_fetch": FULLTEXT_FETCH_SETTING,
                "arxiv_source": ARXIV_SOURCE_SETTING, "model_concurrency": MODEL_CONCURRENCY_SETTING}
        for name, value in changes.items():
            store.set_setting(keys[name], value)
        if "arxiv_source" in changes and (equations := getattr(state, "equations", None)) is not None:
            equations.arxiv_mode = changes["arxiv_source"]
        if "model_concurrency" in changes and (limiter := getattr(state, "limiter", None)) is not None:
            await limiter.set_limit(changes["model_concurrency"])
        return view(request)
