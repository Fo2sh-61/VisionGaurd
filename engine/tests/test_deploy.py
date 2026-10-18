"""The two Windows service definitions WinSW reads (spec 016, plan C).

WinSW is not on a development machine, so the files are parsed here and the
values the plan promises are checked: what runs, with which settings, how it
restarts, where it logs, and as whom.
"""

from __future__ import annotations

import base64
import re
import shutil
import subprocess
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

    def test_second_run_installs_the_matcher_from_the_installed_copy(self):
        """First drill: step 1 left models out, so a re-run from the installed
        copy had no kit folder to install the appearance matcher from."""
        text = (REPO_DIR / "deploy" / "install.ps1").read_text(encoding="utf-8")
        copy = [line for line in text.splitlines()
                if line.lstrip().startswith("robocopy $KitApp")]
        assert len(copy) == 1
        assert "/XD .venv" in copy[0] and "models" not in copy[0]
        pip = [line for line in text.splitlines() if r"reid\loiterwatch" in line
               and "Join-Path" in line]
        assert len(pip) == 1
        assert "$App " in pip[0] and "$KitApp" not in pip[0]

    def test_start_wait_stops_at_a_reported_failure(self):
        """First drill: the engine failed, WinSW gave up, and step 9 polled a
        502 until Ctrl-C. serve.py leaves start-failure.txt; step 9 reads it."""
        text = (REPO_DIR / "deploy" / "install.ps1").read_text(encoding="utf-8")
        step9 = text.split("Step 9", 1)[1]
        assert "start-failure.txt" in step9
        assert "LastWriteTime" in step9
        assert "Start-Service visionguard-engine" in step9

    def test_service_rights_message_does_not_claim_only(self):
        """C:/VisionGuard inherits Authenticated Users: Modify, so 'only' was false."""
        text = (REPO_DIR / "deploy" / "install.ps1").read_text(encoding="utf-8")
        said = [line for line in text.splitlines() if "LocalService" in line and "Ok " in line]
        assert said and all("only" not in line for line in said)

    def test_only_asks_winsw_2_12_for_commands_it_has(self):
        """Second drill, 18 Oct 2026: a re-run asked WinSW 2.12 to `refresh`,
        which only WinSW 3 has, and stopped with both services down."""
        text = (REPO_DIR / "deploy" / "install.ps1").read_text(encoding="utf-8")
        winsw_2_12 = {"install", "uninstall", "start", "stop", "stopwait",
                      "restart", "status", "test", "testwait", "version", "help"}
        asked = re.findall(r'Join-Path \$serviceDir "\$name\.exe"\) @\(\'(\w+)\'\)', text)
        assert asked, "the WinSW calls were not found"
        assert set(asked) <= winsw_2_12

    def test_firewall_stays_private_and_warns_on_a_public_network(self):
        text = (REPO_DIR / "deploy" / "install.ps1").read_text(encoding="utf-8")
        assert "Set-NetFirewallRule" in text
        assert "Get-NetConnectionProfile" in text
        assert "Set-NetConnectionProfile" in text
        assert text.count("-Profile Private,Domain") == 2


def _step6() -> str:
    return _script("install.ps1").split("Step 6", 1)[1].split("Step 7", 1)[0]


def _boot_lines() -> str:
    """The lines the startup task runs, as written in install.ps1."""
    return _script("install.ps1").split("$bootLines = @'\n", 1)[1].split("\n'@", 1)[0]


def _script(name: str) -> str:
    return (REPO_DIR / "deploy" / name).read_text(encoding="utf-8")


def _parse_errors(name: str) -> str:
    command = ("$e = $null; [void][System.Management.Automation.Language.Parser]::ParseFile("
               f"'{REPO_DIR / 'deploy' / name}', [ref]$null, [ref]$e); "
               "$e | ForEach-Object { $_.Message }")
    done = subprocess.run(["powershell", "-NoProfile", "-Command", command],
                          capture_output=True, text=True, timeout=60)
    return done.stdout.strip()


needs_powershell = pytest.mark.skipif(shutil.which("powershell") is None,
                                      reason="powershell is not available")


