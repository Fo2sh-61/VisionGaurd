"""Egyptian plates as text. The one guarantee the register is built on.

`vehicle.plate` is `UNIQUE`. That constraint is only worth anything if the
same car always produces the same key — from a camera, from a typed form, from
a spreadsheet. `normalize` is what makes that true, so the first class here is
the most important in the file: if it breaks, a school gets three rows per car
and nobody notices until the gate log stops making sense.

Nothing here loads a model or touches a camera. It runs in milliseconds.
"""

from __future__ import annotations

import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from vg import platetext as pt  # noqa: E402

#: One real plate, in the three ways it reaches this system.
FROM_CAMERA = "ب ج د ١٢٣٤"      # Indic digits, as the model emits them
FROM_KEYBOARD = "ب ج د 1234"     # whichever keyboard the office had
FROM_SPREADSHEET = "بجد١٢٣٤"     # no spaces, exported by something older

CANONICAL = "بجد 1234"


class TestOneCarIsOneKey:
    """The guarantee `UNIQUE` depends on."""

    @pytest.mark.parametrize(
        "raw", [FROM_CAMERA, FROM_KEYBOARD, FROM_SPREADSHEET])
    def test_every_way_a_plate_arrives_lands_on_one_key(self, raw):
        assert pt.normalize(raw) == CANONICAL

    def test_arabic_and_ascii_digits_are_the_same_car(self):
        """Stated on its own because it is the whole reason this module
        exists. A camera reads ١٢٣٤; the office typed 1234."""
        assert pt.normalize(FROM_CAMERA) == pt.normalize(FROM_KEYBOARD)

    def test_persian_digit_variants_are_accepted(self):
        """Readers sometimes emit the Persian forms for the same numerals.
        Treating those as a different car would split one vehicle in two."""
        assert pt.normalize("بجد ۱۲۳۴") == CANONICAL

    @pytest.mark.parametrize("variant,plain", [
        ("أ", "ا"), ("إ", "ا"), ("آ", "ا"), ("ة", "ه"), ("ي", "ى"),
    ])
    def test_letter_variants_are_unified(self, variant, plain):
        """A person and a model will not agree on which of these they meant,
        and a search that distinguishes them finds nothing."""
        assert pt.normalize(f"{variant}ب 12") == pt.normalize(f"{plain}ب 12")

    def test_diacritics_and_zero_width_marks_are_stripped(self):
        assert pt.normalize("بـجـد‏ 1234") == CANONICAL

    def test_the_canonical_form_keeps_letters_arabic_and_digits_ascii(self):
        letters, _, digits = pt.normalize(FROM_CAMERA).partition(" ")

        assert digits.isascii() and digits.isdigit()
        assert not letters.isascii()


class TestNothingIsNotSomething:
    @pytest.mark.parametrize("raw", ["", "   ", "!!!", "---"])
    def test_a_plate_with_no_content_normalises_to_empty(self, raw):
        assert pt.normalize(raw) == ""

    def test_an_empty_plate_scores_zero_and_displays_as_nothing(self):
        assert pt.plausibility("") == 0.0
        assert pt.display("") == ""
        assert pt.transliterate("") == ""


class TestPlausibilityWeighsButNeverRejects:
    """Multiplied into the vote weight, so an odd plate needs more agreement
    before it is recorded. It must never return a hard no: a strange plate
    that is genuinely on a car has to be recordable."""

    def test_a_normal_plate_scores_full(self):
        assert pt.plausibility(CANONICAL) == 1.0

    def test_nonsense_scores_far_lower_but_not_zero(self):
        junk = pt.plausibility("ابجدرسص 12345678")

        assert 0.0 < junk < 0.5, "must weigh down, never reject"

    def test_a_missing_half_is_penalised(self):
        assert pt.plausibility("بجد") < pt.plausibility(CANONICAL)
        assert pt.plausibility("1234") < pt.plausibility(CANONICAL)

    def test_wellformed_is_the_strict_shape_check(self):
        assert pt.is_wellformed(CANONICAL)
        assert not pt.is_wellformed("ابجدرس 12345")
        assert not pt.is_wellformed("بجد")


