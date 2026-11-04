import io
from datetime import datetime, timezone

from PIL import Image

from app.diary import Category, DiaryData, month_for
from app.render_diary_official import comparison, render_diary_official

NOW = datetime(2026, 1, 15, tzinfo=timezone.utc)


def _m(month, cats=True):
    return DiaryData(month=month, year=2026, primogems=100, mora=5, primogem_rate=17, mora_rate=-5,
                     categories=[Category("Events", 60, 60), Category("Mail", 40, 40), Category("Weird new source", 1, 0)] if cats else [])


def test_month_back_crosses_year():
    assert month_for(0, False, NOW, back=2) == (2025, 11) and month_for(0, True, NOW) == (2025, 12)


def test_comparison_text():
    assert comparison(_m(1)) == "17% more Primogems than last month, 5% less Mora than last month."


def test_render_one_to_three_months_and_empty():
    for months in ([_m(1)], [_m(1), _m(12, False), _m(11)], [DiaryData(month=1, year=2026)]):
        png = render_diary_official(months, nickname="", fetched_at=NOW, source="cached")
        Image.open(io.BytesIO(png)).verify()
