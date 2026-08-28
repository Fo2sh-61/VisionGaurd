"""The API server.

Every endpoint maps one-to-one onto a function in web/src/services/api.ts.
No endpoint returns a shape the UI has to reassemble from several calls.

Run it:
    python -m uvicorn vg.api.app:app --reload --port 8000     (from engine/)
    python engine/tools/serve.py                              (from the repo root)

Then http://127.0.0.1:8000/docs for the generated OpenAPI page — that page IS
the frozen contract, and it is what the front end is written against.
"""

from __future__ import annotations

import logging
import os
import threading
from pathlib import Path
from contextlib import asynccontextmanager
from datetime import date, datetime, timedelta, timezone
from typing import Annotated

from fastapi import Depends, FastAPI, File, HTTPException, Query, Request, UploadFile
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import FileResponse, JSONResponse, Response, StreamingResponse

from vg import config as vgconfig
from vg.auth import deps as auth_deps
from vg.api import schemas as S
from vg.clock import clock_for
from vg.api.store import (
    TZ_OFFSET_MINUTES,
    AlreadyBusy,
    MockStore,
    NotAffordable,
    NothingThere,
    Store,
    SubsystemUnavailable,
)
from vg.auth.passwords import WeakPassword
from vg.auth.store import SELF_SIGNUP_ROLE, EmailTaken

log = logging.getLogger(__name__)

# Windows for the three history endpoints, mapped to days. The UI sends its
# own label strings; translating them here keeps that vocabulary out of the store.
WINDOW_DAYS = {
    "Today": 1,
    "Last 7 days": 7,
    "Last 30 days": 30,
    "Last 90 days": 90,
    "This school year": 365,
}

#: The knife page's periods. Seven, not the five in `WINDOW_DAYS`, and three
#: of them are not "N days ago" at all: Today and Yesterday are calendar days
#: at the site, and All has no bound. Kept separate from `WINDOW_DAYS` rather
#: than widening it, because every other page's window genuinely is a rolling
#: number of days and would have to grow a clock to use this.
WEAPON_WINDOWS: tuple[str, ...] = (
    "Today",
    "Yesterday",
    "Last 7 days",
    "Last 30 days",
    "Last 90 days",
    "This school year",
    "All",
)


def weapon_window(label: str, clock, term_from: str | None) -> tuple:
    """A period label to `(since, until)`. Either bound may be None.

    Today and Yesterday are the **site's** calendar days, not the server's: a
    school in Cairo at 00:30 local is still on the previous UTC day, and a
    server-midnight boundary would file last night's entries under this
    morning.

    `term_from` is a string out of `hours.term_from` — possibly empty, and
    possibly not a date anybody typed correctly. An unusable one falls back to
    a rolling year rather than to the epoch: a label reading "this school year"
    must not quietly become "everything ever".
    """
    if label not in WEAPON_WINDOWS:
        raise HTTPException(
            status_code=422,
            detail=f"unknown window {label!r}; expected one of {list(WEAPON_WINDOWS)}",
        )

    now = datetime.now(timezone.utc)
    if label == "All":
        return None, None

    midnight = _local_midnight(now, clock)
    if label == "Today":
        return midnight, None
    if label == "Yesterday":
        return midnight - timedelta(days=1), midnight
    if label == "This school year":
        start = _term_start(term_from, clock)
        return (start if start is not None else now - timedelta(days=365)), None

    days = {"Last 7 days": 7, "Last 30 days": 30, "Last 90 days": 90}[label]
    return now - timedelta(days=days), None


def _local_midnight(when: datetime, clock) -> datetime:
    """The start of the site's day containing `when`, as an instant.

    Solved, not assumed. Turning a local wall-clock time back into an
    instant needs the offset **at that instant**, which on the two days a
    year the clocks change is not the offset now. Using today's offset put
    the start of Today an hour out on those days — and Yesterday's bounds
    moved with it, so an hour of entries appeared in both periods at once or
    in neither.

    One guess, then one correction. The guess uses the current offset; the
    correction re-asks the clock what the offset is at the guessed instant
    and tries again. A second iteration converges because offsets move by
    whole hours and a day is much longer than the jump.
    """
    local = clock.local(when).replace(hour=0, minute=0, second=0, microsecond=0)
    naive_midnight = local.replace(tzinfo=timezone.utc)

    guess = naive_midnight - timedelta(minutes=clock.offset_minutes(when))
    for _ in range(2):
        corrected = naive_midnight - timedelta(
            minutes=clock.offset_minutes(guess))
        if corrected == guess:
            return guess
        guess = corrected
    return guess


def _term_start(term_from: str | None, clock) -> datetime | None:
    """`hours.term_from` as local midnight, or None if it is not a date."""
    if not term_from:
        return None
    try:
        day = date.fromisoformat(term_from.strip())
    except (TypeError, ValueError):
        log.warning("hours.term_from is not a date: %r", term_from)
        return None
    local = datetime(day.year, day.month, day.day, tzinfo=timezone.utc)
    return local - timedelta(minutes=clock.offset_minutes(local))


_store: Store = MockStore()

# Set the instant shutdown begins, before anything else is torn down.
#
# An MJPEG stream is an HTTP connection that never completes by design, and
# uvicorn's graceful shutdown waits for open connections to finish. With a
# camera view open in a browser tab, the server waits for the browser and the
# browser waits for the server — forever. This event is how the stream
# generator learns to stop on its own. See `stream()` below.
SHUTTING_DOWN = threading.Event()


def get_store() -> Store:
    return _store


def set_store(store: Store) -> None:
    """Swap the mock for the live engine. The only line that changes at go-live."""
    global _store
    _store = store


StoreDep = Annotated[Store, Depends(get_store)]


def window_days(label: str) -> int:
    if label not in WINDOW_DAYS:
        raise HTTPException(
            status_code=422,
            detail=f"unknown window {label!r}; expected one of {sorted(WINDOW_DAYS)}",
        )
    return WINDOW_DAYS[label]


@asynccontextmanager
async def lifespan(app: FastAPI):
    """Open the cameras, serve, then shut them down cleanly.

    Set `VG_MOCK=1` to skip capture entirely and serve fixtures — useful for
    front-end work on a machine with no camera attached.
    """
    app.state.registry = None
    try:
        cfg = vgconfig.load()
        app.state.config = cfg
        log.info("loaded config for %s (%d cameras)", cfg.site_name, len(cfg.cameras))
    except vgconfig.ConfigError as exc:
        # A bad config must not stop the API from starting. System Health is the
        # page an operator opens to find out what is broken; it cannot be the
        # page that fails to load because something is broken.
        log.error("config failed to load, serving fixtures: %s", exc)
        app.state.config = None
        cfg = None

    app.state.recogniser = None
    app.state.gallery = None

    # Auth comes up before anything else and independently of every feature.
    # A camera that will not open, a model that will not load, a database that
    # will not migrate - none of them may leave the engine serving requests to
    # people it cannot identify. If this fails, the middleware refuses every
    # request rather than guessing.
    app.state.users = None
    app.state.users_error = None
    try:
        from pathlib import Path

        from vg.auth.store import UserStore

        users_db = vgconfig.REPO_DIR / "engine" / "data" / "visionguard.db"
        if cfg is not None:
            raw_url = str(cfg.storage.database_url).replace("sqlite:///", "")
            candidate = Path(raw_url)
            users_db = candidate if candidate.is_absolute() else vgconfig.REPO_DIR / candidate
        app.state.users = UserStore(users_db)
        if app.state.users.count() == 0:
            # Not a failure - a fresh install. But it is worth saying loudly,
            # because nobody can sign in and the console will look broken.
            log.warning(
                "no accounts exist yet - nobody can sign in. Create the first "
                "administrator with: python engine/tools/create_user.py"
            )
    except Exception as exc:
        log.exception("authentication failed to start")
        app.state.users_error = _reason(exc)
        _reraise_if_strict(exc, "authentication")

    app.state.cameras = None

    # Why a subsystem is not running, in the operator's words. Empty means it
    # is running. These are read by /system/health so a degraded engine says so
    # on the page built to answer that question, rather than only in a log file
    # nobody has open.
    app.state.recognition_error: str | None = None
    app.state.people_error: str | None = None
    app.state.enrolment_error: str | None = None
    app.state.enrolment = None
    app.state.tracking_error: str | None = None
    app.state.tracking = None
    app.state.counts_error: str | None = None
    app.state.counts = None
    app.state.counts_stop = None
    app.state.zones_error: str | None = None
    app.state.zones = None
    app.state.scenes = None
    app.state.weapons_error: str | None = None
    app.state.weapons = None
    app.state.weapon_scenes = None
    app.state.lost_error: str | None = None
    app.state.lost = None
    app.state.vehicles_error: str | None = None
    app.state.vehicles = None
    app.state.vehicle_store = None

    if cfg is not None and os.getenv("VG_MOCK") != "1":
        from pathlib import Path

        from vg.api.live import LiveStore
        from vg.ingest.registry import CameraRegistry
        from vg.ingest.store import CameraStore, merge_cameras

        database = Path(str(cfg.storage.database_url).replace("sqlite:///", ""))
        if not database.is_absolute():
            database = vgconfig.REPO_DIR / database

        # The roster is engine.yaml plus whatever the console has added since.
        # Stored cameras win a clash so an edit made in the UI is not silently
        # reverted by the config file on the next restart.
        cameras = CameraStore(database)
        roster = merge_cameras(cfg.cameras, cameras.all())
        log.info(
            "%d camera(s): %d from engine.yaml, %d added since",
            len(roster), len(cfg.cameras), len(cameras.all()),
        )

        registry = CameraRegistry(roster)
        registry.start()
        ready = registry.wait_for_first_frame(timeout=8.0)
        log.info("%d of %d camera(s) delivering frames", ready, len(registry.workers))
        app.state.registry = registry
        app.state.cameras = cameras

        # The face model and gallery come up first and are shared. Enrolment
        # must work on a machine with no camera and no attendance feature —
        # people are enrolled before cameras are configured, not after.
        (
            face_pipeline,
            face_gallery,
            app.state.enrolment,
            app.state.enrolment_error,
        ) = _start_enrolment(cfg)

        # Two independent workers. Neither requires the other, so a camera set
        # to counting alone is fully served without loading a face model, and
        # an attendance camera never runs the person detector it does not use.
        people, app.state.people_error = _start_people(cfg, registry, roster)

        # Before tracking, because a follow records through it. It needs only
        # the frame bus and a folder, both of which exist by now, and it costs
        # nothing until somebody presses record — no model, no thread.
        from vg.ingest.recorder import Recorder

        app.state.recorder = Recorder(
            registry.bus, cfg.storage.clips_dir, clock=cfg.timezone)

        tracking, app.state.tracking_error = _start_tracking(
            cfg, registry, roster,
            getattr(people, "detector", None),
            recorder=app.state.recorder,
        )
        app.state.tracking = tracking
        (
            counts_store,
            app.state.counts_stop,
            app.state.counts_error,
        ) = _start_counts(cfg, registry, roster, people)
        app.state.counts = counts_store
        # Restricted zones. Shares the person detector; needs no other feature
        # switched on, and a camera nobody restricted costs it nothing.
        (
            app.state.zones,
            app.state.scenes,
            app.state.zones_error,
        ) = _start_zones(
            cfg, registry, roster, getattr(people, "detector", None), cameras,
        )
        # Knife detection. Shares the same person detector, needs no other
        # feature switched on, and every enabled camera is checked.
        (
            app.state.weapons,
            app.state.weapon_scenes,
            app.state.weapons_error,
        ) = _start_weapons(
            cfg, registry, roster, getattr(people, "detector", None),
        )
        # Bag detection. The thread starts but sleeps: work happens only
        # for cameras somebody is actually looking at.
        app.state.lost, app.state.lost_error = _start_lost(cfg, registry, roster)
        # Vehicle gate. Its own two models, shared with nothing - a plate is
        # not a person, so there is no person pass to reuse. The register
        # comes up even when the cameras do not, because a school fills the
        # vehicle list before the gate is wired.
        (
            app.state.vehicles,
            app.state.vehicle_store,
            app.state.vehicles_error,
        ) = _start_vehicles(cfg, registry, roster)
        # Where somebody has been. Written by whichever recognition tier saw
        # them, read by the Track page as one indexed query — which is the
        # whole reason the past-path question is instant.
        from vg.events.anchors import AnchorStore

        anchors = AnchorStore(_database(cfg), cfg.timezone)
        app.state.anchors = anchors

        (
            gallery,
            sightings,
            recogniser,
            app.state.recognition_error,
        ) = _start_recognition(
            cfg, registry, roster, face=(face_pipeline, face_gallery),
            tracking=tracking, anchors=anchors,
        )

        # The second tier. Same class, same gallery, same pipeline — a lower
        # rate and an easier bar, on every camera the first one did not take.
        patrol, app.state.patrol_error = _start_patrol(
            cfg, registry, roster,
            identity_cameras=recogniser.cameras if recogniser else [],
            shared=(face_pipeline, gallery, sightings),
            anchors=anchors,
        )
        app.state.patrol = patrol

        app.state.people = people
        app.state.gallery = gallery
        app.state.recogniser = recogniser

        # The archive runner. Its threads exist from here, but they do nothing
        # at all until somebody asks to watch a stop — an idle engine spends
        # nothing on this.
        app.state.archive, app.state.archive_error = _start_archive(
            cfg, people, face=(face_pipeline, gallery))

        store = LiveStore(
            cfg, registry, gallery, sightings, recogniser, cameras, people,
            tracking=tracking,
            anchors=anchors,
            archive=app.state.archive,
            counts=counts_store,
            recorder=app.state.recorder,
            users=app.state.users,
            scenes=app.state.scenes,
            zones=app.state.zones,
            weapons=app.state.weapons,
            weapon_scenes=app.state.weapon_scenes,
            lost=app.state.lost,
            vehicles=app.state.vehicles,
            vehicle_store=app.state.vehicle_store,
        )
        store.recognition_error = app.state.recognition_error
        store.people_error = app.state.people_error
        store.zones_error = app.state.zones_error
        store.weapons_error = app.state.weapons_error
        store.lost_error = app.state.lost_error
        store.vehicles_error = app.state.vehicles_error
        set_store(store)

        # The banner. A console showing invented attendance next to real camera
        # feeds is worse than one that shows nothing, because there is no way to
        # tell from the screen which it is. If recognition did not come up, say
        # so once, loudly, at the top of the log.
        if not store.recognition_live:
            log.critical(
                "FACE RECOGNITION IS NOT RUNNING - attendance, the people "
                "directory and the live boxes are DEMO FIXTURES, not real "
                "data. Reason: %s",
                app.state.recognition_error or "no camera has the 'attendance' feature",
            )
    else:
        log.info("serving mock fixtures (VG_MOCK=1 or no config)")

    try:
        yield
    finally:
        # FIRST, before any worker is touched. Open MJPEG streams check this
        # every iteration; releasing them is what lets uvicorn's graceful
        # shutdown actually complete instead of waiting on a browser tab.
        SHUTTING_DOWN.set()

        stop_counts = getattr(app.state, "counts_stop", None)
        if stop_counts is not None:
            stop_counts.set()

        # Before the cameras go: an mp4 whose writer was never released is an
        # unplayable one, and it would be the file somebody went looking for.
        recorder = getattr(app.state, "recorder", None)
        if recorder is not None:
            recorder.stop_all()

        # Not a worker: it has no `stop(actor)` signature. Ended here so its
        # thread is joined before the cameras it reads go away underneath it.
        watch = getattr(app.state, "lost", None)
        if watch is not None:
            watch.stop()
        for worker in (
            # Plate reading before the cameras go: a settled plate mid-write
            # would otherwise lose the row the voting already decided to keep.
            getattr(app.state, "vehicles", None),
            # Knife detection first, then zones: stopping either closes any
            # running scene and releases its clip, so the log has no row
            # saying a knife is still in view and no half-written mp4 nobody
            # can play. Knives lead because that is the row an operator is
            # most likely to be looking at when the engine goes down.
            getattr(app.state, "weapons", None),
            getattr(app.state, "zones", None),
            getattr(app.state, "people", None),
            getattr(app.state, "recogniser", None),
            getattr(app.state, "patrol", None),
            getattr(app.state, "tracking", None),
        ):
            if worker is not None:
                worker.stop()
        if app.state.registry is not None:
            app.state.registry.stop()
        # After the workers, never before: a store closed under a running
        # writer is the one way this loses a row it already decided to keep.
        runner = getattr(app.state, "archive", None)
        if runner is not None:
            runner.stop()
        anchor_store = getattr(app.state, "anchors", None)
        if anchor_store is not None:
            anchor_store.close()
        # After the worker that writes into it, for the same reason.
        vehicle_store = getattr(app.state, "vehicle_store", None)
        if vehicle_store is not None:
            vehicle_store.close_db()


