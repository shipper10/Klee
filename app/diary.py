"""Normalized Traveler's Diary data, parsed from HoYoLAB's raw ledger payload."""

from __future__ import annotations

from collections.abc import Mapping
from dataclasses import asdict, dataclass, field
from datetime import datetime, timedelta, timezone
from typing import Any

SCHEMA_VERSION = 1


def month_for(region_offset_hours: int, previous: bool, now: datetime | None = None, back: int | None = None) -> tuple[int, int]:
    """(year, month) of the diary to request, in the game server's time zone. `back` = months before the current one."""
    now = (now or datetime.now(timezone.utc)).astimezone(timezone(timedelta(hours=region_offset_hours)))
    year, month = now.year, now.month
    for _ in range(back if back is not None else int(previous)):
        year, month = (year - 1, 12) if month == 1 else (year, month - 1)
    return year, month


def _int(value: Any) -> int:
    try:
        return int(value)
    except (TypeError, ValueError):
        return 0


@dataclass
class Category:
    name: str
    amount: int = 0
    percent: int = 0


@dataclass
class DiaryData:
    month: int = 0
    year: int = 0
    primogems: int = 0
    mora: int = 0
    last_primogems: int = 0
    last_mora: int = 0
    primogem_rate: int = 0  # change vs. last month, percent
    mora_rate: int = 0
    today_primogems: int = 0
    today_mora: int = 0
    categories: list[Category] = field(default_factory=list)

    @property
    def found(self) -> bool:
        return bool(self.month)

    @classmethod
    def from_raw(cls, raw: Mapping[str, Any]) -> "DiaryData":
        m = raw.get("month_data") or {}
        day = raw.get("day_data") or {}
        cats = [
            Category(str(c.get("action") or "Other"), _int(c.get("num")), _int(c.get("percent")))
            for c in (m.get("group_by") or [])
        ]
        cats.sort(key=lambda c: -c.amount)
        return cls(
            month=_int(raw.get("data_month")),
            primogems=_int(m.get("current_primogems")),
            mora=_int(m.get("current_mora")),
            last_primogems=_int(m.get("last_primogems")),
            last_mora=_int(m.get("last_mora")),
            primogem_rate=_int(m.get("primogem_rate")),
            mora_rate=_int(m.get("mora_rate")),
            today_primogems=_int(day.get("current_primogems")),
            today_mora=_int(day.get("current_mora")),
            categories=cats,
        )

    def to_json(self) -> dict[str, Any]:
        return asdict(self)

    @classmethod
    def from_json(cls, data: dict[str, Any]) -> "DiaryData":
        return cls(**{**data, "categories": [Category(**c) for c in data.get("categories", [])]})
