"""Config loading and schedule evaluation.

The schedule tests matter more than they look: a wrong answer here means either
a silent security hole (zone never fires) or an alert storm (fires all day).

Run:  python -m pytest engine/tests -q
"""

from __future__ import annotations

import sys
from datetime import datetime, time as dtime
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from vg import config as cfg  # noqa: E402


# --- helpers ---------------------------------------------------------------

def at(day: str, hhmm: str) -> datetime:
    """A datetime on a known weekday. 2026-08-03 is a Monday."""
    monday = 3
    offset = ["mon", "tue", "wed", "thu", "fri", "sat", "sun"].index(day)
    hh, mm = (int(x) for x in hhmm.split(":"))
    return datetime(2026, 8, monday + offset, hh, mm)


# --- schedule --------------------------------------------------------------

class TestScheduleOutside:
    """'outside' = a lab that is off-limits except during its open hours."""

    schedule = cfg.Schedule(
        mode="outside",
        days=("mon", "tue", "wed", "thu", "fri"),
        start=dtime(8, 0),
        end=dtime(16, 0),
    )

    @pytest.mark.parametrize("when", ["06:12", "07:59", "16:00", "23:30", "00:01"])
    def test_restricted_out_of_hours(self, when):
        assert self.schedule.is_restricted_at(at("wed", when)) is True

    @pytest.mark.parametrize("when", ["08:00", "12:00", "15:59"])
    def test_open_during_hours(self, when):
        assert self.schedule.is_restricted_at(at("wed", when)) is False

    def test_weekend_is_restricted_all_day(self):
        # The lab is only open on weekdays, so Saturday noon is still a breach.
        assert self.schedule.is_restricted_at(at("sat", "12:00")) is True
        assert self.schedule.is_restricted_at(at("sun", "12:00")) is True


class TestScheduleInside:
    """'inside' = an exam hall, off-limits only while a session is running."""

    schedule = cfg.Schedule(
        mode="inside",
        days=("mon", "tue", "wed", "thu", "fri"),
        start=dtime(9, 0),
        end=dtime(11, 0),
    )

    def test_restricted_during_window(self):
        assert self.schedule.is_restricted_at(at("tue", "10:00")) is True

    def test_free_outside_window(self):
        assert self.schedule.is_restricted_at(at("tue", "08:59")) is False
        assert self.schedule.is_restricted_at(at("tue", "11:00")) is False

    def test_free_on_unscheduled_day(self):
        # No exam on Saturday, so nothing is restricted.
        assert self.schedule.is_restricted_at(at("sat", "10:00")) is False


class TestScheduleAlways:
    def test_always_restricted(self):
        schedule = cfg.Schedule(mode="always")
        assert schedule.is_restricted_at(at("mon", "03:00")) is True
        assert schedule.is_restricted_at(at("sun", "14:00")) is True


class TestScheduleMidnightCrossing:
    """A window that wraps past midnight — the case an off-by-one loves."""

    schedule = cfg.Schedule(
        mode="inside", days=tuple(cfg.WEEKDAYS), start=dtime(22, 0), end=dtime(6, 0)
    )

    @pytest.mark.parametrize("when", ["22:00", "23:59", "00:00", "05:59"])
    def test_inside_the_wrapped_window(self, when):
        assert self.schedule.is_restricted_at(at("thu", when)) is True

    @pytest.mark.parametrize("when", ["06:00", "12:00", "21:59"])
    def test_outside_the_wrapped_window(self, when):
        assert self.schedule.is_restricted_at(at("thu", when)) is False


class TestScheduleParsing:
    def test_defaults_to_always(self):
        assert cfg.Schedule.parse(None, "z").mode == "always"

    def test_accepts_several_time_formats(self):
        s = cfg.Schedule.parse(
            {"mode": "outside", "from": "8:00", "to": "4:00PM"}, "z"
        )
        assert s.start == dtime(8, 0)
        assert s.end == dtime(16, 0)

    def test_rejects_unknown_mode(self):
        with pytest.raises(cfg.ConfigError, match="expected outside"):
            cfg.Schedule.parse({"mode": "sometimes"}, "z")

    def test_rejects_bad_weekday(self):
        with pytest.raises(cfg.ConfigError, match="not a weekday"):
            cfg.Schedule.parse({"days": ["funday"]}, "z")

    def test_windowed_mode_requires_both_times(self):
        with pytest.raises(cfg.ConfigError, match="needs both"):
            cfg.Schedule.parse({"mode": "outside", "from": "08:00"}, "z")

    def test_rejects_unparseable_time(self):
        with pytest.raises(cfg.ConfigError, match="cannot parse time"):
            cfg.Schedule.parse({"mode": "inside", "from": "half eight", "to": "9"}, "z")


# --- zones -----------------------------------------------------------------

