"""Verify Citations V1 (D86): the draft routes, bibliography matching and OpenAlex resolution through a mocked httpx
transport, the internal research kept out of every list, and the delete cascade. Drafts and records are SYNTHETIC;
nothing here calls a model or the network."""

import httpx
import pytest
from fastapi.testclient import TestClient
from deixis.api.app import create_app
from deixis.config import Settings
from deixis.workflow.answer import citation_check
from fakes import FakeAdapter
import io
import zipfile
from deixis.documents import draft_parse
from deixis.documents.draft_parse import DraftRefused, parse_draft, read_draft


CHILD_TABLES = ("citation_markers", "citation_bib_entries", "citation_pairs")


BIB = b"""@article{zeng2022, title = {Depth based routing for underwater networks}, author = {Zeng, Yi and Li, Xu},
  year = {2022}, doi = {10.5555/syn.zeng}}
@article{kim2021, title = {Void avoidance in sparse acoustic networks}, author = {Kim, Jae}, year = {2021}}
@article{kim2021b, title = {Another Kim study of the same year}, author = {Kim, Jae}, year = {2021}}
@misc{park2019, title = {Energy aware forwarding}, author = {Park, Min}, year = {2019}, eprint = {1901.00001},
  archivePrefix = {arXiv}}
@article{broken, author = {No Title}}
"""


def work(wid, title, doi=None, year=2022, retracted=False):
    return {"id": f"https://openalex.org/{wid}", "doi": f"https://doi.org/{doi}" if doi else None, "display_name": title,
            "publication_year": year, "type": "article", "ids": {"openalex": f"https://openalex.org/{wid}"},
            "authorships": [{"author": {"display_name": "Ada Provider"}}], "is_retracted": retracted,
            "primary_location": {"version": "publishedVersion", "source": {"display_name": "Provider Journal"}},
            "best_oa_location": None, "abstract_inverted_index": None}


class OpenAlex:
    """A DOI filter answers from `works`; a search answers `searches[query]` (else nothing). `status` other than 200
    fails every request; `short_count` reports more works than it returns."""

    def __init__(self, works=(), searches=None, status=200, short_count=False):
        self.works, self.searches = list(works), dict(searches or {})
        self.status, self.short_count, self.seen = status, short_count, []

    def handler(self, request):
        self.seen.append(request)
        if request.url.host != "api.openalex.org":
            return httpx.Response(404)
        if self.status != 200:
            return httpx.Response(self.status)
        params = request.url.params
        if "filter" in params:
            asked = params["filter"].removeprefix("doi:").split("|")
            found = [w for w in self.works if w["doi"] and w["doi"].removeprefix("https://doi.org/") in asked]
        else:
            found = self.searches.get(params["search.title_and_abstract"], [])
        return httpx.Response(200, json={"meta": {"count": len(found) + self.short_count}, "results": found})


@pytest.fixture
def make(tmp_path):
    def build(openalex=None):
        openalex = openalex or OpenAlex()
        settings = Settings(data_dir=tmp_path / "data", port=8765, search_query="code", fulltext_fetch="off")
        app = create_app(settings, adapters={"fake": FakeAdapter()}, http_client=httpx.AsyncClient(
            transport=httpx.MockTransport(openalex.handler)), extra_hosts=("testserver",), trusted_clients=("testclient",))
        return app, openalex
    return build


def session(client):
    client.headers["x-deixis-csrf"] = client.get("/api/session").json()["csrf_token"]
    return client


def submit(client, draft=None, name="draft.md", text=None, bib=None, bib_name="refs.bib"):
    files = {}
    if draft is not None:
        files["file"] = (name, draft, "application/octet-stream")
    if bib is not None:
        files["bibliography"] = (bib_name, bib, "application/octet-stream")
    return client.post("/api/citation-checks", files=files or None, data={"text": text} if text is not None else None)


def pairs(view):
    return [(m["raw"], p["target"], p["status"]) for m in view["markers"] for p in m["pairs"]]


