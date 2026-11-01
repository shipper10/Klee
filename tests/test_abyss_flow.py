import os
from types import SimpleNamespace

import genshin
import pytest
from aiohttp import web
from aiohttp.test_utils import TestServer

import app.images as images
from app import bot
from app.abyss import AbyssData
from app.crypto import CredentialCipher
from app.errors import ChronicleHidden, ReauthRequired, UpstreamUnavailable
from app.genshin_provider import GenshinProvider, Report
from app.linking import utcnow
from tests.fakes import FakeDatabase
from tests.test_render_abyss import _icon, sample

ACCOUNT = {"id": "acc-1", "game_uid": "712345678", "region": "os_asia", "nickname": "shipper", "is_default": True}


def provider(db=None):
    return GenshinProvider(db or FakeDatabase(), CredentialCipher(os.urandom(32), "v1"))  # type: ignore[arg-type]


# ---- provider ---------------------------------------------------------
async def test_abyss_current_and_previous_cached_separately(monkeypatch):
    p = provider()
    calls = []

    async def fake(account, previous):
        calls.append(previous)
        return sample(total_stars=12 if previous else 36)

    monkeypatch.setattr(p, "_fetch_abyss", fake)
    cur = await p.get_abyss(ACCOUNT)
    prev = await p.get_abyss(ACCOUNT, previous=True)
    cur2 = await p.get_abyss(ACCOUNT)
    assert (cur.data.total_stars, prev.data.total_stars) == (36, 12)
    assert cur2.source == "cached" and calls == [False, True]


async def test_abyss_error_mapping(monkeypatch):
    db = FakeDatabase()
    p = provider(db)
    cookies = {"ltuid_v2": "1", "ltoken_v2": "t"}
    ct, nonce, ver = p._cipher.encrypt(cookies, account_id="acc-1")
    await db.store_credentials("acc-1", ct, nonce, ver)

    class Boom:
        def __init__(self, exc):
            self.exc = exc

        async def get_genshin_spiral_abyss(self, *a, **k):
            raise self.exc

    cases = [
        (genshin.DataNotPublic({"retcode": 10102, "message": "private"}), ChronicleHidden),
        (genshin.InvalidCookies({"retcode": -100, "message": "bad"}), ReauthRequired),
        (genshin.GenshinException({"retcode": 1, "message": "weird"}), UpstreamUnavailable),
        (genshin.TooManyRequests({"retcode": 10101, "message": "x"}), UpstreamUnavailable),
    ]
    for exc, expected in cases:
        monkeypatch.setattr("app.genshin_provider.make_client", lambda *a, _e=exc, **k: Boom(_e))
        with pytest.raises(expected):
            await p._fetch_abyss(ACCOUNT, False)
    assert db.statuses["acc-1"] == "reauth_required"


async def test_hidden_chronicle_is_not_masked_by_stale_cache(monkeypatch):
    p = provider()

    async def hidden(account, previous):
        raise ChronicleHidden()

    monkeypatch.setattr(p, "_fetch_abyss", hidden)
    with pytest.raises(ChronicleHidden):
        await p.get_abyss(ACCOUNT)


# ---- bot handler wiring ----------------------------------------------
class FakeBot:
    def __init__(self):
        self.photos, self.messages, self.actions = [], [], []

    async def send_photo(self, chat_id, photo, caption=None):
        self.photos.append((chat_id, photo.read(), caption))

    async def send_message(self, chat_id, text):
        self.messages.append((chat_id, text))

    async def send_chat_action(self, chat_id, action):
        self.actions.append(action)


class FakeProvider:
    def __init__(self, data=None, exc=None):
        self.data, self.exc, self.calls = data, exc, []

    async def get_abyss(self, account, previous=False):
        self.calls.append(previous)
        if self.exc:
            raise self.exc
        return Report(self.data, utcnow(), "live")


class FakeImages:
    async def fetch_with_fallbacks(self, pairs):
        return {p: _icon(p) for p, _ in pairs}


def ctx(provider):
    deps = bot.Deps(db=None, provider=provider, public_base_url="https://x", images=FakeImages())  # type: ignore[arg-type]
    return SimpleNamespace(bot=FakeBot(), application=SimpleNamespace(bot_data={"deps": deps}))


async def test_send_abyss_full_report():
    c = ctx(FakeProvider(sample()))
    await bot._send_abyss(c, 1, 101, ACCOUNT, previous=False, floor=None)
    chat_id, png, caption = c.bot.photos[0]
    assert png[:8] == b"\x89PNG\r\n\x1a\n" and "Current" in caption and "Live data" in caption


