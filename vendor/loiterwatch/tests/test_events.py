from __future__ import annotations

import json

import pytest

from loiterwatch import Event, EventKind, read_jsonl


def test_iso_epoch_and_millis_timestamps_agree():
    iso = Event.from_dict({"ts": "2026-08-09T10:42:31Z", "zone": "atm", "track_id": "1"})
    epoch = Event.from_dict({"ts": iso.ts, "zone": "atm", "track_id": "1"})
    millis = Event.from_dict({"ts": iso.ts * 1000, "zone": "atm", "track_id": "1"})
    assert epoch.ts == pytest.approx(iso.ts)
    assert millis.ts == pytest.approx(iso.ts)


def test_naive_iso_is_treated_as_utc():
    a = Event.from_dict({"ts": "2026-08-09T10:42:31", "zone": "z"})
    b = Event.from_dict({"ts": "2026-08-09T10:42:31Z", "zone": "z"})
    assert a.ts == b.ts


def test_defaults():
    ev = Event.from_dict({"ts": 0, "zone": "atm"})
    assert ev.kind is EventKind.OBSERVATION
    assert ev.confidence == 1.0
    assert ev.track_id is None


def test_jsonl_is_sorted_and_comments_skipped(tmp_path):
    path = tmp_path / "e.jsonl"
    path.write_text(
        "# comment\n"
        + json.dumps({"ts": 20, "zone": "a", "track_id": "1"}) + "\n\n"
        + json.dumps({"ts": 10, "zone": "a", "track_id": "1"}) + "\n"
    )
    assert [e.ts for e in read_jsonl(str(path))] == [10.0, 20.0]


def test_bad_line_reports_line_number(tmp_path):
    path = tmp_path / "e.jsonl"
    path.write_text(json.dumps({"zone": "a"}) + "\n")
    with pytest.raises(ValueError, match=":1:"):
        list(read_jsonl(str(path)))