class TestReadingsOfOneCarMerge:
    """The reason a correct plate does not lose to two wrong ones.

    `ع/٤`, `ه/٥`, `و/٦` are the same shape and the model genuinely returns
    both for one glyph. If those readings split the vote instead of merging,
    three frames never agree and nothing is ever recorded.
    """

    @pytest.mark.parametrize("a,b", [
        ("بجب 1234", "بجت 1234"),     # ب read as ت - same half
        ("بجج 1234", "بجح 1234"),     # ج read as ح - same half
        ("بجد 1234", "بجد 1244"),     # one digit misread
        ("بجد 1234", "بجد 1235"),     # a different digit misread
        ("مب 451", "مجب 451"),        # a dropped letter, not a substitution
    ])
    def test_two_readings_of_one_car_are_the_same_plate(self, a, b):
        assert pt.same_plate(pt.normalize(a), pt.normalize(b))

    def test_a_letter_read_as_a_digit_is_NOT_merged_here(self):
        """The boundary between this module and the reader, and it is sharp.

        `ه/٥` and `و/٦` are the same shape, so the character model returns
        both for one glyph — but `normalize` sorts every glyph into the letter
        half or the digit half by *what it is*, not by where it sat. A `ه`
        misread as `5` therefore moves across the divide and changes both
        halves at once, which `same_plate` correctly refuses to call one car:

            "بجه 1234"  ->  "بجه 1234"
            "بج5 1234"  ->  "بج 51234"      the 5 joined the digits

        Merging those here would mean accepting any pair of readings whose
        letter and digit errors happen to cancel, which is precisely what
        `test_the_halves_are_compared_separately` forbids.

        **So it is settled one layer earlier**, by position: an Egyptian plate
        keeps letters and numbers in separate halves, so a glyph sitting among
        the digits is a digit whatever it looks like. `LETTER_AS_DIGIT` and
        `DIGIT_AS_LETTER` are the tables for that, and `infer/plates.py`
        applies them before a reading ever reaches this module.
        """
        assert not pt.same_plate(pt.normalize("بجه 1234"),
                                 pt.normalize("بج5 1234"))

        # The tables the reader uses to fix it, before normalisation.
        assert pt.LETTER_AS_DIGIT["ه"] == "5"
        assert pt.DIGIT_AS_LETTER["5"] == "ه"
        assert pt.LETTER_AS_DIGIT["و"] == "6"

    def test_settling_by_position_makes_them_one_car_again(self):
        """What the reader does, shown end to end: put the glyph back on the
        side of the plate it was standing on, and the two readings agree."""
        misread = "بج5 1234"
        letters, _, digits = misread.partition(" ")
        settled = "".join(pt.DIGIT_AS_LETTER.get(c, c) for c in letters) + " " + digits

        assert pt.same_plate(pt.normalize("بجه 1234"), pt.normalize(settled))

    def test_two_different_cars_are_not_merged(self):
        assert not pt.same_plate(pt.normalize("بجد 1234"),
                                 pt.normalize("سصط 9876"))

    def test_the_halves_are_compared_separately(self):
        """A plate must not match another because a letter error and a digit
        error happen to cancel out."""
        assert not pt.same_plate(pt.normalize("بجد 1234"),
                                 pt.normalize("بجه 1244"))

    def test_a_reading_missing_a_half_matches_only_itself(self):
        """`"م 4"` must not claim to be every car on the site — which is how
        one bad frame would poison a whole register."""
        thin = pt.normalize("م 4")

        assert not pt.same_plate(thin, CANONICAL)
        assert pt.same_plate(thin, thin)

    def test_empty_matches_nothing_including_empty(self):
        assert not pt.same_plate("", "")
        assert not pt.same_plate("", CANONICAL)


