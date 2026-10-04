"""Fail if watch code admits evidence or writes a library table."""

import ast
from pathlib import Path
import re


def test_watch_package_has_no_library_writer_or_sql_mutation():
    root = Path("backend/deixis/workflow/watch")
    forbidden_calls = {"record_search", "add_search_run", "upsert_provider_source", "add_to_corpus", "link_records"}
    library = {"sources", "source_versions", "works", "corpus_memberships", "candidates", "candidate_hits",
               "search_runs", "identifier_mappings", "record_links", "selections", "passages"}
    for path in root.glob("*.py"):
        tree = ast.parse(path.read_text())
        for node in ast.walk(tree):
            if isinstance(node, ast.Call) and isinstance(node.func, ast.Attribute):
                assert node.func.attr not in forbidden_calls and not node.func.attr.startswith("add_asset"), (path, node.lineno)
            if isinstance(node, ast.Constant) and isinstance(node.value, str):
                for statement in node.value.split(";"):
                    if re.search(r"\b(?:INSERT|UPDATE|DELETE|REPLACE|DROP|ALTER)\b", statement, re.I):
                        assert not any(re.search(r"\b" + t + r"\b", statement, re.I) for t in library), (path, node.lineno, statement)


def test_check_is_pure_and_only_reads_provider_constants():
    tree = ast.parse(Path("backend/deixis/workflow/watch/check.py").read_text())
    for node in ast.walk(tree):
        if isinstance(node, ast.Call) and isinstance(node.func, ast.Attribute):
            assert node.func.attr not in ("execute", "transaction")
        if isinstance(node, ast.ImportFrom):
            assert not node.module.startswith(("deixis.workflow.store", "deixis.workflow.flow", "deixis.providers"))
