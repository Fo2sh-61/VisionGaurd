"""Zone and station pictures draw one shape: the drawn polygon.

Found by eye on the merged console v2 branch (spec 025). `CameraFrame` draws a
camera's old one-zone overlay (`camera.zone`, the pre-025 "Restricted"
rectangle) even when `detections={false}`. Every zone and station picture went
through it, so a Work stations card showed a restricted-zone box over the
station - another feature's overlay on the page (rule 3) - and a Zones card
showed a stale rectangle beside the polygon actually being watched.

The demo store also drew its two stations on cameras it does not have
("i-lobby", "i-lab"), so `-Mock` showed both cards as "This camera is no longer
on the site".

The first half is a source check, for the reason `test_page_states.py` gives:
`web/` has no test runner, and a missing argument renders no differently from
a correct one until somebody looks.
"""

from __future__ import annotations

import re
from pathlib import Path

from vg.api.store import MockStore

WEB = Path(__file__).resolve().parents[2] / "web" / "src"


def frames_in(name: str) -> list[str]:
    source = (WEB / "components" / name).read_text(encoding="utf-8")
    return re.findall(r"<CameraFrame\b[^>]*>", source, flags=re.S)


def test_the_area_picture_and_editor_never_draw_the_old_zone_overlay():
    for name in ("AreaPicture.tsx", "AreaEditor.tsx"):
        frames = frames_in(name)
        assert frames, f"{name} no longer renders a CameraFrame; update this test"
        for tag in frames:
            assert "camera={withoutZone(camera)}" in tag, (
                f"{name}: a CameraFrame is given the camera with its old zone "
                f"overlay still on it: {tag}")
            assert "detections={false}" in tag, (
                f"{name}: a zone or station picture must not draw boxes, which "
                f"carry names: {tag}")


def test_without_zone_really_drops_the_overlay():
    source = (WEB / "components" / "AreaPicture.tsx").read_text(encoding="utf-8")
    assert re.search(r"return \{ \.\.\.camera, zone: undefined \};", source)


def test_demo_stations_are_drawn_on_cameras_the_demo_store_has():
    store = MockStore()
    cameras = {c.id for c in store.intrusion_cameras()}
    for station in store.stations():
        assert station.camera_id in cameras, (
            f"demo station {station.name!r} is on {station.camera_id!r}, which "
            f"the demo store does not have; the card reads 'camera gone'")
