import asyncio
from types import SimpleNamespace


from app import settings_menu
from app.bot import on_settings
from app.renderers import RENDERERS, renderer
from app.styles import ALL, DEFAULT_STYLE, GLOBAL_USER, LAYOUTS, SERVICE_STYLES, SERVICES, current_choice, is_valid, pick, resolve


def test_registry_is_consistent():
    """Every design offered to users has a drawing function, a label, and every service has a valid default."""
    assert set(SERVICES) == set(SERVICE_STYLES) == set(DEFAULT_STYLE)
    for svc, styles in SERVICE_STYLES.items():
        assert DEFAULT_STYLE[svc] in styles
        for st in styles:
            assert (svc, st) in RENDERERS and st in LAYOUTS
    assert set(RENDERERS) == {(s, st) for s, sts in SERVICE_STYLES.items() for st in sts}


def test_unknown_style_falls_back_to_default_design():
    assert renderer("abyss", "aurora") is RENDERERS[("abyss", "official")]
    assert renderer("character", "nope") is RENDERERS[("character", "build")]


def test_pick_precedence():
    rows = [
        {"user_id": 0, "service": "*", "style": "showcase"},
        {"user_id": 0, "service": "character", "style": "build"},
        {"user_id": 5, "service": "*", "style": "showcase"},
    ]
    assert pick(rows, 9, "profile") == "showcase"      # owner default for all (valid for profile)
    assert pick(rows, 9, "notes") == "official"        # "all" pick is not valid for notes -> default
    assert pick(rows, 9, "character") == "build"       # owner default for that service
    assert pick(rows, 5, "character") == "showcase"    # own "all" beats owner's service default
    assert pick([], 5, "abyss") == "official"
    assert pick([{"user_id": 5, "service": "abyss", "style": "aurora"}], 5, "abyss") == "official"  # removed design
    assert is_valid("character", "build") and not is_valid("character", "x") and not is_valid("zzz", "build")
    assert current_choice(rows, 5, ALL) == "showcase" and current_choice(rows, 5, "abyss") is None


def test_resolve_survives_db_failure():
    class Broken:
        async def get_style_prefs(self, uid):
            raise RuntimeError("x")
    assert asyncio.run(resolve(Broken(), 1, "abyss")) == "official"


def test_menu_callbacks_fit_telegram_limit():
    for scope in ("u", "g"):
        for svc in SERVICES:
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
    _, edits = _run("st:set:u:character:showcase", 5, db)
    assert db.prefs == {(5, "character"): "showcase"} and edits
    answers, _ = _run("st:set:g:character:build", 5, db)
    assert (0, "character") not in db.prefs and "owner" in answers[0].lower()
    answers, _ = _run("st:own", 5, db)
    assert "owner" in answers[0].lower()
    _run("st:set:g:character:build", 1, db)
    assert db.prefs[(GLOBAL_USER, "character")] == "build"
    _run("st:set:u:character:default", 5, db)
    assert (5, "character") not in db.prefs
    _run("st:set:u:character:evil", 5, db)
    assert (5, "character") not in db.prefs
    _run("st:set:u:abyss:showcase", 5, db)  # a design that exists, but not for this report
    assert (5, "abyss") not in db.prefs


def test_share_toggle_and_group_chat_refused():
    db = FakeDb()
    _run("st:share:1", 5, db)
    assert db.sharing is True
    answers, edits = _run("st:share:0", 5, db, private=False)
    assert db.sharing is True and not edits
