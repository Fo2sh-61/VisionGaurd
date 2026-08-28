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
import time
from collections import deque
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

#: The same window for a plate that is only NEARLY the same. Deliberately
#: much shorter — see `_seen_recently`, where the reasoning lives.
NEAR_DEDUPE_SECONDS = 5.0

#: How many frames a track survives without being seen before it is finished.
LOST_FRAMES = 8

#: Overlap at which two boxes are the same car between frames.
IOU_SAME_CAR = 0.25

#: How many recent attempts to keep per camera, for the console's reader card.
#:
#: A window, not a log. Enough to watch three frames agree — which is the
#: whole point of showing it — and small enough that it is obviously not a
#: record of anything. The pass table is the record.
KEEP_ATTEMPTS = 12

#: Weight of the newest read in the rolling per-read timing.
#:
#: An average over all time would go on describing the warm-up minutes after
#: the machine settled; an instant reading jitters too much to be read off a
#: screen. This lands between the two.
READ_MS_ALPHA = 0.2


@dataclass(frozen=True)
class ReadAttempt:
    """One go at reading a plate, including the ones that came to nothing.

    **The failures are the point.** A reader that returns nothing and a reader
    that returns something different every frame are different problems with
    different fixes - the first is the camera's placement, the second is the
    model - and neither is visible from the pass log, which by design only
    ever contains successes. This is the only place the difference shows.

    `display` empty means a plate was found and no characters were read from
    it. `confidence` and `plausibility` are None there rather than 0.0: there
    is no reading to be confident about.
    """

    at: datetime
    camera_id: str
    display: str
    confidence: float | None
    plausibility: float | None
    width_px: int
    #: What this car's vote is leaning towards after this frame, and how far
    #: along it is. None/0 for a plate too small to have joined a track.
    leader_display: str | None
    votes: int


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
        near_dedupe_seconds: float = NEAR_DEDUPE_SECONDS,
    ) -> None:
        super().__init__("vehicles", bus, cameras, rate_hz, boost_hz)
        self.reader = reader
        self.on_pass = on_pass
        self.dedupe_seconds = float(dedupe_seconds)
        self.near_dedupe_seconds = float(near_dedupe_seconds)
        # camera id -> tracks currently in view
        self._tracks: dict[str, list[_Track]] = {}
        # (camera id, plate) -> when it was last recorded, for de-duplication
        self._recent: dict[tuple[str, str], datetime] = {}
        # camera id -> the last few read attempts, for the console's reader
        # card. Bounded, never persisted, and written on the worker thread
        # that produced them - the same thread `analyse` runs on.
        self._attempts: dict[str, deque[ReadAttempt]] = {}
        # camera id -> rolling milliseconds per read. Absent until the first.
        self._read_ms: dict[str, float] = {}

    # -- one frame ----------------------------------------------------------

    def analyse(self, frame: Frame) -> VehiclesResult:
        now = frame.captured_at
        # `perf_counter` here and `frame.captured_at` everywhere else, on
        # purpose: this measures how long the machine took, which is a
        # property of the machine, while everything recorded about the car is
        # a property of the video and must come from the frame.
        started = time.perf_counter()
        reads = self.reader.read_frame(frame.image)
        self._note_read_ms(frame.camera_id,
                           (time.perf_counter() - started) * 1000.0)
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
                # Recorded as an attempt even so. A plate too small to read is
                # the single most common reason a gate records nothing, and it
                # is invisible in the pass log by definition - so this row,
                # with its width in amber, is the only place an operator can
                # see that the camera rather than the software is the problem.
                self._note_attempt(frame.camera_id, now, read, None)
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

            # **A car still in front of the camera is still the same
            # arrival.** This is what makes the gate survive a real barrier,
            # where a car stops and a guard checks it: see `_still_here`.
            self._still_here(frame.camera_id, read.text, now)

            # After the vote, so the leader shown beside this attempt is the
            # one this frame helped decide rather than the one before it.
            self._note_attempt(frame.camera_id, now, read, track)

        passes = tuple(self._settle(frame.camera_id, tracks, now))
        self._tracks[frame.camera_id] = [
            t for t in tracks if t.misses <= LOST_FRAMES]

        return VehiclesResult(reads=tuple(reads), passes=passes,
                              too_small=too_small)

    # -- helpers ------------------------------------------------------------

    def _note_read_ms(self, camera_id: str, elapsed_ms: float) -> None:
        previous = self._read_ms.get(camera_id)
        self._read_ms[camera_id] = elapsed_ms if previous is None else (
            READ_MS_ALPHA * elapsed_ms + (1 - READ_MS_ALPHA) * previous)

    def _note_attempt(self, camera_id: str, now: datetime, read: PlateRead,
                      track: _Track | None) -> None:
        """Keep one read for the console to show. Newest last."""
        leader_text, _, votes = track.leader if track else ("", 0.0, 0)
        read_something = bool(read.text)
        self._attempts.setdefault(
            camera_id, deque(maxlen=KEEP_ATTEMPTS)
        ).append(ReadAttempt(
            at=now,
            camera_id=camera_id,
            display=platetext.display(read.text) if read_something else "",
            # None rather than 0.0 on a read that produced nothing: zero is a
            # measurement, and there is nothing here to have measured.
            confidence=read.confidence if read_something else None,
            plausibility=read.plausibility if read_something else None,
            width_px=max(read.box.w, 0),
            leader_display=platetext.display(leader_text) or None,
            votes=votes,
        ))

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

    def _matches_recent(self, plate: str, seen_plate: str,
                        age: timedelta) -> bool:
        """Is this read the car recorded under `seen_plate`?

        **One rule, used by both the refresh and the check**, because two
        definitions of "the same car" in one file is how the log ended up with
        duplicates in the first place: the voting merged near matches and the
        de-duplication did not.

        Exact text counts for the whole window. A near match counts only for
        `near_dedupe_seconds`, because weaker evidence gets the benefit of the
        doubt for less time — see `_seen_recently`.
        """
        if seen_plate == plate:
            return True
        if self.near_dedupe_seconds <= 0:
            return False
        return (age <= timedelta(seconds=self.near_dedupe_seconds)
                and platetext.same_plate(plate, seen_plate))

    def _still_here(self, camera_id: str, plate: str, now: datetime) -> None:
        """This plate is on screen right now, so its arrival is not over.

        **Why a timer alone cannot work at a real gate.** A car arrives,
        stops, and a guard checks it — for twenty seconds, or two minutes, and
        nobody can say which in advance. While the plate stays visible the
        track holds and no second pass is written, whatever the timer says.
        But the track dies after `LOST_FRAMES` consecutive misses, which is
        under a second at the boosted rate: a guard stepping in front of the
        bumper is enough. The car is re-acquired as a new car and written down
        again.

        So the clock restarts from **the last time this plate was seen**
        rather than from when it was recorded. A car at the barrier keeps
        pushing its own expiry forward for as long as it is there, and only
        counts down once it has actually gone. "How long might a car sit
        there?" stops being a number anybody has to guess.

        **An expired entry is never revived.** Once the gap since the last
        sighting exceeds the window, that arrival is over; the car coming back
        is a new arrival and gets its own row. Refreshing a dead entry would
        mean a car that left and returned an hour later was silently folded
        into the morning's record.

        **Only ever refreshes, never adds.** Adding would let one misread
        frame suppress a real car that arrived moments afterwards.
        """
        if not plate:
            return
        window = timedelta(seconds=self.dedupe_seconds)
        for key, last in self._recent.items():
            if key[0] != camera_id:
                continue
            age = now - last
            if age <= window and self._matches_recent(plate, key[1], age):
                self._recent[key] = now

    def _seen_recently(self, camera_id: str, plate: str, now: datetime) -> bool:
        """Has this car already been written down here, moments ago?

        **Two tiers, because the two possible mistakes are not equally bad.**

        Recording one car twice is untidy: the counts inflate and nothing is
        lost. Recording two cars once loses a car — and if it were the
        blacklisted one, it vanishes with nobody told. So the looser the
        match, the shorter it may be trusted for.

            exact same plate    -> one car, for the full `dedupe_seconds`
            one character out   -> one car, but only for `near_dedupe_seconds`

        The loose tier exists because the reader wobbles: a plate briefly
        hidden loses its track, is picked up again, and can settle a character
        off — two rows, one car. Matching only on the exact string never
        caught that, which is what the log did before 28 Aug 2026.

        The loose tier is *short* because time is what tells the two cases
        apart. A re-acquired car comes back in two to four seconds; a
        genuinely different car has to drive up, which is ten seconds at
        least. Past the short window a near miss is assumed to be a different
        car and is recorded — the safe way to be wrong.

        Prunes as it scans: `_recent` is only ever added to otherwise, and a
        gate runs for months.
        """
        window = timedelta(seconds=self.dedupe_seconds)
        seen = False
        for key in list(self._recent):
            age = now - self._recent[key]
            if age > window:
                del self._recent[key]
                continue
            if not seen and key[0] == camera_id:
                seen = self._matches_recent(plate, key[1], age)
        return seen

    # -- what the API asks for ---------------------------------------------

    def plates_on(self, camera_id: str) -> list[PlateRead]:
        """The plates visible on this camera now, for the overlay.

        Empty when the result has aged out — a box from four seconds ago is
        not a description of what the camera sees, and drawing it would be the
        same lie as a stale frame.
        """
        result = self.result(camera_id)
        return list(result.payload.reads) if result else []

    def attempts_on(self, camera_id: str) -> list[ReadAttempt]:
        """The last few read attempts on this camera, newest first.

        **Deliberately not subject to `plates_on`'s staleness rule**, and the
        difference matters. A box drawn from a four-second-old result would
        claim the plate is on screen now, which is a lie about the picture.
        An attempt is stamped with the moment it happened and is presented as
        history, so keeping it after the car has gone is the honest thing —
        it is exactly what somebody watching the reader wants to look at.

        Empty for a camera this worker does not serve, which is the same
        answer as "nothing has been read yet" and reads correctly either way.
        """
        return list(reversed(self._attempts.get(camera_id, ())))

    def reading_now(self, camera_id: str):
        """The car being read at this camera right now: its crop and answer.

        Returns `(jpeg_bytes, display, votes, votes_needed)`, or None when no
        car is in view. The crop is the **clearest** frame of that car so far,
        not the latest — the same frame the pass will be photographed from,
        so what an operator watches is what gets filed.

        This is what replaced the per-frame reading table on the console. The
        raw reads wobble by a character and showing them invited the reader to
        distrust a system that was working; the picture and the settled answer
        are what a person can actually judge.
        """
        import cv2

        live = [t for t in self._tracks.get(camera_id, ())
                if t.misses == 0 and t.best_image is not None
                and t.best_box is not None]
        if not live:
            return None
        # The nearest car, which at a gate is the one at the barrier.
        track = max(live, key=lambda t: t.best_box.area)
        crop = track.best_box.crop(track.best_image)
        if crop is None or crop.size == 0:
            return None
        ok, buffer = cv2.imencode(".jpg", crop, [cv2.IMWRITE_JPEG_QUALITY, 88])
        if not ok:
            return None
        plate, _, votes = track.leader
        return bytes(buffer), platetext.display(plate), votes, MIN_VOTES

    def read_ms(self, camera_id: str) -> float | None:
        """Rolling milliseconds per read, or None before the first one.

        None, never 0.0: a camera nobody has driven past has no timing, and
        "0 ms" would claim one that nobody took.
        """
        return self._read_ms.get(camera_id)
