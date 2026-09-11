"""Gmail - the one courier, behind one seam.

    send(message, destination) -> SendResult: accepted(provider_id) | failed(reason)

That seam is the whole contract. Adding a courier later is a new class here;
rules, recipients and the delivery log never learn who carried a message.
There is deliberately one implementation per channel and no fallback: a
second courier that silently takes over is a second place a message can go
without anybody having decided it should. (WhatsApp and SMS through Twilio
were removed on 11 Sep 2026; email is enough.)

**No SDK.** Gmail is `smtplib`, in the standard library, so this adds nothing
to requirements.txt (research.md §1). It takes an injectable SMTP factory, so
no test ever touches the network.

**The keys never leave.** They are read from the environment at send time,
and every word a failure carries is built from the courier's own error text or
an exception's class name - never `str(exc)` - and then `redact()` is run
over it anyway.
"""

from __future__ import annotations

import os
import smtplib
import ssl
from dataclasses import dataclass
from email.message import EmailMessage
from email.utils import make_msgid
from typing import Any, Protocol

from vg.alerts.catalogue import Message

GMAIL_HOST = "smtp.gmail.com"
GMAIL_PORT = 465

#: What each channel needs in engine/.env. The names are shown to an
#: administrator when missing; the values never are.
REQUIRED_ENV: dict[str, tuple[str, ...]] = {
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
    if channel not in REQUIRED_ENV or missing_env(channel):
        return None
    return GmailSender(timeout)
