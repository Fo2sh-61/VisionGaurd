"""Twilio and Gmail - one sender per channel, behind one seam.

    send(message, destination) -> SendResult: accepted(provider_id) | failed(reason)

That seam is the whole contract. Swapping a provider later is a new class
here; rules, recipients and the delivery log never learn who carried a
message. There is deliberately one implementation per channel and no
fallback: a second courier that silently takes over is a second place a
message can go without anybody having decided it should.

**No SDK.** Twilio is one HTTPS form POST and Gmail is `smtplib`, both in the
standard library, so this adds nothing to requirements.txt (research.md §1).
Both take an injectable transport, so no test ever touches the network.

**The keys never leave.** They are read from the environment at send time,
and every word a failure carries is built from the courier's own error text or
an exception's class name - never `str(exc)`, which for urllib can include the
request URL, and Twilio's URL contains the Account SID - and then `redact()`
is run over it anyway.
"""

from __future__ import annotations

import base64
import json
import os
import smtplib
import ssl
import urllib.error
import urllib.parse
import urllib.request
from dataclasses import dataclass
from email.message import EmailMessage
from email.utils import make_msgid
from typing import Any, Callable, Protocol

from vg.alerts.catalogue import Message

TWILIO_URL = "https://api.twilio.com/2010-04-01/Accounts/{sid}/Messages.json"
GMAIL_HOST = "smtp.gmail.com"
GMAIL_PORT = 465

#: What each channel needs in engine/.env. The names are shown to an
#: administrator when missing; the values never are.
REQUIRED_ENV: dict[str, tuple[str, ...]] = {
    "whatsapp": ("TWILIO_ACCOUNT_SID", "TWILIO_AUTH_TOKEN", "TWILIO_WHATSAPP_FROM"),
    "sms": ("TWILIO_ACCOUNT_SID", "TWILIO_AUTH_TOKEN", "TWILIO_SMS_FROM"),
    "email": ("GMAIL_USER", "GMAIL_APP_PASSWORD"),
}

SECRET_ENV: tuple[str, ...] = tuple(sorted({v for vs in REQUIRED_ENV.values() for v in vs}))


def missing_env(channel: str) -> list[str]:
    """The variables this channel needs and does not have, in a stable order."""
    return [name for name in REQUIRED_ENV[channel] if not os.environ.get(name, "").strip()]


def redact(text: str | None) -> str | None:
    """Every configured secret value, blanked. Belt and braces over the rule above."""
    if not text:
        return text
    for name in SECRET_ENV:
        value = os.environ.get(name, "").strip()
        if len(value) >= 4:
            text = text.replace(value, "•••")
    return text


@dataclass(frozen=True)
class SendResult:
    """What the courier said. `ok` means it accepted the message - no more."""

    ok: bool
    provider_id: str | None = None
    #: provider_refused | timeout | unreachable
    reason: str | None = None
    #: The courier's own words, redacted.
    provider_reason: str | None = None

    @classmethod
    def accepted(cls, provider_id: str) -> "SendResult":
        return cls(ok=True, provider_id=provider_id)

    @classmethod
    def failed(cls, reason: str, provider_reason: str | None = None) -> "SendResult":
        return cls(ok=False, reason=reason, provider_reason=redact(provider_reason))


class Sender(Protocol):
    def send(self, message: Message, destination: str) -> SendResult: ...


def _is_timeout(exc: BaseException) -> bool:
    if isinstance(exc, TimeoutError):          # socket.timeout is TimeoutError
        return True
    return isinstance(getattr(exc, "reason", None), TimeoutError)


def _exception_words(exc: BaseException) -> str:
    """A failure in words that cannot carry a URL: class names and strerror."""
    inner = getattr(exc, "reason", None)
    name = type(exc).__name__
    if isinstance(inner, BaseException):
        name = f"{name}: {type(inner).__name__}"
        exc = inner
    strerror = getattr(exc, "strerror", None)
    return f"{name} ({strerror})" if strerror else name


# ---------------------------------------------------------------------------
# Twilio - WhatsApp and SMS
# ---------------------------------------------------------------------------

Transport = Callable[[str, bytes, dict[str, str], float], tuple[int, bytes]]


def _urllib_transport(url: str, data: bytes, headers: dict[str, str],
                      timeout: float) -> tuple[int, bytes]:
    request = urllib.request.Request(url, data=data, headers=headers, method="POST")
    try:
        with urllib.request.urlopen(request, timeout=timeout) as response:
            return response.status, response.read()
    except urllib.error.HTTPError as exc:      # an answer, just not a yes
        return exc.code, exc.read()


def _json(raw: bytes) -> dict[str, Any] | None:
    try:
        payload = json.loads(raw.decode("utf-8"))
    except (ValueError, UnicodeDecodeError):
        return None
    return payload if isinstance(payload, dict) else None


