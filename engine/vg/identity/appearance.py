"""Stable identities across cameras, and the names attached to them.

Layer 3.5, sitting between tracking and the "track a person" feature.

**The problem this solves.** A tracker retires an ID the moment it loses
someone, so a person who walks behind a pillar and back comes out the other
side as a stranger. Measured on the walk-through clip: ByteTrack produced **35
distinct track IDs** for a corridor containing a handful of people. Reconstruct
a path from raw track IDs and you get 35 unrelated fragments.

`loiterwatch.IdentityStitcher` remembers what recent people looked like -- the
colour and brightness of their clothing, per body half, plus body shape as a
weak tie-breaker -- and hands back the original ID when someone returns. That is
appearance matching, not deep re-ID: no network, no GPU, a couple of
milliseconds of NumPy.

**Names come from faces, not from appearance.** Clothing tells you *the same
person*, never *which person*. So the flow is:

    face recognised at the gate   ->  bind that name to the body's stable id
    same body seen in a corridor  ->  the name travels, match = APPEARANCE

which is why `MatchKind` has had FACE and APPEARANCE from the beginning and the
UI already draws them in different colours. A face match is evidence about
identity; an appearance match is evidence about continuity, and the two must
never be presented as the same strength of claim.

**Bindings expire.** Clothing is only an identity for as long as somebody is
wearing it. A binding made on Monday is meaningless on Tuesday, and treating it
otherwise would put the wrong child's name on a path.
"""

from __future__ import annotations

import logging
import threading
from dataclasses import dataclass
from datetime import datetime, timezone

log = logging.getLogger(__name__)

# How long a name stays attached to an appearance identity: one working day.
# Clothing is an identity only while it is being worn, so this must never
# outlive the day it was learned on.
BINDING_TTL_SECONDS = 8 * 3600.0

# A face box and a person box are "the same human" when the face sits inside
# the body. Containment rather than IoU: a face is a small fraction of a body,
# so their intersection-over-union is tiny even when they match perfectly.
MIN_FACE_CONTAINMENT = 0.60


@dataclass(frozen=True)
class AppearanceSighting:
    """One person, one camera, one moment - identified by body, not face."""

    stable_id: str
    camera_id: str
    at: datetime
    x: float
    y: float
    w: float
    h: float
    confidence: float
    track_id: int
    person_id: str | None = None

    @property
    def named(self) -> bool:
        return self.person_id is not None


def _containment(inner: tuple[float, float, float, float],
                 outer: tuple[float, float, float, float]) -> float:
    """How much of `inner` lies inside `outer`, 0..1. Both are x1,y1,x2,y2."""
    ax1, ay1, ax2, ay2 = inner
    bx1, by1, bx2, by2 = outer

    ix1, iy1 = max(ax1, bx1), max(ay1, by1)
    ix2, iy2 = min(ax2, bx2), min(ay2, by2)
    if ix2 <= ix1 or iy2 <= iy1:
        return 0.0

    area = (ax2 - ax1) * (ay2 - ay1)
    return 0.0 if area <= 0 else ((ix2 - ix1) * (iy2 - iy1)) / area


