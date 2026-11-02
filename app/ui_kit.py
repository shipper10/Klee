"""Shared drawing helpers for report images (Pillow only, deterministic, no network).

The look follows the dark-navy / cream-gold style of HoYoLAB Battle Chronicle share cards, drawn from scratch:
no HoYoverse artwork is bundled, and no HoYoverse logo or QR code is reproduced.
"""

from __future__ import annotations

import io
import math
from contextvars import ContextVar
from dataclasses import dataclass
from functools import lru_cache, wraps
from pathlib import Path

from PIL import Image, ImageDraw, ImageFont, ImageOps

FONT_DIR = Path(__file__).parent / "assets" / "fonts"

@dataclass(frozen=True)
class Theme:
    """A colour palette. Renderers read colours through `C`, so one layout can wear several looks."""

    id: str
    label: str
    description: str
    bg_top: tuple
    bg_bottom: tuple
    text: tuple
    muted: tuple
    gold: tuple  # accent colour (headings, highlights)
    gold_dark: tuple  # text drawn on top of accent fills and on the tile label strip
    star_on: tuple
    strip: tuple
    tint_rgb: tuple  # colour of translucent overlays (white on dark themes, black on light ones)
    tint_scale: float
    badge: tuple
    warn: tuple
    good: tuple
    card: tuple  # flat card colour used by the Daily Notes layout
    bar_bg: tuple
    notes_bg: tuple
    swatch: tuple


THEMES: dict[str, Theme] = {
    t.id: t
    for t in (
        Theme(
            "classic", "Classic Navy", "Dark navy and cream gold, like the official cards.",
            (30, 30, 70), (13, 14, 36), (238, 238, 246), (164, 166, 196), (226, 201, 150), (58, 51, 64),
            (244, 236, 214), (239, 230, 211), (255, 255, 255), 1.0, (20, 20, 44, 215), (240, 170, 110),
            (118, 214, 160), (33, 37, 54), (52, 57, 80), (20, 22, 33), (226, 201, 150),
        ),
        Theme(
            "aurora", "Aurora", "Deep teal night with a cool mint accent.",
            (14, 44, 56), (6, 14, 24), (234, 247, 247), (150, 186, 190), (128, 226, 200), (8, 34, 34),
            (214, 250, 240), (206, 238, 232), (255, 255, 255), 1.0, (6, 24, 30, 215), (255, 190, 120),
            (128, 226, 200), (18, 40, 50), (36, 66, 78), (8, 20, 28), (128, 226, 200),
        ),
        Theme(
            "sakura", "Sakura Night", "Dark plum with soft rose and pink highlights.",
            (58, 28, 66), (22, 12, 34), (248, 238, 246), (190, 160, 190), (246, 168, 200), (52, 20, 44),
            (255, 226, 238), (250, 226, 238), (255, 255, 255), 1.0, (34, 14, 40, 215), (255, 190, 130),
            (160, 226, 190), (46, 26, 58), (78, 50, 92), (26, 14, 36), (246, 168, 200),
        ),
        Theme(
            "paper", "Paper", "Light, calm cream paper with dark ink. Good for bright screens.",
            (250, 245, 234), (232, 222, 204), (48, 42, 58), (116, 106, 120), (170, 118, 40), (255, 248, 232),
            (200, 138, 36), (96, 80, 104), (0, 0, 0), 0.55, (255, 250, 238, 230), (196, 98, 30),
            (40, 130, 84), (255, 252, 244), (222, 212, 192), (240, 233, 218), (170, 118, 40),
        ),
    )
}
DEFAULT_THEME = "classic"

_current: ContextVar[Theme] = ContextVar("klee_theme", default=THEMES[DEFAULT_THEME])


class _Colors:
    """`C.TEXT`, `C.GOLD`, ... return the colour of the theme that is active for the current render."""

    def __getattr__(self, name: str):
        return getattr(_current.get(), name.lower())

    def tint(self, alpha: int) -> tuple:
        t = _current.get()
        return (*t.tint_rgb, round(alpha * t.tint_scale))

    @property
    def PANEL(self) -> tuple:  # noqa: N802
        return self.tint(20)

    @property
    def PANEL_BORDER(self) -> tuple:  # noqa: N802
        return self.tint(38)

    @property
    def STAR_OFF(self) -> tuple:  # noqa: N802
        return self.tint(46)


C = _Colors()


def themed(fn):
    """Decorator for render functions: accepts `style="<theme id>"` and applies it for the duration of the call."""

    @wraps(fn)
    def wrapper(*args, style: str = DEFAULT_THEME, **kwargs):
        token = _current.set(THEMES.get(style, THEMES[DEFAULT_THEME]))
        try:
            return fn(*args, **kwargs)
        finally:
            _current.reset(token)

    return wrapper


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
    img = vertical_gradient(width, height, C.BG_TOP, C.BG_BOTTOM)
    return img, ImageDraw.Draw(img, "RGBA")


def panel(d: ImageDraw.ImageDraw, box: tuple[int, int, int, int], radius: int = 22, fill=None, outline=None) -> None:
    d.rounded_rectangle(box, radius=radius, fill=C.PANEL if fill is None else fill, outline=C.PANEL_BORDER if outline is None else outline, width=2)


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
        draw_star(d, x, cy, r, C.STAR_ON if i < filled else C.STAR_OFF)
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
        placeholder.ellipse((size * 0.3, size * 0.18, size * 0.7, size * 0.58), fill=C.tint(60))
        placeholder.ellipse((size * 0.18, size * 0.55, size * 0.82, size * 1.1), fill=C.tint(60))
    total_h = size + strip_h
    tile = Image.new("RGBA", (size, total_h), (0, 0, 0, 0))
    tile.alpha_composite(bg, (0, 0))
    if strip_h:
        td = ImageDraw.Draw(tile, "RGBA")
        td.rectangle((0, size, size, total_h), fill=C.STRIP)
        label = f"Lv. {level}" if isinstance(level, int) else str(level)
        fnt = font("semibold", strip_font_size)
        td.text((size / 2, size + strip_h / 2), label, font=fnt, fill=C.GOLD_DARK, anchor="mm")
    mask = Image.new("L", (size, total_h), 0)
    ImageDraw.Draw(mask).rounded_rectangle((0, 0, size - 1, total_h - 1), radius=max(8, size // 10), fill=255)
    img.paste(tile.convert("RGB"), (x, y), mask)
    return total_h


def to_png(img: Image.Image) -> bytes:
    buf = io.BytesIO()
    img.save(buf, format="PNG", optimize=False)
    return buf.getvalue()
