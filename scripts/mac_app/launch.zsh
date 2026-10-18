#!/bin/zsh
# DEIXIS.app launcher (copied into the bundle by make_app.sh; REPO is filled in there).
# Opens the running DEIXIS if it answers; otherwise rebuilds the UI when its sources
# changed, starts the server in the background and opens the page once it answers.
REPO="__REPO__"
URL="http://127.0.0.1:8765/"
LOG="$HOME/Library/Logs/DEIXIS/server.log"
export PATH="$HOME/.local/bin:/opt/homebrew/bin:/usr/local/bin:/usr/bin:/bin"
mkdir -p "${LOG:h}"
note() { osascript -e "display notification \"$1\" with title \"DEIXIS\"" >/dev/null 2>&1 }
up() { curl -s -o /dev/null -m 2 "$URL" }
fail() { note "$1 — see ~/Library/Logs/DEIXIS/server.log"; open -a Console "$LOG"; exit 1 }

if up; then open "$URL"; exit 0; fi

cd "$REPO" || { note "Repo not found: $REPO"; exit 1; }
DIST=apps/web/dist/index.html
if [[ ! -f $DIST ]] || [[ -n "$(find apps/web/src apps/web/public apps/web/index.html apps/web/package.json -newer $DIST -print -quit 2>/dev/null)" ]]; then
  note "Building the interface…"
  (cd apps/web && { [[ -d node_modules ]] || npm ci; } && npm run build) >>"$LOG" 2>&1 || fail "UI build failed"
fi

note "Starting…"
nohup uv run python -m deixis serve --no-browser >>"$LOG" 2>&1 &
for i in {1..90}; do
  if up; then open "$URL"; exit 0; fi
  sleep 1
done
fail "Server did not start"
