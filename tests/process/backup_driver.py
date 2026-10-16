"""P9 H2 backup driver: `python -m deixis backup <dest>` with one point at which it stops and waits to be killed.

Not a test module. DEIXIS_DATA_DIR names the prepared library. `P9_BACKUP_HOLD` selects the point and `P9_BACKUP_HELD`
the file written when it is reached:
  during_files     the first `shutil.copyfile` inside `deixis.storage.backup` (before it copies anything)
  before_manifest  the `json.dumps` of the manifest (every file is copied, no manifest exists)
  after_manifest   the real `create_backup` has returned (the manifest is published), before the path is printed
`backup.shutil` and `backup.json` are replaced by wrappers; backup.py itself is not edited.
"""

import os
import sys
import time
from pathlib import Path

REPO = Path(__file__).resolve().parents[2]
sys.path[:0] = [str(REPO / "backend")]

from deixis import __main__ as deixis_main  # noqa: E402
from deixis.storage import backup  # noqa: E402

MODE = os.environ["P9_BACKUP_HOLD"]
HELD = Path(os.environ["P9_BACKUP_HELD"])


def hold() -> None:
    HELD.write_text(MODE)
    time.sleep(3600)


class Wrapper:
    def __init__(self, real, name, before):
        self._real, self._name, self._before = real, name, before

    def __getattr__(self, attribute):
        value = getattr(self._real, attribute)
        if attribute != self._name:
            return value

        def hooked(*args, **kwargs):
            self._before()
            return value(*args, **kwargs)

        return hooked


if MODE == "during_files":
    backup.shutil = Wrapper(backup.shutil, "copyfile", hold)
elif MODE == "before_manifest":
    backup.json = Wrapper(backup.json, "dumps", hold)
elif MODE == "after_manifest":
    real_create = backup.create_backup

    def create_then_hold(settings, destination):
        target = real_create(settings, destination)
        hold()
        return target

    backup.create_backup = create_then_hold
else:
    sys.exit(f"unknown P9_BACKUP_HOLD {MODE!r}")

sys.exit(deixis_main.main(["backup", sys.argv[1]]))
