"""Traveler's Diary, all available months in one image, in the style of the in-game diary (paper pages on dark blue).

One page per month side by side: income tiles, comparison with the month before, donut chart of Primogem sources with legend.
Icons: game textures (primogem, mora) bundled under app/assets/ui.
"""

from __future__ import annotations

import calendar
import io
from datetime import datetime, timezone

from PIL import Image, ImageDraw

from app.asset_manager import Assets
from app.diary import DiaryData
from app.render_stygian_official import _wrap
from app.ui_kit import font

REPORT_VERSION = "diary-official-v1"
PAD, GAP = 36, 22
PAPER = (232, 237, 245)
PAPER_EDGE = (176, 192, 216)
INK = (44, 56, 82)
MUTED = (112, 124, 148)
TAN = (176, 146, 100)
COLORS = {
    "events": (91, 134, 173), "mail": (139, 116, 184), "daily activity": (201, 165, 90), "adventure": (220, 106, 106),
    "spiral abyss": (122, 160, 112), "quests": (98, 185, 176), "other": (106, 174, 208),
}
FALLBACK = [(150, 130, 170), (170, 150, 110), (110, 150, 150), (180, 120, 140)]
LEGEND_ROW = 32
PAGE_H_BASE = 740


def _color(name: str, i: int) -> tuple[int, int, int]:
    return COLORS.get(name.strip().lower()) or FALLBACK[i % len(FALLBACK)]


def comparison(d: DiaryData) -> str:
    def part(label: str, rate: int) -> str:
        if rate > 0:
            return f"{rate}% more {label} than last month"
        if rate < 0:
            return f"{abs(rate)}% less {label} than last month"
        return f"the same {label} as last month"
    return f"{part('Primogems', d.primogem_rate)}, {part('Mora', d.mora_rate)}.".capitalize().replace("primogems", "Primogems").replace("mora", "Mora")


def _donut(cats, size: int) -> Image.Image:
    k = 4
    big = size * k
    img = Image.new("RGBA", (big, big), (0, 0, 0, 0))
    d = ImageDraw.Draw(img)
    d.ellipse((0, 0, big - 1, big - 1), fill=(214, 224, 240, 255))  # pale outer ring
    box = (big * 0.1, big * 0.1, big * 0.9, big * 0.9)
    total = sum(c.amount for c in cats) or 0
    if total:
        a = -90.0
        for i, c in enumerate(cats):
            sweep = 360 * c.amount / total
            d.pieslice(box, a, a + sweep, fill=_color(c.name, i) + (255,))
            a += sweep
    else:
        d.ellipse(box, fill=(196, 206, 224, 255))
    d.ellipse((big * 0.28, big * 0.28, big * 0.72, big * 0.72), fill=PAPER + (255,))
    d.ellipse((big * 0.3, big * 0.3, big * 0.7, big * 0.7), outline=(206, 216, 232, 255), width=k * 2)
    return img.resize((size, size), Image.LANCZOS)


def _pill(img: Image.Image, d: ImageDraw.ImageDraw, x: int, y: int, w: int, name: str, value: int, icon: Image.Image | None) -> None:
    d.rounded_rectangle((x + 32, y + 8, x + w, y + 56), radius=8, fill=(240, 243, 249), outline=PAPER_EDGE, width=2)
    d.ellipse((x, y, x + 64, y + 64), fill=(176, 188, 210), outline=(150, 166, 194), width=3)
    if icon is not None:
        pic = icon.resize((44, 44), Image.LANCZOS)
        img.paste(pic, (x + 10, y + 10), pic)
    d.text((x + 80, y + 32), f"{name}:", font=font("medium", 19), fill=INK, anchor="lm")
    d.text((x + 80 + d.textlength(f"{name}:", font=font("medium", 19)) + 8, y + 32), f"{value}", font=font("medium", 19), fill=TAN, anchor="lm")


def _page_height(data: DiaryData) -> int:
    return PAGE_H_BASE + max(1, len(data.categories[:8])) * LEGEND_ROW


