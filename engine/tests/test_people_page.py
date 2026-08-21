"""The People page, the enrolment preview, and removing a person.

Three things this file holds, all of which the console can only report and
never enforce.

**A row that explains itself.** The directory used to carry a permanently
empty guardian column and a "Photo on file" badge. The replacement — how many
photos, when they were enrolled, where and when they were last seen — is only
honest if the absence of a value stays an absence: `last_seen` is null when
nobody has ever been sighted, never a placeholder that reads like data.

**A preview that never names anyone.** The enrolment page draws a face outline
and its five feature points over a live view. That payload carries geometry
and nothing else. A name there would be recognition leaking into enrolment,
which is the bug that once made every person read as one person.

**Removal that is real.** Admin-only on the server, audited before anything is
deleted, and effective against the same in-memory index the recognition worker
reads — so a removed person stops being named without a restart.
"""

from __future__ import annotations

import tempfile
from datetime import datetime, timedelta, timezone
from pathlib import Path

import numpy as np
import pytest

from vg import config as vgconfig
from vg.api.live import LiveStore
from vg.config import CameraConfig
from vg.events.sightings import Sighting, SightingStore
from vg.identity.gallery import FaceGallery
from vg.ingest.registry import CameraRegistry

CAIRO = 180  # UTC+3, in minutes
MODEL = "sface-2021dec"

#: Configured but not enabled, so the registry knows the camera and its
#: display name without a capture thread ever opening a device.
ENTRANCE = CameraConfig(
    id="cam-entrance", name="Main entrance", source="0", enabled=False,
)


def local(hour: int, minute: int = 0, day: int = 17) -> datetime:
    """A UTC instant that is `hour:minute` in Cairo on 2026-08-`day`."""
    return datetime(2026, 8, day, hour, minute, tzinfo=timezone.utc) - timedelta(
        minutes=CAIRO
    )


def unit(seed: str) -> np.ndarray:
    """A normalised vector. Nothing here recognises faces, it only enrols them."""
    rng = np.random.default_rng(abs(hash(seed)) % (2**32))
    v = rng.standard_normal(128).astype("float32")
    return v / float(np.linalg.norm(v))


@pytest.fixture
def store():
    """A LiveStore with a real gallery, real sightings and a named camera."""
    with tempfile.TemporaryDirectory() as tmp:
        gallery = FaceGallery(Path(tmp) / "g.db", model=MODEL, threshold=0.363)
        sightings = SightingStore(Path(tmp) / "s.db", clock=CAIRO)

        for pid, name, group in [
            ("p-layla", "Layla Ahmed", "Grade 8"),
            ("p-omar", "Omar Khaled", "Grade 8"),
        ]:
            gallery.add_person(pid, name, group=group)
            gallery.add_embedding(pid, unit(pid), MODEL)

        live = LiveStore(
            config=vgconfig.load(), registry=CameraRegistry([ENTRANCE]),
            gallery=gallery, sightings=sightings,
        )
        yield live
        sightings.close()
        gallery.close()


def person(store: LiveStore, name: str):
    return next(p for p in store.people() if p.name == name)


# ---------------------------------------------------------------------------
# US1 - the row explains itself
# ---------------------------------------------------------------------------

