"""Which weights a runner actually opens, and whether it says so.

**This file exists because of a silence.** The repo carried five TensorRT
engines. No configuration referenced any of them. The library that loads them
was not importable. One was built at 480x480 for a model configured at 640,
which a static-shape plan cannot serve. The product had been running
unaccelerated for months and nothing on any screen said so.

That is not a performance bug, it is a truthfulness bug — the same class as a
page showing fixtures. P6-FR-033 and P6-FR-035 exist because of it, and these
tests are what keep the answer honest.

The design being pinned: **the input size lives in the filename.** A TensorRT
plan has static shapes, so an engine built at one size cannot serve a model
configured at another. Putting the size in the name means a 640 config never
names the 480 file, so "reject a wrong-size build" needs no comparison logic
at all — it cannot happen. Tests below prove the naming carries that weight.
"""

from __future__ import annotations

import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "tools"))

from vg.infer import shared  # noqa: E402
from vg.infer.shared import (  # noqa: E402
    TENSORRT,
    UNACCELERATED,
    engine_path_for,
    weights_to_load,
)


@pytest.fixture
def weights(tmp_path: Path) -> Path:
    """A stand-in .pt. Nothing here loads a model — this is name arithmetic."""
    path = tmp_path / "yolov8s.pt"
    path.write_bytes(b"not really a model")
    return path


@pytest.fixture
def with_tensorrt(monkeypatch):
    """Pretend TensorRT imports, so the choice is about files not this machine."""
    monkeypatch.setattr(shared, "tensorrt_available", lambda: True)


@pytest.fixture
def without_tensorrt(monkeypatch):
    monkeypatch.setattr(shared, "tensorrt_available", lambda: False)


class TestTheNameCarriesTheSize:
    def test_the_engine_name_includes_the_input_size(self, weights):
        assert engine_path_for(weights, 640).name == "yolov8s-640.engine"
        assert engine_path_for(weights, 480).name == "yolov8s-480.engine"

    def test_it_sits_beside_the_weights(self, weights):
        assert engine_path_for(weights, 640).parent == weights.parent

    def test_this_matches_the_convention_already_on_disk(self):
        """`yolov8s-480.engine`, `yolov8s-pose-640.engine` were named this way
        long before this helper existed. Following the existing convention is
        what lets the rule enforce itself rather than needing to be checked."""
        assert engine_path_for(Path("models/yolov8s-pose.pt"), 640).name == (
            "yolov8s-pose-640.engine"
        )


class TestChoosingWhatToLoad:
    def test_the_engine_wins_when_it_exists(self, weights, with_tensorrt):
        engine_path_for(weights, 640).write_bytes(b"engine")

        chosen, form = weights_to_load(weights, 640)

        assert chosen.name == "yolov8s-640.engine"
        assert form == TENSORRT

    def test_the_weights_are_used_when_no_engine_was_built(
        self, weights, with_tensorrt
    ):
        chosen, form = weights_to_load(weights, 640)

        assert chosen == weights
        assert form == UNACCELERATED

    def test_a_wrong_size_engine_is_never_picked_up(self, weights, with_tensorrt):
        """The rule that enforces itself.

        An engine built for 480 exists. The model is configured at 640. A
        static-shape plan cannot serve that, and here it is not even a
        decision — the 640 config asks for a filename that does not exist.
        """
        engine_path_for(weights, 480).write_bytes(b"engine for the wrong size")

        chosen, form = weights_to_load(weights, 640)

        assert chosen == weights, "a 480 engine must not serve a 640 config"
        assert form == UNACCELERATED

    def test_an_engine_is_ignored_when_tensorrt_cannot_be_imported(
        self, weights, without_tensorrt
    ):
        """Exactly the state this repo was found in: engines on disk, library
        gone. Falling back is right; falling back **silently** is what made it
        invisible for months, so the form must change too."""
        engine_path_for(weights, 640).write_bytes(b"engine")

        chosen, form = weights_to_load(weights, 640)

        assert chosen == weights
        assert form == UNACCELERATED

    def test_the_fallback_is_the_gpu_weights_never_the_processor(
        self, weights, without_tensorrt
    ):
        """`weights_to_load` chooses a FILE, never a device.

        Device selection stays in `_resolve_device`, so a missing engine costs
        acceleration and never quietly drops the whole product onto the CPU.
        """
        chosen, _ = weights_to_load(weights, 640)

        assert chosen.suffix == ".pt"


