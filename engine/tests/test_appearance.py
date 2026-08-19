"""Appearance identity and path reconstruction.

The rule these defend: **an appearance match is a claim about continuity, never
about identity.** Clothing says "the same body as before"; only a face says
"this person". Every test here is about keeping those two apart, because the
failure mode of confusing them is a real child's name attached to a stranger's
movements — which reads as authoritative and is very hard to notice.
"""

from __future__ import annotations

import tempfile
from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
from pathlib import Path

import numpy as np
import pytest

from vg.events.appearance import AppearanceStore
from vg.identity.appearance import (
    BINDING_TTL_SECONDS,
    AppearanceSighting,
    AppearanceTracker,
    _containment,
)

NOON = datetime(2026, 8, 15, 9, 0, tzinfo=timezone.utc)


def sighting(stable_id="a1", camera="cam-1", at=None, person=None,
             x=0.2, y=0.1, w=0.2, h=0.6, track_id=1, confidence=0.9):
    return AppearanceSighting(
        stable_id=stable_id, camera_id=camera, at=at or NOON,
        x=x, y=y, w=w, h=h, confidence=confidence,
        track_id=track_id, person_id=person,
    )


@pytest.fixture
def store():
    with tempfile.TemporaryDirectory() as tmp:
        s = AppearanceStore(Path(tmp) / "a.db", min_gap_seconds=0.0)
        yield s
        s.close()


# ---------------------------------------------------------------------------
# geometry
# ---------------------------------------------------------------------------

class TestContainment:
    def test_a_face_inside_a_body_scores_high(self):
        """Containment, not IoU. A head is a small part of a body, so their
        IoU is tiny even when they match perfectly - using IoU here would
        reject every correct pairing."""
        face = (0.25, 0.12, 0.33, 0.24)
        body = (0.20, 0.10, 0.40, 0.70)
        assert _containment(face, body) > 0.95

    def test_a_face_outside_scores_zero(self):
        assert _containment((0.8, 0.8, 0.9, 0.9), (0.1, 0.1, 0.3, 0.6)) == 0.0

    def test_a_half_overlapping_face_scores_around_half(self):
        assert 0.3 < _containment((0.0, 0.0, 0.2, 0.2), (0.1, 0.0, 0.5, 0.2)) < 0.7


# ---------------------------------------------------------------------------
# naming
# ---------------------------------------------------------------------------

class TestNaming:
    def test_an_unnamed_identity_has_no_person(self):
        tracker = AppearanceTracker()
        assert tracker.whois("a1") is None

    def test_binding_a_face_names_the_body_containing_it(self):
        tracker = AppearanceTracker()
        bodies = [sighting(stable_id="a1", x=0.2, y=0.1, w=0.2, h=0.6)]

        named = tracker.bind_face(bodies, (0.25, 0.12, 0.08, 0.12), "p-ahmed", 0.9)

        assert named == "a1"
        assert tracker.whois("a1") == "p-ahmed"

    def test_a_face_inside_two_bodies_is_refused(self):
        """Two overlapping people and one face between them. Guessing attaches
        a name to the wrong person for the rest of the day."""
        tracker = AppearanceTracker()
        bodies = [
            sighting(stable_id="a1", x=0.20, y=0.10, w=0.30, h=0.60),
            sighting(stable_id="a2", x=0.22, y=0.10, w=0.30, h=0.60),
        ]

        assert tracker.bind_face(bodies, (0.25, 0.12, 0.06, 0.10), "p-ahmed", 0.9) is None
        assert tracker.whois("a1") is None and tracker.whois("a2") is None

    def test_a_face_matching_no_body_is_refused(self):
        tracker = AppearanceTracker()
        bodies = [sighting(stable_id="a1", x=0.1, y=0.1, w=0.1, h=0.3)]
        assert tracker.bind_face(bodies, (0.8, 0.8, 0.05, 0.08), "p-ahmed", 0.9) is None

    def test_a_better_face_match_replaces_a_weaker_one(self):
        """Otherwise the first blurry glimpse of the day owns the identity."""
        tracker = AppearanceTracker()
        tracker.bind("a1", "p-weak", score=0.40, at=NOON)
        tracker.bind("a1", "p-strong", score=0.95, at=NOON)
        assert tracker.whois("a1", NOON.timestamp()) == "p-strong"

    def test_a_weaker_face_match_does_not_displace_a_stronger_one(self):
        tracker = AppearanceTracker()
        tracker.bind("a1", "p-strong", score=0.95, at=NOON)
        tracker.bind("a1", "p-weak", score=0.40, at=NOON)
        assert tracker.whois("a1", NOON.timestamp()) == "p-strong"

    def test_a_binding_expires(self):
        """Clothing is an identity only while it is being worn. Yesterday's
        binding on today's body is a wrong name."""
        tracker = AppearanceTracker()
        tracker.bind("a1", "p-ahmed", score=0.9, at=NOON)

        later = NOON.timestamp() + BINDING_TTL_SECONDS + 1
        assert tracker.whois("a1", later) is None

    def test_identities_for_finds_every_body_carrying_a_name(self):
        """One person legitimately has several identities in a day: each
        re-identification after a long gap starts a fresh one."""
        tracker = AppearanceTracker()
        tracker.bind("a1", "p-ahmed", 0.9, NOON)
        tracker.bind("a7", "p-ahmed", 0.9, NOON)
        tracker.bind("a3", "p-layla", 0.9, NOON)

        assert tracker.identities_for("p-ahmed", NOON.timestamp()) == ["a1", "a7"]

    def test_correcting_removes_the_name(self):
        tracker = AppearanceTracker()
        tracker.bind("a1", "p-ahmed", 0.9, NOON)
        tracker.correct("a1", NOON)
        assert tracker.whois("a1", NOON.timestamp()) is None