class TestZoneConfig:
    base = {"id": "z1", "name": "Lab", "camera": "cam-1"}

    def test_rect_shorthand_becomes_a_polygon(self):
        zone = cfg.ZoneConfig.parse({**self.base, "rect": [0.1, 0.2, 0.5, 0.6]}, "z")
        assert zone.polygon == ((0.1, 0.2), (0.6, 0.2), (0.6, 0.8), (0.1, 0.8))

    def test_explicit_polygon_kept(self):
        pts = [[0.0, 0.0], [1.0, 0.0], [0.5, 1.0]]
        zone = cfg.ZoneConfig.parse({**self.base, "polygon": pts}, "z")
        assert len(zone.polygon) == 3

    def test_rejects_pixel_coordinates(self):
        # The commonest mistake: pasting pixels into a normalised field.
        with pytest.raises(cfg.ConfigError, match="outside 0-1"):
            cfg.ZoneConfig.parse({**self.base, "rect": [100, 200, 300, 400]}, "z")

    def test_rejects_degenerate_polygon(self):
        with pytest.raises(cfg.ConfigError, match=">=3 points"):
            cfg.ZoneConfig.parse({**self.base, "polygon": [[0.1, 0.1], [0.2, 0.2]]}, "z")

    def test_requires_a_camera(self):
        with pytest.raises(cfg.ConfigError, match="missing required key 'camera'"):
            cfg.ZoneConfig.parse({"id": "z1", "name": "Lab", "rect": [0, 0, 1, 1]}, "z")


# --- cameras ---------------------------------------------------------------

class TestCameraConfig:
    def test_password_is_masked_for_logging(self):
        cam = cfg.CameraConfig.parse(
            {
                "id": "c1",
                "name": "Gate",
                "source": "rtsp://admin:hunter2@192.168.1.64:554/Streaming/102",
            },
            "c",
        )
        redacted = cam.redacted_source()
        assert "hunter2" not in redacted
        assert "admin" in redacted and "192.168.1.64" in redacted

    def test_rejects_odd_rotation(self):
        with pytest.raises(cfg.ConfigError, match="0/90/180/270"):
            cfg.CameraConfig.parse(
                {"id": "c", "name": "n", "source": "webcam:0", "rotate": 45}, "c"
            )

    def test_rejects_impossible_fps(self):
        with pytest.raises(cfg.ConfigError, match="0 < fps"):
            cfg.CameraConfig.parse(
                {"id": "c", "name": "n", "source": "webcam:0", "fps": 0}, "c"
            )


# --- env expansion ---------------------------------------------------------

class TestEnvExpansion:
    def test_uses_default_when_unset(self, monkeypatch):
        monkeypatch.delenv("VG_TEST_ONLY", raising=False)
        assert cfg._expand("${VG_TEST_ONLY:fallback}", "w") == "fallback"

    def test_env_wins_over_default(self, monkeypatch):
        monkeypatch.setenv("VG_TEST_ONLY", "real")
        assert cfg._expand("${VG_TEST_ONLY:fallback}", "w") == "real"

    def test_missing_without_default_is_a_clear_error(self, monkeypatch):
        monkeypatch.delenv("VG_TEST_ONLY", raising=False)
        with pytest.raises(cfg.ConfigError, match="engine/.env"):
            cfg._expand("${VG_TEST_ONLY}", "cameras[0].source")

    def test_expands_inside_nested_structures(self, monkeypatch):
        monkeypatch.setenv("VG_TEST_ONLY", "x")
        out = cfg._expand({"a": [{"b": "${VG_TEST_ONLY}"}]}, "w")
        assert out == {"a": [{"b": "x"}]}


# --- the real engine.yaml --------------------------------------------------

@pytest.fixture(scope="module")
def loaded():
    return cfg.load()


class TestShippedConfig:
    """The committed engine.yaml must actually load."""

    def test_loads(self, loaded):
        assert loaded.cameras

    def test_ships_without_a_customer_name(self, loaded):
        # engine.yaml leaves site_name blank on purpose — the product is not
        # sold to one school. YAML reads a blank key as None, and str(None)
        # would print the word "None" under the product name in the console.
        assert loaded.site_name == ""

    def test_every_zone_points_at_a_real_camera(self, loaded):
        ids = {c.id for c in loaded.cameras}
        for zone in loaded.zones:
            assert zone.camera_id in ids

    def test_declared_model_weights_exist_on_disk(self, loaded):
        """Every model engine.yaml names must be a file on this machine.

        This checks the machine, not the code. The weights are 1.2 GB tracked
        out of band, so a fresh clone has none of them and CI never will. A
        checkout with nothing to check is not a failing checkout, so it skips
        with a reason rather than turning CI permanently red.

        It only skips when *no* weights are present. If some are there and
        others are not, that is a half-finished local install and still a real
        failure — which is the case this test was written to catch.
        """
        present = [m.name for m in loaded.models.values() if m.exists()]
        if not present:
            pytest.skip(
                "no model weights on this machine (1.2 GB, tracked out of "
                "band) - nothing to check"
            )
        missing = [m.name for m in loaded.models.values() if not m.exists()]
        assert not missing, f"engine.yaml points at missing weights: {missing}"

    def test_no_engine_files_are_referenced(self, loaded):
        # .engine is GPU- and TensorRT-locked; it is a build output, never the
        # configured artifact. Catch it here rather than on the workstation.
        bad = [m.name for m in loaded.models.values() if m.weights.suffix == ".engine"]
        assert not bad, f"config points at TensorRT engines: {bad}"

    def test_duplicate_camera_ids_rejected(self):
        with pytest.raises(cfg.ConfigError, match="duplicate camera id"):
            cfg._reject_duplicates(["a", "b", "a"], "camera")


