"""Keep the persistent icon library complete and current.

* Character table (id -> icon name) comes from genshin.py's updater (Enka/Ambr) and is saved to the store,
  so a restart does not need to download it again.
* Every known character portrait is downloaded once into the store; later runs only fetch new characters.
* Runs automatically (startup + daily) and on demand through the owner-only /updateicons command.
"""

from __future__ import annotations

import asyncio
import json
import logging
from dataclasses import dataclass

from genshin.models.genshin import constants as gc
from genshin.utility import extdb

from app.asset_store import AssetStore, key_for_url
from app.images import ImageFetcher

log = logging.getLogger(__name__)

TABLE_KEY = "meta/characters.json"
LANG = "en-us"
DAILY_SECONDS = 24 * 3600


@dataclass
class SyncReport:
    characters: int = 0
    already_stored: int = 0
    downloaded: int = 0
    failed: int = 0
    table_updated: bool = False
    note: str = ""

    def text(self) -> str:
        head = (
            f"Icon library: {self.characters} characters known, {self.already_stored} already stored, "
            f"{self.downloaded} downloaded now, {self.failed} failed."
        )
        extra = " Character table refreshed." if self.table_updated else " Character table could not be refreshed."
        return head + extra + (f" {self.note}" if self.note else "")


def icon_url(icon_name: str) -> str:
    return f"https://enka.network/ui/UI_AvatarIcon_{icon_name}.png"


def known_icon_urls() -> list[str]:
    table = gc.CHARACTER_NAMES.get(LANG, {})
    names = sorted({c.icon_name for c in table.values() if c.icon_name and not c.icon_name.startswith("Player")})
    return [icon_url(n) for n in names]


async def load_saved_table(store: AssetStore) -> bool:
    """Fill genshin.py's character table from the store if it is empty (saves a download after a restart)."""
    if gc.CHARACTER_NAMES.get(LANG):
        return True
    raw = await store.get(TABLE_KEY)
    if not raw:
        return False
    try:
        data = json.loads(raw)
        gc.CHARACTER_NAMES = {
            lang: {int(i): gc.DBChar(*c) for i, c in chars.items()} for lang, chars in data.items()
        }
        return bool(gc.CHARACTER_NAMES.get(LANG))
    except Exception as exc:
        log.warning("saved character table unreadable (%s)", type(exc).__name__)
        return False


async def sync_icons(fetcher: ImageFetcher, store: AssetStore, force: bool = False) -> SyncReport:
    report = SyncReport()
    try:
        await extdb.update_characters_any(LANG)
        report.table_updated = True
        await store.put(TABLE_KEY, json.dumps(gc.CHARACTER_NAMES).encode(), "application/json")
    except Exception as exc:
        log.warning("character table refresh failed (%s)", type(exc).__name__)
        await load_saved_table(store)

    urls = known_icon_urls()
    report.characters = len(urls)
    if not urls:
        report.note = "No character table available yet."
        return report

    stored = await store.list_keys("icons")
    todo = urls if force else [u for u in urls if key_for_url(u) not in stored]
    report.already_stored = len(urls) - len(todo)

    async def one(url: str) -> bool:
        ok, _ = await fetcher.refresh(url)
        return ok

    results = await asyncio.gather(*(one(u) for u in todo))
    report.downloaded = sum(results)
    report.failed = len(results) - report.downloaded
    if report.failed:
        report.note = "Failed ones are usually brand-new characters whose art is not published yet."
    await fetcher.close_background()
    return report


async def sync_loop(fetcher: ImageFetcher, store: AssetStore) -> None:
    await asyncio.sleep(45)  # let the bot start answering first
    while True:
        try:
            report = await sync_icons(fetcher, store)
            log.info(report.text())
        except Exception as exc:
            log.warning("icon sync failed (%s)", type(exc).__name__)
        await asyncio.sleep(DAILY_SECONDS)
