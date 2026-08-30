"""The plate box, from the reader to the wire — the whole journey.

**This file exists because the last fix for this bug fixed the wrong half.**

Gate tiles had never once drawn a plate box. On 24 Aug that was diagnosed as
the overlay *request* being refused by validation, fixed, and pinned by a test.
The boxes still did not draw, because the failure had moved one layer down: the
*response* carried `kind="plate"` and `schemas.Box.kind` was a `Literal` that
did not include it, so every detections response containing a plate raised
instead of returning. Nothing caught it — no test had ever built a plate box
through the schema.

So the rule for this file: **assert on the far end of the path, never the near
end.** A test that calls `_plate_boxes` and stops has not proved a box reaches
a screen. Every test here ends at a validated `CameraView`, which is the object
the endpoint actually returns.

P6-FR-042.
"""

from __future__ import annotations

import pytest

from vg import config as vgconfig
from vg import platetext
from vg.api import schemas as S
from vg.api.live import LiveStore
from vg.events.vehicles import VehicleStore
from vg.infer.plates import PlateBox, PlateRead
from vg.ingest.registry import CameraRegistry

#: The frame the boxes are measured against. Real numbers rather than 1x1, so
#: that a fraction which is wrong by a factor of the frame size shows up as a
#: wrong fraction rather than as a clamp to 1.0.
FRAME_W, FRAME_H = 1920, 1080

#: One plate, 134 px wide — comfortably over the 100 px line the console
#: colours at and the 60 px floor the reader refuses below.
PLATE = PlateBox(x1=700, y1=760, x2=834, y2=812, confidence=0.94)


class _Frame:
    width, height = FRAME_W, FRAME_H
    captured_at = None


class _CameraWorker:
    """A camera that is up and has a frame. Enough for `camera_view`."""

    def __init__(self, config):
        self.config = config
        self.status = "ok"

    def last_frame(self):
        return _Frame()


class _Reading:
    """A vehicles worker that can see exactly one plate."""

    def __init__(self, read: PlateRead | None):
        self._read = read

    def plates_on(self, camera_id):
        return [self._read] if self._read is not None else []


def _read(text: str = "بجد 1234", confidence: float = 0.94) -> PlateRead:
    return PlateRead(box=PLATE, text=text, confidence=confidence)


@pytest.fixture
def gate(tmp_path):
    """A live store whose gate camera is up, with a register to match against.

    The registry gets a stub worker injected rather than a started one: this
    is about what the API builds from a reading, and starting a camera would
    make the test depend on a device.
    """
    cfg = vgconfig.load()
    camera = next((c for c in cfg.cameras if c.gate), cfg.cameras[0])
    registry = CameraRegistry([])
    registry.workers[camera.id] = _CameraWorker(camera)

    vehicles = VehicleStore(tmp_path / "vehicles.db")
    store = LiveStore(config=cfg, registry=registry, vehicle_store=vehicles)
    try:
        yield store, camera.id, vehicles
    finally:
        vehicles.close_db()


def _boxes_on_screen(store, camera_id) -> list[S.Box]:
    """The boxes as the endpoint would return them — through `CameraView`.

    Re-validating the dumped view is the point of the helper. `CameraView`
    holding a `Box` proves the box was constructible; round-tripping it proves
    it is also *serialisable*, which is the step the endpoint performs and the
    one that was failing.
    """
    view = store.camera_view(camera_id, feature="vehicles")
    assert view is not None, "the stub camera should produce a view"
    S.CameraView.model_validate(view.model_dump(by_alias=True))
    return view.boxes