class TestDirectoryDetails:
    def test_directory_carries_photos_enrolled_and_last_seen(self, store):
        """PPL-FR-008/010. Everything here is a read of data already held.

        `last_camera` is the camera's display NAME, resolved from the runtime
        roster. The id is what the sighting stores; putting "cam-entrance" on
        a page where the operator typed "Main entrance" is the same class of
        mistake as showing a raw database key.
        """
        store.sightings.record(
            Sighting("p-layla", "cam-entrance", local(7, 42), 0.8, MODEL),
            force=True,
        )

        layla = person(store, "Layla Ahmed")
        assert layla.photos == 1
        assert layla.enrolled_at is not None
        assert layla.last_seen is not None
        assert layla.last_seen.utc == local(7, 42)
        assert layla.last_camera == "Main entrance"

    def test_last_camera_falls_back_to_the_id_when_the_camera_is_gone(self, store):
        """A camera removed since the sighting still has to render something.

        The id is ugly but true. Blank would read as "no camera", which is a
        different claim from "a camera that is no longer configured".
        """
        store.sightings.record(
            Sighting("p-omar", "cam-retired", local(8, 5), 0.8, MODEL), force=True,
        )

        assert person(store, "Omar Khaled").last_camera == "cam-retired"

    def test_never_sighted_person_has_null_last_seen(self, store):
        """Null on the wire; "Not seen yet" in words on the screen.

        A placeholder string here would travel as data — sortable, filterable,
        indistinguishable from a real answer once it leaves this boundary.
        """
        omar = person(store, "Omar Khaled")
        assert omar.last_seen is None
        assert omar.last_camera is None

    def test_a_person_with_no_face_reports_zero_photos(self, store):
        """"Cannot be recognised" is a statement about capability.

        `photos` is the number the sentence is built from, so it has to be a
        real count rather than absent.
        """
        store.gallery.add_person("p-visitor", "Nadia Fouad", type="Visitor")

        nadia = person(store, "Nadia Fouad")
        assert nadia.photos == 0
        assert nadia.photo_on_file is False

    def test_last_seen_is_one_query_not_one_per_person(self, store):
        """The directory is ~2,000 people at target. N+1 here is the whole page.

        `last_seen()` answers for everybody in one call, and `people()` calls
        it once — not once per row.
        """
        real = store.sightings.last_seen
        calls: list[int] = []

        def counted():
            calls.append(1)
            return real()

        store.sightings.last_seen = counted
        store.people()

        assert len(calls) == 1

    def test_guardian_fields_still_on_the_wire_and_always_null(self, store):
        """Additive-only: the fields survive, the engine sends null.

        Enrolment never collects a guardian, so the column was permanently a
        dash. The console stops rendering it; removing it from the wire would
        break an older client for nothing.
        """
        layla = person(store, "Layla Ahmed")
        assert layla.guardian_name is None
        assert layla.guardian_relation is None
        assert layla.guardian_phone is None


# ---------------------------------------------------------------------------
# US2 - the enrolment preview
#
# No camera, no model download, no server thread. The detector is a stand-in
# that returns whatever the test wants to see, because what is under test is
# the conversion and the honesty of the payload, not YuNet.
# ---------------------------------------------------------------------------

from vg.infer.faces import DetectedFace  # noqa: E402
from vg.ingest.source import Frame  # noqa: E402

FRAME_W, FRAME_H = 640, 480


def a_face(x=64, y=48, w=160, h=192, confidence=0.97) -> DetectedFace:
    """A detection in pixels, with the five landmarks YuNet emits."""
    points = np.array(
        [
            [x + w * 0.30, y + h * 0.35],   # right eye
            [x + w * 0.70, y + h * 0.35],   # left eye
            [x + w * 0.50, y + h * 0.55],   # nose
            [x + w * 0.35, y + h * 0.75],   # mouth, right corner
            [x + w * 0.65, y + h * 0.75],   # mouth, left corner
        ],
        dtype=np.float32,
    )
    return DetectedFace(
        x=x, y=y, w=w, h=h, confidence=confidence,
        landmarks=points, raw=np.zeros(15, dtype=np.float32),
    )


class FakeDetector:
    def __init__(self, faces):
        self.faces = list(faces)

    def detect(self, image, min_size=0):
        return list(self.faces)


class FakePipeline:
    """Enough of a `FacePipeline` for the preview: a detector, nothing else.

    The preview never embeds and never matches, so an embedder here would be
    scenery, and its absence is what proves it.
    """

    model_name = MODEL

    def __init__(self, faces=()):
        self.detector = FakeDetector(faces)


class FakeWorker:
    def __init__(self, frame, status="ok"):
        self._frame = frame
        self.status = status

    def last_frame(self):
        return self._frame


class FakeRegistry:
    def __init__(self, workers):
        self._workers = dict(workers)

    def worker(self, camera_id):
        return self._workers.get(camera_id)


def a_frame() -> Frame:
    return Frame(
        camera_id="cam-entrance",
        image=np.zeros((FRAME_H, FRAME_W, 3), dtype=np.uint8),
        captured_at=local(7, 42),
        sequence=1,
    )


