import json

import pytest
from aiohttp.test_utils import TestClient, TestServer

import app.web as webmod
from app.link_service import LinkedAccount, LinkError
from app.linking import hash_token, new_token
from app.web_login import CaptchaStep, DoneStep, LoginError, PendingLogin, PendingStore, valid_device_id
from tests.fakes import FakeDatabase

SECRET = "hunter2-very-secret"
MMT = {"gt": "g", "challenge": "c", "new_captcha": 1, "success": 1, "session_id": "sess-1"}
COOKIES = {"ltuid_v2": "1", "ltoken_v2": "v2_tok", "ltmid_v2": "m"}


class FakeBot:
    def __init__(self):
        self.sent = []

    async def send_message(self, chat_id, text):
        self.sent.append((chat_id, text))


class Login:
    """Stands in for HoYoverse: asks for a captcha first, then accepts it."""

    def __init__(self, captcha=True, error=None):
        self.calls, self.captcha, self.error = [], captcha, error

    async def __call__(self, email, password, *, device_id=None, captcha=None):
        self.calls.append({"email": email, "password": password, "device_id": device_id, "captcha": captcha})
        if self.error:
            raise self.error
        if self.captcha and captcha is None:
            return CaptchaStep(dict(MMT), "11111111-1111-4111-8111-111111111111")
        return DoneStep(dict(COOKIES))


@pytest.fixture
def linked(monkeypatch):
    seen = []

    async def fake_link(db, cipher, user_id, cookies):
        seen.append((user_id, dict(cookies)))
        return [LinkedAccount("acc", "71****678", "Nick", "Asia")]

    monkeypatch.setattr(webmod, "link_accounts", fake_link)
    return seen


async def make(login):
    db, bot = FakeDatabase(), FakeBot()
    deps = webmod.WebDeps(db=db, cipher=None, bot=bot, login=login)  # type: ignore[arg-type]
    client = TestClient(TestServer(webmod.build_app(deps)))
    await client.start_server()
    token = new_token()
    db.add_session(hash_token(token))
    return client, db, bot, deps, token


FORM = {"email": "me@example.com", "password": SECRET, "understood": "yes"}


async def test_login_with_captcha_then_link(linked):
    login = Login()
    client, db, bot, deps, token = await make(login)
    try:
        r = await client.post(f"/link/{token}/login", data=FORM, allow_redirects=False)
        assert r.status == 303 and "/captcha/" in r.headers["Location"]
        assert len(deps.pending) == 1 and not linked
        captcha_url = r.headers["Location"]

        page = await client.get(captcha_url)
        text = await page.text()
        assert page.status == 200 and "gt.0.5.0.js" in text and "sess-1" not in text  # no session id in the browser
        assert SECRET not in text and "me@example.com" not in text  # the captcha page holds no secret
        assert "script-src" in page.headers["Content-Security-Policy"]

        body = {"geetest_challenge": "a", "geetest_validate": "b", "geetest_seccode": "c"}
        r = await client.post(captcha_url, json=body)
        data = await r.json()
        assert data["ok"] is True and "Account linked" in data["html"]
        assert login.calls[1]["captcha"] == {**body, "session_id": "sess-1"}
        assert login.calls[1]["device_id"] == "11111111-1111-4111-8111-111111111111"
        assert linked == [(42, COOKIES)] and bot.sent and "Account linked" in bot.sent[0][1]
        assert len(deps.pending) == 0
        # single use: replaying the captcha URL fails
        assert (await client.post(captcha_url, json=body)).status == 200
        assert (await (await client.post(captcha_url, json=body)).json())["ok"] is False
    finally:
        await client.close()


async def test_login_without_captcha_links_immediately(linked):
    client, db, bot, deps, token = await make(Login(captcha=False))
    try:
        r = await client.post(f"/link/{token}/login", data=FORM)
        text = await r.text()
        assert r.status == 200 and "Account linked" in text and SECRET not in text
        assert linked == [(42, COOKIES)] and len(deps.pending) == 0
    finally:
        await client.close()


