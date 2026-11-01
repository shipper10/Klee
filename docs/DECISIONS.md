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
