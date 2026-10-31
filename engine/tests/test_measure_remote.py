"""engine/tools/measure_remote.py — the numbers it writes down must be honest.

The tool's whole job is a table somebody will make a decision from, so the
arithmetic is pinned here: percentiles, the clock offset and its uncertainty,
frame counting on a real-shaped MJPEG stream, failures kept out of timings,
and the comparison built from saved runs.
"""

from __future__ import annotations

import json
import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "tools"))

import measure_remote as mr  # noqa: E402


class TestPercentile:
    def test_nearest_rank(self):
        values = list(range(1, 101))
        assert mr.percentile(values, 50) == 50
        assert mr.percentile(values, 95) == 95

    def test_nothing_measured_is_none_not_zero(self):
        assert mr.percentile([], 50) is None
        assert mr.summarise([], 3) == {"n": 0, "failures": 3, "p50Ms": None, "p95Ms": None}

    def test_failures_are_counted_not_timed(self):
        summary = mr.summarise([10.0, 20.0], failures=5)
        assert summary["n"] == 2 and summary["failures"] == 5
        assert summary["p95Ms"] == 20.0


class TestClockOffset:
    def test_uses_the_shortest_round_trip(self):
        samples = [
            (0.0, 5_000.0, 400.0),     # slow: server reading is loose
            (1_000.0, 6_010.0, 1_020.0),  # fast: 20 ms round trip
        ]
        clock = mr.clock_offset(samples)
        assert clock["offsetMs"] == pytest.approx(5_000.0)
        assert clock["uncertaintyMs"] == 10.0
        assert clock["samples"] == 2

    def test_no_samples(self):
        assert mr.clock_offset([])["offsetMs"] is None


class TestFrameCounting:
    def test_counts_pictures_in_an_mjpeg_body(self):
        frame = b"\xff\xd8" + b"\x00\xff\x00" * 50 + b"\xff\xd9"
        part = b"--frame\r\nContent-Type: image/jpeg\r\n\r\n" + frame + b"\r\n"
        body = part * 7
        found, _ = mr.count_jpegs(body)
        assert found == 7

    def test_a_marker_split_across_two_reads_is_counted_once(self):
        frame = b"\xff\xd8" + b"\x00" * 10
        cut = 1  # between 0xFF and 0xD8
        first, tail = mr.count_jpegs(frame[:cut])
        second, _ = mr.count_jpegs(frame[cut:], tail)
        assert first + second == 1


class TestInstant:
    def test_wire_instant_to_ms(self):
        assert mr.instant_ms({"utc": "1970-01-01T00:00:01Z", "tzOffsetMinutes": 0}) == 1000
        assert mr.instant_ms(None) is None
        assert mr.instant_ms({"utc": None}) is None


def _run(label: str, started: str, **over) -> dict:
    run = {
        "label": label, "url": f"http://{label}", "camera": "cam-clip",
        "started": started, "minutes": 6,
        "clock": {"offsetMs": 3.0, "uncertaintyMs": 12.0, "samples": 20},
        "reads": {"/healthz": {"n": 30, "failures": 0, "p50Ms": 4.0, "p95Ms": 9.0}},
        "tiles": {"n": 800, "failures": 0, "p50Ms": 30.0, "p95Ms": 60.0,
                  "seconds": 60.0, "perSecond": 13.3, "meanBytes": 40960},
        "stream": {"seconds": 30.0, "frames": 150, "perSecond": 5.0, "failures": 0},
        "boxes": {"n": 300, "failures": 0, "ageP50Ms": 120.0, "ageP95Ms": 300.0},
        "events": {"seen": 9, "failures": 0, "ageP50Ms": 2600.0, "ageP95Ms": 3100.0,
                   "seconds": 206.8, "dwellSeconds": 2.0},
        "server": {"start": {"gpuPercent": 30.0}, "end": None},
    }
    run.update(over)
    return run


class TestComparison:
    def test_one_column_per_label_latest_run_wins(self, tmp_path):
        (tmp_path / "local-1.json").write_text(json.dumps(_run("local", "2026-10-31T10:00")))
        (tmp_path / "local-2.json").write_text(json.dumps(_run(
            "local", "2026-10-31T11:00",
            tiles={"n": 1, "failures": 0, "p50Ms": 1.0, "p95Ms": 1.0,
                   "seconds": 60.0, "perSecond": 14.9, "meanBytes": 1})))
        (tmp_path / "cloud-1.json").write_text(json.dumps(_run("cloud", "2026-10-31T12:00")))
        (tmp_path / "notes.json").write_text("[]")  # not a run: ignored

        text = mr.write_comparison(tmp_path).read_text()
        header = next(line for line in text.splitlines() if line.startswith("| Measure"))
        assert "local" in header and "cloud" in header
        assert "14.9" in text and "13.3" in text

    def test_ages_carry_the_clock_uncertainty(self):
        rows = mr.rows_for(_run("cloud", "2026-10-31T12:00"))
        assert rows["Box age when it arrives p50"] == "120 ms ± 12"

    def test_failures_are_shown_beside_the_timing(self):
        run = _run("cloud", "2026-10-31T12:00",
                   reads={"/cameras": {"n": 20, "failures": 10, "p50Ms": 50.0, "p95Ms": 90.0}})
        assert "10 failed" in mr.rows_for(run)["Read /cameras p50 / p95"]

    def test_breaches_say_how_long_they_were_watched_for(self):
        rows = mr.rows_for(_run("cloud", "2026-10-31T12:00"))
        assert rows["Breaches seen (in this many seconds)"] == "9 (in 206.8 s)"

    def test_nothing_measured_reads_as_a_dash(self):
        run = _run("cloud", "2026-10-31T12:00",
                   boxes={"n": 0, "failures": 300, "ageP50Ms": None, "ageP95Ms": None})
        assert mr.rows_for(run)["Box age when it arrives p50"] == "—"


class TestRefusesWithoutAnswer:
    def test_an_address_that_does_not_answer_exits_1(self, tmp_path):
        code = mr.main(["--url", "http://127.0.0.1:9", "--label", "x",
                        "--email", "a@b.c", "--out", str(tmp_path)])
        assert code == 1
        assert not list(tmp_path.glob("x-*.json"))
