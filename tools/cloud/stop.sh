#!/usr/bin/env bash
# Stop the cloud trial cleanly and keep what it made. specs/021-cloud-trial.
#
# Called by the notebook's "Stop and save" cell and by bootstrap.sh's timer
# before Kaggle's session limit. Safe to run twice: the second run finds
# nothing running and copies again.
#
# Ctrl-C (SIGINT) to the engine, not a kill: that is what sets SHUTTING_DOWN,
# so the console's banner says "stopping now" and open streams are released.

set -uo pipefail

TRIAL="${VG_TRIAL_DIR:-/tmp/vg-trial}"
OUT="${VG_OUTPUT_DIR:-/kaggle/working}/trial-$(date -u +%Y%m%d)"
PY="${PYTHON:-python3}"

stop_pid() {  # stop_pid file signal seconds
  local file="$1" sig="$2" wait="$3" pid
  [[ -f "$file" ]] || return 0
  pid="$(cat "$file")"
  if kill -0 "$pid" 2>/dev/null; then
    kill -s "$sig" "$pid" 2>/dev/null || true
    for _ in $(seq 1 "$wait"); do kill -0 "$pid" 2>/dev/null || break; sleep 1; done
    kill -0 "$pid" 2>/dev/null && kill -9 "$pid" 2>/dev/null || true
  fi
  rm -f "$file"
}

echo "stopping the engine (it has up to 30 s to finish) ..."
stop_pid "$TRIAL/engine.pid" INT 30
stop_pid "$TRIAL/cloudflared.pid" TERM 5
# Not the watchdog when the watchdog is what called this.
[[ -f "$TRIAL/watchdog.pid" && "$(cat "$TRIAL/watchdog.pid")" != "$PPID" ]] \
  && stop_pid "$TRIAL/watchdog.pid" TERM 1

mkdir -p "$OUT"
if [[ -f "$TRIAL/visionguard.db" ]]; then
  # sqlite's own backup: a consistent copy even if a write was in flight.
  "$PY" - "$TRIAL/visionguard.db" "$OUT/visionguard.db" <<'EOF'
import sqlite3, sys
src, dst = sqlite3.connect(sys.argv[1]), sqlite3.connect(sys.argv[2])
with dst:
    src.backup(dst)
src.close(); dst.close()
EOF
fi
for item in summary.md engine.log cloudflared.log tensorrt.log watchdog.log url.txt ends-at.txt evidence clips; do
  [[ -e "$TRIAL/$item" ]] && cp -r "$TRIAL/$item" "$OUT/"
done
date -u +"stopped and saved %Y-%m-%dT%H:%M:%SZ" | tee -a "$OUT/summary.md"
echo "saved to $OUT:"
ls -la "$OUT"