class TestHours:
    """School hours bound what counts as an arrival."""

    def test_defaults_are_a_school_day(self):
        hours = cfg.HoursConfig.parse(None, "hours")
        assert hours.start == dtime(7, 30) and hours.end == dtime(15, 0)
        assert hours.late_cutoff == dtime(8, 0)

    def test_parses_the_shipped_shape(self):
        hours = cfg.HoursConfig.parse(
            {"from": "07:00", "to": "16:00", "late_cutoff": "08:15"}, "hours"
        )
        assert hours.start == dtime(7, 0)
        assert hours.end == dtime(16, 0)
        assert hours.late_cutoff == dtime(8, 15)

    def test_cutoff_outside_school_hours_is_rejected(self):
        # A cutoff before the day starts means nobody can ever be on time; one
        # after it ends means nobody can ever be late. Both are silent nonsense.
        with pytest.raises(cfg.ConfigError, match="must fall between"):
            cfg.HoursConfig.parse(
                {"from": "07:30", "to": "15:00", "late_cutoff": "06:00"}, "hours"
            )
        with pytest.raises(cfg.ConfigError, match="must fall between"):
            cfg.HoursConfig.parse(
                {"from": "07:30", "to": "15:00", "late_cutoff": "17:00"}, "hours"
            )

    def test_shipped_config_has_usable_hours(self, loaded):
        assert loaded.hours.start < loaded.hours.late_cutoff <= loaded.hours.end


# --- gate cameras ----------------------------------------------------------

BASE_CAMERA = {"id": "g1", "name": "Gate 1 in", "source": "rtsp://x/1"}


def camera(**extra):
    return cfg.CameraConfig.parse({**BASE_CAMERA, **extra}, "cameras[0]")


class TestGateCameras:
    """`gate` and `direction` are what give a plate read its meaning.

    Without them a pass is "a car went past something, somehow", which is not
    a record of anything. These tests pin the three ways that can go wrong:
    a guessed direction, a gate with no feature, and a feature with no gate.
    """

    def test_a_gate_camera_parses(self):
        cam = camera(gate=1, direction="entry", features=["vehicles"])

        assert cam.gate == 1
        assert cam.direction == "entry"
        assert cam.is_gate

    def test_direction_is_case_and_space_insensitive(self):
        assert camera(gate=2, direction="  EXIT ", features=["vehicles"]).direction == "exit"

    def test_both_is_refused_and_says_why(self):
        """The whole reason this field exists rather than being inferred.

        A single camera can guess direction from whether the plate grows or
        shrinks, and the project this technique came from calls that
        "noticeably less reliable". A guess deciding whether a car is recorded
        as arriving or leaving is exactly the untruth rule 4 forbids.
        """
        with pytest.raises(cfg.ConfigError, match="one camera per direction"):
            camera(gate=1, direction="both", features=["vehicles"])

    def test_an_unknown_direction_is_refused(self):
        with pytest.raises(cfg.ConfigError, match="expected one of"):
            camera(gate=1, direction="inwards", features=["vehicles"])

    def test_a_gate_number_must_be_positive(self):
        with pytest.raises(cfg.ConfigError, match="positive"):
            camera(gate=0, direction="entry", features=["vehicles"])

    def test_the_feature_without_a_gate_is_refused(self):
        """Half-configured is worse than not configured: the worker would run
        and have nowhere honest to file what it saw."""
        with pytest.raises(cfg.ConfigError, match="no gate/direction"):
            camera(features=["vehicles"])

    def test_a_gate_without_the_feature_is_refused(self):
        """Reads like a configured gate. Watches nothing."""
        with pytest.raises(cfg.ConfigError, match="watching nothing"):
            camera(gate=1, direction="entry")

    def test_every_other_camera_is_untouched(self):
        """The fields are additive. A camera written before Vehicle gate
        existed must parse exactly as it did, and not become a gate."""
        cam = camera(features=["attendance", "counting"])

        assert cam.gate is None
        assert cam.direction is None
        assert not cam.is_gate

    def test_the_shipped_config_has_one_gate_camera(self, loaded):
        gates = [c for c in loaded.cameras if c.is_gate]

        assert len(gates) == 1, "engine.yaml should ship exactly one gate camera"
        assert gates[0].direction == "entry"
        # There is no exit camera yet, and the Movements tab must say so
        # rather than print a paired figure it cannot compute (P6-FR-012).
        assert not [c for c in loaded.cameras if c.direction == "exit"]