# Features that need to know where bodies are. Face recognition is
# deliberately absent: it identifies people, it does not locate or count them.
BODY_FEATURES = {"counting", "intrusion", "track"}


def _start_people(cfg, registry, roster):
    """The shared person detector, and the counting worker that uses it.

    Returns `(worker, error)`. The worker carries `.detector` — the one
    `SharedDetection` every body feature is handed — so bringing it up is
    what makes counting, intrusion, tracking AND knife detection possible.

    **Two different questions, and conflating them broke rule 9.** Whether
    the *detector* is needed is not the same as which cameras the
    *PeopleWorker* watches. This used to load the model only when some
    camera asked for counting, intrusion or track — the set that existed
    before knife detection did. Knife detection consumes the same detector
    on every enabled camera, so a school whose cameras were all `attendance`
    got no knife detection at all, and switching People Counting off
    anywhere turned knives off across the whole site. A feature must never
    require another feature to be switched on.

    So: any enabled camera means the detector is needed. The worker still
    watches only the cameras that asked for a body feature, and watches
    nothing — starting no threads — when none did.

    None with no error means there is nothing enabled to look at, which is
    the one case where loading the model would be pure waste.
    """
    # Zones here are vg.config.ZoneConfig - polygons in frame fractions.

    enabled = [c.id for c in roster if c.enabled]
    if not enabled:
        log.info("no camera is enabled; not loading person detection")
        return None, None

    cameras = [
        c.id for c in roster
        if c.enabled and BODY_FEATURES.intersection(c.features)
    ]

    try:
        from vg.features.people import PeopleWorker
        from vg.infer.persons import PersonDetector
        from vg.infer.shared import SharedDetection

        spec = cfg.models.get("person")
        # Wrapped immediately and never unwrapped. Every body feature is handed
        # the SharedDetection, so counting and tracking on one camera cost one
        # detection pass rather than two, and no two threads can be inside the
        # model at the same time. See vg/infer/shared.py - this is finding F2.
        detector = SharedDetection(PersonDetector(
            weights=spec.weights if spec else None,
            device=spec.device if spec else "auto",
            imgsz=spec.imgsz if spec else 640,
            conf=spec.conf if spec else 0.35,
        ))

        zones = {cid: cfg.zones_for(cid) for cid in cameras}
        rate = min((c.fps for c in roster if c.id in cameras), default=2.0)

        worker = PeopleWorker(
            registry.bus, detector, cameras, zones, rate_hz=rate, boost_hz=12.0
        )
        # A worker with no cameras starts no threads (see FeatureWorker.start)
        # and exists only to carry the shared detector to whoever needs it.
        worker.start()
        if cameras:
            log.info(
                "people on %s - %d zone(s), %.0f Hz idle / 12 Hz watched",
                cameras, sum(len(z) for z in zones.values()), rate,
            )
        else:
            log.info(
                "person model loaded for knife detection; no camera asks "
                "for counting, intrusion or track"
            )
        return worker, None
    except Exception as exc:
        # Counting degrades to unavailable; everything else keeps working.
        log.exception("person detection failed to start")
        _reraise_if_strict(exc, "person detection")
        return None, _reason(exc)


def _start_recognition(cfg, registry, roster=None, face=None, tracking=None,
                       anchors=None):
    """Bring up face recognition on the cameras that ask for it.

    Returns `(gallery, sightings, recogniser, error)`; the first three may be
    None. An operational failure here is not fatal — a missing model file or an
    unreadable database degrades the console to cameras-only rather than taking
    the whole API down with it — but it is never silent: the reason travels back
    to /system/health and to a CRITICAL line in the log.

    Set `VG_STRICT=1` to make any failure fatal instead. Use it in CI and on the
    deployment machine, where a console that quietly serves fixtures is worse
    than one that refuses to start.
    """
    all_cameras = roster if roster is not None else list(cfg.cameras)
    # The identity tier: cameras somebody marked `faces: true`, plus the ones
    # asking for attendance. Attendance is included whatever the flag says,
    # because a register built at the patrol rate would miss arrivals.
    cameras = [
        c.id for c in all_cameras
        if c.enabled and (c.faces or "attendance" in c.features)
    ]
    if not cameras:
        log.info("no camera has the 'attendance' feature or `faces: true`; "
                 "identity recognition is off")
        return None, None, None, None

    try:
        from pathlib import Path

        from vg.events.sightings import SightingStore
        from vg.features.recognition import RecognitionWorker
        from vg.identity.gallery import FaceGallery
        from vg.infer.faces import FacePipeline

        database = Path(str(cfg.storage.database_url).replace("sqlite:///", ""))
        if not database.is_absolute():
            database = vgconfig.REPO_DIR / database

        # Share the pipeline and gallery that enrolment already built. Two
        # FaceGallery objects over the same SQLite file would each keep their
        # own in-memory index, so a person enrolled through the browser would
        # not become recognisable until the next restart.
        if face is not None and face[0] is not None:
            pipeline, gallery = face
        else:
            pipeline = FacePipeline()
            gallery = FaceGallery(
                database, model=pipeline.model_name, threshold=pipeline.threshold
            )

        sightings = SightingStore(database, cfg.timezone)

        if gallery.size == 0:
            # Still start: the console should show that recognition is running
            # with nobody enrolled, which is a different and fixable problem
            # from recognition being broken.
            log.warning(
                "recognition is on but the gallery is empty - nobody can be "
                "recognised. Enrol someone: python engine/tools/enroll.py --name ..."
            )

        # Background rate comes from each camera's configured analytics fps.
        # The boost rate is what a camera runs at while somebody has it open.
        background = min(
            (c.fps for c in all_cameras if c.id in cameras), default=2.0
        )

        # The worker itself. Without this line `recogniser` is undefined, the
        # NameError below is swallowed by the except, and the whole console
        # silently falls back to MockStore fixtures — real cameras, invented
        # attendance. Recognition is the one thing a face model cannot do from
        # the API layer, so it has to be constructed here.
        recogniser = RecognitionWorker(
            registry.bus,
            gallery,
            sightings,
            pipeline=pipeline,
            cameras=cameras,
            rate_hz=background,
            boost_hz=12.0,
            tracking=tracking,
            # The identity tier's bar: these are the cameras people look at
            # from close range. The patrol instance beside this one runs the
            # same class with the easier `tracking.patrol` numbers.
            gates=cfg.tracking.identity,
            anchors=anchors,
        )
        recogniser.start()
        log.info(
            "recognition on %s - %d enrolled, %d faces, %.0f Hz idle / 12 Hz watched",
            cameras, gallery.size, gallery.embedding_count, background,
        )
        return gallery, sightings, recogniser, None

    except Exception as exc:
        log.exception("recognition failed to start; serving cameras only")
        _reraise_if_strict(exc, "face recognition")
        return None, None, None, _reason(exc)


def _start_counts(cfg, registry, roster, people):
    """Headcount history: a background sampler writing one row per area.

    A thread rather than a FeatureWorker, because it consumes no frames — it
    only reads the numbers the people worker has already computed. Daemon, so
    it dies with the process and never holds shutdown open.
    """
    if people is None:
        return None, None, "person detection is not running, so nothing can be counted"

    try:
        import threading
        from pathlib import Path

        from vg.events.counts import SAMPLE_SECONDS, AreaCountStore

        database = Path(str(cfg.storage.database_url).replace("sqlite:///", ""))
        if not database.is_absolute():
            database = vgconfig.REPO_DIR / database

        store = AreaCountStore(database, cfg.timezone)
        stop = threading.Event()

        def sample() -> None:
            while not stop.wait(SAMPLE_SECONDS):
                try:
                    totals: dict[str, int] = {}
                    for camera in roster:
                        if not camera.enabled or not camera.area:
                            continue
                        seen = people.count_on(camera.id)
                        if seen is None:
                            continue
                        totals[camera.area] = totals.get(camera.area, 0) + seen
                    if totals:
                        store.record(totals)
                except Exception:
                    # A failed sample loses one row. It must never kill the
                    # thread, or history silently stops being recorded.
                    log.exception("headcount sample failed")

        thread = threading.Thread(target=sample, name="area-counts", daemon=True)
        thread.start()
        log.info("headcount history recording every %.0fs", SAMPLE_SECONDS)
        return store, stop, None
    except Exception as exc:
        log.exception("headcount history failed to start")
        _reraise_if_strict(exc, "headcount history")
        return None, None, _reason(exc)



def _database(cfg) -> Path:
    """Where the SQLite file actually is.

    The same three lines were written out at seven call sites; this is them,
    once. A relative `database_url` is relative to the repository, not to
    whatever directory the engine happened to be started from.
    """
    raw = Path(str(cfg.storage.database_url).replace("sqlite:///", ""))
    return raw if raw.is_absolute() else vgconfig.REPO_DIR / raw

def _face_finder(cfg, pipeline, gallery):
    """What a sweep looks for in a fetched segment: a face, at the same bar.

    The same `AnchorAccumulator` the live tiers use, applied to recorded
    frames instead of a camera. That is the whole design: one bar for one
    claim, so a hit found by sweeping a Tuesday means exactly what a stop on
    a live path means, and the two can sit in the same list without one of
    them being weaker than it looks.

    Returns None when there is nothing to search with, so the runner can
    refuse the sweep honestly rather than finding nobody and calling it an
    answer.
    """
    if pipeline is None or gallery is None:
        return None

    import cv2

    from vg.events.anchors import AnchorAccumulator, FaceMatch

    def find(clip, camera_id, at, person_id):
        camera = cfg.camera(camera_id)
        gates = cfg.tracking.gates_for(camera) if camera else cfg.tracking.patrol
        accumulator = AnchorAccumulator(gates)

        capture = cv2.VideoCapture(str(clip))
        if not capture.isOpened():
            return []

        fps = capture.get(cv2.CAP_PROP_FPS) or 15.0
        found: dict[tuple, object] = {}
        index = 0
        try:
            while True:
                ok, frame = capture.read()
                if not ok:
                    break
                # Every few frames, not every one. A sweep is looking for
                # somebody being somewhere, and the gate already asks for
                # looks spread over seconds — reading every frame would cost
                # several times as much to answer the same question.
                if index % max(1, int(fps / 2)) == 0:
                    when = at + timedelta(seconds=index / fps)
                    for observation in pipeline.observe(frame):
                        match = gallery.match(observation.embedding, observation.model)
                        if match.person is None:
                            continue
                        if person_id and match.person.id != person_id:
                            continue
                        anchor = accumulator.offer(camera_id, FaceMatch(
                            person_id=match.person.id,
                            score=match.score,
                            runner_up=match.runner_up,
                            face_px=int(min(observation.face.w, observation.face.h)),
                            at=when,
                            model=observation.model,
                        ))
                        if anchor is not None:
                            # Keyed by run, so a person standing in front of
                            # one camera is one hit that grows rather than a
                            # column of near-identical rows.
                            found[(anchor.person_id, anchor.started_at)] = anchor
                index += 1
        finally:
            capture.release()

        return list(found.values())

    return find


def _start_archive(cfg, people, face=None):
    """The recorded-video runner. Absent is a normal, sayable state.

    A site with no DVR and no footage folder simply cannot play back a stop,
    and the Track page says so. That is a different thing from the feature
    being broken, and much better than a button that spins for ever.

    The person detector is shared, not a second one: outlines burnt into a
    chunk come from the same model the live features use.
    """
    try:
        from vg.ingest.archive import ArchiveRunner, backend_for

        # The clock so that "there is no video from then" can name the
        # time the operator actually typed, not its UTC equivalent.
        source = backend_for(
            cfg.archive, cfg.storage.footage_dir, clock_for(cfg.timezone),
            # Operator recordings are recorded video of that camera at that
            # time, which is exactly what the archive is for. Leaving them out
            # meant recording a camera through the console and then being told
            # there was no video of it.
            recordings_dir=cfg.storage.clips_dir)
        runner = ArchiveRunner(
            source,
            clips_dir=cfg.storage.clips_dir,
            chunk_seconds=cfg.archive.chunk_seconds,
            keep_legs=cfg.archive.keep_legs,
            detector=getattr(getattr(people, "detector", None), "detector", None),
            finder=_face_finder(cfg, *(face or (None, None))),
        )
        log.info("archive ready - %s backend, %.0fs chunks",
                 cfg.archive.backend, cfg.archive.chunk_seconds)
        return runner, None

    except Exception as exc:
        log.warning("archive is not available: %s", exc)
        _reraise_if_strict(exc, "the recorded-video archive")
        return None, _reason(exc)


