from datetime import datetime, timedelta, UTC
from zoneinfo import ZoneInfo

from personal_hermes.calendar.actions import CalendarActionService
from personal_hermes.calendar.event_request import EventDraft
from personal_hermes.storage.store import StateStore
from personal_hermes.telegram.types import TelegramCallback

TZ = ZoneInfo("Asia/Manila")


class FakeTelegram:
    def __init__(self):
        self.edits = []
        self.answers = []
    def is_authorized(self, event):
        return True
    def edit_message(self, *, chat_id, message_id, text):
        self.edits.append(text)
    def answer_callback(self, *, callback_query_id, text=None):
        self.answers.append(text)


class FakeTelegramUnauthorized(FakeTelegram):
    def is_authorized(self, event):
        return False


class FakeClient:
    def __init__(self):
        self.created = []
    def with_access_token(self, token):
        return self
    def create_calendar_event(self, *, title, start_at, end_at, timezone):
        self.created.append((title, start_at, end_at, timezone))
        class E: id = "evt1"
        return E()


def _store(tmp_path):
    store = StateStore(str(tmp_path / "t.sqlite3")); store.initialize()
    return store


def _uid(store):
    return store.upsert_user_from_telegram(
        telegram_user_id=1, telegram_chat_id=2, display_name=None,
        username=None, now=datetime.now(tz=UTC)).id


def test_confirm_creates_event_and_marks_created(tmp_path):
    store = _store(tmp_path); uid = _uid(store)
    tg = FakeTelegram(); client = FakeClient()
    svc = CalendarActionService(
        openclaw_client=client, telegram=tg, store=store,
        resolve_access_token=lambda user_id, *, now: "tok",
    )
    now = datetime.now(tz=UTC)
    draft = EventDraft(title="dentist",
                       start_at=datetime(2026, 5, 20, 9, 0, tzinfo=TZ),
                       end_at=datetime(2026, 5, 20, 9, 30, tzinfo=TZ))
    pid = svc.prepare_event(user_id=uid, draft=draft, telegram_message_id=5, now=now)

    cb = TelegramCallback(chat_id=2, user_id=1, message_id=5,
                          callback_query_id="q", data=f"cal_confirm:{pid}")
    svc.handle_callback(cb, user_id=uid, now=now)

    assert client.created and client.created[0][0] == "dentist"
    assert client.created[0][3] == "Asia/Manila"
    assert store.get_pending_calendar_event(pid, user_id=uid).status == "created"
    assert any("Created" in e for e in tg.edits)


def test_cancel_marks_cancelled_and_does_not_create(tmp_path):
    store = _store(tmp_path); uid = _uid(store)
    tg = FakeTelegram(); client = FakeClient()
    svc = CalendarActionService(
        openclaw_client=client, telegram=tg, store=store,
        resolve_access_token=lambda user_id, *, now: "tok",
    )
    now = datetime.now(tz=UTC)
    draft = EventDraft(title="x",
                       start_at=datetime(2026, 5, 20, 9, 0, tzinfo=TZ),
                       end_at=datetime(2026, 5, 20, 9, 30, tzinfo=TZ))
    pid = svc.prepare_event(user_id=uid, draft=draft, telegram_message_id=5, now=now)
    cb = TelegramCallback(chat_id=2, user_id=1, message_id=5,
                          callback_query_id="q", data=f"cal_cancel:{pid}")
    svc.handle_callback(cb, user_id=uid, now=now)

    assert client.created == []
    assert store.get_pending_calendar_event(pid, user_id=uid).status == "cancelled"


def test_confirm_works_in_multiuser_when_single_user_auth_is_unset(tmp_path):
    store = _store(tmp_path); uid = _uid(store)
    tg = FakeTelegramUnauthorized(); client = FakeClient()
    svc = CalendarActionService(
        openclaw_client=client, telegram=tg, store=store,
        resolve_access_token=lambda user_id, *, now: "tok",
    )
    now = datetime.now(tz=UTC)
    draft = EventDraft(title="dentist",
                       start_at=datetime(2026, 5, 20, 9, 0, tzinfo=TZ),
                       end_at=datetime(2026, 5, 20, 9, 30, tzinfo=TZ))
    pid = svc.prepare_event(user_id=uid, draft=draft, telegram_message_id=5, now=now)
    cb = TelegramCallback(chat_id=2, user_id=1, message_id=5,
                          callback_query_id="q", data=f"cal_confirm:{pid}")
    svc.handle_callback(cb, user_id=uid, now=now)
    assert client.created and client.created[0][0] == "dentist"
