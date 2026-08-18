"""
One-time setup: download a stronger, more recently-trained threat-detection
model (guns, explosives, grenades, AND knives - published val mAP50 ~81%,
knife mAP50 ~81% on its own test set) and export it to ONNX so
knife_webcam_detect.py can use it instead of normal.onnx.

Why: normal.onnx (from the wavelet-detection research project) is a small
YOLOv8-nano model trained on a narrow dataset - it visibly struggles on a
real webcam (different lighting/angle/distance than its training images).
This model (Subh775/Threat-Detection-YOLOv8n on Hugging Face) was trained
specifically for security/surveillance-style detection with a larger,
more varied dataset, so it should generalize better to a live camera.

Run this ONCE on your own machine (needs internet access to Hugging Face,
which your Windows PC has - this can't run inside Claude's sandboxed
environment because that network is locked down to a handful of domains).

Install the CPU-only build of PyTorch first (much smaller/faster than the
default - the default pulls in several GB of NVIDIA CUDA packages you
don't need for this):

    pip install torch --index-url https://download.pytorch.org/whl/cpu
    pip install ultralytics huggingface_hub
    python export_threat_model.py

It downloads the trained weights, exports them to threat-detection.onnx
in this same folder, and prints the exact one-line edit to make in
knife_webcam_detect.py.
"""

from huggingface_hub import hf_hub_download
from ultralytics import YOLO

REPO_ID = "Subh775/Threat-Detection-YOLOv8n"
WEIGHTS_FILE = "weights/best.pt"
OUTPUT_NAME = "threat-detection.onnx"

print(f"Downloading weights from {REPO_ID} ...")
pt_path = hf_hub_download(repo_id=REPO_ID, filename=WEIGHTS_FILE)
print(f"Downloaded: {pt_path}")

print("Loading model and exporting to ONNX (this can take a minute)...")
model = YOLO(pt_path)
exported_path = model.export(format="onnx", imgsz=640, opset=12, simplify=True)

import shutil
shutil.copy(exported_path, OUTPUT_NAME)
print(f"\nDone! Saved as: {OUTPUT_NAME}")
print(f"\nNow open knife_webcam_detect.py and change:")
print(f'    MODEL_PATH = "normal.onnx"')
print(f"to:")
print(f'    MODEL_PATH = "{OUTPUT_NAME}"')
print("\nEverything else (class names, knife filtering, temporal filter) "
      "adapts automatically - no other changes needed.")
