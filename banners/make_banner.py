"""VisionGuard LinkedIn banners, 1584x396, five styles, drawn entirely in code.
Run: python banners/make_banner.py   ->  banners/banner-1-*.png ... banner-5-*.png
All text starts at x=600 (clear of the profile photo, inside the mobile centre crop).
"""
from pathlib import Path
from PIL import Image, ImageDraw, ImageFont

HERE = Path(__file__).parent
W, H, SS = 1584, 396, 3
BG, INK, SUB, GREEN, MINT = "#f2f5f2", "#1f2b26", "#57655d", "#33705b", "#7cf0bf"
G1, G2, LOGO_GREEN, CREAM = "#cfe8dc", "#9fd3bd", "#5cae91", "#f3e7c4"
S = lambda v: int(v * SS)


def rgb(h, a=255):
    return (int(h[1:3], 16), int(h[3:5], 16), int(h[5:7], 16), a)


def font(name, style, px):
    f = ImageFont.truetype(str(HERE / "fonts" / name), px * SS)
    f.set_variation_by_name(style)
    return f


def lens(d, x, y, s, fill):
    """The mark's lens: a circle-ish blob with one small square-ish corner (bottom-left)."""
    d.rounded_rectangle((x, y, x + s, y + s), radius=s / 2, fill=fill)
    d.rounded_rectangle((x, y + s / 2, x + s / 2, y + s), radius=s * 0.09, fill=fill,
                        corners=(False, False, False, True))


def logo(d, x, y, s, tile=INK, mark=LOGO_GREEN):
    d.rounded_rectangle((x, y, x + s, y + s), radius=s * 0.32, fill=rgb(tile))
    ls = s * 0.46
    lens(d, x + (s - ls) / 2, y + (s - ls) / 2, ls, rgb(mark))


def gradient(size, c1, c2, vertical=False):
    w, h = size
    g = Image.new("RGBA", size)
    gd = ImageDraw.Draw(g)
    n = h if vertical else w
    for i in range(n):
        t = i / max(n - 1, 1)
        col = tuple(int(a + (b - a) * t) for a, b in zip(rgb(c1)[:3], rgb(c2)[:3])) + (255,)
        gd.line((0, i, w, i) if vertical else (i, 0, i, h), fill=col)
    return g


def disc(img, cx, cy, r, c1, c2):
    g = gradient((int(r * 2), int(r * 2)), c1, c2)
    m = Image.new("L", g.size, 0)
    ImageDraw.Draw(m).ellipse((0, 0, g.size[0] - 1, g.size[1] - 1), fill=255)
    img.paste(g, (int(cx - r), int(cy - r)), m)


def text_block(img, ink, sub, label_c, tile=INK, mark=LOGO_GREEN, X=600, support_px=30, label_px=15):
    d = ImageDraw.Draw(img)
    logo_s, gap = 84, 26
    word = font("Rubik.ttf", "Bold", 74)
    support = font("Rubik.ttf", "Regular", support_px)
    label = font("JetBrainsMono.ttf", "Medium", label_px)
    block_h = logo_s + 24 + 38 + 20 + 20
    top = (H - block_h) / 2
    logo(d, S(X), S(top), S(logo_s), tile, mark)
    wb = d.textbbox((0, 0), "VisionGuard", font=word, anchor="ls")
    base = top + logo_s / 2 + (-(wb[1] + wb[3]) / 2) / SS
    d.text((S(X + logo_s + gap), S(base)), "VisionGuard", font=word, fill=rgb(ink), anchor="ls")
    d.text((S(X), S(top + logo_s + 24 + 30)), "AI vision for workplaces.", font=support, fill=rgb(sub), anchor="ls")
    d.text((S(X), S(top + logo_s + 24 + 38 + 20 + 15)), "vision-guard.org", font=label, fill=rgb(label_c), anchor="ls")


def canvas(bg):
    return Image.new("RGBA", (W * SS, H * SS), rgb(bg))


def overlay():
    layer = Image.new("RGBA", (W * SS, H * SS), (0, 0, 0, 0))
    return layer, ImageDraw.Draw(layer)


