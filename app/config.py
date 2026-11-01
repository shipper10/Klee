"""Environment-based configuration. Error messages never contain secret values."""

from __future__ import annotations

import base64
import binascii
import os
from dataclasses import dataclass, field


class ConfigError(RuntimeError):
    pass


def _require(name: str) -> str:
    value = os.environ.get(name, "").strip()
    if not value:
        raise ConfigError(f"Missing required environment variable: {name}")
    return value


def _decode_key(raw: str) -> bytes:
    try:
        key = base64.urlsafe_b64decode(raw + "=" * (-len(raw) % 4))
    except (binascii.Error, ValueError) as exc:
        raise ConfigError("CREDENTIAL_ENCRYPTION_KEY is not valid base64") from exc
    if len(key) != 32:
        raise ConfigError("CREDENTIAL_ENCRYPTION_KEY must decode to exactly 32 bytes")
    return key


@dataclass(frozen=True)
class Settings:
    telegram_bot_token: str = field(repr=False)
    supabase_url: str
    supabase_service_role_key: str = field(repr=False)
    encryption_key: bytes = field(repr=False)
    encryption_key_version: str
    public_base_url: str
    port: int
    log_level: str
    app_env: str
    admin_ids: tuple[int, ...] = ()


def load_settings() -> Settings:
    app_env = os.environ.get("APP_ENV", "production").strip() or "production"
    public_base_url = _require("PUBLIC_BASE_URL").rstrip("/")
    if app_env == "production" and not public_base_url.startswith("https://"):
        raise ConfigError("PUBLIC_BASE_URL must start with https:// in production")

    try:
        port = int(os.environ.get("PORT", "10000"))
    except ValueError as exc:
        raise ConfigError("PORT must be an integer") from exc

    admin_ids: list[int] = []
    for part in os.environ.get("ADMIN_TELEGRAM_IDS", "").split(","):
        if part.strip():
            try:
                admin_ids.append(int(part))
            except ValueError as exc:
                raise ConfigError("ADMIN_TELEGRAM_IDS must be comma-separated numbers") from exc

    return Settings(
        telegram_bot_token=_require("TELEGRAM_BOT_TOKEN"),
        supabase_url=_require("SUPABASE_URL"),
        supabase_service_role_key=_require("SUPABASE_SERVICE_ROLE_KEY"),
        encryption_key=_decode_key(_require("CREDENTIAL_ENCRYPTION_KEY")),
        encryption_key_version=os.environ.get("CREDENTIAL_ENCRYPTION_KEY_VERSION", "v1").strip() or "v1",
        public_base_url=public_base_url,
        port=port,
        log_level=os.environ.get("LOG_LEVEL", "INFO").strip().upper() or "INFO",
        app_env=app_env,
        admin_ids=tuple(admin_ids),
    )
