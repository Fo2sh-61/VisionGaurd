"""Vehicle gate: read the plate, and never trust one frame.

**The whole accuracy argument of this feature is in `_Track.vote`.** A reader
that is right ~90% of the time on a single frame is not good enough to write
a name into a gate log — one frame in ten records the wrong car. But a car
approaching a gate is visible for dozens of frames, and the errors are not
correlated: the misreads scatter while the correct reading repeats. So each
frame casts a **weighted vote**, and nothing is recorded until several frames
agree.

    weight = reading confidence x plausibility x how big the plate was

All three matter. Confidence alone lets a crisp reading of nonsense win.
Plausibility alone lets a barely-visible plate outvote a clear one. Size is
what makes a car three metres away outweigh the same car at fifteen.

**Readings within one edit merge rather than compete.** `ب/ت` and `ج/ح` are
the same shape at gate distances, and if two spellings of one plate split the
vote, three frames never agree and the car is never recorded at all. Merging
them is what turns a good reader into a reliable system.

**Time comes from `frame.captured_at`, never `time.monotonic()`.** The
timestamps then match the video rather than however busy the machine was, and
a test can prove a sixty-second window in microseconds by choosing its own
times.

There is no threading in this file. `FeatureWorker` owns it.
"""

from __future__ import annotations

import logging
from dataclasses import dataclass, field
from datetime import datetime, timedelta

import numpy as np

from vg import platetext
from vg.features.base import FeatureWorker
from vg.infer.plates import PlateBox, PlateRead, PlateReader
from vg.ingest.source import Frame

log = logging.getLogger(__name__)

#: How many separate frames must agree before a pass is recorded.
#:
#: Three, and the number is a floor rather than a preference. Two frames agree
#: by luck often enough to matter; the third is what makes agreement evidence.
MIN_VOTES = 3

#: Total vote weight a plate needs before it counts as read.
#:
#: Weight and count are both required because they fail differently: three
#: glances at a distant plate clear the count and should not clear this, while
#: one superb reading clears the weight and must still wait for company.
MIN_WEIGHT = 0.9

#: Below this the pass is recorded **and flagged**, never discarded.
#:
#: A weak reading is still evidence that a car went through, and the snapshot
#: is kept with it. Throwing it away loses the only record that anything
#: happened; keeping it unflagged would state something the reader does not
#: know. P6-FR-005.
REVIEW_BELOW = 0.55

#: The same plate at the same camera inside this window is one pass.
#:
#: A car sits at a barrier for twenty seconds. Without this every frame it is
#: read in becomes another arrival, and the gate log turns into noise.
#:
#: **The default, not the rule.** P6-FR-006 says the window is configured, and
#: `engine.yaml`'s `vehicles.dedupe_seconds` is where. This was a constant
#: until somebody testing with a plate in their hand found the log ignoring
#: them for a minute with nothing on screen to say why.
DEDUPE_SECONDS = 60.0

#: How many frames a track survives without being seen before it is finished.
LOST_FRAMES = 8

#: Overlap at which two boxes are the same car between frames.
IOU_SAME_CAR = 0.25


def vote_weight(confidence: float, plausibility: float, plate_width: int) -> float:
    """How much this frame's reading is worth.

    Width is capped rather than linear: past about 200px a plate is fully
    legible and being closer adds nothing, so an enormous plate must not be
    able to outvote three good readings on its own.
    """
    size = min(max(plate_width, 0) / 200.0, 1.0)
    return round(max(confidence, 0.0) * max(plausibility, 0.0) * size, 4)


def _iou(a: PlateBox, b: PlateBox) -> float:
    ix = max(min(a.x2, b.x2) - max(a.x1, b.x1), 0)
    iy = max(min(a.y2, b.y2) - max(a.y1, b.y1), 0)
    overlap = ix * iy
    union = a.area + b.area - overlap
    return overlap / union if union > 0 else 0.0


