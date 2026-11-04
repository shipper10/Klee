"""Template registry: which drawing function produces a report for a (service, style) pair.

To add a design: write a `render_<service>_<style>(data, *, ..., style)` function that returns PNG bytes, import it here, add it to
RENDERERS, and list the style in `styles.LAYOUT_SERVICES` (with a label in `styles.LAYOUTS`). Nothing else in the bot changes.
Renderers are plain functions of already-fetched data, so a new design never touches fetching, caching or commands.
"""

from __future__ import annotations

from collections.abc import Callable

from app.build_card.template import render_character_build
from app.render_abyss_official import render_abyss_official
from app.render_diary_official import render_diary_official
from app.render_notes_official import render_notes_official
from app.render_showcase import render_character_showcase
from app.render_showcase_profile import render_profile_showcase
from app.render_stygian_official import render_stygian_official
from app.render_theater_official import render_theater_official
from app.styles import DEFAULT_STYLE

RENDERERS: dict[tuple[str, str], Callable[..., bytes]] = {
    ("notes", "official"): render_notes_official,
    ("abyss", "official"): render_abyss_official,
    ("theater", "official"): render_theater_official,
    ("stygian", "official"): render_stygian_official,
    ("diary", "official"): render_diary_official,
    ("profile", "showcase"): render_profile_showcase,
    ("character", "build"): render_character_build,
    ("character", "showcase"): render_character_showcase,
}


def renderer(service: str, style: str) -> Callable[..., bytes]:
    """The drawing function for this style; an unknown style falls back to the service's default design."""
    return RENDERERS.get((service, style)) or RENDERERS[(service, DEFAULT_STYLE[service])]
