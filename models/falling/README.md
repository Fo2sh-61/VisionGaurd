# Fall detection: rule-based + learned temporal classifier

Two interchangeable detectors behind one `FallDetector` interface:

| name | how it decides |
|---|---|
| `rule_based` | spine angle from vertical per frame (ported from `britishnew/dual_camera_fight_detector.py`) |
| `temporal_model` | 1D-CNN or LSTM over the last 30 normalized poses of each track |

Both feed per-track states (normal / falling / fallen) into the **same** `EventEmitter`
(`detectors/events.py`), so alerts are raised by identical logic:

- the track has been FALLEN for `confirm_s`;
- it was upright at most `transition_s` before it first became FALLEN. "Upright" means
  at least `upright_s` of uninterrupted NORMAL frames, so one glitchy frame doesn't
  count, and someone who was already lying down never fires;
- an alerted track can't alert again until it has been upright for `rearm_s`, and never
  twice within `cooldown_s`.

Before either detector sees a frame, the shared `FallDetector.update` maps tracker ids to
stable identities with `TrackLinker`. ByteTrack often gives a person a new id in the
middle of a fall, so a new id is linked to an identity that disappeared within `link_s`
(default 1 s) if their boxes overlap or are close. Training labels follow the person the
same way (`stitch_subject`). Use `detector.status_for(tracker_id)` to look up a person's
state.

Pose comes from YOLOv8s-pose + ByteTrack (`core/pose.py`), configured the same way as in
britishnew. The weights are looked up in this order: `$FALLDET_POSE_WEIGHTS`, then
`models/yolov8s-pose.pt`, then `E:/britishnew/models/yolov8s-pose.pt`. If none of those
exist, ultralytics downloads them.

## Layout

```
core/        keypoints, pose estimator, frame sources, features.py (windows + normalization)
detectors/   base.py (FallDetector), events.py (shared emitter), registry.py,
             rule_based.py, temporal_model.py
train/       datasets.py (loaders), prepare_data.py, splits.py, model.py, train.py
configs/     cnn.yaml, lstm.yaml
eval.py      side-by-side comparison
gui.py       viewer with the detector dropdown
tests/       synthetic skeletons; no weights or datasets needed
```

## Workflow

```bash
pip install -r requirements.txt

# 1. Run pose once per video and cache it (one .npz per video + index.json)
python -m train.prepare_data --dataset le2i --root D:/data/le2i --out data/cache/le2i
python -m train.prepare_data --dataset urfd --root D:/data/urfd --out data/cache/urfd

# 2. Train (split by video/group into runs/split.json, shared by every config)
python -m train.train --config configs/cnn.yaml
python -m train.train --config configs/lstm.yaml
python -m train.train --config configs/cnn_cctv.yaml      # + CCTV viewpoint augmentation
python -m train.train --config configs/lstm_cctv.yaml

# 3. Pick the model to deploy and install it as checkpoints/temporal_model.pt
python -m train.compare --runs runs/cnn runs/lstm runs/cnn_cctv runs/lstm_cctv \
    --cache data/cache/le2i data/cache/urfd --split-file runs/split.json --negatives data/cache/cctv --install

# 4. Compare both detectors on the held-out test videos
python eval.py --cache data/cache/le2i data/cache/urfd --split-file runs/split.json

# 5. Live / video viewer
python gui.py
```

The GUI and eval use `checkpoints/temporal_model.pt` (or `$FALLDET_CHECKPOINT`), falling
back to the newest `runs/*/best.pt`.

## Datasets

All loaders produce 0-based per-frame labels `normal / falling / fallen` plus a
**group id**. Groups, never frames or windows, are what get split.

- **Le2i** (`--dataset le2i`)
  - Layout: `<scene>/Videos/*.avi` and `<scene>/Annotation_files/*.txt`. The
    `Annotations_files` spelling and the doubly nested `Coffee_room_01/Coffee_room_01/` layout
    are also accepted.
  - The first two lines of each annotation give the fall's start and end frames (1-based).
    Frames before the start are normal, frames from start to end are falling, and frames
    after the end are fallen. `0 0` means the video has no fall.
  - Videos without that header are skipped.
  - Le2i has no subject ids, so the group is the video. `--opt group_by=scene` keeps whole
    rooms together for a stricter split.
- **UR Fall** (`--dataset urfd`)
  - Layout: `fall-NN-cam0-rgb/` PNG folders (preferred) or `fall-NN-cam0.mp4`, plus
    `urfall-cam0-falls.csv`.
  - CSV labels map as: -1 → normal, 0 → falling, 1 → fallen.
  - ADL sequences are labelled normal throughout, because lying on a bed isn't a fall.
  - The `.mp4` files show depth (left) and RGB (right) side by side. The loader keeps only
    the RGB half (`video_crop="right_half"`).
  - cam0 and cam1 of one fall share the group `urfd/fall-NN`. cam1 is opt-in with
    `--opt cams=[0,1]` and reuses the cam0 labels, which assumes the two cameras are
    frame-synchronized.
- **Anything else**: write a `manifest.csv` (`video,group,fall_start,fall_end[,fps]`) and use
  `--dataset manifest`. Or register your own loader:

  ```python
  from train.datasets import register_loader, VideoRecord, fall_segments

  @register_loader("mydata")
  def load_mydata(root, **opts):
      return [VideoRecord("mydata", vid_id, subject_id, path, fall_segments(start, end))]
  ```

Dataset labels describe one person, but ByteTrack often switches ids right as someone falls.
So the labelled **subject** is followed by box overlap across id switches (`stitch_subject`),
not by tracker id. All detections stay in the cache so eval can replay the full scene.

