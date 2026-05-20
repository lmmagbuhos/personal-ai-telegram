from datetime import date, datetime, UTC
from zoneinfo import ZoneInfo

from personal_hermes.calendar.edit import CalendarEditService
from personal_hermes.storage.store import StateStore
from personal_hermes.openclaw.types import CalendarEvent
from personal_hermes.telegram.types import TelegramMessage

TZ = ZoneInfo("Asia/Manila")


class FakeTelegram:
    def __init__(self):
        self.messages = []
        self.edits = []
        self.answers = []
    def send_message(self, *, chat_id, text, buttons=None):
        self.messages.append({"text": text, "buttons": buttons})
        return 1
    def edit_message(self, *, chat_id, message_id, text):
        self.edits.append(text)
    def answer_callback(self, *, callback_query_id, text=None):
        self.answers.append(text)


class FakeClient:
    def __init__(self, events):
        self._events = events
        self.deleted = []
    def with_access_token(self, token):
        return self
    def list_calendar_events(self, start_at, end_at):
        return self._events
    def delete_calendar_event(self, *, event_id):
        self.deleted.append(event_id)


def _store(tmp_path):
    s = StateStore(str(tmp_path / "t.sqlite3")); s.initialize(); return s

def _uid(store):
    return store.upsert_user_from_telegram(
        telegram_user_id=1, telegram_chat_id=2, display_name=None,
        username=None, now=datetime.now(tz=UTC)).id

def _event(eid, title, h):
    return CalendarEvent(id=eid, title=title, all_day=False,
        start_at=datetime(2026,5,20,h,0,tzinfo=TZ), end_at=datetime(2026,5,20,h,30,tzinfo=TZ))


def test_start_cancel_lists_events_as_buttons(tmp_path):
    store = _store(tmp_path); uid = _uid(store)
    tg = FakeTelegram()
    client = FakeClient([_event("e1","Standup",9), _event("e2","Review",14)])
    svc = CalendarEditService(openclaw_client=client, telegram=tg, store=store,
        resolve_access_token=lambda user_id, *, now: "tok", timezone=TZ)
    msg = TelegramMessage(chat_id=2, user_id=1, message_id=5, text="cancel an event today")
    handled = svc.start(msg, operation="cancel", user_id=uid, now=datetime.now(tz=UTC), today=date(2026,5,20))
    assert handled is True
    assert tg.messages
    buttons = tg.messages[0]["buttons"]
    flat = [b for row in buttons for b in row]
    assert any(cb.startswith("cal_pick:") for _label, cb in flat)
    assert any("Standup" in label for label, _cb in flat)
    state = store.get_conversation_state(2, user_id=uid)
    assert state.state == "cal_select"
    assert state.payload["op"] == "cancel"
    assert len(state.payload["candidates"]) == 2


def test_start_cancel_no_events(tmp_path):
    store = _store(tmp_path); uid = _uid(store)
    tg = FakeTelegram()
    svc = CalendarEditService(openclaw_client=FakeClient([]), telegram=tg, store=store,
        resolve_access_token=lambda user_id, *, now: "tok", timezone=TZ)
    msg = TelegramMessage(chat_id=2, user_id=1, message_id=5, text="cancel an event today")
    handled = svc.start(msg, operation="cancel", user_id=uid, now=datetime.now(tz=UTC), today=date(2026,5,20))
    assert handled is True
    assert "No events" in tg.messages[0]["text"]
    assert store.get_conversation_state(2, user_id=uid) is None
