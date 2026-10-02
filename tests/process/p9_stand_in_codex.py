"""P9 H2 stand-in for `codex app-server`: answers `initialize`, then ends when its stdin closes.

Not a test module and not the real program. Modes: `idle` reads stdin lines until EOF; `busy:S` sleeps S seconds without
reading stdin (so it cannot see EOF in that time), then reads until EOF. Whether the real `codex app-server` ends on EOF
is a property of that program and is not shown here.
"""

import json
import sys
import time

mode = sys.argv[1] if len(sys.argv) > 1 else "idle"
request = json.loads(sys.stdin.readline())
sys.stdout.write(json.dumps({"id": request["id"], "result": {"userAgent": "p9-stand-in"}}) + "\n")
sys.stdout.flush()
if mode.startswith("busy:"):
    time.sleep(float(mode.split(":", 1)[1]))
for _ in sys.stdin:
    pass
