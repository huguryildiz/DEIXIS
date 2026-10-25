"""Evidence table runs added for the UI parity slices; the application middleware enforces CSRF.

Column recheck (S17, F20): one run rechecks every cell of a column in row order; each result waits as a proposal in its
cell and only the person's decision changes a value. Pause, resume and cancel are the run controls every run has
(`/api/runs/{run_id}/{action}`), and the one-active-run rule of the research answers 409.
"""

from fastapi import Header, Request
from pydantic import BaseModel, ConfigDict, Field

from deixis.workflow.features.tables.tables import TableStore


class ColumnVersion(BaseModel):
    model_config = ConfigDict(extra="forbid")
    expected_version: int = Field(ge=1, strict=True)  # the column's version


def register_table_routes(app):
    column_path = "/api/researches/{research_id}/tables/{table_id}/columns/{column_id}"

    @app.post(column_path + "/recheck", status_code=202)
    async def recheck_column(research_id: str, table_id: str, column_id: str, body: ColumnVersion, request: Request,
                             idempotency_key: str | None = Header(default=None, max_length=200)):
        run = TableStore(request.app.state.store).request_column_recheck(research_id, table_id, column_id,
                                                                         body.expected_version, idempotency_key)
        request.app.state.worker.wake()
        return run
