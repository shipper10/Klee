

def test_official_render_always_has_summary_and_handles_missing():
    import io
    from datetime import datetime, timezone
    from PIL import Image
    from app.abyss import AbyssData, Chamber, Char, Floor, Stat
    from app.render_abyss_official import render_abyss_official

    ch = Char(icon="x", level=90, rarity=5, value=3, candidates=[])
    chamber = Chamber(number=1, stars=3, timestamp=1792000000, first_half=[ch], second_half=[])
    one = [Floor(number=12, stars=9, max_stars=9, chambers=[chamber])]
    data = AbyssData(period_start=1792000000, period_end=1794600000, total_stars=36, max_floor="12-3", total_battles=6,
                     most_played=[ch], stats=[Stat("most_kills", 5, "x")], floors=one)
    now = datetime.now(timezone.utc)
    png = render_abyss_official(data, nickname="a", icons={}, floors=one, tz_hours=3, fetched_at=now, source="live")
    assert Image.open(io.BytesIO(png)).size[1] > 900  # summary + floor
    empty = AbyssData(period_start=None, period_end=None, total_stars=0, max_floor="", total_battles=0, most_played=[], stats=[], floors=one)
    assert render_abyss_official(empty, nickname="", icons={}, floors=one, tz_hours=0, fetched_at=now, source="cached")
