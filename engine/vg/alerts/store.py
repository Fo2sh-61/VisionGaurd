"""Recipients, rules, the delivery log, and what somebody acknowledged.

Five tables in the engine's own SQLite file, beside the scenes and the passes
they describe. This is engine state, not console state: the console asks,
the engine keeps (spec P9-FR-016), and it survives a restart.

Four decisions worth stating:

**The delivery log is the ledger.** Every attempt is one row - queued, sent
with the courier's id, failed with the courier's words, or skipped with a
reason - and an event whose key already has rows is not sent again. There is
no separate "events" table to disagree with it.

**No message body is stored.** The event and the catalogue rebuild it, and a
stored body would be one more place a name could leak.

**Nothing is deleted but old log rows.** A rule is never deleted, only
switched. A removed recipient's rows keep the name they had, so history reads
the same afterwards. The one exception is `_drop_removed_channels`: WhatsApp
and SMS were taken out on 11 Sep 2026, and their recipients and log rows went
with them, by the owner's decision.

**An acknowledgement cannot be taken back**, the same rule the gate's
dismissals follow: an acknowledgement that can be withdrawn is not one.

**A phone adds itself, switched off** (spec 020). Registering one writes its
push subscription (`push_device`) and a `push` recipient whose destination is
that device's id, with `enabled = 0`: nothing is sent to it until an
administrator switches it on in the same list as the email recipients.
Removing either removes both. A phone is never typed in by hand.
"""

from __future__ import annotations

import logging
import re
import sqlite3
import threading
import uuid
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path

from vg import db
from vg.alerts.events import CHANNELS, KINDS

log = logging.getLogger(__name__)

SCHEMA = """
CREATE TABLE IF NOT EXISTS alert_recipient (
    id           TEXT PRIMARY KEY,
    channel      TEXT NOT NULL,                 -- email | push
    destination  TEXT NOT NULL,                 -- an address, or a push_device id
    name         TEXT NOT NULL,
    language     TEXT NOT NULL DEFAULT 'en',    -- en | ar
    enabled      INTEGER NOT NULL DEFAULT 1,
    created_at   TEXT NOT NULL,
    UNIQUE (channel, destination)
);

CREATE TABLE IF NOT EXISTS alert_rule (
    kind               TEXT PRIMARY KEY,
    in_app             INTEGER,                 -- NULL: not offered (the report)
    email              INTEGER NOT NULL DEFAULT 0,
    push               INTEGER NOT NULL DEFAULT 0,
    vehicle_blacklist  INTEGER,                 -- NULL except on `vehicles`
    vehicle_unknown    INTEGER,
    vehicle_expired    INTEGER
);

CREATE TABLE IF NOT EXISTS alert_delivery (
    id               TEXT PRIMARY KEY,
    event_key        TEXT NOT NULL,
    kind             TEXT NOT NULL,             -- an alert kind, or `test`
    channel          TEXT,                      -- NULL only on a queue_full row
    recipient_id     TEXT,
    recipient_name   TEXT,                      -- copied, so removal keeps history
    language         TEXT,
    outcome          TEXT NOT NULL,             -- queued | sent | failed | skipped
    reason           TEXT,
    provider_reason  TEXT,                      -- the courier's words, redacted
    provider_id      TEXT,
    attempts         INTEGER NOT NULL DEFAULT 0,
    queued_at        TEXT NOT NULL,
    finished_at      TEXT
);
CREATE INDEX IF NOT EXISTS alert_delivery_event ON alert_delivery (event_key);
CREATE INDEX IF NOT EXISTS alert_delivery_queued ON alert_delivery (queued_at);

CREATE TABLE IF NOT EXISTS attention_ack (
    item_id  TEXT PRIMARY KEY,
    by_who   TEXT NOT NULL,
    at       TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS push_device (
    id            TEXT PRIMARY KEY,
    user_id       TEXT NOT NULL,             -- the account that registered it
    label         TEXT NOT NULL,
    endpoint      TEXT NOT NULL UNIQUE,      -- on a browser push service only
    p256dh        TEXT NOT NULL,             -- the phone's keys: what the
    auth          TEXT NOT NULL,             --   message is encrypted for
    created_at    TEXT NOT NULL,
    last_sent_at  TEXT,
    last_error    TEXT
);
CREATE INDEX IF NOT EXISTS push_device_user ON push_device (user_id);
"""

