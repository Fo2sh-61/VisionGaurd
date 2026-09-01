"""Cross-camera identity sharing: two `live` processes, one JSON file.

Each test simulates two (or more) processes by creating separate
`IdentityStitcher` / `SharedIdentityStore` instances that all point at the same
path -- exactly what happens when you run `loiterwatch live` twice with the
same `--identity-db`.
"""
from __future__ import annotations

import json
import os
import time

import numpy as np
import pytest

from loiterwatch.identity import BodySignature, Identity, IdentityStitcher
from loiterwatch.live import Detection
from loiterwatch.shared_identity import LockTimeout, SharedIdentityStore

RED, BLUE, GREEN, BLACK = (40, 40, 200), (200, 60, 40), (60, 180, 60), (20, 20, 20)


def person_frame(top, bottom, box=(100, 60, 220, 420), size=(480, 640)):
    frame = np.full((size[0], size[1], 3), 30, dtype=np.uint8)
    x1, y1, x2, y2 = box
    bh = y2 - y1
    frame[y1:y1 + int(bh * 0.52), x1:x2] = top
    frame[y1 + int(bh * 0.52):y2, x1:x2] = bottom
    return frame


def det(track_id, box=(100, 60, 220, 420)):
    return Detection(str(track_id), box, 0.9)


def camera(store_path):
    """One simulated camera process: its own stitcher, minting from the shared store."""
    store = SharedIdentityStore(store_path, poll_interval=0.0)
    stitcher = IdentityStitcher(
        BodySignature(), max_gap_s=9999, min_similarity=0.6, min_quality=0.55,
        id_source=store.mint_id,
    )
    return store, stitcher


# -- ID minting -------------------------------------------------------------
def test_two_cameras_never_mint_the_same_id(tmp_path):
    path = str(tmp_path / "ids.json")
    a, b = SharedIdentityStore(path), SharedIdentityStore(path)
    minted = [a.mint_id() for _ in range(5)] + [b.mint_id() for _ in range(5)]
    assert len(set(minted)) == 10, "every ID must be unique across processes"


def test_mint_id_survives_a_restart(tmp_path):
    path = str(tmp_path / "ids.json")
    first = SharedIdentityStore(path)
    used = {first.mint_id() for _ in range(3)}

    second = SharedIdentityStore(path)  # new process, same file
    next_one = second.mint_id()
    assert next_one not in used, "a restarted process must not reuse old IDs"


def test_the_concurrent_guard_survives_the_round_trip_through_the_file(tmp_path):
    """One process per camera cannot see the other's live tracks.

    `holders` only knows about tracks in *this* process, so across two `live`
    processes every adopted identity looks unheld -- switching the guard off in
    the one deployment where cross-camera matching is hardest. The identity's
    own last_camera/last_seen come through the file, and answer for both.
    """
    path = str(tmp_path / "ids.json")
    store_a, stitch_a = camera(path)
    _store_b, stitch_b = camera(path)

    frame = person_frame(RED, BLUE)
    for i in range(4):
        stitch_a.update(frame, [det(1)], 100.0 + i, camera="cam_a")
    store_a.sync(stitch_a, now=104.0, force=True)

    seen = stitch_a.update(frame, [det(1)], 104.0, camera="cam_a")
    stable = seen.detections[0].track_id
    assert stitch_b.holders(stable, 104.0) == set(), "no local track holds it"
    assert stitch_b._is_concurrent(stable, "cam_b", 104.0) is False, "not adopted yet"

    stitch_b.identities[stable] = stitch_a.identities[stable]
    assert stitch_b._is_concurrent(stable, "cam_b", 104.5) is True
    assert stitch_b._is_concurrent(stable, "cam_b", 400.0) is False, "long gone"


# -- sync: pushing local state, pulling other cameras' -----------------------
def test_a_person_seen_on_camera_a_is_adopted_by_camera_b(tmp_path):
    path = str(tmp_path / "ids.json")
    store_a, stitch_a = camera(path)
    store_b, stitch_b = camera(path)

    frame = person_frame(RED, BLUE)
    result = stitch_a.update(frame, [det(1)], 100.0)
    stable_id = result.detections[0].track_id
    store_a.sync(stitch_a, now=100.0, force=True)

    adopted = store_b.sync(stitch_b, now=100.0, force=True)
    assert adopted == 1
    assert stable_id in stitch_b.identities


def test_camera_b_recognises_a_person_it_has_never_seen_before(tmp_path):
    """The actual point of the feature: walk past camera A, then camera B."""
    path = str(tmp_path / "ids.json")
    store_a, stitch_a = camera(path)
    store_b, stitch_b = camera(path)

    frame = person_frame(RED, BLUE)
    seen_on_a = stitch_a.update(frame, [det(1)], 100.0).detections[0].track_id
    store_a.sync(stitch_a, now=100.0, force=True)
    stitch_a.update(person_frame(BLACK, BLACK), [], 110.0)  # leaves camera A's view

    store_b.sync(stitch_b, now=200.0, force=True)  # B pulls A's known people first
    result = stitch_b.update(frame, [det(99)], 200.0)  # same person arrives at B

    assert result.detections[0].track_id == seen_on_a
    assert stitch_b.merges == 1


def test_syncing_repeatedly_does_not_inflate_sample_counts(tmp_path):
    """Regression guard: naive merging would double `samples` on every sync."""
    path = str(tmp_path / "ids.json")
    store, stitch = camera(path)
    stitch.update(person_frame(RED, BLUE), [det(1)], 100.0)
    store.sync(stitch, now=100.0, force=True)
    before = stitch.identities[list(stitch.identities)[0]].samples

    for i in range(5):
        store.sync(stitch, now=101.0 + i, force=True)
    after = stitch.identities[list(stitch.identities)[0]].samples
    assert after == before, "repeated syncs with no new observations must be no-ops"


