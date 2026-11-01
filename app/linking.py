"""Single-use linking tokens. Only the SHA-256 hash of a token is ever stored."""

from __future__ import annotations

import hashlib
import re
import secrets
from datetime import datetime, timedelta, timezone
from enum import Enum
from typing import Any, Mapping

TOKEN_TTL = timedelta(minutes=10)
MAX_ATTEMPTS = 5
TOKEN_PATTERN = re.compile(r"^[A-Za-z0-9_-]{20,64}$")


class SessionState(str, Enum):
    OK = "ok"
    UNKNOWN = "unknown"
    EXPIRED = "expired"
    CONSUMED = "consumed"
    LOCKED = "locked"


def utcnow() -> datetime:
    return datetime.now(timezone.utc)


def new_token() -> str:
    return secrets.token_urlsafe(32)


def hash_token(token: str) -> str:
    return hashlib.sha256(token.encode()).hexdigest()


def parse_ts(value: str | datetime | None) -> datetime | None:
    if value is None:
        return None
    if isinstance(value, datetime):
        dt = value
    else:
        dt = datetime.fromisoformat(value)
    return dt if dt.tzinfo else dt.replace(tzinfo=timezone.utc)


def evaluate_session(row: Mapping[str, Any] | None, now: datetime | None = None) -> SessionState:
    if row is None:
        return SessionState.UNKNOWN
    now = now or utcnow()
    if row.get("consumed_at"):
        return SessionState.CONSUMED
    expires = parse_ts(row.get("expires_at"))
    if expires is None or expires <= now:
        return SessionState.EXPIRED
    if int(row.get("attempts") or 0) >= MAX_ATTEMPTS:
        return SessionState.LOCKED
    return SessionState.OK
