import io
import os
from datetime import datetime, timezone

from PIL import Image, ImageDraw

from app.abyss import AbyssData, Chamber, Char, Floor, Stat
from app.render_abyss import render_abyss_card, select_floors

FETCHED = datetime(2026, 10, 31, 10, 0, tzinfo=timezone.utc)
T0 = 1792242330  # 2026-10-17 ~14:45 UTC+8


def _icon(url: str) -> bytes:
    seed = sum(map(ord, url))
    im = Image.new("RGBA", (160, 160), (seed % 200 + 30, (seed * 3) % 200 + 30, (seed * 7) % 200 + 30, 255))
    ImageDraw.Draw(im).ellipse((40, 20, 120, 100), fill=(255, 255, 255, 200))
    buf = io.BytesIO()
    im.save(buf, "PNG")
    return buf.getvalue()


def team(prefix: str, levels=(90, 90, 80, 90), rarity=(5, 5, 5, 4)) -> list[Char]:
    return [Char(icon=f"https://x.hoyoverse.com/{prefix}{i}.png", level=lv, rarity=r) for i, (lv, r) in enumerate(zip(levels, rarity))]


def floor(n: int, stars=9) -> Floor:
    return Floor(
        number=n, stars=stars, max_stars=9,
        chambers=[Chamber(number=c, stars=3, timestamp=T0 + c * 200, first_half=team(f"a{n}{c}"), second_half=team(f"b{n}{c}")) for c in (1, 2, 3)],
    )


def sample(**over) -> AbyssData:
    base = dict(
        period_start=1792166400, period_end=1794844800, total_stars=36, max_floor="12-3", total_battles=6,
        most_played=[Char(icon=f"https://x.hoyoverse.com/m{i}.png", rarity=5, value=6) for i in range(4)],
        stats=[Stat("most_kills", 19), Stat("strongest_strike", 239459), Stat("most_damage_taken", 34448),
               Stat("most_bursts_used", 17), Stat("most_skills_used", 33)],
        floors=[floor(9), floor(10), floor(11), floor(12)],
    )
    base.update(over)
    return AbyssData(**base)


def render(data=None, *, with_icons=True, only_floor=None, **kw):
    data = data or sample()
    icons = {u: _icon(u) for u in data.icon_urls()} if with_icons else {}
    args = dict(nickname="shipper", icons=icons, floors=select_floors(data, only_floor), tz_hours=8,
                fetched_at=FETCHED, source="live")
    args.update(kw)
    return render_abyss_card(data, **args)


def test_png_dimensions_and_sample_output():
    png = render()
    img = Image.open(io.BytesIO(png))
    assert img.width == 1080 and 2500 < img.height < 6000
    assert img.width + img.height < 10000  # Telegram photo limit
    assert len(png) < 5_000_000
    out = os.environ.get("KLEE_SAMPLE_OUT_ABYSS")
    if out:
        with open(out, "wb") as f:
            f.write(png)


def test_deterministic():
    assert render() == render()


def test_default_shows_two_highest_floors_and_floor_filter():
    data = sample()
    assert [f.number for f in select_floors(data, None)] == [11, 12]
    assert [f.number for f in select_floors(data, 10)] == [10]
    assert select_floors(data, 1) == []


def test_missing_icons_use_placeholders():
    png = render(with_icons=False)
    assert Image.open(io.BytesIO(png)).format == "PNG"


def test_corrupt_icon_does_not_crash():
    data = sample()
    icons = {u: b"not an image" for u in data.icon_urls()}
    render_abyss_card(data, nickname="x", icons=icons, floors=select_floors(data, None), tz_hours=8,
                      fetched_at=FETCHED, source="cached")


def test_edge_cases():
    # no battle data at all
    empty = sample(total_stars=0, total_battles=0, most_played=[], stats=[], floors=[])
    assert not empty.has_data
    render(empty, floors=[])
    # one-character halves, unplayed chamber, very long nickname, stale source
    odd = sample(floors=[Floor(12, 3, 9, [Chamber(1, 0, None, [Char("u1", 90, 5)], [])])])
    render(odd, nickname="N" * 90, source="stale")


def test_json_roundtrip():
    d = sample()
    assert AbyssData.from_json(d.to_json()) == d


def test_from_genshin_conversion(monkeypatch):
    """Uses genshin.py's own pydantic models with a payload shaped like the real API."""
    from genshin.models import SpiralAbyss
    from genshin.models.genshin import constants as gc

    # In production genshin.py downloads the character table on the first request; here an empty one is enough.
    monkeypatch.setitem(gc.CHARACTER_NAMES, "en-us", {})

    def av(i, lvl=90):
        return {"id": 10000000 + i, "level": lvl, "rarity": 5, "element": "Pyro", "icon": f"https://x.hoyoverse.com/{i}.png", "name": f"C{i}"}

    raw = {
        "schedule_id": 150, "start_time": "1792166400", "end_time": "1794844800", "total_battle_times": 6,
        "total_win_times": 6, "max_floor": "12-3", "total_star": 36, "is_unlock": True,
        "reveal_rank": [{"avatar_id": 10000001, "avatar_icon": "https://x.hoyoverse.com/1.png", "value": 6, "rarity": 5, "element": "Pyro", "name": "C1"}],
        "defeat_rank": [{"avatar_id": 10000002, "avatar_icon": "https://x.hoyoverse.com/2.png", "value": 19, "rarity": 5, "element": "Pyro", "name": "C2"}],
        "damage_rank": [], "take_damage_rank": [], "energy_skill_rank": [], "normal_skill_rank": [],
        "floors": [{"index": 12, "star": 9, "max_star": 9, "is_unlock": True, "levels": [
            {"index": 1, "star": 3, "max_star": 3, "battles": [
                {"index": 1, "timestamp": "1792242349", "avatars": [av(1), av(2, 80)]},
                {"index": 2, "timestamp": "1792242500", "avatars": [av(3)]}]}]}],
        "daily_reward": 0, "damage_rank_list": [],
    }
    model = SpiralAbyss(**raw)
    data = AbyssData.from_genshin(model)
    assert data.total_stars == 36 and data.max_floor == "12-3" and data.total_battles == 6
    ch = data.floors[0].chambers[0]
    assert [c.level for c in ch.first_half] == [90, 80] and len(ch.second_half) == 1
    assert ch.timestamp == 1792242500
    assert data.stats[0].key == "most_kills" and data.stats[0].value == 19


def test_icon_url_allowlist():
    from app.images import is_allowed_url

    assert is_allowed_url("https://enka.network/ui/UI_AvatarIcon_Furina.png")  # what genshin.py produces
    assert is_allowed_url("https://act-webstatic.hoyoverse.com/x.png")
    assert not is_allowed_url("http://enka.network/ui/x.png")  # https only
    assert not is_allowed_url("https://evil.example.com/x.png")
    assert not is_allowed_url("https://enka.network.evil.com/x.png")
    assert not is_allowed_url("https://nothoyoverse.com/x.png")
    assert not is_allowed_url("file:///etc/passwd")
