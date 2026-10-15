"""Drawing for the attendance demo: face boxes, a 'marked present' toast and the register panel."""

import cv2
import numpy as np

from core.render import FONT, text_chip

from .recognise import fmt_clock

GREEN, AMBER, RED, WHITE, GRAY, DARK = (90, 200, 90), (0, 180, 255), (40, 40, 235), (255, 255, 255), (150, 150, 150), (28, 28, 28)
PANEL_W = 360


def blur_region(img, x, y, w, h, pad=0.2):
    px, py = int(w * pad), int(h * pad)
    x0, y0, x1, y1 = max(0, x - px), max(0, y - py), min(img.shape[1], x + w + px), min(img.shape[0], y + h + py)
    if x1 > x0 and y1 > y0:
        k = max(9, ((x1 - x0) // 3) | 1)
        img[y0:y1, x0:x1] = cv2.GaussianBlur(img[y0:y1, x0:x1], (k, k), 0)


def draw_face(img, box, name, s):
    """Identified: green box + name. Unidentified: amber box + 'Unknown'."""
    x, y, w, h = (int(v * s) for v in box)
    color, label = (GREEN, name) if name else (AMBER, "Unknown")
    cv2.rectangle(img, (x, y), (x + w, y + h), color, max(2, round(s * 1.5)))
    text_chip(img, label, (x, max(0, y - int(36 * max(1.0, s / 1.5)))), color, scale=0.6 * max(1.0, s / 1.5))


def draw_panel(height, register, video_seconds, title="ATTENDANCE"):
    panel = np.full((height, PANEL_W, 3), DARK, np.uint8)
    cv2.putText(panel, title, (18, 38), FONT, 0.8, WHITE, 2, cv2.LINE_AA)
    cv2.putText(panel, f"Present {register.present} of {len(register.names)}", (18, 70), FONT, 0.6,
                GREEN if register.present else GRAY, 1, cv2.LINE_AA)
    cv2.putText(panel, f"Site clock (demo) {fmt_clock(register.clock_at(video_seconds))}", (18, 98), FONT, 0.5, GRAY, 1, cv2.LINE_AA)
    cv2.line(panel, (18, 112), (PANEL_W - 18, 112), (70, 70, 70), 1)
    y = 126
    for pid, name in register.names.items():
        if y + 70 > height:
            break
        entry = register.entries.get(pid)
        if entry is not None and entry.thumb is not None:
            panel[y:y + 56, 18:74] = cv2.resize(entry.thumb, (56, 56))
        else:
            cv2.rectangle(panel, (18, y), (74, y + 56), (60, 60, 60), -1)
        cv2.putText(panel, name[:22], (88, y + 20), FONT, 0.55, WHITE if entry else GRAY, 1, cv2.LINE_AA)
        if entry is None and pid in register.seen_outside_hours:
            cv2.putText(panel, "Seen outside hours", (88, y + 46), FONT, 0.5, AMBER, 1, cv2.LINE_AA)
            cv2.putText(panel, "not counted as arrival", (88, y + 64), FONT, 0.45, GRAY, 1, cv2.LINE_AA)
        elif entry is None:
            cv2.putText(panel, "Not yet arrived", (88, y + 46), FONT, 0.5, GRAY, 1, cv2.LINE_AA)
        else:
            tag, color = ("On time", GREEN) if entry.status == "on_time" else (f"Late +{entry.minutes_late} min", AMBER)
            cv2.putText(panel, f"{fmt_clock(entry.clock_s)}  {tag}", (88, y + 46), FONT, 0.5, color, 1, cv2.LINE_AA)
        y += 70
    return panel


def draw_toast(img, entry, s):
    tag = "On time" if entry.status == "on_time" else f"Late +{entry.minutes_late} min"
    k = max(1.0, s / 1.5)
    text_chip(img, f"{entry.name} marked present  {fmt_clock(entry.clock_s)}  {tag}",
              (16, img.shape[0] - int(110 * k)), GREEN if entry.status == "on_time" else AMBER, scale=0.7 * k)
