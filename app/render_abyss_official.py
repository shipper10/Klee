"""Spiral Abyss card in the style of the official HoYoLAB share page (purple glass panels, summary on top).

The Challenge Summary is always drawn, also when a single floor is requested. Halves of a chamber sit side by side to keep
the image short. Character tiles reuse the Stygian official tile; star icons come from game textures (GenshinUID, GPL-3.0).
"""

from __future__ import annotations

import io
from datetime import datetime, timezone

from PIL import Image, ImageDraw, ImageOps

from app.abyss import AbyssData, Chamber, Char, Floor
from app.render_abyss import STAT_LABELS, _fmt_period, _fmt_time
from app.render_stygian_official import (
    EDGE, INNER, MUTED, PAD, PANEL, TEXT, TILE_GAP, TILE_H, TILE_W, W, _background, _circle, _star4, _tile,
)
from app.render_theater_official import _asset
from app.stygian import SChar
from app.ui_kit import font, load_icon

REPORT_VERSION = "abyss-official-v1"
GOLD = (232, 200, 130)
GOLD_DARK = (84, 60, 24)
HALF_W = 4 * TILE_W + 3 * 8
HALF_GAP = INNER - 60 - 2 * HALF_W
CHAMBER_H = 70 + 36 + TILE_H + 30
FLOOR_HEAD = 96
NOTABLE_LEFT = ("most_kills", "most_damage_taken", "most_skills_used")
NOTABLE_RIGHT = ("strongest_strike", "most_bursts_used")


def _sc(c: Char) -> SChar:
    return SChar(icon=c.icon, level=c.level, rarity=c.rarity, candidates=c.candidates)


