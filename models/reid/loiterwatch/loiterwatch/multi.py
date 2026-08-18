"""Several cameras in one process, sharing one identity pool and one rule engine.

The alternative -- one `live` process per camera, syncing through a JSON file --
still works and is right when the cameras are on different machines. In a single
process the sharing is simply better: identities are shared *instantly* rather
than every `poll_interval` seconds, there is no lock file, and one window shows
you every alert.

Each camera gets its own capture thread and its own YOLO model, because tracker
state is per-model and must not be shared. What *is* shared is the
IdentityStitcher, so a person recognised on one feed keeps their ID on the other.

Capture runs in threads that keep only the newest frame. For RTSP this is not
optional: cameras push frames at their own rate, and a loop that reads them in
order falls further behind real time on every slow detection pass, until the
"live" view is minutes stale.
"""
from __future__ import annotations

import json
import threading
import time
from dataclasses import dataclass, field
from typing import Any, Callable, Iterable, Sequence

from . import alarm
from .alerts import Alert, Severity
from .config import Config
from .engine import Engine
from .events import Event, EventKind
from .identity import IdentityStitcher
from .live import Detection, Overlay, handle_id_prompt, prompt_text


@dataclass
class CameraSpec:
    """One feed. `frame_source` bypasses capture entirely, for tests."""

    name: str
    source: object = 0
    detector: Any = None
    frame_source: Iterable | None = None


class _Grabber:
    """Background reader that keeps only the most recent frame."""

    def __init__(self, source: object, name: str) -> None:
        self.source = source
        self.name = name
        self._frame = None
        self._lock = threading.Lock()
        self._stop = threading.Event()
        self._thread: threading.Thread | None = None
        self.opened = False
        self.finished = False

    def start(self) -> bool:
        import cv2

        self._capture = cv2.VideoCapture(self.source)
        # a small buffer keeps latency down on network cameras
        try:
            self._capture.set(cv2.CAP_PROP_BUFFERSIZE, 1)
        except Exception:
            pass
        self.opened = self._capture.isOpened()
        if not self.opened:
            self.finished = True
            return False
        self._thread = threading.Thread(target=self._loop, daemon=True)
        self._thread.start()
        return True

    def _loop(self) -> None:
        while not self._stop.is_set():
            ok, frame = self._capture.read()
            if not ok:
                self.finished = True
                break
            with self._lock:
                self._frame = frame        # overwrite: old frames are useless

    def read(self):
        with self._lock:
            frame, self._frame = self._frame, None
            return frame

    def stop(self) -> None:
        self._stop.set()
        if self._thread is not None:
            self._thread.join(timeout=1.0)
        try:
            self._capture.release()
        except Exception:
            pass


class _IterGrabber:
    """Test double: pulls from an iterable instead of a camera."""

    def __init__(self, frames: Iterable) -> None:
        self._it = iter(frames)
        self.opened = True
        self.finished = False

    def start(self) -> bool:
        return True

    def read(self):
        try:
            return next(self._it)
        except StopIteration:
            self.finished = True
            return None

    def stop(self) -> None:
        pass


