"""Event emission shared by every detector.

Detectors only classify each track's current state (normal / falling / fallen);
this state machine decides when that becomes a fall *event*, so the rule-based
and learned detectors raise alerts by exactly the same logic:

* a track counts as upright only after ``upright_s`` of uninterrupted NORMAL
  observations (a single glitchy NORMAL frame never counts) ...
* alert when it has been FALLEN for ``confirm_s`` ...
* ... and it was upright no more than ``transition_s`` before it first became
  FALLEN (someone who was already lying/sitting never fires -- this is the
  britishnew "was upright within FALL_HISTORY_S" gate) ...
* ... at most once until the track has been upright again for ``rearm_s``,
  and never twice within ``cooldown_s``.

Two optional rules (off by default; train/calibrate.py switches them on when
they help on validation videos) cover falls whose end is never seen as FALLEN:

* ``falling_alert_s``: a run of FALLING/FALLEN this long that started right
  after the track was upright also alerts (the person ends up in a pose the
  classifier doesn't call "fallen", e.g. sitting on the floor);
* ``lost_alert_s``: a track that was FALLING/FALLEN for at least
  ``min_falling_s`` (right after being upright) and then vanishes for this long
  alerts -- pose estimators often lose people once they are on the floor.

FALLING observations neither confirm nor break a fall. UNKNOWN observations
(no usable pose / no prediction yet) keep the track alive but interrupt an
upright streak.
"""

from dataclasses import asdict, dataclass

from core.features import FALLEN, FALLING, NORMAL, UNKNOWN


@dataclass
class EmitterConfig:
    confirm_s: float = 0.2      # FALLEN must persist this long before alerting
    upright_s: float = 0.3      # uninterrupted NORMAL this long counts as "was upright"
    transition_s: float = 2.0   # max time from last upright frame to the fall starting
    rearm_s: float = 1.0        # upright this long re-arms an alerted track
    cooldown_s: float = 5.0     # min time between two alerts on the same track
    stale_s: float = 3.0        # forget tracks unseen this long
    falling_alert_s: float | None = None   # long FALLING/FALLEN run after upright alerts (None = off)
    lost_alert_s: float | None = None      # vanishing this long mid-fall alerts (None = off)
    min_falling_s: float = 0.2             # minimum fall evidence before a lost track can alert

    def to_dict(self):
        return asdict(self)


class _Track:
    __slots__ = ("last_seen", "last_obs", "last_upright", "normal_since", "run_start", "fallen_since",
                 "alerted", "last_alert", "state", "last_state", "confidence", "bbox")

    def __init__(self):
        self.last_seen = None
        self.last_obs = None        # last frame with a known (non-UNKNOWN) state
        self.last_upright = None    # last frame of a NORMAL streak >= upright_s
        self.normal_since = None    # start of the current uninterrupted NORMAL streak
        self.run_start = None       # first non-NORMAL frame since the track was last upright
        self.fallen_since = None    # first FALLEN frame since the track was last upright
        self.alerted = False
        self.last_alert = None
        self.state = UNKNOWN        # state predicted on the last frame seen
        self.last_state = UNKNOWN   # last known (non-UNKNOWN) state
        self.confidence = 0.0
        self.bbox = None


class EventEmitter:
    def __init__(self, config: EmitterConfig | None = None, fps: float = 30.0):
        self.config = config or EmitterConfig()
        self.reset(fps)

    def reset(self, fps: float = 30.0):
        self.fps = fps
        self._tracks: dict[int, _Track] = {}

    def _frames(self, seconds):
        return max(1, round(seconds * self.fps))

    def _fall_started_upright(self, t):
        """The current non-NORMAL run began within transition_s of being upright."""
        return (t.last_upright is not None and t.run_start is not None
                and t.run_start - t.last_upright <= self._frames(self.config.transition_s))

    def _fire(self, track_id, t, frame_idx):
        from .base import FallEvent

        if t.last_alert is not None and frame_idx - t.last_alert < self._frames(self.config.cooldown_s):
            return None
        t.alerted = True
        t.last_alert = frame_idx
        return FallEvent(track_id=track_id, frame_idx=frame_idx, confidence=t.confidence,
                         bbox=t.bbox, fall_start_frame=t.run_start)

    def observe(self, track_id, frame_idx, state, confidence=0.0, bbox=None):
        """Feed one track's state for one frame; returns a FallEvent or None."""
        t = self._tracks.get(track_id)
        if t is None:
            t = self._tracks[track_id] = _Track()
        t.last_seen = frame_idx
        if bbox is not None:
            t.bbox = tuple(float(v) for v in bbox)
        if state is None or state == UNKNOWN:
            t.state, t.confidence = UNKNOWN, 0.0
            t.normal_since = None
            return None
        contiguous = t.last_obs == frame_idx - 1
        t.last_obs = frame_idx
        t.state = t.last_state = int(state)
        t.confidence = float(confidence)

        if state == NORMAL:
            if t.normal_since is None or not contiguous:
                t.normal_since = frame_idx
            streak = frame_idx - t.normal_since + 1
            if streak >= self._frames(self.config.upright_s):
                t.last_upright = frame_idx
                t.run_start = None
                t.fallen_since = None
            if t.alerted and streak >= self._frames(self.config.rearm_s):
                t.alerted = False
            return None

        t.normal_since = None
        if t.run_start is None:
            t.run_start = frame_idx
        if state == FALLEN and t.fallen_since is None:
            t.fallen_since = frame_idx
        if t.alerted:
            return None

        confirmed_fallen = (
            state == FALLEN
            and frame_idx - t.fallen_since + 1 >= self._frames(self.config.confirm_s)
            and t.last_upright is not None
            and t.fallen_since - t.last_upright <= self._frames(self.config.transition_s))
        long_fall = (
            self.config.falling_alert_s is not None
            and frame_idx - t.run_start + 1 >= self._frames(self.config.falling_alert_s)
            and self._fall_started_upright(t))
        if confirmed_fallen or long_fall:
            return self._fire(track_id, t, frame_idx)
        return None

    def sweep(self, frame_idx):
        """Alerts for tracks that vanished mid-fall (``lost_alert_s``); call once per frame."""
        if self.config.lost_alert_s is None:
            return []
        lost = self._frames(self.config.lost_alert_s)
        min_run = self._frames(self.config.min_falling_s)
        events = []
        for tid, t in self._tracks.items():
            if (not t.alerted and frame_idx - t.last_seen >= lost
                    and t.last_state in (FALLING, FALLEN) and t.last_obs is not None
                    and self._fall_started_upright(t) and t.last_obs - t.run_start + 1 >= min_run):
                event = self._fire(tid, t, frame_idx)
                if event is not None:
                    events.append(event)
        return events

    def prune(self, frame_idx):
        """Drop tracks not seen for ``stale_s``; returns the dropped ids."""
        limit = self._frames(self.config.stale_s)
        stale = [tid for tid, t in self._tracks.items() if frame_idx - t.last_seen > limit]
        for tid in stale:
            del self._tracks[tid]
        return stale

    def status(self, track_id):
        from .base import TrackStatus

        t = self._tracks.get(track_id)
        if t is None:
            return None
        return TrackStatus(track_id=track_id, state=t.state, confidence=t.confidence,
                           alerted=t.alerted, last_seen=t.last_seen, bbox=t.bbox)

    def statuses(self):
        return {tid: self.status(tid) for tid in self._tracks}
