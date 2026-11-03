"""Official in-game element icons, bundled with the project (extracted game textures, UI_Icon_Element_*).

Source: github.com/helingping/gsgametextures (Texture2D/UI/Icon/Element). Game art belongs to HoYoverse.
"""
from __future__ import annotations

from functools import lru_cache
from pathlib import Path

from PIL import Image

DIR = Path(__file__).parent / "assets" / "elements"
ELEMENTS = ("Cryo", "Hydro", "Pyro", "Electro", "Anemo", "Dendro", "Geo")


@lru_cache(maxsize=32)
def element_icon(element: str, size: int) -> Image.Image | None:
    path = DIR / f"{element}.png"
    if element not in ELEMENTS or not path.is_file():
        return None
    try:
        return Image.open(path).convert("RGBA").resize((size, size), Image.LANCZOS)
    except OSError:
        return None
