"""Add an address to the site certificate's names (spec 020).

    python engine/tools/tls_names.py add 100.81.4.7

Setup runs this with the workstation's NetBird address, then re-makes the site
certificate (`site_cert.py site`), so an enrolled phone opens the console at
that address with no warning. Devices keep trusting the same root.

It edits the site's own engine.yaml (`VG_HOME`'s, else the engine's), which a
person wrote and commented, so it changes the `tls.names` list and nothing
else: comments, other keys and line endings stay as they were. An address that
is already listed changes nothing.
"""

from __future__ import annotations

import argparse
import ipaddress
import os
import re
import sys
from pathlib import Path

import yaml

ENGINE_DIR = Path(__file__).resolve().parents[1]


class NamesError(Exception):
    """Why the list could not be changed. Safe to show."""


def _config_file() -> Path:
    home = os.environ.get("VG_HOME", "").strip()
    return (Path(home) if home else ENGINE_DIR) / "engine.yaml"


def add(path: Path, address: str) -> bool:
    """Add `address` to `tls.names`. False when it was already there."""
    try:
        address = str(ipaddress.ip_address(address.strip()))
    except ValueError:
        raise NamesError(f"{address!r} is not an IP address") from None

    data = path.read_bytes()
    newline = "\r\n" if b"\r\n" in data else "\n"
    text = data.decode("utf-8")
    raw = yaml.safe_load(text) or {}
    tls = raw.get("tls")
    if not isinstance(tls, dict) or not isinstance(tls.get("names"), list):
        raise NamesError(f"{path} has no tls block with a names list")
    if address in [str(n).strip() for n in tls["names"]]:
        return False

    lines = text.splitlines(keepends=True)
    start = next(i for i, l in enumerate(lines) if re.match(r"tls:\s*(#.*)?$", l.rstrip("\r\n")))
    end = next((i for i in range(start + 1, len(lines))
                if lines[i].strip() and not lines[i][0].isspace()), len(lines))
    for i in range(start + 1, end):
        flow = re.match(r"^(\s+names:\s*\[)([^\]]*)(\].*)$", lines[i].rstrip("\r\n"))
        if flow:
            items = flow.group(2).rstrip()
            joined = f"{items}, {address}" if items.strip() else address
            lines[i] = flow.group(1) + joined + flow.group(3) + newline
            break
        if re.match(r"^\s+names:\s*(#.*)?$", lines[i].rstrip("\r\n")):
            last = i
            for j in range(i + 1, end):
                if re.match(r"^\s+-\s", lines[j]):
                    last = j
                elif lines[j].strip() and not lines[j].lstrip().startswith("#"):
                    break
            indent = re.match(r"^(\s+)-", lines[last]).group(1) if last > i else \
                re.match(r"^(\s*)", lines[i]).group(1) + "  "
            lines.insert(last + 1, f"{indent}- {address}{newline}")
            break
    else:
        raise NamesError(f"could not find the names line in {path}'s tls block")

    updated = "".join(lines)
    check = (yaml.safe_load(updated) or {}).get("tls", {}).get("names", [])
    if address not in [str(n).strip() for n in check]:
        raise NamesError(f"could not add {address} to {path}; nothing was written")
    path.write_bytes(updated.encode("utf-8"))
    return True


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("action", choices=["add"])
    parser.add_argument("address")
    parser.add_argument("--file", type=Path, default=None,
                        help="the engine.yaml to change (default: VG_HOME's)")
    args = parser.parse_args(argv)
    path = args.file or _config_file()
    try:
        added = add(path, args.address)
    except (NamesError, OSError) as exc:
        print(f"  not done: {exc}", file=sys.stderr)
        return 1
    print(f"  added {args.address} to tls.names in {path}" if added
          else f"  {args.address} is already listed in {path}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
