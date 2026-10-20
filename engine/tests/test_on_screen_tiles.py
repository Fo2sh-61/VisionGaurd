"""Only a camera picture on screen moves, and it moves smoothly.

Found 28 Sep 2026 on the phone: the Home camera read as a slide show. It was
handed no rate, so it fell back to the camera frame's default of one picture
a second. Grids fared little better: their rate was worked out from how many
tiles the page had DRAWN, so ten cameras on the phone's Cameras page ran at 5
a second even with two in view - and the eight out of view kept asking.

Now every tile's rate is the screen's budget shared by the tiles ON SCREEN,
and a tile that is scrolled away, covered by an open camera, or in a
background tab asks for nothing.

Source checks, like `test_stream_release.py`: the repo has no browser test
runner, and neither bug shows in any state the engine can see - the engine
only ever sees the requests that do arrive. The arithmetic of the rate is also
asserted in `web/scripts/check-format.ts`.
"""

from __future__ import annotations

import re
from pathlib import Path

import pytest

from vg.ingest.source import MAX_TILE_FPS

ROOT = Path(__file__).resolve().parents[2]
APPS = ("web", "mobile")


def read(app: str, relative: str) -> str:
    return (ROOT / app / "src" / relative).read_text(encoding="utf-8")


def constant(source: str, name: str) -> float:
    match = re.search(rf"export const {name} = ([\d_]+);", source)
    assert match, f"{name} is not declared in services/frame.ts"
    return float(match.group(1).replace("_", ""))


class TestTheRate:
    """`tileRefreshMs` in services/frame.ts, which both apps share."""

    @staticmethod
    def fps(on_screen: int) -> float:
        frame = read("web", "services/frame.ts")
        budget = constant(frame, "SCREEN_PICTURES_PER_SECOND")
        top = constant(frame, "TILE_MAX_FPS")
        floor = constant(frame, "TILE_MIN_FPS")
        return min(top, max(floor, budget / max(1, on_screen)))

    def test_the_formula_is_the_one_checked_here(self):
        """The arithmetic below mirrors the function; pin its shape."""
        frame = read("web", "services/frame.ts")
        body = frame[frame.index("export function tileRefreshMs("):]
        body = body[:body.index("\n}\n")]
        assert "SCREEN_PICTURES_PER_SECOND / Math.max(1, onScreen)" in body
        assert "Math.min(TILE_MAX_FPS, Math.max(TILE_MIN_FPS, fps))" in body

    def test_a_camera_alone_on_its_screen_runs_at_the_full_rate(self):
        """The Home camera: one tile, and it was getting one picture a second."""
        assert self.fps(1) == MAX_TILE_FPS

    def test_a_phone_screen_of_tiles_all_run_at_the_full_rate(self):
        """A 360 x 780 phone shows at most eight tiles at once."""
        assert self.fps(8) == MAX_TILE_FPS

    def test_the_ceiling_is_the_engines_own(self):
        """Asking for more than the camera prepares fetches one picture twice."""
        frame = read("web", "services/frame.ts")
        assert constant(frame, "TILE_MAX_FPS") == MAX_TILE_FPS

    def test_a_wall_shares_the_budget_and_still_moves(self):
        assert self.fps(12) == 10
        assert self.fps(10_000) == constant(read("web", "services/frame.ts"), "TILE_MIN_FPS")


@pytest.mark.parametrize("app", APPS)
class TestNoPageSetsItsOwnRate:
    def test_the_camera_frame_has_no_default_rate_to_fall_back_to(self, app):
        source = read(app, "components/CameraFrame.tsx")
        assert "SNAPSHOT_REFRESH_MS" not in source, (
            "a default rate is what a page that passes none silently gets - "
            "that was one picture a second on the phone's Home screen")
        assert not re.search(r"^\s*refreshMs\?:", source, re.M), (
            "a rate handed in by the page is worked out from a count that "
            "goes stale as tiles scroll; the tile works it out itself")
        # On the factory network from the tiles on screen; away from it the
        # engine's own pace (spec 020) - never a number a page passed in.
        assert ("const refreshMs = remote && connection\n"
                "    ? connection.tileIntervalSeconds * 1_000\n"
                "    : tileRefreshMs(tilesShowing);") in source

    def test_no_page_hands_a_tile_a_rate(self, app):
        offenders = [
            str(path.relative_to(ROOT))
            for path in (ROOT / app / "src").rglob("*.tsx")
            if re.search(r"\b(refreshMs|boxRefreshMs)=\{", path.read_text(encoding="utf-8"))
        ]
        assert offenders == []


@pytest.mark.parametrize("app", APPS)
class TestATileNobodyCanSeeAsksForNothing:
    def test_it_knows_when_it_is_on_screen_and_when_the_tab_is_hidden(self, app):
        source = read(app, "components/CameraFrame.tsx")
        assert "new IntersectionObserver(" in source
        assert "'visibilitychange'" in source
        assert "const showing = onScreen && pageVisible && !paused;" in source

    def test_the_pictures_stop(self, app):
        source = read(app, "components/CameraFrame.tsx")
        assert "const polling = usePolling && showing;" in source
        assert re.search(r"if \(!polling\) \{\s*wasPolling\.current = false;\s*return;", source), (
            "the picture timer must not run while the tile is not showing")

    def test_a_paused_tile_does_not_change_its_address(self, app):
        """A new address is a new request. The address is built only while
        polling, once per tick - not on every render, where a change in the
        tile's share of the budget would re-ask for a picture."""
        source = read(app, "components/CameraFrame.tsx")
        assert re.search(
            r"polling && \(asked === null \|\| asked\.tick !== tick", source)

    def test_the_stream_is_let_go(self, app):
        """An open MJPEG response makes the engine convert every frame."""
        source = read(app, "components/CameraFrame.tsx")
        assert "(showing ? camera.streamUrl : undefined)" in source

    def test_the_boxes_stop_unless_the_page_shows_what_they_report(self, app):
        """A tile's boxes are only drawn on its picture, so they stop with it.
        The phone's camera screen lists who is in view UNDER the picture, and
        scrolling down to read it must not empty it - the review of this
        change caught exactly that - so a view with `onCount`/`onBoxes`
        keeps asking while the tab is in front, once a second."""
        source = read(app, "components/CameraFrame.tsx")
        assert ("(useStream || tileOverlay) && detections && pageVisible && !paused "
                "&& (onScreen || reported);") in source
        assert "const reported = !!(onCount || onBoxes);" in source
        assert "(onScreen ? DETECTION_REFRESH_MS : OFF_SCREEN_REPORT_MS)" in source
        assert "onCount?.(null)" not in source, (
            "stopping the poll must not empty a list the page is still showing")

    def test_a_tile_handed_another_camera_drops_the_last_ones_picture(self, app):
        """Home and Track reuse one tile for a new camera; an address held
        only by tick showed the old camera under the new name."""
        source = read(app, "components/CameraFrame.tsx")
        assert "asked.from !== snapshotUrl" in source
        assert "usePolling && asking?.from === snapshotUrl" in source

    def test_an_open_camera_pauses_the_grid_under_it(self, app):
        assert "paused={open !== null}" in read(app, "components/CamGrid.tsx")

    def test_the_grid_headcounts_stop_with_the_tab(self, app):
        grid = read(app, "components/CamGrid.tsx")
        assert "if (!pageVisible) return;" in grid
