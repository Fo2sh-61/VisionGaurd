"""Enrolment staging, scoring and commit.

The rule these tests defend: **a thin enrolment is worse than no enrolment.**
Someone in the gallery with one blurry photo is not "partly recognisable" — they
are unreliably recognisable, which on a register looks exactly like a working
system right up until it names the wrong child.

So the service refuses to commit below the photo floor, refuses to guess which
face in a crowded shot is the subject, and refuses near-duplicate photos that
pad the count without adding an angle.

A fake pipeline is injected throughout: this is about the staging logic, and
running the real ONNX models would make these tests slow and dependent on having
photographs of real people checked into the repo.
"""

from __future__ import annotations

import tempfile
from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
from pathlib import Path

import numpy as np
import pytest

from vg.identity.enrolment import (
    MIN_CONFIDENCE,
    REQUIRED_PHOTOS,
    SESSION_TTL,
    EnrolmentService,
    describe_angle,
    quality_score,
    slugify,
)
from vg.identity.gallery import FaceGallery
from vg.infer.faces import MIN_FACE_PIXELS

MODEL = "sface-2021dec"


def unit(seed: int) -> np.ndarray:
    rng = np.random.default_rng(seed)
    v = rng.standard_normal(128).astype(np.float32)
    return v / np.linalg.norm(v)


# ---------------------------------------------------------------------------
# fakes
# ---------------------------------------------------------------------------

@dataclass
class FakeFace:
    x: int = 10
    y: int = 10
    w: int = 120
    h: int = 120
    confidence: float = 0.95
    landmarks: np.ndarray = None
    raw: np.ndarray = None

    def __post_init__(self):
        if self.landmarks is None:
            # right eye, left eye, nose, two mouth corners - nose centred
            self.landmarks = np.array(
                [[40, 40], [80, 40], [60, 60], [45, 80], [75, 80]], dtype=np.float32
            )


class FakeDetector:
    def __init__(self, faces):
        self.faces = faces

    def detect(self, image, min_size=1):
        return list(self.faces)


class FakeEmbedder:
    name = MODEL
    dimensions = 128
    threshold = 0.363

    def __init__(self, vectors):
        self.vectors = list(vectors)
        self.calls = 0

    def embed(self, image, face):
        vector = self.vectors[min(self.calls, len(self.vectors) - 1)]
        self.calls += 1
        return vector


class FakePipeline:
    def __init__(self, faces, vectors):
        self.detector = FakeDetector(faces)
        self.embedder = FakeEmbedder(vectors)

    @property
    def model_name(self):
        return self.embedder.name


@pytest.fixture
def gallery():
    with tempfile.TemporaryDirectory() as tmp:
        g = FaceGallery(Path(tmp) / "g.db", model=MODEL, threshold=0.363)
        yield g
        g.close()


def service(gallery, faces=None, vectors=None):
    faces = faces if faces is not None else [FakeFace()]
    vectors = vectors if vectors is not None else [unit(i) for i in range(10)]
    return EnrolmentService(gallery, FakePipeline(faces, vectors))


IMAGE = np.zeros((480, 640, 3), dtype=np.uint8)


# ---------------------------------------------------------------------------
# pure helpers
# ---------------------------------------------------------------------------

