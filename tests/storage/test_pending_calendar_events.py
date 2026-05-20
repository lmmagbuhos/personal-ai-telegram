from datetime import datetime, timedelta, UTC

from personal_hermes.storage.store import StateStore


def _store(tmp_path):
    store = StateStore(str(tmp_path / "t.sqlite3"))
    store.initialize()
    return store


def _user(store):
    return store.upsert_user_from_telegram(
        telegram_user_id=1, telegram_chat_id=2,
        display_name=None, username=None, now=datetime.now(tz=UTC),
    ).id


def test_create_and_get_pending_event(tmp_path):
    store = _store(tmp_path)
    uid = _user(store)
    now = datetime.now(tz=UTC)
    pid = store.create_pending_calendar_event(
        user_id=uid, title="dentist",
        start_at=now + timedelta(hours=1), end_at=now + timedelta(hours=2),
        timezone="Asia/Manila", created_at=now, expires_at=now + timedelta(minutes=15),
        telegram_message_id=99,
    )
    pending = store.get_pending_calendar_event(pid, user_id=uid, now=now)
    assert pending is not None
    assert pending.title == "dentist"
    assert pending.status == "pending"


def test_expired_pending_event_returns_none(tmp_path):
    store = _store(tmp_path)
    uid = _user(store)
    past = datetime.now(tz=UTC) - timedelta(hours=1)
    pid = store.create_pending_calendar_event(
        user_id=uid, title="x", start_at=past, end_at=past,
        timezone="UTC", created_at=past, expires_at=past, telegram_message_id=None,
    )
    assert store.get_pending_calendar_event(pid, user_id=uid, now=datetime.now(tz=UTC)) is None


def test_mark_created_changes_status(tmp_path):
    store = _store(tmp_path)
    uid = _user(store)
    now = datetime.now(tz=UTC)
    pid = store.create_pending_calendar_event(
        user_id=uid, title="x", start_at=now, end_at=now, timezone="UTC",
        created_at=now, expires_at=now + timedelta(minutes=15), telegram_message_id=None,
    )
    assert store.mark_pending_calendar_event_created(pid) is True
    assert store.get_pending_calendar_event(pid, user_id=uid).status == "created"
