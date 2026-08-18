"""URL construction and probing logic (no network needed)."""
from __future__ import annotations

import pytest

from loiterwatch.probe import (HTTP_PATHS, RTSP_PATHS, ProbeResult, build_urls,
                               quiet_ffmpeg, set_ffmpeg_timeouts, try_url)


def test_urls_cover_every_known_path():
    urls = build_urls("10.0.0.5")
    assert len(urls) == len(RTSP_PATHS) + len(HTTP_PATHS)
    assert all(u.startswith(("rtsp://", "http://")) for u in urls)


def test_credentials_are_embedded():
    urls = build_urls("10.0.0.5", "user", "0000")
    assert urls[0].startswith("rtsp://user:0000@10.0.0.5:554/")


def test_no_credentials_means_no_at_sign():
    urls = build_urls("10.0.0.5")
    assert "@" not in urls[0]


@pytest.mark.parametrize("password,encoded", [
    ("P@ss", "P%40ss"),
    ("a/b", "a%2Fb"),
    ("a:b", "a%3Ab"),
    ("a#b", "a%23b"),
    ("a?b", "a%3Fb"),
])
def test_special_characters_in_passwords_are_encoded(password, encoded):
    """An unencoded '@' silently breaks URL parsing and looks like an auth
    failure, which is the single most common self-inflicted probe failure."""
    url = build_urls("10.0.0.5", "user", password)[0]
    assert f"user:{encoded}@10.0.0.5" in url


def test_username_is_encoded_too():
    url = build_urls("10.0.0.5", "dom\\user", "x")[0]
    assert "dom%5Cuser" in url


def test_custom_ports_are_used():
    urls = build_urls("10.0.0.5", port=8554, http_port=8080)
    assert any(":8554/" in u for u in urls if u.startswith("rtsp"))
    assert any(":8080/" in u for u in urls if u.startswith("http"))


def test_http_can_be_skipped():
    urls = build_urls("10.0.0.5", include_http=False)
    assert all(u.startswith("rtsp://") for u in urls)


def test_query_string_paths_survive_intact():
    urls = build_urls("10.0.0.5")
    assert any("channel=1&subtype=0" in u for u in urls)


def test_try_url_gives_up_rather_than_hanging():
    """A wrong RTSP path can block inside ffmpeg well past its own timeout."""
    result = try_url("rtsp://192.0.2.1:554/nope", timeout=1.0)  # TEST-NET-1
    assert result.ok is False
    assert result.detail


def test_probe_result_display():
    ok = ProbeResult("rtsp://x/1", True, "", 1920, 1080)
    bad = ProbeResult("rtsp://x/2", False, "404")
    assert "OK" in ok.display and "1920x1080" in ok.display
    assert ok.url in ok.display
    assert "OK" not in bad.display


def test_ffmpeg_timeout_env_is_set(monkeypatch):
    monkeypatch.delenv("OPENCV_FFMPEG_CAPTURE_OPTIONS", raising=False)
    set_ffmpeg_timeouts(3.0)
    import os
    value = os.environ["OPENCV_FFMPEG_CAPTURE_OPTIONS"]
    assert "rtsp_transport;tcp" in value
    assert "3000000" in value


def test_ffmpeg_timeout_does_not_override_a_user_setting(monkeypatch):
    monkeypatch.setenv("OPENCV_FFMPEG_CAPTURE_OPTIONS", "mine")
    set_ffmpeg_timeouts(3.0)
    import os
    assert os.environ["OPENCV_FFMPEG_CAPTURE_OPTIONS"] == "mine"


def test_quiet_ffmpeg_silences_the_decoder(monkeypatch):
    """H.265 cameras log on every keyframe; unsilenced it buries the alerts."""
    monkeypatch.delenv("OPENCV_FFMPEG_LOGLEVEL", raising=False)
    quiet_ffmpeg()
    import os
    assert os.environ["OPENCV_FFMPEG_LOGLEVEL"] == "-8"


def test_quiet_ffmpeg_respects_an_explicit_setting(monkeypatch):
    monkeypatch.setenv("OPENCV_FFMPEG_LOGLEVEL", "32")
    quiet_ffmpeg()
    import os
    assert os.environ["OPENCV_FFMPEG_LOGLEVEL"] == "32"