class TestHelpers:
    def test_slug_matches_the_cli_tool(self):
        """Ids must be identical whichever route enrolled the person, or the
        same human ends up in the gallery twice under two ids."""
        assert slugify("Ahmed Hassan") == "p-ahmed-hassan"
        assert slugify("  Layla   Al-Masri ") == "p-layla-al-masri"

    def test_bigger_faces_score_higher(self):
        assert quality_score(200, 0.95) > quality_score(100, 0.95)

    def test_a_face_at_the_floor_still_scores_something(self):
        """MIN_FACE_PIXELS is usable, just not good. Scoring it zero would tell
        the operator to retry a photo that is actually fine."""
        assert quality_score(MIN_FACE_PIXELS, 0.95) > 20

    def test_confidence_matters_but_size_matters_more(self):
        big_unsure = quality_score(200, 0.80)
        small_certain = quality_score(MIN_FACE_PIXELS, 1.0)
        assert big_unsure > small_certain

    def test_centred_nose_reads_as_front_on(self):
        yaw, label = describe_angle(FakeFace())
        assert label == "front on"
        assert abs(yaw) < 0.12

    def test_offset_nose_reads_as_angled(self):
        turned = FakeFace(landmarks=np.array(
            [[40, 40], [80, 40], [48, 60], [45, 80], [75, 80]], dtype=np.float32
        ))
        yaw, label = describe_angle(turned)
        assert label in {"slight angle", "strong angle"}
        assert yaw != 0.0

    def test_opposite_turns_have_opposite_signs(self):
        """The sign is what lets the UI tell two angles apart, which is the
        whole reason varied photos are requested."""
        left = FakeFace(landmarks=np.array(
            [[40, 40], [80, 40], [46, 60], [45, 80], [75, 80]], dtype=np.float32))
        right = FakeFace(landmarks=np.array(
            [[40, 40], [80, 40], [74, 60], [45, 80], [75, 80]], dtype=np.float32))
        assert describe_angle(left)[0] * describe_angle(right)[0] < 0


# ---------------------------------------------------------------------------
# staging
# ---------------------------------------------------------------------------

class TestStaging:
    def test_a_good_photo_is_usable(self, gallery):
        svc = service(gallery)
        session = svc.start("Ahmed Hassan")
        photo = svc.add_photo(session.id, IMAGE)

        assert photo.usable and photo.score > 0
        assert photo.vector is not None

    def test_no_face_is_rejected_with_a_reason(self, gallery):
        svc = service(gallery, faces=[])
        session = svc.start("Ahmed Hassan")
        photo = svc.add_photo(session.id, IMAGE)

        assert not photo.usable
        assert "No face" in photo.note

    def test_two_faces_is_rejected_rather_than_guessed(self, gallery):
        """Enrolling the wrong face poisons the gallery permanently and
        silently. There is no safe way to pick one."""
        svc = service(gallery, faces=[FakeFace(), FakeFace(x=300)])
        session = svc.start("Ahmed Hassan")
        photo = svc.add_photo(session.id, IMAGE)

        assert not photo.usable
        assert "2 faces" in photo.note

    def test_background_noise_does_not_make_a_good_shot_ambiguous(self, gallery):
        """Regression, found against the walk-through clip.

        Detecting below the recognition floor is needed to tell "too small"
        from "no face" — but at a 1px floor YuNet returned 61 "faces" on an
        ordinary corridor frame, so every capture was rejected as ambiguous. A
        background blob is not a person someone might be enrolling.
        """
        noise = [FakeFace(w=8, h=8, x=i * 20) for i in range(60)]
        svc = service(gallery, faces=[FakeFace()] + noise)
        session = svc.start("Ahmed Hassan")
        photo = svc.add_photo(session.id, IMAGE)

        assert photo.usable, photo.note

    def test_two_real_faces_are_still_ambiguous(self, gallery):
        """The noise filter must not weaken the actual guarantee."""
        svc = service(gallery, faces=[FakeFace(), FakeFace(x=300)])
        session = svc.start("Ahmed Hassan")

        assert not svc.add_photo(session.id, IMAGE).usable

    def test_a_face_below_the_recognition_floor_says_so_specifically(self, gallery):
        """"Too small" sends the operator closer; "no face" sends them looking
        for the wrong problem entirely."""
        svc = service(gallery, faces=[FakeFace(w=61, h=61)])
        session = svc.start("Ahmed Hassan")
        photo = svc.add_photo(session.id, IMAGE)

        assert not photo.usable
        assert "61px" in photo.note and str(MIN_FACE_PIXELS) in photo.note

    def test_an_unclear_face_is_rejected(self, gallery):
        svc = service(gallery, faces=[FakeFace(confidence=MIN_CONFIDENCE - 0.1)])
        session = svc.start("Ahmed Hassan")
        photo = svc.add_photo(session.id, IMAGE)

        assert not photo.usable
        assert "Unclear" in photo.note

    def test_a_near_duplicate_is_rejected(self, gallery):
        """Same pose, same light. It pads the count and adds nothing, so
        accepting it would make a thin enrolment look complete."""
        same = unit(1)
        svc = service(gallery, vectors=[same, same])
        session = svc.start("Ahmed Hassan")

        assert svc.add_photo(session.id, IMAGE).usable
        second = svc.add_photo(session.id, IMAGE)

        assert not second.usable
        assert "similar" in second.note.lower()

    def test_rejected_photos_are_still_recorded_so_the_ui_can_explain(self, gallery):
        svc = service(gallery, faces=[])
        session = svc.start("Ahmed Hassan")
        svc.add_photo(session.id, IMAGE)

        assert len(svc.session(session.id).photos) == 1
        assert svc.session(session.id).usable == []

    def test_a_photo_can_be_removed(self, gallery):
        svc = service(gallery)
        session = svc.start("Ahmed Hassan")
        photo = svc.add_photo(session.id, IMAGE)

        assert svc.remove_photo(session.id, photo.id)
        assert svc.session(session.id).photos == []

    def test_unknown_session_raises(self, gallery):
        svc = service(gallery)
        with pytest.raises(KeyError):
            svc.add_photo("nope", IMAGE)


