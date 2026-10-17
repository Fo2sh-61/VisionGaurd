"""The site's own HTTPS certificate, and the root that vouches for it.

    python engine/tools/site_cert.py root --out E:\\
    python engine/tools/site_cert.py site --root E:\\

**Two steps, two places.** `root` runs once per site and writes the root's
public `.crt` and private `.key` to the owner's USB stick, nowhere else. `site`
reads `tls.names` from engine.yaml and writes `site.crt` and `site.key` into
`tls.cert_dir`, where the HTTPS front (Caddy) reads them. When an address
changes, re-run `site`: every device keeps trusting the same root.

**The root is limited.** Its name constraints permit only private addresses
(10/8, 172.16/12, 192.168/16, 100.64/10 for NetBird, 127/8) and the name
`localhost`. A device that trusts it can then never be fooled about a public
website, even if the key is stolen. `--no-limits` drops that, for a device that
refuses constrained roots; say why in the site's notes if you use it.

**The root key never touches the workstation.** `root --out` refuses the
install folder and the backup folder, and `site` writes only the site's own
pair. Only the public `visionguard-root.crt` is ever copied to a device.
"""

from __future__ import annotations

import argparse
import ipaddress
import os
import sys
from collections.abc import Iterable, Sequence
from datetime import datetime, timedelta, timezone
from pathlib import Path

from cryptography import x509
from cryptography.hazmat.primitives import hashes, serialization
from cryptography.hazmat.primitives.asymmetric import ec
from cryptography.x509.oid import ExtendedKeyUsageOID, NameOID

ENGINE_DIR = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ENGINE_DIR))

ROOT_CRT = "visionguard-root.crt"
ROOT_KEY = "visionguard-root.key"
SITE_CRT = "site.crt"
SITE_KEY = "site.key"

ROOT_DAYS = 3652        # ten years, leap days included
SITE_DAYS = 825         # the longest lifetime Apple devices accept

#: What a limited root may vouch for. 100.64/10 is NetBird's range (spec 020).
PRIVATE_NETWORKS = tuple(ipaddress.ip_network(n) for n in (
    "10.0.0.0/8", "172.16.0.0/12", "192.168.0.0/16", "100.64.0.0/10",
    "127.0.0.0/8",
))
PRIVATE_NAMES = ("localhost",)

#: Where the installed system lives. The root key must never land inside it.
INSTALL_DIR = Path(r"C:\VisionGuard")


class CertError(Exception):
    """A plain reason, printed as-is."""


def _inside(path: Path, folder: Path) -> bool:
    path, folder = path.resolve(), folder.resolve()
    return path == folder or folder in path.parents


def _write_key(path: Path, key: ec.EllipticCurvePrivateKey) -> None:
    data = key.private_bytes(
        serialization.Encoding.PEM,
        serialization.PrivateFormat.PKCS8,
        serialization.NoEncryption(),
    )
    # Owner-only where the file system honours the mode. FAT and NTFS do
    # not: on Windows the folder's rights, and the stick in a drawer, do it.
    fd = os.open(path, os.O_WRONLY | os.O_CREAT | os.O_TRUNC, 0o600)
    with os.fdopen(fd, "wb") as fh:
        fh.write(data)


def _write_crt(path: Path, crt: x509.Certificate) -> None:
    path.write_bytes(crt.public_bytes(serialization.Encoding.PEM))


def _name(common: str) -> x509.Name:
    return x509.Name([
        x509.NameAttribute(NameOID.ORGANIZATION_NAME, "VisionGuard"),
        x509.NameAttribute(NameOID.COMMON_NAME, common),
    ])