# 1 ── Light minimal: pale canvas, soft disc, echoed marks on the right
def style1():
    img = canvas(BG)
    disc(img, S(40), S(470), S(300), G1, G2)
    layer, ld = overlay()
    lens(ld, S(1250), S(-60), S(250), rgb(G1))
    lens(ld, S(1390), S(120), S(300), rgb(G2, 200))
    lens(ld, S(1210), S(250), S(150), rgb(GREEN, 150))
    img.alpha_composite(layer)
    ImageDraw.Draw(img).ellipse((S(1356), S(98), S(1372), S(114)), fill=rgb(MINT))
    text_block(img, INK, SUB, GREEN)
    return img


# 2 ── Dark forest: deep ink canvas, soft green glow, mint accent
def style2():
    img = canvas(INK)
    glow, gd = overlay()
    gd.ellipse((S(1100), S(-200), S(1800), S(500)), fill=rgb(GREEN, 120))
    gd.ellipse((S(-250), S(180), S(380), S(700)), fill=rgb(GREEN, 70))
    from PIL import ImageFilter
    glow = glow.filter(ImageFilter.GaussianBlur(S(90)))
    img.alpha_composite(glow)
    layer, ld = overlay()
    lens(ld, S(1330), S(60), S(210), rgb(LOGO_GREEN, 255))
    lens(ld, S(1250), S(250), S(90), rgb(MINT, 255))
    img.alpha_composite(layer)
    text_block(img, "#ffffff", "#a3b0a8", MINT, tile="#2e3933", mark=LOGO_GREEN)
    return img


# 3 -- Soft gradient, refined: calm gradient, one clean concentric-lens motif, strong contrast
def style3():
    img = canvas(G1)
    img.paste(gradient(img.size, "#dcefe5", "#a9d8c4"), (0, 0))
    layer, ld = overlay()
    # one motif on the right: concentric lenses, echoing the logo mark
    lens(ld, S(1250), S(36), S(324), rgb("#ffffff", 95))
    lens(ld, S(1300), S(86), S(224), rgb("#ffffff", 120))
    lens(ld, S(1350), S(136), S(124), rgb(GREEN, 255))
    # a quiet disc behind the profile photo, no other decoration
    ld.ellipse((S(-170), S(240), S(250), S(660)), fill=rgb("#ffffff", 55))
    img.alpha_composite(layer)
    text_block(img, INK, "#2c3d35", "#285a49", support_px=32, label_px=17)
    return img


# 4 ── Mark pattern: a field of small lens marks that fades out toward the text
def style4():
    img = canvas(BG)
    layer, ld = overlay()
    step, size = 44, 20
    for r in range(-1, 10):
        for c in range(-1, 36):
            x, y = c * step + (step / 2 if r % 2 else 0), r * step
            if x > 560 and x < 1300:
                continue
            fade = 0.45
            if x >= 1300:
                fade = min(1, (x - 1300) / 200 + 0.15)
            elif x > 330:
                fade = 0.45 * max(0, (560 - x) / 230)
            if fade <= 0.03:
                continue
            col = rgb(G2 if (r + c) % 3 else G1, int(255 * fade))
            lens(ld, S(x), S(y), S(size), col)
    img.alpha_composite(layer)
    d = ImageDraw.Draw(img)
    lens(d, S(1450), S(176), S(20), rgb(MINT))
    text_block(img, INK, SUB, GREEN)
    return img


# 5 ── Bold split: deep green panel behind the photo, cream mark, pale right
def style5():
    img = canvas(BG)
    d = ImageDraw.Draw(img)
    panel = [(0, 0), (S(520), 0), (S(440), S(H)), (0, S(H))]
    d.polygon(panel, fill=rgb(GREEN))
    layer, ld = overlay()
    lens(ld, S(150), S(-60), S(250), rgb(LOGO_GREEN, 255))
    lens(ld, S(30), S(250), S(130), rgb(CREAM, 255))
    ld.polygon([(S(520), 0), (S(540), 0), (S(460), S(H)), (S(440), S(H))], fill=rgb(MINT))
    img.alpha_composite(layer)
    text_block(img, INK, SUB, GREEN)
    return img


STYLES = [("minimal-light", style1), ("dark-forest", style2), ("soft-gradient", style3),
          ("mark-pattern", style4), ("bold-split", style5)]

for i, (name, fn) in enumerate(STYLES, 1):
    out = fn().convert("RGB").resize((W, H), Image.LANCZOS)
    path = HERE / f"banner-{i}-{name}.png"
    out.save(path)
    print("saved", path.name, out.size)
