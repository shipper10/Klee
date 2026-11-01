"""Safe, bounded download of game icons used in report images.

Only https URLs on an allow-list of HoYoverse hosts are fetched (the API returns the URLs; this is
defense in depth against SSRF). Results are kept in a small in-memory LRU, never written to disk.
A failed download is not an error: the renderer draws a placeholder instead.
"""

from __future__ import annotations

import asyncio
import io
import logging
from collections import Counter, OrderedDict
from collections.abc import Iterable, Sequence
from dataclasses import dataclass, field
from urllib.parse import urlparse

import aiohttp
from PIL import Image

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


@dataclass
class FetchResult:
    images: dict[str, bytes] = field(default_factory=dict)
    failed: int = 0  # items for which no candidate could be downloaded
    reasons: Counter = field(default_factory=Counter)  # e.g. "HTTP 404 enka.network" -> 3
    names: list[str] = field(default_factory=list)  # file names of the portraits that failed

    def summary(self, limit: int = 4) -> str:
        text = "; ".join(f"{r} x{n}" for r, n in self.reasons.most_common(limit))
        return text + (f" | files: {', '.join(self.names[:4])}" if self.names else "")


def _is_image(data: bytes) -> bool:
    try:
        with Image.open(io.BytesIO(data)) as im:
            im.verify()
        return True
    except Exception:
        return False


def _host(url: str) -> str:
    return (urlparse(url).hostname or "?")[:60]


class ImageFetcher:
    def __init__(self, concurrency: int = 6) -> None:
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

    async def _attempt(self, url: str) -> tuple[bytes | None, str, bool]:  # data, reason (or content-type on success), retry
        """One download. Returns (data, failure_reason, worth_retrying)."""
        if self._session is None or self._session.closed:
            self._session = aiohttp.ClientSession(timeout=TIMEOUT)
        try:
            async with self._sem, self._session.get(url, allow_redirects=False) as resp:
                if resp.status != 200:
                    return None, f"HTTP {resp.status} {_host(url)}", resp.status == 429 or resp.status >= 500
                if resp.content_length is not None and resp.content_length > MAX_BYTES:
                    return None, f"too large {_host(url)}", False
                data = await resp.content.read(MAX_BYTES + 1)
                if len(data) > MAX_BYTES:
                    return None, f"too large {_host(url)}", False
                return data, resp.headers.get("Content-Type", "?").split(";")[0][:30], False
        except (aiohttp.ClientError, asyncio.TimeoutError) as exc:
            return None, f"{type(exc).__name__} {_host(url)}", True

    async def _fetch_one(self, url: str) -> tuple[bytes | None, str]:
        if url in self._cache:
            self._cache.move_to_end(url)
            return self._cache[url], ""
        if not is_allowed_url(url):
            log.info("icon skipped (host not allowed): %s", url[:120])
            return None, f"blocked host {_host(url)}"
        reason = ""
        for attempt in range(2):  # one retry for rate limits, server errors and timeouts
            data, reason, retry = await self._attempt(url)
            if data is not None:
                if not _is_image(data):
                    log.info("icon is not a valid image: %s", url[:120])
                    return None, f"not an image {_host(url)} ({reason}, {len(data)}B, starts {data[:4].hex()})"
                self._remember(url, data)
                return data, ""
            if not retry:
                break
            await asyncio.sleep(0.8)
        log.info("icon download failed (%s): %s", reason, url[:120])
        return None, reason

    async def fetch_many(self, urls: Iterable[str]) -> dict[str, bytes]:
        unique = [u for u in dict.fromkeys(urls) if u]
        results = await asyncio.gather(*(self._fetch_one(u) for u in unique))
        return {u: d for u, (d, _) in zip(unique, results) if d is not None}

    async def fetch_first(self, items: Iterable[tuple[str, Sequence[str]]]) -> FetchResult:
        """For each (key, candidate URLs): try the candidates in order until one downloads.

        Images are returned under `key`. Failures are counted per reason, only for items where every candidate failed.
        """

        async def one(key: str, candidates: Sequence[str]) -> tuple[str, bytes | None, list[str]]:
            reasons: list[str] = []
            for url in candidates:
                data, reason = await self._fetch_one(url)
                if data is not None:
                    return key, data, []
                reasons.append(reason)
            return key, None, reasons

        done = await asyncio.gather(*(one(k, c) for k, c in items if k))
        result = FetchResult()
        for key, data, reasons in done:
            if data is not None:
                result.images[key] = data
            else:
                result.failed += 1
                result.names.append(key.rsplit("/", 1)[-1][:60])
                result.reasons.update(reasons or ["no icon URL"])
        if result.failed:
            log.info("icon download: %d portraits missing (%s)", result.failed, result.summary())
        return result
