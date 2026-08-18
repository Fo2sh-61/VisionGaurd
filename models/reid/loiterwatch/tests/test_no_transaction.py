from __future__ import annotations

from conftest import T0, obs, signal, stay

from loiterwatch import Engine, NoTransactionRule


def engine(**kw):
    params = dict(dwell_s=45, expects=["card_inserted"], scope="track", cooldown_s=60)
    params.update(kw)
    return Engine([NoTransactionRule("no_card", zones=["atm"], **params)],
                  exit_grace=5.0, tick_s=1.0)


def test_fires_when_no_transaction_signal_arrives():
    eng = engine()
    stay(eng, "t1", "atm", T0, T0 + 60)
    assert len(eng.alerts) == 1
    assert eng.alerts[0].evidence["observed_signals"] == []


def test_silent_when_the_person_actually_used_the_machine():
    eng = engine()
    events = [obs("t1", "atm", T0 + i) for i in range(0, 90, 2)]
    events.append(signal("atm", "card_inserted", T0 + 21))
    eng.ingest_all(sorted(events, key=lambda e: e.ts))
    assert eng.alerts == []


def test_unattributed_signal_credits_everyone_currently_in_zone():
    """Card readers cannot name a track, so the signal covers the whole zone."""
    eng = engine()
    events = [obs(t, "atm", T0 + i) for i in range(0, 90, 2) for t in ("t1", "t2")]
    events.append(signal("atm", "card_inserted", T0 + 11))
    eng.ingest_all(sorted(events, key=lambda e: e.ts))
    assert eng.alerts == []


def test_arriving_after_someone_elses_transaction_still_alerts():
    eng = engine()
    eng.ingest(signal("atm", "card_inserted", T0))
    stay(eng, "t2", "atm", T0 + 30, T0 + 90)
    assert len(eng.alerts) == 1
    assert eng.alerts[0].track_id == "t2"


def test_zone_scope_treats_any_machine_use_as_explanation():
    eng = engine(scope="zone")
    events = [obs("t1", "atm", T0 + i) for i in range(0, 120, 2)]
    events.append(signal("atm", "card_inserted", T0 + 30))
    eng.ingest_all(sorted(events, key=lambda e: e.ts))
    assert eng.alerts == []


def test_fires_once_per_visit():
    eng = engine(cooldown_s=0)
    stay(eng, "t1", "atm", T0, T0 + 300)
    assert len(eng.alerts) == 1
