# Decisions and changes from the original plan (v1.0, 31 Oct 2026)

Reviewed against the actual source of `genshin.py` 1.7.31 (MIT) and `GenshinUID` 5.2.0 / plugin 7.0.0 (GPL-3.0),
both read from their repositories on 31 Oct 2026.

## Confirmed by the owner (Shiper)

| Decision | Choice |
|---|---|
| Image strategy | Own bot + `genshin.py` + own Pillow templates. GenshinUID is a visual reference only. |
| Servers | HoYoLAB international only (no Miyoushe/China). |
| Account linking | Small web page served by the same service. |
| First milestone | Bot skeleton + account linking + Daily Notes. |
| Hosting | Render Free + UptimeRobot + Supabase (unchanged). |

## What the review found

1. **GenshinUID cannot be used as a renderer library.** Its `AGENTS.md` states it is a plugin for the `gsuid_core`
   framework (installed into `gsuid_core/plugins/GenshinUID/`). Its draw modules import `gsuid_core` for events, fonts,
   image tools and the Mihoyo API models, and fetch data through their own `mys_api` layer, not `genshin.py`.
   Reusing it means either running the whole framework (own database, Chinese-first UI, conflicts with the
   "Supabase is the only source of truth" rule) or copying GPL-3.0 code. Neither fits, so it is a design reference only.
2. **Password login was removed from the first release.** `genshin.py` documents `login_with_password` only through a
   CLI flow where the user solves a CAPTCHA by hand; the docs show no way to run it from a web page for many users.
   The plan itself gated this behind a spike and forbade CAPTCHA bypass. The cookie-based route is the one the
   library documents. The `genshin.py` source also contains app/web/QR/e-mail-verification login sub-clients; evaluating
   them is a possible later spike, not part of this milestone.
3. **`get_genshin_notes(autoauth=True)` changes the user's account settings** (it switches real-time notes on). The
   plan says the bot performs no account-modifying actions, so the bot calls it with `autoauth=False` and tells the
   user to enable the setting themselves.
4. **Linking page lives in the same service**, not a separately hosted app (the plan itself preferred one deployment).
5. **Dropped from the schema for now:** `telegram_users`, `processed_updates` (long polling already tracks offsets),
   and the group tables (groups come in a later milestone). `TELEGRAM_WEBHOOK_SECRET` is dropped (polling only).
6. **Added:** `link_sessions.attempts` (lock a link after 5 failed submissions), AAD binding of each ciphertext to its
   account id, a cookie-name allow-list (anything else a user pastes is discarded), disabled HTTP access logs
   (the URL contains the token) and Telegram-token redaction in logs.
7. **One Telegram owner per game UID** is enforced by a unique constraint; a second owner is refused with a generic message.

## Known limits of this milestone

- **Not yet run against a real Supabase project or the real HoYoLAB API.** The database layer was verified by checking
  the exact HTTP requests it builds against a mocked transport; provider/web/render logic by 45 unit tests with fakes.
  The first real run needs the owner's Supabase/Render/Telegram credentials and a spare HoYoLAB account.
- **Cookie names**: the page asks for `ltuid_v2`, `ltoken_v2`, `ltmid_v2`, because those are the v2 names `genshin.py`
  recognises. Whether HoYoLAB currently shows exactly these in the browser must be confirmed on the first real link.
- The image uses Pillow's built-in font and has no character art yet. It is functional, not a Battle Chronicle clone.
- Key rotation is not implemented: a ciphertext with a different `key_version` is refused.
- `UptimeRobot` keep-alive remains best-effort, as the original plan already states.

## Next milestones (proposed)

1. First real run on a spare account; fix whatever HoYoLAB actually returns.
2. Profile/overview + character cards, then Abyss, Theater, Stygian (all have `genshin.py` methods).
3. Group sharing (`telegram_groups`, `group_settings`, `account_sharing`) with per-account consent.
4. Character art/assets with a license review of each source before bundling.


---

# Milestone 2: report design and the Spiral Abyss report (1 Nov 2026)