def test_resolution_by_doi_needs_exactly_one_work_and_is_idempotent(make):
    openalex = OpenAlex(works=[work("W1", "Depth based routing for underwater networks", "10.5555/syn.zeng"),
                               work("W2", "Twin A", "10.5555/syn.twin"), work("W3", "Twin B", "10.5555/syn.twin"),
                               work("W4", "Energy aware forwarding", "10.48550/arxiv.1901.00001", year=2019)])
    app, _ = make(openalex)
    bib = BIB + b"@article{twin, title = {Twin A}, author = {T, A}, year = {2020}, doi = {10.5555/syn.twin}}\n" \
                b"@article{gone, title = {Gone}, author = {G, A}, year = {2020}, doi = {10.5555/syn.gone}}\n"
    with TestClient(app) as raw:
        client = session(raw)
        draft_id = submit(client, b"A \\cite{zeng2022, park2019, twin, gone}.", "d.tex", bib=bib).json()["id"]
        response = client.post(f"/api/citation-checks/{draft_id}/resolve")
        assert response.status_code == 200, response.text
        view = response.json()
        assert view["resolved_now"] == {"asked": 4, "resolved": 2, "unresolved": 2, "lookup_failed": 0}
        entries = {e["key"]: e for e in view["entries"]}
        assert (entries["zeng2022"]["resolution"]["status"], entries["zeng2022"]["resolution"]["method"]) == ("resolved", "doi")
        assert entries["zeng2022"]["resolution"]["origin"] == "code"
        # Titles and authors shown come from the stored record, not the entry.
        assert entries["zeng2022"]["source"]["title"] == "Depth based routing for underwater networks"
        assert entries["zeng2022"]["source"]["authors"] == ["Ada Provider"]
        assert (entries["park2019"]["resolution"]["method"], entries["park2019"]["source"]["year"]) == ("arxiv", 2019)
        assert (entries["twin"]["resolution"]["status"], entries["twin"]["resolution"]["reason"]) == ("unresolved", "doi_several_works")
        assert entries["gone"]["resolution"]["reason"] == "doi_not_found"
        assert [p["status"] for p in view["markers"][0]["pairs"]] == ["planned", "planned", "unresolved", "unresolved"]
        assert view["counters"]["sources_resolved"] == 2
        sent = len(openalex.seen)
        again = client.post(f"/api/citation-checks/{draft_id}/resolve").json()
        assert again["resolved_now"]["asked"] == 0 and len(openalex.seen) == sent


def test_deleting_a_draft_removes_everything_read_from_it_and_its_research(make):
    openalex = OpenAlex(works=[work("W1", "Depth based routing for underwater networks", "10.5555/syn.zeng")])
    app, _ = make(openalex)
    with TestClient(app) as raw:
        client = session(raw)
        keep = submit(client, b"Kept \\cite{kim2021}.", "keep.tex", bib=BIB).json()
        view = submit(client, b"A \\cite{zeng2022} and (Kim, 2021).", "d.tex", bib=BIB).json()
        client.post(f"/api/citation-checks/{view['id']}/resolve")
        store = app.state.store
        svid = next(e for e in client.get(f"/api/citation-checks/{view['id']}").json()["entries"]
                    if e["key"] == "zeng2022")["source"]["source_version_id"]
        pair = store.conn.execute("SELECT id FROM citation_pairs WHERE draft_id = ? AND bib_entry_id IS NOT NULL",
                                  (view["id"],)).fetchone()[0]
        store.conn.execute("INSERT INTO citation_checks (id, pair_id, status, error_json, created_at)"
                           " VALUES ('chk_1', ?, 'could_not_check', '\"repair_exhausted\"', 'now')", (pair,))
        assert client.delete(f"/api/citation-checks/{view['id']}").json() == {"deleted": True, "files_not_removed": []}
        assert client.get(f"/api/citation-checks/{view['id']}").status_code == 404
        assert store.conn.execute("SELECT COUNT(*) FROM researches WHERE id = ?", (view["research_id"],)).fetchone()[0] == 0
        for table in CHILD_TABLES:
            assert store.conn.execute(f"SELECT COUNT(*) FROM {table} WHERE draft_id = ?", (view["id"],)).fetchone()[0] == 0
        assert store.conn.execute("SELECT COUNT(*) FROM citation_checks").fetchone()[0] == 0
        # The other draft and the stored provider record stay.
        assert client.get(f"/api/citation-checks/{keep['id']}").status_code == 200
        assert store.source(svid)["title"] == "Depth based routing for underwater networks"
        assert client.delete("/api/citation-checks/cdr_missing").status_code == 404


