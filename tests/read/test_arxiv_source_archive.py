"""Reading equations from an arXiv LaTeX source: the archive and macro expansion that fail closed, the source child and its limits (F09 at the production memory limit), fetching the source behind its rate gate, and matching source groups to the PDF's numbered displays. SYNTHETIC archives and PDFs, no network."""

import asyncio
import gzip
import os
import sys
import tarfile
import tempfile
import time
from pathlib import Path
import pytest
from arxiv_helpers import make_arxiv_pdf, make_tar, no_network, source_archive  # noqa: F401 - no_network is an autouse fixture
from deixis.documents import arxiv_source as src
from deixis.documents import pdf
import http.server
import multiprocessing
import signal
import threading
import httpx
from arxiv_helpers import fetch_child, make_arxiv_pdf, no_network, source_archive
from deixis.documents import fetch
from deixis.storage import db
from deixis.workflow.run.store import Store
import pymupdf
from arxiv_helpers import make_arxiv_pdf, no_network, source_archive


REPO = Path(__file__).resolve().parents[2]


def groups_of(tex: str) -> list[dict]:
    found, _ = src.source_groups({"main.tex": tex})
    return found


def doc(body: str, preamble: str = "") -> str:
    return "\\documentclass{article}\n" + preamble + "\n\\begin{document}\n" + body + "\n\\end{document}\n"


def test_the_five_macro_forms_expand_including_optional_arguments_and_def_arguments():
    pre = ("\\newcommand{\\pr}[2][P]{#1(#2)}\\def\\pair#1#2{\\langle #1, #2\\rangle}"
           "\\DeclareMathOperator*{\\argmaxx}{arg\\,max}\\newcommand\\RR{\\mathbb{R}}\\newcommand{\\vv}{V}\\renewcommand{\\vv}{V}")
    found = groups_of(doc("\\begin{equation}\\pr{x} + \\pr[Q]{y} + \\pair{a}{b} + \\argmaxx_{z} \\in \\RR + \\vv\\end{equation}", pre))
    assert found[0]["latex"] == "P(x) + Q(y) + \\langle a, b\\rangle + \\operatorname*{arg\\,max}_{z} \\in \\mathbb{R} + V"
    assert found[0]["refused"] is None


def test_r11_what_the_scan_cannot_read_fails_closed():
    # Sol r11: `\@nameuse{\pick{foo}}` has nested braces, the argument was not matched and the loop just stopped. Every
    # place the scan cannot read now makes the name unsafe or, when the name cannot be known, the source unbounded.
    long = " + ".join("abcdefghijk")
    eq = "\\begin{equation}\\foo + " + long + " = l\\end{equation}\\begin{equation}p = q\\end{equation}"

    def rows(body, preamble="", extra=None):
        found, info = src.source_groups({"main.tex": doc(body + eq, preamble)} | (extra or {}))
        return [g["refused"] for g in found], info
    unbounded = [("{\\newcommand{\\foo}{x}}\\makeatletter\\@nameuse{\\pick{foo}}\\makeatother", "\\def\\pick#1{#1}"),  # Sol's
                 ("\\newcommand{\\foo}{x}\\makeatletter\\@nameuse{foo", ""),  # an unclosed name argument
                 ("\\newcommand{\\foo}{x}\\makeatletter\\@ifundefined", ""),  # no argument at all
                 ("\\newcommand{\\foo}{x}\\endcsname", ""),  # a stray \endcsname
                 ("\\newcommand{\\foo}{x}\\csname foo", ""),  # a \csname never ended
                 ("\\newcommand{\\foo}{x}\\verb|open", ""),  # a \verb never closed on its line
                 ("\\newcommand{\\foo}{x}", "", {"notes.tex": "\\begin{comment} x"})]  # a verbatim-like environment never ended
    for body, preamble, *extra in unbounded:
        refused, info = rows(body, preamble, *extra)
        assert info["unbounded"] and refused[0] == "macro_ambiguous", body + preamble
    # a truncated or malformed definition makes its own name unsafe
    for preamble in ("\\newcommand{\\foo}{x}\\def\\foo", "\\newcommand{\\foo}{x}\\newcommand{\\foo}", "\\newcommand{\\foo}[1]{x#2}",
                     "\\newcommand{\\foo}{x}\\def\\foo #1{y}"):
        refused, info = rows("", preamble)
        assert refused == ["macro_ambiguous", None] and "\\foo" in info["ambiguous_macros"], preamble
    refused, info = rows("", "", {"late.tex": "\\newcommand{\\foo}{x"})  # a body never closed, in a file never read
    assert refused == ["macro_ambiguous", None] and "\\foo" in info["ambiguous_macros"]
    # a use whose argument cannot be read (the group ends first, an unclosed optional argument) refuses its group
    found, _ = src.source_groups({"main.tex": doc("\\begin{equation}p + \\pr\\end{equation}\\begin{equation}\\pr[a + b\\end{equation}"
                                                  "\\begin{equation}\\pr{y}\\end{equation}", "\\newcommand{\\pr}[2][P]{#1(#2)}")})
    assert [(g["latex"], g["refused"]) for g in found][2] == ("P(y)", None)
    assert [g["refused"] for g in found][:2] == ["macro_ambiguous", "macro_ambiguous"]
    # Sol r12: the optional argument ended at the first `]`, even inside braces: `\\myop[{x]y}]{z}` expanded wrongly and
    # placed. Braces in an optional argument now make the use unreadable; a plain one still reads
    found, _ = src.source_groups({"main.tex": doc("\\begin{equation}\\myop[{x]y}]{z} + " + long + "\\end{equation}"
                                                  "\\begin{equation}\\myop[w]{z}\\end{equation}", "\\newcommand{\\myop}[2][d]{#1(#2)}")})
    assert found[0]["refused"] == "macro_ambiguous" and (found[1]["latex"], found[1]["refused"]) == ("w(z)", None)
    # Sol r13: a brace after `\\\\` (a line break) is a real brace; one after a single `\\` is an escaped character
    found, _ = src.source_groups({"main.tex": doc("\\begin{equation}\\myop[a\\\\{x]y\\\\}b]{z} + " + long + "\\end{equation}"
                                                  "\\begin{equation}\\myop[a\\{w\\}]{z}\\end{equation}", "\\newcommand{\\myop}[2][d]{#1(#2)}")})
    assert found[0]["refused"] == "macro_ambiguous" and (found[1]["latex"], found[1]["refused"]) == ("a\\{w\\}(z)", None)


