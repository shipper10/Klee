"""Profile summary + character grid image, styled after the HoYoLAB Battle Chronicle share cards."""

from __future__ import annotations

from datetime import datetime, timezone

from app.profile import ProfChar, ProfileData
from app.regions import mask_uid, server_label
from app.ui_kit import GOLD, GOLD_DARK, MUTED, TEXT, character_tile, fit_text, font, load_icon, new_canvas, panel, to_png

REPORT_VERSION = "profile-v1"
W = 1080
PAD = 48
INNER = W - 2 * PAD
COLS = 8
TILE = 104
GAP = 12
ROW_H = round(TILE * 1.24) + 16
CELL_H = 98
CELL_COLS = 3


def _cells(p: ProfileData) -> list[tuple[str, str]]:
    return [
        ("Days Active", f"{p.days_active}"),
        ("Achievements", f"{p.achievements}"),
        ("Characters", f"{p.characters_owned}"),
        ("Max Friendship", f"{p.max_friendship}"),
        ("Spiral Abyss", p.spiral_abyss or "-"),
        ("Imaginarium Theater", f"Act {p.theater_act}" if p.theater_unlocked and p.theater_act else "-"),
        ("Stygian Onslaught", f"Diff. {p.stygian_difficulty}" if p.stygian_unlocked and p.stygian_difficulty else "-"),
        ("Chests Opened", f"{p.chests}"),
        ("Oculi Collected", f"{p.oculi}"),
        ("Waypoints", f"{p.waypoints}"),
        ("Domains", f"{p.domains}"),
    ]


def select_characters(p: ProfileData, show_all: bool, default_count: int = 16) -> list[ProfChar]:
    chars = p.sorted_characters()
    return chars if show_all else chars[:default_count]


def render_profile_card(
    data: ProfileData, *, nickname: str, uid: str, server: str, icons: dict[str, bytes],
    characters: list[ProfChar], fetched_at: datetime, source: str, summary: bool = True,
) -> bytes:
    cells = _cells(data) if summary else []
    rows_c = -(-len(cells) // CELL_COLS)
    stats_h = (90 + rows_c * (CELL_H + 14) + 16) if summary else 0
    rows_g = -(-len(characters) // COLS) if characters else 0
    grid_h = 96 + max(rows_g, 1) * ROW_H + 20
    header_h = 250 if summary else 190
    height = header_h + (stats_h + 24 if summary else 0) + grid_h + 24 + 110
    img, d = new_canvas(W, height)

    name = fit_text(d, nickname or data.nickname or "Traveler", font("bold", 52), INNER)
    d.text((PAD, 48), name, font=font("bold", 52), fill=TEXT)
    d.text((PAD, 118), f"Adventure Rank {data.level}  ·  {server_label(server)}  ·  UID {mask_uid(uid)}", font=font("regular", 26), fill=MUTED)
    title = "Battle Chronicle" if summary else "All Characters"
    pw = int(d.textlength(title, font=font("semibold", 24))) + 48
    d.rounded_rectangle((PAD, 168, PAD + pw, 208), radius=20, fill=GOLD)
    d.text((PAD + pw / 2, 188), title, font=font("semibold", 24), fill=GOLD_DARK, anchor="mm")
    y = header_h

    if summary:
        panel(d, (PAD, y, W - PAD, y + stats_h), radius=26)
        d.text((PAD + 30, y + 36), "Overview", font=font("semibold", 32), fill=TEXT)
        cw = (INNER - 60 - (CELL_COLS - 1) * 14) // CELL_COLS
        for i, (label, value) in enumerate(cells):
            cx = PAD + 30 + (i % CELL_COLS) * (cw + 14)
            cy = y + 90 + (i // CELL_COLS) * (CELL_H + 14)
            d.rounded_rectangle((cx, cy, cx + cw, cy + CELL_H), radius=14, fill=(255, 255, 255, 22))
            d.text((cx + 18, cy + 14), label, font=font("regular", 20), fill=MUTED)
            d.text((cx + 18, cy + 69), fit_text(d, value, font("bold", 32), cw - 36), font=font("bold", 32), fill=TEXT, anchor="lm")
        y += stats_h + 24

    panel(d, (PAD, y, W - PAD, y + grid_h), radius=26)
    d.text((PAD + 30, y + 36), "Characters", font=font("semibold", 32), fill=TEXT)
    d.text((W - PAD - 30, y + 38), f"{len(characters)} / {data.characters_owned}", font=font("medium", 24), fill=MUTED, anchor="rm")
    if not characters:
        d.text((PAD + 30, y + 110), "No characters found", font=font("regular", 26), fill=MUTED)
    for i, c in enumerate(characters):
        tx = PAD + 30 + (i % COLS) * (TILE + GAP)
        ty = y + 84 + (i // COLS) * ROW_H
        character_tile(img, d, tx, ty, TILE, rarity=c.rarity, level=c.level, icon=load_icon(icons.get(c.icon)), strip_font_size=20)
        if c.constellation > 0:
            bx, by = tx + TILE - 34, ty + 6
            d.rounded_rectangle((bx, by, bx + 28, by + 24), radius=8, fill=(20, 20, 44, 215))
            d.text((bx + 14, by + 12), f"C{c.constellation}", font=font("semibold", 16), fill=GOLD if c.constellation >= 6 else TEXT, anchor="mm")
    y += grid_h + 24

    label = {"live": "Live data", "cached": "Cached data", "stale": "Stale data (HoYoLAB unreachable)"}.get(source, "Data")
    stamp = fetched_at.astimezone(timezone.utc).strftime("%Y-%m-%d %H:%M UTC")
    d.text((PAD, y + 20), f"{label}  ·  fetched {stamp}", font=font("medium", 22), fill=GOLD if source == "live" else (240, 170, 110))
    d.text((PAD, y + 58), f"Unofficial community tool, not affiliated with HoYoverse  ·  {REPORT_VERSION}", font=font("regular", 20), fill=MUTED)
    return to_png(img)
