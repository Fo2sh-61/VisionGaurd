"""Cinematic SIMULATED attendance visuals.

Everything here is an illustration: people are located with a pose detector (face boxes come from
head keypoints, so only faces turned to the camera get one), and WHO they are is scripted (placeholder
names). No recognition runs, and a permanent caption on every frame says so. There are no confidence
numbers: a made-up percentage would be a made-up measurement.
"""

import math
from dataclasses import dataclass, field

import cv2
import numpy as np

from core.render import FONT

TEAL, AMBER, WHITE, DARK, GRAY = (210, 220, 60), (0, 180, 255), (255, 255, 255), (24, 24, 24), (160, 160, 160)
CAPTION = "SIMULATED DEMONSTRATION - illustrative, not live system output"


# ------------------------------------------------------------------ geometry --

def face_box(kps, min_conf=0.5, min_eye_px=7.0):
    """Face box (x, y, w, h) from COCO head keypoints, or None unless the face is turned to the camera
    (nose and both eyes seen)."""
    nose, l_eye, r_eye = kps[0], kps[1], kps[2]
    if min(nose[2], l_eye[2], r_eye[2]) < min_conf:
        return None
    eyes = float(np.hypot(l_eye[0] - r_eye[0], l_eye[1] - r_eye[1]))
    if eyes < min_eye_px:
        return None
    cx = (l_eye[0] + r_eye[0] + nose[0]) / 3.0
    cy = (l_eye[1] + r_eye[1]) / 2.0 + 0.6 * eyes
    h = eyes * 3.0
    w = h * 0.82
    return (cx - w / 2, cy - h / 2, w, h)


def ease_out(t):
    t = min(1.0, max(0.0, t))
    return 1 - (1 - t) ** 3


# -------------------------------------------------------------------- tracks --

@dataclass
class CineTrack:
    id: int
    box: tuple
    first_frame: int
    last_frame: int
    hits: int = 1
    name: str | None = None          # None = not assigned yet, "?" = scripted Unknown
    locked_frame: int | None = None
    thumb: np.ndarray | None = None


class NameQueue:
    """Hands out scripted names in order of appearance; every ``unknown_every``-th person is a visitor
    ('?'). After the script runs out it continues with 'Employee NN'."""

    def __init__(self, names=(), unknown_every=0):
        self.names, self.unknown_every, self.count, self._emp = list(names), unknown_every, 0, 0

    def next(self):
        self.count += 1
        if self.count <= len(self.names):
            return self.names[self.count - 1]
        if self.unknown_every and self.count % self.unknown_every == 0:
            return "?"
        self._emp += 1
        return f"Employee {len(self.names) + self._emp:02d}"


class CineTracks:
    """Stable face tracks from the pose tracker's ids, with box smoothing and re-linking: a person the
    tracker renames within a second, at the same spot, keeps their name (no double 'employees')."""

    def __init__(self, queue, lock_frames=8, smooth=0.4, relink_frames=30, max_age=10):
        self.queue, self.lock_frames, self.smooth = queue, lock_frames, smooth
        self.relink_frames, self.max_age = relink_frames, max_age
        self.tracks: dict[int, CineTrack] = {}
        self.lost: list[CineTrack] = []

    def update(self, frame_idx, faces):
        """faces: [(track_id, box)] -> list of CineTrack seen this frame."""
        seen = []
        for tid, box in faces:
            t = self.tracks.get(tid)
            if t is None:
                t = CineTrack(tid, box, frame_idx, frame_idx)
                cx, cy = box[0] + box[2] / 2, box[1] + box[3] / 2
                # the tracker may have swapped ids while the old one is still "alive": consider both
                for old in self.lost + [o for o in self.tracks.values() if o.last_frame < frame_idx]:
                    ox, oy = old.box[0] + old.box[2] / 2, old.box[1] + old.box[3] / 2
                    if (frame_idx - old.last_frame <= self.relink_frames and old.name is not None
                            and math.hypot(cx - ox, cy - oy) < 1.2 * max(box[2], old.box[2])):
                        t.name, t.locked_frame, t.thumb, t.first_frame = old.name, old.locked_frame, old.thumb, old.first_frame
                        t.hits = old.hits
                        if old in self.lost:
                            self.lost.remove(old)
                        else:
                            del self.tracks[old.id]
                        break
                self.tracks[tid] = t
            else:
                t.hits += 1
                a = self.smooth
                t.box = tuple(a * n + (1 - a) * o for n, o in zip(box, t.box))
            t.last_frame = frame_idx
            if t.name is None and t.hits >= self.lock_frames:
                t.name, t.locked_frame = self.queue.next(), frame_idx
            seen.append(t)
        for tid in [k for k, t in self.tracks.items() if frame_idx - t.last_frame > self.max_age]:
            self.lost.append(self.tracks.pop(tid))
        self.lost = [t for t in self.lost if frame_idx - t.last_frame <= self.relink_frames]
        return seen


