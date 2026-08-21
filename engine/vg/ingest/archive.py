"""Recorded video, fetched on demand and processed in pieces.

This is the only genuinely new machinery in the Track feature, and the only
place in the system that starts threads outside a `FeatureWorker`. Everything
here exists to answer one question — *show me the video behind that stop* —
without lying about how long it will take.

**Nothing runs until somebody asks.** An idle engine does no archive work at
all. There is no background indexing, no pre-processing, and no cache warming
except the one explicit prefetch of the next stop the operator is likely to
click.

**Pieces, not files.** A leg is cut into chunks of `archive.chunk_seconds`.
Playback starts as soon as the first one lands rather than when the last one
does, which is the difference between a ten-second wait and a two-minute one.
Each chunk is a self-contained mp4 with the outlines burnt in, so it is
evidence that can be handed to somebody without this console.

**Two backends behind one seam.** `footage` slices files already on disk and
needs no hardware; `dvr` pulls a time range off a recorder with ffmpeg. The
first is what the tests and the dev machine use, so the whole pipeline is
exercised long before a recorder is plugged in.

**Two workers, a bounded queue, and an honest refusal.** A fetch-and-process
takes seconds, so it cannot happen inside a request; but an unbounded queue
would accept work it has no intention of doing soon. Full means full, and the
caller is told.

Every timing this module quotes comes from `measured_rates`, written by
`tools/measure_track.py` against the actual machine. With no measurement
there is no estimate — the page says the wait is unknown rather than
inventing one.
"""

from __future__ import annotations

import json
import logging
import queue
import shutil
import subprocess
import threading
import uuid
from dataclasses import dataclass, field
from datetime import datetime, timedelta, timezone
from pathlib import Path

import cv2
import numpy as np

log = logging.getLogger(__name__)

#: Colours burnt into a chunk. The same meanings as everywhere else: amber is
#: a body nobody has identified, blue is "the same body", green is a face.
#: BGR, because that is what OpenCV draws in.
AMBER = (63, 162, 223)
BLUE = (216, 155, 91)
GREEN = (116, 143, 63)

#: How long one fetch may run before it is given up on. A DVR that has stopped
#: answering must not hold a worker for ever.
FETCH_TIMEOUT_SECONDS = 120.0

#: The frame rate recorded footage is assumed to run at, for turning a span
#: of video into a number of frames. `tools/measure_track.py` divides by the
#: same constant, so an estimate stays consistent with its measurement even
#: where the assumption does not hold.
SOURCE_FPS = 15.0

#: What `{start}` and `{end}` become in a DVR playback URL. Hikvision's
#: ISO-8601 basic form, which most recorders that speak this dialect accept.
DVR_TIME_FORMAT = "%Y%m%dT%H%M%SZ"


class ArchiveUnavailable(RuntimeError):
    """No archive is configured, or it cannot serve that span."""


class QueueFull(RuntimeError):
    """The runner already has as much work as it will honestly promise."""


class NotMeasured(RuntimeError):
    """Nobody has measured this machine, so there is no honest estimate."""


# ---------------------------------------------------------------------------
# what a job is
# ---------------------------------------------------------------------------

@dataclass
class Chunk:
    """One processed piece of a leg."""

    index: int
    path: Path
    start: datetime
    seconds: float


@dataclass
class LegJob:
    """One request for the video behind a stop.

    Held in memory. A restart loses it, which is stated rather than hidden:
    every chunk is derivable from the archive again, so the page re-offers the
    action instead of pretending the job survived.
    """

    id: str
    camera_id: str
    start: datetime
    end: datetime
    person_id: str | None = None
    descriptor: np.ndarray | None = None
    state: str = "queued"  # queued | running | done | failed
    chunks: list[Chunk] = field(default_factory=list)
    chunks_total: int = 0
    error: str | None = None
    submitted_at: datetime = field(default_factory=lambda: datetime.now(timezone.utc))
    #: Set on a prefetched job so the page can say the next stop is warm.
    prefetch: bool = False

    @property
    def progress(self) -> float:
        if self.chunks_total <= 0:
            return 0.0
        return min(1.0, len(self.chunks) / self.chunks_total)

    @property
    def seconds(self) -> float:
        return (self.end - self.start).total_seconds()


# ---------------------------------------------------------------------------
# where the video comes from
# ---------------------------------------------------------------------------

