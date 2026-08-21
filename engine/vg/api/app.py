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
from contextlib import asynccontextmanager
from datetime import datetime, timedelta, timezone
from typing import Annotated

from fastapi import Depends, FastAPI, File, HTTPException, Query, Request, UploadFile
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import FileResponse, JSONResponse, Response, StreamingResponse

from vg import config as vgconfig
from vg.auth import deps as auth_deps
from vg.api import schemas as S
from vg.api.store import MockStore, Store, SubsystemUnavailable

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
        tracking, app.state.tracking_error = _start_tracking(
            cfg, registry, roster,
            getattr(people, "detector", None),
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
        (
            gallery,
            sightings,
            recogniser,
            app.state.recognition_error,
        ) = _start_recognition(
            cfg, registry, roster, face=(face_pipeline, face_gallery),
            tracking=tracking,
        )

        app.state.people = people
        app.state.gallery = gallery
        app.state.recogniser = recogniser

        # No model, no thread until somebody presses record. It exists as soon
        # as the cameras do, which is the only thing recording depends on.
        from vg.ingest.recorder import Recorder

        app.state.recorder = Recorder(
            registry.bus, cfg.storage.clips_dir, clock=cfg.timezone)

        store = LiveStore(
            cfg, registry, gallery, sightings, recogniser, cameras, people,
            tracking=tracking,
            counts=counts_store,
            recorder=app.state.recorder,
            users=app.state.users,
            scenes=app.state.scenes,
            zones=app.state.zones,
        )
        store.recognition_error = app.state.recognition_error
        store.people_error = app.state.people_error
        store.zones_error = app.state.zones_error
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

        for worker in (
            # Zones first: stopping it closes any running scene and releases
            # its clip, so the log has no row saying somebody is still standing
            # there and no half-written mp4 nobody can play.
            getattr(app.state, "zones", None),
            getattr(app.state, "people", None),
            getattr(app.state, "recogniser", None),
            getattr(app.state, "tracking", None),
        ):
            if worker is not None:
                worker.stop()
        if app.state.registry is not None:
            app.state.registry.stop()


# Features that need to know where bodies are. Face recognition is
# deliberately absent: it identifies people, it does not locate or count them.
BODY_FEATURES = {"counting", "intrusion", "track"}


def _start_people(cfg, registry, roster):
    """Person detection for counting, intrusion and tracking.

    Returns `(worker, error)`. The worker is None when no camera asks for any
    of these — in which case the person model is never loaded at all, and the
    error is None because nothing is wrong.
    """
    # Zones here are vg.config.ZoneConfig - polygons in frame fractions.

    cameras = [
        c.id for c in roster
        if c.enabled and BODY_FEATURES.intersection(c.features)
    ]
    if not cameras:
        log.info("no camera needs person detection; not loading it")
        return None, None

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
        worker.start()
        log.info(
            "people on %s - %d zone(s), %.0f Hz idle / 12 Hz watched",
            cameras, sum(len(z) for z in zones.values()), rate,
        )
        return worker, None
    except Exception as exc:
        # Counting degrades to unavailable; everything else keeps working.
        log.exception("person detection failed to start")
        _reraise_if_strict(exc, "person detection")
        return None, _reason(exc)


def _start_recognition(cfg, registry, roster=None, face=None, tracking=None):
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
    cameras = [c.id for c in all_cameras if c.enabled and "attendance" in c.features]
    if not cameras:
        log.info("no camera has the 'attendance' feature; recognition is off")
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


def _start_tracking(cfg, registry, roster, detector):
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

        token, expires = store.start_session(user)
        response.set_cookie(
            auth_deps.COOKIE_NAME, token,
            httponly=True,      # page scripts cannot read it
            samesite="strict",  # another site cannot ride it
            max_age=int((expires - datetime.now(timezone.utc)).total_seconds()),
            path="/",
        )
        log.info("%s signed in", user.email)
        return S.LoginResult(
            token=token,
            expires_at=S.Instant(
                utc=expires,
                tz_offset_minutes=getattr(get_store(), "_offset", 0),
            ),
            user=S.Account(id=user.id, name=user.name, email=user.email,
                           role=user.role, initials=user.initials),
        )

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
            Query(pattern="^(attendance|track|counting|intrusion|weapons)$"),
        ] = None,
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
        recogniser = request.app.state.recogniser
        if recogniser is not None:
            recogniser.note_interest(camera_id)

        # Boost whichever worker serves this page's overlay, not just
        # recognition — a tracking view that only woke the face model would sit
        # at the cheap background rate and its ids would lag the video.
        tracking = getattr(request.app.state, "tracking", None)
        if feature == "track" and tracking is not None:
            tracking.note_interest(camera_id)

        reader = getattr(store, "camera_detections", None)
        if callable(reader):
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
        return store.weapons(window_days(window))

    @app.post("/weapons/{detection_id}/review", response_model=S.WeaponDetection,
              tags=["weapons"])
    async def review_weapon(
        detection_id: str, review: S.WeaponReview, store: StoreDep
    ) -> S.WeaponDetection:
        """The human gate. Nothing fans out until this is called.

        The detector alone never triggers a notification, a call or a lock.
        """
        result = store.review_weapon(detection_id, review)
        if result is None:
            raise HTTPException(404, f"no detection {detection_id!r}")
        return result

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

    # ----------------------------------------------------------- lost items
    @app.post("/lost-items/search", response_model=S.LostResult, tags=["lost-items"])
    async def search_lost(query: S.LostQuery, store: StoreDep) -> S.LostResult:
        """Retrospective search over stored footage. Budget: under a minute.

        Returns a completed job today. When this runs for real it becomes
        POST -> job id -> poll/stream, which the UI's "Searching footage…"
        state is already built for; `LostResult.job` carries the progress.
        """
        return store.search_lost(query)

    # ----------------------------------------------------------------- track
    @app.post("/track", response_model=S.TrackResult, tags=["track"])
    async def track_person(
        query: S.TrackQuery,
        store: StoreDep,
        actor: Annotated[str, Query(description="who is searching")] = "unknown",
    ) -> S.TrackResult:
        """Reconstruct one person's day across cameras.

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