@pytest.fixture
def preview_app(user_store):
    """build(faces=..., frame=...) gives an app with enrolment and one camera."""
    from vg.api import app as app_module
    from vg.api.store import MockStore
    from vg.identity.enrolment import EnrolmentService

    # Closed before the directory is removed: an open SQLite handle keeps the
    # file locked on Windows and the teardown fails with a permission error
    # that has nothing to do with what the test was checking.
    opened = []

    def build(faces=(), frame="default", enrolment=True):
        app_module.set_store(MockStore())
        application = app_module.create_app()
        application.state.users = user_store

        if enrolment:
            tmp = tempfile.TemporaryDirectory()
            gallery = FaceGallery(Path(tmp.name) / "g.db", model=MODEL, threshold=0.363)
            opened.append((tmp, gallery))
            application.state.enrolment = EnrolmentService(gallery, FakePipeline(faces))
        else:
            application.state.enrolment = None
            application.state.enrolment_error = (
                "enrolment is not available: the face model did not load"
            )

        application.state.registry = FakeRegistry({
            "cam-entrance": FakeWorker(a_frame() if frame == "default" else frame),
        })
        return application

    yield build
    for tmp, gallery in opened:
        gallery.close()
        tmp.cleanup()


class TestEnrolmentPreview:
    def test_preview_returns_faces_as_fractions_with_five_points(
        self, preview_app, authed,
    ):
        """Constitution rule 6: geometry crosses the API as fractions.

        A pixel value here is not a big number, it is a bug: the overlay
        multiplies by 100 and would put the box somewhere off the screen.
        """
        client = authed(preview_app(faces=[a_face()]))

        body = client.get("/enrolment/preview/cam-entrance").json()

        assert body["offline"] is False
        face = body["faces"][0]
        assert face["x"] == pytest.approx(64 / FRAME_W)
        assert face["y"] == pytest.approx(48 / FRAME_H)
        assert face["w"] == pytest.approx(160 / FRAME_W)
        assert face["h"] == pytest.approx(192 / FRAME_H)

        assert len(face["points"]) == 5
        for point in face["points"]:
            assert 0.0 <= point["x"] <= 1.0
            assert 0.0 <= point["y"] <= 1.0

    def test_preview_carries_no_name_or_identity(self, preview_app, authed):
        """An enrolment preview must never claim to know who it sees.

        Recognition leaking into enrolment is the bug that once had every
        person on a camera read as the same person. The payload is geometry;
        there is nowhere for a name to travel even if something sent one.
        """
        client = authed(preview_app(faces=[a_face()]))

        face = client.get("/enrolment/preview/cam-entrance").json()["faces"][0]

        assert set(face) == {"x", "y", "w", "h", "points", "confidence"}

    def test_preview_empty_frame_is_no_faces_not_an_error(self, preview_app, authed):
        """Nobody in front of the camera is information, not a failure."""
        client = authed(preview_app(faces=[]))

        response = client.get("/enrolment/preview/cam-entrance")

        assert response.status_code == 200
        assert response.json()["faces"] == []
        assert response.json()["offline"] is False

    def test_preview_offline_camera_says_offline(self, preview_app, authed):
        """Rule 4: never an empty overlay pretending to have looked.

        Looked-and-found-nobody and could-not-look are different answers, and
        the page draws them differently: one says nobody is detected, the
        other says NO SIGNAL.
        """
        client = authed(preview_app(faces=[a_face()], frame=None))

        body = client.get("/enrolment/preview/cam-entrance").json()

        assert body["offline"] is True
        assert body["faces"] == []
        assert body["at"] is None

    def test_preview_stamps_when_the_frame_was_captured(self, preview_app, authed):
        """The overlay is only as current as the frame it came from."""
        client = authed(preview_app(faces=[a_face()]))

        body = client.get("/enrolment/preview/cam-entrance").json()

        assert body["at"]["utc"].startswith(local(7, 42).isoformat()[:19])

    def test_preview_unknown_camera_404s(self, preview_app, authed):
        client = authed(preview_app(faces=[a_face()]))

        response = client.get("/enrolment/preview/cam-nowhere")

        assert response.status_code == 404
        assert "cam-nowhere" in response.json()["detail"]

    def test_preview_without_enrolment_503s_with_the_same_reason(
        self, preview_app, authed,
    ):
        """It appears and disappears with the rest of enrolment, never alone."""
        client = authed(preview_app(enrolment=False))

        response = client.get("/enrolment/preview/cam-entrance")
        sessions = client.post("/enrolment/sessions", json={"name": "Anyone"})

        assert response.status_code == 503
        assert sessions.status_code == 503
        assert response.json()["detail"] == sessions.json()["detail"]

    def test_preview_is_admin_only(self, preview_app, authed):
        """It lives under /enrolment, which is admin-only by path."""
        client = authed(preview_app(faces=[a_face()]), role="it")

        assert client.get("/enrolment/preview/cam-entrance").status_code == 403

    def test_a_face_at_the_frame_edge_stays_inside_the_fractions(
        self, preview_app, authed,
    ):
        """A face half out of shot still has to describe a drawable box.

        The detector happily returns a negative origin or a box running past
        the edge. Sent as-is it fails wire validation and the overlay vanishes
        mid-enrolment, which reads as no-face when there plainly is one.
        """
        client = authed(preview_app(faces=[a_face(x=-40, y=-30, w=200, h=200)]))

        response = client.get("/enrolment/preview/cam-entrance")

        assert response.status_code == 200
        face = response.json()["faces"][0]
        assert face["x"] == 0.0 and face["y"] == 0.0
        for point in face["points"]:
            assert 0.0 <= point["x"] <= 1.0
            assert 0.0 <= point["y"] <= 1.0


