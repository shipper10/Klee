"""View model for the Character Build Card: plain data, no drawing, no I/O.

Built from CharacterDetail. Every field is either sent by HoYoLAB, derived by an exact rule, or left empty/None.
Nothing is estimated: a missing value is simply not drawn.
"""

from __future__ import annotations

from dataclasses import dataclass, field

from app.character import Artifact, CharacterDetail, Cons, Stat, Talent

# Weapon ascension -> max level. Exact game rule, only used when HoYoLAB sends the ascension and the weapon is 3-5 stars.
WEAPON_MAX_LEVEL = {0: 20, 1: 40, 2: 50, 3: 60, 4: 70, 5: 80, 6: 90}
LABELS = {"Max HP": "HP", "Elemental Mastery": "Elemental Mastery"}
MAX_ROLL_TICKS = 6


@dataclass
class StatRow:
    stat: Stat
    label: str
    value: str
    base: str = ""  # shown small under the value, only when HoYoLAB sent both base and bonus
    bonus: str = ""


@dataclass
class SubRow:
    stat: Stat
    value: str
    ticks: int | None  # roll count exactly as sent (None = not sent -> no tick marks)


@dataclass
class ArtifactRow:
    slot: int
    level: int
    rarity: int
    icon: str
    main: Stat | None
    subs: list[SubRow]
    set_name: str = ""


@dataclass
class BuildModel:
    name: str
    element: str
    level: int
    friendship: int
    constellation: int
    cons: list[Cons]
    talents: list[Talent]
    weapon_name: str = ""
    weapon_icon: str = ""
    weapon_rarity: int = 0
    weapon_level: int = 0
    weapon_max_level: int | None = None
    refinement: int = 0
    weapon_stats: list[Stat] = field(default_factory=list)
    stats: list[StatRow] = field(default_factory=list)
    artifacts: list[ArtifactRow | None] = field(default_factory=list)  # always 5 entries (slots 1-5), None = empty slot
    sets: list[tuple[str, int]] = field(default_factory=list)  # (set name, active pieces 2 or 4)
    set_icon: str = ""


def _clean(v: str) -> str:
    return v.replace("\xa0", " ").strip()


def _row(s: Stat) -> StatRow:
    base, add = _clean(s.base), _clean(s.add)
    show = bool(base and add and add not in ("0", "+0", "0%"))
    return StatRow(stat=s, label=LABELS.get(s.name, s.name), value=_clean(s.value), base=base if show else "", bonus=add if show else "")


def _art_row(a: Artifact) -> ArtifactRow:
    subs = [
        SubRow(stat=s, value=_clean(s.value), ticks=None if s.times is None else max(0, min(MAX_ROLL_TICKS, s.times)))
        for s in a.subs[:4]
    ]
    return ArtifactRow(slot=a.slot, level=a.level, rarity=a.rarity, icon=a.icon, main=a.main, subs=subs, set_name=a.set_name)


def build_model(c: CharacterDetail) -> BuildModel:
    by_slot = {a.slot: a for a in c.artifacts}
    set_counts: dict[str, int] = {}
    for a in c.artifacts:
        if a.set_name:
            set_counts[a.set_name] = set_counts.get(a.set_name, 0) + 1
    sets = [(n, 4 if k >= 4 else 2) for n, k in set_counts.items() if k >= 2]
    first = next((a for a in c.artifacts if a.icon), None)

    w = c.weapon
    m = BuildModel(
        name=c.name or "Unknown", element=c.element, level=c.level, friendship=c.friendship, constellation=c.constellation,
        cons=sorted(c.cons, key=lambda x: x.pos) if c.cons else [Cons(n, "", on, i + 1) for i, (n, on) in enumerate(c.constellations)],
        talents=c.talents[:3],
        stats=[_row(s) for s in (c.core_stats or c.stats)[:8]],
        artifacts=[_art_row(by_slot[i]) if i in by_slot else None for i in range(1, 6)],
        sets=sets, set_icon=first.icon if first else "",
    )
    if w:
        m.weapon_name, m.weapon_icon, m.weapon_rarity = w.name, w.icon, w.rarity
        m.weapon_level, m.refinement = w.level, w.refinement
        m.weapon_stats = [s for s in (w.main, w.sub) if s]
        asc = getattr(w, "ascension", None)
        m.weapon_max_level = WEAPON_MAX_LEVEL.get(asc) if asc is not None and w.rarity >= 3 else None
    return m
