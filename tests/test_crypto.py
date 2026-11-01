import os

import pytest

from app.crypto import CredentialCipher, CryptoError

COOKIES = {"ltuid_v2": "123", "ltoken_v2": "v2_secret", "ltmid_v2": "abc"}


def make(version="v1"):
    return CredentialCipher(os.urandom(32), version)


def test_roundtrip():
    c = make()
    ct, nonce, ver = c.encrypt(COOKIES, account_id="acc-1")
    assert c.decrypt(ct, nonce, ver, account_id="acc-1") == COOKIES


def test_ciphertext_does_not_contain_plaintext():
    c = make()
    ct, _, _ = c.encrypt(COOKIES, account_id="acc-1")
    assert "v2_secret" not in ct


def test_fresh_nonce_every_time():
    c = make()
    a = c.encrypt(COOKIES, account_id="acc-1")
    b = c.encrypt(COOKIES, account_id="acc-1")
    assert a[1] != b[1] and a[0] != b[0]


def test_ciphertext_cannot_be_moved_to_another_account():
    c = make()
    ct, nonce, ver = c.encrypt(COOKIES, account_id="acc-1")
    with pytest.raises(CryptoError):
        c.decrypt(ct, nonce, ver, account_id="acc-2")


def test_tampering_detected():
    c = make()
    ct, nonce, ver = c.encrypt(COOKIES, account_id="acc-1")
    flipped = ("A" if ct[0] != "A" else "B") + ct[1:]
    with pytest.raises(CryptoError):
        c.decrypt(flipped, nonce, ver, account_id="acc-1")


def test_wrong_key_version_rejected():
    c = make("v1")
    ct, nonce, _ = c.encrypt(COOKIES, account_id="acc-1")
    with pytest.raises(CryptoError):
        c.decrypt(ct, nonce, "v0", account_id="acc-1")


def test_error_message_has_no_secret():
    c = make()
    ct, nonce, ver = c.encrypt(COOKIES, account_id="acc-1")
    try:
        c.decrypt(ct, nonce, ver, account_id="other")
    except CryptoError as exc:
        assert "v2_secret" not in str(exc)
