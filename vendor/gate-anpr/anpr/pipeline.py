"""
Per-camera worker: read frames -> detect plate -> read -> vote -> log event.

One CameraWorker thread per camera. Each worker knows its own gate number and
direction (entry/exit), which is what makes multi-camera, multi-gate setups
work: the camera config carries the meaning, the pipeline just records it.
"""

from __future__ import annotations

import logging
import threading
import time
from dataclasses import dataclass
from pathlib import Path

import cv2
import numpy as np

from . import db, plate_text
from .capture import open_capture
from .config import CameraConfig, SystemConfig, SNAPSHOT_DIR, DATASET_DIR, ROOT
from .detector import PlateDetector, PlateBox
from .ocr import PlateReader
from .tracker import PlateTracker, vote_weight

log = logging.getLogger(__name__)

# Absolute floor: below this a plate cannot carry readable characters at any
# resolution, so it is noise rather than a distant vehicle. Not a tuning knob.
MIN_USABLE_PX = 24

# Purely a colour hint on the live picture, to help aim a camera during
# installation. It is NOT a threshold: plates below it are still detected and
# still read, they just carry less weight in the vote.
COMFORTABLE_PX = 100

STATUS_AR = {
    "known": "مسجلة",
    "unknown": "غير مسجلة",
    "blacklist": "محظورة",
    "expired": "تصريح منتهي",
}


@dataclass
class Passage:
    """A confirmed vehicle passage, ready to be written to the database."""

    plate: str
    camera_id: str
    gate_number: int
    direction: str
    confidence: float
    ocr_confidence: float
    plausibility: float
    votes: int
    snapshot: str | None = None
    plate_crop: str | None = None
    low_confidence: bool = False


