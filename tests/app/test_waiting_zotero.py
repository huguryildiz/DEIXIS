"""Zotero for the works waiting for the person's PDF: found by DOI or title, read for a match, never attached here.

Zotero itself is mocked (`find_pdf`, `pdf_bytes`); records and files are SYNTHETIC. Passing shows the routes list the
waiting works' library copies and hand the file back unstored; it says nothing about a live Zotero library.
"""

from deixis.providers import zotero
from helpers import make_pdf
from test_waiting_flow import settled_runs, sw_research

PDF = make_pdf(["SYNTHETIC library copy of a waiting work."])


def test_waiting_works_are_matched_in_zotero_and_the_file_is_read_without_being_attached(tmp_path, monkeypatch):
    asked = []

    async def find_pdf(client, lib, doi, title):
        asked.append(doi)
        if doi == "10.1/oa.2":
            return zotero.ZoteroItem(None, pdf_key="PDFA1234", pdf_filename="w2.pdf")
        if doi == "10.1/oa.3":
            return zotero.ZoteroItem(None, pdf_problem="the item has no PDF")
        return None

    async def pdf_bytes(client, lib, key, fetch_pdf):
        assert key == "PDFA1234"
        return PDF

    monkeypatch.setattr(zotero, "find_pdf", find_pdf)
    monkeypatch.setattr(zotero, "pdf_bytes", pdf_bytes)
    app, client, rid = sw_research(tmp_path, monkeypatch)
    try:
        settled_runs(client, rid)
        before = client.get(f"/api/researches/{rid}/waiting").json()
        found = client.post(f"/api/researches/{rid}/waiting/zotero", json={"source": "local"})
        file = client.get("/api/zotero/attachments/PDFA1234/file", params={"source": "local"})
        bad_key = client.get("/api/zotero/attachments/..%2Fx/file")
        after = client.get(f"/api/researches/{rid}/waiting").json()
    finally:
        client.__exit__(None, None, None)
    assert found.status_code == 200, found.text
    body = found.json()
    w2 = next(r for r in before["rows"] if r["doi"] == "10.1/oa.2")
    assert body["checked"] == before["count"] == 3 and sorted(asked) == ["10.1/oa.2", "10.1/oa.3", "10.1/oa.4"]
    assert body["found"] == [{"work_id": w2["work_id"], "title": w2["title"], "key": "PDFA1234", "filename": "w2.pdf"}]
    assert [n["note"] for n in body["notes"]] == ["the item has no PDF"]
    assert file.status_code == 200 and file.content == PDF and file.headers["content-type"] == "application/pdf"
    assert bad_key.status_code in (404, 422)
    assert after["count"] == 3  # nothing was attached: the person still confirms the version
