import io
from datetime import datetime, timezone

from PIL import Image

from app import bot
from app.genshin_provider import Report
from app.linking import utcnow
from app.render_stygian import render_stygian_card
from app.stygian import StygianData, clean
from tests.test_abyss_flow import ACCOUNT, ctx, provider
from tests.test_render_abyss import _icon

NOW = datetime(2026, 11, 1, 12, 0, tzinfo=timezone.utc)
TS = 3500
IMG = "https://act-webstatic.hoyoverse.com/game_record/genshin/character_icon/UI_AvatarIcon_{}.png"


def team(n=4):
    return [{"avatar_id": 10000002 + i, "name": f"C{i}", "element": "Cryo", "image": IMG.format(f"C{i}"), "level": 90 - i,
             "rarity": 5 if i == 0 else 4, "rank": i} for i in range(n)]


def challenge(name):
    return {"name": name, "second": 301, "teams": team(),
            "best_avatar": [{"avatar_id": 10000003, "side_icon": IMG.format("Side_Jean"), "dps": "123456", "type": 1},
                            {"avatar_id": 10000004, "side_icon": IMG.format("Side_Lisa"), "dps": "999999", "type": 2}],
            "monster": {"monster_id": 1, "name": "Big <b>Boss</b>", "level": 100,
                        "desc": ["{SPRITE_PRESET#11001} Cryo <color=#fff>resist</color> up", "", "Second note"], "tags": []}}


def season(start, end, name, with_mp=False):
    return {"schedule": {"schedule_id": start, "name": name, "start_time": str(start), "end_time": str(end), "is_valid": True},
            "single": {"best": {"difficulty": 5, "second": 180, "icon": "a,b.png"}, "challenge": [challenge("Round 1"), challenge("Round 2")], "has_data": True},
            "mp": {"best": None, "challenge": [challenge("Co-op")] if with_mp else [], "has_data": with_mp}}


RAW = [season(3000, 4000, "Season B", with_mp=True), season(1000, 2000, "Season A")]


def render(data, multi=False, **kw):
    icons = {u: _icon(u) for u, _ in data.icon_candidates()}
    args = dict(nickname="shipper", icons=icons, multi=multi, tz_hours=8, fetched_at=NOW, source="live")
    args.update(kw)
    return render_stygian_card(data, **args)


def test_parse_current_and_previous():
    cur = StygianData.from_raw(RAW, now=TS)
    assert cur.found and cur.season == "Season B" and cur.single.has_data and cur.multi.has_data
    c = cur.single.challenges[0]
    assert c.seconds == 301 and len(c.team) == 4 and c.team[0].rarity == 5 and c.team[1].constellation == 1
    assert [b.value for b in c.best] == ["123456", "999999"] and c.enemy_name == "Big Boss"
    assert c.enemy_notes == ["Cryo resist up", "Second note"]
    assert cur.single.best_difficulty == 5 and cur.single.best_seconds == 180
    prev = StygianData.from_raw(RAW, previous=True, now=TS)
    assert prev.season == "Season A" and not prev.multi.has_data
    assert not StygianData.from_raw(RAW, now=9999).found  # between seasons: nothing current
    assert StygianData.from_raw(RAW, previous=True, now=9999).season == "Season B"
    assert StygianData.from_json(cur.to_json()) == cur


def test_lenient_and_wrapped_payload():
    for payload in ([], {}, {"data": []}, [{}], [{"schedule": {}}]):
        d = StygianData.from_raw(payload)
        assert StygianData.from_json(d.to_json()) == d
    assert StygianData.from_raw({"data": RAW}, now=TS).season == "Season B"
    assert clean("<a>x</a> {B} y") == "x y"


def test_render():
    d = StygianData.from_raw(RAW, now=TS)
    img = Image.open(io.BytesIO(render(d)))
    assert img.width == 1080 and img.width + img.height < 10000
    assert render(d) == render(d)
    render(d, multi=True)
    render(d, icons={})
    render(StygianData.from_raw(RAW, previous=True, now=TS), nickname="N" * 80)


async def test_provider_caches_per_period(monkeypatch):
    p = provider()
    calls = []

    async def fake(account, previous=False):
        calls.append(previous)
        return StygianData.from_raw(RAW, previous=previous, now=TS)

    monkeypatch.setattr(p, "_fetch_stygian", fake)
    assert (await p.get_stygian(ACCOUNT)).data.season == "Season B"
    assert (await p.get_stygian(ACCOUNT)).source == "cached"
    assert (await p.get_stygian(ACCOUNT, previous=True)).data.season == "Season A" and calls == [False, True]


class Prov:
    def __init__(self, data):
        self.data = data

    async def get_stygian(self, account, previous=False):
        return Report(self.data, utcnow(), "live")


async def test_send_stygian_flows():
    d = StygianData.from_raw(RAW, now=TS)
    c = ctx(Prov(d))
    await bot._send_stygian(c, 1, 501, ACCOUNT, multi=False, previous=False)
    await bot._send_stygian(c, 1, 502, ACCOUNT, multi=True, previous=False)
    assert len(c.bot.photos) == 2 and "single" in c.bot.photos[0][2] and "co-op" in c.bot.photos[1][2]

    c2 = ctx(Prov(StygianData()))
    await bot._send_stygian(c2, 1, 503, ACCOUNT, multi=False, previous=False)
    assert "/stygian previous" in c2.bot.messages[0][1]

    prev = StygianData.from_raw(RAW, previous=True, now=TS)  # no co-op data that season
    c3 = ctx(Prov(prev))
    await bot._send_stygian(c3, 1, 504, ACCOUNT, multi=True, previous=True)
    assert "co-op" in c3.bot.messages[0][1] and not c3.bot.photos