class AppearanceTracker:
    """`loiterwatch.IdentityStitcher`, wrapped for VisionGuard.

    Thread-safe: one thread per camera calls `observe`, and the recognition
    worker calls `bind` from another.
    """

    def __init__(self, min_similarity: float = 0.72,
                 cross_min_similarity: float | None = None,
                 max_gap_seconds: float = 900.0, **options) -> None:
        from loiterwatch.identity import IdentityStitcher

        # loiterwatch's own defaults are used as-is, on purpose: they were
        # tuned against real footage and this wrapper is not the place to
        # second-guess them. Everything stays overridable through **options.
        #
        # The one knob worth knowing about: cross_min_similarity sits 0.10
        # BELOW the same-camera bar by default, because a lens change costs
        # some score. loiterwatch's README names that discount as the biggest
        # single source of one number landing on two people. If cross-camera
        # identities start getting mixed up, raise it to match min_similarity.
        kwargs = dict(min_similarity=min_similarity, max_gap_s=max_gap_seconds)
        if cross_min_similarity is not None:
            kwargs["cross_min_similarity"] = cross_min_similarity
        self._stitcher = IdentityStitcher(**kwargs, **options)

        self._names: dict[str, tuple[str, float, float]] = {}
        self._lock = threading.RLock()
        self.observations = 0

    # -- seeing -------------------------------------------------------------

    def observe(self, camera_id: str, frame, tracks, at: datetime | None = None
                ) -> list[AppearanceSighting]:
        """Map this camera's raw track IDs onto stable identities.

        `tracks` are `vg.infer.tracking.Track` - pixel boxes, which is what the
        stitcher needs because it reads the clothing inside them.
        """
        from loiterwatch.live import Detection

        at = at or datetime.now(timezone.utc)
        now = at.timestamp()
        if not tracks:
            return []

        detections = [
            Detection(track_id=str(t.track_id), box=t.box, confidence=t.confidence)
            for t in tracks
        ]

        with self._lock:
            result = self._stitcher.update(frame, detections, now, camera=camera_id)

        height, width = frame.shape[:2]
        out: list[AppearanceSighting] = []
        for track, det in zip(tracks, result.detections):
            stable_id = str(getattr(det, "stable_id", None) or det.track_id)
            x, y, w, h = track.to_fractions(width, height)
            out.append(AppearanceSighting(
                stable_id=stable_id,
                camera_id=camera_id,
                at=at,
                x=x, y=y, w=w, h=h,
                confidence=track.confidence,
                track_id=track.track_id,
                person_id=self.whois(stable_id, now),
            ))

        self.observations += len(out)
        return out

    # -- naming -------------------------------------------------------------

    def bind_face(self, sightings, face_box, person_id: str, score: float,
                  at: datetime | None = None) -> str | None:
        """A face was recognised - attach that name to the body wearing it.

        `face_box` is in fractions, matching what the API and the recognition
        worker already speak. Returns the stable id that was named, or None
        when no body clearly contains the face.

        Ambiguity is refused: if two bodies both contain the face, we do not
        know whose it is, and guessing would attach a name to the wrong person
        for the rest of the day.
        """
        fx, fy, fw, fh = face_box
        face = (fx, fy, fx + fw, fy + fh)

        candidates = [
            s for s in sightings
            if _containment(face, (s.x, s.y, s.x + s.w, s.y + s.h)) >= MIN_FACE_CONTAINMENT
        ]
        if len(candidates) != 1:
            if len(candidates) > 1:
                log.debug("face sits inside %d bodies; not binding", len(candidates))
            return None

        self.bind(candidates[0].stable_id, person_id, score, at)
        return candidates[0].stable_id

    def bind(self, stable_id: str, person_id: str, score: float = 1.0,
             at: datetime | None = None) -> None:
        """Attach a name to an appearance identity.

        A better-scoring face wins. Without that, the first weak match of the
        day would hold the identity against every later, clearer view.
        """
        now = (at or datetime.now(timezone.utc)).timestamp()
        with self._lock:
            existing = self._names.get(stable_id)
            if existing is not None:
                _, prior_score, bound_at = existing
                if now - bound_at < BINDING_TTL_SECONDS and prior_score > score:
                    return
            self._names[stable_id] = (person_id, score, now)
        log.info("appearance %s is %s (%.2f)", stable_id, person_id, score)

    def whois(self, stable_id: str, now: float | None = None) -> str | None:
        """The name on this identity, if it is still fresh."""
        now = now if now is not None else datetime.now(timezone.utc).timestamp()
        with self._lock:
            entry = self._names.get(stable_id)
            if entry is None:
                return None
            person_id, _, bound_at = entry
            if now - bound_at > BINDING_TTL_SECONDS:
                del self._names[stable_id]
                return None
            return person_id

    def identities_for(self, person_id: str, now: float | None = None) -> list[str]:
        """Every appearance identity currently carrying this name.

        More than one is normal and expected: somebody re-identified after a
        long absence gets a fresh identity, which is then named again the next
        time their face is seen.

        `now` is injectable for the same reason it is on `whois`: without it a
        test that pins a fixed timestamp starts passing or failing depending on
        what time of day it is run, which is worse than having no test.
        """
        now = now if now is not None else datetime.now(timezone.utc).timestamp()
        with self._lock:
            return sorted(
                sid for sid, (pid, _, bound) in self._names.items()
                if pid == person_id and now - bound <= BINDING_TTL_SECONDS
            )

    # -- operator corrections ----------------------------------------------

    def correct(self, stable_id: str, at: datetime | None = None) -> str | None:
        """The operator says this is not who we claim. Issues a fresh identity."""
        now = (at or datetime.now(timezone.utc)).timestamp()
        with self._lock:
            self._names.pop(stable_id, None)
            return self._stitcher.correct(stable_id, now)

    def merge(self, id_a: str, id_b: str, at: datetime | None = None) -> str | None:
        """The operator says these two are one person. Folds them together."""
        now = (at or datetime.now(timezone.utc)).timestamp()
        with self._lock:
            return self._stitcher.merge(id_a, id_b, now)

    def holders(self, stable_id: str) -> set:
        """Which cameras are showing this identity right now."""
        with self._lock:
            return self._stitcher.holders(stable_id)

    @property
    def stats(self) -> dict:
        with self._lock:
            return {
                "observations": self.observations,
                "named_identities": len(self._names),
            }
