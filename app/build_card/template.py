"""Character Build Card template (1722x717): art + constellations + talents | weapon + stats | five artifact rows.

Pure drawing: takes a BuildModel, an Assets resolver and a theme. Every missing asset has a drawn fallback, so the
card always renders; missing assets are collected in `assets.missing`.
"""

from __future__ import annotations

import io
from datetime import datetime, timezone

from PIL import Image, ImageChops, ImageDraw, ImageFilter

from app.asset_manager import Art, Assets, game_font
from app.build_card import layers
from app.build_card.model import ArtifactRow, BuildModel, build_model
from app.build_card.theme import BuildTheme, theme_for
from app.character import CharacterDetail
from app.regions import mask_uid, server_label

REPORT_VERSION = "build-v1"
W, H = 1722, 717
WHITE = (246, 247, 252)
MUTED = (200, 204, 222)
GREEN = (150, 232, 120)
ROW_X, ROW_W, ROW_H, ROW_GAP, ROW_Y0 = 1186, 524, 123, 18, 16
MID_X, MID_R = 676, 1138


def _txt(d: ImageDraw.ImageDraw, xy: tuple[float, float], s: str, size: int, fill=WHITE, anchor: str = "la", shadow: bool = True) -> None:
    f = game_font(size)
    if shadow:
        d.text((xy[0] + 1.5, xy[1] + 2), s, font=f, fill=(0, 0, 0, 150), anchor=anchor)
    d.text(xy, s, font=f, fill=fill, anchor=anchor)


def _rr(img: Image.Image, box: tuple[int, int, int, int], radius: int, fill) -> None:
    """Translucent rounded rectangle, properly blended (ImageDraw on an RGBA image would overwrite the alpha)."""
    x0, y0, x1, y1 = (int(v) for v in box)
    w, h = x1 - x0 + 1, y1 - y0 + 1
    layer = Image.new("RGBA", (w, h), (0, 0, 0, 0))
    ImageDraw.Draw(layer).rounded_rectangle((0, 0, w - 1, h - 1), radius=radius, fill=fill)
    img.alpha_composite(layer, (x0, y0))


def _ln(img: Image.Image, p0: tuple[int, int], p1: tuple[int, int], fill, width: int = 1) -> None:
    _rr(img, (p0[0], p0[1], p1[0], p1[1] + width - 1), 0, fill)


def _fit(d: ImageDraw.ImageDraw, s: str, size: int, max_w: int) -> int:
    while size > 12 and d.textlength(s, font=game_font(size)) > max_w:
        size -= 1
    return size


def _paste(img: Image.Image, tile: Image.Image | None, xy: tuple[int, int]) -> bool:
    if tile is None:
        return False
    img.alpha_composite(tile, xy)
    return True


def _disc(img: Image.Image, center: tuple[int, int], r: int, fill, ring=None, ring_w: int = 2) -> None:
    k = 3
    layer = Image.new("RGBA", (2 * r * k, 2 * r * k), (0, 0, 0, 0))
    ImageDraw.Draw(layer).ellipse((0, 0, 2 * r * k - 1, 2 * r * k - 1), fill=fill, outline=ring, width=ring_w * k)
    layer = layer.resize((2 * r, 2 * r), Image.LANCZOS)
    img.alpha_composite(layer, (center[0] - r, center[1] - r))


