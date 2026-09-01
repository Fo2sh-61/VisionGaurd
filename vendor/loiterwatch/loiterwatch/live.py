"""Live camera viewer: boxes, a dwell clock above each person, and alerts.

Detection and tracking are deliberately behind the `Detector` interface so the
overlay and engine wiring can be tested without a camera or a GPU.
"""
from __future__ import annotations

import json
import time
from dataclasses import dataclass
from datetime import datetime
from typing import TYPE_CHECKING, Callable, Iterable, Protocol, Sequence

from . import alarm
from .alerts import Alert, Severity
from .config import Config
from .engine import Engine
from .events import Event, EventKind
from .identity import IdentityStitcher
from .rules.dwell import DwellRule

if TYPE_CHECKING:
    from .shared_identity import SharedIdentityStore

# BGR, because OpenCV
COLOR_OK = (150, 220, 150)
COLOR_SOON = (60, 190, 255)
COLOR_WARNING = (0, 190, 255)
COLOR_CRITICAL = (60, 60, 255)
COLOR_HUD = (240, 240, 240)
COLOR_PANEL = (28, 28, 28)


@dataclass
class Detection:
    track_id: str
    box: tuple[int, int, int, int]  # x1, y1, x2, y2
    confidence: float


class Detector(Protocol):
    def detect(self, frame) -> Sequence[Detection]: ...


class YoloDetector:
    """Ultralytics YOLO + ByteTrack. Track IDs come from the tracker, and the
    dwell clock is only as stable as those IDs are."""

    def __init__(self, weights: str = "yolov8n.pt", conf: float = 0.4,
                 imgsz: int = 640, device: str | None = None,
                 tracker: str = "bytetrack.yaml") -> None:
        try:
            from ultralytics import YOLO
        except ImportError as exc:  # pragma: no cover - environment dependent
            raise SystemExit(
                "ultralytics is not installed.\n"
                "  pip install ultralytics opencv-python\n"
                "(the first run downloads yolov8n.pt automatically)"
            ) from exc
        self.model = YOLO(weights)
        self.conf = conf
        self.imgsz = imgsz
        self.device = device
        self.tracker = tracker

    def detect(self, frame) -> list[Detection]:
        results = self.model.track(
            frame, persist=True, classes=[0], conf=self.conf, imgsz=self.imgsz,
            tracker=self.tracker, verbose=False, device=self.device,
        )
        out: list[Detection] = []
        if not results:
            return out
        boxes = results[0].boxes
        if boxes is None or boxes.id is None:
            return out  # detections without IDs are useless to a temporal rule
        for box, track_id, conf in zip(
            boxes.xyxy.cpu().numpy(), boxes.id.cpu().numpy(), boxes.conf.cpu().numpy()
        ):
            x1, y1, x2, y2 = (int(v) for v in box[:4])
            out.append(Detection(str(int(track_id)), (x1, y1, x2, y2), float(conf)))
        return out


# --------------------------------------------------------------------------
def fmt_clock(seconds: float) -> str:
    seconds = max(0, int(seconds))
    m, s = divmod(seconds, 60)
    h, m = divmod(m, 60)
    return f"{h}:{m:02d}:{s:02d}" if h else f"{m}:{s:02d}"


def prompt_text(mode: str, buffer: str) -> str:
    """What the on-screen prompt says while an ID is being typed."""
    if mode == "join":
        return f"same person:  {buffer or '_'}   [Enter] merge  [Esc] cancel"
    return f"wrong ID?  #p{buffer}_   [Enter] fix  [Esc] cancel"