@pytest.mark.parametrize("files, data, code", [({"file": ("d.pdf", b"%PDF", "application/pdf")}, None, "draft_unknown_format")])
def test_refused_drafts_store_nothing(make, files, data, code):
    app, _ = make()
    with TestClient(app) as raw:
        client = session(raw)
        response = client.post("/api/citation-checks", files=files, data=data)
        assert response.status_code in (413, 415, 422) and response.json()["code"] == code, response.text
        assert app.state.store.conn.execute("SELECT COUNT(*) FROM citation_drafts").fetchone()[0] == 0
        assert app.state.store.conn.execute("SELECT COUNT(*) FROM researches").fetchone()[0] == 0


def test_an_oversized_body_is_refused_before_it_is_read_and_csrf_is_required(make):
    app, _ = make()
    with TestClient(app) as raw:
        client = session(raw)
        too_big = client.post("/api/citation-checks", content=b"x", headers={
            "content-type": "multipart/form-data; boundary=b", "content-length": str(30 * 1024 * 1024)})
        assert too_big.status_code == 413 and too_big.json()["code"] == "draft_too_large"
        assert raw.post("/api/citation-checks", data={"text": "A [1]."}, headers={"x-deixis-csrf": "wrong"}).status_code == 403


def test_the_et_al_rule():
    match = citation_check.authors_match
    assert match(["smith"], True, ["smith", "jones", "brown"]) and not match(["smith"], True, ["smith", "jones"])
    assert match(["smith", "jones"], True, ["smith", "jones", "brown"]) and not match(["smith", "jones"], True, ["smith", "jones"])
    assert match(["smith"], False, ["smith"]) and not match(["smith"], False, ["smith", "jones"])


def docx(*paragraphs, extra_xml=""):
    ns = 'xmlns:w="http://schemas.openxmlformats.org/wordprocessingml/2006/main"'
    body = "".join(f"<w:p><w:r><w:t>{p}</w:t></w:r></w:p>" for p in paragraphs)
    buffer = io.BytesIO()
    with zipfile.ZipFile(buffer, "w") as archive:
        archive.writestr("[Content_Types].xml", "<Types/>")
        archive.writestr("word/document.xml", f'<?xml version="1.0"?>{extra_xml}<w:document {ns}><w:body>{body}</w:body></w:document>')
    return buffer.getvalue()


def markers(text, fmt="md"):
    return [(m.style, m.status, m.raw, [t.value for t in m.targets]) for m in parse_draft(fmt, text).markers]


def test_ieee_numeric_markers_single_range_list_and_adjacent():
    found = markers("Routing helps [3]. Energy drops [3]–[5] and [6-8]. Both [3, 7] agree. See [3], [4]. Also [2,4–6].")
    assert found == [
        ("numeric", "recognized", "[3]", ["3"]),
        ("numeric", "recognized", "[3]–[5]", ["3", "4", "5"]),
        ("numeric", "recognized", "[6-8]", ["6", "7", "8"]),
        ("numeric", "recognized", "[3, 7]", ["3", "7"]),
        ("numeric", "recognized", "[3], [4]", ["3", "4"]),
        ("numeric", "recognized", "[2,4–6]", ["2", "4", "5", "6"]),
    ]


def test_author_year_parenthetical_narrative_multi_and_suffixes():
    found = markers("It holds (Zeng et al., 2022). Both agree (Zeng and Li, 2022; Kim, 2021). Zeng et al. (2022a) "
                    "showed it. Two papers (Kim, 2021a, 2021b) differ. See also (e.g., Park & Lee, 2019, p. 4).")
    assert found == [
        ("author_year", "recognized", "(Zeng et al., 2022)", ["Zeng et al., 2022"]),
        ("author_year", "recognized", "(Zeng and Li, 2022; Kim, 2021)", ["Zeng and Li, 2022", "Kim, 2021"]),
        ("author_year", "recognized", "Zeng et al. (2022a)", ["Zeng et al., 2022a"]),
        ("author_year", "recognized", "(Kim, 2021a, 2021b)", ["Kim, 2021a", "Kim, 2021b"]),
        ("author_year", "recognized", "(e.g., Park & Lee, 2019, p. 4)", ["Park & Lee, 2019"]),
    ]
    target = parse_draft("md", "Zeng et al. (2022a) showed it.").markers[0].targets[0]
    assert (target.names, target.et_al, target.year, target.suffix) == (("Zeng",), True, 2022, "a")


