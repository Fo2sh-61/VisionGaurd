"""
Real-time knife detection from a laptop webcam using your custom-trained
knife-finetuned-v2.onnx model.

Usage:
    pip install onnxruntime opencv-python numpy
    python knife_webcam_detect.py
    (press 'q' in the video window to quit)
"""

import time
from collections import deque

import cv2
import numpy as np
import onnxruntime as ort

# ---------------------------------------------------------------------------
# Config
# ---------------------------------------------------------------------------
MODEL_PATH = "knife-finetuned-v3.onnx"  # your custom-trained model (keep this script next to the .onnx file)
CAMERA_INDEX = 0                 # live webcam (0 = default camera; try 1 if wrong camera opens)
INPUT_SIZE = 640                # model was trained/exported at 640x640
CONF_THRESHOLD = 0.45
IOU_THRESHOLD = 0.45

DETECT_GUNS_TOO = False         # set True to also draw/alert on guns

# --- Temporal consistency filter -------------------------------------------
# Background clutter (ladders, wood panels, pipes, etc.) can trip the model
# for a stray frame. Setting MIN_HITS=1 means a detection draws/alerts
# instantly on the very first frame it appears in (no delay) - the trade-off
# is that one-off false positives are no longer filtered out by persistence,
# so CONF_THRESHOLD above is the main defense against those instead. Raise
# MIN_HITS again later if you'd rather trade a few frames of delay for fewer
# false positives.
HISTORY_LEN = 8      # how many recent frames to remember
MIN_HITS = 1         # box must reappear in at least this many of them (1 = instant, no delay)
IOU_MATCH_THRESHOLD = 0.3   # how much overlap counts as "the same box"

# Class names are read from the ONNX model's own metadata at load time
# (see load_class_names below) so this keeps working if the model is
# swapped again later.
CLASS_NAMES = {}
TARGET_CLASSES = set()


def load_class_names(session):
    """Pull the {id: name} mapping out of the model's embedded metadata."""
    meta = session.get_modelmeta().custom_metadata_map
    names_str = meta.get("names", "{}")
    names = eval(names_str, {"__builtins__": {}})  # e.g. "{0: 'guns', 1: 'knife'}"
    return {int(k): v for k, v in names.items()}


def resolve_target_classes(class_names):
    targets = {cid for cid, name in class_names.items() if "knife" in name.lower()}
    if DETECT_GUNS_TOO:
        targets |= {cid for cid, name in class_names.items()
                    if "gun" in name.lower() or "pistol" in name.lower()}
    return targets or set(class_names)  # fall back to "everything" if no match

BOX_COLOR = (0, 0, 255)         # red boxes (BGR)
TEXT_COLOR = (255, 255, 255)
DETECT_COLOR = (0, 0, 255)      # red banner when something is found
NO_DETECT_COLOR = (0, 160, 0)   # green banner when nothing is found
PANEL_BG = (30, 30, 30)


def draw_status_banner(frame, found):
    h, w = frame.shape[:2]
    text = "KNIFE DETECTED" if found else "NO DETECTION"
    color = DETECT_COLOR if found else NO_DETECT_COLOR

    cv2.rectangle(frame, (0, 0), (w, 40), color, -1)
    cv2.putText(frame, text, (10, 28), cv2.FONT_HERSHEY_SIMPLEX,
                0.9, (255, 255, 255), 2)


