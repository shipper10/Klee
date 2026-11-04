import asyncio
import io
from types import SimpleNamespace

from PIL import Image

from app import settings_menu
from app.bot import Deps, on_settings
from app.render_abyss import render_abyss_card, select_floors
from app.render_notes import render_notes_card
from app.styles import ALL, SERVICES, GLOBAL_USER, current_choice, is_valid, pick, resolve
from app.ui_kit import THEMES
from tests.test_render_abyss import FETCHED, _icon, sample as abyss_sample
from tests.test_render_notes import sample as notes_sample


def test_pick_precedence():
    rows = [
        {"user_id": 0, "service": "*", "style": "aurora"},
        {"user_id": 0, "service": "abyss", "style": "paper"},
        {"user_id": 5, "service": "*", "style": "sakura"},
    ]
    assert pick(rows, 9, "notes") == "aurora"      # owner default for all
    assert pick(rows, 9, "abyss") == "paper"       # owner default for that service
    assert pick(rows, 5, "notes") == "sakura"      # own "all"
    assert pick(rows, 5, "abyss") == "sakura"      # own beats owner
    assert pick([], 5, "zzz") == "classic"
    assert pick([{"user_id": 5, "service": "*", "style": "nope"}], 5, "zzz") == "classic"
    assert is_valid("abyss", "paper") and not is_valid("abyss", "x") and not is_valid("zzz", "paper")
    assert current_choice(rows, 5, ALL) == "sakura" and current_choice(rows, 5, "abyss") is None


def test_resolve_survives_db_failure():
    class Broken:
        async def get_style_prefs(self, uid):
            raise RuntimeError("x")
    assert asyncio.run(resolve(Broken(), 1, "zzz")) == "classic"


def test_every_style_renders_and_differs():
    data = abyss_sample()
    icons = {u: _icon(u) for u in data.icon_urls()}
    pngs = {}
    for sid in THEMES:
        pngs[sid] = render_abyss_card(data, nickname="x", icons=icons, floors=select_floors(data, None), tz_hours=8,
                                       fetched_at=FETCHED, source="live", style=sid)
        Image.open(io.BytesIO(pngs[sid])).verify()
        n = render_notes_card(notes_sample(), nickname="x", uid_masked="1***", server_label="EU", fetched_at=FETCHED, source="live", style=sid)
        Image.open(io.BytesIO(n)).verify()
    assert len(set(pngs.values())) == len(THEMES)
    # unknown style falls back to classic
    again = render_abyss_card(data, nickname="x", icons=icons, floors=select_floors(data, None), tz_hours=8,
                              fetched_at=FETCHED, source="live", style="bogus")
    assert again == pngs["classic"]


def test_preview_renders():
    Image.open(io.BytesIO(settings_menu.render_style_preview())).verify()


def test_menu_callbacks_fit_telegram_limit():
    for scope in ("u", "g"):
        for svc in ["all", *SERVICES]:
            text, markup = settings_menu.style_page(scope, svc, [], 7)
            for row in markup.inline_keyboard:
                for b in row:
                    assert len(b.callback_data.encode()) <= 64
    _, m = settings_menu.home(True, False)
    assert any(b.callback_data == "st:own" for r in m.inline_keyboard for b in r)
    _, m = settings_menu.home(False, None)
    assert not any(b.callback_data == "st:own" for r in m.inline_keyboard for b in r)


class FakeDb:
    def __init__(self):
        self.prefs = {}
        self.sharing = None

    async def get_style_prefs(self, uid):
        return [{"user_id": u, "service": s, "style": st} for (u, s), st in self.prefs.items() if u in (0, uid)]

    async def set_style_pref(self, uid, svc, style):
        if style is None:
            self.prefs.pop((uid, svc), None)
        else:
            self.prefs[(uid, svc)] = style

    async def list_accounts(self, uid):
        return [{"id": "a", "shared_in_groups": bool(self.sharing)}]

    async def set_sharing(self, uid, enabled):
        self.sharing = enabled


def _run(data, user_id, db, admins=(1,), private=True):
    answers, edits = [], []

    class Q:
        def __init__(self):
            self.data = data
            self.from_user = SimpleNamespace(id=user_id)
            self.message = SimpleNamespace(chat=SimpleNamespace(type="private" if private else "group", id=user_id))

        async def answer(self, text=None, show_alert=False):
            answers.append(text)

        async def edit_message_text(self, text, reply_markup=None):
            edits.append(text)

    ctx = SimpleNamespace(application=SimpleNamespace(bot_data={"deps": SimpleNamespace(db=db, admin_ids=set(admins))}))
    import app.bot as bot
    orig = bot._deps
    bot._deps = lambda c: c.application.bot_data["deps"]
    try:
        asyncio.run(on_settings(SimpleNamespace(callback_query=Q()), ctx))
    finally:
        bot._deps = orig
    return answers, edits


def test_user_sets_own_style_and_cannot_touch_owner_scope():
    db = FakeDb()
    _, edits = _run("st:set:u:abyss:paper", 5, db)
    assert db.prefs == {(5, "abyss"): "paper"} and edits
    answers, _ = _run("st:set:g:abyss:aurora", 5, db)
    assert (0, "abyss") not in db.prefs and "owner" in answers[0].lower()
    answers, _ = _run("st:own", 5, db)
    assert "owner" in answers[0].lower()
    _run("st:set:g:all:aurora", 1, db)
    assert db.prefs[(GLOBAL_USER, "*")] == "aurora"
    _run("st:set:u:abyss:default", 5, db)
    assert (5, "abyss") not in db.prefs
    _run("st:set:u:abyss:evil", 5, db)
    assert (5, "abyss") not in db.prefs


def test_share_toggle_and_group_chat_refused():
    db = FakeDb()
    _run("st:share:1", 5, db)
    assert db.sharing is True
    answers, edits = _run("st:share:0", 5, db, private=False)
    assert db.sharing is True and not edits
