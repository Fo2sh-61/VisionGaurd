"""System Health rows added by spec 016: the site certificate.

Each state the row can be in, and the page staying 200 in every one of them
(rule 7). A certificate that has quietly expired is the failure this row is
for: every phone and PC stops trusting the site on the same morning.
"""

from __future__ import annotations

import sys
from dataclasses import replace
from datetime import datetime, timedelta, timezone
from pathlib import Path

import pytest

ENGINE_DIR = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ENGINE_DIR))
sys.path.insert(0, str(ENGINE_DIR / "tools"))

import site_cert  # noqa: E402
from vg import config as vgconfig  # noqa: E402
from vg.api import schemas as S  # noqa: E402
from vg.api.live import LiveStore  # noqa: E402
from vg.ingest.registry import CameraRegistry  # noqa: E402

NAMES = ("192.168.1.20", "127.0.0.1", "localhost")


def store(tls) -> LiveStore:
    return LiveStore(config=replace(vgconfig.load(), tls=tls),
                     registry=CameraRegistry([]))


def row(s: LiveStore) -> S.PipelineStage:
    rows = [p for p in s.health().pipeline if p.key == "certificate"]
    assert len(rows) == 1
    return rows[0]


@pytest.fixture
def made(tmp_path):
    """Make a site certificate that started `days_ago` days ago."""
    usb = tmp_path / "usb"
    usb.mkdir()
    site_cert.make_root(usb, forbidden=(),
                        now=datetime.now(timezone.utc) - timedelta(days=2000))
    cert_dir = tmp_path / "tls"

    def _make(days_ago: int):
        now = datetime.now(timezone.utc) - timedelta(days=days_ago)
        site_cert.make_site(usb, NAMES, cert_dir, now=now)
        return vgconfig.TlsConfig(names=NAMES, cert_dir=cert_dir)
    return _make


def test_not_set_up_on_a_development_machine():
    r = row(store(None))
    assert r.healthy and r.severity is S.Severity.INFO
    assert "not set up" in r.detail.lower()


def test_valid_lists_the_names_and_the_end_date(made):
    r = row(store(made(days_ago=10)))
    assert r.healthy and r.severity is S.Severity.INFO
    for name in NAMES:
        assert name in r.detail
    end = (datetime.now(timezone.utc) + timedelta(days=815)).strftime("%d %b %Y").lstrip("0")
    assert end in r.detail


def test_a_warning_within_thirty_days_of_the_end(made):
    r = row(store(made(days_ago=810)))
    assert not r.healthy and r.severity is S.Severity.WARN
    assert "days" in r.detail and "site_cert.py site" in r.detail


def test_a_failure_once_expired(made):
    r = row(store(made(days_ago=900)))
    assert not r.healthy and r.severity is S.Severity.CRITICAL
    assert "expired" in r.detail.lower()


def test_a_failure_when_the_file_is_missing(tmp_path):
    r = row(store(vgconfig.TlsConfig(names=NAMES, cert_dir=tmp_path / "nowhere")))
    assert not r.healthy and r.severity is S.Severity.CRITICAL
    assert "site.crt" in r.detail


def test_a_failure_when_the_file_is_not_a_certificate(tmp_path):
    (tmp_path / "site.crt").write_text("not a certificate", encoding="utf-8")
    r = row(store(vgconfig.TlsConfig(names=NAMES, cert_dir=tmp_path)))
    assert not r.healthy and r.severity is S.Severity.CRITICAL


def test_re_read_when_the_file_changes(made):
    tls = made(days_ago=900)
    s = store(tls)
    assert not row(s).healthy
    made(days_ago=1)            # `site_cert.py site` run again
    assert row(s).healthy


def test_health_stays_200_whatever_the_certificate(tmp_path, authed):
    from vg.api import app as app_module
    from vg.api.store import MockStore

    s = store(vgconfig.TlsConfig(names=NAMES, cert_dir=tmp_path / "nowhere"))
    app_module.set_store(s)
    try:
        client = authed(app_module.create_app())
        assert client.get("/system/health").status_code == 200
    finally:
        app_module.set_store(MockStore())
