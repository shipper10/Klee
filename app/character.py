"""Normalized single-character detail (weapon, artifacts, talents, stats), parsed from the raw `character/detail` payload."""

from __future__ import annotations

from collections.abc import Mapping
from dataclasses import asdict, dataclass, field
from typing import Any

from app.abyss import icon_candidates

SCHEMA_VERSION = 1
ARTIFACT_SLOTS = {1: "Flower", 2: "Plume", 3: "Sands", 4: "Goblet", 5: "Circlet"}


def _https(url: Any) -> list[str]:
    u = str(url or "")
    if not u:
        return []
    return ["https://" + u[len("http://"):] if u.startswith("http://") else u]


@dataclass
class Stat:
    name: str
    value: str


@dataclass
class Weapon:
    name: str = ""
    level: int = 0
    rarity: int = 3
    refinement: int = 1
    icon: str = ""
    main: Stat | None = None
    sub: Stat | None = None


@dataclass
class Artifact:
    slot: int
    name: str = ""
    set_name: str = ""
    rarity: int = 5
    level: int = 0
    icon: str = ""
    main: Stat | None = None
    subs: list[Stat] = field(default_factory=list)


@dataclass
class Talent:
    name: str
    level: int


@dataclass
class CharacterDetail:
    id: int = 0
    name: str = ""
    element: str = ""
    rarity: int = 4
    level: int = 1
    constellation: int = 0
    friendship: int = 0
    icon: str = ""
    candidates: list[str] = field(default_factory=list)
    weapon: Weapon | None = None
    artifacts: list[Artifact] = field(default_factory=list)
    sets: list[str] = field(default_factory=list)  # e.g. "Marechaussee Hunter (4)"
    talents: list[Talent] = field(default_factory=list)
    constellations: list[tuple[str, bool]] = field(default_factory=list)  # (name, activated)
    stats: list[Stat] = field(default_factory=list)

    def icon_candidates(self) -> list[tuple[str, list[str]]]:
        items = [(self.icon, self.candidates)] if self.icon else []
        if self.weapon and self.weapon.icon:
            items.append((self.weapon.icon, _https(self.weapon.icon)))
        items += [(a.icon, _https(a.icon)) for a in self.artifacts if a.icon]
        return list(dict(items).items())

    @property
    def splash_key(self) -> str:
        return f"splash:{self.id}"

    def splash_candidates(self) -> list[tuple[str, list[str]]]:
        """Full-body splash art (Enka, then yatta), derived from the portrait name. Empty if the name is unknown."""
        import re

        for url in self.candidates:
            m = re.search(r"UI_AvatarIcon_([A-Za-z0-9_]+)\.png", url)
            if m and not m.group(1).startswith("Side"):
                name = m.group(1)
                return [(self.splash_key, [
                    f"https://enka.network/ui/UI_Gacha_AvatarImg_{name}.png",
                    f"https://gi.yatta.moe/assets/UI/UI_Gacha_AvatarImg_{name}.png",
                ])]
        return []

    def to_json(self) -> dict[str, Any]:
        return asdict(self)

    @classmethod
    def from_json(cls, data: dict[str, Any]) -> "CharacterDetail":
        def stat(x: Any) -> Stat | None:
            return Stat(**x) if x else None

        w = data.get("weapon")
        weapon = Weapon(**{**w, "main": stat(w.get("main")), "sub": stat(w.get("sub"))}) if w else None
        arts = [Artifact(**{**a, "main": stat(a.get("main")), "subs": [Stat(**s) for s in a.get("subs", [])]}) for a in data.get("artifacts", [])]
        return cls(**{**data, "weapon": weapon, "artifacts": arts,
                      "talents": [Talent(**t) for t in data.get("talents", [])],
                      "constellations": [tuple(c) for c in data.get("constellations", [])],
                      "stats": [Stat(**s) for s in data.get("stats", [])]})

    @classmethod
    def from_raw(cls, raw: Mapping[str, Any], char_id: int) -> "CharacterDetail | None":
        """Detail for `char_id`, or None if the payload does not contain it."""

        def num(v: Any, default: int = 0) -> int:
            try:
                return int(v)
            except (TypeError, ValueError):
                return default

        prop_map = raw.get("property_map") or {}

        def label(prop: Mapping[str, Any]) -> str:
            info = prop.get("info") or prop_map.get(str(prop.get("property_type"))) or {}
            return str(info.get("name") or f"Stat {prop.get('property_type', '?')}").replace("\xa0", " ")

        def stat(prop: Any, key: str) -> Stat | None:
            if not prop:
                return None
            value = str(prop.get(key) or prop.get("value") or "")
            return Stat(label(prop), value) if value else None

        entry = next((c for c in raw.get("list") or [] if num((c.get("base") or {}).get("id", c.get("id"))) == char_id), None)
        if entry is None:
            return None
        base = {**(entry.get("base") or {}), **{k: v for k, v in entry.items() if k != "base"}}
        url = str(base.get("image") or base.get("icon") or "")
        cands = icon_candidates(str(base.get("icon") or url), char_id)
        r = num(base.get("rarity"), 4)

        w = entry.get("weapon") or {}
        weapon = None
        if w.get("name"):
            weapon = Weapon(
                name=str(w["name"]), level=num(w.get("level")), rarity=num(w.get("rarity"), 3),
                refinement=num(w.get("affix_level"), 1), icon=_https(w.get("icon"))[0] if w.get("icon") else "",
                main=stat(w.get("main_property"), "final"), sub=stat(w.get("sub_property"), "final"),
            )

        arts: list[Artifact] = []
        set_counts: dict[str, int] = {}
        for a in sorted(entry.get("relics") or [], key=lambda x: num(x.get("pos"))):
            sname = str((a.get("set") or {}).get("name") or "")
            set_counts[sname] = set_counts.get(sname, 0) + 1
            arts.append(
                Artifact(
                    slot=num(a.get("pos")), name=str(a.get("name") or ""), set_name=sname, rarity=num(a.get("rarity"), 5),
                    level=num(a.get("level")), icon=_https(a.get("icon"))[0] if a.get("icon") else "",
                    main=stat(a.get("main_property"), "value"),
                    subs=[s for s in (stat(p, "value") for p in a.get("sub_property_list") or []) if s],
                )
            )
        sets = [f"{n} ({'4' if c >= 4 else '2'})" for n, c in set_counts.items() if n and c >= 2]

        talents = [Talent(str(s.get("name") or ""), num(s.get("level"))) for s in entry.get("skills") or []
                   if num(s.get("level")) > 0 and s.get("name")][:4]
        consts = [(str(c.get("name") or ""), bool(c.get("is_actived"))) for c in sorted(entry.get("constellations") or [], key=lambda x: num(x.get("pos")))]

        props = entry.get("selected_properties") or entry.get("base_properties") or []
        stats = [s for s in (stat(p, "final") for p in props) if s and s.value not in ("0", "0%", "0.0%")][:12]

        return cls(
            id=char_id, name=str(base.get("name") or ""), element=str(base.get("element") or ""),
            rarity=r - 100 if r > 100 else r, level=num(base.get("level"), 1),
            constellation=num(base.get("actived_constellation_num")) or sum(1 for _, on in consts if on),
            friendship=num(base.get("fetter")), icon=url or (cands[0] if cands else ""), candidates=cands,
            weapon=weapon, artifacts=arts, sets=sets, talents=talents, constellations=consts, stats=stats,
        )
