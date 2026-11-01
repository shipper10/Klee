"""Parsing of cookies pasted into the linking page.

Only an allow-list of cookie names is kept; everything else the user pasted is dropped
and never stored. Error messages never echo the submitted values.
"""

from __future__ import annotations

import re

# genshin.py accepts either the v2 or the legacy names (see genshin/client/manager/managers.py).
ALLOWED_COOKIES = ("ltuid_v2", "ltoken_v2", "ltmid_v2", "ltuid", "ltoken")

_PAIR_SPLIT = re.compile(r"[;\n\r]+")
_NAME = re.compile(r"^[A-Za-z0-9_]{1,64}$")
_MAX_VALUE_LEN = 2048


class CookieInputError(ValueError):
    """Safe-to-show message about why the pasted cookies were rejected."""


def parse_cookie_input(text: str) -> dict[str, str]:
    found: dict[str, str] = {}
    for chunk in _PAIR_SPLIT.split(text or ""):
        chunk = chunk.strip()
        if not chunk or "=" not in chunk:
            continue
        name, _, value = chunk.partition("=")
        name = name.strip()
        value = value.strip().strip('"').strip("'")
        if not _NAME.match(name) or name not in ALLOWED_COOKIES:
            continue
        if not value or len(value) > _MAX_VALUE_LEN or any(c.isspace() for c in value):
            raise CookieInputError(f"The value for {name} looks invalid. Copy it again without extra spaces.")
        found[name] = value

    has_v2 = "ltuid_v2" in found and "ltoken_v2" in found
    has_legacy = "ltuid" in found and "ltoken" in found
    if not (has_v2 or has_legacy):
        raise CookieInputError(
            "Could not find the required cookies. Paste ltuid_v2 and ltoken_v2 "
            "(plus ltmid_v2 if you have it), written as name=value."
        )
    return found
