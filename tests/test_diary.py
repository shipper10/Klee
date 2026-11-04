import io
from datetime import datetime, timezone

from PIL import Image

from app.diary import DiaryData, month_for
from app.render_diary_official import render_diary_official

RAW = {
    "uid": 700000001, "region": "os_euro", "nickname": "shipper", "data_month": 10,
    "month_data": {
        "current_primogems": 21500, "current_mora": 3200000, "last_primogems": 18000, "last_mora": 3500000,
        "primogem_rate": 19, "mora_rate": -8,
        "group_by": [
            {"action_id": 1, "action": "Daily Commissions", "num": 6000, "percent": 28},
            {"action_id": 2, "action": "Events", "num": 9000, "percent": 42},
            {"action_id": 3, "action": "Spiral Abyss", "num": 6500, "percent": 30},
        ],
    },
    "day_data": {"current_primogems": 60, "current_mora": 12000},
}
NOW = datetime(2026, 11, 2, 12, 0, tzinfo=timezone.utc)


def test_parse_and_roundtrip():
    d = DiaryData.from_raw(RAW)
    assert d.found and d.primogems == 21500 and d.mora_rate == -8 and d.today_mora == 12000
    assert [c.name for c in d.categories] == ["Events", "Spiral Abyss", "Daily Commissions"]
    assert DiaryData.from_json(d.to_json()) == d


def test_missing_data_is_not_found():
    assert not DiaryData.from_raw({}).found


def test_month_for_wraps_and_uses_server_time():
    assert month_for(8, False, datetime(2026, 11, 30, 20, 0, tzinfo=timezone.utc)) == (2026, 12)  # already Dec 1 in UTC+8
    assert month_for(8, True, datetime(2026, 1, 15, tzinfo=timezone.utc)) == (2025, 12)
    assert month_for(-5, False, NOW) == (2026, 11)


def test_render_official():
    d = DiaryData.from_raw(RAW)
    d.year = 2026
    png = render_diary_official([d], nickname="shipper", fetched_at=NOW, source="live")
    Image.open(io.BytesIO(png)).verify()
    empty = DiaryData(month=11, year=2026)
    Image.open(io.BytesIO(render_diary_official([empty], nickname="x", fetched_at=NOW, source="cached"))).verify()