def test_links_devices_and_unsafe_names_are_never_read_and_nothing_is_written_to_disk(tmp_path, monkeypatch):
    monkeypatch.chdir(tmp_path)
    # A temp folder of this test's own: the shared system one also gets the parallel workers' files.
    own_tmp = tmp_path / "tmp"
    own_tmp.mkdir()
    monkeypatch.setenv("TMPDIR", str(own_tmp))
    monkeypatch.setattr(tempfile, "tempdir", str(own_tmp))
    before = sorted(os.listdir(tempfile.gettempdir())), sorted(os.listdir(tmp_path))
    link = tarfile.TarInfo("link.tex")
    link.type, link.linkname = tarfile.SYMTYPE, "/etc/passwd"
    hard = tarfile.TarInfo("hard.tex")
    hard.type, hard.linkname = tarfile.LNKTYPE, "main.tex"
    device = tarfile.TarInfo("dev.tex")
    device.type = tarfile.CHRTYPE
    fifo = tarfile.TarInfo("pipe.tex")
    fifo.type = tarfile.FIFOTYPE
    archive = src.read_archive(make_tar({"main.tex": doc("x"), "../evil.tex": "evil", "/etc/evil.tex": "evil"},
                                        extra=[link, hard, device, fifo]))
    assert archive.content == "tex" and set(archive.files) == {"main.tex"}
    assert (sorted(os.listdir(tempfile.gettempdir())), sorted(os.listdir(tmp_path))) == before


def test_a_pdf_is_pdf_only_a_tar_without_tex_is_no_tex_and_a_single_gzipped_tex_is_read():
    assert src.read_archive(make_arxiv_pdf()).content == "pdf_only"
    assert src.read_archive(make_tar({"fig.eps": "%!PS", "paper.dvi": b"\xf7\x02"})).content == "no_tex"
    single = src.read_archive(gzip.compress(doc("\\begin{equation} a = b \\end{equation}").encode()))
    assert single.content == "tex" and list(single.files) == ["main.tex"]
    assert src.read_archive(b"not an archive at all").content == "no_tex"


MIB = 1024 * 1024


@pytest.mark.skipif(os.environ.get("DEIXIS_P9_PRODUCTION_THRESHOLD") != "1",
                    reason="F09 for the arXiv source child takes about 30 s; set DEIXIS_P9_PRODUCTION_THRESHOLD=1")
def test_the_source_child_is_stopped_at_the_production_memory_limit(tmp_path):
    # ~200 MiB of decoded page content in a PDF of about 200 KB makes the matching step grow past 1 GiB (D159).
    sys.path.insert(0, str(REPO / "scripts" / "release_checks"))
    import memory_probe

    path = tmp_path / "expands-past-1gib.pdf"
    memory_probe.build_pdf(path, 200 * MIB)
    # The production argv and limit; only the 60 s time limit is widened, so a loaded machine ends at the memory limit and
    # not at the clock (growth here is about 30 MiB/s unloaded, slower under load).
    argv = [sys.executable, "-m", "deixis.documents.arxiv_source", str(path), "[]", "placements", str(src.MAX_MEMORY_BYTES)]
    env = {"PYTHONPATH": str(Path(src.__file__).resolve().parents[2])}
    result = asyncio.run(src.run_child(argv, source_archive(), timeout=240, env=env, max_memory=src.MAX_MEMORY_BYTES))
    assert result.failure == "memory_limit"


