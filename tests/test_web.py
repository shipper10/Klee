import pytest
from aiohttp import web
from aiohttp.test_utils import TestClient, TestServer

import app.web as webmod
from app.link_service import LinkedAccount, LinkError
from app.linking import hash_token, new_token
from tests.fakes import FakeDatabase


class FakeBot:
    def __init__(self):
        self.sent = []

    async def send_message(self, chat_id, text):
        self.sent.append((chat_id, text))


@pytest.fixture
async def env():
    db, bot = FakeDatabase(), FakeBot()
    app = webmod.build_app(webmod.WebDeps(db=db, cipher=None, bot=bot))  # type: ignore[arg-type]
    async with TestClient(TestServer(app)) as client:
        yield client, db, bot


GOOD_FORM = {"cookies": "ltuid_v2=1\nltoken_v2=v2_secret", "understood": "yes"}


async def test_health(env):
    client, _, _ = env
    r = await client.get("/health")
    assert r.status == 200 and (await r.json()) == {"status": "ok"}


async def test_form_served_with_security_headers(env):
    client, db, _ = env
    token = new_token()
    db.add_session(hash_token(token))
    r = await client.get(f"/link/{token}")
    assert r.status == 200
    assert r.headers["Cache-Control"] == "no-store" and r.headers["Referrer-Policy"] == "no-referrer"
    assert "Content-Security-Policy" in r.headers
    text = await r.text()
    csp = r.headers["Content-Security-Policy"]
    assert "script-src" not in csp and "default-src 'none'" in csp  # pages that take secrets run no scripts
    assert 'type="password"' in text and "<script" not in text


async def test_unknown_and_malformed_tokens_are_410(env):
    client, _, _ = env
    assert (await client.get(f"/link/{new_token()}")).status == 410
    assert (await client.get("/link/short")).status == 410


async def test_expired_link(env):
    from datetime import timedelta

    client, db, _ = env
    token = new_token()
    db.add_session(hash_token(token), expires_in=timedelta(seconds=-5))
    assert (await client.get(f"/link/{token}")).status == 410


async def test_successful_link_notifies_user_and_consumes_token(env, monkeypatch):
    client, db, bot = env
    token = new_token()
    db.add_session(hash_token(token), user_id=777)

    async def fake_link(db_, cipher, user_id, cookies):
        assert user_id == 777 and "ltoken_v2" in cookies
        return [LinkedAccount("acc-1", "71****678", "Nick", "Asia")]

    monkeypatch.setattr(webmod, "link_accounts", fake_link)
    r = await client.post(f"/link/{token}", data=GOOD_FORM)
    body = await r.text()
    assert r.status == 200 and "Account linked" in body
    assert "v2_secret" not in body  # cookies are never echoed
    assert bot.sent and bot.sent[0][0] == 777
    assert (await client.get(f"/link/{token}")).status == 410  # single use


async def test_link_error_is_shown_and_attempts_are_counted(env, monkeypatch):
    client, db, _ = env
    token = new_token()
    row = db.add_session(hash_token(token))

    async def fail(*a, **k):
        raise LinkError("HoYoLAB did not accept these cookies.")

    monkeypatch.setattr(webmod, "link_accounts", fail)
    r = await client.post(f"/link/{token}", data=GOOD_FORM)
    assert r.status == 400 and "did not accept" in await r.text()
    assert row["attempts"] == 1 and not row["consumed_at"]


async def test_lockout_after_too_many_attempts(env, monkeypatch):
    client, db, _ = env
    token = new_token()
    db.add_session(hash_token(token))

    async def fail(*a, **k):
        raise LinkError("nope")

    monkeypatch.setattr(webmod, "link_accounts", fail)
    for _ in range(5):
        assert (await client.post(f"/link/{token}", data=GOOD_FORM)).status == 400
    assert (await client.post(f"/link/{token}", data=GOOD_FORM)).status == 410


async def test_risk_checkbox_required_and_bad_cookies_rejected(env):
    client, db, _ = env
    token = new_token()
    db.add_session(hash_token(token))
    r = await client.post(f"/link/{token}", data={"cookies": GOOD_FORM["cookies"]})
    assert r.status == 400
    r = await client.post(f"/link/{token}", data={"cookies": "garbage", "understood": "yes"})
    assert r.status == 400 and "required cookies" in await r.text()


async def test_unexpected_exception_does_not_leak_details(env, monkeypatch):
    client, db, _ = env
    token = new_token()
    db.add_session(hash_token(token))

    async def boom(*a, **k):
        raise RuntimeError("secret internal detail v2_secret")

    monkeypatch.setattr(webmod, "link_accounts", boom)
    r = await client.post(f"/link/{token}", data=GOOD_FORM)
    body = await r.text()
    assert r.status == 500 and "secret internal detail" not in body and "v2_secret" not in body
