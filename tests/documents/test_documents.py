import asyncio
import os
import subprocess
import sys
import time
from pathlib import Path
from types import SimpleNamespace

import httpx
import pytest

from deixis.documents import fetch, pdf
from helpers import make_compressed_page_pdf, make_pdf


def test_extract_pdf_keeps_physical_pages(tmp_path):
    path = tmp_path / "synthetic.pdf"
    path.write_bytes(make_pdf(["SYNTHETIC page one about diffusion channels.", "", "Page three mentions a molecule budget."]))
    result = pdf.extract_pdf(path)
    assert result.page_count == 3
    assert result.status == "partial"  # page two has no text layer
    assert [p.physical_page for p in result.pages] == [1, 3]
    assert "molecule budget" in result.pages[1].text


def test_extraction_drops_the_ieee_xplore_download_notice(tmp_path):
    path = tmp_path / "watermarked.pdf"
    path.write_bytes(make_pdf([
        "SYNTHETIC body line one about packet sizes.\n"
        "Authorized licensed use limited to: SYNTHETIC University. Downloaded on\n"
        "September 15,2026 at 19:38:51 UTC from IEEE Xplore.  Restrictions apply.\n"
        "SYNTHETIC body line two about relays.",
    ]))
    text = pdf.extract_pdf(path).pages[0].text
    assert "Authorized licensed" not in text and "Restrictions apply" not in text and "IEEE Xplore" not in text
    assert "body line one about packet sizes." in text and "body line two about relays." in text
    assert pdf.EXTRACTION_VERSION.endswith("-layout-v2")

    one_line = ("ends here.\nAuthorized licensed use limited to: SYNTHETIC University. Downloaded on September 15,2026 at 19:45:08 UTC"
                " from IEEE Xplore.  Restrictions apply. \nNext")
    assert pdf.remove_download_notices(one_line) == "ends here.\nNext"
    # Only the whole notice is removed; a sentence that mentions licensed use stays.
    mention = "Authorized licensed use limited to: members. The rest of this sentence is body text."
    assert pdf.remove_download_notices(mention) == mention


def test_layout_extraction_moves_small_type_after_the_body_and_drops_page_furniture(tmp_path):
    import pymupdf

    doc = pymupdf.open()
    page = doc.new_page(width=612, height=792)
    page.insert_text((300, 30), "7", fontsize=7)  # page number
    page.insert_text((72, 40), "SYNTHETIC JOURNAL, VOL. 1, 2026", fontsize=7)  # running head
    page.insert_text((72, 120), "I. INTRODUCTION", fontsize=10)
    page.insert_text((72, 160), "SYNTHETIC body text about diffusion chan-", fontsize=10)
    page.insert_text((72, 172), "nels continues in the first column", fontsize=10)
    page.insert_text((72, 700), "A. Author is with the Department of SYNTHETIC Studies (e-mail: a@example.org).", fontsize=8)
    page.insert_text((320, 160), "and ends in the second column.", fontsize=10)
    page.insert_text((20, 600), "arXiv:2601.00001v1 [cs.NI]", fontsize=16, rotate=90)
    path = tmp_path / "layout.pdf"
    doc.save(path)

    text = pdf.extract_pdf(path).pages[0].text
    paragraphs = [" ".join(p.split()) for p in text.split("\n\n")]
    assert paragraphs[0] == "I. INTRODUCTION"
    assert "diffusion channels continues" in paragraphs[1]  # hyphenated line end joined
    assert paragraphs[-1].startswith("A. Author is with the Department")  # the note follows the body text
    assert "and ends in the second column." in " ".join(paragraphs[1:-1])
    assert "arXiv:2601" not in text and "SYNTHETIC JOURNAL" not in text and "7" not in text.split()


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


