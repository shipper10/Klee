"""'Showcase' layout for the single-character card: big splash art, glass panels, element-coloured accents.

Drawn from scratch with Pillow. The splash art comes from public Enka/Ambr-style URLs and is cached like every other
icon; if it cannot be downloaded the card falls back to the small portrait over a blurred, element-coloured background.
"""

from __future__ import annotations

from datetime import datetime, timezone

from PIL import Image, ImageChops, ImageDraw, ImageFilter, ImageOps

from app.character import ARTIFACT_SLOTS, CharacterDetail
from app.regions import mask_uid, server_label
from app.ui_kit import character_tile, draw_star, fit_text, font, load_icon

REPORT_VERSION = "showcase-v1"
W = 1280
M = 40
ART_W, ART_H = 660, 640
RX = 690  # left edge of the right column
RW = W - M - RX
CARD_H = 296

ELEMENT = {
    "Pyro": (255, 122, 84), "Hydro": (70, 160, 255), "Anemo": (110, 230, 190), "Electro": (192, 124, 255),
    "Dendro": (150, 220, 70), "Cryo": (150, 226, 255), "Geo": (255, 205, 90),
}
DEFAULT_ACCENT = (226, 201, 150)
GLASS = (10, 12, 26, 178)
EDGE = (255, 255, 255, 38)
TEXT = (240, 241, 248)
MUTED = (170, 174, 200)


def _fade_mask(w: int, h: int, right: int, bottom: int) -> Image.Image:
    mask = Image.new("L", (w, h), 255)
    ramp = Image.linear_gradient("L")  # black (top) -> white (bottom)
    if right:
        horiz = ramp.rotate(90, expand=True).resize((right, h))  # white (left) -> black? rotate keeps orientation checked below
        horiz = ImageOps.mirror(horiz) if horiz.getpixel((0, 0)) < horiz.getpixel((right - 1, 0)) else horiz
        mask.paste(ImageChops.multiply(mask.crop((w - right, 0, w, h)), horiz), (w - right, 0))
    if bottom:
        vert = ImageOps.flip(ramp.resize((w, bottom)))  # white (top) -> black (bottom)
        mask.paste(ImageChops.multiply(mask.crop((0, h - bottom, w, h)), vert), (0, h - bottom))
    return mask


def _glass(d: ImageDraw.ImageDraw, box: tuple[int, int, int, int], radius: int = 22) -> None:
    d.rounded_rectangle(box, radius=radius, fill=GLASS, outline=EDGE, width=2)


