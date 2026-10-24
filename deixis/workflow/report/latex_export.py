"""Read one report snapshot and package the pure LaTeX writer's bytes."""

from __future__ import annotations

import io
import json
import zipfile

from deixis.workflow.report import export_text
from deixis.workflow.report.latex import LatexBundle, to_latex
from deixis.workflow.store import NotFound, Store

MEDIA_TYPE = "application/zip"


def read_bib_sources(store: Store, view: dict) -> list[dict]:
    """Stored version metadata, in reference order, without enrichment."""
    sources = []
    for reference in view["references"]:
        row = store.conn.execute(
            "SELECT id, title, authors_json, year, venue, publication_type, doi, landing_url,"
            " version_label, volume, issue, pages FROM source_versions WHERE id = ?",
            (reference["source_version_id"],),
        ).fetchone()
        if row is None:
            continue
        arxiv = store.conn.execute(
            "SELECT value FROM identifier_mappings WHERE source_version_id = ? AND scheme = 'arxiv'"
            " ORDER BY id LIMIT 1", (row["id"],),
        ).fetchone()
        sources.append({
            "source_version_id": row["id"], "authors": json.loads(row["authors_json"]),
            **{key: row[key] for key in ("title", "year", "venue", "publication_type", "doi", "landing_url",
                                        "version_label", "volume", "issue", "pages")},
            "arxiv_id": arxiv["value"] if arxiv else None,
        })
    return sources


def build_zip(bundle: LatexBundle) -> bytes:
    """Exactly two UTF-8 members with fixed metadata and no text rewriting."""
    output = io.BytesIO()
    with zipfile.ZipFile(output, "w") as archive:
        for extension, text in (("tex", bundle.tex), ("bib", bundle.bib)):
            info = zipfile.ZipInfo(f"{bundle.stem}.{extension}", date_time=(1980, 1, 1, 0, 0, 0))
            info.compress_type = zipfile.ZIP_DEFLATED
            info.create_system = 3
            info.external_attr = 0o644 << 16
            archive.writestr(info, text.encode("utf-8"))
    return output.getvalue()


def export_latex(store: Store, research_id: str, report_id: str) -> tuple[bytes, str, int]:
    from deixis.workflow import queue
    from deixis.workflow.report.store import ReportStore
    from deixis.workflow.views import report_view

    with queue._snapshot(store.conn):
        view = report_view(store, research_id, report_id)
        export_text.ensure_report_finished(view)
        title = store.research(research_id)["title"]
        try:
            corpus = ReportStore(store).snapshot(report_id)["corpus"]
        except NotFound:
            corpus = None
        bib_sources = read_bib_sources(store, view)
    bundle = to_latex(view, title=title, corpus=corpus, bib_sources=bib_sources)
    return build_zip(bundle), bundle.stem + "-latex.zip", bundle.note_count
