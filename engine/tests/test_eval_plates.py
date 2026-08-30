"""The scoring behind the accuracy verdict, without a model in sight.

`eval_plates.py` answers one question — how often does the reader get a plate
exactly right — and that answer is about to decide whether the plate models
get replaced. So the arithmetic underneath it has to be pinned separately
from the models, and fast enough to run every time.

Everything here is the pure half: parsing a label file, deciding whether a
found box is the labelled plate, deciding whether a reading is correct, and
splitting on the width that P6-FR-037's target is stated at. No GPU, no
weights, milliseconds.

**Why `normalize` decides correctness rather than `==`.** The same car
reaches this comparison as `ب ج د ١٢٣٤` from a model and `بجد 1234` from a
person typing truth, and those are the same plate. Comparing raw strings
would score a perfect reader at zero.
"""

from __future__ import annotations

import importlib.util
from pathlib import Path

import pytest

#: Derived from `__file__`, never from the working directory.
#:
#: `test_track_page.py` loads its tool with a relative path and fails whenever
#: pytest is run from `engine/` rather than the repo root — one of the three
#: failures already in this suite. Same trick, without the bug.
TOOL = Path(__file__).resolve().parents[1] / "tools" / "eval_plates.py"


def _load():
    spec = importlib.util.spec_from_file_location("eval_plates", TOOL)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


@pytest.fixture(scope="module")
def tool():
    """The tool, imported without importing torch.

    If this raises `ImportError` on ultralytics, the heavy imports have leaked
    to module scope — which would also make every run of the tool slow to
    start and impossible to test. Keep them inside the functions.
    """
    return _load()


class TestReadingALabelFile:
    """YOLO's format: `class cx cy w h`, every value a fraction."""

    def test_one_plate(self, tool):
        boxes = tool.parse_label("0 0.5 0.5 0.1 0.05", 1000, 800)

        assert len(boxes) == 1
        assert boxes[0] == pytest.approx((450.0, 380.0, 550.0, 420.0))

    def test_the_centre_is_not_the_corner(self, tool):
        """The commonest way to get this wrong, and it fails quietly: boxes
        land offset by half their size and IoU sags instead of collapsing."""
        (x1, y1, x2, y2), = tool.parse_label("0 0.25 0.25 0.5 0.5", 100, 100)

        assert (x1, y1, x2, y2) == pytest.approx((0.0, 0.0, 50.0, 50.0))

    def test_several_plates_in_one_photo(self, tool):
        """51 of the owner's 2,087 images have more than one."""
        boxes = tool.parse_label(
            "0 0.25 0.5 0.1 0.05\n0 0.75 0.5 0.1 0.05", 1000, 800)

        assert len(boxes) == 2

    def test_blank_lines_are_not_plates(self, tool):
        assert tool.parse_label("0 0.5 0.5 0.1 0.05\n\n  \n", 100, 100) != []
        assert len(tool.parse_label("0 0.5 0.5 0.1 0.05\n\n", 100, 100)) == 1

    def test_an_empty_label_file_is_no_plates_not_an_error(self, tool):
        """A photo with no plate in it is a legitimate negative."""
        assert tool.parse_label("", 100, 100) == []

    def test_a_malformed_line_is_refused_loudly(self, tool):
        """Silently skipping a bad line quietly shrinks the denominator, and
        the score goes up for the wrong reason."""
        with pytest.raises(ValueError):
            tool.parse_label("0 0.5 0.5", 100, 100)


class TestWhetherTheBoxIsTheRightBox:
    def test_a_perfect_overlap(self, tool):
        assert tool.iou((0, 0, 10, 10), (0, 0, 10, 10)) == pytest.approx(1.0)

    def test_no_overlap_at_all(self, tool):
        assert tool.iou((0, 0, 10, 10), (50, 50, 60, 60)) == 0.0

    def test_touching_edges_do_not_count_as_overlap(self, tool):
        assert tool.iou((0, 0, 10, 10), (10, 0, 20, 10)) == 0.0

    def test_half_covered(self, tool):
        # Intersection 50, union 150.
        assert tool.iou((0, 0, 10, 10), (5, 0, 15, 10)) == pytest.approx(1 / 3)

    def test_a_zero_area_box_cannot_match(self, tool):
        assert tool.iou((5, 5, 5, 5), (0, 0, 10, 10)) == 0.0