## Design source
The owner supplied screenshots of the official HoYoLAB Battle Chronicle pages and share cards (profile summary, all
characters, character detail, Spiral Abyss, Imaginarium Theater, Stygian Onslaught). Those are the target look:
dark navy panels, cream-gold serif headings, rarity-coloured portrait tiles with a cream level strip, six-point stars.
`app/ui_kit.py` holds the shared palette and components; reports are drawn from scratch with Pillow.
No HoYoverse artwork, logo or QR code is bundled. Fonts are bundled under the SIL OFL (`app/assets/fonts/`).

## Ready-made libraries: what exists and why they were not adopted wholesale
Checked on 31 Oct 2026 (all actively maintained, so freshness is not the problem):

| Project | Last activity | License | Verdict |
|---|---|---|---|
| genshin.py 1.7.31 | commit 26 Oct 2026 | MIT | **Used.** Has Abyss, Theater (incl. Lunar Arcana fields), Stygian, Notes, stats models. |
| hoyo-buddy 1.17.0 (same author) | commit 31 Oct 2026 | AGPL-3.0 | **Reference only.** Discord bot with Pillow drawers for Genshin Abyss/Theater/Stygian/Notes/builds, built on genshin.py models, but in its own visual style, coupled to its `Drawer` class and a separate assets repo. Its web-login API (`hoyo_buddy/api`) is the first place to look for the future phone-friendly linking. |
| GenshinUID plugin 7.0.0 | commit 23 Oct 2026 | GPL-3.0 | Not used: needs the `gsuid_core` framework. |
| EnkaCard / enkanetworkcard | PyPI release Dec 2022 | n/a | Not used (stale on PyPI). |

None of them reproduces the official share-card look, so the layouts are original, informed by the screenshots.

## Findings that changed the code
1. **genshin.py rewrites character icons to `https://enka.network/ui/...`** (`models/genshin/character.py`). The icon
   downloader therefore allows `enka.network` and `gi.yatta.moe` besides HoYoverse hosts; without this every portrait
   would silently have fallen back to a placeholder.
2. **genshin.py downloads its character-name table from Enka/Ambr on the first request** (`chronicle/base.py`). Production
   needs outbound HTTPS to those hosts (Render allows it); a brand-new character may show a guessed name until they update.
3. **Bug fixed from milestone 1:** `genshin.VisitsTooFrequently` is not a top-level export; the except clause would have
   raised AttributeError and hidden the real error. Now `genshin.errors.VisitsTooFrequently`, covered by a test.
4. Server times use genshin.py's own table (Asia/TW +8, Europe +1, America -5).

## Not yet verified
The Abyss image has only been rendered with generated stand-in portraits. Real portraits, real API payloads and the
Telegram upload have not been exercised. The official share card also uses large background art and splash art that
the HoYoLAB API does not provide; they are intentionally not reproduced yet (art licensing is the owner's call).

---

# Milestone 2.1: missing portraits, and hoyo-buddy as a second style (1 Nov 2026)

## Missing portraits (reported by the owner after the first real run)
Three characters showed placeholders in every chamber, so the cause is specific icon URLs, not random failures.
Most likely cause (not confirmed, the sandbox cannot reach enka.network): genshin.py replaces each character icon with
`https://enka.network/ui/UI_AvatarIcon_<name>.png`, and that file is missing for some characters.
Fix: the Abyss payload is now parsed directly (`AbyssData.from_raw`), so the icon URL is the one HoYoLAB itself returns
(what the official site displays); the enka.network copy is only a fallback (`ImageFetcher.fetch_first`).
Every failed download is now logged with its URL and reason (HTTP status or error class), so if a portrait is still
missing the Render log says exactly why. Cache schema bumped to 2 so old cached Abyss data is refreshed.

## hoyo-buddy renderers as a selectable style: not possible as-is
- Its README states that `hoyo-buddy-assets` is **private**; the Genshin drawers load backgrounds, block images and
  fonts from `hoyo-buddy-assets/assets/...`. Without that repository they cannot produce an image, and no public
  access exists.
- Each drawer also imports ~14 internal modules (~4,000 lines: config, cache, emojis, l10n, constants...) and
  third-party packages that a Telegram bot does not otherwise need (discord.py, redis, sentry, enka, ambr, yatta, hakushin...).
- AGPL-3.0 would apply to Klee if any of its code were copied.
It remains a good layout and data-handling reference, but a drop-in second style is not available.

## Milestone 2.2: portraits, second attempt (1 Nov 2026)
Preferring HoYoLAB's raw icon URL (2.1) made things worse: more portraits went blank (the raw URL is often the small
"side" icon or refuses hotlinking). Now each portrait has an ordered candidate list: enka.network by character id (the
first version, worked for most) -> enka.network by the name in HoYoLAB's URL -> gi.yatta.moe -> HoYoLAB's URL.
Downloads retry once on 429/5xx/timeouts. If any portrait still fails, the bot sends a "Note:" line in the chat with the
HTTP codes/hosts, so diagnosis does not depend on Render logs. Cache schema bumped to 3.

