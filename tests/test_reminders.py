import asyncio
from datetime import datetime, timezone
from types import SimpleNamespace

from app import reminders
from app.genshin_provider import Report
from app.errors import ReauthRequired
from tests.test_render_notes import sample
from tests.test_styles import FakeDb, _run

NOW = datetime(2026, 11, 2, tzinfo=timezone.utc)


def test_decide_fires_once_per_rise():
    assert reminders.decide(120, 200, 120, True) == (True, False)
    assert reminders.decide(150, 200, 120, False) == (False, False)  # already told
    assert reminders.decide(100, 200, 120, False) == (False, True)   # spent resin: re-arm
    assert reminders.decide(199, 200, 0, True) == (False, True)
    assert reminders.decide(200, 200, 0, True) == (True, False)
    assert reminders.decide(160, 160, 200, True) == (True, False)    # threshold above max acts as "full"


def test_options_roundtrip():
    for o in reminders.OPTIONS:
        assert reminders.to_option(reminders.to_threshold(o)) == o
    assert reminders.to_threshold("999") is None and reminders.to_threshold("x") is None


class RDb:
    def __init__(self, status="active"):
        self.status = status
        self.state = {}
        self.removed = False

    async def list_accounts(self, uid):
        return [{"id": "a", "is_default": True, "status": self.status}]

    async def update_reminder_state(self, uid, **f):
        self.state.update(f)

    async def set_reminder(self, uid, t):
        self.removed = t is None


class Prov:
    def __init__(self, resin, source="live", exc=None):
        n = sample()
        n.current_resin, n.max_resin, n.resin_recovery_seconds = resin, 200, 3600
        self.result, self.exc = Report(n, NOW, source), exc

    async def get_notes(self, account):
        if self.exc:
            raise self.exc
        return self.result


def _check(db, prov, row):
    sent = []

    async def send(uid, text):
        sent.append(text)

    asyncio.run(reminders.check_user(db, prov, send, row))
    return sent


def test_check_user_sends_and_disarms():
    db = RDb()
    sent = _check(db, Prov(130), {"user_id": 5, "resin_threshold": 120, "armed": True})
    assert len(sent) == 1 and "130/200" in sent[0] and db.state == {"armed": False}
    assert _check(RDb(), Prov(130), {"user_id": 5, "resin_threshold": 120, "armed": False}) == []
    db2 = RDb()
    assert _check(db2, Prov(40), {"user_id": 5, "resin_threshold": 120, "armed": False}) == [] and db2.state == {"armed": True}


def test_stale_and_errors_do_not_send():
    assert _check(RDb(), Prov(200, source="stale"), {"user_id": 5, "resin_threshold": 0, "armed": True}) == []
    assert _check(RDb(), Prov(200, exc=ReauthRequired()), {"user_id": 5, "resin_threshold": 0, "armed": True}) == []


def test_session_expired_warns_once():
    db = RDb(status="reauth_required")
    sent = _check(db, Prov(10), {"user_id": 5, "resin_threshold": 0, "armed": True, "session_warned": False})
    assert len(sent) == 1 and "/link" in sent[0] and db.state == {"session_warned": True}
    assert _check(RDb(status="reauth_required"), Prov(10), {"user_id": 5, "resin_threshold": 0, "session_warned": True}) == []


def test_menu_sets_reminder():
    class MDb(FakeDb):
        reminder = None

        async def get_reminder(self, uid):
            return None if self.reminder is None else {"resin_threshold": self.reminder}

        async def set_reminder(self, uid, t):
            self.reminder = t

    db = MDb()
    _run("st:rem:160", 5, db)
    assert db.reminder == 160
    _run("st:rem:full", 5, db)
    assert db.reminder == 0
    _run("st:rem:off", 5, db)
    assert db.reminder is None
    _run("st:rem:999", 5, db)
    assert db.reminder is None