# ---------------------------------------------------------------------------
# observing
# ---------------------------------------------------------------------------

@dataclass
class FakeTrack:
    track_id: int
    x1: int = 100
    y1: int = 50
    x2: int = 200
    y2: int = 400
    confidence: float = 0.9

    @property
    def box(self):
        return (self.x1, self.y1, self.x2, self.y2)

    def to_fractions(self, w, h):
        return (self.x1 / w, self.y1 / h, (self.x2 - self.x1) / w, (self.y2 - self.y1) / h)


class TestObserving:
    def test_no_tracks_produces_no_sightings(self):
        tracker = AppearanceTracker()
        frame = np.zeros((480, 640, 3), np.uint8)
        assert tracker.observe("cam-1", frame, [], NOON) == []

    def test_a_track_becomes_a_sighting_in_fractions(self):
        """Geometry crosses every boundary as fractions of the frame. A pixel
        value here would break the moment a camera changed resolution."""
        tracker = AppearanceTracker()
        frame = np.zeros((480, 640, 3), np.uint8)

        out = tracker.observe("cam-1", frame, [FakeTrack(track_id=3)], NOON)

        assert len(out) == 1
        s = out[0]
        assert s.camera_id == "cam-1" and s.track_id == 3
        assert 0.0 <= s.x <= 1.0 and 0.0 <= s.y <= 1.0
        assert 0.0 <= s.w <= 1.0 and 0.0 <= s.h <= 1.0

    def test_the_same_body_keeps_its_identity_across_frames(self):
        tracker = AppearanceTracker()
        rng = np.random.default_rng(0)
        frame = rng.integers(0, 255, (480, 640, 3), dtype=np.uint8)

        first = tracker.observe("cam-1", frame, [FakeTrack(track_id=3)], NOON)
        second = tracker.observe(
            "cam-1", frame, [FakeTrack(track_id=3)], NOON + timedelta(seconds=1))

        assert first[0].stable_id == second[0].stable_id


# ---------------------------------------------------------------------------
# the store
# ---------------------------------------------------------------------------

