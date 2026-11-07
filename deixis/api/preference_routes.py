"""Settings → General → Research: the default depth of a new research and three background behaviors; and the
interface language and theme; and whether DEIXIS asks GitHub once a day for a newer version (`update_check.py`).

Each value is stored in `app_settings` and comes before the value DEIXIS started with (its environment variable or
default). The full-text fetch is read when a discovery run is queued, so a run already queued keeps its mode; the
arXiv route and the model-call ceiling change at once. Language and theme are kept here rather than only in the
browser (P10 M1): browser storage is per origin, and the packaged app's port can change; the browser keeps a copy as a
cache. Each reads None until the person chooses one. `fill_only` is the browser's one-time copy of its cached choice:
it writes language and theme only where the library holds none yet, so it never replaces a newer choice.
"""

from __future__ import annotations

from typing import Any, Literal

from fastapi import HTTPException, Request
from pydantic import BaseModel, ConfigDict, Field

from deixis.runtime.config import (ARXIV_SOURCE_SETTING, DEEP_SCREENING_SETTING, DEFAULT_EFFORT_SETTING,
                                   FULLTEXT_FETCH_SETTING, MODEL_CONCURRENCY_MAX, MODEL_CONCURRENCY_SETTING)
from deixis.workflow.run import fast_path
from deixis.runtime import update_check
from deixis.documents import arxiv_source

EFFORTS = ("quick", "standard", "detailed")
UI_LANGUAGE_SETTING = "ui_language"
UI_THEME_SETTING = "ui_theme"
LANGUAGES = ("en", "tr")
THEMES = ("system", "light", "dark")


class Preferences(BaseModel):
    model_config = ConfigDict(extra="forbid")
    default_effort: Literal["quick", "standard", "detailed"] | None = None
    fulltext_fetch: Literal["auto", "off"] | None = None
    arxiv_source: Literal["auto", "off"] | None = None
    deep_screening: Literal["on", "off"] | None = None
    model_concurrency: int | None = Field(default=None, ge=1, le=MODEL_CONCURRENCY_MAX)
    language: Literal["en", "tr"] | None = None
    theme: Literal["system", "light", "dark"] | None = None
    update_check: Literal["on", "off"] | None = None
    fill_only: bool = False


def register_preference_routes(app) -> None:
    def view(request: Request) -> dict[str, Any]:
        state = request.app.state
        settings, store = state.settings, state.store
        effort = store.setting(DEFAULT_EFFORT_SETTING)
        return {
            "default_effort": effort if effort in EFFORTS else "standard",
            "fulltext_fetch": settings.effective_fulltext_fetch(),
            "arxiv_source": settings.effective_arxiv_source(),
            # The arXiv route runs only on POSIX.
            "arxiv_route_possible": arxiv_source.posix_available(),
            # Read when a discovery is queued; the windows are the policy's own constant, by depth.
            "deep_screening": settings.effective_deep_screening(),
            "deep_screening_windows": {effort: fast_path.screened_once(effort) for effort in fast_path.DEEP_SCREENING_EFFORTS},
            "model_concurrency": settings.effective_model_concurrency(),
            "model_concurrency_max": MODEL_CONCURRENCY_MAX,
            "language": language if (language := store.setting(UI_LANGUAGE_SETTING)) in LANGUAGES else None,
            "theme": theme if (theme := store.setting(UI_THEME_SETTING)) in THEMES else None,
            "update_check": "on" if update_check.enabled(store) else "off",
        }

    @app.get("/api/settings/preferences")
    async def get_preferences(request: Request) -> dict[str, Any]:
        return view(request)

    @app.put("/api/settings/preferences")
    async def put_preferences(body: Preferences, request: Request) -> dict[str, Any]:
        state = request.app.state
        store = state.store
        changes = body.model_dump(exclude_none=True, exclude={"fill_only"})
        if body.fill_only:
            if set(changes) - {"language", "theme"}:
                raise HTTPException(422, "fill_only takes only language and theme")
            for name, value in changes.items():
                store.set_setting_if_unset({"language": UI_LANGUAGE_SETTING, "theme": UI_THEME_SETTING}[name], value)
            return view(request)
        keys = {"default_effort": DEFAULT_EFFORT_SETTING, "fulltext_fetch": FULLTEXT_FETCH_SETTING,
                "deep_screening": DEEP_SCREENING_SETTING,
                "arxiv_source": ARXIV_SOURCE_SETTING, "model_concurrency": MODEL_CONCURRENCY_SETTING,
                "language": UI_LANGUAGE_SETTING, "theme": UI_THEME_SETTING, "update_check": update_check.SETTING}
        for name, value in changes.items():
            store.set_setting(keys[name], value)
        if "arxiv_source" in changes and (equations := getattr(state, "equations", None)) is not None:
            equations.arxiv_mode = changes["arxiv_source"]
        if "model_concurrency" in changes and (limiter := getattr(state, "limiter", None)) is not None:
            await limiter.set_limit(changes["model_concurrency"])
        if changes.get("update_check") == "on" and (checker := getattr(state, "update_check", None)) is not None:
            checker.soon()  # turned on: checks at once when the last check is a day old
        return view(request)
