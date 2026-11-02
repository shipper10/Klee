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

REPORT_VERSION = "showcase-v2"
W, H = 1600, 760
M = 20
ART_W = 600
MX, MW = 600, 430  # middle column
AX, AW = 1050, W - M - 1050  # artifact column
ROW_H, ROW_GAP = 138, 8

ELEMENT = {
    "Pyro": (255, 122, 84), "Hydro": (70, 160, 255), "Anemo": (110, 230, 190), "Electro": (192, 124, 255),
    "Dendro": (150, 220, 70), "Cryo": (150, 226, 255), "Geo": (255, 205, 90),
}
DEFAULT_ACCENT = (226, 201, 150)
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


def _glass(d: ImageDraw.ImageDraw, box: tuple[int, int, int, int], accent: tuple, radius: int = 20) -> None:
    """Element-tinted dark glass: the accent colour mixed deep into the background."""
    tint = tuple(round(a * 0.22 + 10 * 0.78) for a in accent)
    d.rounded_rectangle(box, radius=radius, fill=(*tint, 196), outline=(*accent, 70), width=2)


ABBR = {"Energy Recharge": "ER", "Elemental Mastery": "EM"}


def _background(splash: Image.Image | None, portrait: Image.Image | None, accent: tuple, h: int) -> Image.Image:
    base = splash or portrait
    if base is not None:
        bg = ImageOps.fit(base.convert("RGB"), (W, h), method=Image.BILINEAR, centering=(0.2, 0.3))
        bg = bg.resize((W // 4, h // 4)).filter(ImageFilter.GaussianBlur(9)).resize((W, h), Image.BILINEAR)
        bg = Image.blend(bg, Image.new("RGB", (W, h), (8, 9, 20)), 0.66)
    else:
        bg = Image.new("RGB", (W, h), (12, 13, 28))
    glow = Image.new("RGB", (W, h), accent)
    ramp = Image.linear_gradient("L").resize((W, h)).point(lambda v: int((255 - v) * 0.34))
    bg.paste(glow, (0, 0), ramp)
    return bg


def render_character_showcase(
    c: CharacterDetail, *, nickname: str, uid: str, server: str, icons: dict[str, bytes], fetched_at: datetime,
    source: str, style: str = "showcase",
) -> bytes:
    accent = ELEMENT.get(c.element, DEFAULT_ACCENT)
    splash = load_icon(icons.get(c.splash_key))
    portrait = load_icon(icons.get(c.icon))
    img = _background(splash, portrait, accent, H)
    d = ImageDraw.Draw(img, "RGBA")

    # --- art (full height, fading into the middle column)
    if splash is not None:
        art = ImageOps.fit(splash, (ART_W + 60, H), method=Image.LANCZOS, centering=(0.5, 0.3))
        rgba = art.copy()
        rgba.putalpha(_fade_mask(ART_W + 60, H, right=200, bottom=120))
        img.paste(rgba, (0, 0), rgba)
    elif portrait is not None:
        p = ImageOps.contain(portrait, (420, 420), method=Image.LANCZOS)
        img.paste(p, (100, 170), p)

    # legibility: darken behind the name (top) and the footer (bottom)
    shade = Image.new("RGBA", (ART_W, H), (0, 0, 0, 0))
    top = Image.linear_gradient("L").transpose(Image.FLIP_TOP_BOTTOM).resize((ART_W, 280)).point(lambda v: int(v * 0.62))
    bottom = Image.linear_gradient("L").resize((ART_W, 140)).point(lambda v: int(v * 0.70))
    shade.paste((0, 0, 0, 255), (0, 0), top)
    shade.paste((0, 0, 0, 255), (0, H - 140), bottom)
    img.paste(shade, (0, 0), shade)
    d = ImageDraw.Draw(img, "RGBA")

    # --- name block (top-left)
    for i in range(c.rarity):
        draw_star(d, 44 + i * 32, 40, 13, accent)
    name_font = font("serif-bold", 64)
    d.text((M + 14, 62), fit_text(d, c.name or "Unknown", name_font, ART_W - 60), font=name_font, fill=TEXT)
    chip = c.element or "-"
    cw = int(d.textlength(chip, font=font("semibold", 22))) + 32
    d.rounded_rectangle((M + 14, 148, M + 14 + cw, 184), radius=18, fill=accent + (255,))
    d.text((M + 14 + cw / 2, 166), chip, font=font("semibold", 22), fill=(20, 20, 34), anchor="mm")
    d.text((M + 14 + cw + 16, 166), f"Lv. {c.level}   ·   Friendship {c.friendship}", font=font("medium", 24), fill=TEXT, anchor="lm")
    # constellations: a column of circles like the Enka layout
    for i in range(6):
        on = i < c.constellation
        cy = 250 + i * 58
        d.ellipse((M + 14, cy - 22, M + 14 + 44, cy + 22), fill=accent + (255,) if on else (10, 12, 26, 170), outline=accent + (200,), width=2)
        d.text((M + 14 + 22, cy), f"{i + 1}" if on else "🔒"[:0] + f"{i + 1}", font=font("bold", 20), fill=(20, 20, 34) if on else MUTED, anchor="mm")
    # footer over the art
    label = {"live": "Live data", "cached": "Cached data", "stale": "Stale data"}.get(source, "Data")
    stamp = fetched_at.astimezone(timezone.utc).strftime("%Y-%m-%d %H:%M UTC")
    d.text((M + 14, H - 78), f"{nickname or 'Traveler'}  ·  {server_label(server)}  ·  UID {mask_uid(uid)}", font=font("medium", 20), fill=TEXT)
    d.text((M + 14, H - 52), f"{label}, fetched {stamp}", font=font("regular", 18), fill=MUTED)
    d.text((M + 14, H - 28), f"Unofficial community tool, not affiliated with HoYoverse  ·  {REPORT_VERSION}", font=font("regular", 16), fill=MUTED)

    # --- middle: weapon, talents, attributes
    y = M
    wh = 168
    _glass(d, (MX, y, MX + MW, y + wh), accent)
    if c.weapon:
        w = c.weapon
        character_tile(img, d, MX + 20, y + 20, 108, rarity=w.rarity, level=None, icon=load_icon(icons.get(w.icon)))
        tx = MX + 20 + 108 + 20
        d.text((tx, y + 24), fit_text(d, w.name, font("semibold", 22), MX + MW - 18 - tx), font=font("semibold", 22), fill=TEXT)
        d.text((tx, y + 62), f"Lv. {w.level}   ·   R{w.refinement}", font=font("medium", 22), fill=MUTED)
        bx = tx
        for st in [x for x in (w.main, w.sub) if x]:
            text = f"{ABBR.get(st.name, st.name)} {st.value}"
            bw = int(d.textlength(text, font=font("semibold", 18))) + 18
            d.rounded_rectangle((bx, y + 104, bx + bw, y + 142), radius=10, fill=(255, 255, 255, 26))
            d.text((bx + bw / 2, y + 123), text, font=font("semibold", 18), fill=accent, anchor="mm")
            bx += bw + 6
    else:
        d.text((MX + 24, y + 70), "No weapon data", font=font("regular", 24), fill=MUTED)
    y += wh + 12

    th = 96
    _glass(d, (MX, y, MX + MW, y + th), accent)
    shown = c.talents[:3]
    colw = (MW - 36) // 3
    for i, t in enumerate(shown):
        tx = MX + 18 + i * colw
        d.text((tx, y + 18), fit_text(d, t.name, font("regular", 18), colw - 12), font=font("regular", 18), fill=MUTED)
        d.text((tx, y + 62), f"Lv. {t.level}", font=font("bold", 30), fill=TEXT, anchor="lm")
    if not shown:
        d.text((MX + 20, y + 34), "No talent data", font=font("regular", 22), fill=MUTED)
    y += th + 12

    sh = H - M - y
    _glass(d, (MX, y, MX + MW, y + sh), accent)
    per = max(1, (sh - 20) // 44)
    for i, st in enumerate(c.stats[:per]):
        cy = y + 14 + i * 44 + 22
        d.text((MX + 22, cy), fit_text(d, st.name, font("medium", 23), MW - 44 - int(d.textlength(st.value, font=font("bold", 26))) - 14), font=font("medium", 23), fill=TEXT, anchor="lm")
        d.text((MX + MW - 22, cy), st.value, font=font("bold", 26), fill=TEXT, anchor="rm")
        if i < min(per, len(c.stats)) - 1:
            d.line((MX + 22, cy + 22, MX + MW - 22, cy + 22), fill=(255, 255, 255, 22), width=1)

    # --- artifacts: five rows
    by_slot = {a.slot: a for a in c.artifacts}
    for i in range(5):
        ay = M + i * (ROW_H + ROW_GAP)
        _glass(d, (AX, ay, AX + AW, ay + ROW_H), accent)
        a = by_slot.get(i + 1)
        if a is None:
            d.text((AX + AW / 2, ay + ROW_H / 2), f"{ARTIFACT_SLOTS.get(i + 1, '-')}  ·  empty", font=font("regular", 22), fill=MUTED, anchor="mm")
            continue
        character_tile(img, d, AX + 16, ay + 16, 106, rarity=a.rarity, level=None, icon=load_icon(icons.get(a.icon)))
        d.rounded_rectangle((AX + 16, ay + 16, AX + 16 + 62, ay + 16 + 28), radius=8, fill=(10, 12, 26, 220))
        d.text((AX + 16 + 31, ay + 16 + 14), f"+{a.level}", font=font("bold", 19), fill=accent, anchor="mm")
        mx = AX + 16 + 106 + 16
        d.text((mx, ay + 18), ARTIFACT_SLOTS.get(a.slot, ""), font=font("regular", 17), fill=MUTED)
        if a.main:
            d.text((mx, ay + 42), fit_text(d, ABBR.get(a.main.name, a.main.name), font("semibold", 20), 150), font=font("semibold", 20), fill=accent)
            d.text((mx, ay + 82), a.main.value, font=font("bold", 36), fill=TEXT, anchor="lm")
        d.text((mx, ay + 116), fit_text(d, a.set_name, font("regular", 16), 150), font=font("regular", 16), fill=MUTED)
        sx0 = mx + 166
        sw = (AX + AW - 16 - sx0) // 2
        for j, st in enumerate(a.subs[:4]):
            sx = sx0 + (j % 2) * sw
            sy = ay + 22 + (j // 2) * 58
            name = ABBR.get(st.name, st.name)
            d.text((sx, sy), fit_text(d, name, font("regular", 18), sw - 10), font=font("regular", 18), fill=MUTED)
            d.text((sx, sy + 24), st.value, font=font("semibold", 26), fill=TEXT)
        if c.sets and i == 4:
            pass

    out = img
    import io
    buf = io.BytesIO()
    out.save(buf, format="PNG")
    return buf.getvalue()