@pytest.mark.parametrize(
    "url",
    [
        "file:///etc/passwd",
        "http://127.0.0.1:8765/api/researches",
        "http://localhost/admin",
        "http://169.254.169.254/latest/meta-data",
        "http://10.0.0.5/paper.pdf",
        "http://[::1]/x.pdf",
        "https://user:pw@example.org/x.pdf",
    ],
)
def test_private_or_unsafe_urls_are_blocked(url):
    result = asyncio.run(fetch.fetch_pdf(url))
    assert result.status == "blocked_url"


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


def test_a_child_under_the_limit_runs_to_its_end_with_its_output():
    completed = pdf._run_watched(_child("import sys; sys.stdout.write('x' * 200000); sys.stderr.write('note'); sys.exit(0)"),
                                 PLAIN_ENV, timeout=30, max_memory=1024 * 1024 * 1024)
    assert (completed.returncode, len(completed.stdout), completed.stderr) == (0, 200000, b"note")


def _wait_for_pid(pid_file) -> int:
    deadline = time.monotonic() + 10
    while not (pid_file.exists() and pid_file.read_text()):
        assert time.monotonic() < deadline, "the child never wrote its pid"
        time.sleep(0.05)
    return int(pid_file.read_text())


def test_a_child_past_the_time_limit_is_killed_and_reaped(tmp_path):
    pid_file = tmp_path / "pid"
    code = f"import os, time; open({str(pid_file)!r}, 'w').write(str(os.getpid())); time.sleep(30)"
    started = time.monotonic()
    with pytest.raises(subprocess.TimeoutExpired):
        pdf._run_watched(_child(code), PLAIN_ENV, timeout=4, max_memory=1024 * 1024 * 1024)
    assert time.monotonic() - started < 20
    with pytest.raises(ProcessLookupError):
        os.kill(_wait_for_pid(pid_file), 0)  # gone, not left behind


def test_the_time_limit_holds_even_when_the_child_ends_just_after_it(monkeypatch):
    # The clock is replaced: the first two reads (the start and the first wait) give 0 and every later read is far past the
    # 10 s limit, while the child ends within its first 50 ms turn. A child that finishes after the deadline is a timeout all
    # the same. (A child slower than one turn meets the loop's own deadline check instead; the test passes either way.)
    reads = iter([0.0, 0.0])
    monkeypatch.setattr(pdf, "time", SimpleNamespace(monotonic=lambda: next(reads, 1000.0), sleep=time.sleep))
    with pytest.raises(subprocess.TimeoutExpired):
        pdf._run_watched(_child("pass"), PLAIN_ENV, timeout=10, max_memory=1024 * 1024 * 1024)


@pytest.mark.skipif(not pdf._watch_supported(), reason="the memory watch exists on macOS and Linux only")
def test_a_watch_that_cannot_read_the_child_is_a_visible_failure_not_a_clean_run(tmp_path, monkeypatch):
    monkeypatch.setattr(pdf, "_resident_bytes", lambda pid: None)
    monkeypatch.setattr(pdf, "WATCH_LOST_TURNS", 10)
    pid_file = tmp_path / "pid"
    code = f"import os, time; open({str(pid_file)!r}, 'w').write(str(os.getpid())); time.sleep(30)"
    started = time.monotonic()
    with pytest.raises(pdf.MemoryWatchLost):
        pdf._run_watched(_child(code), PLAIN_ENV, timeout=60, max_memory=1024 * 1024 * 1024)
    assert time.monotonic() - started < 15  # stopped after ten unreadable turns, not at the end of the sleep
    with pytest.raises(ProcessLookupError):
        os.kill(_wait_for_pid(pid_file), 0)  # killed and reaped


@pytest.mark.skipif(not pdf._watch_supported(), reason="the memory watch exists on macOS and Linux only")
def test_unreadable_turns_that_are_not_in_a_row_do_not_stop_a_child(monkeypatch):
    # Four unreadable turns, then one readable, again and again: more than five in all, never five in a row.
    reads = iter([None, None, None, None, 1] * 40)
    monkeypatch.setattr(pdf, "_resident_bytes", lambda pid: next(reads, 1))
    monkeypatch.setattr(pdf, "WATCH_LOST_TURNS", 5)
    completed = pdf._run_watched(_child("import time; time.sleep(1.5)"), PLAIN_ENV, timeout=30, max_memory=1024 * 1024 * 1024)
    assert completed.returncode == 0


