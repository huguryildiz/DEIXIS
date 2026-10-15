"""DOCX and XLSX downloads of the answer report, the evidence table and the evidence report.

GET routes like the other downloads: the host and origin checks of the app middleware apply, there is nothing to
CSRF-protect, and an unknown or foreign id answers 404 before any file is written. `lang` and `style` carry the
interface language and citation style the browser uses for its own Markdown and CSV, so both files read the same.
"""

from typing import Any, Literal

from fastapi import HTTPException, Request, Response

from deixis.domain.rules import RevisionConflict
from deixis.exports import answer as answer_export
from deixis.exports import ooxml
from deixis.exports import report as report_export
from deixis.exports import table as table_export
from deixis.exports.text import attachment
from deixis.workflow.store import NotFound
from deixis.workflow.tables import TableStore
from deixis.workflow.views import research_view


def _download(data: bytes, media_type: str, name: str) -> Response:
    return Response(data, media_type=media_type, headers={"Content-Disposition": attachment(name)})


def _report_title(view: dict[str, Any], answer: dict[str, Any]) -> str:
    # ResearchView.tsx: the saved report title, else the question when it starts with the research title.
    question, title = view["scope"]["question"], view["research"]["title"]
    saved = answer.get("report_title")
    return saved if saved is not None else question if question.startswith(title) else title


def register_export_routes(app) -> None:
    @app.get("/api/researches/{research_id}/answers/{answer_id}/export/docx")
    async def export_answer_docx(research_id: str, answer_id: str, request: Request,
                                 lang: Literal["en", "tr"] = "en",
                                 style: Literal["apa", "ieee", "mla", "chicago"] = "apa") -> Response:
        view = research_view(request.app.state.store, research_id)
        answer = next((item for item in view["answers"] if item["id"] == answer_id), None)
        if answer is None:
            raise NotFound(answer_id)
        if answer["status"] != "structurally_valid":
            raise RevisionConflict("Only a source-linked answer can be exported")
        title = _report_title(view, answer)
        version = answer["report_version"] if answer.get("report_version") is not None else 0
        blocks = answer_export.blocks(answer, view["sources"], title=title, version=version, language=lang, style=style)
        return _download(ooxml.docx(blocks, title=title), ooxml.DOCX_MEDIA_TYPE, answer_export.filename(title, version))

    @app.get("/api/researches/{research_id}/tables/{table_id}/export/{fmt}")
    async def export_table(research_id: str, table_id: str, fmt: Literal["xlsx", "docx"], request: Request,
                           lang: Literal["en", "tr"] = "en",
                           style: Literal["apa", "ieee", "mla", "chicago"] = "apa") -> Response:
        store = request.app.state.store
        table = TableStore(store).table_view(research_id, table_id)
        if not table["columns"] or not table["rows"]:
            raise HTTPException(422, "The table has no columns or no rows to export")
        research = research_view(store, research_id)
        sources, research_title = research["sources"], research["research"]["title"]
        if fmt == "xlsx":
            data, media = table_export.xlsx(table, sources, language=lang, style=style), ooxml.XLSX_MEDIA_TYPE
        else:
            data = table_export.docx(table, sources, language=lang, style=style, research_title=research_title)
            media = ooxml.DOCX_MEDIA_TYPE
        return _download(data, media, table_export.filename(table, fmt, research_title=research_title, language=lang))

    @app.get("/api/researches/{research_id}/reports/{report_id}/export/docx")
    async def export_report_docx(research_id: str, report_id: str, request: Request) -> Response:
        data, name = report_export.export_docx(request.app.state.store, research_id, report_id)
        return _download(data, ooxml.DOCX_MEDIA_TYPE, name)
