"""Reverse citation search R2: read a statement research's check revisions, one revision with its items and counters,
its preview (list, cap and cost range on the model stored with it) and its export. A check is started, checked again
and resumed through the run routes (`POST /api/researches/{id}/runs` with kind `statement_check`, and the run resume),
never here; nothing here calls a model or writes a revision. Reading a revision marks it `stale` when it no longer
stands (`statement_check.refresh_currency`).
"""

from __future__ import annotations

from typing import Any

from fastapi import Query, Request
from fastapi.responses import Response

from deixis.workflow import statement_check


def register_statement_check_routes(app) -> None:
    @app.get("/api/researches/{research_id}/statement-checks")
    async def list_checks(research_id: str, request: Request) -> dict[str, Any]:
        store = request.app.state.store
        store.research(research_id)
        return statement_check.list_checks(store, research_id)

    @app.get("/api/statement-checks/{check_id}")
    async def check_view(check_id: str, request: Request) -> dict[str, Any]:
        return statement_check.view(request.app.state.store, check_id)

    @app.get("/api/statement-checks/{check_id}/preview")
    async def check_preview(check_id: str, request: Request) -> dict[str, Any]:
        return statement_check.preview(request.app.state.store, check_id)

    @app.get("/api/statement-checks/{check_id}/export")
    async def check_export(check_id: str, request: Request, format: str = Query("csv", pattern="^(csv|md)$")):
        text = statement_check.export(request.app.state.store, check_id, format)
        media = "text/csv" if format == "csv" else "text/markdown"
        return Response(text, media_type=f"{media}; charset=utf-8",
                        headers={"Content-Disposition": f'attachment; filename="statement-check-{check_id}.{format}"'})