# ---------------------------------------------------------------------------
# readiness and advice
# ---------------------------------------------------------------------------

class TestReadiness:
    def test_not_ready_below_the_floor(self, gallery):
        svc = service(gallery)
        session = svc.start("Ahmed Hassan")
        for _ in range(REQUIRED_PHOTOS - 1):
            svc.add_photo(session.id, IMAGE)

        assert not svc.session(session.id).ready

    def test_ready_at_the_floor(self, gallery):
        svc = service(gallery)
        session = svc.start("Ahmed Hassan")
        for _ in range(REQUIRED_PHOTOS):
            svc.add_photo(session.id, IMAGE)

        assert svc.session(session.id).ready

    def test_advice_says_how_many_more_are_needed(self, gallery):
        svc = service(gallery)
        session = svc.start("Ahmed Hassan")
        svc.add_photo(session.id, IMAGE)

        advice = svc.session(session.id).advice
        assert str(REQUIRED_PHOTOS - 1) in advice

    def test_advice_warns_when_every_angle_is_the_same(self, gallery):
        """Three photos of the same pose satisfy the count but not the point."""
        svc = service(gallery)
        session = svc.start("Ahmed Hassan")
        for _ in range(REQUIRED_PHOTOS):
            svc.add_photo(session.id, IMAGE)

        assert "same angle" in svc.session(session.id).advice


# ---------------------------------------------------------------------------
# commit
# ---------------------------------------------------------------------------

