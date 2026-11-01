"""Normalized Spiral Abyss data (independent of genshin.py models so it can be cached and tested)."""

from __future__ import annotations

import re
from collections.abc import Mapping
from dataclasses import asdict, dataclass, field
from datetime import datetime, timezone
from typing import Any

SCHEMA_VERSION = 3


_ICON_NAME = re.compile(r"UI_AvatarIcon(?:_Side)?_(.+?)\.png")


def _icon_name_for_id(char_id: int) -> str:
    """Icon file name genshin.py knows for a character id (its table comes from Enka/Ambr), or ""."""
    try:
        from genshin.models.genshin import constants as gc

        entry = gc.CHARACTER_NAMES.get("en-us", {}).get(char_id)
        return str(getattr(entry, "icon_name", "") or "")
    except Exception:  # the table is optional; never let it break a report
        return ""


def icon_candidates(raw_url: str, char_id: int = 0) -> list[str]:
    """Download candidates for one character portrait, best first.

    1. enka.network by character id (what the first version used; worked for most characters),
    2. enka.network by the name inside HoYoLAB's own URL,
    3. the same name on gi.yatta.moe,
    4. HoYoLAB's URL itself (may be the small side icon, but better than a placeholder).
    """
    names = [n for n in (_icon_name_for_id(char_id) if char_id else "",) if n]
    m = _ICON_NAME.search(raw_url or "")
    if m:
        names.append(m.group(1))
    out: list[str] = []
    for n in dict.fromkeys(names):
        out.append(f"https://enka.network/ui/UI_AvatarIcon_{n}.png")
    for n in dict.fromkeys(names[-1:]):
        out.append(f"https://gi.yatta.moe/assets/UI/UI_AvatarIcon_{n}.png")
    if raw_url:
        out.append("https://" + raw_url[len("http://"):] if raw_url.startswith("http://") else raw_url)
    return list(dict.fromkeys(out))


@dataclass
class Char:
    icon: str  # lookup key: the URL HoYoLAB returned (or the first candidate if it returned none)
    level: int = 0
    rarity: int = 4
    value: int = 0  # play count / stat value, depending on where it is used
    candidates: list[str] = field(default_factory=list)  # download URLs, best first


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

    def _all_chars(self) -> list[Char]:
        chars = list(self.most_played)
        for f in self.floors:
            for ch in f.chambers:
                chars += ch.first_half + ch.second_half
        return chars

    def icon_urls(self) -> list[str]:
        return [u for u in dict.fromkeys(c.icon for c in self._all_chars()) if u]

    def icon_candidates(self) -> list[tuple[str, list[str]]]:
        """(lookup key, download candidates) for every distinct icon."""
        found = {c.icon: c.candidates for c in self._all_chars() if c.icon}
        return list(found.items())

    @property
    def has_data(self) -> bool:
        return self.total_battles > 0 or any(f.chambers for f in self.floors)

    @classmethod
    def from_raw(cls, raw: Mapping[str, Any]) -> "AbyssData":
        """Parse the raw HoYoLAB `spiralAbyss` payload (field names taken from genshin.py 1.7.31's model aliases).

        Parsed directly so that every icon URL HoYoLAB returns is kept as the last-resort download candidate.
        """

        def to_int(v: Any, default: int = 0) -> int:
            try:
                return int(v)
            except (TypeError, ValueError):
                return default

        def rarity_of(v: Any) -> int:
            r = to_int(v, 4)
            return r - 100 if r > 100 else r  # collaboration characters are stored as 105

        def icon_of(item: Mapping[str, Any], key: str) -> str:
            return str(item.get(key) or item.get("icon") or item.get("image") or "")

        def char(item: Mapping[str, Any], key: str = "icon", **extra: Any) -> Char:
            url = icon_of(item, key)
            cands = icon_candidates(url, to_int(item.get("id") or item.get("avatar_id")))
            return Char(icon=url or (cands[0] if cands else ""), rarity=rarity_of(item.get("rarity")), candidates=cands, **extra)

        stats: list[Stat] = []
        for key, rank_key in (
            ("most_kills", "defeat_rank"),
            ("strongest_strike", "damage_rank"),
            ("most_damage_taken", "take_damage_rank"),
            ("most_bursts_used", "energy_skill_rank"),
            ("most_skills_used", "normal_skill_rank"),
        ):
            top = (raw.get(rank_key) or [None])[0]
            if top:
                stats.append(Stat(key=key, value=to_int(top.get("value")), icon=icon_of(top, "avatar_icon")))

        floors: list[Floor] = []
        for f in raw.get("floors") or []:
            chambers: list[Chamber] = []
            for c in f.get("levels") or []:
                halves: dict[int, list[Char]] = {1: [], 2: []}
                last_ts: int | None = None
                for b in c.get("battles") or []:
                    halves.setdefault(to_int(b.get("index"), 1), []).extend(
                        char(a, "icon", level=to_int(a.get("level"))) for a in b.get("avatars") or []
                    )
                    t = to_int(b.get("timestamp"), 0)
                    if t and (last_ts is None or t > last_ts):
                        last_ts = t
                chambers.append(
                    Chamber(
                        number=to_int(c.get("index")),
                        stars=to_int(c.get("star")),
                        timestamp=last_ts,
                        first_half=halves.get(1, []),
                        second_half=halves.get(2, []),
                    )
                )
            floors.append(
                Floor(
                    number=to_int(f.get("index")),
                    stars=to_int(f.get("star")),
                    max_stars=to_int(f.get("max_star"), 9),
                    chambers=chambers,
                )
            )

        return cls(
            period_start=to_int(raw.get("start_time")),
            period_end=to_int(raw.get("end_time")),
            total_stars=to_int(raw.get("total_star")),
            max_floor=str(raw.get("max_floor") or "-"),
            total_battles=to_int(raw.get("total_battle_times")),
            most_played=[
                char(c, "avatar_icon", value=to_int(c.get("value"))) for c in (raw.get("reveal_rank") or [])[:4]
            ],
            stats=stats,
            floors=sorted(floors, key=lambda x: x.number),
        )

    @staticmethod
    def utc(ts_value: int | None) -> datetime | None:
        return datetime.fromtimestamp(ts_value, tz=timezone.utc) if ts_value else None
