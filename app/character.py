"""Normalized single-character detail (weapon, artifacts, talents, stats), parsed from the raw `character/detail` payload."""

from __future__ import annotations

from collections.abc import Mapping
from dataclasses import asdict, dataclass, field
from typing import Any

from app.abyss import icon_candidates
from app.stats import CORE_KEYS, stat_key

SCHEMA_VERSION = 2
ARTIFACT_SLOTS = {1: "Flower", 2: "Plume", 3: "Sands", 4: "Goblet", 5: "Circlet"}


def _https(url: Any) -> list[str]:
    u = str(url or "")
    if not u:
        return []
    return ["https://" + u[len("http://"):] if u.startswith("http://") else u]


def splash_for(candidates: list[str], key: str) -> list[tuple[str, list[str]]]:
    """Full-body splash art download candidates (Enka, then yatta) derived from a portrait candidate list."""
    import re

    for url in candidates:
        m = re.search(r"UI_AvatarIcon_([A-Za-z0-9_]+)\.png", url)
        if m and not m.group(1).startswith("Side"):
            name = m.group(1)
            return [(key, [
                f"https://enka.network/ui/UI_Gacha_AvatarImg_{name}.png",
                f"https://gi.yatta.moe/assets/UI/UI_Gacha_AvatarImg_{name}.png",
            ])]
    return []


@dataclass
class Stat:
    """One displayed value. Optional fields stay empty/None when HoYoLAB did not send them (never estimated)."""

    name: str
    value: str
    times: int | None = None  # artifact substat: how many times it was rolled, as sent by HoYoLAB
    base: str = ""  # character stats: value before bonuses
    add: str = ""  # character stats: bonus from weapon/artifacts
    prop: int = 0  # HoYoLAB property_type (stable id, used to pick the stat icon)
    icon: str = ""  # HoYoLAB-provided icon URL for the stat, if any


@dataclass
class Weapon:
    name: str = ""
    level: int = 0
    rarity: int = 3
    refinement: int = 1
    icon: str = ""
    main: Stat | None = None
    sub: Stat | None = None
    ascension: int | None = None  # HoYoLAB promote_level, None if not sent


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
    icon: str = ""
    kind: int = 0  # HoYoLAB skill_type (1 normal, 2 skill, 3 burst; others as sent)


@dataclass
class Cons:
    name: str
    icon: str = ""
    active: bool = False
    pos: int = 0


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
    core_stats: list[Stat] = field(default_factory=list)  # HP, ATK, DEF, EM, Crit, ER + own-element DMG bonus
    cons: list[Cons] = field(default_factory=list)
    art_url: str = ""  # HoYoLAB character artwork URL (`image`), a candidate for the art tiers

    def icon_candidates(self) -> list[tuple[str, list[str]]]:
        items = [(self.icon, self.candidates)] if self.icon else []
        if self.weapon and self.weapon.icon:
            items.append((self.weapon.icon, _https(self.weapon.icon)))
        items += [(a.icon, _https(a.icon)) for a in self.artifacts if a.icon]
        return list(dict(items).items())

    def extra_icon_candidates(self) -> list[tuple[str, list[str]]]:
        """Talent, constellation and stat icons that HoYoLAB sends (used by the Build Card)."""
        urls = [t.icon for t in self.talents] + [c.icon for c in self.cons]
        urls += [s.icon for s in self.core_stats]
        for a in self.artifacts:
            urls += [s.icon for s in [a.main, *a.subs] if s]
        return [(u, _https(u)) for u in dict.fromkeys(u for u in urls if u)]

    @property
    def splash_key(self) -> str:
        return f"splash:{self.id}"

    def splash_candidates(self) -> list[tuple[str, list[str]]]:
        """Full-body splash art (Enka, then yatta), derived from the portrait name. Empty if the name is unknown."""
        return splash_for(self.candidates, self.splash_key)

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
                      "cons": [Cons(**c) for c in data.get("cons", [])],
                      "core_stats": [Stat(**x) for x in data.get("core_stats", [])],
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

        def icon_of(prop: Mapping[str, Any]) -> str:
            info = prop.get("info") or prop_map.get(str(prop.get("property_type"))) or {}
            return (_https(info.get("icon")) or [""])[0]

        def stat(prop: Any, key: str) -> Stat | None:
            if not prop:
                return None
            value = str(prop.get(key) or prop.get("value") or "")
            if not value:
                return None
            times = prop.get("times")
            return Stat(
                label(prop), value,
                times=num(times) if times is not None else None,
                base=str(prop.get("base") or ""), add=str(prop.get("add") or ""),
                prop=num((prop.get("info") or {}).get("property_type", prop.get("property_type"))),
                icon=icon_of(prop),
            )

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
                ascension=num(w["promote_level"]) if w.get("promote_level") is not None else None,
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

        talents = [Talent(str(s.get("name") or ""), num(s.get("level")), icon=(_https(s.get("icon")) or [""])[0], kind=num(s.get("skill_type")))
                   for s in entry.get("skills") or [] if num(s.get("level")) > 0 and s.get("name")][:4]
        cons = [Cons(str(c.get("name") or ""), (_https(c.get("icon")) or [""])[0], bool(c.get("is_actived")), num(c.get("pos")))
                for c in sorted(entry.get("constellations") or [], key=lambda x: num(x.get("pos")))]
        consts = [(str(c.get("name") or ""), bool(c.get("is_actived"))) for c in sorted(entry.get("constellations") or [], key=lambda x: num(x.get("pos")))]

        props = entry.get("selected_properties") or entry.get("base_properties") or []
        stats = [s for s in (stat(p, "final") for p in props) if s and s.value not in ("0", "0%", "0.0%")][:12]
        element = str(base.get("element") or "")
        # Stat block: HP, ATK, DEF, EM, CRIT Rate, CRIT DMG, ER, then the own-element DMG bonus. HoYoLAB spreads these over
        # base/selected/extra lists, so pick by name from all of them (first list that has it wins; base has base/add).
        pool = [x for lst in ("base_properties", "selected_properties", "extra_properties") for x in (stat(p, "final") for p in entry.get(lst) or []) if x]
        by_key: dict[str, Stat] = {}
        for st in pool:
            k = stat_key(st.name, st.value)
            if k in CORE_KEYS and k not in by_key:
                by_key[k] = st
        core = [by_key[k] for k in CORE_KEYS if k in by_key]
        # DMG bonus row: the character's own element if listed with a non-zero value (exact values, selection rule only)
        bonus = [s for s in (stat(p, "final") for p in entry.get("element_properties") or []) if s and s.value not in ("0", "0%", "0.0%")]
        own = next((s for s in bonus if element and element.lower() in s.name.lower()), None)
        if own:
            core.append(own)

        return cls(
            id=char_id, name=str(base.get("name") or ""), element=str(base.get("element") or ""),
            rarity=r - 100 if r > 100 else r, level=num(base.get("level"), 1),
            constellation=num(base.get("actived_constellation_num")) or sum(1 for _, on in consts if on),
            friendship=num(base.get("fetter")), icon=url or (cands[0] if cands else ""), candidates=cands,
            weapon=weapon, artifacts=arts, sets=sets, talents=talents, constellations=consts, stats=stats,
            core_stats=core, cons=cons, art_url=_https(base.get("image"))[0] if base.get("image") else "",
        )


