"""Build the Windows icon from the console's own logo mark.

`web/src/components/Logo.tsx` is the mark: a rounded square filled with the
accent colour, with a single "lens" cut out of it - a circle whose bottom-left
corner is square. This redraws exactly that, at the sizes Windows asks for,
into `assets/visionguard.ico`.

Redrawn rather than exported because the mark is CSS, not a file: it is two
divs and a border-radius. The numbers below are lifted straight from that
component and from `web/src/styles/tokens.css`, so if the mark changes this
script is the one place to update - and the icon is a build output, never
something to edit by hand.

    python tools/make_icon.py

Everything is drawn at 8x and shrunk with LANCZOS. Rounded corners at 16px
drawn directly are a staircase; supersampling is what makes a small icon look
like a shape rather than an artefact.
"""

from __future__ import annotations

from pathlib import Path

from PIL import Image, ImageDraw

REPO = Path(__file__).resolve().parents[1]
OUT = REPO / "assets" / "visionguard.ico"

#: From `web/src/styles/tokens.css`. The LIGHT theme's values: an icon sits on
#: a taskbar, not inside the app, so it cannot follow the viewer's theme and
#: has to pick one. Light is the one the mark was designed against.
ACCENT = (0x33, 0x70, 0x5B, 0xFF)   # --ac
PANEL = (0xE9, 0xEF, 0xE9, 0xFF)    # --panel

#: From `Logo.tsx`. `borderRadius: size * 0.32` on the outer square, an inner
#: square of `size * 0.43`, and `borderRadius: '50% 50% 50% 4px'` on it -
#: which is CSS for "circle, except the bottom-left corner". At the size the
#: component is normally drawn (28px) that 4px is a third of the inner box, so
#: it is carried here as a fraction rather than a pixel count: a fixed 4px
#: would vanish at 16px and dominate at 256.
OUTER_RADIUS = 0.32
LENS_SIZE = 0.43
LENS_CORNER = 0.33

#: A margin so the square does not touch the edge of the canvas. Windows draws
#: icons hard against their bounds, and a mark that fills every pixel reads as
#: clipped rather than as deliberate.
MARGIN = 0.06

#: Every size Windows actually asks for. 16 is the title bar, 32 the desktop
#: at 100%, 256 the "extra large icons" view and the Alt-Tab card.
SIZES = (16, 20, 24, 32, 40, 48, 64, 128, 256)

SUPERSAMPLE = 8


def _draw(size: int) -> Image.Image:
    """The mark at one size, drawn large and shrunk."""
    big = size * SUPERSAMPLE
    image = Image.new("RGBA", (big, big), (0, 0, 0, 0))
    draw = ImageDraw.Draw(image)

    inset = big * MARGIN
    square = big - 2 * inset
    draw.rounded_rectangle(
        [inset, inset, inset + square, inset + square],
        radius=square * OUTER_RADIUS,
        fill=ACCENT,
    )

    # The lens. A circle plus a square over its bottom-left quadrant, unioned
    # by drawing both into the same image - PIL takes one radius for all four
    # corners, so a per-corner shape has to be built rather than asked for.
    lens = square * LENS_SIZE
    cx = cy = big / 2
    left, top = cx - lens / 2, cy - lens / 2
    draw.ellipse([left, top, left + lens, top + lens], fill=PANEL)
    draw.rounded_rectangle(
        [left, cy, cx, cy + lens / 2],
        radius=lens * LENS_CORNER,
        fill=PANEL,
        # (top-left, top-right, bottom-right, bottom-left) - only the corner
        # the CSS squares off keeps any rounding at all.
        corners=(False, False, False, True),
    )

    return image.resize((size, size), Image.LANCZOS)


def main() -> int:
    OUT.parent.mkdir(parents=True, exist_ok=True)
    frames = [_draw(s) for s in SIZES]
    # Pillow writes every size given in `sizes` from the image it is called
    # on, so the largest is passed as the base and the rest as already-drawn
    # frames - otherwise every size is a resample of one bitmap and the small
    # ones lose the lens.
    frames[-1].save(OUT, format="ICO",
                    sizes=[(s, s) for s in SIZES],
                    append_images=frames[:-1])
    print(f"wrote {OUT.relative_to(REPO)} - {', '.join(str(s) for s in SIZES)}px")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
