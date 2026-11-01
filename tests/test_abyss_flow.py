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
    def __init__(self, fail=0):
        self.fail = fail

    async def fetch_first(self, items):
        res = images.FetchResult()
        res.images = {k: _icon(k) for k, _ in items}
        if self.fail:
            res.failed = self.fail
            res.reasons.update({"HTTP 404 enka.network": self.fail})
        return res


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


async def test_fetch_first_tries_candidates_in_order(monkeypatch):
    hits = []

    async def ok(request):
        hits.append("ok")
        return web.Response(body=_icon("a"), content_type="image/png")

    async def missing(request):
        hits.append("missing")
        return web.Response(status=404)

    app = web.Application()
    app.router.add_get("/ok", ok)
    app.router.add_get("/missing", missing)
    async with TestServer(app) as server:
        monkeypatch.setattr(images, "is_allowed_url", lambda u: True)
        base = str(server.make_url("/"))
        f = images.ImageFetcher()
        res = await f.fetch_first([
            ("first_ok", [base + "ok", base + "missing"]),
            ("second_ok", [base + "missing", base + "ok"]),
            ("none", [base + "missing"]),
            ("empty", []),
        ])
        await f.close()
    assert set(res.images) == {"first_ok", "second_ok"}
    assert res.failed == 2 and "HTTP 404" in res.summary()


async def test_fetch_retries_rate_limit_once(monkeypatch):
    calls = []

    async def flaky(request):
        calls.append(1)
        if len(calls) == 1:
            return web.Response(status=429)
        return web.Response(body=_icon("b"), content_type="image/png")

    app = web.Application()
    app.router.add_get("/flaky", flaky)
    async with TestServer(app) as server:
        monkeypatch.setattr(images, "is_allowed_url", lambda u: True)
        f = images.ImageFetcher()
        res = await f.fetch_first([("k", [str(server.make_url("/flaky"))])])
        await f.close()
    assert "k" in res.images and len(calls) == 2


async def test_send_abyss_reports_portrait_failures_in_chat():
    prov = FakeProvider(sample())
    c = ctx(prov)
    c.application.bot_data["deps"].images = FakeImages(fail=2)
    await bot._send_abyss(c, 1, 120, ACCOUNT, previous=False, floor=None)
    assert c.bot.photos and "2 character portrait(s)" in c.bot.messages[-1][1]
    assert "HTTP 404 enka.network" in c.bot.messages[-1][1]


async def test_fetch_reads_whole_body_when_it_arrives_in_pieces(monkeypatch):
    import asyncio
    import io as _io
    from PIL import Image as _Image

    big = _Image.effect_noise((400, 400), 90).convert("RGB")
    buf = _io.BytesIO()
    big.save(buf, "PNG")
    body = buf.getvalue()
    assert len(body) > 40000

    async def slow(request):
        resp = web.StreamResponse(headers={"Content-Type": "image/png"})
        await resp.prepare(request)
        for i in range(0, len(body), 8192):
            await resp.write(body[i:i + 8192])
            await asyncio.sleep(0.01)
        return resp

    app = web.Application()
    app.router.add_get("/big", slow)
    async with TestServer(app) as server:
        monkeypatch.setattr(images, "is_allowed_url", lambda u: True)
        f = images.ImageFetcher()
        res = await f.fetch_first([("k", [str(server.make_url("/big"))])])
        await f.close()
    assert res.images.get("k") == body and res.failed == 0