@dataclass
class _Track:
    """One car approaching the gate, across frames."""

    box: PlateBox
    first_seen: datetime
    last_seen: datetime
    votes: dict[str, float] = field(default_factory=dict)
    counts: dict[str, int] = field(default_factory=dict)
    best_confidence: float = 0.0
    misses: int = 0
    reported: bool = False
    #: The frame that read best, and where the plate was in it. Kept so the
    #: pass can be photographed (P6-FR-003) from the clearest look the camera
    #: got, rather than from whichever frame happened to be the third. One
    #: image per car in view, dropped when the track is.
    best_image: "np.ndarray | None" = field(default=None, compare=False,
                                            repr=False)
    best_box: PlateBox | None = field(default=None, compare=False, repr=False)

    def vote(self, text: str, weight: float, confidence: float) -> None:
        """Add a frame's reading, merging it into a near match if there is one.

        The merge is the point. Two spellings of one plate that compete
        instead of combining never reach three agreeing frames, so the car is
        never recorded — a failure that looks like the reader not working
        rather than the voting being wrong.
        """
        if not text:
            return
        key = self._existing(text) or text
        if key != text:
            # Keep whichever reading is more likely to be complete: a dropped
            # character is far more common than an invented one.
            better = platetext.richer(key, text)
            if better != key:
                self.votes[better] = self.votes.pop(key, 0.0)
                self.counts[better] = self.counts.pop(key, 0)
                key = better

        self.votes[key] = self.votes.get(key, 0.0) + weight
        self.counts[key] = self.counts.get(key, 0) + 1
        self.best_confidence = max(self.best_confidence, confidence)

    def _existing(self, text: str) -> str | None:
        for candidate in self.votes:
            if platetext.same_plate(text, candidate):
                return candidate
        return None

    @property
    def leader(self) -> tuple[str, float, int]:
        """The winning plate, its weight and how many frames agreed."""
        if not self.votes:
            return "", 0.0, 0
        text = max(self.votes, key=lambda t: self.votes[t])
        return text, self.votes[text], self.counts.get(text, 0)

    @property
    def settled(self) -> bool:
        """Enough agreement to record. Both bars, for different reasons."""
        _, weight, count = self.leader
        return count >= MIN_VOTES and weight >= MIN_WEIGHT


@dataclass(frozen=True)
class VehiclePassRead:
    """A plate the worker is confident enough to hand to the event layer."""

    plate: str
    display: str
    confidence: float
    votes: int
    needs_review: bool
    first_seen: datetime
    box: PlateBox
    #: The clearest frame this car was read in, and the plate's place in it.
    #: The event layer writes the two files; this layer never touches disk,
    #: which is what keeps it testable without one. Either may be None when
    #: the track never held a frame - a photograph is evidence, not a
    #: precondition, and a pass is recorded with or without one.
    image: "np.ndarray | None" = field(default=None, compare=False, repr=False)
    image_box: PlateBox | None = field(default=None, compare=False, repr=False)


@dataclass
class VehiclesResult:
    """What one frame produced, for the overlay and for the store."""

    reads: tuple[PlateRead, ...] = ()
    passes: tuple[VehiclePassRead, ...] = ()
    #: True when a plate was found but was physically too small to read.
    too_small: bool = False


