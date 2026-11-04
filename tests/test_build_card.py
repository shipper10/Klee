import io
from datetime import datetime, timezone

import pytest
from PIL import Image

from app.asset_manager import Assets, plan_character_art, stat_key, validate_art, art_key
from app.build_card.model import build_model
from app.build_card.template import H, W, render_character_build
from app.build_card.theme import THEMES, theme_for
from app.character import Artifact, CharacterDetail, Cons, Stat, Talent, Weapon, describe_raw
from tests.test_character import ICON, raw

NOW = datetime(2026, 11, 1, 12, 0, tzinfo=timezone.utc)


def png(w, h, color=(120, 60, 60, 255)) -> bytes:
    buf = io.BytesIO()
    Image.new("RGBA", (w, h), color).save(buf, "PNG")
    return buf.getvalue()


def full(element="Pyro", **kw) -> CharacterDetail:
    c = CharacterDetail(id=7, name="Tester", element=element, rarity=5, level=90, constellation=2, friendship=10,
                        icon=ICON, candidates=[ICON], art_url="https://x.hoyoverse.com/art.png")
    c.weapon = Weapon("Blade", 90, 5, 1, "https://x.hoyoverse.com/w.png", Stat("ATK", "674"), Stat("CRIT DMG", "22.1%"), 6)
    c.artifacts = [Artifact(i, "p", "Set A", 5, 20, f"https://x.hoyoverse.com/a{i}.png", Stat("HP", "4,780"),
                            [Stat("CRIT Rate", "6.6%", times=2), Stat("ATK", "23", times=1)]) for i in range(1, 6)]
    c.talents = [Talent("n", 9, "https://x.hoyoverse.com/t.png", 1), Talent("e", 9, "", 2), Talent("q", 6, "", 3)]
    c.cons = [Cons(f"c{i}", "", i <= 2, i) for i in range(1, 7)]
    c.core_stats = [Stat("Max HP", "18,182", base="13,103", add="+5,079"), Stat("ATK", "2,430"), Stat("CRIT Rate", "70.2%"),
                    Stat(f"{element} DMG Bonus", "46.6%")]
    for k, v in kw.items():
        setattr(c, k, v)
    return c


def render(c, icons=None):
    return Image.open(io.BytesIO(render_character_build(c, nickname="n", uid="123456789", server="os_asia", icons=icons or {},
                                                        fetched_at=NOW, source="live")))


# ---- data: what HoYoLAB sends vs what is left empty -------------------------------------------------------------
def test_parsing_keeps_times_base_add_and_icons_but_never_invents():
    r = raw()
    entry = r["list"][0]
    entry["selected_properties"][0].update({"base": "13,103", "add": "+5,079", "info": {"property_type": 2000, "name": "Max HP", "icon": "http://s/hp.png"}})
    entry["base_properties"] = [entry["selected_properties"][0]]
    entry["skills"][0]["icon"] = "http://s/skill.png"
    entry["constellations"][0]["icon"] = "http://s/c1.png"
    c = CharacterDetail.from_raw(r, 10000089)
    sub = c.artifacts[0].subs[0]
    assert sub.times == 2  # sent by HoYoLAB
    assert c.core_stats[0].base == "13,103" and c.core_stats[0].add == "+5,079" and c.core_stats[0].icon == "https://s/hp.png"
    assert c.talents[0].icon == "https://s/skill.png" and c.cons[0].icon == "https://s/c1.png" and c.cons[0].active
    assert c.weapon.ascension is None  # promote_level not in payload -> unknown, not guessed
    assert CharacterDetail.from_json(c.to_json()) == c


def test_missing_times_stay_none():
    r = raw()
    for rel in r["list"][0]["relics"]:
        for p in rel["sub_property_list"]:
            p.pop("times")
    c = CharacterDetail.from_raw(r, 10000089)
    assert all(s.times is None for a in c.artifacts for s in a.subs)
    assert all(sub.ticks is None for row in build_model(c).artifacts if row for sub in row.subs)


