"""Imaginarium Theater report image, styled after the HoYoLAB Battle Chronicle share card."""

from __future__ import annotations

from datetime import datetime, timezone

from app.render_abyss import _fmt_period, _fmt_time
from app.theater import CHAR_TYPES, TAct, TheaterData
from app.ui_kit import C, character_tile, draw_star, fit_text, font, load_icon, new_canvas, panel, themed, to_png

REPORT_VERSION = "theater-v1"
W = 1080
PAD = 48
INNER = W - 2 * PAD
TILE = 104
GAP = 12
ACT_H = 96 + round(TILE * 1.24) + 14 + 64 + 18
STAT_LABELS = {"most_defeats": "Most Defeats", "most_damage": "Highest Damage", "most_damage_taken": "Most Damage Taken"}


def select_acts(data: TheaterData, show_all: bool, default_count: int = 4) -> list[TAct]:
    acts = sorted(data.acts, key=lambda a: -a.number)
    return acts if show_all else acts[:default_count]


def _clock(seconds: int) -> str:
    return f"{seconds // 60}:{seconds % 60:02d}" if seconds else "-"


@themed
def render_theater_card(
    data: TheaterData, *, nickname: str, icons: dict[str, bytes], acts: list[TAct], tz_hours: int,
    fetched_at: datetime, source: str, full_summary: bool = True,
) -> bytes:
    cells = [
        ("Best Act", f"Act {data.best_act}" if data.best_act else "-"),
        ("Medals", f"{data.medals}"),
        ("Fantasia Flowers Used", f"{data.fantasia_flowers}"),
        ("Audience Support", f"{data.audience_support}"),
        ("Assists to Others", f"{data.assists}"),
        ("Total Cast Time", _clock(data.total_cast_seconds)),
    ]
    stat_chars = data.stats
    summary_h = 0
    if full_summary:
        summary_h = 92 + 2 * 98 + 14 + 24
        if stat_chars:
            summary_h += 52 + round(TILE * 1.24) + 30
    height = 250 + (summary_h + 24 if full_summary else 0) + len(acts) * (ACT_H + 24) + 130
    img, d = new_canvas(W, height)

    d.text((PAD, 48), f"Dear {fit_text(d, nickname or 'Traveler', font('bold', 52), INNER - 190)}", font=font("bold", 52), fill=C.TEXT)
    d.text((PAD, 118), "Review your Imaginarium Theater records~", font=font("regular", 26), fill=C.MUTED)
    period = f"Period: {_fmt_period(data.period_start, data.period_end, tz_hours)}" if data.period_start else "Imaginarium Theater"
    if data.difficulty_name:
        period += f"  ·  {data.difficulty_name}"
    pw = int(d.textlength(period, font=font("semibold", 24))) + 48
    d.rounded_rectangle((PAD, 164, PAD + pw, 204), radius=20, fill=C.GOLD)
    d.text((PAD + pw / 2, 184), period, font=font("semibold", 24), fill=C.GOLD_DARK, anchor="mm")
    y = 250

    if full_summary:
        panel(d, (PAD, y, W - PAD, y + summary_h), radius=26)
        d.text((PAD + 30, y + 36), "Challenge Summary", font=font("semibold", 32), fill=C.TEXT)
        cw = (INNER - 60 - 2 * 14) // 3
        for i, (label, value) in enumerate(cells):
            cx = PAD + 30 + (i % 3) * (cw + 14)
            cy = y + 92 + (i // 3) * 98
            d.rounded_rectangle((cx, cy, cx + cw, cy + 84), radius=14, fill=C.tint(22))
            d.text((cx + 18, cy + 12), fit_text(d, label, font("regular", 20), cw - 36), font=font("regular", 20), fill=C.MUTED)
            d.text((cx + 18, cy + 58), value, font=font("bold", 32), fill=C.TEXT, anchor="lm")
        if stat_chars:
            sy = y + 92 + 2 * 98 + 14
            d.text((PAD + 30, sy), "Notable Characters", font=font("serif", 28), fill=C.GOLD)
            sy += 52
            for i, s in enumerate(stat_chars[:3]):
                sx = PAD + 30 + i * (cw + 14)
                character_tile(img, d, sx, sy, TILE, rarity=s.char.rarity, level=f"{s.char.value:,}".replace(",", ""),
                               icon=load_icon(icons.get(s.char.icon)), strip_font_size=20)
                d.text((sx + TILE + 14, sy + 30), STAT_LABELS.get(s.key, s.key), font=font("regular", 20), fill=C.TEXT)
        y += summary_h + 24

    for a in acts:
        panel(d, (PAD, y, W - PAD, y + ACT_H), radius=26)
        title = f"Lunar Arcana {a.arcana_number}" if a.is_arcana and a.arcana_number else f"Act {a.number}"
        d.text((PAD + 30, y + 24), title, font=font("serif", 32), fill=C.GOLD)
        d.text((PAD + 30, y + 62), _fmt_time(a.finish_time, tz_hours), font=font("regular", 20), fill=C.MUTED)
        if a.medal:
            draw_star(d, W - PAD - 150, y + 40, 20, C.GOLD)
            d.text((W - PAD - 36, y + 40), "Medal", font=font("semibold", 26), fill=C.TEXT, anchor="rm")
        ty = y + 96
        for i, c in enumerate(a.characters[:8]):
            tx = PAD + 30 + i * (TILE + GAP)
            th = character_tile(img, d, tx, ty, TILE, rarity=c.rarity, level=c.level, icon=load_icon(icons.get(c.icon)), strip_font_size=20)
            tag = CHAR_TYPES.get(c.kind)
            if tag:
                tw = int(d.textlength(tag, font=font("semibold", 15))) + 14
                d.rounded_rectangle((tx + 4, ty + 4, tx + 4 + tw, ty + 26), radius=8, fill=C.BADGE)
                d.text((tx + 4 + tw / 2, ty + 15), tag, font=font("semibold", 15), fill=C.TEXT, anchor="mm")
        ly = ty + round(TILE * 1.24) + 14
        for label, names in (("Wondrous Booms", a.booms), ("Mystery Caches", a.caches)):
            text = f"{label}: " + (", ".join(names) if names else "-")
            d.text((PAD + 30, ly), fit_text(d, text, font("regular", 20), INNER - 60), font=font("regular", 20), fill=C.MUTED)
            ly += 30
        y += ACT_H + 24

    label = {"live": "Live data", "cached": "Cached data", "stale": "Stale data (HoYoLAB unreachable)"}.get(source, "Data")
    stamp = fetched_at.astimezone(timezone.utc).strftime("%Y-%m-%d %H:%M UTC")
    d.text((PAD, y + 20), f"{label}  ·  fetched {stamp}", font=font("medium", 22), fill=C.GOLD if source == "live" else C.WARN)
    d.text((PAD, y + 58), f"Unofficial community tool, not affiliated with HoYoverse  ·  {REPORT_VERSION}", font=font("regular", 20), fill=C.MUTED)
    return to_png(img)
