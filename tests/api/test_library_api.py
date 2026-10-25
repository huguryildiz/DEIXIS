"""The library: CSRF on writes, saving sets, PDF upload checks, bibliography export, new research from a set, and the
BibTeX/RIS reader.

FakeAdapter, mocked HTTP and SYNTHETIC files. Passing shows route behaviour and parser bounds, not live lookups.
"""

import pytest
from fastapi.testclient import TestClient
from pathlib import Path

from deixis.imports import bibtex_ris as b
from deixis.storage.db import transaction
from helpers import make_pdf
from test_api_flow import app_for
from test_api_flow import create
from test_api_flow import session
from test_library import seed_work


MODEL = {"question": "SYNTHETIC: how are packet sizes chosen?", "model_connection": "fake",
         "requested_model": "fake-model", "effort": "quick"}


def pdf_file(name="paper.pdf", text="SYNTHETIC packet study."):
    return {"file": (name, make_pdf([text]), "application/pdf")}


@pytest.mark.parametrize("path, kwargs", [
    ("/api/library/items", {"json": {"source_version_ids": ["srv_x"]}}),
])
def test_every_library_write_needs_the_csrf_token(tmp_path, path, kwargs):
    app = app_for(tmp_path)
    with TestClient(app) as raw:
        session(raw)
        assert raw.post(path, headers={"x-deixis-csrf": "wrong"}, **kwargs).status_code == 403
        assert app.state.store.conn.execute("SELECT COUNT(*) FROM researches").fetchone()[0] == 0


def test_library_upload_refuses_a_non_pdf_and_reuses_the_same_file(tmp_path):
    app = app_for(tmp_path)
    with TestClient(app) as raw:
        client = session(raw)
        refused = client.post("/api/library/uploads", files={"file": ("notes.txt", b"SYNTHETIC plain text", "text/plain")})
        assert refused.status_code == 422 and refused.json()["code"] == "upload_not_pdf"
        first = client.post("/api/library/uploads", files=pdf_file("same.pdf"))
        assert first.status_code == 201, first.text
        assert first.json()["already_saved"] is False
        second = client.post("/api/library/uploads", files=pdf_file("same-again.pdf"))
        assert second.json()["source_version_id"] == first.json()["source_version_id"]
        assert second.json()["already_saved"] is True
        assert app.state.store.conn.execute("SELECT COUNT(*) FROM library_items").fetchone()[0] == 1
        # A file uploaded into a research before is the same record; saving it from the Library marks it uploaded.
        rid = create(client, source_scope="attached")
        held = client.post(f"/api/researches/{rid}/uploads", files=pdf_file("held.pdf", "SYNTHETIC held study."))
        svid = held.json()["uploaded_source_version_id"]
        from_research = client.post("/api/library/uploads", files=pdf_file("held.pdf", "SYNTHETIC held study.")).json()
        assert (from_research["source_version_id"], from_research["already_saved"]) == (svid, False)
        # Each listed version names the researches that hold it now (S25: a removal names only those versions).
        version = next(v for e in from_research["library"]["entries"] for v in e["versions"] if v["source_version_id"] == svid)
        assert version["research_ids"] == [rid]
        assert client.request("DELETE", f"/api/researches/{rid}/sources", json={"source_version_ids": [svid]}).status_code == 200
        after = client.get("/api/library").json()
        assert next(v for e in after["entries"] for v in e["versions"] if v["source_version_id"] == svid)["research_ids"] == []
        assert app.state.store.conn.execute("SELECT origin, metadata_origin FROM library_items WHERE source_version_id = ?",
                                            (svid,)).fetchone()[:] == ("upload", "user_supplied")


