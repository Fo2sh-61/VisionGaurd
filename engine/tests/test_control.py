"""The icon by the clock (deploy/control/VisionGuardControl.cs).

It is built by the .NET Framework compiler that ships with Windows, which only
understands C# 5. If a change here uses newer syntax the kit cannot be built,
so the test compiles it for real wherever that compiler exists.
"""
import subprocess
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[2]
SOURCE = ROOT / "deploy" / "control" / "VisionGuardControl.cs"
ICON = ROOT / "assets" / "visionguard.ico"
CSC = Path(r"C:\Windows\Microsoft.NET\Framework64\v4.0.30319\csc.exe")


def _text() -> str:
    return SOURCE.read_text(encoding="utf-8")


def test_compiles_with_the_built_in_compiler(tmp_path):
    if not CSC.exists():
        pytest.skip("csc.exe (.NET Framework 4) is not on this machine")
    out = tmp_path / "VisionGuardControl.exe"
    done = subprocess.run(
        [
            str(CSC), "/nologo", "/target:winexe", "/optimize+",
            f"/out:{out}", f"/win32icon:{ICON}",
            "/r:System.dll", "/r:System.Drawing.dll",
            "/r:System.Windows.Forms.dll", "/r:System.ServiceProcess.dll",
            str(SOURCE),
        ],
        capture_output=True, text=True, timeout=120,
    )
    assert done.returncode == 0, done.stdout + done.stderr
    assert out.exists()


@pytest.mark.parametrize("needle", [
    'Local\\\\VisionGuardControl',
    "visionguard-engine",
    "visionguard-front",
    "https://localhost/healthz",
    "start-failure.txt",
    "Hide this icon",
    "--app=",
])
def test_source_names_what_the_contract_needs(needle):
    assert needle in _text()


def test_certificate_checks_are_never_switched_off():
    assert "ServerCertificateValidationCallback" not in _text()


def test_results_never_go_back_through_the_menu():
    """Checker, 18 Oct 2026: a ContextMenuStrip has no window until it is first
    shown, so menu.BeginInvoke threw and the icon sat on "checking..." until
    somebody opened the menu. Results go through a window made at start."""
    text = _text()
    assert "menu.BeginInvoke" not in text
    assert "ui.Handle" in text and "ui.BeginInvoke" in text


def test_check_mode_says_where_visionguard_stands(tmp_path):
    """`--check` runs the icon's own check once: whatever this machine has,
    the answer is a plain sentence and exit 0 only when it is running."""
    if not CSC.exists():
        pytest.skip("csc.exe (.NET Framework 4) is not on this machine")
    out = tmp_path / "VisionGuardControl.exe"
    subprocess.run(
        [str(CSC), "/nologo", "/target:winexe", f"/out:{out}", f"/win32icon:{ICON}",
         "/r:System.dll", "/r:System.Drawing.dll", "/r:System.Windows.Forms.dll",
         "/r:System.ServiceProcess.dll", str(SOURCE)],
        check=True, capture_output=True, timeout=120,
    )
    done = subprocess.run([str(out), "--check"], capture_output=True, text=True, timeout=30)
    said = done.stdout.strip()
    assert said.startswith("VisionGuard")
    assert (done.returncode == 0) == (said == "VisionGuard is running")