def _heart(img: Image.Image, c: tuple[int, int], r: int, color) -> None:
    """Friendship mark: a drawn heart outline with a smaller heart inside (the game icon has baked-in CJK text)."""
    k = 4
    size = r * 2 * k + 8
    layer = Image.new("RGBA", (size, size), (0, 0, 0, 0))
    d = ImageDraw.Draw(layer)
    for scale, width in ((1.0, 5), (0.55, 4)):
        rr = r * k * scale
        cx, cy = size / 2, size / 2 + rr * 0.08
        d.ellipse((cx - rr, cy - rr * 0.95, cx, cy + rr * 0.05), outline=WHITE, width=width)
        d.ellipse((cx, cy - rr * 0.95, cx + rr, cy + rr * 0.05), outline=WHITE, width=width)
        d.line([(cx - rr * 0.92, cy - rr * 0.35), (cx, cy + rr * 0.95), (cx + rr * 0.92, cy - rr * 0.35)], fill=WHITE, width=width)
    layer = layer.resize((size // k, size // k), Image.LANCZOS)
    img.alpha_composite(layer, (c[0] - layer.width // 2, c[1] - layer.height // 2))


# ---- art ---------------------------------------------------------------------------------------------------------
def _place_art(img: Image.Image, art: Art, theme: BuildTheme) -> None:
    if art.image is None:
        return
    a = art.image
    layer = Image.new("RGBA", (W, H), (0, 0, 0, 0))
    if art.tier == "splash":  # wide 2:1 wish art: scale up and centre the character in the left column
        sc = 0.86
        s = a.resize((int(a.width * sc), int(a.height * sc)), Image.LANCZOS)
        layer.alpha_composite(s, (int(330 - s.width * 0.5), -int((s.height - H) * 0.30))) if s.width else None
    elif art.tier == "full":
        sc = max(660 / a.width, H / a.height)
        s = a.resize((int(a.width * sc), int(a.height * sc)), Image.LANCZOS)
        layer.alpha_composite(s, (int((660 - s.width) / 2), 0))
    else:  # portrait icon: small square art, bottom aligned
        s = a.resize((520, int(520 * a.height / a.width)), Image.LANCZOS)
        layer.alpha_composite(s, (70, H - s.height - 40))
    layer = layers.fade_right(layer, 560, 720)
    glow = Image.new("RGBA", (W, H), theme.glow + (0,))
    glow.putalpha(layer.getchannel("A").filter(ImageFilter.GaussianBlur(16)).point(lambda v: int(v * 0.55)))
    img.alpha_composite(glow)
    shadow = Image.new("RGBA", (W, H), (0, 0, 0, 0))
    shadow.putalpha(layer.getchannel("A").filter(ImageFilter.GaussianBlur(10)).point(lambda v: int(v * 0.5)))
    img.alpha_composite(shadow, (6, 8))
    img.alpha_composite(layer)


# ---- left column -------------------------------------------------------------------------------------------------
def _left(img: Image.Image, m: BuildModel, assets: Assets, theme: BuildTheme, nickname: str, uid: str) -> None:
    d = ImageDraw.Draw(img, "RGBA")
    size = _fit(d, m.name, 44, 400)
    _txt(d, (33, 24), m.name, size, WHITE, "la")
    nx = 33 + int(d.textlength(m.name, font=game_font(size))) + 16
    if nickname:
        d.polygon([(nx, 66), (nx + 8, 66), (nx + 4, 59)], fill=MUTED)
        _txt(d, (nx + 14, 70), nickname[:18], 19, MUTED, "ls")
    _txt(d, (33, 98), f"Lv. {m.level}", 26, WHITE, "lm")
    _heart(img, (50, 141), 15, theme.accent)
    _txt(d, (76, 141), str(m.friendship), 26, WHITE, "lm")

    # constellations: icon in a ring when active, lock when not
    for i in range(6):
        cy = 303 + int(i * 65.8)
        cons = next((c for c in m.cons if c.pos == i + 1), None)
        active = bool(cons and cons.active) if cons else i < m.constellation
        _disc(img, (58, cy), 25, (14, 14, 26, 190), ring=theme.accent + (235,) if active else theme.accent + (120,), ring_w=2)
        icon = assets.icon(cons.icon, 38) if (active and cons and cons.icon) else None
        if active and icon is not None:
            _paste(img, icon, (58 - 19, cy - 19))
        elif active:
            _txt(d, (58, cy), str(i + 1), 24, theme.accent, "mm")
        else:
            lock = assets.ui("lock", 30, tint=(226, 228, 240))
            if not _paste(img, lock, (58 - 15, cy - 15)):
                _txt(d, (58, cy), str(i + 1), 22, MUTED, "mm", shadow=False)

    # talents: three round badges with level
    for i in range(3):
        cx, cy = 578, [413, 517, 620][i]
        t = m.talents[i] if i < len(m.talents) else None
        if t is None:
            continue
        _disc(img, (cx, cy), 32, (12, 12, 24, 170), ring=(255, 255, 255, 120), ring_w=2)
        icon = assets.icon(t.icon, 52) if t.icon else None
        if icon is not None:
            _paste(img, icon, (cx - 26, cy - 26))
        else:
            _txt(d, (cx, cy), ("NA", "Skill", "Burst")[min(2, max(0, (t.kind or i + 1) - 1))], 16, MUTED, "mm")
        _disc(img, (cx, cy + 36), 14, (16, 16, 30, 235), ring=(255, 255, 255, 90), ring_w=1)
        _txt(d, (cx, cy + 36), str(t.level), 18, WHITE, "mm", shadow=False)
    if uid:
        _txt(d, (28, 686), mask_uid(uid), 22, WHITE, "lm")


# ---- middle column -----------------------------------------------------------------------------------------------
def _chip(img: Image.Image, d: ImageDraw.ImageDraw, x: int, y: int, stat_icon: Image.Image | None, value: str) -> int:
    w = int(d.textlength(value, font=game_font(27))) + (46 if stat_icon is not None else 24)
    chip = Image.new("RGBA", (w, 38), (0, 0, 0, 0))
    ImageDraw.Draw(chip).rounded_rectangle((0, 0, w - 1, 37), radius=8, fill=(255, 255, 255, 38))
    img.alpha_composite(chip, (x, y))
    tx = x + 12
    if stat_icon is not None:
        _paste(img, stat_icon, (x + 9, y + 5))
        tx = x + 44
    _txt(d, (tx, y + 19), value, 27, WHITE, "lm")
    return w


def _middle(img: Image.Image, m: BuildModel, assets: Assets, theme: BuildTheme) -> None:
    d = ImageDraw.Draw(img, "RGBA")
    if m.weapon_name:
        icon = assets.icon(m.weapon_icon, 124) if m.weapon_icon else None
        if icon is not None:
            sh = Image.new("RGBA", icon.size, (0, 0, 0, 0))
            sh.putalpha(icon.getchannel("A").filter(ImageFilter.GaussianBlur(6)).point(lambda v: int(v * 0.55)))
            img.alpha_composite(sh, (MID_X + 6, 40))
            img.alpha_composite(icon, (MID_X, 34))
        else:
            layers.glass(img, (MID_X, 40, MID_X + 118, 158), theme, 12, 120)
        stars = assets.stars(m.weapon_rarity)
        if stars is not None:
            _paste(img, stars.resize((int(stars.width * 0.95), int(stars.height * 0.95)), Image.LANCZOS), (MID_X + 4, 154))
        width = MID_R - 826 - 4
        if d.textlength(m.weapon_name, font=game_font(34)) <= width:
            _txt(d, (826, 47), m.weapon_name, 34, WHITE, "lm")
        else:  # two lines, split at the word boundary that balances them
            words = m.weapon_name.split()
            cut = min(range(1, len(words)), key=lambda i: abs(len(" ".join(words[:i])) - len(" ".join(words[i:])))) if len(words) > 1 else 1
            lines = [" ".join(words[:cut]), " ".join(words[cut:])] if len(words) > 1 else [m.weapon_name]
            size = min(_fit(d, ln, 32, width) for ln in lines)
            for k, ln in enumerate(lines):
                _txt(d, (826, 36 + k * 34), ln, size, WHITE, "lm")
        x = 826
        for s in m.weapon_stats[:2]:
            x += _chip(img, d, x, 112, assets.stat_icon(s, 28), s.value) + 10
        y = 158
        r_w = 52
        _rr(img, (826, y, 826 + r_w, y + 34), 7, (0, 0, 0, 120))
        _txt(d, (826 + r_w / 2, y + 17), f"R{m.refinement}", 22, (240, 226, 190), "mm", shadow=False)
        lv = f"Lv. {m.weapon_level}" + (f" / {m.weapon_max_level}" if m.weapon_max_level else "")
        lw = int(d.textlength(lv, font=game_font(23))) + 22
        _rr(img, (826 + r_w + 10, y, 826 + r_w + 10 + lw, y + 34), 7, (0, 0, 0, 120))
        _txt(d, (826 + r_w + 21, y + 17), lv, 23, WHITE, "lm", shadow=False)
    else:
        _txt(d, (MID_X, 90), "No weapon data", 26, MUTED, "lm")

    rows = m.stats[:8]
    step = 51 if len(rows) <= 7 else 46
    for i, r in enumerate(rows):
        cy = 245 + i * step
        _paste(img, assets.stat_icon(r.stat, 30), (MID_X - 2, cy - 15))
        _txt(d, (MID_X + 40, cy), r.label, 25, WHITE, "lm")
        has_sub = bool(r.base and r.bonus)
        _txt(d, (MID_R, cy - (6 if has_sub else 0)), r.value, 27, WHITE, "rm")
        if has_sub:
            bonus = r.bonus if r.bonus.startswith("+") else f"+{r.bonus}"
            bw = int(d.textlength(bonus, font=game_font(14)))
            _txt(d, (MID_R, cy + 17), bonus, 14, GREEN, "rm", shadow=False)
            _txt(d, (MID_R - bw - 6, cy + 17), r.base, 14, MUTED, "rm", shadow=False)

    # artifact sets
    y = 672 if len(m.sets) <= 1 else 660
    layers.glass(img, (MID_X - 4, 644, MID_X + 52, 700), theme, 10, 130)
    set_icon = assets.icon(m.set_icon, 44) if m.set_icon else None
    _paste(img, set_icon, (MID_X + 2, 650))
    if not m.sets:
        _txt(d, (780, 672), "No complete artifact set", 20, MUTED, "lm")
    for j, (name, pieces) in enumerate(m.sets[:2]):
        yy = y + (j * 30 if len(m.sets) > 1 else 0)
        size = _fit(d, name, 22, MID_R - 780 - 52)
        _txt(d, (780, yy), name, size, GREEN, "lm")
        _rr(img, (MID_R - 36, yy - 14, MID_R, yy + 14), 6, (0, 0, 0, 120))
        _txt(d, (MID_R - 18, yy), str(pieces), 20, WHITE, "mm", shadow=False)


# ---- right column ------------------------------------------------------------------------------------------------
def _artifact_row(img: Image.Image, a: ArtifactRow | None, idx: int, assets: Assets, theme: BuildTheme) -> None:
    y = ROW_Y0 + idx * (ROW_H + ROW_GAP)
    layers.glass(img, (ROW_X, y, ROW_X + ROW_W, y + ROW_H), theme, 16, 190)
    d = ImageDraw.Draw(img, "RGBA")
    if a is None:
        _txt(d, (ROW_X + ROW_W / 2, y + ROW_H / 2), "Empty slot", 24, MUTED, "mm")
        return
    icon = assets.icon(a.icon, 132) if a.icon else None
    if icon is not None:
        sh = Image.new("RGBA", icon.size, (0, 0, 0, 0))
        sh.putalpha(icon.getchannel("A").filter(ImageFilter.GaussianBlur(5)).point(lambda v: int(v * 0.6)))
        img.alpha_composite(sh, (ROW_X + 5, y - 2))
        img.alpha_composite(icon, (ROW_X + 2, y - 6))
    else:
        _disc(img, (ROW_X + 68, y + 56), 46, (0, 0, 0, 90), ring=(255, 255, 255, 60))
    d = ImageDraw.Draw(img, "RGBA")
    if a.main:
        mi = assets.stat_icon(a.main, 28)
        _paste(img, mi, (ROW_X + 126, y + 14))
        d.text((ROW_X + 80, y + 66), a.main_value, font=game_font(36), fill=WHITE, anchor="mm", stroke_width=3, stroke_fill=(10, 8, 14, 220))
    stars = assets.stars(a.rarity)
    if stars is not None:
        _paste(img, stars.resize((int(stars.width * 0.72), int(stars.height * 0.72)), Image.LANCZOS), (ROW_X + 14, y + 92))
    _rr(img, (ROW_X + 122, y + 92, ROW_X + 168, y + 114), 6, (0, 0, 0, 150))
    _txt(d, (ROW_X + 145, y + 103), f"+{a.level}", 17, WHITE, "mm", shadow=False)

    _rr(img, (ROW_X + 182, y + 14, ROW_X + 182, y + ROW_H - 14), 0, (255, 255, 255, 40))
    for j, s in enumerate(a.subs[:4]):
        cx = ROW_X + 196 + (j % 2) * 160
        cy = y + 34 + (j // 2) * 54
        _rr(img, (cx - 6, cy - 21, cx + 142, cy + 21), 7, (0, 0, 0, 62))
        _paste(img, assets.stat_icon(s.stat, 28), (cx, cy - 14))
        _txt(d, (cx + 36, cy), s.value, 28, WHITE, "lm")
        _rr(img, (cx, cy + 20, cx + 134, cy + 21), 0, (255, 255, 255, 70))
        if s.ticks:
            for t in range(s.ticks):
                tx = cx + 5 + t * 14
                _rr(img, (tx, cy + 25, tx + 9, cy + 28), 1, theme.accent + (235,))


# ---- entry points ------------------------------------------------------------------------------------------------
def draw_card(m: BuildModel, assets: Assets, art: Art, *, nickname: str, uid: str, theme: BuildTheme,
              fetched_at: datetime | None = None, source: str = "", server: str = "") -> Image.Image:
    img = layers.gradient(W, H, theme.bg_light, theme.bg_dark)
    img.alpha_composite(layers.radial_glow(W, H, (330, 340), 430, theme.glow, 0.42))
    img.alpha_composite(layers.light_rays(W, H, (60, -40), theme.accent))
    img.alpha_composite(layers.dust(W, H, theme.accent))
    _place_art(img, art, theme)
    img.alpha_composite(layers.vignette(W, H, 0.4))
    img.alpha_composite(layers.grain(W, H))
    shade = Image.linear_gradient("L").resize((W, 150)).point(lambda v: int(v * 0.55))
    foot = Image.new("RGBA", (W, 150), (0, 0, 0, 0))
    foot.putalpha(shade)
    img.alpha_composite(foot, (0, H - 150))
    left_shade = Image.linear_gradient("L").transpose(Image.FLIP_TOP_BOTTOM).resize((660, 190)).point(lambda v: int(v * 0.55))
    top = Image.new("RGBA", (660, 190), (0, 0, 0, 0))
    top.putalpha(left_shade)
    img.alpha_composite(top, (0, 0))
    _left(img, m, assets, theme, nickname, uid)
    _middle(img, m, assets, theme)
    for i, a in enumerate(m.artifacts):
        _artifact_row(img, a, i, assets, theme)
    d = ImageDraw.Draw(img, "RGBA")
    if fetched_at is not None:
        label = {"live": "Live data", "cached": "Cached data", "stale": "Stale data"}.get(source, "Data")
        stamp = fetched_at.astimezone(timezone.utc).strftime("%Y-%m-%d %H:%M UTC")
        tail = f"  ·  {server_label(server)}" if server else ""
        _txt(d, (28, 708), f"{label}, fetched {stamp}{tail}  ·  Unofficial community tool  ·  {REPORT_VERSION}", 12, MUTED, "lm", shadow=False)
    return img


def render_character_build(
    c: CharacterDetail, *, nickname: str, uid: str, server: str, icons: dict[str, bytes], fetched_at: datetime,
    source: str, style: str = "build",
) -> bytes:
    assets = Assets(fetched=icons)
    model = build_model(c)
    art = assets.art(c)
    img = draw_card(model, assets, art, nickname=nickname, uid=uid, theme=theme_for(c.element), fetched_at=fetched_at, source=source, server=server)
    buf = io.BytesIO()
    img.convert("RGB").save(buf, format="PNG")
    return buf.getvalue()
