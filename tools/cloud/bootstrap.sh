#!/usr/bin/env bash
# The cloud trial, from a fresh Kaggle GPU session to a printed https address.
# specs/021-cloud-trial. Run by cloud/visionguard_trial.ipynb, from a copy of
# the repository in /tmp/vg (the notebook makes it from the code dataset).
#
#   VG_ADMIN_PASSWORD   required; the notebook reads it from a Kaggle secret
#   VG_MODELS_DIR       where the owner's models dataset is mounted
#                       (default: searched under /kaggle/input)
#   VG_TRIAL_HOURS      how long until the engine stops itself (default 11.5;
#                       Kaggle ends a GPU session at 12 h)
#   VG_SKIP_TENSORRT=1  run the .pt files and do not build engines
#
# Every step prints how long it took. The first one that fails stops the run
# and says which; nothing is downloaded but Python packages, ffmpeg and
# cloudflared, and no model is ever downloaded, sourced or trained.

set -euo pipefail

REPO="$(cd "$(dirname "${BASH_SOURCE[0]}")/../.." && pwd)"
TRIAL="${VG_TRIAL_DIR:-/tmp/vg-trial}"
OUT="${VG_OUTPUT_DIR:-/kaggle/working}"
SUMMARY="$TRIAL/summary.md"
PY="${PYTHON:-python3}"

# The cloud never runs the password-free developer sign-in. The engine also
# refuses it under the cloud profile; this makes sure it is never even asked.
unset VG_DEV_SIGNIN VG_STRICT

if [[ -e "$TRIAL/visionguard.db" ]]; then
  echo "FAILED: $TRIAL already holds a database. The trial starts from an empty one;"
  echo "        run tools/cloud/stop.sh, or restart the notebook's session."
  exit 1
fi
mkdir -p "$TRIAL/clips" "$TRIAL/evidence"
: > "$SUMMARY"

started_all=$SECONDS
note() { echo "$*" | tee -a "$SUMMARY"; }
step() {  # step "name" command...
  local name="$1"; shift
  local t0=$SECONDS
  echo
  echo "== $name"
  if "$@"; then
    note "- $name: ok, $((SECONDS - t0)) s"
  else
    note "- $name: **FAILED** after $((SECONDS - t0)) s"
    echo "FAILED at: $name. Paste everything above to Claude."
    exit 1
  fi
}

note "# Cloud trial session, $(date -u +%Y-%m-%dT%H:%M:%SZ)"
note ""

# --------------------------------------------------------------------- checks
check_gpu() {
  command -v nvidia-smi >/dev/null || { echo "no nvidia-smi: switch the notebook's Accelerator to GPU T4"; return 1; }
  nvidia-smi --query-gpu=name,driver_version,memory.total --format=csv,noheader | tee -a "$SUMMARY"
  "$PY" - <<'EOF' | tee -a "$SUMMARY"
import platform, sys
import torch
print(f"python {platform.python_version()}, torch {torch.__version__}, "
      f"cuda {torch.version.cuda}, gpu available: {torch.cuda.is_available()}")
sys.exit(0 if torch.cuda.is_available() else 1)
EOF
}

check_internet() {
  curl -fsS -o /dev/null --max-time 10 https://pypi.org/simple/ || {
    echo "no internet: turn Internet on in the notebook settings (needs a phone-verified account)"
    return 1
  }
}

check_secret() {
  [[ -n "${VG_ADMIN_PASSWORD:-}" ]] || { echo "VG_ADMIN_PASSWORD is empty: add it under Add-ons -> Secrets and attach it"; return 1; }
}

# The owner's files. Listed, never fetched: a missing one stops the run.
REQUIRED_MODELS=(
  "yolov8s.pt"                              # person: counting, intrusion, track
  "yolov8s-pose.pt"                         # falls: the pose stage
  "falling/checkpoints__temporal_model.pt"  # falls: the owner's LSTM
  "face_detection_yunet_2023mar.onnx"       # attendance: finding faces
  "face_recognition_sface_2021dec.onnx"     # attendance: SFace
)
REQUIRED_FOOTAGE=(
  "walk-through_cam-laptop_20260805-121705.mp4"
  "walk-through_cam-laptop_20260805-121705.json"
)

find_input() {  # find_input relative/path -> absolute path under the models dataset
  # The full relative path is preferred; the bare file name is accepted, so
  # an upload that flattened models/falling/ still counts.
  local name="$1" base all found
  base="$(basename "$name")"
  all="$(find "${VG_MODELS_DIR:-/kaggle/input}" -type f -name "$base" 2>/dev/null || true)"
  found="$(grep -F -- "$name" <<<"$all" | head -n1 || true)"
  [[ -z "$found" ]] && found="$(head -n1 <<<"$all")"
  [[ -n "$found" ]] && echo "$found"
}

