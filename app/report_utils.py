"""Small helpers shared by the report templates and the bot: time formatting and "which items to show" selection.

Kept free of drawing code so any template (present or future) can use them.
"""

from __future__ import annotations

from datetime import datetime, timedelta, timezone

from app.abyss import AbyssData, Floor
from app.profile import ProfChar, ProfileData

ABYSS_STAT_LABELS = {
    "most_kills": "Most Defeats",
    "strongest_strike": "Strongest Single Strike",
    "most_damage_taken": "Most Damage Taken",
    "most_bursts_used": "Elemental Bursts Unleashed",
    "most_skills_used": "Elemental Skills Cast",
}


def fmt_time(ts: int | None, tz_hours: int) -> str:
    if not ts:
        return ""
    return datetime.fromtimestamp(ts, tz=timezone(timedelta(hours=tz_hours))).strftime("%Y/%m/%d %H:%M:%S")


def fmt_period(start: int, end: int, tz_hours: int) -> str:
    tz = timezone(timedelta(hours=tz_hours))
    day = lambda t: datetime.fromtimestamp(t, tz=tz).strftime("%Y/%m/%d")  # noqa: E731
    return f"{day(start)} - {day(end)}"


def fmt_duration(seconds: int) -> str:
    """Short form used in reminder messages: 'now', '<1m', '35m', '2h 5m', '3d 4h'."""
    seconds = max(0, int(seconds))
    if seconds < 60:
        return "now" if seconds == 0 else "<1m"
    minutes = seconds // 60
    days, minutes = divmod(minutes, 1440)
    hours, minutes = divmod(minutes, 60)
    if days:
        return f"{days}d {hours}h"
    if hours:
        return f"{hours}h {minutes}m"
    return f"{minutes}m"


def select_floors(data: AbyssData, only_floor: int | None, default_count: int = 2) -> list[Floor]:
    with_data = [f for f in data.floors if f.chambers]
    if only_floor is not None:
        return [f for f in with_data if f.number == only_floor]
    return with_data[-default_count:]


def select_characters(p: ProfileData, show_all: bool, default_count: int = 16) -> list[ProfChar]:
    chars = p.sorted_characters()
    return chars if show_all else chars[:default_count]
