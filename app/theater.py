"""Normalized Imaginarium Theater data, parsed from HoYoLAB's raw `role_combat` payload."""

from __future__ import annotations

from collections.abc import Mapping
from dataclasses import asdict, dataclass, field
from typing import Any

from app.abyss import icon_candidates

SCHEMA_VERSION = 1
DIFFICULTIES = {1: "Easy", 2: "Normal", 3: "Hard", 4: "Visionary", 5: "Arcana Challenge"}
CHAR_TYPES = {2: "Trial", 3: "Support"}  # 1 = the player's own character


def pick_season(entries: list[Mapping[str, Any]], previous: bool, now: int | None = None) -> Mapping[str, Any]:
    """Current season = the one whose schedule contains `now`; previous = the latest one that already ended.

    Falls back to list order (newest first) if the schedules are missing or unreadable.
    """
    import time

    now = int(time.time()) if now is None else now

    def span(e: Mapping[str, Any]) -> tuple[int, int]:
        sc = e.get("schedule") or {}
        try:
            return int(sc.get("start_time")), int(sc.get("end_time"))
        except (TypeError, ValueError):
            return 0, 0

    timed = [e for e in entries if span(e)[0]]
    if timed:
        ordered = sorted(timed, key=lambda e: -span(e)[0])
        if previous:
            ended = [e for e in ordered if span(e)[1] < now]
            return ended[0] if ended else {}
        current = [e for e in ordered if span(e)[0] <= now <= span(e)[1]]
        return current[0] if current else {}
    index = 1 if previous else 0
    return entries[index] if len(entries) > index else {}


@dataclass
class TChar:
    icon: str
    level: int = 0
    rarity: int = 4
    kind: int = 1
    value: int = 0  # used by battle-stat characters
    candidates: list[str] = field(default_factory=list)


@dataclass
class TAct:
    number: int
    medal: bool = False
    finish_time: int = 0
    is_arcana: bool = False
    arcana_number: int = 0
    characters: list[TChar] = field(default_factory=list)
    booms: list[str] = field(default_factory=list)  # Wondrous Booms
    caches: list[str] = field(default_factory=list)  # Mystery Caches


@dataclass
class TStat:
    key: str  # most_defeats | most_damage | most_damage_taken
    char: TChar


