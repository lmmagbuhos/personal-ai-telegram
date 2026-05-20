from datetime import date, datetime, UTC
from zoneinfo import ZoneInfo

from personal_hermes.calendar.edit import CalendarEditService
from personal_hermes.storage.store import StateStore
from personal_hermes.openclaw.types import CalendarEvent
from personal_hermes.telegram.types import TelegramMessage, TelegramCallback

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


def _start_cancel(tmp_path):
    store = _store(tmp_path); uid = _uid(store)
    tg = FakeTelegram()
    client = FakeClient([_event("e1","Standup",9), _event("e2","Review",14)])
    svc = CalendarEditService(openclaw_client=client, telegram=tg, store=store,
        resolve_access_token=lambda user_id, *, now: "tok", timezone=TZ)
    msg = TelegramMessage(chat_id=2, user_id=1, message_id=5, text="cancel an event today")
    svc.start(msg, operation="cancel", user_id=uid, now=datetime.now(tz=UTC), today=date(2026,5,20))
    return store, uid, tg, client, svc

def test_pick_then_confirm_deletes_event(tmp_path):
    store, uid, tg, client, svc = _start_cancel(tmp_path)
    now = datetime.now(tz=UTC)
    svc.handle_callback(TelegramCallback(chat_id=2,user_id=1,message_id=5,callback_query_id="q",data="cal_pick:1"), user_id=uid, now=now)
    assert any("Review" in t for t in (tg.edits + [m["text"] for m in tg.messages]))
    svc.handle_callback(TelegramCallback(chat_id=2,user_id=1,message_id=5,callback_query_id="q",data="cal_del_ok"), user_id=uid, now=now)
    assert client.deleted == ["e2"]
    assert store.get_conversation_state(2, user_id=uid) is None

def test_pick_then_cancel_does_not_delete(tmp_path):
    store, uid, tg, client, svc = _start_cancel(tmp_path)
    now = datetime.now(tz=UTC)
    svc.handle_callback(TelegramCallback(chat_id=2,user_id=1,message_id=5,callback_query_id="q",data="cal_pick:0"), user_id=uid, now=now)
    svc.handle_callback(TelegramCallback(chat_id=2,user_id=1,message_id=5,callback_query_id="q",data="cal_del_no"), user_id=uid, now=now)
    assert client.deleted == []
    assert store.get_conversation_state(2, user_id=uid) is None

def test_confirm_without_session_is_expired(tmp_path):
    store = _store(tmp_path); uid = _uid(store)
    tg = FakeTelegram()
    svc = CalendarEditService(openclaw_client=FakeClient([]), telegram=tg, store=store,
        resolve_access_token=lambda user_id, *, now: "tok", timezone=TZ)
    svc.handle_callback(TelegramCallback(chat_id=2,user_id=1,message_id=5,callback_query_id="q",data="cal_del_ok"), user_id=uid, now=datetime.now(tz=UTC))
    assert any("expired" in (t or "").lower() for t in tg.answers)


def _start_edit(tmp_path):
    store = _store(tmp_path); uid = _uid(store)
    tg = FakeTelegram()
    client = FakeClient([_event("e1","Standup",9), _event("e2","Review",14)])
    svc = CalendarEditService(openclaw_client=client, telegram=tg, store=store,
        resolve_access_token=lambda user_id, *, now: "tok", timezone=TZ)
    msg = TelegramMessage(chat_id=2, user_id=1, message_id=5, text="edit an event today")
    svc.start(msg, operation="edit", user_id=uid, now=datetime.now(tz=UTC), today=date(2026,5,20))
    return store, uid, tg, client, svc

def test_edit_pick_shows_field_buttons(tmp_path):
    store, uid, tg, client, svc = _start_edit(tmp_path)
    now = datetime.now(tz=UTC)
    svc.handle_callback(TelegramCallback(chat_id=2,user_id=1,message_id=5,callback_query_id="q",data="cal_pick:1"), user_id=uid, now=now)
    flat = [b for m in tg.messages for row in (m["buttons"] or []) for b in row]
    cbs = [cb for _label, cb in flat]
    assert "cal_field:time" in cbs and "cal_field:title" in cbs
    assert "cal_field:location" in cbs and "cal_field:description" in cbs
    state = store.get_conversation_state(2, user_id=uid)
    assert state.state == "cal_choose_field"
    assert state.payload["event"]["id"] == "e2"

def test_edit_choose_field_prompts_for_value(tmp_path):
    store, uid, tg, client, svc = _start_edit(tmp_path)
    now = datetime.now(tz=UTC)
    svc.handle_callback(TelegramCallback(chat_id=2,user_id=1,message_id=5,callback_query_id="q",data="cal_pick:0"), user_id=uid, now=now)
    svc.handle_callback(TelegramCallback(chat_id=2,user_id=1,message_id=5,callback_query_id="q",data="cal_field:title"), user_id=uid, now=now)
    state = store.get_conversation_state(2, user_id=uid)
    assert state.state == "cal_edit_value"
    assert state.payload["field"] == "title"
    assert any("new title" in m["text"].lower() for m in tg.messages)


def _to_value_step(tmp_path, field):
    store, uid, tg, client, svc = _start_edit(tmp_path)
    now = datetime.now(tz=UTC)
    svc.handle_callback(TelegramCallback(chat_id=2,user_id=1,message_id=5,callback_query_id="q",data="cal_pick:1"), user_id=uid, now=now)  # picks "Review" (e2, 14:00-14:30 on 2026-05-20)
    svc.handle_callback(TelegramCallback(chat_id=2,user_id=1,message_id=5,callback_query_id="q",data=f"cal_field:{field}"), user_id=uid, now=now)
    return store, uid, tg, client, svc


def test_handle_value_title_sets_confirm(tmp_path):
    store, uid, tg, client, svc = _to_value_step(tmp_path, "title")
    now = datetime.now(tz=UTC)
    handled = svc.handle_value(TelegramMessage(chat_id=2,user_id=1,message_id=6,text="Sprint review"), user_id=uid, now=now)
    assert handled is True
    state = store.get_conversation_state(2, user_id=uid)
    assert state.state == "cal_confirm_edit"
    assert state.payload["new_value"] == {"text": "Sprint review"}
    assert any("Sprint review" in m["text"] for m in tg.messages)
    flat = [cb for m in tg.messages for row in (m["buttons"] or []) for _l, cb in row]
    assert "cal_edit_ok" in flat and "cal_edit_no" in flat


def test_handle_value_time_parses_range(tmp_path):
    store, uid, tg, client, svc = _to_value_step(tmp_path, "time")
    now = datetime.now(tz=UTC)
    svc.handle_value(TelegramMessage(chat_id=2,user_id=1,message_id=6,text="4-4:30pm"), user_id=uid, now=now)
    state = store.get_conversation_state(2, user_id=uid)
    assert state.state == "cal_confirm_edit"
    nv = state.payload["new_value"]
    assert nv["start"].startswith("2026-05-20T16:00:00")
    assert nv["end"].startswith("2026-05-20T16:30:00")


def test_handle_value_unparseable_time_stays(tmp_path):
    store, uid, tg, client, svc = _to_value_step(tmp_path, "time")
    now = datetime.now(tz=UTC)
    svc.handle_value(TelegramMessage(chat_id=2,user_id=1,message_id=6,text="sometime later"), user_id=uid, now=now)
    state = store.get_conversation_state(2, user_id=uid)
    assert state.state == "cal_edit_value"
    assert any("couldn't read" in m["text"].lower() for m in tg.messages)
