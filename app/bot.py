"""Telegram handlers (python-telegram-bot). Handlers call GenshinProvider, never genshin.py."""

from __future__ import annotations

import asyncio
import io
import logging
import time
from dataclasses import dataclass, field
from datetime import timedelta
from typing import Any

from telegram import (
    BotCommand,
    InlineKeyboardButton,
    InlineKeyboardMarkup,
    LinkPreviewOptions,
    Update,
)
from telegram.constants import ChatAction, ChatType
from telegram.ext import Application, CallbackQueryHandler, CommandHandler, ContextTypes

from app.db import Database
from app.errors import BotError, NoRecords, RateLimited
from app.genshin_provider import GenshinProvider
from app.images import ImageFetcher
from app.linking import TOKEN_TTL, hash_token, new_token, utcnow
from app.regions import mask_uid, server_label, server_utc_offset
from app.render_abyss import render_abyss_card, select_floors
from app.render_notes import render_notes_card

log = logging.getLogger(__name__)

NOTES_COOLDOWN_SECONDS = 10
UUID_PATTERN = r"[0-9a-fA-F-]{36}"

COMMANDS = [
    BotCommand("link", "Connect a Genshin account (private chat)"),
    BotCommand("accounts", "List your linked accounts"),
    BotCommand("setaccount", "Choose your default account"),
    BotCommand("notes", "Daily Notes image (resin, commissions…)"),
    BotCommand("abyss", "Spiral Abyss report image"),
    BotCommand("unlink", "Remove a linked account"),
    BotCommand("privacy", "What is stored and why"),
    BotCommand("help", "Help"),
]

HELP_TEXT = (
    "Hi! I show Genshin Impact data from HoYoLAB (international servers) as images.\n\n"
    "Available now:\n"
    "/link – connect an account (private chat only)\n"
    "/accounts – your linked accounts\n"
    "/setaccount – choose the default account\n"
    "/notes – Daily Notes image (add “pick” to choose an account)\n"
    "/abyss – Spiral Abyss image (options: previous, or a floor number like 12)\n"
    "/unlink – remove an account and its stored session\n"
    "/privacy – what I store\n\n"
    "Coming later: Theater, Stygian, profile, Diary, Wishes, group sharing.\n"
    "Unofficial community tool, not affiliated with HoYoverse."
)

PRIVACY_TEXT = (
    "What this bot stores:\n"
    "• Your Telegram user ID.\n"
    "• For each linked game account: UID, server, nickname.\n"
    "• The HoYoLAB session cookies you provide, encrypted (AES-256-GCM). I never ask for your password.\n"
    "• Short-lived cached report data (Daily Notes: a few minutes).\n"
    "• A minimal audit log (what happened, when, no secrets).\n\n"
    "Why: to read your Battle Chronicle data on your request. The bot only reads; it never changes your account.\n"
    "Risk: those cookies are also your HoYoLAB login. A spare account is safest.\n"
    "Delete: /unlink removes the stored session and cache. It does not sign you out of HoYoLAB; "
    "change your HoYoLAB password if you want to invalidate old sessions.\n"
    "This is an unofficial community tool, not affiliated with HoYoverse."
)


@dataclass
class Deps:
    db: Database
    provider: GenshinProvider
    public_base_url: str
    images: ImageFetcher = field(default_factory=ImageFetcher)
    cooldowns: dict[int, float] = field(default_factory=dict)


def _deps(context: ContextTypes.DEFAULT_TYPE) -> Deps:
    return context.application.bot_data["deps"]


def _private(update: Update) -> bool:
    return bool(update.effective_chat and update.effective_chat.type == ChatType.PRIVATE)


def _label(account: dict[str, Any]) -> str:
    star = "★ " if account.get("is_default") else ""
    name = account.get("nickname") or "Traveler"
    return f"{star}{name} · {mask_uid(account['game_uid'])} · {server_label(account['region'])}"


