"""Zone geometry and worker independence.

Two things are under test here:

  1. Where a person has to be to count as inside a zone. Get this wrong and
     every count and every alert is wrong with it.
  2. That counting does not require face recognition. This was a real bug — a
     camera configured for counting alone was processed by nothing at all,
     because person detection lived inside the recognition worker.
"""

from __future__ import annotations

import pytest

from vg.features.people import (
    PeopleResult,
    ZoneOccupancy,
    feet_point,
    point_in_polygon,
)
from vg.infer.persons import DetectedPerson

# A square occupying the middle of the frame.
SQUARE = ((0.2, 0.2), (0.8, 0.2), (0.8, 0.8), (0.2, 0.8))

# An L-shape — the case a bounding-box test gets wrong.
L_SHAPE = ((0.1, 0.1), (0.5, 0.1), (0.5, 0.5), (0.9, 0.5), (0.9, 0.9), (0.1, 0.9))


def person(x: float, y: float, w: float = 0.1, h: float = 0.3) -> DetectedPerson:
    return DetectedPerson(x=x, y=y, w=w, h=h, confidence=0.9)


class TestPointInPolygon:
    @pytest.mark.parametrize("point", [(0.5, 0.5), (0.25, 0.25), (0.75, 0.75)])
    def test_inside(self, point):
        assert point_in_polygon(*point, SQUARE) is True

    @pytest.mark.parametrize("point", [(0.1, 0.5), (0.9, 0.5), (0.5, 0.1), (0.5, 0.9)])
    def test_outside(self, point):
        assert point_in_polygon(*point, SQUARE) is False

    def test_concave_shapes_are_handled(self):
        # The whole reason for ray casting rather than a bounding box: real
        # zones are L-shaped corridors and bench cut-outs, not rectangles.
        assert point_in_polygon(0.2, 0.2, L_SHAPE) is True   # in the upper arm
        assert point_in_polygon(0.8, 0.7, L_SHAPE) is True   # in the lower arm
        assert point_in_polygon(0.8, 0.2, L_SHAPE) is False  # in the notch

    def test_a_bounding_box_test_would_get_the_notch_wrong(self):
        # Documents why the simpler implementation was rejected: the notch is
        # inside the polygon's bounding box but outside the polygon.
        xs = [p[0] for p in L_SHAPE]
        ys = [p[1] for p in L_SHAPE]
        in_bbox = min(xs) <= 0.8 <= max(xs) and min(ys) <= 0.2 <= max(ys)
        assert in_bbox is True
        assert point_in_polygon(0.8, 0.2, L_SHAPE) is False


class TestFeetPoint:
    def test_is_the_bottom_centre_of_the_box(self):
        assert feet_point(person(x=0.4, y=0.2, w=0.2, h=0.6)) == (0.5, 0.8)

    def test_someone_standing_in_the_zone_counts(self):
        # Feet at (0.5, 0.7) — inside the square.
        assert point_in_polygon(*feet_point(person(0.45, 0.4, 0.1, 0.3)), SQUARE)

    def test_someone_standing_below_the_zone_does_not_count(self):
        # Zone spans y 0.2-0.8. This person's box runs y 0.6-1.0, so their
        # torso overlaps the zone but their feet are at y=1.0, below it.
        # They are standing outside and leaning in.
        standing_below = person(x=0.45, y=0.6, w=0.1, h=0.4)

        assert feet_point(standing_below) == (0.5, 1.0)
        assert point_in_polygon(*feet_point(standing_below), SQUARE) is False

        # The same person under a centroid rule: centre at y=0.8... on the
        # edge. Take a slightly shorter box to make the contrast unambiguous.
        leaning = person(x=0.45, y=0.55, w=0.1, h=0.4)
        centroid = (leaning.x + leaning.w / 2, leaning.y + leaning.h / 2)
        assert point_in_polygon(*centroid, SQUARE) is True, (
            "centroid counts them inside"
        )
        assert point_in_polygon(*feet_point(leaning), SQUARE) is False, (
            "feet correctly do not — this is why the feet rule was chosen"
        )

    def test_someone_walking_past_the_edge_does_not_count(self):
        # Any-overlap would fire on this; feet would not.
        beside = person(x=0.78, y=0.5, w=0.1, h=0.3)
        assert point_in_polygon(*feet_point(beside), SQUARE) is False


class TestPeopleResult:
    def test_count_is_the_number_of_bodies(self):
        result = PeopleResult(people=(person(0.1, 0.1), person(0.5, 0.5)))
        assert result.count == 2

    def test_zone_lookup_by_id(self):
        result = PeopleResult(
            zones=(ZoneOccupancy("chem", "Chemistry lab", 1, True, (0,)),)
        )
        assert result.zone("chem").count == 1
        assert result.zone("nope") is None

    def test_empty_result_counts_zero(self):
        assert PeopleResult().count == 0


class TestWorkerIndependence:
    """Counting must not require attendance.

    The original build ran person detection inside the recognition worker and
    only started it for cameras with `attendance`, so a counting-only camera
    was silently never processed.
    """

    def test_body_features_do_not_include_attendance(self):
        from vg.api.app import BODY_FEATURES

        assert "attendance" not in BODY_FEATURES
        assert {"counting", "intrusion"}.issubset(BODY_FEATURES)

    def test_a_counting_only_camera_is_served(self):
        from vg.api.app import BODY_FEATURES
        from vg.config import CameraConfig

        camera = CameraConfig.parse(
            {"id": "c1", "name": "Yard", "source": "webcam:0", "features": ["counting"]},
            "c",
        )
        assert BODY_FEATURES.intersection(camera.features), (
            "a counting-only camera must be picked up by the people worker"
        )

    def test_an_attendance_only_camera_needs_no_person_detector(self):
        from vg.api.app import BODY_FEATURES
        from vg.config import CameraConfig

        camera = CameraConfig.parse(
            {"id": "c1", "name": "Gate", "source": "webcam:0",
             "features": ["attendance"]},
            "c",
        )
        # Attendance identifies people; it does not need to locate or count
        # them, so the person model should never load for this camera.
        assert not BODY_FEATURES.intersection(camera.features)

    def test_recognition_worker_no_longer_does_person_detection(self):
        import inspect

        from vg.features.recognition import RecognitionWorker

        source = inspect.getsource(RecognitionWorker)
        assert "persons" not in source, (
            "person detection must live in PeopleWorker, not here"
        )
        assert "people_count" not in source

    def test_both_workers_share_one_base(self):
        from vg.features.base import FeatureWorker
        from vg.features.people import PeopleWorker
        from vg.features.recognition import RecognitionWorker

        # Threading, rate limiting and boost live in one place, so adding a
        # third feature is one file with no concurrency code in it.
        assert issubclass(PeopleWorker, FeatureWorker)
        assert issubclass(RecognitionWorker, FeatureWorker)