class TestCommit:
    def test_nothing_reaches_the_gallery_before_commit(self, gallery):
        """The whole reason for staging: an abandoned enrolment leaves no
        trace, so there is never a half-enrolled person to clean up."""
        svc = service(gallery)
        session = svc.start("Ahmed Hassan")
        for _ in range(REQUIRED_PHOTOS):
            svc.add_photo(session.id, IMAGE)

        assert gallery.people() == []
        assert gallery.embedding_count == 0

    def test_commit_writes_person_and_every_usable_vector(self, gallery):
        svc = service(gallery)
        session = svc.start("Ahmed Hassan", type="Student", group="Grade 8")
        for _ in range(REQUIRED_PHOTOS):
            svc.add_photo(session.id, IMAGE)

        person = svc.commit(session.id)

        assert person.name == "Ahmed Hassan"
        assert person.id == "p-ahmed-hassan"
        assert person.group == "Grade 8"
        assert person.photo_count == REQUIRED_PHOTOS
        assert person.photo_on_file

    def test_the_floor_is_five(self, gallery):
        """Owner decision, 2026-08-21 — raised from three.

        Pinned as a number, not as `REQUIRED_PHOTOS`, because every other test
        here derives from the constant and would happily follow it anywhere.
        A floor that moves silently is not a floor.
        """
        assert REQUIRED_PHOTOS == 5

    def test_nobody_is_enrolled_without_photos(self, gallery):
        """A refused enrolment creates no person at all.

        Not a directory row waiting for photos: somebody with no face on file
        cannot be recognised, so every register they appear in can only ever
        mark them absent, and nothing on the page would explain why.
        """
        svc = service(gallery)
        session = svc.start("Ahmed Hassan")

        with pytest.raises(ValueError):
            svc.commit(session.id)

        assert gallery.people() == []
        assert gallery.person("p-ahmed-hassan") is None

    def test_a_short_enrolment_creates_nobody_either(self, gallery):
        """One short of the floor is still refused, and still creates nothing.

        The check runs before `add_person`, so there is no half-written person
        to roll back — which is the property that makes staging worth having.
        """
        svc = service(gallery)
        session = svc.start("Ahmed Hassan")
        for _ in range(REQUIRED_PHOTOS - 1):
            svc.add_photo(session.id, IMAGE)

        with pytest.raises(ValueError, match="required"):
            svc.commit(session.id)

        assert gallery.people() == []
        assert gallery.embedding_count == 0

    def test_commit_refuses_a_thin_enrolment(self, gallery):
        svc = service(gallery)
        session = svc.start("Ahmed Hassan")
        svc.add_photo(session.id, IMAGE)

        with pytest.raises(ValueError, match="required"):
            svc.commit(session.id)
        assert gallery.people() == []

    def test_unusable_photos_do_not_count_toward_the_floor(self, gallery):
        """Uploads that failed do not count towards the floor."""
        svc = service(gallery, faces=[])
        session = svc.start("Ahmed Hassan")
        for _ in range(REQUIRED_PHOTOS + 2):
            svc.add_photo(session.id, IMAGE)

        with pytest.raises(ValueError):
            svc.commit(session.id)

    def test_the_session_is_gone_after_commit(self, gallery):
        svc = service(gallery)
        session = svc.start("Ahmed Hassan")
        for _ in range(REQUIRED_PHOTOS):
            svc.add_photo(session.id, IMAGE)
        svc.commit(session.id)

        assert svc.session(session.id) is None

    def test_cancel_leaves_no_trace(self, gallery):
        svc = service(gallery)
        session = svc.start("Ahmed Hassan")
        for _ in range(REQUIRED_PHOTOS):
            svc.add_photo(session.id, IMAGE)

        assert svc.cancel(session.id)
        assert svc.session(session.id) is None
        assert gallery.people() == []

    def test_committed_vectors_actually_recognise_the_person(self, gallery):
        """End to end: what was enrolled must match against the gallery
        afterwards. Storing vectors that cannot be matched is the failure this
        whole flow exists to prevent."""
        # One distinct vector per required photo. A fixed three stopped
        # covering the floor the moment it moved, and every repeat is
        # rejected as too similar, so the enrolment never reached commit.
        vectors = [unit(i + 1) for i in range(REQUIRED_PHOTOS)]
        svc = service(gallery, vectors=vectors)
        session = svc.start("Ahmed Hassan")
        for _ in range(REQUIRED_PHOTOS):
            svc.add_photo(session.id, IMAGE)
        svc.commit(session.id)

        match = gallery.match(vectors[0], MODEL)
        assert match.matched and match.person.name == "Ahmed Hassan"

    def test_a_name_is_required(self, gallery):
        svc = service(gallery)
        with pytest.raises(ValueError):
            svc.start("   ")


# ---------------------------------------------------------------------------
# the API seam
# ---------------------------------------------------------------------------

@pytest.fixture
def client(gallery, authed):
    """A test client with a fake enrolment service already attached.

    The lifespan does not run under a bare TestClient, so `app.state.enrolment`
    is injected here. That is also the behaviour being relied on by
    `test_enrolment_is_unavailable_not_broken` below.
    """

    from vg.api.app import create_app
    from vg.api.store import MockStore
    from vg.api import app as app_module

    app_module.set_store(MockStore())
    app = create_app()
    app.state.enrolment = service(gallery)
    app.state.enrolment_error = None
    app.state.registry = None
    # Enrolment is admin-only, and these tests exercise the feature rather
    # than the gate. test_authorisation.py covers the gate.
    return authed(app, "admin")


def jpeg() -> bytes:
    import cv2

    ok, buf = cv2.imencode(".jpg", IMAGE)
    assert ok
    return buf.tobytes()


def upload(client, session_id: str):
    return client.post(
        f"/enrolment/sessions/{session_id}/photos",
        files={"file": ("shot.jpg", jpeg(), "image/jpeg")},
    )


