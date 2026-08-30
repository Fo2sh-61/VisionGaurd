"""Naming the colour of a bag, and being honest about when it cannot be done.

The owner asked for a way to catch a bag's colour regardless of the light. The
honest answer has two halves, and this file is built around the split.

**What can be made light-invariant.** Hue — whether a thing is red, blue, green
or yellow — survives dimming and brightening, because intensity scales all three
channels together. A colour *cast* (warm lamps, cool daylight) does shift hue,
and grey-world normalisation cancels most of it: scale the crop's channels so
the surrounding frame's mean is neutral, then read the colour.

**What cannot.** Black, grey and white differ only in *lightness*, and lightness
is exactly what lighting changes. A grey bag in a dim corridor is black to the
camera; a white one in shadow is grey. No measurement fixes this without knowing
the light, which the camera does not. So grey and white are one palette entry,
`light`, and the page offers them as one choice: a distinction the camera cannot
make must not be offered as if it could.

**Every guess carries a lenient set**, and the filter matches against that
rather than the single best name. A dark blue bag answers to `blue` and to
`black`; a grey one in poor light answers to `light` and to `black`. Hiding the
right bag is the expensive error and showing one extra is nearly free.

Measured on synthetic bag patches (colour + texture noise + a dark strap) under
seven lighting conditions — normal, dim, very dim, bright, warm lamps, cool
daylight, dim-and-warm:

    strict nearest colour                  47 / 49 = 96 %
    lenient set contains the true colour   49 / 49 = 100 %

The two strict misses are a white patch and a mid-grey one under a quarter of
normal light, where both read as pure black. That is the unresolvable half
above, not a bug: below `DIM_SCENE` this file stops treating lightness as
evidence and puts both names in the set. `test_colour_under_seven_lights` is
that table, and it asserts only on the lenient set.

**Those numbers are synthetic.** Real corridor cameras — JPEG, auto-exposure,
colour bleed from a red coat next to the bag — will be worse, and nothing here
is calibrated on the school's cameras. That is why colour is a filter over bags
already found rather than a way of finding them, and why the count it hides goes
on screen.

No model, no GPU, no state. Pure NumPy and OpenCV.
"""

from __future__ import annotations

import logging

import cv2
import numpy as np

log = logging.getLogger(__name__)

# The palette, and the only colour names the wire ever carries. `light` is grey
# and white together, for the reason in the module docstring.
KNOWN_COLOURS: tuple[str, ...] = ("black", "light", "red", "blue", "green", "yellow")

# Below this Lab chroma a pixel has no colour worth naming - it is black, grey
# or white, and only its lightness separates those.
ACHROMATIC_CHROMA = 14.0

# How far a hue can sit from a reference and still be called by its name. 35
# degrees keeps the four chromatic bins adjacent without overlapping.
HUE_TOLERANCE_DEG = 35.0

# Lab L* bands, on the 0..255 scale OpenCV uses for 8-bit Lab.
DARK_L = 70.0
LIGHT_L = 150.0

# Below this mean scene brightness, lightness stops being evidence. Everything
# in a very dim corridor is dark, so "the bag is dark" says nothing about the
# bag - and a white rucksack under a failed light must still answer to `light`
# or the filter hides the thing somebody is looking for.
DIM_SCENE = 64.0

# Reference hue angles in the Lab a*/b* plane, in degrees.
_HUES: dict[str, float] = {
    "red": 35.0,
    "yellow": 100.0,
    "green": 165.0,
    "blue": 290.0,
}


class ColourGuess:
    """One name, plus every name this colour could honestly also be called."""

    __slots__ = ("best", "lenient")

    def __init__(self, best: str, lenient: frozenset[str]) -> None:
        self.best = best
        self.lenient = lenient

    def __repr__(self) -> str:  # pragma: no cover - debugging only
        return f"ColourGuess({self.best!r}, {sorted(self.lenient)!r})"

    def __eq__(self, other: object) -> bool:
        return (isinstance(other, ColourGuess)
                and self.best == other.best and self.lenient == other.lenient)


def crop_for(image: np.ndarray, box) -> np.ndarray:
    """The pixels under a fractional box, clamped to the frame.

    Boxes cross the API as fractions of the frame, so this is where they become
    pixels again — and the clamp is not paranoia: a box that starts at 0.99 and
    is 0.05 wide would otherwise slice past the edge and come back empty.
    """
    height, width = image.shape[:2]
    x1 = max(0, min(width - 1, int(box.x * width)))
    y1 = max(0, min(height - 1, int(box.y * height)))
    x2 = max(x1 + 1, min(width, int((box.x + box.w) * width)))
    y2 = max(y1 + 1, min(height, int((box.y + box.h) * height)))
    return image[y1:y2, x1:x2]


