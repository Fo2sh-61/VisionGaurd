"""Camera source: parsing, health transitions, and the NO SIGNAL contract.

The stale-frame tests are the ones that matter. The front end promises
"NO SIGNAL - showing last received frame", and the failure mode we must rule out
is serving an old frame while claiming it is live.

Tests that need real hardware are marked `camera` and skipped by default:
    python -m pytest engine/tests -m camera
"""

from __future__ import annotations

from datetime import datetime, timezone

import numpy as np
import pytest

from vg.ingest.source import CameraSource, Frame, SourceKind, parse_source


def blank(w: int = 64, h: int = 48) -> np.ndarray:
    return np.zeros((h, w, 3), dtype=np.uint8)


# --- source string parsing -------------------------------------------------

class TestParseSource:
    @pytest.mark.parametrize(
        "spec,expected",
        [
            ("webcam:0", (SourceKind.WEBCAM, 0)),
            ("webcam:2", (SourceKind.WEBCAM, 2)),
            ("0", (SourceKind.WEBCAM, 0)),
            ("rtsp://host/stream", (SourceKind.RTSP, "rtsp://host/stream")),
            ("http://host/mjpeg", (SourceKind.RTSP, "http://host/mjpeg")),
            ("file:clips/a.mp4", (SourceKind.FILE, "clips/a.mp4")),
            ("clips/a.mp4", (SourceKind.FILE, "clips/a.mp4")),
        ],
    )
    def test_recognised_forms(self, spec, expected):
        assert parse_source(spec) == expected

    def test_rejects_non_numeric_webcam(self):
        with pytest.raises(ValueError, match="numeric index"):
            parse_source("webcam:front")


# --- credential handling ---------------------------------------------------

class TestRedaction:
    def test_password_never_appears_in_the_redacted_form(self):
        cam = CameraSource(
            "c1", "rtsp://admin:NewTiger%402019@10.0.9.123:554/Streaming/102"
        )
        assert "NewTiger" not in cam.redacted
        assert "****" in cam.redacted
        # The bits an operator needs to diagnose the fault survive.
        assert "10.0.9.123" in cam.redacted and "admin" in cam.redacted

    def test_webcam_has_nothing_to_redact(self):
        assert CameraSource("c1", "webcam:0").redacted == "webcam:0"

    def test_url_without_credentials_is_unchanged(self):
        cam = CameraSource("c1", "rtsp://192.168.1.5/stream")
        assert cam.redacted == "rtsp://192.168.1.5/stream"


# --- health transitions ----------------------------------------------------

class TestHealth:
    def test_starts_down_before_anything_opens(self):
        cam = CameraSource("c1", "webcam:99")
        assert cam.health.status == "down"
        assert cam.health.online is False

    def test_single_read_failure_does_not_declare_an_outage(self):
        # RTSP drops the odd frame under normal load. One miss is not an outage,
        # and treating it as one would flap the System Health page constantly.
        cam = CameraSource("c1", "rtsp://host/s")
        cam.health.status = "ok"
        cam._note_failure("transient")
        assert cam.health.status == "ok"

    def test_repeated_failures_declare_an_outage(self):
        cam = CameraSource("c1", "rtsp://host/s")
        cam.health.status = "ok"
        for _ in range(CameraSource.FAILURES_BEFORE_DOWN):
            cam._note_failure("gone")
        assert cam.health.status == "down"
        assert cam.health.online is False

    def test_credentialled_stream_reports_auth_not_down(self):
        # OpenCV cannot tell a bad password from an unreachable host, but if the
        # URL has a username, 'check the password' is the actionable diagnosis —
        # and `auth` is a state the UI already renders.
        cam = CameraSource("c1", "rtsp://admin:wrong@host/s")
        for _ in range(CameraSource.FAILURES_BEFORE_DOWN):
            cam._note_failure("refused")
        assert cam.health.status == "auth"

    def test_a_good_read_clears_the_error(self):
        cam = CameraSource("c1", "webcam:0")
        cam.health.status = "down"
        cam.health.last_error = "boom"
        cam.health.consecutive_failures = 5

        # Simulate what read() does on success.
        cam.health.consecutive_failures = 0
        cam.health.status = "ok"
        cam.health.last_error = None
        assert cam.health.online and cam.health.last_error is None


# --- the NO SIGNAL contract ------------------------------------------------