def _page(img: Image.Image, d: ImageDraw.ImageDraw, x: int, y: int, w: int, h: int, data: DiaryData, nickname: str, assets: Assets) -> None:
    d.rounded_rectangle((x, y, x + w, y + h), radius=14, fill=PAPER)
    d.rounded_rectangle((x + 8, y + 8, x + w - 8, y + h - 8), radius=10, outline=PAPER_EDGE, width=2)
    d.rounded_rectangle((x + 13, y + 13, x + w - 13, y + h - 13), radius=8, outline=(205, 215, 232), width=1)
    ix, iw = x + 34, w - 68
    month = calendar.month_name[data.month] if 1 <= data.month <= 12 else str(data.month)
    title, tsize = f"Traveler's Diary : {month}", 25
    while tsize > 15 and d.textlength(title, font=font("bold", tsize)) > iw:
        tsize -= 1
    d.text((ix, y + 52), title, font=font("bold", tsize), fill=INK, anchor="lm")
    d.text((ix, y + 88), f"Nickname: {nickname or 'Traveler'}", font=font("regular", 18), fill=MUTED, anchor="lm")
    d.text((ix + iw, y + 88), str(data.year or ""), font=font("medium", 18), fill=TAN, anchor="rm")
    d.line((ix, y + 112, ix + iw, y + 112), fill=PAPER_EDGE, width=2)
    d.text((ix, y + 142), "Acquired this month", font=font("bold", 21), fill=INK, anchor="lm")
    _pill(img, d, ix, y + 166, iw, "Primogems", data.primogems, assets.ui("diary_primogem"))
    _pill(img, d, ix, y + 240, iw, "Mora", data.mora, assets.ui("diary_mora"))
    cy = y + 330
    for line in _wrap(d, comparison(data), font("regular", 19), iw, 4):
        d.text((ix, cy), line, font=font("regular", 19), fill=INK, anchor="lm")
        cy += 28
    cy += 14
    d.line((ix, cy, ix + iw, cy), fill=PAPER_EDGE, width=1)
    d.text((ix, cy + 32), "Primogems obtained", font=font("bold", 21), fill=INK, anchor="lm")
    cats = data.categories[:8]
    size = 190
    ring = _donut([c for c in cats if c.amount > 0], size)
    img.paste(ring, (x + (w - size) // 2, cy + 56), ring)
    ly = cy + 56 + size + 22
    if not cats:
        d.text((ix, ly + 10), "No income recorded yet", font=font("regular", 18), fill=MUTED, anchor="lm")
    for i, c in enumerate(cats):
        d.rectangle((ix, ly + 6 + i * LEGEND_ROW, ix + 14, ly + 20 + i * LEGEND_ROW), fill=_color(c.name, i))
        d.text((ix + 24, ly + 13 + i * LEGEND_ROW), c.name, font=font("regular", 18), fill=INK, anchor="lm")
        d.text((ix + iw, ly + 13 + i * LEGEND_ROW), f"{c.percent}%", font=font("medium", 18), fill=INK, anchor="rm")


def render_diary_official(
    months: list[DiaryData], *, nickname: str, fetched_at: datetime, source: str, style: str = "official",
) -> bytes:
    """`months` newest first. Rendered oldest -> newest from left to right."""
    assets = Assets()
    pages = list(reversed(months)) or [DiaryData()]
    n = len(pages)
    pw = 360
    width = 2 * PAD + n * pw + (n - 1) * GAP
    width = max(width, 760)
    ph = max(_page_height(p) for p in pages)
    height = 190 + ph + 130
    base = Image.new("RGB", (width, height), (16, 26, 46))
    ramp = Image.linear_gradient("L").transpose(Image.FLIP_TOP_BOTTOM).resize((width, min(height, 700))).point(lambda v: int(v * 0.5))
    layer = Image.new("L", (width, height), 0)
    layer.paste(ramp, (0, 0))
    base.paste(Image.new("RGB", (width, height), (44, 78, 120)), (0, 0), layer)
    img = base.convert("RGBA")
    d = ImageDraw.Draw(img, "RGBA")
    d.text((PAD, 62), f"Dear {nickname or 'Traveler'}", font=font("bold", 44), fill=(240, 244, 252), anchor="lm")
    d.text((PAD, 116), f"Your Traveler's Diary~  ·  last {n} month{'s' if n != 1 else ''}", font=font("regular", 25), fill=(170, 186, 214), anchor="lm")
    x0 = (width - (n * pw + (n - 1) * GAP)) // 2
    for i, p in enumerate(pages):
        _page(img, d, x0 + i * (pw + GAP), 170, pw, ph, p, nickname, assets)
    y = 170 + ph + 30
    label = {"live": "Live data", "cached": "Cached data", "stale": "Stale data (HoYoLAB unreachable)"}.get(source, "Data")
    stamp = fetched_at.astimezone(timezone.utc).strftime("%Y-%m-%d %H:%M UTC")
    d.text((PAD, y + 14), f"{label}  ·  fetched {stamp}", font=font("medium", 22), fill=(170, 186, 214))
    d.text((PAD, y + 52), f"Unofficial community tool, not affiliated with HoYoverse  ·  {REPORT_VERSION}", font=font("regular", 19), fill=(130, 146, 176))
    buf = io.BytesIO()
    img.convert("RGB").save(buf, format="PNG")
    return buf.getvalue()