class TestPickingTheFullerReading:
    def test_the_longer_reading_wins_when_both_look_like_plates(self):
        """A dropped character is far more common than an invented one."""
        assert pt.richer("مجب 451", "مب 451") == "مجب 451"

    def test_but_plausibility_beats_length(self):
        assert pt.richer(CANONICAL, "ابجدرسص 12345678") == CANONICAL

    def test_something_beats_nothing(self):
        assert pt.richer("", CANONICAL) == CANONICAL
        assert pt.richer(CANONICAL, "") == CANONICAL


class TestRendering:
    def test_display_spaces_the_letters_and_uses_arabic_digits(self):
        shown = pt.display(CANONICAL)

        assert shown.startswith("ب ج د")
        assert "١٢٣٤" in shown

    def test_display_can_keep_ascii_digits(self):
        assert "1234" in pt.display(CANONICAL, arabic_digits=False)

    def test_transliteration_gives_a_latin_keyboard_something_to_search(self):
        assert pt.transliterate(CANONICAL) == "B G D 1234"

    def test_display_survives_being_encoded_for_a_windows_console(self):
        """A real trap, hit while building this.

        The default Windows console is cp1252 and cannot encode Arabic, so
        `print(plate)` raises `UnicodeEncodeError`. Anything that logs a plate
        must log the canonical or transliterated form, never the rendered one
        — a crash inside a log line would take the camera thread down.
        """
        with pytest.raises(UnicodeEncodeError):
            pt.display(CANONICAL).encode("cp1252")

        # Both of these are safe to put in a log line.
        pt.transliterate(CANONICAL).encode("cp1252")
        CANONICAL.encode("utf-8")


class TestEditDistance:
    def test_identical_is_zero(self):
        assert pt.edit_distance("بجد", "بجد") == 0

    def test_it_gives_up_rather_than_scoring_far_apart_strings(self):
        """Bounded on purpose: this runs per candidate per frame."""
        assert pt.edit_distance("بجد", "سصطعفق", cap=1) > 1

    def test_it_counts_a_dropped_character_as_one_edit(self):
        assert pt.edit_distance("مجب", "مب") == 1


class TestTheCharacterModelGetsTheRawCrop:
    """The regression that made every read close but wrong.

    This shipped feeding `strip_band(...)` and `enhance(...)` to the character
    model. Both are correct for a *text* reader and wrong for a character
    detector: the band scan eats into the digits above a faded band, and
    `enhance` returns a single-channel CLAHE'd, sharpened image, so weights
    trained on colour plate crops were reading greyscale ones. The plates came
    back a character or two off — on the same weights that read them correctly
    in the project they came from.

    Nothing here loads a model. It pins the shape of the call.
    """

    @staticmethod
    def _spy():
        """A `PlateReader` with both models replaced by recorders."""
        import numpy as np

        from vg.infer.plates import PlateBox, PlateReader

        reader = object.__new__(PlateReader)
        frame = np.zeros((240, 320, 3), dtype=np.uint8)
        # Something with colour and structure in it, so a greyscale or
        # band-stripped copy cannot compare equal by accident.
        frame[40:120, 60:260] = (30, 200, 240)
        frame[45:60, 60:260] = (200, 40, 40)      # the coloured band
        box = PlateBox(x1=60, y1=40, x2=260, y2=120, confidence=0.9)

        seen: list = []
        reader.find = lambda _frame: [box]                    # type: ignore
        reader.read_plate = lambda crop: (                    # type: ignore
            seen.append(crop) or ("بجد 1234", 0.8, []))
        return reader, frame, box, seen

    def test_it_is_the_plain_crop_of_the_frame(self):
        import numpy as np

        reader, frame, box, seen = self._spy()

        reader.read_frame(frame)

        assert len(seen) == 1
        assert np.array_equal(seen[0], box.crop(frame)), (
            "the character model must get the crop as photographed")

    def test_it_still_has_its_three_colour_channels(self):
        """`enhance()` returns one channel. That alone changes every read."""
        reader, frame, _box, seen = self._spy()

        reader.read_frame(frame)

        assert seen[0].ndim == 3
        assert seen[0].shape[2] == 3

    def test_the_coloured_band_is_still_on_it(self):
        """The band carries no registration and the model has no class for it,
        so it costs nothing — and cutting it costs whole characters."""
        reader, frame, box, seen = self._spy()

        reader.read_frame(frame)

        assert seen[0].shape[0] == box.crop(frame).shape[0], (
            "no rows may be trimmed off the top of the plate")

    def test_the_helpers_are_still_here_and_still_out_of_the_path(self):
        """They are correct for the reader they were written for. Keeping them
        importable is fine; calling them from `read_frame` is the bug."""
        import inspect

        from vg.infer import plates

        assert callable(plates.strip_band)
        assert callable(plates.enhance)

        # Comments in that function name both, deliberately. Read the code.
        code = "".join(line.split("#")[0] for line
                       in inspect.getsource(plates.PlateReader.read_frame).splitlines())
        assert "strip_band(" not in code
        assert "enhance(" not in code


