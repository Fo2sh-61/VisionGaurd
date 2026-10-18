"""`engine/tools/tls_names.py add <address>` (spec 020, T019).

Setup adds the workstation's NetBird address to the site certificate's names,
so an enrolled phone opens the console with no warning. It edits the site's
own engine.yaml, which a person wrote and commented, so it changes the one
list and nothing else: comments, other keys and line endings stay as they were.
"""

from __future__ import annotations

import importlib.util
from pathlib import Path

import pytest

ENGINE_DIR = Path(__file__).resolve().parents[1]


def tool():
    spec = importlib.util.spec_from_file_location(
        "tls_names", ENGINE_DIR / "tools" / "tls_names.py")
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


FLOW = (
    "site_name: Test\n"
    "tls:\n"
    "  names: [192.168.1.5, 127.0.0.1, localhost]   # 192.168.1.5: this PC's Wi-Fi\n"
    "  cert_dir: C:\\VisionGuard\\data\\tls\n"
    "\n"
    "storage:\n"
    "  names: [not, this, one]\n"
)

BLOCK = (
    "tls:\n"
    "  # the addresses phones use\n"
    "  names:\n"
    "    - 192.168.1.5\n"
    "    - 127.0.0.1   # this machine\n"
    "    - localhost\n"
    "  cert_dir: C:\\VisionGuard\\data\\tls\n"
    "storage: {}\n"
)


def write(tmp_path, text, newline="\n"):
    path = tmp_path / "engine.yaml"
    path.write_bytes(text.replace("\n", newline).encode("utf-8"))
    return path


def test_adds_to_a_one_line_list_and_keeps_its_comment(tmp_path):
    path = write(tmp_path, FLOW)
    assert tool().add(path, "100.81.4.7") is True
    text = path.read_text(encoding="utf-8")
    assert ("  names: [192.168.1.5, 127.0.0.1, localhost, 100.81.4.7]"
            "   # 192.168.1.5: this PC's Wi-Fi\n") in text
    assert "  names: [not, this, one]\n" in text          # another block's key
    assert text.replace(", 100.81.4.7", "") == FLOW         # nothing else moved


def test_adds_to_a_list_written_one_item_a_line(tmp_path):
    path = write(tmp_path, BLOCK)
    assert tool().add(path, "100.81.4.7") is True
    assert path.read_text(encoding="utf-8") == BLOCK.replace(
        "    - localhost\n", "    - localhost\n    - 100.81.4.7\n")


def test_an_address_already_there_changes_nothing(tmp_path):
    path = write(tmp_path, FLOW)
    before = path.read_bytes()
    assert tool().add(path, "127.0.0.1") is False
    assert path.read_bytes() == before


def test_windows_line_endings_stay(tmp_path):
    path = write(tmp_path, FLOW, newline="\r\n")
    tool().add(path, "100.81.4.7")
    data = path.read_bytes()
    assert data.count(b"\r\n") == FLOW.count("\n") and b"\n" not in data.replace(b"\r\n", b"")


def test_no_tls_block_is_refused_plainly(tmp_path):
    path = write(tmp_path, "storage: {}\n")
    names = tool()
    with pytest.raises(names.NamesError, match="no tls block"):
        names.add(path, "100.81.4.7")


@pytest.mark.parametrize("bad", ["school.example", "100.81.4.7/16", ""])
def test_only_an_address_is_accepted(tmp_path, bad):
    path = write(tmp_path, FLOW)
    names = tool()
    with pytest.raises(names.NamesError, match="not an IP address"):
        names.add(path, bad)


def test_the_result_still_loads_as_the_engine_reads_it(tmp_path):
    from vg import config as vgconfig

    path = write(tmp_path, FLOW)
    tool().add(path, "100.81.4.7")
    import yaml
    raw = yaml.safe_load(path.read_text(encoding="utf-8"))
    tls = vgconfig.TlsConfig.parse(raw["tls"], "tls", tmp_path)
    assert tls.names == ("192.168.1.5", "127.0.0.1", "localhost", "100.81.4.7")


def test_main_reports_what_it_did(tmp_path, capsys):
    path = write(tmp_path, FLOW)
    assert tool().main(["add", "100.81.4.7", "--file", str(path)]) == 0
    assert "added 100.81.4.7" in capsys.readouterr().out
    assert tool().main(["add", "100.81.4.7", "--file", str(path)]) == 0
    assert "already listed" in capsys.readouterr().out
    assert tool().main(["add", "nope", "--file", str(path)]) == 1
