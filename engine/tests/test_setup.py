"""Setup.exe: the Inno Setup script and the release script that builds it (spec 016, 1f).

The script is read as text for the promises that matter (admin rights, the
data folder is never deleted, the password never reaches a command line). Where
Inno Setup is installed, a tiny fake kit is really compiled.
"""

from __future__ import annotations

import os
import re
import shutil
import subprocess
from pathlib import Path

import pytest

REPO_DIR = Path(__file__).resolve().parents[2]
ISS = REPO_DIR / "deploy" / "setup" / "VisionGuard.iss"
RELEASE = REPO_DIR / "tools" / "make_release.ps1"
ISCC = Path(os.environ.get("LOCALAPPDATA", "")) / "Programs" / "Inno Setup 7" / "ISCC.exe"


@pytest.fixture(scope="module")
def iss() -> str:
    return ISS.read_text(encoding="utf-8")


def section(text: str, name: str) -> list[str]:
    """The non-comment lines of one [Section]."""
    out: list[str] = []
    inside = False
    for line in text.splitlines():
        if re.match(r"^\[\w+\]\s*$", line):
            inside = line.strip() == f"[{name}]"
        elif inside and line.strip() and not line.lstrip().startswith(";"):
            out.append(line)
    return out


class TestScript:
    def test_asks_for_admin_once_and_installs_to_the_fixed_folder(self, iss):
        assert "PrivilegesRequired=admin" in iss
        assert r"DefaultDirName=C:\VisionGuard" in iss
        assert "DisableDirPage=yes" in iss

    def test_is_64_bit_only(self, iss):
        assert "ArchitecturesAllowed=x64compatible" in iss
        assert "ArchitecturesInstallIn64BitMode=x64compatible" in iss

    def test_uninstall_runs_the_uninstall_script_hidden(self, iss):
        (line,) = section(iss, "UninstallRun")
        assert "uninstall.ps1" in line
        assert "runhidden" in line and "waituntilterminated" in line
        assert "RunOnceId" in line

    def test_icon_starts_with_windows_for_every_user(self, iss):
        reg = "\n".join(section(iss, "Registry"))
        assert "HKLM" in reg
        assert r"Software\Microsoft\Windows\CurrentVersion\Run" in reg
        assert "VisionGuard Control" in reg and "uninsdeletevalue" in reg

    def test_the_run_value_starts_only_the_tray(self, iss):
        (line,) = [ln for ln in section(iss, "Registry") if "VisionGuard Control" in ln]
        value = re.search(r'ValueData: (".*?"); Flags', line).group(1)
        assert value == '"""{app}\\app\\bin\\VisionGuardControl.exe"" --tray"'

    def test_control_has_a_desktop_icon_and_a_start_menu_entry_that_open_the_window(self, iss):
        icons = section(iss, "Icons")
        for place in ("{commondesktop}", "{commonprograms}"):
            (line,) = [ln for ln in icons if ln.startswith('Name: "' + place + '\\VisionGuard Control"')]
            assert r'Filename: "{app}\app\bin\VisionGuardControl.exe"' in line
            assert "Parameters" not in line
            assert r'IconFilename: "{app}\app\assets\visionguard.ico"' in line

    def test_the_data_folder_is_never_deleted(self, iss):
        for line in section(iss, "UninstallDelete") + section(iss, "Files"):
            assert "data" not in line.lower().replace("metadata", ""), line
        for line in section(iss, "UninstallDelete"):
            assert line.startswith("Type:")
            assert r"{app}\app" in line or r"{app}\logs" in line or "python-3.14" in line

    def test_the_password_never_reaches_a_command_line(self, iss):
        # Only the environment variable carries it, set in Setup's own process.
        for name in ("Run", "UninstallRun", "Icons", "Registry"):
            assert "VG_ADMIN_PASSWORD" not in "\n".join(section(iss, name))
        code = "\n".join(section(iss, "Code"))
        assert "SetEnvironmentVariableW('VG_ADMIN_PASSWORD'" in code
        # cleared again afterwards
        assert "SetEnvironmentVariableW('VG_ADMIN_PASSWORD', '')" in code
        # and never typed into the script's parameters or the log
        params = [ln for ln in code.splitlines() if "Params" in ln]
        assert not any("Values[2]" in ln or "Values[3]" in ln for ln in params)
        assert "Values[2]" not in "".join(ln for ln in code.splitlines() if "SaveStringToFile" in ln)

    def test_install_output_is_appended_to_the_log(self, iss):
        assert r"C:\VisionGuard\logs\install.log" in iss
        assert re.search(r"SaveStringToFile\(LogFile, S \+ #13#10, True\)", iss)

    def test_the_two_run_choices_wait_for_a_good_install(self, iss):
        lines = section(iss, "Run")
        assert len(lines) == 2
        control = [ln for ln in lines if "VisionGuardControl.exe" in ln]
        assert len(control) == 1
        assert 'Description: "Open VisionGuard Control"' in control[0]
        assert "Parameters" not in control[0] and "nowait" in control[0]
        for line in lines:
            assert "postinstall" in line and "runasoriginaluser" in line
            assert "Check: InstallSucceeded" in line

    def test_failure_is_said_plainly(self, iss):
        assert "NOT fully installed" in iss
        assert "Fix it and run Setup again" in iss
        assert "STOPPED:" in iss

    def test_the_uninstall_says_the_data_was_kept(self, iss):
        assert r"C:\VisionGuard\data" in iss
        assert "kept" in iss

    def test_password_rules(self, iss):
        assert "Length(Pw) < 12" in iss
        assert "Pw <> AdminPage.Values[3]" in iss
        assert "AdminPage.Add('Password:', True)" in iss
        assert "AdminPage.Add('Password again:', True)" in iss

    def test_pages_are_skipped_when_the_site_already_has_its_own(self, iss):
        assert r"DataDir + '\engine.yaml'" in iss
        assert r"DataDir + '\visionguard.db'" in iss


