"""Report designs ("styles"): which designs exist for each report type, and how a user's choice is resolved.

Order of precedence for a report: the user's own pick for that service, the user's pick for "all services",
the owner's default for that service, the owner's default for all services, then the built-in default.
A stored choice that is no longer available (for example a design that was removed) is ignored, so removing a design never
breaks a user. To add a design see `app/renderers.py`.
"""

from __future__ import annotations

from typing import Any, Protocol

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
# Every design: id -> (label, description).
LAYOUTS: dict[str, tuple[str, str]] = {
    "official": ("Official look", "Close to the official HoYoLAB page for that report."),
    "build": ("Build Card", "Game-style build card: full art, stat icons, artifact rolls, element-themed background."),
    "showcase": ("Showcase", "Large splash art, glass panels and element colours, in the spirit of Enka cards."),
}
# Designs available per service (the first one is not special; DEFAULT_STYLE says which is used by default).
SERVICE_STYLES: dict[str, list[str]] = {
    "notes": ["official"],
    "abyss": ["official"],
    "theater": ["official"],
    "stygian": ["official"],
    "diary": ["official"],
    "profile": ["showcase"],
    "character": ["build", "showcase"],
}
# Built-in default per service when nobody (user or owner) has chosen anything.
DEFAULT_STYLE: dict[str, str] = {
    "notes": "official", "abyss": "official", "theater": "official", "stygian": "official", "diary": "official",
    "profile": "showcase", "character": "build",
}


def known(style: str) -> bool:
    return style in LAYOUTS


def label(style: str) -> str:
    return LAYOUTS[style][0]


def description(style: str) -> str:
    return LAYOUTS[style][1]


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
    return DEFAULT_STYLE[service]


async def resolve(db: PrefStore, user_id: int, service: str) -> str:
    try:
        rows = await db.get_style_prefs(user_id)
    except Exception:
        return DEFAULT_STYLE[service]  # never block a report because preferences are unavailable
    return pick(rows, user_id, service)


def current_choice(rows: list[dict[str, Any]], user_id: int, service: str) -> str | None:
    """The explicit choice stored for exactly this scope and service (None = using the default)."""
    for r in rows:
        if int(r["user_id"]) == user_id and r["service"] == service and (known(r["style"]) if service == ALL else is_valid(service, r["style"])):
            return r["style"]
    return None
