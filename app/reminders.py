"""Resin reminders: a background loop that messages a user in private chat when their resin reaches a chosen level."""

from __future__ import annotations

import asyncio
import logging
from typing import Any, Protocol

from app.errors import ReauthRequired
from app.report_utils import fmt_duration

log = logging.getLogger(__name__)

CHECK_SECONDS = 600
OPTIONS = ("off", "80", "120", "160", "full")


def to_threshold(option: str) -> int | None:
    """Menu option -> stored value (None = off, 0 = when full)."""
    if option == "off":
        return None
    if option == "full":
        return 0
    return int(option) if option.isdigit() and option in OPTIONS else None


def to_option(threshold: int | None) -> str:
    return "off" if threshold is None else ("full" if threshold == 0 else str(threshold))


def label(option: str) -> str:
    return {"off": "Off", "full": "When full"}.get(option, f"At {option} resin")


def decide(current: int, max_resin: int, threshold: int, armed: bool) -> tuple[bool, bool]:
    """Returns (send_message, new_armed). Sends once per rise; re-arms after resin is spent."""
    target = max_resin if threshold == 0 else min(threshold, max_resin)
    if current >= target:
        return armed, False
    return False, True


def message(current: int, max_resin: int, recovery_seconds: int) -> str:
    if current >= max_resin:
        return f"Your resin is full ({current}/{max_resin})."
    return f"Your resin is {current}/{max_resin}. Full in {fmt_duration(recovery_seconds)}."


class ReminderStore(Protocol):
    async def list_reminders(self) -> list[dict[str, Any]]: ...
    async def update_reminder_state(self, user_id: int, **fields: Any) -> None: ...
    async def set_reminder(self, user_id: int, threshold: int | None) -> None: ...
    async def list_accounts(self, telegram_user_id: int) -> list[dict[str, Any]]: ...


def pick_account(rows: list[dict[str, Any]]) -> dict[str, Any] | None:
    return next((r for r in rows if r.get("is_default")), rows[0] if rows else None)


async def check_user(db: ReminderStore, provider: Any, send, row: dict[str, Any]) -> None:
    """Handle one reminder row. `send(user_id, text)` raises on Telegram failure."""
    user_id = int(row["user_id"])
    account = pick_account(await db.list_accounts(user_id))
    if account is None:
        await db.set_reminder(user_id, None)  # nothing linked any more
        return
    if account.get("status") == "reauth_required":
        if not row.get("session_warned"):
            await send(user_id, "Resin reminders paused: your HoYoLAB session expired. Use /link to sign in again.")
            await db.update_reminder_state(user_id, session_warned=True)
        return
    try:
        result = await provider.get_notes(account)
    except ReauthRequired:
        return  # the provider marked the account; the next round sends the notice
    except Exception:
        return
    if result.source == "stale":
        return
    notes = result.data
    notify, armed = decide(notes.current_resin, notes.max_resin, int(row["resin_threshold"]), bool(row.get("armed", True)))
    if notify:
        await send(user_id, message(notes.current_resin, notes.max_resin, notes.resin_recovery_seconds))
    changes: dict[str, Any] = {}
    if armed != bool(row.get("armed", True)):
        changes["armed"] = armed
    if row.get("session_warned"):
        changes["session_warned"] = False
    if changes:
        await db.update_reminder_state(user_id, **changes)


async def reminder_loop(db: ReminderStore, provider: Any, bot: Any, interval: int = CHECK_SECONDS) -> None:
    await asyncio.sleep(90)

    async def send(user_id: int, text: str) -> None:
        await bot.send_message(user_id, text)

    while True:
        try:
            rows = await db.list_reminders()
        except Exception as exc:
            log.warning("reminder list failed (%s)", type(exc).__name__)
            rows = []
        for row in rows:
            try:
                await check_user(db, provider, send, row)
            except Exception as exc:
                name = type(exc).__name__
                if name in ("Forbidden", "BadRequest"):  # user blocked the bot or chat is gone
                    try:
                        await db.set_reminder(int(row["user_id"]), None)
                    except Exception:
                        pass
                log.warning("reminder failed (%s)", name)
            await asyncio.sleep(1)
        await asyncio.sleep(interval)