async def test_wrong_password_shows_message_and_never_echoes_secret(linked):
    client, db, bot, deps, token = await make(Login(error=LoginError("Wrong e-mail or password.")))
    try:
        r = await client.post(f"/link/{token}/login", data=FORM)
        text = await r.text()
        assert r.status == 400 and "Wrong e-mail or password." in text
        assert SECRET not in text and "me@example.com" not in text and not linked
        assert db.sessions[hash_token(token)]["attempts"] == 1
    finally:
        await client.close()


async def test_validation_and_lockout(linked):
    client, db, bot, deps, token = await make(Login())
    try:
        r = await client.post(f"/link/{token}/login", data={**FORM, "understood": "no"})
        assert r.status == 400 and "tick the box" in await r.text()
        r = await client.post(f"/link/{token}/login", data={**FORM, "password": ""})
        assert r.status == 400
        r = await client.post(f"/link/{token}/login", data={**FORM, "password": "x" * 300})
        assert r.status == 400
        for _ in range(3):
            await client.post(f"/link/{token}/login", data={**FORM, "understood": "no"})
        assert (await client.post(f"/link/{token}/login", data=FORM)).status == 410  # locked after 5 attempts
    finally:
        await client.close()


async def test_link_failure_after_login_is_reported(monkeypatch):
    async def boom(*a, **k):
        raise LinkError("No Genshin Impact account on an international server was found for these cookies.")

    monkeypatch.setattr(webmod, "link_accounts", boom)
    client, db, bot, deps, token = await make(Login(captcha=False))
    try:
        r = await client.post(f"/link/{token}/login", data=FORM)
        assert r.status == 400 and "international server" in await r.text()
    finally:
        await client.close()


async def test_captcha_rejects_foreign_session_bad_body_and_expiry(linked):
    client, db, bot, deps, token = await make(Login())
    try:
        r = await client.post(f"/link/{token}/login", data=FORM, allow_redirects=False)
        url = r.headers["Location"]
        other = new_token()
        db.add_session(hash_token(other), user_id=99)
        wrong_user = url.replace(token, other)
        assert (await client.get(wrong_user)).status == 410  # a pending login belongs to one link only
        bad = await client.post(url, json={"geetest_challenge": "a"})
        assert (await bad.json())["ok"] is False and len(deps.pending) == 0  # bad answers burn the pending login
        assert (await client.get(url)).status == 410
    finally:
        await client.close()


async def test_captcha_failure_from_hoyoverse_is_shown(linked):
    class Flaky(Login):
        async def __call__(self, email, password, *, device_id=None, captcha=None):
            if captcha:
                raise LoginError("The captcha check failed. Please start again.")
            return await super().__call__(email, password, device_id=device_id, captcha=captcha)

    client, db, bot, deps, token = await make(Flaky())
    try:
        r = await client.post(f"/link/{token}/login", data=FORM, allow_redirects=False)
        body = {"geetest_challenge": "a", "geetest_validate": "b", "geetest_seccode": "c"}
        data = await (await client.post(r.headers["Location"], json=body)).json()
        assert data == {"ok": False, "message": "The captcha check failed. Please start again."} and not linked
    finally:
        await client.close()


def test_pending_store_expiry_single_use_and_wipe():
    clock = [0.0]
    store = PendingStore(ttl=60, now=lambda: clock[0])
    item = PendingLogin(1, "s", "e@x.com", SECRET, "d", {})
    key = store.add(item)
    assert store.peek(key, 1, "s") is item and store.peek(key, 2, "s") is None and store.peek(key, 1, "t") is None
    assert store.take(key, 1, "s") is item and store.take(key, 1, "s") is None
    key = store.add(PendingLogin(1, "s", "e@x.com", SECRET, "d", {}))
    clock[0] = 61
    assert store.peek(key, 1, "s") is None and len(store) == 0
    assert SECRET not in repr(item)
    item.wipe()
    assert item.password == "" and item.email == ""


