from datetime import UTC, date, datetime, timedelta

from personal_hermes.storage.store import StateStore


def test_seen_email_tracking_is_idempotent(tmp_path):
    store = StateStore(tmp_path / "state.sqlite3")
    store.initialize()

    first_seen = store.mark_email_seen(
        email_id="msg-1",
        thread_id="thread-1",
        subject="Subject",
        sender="sender@example.com",
        telegram_message_id=123,
        first_seen_at=datetime(2026, 5, 19, 8, 0, tzinfo=UTC),
    )
    second_seen = store.mark_email_seen(
        email_id="msg-1",
        thread_id="thread-1",
        subject="Changed",
        sender="changed@example.com",
        telegram_message_id=456,
        first_seen_at=datetime(2026, 5, 19, 9, 0, tzinfo=UTC),
    )

    assert first_seen is True
    assert second_seen is False
    assert store.has_seen_email("msg-1") is True
    assert store.has_seen_email("missing") is False


def test_pending_reply_lifecycle_and_expiry(tmp_path):
    store = StateStore(tmp_path / "state.sqlite3")
    store.initialize()
    now = datetime(2026, 5, 19, 8, 0, tzinfo=UTC)

    reply_id = store.create_pending_reply(
        email_id="msg-1",
        thread_id="thread-1",
        reply_text="Suggested reply",
        created_at=now,
        expires_at=now + timedelta(days=7),
        telegram_message_id=123,
    )

    pending = store.get_pending_reply(reply_id, now=now)
    assert pending is not None
    assert pending.status == "pending"
    assert pending.reply_text == "Suggested reply"

    store.update_pending_reply_text(reply_id, "Edited reply")
    edited = store.get_pending_reply(reply_id, now=now)
    assert edited is not None
    assert edited.reply_text == "Edited reply"

    assert store.mark_pending_reply_sent(reply_id, sent_at=now) is True
    assert store.mark_pending_reply_sent(reply_id, sent_at=now) is False
    sent = store.get_pending_reply(reply_id, now=now)
    assert sent is not None
    assert sent.status == "sent"


def test_expired_pending_reply_cannot_be_loaded_as_sendable(tmp_path):
    store = StateStore(tmp_path / "state.sqlite3")
    store.initialize()
    now = datetime(2026, 5, 19, 8, 0, tzinfo=UTC)

    reply_id = store.create_pending_reply(
        email_id="msg-1",
        thread_id="thread-1",
        reply_text="Suggested reply",
        created_at=now - timedelta(days=8),
        expires_at=now - timedelta(days=1),
        telegram_message_id=123,
    )

    assert store.get_pending_reply(reply_id, now=now) is None
    row = store.get_pending_reply(reply_id)
    assert row is not None
    assert row.status == "expired"


def test_reply_audit_log_records_sent_reply_metadata(tmp_path):
    store = StateStore(tmp_path / "state.sqlite3")
    store.initialize()
    sent_at = datetime(2026, 5, 19, 8, 0, tzinfo=UTC)

    audit_id = store.record_reply_audit(
        email_id="msg-1",
        thread_id="thread-1",
        recipient="sender@example.com",
        subject="Subject",
        telegram_user_id=789,
        telegram_action_id="cb-1",
        sent_at=sent_at,
    )

    assert audit_id > 0
    assert store.count_reply_audits() == 1


def test_calendar_agenda_and_reminder_deduplication(tmp_path):
    store = StateStore(tmp_path / "state.sqlite3")
    store.initialize()
    sent_at = datetime(2026, 5, 19, 8, 0, tzinfo=UTC)
    event_start = datetime(2026, 5, 19, 9, 30, tzinfo=UTC)

    assert store.mark_agenda_sent(date(2026, 5, 19), sent_at=sent_at) is True
    assert store.mark_agenda_sent(date(2026, 5, 19), sent_at=sent_at) is False

    assert store.mark_calendar_reminder_sent(
        event_id="event-1",
        event_start_at=event_start,
        sent_at=sent_at,
    ) is True
    assert store.mark_calendar_reminder_sent(
        event_id="event-1",
        event_start_at=event_start,
        sent_at=sent_at,
    ) is False
    assert store.mark_calendar_reminder_sent(
        event_id="event-1",
        event_start_at=event_start + timedelta(hours=1),
        sent_at=sent_at,
    ) is True


def test_conversation_state_round_trip_and_clear(tmp_path):
    store = StateStore(tmp_path / "state.sqlite3")
    store.initialize()
    updated_at = datetime(2026, 5, 19, 8, 0, tzinfo=UTC)

    store.set_conversation_state(
        telegram_chat_id=123,
        state="editing_reply",
        payload={"pending_reply_id": 9},
        updated_at=updated_at,
    )

    state = store.get_conversation_state(123)
    assert state is not None
    assert state.state == "editing_reply"
    assert state.payload == {"pending_reply_id": 9}

    store.clear_conversation_state(123)
    assert store.get_conversation_state(123) is None