def _start_patrol(cfg, registry, roster, identity_cameras, shared, anchors):
    """The patrol tier: the same recogniser, slowly, on every other camera.

    Not a new class and not a new kind of worker — a second `RecognitionWorker`
    instance with a lower rate and the easier `tracking.patrol` gates. Per-
    camera rates inside one worker would have meant changing `FeatureWorker`,
    which every feature inherits, for the benefit of one consumer.

    It exists so that "where did they go" has an answer at all. The identity
    tier only watches the doorways somebody thought to mark `faces: true`; a
    person crossing a corridor between two of them would otherwise leave no
    trace to read back later.

    Shares the pipeline, gallery and sighting store with the identity tier.
    That is allowed and deliberate: the pipeline is already used concurrently
    by one thread per camera inside a single worker, so a second instance adds
    no new kind of sharing — only more of it.

    `tracking.patrol_hz: 0` switches the whole tier off.
    """
    pipeline, gallery, sightings = shared
    if pipeline is None or gallery is None or sightings is None:
        return None, None

    rate = cfg.tracking.patrol_hz
    if rate <= 0:
        log.info("patrol recognition is switched off (tracking.patrol_hz: 0)")
        return None, None

    all_cameras = roster if roster is not None else list(cfg.cameras)
    cameras = [
        c.id for c in all_cameras
        if c.enabled and c.id not in set(identity_cameras)
    ]
    if not cameras:
        log.info("every enabled camera is in the identity tier; no patrol needed")
        return None, None

    try:
        from vg.features.recognition import RecognitionWorker

        patrol = RecognitionWorker(
            registry.bus,
            gallery,
            sightings,
            pipeline=pipeline,
            cameras=cameras,
            rate_hz=rate,
            # No boost. Nobody watches a patrol camera *through* this tier —
            # if they open one it is the identity work that speeds up, and a
            # boost here would only spend the CPU twice.
            boost_hz=rate,
            gates=cfg.tracking.patrol,
            anchors=anchors,
            name="patrol",
        )
        patrol.start()
        log.info("patrol recognition on %s - %.2f Hz", cameras, rate)
        return patrol, None

    except Exception as exc:
        # Degrades to "no path anchors on those cameras", which the Track page
        # says out loud. It never takes the identity tier down with it.
        log.exception("patrol recognition failed to start")
        _reraise_if_strict(exc, "patrol recognition")
        return None, _reason(exc)

def _start_tracking(cfg, registry, roster, detector, recorder=None):
    """Track-a-person: ByteTrack plus appearance identity, on `track` cameras.

    Takes the person detector that `_start_people` already built rather than
    loading a second copy — one YOLO pass per frame, fanned out (DEV_PLAN
    §3.4). Returns `(worker, error)`; a None worker with a None error simply
    means no camera asked for it.
    """
    cameras = [c.id for c in roster if c.enabled and "track" in c.features]
    if not cameras:
        log.info("no camera has the 'track' feature; tracking is off")
        return None, None

    if detector is None:
        return None, "person detection is not running, so tracking cannot start"

    try:
        from pathlib import Path

        from vg.events.appearance import AppearanceStore
        from vg.features.tracking import TrackingWorker
        from vg.identity.appearance import AppearanceTracker
        from vg.infer.tracking import TrackerPool

        database = Path(str(cfg.storage.database_url).replace("sqlite:///", ""))
        if not database.is_absolute():
            database = vgconfig.REPO_DIR / database

        rate = min((c.fps for c in roster if c.id in cameras), default=2.0)
        worker = TrackingWorker(
            registry.bus,
            detector,
            TrackerPool(frame_rate=rate),
            AppearanceTracker(),
            AppearanceStore(database, cfg.timezone),
            cameras=cameras,
            rate_hz=rate,
            boost_hz=12.0,
            # Without this a follow can be watched but never recorded, and the
            # page correctly-but-uselessly says recording is unavailable on an
            # engine whose recorder is running perfectly well.
            recorder=recorder,
        )
        worker.start()
        log.info("tracking on %s - %.0f Hz idle / 12 Hz watched", cameras, rate)
        return worker, None
    except Exception as exc:
        log.exception("tracking failed to start")
        _reraise_if_strict(exc, "person tracking")
        return None, _reason(exc)


def _start_zones(cfg, registry, roster, detector, cameras_store):
    """Restricted zones: log and record anyone on a camera marked restricted.

    Serves **every enabled camera**, not only the ones with `intrusion` in
    their features. The console's toggle is the switch now, and a toggle that
    silently did nothing on a camera somebody forgot to list in engine.yaml
    would be a dead control on a safety feature — which is worse than the cost
    of an idle thread. A camera nobody restricted returns from `analyse` before
    the detector is touched, so watching all of them is genuinely free.

    Takes the person detector `_start_people` already built. Never a second
    one: `SharedDetection` caches per frame, so counting and zones landing on
    the same frame cost one model pass, not two (P1-01).

    Returns `(worker, scenes, error)`.
    """
    watched = [c.id for c in roster if c.enabled]
    if not watched:
        log.info("no enabled camera; restricted zones are off")
        return None, None, None

    if detector is None:
        # The exact sentence the page shows. Not "unavailable" on its own: an
        # operator cannot fix what they cannot name.
        return None, None, (
            "person detection is not running, so nothing can watch the "
            "restricted areas"
        )

    try:
        from pathlib import Path

        from vg.events.zones import SceneStore
        from vg.features.zones import ZonesWorker
        from vg.ingest.recorder import Recorder

        database = Path(str(cfg.storage.database_url).replace("sqlite:///", ""))
        if not database.is_absolute():
            database = vgconfig.REPO_DIR / database

        scenes = SceneStore(database)
        # A scene left open by a killed process would otherwise show somebody
        # still standing in a restricted area, forever.
        scenes.close_orphans()

        restricted = cameras_store.restricted_ids() if cameras_store else set()
        rate = min((c.fps for c in roster if c.id in watched), default=2.0)

        worker = ZonesWorker(
            registry.bus,
            detector,
            watched,
            scenes,
            # Its OWN recorder, into `clips_dir/zones/`, deliberately not the
            # one behind the operator's record button. Sharing that one would
            # make the two features fight for the same camera: an automatic
            # scene in progress would refuse an operator pressing Record, and
            # the retention rule here (a few clips per camera) would be running
            # over a folder somebody else's files are in. Separate recorders
            # each get their own frame subscription, so both can run at once
            # and neither can stop the other's file.
            recorder=Recorder(
                registry.bus, cfg.storage.zone_clips_dir, clock=cfg.timezone),
            restricted=restricted,
            rate_hz=rate,
            boost_hz=12.0,
        )
        worker.start()
        log.info(
            "restricted zones on %d camera(s), %d switched on - %.0f Hz idle",
            len(watched), len(restricted), rate,
        )
        return worker, scenes, None
    except Exception as exc:
        log.exception("restricted zones failed to start")
        _reraise_if_strict(exc, "restricted zones")
        return None, None, _reason(exc)


def _start_weapons(cfg, registry, roster, detector):
    """Knife detection: look for a knife on the people in view, on every camera.

    Serves **every enabled camera**, not the ones with `weapons` in their
    features. There is no per-camera switch on purpose: a flag would read as
    "knife detection is on here and off there", and a school that thinks a
    corridor is being checked when it is not is worse off than one that knows
    it is not. A camera with nobody in view never reaches the knife model, so
    watching all of them costs one person pass — which counting and zones have
    usually already paid for.

    Takes the person detector `_start_people` already built. Never a second
    one: `SharedDetection` caches per frame, so counting, zones and knives
    landing on the same frame cost one model pass, not three (P1-01).

    Returns `(worker, scenes, error)`. Every failure comes back as a sentence
    for the page rather than an exception — a missing weights file on a fresh
    machine must not take the whole engine down, and it must not be silent
    either (rule 8).
    """
    watched = [c.id for c in roster if c.enabled]
    if not watched:
        log.info("no enabled camera; knife detection is off")
        return None, None, "No camera is running, so nothing is being checked for knives."

    if detector is None:
        # The exact sentence the page shows. Knives are looked for *on people*,
        # so without person detection there is nothing to look at.
        return None, None, (
            "Person detection is not running, so knives cannot be checked - "
            "knives are looked for on people."
        )

    try:
        from vg.events.weapons import WeaponSceneStore
        from vg.features.weapons import WeaponsWorker
        from vg.infer.weapons import WeaponDetector
        from vg.ingest.recorder import Recorder

        spec = cfg.models.get("weapons")
        if spec is None:
            return None, None, "No 'weapons' model is configured in engine.yaml."

        knives = WeaponDetector(
            weights=spec.weights,
            device=spec.device,
            imgsz=spec.imgsz,
            conf=spec.conf,
            iou=spec.iou,
            half=spec.half,
        )

        scenes = WeaponSceneStore(_database(cfg))
        # A scene left open by a killed process would otherwise show a knife
        # still in view, forever, and its half-written file would be offered
        # as a clip.
        scenes.close_orphans()
        # Videos past their retention go now rather than waiting for the
        # first page load, so an engine nobody opens the console on still
        # keeps the promise the page makes.
        scenes.expire(
            datetime.now(timezone.utc)
            - timedelta(days=cfg.storage.clip_retention_days)
        )

        rate = min((c.fps for c in roster if c.id in watched), default=2.0)

        worker = WeaponsWorker(
            registry.bus,
            detector,
            knives,
            watched,
            scenes,
            # Its OWN recorder, into `clips_dir/weapons/`, deliberately not the
            # one behind the operator's record button and not the zones one
            # either. Sharing would make the features fight for the same
            # camera, and a knife clip must never lose to a zone clip.
            recorder=Recorder(
                registry.bus, cfg.storage.weapon_clips_dir, clock=cfg.timezone),
            retention_days=cfg.storage.clip_retention_days,
            rate_hz=rate,
            boost_hz=12.0,
        )
        worker.start()
        log.info(
            "knife detection on %d camera(s) - %s on %s, %.0f Hz idle",
            len(watched), knives.version, knives.device, rate,
        )
        return worker, scenes, None
    except FileNotFoundError as exc:
        # The commonest case by far, and not a bug: a machine without the
        # owner's weights. Say which file, and keep every other feature up.
        log.warning("knife detection is off: %s", exc)
        _reraise_if_strict(exc, "knife detection")
        return None, None, f"Knife detection failed to start ({exc})"
    except Exception as exc:
        log.exception("knife detection failed to start")
        _reraise_if_strict(exc, "knife detection")
        return None, None, f"Knife detection failed to start ({_reason(exc)})"


def _start_vehicles(cfg, registry, roster):
    """Plate reading at the gate cameras, if any are configured.

    Returns `(worker, store, reason)`. A missing weights file or an unset gate
    is payload for the page, never an exception - a fresh machine without the
    owner's plate models must not take the engine down, and must not be silent
    about it either (rule 8).

    **The register comes up even when the cameras do not.** Somebody fills the
    vehicle list before the gate is wired, not after, so the store is opened
    whatever the worker does.
    """
    from vg.events.vehicles import VehicleStore, save_pass_images

    store = VehicleStore(_database(cfg))
    # Plate images past their retention go now rather than waiting for a page
    # load, so an engine nobody opens the console on still keeps the promise.
    store.expire(datetime.now(timezone.utc)
                 - timedelta(days=cfg.storage.clip_retention_days))

    gates = [c for c in roster if c.enabled and c.is_gate]
    if not gates:
        return None, store, (
            "No camera is set up as a gate, so no plates are being read. "
            "A gate camera needs a gate number and a direction.")

    try:
        from vg.features.vehicles import VehiclesWorker
        from vg.infer.plates import PlateReader

        plates = cfg.models.get("plates")
        chars = cfg.models.get("plate_chars")
        if plates is None or chars is None:
            return None, store, (
                "The plate models are not configured in engine.yaml, so no "
                "plate can be read.")

        reader = PlateReader(
            plate_weights=plates.weights,
            char_weights=chars.weights,
            device=plates.device,
            imgsz=plates.imgsz,
            conf=plates.conf,
            iou=plates.iou,
            half=plates.half,
            # Both models, one answer: a reader whose detector is accelerated
            # and whose character model is not is still one reader, and
            # System Health has one row to describe it.
            accelerate=plates.accelerate and chars.accelerate,
        )

        by_camera = {c.id: c for c in gates}
        clock = clock_for(cfg.timezone)

        # The last time old plate images were swept, so a machine nobody
        # opens the console on still keeps the thirty-day promise. Hourly is
        # far more often than needed to be correct and far too rare to cost
        # anything; a list rather than a nonlocal because this is a closure
        # over a camera thread.
        last_sweep = [datetime.now(timezone.utc)]

        def record(camera_id: str, read) -> None:
            """One settled plate becomes one row. Called on a camera thread."""
            camera = by_camera.get(camera_id)
            if camera is None:
                return
            # The photograph first, so its path goes onto the row rather than
            # being attached afterwards. It returns None on any failure - a
            # picture that could not be written must not cost the pass.
            snapshot, crop = save_pass_images(
                cfg.storage.gate_images_dir, camera_id, read.first_seen,
                read.plate, read.image, read.image_box)
            store.record_pass(
                at=read.first_seen,
                camera_id=camera_id,
                gate=camera.gate,
                direction=camera.direction,
                plate=read.plate,
                confidence=read.confidence,
                votes=read.votes,
                needs_review=read.needs_review,
                today=date.fromisoformat(clock.today()),
                snapshot=snapshot,
                plate_crop=crop,
            )

            now = datetime.now(timezone.utc)
            if now - last_sweep[0] >= timedelta(hours=1):
                last_sweep[0] = now
                try:
                    store.expire(
                        now - timedelta(days=cfg.storage.clip_retention_days))
                except Exception:  # noqa: BLE001 - reported, never raised
                    log.exception("could not expire old gate images")

        rate = min((c.fps for c in gates), default=4.0)
        worker = VehiclesWorker(
            registry.bus, reader, [c.id for c in gates],
            on_pass=record, rate_hz=rate, boost_hz=12.0,
            dedupe_seconds=cfg.vehicles.dedupe_seconds,
            near_dedupe_seconds=cfg.vehicles.near_dedupe_seconds,
        )
        worker.start()
        log.info(
            "plate reading on %d gate camera(s) - %s on %s (%s), %.0f Hz idle, "
            "%.0fs repeat window",
            len(gates), reader.version, reader.device, reader.form, rate,
            cfg.vehicles.dedupe_seconds,
        )
        return worker, store, None
    except FileNotFoundError as exc:
        # The commonest case, and not a bug: a machine without the owner's
        # plate weights. Say which file, and keep every other feature up.
        log.warning("plate reading is off: %s", exc)
        _reraise_if_strict(exc, "plate reading")
        return None, store, f"Plate reading failed to start ({exc})"
    except Exception as exc:
        log.exception("plate reading failed to start")
        _reraise_if_strict(exc, "plate reading")
        return None, store, f"Plate reading failed to start ({_reason(exc)})"


def _start_enrolment(cfg):
    """The face model and gallery, built once and shared.

    Deliberately independent of cameras. You enrol people *before* the cameras
    are configured, not after, so enrolment must come up on a machine with no
    camera attached and no `attendance` feature switched on anywhere. Face
    detection and embedding are CPU-only, so this costs no GPU.

    Returns `(pipeline, gallery, service, error)`. All four are None-safe: if
    the model files are missing, enrolment reports why on /system/health and
    every other page keeps working.
    """
    try:
        from pathlib import Path

        from vg.identity.enrolment import EnrolmentService
        from vg.identity.gallery import FaceGallery
        from vg.infer.faces import FacePipeline

        database = Path(str(cfg.storage.database_url).replace("sqlite:///", ""))
        if not database.is_absolute():
            database = vgconfig.REPO_DIR / database

        pipeline = FacePipeline()
        gallery = FaceGallery(
            database, model=pipeline.model_name, threshold=pipeline.threshold
        )
        service = EnrolmentService(gallery, pipeline)

        log.info(
            "enrolment ready - %d enrolled, %d faces (%s)",
            gallery.size, gallery.embedding_count, pipeline.model_name,
        )
        return pipeline, gallery, service, None

    except Exception as exc:
        log.exception("enrolment failed to start")
        _reraise_if_strict(exc, "enrolment")
        return None, None, None, _reason(exc)