def test_latex_cite_commands_with_optional_arguments_and_multiple_keys():
    text = (r"\begin{document}As shown \cite{zeng2022, kim2021}. Also \citep[p.~3]{li2020} and \citet[see][ch.~2]{park}."
            r" Bad \cite{a b}. Broken \cite here. % \cite{commented}" "\n" r"\end{document}")
    assert markers(text, "tex") == [
        ("latex", "recognized", r"\cite{zeng2022, kim2021}", ["zeng2022", "kim2021"]),
        ("latex", "recognized", r"\citep[p.~3]{li2020}", ["li2020"]),
        ("latex", "recognized", r"\citet[see][ch.~2]{park}", ["park"]),
        ("latex", "unrecognized", r"\cite{a b}", []),
        ("latex", "unrecognized", r"\cite", []),
    ]


def test_formats_text_md_tex_and_docx_paragraphs():
    assert read_draft(b"Claim [1].", "draft.md", None) == ("md", "Claim [1].")
    assert read_draft(b"Claim \\cite{a}.", "draft.tex", None)[0] == "tex"
    assert read_draft(None, None, "Pasted [2].\r\nNext") == ("text", "Pasted [2].\nNext")
    fmt, text = read_draft(docx("First claim [1].", "Second (Zeng, 2022)."), "draft.docx", None)
    assert (fmt, text) == ("docx", "First claim [1].\n\nSecond (Zeng, 2022).")
    assert len(parse_draft(fmt, text).markers) == 2


@pytest.mark.parametrize("data, name, pasted, code", [(b"x", "draft.pdf", None, "draft_unknown_format"), (b"\x00\x01binary", "draft.txt", None, "draft_not_text")])
def test_drafts_that_are_refused(data, name, pasted, code):
    with pytest.raises(DraftRefused) as caught:
        read_draft(data, name, pasted)
    assert caught.value.code == code


def docx_xml(xml: bytes):
    buffer = io.BytesIO()
    with zipfile.ZipFile(buffer, "w") as archive:
        archive.writestr("word/document.xml", xml)
    return buffer.getvalue()


W_NS = 'xmlns:w="http://schemas.openxmlformats.org/wordprocessingml/2006/main"'


@pytest.mark.parametrize("encoding", ["utf-8"])
@pytest.mark.parametrize("dtd", ['<!DOCTYPE w:document [<!ENTITY a "SYNTHETIC-expanded"><!ENTITY b "&a;&a;&a;&a;">]>', '<!DOCTYPE w:document SYSTEM "http://example.invalid/x.dtd">'])
def test_a_docx_with_a_dtd_or_entity_is_refused_in_any_encoding(encoding, dtd):
    # Sol round 1: a UTF-16 document.xml passed the old byte search and its internal entity was expanded.
    declaration = f'<?xml version="1.0" encoding="{encoding.upper()}"?>' if not encoding.endswith(("le", "be")) else \
        f'<?xml version="1.0" encoding="UTF-16"?>'
    xml = f'{declaration}{dtd}<w:document {W_NS}><w:body><w:p><w:r><w:t>&b;</w:t></w:r></w:p></w:body></w:document>'
    data = xml.encode(encoding)
    if encoding in ("utf-16-le", "utf-16-be"):
        data = ("\ufeff" + xml).encode(encoding)
    assert b"<!DOCTYPE" not in data or encoding == "utf-8"
    with pytest.raises(DraftRefused) as caught:
        read_draft(docx_xml(data), "draft.docx", None)
    assert caught.value.code == "draft_unreadable"


def list_of(count, numbered=True):
    return "\n".join(f"[{i}] A. Author{i}, \"Title {i},\" 2020." if numbered else f"Author{i}, A. (2020). Title {i}. J."
                     for i in range(1, count + 1))


@pytest.mark.parametrize("draft, fmt", [("Claim [1].\n\nReferences\n" + list_of(500) + "\n[1] B. Second, \"Duplicate one,\" 2021.", "md")])
def test_a_reference_list_over_the_cap_is_refused_whole_never_cut(draft, fmt):
    with pytest.raises(DraftRefused) as caught:
        parse_draft(fmt, draft)
    assert caught.value.code == "draft_list_too_long" and caught.value.status == 413