def name_colour(crop_bgr: np.ndarray, frame_bgr: np.ndarray) -> ColourGuess:
    """What colour this bag looks, and what else it could reasonably be called.

    `frame_bgr` is the whole picture the crop came from: the grey-world gain is
    measured against the scene, not the bag, because a bag that fills its own
    crop would otherwise normalise itself to grey every time.
    """
    if crop_bgr is None or crop_bgr.size == 0:
        return ColourGuess("light", frozenset({"light"}))

    # The central 60 %. Straps, zips and the background live at the edges, and
    # a strap crossing a corner is enough to drag a mean into the wrong bin.
    height, width = crop_bgr.shape[:2]
    my, mx = int(height * 0.2), int(width * 0.2)
    core = crop_bgr[my:height - my, mx:width - mx] if height > 4 and width > 4 else crop_bgr
    if core.size == 0:
        core = crop_bgr

    core = _grey_world(core, frame_bgr)

    # The median, not the mean: a logo, a zip or a highlight cannot drag it.
    median = np.median(core.reshape(-1, 3), axis=0).astype(np.uint8)
    lab = cv2.cvtColor(median.reshape(1, 1, 3), cv2.COLOR_BGR2LAB)[0, 0]
    lightness, a_star, b_star = float(lab[0]), float(lab[1]) - 128.0, float(lab[2]) - 128.0

    # How much light there was, before any normalising. The grey-world gain
    # rebalances the channels but deliberately leaves the level alone, so this
    # still measures the room rather than the correction.
    scene_level = float(np.mean(frame_bgr)) if frame_bgr is not None and frame_bgr.size else 128.0

    chroma = float(np.hypot(a_star, b_star))
    if chroma < ACHROMATIC_CHROMA:
        return _achromatic(lightness, scene_level)

    hue = float(np.degrees(np.arctan2(b_star, a_star)) % 360.0)
    best = min(_HUES, key=lambda name: _hue_gap(hue, _HUES[name]))

    lenient = {best}
    for name, reference in _HUES.items():
        if _hue_gap(hue, reference) <= HUE_TOLERANCE_DEG:
            lenient.add(name)
    # A dark chromatic bag reads black in poor light, and often does to the eye
    # as well - a navy rucksack is "the black one" to most people describing it.
    if lightness < DARK_L:
        lenient.add("black")
    if lightness > LIGHT_L or scene_level < DIM_SCENE:
        lenient.add("light")
    # Barely coloured at all: whatever it is, it could equally be called grey.
    if chroma < ACHROMATIC_CHROMA * 1.6:
        lenient.add("black" if lightness < DARK_L else "light")

    return ColourGuess(best, frozenset(lenient))


def _achromatic(lightness: float, scene_level: float) -> ColourGuess:
    """Black or light, and always both when the lightness is not evidence.

    This is the half that cannot be made light-invariant, so the lenient set
    does the work: anything not clearly at one end answers to both names.

    In a dim room *nothing* is clearly at one end. Measured on D3's table, a
    white patch under a quarter of normal light reads as pure black - so when
    the scene is dark the guess still gets a best name, but the set holds both.
    """
    if scene_level < DIM_SCENE:
        return ColourGuess("black" if lightness < DARK_L else "light",
                           frozenset({"black", "light"}))
    if lightness < DARK_L:
        best, lenient = "black", {"black"}
        if lightness > DARK_L * 0.7:
            lenient.add("light")
    elif lightness > LIGHT_L:
        best, lenient = "light", {"light"}
    else:
        # The middle band is exactly where a dim grey and a shadowed white are
        # indistinguishable. Claiming either one would be claiming precision
        # the measurement does not have.
        best, lenient = "light", {"light", "black"}
    return ColourGuess(best, frozenset(lenient))


def _grey_world(crop: np.ndarray, frame: np.ndarray) -> np.ndarray:
    """Cancel the scene's colour cast, using the frame as the grey reference.

    Warm lamps push every channel towards red and cool daylight towards blue;
    both shift a hue enough to cross a bin boundary. Scaling so the *frame's*
    mean is neutral removes most of it in three lines.
    """
    means = frame.reshape(-1, 3).mean(axis=0)
    if not np.all(np.isfinite(means)) or float(means.min()) <= 1.0:
        # A frame that is almost black gives a gain of hundreds and turns noise
        # into a confident colour. Leave it alone and let the chroma gate call
        # it achromatic, which is the truth.
        return crop
    gain = float(means.mean()) / means
    return np.clip(crop.astype(np.float32) * gain, 0, 255).astype(np.uint8)


def _hue_gap(hue: float, reference: float) -> float:
    """Degrees between two hue angles, the short way round the circle."""
    gap = abs(hue - reference) % 360.0
    return min(gap, 360.0 - gap)