class FootageBackend:
    """Slices files already sitting under `storage.footage_dir`.

    Spans are read from each clip's sidecar json when there is one — it
    records `started_utc`, `duration_seconds` and `camera_id`, which is
    exactly the index needed and is more trustworthy than a filename. Files
    without a sidecar fall back to the recorder's own naming.
    """

    name = "footage"

    def __init__(self, footage_dir: Path) -> None:
        self.directory = Path(footage_dir)

    def coverage(self, camera_id: str) -> list[tuple[datetime, datetime, Path]]:
        found: list[tuple[datetime, datetime, Path]] = []
        if not self.directory.is_dir():
            return found

        for clip in sorted(self.directory.glob("*.mp4")):
            span = self._span_of(clip)
            if span is None:
                continue
            cam, start, end = span
            if cam == camera_id:
                found.append((start, end, clip))
        return found

    def _span_of(self, clip: Path) -> tuple[str, datetime, datetime] | None:
        sidecar = clip.with_suffix(".json")
        if sidecar.is_file():
            try:
                meta = json.loads(sidecar.read_text(encoding="utf-8"))
                start = _parse(meta["started_utc"])
                seconds = float(meta.get("duration_seconds") or 0.0)
                return str(meta["camera_id"]), start, start + timedelta(seconds=seconds)
            except (KeyError, ValueError, TypeError, json.JSONDecodeError):
                log.debug("unreadable sidecar %s", sidecar)

        # `<camera>_<YYYYMMDD-HHMMSS>.mp4`, which is what the recorder writes.
        # Duration comes from the file itself; there is nowhere else to get it.
        parts = clip.stem.rsplit("_", 1)
        if len(parts) != 2:
            return None
        try:
            start = datetime.strptime(parts[1], "%Y%m%d-%H%M%S").replace(
                tzinfo=timezone.utc)
        except ValueError:
            return None
        seconds = _duration_of(clip)
        if seconds <= 0:
            return None
        return parts[0].split("_")[-1], start, start + timedelta(seconds=seconds)

    def fetch(self, camera_id: str, start: datetime, end: datetime, into: Path) -> Path:
        """Cut [start, end) out of whichever file covers it."""
        for file_start, file_end, clip in self.coverage(camera_id):
            if start >= file_start and start < file_end:
                offset = (start - file_start).total_seconds()
                wanted = min((end - start).total_seconds(), (file_end - start).total_seconds())
                _slice(clip, into, offset, wanted)
                return into

        raise ArchiveUnavailable(
            f"No recorded footage covers {camera_id} at "
            f"{start.isoformat(timespec='seconds')}."
        )


class DvrBackend:
    """Pulls a time range off a recorder with ffmpeg.

    The URL is a template because every recorder spells playback differently,
    and encoding one vendor's dialect in code would mean a code change for the
    next site. `{channel}` comes from `archive.channels`, `{start}` and
    `{end}` are UTC in the DVR's usual basic ISO form.
    """

    name = "dvr"

    def __init__(self, template: str, channels: dict[str, str]) -> None:
        self.template = template
        self.channels = dict(channels)

    def coverage(self, camera_id: str) -> list[tuple[datetime, datetime, Path]]:
        # A recorder is not asked what it holds; it is asked for a span and it
        # either answers or does not. Claiming to know its coverage without
        # querying it would be an invention.
        return []

    def fetch(self, camera_id: str, start: datetime, end: datetime, into: Path) -> Path:
        channel = self.channels.get(camera_id)
        if channel is None:
            raise ArchiveUnavailable(
                f"{camera_id} has no channel in `archive.channels`, so the "
                f"recorder cannot be asked for its video."
            )

        url = self.template.format(
            channel=channel,
            start=start.astimezone(timezone.utc).strftime(DVR_TIME_FORMAT),
            end=end.astimezone(timezone.utc).strftime(DVR_TIME_FORMAT),
        )
        seconds = max(1.0, (end - start).total_seconds())

        try:
            done = subprocess.run(
                ["ffmpeg", "-nostdin", "-y", "-rtsp_transport", "tcp",
                 "-i", url, "-t", f"{seconds:.1f}", "-c", "copy", str(into)],
                capture_output=True, timeout=FETCH_TIMEOUT_SECONDS,
            )
        except FileNotFoundError as exc:
            raise ArchiveUnavailable(
                "ffmpeg is not on PATH, so recorded video cannot be fetched."
            ) from exc
        except subprocess.TimeoutExpired as exc:
            raise ArchiveUnavailable(
                f"The recorder did not answer within "
                f"{FETCH_TIMEOUT_SECONDS:.0f}s for {camera_id}."
            ) from exc

        if done.returncode != 0 or not into.is_file() or into.stat().st_size == 0:
            tail = (done.stderr or b"").decode("utf-8", "replace").strip().splitlines()
            raise ArchiveUnavailable(
                f"The recorder refused that span for {camera_id}"
                + (f": {tail[-1]}" if tail else ".")
            )
        return into


