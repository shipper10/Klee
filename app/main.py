"""Entry point: one process runs Telegram long polling and the HTTP server (health + link page)."""

from __future__ import annotations

import asyncio
import logging
import re
import signal

from aiohttp import web
from telegram.ext import Application

from app.asset_store import AssetStore
from app.bot import COMMANDS, Deps, register
from app.config import Settings, load_settings
from app.crypto import CredentialCipher
from app.db import Database
from app.genshin_provider import GenshinProvider
from app.icon_sync import load_saved_table, sync_icons, sync_loop
from app.images import ImageFetcher
from app.reminders import reminder_loop
from app.web import WebDeps, build_app

log = logging.getLogger("klee")

_TOKEN_RE = re.compile(r"bot\d+:[A-Za-z0-9_-]+")


class RedactFilter(logging.Filter):
    """Last line of defense: strip Telegram bot tokens from any log line."""

    def filter(self, record: logging.LogRecord) -> bool:
        record.msg = _TOKEN_RE.sub("bot<redacted>", str(record.getMessage()))
        record.args = ()
        return True


def setup_logging(level: str) -> None:
    logging.basicConfig(level=level, format="%(asctime)s %(levelname)s %(name)s: %(message)s")
    for handler in logging.getLogger().handlers:
        handler.addFilter(RedactFilter())
    # httpx logs full request URLs (which contain the bot token) at INFO.
    for noisy in ("httpx", "httpcore", "hpack", "aiohttp.access"):
        logging.getLogger(noisy).setLevel(logging.WARNING)


async def run(settings: Settings) -> None:
    db = await Database.connect(settings.supabase_url, settings.supabase_service_role_key)
    cipher = CredentialCipher(settings.encryption_key, settings.encryption_key_version)
    provider = GenshinProvider(db, cipher)

    application = Application.builder().token(settings.telegram_bot_token).concurrent_updates(True).build()
    store = AssetStore(db.storage)
    await store.ensure_bucket()
    if await load_saved_table(store):
        log.info("character table restored from the asset store")
    fetcher = ImageFetcher(store=store)

    async def icon_sync(force: bool):
        return await sync_icons(fetcher, store, force=force)

    deps = Deps(
        db=db, provider=provider, public_base_url=settings.public_base_url,
        images=fetcher, admin_ids=settings.admin_ids, icon_sync=icon_sync,
    )
    sync_task = asyncio.create_task(sync_loop(fetcher, store))
    register(application, deps)

    await application.initialize()
    web_app = build_app(WebDeps(db=db, cipher=cipher, bot=application.bot))
    # access_log=None: link URLs contain the single-use token and must not reach the logs.
    runner = web.AppRunner(web_app, access_log=None)
    await runner.setup()
    await web.TCPSite(runner, "0.0.0.0", settings.port).start()
    log.info("HTTP server listening on port %s", settings.port)

    await application.start()
    reminder_task = asyncio.create_task(reminder_loop(db, provider, application.bot))
    await application.updater.start_polling(allowed_updates=["message", "callback_query"])
    try:
        await application.bot.set_my_commands(COMMANDS)
    except Exception as exc:
        log.warning("could not set bot commands: %s", type(exc).__name__)
    log.info("Bot is polling")

    stop = asyncio.Event()
    loop = asyncio.get_running_loop()
    for sig in (signal.SIGTERM, signal.SIGINT):
        try:
            loop.add_signal_handler(sig, stop.set)
        except NotImplementedError:  # e.g. Windows
            pass
    await stop.wait()

    log.info("Shutting down")
    sync_task.cancel()
    reminder_task.cancel()
    await application.updater.stop()
    await application.stop()
    await application.shutdown()
    await runner.cleanup()
    await deps.images.close()


def main() -> None:
    settings = load_settings()
    setup_logging(settings.log_level)
    asyncio.run(run(settings))


if __name__ == "__main__":
    main()