#: kind, in_app, email, push, blacklist, unknown, expired.
#: Email and push off and nobody listed: a fresh install sends nothing until an
#: administrator decides it should (P9-FR-015, spec 020 P9-FR-105).
DEFAULT_RULES = (
    ("weapon", 1, 0, 0, None, None, None),
    ("intrusion", 1, 0, 0, None, None, None),
    ("vehicles", 1, 0, 0, 1, 1, 1),
    ("camera", 1, 0, 0, None, None, None),
    ("attendance", None, 0, 0, None, None, None),
)

RULE_FLAGS = ("in_app", "email", "push",
              "vehicle_blacklist", "vehicle_unknown", "vehicle_expired")

#: Channels this store once had and no longer carries (removed 11 Sep 2026).
REMOVED_CHANNELS = ("whatsapp", "sms")

LANGUAGES = ("en", "ar")
NAME_MAX = 80
#: A phone's own name for itself, as its owner sees it in the list.
LABEL_MAX = 40

_EMAIL = re.compile(r"^[^@\s]+@[^@\s]+\.[^@\s]+$")
_DEVICE_ID = re.compile(r"^[0-9a-f]{32}$")


class DuplicateRecipient(ValueError):
    """That destination is already listed on that channel."""


def mask_destination(destination: str) -> str:
    """Enough of an address to tell two apart in the audit, no more."""
    text = str(destination or "")
    return "…" + text[-4:] if len(text) > 4 else "…"


def normalise_destination(channel: str, raw: str) -> str:
    """A lower-cased address. Else refused."""
    text = str(raw or "").strip()
    if channel == "email":
        text = text.lower()
        if not _EMAIL.match(text):
            raise ValueError("destination")
        return text
    if channel == "push":
        if not _DEVICE_ID.match(text):
            raise ValueError("destination")
        return text
    raise ValueError("channel")


@dataclass(frozen=True)
class Rule:
    kind: str
    in_app: bool | None
    email: bool
    push: bool = False
    vehicle_blacklist: bool | None = None
    vehicle_unknown: bool | None = None
    vehicle_expired: bool | None = None

    def channel_on(self, channel: str) -> bool:
        return bool(getattr(self, channel))

    def reason_on(self, reason: str | None) -> bool:
        """For the gate rule: does this reason count as an alert at all?"""
        return bool(getattr(self, f"vehicle_{reason}", None)) if reason else False


@dataclass(frozen=True)
class Recipient:
    id: str
    channel: str
    destination: str
    name: str
    language: str
    enabled: bool
    created_at: datetime


@dataclass(frozen=True)
class PushDevice:
    """One phone's push subscription. `enabled` is its recipient's switch."""

    id: str
    user_id: str
    label: str
    endpoint: str
    p256dh: str
    auth: str
    created_at: datetime
    enabled: bool = False
    recipient_id: str | None = None
    last_sent_at: datetime | None = None
    last_error: str | None = None


@dataclass(frozen=True)
class Delivery:
    id: str
    event_key: str
    kind: str
    channel: str | None
    recipient_id: str | None
    recipient_name: str | None
    language: str | None
    outcome: str
    reason: str | None
    provider_reason: str | None
    provider_id: str | None
    attempts: int
    queued_at: datetime
    finished_at: datetime | None

    @property
    def at(self) -> datetime:
        return self.finished_at or self.queued_at


def _iso(when: datetime) -> str:
    if when.tzinfo is None:
        when = when.replace(tzinfo=timezone.utc)
    return when.astimezone(timezone.utc).isoformat()


def _parse(text: str | None) -> datetime | None:
    if not text:
        return None
    when = datetime.fromisoformat(text)
    return when if when.tzinfo else when.replace(tzinfo=timezone.utc)


def _flag(value) -> bool | None:
    return None if value is None else bool(value)


