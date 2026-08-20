"""People in frame, and people inside zones.

Serves counting, intrusion and track-a-person. Runs on any camera configured
for those, and does not know or care whether face recognition exists — that
independence is the point.

Zone membership uses the **feet point**: the bottom-centre of the person's box.
That is where they are standing on the floor, which is what a zone actually
describes. The alternatives are both worse:

  centroid      a tall person standing just outside the line has their torso
                over it, so they count as inside while their feet are clearly
                outside — over-counts along every boundary
  any overlap   anyone walking past the edge of the zone triggers it

Feet also degrade sensibly: when someone is partly out of frame at the bottom,
their box is clipped, the feet point rises, and they stop being counted in a
zone near the bottom edge — which is the safe direction to be wrong.
"""

from __future__ import annotations

from dataclasses import dataclass

from vg.config import ZoneConfig
from vg.features.base import FeatureWorker
from vg.infer.persons import DetectedPerson
from vg.infer.shared import SharedDetection
from vg.ingest.source import Frame


def feet_point(person: DetectedPerson) -> tuple[float, float]:
    """Where this person is standing: bottom-centre of the box."""
    return person.x + person.w / 2, person.y + person.h


def point_in_polygon(x: float, y: float, polygon: tuple[tuple[float, float], ...]) -> bool:
    """Ray casting. Counts crossings of a horizontal ray to the right.

    Handles concave shapes, which matters because real restricted areas are
    rarely rectangles — an L-shaped corridor or a lab bench cut-out would give
    the wrong answer under a bounding-box test.
    """
    inside = False
    count = len(polygon)
    j = count - 1

    for i in range(count):
        xi, yi = polygon[i]
        xj, yj = polygon[j]
        # Does the edge straddle the ray's height, and is the crossing to the right?
        if (yi > y) != (yj > y):
            crossing_x = (xj - xi) * (y - yi) / (yj - yi) + xi
            if x < crossing_x:
                inside = not inside
        j = i

    return inside


@dataclass(frozen=True)
class ZoneOccupancy:
    """How many people are standing in one zone, right now."""

    zone_id: str
    zone_name: str
    count: int
    enabled: bool
    # Indexes into the frame's people list, so the UI can highlight exactly
    # which boxes are the ones inside.
    occupants: tuple[int, ...] = ()


@dataclass(frozen=True)
class PeopleResult:
    """One frame's worth of people, plus which zones they are in."""

    people: tuple[DetectedPerson, ...] = ()
    zones: tuple[ZoneOccupancy, ...] = ()

    @property
    def count(self) -> int:
        return len(self.people)

    def zone(self, zone_id: str) -> ZoneOccupancy | None:
        return next((z for z in self.zones if z.zone_id == zone_id), None)


class PeopleWorker(FeatureWorker[PeopleResult]):
    """Person detection and zone occupancy.

    Independent of recognition: a camera set to `[counting]` alone is fully
    served by this worker and never loads a face model.
    """

    def __init__(
        self,
        bus,
        detector: SharedDetection,
        cameras: list[str],
        zones: dict[str, tuple[ZoneConfig, ...]] | None = None,
        rate_hz: float = 2.0,
        boost_hz: float = 12.0,
    ) -> None:
        super().__init__("people", bus, cameras, rate_hz, boost_hz)
        self.detector = detector
        # camera id -> its zones. Rebindable at runtime so drawing a new zone
        # takes effect without restarting the engine.
        self.zones = zones or {}

    def set_zones(self, camera_id: str, zones: tuple[ZoneConfig, ...]) -> None:
        self.zones[camera_id] = zones

    def analyse(self, frame: Frame) -> PeopleResult:
        people = tuple(self.detector.detect(frame))
        zones = self.zones.get(frame.camera_id, ())

        occupancy = []
        for zone in zones:
            occupants = tuple(
                i for i, person in enumerate(people)
                if point_in_polygon(*feet_point(person), zone.polygon)
            )
            occupancy.append(ZoneOccupancy(
                zone_id=zone.id,
                zone_name=zone.name,
                # A disabled zone still reports its occupancy. Pausing a zone
                # stops it alerting; it does not blind it, and the UI promises
                # a paused zone stays visible rather than going dark.
                count=len(occupants),
                enabled=zone.enabled,
                occupants=occupants,
            ))

        return PeopleResult(people=people, zones=tuple(occupancy))

    # -- reads --------------------------------------------------------------

    def count_on(self, camera_id: str) -> int | None:
        """People in frame, or None when nothing recent has measured it.

        None and 0 are different claims: 0 means the detector looked and the
        room is empty, None means nobody is looking at this camera.
        """
        payload = self.payload(camera_id)
        return payload.count if payload else None

    def people_on(self, camera_id: str) -> tuple[DetectedPerson, ...]:
        payload = self.payload(camera_id)
        return payload.people if payload else ()

    def zones_on(self, camera_id: str) -> tuple[ZoneOccupancy, ...]:
        payload = self.payload(camera_id)
        return payload.zones if payload else ()

    def zone_count(self, camera_id: str, zone_id: str) -> int | None:
        payload = self.payload(camera_id)
        if payload is None:
            return None
        occupancy = payload.zone(zone_id)
        return occupancy.count if occupancy else None
