"""Supabase data access (PostgREST over HTTPS, using the service-role key).

Every method returns plain dicts. Credentials are only ever read through
`get_credentials`, which is used by the Genshin provider and nowhere else.
"""

from __future__ import annotations

from datetime import datetime, timedelta, timezone
from typing import Any

from supabase import AsyncClient, acreate_client

from app.linking import utcnow


def _iso(dt: datetime) -> str:
    return dt.astimezone(timezone.utc).isoformat()


class Database:
    def __init__(self, client: AsyncClient) -> None:
        self._c = client

    @classmethod
    async def connect(cls, url: str, service_role_key: str) -> "Database":
        return cls(await acreate_client(url, service_role_key))

    async def ping(self) -> None:
        await self._c.table("game_accounts").select("id").limit(1).execute()

    # ---- link sessions -------------------------------------------------
    async def create_link_session(self, telegram_user_id: int, token_hash: str, expires_at: datetime) -> None:
        await self._c.table("link_sessions").insert(
            {"telegram_user_id": telegram_user_id, "token_hash": token_hash, "expires_at": _iso(expires_at)}
        ).execute()

    async def get_link_session(self, token_hash: str) -> dict[str, Any] | None:
        res = await self._c.table("link_sessions").select("*").eq("token_hash", token_hash).limit(1).execute()
        return res.data[0] if res.data else None

    async def bump_link_attempts(self, session_id: str, attempts: int) -> None:
        await self._c.table("link_sessions").update({"attempts": attempts + 1}).eq("id", session_id).execute()

    async def consume_link_session(self, session_id: str) -> bool:
        """Atomically mark a session used. Returns False if someone else consumed it first."""
        res = (
            await self._c.table("link_sessions")
            .update({"consumed_at": _iso(utcnow())})
            .eq("id", session_id)
            .is_("consumed_at", "null")
            .execute()
        )
        return bool(res.data)

    async def purge_old_link_sessions(self) -> None:
        cutoff = utcnow() - timedelta(days=1)
        await self._c.table("link_sessions").delete().lt("expires_at", _iso(cutoff)).execute()

    # ---- accounts ------------------------------------------------------
    async def find_account_by_uid(self, game_uid: str) -> dict[str, Any] | None:
        res = await self._c.table("game_accounts").select("*").eq("game_uid", game_uid).limit(1).execute()
        return res.data[0] if res.data else None

    async def upsert_game_account(
        self, telegram_user_id: int, game_uid: str, region: str, nickname: str | None
    ) -> dict[str, Any]:
        now = _iso(utcnow())
        res = (
            await self._c.table("game_accounts")
            .upsert(
                {
                    "telegram_user_id": telegram_user_id,
                    "game_uid": game_uid,
                    "region": region,
                    "nickname": nickname,
                    "status": "active",
                    "updated_at": now,
                    "last_validated_at": now,
                },
                on_conflict="game_uid",
            )
            .execute()
        )
        return res.data[0]

    async def list_accounts(self, telegram_user_id: int) -> list[dict[str, Any]]:
        res = (
            await self._c.table("game_accounts")
            .select("*")
            .eq("telegram_user_id", telegram_user_id)
            .order("created_at")
            .execute()
        )
        return list(res.data)

    async def get_account_for_user(self, account_id: str, telegram_user_id: int) -> dict[str, Any] | None:
        res = (
            await self._c.table("game_accounts")
            .select("*")
            .eq("id", account_id)
            .eq("telegram_user_id", telegram_user_id)
            .limit(1)
            .execute()
        )
        return res.data[0] if res.data else None

    async def ensure_default(self, telegram_user_id: int) -> None:
        accounts = await self.list_accounts(telegram_user_id)
        if accounts and not any(a["is_default"] for a in accounts):
            await self.set_default(telegram_user_id, accounts[0]["id"])

    async def set_default(self, telegram_user_id: int, account_id: str) -> None:
        # Unset first: a partial unique index allows only one default per user.
        await self._c.table("game_accounts").update({"is_default": False}).eq(
            "telegram_user_id", telegram_user_id
        ).eq("is_default", True).execute()
        await self._c.table("game_accounts").update({"is_default": True}).eq("id", account_id).eq(
            "telegram_user_id", telegram_user_id
        ).execute()

    async def set_status(self, account_id: str, status: str) -> None:
        await self._c.table("game_accounts").update({"status": status, "updated_at": _iso(utcnow())}).eq(
            "id", account_id
        ).execute()

    async def delete_account(self, telegram_user_id: int, account_id: str) -> bool:
        """Deletes the account; credentials and cache rows go with it (ON DELETE CASCADE)."""
        res = (
            await self._c.table("game_accounts")
            .delete()
            .eq("id", account_id)
            .eq("telegram_user_id", telegram_user_id)
            .execute()
        )
        deleted = bool(res.data)
        if deleted:
            await self.ensure_default(telegram_user_id)
        return deleted

    # ---- credentials (encrypted) --------------------------------------
    async def store_credentials(self, account_id: str, ciphertext: str, nonce: str, key_version: str) -> None:
        await self._c.table("account_credentials").upsert(
            {
                "game_account_id": account_id,
                "ciphertext": ciphertext,
                "nonce": nonce,
                "key_version": key_version,
                "updated_at": _iso(utcnow()),
            },
            on_conflict="game_account_id",
        ).execute()

    async def get_credentials(self, account_id: str) -> dict[str, Any] | None:
        res = (
            await self._c.table("account_credentials").select("*").eq("game_account_id", account_id).limit(1).execute()
        )
        return res.data[0] if res.data else None

    # ---- cache ---------------------------------------------------------
    async def get_cache(self, account_id: str, cache_key: str) -> dict[str, Any] | None:
        res = (
            await self._c.table("activity_cache")
            .select("*")
            .eq("game_account_id", account_id)
            .eq("cache_key", cache_key)
            .limit(1)
            .execute()
        )
        return res.data[0] if res.data else None

    async def put_cache(
        self,
        account_id: str,
        cache_key: str,
        payload: dict[str, Any],
        schema_version: int,
        fetched_at: datetime,
        ttl: timedelta,
    ) -> None:
        await self._c.table("activity_cache").upsert(
            {
                "game_account_id": account_id,
                "cache_key": cache_key,
                "payload": payload,
                "schema_version": schema_version,
                "fetched_at": _iso(fetched_at),
                "expires_at": _iso(fetched_at + ttl),
            },
            on_conflict="game_account_id,cache_key",
        ).execute()

    # ---- audit ---------------------------------------------------------
    async def audit(
        self, actor_telegram_user_id: int | None, action: str, target_type: str | None = None, target_id: str | None = None
    ) -> None:
        """Non-secret audit trail. Never pass cookies, tokens or raw payloads here."""
        await self._c.table("audit_events").insert(
            {
                "actor_telegram_user_id": actor_telegram_user_id,
                "action": action,
                "target_type": target_type,
                "target_id": target_id,
            }
        ).execute()
