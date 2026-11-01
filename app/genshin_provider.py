"""The only module that talks to HoYoLAB (through genshin.py).

Telegram handlers call `GenshinProvider`, never genshin.py directly.
"""

from __future__ import annotations

import asyncio
import logging
from collections.abc import Awaitable, Callable
from dataclasses import dataclass
from datetime import datetime, timedelta
from typing import Any, Generic, Mapping, TypeVar

import aiohttp
import genshin

from app import abyss as abyss_mod
from app import notes as notes_mod
from app.abyss import AbyssData
from app.crypto import CredentialCipher, CryptoError
from app.db import Database
from app.errors import ChronicleHidden, NotesDisabled, ReauthRequired, UpstreamUnavailable
from app.linking import parse_ts, utcnow
from app.notes import NotesData

log = logging.getLogger(__name__)

NOTES_CACHE_KEY = "notes"
NOTES_TTL = timedelta(minutes=3)
ABYSS_TTL = timedelta(minutes=30)
REQUEST_TIMEOUT_SECONDS = 25

T = TypeVar("T")


@dataclass
class Report(Generic[T]):
    data: T
    fetched_at: datetime
    source: str  # "live" | "cached" | "stale"


NotesResult = Report[NotesData]


def make_client(cookies: Mapping[str, str], uid: int | None = None, on_cookie_update: Any = None) -> genshin.Client:
    return genshin.Client(
        dict(cookies),
        game=genshin.Game.GENSHIN,
        region=genshin.Region.OVERSEAS,
        lang="en-us",
        uid=uid,
        on_cookie_update=on_cookie_update,
    )


class GenshinProvider:
    def __init__(self, db: Database, cipher: CredentialCipher, max_concurrent: int = 3) -> None:
        self._db = db
        self._cipher = cipher
        self._semaphore = asyncio.Semaphore(max_concurrent)
        # One refresh per account at a time; concurrent identical requests wait and then hit the cache.
        self._locks: dict[str, asyncio.Lock] = {}

    # ---- public reports -------------------------------------------------
    async def get_notes(self, account: Mapping[str, Any]) -> Report[NotesData]:
        return await self._cached(
            account, NOTES_CACHE_KEY, NOTES_TTL, notes_mod.SCHEMA_VERSION, self._fetch_notes, NotesData.from_json
        )

    async def get_abyss(self, account: Mapping[str, Any], previous: bool = False) -> Report[AbyssData]:
        async def fetch(acc: Mapping[str, Any]) -> AbyssData:
            return await self._fetch_abyss(acc, previous)

        key = "abyss:previous" if previous else "abyss:current"
        return await self._cached(account, key, ABYSS_TTL, abyss_mod.SCHEMA_VERSION, fetch, AbyssData.from_json)

    # ---- caching --------------------------------------------------------
    async def _cached(
        self,
        account: Mapping[str, Any],
        cache_key: str,
        ttl: timedelta,
        schema_version: int,
        fetch: Callable[[Mapping[str, Any]], Awaitable[Any]],
        from_json: Callable[[dict[str, Any]], Any],
    ) -> Report[Any]:
        account_id = str(account["id"])
        lock = self._locks.setdefault(account_id, asyncio.Lock())
        async with lock:
            row = await self._db.get_cache(account_id, cache_key)
            cached = self._decode(row, schema_version, from_json)
            if cached and parse_ts(row["expires_at"]) > utcnow():  # type: ignore[index]
                return Report(cached.data, cached.fetched_at, "cached")

            try:
                data = await fetch(account)
            except UpstreamUnavailable:
                # Only "HoYoLAB is down" falls back to old data; auth/privacy problems must stay visible.
                if cached:
                    return Report(cached.data, cached.fetched_at, "stale")
                raise

            fetched_at = utcnow()
            try:
                await self._db.put_cache(account_id, cache_key, data.to_json(), schema_version, fetched_at, ttl)
            except Exception:  # caching must never break a successful report
                log.warning("cache write failed (%s)", cache_key.split(":")[0])
            return Report(data, fetched_at, "live")

    @staticmethod
    def _decode(row: Mapping[str, Any] | None, schema_version: int, from_json: Callable[[dict[str, Any]], Any]) -> Report[Any] | None:
        if not row or row.get("schema_version") != schema_version:
            return None
        try:
            return Report(from_json(row["payload"]), parse_ts(row["fetched_at"]), "cached")  # type: ignore[arg-type]
        except (KeyError, TypeError, ValueError):
            return None

    # ---- upstream calls -------------------------------------------------
    async def _fetch_notes(self, account: Mapping[str, Any]) -> NotesData:
        uid = int(account["game_uid"])

        async def call(client: genshin.Client) -> Any:
            # autoauth=False: never change the user's HoYoLAB privacy settings on their behalf.
            return await client.get_genshin_notes(uid, autoauth=False)

        return NotesData.from_genshin(await self._call(account, call))

    async def _fetch_abyss(self, account: Mapping[str, Any], previous: bool) -> AbyssData:
        uid = int(account["game_uid"])

        async def call(client: genshin.Client) -> Any:
            return await client.get_genshin_spiral_abyss(uid, previous=previous)

        return AbyssData.from_genshin(await self._call(account, call))

    async def _call(self, account: Mapping[str, Any], call: Callable[[genshin.Client], Awaitable[Any]]) -> Any:
        """Run one genshin.py request with decrypted cookies, mapping every failure to a safe BotError."""
        account_id = str(account["id"])
        cookies = await self._load_cookies(account_id)

        async def save_updated_cookies(updated: Mapping[str, str]) -> None:
            try:
                ct, nonce, version = self._cipher.encrypt(updated, account_id=account_id)
                await self._db.store_credentials(account_id, ct, nonce, version)
            except Exception:
                # genshin.py would re-raise into the request; losing a refresh is the lesser evil.
                log.warning("could not persist refreshed cookies")

        client = make_client(cookies, int(account["game_uid"]), save_updated_cookies)
        try:
            async with self._semaphore:
                return await asyncio.wait_for(call(client), timeout=REQUEST_TIMEOUT_SECONDS)
        except genshin.InvalidCookies:
            await self._db.set_status(account_id, "reauth_required")
            raise ReauthRequired() from None
        except genshin.DataNotPublic:
            raise ChronicleHidden() from None
        except (genshin.TooManyRequests, genshin.errors.VisitsTooFrequently):
            raise UpstreamUnavailable("HoYoLAB is rate limiting requests. Please wait a minute and try again.") from None
        except genshin.GenshinException as exc:
            if "not enabled" in (exc.msg or "").lower():
                raise NotesDisabled() from None
            log.warning("genshin error: %s retcode=%s", type(exc).__name__, exc.retcode)
            raise UpstreamUnavailable() from None
        except (asyncio.TimeoutError, aiohttp.ClientError):
            raise UpstreamUnavailable() from None

    async def _load_cookies(self, account_id: str) -> dict[str, str]:
        row = await self._db.get_credentials(account_id)
        if not row:
            await self._db.set_status(account_id, "reauth_required")
            raise ReauthRequired()
        try:
            return self._cipher.decrypt(row["ciphertext"], row["nonce"], row["key_version"], account_id=account_id)
        except CryptoError:
            log.error("stored credential could not be decrypted for an account")
            await self._db.set_status(account_id, "error")
            raise UpstreamUnavailable("Stored credentials could not be read. Please /link the account again.") from None
