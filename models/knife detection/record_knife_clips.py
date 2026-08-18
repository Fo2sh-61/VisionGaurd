"""
Record training clips from your webcam for the custom knife dataset.

Records at the camera's max resolution into knife_clips/clip_XX.mp4.
Controls:
    r = start/stop recording a clip
    q = quit

WHAT TO RECORD (~10-15 min total):
  1. Knife at 2-6 meters (the weak zone): walk around, stand, turn,
     knife at your side / raised / pointing different directions.
  2. Different lighting: lights on, lights off, near a window.
  3. Different backgrounds if possible.
  4. A few close-range passes too (0.5-2m).
  5. IMPORTANT: 2-3 minutes with NO knife - hold a phone, pen, spoon,
     spatula instead. These teach the model what NOT to flag.

Then run train_knife_model_v3_custom.py in Colab (it will ask you to
upload the clips folder as a zip).
"""

import os
import time

import cv2

CAMERA_INDEX = 0
OUT_DIR = "knife_clips"

os.makedirs(OUT_DIR, exist_ok=True)

cap = cv2.VideoCapture(CAMERA_INDEX)
cap.set(cv2.CAP_PROP_FRAME_WIDTH, 1920)
cap.set(cv2.CAP_PROP_FRAME_HEIGHT, 1080)
w = int(cap.get(cv2.CAP_PROP_FRAME_WIDTH))
h = int(cap.get(cv2.CAP_PROP_FRAME_HEIGHT))
fps = cap.get(cv2.CAP_PROP_FPS) or 30
print(f"Camera: {w}x{h} @ {fps:.0f}fps")

writer = None
clip_idx = len([f for f in os.listdir(OUT_DIR) if f.endswith(".mp4")])
rec_start = 0

while True:
    ok, frame = cap.read()
    if not ok:
        break

    display = frame.copy()
    if writer is not None:
        writer.write(frame)
        elapsed = time.time() - rec_start
        cv2.circle(display, (30, 30), 12, (0, 0, 255), -1)
        cv2.putText(display, f"REC {elapsed:.0f}s (clip {clip_idx})", (55, 40),
                    cv2.FONT_HERSHEY_SIMPLEX, 1.0, (0, 0, 255), 2)
    else:
        cv2.putText(display, "Press 'r' to record, 'q' to quit", (20, 40),
                    cv2.FONT_HERSHEY_SIMPLEX, 1.0, (0, 200, 0), 2)

    cv2.imshow("Dataset Recorder", display)
    key = cv2.waitKey(1) & 0xFF

    if key == ord("r"):
        if writer is None:
            path = os.path.join(OUT_DIR, f"clip_{clip_idx:02d}.mp4")
            writer = cv2.VideoWriter(path, cv2.VideoWriter_fourcc(*"mp4v"), fps, (w, h))
            rec_start = time.time()
            print(f"Recording -> {path}")
        else:
            writer.release()
            writer = None
            print(f"Saved clip_{clip_idx:02d}.mp4")
            clip_idx += 1
    elif key == ord("q"):
        break

if writer is not None:
    writer.release()
cap.release()
cv2.destroyAllWindows()
print(f"\nDone. {clip_idx} clips in {OUT_DIR}/")
print("Zip that folder and run train_knife_model_v3_custom.py in Colab.")
