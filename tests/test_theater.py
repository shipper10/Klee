import io
from datetime import datetime, timezone

from PIL import Image

from app import bot
from app.genshin_provider import Report
from app.linking import utcnow
from app.render_theater import render_theater_card, select_acts
from app.theater import TheaterData
from tests.test_abyss_flow import ACCOUNT, ctx, provider
from tests.test_render_abyss import _icon

NOW = datetime(2026, 11, 1, 12, 0, tzinfo=timezone.utc)
HOYO = "https://act-webstatic.hoyoverse.com/game_record/genshin/character_icon/UI_AvatarIcon_{}.png"


def av(name, level=90, kind=1, rarity=5):
    return {"avatar_id": 10000002, "avatar_type": kind, "level": level, "image": HOYO.format(name), "rarity": rarity}


def raw(acts=10, with_stats=True):
    rounds = [{"round_id": i, "is_get_medal": i % 2 == 0, "finish_time": 1792242349 + i * 600, "is_tarot": False,
               "avatars": [av(f"A{i}"), av(f"B{i}", 80, 2, 4), av(f"C{i}", 90, 3), av("Shenhe", 70, 1, 105)],
               "buffs": [{"name": "Boom One"}, {"name": "Boom Two"}], "choice_cards": [{"name": "Cache"}]}
              for i in range(1, acts + 1)]
    fight = {"max_defeat_avatar": {"avatar_id": 1, "avatar_icon": HOYO.format("Furina"), "value": "55", "rarity": 5},
             "max_damage_avatar": {"avatar_id": 0}, "max_take_damage_avatar": None,
             "shortest_avatar_list": [], "total_use_time": 754} if with_stats else {}
    return {"is_unlock": True, "data": [{"has_data": True, "has_detail_data": True,
            "stat": {"difficulty_id": 4, "max_round_id": acts, "medal_num": 5, "coin_num": 12, "avatar_bonus_num": 3, "rent_cnt": 2},
            "schedule": {"start_time": "1790000000", "end_time": "1792600000"},
            "detail": {"rounds_data": rounds, "backup_avatars": [], "fight_statisic": fight}}]}


def render(data, show_all=False, **kw):
    acts = select_acts(data, show_all)
    icons = {u: _icon(u) for u, _ in data.icon_candidates()}
    args = dict(nickname="shipper", icons=icons, acts=acts, tz_hours=8, fetched_at=NOW, source="live")
    args.update(kw)
    return render_theater_card(data, **args)


def test_from_raw_parses_fields_and_ignores_empty_stats():
    d = TheaterData.from_raw(raw())
    assert d.unlocked and d.has_data and d.difficulty_name == "Visionary" and d.best_act == 10 and d.medals == 5
    assert [s.key for s in d.stats] == ["most_defeats"] and d.stats[0].char.value == 55
    a = d.acts[0]
    assert [c.kind for c in a.characters] == [1, 2, 3, 1] and a.characters[3].rarity == 5 and a.booms == ["Boom One", "Boom Two"]
    assert a.characters[0].candidates[0].startswith("https://enka.network/ui/")
    assert TheaterData.from_json(d.to_json()) == d


def test_from_raw_is_lenient():
    for payload in ({}, {"data": []}, {"is_unlock": True, "data": [{}]}, {"data": [{"detail": {"rounds_data": [{}]}}]}):
        d = TheaterData.from_raw(payload)
        assert TheaterData.from_json(d.to_json()) == d
    assert not TheaterData.from_raw({"is_unlock": True, "data": [{"has_data": True}]}).has_data


def test_render_sizes_and_defaults():
    d = TheaterData.from_raw(raw())
    assert [a.number for a in select_acts(d, False)] == [10, 9, 8, 7] and len(select_acts(d, True)) == 10
    full = Image.open(io.BytesIO(render(d, True)))
    short = Image.open(io.BytesIO(render(d)))
    assert full.width == 1080 and full.width + full.height < 10000 and short.height < full.height
    assert render(d) == render(d)
    render(TheaterData.from_raw(raw(3, with_stats=False)), icons={})
    render(TheaterData.from_raw(raw(1)), nickname="N" * 80)


async def test_provider_caches_theater(monkeypatch):
    p = provider()
    calls = []

    async def fake(account):
        calls.append(1)
        return TheaterData.from_raw(raw(2))

    monkeypatch.setattr(p, "_fetch_theater", fake)
    assert (await p.get_theater(ACCOUNT)).source == "live"
    assert (await p.get_theater(ACCOUNT)).source == "cached" and len(calls) == 1


class Prov:
    def __init__(self, data):
        self.data = data

    async def get_theater(self, account):
        return Report(self.data, utcnow(), "live")


async def test_send_theater_flows():
    c = ctx(Prov(TheaterData.from_raw(raw(6))))
    await bot._send_theater(c, 1, 401, ACCOUNT, show_all=False)
    assert c.bot.photos[0][1][:4] == b"\x89PNG" and "Imaginarium" in c.bot.photos[0][2]
    for n, data, text in ((402, TheaterData(), "not unlocked"), (403, TheaterData(unlocked=True), "No Imaginarium")):
        c2 = ctx(Prov(data))
        await bot._send_theater(c2, 1, n, ACCOUNT, show_all=False)
        assert text in c2.bot.messages[0][1] and not c2.bot.photos
