"""The /settings menu: pure builders for text and inline keyboards, plus the style preview image.

Callback data (all start with "st:"):
  st:home | st:me | st:me:<svc> | st:own | st:own:<svc> | st:set:<u|g>:<svc>:<style|default> | st:share:<0|1> | st:prev | st:close
<svc> is a service key or "all". Scope "u" = the user's own choice, "g" = the owner's default for everyone.
"""

from __future__ import annotations

from typing import Any

from app import reminders
from app.styles import ALL, SERVICES, SERVICE_STYLES, current_choice, pick
from app.ui_kit import THEMES, C, _current, draw_stars, font, new_canvas, panel, to_png
from telegram import InlineKeyboardButton as Btn, InlineKeyboardMarkup as Markup

Menu = tuple[str, Markup]


def svc_key(svc: str) -> str:
    return ALL if svc == "all" else svc


def valid_svc(svc: str) -> bool:
    return svc == "all" or svc in SERVICES


def reminder_page(current: str) -> Menu:
    buttons = [[Btn(("✓ " if current == o else "") + reminders.label(o), callback_data=f"st:rem:{o}")] for o in reminders.OPTIONS]
    buttons.append([Btn("‹ Back", callback_data="st:home")])
    text = ("Resin reminder\nI will message you here when your resin reaches the level you pick. "
            "I check about every 10 minutes and tell you once until you spend some resin.\n\n"
            f"Now: {reminders.label(current)}")
    return text, Markup(buttons)


def home(is_owner: bool, sharing: bool | None, reminder: str | None = None) -> Menu:
    rows = [[Btn("🎨 Image style", callback_data="st:me")]]
    if reminder is not None:
        rows.append([Btn(f"⏰ Resin reminder: {reminders.label(reminder)}", callback_data="st:rem")])
    if sharing is not None:
        rows.append([Btn(f"👥 Group sharing: {'ON' if sharing else 'OFF'} (tap to switch)", callback_data=f"st:share:{0 if sharing else 1}")])
    rows.append([Btn("🖼 Preview the styles", callback_data="st:prev")])
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
    entries = [("all", "All services")] + [(k, v) for k, v in SERVICES.items()]
    for key, label in entries:
        chosen = current_choice(rows_db, uid, svc_key(key))
        tag = f" · {THEMES[chosen].label}" if chosen else ""
        buttons.append([Btn(f"{label}{tag}", callback_data=f"st:{'own' if owner else 'me'}:{key}")])
    buttons.append([Btn("‹ Back", callback_data=back)])
    if owner:
        text = ("Owner default style\nThis is what everyone sees unless they picked their own. "
                "A style set for one service wins over “All services”.")
    else:
        text = ("Image style\nPick a look for each report, or one look for all of them. "
                "A style set for one report wins over “All services”. Nothing chosen = the default.")
    return text, Markup(buttons)


def style_page(scope: str, svc: str, rows_db: list[dict[str, Any]], user_id: int) -> Menu:
    owner = scope == "g"
    uid = 0 if owner else user_id
    key = svc_key(svc)
    label = "All services" if key == ALL else SERVICES[key]
    chosen = current_choice(rows_db, uid, key)
    if key == ALL:
        effective_service = "notes"
    else:
        effective_service = key
    shown = chosen or pick(rows_db, uid if not owner else 0, effective_service)
    styles = SERVICE_STYLES[effective_service]
    lines = [f"{label}" + (" · owner default" if owner else ""), ""]
    for sid in styles:
        mark = "✓ " if chosen == sid else "   "
        lines.append(f"{mark}{THEMES[sid].label}: {THEMES[sid].description}")
    lines.append("")
    lines.append(f"Now: {THEMES[shown].label}" + ("" if chosen else " (default, nothing chosen here)"))
    s = "g" if owner else "u"
    buttons = [[Btn(("✓ " if chosen == sid else "") + THEMES[sid].label, callback_data=f"st:set:{s}:{svc}:{sid}")] for sid in styles]
    buttons.append([Btn("↺ Use the default", callback_data=f"st:set:{s}:{svc}:default")])
    buttons.append([Btn("‹ Back", callback_data="st:own" if owner else "st:me")])
    return "\n".join(lines), Markup(buttons)


def render_style_preview() -> bytes:
    """One image showing every style as a small sample card."""
    cw, ch, gap = 420, 250, 24
    cols = 2
    rows = (len(THEMES) + cols - 1) // cols
    base, d = new_canvas(cols * cw + (cols + 1) * gap, rows * ch + (rows + 1) * gap + 50)
    d.text((gap, 18), "Available image styles", font=font("semibold", 26), fill=C.TEXT)
    for i, theme in enumerate(THEMES.values()):
        x = gap + (i % cols) * (cw + gap)
        y = 60 + gap + (i // cols) * (ch + gap)
        token = _current.set(theme)
        try:
            card = new_canvas(cw, ch)
            cimg, cd = card
            panel(cd, (16, 16, cw - 16, ch - 16))
            cd.text((34, 30), theme.label, font=font("bold", 30), fill=C.TEXT)
            cd.text((34, 76), "Resin 160/200", font=font("regular", 22), fill=C.MUTED)
            cd.rounded_rectangle((34, 116, 34 + 150, 116 + 40), radius=20, fill=C.GOLD)
            cd.text((34 + 75, 136), "Highlight", font=font("semibold", 20), fill=C.GOLD_DARK, anchor="mm")
            draw_stars(cd, cw - 40, 136, 3, 3, r=15, gap=8)
            cd.text((34, 182), theme.id, font=font("medium", 20), fill=C.GOLD)
            base.paste(cimg, (x, y))
        finally:
            _current.reset(token)
    return to_png(base)