link_inputs() {
  local missing=0 rel src
  for rel in "${REQUIRED_MODELS[@]}"; do
    if [[ -f "$REPO/models/$rel" && ! -L "$REPO/models/$rel" ]]; then
      echo "  model    $rel (in git, came with the code)"
    elif src="$(find_input "$rel")"; then
      mkdir -p "$REPO/models/$(dirname "$rel")"
      ln -sf "$src" "$REPO/models/$rel"
      echo "  model    $rel"
    else
      echo "  MISSING  model $rel - add it to your private models dataset"; missing=1
    fi
  done
  for rel in "${REQUIRED_FOOTAGE[@]}"; do
    if src="$(find_input "$rel")"; then
      mkdir -p "$REPO/engine/data/footage"
      ln -sf "$src" "$REPO/engine/data/footage/$rel"
      echo "  footage  $rel"
    else
      echo "  MISSING  footage $rel - add it to your private models dataset"; missing=1
    fi
  done
  [[ -f "$REPO/web/dist/index.html" ]] || { echo "  MISSING  web/dist - make the code dataset with tools/cloud/pack.ps1"; missing=1; }
  return $missing
}

# -------------------------------------------------------------------- install
install_python() {
  # Pin what Kaggle installed for the GPU, so nothing here replaces it.
  "$PY" -m pip freeze | grep -Ei '^(torch|torchvision|torchaudio)==' > "$TRIAL/keep-torch.txt" || true
  "$PY" -m pip install -q -c "$TRIAL/keep-torch.txt" -r "$REPO/engine/requirements.txt"
  # The appearance matcher tracking uses. Its source is in git, not on PyPI.
  "$PY" -m pip install -q --no-deps "$REPO/models/reid/loiterwatch"
  "$PY" - <<'EOF'
import cv2, pynvml, ultralytics
pynvml.nvmlInit()
print(f"  opencv {cv2.__version__}, ultralytics {ultralytics.__version__}, "
      f"nvml driver {pynvml.nvmlSystemGetDriverVersion()}")
EOF
}

ffmpeg_with_x264() {  # prints the first ffmpeg that can write H.264
  local exe
  for exe in $(which -a ffmpeg 2>/dev/null) /usr/bin/ffmpeg /usr/local/bin/ffmpeg; do
    [[ -x "$exe" ]] && "$exe" -hide_banner -encoders 2>/dev/null | grep -q ' libx264 ' \
      && { echo "$exe"; return 0; }
  done
  return 1
}

install_ffmpeg() {
  # The first ffmpeg on Kaggle's PATH has no libx264 and hides the system's
  # (first run, 31 Oct 2026), so every copy is asked, not just the first.
  local exe
  if ! exe="$(ffmpeg_with_x264)"; then
    echo "  no ffmpeg with libx264 yet; installing the system's"
    apt-get -qq update >/dev/null 2>&1 || true
    apt-get -qq install -y ffmpeg >/dev/null 2>&1 || echo "  apt-get install ffmpeg failed"
    exe="$(ffmpeg_with_x264)" || exe=""
  fi
  if [[ -n "$exe" ]]; then
    echo "$exe" > "$TRIAL/ffmpeg.txt"
    note "  ffmpeg with libx264: $exe - clips are browser-playable H.264"
  else
    # Not fatal: the trial is about speed. Clips still save (mp4v), and the
    # engine's log and System Health say they will not play in the browser.
    note "  **no ffmpeg with libx264 anywhere: clips save as mp4v and will NOT play in the browser**"
  fi
}

install_cloudflared() {
  command -v cloudflared >/dev/null && { cloudflared --version; return 0; }
  # Cloudflare's own signed package repository, so apt checks the signature.
  mkdir -p --mode=0755 /usr/share/keyrings
  curl -fsSL https://pkg.cloudflare.com/cloudflare-main.gpg -o /usr/share/keyrings/cloudflare-main.gpg
  echo 'deb [signed-by=/usr/share/keyrings/cloudflare-main.gpg] https://pkg.cloudflare.com/cloudflared any main' \
    > /etc/apt/sources.list.d/cloudflared.list
  apt-get -qq update && apt-get -qq install -y cloudflared >/dev/null
  cloudflared --version
}

