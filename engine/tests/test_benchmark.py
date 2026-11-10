"""The site sizing arithmetic in `engine/tools/benchmark.py`.

Workload placement reported 9.17 cores for 100 cameras by costing
`live_capture: watched` as "skip the decode on four frames in five". On
OpenCV's FFmpeg backend `grab()` IS the decode; `retrieve()` only turns the
decoded frame into pixels. So an unwatched camera skips the retrieve() share
of a frame and still pays for every decode. These pin the arithmetic so the
old claim cannot come back quietly.

Nothing here times anything real - the figures are fed in - except the one
test that runs the decode split over a tiny generated clip, and that checks
only that it counts the frames and keeps the share inside 0..1.

`TestHardwareDecode` covers `--hw` and `--streams`, added 12 Sep 2026. Same
rule: no figure is asserted, because every machine answers differently. What
is pinned is that the tool cannot report a graphics chip's name over numbers
the processor produced - which is what OpenCV does by default when a chip
will not decode a file.
"""

import importlib.util
import sys
from pathlib import Path

import cv2
import numpy as np
import pytest

TOOL = Path(__file__).resolve().parents[1] / "tools" / "benchmark.py"

#: The 30 Aug after-run's mix, and its person timing: 2.57 cores over 100
#: cameras at 2 Hz. Recovered from its published total, 9.17.
MIX = "person=1.0@2,faces=0.15@5,plates=0.05@5"
PERSON_MS = 12.85


@pytest.fixture(scope="module")
def bench():
    # Registered before it runs: `@dataclass` looks its own module up in
    # sys.modules, and a script loaded by path is not there otherwise.
    spec = importlib.util.spec_from_file_location("vg_tool_benchmark", TOOL)
    module = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = module
    try:
        spec.loader.exec_module(module)
        yield module
    finally:
        sys.modules.pop(spec.name, None)


def _total(bench, share, decode_hz):
    rows = bench._demand(100, bench._parse_mix(MIX), PERSON_MS, decode_hz, share)
    return sum(row[-1] for row in rows)


class TestCaptureArithmetic:
    @pytest.fixture(autouse=True)
    def the_12_sep_figures(self, bench, monkeypatch):
        """These tests replay the 30 Aug / 12 Sep arithmetic, so they pin the
        figures it ran on. The defaults moved to a real NVR on 5 Nov 2026."""
        monkeypatch.setitem(bench.ASSUMED_MS, "decode", 6.0)
        monkeypatch.setitem(bench.ASSUMED_MS, "faces", 44.0)
        monkeypatch.setitem(bench.ASSUMED_MS, "patrol", 44.0)
        monkeypatch.setitem(bench.ASSUMED_MS, "plates", 12.0)
        monkeypatch.setattr(bench, "CAMERA_FPS", 25.0)

    def test_the_published_after_figure_needed_retrieve_to_be_the_whole_decode(self, bench):
        # 9.17 is exactly what you get if retrieve() were 100% of a frame's
        # cost - the assumption this test file exists to retire.
        assert _total(bench, share=1.0, decode_hz=5) == pytest.approx(9.17, abs=0.01)

    def test_an_unwatched_camera_still_decodes_every_frame(self, bench):
        rows = {row[0]: row for row in bench._demand(
            100, bench._parse_mix(MIX), PERSON_MS, 5, 0.10)}

        assert rows["grab"][2] == bench.CAMERA_FPS
        assert rows["grab"][4] == pytest.approx(100 * 25 * 6.0 * 0.90 / 1000)
        assert rows["retrieve"][2] == 5
        assert rows["retrieve"][4] == pytest.approx(100 * 5 * 6.0 * 0.10 / 1000)
        # The old arithmetic charged 3.00 cores for capture here.
        assert rows["grab"][4] + rows["retrieve"][4] == pytest.approx(13.80)

    def test_nothing_measured_means_watched_saves_nothing(self, bench):
        assert _total(bench, share=0.0, decode_hz=5) == pytest.approx(
            _total(bench, share=0.0, decode_hz=25))

    def test_the_before_figure_does_not_depend_on_the_split(self, bench):
        # Every frame retrieved: grab + retrieve is the whole 6 ms either way.
        before = _total(bench, share=1.0, decode_hz=25)
        for share in (0.0, 0.1, 0.41):
            assert _total(bench, share, decode_hz=25) == pytest.approx(before)

    def test_the_headline_is_the_cautious_end_and_the_other_end_is_shown(self, bench, capsys):
        bench._site(100, MIX, PERSON_MS, 8, decode_hz=5, shares=[0.41, 0.10])
        out = capsys.readouterr().out

        assert "19.97 cores working flat out" in out    # 10%: the bigger bill
        assert "16.25 cores" in out                      # 41%: printed beside it
        assert "about 40 cameras" in out

    def test_no_measurement_says_so(self, bench, capsys):
        bench._site(100, MIX, PERSON_MS, 8, decode_hz=5, shares=[])
        out = capsys.readouterr().out

        assert "NOT measured" in out
        assert "21.17 cores working flat out" in out     # no saving credited

    def test_the_unit_is_cores_not_seconds_per_second(self, bench, capsys):
        bench._site(100, MIX, PERSON_MS, 8, decode_hz=5, shares=[0.1])
        out = capsys.readouterr().out

        assert "s/s" not in out
        assert "cores" in out


