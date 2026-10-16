"""Figure and equation reads of a stored PDF run in a bounded child process, never in the server process."""

import json
import os
import subprocess
import threading
import time
from concurrent.futures import ThreadPoolExecutor

import pymupdf
import pytest

from deixis.documents import arxiv_source, equation_regions, figures, math_reader
from test_figures import figure_pdf

CROP = {"page": 1, "box": [100, 150, 400, 300], "dpi": 100, "cut": []}


def test_figure_and_equation_reads_do_not_open_the_pdf_in_the_server_process(tmp_path, monkeypatch):
    path = tmp_path / "fig.pdf"
    path.write_bytes(figure_pdf())

    def opened_here(*args, **kwargs):
        raise AssertionError("PyMuPDF opened the PDF in the server process")

    monkeypatch.setattr(pymupdf, "open", opened_here)
    assert [f["label"] for f in figures.find_figures(path)] == ["1"]
    assert figures.find_algorithms(path) == []
    assert figures.render_figure(path, 1, [100, 150, 400, 300]).startswith(b"\x89PNG")
    assert math_reader.math_pages(path) == []
    assert math_reader.table_pages(path) == []
    assert equation_regions.detect(path) == []
    assert arxiv_source.stamp_key(path) is None
    assert math_reader.check_equations(path, {0: [{"bbox": [100, 150, 400, 300], "latex": "z = 9"}]}) == []
    assert math_reader.inline_math_marks(path, [0]) == ({"0": []}, [])
    assert equation_regions.render_crop(path, CROP).startswith(b"\x89PNG")


def test_an_equation_read_stopped_at_its_memory_limit_fails_like_an_unreadable_pdf(tmp_path, monkeypatch):
    from deixis.documents import pdf_child

    path = tmp_path / "fig.pdf"
    path.write_bytes(figure_pdf())
    monkeypatch.setattr(pdf_child, "MAX_MEMORY_BYTES", 1024 * 1024)  # far below what a Python child starts with
    with pytest.raises(pdf_child.ChildFailed):
        math_reader.math_pages(path)
    with pytest.raises(pdf_child.ChildFailed):
        equation_regions.detect(path, set(), False)
    with pytest.raises(pdf_child.ChildFailed):
        math_reader.inline_math_marks(path, [0])
    with pytest.raises(pdf_child.ChildFailed):
        equation_regions.render_crop(path, CROP)


def test_no_more_than_two_pdf_children_run_at_once(monkeypatch):
    from deixis.documents import pdf, pdf_child

    running, most, lock = 0, 0, threading.Lock()

    def child(argv, env, timeout, max_memory):
        nonlocal running, most
        with lock:
            running += 1
            most = max(most, running)
        time.sleep(0.2)
        with lock:
            running -= 1
        return subprocess.CompletedProcess(argv, 0, b'{"result": []}', b"")

    monkeypatch.setattr(pdf, "_run_watched", child)
    with ThreadPoolExecutor(6) as pool:
        assert list(pool.map(lambda _: pdf_child.run("math_pages", "x.pdf"), range(6))) == [[]] * 6
    assert most == 2


def test_a_read_whose_input_is_longer_than_a_command_line_still_runs(tmp_path):
    path = tmp_path / "fig.pdf"
    path.write_bytes(figure_pdf())
    # 400 pages of ten long equations; only page 0 exists, the others are skipped as pages the PDF does not have.
    equations = {i: [{"bbox": [0, 0, 1, 1], "latex": "x" * 300} for _ in range(10)] for i in range(400)}
    assert len(json.dumps(sorted(equations.items()))) > os.sysconf("SC_ARG_MAX")
    assert math_reader.check_equations(path, equations) == []
