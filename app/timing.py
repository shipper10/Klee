"""Tiny in-memory record of how long each stage of recent reports took (for the owner's /debug view)."""

from __future__ import annotations

import time
from collections import deque
from contextlib import contextmanager

_events: deque[tuple[float, str, str, float]] = deque(maxlen=60)


def record(kind: str, stage: str, seconds: float) -> None:
    _events.append((time.time(), kind, stage, seconds))


@contextmanager
def timed(kind: str, stage: str):
    start = time.monotonic()
    try:
        yield
    finally:
        record(kind, stage, time.monotonic() - start)


def summary(limit: int = 12) -> str:
    if not _events:
        return "No timings recorded yet (request a report first)."
    lines = []
    now = time.time()
    for ts, kind, stage, secs in list(_events)[-limit:]:
        lines.append(f"{int(now - ts):>4}s ago  {kind:<10} {stage:<8} {secs:.1f}s")
    return "\n".join(lines)
