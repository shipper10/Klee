"""Daily Notes card (PNG). Pure function of its inputs, so identical input gives identical output.

Uses Pillow's built-in scalable font so nothing has to be downloaded at build or run time.
Visual style is original; it follows the information layout of Battle Chronicle only loosely.
"""

from __future__ import annotations

import io
from datetime import datetime, timezone
from functools import lru_cache

from PIL import Image, ImageDraw, ImageFont

from app.notes import NotesData
from app.ui_kit import C, themed

REPORT_VERSION = "notes-v1"

W = 960
PAD = 40



@lru_cache(maxsize=32)
def _font(size: int) -> ImageFont.FreeTypeFont:
    return ImageFont.load_default(size=size)  # type: ignore[return-value]


def fmt_duration(seconds: int) -> str:
    seconds = max(0, int(seconds))
    if seconds < 60:
        return "now" if seconds == 0 else "<1m"
    minutes = seconds // 60
    days, minutes = divmod(minutes, 1440)
    hours, minutes = divmod(minutes, 60)
    if days:
        return f"{days}d {hours}h"
    if hours:
        return f"{hours}h {minutes}m"
    return f"{minutes}m"


def _fit(draw: ImageDraw.ImageDraw, text: str, font: ImageFont.FreeTypeFont, max_width: int) -> str:
    if draw.textlength(text, font=font) <= max_width:
        return text
    while text and draw.textlength(text + "…", font=font) > max_width:
        text = text[:-1]
    return text + "…"


def _card(draw: ImageDraw.ImageDraw, x: int, y: int, w: int, h: int) -> None:
    draw.rounded_rectangle((x, y, x + w, y + h), radius=22, fill=C.CARD)


