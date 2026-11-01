"""Spiral Abyss report image, styled after the HoYoLAB Battle Chronicle share card."""

from __future__ import annotations

from datetime import datetime, timedelta, timezone

from app.abyss import AbyssData, Char, Chamber, Floor
from app.ui_kit import (
    GOLD,
    GOLD_DARK,
    MUTED,
    PANEL,
    TEXT,
    character_tile,
    draw_star,
    draw_stars,
    fit_text,
    font,
    load_icon,
    new_canvas,
    panel,
    to_png,
)

REPORT_VERSION = "abyss-v1"
W = 1080
PAD = 48
INNER = W - 2 * PAD

STAT_LABELS = {
    "most_kills": "Most Defeats",
    "strongest_strike": "Strongest Single Strike",
    "most_damage_taken": "Most Damage Taken",
    "most_bursts_used": "Elemental Bursts Unleashed",
    "most_skills_used": "Elemental Skills Cast",
}

TILE = 104
TILE_GAP = 12
HALF_W = 4 * TILE + 3 * TILE_GAP  # 4 portraits per half
HALF_GAP = INNER - 60 - 2 * HALF_W  # remaining space between the two halves (inside 30px panel padding)
CHAMBER_H = 92 + 38 + round(TILE * 1.24) + 26
FLOOR_HEADER_H = 104
SUMMARY_BASE_H = 130 + 150 + 56  # title + star banner + notable-stats heading (rows added below)


def _fmt_time(ts: int | None, tz_hours: int) -> str:
    if not ts:
        return ""
    dt = datetime.fromtimestamp(ts, tz=timezone(timedelta(hours=tz_hours)))
    return dt.strftime("%Y/%m/%d %H:%M:%S")


def _fmt_period(start: int, end: int, tz_hours: int) -> str:
    tz = timezone(timedelta(hours=tz_hours))
    f = lambda t: datetime.fromtimestamp(t, tz=tz).strftime("%Y/%m/%d")  # noqa: E731
    return f"{f(start)} - {f(end)}"


def select_floors(data: AbyssData, only_floor: int | None, default_count: int = 2) -> list[Floor]:
    with_data = [f for f in data.floors if f.chambers]
    if only_floor is not None:
        return [f for f in with_data if f.number == only_floor]
    return with_data[-default_count:]


def _summary_height(data: AbyssData) -> int:
    h = 130 + 150
    if data.most_played:
        h += 56 + round(110 * 1.24) + 36
    h += 56 + max(1, len(data.stats)) * 54 + 24
    return h


