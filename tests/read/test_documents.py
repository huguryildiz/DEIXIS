"""PDF text extraction in its child process: physical pages, page furniture, text and memory limits, the watcher (F09 at the production limit), and the stored file written whole. SYNTHETIC PDFs."""

import asyncio
import os
import sys
import time
from pathlib import Path
import pytest
from deixis.documents import pdf
from helpers import make_compressed_page_pdf, make_pdf
import hashlib
from deixis.workflow import file_restore
from deixis.storage import db
from deixis.workflow.store import Store
import pymupdf
from deixis.documents import figures


def test_extract_pdf_keeps_physical_pages(tmp_path):
    path = tmp_path / "synthetic.pdf"
    path.write_bytes(make_pdf(["SYNTHETIC page one about diffusion channels.", "", "Page three mentions a molecule budget."]))
    result = pdf.extract_pdf(path)
    assert result.page_count == 3
    assert result.status == "partial"  # page two has no text layer
    assert [p.physical_page for p in result.pages] == [1, 3]
    assert "molecule budget" in result.pages[1].text


def test_layout_extraction_drops_headers_and_footers_repeated_across_pages(tmp_path):
    import pymupdf

    doc = pymupdf.open()
    for n in range(1, 6):
        page = doc.new_page(width=612, height=792)
        page.insert_text((72, 40), f"J. Synthetic Eng. 2023, 11, 1567 {n} of 5", fontsize=10)  # body-size running head
        page.insert_text((72, 300), f"SYNTHETIC body text on page {n} about acoustic links.", fontsize=10)
        page.insert_text((72, 770), f"Synthetic Footer Journal, page {n}", fontsize=10)
    doc[0].insert_text((72, 735), "A one-off line at the bottom of the first page.", fontsize=10)
    path = tmp_path / "repeated.pdf"
    doc.save(path)

    pages = pdf.extract_pdf(path).pages
    for n, page in enumerate(pages, start=1):
        assert "Synthetic Eng" not in page.text and "Footer Journal" not in page.text
        assert f"body text on page {n} about acoustic links." in page.text
    assert "A one-off line at the bottom" in pages[0].text  # not repeated, so kept

    two = pymupdf.open()
    for n in range(1, 3):
        two.new_page(width=612, height=792).insert_text((72, 40), f"J. Synthetic Eng. {n} of 2", fontsize=10)
    two.save(tmp_path / "two.pdf")
    assert "J. Synthetic Eng." in pdf.extract_pdf(tmp_path / "two.pdf").pages[0].text  # too few pages to call it repeated


def test_a_numbered_reference_entry_is_one_paragraph():
    split_and_joined = ["[39] M. H. Author, D. J.", "Twitchen, “A SYNTHETIC title,” 2018.\n[40] Y.-A. Chen, J. Zhang,", "K. Chen et al., 2021."]
    assert pdf._paragraphs(split_and_joined) == [
        "[39] M. H. Author, D. J.\nTwitchen, “A SYNTHETIC title,” 2018.", "[40] Y.-A. Chen, J. Zhang,\nK. Chen et al., 2021."]
    assert pdf._paragraphs(["Body paragraph one.", "Body paragraph two."]) == ["Body paragraph one.", "Body paragraph two."]


def test_non_pdf_bytes_fail_extraction(tmp_path):
    path = tmp_path / "not.pdf"
    path.write_bytes(b"<html>not a pdf</html>")
    assert pdf.extract_pdf(path).status == "failed"


def test_chunk_page_respects_limit_and_covers_text():
    text = " ".join(f"Sentence {i} about channel capacity." for i in range(200))
    chunks = pdf.chunk_page(text, limit=300)
    assert all(len(c[2]) <= 300 for c in chunks)
    assert chunks[0][0] == 0 and chunks[-1][1] == len(text)


def test_extraction_stops_at_the_text_limit(tmp_path):
    path = tmp_path / "long.pdf"
    path.write_bytes(make_pdf([f"SYNTHETIC page {i} " + "word " * 40 for i in range(6)]))
    result = pdf.extract_pdf(path, max_chars=300)  # each line runs past the page edge; only its visible ~99 characters count
    assert result.status == "partial"
    assert sum(len(p.text) for p in result.pages) <= 300 and len(result.pages) < 6


