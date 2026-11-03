"""'Showcase' layout for /profile and /characters: blurred splash header, player numbers, character grid."""

from __future__ import annotations

import io
from datetime import datetime, timezone

from PIL import Image, ImageDraw

from app.profile import ProfChar, ProfileData
from app.regions import mask_uid, server_label
from app.render_showcase import ABBR, DEFAULT_ACCENT, ELEMENT, MUTED, TEXT, _background, _glass  # noqa: F401
from app.ui_kit import character_tile, fit_text, font, load_icon

REPORT_VERSION = "showcase-profile-v1"
W = 1600
M = 24
TILE = 112
COLS = 12
GAP = 14
HEAD_H = 270


def splash_key(c: ProfChar) -> str:
    return f"splash:{c.id}"


def _numbers(p: ProfileData) -> list[tuple[str, str]]:
    return [
        (f"{p.achievements}", "Total Achievements"),
        (p.spiral_abyss or "-", "Spiral Abyss"),
        (f"Act {p.theater_act}" if p.theater_unlocked and p.theater_act else "-", "Imaginarium Theater"),
        (f"Diff. {p.stygian_difficulty}" if p.stygian_unlocked and p.stygian_difficulty else "-", "Stygian Onslaught"),
    ]


def _cells(p: ProfileData) -> list[tuple[str, str]]:
    return [
        ("Days Active", f"{p.days_active}"), ("Characters", f"{p.characters_owned}"), ("Max Friendship", f"{p.max_friendship}"),
        ("Chests Opened", f"{p.chests}"), ("Oculi Collected", f"{p.oculi}"), ("Waypoints", f"{p.waypoints}"),
    ]


def render_profile_showcase(
    data: ProfileData, *, nickname: str, uid: str, server: str, icons: dict[str, bytes],
    characters: list[ProfChar], fetched_at: datetime, source: str, summary: bool = True, style: str = "showcase",
) -> bytes:
    top = characters[0] if characters else None
    accent = ELEMENT.get(top.element, DEFAULT_ACCENT) if top else DEFAULT_ACCENT
    splash = load_icon(icons.get(splash_key(top))) if top else None
    portrait = load_icon(icons.get(top.icon)) if top else None

    cells = _cells(data) if summary else []
    rows_g = max(1, -(-len(characters) // COLS))
    cell_h = 96
    cells_h = (cell_h + 12) * -(-len(cells) // 6) if cells else 0
    grid_h = 70 + rows_g * (round(TILE * 1.24) + 16) + 10
    height = HEAD_H + 16 + (cells_h + 4 if cells else 0) + grid_h + 24 + 90
    img = _background(splash, portrait, accent, height)
    d = ImageDraw.Draw(img, "RGBA")
    d.rectangle((0, 0, W, HEAD_H), fill=(6, 8, 18, 120))

    name = fit_text(d, nickname or data.nickname or "Traveler", font("serif-bold", 72), 800)
    d.text((M + 28, 52), name, font=font("serif-bold", 72), fill=TEXT)
    d.text((M + 28, 150), f"AR {data.level}   ·   {server_label(server)}   ·   UID {mask_uid(uid)}", font=font("medium", 28), fill=TEXT)
    title = "Battle Chronicle" if summary else "All Characters"
    tw = int(d.textlength(title, font=font("semibold", 22))) + 36
    d.rounded_rectangle((M + 28, 200, M + 28 + tw, 238), radius=19, fill=accent + (255,))
    d.text((M + 28 + tw / 2, 219), title, font=font("semibold", 22), fill=(20, 20, 34), anchor="mm")

    # player numbers, right-aligned like the Enka header
    for i, (value, label) in enumerate(_numbers(data)):
        ry = 44 + i * 52
        d.text((W - 360, ry + 22), value, font=font("bold", 34), fill=TEXT, anchor="rm")
        d.text((W - 340, ry + 22), label, font=font("medium", 26), fill=MUTED, anchor="lm")
    y = HEAD_H + 16

    if cells:
        cw = (W - 2 * M - 5 * 12) // 6
        for i, (label, value) in enumerate(cells):
            cx = M + (i % 6) * (cw + 12)
            cy = y + (i // 6) * (cell_h + 12)
            _glass(d, (cx, cy, cx + cw, cy + cell_h), accent)
            d.text((cx + 20, cy + 16), label, font=font("regular", 20), fill=MUTED)
            d.text((cx + 20, cy + 62), fit_text(d, value, font("bold", 34), cw - 40), font=font("bold", 34), fill=TEXT, anchor="lm")
        y += (cell_h + 12) * -(-len(cells) // 6) + 4

    _glass(d, (M, y, W - M, y + grid_h), accent)
    d.text((M + 28, y + 34), "Characters", font=font("semibold", 30), fill=TEXT, anchor="lm")
    d.text((W - M - 28, y + 36), f"{len(characters)} / {data.characters_owned}", font=font("medium", 24), fill=MUTED, anchor="rm")
    if not characters:
        d.text((M + 28, y + 100), "No characters found", font=font("regular", 26), fill=MUTED)
    gx = M + (W - 2 * M - (COLS * TILE + (COLS - 1) * GAP)) // 2
    for i, c in enumerate(characters):
        tx = gx + (i % COLS) * (TILE + GAP)
        ty = y + 66 + (i // COLS) * (round(TILE * 1.24) + 16)
        character_tile(img, d, tx, ty, TILE, rarity=c.rarity, level=c.level, icon=load_icon(icons.get(c.icon)), strip_font_size=20)
        if c.constellation > 0:
            bx, by = tx + TILE - 36, ty + 6
            d.rounded_rectangle((bx, by, bx + 30, by + 26), radius=8, fill=(10, 12, 26, 225))
            d.text((bx + 15, by + 13), f"C{c.constellation}", font=font("semibold", 16), fill=accent if c.constellation >= 6 else TEXT, anchor="mm")
    y += grid_h + 24

    label = {"live": "Live data", "cached": "Cached data", "stale": "Stale data (HoYoLAB unreachable)"}.get(source, "Data")
    stamp = fetched_at.astimezone(timezone.utc).strftime("%Y-%m-%d %H:%M UTC")
    d.text((M + 8, y + 10), f"{label}  ·  fetched {stamp}", font=font("medium", 22), fill=accent if source == "live" else (240, 170, 110))
    d.text((M + 8, y + 46), f"Unofficial community tool, not affiliated with HoYoverse  ·  {REPORT_VERSION}", font=font("regular", 19), fill=MUTED)
    buf = io.BytesIO()
    img.crop((0, 0, W, height)).save(buf, format="PNG")
    return buf.getvalue()