def run_multi(
    config: Config,
    cameras: Sequence[CameraSpec],
    stitcher: IdentityStitcher | None = None,
    window: bool = True,
    play_alarm: bool = True,
    show_timer: bool = False,
    log_path: str | None = None,
    identity_store: Any = None,
    clock: Callable[[], float] | None = None,
    max_frames: int | None = None,
    hold_on_exit: bool = True,
    debug_reid: bool = False,
) -> Engine:
    from .probe import quiet_ffmpeg, set_ffmpeg_timeouts

    # before the first VideoCapture: TCP transport for RTSP, and no decoder
    # chatter drowning the alerts
    quiet_ffmpeg()
    set_ffmpeg_timeouts(10.0)

    import cv2

    engine = config.engine()
    overlays = {c.name: Overlay(c.name, show_timer=show_timer) for c in cameras}
    states: dict[str, Severity] = {}
    relinked: dict[str, float] = {}
    recent: list[Alert] = []
    log_file = open(log_path, "a", encoding="utf-8") if log_path else None
    fps: dict[str, float] = {c.name: 0.0 for c in cameras}
    last_tick: dict[str, float] = {}
    last_frames: dict[str, Any] = {}

    grabbers: dict[str, Any] = {}
    for spec in cameras:
        if spec.frame_source is not None:
            grabbers[spec.name] = _IterGrabber(spec.frame_source)
        else:
            grabber = _Grabber(spec.source, spec.name)
            if grabber.start():
                print(f"[{spec.name}] opened {spec.source!r}", flush=True)
            else:
                print(f"[{spec.name}] FAILED to open {spec.source!r} -- "
                      f"continuing without it", flush=True)
            grabbers[spec.name] = grabber

    live_specs = [c for c in cameras if grabbers[c.name].opened]
    if not live_specs:
        raise SystemExit("no cameras could be opened")

    tick = clock or time.time
    now = tick()
    if identity_store is not None and stitcher is not None:
        adopted = identity_store.sync(stitcher, now=now, force=True)
        if adopted:
            print(f"identities: loaded {adopted} known people", flush=True)

    quit_requested = False
    #: None when idle, else "correct" (n) or "join" (j), plus the digits typed
    key_mode: str | None = None
    key_buffer = ""
    count = 0
    try:
        while True:
            if all(grabbers[c.name].finished for c in live_specs):
                break

            worked = False
            for spec in live_specs:
                frame = grabbers[spec.name].read()
                if frame is None:
                    continue
                worked = True
                now = tick()
                previous = last_tick.get(spec.name)
                if previous is not None and now > previous:
                    fps[spec.name] = 0.9 * fps[spec.name] + 0.1 / (now - previous)
                last_tick[spec.name] = now

                new_alerts = engine.advance(now)
                detections = spec.detector.detect(frame)

                if stitcher is not None:
                    # camera name namespaces the tracker IDs: every tracker
                    # numbers its own people from 1, so without this the two
                    # feeds' "track 1" would be treated as one person
                    before = set(stitcher.identities)
                    result = stitcher.update(frame, detections, now,
                                             camera=spec.name)
                    detections = result.detections
                    for stable, old_raw in result.relinked.items():
                        relinked[stable] = now
                        print(f"[{spec.name}] re-linked #{stable} "
                              f"(was tracker id {old_raw})", flush=True)
                    if debug_reid:
                        for new_id in set(stitcher.identities) - before:
                            best = stitcher.last_best
                            if best is None:
                                print(f"[{spec.name}] new #{new_id}: "
                                      f"nobody to compare against", flush=True)
                                continue
                            score, who = best
                            line = (f"[{spec.name}] new #{new_id}: closest was "
                                    f"#{who} at {score:.2f} (need "
                                    f"{stitcher.cross_min_similarity:.2f} "
                                    f"cross-camera)")
                            # the gap to the runner-up is what a cross-camera
                            # match is actually decided on, so print it: if it
                            # is routinely under --cross-margin, no threshold
                            # will separate these people and the descriptor is
                            # the thing to change
                            if stitcher.last_runner_up is not None:
                                second, other = stitcher.last_runner_up
                                line += (f"; runner-up #{other} at {second:.2f}"
                                         f" -- gap {score - second:.2f} vs "
                                         f"margin {stitcher.cross_margin:.2f}")
                            print(line, flush=True)
                        if stitcher.last_reject_reason:
                            print(f"[{spec.name}] {stitcher.last_reject_reason}",
                                  flush=True)

                for det in detections:
                    new_alerts += engine.ingest(Event(
                        ts=now, kind=EventKind.OBSERVATION, zone=spec.name,
                        track_id=det.track_id, confidence=det.confidence,
                    ))

                for alert in new_alerts:
                    if alert.track_id:
                        prev = states.get(alert.track_id)
                        if prev is None or alert.severity.rank > prev.rank:
                            states[alert.track_id] = alert.severity
                    recent.append(alert)
                    print(f"{alert.clock} [{alert.severity.value.upper()}] "
                          f"[{alert.zone}] {alert.rule_id}: {alert.message}",
                          flush=True)
                    if play_alarm:
                        alarm.play(alert.severity)
                    if log_file:
                        log_file.write(json.dumps(alert.to_dict()) + "\n")
                        log_file.flush()

                visible = {d.track_id for d in detections}
                for gone in [t for t in states
                             if t not in visible
                             and not any(t in engine.world.zone(c.name).active
                                         for c in live_specs)]:
                    del states[gone]

                overlays[spec.name].draw(
                    frame, detections, engine, states, now, recent,
                    fps[spec.name], relinked,
                    stitcher.merges if stitcher else 0,
                    None if key_mode is None
                    else prompt_text(key_mode, key_buffer),
                )
                last_frames[spec.name] = frame

                if window:
                    cv2.imshow(f"loiterwatch - {spec.name}", frame)

                count += 1
                if max_frames is not None and count >= max_frames:
                    quit_requested = True
                    break

            if quit_requested:
                break

            if identity_store is not None and stitcher is not None:
                identity_store.sync(stitcher, now)

            if window:
                key = cv2.waitKey(1) & 0xFF

                if key_mode is not None:
                    key_mode, key_buffer = handle_id_prompt(
                        key, key_mode, key_buffer, stitcher, now)
                    continue

                if key in (ord("q"), 27):
                    quit_requested = True
                    break
                if key == ord("s"):
                    for name, frame in last_frames.items():
                        path = f"snapshot_{name}_{int(now)}.jpg"
                        cv2.imwrite(path, frame)
                        print(f"saved {path}", flush=True)
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
            elif not worked:
                time.sleep(0.005)   # nothing ready; do not spin the CPU
    finally:
        for grabber in grabbers.values():
            grabber.stop()
        if log_file:
            log_file.close()
        if identity_store is not None and stitcher is not None:
            identity_store.sync(stitcher, now=now, force=True)
        if window and hold_on_exit and not quit_requested and last_frames:
            for name, frame in last_frames.items():
                cv2.rectangle(frame, (0, frame.shape[0] - 40),
                              (frame.shape[1], frame.shape[0]), (28, 28, 28), -1)
                cv2.putText(frame, "session ended -- press any key to close",
                            (10, frame.shape[0] - 14), cv2.FONT_HERSHEY_SIMPLEX,
                            0.6, (240, 240, 240), 1, cv2.LINE_AA)
                cv2.imshow(f"loiterwatch - {name}", frame)
            cv2.waitKey(0)
        if window:
            cv2.destroyAllWindows()
    return engine


def parse_camera_arg(value: str) -> tuple[str, object]:
    """`name=source`, or a bare source that gets an auto-generated name."""
    if "=" in value:
        name, source = value.split("=", 1)
        name, source = name.strip(), source.strip()
    else:
        name, source = "", value.strip()
    if not name:
        name = f"cam_{source}" if str(source).isdigit() else "cam"
    return name, int(source) if str(source).isdigit() else source
