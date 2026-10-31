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
   Upload it as a new version of a **private** dataset `visionguard-code`. Then in the
   notebook's Input panel: `visionguard-code` → ⋮ → **Check for updates** → **Update**.
   Kaggle does not switch a notebook to a new dataset version by itself (31 Oct 2026:
   it was still reading version 2 after version 3 was uploaded).

## Each time you want it

Two buttons. Kaggle counts GPU time from the first to the second, nothing else.

- **START**: open the notebook on Kaggle, click **Run All** (▶▶ at the top). After
  about 6 minutes the bottom of the output shows
  `Console: https://<random>.trycloudflare.com`. Open it on your PC and sign in as
  `admin@trial.local` with your secret's password.
- **STOP**: click the **power button ⏻** at the top of the notebook. Counting stops
  at that moment.

The address is new every START. If you forget STOP, the engine stops itself after
4.5 hours, but Kaggle keeps counting until ⏻ is pressed.

To measure the cloud (6 minutes, while it runs):

```powershell
python engine/tools/measure_remote.py --url https://<random>.trycloudflare.com --label cloud --email admin@trial.local
```

The table is `specs/021-cloud-trial/evidence/comparison.md`; its **local** column was
measured on 31 Oct 2026 on this laptop with the same profile.

Optional, for a background run (Save Version → Save & Run All): set `VG_IDLE_MINUTES`
and the trial stops itself that many minutes after the last use, and the run's end
stops the clock. Off by default.

## Your laptop webcam in the cloud

Once, on the laptop: `.\tools\cloud\install-camera-shortcut.ps1` puts
**VisionGuard Cloud Camera** on the desktop (already done on 31 Oct 2026).

Each time, after START has printed the address:

1. Double-click **VisionGuard Cloud Camera**. Paste the address, check the email
   (`admin@trial.local`), type the password, press **Start**. The window shows how many
   pictures a second it sends (about 10).
2. In the cloud console, **Laptop webcam (sent to the cloud)** is live, with the same
   features as your desktop's laptop camera. Enrol yourself there to be named.
3. **Stop** (or close the window) and the camera reads NO SIGNAL within seconds.

The webcam cannot be used by the desktop engine and the sender at the same time: stop
`dev.ps1` first. Upload needed: about 2-3 Mbps while sending.

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
