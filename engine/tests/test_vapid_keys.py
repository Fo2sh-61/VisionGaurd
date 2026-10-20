"""`engine/tools/make_vapid_keys.py` (spec 020, T036).

Setup runs it on every install. The first time it makes the site's Web Push
keys and adds them to the site's `.env`; after that it changes nothing, because
new keys would cut off every phone already switched on. The private key is
never printed.
"""

from __future__ import annotations

import base64
import importlib.util
from pathlib import Path

ENGINE_DIR = Path(__file__).resolve().parents[1]


def tool():
    spec = importlib.util.spec_from_file_location(
        "make_vapid_keys", ENGINE_DIR / "tools" / "make_vapid_keys.py")
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def values(path: Path) -> dict[str, str]:
    out = {}
    for line in path.read_text(encoding="utf-8").splitlines():
        if "=" in line and not line.lstrip().startswith("#"):
            name, _, value = line.partition("=")
            out[name.strip()] = value.strip()
    return out


def raw(text: str) -> bytes:
    return base64.urlsafe_b64decode(text + "=" * (-len(text) % 4))


def test_the_first_run_adds_the_three_keys_and_keeps_the_rest(tmp_path, capsys):
    env = tmp_path / ".env"
    env.write_text("# cameras\nVG_RTSP_1=rtsp://x\nGMAIL_USER=vg.factory@gmail.com\n",
                   encoding="utf-8")
    assert tool().main(["--env", str(env)]) == 0
    found = values(env)
    assert found["VG_RTSP_1"] == "rtsp://x" and "# cameras" in env.read_text(encoding="utf-8")
    public, private = raw(found["VG_VAPID_PUBLIC_KEY"]), raw(found["VG_VAPID_PRIVATE_KEY"])
    assert len(public) == 65 and public[0] == 4 and len(private) == 32
    assert found["VG_VAPID_SUBJECT"] == "mailto:vg.factory@gmail.com"
    printed = capsys.readouterr().out
    assert found["VG_VAPID_PRIVATE_KEY"] not in printed
    assert "made" in printed


def test_a_second_run_changes_nothing(tmp_path, capsys):
    env = tmp_path / ".env"
    tool().main(["--env", str(env)])
    before = env.read_bytes()
    assert tool().main(["--env", str(env)]) == 0
    assert env.read_bytes() == before
    assert "already" in capsys.readouterr().out


def test_without_a_site_address_the_subject_is_a_placeholder_that_says_so(tmp_path):
    env = tmp_path / ".env"
    tool().main(["--env", str(env)])
    assert values(env)["VG_VAPID_SUBJECT"] == "https://visionguard.invalid"


def test_windows_line_endings_stay(tmp_path):
    env = tmp_path / ".env"
    env.write_bytes(b"VG_RTSP_1=\r\nGMAIL_USER=\r\n")
    tool().main(["--env", str(env)])
    data = env.read_bytes()
    assert b"\n" not in data.replace(b"\r\n", b"")


def test_the_example_names_them(tmp_path):
    example = (ENGINE_DIR / ".env.example").read_text(encoding="utf-8")
    for name in ("VG_VAPID_PUBLIC_KEY=", "VG_VAPID_PRIVATE_KEY=", "VG_VAPID_SUBJECT="):
        assert name in example