class TestStore:
    def test_a_sighting_is_written_and_counted(self, store):
        assert store.record(sighting())
        assert store.count_on(store.local_date(NOON)) == 1

    def test_dense_sightings_are_sampled_down(self):
        """One row per person per frame is millions of rows a day on a real
        site, and a person standing still needs none of them."""
        with tempfile.TemporaryDirectory() as tmp:
            s = AppearanceStore(Path(tmp) / "a.db", min_gap_seconds=3.0)
            s.record(sighting(at=NOON))
            written = s.record(sighting(at=NOON + timedelta(seconds=1)))
            later = s.record(sighting(at=NOON + timedelta(seconds=5)))
            s.close()

        assert not written, "a sighting one second later should be skipped"
        assert later, "a sighting five seconds later should be kept"

    def test_the_date_is_the_sites_not_the_servers(self):
        """A path belongs to a school day. A server in another timezone must
        not decide where that boundary falls."""
        with tempfile.TemporaryDirectory() as tmp:
            s = AppearanceStore(Path(tmp) / "a.db", tz_offset_minutes=180)
            late = datetime(2026, 8, 15, 22, 30, tzinfo=timezone.utc)
            assert s.local_date(late) == "2026-08-16"
            s.close()

    def test_naming_backfills_earlier_rows(self, store):
        """Recognition happens after the body has been seen for a few frames.
        A path starting only at the face match is missing its beginning."""
        for i in range(3):
            store.record(sighting(stable_id="a1", at=NOON + timedelta(seconds=i)))

        assert store.name_identity("a1", "p-ahmed") == 3
        assert len(store.path_for("p-ahmed", store.local_date(NOON))) == 1

    def test_naming_does_not_overwrite_an_existing_name(self, store):
        store.record(sighting(stable_id="a1", person="p-layla", at=NOON))
        assert store.name_identity("a1", "p-ahmed") == 0

    def test_a_correction_withdraws_the_name_but_keeps_the_row(self, store):
        """The body was really there. Only the claim about who it was is wrong."""
        store.record(sighting(stable_id="a1", person="p-ahmed", at=NOON))

        assert store.unname_identity("a1") == 1
        assert store.count_on(store.local_date(NOON)) == 1
        assert store.path_for("p-ahmed", store.local_date(NOON)) == []


class TestPaths:
    def test_consecutive_sightings_on_one_camera_are_one_stop(self, store):
        for i in range(5):
            store.record(sighting(person="p-ahmed", at=NOON + timedelta(seconds=i * 2)))

        path = store.path_for("p-ahmed", store.local_date(NOON))
        assert len(path) == 1
        assert path[0].sightings == 5
        assert path[0].seconds == pytest.approx(8.0)

    def test_moving_between_cameras_makes_separate_stops(self, store):
        store.record(sighting(camera="cam-gate", person="p-ahmed", at=NOON))
        store.record(sighting(camera="cam-hall", person="p-ahmed",
                              at=NOON + timedelta(seconds=30)))

        path = store.path_for("p-ahmed", store.local_date(NOON))
        assert [s.camera_id for s in path] == ["cam-gate", "cam-hall"]

    def test_returning_to_a_camera_after_a_gap_is_a_new_stop(self, store):
        store.record(sighting(camera="cam-gate", person="p-ahmed", at=NOON))
        store.record(sighting(camera="cam-gate", person="p-ahmed",
                              at=NOON + timedelta(minutes=20)))

        path = store.path_for("p-ahmed", store.local_date(NOON), gap_seconds=60)
        assert len(path) == 2

    def test_pacing_in_and_out_of_view_stays_one_stop(self, store):
        """Without the gap rule, someone shifting at the edge of frame
        produces dozens of stops and an unreadable path."""
        for i in range(6):
            store.record(sighting(camera="cam-gate", person="p-ahmed",
                                  at=NOON + timedelta(seconds=i * 10)))

        path = store.path_for("p-ahmed", store.local_date(NOON), gap_seconds=60)
        assert len(path) == 1

    def test_a_path_is_chronological(self, store):
        store.record(sighting(camera="cam-c", person="p-ahmed",
                              at=NOON + timedelta(minutes=10)))
        store.record(sighting(camera="cam-a", person="p-ahmed", at=NOON))
        store.record(sighting(camera="cam-b", person="p-ahmed",
                              at=NOON + timedelta(minutes=5)))

        path = store.path_for("p-ahmed", store.local_date(NOON))
        assert [s.camera_id for s in path] == ["cam-a", "cam-b", "cam-c"]

    def test_an_unknown_person_has_an_empty_path_not_an_error(self, store):
        assert store.path_for("p-nobody", "2026-08-15") == []

    def test_an_unnamed_body_can_still_be_pathed(self, store):
        """Somebody was there and moved around; nobody knows who. That is a
        real, useful answer - and pretending it is nothing loses it."""
        store.record(sighting(stable_id="a9", camera="cam-a", at=NOON))
        store.record(sighting(stable_id="a9", camera="cam-b",
                              at=NOON + timedelta(minutes=2)))

        path = store.path_for_identity("a9", store.local_date(NOON))
        assert len(path) == 2
        assert all(s.person_id is None for s in path)

    def test_old_rows_can_be_pruned(self, store):
        old = datetime.now(timezone.utc) - timedelta(days=40)
        store.record(sighting(at=old))
        store.record(sighting(stable_id="a2", at=datetime.now(timezone.utc)))

        assert store.prune(keep_days=14) == 1