class TestMatchingWhatWasFoundToWhatIsThere:
    def test_one_plate_found(self, tool):
        found, missed, extra = tool.match_boxes(
            [(0, 0, 100, 40)], [(2, 1, 101, 41)])

        assert len(found) == 1 and missed == 0 and extra == 0

    def test_a_plate_the_detector_walked_past(self, tool):
        found, missed, extra = tool.match_boxes([(0, 0, 100, 40)], [])

        assert found == [] and missed == 1 and extra == 0

    def test_something_that_is_not_a_plate(self, tool):
        found, missed, extra = tool.match_boxes([], [(0, 0, 100, 40)])

        assert found == [] and missed == 0 and extra == 1

    def test_a_box_in_the_wrong_place_is_a_miss_and_a_false_alarm(self, tool):
        """Not a near-miss. It failed to find the plate *and* it invented one,
        and a score that counted it once would flatter the detector."""
        found, missed, extra = tool.match_boxes(
            [(0, 0, 100, 40)], [(500, 500, 600, 540)])

        assert found == [] and missed == 1 and extra == 1

    def test_each_true_plate_is_claimed_once(self, tool):
        """Two boxes on one plate is one hit and one false alarm — otherwise a
        detector that sprayed boxes everywhere would score perfectly."""
        found, missed, extra = tool.match_boxes(
            [(0, 0, 100, 40)], [(0, 0, 100, 40), (1, 1, 99, 39)])

        assert len(found) == 1 and missed == 0 and extra == 1

    def test_the_better_overlap_wins(self, tool):
        truth = (0, 0, 100, 40)
        found, _, _ = tool.match_boxes(truth and [truth],
                                       [(20, 5, 110, 45), (0, 0, 100, 40)])

        assert found[0][1] == (0, 0, 100, 40)


class TestWhetherTheReadingIsRight:
    def test_the_same_plate_written_two_ways_is_correct(self, tool):
        """Indic digits off a camera against ASCII digits typed by a person."""
        assert tool.exact_read("ب ج د ١٢٣٤", "بجد 1234") is True

    def test_a_wrong_digit_is_wrong(self, tool):
        assert tool.exact_read("بجد 1235", "بجد 1234") is False

    def test_a_dropped_letter_is_wrong(self, tool):
        """Exact means exact — `same_plate`'s one-edit tolerance is for
        merging votes, never for grading."""
        assert tool.exact_read("بج 1234", "بجد 1234") is False

    def test_reading_nothing_is_wrong_not_skipped(self, tool):
        assert tool.exact_read("", "بجد 1234") is False

    def test_a_spurious_reading_against_no_truth_is_wrong(self, tool):
        assert tool.exact_read("بجد 1234", "") is False


class TestTheWidthTheTargetIsStatedAt:
    def test_the_target_is_the_one_the_spec_names(self, tool):
        """P6-FR-037: at least 95% exact on plates at least 100 px wide."""
        assert tool.READABLE_WIDTH_PX == 100

    def test_a_comfortable_plate_counts_towards_the_target(self, tool):
        assert tool.counts_towards_target((0, 0, 134, 40)) is True

    def test_exactly_the_line_counts(self, tool):
        assert tool.counts_towards_target((0, 0, 100, 40)) is True

    def test_a_distant_plate_is_measured_but_not_targeted(self, tool):
        """Below the line is reported with no target attached — that regime
        belongs to where the camera is pointed, not to the software."""
        assert tool.counts_towards_target((0, 0, 61, 20)) is False


class TestTheDatasetIsReadAsItActuallyIs:
    def test_uppercase_extensions_are_not_dropped(self, tool):
        """56 of the owner's 2,087 images are `.JPG` or `.jpeg`. Globbing
        `*.jpg` alone silently loses 2.7% of the set."""
        assert {e.lower() for e in tool.IMAGE_SUFFIXES} == {
            ".jpg", ".jpeg", ".png"}

    def test_the_class_list_is_not_a_label_file(self, tool):
        """`classes.txt` sits beside the labels and is not one. Counting it
        as an orphan was in the plan until the inventory caught it."""
        assert tool.is_label_file(Path("0001.txt")) is True
        assert tool.is_label_file(Path("classes.txt")) is False
