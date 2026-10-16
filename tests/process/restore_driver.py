"""P9 H4 restore driver: `python -m deixis restore <backup>` with one point at which it stops and waits to be killed.

Not a test module. DEIXIS_DATA_DIR names the (empty) target. `P9_RESTORE_HOLD` selects the point, `P9_RESTORE_HELD` is the
file written when it is reached:
  file_copy   the nth `shutil.copyfile` inside `deixis.storage.backup` (`P9_RESTORE_NTH`, default 1; the files come first,
              the database staging copy last) first writes the first half of its source to the destination it was given
              (a write cut by SIGKILL), writes the held file and sleeps. On the old code that destination is the final,
              hash-named file; on the fixed code it is a `.restoring-*.part` file.
  db_replace  the `os.replace` that puts `library.sqlite` in place: every file is placed and the staging copy is complete.
`backup.shutil` and `backup.os` are replaced by wrappers; backup.py itself is not edited.
"""

import os
import sys
import time
from pathlib import Path

REPO = Path(__file__).resolve().parents[2]
sys.path[:0] = [str(REPO / "backend")]

from deixis import __main__ as deixis_main  # noqa: E402
from deixis.storage import backup  # noqa: E402

MODE = os.environ["P9_RESTORE_HOLD"]
HELD = Path(os.environ["P9_RESTORE_HELD"])
NTH = int(os.environ.get("P9_RESTORE_NTH", "1"))


def hold(note: str) -> None:
    HELD.write_text(note)
    time.sleep(3600)


class Wrapper:
    def __init__(self, real, name, hooked):
        self._real, self._name, self._hooked = real, name, hooked

    def __getattr__(self, attribute):
        value = getattr(self._real, attribute)
        return self._hooked(value) if attribute == self._name else value


if MODE == "file_copy":
    calls = []

    def cut_copy(real_copyfile):
        def copyfile(src, dst, **kwargs):
            calls.append(Path(dst).name)
            if len(calls) == NTH:
                data = Path(src).read_bytes()
                with open(dst, "wb") as handle:
                    handle.write(data[: len(data) // 2])
                    handle.flush()
                    os.fsync(handle.fileno())
                hold(f"{Path(dst).name} {len(data) // 2}/{len(data)}")
            return real_copyfile(src, dst, **kwargs)
        return copyfile

    backup.shutil = Wrapper(backup.shutil, "copyfile", cut_copy)
elif MODE == "db_replace":
    def hold_database_replace(real_replace):
        def replace(src, dst, *args, **kwargs):
            if Path(dst).name == backup.DB_NAME:
                hold(f"replace {Path(src).name} -> {Path(dst).name}")
            return real_replace(src, dst, *args, **kwargs)
        return replace

    backup.os = Wrapper(backup.os, "replace", hold_database_replace)
else:
    sys.exit(f"unknown P9_RESTORE_HOLD {MODE!r}")

sys.exit(deixis_main.main(["restore", sys.argv[1]]))
