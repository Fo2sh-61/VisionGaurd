"""Record a camera to disk, started and stopped by a person.

Deliberately **not** a rolling buffer. Holding the last thirty seconds of every
camera in memory so a clip can reach backwards costs that memory all day, on
every camera, whether or not anybody ever presses the button. This records from
the moment it is asked to and no earlier, which is the honest thing the button
can promise: what you see after pressing record is what you get.

The consequence has to be said plainly on screen rather than discovered: a
weapon detection that has already happened is not in the video. The recording
starts when you press it.

Three things this must never do:

**Stall ingest.** It reads from a `Subscription`, which drops old frames rather
than growing, so a slow disk costs frames in the recording and nothing else.

**Run forever.** A recording nobody stopped fills the disk overnight — roughly
10 GB a camera. There is a hard limit, and hitting it is recorded as the reason
the recording ended rather than looking like a normal stop.

**Claim a file it did not write.** A camera that goes dark the moment recording
starts produces no frames and therefore no file. That comes back as a failure
with a reason, not as a saved recording of nothing.
"""

from __future__ import annotations

import logging
import threading
import uuid
from dataclasses import dataclass, field
from datetime import datetime, timezone
from pathlib import Path

import cv2

from vg.clock import Clock, clock_for
from vg.ingest.framebus import FrameBus

log = logging.getLogger(__name__)

#: A recording nobody stopped ends itself. Ten minutes is long enough to follow
#: an incident through a building and short enough that forgetting costs a file
#: rather than a disk.
MAX_SECONDS = 600.0

#: If no frame arrives in this long, the camera is dark and there is nothing to
#: record. Ending with that reason beats a recording indicator that never stops.
NO_FRAMES_SECONDS = 15.0

#: mp4v is what OpenCV ships everywhere. H.264 needs a licensed build.
FOURCC = "mp4v"


@dataclass
class Recording:
    """One recording, running or finished."""

    id: str
    camera_id: str
    started_at: datetime
    started_by: str
    fps: float
    state: str = "recording"  # recording | saved | failed
    stopped_at: datetime | None = None
    frames: int = 0
    path: Path | None = None
    #: Why it ended, when that was not a person pressing stop. Also why it
    #: failed. None while running or after a plain stop.
    reason: str | None = None

    @property
    def seconds(self) -> float:
        end = self.stopped_at or datetime.now(timezone.utc)
        return max(0.0, (end - self.started_at).total_seconds())

    @property
    def running(self) -> bool:
        return self.state == "recording"


@dataclass
class _Job:
    recording: Recording
    stop: threading.Event = field(default_factory=threading.Event)
    thread: threading.Thread | None = None