class TestEnrolmentApi:
    def test_start_returns_a_session_with_nothing_staged(self, client):
        r = client.post("/enrolment/sessions", json={"name": "Ahmed Hassan"})
        assert r.status_code == 201

        body = r.json()
        assert body["personId"] == "p-ahmed-hassan"
        assert body["photos"] == []
        assert body["ready"] is False
        assert body["requiredCount"] == REQUIRED_PHOTOS

    def test_the_wire_is_camel_case(self, client):
        """The front end is TypeScript; snake_case would force a translation
        layer nobody wants to maintain."""
        body = client.post("/enrolment/sessions", json={"name": "A B"}).json()
        assert "usableCount" in body and "usable_count" not in body
        assert "personId" in body

    def test_uploading_a_photo_returns_the_whole_session(self, client):
        session = client.post("/enrolment/sessions", json={"name": "A B"}).json()
        body = upload(client, session["id"]).json()

        assert len(body["photos"]) == 1
        assert body["photos"][0]["usable"] is True
        assert body["usableCount"] == 1

    def test_a_rejected_photo_is_200_with_a_reason_not_an_error(self, client, gallery):
        """The operator has to read *why* it failed, next to the thumbnail. An
        HTTP error status cannot carry that, and reads as a broken button."""
        client.app.state.enrolment = service(gallery, faces=[])
        session = client.post("/enrolment/sessions", json={"name": "A B"}).json()

        r = upload(client, session["id"])
        assert r.status_code == 200
        assert r.json()["photos"][0]["usable"] is False
        assert "No face" in r.json()["photos"][0]["note"]

    def test_ready_flips_at_the_photo_floor(self, client):
        session = client.post("/enrolment/sessions", json={"name": "A B"}).json()
        for _ in range(REQUIRED_PHOTOS - 1):
            body = upload(client, session["id"]).json()
        assert body["ready"] is False

        body = upload(client, session["id"]).json()
        assert body["ready"] is True

    def test_a_photo_can_be_removed(self, client):
        session = client.post("/enrolment/sessions", json={"name": "A B"}).json()
        photo = upload(client, session["id"]).json()["photos"][0]

        r = client.delete(f"/enrolment/sessions/{session['id']}/photos/{photo['id']}")
        assert r.status_code == 200 and r.json()["photos"] == []

    def test_commit_below_the_floor_is_refused_with_a_reason(self, client):
        session = client.post("/enrolment/sessions", json={"name": "A B"}).json()
        upload(client, session["id"])

        r = client.post(f"/enrolment/sessions/{session['id']}/commit")
        assert r.status_code == 422
        assert "required" in r.json()["detail"]

    def test_commit_returns_the_directory_person(self, client, gallery):
        session = client.post(
            "/enrolment/sessions",
            json={"name": "Ahmed Hassan", "type": "Student", "group": "Grade 8"},
        ).json()
        for _ in range(REQUIRED_PHOTOS):
            upload(client, session["id"])

        r = client.post(f"/enrolment/sessions/{session['id']}/commit")
        assert r.status_code == 200

        body = r.json()
        assert body["name"] == "Ahmed Hassan"
        assert body["photoOnFile"] is True
        assert gallery.person("p-ahmed-hassan").photo_count == REQUIRED_PHOTOS

    def test_a_committed_session_is_gone(self, client):
        session = client.post("/enrolment/sessions", json={"name": "A B"}).json()
        for _ in range(REQUIRED_PHOTOS):
            upload(client, session["id"])
        client.post(f"/enrolment/sessions/{session['id']}/commit")

        assert client.get(f"/enrolment/sessions/{session['id']}").status_code == 404

    def test_cancel_discards_everything(self, client, gallery):
        session = client.post("/enrolment/sessions", json={"name": "A B"}).json()
        for _ in range(REQUIRED_PHOTOS):
            upload(client, session["id"])

        assert client.delete(f"/enrolment/sessions/{session['id']}").status_code == 204
        assert gallery.people() == []

    def test_unknown_session_is_404_not_500(self, client):
        assert upload(client, "nope").status_code == 404
        assert client.post("/enrolment/sessions/nope/commit").status_code == 404

    def test_an_unreadable_upload_says_so(self, client):
        session = client.post("/enrolment/sessions", json={"name": "A B"}).json()
        r = client.post(
            f"/enrolment/sessions/{session['id']}/photos",
            files={"file": ("x.jpg", b"not an image", "image/jpeg")},
        )
        assert r.status_code == 422
        assert "image" in r.json()["detail"].lower()

    def test_capture_from_a_missing_camera_is_404(self, client):
        session = client.post("/enrolment/sessions", json={"name": "A B"}).json()
        r = client.post(
            f"/enrolment/sessions/{session['id']}/capture?camera_id=nope"
        )
        assert r.status_code == 404

    def test_enrolment_is_unavailable_not_broken(self, client):
        """The face model failing to load must degrade this one feature and say
        why — never take the API down or, worse, silently pretend to work."""
        client.app.state.enrolment = None
        client.app.state.enrolment_error = "FileNotFoundError: SFace weights not found"

        r = client.post("/enrolment/sessions", json={"name": "A B"})
        assert r.status_code == 503
        assert "SFace" in r.json()["detail"]

    def test_no_endpoint_returns_image_data(self, client):
        """The gallery stores vectors and never pixels. A vector cannot be
        turned back into a photograph, and that is the property that limits
        what a leak of children's biometric data exposes."""
        session = client.post("/enrolment/sessions", json={"name": "A B"}).json()
        body = upload(client, session["id"]).json()

        serialised = str(body)
        assert "image" not in serialised.lower()
        assert "vector" not in serialised.lower()
        for photo in body["photos"]:
            assert set(photo) == {
                "id", "usable", "score", "facePixels", "confidence",
                "similarity", "yaw", "note", "source", "reason", "reasonValue",
            }