def draw_detections_panel(frame, detections):
    """Bounding boxes on the frame + a side panel listing each detection's data."""
    panel_x = frame.shape[1] - 300
    panel_y = 50
    line_h = 20

    panel_h = 20 + line_h * (1 + 4 * max(len(detections), 0)) if detections else 0
    if detections:
        overlay = frame.copy()
        cv2.rectangle(overlay, (panel_x, panel_y),
                      (panel_x + 290, panel_y + panel_h + 10), PANEL_BG, -1)
        cv2.addWeighted(overlay, 0.6, frame, 0.4, 0, frame)

        cv2.putText(frame, f"Detections: {len(detections)}", (panel_x + 8, panel_y + 18),
                    cv2.FONT_HERSHEY_SIMPLEX, 0.55, (0, 255, 255), 1)
        y = panel_y + 18

    for idx, (box, cls_id, conf) in enumerate(detections):
        x1, y1, x2, y2 = box.astype(int)
        name = CLASS_NAMES.get(int(cls_id), str(cls_id))

        # box + label directly on the object
        label = f"{name} {conf:.2f}"
        cv2.rectangle(frame, (x1, y1), (x2, y2), BOX_COLOR, 2)
        (tw, th), _ = cv2.getTextSize(label, cv2.FONT_HERSHEY_SIMPLEX, 0.6, 2)
        cv2.rectangle(frame, (x1, max(y1 - th - 10, 0)), (x1 + tw + 6, max(y1, th + 10)), BOX_COLOR, -1)
        cv2.putText(frame, label, (x1 + 3, max(y1 - 6, th + 4)),
                    cv2.FONT_HERSHEY_SIMPLEX, 0.6, TEXT_COLOR, 2)

        # detailed data in the side panel
        y += line_h
        cv2.putText(frame, f"#{idx} {name}", (panel_x + 8, y),
                    cv2.FONT_HERSHEY_SIMPLEX, 0.5, (255, 255, 255), 1)
        y += line_h
        cv2.putText(frame, f"conf: {conf:.3f}", (panel_x + 8, y),
                    cv2.FONT_HERSHEY_SIMPLEX, 0.5, (200, 200, 200), 1)
        y += line_h
        cv2.putText(frame, f"xy: ({x1},{y1})-({x2},{y2})", (panel_x + 8, y),
                    cv2.FONT_HERSHEY_SIMPLEX, 0.45, (200, 200, 200), 1)
        y += line_h
        cv2.putText(frame, f"wh: {x2 - x1}x{y2 - y1}", (panel_x + 8, y),
                    cv2.FONT_HERSHEY_SIMPLEX, 0.45, (200, 200, 200), 1)


def letterbox(img, new_size=640, color=(114, 114, 114)):
    """Resize + pad image to a square while keeping aspect ratio, YOLO-style."""
    h, w = img.shape[:2]
    scale = min(new_size / h, new_size / w)
    nh, nw = int(round(h * scale)), int(round(w * scale))
    resized = cv2.resize(img, (nw, nh), interpolation=cv2.INTER_LINEAR)

    pad_h, pad_w = new_size - nh, new_size - nw
    top, bottom = pad_h // 2, pad_h - pad_h // 2
    left, right = pad_w // 2, pad_w - pad_w // 2

    padded = cv2.copyMakeBorder(resized, top, bottom, left, right,
                                 cv2.BORDER_CONSTANT, value=color)
    return padded, scale, left, top


def preprocess(frame):
    img, scale, pad_x, pad_y = letterbox(frame, INPUT_SIZE)
    img = cv2.cvtColor(img, cv2.COLOR_BGR2RGB).astype(np.float32) / 255.0
    img = img.transpose(2, 0, 1)[None, ...]  # HWC -> NCHW, add batch dim
    return np.ascontiguousarray(img), scale, pad_x, pad_y


def postprocess(output, scale, pad_x, pad_y, frame_shape):
    # output shape: (1, 4 + num_classes, num_boxes) -> (num_boxes, 4 + num_classes)
    preds = np.squeeze(output).T
    boxes_xywh = preds[:, :4]
    class_scores = preds[:, 4:]

    class_ids = np.argmax(class_scores, axis=1)
    confidences = class_scores[np.arange(len(class_scores)), class_ids]

    keep = confidences > CONF_THRESHOLD
    boxes_xywh, class_ids, confidences = boxes_xywh[keep], class_ids[keep], confidences[keep]

    target_mask = np.isin(class_ids, list(TARGET_CLASSES))
    boxes_xywh, class_ids, confidences = boxes_xywh[target_mask], class_ids[target_mask], confidences[target_mask]

    if len(boxes_xywh) == 0:
        return []

    # cx, cy, w, h (in letterboxed 640x640 space) -> x1, y1, x2, y2
    cx, cy, w, h = boxes_xywh[:, 0], boxes_xywh[:, 1], boxes_xywh[:, 2], boxes_xywh[:, 3]
    x1 = cx - w / 2
    y1 = cy - h / 2
    x2 = cx + w / 2
    y2 = cy + h / 2

    # undo letterbox padding/scaling to map back to the original frame
    x1 = (x1 - pad_x) / scale
    y1 = (y1 - pad_y) / scale
    x2 = (x2 - pad_x) / scale
    y2 = (y2 - pad_y) / scale

    fh, fw = frame_shape[:2]
    x1 = np.clip(x1, 0, fw - 1)
    y1 = np.clip(y1, 0, fh - 1)
    x2 = np.clip(x2, 0, fw - 1)
    y2 = np.clip(y2, 0, fh - 1)

    boxes_xyxy = np.stack([x1, y1, x2, y2], axis=1)

    # NMS expects [x, y, w, h]
    nms_boxes = np.stack([x1, y1, x2 - x1, y2 - y1], axis=1).tolist()
    indices = cv2.dnn.NMSBoxes(nms_boxes, confidences.tolist(), CONF_THRESHOLD, IOU_THRESHOLD)
    if len(indices) == 0:
        return []
    indices = np.array(indices).flatten()

    results = []
    for i in indices:
        results.append((boxes_xyxy[i], class_ids[i], confidences[i]))
    return results


