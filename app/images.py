"""Safe, bounded download of game icons used in report images.

Only https URLs on an allow-list of HoYoverse hosts are fetched (the API returns the URLs; this is
defense in depth against SSRF). Results are kept in a small in-memory LRU, never written to disk.
A failed download is not an error: the renderer draws a placeholder instead.
"""

from __future__ import annotations

import asyncio
import logging
from collections import OrderedDict
from collections.abc import Iterable
from urllib.parse import urlparse

import aiohttp

log = logging.getLogger(__name__)

# genshin.py rewrites character icons to enka.network (verified in genshin/models/genshin/character.py:
# ENKA_ICON_BASE / AMBR_ICON_BASE), so those hosts must be allowed besides HoYoverse's own CDNs.
ALLOWED_HOST_SUFFIXES = (".hoyoverse.com", ".hoyolab.com", ".mihoyo.com")
ALLOWED_HOSTS = ("enka.network", "gi.yatta.moe")
MAX_BYTES = 3 * 1024 * 1024
CACHE_SIZE = 300
TIMEOUT = aiohttp.ClientTimeout(total=12)


def is_allowed_url(url: str) -> bool:
    try:
        parsed = urlparse(url)
    except ValueError:
        return False
    host = (parsed.hostname or "").lower()
    if parsed.scheme != "https":
        return False
    return host in ALLOWED_HOSTS or any(host.endswith(s) for s in ALLOWED_HOST_SUFFIXES)


class ImageFetcher:
    def __init__(self, concurrency: int = 8) -> None:
        self._cache: OrderedDict[str, bytes] = OrderedDict()
        self._sem = asyncio.Semaphore(concurrency)
        self._session: aiohttp.ClientSession | None = None

    async def close(self) -> None:
        if self._session and not self._session.closed:
            await self._session.close()

    def _remember(self, url: str, data: bytes) -> None:
        self._cache[url] = data
        self._cache.move_to_end(url)
        while len(self._cache) > CACHE_SIZE:
            self._cache.popitem(last=False)

    async def _fetch_one(self, url: str) -> bytes | None:
        if url in self._cache:
            self._cache.move_to_end(url)
            return self._cache[url]
        if not is_allowed_url(url):
            return None
        if self._session is None or self._session.closed:
            self._session = aiohttp.ClientSession(timeout=TIMEOUT)
        try:
            async with self._sem, self._session.get(url, allow_redirects=False) as resp:
                if resp.status != 200:
                    return None
                declared = resp.content_length
                if declared is not None and declared > MAX_BYTES:
                    return None
                data = await resp.content.read(MAX_BYTES + 1)
                if len(data) > MAX_BYTES:
                    return None
        except (aiohttp.ClientError, asyncio.TimeoutError):
            return None
        self._remember(url, data)
        return data

    async def fetch_many(self, urls: Iterable[str]) -> dict[str, bytes]:
        unique = [u for u in dict.fromkeys(urls) if u]
        results = await asyncio.gather(*(self._fetch_one(u) for u in unique))
        found = {u: d for u, d in zip(unique, results) if d is not None}
        if len(found) < len(unique):
            log.info("icon download: %d of %d failed", len(unique) - len(found), len(unique))
        return found
