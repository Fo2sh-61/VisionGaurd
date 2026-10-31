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

## Each work day

5. **(Kaggle)** Open the notebook. Settings: Accelerator **GPU T4**, Internet **on**.
   Inputs: `visionguard-code` and `visionguard-models`. Run cells 1, 2 and 3.
6. Cell 3 prints each step with its time, and ends with
   `Console: https://<random>.trycloudflare.com`. If a step fails it says which and
   stops: paste the whole output to Claude.
7. Run cell 4 and leave it running (it keeps the session busy and prints the
   engine's state every 5 minutes).
8. **(PC)** Open the address. Sign in as `admin@trial.local` with your secret's
   password.
9. **(PC)** Measure the cloud (6 minutes):

   ```powershell
   python engine/tools/measure_remote.py --url https://<random>.trycloudflare.com --label cloud --email admin@trial.local
   ```

   The table is `specs/021-cloud-trial/evidence/comparison.md`. Its **local** column
   was measured on 31 Oct 2026 on this laptop with the same profile (see "Local
   column" below to measure it again).
10. **(Kaggle)** Before closing: interrupt cell 4, run cell 5 **Stop and save**, then
    download the `trial-<date>` folder from the Output panel. Until we confirm that
    Kaggle keeps `/kaggle/working` after an interactive session, assume it does not.

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
