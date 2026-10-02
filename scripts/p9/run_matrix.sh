#!/usr/bin/env bash
# P9 acceptance matrix, one command. H1 adds the install and start rows (I01 to I05, I07; I08 is manual).
# Later batches append their own rows below the harness call, each writing its raw output under .local/p9-<batch>/.
set -u
cd "$(dirname "$0")/../.." || exit 2

python3 scripts/p9/install_check.py "$@"
status=$?

# H2 and later: add the next harness here and fold its status into `status`.
exit "$status"
