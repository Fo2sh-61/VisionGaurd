"""Knife detection: a knife held by somebody, on any camera.

Two models, in a fixed order, and the order is the whole feature:

    person pass (shared)  ->  nobody?  ->  stop. The knife model never runs.
                              somebody? ->  knife pass, then keep only the
                                            knives whose box centre lies
                                            inside a person's box.

**Nobody in view means the knife model does not run.** Not "runs and finds
nothing" — does not run. That gate is the entire cost argument: a site with
208 cameras can afford a second model only because an empty corridor pays for
one pass, not two. It is also the reason `SharedDetection` is passed in rather
than a second person detector: on a camera that counting or zones already
looked at, this feature's person pass is a cache hit and costs nothing at all.

**A knife with nobody near it is not a detection.** Measured, not assumed: on
the two recorded clips — neither of which contains a knife — the model's
strongest and longest false runs were a desk edge and a chair in the
bottom-right corner, scoring over 0.5 in nine frames of 120, with somebody
sitting at that desk the whole time. "Only when a person is in view" would not
have removed them; "on the person" does. Growing the person box by 25 % lets
them straight back in, so the margin is zero.

The rest is one small state machine per camera:

    idle       --1st hit-->        candidate    remember when it started
    candidate  --3 hits, >=1 s-->  in a scene   open, and start recording
    candidate  --2 s quiet-->      idle         forget it; it was furniture
    in a scene --hit-->            in a scene   extend, raise the peak
    in a scene --no knife, <2 s--> in a scene   a blink; do nothing
    in a scene --no knife, >=2 s-->idle         close, reason "gone"
    in a scene --2 min elapsed-->  idle         close "limit", reopen at once

**Two seconds, not one and not ten.** Restricted zones close a scene after a
second without a body, because a body is a large reliable thing. A knife is
small, often half-hidden by the hand holding it, and the detector loses it
constantly — so a one-second rule would turn a single incident into a dozen
entries and a dozen videos.

This was ten seconds until the owner watched it with a real knife. Ten bought
one entry per incident and charged ten dead seconds at the end of every video
for it. Two is his call, made with the thing in his hand: short clips, at the
price of an occasional split when the detector loses a knife for longer than
that. See `GAP_SECONDS`.

**The entry is stamped with the first sighting, not the third.** An operator
opening the clip should watch the knife arrive, not find it already in shot.

**Time comes from `frame.captured_at`, never `time.monotonic()`.** The gaps
then match the video rather than however long the machine was busy, and a test
can prove a two-minute limit in microseconds by choosing its own timestamps.

There is no threading in this file. `FeatureWorker` owns it, and the knife
model owns its own lock.
"""

from __future__ import annotations

import logging
from dataclasses import dataclass
from datetime import datetime, timedelta, timezone

from vg.events.weapons import WeaponSceneStore
from vg.features.base import FeatureWorker
from vg.infer.persons import DetectedPerson
from vg.infer.shared import SharedDetection
from vg.infer.weapons import DetectedWeapon, WeaponDetector
from vg.ingest.recorder import AlreadyRecording
from vg.ingest.source import Frame

log = logging.getLogger(__name__)

#: How many sightings make a knife, and over how long. The longest false run
#: with the box on a person, measured across both recorded clips, is one
#: frame; a knife somebody is actually holding is visible for seconds. Research
#: D2. P6-FR-003.
CONFIRM_HITS = 3
CONFIRM_SECONDS = 1.0

#: How long a part-built candidate survives without another hit. A blink
#: between the three sightings must not reset the count; a minute must.
CANDIDATE_GAP_SECONDS = 2.0