def _start_lost(cfg, registry, roster):
    """Bag detection, on whichever cameras somebody is looking at.

    There is no search and no job. The thread starts here but stays asleep: it
    does work only for cameras a tile is currently polling a `lost` overlay
    for, so an operator who is not on the page costs nothing.

    Takes no person detector, on purpose. Knives are looked for on people; a
    lost bag is precisely the one with nobody near it, so the frame goes to the
    model whole and no other feature has to be switched on for this to work
    (rule 9).

    Returns `(search, error)`. Every failure comes back as a sentence for the
    page rather than an exception - a missing weights file on a fresh machine
    must not take the engine down, and it must not be silent either (rule 8).
    """
    if not [c.id for c in roster if c.enabled]:
        log.info("no enabled camera; bag detection has nothing to look at")
        return None, "No camera is running, so there is nothing to check."

    try:
        from vg.features.lostbag import BagWatch
        from vg.infer.bags import BagDetector

        spec = cfg.models.get("bags")
        if spec is None:
            return None, "No 'bags' model is configured in engine.yaml."

        detector = BagDetector(
            weights=spec.weights,
            device=spec.device,
            imgsz=spec.imgsz,
            conf=spec.conf,
            iou=spec.iou,
            half=spec.half,
        )
        watch = BagWatch(registry, detector, clock_for(cfg.timezone))
        # Started, but it does nothing until a tile asks for a bag
        # overlay - the loop sleeps while no camera is being looked at.
        watch.start()
        return watch, None
    except FileNotFoundError as exc:
        # The commonest case by far, and not a bug: a machine without the
        # owner's weights. Say which file, and keep every other feature up.
        log.warning("bag detection is off: %s", exc)
        _reraise_if_strict(exc, "bag detection")
        return None, f"Bag detection failed to start ({exc})"
    except Exception as exc:
        log.exception("bag detection failed to start")
        _reraise_if_strict(exc, "lost bag search")
        return None, f"Bag detection failed to start ({_reason(exc)})"


def _reason(exc: BaseException) -> str:
    """One line an operator can act on, not a traceback."""
    return f"{type(exc).__name__}: {exc}"


def _reraise_if_strict(exc: BaseException, what: str) -> None:
    """Refuse to start rather than serve fixtures, when asked to.

    A NameError or AttributeError in this path is a bug in the engine, not a
    site problem, and degrading past it produces the worst possible outcome: a
    console that looks completely healthy while every number on it is invented.
    Under VG_STRICT the process dies and somebody finds out immediately.
    """
    if os.getenv("VG_STRICT") == "1":
        raise RuntimeError(
            f"{what} failed to start and VG_STRICT=1 is set: {_reason(exc)}"
        ) from exc


def create_app() -> FastAPI:
    app = FastAPI(
        title="VisionGuard engine",
        version="0.1.0",
        summary="The API behind web/ and mobile/. Shapes match services/api.ts.",
        lifespan=lifespan,
    )

    origins = ["http://localhost:5173", "http://localhost:5174",
               "http://127.0.0.1:5173", "http://127.0.0.1:5174"]
    try:
        cfg = vgconfig.load()
        origins = list(cfg.api.cors_origins)
    except vgconfig.ConfigError:
        pass

    app.add_middleware(
        CORSMiddleware,
        allow_origins=origins,
        allow_credentials=True,
        allow_methods=["*"],
        allow_headers=["*"],
    )

    @app.middleware("http")
    async def authenticate(request: Request, call_next):
        """Resolve the caller, and refuse everything that is not public.

        Deny by default, in one place. A per-endpoint decorator is the same
        rule written as a hope: the endpoint somebody forgets to decorate is
        the one that leaks, and nothing about the code would look wrong.

        Roles are still checked per endpoint, because "signed in" and
        "allowed to do this" are different questions. This answers the first.
        """
        request.state.user = auth_deps.user_from(request)

        # CORS preflight carries no credentials by design; blocking it would
        # break the browser before it ever gets to send the real request.
        if request.method == "OPTIONS":
            return await call_next(request)

        if request.state.user is None and not auth_deps.is_public(request.url.path):
            store = getattr(request.app.state, "users", None)
            if store is None:
                # Auth failed to start. Refusing every request is the only
                # safe reading: an engine that cannot check who you are must
                # not guess, and System Health says why.
                return JSONResponse(
                    status_code=503,
                    content={"detail": "Sign-in is unavailable, so nothing can be "
                                       "served. See System Health."},
                )
            return JSONResponse(
                status_code=401,
                content={"detail": "Sign in to use this."},
                headers={"WWW-Authenticate": "Bearer"},
            )

        # Signed in, but is this theirs to do? Enrolment and configuration
        # changes are admin-only, decided from the path so a new endpoint
        # under those prefixes is locked the day it is written.
        user = request.state.user
        if user is not None and auth_deps.requires_admin(request.method,
                                                         request.url.path):
            if not user.is_admin:
                log.warning("%s (%s) was refused %s %s", user.email, user.role,
                            request.method, request.url.path)
                return JSONResponse(
                    status_code=403,
                    content={"detail": "This needs an administrator account."},
                )

        return await call_next(request)

    @app.exception_handler(Exception)
    async def unhandled(request: Request, exc: Exception):
        # Never leak a stack trace to the browser; the UI renders `Problem`.
        log.exception("unhandled error on %s", request.url.path)
        return JSONResponse(
            status_code=500,
            content=S.Problem(error="internal_error",
                              detail="The engine hit an unexpected error.",
                              retryable=True).model_dump(by_alias=True),
        )

    _mount(app)
    return app


# --------------------------------------------------------------------- sign-up
#
# Sign-up is open: anyone who can reach the console can create a working
# account. That is a deliberate product decision, not an oversight, and these
# three helpers are what keep it from being worse than it has to be.

#: Longest values accepted from the sign-up form. Not a validation policy —
#: a bound, so an unauthenticated endpoint cannot be used to write megabytes
#: into the database one field at a time.
MAX_NAME = 80
MAX_EMAIL = 254  # RFC 5321's limit on an address

#: New accounts one address can create in `SIGNUP_WINDOW_SECONDS`. Generous
#: for a real person setting up a colleague, useless for filling the table.
SIGNUP_LIMIT = 5
SIGNUP_WINDOW_SECONDS = 3600


class _SignupThrottle:
    """Per-caller cap on account creation. In memory, and that is enough.

    A restart forgets it, and a caller with many addresses walks around it.
    Both are true, and neither is what this is for: it stops one script from
    turning an open form into a million rows before anybody notices. Anything
    stronger belongs in front of the engine, not inside it.
    """

    def __init__(self) -> None:
        self._seen: dict[str, list[datetime]] = {}
        self._lock = threading.Lock()

    def allow(self, caller: str) -> bool:
        now = datetime.now(timezone.utc)
        cutoff = now - timedelta(seconds=SIGNUP_WINDOW_SECONDS)
        with self._lock:
            recent = [t for t in self._seen.get(caller, []) if t > cutoff]
            if len(recent) >= SIGNUP_LIMIT:
                self._seen[caller] = recent
                return False
            recent.append(now)
            self._seen[caller] = recent
            return True


_signups = _SignupThrottle()


def _looks_like_an_email(value: str) -> bool:
    """The shape of an address, not a proof that it exists.

    Nothing here delivers mail, so a regex that rejects valid addresses would
    only lock real staff out. This catches the empty box and the typed name.
    """
    if len(value) > MAX_EMAIL or any(c.isspace() for c in value):
        return False
    local, _, domain = value.partition("@")
    return bool(local) and bool(domain) and "." in domain and not domain.endswith(".")


def _issue_session(store, user, response: Response) -> S.LoginResult:
    """Start a session and dress it for the wire. One place, two callers.

    The token goes in the body *and* as an HttpOnly cookie. The body is for
    the API client; the cookie exists because the MJPEG camera streams are
    loaded by `<img src=...>`, which cannot send an Authorization header.
    Sign-in and sign-up must set it identically — a sign-up that returned a
    token but no cookie would look like it worked and then show black
    cameras.
    """
    token, expires = store.start_session(user)
    response.set_cookie(
        auth_deps.COOKIE_NAME, token,
        httponly=True,      # page scripts cannot read it
        samesite="strict",  # another site cannot ride it
        max_age=int((expires - datetime.now(timezone.utc)).total_seconds()),
        path="/",
    )
    return S.LoginResult(
        token=token,
        expires_at=S.Instant(
            utc=expires,
            tz_offset_minutes=getattr(get_store(), "_offset", 0),
        ),
        user=S.Account(id=user.id, name=user.name, email=user.email,
                       role=user.role, initials=user.initials),
    )


