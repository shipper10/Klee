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
from telegram.error import BadRequest
from telegram.ext import Application, CallbackQueryHandler, CommandHandler, ContextTypes

from app.db import Database
from app.errors import BotError, NoRecords, RateLimited
from app.genshin_provider import GenshinProvider
from app.images import ImageFetcher
from app.linking import TOKEN_TTL, hash_token, new_token, utcnow
from app.regions import mask_uid, server_label, server_utc_offset
from app.styles import label as style_label
from app.styles import resolve as resolve_style
from app.styles import SERVICE_STYLES, known as styles_known
from app import reminders, settings_menu, timing
from app.stygian import describe_raw as describe_stygian_raw
from app.theater import describe_raw as describe_theater_raw
from app.character import describe_raw as describe_character_raw, splash_for
from app.render_stygian_official import render_stygian_official
from app.render_showcase import render_character_showcase
from app.build_card.template import render_character_build
from app.asset_manager import plan_character_art
from app.render_showcase_profile import render_profile_showcase, splash_key
from app.render_diary import render_diary_card
from app.render_abyss import render_abyss_card, select_floors
from app.render_notes import render_notes_card
from app.render_character import render_character_card
from app.profile import find_characters
from app.render_stygian import render_stygian_card
from app.render_theater import render_theater_card, select_acts
from app.render_profile import render_profile_card, select_characters

log = logging.getLogger(__name__)

NOTES_COOLDOWN_SECONDS = 10
UUID_PATTERN = r"[0-9a-fA-F-]{36}"

COMMANDS = [
    BotCommand("link", "Connect a Genshin account (private chat)"),
    BotCommand("accounts", "List your linked accounts"),
    BotCommand("setaccount", "Choose your default account"),
    BotCommand("notes", "Daily Notes image (resin, commissions…)"),
    BotCommand("abyss", "Spiral Abyss report image"),
    BotCommand("theater", "Imaginarium Theater report image"),
    BotCommand("stygian", "Stygian Onslaught report image"),
    BotCommand("diary", "Traveler's Diary: primogems and mora income"),
    BotCommand("profile", "Profile overview + top characters"),
    BotCommand("characters", "All your characters"),
    BotCommand("character", "Details of one character: /character Furina"),
    BotCommand("settings", "Settings: image style, group sharing"),
    BotCommand("share", "Let group members view your reports (on/off)"),
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
    "/theater – Imaginarium Theater image (options: previous, all)\n"
    "/stygian – Stygian Onslaught image (options: previous, coop)\n"
    "/diary – primogems and mora income this month (option: previous)\n"
    "/profile – account overview with your top characters\n"
    "/characters – all your characters\n"
    "/character <name> – weapon, artifacts, talents and stats of one character (add: compare, to see every style)\n"
    "/settings – image style (look of the reports) and group sharing, with buttons\n"
    "/share on|off – let group members view your reports (reply to your message with a command)\n"
    "/groupreports on|off – group admins: enable or disable the bot in a group\n"
    "/unlink – remove an account and its stored session\n"
    "/privacy – what I store\n\n"
    "In groups: use the same commands for yourself, or reply to someone's message with a command "
    "if they turned on /share. Linking stays in private chat.\n"
    "Coming later: Wishes, easier phone linking.\n"
    "Unofficial community tool, not affiliated with HoYoverse."
)