def backend_for(config, footage_dir: Path):
    """The archive seam, chosen by config. Never guessed at."""
    if config.backend == "footage":
        return FootageBackend(footage_dir)
    if not config.playback_url:
        raise ArchiveUnavailable(
            "The dvr backend has no `archive.playback_url`, so there is "
            "nowhere to fetch recorded video from."
        )
    return DvrBackend(config.playback_url, config.channels)


# ---------------------------------------------------------------------------
# the runner
# ---------------------------------------------------------------------------

class ArchiveRunner:
    """Two threads, a bounded queue, and no work at all when nobody asks.

    Two rather than one because the operator's leg and the prefetch of the
    next one should not queue behind each other; two rather than four because
    each is decoding and encoding video and they share one GPU and one disk.

    The queue is bounded on purpose. An unbounded one accepts work it has no
    intention of getting to soon, and then the page shows a spinner that means
    nothing. Full is answered with `QueueFull`, and the page says so.
    """

    def __init__(
        self,
        source,
        clips_dir: Path,
        chunk_seconds: float = 30.0,
        keep_legs: int = 3,
        detector=None,
        workers: int = 2,
        queue_size: int = 8,
    ) -> None:
        self.source = source
        self.root = Path(clips_dir) / "track"
        self.chunk_seconds = float(chunk_seconds)
        self.keep_legs = int(keep_legs)
        self.detector = detector

        self._queue: queue.Queue = queue.Queue(maxsize=queue_size)
        self._jobs: dict[str, LegJob] = {}
        self._order: list[str] = []
        self._lock = threading.RLock()
        self._stop = threading.Event()
        self._threads = [
            threading.Thread(target=self._run, name=f"archive-{i}", daemon=True)
            for i in range(workers)
        ]
        for thread in self._threads:
            thread.start()

    # -- submitting ---------------------------------------------------------

    def submit(
        self, camera_id: str, start: datetime, end: datetime,
        person_id: str | None = None, descriptor=None, prefetch: bool = False,
    ) -> LegJob:
        job = LegJob(
            id=uuid.uuid4().hex[:12],
            camera_id=camera_id, start=start, end=end,
            person_id=person_id, descriptor=descriptor, prefetch=prefetch,
        )
        job.chunks_total = max(1, int(round(job.seconds / self.chunk_seconds)))

        try:
            self._queue.put_nowait(job)
        except queue.Full as exc:
            raise QueueFull(
                "The engine is already fetching as much recorded video as it "
                "can keep up with. Try again in a moment."
            ) from exc

        with self._lock:
            self._jobs[job.id] = job
            self._order.append(job.id)
        return job

    def job(self, job_id: str) -> LegJob | None:
        with self._lock:
            return self._jobs.get(job_id)

    def chunk(self, job_id: str, index: int) -> tuple[Path | None, str]:
        """A chunk's file, or why there is not one. The breach-clip shape."""
        job = self.job(job_id)
        if job is None:
            return None, ("That piece of video has been replaced by newer ones. "
                          "Ask for the stop again and it will be rebuilt.")
        for chunk in job.chunks:
            if chunk.index == index:
                if chunk.path.is_file():
                    return chunk.path, ""
                return None, "That piece of video is no longer on disk."
        if job.state == "failed":
            return None, job.error or "That leg could not be built."
        return None, "That piece of video has not been built yet."

    def stop(self) -> None:
        self._stop.set()
        for thread in self._threads:
            thread.join(timeout=3.0)

    # -- the loop -----------------------------------------------------------

    def _run(self) -> None:
        while not self._stop.is_set():
            try:
                job = self._queue.get(timeout=0.5)
            except queue.Empty:
                continue
            try:
                self._build(job)
            except Exception as exc:  # noqa: BLE001 - a bad job is not a dead runner
                job.state = "failed"
                job.error = str(exc)
                log.warning("leg %s failed: %s", job.id, exc)
            finally:
                self._queue.task_done()

    def _build(self, job: LegJob) -> None:
        job.state = "running"
        directory = self.root / job.id
        directory.mkdir(parents=True, exist_ok=True)

        at = job.start
        index = 0
        while at < job.end and not self._stop.is_set():
            until = min(job.end, at + timedelta(seconds=self.chunk_seconds))
            raw = directory / f"raw-{index:03d}.mp4"
            out = directory / f"chunk-{index:03d}.mp4"

            try:
                self.source.fetch(job.camera_id, at, until, raw)
            except ArchiveUnavailable:
                if index == 0:
                    raise
                # Ran off the end of what the archive holds. The chunks
                # already built stay playable; the leg is simply shorter than
                # asked for, which is the truth about that camera.
                log.debug("leg %s ran out of footage at chunk %d", job.id, index)
                break

            self._process(raw, out, job)
            raw.unlink(missing_ok=True)

            job.chunks.append(Chunk(
                index=index, path=out, start=at,
                seconds=(until - at).total_seconds(),
            ))
            at = until
            index += 1

        job.chunks_total = max(job.chunks_total, len(job.chunks)) or 1
        job.state = "done"
        self._retain()

    def _process(self, raw: Path, out: Path, job: LegJob) -> None:
        """Outline the people, and burn it in.

        Burnt in rather than sent as coordinates because a chunk has to be
        evidence on its own: an mp4 somebody can open next week, on a machine
        with no console, and still see what was being pointed at. An overlay
        that needs this page to render is not that.
        """
        if self.detector is None:
            # No model loaded. The video is still the video — playing it with
            # nothing drawn on it is honest, and saying "we could not outline
            # anybody" is better than not showing the footage at all.
            shutil.move(str(raw), str(out))
            return

        capture = cv2.VideoCapture(str(raw))
        if not capture.isOpened():
            shutil.move(str(raw), str(out))
            return

        fps = capture.get(cv2.CAP_PROP_FPS) or 15.0
        width = int(capture.get(cv2.CAP_PROP_FRAME_WIDTH) or 0)
        height = int(capture.get(cv2.CAP_PROP_FRAME_HEIGHT) or 0)
        writer = _writer(out, fps, width, height)

        try:
            while True:
                ok, frame = capture.read()
                if not ok:
                    break
                for person in self.detector.detect(frame):
                    x = int(person.x * width)
                    y = int(person.y * height)
                    w = int(person.w * width)
                    h = int(person.h * height)
                    cv2.rectangle(frame, (x, y), (x + w, y + h), AMBER, 2)
                if writer is not None:
                    writer.write(frame)
        finally:
            capture.release()
            if writer is not None:
                writer.release()

        if not out.is_file() or out.stat().st_size == 0:
            shutil.move(str(raw), str(out))

    # -- retention ----------------------------------------------------------

    def _retain(self) -> None:
        """Keep the last N legs per camera. A leg is always re-derivable."""
        with self._lock:
            by_camera: dict[str, list[str]] = {}
            for job_id in self._order:
                job = self._jobs.get(job_id)
                if job is not None and job.state in ("done", "failed"):
                    by_camera.setdefault(job.camera_id, []).append(job_id)

            drop: list[str] = []
            for job_ids in by_camera.values():
                drop.extend(job_ids[: max(0, len(job_ids) - self.keep_legs)])

            for job_id in drop:
                job = self._jobs.pop(job_id, None)
                if job_id in self._order:
                    self._order.remove(job_id)
                if job is not None:
                    shutil.rmtree(self.root / job.id, ignore_errors=True)


