"""Cross-camera recognition: one identity pool shared by several `live` processes.

Each `loiterwatch live` process runs its own detector, tracker, and
IdentityStitcher -- one process per camera. Left alone, two such processes each
number their own people p1, p2, ... independently, so "p3" on the front-door
camera and "p3" on the ATM camera are two unrelated strangers who happen to
share a label, and neither process ever learns the other exists.

SharedIdentityStore fixes both problems through one JSON file on disk:

  * **IDs are minted from a counter kept in the file**, allocated under a lock,
    so no two cameras ever hand the same ID to two different people.
  * **On a schedule**, each process pushes its own updates and pulls in
    identities discovered by other cameras, merging galleries rather than
    overwriting them -- so a clothing view captured by camera A is still
    available for matching when that person next walks past camera B.

Concurrency uses a plain lock *file* (atomic create-exclusive via `os.open`),
which behaves the same on Windows and POSIX with no extra dependency, plus
atomic replace on write so a reader never sees a half-written file. A lock left
behind by a crashed process is reclaimed automatically after `stale_lock_s`.

This is eventually consistent, not strictly consistent: a person pruned from one
camera's memory can briefly vanish from the shared file until another camera
that still remembers them syncs again. For loitering alerts that trade-off is
the right one -- availability over one authoritative order of events.
"""
from __future__ import annotations

import json
import os
import tempfile
import time

from .identity import Identity, similarity

# a view this similar to one already in the gallery adds nothing
_NOVELTY_THRESHOLD = 0.93


class LockTimeout(RuntimeError):
    """Could not acquire the shared file's lock within `lock_timeout` seconds."""


def _merge_into(mine: Identity, theirs: Identity, gallery_size: int) -> None:
    """Fold another camera's view of the same person into ours, in place."""
    mine.last_seen = max(mine.last_seen, theirs.last_seen)
    if theirs.first_seen and (not mine.first_seen or theirs.first_seen < mine.first_seen):
        mine.first_seen = theirs.first_seen
    # max, not sum: repeated syncs must not inflate these on every pass
    mine.samples = max(mine.samples, theirs.samples)
    mine.relinks = max(mine.relinks, theirs.relinks)
    for view in theirs.gallery:
        if len(mine.gallery) >= gallery_size:
            break
        if any((similarity(view, existing) or 0) >= _NOVELTY_THRESHOLD
               for existing in mine.gallery):
            continue  # a near-duplicate of a view we already have
        mine.gallery.append(view)


class SharedIdentityStore:
    def __init__(self, path: str, poll_interval: float = 2.0,
                 lock_timeout: float = 5.0, stale_lock_s: float = 20.0) -> None:
        self.path = path
        self.lock_path = path + ".lock"
        self.poll_interval = float(poll_interval)
        self.lock_timeout = float(lock_timeout)
        self.stale_lock_s = float(stale_lock_s)
        self._last_sync = float("-inf")

    # -- locking ------------------------------------------------------------
    def _acquire(self) -> None:
        deadline = time.time() + self.lock_timeout
        while True:
            try:
                fd = os.open(self.lock_path, os.O_CREAT | os.O_EXCL | os.O_RDWR)
                os.close(fd)
                return
            except FileExistsError:
                try:
                    age = time.time() - os.path.getmtime(self.lock_path)
                except OSError:
                    continue  # it was removed between the open() and stat()
                if age > self.stale_lock_s:
                    try:
                        os.remove(self.lock_path)  # a crashed process left this
                    except OSError:
                        pass
                    continue
                if time.time() > deadline:
                    raise LockTimeout(f"could not lock {self.lock_path}")
                time.sleep(0.05)

    def _release(self) -> None:
        try:
            os.remove(self.lock_path)
        except OSError:
            pass

    # -- storage --------------------------------------------------------------
    def _read(self) -> dict:
        try:
            with open(self.path, "r", encoding="utf-8") as handle:
                return json.load(handle)
        except (FileNotFoundError, json.JSONDecodeError):
            return {"version": 1, "next_id": 1, "identities": []}

    def _write(self, payload: dict) -> None:
        directory = os.path.dirname(os.path.abspath(self.path)) or "."
        fd, tmp = tempfile.mkstemp(dir=directory, prefix=".loiterwatch-", suffix=".tmp")
        try:
            with os.fdopen(fd, "w", encoding="utf-8") as handle:
                json.dump(payload, handle)
            os.replace(tmp, self.path)  # atomic on both Windows and POSIX
        finally:
            if os.path.exists(tmp):
                try:
                    os.remove(tmp)
                except OSError:
                    pass

    # -- public ---------------------------------------------------------------
    def mint_id(self) -> str:
        """A stable ID that no other camera process will also hand out."""
        self._acquire()
        try:
            payload = self._read()
            n = int(payload.get("next_id", 1))
            payload["next_id"] = n + 1
            self._write(payload)
            return f"p{n}"
        finally:
            self._release()

    def sync(self, stitcher, now: float, force: bool = False,
             gallery_size: int = 12) -> int:
        """Push this camera's identities out, pull other cameras' in.

        Rate-limited to `poll_interval` unless `force=True` -- safe to call
        every frame from the live loop; most calls do nothing but check a clock.
        Returns how many identities were newly adopted from elsewhere.
        """
        if not force and now - self._last_sync < self.poll_interval:
            return 0
        self._last_sync = now

        self._acquire()
        try:
            payload = self._read()
            shared = {
                raw["stable_id"]: Identity.from_dict(raw)
                for raw in payload.get("identities", [])
            }

            adopted = 0
            for sid, theirs in shared.items():
                mine = stitcher.identities.get(sid)
                if mine is None:
                    stitcher.identities[sid] = theirs
                    adopted += 1
                else:
                    _merge_into(mine, theirs, gallery_size)

            payload["identities"] = [i.to_dict() for i in stitcher.identities.values()]
            payload["next_id"] = max(int(payload.get("next_id", 1)), stitcher._next_id)
            self._write(payload)
            return adopted
        finally:
            self._release()
