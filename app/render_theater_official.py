"""Imaginarium Theater card in the style of the official HoYoLAB share page, with the acts in two columns.

Layout (1080 px wide): library header with title, the "Past Performances" summary panel, performance statistics,
then the Cast List with one cream card per act, two cards per row to keep the image short.
Artwork: the library background and stella/trophy icons come from game textures (GenshinUID, GPL-3.0); character tiles reuse
the Stygian official tile. No HoYoverse logo or QR code is drawn.
"""

from __future__ import annotations

import io
from datetime import datetime, timedelta, timezone
from pathlib import Path

from PIL import Image, ImageDraw, ImageFilter, ImageOps

from app.regions import mask_uid
from app.render_stygian_official import TILE_H, TILE_W, _star4, _tile, _wrap
from app.stygian import SChar
from app.theater import CHAR_TYPES, TAct, TChar, TheaterData
from app.ui_kit import fit_text, font, load_icon

REPORT_VERSION = "theater-official-v1"
W = 1080
PAD = 40
GAP = 20
CARD_W = (W - 2 * PAD - GAP) // 2
ASSETS = Path(__file__).parent / "assets" / "ui"
PAGE = (21, 18, 25)
CREAM = (240, 234, 223)
CREAM_EDGE = (214, 202, 180)
BROWN = (116, 88, 64)
BROWN_DARK = (84, 62, 44)
BAR = (229, 217, 192)
GOLD = (226, 196, 140)
TEXT = (245, 241, 235)
MUTED = (178, 170, 164)
ROW = (255, 255, 255, 14)
LINE = (255, 255, 255, 34)
TAG = (222, 98, 98)


def _asset(name: str, size: int | tuple[int, int] | None = None) -> Image.Image | None:
    try:
        img = Image.open(ASSETS / f"{name}.png").convert("RGBA")
    except OSError:
        return None
    if size is None:
        return img
    return img.resize((size, size) if isinstance(size, int) else size, Image.LANCZOS)


def _rr(img: Image.Image, box: tuple[int, int, int, int], radius: int, fill=None, outline=None, width: int = 1) -> None:
    """Translucent rounded rectangle, properly blended (ImageDraw on RGBA would overwrite alpha)."""
    x0, y0, x1, y1 = (int(v) for v in box)
    w, h = x1 - x0 + 1, y1 - y0 + 1
    layer = Image.new("RGBA", (w, h), (0, 0, 0, 0))
    ImageDraw.Draw(layer).rounded_rectangle((0, 0, w - 1, h - 1), radius=radius, fill=fill, outline=outline, width=width)
    img.alpha_composite(layer, (x0, y0))


def _duration(seconds: int) -> str:
    return f"{seconds // 60}m {seconds % 60:02d}s" if seconds else "-"


def _stamp(ts: int, tz_hours: int) -> str:
    if not ts:
        return ""
    return datetime.fromtimestamp(ts, timezone(timedelta(hours=tz_hours))).strftime("%Y.%m.%d %H:%M:%S")


def _period(start: int, end: int, tz_hours: int) -> str:
    tz = timezone(timedelta(hours=tz_hours))
    f = lambda t: datetime.fromtimestamp(t, tz).strftime("%Y.%m.%d")  # noqa: E731
    return f"Period: {f(start)}-{f(end)}"


def _sc(c: TChar) -> SChar:
    return SChar(icon=c.icon, level=c.level, rarity=c.rarity, candidates=c.candidates)


RARITY = {5: ((236, 176, 98), (190, 126, 58)), 4: ((166, 132, 226), (108, 82, 168))}


def _mini(img: Image.Image, x: int, y: int, size: int, c: TChar, icon: Image.Image | None) -> None:
    """Compact rounded portrait (no level strip) for the statistics rows."""
    top, bottom = RARITY.get(c.rarity, ((112, 118, 140), (76, 80, 100)))
    tile = Image.new("RGBA", (size, size), (0, 0, 0, 0))
    grad = Image.linear_gradient("L").resize((size, size))
    tile.paste(Image.composite(Image.new("RGB", (size, size), bottom), Image.new("RGB", (size, size), top), grad), (0, 0))
    if icon is not None:
        tile.alpha_composite(ImageOps.fit(icon, (size, size), method=Image.LANCZOS, centering=(0.5, 0.25)))
    mask = Image.new("L", (size, size), 0)
    ImageDraw.Draw(mask).rounded_rectangle((0, 0, size - 1, size - 1), radius=10, fill=255)
    img.paste(tile.convert("RGB"), (x, y), mask)