def test_galleries_merge_without_duplicating_identical_views(tmp_path):
    path = str(tmp_path / "ids.json")
    store_a, stitch_a = camera(path)
    store_b, stitch_b = camera(path)

    frame = person_frame(RED, BLUE)
    stitch_a.update(frame, [det(1)], 100.0)
    store_a.sync(stitch_a, now=100.0, force=True)
    store_b.sync(stitch_b, now=100.0, force=True)

    sid = list(stitch_b.identities)[0]
    before = len(stitch_b.identities[sid].gallery)
    for i in range(5):
        store_b.sync(stitch_b, now=101.0 + i, force=True)
    after = len(stitch_b.identities[sid].gallery)
    assert after == before, "re-syncing the same view must not grow the gallery"


def test_a_second_outfit_view_from_another_camera_is_added(tmp_path):
    """Camera A saw them from the front, camera B from the back -- both views
    should end up in the shared gallery so either angle matches later."""
    path = str(tmp_path / "ids.json")
    store_a, stitch_a = camera(path)
    store_b, stitch_b = camera(path)

    front = person_frame(RED, BLUE)
    back = person_frame(GREEN, BLACK)

    stitch_a.update(front, [det(1)], 100.0)
    store_a.sync(stitch_a, now=100.0, force=True)

    store_b.sync(stitch_b, now=101.0, force=True)
    sid = list(stitch_b.identities)[0]
    # same raw track id "1" locally on camera B, but a different outfit view --
    # touch it directly the way update() would, to add the second gallery entry
    stitch_b.raw_to_stable["7"] = sid
    stitch_b._touch(sid, BodySignature().signature(back, (100, 60, 220, 420)), 101.0)
    store_b.sync(stitch_b, now=102.0, force=True)

    store_a.sync(stitch_a, now=103.0, force=True)
    assert len(stitch_a.identities[sid].gallery) == 2


def test_poll_interval_rate_limits_unless_forced(tmp_path):
    path = str(tmp_path / "ids.json")
    store, stitch = camera(path)
    store.poll_interval = 100.0
    assert store.sync(stitch, now=0.0, force=True) == 0  # first call primes _last_sync
    # a second call moments later, not forced, should be skipped -> returns 0
    # with no exception and no file write
    exists_before = os.path.exists(store.path)
    store.sync(stitch, now=0.5)
    assert os.path.exists(store.path) == exists_before


# -- durability under a crashed / slow peer -----------------------------------
def test_a_stale_lock_from_a_crashed_process_is_reclaimed(tmp_path):
    path = str(tmp_path / "ids.json")
    store = SharedIdentityStore(path, lock_timeout=0.3, stale_lock_s=0.1)
    # simulate a crashed process: lock file present, never released
    with open(store.lock_path, "w") as fh:
        fh.write("")
    old = time.time() - 5
    os.utime(store.lock_path, (old, old))

    store.mint_id()  # must reclaim the stale lock rather than raising
    assert not os.path.exists(store.lock_path)


def test_a_fresh_lock_held_by_someone_else_times_out(tmp_path):
    path = str(tmp_path / "ids.json")
    store = SharedIdentityStore(path, lock_timeout=0.2, stale_lock_s=60.0)
    with open(store.lock_path, "w") as fh:
        fh.write("")  # freshly created -- not stale, must not be reclaimed
    with pytest.raises(LockTimeout):
        store.mint_id()


def test_loading_a_corrupt_file_does_not_crash(tmp_path):
    path = tmp_path / "ids.json"
    path.write_text("{not valid json")
    store = SharedIdentityStore(str(path))
    assert store.mint_id() == "p1"  # falls back to a fresh counter


# -- end to end through IdentityStitcher, three cameras -----------------------
def test_three_cameras_share_one_person_correctly(tmp_path):
    path = str(tmp_path / "ids.json")
    stores = [camera(path) for _ in range(3)]
    frame = person_frame(RED, BLUE)

    # person walks past camera 0
    first_id = stores[0][1].update(frame, [det(1)], 100.0).detections[0].track_id
    stores[0][0].sync(stores[0][1], now=100.0, force=True)
    stores[0][1].update(person_frame(BLACK, BLACK), [], 110.0)

    # ... then camera 1 ...
    stores[1][0].sync(stores[1][1], now=200.0, force=True)
    r1 = stores[1][1].update(frame, [det(1)], 200.0)
    assert r1.detections[0].track_id == first_id
    stores[1][0].sync(stores[1][1], now=201.0, force=True)
    stores[1][1].update(person_frame(BLACK, BLACK), [], 210.0)

    # ... then camera 2
    stores[2][0].sync(stores[2][1], now=300.0, force=True)
    r2 = stores[2][1].update(frame, [det(1)], 300.0)
    assert r2.detections[0].track_id == first_id


def test_different_people_on_different_cameras_stay_different(tmp_path):
    path = str(tmp_path / "ids.json")
    store_a, stitch_a = camera(path)
    store_b, stitch_b = camera(path)

    id_a = stitch_a.update(person_frame(RED, BLUE), [det(1)], 100.0).detections[0].track_id
    store_a.sync(stitch_a, now=100.0, force=True)

    store_b.sync(stitch_b, now=100.0, force=True)
    id_b = stitch_b.update(person_frame(GREEN, BLACK), [det(1)], 100.0).detections[0].track_id

    assert id_a != id_b
    assert stitch_b.merges == 0