## Milestone 2.3: the real portrait bug, and a persistent icon library (1 Nov 2026)
**Root cause of the blank portraits:** `StreamReader.read(n)` returns only the bytes that have arrived so far, so larger
PNGs were silently cut off (the HoYoLAB one in the diagnostic was exactly 32768 bytes). Truncated images could not be
drawn, hence a placeholder. Fixed by reading the whole body in chunks (regression test with a slow chunked server).

**Persistent library:** Render's disk is wiped on restart, so icons and genshin.py's character table are stored in a
private Supabase Storage bucket `game-assets` (created automatically on startup).
Lookup order: memory -> Supabase Storage -> network (and a successful download is saved). A recently failed URL is not
retried for 10 minutes. Automatic update: 45 s after startup and every 24 h the character table is refreshed and every
known portrait that is not stored yet is downloaded. Manual: `/updateicons` (owner only, `ADMIN_TELEGRAM_IDS`);
`/updateicons force` re-downloads everything. `/myid` shows your Telegram id.

## Milestone 3: profile overview and character grid (1 Nov 2026)
`/profile` (overview cells + top 16 characters) and `/characters` (all, 8 per row, level strip and constellation badge)
use `genshin.get_genshin_user` (stats + character list in two requests), cached 10 min. Portraits use the same
candidate/persistent-store pipeline as the Abyss. Per-character detail (weapon, artifacts, talents) is not drawn yet;
it needs `get_genshin_detailed_characters` and is a candidate for the next step, with Theater and Stygian.

## Milestone 4: Imaginarium Theater (1 Nov 2026)
`/theater` (latest 4 acts, `/theater all` for every act) parses HoYoLAB's raw `role_combat` payload directly
(`TheaterData.from_raw`), so portraits use the same candidate/persistent-store pipeline. Shows the season summary,
notable characters, each act's cast with Trial/Support tags, Wondrous Booms and Mystery Caches (names only; their icons
are not drawn). Cached 30 min. Not yet verified against a real payload: field names follow genshin.py's model aliases.

