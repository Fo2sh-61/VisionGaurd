"""Identity stitching: keep one person's ID across leaving and re-entering.

Trackers retire an ID once a person is gone, so a re-entry arrives as a stranger:
every dwell timer resets and `repeat_entry` never counts past one. This layer
sits between the tracker and the engine, remembers what recent people looked
like, and hands back the original ID when someone returns.

What it matches on, per body half:
  * hue/saturation histogram -- the colour of the clothing
  * brightness histogram     -- separates black from white from grey, which hue
                                cannot do at all (and most jackets are dark)
plus body shape (height:width) as a weak tie-breaker.

Accuracy comes mostly from refusing to answer when the evidence is bad:

  * **Truncated people are not matched.** Someone walking in from the side is
    half outside the frame for the first few frames -- exactly when we want to
    identify them, and exactly when the crop is worthless. Those frames are
    scored for quality and skipped.
  * **Ambiguity is rejected.** If the best and second-best candidates are close
    together, no match is made. Two similar-looking people are the case that
    produces confidently wrong answers.
  * **Evidence accumulates.** The decision is revisited over a short probation
    window as better views arrive, rather than being fixed by whatever the first
    frame happened to look like.

A false merge invents dwell time for a person who was not standing there, so
every one of these trades recall for precision on purpose.
"""
from __future__ import annotations

import json
from dataclasses import dataclass, field
from typing import Any, Callable, Protocol, Sequence

import numpy as np

# how much each cue contributes to the final score
WEIGHT_UPPER = 0.45
WEIGHT_LOWER = 0.35
WEIGHT_SHAPE = 0.20

# within a region, colour matters more than brightness but brightness is what
# rescues black/white/grey clothing, where hue is pure noise
HS_WEIGHT = 0.80
TONE_WEIGHT = 0.45


class Appearance(Protocol):
    def signature(self, frame, box: tuple[int, int, int, int]) -> Any: ...


def cosine(a: np.ndarray, b: np.ndarray) -> float:
    return float(np.dot(a, b))  # both are unit vectors


def _normalise(vec: np.ndarray) -> np.ndarray | None:
    norm = float(np.linalg.norm(vec))
    return None if norm == 0 else vec / norm


def _region_vector(frame, rect, hs_bins=(12, 8), tone_bins: int = 8,
                   min_pixels: int = 150):
    """Colour + brightness descriptor for one body region.

    Hue/saturation is computed only over colourful pixels, so a grey wall behind
    a person does not vote. Brightness is measured in absolute terms, which is
    deliberate: two attempts to make it illumination-invariant were measured and
    both lost more than they gained. Grey-world normalisation divides out the
    garment's own colour, because a person-shaped crop is mostly garment rather
    than a fair sample of the scene. Normalising brightness by the crop mean
    fixed shade-versus-sunlight but collapsed the dark/light distinction that
    separates a black coat from a white one, raising 'completely different
    outfit' from 0.20 to 0.48.
    """
    import cv2

    h, w = frame.shape[:2]
    x1, y1, x2, y2 = rect
    x1, x2 = max(0, min(w - 1, int(x1))), max(0, min(w, int(x2)))
    y1, y2 = max(0, min(h - 1, int(y1))), max(0, min(h, int(y2)))
    if x2 - x1 < 4 or y2 - y1 < 4:
        return None
    crop = frame[y1:y2, x1:x2]
    if crop.size < min_pixels:
        return None

    hsv = cv2.cvtColor(crop, cv2.COLOR_BGR2HSV)
    colourful = cv2.inRange(hsv, (0, 50, 40), (180, 255, 255))
    hs = cv2.calcHist([hsv], [0, 1], colourful, list(hs_bins), [0, 180, 0, 256])
    tone = cv2.calcHist([hsv], [2], None, [tone_bins], [0, 256])

    hs_vec = _normalise(hs.flatten().astype(np.float32))
    tone_vec = _normalise(tone.flatten().astype(np.float32))
    if hs_vec is None:
        hs_vec = np.zeros(hs_bins[0] * hs_bins[1], dtype=np.float32)
    if tone_vec is None:
        tone_vec = np.zeros(tone_bins, dtype=np.float32)
    return _normalise(np.concatenate([hs_vec * HS_WEIGHT, tone_vec * TONE_WEIGHT]))


def detection_quality(frame_shape, box, confidence: float = 1.0,
                      good_height: int = 90, margin: int = 3) -> float:
    """0-1 estimate of how much this crop can be trusted for identification.

    Truncation is the dominant term. A person entering from the left is a
    vertical sliver of themselves, and matching on that produces exactly the
    wrong-ID behaviour this whole module exists to prevent.
    """
    h, w = frame_shape[:2]
    x1, y1, x2, y2 = box
    bw, bh = x2 - x1, y2 - y1
    if bw <= 0 or bh <= 0:
        return 0.0

    visible = (max(0, min(w, x2) - max(0, x1)) * max(0, min(h, y2) - max(0, y1)))
    inside = visible / float(bw * bh)
    size = min(1.0, bh / float(good_height))
    quality = inside * size * min(1.0, confidence / 0.5)

    # side truncation destroys the descriptor; top/bottom only clips head or feet
    if x1 <= margin or x2 >= w - margin:
        quality *= 0.25
    if y1 <= margin:
        quality *= 0.80
    if y2 >= h - margin:
        quality *= 0.85
    return float(max(0.0, min(1.0, quality)))


@dataclass
class Signature:
    """One observed view of a person: what they wore and how they were built."""

    upper: np.ndarray | None = None
    lower: np.ndarray | None = None
    aspect: float | None = None

    @property
    def usable(self) -> bool:
        return self.upper is not None or self.lower is not None

    def to_dict(self) -> dict:
        return {
            "upper": None if self.upper is None else self.upper.tolist(),
            "lower": None if self.lower is None else self.lower.tolist(),
            "aspect": self.aspect,
        }

    @classmethod
    def from_dict(cls, raw: dict) -> "Signature":
        def vec(v):
            return None if v is None else np.asarray(v, dtype=np.float32)
        return cls(vec(raw.get("upper")), vec(raw.get("lower")), raw.get("aspect"))