# ------------------------------------------------------------------- drawing --

def corner_box(img, box, color, thickness, grow=1.0, alpha=1.0):
    x, y, w, h = box
    cx, cy = x + w / 2, y + h / 2
    w, h = w * grow, h * grow
    x0, y0, x1, y1 = int(cx - w / 2), int(cy - h / 2), int(cx + w / 2), int(cy + h / 2)
    ln = max(6, int(min(w, h) * 0.28))
    layer = img if alpha >= 1 else img.copy()
    for (px, py, dx, dy) in ((x0, y0, 1, 1), (x1, y0, -1, 1), (x0, y1, 1, -1), (x1, y1, -1, -1)):
        cv2.line(layer, (px, py), (px + dx * ln, py), color, thickness, cv2.LINE_AA)
        cv2.line(layer, (px, py), (px, py + dy * ln), color, thickness, cv2.LINE_AA)
    if layer is not img:
        cv2.addWeighted(layer, alpha, img, 1 - alpha, 0, img)
    return x0, y0, x1, y1


def pixelate(img, box, pad=0.25, blocks=7):
    x, y, w, h = box
    x0, y0 = max(0, int(x - w * pad)), max(0, int(y - h * pad))
    x1, y1 = min(img.shape[1], int(x + w * (1 + pad))), min(img.shape[0], int(y + h * (1 + pad)))
    if x1 - x0 < 4 or y1 - y0 < 4:
        return
    roi = img[y0:y1, x0:x1]
    small = cv2.resize(roi, (blocks, max(2, int(blocks * roi.shape[0] / roi.shape[1]))), interpolation=cv2.INTER_AREA)
    img[y0:y1, x0:x1] = cv2.resize(small, (roi.shape[1], roi.shape[0]), interpolation=cv2.INTER_NEAREST)


def chip(img, text, org, color, scale=0.62, pad=7, alpha=0.78):
    (tw, th), base = cv2.getTextSize(text, FONT, scale, 1)
    x, y = int(org[0]), int(org[1])
    x0, y0 = max(0, x), max(0, y)
    x1, y1 = min(img.shape[1], x + tw + 2 * pad), min(img.shape[0], y + th + base + 2 * pad)
    if x1 > x0 and y1 > y0:
        roi = img[y0:y1, x0:x1]
        solid = np.empty_like(roi)
        solid[:] = DARK
        roi[:] = cv2.addWeighted(roi, 1 - alpha, solid, alpha, 0)
    cv2.putText(img, text, (x + pad, y + pad + th), FONT, scale, color, 1, cv2.LINE_AA)
    return x + tw + 2 * pad, y + th + base + 2 * pad


def draw_track(img, t, frame_idx, fps):
    """One scripted face: lock-on animation (shrinking brackets + scan line), then a steady box and name."""
    p = ease_out((frame_idx - (t.locked_frame if t.locked_frame is not None else frame_idx)) / (0.45 * fps))
    unknown = t.name == "?"
    color = AMBER if unknown else TEAL
    thick = max(2, int(img.shape[0] / 420))
    if unknown:
        pixelate(img, t.box)
    x0, y0, x1, y1 = corner_box(img, t.box, color, thick, grow=1.0 + 0.7 * (1 - p), alpha=0.35 + 0.65 * p)
    if p < 1:
        sy = int(y0 + (y1 - y0) * ((frame_idx * 0.09) % 1.0))
        cv2.line(img, (x0, sy), (x1, sy), color, 1, cv2.LINE_AA)
    if p > 0.4:
        label = "Unknown" if unknown else t.name
        chip(img, label, (x0, y0 - int(img.shape[0] * 0.05)), color, scale=img.shape[0] / 1500 + 0.18)


