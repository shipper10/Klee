"""Asset Manager: one place that resolves logical asset keys to validated images, with fallbacks.

Renderers never know where an image came from. They ask for ("element", "Pyro"), ("stat", <Stat>), ("art", <character>)
and get a PIL image or None; None means "draw the fallback". Every miss is recorded in `Assets.missing` so it can be
reported (owner diagnostics) instead of failing silently.

Two kinds of sources:
* bundled  - files under app/assets (fonts, element/stat icons, UI bits); always available;
* fetched  - bytes downloaded by ImageFetcher (character art, weapon/artifact/talent icons); validated here before use.
"""

from __future__ import annotations

import io
import re
from dataclasses import dataclass, field
from functools import lru_cache
from pathlib import Path
from typing import Any

from PIL import Image, ImageFont

from app.character import CharacterDetail, Stat, splash_for
from app.constants import ELEMENTS
from app.stats import stat_key  # noqa: F401  (re-exported)

ROOT = Path(__file__).parent / "assets"

# Provenance of every source (used for README credits and owner diagnostics).
SOURCES = {
    "font": "yuanshen.ttf (in-game font) via GenshinUID, GPL-3.0",
    "element": "helingping/gsgametextures UI_Icon_Element_*",
    "stat": "GenshinUID enka texture2D icons",
    "ui": "GenshinUID textures (lock, friendship hearts, star rows)",
    "art:full": "HoYoLAB character `image` URL (validated)",
    "art:splash": "enka.network / gi.yatta.moe UI_Gacha_AvatarImg_<Name>",
    "art:icon": "HoYoLAB / enka character portrait",
    "icon": "HoYoLAB CDN (weapon, artifact, talent, constellation)",
}

# Order the art tiers are tried; each tier is validated, the first valid one wins.
ART_ORDER = ("full", "splash", "icon")
ART_RULES = {  # tier: (min width, min height, min aspect h/w, max aspect h/w)
    "full": (400, 600, 1.0, 3.0),
    "splash": (1000, 500, 0.3, 1.2),
    "icon": (96, 96, 0.5, 2.5),
}


def art_key(char_id: int, tier: str) -> str:
    return f"art:{tier}:{char_id}"


def plan_character_art(c: CharacterDetail) -> list[tuple[str, list[str]]]:
    """Download plan for the three art tiers (keys + ordered candidate URLs). Missing tiers are simply absent."""
    plan: list[tuple[str, list[str]]] = []
    if c.art_url:
        plan.append((art_key(c.id, "full"), [c.art_url]))
    for _, urls in splash_for(c.candidates, "x"):
        plan.append((art_key(c.id, "splash"), urls))
    if c.candidates:
        plan.append((art_key(c.id, "icon"), list(c.candidates)))
    return plan


def decode_image(data: bytes | None) -> Image.Image | None:
    """Bytes -> RGBA image, or None if the payload is not a real, openable image (HTML error pages, truncated files)."""
    if not data:
        return None
    try:
        probe = Image.open(io.BytesIO(data))
        probe.verify()
        return Image.open(io.BytesIO(data)).convert("RGBA")
    except Exception:
        return None


def validate_art(img: Image.Image | None, tier: str) -> bool:
    if img is None:
        return False
    min_w, min_h, lo, hi = ART_RULES[tier]
    w, h = img.size
    return w >= min_w and h >= min_h and lo <= h / w <= hi


@dataclass
class Art:
    image: Image.Image | None
    tier: str  # "full" | "splash" | "icon" | "none"


@lru_cache(maxsize=256)
def _bundled(rel: str) -> Image.Image | None:
    path = ROOT / rel
    if not path.is_file():
        return None
    try:
        return Image.open(path).convert("RGBA")
    except OSError:
        return None


def _resized(img: Image.Image | None, size: int | tuple[int, int] | None) -> Image.Image | None:
    if img is None or size is None:
        return img
    box = (size, size) if isinstance(size, int) else size
    return img.resize(box, Image.LANCZOS)


@lru_cache(maxsize=16)
def game_font(size: int) -> ImageFont.FreeTypeFont:
    path = ROOT / "fonts" / "yuanshen.ttf"
    try:
        return ImageFont.truetype(str(path), size)
    except OSError:  # font file missing: degrade to the bundled UI font instead of crashing
        return ImageFont.truetype(str(ROOT / "fonts" / "Inter-Bold.otf"), size)


@dataclass
class Assets:
    """Per-render resolver. `fetched` is the dict[key -> bytes] returned by ImageFetcher."""

    fetched: dict[str, bytes] = field(default_factory=dict)
    missing: list[str] = field(default_factory=list)

    def _miss(self, what: str) -> None:
        if what not in self.missing:
            self.missing.append(what)

    # ---- bundled ----------------------------------------------------------
    def element(self, element: str, size: int | None = None) -> Image.Image | None:
        img = _bundled(f"elements/{element}.png") if element in ELEMENTS else None
        if img is None:
            self._miss(f"element:{element}")
        return _resized(img, size)

    def ui(self, name: str, size: int | tuple[int, int] | None = None, tint: tuple[int, int, int] | None = None) -> Image.Image | None:
        img = _bundled(f"ui/{name}.png")
        if img is None:
            self._miss(f"ui:{name}")
        elif tint is not None:  # recolour a one-colour glyph, keeping its alpha
            img = Image.merge("RGBA", (*Image.new("RGB", img.size, tint).split(), img.getchannel("A")))
        return _resized(img, size)

    def stars(self, rarity: int) -> Image.Image | None:
        return self.ui(f"stars/{max(1, min(5, rarity))}")

    def stat_icon(self, stat: Stat | None, size: int | None = None, fallback_element: str = "") -> Image.Image | None:
        """Bundled icon by logical key; falls back to the HoYoLAB-provided icon if it was downloaded; else None."""
        if stat is None:
            return None
        key = stat_key(stat.name, stat.value)
        img: Image.Image | None = None
        if key and key.startswith("element:"):
            img = self.element(key.split(":", 1)[1])
        elif key:
            img = _bundled(f"stats/{key}.png")
        if img is None and stat.icon:
            img = decode_image(self.fetched.get(stat.icon))
        if img is None:
            self._miss(f"stat:{stat.name}")
        return _resized(img, size)

    # ---- fetched ----------------------------------------------------------
    def icon(self, url: str, size: int | tuple[int, int] | None = None) -> Image.Image | None:
        """Weapon / artifact / talent / constellation icon downloaded by URL."""
        img = decode_image(self.fetched.get(url)) if url else None
        if img is None:
            self._miss("icon")
        return _resized(img, size)

    def art(self, c: CharacterDetail) -> Art:
        """Best valid art among full artwork, splash art and portrait icon (see ART_ORDER)."""
        for tier in ART_ORDER:
            img = decode_image(self.fetched.get(art_key(c.id, tier)))
            if validate_art(img, tier):
                return Art(img, tier)
        self._miss("art")
        return Art(None, "none")
