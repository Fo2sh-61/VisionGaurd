"""The control app: the icon by the clock and its window (deploy/control/*.cs).

It is built by the .NET Framework compiler that ships with Windows, which only
understands C# 5. If a change here uses newer syntax the kit cannot be built,
so the test compiles it for real wherever that compiler exists.
"""
import subprocess
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[2]
SOURCES = sorted((ROOT / "deploy" / "control").glob("*.cs"))
ICON = ROOT / "assets" / "visionguard-control.ico"
CSC = Path(r"C:\Windows\Microsoft.NET\Framework64\v4.0.30319\csc.exe")


def _text() -> str:
    return "\n".join(f.read_text(encoding="utf-8") for f in SOURCES)


def _compile(out: Path, optimize: bool = False) -> subprocess.CompletedProcess:
    """The exact command the kit is built with (tools/make_release.ps1)."""
    return subprocess.run(
        [
            str(CSC), "/nologo", "/target:winexe", *(["/optimize+"] if optimize else []),
            f"/out:{out}", f"/win32icon:{ICON}",
            "/r:System.dll", "/r:System.Drawing.dll",
            "/r:System.Windows.Forms.dll", "/r:System.ServiceProcess.dll",
            *map(str, SOURCES),
        ],
        capture_output=True, text=True, timeout=120,
    )


def test_compiles_with_the_built_in_compiler(tmp_path):
    if not CSC.exists():
        pytest.skip("csc.exe (.NET Framework 4) is not on this machine")
    out = tmp_path / "VisionGuardControl.exe"
    done = _compile(out, optimize=True)
    assert done.returncode == 0, done.stdout + done.stderr
    assert out.exists()


@pytest.mark.parametrize("needle", [
    'Local\\\\VisionGuardControl',
    "visionguard-engine",
    "visionguard-front",
    "https://localhost/healthz",
    "start-failure.txt",
    "Exit VisionGuard Control (cameras keep running)",
    "Stop VisionGuard and exit",
    "--app=",
    'Local\\\\VisionGuardControlShow',
    "autostart.txt",
    "VisionGuard start at boot",
    "Start automatically when the PC starts",
    "Open VisionGuard Control",
    "C:\\Users\\Public\\Desktop\\VisionGuard.lnk",
])
def test_source_names_what_the_contract_needs(needle):
    assert needle in _text()


def test_certificate_checks_are_never_switched_off():
    assert "ServerCertificateValidationCallback" not in _text()


def test_it_leaves_when_windows_or_setup_asks():
    """19 Oct 2026: Setup's "close the applications" could not close the icon,
    because its X only hides the window. A session ending (sign-out, restart, or
    the Restart Manager an installer uses) now ends it, and Setup ends it
    itself before copying files."""
    text = _text()
    assert "SystemEvents.SessionEnding += OnSessionEnding" in text
    assert "SystemEvents.SessionEnding -= OnSessionEnding" in text
    iss = (ROOT / "deploy" / "setup" / "VisionGuard.iss").read_text(encoding="utf-8")
    prepare = iss.split("function PrepareToInstall", 1)[1].split("end;", 1)[0]
    assert "taskkill.exe'), '/F /IM VisionGuardControl.exe'" in prepare
    # before the services, so nothing is left holding app\bin
    assert prepare.index("VisionGuardControl.exe") < prepare.index("stop visionguard-front")


def test_the_finish_page_lists_only_the_installers_warnings():
    """19 Oct 2026: ultralytics' own "WARNING ..." lines were collected too."""
    iss = (ROOT / "deploy" / "setup" / "VisionGuard.iss").read_text(encoding="utf-8")
    assert "if Copy(S, 1, 13) = '    WARNING  ' then" in iss
    assert "if Pos('WARNING', S) > 0 then" not in iss
    install = (ROOT / "deploy" / "install.ps1").read_text(encoding="utf-8")
    assert 'Write-Host ("    WARNING  ' in install


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
    assert _compile(out).returncode == 0
    done = subprocess.run([str(out), "--check"], capture_output=True, text=True, timeout=30)
    said = done.stdout.strip()
    assert said.startswith("VisionGuard")
    assert (done.returncode == 0) == (said == "VisionGuard is running")


@pytest.fixture(scope="module")
def built(tmp_path_factory):
    if not CSC.exists():
        pytest.skip("csc.exe (.NET Framework 4) is not on this machine")
    out = tmp_path_factory.mktemp("control") / "VisionGuardControl.exe"
    done = _compile(out)
    assert done.returncode == 0, done.stdout + done.stderr
    return out


@pytest.mark.parametrize("text", [
    "https://192.168.1.5:8443/",
    "x",
    "0123456789abcdefghijklmnopqrstuvwxyz0123456789abcdefghijklmnopqr",
    "https://192.168.100.200:8443/some/very/long/path/" + "segment-" * 15 + "end?token=abcdef0123456789",
])
def test_qr_picture_decodes_to_the_same_text(built, tmp_path, text):
    """The proof the encoder is right: an independent reader gets the text back."""
    cv2 = pytest.importorskip("cv2")
    png = tmp_path / "qr.png"
    done = subprocess.run([str(built), "--qr", text, str(png)], capture_output=True, text=True, timeout=30)
    assert done.returncode == 0, done.stdout + done.stderr
    image = cv2.imread(str(png))
    assert image is not None
    decoded, _points, _raw = cv2.QRCodeDetector().detectAndDecode(image)
    assert decoded == text


@pytest.mark.parametrize("yaml, expected", [
    # the drill site's own line, comment and all
    ("tls:\n  names: [192.168.1.5, 127.0.0.1, localhost]   # this PC's Wi-Fi\n"
     "  cert_dir: C:\\VisionGuard\\data\\tls\n", "https://192.168.1.5:8443/"),
    ("tls:\n  names:\n    - localhost\n    - 10.0.0.7\n", "https://10.0.0.7:8443/"),
    ("tls:\n  names: [127.0.0.1, localhost]\n", "none"),
    ("api:\n  port: 8000\n# tls:\n#   names: [192.168.1.20]\n", "none"),
    ("other:\n  names: [192.168.9.9]\ntls:\n  names: ['172.16.0.4']\n", "https://172.16.0.4:8443/"),
])
def test_phone_address_comes_from_tls_names(built, tmp_path, yaml, expected):
    path = tmp_path / "engine.yaml"
    path.write_text(yaml, encoding="utf-8")
    done = subprocess.run([str(built), "--phone-address", str(path)],
                          capture_output=True, text=True, timeout=30)
    assert done.stdout.strip() == expected
    assert (done.returncode == 0) == (expected != "none")


def test_task_state_is_one_of_three_honest_answers(built):
    """The window's "is automatic start set up?" answer comes from the Task
    Scheduler's own error codes, so it can tell "missing" from "not allowed"."""
    done = subprocess.run([str(built), "--task-state"], capture_output=True, text=True, timeout=30)
    assert done.stdout.strip() in ("set-up", "missing", "unknown")
    assert (done.returncode == 0) == (done.stdout.strip() == "set-up")
    assert 'ProcessStartInfo("schtasks' not in _text()
    assert 'GetTypeFromProgID("Schedule.Service")' in _text()


def test_qr_refuses_text_that_is_too_long(built, tmp_path):
    done = subprocess.run([str(built), "--qr", "a" * 300, str(tmp_path / "q.png")],
                          capture_output=True, text=True, timeout=30)
    assert done.returncode != 0
    assert not (tmp_path / "q.png").exists()
