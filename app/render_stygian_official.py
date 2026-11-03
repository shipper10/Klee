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

REPORT_VERSION = "stygian-official-v1"
W = 1080
PAD = 42
INNER = W - 2 * PAD
TILE_W, TILE_H, TILE_GAP = 104, 134, 12
ROW_H = 58
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


def _tile(img: Image.Image, d: ImageDraw.ImageDraw, x: int, y: int, c: SChar, icon: Image.Image | None) -> None:
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
    td.rectangle((0, TILE_H - 30, TILE_W, TILE_H), fill=(239, 230, 211, 235))
    td.text((TILE_W / 2, TILE_H - 15), f"Lv. {c.level}", font=font("medium", 20), fill=(70, 62, 78), anchor="mm")
    col = ELEMENT_COLOR.get(c.element)
    if col:
        td.ellipse((5, 5, 25, 25), fill=(20, 18, 34, 200), outline=col + (255,), width=2)
        td.ellipse((11, 11, 19, 19), fill=col + (255,))
    if c.constellation > 0:
        td.rounded_rectangle((TILE_W - 28, 5, TILE_W - 5, 27), radius=6, fill=(20, 18, 34, 215))
        td.text((TILE_W - 16.5, 16), str(c.constellation), font=font("semibold", 15), fill=TEXT, anchor="mm")
    mask = Image.new("L", (TILE_W, TILE_H), 0)
    ImageDraw.Draw(mask).rounded_rectangle((0, 0, TILE_W - 1, TILE_H - 1), radius=9, fill=255)
    img.paste(tile.convert("RGB"), (x, y), mask)


def _circle(img: Image.Image, x: int, y: int, size: int, icon: Image.Image | None, color=(150, 120, 190)) -> None:
    base = Image.new("RGBA", (size, size), color + (255,))
    if icon is not None:
        base.alpha_composite(ImageOps.fit(icon, (size, size), method=Image.LANCZOS, centering=(0.5, 0.3)))
    mask = Image.new("L", (size, size), 0)
    ImageDraw.Draw(mask).ellipse((0, 0, size - 1, size - 1), fill=255)
    img.paste(base.convert("RGB"), (x, y), mask)


def _challenge_height(d: ImageDraw.ImageDraw, ch: SChallenge) -> int:
    lines = len(_wrap(d, ch.name or "Challenge", font("semibold", 32), INNER - 60))
    return 24 + lines * 44 + 14 + 52 + 20 + TILE_H + 20 + 2 * ROW_H + 8 + 26