@pytest.mark.skipif(not pdf._watch_supported(), reason="the memory watch exists on macOS and Linux only")
def test_a_child_that_ends_between_the_wait_and_the_read_is_not_a_lost_watch(monkeypatch):
    # Every read fails, but the child is finished by the time the watcher looks: that is a normal end, not MemoryWatchLost.
    monkeypatch.setattr(pdf, "WATCH_LOST_TURNS", 1)
    monkeypatch.setattr(pdf, "_resident_bytes", lambda pid: time.sleep(0.5))  # the "read" outlasts the child, and returns None
    completed = pdf._run_watched(["/bin/sleep", "0.2"], PLAIN_ENV, timeout=30, max_memory=1024 * 1024 * 1024)
    assert completed.returncode == 0


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
    sys.path.insert(0, str(Path(__file__).resolve().parents[2] / "scripts" / "p9"))
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


def test_fetch_connects_to_the_checked_address_so_a_second_dns_answer_is_not_used(monkeypatch):
    # First answer public, any later answer private (DNS rebinding).
    resolve, calls = resolver({"papers.example": ["93.184.216.34"]}, {"papers.example": ["127.0.0.1"]})
    monkeypatch.setattr(fetch, "_resolve", resolve)
    seen = []

    def handler(request):
        seen.append(request)
        return httpx.Response(200, content=make_pdf(["SYNTHETIC"]))

    async def run():
        async with httpx.AsyncClient(transport=httpx.MockTransport(handler)) as client:
            return await fetch.fetch_pdf("https://papers.example/a.pdf?x=1", client)

    result = asyncio.run(run())
    assert result.status == "ok" and calls == ["papers.example"]
    request = seen[0]
    assert (request.url.host, request.url.path, request.url.query) == ("93.184.216.34", "/a.pdf", b"x=1")
    assert request.headers["host"] == "papers.example" and request.extensions["sni_hostname"] == "papers.example"
    assert result.final_url == "https://papers.example/a.pdf?x=1"


def test_a_pdf_request_asks_for_a_pdf_and_names_the_contact_address(monkeypatch):
    resolve, _ = resolver({"papers.example": ["93.184.216.34"]})
    monkeypatch.setattr(fetch, "_resolve", resolve)
    monkeypatch.setenv("DEIXIS_CONTACT_EMAIL", "owner@example.org")
    seen = []

    def handler(request):
        seen.append(request)
        return httpx.Response(200, content=make_pdf(["SYNTHETIC"]))

    async def run():
        async with httpx.AsyncClient(transport=httpx.MockTransport(handler), headers={"User-Agent": fetch.user_agent()}) as client:
            return await fetch.fetch_pdf("https://papers.example/a.pdf", client)

    assert asyncio.run(run()).status == "ok"
    assert seen[0].headers["accept"] == fetch.PDF_ACCEPT
    assert seen[0].headers["user-agent"] == "DEIXIS/0.1 (local research workspace; mailto:owner@example.org)"
    monkeypatch.delenv("DEIXIS_CONTACT_EMAIL")
    assert fetch.user_agent() == fetch.USER_AGENT


def test_redirect_to_a_private_address_is_blocked(monkeypatch):
    resolve, _ = resolver({"papers.example": ["93.184.216.34"], "intranet.example": ["10.0.0.7"]})
    monkeypatch.setattr(fetch, "_resolve", resolve)

    def handler(request):
        return httpx.Response(302, headers={"location": "http://intranet.example/secret.pdf"})

    async def run():
        async with httpx.AsyncClient(transport=httpx.MockTransport(handler)) as client:
            return await fetch.fetch_pdf("https://papers.example/a.pdf", client)

    result = asyncio.run(run())
    assert result.status == "blocked_url" and result.final_url == "http://intranet.example/secret.pdf"
