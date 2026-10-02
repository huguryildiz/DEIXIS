"""P9 H7 item 05 (D165): no test module defines one test name twice in one scope."""

import ast
import collections
from pathlib import Path

TESTS = Path(__file__).parent


def test_no_test_name_is_defined_twice_in_one_scope():
    duplicates = []
    for path in sorted(TESTS.rglob("*.py")):
        def scan(body, scope):
            names = collections.Counter(
                n.name for n in body if isinstance(n, (ast.FunctionDef, ast.AsyncFunctionDef)) and n.name.startswith("test"))
            duplicates.extend(f"{path.relative_to(TESTS)}:{scope}{name}" for name, count in names.items() if count > 1)
            for node in body:
                if isinstance(node, ast.ClassDef):
                    scan(node.body, f"{node.name}.")
        scan(ast.parse(path.read_text()).body, "")
    assert duplicates == []
