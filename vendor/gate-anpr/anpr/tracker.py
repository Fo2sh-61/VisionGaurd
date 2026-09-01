"""
Multi-frame tracking and vote-based plate confirmation.

A single frame is never trusted. Each plate is tracked across frames while the
car approaches the barrier, every frame contributes a weighted vote, and the
plate is only confirmed once one candidate has enough support. This is what
turns a ~90%-per-frame reader into a system that is right almost every time,
and it is the single highest-value piece of logic in the project.

Voting details that matter in practice:
  * Votes are weighted by (ocr confidence x plausibility x plate size), so a
    close, sharp, well-formed read outweighs a distant blurry one.
  * Candidates one confusable glyph apart are merged into the stronger one -
    ه/٥ and و/٦ misreads otherwise split the vote and delay confirmation.
  * A track that never reaches the threshold is dropped silently rather than
    logged as a bad plate.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Iterable

from . import plate_text
from .detector import PlateBox


@dataclass
class Track:
    track_id: int
    box: PlateBox
    first_seen: float
    last_seen: float
    misses: int = 0
    # Width of the plate the first time it was seen. Direction on a camera set
    # to "both" is read off the change from this, so it has to be captured at
    # creation rather than inferred later.
    first_w: int = 0
    votes: dict[str, float] = field(default_factory=dict)
    counts: dict[str, int] = field(default_factory=dict)
    best_crop: object | None = None      # np.ndarray of the sharpest crop
    best_crop_score: float = 0.0
    best_frame: object | None = None
    reported: bool = False
    # OCR bookkeeping. Recognition is 10-100x more expensive than detection,
    # so a track remembers when it was last read and how good that view was.
    last_ocr_at: float = 0.0
    last_ocr_area: int = 0
    ocr_count: int = 0

    def __post_init__(self) -> None:
        if not self.first_w:
            self.first_w = self.box.w

    # -- voting ----------------------------------------------------------

    # How far apart two reads may be and still count as the same plate *inside
    # one track*. Deliberately looser than anywhere else in the system: a track
    # is one bounding box following one plate, so the chance that two genuinely
    # different vehicles are voting in it is nil, while the chance that the
    # reader dropped a glyph on one frame and a different one on the next is
    # high. Everywhere outside a track, where two reads really can be two cars,
    # the tighter one-edit rule applies.
    MERGE_EDITS = 2

    def add_vote(self, text: str, weight: float) -> None:
        """
        Add one frame's reading, folding it into an existing candidate if it is
        the same plate read imperfectly.

        Without the folding, a reader that drops one glyph per frame never
        agrees with itself: "مجب 451", "مب 451" and "مجب 41" are three
        candidates with one vote each, none of them ever reaches the threshold,
        and the car is either logged as a guess or not logged at all. Folded,
        they are five votes for one plate - and the spelling kept is the
        fullest one, because a dropped character is far more common than an
        invented one.
        """
        if not text:
            return
        match = self._existing_match(text)
        if match is None:
            self.votes[text] = self.votes.get(text, 0.0) + weight
            self.counts[text] = self.counts.get(text, 0) + 1
            return
        key = plate_text.richer(text, match)
        if key != match:                      # this read spells it better
            self.votes[key] = self.votes.pop(match, 0.0)
            self.counts[key] = self.counts.pop(match, 0)
        self.votes[key] = self.votes.get(key, 0.0) + weight
        self.counts[key] = self.counts.get(key, 0) + 1

    def _existing_match(self, text: str) -> str | None:
        """The best-supported candidate that is the same plate as `text`."""
        if text in self.votes:
            return text
        best = None
        for cand in self.votes:
            if plate_text.same_plate(text, cand, self.MERGE_EDITS):
                if best is None or self.votes[cand] > self.votes[best]:
                    best = cand
        return best

    def leader(self) -> tuple[str, float, int]:
        if not self.votes:
            return "", 0.0, 0
        text = max(self.votes, key=lambda k: self.votes[k])
        return text, self.votes[text], self.counts.get(text, 0)

    def margin(self) -> float:
        """Gap between the top candidate and the runner-up. Low = ambiguous."""
        if len(self.votes) < 2:
            return 1.0
        vals = sorted(self.votes.values(), reverse=True)
        return (vals[0] - vals[1]) / vals[0] if vals[0] else 0.0


class PlateTracker:
    """Greedy IoU tracker. Plates at a gate are few and slow — this is plenty."""

    def __init__(self, max_misses: int = 12, iou_threshold: float = 0.25,
                 min_votes: int = 3) -> None:
        self.max_misses = max_misses
        self.iou_threshold = iou_threshold
        self.min_votes = min_votes
        self._tracks: dict[int, Track] = {}
        self._next_id = 1

    @property
    def tracks(self) -> Iterable[Track]:
        return self._tracks.values()

    def update(self, boxes: list[PlateBox], now: float) -> list[tuple[Track, PlateBox]]:
        """Match detections to tracks. Returns (track, box) pairs to read."""
        pairs: list[tuple[Track, PlateBox]] = []
        unmatched = list(boxes)
        matched: set[int] = set()

        for track in list(self._tracks.values()):
            best, best_iou = None, 0.0
            for b in unmatched:
                i = _iou(track.box, b)
                if i > best_iou:
                    best, best_iou = b, i
            if best is not None and best_iou >= self.iou_threshold:
                track.box = best
                track.last_seen = now
                track.misses = 0
                unmatched.remove(best)
                matched.add(track.track_id)
                pairs.append((track, best))
            else:
                track.misses += 1

        # A box left over is not automatically a new vehicle. The detector
        # regularly proposes a second, differently-framed box for a plate it
        # has already found, and IoU alone calls that a stranger: a tight box
        # and a loose one on the same plate score well under the matching
        # threshold. Left unchecked each of those became its own track, voted
        # on its own, and reported its own event - which is why one car
        # arriving produced three rows in the log and pushed the occupancy
        # count up by three. Position decides it here: a box sitting on top of
        # a plate already being tracked belongs to that plate.
        for b in unmatched:
            host = self._host_track(b)
            if host is None:
                t = Track(track_id=self._next_id, box=b, first_seen=now,
                          last_seen=now)
                self._tracks[self._next_id] = t
                self._next_id += 1
                pairs.append((t, b))
            elif host.track_id not in matched:
                # The plate moved further than IoU tolerates - a fast car, or a
                # jittery detection. Same vehicle; carry the track over.
                host.box = b
                host.last_seen = now
                host.misses = 0
                matched.add(host.track_id)
                pairs.append((host, b))
            # else: a duplicate box on a plate already read this frame - drop
            # it, so it costs neither an event nor a recognition.

        return pairs

    def _host_track(self, box: PlateBox) -> Track | None:
        """The tracked plate this box sits on, if any."""
        best, best_cover = None, 0.0
        for track in self._tracks.values():
            c = _containment(track.box, box)
            if c > best_cover:
                best, best_cover = track, c
        return best if best_cover >= 0.5 else None

    # Average per-vote weight a track must sustain to be believed. The total
    # bar is this times `min_votes`, so the two settings stay consistent:
    # a fixed total silently raises the per-read standard every time an
    # operator lowers min_votes, which is the opposite of what they asked for.
    # At the historical min_votes=3 this reproduces the old 1.6 threshold.
    WEIGHT_PER_VOTE = 0.55

    def confirmed(self, min_weight: float | None = None) -> list[Track]:
        """
        Tracks with enough agreeing reads to act on, reported once each.

        `min_votes` is the operator's decision about how much agreement a gate
        requires, so it is never quietly undercut here — a site that sets 5 for
        a high-security barrier must get 5. Speed comes from lowering it in the
        config: with a character-detection model on a GPU each vote costs one
        frame, so min_votes=2 confirms in about a tenth of a second.
        """
        if min_weight is None:
            min_weight = self.min_votes * self.WEIGHT_PER_VOTE
        out = []
        for t in self._tracks.values():
            if t.reported:
                continue
            text, weight, count = t.leader()
            if text and count >= self.min_votes and weight >= min_weight:
                t.reported = True
                out.append(t)
        return out

    def expired(self) -> list[Track]:
        """Tracks whose car has left the frame. Removes them from the tracker."""
        gone = [t for t in self._tracks.values() if t.misses > self.max_misses]
        for t in gone:
            self._tracks.pop(t.track_id, None)
        return gone

    def unreported_leftovers(self, tracks: list[Track]) -> list[Track]:
        """
        Expired tracks that were read but never reached the threshold.

        Without this a vehicle that is only briefly in view — a car that rolls
        through, or any plate the reader disagreed with itself about — is
        deleted in silence, having been detected, cropped and read. From the
        outside that is indistinguishable from the camera never seeing it, and
        it is the worst possible failure for a gate: no event, no alert, no
        snapshot, nothing to review. Handing the read back with whatever
        support it gathered lets the caller log it for a human to confirm.
        """
        return [t for t in tracks if not t.reported and t.leader()[0]]

    def reset(self) -> None:
        self._tracks.clear()


def _containment(a: PlateBox, b: PlateBox) -> float:
    """Overlap as a fraction of the smaller box, not of their union.

    Two boxes on the same plate often differ a lot in size - one hugging the
    characters, one including the frame - and IoU reads that as a poor match
    even when one sits entirely inside the other. What identifies "same plate"
    is the containment, which is what this measures.
    """
    ix = max(min(a.x2, b.x2) - max(a.x1, b.x1), 0)
    iy = max(min(a.y2, b.y2) - max(a.y1, b.y1), 0)
    small = min(a.area, b.area)
    return (ix * iy) / small if small else 0.0


def _iou(a: PlateBox, b: PlateBox) -> float:
    ix1, iy1 = max(a.x1, b.x1), max(a.y1, b.y1)
    ix2, iy2 = min(a.x2, b.x2), min(a.y2, b.y2)
    iw, ih = max(ix2 - ix1, 0), max(iy2 - iy1, 0)
    inter = iw * ih
    union = a.area + b.area - inter
    return inter / union if union else 0.0


# Plate width, in pixels, at which a read is trusted at full strength. Chosen
# from what the reader actually needs rather than from the optics: accuracy is
# flat above roughly this size and tails off below it.
FULL_STRENGTH_PX = 160


def vote_weight(ocr_conf: float, plausibility: float, plate_w: int,
                frame_w: int = 0) -> float:
    """
    Weight one frame's contribution.

    The size term is in absolute pixels, not as a fraction of frame width.
    What limits a read is how many pixels the glyphs occupy, and that is a
    property of the plate alone — measuring it against frame width instead
    punishes a plate for the camera being wide, so the identical plate at the
    identical distance scores lower on a 4K camera than on a 720p one, and a
    gate framed to see a whole driveway scores lower than a tightly cropped
    one. `frame_w` is kept for callers that still pass it, and ignored.
    """
    size = min(plate_w / float(FULL_STRENGTH_PX), 1.0)
    return round(float(ocr_conf) * float(plausibility) * (0.4 + 0.6 * size), 4)
