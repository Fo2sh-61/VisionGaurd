"""The site's wall clock.

Every store and the API used to hold a single integer — "we are 180 minutes
ahead of UTC" — worked out once when the process started and then used for
every timestamp forever. Egypt puts its clocks forward at the end of April and
back at the end of October, so an engine started in September is an hour wrong
from the last Friday in October until somebody restarts it. Nothing announces
it. Every arrival time, every chart bucket and every "which day is this?"
boundary is quietly off by an hour.

So an offset is not a property of the site. It is a property of *an instant at*
the site, and that is the only shape this module offers.

Two consequences worth stating, because they are choices and not accidents:

**A past moment keeps the offset it happened under.** An arrival at 07:42 on a
July morning still reads 07:42 in December, because July's offset is what gets
applied to it. The alternative — rendering everything with today's offset —
would move every historical time by an hour on the day the clocks change, so a
register printed in July would stop matching the screen.

**A day boundary is worked out the same way.** `local_date` is what decides
which school day a sighting belongs to, so it has to move with the clock too.

Rows already written keep the date they were written with. They can only be
wrong if the engine ran without a restart straight through a transition, which
is the thing this module prevents.
"""

from __future__ import annotations

import logging
from datetime import date, datetime, time, timedelta, timezone

log = logging.getLogger(__name__)


class Clock:
    """A site clock. Subclasses decide what the offset is at a given instant."""

    #: False when the timezone could not be resolved at all, so every time
    #: shown is UTC rather than local. Surfaced on System Health: constitution
    #: rule 8 — a subsystem that fails to start must say so in the UI, and a
    #: console silently three hours out is exactly that failure.
    ok: bool = True
    error: str | None = None
    name: str = "UTC"

    def offset_minutes(self, when: datetime | None = None) -> int:
        raise NotImplementedError

    def local(self, when: datetime) -> datetime:
        """`when` as the site experienced it. Naive in, naive out."""
        return _as_utc(when) + timedelta(minutes=self.offset_minutes(when))

    def local_date(self, when: datetime) -> str:
        """Which school day an instant belongs to, as an ISO date.

        Not the server's date and not the viewer's: a school in Cairo at 00:30
        local is still on the previous UTC day, and filing an arrival under the
        wrong date silently corrupts the register.
        """
        return self.local(when).date().isoformat()

    def local_time(self, when: datetime) -> time:
        return self.local(when).time()

    def today(self, when: datetime | None = None) -> str:
        return self.local_date(when or datetime.now(timezone.utc))


class FixedClock(Clock):
    """One offset, always. For tests, fixtures, and sites that do not shift.

    A test that used a real timezone would change its answer twice a year,
    which is the opposite of what a test is for.
    """

    def __init__(self, offset_minutes: int = 0, name: str = "UTC") -> None:
        self._offset = offset_minutes
        self.name = name

    def offset_minutes(self, when: datetime | None = None) -> int:
        return self._offset


class SiteClock(Clock):
    """A real IANA timezone, asked afresh for every instant.

    Windows ships no timezone database, so `zoneinfo` needs the `tzdata`
    package (it is in requirements.txt). Falling back to UTC silently would put
    every timestamp in the console three hours out for Cairo — an event at
    6:12am would read 3:12am — so the failure is recorded on the clock itself
    and shown on System Health, not only logged.
    """

    def __init__(self, timezone_name: str) -> None:
        self.name = timezone_name
        self._zone = None
        try:
            from zoneinfo import ZoneInfo

            zone = ZoneInfo(timezone_name)
            if datetime.now(zone).utcoffset() is None:
                raise ValueError("no UTC offset")
            self._zone = zone
        except Exception as exc:
            self.ok = False
            self.error = (
                f"cannot resolve timezone {timezone_name!r} ({exc}). Every time "
                f"shown is UTC, not local. Install tzdata: pip install tzdata"
            )
            log.error("%s", self.error)

    def offset_minutes(self, when: datetime | None = None) -> int:
        if self._zone is None:
            return 0
        moment = _as_utc(when or datetime.now(timezone.utc))
        offset = moment.replace(tzinfo=timezone.utc).astimezone(self._zone).utcoffset()
        return 0 if offset is None else int(offset.total_seconds() // 60)


def clock_for(value: Clock | int | str | None) -> Clock:
    """Accept a clock, a plain offset, or a timezone name.

    The stores used to take `tz_offset_minutes: int`. Tests that want a frozen
    offset still pass one and get a `FixedClock`; production passes a name and
    gets a clock that moves.
    """
    if isinstance(value, Clock):
        return value
    if isinstance(value, str):
        return SiteClock(value)
    return FixedClock(value or 0)


def _as_utc(when: datetime) -> datetime:
    """Naive datetimes are UTC here; the stores write ISO-8601 UTC throughout."""
    if when.tzinfo is None:
        return when
    return when.astimezone(timezone.utc).replace(tzinfo=None)


def minutes_late(local_arrival: time, cutoff: time) -> int:
    """How far past the cutoff an arrival was, in whole minutes."""
    return int(
        (
            datetime.combine(date.today(), local_arrival)
            - datetime.combine(date.today(), cutoff)
        ).total_seconds()
        // 60
    )