def make_root(out: Path, *, limits: bool = True,
              forbidden: Iterable[Path] = (INSTALL_DIR,),
              now: datetime | None = None) -> tuple[Path, Path]:
    """Write the root's `.crt` and `.key` into `out`. Returns both paths."""
    out = Path(out)
    for folder in forbidden:
        if _inside(out, Path(folder)):
            raise CertError(
                f"{out} is inside {folder}. The root key belongs on the "
                f"owner's USB stick, never on the workstation or in a backup")
    if (out / ROOT_KEY).exists() or (out / ROOT_CRT).exists():
        raise CertError(
            f"{out} already holds a root. Making a new one would make every "
            f"device that trusts the old one refuse the site. Use another "
            f"folder if you really mean to start again")
    if not out.is_dir():
        raise CertError(f"{out} is not a folder. Plug in the USB stick first")

    now = now or datetime.now(timezone.utc)
    key = ec.generate_private_key(ec.SECP256R1())
    name = _name("VisionGuard site root")
    builder = (
        x509.CertificateBuilder()
        .subject_name(name)
        .issuer_name(name)
        .public_key(key.public_key())
        .serial_number(x509.random_serial_number())
        .not_valid_before(now)
        .not_valid_after(now + timedelta(days=ROOT_DAYS))
        .add_extension(x509.BasicConstraints(ca=True, path_length=0), critical=True)
        .add_extension(x509.KeyUsage(
            digital_signature=False, content_commitment=False,
            key_encipherment=False, data_encipherment=False, key_agreement=False,
            key_cert_sign=True, crl_sign=True, encipher_only=False,
            decipher_only=False), critical=True)
        .add_extension(x509.SubjectKeyIdentifier.from_public_key(key.public_key()),
                       critical=False)
    )
    if limits:
        permitted: list[x509.GeneralName] = [
            x509.IPAddress(net) for net in PRIVATE_NETWORKS]
        permitted += [x509.DNSName(n) for n in PRIVATE_NAMES]
        builder = builder.add_extension(
            x509.NameConstraints(permitted_subtrees=permitted,
                                 excluded_subtrees=None),
            critical=True)
    crt = builder.sign(key, hashes.SHA256())

    crt_path, key_path = out / ROOT_CRT, out / ROOT_KEY
    _write_key(key_path, key)
    _write_crt(crt_path, crt)
    return crt_path, key_path


def _load_root(root_dir: Path) -> tuple[x509.Certificate, ec.EllipticCurvePrivateKey]:
    crt_path, key_path = Path(root_dir) / ROOT_CRT, Path(root_dir) / ROOT_KEY
    if not crt_path.is_file() or not key_path.is_file():
        raise CertError(
            f"no root in {root_dir}: expected {ROOT_CRT} and {ROOT_KEY}. "
            f"Plug in the USB stick, or make one with `site_cert.py root`")
    crt = x509.load_pem_x509_certificate(crt_path.read_bytes())
    key = serialization.load_pem_private_key(key_path.read_bytes(), password=None)
    if not isinstance(key, ec.EllipticCurvePrivateKey) or (
            key.public_key().public_numbers() != crt.public_key().public_numbers()):
        raise CertError(f"{ROOT_KEY} in {root_dir} does not belong to {ROOT_CRT}")
    return crt, key


def _covered(name: str, root: x509.Certificate) -> bool:
    """True when the root's name constraints (if any) permit this name."""
    try:
        nc = root.extensions.get_extension_for_class(x509.NameConstraints).value
    except x509.ExtensionNotFound:
        return True
    permitted = nc.permitted_subtrees or []
    try:
        address = ipaddress.ip_address(name)
    except ValueError:
        return any(isinstance(g, x509.DNSName) and g.value == name for g in permitted)
    return any(isinstance(g, x509.IPAddress) and address in g.value
               for g in permitted)


