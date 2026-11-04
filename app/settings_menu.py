"""The /settings menu: pure builders for text and inline keyboards.

Callback data (all start with "st:"):
  st:home | st:me | st:me:<svc> | st:own | st:own:<svc> | st:set:<u|g>:<svc>:<style|default> | st:share:<0|1> | st:close
<svc> is a service key. Scope "u" = the user's own choice, "g" = the owner's default for everyone.
"""

from __future__ import annotations

from typing import Any

from app import reminders
from app.styles import description, label as style_label, SERVICES, SERVICE_STYLES, current_choice, pick
from telegram import InlineKeyboardButton as Btn, InlineKeyboardMarkup as Markup

Menu = tuple[str, Markup]


def valid_svc(svc: str) -> bool:
    return svc in SERVICES


def reminder_page(current: str) -> Menu:
    buttons = [[Btn(("✓ " if current == o else "") + reminders.label(o), callback_data=f"st:rem:{o}")] for o in reminders.OPTIONS]
    buttons.append([Btn("‹ Back", callback_data="st:home")])
    text = ("Resin reminder\nI will message you here when your resin reaches the level you pick. "
            "I check about every 10 minutes and tell you once until you spend some resin.\n\n"
            f"Now: {reminders.label(current)}")
    return text, Markup(buttons)


def home(is_owner: bool, sharing: bool | None, reminder: str | None = None) -> Menu:
    rows = [[Btn("🎨 Image design", callback_data="st:me")]]
    if reminder is not None:
        rows.append([Btn(f"⏰ Resin reminder: {reminders.label(reminder)}", callback_data="st:rem")])
    if sharing is not None:
        rows.append([Btn(f"👥 Group sharing: {'ON' if sharing else 'OFF'} (tap to switch)", callback_data=f"st:share:{0 if sharing else 1}")])
    if is_owner:
        rows.append([Btn("🛠 Owner: default style for everyone", callback_data="st:own")])
    rows.append([Btn("✖ Close", callback_data="st:close")])
    text = "Settings\nChoose what you want to change. Everything here is saved for you and applies in private chat and in groups."
    return text, Markup(rows)


def service_list(scope: str, rows_db: list[dict[str, Any]], user_id: int) -> Menu:
    owner = scope == "g"
    uid = 0 if owner else user_id
    back = "st:home"
    buttons = []
    for key, label in SERVICES.items():
        chosen = current_choice(rows_db, uid, key)
        tag = f" · {style_label(chosen)}" if chosen else ""
        buttons.append([Btn(f"{label}{tag}", callback_data=f"st:{'own' if owner else 'me'}:{key}")])
    buttons.append([Btn("‹ Back", callback_data=back)])
    if owner:
        text = "Owner default design\nThis is what everyone sees unless they picked their own."
    else:
        text = "Image design\nPick a design for each report. Nothing chosen = the default design."
    return text, Markup(buttons)


def style_page(scope: str, svc: str, rows_db: list[dict[str, Any]], user_id: int) -> Menu:
    owner = scope == "g"
    uid = 0 if owner else user_id
    label = SERVICES[svc]
    chosen = current_choice(rows_db, uid, svc)
    shown = chosen or pick(rows_db, uid if not owner else 0, svc)
    styles = SERVICE_STYLES[svc]
    lines = [f"{label}" + (" · owner default" if owner else ""), ""]
    for sid in styles:
        mark = "✓ " if chosen == sid else "   "
        lines.append(f"{mark}{style_label(sid)}: {description(sid)}")
    lines.append("")
    lines.append(f"Now: {style_label(shown)}" + ("" if chosen else " (default, nothing chosen here)"))
    if len(styles) == 1:
        lines.append("This report has only one design for now.")
    s = "g" if owner else "u"
    buttons = [[Btn(("✓ " if chosen == sid else "") + style_label(sid), callback_data=f"st:set:{s}:{svc}:{sid}")] for sid in styles]
    buttons.append([Btn("↺ Use the default", callback_data=f"st:set:{s}:{svc}:default")])
    buttons.append([Btn("‹ Back", callback_data="st:own" if owner else "st:me")])
    return "\n".join(lines), Markup(buttons)
