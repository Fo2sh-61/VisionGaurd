"""Face pipeline and gallery.

The gallery tests are about refusing to guess. Recognition that says "I don't
know" is a usable system; recognition that confidently names the wrong child on
an attendance register is worse than having none, because the wrong answer gets
believed and an absence gets corrected.
"""

from __future__ import annotations

import tempfile
from pathlib import Path

import numpy as np
import pytest

from vg.identity.gallery import FaceGallery
from vg.infer.faces import MIN_FACE_PIXELS, SFACE_COSINE_THRESHOLD

MODEL = "sface-2021dec"


def unit(seed: int) -> np.ndarray:
    rng = np.random.default_rng(seed)
    v = rng.standard_normal(128).astype(np.float32)
    return v / np.linalg.norm(v)


def nudge(vector: np.ndarray, amount: float, seed: int = 0) -> np.ndarray:
    """A vector `amount` away from the original — a different photo of one person."""
    rng = np.random.default_rng(seed)
    noise = rng.standard_normal(128).astype(np.float32)
    noise /= np.linalg.norm(noise)
    out = vector * (1 - amount) + noise * amount
    return out / np.linalg.norm(out)


@pytest.fixture
def gallery():
    with tempfile.TemporaryDirectory() as tmp:
        g = FaceGallery(Path(tmp) / "g.db", model=MODEL, threshold=0.363)
        yield g
        g.close()


class TestGalleryBasics:
    def test_empty_gallery_declines_rather_than_erroring(self, gallery):
        match = gallery.match(unit(1))
        assert not match.matched
        assert "empty" in match.reason

    def test_exact_vector_matches_its_owner(self, gallery):
        gallery.add_person("p1", "Alice")
        v = unit(1)
        gallery.add_embedding("p1", v, MODEL)

        match = gallery.match(v)
        assert match.matched and match.person.name == "Alice"
        assert match.score == pytest.approx(1.0, abs=1e-5)

    def test_a_stranger_is_not_matched(self, gallery):
        gallery.add_person("p1", "Alice")
        gallery.add_embedding("p1", unit(1), MODEL)

        match = gallery.match(unit(999))
        assert not match.matched
        assert "below threshold" in match.reason

    def test_removing_a_person_removes_their_faces(self, gallery):
        gallery.add_person("p1", "Alice")
        gallery.add_embedding("p1", unit(1), MODEL)
        assert gallery.embedding_count == 1

        assert gallery.remove_person("p1") is True
        assert gallery.embedding_count == 0
        assert not gallery.match(unit(1)).matched

    def test_person_survives_a_reopen(self):
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / "g.db"
            v = unit(1)
            first = FaceGallery(path, model=MODEL, threshold=0.363)
            first.add_person("p1", "Alice")
            first.add_embedding("p1", v, MODEL)
            first.close()

            second = FaceGallery(path, model=MODEL, threshold=0.363)
            assert second.match(v).person.name == "Alice"
            second.close()


class TestRefusingToGuess:
    def test_two_close_candidates_produce_no_answer(self, gallery):
        # The failure that matters: two students who look alike to the model.
        # Naming either is a coin flip, so the gallery must decline.
        base = unit(1)
        gallery.add_person("p1", "Alice")
        gallery.add_person("p2", "Bob")
        gallery.add_embedding("p1", base, MODEL)
        gallery.add_embedding("p2", nudge(base, 0.02, seed=5), MODEL)

        match = gallery.match(base)
        assert not match.matched
        assert "too close to call" in match.reason
        # It still reports what it saw, so the refusal is diagnosable.
        assert match.score > gallery.threshold
        assert match.margin < gallery.margin

    def test_a_clear_winner_is_returned(self, gallery):
        gallery.add_person("p1", "Alice")
        gallery.add_person("p2", "Bob")
        gallery.add_embedding("p1", unit(1), MODEL)
        gallery.add_embedding("p2", unit(2), MODEL)

        match = gallery.match(unit(1))
        assert match.matched and match.person.name == "Alice"
        assert match.margin >= gallery.margin

    def test_score_is_reported_even_when_declining(self, gallery):
        gallery.add_person("p1", "Alice")
        gallery.add_embedding("p1", unit(1), MODEL)

        match = gallery.match(nudge(unit(1), 0.9, seed=3))
        assert not match.matched
        # "unknown" with no number teaches nothing about where to set the
        # threshold; the score has to come back either way.
        assert 0.0 <= match.score <= 1.0


