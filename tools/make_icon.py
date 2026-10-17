"""Build the Windows icon from the console's own logo mark.

`web/src/components/Logo.tsx` is the mark: a rounded square filled with the
accent colour, with a single "lens" cut out of it - a circle whose bottom-left
corner is square. This redraws exactly that, at the sizes Windows asks for,
into `assets/visionguard.ico` - and a phone-shaped variant of it into
`assets/visionguard-mobile.ico`, for the phone app's shortcut. It also writes
the PNG icons that make both apps installable (spec 016): 192 and 512 px, and a
512 px "maskable" one, into `web/public/` and `mobile/public/`.

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

#: The phone app draws the very same logo, so a second square icon would
#: leave the label as the only way to tell the two desktop shortcuts apart.
OUT_MOBILE = REPO / "assets" / "visionguard-mobile.ico"

#: Where each app's installable icons go. Both get the square mark: on a
#: phone's home screen the phone-shaped variant would be a phone in a phone.
PUBLIC = (REPO / "web" / "public", REPO / "mobile" / "public")

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

#: The phone variant: the body about as wide as a phone is for its height,
#: and the lens shrunk to suit it - at full size it filled the narrower body
#: edge to edge and read as the square mark squeezed.
PHONE_WIDTH = 0.62
PHONE_LENS = 0.8

#: The speaker slot is what makes the shape read as a phone rather than a
#: tall tile, but below 32px it is less than a pixel high - a smudge, not a
#: slot - so the small sizes go without it.
PHONE_SLOT_FROM = 32


def _draw(size: int, phone: bool = False) -> Image.Image:
    """The mark at one size, drawn large and shrunk.

    `phone` draws the phone app's variant: the same body, lens and colours,
    narrower than it is tall.
    """
    big = size * SUPERSAMPLE
    image = Image.new("RGBA", (big, big), (0, 0, 0, 0))
    draw = ImageDraw.Draw(image)

    inset = big * MARGIN
    square = big - 2 * inset
    # For the square mark `body` is `square` and `edge` is `inset`, exactly,
    # so the web icon comes out byte for byte what it was before this.
    body = square * PHONE_WIDTH if phone else square
    edge = inset + (square - body) / 2
    draw.rounded_rectangle(
        [edge, inset, edge + body, inset + square],
        radius=body * OUTER_RADIUS,
        fill=ACCENT,
    )

    # The lens. A circle plus a square over its bottom-left quadrant, unioned
    # by drawing both into the same image - PIL takes one radius for all four
    # corners, so a per-corner shape has to be built rather than asked for.
    lens = square * LENS_SIZE * (PHONE_LENS if phone else 1)
    cx = cy = big / 2
    _lens(draw, cx, cy, lens)

    if phone and size >= PHONE_SLOT_FROM:
        slot_width, slot_height = body * 0.26, square * 0.04
        slot_top = inset + square * 0.09
        draw.rounded_rectangle(
            [cx - slot_width / 2, slot_top,
             cx + slot_width / 2, slot_top + slot_height],
            radius=slot_height / 2,
            fill=PANEL,
        )

    return image.resize((size, size), Image.LANCZOS)


def _lens(draw: ImageDraw.ImageDraw, cx: float, cy: float, lens: float) -> None:
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


def _draw_maskable(size: int) -> Image.Image:
    """The mark for a launcher that crops icons to its own shape.

    Android cuts a circle, squircle or teardrop out of a maskable icon, so the
    accent fills the whole canvas and only the lens carries the shape. The
    lens is the same share of the canvas as on the plain icon, well inside the
    safe zone (the middle 80%) that every launcher keeps.
    """
    big = size * SUPERSAMPLE
    image = Image.new("RGBA", (big, big), ACCENT)
    _lens(ImageDraw.Draw(image), big / 2, big / 2, big * (1 - 2 * MARGIN) * LENS_SIZE)
    return image.resize((size, size), Image.LANCZOS)


def write_pngs() -> None:
    for folder in PUBLIC:
        folder.mkdir(parents=True, exist_ok=True)
        for name, image in (
            ("icon-192.png", _draw(192)),
            ("icon-512.png", _draw(512)),
            ("icon-maskable-512.png", _draw_maskable(512)),
        ):
            image.save(folder / name, format="PNG", optimize=True)
        print(f"wrote {folder.relative_to(REPO)} - icon-192, icon-512, "
              f"icon-maskable-512")


def main() -> int:
    OUT.parent.mkdir(parents=True, exist_ok=True)
    for out, phone in ((OUT, False), (OUT_MOBILE, True)):
        frames = [_draw(s, phone) for s in SIZES]
        # Pillow writes every size given in `sizes` from the image it is
        # called on, so the largest is passed as the base and the rest as
        # already-drawn frames - otherwise every size is a resample of one
        # bitmap and the small ones lose the lens.
        frames[-1].save(out, format="ICO",
                        sizes=[(s, s) for s in SIZES],
                        append_images=frames[:-1])
        print(f"wrote {out.relative_to(REPO)} - "
              f"{', '.join(str(s) for s in SIZES)}px")
    write_pngs()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