# ---------------------------------------------------------------------------
# US3 - removing a person
#
# The only destructive action in this feature. Everything below is a rule the
# console can report but never enforce: who is allowed, what actually gets
# deleted, and what is written down before anything is.
# ---------------------------------------------------------------------------

@pytest.fixture
def removal_app(user_store):
    """An app whose store is a real LiveStore over a throwaway gallery."""
    from vg.api import app as app_module

    tmp = tempfile.TemporaryDirectory()
    gallery = FaceGallery(Path(tmp.name) / "g.db", model=MODEL, threshold=0.363)
    sightings = SightingStore(Path(tmp.name) / "s.db", clock=CAIRO)

    gallery.add_person("p-layla", "Layla Ahmed", group="Grade 8")
    gallery.add_embedding("p-layla", unit("p-layla"), MODEL)
    gallery.add_embedding("p-layla", unit("p-layla-2"), MODEL)
    gallery.add_person("p-omar", "Omar Khaled", group="Grade 8")
    gallery.add_embedding("p-omar", unit("p-omar"), MODEL)

    store = LiveStore(
        config=vgconfig.load(), registry=CameraRegistry([ENTRANCE]),
        gallery=gallery, sightings=sightings,
    )
    app_module.set_store(store)
    application = app_module.create_app()
    application.state.users = user_store
    application.state.registry = store.registry

    yield application, store

    sightings.close()
    gallery.close()
    tmp.cleanup()


def embeddings(gallery: FaceGallery, person_id: str) -> int:
    row = gallery._conn.execute(
        "SELECT COUNT(*) AS n FROM face_embedding WHERE person_id = ?", (person_id,),
    ).fetchone()
    return row["n"]


class TestRemovalPermissions:
    def test_removal_requires_admin(self, removal_app, authed):
        """A person's face data leaving the system is not an IT-support task.

        Enforced by path, in the one place permissions are decided, so a write
        endpoint added under /people next year is admin-only the day it is
        written rather than the day somebody remembers.
        """
        application, _ = removal_app

        assert authed(application, role="it").delete(
            "/people/p-layla"
        ).status_code == 403
        assert authed(application, role="admin").delete(
            "/people/p-layla"
        ).status_code == 204

    def test_people_get_stays_open_to_non_admins(self, removal_app, authed):
        """The other half of the rule.

        Reads must not become admin-only by accident: an operator who cannot
        see the directory cannot do their job, and the directory is data about
        who is enrolled, not a lever that changes anything.
        """
        application, _ = removal_app

        response = authed(application, role="it").get("/people")

        assert response.status_code == 200
        assert len(response.json()) == 2

    def test_the_path_rule_itself(self):
        """Without HTTP in the way."""
        from vg.auth import deps as auth_deps

        assert not auth_deps.requires_admin("GET", "/people")
        assert not auth_deps.requires_admin("GET", "/people/p-layla/history")
        assert auth_deps.requires_admin("DELETE", "/people/p-layla")
        # A lookalike prefix must not be swept in, and a real one must not be
        # escapable by hanging something off the end of it.
        assert not auth_deps.requires_admin("DELETE", "/peoplewatch")