def _bar(draw: ImageDraw.ImageDraw, x: int, y: int, w: int, h: int, ratio: float, color: tuple[int, int, int]) -> None:
    ratio = min(1.0, max(0.0, ratio))
    draw.rounded_rectangle((x, y, x + w, y + h), radius=h // 2, fill=C.BAR_BG)
    if ratio > 0:
        draw.rounded_rectangle((x, y, x + max(h, int(w * ratio)), y + h), radius=h // 2, fill=color)


def _stat_card(
    draw: ImageDraw.ImageDraw, x: int, y: int, w: int, h: int, title: str, value: str, sub: str, color=C.TEXT
) -> None:
    _card(draw, x, y, w, h)
    draw.text((x + 26, y + 20), title, font=_font(24), fill=C.MUTED)
    draw.text((x + 26, y + 58), value, font=_font(44), fill=color)
    draw.text((x + 26, y + h - 38), _fit(draw, sub, _font(22), w - 52), font=_font(22), fill=C.MUTED)


@themed
def render_notes_card(
    data: NotesData,
    *,
    nickname: str,
    uid_masked: str,
    server_label: str,
    fetched_at: datetime,
    source: str,
    now: datetime | None = None,
) -> bytes:
    now = now or datetime.now(timezone.utc)
    age = max(0, int((now - fetched_at).total_seconds()))

    def left(seconds: int) -> int:
        # Remaining times are counted down from when the data was fetched.
        return max(0, seconds - age)

    rows = max(len(data.expeditions), 1)
    height = PAD + 110 + 20 + 220 + 20 + 2 * 170 + 20 + (90 + rows * 54) + 20 + 90 + PAD
    img = Image.new("RGB", (W, height), C.NOTES_BG)
    d = ImageDraw.Draw(img)
    inner = W - 2 * PAD
    y = PAD

    # Header
    d.text((PAD, y), _fit(d, nickname or "Traveler", _font(44), inner - 260), font=_font(44), fill=C.TEXT)
    d.text((PAD, y + 62), f"UID {uid_masked}  ·  {server_label}", font=_font(26), fill=C.MUTED)
    d.text((W - PAD, y + 6), "Daily Notes", font=_font(34), fill=C.GOLD, anchor="ra")
    y += 110 + 20

    # Resin
    _card(d, PAD, y, inner, 220)
    d.text((PAD + 30, y + 24), "Original Resin", font=_font(26), fill=C.MUTED)
    d.text((PAD + 30, y + 62), f"{data.current_resin}", font=_font(84), fill=C.TEXT)
    num_w = d.textlength(f"{data.current_resin}", font=_font(84))
    d.text((PAD + 30 + num_w + 8, y + 112), f"/ {data.max_resin}", font=_font(36), fill=C.MUTED)
    resin_left = left(data.resin_recovery_seconds)
    full = data.current_resin >= data.max_resin
    d.text(
        (W - PAD - 30, y + 30),
        "Full" if full else f"Full in {fmt_duration(resin_left)}",
        font=_font(30),
        fill=C.GOOD if full else C.GOLD,
        anchor="ra",
    )
    _bar(d, PAD + 30, y + 172, inner - 60, 18, data.current_resin / max(1, data.max_resin), C.GOLD)
    y += 220 + 20

    # Four stats
    gap = 20
    cw = (inner - gap) // 2
    realm_left = left(data.realm_currency_recovery_seconds)
    realm_full = data.current_realm_currency >= data.max_realm_currency
    _stat_card(
        d, PAD, y, cw, 170, "Realm Currency",
        f"{data.current_realm_currency} / {data.max_realm_currency}",
        "Full" if realm_full else f"Full in {fmt_duration(realm_left)}",
    )
    done = data.completed_commissions >= data.max_commissions
    _stat_card(
        d, PAD + cw + gap, y, cw, 170, "Daily Commissions",
        f"{data.completed_commissions} / {data.max_commissions}",
        "Reward claimed" if data.claimed_commission_reward else ("Reward ready to claim" if done else "In progress"),
        color=C.GOOD if done else C.TEXT,
    )
    y += 170 + gap
    _stat_card(
        d, PAD, y, cw, 170, "Weekly Boss Discounts",
        f"{data.remaining_resin_discounts} / {data.max_resin_discounts}",
        "remaining this week",
    )
    if data.transformer_recovery_seconds is None:
        t_value, t_sub, t_color = "N/A", "Not available on this account", C.MUTED
    else:
        t_left = left(data.transformer_recovery_seconds)
        t_value = "Ready" if t_left == 0 else fmt_duration(t_left)
        t_sub, t_color = ("Can be used now" if t_left == 0 else "until ready"), (C.GOOD if t_left == 0 else C.TEXT)
    _stat_card(d, PAD + cw + gap, y, cw, 170, "Parametric Transformer", t_value, t_sub, color=t_color)
    y += 170 + 20

    # Expeditions
    block_h = 90 + rows * 54
    _card(d, PAD, y, inner, block_h)
    d.text((PAD + 30, y + 22), "Expeditions", font=_font(28), fill=C.TEXT)
    d.text(
        (W - PAD - 30, y + 26),
        f"{len(data.expeditions)} / {data.max_expeditions} sent",
        font=_font(24), fill=C.MUTED, anchor="ra",
    )
    ry = y + 80
    if not data.expeditions:
        d.text((PAD + 30, ry), "No expeditions in progress", font=_font(26), fill=C.MUTED)
    for i, exp in enumerate(data.expeditions, start=1):
        remaining = left(exp.remaining_seconds)
        done_exp = remaining == 0
        d.ellipse((PAD + 30, ry + 10, PAD + 46, ry + 26), fill=C.GOOD if done_exp else C.WARN)
        d.text((PAD + 64, ry), f"Expedition {i}", font=_font(26), fill=C.TEXT)
        d.text(
            (W - PAD - 30, ry), "Finished" if done_exp else f"Ready in {fmt_duration(remaining)}",
            font=_font(26), fill=C.GOOD if done_exp else C.MUTED, anchor="ra",
        )
        ry += 54
    y += block_h + 20

    # Footer: freshness + disclaimer
    label = {"live": "Live data", "cached": "Cached data", "stale": "Stale data (HoYoLAB unreachable)"}.get(
        source, "Data"
    )
    stamp = fetched_at.astimezone(timezone.utc).strftime("%Y-%m-%d %H:%M UTC")
    d.text((PAD, y + 8), f"{label}  ·  fetched {stamp}", font=_font(24), fill=C.GOLD if source == "live" else C.WARN)
    d.text(
        (PAD, y + 46),
        f"Unofficial community tool, not affiliated with HoYoverse  ·  {REPORT_VERSION}",
        font=_font(20), fill=C.MUTED,
    )

    buf = io.BytesIO()
    img.save(buf, format="PNG")
    return buf.getvalue()
