"""In-memory stand-in for app.db.Database (only the methods the tests need)."""

from __future__ import annotations

from datetime import datetime, timedelta
from typing import Any

from app.linking import utcnow


class FakeDatabase:
    def __init__(self) -> None:
        self.sessions: dict[str, dict[str, Any]] = {}
        self.cache: dict[tuple[str, str], dict[str, Any]] = {}
        self.statuses: dict[str, str] = {}
        self.credentials: dict[str, dict[str, Any]] = {}

    def add_session(self, token_hash: str, user_id: int = 42, *, expires_in: timedelta = timedelta(minutes=10),
                    attempts: int = 0, consumed: bool = False) -> dict[str, Any]:
        row = {
            "id": f"sess-{len(self.sessions)}",
            "telegram_user_id": user_id,
            "token_hash": token_hash,
            "attempts": attempts,
            "expires_at": (utcnow() + expires_in).isoformat(),
            "consumed_at": utcnow().isoformat() if consumed else None,
        }
        self.sessions[token_hash] = row
        return row

    async def get_link_session(self, token_hash):
        return self.sessions.get(token_hash)

    async def bump_link_attempts(self, session_id, attempts):
        for row in self.sessions.values():
            if row["id"] == session_id:
                row["attempts"] = attempts + 1

    async def consume_link_session(self, session_id):
        for row in self.sessions.values():
            if row["id"] == session_id and not row["consumed_at"]:
                row["consumed_at"] = utcnow().isoformat()
                return True
        return False

    async def get_cache(self, account_id, cache_key):
        return self.cache.get((account_id, cache_key))

    async def put_cache(self, account_id, cache_key, payload, schema_version, fetched_at: datetime, ttl: timedelta):
        self.cache[(account_id, cache_key)] = {
            "payload": payload,
            "schema_version": schema_version,
            "fetched_at": fetched_at.isoformat(),
            "expires_at": (fetched_at + ttl).isoformat(),
        }

    async def set_status(self, account_id, status):
        self.statuses[account_id] = status

    async def store_credentials(self, account_id, ciphertext, nonce, key_version):
        self.credentials[account_id] = {"ciphertext": ciphertext, "nonce": nonce, "key_version": key_version}

    async def get_credentials(self, account_id):
        return self.credentials.get(account_id)
