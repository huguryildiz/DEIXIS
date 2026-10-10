"""RR-A request-time disk failures, synthetic data and scripted transports only."""

import ast
import tempfile
from pathlib import Path
from types import SimpleNamespace

import httpx
import pytest
from fastapi.testclient import TestClient

from deixis.api.app import create_app
from deixis.documents import pdf
from deixis.providers import zotero
from fakes import FakeAdapter
from helpers import make_pdf
from test_api_flow import create, session, sw_settings
from test_asset_replacement import extraction
import test_zotero as z


def app_for(base, http=None):
    def refuse(request):
        raise AssertionError(f"unexpected outbound request: {request.url}")

    return create_app(sw_settings(base), adapters={"fake": FakeAdapter()}, start_worker=False,
                      http_client=http or httpx.AsyncClient(transport=httpx.MockTransport(refuse)),
                      extra_hosts=("testserver",), trusted_clients=("testclient",))


def route_first(app):
    """Put the route just added ahead of the static mount at "/", which create_app adds only when apps/web/dist exists."""
    app.router.routes.insert(0, app.router.routes.pop())


@pytest.mark.parametrize("error_number,status", [(28, 507), (13, 400)])
def test_multipart_spool_failure(tmp_path, monkeypatch, error_number, status):
    app = app_for(tmp_path)
    with TestClient(app, raise_server_exceptions=False) as client:
        session(client)
        rid = create(client, source_scope="attached")

        def fail(self):
            raise OSError(error_number, "SYNTHETIC spool unavailable")

        monkeypatch.setattr(tempfile.SpooledTemporaryFile, "rollover", fail)
        response = client.post(f"/api/researches/{rid}/uploads", files={
            "file": ("big.pdf", b"%PDF-1.7\n" + b"x" * (2 * 1024 * 1024), "application/pdf")})
        assert response.status_code == status, response.text
        if status == 507:
            assert response.json()["code"] == "disk_full"
        else:
            assert response.json() == {"detail": "There was an error parsing the body"}


def test_http_defaults_keep_status_detail_headers_and_validation(tmp_path):
    from fastapi import HTTPException

    app = app_for(tmp_path)

    @app.get("/api/synthetic-http-error")
    def synthetic_error():
        raise HTTPException(404, "SYNTHETIC missing", headers={"x-synthetic": "retained"})

    route_first(app)

    with TestClient(app) as client:
        session(client)
        response = client.get("/api/synthetic-http-error")
        assert response.status_code == 404
        assert response.json() == {"detail": "SYNTHETIC missing"}
        assert response.headers["x-synthetic"] == "retained"
        rid = create(client, source_scope="attached")
        invalid = client.post(f"/api/researches/{rid}/uploads")
        assert invalid.status_code == 422
        assert invalid.json()["detail"][0]["loc"] == ["body", "file"]


def test_an_http_error_with_a_disk_cause_outside_body_parsing_is_left_as_it_was(tmp_path):
    from fastapi import HTTPException

    app = app_for(tmp_path)

    @app.get("/api/synthetic-http-disk-cause")
    def synthetic_error():
        try:
            raise OSError(28, "SYNTHETIC no space")
        except OSError as exc:
            raise HTTPException(503, "SYNTHETIC own sentence", headers={"x-synthetic": "kept"}) from exc

    route_first(app)

    with TestClient(app) as client:
        session(client)
        response = client.get("/api/synthetic-http-disk-cause")
        assert response.status_code == 503 and response.json() == {"detail": "SYNTHETIC own sentence"}
        assert response.headers["x-synthetic"] == "kept"


SITES = ["upload", "upload_to_source", "match_uploads", "match_waiting", "attach_waiting_pdf",
         "zotero_import_payload", "zotero_import_papers", "zotero_pdfs", "replace_asset"]


