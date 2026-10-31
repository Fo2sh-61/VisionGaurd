# Quickstart: Cloud trial

What Mohamed does, start to finish. **(PC)** runs on the laptop, **(Kaggle)** in the
browser. Google Colab is not supported: its free tier forbids a web UI reached
through a tunnel.

## Once

1. **(Kaggle)** Settings → verify your phone number. Notebooks only get internet
   after that.
2. **(Kaggle)** Datasets → New dataset → **Private**, named `visionguard-models`.
   Upload these files (the notebook checks for each and stops naming any that is
   missing; it never downloads one):

   | From | File |
   |---|---|
   | `models/` | `yolov8s.pt` |
   | `models/` | `yolov8s-pose.pt` |
   | `models/` | `face_detection_yunet_2023mar.onnx` |
   | `models/` | `face_recognition_sface_2021dec.onnx` |
   | `engine/data/footage/` | `walk-through_cam-laptop_20260805-121705.mp4` |
   | `engine/data/footage/` | `walk-through_cam-laptop_20260805-121705.json` |

   The falls model (`models/falling/checkpoints__temporal_model.pt`) is in git, so it
   comes with the code.
3. **(Kaggle)** Create a notebook: File → Import notebook →
   `cloud/visionguard_trial.ipynb` from this repository. Then Add-ons → Secrets → add
   `VG_ADMIN_PASSWORD` (a password you use nowhere else) and attach it.

## Each new code version

4. **(PC)** With everything committed:

   ```powershell
   .\tools\cloud\pack.ps1
   ```

   It builds the console and writes `visionguard-trial.zip` from the current commit.
   Upload it as a new version of a **private** dataset `visionguard-code`.

## Each work day (one click)

Up to six days a week (Saturday to Thursday), 4.5 hours a day: 27 of Kaggle's ~30
weekly GPU hours, with room for setup.

5. **(Kaggle)** Open the notebook. Top right: **Save Version** → **Save & Run All
   (Commit)** → **Save**. That's the click. It runs in the background, even with the
   tab closed: setup (~6 min), then 4.5 h of engine, then it stops, saves, and gives
   the GPU back.
6. **Today's address**: bottom left, **View Active Events** → the running version →
   its log. Look for `Console: https://<random>.trycloudflare.com` (it is repeated
   every 5 minutes). If a step says **FAILED**, paste the log to Claude.
7. **(PC)** Open the address. Sign in as `admin@trial.local` with your secret's
   password.
8. **(PC)** To measure the cloud (6 minutes):

   ```powershell
   python engine/tools/measure_remote.py --url https://<random>.trycloudflare.com --label cloud --email admin@trial.local
   ```

   The table is `specs/021-cloud-trial/evidence/comparison.md`. Its **local** column
   was measured on 31 Oct 2026 on this laptop with the same profile (see "Local
   column" below to measure it again).
9. **Afterwards**: the finished version's **Output** holds `trial-<date>/` (database,
   logs, benchmark, summary).

**Stopping early**: open the running version and cancel it; the engine's database
is then not saved. In an interactive session instead (Run All in the editor), cell 4
saves by itself at the end, and you press the power button so the GPU clock stops.

Not yet confirmed on Kaggle: that a background (Commit) run gets the GPU, internet
and the secret, and shows its log while it runs. The first one-click run is that
test.

## What you should see

- A banner on every page: when the engine stops, in your own time. Amber in the last
  15 minutes, then "stopping now", then "stopped".
- System Health: the T4, its memory, and which models loaded as TensorRT (`.engine`)
  and which from `.pt`.
- Ask and email: "not configured".
- The clip camera is a restricted area (the notebook switches it on), so breaches
  appear and their clips play in the browser.
- Known, by design: a clip address opened in a **new tab** shows the console, not the
  video. Play clips inside the page.

## Local column

The same profile on this laptop, with a throwaway database and a throwaway admin, so
the two columns differ only in where the engine runs:

```powershell
$env:VG_TRIAL_DIR = "$env:TEMP\vg-trial"; Remove-Item $env:VG_TRIAL_DIR -Recurse -ErrorAction SilentlyContinue
$env:VG_CONFIG_OVERLAY = 'engine/profiles/cloud.yaml'; $env:VG_CAMERAS = 'cam-clip'; $env:VG_PUBLIC_URL = 'http://127.0.0.1:8000'
$env:VG_ADMIN_PASSWORD = Read-Host 'trial password' ; Remove-Item Env:VG_DEV_SIGNIN -ErrorAction SilentlyContinue
cd web; npm.cmd run build; cd ..
python engine/tools/create_user.py --email admin@trial.local --name 'Trial admin' --role admin --password-env VG_ADMIN_PASSWORD
python engine/tools/serve.py
```

Then sign in at `http://127.0.0.1:8000`, switch `cam-clip` on in the Restricted
zones page, and run `measure_remote.py` with `--url http://127.0.0.1:8000 --label local`.