def glass_panel(img, x, y, w, h, alpha=0.62):
    roi = img[y:y + h, x:x + w]
    solid = np.empty_like(roi)
    solid[:] = DARK
    roi[:] = cv2.addWeighted(roi, 1 - alpha, solid, alpha, 0)
    cv2.rectangle(img, (x, y), (x + w, y + h), (80, 80, 80), 1)


def draw_register(img, register, appear, frame_idx, fps, video_seconds, rate):
    """Right-hand glass panel: latest arrivals first, rows slide in."""
    H, W = img.shape[:2]
    pw, ph = int(W * 0.235), int(H * 0.62)
    px, py = W - pw - 24, 64
    glass_panel(img, px, py, pw, ph)
    s = H / 1080
    cv2.putText(img, "ATTENDANCE", (px + 18, py + int(38 * s)), FONT, 0.8 * s + 0.1, WHITE, 1, cv2.LINE_AA)
    on = sum(1 for e in register.entries.values() if e.status == "on_time")
    late = register.present - on
    cv2.putText(img, f"Present {register.present}   On time {on}   Late {late}", (px + 18, py + int(70 * s)), FONT, 0.5 * s + 0.1, GRAY, 1, cv2.LINE_AA)
    cv2.line(img, (px + 18, py + int(84 * s)), (px + pw - 18, py + int(84 * s)), (70, 70, 70), 1)
    row_h = int(70 * s)
    entries = sorted(register.entries.values(), key=lambda e: e.frame_idx, reverse=True)
    y = py + int(98 * s)
    for e in entries:
        if y + row_h > py + ph:
            break
        slide = 1 - ease_out((frame_idx - appear.get(e.person_id, 0)) / (0.5 * fps))
        ox = int(slide * pw * 0.6)
        if e.thumb is not None and e.thumb.size:
            th = cv2.resize(e.thumb, (int(row_h * 0.8), int(row_h * 0.8)))
            img[y:y + th.shape[0], px + 18 + ox:px + 18 + ox + th.shape[1]] = th
        tx = px + 18 + int(row_h * 0.8) + 14 + ox
        tag, color = ("On time", TEAL) if e.status == "on_time" else (f"Late +{e.minutes_late} min", AMBER)
        cv2.putText(img, e.name[:20], (tx, y + int(24 * s)), FONT, 0.58 * s + 0.1, WHITE, 1, cv2.LINE_AA)
        cv2.putText(img, f"{fmt(e.clock_s)}  {tag}", (tx, y + int(50 * s)), FONT, 0.46 * s + 0.1, color, 1, cv2.LINE_AA)
        y += row_h


def fmt(sec):
    s = int(sec) % 86400
    return f"{s // 3600:02d}:{s % 3600 // 60:02d}:{s % 60:02d}"


def paste(img, patch, x, y):
    """Copy ``patch`` onto ``img`` at (x, y), clipped to the image (x may be negative)."""
    h, w = patch.shape[:2]
    x0, y0, x1, y1 = max(0, x), max(0, y), min(img.shape[1], x + w), min(img.shape[0], y + h)
    if x1 > x0 and y1 > y0:
        img[y0:y1, x0:x1] = patch[y0 - y:y1 - y, x0 - x:x1 - x]


def lower_third(img, entry, age_frames, fps):
    """Slide-in banner when someone is marked present."""
    H, W = img.shape[:2]
    p = ease_out(age_frames / (0.4 * fps))
    if age_frames > 2.6 * fps:
        p = 1 - ease_out((age_frames - 2.6 * fps) / (0.4 * fps))
    if p <= 0:
        return
    s = H / 1080
    bw, bh = int(W * 0.34), int(86 * s)
    x = int(-bw + p * (bw + 36))
    y = H - int(150 * s)
    banner = img[y:y + bh, max(0, 0):bw].copy()                    # background under the banner's final box
    banner = cv2.resize(img[y:y + bh, 36:36 + bw], (bw, bh)) if banner.shape[1] != bw else banner
    solid = np.empty_like(banner)
    solid[:] = DARK
    banner = cv2.addWeighted(banner, 0.22, solid, 0.78, 0)
    color = TEAL if entry.status == "on_time" else AMBER
    cv2.rectangle(banner, (0, 0), (6, bh), color, -1)
    cv2.rectangle(banner, (0, 0), (bw - 1, bh - 1), (80, 80, 80), 1)
    if entry.thumb is not None and entry.thumb.size:
        th = cv2.resize(entry.thumb, (int(bh * 0.76), int(bh * 0.76)))
        banner[8:8 + th.shape[0], 20:20 + th.shape[1]] = th
    tx = 20 + int(bh * 0.76) + 16
    tag = "On time" if entry.status == "on_time" else f"Late +{entry.minutes_late} min"
    cv2.putText(banner, entry.name, (tx, int(34 * s)), FONT, 0.74 * s + 0.1, WHITE, 1, cv2.LINE_AA)
    cv2.putText(banner, f"Marked present  {fmt(entry.clock_s)}  {tag}", (tx, int(66 * s)), FONT, 0.5 * s + 0.1,
                color, 1, cv2.LINE_AA)
    paste(img, banner, x, y)