build_tensorrt() {
  if [[ "${VG_SKIP_TENSORRT:-}" == "1" ]]; then
    note "  TensorRT skipped (VG_SKIP_TENSORRT=1): every model runs from its .pt"
    return 0
  fi
  # The cu12 line: build_engines.py records that cu13 segfaults at Builder().
  "$PY" -m pip install -q -c "$TRIAL/keep-torch.txt" tensorrt-cu12 \
    || { note "  TensorRT would not install: every model runs from its .pt"; return 0; }
  # Never fatal. A model whose engine does not build runs from its .pt, and
  # the summary and System Health both say which.
  (cd "$REPO" && timeout 1800 "$PY" engine/tools/build_engines.py --only person pose) \
    2>&1 | tee "$TRIAL/tensorrt.log" | grep -Ei 'built|failed|skipp|engine' | tee -a "$SUMMARY" || true
  ls -1 "$REPO"/models/*.engine 2>/dev/null | sed 's/^/  engine   /' | tee -a "$SUMMARY" || true
}

benchmark() {
  # Server-side numbers, before the engine takes the GPU. Never fatal.
  (cd "$REPO" && timeout 900 "$PY" engine/tools/benchmark.py --model person) \
    > "$TRIAL/evidence/benchmark-person.txt" 2>&1 || true
  (cd "$REPO" && timeout 900 "$PY" engine/tools/benchmark.py --site 16) \
    > "$TRIAL/evidence/benchmark-site16.txt" 2>&1 || true
  tail -n 12 "$TRIAL/evidence/benchmark-person.txt" || true
}

create_admin() {
  (cd "$REPO" && "$PY" engine/tools/create_user.py --email admin@trial.local \
     --name "Trial admin" --role admin --password-env VG_ADMIN_PASSWORD)
}

# ------------------------------------------------------------------- running
open_tunnel() {
  nohup cloudflared tunnel --no-autoupdate --url http://127.0.0.1:8000 \
    > "$TRIAL/cloudflared.log" 2>&1 &
  echo $! > "$TRIAL/cloudflared.pid"
  local i url=""
  for i in $(seq 1 60); do
    url="$(grep -Eo 'https://[a-z0-9-]+\.trycloudflare\.com' "$TRIAL/cloudflared.log" | head -n1 || true)"
    [[ -n "$url" ]] && break
    sleep 1
  done
  [[ -n "$url" ]] || { tail -n 20 "$TRIAL/cloudflared.log"; return 1; }
  echo "$url" > "$TRIAL/url.txt"
}

start_engine() {
  local hours="${VG_TRIAL_HOURS:-11.5}" ends
  ends="$(date -u -d "+$("$PY" -c "print(int(float('$hours') * 3600))") seconds" +%Y-%m-%dT%H:%M:%S+00:00)"
  echo "$ends" > "$TRIAL/ends-at.txt"
  (
    cd "$REPO"
    export VG_CONFIG_OVERLAY=engine/profiles/cloud.yaml VG_CAMERAS=cam-clip \
           VG_TRIAL_DIR="$TRIAL" VG_PUBLIC_URL="$(cat "$TRIAL/url.txt")" \
           VG_SESSION_ENDS_AT="$ends"
    [[ -s "$TRIAL/ffmpeg.txt" ]] && export VG_FFMPEG="$(cat "$TRIAL/ffmpeg.txt")"
    nohup "$PY" engine/tools/serve.py > "$TRIAL/engine.log" 2>&1 &
    echo $! > "$TRIAL/engine.pid"
  )
  local i
  for i in $(seq 1 300); do
    curl -fsS -o /dev/null http://127.0.0.1:8000/healthz && return 0
    kill -0 "$(cat "$TRIAL/engine.pid")" 2>/dev/null || { tail -n 40 "$TRIAL/engine.log"; return 1; }
    sleep 1
  done
  tail -n 40 "$TRIAL/engine.log"; return 1
}

restrict_clip() {
  # Restricted areas are whole cameras switched on in the console. Do what
  # the console's toggle does, as the trial admin, so the clip raises
  # breaches to time. Audited like any other admin action.
  "$PY" - <<'EOF'
import json, os, urllib.request
base = "http://127.0.0.1:8000"
def call(method, path, body, token=None):
    req = urllib.request.Request(base + path, method=method, data=json.dumps(body).encode())
    req.add_header("Content-Type", "application/json")
    if token:
        req.add_header("Authorization", f"Bearer {token}")
    with urllib.request.urlopen(req, timeout=30) as r:
        return json.load(r)
token = call("POST", "/auth/login", {"email": "admin@trial.local",
                                     "password": os.environ["VG_ADMIN_PASSWORD"]})["token"]
zone = call("PATCH", "/zones/cam-clip", {"enabled": True}, token)
print("  cam-clip restricted:", zone.get("enabled"))
EOF
}

start_watchdog() {
  local ends now
  ends="$(date -u -d "$(cat "$TRIAL/ends-at.txt")" +%s)"; now="$(date -u +%s)"
  nohup bash -c "sleep $((ends - now)); bash '$REPO/tools/cloud/stop.sh'" \
    > "$TRIAL/watchdog.log" 2>&1 &
  echo $! > "$TRIAL/watchdog.pid"
}

step "GPU and Python"        check_gpu
step "Internet"              check_internet
step "Admin password secret" check_secret
step "Models, clip, console" link_inputs
step "Python packages"       install_python
step "ffmpeg (H.264 clips)"  install_ffmpeg
step "cloudflared"           install_cloudflared
step "TensorRT engines"      build_tensorrt
step "Server benchmark"      benchmark
step "Administrator account" create_admin
step "Tunnel"                open_tunnel
step "Engine"                start_engine
step "Clip camera restricted" restrict_clip
step "Stop timer"            start_watchdog

note ""
note "- total: $((SECONDS - started_all)) s"
note "- engine stops itself at $(cat "$TRIAL/ends-at.txt") (UTC); output goes to $OUT"
grep -Ei 'tensorrt inference|loading .*\.pt|encoding video' "$TRIAL/engine.log" | tee -a "$SUMMARY" || true
echo
echo "Console: $(cat "$TRIAL/url.txt")"
echo "Sign in as admin@trial.local with your VG_ADMIN_PASSWORD secret."