class TestAPlateReachesTheScreen:
    """The bug, stated as the thing that must be true."""

    def test_a_plate_in_view_becomes_a_box_on_the_tile(self, gate):
        store, camera_id, _ = gate
        store.vehicles_worker = _Reading(_read())

        boxes = _boxes_on_screen(store, camera_id)

        assert len(boxes) == 1, "one plate in view, one box on the tile"
        assert boxes[0].kind == "plate"

    def test_the_box_is_where_the_plate_was(self, gate):
        """Fractions of the frame, never pixels. Rule 6."""
        store, camera_id, _ = gate
        store.vehicles_worker = _Reading(_read())

        box = _boxes_on_screen(store, camera_id)[0]

        assert box.x == pytest.approx(700 / FRAME_W)
        assert box.y == pytest.approx(760 / FRAME_H)
        assert box.w == pytest.approx(134 / FRAME_W)
        assert box.h == pytest.approx(52 / FRAME_H)
        assert all(0.0 <= v <= 1.0 for v in (box.x, box.y, box.w, box.h))

    def test_the_box_carries_the_plate_width_in_pixels(self, gate):
        """The aiming aid.

        A fraction cannot answer "is this plate big enough to read" without the
        capture resolution, which the console does not have. The engine
        measured it in pixels, so the engine sends it in pixels — display
        information, not geometry.
        """
        store, camera_id, _ = gate
        store.vehicles_worker = _Reading(_read())

        assert _boxes_on_screen(store, camera_id)[0].plate_width_px == 134

    def test_the_label_is_the_plate_and_never_a_person(self, gate):
        """Rule 1: a plate names a car, never whoever is driving it."""
        store, camera_id, vehicles = gate
        vehicles.add(plate="بجد 1234", owner_name="Mohamed Fouad",
                     category="staff")
        store.vehicles_worker = _Reading(_read())

        label = _boxes_on_screen(store, camera_id)[0].label

        # Indic digits, not ASCII: the label is the plate as it reads on the
        # car, which is what `platetext.display` exists to produce.
        assert platetext.to_arabic_digits("1234") in label
        assert "Mohamed" not in label, "the owner must never be painted on a car"

    def test_a_plate_that_read_nothing_still_draws(self, gate):
        """The car was there. Saying so is not the same as naming it."""
        store, camera_id, _ = gate
        store.vehicles_worker = _Reading(_read(text="", confidence=0.0))

        box = _boxes_on_screen(store, camera_id)[0]

        assert box.kind == "plate"
        assert box.label == "Plate"


class TestTheColourSaysWhatTheRegisterSays:
    """Severity is what `boxColor()` paints, so it is part of the contract."""

    @pytest.mark.parametrize("category, expected", [
        ("staff", S.Severity.INFO),        # registered  -> green
        ("visitor", S.Severity.INFO),      # registered  -> green
        ("blacklist", S.Severity.CRITICAL),  # withdrawn -> red
    ])
    def test_a_registered_car_is_coloured_by_its_category(
            self, gate, category, expected):
        store, camera_id, vehicles = gate
        vehicles.add(plate="بجد 1234", owner_name="Someone", category=category)
        store.vehicles_worker = _Reading(_read())

        assert _boxes_on_screen(store, camera_id)[0].severity is expected

    def test_a_car_nobody_knows_is_a_warning_not_an_alarm(self, gate):
        store, camera_id, _ = gate
        store.vehicles_worker = _Reading(_read())

        assert _boxes_on_screen(store, camera_id)[0].severity is S.Severity.WARN

    def test_an_expired_permit_is_a_warning(self, gate):
        store, camera_id, vehicles = gate
        vehicles.add(plate="بجد 1234", owner_name="Hoda Kamel",
                     category="visitor", valid_until="2020-01-01")
        store.vehicles_worker = _Reading(_read())

        assert _boxes_on_screen(store, camera_id)[0].severity is S.Severity.WARN


class TestThePlateStaysOnItsOwnPage:
    """Rule 3: each feature draws its own overlay."""

    def test_no_other_feature_shows_a_plate(self, gate):
        store, camera_id, _ = gate
        store.vehicles_worker = _Reading(_read())

        for feature in ("attendance", "counting", "track", "weapons", None):
            view = store.camera_view(camera_id, feature=feature)
            kinds = {b.kind for b in view.boxes}
            assert "plate" not in kinds, f"{feature} drew a plate box"

    def test_nothing_is_drawn_when_plates_are_not_being_read(self, gate):
        """No worker is not an empty gate — but it draws nothing either way."""
        store, camera_id, _ = gate
        store.vehicles_worker = None

        assert _boxes_on_screen(store, camera_id) == []