def average_signatures(signatures: Sequence) -> Any:
    """Blend several views of one person into a single cleaner descriptor.

    Matching on one frame means matching on one frame's noise: motion blur, a
    passing shadow, an arm across the torso. Averaging the first few good views
    of a new track before deciding who they are is the cheapest accuracy win
    available, because the noise is uncorrelated between frames and the signal
    is not.
    """
    usable = [s for s in signatures if s is not None]
    if not usable:
        return None
    if len(usable) == 1:
        return usable[0]
    if isinstance(usable[0], np.ndarray):
        stacked = [s for s in usable if s.shape == usable[0].shape]
        return _normalise(np.sum(stacked, axis=0))

    def blend(attr: str):
        vectors = [getattr(s, attr) for s in usable if getattr(s, attr) is not None]
        if not vectors:
            return None
        shape = vectors[0].shape
        vectors = [v for v in vectors if v.shape == shape]
        return _normalise(np.sum(vectors, axis=0))

    aspects = [s.aspect for s in usable if s.aspect]
    return Signature(
        blend("upper"), blend("lower"),
        aspect=float(np.median(aspects)) if aspects else None,
    )


def shape_similarity(a: float | None, b: float | None) -> float | None:
    """1.0 for identical build, decaying with the difference in aspect ratio."""
    if a is None or b is None or a <= 0 or b <= 0:
        return None
    ratio = max(a, b) / min(a, b)
    return float(np.exp(-(ratio - 1.0) * 2.0))


def similarity(a, b, use_shape: bool = True,
               weights: tuple[float, float, float] | None = None) -> float | None:
    """Weighted match score, renormalised over whichever cues both sides have.

    Returns None when there is nothing comparable, so callers can distinguish
    "different person" from "cannot tell".

    `use_shape=False` drops the build cue. Set it when comparing across
    cameras: height:width depends heavily on how the camera is mounted, so the
    same person filmed head-on and from an overhead corner has genuinely
    different proportions, and scoring that as a mismatch buries a good colour
    match under a bogus penalty.
    """
    # plain vectors (a custom Appearance may return one) compare directly
    if isinstance(a, np.ndarray) or isinstance(b, np.ndarray):
        if not (isinstance(a, np.ndarray) and isinstance(b, np.ndarray)):
            return None
        return cosine(a, b) if a.shape == b.shape else None

    if a is None or b is None:
        return None

    w_upper, w_lower, w_shape = weights or (WEIGHT_UPPER, WEIGHT_LOWER,
                                            WEIGHT_SHAPE)

    parts: list[tuple[float, float]] = []
    shape_only = True
    if a.upper is not None and b.upper is not None and a.upper.shape == b.upper.shape:
        parts.append((w_upper, cosine(a.upper, b.upper)))
        shape_only = False
    if a.lower is not None and b.lower is not None and a.lower.shape == b.lower.shape:
        parts.append((w_lower, cosine(a.lower, b.lower)))
        shape_only = False
    if use_shape:
        shape = shape_similarity(a.aspect, b.aspect)
        if shape is not None:
            parts.append((w_shape, shape))

    if not parts:
        return None
    # shape alone is far too weak to justify a merge -- lots of people are
    # roughly the same build, so require at least one colour cue
    if shape_only:
        return None
    total_weight = sum(w for w, _ in parts)
    if total_weight <= 0:
        return None
    return sum(w * s for w, s in parts) / total_weight


class BodySignature:
    """Upper/lower body colour plus build. The default appearance model.

    Regions come from the box rather than a segmentation mask: torso is the
    middle 60% horizontally and 15-50% vertically, legs are 55-90%. Heads and
    feet are excluded because they are mostly background and floor.
    """

    def __init__(self, hs_bins: tuple[int, int] = (12, 8), tone_bins: int = 8,
                 min_pixels: int = 150) -> None:
        self.hs_bins = hs_bins
        self.tone_bins = tone_bins
        self.min_pixels = min_pixels

    def signature(self, frame, box) -> Signature | None:
        h = frame.shape[0]
        x1, y1, x2, y2 = box
        bw, bh = x2 - x1, y2 - y1
        if bw <= 0 or bh <= 0:
            return None
        left, right = x1 + bw * 0.20, x1 + bw * 0.80

        def region(top_frac, bottom_frac):
            return _region_vector(
                frame, (left, y1 + bh * top_frac, right, y1 + bh * bottom_frac),
                self.hs_bins, self.tone_bins, self.min_pixels,
            )

        upper = region(0.15, 0.50)
        # if the feet are cut off by the frame edge, the "legs" band is really
        # whatever is above them -- better to report nothing than something wrong
        lower = None if y2 >= h - 3 else region(0.55, 0.90)
        sig = Signature(upper, lower, aspect=bh / bw if bw else None)
        return sig if sig.usable else None


class ColorHistogram(BodySignature):
    """Torso-only colour, kept for callers that want the simpler cue."""

    def signature(self, frame, box):
        sig = super().signature(frame, box)
        return None if sig is None else sig.upper


@dataclass
class Identity:
    stable_id: str
    gallery: list = field(default_factory=list)
    last_seen: float = 0.0
    first_seen: float = 0.0
    samples: int = 1
    relinks: int = 0
    #: which camera saw them last -- lets a match skip the anti-jitter delay
    #: when the sighting comes from a *different* camera
    last_camera: str | None = None
    #: small BGR crop of the best view seen, kept only in memory so a human can
    #: look at what the matcher was actually comparing. Never serialised.
    thumb: Any = None
    thumb_quality: float = 0.0

    def best_match(self, signature, use_shape: bool = True,
                   weights: tuple[float, float, float] | None = None) -> float | None:
        scores = [s for s in (similarity(signature, g, use_shape, weights)
                              for g in self.gallery)
                  if s is not None]
        return max(scores) if scores else None

    def to_dict(self) -> dict:
        def enc(g):
            return g.tolist() if isinstance(g, np.ndarray) else g.to_dict()
        return {
            "stable_id": self.stable_id,
            "gallery": [enc(g) for g in self.gallery],
            "last_seen": self.last_seen,
            "first_seen": self.first_seen,
            "samples": self.samples,
            "relinks": self.relinks,
            "last_camera": self.last_camera,
        }

    @classmethod
    def from_dict(cls, raw: dict) -> "Identity":
        gallery = [
            np.asarray(g, dtype=np.float32) if isinstance(g, list)
            else Signature.from_dict(g)
            for g in raw.get("gallery", [])
        ]
        return cls(
            raw["stable_id"], gallery, raw.get("last_seen", 0.0),
            raw.get("first_seen", 0.0), raw.get("samples", 1), raw.get("relinks", 0),
            raw.get("last_camera"),
        )