@pytest.mark.parametrize("site", SITES)
@pytest.mark.parametrize("error_number,status", [(28, 507), (13, 500)])
def test_request_directory_failure_at_each_site(tmp_path, monkeypatch, site, error_number, status):
    data = make_pdf(["SYNTHETIC upload text"])
    local_pdf = tmp_path / "synthetic-zotero.pdf"
    local_pdf.write_bytes(data)
    http = z.zotero_client({"PDFA1234": local_pdf.as_uri()}, []) if site.startswith("zotero_import") else None
    app = app_for(tmp_path, http)
    settings = sw_settings(tmp_path)
    target = settings.payloads_dir if site == "zotero_import_payload" else settings.papers_dir
    with TestClient(app, raise_server_exceptions=False) as client:
        session(client)
        rid = create(client, source_scope="attached")
        store = app.state.store
        svid = store.create_upload_source("SYNTHETIC source")
        store.add_to_corpus(rid, svid, "user_upload", selection_state="included", selection_origin="user")
        if site == "replace_asset":
            aid = store.add_asset_with_pages(svid, "a" * 64, 1, "synthetic.pdf", "user_upload", None,
                                             "synthetic.pdf", extraction(["SYNTHETIC old"]), pdf.EXTRACTION_VERSION, pdf.chunk_page)
        if site == "zotero_pdfs":
            async def find(*args):
                return SimpleNamespace(pdf_key="PDFA1234", pdf_filename="synthetic.pdf")

            async def pdf_bytes(*args):
                return data

            monkeypatch.setattr(zotero, "find_pdf", find)
            monkeypatch.setattr(zotero, "pdf_bytes", pdf_bytes)
        assert not target.exists(), "the fault must be directory creation, not an existing-folder path"
        real_mkdir = Path.mkdir
        reached = []

        def fail(self, *args, **kwargs):
            if self == target:
                assert not self.exists()
                reached.append(self)
                raise OSError(error_number, "SYNTHETIC directory unavailable")
            return real_mkdir(self, *args, **kwargs)

        monkeypatch.setattr(Path, "mkdir", fail)
        base = f"/api/researches/{rid}"
        files = {"file": ("synthetic.pdf", data, "application/pdf")}
        if site == "upload":
            response = client.post(base + "/uploads", files=files)
        elif site == "upload_to_source":
            response = client.post(base + f"/sources/{svid}/uploads", files=files)
        elif site in ("match_uploads", "match_waiting"):
            response = client.post(base + "/uploads/match", files={"files": files["file"]})
        elif site == "attach_waiting_pdf":
            response = client.post(base + "/waiting/uploads", files=files, data={
                "work_id": store.source(svid)["work_id"], "source_version_id": svid,
                "scope_revision": store.research(rid)["current_scope_revision"],
                "versions_digest": "SYNTHETIC", "sha256": "a" * 64})
        elif site.startswith("zotero_import"):
            response = client.post(base + "/zotero-imports", json={"source": "local", "collection_key": z.COLLECTION})
        elif site == "zotero_pdfs":
            response = client.post(base + "/zotero-pdfs", json={"source": "local"})
        else:
            response = client.put(base + f"/sources/{svid}/assets/{aid}", files=files)
        assert reached == [target], response.text
        assert response.status_code == status, response.text
        if status == 507:
            assert response.json()["code"] == "disk_full"


def test_every_request_directory_call_is_guarded():
    tree = ast.parse((Path(__file__).parents[2] / "backend/deixis/api/app.py").read_text())
    parents = {child: node for node in ast.walk(tree) for child in ast.iter_child_nodes(node)}
    calls = [node for node in ast.walk(tree) if isinstance(node, ast.Call)
             and isinstance(node.func, ast.Attribute) and node.func.attr == "mkdir"
             and isinstance(node.func.value, ast.Attribute) and node.func.value.attr in ("papers_dir", "payloads_dir")]
    assert len(calls) == 8  # No startup/lifespan calls use these two attributes in this checkout.
    unguarded = []
    for call in calls:
        node, guarded, function = call, False, None
        while node in parents:
            node = parents[node]
            if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)) and function is None:
                function = node.name
            if isinstance(node, ast.With) and any(isinstance(item.context_expr, ast.Call)
                                                 and getattr(item.context_expr.func, "id", "") == "disk_full_refused"
                                                 for item in node.items):
                guarded = True
        if not guarded:
            unguarded.append((function, call.lineno))
    assert unguarded == []