class TestInstallForSetup:
    """Setup (the wizard) runs install.ps1 hidden: nothing may wait for a person."""

    def test_takes_the_first_administrator_as_parameters(self):
        text = _script("install.ps1")
        assert "[string]$AdminEmail" in text and "[string]$AdminName" in text

    def test_step7_reads_the_password_from_the_environment_only(self):
        step7 = _script("install.ps1").split("Step 7", 1)[1].split("Step 8", 1)[0]
        assert "'--password-from-env', 'VG_ADMIN_PASSWORD'" in step7
        assert "$env:VG_ADMIN_PASSWORD" in step7
        assert "'--password'" not in step7
        # the password variable is never written out
        assert "$env:VG_ADMIN_PASSWORD" not in "".join(
            line for line in step7.splitlines() if "Write-Host" in line or "Ok " in line)

    def test_step7_without_a_console_stops_with_a_plain_reason(self):
        step7 = _script("install.ps1").split("Step 7", 1)[1].split("Step 8", 1)[0]
        assert "[Environment]::UserInteractive" in step7
        assert "[Console]::IsInputRedirected" in step7
        assert ("Stop-Install 'there is no administrator account yet; run Setup again "
                "and fill in the first administrator page'") in step7
        # the prompt path comes after the environment path, never before it
        assert step7.index("--password-from-env") < step7.index("IsInputRedirected")

    def test_anyone_signed_in_may_stop_and_start_the_services(self):
        text = _script("install.ps1")
        assert "Run sc.exe @('sdset', $name, $serviceSddl)" in text
        entry = re.search(r"\(A;;([A-Z]+);;;IU\)", text)
        assert entry, "no Interactive Users entry"
        # RP = start, WP = stop, LO = interrogate, LC = query status
        for right in ("RP", "WP", "LO", "LC"):
            assert right in entry.group(1)
        assert ";;;SY)" in text and ";;;BA)" in text
        assert "anyone signed in at this PC may stop and start $name" in text

    def test_the_site_gets_the_ultralytics_that_was_tested(self):
        """19 Oct 2026: '>=8.4.127' let a site install 8.4.182, whose CUDA-graph
        capture broke when two features loaded at once, and the engine stopped."""
        req = (REPO_DIR / "engine" / "requirements.txt").read_text(encoding="utf-8")
        line = next(ln for ln in req.splitlines() if ln.startswith("ultralytics"))
        assert re.match(r"ultralytics==\d+\.\d+\.\d+\s", line + " "), line

    def test_users_may_read_the_startup_task_and_nothing_more(self):
        """Without this a normal user's VisionGuard Control could only say it
        cannot tell; with more than read, a user could change what SYSTEM runs."""
        text = _script("install.ps1")
        sd = re.search(r"SetSecurityDescriptor\('([^']+)'", text)
        assert sd, "the task's permissions are not set"
        aces = dict((m.group(2), m.group(1)) for m in re.finditer(r"\(A;;(\w+);;;(\w+)\)", sd.group(1)))
        assert aces.get("AU") == "GR"
        assert aces.get("SY") == "FA" and aces.get("BA") == "FA"
        assert set(aces) == {"SY", "BA", "AU"}

    def test_setup_can_forbid_every_question(self):
        """A hidden run whose stdin is not redirected would otherwise reach the
        prompt and wait for ever; Setup passes -NoPrompt."""
        text = _script("install.ps1")
        assert "[switch]$NoPrompt" in text
        step7 = text.split("Step 7", 1)[1].split("Step 8", 1)[0]
        assert "-not $NoPrompt -and [Environment]::UserInteractive" in step7
        iss = (REPO_DIR / "deploy" / "setup" / "VisionGuard.iss").read_text(encoding="utf-8")
        assert "-NoPrompt" in iss

    def test_the_password_leaves_the_environment_before_step_1(self):
        """Otherwise pip and the Python installer inherit it."""
        text = _script("install.ps1")
        cleared = text.index("Remove-Item Env:\\VG_ADMIN_PASSWORD")
        assert cleared < text.index("Step 1 ")
        step7 = text.split("Step 7", 1)[1].split("Step 8", 1)[0]
        assert "finally" in step7 and "Remove-Item Env:\\VG_ADMIN_PASSWORD" in step7

    def test_nothing_waits_for_the_keyboard(self):
        text = _script("install.ps1")
        assert "Read-Host" not in text
        assert "'/quiet'" in text

    @needs_powershell
    def test_parses(self):
        assert _parse_errors("install.ps1") == ""


class TestStartupTask:
    """Both services start on demand; a SYSTEM task starts them unless autostart.txt says off."""

    def test_both_services_start_on_demand(self):
        step6 = _step6()
        assert "Run sc.exe @('config', $name, 'start=', 'demand')" in step6
        # one call per service, inside the loop over $Services
        before = step6.split("Run sc.exe @('config'", 1)[0]
        assert before.rstrip().endswith("foreach ($name in $Services) {")

    def test_the_task_is_registered_as_system_at_startup(self):
        step6 = _step6()
        assert "$taskName = 'VisionGuard start at boot'" in step6
        assert "New-ScheduledTaskTrigger -AtStartup" in step6
        assert "-UserId 'SYSTEM' -LogonType ServiceAccount -RunLevel Highest" in step6
        assert "Register-ScheduledTask -TaskName $taskName" in step6 and "-Force" in step6
        assert "-AllowStartIfOnBatteries -DontStopIfGoingOnBatteries" in step6
        assert "New-TimeSpan -Minutes 10" in step6

    def test_the_task_runs_windows_powershell_with_a_command_never_a_file(self):
        step6 = _step6()
        assert r'"$env:SystemRoot\System32\WindowsPowerShell\v1.0\powershell.exe"' in step6
        argument = next(ln for ln in step6.splitlines() if "-Argument" in ln)
        assert "-Command" in argument and "-File" not in argument
        assert "-NoProfile" in argument and "-NonInteractive" in argument
        assert "-ExecutionPolicy Bypass" in argument

    def test_the_inline_lines_read_the_switch_and_start_both_services(self):
        lines = _boot_lines()
        assert "autostart.txt" in lines and "'off'" in lines
        assert "Start-Service visionguard-engine" in lines
        assert "Start-Service visionguard-front" in lines
        assert '"' not in lines                      # quote-safe inside -Argument
        # the file's text is only compared, never run
        assert "Invoke-Expression" not in lines and "iex" not in lines.lower().split()
        assert "& $" not in lines and ". $" not in lines

    def test_the_task_never_runs_anything_from_the_app_folder(self):
        step6 = _step6()
        task_part = step6.split("$bootLines", 1)[1].split("# The service account", 1)[0]
        code = "\n".join(ln for ln in task_part.splitlines() if not ln.lstrip().startswith("#"))
        assert r"C:\VisionGuard\app" not in code and "$App" not in code
        assert r"C:\VisionGuard\app" not in _boot_lines()

    def test_autostart_txt_is_written_only_when_missing(self):
        step6 = _step6()
        (line,) = [ln for ln in step6.splitlines() if "Set-Content" in ln]
        assert line.startswith("if (-not (Test-Path $autostart))")
        assert "-Value 'on'" in line

    def test_the_ok_line_says_when_it_starts(self):
        assert ("VisionGuard starts when the PC starts unless the switch in VisionGuard "
                "Control is off") in _step6()

    def test_step9_still_starts_both_services_itself(self):
        step9 = _script("install.ps1").split("Step 9", 1)[1]
        assert "foreach ($name in $Services) { Start-Service -Name $name" in step9


