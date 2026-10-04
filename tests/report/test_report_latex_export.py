"""SYNTHETIC real-flow and packaging checks; no TeX or external calls."""

import ast
from copy import deepcopy
import io
import json
from pathlib import Path
import re
import zipfile

import pytest
from fastapi.testclient import TestClient

from deixis.domain.rules import RevisionConflict
from deixis.workflow import queue, views
from deixis.workflow.report import latex_export
from deixis.workflow.report.export import export_markdown
from deixis.workflow.report.latex import LatexBundle, to_latex
from deixis.workflow.report.store import ReportStore
from test_api_flow import app_for, create, session
from test_report_api import upload_and_include, create_table, fill_table
from test_report_export import complete
from test_report_flow import ReportAdapter


def assert_error(response, status, detail=None):
    assert response.status_code == status
    assert "detail" in response.json()
    assert response.json()["detail"]
    if detail is not None:
        assert response.json()["detail"] == detail
    assert "content-disposition" not in response.headers
    assert "x-deixis-export-notes" not in response.headers
    assert response.headers["content-type"] != "application/zip"


def opened(data, stem):
    with zipfile.ZipFile(io.BytesIO(data)) as archive:
        assert archive.namelist() == [stem + ".tex", stem + ".bib"]
        assert archive.testzip() is None
        return tuple(archive.read(name) for name in archive.namelist())


def assert_notes(response, tex):
    header = response.headers["x-deixis-export-notes"]
    assert re.fullmatch(r"[0-9]+", header)
    number = int(header)
    announced = re.search(r"^% Export notes: (none|[0-9]+)$", tex, re.M).group(1)
    assert number == (0 if announced == "none" else int(announced))
    numbered = re.findall(r"^% [0-9]+\. ", tex, re.M)
    more = re.search(r"^% and ([0-9]+) more$", tex, re.M)
    assert number == len(numbered) + (int(more.group(1)) if more else 0)
    return number


def counts(store):
    return store.conn.total_changes, tuple(store.conn.execute(f"SELECT COUNT(*) FROM {name}").fetchone()[0]
                                           for name in ("source_versions", "works", "reports", "runs"))


@pytest.fixture
def finished(tmp_path):
    store, reports, rid, report_id = complete(tmp_path)
    try:
        yield store, reports, rid, report_id
    finally:
        store.conn.close()


def test_finished_route_zip_content_and_unchanged_markdown(tmp_path):
    with TestClient(app_for(tmp_path, ReportAdapter())) as raw:
        client = session(raw)
        rid = create(client, source_scope="attached", effort="quick")
        upload_and_include(client, rid)
        table = create_table(client, rid, with_columns=True)
        fill_table(client, rid, table)
        started = client.post(f"/api/researches/{rid}/reports", json={"table_id": table["table"]["id"]})
        report_id = started.json()["target"]["report_id"]
        from test_api_flow import wait_run
        _, run = wait_run(client, rid, started.json()["id"])
        assert run["status"] == "completed"
        store = raw.app.state.store
        path = f"/api/researches/{rid}/reports/{report_id}"
        view = client.get(path).json()
        before = counts(store)
        response = client.get(path + "/export?format=latex")
        assert response.status_code == 200, response.text
        assert response.headers["content-type"] == latex_export.MEDIA_TYPE == "application/zip"
        name = re.fullmatch(r'attachment; filename="(report-[a-z0-9-]+-v[0-9]+-latex\.zip)"',
                            response.headers["content-disposition"]).group(1)
        stem = name.removesuffix("-latex.zip")
        tex_bytes, bib_bytes = opened(response.content, stem)
        tex, bib = tex_bytes.decode("utf-8"), bib_bytes.decode("utf-8")
        assert tex.startswith("% DEIXIS evidence report, IEEEtran export for XeLaTeX.\n")
        assert next(line for line in tex.splitlines() if line and not line.startswith("%")) == r"\documentclass[journal]{IEEEtran}"
        assert rf"\bibliography{{{stem}}}" in tex
        assert store.research(rid)["title"] in tex
        assert all(token not in tex for token in ("claim_key", "psg_", "cel_", "support_type"))
        cited = list(dict.fromkeys(key for group in re.findall(r"\\cite\{([^}]+)\}", tex) for key in group.split(",")))
        bib_keys = re.findall(r"^@\w+\{([^,]+),", bib, re.M)
        assert cited == [ref["source_key"] for ref in view["references"]]
        assert set(cited) == set(bib_keys)
        assert len(bib_keys) == len(view["references"])
        assert assert_notes(response, tex) == 0
        assert client.get(path + "/export?format=latex").content == response.content
        assert latex_export.export_latex(store, rid, report_id) == (response.content, name, 0)
        with queue._snapshot(store.conn):
            snapshot_view = views.report_view(store, rid, report_id)
            title = store.research(rid)["title"]
            corpus = ReportStore(store).snapshot(report_id)["corpus"]
            sources = latex_export.read_bib_sources(store, snapshot_view)
        bundle = to_latex(snapshot_view, title=title, corpus=corpus, bib_sources=sources)
        assert tex_bytes == bundle.tex.encode("utf-8")
        assert bib_bytes == bundle.bib.encode("utf-8")
        assert counts(store) == before
        md = client.get(path + "/export?format=markdown")
        default = client.get(path + "/export")
        assert md.status_code == default.status_code == 200
        assert md.content == default.content
        for result in (md, default):
            assert result.headers["content-type"] == "text/markdown; charset=utf-8"
            assert result.headers["content-disposition"].endswith('.md"')
            assert "x-deixis-export-notes" not in result.headers
        text, md_name = export_markdown(store, rid, report_id)
        assert md.content == text.encode("utf-8")
        assert md.headers["content-disposition"] == f'attachment; filename="{md_name}"'
        assert_error(client.get(path + "/export?format=pdf"), 422)
        # A missing D59 key is injected in the synthetic database to exercise a real note.
        store.conn.execute("UPDATE works SET source_key = NULL WHERE id = (SELECT work_id FROM source_versions WHERE id = ?)",
                           (view["references"][0]["source_version_id"],))
        noted = client.get(path + "/export?format=latex")
        assert noted.status_code == 200
        assert assert_notes(noted, opened(noted.content, stem)[0].decode("utf-8")) > 0
        # Missing source_versions is intentionally corrupt test data, not a user operation.
        version = view["references"][0]["source_version_id"]
        previous_fk = store.conn.execute("PRAGMA foreign_keys").fetchone()[0]
        try:
            store.conn.execute("PRAGMA foreign_keys = OFF")
            store.conn.execute("DELETE FROM source_versions WHERE id = ?", (version,))
        finally:
            store.conn.execute(f"PRAGMA foreign_keys = {previous_fk}")
        before = counts(store)
        with pytest.raises(RevisionConflict) as error:
            latex_export.export_latex(store, rid, report_id)
        assert_error(client.get(path + "/export?format=latex"), 409, str(error.value))
        assert counts(store) == before


