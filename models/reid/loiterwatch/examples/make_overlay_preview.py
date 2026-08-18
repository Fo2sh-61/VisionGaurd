"""Render a still preview of the live overlay (no camera needed)."""
from __future__ import annotations

import cv2
import numpy as np

from loiterwatch import Event, EventKind, Severity, load_config
from loiterwatch.live import Detection, Overlay

T0 = 1_770_000_000.0


def person(frame, x, y, h, shade=(150, 150, 160)):
    w = int(h * 0.38)
    cv2.circle(frame, (x + w // 2, y + int(h * 0.11)), int(h * 0.11), shade, -1)
    cv2.rectangle(frame, (x + int(w * 0.15), y + int(h * 0.22)),
                  (x + int(w * 0.85), y + int(h * 0.66)), shade, -1)
    cv2.rectangle(frame, (x + int(w * 0.22), y + int(h * 0.66)),
                  (x + int(w * 0.44), y + h), shade, -1)
    cv2.rectangle(frame, (x + int(w * 0.56), y + int(h * 0.66)),
                  (x + int(w * 0.78), y + h), shade, -1)
    return (x, y, x + w, y + h)


def scene():
    frame = np.full((520, 940, 3), 38, dtype=np.uint8)
    cv2.rectangle(frame, (0, 330), (940, 520), (52, 52, 56), -1)   # floor
    cv2.line(frame, (0, 330), (940, 330), (70, 70, 74), 2)
    for x in range(0, 940, 120):                                   # back wall panels
        cv2.line(frame, (x, 60), (x, 330), (46, 46, 50), 1)
    return frame


config = load_config("examples/live.yaml")
engine = config.engine()
cam = "cam_live"

frame = scene()
box_a = person(frame, 180, 150, 330)          # loitering
box_b = person(frame, 640, 190, 290, (140, 145, 150))   # just arrived

# track-A has been standing there 22s; track-B arrived 2s ago
for i in range(0, 221):
    engine.ingest(Event(ts=T0 + i * 0.1, kind=EventKind.OBSERVATION, zone=cam,
                        track_id="1", confidence=0.91))
for i in range(200, 221):
    engine.ingest(Event(ts=T0 + i * 0.1, kind=EventKind.OBSERVATION, zone=cam,
                        track_id="2", confidence=0.83))

now = T0 + 22.0
states = {a.track_id: a.severity for a in engine.alerts if a.track_id}
detections = [Detection("1", box_a, 0.91), Detection("2", box_b, 0.83)]
Overlay(cam).draw(frame, detections, engine, states, now, engine.alerts, 29.7)

cv2.imwrite("examples/overlay_preview.png", frame)
print(f"wrote examples/overlay_preview.png  ({len(engine.alerts)} alerts, states={states})")
