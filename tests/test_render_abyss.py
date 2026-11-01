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


def _raw_payload():
    """Shaped like the real `spiralAbyss` response (field names = genshin.py's model aliases)."""
    hoyo = "https://act-webstatic.hoyoverse.com/game_record/genshin/character_icon/UI_AvatarIcon_{}.png"

    def av(name, lvl=90, rarity=5):
        return {"id": 10000001, "level": lvl, "rarity": rarity, "element": "Pyro", "icon": hoyo.format(name)}

    return {
        "schedule_id": 150, "start_time": "1792166400", "end_time": "1794844800", "total_battle_times": 6,
        "total_win_times": 6, "max_floor": "12-3", "total_star": 36, "is_unlock": True,
        "reveal_rank": [{"avatar_id": 1, "avatar_icon": hoyo.format("Furina"), "value": 6, "rarity": 5}],
        "defeat_rank": [{"avatar_id": 2, "avatar_icon": hoyo.format("Nilou"), "value": 19, "rarity": 5}],
        "damage_rank": [], "take_damage_rank": [], "energy_skill_rank": [], "normal_skill_rank": [],
        "floors": [{"index": 12, "star": 9, "max_star": 9, "is_unlock": True, "levels": [
            {"index": 1, "star": 3, "max_star": 3, "battles": [
                {"index": 1, "timestamp": "1792242349", "avatars": [av("Columbina"), av("Nefer", 80), av("Yelan", 90, 105)]},
                {"index": 2, "timestamp": "1792242500", "avatars": [av("Shenhe", 70, 4)]}]}]}],
    }


def test_from_raw_keeps_original_icon_urls_and_adds_fallback():
    data = AbyssData.from_raw(_raw_payload())
    assert data.total_stars == 36 and data.max_floor == "12-3" and data.total_battles == 6
    ch = data.floors[0].chambers[0]
    assert [c.level for c in ch.first_half] == [90, 80, 90] and len(ch.second_half) == 1
    assert ch.timestamp == 1792242500 and ch.stars == 3
    first = ch.first_half[0]
    assert first.icon == "https://act-webstatic.hoyoverse.com/game_record/genshin/character_icon/UI_AvatarIcon_Columbina.png"
    cands = first.candidates
    assert cands[0] == "https://enka.network/ui/UI_AvatarIcon_Columbina.png"
    assert cands[-1] == first.icon  # HoYoLAB's own URL is the last resort
    assert any(c.startswith("https://gi.yatta.moe/") for c in cands)
    assert ch.first_half[2].rarity == 5  # collaboration characters are stored as 105
    assert data.stats[0].key == "most_kills" and data.stats[0].value == 19
    assert data.most_played[0].value == 6 and "Furina" in data.most_played[0].icon
    assert data.icon_candidates()[0][1][0].startswith("https://enka.network/ui/")


def test_from_raw_is_lenient_about_missing_fields():
    data = AbyssData.from_raw({})
    assert data.total_stars == 0 and data.floors == [] and not data.has_data
    odd = AbyssData.from_raw({"floors": [{"index": 3, "levels": [{"index": 1, "battles": [{"index": 1, "avatars": [{}]}]}]}]})
    assert odd.floors[0].chambers[0].first_half[0].icon == ""
    assert AbyssData.from_json(odd.to_json()) == odd


def test_icon_candidates_handles_odd_urls(monkeypatch):
    from app.abyss import icon_candidates

    assert icon_candidates("", 0) == []
    assert icon_candidates("https://x.com/a.png") == ["https://x.com/a.png"]
    side = icon_candidates("https://x.com/UI_AvatarIcon_Side_Ayaka.png")
    assert side[0] == "https://enka.network/ui/UI_AvatarIcon_Ayaka.png"
    assert icon_candidates("http://x.com/UI_AvatarIcon_Ayaka.png")[-1] == "https://x.com/UI_AvatarIcon_Ayaka.png"
    monkeypatch.setattr("app.abyss._icon_name_for_id", lambda i: "Ayaka" if i == 7 else "")
    by_id = icon_candidates("https://x.com/UI_AvatarIcon_Side_Other.png", 7)
    assert by_id[0] == "https://enka.network/ui/UI_AvatarIcon_Ayaka.png"
    assert "https://enka.network/ui/UI_AvatarIcon_Other.png" in by_id


def test_icon_url_allowlist():
    from app.images import is_allowed_url

    assert is_allowed_url("https://enka.network/ui/UI_AvatarIcon_Furina.png")  # what genshin.py produces
    assert is_allowed_url("https://act-webstatic.hoyoverse.com/x.png")
    assert not is_allowed_url("http://enka.network/ui/x.png")  # https only
    assert not is_allowed_url("https://evil.example.com/x.png")
    assert not is_allowed_url("https://enka.network.evil.com/x.png")
    assert not is_allowed_url("https://nothoyoverse.com/x.png")
    assert not is_allowed_url("file:///etc/passwd")