# ---------------------------------------------------------------------------
# what to warm up next
# ---------------------------------------------------------------------------

def next_to_warm(
    anchors: list, index: int, cameras: list, current_camera: str,
) -> str | None:
    """Which camera the operator is most likely to want next.

    Three steps, in order, and it stops at the first that answers:

      1. the next anchor's camera — they were actually seen there, which beats
         any guess about the building
      2. a `neighbours:` camera — somebody said you can walk between these
      3. another camera in the same area — the weakest of the three, and the
         reason it is last

    Returns None rather than a guess when none of the three applies. Warming
    the wrong camera costs a fetch nobody wanted.
    """
    # Only ever a camera this engine is actually running. A `neighbours:`
    # entry can name a camera that has since been removed or switched off, and
    # warming one of those spends a fetch on nothing.
    live = {c.id: c for c in cameras if c.enabled}

    following = anchors[index + 1:] if 0 <= index < len(anchors) else []
    for anchor in following:
        if anchor.camera_id != current_camera and anchor.camera_id in live:
            return anchor.camera_id

    here = live.get(current_camera) or next(
        (c for c in cameras if c.id == current_camera), None)
    if here is None:
        return None

    for neighbour in here.neighbours:
        if neighbour != current_camera and neighbour in live:
            return neighbour

    for camera in live.values():
        if camera.id != current_camera and camera.area == here.area:
            return camera.id
    return None


