"""Stygian Onslaught card drawn in the style of the official HoYoLAB Battle Chronicle share card.

Everything is drawn from scratch: purple glass panels, a "Best Record" bar, per-challenge team tiles, the boss
artwork HoYoLAB returns with the data, and the Strongest Single Strike / Highest Total Damage Dealt rows.
No HoYoverse logo, QR code or bundled artwork is used.
"""

from __future__ import annotations

import io
import math
from datetime import datetime, timedelta, timezone

from PIL import Image, ImageChops, ImageDraw, ImageFilter, ImageOps

from app.regions import mask_uid
from app.stygian import SChallenge, SChar, StygianData
from app.ui_kit import fit_text, font, load_icon

REPORT_VERSION = "stygian-official-v2"
W = 1080
PAD = 43
INNER = W - 2 * PAD
S = 1.44  # the official share card is 750 px wide; every size below is its measurement times S
TILE_W, TILE_H, TILE_GAP = 104, 134, 17
ROW_H = 81
TEXT = (245, 243, 252)
MUTED = (196, 188, 220)
PANEL = (110, 78, 160, 64)
EDGE = (200, 170, 235, 90)
ROMAN = {1: "I", 2: "II", 3: "III", 4: "IV", 5: "V"}
ELEMENT_COLOR = {
    "Pyro": (255, 122, 84), "Hydro": (70, 160, 255), "Anemo": (110, 230, 190), "Electro": (192, 124, 255),
    "Dendro": (150, 220, 70), "Cryo": (150, 226, 255), "Geo": (255, 205, 90),
}
RARITY_BG = {5: ((236, 176, 98), (190, 126, 58)), 4: ((166, 132, 226), (108, 82, 168))}
LABELS = {1: "Strongest Single Strike", 2: "Highest Total Damage Dealt"}


def _period(start: int, end: int, tz_hours: int) -> str:
    tz = timezone(timedelta(hours=tz_hours))
    f = lambda t: datetime.fromtimestamp(t, tz).strftime("%Y.%m.%d")  # noqa: E731
    return f"Period: {f(start)}-{f(end)}"


def _clock(seconds: int) -> str:
    return f"{seconds}s" if seconds else "-"


def _wrap(d: ImageDraw.ImageDraw, text: str, fnt, width: int, max_lines: int = 2) -> list[str]:
    words, lines, cur = text.split(), [], ""
    for w in words:
        trial = (cur + " " + w).strip()
        if d.textlength(trial, font=fnt) <= width or not cur:
            cur = trial
        else:
            lines.append(cur)
            cur = w
    if cur:
        lines.append(cur)
    if len(lines) > max_lines:
        lines = lines[:max_lines]
        lines[-1] = fit_text(d, lines[-1] + "…", fnt, width)
    return lines or [""]


def _background(h: int) -> Image.Image:
    base = Image.new("RGB", (W, h), (22, 20, 38))
    glow = Image.new("RGB", (W, h), (96, 56, 150))
    ramp = Image.linear_gradient("L").transpose(Image.FLIP_TOP_BOTTOM).resize((W, min(h, 560))).point(lambda v: int(v * 0.55))
    layer = Image.new("L", (W, h), 0)
    layer.paste(ramp, (0, 0))
    base.paste(glow, (0, 0), layer)
    return base


def _star4(d: ImageDraw.ImageDraw, cx: float, cy: float, r: float, fill) -> None:
    pts = []
    for k in range(8):
        rad = r if k % 2 == 0 else r * 0.38
        a = math.radians(-90 + k * 45)
        pts.append((cx + rad * math.cos(a), cy + rad * math.sin(a)))
    d.polygon(pts, fill=fill)


