"""Traveler's Diary report image."""

from __future__ import annotations

import calendar
from datetime import datetime, timezone

from app.diary import DiaryData
from app.ui_kit import C, fit_text, font, new_canvas, panel, themed, to_png

REPORT_VERSION = "diary-v1"
W = 1080
PAD = 48
INNER = W - 2 * PAD


def _rate(rate: int) -> tuple[str, tuple]:
    if rate > 0:
        return f"▲ {rate}% vs last month", C.GOOD
    if rate < 0:
        return f"▼ {abs(rate)}% vs last month", C.WARN
    return "same as last month", C.MUTED


def _money(n: int) -> str:
    return f"{n:,}"


def _block(d, x: int, y: int, w: int, title: str, now: int, last: int, rate: int, today: int) -> None:
    panel(d, (x, y, x + w, y + 276), radius=26)
    d.text((x + 28, y + 26), title, font=font("serif", 32), fill=C.GOLD)
    d.text((x + 28, y + 100), _money(now), font=font("bold", 64), fill=C.TEXT, anchor="lm")
    text, color = _rate(rate)
    d.text((x + 28, y + 152), text, font=font("medium", 22), fill=color)
    d.text((x + 28, y + 196), f"Last month: {_money(last)}", font=font("regular", 22), fill=C.MUTED)
    d.text((x + 28, y + 224), f"Today: {_money(today)}", font=font("regular", 22), fill=C.MUTED)


@themed
def render_diary_card(data: DiaryData, *, nickname: str, fetched_at: datetime, source: str) -> bytes:
    cats = data.categories[:8]
    height = 250 + 276 + 24 + (110 + len(cats) * 64 if cats else 140) + 24 + 120
    img, d = new_canvas(W, height)
    d.text((PAD, 48), f"Dear {fit_text(d, nickname or 'Traveler', font('bold', 52), INNER - 190)}", font=font("bold", 52), fill=C.TEXT)
    d.text((PAD, 118), "Your Traveler's Diary~", font=font("regular", 26), fill=C.MUTED)
    period = f"{calendar.month_name[data.month] if 1 <= data.month <= 12 else data.month} {data.year or ''}".strip()
    pw = int(d.textlength(period, font=font("semibold", 24))) + 48
    d.rounded_rectangle((PAD, 164, PAD + pw, 204), radius=20, fill=C.GOLD)
    d.text((PAD + pw / 2, 184), period, font=font("semibold", 24), fill=C.GOLD_DARK, anchor="mm")

    y = 250
    half = (INNER - 24) // 2
    _block(d, PAD, y, half, "Primogems", data.primogems, data.last_primogems, data.primogem_rate, data.today_primogems)
    _block(d, PAD + half + 24, y, half, "Mora", data.mora, data.last_mora, data.mora_rate, data.today_mora)
    y += 276 + 24

    panel(d, (PAD, y, W - PAD, y + (110 + len(cats) * 64 if cats else 140)), radius=26)
    d.text((PAD + 30, y + 34), "Primogem sources this month", font=font("semibold", 30), fill=C.TEXT)
    if not cats:
        d.text((PAD + 30, y + 90), "No income recorded yet", font=font("regular", 24), fill=C.MUTED)
        y += 140
    else:
        top = max(c.amount for c in cats) or 1
        ry = y + 84
        bar_x, bar_w = PAD + 330, INNER - 330 - 200
        for c in cats:
            d.text((PAD + 30, ry + 22), fit_text(d, c.name, font("regular", 24), 280), font=font("regular", 24), fill=C.TEXT, anchor="lm")
            d.rounded_rectangle((bar_x, ry + 12, bar_x + bar_w, ry + 32), radius=10, fill=C.tint(26))
            fill_w = max(10, round(bar_w * c.amount / top))
            d.rounded_rectangle((bar_x, ry + 12, bar_x + fill_w, ry + 32), radius=10, fill=C.GOLD)
            d.text((W - PAD - 30, ry + 22), f"{_money(c.amount)}  ·  {c.percent}%", font=font("semibold", 24), fill=C.TEXT, anchor="rm")
            ry += 64
        y += 110 + len(cats) * 64
    y += 24

    label = {"live": "Live data", "cached": "Cached data", "stale": "Stale data (HoYoLAB unreachable)"}.get(source, "Data")
    stamp = fetched_at.astimezone(timezone.utc).strftime("%Y-%m-%d %H:%M UTC")
    d.text((PAD, y + 20), f"{label}  ·  fetched {stamp}", font=font("medium", 22), fill=C.GOLD if source == "live" else C.WARN)
    d.text((PAD, y + 58), f"Unofficial community tool, not affiliated with HoYoverse  ·  {REPORT_VERSION}", font=font("regular", 20), fill=C.MUTED)
    return to_png(img)
