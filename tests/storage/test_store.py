import sqlite3
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


def test_initialize_migrates_legacy_single_user_schema(tmp_path):
    database_path = tmp_path / "state.sqlite3"
    with sqlite3.connect(database_path) as connection:
        connection.execute(
            """
            CREATE TABLE seen_emails (
                email_id TEXT PRIMARY KEY,
                thread_id TEXT NOT NULL,
                subject TEXT NOT NULL,
                sender TEXT NOT NULL,
                first_seen_at TEXT NOT NULL,
                telegram_message_id INTEGER
            )
            """
        )
        connection.execute(
            """
            CREATE TABLE pending_replies (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                email_id TEXT NOT NULL,
                thread_id TEXT NOT NULL,
                reply_text TEXT NOT NULL,
                status TEXT NOT NULL,
                created_at TEXT NOT NULL,
                expires_at TEXT NOT NULL,
                telegram_message_id INTEGER
            )
            """
        )
        connection.execute(
            """
            CREATE TABLE reply_audit_log (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                email_id TEXT NOT NULL,
                thread_id TEXT NOT NULL,
                recipient TEXT NOT NULL,
                subject TEXT NOT NULL,
                telegram_user_id INTEGER NOT NULL,
                telegram_action_id TEXT NOT NULL,
                sent_at TEXT NOT NULL
            )
            """
        )
        now = datetime(2026, 5, 19, 8, 0, tzinfo=UTC)
        connection.execute(
            """
            INSERT INTO seen_emails (
                email_id,
                thread_id,
                subject,
                sender,
                first_seen_at,
                telegram_message_id
            ) VALUES (?, ?, ?, ?, ?, ?)
            """,
            (
                "msg-legacy",
                "thread-legacy",
                "Legacy subject",
                "legacy@example.com",
                now.isoformat(),
                10,
            ),
        )
        connection.execute(
            """
            INSERT INTO pending_replies (
                email_id,
                thread_id,
                reply_text,
                status,
                created_at,
                expires_at,
                telegram_message_id
            ) VALUES (?, ?, ?, ?, ?, ?, ?)
            """,
            (
                "msg-legacy",
                "thread-legacy",
                "Legacy reply",
                "pending",
                now.isoformat(),
                (now + timedelta(days=1)).isoformat(),
                11,
            ),
        )
        connection.execute(
            """
            INSERT INTO reply_audit_log (
                email_id,
                thread_id,
                recipient,
                subject,
                telegram_user_id,
                telegram_action_id,
                sent_at
            ) VALUES (?, ?, ?, ?, ?, ?, ?)
            """,
            (
                "msg-legacy",
                "thread-legacy",
                "legacy@example.com",
                "Legacy subject",
                12345,
                "cb-legacy",
                now.isoformat(),
            ),
        )

    store = StateStore(database_path)
    store.initialize()

    with sqlite3.connect(database_path) as connection:
        connection.row_factory = sqlite3.Row
        user = connection.execute(
            "SELECT id FROM users WHERE telegram_user_id = 0 AND telegram_chat_id = 0"
        ).fetchone()
        assert user is not None
        default_user_id = int(user["id"])

        seen_row = connection.execute(
            "SELECT user_id FROM seen_emails WHERE email_id = ?",
            ("msg-legacy",),
        ).fetchone()
        assert seen_row is not None and int(seen_row["user_id"]) == default_user_id

        pending_row = connection.execute(
            "SELECT id, user_id FROM pending_replies WHERE email_id = ?",
            ("msg-legacy",),
        ).fetchone()
        assert pending_row is not None
        assert int(pending_row["user_id"]) == default_user_id

        audit_row = connection.execute(
            "SELECT user_id FROM reply_audit_log WHERE email_id = ?",
            ("msg-legacy",),
        ).fetchone()
        assert audit_row is not None and int(audit_row["user_id"]) == default_user_id

        schema_version = connection.execute("PRAGMA user_version").fetchone()[0]
        assert schema_version == 2

    assert store.has_seen_email("msg-legacy") is True
    assert store.get_pending_reply(1, now=now) is not None
