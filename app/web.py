"""HTTP side of the service: health check for UptimeRobot and the account-linking page.

Access logging is disabled in main.py because linking URLs contain the single-use token.
Submitted cookies are never logged, echoed back, or kept after the request.
"""

from __future__ import annotations

import html
import logging
from dataclasses import dataclass

from aiohttp import web

from app.cookies import CookieInputError, parse_cookie_input
from app.crypto import CredentialCipher
from app.db import Database
from app.link_service import LinkError, link_accounts
from app.linking import TOKEN_PATTERN, SessionState, evaluate_session, hash_token

log = logging.getLogger(__name__)

SECURITY_HEADERS = {
    "Cache-Control": "no-store",
    "Referrer-Policy": "no-referrer",
    "X-Content-Type-Options": "nosniff",
    "X-Frame-Options": "DENY",
    "Content-Security-Policy": "default-src 'none'; style-src 'unsafe-inline'; form-action 'self'; base-uri 'none'",
}

STYLE = """
body{font-family:system-ui,sans-serif;background:#14161f;color:#ecedf5;margin:0;padding:20px;line-height:1.5}
main{max-width:640px;margin:0 auto}
h1{font-size:1.5rem;color:#e9c478}
.box{background:#212536;border-radius:14px;padding:16px 18px;margin:14px 0}
.warn{border-left:4px solid #f0aa6e}
textarea{width:100%;box-sizing:border-box;min-height:120px;background:#14161f;color:#ecedf5;border:1px solid #3a4060;
border-radius:10px;padding:10px;font-family:monospace}
button{background:#e9c478;color:#14161f;border:0;border-radius:10px;padding:12px 20px;font-size:1rem;font-weight:600}
label{display:block;margin:12px 0}
code{background:#14161f;padding:1px 5px;border-radius:5px}
.err{color:#f0aa6e;font-weight:600}
"""


@dataclass
class WebDeps:
    db: Database
    cipher: CredentialCipher
    bot: object  # telegram.Bot; typed loosely to keep this module import-light


DEPS_KEY: web.AppKey[WebDeps] = web.AppKey("deps")


def _page(title: str, body: str, status: int = 200) -> web.Response:
    doc = (
        "<!doctype html><html lang='en'><head><meta charset='utf-8'>"
        "<meta name='viewport' content='width=device-width,initial-scale=1'>"
        f"<title>{html.escape(title)}</title><style>{STYLE}</style></head>"
        f"<body><main>{body}</main></body></html>"
    )
    return web.Response(text=doc, status=status, content_type="text/html", headers=SECURITY_HEADERS)


def _form(error: str | None = None) -> str:
    err = f"<p class='err'>{html.escape(error)}</p>" if error else ""
    return f"""
<h1>Link your Genshin account</h1>
<div class="box warn">
<b>Read this first.</b> The cookies below are the same ones HoYoLAB uses to keep you signed in.
Anyone holding them can act as you on HoYoLAB. This bot only reads Battle Chronicle data and stores the
cookies encrypted, but no one can promise a hosted service is risk-free.
<b>Use a spare HoYoLAB account if you can.</b> This is an unofficial community tool, not affiliated with HoYoverse.
We never ask for your password.
</div>
<div class="box">
<b>How to get the cookies</b>
<ol>
<li>Open <code>hoyolab.com</code> in a desktop browser and sign in.</li>
<li>Open developer tools (F12) and go to <b>Application</b> (Chrome/Edge) or <b>Storage</b> (Firefox) → <b>Cookies</b> → hoyolab.com.</li>
<li>Copy the values of <code>ltuid_v2</code>, <code>ltoken_v2</code> and <code>ltmid_v2</code> and paste them below
as <code>name=value</code>, one per line.</li>
</ol>
</div>
{err}
<form method="post" autocomplete="off">
<textarea name="cookies" placeholder="ltuid_v2=...&#10;ltoken_v2=...&#10;ltmid_v2=..." required></textarea>
<label><input type="checkbox" name="understood" value="yes" required>
I understand the risks above.</label>
<button type="submit">Link account</button>
</form>
<p>The link works once and expires 10 minutes after you ask for it in Telegram.
Use /unlink in the bot at any time to delete the stored session.</p>
"""


