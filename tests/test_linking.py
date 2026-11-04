from datetime import timedelta

from app.linking import (
    MAX_ATTEMPTS,
    TOKEN_PATTERN,
    SessionState,
    evaluate_session,
    hash_token,
    new_token,
    parse_ts,
)
from app.regions import is_international_server, mask_uid, server_label
from tests.fakes import FakeDatabase


def test_token_shape_and_hash():
    t = new_token()
    assert TOKEN_PATTERN.match(t)
    assert hash_token(t) != t and len(hash_token(t)) == 64
    assert new_token() != t


def test_session_states():
    db = FakeDatabase()
    assert evaluate_session(None) is SessionState.UNKNOWN
    assert evaluate_session(db.add_session("a")) is SessionState.OK
    assert evaluate_session(db.add_session("b", expires_in=timedelta(seconds=-1))) is SessionState.EXPIRED
    assert evaluate_session(db.add_session("c", consumed=True)) is SessionState.CONSUMED
    assert evaluate_session(db.add_session("d", attempts=MAX_ATTEMPTS)) is SessionState.LOCKED


def test_parse_ts_variable_fraction_digits():
    assert parse_ts("2026-10-31T10:00:00.12345+00:00").year == 2026
    assert parse_ts("2026-10-31T10:00:00Z").tzinfo is not None
    assert parse_ts("2026-10-31T10:00:00").tzinfo is not None


def test_masking():
    assert mask_uid("712345678") == "71****678"
    assert "3456" not in mask_uid("712345678")
    assert mask_uid("123") == "***"


def test_servers():
    assert is_international_server("os_asia") and not is_international_server("cn_gf01")
    assert server_label("os_cht") == "TW/HK/MO" and server_label("unknown") == "unknown"
