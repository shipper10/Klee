"""Persistent store for downloaded game assets (portraits, character table), kept in Supabase Storage.

Render's free disk is wiped on every restart/redeploy, so assets live in a private Supabase Storage bucket.
Every method swallows storage errors: a broken store must never break a report, it only means "download again".
"""

from __future__ import annotations

import logging
import re
from typing import Any

log = logging.getLogger(__name__)

BUCKET = "game-assets"


def key_for_url(url: str) -> str:
    """Stable, storage-safe object key for an icon URL: icons/<host>__<path>."""
    safe = re.sub(r"[^A-Za-z0-9._-]+", "_", re.sub(r"^https?://", "", url))[:160]
    return f"icons/{safe}"


class AssetStore:
    def __init__(self, storage: Any, bucket: str = BUCKET) -> None:
        self._storage = storage
        self._bucket = bucket

    def _files(self) -> Any:
        return self._storage.from_(self._bucket)

    async def ensure_bucket(self) -> None:
        try:
            await self._storage.create_bucket(self._bucket, options={"public": False})
            log.info("created storage bucket %s", self._bucket)
        except Exception as exc:  # already exists is the normal case
            log.debug("bucket not created (%s)", type(exc).__name__)

    async def get(self, key: str) -> bytes | None:
        try:
            return await self._files().download(key)
        except Exception:
            return None

    async def put(self, key: str, data: bytes, content_type: str = "image/png") -> bool:
        try:
            await self._files().upload(key, data, {"content-type": content_type, "upsert": "true"})
            return True
        except Exception as exc:
            log.warning("asset store write failed (%s)", type(exc).__name__)
            return False

    async def list_keys(self, folder: str) -> set[str]:
        """All object keys directly under `folder` (paged)."""
        found: set[str] = set()
        offset = 0
        try:
            while True:
                page = await self._files().list(folder, {"limit": 1000, "offset": offset})
                found.update(f"{folder}/{item['name']}" for item in page if item.get("name"))
                if len(page) < 1000:
                    return found
                offset += 1000
        except Exception as exc:
            log.warning("asset store list failed (%s)", type(exc).__name__)
            return found