@pytest.mark.parametrize("status", ["failed", "cancelled"])
def test_draft_gates_and_unknown_ids(tmp_path, status):
    with TestClient(app_for(tmp_path, ReportAdapter())) as raw:
        client = session(raw)
        other = create(client, source_scope="attached")
        rid = create(client, source_scope="attached")
        store = raw.app.state.store
        run = store.create_run(rid, "report", {"max_model_calls": 1, "max_provider_requests": 0}, None,
                               {"table_id": "tbl_synthetic"})
        reports = ReportStore(store)
        report_id = reports.create_report(rid, run["id"], run["scope_revision"], "en")
        path = f"/api/researches/{rid}/reports/{report_id}/export?format=latex"
        assert_error(client.get(path), 409, "The report is still being written")
        reports.create_section(report_id, "abstract", 0)
        reports.finalize(report_id, "draft")
        store.update_run(run["id"], status="paused")
        assert_error(client.get(path), 409, "The report is still being written")
        store.update_run(run["id"], status=status)
        result = client.get(path)
        assert result.status_code == 200
        name = re.fullmatch(r'attachment; filename="(report-[a-z0-9-]+-draft-latex\.zip)"',
                            result.headers["content-disposition"]).group(1)
        tex, bib = opened(result.content, name.removesuffix("-latex.zip"))
        assert "DRAFT: 1 sections not validated." in tex.decode("utf-8")
        assert bib == b""
        for research, report in ((other, report_id), (rid, "rpt_unknown000"), ("res_unknown000", report_id)):
            assert_error(client.get(f"/api/researches/{research}/reports/{report}/export?format=latex"), 404)


def test_bib_sources_uses_stored_rows_in_reference_order(finished):
    store, _, _, _ = finished
    first = store.create_upload_source("SYNTHETIC stored first")
    second = store.create_upload_source("SYNTHETIC stored second")
    gone = store.create_upload_source("SYNTHETIC deleted version")
    previous_fk = store.conn.execute("PRAGMA foreign_keys").fetchone()[0]
    try:
        store.conn.execute("PRAGMA foreign_keys = OFF")
        store.conn.execute("DELETE FROM source_versions WHERE id = ?", (gone,))
    finally:
        store.conn.execute(f"PRAGMA foreign_keys = {previous_fk}")
    store.conn.execute("UPDATE source_versions SET authors_json = ?, volume = ?, issue = ?, pages = ? WHERE id = ?",
                       ('["Stored Author"]', "7", "8", "9--10", first))
    for value in ("2601.00002", "2601.00001"):
        store.conn.execute("INSERT INTO identifier_mappings (source_version_id, scheme, value, provider, retrieved_at)"
                           " VALUES (?, 'arxiv', ?, 'synthetic', '2026-10-02')", (first, value))
    view = {"references": [{"source_version_id": second, "title": "Wrong view title", "authors": ["Wrong"]},
                           {"source_version_id": first}, {"source_version_id": gone}]}
    original = deepcopy(view)
    before = counts(store)
    rows = latex_export.read_bib_sources(store, view)
    assert [row["source_version_id"] for row in rows] == [second, first]
    assert rows[0]["arxiv_id"] is None and rows[1]["arxiv_id"] == "2601.00002"
    assert rows[1]["authors"] == ["Stored Author"] and isinstance(rows[0]["authors"], list)
    assert (rows[1]["volume"], rows[1]["issue"], rows[1]["pages"]) == ("7", "8", "9--10")
    fields = {"source_version_id", "title", "authors", "year", "venue", "publication_type", "doi", "landing_url",
              "version_label", "volume", "issue", "pages", "arxiv_id"}
    for row in rows:
        assert set(row) == fields
        stored = store.conn.execute("SELECT * FROM source_versions WHERE id = ?", (row["source_version_id"],)).fetchone()
        assert row["authors"] == json.loads(stored["authors_json"])
        for key in fields - {"source_version_id", "authors", "arxiv_id"}:
            assert row[key] == stored[key]
    assert view == original and counts(store) == before