@dataclass
class TheaterData:
    unlocked: bool = False
    has_data: bool = False
    period_start: int = 0
    period_end: int = 0
    difficulty: int = 0
    best_act: int = 0
    medals: int = 0
    fantasia_flowers: int = 0
    audience_support: int = 0
    assists: int = 0
    arcana_completed: int = 0
    total_cast_seconds: int = 0
    stats: list[TStat] = field(default_factory=list)
    fastest: list[TChar] = field(default_factory=list)
    acts: list[TAct] = field(default_factory=list)

    @property
    def difficulty_name(self) -> str:
        return DIFFICULTIES.get(self.difficulty, "")

    def _all_chars(self) -> list[TChar]:
        out = [c for a in self.acts for c in a.characters] + [s.char for s in self.stats] + list(self.fastest)
        return out

    def icon_candidates(self) -> list[tuple[str, list[str]]]:
        return list({c.icon: c.candidates for c in self._all_chars() if c.icon}.items())

    def to_json(self) -> dict[str, Any]:
        return asdict(self)

    @classmethod
    def from_json(cls, data: dict[str, Any]) -> "TheaterData":
        d = dict(data)
        d["stats"] = [TStat(s["key"], TChar(**s["char"])) for s in d.get("stats", [])]
        d["fastest"] = [TChar(**c) for c in d.get("fastest", [])]
        d["acts"] = [TAct(**{**a, "characters": [TChar(**c) for c in a.get("characters", [])]}) for a in d.get("acts", [])]
        return cls(**d)

    @classmethod
    def from_raw(cls, raw: Mapping[str, Any], previous: bool = False, now: int | None = None) -> "TheaterData":
        def num(v: Any, default: int = 0) -> int:
            try:
                return int(v)
            except (TypeError, ValueError):
                return default

        def char(item: Mapping[str, Any], **extra: Any) -> TChar:
            url = str(item.get("image") or item.get("icon") or item.get("avatar_icon") or "")
            cands = icon_candidates(url, num(item.get("avatar_id") or item.get("id")))
            r = num(item.get("rarity"), 4)
            return TChar(icon=url or (cands[0] if cands else ""), rarity=r - 100 if r > 100 else r, candidates=cands, **extra)

        latest = pick_season(raw.get("data") or [], previous, now)
        stat = latest.get("stat") or {}
        sched = latest.get("schedule") or {}
        detail = latest.get("detail") or {}
        fight = detail.get("fight_statisic") or {}

        stats: list[TStat] = []
        for key, name in (("most_defeats", "max_defeat_avatar"), ("most_damage", "max_damage_avatar"),
                          ("most_damage_taken", "max_take_damage_avatar")):
            top = fight.get(name)
            if top and num(top.get("avatar_id")):
                stats.append(TStat(key, char(top, value=num(top.get("value")))))

        acts: list[TAct] = []
        for r in detail.get("rounds_data") or []:
            acts.append(
                TAct(
                    number=num(r.get("round_id")), medal=bool(r.get("is_get_medal")), finish_time=num(r.get("finish_time")),
                    is_arcana=bool(r.get("is_tarot")), arcana_number=num(r.get("tarot_serial_no")),
                    characters=[char(a, level=num(a.get("level")), kind=num(a.get("avatar_type"), 1)) for a in r.get("avatars") or []],
                    booms=[str(b.get("name")) for b in r.get("buffs") or [] if b.get("name")],
                    caches=[str(b.get("name")) for b in r.get("choice_cards") or [] if b.get("name")],
                )
            )
        return cls(
            unlocked=bool(raw.get("is_unlock")), has_data=bool(latest.get("has_data")) and bool(acts),
            period_start=num(sched.get("start_time")), period_end=num(sched.get("end_time")),
            difficulty=num(stat.get("difficulty_id")), best_act=num(stat.get("max_round_id")),
            medals=num(stat.get("medal_num")), fantasia_flowers=num(stat.get("coin_num")),
            audience_support=num(stat.get("avatar_bonus_num")), assists=num(stat.get("rent_cnt")),
            arcana_completed=num(stat.get("tarot_finished_cnt")), total_cast_seconds=num(fight.get("total_use_time")),
            stats=stats,
            fastest=[char(a, value=num(a.get("value"))) for a in fight.get("shortest_avatar_list") or []],
            acts=acts,
        )


def describe_raw(raw: Mapping[str, Any], now: int | None = None) -> str:
    """Safe summary of the payload's shape (no names, no UID, no character data) for troubleshooting."""
    import time
    from datetime import datetime, timezone

    now = int(time.time()) if now is None else now

    def ts(v: Any) -> str:
        try:
            return datetime.fromtimestamp(int(v), timezone.utc).strftime("%Y-%m-%d %H:%M")
        except (TypeError, ValueError, OSError):
            return str(v)

    entries = raw.get("data") or []
    lines = [f"now (UTC): {ts(now)}", f"is_unlock: {raw.get('is_unlock')}", f"seasons in payload: {len(entries)}"]
    for i, e in enumerate(entries):
        sc = e.get("schedule") or {}
        det = e.get("detail") or {}
        lines.append(
            f"#{i}: {ts(sc.get('start_time'))} -> {ts(sc.get('end_time'))} | has_data={e.get('has_data')} "
            f"has_detail={e.get('has_detail_data')} acts={len(det.get('rounds_data') or [])}"
        )
    for name, prev in (("current", False), ("previous", True)):
        picked = pick_season(entries, prev, now)
        sc = picked.get("schedule") or {}
        lines.append(f"{name} picks: " + (f"{ts(sc.get('start_time'))} (acts={len((picked.get('detail') or {}).get('rounds_data') or [])})" if picked else "nothing"))
    return "\n".join(lines)