def handle_id_prompt(key: int, mode: str, buffer: str, stitcher, now: float):
    """Collect digits for the `n` (correct) and `j` (join) keys.

    Returns the next (mode, buffer); mode is None once the prompt is finished.
    Shared by the single- and multi-camera loops so the two cannot drift apart.
    """
    if key in (13, 10):                                   # Enter
        numbers = [n for n in buffer.split() if n]
        if stitcher is None:
            print("no identity tracking active", flush=True)
        elif mode == "join":
            if len(numbers) != 2:
                print("join needs two IDs, e.g. '3 7'", flush=True)
            else:
                a, b = (f"p{n}" for n in numbers)
                kept = stitcher.merge(a, b, now)
                if kept is None:
                    print(f"could not merge #{a} and #{b} -- "
                          f"check both IDs exist", flush=True)
                else:
                    print(f"merged #{a} + #{b} -> #{kept}", flush=True)
                    for pair, offset in stitcher.pair_offsets.items():
                        print(f"   learned: cameras {sorted(pair)} need "
                              f"{offset:.2f} more slack", flush=True)
        else:
            if not numbers:
                print("correction cancelled (no ID typed)", flush=True)
            else:
                target = f"p{numbers[0]}"
                new_id = stitcher.correct(target, now)
                if new_id is None:
                    print(f"#{target} is not on screen right now", flush=True)
                else:
                    print(f"corrected: #{target} -> #{new_id}; they will "
                          f"never be merged again", flush=True)
        return None, ""
    if key == 27:                                          # Esc
        print("cancelled", flush=True)
        return None, ""
    if key in (8, 127):                                    # Backspace
        return mode, buffer[:-1]
    if 0x30 <= key <= 0x39:                                # 0-9
        return mode, buffer + chr(key)
    if key == 32 and mode == "join":                       # space separator
        return mode, buffer + " "
    return mode, buffer


def next_threshold(rules: Iterable, zone: str, dwell: float, now: float) -> float | None:
    """The soonest threshold this person is heading toward, for the countdown."""
    candidates: list[float] = []
    for rule in rules:
        if not isinstance(rule, DwellRule) or not rule.enabled:
            continue
        if not rule.in_schedule(now):
            continue
        if rule.zones and zone not in rule.zones:
            continue
        for after_s, _sev, _tpl in rule.levels:
            if after_s > dwell:
                candidates.append(after_s)
                break
    return min(candidates) if candidates else None


