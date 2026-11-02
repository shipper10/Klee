"""HTTP side of the service: health check for UptimeRobot and the account-linking page.

Access logging is disabled in main.py because linking URLs contain the single-use token.
Submitted cookies are never logged, echoed back, or kept after the request.
"""

from __future__ import annotations

import html
import json
import logging
from collections.abc import Awaitable, Callable
from dataclasses import dataclass, field
from typing import Any

from aiohttp import web

from app.cookies import CookieInputError, parse_cookie_input
from app.crypto import CredentialCipher
from app.db import Database
from app.link_service import LinkError, link_accounts
from app.linking import TOKEN_PATTERN, SessionState, evaluate_session, hash_token
from app.web_login import (
    CAPTCHA_FIELDS, CaptchaStep, DoneStep, LoginError, PendingLogin, PendingStore, start_login,
)

log = logging.getLogger(__name__)

SECURITY_HEADERS = {
    "Cache-Control": "no-store",
    "Referrer-Policy": "no-referrer",
    "X-Content-Type-Options": "nosniff",
    "X-Frame-Options": "DENY",
    "Content-Security-Policy": "default-src 'none'; style-src 'unsafe-inline'; form-action 'self'; base-uri 'none'",
}
# The captcha page loads Geetest's scripts. It contains no secret (the password stays on the server), so only this
# page gets the wider policy; the pages that ask for the password or cookies run no third-party code.
CAPTCHA_HEADERS = {
    **SECURITY_HEADERS,
    "Content-Security-Policy": "default-src 'none'; script-src 'unsafe-inline' https:; style-src 'unsafe-inline' https:; "
    "connect-src 'self' https:; img-src https: data:; font-src https:; frame-src https:; base-uri 'none'",
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
input[type=email],input[type=password]{width:100%;box-sizing:border-box;background:#14161f;color:#ecedf5;border:1px solid #3a4060;border-radius:10px;padding:12px;font-size:1rem}
h2{font-size:1.15rem;color:#e9c478;margin-top:26px}
"""


@dataclass
class WebDeps:
    db: Database
    cipher: CredentialCipher
    bot: object  # telegram.Bot; typed loosely to keep this module import-light
    login: Callable[..., Awaitable[Any]] = start_login  # replaced by a fake in tests
    pending: PendingStore = field(default_factory=PendingStore)


DEPS_KEY: web.AppKey[WebDeps] = web.AppKey("deps")


def _page(title: str, body: str, status: int = 200) -> web.Response:
    doc = (
        "<!doctype html><html lang='en'><head><meta charset='utf-8'>"
        "<meta name='viewport' content='width=device-width,initial-scale=1'>"
        f"<title>{html.escape(title)}</title><style>{STYLE}</style></head>"
        f"<body><main>{body}</main></body></html>"
    )
    return web.Response(text=doc, status=status, content_type="text/html", headers=SECURITY_HEADERS)


def _form(error: str | None = None, *, cookie_error: bool = False, token: str = "") -> str:
    err = f"<p class='err'>{html.escape(error)}</p>" if error else ""
    login_err, cookie_err = ("", err) if cookie_error else (err, "")
    return f"""
<h1>Link your Genshin account</h1>
<div class="box">
<b>Option 1 · Sign in (easiest on a phone)</b>
<p>Use the e-mail and password of your <b>HoYoverse account</b> (the one you use for Genshin, not a Google/Apple
button). The password is sent to HoYoverse only to get a session; it is never stored or logged.
You may have to solve a quick captcha. <span dir="rtl">(الإيميل وكلمة سر حساب HoYoverse، وليس حساب جوجل)</span></p>
{login_err}
<form method="post" action="/link/{html.escape(token)}/login" autocomplete="off">
<label>E-mail<br><input type="email" name="email" autocomplete="username" required maxlength="254"></label>
<label>Password<br><input type="password" name="password" autocomplete="current-password" required maxlength="256"></label>
<label><input type="checkbox" name="understood" value="yes" required> I understand the risks below.</label>
<button type="submit">Sign in and link</button>
</form>
<p>Linked this way, the bot keeps the same kind of session as Option 2 and works for as long as that session stays valid.
Changing your HoYoverse password ends it; then just link again.</p>
</div>
<h2>Option 2 · Paste cookies</h2>
<div class="box warn">
<b>Read this first.</b> The cookies below are the same ones HoYoLAB uses to keep you signed in.
Anyone holding them can act as you on HoYoLAB. This bot only reads Battle Chronicle data and stores the
cookies encrypted, but no one can promise a hosted service is risk-free.
<b>Use a spare HoYoLAB account if you can.</b> This is an unofficial community tool, not affiliated with HoYoverse.
Whichever option you use, treat this like handing over access to your account.
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
{cookie_err}
<form method="post" action="/link/{html.escape(token)}" autocomplete="off">
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
    return _page("Link your account", _form(token=token))


async def _open_session(request: web.Request) -> tuple[WebDeps, str, dict | None, SessionState]:
    deps = request.app[DEPS_KEY]
    token = request.match_info["token"]
    if not TOKEN_PATTERN.match(token):
        return deps, token, None, SessionState.UNKNOWN
    row = await deps.db.get_link_session(hash_token(token))
    return deps, token, row, evaluate_session(row)


async def _complete_link(deps: WebDeps, row: dict, cookies: dict[str, str]) -> list:
    """Validate the cookies, store them encrypted, close the link session and tell the user in Telegram."""
    telegram_user_id = int(row["telegram_user_id"])
    try:
        linked = await link_accounts(deps.db, deps.cipher, telegram_user_id, cookies)
    finally:
        cookies.clear()
    if not await deps.db.consume_link_session(row["id"]):
        # Lost a race with a second submission of the same link; accounts are already stored.
        log.info("link session was consumed concurrently")
    try:
        await deps.bot.send_message(  # type: ignore[attr-defined]
            chat_id=telegram_user_id,
            text="Account linked ✅\n"
            + "\n".join(f"• {a.nickname} · UID {a.uid_masked} · {a.server}" for a in linked)
            + "\n\nTry /notes. If notes fail, make sure Real-Time Notes is enabled in your HoYoLAB privacy settings.",
        )
    except Exception as exc:
        log.warning("could not send link confirmation: %s", type(exc).__name__)
    return linked


def _success_page(linked: list) -> web.Response:
    return _page("Account linked", _success_body(linked))


def _success_body(linked: list) -> str:
    names = "".join(
        f"<li>{html.escape(a.nickname)} · UID {html.escape(a.uid_masked)} · {html.escape(a.server)}</li>" for a in linked
    )
    return (
        f"<h1>Account linked ✅</h1><div class='box'><ul>{names}</ul>"
        "You can close this page and go back to Telegram. Your credentials were not shown or kept in the browser.</div>"
    )


async def link_post(request: web.Request) -> web.Response:
    deps, token, row, state = await _open_session(request)
    if state is not SessionState.OK or row is None:
        return _dead_link(state)

    form = await request.post()
    cookie_text = str(form.get("cookies", ""))
    understood = form.get("understood") == "yes"

    # Count the attempt before doing anything else so a failing flow cannot be retried forever.
    await deps.db.bump_link_attempts(row["id"], int(row.get("attempts") or 0))

    if not understood:
        return _page("Link your account", _form("Please tick the box to confirm you understand the risks.", cookie_error=True, token=token), 400)
    try:
        cookies = parse_cookie_input(cookie_text)
    except CookieInputError as exc:
        return _page("Link your account", _form(str(exc), cookie_error=True, token=token), 400)

    try:
        linked = await _complete_link(deps, row, cookies)
    except LinkError as exc:
        return _page("Link your account", _form(str(exc), cookie_error=True, token=token), 400)
    except Exception as exc:
        log.error("linking failed: %s", type(exc).__name__)
        return _page("Link your account", _form("Something went wrong on our side. Please try again later.", cookie_error=True, token=token), 500)
    return _success_page(linked)


async def link_login(request: web.Request) -> web.Response:
    """Step 1 of e-mail sign-in: ask HoYoverse; either finish, or park the sign-in and send the user to the captcha."""
    deps, token, row, state = await _open_session(request)
    if state is not SessionState.OK or row is None:
        return _dead_link(state)

    form = await request.post()
    email, password = str(form.get("email", "")).strip(), str(form.get("password", ""))
    understood = form.get("understood") == "yes"
    await deps.db.bump_link_attempts(row["id"], int(row.get("attempts") or 0))

    def again(message: str, status: int = 400) -> web.Response:
        return _page("Link your account", _form(message, token=token), status)

    if not understood:
        return again("Please tick the box to confirm you understand the risks.")
    if not email or not password or len(email) > 254 or len(password) > 256:
        return again("Enter your HoYoverse e-mail and password.")

    try:
        step = await deps.login(email, password)
        if isinstance(step, CaptchaStep):
            key = deps.pending.add(
                PendingLogin(
                    user_id=int(row["telegram_user_id"]), session_id=str(row["id"]), email=email, password=password,
                    device_id=step.device_id, mmt=step.mmt,
                )
            )
            raise web.HTTPSeeOther(f"/link/{token}/captcha/{key}")
        cookies = dict(step.cookies)
        linked = await _complete_link(deps, row, cookies)
    except web.HTTPSeeOther:
        raise
    except (LoginError, LinkError) as exc:
        return again(str(exc))
    except Exception as exc:
        log.error("sign-in failed: %s", type(exc).__name__)
        return again("Something went wrong on our side. Please try again later.", 500)
    finally:
        email = password = ""
    return _success_page(linked)


_CAPTCHA_JS = """
var mmt = __MMT__;
function show(html){ document.getElementById('msg').innerHTML = html; }
function fail(m){ show('<p class="err">' + m + '</p><p><a href="__BACK__">Start again</a></p>'); }
initGeetest({gt: mmt.gt, challenge: mmt.challenge, new_captcha: mmt.new_captcha, api_server: 'api-na.geetest.com',
  https: true, product: 'bind', lang: 'en'}, function(captcha){
  captcha.onReady(function(){ captcha.verify(); });
  captcha.onError(function(){ fail('The captcha could not load. Check your connection and start again.'); });
  captcha.onSuccess(function(){
    var v = captcha.getValidate();
    show('Finishing sign-in…');
    fetch(location.pathname, {method: 'POST', headers: {'Content-Type': 'application/json'},
      body: JSON.stringify({geetest_challenge: v.geetest_challenge, geetest_validate: v.geetest_validate, geetest_seccode: v.geetest_seccode})})
      .then(function(r){ return r.json(); })
      .then(function(d){ if (d.ok) { document.querySelector('main').innerHTML = d.html; } else { fail(d.message); } })
      .catch(function(){ fail('Network error. Please start again.'); });
  });
});
"""


async def captcha_get(request: web.Request) -> web.Response:
    deps, token, row, state = await _open_session(request)
    if state is not SessionState.OK or row is None:
        return _dead_link(state)
    pending = deps.pending.peek(request.match_info["key"], int(row["telegram_user_id"]), str(row["id"]))
    if pending is None:
        return _dead_link(SessionState.EXPIRED)
    from genshin.client.components.auth.server import GT_V3_URL

    mmt = {k: pending.mmt.get(k) for k in ("gt", "challenge", "new_captcha")}  # no session id in the browser
    script = _CAPTCHA_JS.replace("__MMT__", json.dumps(mmt).replace("<", "\\u003c")).replace("__BACK__", f"/link/{token}")
    body = (
        "<h1>One quick check</h1><div class='box' id='msg'>Loading the captcha… A small puzzle will appear. "
        "Solve it and the account will be linked automatically.</div>"
        f"<script src=\"{GT_V3_URL}\"></script><script>{script}</script>"
    )
    doc = (
        "<!doctype html><html lang='en'><head><meta charset='utf-8'><meta name='referrer' content='no-referrer'>"
        "<meta name='viewport' content='width=device-width,initial-scale=1'><title>Captcha</title>"
        f"<style>{STYLE}</style></head><body><main>{body}</main></body></html>"
    )
    return web.Response(text=doc, content_type="text/html", headers=CAPTCHA_HEADERS)


async def captcha_post(request: web.Request) -> web.Response:
    """Step 2: the captcha was solved in the browser; finish the sign-in with the parked credentials."""
    deps, token, row, state = await _open_session(request)

    def reply(ok: bool, **data: Any) -> web.Response:
        return web.json_response({"ok": ok, **data}, headers=SECURITY_HEADERS)

    if state is not SessionState.OK or row is None:
        return reply(False, message="This link is no longer valid. Please start again.")
    pending = deps.pending.take(request.match_info["key"], int(row["telegram_user_id"]), str(row["id"]))
    if pending is None:
        return reply(False, message="This captcha expired. Please start again.")
    if request.content_type != "application/json":
        return reply(False, message="Bad request.")
    try:
        data = await request.json()
        captcha = {k: str(data[k]) for k in CAPTCHA_FIELDS}
        if any(not v or len(v) > 4096 for v in captcha.values()):
            raise ValueError
    except Exception:
        pending.wipe()
        return reply(False, message="The captcha answer was not valid. Please start again.")
    captcha["session_id"] = str(pending.mmt.get("session_id", ""))

    try:
        step = await deps.login(pending.email, pending.password, device_id=pending.device_id, captcha=captcha)
        if isinstance(step, CaptchaStep):
            return reply(False, message="HoYoverse asked for another captcha. Please start again.")
        linked = await _complete_link(deps, row, dict(step.cookies))
    except (LoginError, LinkError) as exc:
        return reply(False, message=str(exc))
    except Exception as exc:
        log.error("sign-in failed: %s", type(exc).__name__)
        return reply(False, message="Something went wrong on our side. Please try again later.")
    finally:
        pending.wipe()
    return reply(True, html=_success_body(linked))


def build_app(deps: WebDeps) -> web.Application:
    app = web.Application(client_max_size=16 * 1024)
    app[DEPS_KEY] = deps
    app.router.add_get("/", health)
    app.router.add_get("/health", health)
    app.router.add_get("/link/{token}", link_get)
    app.router.add_post("/link/{token}", link_post)
    app.router.add_post("/link/{token}/login", link_login)
    app.router.add_get("/link/{token}/captcha/{key}", captcha_get)
    app.router.add_post("/link/{token}/captcha/{key}", captcha_post)
    return app