@dataclass
class StitchResult:
    """Detections with stable IDs, plus what just happened, for the overlay."""

    detections: list
    relinked: dict[str, str] = field(default_factory=dict)  # stable_id -> old raw id


class IdentityStitcher:
    def __init__(
        self,
        appearance: Appearance | None = None,
        max_gap_s: float = 900.0,
        min_similarity: float = 0.72,
        min_absence_s: float = 0.5,
        gallery_size: int = 12,
        novelty: float = 0.93,
        memory: int = 256,
        min_quality: float = 0.55,
        margin: float = 0.05,
        probation_samples: int = 5,
        probation_window_s: float = 5.0,
        min_evidence: int = 2,
        cross_min_similarity: float | None = None,
        recent_absence_s: float = 20.0,
        recent_bonus: float = 0.08,
        quality_floor: float = 0.15,
        low_quality_penalty: float = 0.15,
        concurrent_min_similarity: float | None = None,
        cross_margin: float | None = None,
        cross_min_evidence: int | None = None,
        concurrent_confirmations: int = 3,
        confirm_window_s: float = 2.0,
        holder_window_s: float = 2.0,
        adaptive_weights: bool = True,
        min_population: int = 4,
        weights_refresh_s: float = 5.0,
        id_source: "Callable[[], str] | None" = None,
        **legacy: Any,
    ) -> None:
        self.appearance = appearance or BodySignature()
        #: mint IDs from here instead of a local counter when several cameras
        #: share one identity pool -- see SharedIdentityStore.mint_id, which
        #: hands out IDs under a lock so two cameras never collide
        self.id_source = id_source
        self.max_gap_s = float(max_gap_s)
        self.min_similarity = float(min_similarity)
        #: refuse to re-link someone who vanished only an instant ago -- that is
        #: tracker jitter, and `exit_grace_s` already covers it
        self.min_absence_s = float(min_absence_s)
        #: views kept per person; more views survive more pose/lighting change
        self.gallery_size = int(gallery_size)
        #: only store a view that differs from what we already have
        self.novelty = float(novelty)
        self.memory = int(memory)
        #: crops below this quality are not used to match or to learn from
        self.min_quality = float(min_quality)
        #: best must beat runner-up by this much, or the answer is "don't know"
        self.margin = float(margin)
        #: good views to collect before the identity decision is frozen
        self.probation_samples = int(probation_samples)
        #: ...and how long to keep trying. Both must be satisfied before a
        #: track's identity is final: a person who walks into camera B before
        #: camera A has learned them needs a second chance a moment later, and
        #: five frames at 30fps is a sixth of a second.
        self.probation_window_s = float(probation_window_s)
        #: an identity needs this many stored views before others can match it
        self.min_evidence = int(min_evidence)
        #: separate, lower bar for matching a person last seen on another
        #: camera -- see _match for why
        self.cross_min_similarity = float(
            cross_min_similarity if cross_min_similarity is not None
            else max(0.0, self.min_similarity - 0.10)
        )
        #: an absence shorter than this counts as evidence of sameness
        self.recent_absence_s = float(recent_absence_s)
        self.recent_bonus = float(recent_bonus)
        #: below this a crop is not even looked at; between it and min_quality
        #: a crop may match but only against a stricter bar, and never learns
        self.quality_floor = float(quality_floor)
        self.low_quality_penalty = float(low_quality_penalty)
        #: the bar for adopting an identity another camera is showing *right
        #: now*. Deliberately not discounted: sharing an in-use ID is how two
        #: different people end up on one number.
        self.concurrent_min_similarity = float(
            concurrent_min_similarity if concurrent_min_similarity is not None
            else self.min_similarity
        )
        #: The ambiguity margin, cross-camera. Deliberately wider than the
        #: same-camera one, and this is where cross-camera precision is bought.
        #: Raising the *absolute* bar to stop false merges also stops the true
        #: ones -- one unchanged person really does score lower through a
        #: second lens. What separates the two cases is not the score, it is
        #: the gap to the runner-up: a genuine match wins its comparison
        #: outright, a lookalike wins it by a whisker. So the absolute bar is
        #: left low enough for the true match to clear, and the *relative* bar
        #: is raised until only unambiguous winners get through.
        self.cross_margin = float(
            cross_margin if cross_margin is not None else self.margin * 2.0)
        #: observations an identity needs before a *different* camera may claim
        #: it. A gallery built from three frames describes a blur, not a person
        self.cross_min_evidence = int(
            cross_min_evidence if cross_min_evidence is not None
            else self.min_evidence)
        #: consecutive observations that must agree before a track may take an
        #: identity another camera is showing *right now*. Real overlap wins
        #: every frame; a lookalike wins one and loses the next.
        self.concurrent_confirmations = int(concurrent_confirmations)
        #: a confirmation streak older than this is stale and starts over
        self.confirm_window_s = float(confirm_window_s)
        #: how recently a camera must have shown an identity to still count as
        #: holding it. Tracker bookkeeping survives for `max_gap_s`, so without
        #: this "held elsewhere" would mean "seen elsewhere in the last fifteen
        #: minutes" -- which quietly applied the concurrent bar to people who
        #: had long since walked out of the other camera's view.
        self.holder_window_s = float(holder_window_s)

        self.raw_to_stable: dict[str, str] = {}
        self.identities: dict[str, Identity] = {}
        #: raw_id -> [good samples seen, first seen at]
        self._probation: dict[str, list[float]] = {}
        #: raw_id -> recent good signatures, averaged before deciding identity
        self._pending_views: dict[str, list] = {}
        #: raw_id -> when that tracker ID was last seen, so retired ones can be
        #: cleaned up. Trackers hand out IDs forever; without this the
        #: bookkeeping grows for the lifetime of the process.
        self._raw_last_seen: dict[str, float] = {}
        #: raw_id -> [candidate identity, times it has won, when it last won]
        #: while a track is trying to take an identity another camera holds
        self._confirming: dict[str, list] = {}
        self._next_id = 1
        self.merges = 0
        self.rejected_ambiguous = 0
        self.rejected_unconfirmed = 0
        self.skipped_low_quality = 0
        #: set when a match was declined because two people scored alike --
        #: the usual cause is several people in the same uniform
        self.last_reject_reason: str | None = None
        #: identity pairs an operator has told us are different people, as
        #: frozenset({a, b}). Corrections are permanent for the session: the
        #: system was already confident and wrong, so nothing it learns later
        #: should be allowed to re-merge them.
        self.forbidden: set[frozenset] = set()
        self.corrections = 0
        self.manual_merges = 0
        #: frozenset({cam_a, cam_b}) -> similarity slack learned from merges the
        #: operator confirmed, so a pair of cameras that render people
        #: differently gets easier to match over time instead of staying broken
        self.pair_offsets: dict[frozenset, float] = {}
        self.pair_samples: dict[frozenset, int] = {}
        self.max_pair_offset = 0.25
        #: re-weight cues by how well they separate the people actually seen
        self.adaptive_weights = bool(adaptive_weights)
        self.min_population = int(min_population)
        self.weights_refresh_s = float(weights_refresh_s)
        self._weights_cache: tuple[float, float, float] | None = None
        self._weights_at: float | None = None
        #: a spread of distinct-looking people recently observed, used only to
        #: measure which cues separate them. Near-duplicates are not stored, so
        #: one person lingering in view cannot dominate the sample.
        self._population: list = []
        self.population_size = 48
        #: crop quality of the most recent detection considered, for diagnostics
        self.last_quality: float | None = None
        #: crop of the most recent detection, so a failed match can be shown
        self.last_thumb: Any = None
        #: best candidate considered on the last _match, matched or not --
        #: purely for diagnostics, so you can see what scores you are getting
        self.last_best: tuple[float, str] | None = None
        #: and the one behind it. The gap between these two is what actually
        #: decides a cross-camera match, so it is the number to tune against
        self.last_runner_up: tuple[float, str] | None = None

    # -- public -----------------------------------------------------------
    def update(self, frame, detections: Sequence, now: float,
               camera: str | None = None) -> StitchResult:
        """Map this camera's tracker IDs onto stable identities.

        `camera` matters when one stitcher serves several feeds: tracker IDs are
        only unique *within* a camera (every tracker starts counting at 1), so
        they are namespaced per camera before use.
        """
        from .live import Detection  # local import avoids a cycle

        out: list = []
        relinked: dict[str, str] = {}
        keys = {id(d): self._key(camera, d.track_id) for d in detections}
        # people already accounted for in THIS frame cannot also be someone
        # else in it -- but a person on another camera is fair game
        claimed = {
            self.raw_to_stable[keys[id(d)]]
            for d in detections
            if keys[id(d)] in self.raw_to_stable
        }

        for det in detections:
            raw_key = keys[id(det)]
            quality = detection_quality(frame.shape, det.box,
                                        getattr(det, "confidence", 1.0))
            self.last_quality = quality

            # A poor crop is not worthless, it is just weak evidence -- and
            # re-entering the frame *guarantees* poor crops, because the person
            # arrives truncated at an edge. Discarding those frames outright
            # meant the one moment we most need an answer was the one moment we
            # refused to look. So: use them to match, but demand a much better
            # score, and never let them into the gallery where they would
            # corrupt what we know the person looks like.
            signature = None
            trusted = False
            if quality >= self.quality_floor:
                signature = self.appearance.signature(frame, det.box)
                trusted = quality >= self.min_quality
            if signature is None or not trusted:
                self.skipped_low_quality += 1
            if trusted and signature is not None:
                # sampled BEFORE matching: the second person to walk past must
                # already be able to tell that the first one's shirt looks
                # identical, or they are merged before the statistic exists
                self._sample_population(signature)

            thumb = None
            if signature is not None and quality >= self.min_quality:
                thumb = self._thumbnail(frame, det.box)

            stable = self.raw_to_stable.get(raw_key)
            if stable is None:
                # start as a fresh identity so output is stable from frame one;
                # probation may replace it once a trustworthy view arrives
                stable = self._create(signature, now, camera)
                self.raw_to_stable[raw_key] = stable
                self._probation[raw_key] = [0, now]

            if signature is not None and raw_key in self._probation:
                # decide from the average of this track's good views so far,
                # not from whichever single frame happened to arrive
                views = self._pending_views.setdefault(raw_key, [])
                views.append(signature)
                if len(views) > 8:
                    views.pop(0)
                evidence = average_signatures(views)
                match, _cross = self._match(
                    evidence, now, claimed | {stable}, camera, current=stable,
                    penalty=0.0 if trusted else self.low_quality_penalty)
                # taking an identity another camera is showing this instant is
                # the one decision that puts two people on one number, so it is
                # the one decision not made from a single frame
                if match is not None and self._is_concurrent(match, camera, now):
                    match = self._confirm(raw_key, match, now)
                old_raw = None
                if match is not None:
                    old_raw = self._retire_raw(match, camera)
                    self._confirming.pop(raw_key, None)
                    self._absorb(stable, match)
                    self.raw_to_stable[raw_key] = match
                    self.identities[match].relinks += 1
                    self.merges += 1
                    relinked[match] = old_raw or "?"
                    stable = match
                    del self._probation[raw_key]
                    self._pending_views.pop(raw_key, None)
                else:
                    state = self._probation[raw_key]
                    state[0] += 1
                    # close probation only when we have both enough good views
                    # AND enough elapsed time for another camera to have seen
                    # this person too -- and never while a match is midway
                    # through proving itself, or the proof could never land
                    if (state[0] >= self.probation_samples
                            and now - state[1] >= self.probation_window_s
                            and raw_key not in self._confirming):
                        del self._probation[raw_key]
                        self._pending_views.pop(raw_key, None)

            claimed.add(stable)
            self._raw_last_seen[raw_key] = now
            # only trustworthy crops teach the gallery what this person looks like
            self._touch(stable, signature if trusted else None, now, camera)
            identity = self.identities.get(stable)
            if identity is not None and thumb is not None and \
                    quality >= identity.thumb_quality:
                identity.thumb, identity.thumb_quality = thumb, quality
            self.last_thumb = thumb
            out.append(Detection(stable, det.box, det.confidence))

        self._prune(now)
        return StitchResult(out, relinked)

    def correct(self, wrong_id: str, now: float) -> str | None:
        """Operator says: whoever is wearing this ID right now is not that person.

        Splits the live track off onto a brand new identity and bans the pair
        from ever being merged again this session. Returns the new ID, or None
        if `wrong_id` is not currently on screen.

        The banned pair is the important half. Simply re-running the matcher
        would reproduce the same answer -- it already thought this was the best
        candidate. Recording "these two are different people" is the only thing
        that changes the outcome, and it is information only you have.
        """
        raw_keys = [raw for raw, stable in self.raw_to_stable.items()
                    if stable == wrong_id]
        if not raw_keys:
            return None

        old = self.identities.get(wrong_id)
        new_id = self._create(None, now, old.last_camera if old else None)
        fresh = self.identities[new_id]

        # the live track keeps the views it has actually contributed, so the
        # new identity starts with a real description rather than nothing
        for raw_key in raw_keys:
            self.raw_to_stable[raw_key] = new_id
            for view in self._pending_views.get(raw_key, []):
                fresh.gallery.append(view)
            # give it another probation window to find its true match, with no
            # half-finished claim carried over from the identity we just left
            self._probation[raw_key] = [0, now]
            self._confirming.pop(raw_key, None)
            self._pending_views[raw_key] = list(
                self._pending_views.get(raw_key, []))

        if not fresh.gallery and old is not None and old.gallery:
            # nothing pending: take the most recent view from the identity we
            # are splitting away from, which is most likely to be this person
            fresh.gallery.append(old.gallery[-1])
            if len(old.gallery) > 1:
                old.gallery.pop()

        self.forbidden.add(frozenset({wrong_id, new_id}))
        self.corrections += 1
        return new_id

    def merge(self, id_a: str, id_b: str, now: float) -> str | None:
        """Operator says these two identities are one person.

        The immediate effect is that one ID wins. The lasting effect is bigger:
        the surviving gallery now holds views from *both* cameras, so the next
        time either camera sees this person it compares against a view taken
        from its own angle instead of the other camera's. One merge makes the
        pair self-sustaining.

        A per-camera-pair offset is also learned. If the operator says a 0.38
        match was correct when the bar was 0.50, that gap is real information
        about how far apart these two cameras render the same person, and it
        is applied to future comparisons between them.
        """
        if id_a == id_b:
            return None
        first, second = self.identities.get(id_a), self.identities.get(id_b)
        if first is None or second is None:
            return None

        # an explicit instruction overrides an earlier correction
        self.forbidden.discard(frozenset({id_a, id_b}))

        keeper, loser = ((first, second)
                         if first.first_seen <= second.first_seen
                         else (second, first))

        self._learn_pair_offset(keeper, loser)

        for view in loser.gallery:
            if len(keeper.gallery) >= self.gallery_size:
                break
            best = keeper.best_match(view)
            if best is not None and best >= self.novelty:
                continue  # a near-duplicate of something we already hold
            keeper.gallery.append(view)

        keeper.samples += loser.samples
        keeper.relinks += loser.relinks
        keeper.first_seen = min(keeper.first_seen or now, loser.first_seen or now)
        keeper.last_seen = max(keeper.last_seen, loser.last_seen)

        for raw_key, stable in list(self.raw_to_stable.items()):
            if stable == loser.stable_id:
                self.raw_to_stable[raw_key] = keeper.stable_id
                # let it settle onto the merged identity rather than re-deciding
                self._probation.pop(raw_key, None)
                self._pending_views.pop(raw_key, None)
                self._confirming.pop(raw_key, None)

        for pair in {p for p in self.forbidden if loser.stable_id in p}:
            other = next(iter(pair - {loser.stable_id}), None)
            self.forbidden.discard(pair)
            if other is not None and other != keeper.stable_id:
                self.forbidden.add(frozenset({keeper.stable_id, other}))

        del self.identities[loser.stable_id]
        self.manual_merges += 1
        return keeper.stable_id

    def _learn_pair_offset(self, keeper: Identity, loser: Identity) -> None:
        """Record how much slack this camera pair needs, from a confirmed match."""
        cam_a, cam_b = keeper.last_camera, loser.last_camera
        if not cam_a or not cam_b or cam_a == cam_b:
            return
        scores = [s for s in (similarity(x, y, use_shape=False)
                              for x in keeper.gallery for y in loser.gallery)
                  if s is not None]
        if not scores:
            return
        shortfall = self.cross_min_similarity - max(scores)
        if shortfall <= 0:
            return  # they already scored well enough; nothing to learn
        pair = frozenset({cam_a, cam_b})
        seen = self.pair_samples.get(pair, 0)
        previous = self.pair_offsets.get(pair, 0.0)
        # running mean, so one generous merge cannot collapse the threshold
        blended = (previous * seen + shortfall) / (seen + 1)
        self.pair_offsets[pair] = min(blended, self.max_pair_offset)
        self.pair_samples[pair] = seen + 1

    def _is_forbidden(self, a: str, b: str) -> bool:
        return frozenset({a, b}) in self.forbidden

    @staticmethod
    def _thumbnail(frame, box, size: tuple[int, int] = (72, 160)):
        """The crop as a human would see it, for eyeballing a bad match."""
        import cv2

        h, w = frame.shape[:2]
        x1, y1, x2, y2 = box
        x1, x2 = max(0, min(w - 1, int(x1))), max(0, min(w, int(x2)))
        y1, y2 = max(0, min(h - 1, int(y1))), max(0, min(h, int(y2)))
        if x2 - x1 < 4 or y2 - y1 < 4:
            return None
        try:
            return cv2.resize(frame[y1:y2, x1:x2], size)
        except Exception:
            return None

    @staticmethod
    def _key(camera: str | None, raw_id: str) -> str:
        return raw_id if camera is None else f"{camera}\x00{raw_id}"

    def stable_id(self, raw_id: str, camera: str | None = None) -> str:
        return self.raw_to_stable.get(self._key(camera, raw_id), raw_id)

    # -- persistence ------------------------------------------------------
    def save(self, path: str) -> None:
        """Write the gallery so IDs survive a restart."""
        payload = {
            "version": 1,
            "next_id": self._next_id,
            "identities": [i.to_dict() for i in self.identities.values()],
        }
        with open(path, "w", encoding="utf-8") as handle:
            json.dump(payload, handle)

    def load(self, path: str) -> int:
        """Restore a saved gallery. Returns how many identities were read.

        Timestamps come back as they were written, so anything older than
        `max_gap_s` relative to the new session's clock is ignored on the first
        match attempt -- pass a large `max_gap_s` if you want yesterday's people
        to still be recognised today.
        """
        try:
            with open(path, "r", encoding="utf-8") as handle:
                payload = json.load(handle)
        except (FileNotFoundError, json.JSONDecodeError):
            return 0
        self.identities = {
            raw["stable_id"]: Identity.from_dict(raw)
            for raw in payload.get("identities", [])
        }
        self._next_id = max(int(payload.get("next_id", 1)), self._next_id)
        self.raw_to_stable.clear()  # tracker IDs from the old session are meaningless
        self._probation.clear()
        self._confirming.clear()
        return len(self.identities)

    # -- internals --------------------------------------------------------
    def _match(self, signature, now: float, claimed: set[str],
               camera: str | None = None, current: str | None = None,
               penalty: float = 0.0) -> tuple[str | None, bool]:
        """Best candidate, but only if it is unambiguously ahead of the rest.

        Returns the winner and whether that decision was made across cameras,
        because a cross-camera win is held to the wider ambiguity margin.
        """
        if signature is None:
            return None, False
        scored: list[tuple[float, str, bool]] = []   # cleared the absolute bar
        considered: list[tuple[float, str]] = []     # every comparable rival
        weights = self.cue_weights(now)
        for identity in self.identities.values():
            if identity.stable_id in claimed:
                continue  # that person is on screen right now
            if current is not None and self._is_forbidden(current,
                                                          identity.stable_id):
                continue  # an operator has told us these are different people
            # evidence is observations, not gallery size: someone who looked
            # identical for five minutes is well known despite storing one view
            if not identity.gallery or identity.samples < self.min_evidence:
                continue  # glimpsed too briefly to claim a match against
            gap = now - identity.last_seen
            if gap > self.max_gap_s:
                continue
            # the anti-jitter delay only makes sense within one camera. Across
            # cameras there is no jitter -- overlapping views legitimately show
            # the same person on both feeds at the same instant.
            same_camera = camera is None or identity.last_camera in (None, camera)
            if same_camera and gap < self.min_absence_s:
                continue

            # Cross-camera is a harder problem than the same camera twice:
            # different white balance, exposure and mounting angle all shift
            # the descriptor for one unchanged person. Drop the build cue and
            # accept a lower score rather than pretending the two are alike.
            score = identity.best_match(signature, use_shape=same_camera,
                                        weights=weights)
            if score is None:
                continue
            # Recorded before any of the bars below. A rival that finished a
            # hair under the threshold is not a non-event -- it is the whole
            # reason to distrust the winner, and the old code threw it away.
            considered.append((score, identity.stable_id))

            # A gallery this thin has not seen the person from enough angles to
            # be worth matching another camera against.
            if not same_camera and identity.samples < self.cross_min_evidence:
                continue

            threshold = (self.min_similarity if same_camera
                         else self.cross_min_similarity)
            if not same_camera and camera and identity.last_camera:
                # slack learned from merges the operator confirmed between
                # these two specific cameras
                threshold -= self.pair_offsets.get(
                    frozenset({camera, identity.last_camera}), 0.0)
            # Someone reappearing seconds after stepping out is far more likely
            # to be the person who just left than a stranger who happens to
            # resemble them. Treat a short absence as evidence in its own right.
            if gap <= self.recent_absence_s:
                threshold -= self.recent_bonus
            threshold += penalty   # weak crop: only a strong match counts

            # Handing out an ID that some *other* camera is showing right now
            # is the one mistake that puts two different people on one number.
            # Legitimate overlap still passes, it just has to earn it: no
            # discounts, and never on a weak crop.
            held_elsewhere = {c for c in self.holders(identity.stable_id, now)
                              if c is not None and c != camera}
            if held_elsewhere:
                if penalty > 0:
                    continue      # weak crop may not claim an in-use identity
                threshold = max(threshold, self.concurrent_min_similarity)
            if score >= threshold:
                scored.append((score, identity.stable_id, not same_camera))

        considered.sort(reverse=True)
        self.last_best = considered[0] if considered else None
        self.last_runner_up = considered[1] if len(considered) > 1 else None

        if not scored:
            self.last_reject_reason = "no candidate above threshold"
            return None, False
        scored.sort(reverse=True)
        best_score, best_id, best_cross = scored[0]

        # Two people look equally like this one; guessing is worse than not.
        # In practice this means matching uniforms: aprons and workwear make
        # several people genuinely indistinguishable to a colour histogram.
        #
        # The runner-up is the best *other* candidate that was comparable at
        # all, not merely the best one that also cleared the threshold. Those
        # are the same thing only while the threshold is high. Push the
        # cross-camera bar down -- which is exactly what makes one person keep
        # their ID across two lenses -- and the rivals drop below it one by
        # one, until the last candidate standing is unopposed by construction
        # and every ambiguous case sails through as certain.
        margin = self.cross_margin if best_cross else self.margin
        runner_up = next(((s, sid) for s, sid in considered if sid != best_id),
                         None)
        if runner_up is not None and best_score - runner_up[0] < margin:
            self.rejected_ambiguous += 1
            self.last_reject_reason = (
                f"ambiguous: #{best_id} {best_score:.2f} vs "
                f"#{runner_up[1]} {runner_up[0]:.2f} "
                f"(need {margin:.2f} clear)")
            return None, False
        self.last_reject_reason = None
        return best_id, best_cross

    def _retire_raw(self, stable_id: str, camera: str | None) -> str | None:
        """Drop the tracker ID this identity used to wear on THIS camera.

        Only this camera. Another camera holding the same identity is the
        overlapping case working correctly: one person, two simultaneous views.
        Deleting that mapping would orphan the other camera's live track, which
        would promptly invent a new identity and try to steal this one back.
        """
        old_raw = next(
            (raw for raw, stable in self.raw_to_stable.items()
             if stable == stable_id and self._camera_of(raw) == camera),
            None,
        )
        if old_raw is not None:
            del self.raw_to_stable[old_raw]
            self._probation.pop(old_raw, None)
            self._pending_views.pop(old_raw, None)
            self._raw_last_seen.pop(old_raw, None)
            self._confirming.pop(old_raw, None)
        return old_raw

    def _is_concurrent(self, stable_id: str, camera: str | None,
                       now: float) -> bool:
        """Is another camera showing this identity at this moment?

        Two signals, because neither covers both deployments. Live tracks in
        `raw_to_stable` are the direct answer, but they only exist for cameras
        in *this* process -- run one `live` per camera against a shared file and
        every identity from the other process looks unheld, which would switch
        this guard off exactly where cross-camera matching is hardest. The
        identity's own `last_camera`/`last_seen` survive the round trip through
        the file, so they answer for both.
        """
        if self.concurrent_confirmations <= 1:
            return False
        if any(c is not None and c != camera
               for c in self.holders(stable_id, now)):
            return True
        identity = self.identities.get(stable_id)
        return (identity is not None
                and identity.last_camera is not None
                and identity.last_camera != camera
                and now - identity.last_seen <= self.holder_window_s)

    def _confirm(self, raw_key: str, candidate: str, now: float) -> str | None:
        """Hold a claim on an in-use identity until it repeats itself.

        One frame of colour histogram is a coin with a heavy thumb on it. Two
        people in dark coats will trade the lead frame to frame; the person who
        genuinely is `candidate` wins every single one. Asking the same answer
        to come back `concurrent_confirmations` times in a row costs a tenth of
        a second at 30fps and throws away the coin-flips.

        The streak restarts if the candidate changes, or if more than
        `confirm_window_s` passes between two agreements -- the agreements have
        to come from one continuous look at the person, not from lucky frames
        collected over an evening. Timing each gap rather than the whole streak
        is deliberate: bounding the total span would mean a feed running at a
        frame a second could never finish confirming anything, and silently
        losing cross-camera matching on slow hardware is a worse failure than
        the one it would prevent.
        """
        streak = self._confirming.get(raw_key)
        if (streak is None or streak[0] != candidate
                or now - streak[2] > self.confirm_window_s):
            streak = [candidate, 0, now]
            self._confirming[raw_key] = streak
        streak[1] += 1
        streak[2] = now
        if streak[1] >= self.concurrent_confirmations:
            del self._confirming[raw_key]
            return candidate
        self.rejected_unconfirmed += 1
        self.last_reject_reason = (
            f"confirming #{candidate}: {streak[1]} of "
            f"{self.concurrent_confirmations} observations agree")
        return None

    def _sample_population(self, signature) -> None:
        """Keep a spread of distinct-looking observations for the statistic.

        Deliberately not one-per-identity: identities are the thing being
        fixed. Near-duplicates are skipped so a person standing still for five
        minutes contributes one sample, not nine thousand.
        """
        if not self.adaptive_weights or not isinstance(signature, Signature):
            return
        for existing in self._population:
            score = similarity(signature, existing, use_shape=False)
            if score is not None and score >= 0.97:
                return
        self._population.append(signature)
        if len(self._population) > self.population_size:
            self._population.pop(0)

    def cue_weights(self, now: float) -> tuple[float, float, float] | None:
        """Weight each cue by how well it actually separates the people seen.

        A uniform defeats a fixed weighting. If every member of staff wears the
        same apron, the upper-body cue agrees for everyone -- it contributes
        0.45 of apparent similarity while carrying no information at all, and
        the trousers that *do* distinguish them are outvoted. Two colleagues
        then score 0.82 against each other, above any threshold that still lets
        a real re-entry match, and one steals the other's ID.

        So the weights are measured rather than assumed: a cue that is nearly
        identical across the known population is scaled toward zero, and
        whatever still varies carries the decision. Returns None while too few
        people are known for the statistic to mean anything.
        """
        if not self.adaptive_weights:
            return None
        if (self._weights_at is not None
                and now - self._weights_at < self.weights_refresh_s):
            return self._weights_cache

        self._weights_at = now
        self._weights_cache = None

        # Sampled from raw observations, never from confirmed identities. If
        # the statistic were built from identities it could not bootstrap: a
        # uniform merges everyone into one identity, leaving a population of
        # one, and the reweighting that would have prevented the merge never
        # triggers. Observations are unaffected by matching decisions.
        reps = [r for r in self._population if isinstance(r, Signature)]
        if len(reps) < self.min_population:
            return None

        scaled: list[float] = []
        for attr, base in (("upper", WEIGHT_UPPER), ("lower", WEIGHT_LOWER)):
            vectors = [getattr(r, attr) for r in reps
                       if getattr(r, attr) is not None]
            if len(vectors) < self.min_population:
                scaled.append(base)
                continue
            shape = vectors[0].shape
            vectors = [v for v in vectors if v.shape == shape]
            pairs = [cosine(vectors[i], vectors[j])
                     for i in range(len(vectors))
                     for j in range(i + 1, len(vectors))]
            if not pairs:
                scaled.append(base)
                continue
            # everyone alike on this cue -> it distinguishes nobody
            informative = max(0.0, 1.0 - sum(pairs) / len(pairs))
            scaled.append(base * informative)

        # Build gets the same treatment, and needs it most: people are all
        # roughly person-shaped, so shape_similarity returns ~1.0 for nearly
        # every pair. Left at a fixed weight it becomes a constant floor of
        # agreement between strangers -- and the floor *rises* exactly when
        # another cue collapses, because the score is renormalised over
        # whatever remains.
        aspects = [r.aspect for r in reps if r.aspect]
        shape_weight = WEIGHT_SHAPE
        if len(aspects) >= self.min_population:
            pairs = [shape_similarity(aspects[i], aspects[j])
                     for i in range(len(aspects))
                     for j in range(i + 1, len(aspects))]
            pairs = [p for p in pairs if p is not None]
            if pairs:
                shape_weight = WEIGHT_SHAPE * max(
                    0.0, 1.0 - sum(pairs) / len(pairs))

        if sum(scaled) + shape_weight <= 1e-6:
            return None      # nothing separates anyone; keep the defaults
        self._weights_cache = (scaled[0], scaled[1], shape_weight)
        return self._weights_cache

    @staticmethod
    def _camera_of(raw_key: str) -> str | None:
        camera, sep, _ = raw_key.partition("\x00")
        return camera if sep else None

    def holders(self, stable_id: str, now: float | None = None) -> set[str | None]:
        """Cameras showing this identity, as of `now`.

        The invariant worth stating: at most one live track *per camera* may
        wear an identity, while several cameras may wear it at once -- that is
        one person seen from two angles, not two people sharing a number.

        Pass `now` to mean it. Tracker bookkeeping is kept for `max_gap_s` --
        fifteen minutes by default -- so without a clock this answers "which
        cameras have shown this identity recently", and someone who walked out
        of camera B a quarter of an hour ago still counts as being on it. That
        is the difference between guarding a live overlap and quietly applying
        the concurrent bar to every handover in the building.
        """
        held: set[str | None] = set()
        for raw, stable in self.raw_to_stable.items():
            if stable != stable_id:
                continue
            if now is not None:
                seen = self._raw_last_seen.get(raw)
                # a track with no timestamp yet is being set up in this very
                # frame -- treat it as live rather than guess it away
                if seen is not None and now - seen > self.holder_window_s:
                    continue
            held.add(self._camera_of(raw))
        return held

    def _absorb(self, provisional: str, target: str) -> None:
        """Fold a just-created placeholder identity into the one it matched."""
        if provisional == target or provisional not in self.identities:
            return
        ghost = self.identities.pop(provisional)
        self.identities[target].samples += ghost.samples
        # Corrections recorded against the placeholder must follow it. After a
        # correction the split-off track usually finds its real identity a frame
        # later; if the ban stayed pinned to the discarded placeholder, the same
        # wrong merge would be free to happen all over again.
        moved = {p for p in self.forbidden if provisional in p}
        for pair in moved:
            other = next(iter(pair - {provisional}), None)
            self.forbidden.discard(pair)
            if other is not None and other != target:
                self.forbidden.add(frozenset({target, other}))

    def _create(self, signature, now: float, camera: str | None = None) -> str:
        if self.id_source is not None:
            stable = self.id_source()
        else:
            stable = f"p{self._next_id}"
            self._next_id += 1
        gallery = [signature] if signature is not None else []
        self.identities[stable] = Identity(stable, gallery, now, now,
                                           last_camera=camera)
        return stable

    def _touch(self, stable: str, signature, now: float,
               camera: str | None = None) -> None:
        identity = self.identities.get(stable)
        if identity is None:
            return
        identity.last_seen = now
        identity.samples += 1
        if camera is not None:
            identity.last_camera = camera
        if signature is None:
            return
        # only keep genuinely new-looking views, so the gallery spans poses
        # instead of holding twelve copies of the same frame
        best = identity.best_match(signature)
        if best is not None and best >= self.novelty:
            return
        identity.gallery.append(signature)
        if len(identity.gallery) > self.gallery_size:
            identity.gallery.pop(0)

    def _prune(self, now: float) -> None:
        # retire tracker IDs that stopped appearing. Their identity lives on in
        # `identities`; it is only this raw-ID bookkeeping being dropped.
        for raw_key, seen in list(self._raw_last_seen.items()):
            if now - seen <= self.max_gap_s:
                continue
            self._raw_last_seen.pop(raw_key, None)
            self.raw_to_stable.pop(raw_key, None)
            self._probation.pop(raw_key, None)
            self._pending_views.pop(raw_key, None)
            self._confirming.pop(raw_key, None)
        # pending views are only useful while probation is open
        for raw_key in list(self._pending_views):
            if raw_key not in self._probation:
                self._pending_views.pop(raw_key, None)
        for raw_key in list(self._confirming):
            if raw_key not in self._probation:
                self._confirming.pop(raw_key, None)

        stale = [
            sid for sid, ident in self.identities.items()
            if now - ident.last_seen > self.max_gap_s
            and sid not in self.raw_to_stable.values()
        ]
        for sid in stale:
            del self.identities[sid]
        if len(self.identities) > self.memory:
            keep = sorted(self.identities.values(), key=lambda i: i.last_seen,
                          reverse=True)[:self.memory]
            self.identities = {i.stable_id: i for i in keep}
