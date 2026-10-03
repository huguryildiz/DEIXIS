"""Review-package read boundary, including B2's pure run planner."""

import ast
import inspect
import hashlib
from pathlib import Path

from deixis.workflow.review.reader import ReviewReader
from deixis.workflow.review.snapshot import build_snapshot
from deixis.workflow.review.stale import stale_reasons
from tests.review_helpers import report_with_sections, review_lib, all_rows


def test_review_package_import_and_write_boundary():
    root = Path("backend/deixis/workflow/review")
    assert (root / "run.py").is_file()
    forbidden = {"deixis.workflow.store", "deixis.workflow.report.store", "deixis.workflow.tables",
                 "deixis.workflow.candidates.store", "deixis.workflow.lineage.store", "deixis.workflow.flow"}
    for file in root.glob("*.py"):
        tree = ast.parse(file.read_text())
        type_only = set()
        for node in ast.walk(tree):
            if isinstance(node, ast.If) and isinstance(node.test, ast.Name) and node.test.id == "TYPE_CHECKING":
                type_only.update(id(n) for child in node.body for n in ast.walk(child))
        for node in ast.walk(tree):
            if isinstance(node, ast.ImportFrom) and node.module in forbidden and id(node) not in type_only:
                assert file.name == "store.py" and {n.name for n in node.names} <= {"NotFound", "RevisionConflict", "purge_owner_reviews"}
            if isinstance(node, ast.Import) and id(node) not in type_only:
                assert not any(n.name in forbidden for n in node.names)
            if isinstance(node, ast.Attribute):
                assert node.attr not in {"edit_claim", "save_claims", "save_answer", "save_review"}
            if isinstance(node, ast.Call):
                if file.name not in {"reader.py", "store.py"}:
                    assert not (isinstance(node.func, ast.Attribute) and node.func.attr in {"execute", "executemany", "executescript", "commit", "rollback"})
                    assert not (isinstance(node.func, ast.Name) and node.func.id == "transaction")
                if file.name == "reader.py" and isinstance(node.func, ast.Attribute) and node.func.attr == "execute":
                    assert isinstance(node.args[0], ast.Constant)
                    assert node.args[0].value.lstrip().upper().startswith(("SELECT", "WITH"))


def test_reader_public_methods_are_named_reads_only():
    names = {name for name, value in inspect.getmembers(ReviewReader, inspect.isfunction) if not name.startswith("_")}
    assert names == {"consistent_read", "research", "scope", "answer", "latest_answer", "answer_claims", "answer_links",
                     "report", "latest_report_version", "report_sections", "report_claims", "report_links", "report_snapshot",
                     "report_claim_revisions", "report_original_links",
                     "source", "source_access", "passage", "included_sources", "selection_stamp", "included_rows", "cells", "columns", "evidence_dependency", "evidence_exists"}
    assert not any(name.startswith(("save", "write", "edit", "delete", "insert", "update", "purge")) for name in names)


def test_snapshot_and_stale_reads_leave_every_table_unchanged(review_lib):
    def row_hashes():
        return {table: hashlib.sha256(repr(rows).encode("utf-8")).hexdigest()
                for table, rows in all_rows(lib["conn"]).items()}

    lib = review_lib; before = row_hashes()
    content, markers = build_snapshot(lib["reader"], lib["rid"], "report", lib["report_id"])
    assert row_hashes() == before
    row = {"research_id": lib["rid"], "target_kind": "report", "target_id": lib["report_id"], "content": content, "markers": markers}
    assert stale_reasons(lib["reader"], row) == []
    assert row_hashes() == before
    lib["reviews"].add_snapshot(content, markers)
    after = row_hashes()
    assert after["owner_review_snapshots"] != before["owner_review_snapshots"]
    assert {k: v for k, v in after.items() if k != "owner_review_snapshots"} == {k: v for k, v in before.items() if k != "owner_review_snapshots"}
