"""Workspaces for owed-kit tests, independent of pytest's repository basetemp."""

from pathlib import Path
import tempfile

import pytest


@pytest.fixture
def tmp_path():
    # Resolve /tmp before creating paths: K6 rejects symlink ancestors and
    # permits external databases only under /tmp, including on macOS.
    with tempfile.TemporaryDirectory(
        prefix="deixis-owed-kit-", dir=Path("/tmp").resolve()
    ) as root:
        yield Path(root)