def _background(c: CharacterDetail, splash: Image.Image | None, portrait: Image.Image | None, accent: tuple, h: int) -> Image.Image:
    base = splash or portrait
    if base is not None:
        bg = ImageOps.fit(base.convert("RGB"), (W, h), method=Image.BILINEAR, centering=(0.35, 0.3))
        bg = bg.resize((W // 4, h // 4)).filter(ImageFilter.GaussianBlur(9)).resize((W, h), Image.BILINEAR)
        bg = Image.blend(bg, Image.new("RGB", (W, h), (8, 9, 20)), 0.74)
    else:
        bg = Image.new("RGB", (W, h), (12, 13, 28))
    glow = Image.new("RGB", (W, h), accent)
    ramp = Image.linear_gradient("L").resize((W, h)).point(lambda v: int((255 - v) * 0.20))
    bg.paste(glow, (0, 0), ramp)
    return bg


def render_character_showcase(
    c: CharacterDetail, *, nickname: str, uid: str, server: str, icons: dict[str, bytes], fetched_at: datetime,
    source: str, style: str = "showcase",
) -> bytes:
    accent = ELEMENT.get(c.element, DEFAULT_ACCENT)
    splash = load_icon(icons.get(c.splash_key))
    portrait = load_icon(icons.get(c.icon))
    h = 60 + ART_H + 24 + CARD_H + 150
    img = _background(c, splash, portrait, accent, h)
    d = ImageDraw.Draw(img, "RGBA")

    # --- art
    if splash is not None:
        art = ImageOps.fit(splash, (ART_W, ART_H), method=Image.LANCZOS, centering=(0.5, 0.25))
        art_rgba = art.copy()
        art_rgba.putalpha(_fade_mask(ART_W, ART_H, right=170, bottom=200))
        img.paste(art_rgba, (0, 0), art_rgba)
    elif portrait is not None:
        size = 420
        p = ImageOps.contain(portrait, (size, size), method=Image.LANCZOS)
        img.paste(p, (M + 80, 90), p)

    # --- name block (bottom-left of the art)
    d.rectangle((0, 0, 8, ART_H), fill=accent + (255,))
    for i in range(c.rarity):
        draw_star(d, M + 14 + i * 34, 400, 14, accent)
    name_font = font("serif-bold", 76)
    d.text((M, 424), fit_text(d, c.name or "Unknown", name_font, ART_W - 2 * M), font=name_font, fill=TEXT)
    chip = c.element or "-"
    cw = int(d.textlength(chip, font=font("semibold", 24))) + 36
    d.rounded_rectangle((M, 530, M + cw, 570), radius=20, fill=accent + (255,))
    d.text((M + cw / 2, 550), chip, font=font("semibold", 24), fill=(20, 20, 34), anchor="mm")
    d.text((M + cw + 18, 550), f"Lv. {c.level}   ·   Friendship {c.friendship}", font=font("medium", 26), fill=TEXT, anchor="lm")
    for i in range(6):
        on = i < c.constellation
        cx = M + 16 + i * 44
        d.ellipse((cx - 15, 590, cx + 15, 620), fill=accent + (255,) if on else (255, 255, 255, 30), outline=(255, 255, 255, 80))
        d.text((cx, 605), f"{i + 1}", font=font("bold", 17), fill=(20, 20, 34) if on else MUTED, anchor="mm")
    d.text((M + 6 * 44 + 8, 605), f"C{c.constellation}", font=font("bold", 24), fill=accent, anchor="lm")

    # --- weapon
    y = M
    wh = 168
    _glass(d, (RX, y, RX + RW, y + wh))
    if c.weapon:
        w = c.weapon
        character_tile(img, d, RX + 22, y + 22, 100, rarity=w.rarity, level=None, icon=load_icon(icons.get(w.icon)))
        tx = RX + 22 + 100 + 24
        d.text((tx, y + 26), fit_text(d, w.name, font("semibold", 27), RX + RW - 22 - tx), font=font("semibold", 27), fill=TEXT)
        d.text((tx, y + 68), f"Lv. {w.level}  ·  Refinement {w.refinement}", font=font("regular", 23), fill=MUTED)
        parts = [f"{s.name} {s.value}" for s in (w.main, w.sub) if s]
        d.text((tx, y + 108), fit_text(d, "   ".join(parts), font("medium", 22), RX + RW - 22 - tx), font=font("medium", 22), fill=accent)
    else:
        d.text((RX + 24, y + 70), "No weapon data", font=font("regular", 24), fill=MUTED)
    y += wh + 16

    # --- talents
    th = 112
    _glass(d, (RX, y, RX + RW, y + th))
    shown = c.talents[:3]
    colw = (RW - 44) // 3
    for i, t in enumerate(shown):
        tx = RX + 22 + i * colw
        d.text((tx, y + 18), fit_text(d, t.name, font("regular", 19), colw - 14), font=font("regular", 19), fill=MUTED)
        d.text((tx, y + 70), f"Lv. {t.level}", font=font("bold", 34), fill=TEXT, anchor="lm")
    if not shown:
        d.text((RX + 24, y + 42), "No talent data", font=font("regular", 24), fill=MUTED)
    y += th + 16

    # --- attributes
    sh = ART_H + M - y
    _glass(d, (RX, y, RX + RW, y + sh))
    rows = sh - 24
    per_col = max(1, rows // 40)
    colw = (RW - 44 - 20) // 2
    for i, s in enumerate(c.stats[: per_col * 2]):
        cx = RX + 22 + (i // per_col) * (colw + 20)
        cy = y + 20 + (i % per_col) * 40
        d.text((cx, cy + 20), fit_text(d, s.name, font("regular", 21), colw - int(d.textlength(s.value, font=font("semibold", 23))) - 14), font=font("regular", 21), fill=MUTED, anchor="lm")
        d.text((cx + colw, cy + 20), s.value, font=font("semibold", 23), fill=TEXT, anchor="rm")
        if i % per_col != per_col - 1:
            d.line((cx, cy + 40, cx + colw, cy + 40), fill=(255, 255, 255, 18), width=1)

    # --- artifacts
    ay = ART_H + M + 24
    n = 5
    gap = 16
    aw = (W - 2 * M - (n - 1) * gap) // n
    by_slot = {a.slot: a for a in c.artifacts}
    for i in range(n):
        x = M + i * (aw + gap)
        _glass(d, (x, ay, x + aw, ay + CARD_H))
        a = by_slot.get(i + 1)
        if a is None:
            d.text((x + aw / 2, ay + CARD_H / 2), ARTIFACT_SLOTS.get(i + 1, "-") + "\nempty", font=font("regular", 22), fill=MUTED, anchor="mm", align="center")
            continue
        character_tile(img, d, x + 14, ay + 14, 76, rarity=a.rarity, level=None, icon=load_icon(icons.get(a.icon)))
        d.text((x + aw - 16, ay + 40), f"+{a.level}", font=font("bold", 30), fill=accent, anchor="rm")
        d.text((x + aw - 16, ay + 70), ARTIFACT_SLOTS.get(a.slot, ""), font=font("regular", 18), fill=MUTED, anchor="rm")
        d.text((x + 16, ay + 100), fit_text(d, a.set_name, font("regular", 18), aw - 32), font=font("regular", 18), fill=MUTED)
        if a.main:
            d.text((x + 16, ay + 124), fit_text(d, a.main.name, font("semibold", 20), aw - 32), font=font("semibold", 20), fill=accent)
            d.text((x + 16, ay + 150), a.main.value, font=font("bold", 30), fill=TEXT)
        d.line((x + 16, ay + 194, x + aw - 16, ay + 194), fill=(255, 255, 255, 36), width=1)
        for j, s in enumerate(a.subs[:4]):
            sy = ay + 208 + j * 22
            d.text((x + 16, sy), fit_text(d, s.name, font("regular", 18), aw - 32 - int(d.textlength(s.value, font=font("semibold", 19))) - 8), font=font("regular", 18), fill=MUTED, anchor="lm")
            d.text((x + aw - 16, sy), s.value, font=font("semibold", 19), fill=TEXT, anchor="rm")

    # --- footer
    fy = ay + CARD_H + 22
    if c.sets:
        d.text((M, fy), "Sets: " + ",  ".join(c.sets), font=font("medium", 22), fill=accent)
        fy += 36
    label = {"live": "Live data", "cached": "Cached data", "stale": "Stale data (HoYoLAB unreachable)"}.get(source, "Data")
    stamp = fetched_at.astimezone(timezone.utc).strftime("%Y-%m-%d %H:%M UTC")
    d.text((M, fy), f"{nickname or 'Traveler'}  ·  {server_label(server)}  ·  UID {mask_uid(uid)}  ·  {label}, fetched {stamp}", font=font("regular", 20), fill=MUTED)
    d.text((M, fy + 30), f"Unofficial community tool, not affiliated with HoYoverse  ·  {REPORT_VERSION}", font=font("regular", 18), fill=MUTED)
    out = img.crop((0, 0, W, min(h, fy + 70)))
    import io
    buf = io.BytesIO()
    out.save(buf, format="PNG")
    return buf.getvalue()
