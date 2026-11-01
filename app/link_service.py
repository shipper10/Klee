"""Turns pasted cookies into linked game accounts (validate -> encrypt -> store)."""

from __future__ import annotations

import asyncio
import logging
from dataclasses import dataclass
from typing import Mapping

import aiohttp
import genshin

from app.crypto import CredentialCipher
from app.db import Database
from app.genshin_provider import make_client
from app.regions import is_international_server, mask_uid, server_label

log = logging.getLogger(__name__)


class LinkError(Exception):
    """Message is safe to show on the web page."""


@dataclass
class LinkedAccount:
    account_id: str
    uid_masked: str
    nickname: str
    server: str


async def link_accounts(
    db: Database, cipher: CredentialCipher, telegram_user_id: int, cookies: Mapping[str, str]
) -> list[LinkedAccount]:
    client = make_client(cookies)
    try:
        accounts = await asyncio.wait_for(client.get_game_accounts(), timeout=25)
    except genshin.InvalidCookies:
        raise LinkError("HoYoLAB did not accept these cookies. Make sure they are current and copied completely.") from None
    except (asyncio.TimeoutError, aiohttp.ClientError):
        raise LinkError("Could not reach HoYoLAB. Please try again in a moment.") from None
    except genshin.GenshinException as exc:
        log.warning("link validation failed: %s retcode=%s", type(exc).__name__, exc.retcode)
        raise LinkError("HoYoLAB rejected the request. Please try again later.") from None

    genshin_accounts = [
        a for a in accounts if a.game == genshin.Game.GENSHIN and is_international_server(a.server)
    ]
    if not genshin_accounts:
        raise LinkError("No Genshin Impact account on an international server was found for these cookies.")

    linked: list[LinkedAccount] = []
    conflicts = 0
    for acc in genshin_accounts:
        uid = str(acc.uid)
        existing = await db.find_account_by_uid(uid)
        if existing and int(existing["telegram_user_id"]) != telegram_user_id:
            conflicts += 1
            continue
        row = await db.upsert_game_account(telegram_user_id, uid, acc.server, acc.nickname)
        account_id = str(row["id"])
        ciphertext, nonce, version = cipher.encrypt(cookies, account_id=account_id)
        await db.store_credentials(account_id, ciphertext, nonce, version)
        await db.audit(telegram_user_id, "account_linked", "game_account", account_id)
        linked.append(LinkedAccount(account_id, mask_uid(uid), acc.nickname, server_label(acc.server)))

    if not linked:
        raise LinkError("These game accounts are already linked to another Telegram user.")

    await db.ensure_default(telegram_user_id)
    return linked