def _fill_page(height: int) -> Image.Image:
    img = Image.new("RGBA", (W, height), PAGE + (255,))
    bg = _asset("theater_bg")
    if bg is not None:
        art = ImageOps.fit(bg, (W, 600), method=Image.LANCZOS, centering=(0.5, 0.3))
        art = Image.blend(art.convert("RGB"), Image.new("RGB", art.size, PAGE), 0.12).convert("RGBA")
        fade = Image.linear_gradient("L").transpose(Image.FLIP_TOP_BOTTOM).resize((W, 600)).point(lambda v: min(255, int(v * 1.25)))
        art.putalpha(fade)
        img.alpha_composite(art, (0, 0))
    return img


# ---- cards -------------------------------------------------------------------------------------------------------
def _sections(d: ImageDraw.ImageDraw, a: TAct, width: int) -> list[tuple[str, list[str]]]:
    body = font("regular", 20)
    out: list[tuple[str, list[str]]] = []
    if a.blessing_text:
        title = f"Blessing Level {a.blessing_level}" if a.blessing_level else "Blessings"
        out.append((title, _wrap(d, a.blessing_text, body, width, max_lines=6)))
    for label, names in (("Wondrous Booms", a.booms), ("Mystery Caches", a.caches)):
        if names:
            out.append((f"{label} x{len(names)}", _wrap(d, ", ".join(names), body, width, max_lines=3)))
    return out


