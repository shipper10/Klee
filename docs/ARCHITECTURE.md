# Architecture and how to add a design

## Data flow (one report)

```
Telegram command (app/bot.py)
  -> GenshinProvider.get_<report>()        fetch from HoYoLAB, parse to a plain dataclass, cache with a SCHEMA_VERSION
  -> ImageFetcher.fetch_first(...)         portraits/icons: memory LRU -> Supabase Storage -> network (host allow-list)
  -> styles.resolve(user, service)         which design this user gets
  -> renderers.renderer(service, style)    the drawing function (falls back to the service's default design)
  -> PNG bytes -> send_photo
```

Parsing, caching and fetching never depend on how the image looks, and drawing functions never fetch anything.

## Modules

| Area | Files |
|---|---|
| Report data (parse + cache shape) | `abyss.py`, `theater.py`, `stygian.py`, `diary.py`, `notes.py`, `profile.py`, `character.py` |
| Designs (pure functions, PNG out) | `render_*_official.py` (Abyss, Theater, Stygian, Notes, Diary), `build_card/` (Character Build Card), `render_showcase.py` + `render_showcase_profile.py` |
| Design registry | `styles.py` (which designs exist per report, defaults, user/owner resolution), `renderers.py` (design -> function) |
| Shared drawing | `ui_kit.py` (fonts, icon decoding, text fitting, portrait tile), `asset_manager.py` (validated assets with fallbacks), `elements.py`, `stats.py` |
| Shared report helpers | `report_utils.py` (time formats, which floors/characters to show) |
| Bundled assets | `app/assets/` (fonts, element/stat/ui icons; sources listed in the README) |

## Adding a new design

1. Write `app/render_<service>_<name>.py` with a function `render_<service>_<name>(data, *, <same keyword arguments as the existing design of that service>, style) -> bytes`.
   Reuse `ui_kit` / `asset_manager`; draw a fallback for every image that can be missing.
2. Register it in `app/renderers.py` (`RENDERERS[("<service>", "<name>")] = ...`).
3. In `app/styles.py`: add the id to `LAYOUTS` (label + description) and to `SERVICE_STYLES["<service>"]`. Change `DEFAULT_STYLE` only when it should become the default.
4. Test: `tests/test_styles.py::test_registry_is_consistent` checks that every listed design has a function. Add a render test with full, empty and corrupt data.

Users who picked the design in `/settings` get it immediately; nobody else changes. `/character <name> compare` renders every design of the character report.

## Rules the code follows

- Never estimate or invent numbers: a value HoYoLAB did not send is not drawn.
- Cached results carry a `SCHEMA_VERSION`; bump it whenever parsing changes what is stored (current: abyss 4, stygian 3, theater 5, character 2, notes 2, diary 1, profile 2).
- Every missing asset has a drawn fallback; misses are recorded (`Assets.missing`) for the owner's diagnostics (`/debug`).
- Pillow: draw translucent shapes on a separate layer and `alpha_composite` them (`ImageDraw` on an RGBA image overwrites alpha).
