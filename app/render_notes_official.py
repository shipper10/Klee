"""Real-Time Notes in the style of the official HoYoLAB page (cream cards with a tan value column).

Cards sit in two columns and expeditions in two columns, so the image stays short. Icons: game textures
(resin, realm currency, parametric transformer) bundled under app/assets/ui; the commission and
enemy markers are drawn; expedition portraits are the side icons HoYoLAB sends.
"""

from __future__ import annotations

import io
from datetime import datetime, timezone

from PIL import Image, ImageDraw

from app.asset_manager import Assets
from app.notes import NotesData
from app.render_notes import fmt_duration  # noqa: F401  (kept for compatibility)
from app.render_stygian_official import _circle, _wrap
from app.ui_kit import font, load_icon

REPORT_VERSION = "notes-official-v1"
W, PAD, GAP = 1080, 40, 20
CARD_W = (W - 2 * PAD - GAP) // 2
CARD_H = 132
VALUE_W = 160
BG = (240, 230, 222)
CARD = (246, 242, 234)
CARD_EDGE = (226, 214, 200)
VALUE_BG = (233, 224, 212)
INK = (38, 34, 30)
SUB = (170, 154, 136)
VALUE = (128, 96, 66)
GOOD = (96, 140, 84)


def long_duration(seconds: int) -> str:
    """'2 min', '10 h 3 min', '3 d 4 h' (the wording of the official page)."""
    minutes = max(0, int(seconds)) // 60
    days, minutes = divmod(minutes, 1440)
    hours, minutes = divmod(minutes, 60)
    if days:
        return f"{days} d {hours} h" if hours else f"{days} d"
    if hours:
        return f"{hours} h {minutes} min" if minutes else f"{hours} h"
    return f"{max(1, minutes)} min" if seconds > 0 else "0 min"


def _diamond(d: ImageDraw.ImageDraw, cx: int, cy: int, r: int, fill, inner=None) -> None:
    d.polygon([(cx, cy - r), (cx + r, cy), (cx, cy + r), (cx - r, cy)], fill=fill)
    if inner:
        k = r // 2
        d.polygon([(cx, cy - k), (cx + k, cy), (cx, cy + k), (cx - k, cy)], fill=inner)