def _iou(box_a, box_b):
    xa = max(box_a[0], box_b[0])
    ya = max(box_a[1], box_b[1])
    xb = min(box_a[2], box_b[2])
    yb = min(box_a[3], box_b[3])
    inter = max(0, xb - xa) * max(0, yb - ya)
    area_a = (box_a[2] - box_a[0]) * (box_a[3] - box_a[1])
    area_b = (box_b[2] - box_b[0]) * (box_b[3] - box_b[1])
    union = area_a + area_b - inter
    return inter / union if union > 0 else 0.0


def filter_persistent(detections, history):
    """Only keep detections that recur in enough of the recent frames.

    `history` is a deque of past frames' raw detection lists (each a list
    of (box, cls_id, conf)). The current frame's detections are appended
    to it, then anything that doesn't have enough IoU-matching neighbors
    across the window is dropped as a likely one-off false positive.
    """
    history.append(detections)

    confirmed = []
    for box, cls_id, conf in detections:
        hits = sum(
            1 for past in history
            if any(pc == cls_id and _iou(box, pbox) > IOU_MATCH_THRESHOLD
                   for pbox, pc, _ in past)
        )
        if hits >= MIN_HITS:
            confirmed.append((box, cls_id, conf))
    return confirmed


def main():
    global CLASS_NAMES, TARGET_CLASSES

    print("Loading model...")
    # Try GPU acceleration first (DirectML works with NVIDIA/AMD/Intel GPUs on
    # Windows, no CUDA setup needed), fall back to CPU if unavailable.
    available = ort.get_available_providers()
    providers = ["DmlExecutionProvider", "CPUExecutionProvider"] if "DmlExecutionProvider" in available else ["CPUExecutionProvider"]
    session = ort.InferenceSession(MODEL_PATH, providers=providers)
    print("Using provider:", session.get_providers()[0])
    input_name = session.get_inputs()[0].name

    CLASS_NAMES = load_class_names(session)
    TARGET_CLASSES = resolve_target_classes(CLASS_NAMES)
    print("Model classes:", CLASS_NAMES)
    print("Flagging:", {CLASS_NAMES[c] for c in TARGET_CLASSES})

    cap = cv2.VideoCapture(CAMERA_INDEX)
    if not cap.isOpened():
        raise RuntimeError(f"Could not open video source: {CAMERA_INDEX}")

    # Request the highest resolution the webcam supports. This doesn't slow
    # down inference (the model still only ever sees a 640x640 letterboxed
    # crop) but gives the resize step more real detail to work with, which
    # helps the model resolve smaller/farther-away knives.
    cap.set(cv2.CAP_PROP_FRAME_WIDTH, 1920)
    cap.set(cv2.CAP_PROP_FRAME_HEIGHT, 1080)
    actual_w = int(cap.get(cv2.CAP_PROP_FRAME_WIDTH))
    actual_h = int(cap.get(cv2.CAP_PROP_FRAME_HEIGHT))
    print(f"Camera resolution: {actual_w}x{actual_h}")

    print(f"Source opened: {CAMERA_INDEX}. Press 'q' to quit.")
    prev_time = time.time()
    history = deque(maxlen=HISTORY_LEN)

    while True:
        ok, frame = cap.read()
        if not ok:
            print("End of video / failed to read frame.")
            break

        img, scale, pad_x, pad_y = preprocess(frame)
        output = session.run(None, {input_name: img})[0]
        raw_detections = postprocess(output, scale, pad_x, pad_y, frame.shape)
        detections = filter_persistent(raw_detections, history)

        for box, cls_id, conf in detections:
            if "knife" in CLASS_NAMES.get(int(cls_id), "").lower():
                print(f"[ALERT] Knife detected (confidence {conf:.2f})")

        draw_detections_panel(frame, detections)
        draw_status_banner(frame, found=len(detections) > 0)

        now = time.time()
        fps = 1 / (now - prev_time) if now > prev_time else 0
        prev_time = now
        cv2.putText(frame, f"FPS: {fps:.1f}", (10, frame.shape[0] - 10),
                    cv2.FONT_HERSHEY_SIMPLEX, 0.7, (0, 255, 0), 2)

        cv2.imshow("Knife Detection", frame)
        if cv2.waitKey(1) & 0xFF == ord("q"):
            break

    cap.release()
    cv2.destroyAllWindows()


if __name__ == "__main__":
    main()
