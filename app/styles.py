"""Image styles: which looks exist for each report type, and how a user's choice is resolved.

Order of precedence for a report: the user's own pick for that service, the user's pick for "all services",
the owner's default for that service, the owner's default for all services, then the built-in default.
A style is currently a colour theme (see ui_kit.THEMES); the registry is per service so a service can later get
a different layout without touching the others.
"""

from __future__ import annotations

from typing import Any, Protocol

from app.ui_kit import DEFAULT_THEME, THEMES

GLOBAL_USER = 0
ALL = "*"

SERVICES: dict[str, str] = {
    "notes": "Daily Notes",
    "abyss": "Spiral Abyss",
    "theater": "Imaginarium Theater",
    "stygian": "Stygian Onslaught",
    "diary": "Traveler's Diary",
    "profile": "Profile and characters",
    "character": "Character card",
}
# Layout styles: a style with its own drawing code (not just colours), available only for the listed services.
LAYOUTS: dict[str, tuple[str, str]] = {
    "official": ("Official look", "Purple Battle Chronicle style, close to the HoYoLAB share card."),
    "build": ("Build Card", "Game-style build card: full art, stat icons, artifact rolls, element-themed background."),
    "showcase": ("Showcase", "Large splash art, glass panels and element colours, in the spirit of Enka cards."),
}
LAYOUT_SERVICES: dict[str, list[str]] = {"character": ["build", "showcase"], "profile": ["showcase"], "stygian": ["official"], "theater": ["official"], "abyss": ["official"], "notes": ["official"]}
SERVICE_STYLES: dict[str, list[str]] = {svc: list(THEMES) + LAYOUT_SERVICES.get(svc, []) for svc in SERVICES}


# Built-in default per service when nobody (user or owner) has chosen anything.
DEFAULT_STYLE: dict[str, str] = {"stygian": "official", "theater": "official", "abyss": "official", "notes": "official"}


def known(style: str) -> bool:
    return style in THEMES or style in LAYOUTS


def label(style: str) -> str:
    return THEMES[style].label if style in THEMES else LAYOUTS[style][0]


def description(style: str) -> str:
    return THEMES[style].description if style in THEMES else LAYOUTS[style][1]


class PrefStore(Protocol):
    async def get_style_prefs(self, user_id: int) -> list[dict[str, Any]]: ...
    async def set_style_pref(self, user_id: int, service: str, style: str | None) -> None: ...


def is_valid(service: str, style: str) -> bool:
    return service in SERVICE_STYLES and style in SERVICE_STYLES[service]


def pick(rows: list[dict[str, Any]], user_id: int, service: str) -> str:
    """Pure resolution over rows of (user_id, service, style)."""
    table = {(int(r["user_id"]), r["service"]): r["style"] for r in rows}
    for key in ((user_id, service), (user_id, ALL), (GLOBAL_USER, service), (GLOBAL_USER, ALL)):
        style = table.get(key)
        if style and is_valid(service, style):
            return style
    return DEFAULT_STYLE.get(service, DEFAULT_THEME)


async def resolve(db: PrefStore, user_id: int, service: str) -> str:
    try:
        rows = await db.get_style_prefs(user_id)
    except Exception:
        return DEFAULT_STYLE.get(service, DEFAULT_THEME)  # never block a report because preferences are unavailable
    return pick(rows, user_id, service)


def current_choice(rows: list[dict[str, Any]], user_id: int, service: str) -> str | None:
    """The explicit choice stored for exactly this scope and service (None = using the default)."""
    for r in rows:
        if int(r["user_id"]) == user_id and r["service"] == service and known(r["style"]):
            return r["style"]
    return None