# ---------------------------------------------------------------------------
# spec 023: reasons as codes, and an audited commit
# ---------------------------------------------------------------------------

class _CutOffEmbedder(FakeEmbedder):
    def embed(self, image, face):
        raise ValueError("landmarks outside the frame")


class TestRejectionReasons:
    """The console words the reason; the engine says which one and how much.
    `note` stays an English sentence for the phone."""

    def _photo(self, gallery, **kw):
        svc = service(gallery, **kw)
        session = svc.start("Ahmed Hassan")
        return svc, session, svc.add_photo(session.id, IMAGE)

    def test_no_face(self, gallery):
        _, _, photo = self._photo(gallery, faces=[])
        assert (photo.reason, photo.reason_value) == ("no_face", None)
        assert "No face" in photo.note

    def test_several_faces_carries_the_count(self, gallery):
        _, _, photo = self._photo(
            gallery, faces=[FakeFace(), FakeFace(x=300), FakeFace(x=500)])
        assert (photo.reason, photo.reason_value) == ("several_faces", 3)
        assert "3 faces" in photo.note

    def test_too_small_carries_the_biggest_face_in_pixels(self, gallery):
        _, _, photo = self._photo(gallery, faces=[FakeFace(w=61, h=61)])
        assert (photo.reason, photo.reason_value) == ("too_small", 61)
        assert "61px" in photo.note

    def test_unclear_carries_the_score(self, gallery):
        _, _, photo = self._photo(gallery, faces=[FakeFace(confidence=0.5)])
        assert photo.reason == "unclear" and photo.reason_value == 0.5
        assert "Unclear" in photo.note

    def test_cut_off(self, gallery):
        svc = service(gallery)
        svc.pipeline.embedder = _CutOffEmbedder([])
        session = svc.start("Ahmed Hassan")
        photo = svc.add_photo(session.id, IMAGE)
        assert (photo.reason, photo.reason_value) == ("cut_off", None)
        assert "cut off" in photo.note

    def test_too_similar_carries_the_similarity(self, gallery):
        same = unit(1)
        svc = service(gallery, vectors=[same, same])
        session = svc.start("Ahmed Hassan")
        svc.add_photo(session.id, IMAGE)
        second = svc.add_photo(session.id, IMAGE)
        assert second.reason == "too_similar"
        assert second.reason_value > 0.92
        assert "similar" in second.note.lower()

    def test_a_usable_photo_has_no_reason(self, gallery):
        _, _, photo = self._photo(gallery)
        assert photo.usable and photo.reason is None and photo.reason_value is None

    def test_the_wire_carries_them_camel_cased(self, client, gallery):
        client.app.state.enrolment = service(gallery, faces=[FakeFace(w=61, h=61)])
        session = client.post("/enrolment/sessions", json={"name": "A B"}).json()
        photo = upload(client, session["id"]).json()["photos"][0]
        assert photo["reason"] == "too_small"
        assert photo["reasonValue"] == 61
        assert "No face" not in photo["note"] and "61px" in photo["note"]