class TestReleaseScript:
    def test_it_parses(self):
        ps = shutil.which("powershell") or shutil.which("pwsh")
        if not ps:
            pytest.skip("no PowerShell on this machine")
        cmd = (
            "$e=$null;[void][System.Management.Automation.Language.Parser]::ParseFile("
            f"'{RELEASE}',[ref]$null,[ref]$e);if($e){{$e|%{{$_.Message}};exit 1}}"
        )
        done = subprocess.run([ps, "-NoProfile", "-Command", cmd], capture_output=True, text=True)
        assert done.returncode == 0, done.stdout + done.stderr

    def test_it_builds_the_icon_and_the_setup(self):
        text = RELEASE.read_text(encoding="utf-8")
        assert r"deploy\control" in text and "*.cs" in text and "csc.exe" in text
        assert "VisionGuardControl.cs" not in text
        assert "[string]$Iscc" in text
        assert "/DKitDir=$Out" in text and "/DAppVersion=$Tag" in text
        assert "VisionGuard-Setup-$Tag.exe" in text


@pytest.mark.skipif(not ISCC.exists(), reason=f"Inno Setup 7 is not installed at {ISCC}")
def test_a_fake_kit_really_compiles(tmp_path):
    kit = tmp_path / "kit"
    for sub in ("app/deploy", "app/assets", "app/bin"):
        (kit / sub).mkdir(parents=True)
    (kit / "app/deploy/install.ps1").write_text("exit 0\n")
    shutil.copy(REPO_DIR / "assets" / "visionguard.ico", kit / "app/assets/visionguard.ico")
    (kit / "app/bin/VisionGuardControl.exe").write_bytes(b"MZ-not-real")
    (kit / "python-3.14.0-amd64.exe").write_bytes(b"MZ-not-real")
    out = tmp_path / "out"
    done = subprocess.run(
        [str(ISCC), f"/DKitDir={kit}", "/DAppVersion=test", f"/O{out}", str(ISS)],
        capture_output=True,
        text=True,
    )
    assert done.returncode == 0, done.stdout + done.stderr
    assert (out / "VisionGuard-Setup-test.exe").exists()