def test_device_id_validator():
    assert valid_device_id("11111111-1111-4111-8111-111111111111") and not valid_device_id("nope")


# ---- start_login against a stubbed genshin.py ------------------------------------------------------------------
import genshin
from genshin.models.auth.cookie import WebLoginResult
from genshin.models.auth.geetest import SessionMMT

from app import web_login


def _web_result(**over):
    data = dict(cookie_token_v2="ct", account_mid_v2="am", account_id_v2="1", ltoken_v2="lt", ltmid_v2="lm", ltuid_v2="1")
    data.update(over)
    return WebLoginResult(**data)


def _stub(monkeypatch, behaviour):
    calls = []

    async def fake(self, account, password, *, device_id, encrypted=False, token_type=6, mmt_result=None):
        calls.append({"device_id": device_id, "token_type": token_type, "mmt": mmt_result})
        return behaviour(mmt_result)

    monkeypatch.setattr(genshin.Client, "_os_web_login", fake)
    return calls


async def test_start_login_returns_only_the_manual_method_cookies(monkeypatch):
    _stub(monkeypatch, lambda mmt: _web_result())
    step = await web_login.start_login("a@b.c", SECRET)
    assert isinstance(step, DoneStep) and set(step.cookies) == {"ltuid_v2", "ltoken_v2", "ltmid_v2"}
    assert "cookie_token_v2" not in step.cookies and "account_id_v2" not in step.cookies


async def test_start_login_captcha_then_result_uses_same_device_id(monkeypatch):
    mmt = SessionMMT(**MMT)
    calls = _stub(monkeypatch, lambda m: mmt if m is None else _web_result())
    first = await web_login.start_login("a@b.c", SECRET)
    assert isinstance(first, CaptchaStep) and first.mmt["session_id"] == "sess-1"
    cap = {"geetest_challenge": "a", "geetest_validate": "b", "geetest_seccode": "c", "session_id": "sess-1"}
    second = await web_login.start_login("a@b.c", SECRET, device_id=first.device_id, captcha=cap)
    assert isinstance(second, DoneStep)
    assert calls[0]["device_id"] == calls[1]["device_id"] == first.device_id and calls[1]["mmt"].geetest_validate == "b"


@pytest.mark.parametrize(
    "exc, text",
    [
        (genshin.errors.AccountLoginFail({"retcode": -3208, "message": "x"}), "Wrong e-mail or password"),
        (genshin.errors.AccountDoesNotExist({"retcode": -3203, "message": "x"}), "No HoYoverse account"),
        (genshin.errors.AccountHasLocked({"retcode": -3202, "message": "x"}), "locked"),
        (genshin.errors.GeetestFailed({"retcode": -3102, "message": "x"}), "captcha"),
        (genshin.GenshinException({"retcode": -1, "message": "x"}), "refused the sign-in"),
    ],
)
async def test_start_login_error_mapping_never_leaks_details(monkeypatch, exc, text):
    def boom(mmt):
        raise exc

    _stub(monkeypatch, boom)
    with pytest.raises(LoginError) as info:
        await web_login.start_login("a@b.c", SECRET)
    assert text in str(info.value) and SECRET not in str(info.value)


async def test_start_login_rejects_malformed_captcha_and_missing_cookies(monkeypatch):
    _stub(monkeypatch, lambda mmt: _web_result(ltoken_v2=""))
    with pytest.raises(LoginError):
        await web_login.start_login("a@b.c", SECRET, captcha={"geetest_challenge": "only"})
    with pytest.raises(LoginError):
        await web_login.start_login("a@b.c", SECRET)


async def test_form_posts_use_absolute_paths_that_contain_the_token(linked):
    client, db, bot, deps, token = await make(Login())
    try:
        text = await (await client.get(f"/link/{token}")).text()
        assert f'action="/link/{token}/login"' in text and f'action="/link/{token}"' in text
        # the failed-login page must keep working too
        r = await client.post(f"/link/{token}/login", data={**FORM, "understood": "no"})
        assert f'action="/link/{token}/login"' in await r.text()
    finally:
        await client.close()
