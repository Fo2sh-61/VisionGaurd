"""The FallDetector interface every detector implements.

A detector is fed the pose estimator's output frame by frame and returns the
fall events it decided to raise on that frame. All per-track state lives in
the detector; ``reset(fps)`` starts a new video/stream.

ByteTrack often hands a person a new id in the middle of a fall (the box
changes shape abruptly). ``update`` therefore first maps tracker ids to stable
identities with ``TrackLinker`` -- the same "follow the box" idea that
train/prepare_data.stitch_subject uses to label training data -- and only then
calls the detector's ``_update``. Use ``status_for(tracker_id)`` to look up the
status of a person as the tracker currently names them.
"""

from abc import ABC, abstractmethod
from dataclasses import dataclass, replace
from typing import ClassVar, Sequence

from core.boxes import box_iou, center_distance
from core.pose import Person

from .events import EmitterConfig, EventEmitter


@dataclass(frozen=True)
class FallEvent:
    track_id: int                      # stable identity (see TrackLinker)
    frame_idx: int                     # frame the alert was raised on
    confidence: float
    bbox: tuple[float, float, float, float] | None = None
    fall_start_frame: int | None = None   # first non-normal frame of the run that led here


@dataclass
class TrackStatus:
    """Latest per-track state, for drawing overlays and frame-level evaluation."""
    track_id: int
    state: int                         # core.features NORMAL / FALLING / FALLEN / UNKNOWN
    confidence: float
    alerted: bool
    last_seen: int
    bbox: tuple[float, float, float, float] | None = None


class TrackLinker:
    """Maps tracker ids to stable identities across id switches.

    A tracker id seen for the first time is linked to an identity that went
    missing at most ``max_lost_s`` ago if their boxes overlap (IoU >=
    ``min_iou``) or their centers are close (within ``max_center_dist`` of the
    lost box's longer side); otherwise it starts a new identity.
    """

    def __init__(self, max_lost_s=1.0, min_iou=0.1, max_center_dist=0.5):
        self.max_lost_s = max_lost_s
        self.min_iou = min_iou
        self.max_center_dist = max_center_dist
        self.reset()

    def reset(self, fps=30.0):
        self.fps = fps
        self.alias: dict[int, int] = {}                 # tracker id -> stable id
        self._last: dict[int, tuple[int, tuple]] = {}   # stable id -> (frame, bbox)

    def stable_id(self, track_id):
        return self.alias.get(track_id, track_id)

    def link(self, frame_idx, persons):
        if self.max_lost_s <= 0:
            return list(persons)
        max_lost = max(1, round(self.max_lost_s * self.fps))
        out, fresh, present = list(persons), [], set()
        for i, p in enumerate(persons):
            if p.track_id is None:
                continue
            if p.track_id in self.alias:
                present.add(self.alias[p.track_id])
            else:
                fresh.append(i)
        for i in fresh:
            p = persons[i]
            best, best_d = p.track_id, float("inf")
            for sid, (f, box) in self._last.items():
                if sid in present or not 1 <= frame_idx - f <= max_lost:
                    continue
                d = center_distance(box, p.bbox)
                if (box_iou(box, p.bbox) >= self.min_iou or d <= self.max_center_dist) and d < best_d:
                    best, best_d = sid, d
            self.alias[p.track_id] = best
            present.add(best)
        for i, p in enumerate(persons):
            if p.track_id is None:
                continue
            sid = self.alias[p.track_id]
            if sid != p.track_id:
                out[i] = replace(p, track_id=sid)
            self._last[sid] = (frame_idx, tuple(p.bbox))
        for sid in [s for s, (f, _) in self._last.items() if frame_idx - f > max_lost]:
            del self._last[sid]
            for tid in [t for t, s in self.alias.items() if s == sid]:
                del self.alias[tid]
        return out


class FallDetector(ABC):
    name: ClassVar[str]           # registry key, used on the command line
    display_name: ClassVar[str]   # label shown in the GUI dropdown

    def __init__(self, emitter_config: EmitterConfig | None = None, link_s: float = 1.0):
        """link_s: how long a lost identity can be re-linked to a new tracker id (0 = off)."""
        self.emitter = EventEmitter(emitter_config)
        self.linker = TrackLinker(max_lost_s=link_s)
        self.fps = 30.0

    @classmethod
    def unavailable_reason(cls) -> str | None:
        """Why this detector can't be built with default arguments (e.g. no
        checkpoint yet), or None if it can."""
        return None

    def reset(self, fps: float = 30.0) -> None:
        """Forget all tracks; call at the start of every video or stream."""
        self.fps = fps
        self.emitter.reset(fps)
        self.linker.reset(fps)

    def update(self, frame_idx: int, persons: Sequence[Person]) -> list[FallEvent]:
        """Process one frame's detections and return newly raised fall events."""
        events = self._update(frame_idx, self.linker.link(frame_idx, persons))
        return events + self.emitter.sweep(frame_idx)   # people who vanished mid-fall

    @abstractmethod
    def _update(self, frame_idx: int, persons: Sequence[Person]) -> list[FallEvent]:
        """Like ``update``, with ``track_id`` already replaced by stable identities."""

    def statuses(self) -> dict[int, TrackStatus]:
        """Stable identity -> status."""
        return self.emitter.statuses()

    def status_for(self, track_id: int | None) -> TrackStatus | None:
        """Status of the person the tracker currently calls ``track_id``."""
        if track_id is None:
            return None
        return self.emitter.status(self.linker.stable_id(track_id))