def test_extraction_is_stopped_when_it_exceeds_the_memory_limit(tmp_path):
    # ~70 MB of decoded page content in a file of well under 1 MB.
    path = tmp_path / "expands.pdf"
    path.write_bytes(make_compressed_page_pdf(b"BT /F1 11 Tf 72 720 Td (" + b"A" * 70_000_000 + b") Tj ET"))
    assert path.stat().st_size < 1_000_000
    started = time.monotonic()
    result = pdf.extract_pdf(path, max_memory=100 * 1024 * 1024)
    assert (result.status, result.error) == ("failed", "extraction exceeded the memory limit")
    assert time.monotonic() - started < 30


def _child(code: str) -> list[str]:
    return [sys.executable, "-c", code]


PLAIN_ENV = {"PATH": os.environ.get("PATH", "")}


def test_the_parent_stops_a_child_that_holds_the_interpreter_lock_past_the_limit():
    # The in-child watchdog is a thread and cannot run while a C call holds the lock (D138). This child reserves 300 MiB with
    # `calloc` (untouched pages are not resident), reports `ready` while at about 30 MiB, then touches all of it inside
    # `memset` called through PyDLL, which keeps the lock, and then sleeps 30 s in a PyDLL `sleep`. The size crosses the limit
    # only inside those calls, so `ready` always precedes the stop; only a watcher outside the child can stop it, and it must
    # do so long before the sleep ends.
    code = ("import ctypes, sys\nlib = ctypes.PyDLL(None)\nlib.calloc.restype = ctypes.c_void_p\n"
            "lib.memset.argtypes = [ctypes.c_void_p, ctypes.c_int, ctypes.c_size_t]\n"
            "small = bytearray(30 * 1024 * 1024)\nfor i in range(0, len(small), 4096): small[i] = 1\n"
            "big = lib.calloc(1, 300 * 1024 * 1024)\nsys.stdout.write('ready'); sys.stdout.flush()\n"
            "lib.memset(big, 1, 300 * 1024 * 1024)\nlib.sleep(30)\n")
    started = time.monotonic()
    completed = pdf._run_watched(_child(code), PLAIN_ENV, timeout=60, max_memory=200 * 1024 * 1024)
    assert completed.returncode == pdf.MEMORY_EXIT_CODE and b"memory limit exceeded" in completed.stderr
    assert completed.stdout == b"ready"  # killed after it started, inside the lock-holding calls
    assert time.monotonic() - started < 20  # far from the 30 s the child would have slept


def _wait_for_pid(pid_file) -> int:
    deadline = time.monotonic() + 10
    while not (pid_file.exists() and pid_file.read_text()):
        assert time.monotonic() < deadline, "the child never wrote its pid"
        time.sleep(0.05)
    return int(pid_file.read_text())


def test_a_lost_memory_watch_is_reported_as_a_failed_extraction(tmp_path, monkeypatch):
    def lost(*args, **kwargs):
        raise pdf.MemoryWatchLost("unreadable")

    monkeypatch.setattr(pdf, "_run_watched", lost)
    path = tmp_path / "small.pdf"
    path.write_bytes(make_pdf(["SYNTHETIC"]))
    result = pdf.extract_pdf(path)
    assert (result.status, result.error) == ("failed", "extraction memory limit could not be watched")


@pytest.mark.skipif(os.environ.get("DEIXIS_P9_PRODUCTION_THRESHOLD") != "1", reason="F09 at the production limit takes about 30 s; set DEIXIS_P9_PRODUCTION_THRESHOLD=1")
def test_extraction_is_stopped_at_the_production_memory_limit(tmp_path):
    # ~200 MiB of decoded page content in a file of about 200 KB makes the extraction child grow past 1 GiB (D138).
    sys.path.insert(0, str(Path(__file__).resolve().parents[2] / "scripts" / "release_checks"))
    import memory_probe

    path = tmp_path / "expands-past-1gib.pdf"
    memory_probe.build_pdf(path, 200 * 1024 * 1024)
    result = pdf.extract_pdf(path)  # default max_memory: the production 1 GiB
    assert (result.status, result.error) == ("failed", "extraction exceeded the memory limit")


def resolver(*answers):
    calls = []

    async def resolve(host, port):
        calls.append(host)
        return answers[min(len(calls), len(answers)) - 1][host]
    return resolve, calls


