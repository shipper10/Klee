import io
import os
from datetime import datetime, timedelta, timezone

from PIL import Image

from app.notes import ExpeditionInfo, NotesData
from app.render_notes import fmt_duration, render_notes_card

FETCHED = datetime(2026, 10, 31, 10, 0, tzinfo=timezone.utc)


def sample(**over) -> NotesData:
    base = dict(
        current_resin=160, max_resin=200, resin_recovery_seconds=19200,
        current_realm_currency=1800, max_realm_currency=2400, realm_currency_recovery_seconds=36000,
        completed_commissions=3, max_commissions=4, claimed_commission_reward=False,
        remaining_resin_discounts=2, max_resin_discounts=3,
        transformer_recovery_seconds=None, max_expeditions=5,
        expeditions=[ExpeditionInfo(0), ExpeditionInfo(5400), ExpeditionInfo(30000)],
    )
    base.update(over)
    return NotesData(**base)


def render(data=None, **kw):
    args = dict(nickname="Traveler", uid_masked="71****678", server_label="Asia",
                fetched_at=FETCHED, source="live", now=FETCHED)
    args.update(kw)
    return render_notes_card(data or sample(), **args)


def test_png_output_and_size():
    png = render()
    img = Image.open(io.BytesIO(png))
    assert img.format == "PNG" and img.width == 960 and 1000 < img.height < 2500
    assert len(png) < 2_000_000
    out = os.environ.get("KLEE_SAMPLE_OUT")
    if out:
        with open(out, "wb") as f:
            f.write(png)


def test_deterministic():
    assert render() == render()


def test_edge_cases_do_not_crash():
    render(sample(expeditions=[], current_resin=200, transformer_recovery_seconds=0))
    render(sample(expeditions=[ExpeditionInfo(1)] * 5, transformer_recovery_seconds=90000), source="stale")
    render(nickname="A" * 80 + " very long nickname", source="cached", now=FETCHED + timedelta(hours=3))


def test_fmt_duration():
    assert fmt_duration(0) == "now" and fmt_duration(30) == "<1m"
    assert fmt_duration(90) == "1m" and fmt_duration(5400) == "1h 30m" and fmt_duration(90000) == "1d 1h"


def test_json_roundtrip():
    d = sample()
    assert NotesData.from_json(d.to_json()) == d
