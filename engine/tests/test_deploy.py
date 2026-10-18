"""The two Windows service definitions WinSW reads (spec 016, plan C).

WinSW is not on a development machine, so the files are parsed here and the
values the plan promises are checked: what runs, with which settings, how it
restarts, where it logs, and as whom.
"""

from __future__ import annotations

import xml.etree.ElementTree as ET
from pathlib import Path

import pytest

REPO_DIR = Path(__file__).resolve().parents[2]
SERVICE_DIR = REPO_DIR / "deploy" / "service"


def load(name: str) -> ET.Element:
    return ET.parse(SERVICE_DIR / f"{name}.xml").getroot()


@pytest.fixture(params=["visionguard-engine", "visionguard-front"])
def service(request):
    return request.param, load(request.param)


class TestBoth:
    def test_its_id_is_its_file_name(self, service):
        name, root = service
        assert root.findtext("id") == name

    def test_starts_by_itself(self, service):
        assert service[1].findtext("startmode") == "Automatic"

    def test_three_restarts_ten_seconds_apart_then_stays_stopped(self, service):
        actions = [(e.get("action"), e.get("delay")) for e in service[1].findall("onfailure")]
        assert actions == [("restart", "10 sec")] * 3 + [("none", None)]
        assert service[1].findtext("resetfailure") == "1 hour"

    def test_logs_roll_by_size_in_the_logs_folder(self, service):
        root = service[1]
        assert root.findtext("logpath") == r"C:\VisionGuard\logs"
        log = root.find("log")
        assert log is not None and log.get("mode") == "roll-by-size"
        assert log.findtext("sizeThreshold") == "10240"     # KB: 10 MB
        assert log.findtext("keepFiles") == "10"

    def test_runs_as_local_service(self, service):
        account = service[1].find("serviceaccount")
        assert account is not None
        assert account.findtext("domain") == "NT AUTHORITY"
        assert account.findtext("user") == "LocalService"
        assert account.find("password") is None


class TestEngine:
    def test_runs_serve_py_from_the_apps_own_python(self):
        root = load("visionguard-engine")
        assert root.findtext("executable") == r"%BASE%\..\.venv\Scripts\python.exe"
        assert r"engine\tools\serve.py" in root.findtext("arguments")

    def test_strict_with_the_site_folders(self):
        env = {e.get("name"): e.get("value") for e in load("visionguard-engine").findall("env")}
        assert env == {
            "VG_STRICT": "1",
            "VG_HOME": r"C:\VisionGuard\data",
            "VG_LOGS": r"C:\VisionGuard\logs",
        }


class TestFront:
    def test_runs_caddy_with_the_shipped_caddyfile(self):
        root = load("visionguard-front")
        assert root.findtext("executable") == r"%BASE%\..\bin\caddy.exe"
        assert root.findtext("arguments") == r'run --config "%BASE%\..\deploy\Caddyfile"'
        assert (REPO_DIR / "deploy" / "Caddyfile").is_file()

    def test_needs_no_engine_settings(self):
        assert not load("visionguard-front").findall("env")


class TestInstall:
    def test_never_copies_tensorrt_plans_with_the_models(self):
        """First drill, 18 Oct 2026: plans built by TensorRT 11.2 on the dev
        setup were copied into an 11.4 install and the engine would not start.
        A plan is built on the machine, never carried to it."""
        text = (REPO_DIR / "deploy" / "install.ps1").read_text(encoding="utf-8")
        copy = [line for line in text.splitlines()
                if line.lstrip().startswith("robocopy $Models")]
        assert len(copy) == 1
        assert "/XF *.engine" in copy[0]