def _act_height(d: ImageDraw.ImageDraw, a: TAct) -> int:
    rows = max(1, -(-len(a.characters[:8]) // 4))
    h = 84 + rows * (TILE_H + 10)
    secs = _sections(d, a, CARD_W - 74)
    if secs:
        h += 12 + 34 + sum(40 + 26 * len(lines) + 12 for _, lines in secs)
    return h + 20


def _act_card(img: Image.Image, d: ImageDraw.ImageDraw, x: int, y: int, a: TAct, icons: dict[str, bytes], tz_hours: int, height: int) -> None:
    _rr(img, (x, y, x + CARD_W, y + height), 14, fill=CREAM + (255,), outline=CREAM_EDGE + (255,), width=2)
    d = ImageDraw.Draw(img, "RGBA")
    stella = _asset("stella_on" if a.medal else "stella_off", 44)
    if stella is not None:
        img.alpha_composite(stella, (x + 20, y + 16))
    title = f"Lunar Arcana {a.arcana_number}" if a.is_arcana and a.arcana_number else f"Act {a.number}"
    d.text((x + 74, y + 38), title, font=font("serif-bold", 30), fill=BROWN_DARK, anchor="lm")
    d.text((x + CARD_W - 22, y + 40), _stamp(a.finish_time, tz_hours), font=font("regular", 17), fill=BROWN, anchor="rm")
    ty = y + 78
    for i, c in enumerate(a.characters[:8]):
        tx = x + 25 + (i % 4) * (TILE_W + 8)
        row_y = ty + (i // 4) * (TILE_H + 10)
        _tile(img, d, tx, row_y, _sc(c), load_icon(icons.get(c.icon)))
        tag = CHAR_TYPES.get(c.kind)
        if tag:
            tw = int(d.textlength(tag, font=font("semibold", 16))) + 16
            _rr(img, (tx + TILE_W - tw - 4, row_y + 4, tx + TILE_W - 4, row_y + 28), 6, fill=TAG + (255,))
            d.text((tx + TILE_W - 4 - tw / 2, row_y + 16), tag, font=font("semibold", 16), fill=(255, 255, 255), anchor="mm")
    cy = ty + max(1, -(-len(a.characters[:8]) // 4)) * (TILE_H + 10) + 2
    secs = _sections(d, a, CARD_W - 74)
    if secs:
        d.text((x + 25, cy + 12), "Performance Details", font=font("semibold", 20), fill=BROWN, anchor="lm")
        cy += 34
    for head, lines in secs:
        d.rectangle((x + 25, cy, x + CARD_W - 25, cy + 38), fill=BAR)
        d.text((x + 38, cy + 19), head, font=font("semibold", 21), fill=BROWN_DARK, anchor="lm")
        _star4(d, x + CARD_W - 40, cy + 19, 7, BROWN)
        body_h = 26 * len(lines) + 14
        d.rectangle((x + 25, cy + 38, x + CARD_W - 25, cy + 38 + body_h), fill=(247, 244, 238), outline=CREAM_EDGE)
        for k, line in enumerate(lines):
            d.text((x + 38, cy + 52 + k * 26), line, font=font("regular", 20), fill=(96, 82, 70), anchor="lm")
        cy += 38 + body_h + 12


# ---- main --------------------------------------------------------------------------------------------------------
def _row_list(img: Image.Image, d: ImageDraw.ImageDraw, x: int, y: int, w: int, rows: list[tuple[str, str]], row_h: int = 62) -> int:
    _rr(img, (x, y, x + w, y + row_h * len(rows)), 8, fill=(255, 255, 255, 12), outline=LINE)
    d = ImageDraw.Draw(img, "RGBA")
    for i, (label, value) in enumerate(rows):
        ry = y + i * row_h
        if i:
            _rr(img, (x + 14, ry, x + w - 14, ry), 0, fill=LINE)
        d.text((x + 20, ry + row_h / 2), label, font=font("regular", 20), fill=TEXT, anchor="lm")
        if value:
            d.text((x + w - 20, ry + row_h / 2), value, font=font("semibold", 21), fill=TEXT, anchor="rm")
    return y + row_h * len(rows)


def render_theater_official(
    data: TheaterData, *, nickname: str, icons: dict[str, bytes], acts: list[TAct], tz_hours: int, fetched_at: datetime,
    source: str, uid: str = "", previous: bool = False, full_summary: bool = True, style: str = "official",
) -> bytes:
    probe = ImageDraw.Draw(Image.new("RGB", (4, 4)))
    acts_sorted = sorted(acts, key=lambda a: a.number)
    pairs = [acts_sorted[i:i + 2] for i in range(0, len(acts_sorted), 2)]
    heights = [max(_act_height(probe, a) for a in pair) for pair in pairs]

    summary_h = 0
    if full_summary:
        summary_h = 70 + 62 * 5 + 40 + 70 + 3 * 92 + (150 if data.fastest else 0) + 40
    cast_h = (110 + sum(h + GAP for h in heights) + 30) if pairs else 0
    height = 330 + summary_h + cast_h + 150
    img = _fill_page(height)
    d = ImageDraw.Draw(img, "RGBA")

    # header
    d.text((PAD, 64), "Imaginarium Theater", font=font("serif-bold", 44), fill=GOLD, anchor="lm")
    d.text((PAD, 120), nickname or "Traveler", font=font("serif-bold", 30), fill=TEXT, anchor="lm")
    if uid:
        d.text((PAD, 160), f"UID: {mask_uid(uid)}", font=font("serif", 24), fill=MUTED, anchor="lm")
    _rr(img, (PAD, 196, W - PAD, 197), 0, fill=LINE)
    _star4(d, W // 2, 196, 8, (255, 255, 255, 150))
    # season selector (shows which season this card is)
    for i, (label, active) in enumerate((("Current Lunar Phase", not previous), ("Previous Lunar Phase", previous))):
        px = PAD + (0 if i == 0 else 270)
        _rr(img, (px, 224, px + 250, 262), 19, fill=(40, 34, 30, 230) if active else (255, 255, 255, 26), outline=GOLD + (255,) if active else None, width=2)
        d.text((px + 125, 243), label, font=font("semibold", 20), fill=GOLD if active else MUTED, anchor="mm")
    if data.period_start:
        d.text((PAD, 292), _period(data.period_start, data.period_end, tz_hours), font=font("regular", 20), fill=MUTED, anchor="lm")
    y = 330

    if full_summary:
        _rr(img, (PAD, y, W - PAD, y + 70 + 62 * 5 + 28), 12, fill=(34, 28, 26, 215), outline=(255, 255, 255, 40), width=2)
        d = ImageDraw.Draw(img, "RGBA")
        d.text((PAD + 36, y + 38), "Imaginarium Theater: Past Performances", font=font("bold", 26), fill=TEXT, anchor="lm")
        best = f"Act {data.best_act}" if data.best_act else "-"
        if data.arcana_completed:
            best += f"   Arcana {data.arcana_completed}"
        rows = [
            ("Best Record", best),
            ("Star Challenge Stellas", ""),
            ("Fantasia Flowers Used", f"{data.fantasia_flowers:,}"),
            ("Triggered External Audience Support", f"{data.audience_support} time(s)"),
            ("Supporting Cast Characters Assist Other Players", f"{data.assists} time(s)"),
        ]
        ry0 = y + 70
        end = _row_list(img, d, PAD + 22, ry0, W - 2 * PAD - 44, rows)
        # stella icons in their row (one per act, lit when the stella was obtained)
        flags = data.stellas or [True] * data.medals
        if flags:
            n = len(flags)
            sx = W - PAD - 22 - 20 - n * 38
            _rr(img, (sx - 10, ry0 + 62 + 8, W - PAD - 22 - 14, ry0 + 62 * 2 - 8), 22, fill=(0, 0, 0, 90))
            for k, on in enumerate(flags):
                st = _asset("stella_on" if on else "stella_off", 34)
                if st is not None:
                    img.alpha_composite(st, (sx + k * 38, ry0 + 62 + 14))
        y = end + 40

        # statistics
        d = ImageDraw.Draw(img, "RGBA")
        name = data.difficulty_name  # follows the mode actually played (Easy/Normal/Hard/Visionary/Arcana Challenge)
        mode = f"{name} Mode" if name else "Imaginarium Theater"
        d.text((PAD + 6, y + 18), mode, font=font("serif-bold", 30), fill=TEXT, anchor="lm")
        d.text((W - PAD - 6, y + 18), f"Performance Duration: {_duration(data.total_cast_seconds)}", font=font("regular", 20), fill=MUTED, anchor="rm")
        y += 56
        labels = {"most_damage": "Highest Damage Dealt", "most_defeats": "Most Opponents Defeated", "most_damage_taken": "Most Damage Taken"}
        _rr(img, (PAD, y, W - PAD, y + 92 * max(1, len(data.stats))), 8, fill=(255, 255, 255, 12), outline=LINE)
        d = ImageDraw.Draw(img, "RGBA")
        order = {"most_damage": 0, "most_defeats": 1, "most_damage_taken": 2}
        for i, s in enumerate(sorted(data.stats, key=lambda t: order.get(t.key, 9))[:3]):
            ry = y + i * 92
            if i:
                _rr(img, (PAD + 14, ry, W - PAD - 14, ry), 0, fill=LINE)
            _mini(img, PAD + 18, ry + 8, 76, s.char, load_icon(icons.get(s.char.icon)))
            d.text((PAD + 18 + 76 + 22, ry + 46), labels.get(s.key, s.key), font=font("regular", 22), fill=TEXT, anchor="lm")
            d.text((W - PAD - 24, ry + 46), f"{s.char.value:,}", font=font("bold", 30), fill=GOLD, anchor="rm")
        y += 92 * max(1, len(data.stats)) + 28
        if data.fastest:
            d.text((PAD + 6, y + 16), "Team That Completed the Performance the Fastest", font=font("semibold", 22), fill=TEXT, anchor="lm")
            y += 44
            for i, c in enumerate(data.fastest[:4]):
                _mini(img, PAD + 6 + i * 78, y, 66, c, load_icon(icons.get(c.icon)))
            y += 66 + 36

    # cast list, two acts per row
    if pairs:
        _rr(img, (PAD - 10, y, W - PAD + 10, y + cast_h - 30), 12, fill=(26, 22, 22, 235), outline=(255, 255, 255, 40), width=2)
        d = ImageDraw.Draw(img, "RGBA")
        d.text((W // 2, y + 44), "Cast List", font=font("serif-bold", 30), fill=TEXT, anchor="mm")
        cy = y + 90
        for pair, h in zip(pairs, heights):
            for k, a in enumerate(pair):
                _act_card(img, d, PAD + k * (CARD_W + GAP), cy, a, icons, tz_hours, h)
            cy += h + GAP
        y += cast_h

    d = ImageDraw.Draw(img, "RGBA")
    label = {"live": "Live data", "cached": "Cached data", "stale": "Stale data (HoYoLAB unreachable)"}.get(source, "Data")
    stamp = fetched_at.astimezone(timezone.utc).strftime("%Y-%m-%d %H:%M UTC")
    d.text((PAD, y + 24), f"{label}  ·  fetched {stamp}", font=font("medium", 20), fill=GOLD if source == "live" else (240, 180, 90))
    d.text((PAD, y + 56), f"Unofficial community tool, not affiliated with HoYoverse  ·  {REPORT_VERSION}", font=font("regular", 18), fill=MUTED)
    out = img.crop((0, 0, W, min(height, y + 96))).convert("RGB")
    buf = io.BytesIO()
    out.save(buf, format="PNG")
    return buf.getvalue()