def _icon(img: Image.Image, kind: str, x: int, y: int, size: int, assets: Assets) -> None:
    name = {"resin": "notes_resin", "realm": "notes_realm", "transformer": "notes_transformer"}.get(kind)
    pic = assets.ui(name, size) if name else None
    if pic is not None:
        img.paste(pic, (x, y), pic)
        return
    d = ImageDraw.Draw(img, "RGBA")  # drawn markers (also the fallback for a missing texture)
    cx, cy = x + size // 2, y + size // 2
    if kind == "commission":
        _diamond(d, cx, cy, size // 2, (150, 110, 205), (238, 226, 250))
    elif kind == "enemies":
        _diamond(d, cx, cy, size // 2, (36, 40, 52), (74, 190, 196))
    else:
        d.ellipse((x + 4, y + 4, x + size - 4, y + size - 4), fill=(190, 170, 140))


def _card(img: Image.Image, d: ImageDraw.ImageDraw, x: int, y: int, w: int, kind: str, title: str, sub: str, value: str, assets: Assets, vcolor=VALUE) -> None:
    d.rectangle((x, y, x + w, y + CARD_H), fill=CARD, outline=CARD_EDGE, width=2)
    d.rectangle((x + w - VALUE_W, y + 2, x + w - 2, y + CARD_H - 2), fill=VALUE_BG)
    _icon(img, kind, x + 20, y + CARD_H // 2 - 20, 40, assets)
    text_w = w - VALUE_W - 76 - 16
    tl = _wrap(d, title, font("bold", 23), text_w, 2)
    sl = _wrap(d, sub, font("regular", 18), text_w, 4 - len(tl))
    block = len(tl) * 29 + len(sl) * 23 + 4
    ty = y + (CARD_H - block) // 2
    for i, line in enumerate(tl):
        d.text((x + 76, ty + 14 + i * 29), line, font=font("bold", 23), fill=INK, anchor="lm")
    for i, line in enumerate(sl):
        d.text((x + 76, ty + len(tl) * 29 + 14 + i * 23), line, font=font("regular", 18), fill=SUB, anchor="lm")
    vf = font("medium", 28 if len(value) <= 9 else 21)
    cx = x + w - VALUE_W // 2
    lines = [value] if len(value) <= 9 else _wrap(d, value, vf, VALUE_W - 20, 2)
    for i, line in enumerate(lines):
        d.text((cx, y + CARD_H / 2 + (i - (len(lines) - 1) / 2) * 28), line, font=vf, fill=vcolor, anchor="mm")


def render_notes_official(
    data: NotesData, *, nickname: str, uid_masked: str, server_label: str, fetched_at: datetime, source: str,
    icons: dict[str, bytes] | None = None, now: datetime | None = None, style: str = "official",
) -> bytes:
    icons = icons or {}
    assets = Assets()
    now = now or datetime.now(timezone.utc)
    age = max(0, int((now - fetched_at).total_seconds()))

    def left(seconds: int) -> int:
        return max(0, seconds - age)  # remaining times count down from when the data was fetched

    exp_rows = max(1, (len(data.expeditions) + 1) // 2)
    exp_h = 76 + exp_rows * 82 + 14
    height = 150 + 3 * (CARD_H + GAP) + exp_h + 120
    img = Image.new("RGB", (W, height), BG)
    d = ImageDraw.Draw(img, "RGBA")

    d.text((PAD, 52), "Real-Time Notes", font=font("bold", 44), fill=INK, anchor="lm")
    d.text((PAD, 100), f"{nickname or 'Traveler'}  ·  UID {uid_masked}  ·  {server_label}", font=font("medium", 24), fill=SUB, anchor="lm")
    d.text((W - PAD, 100), "There may be a delay in data refresh; refer to the actual game data.", font=font("regular", 17), fill=SUB, anchor="rm")

    resin_full = data.current_resin >= data.max_resin
    resin_sub = "Original Resin is full" if resin_full else f"{long_duration(left(data.resin_recovery_seconds))} until fully replenished"
    realm_full = data.current_realm_currency >= data.max_realm_currency
    realm_sub = "The limit has been reached" if realm_full else f"The limit will be reached in {long_duration(left(data.realm_currency_recovery_seconds))}"
    done = data.completed_commissions >= data.max_commissions
    com_sub = ("Daily Commission Reward has already been claimed" if data.claimed_commission_reward
               else "Daily Commission Reward is ready to claim" if done else "Daily Commissions in progress")
    if data.transformer_recovery_seconds is None:
        t_sub, t_val = "Not available on this account", "N/A"
    else:
        t_left = left(data.transformer_recovery_seconds)
        t_sub, t_val = ("Can be used now", "Ready") if t_left == 0 else (f"Can be used again after {long_duration(t_left)}", "Cooldown in progress")

    cards = [
        ("resin", "Original Resin", resin_sub, f"{data.current_resin}/{data.max_resin}", GOOD if resin_full else VALUE),
        ("realm", "Jar of Riches - Realm Currency", realm_sub, f"{data.current_realm_currency}/{data.max_realm_currency}", GOOD if realm_full else VALUE),
        ("commission", "Daily Commissions", com_sub, f"{data.completed_commissions}/{data.max_commissions}", GOOD if done else VALUE),
        ("enemies", "Enemies of Note", "Remaining resin cost-halving opportunities this week", f"{data.remaining_resin_discounts}/{data.max_resin_discounts}", VALUE),
        ("transformer", "Parametric Transformer", t_sub, t_val, GOOD if t_val == "Ready" else VALUE),
    ]
    y = 150
    for i, (kind, title, sub, value, vc) in enumerate(cards):
        if i == 0:  # resin is the headline card: full width
            _card(img, d, PAD, y, W - 2 * PAD, kind, title, sub, value, assets, vc)
        else:
            col, row = (i - 1) % 2, 1 + (i - 1) // 2
            _card(img, d, PAD + col * (CARD_W + GAP), y + row * (CARD_H + GAP), CARD_W, kind, title, sub, value, assets, vc)
    y += 3 * (CARD_H + GAP)
    d.rectangle((PAD, y, W - PAD, y + exp_h), fill=CARD, outline=CARD_EDGE, width=2)
    d.text((PAD + 28, y + 38), f"Expedition Limit ({len(data.expeditions)}/{data.max_expeditions})", font=font("bold", 26), fill=(98, 92, 86), anchor="lm")
    colw = (W - 2 * PAD - 56 - 16) // 2
    if not data.expeditions:
        d.text((PAD + 28, y + 100), "No expeditions in progress", font=font("regular", 22), fill=SUB, anchor="lm")
    for i, e in enumerate(data.expeditions):
        ex = PAD + 28 + (i % 2) * (colw + 16)
        ey = y + 76 + (i // 2) * 82
        d.rounded_rectangle((ex, ey, ex + colw, ey + 68), radius=34, fill=(236, 226, 214))
        _circle(img, ex + 6, ey + 6, 56, load_icon(icons.get(e.icon)), color=(214, 196, 170))
        d.ellipse((ex + 6, ey + 6, ex + 62, ey + 62), outline=(222, 176, 96), width=3)
        rem = left(e.remaining_seconds)
        txt = "Expedition Finished" if rem == 0 else f"Expedition Time Remaining: {long_duration(rem)}"
        d.text((ex + 78, ey + 34), txt, font=font("bold", 21), fill=GOOD if rem == 0 else (176, 160, 142), anchor="lm")
    y += exp_h + 28

    label = {"live": "Live data", "cached": "Cached data", "stale": "Stale data (HoYoLAB unreachable)"}.get(source, "Data")
    stamp = fetched_at.astimezone(timezone.utc).strftime("%Y-%m-%d %H:%M UTC")
    d.text((PAD, y + 12), f"{label}  ·  fetched {stamp}", font=font("medium", 22), fill=VALUE if source == "live" else (190, 120, 70))
    d.text((PAD, y + 48), f"Unofficial community tool, not affiliated with HoYoverse  ·  {REPORT_VERSION}", font=font("regular", 19), fill=SUB)
    buf = io.BytesIO()
    img.crop((0, 0, W, y + 84)).save(buf, format="PNG")
    return buf.getvalue()
