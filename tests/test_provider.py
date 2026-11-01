import os
from datetime import timedelta

import pytest

from app.crypto import CredentialCipher
from app.errors import ReauthRequired, UpstreamUnavailable
from app.genshin_provider import NOTES_CACHE_KEY, NOTES_TTL, GenshinProvider
from app.linking import utcnow
from app.notes import SCHEMA_VERSION
from tests.fakes import FakeDatabase
from tests.test_render_notes import sample

ACCOUNT = {"id": "acc-1", "game_uid": "712345678"}


def make_provider(db):
    return GenshinProvider(db, CredentialCipher(os.urandom(32), "v1"))  # type: ignore[arg-type]


async def test_live_then_cached(monkeypatch):
    db = FakeDatabase()
    p = make_provider(db)
    calls = []

    async def fake_fetch(account):
        calls.append(1)
        return sample()

    monkeypatch.setattr(p, "_fetch_notes", fake_fetch)
    first = await p.get_notes(ACCOUNT)
    second = await p.get_notes(ACCOUNT)
    assert first.source == "live" and second.source == "cached" and len(calls) == 1


async def test_expired_cache_triggers_refetch(monkeypatch):
    db = FakeDatabase()
    await db.put_cache("acc-1", NOTES_CACHE_KEY, sample().to_json(), SCHEMA_VERSION,
                       utcnow() - NOTES_TTL - timedelta(minutes=1), NOTES_TTL)
    p = make_provider(db)

    async def fake_fetch(account):
        return sample(current_resin=1)

    monkeypatch.setattr(p, "_fetch_notes", fake_fetch)
    res = await p.get_notes(ACCOUNT)
    assert res.source == "live" and res.data.current_resin == 1


async def test_upstream_failure_serves_stale_copy(monkeypatch):
    db = FakeDatabase()
    await db.put_cache("acc-1", NOTES_CACHE_KEY, sample().to_json(), SCHEMA_VERSION,
                       utcnow() - timedelta(hours=1), NOTES_TTL)
    p = make_provider(db)

    async def down(account):
        raise UpstreamUnavailable()

    monkeypatch.setattr(p, "_fetch_notes", down)
    assert (await p.get_notes(ACCOUNT)).source == "stale"


async def test_upstream_failure_without_cache_raises(monkeypatch):
    p = make_provider(FakeDatabase())

    async def down(account):
        raise UpstreamUnavailable()

    monkeypatch.setattr(p, "_fetch_notes", down)
    with pytest.raises(UpstreamUnavailable):
        await p.get_notes(ACCOUNT)


async def test_reauth_is_never_masked_by_stale_cache(monkeypatch):
    db = FakeDatabase()
    await db.put_cache("acc-1", NOTES_CACHE_KEY, sample().to_json(), SCHEMA_VERSION,
                       utcnow() - timedelta(hours=1), NOTES_TTL)
    p = make_provider(db)

    async def revoked(account):
        raise ReauthRequired()

    monkeypatch.setattr(p, "_fetch_notes", revoked)
    with pytest.raises(ReauthRequired):
        await p.get_notes(ACCOUNT)


async def test_cache_is_per_account(monkeypatch):
    db = FakeDatabase()
    p = make_provider(db)

    async def fetch(account):
        return sample(current_resin=int(account["game_uid"][-2:]))

    monkeypatch.setattr(p, "_fetch_notes", fetch)
    a = await p.get_notes({"id": "a", "game_uid": "100000011"})
    b = await p.get_notes({"id": "b", "game_uid": "100000022"})
    assert (a.data.current_resin, b.data.current_resin) == (11, 22)


async def test_missing_credentials_marks_reauth():
    db = FakeDatabase()
    p = make_provider(db)
    with pytest.raises(ReauthRequired):
        await p._fetch_notes(ACCOUNT)
    assert db.statuses["acc-1"] == "reauth_required"