def test_bibliography_for_a_set_exports_the_record_each_row_shows(tmp_path):
    app = app_for(tmp_path)
    with TestClient(app) as raw:
        client = session(raw)
        store = app.state.store
        rid = create(client, source_scope="attached")
        work_id, published, preprint = seed_work(store, rid)
        with transaction(store.conn):
            store.conn.execute("UPDATE source_versions SET authors_json = '[\"Ada Synthetic\"]', publication_type = 'article'"
                               " WHERE id = ?", (published,))
            store.conn.execute("INSERT INTO identifier_mappings (source_version_id, scheme, value, provider, retrieved_at)"
                               " VALUES (?, 'arxiv', '2101.00001', 'openalex', '2026-10-11T00:00:00Z')", (preprint,))
        only = client.post("/api/library/uploads", files=pdf_file("library_only.pdf")).json()

        assert client.post("/api/library/bibliography", json={"format": "bibtex"}).status_code == 422
        assert client.post("/api/library/bibliography", json={"work_ids": ["wrk_missing"]}).status_code == 404
        assert client.post("/api/library/bibliography", json={"source_version_ids": ["srv_missing"]}).status_code == 404
        assert client.post("/api/library/bibliography", json={"work_ids": [work_id], "format": "csv"}).status_code == 422

        bib = client.post("/api/library/bibliography", json={"work_ids": [work_id, only["work_id"]]})
        assert bib.status_code == 200, bib.text
        assert bib.headers["content-type"].startswith("application/x-bibtex")
        assert bib.headers["content-disposition"] == 'attachment; filename="deixis-library.bib"'
        # The row shows the published record (DOI, venue, year), so that record is exported, not merged with the preprint.
        assert bib.text.count("@") == 2 and "@article{synthetic2021synthetic," in bib.text
        assert "doi = {10.1/syn}" in bib.text and "journal = {Synthetic J}" in bib.text and "2101.00001" not in bib.text
        assert "title = {library only}" in bib.text

        ris = client.post("/api/library/bibliography", json={"format": "ris", "source_version_ids": [preprint, published]})
        assert ris.status_code == 200 and ris.headers["content-disposition"].endswith('deixis-library.ris"')
        records = [r for r in ris.text.split("ER  - ") if r.strip()]
        assert len(records) == 2 and "submitted manuscript" in records[0] and "DO  - 10.1/syn" in records[1]


def test_new_research_from_a_set_holds_those_works_in_attached_scope(tmp_path):
    app = app_for(tmp_path)
    with TestClient(app) as raw:
        client = session(raw)
        store = app.state.store
        origin = create(client, source_scope="attached")
        work_id, published, preprint = seed_work(store, origin)
        only = client.post("/api/library/uploads", files=pdf_file("library_only.pdf")).json()
        count = lambda: store.conn.execute("SELECT COUNT(*) FROM researches").fetchone()[0]

        assert client.post("/api/library/researches", json=MODEL | {"work_ids": []}).status_code == 422
        assert client.post("/api/library/researches", json=MODEL | {"work_ids": [work_id], "source_scope": "academic"}).status_code == 422
        assert client.post("/api/library/researches", json=MODEL | {"work_ids": [work_id, "wrk_missing"]}).status_code == 404
        # The create route's own checks apply: an unknown model connection is refused before anything is written.
        assert client.post("/api/library/researches", json=MODEL | {"work_ids": [work_id], "model_connection": "none"}).status_code == 422
        assert count() == 1

        response = client.post("/api/library/researches", json=MODEL | {"work_ids": [work_id, only["work_id"]], "intent": "table"})
        assert response.status_code == 201, response.text
        view = response.json()
        rid = view["research"]["id"]
        assert count() == 2 and view["scope"]["source_scope"] == "attached" and view["research"]["intent"] == "table"
        # One version per work, the one with the deepest stored reading (the preprint's abstract); versions stay apart.
        assert view["added_source_version_ids"] == [preprint, only["source_version_id"]]
        assert {s["source_version_id"]: s["selection"]["state"] for s in view["sources"]} == {
            preprint: "included", only["source_version_id"]: "included"}
        assert not store.is_active_member(rid, published)
        # A table research gets its study table holding the attached works.
        assert store.conn.execute("SELECT COUNT(*) FROM evidence_tables WHERE research_id = ?", (rid,)).fetchone()[0] == 1


FIXTURES = Path(__file__).resolve().parents[1] / "fixtures" / "imports"


def read(name, fmt=None):
    data = (FIXTURES / name).read_bytes()
    return b.read_file(data, name, fmt)


