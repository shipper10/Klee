> **Status (4 Nov 2026): historical.** This analysis led to the Asset Manager, the Build Card and the official-look designs now in the code.
> For the current structure and how to add a design, see [`ARCHITECTURE.md`](ARCHITECTURE.md). The old colour-theme renderers described in section 1 were removed.

# Klee rendering: analysis and plan (Character Build Card)

## 1. Current system (as inspected)

Data path (kept as is):
HoYoLAB `character/detail` -> `genshin_provider.get_character` (cache + schema version) -> `character.CharacterDetail.from_raw` -> `bot._send_character` -> images fetched by `ImageFetcher` (memory LRU -> Supabase Storage -> network) -> renderer returns PNG bytes.

Renderers: one function per report (`render_*.py`, 6k lines in `app/`), shared helpers in `ui_kit.py` (themes, panel, tile, stars, fonts). Styles are chosen per user via `styles.py` (`LAYOUTS`), so a new template can be added without touching commands.

Assets today: Inter + Source Serif fonts, 7 official element icons (just added). Everything else is fetched per report (portraits, weapon, artifact icons) or drawn in code (glass panels, circles, glyphs).

## 2. Why the current card looks weak (vs the reference)

1. **No layered art.** The reference is a full-height splash on a coloured, textured, element-tinted background with light rays. Ours is a blurred, darkened copy of the same image. The splash itself is also the weakest dependency: its URL (enka UI_Gacha_AvatarImg) is unverified from our side, so on failure we fall back to a small portrait.
2. **Text instead of game icons.** Stats are plain words ("Crit Rate"); the reference uses the in-game stat icon next to every value. Artifact slots, weapon type, element, talent and constellation icons are missing or drawn as circles with numbers.
3. **Data we receive but throw away:**
   - `times` per artifact substat (roll count -> the small tick marks under each substat in the reference);
   - `base` and `add` per stat (the "13,103 +5,079" under HP/ATK/DEF);
   - skill icons and levels incl. constellation bonus, constellation icons with locked/unlocked state;
   - `PropInfo.icon` (HoYoLAB sends an icon URL for each stat) and artifact set names with piece counts.
4. **No design system.** Every renderer hard-codes coordinates and colours; there is no layer model (background / art / panels / content / overlay), no icon registry, no typography scale. This is why tweaks only change colours.
5. **Typography.** One generic sans plus a serif title. The reference uses a game-like font with strong weight contrast (large main values, small base/bonus values) and consistent baselines.
6. **Textures.** No real panel texture, no grain, no inner highlights, no per-element palette beyond one accent colour.

## 3. Assets we are missing

| Need | Source | Status |
|---|---|---|
| Character splash (full art) | enka `UI_Gacha_AvatarImg_<Name>` / yatta | URL unverified from our side; need a verified fallback chain and a one-time diagnostic from Render |
| Stat icons (HP, ATK, DEF, EM, Crit, ER, DMG bonus...) | HoYoLAB `PropInfo.icon` (already in payload) and game textures (UI_Icon_Property atlas in helingping/gsgametextures) | Not used yet; need to confirm the CDN URLs load, else crop from the atlas and bundle |
| Element icons | bundled | Done |
| Artifact slot icons, weapon type icons, star rating | game textures | To bundle (small) |
| Constellation / talent icons | HoYoLAB payload (`constellations[].icon`, `skills[].icon`) | Not parsed yet |
| Element-tinted backgrounds + light-ray overlay | game textures (Gacha / Avatar) or GenshinUID `utils/image` backgrounds (GPL-3, credit) | To choose and bundle |
| Panel frame textures (artifact rows) | GenshinUID `genshinuid_enka/texture2D` or drawn with layered gradients | To choose |
| Game-like font | Genshin-style open font (e.g. Gilroy-like) or the game's own font from GenshinUID `yuanshen_origin.ttf` | To decide |

## 4. Target architecture (incremental, nothing rewritten)

```
report data (CharacterDetail)           unchanged
        |
 view model (new)  character_card_model.py  -> plain dataclass: header, weapon, stat rows (icon key, base, bonus, final), artifact rows (icon keys, main, subs with roll ticks), talents, constellations, palette key
        |
 template (new)    templates/character_build.py  -> pure drawing from the view model + assets; layers: background, art, panels, content, overlay
        |
 asset registry (new) assets.py -> logical keys ("stat:crit_rate", "element:Pyro", "slot:flower") -> bundled file or fetched URL; one place to fix any source
        |
 styles.py: register as a layout of "character" (default stays showcase until approved)
```

The old renderers keep working; the new template is selectable in /settings, and becomes the default only after approval. The same pieces (asset registry, typography scale, panel textures) then serve Abyss/Theater/Stygian later.

## 5. Plan

1. Verify asset sources (diagnostic command for the owner; bundle what is small and certain).
2. Extend parsing in `character.py` (roll counts, base/add, skill + constellation icons, stat icons) with a schema bump; no change to fetching.
3. Asset registry + typography scale + panel texture helpers.
4. Character Build Card template at the reference proportions (1722x717, three columns: art + constellations, weapon + stats, 5 artifact rows).
5. Visual check against the reference with fixture data (several elements, 4/5-star weapons, missing pieces), tests for the view model, then register as a style.

## 6. Risks and open questions

- Splash art availability is the biggest quality factor; without it the left column cannot reach the reference level. Needs the Render diagnostic.
- Reference fonts are game fonts; using GenshinUID's `yuanshen_origin.ttf` is the fastest route (game asset, credit).
- GenshinUID assets are GPL-3.0: credit them in the README.
