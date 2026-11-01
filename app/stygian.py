"""Normalized Stygian Onslaught data, parsed from HoYoLAB's raw `hard_challenge` payload."""

from __future__ import annotations

import re
import time
from collections.abc import Mapping
from dataclasses import asdict, dataclass, field
from typing import Any

from app.abyss import icon_candidates

SCHEMA_VERSION = 1
BEST_KINDS = {1: "Strongest Strike", 2: "Highest Damage"}
_MARKUP = re.compile(r"<[^>]*>|\{[^}]*\}")


def clean(text: Any) -> str:
    return re.sub(r"\s+", " ", _MARKUP.sub("", str(text or ""))).strip()


@dataclass
class SChar:
    icon: str
    level: int = 0
    rarity: int = 4
    constellation: int = 0
    value: str = ""  # best-character value (damage)
    kind: int = 0  # 1 strike, 2 damage (best characters only)
    candidates: list[str] = field(default_factory=list)


@dataclass
class SChallenge:
    name: str = ""
    seconds: int = 0
    team: list[SChar] = field(default_factory=list)
    best: list[SChar] = field(default_factory=list)
    enemy_name: str = ""
    enemy_level: int = 0
    enemy_notes: list[str] = field(default_factory=list)


@dataclass
class SMode:
    has_data: bool = False
    best_difficulty: int = 0
    best_seconds: int = 0
    challenges: list[SChallenge] = field(default_factory=list)


@dataclass
class StygianData:
    found: bool = False  # a matching season exists in the payload
    season: str = ""
    period_start: int = 0
    period_end: int = 0
    single: SMode = field(default_factory=SMode)
    multi: SMode = field(default_factory=SMode)

    def mode(self, multi: bool) -> SMode:
        return self.multi if multi else self.single

    @property
    def has_data(self) -> bool:
        return self.single.has_data or self.multi.has_data

    def icon_candidates(self, multi: bool | None = None) -> list[tuple[str, list[str]]]:
        modes = [self.single, self.multi] if multi is None else [self.mode(multi)]
        chars = [c for m in modes for ch in m.challenges for c in ch.team + ch.best]
        return list({c.icon: c.candidates for c in chars if c.icon}.items())

    def to_json(self) -> dict[str, Any]:
        return asdict(self)

    @classmethod
    def from_json(cls, data: dict[str, Any]) -> "StygianData":
        def mode(m: dict[str, Any]) -> SMode:
            chs = [
                SChallenge(**{**c, "team": [SChar(**x) for x in c.get("team", [])], "best": [SChar(**x) for x in c.get("best", [])]})
                for c in m.get("challenges", [])
            ]
            return SMode(**{**m, "challenges": chs})

        return cls(**{**data, "single": mode(data.get("single", {})), "multi": mode(data.get("multi", {}))})

    @classmethod
    def from_raw(cls, raw: list[Mapping[str, Any]] | Mapping[str, Any], previous: bool = False, now: int | None = None) -> "StygianData":
        entries = list(raw.get("data") or []) if isinstance(raw, Mapping) else list(raw or [])
        now = int(time.time()) if now is None else now

        def num(v: Any, default: int = 0) -> int:
            try:
                return int(v)
            except (TypeError, ValueError):
                return default

        def span(e: Mapping[str, Any]) -> tuple[int, int]:
            sc = e.get("schedule") or {}
            return num(sc.get("start_time")), num(sc.get("end_time"))

        timed = sorted((e for e in entries if span(e)[0]), key=lambda e: -span(e)[0])
        if timed:
            pool = [e for e in timed if (span(e)[1] < now if previous else span(e)[0] <= now <= span(e)[1])]
            entry: Mapping[str, Any] = pool[0] if pool else {}
        else:
            index = 1 if previous else 0
            entry = entries[index] if len(entries) > index else {}
        if not entry:
            return cls()

        def char(item: Mapping[str, Any], **extra: Any) -> SChar:
            url = str(item.get("image") or item.get("icon") or item.get("side_icon") or "")
            cands = icon_candidates(url, num(item.get("avatar_id") or item.get("id")))
            r = num(item.get("rarity"), 4)
            return SChar(icon=url or (cands[0] if cands else ""), rarity=r - 100 if r > 100 else r, candidates=cands, **extra)

        def mode(m: Mapping[str, Any]) -> SMode:
            best = m.get("best") or {}
            chs = []
            for c in m.get("challenge") or []:
                mon = c.get("monster") or {}
                chs.append(
                    SChallenge(
                        name=clean(c.get("name")), seconds=num(c.get("second")),
                        team=[char(t, level=num(t.get("level")), constellation=num(t.get("rank"))) for t in c.get("teams") or []],
                        best=[char(b, value=str(b.get("dps") or ""), kind=num(b.get("type"))) for b in c.get("best_avatar") or []],
                        enemy_name=clean(mon.get("name")), enemy_level=num(mon.get("level")),
                        enemy_notes=[n for n in (clean(d) for d in mon.get("desc") or []) if n][:3],
                    )
                )
            return SMode(has_data=bool(m.get("has_data")) and bool(chs), best_difficulty=num(best.get("difficulty")),
                         best_seconds=num(best.get("second")), challenges=chs)

        start, end = span(entry)
        return cls(found=True, season=clean((entry.get("schedule") or {}).get("name")), period_start=start, period_end=end,
                   single=mode(entry.get("single") or {}), multi=mode(entry.get("mp") or {}))
