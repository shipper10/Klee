"""Normalized Spiral Abyss data (independent of genshin.py models so it can be cached and tested)."""

from __future__ import annotations

from dataclasses import asdict, dataclass, field
from datetime import datetime, timezone
from typing import Any

SCHEMA_VERSION = 1


@dataclass
class Char:
    icon: str
    level: int = 0
    rarity: int = 4
    value: int = 0  # play count / stat value, depending on where it is used


@dataclass
class Chamber:
    number: int
    stars: int
    timestamp: int | None  # unix seconds of the last battle, None if not played
    first_half: list[Char] = field(default_factory=list)
    second_half: list[Char] = field(default_factory=list)


@dataclass
class Floor:
    number: int
    stars: int
    max_stars: int
    chambers: list[Chamber] = field(default_factory=list)


@dataclass
class Stat:
    key: str  # most_kills | strongest_strike | most_damage_taken | most_bursts_used | most_skills_used
    value: int
    icon: str = ""


@dataclass
class AbyssData:
    period_start: int
    period_end: int
    total_stars: int
    max_floor: str
    total_battles: int
    most_played: list[Char] = field(default_factory=list)
    stats: list[Stat] = field(default_factory=list)
    floors: list[Floor] = field(default_factory=list)

    def to_json(self) -> dict[str, Any]:
        return asdict(self)

    @classmethod
    def from_json(cls, data: dict[str, Any]) -> "AbyssData":
        return cls(
            period_start=data["period_start"],
            period_end=data["period_end"],
            total_stars=data["total_stars"],
            max_floor=data["max_floor"],
            total_battles=data["total_battles"],
            most_played=[Char(**c) for c in data.get("most_played", [])],
            stats=[Stat(**s) for s in data.get("stats", [])],
            floors=[
                Floor(
                    number=f["number"],
                    stars=f["stars"],
                    max_stars=f["max_stars"],
                    chambers=[
                        Chamber(
                            number=c["number"],
                            stars=c["stars"],
                            timestamp=c.get("timestamp"),
                            first_half=[Char(**x) for x in c.get("first_half", [])],
                            second_half=[Char(**x) for x in c.get("second_half", [])],
                        )
                        for c in f.get("chambers", [])
                    ],
                )
                for f in data.get("floors", [])
            ],
        )

    def icon_urls(self) -> list[str]:
        urls = [c.icon for c in self.most_played]
        for f in self.floors:
            for ch in f.chambers:
                urls += [c.icon for c in ch.first_half + ch.second_half]
        return [u for u in dict.fromkeys(urls) if u]

    @property
    def has_data(self) -> bool:
        return self.total_battles > 0 or any(f.chambers for f in self.floors)

    @classmethod
    def from_genshin(cls, abyss: Any) -> "AbyssData":
        """Convert `genshin.models.SpiralAbyss` (fields verified against genshin.py 1.7.31)."""

        def ts(dt: datetime | None) -> int | None:
            return int(dt.timestamp()) if dt else None

        ranks = abyss.ranks
        stats: list[Stat] = []
        for key, lst in (
            ("most_kills", ranks.most_kills),
            ("strongest_strike", ranks.strongest_strike),
            ("most_damage_taken", ranks.most_damage_taken),
            ("most_bursts_used", ranks.most_bursts_used),
            ("most_skills_used", ranks.most_skills_used),
        ):
            if lst:
                stats.append(Stat(key=key, value=int(lst[0].value), icon=lst[0].icon))

        floors: list[Floor] = []
        for f in abyss.floors:
            chambers: list[Chamber] = []
            for c in f.chambers:
                halves: dict[int, list[Char]] = {1: [], 2: []}
                last_ts: int | None = None
                for b in c.battles:
                    halves.setdefault(int(b.half), []).extend(
                        Char(icon=ch.icon, level=int(ch.level), rarity=int(ch.rarity)) for ch in b.characters
                    )
                    t = ts(b.timestamp)
                    if t is not None and (last_ts is None or t > last_ts):
                        last_ts = t
                chambers.append(
                    Chamber(
                        number=int(c.chamber),
                        stars=int(c.stars),
                        timestamp=last_ts,
                        first_half=halves.get(1, []),
                        second_half=halves.get(2, []),
                    )
                )
            floors.append(Floor(number=int(f.floor), stars=int(f.stars), max_stars=int(f.max_stars), chambers=chambers))

        return cls(
            period_start=ts(abyss.start_time) or 0,
            period_end=ts(abyss.end_time) or 0,
            total_stars=int(abyss.total_stars),
            max_floor=str(abyss.max_floor),
            total_battles=int(abyss.total_battles),
            most_played=[
                Char(icon=c.icon, rarity=int(c.rarity), value=int(c.value)) for c in ranks.most_played[:4]
            ],
            stats=stats,
            floors=sorted(floors, key=lambda x: x.number),
        )

    @staticmethod
    def utc(ts_value: int | None) -> datetime | None:
        return datetime.fromtimestamp(ts_value, tz=timezone.utc) if ts_value else None
