import io
from datetime import datetime, timezone

from PIL import Image

from app import bot
from app.character import CharacterDetail
from app.genshin_provider import Report
from app.linking import utcnow
from app.profile import ProfChar, ProfileData, find_characters
from app.render_character import render_character_card
from tests.test_abyss_flow import ACCOUNT, ctx, provider
from tests.test_render_abyss import _icon

NOW = datetime(2026, 11, 1, 12, 0, tzinfo=timezone.utc)
PROPS = {str(i): {"property_type": i, "name": n, "icon": "", "filter_name": n} for i, n in
         {2000: "Max HP", 2001: "ATK", 20: "CRIT Rate", 22: "CRIT DMG", 23: "Energy Recharge", 40: "Pyro DMG Bonus", 28: "Elemental Mastery"}.items()}
ICON = "https://act-webstatic.hoyoverse.com/game_record/genshin/character_icon/UI_AvatarIcon_Furina.png"


def pv(t, final, base="0", add="0"):
    return {"property_type": t, "base": base, "add": add, "final": final}


def raw(char_id=10000089):
    relics = [{"id": i, "icon": f"http://act-webstatic.hoyoverse.com/relic{i}.png", "name": f"Piece {i}", "pos_name": "x", "pos": i,
               "rarity": 5, "level": 20, "set": {"id": 1, "name": "Golden Troupe", "affixes": []},
               "main_property": {"value": "4,780", "times": 0, "property_type": 2000},
               "sub_property_list": [{"value": "10.5%", "times": 2, "property_type": 20}, {"value": "21.0%", "times": 3, "property_type": 22},
                                     {"value": "40", "times": 1, "property_type": 28}, {"value": "5.2%", "times": 1, "property_type": 23}]}
              for i in (3, 1, 2, 5, 4)]
    entry = {"base": {"id": char_id, "name": "Furina", "element": "Hydro", "rarity": 5, "icon": ICON, "image": ICON, "level": 90,
                      "fetter": 10, "actived_constellation_num": 2},
             "weapon": {"id": 1, "icon": "https://x.hoyoverse.com/w.png", "name": "Splendor of Tranquil Waters", "rarity": 5, "level": 90,
                        "type": 1, "affix_level": 1, "main_property": pv(2001, "542"), "sub_property": pv(20, "44.1%")},
             "relics": relics,
             "constellations": [{"id": i, "icon": "", "pos": i, "name": f"Const {i}", "effect": "", "is_actived": i <= 2} for i in range(1, 7)],
             "skills": [{"skill_id": 1, "skill_type": 1, "name": "Normal Attack", "level": 9}, {"skill_id": 2, "skill_type": 2, "name": "Salon", "level": 11},
                        {"skill_id": 3, "skill_type": 2, "name": "Passive", "level": 0}],
             "selected_properties": [pv(2000, "35,000"), pv(2001, "1,900"), pv(20, "75.5%"), pv(22, "210.2%"), pv(23, "120.0%"), pv(40, "0%")]}
    return {"list": [entry, {"base": {"id": 1, "name": "Other"}}], "property_map": PROPS}


def test_from_raw_parses_everything_and_hides_empty_stats():
    c = CharacterDetail.from_raw(raw(), 10000089)
    assert c.name == "Furina" and c.level == 90 and c.constellation == 2 and c.friendship == 10 and c.rarity == 5
    assert c.weapon.name.startswith("Splendor") and c.weapon.main.name == "ATK" and c.weapon.sub.value == "44.1%"
    assert [a.slot for a in c.artifacts] == [1, 2, 3, 4, 5] and c.artifacts[0].icon.startswith("https://")
    assert c.artifacts[0].main.name == "Max HP" and [s.name for s in c.artifacts[0].subs][:2] == ["CRIT Rate", "CRIT DMG"]
    assert c.sets == ["Golden Troupe (4)"]
    assert [t.name for t in c.talents] == ["Normal Attack", "Salon"]  # level-0 passives skipped
    assert sum(on for _, on in c.constellations) == 2
    assert "Pyro DMG Bonus" not in [s.name for s in c.stats] and c.stats[0].name == "Max HP"
    assert c.candidates[0].startswith("https://enka.network/ui/")
    assert CharacterDetail.from_json(c.to_json()) == c


def test_from_raw_missing_character_and_lenient():
    assert CharacterDetail.from_raw(raw(), 424242) is None
    assert CharacterDetail.from_raw({}, 1) is None
    d = CharacterDetail.from_raw({"list": [{"base": {"id": 7}}]}, 7)
    assert d is not None and d.weapon is None and d.artifacts == []
    assert CharacterDetail.from_json(d.to_json()) == d


