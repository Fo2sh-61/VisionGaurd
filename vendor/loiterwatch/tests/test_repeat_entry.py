from __future__ import annotations

from conftest import T0, exit_event, stay

from loiterwatch import Engine, RepeatEntryRule


def engine(**kw):
    params = dict(count=3, window_s=900, min_visit_s=5, min_gap_s=20, cooldown_s=60)
    params.update(kw)
    return Engine([RepeatEntryRule("casing", zones=["atm"], **params)],
                  exit_grace=5.0, tick_s=1.0)


def visit(eng, track, start, length=15):
    stay(eng, track, "atm", start, start + length)
    eng.ingest(exit_event(track, "atm", start + length + 1))


def test_fires_on_third_entry_not_second():
    eng = engine()
    visit(eng, "t1", T0)
    visit(eng, "t1", T0 + 120)
    assert eng.alerts == []
    visit(eng, "t1", T0 + 240)
    assert len(eng.alerts) == 1
    assert eng.alerts[0].evidence["entries"] == 3


def test_walk_by_blips_do_not_count():
    eng = engine()
    for i in range(5):
        visit(eng, "t1", T0 + i * 120, length=2)  # under min_visit_s
    assert eng.alerts == []


def test_entries_outside_window_expire():
    eng = engine(window_s=200)
    visit(eng, "t1", T0)
    visit(eng, "t1", T0 + 100)
    visit(eng, "t1", T0 + 400)  # first is now out of the window
    assert eng.alerts == []


def test_min_gap_rejects_flicker():
    eng = engine(min_gap_s=60)
    visit(eng, "t1", T0)
    visit(eng, "t1", T0 + 30)
    visit(eng, "t1", T0 + 60)
    assert eng.alerts == []


def test_does_not_refire_for_the_same_latest_visit():
    eng = engine(cooldown_s=0)
    visit(eng, "t1", T0)
    visit(eng, "t1", T0 + 120)
    stay(eng, "t1", "atm", T0 + 240, T0 + 400)
    assert len(eng.alerts) == 1


def test_separate_tracks_do_not_pool():
    eng = engine()
    visit(eng, "t1", T0)
    visit(eng, "t2", T0 + 120)
    visit(eng, "t3", T0 + 240)
    assert eng.alerts == []