## Milestone 5: previous season for Theater, and Stygian Onslaught (1 Nov 2026)
The Theater payload lists several seasons, and genshin.py's `previous` flag does nothing for it, so the season is picked
by schedule (current = contains now, previous = latest ended; list order if no schedule). `/theater previous`.
`/stygian` (options `previous`, `coop`) parses the raw `hard_challenge` list the same way: season summary (best
difficulty and time), each challenge's team, strongest-strike / highest-damage characters and enemy notes (markup
stripped). Not yet verified against real payloads (field names follow genshin.py's model aliases).

## Milestone 6: single-character detail (2 Nov 2026)
`/character <name>` finds the character in the (cached) profile by name (exact, then prefix, then substring), then asks
HoYoLAB's `character/detail` for just that id (`return_raw_data=True`, parsed in `app/character.py`, cached 10 min).
Card: portrait/level/constellation/friendship, weapon with main and sub stat, five artifacts with main stat and four
substats, set bonuses, attributes, talents (level > 0 only) and constellation circles. Profile cache schema is now 2
(`ProfChar.id`). Not yet verified on a real payload; the property names come from the response's own `property_map`.

## Milestone 7: groups (2 Nov 2026)
Rules: linking and account management stay private-chat only. In a group, a report command shows the *asker's own*
default account. Replying to another member's message with a report command shows that member's default account only
if they ran `/share on` (per-account flag `shared_in_groups`, off by default; revocable any time). Group admins can
turn the bot off/on with `/groupreports on|off` (table `group_settings`, groups are enabled by default; a missing table
means enabled). Abuse limits: the asker's 10 s cooldown applies, plus one report per group every 3 s (silent).
The shared image shows nickname, masked UID, server and game data only; cookies are never reachable from a group.
Requires `supabase/migrations/002_groups.sql` (adds the flag and the table); until it is applied, `/share` and
`/groupreports` answer that the database update is pending and everything else keeps working.

## Milestone 8: sign in with e-mail and password on the link page (2 Nov 2026)
Researched before building (genshin.py 1.7.31 source, hoyo-buddy docs):
- genshin.py's overseas web sign-in (`_os_web_login`, token_type 6) returns `ltuid_v2`, `ltoken_v2`, `ltmid_v2`
  (+ cookie_token_v2, account ids). We keep only the first three: exactly what the pasted-cookie method stores, so the
  link lasts as long as a pasted-cookie link. Hoyo-buddy's docs state such cookies last about one year and stop working
  immediately when the HoYoverse password changes; we did not measure this ourselves.
- It needs a HoYoverse e-mail and password. Accounts that sign in to the game with Google/Apple/Facebook/Steam/console
  must first set a password in the HoYoverse account center (hoyo-buddy's pre-setup guide). The cookie method stays.
- Captcha: HoYoverse may answer with a Geetest v3 challenge. Flow: form (no scripts, strict CSP) -> server asks HoYoverse
  -> if captcha: sign-in is parked in memory (single use, 5 min, bound to that link and user) and the browser is sent to
  a captcha page that contains no secret and holds no session id; the solved answer is posted back and the server
  finishes the sign-in. Only the captcha page may load third-party scripts (Geetest).
- Password handling: never logged, stored or echoed; wiped from the parked object after use; sent to HoYoverse only
  through genshin.py (RSA-encrypted as the library does). Link attempts are counted (5 max) as before.
- stoken is deliberately not stored (it is a stronger credential than the cookies we need).
Not yet tested against the real HoYoverse service: the sandbox cannot reach it. Tests use a stubbed genshin.py.

## Milestone 9: image styles and /settings
- Enka-based card libraries (enkacard, enkanetworkcard, hattvr/enka-card) were rejected: character cards only, need the in-game showcase, unmaintained since 2022-2024, no licence stated.
- Styles are colour themes (`ui_kit.THEMES`: classic, aurora, sakura, paper) applied through `C` and the `@themed` decorator, so every renderer supports every theme. No third-party artwork is bundled. `styles.SERVICE_STYLES` is per service so a service can get its own layout later.
- Precedence: user's pick for the service, user's "all", owner default for the service, owner default for all, classic. Stored in `style_prefs` (user_id 0 = owner default). Needs `supabase/migrations/003_style_prefs.sql`; without it everything stays classic.
- `/settings` (private chat): inline buttons for style per service, group sharing toggle, preview image; owner section (ADMIN_TELEGRAM_IDS) sets the default for everyone. Owner scope is re-checked on every button press.

## Milestone 10: Traveler's Diary and resin reminders
- `/diary` uses genshin.py's raw ledger endpoint for the server-time month (current or previous), cached 20 minutes.
- Resin reminders: `/settings` → Resin reminder (off, 80, 120, 160, when full). A background loop (first run 90 s after start, then every 10 min, one user per second) reads the default account's Daily Notes through the normal cached provider path and sends one private message per rise (`armed` flag in table `reminders`, migration `004_reminders.sql`). Stale data never triggers a message; an expired session sends one notice; users who blocked the bot are switched off.

## Milestone 11: design phase, first layout style ("Showcase")
- Evaluated for reuse: hoyo-buddy (GPL-3.0; covers abyss/theater/stygian/notes/characters from genshin.py models, but imports discord, its own l10n/cache layers and needs the private `hoyo-buddy-assets` submodule, so it cannot run standalone), GenshinUID (GPL-3.0, needs the gsuid_core framework), enkacard 3.3.9 (no licence, character cards only, fetches its own data from Enka by UID, last push Oct 2024). None can be embedded without changing how data is fetched.
- Chosen path: our own additional layouts that use the same normalized data. Styles are now either colour themes (all services) or layouts with their own drawing code (`styles.LAYOUTS`, `LAYOUT_SERVICES`). First layout: `showcase` for the character card (`render_showcase.py`): splash art from enka.network (then gi.yatta.moe), glass panels, element accent colour; falls back to the portrait over a blurred background when the splash cannot be downloaded.
- Showcase now also covers profile/characters (`render_showcase_profile.py`, top character splash as the blurred header).
- Next layouts to add the same way: Abyss, Theater, Stygian, Notes, Diary.

## Milestone 12: Stygian in the official Battle Chronicle look
- New layout style `official` (`render_stygian_official.py`), the built-in default for `/stygian` (`styles.DEFAULT_STYLE`); owner/user choices still override it. Drawn from the official share card: purple glass panels, Best Record bar, tall team tiles (HoYoLAB card art first, Enka fallbacks), boss art from the payload (`monster.icon`) with level pill, and the Strongest Single Strike / Highest Total Damage Dealt rows. No HoYoverse logo or QR code.
- `/debug stygian` (owner) lists the payload's key names to check field assumptions.

## Element icons
Official in-game element icons (UI_Icon_Element_*) are bundled in `app/assets/elements/` (source: helingping/gsgametextures, game art © HoYoverse). No network needed; drawn glyphs remain only as a fallback. The wider asset-library plan (manifest, Supabase storage, asset manager) is a later phase.

## Milestone 13: Character Build Card (independent template)
- New packages: `app/asset_manager.py` (logical keys, bundled + fetched sources, validation, fallbacks, `Assets.missing`), `app/build_card/` (`model.py` view model, `theme.py` per-element palettes, `layers.py` procedural layers, `template.py` drawing). Registered as layout style `build` for the `character` service; Showcase and the colour styles are untouched.
- Art tiers: full artwork (HoYoLAB `image`), splash (enka/yatta `UI_Gacha_AvatarImg_*`), portrait icon; each tier is validated by size/aspect and the first valid one is used.
- Data rules: only fields HoYoLAB sends are drawn (`times` -> roll ticks, `base`/`add` -> small numbers). Missing -> not drawn. Weapon max level only when `promote_level` is sent. Own-element DMG bonus chosen by name match only.
- `/character <name> compare` renders classic, showcase and build from the same data. Owner `/debug character <name>` prints which fields the real payload contains.
- Credits: yuanshen.ttf, stat icons, lock icon, star rows from GenshinUID (GPL-3.0); element icons from helingping/gsgametextures; all game art (c) HoYoverse.

## Milestone 14: Theater official look (two acts per row)
- `app/render_theater_official.py`: library header, "Past Performances" panel (best record, stella row, flowers, support counts), statistics, then the Cast List with cream act cards, two per row. Default style for `theater` (classic stays selectable). In this style all acts are shown (the 2-column grid keeps the image short).
- Data: `stellas` (`get_medal_round_list`) and per-act blessing level/text are parsed only if HoYoLAB sends them (`splendour_buff.summary`); otherwise those parts are simply not drawn. `/debug theater` now lists round keys to confirm.
- Textures (library background, stella and trophy icons) from GenshinUID (GPL-3.0).

## Milestone 15 - Spiral Abyss official look
`render_abyss_official` (layout "official", default for abyss; classic stays selectable). The Challenge Summary (stars, deepest descent, battles, most played, notable stats) is always drawn on top, also for `/abyss 11` or `/abyss 12`. Chamber halves sit side by side to keep the image short. Star icons: GenshinUID textures (GPL-3.0).

Milestone 16 - Notes official look + Abyss stat icons: Notes uses cream cards (resin full width, 2x2 grid, two-column expeditions) with bundled game icons; expedition portraits come from HoYoLAB side icons (notes schema 2). Abyss "Notable Stats" portraits are now downloaded like the other icons (they were missing from the fetch list; abyss schema 4).
