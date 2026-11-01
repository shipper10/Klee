"""Game server helpers (HoYoLAB international servers only)."""

from __future__ import annotations

SERVER_LABELS = {
    "os_usa": "America",
    "os_euro": "Europe",
    "os_asia": "Asia",
    "os_cht": "TW/HK/MO",
}


def is_international_server(server: str) -> bool:
    return server.startswith("os_")


def server_label(server: str) -> str:
    return SERVER_LABELS.get(server, server)


def mask_uid(uid: str) -> str:
    """Show only enough of a UID to tell accounts apart, e.g. 71****345."""
    uid = str(uid)
    if len(uid) < 6:
        return "*" * len(uid)
    return f"{uid[:2]}{'*' * (len(uid) - 5)}{uid[-3:]}"


# Verified against genshin.py: constants.SERVER_TIMEZONES.
SERVER_UTC_OFFSETS = {"os_asia": 8, "os_cht": 8, "os_usa": -5, "os_euro": 1}


def server_utc_offset(server: str) -> int:
    return SERVER_UTC_OFFSETS.get(server, 8)
