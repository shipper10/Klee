"""Single-character detail card, styled after the HoYoLAB Battle Chronicle character page."""

from __future__ import annotations

from datetime import datetime, timezone

from app.character import ARTIFACT_SLOTS, CharacterDetail
from app.regions import mask_uid, server_label
from app.ui_kit import GOLD, GOLD_DARK, MUTED, TEXT, character_tile, fit_text, font, load_icon, new_canvas, panel, to_png

REPORT_VERSION = "character-v1"
W = 1080
PAD = 48
INNER = W - 2 * PAD
ART_H = 128
HEAD_H = 250
WEAPON_H = 182


def render_character_card(
    c: CharacterDetail, *, nickname: str, uid: str, server: str, icons: dict[str, bytes], fetched_at: datetime, source: str,
) -> bytes:
    stat_rows = -(-len(c.stats) // 3)
    arts_h = (84 + len(c.artifacts) * ART_H + (44 if c.sets else 0) + 16) if c.artifacts else 0
    stats_h = (84 + stat_rows * 82 + 6) if c.stats else 0
    talents_h = 84 + max(len(c.talents), 1) * 46 + (96 if c.constellations else 0)
    weapon_h = WEAPON_H if c.weapon else 0
    height = 60 + HEAD_H + 24 + (weapon_h + 24 if weapon_h else 0) + (arts_h + 24 if arts_h else 0) + (stats_h + 24 if stats_h else 0) + talents_h + 24 + 120
    img, d = new_canvas(W, height)
    y = 48

    # --- head
    panel(d, (PAD, y, W - PAD, y + HEAD_H), radius=26)
    character_tile(img, d, PAD + 30, y + 30, 160, rarity=c.rarity, level=c.level, icon=load_icon(icons.get(c.icon)), strip_font_size=24)
    tx = PAD + 30 + 160 + 34
    d.text((tx, y + 36), fit_text(d, c.name or "Unknown", font("bold", 52), W - PAD - 30 - tx), font=font("bold", 52), fill=TEXT)
    d.text((tx, y + 106), f"{c.element}  ·  C{c.constellation}  ·  Friendship {c.friendship}", font=font("regular", 26), fill=GOLD)
    d.text((tx, y + 156), f"{c.rarity}-star", font=font("medium", 24), fill=MUTED)
    d.text((tx, y + 200), f"{nickname or 'Traveler'}  ·  {server_label(server)}  ·  UID {mask_uid(uid)}", font=font("regular", 22), fill=MUTED)
    y += HEAD_H + 24

    # --- weapon
    if c.weapon:
        w = c.weapon
        panel(d, (PAD, y, W - PAD, y + WEAPON_H), radius=26)
        d.text((PAD + 30, y + 22), "Weapon", font=font("serif", 26), fill=GOLD)
        character_tile(img, d, PAD + 30, y + 64, 90, rarity=w.rarity, level=None, icon=load_icon(icons.get(w.icon)))
        wx = PAD + 30 + 90 + 28
        d.text((wx, y + 70), fit_text(d, w.name, font("semibold", 32), W - PAD - 30 - wx), font=font("semibold", 32), fill=TEXT)
        d.text((wx, y + 116), f"Lv. {w.level}  ·  Refinement {w.refinement}", font=font("regular", 24), fill=MUTED)
        sx = W - PAD - 30
        if w.main:
            d.text((sx, y + 74), f"{w.main.name}  {w.main.value}", font=font("medium", 24), fill=TEXT, anchor="rm")
        if w.sub:
            d.text((sx, y + 112), f"{w.sub.name}  {w.sub.value}", font=font("medium", 24), fill=TEXT, anchor="rm")
        y += weapon_h + 24

    # --- artifacts
    if c.artifacts:
        panel(d, (PAD, y, W - PAD, y + arts_h), radius=26)
        d.text((PAD + 30, y + 24), "Artifacts", font=font("semibold", 32), fill=TEXT)
        ay = y + 80
        for a in c.artifacts:
            d.line((PAD + 30, ay - 6, W - PAD - 30, ay - 6), fill=(255, 255, 255, 30), width=2)
            character_tile(img, d, PAD + 30, ay + 4, 82, rarity=a.rarity, level=f"+{a.level}", icon=load_icon(icons.get(a.icon)), strip_font_size=16)
            ax = PAD + 30 + 82 + 24
            d.text((ax, ay + 10), f"{ARTIFACT_SLOTS.get(a.slot, '')}  ·  {fit_text(d, a.set_name, font('regular', 20), 300)}", font=font("regular", 20), fill=MUTED)
            if a.main:
                d.text((ax, ay + 40), f"{a.main.name}", font=font("semibold", 24), fill=GOLD)
                d.text((ax, ay + 72), a.main.value, font=font("bold", 30), fill=TEXT)
            for i, s in enumerate(a.subs[:4]):
                sx = ax + 330 + (i % 2) * 300
                sy = ay + 12 + (i // 2) * 58
                d.text((sx, sy), f"{s.name}", font=font("regular", 20), fill=MUTED)
                d.text((sx, sy + 24), s.value, font=font("semibold", 22), fill=TEXT)
            ay += ART_H
        if c.sets:
            d.text((PAD + 30, ay + 6), "Sets: " + ",  ".join(c.sets), font=font("medium", 22), fill=GOLD)
        y += arts_h + 24

    # --- stats
    if c.stats:
        panel(d, (PAD, y, W - PAD, y + stats_h), radius=26)
        d.text((PAD + 30, y + 24), "Attributes", font=font("semibold", 32), fill=TEXT)
        cw = (INNER - 60 - 28) // 3
        for i, s in enumerate(c.stats):
            cx = PAD + 30 + (i % 3) * (cw + 14)
            cy = y + 84 + (i // 3) * 82
            d.rounded_rectangle((cx, cy, cx + cw, cy + 70), radius=12, fill=(255, 255, 255, 22))
            d.text((cx + 16, cy + 10), fit_text(d, s.name, font("regular", 18), cw - 32), font=font("regular", 18), fill=MUTED)
            d.text((cx + 16, cy + 48), s.value, font=font("bold", 26), fill=TEXT, anchor="lm")
        y += stats_h + 24

    # --- talents + constellations
    panel(d, (PAD, y, W - PAD, y + talents_h), radius=26)
    d.text((PAD + 30, y + 24), "Talents", font=font("semibold", 32), fill=TEXT)
    ty = y + 84
    for t in c.talents:
        d.text((PAD + 30, ty), fit_text(d, t.name, font("regular", 24), INNER - 200), font=font("regular", 24), fill=TEXT)
        d.text((W - PAD - 30, ty), f"Lv. {t.level}", font=font("bold", 26), fill=GOLD, anchor="ra")
        ty += 46
    if not c.talents:
        d.text((PAD + 30, ty), "No talent data", font=font("regular", 24), fill=MUTED)
        ty += 46
    if c.constellations:
        d.text((PAD + 30, ty + 8), "Constellations", font=font("serif", 26), fill=GOLD)
        for i, (name, on) in enumerate(c.constellations[:6]):
            cx = PAD + 330 + i * 70
            d.ellipse((cx, ty, cx + 52, ty + 52), fill=GOLD if on else (255, 255, 255, 30), outline=(255, 255, 255, 60))
            d.text((cx + 26, ty + 26), f"C{i + 1}", font=font("bold", 20), fill=GOLD_DARK if on else MUTED, anchor="mm")
    y += talents_h + 24

    label = {"live": "Live data", "cached": "Cached data", "stale": "Stale data (HoYoLAB unreachable)"}.get(source, "Data")
    stamp = fetched_at.astimezone(timezone.utc).strftime("%Y-%m-%d %H:%M UTC")
    d.text((PAD, y + 20), f"{label}  ·  fetched {stamp}", font=font("medium", 22), fill=GOLD if source == "live" else (240, 170, 110))
    d.text((PAD, y + 58), f"Unofficial community tool, not affiliated with HoYoverse  ·  {REPORT_VERSION}", font=font("regular", 20), fill=MUTED)
    return to_png(img)