def _mount(app: FastAPI) -> None:
    # ---------------------------------------------------------------- health
    @app.get("/healthz", tags=["meta"], summary="Liveness probe")
    async def healthz() -> dict:
        """The only endpoint reachable without signing in.

        A load balancer cannot authenticate and still has to tell a running
        engine from a dead one. It says nothing about the site.
        """
        return {"ok": True, "version": app.version}

    # ----------------------------------------------------------------- auth
    @app.post("/auth/login", tags=["auth"], summary="Sign in")
    async def login(request: Request, body: S.LoginRequest, response: Response):
        """Exchange an email and password for a session.

        One failure message for every way this can fail - unknown account,
        wrong password, disabled account. Telling them apart hands an attacker
        a list of real email addresses, and a school's addresses are guessable.

        The token comes back in the body *and* as an HttpOnly cookie. The body
        is for the API client; the cookie exists because the MJPEG camera
        streams are loaded by `<img src=...>`, which cannot send an
        Authorization header.
        """
        store = getattr(request.app.state, "users", None)
        if store is None:
            raise HTTPException(
                status_code=503,
                detail="Sign-in is unavailable. See System Health.",
            )

        user = store.authenticate(body.email, body.password)
        if user is None:
            log.warning("failed sign-in for %r from %s", body.email,
                        request.client.host if request.client else "?")
            raise HTTPException(status_code=401, detail="Email or password is wrong.")

        log.info("%s signed in", user.email)
        return _issue_session(store, user, response)

    @app.post("/auth/register", tags=["auth"], summary="Create an account")
    async def register(request: Request, body: S.RegisterRequest, response: Response):
        """Open sign-up. Creates a working account and signs it in.

        **This endpoint is reachable without a session, by anyone who can
        reach the engine.** That is the shape that was asked for, so the
        limits are what make it survivable:

        * The role is always `SELF_SIGNUP_ROLE` ("it"), fixed here and never
          read from the body. `RegisterRequest` forbids extra fields, so
          sending `"role": "admin"` is a 422, not a promotion. Enrolment,
          sources and user management stay behind `ADMIN_PREFIXES`.
        * The password goes through the same argon2 path and the same
          12-character floor as every other account. There is no weaker rule
          for accounts made this way.
        * `_SignupThrottle` caps how fast one caller can make accounts.

        **The honest cost.** `/auth/login` refuses to say whether an address
        exists; this endpoint has to, because telling somebody their sign-up
        worked when it did not is the thing the constitution forbids outright.
        So an open form is a way to test which addresses are registered. That
        is the trade this design makes, and it is why the sign-up page says
        the same thing in plain words.
        """
        store = getattr(request.app.state, "users", None)
        if store is None:
            raise HTTPException(
                status_code=503,
                detail="Sign-up is unavailable. See System Health.",
            )

        caller = request.client.host if request.client else "?"
        if not _signups.allow(caller):
            log.warning("sign-up rate limit hit from %s", caller)
            raise HTTPException(
                status_code=429,
                detail="Too many accounts created from here. Try again later.",
            )

        name = body.name.strip()
        email = body.email.strip()
        if not name or len(name) > MAX_NAME:
            raise HTTPException(400, f"Enter a name, up to {MAX_NAME} characters.")
        if not _looks_like_an_email(email):
            raise HTTPException(400, "Enter a valid email address.")

        try:
            user = store.create_user(
                email=email, name=name, role=SELF_SIGNUP_ROLE,
                password=body.password,
            )
        except WeakPassword as weak:
            # Its own message carries the length. Inventing one here would
            # let the two drift apart the day the floor moves.
            raise HTTPException(400, str(weak)) from weak
        except EmailTaken as taken:
            raise HTTPException(409, str(taken)) from taken

        log.info("new %s account registered: %s (from %s)", user.role, user.email,
                 caller)
        return _issue_session(store, user, response)

    @app.post("/auth/logout", tags=["auth"], summary="Sign out")
    async def logout(request: Request, response: Response) -> dict:
        """End this session now, server-side.

        Deleting the row is what makes it real. Clearing the cookie alone
        would leave a token that still works if it was captured.
        """
        store = getattr(request.app.state, "users", None)
        if store is not None:
            store.end_session(auth_deps.token_from(request))
        response.delete_cookie(auth_deps.COOKIE_NAME, path="/")
        return {"ok": True}

    @app.get("/auth/me", tags=["auth"], summary="Who am I")
    async def me(user: auth_deps.CurrentUser) -> S.Account:
        """The signed-in account, as the server sees it.

        The console asks this on load instead of trusting its own storage.
        The old build kept the role in localStorage, where the user could
        edit it; this is the answer that counts.
        """
        return S.Account(id=user.id, name=user.name, email=user.email,
                         role=user.role, initials=user.initials)

    @app.get("/site", response_model=S.SiteInfo, tags=["meta"])
    async def get_site(store: StoreDep) -> S.SiteInfo:
        """School name, the site's today, and the live camera tally.

        The app chrome needs these before any page loads, and `today` must be
        server-authoritative — a device with a wrong clock cannot be allowed to
        decide which day an attendance register belongs to.
        """
        return store.site()

    # --------------------------------------------------------------- frames
    @app.get(
        "/cameras/{camera_id}/snapshot",
        tags=["cameras"],
        summary="Latest frame as JPEG",
        response_class=Response,
    )
    async def snapshot(request: Request, camera_id: str) -> Response:
        """The last good frame.

        `X-Frame-Stale: true` marks a frame served from a dropped stream. The
        image is real but not current, and the UI draws NO SIGNAL over it. A
        404 means nothing was ever captured — the tile renders as offline
        rather than showing a black rectangle that looks like a working camera.
        """
        registry = request.app.state.registry
        if registry is None:
            raise HTTPException(404, "no camera capture running")

        worker = registry.worker(camera_id)
        if worker is None:
            raise HTTPException(404, f"no camera {camera_id!r}")

        jpeg = worker.snapshot_jpeg()
        if jpeg is None:
            raise HTTPException(404, f"camera {camera_id!r} has produced no frames")

        return Response(
            content=jpeg,
            media_type="image/jpeg",
            headers={
                "Cache-Control": "no-store",
                "X-Frame-Stale": "true" if worker.status != "ok" else "false",
            },
        )

    @app.get("/cameras/{camera_id}/stream", tags=["cameras"], summary="MJPEG stream")
    async def stream(request: Request, camera_id: str) -> StreamingResponse:
        """Live view for the camera modal.

        MJPEG rather than WebRTC: it is one `<img src>` in the browser with no
        signalling, no codec negotiation and no extra dependency. It is
        bandwidth-hungry, which is fine for one operator watching one camera
        and is why it is not used for the tile grid.
        """
        registry = request.app.state.registry
        if registry is None or registry.worker(camera_id) is None:
            raise HTTPException(404, f"no camera {camera_id!r}")

        worker = registry.worker(camera_id)
        boundary = "vgframe"

        async def frames():
            """Push each new frame as it arrives.

            Waiting on the camera's frame signal rather than sleeping on a timer:
            a fixed `sleep(0.1)` adds up to 100 ms of lag on every frame and caps
            the stream at 10 fps regardless of what the camera can deliver. The
            blocking wait runs in a worker thread so the event loop stays free.
            """
            import asyncio

            last_sequence = -1
            # Two exits: the viewer closed the tab, or the server is stopping.
            # Without the second one this loop outlives Ctrl-C and holds the
            # whole process open.
            while not SHUTTING_DOWN.is_set():
                if await request.is_disconnected():
                    break

                frame = await asyncio.to_thread(
                    worker.source.wait_for_frame, last_sequence, 2.0
                )
                if frame is None:
                    # No new frame within the timeout — the stream is down.
                    # Send the last one so the viewer sees NO SIGNAL over a
                    # still image rather than a dead connection.
                    jpeg = worker.snapshot_jpeg(quality=70, max_width=960)
                    if jpeg is None:
                        break
                else:
                    last_sequence = frame.sequence
                    jpeg = worker.encode_jpeg(frame, quality=70, max_width=960)

                if jpeg:
                    yield (
                        f"--{boundary}\r\nContent-Type: image/jpeg\r\n"
                        f"Content-Length: {len(jpeg)}\r\n\r\n"
                    ).encode() + jpeg + b"\r\n"

        return StreamingResponse(
            frames(),
            media_type=f"multipart/x-mixed-replace; boundary={boundary}",
            headers={"Cache-Control": "no-store"},
        )

    @app.get(
        "/cameras/{camera_id}/detections",
        response_model=S.CameraDetections,
        tags=["cameras"],
        summary="Boxes and headcount for one camera",
    )
    async def detections(
        request: Request,
        camera_id: str,
        store: StoreDep,
        feature: Annotated[
            str | None,
            # Built from the one list rather than typed out again. This
            # shipped without `vehicles` in it, so every plate-box poll came
            # back 422 and no gate tile ever drew a box - the feature's whole
            # overlay, refused by a regex nobody remembered to extend.
            # `test_api.py` pins the list against `_boxes` so the next
            # feature cannot repeat it.
            Query(pattern=S.OVERLAY_FEATURE_PATTERN),
        ] = None,
        colour: Annotated[str | None, Query()] = None,
    ) -> S.CameraDetections:
        """Just the overlay geometry, nothing else.

        The enlarged view watches an MJPEG stream and needs boxes that keep up
        with it. Re-fetching the whole camera payload several times a second to
        get them would drag along names, zones and timestamps that have not
        changed. This is a few hundred bytes and can be polled hard.

        Polling here also *tells the engine somebody is watching*, which raises
        that camera's recognition rate for a couple of seconds. Cameras nobody
        has open stay at the cheap background rate — at 208 cameras, running
        every one at full speed does not fit on any GPU, and would be spent on
        views nobody is looking at.

        Boxes are drawn client-side rather than burned into the JPEG so they
        stay sharp at any size and the pixels remain untouched evidence.
        """
        # Boost the worker whose overlay was actually asked for, and only
        # that one.
        #
        # Recognition used to be boosted on EVERY detections poll, whatever
        # the page wanted. That was affordable while only the enlarged view
        # polled — one camera at a time. The Knife page now draws its overlay
        # on the grid tiles as well, so an unconditional boost would push
        # every camera on screen to the expensive face rate to answer a
        # question about knives. `_boxes` sends weapons to `_knife_boxes` and
        # counting/intrusion to `_person_boxes`; neither reads a face.
        FACE_OVERLAYS = (None, "attendance", "track")
        # `getattr`, like its three siblings below. `app.state` is filled in
        # by the lifespan, so a bare attribute read turns "the engine has
        # not finished starting" into an AttributeError and a 500 - a
        # degradation answered with a 5xx, which is what rule 7 forbids.
        recogniser = getattr(request.app.state, "recogniser", None)
        if feature in FACE_OVERLAYS and recogniser is not None:
            recogniser.note_interest(camera_id)

        # A tracking view that only woke the face model would sit at the
        # cheap background rate and its ids would lag the video.
        tracking = getattr(request.app.state, "tracking", None)
        if feature == "track" and tracking is not None:
            tracking.note_interest(camera_id)

        weapons = getattr(request.app.state, "weapons", None)
        if feature == "weapons" and weapons is not None:
            weapons.note_interest(camera_id)

        # A gate tile that only woke the face model would leave plate reading
        # at the camera's idle rate - 5 Hz on the webcam - while somebody
        # holds a plate up to it. Three frames have to agree before a pass is
        # recorded, so five looks a second is the difference between reading
        # a plate and appearing not to.
        vehicles = getattr(request.app.state, "vehicles", None)
        if feature == "vehicles" and vehicles is not None:
            vehicles.note_interest(camera_id)

        # Bag detection runs for exactly the cameras somebody is looking at,
        # and this poll is what says so. No page open, no poll, no model call -
        # which is the whole of why it costs nothing when nobody is using it.
        if feature == "lost":
            noticed = getattr(store, "note_lost_interest", None)
            if callable(noticed):
                noticed(camera_id)

        reader = getattr(store, "camera_detections", None)
        if callable(reader):
            try:
                return reader(camera_id, feature, colour)
            except TypeError:
                # A store that predates the colour filter (MockStore) still
                # answers the question it does understand.
                return reader(camera_id, feature)
        return S.CameraDetections(camera_id=camera_id)

    @app.get(
        "/cameras/counts",
        response_model=dict[str, int | None],
        tags=["cameras"],
        summary="Live headcount for every camera",
    )
    async def camera_counts(store: StoreDep) -> dict[str, int | None]:
        """Current people per camera, as one small object.

        The grid needs a number that keeps moving, but polling the full camera
        payload per tile would send names, zones, boxes and timestamps over and
        over to update one integer — and would scale with the number of tiles.
        This is one request for the whole page, a few dozen bytes, no matter
        how many cameras are on it.

        `null` means no recent measurement, which is not the same as zero and
        must not be rendered as one. A camera without the `counting` feature is
        always null: nothing is looking.
        """
        counts = getattr(store, "live_counts", None)
        return counts() if callable(counts) else {}

    @app.get("/cameras", response_model=list[S.CameraView], tags=["cameras"])
    async def list_cameras(store: StoreDep) -> list[S.CameraView]:
        live = getattr(store, "live_cameras", None)
        return live() if callable(live) else store.intrusion_cameras()

    # ------------------------------------------------------------- recording
    #
    # Recording is started and stopped by a person, and records from the moment
    # it is asked to - nothing is buffered, so the seconds before the button
    # was pressed do not exist. A refusal comes back 200 with `ok: false` and a
    # reason, because the operator needs to read it next to the button they
    # just pressed, which an HTTP error status cannot deliver.

    @app.get("/cameras/{camera_id}/recording", response_model=S.RecordingResult,
             tags=["cameras"])
    async def get_recording(camera_id: str, store: StoreDep) -> S.RecordingResult:
        """What this camera is doing, or where its last recording went."""
        return store.recording(camera_id)

    @app.post("/cameras/{camera_id}/recording", response_model=S.RecordingResult,
              tags=["cameras"])
    async def start_recording(
        camera_id: str,
        store: StoreDep,
        actor: Annotated[str, Query(description="who pressed record")] = "unknown",
    ) -> S.RecordingResult:
        return store.start_recording(camera_id, actor)

    @app.delete("/cameras/{camera_id}/recording", response_model=S.RecordingResult,
                tags=["cameras"])
    async def stop_recording(
        camera_id: str,
        store: StoreDep,
        actor: Annotated[str, Query(description="who pressed stop")] = "unknown",
    ) -> S.RecordingResult:
        """Waits for the file to be closed before answering.

        Returning early would hand back a path that cannot be opened yet and
        send the operator looking for a file that is still being written.
        """
        return store.stop_recording(camera_id, actor)

    # ------------------------------------------------------------- intrusion
    @app.get("/zones", response_model=list[S.Zone], tags=["intrusion"])
    async def get_zones(store: StoreDep) -> list[S.Zone]:
        """All zones, including disabled ones.

        A paused zone stays visible in the UI, so it is never filtered here.
        """
        return store.zones()

    @app.patch("/zones/{zone_id}", response_model=S.Zone, tags=["intrusion"])
    async def patch_zone(zone_id: str, update: S.ZoneUpdate, store: StoreDep) -> S.Zone:
        zone = store.set_zone_enabled(zone_id, update.enabled)
        if zone is None:
            raise HTTPException(404, f"no zone {zone_id!r}")
        return zone

    @app.get("/breaches", response_model=list[S.Breach], tags=["intrusion"])
    async def get_breaches(
        store: StoreDep,
        window: Annotated[str, Query(description="Today | Last 7 days | Last 30 days")] = "Today",
    ) -> list[S.Breach]:
        return store.breaches(window_days(window))

    @app.get("/breaches/{breach_id}/clip", tags=["intrusion"])
    async def get_breach_clip(breach_id: str, store: StoreDep):
        """Play the clip recorded for one detection.

        Same-origin on purpose: a `<video src>` cannot send an Authorization
        header, so the browser reaches this through the dev proxy exactly the
        way it reaches the camera streams. An absolute engine URL here would
        play for nobody.

        Everything that can go wrong is a 404 carrying the reason in words —
        replaced, failed, never recorded, or a file that is no longer on disk.
        None of them is a 500: the row is data, and a wrong one must not become
        a stack trace or a way to read the disk.
        """
        path, reason = store.clip_for_breach(breach_id)
        if path is None:
            raise HTTPException(404, reason)
        return FileResponse(path, media_type="video/mp4")

    @app.get("/intrusion/cameras", response_model=list[S.CameraView], tags=["intrusion"])
    async def get_intrusion_cameras(store: StoreDep) -> list[S.CameraView]:
        return store.intrusion_cameras()

    # --------------------------------------------------------------- weapons
    @app.get("/weapons/detections", response_model=list[S.WeaponDetection],
             tags=["weapons"])
    async def get_weapons(
        store: StoreDep,
        window: Annotated[str, Query()] = "Last 30 days",
    ) -> list[S.WeaponDetection]:
        """Detection history, dismissed ones included.

        False alarms are retained deliberately — the product's honesty claim
        depends on them staying visible. There is no delete endpoint.
        """
        # The clock is the site's, from the live store when there is one.
        # Demo mode has no store clock and falls back to the configured
        # offset, which is what every other endpoint does.
        clock = getattr(store, "clock", None) or clock_for(TZ_OFFSET_MINUTES)
        hours = getattr(getattr(store, "config", None), "hours", None)
        since, until = weapon_window(
            window, clock, getattr(hours, "term_from", ""))
        return store.weapons(since, until)

    @app.post("/weapons/{detection_id}/review", response_model=S.WeaponDetection,
              tags=["weapons"])
    async def review_weapon(
        detection_id: str, review: S.WeaponReview, store: StoreDep,
        user: auth_deps.CurrentUser,
    ) -> S.WeaponDetection:
        """The human gate. Nothing fans out until this is called.

        The detector alone never triggers a notification, a call or a lock.

        The reviewer is the **signed-in account**, not `review.actor`. The
        body's actor is ignored entirely: a caller must not be able to put
        somebody else's name against a verdict on a weapon.

        Not admin-only. Reviewing is an operator action — `/weapons` is
        deliberately absent from `ADMIN_WRITE_PREFIXES`, so IT support
        watching the cameras at night can clear a false alarm.
        """
        result = store.review_weapon(detection_id, review, reviewer=user.name)
        if result is None:
            # Two causes, one answer: unknown id, or somebody already
            # decided. Neither leaves anything here awaiting a decision.
            raise HTTPException(
                404, f"no detection {detection_id!r} awaiting review")
        return result

    @app.get("/weapons/{detection_id}/clip", tags=["weapons"],
             response_class=FileResponse)
    async def get_weapon_clip(detection_id: str, store: StoreDep):
        """Play the video recorded for one knife detection.

        Same-origin on purpose: a `<video src>` cannot send an Authorization
        header, so the browser reaches this through the dev proxy exactly the
        way it reaches the camera streams. An absolute engine URL here would
        play for nobody.

        Everything that can go wrong is a 404 carrying the reason in words —
        still recording, failed, expired, or a file that is no longer on
        disk. None of them is a 500: the row is data, and a wrong one must
        not become a stack trace or a way to read the disk.
        """
        path, reason = store.clip_for_weapon(detection_id)
        if path is None:
            raise HTTPException(404, reason)
        return FileResponse(path, media_type="video/mp4")

    @app.get("/weapons/cameras", response_model=list[S.CameraView], tags=["weapons"])
    async def get_weapon_cameras(store: StoreDep) -> list[S.CameraView]:
        return store.weapon_cameras()

    # ------------------------------------------------------------ attendance
    @app.get("/attendance", response_model=S.AttendanceResult, tags=["attendance"])
    async def get_attendance(
        store: StoreDep,
        mode: Annotated[str, Query(pattern="^(group|person)$")] = "group",
        subject: Annotated[str, Query()] = "Grade 8",
        date: Annotated[str, Query(description="ISO date")] = "2026-07-29",
    ) -> S.AttendanceResult:
        return store.attendance(mode, subject, date)

    @app.get(
        "/attendance/export",
        tags=["attendance"],
        summary="Attendance register as CSV",
        response_class=Response,
    )
    async def export_attendance(
        store: StoreDep,
        mode: Annotated[str, Query(pattern="^(group|person)$")] = "group",
        subject: Annotated[str, Query()] = "Everyone",
        date: Annotated[str, Query(description="ISO date")] = "2026-07-29",
    ) -> Response:
        """The register for one day, as a spreadsheet.

        Exports what the page shows for that date and nothing more. Each row
        carries the confidence and the camera that made the identification, so
        a disputed mark can be traced back to the evidence rather than taken on
        faith — an attendance record a school acts on has to be auditable.

        Absences are exported as rows too. A register that silently omits the
        people it did not see is unusable as a register.
        """
        import csv
        import io as _io

        result = store.attendance(mode, subject, date)

        buffer = _io.StringIO()
        writer = csv.writer(buffer, lineterminator="\n")
        writer.writerow([
            "date", "name", "person_id", "type", "status",
            "first_seen_local", "minutes_late", "camera", "confidence",
        ])

        offset = 0
        for record in result.records:
            seen_local = ""
            if record.seen_at:
                offset = record.seen_at.tz_offset_minutes
                local = record.seen_at.utc + timedelta(minutes=offset)
                seen_local = local.strftime("%Y-%m-%d %H:%M:%S")

            writer.writerow([
                result.date,
                record.person.name or "",
                record.person.id or "",
                record.person.type.value if record.person.type else "",
                record.status.value,
                seen_local,
                record.minutes_late if record.minutes_late is not None else "",
                record.location or "",
                f"{record.person.confidence:.3f}" if record.person.confidence else "",
            ])

        # A trailing summary so the numbers travel with the rows. Whoever opens
        # this in a week should not have to re-derive the totals.
        writer.writerow([])
        writer.writerow(["expected", result.expected])
        writer.writerow(["present", result.present])
        writer.writerow(["late", result.late])
        writer.writerow(["absent", result.absent])
        writer.writerow(["exported_utc", datetime.now(timezone.utc).isoformat(timespec="seconds")])
        writer.writerow(["timezone_offset_minutes", offset])

        safe = "".join(c if c.isalnum() or c in "-_" else "-" for c in subject)
        filename = f"attendance-{safe}-{result.date}.csv"

        return Response(
            content=buffer.getvalue(),
            media_type="text/csv; charset=utf-8",
            headers={
                "Content-Disposition": f'attachment; filename="{filename}"',
                # Let the browser read the filename we chose on a cross-origin
                # fetch; without this the download is named after the endpoint.
                "Access-Control-Expose-Headers": "Content-Disposition",
            },
        )

    # -------------------------------------------------------------- counting
    @app.get("/count", response_model=S.CountResult, tags=["counting"])
    async def get_count(
        store: StoreDep,
        place: Annotated[str, Query()] = "Cafeteria",
        when: Annotated[str, Query(description="Right now | Today by hour | This week by day")] = "Right now",
    ) -> S.CountResult:
        return store.count(place, when)

    # ----------------------------------------------------------------- track
    @app.post("/track", response_model=S.TrackResult, tags=["track"])
    async def track_person(
        query: S.TrackQuery,
        store: StoreDep,
        actor: Annotated[str, Query(description="who is searching")] = "unknown",
    ) -> S.TrackResult:
        """Reconstruct one person's day across cameras.

        SUPERSEDED by `GET /path/{person}`, and no longer called by this
        console. It rebuilds a path from every stored sighting, including the
        single-frame recognitions that were never good enough to claim; the
        anchor table `/path` reads only ever received stops whose evidence
        cleared the bar, so it cannot return a wrong leg by construction.

        Still served, because wire changes are additive only and something
        outside this repository may still be asking. Nothing here does.

        The audit row is committed BEFORE the result is returned — if the audit
        write fails, the search fails. `TrackResult.audit_id` is the receipt.
        """
        return store.track(query, actor)

    @app.get("/audit", response_model=list[S.AuditEntry], tags=["track"])
    async def get_audit(
        store: StoreDep, limit: Annotated[int, Query(ge=1, le=500)] = 50
    ) -> list[S.AuditEntry]:
        return store.audit(limit)

    # ---------------------------------------------------------------- system
    @app.get("/system/capabilities", response_model=list[S.Capability],
             tags=["system"])
    async def get_capabilities(store: StoreDep) -> list[S.Capability]:
        """What the console can honestly show, and why not otherwise.

        Every page checks this before rendering a number. A page cannot tell an
        empty register from a broken one — both arrive as zero rows — and
        guessing misleads either way: a real empty day read as a fault, or a
        dead subsystem read as "nobody came".

        200 always, like /system/health. A degraded engine is a state the UI
        renders, not an error it has to handle.
        """
        return store.capabilities()

    @app.get("/system/health", response_model=S.SystemHealth, tags=["system"])
    async def get_health(store: StoreDep) -> S.SystemHealth:
        """Degradation arrives as payload, never as a 5xx.

        A camera down or a model unloaded are states the UI renders. This
        endpoint stays 200 even when everything it describes is broken.
        """
        return store.health()

    @app.get("/sources", response_model=list[S.CameraSource], tags=["system"])
    async def get_sources(store: StoreDep) -> list[S.CameraSource]:
        return store.sources()

    @app.post("/sources", response_model=S.CameraSource, tags=["system"], status_code=201)
    async def add_source(req: S.AddCameraRequest, store: StoreDep) -> S.CameraSource:
        """Add a camera and start watching it immediately.

        Persisted to the database, not written back into engine.yaml —
        rewriting a config file from a web request destroys its comments and
        turns a typo into a failed restart. The camera appears on every page
        at once because every page reads the same registry.
        """
        add = getattr(store, "add_camera", None)
        if not callable(add):
            raise HTTPException(503, "camera management needs the live engine")
        try:
            return add(req)
        except ValueError as exc:
            # A bad source string is the operator's typo, not a server fault.
            raise HTTPException(422, str(exc)) from exc

    @app.delete("/sources/{source_id}", tags=["system"], status_code=204)
    async def remove_source(source_id: str, store: StoreDep) -> Response:
        """Stop watching a camera.

        Soft delete: events already recorded against it are kept, because
        removing a camera should not erase the history it produced.
        """
        remove = getattr(store, "remove_camera", None)
        if not callable(remove):
            raise HTTPException(503, "camera management needs the live engine")
        if not remove(source_id):
            raise HTTPException(404, f"no camera {source_id!r}")
        return Response(status_code=204)

    @app.get("/sources/areas", response_model=list[str], tags=["system"])
    async def get_areas(store: StoreDep) -> list[str]:
        return store.areas()

    @app.post("/sources/scan", response_model=list[S.FoundDevice], tags=["system"])
    async def scan_network(store: StoreDep) -> list[S.FoundDevice]:
        return store.scan()

    @app.post("/sources/dvr", response_model=S.DvrConnectResult, tags=["system"])
    async def connect_dvr(
        req: S.DvrConnectRequest, store: StoreDep
    ) -> S.DvrConnectResult:
        """Connect a recorder and enumerate its channels.

        Takes host and credentials — `connectDvr()` in api.ts currently takes no
        arguments, so that signature has to change. The credentials the operator
        types must actually reach the engine.
        """
        return store.connect_dvr(req)

    @app.post("/sources/test", response_model=S.TestConnectionResult, tags=["system"])
    async def test_connection(
        req: S.TestConnectionRequest, store: StoreDep
    ) -> S.TestConnectionResult:
        """Pull one frame from a candidate source.

        A failure comes back 200 with `ok: false` and a reason — the UI shows it
        inline next to the form, which an HTTP error status could not do.
        """
        return store.test_connection(req)

    # ------------------------------------------------------------- tracking
    #
    # The appearance id is the product here. It survives someone leaving the
    # frame and returning, and moving between cameras, without needing a face
    # at any point — so these endpoints exist to get that id onto the screen
    # live, rather than only into the database.

    def _tracking(request: Request):
        return getattr(request.app.state, "tracking", None)

    @app.get("/tracking/live", response_model=S.LiveTracking, tags=["track"])
    async def tracking_live(request: Request) -> S.LiveTracking:
        """Every body the tracker can see right now, on every tracked camera.

        Degradation is payload, not a 5xx: when tracking is not running the
        page shows why instead of an error, exactly like every other subsystem.
        """
        worker = _tracking(request)
        if worker is None:
            return S.LiveTracking(
                running=False,
                reason=getattr(request.app.state, "tracking_error", None)
                or "no camera has the 'track' feature switched on",
            )

        store = get_store()
        registry = request.app.state.registry
        offset = getattr(store, "_offset", 0)

        # Built from the same code that draws the tracking overlay, so the
        # page and the picture can never disagree about who is who. In
        # particular the name comes from a face seen INSIDE this body in this
        # frame — never from a stored binding, which is what previously put one
        # person's name on every body on the camera.
        # Through the store's public overlay, asking as the `track` feature.
        # This was `getattr(store, "_tracked_boxes", None)`, which reached into
        # a private method and quietly produced nothing when the store did not
        # happen to have one.

        out: list[S.TrackedIdentity] = []
        for camera_id in worker.cameras:
            worker.note_interest(camera_id)
            camera = registry.worker(camera_id) if registry else None
            camera_name = camera.config.name if camera else camera_id
            at = camera.last_frame().captured_at if (camera and camera.last_frame()) else None

            for box in store.overlay(camera_id, "track"):
                out.append(S.TrackedIdentity(
                    stable_id=box.track_id or "",
                    camera_id=camera_id,
                    camera_name=camera_name,
                    at=S.Instant(
                        utc=at or datetime.now(timezone.utc),
                        tz_offset_minutes=offset,
                    ),
                    box=box,
                    name=box.label,
                    # APPEARANCE: the body is here because clothing matched.
                    # A readable face is an annotation on top, not the reason.
                    match=S.MatchKind.APPEARANCE,
                ))

        return S.LiveTracking(running=True, cameras=list(worker.cameras), identities=out)

    # ------------------------------------------------------------------ path
    #
    # Operator work like the rest of /tracking, and audited for the same
    # reason: knowing who looked somebody up is the control that matters.

    @app.get("/path/{person}", response_model=S.PathSkeleton, tags=["track"])
    async def path_skeleton(
        person: str,
        store: StoreDep,
        user: auth_deps.CurrentUser,
        date: str | None = None,
        start: str | None = None,
        end: str | None = None,
    ) -> S.PathSkeleton:
        """Where somebody was, answered from the anchor table alone.

        `person` takes an id or a display name, the same rule
        `/people/{person}/history` follows, because names still travel in URLs.

        An empty `anchors` list comes back with a 200. Nobody being identified
        in that window is an answer — a different one from the system being
        unable to look, which is the 503.
        """
        # The SITE's today, never the browser's: a device in another
        # timezone must not decide which day a path is asked about.
        on = date or store.site().today
        try:
            return store.path_skeleton(person, on, user.name, start, end)
        except SubsystemUnavailable as exc:
            raise HTTPException(503, str(exc)) from exc
        except NothingThere as exc:
            raise HTTPException(404, str(exc)) from exc

    @app.post("/path/sweep/estimate", response_model=S.SweepEstimate, tags=["track"])
    async def sweep_estimate(
        req: S.SweepRequest, store: StoreDep, user: auth_deps.CurrentUser,
    ) -> S.SweepEstimate:
        """What that sweep would cost. Nothing runs, and nobody is looked at.

        Not audited on purpose: this is an operator finding out whether the
        question is affordable, not asking it. The audit entry belongs on the
        sweep itself, which is the thing that actually looks at people.
        """
        try:
            return store.sweep_estimate(req)
        except SubsystemUnavailable as exc:
            raise HTTPException(503, str(exc)) from exc
        except NothingThere as exc:
            raise HTTPException(404, str(exc)) from exc

    @app.post("/path/sweep", response_model=S.SweepJob, tags=["track"])
    async def start_sweep(
        req: S.SweepRequest, store: StoreDep, user: auth_deps.CurrentUser,
    ) -> S.SweepJob:
        """Run a sweep, if the same estimate says it is affordable.

        422 rather than 400 when it is too big: the request is well formed and
        the engine understood it perfectly — it is the amount of work that is
        refused, and the reason carries the arithmetic so the operator can
        narrow the window rather than guess.
        """
        try:
            return store.start_sweep(req, user.name)
        except SubsystemUnavailable as exc:
            raise HTTPException(503, str(exc)) from exc
        except NotAffordable as exc:
            raise HTTPException(422, str(exc)) from exc
        except AlreadyBusy as exc:
            raise HTTPException(409, str(exc)) from exc
        except NothingThere as exc:
            raise HTTPException(404, str(exc)) from exc

    @app.post("/path/sweep/stranger", response_model=S.SweepJob, tags=["track"])
    async def follow_stranger(
        req: S.StrangerRequest, store: StoreDep, user: auth_deps.CurrentUser,
    ) -> S.SweepJob:
        """Follow somebody who was never enrolled, from a body in a chunk.

        Every hit comes back as APPEARANCE and carries no name. That is not a
        gap to fill in later: a body matched by the colour of its clothes is
        evidence that the same body moved, and calling that an identification
        is the exact mistake this system is built to avoid.
        """
        try:
            return store.follow_stranger(req.point, req.sweep, user.name)
        except SubsystemUnavailable as exc:
            raise HTTPException(503, str(exc)) from exc
        except NotAffordable as exc:
            raise HTTPException(422, str(exc)) from exc
        except AlreadyBusy as exc:
            raise HTTPException(409, str(exc)) from exc
        except NothingThere as exc:
            raise HTTPException(404, str(exc)) from exc

    @app.get("/path/sweep/{job_id}", response_model=S.SweepJob, tags=["track"])
    async def get_sweep(
        job_id: str, store: StoreDep, user: auth_deps.CurrentUser,
    ) -> S.SweepJob:
        try:
            return store.sweep(job_id)
        except SubsystemUnavailable as exc:
            raise HTTPException(503, str(exc)) from exc
        except NothingThere as exc:
            raise HTTPException(404, str(exc)) from exc

    @app.delete("/path/sweep/{job_id}", response_model=S.SweepJob, tags=["track"])
    async def stop_sweep(
        job_id: str, store: StoreDep, user: auth_deps.CurrentUser,
    ) -> S.SweepJob:
        """Stop it. Stopped means stopped — the hits so far are what it found,
        never dressed up as everything there was."""
        try:
            return store.stop_sweep(job_id, user.name)
        except SubsystemUnavailable as exc:
            raise HTTPException(503, str(exc)) from exc
        except NothingThere as exc:
            raise HTTPException(404, str(exc)) from exc

    @app.post("/path/legs", response_model=S.LegJob, tags=["track"])
    async def start_leg(
        req: S.LegRequest, store: StoreDep, user: auth_deps.CurrentUser,
    ) -> S.LegJob:
        """Fetch and process the video behind one stop.

        Returns immediately with a queued job. Chunks appear in `chunkUrls`
        as they land, and the page plays the first without waiting for the
        last — which is the whole reason this is a job and not a download.

        503 when there is no archive to fetch from, 409 when the runner is
        already doing as much as it will honestly promise.
        """
        try:
            return store.start_leg(req, user.name)
        except SubsystemUnavailable as exc:
            raise HTTPException(503, str(exc)) from exc
        except AlreadyBusy as exc:
            raise HTTPException(409, str(exc)) from exc
        except NothingThere as exc:
            raise HTTPException(404, str(exc)) from exc

    @app.get("/path/legs/{job_id}", response_model=S.LegJob, tags=["track"])
    async def get_leg(
        job_id: str, store: StoreDep, user: auth_deps.CurrentUser,
    ) -> S.LegJob:
        try:
            return store.leg(job_id)
        except SubsystemUnavailable as exc:
            raise HTTPException(503, str(exc)) from exc
        except NothingThere as exc:
            raise HTTPException(404, str(exc)) from exc

    @app.get("/path/legs/{job_id}/chunks/{index}", tags=["track"])
    async def get_leg_chunk(job_id: str, index: int, store: StoreDep):
        """One processed piece of a leg.

        Same-origin for the same reason breach clips are: a `<video src>`
        cannot send an Authorization header, so the browser reaches this
        through the dev proxy exactly as it reaches the camera streams.

        Everything that can go wrong is a 404 with the reason in words —
        not built yet, replaced by newer legs, or a file no longer on disk.
        None of them is a 500: a job id is data, and a wrong one must not
        become a stack trace or a way to read the disk.
        """
        try:
            path, reason = store.leg_chunk(job_id, index)
        except SubsystemUnavailable as exc:
            raise HTTPException(503, str(exc)) from exc
        if path is None:
            raise HTTPException(404, reason)
        return FileResponse(path, media_type="video/mp4")

    # -- following one person, live ------------------------------------------
    #
    # Operator work, not administrator work: an `it` account can follow and
    # record. Every one of these is audited instead, which is the control that
    # actually matters here — knowing who watched whom.
    #
    # Three refusals, three different meanings, and they must not be collapsed:
    #   503  tracking is not running at all
    #   404  nobody is standing where you clicked (try again, they moved)
    #   409  a follow is already open (the reply says which)

    def _follow_or_http(call):
        """Run a store call and turn its refusals into the right status."""
        try:
            return call()
        except SubsystemUnavailable as exc:
            raise HTTPException(503, str(exc)) from exc
        except AlreadyBusy as exc:
            raise HTTPException(409, str(exc)) from exc
        except NothingThere as exc:
            raise HTTPException(404, str(exc)) from exc

    @app.post("/tracking/follow", response_model=S.FollowView, tags=["track"])
    async def follow_start(
        req: S.FollowRequest, store: StoreDep, user: auth_deps.CurrentUser,
    ) -> S.FollowView:
        """Follow whichever body is under that point.

        `x` and `y` are fractions of the frame, so the console never needs to
        know the camera's resolution.
        """
        return _follow_or_http(
            lambda: store.follow_start(req.camera_id, req.x, req.y, user.name)
        )

    @app.get("/tracking/follow", response_model=S.FollowView, tags=["track"])
    async def follow_current(store: StoreDep, user: auth_deps.CurrentUser) -> S.FollowView:
        """The follow as it stands. The page polls this once a second.

        404 when nothing is being followed — that is a state the page handles,
        not an error, and it is how a follow that ended server-side (the timer
        ran out, the track was lost) reaches a browser that was not asked.
        """
        view = store.follow_view()
        if view is None:
            raise HTTPException(404, "Nothing is being followed.")
        return view

    @app.delete("/tracking/follow", response_model=S.FollowView, tags=["track"])
    async def follow_stop(store: StoreDep, user: auth_deps.CurrentUser) -> S.FollowView:
        view = _follow_or_http(lambda: store.follow_end(user.name))
        if view is None:
            raise HTTPException(404, "Nothing is being followed.")
        return view

    @app.post("/tracking/follow/record", response_model=S.FollowView, tags=["track"])
    async def follow_record_start(
        req: S.FollowRecordRequest, store: StoreDep, user: auth_deps.CurrentUser,
    ) -> S.FollowView:
        """Record the followed person, one segment per camera they cross.

        A timer stops it server-side, as does losing the track. Closing the
        tab therefore cannot leave a camera recording, which a web-driven stop
        could not promise.
        """
        return _follow_or_http(
            lambda: store.follow_record_start(req.timer_seconds, user.name)
        )

    @app.delete("/tracking/follow/record", response_model=S.FollowView, tags=["track"])
    async def follow_record_stop(
        store: StoreDep, user: auth_deps.CurrentUser,
    ) -> S.FollowView:
        return _follow_or_http(lambda: store.follow_record_stop(user.name))

    @app.post("/tracking/{stable_id}/correct", tags=["track"], status_code=204)
    async def tracking_correct(stable_id: str, request: Request) -> Response:
        """The operator says this body is not who we claim.

        The rows stay — a body really was there. Only the claim about who it
        was is withdrawn, and the tracker issues a fresh identity so the
        mistake does not travel forward.
        """
        worker = _tracking(request)
        if worker is None:
            raise HTTPException(503, "tracking is not running")
        worker.correct(stable_id)
        return Response(status_code=204)

    # ------------------------------------------------------------- enrolment
    #
    # Photos are staged in memory and only written to the gallery on commit.
    # An abandoned enrolment therefore leaves no trace, and there is never a
    # half-enrolled person who fails recognition for reasons nobody can see.
    #
    # No endpoint here accepts or returns image data beyond the upload itself.
    # The browser keeps its own thumbnails; the engine embeds and drops.

    def _enrolment(request: Request):
        service = getattr(request.app.state, "enrolment", None)
        if service is None:
            reason = getattr(request.app.state, "enrolment_error", None)
            raise HTTPException(
                503,
                reason or "enrolment is not available: the face model did not load",
            )
        return service

    def _session_view(session) -> S.EnrolmentSessionView:
        from vg.identity.enrolment import REQUIRED_PHOTOS

        return S.EnrolmentSessionView(
            id=session.id,
            name=session.name,
            type=session.type,
            person_id=session.person_id,
            group=session.group,
            detail=session.detail,
            photos=[
                S.EnrolmentPhoto(
                    id=p.id, usable=p.usable, score=p.score,
                    face_pixels=p.face_pixels, confidence=p.confidence,
                    similarity=p.similarity, yaw=p.yaw, note=p.note, source=p.source,
                )
                for p in session.photos
            ],
            usable_count=len(session.usable),
            required_count=REQUIRED_PHOTOS,
            ready=session.ready,
            advice=session.advice,
        )

    def _decode(data: bytes):
        """Bytes to BGR, or a 422 the operator can act on."""
        import cv2
        import numpy as np

        if not data:
            raise HTTPException(422, "empty upload")

        image = cv2.imdecode(np.frombuffer(data, np.uint8), cv2.IMREAD_COLOR)
        if image is None:
            raise HTTPException(422, "could not read that image - JPEG or PNG only")
        return image

    def _stamp(when):
        """An instant carrying the SITE's offset for that moment.

        Asked per instant rather than held from startup: an offset cached at
        boot is an hour wrong from the last Friday in October until somebody
        restarts the engine, and nothing says so.
        """
        if when is None:
            return None
        clock = getattr(get_store(), "clock", None)
        offset = clock.offset_minutes(when) if clock is not None else 0
        return S.Instant(utc=when, tz_offset_minutes=offset)

    @app.get("/enrolment/preview/{camera_id}", response_model=S.EnrolmentPreview,
             tags=["enrolment"])
    async def enrolment_preview(camera_id: str, request: Request) -> S.EnrolmentPreview:
        """The faces in the camera's latest frame, for the live overlay.

        Detection runs here, in the request, on the frame the camera already
        has — no worker, no thread, and nothing running at all when nobody is
        on the enrolment page. The console polls this a few times a second
        while a session is open and stops when the page is left.

        No name and no match cross this boundary. The recognition worker's
        boxes were the tempting alternative and are the wrong answer twice
        over: they only exist on cameras with the `attendance` feature, and
        enrolment must work from any camera (a feature may never require
        another one); and they carry names, which an enrolment preview must
        never display.
        """
        service = _enrolment(request)

        registry = getattr(request.app.state, "registry", None)
        worker = registry.worker(camera_id) if registry else None
        if worker is None:
            raise HTTPException(404, f"no camera {camera_id!r}")

        frame = worker.last_frame()
        if frame is None or worker.status != "ok":
            # Could not look, which is a different answer from having looked
            # and found nobody. The page draws NO SIGNAL for this one.
            return S.EnrolmentPreview(camera_id=camera_id, at=None, offline=True)

        return S.EnrolmentPreview(
            camera_id=camera_id,
            at=_stamp(frame.captured_at),
            offline=False,
            faces=[S.PreviewFace(**face) for face in service.preview(frame)],
        )

    @app.post("/enrolment/sessions", response_model=S.EnrolmentSessionView,
              tags=["enrolment"], status_code=201)
    async def start_enrolment(
        req: S.StartEnrolmentRequest, request: Request
    ) -> S.EnrolmentSessionView:
        """Begin enrolling someone. Writes nothing to the gallery."""
        service = _enrolment(request)
        try:
            session = service.start(
                name=req.name, type=req.type.value,
                group=req.group, detail=req.detail, person_id=req.person_id,
            )
        except ValueError as exc:
            raise HTTPException(422, str(exc)) from exc
        return _session_view(session)

    @app.get("/enrolment/sessions/{session_id}",
             response_model=S.EnrolmentSessionView, tags=["enrolment"])
    async def get_enrolment(session_id: str, request: Request) -> S.EnrolmentSessionView:
        session = _enrolment(request).session(session_id)
        if session is None:
            raise HTTPException(404, "no such enrolment session, or it expired")
        return _session_view(session)

    @app.post("/enrolment/sessions/{session_id}/photos",
              response_model=S.EnrolmentSessionView, tags=["enrolment"])
    async def add_enrolment_photo(
        session_id: str, request: Request, file: UploadFile = File(...)
    ) -> S.EnrolmentSessionView:
        """Assess one uploaded photo and stage it if it is worth keeping.

        Returns the whole session rather than just the photo: the advice line
        and the ready flag both depend on the *set*, so returning one photo
        would force the UI to re-fetch immediately every time.

        A rejected photo is a 200 with `usable: false` and a reason, not an
        error status — the operator needs to see why on screen, next to the
        thumbnail, and an HTTP error cannot carry that.
        """
        service = _enrolment(request)
        image = _decode(await file.read())
        try:
            service.add_photo(session_id, image, source=file.filename or "upload")
        except KeyError:
            raise HTTPException(404, "no such enrolment session, or it expired") from None
        return _session_view(service.session(session_id))

    @app.post("/enrolment/sessions/{session_id}/capture",
              response_model=S.EnrolmentSessionView, tags=["enrolment"])
    async def capture_enrolment_photo(
        session_id: str, request: Request, camera_id: str
    ) -> S.EnrolmentSessionView:
        """Take the camera's current frame and assess it.

        Enrolling from the actual entrance camera, at its real mounting angle
        and lighting, produces markedly better recognition than a laptop webcam
        — the enrolment then matches the conditions the person will be seen in.
        """
        service = _enrolment(request)
        registry = request.app.state.registry
        worker = registry.worker(camera_id) if registry else None
        if worker is None:
            raise HTTPException(404, f"no camera {camera_id!r}")

        frame = worker.last_frame()
        if frame is None:
            raise HTTPException(503, f"camera {camera_id!r} has not delivered a frame")

        try:
            service.add_photo(session_id, frame.image, source=f"camera:{camera_id}")
        except KeyError:
            raise HTTPException(404, "no such enrolment session, or it expired") from None
        return _session_view(service.session(session_id))

    @app.delete("/enrolment/sessions/{session_id}/photos/{photo_id}",
                response_model=S.EnrolmentSessionView, tags=["enrolment"])
    async def remove_enrolment_photo(
        session_id: str, photo_id: str, request: Request
    ) -> S.EnrolmentSessionView:
        service = _enrolment(request)
        try:
            if not service.remove_photo(session_id, photo_id):
                raise HTTPException(404, f"no photo {photo_id!r} in this session")
        except KeyError:
            raise HTTPException(404, "no such enrolment session, or it expired") from None
        return _session_view(service.session(session_id))

    @app.post("/enrolment/sessions/{session_id}/commit",
              response_model=S.DirectoryPerson, tags=["enrolment"])
    async def commit_enrolment(session_id: str, request: Request) -> S.DirectoryPerson:
        """Write the person and their vectors to the gallery.

        Refuses below the photo floor with a 422 the UI shows inline. The Save
        button is disabled until `ready`, so reaching this is either a stale tab
        or a direct API call — both deserve the same honest refusal.
        """
        service = _enrolment(request)
        try:
            person = service.commit(session_id)
        except KeyError:
            raise HTTPException(404, "no such enrolment session, or it expired") from None
        except ValueError as exc:
            raise HTTPException(422, str(exc)) from exc

        return S.DirectoryPerson(
            id=person.id, name=person.name, type=S.PersonType(person.type),
            group=person.group, detail=person.detail,
            photo_on_file=person.photo_on_file,
        )

    @app.delete("/enrolment/sessions/{session_id}", tags=["enrolment"],
                status_code=204)
    async def cancel_enrolment(session_id: str, request: Request) -> Response:
        """Discard an enrolment. Nothing was committed, so nothing is undone."""
        if not _enrolment(request).cancel(session_id):
            raise HTTPException(404, "no such enrolment session, or it expired")
        return Response(status_code=204)

    # ------------------------------------------------------------- directory
    @app.get("/people", response_model=list[S.DirectoryPerson], tags=["people"])
    async def get_people(store: StoreDep) -> list[S.DirectoryPerson]:
        return store.people()

    @app.delete("/people/{person_id}", tags=["people"], status_code=204)
    async def remove_person(
        person_id: str, store: StoreDep, user: auth_deps.AdminUser,
    ) -> Response:
        """Remove somebody from the system.

        Administrator-only, enforced by path in `auth/deps.py` whatever this
        console believes, and audited before anything is deleted. Their face
        vectors go with them, so the cameras stop naming them from the next
        frame without a restart.

        Sightings are deliberately kept — stored, unreachable from any page,
        awaiting P3's erasure. Audit entries are never deleted at all.
        """
        try:
            removed = store.remove_person(person_id, user.name)
        except SubsystemUnavailable as exc:
            # Nothing to remove from is not the same answer as no such person.
            # A 404 would send an administrator hunting for somebody who is
            # perfectly present on a system where recognition is not running.
            #
            # Only this exception. Catching RuntimeError at large would dress
            # a genuinely broken delete up as a missing subsystem, and the
            # operator would go looking at the wrong thing.
            raise HTTPException(503, str(exc)) from exc

        if not removed:
            raise HTTPException(404, f"no person {person_id!r}")
        return Response(status_code=204)

    @app.get("/groups", response_model=list[S.GroupSummary], tags=["people"])
    async def get_groups(store: StoreDep) -> list[S.GroupSummary]:
        return store.groups()

    @app.get("/groups/{name}", response_model=S.GroupDetail, tags=["people"])
    async def get_group(name: str, store: StoreDep) -> S.GroupDetail:
        group = store.group(name)
        if group is None:
            raise HTTPException(404, f"no group {name!r}")
        return group

    @app.get("/people/{person}/history", response_model=S.PersonHistory,
             tags=["people"])
    async def get_history(person: str, store: StoreDep) -> S.PersonHistory:
        """`person` accepts an id or a display name.

        Names are the current key and they travel in URLs, which breaks on
        duplicates. Accepting both lets the UI migrate to ids without a flag day.
        """
        history = store.history(person)
        if history is None:
            raise HTTPException(404, f"no person {person!r}")
        return history

    @app.get("/users", response_model=list[S.User], tags=["people"])
    async def get_users(store: StoreDep) -> list[S.User]:
        return store.users()

    # --------------------------------------------------------- vehicle gate
    #
    # Everything under /vehicles is admin-WRITE by path (`auth/deps.py`), so
    # a guard can read the register and the log and change neither. That is
    # one line in one file rather than a decorator per endpoint, because the
    # endpoint somebody forgets to decorate is the one that leaks.

    @app.get("/vehicles/summary", response_model=S.GateSummary, tags=["vehicles"])
    async def vehicle_summary(store: StoreDep) -> S.GateSummary:
        """The Live tiles.

        Always 200, including when nothing is running: the counts are
        optional and `reason` carries the why. A tile with no number renders
        that reason; a tile showing 0 would be claiming a measurement.
        """
        return store.vehicle_summary()

    @app.get("/vehicles/passes", response_model=list[S.VehiclePass],
             tags=["vehicles"])
    async def vehicle_passes(
        store: StoreDep,
        limit: int = Query(100, ge=1, le=1000),
        plate: str = "",
        gate: int | None = None,
        direction: str = "",
        status: str = "",
    ) -> list[S.VehiclePass]:
        """The pass log, newest first."""
        return store.vehicle_passes(limit=limit, plate=plate, gate=gate,
                                    direction=direction, status=status)

    @app.get("/vehicles/cameras", response_model=list[S.CameraView],
             tags=["vehicles"])
    async def vehicle_cameras(store: StoreDep) -> list[S.CameraView]:
        """Gate cameras only. A camera with no gate number watches no gate."""
        return store.vehicle_cameras()

    @app.get("/vehicles/reader", response_model=S.GateReaderNow,
             tags=["vehicles"])
    async def vehicle_reader(store: StoreDep, request: Request) -> S.GateReaderNow:
        """Every read attempt, including the ones that came to nothing.

        Readable by any signed-in user: this is the tool for working out
        whether a gate is failing because of the camera, the model, or a
        stopped subsystem, and the person standing at the gate is a guard.

        **Boosts the reader, exactly like a tile overlay poll does.** Without
        it the card sits at the camera's idle rate while somebody watches it
        and three-frames-to-agree never happens - the same failure that made
        plates unreadable from the tiles until 24 Aug. Nothing else here
        wakes plate reading up, so this call has to.
        """
        vehicles = getattr(request.app.state, "vehicles", None)
        if vehicles is not None:
            for camera in getattr(vehicles, "cameras", ()):
                vehicles.note_interest(camera)
        return store.vehicle_reader()

    def _for_day(method, day: str):
        """Call a day-scoped store method, turning a bad date into a 422.

        **Never falls back to today.** A malformed date that quietly returned
        today's figures would answer a question nobody asked, and the operator
        would read Tuesday's chart believing it was the day they picked.
        """
        try:
            return method(day)
        except ValueError:
            raise HTTPException(
                422, f"{day!r} is not a date. Use YYYY-MM-DD.") from None

    @app.get("/vehicles/traffic", response_model=list[S.TrafficHour],
             tags=["vehicles"])
    async def vehicle_traffic(store: StoreDep,
                              day: str = "") -> list[S.TrafficHour]:
        """One day's entries and exits by hour — the Movements chart.

        Hours with nothing in them are absent rather than zero, and a day
        nothing drove through is an empty list. A row of flat bars would be a
        drawing of data that does not exist.
        """
        return _for_day(store.vehicle_traffic, day)

    @app.get("/vehicles/cameras/{camera_id}/crop", tags=["vehicles"])
    async def vehicle_crop(camera_id: str, store: StoreDep) -> Response:
        """A photograph of the plate this camera is reading right now.

        The clearest frame of that car so far, not the latest — the same one
        the pass will be filed with, so what an operator watches is what gets
        recorded.

        404 when no car is in view, which is the ordinary state of a gate and
        not an error; the console simply shows nothing. `no-store` because the
        picture changes as the car moves and a cached crop of the last car
        would be exactly the sort of stale-shown-as-live this product refuses.
        """
        crop = store.vehicle_crop(camera_id)
        if crop is None:
            raise HTTPException(404, "No car is being read at this camera.")
        return Response(content=crop, media_type="image/jpeg",
                        headers={"Cache-Control": "no-store"})

    @app.get("/vehicles/alerts", response_model=list[S.GateAlert],
             tags=["vehicles"])
    async def vehicle_alerts(store: StoreDep) -> list[S.GateAlert]:
        """Today's passes still waiting for a person, newest first.

        Facts, not sentences: the console builds the wording from these
        fields, because `format.ts` owns every rendered string.
        """
        return store.vehicle_alerts()

    @app.post("/vehicles/alerts/{pass_id}/dismiss", tags=["vehicles"])
    async def dismiss_alert(pass_id: str, store: StoreDep,
                            user: auth_deps.CurrentUser,
                            action_taken: bool = False) -> dict:
        """Clear one alert, under the name of whoever cleared it.

        **The one write under `/vehicles` a guard may make**, carved out by
        path in `auth/deps.py`. The person standing at the gate is a guard,
        and an alert that only an administrator can clear piles up all shift
        until nobody reads it. What a guard still cannot do is act on it:
        registering a car or renewing a permit are register writes and stay
        administrator-only.

        409, not 404, on a second dismissal: the alert existed and somebody
        has already dealt with it, which is a different fact from "no such
        pass" and reads differently to whoever hits it.
        """
        try:
            cleared = store.dismiss_alert(pass_id, user.name, action_taken)
        except SubsystemUnavailable as exc:
            # "Nothing is running" is not the same answer as "not found", and
            # neither is a 500. Rule 7: degradation is payload with a reason.
            raise HTTPException(503, str(exc)) from exc
        except KeyError:
            raise HTTPException(404, f"no pass {pass_id!r}") from None
        if not cleared:
            raise HTTPException(409, "That alert has already been dismissed.")
        return {"ok": True}

    @app.get("/vehicles/passes/{pass_id}/snapshot", tags=["vehicles"])
    async def vehicle_snapshot(pass_id: str, request: Request):
        """The photograph kept with one pass.

        404 when the image has aged out at thirty days. **The pass itself
        still exists** - the time, gate, plate and status are the record and
        are kept for good, so this is "the photo is gone", never "the pass is
        gone".
        """
        store = getattr(request.app.state, "vehicle_store", None)
        if store is None:
            raise HTTPException(503, "The vehicle log is not available.")

        record = store.pass_by_id(pass_id)
        if record is None:
            raise HTTPException(404, f"no pass {pass_id!r}")
        if not record.snapshot or not Path(record.snapshot).is_file():
            raise HTTPException(
                404, "The photograph for this pass has passed its retention "
                     "and been deleted. The pass itself is kept.")
        return FileResponse(record.snapshot, media_type="image/jpeg")

    @app.get("/vehicles/register", response_model=list[S.RegisteredVehicle],
             tags=["vehicles"])
    async def vehicle_register(store: StoreDep, q: str = "",
                               category: str = "") -> list[S.RegisteredVehicle]:
        """The register. A guard may read it; only an admin may change it."""
        return store.vehicle_register(q, category)

    @app.get("/vehicles/template", tags=["vehicles"])
    async def vehicle_template():
        """The blank import template, with one example row.

        A CSV rather than an .xlsx: Excel opens it, LibreOffice opens it, and
        it needs no library to produce - so downloading the template works on
        a machine where the importer itself would not.
        """
        from vg.events.vehicles import template_csv

        return Response(
            content=template_csv(),
            media_type="text/csv",
            headers={"Content-Disposition":
                     "attachment; filename=vehicle-register-template.csv"},
        )

    @app.post("/vehicles/register", response_model=S.RegisteredVehicle,
              status_code=201, tags=["vehicles"])
    async def add_vehicle(body: S.VehicleRegistration,
                          store: StoreDep, user: auth_deps.CurrentUser):
        """Register a vehicle. 409 when that plate is already on the list."""
        from vg.events.vehicles import PlateTaken

        try:
            return store.add_vehicle(body, user.name)
        except PlateTaken as taken:
            raise HTTPException(409, str(taken)) from taken
        except ValueError as bad:
            raise HTTPException(400, str(bad)) from bad

    @app.patch("/vehicles/register/{vehicle_id}",
               response_model=S.RegisteredVehicle, tags=["vehicles"])
    async def edit_vehicle(vehicle_id: str, body: S.VehicleRegistration,
                           store: StoreDep, user: auth_deps.CurrentUser):
        """Change an entry. Applies from the car's next pass; recorded passes
        are not altered."""
        from vg.events.vehicles import PlateTaken

        try:
            updated = store.edit_vehicle(vehicle_id, body, user.name)
        except PlateTaken as taken:
            raise HTTPException(409, str(taken)) from taken
        except ValueError as bad:
            raise HTTPException(400, str(bad)) from bad
        if updated is None:
            raise HTTPException(404, f"no vehicle {vehicle_id!r}")
        return updated

    @app.delete("/vehicles/register/{vehicle_id}", tags=["vehicles"])
    async def remove_vehicle(vehicle_id: str, store: StoreDep,
                             user: auth_deps.CurrentUser) -> dict:
        """Remove an entry. **The car's passes are kept.**

        From its next pass it is logged as not registered. It still passes and
        is still photographed - the software never blocks anything.
        """
        if not store.remove_vehicle(vehicle_id, user.name):
            raise HTTPException(404, f"no vehicle {vehicle_id!r}")
        return {"ok": True}

    @app.get("/vehicles/import/last", response_model=S.VehicleImportRun,
             tags=["vehicles"])
    async def last_import(store: StoreDep) -> S.VehicleImportRun:
        """The most recent register import.

        **404 when nobody has ever imported anything**, and that is the point:
        the console then shows no "last import" line at all rather than a row
        of zeros. "0 rows imported" reads as a failed import rather than as an
        import that never happened.
        """
        run = store.last_import()
        if run is None:
            raise HTTPException(404, "Nothing has been imported yet.")
        return run

    @app.post("/vehicles/import", response_model=S.VehicleImportResult,
              tags=["vehicles"])
    async def import_vehicles(store: StoreDep, user: auth_deps.CurrentUser,
                              file: UploadFile = File(...)):
        """Load a spreadsheet into the register.

        Never partial-silent: the result names every rejected row and why, so
        an office cannot believe a list is loaded and find out at the gate.
        """
        data = await file.read()
        try:
            return store.import_vehicles(file.filename or "upload.csv",
                                         data, user.name)
        except RuntimeError as exc:
            # openpyxl absent. Say which format still works rather than 500.
            raise HTTPException(400, str(exc)) from exc


    @app.get("/vehicles/gates", response_model=list[S.GateTotals],
             tags=["vehicles"])
    async def vehicle_gates(store: StoreDep,
                            day: str = "") -> list[S.GateTotals]:
        """Today, gate by gate.

        `pairingAvailable` is false for a gate with no exit camera, and
        `inside` is then absent. The page says why instead of printing a
        figure it cannot stand behind.
        """
        return _for_day(store.vehicle_gates, day)

    @app.get("/vehicles/inside", response_model=list[S.VehicleVisit],
             tags=["vehicles"])
    async def vehicles_inside(store: StoreDep) -> list[S.VehicleVisit]:
        """Cars seen entering today and not seen leaving.

        Derived from the passes, never stored, so it cannot drift out of step
        with the log it is computed from.
        """
        return store.vehicles_inside()

    @app.get("/vehicles/visits", response_model=list[S.VehicleVisit],
             tags=["vehicles"])
    async def vehicle_visits(store: StoreDep,
                             day: str = "") -> list[S.VehicleVisit]:
        """Today's completed visits. `inferred` marks an exit nobody saw."""
        return _for_day(store.vehicle_visits, day)

    @app.delete("/vehicles/passes/{pass_id}", tags=["vehicles"])
    async def delete_pass(pass_id: str, store: StoreDep,
                          user: auth_deps.CurrentUser) -> dict:
        """Remove one pass, its photograph and its plate crop.

        Administrator only, by the same path rule as the rest of `/vehicles`:
        a guard reads the gate log, an administrator changes it.

        **Permanent.** "Inside now" and the visit list are computed from the
        pass table, so a row kept hidden would go on answering questions after
        somebody deleted it. The audit entry is written before the row goes
        and cannot itself be deleted, which is how the log can lose a row
        without the system losing the knowledge that it did.
        """
        if not store.delete_pass(pass_id, user.name):
            raise HTTPException(404, f"no pass {pass_id!r}")
        return {"ok": True}

    @app.post("/vehicles/export", tags=["vehicles"], response_class=Response)
    async def export_passes(
        store: StoreDep,
        user: auth_deps.CurrentUser,
        limit: int = Query(5000, ge=1, le=50000),
        plate: str = "",
        gate: int | None = None,
        direction: str = "",
        status: str = "",
        day: str = "",
    ) -> Response:
        """The pass log as a spreadsheet.

        A POST, deliberately. P6-FR-023 requires the audit entry to be
        written before the file is handed over, and a GET that writes is a
        GET that lies about being safe. `SAFE_METHODS` in `auth/deps.py` is
        also what decides admin-write, so a GET export would have been
        readable by a guard *and* unaudited.
        """
        try:
            body = store.export_passes(
                user.name, limit=limit, plate=plate, gate=gate,
                direction=direction, status=status, day=day)
        except ValueError:
            raise HTTPException(
                422, f"{day!r} is not a date. Use YYYY-MM-DD.") from None
        stamp = datetime.now(timezone.utc).strftime("%Y-%m-%d")
        return Response(
            content=body,
            media_type="text/csv; charset=utf-8",
            headers={
                "Content-Disposition":
                    f'attachment; filename="vehicle-passes-{stamp}.csv"',
                "Access-Control-Expose-Headers": "Content-Disposition",
            },
        )
    # ------------------------------------------------------------- attention
    @app.get("/attention", response_model=list[S.AttentionItem], tags=["home"])
    async def get_attention(store: StoreDep) -> list[S.AttentionItem]:
        return store.attention()

    @app.post("/attention/{item_id}/ack", response_model=S.AttentionItem,
              tags=["home"])
    async def ack_attention(
        item_id: str, ack: S.Acknowledgement, store: StoreDep
    ) -> S.AttentionItem:
        item = store.acknowledge(item_id, ack.actor)
        if item is None:
            raise HTTPException(404, f"no attention item {item_id!r}")
        return item

    # -------------------------------------------------------------- settings
    @app.get("/settings/school", response_model=S.SchoolProfile, tags=["settings"])
    async def get_school(store: StoreDep) -> S.SchoolProfile:
        return store.school_profile()

    @app.get("/settings/alerts", response_model=list[S.AlertRule], tags=["settings"])
    async def get_alerts(store: StoreDep) -> list[S.AlertRule]:
        return store.alert_rules()

    @app.get("/settings/delivery", response_model=list[S.DeliveryTarget],
             tags=["settings"])
    async def get_delivery(store: StoreDep) -> list[S.DeliveryTarget]:
        return store.delivery_targets()


app = create_app()
