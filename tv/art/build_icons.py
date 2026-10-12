"""build_icons.py <source image> <android res dir> <preview dir>

Turns the square artwork into Android launcher icons:
  - adaptive icon foreground PNGs (mipmap-*/ic_launcher_foreground.png) + background color
  - legacy rounded-square icons for Android 6-7 (mipmap-*/ic_launcher.png)
  - previews of the adaptive icon under circle / squircle masks
"""
import sys
from pathlib import Path

from PIL import Image, ImageChops, ImageDraw, ImageFilter

SRC, RES, PREVIEW = Path(sys.argv[1]), Path(sys.argv[2]), Path(sys.argv[3])
BG = (10, 1, 53)          # matches the artwork's dark edges (#0a0135)
SCALE = 0.64              # artwork size relative to the 108dp adaptive canvas
DENSITIES = {"mdpi": 1, "hdpi": 1.5, "xhdpi": 2, "xxhdpi": 3, "xxxhdpi": 4}

art = Image.open(SRC).convert("RGB")


def feather_mask(size: int, fade: float) -> Image.Image:
    """Opaque centre fading to transparent over `fade` of each edge."""
    m = Image.new("L", (size, size), 0)
    inset = int(size * fade)
    ImageDraw.Draw(m).rectangle((inset, inset, size - inset, size - inset), fill=255)
    return m.filter(ImageFilter.GaussianBlur(inset / 2))


def adaptive_full(px: int) -> Image.Image:
    """Full 108dp adaptive canvas (background + feathered artwork), opaque."""
    canvas = Image.new("RGB", (px, px), BG)
    art_px = round(px * SCALE)
    scaled = art.resize((art_px, art_px), Image.Resampling.LANCZOS)
    off = (px - art_px) // 2
    canvas.paste(scaled, (off, off), feather_mask(art_px, 0.06))
    return canvas


def rounded(img: Image.Image, radius_frac: float) -> Image.Image:
    size = img.size[0]
    mask = Image.new("L", (size * 4, size * 4), 0)
    ImageDraw.Draw(mask).rounded_rectangle((0, 0, size * 4 - 1, size * 4 - 1), radius=int(size * 4 * radius_frac), fill=255)
    out = img.convert("RGBA")
    out.putalpha(mask.resize((size, size), Image.Resampling.LANCZOS))
    return out


# Adaptive foreground: the whole composite as an opaque layer; background layer is the same colour.
for name, k in DENSITIES.items():
    d = RES / f"mipmap-{name}"
    d.mkdir(parents=True, exist_ok=True)
    adaptive_full(round(108 * k)).save(d / "ic_launcher_foreground.png", optimize=True)
    # Legacy icon (48dp): artwork zoomed slightly so the dancer fills the square, rounded corners.
    px = round(48 * k)
    crop = art.crop((40, 40, art.width - 40, art.height - 40))
    rounded(crop.resize((px, px), Image.Resampling.LANCZOS), 0.18).save(d / "ic_launcher.png", optimize=True)

# Previews: what launchers show (centre 72/108 of the canvas, then masked).
PREVIEW.mkdir(parents=True, exist_ok=True)
full = adaptive_full(432 * 2)
vis = full.crop((full.width // 6, full.width // 6, full.width * 5 // 6, full.width * 5 // 6))
sheet = Image.new("RGB", (1000, 330), (233, 228, 223))
x = 20
for shape, size in (("circle", 288), ("squircle", 288), ("circle", 96), ("squircle", 72), ("circle", 48)):
    icon = vis.resize((size, size), Image.Resampling.LANCZOS).convert("RGBA")
    m = Image.new("L", (size * 4, size * 4), 0)
    if shape == "circle":
        ImageDraw.Draw(m).ellipse((0, 0, size * 4 - 1, size * 4 - 1), fill=255)
    else:
        ImageDraw.Draw(m).rounded_rectangle((0, 0, size * 4 - 1, size * 4 - 1), radius=int(size * 4 * 0.3), fill=255)
    icon.putalpha(ImageChops.multiply(icon.getchannel("A"), m.resize((size, size), Image.Resampling.LANCZOS)))
    sheet.paste(icon, (x, 300 - size), icon)
    x += size + 24
sheet.save(PREVIEW / "adaptive_preview.png")
print("done")
