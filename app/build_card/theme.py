"""Per-element palettes for the Build Card. Adding an element look = adding one entry."""

from __future__ import annotations

from dataclasses import dataclass

RGB = tuple[int, int, int]


@dataclass(frozen=True)
class BuildTheme:
    bg_light: RGB  # top-left of the background gradient
    bg_dark: RGB  # bottom-right
    glow: RGB  # radial light behind the character
    accent: RGB  # highlights, chips, ticks
    panel_tint: RGB  # tint mixed into the glass panels


THEMES: dict[str, BuildTheme] = {
    "Pyro": BuildTheme((150, 34, 30), (56, 12, 18), (255, 120, 70), (255, 168, 120), (120, 24, 24)),
    "Hydro": BuildTheme((18, 104, 152), (8, 36, 70), (80, 170, 255), (140, 210, 255), (14, 70, 120)),
    "Anemo": BuildTheme((24, 128, 116), (10, 52, 58), (90, 230, 200), (150, 240, 215), (14, 90, 90)),
    "Electro": BuildTheme((104, 48, 168), (38, 16, 80), (180, 120, 255), (205, 165, 255), (74, 34, 130)),
    "Dendro": BuildTheme((40, 120, 44), (12, 48, 22), (150, 235, 90), (190, 240, 130), (26, 84, 34)),
    "Cryo": BuildTheme((44, 112, 168), (16, 44, 92), (170, 230, 255), (200, 238, 255), (28, 76, 130)),
    "Geo": BuildTheme((164, 112, 30), (66, 44, 14), (255, 205, 90), (255, 220, 130), (126, 86, 22)),
}
NEUTRAL = BuildTheme((70, 74, 100), (24, 26, 44), (200, 205, 255), (220, 224, 255), (50, 54, 84))


def theme_for(element: str) -> BuildTheme:
    return THEMES.get(element, NEUTRAL)