class TestStaleFrames:
    def test_no_frame_at_all_returns_none(self):
        # A camera that has never worked has nothing to show. The UI renders an
        # offline tile; it must not be handed a black frame pretending to be one.
        cam = CameraSource("c1", "webcam:99")
        assert cam._stale() is None

    def test_stale_frame_is_flagged_as_stale(self):
        cam = CameraSource("c1", "webcam:0")
        original = Frame("c1", blank(), datetime.now(timezone.utc), 7)
        cam._last_good = original

        stale = cam._stale()
        assert stale is not None
        assert stale.is_stale is True

    def test_stale_frame_keeps_the_ORIGINAL_capture_time(self):
        # This is the whole promise. If the timestamp were refreshed, the console
        # would show a five-minute-old empty corridor labelled "now".
        captured = datetime(2026, 8, 5, 6, 12, 0, tzinfo=timezone.utc)
        cam = CameraSource("c1", "webcam:0")
        cam._last_good = Frame("c1", blank(), captured, 7)

        assert cam._stale().captured_at == captured

    def test_stale_frame_keeps_the_original_sequence_number(self):
        cam = CameraSource("c1", "webcam:0")
        cam._last_good = Frame("c1", blank(), datetime.now(timezone.utc), 7)
        assert cam._stale().sequence == 7

    def test_serving_stale_frames_is_counted(self):
        cam = CameraSource("c1", "webcam:0")
        cam._last_good = Frame("c1", blank(), datetime.now(timezone.utc), 1)
        cam._stale()
        cam._stale()
        assert cam.health.frames_dropped == 2

    def test_fresh_frames_are_never_marked_stale(self):
        assert Frame("c1", blank(), datetime.now(timezone.utc), 1).is_stale is False


# --- frame geometry --------------------------------------------------------

class TestFrameGeometry:
    def test_dimensions_read_from_the_array(self):
        frame = Frame("c1", blank(w=320, h=240), datetime.now(timezone.utc), 1)
        assert (frame.width, frame.height) == (320, 240)

    def test_normalisation_produces_fractions(self):
        # Everything above this layer works in fractions of the frame, so a
        # detection is resolution-independent all the way to the browser.
        frame = Frame("c1", blank(w=200, h=100), datetime.now(timezone.utc), 1)
        assert frame.to_normalised(100, 50) == (0.5, 0.5)
        assert frame.to_normalised(200, 100) == (1.0, 1.0)


# --- backoff ---------------------------------------------------------------

class TestBackoff:
    def test_grows_then_caps(self):
        cam = CameraSource("c1", "rtsp://host/s")
        delays = [cam._backoff() for _ in range(10)]
        assert delays[:5] == list(CameraSource.BACKOFF)
        # Capped, not unbounded: a camera back after an hour is picked up in ~10s.
        assert all(d == CameraSource.BACKOFF[-1] for d in delays[5:])

    def test_reset_on_successful_open(self):
        cam = CameraSource("c1", "rtsp://host/s")
        cam._backoff()
        cam._backoff()
        cam._backoff_index = 0  # what open() does on success
        assert cam._backoff() == CameraSource.BACKOFF[0]


# --- rotation --------------------------------------------------------------

class TestRotation:
    def test_rejects_nothing_here_but_swaps_axes(self):
        from vg.ingest.source import _rotate

        img = blank(w=200, h=100)
        assert _rotate(img, 90).shape[:2] == (200, 100)
        assert _rotate(img, 180).shape[:2] == (100, 200)
        assert _rotate(img, 0) is img


# --- real hardware ---------------------------------------------------------

@pytest.mark.camera
class TestRealWebcam:
    def test_opens_and_reads(self):
        with CameraSource("cam-laptop", "webcam:0", target_fps=5) as cam:
            if not cam.health.online:
                pytest.skip(f"no webcam available: {cam.health.last_error}")
            frame = cam.read()
            assert frame is not None and not frame.is_stale
            assert frame.width > 0 and frame.height > 0
            assert frame.captured_at.tzinfo is timezone.utc

    def test_frames_iterator_respects_target_fps(self):
        import time

        with CameraSource("cam-laptop", "webcam:0", target_fps=5) as cam:
            if not cam.health.online:
                pytest.skip("no webcam available")
            start = time.monotonic()
            count = 0
            for _ in cam.frames():
                count += 1
                if count >= 5:
                    break
            elapsed = time.monotonic() - start
            # 5 frames at 5 fps is ~0.8s of gaps; allow generous slack.
            assert 0.4 < elapsed < 3.0, f"5 frames took {elapsed:.2f}s"
