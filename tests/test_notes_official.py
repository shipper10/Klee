import io
from datetime import datetime, timezone

from PIL import Image

from app.notes import ExpeditionInfo, NotesData
from app.render_notes_official import long_duration, render_notes_official

NOW = datetime.now(timezone.utc)


def _data(**kw):
    base = dict(current_resin=71, max_resin=160, resin_recovery_seconds=42480, current_realm_currency=2070, max_realm_currency=2400,
                realm_currency_recovery_seconds=36180, completed_commissions=4, max_commissions=4, claimed_commission_reward=True,
                remaining_resin_discounts=0, max_resin_discounts=3, transformer_recovery_seconds=259200, max_expeditions=5,
                expeditions=[ExpeditionInfo(120, "u")] * 5)
    base.update(kw)
    return NotesData(**base)


def test_long_duration():
    assert long_duration(120) == "2 min" and long_duration(36180) == "10 h 3 min" and long_duration(259200) == "3 d"


def test_render_variants():
    for d in (_data(), _data(transformer_recovery_seconds=None, expeditions=[], current_resin=160, resin_recovery_seconds=0),
              _data(transformer_recovery_seconds=0, claimed_commission_reward=False, expeditions=[ExpeditionInfo(0)])):
        png = render_notes_official(d, nickname="", uid_masked="1", server_label="EU", fetched_at=NOW, source="stale")
        assert Image.open(io.BytesIO(png)).size[1] < 1200


def test_expedition_icon_roundtrip():
    d = _data()
    assert NotesData.from_json(d.to_json()).expeditions[0].icon == "u"
    old = d.to_json()
    for e in old["expeditions"]:
        e.pop("icon")
    assert NotesData.from_json(old).expeditions[0].icon == ""