def test_own_element_bonus_selected_by_rule_only():
    r = raw()
    e = r["list"][0]
    e["base_properties"] = [{"property_type": 2000, "base": "1", "add": "0", "final": "35,000"}]
    e["element_properties"] = [{"property_type": 42, "final": "28.8%", "info": {"property_type": 42, "name": "Hydro DMG Bonus"}},
                               {"property_type": 40, "final": "46.6%", "info": {"property_type": 40, "name": "Pyro DMG Bonus"}}]
    c = CharacterDetail.from_raw(r, 10000089)  # Furina is Hydro
    assert c.core_stats[-1].name == "Hydro DMG Bonus"
    e["element_properties"] = [{"property_type": 40, "final": "46.6%", "info": {"property_type": 40, "name": "Pyro DMG Bonus"}}]
    assert "Pyro DMG Bonus" not in [s.name for s in CharacterDetail.from_raw(r, 10000089).core_stats]


def test_describe_raw_reports_shape_without_values():
    text = describe_raw(raw(), 10000089)
    assert "substat 'times' present on all: True" in text and "4,780" not in text and "Splendor" not in text  # CDN file names are shown on purpose (art URL patterns)


# ---- view model --------------------------------------------------------------------------------------------------
def test_model_shapes():
    m = build_model(full())
    assert len(m.artifacts) == 5 and m.sets == [("Set A", 4)] and m.weapon_max_level == 90
    assert m.stats[0].bonus == "+5,079" and m.stats[1].bonus == ""
    assert build_model(full(artifacts=full().artifacts[:2])).artifacts[2:] == [None, None, None]
    assert build_model(full(weapon=None)).weapon_name == ""


def test_weapon_max_level_only_when_ascension_known():
    c = full()
    c.weapon.ascension = None
    assert build_model(c).weapon_max_level is None
    c.weapon.ascension, c.weapon.rarity = 3, 2
    assert build_model(c).weapon_max_level is None  # 1-2 star weapons follow other caps: not guessed


# ---- assets ------------------------------------------------------------------------------------------------------
@pytest.mark.parametrize("name,value,key", [
    ("Max HP", "4,780", "hp"), ("HP", "9.3%", "hp_pct"), ("ATK", "311", "atk"), ("ATK%", "46.6%", "atk_pct"),
    ("DEF", "23", "def"), ("CRIT Rate", "3.9%", "crit_rate"), ("Energy Recharge", "5.2%", "er"),
    ("Pyro DMG Bonus", "46.6%", "element:Pyro"), ("Healing Bonus", "35.9%", "healing"), ("Something New", "1", None),
])
def test_stat_key(name, value, key):
    assert stat_key(name, value) == key


def test_art_validation_and_tier_order():
    c = full()
    plan = dict(plan_character_art(c))
    assert set(plan) == {art_key(7, "full"), art_key(7, "splash"), art_key(7, "icon")}
    assert validate_art(Image.new("RGBA", (2048, 1024)), "splash") and not validate_art(Image.new("RGBA", (300, 150)), "splash")
    assert not validate_art(Image.new("RGBA", (800, 400)), "full")  # landscape is not "full artwork"
    a = Assets(fetched={art_key(7, "full"): b"<html>not an image</html>", art_key(7, "splash"): png(2048, 1024), art_key(7, "icon"): png(256, 256)})
    assert a.art(c).tier == "splash"  # broken full art is skipped
    assert Assets(fetched={art_key(7, "icon"): png(256, 256)}).art(c).tier == "icon"
    none = Assets()
    assert none.art(c).tier == "none" and "art" in none.missing


def test_every_element_has_a_theme_and_a_bundled_icon():
    a = Assets()
    for el in THEMES:
        assert a.element(el, 20) is not None
    assert theme_for("???") is not THEMES["Pyro"]


