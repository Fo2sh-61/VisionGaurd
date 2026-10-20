"""Phone notifications: Web Push, from the workstation to a registered phone (spec 020).

    send(message, destination=push_device id) -> SendResult

The same seam as email (`providers.py`). Three rules hold it:

**Only to the browsers' own push services** (P9-FR-108). A phone's
subscription names a URL the workstation will call. Accepted only when it is
`https` on the default port to a host in `push.allowed_hosts` - checked when a
phone registers and again before every send - so a signed-in user can never
make the workstation call into the factory network.

**Nothing readable on the way** (P9-FR-104). Web Push encrypts the message for
the one phone (RFC 8291); the push service carries bytes it cannot read. The
workstation signs with its own VAPID keys, made at install time and kept in
`.env`; no Google or Firebase account is involved.

**A failure is a row** (P9-FR-106): no internet, a refused message, or a
phone the push service has forgotten (404/410, which also removes the phone
and its recipient). A phone whose account is disabled is not sent to at all.
"""

from __future__ import annotations

import base64
import ipaddress
import json
import os
from collections.abc import Callable, Sequence
from datetime import datetime, timezone
from urllib.parse import urlsplit

import requests
from pywebpush import WebPushException, webpush as _webpush

from vg.alerts.catalogue import Message
from vg.alerts.providers import SendResult

__all__ = ["PushSender", "WebPushException", "endpoint_allowed", "make_vapid_keys"]

#: How long a push service keeps a notification for a phone that is off or
#: out of signal. Late is still useful - the notification carries its time.
TTL_SECONDS = 3600
#: The longest subscription URL accepted. Real ones are a few hundred bytes.
MAX_ENDPOINT = 2048


def endpoint_allowed(url: str, allowed_hosts: Sequence[str]) -> bool:
    """Is this a push service the workstation may call? Never raises."""
    if not url or len(url) > MAX_ENDPOINT:
        return False
    try:
        parts = urlsplit(url)
        port = parts.port
    except ValueError:
        return False
    host = (parts.hostname or "").lower()
    if parts.scheme != "https" or not host or parts.username or parts.password:
        return False
    if port not in (None, 443):
        return False
    try:
        ipaddress.ip_address(host)
        return False                    # an address, never a name: refused outright
    except ValueError:
        pass
    for pattern in allowed_hosts:
        if pattern.startswith("*."):
            if host.endswith(pattern[1:]) and host != pattern[2:]:
                return True
        elif host == pattern:
            return True
    return False


def _b64(raw: bytes) -> str:
    return base64.urlsafe_b64encode(raw).rstrip(b"=").decode("ascii")


def make_vapid_keys() -> tuple[str, str]:
    """A new VAPID key pair: (public, private), both base64url.

    The public key is what a phone subscribes with (`applicationServerKey`);
    the private one signs every message and never leaves `.env`.
    """
    from cryptography.hazmat.primitives import serialization
    from cryptography.hazmat.primitives.asymmetric import ec

    key = ec.generate_private_key(ec.SECP256R1())
    private = key.private_numbers().private_value.to_bytes(32, "big")
    public = key.public_key().public_bytes(
        serialization.Encoding.X962, serialization.PublicFormat.UncompressedPoint)
    return _b64(public), _b64(private)


class PushSender:
    """One notification to one registered phone."""

    def __init__(self, *, store, allowed_hosts: Sequence[str],
                 user_active: Callable[[str], bool] | None = None,
                 timeout: float = 10.0, webpush=_webpush) -> None:
        self.store = store
        self.allowed_hosts = tuple(allowed_hosts)
        self.user_active = user_active
        self.timeout = timeout
        self._webpush = webpush

    def send(self, message: Message, destination: str) -> SendResult:
        device = self.store.push_device(destination)
        if device is None:
            return SendResult.failed("device_gone", "this phone is no longer registered")
        if self.user_active is not None and not self.user_active(device.user_id):
            return SendResult.failed("account_disabled", "the phone's account is disabled")
        if not endpoint_allowed(device.endpoint, self.allowed_hosts):
            return SendResult.failed("provider_refused",
                                     "the phone's push address is not a known push service")

        payload = json.dumps({"title": message.subject, "body": message.body,
                              "path": message.path}, ensure_ascii=False)
        try:
            answer = self._webpush(
                subscription_info={"endpoint": device.endpoint,
                                   "keys": {"p256dh": device.p256dh, "auth": device.auth}},
                data=payload,
                vapid_private_key=os.environ.get("VG_VAPID_PRIVATE_KEY", "").strip(),
                vapid_claims={"sub": os.environ.get("VG_VAPID_SUBJECT", "").strip()},
                ttl=TTL_SECONDS,
                timeout=self.timeout,
            )
        except WebPushException as exc:
            status = getattr(exc.response, "status_code", None)
            if status in (404, 410):
                self.store.remove_push_device(device.id)
                return SendResult.failed(
                    "device_gone",
                    f"the push service no longer knows this phone (HTTP {status}); "
                    "it was removed and must switch notifications on again")
            words = f"the push service refused it (HTTP {status})" if status else "WebPushException"
            self.store.note_push(device.id, error=words)
            return SendResult.failed("provider_refused", words)
        except requests.Timeout:
            self.store.note_push(device.id, error="timeout")
            return SendResult.failed("timeout", "the push service did not answer in time")
        except (requests.ConnectionError, OSError) as exc:
            words = f"no internet ({type(exc).__name__})"
            self.store.note_push(device.id, error=words)
            return SendResult.failed("unreachable", words)
        self.store.note_push(device.id, sent_at=datetime.now(timezone.utc))
        headers = getattr(answer, "headers", None) or {}
        return SendResult.accepted(headers.get("Location") or f"push:{device.id}")