async def _private_only(update: Update) -> bool:
    if _private(update):
        return True
    if update.effective_message:
        await update.effective_message.reply_text("Please use this command in a private chat with me.")
    return False


async def start(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    await update.effective_message.reply_text(HELP_TEXT)


async def help_cmd(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    await update.effective_message.reply_text(HELP_TEXT)


async def privacy(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    await update.effective_message.reply_text(PRIVACY_TEXT)


async def link(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    if not await _private_only(update):
        return
    deps = _deps(context)
    user_id = update.effective_user.id
    token = new_token()
    try:
        await deps.db.purge_old_link_sessions()
        await deps.db.create_link_session(user_id, hash_token(token), utcnow() + TOKEN_TTL)
    except Exception as exc:
        log.error("could not create link session: %s", type(exc).__name__)
        await update.effective_message.reply_text("Temporary problem. Please try /link again in a minute.")
        return
    minutes = int(TOKEN_TTL.total_seconds() // 60)
    await update.effective_message.reply_text(
        "Open this one-time link to connect your account (valid for "
        f"{minutes} minutes):\n\n{deps.public_base_url}/link/{token}\n\n"
        "I will never ask for your password, and you should not paste cookies into this chat. "
        "Using a spare HoYoLAB account is the safest option.",
        link_preview_options=LinkPreviewOptions(is_disabled=True),
        protect_content=True,
    )


async def accounts(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    if not await _private_only(update):
        return
    rows = await _deps(context).db.list_accounts(update.effective_user.id)
    if not rows:
        await update.effective_message.reply_text("You have no linked accounts yet. Use /link.")
        return
    lines = [f"{i}. {_label(r)}" + ("" if r["status"] == "active" else f"  [{r['status']}]") for i, r in enumerate(rows, 1)]
    await update.effective_message.reply_text("Your accounts (★ = default):\n" + "\n".join(lines))


def _keyboard(prefix: str, rows: list[dict[str, Any]]) -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup([[InlineKeyboardButton(_label(r), callback_data=f"{prefix}:{r['id']}")] for r in rows])


async def setaccount(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    if not await _private_only(update):
        return
    rows = await _deps(context).db.list_accounts(update.effective_user.id)
    if not rows:
        await update.effective_message.reply_text("You have no linked accounts yet. Use /link.")
        return
    await update.effective_message.reply_text("Choose your default account:", reply_markup=_keyboard("setdef", rows))


async def on_setdef(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    query = update.callback_query
    await query.answer()
    deps = _deps(context)
    account_id = query.data.split(":", 1)[1]
    account = await deps.db.get_account_for_user(account_id, query.from_user.id)
    if not account:
        await query.edit_message_text("That account is no longer available.")
        return
    await deps.db.set_default(query.from_user.id, account_id)
    await query.edit_message_text(f"Default account set to {_label({**account, 'is_default': False})}.")


async def unlink(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    if not await _private_only(update):
        return
    rows = await _deps(context).db.list_accounts(update.effective_user.id)
    if not rows:
        await update.effective_message.reply_text("You have no linked accounts.")
        return
    await update.effective_message.reply_text("Which account should I remove?", reply_markup=_keyboard("unlink", rows))


async def on_unlink_ask(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    query = update.callback_query
    await query.answer()
    account_id = query.data.split(":", 1)[1]
    account = await _deps(context).db.get_account_for_user(account_id, query.from_user.id)
    if not account:
        await query.edit_message_text("That account is no longer available.")
        return
    markup = InlineKeyboardMarkup(
        [[
            InlineKeyboardButton("Yes, remove it", callback_data=f"unlinkok:{account_id}"),
            InlineKeyboardButton("Cancel", callback_data="cancel:0"),
        ]]
    )
    await query.edit_message_text(
        f"Remove {_label({**account, 'is_default': False})}?\n"
        "This deletes the stored session and cached data. It does not sign you out of HoYoLAB.",
        reply_markup=markup,
    )


async def on_unlink_confirm(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    query = update.callback_query
    await query.answer()
    deps = _deps(context)
    account_id = query.data.split(":", 1)[1]
    deleted = await deps.db.delete_account(query.from_user.id, account_id)
    if deleted:
        await deps.db.audit(query.from_user.id, "account_unlinked", "game_account", account_id)
        await query.edit_message_text("Account removed. Its stored session and cache were deleted.")
    else:
        await query.edit_message_text("That account is no longer available.")


async def on_cancel(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    query = update.callback_query
    await query.answer()
    await query.edit_message_text("Cancelled.")


def _check_cooldown(deps: Deps, user_id: int) -> None:
    now = time.monotonic()
    last = deps.cooldowns.get(user_id, 0.0)
    if now - last < NOTES_COOLDOWN_SECONDS:
        raise RateLimited()
    deps.cooldowns[user_id] = now
    if len(deps.cooldowns) > 5000:  # keep the dict bounded
        cutoff = now - 3600
        for uid in [u for u, t in deps.cooldowns.items() if t < cutoff]:
            deps.cooldowns.pop(uid, None)


async def _send_notes(context: ContextTypes.DEFAULT_TYPE, chat_id: int, user_id: int, account: dict[str, Any]) -> None:
    deps = _deps(context)
    try:
        _check_cooldown(deps, user_id)
        await context.bot.send_chat_action(chat_id, ChatAction.UPLOAD_PHOTO)
        result = await deps.provider.get_notes(account)
        png = await asyncio.to_thread(
            render_notes_card,
            result.data,
            nickname=account.get("nickname") or "Traveler",
            uid_masked=mask_uid(account["game_uid"]),
            server_label=server_label(account["region"]),
            fetched_at=result.fetched_at,
            source=result.source,
        )
    except BotError as exc:
        await context.bot.send_message(chat_id, exc.user_message)
        return
    except Exception as exc:
        log.error("notes failed: %s", type(exc).__name__)
        await context.bot.send_message(chat_id, "Something went wrong. Please try again later.")
        return

    await context.bot.send_photo(
        chat_id, photo=io.BytesIO(png), caption=f"Daily Notes · {SOURCE_CAPTIONS[result.source]}"
    )


SOURCE_CAPTIONS = {
    "live": "Live data",
    "cached": "Cached data (updated within the last few minutes)",
    "stale": "Stale data: HoYoLAB did not answer, showing the last saved copy",
}


async def _send_abyss(
    context: ContextTypes.DEFAULT_TYPE, chat_id: int, user_id: int, account: dict[str, Any], previous: bool, floor: int | None
) -> None:
    deps = _deps(context)
    try:
        _check_cooldown(deps, user_id)
        await context.bot.send_chat_action(chat_id, ChatAction.UPLOAD_PHOTO)
        result = await deps.provider.get_abyss(account, previous=previous)
        floors = select_floors(result.data, floor)
        if not result.data.has_data or not floors:
            if floor is not None and result.data.has_data:
                raise NoRecords(f"No records for Spiral Abyss floor {floor} in this period.")
            raise NoRecords("No Spiral Abyss records for this period yet.")
        icons = await deps.images.fetch_with_fallbacks(result.data.icon_pairs())
        png = await asyncio.to_thread(
            render_abyss_card,
            result.data,
            nickname=account.get("nickname") or "Traveler",
            icons=icons,
            floors=floors,
            tz_hours=server_utc_offset(account["region"]),
            fetched_at=result.fetched_at,
            source=result.source,
            full_summary=floor is None,
        )
    except BotError as exc:
        await context.bot.send_message(chat_id, exc.user_message)
        return
    except Exception as exc:
        log.error("abyss failed: %s", type(exc).__name__)
        await context.bot.send_message(chat_id, "Something went wrong. Please try again later.")
        return

    period = "Previous" if previous else "Current"
    await context.bot.send_photo(
        chat_id, photo=io.BytesIO(png), caption=f"Spiral Abyss ({period} period) · {SOURCE_CAPTIONS[result.source]}"
    )


def _parse_abyss_args(args: list[str]) -> tuple[bool, int | None]:
    previous, floor = False, None
    for a in args:
        a = a.lower()
        if a in ("previous", "prev", "last"):
            previous = True
        elif a.isdigit() and 1 <= int(a) <= 12:
            floor = int(a)
    return previous, floor


async def abyss(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    message = update.effective_message
    if not _private(update):
        await message.reply_text(
            "Reports in groups need the account owner's sharing permission, which is not available yet. "
            "Please use /abyss in a private chat with me."
        )
        return
    deps = _deps(context)
    user_id = update.effective_user.id
    rows = await deps.db.list_accounts(user_id)
    if not rows:
        await message.reply_text("You have no linked accounts yet. Use /link.")
        return
    previous, floor = _parse_abyss_args(context.args or [])
    account = next((r for r in rows if r["is_default"]), rows[0])
    await _send_abyss(context, update.effective_chat.id, user_id, account, previous, floor)


async def notes(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    message = update.effective_message
    if not _private(update):
        await message.reply_text(
            "Reports in groups need the account owner's sharing permission, which is not available yet. "
            "Please use /notes in a private chat with me."
        )
        return
    deps = _deps(context)
    user_id = update.effective_user.id
    rows = await deps.db.list_accounts(user_id)
    if not rows:
        await message.reply_text("You have no linked accounts yet. Use /link.")
        return
    if context.args and context.args[0].lower() == "pick" and len(rows) > 1:
        await message.reply_text("Which account?", reply_markup=_keyboard("notes", rows))
        return
    account = next((r for r in rows if r["is_default"]), rows[0])
    await _send_notes(context, update.effective_chat.id, user_id, account)


async def on_notes_pick(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    query = update.callback_query
    await query.answer()
    account_id = query.data.split(":", 1)[1]
    account = await _deps(context).db.get_account_for_user(account_id, query.from_user.id)
    if not account:
        await query.edit_message_text("That account is no longer available.")
        return
    await query.edit_message_text(f"Fetching Daily Notes for {_label({**account, 'is_default': False})}…")
    await _send_notes(context, query.message.chat_id, query.from_user.id, account)


async def on_error(update: object, context: ContextTypes.DEFAULT_TYPE) -> None:
    # Class name only: exception text could contain request details.
    log.error("unhandled error in handler: %s", type(context.error).__name__)


def register(application: Application, deps: Deps) -> None:
    application.bot_data["deps"] = deps
    application.add_handler(CommandHandler("start", start))
    application.add_handler(CommandHandler("help", help_cmd))
    application.add_handler(CommandHandler("privacy", privacy))
    application.add_handler(CommandHandler("link", link))
    application.add_handler(CommandHandler("accounts", accounts))
    application.add_handler(CommandHandler("setaccount", setaccount))
    application.add_handler(CommandHandler("unlink", unlink))
    application.add_handler(CommandHandler("notes", notes))
    application.add_handler(CommandHandler("abyss", abyss))
    application.add_handler(CallbackQueryHandler(on_setdef, pattern=rf"^setdef:{UUID_PATTERN}$"))
    application.add_handler(CallbackQueryHandler(on_unlink_ask, pattern=rf"^unlink:{UUID_PATTERN}$"))
    application.add_handler(CallbackQueryHandler(on_unlink_confirm, pattern=rf"^unlinkok:{UUID_PATTERN}$"))
    application.add_handler(CallbackQueryHandler(on_notes_pick, pattern=rf"^notes:{UUID_PATTERN}$"))
    application.add_handler(CallbackQueryHandler(on_cancel, pattern=r"^cancel:0$"))
    application.add_error_handler(on_error)