class Overlay:
    """Draws everything on top of the frame. Pure rendering, no state."""

    def __init__(self, camera: str, show_ids: bool = True,
                 show_timer: bool = False) -> None:
        self.camera = camera
        self.show_ids = show_ids
        #: the dwell clock is off by default -- the label stays a bare ID, and
        #: alert state is carried by colour instead of numbers
        self.show_timer = show_timer

    def draw(self, frame, detections, engine: Engine, states, now: float,
             recent: Sequence[Alert], fps: float,
             relinked: dict[str, float] | None = None, merges: int = 0,
             correcting: str | None = None):
        import cv2

        zone = engine.world.zone(self.camera)
        height, width = frame.shape[:2]
        worst = Severity.INFO
        any_alert = False

        for det in detections:
            x1, y1, x2, y2 = det.box
            visit = zone.active.get(det.track_id)
            dwell = visit.dwell(now) if visit else 0.0
            severity = states.get(det.track_id)
            target = next_threshold(engine.rules, self.camera, dwell, now)

            if severity is Severity.CRITICAL:
                color, any_alert = COLOR_CRITICAL, True
                worst = Severity.CRITICAL
            elif severity is not None:
                color, any_alert = COLOR_WARNING, True
                worst = max(worst, severity, key=lambda s: s.rank)
            elif target and dwell >= target * 0.5:
                color = COLOR_SOON
            else:
                color = COLOR_OK

            thickness = 3 if severity is not None else 2
            cv2.rectangle(frame, (x1, y1), (x2, y2), color, thickness)

            # --- the label, sitting just above the box ---------------------
            parts = []
            if self.show_ids:
                parts.append(f"#{det.track_id}")
            if self.show_timer:
                clock = fmt_clock(dwell)
                if target is not None:
                    clock += f" / {fmt_clock(target)}"
                parts.append(clock)
            if relinked and now - relinked.get(det.track_id, -1e9) < 3.0:
                parts.append("RE-ID")   # identity carried over from an earlier visit
            label = "  ".join(parts) or " "

            font, scale, ftk = cv2.FONT_HERSHEY_SIMPLEX, 0.62, 2
            (tw, th), _ = cv2.getTextSize(label, font, scale, ftk)
            pad = 6
            bar_h = 5 if (self.show_timer and target) else 0
            box_h = th + pad * 2 + bar_h
            by2 = max(box_h, y1 - 4)          # flip below the top edge if needed
            by1 = by2 - box_h
            bx1 = min(x1, width - (tw + pad * 2) - 2)
            bx2 = bx1 + tw + pad * 2
            cv2.rectangle(frame, (bx1, by1), (bx2, by2), color, -1)
            cv2.putText(frame, label, (bx1 + pad, by2 - pad - bar_h), font, scale,
                        (20, 20, 20), ftk, cv2.LINE_AA)

            # --- progress toward the next threshold, along the label edge ---
            if bar_h and target and target > 0:
                frac = min(1.0, dwell / target)
                cv2.rectangle(frame, (bx1, by2 - bar_h), (bx2, by2), (35, 35, 35), -1)
                cv2.rectangle(frame, (bx1, by2 - bar_h),
                              (bx1 + int((bx2 - bx1) * frac), by2), (250, 250, 250), -1)

            if severity is not None:
                tag = "LOITERING" if severity is Severity.CRITICAL else "WATCH"
                # inside the box, so it never collides with the alert log
                cv2.putText(frame, tag, (x1 + 6, max(by2 + 20, y2 - 10)),
                            font, 0.58, color, 2, cv2.LINE_AA)

        self._hud(frame, len(detections), now, fps, any_alert, worst, recent,
                  merges, correcting)
        return frame

    def _hud(self, frame, count, now, fps, any_alert, worst, recent, merges=0,
             correcting=None):
        import cv2

        height, width = frame.shape[:2]
        font = cv2.FONT_HERSHEY_SIMPLEX
        cv2.rectangle(frame, (0, 0), (width, 34), COLOR_PANEL, -1)
        stamp = datetime.fromtimestamp(now).strftime("%H:%M:%S")
        text = f"{self.camera}  {stamp}   people: {count}   {fps:4.1f} fps"
        if merges:
            text += f"   re-links: {merges}"
        cv2.putText(frame, text, (10, 23), font, 0.6, COLOR_HUD, 1, cv2.LINE_AA)

        if any_alert:
            edge = COLOR_CRITICAL if worst is Severity.CRITICAL else COLOR_WARNING
            cv2.rectangle(frame, (2, 2), (width - 3, height - 3), edge, 4)

        if correcting is not None:
            prompt = correcting
            (tw, th), _ = cv2.getTextSize(prompt, font, 0.7, 2)
            x, y = (width - tw) // 2, height // 2
            cv2.rectangle(frame, (x - 14, y - th - 14), (x + tw + 14, y + 14),
                          (20, 20, 20), -1)
            cv2.rectangle(frame, (x - 14, y - th - 14), (x + tw + 14, y + 14),
                          COLOR_SOON, 2)
            cv2.putText(frame, prompt, (x, y), font, 0.7, COLOR_SOON, 2,
                        cv2.LINE_AA)

        for i, alert in enumerate(list(recent)[-3:][::-1]):
            y = height - 12 - i * 20
            color = COLOR_CRITICAL if alert.severity is Severity.CRITICAL else COLOR_WARNING
            # local time here, matching the HUD clock -- operators read wall time
            stamp = datetime.fromtimestamp(alert.ts).strftime("%H:%M:%S")
            text = f"{stamp}  {alert.rule_id}  #{alert.track_id}"
            cv2.putText(frame, text, (10, y), font, 0.5, color, 1, cv2.LINE_AA)