PRIVACY_TEXT = (
    "What this bot stores:\n"
    "• Your Telegram user ID.\n"
    "• For each linked game account: UID, server, nickname.\n"
    "• The HoYoLAB session cookies you provide (or get by signing in on the link page), encrypted (AES-256-GCM).\n"
    "• Your HoYoverse password is never stored or logged. If you sign in with it, it is sent to HoYoverse only to get "
    "those cookies and, if a captcha is needed, waits in memory for a few minutes at most.\n"
    "• Short-lived cached report data (Daily Notes: a few minutes).\n"
    "• Whether you allowed group sharing (/share, off by default) and each group's on/off setting.\n"
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
    admin_ids: tuple[int, ...] = ()
    chat_cooldowns: dict[int, float] = field(default_factory=dict)
    icon_sync: Any = None  # async (force: bool) -> object with .text(); None when no persistent store


def _deps(context: ContextTypes.DEFAULT_TYPE) -> Deps:
    return context.application.bot_data["deps"]


def _private(update: Update) -> bool:
    return bool(update.effective_chat and update.effective_chat.type == ChatType.PRIVATE)


GROUP_CHAT_SECONDS = 3.0  # at most one report per group every few seconds, whoever asks


def _in_group(update: Update) -> bool:
    return bool(update.effective_chat and update.effective_chat.type in (ChatType.GROUP, ChatType.SUPERGROUP))


def _pick_default(rows: list[dict[str, Any]]) -> dict[str, Any]:
    return next((r for r in rows if r["is_default"]), rows[0])


async def _resolve(update: Update, context: ContextTypes.DEFAULT_TYPE) -> tuple[dict[str, Any], int] | None:
    """Which account should a report command use? Returns (account, asking_user_id) or None after replying.

    Private chat: your own default account. Group: your own account, or (when you reply to someone's message)
    that person's account, but only if they turned on /share. Groups can be switched off by an admin.
    """
    message, deps = update.effective_message, _deps(context)
    me = update.effective_user.id
    if _private(update):
        rows = await deps.db.list_accounts(me)
        if not rows:
            await message.reply_text("You have no linked accounts yet. Use /link.")
            return None
        return _pick_default(rows), me
    if not _in_group(update):
        return None
    chat_id = update.effective_chat.id
    if not await deps.db.group_reports_enabled(chat_id):
        await message.reply_text("Reports are turned off in this group by an admin.")
        return None
    now = time.monotonic()
    if now - deps.chat_cooldowns.get(chat_id, 0.0) < GROUP_CHAT_SECONDS:
        return None  # silent: avoids flooding the group
    deps.chat_cooldowns[chat_id] = now
    if len(deps.chat_cooldowns) > 2000:
        for cid in [c for c, t in deps.chat_cooldowns.items() if t < now - 3600]:
            deps.chat_cooldowns.pop(cid, None)

    target = message.reply_to_message.from_user if message.reply_to_message else None
    if target is not None and not target.is_bot and target.id != me:
        rows = [r for r in await deps.db.list_accounts(target.id) if r.get("shared_in_groups")]
        if not rows:
            await message.reply_text(
                f"{target.first_name or 'That user'} has not linked an account or has not allowed sharing in groups."
            )
            return None
        return _pick_default(rows), me
    rows = await deps.db.list_accounts(me)
    if not rows:
        await message.reply_text("You have no linked accounts yet. Open a private chat with me and use /link.")
        return None
    return _pick_default(rows), me


async def share(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """/share on|off: let other group members view your reports by replying to your message with a command."""
    if not await _private_only(update):
        return
    deps, user_id = _deps(context), update.effective_user.id
    rows = await deps.db.list_accounts(user_id)
    if not rows:
        await update.effective_message.reply_text("You have no linked accounts yet. Use /link.")
        return
    arg = context.args[0].lower() if context.args else ""
    if arg in ("on", "off"):
        try:
            await deps.db.set_sharing(user_id, arg == "on")
        except Exception as exc:
            log.error("set_sharing failed: %s", type(exc).__name__)
            await update.effective_message.reply_text("Sharing is not available yet (the database update has not been applied).")
            return
        rows = await deps.db.list_accounts(user_id)
    on = any(r.get("shared_in_groups") for r in rows)
    await update.effective_message.reply_text(
        f"Sharing in groups is {'ON' if on else 'OFF'}.\n"
        "When ON, someone in a group chat who replies to one of your messages with a report command "
        "(for example /abyss) sees the report for your default account: your nickname, a partly hidden UID, "
        "server and game data. Nothing else is shared, and nobody can see your cookies.\n"
        "Use /share on or /share off. You can always use the commands for yourself in any group."
    )


async def groupreports(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """/groupreports on|off: group admins switch the bot's reports on or off for this group."""
    if not _in_group(update):
        await update.effective_message.reply_text("Use this command inside the group you want to change.")
        return
    deps, chat_id, user_id = _deps(context), update.effective_chat.id, update.effective_user.id
    try:
        member = await context.bot.get_chat_member(chat_id, user_id)
        is_admin = member.status in ("administrator", "creator")
    except Exception:
        is_admin = False
    if not is_admin:
        await update.effective_message.reply_text("Only group admins can change this.")
        return
    arg = context.args[0].lower() if context.args else ""
    if arg in ("on", "off"):
        try:
            await deps.db.set_group_reports(chat_id, arg == "on", user_id)
        except Exception as exc:
            log.error("set_group_reports failed: %s", type(exc).__name__)
            await update.effective_message.reply_text("Could not save the setting (the database update has not been applied).")
            return
    enabled = await deps.db.group_reports_enabled(chat_id)
    await update.effective_message.reply_text(
        f"Reports are {'ON' if enabled else 'OFF'} in this group. Use /groupreports on or /groupreports off."
    )


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


async def myid(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    await update.effective_message.reply_text(f"Your Telegram id: {update.effective_user.id}")


async def _icons(deps: Deps, items: Any) -> Any:
    with timing.timed("report", "icons"):
        return await deps.images.fetch_first(items)


async def _timed_render(fn: Any, *args: Any, **kwargs: Any) -> Any:
    with timing.timed(fn.__name__.replace("render_", "").replace("_card", ""), "render"):
        return await asyncio.to_thread(fn, *args, **kwargs)


async def debug(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """Owner-only troubleshooting: /debug timing | /debug theater."""
    deps = _deps(context)
    if not _private(update) or update.effective_user.id not in deps.admin_ids:
        return
    what = (context.args[0].lower() if context.args else "")
    message = update.effective_message
    if what == "timing":
        await message.reply_text(timing.summary())
    elif what == "stygian":
        rows = await deps.db.list_accounts(update.effective_user.id)
        if not rows:
            await message.reply_text("Link an account first.")
            return
        try:
            raw = await deps.provider.get_stygian_raw(_pick_default(rows))
            await message.reply_text(describe_stygian_raw(raw))
        except BotError as exc:
            await message.reply_text(exc.user_message)
        except Exception as exc:
            await message.reply_text(f"Failed: {type(exc).__name__}")
    elif what == "character":
        rows = await deps.db.list_accounts(update.effective_user.id)
        query = " ".join(context.args[1:])
        if not rows or not query:
            await message.reply_text("Usage: /debug character <name> (needs a linked account)")
            return
        try:
            account = _pick_default(rows)
            matches = find_characters((await deps.provider.get_profile(account)).data, query)
            if not matches:
                await message.reply_text("No such character on this account.")
                return
            raw = await deps.provider.get_character_raw(account, matches[0].id)
            await message.reply_text(describe_character_raw(raw, matches[0].id))
        except BotError as exc:
            await message.reply_text(exc.user_message)
        except Exception as exc:
            await message.reply_text(f"Failed: {type(exc).__name__}")
    elif what == "theater":
        rows = await deps.db.list_accounts(update.effective_user.id)
        if not rows:
            await message.reply_text("Link an account first.")
            return
        try:
            raw = await deps.provider.get_theater_raw(_pick_default(rows))
            await message.reply_text(describe_theater_raw(raw))
        except BotError as exc:
            await message.reply_text(exc.user_message)
        except Exception as exc:
            await message.reply_text(f"Failed: {type(exc).__name__}")
    else:
        await message.reply_text("Usage: /debug timing | /debug theater | /debug stygian | /debug character <name>")


async def updateicons(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """Owner-only: refresh the stored character table and portraits. `/updateicons force` re-downloads everything."""
    deps = _deps(context)
    if not _private(update) or update.effective_user.id not in deps.admin_ids:
        return  # silent for everyone else
    if deps.icon_sync is None:
        await update.effective_message.reply_text("The icon library is not enabled.")
        return
    force = bool(context.args) and context.args[0].lower() == "force"
    await update.effective_message.reply_text("Updating the icon library…" + (" (full refresh)" if force else ""))
    try:
        report = await deps.icon_sync(force)
        await update.effective_message.reply_text(report.text())
    except Exception as exc:
        await update.effective_message.reply_text(f"Update failed: {type(exc).__name__}")


async def settings(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    if not await _private_only(update):
        return
    deps, user_id = _deps(context), update.effective_user.id
    text, markup = settings_menu.home(user_id in deps.admin_ids, await _sharing_state(deps, user_id), await _reminder_state(deps, user_id))
    await update.effective_message.reply_text(text, reply_markup=markup)


async def _sharing_state(deps: Deps, user_id: int) -> bool | None:
    """True/False when the user has linked accounts, None when there is nothing to share yet."""
    rows = await deps.db.list_accounts(user_id)
    if not rows:
        return None
    return any(r.get("shared_in_groups") for r in rows)


async def _reminder_state(deps: Deps, user_id: int) -> str | None:
    """Option name when the user has a linked account (reminders need one), else None (button hidden)."""
    if not await deps.db.list_accounts(user_id):
        return None
    row = await deps.db.get_reminder(user_id)
    return reminders.to_option(int(row["resin_threshold"])) if row else "off"


async def on_settings(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    query = update.callback_query
    deps, user_id = _deps(context), query.from_user.id
    if not (query.message and query.message.chat.type == ChatType.PRIVATE):
        await query.answer("Open /settings in a private chat with me.", show_alert=True)
        return
    parts = query.data.split(":")[1:]  # after "st"
    action = parts[0] if parts else ""
    is_owner = user_id in deps.admin_ids
    try:
        if action == "close":
            await query.answer()
            await query.delete_message()
            return
        if action == "prev":
            await query.answer()
            png = await asyncio.to_thread(settings_menu.render_style_preview)
            await context.bot.send_photo(query.message.chat.id, photo=io.BytesIO(png), caption="The available image styles")
            return
        if action == "rem" and len(parts) <= 2:
            await query.answer()
            if len(parts) == 2:
                if parts[1] not in reminders.OPTIONS or await _reminder_state(deps, user_id) is None:
                    await query.answer("Link an account first with /link.", show_alert=True)
                    return
                await deps.db.set_reminder(user_id, reminders.to_threshold(parts[1]))
            text, markup = settings_menu.reminder_page(await _reminder_state(deps, user_id) or "off")
            await query.edit_message_text(text, reply_markup=markup)
            return
        if action == "share" and len(parts) == 2 and parts[1] in ("0", "1"):
            if await _sharing_state(deps, user_id) is None:
                await query.answer("Link an account first with /link.", show_alert=True)
                return
            await deps.db.set_sharing(user_id, parts[1] == "1")
            await query.answer("Saved")
            view = "home"
        elif action in ("own", "set") and (action == "own" or (len(parts) == 4 and parts[1] == "g")) and not is_owner:
            await query.answer("Only the bot owner can change this.", show_alert=True)
            return
        elif action == "set":
            if len(parts) != 4 or parts[1] not in ("u", "g") or not settings_menu.valid_svc(parts[2]):
                await query.answer()
                return
            scope, svc, style = parts[1], settings_menu.svc_key(parts[2]), parts[3]
            if style != "default" and not (styles_known(style) and style in SERVICE_STYLES.get(svc if svc != "*" else "notes", [])):
                await query.answer()
                return
            await deps.db.set_style_pref(0 if scope == "g" else user_id, svc, None if style == "default" else style)
            await query.answer("Saved")
            view = f"{'own' if scope == 'g' else 'me'}:{parts[2]}"
        else:
            await query.answer()
            view = ":".join(parts) or "home"
        rows = await deps.db.get_style_prefs(user_id)
        vparts = view.split(":")
        if vparts[0] == "home":
            text, markup = settings_menu.home(is_owner, await _sharing_state(deps, user_id), await _reminder_state(deps, user_id))
        elif vparts[0] in ("me", "own") and len(vparts) == 1:
            text, markup = settings_menu.service_list("g" if vparts[0] == "own" else "u", rows, user_id)
        elif vparts[0] in ("me", "own") and len(vparts) == 2 and settings_menu.valid_svc(vparts[1]):
            text, markup = settings_menu.style_page("g" if vparts[0] == "own" else "u", vparts[1], rows, user_id)
        else:
            return
        await query.edit_message_text(text, reply_markup=markup)
    except BadRequest:
        pass  # "message is not modified" when the same page is shown again
    except Exception as exc:
        log.error("settings failed: %s", type(exc).__name__)
        await query.answer("That did not work. Please try again.", show_alert=True)


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
        "On that page you can sign in with your HoYoverse e-mail and password, or paste cookies. "
        "Never send a password or cookies in this chat: only on that page. "
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
        style = await resolve_style(deps.db, user_id, "notes")
        png = await _timed_render(
            render_notes_card,
            result.data,
            nickname=account.get("nickname") or "Traveler",
            uid_masked=mask_uid(account["game_uid"]),
            server_label=server_label(account["region"]),
            fetched_at=result.fetched_at,
            source=result.source,
            style=style,
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
        fetched = await _icons(deps, result.data.icon_candidates())
        icons = fetched.images
        style = await resolve_style(deps.db, user_id, "abyss")
        png = await _timed_render(
            render_abyss_card,
            result.data,
            nickname=account.get("nickname") or "Traveler",
            icons=icons,
            floors=floors,
            tz_hours=server_utc_offset(account["region"]),
            fetched_at=result.fetched_at,
            source=result.source,
            full_summary=floor is None,
            style=style,
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
    if fetched.failed:
        # Diagnostics in the chat itself: only icon hosts and HTTP codes, nothing secret.
        await context.bot.send_message(
            chat_id,
            f"Note: {fetched.failed} character portrait(s) could not be loaded and show as blank tiles "
            f"({fetched.summary()}). Please send this line to the developer.",
        )


async def _send_profile(
    context: ContextTypes.DEFAULT_TYPE, chat_id: int, user_id: int, account: dict[str, Any], show_all: bool
) -> None:
    deps = _deps(context)
    try:
        _check_cooldown(deps, user_id)
        await context.bot.send_chat_action(chat_id, ChatAction.UPLOAD_PHOTO)
        result = await deps.provider.get_profile(account)
        chars = select_characters(result.data, show_all)
        style = await resolve_style(deps.db, user_id, "profile")
        wanted = [(c.icon, c.candidates) for c in chars if c.icon]
        if style == "showcase" and chars:
            wanted += splash_for(chars[0].candidates, splash_key(chars[0]))
        fetched = await _icons(deps, wanted)
        png = await _timed_render(
            render_profile_showcase if style == "showcase" else render_profile_card,
            result.data,
            nickname=account.get("nickname") or result.data.nickname or "Traveler",
            uid=str(account["game_uid"]),
            server=account["region"],
            icons=fetched.images,
            characters=chars,
            fetched_at=result.fetched_at,
            source=result.source,
            summary=not show_all,
            style=style,
        )
    except BotError as exc:
        await context.bot.send_message(chat_id, exc.user_message)
        return
    except Exception as exc:
        log.error("profile failed: %s", type(exc).__name__)
        await context.bot.send_message(chat_id, "Something went wrong. Please try again later.")
        return

    title = "All characters" if show_all else "Profile"
    await context.bot.send_photo(chat_id, photo=io.BytesIO(png), caption=f"{title} · {SOURCE_CAPTIONS[result.source]}")
    if fetched.failed:
        await context.bot.send_message(
            chat_id,
            f"Note: {fetched.failed} character portrait(s) could not be loaded and show as blank tiles "
            f"({fetched.summary()}). Please send this line to the developer.",
        )


async def _send_theater(
    context: ContextTypes.DEFAULT_TYPE, chat_id: int, user_id: int, account: dict[str, Any], show_all: bool,
    previous: bool = False,
) -> None:
    deps = _deps(context)
    try:
        _check_cooldown(deps, user_id)
        await context.bot.send_chat_action(chat_id, ChatAction.UPLOAD_PHOTO)
        result = await deps.provider.get_theater(account, previous=previous)
        if not result.data.unlocked:
            raise NoRecords("Imaginarium Theater is not unlocked on this account yet.")
        acts = select_acts(result.data, show_all)
        if not result.data.has_data:
            raise NoRecords(
                "No Imaginarium Theater records for the " + ("previous" if previous else "current")
                + " season." + ("" if previous else " Try /theater previous.")
            )
        fetched = await _icons(deps, result.data.icon_candidates())
        style = await resolve_style(deps.db, user_id, "theater")
        png = await _timed_render(
            render_theater_card,
            result.data,
            nickname=account.get("nickname") or "Traveler",
            icons=fetched.images,
            acts=acts,
            tz_hours=server_utc_offset(account["region"]),
            fetched_at=result.fetched_at,
            source=result.source,
            style=style,
        )
    except BotError as exc:
        await context.bot.send_message(chat_id, exc.user_message)
        return
    except Exception as exc:
        log.error("theater failed: %s", type(exc).__name__)
        await context.bot.send_message(chat_id, "Something went wrong. Please try again later.")
        return

    await context.bot.send_photo(chat_id, photo=io.BytesIO(png), caption=f"Imaginarium Theater ({'Previous' if previous else 'Current'} season) · {SOURCE_CAPTIONS[result.source]}"
        + ("" if acts else "\nAct-by-act details are not provided by HoYoLAB for this season yet; showing the summary only."))
    if fetched.failed:
        await context.bot.send_message(
            chat_id,
            f"Note: {fetched.failed} character portrait(s) could not be loaded and show as blank tiles "
            f"({fetched.summary()}). Please send this line to the developer.",
        )


async def theater(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    message = update.effective_message
    resolved = await _resolve(update, context)
    if resolved is None:
        return
    account, user_id = resolved
    args = [a.lower() for a in context.args or []]
    show_all = "all" in args
    previous = any(a in ("previous", "prev", "last") for a in args)
    await _send_theater(context, update.effective_chat.id, user_id, account, show_all, previous)


async def _send_diary(context: ContextTypes.DEFAULT_TYPE, chat_id: int, user_id: int, account: dict[str, Any], previous: bool) -> None:
    deps = _deps(context)
    try:
        _check_cooldown(deps, user_id)
        await context.bot.send_chat_action(chat_id, ChatAction.UPLOAD_PHOTO)
        result = await deps.provider.get_diary(account, previous=previous)
        if not result.data.found:
            raise NoRecords("No Traveler's Diary data for that month yet." + ("" if previous else " Try /diary previous."))
        style = await resolve_style(deps.db, user_id, "diary")
        png = await _timed_render(
            render_diary_card,
            result.data,
            nickname=account.get("nickname") or "Traveler",
            fetched_at=result.fetched_at,
            source=result.source,
            style=style,
        )
    except BotError as exc:
        await context.bot.send_message(chat_id, exc.user_message)
        return
    except Exception as exc:
        log.error("diary failed: %s", type(exc).__name__)
        await context.bot.send_message(chat_id, "Something went wrong. Please try again later.")
        return

    await context.bot.send_photo(
        chat_id, photo=io.BytesIO(png),
        caption=f"Traveler's Diary ({'previous' if previous else 'this'} month) · {SOURCE_CAPTIONS[result.source]}",
    )


async def diary(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    resolved = await _resolve(update, context)
    if resolved is None:
        return
    account, user_id = resolved
    previous = any(a.lower() in ("previous", "prev", "last") for a in context.args or [])
    await _send_diary(context, update.effective_chat.id, user_id, account, previous)


async def _send_stygian(
    context: ContextTypes.DEFAULT_TYPE, chat_id: int, user_id: int, account: dict[str, Any], multi: bool, previous: bool
) -> None:
    deps = _deps(context)
    try:
        _check_cooldown(deps, user_id)
        await context.bot.send_chat_action(chat_id, ChatAction.UPLOAD_PHOTO)
        result = await deps.provider.get_stygian(account, previous=previous)
        when = "previous" if previous else "current"
        if not result.data.found:
            raise NoRecords(f"No Stygian Onslaught season found for the {when} period." + ("" if previous else " Try /stygian previous."))
        if not result.data.mode(multi).has_data:
            other = ""
            if result.data.mode(not multi).has_data:
                other = " Try /stygian" + ("" if multi else " coop") + "."
            raise NoRecords(f"No {'co-op' if multi else 'single player'} Stygian Onslaught records for the {when} season.{other}")
        fetched = await _icons(deps, result.data.icon_candidates(multi))
        style = await resolve_style(deps.db, user_id, "stygian")
        png = await _timed_render(
            render_stygian_official if style == "official" else render_stygian_card,
            result.data,
            nickname=account.get("nickname") or "Traveler",
            icons=fetched.images,
            multi=multi,
            tz_hours=server_utc_offset(account["region"]),
            fetched_at=result.fetched_at,
            source=result.source,
            uid=str(account["game_uid"]),
            style=style,
        )
    except BotError as exc:
        await context.bot.send_message(chat_id, exc.user_message)
        return
    except Exception as exc:
        log.error("stygian failed: %s", type(exc).__name__)
        await context.bot.send_message(chat_id, "Something went wrong. Please try again later.")
        return

    await context.bot.send_photo(
        chat_id, photo=io.BytesIO(png),
        caption=f"Stygian Onslaught ({'Previous' if previous else 'Current'} season, {'co-op' if multi else 'single'}) · {SOURCE_CAPTIONS[result.source]}",
    )
    if fetched.failed:
        await context.bot.send_message(
            chat_id,
            f"Note: {fetched.failed} character portrait(s) could not be loaded and show as blank tiles "
            f"({fetched.summary()}). Please send this line to the developer.",
        )


async def stygian(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    message = update.effective_message
    resolved = await _resolve(update, context)
    if resolved is None:
        return
    account, user_id = resolved
    args = [a.lower() for a in context.args or []]
    previous = any(a in ("previous", "prev", "last") for a in args)
    multi = any(a in ("coop", "co-op", "multi", "mp") for a in args)
    await _send_stygian(context, update.effective_chat.id, user_id, account, multi, previous)


async def _send_character(
    context: ContextTypes.DEFAULT_TYPE, chat_id: int, user_id: int, account: dict[str, Any], query: str
) -> None:
    deps = _deps(context)
    words = query.split()
    compare = bool(words) and words[-1].lower() == "compare"
    if compare:
        query = " ".join(words[:-1])
    try:
        profile_report = await deps.provider.get_profile(account)  # cached; gives names and ids
        matches = find_characters(profile_report.data, query)
        if not query.strip():
            top = ", ".join(c.name for c in profile_report.data.sorted_characters()[:10])
            raise NoRecords(f"Tell me which character, e.g. /character Furina\nYour top characters: {top}")
        if not matches:
            raise NoRecords(f"I could not find a character named “{query[:40]}” on this account. Check the spelling (English name).")
        if len(matches) > 1 and len({m.name for m in matches}) > 1:
            names = ", ".join(m.name for m in matches[:8])
            raise NoRecords(f"Several characters match: {names}. Please type the full name.")
        _check_cooldown(deps, user_id)
        await context.bot.send_chat_action(chat_id, ChatAction.UPLOAD_PHOTO)
        result = await deps.provider.get_character(account, matches[0].id)
        chosen = await resolve_style(deps.db, user_id, "character")
        styles = ["classic", "showcase", "build"] if compare else [chosen]
        wanted = result.data.icon_candidates()
        if "showcase" in styles:
            wanted += result.data.splash_candidates()
        if "build" in styles:
            wanted += result.data.extra_icon_candidates() + plan_character_art(result.data)
        fetched = await _icons(deps, wanted)
        common = dict(
            nickname=account.get("nickname") or "Traveler", uid=str(account["game_uid"]), server=account["region"],
            icons=fetched.images, fetched_at=result.fetched_at, source=result.source,
        )
        renderers = {"showcase": render_character_showcase, "build": render_character_build}
        pngs = [
            await _timed_render(renderers.get(st, render_character_card), result.data, **common, style=st)
            for st in styles
        ]
    except BotError as exc:
        await context.bot.send_message(chat_id, exc.user_message)
        return
    except Exception as exc:
        log.error("character failed: %s", type(exc).__name__)
        await context.bot.send_message(chat_id, "Something went wrong. Please try again later.")
        return

    for st, png in zip(styles, pngs):
        tag = f" [{style_label(st)}]" if compare else ""
        await context.bot.send_photo(chat_id, photo=io.BytesIO(png), caption=f"{result.data.name}{tag} · {SOURCE_CAPTIONS[result.source]}")
    if fetched.failed:
        await context.bot.send_message(
            chat_id,
            f"Note: {fetched.failed} image(s) could not be loaded and show as blank tiles "
            f"({fetched.summary()}). Please send this line to the developer.",
        )


async def character(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    message = update.effective_message
    resolved = await _resolve(update, context)
    if resolved is None:
        return
    account, user_id = resolved
    await _send_character(context, update.effective_chat.id, user_id, account, " ".join(context.args or []))


async def _profile_entry(update: Update, context: ContextTypes.DEFAULT_TYPE, show_all: bool, command: str) -> None:
    message = update.effective_message
    resolved = await _resolve(update, context)
    if resolved is None:
        return
    account, user_id = resolved
    await _send_profile(context, update.effective_chat.id, user_id, account, show_all)


async def profile(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    await _profile_entry(update, context, False, "profile")


async def characters(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    await _profile_entry(update, context, True, "characters")


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
    resolved = await _resolve(update, context)
    if resolved is None:
        return
    account, user_id = resolved
    previous, floor = _parse_abyss_args(context.args or [])
    await _send_abyss(context, update.effective_chat.id, user_id, account, previous, floor)


async def notes(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    message = update.effective_message
    if _private(update) and context.args and context.args[0].lower() == "pick":
        rows = await _deps(context).db.list_accounts(update.effective_user.id)
        if len(rows) > 1:
            await message.reply_text("Which account?", reply_markup=_keyboard("notes", rows))
            return
    resolved = await _resolve(update, context)
    if resolved is None:
        return
    account, user_id = resolved
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
    application.add_handler(CommandHandler("myid", myid))
    application.add_handler(CommandHandler("settings", settings))
    application.add_handler(CommandHandler("share", share))
    application.add_handler(CommandHandler("groupreports", groupreports))
    application.add_handler(CommandHandler("updateicons", updateicons))
    application.add_handler(CommandHandler("debug", debug))
    application.add_handler(CommandHandler("link", link))
    application.add_handler(CommandHandler("accounts", accounts))
    application.add_handler(CommandHandler("setaccount", setaccount))
    application.add_handler(CommandHandler("unlink", unlink))
    application.add_handler(CommandHandler("notes", notes))
    application.add_handler(CommandHandler("abyss", abyss))
    application.add_handler(CommandHandler("character", character))
    application.add_handler(CommandHandler("theater", theater))
    application.add_handler(CommandHandler("stygian", stygian))
    application.add_handler(CommandHandler("diary", diary))
    application.add_handler(CommandHandler("profile", profile))
    application.add_handler(CommandHandler("characters", characters))
    application.add_handler(CallbackQueryHandler(on_setdef, pattern=rf"^setdef:{UUID_PATTERN}$"))
    application.add_handler(CallbackQueryHandler(on_unlink_ask, pattern=rf"^unlink:{UUID_PATTERN}$"))
    application.add_handler(CallbackQueryHandler(on_unlink_confirm, pattern=rf"^unlinkok:{UUID_PATTERN}$"))
    application.add_handler(CallbackQueryHandler(on_notes_pick, pattern=rf"^notes:{UUID_PATTERN}$"))
    application.add_handler(CallbackQueryHandler(on_settings, pattern=r"^st:[a-z0-9:_-]{1,50}$"))
    application.add_handler(CallbackQueryHandler(on_cancel, pattern=r"^cancel:0$"))
    application.add_error_handler(on_error)
