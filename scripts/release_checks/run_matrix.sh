#!/usr/bin/env bash
# P9 acceptance matrix, one command: every automatic (S, G, A) row of plan section 4, then the result table.
#   scripts/release_checks/run_matrix.sh [--only a,b] [--skip a,b] [--out-dir DIR] [--overlay-uncommitted] [--keep] [--self-test]
# The work is in run_matrix.py; raw output goes to .local/release-checks/matrix/<stamp>/ (ignored by Git). Exit 0 only when every mandatory row is geçti.
set -u
cd "$(dirname "$0")/../.." || exit 2

if [ "$(uname -m)" != "arm64" ]; then
  echo "refused: native arm64 only (plan section 2); uname -m says $(uname -m)" >&2
  exit 2
fi
PY=.venv/bin/python
[ -x "$PY" ] || PY=python3
exec "$PY" scripts/release_checks/run_matrix.py "$@"
