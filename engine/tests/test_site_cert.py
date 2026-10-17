"""The site's own root and HTTPS certificate (spec 016, plan B).

The root is limited to private addresses, so a stolen root key can never vouch
for a public website. Its key lives on the owner's USB stick: these tests pin
that it is never written next to the site certificate, and never inside the
install or backup folders.
"""

from __future__ import annotations

import ipaddress
import sys
from datetime import datetime, timedelta, timezone
from pathlib import Path

import pytest
from cryptography import x509
from cryptography.hazmat.primitives.asymmetric import ec
from cryptography.x509.oid import ExtendedKeyUsageOID

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "tools"))

import site_cert  # noqa: E402

NOW = datetime(2026, 10, 17, 9, 0, tzinfo=timezone.utc)
NAMES = ("192.168.1.20", "127.0.0.1", "localhost")


def _cert(path: Path) -> x509.Certificate:
    return x509.load_pem_x509_certificate(path.read_bytes())


@pytest.fixture
def usb(tmp_path):
    out = tmp_path / "usb"
    out.mkdir()
    return out


@pytest.fixture
def root(usb, tmp_path):
    site_cert.make_root(usb, forbidden=(tmp_path / "VisionGuard",), now=NOW)
    return usb


class TestRoot:
    def test_is_a_p256_ca_with_path_length_zero_for_ten_years(self, root):
        crt = _cert(root / site_cert.ROOT_CRT)
        assert isinstance(crt.public_key(), ec.EllipticCurvePublicKey)
        assert crt.public_key().curve.name == "secp256r1"
        basic = crt.extensions.get_extension_for_class(x509.BasicConstraints)
        assert basic.critical and basic.value.ca and basic.value.path_length == 0
        assert crt.not_valid_before_utc == NOW
        years = (crt.not_valid_after_utc - crt.not_valid_before_utc).days / 365.25
        assert 9.99 < years < 10.01

    def test_is_limited_to_private_addresses_and_localhost(self, root):
        crt = _cert(root / site_cert.ROOT_CRT)
        nc = crt.extensions.get_extension_for_class(x509.NameConstraints)
        assert nc.critical
        nets = {g.value for g in nc.value.permitted_subtrees
                if isinstance(g, x509.IPAddress)}
        assert nets == {ipaddress.ip_network(n) for n in (
            "10.0.0.0/8", "172.16.0.0/12", "192.168.0.0/16",
            "100.64.0.0/10", "127.0.0.0/8")}
        dns = {g.value for g in nc.value.permitted_subtrees
               if isinstance(g, x509.DNSName)}
        assert dns == {"localhost"}
        assert not nc.value.excluded_subtrees

    def test_no_limits_makes_a_root_without_constraints(self, usb, tmp_path):
        site_cert.make_root(usb, limits=False, forbidden=(), now=NOW)
        crt = _cert(usb / site_cert.ROOT_CRT)
        with pytest.raises(x509.ExtensionNotFound):
            crt.extensions.get_extension_for_class(x509.NameConstraints)

    def test_writes_only_to_the_usb_folder(self, root):
        assert sorted(p.name for p in root.iterdir()) == sorted(
            [site_cert.ROOT_CRT, site_cert.ROOT_KEY])

    def test_out_inside_the_install_folder_is_refused(self, tmp_path):
        install = tmp_path / "VisionGuard"
        (install / "data").mkdir(parents=True)
        with pytest.raises(site_cert.CertError, match="USB stick"):
            site_cert.make_root(install / "data", forbidden=(install,), now=NOW)
        assert not any((install / "data").iterdir())

    def test_out_inside_the_backup_folder_is_refused(self, tmp_path):
        backups = tmp_path / "Backups"
        backups.mkdir()
        with pytest.raises(site_cert.CertError, match="USB stick"):
            site_cert.make_root(backups, forbidden=(tmp_path / "VisionGuard", backups),
                                now=NOW)

    def test_an_existing_root_is_never_replaced(self, root):
        # A new root would make every device that trusts the old one refuse
        # the site. Replacing it has to be a deliberate act, not a re-run.
        before = (root / site_cert.ROOT_KEY).read_bytes()
        with pytest.raises(site_cert.CertError, match="already"):
            site_cert.make_root(root, forbidden=(), now=NOW)
        assert (root / site_cert.ROOT_KEY).read_bytes() == before


class TestSite:
    def test_names_purpose_lifetime_and_signer(self, root, tmp_path):
        cert_dir = tmp_path / "data" / "tls"
        site_cert.make_site(root, NAMES, cert_dir, now=NOW)
        leaf = _cert(cert_dir / site_cert.SITE_CRT)
        ca = _cert(root / site_cert.ROOT_CRT)

        san = leaf.extensions.get_extension_for_class(x509.SubjectAlternativeName).value
        got = [str(v) for v in san.get_values_for_type(x509.IPAddress)]
        got += san.get_values_for_type(x509.DNSName)
        assert sorted(got) == sorted(NAMES)

        basic = leaf.extensions.get_extension_for_class(x509.BasicConstraints)
        assert basic.value.ca is False
        eku = leaf.extensions.get_extension_for_class(x509.ExtendedKeyUsage).value
        assert list(eku) == [ExtendedKeyUsageOID.SERVER_AUTH]
        assert (leaf.not_valid_after_utc - leaf.not_valid_before_utc) == timedelta(days=825)

        assert leaf.issuer == ca.subject
        leaf.verify_directly_issued_by(ca)

    def test_a_public_address_is_refused_with_a_plain_reason(self, root, tmp_path):
        cert_dir = tmp_path / "tls"
        with pytest.raises(site_cert.CertError, match="8.8.8.8.*private"):
            site_cert.make_site(root, ("127.0.0.1", "8.8.8.8"), cert_dir, now=NOW)
        assert not cert_dir.exists() or not any(cert_dir.iterdir())

    def test_an_unlimited_root_signs_any_address(self, usb, tmp_path):
        site_cert.make_root(usb, limits=False, forbidden=(), now=NOW)
        site_cert.make_site(usb, ("8.8.8.8",), tmp_path / "tls", now=NOW)

    def test_the_root_key_is_never_written_to_cert_dir(self, root, tmp_path):
        cert_dir = tmp_path / "tls"
        site_cert.make_site(root, NAMES, cert_dir, now=NOW)
        key = (root / site_cert.ROOT_KEY).read_bytes()
        names = sorted(p.name for p in cert_dir.iterdir())
        assert names == sorted([site_cert.SITE_CRT, site_cert.SITE_KEY])
        for p in cert_dir.iterdir():
            assert p.read_bytes() != key

    def test_a_rerun_replaces_the_site_certificate(self, root, tmp_path):
        # An address changed: re-run, devices keep trusting the same root.
        cert_dir = tmp_path / "tls"
        site_cert.make_site(root, NAMES, cert_dir, now=NOW)
        site_cert.make_site(root, ("192.168.1.30", "localhost"), cert_dir, now=NOW)
        leaf = _cert(cert_dir / site_cert.SITE_CRT)
        san = leaf.extensions.get_extension_for_class(x509.SubjectAlternativeName).value
        assert [str(v) for v in san.get_values_for_type(x509.IPAddress)] == ["192.168.1.30"]

    def test_a_missing_root_says_where_it_looked(self, tmp_path):
        with pytest.raises(site_cert.CertError, match="no root"):
            site_cert.make_site(tmp_path, NAMES, tmp_path / "tls", now=NOW)