class TestMultipleAnglesPerPerson:
    def test_best_of_several_embeddings_wins(self, gallery):
        # One photo is one angle. Matching takes each person's BEST vector, so
        # enrolling several varied captures is what makes this work at all.
        gallery.add_person("p1", "Alice")
        gallery.add_embedding("p1", unit(1), MODEL)
        gallery.add_embedding("p1", unit(2), MODEL)
        gallery.add_embedding("p1", unit(3), MODEL)

        for seed in (1, 2, 3):
            match = gallery.match(unit(seed))
            assert match.matched and match.person.name == "Alice"

    def test_photo_count_is_tracked(self, gallery):
        gallery.add_person("p1", "Alice")
        assert gallery.person("p1").photo_on_file is False

        gallery.add_embedding("p1", unit(1), MODEL)
        gallery.add_embedding("p1", unit(2), MODEL)
        assert gallery.person("p1").photo_count == 2
        assert gallery.person("p1").photo_on_file is True

    def test_size_counts_only_recognisable_people(self, gallery):
        # Someone in the directory with no photo cannot be recognised, and the
        # UI says so. The count has to reflect that.
        gallery.add_person("p1", "Alice")
        gallery.add_person("p2", "Bob")
        gallery.add_embedding("p1", unit(1), MODEL)

        assert len(gallery.people()) == 2
        assert gallery.size == 1


class TestModelMismatch:
    def test_storing_a_foreign_model_is_refused(self, gallery):
        # SFace and ArcFace vectors are not comparable. Mixing them produces
        # plausible-looking nonsense rather than an obvious failure.
        with pytest.raises(ValueError, match="refusing to store"):
            gallery.add_embedding("p1", unit(1), "arcface-r50")

    def test_matching_a_foreign_model_declines(self, gallery):
        gallery.add_person("p1", "Alice")
        gallery.add_embedding("p1", unit(1), MODEL)

        match = gallery.match(unit(1), model="arcface-r50")
        assert not match.matched
        assert "gallery holds" in match.reason

    def test_wrong_dimensions_decline(self, gallery):
        gallery.add_person("p1", "Alice")
        gallery.add_embedding("p1", unit(1), MODEL)

        match = gallery.match(np.zeros(512, dtype=np.float32))
        assert not match.matched
        assert "size" in match.reason


class TestFaceSizeGate:
    def test_minimum_face_size_is_enforced_by_default(self):
        # Measured, not guessed: at 40 px the same person scored 0.23-0.48
        # against themselves, below the 0.363 threshold. Small faces do not
        # give a weak signal, they give a meaningless one.
        assert MIN_FACE_PIXELS >= 80

    def test_threshold_matches_the_published_operating_point(self):
        assert SFACE_COSINE_THRESHOLD == pytest.approx(0.363)


@pytest.mark.camera
class TestRealFaces:
    def test_pipeline_produces_normalised_embeddings(self):
        from vg.infer.faces import FacePipeline
        from vg.ingest.source import CameraSource

        pipeline = FacePipeline()
        cam = CameraSource("t", "webcam:0", target_fps=10)
        if not cam.open():
            pytest.skip("no webcam")

        try:
            for _ in range(60):
                frame = cam.read()
                if frame is None or frame.is_stale:
                    continue
                observations = pipeline.observe(frame.image)
                if observations:
                    embedding = observations[0].embedding
                    assert embedding.shape == (128,)
                    assert np.linalg.norm(embedding) == pytest.approx(1.0, abs=1e-4)
                    return
            pytest.skip("no face in view")
        finally:
            cam.close()

    def test_same_frame_embeds_identically(self):
        from vg.infer.faces import FacePipeline
        from vg.ingest.source import CameraSource

        pipeline = FacePipeline()
        cam = CameraSource("t", "webcam:0", target_fps=10)
        if not cam.open():
            pytest.skip("no webcam")

        try:
            for _ in range(60):
                frame = cam.read()
                if frame is None or frame.is_stale:
                    continue
                faces = pipeline.detector.detect(frame.image)
                if not faces:
                    continue
                a = pipeline.embedder.embed(frame.image, faces[0])
                b = pipeline.embedder.embed(frame.image, faces[0])
                # Determinism check: any drift here is a pipeline bug, not a
                # property of the person.
                assert float(np.dot(a, b)) == pytest.approx(1.0, abs=1e-5)
                return
            pytest.skip("no face in view")
        finally:
            cam.close()
