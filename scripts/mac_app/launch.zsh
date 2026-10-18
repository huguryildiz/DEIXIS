#!/bin/zsh
# DEIXIS.app launcher (copied into the bundle by make_app.sh; REPO is filled in there).
# Opens the running DEIXIS if it answers and its code is current. When the code changed after
# that server started, restarts it, but only while no run or background fetch is working.
# Otherwise rebuilds the UI when its sources changed, starts the server in the background and
# opens the page once it answers. DEIXIS_PORT and DEIXIS_DATA_DIR override the defaults (tests).
REPO="__REPO__"
PORT="${DEIXIS_PORT:-8765}"
URL="http://127.0.0.1:$PORT/"
DB="${DEIXIS_DATA_DIR:-$HOME/Library/Application Support/DEIXIS}/library.sqlite"
LOG="$HOME/Library/Logs/DEIXIS/server.log"
export PATH="$HOME/.local/bin:/opt/homebrew/bin:/usr/local/bin:/usr/bin:/bin:/usr/sbin:/sbin"
mkdir -p "${LOG:h}"
note() { osascript -e "display notification \"$1\" with title \"DEIXIS\"" >/dev/null 2>&1 }
up() { curl -s -o /dev/null -m 2 "$URL" }
fail() { note "$1 — see ~/Library/Logs/DEIXIS/server.log"; open -a Console "$LOG"; exit 1 }

cd "$REPO" || { note "Repo not found: $REPO"; exit 1; }

if up; then
  PID=$(lsof -nP -tiTCP:$PORT -sTCP:LISTEN | head -1)
  [[ -n $PID ]] || { open "$URL"; exit 0; }
  # A file stamped with the server's start time; any source newer than it means the server runs old code.
  REF=$(mktemp)
  touch -t "$(date -j -f '%a %b %d %T %Y' "$(ps -o lstart= -p $PID | xargs)" +%Y%m%d%H%M.%S)" "$REF"
  STALE=$(find backend methods contracts pyproject.toml uv.lock apps/web/src apps/web/public apps/web/index.html \
    -type f -newer "$REF" -print -quit 2>/dev/null)
  rm -f "$REF"
  if [[ -z $STALE ]]; then open "$URL"; exit 0; fi
  BUSY=$(sqlite3 -readonly "$DB" "SELECT (SELECT count(*) FROM runs WHERE status IN ('queued','running','pause_requested'))
    + (SELECT count(*) FROM fast_path_background_fetches WHERE status IN ('queued','running'))" 2>/dev/null)
  if [[ $BUSY != 0 ]]; then
    note "A newer version is ready. Open DEIXIS again when the current run has finished."
    open "$URL"; exit 0
  fi
  note "Restarting with the new version…"
  kill -TERM $PID
  for i in {1..40}; do up || break; sleep 0.5; done
  up && fail "The old server did not stop"
fi

DIST=apps/web/dist/index.html
if [[ ! -f $DIST ]] || [[ -n "$(find apps/web/src apps/web/public apps/web/index.html apps/web/package.json -newer $DIST -print -quit 2>/dev/null)" ]]; then
  note "Building the interface…"
  (cd apps/web && { [[ -d node_modules ]] || npm ci; } && npm run build) >>"$LOG" 2>&1 || fail "UI build failed"
fi

note "Starting…"
nohup uv run python -m deixis serve --no-browser --port $PORT >>"$LOG" 2>&1 &
for i in {1..90}; do
  if up; then open "$URL"; exit 0; fi
  sleep 1
done
fail "Server did not start"