def render(c, **kw):
    args = dict(nickname="shipper", uid="712345678", server="os_asia", icons={u: _icon(u) for u, _ in c.icon_candidates()},
                fetched_at=NOW, source="live")
    args.update(kw)
    return render_character_card(c, **args)


def test_render_and_edge_cases():
    c = CharacterDetail.from_raw(raw(), 10000089)
    img = Image.open(io.BytesIO(render(c)))
    assert img.width == 1080 and img.width + img.height < 10000
    assert render(c) == render(c)
    render(c, icons={}, nickname="N" * 80)
    render(CharacterDetail.from_raw({"list": [{"base": {"id": 7}}]}, 7))


def profile():
    return ProfileData(characters=[ProfChar("Furina", ICON, id=10000089, rarity=5, level=90), ProfChar("Kamisato Ayaka", "a", id=2, rarity=5, level=90),
                                   ProfChar("Kamisato Ayato", "b", id=3, rarity=5, level=80), ProfChar("Xingqiu", "c", id=4, level=70)])


def test_find_characters_matching_rules():
    p = profile()
    assert [c.name for c in find_characters(p, "furina")] == ["Furina"]
    assert [c.name for c in find_characters(p, "Kamisato Ayaka")] == ["Kamisato Ayaka"]
    assert len(find_characters(p, "kamisato")) == 2
    assert [c.name for c in find_characters(p, "xing qiu")] == ["Xingqiu"]
    assert find_characters(p, "") == [] and find_characters(p, "zzz") == []


async def test_provider_caches_character(monkeypatch):
    p = provider()
    calls = []

    async def fake(account, char_id):
        calls.append(char_id)
        return CharacterDetail.from_raw(raw(char_id), char_id)

    monkeypatch.setattr(p, "_fetch_character", fake)
    assert (await p.get_character(ACCOUNT, 10000089)).source == "live"
    assert (await p.get_character(ACCOUNT, 10000089)).source == "cached" and calls == [10000089]


class Prov:
    async def get_profile(self, account):
        return Report(profile(), utcnow(), "live")

    async def get_character(self, account, char_id):
        return Report(CharacterDetail.from_raw(raw(char_id), char_id), utcnow(), "live")


async def test_send_character_flows():
    c = ctx(Prov())
    await bot._send_character(c, 1, 601, ACCOUNT, "furina")
    assert c.bot.photos and c.bot.photos[0][2].startswith("Furina")
    for n, q, text in ((602, "", "Your top characters"), (603, "nobody", "could not find"), (604, "kamisato", "Several characters")):
        c2 = ctx(Prov())
        await bot._send_character(c2, 1, n, ACCOUNT, q)
        assert text in c2.bot.messages[0][1] and not c2.bot.photos


def test_splash_candidates_and_showcase_render():
    from app.render_showcase import render_character_showcase

    c = CharacterDetail.from_raw(raw(), 10000089)
    (key, urls), = c.splash_candidates()
    assert key == c.splash_key and urls[0] == "https://enka.network/ui/UI_Gacha_AvatarImg_Furina.png" and "yatta" in urls[1]
    icons = {u: _icon(u) for u, _ in c.icon_candidates()}
    for with_splash in (True, False):
        ic = dict(icons)
        if with_splash:
            buf = io.BytesIO()
            Image.new("RGB", (2048, 1024), (50, 80, 150)).save(buf, "PNG")
            ic[c.splash_key] = buf.getvalue()
        png = render_character_showcase(c, nickname="x", uid="700000001", server="os_euro", icons=ic, fetched_at=NOW, source="live")
        Image.open(io.BytesIO(png)).verify()
    # no icons at all and sparse data must not crash
    sparse = CharacterDetail(id=1, name="X", element="Weird")
    Image.open(io.BytesIO(render_character_showcase(sparse, nickname="", uid="1", server="os_euro", icons={}, fetched_at=NOW, source="cached"))).verify()


def test_showcase_style_only_for_character_and_selectable():
    from app.styles import is_valid, pick

    assert is_valid("character", "showcase") and not is_valid("zzz", "showcase")
    rows = [{"user_id": 5, "service": "*", "style": "showcase"}]
    assert pick(rows, 5, "character") == "showcase"
    assert pick(rows, 5, "zzz") == "classic"  # a layout the service does not have falls back
