"""Owner commands for follow-up; the application middleware enforces CSRF."""

from typing import Literal

from fastapi import Header, Request
from pydantic import BaseModel, ConfigDict, Field

from deixis.workflow.watch.store import WatchStore
from deixis.workflow.watch.view import check_view, command_view, item_view, watch_view


class Preview(BaseModel):
    model_config = ConfigDict(extra="forbid")
    kind: Literal["protocol_queries", "citing_works"]


class Create(Preview):
    mode: Literal["manual", "interval"] = "manual"
    interval_days: Literal[1, 7, 30] | None = None
    catch_up: bool | None = Field(default=None, strict=True)
    expected_scope_revision: int = Field(ge=1, strict=True)


class Schedule(BaseModel):
    model_config = ConfigDict(extra="forbid")
    mode: Literal["manual", "interval"]
    interval_days: Literal[1, 7, 30] | None = None
    catch_up: bool | None = Field(default=None, strict=True)
    expected_schedule_version: int = Field(ge=1, strict=True)


class Expected(BaseModel):
    model_config = ConfigDict(extra="forbid")
    expected_state_version: int = Field(ge=1, strict=True)


class Dismiss(BaseModel):
    model_config = ConfigDict(extra="forbid")
    reason: str | None = Field(default=None, max_length=500)
    expected_status: str


def register_watch_routes(app):
    root = "/api/researches/{research_id}"
    key_type = Header(alias="Idempotency-Key", min_length=1, max_length=200)

    def store(request):
        return WatchStore(request.app.state.store)

    def answer(request, research_id, result, wake=False):
        response = command_view(store(request), research_id, result)
        if wake and not result["replayed"]:
            request.app.state.worker.wake()
        return response

    @app.post(root + "/watches/preview")
    async def preview(research_id: str, body: Preview, request: Request):
        return store(request).preview(research_id, body.kind)

    @app.post(root + "/watches", status_code=201)
    async def create(research_id: str, body: Create, request: Request, key: str = key_type):
        # Null schedule settings are equivalent to absence; retain B5 manual-command hashes after upgrade.
        return answer(request, research_id, store(request).create(research_id, body.model_dump(exclude_none=True), key), True)

    @app.get(root + "/watches")
    async def listing(research_id: str, request: Request):
        reader = store(request)
        return [watch_view(reader, row) for row in reader.watches(research_id)]

    @app.post(root + "/watches/{watch_id}/checks", status_code=202)
    async def check_now(research_id: str, watch_id: str, body: Expected, request: Request, key: str = key_type):
        return answer(request, research_id, store(request).check_now(research_id, watch_id, body.model_dump(), key), True)

    @app.post(root + "/watches/{watch_id}/disable")
    async def disable(research_id: str, watch_id: str, body: Expected, request: Request, key: str = key_type):
        return answer(request, research_id, store(request).disable(research_id, watch_id, body.model_dump(), key))

    @app.post(root + "/watches/{watch_id}/schedule")
    async def schedule(research_id: str, watch_id: str, body: Schedule, request: Request, key: str = key_type):
        return answer(request, research_id, store(request).schedule(research_id, watch_id, body.model_dump(), key))

    @app.post(root + "/watches/{watch_id}/rebind", status_code=201)
    async def rebind(research_id: str, watch_id: str, body: Expected, request: Request, key: str = key_type):
        return answer(request, research_id, store(request).rebind(research_id, watch_id, body.model_dump(), key), True)

    @app.get(root + "/watches/{watch_id}/checks/{check_id}")
    async def read_check(research_id: str, watch_id: str, check_id: str, request: Request):
        reader = store(request)
        return check_view(reader, reader.check(research_id, check_id, watch_id))

    @app.get(root + "/watch-items")
    async def items(research_id: str, request: Request, status: Literal["new", "dismissed", "merged", "added"] = "new"):
        reader = store(request)
        return [item_view(reader, row) for row in reader.items(research_id, status)]

    @app.post(root + "/watch-items/{item_id}/dismiss")
    async def dismiss(research_id: str, item_id: str, body: Dismiss, request: Request, key: str = key_type):
        return answer(request, research_id, store(request).dismiss(research_id, item_id, body.model_dump(), key))
