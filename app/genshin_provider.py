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
from app import profile as profile_mod
from app.profile import ProfileData
from app import theater as theater_mod
from app.theater import TheaterData
from app import diary as diary_mod
from app.diary import DiaryData
from app import stygian as stygian_mod
from app.stygian import StygianData
from app import character as character_mod
from app.character import CharacterDetail
from app.crypto import CredentialCipher, CryptoError
from app.db import Database
from app import timing
from app.regions import server_utc_offset
from app.errors import ChronicleHidden, NotesDisabled, ReauthRequired, UpstreamUnavailable
from app.linking import parse_ts, utcnow
from app.notes import NotesData

log = logging.getLogger(__name__)

NOTES_CACHE_KEY = "notes"
NOTES_TTL = timedelta(minutes=3)
ABYSS_TTL = timedelta(minutes=30)
PROFILE_TTL = timedelta(minutes=10)
THEATER_TTL = timedelta(minutes=30)
STYGIAN_TTL = timedelta(minutes=30)
CHARACTER_TTL = timedelta(minutes=10)
DIARY_TTL = timedelta(minutes=20)
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

    async def get_profile(self, account: Mapping[str, Any]) -> Report[ProfileData]:
        return await self._cached(
            account, "profile", PROFILE_TTL, profile_mod.SCHEMA_VERSION, self._fetch_profile, ProfileData.from_json
        )

    async def get_theater(self, account: Mapping[str, Any], previous: bool = False) -> Report[TheaterData]:
        async def fetch(acc: Mapping[str, Any]) -> TheaterData:
            return await self._fetch_theater(acc, previous)

        key = "theater:previous" if previous else "theater:current"
        return await self._cached(account, key, THEATER_TTL, theater_mod.SCHEMA_VERSION, fetch, TheaterData.from_json)

    async def get_character(self, account: Mapping[str, Any], char_id: int) -> Report[CharacterDetail]:
        async def fetch(acc: Mapping[str, Any]) -> CharacterDetail:
            return await self._fetch_character(acc, char_id)

        return await self._cached(
            account, f"character:{char_id}", CHARACTER_TTL, character_mod.SCHEMA_VERSION, fetch, CharacterDetail.from_json
        )

    async def get_stygian(self, account: Mapping[str, Any], previous: bool = False) -> Report[StygianData]:
        async def fetch(acc: Mapping[str, Any]) -> StygianData:
            return await self._fetch_stygian(acc, previous)

        key = "stygian:previous" if previous else "stygian:current"
        return await self._cached(account, key, STYGIAN_TTL, stygian_mod.SCHEMA_VERSION, fetch, StygianData.from_json)

    async def get_diary(self, account: Mapping[str, Any], previous: bool = False) -> Report[DiaryData]:
        async def fetch(acc: Mapping[str, Any]) -> DiaryData:
            return await self._fetch_diary(acc, previous)

        key = "diary:previous" if previous else "diary:current"
        return await self._cached(account, key, DIARY_TTL, diary_mod.SCHEMA_VERSION, fetch, DiaryData.from_json)

    async def get_stygian_raw(self, account: Mapping[str, Any]) -> Any:
        uid = int(account["game_uid"])

        async def call(client: genshin.Client) -> Any:
            return await client.get_stygian_onslaught(uid, raw=True, need_detail=True)

        return await self._call(account, call)

    async def get_character_raw(self, account: Mapping[str, Any], char_id: int) -> Any:
        """Uncached raw payload, for the owner's /debug check."""
        uid = int(account["game_uid"])

        async def call(client: genshin.Client) -> Any:
            return await client.get_genshin_detailed_characters(uid, characters=[char_id], return_raw_data=True)

        return await self._call(account, call)

    async def get_theater_raw(self, account: Mapping[str, Any]) -> Any:
        """Uncached raw payload, for the owner's /debug check."""
        uid = int(account["game_uid"])

        async def call(client: genshin.Client) -> Any:
            return await client.get_imaginarium_theater(uid, need_detail=True, raw=True)

        return await self._call(account, call)

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
            with timing.timed(cache_key.split(':')[0], 'cache-db'):
                row = await self._db.get_cache(account_id, cache_key)
            cached = self._decode(row, schema_version, from_json)
            if cached and parse_ts(row["expires_at"]) > utcnow():  # type: ignore[index]
                return Report(cached.data, cached.fetched_at, "cached")

            try:
                with timing.timed(cache_key.split(':')[0], 'hoyolab'):
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
            return await client.get_genshin_spiral_abyss(uid, previous=previous, raw=True)

        return AbyssData.from_raw(await self._call(account, call))

    async def _fetch_profile(self, account: Mapping[str, Any]) -> ProfileData:
        uid = int(account["game_uid"])

        async def call(client: genshin.Client) -> Any:
            return await client.get_genshin_user(uid)

        return ProfileData.from_genshin(await self._call(account, call))

    async def _fetch_theater(self, account: Mapping[str, Any], previous: bool = False) -> TheaterData:
        uid = int(account["game_uid"])

        async def call(client: genshin.Client) -> Any:
            # genshin.py warns that `previous` does nothing here: the payload lists several seasons.
            return await client.get_imaginarium_theater(uid, need_detail=True, raw=True)

        return TheaterData.from_raw(await self._call(account, call), previous=previous)

    async def _fetch_character(self, account: Mapping[str, Any], char_id: int) -> CharacterDetail:
        uid = int(account["game_uid"])

        async def call(client: genshin.Client) -> Any:
            return await client.get_genshin_detailed_characters(uid, characters=[char_id], return_raw_data=True)

        detail = CharacterDetail.from_raw(await self._call(account, call), char_id)
        if detail is None:
            raise UpstreamUnavailable("HoYoLAB returned no details for that character.")
        return detail

    async def _fetch_stygian(self, account: Mapping[str, Any], previous: bool = False) -> StygianData:
        uid = int(account["game_uid"])

        async def call(client: genshin.Client) -> Any:
            return await client.get_stygian_onslaught(uid, raw=True, need_detail=True)

        return StygianData.from_raw(await self._call(account, call), previous=previous)

    async def _fetch_diary(self, account: Mapping[str, Any], previous: bool = False) -> DiaryData:
        uid = int(account["game_uid"])
        year, month = diary_mod.month_for(server_utc_offset(account["region"]), previous)

        async def call(client: genshin.Client) -> Any:
            return await client.request_ledger(uid, game=genshin.Game.GENSHIN, month=month)

        data = DiaryData.from_raw(await self._call(account, call))
        data.year = year
        return data

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