def _badge(img: Image.Image, cx: int, cy: int, size: int, difficulty: int) -> None:
    """A small flower badge with the difficulty as a Roman numeral (drawn, not the official icon)."""
    layer = Image.new("RGBA", (size * 2, size * 2), (0, 0, 0, 0))
    ld = ImageDraw.Draw(layer)
    c = size
    for k in range(6):
        petal = Image.new("RGBA", (size * 2, size * 2), (0, 0, 0, 0))
        pd = ImageDraw.Draw(petal)
        pd.ellipse((c - size * 0.22, c - size * 0.92, c + size * 0.22, c - size * 0.1), fill=(246, 196, 228, 255), outline=(255, 255, 255, 255), width=2)
        layer.alpha_composite(petal.rotate(k * 60, center=(c, c)))
    ld.ellipse((c - size * 0.34, c - size * 0.34, c + size * 0.34, c + size * 0.34), fill=(120, 60, 160, 255), outline=(255, 255, 255, 255), width=2)
    ld.text((c, c), ROMAN.get(difficulty, str(difficulty or "")), font=font("bold", int(size * 0.62)), fill=(255, 255, 255, 255), anchor="mm")
    layer = layer.resize((size, size), Image.LANCZOS)
    img.paste(layer, (cx - size // 2, cy - size // 2), layer)



def _glyph(img: Image.Image, cx: int, cy: int, size: int, element: str) -> None:
    """Small element symbol (drawn, not the official sprite): coloured glyph with a dark rim so it reads on any art."""
    color = ELEMENT_COLOR.get(element)
    if not color:
        return
    k = 4
    n = size * k
    layer = Image.new("RGBA", (n, n), (0, 0, 0, 0))
    ld = ImageDraw.Draw(layer)
    c = n / 2

    def shapes(dr: ImageDraw.ImageDraw, fill, grow: int = 0) -> None:
        r = n * 0.42
        if element == "Cryo":
            for a in range(0, 360, 60):
                ex, ey = c + r * math.cos(math.radians(a)), c + r * math.sin(math.radians(a))
                dr.line((c, c, ex, ey), fill=fill, width=int(n * 0.1) + grow)
                bx, by = c + r * 0.62 * math.cos(math.radians(a)), c + r * 0.62 * math.sin(math.radians(a))
                for da in (-45, 45):
                    dr.line((bx, by, bx + r * 0.3 * math.cos(math.radians(a + da)), by + r * 0.3 * math.sin(math.radians(a + da))), fill=fill, width=int(n * 0.07) + grow)
        elif element == "Hydro":
            dr.ellipse((c - r * 0.62, c - r * 0.1, c + r * 0.62, c + r * 1.0), fill=fill)
            dr.polygon([(c, c - r * 1.05), (c - r * 0.58, c + r * 0.25), (c + r * 0.58, c + r * 0.25)], fill=fill)
        elif element == "Pyro":
            dr.polygon([(c, c - r * 1.05), (c + r * 0.55, c - r * 0.2), (c + r * 0.85, c + r * 0.35), (c + r * 0.4, c + r * 0.95),
                        (c - r * 0.4, c + r * 0.95), (c - r * 0.85, c + r * 0.3), (c - r * 0.45, c - r * 0.1), (c - r * 0.2, c - r * 0.4)], fill=fill)
        elif element == "Electro":
            dr.polygon([(c + r * 0.25, c - r * 1.05), (c - r * 0.65, c + r * 0.12), (c - r * 0.05, c + r * 0.12),
                        (c - r * 0.3, c + r * 1.05), (c + r * 0.65, c - r * 0.2), (c + r * 0.05, c - r * 0.2)], fill=fill)
        elif element == "Anemo":
            for off in (-0.55, 0, 0.55):
                dr.arc((c - r * (1 - abs(off) * 0.3), c + off * r - r * 0.55, c + r * (1 - abs(off) * 0.3), c + off * r + r * 0.55), 200, 20, fill=fill, width=int(n * 0.1) + grow)
        elif element == "Dendro":
            dr.polygon([(c - r * 0.8, c + r * 0.8), (c - r * 0.5, c - r * 0.3), (c + r * 0.2, c - r * 0.95), (c + r * 0.85, c - r * 0.85),
                        (c + r * 0.75, c - r * 0.1), (c, c + r * 0.55)], fill=fill)
        elif element == "Geo":
            dr.polygon([(c, c - r * 1.0), (c + r * 0.8, c), (c, c + r * 1.0), (c - r * 0.8, c)], fill=fill)

    shapes(ld, (20, 16, 34, 235), grow=int(n * 0.06))
    big = Image.new("RGBA", (n, n), (0, 0, 0, 0))
    bd = ImageDraw.Draw(big)
    shapes(bd, color + (255,))
    layer = layer.filter(ImageFilter.MaxFilter(5))
    layer.alpha_composite(big)
    layer = layer.resize((size, size), Image.LANCZOS)
    img.paste(layer, (cx - size // 2, cy - size // 2), layer)


def _tile(img: Image.Image, d: ImageDraw.ImageDraw, x: int, y: int, c: SChar, icon: Image.Image | None, sprite: bytes | None = None) -> None:
    top, bottom = RARITY_BG.get(c.rarity, ((112, 118, 140), (76, 80, 100)))
    ramp = Image.linear_gradient("L").resize((TILE_W, TILE_H))
    tile = Image.composite(Image.new("RGB", (TILE_W, TILE_H), bottom), Image.new("RGB", (TILE_W, TILE_H), top), ramp).convert("RGBA")
    if icon is not None:
        ratio = icon.height / max(1, icon.width)
        if ratio > 1.15:  # tall card art: fill the tile, keep the face
            fitted = ImageOps.fit(icon, (TILE_W, TILE_H), method=Image.LANCZOS, centering=(0.5, 0.25))
        else:  # square portrait: fit by width and sit it at the top
            fitted = ImageOps.fit(icon, (TILE_W, TILE_W), method=Image.LANCZOS, centering=(0.5, 0.3))
            holder = Image.new("RGBA", (TILE_W, TILE_H), (0, 0, 0, 0))
            holder.paste(fitted, (0, 0))
            fitted = holder
        tile.alpha_composite(fitted)
    td = ImageDraw.Draw(tile, "RGBA")
    td.rectangle((0, TILE_H - 31, TILE_W, TILE_H), fill=(239, 230, 211, 238))
    td.text((TILE_W / 2, TILE_H - 15), f"Lv. {c.level}", font=font("medium", 24), fill=(86, 78, 94), anchor="mm")
    if c.constellation > 0:
        td.rounded_rectangle((TILE_W - 30, 5, TILE_W - 5, 29), radius=5, fill=(40, 34, 52, 230))
        td.text((TILE_W - 17.5, 17), str(c.constellation), font=font("semibold", 16), fill=TEXT, anchor="mm")
    mask = Image.new("L", (TILE_W, TILE_H), 0)
    ImageDraw.Draw(mask).rounded_rectangle((0, 0, TILE_W - 1, TILE_H - 1), radius=8, fill=255)
    img.paste(tile.convert("RGB"), (x, y), mask)
    if sprite:
        try:
            ic = Image.open(io.BytesIO(sprite)).convert("RGBA").resize((40, 40), Image.LANCZOS)
            img.paste(ic, (x + 2, y + 2), ic)
            return
        except Exception:
            pass
    _glyph(img, x + 20, y + 20, 36, c.element)


def _circle(img: Image.Image, x: int, y: int, size: int, icon: Image.Image | None, color=(150, 120, 190)) -> None:
    base = Image.new("RGBA", (size, size), color + (255,))
    if icon is not None:
        base.alpha_composite(ImageOps.fit(icon, (size, size), method=Image.LANCZOS, centering=(0.5, 0.3)))
    mask = Image.new("L", (size, size), 0)
    ImageDraw.Draw(mask).ellipse((0, 0, size - 1, size - 1), fill=255)
    img.paste(base.convert("RGB"), (x, y), mask)


def _lines(d: ImageDraw.ImageDraw, ch: SChallenge) -> list[str]:
    return _wrap(d, ch.name or "Challenge", font("semibold", 40), 800)


def _challenge_height(d: ImageDraw.ImageDraw, ch: SChallenge) -> int:
    n = len(_lines(d, ch))
    return round((34 + 36 * n + 12 + 61 + 93 + 20 + 56 * 2 - 4 + 32) * S)


def render_stygian_official(
    data: StygianData, *, nickname: str, icons: dict[str, bytes], multi: bool, tz_hours: int,
    fetched_at: datetime, source: str, uid: str = "", style: str = "official",
) -> bytes:
    mode = data.mode(multi)
    probe = ImageDraw.Draw(Image.new("RGB", (4, 4)))
    heights = [_challenge_height(probe, ch) for ch in mode.challenges]
    top0 = round(376 * S)
    height = top0 + sum(h + round(32 * S) for h in heights) + 150
    img = _background(height)
    d = ImageDraw.Draw(img, "RGBA")

    # --- header (positions measured on the official card, times S)
    d.text((round(32 * S), round(52 * S)), f"UID: {mask_uid(uid)}" if uid else (nickname or "Traveler"), font=font("regular", 32), fill=MUTED, anchor="lm")
    label = "Stygian Onslaught"
    cx0, cy0, ch0 = round(33 * S), round(80 * S), round(42 * S)
    lw = int(d.textlength(label, font=font("semibold", 32))) + round(70 * S) - 20
    d.rounded_rectangle((cx0, cy0, cx0 + lw, cy0 + ch0), radius=10, fill=(255, 255, 255, 26), outline=(255, 255, 255, 64), width=2)
    _star4(d, cx0 + 30, cy0 + ch0 // 2, 11, (255, 255, 255, 255))
    d.text((round(70 * S), cy0 + ch0 // 2), label, font=font("semibold", 32), fill=TEXT, anchor="lm")
    if data.period_start:
        d.text((round(30 * S), round(176 * S)), _period(data.period_start, data.period_end, tz_hours), font=font("regular", 31), fill=MUTED, anchor="lm")
    mid, my = W // 2, round(236 * S)
    title = "Co-op Mode" if multi else "Single-Player Mode"
    tw = int(d.textlength(title, font=font("regular", 37))) // 2
    d.line((round(52 * S), my, mid - tw - 30, my), fill=(255, 255, 255, 50), width=2)
    d.line((mid + tw + 30, my, W - round(52 * S), my), fill=(255, 255, 255, 50), width=2)
    _star4(d, round(52 * S), my, 8, (255, 255, 255, 140))
    _star4(d, W - round(52 * S), my, 8, (255, 255, 255, 140))
    d.text((mid, my), title, font=font("regular", 37), fill=MUTED, anchor="mm")

    # --- best record bar
    by0, bh = round(285 * S), round(58 * S)
    gradient = Image.linear_gradient("L").rotate(90).resize((INNER, bh))
    bar = Image.composite(Image.new("RGBA", (INNER, bh), (110, 68, 168, 255)), Image.new("RGBA", (INNER, bh), (150, 96, 200, 255)), gradient)
    img.paste(bar.convert("RGB"), (PAD, by0))
    d.text((PAD + round(32 * S), by0 + bh // 2), "Best Record", font=font("medium", 40), fill=TEXT, anchor="lm")
    t_right = W - PAD - round(32 * S)
    d.text((t_right, by0 + bh // 2), _clock(mode.best_seconds), font=font("bold", 46), fill=TEXT, anchor="rm")
    if mode.best_difficulty:
        _badge(img, t_right - int(d.textlength(_clock(mode.best_seconds), font=font("bold", 46))) - 56, by0 + bh // 2, 92, mode.best_difficulty)
    y = top0

    # --- challenges
    for ch, h in zip(mode.challenges, heights):
        d.rounded_rectangle((PAD, y, W - PAD, y + h), radius=10, fill=PANEL, outline=EDGE, width=2)
        lines = _lines(d, ch)
        for i, line in enumerate(lines):
            d.text((round(62 * S), y + round((52 + 36 * i) * S)), line, font=font("semibold", 40), fill=TEXT, anchor="lm")
        bar_top = y + round((34 + 36 * len(lines) + 12) * S)
        tiles_top = bar_top + round(61 * S)
        tiles_bottom = tiles_top + TILE_H
        # boss artwork, dark-red glow and level pill on the right
        bcx, bcy = round(552 * S), bar_top + round(44 * S)
        boss = load_icon(icons.get(ch.enemy_icon)) if ch.enemy_icon else None
        if boss is not None or ch.enemy_level:
            glow = Image.new("RGBA", (420, 420), (0, 0, 0, 0))
            ImageDraw.Draw(glow).ellipse((50, 70, 370, 380), fill=(150, 30, 70, 165))
            glow = glow.filter(ImageFilter.GaussianBlur(34))
            img.paste(glow, (bcx - 210, bcy - 190), glow)
        if boss is not None:
            fitted = ImageOps.contain(boss, (round(150 * S), round(205 * S)), method=Image.LANCZOS)
            img.paste(fitted, (bcx - fitted.width // 2, bcy - fitted.height // 2 - 6), fitted)
        if ch.enemy_level:
            txt = f"Lv. {ch.enemy_level}"
            pw = int(d.textlength(txt, font=font("medium", 26))) + 44
            py = tiles_bottom - round(18 * S)
            d.rounded_rectangle((bcx - pw // 2, py - 20, bcx + pw // 2, py + 20), radius=20, fill=(24, 18, 34, 225))
            d.text((bcx, py), txt, font=font("medium", 26), fill=TEXT, anchor="mm")
        # time bar
        bw = round(332 * S)
        d.rounded_rectangle((round(57 * S), bar_top, round(57 * S) + bw, bar_top + round(40 * S)), radius=6, fill=(255, 255, 255, 32))
        d.text((round(69 * S), bar_top + round(20 * S)), "Time Elapsed", font=font("medium", 29), fill=TEXT, anchor="lm")
        d.text((round(57 * S) + bw - 18, bar_top + round(20 * S)), _clock(ch.seconds), font=font("bold", 32), fill=TEXT, anchor="rm")
        # team
        for i, c in enumerate(ch.team[:4]):
            _tile(img, d, round(62 * S) + i * (TILE_W + TILE_GAP), tiles_top, c, load_icon(icons.get(c.icon)), icons.get(f"el:{c.element}"))
        # best rows
        ry = tiles_bottom + round(20 * S)
        rh = round(52 * S)
        for b in sorted(ch.best, key=lambda b: b.kind or 9)[:2]:
            d.rounded_rectangle((round(62 * S), ry, W - round(62 * S) + 2, ry + rh), radius=6, fill=(255, 255, 255, 30))
            _circle(img, round(78 * S), ry + (rh - 56) // 2, 56, load_icon(icons.get(b.icon)))
            d.text((round(124 * S), ry + rh // 2), LABELS.get(b.kind, "Best"), font=font("semibold", 29), fill=TEXT, anchor="lm")
            d.text((W - round(76 * S), ry + rh // 2), b.value or "-", font=font("bold", 34), fill=TEXT, anchor="rm")
            ry += round(56 * S)
        y += h + round(32 * S)

    stamp = fetched_at.astimezone(timezone.utc).strftime("%Y-%m-%d %H:%M UTC")
    note = {"live": "Live data", "cached": "Cached data", "stale": "Stale data (HoYoLAB unreachable)"}.get(source, "Data")
    d.text((PAD + 4, y + 10), f"{nickname or 'Traveler'}  ·  {note}, fetched {stamp}", font=font("medium", 22), fill=MUTED)
    d.text((PAD + 4, y + 48), f"Unofficial community tool, not affiliated with HoYoverse  ·  {REPORT_VERSION}", font=font("regular", 19), fill=(150, 142, 178))
    buf = io.BytesIO()
    img.crop((0, 0, W, y + 90)).save(buf, format="PNG")
    return buf.getvalue()