def make_site(root_dir: Path, names: Sequence[str], cert_dir: Path, *,
              now: datetime | None = None) -> tuple[Path, Path]:
    """Write `site.crt` and `site.key` for `names` into `cert_dir`."""
    if not names:
        raise CertError("no names to make a certificate for. Fill tls.names")
    root, root_key = _load_root(root_dir)

    refused = [n for n in names if not _covered(n, root)]
    if refused:
        raise CertError(
            f"the root does not cover {', '.join(refused)}. It is limited to "
            f"private addresses (10.x, 172.16-31.x, 192.168.x, 100.64-127.x, "
            f"127.x) and localhost, so a public address can never be signed")

    now = now or datetime.now(timezone.utc)
    end = min(now + timedelta(days=SITE_DAYS), root.not_valid_after_utc)
    sans: list[x509.GeneralName] = []
    for n in names:
        try:
            sans.append(x509.IPAddress(ipaddress.ip_address(n)))
        except ValueError:
            sans.append(x509.DNSName(n))

    key = ec.generate_private_key(ec.SECP256R1())
    crt = (
        x509.CertificateBuilder()
        .subject_name(_name(names[0]))
        .issuer_name(root.subject)
        .public_key(key.public_key())
        .serial_number(x509.random_serial_number())
        .not_valid_before(now)
        .not_valid_after(end)
        .add_extension(x509.SubjectAlternativeName(sans), critical=False)
        .add_extension(x509.BasicConstraints(ca=False, path_length=None), critical=True)
        .add_extension(x509.KeyUsage(
            digital_signature=True, content_commitment=False,
            key_encipherment=False, data_encipherment=False, key_agreement=False,
            key_cert_sign=False, crl_sign=False, encipher_only=False,
            decipher_only=False), critical=True)
        .add_extension(x509.ExtendedKeyUsage([ExtendedKeyUsageOID.SERVER_AUTH]),
                       critical=False)
        .add_extension(x509.SubjectKeyIdentifier.from_public_key(key.public_key()),
                       critical=False)
        .add_extension(
            x509.AuthorityKeyIdentifier.from_issuer_public_key(root_key.public_key()),
            critical=False)
        .sign(root_key, hashes.SHA256())
    )

    cert_dir = Path(cert_dir)
    cert_dir.mkdir(parents=True, exist_ok=True)
    crt_path, key_path = cert_dir / SITE_CRT, cert_dir / SITE_KEY
    _write_key(key_path, key)
    _write_crt(crt_path, crt)
    return crt_path, key_path


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="VisionGuard site certificate.")
    sub = parser.add_subparsers(dest="command", required=True)
    r = sub.add_parser("root", help="make the site root on the USB stick (once)")
    r.add_argument("--out", required=True, type=Path, help="the USB stick, e.g. E:\\")
    r.add_argument("--no-limits", action="store_true",
                   help="no name constraints (only for a device that refuses them)")
    r.add_argument("--backup-dir", type=Path, action="append", default=[],
                   help="a backup folder the key must stay out of (repeatable)")
    s = sub.add_parser("site", help="make this site's HTTPS certificate")
    s.add_argument("--root", required=True, type=Path, help="the USB stick, e.g. E:\\")
    args = parser.parse_args(argv)

    try:
        if args.command == "root":
            from vg import config as vgconfig
            forbidden = [INSTALL_DIR, vgconfig.REPO_DIR, *args.backup_dir]
            home = vgconfig.site_home()
            if home is not None:
                forbidden.append(home)
            crt, key = make_root(args.out, limits=not args.no_limits,
                                 forbidden=forbidden)
            print(f"\n  root written\n    {crt}  (copy this one to devices)\n"
                  f"    {key}  (keep on this stick only)\n")
        else:
            from vg import config as vgconfig
            tls = vgconfig.load().tls
            if tls is None:
                raise CertError(
                    "engine.yaml has no tls block. Add tls.names (the "
                    "workstation's address, 127.0.0.1 and localhost) first")
            if _inside(args.root, tls.cert_dir):
                raise CertError(
                    f"--root {args.root} is inside tls.cert_dir. The root "
                    f"belongs on the USB stick")
            crt, _ = make_site(args.root, tls.names, tls.cert_dir)
            print(f"\n  site certificate written to {crt.parent}\n"
                  f"    names  {', '.join(tls.names)}\n"
                  f"    until  {x509.load_pem_x509_certificate(crt.read_bytes()).not_valid_after_utc:%Y-%m-%d}\n")
    except CertError as exc:
        print(f"\n  not done: {exc}\n", file=sys.stderr)
        return 1
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
