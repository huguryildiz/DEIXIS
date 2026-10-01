"""H0b: show where the PDF extraction child is while it grows, and whether its own threads can run (D138).

Builds the same one-page PDF as `memory_probe.py`, runs `pdf._extract_in_process` in a child with the in-child watchdog
and a second ticker thread, and asks `faulthandler` for every thread's stack after `--seconds`. If the ticker prints
nothing after its first lines, the interpreter lock was held by one long C call and no Python thread could run. Prints the
child's stderr. Run from the repo root with `PYTHONPATH=backend`."""

from __future__ import annotations

import argparse
import subprocess
import sys
import tempfile
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
import memory_probe  # noqa: E402

CHILD = """
import faulthandler, resource, sys, threading, time
faulthandler.dump_traceback_later(SECONDS, exit=True)
from deixis.documents import pdf
def tick():
    t0 = time.time()
    while True:
        time.sleep(0.5)
        print("tick %.1f s, peak rss %d MiB" % (time.time() - t0, resource.getrusage(resource.RUSAGE_SELF).ru_maxrss / 2**20), file=sys.stderr, flush=True)
threading.Thread(target=tick, daemon=True).start()
pdf._watch_memory(LIMIT)
pdf._extract_in_process("PATH", 3000000)
"""


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--decoded-mib", type=int, default=67)
    parser.add_argument("--limit-mib", type=int, default=100)
    parser.add_argument("--seconds", type=int, default=8)
    args = parser.parse_args()
    backend = Path(__file__).resolve().parents[2] / "backend"
    with tempfile.TemporaryDirectory() as tmp:
        path = Path(tmp) / "probe.pdf"
        memory_probe.build_pdf(path, args.decoded_mib * memory_probe.MIB)
        code = CHILD.replace("SECONDS", str(args.seconds)).replace("LIMIT", str(args.limit_mib * memory_probe.MIB)).replace("PATH", str(path))
        done = subprocess.run([sys.executable, "-c", code], capture_output=True, text=True, env={"PYTHONPATH": str(backend)})
    print(f"exit code {done.returncode} (1 = faulthandler timeout; 3 would be the in-child watchdog)")
    print(done.stderr)


if __name__ == "__main__":
    main()
