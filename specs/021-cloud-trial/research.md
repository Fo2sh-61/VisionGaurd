# Research: Cloud trial

Checked 31 Oct 2026. "Verified" means read in this repository or run on this laptop;
"unverified" means a public source, to be confirmed by the first Kaggle run.

## R1. Which free platform

- **Decision**: Kaggle only.
- **Rationale**: Colab's FAQ lists, for free managed runtimes, "bypassing the notebook UI
  to interact primarily via a web UI" and "connecting to remote proxies" as disallowed and
  liable to termination without warning. That is exactly this trial. Kaggle has no such
  written rule found; tunnels from Kaggle notebooks are common practice (unverified as
  policy).
- **Alternatives**: Colab free (rejected above); Colab paid lifts the limits — later phase.

## R2. Kaggle limits

- **Decision**: design for a 12 h session, ~30 GPU h/week, disk wiped at the end, no
  inbound port; stop at 11 h 30 m by default.
- **Rationale**: Kaggle's docs (as reported Sep 2026) say 12 h for GPU sessions; older blogs
  say 9 h. The notebook prints its own start time and deadline and the watchdog uses them.
  Internet in a notebook needs a phone-verified account (unverified — first run).
- **Open**: whether files in `/kaggle/working` survive the end of an *interactive* session
  (they do for "Save & Run All" versions). Quickstart tells Mohamed to download the output
  folder before stopping until this is confirmed.

## R3. H.264 on Linux

- **Decision**: add a pipe-to-`ffmpeg` (`libx264`) encoder after OpenCV's own avc1 on Linux.
- **Rationale**: verified in `ingest/encoder.py` that OpenCV's pip build ships no H.264
  encoder (the reason Windows names Media Foundation). On Linux there is no Media
  Foundation. `ffmpeg` with `libx264` is a standard package and usually present on Kaggle
  (unverified); bootstrap installs it with `apt-get` if missing and says so.
- **Alternatives**: mp4v (does not play in the console); re-encode after saving (clip
  unplayable until a second job runs, two code paths).

## R4. Python 3.11 / 3.12

- **Decision**: no source change expected; prove it by running the suite on Python 3.11.
- **Rationale**: verified: every engine file parses with `ast` at `feature_version` 3.11;
  every module that defines annotations has `from __future__ import annotations` (the ten
  without it are `__init__` files); no `itertools.batched`, `typing.override` or other 3.12+
  call found. Library behaviour can still differ, so the suite is the proof. This laptop has
  Python 3.11 and 3.12 installed (`py -0`).

## R5. Config overlay

- **Decision**: `VG_CONFIG_OVERLAY` env var naming a YAML file, deep-merged into the raw
  `engine.yaml` dict before validation.
- **Rationale**: matches `VG_CAMERAS` (verified: `config.py` `_apply_camera_override`, chosen
  so the main file is never rewritten). Env expansion `${VAR}` already exists in `_expand`,
  so the overlay can name the trial folder and public address without a new mechanism.
- **Alternatives**: a whole second `engine.yaml` (600 lines copied, drifts); CLI flags on
  `serve.py` (does not reach `get_config()` used elsewhere).

## R6. Serving the console

- **Decision**: the engine serves `web/dist` itself, only when `api.console_dir` is set.
- **Rationale**: verified spec 016 has not built this (its plan is still the template) and
  spec 020 plans a separate HTTPS front on Windows. Neither exists to reuse. One folder
  mount in the engine is the smallest step and leaves 016's front free to replace it.

## R7. Dev sign-in in the cloud

- **Decision**: `dev_signin.role_from_env` refuses when the config's `profile` is `cloud`;
  bootstrap also unsets `VG_DEV_SIGNIN`.
- **Rationale**: verified the existing fences: loopback connection **and** loopback host.
  `cloudflared` connects from loopback but forwards the public host name, so the second
  fence would already refuse it — but "probably refused by a header check" is not good
  enough on a public address. `VG_STRICT=1` would also refuse it, but makes every subsystem
  failure fatal, which a trial does not want.

## R8. Event timing without a shared clock

- **Decision**: estimate the server-minus-PC clock offset from `/healthz` `now` using the
  shortest round trip; report every age with ± half that round trip.
- **Rationale**: Kaggle's clock and the laptop's are not synchronised to milliseconds; the
  MJPEG frame carries no capture time. The breach and detection payloads already carry
  `at`. Adding `now` to `/healthz` is the only API addition this needs.

## R9. Getting the code onto Kaggle

- **Decision**: `pack.ps1` builds `web/dist`, then `git archive HEAD` + `web/dist` into one
  zip uploaded as a private dataset. Models and the clip are a second private dataset that
  rarely changes.
- **Rationale**: the GitHub repo would need a token in the notebook; Kaggle images may lack
  Node. A commit-based archive matches how the website is already published.

## R10. TensorRT on a T4

- **Decision**: build at the start of every session (owner's choice), for the models
  `cam-clip` uses, with `build_engines.py --only …`; time each; on failure run the `.pt` and
  list it.
- **Rationale**: verified `build_engines.py` confirms each build by looking for the file and
  `infer/shared.py` picks `<stem>-<imgsz>.engine` next to the weights. Build time on a T4 is
  unknown (unverified); the notebook prints it.
