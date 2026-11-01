import pytest

from app.cookies import CookieInputError, parse_cookie_input


def test_newline_separated():
    got = parse_cookie_input("ltuid_v2=1\nltoken_v2=v2_abc\nltmid_v2=m")
    assert got == {"ltuid_v2": "1", "ltoken_v2": "v2_abc", "ltmid_v2": "m"}


def test_header_style_with_semicolons_and_quotes():
    got = parse_cookie_input('ltuid_v2="1"; ltoken_v2=\'v2_abc\'; ltmid_v2=m')
    assert got["ltoken_v2"] == "v2_abc"


def test_legacy_names_accepted():
    assert parse_cookie_input("ltuid=1; ltoken=abc") == {"ltuid": "1", "ltoken": "abc"}


def test_unknown_cookies_are_dropped_not_stored():
    got = parse_cookie_input("ltuid_v2=1\nltoken_v2=a\ncookie_token_v2=DANGEROUS\nsessionid=zzz")
    assert set(got) == {"ltuid_v2", "ltoken_v2"}


def test_missing_required_cookie():
    with pytest.raises(CookieInputError):
        parse_cookie_input("ltuid_v2=1")


def test_garbage():
    with pytest.raises(CookieInputError):
        parse_cookie_input("hello world")


def test_error_never_echoes_value():
    with pytest.raises(CookieInputError) as exc:
        parse_cookie_input("ltuid_v2=has space inside\nltoken_v2=SECRETVALUE")
    assert "SECRETVALUE" not in str(exc.value)
    assert "has space inside" not in str(exc.value)