class TestRemoval:
    def test_removal_deletes_person_and_embeddings(self, removal_app, authed):
        """The cascade actually fires.

        Deleting the name and quietly keeping the biometric vectors is the
        worst of both: the person is gone from every screen, and the thing
        that actually identifies them is still in the database.
        """
        application, store = removal_app
        assert embeddings(store.gallery, "p-layla") == 2

        response = authed(application).delete("/people/p-layla")

        assert response.status_code == 204
        assert store.gallery.person("p-layla") is None
        assert embeddings(store.gallery, "p-layla") == 0
        # Nobody else was touched.
        assert store.gallery.person("p-omar") is not None
        assert embeddings(store.gallery, "p-omar") == 1

    def test_removed_person_is_never_matched_again(self, removal_app, authed):
        """PPL-FR-006, without a restart.

        The recognition worker holds this same gallery object, so the index
        `match()` reads here is the index it reads on the next frame.
        """
        application, store = removal_app
        vector = unit("p-layla")
        assert store.gallery.match(vector, MODEL).person.id == "p-layla"

        authed(application).delete("/people/p-layla")

        assert store.gallery.match(vector, MODEL).matched is False

    def test_removal_disappears_from_the_directory(self, removal_app, authed):
        application, store = removal_app

        authed(application).delete("/people/p-layla")

        assert [p.name for p in store.people()] == ["Omar Khaled"]

    def test_removal_writes_the_audit_entry_before_deleting(self, removal_app, authed):
        """Who removed whom, recorded before anything is gone.

        The ordering is the point. A crash between the two leaves an audited
        intent, which somebody can investigate; the other order leaves a person
        who vanished with nothing saying why.
        """
        application, store = removal_app

        authed(application, role="admin").delete("/people/p-layla")

        entry = next(e for e in store.audit(50) if e.action == "person.remove")
        assert entry.subject == "Layla Ahmed"
        assert entry.actor

    def test_the_audit_survives_a_delete_that_fails(self, removal_app, authed):
        """Audit-first, proven by breaking the half that comes second.

        The request fails outright, which is correct — a removal that did not
        happen must not answer 204. What matters is that the attempt is on
        record: somebody can see that an administrator tried to remove this
        person and find out why they are still there.
        """
        application, store = removal_app

        def explode(person_id):
            raise RuntimeError("disk gone")

        store.gallery.remove_person = explode

        with pytest.raises(RuntimeError, match="disk gone"):
            authed(application).delete("/people/p-layla")

        assert any(e.action == "person.remove" for e in store.audit(50))
        # And nothing was half-done: they are still there to try again.
        assert store.gallery.person("p-layla") is not None

    def test_removing_unknown_person_404s(self, removal_app, authed):
        """An honest refusal. Nothing is written, because nothing happened."""
        application, store = removal_app

        response = authed(application).delete("/people/p-nobody")

        assert response.status_code == 404
        assert "p-nobody" in response.json()["detail"]
        assert not [e for e in store.audit(50) if e.action == "person.remove"]

    def test_sightings_are_kept(self, removal_app, authed):
        """Owner decision, 2026-08-21.

        The rows stay in the database and stop being reachable from any page.
        Full every-table erasure is P3's, and deleting them here would also be
        deleting the evidence behind a register that has already been read.
        """
        application, store = removal_app
        store.sightings.record(
            Sighting("p-layla", "cam-entrance", local(7, 42), 0.8, MODEL), force=True,
        )

        authed(application).delete("/people/p-layla")

        assert len(store.sightings.sightings_on("2026-08-17", "p-layla")) == 1


class TestRemovalWithoutAGallery:
    def test_removal_without_a_gallery_says_so(self, bare_live_store, user_store,
                                               authed):
        """No gallery is not "no such person" — it is "nothing to remove from".

        A 404 here would send an administrator looking for a person who is
        perfectly present, on a system where recognition simply is not running.
        """
        from vg.api import app as app_module

        app_module.set_store(bare_live_store)
        application = app_module.create_app()
        application.state.users = user_store

        response = authed(application).delete("/people/p-layla")

        assert response.status_code == 503