class TestItAlwaysSaysWhichOneItGot:
    """P6-FR-035. The form is the whole point — an unaccelerated run that
    announces itself is a slower product; one that does not is a lie."""

    @pytest.mark.parametrize("built", [True, False])
    def test_a_form_is_always_returned(self, weights, with_tensorrt, built):
        if built:
            engine_path_for(weights, 640).write_bytes(b"engine")

        _, form = weights_to_load(weights, 640)

        assert form in (TENSORRT, UNACCELERATED)

    def test_the_two_forms_are_distinguishable_in_a_sentence(self):
        """These strings are printed into System Health. If they ever collide,
        the page stops answering the question it exists to answer."""
        assert TENSORRT != UNACCELERATED
        assert TENSORRT and UNACCELERATED


class _FakeYOLO:
    """Stands in for ultralytics.YOLO. Like the real one, a plan is only
    opened on the first predict - which is where a stale one fails."""

    opened: list[str] = []

    def __init__(self, path, task=None):
        self.path = str(path)

    def predict(self, *args, **kwargs):
        _FakeYOLO.opened.append(self.path)
        if self.path.endswith(".engine"):
            raise AttributeError(
                "'NoneType' object has no attribute 'create_execution_context'")
        return []


@pytest.fixture
def fake_yolo(monkeypatch):
    import ultralytics

    _FakeYOLO.opened = []
    monkeypatch.setattr(ultralytics, "YOLO", _FakeYOLO)
    return _FakeYOLO


class TestAStalePlanFallsBack:
    """First site install, 18 Oct 2026: plans built by TensorRT 11.2 met
    TensorRT 11.4. They deserialised to None on the first predict - after
    `load_model`'s try - and the engine would not start at all."""

    def test_a_plan_that_will_not_open_falls_back_to_the_weights(
        self, weights, with_tensorrt, fake_yolo
    ):
        engine_path_for(weights, 640).write_bytes(b"plan from another TensorRT")

        model, loaded, form = shared.load_model(weights, 640)

        assert loaded == weights
        assert form == UNACCELERATED
        assert model.path == str(weights)
        assert fake_yolo.opened == [str(engine_path_for(weights, 640))]

    def test_engine_opens_names_the_reason(self, weights, fake_yolo):
        plan = engine_path_for(weights, 640)
        plan.write_bytes(b"stale")

        why = shared.engine_opens(plan, 640)

        assert why and "create_execution_context" in why

    def test_the_build_tool_rebuilds_a_stale_plan_instead_of_calling_it_present(
        self, weights, monkeypatch
    ):
        import build_engines

        engine_path_for(weights, 640).write_bytes(b"stale")
        monkeypatch.setattr(build_engines, "engine_opens", lambda *a: "will not open")
        import ultralytics

        class Exporter:
            def __init__(self, path):
                pass

            def export(self, **kwargs):
                out = weights.with_suffix(".engine")
                out.write_bytes(b"fresh plan")
                return str(out)

        monkeypatch.setattr(ultralytics, "YOLO", Exporter)

        status, _ = build_engines.build("person", weights, 640, False, False)

        assert status == "built"
        assert engine_path_for(weights, 640).read_bytes() == b"fresh plan"


class TestProbingThisMachine:
    def test_availability_is_a_bool_and_does_not_raise(self):
        """Whatever is or is not installed, asking must be safe: this runs
        during model construction on every start."""
        assert isinstance(shared.tensorrt_available(), bool)

    def test_a_broken_install_reads_as_unavailable(self, monkeypatch):
        """An import that succeeds and then fails on use is the failure mode
        that cost this project two builds — the cu13 wheel imports fine and
        segfaults at `trt.Builder()`. Anything that raises means no."""
        import builtins

        real_import = builtins.__import__

        def explode(name, *args, **kwargs):
            if name == "tensorrt":
                raise ImportError("half-installed")
            return real_import(name, *args, **kwargs)

        monkeypatch.setattr(builtins, "__import__", explode)

        assert shared.tensorrt_available() is False
