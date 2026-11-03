"""Stygian Onslaught report image, styled after the HoYoLAB Battle Chronicle share card."""

from __future__ import annotations

from datetime import datetime, timezone

from app.render_abyss import _fmt_period
from app.stygian import BEST_KINDS, SChallenge, StygianData
from app.ui_kit import C, character_tile, fit_text, font, load_icon, new_canvas, panel, themed, to_png

REPORT_VERSION = "stygian-v1"
W = 1080
PAD = 48
INNER = W - 2 * PAD
TILE = 104
GAP = 12
CH_H = 96 + round(TILE * 1.24) + 14 + 34 + 3 * 28 + 18


def _clock(seconds: int) -> str:
    return f"{seconds // 60}:{seconds % 60:02d}" if seconds else "-"


@themed
def render_stygian_card(
    data: StygianData, *, nickname: str, icons: dict[str, bytes], multi: bool, tz_hours: int,
    fetched_at: datetime, source: str, uid: str = "",
) -> bytes:
    mode = data.mode(multi)
    challenges = mode.challenges
    height = 250 + 200 + len(challenges) * (CH_H + 24) + 130
    img, d = new_canvas(W, height)

    d.text((PAD, 48), f"Dear {fit_text(d, nickname or 'Traveler', font('bold', 52), INNER - 190)}", font=font("bold", 52), fill=C.TEXT)
    d.text((PAD, 118), "Review your Stygian Onslaught records~", font=font("regular", 26), fill=C.MUTED)
    period = f"Period: {_fmt_period(data.period_start, data.period_end, tz_hours)}" if data.period_start else "Stygian Onslaught"
    pw = int(d.textlength(period, font=font("semibold", 24))) + 48
    d.rounded_rectangle((PAD, 164, PAD + pw, 204), radius=20, fill=C.GOLD)
    d.text((PAD + pw / 2, 184), period, font=font("semibold", 24), fill=C.GOLD_DARK, anchor="mm")
    y = 250

    panel(d, (PAD, y, W - PAD, y + 176), radius=26)
    d.text((PAD + 30, y + 36), fit_text(d, data.season or "Stygian Onslaught", font("semibold", 32), INNER - 300), font=font("semibold", 32), fill=C.TEXT)
    d.text((W - PAD - 30, y + 38), "Co-op" if multi else "Single Player", font=font("medium", 24), fill=C.MUTED, anchor="rm")
    cw = (INNER - 60 - 14) // 2
    for i, (label, value) in enumerate((("Best Difficulty", f"Level {mode.best_difficulty}" if mode.best_difficulty else "-"),
                                        ("Best Clear Time", _clock(mode.best_seconds)))):
        cx = PAD + 30 + i * (cw + 14)
        d.rounded_rectangle((cx, y + 88, cx + cw, y + 160), radius=14, fill=C.tint(22))
        d.text((cx + 18, y + 96), label, font=font("regular", 20), fill=C.MUTED)
        d.text((cx + 18, y + 138), value, font=font("bold", 30), fill=C.TEXT, anchor="lm")
    y += 176 + 24

    for ch in challenges:
        _draw_challenge(img, d, ch, y, icons)
        y += CH_H + 24

    label = {"live": "Live data", "cached": "Cached data", "stale": "Stale data (HoYoLAB unreachable)"}.get(source, "Data")
    stamp = fetched_at.astimezone(timezone.utc).strftime("%Y-%m-%d %H:%M UTC")
    d.text((PAD, y + 20), f"{label}  ·  fetched {stamp}", font=font("medium", 22), fill=C.GOLD if source == "live" else C.WARN)
    d.text((PAD, y + 58), f"Unofficial community tool, not affiliated with HoYoverse  ·  {REPORT_VERSION}", font=font("regular", 20), fill=C.MUTED)
    return to_png(img)


def _draw_challenge(img, d, ch: SChallenge, y: int, icons: dict[str, bytes]) -> None:
    panel(d, (PAD, y, W - PAD, y + CH_H), radius=26)
    d.text((PAD + 30, y + 24), fit_text(d, ch.name or "Challenge", font("serif", 32), 520), font=font("serif", 32), fill=C.GOLD)
    d.text((W - PAD - 30, y + 40), f"Time {_clock(ch.seconds)}", font=font("semibold", 26), fill=C.TEXT, anchor="rm")
    ty = y + 96
    for i, c in enumerate(ch.team[:4]):
        character_tile(img, d, PAD + 30 + i * (TILE + GAP), ty, TILE, rarity=c.rarity, level=c.level,
                       icon=load_icon(icons.get(c.icon)), strip_font_size=20)
    bx = PAD + 30 + 4 * (TILE + GAP) + 40
    for i, b in enumerate(ch.best[:2]):
        x = bx + i * 220
        character_tile(img, d, x, ty, TILE, rarity=b.rarity, level=b.value or None, icon=load_icon(icons.get(b.icon)), strip_font_size=18)
        d.text((x + TILE / 2, ty + round(TILE * 1.24) + 16), BEST_KINDS.get(b.kind, "Best"), font=font("regular", 18), fill=C.MUTED, anchor="mm")
    ly = ty + round(TILE * 1.24) + 14 + 22
    enemy = f"Enemy: {ch.enemy_name}" + (f"  ·  Lv. {ch.enemy_level}" if ch.enemy_level else "") if ch.enemy_name else "Enemy: -"
    d.text((PAD + 30, ly), fit_text(d, enemy, font("semibold", 22), INNER - 60), font=font("semibold", 22), fill=C.TEXT)
    ly += 34
    for note in ch.enemy_notes[:3]:
        d.text((PAD + 30, ly), fit_text(d, note, font("regular", 20), INNER - 60), font=font("regular", 20), fill=C.MUTED)
        ly += 28