def grade(img, vignette):
    """Light cinematic grade: a touch of contrast and a soft vignette."""
    out = cv2.convertScaleAbs(img, alpha=1.06, beta=-6)
    return (out.astype(np.float32) * vignette[..., None]).astype(np.uint8)


def make_vignette(h, w, strength=0.28):
    yy, xx = np.mgrid[0:h, 0:w].astype(np.float32)
    d = np.sqrt(((xx - w / 2) / (w / 2)) ** 2 + ((yy - h / 2) / (h / 2)) ** 2) / math.sqrt(2)
    return 1.0 - strength * d ** 2


def top_bar(img, title, clock_text):
    H, W = img.shape[:2]
    chip(img, title, (24, 18), WHITE, scale=H / 1500 + 0.2)
    text = f"SITE CLOCK (demo)  {clock_text}"
    (tw, _), _ = cv2.getTextSize(text, FONT, H / 1500 + 0.1, 1)
    chip(img, text, (W - tw - 24 - 24, 18), GRAY, scale=H / 1500 + 0.1)


def caption(img):
    H, W = img.shape[:2]
    sc = H / 1500 + 0.1
    (tw, _), _ = cv2.getTextSize(CAPTION, FONT, sc, 1)
    chip(img, CAPTION, ((W - tw) // 2 - 7, H - int(H * 0.06)), AMBER, scale=sc)


def title_card(img, title, frame_idx, fps, seconds=1.4):
    """Dark opening that fades away over a centred title."""
    t = frame_idx / fps
    if t >= seconds:
        return
    a = 0.78 * (1 - ease_out(t / seconds)) if t > 0.5 else 0.78
    H, W = img.shape[:2]
    layer = np.zeros_like(img)
    cv2.addWeighted(layer, a, img, 1 - a, 0, img)
    sc = H / 700
    (tw, th), _ = cv2.getTextSize(title, FONT, sc, 2)
    txt = img.copy()
    cv2.putText(txt, title, ((W - tw) // 2, H // 2), FONT, sc, WHITE, 2, cv2.LINE_AA)
    k = 1.0 if t < 0.8 else max(0.0, 1 - (t - 0.8) / (seconds - 0.8))
    cv2.addWeighted(txt, k, img, 1 - k, 0, img)


def summary_card(img, register, total_seen, unknown, alpha):
    H, W = img.shape[:2]
    on = sum(1 for e in register.entries.values() if e.status == "on_time")
    lines = [f"{register.present} marked present", f"{on} on time    {register.present - on} late",
             f"{unknown} visitor(s) not enrolled"]
    layer = img.copy()
    cv2.rectangle(layer, (0, 0), (W, H), (0, 0, 0), -1)
    cv2.addWeighted(layer, 0.55 * alpha, img, 1 - 0.55 * alpha, 0, img)
    sc = H / 620
    y = H // 2 - int(60 * sc)
    for i, line in enumerate(lines):
        (tw, th), _ = cv2.getTextSize(line, FONT, sc * (1.15 if i == 0 else 0.8), 2)
        col = tuple(int(c * alpha) for c in (WHITE if i == 0 else GRAY))
        cv2.putText(img, line, ((W - tw) // 2, y), FONT, sc * (1.15 if i == 0 else 0.8), col, 2, cv2.LINE_AA)
        y += int(70 * sc)
