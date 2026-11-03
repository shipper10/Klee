"""Procedural background and surface layers (no external assets, deterministic per size).

Layers, bottom to top: gradient -> glow -> light rays -> dust -> (art is composited by the template) -> glass panels -> vignette+grain.
"""

from __future__ import annotations

import math
import random

from PIL import Image, ImageChops, ImageDraw, ImageFilter

from app.build_card.theme import BuildTheme


def gradient(w: int, h: int, light, dark) -> Image.Image:
    """Diagonal gradient from top-left (light) to bottom-right (dark)."""
    ramp = Image.linear_gradient("L").rotate(45, expand=True).resize((w, h), Image.BILINEAR)
    return Image.composite(Image.new("RGB", (w, h), dark), Image.new("RGB", (w, h), light), ramp).convert("RGBA")


def radial_glow(w: int, h: int, center: tuple[int, int], radius: int, color, strength: float) -> Image.Image:
    layer = Image.new("RGBA", (w, h), color + (0,))
    mask = Image.new("L", (w, h), 0)
    ImageDraw.Draw(mask).ellipse((center[0] - radius, center[1] - radius, center[0] + radius, center[1] + radius), fill=int(255 * strength))
    mask = mask.filter(ImageFilter.GaussianBlur(radius // 2))
    layer.putalpha(mask)
    return layer


def light_rays(w: int, h: int, origin: tuple[int, int], color, seed: int = 7) -> Image.Image:
    rnd = random.Random(seed)
    layer = Image.new("RGBA", (w, h), (0, 0, 0, 0))
    d = ImageDraw.Draw(layer)
    reach = int(math.hypot(w, h))
    for _ in range(9):
        angle = math.radians(rnd.uniform(5, 80))
        spread = math.radians(rnd.uniform(1.5, 5))
        a1, a2 = angle - spread, angle + spread
        d.polygon(
            [origin, (origin[0] + reach * math.cos(a1), origin[1] + reach * math.sin(a1)),
             (origin[0] + reach * math.cos(a2), origin[1] + reach * math.sin(a2))],
            fill=color + (rnd.randint(14, 34),),
        )
    return layer.filter(ImageFilter.GaussianBlur(10))


def dust(w: int, h: int, color, count: int = 90, seed: int = 11) -> Image.Image:
    rnd = random.Random(seed)
    layer = Image.new("RGBA", (w, h), (0, 0, 0, 0))
    d = ImageDraw.Draw(layer)
    for _ in range(count):
        x, y, r = rnd.randint(0, w), rnd.randint(0, h), rnd.choice((1, 1, 1, 2, 2, 3))
        d.ellipse((x - r, y - r, x + r, y + r), fill=color + (rnd.randint(50, 160),))
    return layer.filter(ImageFilter.GaussianBlur(0.7))


def vignette(w: int, h: int, strength: float = 0.55) -> Image.Image:
    mask = Image.radial_gradient("L").resize((w, h), Image.BILINEAR)  # 0 at centre -> 255 at corners
    mask = mask.point(lambda v: int(max(0, v - 90) * strength * 1.6))
    layer = Image.new("RGBA", (w, h), (0, 0, 0, 0))
    layer.putalpha(mask)
    return layer


def grain(w: int, h: int, amount: int = 10, seed: int = 3) -> Image.Image:
    noise = Image.effect_noise((w, h), 64).point(lambda v: 128 + (v - 128) * amount // 64)
    layer = Image.new("RGBA", (w, h), (255, 255, 255, 0))
    layer.putalpha(noise.point(lambda v: abs(v - 128) // 2))
    return layer


def rounded_mask(size: tuple[int, int], radius: int) -> Image.Image:
    k = 3
    m = Image.new("L", (size[0] * k, size[1] * k), 0)
    ImageDraw.Draw(m).rounded_rectangle((0, 0, size[0] * k - 1, size[1] * k - 1), radius=radius * k, fill=255)
    return m.resize(size, Image.LANCZOS)


def glass(img: Image.Image, box: tuple[int, int, int, int], theme: BuildTheme, radius: int = 14, opacity: int = 150) -> None:
    """Translucent dark panel with a tinted fill, soft shadow, top highlight and a thin rim."""
    x0, y0, x1, y1 = box
    w, h = x1 - x0, y1 - y0
    shadow = Image.new("RGBA", (w + 40, h + 40), (0, 0, 0, 0))
    ImageDraw.Draw(shadow).rounded_rectangle((20, 24, 20 + w, 24 + h), radius=radius, fill=(0, 0, 0, 110))
    img.alpha_composite(shadow.filter(ImageFilter.GaussianBlur(9)), (x0 - 20, y0 - 20))
    panel = Image.new("RGBA", (w, h), (0, 0, 0, 0))
    body = Image.new("RGBA", (w, h), theme.panel_tint + (opacity,))
    top = Image.linear_gradient("L").transpose(Image.FLIP_TOP_BOTTOM).resize((w, h)).point(lambda v: int(v * 0.16))
    body.paste((255, 255, 255, 255), (0, 0), top)
    panel.alpha_composite(Image.composite(body, panel, rounded_mask((w, h), radius)))
    rim = Image.new("RGBA", (w, h), (0, 0, 0, 0))
    ImageDraw.Draw(rim).rounded_rectangle((0, 0, w - 1, h - 1), radius=radius, outline=(255, 255, 255, 38), width=1)
    panel.alpha_composite(rim)
    img.alpha_composite(panel, (x0, y0))


def fade_right(img: Image.Image, start: int, end: int) -> Image.Image:
    """Multiply alpha by a horizontal ramp that is 1 before `start` and 0 after `end`."""
    w, h = img.size
    ramp = Image.linear_gradient("L").rotate(90, expand=True).transpose(Image.FLIP_LEFT_RIGHT).resize((max(1, end - start), h))
    mask = Image.new("L", (w, h), 255)
    mask.paste(0, (end, 0, w, h))
    mask.paste(ramp, (start, 0))
    out = img.copy()
    out.putalpha(ImageChops.multiply(out.getchannel("A"), mask))
    return out