class Recorder:
    """Every recording in flight, and the folder they land in.

    One recording per camera at a time. Two people pressing record on the same
    camera would otherwise write two files from one stream and the second stop
    would end whichever the dictionary happened to hold.
    """

    def __init__(
        self,
        bus: FrameBus,
        directory: Path | str,
        clock: Clock | int | str = 0,
        max_seconds: float = MAX_SECONDS,
    ) -> None:
        self.bus = bus
        self.directory = Path(directory)
        self.clock = clock_for(clock)
        self.max_seconds = max_seconds
        self._jobs: dict[str, _Job] = {}
        self._finished: dict[str, Recording] = {}
        self._lock = threading.RLock()

    # -- asking -------------------------------------------------------------

    def current(self, camera_id: str) -> Recording | None:
        """The running recording for a camera, or the last finished one."""
        with self._lock:
            job = self._jobs.get(camera_id)
            if job is not None:
                return job.recording
            return self._finished.get(camera_id)

    def running(self) -> list[Recording]:
        with self._lock:
            return [j.recording for j in self._jobs.values()]

    # -- doing --------------------------------------------------------------

    def start(self, camera_id: str, actor: str, fps: float = 10.0) -> Recording:
        """Begin recording. Raises `AlreadyRecording` if one is already running.

        The caller gets the recording back straight away rather than waiting
        for the first frame — the operator pressed a button and needs the
        indicator to change now, and a camera that turns out to be dark reports
        that a moment later through the same object.
        """
        with self._lock:
            if camera_id in self._jobs:
                raise AlreadyRecording(camera_id)

            started = datetime.now(timezone.utc)
            recording = Recording(
                id=uuid.uuid4().hex[:12],
                camera_id=camera_id,
                started_at=started,
                started_by=actor,
                fps=max(1.0, fps),
            )
            job = _Job(recording=recording)
            job.thread = threading.Thread(
                target=self._run, args=(job,),
                name=f"recorder-{camera_id}", daemon=True,
            )
            self._jobs[camera_id] = job
            job.thread.start()

        log.info("recording %s started on %s by %s",
                 recording.id, camera_id, actor)
        return recording

    def stop(self, camera_id: str, actor: str) -> Recording | None:
        """End a running recording and wait for the file to be closed.

        Waiting matters: returning before the writer has released the file
        would hand back a path that cannot be opened yet, and the operator
        would go looking for it.
        """
        with self._lock:
            job = self._jobs.get(camera_id)
            if job is None:
                return None

        job.stop.set()
        if job.thread is not None:
            job.thread.join(timeout=10.0)

        with self._lock:
            self._jobs.pop(camera_id, None)
            self._finished[camera_id] = job.recording

        log.info("recording %s stopped on %s by %s - %d frames, %s",
                 job.recording.id, camera_id, actor, job.recording.frames,
                 job.recording.path)
        return job.recording

    def stop_all(self) -> None:
        """Shutdown. An unfinished mp4 is an unplayable one."""
        for camera_id in list(self._jobs):
            self.stop(camera_id, actor="shutdown")

    # -- the thread ---------------------------------------------------------

    def _run(self, job: _Job) -> None:
        recording = job.recording
        writer: cv2.VideoWriter | None = None
        subscription = self.bus.subscribe(recording.camera_id, maxsize=8)
        try:
            while not job.stop.is_set():
                if recording.seconds >= self.max_seconds:
                    recording.reason = (
                        f"Stopped automatically after "
                        f"{int(self.max_seconds // 60)} minutes."
                    )
                    break

                frame = subscription.get(timeout=1.0)
                if frame is None:
                    if recording.frames == 0 and recording.seconds >= NO_FRAMES_SECONDS:
                        recording.reason = (
                            "The camera sent no frames, so there was nothing "
                            "to record."
                        )
                        break
                    continue

                if writer is None:
                    writer = self._open(recording, frame)
                    if writer is None:
                        return  # _open recorded the reason
                writer.write(frame.image)
                recording.frames += 1
        except Exception as exc:
            log.exception("recording %s failed", recording.id)
            recording.state = "failed"
            recording.reason = f"Recording failed: {exc}"
        finally:
            self.bus.unsubscribe(subscription)
            if writer is not None:
                writer.release()
            recording.stopped_at = datetime.now(timezone.utc)
            if recording.state == "recording":
                # No frames means no file, and a "saved" recording with nothing
                # in it is the fake save rule 4 forbids.
                if recording.frames == 0:
                    recording.state = "failed"
                    recording.reason = recording.reason or (
                        "No frames were captured, so no file was written."
                    )
                    recording.path = None
                else:
                    recording.state = "saved"
            with self._lock:
                if self._jobs.get(recording.camera_id) is job:
                    self._jobs.pop(recording.camera_id, None)
                    self._finished[recording.camera_id] = recording

    def _open(self, recording: Recording, frame) -> cv2.VideoWriter | None:
        """Open the file once the first frame has told us its size."""
        try:
            self.directory.mkdir(parents=True, exist_ok=True)
            stamp = self.clock.local(recording.started_at).strftime("%Y%m%d-%H%M%S")
            path = self.directory / f"{recording.camera_id}_{stamp}.mp4"
            writer = cv2.VideoWriter(
                str(path), cv2.VideoWriter_fourcc(*FOURCC),
                recording.fps, (frame.width, frame.height),
            )
            if not writer.isOpened():
                raise OSError(f"could not open {path} for writing")
        except Exception as exc:
            log.exception("recording %s could not open a file", recording.id)
            recording.state = "failed"
            recording.reason = f"Could not write the file: {exc}"
            return None

        recording.path = path
        return writer


class AlreadyRecording(RuntimeError):
    """One recording per camera. Two writers on one stream is not a feature."""

    def __init__(self, camera_id: str) -> None:
        super().__init__(f"{camera_id} is already recording")
        self.camera_id = camera_id