def test_a_child_limit_or_the_memory_watch_makes_the_source_unreadable(tmp_path, monkeypatch):
    for failure in ("timed_out", "memory_limit", "output_too_large"):
        async def fake(argv, stdin=b"", **kwargs):
            return src.ChildResult(None, b"", "SYNTHETIC", failure)
        monkeypatch.setattr(src, "run_child", fake)
        found = asyncio.run(src.read_source(source_archive(), tmp_path / "x.pdf", set()))
        assert found["content"] == "unreadable" and found["error"] == failure


def test_the_real_child_reads_a_synthetic_source_against_a_synthetic_pdf(tmp_path):
    path = tmp_path / "paper.pdf"
    path.write_bytes(make_arxiv_pdf())
    found = asyncio.run(src.read_source(source_archive(), path, set()))
    assert found["content"] == "tex" and [p["n"] for p in found["placements"]] == ["1", "2"]
    assert found["placements"][0]["latex"] == "P_{a b} = c_{d}"


KEY = "2101.00001v2"


ARCHIVE = source_archive()


# ---- decision 1 ----------------------------------------------------------------------------------------------------------
def record(**fields):
    return {"doi": "10.48550/arXiv.2101.00001", "landing_url": "https://arxiv.org/abs/2101.00001v2",
            "oa_pdf_url": "https://arxiv.org/pdf/2101.00001v2", "version_label": "arXiv v2"} | fields


# ---- decision 2 with a mock transport and a fake clock ------------------------------------------------------------------
class Clock:
    def __init__(self):
        self.now = 1_800_000_000.0

    def time(self):
        return self.now

    async def sleep(self, seconds):
        self.now += seconds
        await asyncio.sleep(0)


@pytest.fixture
def clock(monkeypatch):
    fake = Clock()
    monkeypatch.setattr(src, "clock", fake.time)
    monkeypatch.setattr(src, "sleep", fake.sleep)
    return fake


@pytest.fixture
def public(monkeypatch):
    async def resolve(url):
        return "93.184.216.34"  # a documentation-range public address; the mock transport answers, nothing connects
    monkeypatch.setattr(fetch, "check_public_url", resolve)


def store_at(tmp_path):
    conn = db.connect(tmp_path / "library.sqlite")
    db.migrate(conn)
    return Store(conn)


def ok(key=KEY, body=ARCHIVE):
    return httpx.Response(200, content=body, headers={"content-type": "application/gzip",
                                                      "content-disposition": f'attachment; filename="arXiv-{key}.tar.gz"'})


def sources_with(tmp_path, handler, seen=None):
    def record_and_answer(request):
        if seen is not None:
            seen.append((src.clock(), str(request.url.path)))
        return handler(request)
    client = httpx.AsyncClient(transport=httpx.MockTransport(record_and_answer))
    return src.SourceStore(store_at(tmp_path), tmp_path / "data", client=client)


def test_a_source_is_fetched_once_stored_through_a_part_file_and_then_read_back(tmp_path, clock, public):
    seen = []
    sources = sources_with(tmp_path, lambda r: ok(), seen)
    row = asyncio.run(sources.ensure(KEY))
    assert row["status"] == "downloaded" and row["attempts"] == 1 and row["content"] is None and len(seen) == 1
    assert seen[0][1] == "/e-print/2101.00001v2" and not list((tmp_path / "data/arxiv-sources").glob("*.part-*"))
    assert asyncio.run(sources.read(KEY)) == (ARCHIVE, None)
    assert asyncio.run(sources.ensure(KEY))["status"] == "downloaded" and len(seen) == 1  # never fetched twice


@pytest.mark.parametrize("response, status", [
    pytest.param(lambda: httpx.Response(200, content=b"x" * (fetch.MAX_BYTES + 1), headers={"content-type": "application/gzip"}), "too_large", id="<lambda>-too_large"),
])
def test_each_answer_has_its_download_status(tmp_path, clock, public, response, status):
    sources = sources_with(tmp_path, lambda r: response())
    row = asyncio.run(sources.ensure(KEY))
    assert row["status"] == status and row["attempts"] == 1 and row["content"] is None
    assert not (tmp_path / "data/arxiv-sources" / f"{KEY}.src").exists()


def test_a_host_resolving_to_a_private_address_is_refused_without_a_request(tmp_path, clock, monkeypatch):
    async def private(host, port):
        return ["10.0.0.7"]
    monkeypatch.setattr(fetch, "_resolve", private)
    seen = []
    sources = sources_with(tmp_path, lambda r: ok(), seen)
    row = asyncio.run(sources.ensure(KEY))
    assert row["status"] == "unreadable" and "non-public" in row["error"] and seen == []