class CameraWorker(threading.Thread):
    def __init__(self, cam: CameraConfig, cfg: SystemConfig,
                 detector: PlateDetector | None = None,
                 reader: PlateReader | None = None,
                 stop_event: threading.Event | None = None) -> None:
        super().__init__(name=f"cam-{cam.id}", daemon=True)
        self.cam = cam
        self.cfg = cfg
        rc = cfg.recognition
        self.detector = detector or PlateDetector(
            rc.detector_backend, str(ROOT / rc.plate_detector_weights),
            rc.min_detect_conf, rc.device)
        self.reader = reader or PlateReader(
            rc.ocr_backend, str(ROOT / rc.char_detector_weights), rc.device)
        self.tracker = PlateTracker(min_votes=rc.min_votes)
        self.stop_event = stop_event or threading.Event()
        self.frames = 0
        self.fps = 0.0
        self._collected_today = 0
        self._collect_day = ""
        self._read_error_logged = False
        self._ocr_cost = 0.0
        # Rolling window of what the reader actually returned, confirmed or
        # not. Without this, "the box is drawn but nothing is logged" is
        # impossible to diagnose from the outside — you cannot tell whether the
        # reader produced nothing, or produced a different answer each frame.
        self.attempts: list[dict] = []
        self._live_lock = threading.Lock()
        self._live_jpeg: bytes | None = None
        self._last_boxes: list = []

    # -- main loop ---------------------------------------------------------

    def run(self) -> None:  # pragma: no cover - needs a live camera
        conn = db.connect()
        while not self.stop_event.is_set():
            cap = self._open()
            if cap is None:
                db.set_camera_status(conn, self.cam.id, False,
                                     error="cannot open source")
                if self.stop_event.wait(self.cam.reconnect_seconds):
                    break
                continue
            db.set_camera_status(conn, self.cam.id, True)
            interval = 1.0 / max(self.cam.fps_limit, 0.5)
            last, t0, count = 0.0, time.time(), 0
            try:
                while not self.stop_event.is_set():
                    ok, frame = cap.read()
                    if not ok or frame is None:
                        log.warning("[%s] stream ended, reconnecting", self.cam.id)
                        break
                    now = time.time()
                    if now - last < interval:
                        continue
                    last = now
                    self.process_frame(frame, conn=conn, now=now)
                    count += 1
                    if now - t0 >= 5:
                        self.fps = round(count / (now - t0), 2)
                        db.set_camera_status(conn, self.cam.id, True, self.fps)
                        t0, count = now, 0
            except Exception as exc:
                log.exception("[%s] worker error: %s", self.cam.id, exc)
                db.set_camera_status(conn, self.cam.id, False, error=str(exc))
            finally:
                cap.release()
                self.tracker.reset()
            if self.stop_event.wait(self.cam.reconnect_seconds):
                break
        db.set_camera_status(conn, self.cam.id, False)

    def _open(self):  # pragma: no cover
        cap = open_capture(self.cam.source,
                           width=getattr(self.cam, "capture_width", 0),
                           height=getattr(self.cam, "capture_height", 0))
        if cap is None:
            log.error("[%s] cannot open %s", self.cam.id, self.cam.source)
            return None
        # Report what the driver actually gave us. A camera that quietly stays
        # at 640x480 after being asked for 720p is the difference between
        # reading a plate at 3m and never reading one, and it is invisible
        # otherwise.
        try:
            w = int(cap.get(cv2.CAP_PROP_FRAME_WIDTH))
            h = int(cap.get(cv2.CAP_PROP_FRAME_HEIGHT))
            if w and h:
                log.info("[%s] capturing at %dx%d", self.cam.id, w, h)
        except Exception:
            pass
        return cap

    # -- per frame ---------------------------------------------------------

    def process_frame(self, frame: np.ndarray, conn=None, now: float | None = None
                      ) -> list[Passage]:
        """Detect, read and vote on one frame. Returns any confirmed passages."""
        conn = conn if conn is not None else db.connect()
        now = now if now is not None else time.time()
        self.frames += 1

        frame = self._prepare(frame)
        roi_frame, ox, oy = self._apply_roi(frame)
        boxes = self._detect(roi_frame)

        shifted = [PlateBox(b.x1 + ox, b.y1 + oy, b.x2 + ox, b.y2 + oy, b.conf)
                   for b in boxes]

        pairs = self.tracker.update(shifted, now)

        # The detector deliberately proposes a plate AND its halves, and a car
        # body sometimes passes the shape filter too. Picking "the right" box
        # from those is guesswork — the body is bigger than the plate, but the
        # plate is bigger than its own halves, so no size rule separates them.
        # Bounding the spend is reliable where choosing is not: read the
        # biggest unread candidates first, at most a few per frame.
        budget = self._read_budget()
        pairs.sort(key=lambda tb: tb[1].area, reverse=True)

        for track, box in pairs:
            crop = box.crop(frame)

            # Always keep the sharpest view, even on frames we do not read:
            # it costs nothing and it is what gets saved and shown.
            sharp = _sharpness(crop) * (box.w / max(frame.shape[1], 1))
            if sharp > track.best_crop_score:
                track.best_crop_score = sharp
                track.best_crop = crop.copy()
                track.best_frame = frame.copy()

            if budget <= 0 or not self._should_read(track, box, now):
                continue
            budget -= 1

            # A reader failure on one crop must not take the gate down. Log it
            # once per camera and keep going: a stopped camera is a far worse
            # outcome than a missed plate.
            t0 = time.time()
            try:
                res = self.reader.read(crop, context=frame)
            except Exception as exc:
                if not self._read_error_logged:
                    log.exception("[%s] reader failed on a frame: %s",
                                  self.cam.id, exc)
                    self._read_error_logged = True
                continue
            finally:
                self._note_ocr_cost(time.time() - t0)
                track.last_ocr_at = now
                track.last_ocr_area = box.area
                track.ocr_count += 1

            if res.text:
                w = vote_weight(res.confidence, res.plausibility, box.w,
                                frame.shape[1])
                track.add_vote(res.text, w)
            leader, _, votes = track.leader()
            self._note_attempt(res, box, leader, votes)
            if not res.text:
                continue

        self._publish_live(frame, shifted)

        out: list[Passage] = []
        for track in self.tracker.confirmed():
            p = self._emit(track, conn)
            if p:
                out.append(p)

        # A car that has left the frame gets one last chance. Anything emitted
        # here failed to reach the vote threshold, so it is forced to
        # low-confidence and lands in the review queue rather than being
        # treated as a settled identification.
        gone = self.tracker.expired()
        for track in self.tracker.unreported_leftovers(gone):
            p = self._emit(track, conn, force_low=True)
            if p:
                out.append(p)
        return out

    # -- live view ----------------------------------------------------------

    def _publish_live(self, frame: np.ndarray, boxes: list) -> None:
        """Keep the newest annotated frame ready for the dashboard."""
        if not getattr(self.cfg, "live_view", True):
            return
        try:
            view = frame.copy()
            for b in boxes:
                good = b.w >= COMFORTABLE_PX
                colour = (0, 200, 0) if good else (0, 165, 255)
                cv2.rectangle(view, (b.x1, b.y1), (b.x2, b.y2), colour, 2)
                cv2.putText(view, f"{b.w}px", (b.x1, max(b.y1 - 6, 12)),
                            cv2.FONT_HERSHEY_SIMPLEX, 0.5, colour, 2,
                            cv2.LINE_AA)
            x1f, y1f, x2f, y2f = self.cam.roi
            if (x1f, y1f, x2f, y2f) != (0.0, 0.0, 1.0, 1.0):
                h, w = view.shape[:2]
                cv2.rectangle(view, (int(x1f * w), int(y1f * h)),
                              (int(x2f * w), int(y2f * h)), (90, 90, 90), 1)
            target = getattr(self.cfg, "live_view_width", 900)
            if view.shape[1] > target:
                scale = target / view.shape[1]
                view = cv2.resize(view, (target, int(view.shape[0] * scale)),
                                  interpolation=cv2.INTER_AREA)
            ok, buf = cv2.imencode(".jpg", view,
                                   [cv2.IMWRITE_JPEG_QUALITY, 72])
            if ok:
                with self._live_lock:
                    self._live_jpeg = buf.tobytes()
        except Exception:
            pass          # the live view must never affect recognition

    def latest_jpeg(self) -> bytes | None:
        with self._live_lock:
            return self._live_jpeg

    # -- detection and recognition budget -----------------------------------

    def _detect(self, roi_frame: np.ndarray) -> list:
        """
        Find plates, with a second look for distant ones.

        There is no user-set minimum plate width any more. A hard cut-off threw
        away exactly the far-away plates the operator wants to catch, and the
        right number depends on lens, distance and mounting height — nobody can
        guess it correctly. Size now only weights the vote, so a small plate
        contributes less rather than being discarded.

        When nothing is found at native size, the frame is retried upscaled.
        That costs nothing on the frames that already found a plate, and adds
        real range on the ones that did not.
        """
        boxes = [b for b in self.detector.detect(roi_frame) if b.w >= MIN_USABLE_PX]
        if boxes or roi_frame is None or roi_frame.size == 0:
            return boxes

        h, w = roi_frame.shape[:2]
        if w >= 2200:                 # already high-res; upscaling adds nothing
            return boxes
        up = cv2.resize(roi_frame, (w * 2, h * 2), interpolation=cv2.INTER_CUBIC)
        found = self.detector.detect(up)
        return [PlateBox(b.x1 // 2, b.y1 // 2, b.x2 // 2, b.y2 // 2, b.conf)
                for b in found if b.w // 2 >= MIN_USABLE_PX]

    def _note_attempt(self, res, box, leader: str, votes: int) -> None:
        """Record one recognition attempt for the diagnostics panel."""
        self.attempts.insert(0, {
            "at": db.now_local().strftime("%H:%M:%S"),
            "raw": res.text or "",
            "display": plate_text.display(res.text) if res.text else "",
            "conf": round(res.confidence, 2),
            "plausible": round(res.plausibility, 2) if res.text else 0.0,
            "width_px": box.w,
            "leader": plate_text.display(leader) if leader else "",
            "votes": votes,
            "needed": self.cfg.recognition.min_votes,
        })
        del self.attempts[40:]

    def _read_budget(self) -> int:
        """
        How many recognitions this frame may spend.

        Measured, not configured. A fast reader (a trained character model)
        can afford several boxes per frame; easyocr on a CPU takes ~0.3s and
        must be held to one, or the capture loop falls behind the traffic and
        cars pass unrecorded. This is what "optimum" means here — the system
        measures its own reader and adapts.
        """
        if self._ocr_cost <= 0.0:
            return 3                       # unknown yet: let it measure
        if self._ocr_cost > 0.15:
            return 1
        if self._ocr_cost > 0.05:
            return 2
        return 4

    def _note_ocr_cost(self, seconds: float) -> None:
        """Rolling average of how long one recognition actually takes."""
        self._ocr_cost = (0.8 * self._ocr_cost + 0.2 * seconds
                          if self._ocr_cost else seconds)

    def _should_read(self, track, box, now: float) -> bool:
        """
        Decide whether this plate is worth spending a recognition on.

        Reading every detected box on every frame is what made the system slow:
        the capture loop ran at the speed of the OCR engine, so a 0.5s reader
        capped the whole camera at 2 fps and cars were missed. Detection is
        cheap, recognition is not — so detect always, recognise selectively.

        A track is read when it is new, when the plate has grown meaningfully
        closer (a better view than the one already spent), or after a pause
        scaled to how slow the reader actually is. Once enough frames agree,
        reading stops entirely.
        """
        if track.reported:
            return False
        if track.ocr_count == 0:
            return True                       # first sight of this vehicle
        _, _, votes = track.leader()
        if votes >= self.cfg.recognition.min_votes:
            return False                      # already decided
        # Self-tuning: never queue reads faster than the reader can serve them.
        interval = max(0.05, min(self._ocr_cost * 1.2, 1.0))
        elapsed = now - track.last_ocr_at
        if elapsed < interval:
            return False
        grew = box.area >= track.last_ocr_area * 1.15
        return grew or elapsed >= interval * 2

    def _prepare(self, frame: np.ndarray) -> np.ndarray:
        if self.cam.rotate == 90:
            return cv2.rotate(frame, cv2.ROTATE_90_CLOCKWISE)
        if self.cam.rotate == 180:
            return cv2.rotate(frame, cv2.ROTATE_180)
        if self.cam.rotate == 270:
            return cv2.rotate(frame, cv2.ROTATE_90_COUNTERCLOCKWISE)
        return frame

    def _apply_roi(self, frame: np.ndarray) -> tuple[np.ndarray, int, int]:
        x1f, y1f, x2f, y2f = self.cam.roi
        if (x1f, y1f, x2f, y2f) == (0.0, 0.0, 1.0, 1.0):
            return frame, 0, 0
        h, w = frame.shape[:2]
        x1, y1 = int(x1f * w), int(y1f * h)
        x2, y2 = int(x2f * w), int(y2f * h)
        x1, y1 = max(x1, 0), max(y1, 0)
        x2, y2 = min(x2, w), min(y2, h)
        if x2 - x1 < 20 or y2 - y1 < 20:
            return frame, 0, 0
        return frame[y1:y2, x1:x2], x1, y1

    # -- writing an event ---------------------------------------------------

    def _emit(self, track, conn, force_low: bool = False) -> Passage | None:
        plate, weight, votes = track.leader()
        if not plate:
            return None

        rc = self.cfg.recognition
        ocr_conf = round(min(weight / max(votes, 1), 1.0), 4)
        plaus = plate_text.plausibility(plate)
        conf = round(ocr_conf * plaus, 4)
        low = force_low or conf < rc.min_accept_conf or track.margin() < 0.15

        prior = db.recent_event(conn, plate, self.cam.id, rc.dedupe_seconds)
        if prior is not None:
            # The same vehicle, still in front of the camera. One car is one
            # event - a second row here is not extra information, it is a
            # phantom car in the occupancy count. But a later read is often a
            # better read, because the plate is closer, so a clearer view
            # replaces the logged one instead of being thrown away.
            if conf > (prior["confidence"] or 0.0):
                snap_rel = crop_rel = None
                if track.best_frame is not None:
                    snap_rel, crop_rel = self._save_images(plate, track)
                db.improve_event(conn, int(prior["id"]), plate=plate,
                                 confidence=conf, ocr_confidence=ocr_conf,
                                 plausibility=plaus, votes=votes,
                                 low_confidence=low, snapshot=snap_rel,
                                 plate_crop=crop_rel)
                log.info("[%s] %s -> %s (better read of the same car)",
                         self.cam.id, plate_text.display(prior["plate"]),
                         plate_text.display(plate))
            else:
                log.debug("[%s] %s deduped", self.cam.id, plate)
            return None

        direction = self.cam.direction
        if direction == "both":
            direction = self._infer_direction(track)

        snap_rel = crop_rel = None
        if track.best_frame is not None:
            snap_rel, crop_rel = self._save_images(plate, track)

        status, veh = db.classify(conn, plate)
        when = db.now_local()
        event_id = db.insert_event(
            conn, plate=plate, camera_id=self.cam.id,
            gate_number=self.cam.gate_number, direction=direction,
            status=status, vehicle_id=veh["id"] if veh else None,
            confidence=conf, ocr_confidence=ocr_conf, plausibility=plaus,
            votes=votes, low_confidence=low, snapshot=snap_rel,
            plate_crop=crop_rel, when=when)

        event = dict(conn.execute("SELECT * FROM events WHERE id=?",
                                  (event_id,)).fetchone())
        visit = db.register_passage(conn, event)
        self._raise_alerts(conn, event, veh, visit, low)

        log.info("[%s] gate %s %s: %s (%s) conf=%.2f votes=%d",
                 self.cam.id, self.cam.gate_number, direction,
                 plate_text.display(plate), status, conf, votes)

        return Passage(plate=plate, camera_id=self.cam.id,
                       gate_number=self.cam.gate_number, direction=direction,
                       confidence=conf, ocr_confidence=ocr_conf,
                       plausibility=plaus, votes=votes, snapshot=snap_rel,
                       plate_crop=crop_rel, low_confidence=low)

    def _infer_direction(self, track) -> str:
        """
        Single camera covering both ways: use plate growth.

        A plate getting bigger across the track means the car is coming toward
        the camera; shrinking means it is leaving. This compares the plate
        against its own first sighting, which is the only thing that carries
        the direction — the previous version compared the width against a
        fixed 48 pixels, so any plate a camera could read at all came out as
        "entry" and a `both` camera could never record an exit at all.

        Mount the camera facing incoming traffic and this holds. For anything
        more than a small site, use two cameras and set the direction
        explicitly: growth needs the car to actually move through the frame,
        and a plate first seen at its closest cannot be told apart either way.
        """
        grown = track.box.w - track.first_w
        if abs(grown) < max(track.first_w * 0.12, 3):
            return "entry"        # too little movement to call; assume arrival
        return "entry" if grown > 0 else "exit"

    def _save_images(self, plate: str, track) -> tuple[str | None, str | None]:
        day = db.now_local().strftime("%Y-%m-%d")
        folder = SNAPSHOT_DIR / day / self.cam.id
        folder.mkdir(parents=True, exist_ok=True)
        stamp = db.now_local().strftime("%H%M%S")
        safe = plate.replace(" ", "_") or "unknown"
        snap = folder / f"{stamp}_{safe}.jpg"
        crop = folder / f"{stamp}_{safe}_plate.jpg"
        try:
            cv2.imwrite(str(snap), track.best_frame,
                        [cv2.IMWRITE_JPEG_QUALITY, 85])
            if track.best_crop is not None:
                cv2.imwrite(str(crop), track.best_crop,
                            [cv2.IMWRITE_JPEG_QUALITY, 95])
            self._collect_for_training(track, plate, day)
            return (str(snap.relative_to(SNAPSHOT_DIR)),
                    str(crop.relative_to(SNAPSHOT_DIR)))
        except Exception as exc:
            log.warning("[%s] could not save images: %s", self.cam.id, exc)
            return None, None

    def _collect_for_training(self, track, plate: str, day: str) -> None:
        """
        Bank every plate crop for later labelling.

        This is how the system gets good: three weeks of real crops from your
        actual camera angle, lighting and dust, then fine-tune on them. Costs
        almost nothing to keep and is far more valuable than any public dataset.
        """
        if not self.cfg.collect_dataset or track.best_crop is None:
            return
        if self._collect_day != day:
            self._collect_day, self._collected_today = day, 0
        if self._collected_today >= self.cfg.collect_max_per_day:
            return
        folder = DATASET_DIR / "plates" / day
        folder.mkdir(parents=True, exist_ok=True)
        stamp = db.now_local().strftime("%H%M%S%f")[:-3]
        name = f"{self.cam.id}_{stamp}_{plate.replace(' ', '_')}.jpg"
        cv2.imwrite(str(folder / name), track.best_crop,
                    [cv2.IMWRITE_JPEG_QUALITY, 95])
        self._collected_today += 1

    def _raise_alerts(self, conn, event: dict, veh, visit: dict,
                      low: bool) -> None:
        gate = event["gate_number"]
        disp = plate_text.display(event["plate"])
        status = event["status"]
        dir_ar = "دخول" if event["direction"] == "entry" else "خروج"

        if status == "blacklist" and self.cfg.alert_on_blacklist:
            db.add_alert(conn, "danger", "blacklist",
                         f"سيارة محظورة {disp} عند البوابة {gate} ({dir_ar})",
                         event["plate"], event["id"], gate)
        elif status == "unknown" and self.cfg.alert_on_unknown:
            # A single misread glyph turns a resident into a stranger. Say so
            # in the alert rather than making the guard search for it: the
            # suggestion is a question for a human, never an admission.
            maybe = db.near_vehicle(conn, event["plate"])
            extra = ""
            if maybe is not None:
                owner = (maybe["owner_name"] or "").strip()
                extra = (f" — ربما {plate_text.display(maybe['plate'])}"
                         + (f" ({owner})" if owner else "")
                         + "؟ يرجى التأكد")
            db.add_alert(conn, "warning", "unknown",
                         f"سيارة غير مسجلة {disp} عند البوابة {gate} ({dir_ar}){extra}",
                         event["plate"], event["id"], gate)
        elif status == "expired":
            owner = (veh["owner_name"] if veh else "") or ""
            db.add_alert(conn, "warning", "expired",
                         f"تصريح منتهي {disp} {owner} عند البوابة {gate}",
                         event["plate"], event["id"], gate)

        if low:
            db.add_alert(conn, "info", "low_confidence",
                         f"قراءة غير مؤكدة {disp} عند البوابة {gate} — "
                         f"يرجى المراجعة",
                         event["plate"], event["id"], gate)


def _sharpness(img: np.ndarray) -> float:
    if img is None or img.size == 0:
        return 0.0
    gray = cv2.cvtColor(img, cv2.COLOR_BGR2GRAY) if img.ndim == 3 else img
    return float(cv2.Laplacian(gray, cv2.CV_64F).var())


class WorkerPool:
    """Starts one worker per enabled camera and keeps them alive."""

    def __init__(self, cfg: SystemConfig) -> None:
        self.cfg = cfg
        self.stop_event = threading.Event()
        self.workers: list[CameraWorker] = []

    def start(self) -> None:
        # Fresh event on every start: stop() leaves the old one set, so reusing
        # it would make restarted workers exit immediately. This matters
        # because the settings page restarts the pool in place.
        self.stop_event = threading.Event()
        cams = [c for c in self.cfg.cameras if c.enabled]
        if not cams:
            log.warning("no enabled cameras in config")
        # Detector and reader are shared: loading YOLO weights once instead of
        # once per camera saves a lot of memory on a Jetson.
        rc = self.cfg.recognition
        detector = PlateDetector(rc.detector_backend,
                                 str(ROOT / rc.plate_detector_weights),
                                 rc.min_detect_conf, rc.device)
        reader = PlateReader(rc.ocr_backend,
                             str(ROOT / rc.char_detector_weights), rc.device)
        for cam in cams:
            w = CameraWorker(cam, self.cfg, detector, reader, self.stop_event)
            w.start()
            self.workers.append(w)
            log.info("started %s -> gate %d (%s)", cam.id, cam.gate_number,
                     cam.direction)

    def stop(self) -> None:
        self.stop_event.set()
        for w in self.workers:
            w.join(timeout=6)
        self.workers.clear()

    def restart(self, cfg: SystemConfig | None = None) -> None:
        """Apply changed camera settings without restarting the process."""
        if cfg is not None:
            self.cfg = cfg
        self.stop()
        time.sleep(0.6)          # let the OS release the camera handles
        self.start()
