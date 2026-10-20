"""Make the site's Web Push keys, once (spec 020, phone notifications).

    python engine/tools/make_vapid_keys.py

Setup runs this on every install. The first time it makes a VAPID key pair
and adds three lines to the site's `.env` (`VG_HOME`'s, else the engine's):

    VG_VAPID_PUBLIC_KEY    what each phone subscribes with
    VG_VAPID_PRIVATE_KEY   signs every notification; never leaves .env
    VG_VAPID_SUBJECT       who the push services may contact: the site's own
                           Gmail address (GMAIL_USER) when there is one

After that it changes nothing: new keys would silently cut off every phone
already switched on. No Google or Firebase account is involved. The private
key is never printed. Keep `.env` in the backup; losing it means every phone
must switch notifications on again.
"""

from __future__ import annotations

import argparse
import os
import sys
from pathlib import Path

ENGINE_DIR = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ENGINE_DIR))

NAMES = ("VG_VAPID_PUBLIC_KEY", "VG_VAPID_PRIVATE_KEY", "VG_VAPID_SUBJECT")
#: When the site has no address of its own yet. `.invalid` can never be a
#: real place, so nobody is contacted by mistake; set a real one in .env.
PLACEHOLDER_SUBJECT = "https://visionguard.invalid"


def _env_file() -> Path:
    home = os.environ.get("VG_HOME", "").strip()
    return (Path(home) if home else ENGINE_DIR) / ".env"


def _values(text: str) -> dict[str, str]:
    out = {}
    for line in text.splitlines():
        if "=" in line and not line.lstrip().startswith("#"):
            name, _, value = line.partition("=")
            out[name.strip()] = value.strip()
    return out


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("--env", type=Path, default=None,
                        help="the .env to add the keys to (default: VG_HOME's)")
    args = parser.parse_args(argv)
    env = args.env or _env_file()

    data = env.read_bytes() if env.exists() else b""
    newline = "\r\n" if b"\r\n" in data else "\n"
    text = data.decode("utf-8")
    current = _values(text)
    if all(current.get(name) for name in NAMES):
        print(f"  push keys: already in {env} (kept; new ones would cut off every phone)")
        return 0

    from vg.alerts.push import make_vapid_keys

    public, private = make_vapid_keys()
    gmail = current.get("GMAIL_USER", "")
    subject = f"mailto:{gmail}" if "@" in gmail else PLACEHOLDER_SUBJECT
    wanted = {"VG_VAPID_PUBLIC_KEY": public, "VG_VAPID_PRIVATE_KEY": private,
              "VG_VAPID_SUBJECT": subject}

    lines = text.splitlines()
    for i, line in enumerate(lines):
        name = line.partition("=")[0].strip()
        if name in wanted and not line.lstrip().startswith("#"):
            lines[i] = f"{name}={wanted.pop(name)}"
    if wanted:
        if lines and lines[-1].strip():
            lines.append("")
        lines.append("# Phone notifications (spec 020): made by make_vapid_keys.py. Keep in the backup.")
        lines += [f"{name}={value}" for name, value in wanted.items()]
    env.parent.mkdir(parents=True, exist_ok=True)
    env.write_bytes((newline.join(lines) + newline).encode("utf-8"))
    print(f"  push keys: made and added to {env}; contact {subject}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