# ---- full renders, including missing data and missing assets ----------------------------------------------------
@pytest.mark.parametrize("element", list(THEMES) + ["Unknown"])
def test_render_all_elements_without_any_downloaded_asset(element):
    img = render(full(element))
    assert img.size == (W, H)


def test_render_with_art_and_icons():
    icons = {art_key(7, "splash"): png(2048, 1024, (200, 90, 60, 255)), "https://x.hoyoverse.com/w.png": png(256, 256),
             "https://x.hoyoverse.com/t.png": png(80, 80)}
    icons.update({f"https://x.hoyoverse.com/a{i}.png": png(256, 256) for i in range(1, 6)})
    assert render(full(), icons).size == (W, H)


def test_render_degraded_data():
    assert render(full(weapon=None, artifacts=[], talents=[], cons=[], core_stats=[], sets=[])).size == (W, H)
    assert render(CharacterDetail(id=1, name="Bare", element="Geo")).size == (W, H)
    c = full()
    c.artifacts[0].subs = []
    c.artifacts[1].main = None
    assert render(c).size == (W, H)
    long = full(name="A Very Long Character Name That Should Shrink Instead Of Overflowing")
    long.weapon.name = "An Extremely Long Weapon Name Of Many Words Indeed"
    assert render(long).size == (W, H)


def test_asset_manager_records_missing_without_raising():
    a = Assets()
    assert a.stat_icon(Stat("Mystery", "1")) is None and a.icon("https://x/none.png") is None
    assert "stat:Mystery" in a.missing and "icon" in a.missing


# ---- real-payload shapes seen on a live account ----------------------------------------------------------------
def test_core_stats_picked_by_name_across_lists_and_stamina_excluded():
    r = raw()
    e = r["list"][0]
    pv = lambda t, name, final, base="0", add="0": {"property_type": t, "base": base, "add": add, "final": final, "info": {"property_type": t, "name": name}}
    e["base_properties"] = [pv(2000, "Max HP", "18182", "13103", "5079"), pv(2001, "ATK", "2430", "1016", "1414"), pv(2002, "DEF", "923", "765", "158"),
                            pv(28, "Elemental Mastery", "16"), pv(10, "Max Stamina", "240")]
    e["selected_properties"] = [pv(20, "CRIT Rate", "70.2%"), pv(22, "CRIT DMG", "236.9%")]
    e["extra_properties"] = [pv(23, "Energy Recharge", "109.1%")]
    e["element_properties"] = [pv(40, "Pyro DMG Bonus", "46.6%"), pv(42, "Hydro DMG Bonus", "28.8%")]
    c = CharacterDetail.from_raw(r, 10000089)  # Hydro
    names = [s.name for s in c.core_stats]
    assert names == ["Max HP", "ATK", "DEF", "Elemental Mastery", "CRIT Rate", "CRIT DMG", "Energy Recharge", "Hydro DMG Bonus"]
    assert "Max Stamina" not in names and c.core_stats[0].base == "13103"


def test_number_formatting_is_pure_formatting():
    from app.stats import group_digits, with_plus
    assert group_digits("18182") == "18,182" and group_digits("+5079") == "+5,079" and group_digits("46.6%") == "46.6%"
    assert group_digits("4,780") == "4,780" and with_plus("23") == "+23" and with_plus("21.0%") == "+21.0%" and with_plus("+5") == "+5"
    c = full(core_stats=[Stat("Max HP", "18182", base="13103", add="5079")])
    c.artifacts[0].main = Stat("HP", "4780")
    c.artifacts[0].subs = [Stat("CRIT DMG", "21.0%", times=3)]
    m = build_model(c)
    assert m.stats[0].value == "18,182" and m.stats[0].base == "13,103" and m.stats[0].bonus == "+5,079"
    assert m.artifacts[0].main_value == "4,780" and m.artifacts[0].subs[0].value == "+21.0%"


def test_long_weapon_name_wraps_and_renders():
    c = full()
    c.weapon.name = "Crimson Moon's Semblance"
    assert render(c).size == (W, H)