def _stars(img: Image.Image, right: int, cy: int, lit: int, total: int = 3, size: int = 40) -> None:
    for i in range(total):
        st = _asset("stella_on" if i < lit else "stella_off", size)
        if st is not None:
            img.paste(st, (right - (total - i) * (size + 4), cy - size // 2), st)


def _summary_height(data: AbyssData) -> int:
    h = 72 + 130 + 30
    if data.most_played:
        h += 48 + TILE_H + 34
    rows = max(len(NOTABLE_LEFT), len(NOTABLE_RIGHT)) if data.stats else 1
    return h + 48 + rows * 54 + 40


def render_abyss_official(
    data: AbyssData, *, nickname: str, icons: dict[str, bytes], floors: list[Floor], tz_hours: int, fetched_at: datetime,
    source: str, full_summary: bool = True, style: str = "official",
) -> bytes:
    # The summary is part of this layout whatever floors were asked for (`full_summary` is accepted but not used to hide it).
    summary_h = _summary_height(data)
    floors_h = sum(FLOOR_HEAD + len(f.chambers) * CHAMBER_H + 28 for f in floors)
    height = 250 + summary_h + 28 + floors_h + 130
    img = _background(height)
    d = ImageDraw.Draw(img, "RGBA")

    d.text((PAD, 66), f"Dear {nickname or 'Traveler'}", font=font("bold", 44), fill=TEXT, anchor="lm")
    d.text((PAD, 122), "Review your Spiral Abyss challenge records~", font=font("regular", 26), fill=MUTED, anchor="lm")
    period = f"Period: {_fmt_period(data.period_start, data.period_end, tz_hours)}" if data.period_start else "Spiral Abyss"
    pw = int(d.textlength(period, font=font("semibold", 24))) + 56
    d.rounded_rectangle((PAD, 160, PAD + pw, 204), radius=22, fill=GOLD)
    _star4(d, PAD + 26, 182, 9, GOLD_DARK)
    d.text((PAD + 46 + (pw - 56) / 2, 182), period, font=font("semibold", 24), fill=GOLD_DARK, anchor="mm")
    y = 250

    # --- Challenge Summary
    d.rounded_rectangle((PAD, y, W - PAD, y + summary_h), radius=10, fill=PANEL, outline=EDGE, width=2)
    _star4(d, PAD + 40, y + 40, 12, TEXT)
    d.text((PAD + 66, y + 40), "Challenge Summary", font=font("semibold", 32), fill=TEXT, anchor="lm")
    by = y + 72
    d.rounded_rectangle((PAD + 24, by, W - PAD - 24, by + 130), radius=8, fill=(255, 255, 255, 26), outline=EDGE, width=2)
    star = _asset("stella_on", 56)
    cx = W // 2
    if star is not None:
        img.paste(star, (cx - 100, by + 14), star)
    d.text((cx - 36, by + 42), f"{data.total_stars}", font=font("bold", 58), fill=TEXT, anchor="lm")
    d.text((cx, by + 98), f"Deepest Descent: {data.max_floor}        Battles Fought: {data.total_battles}", font=font("semibold", 23), fill=MUTED, anchor="mm")
    cy = by + 130 + 30
    if data.most_played:
        d.text((PAD + 28, cy), "Most Played Characters", font=font("serif", 26), fill=GOLD, anchor="lm")
        cy += 36
        for i, c in enumerate(data.most_played[:4]):
            tx = PAD + 28 + i * (TILE_W + 40)
            _tile(img, d, tx, cy, _sc(c), load_icon(icons.get(c.icon)), label=str(c.value))
            if i < min(3, len(data.most_played) - 1):
                d.text((tx + TILE_W + 20, cy + TILE_H // 2), "+", font=font("bold", 30), fill=MUTED, anchor="mm")
        cy += TILE_H + 34
    d.text((PAD + 28, cy), "Notable Stats", font=font("serif", 26), fill=GOLD, anchor="lm")
    cy += 34
    by_key = {s.key: s for s in data.stats}
    rows = max(len(NOTABLE_LEFT), len(NOTABLE_RIGHT))
    d.rounded_rectangle((PAD + 24, cy, W - PAD - 24, cy + rows * 54 + 12), radius=8, fill=(255, 255, 255, 18), outline=EDGE, width=1)
    if not data.stats:
        d.text((PAD + 48, cy + 30), "No battle records yet", font=font("regular", 24), fill=MUTED, anchor="lm")
    colw = (W - 2 * PAD - 48) // 2
    for col, keys in enumerate((NOTABLE_LEFT, NOTABLE_RIGHT)):
        for r, key in enumerate(keys):
            s = by_key.get(key)
            if s is None:
                continue
            x0 = PAD + 24 + col * colw + 18
            ry = cy + 6 + r * 54
            _circle(img, x0, ry + 5, 40, load_icon(icons.get(s.icon)), color=(120, 100, 170))
            d.text((x0 + 52, ry + 25), STAT_LABELS.get(key, key) + ":", font=font("medium", 23), fill=TEXT, anchor="lm")
            d.text((x0 + colw - 46, ry + 25), str(s.value), font=font("bold", 25), fill=TEXT, anchor="rm")
    y += summary_h + 28

    # --- floors
    for f in floors:
        block_h = FLOOR_HEAD + len(f.chambers) * CHAMBER_H
        d.rounded_rectangle((PAD, y, W - PAD, y + block_h), radius=10, fill=PANEL, outline=EDGE, width=2)
        d.ellipse((PAD + 26, y + 24, PAD + 26 + 52, y + 24 + 52), fill=(30, 24, 52, 230), outline=TEXT, width=3)
        d.text((PAD + 52, y + 50), str(f.number), font=font("bold", 28), fill=TEXT, anchor="mm")
        d.text((PAD + 96, y + 50), f"Spiral Abyss Floor {f.number}", font=font("semibold", 34), fill=TEXT, anchor="lm")
        star = _asset("stella_on", 44)
        if star is not None:
            img.paste(star, (W - PAD - 170, y + 28), star)
        d.text((W - PAD - 36, y + 50), f"{f.stars}/{f.max_stars}", font=font("bold", 34), fill=TEXT, anchor="rm")
        cy = y + FLOOR_HEAD
        for ch in f.chambers:
            d.line((PAD + 28, cy, W - PAD - 28, cy), fill=(255, 255, 255, 40), width=1)
            _star4(d, W // 2, cy, 6, (255, 255, 255, 150))
            d.text((PAD + 30, cy + 24), f"Chamber {ch.number}", font=font("serif", 28), fill=TEXT, anchor="lm")
            d.text((PAD + 30, cy + 54), _fmt_time(ch.timestamp, tz_hours), font=font("regular", 19), fill=MUTED, anchor="lm")
            _stars(img, W - PAD - 30, cy + 38, ch.stars)
            for half_i, (label, chars) in enumerate((("First Half", ch.first_half), ("Second Half", ch.second_half))):
                hx = PAD + 30 + half_i * (HALF_W + HALF_GAP)
                d.text((hx, cy + 84), label, font=font("serif", 22), fill=MUTED, anchor="lm")
                for i, c in enumerate(chars[:4]):
                    _tile(img, d, hx + i * (TILE_W + 8), cy + 104, _sc(c), load_icon(icons.get(c.icon)))
            cy += CHAMBER_H
        y += block_h + 28

    label = {"live": "Live data", "cached": "Cached data", "stale": "Stale data (HoYoLAB unreachable)"}.get(source, "Data")
    stamp = fetched_at.astimezone(timezone.utc).strftime("%Y-%m-%d %H:%M UTC")
    d.text((PAD + 4, y + 14), f"{nickname or 'Traveler'}  ·  {label}, fetched {stamp}", font=font("medium", 22), fill=MUTED)
    d.text((PAD + 4, y + 52), f"Unofficial community tool, not affiliated with HoYoverse  ·  {REPORT_VERSION}", font=font("regular", 19), fill=(150, 142, 178))
    buf = io.BytesIO()
    img.crop((0, 0, W, y + 94)).save(buf, format="PNG")
    return buf.getvalue()
