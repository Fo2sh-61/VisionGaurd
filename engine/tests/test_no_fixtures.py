"""Nothing invented ever reaches a screen.

The rule these defend is constitution rule 4: **never show anything untrue.**
If something is unavailable, say so plainly with a reason.

`LiveStore` subclasses `MockStore`, which was a good decision — it let each
capability move to real data on its own instead of everything having to land at
once. But it left a trap. Ten live methods called `super()` when their own data
was missing, so a page showed measured numbers and then, the moment a camera
dropped off or a model failed to load, silently showed invented ones instead.

Intermittent is worse than permanent here. A page that is always fake gets
noticed and distrusted. A page that is real until the moment it matters gets
believed.

So: outside demo mode, an unavailable capability returns *empty*, and the
reason travels to `/system/capabilities` for the screen to show. Empty plus a
stated reason is honest. Invented rows are not, however plausible they look.
"""

from __future__ import annotations

import pytest

from vg.api import schemas as S


# -- the ten that used to switch -------------------------------------------
#
# Each is a live method whose own data source is absent. None of them may
# answer with something MockStore made up.

@pytest.mark.parametrize("call, what", [
    (lambda s: s.intrusion_cameras(), "intrusion cameras"),
    (lambda s: s.areas(), "areas"),
    (lambda s: s.people(), "the people directory"),
    (lambda s: s.groups(), "groups"),
])
def test_an_absent_subsystem_returns_nothing_not_fixtures(bare_live_store, call, what):
    assert call(bare_live_store) == [], f"{what} fell back to fixtures"


def test_attendance_without_recognition_is_empty_not_invented(bare_live_store):
    result = bare_live_store.attendance("group", "Everyone", "2026-08-19")
    assert result.present == 0 and result.late == 0
    assert result.days == [] or result.days is None or len(result.days) == 0


def test_track_without_tracking_is_empty_not_invented(bare_live_store):
    result = bare_live_store.track(
        S.TrackQuery(who="Anyone", date="2026-08-19"),
        actor="tester",
    )
    assert result.path == []


def test_site_does_not_borrow_fixture_areas(bare_live_store):
    """`site()` used MockStore as a template and kept its `areas` list."""
    assert bare_live_store.site().areas == []


def test_history_and_group_do_not_fall_back_to_fixtures(bare_live_store):
    """The last two screens that did.

    Both names below are MockStore's own fixtures, so a fall-through returns
    a full page about a child who does not attend this school rather than
    None. What the real ones do instead is in test_person_history.py.
    """
    assert bare_live_store.history("Layla Ahmed") is None
    assert bare_live_store.group("Grade 8") is None


# -- the list the screen checks --------------------------------------------


def test_every_capability_declares_itself(bare_live_store):
    """No capability may be silent about which it is."""
    caps = bare_live_store.capabilities()
    assert caps, "the capability list is empty"
    for cap in caps:
        assert cap.state in (S.DataState.LIVE, S.DataState.UNAVAILABLE, S.DataState.DEMO)


def test_an_unavailable_capability_says_why(bare_live_store):
    """Rule 4: say so plainly, *with a reason*. Empty alone is not enough."""
    unavailable = [c for c in bare_live_store.capabilities()
                   if c.state == S.DataState.UNAVAILABLE]
    assert unavailable, "nothing is running, so something must be unavailable"
    for cap in unavailable:
        assert cap.reason, f"{cap.key} is unavailable and does not say why"
        assert len(cap.reason) > 10, f"{cap.key}'s reason is not a sentence"


def test_a_live_capability_offers_no_excuse(live_ish_store):
    """A working capability with a reason attached would read as broken."""
    for cap in live_ish_store.capabilities():
        if cap.state == S.DataState.LIVE:
            assert cap.reason is None, f"{cap.key} is live but explains itself"


def test_demo_mode_is_labelled_demo_not_live():
    """VG_MOCK serves fixtures on purpose. It must still admit to it."""
    from vg.api.store import MockStore

    caps = MockStore().capabilities()
    assert caps, "MockStore must declare its capabilities too"
    assert all(c.state == S.DataState.DEMO for c in caps), \
        "fixtures reported themselves as live"


# -- the list and the data must never contradict each other ----------------


def test_nothing_unavailable_still_returns_rows(bare_live_store):
    """The worst outcome of this change would be a page arguing with itself.

    A banner reading "not available" above three invented breaches is worse
    than either half alone: the rows are the part people believe, and the
    banner just makes the page look buggy rather than empty.

    So for every capability the engine admits it cannot serve, the method that
    serves it must come back with nothing.
    """
    store = bare_live_store
    getters = {
        "breaches": lambda: store.breaches(30),
        "weapons": lambda: store.weapons(None, None),
        "users": lambda: store.users(),
        "attention": lambda: store.attention(),
        "people": lambda: store.people(),
        "groups": lambda: store.groups(),
        "search_lost": lambda: store.search_lost(S.LostQuery(item="bag")).hits,
        "track": lambda: store.track(
            S.TrackQuery(who="Anyone", date="2026-08-19"), actor="t").path,
        "attendance": lambda: store.attendance(
            "group", "Everyone", "2026-08-19").records,
    }

    for cap in store.capabilities():
        if cap.state != S.DataState.UNAVAILABLE or cap.key not in getters:
            continue
        rows = getters[cap.key]()
        assert rows == [], (
            f"{cap.key} is reported unavailable but still returned "
            f"{len(rows)} row(s) - the page would contradict its own banner"
        )


def test_the_audit_trail_is_real_even_though_it_is_unavailable(bare_live_store):
    """`audit` is the one capability flagged unavailable that still has rows.

    It is marked unavailable because it does not survive a restart, not
    because it is invented — what is in there really happened this session,
    and rule 11 requires a track search to be written before its result
    returns. Dropping those rows to satisfy a tidy rule would delete a real
    audit trail, so this pins the exception on purpose.
    """
    store = bare_live_store
    before = len(store.audit(100))
    store.track(S.TrackQuery(who="Someone", date="2026-08-19"), actor="tester")
    after = store.audit(100)

    assert len(after) == before + 1, "a search that found nothing was not logged"
    assert after[-1].action == "track.search"
