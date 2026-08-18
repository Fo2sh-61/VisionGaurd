"""
Fine-tune YOLOv8 on the Kaggle "Knife Dataset" by shank885
(https://www.kaggle.com/datasets/shank885/knife-dataset - the dataset behind
the "starter-knife-dataset-79da7791-0" notebook you linked) and export it to
ONNX, ready to drop into knife_webcam_detect.py.

This is an older (2020) dataset, so unlike the other Kaggle set we used, it
may not ship pre-formatted for YOLO (data.yaml + images/labels). This script
handles three possible layouts automatically:
  1. Already has a data.yaml -> use it directly.
  2. Has a train/valid + images/labels YOLO-style layout -> build a data.yaml.
  3. Has Pascal VOC style XML annotations (images/ + Annotations/*.xml) ->
     converts every XML box to YOLO .txt format (single class: knife) and
     builds a data.yaml from that.
If none of these match, it prints the folder contents so you can tell me
what it actually looks like and I'll adjust the script.

HOW TO RUN (Google Colab):
1. https://colab.research.google.com/ -> New notebook
2. Runtime -> Change runtime type -> GPU (T4, free tier)
3. Get your Kaggle API token: kaggle.com -> profile picture -> Settings ->
   API -> "Create New Token" (downloads kaggle.json)
4. Paste this whole file into one cell, run it (Shift+Enter). It will pause
   and ask you to upload kaggle.json when it needs it.
5. When done, it auto-downloads knife-finetuned.onnx. Move it next to
   knife_webcam_detect.py and set:
       MODEL_PATH = "knife-finetuned.onnx"
"""

EPOCHS = 100
IMG_SIZE = 640
DATASET_SLUG = "shank885/knife-dataset"

# --- Install dependencies ---------------------------------------------------
import subprocess, sys
subprocess.run([sys.executable, "-m", "pip", "install", "-q", "kaggle", "ultralytics"], check=True)

import os
import shutil
import xml.etree.ElementTree as ET
from pathlib import Path

# --- Kaggle auth -------------------------------------------------------------
kaggle_dir = Path.home() / ".kaggle"
kaggle_dir.mkdir(exist_ok=True)
kaggle_json = kaggle_dir / "kaggle.json"

if not kaggle_json.exists():
    try:
        from google.colab import files
        print("Upload your kaggle.json API token now...")
        uploaded = files.upload()
        for fname in uploaded:
            Path(fname).rename(kaggle_json)
    except ImportError:
        raise RuntimeError(
            "Place your kaggle.json at ~/.kaggle/kaggle.json before running "
            "this script (not running inside Colab, so the upload prompt "
            "isn't available)."
        )

os.chmod(kaggle_json, 0o600)

# --- Download the dataset ----------------------------------------------------
DATA_DIR = Path("knife_dataset_shank885")
DATA_DIR.mkdir(exist_ok=True)

subprocess.run(
    ["kaggle", "datasets", "download", "-d", DATASET_SLUG, "-p", str(DATA_DIR), "--unzip"],
    check=True,
)
print(f"Dataset downloaded to: {DATA_DIR.resolve()}")

print("Folder contents:")
all_paths = sorted(DATA_DIR.rglob("*"))
for p in all_paths[:80]:
    print(" ", p.relative_to(DATA_DIR))
if len(all_paths) > 80:
    print(f"  ... and {len(all_paths) - 80} more files")

# --- Case 1: already has a data.yaml ----------------------------------------
yaml_candidates = list(DATA_DIR.rglob("data.yaml"))
data_yaml_path = None

if yaml_candidates:
    data_yaml_path = yaml_candidates[0]
    print(f"\nFound existing data.yaml: {data_yaml_path}")

# --- Case 2: YOLO-style images/labels layout --------------------------------
if data_yaml_path is None:
    train_images = next((p for p in DATA_DIR.rglob("*") if p.is_dir() and p.name == "images"
                          and "train" in str(p).lower()), None)
    val_images = next((p for p in DATA_DIR.rglob("*") if p.is_dir() and p.name == "images"
                        and ("valid" in str(p).lower() or "val" in str(p).lower())), None)
    if train_images:
        print(f"\nFound YOLO-style layout: {train_images}")
        data_yaml_path = DATA_DIR / "auto_data.yaml"
        data_yaml_path.write_text(
            f"train: {train_images}\n"
            f"val: {val_images or train_images}\n"
            f"nc: 1\n"
            f"names: ['knife']\n"
        )