def _now() -> datetime:
    return datetime.now(timezone.utc)


class AlertStore:
    """The four tables. One connection, one lock, like every store here."""

    def __init__(self, database: Path | str) -> None:
        self.path = Path(database)
        self._lock = threading.RLock()
        self._conn = db.connect(self.path)
        self._conn.executescript(SCHEMA)
        self._drop_removed_channels()
        self._add_push_column()
        # On every open, and never an overwrite: seeding must not undo an edit.
        self._conn.executemany(
            "INSERT OR IGNORE INTO alert_rule (kind, in_app, email, push,"
            " vehicle_blacklist, vehicle_unknown, vehicle_expired)"
            " VALUES (?, ?, ?, ?, ?, ?, ?)", DEFAULT_RULES)
        self._conn.commit()

    def _add_push_column(self) -> None:
        """A database from before spec 020 gains the push switch, off for every kind.

        `CREATE TABLE IF NOT EXISTS` leaves an existing table as it was; the
        same ask-then-add step as `auth/store.py`. Every other column and row
        is kept.
        """
        columns = {r["name"] for r in self._conn.execute("PRAGMA table_info(alert_rule)")}
        if "push" not in columns:
            with self._conn:
                self._conn.execute(
                    "ALTER TABLE alert_rule ADD COLUMN push INTEGER NOT NULL DEFAULT 0")
            log.info("alerts: phone notifications added to the rules, off for every kind")

    def _drop_removed_channels(self) -> None:
        """A database from before 11 Sep 2026 loses WhatsApp and SMS for good.

        Their rule switches, their recipients and their log rows, in one
        transaction. Nothing is left behind that the console could no longer
        name. Does nothing on a database that never had them.
        """
        columns = {r["name"] for r in self._conn.execute("PRAGMA table_info(alert_rule)")}
        stale = [c for c in REMOVED_CHANNELS if c in columns]
        marks = ", ".join("?" for _ in REMOVED_CHANNELS)
        with self._conn:
            for column in stale:
                self._conn.execute(f"ALTER TABLE alert_rule DROP COLUMN {column}")
            people = self._conn.execute(
                f"DELETE FROM alert_recipient WHERE channel IN ({marks})",
                REMOVED_CHANNELS).rowcount
            rows = self._conn.execute(
                f"DELETE FROM alert_delivery WHERE channel IN ({marks})",
                REMOVED_CHANNELS).rowcount
        if stale or people or rows:
            log.info("alerts: WhatsApp and SMS removed - %d recipient(s) and %d "
                     "log row(s) deleted", people, rows)

    def close_db(self) -> None:
        with self._lock:
            self._conn.close()

    # -- rules ---------------------------------------------------------------

    def rules(self) -> dict[str, Rule]:
        with self._lock:
            rows = self._conn.execute("SELECT * FROM alert_rule").fetchall()
        found = {
            r["kind"]: Rule(
                kind=r["kind"], in_app=_flag(r["in_app"]), email=bool(r["email"]),
                push=bool(r["push"]),
                vehicle_blacklist=_flag(r["vehicle_blacklist"]),
                vehicle_unknown=_flag(r["vehicle_unknown"]),
                vehicle_expired=_flag(r["vehicle_expired"]),
            )
            for r in rows
        }
        return {kind: found[kind] for kind in KINDS if kind in found}

    def update_rule(self, kind: str, **flags: bool | None) -> Rule:
        """Switch some of one rule's flags. `None` leaves a flag as it is.

        KeyError: no such kind. ValueError: a flag this kind does not offer -
        In-app on the report, or a gate switch anywhere but the gate rule.
        """
        if kind not in KINDS:
            raise KeyError(kind)
        stray = sorted(set(flags) - set(RULE_FLAGS))
        if stray:
            raise ValueError(f"unknown flag(s) {stray}")
        current = self.rules()[kind]
        changes: dict[str, int] = {}
        for name, value in flags.items():
            if value is None:
                continue
            if name == "in_app" and current.in_app is None:
                raise ValueError(f"in_app is not offered for {kind}")
            if name.startswith("vehicle_") and kind != "vehicles":
                raise ValueError(f"{name} belongs to the vehicles rule only")
            changes[name] = int(bool(value))
        if changes:
            assignments = ", ".join(f"{name} = ?" for name in changes)
            with self._lock:
                self._conn.execute(
                    f"UPDATE alert_rule SET {assignments} WHERE kind = ?",
                    (*changes.values(), kind))
                self._conn.commit()
        return self.rules()[kind]

    # -- recipients ----------------------------------------------------------

    @staticmethod
    def _recipient(r) -> Recipient:
        return Recipient(
            id=r["id"], channel=r["channel"], destination=r["destination"],
            name=r["name"], language=r["language"], enabled=bool(r["enabled"]),
            created_at=_parse(r["created_at"]),
        )

    def recipients(self) -> list[Recipient]:
        with self._lock:
            rows = self._conn.execute(
                "SELECT * FROM alert_recipient"
                " ORDER BY channel, name COLLATE NOCASE, created_at").fetchall()
        return [self._recipient(r) for r in rows]

    def recipient(self, recipient_id: str) -> Recipient | None:
        with self._lock:
            row = self._conn.execute(
                "SELECT * FROM alert_recipient WHERE id = ?", (recipient_id,)).fetchone()
        return self._recipient(row) if row else None

    @staticmethod
    def _clean_name(name: str) -> str:
        text = " ".join(str(name or "").split())
        if not text or len(text) > NAME_MAX:
            raise ValueError("name")
        return text

    def add_recipient(self, channel: str, destination: str, name: str,
                      language: str = "en", enabled: bool = True,
                      at: datetime | None = None) -> Recipient:
        if channel not in CHANNELS:
            raise ValueError("channel")
        if channel == "push":
            # A phone registers itself from the phone app (`register_push_device`).
            raise ValueError("a phone adds itself from the phone app")
        if language not in LANGUAGES:
            raise ValueError("language")
        clean = normalise_destination(channel, destination)
        label = self._clean_name(name)
        recipient_id = uuid.uuid4().hex
        try:
            with self._lock:
                self._conn.execute(
                    "INSERT INTO alert_recipient (id, channel, destination, name,"
                    " language, enabled, created_at) VALUES (?, ?, ?, ?, ?, ?, ?)",
                    (recipient_id, channel, clean, label, language, int(bool(enabled)),
                     _iso(at or _now())))
                self._conn.commit()
        except sqlite3.IntegrityError:
            raise DuplicateRecipient(f"{clean} is already listed for {channel}") from None
        return self.recipient(recipient_id)

    def update_recipient(self, recipient_id: str, *, destination: str | None = None,
                         name: str | None = None, language: str | None = None,
                         enabled: bool | None = None) -> Recipient:
        current = self.recipient(recipient_id)
        if current is None:
            raise KeyError(recipient_id)
        changes: dict[str, object] = {}
        if destination is not None:
            changes["destination"] = normalise_destination(current.channel, destination)
        if name is not None:
            changes["name"] = self._clean_name(name)
        if language is not None:
            if language not in LANGUAGES:
                raise ValueError("language")
            changes["language"] = language
        if enabled is not None:
            changes["enabled"] = int(bool(enabled))
        if changes:
            assignments = ", ".join(f"{column} = ?" for column in changes)
            try:
                with self._lock:
                    self._conn.execute(
                        f"UPDATE alert_recipient SET {assignments} WHERE id = ?",
                        (*changes.values(), recipient_id))
                    self._conn.commit()
            except sqlite3.IntegrityError:
                raise DuplicateRecipient(
                    f"{changes.get('destination')} is already listed for "
                    f"{current.channel}") from None
        return self.recipient(recipient_id)

    def remove_recipient(self, recipient_id: str) -> bool:
        """Remove one recipient; a phone's subscription goes with it."""
        with self._lock:
            row = self._conn.execute(
                "SELECT channel, destination FROM alert_recipient WHERE id = ?",
                (recipient_id,)).fetchone()
            with self._conn:
                cursor = self._conn.execute(
                    "DELETE FROM alert_recipient WHERE id = ?", (recipient_id,))
                if row is not None and row["channel"] == "push":
                    self._conn.execute("DELETE FROM push_device WHERE id = ?",
                                       (row["destination"],))
        return cursor.rowcount == 1

    # -- phones (spec 020) ---------------------------------------------------

    def _device(self, r) -> PushDevice:
        return PushDevice(
            id=r["id"], user_id=r["user_id"], label=r["label"], endpoint=r["endpoint"],
            p256dh=r["p256dh"], auth=r["auth"], created_at=_parse(r["created_at"]),
            enabled=bool(r["enabled"]) if r["enabled"] is not None else False,
            recipient_id=r["recipient_id"], last_sent_at=_parse(r["last_sent_at"]),
            last_error=r["last_error"],
        )

    _DEVICES = ("SELECT d.*, r.id AS recipient_id, r.enabled AS enabled FROM push_device d"
                " LEFT JOIN alert_recipient r ON r.channel = 'push' AND r.destination = d.id")

    def register_push_device(self, *, user_id: str, user_name: str, label: str,
                             endpoint: str, p256dh: str, auth: str,
                             at: datetime | None = None) -> tuple[PushDevice, Recipient]:
        """Add a phone, switched off; or update the one with this subscription.

        The same browser subscribing again (new keys after a reinstall) is the
        same phone, not a second one. A phone that comes back under another
        account is switched off again: a new person is a new decision.
        """
        clean_label = " ".join(str(label or "").split())[:LABEL_MAX] or "Phone"
        name = self._clean_name(f"{' '.join(str(user_name or '').split())[:NAME_MAX - LABEL_MAX - 3]}"
                                f" · {clean_label}")
        now = _iso(at or _now())
        with self._lock:
            with self._conn:
                old = self._conn.execute(
                    "SELECT id, user_id FROM push_device WHERE endpoint = ?",
                    (endpoint,)).fetchone()
                if old is None:
                    device_id = uuid.uuid4().hex
                    self._conn.execute(
                        "INSERT INTO push_device (id, user_id, label, endpoint, p256dh,"
                        " auth, created_at) VALUES (?, ?, ?, ?, ?, ?, ?)",
                        (device_id, user_id, clean_label, endpoint, p256dh, auth, now))
                    self._conn.execute(
                        "INSERT INTO alert_recipient (id, channel, destination, name,"
                        " language, enabled, created_at) VALUES (?, 'push', ?, ?, 'en', 0, ?)",
                        (uuid.uuid4().hex, device_id, name, now))
                else:
                    device_id = old["id"]
                    self._conn.execute(
                        "UPDATE push_device SET user_id = ?, label = ?, p256dh = ?, auth = ?"
                        " WHERE id = ?", (user_id, clean_label, p256dh, auth, device_id))
                    switched_off = ", enabled = 0" if old["user_id"] != user_id else ""
                    self._conn.execute(
                        f"UPDATE alert_recipient SET name = ?{switched_off}"
                        " WHERE channel = 'push' AND destination = ?", (name, device_id))
        device = self.push_device(device_id)
        return device, self.recipient(device.recipient_id)

    def push_device(self, device_id: str) -> PushDevice | None:
        with self._lock:
            row = self._conn.execute(f"{self._DEVICES} WHERE d.id = ?",
                                     (device_id,)).fetchone()
        return self._device(row) if row else None

    def push_devices(self, user_id: str | None = None) -> list[PushDevice]:
        query, args = self._DEVICES, ()
        if user_id is not None:
            query, args = f"{query} WHERE d.user_id = ?", (user_id,)
        with self._lock:
            rows = self._conn.execute(f"{query} ORDER BY d.created_at", args).fetchall()
        return [self._device(r) for r in rows]

    def remove_push_device(self, device_id: str) -> bool:
        """Remove one phone and its recipient. False when it was not there."""
        with self._lock:
            with self._conn:
                cursor = self._conn.execute("DELETE FROM push_device WHERE id = ?",
                                            (device_id,))
                self._conn.execute(
                    "DELETE FROM alert_recipient WHERE channel = 'push' AND destination = ?",
                    (device_id,))
        return cursor.rowcount == 1

    def remove_devices_of(self, user_id: str) -> int:
        """Every phone of one account: it was disabled or deleted."""
        removed = 0
        for device in self.push_devices(user_id):
            removed += int(self.remove_push_device(device.id))
        return removed

    def note_push(self, device_id: str, *, sent_at: datetime | None = None,
                  error: str | None = None) -> None:
        """When this phone was last reached, or why not."""
        with self._lock:
            if sent_at is not None:
                self._conn.execute(
                    "UPDATE push_device SET last_sent_at = ?, last_error = NULL WHERE id = ?",
                    (_iso(sent_at), device_id))
            else:
                self._conn.execute("UPDATE push_device SET last_error = ? WHERE id = ?",
                                   (error, device_id))
            self._conn.commit()

    # -- the delivery log ----------------------------------------------------

    @staticmethod
    def _delivery(r) -> Delivery:
        return Delivery(
            id=r["id"], event_key=r["event_key"], kind=r["kind"], channel=r["channel"],
            recipient_id=r["recipient_id"], recipient_name=r["recipient_name"],
            language=r["language"], outcome=r["outcome"], reason=r["reason"],
            provider_reason=r["provider_reason"], provider_id=r["provider_id"],
            attempts=int(r["attempts"]), queued_at=_parse(r["queued_at"]),
            finished_at=_parse(r["finished_at"]),
        )

    def has_rows(self, event_key: str) -> bool:
        with self._lock:
            return self._conn.execute(
                "SELECT 1 FROM alert_delivery WHERE event_key = ? LIMIT 1",
                (event_key,)).fetchone() is not None

    def add_row(self, event_key: str, kind: str, outcome: str, *, at: datetime,
                channel: str | None = None, recipient: Recipient | None = None,
                language: str | None = None, reason: str | None = None,
                provider_reason: str | None = None, attempts: int = 0) -> str:
        (row_id,) = self.add_rows(event_key, kind, [dict(
            outcome=outcome, channel=channel, recipient=recipient, language=language,
            reason=reason, provider_reason=provider_reason, attempts=attempts)], at=at)
        return row_id

    def add_rows(self, event_key: str, kind: str, rows: list[dict], *,
                 at: datetime) -> list[str]:
        """One event's rows, written together or not at all.

        An event whose key has any row is never recorded again, so half an
        event's rows would silence the other half for good. Each row is
        `add_row`'s keywords: `outcome`, and any of `channel`, `recipient`,
        `language`, `reason`, `provider_reason`, `attempts`.
        """
        ids: list[str] = []
        with self._lock:
            try:
                for row in rows:
                    ids.append(self._insert(event_key, kind, at, **row))
                self._conn.commit()
            except BaseException:
                self._conn.rollback()
                raise
        return ids

    def _insert(self, event_key: str, kind: str, at: datetime, *, outcome: str,
                channel: str | None = None, recipient: Recipient | None = None,
                language: str | None = None, reason: str | None = None,
                provider_reason: str | None = None, attempts: int = 0) -> str:
        row_id = uuid.uuid4().hex
        self._conn.execute(
            "INSERT INTO alert_delivery (id, event_key, kind, channel,"
            " recipient_id, recipient_name, language, outcome, reason,"
            " provider_reason, attempts, queued_at, finished_at)"
            " VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)",
            (row_id, event_key, kind, channel,
             recipient.id if recipient else None,
             recipient.name if recipient else None,
             language, outcome, reason, provider_reason, attempts, _iso(at),
             None if outcome == "queued" else _iso(at)))
        return row_id

    def finish(self, row_id: str, outcome: str, *, at: datetime,
               reason: str | None = None, provider_reason: str | None = None,
               provider_id: str | None = None, attempts: int = 0) -> None:
        with self._lock:
            self._conn.execute(
                "UPDATE alert_delivery SET outcome = ?, reason = ?, provider_reason = ?,"
                " provider_id = ?, attempts = ?, finished_at = ? WHERE id = ?",
                (outcome, reason, provider_reason, provider_id, attempts, _iso(at),
                 row_id))
            self._conn.commit()

    def mark_sent(self, row_id: str, provider_id: str, attempts: int,
                  at: datetime) -> None:
        self.finish(row_id, "sent", at=at, provider_id=provider_id, attempts=attempts)

    def mark_failed(self, row_id: str, reason: str, provider_reason: str | None,
                    attempts: int, at: datetime) -> None:
        self.finish(row_id, "failed", at=at, reason=reason,
                    provider_reason=provider_reason, attempts=attempts)

    def fail_unfinished(self, reason: str, at: datetime, keep: str | None = None) -> int:
        """Rows still `queued` - left by an engine that stopped - become failed.

        `keep` is a row a courier is still carrying: its outcome is the
        courier's answer, not a guess made while the courier is still talking.
        """
        with self._lock:
            cursor = self._conn.execute(
                "UPDATE alert_delivery SET outcome = 'failed', reason = ?,"
                " finished_at = ? WHERE outcome = 'queued' AND id IS NOT ?",
                (reason, _iso(at), keep))
            self._conn.commit()
        return cursor.rowcount

    def row(self, row_id: str) -> Delivery | None:
        with self._lock:
            found = self._conn.execute(
                "SELECT * FROM alert_delivery WHERE id = ?", (row_id,)).fetchone()
        return self._delivery(found) if found else None

    def recent(self, limit: int) -> list[Delivery]:
        with self._lock:
            rows = self._conn.execute(
                "SELECT * FROM alert_delivery ORDER BY queued_at DESC, rowid DESC"
                " LIMIT ?", (int(limit),)).fetchall()
        return [self._delivery(r) for r in rows]

    def counts_since(self, since: datetime) -> dict[str, int]:
        with self._lock:
            rows = self._conn.execute(
                "SELECT outcome, COUNT(*) AS n FROM alert_delivery"
                " WHERE queued_at >= ? GROUP BY outcome", (_iso(since),)).fetchall()
        return {r["outcome"]: int(r["n"]) for r in rows}

    def recipients_of(self, event_key: str) -> set[tuple[str, str]]:
        """Who an event actually went to: (channel, recipient id), skips excluded."""
        with self._lock:
            rows = self._conn.execute(
                "SELECT channel, recipient_id FROM alert_delivery WHERE event_key = ?"
                " AND outcome != 'skipped' AND recipient_id IS NOT NULL",
                (event_key,)).fetchall()
        return {(r["channel"], r["recipient_id"]) for r in rows}

    def last_camera_events(self) -> dict[str, str]:
        """The newest word on each camera: `down` or `up`."""
        with self._lock:
            rows = self._conn.execute(
                "SELECT event_key FROM alert_delivery WHERE event_key LIKE 'camera:%'"
                " ORDER BY queued_at, rowid").fetchall()
        last: dict[str, str] = {}
        for r in rows:
            try:
                camera_id, state, _ = r["event_key"][len("camera:"):].rsplit(":", 2)
            except ValueError:
                continue
            if state in ("down", "up"):
                last[camera_id] = state
        return last

    def delete_older_than(self, when: datetime) -> int:
        with self._lock:
            cursor = self._conn.execute(
                "DELETE FROM alert_delivery WHERE queued_at < ? AND outcome != 'queued'",
                (_iso(when),))
            self._conn.commit()
        return cursor.rowcount

    # -- acknowledgements ----------------------------------------------------

    def ack(self, item_id: str, by_who: str, at: datetime) -> bool:
        """Record that somebody dealt with a Home item. False if already done."""
        with self._lock:
            cursor = self._conn.execute(
                "INSERT OR IGNORE INTO attention_ack (item_id, by_who, at)"
                " VALUES (?, ?, ?)", (item_id, by_who, _iso(at)))
            self._conn.commit()
        return cursor.rowcount == 1

    def acked(self) -> set[str]:
        with self._lock:
            rows = self._conn.execute("SELECT item_id FROM attention_ack").fetchall()
        return {r["item_id"] for r in rows}