#: How long the camera must see no knife before the incident is over, and
#: therefore how long the video runs on past the last sighting. P6-FR-004.
#:
#: **Two seconds, set by the owner on 22 Aug 2026 after watching it with a real
#: knife.** It was ten, chosen from the recorded clips before anyone had seen
#: the model track a knife somebody was actually holding. Ten seconds is a long
#: time to sit at the end of every video waiting for nothing to happen: his
#: scenes ran 12 to 19 seconds for 2 to 9 seconds of knife.
#:
#: The cost is real and he accepted it. This is also the anti-flicker rule, so
#: shortening it means a detector that loses the knife for more than two
#: seconds now ends the incident: one hand-turn too long and what a person
#: would call a single event becomes two entries and two videos. Ten seconds
#: bought one entry per incident at the price of ten dead seconds on every
#: clip. Two buys short clips at the price of occasional splits.
#:
#: If the splitting turns out to be worse than the waiting, this is the number
#: to move, and `test_flicker_under_the_gap_is_one_scene` is the test that
#: describes what changes.
GAP_SECONDS = 2.0

#: How long the camera must see no knife at all before the next one is news
#: again — the length of a *run*, as opposed to a scene.
#:
#: `GAP_SECONDS` decides when an entry ends. This decides when a *message*
#: ends, and they are deliberately not the same number: at two seconds a hand
#: turning cuts one incident into two entries, and without this that would be
#: two alerts about one knife. Only the first scene of a run is announced; the
#: rest are opened `continues=True` and send nothing.
#:
#: Entries are untouched — every scene is still logged, recorded and listed.
#: The same rule and the same minute as `features/zones.py`, set by the owner
#: on 12 Sep 2026 after the zone feature mailed thirty-two times about one
#: visit. The two are separate numbers on purpose: a knife reappearing is not
#: the same kind of news as somebody walking back past a door, so either can
#: move without the other.
ALERT_AGAIN_AFTER_SECONDS = 60.0

#: Longest a single scene may run. Somebody holding a knife for an afternoon is
#: not one clip, and the entry says it was cut rather than looking like they
#: put it away. Deliberately NOT `recorder.MAX_SECONDS` — the manual record
#: button legitimately wants its ten minutes.
MAX_SCENE_SECONDS = 120.0

#: How far outside a person's box a knife's centre may sit. Zero, and measured:
#: at 0 % no false run survives more than a frame, at 25 % the corner furniture
#: comes back. Research D2.
PERSON_MARGIN = 0.0

#: How long the red box stays on the picture after the last frame the model
#: actually fired on.
#:
#: Without this the overlay is invisible. The knife model is intermittent by
#: nature — that is the entire reason `GAP_SECONDS` is ten seconds and not one
#: — so on most analysed frames it finds nothing even while somebody is plainly
#: holding a knife. Drawing only the current frame's hits therefore put a box
#: on screen for one 200 ms analysis tick and nothing in between: the entry
#: appeared in the list and the picture stayed bare, which is exactly what the
#: owner reported on 22 Aug 2026.
#:
#: Two seconds is the compromise. Long enough to be seen at the 5 Hz analysis
#: rate; short enough that the box is never far from where the knife actually
#: was. It is deliberately far shorter than `GAP_SECONDS`: a scene survives a
#: ten-second blink because the incident is still happening, but a *box* held
#: for ten seconds would be pointing at a place the knife has left, and a box
#: in the wrong place is a false claim about what the camera can see.
OVERLAY_HOLD_SECONDS = 2.0

#: Who the recorder logs as having asked. Never a person's name: pretending an
#: operator pressed record would be a lie in the recording log.
ACTOR = "knife-detection"

#: What an entry says when the recorder refused because one was already
#: running on that camera. Deliberately does not name an operator: this
#: feature has its own recorder, so the only thing that can be holding it is
#: this feature, and blaming a person for it would be a guess printed as fact.
BUSY_REASON = (
    "No clip: a recording was already running on this camera."
)


@dataclass
class Candidate:
    """Sightings that have not yet earned a scene. Sub-second by design."""

    first_at: datetime
    last_at: datetime
    hits: int = 1
    # The best score seen while this was still a candidate. The scene is
    # stamped with the FIRST sighting, so every one of these sightings is
    # inside it and its confidence counts towards the peak — dropping them
    # would report the third frame's score as if it were the highest.
    peak: float = 0.0