def test_lines_mostly_unmapped_glyphs_become_one_marker():
    # SYNTHETIC: an algorithm block whose symbol font has no Unicode map, as MuPDF reports it (U+FFFD).
    block = {"bbox": (50, 300, 500, 400), "size": 10.0, "chars": 120, "lines": [
        "\ufffd \ufffd: a received packet", "if \ufffd \ufffd \ufffd", "\ufffd\ufffd \ufffd \ufffdthen", "\ufffd", "else discard"]}
    other = {"bbox": (50, 420, 500, 440), "size": 10.0, "chars": 10, "lines": ["\ufffd\ufffd \ufffd"]}
    text = pdf._page_text([block, other], 800, 10.0)
    assert text == f"\ufffd \ufffd: a received packet\n{pdf.UNREADABLE}\nelse discard\n\n{pdf.UNREADABLE}"
    # The U+FFFD a mark's next line opens with is taken into the mark.
    subscript = dict(block, lines=["\ufffd\ufffd", "\ufffd i: CURRENT ANGLE of node i"])
    assert pdf._page_text([subscript], 800, 10.0) == f"{pdf.UNREADABLE}i: CURRENT ANGLE of node i"
    assert pdf._readable("We start from the small base angle 2u, that is, 30\ufffd") .endswith("30\ufffd")


DATA = b"%PDF-1.4 SYNTHETIC " + b"x" * 5000


SHA = hashlib.sha256(DATA).hexdigest()


def place(folder):
    conn = db.connect(folder / "library.sqlite")
    db.migrate(conn)
    try:
        return asyncio.run(file_restore.store_pdf_file(Store(conn), folder, folder / "recovery", DATA,
                                                      caller="acquisition", research_id=None)).path
    finally:
        conn.close()


def temporary_files(folder):
    return [p for p in folder.iterdir() if p.suffix in (".part", ".partial")]


def test_a_truncated_file_is_replaced(tmp_path):
    (tmp_path / f"{SHA}.pdf").write_bytes(DATA[: len(DATA) // 2])
    path = place(tmp_path)
    assert path.read_bytes() == DATA
    assert temporary_files(tmp_path) == []
    torn = DATA[:len(DATA) // 2]
    assert (tmp_path / ("retained-" + hashlib.sha256(torn).hexdigest() + ".bin")).read_bytes() == torn


def test_no_temporary_file_after_an_exception(tmp_path, monkeypatch):
    def refuse(source, target):
        raise OSError("SYNTHETIC replace failure")

    monkeypatch.setattr(file_restore.os, "replace", refuse)
    with pytest.raises(OSError):
        place(tmp_path)
    assert temporary_files(tmp_path) == []
    assert not (tmp_path / f"{SHA}.pdf").exists()


# Figure regions found from captions on synthetic PDF pages (D58).

def algorithm_pdf() -> bytes:
    doc = pymupdf.open()
    page = doc.new_page()
    for y in (100, 114, 200):  # the rule above the caption, the one under it and the bottom rule
        page.draw_line((72, y), (300, y), width=0.5)
    page.insert_text((72, 110), "Algorithm 2 SYNTHETIC Greedy Assignment", fontsize=9)
    page.insert_text((72, 130), "1: for all SYNTHETIC items do", fontsize=9)
    page.insert_text((72, 190), "2: end for", fontsize=9)
    page.insert_text((72, 260), "Algorithm 2 first sorts the SYNTHETIC items; no rules surround this sentence.", fontsize=10)
    page.insert_text((72, 300), "Algorithm 3 SYNTHETIC caption with no ruled box", fontsize=9)
    return doc.tobytes()


def test_an_algorithm_box_runs_from_the_rule_above_its_caption_to_the_bottom_rule(tmp_path):
    path = tmp_path / "alg.pdf"
    path.write_bytes(algorithm_pdf())
    found = figures.find_algorithms(path)
    assert [(f["page"], f["label"]) for f in found] == [(1, "algorithm-2")]
    x0, y0, x1, y1 = found[0]["bbox"]
    assert x0 <= 72 and x1 >= 300 and 99 <= y0 <= 100 and 200 <= y1 <= 201
    assert figures.render_figure(path, 1, found[0]["bbox"]).startswith(b"\x89PNG")