def render_stygian_official(
    data: StygianData, *, nickname: str, icons: dict[str, bytes], multi: bool, tz_hours: int,
    fetched_at: datetime, source: str, uid: str = "", style: str = "official",
) -> bytes:
    mode = data.mode(multi)
    probe = ImageDraw.Draw(Image.new("RGB", (4, 4)))
    heights = [_challenge_height(probe, ch) for ch in mode.challenges]
    height = 372 + sum(h + 30 for h in heights) + 150
    img = _background(height)
    d = ImageDraw.Draw(img, "RGBA")

    # --- header
    d.text((PAD + 4, 36), f"UID: {mask_uid(uid)}" if uid else (nickname or "Traveler"), font=font("regular", 26), fill=MUTED)
    label = "Stygian Onslaught"
    lw = int(d.textlength(label, font=font("semibold", 28))) + 78
    d.rounded_rectangle((PAD, 78, PAD + lw, 134), radius=14, fill=(255, 255, 255, 26), outline=(255, 255, 255, 60), width=2)
    _star4(d, PAD + 30, 106, 11, (255, 255, 255, 255))
    d.text((PAD + 56, 106), label, font=font("semibold", 28), fill=TEXT, anchor="lm")
    if data.period_start:
        d.text((PAD + 4, 176), _period(data.period_start, data.period_end, tz_hours), font=font("regular", 25), fill=MUTED, anchor="lm")
    mid = W // 2
    title = "Co-op Mode" if multi else "Single-Player Mode"
    tw = int(d.textlength(title, font=font("regular", 30))) // 2
    d.line((PAD + 40, 238, mid - tw - 40, 238), fill=(255, 255, 255, 50), width=2)
    d.line((mid + tw + 40, 238, W - PAD - 40, 238), fill=(255, 255, 255, 50), width=2)
    _star4(d, PAD + 30, 238, 8, (255, 255, 255, 120))
    _star4(d, W - PAD - 30, 238, 8, (255, 255, 255, 120))
    d.text((mid, 238), title, font=font("regular", 30), fill=MUTED, anchor="mm")

    # --- best record bar
    bar = Image.new("RGBA", (INNER, 68), (0, 0, 0, 0))
    gradient = Image.linear_gradient("L").rotate(90).resize((INNER, 68))
    left, right = Image.new("RGBA", (INNER, 68), (112, 70, 168, 255)), Image.new("RGBA", (INNER, 68), (150, 96, 200, 255))
    bar = Image.composite(left, right, gradient)
    img.paste(bar.convert("RGB"), (PAD, 290))
    d.text((PAD + 30, 324), "Best Record", font=font("medium", 30), fill=TEXT, anchor="lm")
    d.text((W - PAD - 28, 324), _clock(mode.best_seconds), font=font("bold", 34), fill=TEXT, anchor="rm")
    if mode.best_difficulty:
        _badge(img, W - PAD - 28 - int(d.textlength(_clock(mode.best_seconds), font=font("bold", 34))) - 44, 324, 60, mode.best_difficulty)
    y = 372

    # --- challenges
    for ch, h in zip(mode.challenges, heights):
        d.rounded_rectangle((PAD, y, W - PAD, y + h), radius=14, fill=PANEL, outline=EDGE, width=2)
        ty = y + 24
        lines = _wrap(d, ch.name or "Challenge", font("semibold", 32), INNER - 60)
        for line in lines:
            d.text((PAD + 30, ty), line, font=font("semibold", 32), fill=TEXT)
            ty += 44
        ty += 14
        # boss artwork with a dark glow and level pill, right side
        region_top, region_h = ty, 52 + 20 + TILE_H
        boss = load_icon(icons.get(ch.enemy_icon)) if ch.enemy_icon else None
        bx = W - PAD - 200
        by = region_top + region_h // 2
        if boss is not None or ch.enemy_level:
            glow = Image.new("RGBA", (360, 360), (0, 0, 0, 0))
            ImageDraw.Draw(glow).ellipse((40, 60, 320, 330), fill=(150, 30, 70, 150))
            glow = glow.filter(ImageFilter.GaussianBlur(30))
            img.paste(glow, (bx - 180, by - 170), glow)
        if boss is not None:
            fitted = ImageOps.contain(boss, (250, 250), method=Image.LANCZOS)
            img.paste(fitted, (bx - fitted.width // 2, by - fitted.height // 2 - 8), fitted)
        if ch.enemy_level:
            txt = f"Lv. {ch.enemy_level}"
            pw = int(d.textlength(txt, font=font("medium", 24))) + 40
            d.rounded_rectangle((bx - pw // 2, by + 62, bx + pw // 2, by + 100), radius=19, fill=(20, 16, 30, 215))
            d.text((bx, by + 81), txt, font=font("medium", 24), fill=TEXT, anchor="mm")
        # time bar
        d.rounded_rectangle((PAD + 30, ty, PAD + 30 + 470, ty + 52), radius=8, fill=(255, 255, 255, 30))
        d.text((PAD + 46, ty + 26), "Time Elapsed", font=font("medium", 24), fill=TEXT, anchor="lm")
        d.text((PAD + 30 + 454, ty + 26), _clock(ch.seconds), font=font("bold", 26), fill=TEXT, anchor="rm")
        # team
        tx0, tty = PAD + 30, ty + 52 + 20
        for i, c in enumerate(ch.team[:4]):
            _tile(img, d, tx0 + i * (TILE_W + TILE_GAP), tty, c, load_icon(icons.get(c.icon)))
        # best rows
        ry = tty + TILE_H + 20
        best = sorted(ch.best, key=lambda b: b.kind or 9)[:2]
        for b in best:
            d.rounded_rectangle((PAD + 24, ry, W - PAD - 24, ry + ROW_H - 4), radius=8, fill=(255, 255, 255, 28))
            _circle(img, PAD + 36, ry + 3, ROW_H - 10, load_icon(icons.get(b.icon)))
            d.text((PAD + 36 + ROW_H, ry + (ROW_H - 4) // 2), LABELS.get(b.kind, "Best"), font=font("semibold", 26), fill=TEXT, anchor="lm")
            d.text((W - PAD - 42, ry + (ROW_H - 4) // 2), b.value or "-", font=font("bold", 30), fill=TEXT, anchor="rm")
            ry += ROW_H
        y += h + 30

    stamp = fetched_at.astimezone(timezone.utc).strftime("%Y-%m-%d %H:%M UTC")
    note = {"live": "Live data", "cached": "Cached data", "stale": "Stale data (HoYoLAB unreachable)"}.get(source, "Data")
    d.text((PAD + 4, y + 10), f"{nickname or 'Traveler'}  ·  {note}, fetched {stamp}", font=font("medium", 22), fill=MUTED)
    d.text((PAD + 4, y + 48), f"Unofficial community tool, not affiliated with HoYoverse  ·  {REPORT_VERSION}", font=font("regular", 19), fill=(150, 142, 178))
    buf = io.BytesIO()
    img.crop((0, 0, W, y + 90)).save(buf, format="PNG")
    return buf.getvalue()