def render_abyss_card(
    data: AbyssData,
    *,
    nickname: str,
    icons: dict[str, bytes],
    floors: list[Floor],
    tz_hours: int,
    fetched_at: datetime,
    source: str,
    full_summary: bool = True,
) -> bytes:
    summary_h = _summary_height(data) if full_summary else 0
    header_h = 230
    floors_h = sum(FLOOR_HEADER_H + len(f.chambers) * CHAMBER_H + 24 for f in floors)
    footer_h = 120
    height = header_h + summary_h + (24 if full_summary else 0) + floors_h + footer_h

    img, d = new_canvas(W, height)

    # --- header
    d.text((PAD, 52), f"Dear {fit_text(d, nickname or 'Traveler', font('semibold', 46), INNER - 150)}", font=font("semibold", 46), fill=TEXT)
    d.text((PAD, 116), "Review your Spiral Abyss challenge records~", font=font("regular", 28), fill=MUTED)
    period = f"Period: {_fmt_period(data.period_start, data.period_end, tz_hours)}"
    pw = int(d.textlength(period, font=font("semibold", 24))) + 40
    d.rounded_rectangle((PAD, 162, PAD + pw, 206), radius=22, fill=GOLD)
    d.text((PAD + pw / 2, 184), period, font=font("semibold", 24), fill=GOLD_DARK, anchor="mm")
    y = header_h

    # --- summary
    if full_summary:
        panel(d, (PAD, y, W - PAD, y + summary_h), radius=26)
        d.text((PAD + 30, y + 36), "Challenge Summary", font=font("semibold", 32), fill=TEXT)
        sy = y + 92
        d.rounded_rectangle((PAD + 30, sy, W - PAD - 30, sy + 150), radius=16, fill=(255, 255, 255, 26))
        cx = W // 2
        draw_star(d, cx - 70, sy + 46, 24, GOLD)
        d.text((cx - 36, sy + 46), f"{data.total_stars}", font=font("bold", 62), fill=TEXT, anchor="lm")
        d.text((cx, sy + 104), f"Deepest Descent: {data.max_floor}    ·    Battles Fought: {data.total_battles}", font=font("regular", 24), fill=MUTED, anchor="mm")
        cy = sy + 150 + 30
        if data.most_played:
            d.text((PAD + 30, cy), "Most Played Characters", font=font("serif", 28), fill=GOLD)
            cy += 52
            for i, c in enumerate(data.most_played[:4]):
                tx = PAD + 30 + i * (110 + 22)
                th = character_tile(img, d, tx, cy, 110, rarity=c.rarity, level=str(c.value), icon=load_icon(icons.get(c.icon)))
            cy += th + 30
        d.text((PAD + 30, cy), "Notable Stats", font=font("serif", 28), fill=GOLD)
        cy += 50
        if not data.stats:
            d.text((PAD + 30, cy + 10), "No battle records yet", font=font("regular", 26), fill=MUTED)
        for s in data.stats:
            d.rounded_rectangle((PAD + 30, cy, W - PAD - 30, cy + 46), radius=12, fill=(255, 255, 255, 18))
            d.text((PAD + 52, cy + 23), STAT_LABELS.get(s.key, s.key), font=font("regular", 26), fill=TEXT, anchor="lm")
            d.text((W - PAD - 52, cy + 23), f"{s.value:,}".replace(",", ""), font=font("bold", 28), fill=TEXT, anchor="rm")
            cy += 54
        y += summary_h + 24

    # --- floors
    for f in floors:
        block_h = FLOOR_HEADER_H + len(f.chambers) * CHAMBER_H
        panel(d, (PAD, y, W - PAD, y + block_h), radius=26)
        d.ellipse((PAD + 28, y + 26, PAD + 28 + 64, y + 26 + 64), fill=(239, 230, 211))
        d.text((PAD + 60, y + 58), str(f.number), font=font("bold", 34), fill=GOLD_DARK, anchor="mm")
        d.text((PAD + 114, y + 58), f"Spiral Abyss Floor {f.number}", font=font("semibold", 36), fill=TEXT, anchor="lm")
        draw_star(d, W - PAD - 150, y + 58, 22, GOLD)
        d.text((W - PAD - 40, y + 58), f"{f.stars}/{f.max_stars}", font=font("bold", 34), fill=TEXT, anchor="rm")
        cy = y + FLOOR_HEADER_H
        for ch in f.chambers:
            d.line((PAD + 28, cy, W - PAD - 28, cy), fill=(255, 255, 255, 34), width=2)
            d.text((PAD + 30, cy + 22), f"Chamber {ch.number}", font=font("serif", 30), fill=GOLD)
            d.text((PAD + 30, cy + 58), _fmt_time(ch.timestamp, tz_hours), font=font("regular", 20), fill=MUTED)
            draw_stars(d, W - PAD - 30, cy + 40, ch.stars, 3)
            ry = cy + 92
            for half_i, (label, chars) in enumerate((("First Half", ch.first_half), ("Second Half", ch.second_half))):
                hx = PAD + 30 + half_i * (HALF_W + HALF_GAP)
                d.text((hx, ry), label, font=font("serif", 24), fill=TEXT)
                for i, c in enumerate(chars[:4]):
                    character_tile(
                        img, d, hx + i * (TILE + TILE_GAP), ry + 38, TILE,
                        rarity=c.rarity, level=c.level, icon=load_icon(icons.get(c.icon)), strip_font_size=20,
                    )
            cy += CHAMBER_H
        y += block_h + 24

    # --- footer
    label = {"live": "Live data", "cached": "Cached data", "stale": "Stale data (HoYoLAB unreachable)"}.get(source, "Data")
    stamp = fetched_at.astimezone(timezone.utc).strftime("%Y-%m-%d %H:%M UTC")
    d.text((PAD, y + 20), f"{label}  ·  fetched {stamp}", font=font("medium", 22), fill=GOLD if source == "live" else (240, 170, 110))
    d.text((PAD, y + 58), f"Unofficial community tool, not affiliated with HoYoverse  ·  {REPORT_VERSION}", font=font("regular", 20), fill=MUTED)
    return to_png(img)
