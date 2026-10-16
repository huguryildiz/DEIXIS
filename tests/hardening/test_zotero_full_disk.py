"""P9 H7 item 03 (D165): a full disk while a Zotero route writes a PDF or its payload answers 507. SYNTHETIC, no network."""

from fastapi.testclient import TestClient


# ---- item 03: a full disk while a Zotero route writes a PDF or its payload answers 507, not a bare 500 ----------------

def zotero_import_with(tmp_path, monkeypatch, patch):
    import errno
    import test_zotero as z

    path = tmp_path / "PDFA1234 file.pdf"
    path.write_bytes(z.make_pdf(["SYNTHETIC text of PDFA1234"]))
    patch(monkeypatch, errno)
    with TestClient(z.app_for(tmp_path, z.zotero_client({"PDFA1234": path.as_uri()}, [])), raise_server_exceptions=False) as client:
        rid = z.start(client)
        return client.post(f"/api/researches/{rid}/zotero-imports", json={"source": "local", "collection_key": z.COLLECTION})


def test_zotero_import_on_a_full_disk_refuses_with_the_disk_full_sentence_when_the_pdf_cannot_be_stored(tmp_path, monkeypatch):
    from deixis.documents import pdf_files

    def full(path, data):
        raise OSError(28, "No space left on device")

    response = zotero_import_with(tmp_path, monkeypatch, lambda mp, errno: mp.setattr(pdf_files, "stage_bytes", full))
    assert response.status_code == 507, response.text
    assert response.json()["code"] == "disk_full" and "disk is full" in response.json()["detail"]


def test_zotero_import_on_a_full_disk_refuses_with_the_disk_full_sentence_when_the_payload_cannot_be_written(tmp_path, monkeypatch):
    from pathlib import Path as P

    real = P.write_text

    def full(self, *args, **kwargs):
        if self.suffix == ".json" and "provider-payloads" in str(self):
            raise OSError(28, "No space left on device")
        return real(self, *args, **kwargs)

    response = zotero_import_with(tmp_path, monkeypatch, lambda mp, errno: mp.setattr(P, "write_text", full))
    assert response.status_code == 507 and response.json()["code"] == "disk_full"


def test_an_unrelated_oserror_in_that_route_is_not_taken_for_a_full_disk(tmp_path, monkeypatch):
    from deixis.documents import pdf_files

    def broken(path, data):
        raise OSError(13, "Permission denied")

    response = zotero_import_with(tmp_path, monkeypatch, lambda mp, errno: mp.setattr(pdf_files, "stage_bytes", broken))
    assert response.status_code == 500


def test_every_pdf_write_in_the_api_is_inside_disk_full_refused():
    """Covers the second Zotero route (`zotero-pdfs`), which has the same write as the import and no test of its own."""
    import ast
    from pathlib import Path as P

    tree = ast.parse((P(__file__).parents[2] / "backend" / "deixis" / "api" / "app.py").read_text())
    parents = {child: node for node in ast.walk(tree) for child in ast.iter_child_nodes(node)}
    calls = [n for n in ast.walk(tree) if isinstance(n, ast.Call) and isinstance(n.func, ast.Attribute) and n.func.attr == "store_pdf_file"]
    assert len(calls) == 2

    def guarded(node):
        while node in parents:
            node = parents[node]
            if isinstance(node, ast.With) and any(isinstance(i.context_expr, ast.Call) and getattr(i.context_expr.func, "id", "") == "disk_full_refused"
                                                  for i in node.items):
                return True
        return False

    assert all(guarded(call) for call in calls)