class TestThePlateModelsAreCalledAsTheyWereTrained:
    """The second half of the same regression, and the more expensive half.

    The character assembly in `infer/plates.py` is a faithful port — the
    grouping, the letter/digit settling and the reading order are identical to
    gate-anpr's, function for function. What was not identical was **how the
    models were called**: this engine asked for FP16 and a TensorRT plan, and
    set NMS at 0.45 where ultralytics defaults to 0.7 and gate-anpr takes the
    default.

    A person detector has room for that. A model deciding which of 38
    characters a twenty-pixel glyph is has less, and the cost shows up as a
    plate that is nearly right — which is worse than one that is obviously
    wrong, because it reaches the register and matches nobody.

    These pin the shipped configuration. Changing any of them is allowed; doing
    it without running `engine/tools/compare_plates.py` first is not.
    """

    @staticmethod
    def _models():
        from vg import config as vgconfig

        cfg = vgconfig.load()
        return cfg.models["plates"], cfg.models["plate_chars"]

    def test_both_run_at_full_precision(self):
        """gate-anpr passes no precision argument at all, so it gets FP32."""
        plates, chars = self._models()

        assert plates.half is False
        assert chars.half is False

    def test_neither_uses_a_tensorrt_plan(self):
        """A plan is compiled at a fixed input size, and the accuracy of the
        weights it came from is not a promise it makes."""
        plates, chars = self._models()

        assert plates.accelerate is False
        assert chars.accelerate is False

    def test_nms_matches_the_library_default_gate_anpr_relies_on(self):
        plates, chars = self._models()

        assert plates.iou == 0.7
        assert chars.iou == 0.7

    def test_the_detector_threshold_is_gate_anprs(self):
        """`min_detect_conf: float = 0.35` in `anpr/config.py`."""
        plates, _ = self._models()

        assert plates.conf == 0.35

    def test_the_character_thresholds_are_gate_anprs_two_tier_rule(self):
        """A weak box may only ever be an alternative reading of a character
        already found, never an extra character. That is what makes the low
        floor safe."""
        from vg.infer import plates as p

        assert p.ALT_CONF == 0.10
        assert p.DETECT_CONF == 0.25
        assert p.READ_WIDTH == 320

    def test_accelerate_defaults_to_true_for_every_other_model(self):
        """This is an opt-out for two models, not a retreat from TensorRT."""
        from vg import config as vgconfig

        others = {name: m for name, m in vgconfig.load().models.items()
                  if name not in ("plates", "plate_chars")}

        assert others, "no other models configured - has engine.yaml changed?"
        assert all(m.accelerate for m in others.values())

    def test_the_flag_actually_reaches_the_loader(self):
        """A config key nothing reads is a setting somebody believes they
        changed."""
        import inspect

        from vg.infer.shared import load_model

        source = inspect.getsource(load_model)
        assert "if not accelerate:" in source
