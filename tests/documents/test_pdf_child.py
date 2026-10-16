"""Figure and equation reads of a stored PDF run in a bounded child process, never in the server process."""

import pymupdf
import pytest

from deixis.documents import arxiv_source, equation_regions, figures, math_reader
from test_figures import figure_pdf


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


def test_an_equation_read_stopped_at_its_memory_limit_fails_like_an_unreadable_pdf(tmp_path, monkeypatch):
    from deixis.documents import pdf_child

    path = tmp_path / "fig.pdf"
    path.write_bytes(figure_pdf())
    monkeypatch.setattr(pdf_child, "MAX_MEMORY_BYTES", 1024 * 1024)  # far below what a Python child starts with
    with pytest.raises(pdf_child.ChildFailed):
        math_reader.math_pages(path)
    with pytest.raises(pdf_child.ChildFailed):
        equation_regions.detect(path, set(), False)
