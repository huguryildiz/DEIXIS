"""store_pdf_file (P9 H2, F02): a final `<sha>.pdf` is whole or absent, and no temporary file is left behind."""

import hashlib
import os

import pytest

from deixis.documents import pdf_files

DATA = b"%PDF-1.4 SYNTHETIC " + b"x" * 5000
SHA = hashlib.sha256(DATA).hexdigest()


def test_fresh_write(tmp_path):
    path = pdf_files.store_pdf_file(tmp_path, SHA, DATA)
    assert path == tmp_path / f"{SHA}.pdf" and path.read_bytes() == DATA
    assert [p.name for p in tmp_path.iterdir()] == [path.name]


def test_a_correct_file_is_reused_not_rewritten(tmp_path):
    path = pdf_files.store_pdf_file(tmp_path, SHA, DATA)
    os.utime(path, ns=(1_000_000_000, 1_000_000_000))
    assert pdf_files.store_pdf_file(tmp_path, SHA, DATA) == path
    assert path.stat().st_mtime_ns == 1_000_000_000
    assert [p.name for p in tmp_path.iterdir()] == [path.name]


def test_a_truncated_file_is_replaced(tmp_path):
    (tmp_path / f"{SHA}.pdf").write_bytes(DATA[: len(DATA) // 2])
    path = pdf_files.store_pdf_file(tmp_path, SHA, DATA)
    assert path.read_bytes() == DATA
    assert [p.name for p in tmp_path.iterdir()] == [path.name]


def test_a_same_size_wrong_file_is_replaced(tmp_path):
    (tmp_path / f"{SHA}.pdf").write_bytes(b"y" * len(DATA))
    assert pdf_files.store_pdf_file(tmp_path, SHA, DATA).read_bytes() == DATA


def test_no_temporary_file_after_an_exception(tmp_path, monkeypatch):
    def refuse(source, target):
        raise OSError("SYNTHETIC replace failure")

    monkeypatch.setattr(pdf_files.os, "replace", refuse)
    with pytest.raises(OSError):
        pdf_files.store_pdf_file(tmp_path, SHA, DATA)
    assert list(tmp_path.iterdir()) == []