class TwilioSender:
    """One Twilio account, two channels: the only difference is `whatsapp:`."""

    FROM = {"whatsapp": "TWILIO_WHATSAPP_FROM", "sms": "TWILIO_SMS_FROM"}

    def __init__(self, channel: str, timeout: float = 10.0,
                 transport: Transport | None = None) -> None:
        if channel not in self.FROM:
            raise ValueError(f"Twilio carries whatsapp or sms, not {channel!r}")
        self.channel = channel
        self.timeout = timeout
        self._transport = transport or _urllib_transport

    def send(self, message: Message, destination: str) -> SendResult:
        sid = os.environ.get("TWILIO_ACCOUNT_SID", "").strip()
        token = os.environ.get("TWILIO_AUTH_TOKEN", "").strip()
        sender = os.environ.get(self.FROM[self.channel], "").strip()
        to = destination
        if self.channel == "whatsapp":
            sender = sender if sender.startswith("whatsapp:") else f"whatsapp:{sender}"
            to = f"whatsapp:{destination}"

        data = urllib.parse.urlencode(
            {"From": sender, "To": to, "Body": message.body}).encode("utf-8")
        auth = base64.b64encode(f"{sid}:{token}".encode("utf-8")).decode("ascii")
        headers = {
            "Authorization": f"Basic {auth}",
            "Content-Type": "application/x-www-form-urlencoded",
            "Accept": "application/json",
        }
        try:
            status, raw = self._transport(
                TWILIO_URL.format(sid=sid), data, headers, self.timeout)
        except Exception as exc:
            return SendResult.failed("timeout" if _is_timeout(exc) else "unreachable",
                                     _exception_words(exc))

        payload = _json(raw)
        if 200 <= status < 300:
            message_id = (payload or {}).get("sid")
            if message_id:
                return SendResult.accepted(str(message_id))
            return SendResult.failed("provider_refused",
                                     f"HTTP {status} with no message id")
        if payload and payload.get("message"):
            code = payload.get("code")
            words = str(payload["message"]) + (f" (Twilio {code})" if code else "")
            return SendResult.failed("provider_refused", words)
        return SendResult.failed("provider_refused", f"HTTP {status}")


# ---------------------------------------------------------------------------
# Gmail - email
# ---------------------------------------------------------------------------

def _gmail_ssl(host: str, port: int, timeout: float):
    return smtplib.SMTP_SSL(host, port, timeout=timeout,
                            context=ssl.create_default_context())


def _smtp_words(code: int, raw: Any) -> str:
    text = raw.decode("utf-8", errors="replace") if isinstance(raw, bytes) else str(raw)
    return f"{' '.join(text.split())} (SMTP {code})"


class GmailSender:
    """Gmail over SMTP with an App Password. Plain text, never an attachment."""

    def __init__(self, timeout: float = 10.0, smtp_factory=None) -> None:
        self.timeout = timeout
        self._smtp_factory = smtp_factory or _gmail_ssl

    def send(self, message: Message, destination: str) -> SendResult:
        user = os.environ.get("GMAIL_USER", "").strip()
        password = os.environ.get("GMAIL_APP_PASSWORD", "").strip()

        mail = EmailMessage()
        mail["From"] = user
        mail["To"] = destination
        mail["Subject"] = message.subject
        # Gmail's SMTP answer carries no id of its own; the one we set is what
        # the recipient's mailbox shows, so it is the one worth logging.
        message_id = make_msgid(domain="visionguard.local")
        mail["Message-ID"] = message_id
        mail.set_content(message.body)          # text/plain, utf-8

        try:
            with self._smtp_factory(GMAIL_HOST, GMAIL_PORT, self.timeout) as smtp:
                smtp.login(user, password)
                smtp.send_message(mail)
        except smtplib.SMTPResponseException as exc:     # includes a wrong password
            return SendResult.failed("provider_refused",
                                     _smtp_words(exc.smtp_code, exc.smtp_error))
        except smtplib.SMTPRecipientsRefused as exc:
            code, raw = next(iter(exc.recipients.values()), (0, b"recipient refused"))
            return SendResult.failed("provider_refused", _smtp_words(code, raw))
        except smtplib.SMTPException as exc:
            return SendResult.failed("provider_refused", type(exc).__name__)
        except TimeoutError:
            return SendResult.failed("timeout", "TimeoutError")
        except OSError as exc:
            return SendResult.failed("unreachable", _exception_words(exc))
        return SendResult.accepted(message_id)


def for_channel(channel: str, timeout: float = 10.0) -> Sender | None:
    """The sender for a channel, or None when its keys are not all set."""
    if missing_env(channel):
        return None
    if channel == "email":
        return GmailSender(timeout)
    return TwilioSender(channel, timeout)