def describe_raw(raw: Mapping[str, Any], char_id: int) -> str:
    """Safe shape summary for /debug: which fields HoYoLAB really sends (key names, counts and CDN file names only)."""
    import re

    entry = next((c for c in raw.get("list") or [] if str((c.get("base") or {}).get("id", c.get("id"))) == str(char_id)), None)
    if entry is None:
        return "character not in payload"

    def keys(x: Any) -> str:
        return ",".join(sorted(x.keys())) if isinstance(x, Mapping) else "-"

    def tail(url: Any) -> str:
        m = re.search(r"https?://([^/]+)/(.*)", str(url or ""))
        return f"{m.group(1)}/.../{m.group(2).rsplit('/', 1)[-1]}" if m else "-"

    base = entry.get("base") or {}
    rel = (entry.get("relics") or [{}])[0]
    lines = [
        f"entry keys: {keys(entry)}",
        f"base keys: {keys(base)}",
        f"base.image: {tail(base.get('image'))} | base.icon: {tail(base.get('icon'))}",
        f"weapon keys: {keys(entry.get('weapon'))}",
        f"relic keys: {keys(rel)}",
        f"relic main keys: {keys(rel.get('main_property'))}",
        f"relic sub[0] keys: {keys((rel.get('sub_property_list') or [{}])[0])}",
        f"substat 'times' present on all: {all('times' in p for r in entry.get('relics') or [] for p in r.get('sub_property_list') or [])}",
        f"skill keys: {keys((entry.get('skills') or [{}])[0])} | skill icon: {tail((entry.get('skills') or [{}])[0].get('icon'))}",
        f"constellation keys: {keys((entry.get('constellations') or [{}])[0])}",
        f"base_properties: {len(entry.get('base_properties') or [])} keys={keys((entry.get('base_properties') or [{}])[0])}",
        f"selected_properties: {len(entry.get('selected_properties') or [])} | element_properties: {len(entry.get('element_properties') or [])} | extra_properties: {len(entry.get('extra_properties') or [])}",
        f"prop info keys: {keys(((entry.get('base_properties') or [{}])[0]).get('info'))} | icon: {tail((((entry.get('base_properties') or [{}])[0]).get('info') or {}).get('icon'))}",
        f"property_map entries: {len(raw.get('property_map') or {})}",
    ]
    return "\n".join(lines)
