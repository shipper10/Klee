import base64
import os

import pytest

from app.config import ConfigError, load_settings

KEY = base64.urlsafe_b64encode(os.urandom(32)).decode()
BASE = {
    "TELEGRAM_BOT_TOKEN": "123:SECRETTOKEN",
    "SUPABASE_URL": "https://x.supabase.co",
    "SUPABASE_SERVICE_ROLE_KEY": "SECRETSERVICEKEY",
    "CREDENTIAL_ENCRYPTION_KEY": KEY,
    "PUBLIC_BASE_URL": "https://klee.onrender.com/",
}


def env(monkeypatch, **over):
    for k in list(os.environ):
        if k in BASE or k in ("APP_ENV", "PORT"):
            monkeypatch.delenv(k)
    for k, v in {**BASE, **over}.items():
        if v is not None:
            monkeypatch.setenv(k, v)


def test_loads_and_normalizes(monkeypatch):
    env(monkeypatch, PORT="8080")
    s = load_settings()
    assert s.public_base_url == "https://klee.onrender.com" and s.port == 8080
    assert len(s.encryption_key) == 32


def test_accepts_render_generated_standard_base64_key(monkeypatch):
    # Render's generateValue produces standard base64 (may contain + and /), 44 chars ending in "=".
    raw = bytes([251, 255, 190] * 10 + [1, 2])  # encodes with '+' and '/'
    std = base64.b64encode(raw).decode()
    assert "+" in std or "/" in std
    env(monkeypatch, CREDENTIAL_ENCRYPTION_KEY=std)
    assert load_settings().encryption_key == raw


def test_repr_hides_secrets(monkeypatch):
    env(monkeypatch)
    text = repr(load_settings())
    assert "SECRETTOKEN" not in text and "SECRETSERVICEKEY" not in text and KEY not in text


def test_missing_variable_named_but_no_values(monkeypatch):
    env(monkeypatch, SUPABASE_URL=None)
    with pytest.raises(ConfigError, match="SUPABASE_URL"):
        load_settings()


def test_bad_key_rejected_without_echo(monkeypatch):
    env(monkeypatch, CREDENTIAL_ENCRYPTION_KEY=base64.urlsafe_b64encode(b"short").decode())
    with pytest.raises(ConfigError) as exc:
        load_settings()
    assert "short" not in str(exc.value)


def test_https_required_in_production(monkeypatch):
    env(monkeypatch, PUBLIC_BASE_URL="http://example.com")
    with pytest.raises(ConfigError):
        load_settings()
