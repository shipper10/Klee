"""Stat naming and number formatting shared by the parser, the view model and the asset manager."""

from __future__ import annotations

import re

from app.constants import ELEMENTS

_PLAIN = re.compile(r"[^a-z]+")
# Build Card stat block, in display order (logical keys from stat_key).
CORE_KEYS = ("hp", "atk", "def", "em", "crit_rate", "crit_dmg", "er")


def stat_key(name: str, value: str = "") -> str | None:
    """Logical stat key from the displayed name; flat vs percent is decided by the value, never guessed."""
    n = _PLAIN.sub(" ", name.lower().replace("%", " ")).strip()
    n = n.replace("max ", "").replace("base ", "")
    pct = str(value).strip().endswith("%")
    table = {
        "hp": "hp_pct" if pct else "hp",
        "atk": "atk_pct" if pct else "atk",
        "def": "def_pct" if pct else "def",
        "elemental mastery": "em",
        "crit rate": "crit_rate",
        "crit dmg": "crit_dmg",
        "energy recharge": "er",
        "healing bonus": "healing",
        "physical dmg bonus": "physical",
    }
    if n in table:
        return table[n]
    for el in ELEMENTS:
        if n == f"{el.lower()} dmg bonus":
            return f"element:{el}"
    return None


_INT = re.compile(r"([+-]?)(\d+)")


def group_digits(value: str) -> str:
    """'18182' -> '18,182', '+5079' -> '+5,079'. Pure formatting; anything else (percentages, decimals, already grouped) is untouched."""
    v = value.replace("\xa0", " ").strip()
    m = _INT.fullmatch(v)
    return f"{m.group(1)}{int(m.group(2)):,}" if m else v


def with_plus(value: str) -> str:
    v = group_digits(value)
    return v if not v or v[0] in "+-" else f"+{v}"