def _run_boot_lines(tmp_path, content):
    """Run the task's real lines with Start-Service replaced by a recorder."""
    switch = tmp_path / "autostart.txt"
    if content is not None:
        switch.write_bytes(content)
    lines = _boot_lines().replace(r"C:\VisionGuard\data\autostart.txt", str(switch))
    assert str(switch) in lines
    script = ('function Start-Service { param($Name) Write-Output "started $Name" }\n'
              + "; ".join(ln for ln in lines.splitlines() if ln.strip()))
    encoded = base64.b64encode(script.encode("utf-16-le")).decode()
    done = subprocess.run(["powershell", "-NoProfile", "-NonInteractive", "-EncodedCommand", encoded],
                          capture_output=True, text=True, timeout=60)
    assert done.returncode == 0, done.stderr
    return done.stdout.split()


@needs_powershell
class TestStartupTaskLogic:
    BOTH = ["started", "visionguard-engine", "started", "visionguard-front"]

    @pytest.mark.parametrize("content,expect_both", [
        (None, True),
        (b"off\r\n", False),
        (b"OFF \r\n", False),
        (b"  Off\n", False),
        (b"on\r\n", True),
        (b"garbage\n", True),
        (b"", True),
        (b"\n", True),
        (b"on\noff\n", True),
    ])
    def test_switch(self, tmp_path, content, expect_both):
        started = _run_boot_lines(tmp_path, content)
        assert started == (self.BOTH if expect_both else [])


class TestUninstall:
    def test_removes_both_services(self):
        text = _script("uninstall.ps1")
        assert "'visionguard-engine', 'visionguard-front'" in text
        assert "Stop-Service" in text and "uninstall" in text and "sc.exe delete" in text

    def test_removes_both_firewall_rules(self):
        text = _script("uninstall.ps1")
        assert "foreach ($port in 443, 8443)" in text
        assert '"VisionGuard HTTPS $port"' in text
        assert "Remove-NetFirewallRule" in text

    def test_removes_the_root_by_its_exact_subject(self):
        text = _script("uninstall.ps1")
        assert "'CN=VisionGuard site root'" in text and "'O=VisionGuard'" in text
        assert "$_.Subject -eq $_.Issuer" in text
        assert "-like" not in text and "-match" not in text
        # and that is what site_cert.py names the root
        cert = (REPO_DIR / "engine" / "tools" / "site_cert.py").read_text(encoding="utf-8")
        assert '_name("VisionGuard site root")' in cert
        assert 'NameOID.ORGANIZATION_NAME, "VisionGuard"' in cert

    def test_removes_the_desktop_shortcut_and_ends_the_control_icon(self):
        text = _script("uninstall.ps1")
        assert r"C:\Users\Public\Desktop\VisionGuard.lnk" in text
        assert r"C:\Users\Public\Desktop\VisionGuard Control.lnk" in text
        assert "VisionGuardControl" in text

    def test_removes_the_startup_task(self):
        text = _script("uninstall.ps1")
        assert "$taskName = 'VisionGuard start at boot'" in text
        assert "Unregister-ScheduledTask -TaskName $taskName -Confirm:$false" in text
        assert 'Skip "no task' in text

    def test_never_deletes_the_data_folder(self):
        text = _script("uninstall.ps1")
        for line in text.splitlines():
            if line.lstrip().startswith("#"):
                continue
            if "Remove-Item" in line or "rmdir" in line or "robocopy" in line:
                assert "$Data" not in line and "data" not in line.lower()
        assert "Your data folder was kept: $Data" in text
        assert "exit 0" in text

    @needs_powershell
    def test_parses(self):
        assert _parse_errors("uninstall.ps1") == ""