class VehiclesWorker(FeatureWorker[VehiclesResult]):
    """Reads plates at gate cameras and emits one pass per car.

    `on_pass` is called for each settled plate. It is a plain callback rather
    than a store reference so this file stays testable without a database and
    without a camera.
    """

    def __init__(
        self,
        bus,
        reader: PlateReader,
        cameras: list[str],
        on_pass=None,
        rate_hz: float = 4.0,
        boost_hz: float = 12.0,
        dedupe_seconds: float = DEDUPE_SECONDS,
    ) -> None:
        super().__init__("vehicles", bus, cameras, rate_hz, boost_hz)
        self.reader = reader
        self.on_pass = on_pass
        self.dedupe_seconds = float(dedupe_seconds)
        # camera id -> tracks currently in view
        self._tracks: dict[str, list[_Track]] = {}
        # (camera id, plate) -> when it was last recorded, for de-duplication
        self._recent: dict[tuple[str, str], datetime] = {}

    # -- one frame ----------------------------------------------------------

    def analyse(self, frame: Frame) -> VehiclesResult:
        now = frame.captured_at
        reads = self.reader.read_frame(frame.image)
        tracks = self._tracks.setdefault(frame.camera_id, [])

        for track in tracks:
            track.misses += 1

        too_small = False
        for read in reads:
            if not read.readable:
                # The camera is too far away, or the car is. Worth surfacing:
                # no amount of software fixes a plate 40 pixels wide, and an
                # operator should be told to move the camera rather than left
                # wondering why nothing is recorded.
                too_small = True
                continue

            track = self._match(tracks, read.box)
            if track is None:
                track = _Track(box=read.box, first_seen=now, last_seen=now)
                tracks.append(track)
            track.box = read.box
            track.last_seen = now
            track.misses = 0
            track.vote(read.text, vote_weight(read.confidence,
                                              read.plausibility, read.box.w),
                       read.confidence)
            # `vote` has already raised `best_confidence` to at least this
            # read, so equality means this frame IS the best one so far. Keep
            # it for the photograph: the clearest look, not the third look.
            if track.best_image is None or read.confidence >= track.best_confidence:
                track.best_image = frame.image
                track.best_box = read.box

        passes = tuple(self._settle(frame.camera_id, tracks, now))
        self._tracks[frame.camera_id] = [
            t for t in tracks if t.misses <= LOST_FRAMES]

        return VehiclesResult(reads=tuple(reads), passes=passes,
                              too_small=too_small)

    # -- helpers ------------------------------------------------------------

    @staticmethod
    def _match(tracks: list[_Track], box: PlateBox) -> _Track | None:
        best, score = None, IOU_SAME_CAR
        for track in tracks:
            overlap = _iou(track.box, box)
            if overlap >= score:
                best, score = track, overlap
        return best

    def _settle(self, camera_id: str, tracks: list[_Track],
                now: datetime) -> list[VehiclePassRead]:
        """Emit a pass for every track that has now agreed with itself."""
        out: list[VehiclePassRead] = []
        for track in tracks:
            if track.reported or not track.settled:
                continue

            plate, _, votes = track.leader
            if self._seen_recently(camera_id, plate, now):
                # Same car, same camera, still at the barrier. One pass.
                track.reported = True
                continue

            confidence = round(track.best_confidence, 4)
            record = VehiclePassRead(
                plate=plate,
                display=platetext.display(plate),
                confidence=confidence,
                votes=votes,
                needs_review=confidence < REVIEW_BELOW,
                # Stamped with the FIRST sighting, not the third: an operator
                # opening the snapshot should watch the car arrive, not find
                # it already at the barrier.
                first_seen=track.first_seen,
                box=track.box,
                image=track.best_image,
                image_box=track.best_box,
            )
            track.reported = True
            self._recent[(camera_id, plate)] = now
            out.append(record)

            # Transliterated, never the Arabic display form: the default
            # Windows console is cp1252 and cannot encode Arabic, so logging
            # the rendered plate raises UnicodeEncodeError - inside a camera
            # thread, which would take the camera down over a log line.
            log.info("gate pass on %s: %s (%d frames, %.2f)", camera_id,
                     platetext.transliterate(plate), votes, confidence)

            if self.on_pass is not None:
                try:
                    self.on_pass(camera_id, record)
                except Exception:
                    # A store that refuses a write must not stop the camera.
                    log.exception("could not record a gate pass on %s", camera_id)
        return out

    def _seen_recently(self, camera_id: str, plate: str, now: datetime) -> bool:
        last = self._recent.get((camera_id, plate))
        if last is None:
            return False
        if now - last > timedelta(seconds=self.dedupe_seconds):
            return False
        return True

    # -- what the API asks for ---------------------------------------------

    def plates_on(self, camera_id: str) -> list[PlateRead]:
        """The plates visible on this camera now, for the overlay.

        Empty when the result has aged out — a box from four seconds ago is
        not a description of what the camera sees, and drawing it would be the
        same lie as a stale frame.
        """
        result = self.result(camera_id)
        return list(result.payload.reads) if result else []
