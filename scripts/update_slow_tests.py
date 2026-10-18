"""Add to tests/slow_tests.txt every test that took 0.2 s or more in the durations pytest-testmon stored (.testmondata).

Run after a full `uv run pytest --testmon -m "slow or not slow"`, so every test has a stored duration. Names already
listed stay; names testmon no longer knows are dropped. The default run then leaves the slow ones out (tests/conftest.py).
"""

import sqlite3
from datetime import date
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
LIST = ROOT / "tests" / "slow_tests.txt"
THRESHOLD = 0.2

rows = sqlite3.connect(f"file:{ROOT / '.testmondata'}?mode=ro", uri=True).execute(
    "SELECT test_name, max(coalesce(duration, 0)) FROM test_execution GROUP BY test_name").fetchall()
known = {name for name, _ in rows}
listed = {line for line in LIST.read_text().splitlines() if line and not line.startswith("#")}
slow = sorted((listed & known) | {name for name, seconds in rows if seconds >= THRESHOLD})
header = [f"# Tests that took {THRESHOLD} s or more (call + setup + teardown), from pytest-testmon's stored durations on "
          f"{date.today().isoformat()}, on a 10-core M-series Mac under load.",
          "# conftest.py marks them slow; the default run leaves them out. Regenerate: uv run python scripts/update_slow_tests.py"]
LIST.write_text("\n".join(header + slow) + "\n")
print(f"{len(slow)} slow tests listed ({len(slow) - len(listed & known)} new, {len(listed - known)} gone)")