def test_bibtex_fixture_reads_braces_quotes_strings_and_authors():
    fmt, entries, errors = read("synthetic.bib")
    assert fmt == "bibtex"
    by_key = {e.key: e for e in entries}
    assert list(by_key) == ["lovelace2021diffusion", "relay2020", "godel1931"]
    first = by_key["lovelace2021diffusion"]
    # Braces dropped, accents turned into Unicode, an escaped & kept, math left as written.
    assert first.title == "SYNTHETIC Diffusion Scheduling with $\\alpha$-stable Noise & Müller's étude"
    # Last, First / braced corporate name / Last, Jr, First; "others" is not an author.
    assert first.authors == ["Ada Lovelace", "Jörg Müller", "Synthetic Consortium", "John Doe Jr"]
    assert first.venue == "Synthetic Journal of Letters"  # @string concatenated with #
    assert (first.year, first.volume, first.issue, first.pages) == (2021, "12", "3", "10-20")
    assert first.doi == "10.5555/syn.hit" and first.publication_type == "journalArticle"
    assert first.abstract == "We schedule molecule releases."
    relay = by_key["relay2020"]  # parenthesised entry, quoted values
    assert (relay.title, relay.authors, relay.venue, relay.year) == (
        "SYNTHETIC relay budget under drift", ["Q. Synthetic", "R. Example"], "Proc. Synthetic Workshop", 2020)
    assert relay.publication_type == "conferencePaper" and relay.doi == "10.5555/syn.miss"
    book = by_key["godel1931"]  # missing fields stay empty; the year comes from biblatex `date`
    assert (book.title, book.authors, book.year, book.venue, book.doi, book.pages) == (
        "SYNTHETIC Book on Gašper Çelik and øystein", ["Kurt Gödel"], 1931, "Synthetic Press", None, None)
    assert [(e.index, e.key, e.code) for e in errors] == [
        (3, "unclosed2019", "unclosed_value"), (5, "notitle2018", "no_title"),
        (6, "undefined2017", "undefined_string"), (7, "baddoi2016", "invalid_doi")]
    assert all(e.line > 1 for e in errors)


def test_ris_fixture_reads_records_and_reports_the_broken_ones():
    fmt, entries, errors = read("synthetic.ris")
    assert fmt == "ris"
    first, book = entries
    assert (first.key, first.title, first.authors, first.year) == (
        "ris-one", "SYNTHETIC RIS diffusion record", ["Ada Lovelace", "John Doe Jr."], 2019)
    assert (first.venue, first.volume, first.issue, first.pages, first.doi) == ("Synthetic Journal", "4", "2", "1-9", "10.5555/syn.hit")
    assert first.abstract == "A first line of the abstract that wraps to a second line."
    assert (book.index, book.title, book.authors, book.year, book.venue, book.publication_type) == (
        3, "SYNTHETIC RIS book without DOI", ["Rae Example"], 2001, "Synthetic Press", "book")
    assert [(e.index, e.code) for e in errors] == [(2, "unclosed_record"), (4, "no_title"), (None, "outside_record")]


@pytest.mark.parametrize("data", [
    b"@a{k, t={" * 500_000,  # values that never close, all on one line
], ids=["open-values-one-line"])
def test_pathological_files_stop_early_in_bounded_time(data):
    import time
    assert len(data) <= b.MAX_FILE_BYTES
    started = time.perf_counter()
    try:
        _, entries, errors = b.read_file(data, "x.ris" if data.startswith(b"TY") else "x.bib")
        assert len(entries) + len(errors) <= b.MAX_ENTRIES
    except b.ImportRefused as refused:
        assert refused.code == "import_too_many_entries"
    assert time.perf_counter() - started < 3.0


def bounded(run, seconds=3.0, peak_bytes=64 * 1024 * 1024):
    """Run `run()` and assert it stayed within the time given (untraced) and, when `peak_bytes` is given, within that
    traced memory (a second, traced run: tracing slows Python too much to time it)."""
    import time
    import tracemalloc
    started = time.perf_counter()
    try:
        result = run()
    finally:
        elapsed = time.perf_counter() - started
        assert elapsed < seconds, elapsed
    if peak_bytes is not None:
        tracemalloc.start()
        try:
            run()
        finally:
            peak = tracemalloc.get_traced_memory()[1]
            tracemalloc.stop()
            assert peak < peak_bytes, peak
    return result
