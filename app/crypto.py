"""AES-256-GCM encryption for stored session cookies.

The account id is bound to the ciphertext as associated data, so a ciphertext copied
from one account's row onto another account's row fails to decrypt.
"""

from __future__ import annotations

import base64
import json
import os
from collections.abc import Mapping

from cryptography.exceptions import InvalidTag
from cryptography.hazmat.primitives.ciphers.aead import AESGCM


class CryptoError(RuntimeError):
    """Raised for any decryption problem. Never includes secret material."""


class CredentialCipher:
    def __init__(self, key: bytes, key_version: str) -> None:
        if len(key) != 32:
            raise ValueError("key must be 32 bytes")
        self._aes = AESGCM(key)
        self.key_version = key_version

    def encrypt(self, cookies: Mapping[str, str], *, account_id: str) -> tuple[str, str, str]:
        """Return (ciphertext_b64, nonce_b64, key_version)."""
        nonce = os.urandom(12)
        plaintext = json.dumps(dict(cookies), separators=(",", ":"), sort_keys=True).encode()
        ciphertext = self._aes.encrypt(nonce, plaintext, account_id.encode())
        return (
            base64.b64encode(ciphertext).decode(),
            base64.b64encode(nonce).decode(),
            self.key_version,
        )

    def decrypt(self, ciphertext_b64: str, nonce_b64: str, key_version: str, *, account_id: str) -> dict[str, str]:
        if key_version != self.key_version:
            # Key rotation is not implemented yet; fail loudly instead of guessing.
            raise CryptoError("Credential was encrypted with a different key version")
        try:
            plaintext = self._aes.decrypt(
                base64.b64decode(nonce_b64),
                base64.b64decode(ciphertext_b64),
                account_id.encode(),
            )
            data = json.loads(plaintext)
        except (InvalidTag, ValueError):
            raise CryptoError("Could not decrypt stored credential") from None
        if not isinstance(data, dict):
            raise CryptoError("Stored credential has an unexpected shape")
        return {str(k): str(v) for k, v in data.items()}
