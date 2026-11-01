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