# --- Case 3: Pascal VOC XML annotations -> convert to YOLO -------------------
if data_yaml_path is None:
    xml_files = list(DATA_DIR.rglob("*.xml"))
    if xml_files:
        print(f"\nFound {len(xml_files)} Pascal VOC XML annotation files - converting to YOLO format...")

        YOLO_DIR = DATA_DIR / "yolo_converted"
        (YOLO_DIR / "images").mkdir(parents=True, exist_ok=True)
        (YOLO_DIR / "labels").mkdir(parents=True, exist_ok=True)

        converted = 0
        for xml_path in xml_files:
            try:
                tree = ET.parse(xml_path)
                root = tree.getroot()
                filename = root.find("filename").text
                img_path = xml_path.parent / filename
                if not img_path.exists():
                    # sometimes images live in a sibling folder
                    matches = list(DATA_DIR.rglob(filename))
                    if not matches:
                        continue
                    img_path = matches[0]

                size = root.find("size")
                img_w = int(size.find("width").text)
                img_h = int(size.find("height").text)

                lines = []
                for obj in root.findall("object"):
                    box = obj.find("bndbox")
                    xmin = float(box.find("xmin").text)
                    ymin = float(box.find("ymin").text)
                    xmax = float(box.find("xmax").text)
                    ymax = float(box.find("ymax").text)

                    cx = ((xmin + xmax) / 2) / img_w
                    cy = ((ymin + ymax) / 2) / img_h
                    w = (xmax - xmin) / img_w
                    h = (ymax - ymin) / img_h
                    lines.append(f"0 {cx:.6f} {cy:.6f} {w:.6f} {h:.6f}")  # class 0 = knife

                if not lines:
                    continue

                shutil.copy(img_path, YOLO_DIR / "images" / img_path.name)
                (YOLO_DIR / "labels" / (img_path.stem + ".txt")).write_text("\n".join(lines))
                converted += 1
            except Exception as e:
                print(f"  Skipped {xml_path.name}: {e}")

        print(f"Converted {converted} images with boxes.")
        if converted == 0:
            raise RuntimeError(
                "Found XML files but couldn't convert any (see errors above). "
                "Check the XML structure and adjust the parsing code."
            )

        data_yaml_path = YOLO_DIR / "data.yaml"
        data_yaml_path.write_text(
            f"train: {(YOLO_DIR / 'images').resolve()}\n"
            f"val: {(YOLO_DIR / 'images').resolve()}\n"
            f"nc: 1\n"
            f"names: ['knife']\n"
        )

# --- Give up gracefully if nothing matched -----------------------------------
if data_yaml_path is None:
    raise RuntimeError(
        "Couldn't auto-detect this dataset's format (no data.yaml, no "
        "images/labels folders, no XML annotations). See the folder "
        "listing printed above - tell Claude what it looks like and the "
        "script can be adjusted."
    )

print(f"\nUsing data.yaml:\n{data_yaml_path.read_text()}")

# --- Fine-tune YOLOv8n --------------------------------------------------------
from ultralytics import YOLO

model = YOLO("yolov8n.pt")
results = model.train(
    data=str(data_yaml_path),
    epochs=EPOCHS,
    imgsz=IMG_SIZE,
    patience=20,
)

best_pt = f"{results.save_dir}/weights/best.pt"
print(f"Best weights: {best_pt}")

# --- Export to ONNX ------------------------------------------------------------
trained = YOLO(best_pt)
exported_path = trained.export(format="onnx", imgsz=IMG_SIZE, opset=12, simplify=True)

shutil.copy(exported_path, "knife-finetuned.onnx")
print("Saved: knife-finetuned.onnx")

# --- Download it from Colab ---------------------------------------------------
try:
    from google.colab import files
    files.download("knife-finetuned.onnx")
except ImportError:
    print("Not running in Colab - find knife-finetuned.onnx in the working directory.")

print("\nDone. Move knife-finetuned.onnx next to knife_webcam_detect.py and set:")
print('    MODEL_PATH = "knife-finetuned.onnx"')
