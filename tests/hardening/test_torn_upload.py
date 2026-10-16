"""P9 H7 item 01 (D165): an upload does not trust a torn file an older version left under the hash name. SYNTHETIC."""

from fastapi.testclient import TestClient

from test_api_flow import app_for, create, session


# ---- item 01: an upload does not trust a torn file an older version left under the hash name ------------------------

def test_uploading_a_pdf_replaces_a_torn_file_under_its_hash_name(tmp_path):
    import hashlib

    from deixis.storage.backup import create_backup
    from helpers import make_pdf
    from test_api_flow import sw_settings

    data = make_pdf(["SYNTHETIC molecule text one", "SYNTHETIC molecule text two"])
    sha = hashlib.sha256(data).hexdigest()
    settings = sw_settings(tmp_path)
    settings.papers_dir.mkdir(parents=True, exist_ok=True)
    torn = settings.papers_dir / f"{sha}.pdf"
    torn.write_bytes(data[: len(data) // 2])  # what the pre-D162 download write could leave behind
    with TestClient(app_for(tmp_path)) as client:
        session(client)
        rid = create(client, source_scope="attached")
        response = client.post(f"/api/researches/{rid}/uploads", files={"file": ("a.pdf", data, "application/pdf")})
        assert response.status_code == 201, response.text
        asset = response.json()["sources"][0]["access"]["assets"][0]
        assert asset["extraction_status"] == "succeeded"
    assert torn.read_bytes() == data  # the file under the name now is the file the row's hash names
    assert not list(settings.papers_dir.glob("*.partial"))
    folder = create_backup(settings, tmp_path / "backup")  # refuses a file that does not match its recorded hash
    assert (folder / "manifest.json").exists()


def test_uploading_the_same_pdf_twice_keeps_the_one_whole_file(tmp_path):
    from helpers import make_pdf

    data = make_pdf(["SYNTHETIC molecule text"])
    with TestClient(app_for(tmp_path)) as client:
        session(client)
        rid = create(client, source_scope="attached")
        assert client.post(f"/api/researches/{rid}/uploads", files={"file": ("a.pdf", data, "application/pdf")}).status_code == 201
        before = [(p.name, p.stat().st_mtime_ns) for p in (tmp_path / "data" / "papers").iterdir()]
        rid2 = create(client, source_scope="attached")
        assert client.post(f"/api/researches/{rid2}/uploads", files={"file": ("a.pdf", data, "application/pdf")}).status_code == 201
        assert [(p.name, p.stat().st_mtime_ns) for p in (tmp_path / "data" / "papers").iterdir()] == before