@dataclass
class SceneState:
    """One camera's in-flight scene. Lost on restart, and closed on the next."""

    scene_id: str
    started_at: datetime
    last_knife_at: datetime
    peak: float = 0.0
    recording: bool = False


@dataclass(frozen=True)
class WeaponsResult:
    """What this worker saw on one frame.

    `checked` says the knife model actually ran, which is not the same as
    finding nothing: a frame with nobody in it was never looked at, and the
    page must not read that as an all-clear.
    """

    checked: bool = False
    people: int = 0
    knives: tuple[DetectedWeapon, ...] = ()
    scene_id: str | None = None


class WeaponsWorker(FeatureWorker[WeaponsResult]):
    """Looks for a knife on the people in view, and logs each one as a scene."""

    def __init__(
        self,
        bus,
        people: SharedDetection,
        knives: WeaponDetector,
        cameras: list[str],
        scenes: WeaponSceneStore,
        recorder=None,
        retention_days: int | None = None,
        rate_hz: float = 2.0,
        boost_hz: float = 12.0,
    ) -> None:
        super().__init__("weapons", bus, cameras, rate_hz, boost_hz)
        # The SAME SharedDetection the people worker holds, never a second
        # detector. It caches on (camera_id, frame.sequence), so when both
        # workers land on one frame the person model runs once — and switching
        # this feature on cannot change what Counting reports (rule 9).
        self.people = people
        # One instance, shared by every camera thread. Its lock is inside
        # `detect()`, not here.
        self.knives = knives
        # The knife model's pool. The person pass this worker also reads is
        # charged to `people`, which is where it runs — counting it twice
        # would say switching knives on doubles the person detector.
        self.device = getattr(knives, "device", None)
        self.scenes = scenes
        # Absent means scenes are still logged, with an honest reason for the
        # missing video rather than a button that does nothing.
        self.recorder = recorder
        # How long a video is kept. Held here rather than in the store because
        # the store must not have to be edited when a site changes the period.
        # None means this worker never sweeps — the console's read still does,
        # and so does startup.
        self.retention_days = retention_days
        # camera id -> sightings that have not yet earned a scene.
        self._candidates: dict[str, Candidate] = {}
        # camera id -> the scene running on it right now.
        self._live: dict[str, SceneState] = {}
        # camera id -> (frame time of the last frame the model fired on, the
        # boxes it found). What the overlay draws — see OVERLAY_HOLD_SECONDS.
        self._seen: dict[str, tuple[datetime, tuple[DetectedWeapon, ...]]] = {}
        # camera id -> the time of the last frame analysed at all. The hold is
        # measured between two FRAME times, never against the wall clock, so it
        # means the same thing on a live camera and on a recorded clip.
        self._last_frame_at: dict[str, datetime] = {}
        # camera id -> the last frame with a knife on it, ACROSS scenes.
        # `_seen` is dropped when a scene closes; this outlives it, and is the
        # only thing that can say whether the camera has been clear long enough
        # for the next knife to be a new incident. See ALERT_AGAIN_AFTER_SECONDS.
        self._last_hit_at: dict[str, datetime] = {}
        # Cameras whose current run has already been handed to the alert hook.
        self._announced: set[str] = set()

    # -- one frame ----------------------------------------------------------

    def analyse(self, frame: Frame) -> WeaponsResult:
        camera_id = frame.camera_id
        now = frame.captured_at
        self._last_frame_at[camera_id] = now
        # On every frame, before anything else: a camera that went dark
        # delivers no quiet frames at all, and if the run could only end on
        # those, the first knife after an outage would be taken for the last
        # one before it and nobody would be told.
        self._end_run(camera_id, now)

        people = self.people.detect(frame)
        if not people:
            # BEFORE the knife model. Nobody to hold anything, so there is
            # nothing to look for and nothing to pay for.
            self._quiet(camera_id, now)
            return WeaponsResult(checked=False)

        hits = tuple(
            k for k in self.knives.detect(frame.image) if _on_a_person(k, people)
        )
        if not hits:
            self._quiet(camera_id, now)
            return WeaponsResult(checked=True, people=len(people))

        # What the overlay will draw for the next OVERLAY_HOLD_SECONDS. Kept
        # separate from the returned result on purpose: the result says what
        # THIS frame showed, which is what the state machine reasons about;
        # the overlay says what the camera has shown recently, which is what a
        # person needs to be able to see at all.
        self._seen[camera_id] = (now, hits)
        # Spans scenes, so it is set here rather than on the scene state.
        self._last_hit_at[camera_id] = now

        peak = max(k.confidence for k in hits)
        state = self._live.get(camera_id)

        if state is None:
            scene_id = self._note_candidate(camera_id, now, peak)
            return WeaponsResult(
                checked=True, people=len(people), knives=hits, scene_id=scene_id,
            )

        state.last_knife_at = now
        if peak > state.peak:
            state.peak = peak
            self.scenes.note_confidence(state.scene_id, peak)

        if (now - state.started_at).total_seconds() >= MAX_SCENE_SECONDS:
            # Cut, but not blind: the knife is still there, so the next scene
            # opens on this same frame.
            self._close(camera_id, now, "limit")
            return WeaponsResult(
                checked=True, people=len(people), knives=hits,
                # Same knife, same hand: a new entry, not a new alert — and
                # `_open` works that out from the run rather than being told,
                # because "same hand" is only true while the frames kept
                # coming. A camera dark for two hours reaches this line too.
                scene_id=self._open(camera_id, now, peak, at=now),
            )

        return WeaponsResult(
            checked=True, people=len(people), knives=hits, scene_id=state.scene_id,
        )

    def _quiet(self, camera_id: str, now: datetime) -> None:
        """A frame with no knife on anybody — for either reason.

        A frame nobody was in and a frame with people but no knife are the same
        thing to the state machine: nothing was seen. Treating "nobody there"
        as a special case would leave a scene open on an empty corridor until
        somebody walked back into it.
        """
        candidate = self._candidates.get(camera_id)
        if candidate is not None:
            if (now - candidate.last_at).total_seconds() >= CANDIDATE_GAP_SECONDS:
                del self._candidates[camera_id]

        state = self._live.get(camera_id)
        if state is not None:
            if (now - state.last_knife_at).total_seconds() >= GAP_SECONDS:
                self._close(camera_id, now, "gone")

    def _end_run(self, camera_id: str, now: datetime) -> None:
        """A camera clear of knives this long ends the run: the next is news.

        Called from the top of `analyse`, on every frame. The mark is dropped
        with the run, so a quiet camera costs one dictionary lookup a frame
        and nothing else.
        """
        last = self._last_hit_at.get(camera_id)
        if last is None:
            return
        if (now - last).total_seconds() >= ALERT_AGAIN_AFTER_SECONDS:
            del self._last_hit_at[camera_id]
            self._announced.discard(camera_id)

    def _note_candidate(
        self, camera_id: str, now: datetime, confidence: float
    ) -> str | None:
        """Count a sighting, and open a scene once there are enough of them.

        Returns the new scene's id, or None while this is still only a
        candidate. Nothing is written to the database until the third hit —
        a candidate that never becomes a scene must leave no trace, or the
        page fills with the furniture the confirm rule exists to remove.
        """
        candidate = self._candidates.get(camera_id)
        if candidate is None or (
            (now - candidate.last_at).total_seconds() >= CANDIDATE_GAP_SECONDS
        ):
            self._candidates[camera_id] = Candidate(
                first_at=now, last_at=now, hits=1, peak=confidence)
            return None

        candidate.hits += 1
        candidate.last_at = now
        candidate.peak = max(candidate.peak, confidence)
        if candidate.hits < CONFIRM_HITS:
            return None
        if (now - candidate.first_at).total_seconds() < CONFIRM_SECONDS:
            return None

        started_at = candidate.first_at
        peak = candidate.peak
        del self._candidates[camera_id]
        # The FIRST sighting, not this one: the clip should show the knife
        # arriving. The peak carries every sighting since then.
        return self._open(camera_id, started_at, peak, at=now)

    # -- opening and closing ------------------------------------------------

    def _open(self, camera_id: str, started_at: datetime, confidence: float,
              at: datetime | None = None) -> str:
        # Whether this is news is never passed in: it is the run that decides,
        # in one place. Still inside a run — the camera has not been clear of
        # knives for `ALERT_AGAIN_AFTER_SECONDS` — means a new entry and not a
        # new alert, and the alert hook reads `continues` and sends nothing.
        continues = camera_id in self._announced
        scene_id = self.scenes.open(
            camera_id, started_at, confidence, self.knives.version,
            continues=continues)
        self._announced.add(camera_id)
        state = SceneState(
            scene_id=scene_id,
            started_at=started_at,
            last_knife_at=at or started_at,
            peak=confidence,
        )
        self._live[camera_id] = state
        state.recording = self._start_recording(camera_id, scene_id)
        log.info("knife scene %s opened on %s", scene_id[:8], camera_id)
        return scene_id

    def _close(self, camera_id: str, at: datetime, reason: str) -> None:
        state = self._live.pop(camera_id, None)
        # Dropped whether or not a scene was running, so a camera that leaves
        # the roster cannot leave its last boxes behind for ever.
        self._seen.pop(camera_id, None)
        if state is None:
            return
        self.scenes.close(state.scene_id, at, reason)
        if state.recording:
            self._stop_recording(camera_id, state.scene_id)
        log.info("knife scene %s closed on %s (%s)",
                 state.scene_id[:8], camera_id, reason)

    def _closing(self, camera_id: str) -> None:
        """This camera is leaving the worker. Close its scene, on its thread.

        `_close` already drops `_seen`; the rest is dropped here so a camera
        that leaves the roster leaves nothing behind — and so the next knife
        after it comes back is news, not a continuation of the last run.
        """
        self._close(camera_id, datetime.now(timezone.utc), "switched_off")
        self._last_frame_at.pop(camera_id, None)
        self._last_hit_at.pop(camera_id, None)
        self._announced.discard(camera_id)
        super()._closing(camera_id)

    def close_all(self, reason: str = "shutdown") -> None:
        """Close every running scene. Call only when no worker thread is live.

        No scene may be left showing as still running, or the page reports a
        knife in view that was put away when the engine stopped.
        """
        for camera_id in list(self._live):
            self._close(camera_id, datetime.now(timezone.utc), reason)

    def stop(self) -> None:
        # Threads first, then the scenes. The other order would close a scene
        # underneath the thread still writing to it. Once `super().stop()`
        # returns, the camera threads are joined and this is the only one left.
        super().stop()
        self.close_all("shutdown")

    # -- recording ----------------------------------------------------------

    def _start_recording(self, camera_id: str, scene_id: str) -> bool:
        """Begin a clip. Returns whether one is actually being written.

        Every failure here is recorded as a reason on the scene rather than
        raised: an incident that happened is worth logging even when no video
        of it exists, and a "saved" entry with no file is the fake save rule 4
        forbids.
        """
        if self.recorder is None:
            self.scenes.fail_clip(
                scene_id, "No clip: recording is not running on this engine.")
            return False
        try:
            self.recorder.start(camera_id, actor=ACTOR)
        except AlreadyRecording:
            # Never steal the operator's file.
            self.scenes.fail_clip(scene_id, BUSY_REASON)
            return False
        except Exception as exc:  # noqa: BLE001 - reported, never raised
            log.exception("could not start recording %s", camera_id)
            self.scenes.fail_clip(
                scene_id, f"No clip: recording failed to start ({exc}).")
            return False
        self.scenes.start_clip(scene_id)
        return True

    def _stop_recording(self, camera_id: str, scene_id: str) -> None:
        try:
            recording = self.recorder.stop(camera_id, actor=ACTOR)
        except Exception as exc:  # noqa: BLE001 - reported, never raised
            log.exception("could not stop recording %s", camera_id)
            self.scenes.fail_clip(scene_id, f"No clip: recording failed ({exc}).")
            return

        if recording is None:
            self.scenes.fail_clip(
                scene_id, "No clip: the recording had already stopped.")
            return
        if recording.state != "saved" or recording.path is None:
            self.scenes.fail_clip(
                scene_id,
                recording.reason or "No clip: nothing was written to disk.")
            return
        self.scenes.attach_clip(scene_id, recording.path)
        self._expire_old_clips()

    def _expire_old_clips(self) -> None:
        """Drop videos past their retention, whenever a new one saves.

        The other two sweeps are at startup and on every console read. This one
        is the only one that does not need a person: an engine running for
        months with nobody opening the page would otherwise keep every video it
        ever wrote, and the retention period is a promise to the people on
        camera, not a feature of the console.

        Reported, never raised. A knife video that saved correctly must not be
        undone by a failure to tidy up an old one.
        """
        if not self.retention_days:
            return
        try:
            self.scenes.expire(
                datetime.now(timezone.utc) - timedelta(days=self.retention_days))
        except Exception:  # noqa: BLE001 - reported, never raised
            log.exception("could not expire old knife clips")

    # -- reads --------------------------------------------------------------

    def knives_on(self, camera_id: str) -> list[DetectedWeapon]:
        """The knives to draw on this camera right now.

        The last frame the model actually fired on, held for
        `OVERLAY_HOLD_SECONDS` — not the last frame analysed. Reading the
        instantaneous frame is what made this overlay invisible: the model
        blinks constantly, so the box existed for one analysis tick at a time
        and a person watching the page saw an entry appear over a bare picture.

        The hold is measured between two **frame** times, never against the
        wall clock, so it means the same thing on a live camera and on a
        recorded clip and a test can prove it without sleeping.

        A camera that has stopped delivering frames is not handled here and
        does not need to be: both callers — `camera_view` and
        `camera_detections` in `api/live.py` — already build `boxes` as
        `self._boxes(...) if online else []`, so a dropped stream draws nothing
        whatever this returns. Repeating that check here by asking `payload()`
        looked prudent and was worse than useless: `Result.at` is the frame's
        timestamp, so on any source whose frames are not stamped with the wall
        clock `payload()` returns None and the overlay silently disappears.

        Empty when the last frame had nobody in it, which is the truth: the
        model was not asked, so it found nothing.
        """
        seen = self._seen.get(camera_id)
        last_frame_at = self._last_frame_at.get(camera_id)
        if seen is None or last_frame_at is None:
            return []

        seen_at, knives = seen
        if (last_frame_at - seen_at).total_seconds() > OVERLAY_HOLD_SECONDS:
            return []
        return list(knives)

    def scene_on(self, camera_id: str) -> str | None:
        """The running scene for a camera, if a knife is in view right now."""
        state = self._live.get(camera_id)
        return state.scene_id if state else None


def _on_a_person(weapon: DetectedWeapon, people: list[DetectedPerson]) -> bool:
    """Is this knife's centre inside somebody's box?

    The centre, not an overlap: a knife touching the edge of a person box is
    the desk behind them far more often than it is something in their hand.
    The margin is zero — see `PERSON_MARGIN`.
    """
    cx = weapon.x + weapon.w / 2
    cy = weapon.y + weapon.h / 2
    for body in people:
        grow_w = body.w * PERSON_MARGIN
        grow_h = body.h * PERSON_MARGIN
        if (body.x - grow_w <= cx <= body.x + body.w + grow_w
                and body.y - grow_h <= cy <= body.y + body.h + grow_h):
            return True
    return False
