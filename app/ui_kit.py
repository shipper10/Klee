"""Shared drawing helpers for report images (Pillow only, deterministic, no network).

The look follows the dark-navy / cream-gold style of HoYoLAB Battle Chronicle share cards, drawn from scratch:
no HoYoverse artwork is bundled, and no HoYoverse logo or QR code is reproduced.
"""

from __future__ import annotations

import io
import math
from functools import lru_cache
from pathlib import Path

from PIL import Image, ImageDraw, ImageFont, ImageOps

FONT_DIR = Path(__file__).parent / "assets" / "fonts"

# Palette sampled by eye from the official share cards.
BG_TOP = (30, 30, 70)
BG_BOTTOM = (13, 14, 36)
PANEL = (255, 255, 255, 20)
PANEL_BORDER = (255, 255, 255, 38)
TEXT = (238, 238, 246)
MUTED = (164, 166, 196)
GOLD = (226, 201, 150)
GOLD_DARK = (58, 51, 64)
STAR_ON = (244, 236, 214)
STAR_OFF = (255, 255, 255, 46)
STRIP = (239, 230, 211)

RARITY_BG = {
    5: ((236, 176, 98), (190, 126, 58)),
    4: ((166, 132, 226), (108, 82, 168)),
}
DEFAULT_RARITY_BG = ((112, 118, 140), (76, 80, 100))


@lru_cache(maxsize=64)
def font(name: str, size: int) -> ImageFont.FreeTypeFont:
    files = {
        "regular": "Inter-Regular.otf",
        "medium": "Inter-Medium.otf",
        "semibold": "Inter-SemiBold.otf",
        "bold": "Inter-Bold.otf",
        "serif": "SourceSerifPro-Semibold.ttf",
        "serif-bold": "SourceSerifPro-Bold.ttf",
    }
    return ImageFont.truetype(str(FONT_DIR / files[name]), size)


def vertical_gradient(width: int, height: int, top: tuple, bottom: tuple) -> Image.Image:
    base = Image.new("RGB", (1, height))
    px = base.load()
    for y in range(height):
        t = y / max(1, height - 1)
        px[0, y] = tuple(round(top[i] + (bottom[i] - top[i]) * t) for i in range(3))
    return base.resize((width, height))


def new_canvas(width: int, height: int) -> tuple[Image.Image, ImageDraw.ImageDraw]:
    img = vertical_gradient(width, height, BG_TOP, BG_BOTTOM)
    return img, ImageDraw.Draw(img, "RGBA")


def panel(d: ImageDraw.ImageDraw, box: tuple[int, int, int, int], radius: int = 22, fill=PANEL, outline=PANEL_BORDER) -> None:
    d.rounded_rectangle(box, radius=radius, fill=fill, outline=outline, width=2)


def fit_text(d: ImageDraw.ImageDraw, text: str, fnt: ImageFont.FreeTypeFont, max_width: int) -> str:
    if d.textlength(text, font=fnt) <= max_width:
        return text
    while text and d.textlength(text + "…", font=fnt) > max_width:
        text = text[:-1]
    return text + "…"


def draw_star(d: ImageDraw.ImageDraw, cx: float, cy: float, r: float, fill) -> None:
    """Six-pointed star (like the Abyss star icon): two overlapping triangles."""
    for rot in (-90, 90):
        pts = [
            (cx + r * math.cos(math.radians(rot + k * 120)), cy + r * math.sin(math.radians(rot + k * 120)))
            for k in range(3)
        ]
        d.polygon(pts, fill=fill)


def draw_stars(d: ImageDraw.ImageDraw, right: int, cy: int, filled: int, total: int, r: int = 17, gap: int = 12) -> None:
    x = right - r
    for i in range(total - 1, -1, -1):
        draw_star(d, x, cy, r, STAR_ON if i < filled else STAR_OFF)
        x -= 2 * r + gap


def load_icon(data: bytes | None) -> Image.Image | None:
    if not data:
        return None
    try:
        im = Image.open(io.BytesIO(data))
        im.load()
        return im.convert("RGBA")
    except Exception:  # corrupt or unsupported image: treat like a missing icon
        return None


def character_tile(
    img: Image.Image,
    d: ImageDraw.ImageDraw,
    x: int,
    y: int,
    size: int,
    *,
    rarity: int,
    level: int | str | None,
    icon: Image.Image | None,
    strip_font_size: int = 22,
) -> int:
    """Draw a rarity-coloured portrait tile with a cream level strip. Returns its total height."""
    strip_h = round(size * 0.24) if level is not None else 0
    top, bottom = RARITY_BG.get(rarity, DEFAULT_RARITY_BG)
    bg = vertical_gradient(size, size, top, bottom).convert("RGBA")
    if icon is not None:
        fitted = ImageOps.fit(icon, (size, size), method=Image.LANCZOS, centering=(0.5, 0.3))
        bg.alpha_composite(fitted)
    else:
        placeholder = ImageDraw.Draw(bg, "RGBA")
        placeholder.ellipse((size * 0.3, size * 0.18, size * 0.7, size * 0.58), fill=(255, 255, 255, 60))
        placeholder.ellipse((size * 0.18, size * 0.55, size * 0.82, size * 1.1), fill=(255, 255, 255, 60))
    total_h = size + strip_h
    tile = Image.new("RGBA", (size, total_h), (0, 0, 0, 0))
    tile.alpha_composite(bg, (0, 0))
    if strip_h:
        td = ImageDraw.Draw(tile, "RGBA")
        td.rectangle((0, size, size, total_h), fill=STRIP)
        label = f"Lv. {level}" if isinstance(level, int) else str(level)
        fnt = font("semibold", strip_font_size)
        td.text((size / 2, size + strip_h / 2), label, font=fnt, fill=GOLD_DARK, anchor="mm")
    mask = Image.new("L", (size, total_h), 0)
    ImageDraw.Draw(mask).rounded_rectangle((0, 0, size - 1, total_h - 1), radius=max(8, size // 10), fill=255)
    img.paste(tile.convert("RGB"), (x, y), mask)
    return total_h


def to_png(img: Image.Image) -> bytes:
    buf = io.BytesIO()
    img.save(buf, format="PNG", optimize=False)
    return buf.getvalue()
