"""Citation snowballing (plan .local/plans/snowballing-plan.md); the application middleware enforces CSRF.

`GET .../snowball` lists the works a round can start from and every series with its rounds, counts and new works.
`POST .../snowball` queues one round: 409 while another run of the research is active or the series cannot go on,
422 when no search of the question finished, no chosen work has an OpenAlex record, or the series reached its round cap.
Pause, resume and cancel are the run controls every run has (`/api/runs/{run_id}/{action}`).
"""

from fastapi import Header, Query, Request
from fastapi.responses import JSONResponse
from pydantic import BaseModel, Field

from deixis.workflow import snowball


class SnowballRound(BaseModel):
    seeds: list[str] = Field(default_factory=list, max_length=snowball.MAX_SEEDS)
    dois: list[str] = Field(default_factory=list, max_length=snowball.MAX_SEEDS)
    directions: list[str] = Field(default_factory=lambda: list(snowball.DIRECTIONS), min_length=1, max_length=2)
    series_id: str | None = Field(default=None, max_length=200)


def register_snowball_routes(app):
    @app.get("/api/researches/{research_id}/snowball")
    async def snowball_view(research_id: str, request: Request, include_excluded: bool = Query(False)):
        return snowball.view(request.app.state.store, research_id, include_excluded)

    @app.post("/api/researches/{research_id}/snowball", status_code=202)
    async def snowball_run(research_id: str, body: SnowballRound, request: Request,
                           idempotency_key: str | None = Header(default=None, max_length=200)):
        try:
            run = snowball.request(request.app.state.store, research_id, seeds=body.seeds, dois=body.dois,
                                   directions=body.directions, series_id=body.series_id,
                                   idempotency_key=idempotency_key)
        except snowball.SnowballRefused as exc:
            return JSONResponse(exc.extra | {"detail": exc.detail, "code": exc.code}, status_code=exc.status)
        request.app.state.worker.wake()
        return run