def test_one_read_transaction_trace(finished):
    store, _, rid, report = finished
    statements = []
    assert store.conn.in_transaction is False
    store.conn.set_trace_callback(statements.append)
    try:
        latex_export.export_latex(store, rid, report)
    finally:
        store.conn.set_trace_callback(None)
    commands = [statement.strip().upper() for statement in statements]
    assert commands.count("BEGIN") == commands.count("COMMIT") == 1
    start, end = commands.index("BEGIN"), commands.index("COMMIT")
    assert any(command.startswith("SELECT") for command in commands)
    assert all(start < i < end for i, command in enumerate(commands) if command.startswith("SELECT"))
    assert not any(command.startswith(("INSERT", "UPDATE", "DELETE", "REPLACE")) for command in commands)
    assert store.conn.in_transaction is False


def test_reads_are_inside_snapshot_and_render_is_outside(finished, monkeypatch):
    store, _, rid, report = finished
    observed = []
    for module, name in ((views, "report_view"), (latex_export, "read_bib_sources"), (latex_export, "to_latex"),
                         (latex_export, "build_zip")):
        original = getattr(module, name)
        def spy(*args, _original=original, _name=name, **kwargs):
            observed.append((_name, store.conn.in_transaction))
            return _original(*args, **kwargs)
        monkeypatch.setattr(module, name, spy)
    assert store.conn.in_transaction is False
    latex_export.export_latex(store, rid, report)
    assert observed == [("report_view", True), ("read_bib_sources", True), ("to_latex", False), ("build_zip", False)]
    # isolation_level=None: a bare SELECT cannot satisfy the True assertions.
    # Moving either reader outside _snapshot therefore fails this test.
    assert store.conn.in_transaction is False


def test_export_preserves_callers_open_transaction(finished):
    store, _, rid, report = finished
    statements = []
    store.conn.execute("BEGIN")
    store.conn.set_trace_callback(statements.append)
    try:
        latex_export.export_latex(store, rid, report)
        assert store.conn.in_transaction is True
        assert not any(s.strip().upper().startswith(("BEGIN", "COMMIT", "ROLLBACK")) for s in statements)
    finally:
        store.conn.set_trace_callback(None)
        store.conn.execute("ROLLBACK")


@pytest.mark.parametrize("tex,bib", [("Türkçe α\n", "@misc{A, title={İ}}\n"), ("Türkçe α", ""), ("line\n", "end")])
def test_build_zip_exact_encodings_and_metadata(tex, bib):
    bundle = LatexBundle("report-synthetic-v1", tex, bib, ())
    data = latex_export.build_zip(bundle)
    assert data == latex_export.build_zip(bundle)
    assert opened(data, bundle.stem) == (bundle.tex.encode("utf-8"), bundle.bib.encode("utf-8"))
    with zipfile.ZipFile(io.BytesIO(data)) as archive:
        assert archive.comment == b""
        for entry in archive.infolist():
            assert entry.date_time == (1980, 1, 1, 0, 0, 0)
            assert entry.compress_type == zipfile.ZIP_DEFLATED
            assert entry.create_system == 3
            assert entry.external_attr == 0o644 << 16
            assert not entry.is_dir()


def test_import_boundary():
    tree = ast.parse(Path(latex_export.__file__).read_text())
    allowed = {"__future__", "io", "json", "zipfile", "deixis.domain.rules", "deixis.workflow.report",
               "deixis.workflow.report.latex", "deixis.workflow.store", "deixis.workflow",
               "deixis.workflow.report.store", "deixis.workflow.views"}
    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            assert all(alias.name in allowed for alias in node.names)
        if isinstance(node, ast.ImportFrom):
            assert node.module in allowed
            assert not (node.module == "deixis.workflow.report" and any(a.name == "export" for a in node.names))
