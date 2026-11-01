import io
from datetime import datetime, timezone
from types import SimpleNamespace

from PIL import Image

from app import bot
from app.genshin_provider import Report
from app.linking import utcnow
from app.profile import ProfChar, ProfileData
from app.render_profile import render_profile_card, select_characters
from tests.fakes import FakeDatabase
from tests.test_abyss_flow import ACCOUNT, FakeBot, FakeImages, ctx, provider
from tests.test_render_abyss import _icon

NOW = datetime(2026, 11, 1, 12, 0, tzinfo=timezone.utc)


def sample(n=30) -> ProfileData:
    chars = [
        ProfChar(name=f"Char{i}", icon=f"https://x.hoyoverse.com/c{i}.png", level=90 - i % 20, rarity=5 if i % 4 == 0 else 4,
                 constellation=i % 7, candidates=[f"https://enka.network/ui/UI_AvatarIcon_C{i}.png"])
        for i in range(n)
    ]
    return ProfileData(nickname="shipper", level=60, days_active=700, achievements=640, characters_owned=n, max_friendship=20,
                       spiral_abyss="12-3", theater_act=10, theater_unlocked=True, stygian_difficulty=5, stygian_unlocked=True,
                       chests=2000, oculi=1100, waypoints=500, domains=60, characters=chars)


def render(data=None, show_all=False, icons=True, **kw):
    data = data or sample()
    chars = select_characters(data, show_all)
    args = dict(nickname="shipper", uid="712345678", server="os_asia",
                icons={c.icon: _icon(c.icon) for c in chars} if icons else {}, characters=chars,
                fetched_at=NOW, source="live", summary=not show_all)
    args.update(kw)
    return render_profile_card(data, **args)


def test_sizes_and_limits():
    short = Image.open(io.BytesIO(render()))
    full = Image.open(io.BytesIO(render(sample(122), show_all=True)))
    assert short.width == full.width == 1080
    assert full.width + full.height < 10000 and short.height < full.height


def test_default_shows_top_16_sorted_and_all_on_request():
    d = sample(40)
    top = select_characters(d, False)
    assert len(top) == 16 and top[0].rarity == 5 and len(select_characters(d, True)) == 40


def test_deterministic_and_edge_cases():
    assert render() == render()
    render(ProfileData(), icons=False, characters=[])  # brand-new empty account
    render(sample(1), nickname="N" * 80)


def test_json_roundtrip():
    d = sample(5)
    assert ProfileData.from_json(d.to_json()) == d


def test_from_genshin_reads_models():
    user = SimpleNamespace(
        info=SimpleNamespace(nickname="Zed", level=58),
        stats=SimpleNamespace(days_active=10, achievements=20, characters=2, max_friendship_characters=1, spiral_abyss="9-1",
                              theater=SimpleNamespace(unlocked=True, max_act=4), stygian=SimpleNamespace(unlocked=False, difficulty=0),
                              common_chests=1, exquisite_chests=2, precious_chests=3, luxurious_chests=4, remarkable_chests=5,
                              anemoculi=10, geoculi=20, electroculi=5, dendroculi=5, hydroculi=5, pyroculi=5, lunoculi=1,
                              unlocked_waypoints=7, unlocked_domains=3),
        characters=[SimpleNamespace(id=10000002, name="Ayaka", icon="https://enka.network/ui/UI_AvatarIcon_Ayaka.png",
                                    level=90, rarity=5, constellation=2, friendship=10, element="Cryo")],
    )
    p = ProfileData.from_genshin(user)
    assert p.nickname == "Zed" and p.chests == 15 and p.oculi == 51 and p.theater_act == 4 and not p.stygian_unlocked
    assert p.characters[0].constellation == 2 and p.characters[0].candidates[0].startswith("https://enka.network/ui/")
    assert ProfileData.from_json(p.to_json()) == p


async def test_provider_caches_profile(monkeypatch):
    p = provider()
    calls = []

    async def fake(account):
        calls.append(1)
        return sample(3)

    monkeypatch.setattr(p, "_fetch_profile", fake)
    assert (await p.get_profile(ACCOUNT)).source == "live"
    assert (await p.get_profile(ACCOUNT)).source == "cached" and len(calls) == 1


class FakeProv:
    async def get_profile(self, account):
        return Report(sample(20), utcnow(), "live")


async def test_send_profile_summary_and_all():
    c = ctx(FakeProv())
    await bot._send_profile(c, 1, 301, ACCOUNT, show_all=False)
    await bot._send_profile(c, 1, 302, ACCOUNT, show_all=True)
    assert [x[2].split(" ·")[0] for x in c.bot.photos] == ["Profile", "All characters"]
    assert all(x[1][:4] == b"\x89PNG" for x in c.bot.photos)


async def test_send_profile_error_is_friendly():
    class Boom:
        async def get_profile(self, account):
            raise RuntimeError("secret detail")

    c = ctx(Boom())
    await bot._send_profile(c, 1, 303, ACCOUNT, show_all=False)
    assert "secret" not in c.bot.messages[0][1] and not c.bot.photos
