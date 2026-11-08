"""Presentation overlay for demo videos: skeletons and boxes colored by each person's
state, a scenario title, and a banner that appears only when the detector raises an alert.

Everything drawn comes from the detector's own output (``detector.status_for`` and the
alert events); nothing is scripted. Frames are upscaled first and the overlay is drawn
at the output resolution, so lines stay crisp.
"""

import math

import cv2
import numpy as np

from .features import FALLEN, FALLING, NORMAL
from .keypoints import KP_CONF_MIN, SKELETON

FONT = cv2.FONT_HERSHEY_DUPLEX
GREEN, ORANGE, BLUE, RED, GRAY, WHITE = (90, 200, 90), (0, 165, 255), (230, 140, 40), (40, 40, 235), (170, 170, 170), (255, 255, 255)
STATE_STYLE = {NORMAL: (GREEN, "OK"), FALLING: (ORANGE, "Possible fall"), FALLEN: (BLUE, "On the floor")}


def auto_scale(height, target=720):
    """Smallest integer upscale factor that reaches ``target`` pixels of height."""
    return max(1, -(-target // height))


def text_chip(img, text, org, color, scale=0.7, pad=8, bg=(20, 20, 20), alpha=0.72):
    """Text on a translucent rounded-ish box; ``org`` is the box's top-left corner."""
    (tw, th), base = cv2.getTextSize(text, FONT, scale, 2)
    x, y = org
    x2, y2 = x + tw + 2 * pad, y + th + base + 2 * pad
    roi = img[max(y, 0):y2, max(x, 0):x2]
    if roi.size:
        solid = np.empty_like(roi)
        solid[:] = bg
        roi[:] = cv2.addWeighted(roi, 1 - alpha, solid, alpha, 0)
    cv2.putText(img, text, (x + pad, y + pad + th), FONT, scale, color, 2, cv2.LINE_AA)
    return x2, y2


def draw_person(img, person, status, s):
    """Skeleton + box + short label for one person, in output pixels (``s`` = upscale)."""
    alerted = bool(status and status.alerted)
    if alerted:
        color, label = RED, "FALL DETECTED"
    elif status is not None and status.state in STATE_STYLE:
        color, label = STATE_STYLE[status.state]
    else:
        color, label = GRAY, "Tracking"
    thick = max(2, round(s * 0.8))
    x1, y1, x2, y2 = (int(v * s) for v in person.bbox)
    cv2.rectangle(img, (x1, y1), (x2, y2), color, thick)
    kps = person.keypoints
    for a, b in SKELETON:
        if kps[a, 2] >= KP_CONF_MIN and kps[b, 2] >= KP_CONF_MIN:
            cv2.line(img, (int(kps[a, 0] * s), int(kps[a, 1] * s)), (int(kps[b, 0] * s), int(kps[b, 1] * s)),
                     color, thick, cv2.LINE_AA)
    for k in range(17):
        if kps[k, 2] >= KP_CONF_MIN:
            cv2.circle(img, (int(kps[k, 0] * s), int(kps[k, 1] * s)), thick + 1, WHITE, -1, cv2.LINE_AA)
    chip_y = max(0, y1 - int(34 * s / 3 * 1.0) - 6)
    text_chip(img, label, (x1, chip_y), color, scale=0.55 * max(1.0, s / 3))


def fmt_time(seconds):
    return f"{int(seconds // 60)}:{int(seconds % 60):02d}"


def draw_frame(frame, persons, detector, s, title, t_seconds, alert_times, banner_frames_left, fps, frame_idx):
    """Return the upscaled frame with everything drawn.

    alert_times: seconds at which alerts were raised so far; banner_frames_left > 0 shows
    the big alert banner (it pulses so it reads as an alarm)."""
    h, w = frame.shape[:2]
    img = cv2.resize(frame, (w * s, h * s), interpolation=cv2.INTER_LANCZOS4)
    for p in persons:
        draw_person(img, p, detector.status_for(p.track_id), s)
    k = max(1.0, s / 3)
    if title:
        text_chip(img, title, (12, 12), WHITE, scale=0.62 * k)
    if alert_times:
        text_chip(img, f"ALERT RAISED at {fmt_time(alert_times[0])}", (12, img.shape[0] - int(52 * k)), RED, scale=0.62 * k)
    else:
        text_chip(img, "Monitoring - no alert", (12, img.shape[0] - int(52 * k)), GREEN, scale=0.62 * k)
    text_chip(img, fmt_time(t_seconds), (img.shape[1] - int(86 * k), 12), WHITE, scale=0.62 * k)
    if banner_frames_left > 0:
        pulse = 0.68 + 0.17 * math.sin(frame_idx / fps * 8.0)   # gentle pulse: reads as an alarm
        bar_h = int(64 * k)
        y0 = img.shape[0] // 2 - bar_h // 2 - int(60 * k)
        overlay = img.copy()
        cv2.rectangle(overlay, (0, y0), (img.shape[1], y0 + bar_h), RED, -1)
        img = cv2.addWeighted(overlay, pulse, img, 1 - pulse, 0)
        (tw, th), _ = cv2.getTextSize("FALL DETECTED", FONT, 1.6 * k, 3)
        cv2.putText(img, "FALL DETECTED", ((img.shape[1] - tw) // 2, y0 + (bar_h + th) // 2), FONT, 1.6 * k, WHITE, 3, cv2.LINE_AA)
    return img