Re-running `prepare_data`:
- reuses an existing cache only if it was made with the same pose settings (weights,
  confidence, image size, `--max-frames`). Otherwise the video is extracted again.
- always takes labels and groups from the current loader, so `--opt group_by=scene` or a
  different `frame_offset` applies without re-running pose.
- writes caches atomically, and re-extracts an unreadable cache instead of skipping it.

## Windows and normalization (`core/features.py`)

- **Window**: 30 consecutive frames, labelled by the **last** frame. That's what the online
  detector predicts: the current state given the past 30 frames.
- **Gaps**: up to 5 missing frames are filled by holding the last pose; a longer gap starts
  a new segment. The online `TrackBuffer` does exactly the same, and a test checks that
  training and live windows are identical.
- **Normalization**: each window is centered on **one** point, the mean hip center over the
  window, and divided by **one** scale, the median torso length. Centering each frame on its
  own hips would erase the downward motion that signals a fall.
- **Scale guard**: the scale can't drop below a quarter of the body's keypoint extent, so a
  torso foreshortened by falling toward the camera doesn't blow up the coordinates.
- **Missing keypoints**: keypoints below 0.30 confidence become `(0, 0, 0)`.
- **Warm-up** (`data.min_frames`, default 10): the model predicts once 10 poses are
  buffered, padding the start of the window by repeating the first pose. Training pads
  the same way. Without this, a track gets no prediction for its first second, and falls
  near the start of a clip are missed.

## Training (`train/train.py`, any config key can be overridden)

- `model.arch: cnn | lstm`.
  - CNN: 3 dilated residual Conv1d blocks, then mean pooling plus the last time step.
  - LSTM: 2 layers, classifies from the last hidden state.
  - Both are about 12–60k parameters.
- Cross-entropy weighted by inverse class frequency (`train.class_weighting`).
- Augmentation: left/right mirror, scale, jitter and keypoint dropout. The `*_cctv` configs
  add **viewpoint augmentation** for CCTV-style cameras that are mounted high, look down
  through wide-angle lenses, and often see people behind counters:
  - `rotate_deg`: random tilt;
  - `squash`: vertical compression from a downward view;
  - `shear`;
  - `occlude_lower_p`: hides the knees and ankles.

  Each augmented window is normalized again, exactly as the detector would normalize such
  a view.
- Early stopping on validation **macro-F1**. `best.pt` stores the weights plus everything
  needed to prepare input (window, max gap, confidence threshold, feature version), and it
  loads with `torch.load(weights_only=True)`.
- Prints the validation (and test) confusion matrix with per-class precision, recall and F1.
- **Alert calibration** (`train/calibrate.py`, runs automatically): replays the validation
  videos through the real detector and picks two settings.
  - `fallen_threshold`: how confident the model must be before a person counts as fallen.
  - `min_visible_kps`: frames showing fewer keypoints than this keep the previous
    prediction instead of being judged.

  The best event-level F1 wins, and the result is stored in `best.pt`. Nothing is written
  if the validation videos contain no detectable falls.
- `train/compare.py` ranks finished runs:
  - by validation event-F1, then by fewest false alarms on fall-free target footage
    (`--negatives`);
  - test-split results are shown for every run but never used to choose;
  - `--install` copies the winner to `checkpoints/temporal_model.pt`.
- `--arch lstm` without `--out` writes to `runs/lstm`, not the config's `runs/cnn`. Numeric
  config values are cast to the right type, so `lr: 1e-3` works even though YAML reads it
  as a string.

## Demo videos (`demo.py`)

```bash
python demo.py my_clip.mp4 --out demo.mp4 --title "Fall: person trips in a corridor"
```

Runs the installed model over a video and saves an annotated copy at 720p or more. Skeleton
and box colors follow each person's predicted state, and the red FALL DETECTED banner appears
only when the detector really raises an alert. Use `--detector rule_based` for the baseline,
and `--crop right_half` for UR Fall `.mp4` files (depth | RGB side by side).
The output is MPEG-4 (no H.264 encoder on this machine); it imports into Premiere/DaVinci.

## Attendance demo videos (`demo_attendance.py`)

```bash
python demo_attendance.py clip.mp4 --people people/ --out demo.mp4 --title "Arrives on time" --clock 07:52:00 --blur-unknown --expect "Layla Ahmed"
```

Real recognition with VisionGuard's own face models, drawn with a register panel (present / on time / late). A name appears only when the engine recognised the face; `--blur-unknown` blurs everyone else; `--expect` fails the run if someone was missed or wrongly named. See `data/attendance_DRAFT/README.txt`.

## Evaluation (`eval.py`)

Pose runs once per video, and the identical detections are replayed into every detector.
Pass `--split-file runs/<arch>/split.json`, which defaults to the `test` split.
Without it, eval scores every cached video, including training videos, and the output
says so.

- **Event level**: the first alert in `[fall start − 1 s, impact + 3 s]` counts as a true
  positive. Alerts outside that window are false alarms, and a fall with no alert in it is
  a miss. "Impact" is the first fallen frame.
- **Reported metrics**: precision, recall, F1, false alarms per minute, mean latency after
  impact, and detector-only ms per frame.
- **Frame level**: the subject's per-frame state is compared with the labels.

## Notes and limitations

- The temporal model learns dynamics at the training videos' frame rate (25–30 fps). Feeding
  it a much slower camera changes what 30 frames means.
- A person lying still for more than a window after a fall looks the same as someone lying
  on a sofa. The model can't separate them from 30 frames, which is why alerts require the
  normal → fallen transition.
- The Le2i and UR Fall loaders were written against the published layouts and checked with
  fixture files only; neither dataset was available locally.

## Tests

```bash
python -m pytest
```
