"""GUI smoke test: the detector dropdown lists every registered detector."""

import numpy as np
import pytest

from detectors import available_detectors
from tests.synth import fall_sequence, persons_from

tk = pytest.importorskip("tkinter")


@pytest.fixture
def app():
    import gui

    try:
        root = tk.Tk()
    except tk.TclError:
        pytest.skip("no display")
    root.withdraw()
    yield gui.FallDetectionApp(root)
    root.destroy()


def test_dropdown_lists_both_detectors(app):
    values = list(app.detector_box.cget("values"))
    assert values == list(available_detectors().values())
    assert len(values) >= 2
    app.detector.set(available_detectors()["temporal_model"])
    app._refresh_state()
    assert app.selected_detector() == "temporal_model"
    assert str(app.ckpt_entry.cget("state")) == "normal"
    app.detector.set(available_detectors()["rule_based"])
    app._refresh_state()
    assert str(app.ckpt_entry.cget("state")) == "disabled"


def test_draw_overlay_runs():
    import gui
    from detectors import create_detector

    kps, _ = fall_sequence()
    det = create_detector("rule_based")
    det.reset(25.0)
    frame = np.zeros((480, 640, 3), np.uint8)
    for f, persons in enumerate(persons_from(kps)):
        det.update(f, persons)
    out = gui.draw_overlay(frame, persons, det)
    assert out.any()