async def test_send_abyss_previous_and_floor():
    prov = FakeProvider(sample())
    c = ctx(prov)
    await bot._send_abyss(c, 1, 102, ACCOUNT, previous=True, floor=10)
    assert prov.calls == [True] and "Previous" in c.bot.photos[0][2]


async def test_send_abyss_missing_floor_and_empty_period():
    c = ctx(FakeProvider(sample()))
    await bot._send_abyss(c, 1, 103, ACCOUNT, previous=False, floor=2)
    assert "floor 2" in c.bot.messages[0][1] and not c.bot.photos
    empty = sample(total_stars=0, total_battles=0, most_played=[], stats=[], floors=[])
    c = ctx(FakeProvider(empty))
    await bot._send_abyss(c, 1, 104, ACCOUNT, previous=False, floor=None)
    assert "No Spiral Abyss records" in c.bot.messages[0][1]


async def test_send_abyss_errors_become_safe_messages():
    c = ctx(FakeProvider(exc=ChronicleHidden()))
    await bot._send_abyss(c, 1, 105, ACCOUNT, previous=False, floor=None)
    assert "private" in c.bot.messages[0][1]
    c = ctx(FakeProvider(exc=RuntimeError("secret internal ltoken_v2=abc")))
    await bot._send_abyss(c, 1, 106, ACCOUNT, previous=False, floor=None)
    assert "abc" not in c.bot.messages[0][1] and "ltoken" not in c.bot.messages[0][1]


async def test_cooldown_blocks_rapid_repeat():
    prov = FakeProvider(sample())
    c = ctx(prov)
    await bot._send_abyss(c, 1, 107, ACCOUNT, previous=False, floor=None)
    await bot._send_abyss(c, 1, 107, ACCOUNT, previous=False, floor=None)
    assert len(c.bot.photos) == 1 and "wait" in c.bot.messages[0][1].lower() and prov.calls == [False]


def test_parse_abyss_args():
    assert bot._parse_abyss_args([]) == (False, None)
    assert bot._parse_abyss_args(["previous", "12"]) == (True, 12)
    assert bot._parse_abyss_args(["13", "0", "x"]) == (False, None)


# ---- image fetcher ----------------------------------------------------
async def test_image_fetcher_limits(monkeypatch):
    big = b"x" * (images.MAX_BYTES + 10)

    async def ok(request):
        return web.Response(body=_icon("a"), content_type="image/png")

    async def huge(request):
        return web.Response(body=big)

    async def missing(request):
        return web.Response(status=404)

    async def redirect(request):
        raise web.HTTPFound("http://127.0.0.1:1/secret")

    app = web.Application()
    for path, h in (("/ok", ok), ("/huge", huge), ("/missing", missing), ("/redir", redirect)):
        app.router.add_get(path, h)
    async with TestServer(app) as server:
        monkeypatch.setattr(images, "is_allowed_url", lambda u: True)
        f = images.ImageFetcher()
        base = str(server.make_url("/"))
        got = await f.fetch_many([base + "ok", base + "huge", base + "missing", base + "redir", base + "ok"])
        await f.close()
    assert list(got) == [base + "ok"]  # oversize, 404 and redirects are all dropped; duplicates fetched once


async def test_image_fetcher_blocks_disallowed_hosts():
    f = images.ImageFetcher()
    assert await f.fetch_many(["http://127.0.0.1/x.png", "https://evil.example.com/x.png", ""]) == {}
    await f.close()


async def test_fetch_with_fallbacks_uses_alt_only_when_primary_fails(monkeypatch):
    async def ok(request):
        return web.Response(body=_icon("a"), content_type="image/png")

    async def missing(request):
        return web.Response(status=404)

    app = web.Application()
    app.router.add_get("/ok", ok)
    app.router.add_get("/missing", missing)
    async with TestServer(app) as server:
        monkeypatch.setattr(images, "is_allowed_url", lambda u: True)
        base = str(server.make_url("/"))
        f = images.ImageFetcher()
        got = await f.fetch_with_fallbacks([
            (base + "ok", base + "missing"),       # primary works, fallback must not be needed
            (base + "missing", base + "ok"),       # primary 404 -> falls back
            (base + "missing", ""),                # nothing works -> absent (placeholder)
        ])
        await f.close()
    assert set(got) == {base + "ok", base + "missing"} and got[base + "missing"] == got[base + "ok"]
