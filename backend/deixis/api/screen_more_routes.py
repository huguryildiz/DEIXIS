"""The not-read list and the "Screen more" run (UI parity S20, F12 and F13); the application middleware enforces CSRF.

`GET .../unscreened` pages through the works of the latest completed discovery's frozen list that were never screened,
in list order; rank and similarity are labelled prioritization signals. `POST .../screen-more` queues one `screen_more`
run for the next 40 of them that have an abstract: 409 while another run of the research is active, 422 when there is
no completed discovery list or nothing screenable is left. Pause, resume and cancel are the run controls every run has
(`/api/runs/{run_id}/{action}`).
"""

from fastapi import Header, HTTPException, Query, Request
from fastapi.responses import JSONResponse

from deixis.workflow import screen_more


def register_screen_more_routes(app):
    @app.get("/api/researches/{research_id}/unscreened")
    async def unscreened(research_id: str, request: Request, offset: int = Query(0, ge=0),
                         limit: int = Query(50, ge=1, le=screen_more.MAX_PAGE)):
        try:
            return screen_more.unscreened(request.app.state.store, research_id, offset, limit)
        except screen_more.NothingToScreen as exc:
            raise HTTPException(422, exc.detail) from exc

    @app.post("/api/researches/{research_id}/screen-more", status_code=202)
    async def screen_more_run(research_id: str, request: Request,
                              idempotency_key: str | None = Header(default=None, max_length=200)):
        try:
            run = screen_more.request(request.app.state.store, research_id, idempotency_key)
        except screen_more.NothingToScreen as exc:
            return JSONResponse({"detail": exc.detail, "code": exc.code}, status_code=422)
        request.app.state.worker.wake()
        return run