class TestEnrolmentIsAudited:
    def _staged(self, client, photos=REQUIRED_PHOTOS, **body):
        session = client.post(
            "/enrolment/sessions",
            json={"name": "Ahmed Hassan", "group": "Grade 8", **body}).json()
        for _ in range(photos):
            upload(client, session["id"])
        return session

    def _entries(self):
        from vg.api import app as app_module
        return [e for e in app_module.get_store()._audit if e.action == "person.enrol"]

    def test_commit_writes_the_entry_with_name_group_and_photo_count(self, client):
        session = self._staged(client)
        assert client.post(f"/enrolment/sessions/{session['id']}/commit").status_code == 200

        (entry,) = self._entries()
        assert entry.subject == "Ahmed Hassan"
        assert str(REQUIRED_PHOTOS) in entry.detail and "Grade 8" in entry.detail
        assert entry.actor == "Test Admin"

    def test_the_entry_exists_before_the_commit_runs(self, client):
        """Order is the guarantee: a commit that dies leaves an audited
        attempt, never a person nobody can say who added."""
        session = self._staged(client)
        seen = {}
        service_ = client.app.state.enrolment
        real = service_.commit

        def commit(session_id):
            seen["entries"] = len(self._entries())
            raise RuntimeError("disk full")

        service_.commit = commit
        with pytest.raises(RuntimeError):
            client.post(f"/enrolment/sessions/{session['id']}/commit")
        service_.commit = real
        assert seen["entries"] == 1

    def test_a_refused_commit_keeps_the_entry_and_the_session(self, client):
        session = self._staged(client, photos=1)
        r = client.post(f"/enrolment/sessions/{session['id']}/commit")
        assert r.status_code == 422
        assert len(self._entries()) == 1
        assert client.get(f"/enrolment/sessions/{session['id']}").status_code == 200

    def test_it_cannot_commit(self, client, authed):
        session = self._staged(client)
        it = authed(client.app, "it")
        assert it.post(f"/enrolment/sessions/{session['id']}/commit").status_code == 403

    def test_a_committed_session_leaves_rows_only_in_person_and_face_embedding(
            self, client, gallery):
        """Pins the photo note: nothing is kept but measurements."""
        session = self._staged(client)
        client.post(f"/enrolment/sessions/{session['id']}/commit")

        tables = [r["name"] for r in gallery._conn.execute(
            "SELECT name FROM sqlite_master WHERE type='table' "
            "AND name NOT LIKE 'sqlite_%'").fetchall()]
        filled = {
            t for t in tables
            if gallery._conn.execute(f"SELECT COUNT(*) AS n FROM {t}").fetchone()["n"]
        }
        assert filled == {"person", "face_embedding"}

    def test_a_cancelled_session_leaves_no_person_and_no_face(self, client, gallery):
        session = self._staged(client)
        assert client.delete(f"/enrolment/sessions/{session['id']}").status_code == 204
        for table in ("person", "face_embedding"):
            assert gallery._conn.execute(
                f"SELECT COUNT(*) AS n FROM {table}").fetchone()["n"] == 0

    def test_an_expired_session_leaves_no_person_and_no_face(self, client, gallery):
        session = self._staged(client)
        service = client.app.state.enrolment
        stale = datetime.now(timezone.utc) - SESSION_TTL - timedelta(minutes=1)
        service._sessions[session["id"]].touched_at = stale  # abandoned past the TTL
        assert client.get(f"/enrolment/sessions/{session['id']}").status_code == 404
        for table in ("person", "face_embedding"):
            assert gallery._conn.execute(
                f"SELECT COUNT(*) AS n FROM {table}").fetchone()["n"] == 0
