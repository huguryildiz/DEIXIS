"""Existing whole/torn/same-size/cleanup cases routed through staging and the sole placement driver."""

import hashlib
import os
import asyncio

import pytest

from deixis.documents import pdf_files
from deixis.workflow import file_restore
from deixis.storage import db
from deixis.workflow.store import Store

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


def test_fresh_write(tmp_path):
    path = place(tmp_path)
    assert path == tmp_path / f"{SHA}.pdf" and path.read_bytes() == DATA
    assert temporary_files(tmp_path) == []
    assert pdf_files.file_is_whole(path, SHA, len(DATA))


def test_a_correct_file_is_reused_not_rewritten(tmp_path):
    path = place(tmp_path)
    os.utime(path, ns=(1_000_000_000, 1_000_000_000))
    assert place(tmp_path) == path
    assert path.stat().st_mtime_ns == 1_000_000_000
    assert temporary_files(tmp_path) == []


def test_a_truncated_file_is_replaced(tmp_path):
    (tmp_path / f"{SHA}.pdf").write_bytes(DATA[: len(DATA) // 2])
    path = place(tmp_path)
    assert path.read_bytes() == DATA
    assert temporary_files(tmp_path) == []
    torn = DATA[:len(DATA) // 2]
    assert (tmp_path / ("retained-" + hashlib.sha256(torn).hexdigest() + ".bin")).read_bytes() == torn


def test_a_same_size_wrong_file_is_replaced(tmp_path):
    (tmp_path / f"{SHA}.pdf").write_bytes(b"y" * len(DATA))
    assert place(tmp_path).read_bytes() == DATA


def test_no_temporary_file_after_an_exception(tmp_path, monkeypatch):
    def refuse(source, target):
        raise OSError("SYNTHETIC replace failure")

    monkeypatch.setattr(file_restore.os, "replace", refuse)
    with pytest.raises(OSError):
        place(tmp_path)
    assert temporary_files(tmp_path) == []
    assert not (tmp_path / f"{SHA}.pdf").exists()