class TestDecodeSplit:
    def test_counts_every_frame_and_keeps_the_share_in_range(self, bench, tiny_clip):
        split = bench._decode_split(tiny_clip, threads=1, rounds=1)

        assert split.frames == 20
        assert 0.0 <= split.share <= 1.0

    def test_a_negative_share_is_noise_not_a_saving(self, bench):
        split = bench.DecodeSplit(threads=1, frames=10, grab_ms=1.2,
                                  both_ms=1.1, round_shares=[-0.09])
        assert split.share == 0.0

    def test_a_missing_clip_is_refused_not_swapped_for_another(self, bench, tmp_path):
        with pytest.raises(SystemExit):
            bench._clip(str(tmp_path / "not-here.mp4"))


@pytest.fixture
def tiny_clip(tmp_path):
    """A 20-frame recording in a format no graphics chip decodes."""
    clip = tmp_path / "tiny.avi"
    writer = cv2.VideoWriter(str(clip), cv2.VideoWriter_fourcc(*"MJPG"), 15, (64, 48))
    for i in range(20):
        writer.write(np.full((48, 64, 3), i * 10, np.uint8))
    writer.release()

    probe = cv2.VideoCapture(str(clip), cv2.CAP_FFMPEG)
    opened = probe.isOpened()
    probe.release()
    if not opened:
        pytest.skip("this OpenCV build cannot read the clip through FFmpeg")
    return clip


class TestHardwareDecode:
    """`--hw`: what a graphics chip would take off the processor."""

    def test_naming_a_chip_never_uses_the_combination_opencv_refuses(self, bench):
        # `VIDEO_ACCELERATION_ANY` with `CAP_PROP_HW_DEVICE` is rejected at
        # open - "Invalid usage of CAP_PROP_HW_DEVICE with 'ANY'" - and the
        # capture then falls back to the processor. Naming a chip has to name
        # the interface too.
        #
        # Read as pairs, never as a flat list: the parameters are
        # property, value, property, value, and every one of them is a small
        # integer. `VIDEO_ACCELERATION_ANY` is 1, and so is graphics chip 1 -
        # which is how the first version of this test failed on a list that
        # was perfectly correct.
        params = bench._hw_params(1)
        asked = dict(zip(params[::2], params[1::2]))

        assert asked[cv2.CAP_PROP_HW_DEVICE] == 1
        assert asked[cv2.CAP_PROP_HW_ACCELERATION] != cv2.VIDEO_ACCELERATION_ANY

    def test_the_processor_row_is_opened_with_nothing(self, bench):
        # The first run of this tool asked for `VIDEO_ACCELERATION_ANY` on the
        # row it called "processor", so the Intel chip answered both rows and
        # the two agreeing looked like corroboration. Nothing at all, or it is
        # not the processor.
        assert bench._capture_params(None) == []
        assert bench._capture_params(1) == bench._hw_params(1)

    def test_a_chip_that_will_not_decode_the_clip_is_left_out(self, bench, tiny_clip):
        # No graphics chip decodes Motion JPEG. Every one of them must be
        # skipped rather than measured, because OpenCV opens the file anyway
        # and decodes it on the processor without saying so.
        decoders = bench._decoders(tiny_clip)

        assert [device for _, device in decoders] == [None]

    def test_a_chip_that_took_nothing_is_labelled_so(self, bench, capsys):
        split = bench.DecodeSplit(threads=1, frames=10, grab_ms=1.0, both_ms=2.0,
                                  round_shares=[0.5], label="Some Chip",
                                  device=1, accelerated=False)
        bench._print_hardware([split])

        assert "REFUSED" in capsys.readouterr().out

    def test_a_chip_that_did_the_work_is_not(self, bench, capsys):
        split = bench.DecodeSplit(threads=1, frames=10, grab_ms=1.0, both_ms=2.0,
                                  round_shares=[0.5], label="Some Chip",
                                  device=1, accelerated=True)
        bench._print_hardware([split])

        assert "REFUSED" not in capsys.readouterr().out

    def test_the_copy_is_refused_rather_than_faked(self, bench, tmp_path):
        not_a_video = tmp_path / "notes.txt"
        not_a_video.write_text("no frames here")

        assert bench._h264_copy(not_a_video, tmp_path / "copy.mp4") is None

    def test_what_is_being_decoded_is_named(self, bench, tiny_clip):
        described = bench._describe(tiny_clip)

        assert "64x48" in described
        assert "Mbit/s" in described

    def test_streams_are_counted_while_they_run(self, bench, tiny_clip):
        level = bench._stream_level(tiny_clip, None, streams=2, seconds=0.3)

        assert level is not None
        frames_per_second, cores = level
        assert frames_per_second > 0
        assert cores >= 0

    def test_the_engine_still_decodes_on_the_processor(self):
        """`--hw` measures; it does not switch anything on.

        The owner has not chosen hardware decode yet, so `CameraSource.open()`
        asks for none. When he does choose it, this test is the one to change
        - deliberately, and with the System Health wording that goes with it.
        """
        source = (Path(__file__).resolve().parents[1] / "vg" / "ingest"
                  / "source.py").read_text(encoding="utf-8")

        assert "CAP_PROP_HW_ACCELERATION" not in source
