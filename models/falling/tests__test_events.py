"""Shared event-emission state machine (detectors/events.py)."""

from core.features import FALLEN, FALLING, NORMAL, UNKNOWN
from detectors.events import EmitterConfig, EventEmitter

FPS = 10.0
CFG = EmitterConfig(confirm_s=0.3, transition_s=1.0, rearm_s=0.5, cooldown_s=3.0, stale_s=1.0)


def feed(emitter, states, start=0, track=1):
    events = []
    for i, s in enumerate(states):
        ev = emitter.observe(track, start + i, s, 0.9)
        if ev:
            events.append(ev)
    return events


def test_upright_then_fallen_alerts_once_after_confirmation():
    em = EventEmitter(CFG, FPS)
    events = feed(em, [NORMAL] * 5 + [FALLING] * 3 + [FALLEN] * 10)
    assert len(events) == 1
    ev = events[0]
    assert ev.frame_idx == 8 + 2          # 3 FALLEN frames (confirm 0.3 s at 10 fps)
    assert ev.fall_start_frame == 5
    assert em.statuses()[1].alerted


def test_already_lying_never_alerts():
    em = EventEmitter(CFG, FPS)
    assert feed(em, [FALLEN] * 30) == []


def test_slow_transition_does_not_alert():
    em = EventEmitter(CFG, FPS)
    # 15 FALLING frames (1.5 s) between the last NORMAL and the first FALLEN > transition_s
    assert feed(em, [NORMAL] * 5 + [FALLING] * 15 + [FALLEN] * 10) == []


def test_brief_fallen_blip_does_not_alert():
    em = EventEmitter(CFG, FPS)
    assert feed(em, [NORMAL] * 5 + [FALLEN] * 2 + [NORMAL] * 10) == []


def test_unknown_frames_do_not_break_a_fall():
    em = EventEmitter(CFG, FPS)
    events = feed(em, [NORMAL] * 5 + [FALLEN, UNKNOWN, None, FALLEN, FALLEN])
    assert len(events) == 1 and events[0].frame_idx == 8   # FALLEN since frame 5, still FALLEN at 8


def test_rearm_after_recovery_and_cooldown():
    em = EventEmitter(CFG, FPS)
    seq = [NORMAL] * 5 + [FALLEN] * 5 + [NORMAL] * 5 + [FALLEN] * 5   # second fall 1.0 s later: cooldown
    assert len(feed(em, seq)) == 1
    later = [NORMAL] * 10 + [FALLEN] * 5                                # well after the cooldown
    events = feed(em, later, start=len(seq) + 20)
    assert len(events) == 1


def test_no_rearm_without_enough_normal_frames():
    em = EventEmitter(CFG, FPS)
    seq = [NORMAL] * 5 + [FALLEN] * 5 + [NORMAL] * 2 + [FALLEN] * 40 + [NORMAL] * 2 + [FALLEN] * 5
    assert len(feed(em, seq)) == 1


def test_tracks_are_independent_and_pruned():
    em = EventEmitter(CFG, FPS)
    for f in range(5):
        em.observe(1, f, NORMAL)
        em.observe(2, f, FALLEN)
    events = [em.observe(1, f, FALLEN) for f in range(5, 10)]
    assert [e.frame_idx for e in events if e] == [7]
    assert not em.statuses()[2].alerted        # track 2 was lying from the start
    assert em.prune(15) == [2]                 # last seen at 4, stale after 1 s
    assert em.prune(20) == [1]
    assert em.statuses() == {}


def test_single_normal_glitch_while_lying_does_not_alert():
    em = EventEmitter(CFG, FPS)
    assert feed(em, [FALLEN] * 20 + [NORMAL] + [FALLEN] * 10) == []
    assert feed(em, [NORMAL, NORMAL] + [FALLEN] * 10, start=40) == []   # 2 < upright_s (3 frames)


def test_normal_frames_separated_by_unknown_do_not_rearm():
    em = EventEmitter(CFG, FPS)
    assert len(feed(em, [NORMAL] * 5 + [FALLEN] * 5)) == 1
    flicker = ([NORMAL] + [UNKNOWN] * 3) * 12          # 48 frames, never 3 NORMAL in a row
    assert feed(em, flicker + [FALLEN] * 5, start=10) == []
    assert em.statuses()[1].alerted


def test_a_gap_in_observations_breaks_the_upright_streak():
    em = EventEmitter(CFG, FPS)
    for f in (0, 2, 4):                                  # NORMAL every other frame only
        em.observe(1, f, NORMAL)
    assert [em.observe(1, f, FALLEN) for f in range(5, 10)] == [None] * 5


def test_status_reports_unknown_on_frames_without_a_prediction():
    em = EventEmitter(CFG, FPS)
    em.observe(1, 0, FALLEN, 0.8)
    assert em.status(1).state == FALLEN
    em.observe(1, 1, UNKNOWN)
    status = em.status(1)
    assert status.state == UNKNOWN and status.confidence == 0.0 and status.last_seen == 1


def test_long_falling_run_alerts_only_when_enabled():
    cfg = EmitterConfig(confirm_s=0.3, transition_s=1.0, falling_alert_s=1.0)      # 10 frames at 10 fps
    events = feed(EventEmitter(cfg, FPS), [NORMAL] * 5 + [FALLING] * 15)
    assert [e.frame_idx for e in events] == [14] and events[0].fall_start_frame == 5
    assert feed(EventEmitter(CFG, FPS), [NORMAL] * 5 + [FALLING] * 15) == []      # off by default
    assert feed(EventEmitter(cfg, FPS), [FALLING] * 30) == []                     # never upright
    assert feed(EventEmitter(cfg, FPS), [NORMAL] * 5 + [FALLING] * 9 + [NORMAL] * 5) == []   # too short


def test_track_lost_mid_fall_alerts_only_when_enabled():
    cfg = EmitterConfig(lost_alert_s=0.5, min_falling_s=0.2)
    em = EventEmitter(cfg, FPS)
    feed(em, [NORMAL] * 5 + [FALLING] * 3)                 # last seen at frame 7, mid-fall
    events = [e for f in range(8, 20) for e in em.sweep(f)]
    assert [e.frame_idx for e in events] == [12]          # 0.5 s after it vanished, once
    walker = EventEmitter(cfg, FPS)
    feed(walker, [NORMAL] * 10)                           # walking out of view: never
    assert all(not walker.sweep(f) for f in range(10, 40))
    brief = EventEmitter(cfg, FPS)
    feed(brief, [NORMAL] * 5 + [FALLING])                 # 1 frame of evidence < min_falling_s
    assert all(not brief.sweep(f) for f in range(6, 30))
    off = EventEmitter(CFG, FPS)
    feed(off, [NORMAL] * 5 + [FALLING] * 3)
    assert all(not off.sweep(f) for f in range(8, 40))


def test_reset_forgets_everything():
    em = EventEmitter(CFG, FPS)
    feed(em, [NORMAL] * 3)
    em.reset(25.0)
    assert em.statuses() == {} and em.fps == 25.0