_STATE_MESSAGES = {
    SessionState.UNKNOWN: "This link is not valid.",
    SessionState.EXPIRED: "This link has expired.",
    SessionState.CONSUMED: "This link has already been used.",
    SessionState.LOCKED: "Too many failed attempts on this link.",
}


def _dead_link(state: SessionState) -> web.Response:
    msg = _STATE_MESSAGES.get(state, "This link is not valid.")
    return _page(
        "Link unavailable",
        f"<h1>Link unavailable</h1><div class='box'>{html.escape(msg)} "
        "Send <code>/link</code> to the bot in a private chat to get a new one.</div>",
        status=410,
    )


async def health(_: web.Request) -> web.Response:
    return web.json_response({"status": "ok"})


async def link_get(request: web.Request) -> web.Response:
    deps = request.app[DEPS_KEY]
    token = request.match_info["token"]
    if not TOKEN_PATTERN.match(token):
        return _dead_link(SessionState.UNKNOWN)
    row = await deps.db.get_link_session(hash_token(token))
    state = evaluate_session(row)
    if state is not SessionState.OK:
        return _dead_link(state)
    return _page("Link your account", _form())


async def link_post(request: web.Request) -> web.Response:
    deps = request.app[DEPS_KEY]
    token = request.match_info["token"]
    if not TOKEN_PATTERN.match(token):
        return _dead_link(SessionState.UNKNOWN)

    row = await deps.db.get_link_session(hash_token(token))
    state = evaluate_session(row)
    if state is not SessionState.OK or row is None:
        return _dead_link(state)

    form = await request.post()
    cookie_text = str(form.get("cookies", ""))
    understood = form.get("understood") == "yes"

    # Count the attempt before doing anything else so a failing flow cannot be retried forever.
    await deps.db.bump_link_attempts(row["id"], int(row.get("attempts") or 0))

    if not understood:
        return _page("Link your account", _form("Please tick the box to confirm you understand the risks."), 400)
    try:
        cookies = parse_cookie_input(cookie_text)
    except CookieInputError as exc:
        return _page("Link your account", _form(str(exc)), 400)

    telegram_user_id = int(row["telegram_user_id"])
    try:
        linked = await link_accounts(deps.db, deps.cipher, telegram_user_id, cookies)
    except LinkError as exc:
        return _page("Link your account", _form(str(exc)), 400)
    except Exception as exc:
        log.error("linking failed: %s", type(exc).__name__)
        return _page("Link your account", _form("Something went wrong on our side. Please try again later."), 500)
    finally:
        cookies.clear()

    if not await deps.db.consume_link_session(row["id"]):
        # Lost a race with a second submission of the same link; accounts are already stored.
        log.info("link session was consumed concurrently")

    names = "".join(
        f"<li>{html.escape(a.nickname)} · UID {html.escape(a.uid_masked)} · {html.escape(a.server)}</li>" for a in linked
    )
    try:
        await deps.bot.send_message(  # type: ignore[attr-defined]
            chat_id=telegram_user_id,
            text="Account linked ✅\n"
            + "\n".join(f"• {a.nickname} · UID {a.uid_masked} · {a.server}" for a in linked)
            + "\n\nTry /notes. If notes fail, make sure Real-Time Notes is enabled in your HoYoLAB privacy settings.",
        )
    except Exception as exc:
        log.warning("could not send link confirmation: %s", type(exc).__name__)

    return _page(
        "Account linked",
        f"<h1>Account linked ✅</h1><div class='box'><ul>{names}</ul>"
        "You can close this page and go back to Telegram. Your cookies were not shown or kept in the browser.</div>",
    )


def build_app(deps: WebDeps) -> web.Application:
    app = web.Application(client_max_size=16 * 1024)
    app[DEPS_KEY] = deps
    app.router.add_get("/", health)
    app.router.add_get("/health", health)
    app.router.add_get("/link/{token}", link_get)
    app.router.add_post("/link/{token}", link_post)
    return app
