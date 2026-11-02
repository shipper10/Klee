"""Sign in with a HoYoverse e-mail and password on the linking page (phone friendly).

The result is the same set of cookies the manual method uses (ltuid_v2, ltoken_v2, ltmid_v2), so the link lasts
exactly as long as a pasted-cookie link. The password is only ever used to ask HoYoverse for those cookies:
it is never logged, never written to the database, and, if a captcha has to be solved, it waits in process memory
for a few minutes (single use) so the captcha page itself never contains any secret.
"""

from __future__ import annotations

import asyncio
import logging
import secrets
import time
import uuid
from dataclasses import dataclass, field
from typing import Any

import aiohttp
import genshin
from genshin.models.auth.geetest import SessionMMT, SessionMMTResult

log = logging.getLogger(__name__)

KEEP_COOKIES = ("ltuid_v2", "ltoken_v2", "ltmid_v2")  # everything else (cookie_token, account ids...) is dropped
PENDING_TTL_SECONDS = 300
PENDING_MAX = 200
CAPTCHA_FIELDS = ("geetest_challenge", "geetest_validate", "geetest_seccode")


class LoginError(Exception):
    """Message is safe to show to the user."""


@dataclass
class CaptchaStep:
    mmt: dict[str, Any]
    device_id: str


@dataclass
class DoneStep:
    cookies: dict[str, str]


async def start_login(
    email: str, password: str, *, device_id: str | None = None, captcha: dict[str, str] | None = None
) -> CaptchaStep | DoneStep:
    """One call to HoYoverse's web sign-in. Returns the captcha to solve, or the cookies."""
    client = genshin.Client(region=genshin.Region.OVERSEAS)
    device_id = device_id or client.generate_web_device_id()
    mmt_result = None
    if captcha:
        try:
            mmt_result = SessionMMTResult(**captcha)
        except Exception:
            raise LoginError("The captcha answer was not valid. Please start again.") from None
    try:
        # token_type=6: ltoken_v2 + cookie_token_v2 (we keep only the ltoken part, like the manual method).
        result = await asyncio.wait_for(
            client._os_web_login(email, password, device_id=device_id, token_type=6, mmt_result=mmt_result), timeout=30
        )
    except genshin.errors.AccountLoginFail:
        raise LoginError("Wrong e-mail or password.") from None
    except genshin.errors.AccountDoesNotExist:
        raise LoginError("No HoYoverse account uses that e-mail.") from None
    except genshin.errors.AccountHasLocked:
        raise LoginError("HoYoverse has temporarily locked this account. Try again later.") from None
    except genshin.errors.GeetestFailed:
        raise LoginError("The captcha check failed. Please start again.") from None
    except (genshin.TooManyRequests, genshin.errors.VisitsTooFrequently):
        raise LoginError("Too many attempts. Wait a few minutes and try again.") from None
    except genshin.GenshinException as exc:
        log.warning("web sign-in rejected: %s retcode=%s", type(exc).__name__, exc.retcode)
        raise LoginError(
            "HoYoverse refused the sign-in. If you use Google/Apple/Steam to sign in to the game, "
            "set a HoYoverse password first, or use the cookie method below."
        ) from None
    except (asyncio.TimeoutError, aiohttp.ClientError):
        raise LoginError("Could not reach HoYoverse. Please try again in a moment.") from None

    if isinstance(result, SessionMMT):
        return CaptchaStep(result.model_dump(), device_id)
    cookies = {k: v for k, v in result.to_dict().items() if k in KEEP_COOKIES and v}
    if "ltuid_v2" not in cookies or "ltoken_v2" not in cookies:
        raise LoginError("HoYoverse did not return the expected session. Use the cookie method below.")
    return DoneStep(cookies)


@dataclass
class PendingLogin:
    user_id: int
    session_id: str
    email: str = field(repr=False)
    password: str = field(repr=False)
    device_id: str
    mmt: dict[str, Any]
    created: float = field(default_factory=time.monotonic)

    def wipe(self) -> None:
        self.email = self.password = ""


class PendingStore:
    """Short-lived, single-use, in-memory holder for a sign-in waiting on a captcha."""

    def __init__(self, ttl: float = PENDING_TTL_SECONDS, now=time.monotonic) -> None:
        self._items: dict[str, PendingLogin] = {}
        self._ttl = ttl
        self._now = now

    def _purge(self) -> None:
        cutoff = self._now() - self._ttl
        for key in [k for k, v in self._items.items() if v.created < cutoff]:
            self._items.pop(key).wipe()

    def add(self, item: PendingLogin) -> str:
        self._purge()
        while len(self._items) >= PENDING_MAX:
            self._items.pop(next(iter(self._items))).wipe()
        key = secrets.token_urlsafe(24)
        item.created = self._now()
        self._items[key] = item
        return key

    def peek(self, key: str, user_id: int, session_id: str) -> PendingLogin | None:
        self._purge()
        item = self._items.get(key)
        if item and item.user_id == user_id and item.session_id == session_id:
            return item
        return None

    def take(self, key: str, user_id: int, session_id: str) -> PendingLogin | None:
        item = self.peek(key, user_id, session_id)
        if item:
            self._items.pop(key, None)
        return item

    def __len__(self) -> int:
        return len(self._items)


def valid_device_id(value: str) -> bool:
    try:
        return str(uuid.UUID(value)) == value.lower()
    except ValueError:
        return False
