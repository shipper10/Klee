"""The only module that talks to HoYoLAB (through genshin.py).

Telegram handlers call `GenshinProvider`, never genshin.py directly.
"""

from __future__ import annotations

import asyncio
import logging
from dataclasses import dataclass
from datetime import datetime, timedelta
from typing import Any, Mapping

import aiohttp
import genshin

from app.crypto import CredentialCipher, CryptoError
from app.db import Database
from app.errors import NotesDisabled, ReauthRequired, UpstreamUnavailable
from app.linking import parse_ts, utcnow
from app.notes import SCHEMA_VERSION, NotesData

log = logging.getLogger(__name__)

NOTES_CACHE_KEY = "notes"
NOTES_TTL = timedelta(minutes=3)
REQUEST_TIMEOUT_SECONDS = 25


@dataclass
class NotesResult:
    data: NotesData
    fetched_at: datetime
    source: str  # "live" | "cached" | "stale"


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

    async def get_notes(self, account: Mapping[str, Any]) -> NotesResult:
        account_id = str(account["id"])
        lock = self._locks.setdefault(account_id, asyncio.Lock())
        async with lock:
            cached_row = await self._db.get_cache(account_id, NOTES_CACHE_KEY)
            cached = self._cached_result(cached_row)
            now = utcnow()
            if cached and parse_ts(cached_row["expires_at"]) > now:  # type: ignore[index]
                return NotesResult(cached.data, cached.fetched_at, "cached")

            try:
                data = await self._fetch_notes(account)
            except UpstreamUnavailable:
                if cached:
                    return NotesResult(cached.data, cached.fetched_at, "stale")
                raise

            fetched_at = utcnow()
            try:
                await self._db.put_cache(
                    account_id, NOTES_CACHE_KEY, data.to_json(), SCHEMA_VERSION, fetched_at, NOTES_TTL
                )
            except Exception:  # caching must never break a successful report
                log.warning("cache write failed (%s)", "notes")
            return NotesResult(data, fetched_at, "live")

    @staticmethod
    def _cached_result(row: Mapping[str, Any] | None) -> NotesResult | None:
        if not row or row.get("schema_version") != SCHEMA_VERSION:
            return None
        try:
            return NotesResult(NotesData.from_json(row["payload"]), parse_ts(row["fetched_at"]), "cached")  # type: ignore[arg-type]
        except (KeyError, TypeError, ValueError):
            return None

    async def _fetch_notes(self, account: Mapping[str, Any]) -> NotesData:
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
                # autoauth=False: never change the user's HoYoLAB privacy settings on their behalf.
                notes = await asyncio.wait_for(
                    client.get_genshin_notes(int(account["game_uid"]), autoauth=False),
                    timeout=REQUEST_TIMEOUT_SECONDS,
                )
        except genshin.InvalidCookies:
            await self._db.set_status(account_id, "reauth_required")
            raise ReauthRequired() from None
        except (genshin.TooManyRequests, genshin.VisitsTooFrequently):
            raise UpstreamUnavailable("HoYoLAB is rate limiting requests. Please wait a minute and try again.") from None
        except genshin.GenshinException as exc:
            if "not enabled" in (exc.msg or "").lower():
                raise NotesDisabled() from None
            log.warning("genshin error on notes: %s retcode=%s", type(exc).__name__, exc.retcode)
            raise UpstreamUnavailable() from None
        except (asyncio.TimeoutError, aiohttp.ClientError):
            raise UpstreamUnavailable() from None

        return NotesData.from_genshin(notes)

    async def _load_cookies(self, account_id: str) -> dict[str, str]:
        row = await self._db.get_credentials(account_id)
        if not row:
            await self._db.set_status(account_id, "reauth_required")
            raise ReauthRequired()
        try:
            return self._cipher.decrypt(
                row["ciphertext"], row["nonce"], row["key_version"], account_id=account_id
            )
        except CryptoError:
            log.error("stored credential could not be decrypted for an account")
            await self._db.set_status(account_id, "error")
            raise UpstreamUnavailable("Stored credentials could not be read. Please /link the account again.") from None
