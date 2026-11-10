#!/usr/bin/env bash
# VisionGuard - the double-click launcher for Ubuntu (the Jetson).
#
# The same job launch.ps1 does on Windows: start the engine, open the console
# once the engine answers, and stop everything when the window is closed.
#
#   ./launch.sh                webcam / configured cameras
#   ./launch.sh --clip         the labelled recording instead of the webcam
#   ./launch.sh --mock         fixtures only, no models, no camera
#   ./launch.sh --no-browser   start it, open nothing
#
# One address: the engine serves the built console (web/dist) itself, so there
# is no dev server. Build it once with `cd web && npm ci && npm run build`.
# Re-create the desktop icon with:  tools/install-shortcut.sh
#
# Closing the window stops the engine. Two things make that hold however the
# launcher dies: `setpriv --pdeathsig KILL` (the engine is killed if its parent
# is) and a trap that sends the engine SIGINT - the same signal as Ctrl-C, which
# lets it release cameras and say "stopping" - and SIGKILL after 10 s.

set -uo pipefail

ROOT="$(cd "$(dirname "$(readlink -f "${BASH_SOURCE[0]}")")" && pwd)"
cd "$ROOT" || exit 1

PORT=8000
URL="http://localhost:$PORT"
WAIT_SECONDS=90
STATE="${XDG_STATE_HOME:-$HOME/.local/state}/visionguard"
LOG="$STATE/engine.log"

MOCK=0
CLIP=0
BROWSER=1
for arg in "$@"; do
  case "$arg" in
    --mock) MOCK=1 ;;
    --clip) CLIP=1 ;;
    --no-browser) BROWSER=0 ;;
    -h|--help) sed -n '2,15p' "${BASH_SOURCE[0]}" | sed 's/^# \{0,1\}//'; exit 0 ;;
    *) echo "launch.sh: unknown option $arg (try --help)" >&2; exit 2 ;;
  esac
done

# A double-click has no terminal to read, so an error goes where somebody
# looking at the screen will see it: zenity, else notify-send, else the
# terminal.
fail() {
  echo "VisionGuard: $1" >&2
  if command -v zenity >/dev/null 2>&1 && [[ -n "${DISPLAY:-}${WAYLAND_DISPLAY:-}" ]]; then
    zenity --error --title "VisionGuard" --no-markup --text "$1" 2>/dev/null
  elif command -v notify-send >/dev/null 2>&1; then
    notify-send --urgency=critical "VisionGuard" "$1"
  fi
  exit 1
}

if [[ -x "$ROOT/.venv/bin/python" ]]; then
  PY="$ROOT/.venv/bin/python"
elif command -v python3 >/dev/null 2>&1; then
  PY="$(command -v python3)"
else
  fail "Python 3 was not found. Install it, or create the project's .venv."
fi

[[ -f "$ROOT/web/dist/index.html" ]] \
  || fail "The console is not built ($ROOT/web/dist is missing). Run: cd web && npm ci && npm run build"

answers() {  # answers URL -> 0 when something replies
  "$PY" -c 'import sys, urllib.request; urllib.request.urlopen(sys.argv[1], timeout=2)' "$1" \
    >/dev/null 2>&1
}

if answers "$URL/healthz"; then
  fail "Something is already answering on port $PORT - VisionGuard may already be running."
fi

mkdir -p "$STATE"
export PYTHONUNBUFFERED=1
export VG_CONSOLE_DIR="$ROOT/web/dist"
[[ $MOCK -eq 1 ]] && export VG_MOCK=1
[[ $CLIP -eq 1 ]] && export VG_CAMERAS=cam-clip

# setpriv is part of util-linux. Without it the trap below still stops the
# engine on a normal exit; only a killed launcher could leave it running.
PDEATH=()
command -v setpriv >/dev/null 2>&1 && PDEATH=(setpriv --pdeathsig KILL)

ENGINE_PID=""
stop_engine() {
  local pid="$ENGINE_PID"
  ENGINE_PID=""
  [[ -n "$pid" ]] && kill -0 "$pid" 2>/dev/null || return 0
  kill -s INT "$pid" 2>/dev/null || true
  for _ in $(seq 1 10); do
    kill -0 "$pid" 2>/dev/null || return 0
    sleep 1
  done
  kill -s KILL "$pid" 2>/dev/null || true
}
trap stop_engine EXIT
trap 'exit 130' INT TERM HUP

echo "VisionGuard: starting the engine ($PY) ..."
if [[ -t 1 ]]; then
  "${PDEATH[@]}" "$PY" "$ROOT/engine/tools/serve.py" &
else
  "${PDEATH[@]}" "$PY" "$ROOT/engine/tools/serve.py" >"$LOG" 2>&1 &
fi
ENGINE_PID=$!

# Listening is not the same as answering: wait for /healthz, and give up the
# moment the engine has died instead of waiting out the clock.
ready=0
for _ in $(seq 1 "$WAIT_SECONDS"); do
  if ! kill -0 "$ENGINE_PID" 2>/dev/null; then
    ENGINE_PID=""
    fail "The engine stopped while starting. Its log: $LOG"
  fi
  if answers "$URL/healthz"; then ready=1; break; fi
  sleep 1
done
[[ $ready -eq 1 ]] || fail "The engine did not answer within $WAIT_SECONDS seconds. Its log: $LOG"
echo "VisionGuard: ready at $URL"

if [[ $BROWSER -eq 1 ]]; then
  BROWSER_BIN=""
  for name in chromium-browser chromium google-chrome; do
    command -v "$name" >/dev/null 2>&1 && { BROWSER_BIN="$name"; break; }
  done
  if [[ -n "$BROWSER_BIN" ]]; then
    # A dedicated profile makes this a window of its own that this command
    # waits for. Chromium here is a snap, which refuses a profile outside
    # $HOME. Without one the command hands over to the running browser and
    # returns at once, and the trap would stop the engine under the page.
    started=$SECONDS
    "$BROWSER_BIN" --app="$URL" --user-data-dir="$HOME/.config/visionguard-window" \
      --no-first-run >/dev/null 2>&1
    if (( SECONDS - started < 5 )); then
      echo "VisionGuard: the window closed at once, so the engine is left running."
      echo "             Press Ctrl-C here to stop it."
      wait "$ENGINE_PID"
    fi
    exit 0
  fi
  echo "VisionGuard: no Chromium or Chrome found; open $URL yourself."
fi

# --no-browser, or no browser to wait for: run until the engine stops or Ctrl-C.
wait "$ENGINE_PID"