# ---------------------------------------------------------------------------
# estimates — measured, never guessed
# ---------------------------------------------------------------------------

@dataclass(frozen=True)
class Estimate:
    """How long something will take, and whether it is worth starting."""

    seconds: float
    camera_hours: float
    allowed: bool
    reason: str | None = None
    measured_at: datetime | None = None


def estimate_for(
    camera_hours: float, rates, budget_seconds: float, chunk_seconds: float = 30.0,
) -> Estimate:
    """Work out a wait from what was measured on this machine.

    There is deliberately no fallback. With no measurement the answer is "we
    do not know", because a number typed by a developer on a different machine
    is not an estimate, it is a decoration.
    """
    if rates is None:
        return Estimate(
            seconds=0.0, camera_hours=camera_hours, allowed=False,
            reason=("Nobody has measured how fast this machine reads recorded "
                    "video yet, so there is no honest estimate. Run "
                    "`python engine/tools/measure_track.py` first."),
        )

    video_seconds = camera_hours * 3600.0
    # `fetch_x` is a multiple of real time: 4x means an hour of video arrives
    # in a quarter of an hour.
    fetch = video_seconds / max(0.01, rates.fetch_x)
    # `process_fps` is frames a second, so the frame count has to come from
    # somewhere. SOURCE_FPS is what recorded footage is assumed to run at;
    # measure_track.py measures against the same number, so the two agree even
    # if the assumption is wrong for a particular recorder.
    process = video_seconds * SOURCE_FPS / max(0.01, rates.process_fps)
    total = fetch + process

    if total > budget_seconds:
        return Estimate(
            seconds=total, camera_hours=camera_hours, allowed=False,
            measured_at=rates.measured_at,
            reason=(f"That would take about {total / 60:.0f} minutes, over the "
                    f"{budget_seconds / 60:.0f} minute limit. Narrow the window "
                    f"or pick fewer cameras."),
        )
    return Estimate(
        seconds=total, camera_hours=camera_hours, allowed=True,
        measured_at=rates.measured_at,
    )


# ---------------------------------------------------------------------------
# video helpers
# ---------------------------------------------------------------------------

def _writer(path: Path, fps: float, width: int, height: int):
    if width <= 0 or height <= 0:
        return None
    for code in ("avc1", "mp4v"):
        writer = cv2.VideoWriter(
            str(path), cv2.VideoWriter_fourcc(*code), max(1.0, fps), (width, height)
        )
        if writer.isOpened():
            return writer
        writer.release()
    return None


def _slice(clip: Path, into: Path, offset_seconds: float, seconds: float) -> None:
    """Copy `seconds` of `clip`, starting `offset_seconds` in."""
    capture = cv2.VideoCapture(str(clip))
    if not capture.isOpened():
        raise ArchiveUnavailable(f"{clip.name} cannot be opened.")

    try:
        fps = capture.get(cv2.CAP_PROP_FPS) or 15.0
        width = int(capture.get(cv2.CAP_PROP_FRAME_WIDTH) or 0)
        height = int(capture.get(cv2.CAP_PROP_FRAME_HEIGHT) or 0)
        capture.set(cv2.CAP_PROP_POS_FRAMES, max(0, int(offset_seconds * fps)))

        writer = _writer(into, fps, width, height)
        if writer is None:
            raise ArchiveUnavailable("No usable video encoder is available.")

        wanted = max(1, int(seconds * fps))
        try:
            for _ in range(wanted):
                ok, frame = capture.read()
                if not ok:
                    break
                writer.write(frame)
        finally:
            writer.release()
    finally:
        capture.release()

    if not into.is_file() or into.stat().st_size == 0:
        raise ArchiveUnavailable(f"Nothing could be read out of {clip.name}.")


def _duration_of(clip: Path) -> float:
    capture = cv2.VideoCapture(str(clip))
    if not capture.isOpened():
        return 0.0
    try:
        fps = capture.get(cv2.CAP_PROP_FPS) or 0.0
        frames = capture.get(cv2.CAP_PROP_FRAME_COUNT) or 0.0
        return frames / fps if fps > 0 else 0.0
    finally:
        capture.release()


def _parse(value: str) -> datetime:
    parsed = datetime.fromisoformat(value)
    return parsed if parsed.tzinfo else parsed.replace(tzinfo=timezone.utc)
