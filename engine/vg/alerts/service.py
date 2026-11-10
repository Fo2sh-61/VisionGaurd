"""The one sender thread: from the hand-off queue to a courier, a row per attempt.

A camera thread that commits an event does one `put_nowait` and goes back to
its frames. Everything after that happens here, on one daemon thread, so a
courier that is slow or down costs detection, recording and the console
nothing (constitution II, spec P9-FR-029).

**Rows before couriers.** The launcher stops the engine by killing its job
object, and no `finally` runs when it does. So a message that exists only in
memory at that moment would vanish without a trace. Each pass therefore
records everything waiting on the queue - one row per recipient, written
before any courier is called - and only then makes at most one courier call.
On the next start, any row still `queued` is marked `failed: engine_stopped`
rather than sent late. What can still be lost is an event that arrived during
the one courier call in flight, at most `timeout_seconds` of them.

**The log is the ledger.** An event whose key already has rows is not sent
again; that, plus the startup sweep, is what makes a restart harmless. So an
event's rows are written together or not at all - half an event recorded
would silence the other half for good - and an event that could not be
written is tried again on the next passes.

**A switched-off channel is not an attempt** and writes nothing. A channel
that is on but cannot be used writes one `skipped` row saying why: no keys,
nobody listed, a recipient switched off.

One pass (`step`) is also the unit the tests drive, so they need no thread and
no sleeps: the clock is injected, and a retry "five seconds later" is a test
moving that clock five seconds.
"""

from __future__ import annotations

import logging
import queue
import threading
from dataclasses import dataclass, replace
from datetime import datetime, timedelta, timezone
from typing import Any, Callable

from vg.alerts import catalogue, events, providers
from vg.alerts.events import CHANNELS, AlertEvent
from vg.alerts.store import AlertStore, Recipient

log = logging.getLogger(__name__)

#: How long a failed attempt waits before the next one.
RETRY_PAUSE = timedelta(seconds=5)
#: The longest a pass waits for work: how often cameras and the clock are read.
TICK_SECONDS = 15.0
#: The noon report goes out in this window or not at all - never late.
REPORT_WINDOW = timedelta(minutes=10)
#: How many passes try an event whose rows could not be written.
RECORD_TRIES = 3
#: How much longer than one courier call a stop waits for the sender.
STOP_MARGIN = 5.0

_WAKE = object()


@dataclass
class _Pending:
    """One queued row the sender still owes an attempt."""

    row_id: str
    event: AlertEvent
    recipient: Recipient
    channel: str
    language: str
    due: datetime
    attempts: int = 0