def run(
    config: Config,
    detector: Detector,
    source: object = 0,
    camera: str = "cam_live",
    window: bool = True,
    log_path: str | None = None,
    record_path: str | None = None,
    max_frames: int | None = None,
    frame_source: Iterable | None = None,
    clock: Callable[[], float] | None = None,
    stitcher: "IdentityStitcher | None" = None,
    play_alarm: bool = True,
    hold_on_exit: bool = True,
    show_timer: bool = False,
    identity_store: "SharedIdentityStore | None" = None,
    debug_reid: bool = False,
) -> Engine:
    """Main loop.

    `frame_source` lets tests drive it without a camera. `clock` overrides wall
    time -- pass a frame-count-derived clock when processing a recorded file, or
    the timings will reflect how fast your machine decoded it rather than what
    actually happened. `hold_on_exit` keeps the window open (waiting for a
    keypress) when the source runs out on its own, so the feed does not vanish
    the instant a video file ends or a camera disconnects -- only an explicit
    `q`/`Esc` closes it immediately. `identity_store`, if given, keeps this
    camera's identities synced with other `live` processes pointed at the same
    file -- see shared_identity.SharedIdentityStore.
    """
    from .probe import quiet_ffmpeg, set_ffmpeg_timeouts

    # before the first VideoCapture: TCP transport for RTSP, and no decoder
    # chatter drowning the alerts
    quiet_ffmpeg()
    set_ffmpeg_timeouts(10.0)

    import cv2

    engine = config.engine()
    overlay = Overlay(camera, show_timer=show_timer)
    states: dict[str, Severity] = {}
    relinked: dict[str, float] = {}
    recent: list[Alert] = []
    log_file = open(log_path, "a", encoding="utf-8") if log_path else None
    writer = None
    capture = None
    last_frame = None
    quit_requested = False
    #: None when idle, else "correct" (n) or "join" (j), plus the digits typed
    key_mode: str | None = None
    key_buffer = ""

    def frames():
        nonlocal capture
        if frame_source is not None:
            yield from frame_source
            return
        capture = cv2.VideoCapture(source)
        if not capture.isOpened():
            raise SystemExit(f"could not open video source {source!r}")
        while True:
            ok, frame = capture.read()
            if not ok:
                break
            yield frame

    tick = clock or time.time
    fps, last = 0.0, tick()
    last_now = last
    count = 0

    if identity_store is not None and stitcher is not None:
        adopted = identity_store.sync(stitcher, now=last, force=True)
        if adopted:
            print(f"identities: loaded {adopted} known people from other cameras",
                  flush=True)

    try:
        for frame in frames():
            now = tick()
            last_now = now
            dt = now - last
            fps = 0.9 * fps + 0.1 / dt if dt > 0 else fps
            last = now

            new_alerts = engine.advance(now)
            detections = detector.detect(frame)
            if stitcher is not None:
                # remap tracker IDs to stable identities BEFORE the engine sees
                # them, so a re-entry continues the same visit
                before = set(stitcher.identities)
                result = stitcher.update(frame, detections, now, camera=camera)
                detections = result.detections
                for stable, old_raw in result.relinked.items():
                    relinked[stable] = now
                    print(f"re-linked #{stable} (was tracker id {old_raw})", flush=True)
                if debug_reid:
                    for new_id in set(stitcher.identities) - before:
                        best = stitcher.last_best
                        why = stitcher.last_reject_reason or ""
                        quality = stitcher.last_quality
                        known = len(stitcher.identities) - 1
                        if quality is not None and quality < stitcher.quality_floor:
                            # never even described, so no match was possible
                            print(f"new #{new_id}: crop quality {quality:.2f} "
                                  f"below floor {stitcher.quality_floor:.2f} -- "
                                  f"not identified at all", flush=True)
                        elif quality is not None and quality < stitcher.min_quality:
                            need = stitcher.min_similarity + stitcher.low_quality_penalty
                            got = f"{stitcher.last_best[0]:.2f}" if stitcher.last_best else "none"
                            print(f"new #{new_id}: weak crop (quality "
                                  f"{quality:.2f}), needed {need:.2f} to match, "
                                  f"best was {got}", flush=True)
                        elif best is None:
                            print(f"new #{new_id}: no comparable candidate "
                                  f"({known} known, quality "
                                  f"{quality if quality is None else round(quality, 2)})",
                                  flush=True)
                        else:
                            score, who = best
                            rival = ""
                            if stitcher.last_runner_up is not None:
                                second, other = stitcher.last_runner_up
                                rival = (f", runner-up #{other} {second:.2f} "
                                         f"(gap {score - second:.2f})")
                            print(f"new #{new_id}: closest #{who} at {score:.2f} "
                                  f"(need {stitcher.min_similarity:.2f}, quality "
                                  f"{quality:.2f}){rival}"
                                  + (f" -- {why}" if why and "no candidate" not in why
                                     else ""),
                                  flush=True)
                if identity_store is not None:
                    adopted = identity_store.sync(stitcher, now)
                    if adopted:
                        print(f"identities: adopted {adopted} from other cameras",
                              flush=True)
            for det in detections:
                new_alerts += engine.ingest(Event(
                    ts=now, kind=EventKind.OBSERVATION, zone=camera,
                    track_id=det.track_id, confidence=det.confidence,
                ))

            for alert in new_alerts:
                if alert.track_id:
                    prev = states.get(alert.track_id)
                    if prev is None or alert.severity.rank > prev.rank:
                        states[alert.track_id] = alert.severity
                recent.append(alert)
                print(f"{alert.clock} [{alert.severity.value.upper()}] "
                      f"{alert.rule_id}: {alert.message}", flush=True)
                if play_alarm:
                    alarm.play(alert.severity)
                if log_file:
                    log_file.write(json.dumps(alert.to_dict()) + "\n")
                    log_file.flush()

            live_ids = {d.track_id for d in detections}
            for gone in [t for t in states if t not in live_ids
                         and t not in engine.world.zone(camera).active]:
                del states[gone]

            overlay.draw(frame, detections, engine, states, now, recent, fps,
                         relinked, stitcher.merges if stitcher else 0,
                         None if key_mode is None
                         else prompt_text(key_mode, key_buffer))

            if record_path:
                if writer is None:
                    h, w = frame.shape[:2]
                    writer = cv2.VideoWriter(
                        record_path, cv2.VideoWriter_fourcc(*"mp4v"), 20.0, (w, h))
                writer.write(frame)

            if window:
                last_frame = frame
                cv2.imshow("loiterwatch", frame)
                key = cv2.waitKey(1) & 0xFF

                if key_mode is not None:
                    key_mode, key_buffer = handle_id_prompt(
                        key, key_mode, key_buffer, stitcher, now)
                    count += 1
                    if max_frames is not None and count >= max_frames:
                        break
                    continue

                if key in (ord("q"), 27):
                    quit_requested = True
                    break
                if key == ord("s"):
                    name = f"snapshot_{int(now)}.jpg"
                    cv2.imwrite(name, frame)
                    print(f"saved {name}", flush=True)
                if key == ord("m"):
                    play_alarm = not play_alarm
                    print(f"alarm {'on' if play_alarm else 'muted'}", flush=True)
                if key == ord("n") and stitcher is not None:
                    key_mode, key_buffer = "correct", ""
                    print("wrong ID: type the number, then Enter (Esc cancels)",
                          flush=True)
                if key == ord("j") and stitcher is not None:
                    key_mode, key_buffer = "join", ""
                    print("same person: type both numbers separated by a space, "
                          "then Enter (Esc cancels)", flush=True)

            count += 1
            if max_frames is not None and count >= max_frames:
                break
    finally:
        if capture is not None:
            capture.release()
        if writer is not None:
            writer.release()
        if log_file:
            log_file.close()
        if identity_store is not None and stitcher is not None:
            identity_store.sync(stitcher, now=last_now, force=True)
        if window and hold_on_exit and not quit_requested and last_frame is not None:
            # the source ran out on its own (video end, camera unplugged) --
            # do not make the feed vanish, wait for the person to dismiss it
            msg = "session ended -- press any key to close"
            cv2.rectangle(last_frame, (0, last_frame.shape[0] - 40),
                          (last_frame.shape[1], last_frame.shape[0]), (28, 28, 28), -1)
            cv2.putText(last_frame, msg, (10, last_frame.shape[0] - 14),
                        cv2.FONT_HERSHEY_SIMPLEX, 0.6, (240, 240, 240), 1, cv2.LINE_AA)
            cv2.imshow("loiterwatch", last_frame)
            cv2.waitKey(0)
        if window:
            cv2.destroyAllWindows()
    return engine
