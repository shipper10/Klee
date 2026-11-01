from types import SimpleNamespace

import pytest

from app import bot


class Db:
    def __init__(self):
        self.accounts = {
            1: [{"id": "a1", "game_uid": "711111111", "region": "os_asia", "nickname": "Me", "is_default": True, "shared_in_groups": False}],
            2: [{"id": "a2", "game_uid": "722222222", "region": "os_euro", "nickname": "Friend", "is_default": True, "shared_in_groups": True}],
            3: [{"id": "a3", "game_uid": "733333333", "region": "os_usa", "nickname": "Shy", "is_default": True, "shared_in_groups": False}],
        }
        self.enabled = {}
        self.saved = {}

    async def list_accounts(self, user_id):
        return self.accounts.get(user_id, [])

    async def group_reports_enabled(self, chat_id):
        return self.enabled.get(chat_id, True)

    async def set_group_reports(self, chat_id, enabled, by):
        self.enabled[chat_id] = enabled

    async def set_sharing(self, user_id, enabled):
        for a in self.accounts.get(user_id, []):
            a["shared_in_groups"] = enabled


class Msg:
    def __init__(self, reply_to=None):
        self.sent, self.reply_to_message = [], reply_to

    async def reply_text(self, text, **kw):
        self.sent.append(text)


def user(uid, bot_=False, name="U"):
    return SimpleNamespace(id=uid, is_bot=bot_, first_name=name)


def upd(uid, chat_type="supergroup", chat_id=-100, reply_to=None):
    return SimpleNamespace(effective_message=Msg(reply_to), effective_user=user(uid),
                           effective_chat=SimpleNamespace(type=chat_type, id=chat_id))


def context(db, args=None, status="member"):
    deps = bot.Deps(db=db, provider=None, public_base_url="https://x")  # type: ignore[arg-type]

    async def get_chat_member(chat_id, uid):
        return SimpleNamespace(status=status)

    return SimpleNamespace(args=args or [], bot=SimpleNamespace(get_chat_member=get_chat_member),
                           application=SimpleNamespace(bot_data={"deps": deps}))


async def test_private_uses_own_default_account():
    u = upd(1, "private", chat_id=1)
    got = await bot._resolve(u, context(Db()))
    assert got[0]["id"] == "a1" and got[1] == 1
    u = upd(9, "private", chat_id=9)
    assert await bot._resolve(u, context(Db())) is None and "/link" in u.effective_message.sent[0]


async def test_group_uses_own_account_without_reply():
    u = upd(1)
    assert (await bot._resolve(u, context(Db())))[0]["id"] == "a1"


async def test_group_reply_to_sharing_user_shows_their_account_but_cooldown_is_the_askers():
    u = upd(1, reply_to=SimpleNamespace(from_user=user(2, name="Friend")))
    account, asker = await bot._resolve(u, context(Db()))
    assert account["id"] == "a2" and asker == 1


async def test_group_reply_to_user_who_did_not_share_is_refused_and_nothing_leaks():
    for target in (3, 99):
        u = upd(1, reply_to=SimpleNamespace(from_user=user(target, name="Shy")))
        assert await bot._resolve(u, context(Db())) is None
        assert "not allowed sharing" in u.effective_message.sent[0] and "73" not in u.effective_message.sent[0]


async def test_reply_to_a_bot_or_to_self_falls_back_to_own_account():
    for target in (user(55, bot_=True), user(1)):
        u = upd(1, reply_to=SimpleNamespace(from_user=target))
        assert (await bot._resolve(u, context(Db())))[0]["id"] == "a1"


async def test_group_without_linked_account_gets_private_link_hint():
    u = upd(9)
    assert await bot._resolve(u, context(Db())) is None and "private chat" in u.effective_message.sent[0]


async def test_disabled_group_refuses_and_chat_rate_limit_is_silent():
    db = Db()
    db.enabled[-100] = False
    u = upd(1)
    assert await bot._resolve(u, context(db)) is None and "turned off" in u.effective_message.sent[0]
    c = context(Db())
    assert await bot._resolve(upd(1), c) is not None
    quick = upd(1)
    assert await bot._resolve(quick, c) is None and quick.effective_message.sent == []  # silent


async def test_share_toggle_in_private_only():
    db = Db()
    c = context(db, ["on"])
    u = upd(1, "private", chat_id=1)
    await bot.share(u, c)
    assert db.accounts[1][0]["shared_in_groups"] is True and "ON" in u.effective_message.sent[-1]
    c.args = ["off"]
    await bot.share(u, c)
    assert db.accounts[1][0]["shared_in_groups"] is False and "OFF" in u.effective_message.sent[-1]
    g = upd(1)
    await bot.share(g, context(db, ["on"]))
    assert "private chat" in g.effective_message.sent[0] and db.accounts[1][0]["shared_in_groups"] is False


async def test_share_reports_when_database_not_migrated():
    db = Db()

    async def boom(user_id, enabled):
        raise RuntimeError("column does not exist")

    db.set_sharing = boom
    u = upd(1, "private", chat_id=1)
    await bot.share(u, context(db, ["on"]))
    assert "not available yet" in u.effective_message.sent[0]


async def test_groupreports_admin_only():
    db = Db()
    u = upd(1)
    await bot.groupreports(u, context(db, ["off"], status="member"))
    assert "Only group admins" in u.effective_message.sent[0] and db.enabled == {}
    u = upd(1)
    await bot.groupreports(u, context(db, ["off"], status="administrator"))
    assert db.enabled == {-100: False} and "OFF" in u.effective_message.sent[0]
    p = upd(1, "private", chat_id=1)
    await bot.groupreports(p, context(db, ["on"], status="creator"))
    assert "inside the group" in p.effective_message.sent[0]