class AlertService:
    def __init__(self, config, store: AlertStore, registry=None, clock=None, *,
                 hours=None, senders: Callable[[str], Any] | None = None,
                 now: Callable[[], datetime] | None = None) -> None:
        from vg.clock import clock_for

        self.config = config
        self.store = store
        self.registry = registry
        self.clock = clock or clock_for(0)
        #: Returns the `HoursConfig` in force now, for the term dates and the
        #: working days the noon report needs. A callable, not a value, so a
        #: save in Settings reaches the next tick without a restart.
        self.hours = hours
        self._senders = senders or (
            lambda channel: providers.for_channel(channel, config.timeout_seconds))
        self._now = now or (lambda: datetime.now(timezone.utc))
        self._queue: queue.Queue = queue.Queue(maxsize=config.queue_size)
        self._lock = threading.RLock()
        self._pending: list[_Pending] = []
        #: The row a courier is carrying right now, if any.
        self._in_flight: _Pending | None = None
        #: Events whose rows could not be written yet, with the tries so far.
        self._held: list[tuple[AlertEvent, int]] = []
        self._stop = threading.Event()
        self._thread: threading.Thread | None = None
        self._announced_down: set[str] = set()
        self._report_day: str | None = None
        self._retention_day: str | None = None
        self.started_at: datetime = self._now()
        self._camera_name: Callable[[str], str | None] = lambda camera_id: None
        self._attendance_counts: Callable[[str], Any] | None = None
        self._zone_channels: Callable[[str], frozenset[str] | None] | None = None

    # -- lifecycle -----------------------------------------------------------

    def bind(self, *, camera_name: Callable[[str], str | None] | None = None,
             attendance_counts: Callable[[str], Any] | None = None,
             hours: Callable[[], Any] | None = None,
             zone_channels: Callable[[str], frozenset[str] | None] | None = None,
             ) -> None:
        """What the sender needs from the rest of the engine, once it exists.

        `zone_channels(area_id)` says which courier channels one zone or
        station asked for, or None when it asked for nothing in particular.
        """
        if zone_channels is not None:
            self._zone_channels = zone_channels
        if hours is not None:
            self.hours = hours
        if camera_name is not None:
            self._camera_name = camera_name
        if attendance_counts is not None:
            self._attendance_counts = attendance_counts

    def start(self, run_thread: bool = True) -> None:
        now = self._now()
        self.started_at = now
        self._stop.clear()
        left = self.store.fail_unfinished("engine_stopped", now)
        if left:
            log.warning("alerts: %d message(s) the last run never sent are logged "
                        "as failed, not sent late", left)
        self._announced_down = {
            camera_id for camera_id, state in self.store.last_camera_events().items()
            if state == "down"}
        if run_thread:
            self._thread = threading.Thread(
                target=self._run, name="alert-sender", daemon=True)
            self._thread.start()
            log.info("alert sender started")

    def stop(self, timeout: float | None = None) -> bool:
        """Stop the thread, and log whatever was still waiting as not sent.

        It waits as long as one courier call may take, so a message a courier
        is carrying ends with the courier's own answer. A courier that outlasts
        even that leaves its row queued - it may still accept the message - and
        the next start logs the row as failed if no answer was ever written.

        True once the thread has finished. False means it is still running,
        so the caller must not close the store under it: that would throw away
        the courier's answer when it comes.
        """
        self._stop.set()
        self._wake()
        thread, self._thread = self._thread, None
        if thread is not None:
            thread.join(self.config.timeout_seconds + STOP_MARGIN
                        if timeout is None else timeout)
        finished = thread is None or not thread.is_alive()
        now = self._now()
        # Whatever never reached a row still gets one: stopping is not a reason
        # for a message to vanish from the log.
        while True:
            try:
                item = self._queue.get_nowait()
            except queue.Empty:
                break
            if isinstance(item, AlertEvent):
                self._log_lost(item, "engine_stopped", now)
        with self._lock:
            held, self._held = self._held, []
            self._pending.clear()
            carrying = self._in_flight
        for event, _ in held:
            self._log_lost(event, "engine_stopped", now)
        if carrying is not None:
            log.warning("alerts: a courier was still carrying %s at stop; its row "
                        "waits for the courier's answer", carrying.event.event_key)
        try:
            self.store.fail_unfinished("engine_stopped", now,
                                       keep=carrying.row_id if carrying else None)
        except Exception:
            log.exception("alerts: could not mark unsent messages at stop")
        return finished

    @property
    def running(self) -> bool:
        return self._thread is not None and self._thread.is_alive()

    @property
    def dead(self) -> bool:
        """Started, and its thread has since died. Not the same as never started."""
        return self._thread is not None and not self._thread.is_alive()

    def _run(self) -> None:
        while not self._stop.is_set():
            try:
                self.step(self._wait_seconds())
            except Exception:
                log.exception("alert sender: a pass failed; carrying on")
                self._stop.wait(1.0)

    # -- the hand-off --------------------------------------------------------

    def enqueue(self, event: AlertEvent) -> None:
        """Called on whatever thread saw the event. Never blocks.

        A full queue drops its OLDEST event, not this one - the knife that just
        opened matters more than a camera that went dark an hour ago - and the
        drop is written to the log. This is the only store write a camera
        thread ever makes here, and only once a courier has been stuck a long
        while.
        """
        try:
            self._queue.put_nowait(event)
            return
        except queue.Full:
            pass
        try:
            oldest = self._queue.get_nowait()
        except queue.Empty:
            oldest = None
        if isinstance(oldest, AlertEvent):
            self._log_lost(oldest, "queue_full", self._now())
        try:
            self._queue.put_nowait(event)
        except queue.Full:
            self._log_lost(event, "queue_full", self._now())

    # -- the store hooks ---------------------------------------------------------
    #
    # Each runs on the thread that committed the event - a camera thread - so
    # each does nothing but build the event and hand it over.

    def on_weapon_open(self, scene_id: str, camera_id: str, started_at: datetime,
                       confidence: float, continues: bool = False) -> None:
        """`WeaponSceneStore.on_open`. A two-minute continuation is not news."""
        if continues:
            return
        self.enqueue(events.weapon_opened(scene_id, camera_id, started_at, confidence))

    def on_zone_open(self, scene_id: str, camera_id: str, started_at: datetime,
                     continues: bool = False, zone_id: str | None = None) -> None:
        """`SceneStore.on_open`. A long visit is one message, not one a scene.

        The zone's own Notify choice, when it has one, decides the channels;
        Settings' row is only what a new zone starts with.
        """
        if continues:
            return
        channels = None
        if zone_id and self._zone_channels is not None:
            try:
                channels = self._zone_channels(zone_id)
            except Exception:
                log.exception("alerts: could not read zone %s's notify choice",
                              zone_id)
        self.enqueue(events.intrusion_opened(
            scene_id, camera_id, started_at, channels=channels))

    def on_station_absent(self, station_id: str, camera_id: str, at: datetime,
                          away_since: datetime, station: str,
                          limit_minutes: int, assignee: str | None = None,
                          channels: frozenset[str] | None = None) -> None:
        """`StationStore.on_alert`. One message per absence."""
        self.enqueue(events.station_absent(
            station_id, camera_id, at, away_since, station, limit_minutes,
            assignee, channels))

    def on_pass(self, record) -> None:
        """`VehicleStore.on_pass`, once the reader is done with the pass."""
        event = self._gate_event(record)
        if event is not None:
            self.enqueue(event)

    def not_sent(self, records, reason: str) -> None:
        """Gate passes the last run recorded but never finished: it stopped
        while the car was still in view (`VehicleStore.close_unfinished`).

        Each is logged as failed for exactly the people who would have had it,
        and nothing goes out: a gate message gives a time and no date, so one
        sent after a restart would read as today. The start-up sweep treats a
        message already queued the same way. Called before the thread starts.
        """
        for record in records:
            event = self._gate_event(record)
            if event is None:
                continue
            try:
                self._record(event, give_up=reason)
            except Exception:
                log.exception("alerts: could not log %s as not sent", event.event_key)

    @staticmethod
    def _gate_event(record) -> AlertEvent | None:
        """Only these facts are read - never the owner."""
        if record.status not in events.GATE_REASONS:
            return None
        return events.gate_alert(
            record.id, record.camera_id, record.at, record.plate_display,
            record.gate, record.status, record.confidence, record.needs_review)

    def verdict(self, scene_id: str, camera_id: str, verdict: str, reviewer: str,
                at: datetime, since: datetime | None = None) -> None:
        """A person decided. Called from `review_weapon`, on a request thread.

        It goes to exactly the recipients the opening went to - the people who
        got the scare get the answer - and nowhere if the opening went nowhere.
        """
        self.enqueue(events.weapon_verdict(scene_id, camera_id, at, verdict, reviewer,
                                           since))

    def test_send(self, recipient_id: str) -> str:
        """Record a test message for one recipient, now. Returns its row id.

        KeyError when there is no such recipient. Runs on the request thread;
        the courier call itself is still the sender thread's.
        """
        rows = self._record(events.test_message(recipient_id, self._now()))
        self._wake()
        return rows[0]

    def _wake(self) -> None:
        try:
            self._queue.put_nowait(_WAKE)
        except queue.Full:
            pass

    def _log_lost(self, event: AlertEvent, reason: str, at: datetime) -> None:
        log.warning("alerts: %s was not sent (%s)", event.event_key, reason)
        try:
            self.store.add_row(event.event_key, event.kind, "failed", at=at, reason=reason)
        except Exception:
            log.exception("alerts: could not log a dropped message")

    # -- one pass --------------------------------------------------------------

    def step(self, timeout: float = 0.0) -> None:
        """Record everything waiting, make at most one courier call, then tick.

        Once a stop is asked, a pass only records: it starts no courier call
        and reads no camera, so a stop waits on one call at most.
        """
        item = self._take(timeout)
        with self._lock:
            held, self._held = self._held, []
        for event, tries in held:
            self._try_record(event, tries)
        while item is not None:
            if isinstance(item, AlertEvent):
                self._try_record(item, 0)
            item = self._take(0)
        if self._stop.is_set():
            return
        self._send_one_due()
        if self._stop.is_set():
            return
        now = self._now()
        self._tick_cameras(now)
        self._tick_report(now)
        self._tick_retention(now)

    def _try_record(self, event: AlertEvent, tries: int) -> None:
        """Record one event; one whose rows could not be written waits a pass.

        Nothing of it was written (`_record` writes an event whole or not at
        all), so the ledger will not take the next try for a repeat.
        """
        try:
            self._record(event)
        except Exception:
            tries += 1
            if tries >= RECORD_TRIES:
                log.exception("alerts: could not record %s; given up after %d tries",
                              event.event_key, tries)
                return
            log.warning("alerts: could not record %s; trying again next pass",
                        event.event_key, exc_info=True)
            with self._lock:
                self._held.append((event, tries))

    def _take(self, timeout: float):
        try:
            if timeout and timeout > 0:
                return self._queue.get(timeout=timeout)
            return self._queue.get_nowait()
        except queue.Empty:
            return None

    def _wait_seconds(self) -> float:
        with self._lock:
            if not self._pending:
                return TICK_SECONDS
            soonest = min(p.due for p in self._pending)
        wait = (soonest - self._now()).total_seconds()
        return max(0.0, min(TICK_SECONDS, wait))

    # -- recording -------------------------------------------------------------

    def _name_of(self, camera_id: str) -> str | None:
        try:
            return self._camera_name(camera_id)
        except Exception:
            return None

    def _record(self, event: AlertEvent, give_up: str | None = None) -> list[str]:
        """The event's rows, one per recipient and channel. `give_up` names why
        its messages can no longer go - see `_write`."""
        with self._lock:
            if event.camera_id and not event.camera_name:
                event = replace(event, camera_name=self._name_of(event.camera_id))
            if event.kind == "test":
                return self._record_test(event)
            if self.store.has_rows(event.event_key):
                return []
            rule = self.store.rules().get(event.kind)
            if rule is None:
                return []
            recipients = self.store.recipients()
            now = self._now()

            rows: list[dict] = []
            if event.template in ("weapon.confirmed", "weapon.dismissed"):
                # The verdict follows the opening to exactly the people who got
                # it - whoever received the scare receives the answer.
                targets = self.store.recipients_of(events.opening_key(event))
                if not targets:
                    return []
                for channel in CHANNELS:
                    people = [r for r in recipients
                              if r.channel == channel and (channel, r.id) in targets]
                    if people:
                        rows += self._rows_for(event, channel, people, say_nobody=False)
                return self._write(event, rows, now, give_up)

            if event.kind == "vehicles" and not rule.reason_on(event.facts.get("reason")):
                return []
            for channel in CHANNELS:
                # An event that carries its own channels (a zone's or station's
                # Notify ticks) is not second-guessed by the kind's rule.
                wanted = (channel in event.channels if event.channels is not None
                          else rule.channel_on(channel))
                if wanted:
                    people = [r for r in recipients if r.channel == channel]
                    rows += self._rows_for(event, channel, people)
            return self._write(event, rows, now, give_up)

    def _rows_for(self, event: AlertEvent, channel: str, people: list[Recipient],
                  say_nobody: bool = True) -> list[dict]:
        """The rows one channel owes an event: decided here, written by `_write`."""
        if event.kind == "attendance" and event.groups is None:
            return [dict(outcome="skipped", channel=channel,
                         reason="attendance_unavailable")]
        if self._senders(channel) is None:
            return [dict(outcome="skipped", channel=channel, reason="provider_missing")]
        rows = [dict(outcome="skipped", channel=channel, recipient=person,
                     reason="recipient_off")
                for person in people if not person.enabled]
        enabled = [p for p in people if p.enabled]
        if not enabled:
            if say_nobody:
                rows.append(dict(outcome="skipped", channel=channel,
                                 reason="no_recipients"))
            return rows
        return rows + [self._queued(person, channel) for person in enabled]

    def _queued(self, person: Recipient, channel: str) -> dict:
        return dict(outcome="queued", channel=channel, recipient=person,
                    language=catalogue.language_for(person.language,
                                                    self.config.send_draft_arabic))

    def _record_test(self, event: AlertEvent) -> list[str]:
        person = self.store.recipient(event.recipient_id or "")
        if person is None:
            raise KeyError(event.recipient_id)
        row = self._queued(person, person.channel)
        if self._senders(person.channel) is None:
            row.update(outcome="skipped", reason="provider_missing")
        return self._write(event, [row], self._now())

    def _write(self, event: AlertEvent, rows: list[dict], now: datetime,
               give_up: str | None = None) -> list[str]:
        """One event's rows in one write; then the queued ones are owed an attempt.

        Owed only once written: a message with no row must never reach a courier.
        With `give_up`, a message that would have been queued is written failed
        for that reason instead, and is owed nothing.
        """
        if give_up is not None:
            rows = [dict(row, outcome="failed", reason=give_up)
                    if row["outcome"] == "queued" else row for row in rows]
        ids = self.store.add_rows(event.event_key, event.kind, rows, at=now)
        for row_id, row in zip(ids, rows):
            if row["outcome"] == "queued":
                self._pending.append(_Pending(row_id, event, row["recipient"],
                                              row["channel"], row["language"], due=now))
        return ids

    def _skip_all(self, event: AlertEvent, reason: str, now: datetime) -> None:
        rule = self.store.rules().get(event.kind)
        if rule is None:
            return
        self.store.add_rows(event.event_key, event.kind, [
            dict(outcome="skipped", channel=channel, reason=reason)
            for channel in CHANNELS if rule.channel_on(channel)], at=now)

    # -- sending ---------------------------------------------------------------

    def _send_one_due(self) -> bool:
        now = self._now()
        with self._lock:
            due = [p for p in self._pending if p.due <= now]
            if not due:
                return False
            item = min(due, key=lambda p: p.due)
            self._pending.remove(item)
            self._in_flight = item
        try:
            self._carry(item, now)
        finally:
            with self._lock:
                self._in_flight = None
        return True

    def _carry(self, item: _Pending, now: datetime) -> None:
        """One courier call for one row, and its outcome written to that row."""
        sender = self._senders(item.channel)
        if sender is None:         # the keys went away between recording and now
            self.store.finish(item.row_id, "skipped", at=now, reason="provider_missing",
                              attempts=item.attempts)
            return
        message = catalogue.build(
            item.event, item.language, clock=self.clock,
            console_url=self.config.console_url,
            send_draft_arabic=self.config.send_draft_arabic)
        try:
            result = sender.send(message, item.recipient.destination)
        except Exception as exc:   # a courier must never take the thread with it
            log.exception("alerts: %s sender raised", item.channel)
            result = providers.SendResult.failed("unreachable", type(exc).__name__)

        item.attempts += 1
        finished = self._now()
        if result.ok:
            self.store.mark_sent(item.row_id, result.provider_id or "", item.attempts,
                                 finished)
        elif item.attempts >= self.config.retries:
            self.store.mark_failed(item.row_id, result.reason or "unreachable",
                                   providers.redact(result.provider_reason),
                                   item.attempts, finished)
        else:
            item.due = finished + RETRY_PAUSE
            with self._lock:
                self._pending.append(item)

    # -- ticks -----------------------------------------------------------------

    def _tick_cameras(self, now: datetime) -> None:
        """One message when a camera has been dark long enough, one when back.

        The same `offline_cameras` rule Home uses, so the two cannot disagree.
        `_announced_down` is seeded from the log at start, so a restart while
        a camera is still dark says nothing new - and says "back" once it is.
        It changes only after the row is written: a write that fails leaves
        the camera to be tried again next pass, not taken as said.
        """
        workers = getattr(self.registry, "workers", None) or {}
        offline = events.offline_cameras(
            workers, now, self.config.camera_offline_minutes, self.started_at)
        for camera_id, since in offline.items():
            if camera_id not in self._announced_down:
                self._record(events.camera_down(camera_id, since))
                self._announced_down.add(camera_id)
        for camera_id in list(self._announced_down):
            if camera_id in offline:
                continue
            worker = workers.get(camera_id)
            if worker is None:          # removed from the roster: nothing to say
                self._announced_down.discard(camera_id)
                continue
            try:
                back = worker.status == "ok"
            except Exception:
                continue
            if back:
                self._record(events.camera_up(camera_id, now))
                self._announced_down.discard(camera_id)

    def _tick_report(self, now: datetime) -> None:
        """The noon attendance report: once a school day, never twice, never late.

        Fires in `[report_time, report_time + 10 min)` site time on a school
        day - one of the working days inside the term - when nothing is recorded
        for today yet. The log is what makes "once" survive a restart. Past
        the window with nothing recorded, one `skipped: engine_down_at_noon`
        row per switched-on channel - but only when the sender started after
        the report time: a sender that was running at noon with nothing
        switched on was not down, and says nothing. A day is decided once,
        then left alone.
        """
        if self.hours is None:
            return
        hours = self.hours()
        local = self.clock.local(now)
        day = local.date()
        day_iso = day.isoformat()
        if self._report_day == day_iso:
            return
        if not events.is_school_day(day, hours.term_from, hours.term_to,
                                    hours.working_days):
            self._report_day = day_iso
            return
        start = datetime.combine(day, self.config.report_time)
        if local < start:
            return
        if self.store.has_rows(f"attendance:{day_iso}"):
            self._report_day = day_iso
            return
        if local < start + REPORT_WINDOW:
            counts = None
            if self._attendance_counts is not None:
                try:
                    counts = self._attendance_counts(day_iso)
                except Exception:
                    # No counts is a stated skip below, never invented zeros.
                    log.exception("alerts: the attendance counts could not be read")
            self._record(events.attendance_report(day_iso, now, counts))
        elif self.clock.local(self.started_at) > start:
            self._skip_all(events.attendance_report(day_iso, now, ()),
                           "engine_down_at_noon", now)
        self._report_day = day_iso

    def _tick_retention(self, now: datetime) -> None:
        day = self.clock.local_date(now)
        if self._retention_day == day:
            return
        self._retention_day = day
        cutoff = now - timedelta(days=self.config.log_retention_days)
        removed = self.store.delete_older_than(cutoff)
        if removed:
            log.info("alerts: removed %d delivery-log row(s) older than %d days",
                     removed, self.config.log_retention_days)
