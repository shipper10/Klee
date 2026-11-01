"""Normalized player profile (overview stats + character list), independent of genshin.py models."""

from __future__ import annotations

from dataclasses import asdict, dataclass, field
from typing import Any

from app.abyss import icon_candidates

SCHEMA_VERSION = 1


@dataclass
class ProfChar:
    name: str
    icon: str  # lookup key for downloaded images
    level: int = 1
    rarity: int = 4
    constellation: int = 0
    friendship: int = 0
    element: str = ""
    candidates: list[str] = field(default_factory=list)


@dataclass
class ProfileData:
    nickname: str = ""
    level: int = 0
    days_active: int = 0
    achievements: int = 0
    characters_owned: int = 0
    max_friendship: int = 0
    spiral_abyss: str = ""
    theater_act: int = 0
    theater_unlocked: bool = False
    stygian_difficulty: int = 0
    stygian_unlocked: bool = False
    chests: int = 0
    oculi: int = 0
    waypoints: int = 0
    domains: int = 0
    characters: list[ProfChar] = field(default_factory=list)

    def to_json(self) -> dict[str, Any]:
        return asdict(self)

    @classmethod
    def from_json(cls, data: dict[str, Any]) -> "ProfileData":
        chars = [ProfChar(**c) for c in data.get("characters", [])]
        return cls(**{**data, "characters": chars})

    def sorted_characters(self) -> list[ProfChar]:
        return sorted(self.characters, key=lambda c: (-c.rarity, -c.level, -c.constellation, c.name))

    def icon_candidates(self, limit: int | None = None) -> list[tuple[str, list[str]]]:
        chars = self.sorted_characters()[:limit] if limit else self.sorted_characters()
        return [(c.icon, c.candidates) for c in chars if c.icon]

    @classmethod
    def from_genshin(cls, user: Any) -> "ProfileData":
        """Build from genshin.py's GenshinUserStats (only the fields we draw are read)."""
        s, info = user.stats, user.info
        g = lambda obj, name, default=0: getattr(obj, name, default) or default  # noqa: E731
        theater, stygian = getattr(s, "theater", None), getattr(s, "stygian", None)
        chars = []
        for c in user.characters:
            url = str(g(c, "icon", ""))
            cands = icon_candidates(url, int(g(c, "id")))
            chars.append(
                ProfChar(
                    name=str(g(c, "name", "")), icon=url or (cands[0] if cands else ""),
                    level=int(g(c, "level", 1)), rarity=int(g(c, "rarity", 4)),
                    constellation=int(g(c, "constellation")), friendship=int(g(c, "friendship")),
                    element=str(g(c, "element", "")), candidates=cands,
                )
            )
        return cls(
            nickname=str(g(info, "nickname", "")), level=int(g(info, "level")),
            days_active=int(g(s, "days_active")), achievements=int(g(s, "achievements")),
            characters_owned=int(g(s, "characters")) or len(chars),
            max_friendship=int(g(s, "max_friendship_characters")), spiral_abyss=str(g(s, "spiral_abyss", "")),
            theater_act=int(g(theater, "max_act")), theater_unlocked=bool(g(theater, "unlocked", False)),
            stygian_difficulty=int(g(stygian, "difficulty")), stygian_unlocked=bool(g(stygian, "unlocked", False)),
            chests=sum(int(g(s, n)) for n in ("common_chests", "exquisite_chests", "precious_chests", "luxurious_chests", "remarkable_chests")),
            oculi=sum(int(g(s, n)) for n in ("anemoculi", "geoculi", "electroculi", "dendroculi", "hydroculi", "pyroculi", "lunoculi")),
            waypoints=int(g(s, "unlocked_waypoints")), domains=int(g(s, "unlocked_domains")),
            characters=chars,
        )
