#!/bin/zsh
# DEIXIS.app launcher (copied into the bundle by make_app.sh; REPO is filled in there).
# Every click starts a clean server: stops the one already listening, rebuilds the UI when its
# sources changed, starts the server in the background and opens the page once it answers.
# A run that was working is picked up again at startup (recovered runs, see /api/health).
# The launcher exits once the page opens, so the server stops itself after 15 minutes with no
# open tab polling it and no run working (--idle-exit).
# DEIXIS_PORT and DEIXIS_DATA_DIR override the defaults (tests).
REPO="__REPO__"
PORT="${DEIXIS_PORT:-8765}"
URL="http://127.0.0.1:$PORT/"
LOG="$HOME/Library/Logs/DEIXIS/server.log"
export PATH="$HOME/.local/bin:/opt/homebrew/bin:/usr/local/bin:/usr/bin:/bin:/usr/sbin:/sbin"
mkdir -p "${LOG:h}"
note() { osascript -e "display notification \"$1\" with title \"DEIXIS\"" >/dev/null 2>&1 }
up() { curl -s -o /dev/null -m 2 "$URL" }
fail() { note "$1 — see ~/Library/Logs/DEIXIS/server.log"; open -a Console "$LOG"; exit 1 }

cd "$REPO" || { note "Repo not found: $REPO"; exit 1; }

PIDS=$(lsof -nP -tiTCP:$PORT -sTCP:LISTEN)
if [[ -n $PIDS ]]; then
  note "Restarting…"
  kill -TERM ${(f)PIDS}
  for i in {1..40}; do lsof -nP -tiTCP:$PORT -sTCP:LISTEN >/dev/null || break; sleep 0.5; done
  lsof -nP -tiTCP:$PORT -sTCP:LISTEN >/dev/null && fail "The old server did not stop"
fi

DIST=web/dist/index.html
if [[ ! -f $DIST ]] || [[ -n "$(find web/src web/public web/index.html web/package.json -newer $DIST -print -quit 2>/dev/null)" ]]; then
  note "Building the interface…"
  (cd web && { [[ -d node_modules ]] || npm ci; } && npm run build) >>"$LOG" 2>&1 || fail "UI build failed"
fi

note "Starting…"
nohup uv run python -m deixis serve --no-browser --idle-exit 15 --port $PORT >>"$LOG" 2>&1 &
for i in {1..90}; do
  if up; then open "$URL"; exit 0; fi
  sleep 1
done
fail "Server did not start"