# ---- decision 2 across processes, arrivals as a local server sees them ---------------------------------------------------
class Server:
    """A SYNTHETIC arXiv on loopback: records each request's arrival time (server side), can delay or redirect."""

    def __init__(self, delay: float = 0.0, redirect: bool = False):
        self.arrivals: list[tuple[float, str]] = []
        server = self

        class Handler(http.server.BaseHTTPRequestHandler):
            def do_GET(self):
                server.arrivals.append((time.time(), self.path))
                key = self.path.rsplit("/", 1)[1]
                if redirect and self.path.startswith("/e-print/"):
                    self.send_response(302)
                    self.send_header("Location", f"/src/{key}")
                    self.end_headers()
                    return
                time.sleep(server.delay)
                self.send_response(200)
                self.send_header("Content-Type", "application/gzip")
                self.send_header("Content-Disposition", f'attachment; filename="arXiv-{key}.tar.gz"')
                self.send_header("Content-Length", str(len(ARCHIVE)))
                self.end_headers()
                try:
                    self.wfile.write(ARCHIVE)
                except (BrokenPipeError, ConnectionResetError):
                    pass

            def log_message(self, *args):
                pass

        self.delay = delay
        self.httpd = http.server.ThreadingHTTPServer(("127.0.0.1", 0), Handler)
        self.httpd.daemon_threads = True
        self.port = self.httpd.server_address[1]
        threading.Thread(target=self.httpd.serve_forever, daemon=True).start()

    def wait_for(self, count: int, timeout: float = 30) -> None:
        deadline = time.time() + timeout
        while len(self.arrivals) < count and time.time() < deadline:
            time.sleep(0.02)
        assert len(self.arrivals) >= count, self.arrivals

    def close(self):
        self.httpd.shutdown()


@pytest.fixture
def shared(tmp_path):
    conn = db.connect(tmp_path / "library.sqlite")
    db.migrate(conn)
    conn.close()
    return str(tmp_path / "library.sqlite"), str(tmp_path / "data")


def spawn(shared, port, key, results, offset=0.0):
    process = multiprocessing.get_context("spawn").Process(target=fetch_child, args=(*shared, port, key, results, offset))
    process.start()
    return process


def gaps(arrivals):
    times = sorted(t for t, _ in arrivals)
    return [b - a for a, b in zip(times, times[1:])]


TOP = ["SYNTHETIC. We study a simple model of signal detection in which the receiver counts the",
       "particles that arrive within each interval and compares the count with a threshold chosen",
       "in advance. The quantities below are defined once and then used throughout this paper."]


def build(tmp_path, pages, name="paper.pdf"):
    """pages: lists of (x, y, text) or (x, y, text, size); inserted in order, which is the text layer's reading order."""
    doc = pymupdf.open()
    for lines in pages:
        page = doc.new_page(width=612, height=792)
        for item in lines:
            x, y, text, size = (*item, 10) if len(item) == 3 else item
            page.insert_text((x, y), text, fontsize=size, fontname="helv")
    path = tmp_path / name
    path.write_bytes(doc.tobytes())
    return path


def top(y=90):
    return [(72, y + 14 * k, line) for k, line in enumerate(TOP)]


def equation(y, printed, number, x=200):
    return [(x, y, printed), (520, y, f"({number})")]


def prose(y, text="where the symbols keep the meaning they have in the model defined above."):
    return [(72, y, text)]


def tex(body):
    return "\\documentclass{article}\n\\begin{document}\n" + body + "\n\\end{document}\n"


def eq(latex):
    return f"\\begin{{equation}}\n{latex}\n\\end{{equation}}\n"


def run(path, body, skip=()):
    found, _ = src.source_groups({"main.tex": tex(body)})
    return src.match(path, found, set(skip))


def test_the_right_group_is_chosen_and_the_constants_are_named(tmp_path):
    path = build(tmp_path, [top() + equation(160, "P a b = c d", 1) + prose(190) + equation(230, "Q m n = r s t", 2) + prose(260)])
    result = run(path, eq("P_{a b} = c_{d}") + eq("Q_{m} n = r \\frac{s}{t}"))
    assert [(p["n"], p["latex"]) for p in result["placements"]] == [("1", "P_{a b} = c_{d}"), ("2", "Q_{m} n = r \\frac{s}{t}")]
    assert src.PARAMS == {"min_recall": 0.9, "min_margin": 0.2, "prose_words": 3, "max_region_lines": 12, "order_score_offset": 0.5,
                          "absorb_overlap": 0.5, "max_group_chars": 4000, "max_macro_depth": 8, "max_expander_calls": 20000}


# ---- placement (decision 5) --------------------------------------------------------------------------------------------
