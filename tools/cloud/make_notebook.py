"""Write cloud/visionguard_trial.ipynb from the cells below.

    python tools/cloud/make_notebook.py

The notebook is generated rather than hand-edited JSON, so a change to it is a
readable diff here. specs/021-cloud-trial.
"""

from __future__ import annotations

import json
from pathlib import Path

REPO = Path(__file__).resolve().parents[2]
TARGET = REPO / "cloud" / "visionguard_trial.ipynb"

INTRO = """\
# VisionGuard cloud trial (Kaggle)

The recorded clip, an empty database, one administrator, a public https address.

**START**: click **Run All** (▶▶ at the top). After about 6 minutes the address
appears at the bottom: `Console: https://....trycloudflare.com`.

**STOP**: click the **power button ⏻** at the top. Kaggle's GPU clock stops then,
and only then. (If you forget, the engine stops itself after 4.5 hours, but the
clock keeps counting until you press ⏻.)

**Settings once**: Accelerator **GPU T4**, Internet **on**. Inputs: your private
`visionguard-code` and `visionguard-models` datasets. Add-ons → Secrets:
`VG_ADMIN_PASSWORD`, attached to this notebook.

Nothing here contains a key. Ask and email report "not configured" in the trial."""

FIND_CODE = """\
# 1. Copy the code from the code dataset to /tmp/vg (inputs are read-only).
import glob, os, shutil, subprocess, zipfile

# Always a fresh copy, so a new version of the dataset is what runs.
VG = "/tmp/vg"
shutil.rmtree(VG, ignore_errors=True)
scripts = glob.glob("/kaggle/input/**/tools/cloud/bootstrap.sh", recursive=True)
zips = glob.glob("/kaggle/input/**/visionguard-trial.zip", recursive=True)
if len(scripts) > 1:
    raise SystemExit(f"More than one copy of the code is attached: {scripts}. Remove the old one.")
if scripts:
    shutil.copytree(os.path.dirname(os.path.dirname(os.path.dirname(scripts[0]))), VG)
elif zips:
    with zipfile.ZipFile(zips[0]) as z:
        z.extractall("/tmp")
    os.rename("/tmp/visionguard", VG)
else:
    raise SystemExit("No code found: add your visionguard-code dataset as an input.")
print("code in", VG, "-", len(os.listdir(VG)), "entries")"""

SECRET = """\
# 2. The admin password, from the Kaggle secret. Never printed.
from kaggle_secrets import UserSecretsClient

env = dict(os.environ)
env["VG_ADMIN_PASSWORD"] = UserSecretsClient().get_secret("VG_ADMIN_PASSWORD")
env.pop("VG_DEV_SIGNIN", None)
print("secret read:", bool(env["VG_ADMIN_PASSWORD"]))"""

START = """\
# 3. Start: checks, installs, TensorRT, admin, tunnel, engine. Each step prints its time.
import time

log_path = "/tmp/vg-bootstrap.log"
log = open(log_path, "w")
boot = subprocess.Popen(["bash", f"{VG}/tools/cloud/bootstrap.sh"], cwd=VG, env=env,
                        stdout=log, stderr=subprocess.STDOUT)
shown = 0
while True:
    with open(log_path) as f:
        text = f.read()
    print(text[shown:], end="")
    shown = len(text)
    if boot.poll() is not None:
        break
    time.sleep(3)
print("\\nbootstrap exit code:", boot.returncode)
if boot.returncode != 0:
    # Keep what there is (the summary names the failed step), then end the run
    # here, so a failed start does not sit on the GPU.
    subprocess.run(["bash", f"{VG}/tools/cloud/stop.sh"])
    raise SystemExit("The start failed: see the step marked FAILED above.")"""

KEEP_ALIVE = """\
# 4. Prints the address every 5 minutes while the engine runs. To stop, press the
#    power button at the top: that is what stops Kaggle's GPU clock.
import json, urllib.request

url = open("/tmp/vg-trial/url.txt").read().strip()
while True:
    try:
        with urllib.request.urlopen("http://127.0.0.1:8000/healthz", timeout=10) as r:
            h = json.load(r)
        print(time.strftime("%H:%M:%S"), "engine up at", url, "- stops at", h.get("endsAt"), flush=True)
    except Exception as exc:
        print(time.strftime("%H:%M:%S"), "engine stopped:", exc, flush=True)
        break
    time.sleep(300)
print(subprocess.run(["bash", f"{VG}/tools/cloud/stop.sh"], capture_output=True, text=True).stdout)
print("The engine has stopped and saved. NOW PRESS THE POWER BUTTON AT THE TOP: Kaggle is still counting.")"""

STOP = """\
# 5. Only to stop EARLY, by hand: stop and save now. A normal run never needs it
#    (cell 4 already saved); running it again is harmless.
print(subprocess.run(["bash", f"{VG}/tools/cloud/stop.sh"], capture_output=True, text=True).stdout)"""


def _cell(kind: str, text: str) -> dict:
    cell = {"cell_type": kind, "metadata": {}, "source": text.splitlines(keepends=True)}
    if kind == "code":
        cell.update({"execution_count": None, "outputs": []})
    return cell


def notebook() -> dict:
    return {
        "cells": [
            _cell("markdown", INTRO),
            _cell("code", FIND_CODE),
            _cell("code", SECRET),
            _cell("code", START),
            _cell("code", KEEP_ALIVE),
            _cell("code", STOP),
        ],
        "metadata": {
            "kernelspec": {"display_name": "Python 3", "language": "python", "name": "python3"},
            "language_info": {"name": "python"},
        },
        "nbformat": 4,
        "nbformat_minor": 5,
    }


def main() -> int:
    TARGET.parent.mkdir(parents=True, exist_ok=True)
    TARGET.write_text(json.dumps(notebook(), indent=1) + "\n", encoding="utf-8", newline="\n")
    print(f"  wrote {TARGET}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
