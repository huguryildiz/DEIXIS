"""The macOS app's saved report PDF: the shell asks the backend to stamp the footer WebKit cannot draw.

SYNTHETIC PDF in a temporary home folder; no WebKit runs. Passing shows the stamp route's checks and the footer text on
every page, not how the footer looks next to a real report.
"""

from __future__ import annotations

from pathlib import Path

import pymupdf
from fastapi.testclient import TestClient

from deixis.api.app import create_app
from deixis.runtime.config import Settings
from fakes import FakeAdapter


def test_the_shell_stamps_the_wordmark_and_page_numbers_on_a_pdf_in_downloads(tmp_path, monkeypatch):
    monkeypatch.setattr(Path, "home", classmethod(lambda cls: tmp_path))
    (tmp_path / "Downloads").mkdir()
    doc = pymupdf.open()
    for _ in range(3):
        doc.new_page(width=595, height=842).insert_text((72, 100), "SYNTHETIC report text")
    doc.save(tmp_path / "Downloads" / "report.pdf")
    app = create_app(Settings(data_dir=tmp_path / "data", port=8765, model_concurrency=1), adapters={"fake": FakeAdapter()},
                     start_worker=False, extra_hosts=("testserver",), trusted_clients=("testclient",), control_token="SYNTHETIC-token")
    with TestClient(app) as client:
        stamp = lambda name, token="SYNTHETIC-token": client.post("/api/internal/stamp-pdf", params={"name": name},  # noqa: E731
                                                                  headers={"x-deixis-control": token})
        assert stamp("report.pdf", token="wrong").status_code == 403
        assert stamp("../report.pdf").status_code == 404  # a path, not a file name in Downloads
        assert stamp("missing.pdf").status_code == 404
        assert stamp("report.pdf").json() == {"pages": 3}
    stamped = pymupdf.open(tmp_path / "Downloads" / "report.pdf")
    for number, page in enumerate(stamped, 1):
        # The wordmark is one image; the page number is text at the bottom right.
        assert str(number) in page.get_text(clip=pymupdf.Rect(400, 780, 595, 842)) and len(page.get_images()) == 1
