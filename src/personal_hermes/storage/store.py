import json
import sqlite3
from dataclasses import dataclass
from datetime import date, datetime
from importlib import resources
from pathlib import Path
from typing import Any


@dataclass(frozen=True)
class PendingReply:
    id: int
    email_id: str
    thread_id: str
    reply_text: str
    status: str
    created_at: datetime
    expires_at: datetime
    telegram_message_id: int | None


@dataclass(frozen=True)
class ConversationState:
    telegram_chat_id: int
    state: str
    payload: dict[str, Any]
    updated_at: datetime


class StateStore:
    def __init__(self, database_path: str | Path) -> None:
        self.database_path = Path(database_path)

    def initialize(self) -> None:
        self.database_path.parent.mkdir(parents=True, exist_ok=True)
        schema = resources.files("personal_hermes.storage").joinpath("schema.sql")
        with self._connect() as connection:
            connection.executescript(schema.read_text(encoding="utf-8"))

    def mark_email_seen(
        self,
        *,
        email_id: str,
        thread_id: str,
        subject: str,
        sender: str,
        telegram_message_id: int | None,
        first_seen_at: datetime,
    ) -> bool:
        with self._connect() as connection:
            cursor = connection.execute(
                """
                INSERT OR IGNORE INTO seen_emails (
                    email_id,
                    thread_id,
                    subject,
                    sender,
                    first_seen_at,
                    telegram_message_id
                )
                VALUES (?, ?, ?, ?, ?, ?)
                """,
                (
                    email_id,
                    thread_id,
                    subject,
                    sender,
                    self._datetime_to_text(first_seen_at),
                    telegram_message_id,
                ),
            )
            return cursor.rowcount == 1

    def has_seen_email(self, email_id: str) -> bool:
        with self._connect() as connection:
            row = connection.execute(
                "SELECT 1 FROM seen_emails WHERE email_id = ?",
                (email_id,),
            ).fetchone()
        return row is not None

    def create_pending_reply(
        self,
        *,
        email_id: str,
        thread_id: str,
        reply_text: str,
        created_at: datetime,
        expires_at: datetime,
        telegram_message_id: int | None,
    ) -> int:
        with self._connect() as connection:
            cursor = connection.execute(
                """
                INSERT INTO pending_replies (
                    email_id,
                    thread_id,
                    reply_text,
                    status,
                    created_at,
                    expires_at,
                    telegram_message_id
                )
                VALUES (?, ?, ?, 'pending', ?, ?, ?)
                """,
                (
                    email_id,
                    thread_id,
                    reply_text,
                    self._datetime_to_text(created_at),
                    self._datetime_to_text(expires_at),
                    telegram_message_id,
                ),
            )
            return int(cursor.lastrowid)

    def get_pending_reply(
        self,
        pending_reply_id: int,
        *,
        now: datetime | None = None,
    ) -> PendingReply | None:
        if now is not None:
            self.expire_pending_replies(now)

        with self._connect() as connection:
            row = connection.execute(
                "SELECT * FROM pending_replies WHERE id = ?",
                (pending_reply_id,),
            ).fetchone()

        if row is None:
            return None
        reply = self._pending_reply_from_row(row)
        if now is not None and reply.status == "expired":
            return None
        return reply

    def update_pending_reply_text(self, pending_reply_id: int, reply_text: str) -> bool:
        with self._connect() as connection:
            cursor = connection.execute(
                """
                UPDATE pending_replies
                SET reply_text = ?
                WHERE id = ? AND status = 'pending'
                """,
                (reply_text, pending_reply_id),
            )
            return cursor.rowcount == 1

    def mark_pending_reply_sent(self, pending_reply_id: int, *, sent_at: datetime) -> bool:
        del sent_at
        return self._update_pending_reply_status(pending_reply_id, "sent")

    def mark_pending_reply_failed(self, pending_reply_id: int) -> bool:
        return self._update_pending_reply_status(pending_reply_id, "failed")

    def mark_pending_reply_ignored(self, pending_reply_id: int) -> bool:
        return self._update_pending_reply_status(pending_reply_id, "ignored")

    def expire_pending_replies(self, now: datetime) -> int:
        with self._connect() as connection:
            cursor = connection.execute(
                """
                UPDATE pending_replies
                SET status = 'expired'
                WHERE status = 'pending' AND expires_at <= ?
                """,
                (self._datetime_to_text(now),),
            )
            return cursor.rowcount

    def record_reply_audit(
        self,
        *,
        email_id: str,
        thread_id: str,
        recipient: str,
        subject: str,
        telegram_user_id: int,
        telegram_action_id: str,
        sent_at: datetime,
    ) -> int:
        with self._connect() as connection:
            cursor = connection.execute(
                """
                INSERT INTO reply_audit_log (
                    email_id,
                    thread_id,
                    recipient,
                    subject,
                    telegram_user_id,
                    telegram_action_id,
                    sent_at
                )
                VALUES (?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    email_id,
                    thread_id,
                    recipient,
                    subject,
                    telegram_user_id,
                    telegram_action_id,
                    self._datetime_to_text(sent_at),
                ),
            )
            return int(cursor.lastrowid)

    def count_reply_audits(self) -> int:
        with self._connect() as connection:
            row = connection.execute("SELECT COUNT(*) AS count FROM reply_audit_log").fetchone()
        return int(row["count"])

    def mark_agenda_sent(self, agenda_date: date, *, sent_at: datetime) -> bool:
        with self._connect() as connection:
            cursor = connection.execute(
                """
                INSERT OR IGNORE INTO calendar_agenda_notifications (
                    agenda_date,
                    sent_at
                )
                VALUES (?, ?)
                """,
                (agenda_date.isoformat(), self._datetime_to_text(sent_at)),
            )
            return cursor.rowcount == 1

    def mark_calendar_reminder_sent(
        self,
        *,
        event_id: str,
        event_start_at: datetime,
        sent_at: datetime,
    ) -> bool:
        with self._connect() as connection:
            cursor = connection.execute(
                """
                INSERT OR IGNORE INTO calendar_reminders (
                    event_id,
                    event_start_at,
                    sent_at
                )
                VALUES (?, ?, ?)
                """,
                (
                    event_id,
                    self._datetime_to_text(event_start_at),
                    self._datetime_to_text(sent_at),
                ),
            )
            return cursor.rowcount == 1

    def set_conversation_state(
        self,
        *,
        telegram_chat_id: int,
        state: str,
        payload: dict[str, Any],
        updated_at: datetime,
    ) -> None:
        with self._connect() as connection:
            connection.execute(
                """
                INSERT INTO conversation_state (
                    telegram_chat_id,
                    state,
                    payload_json,
                    updated_at
                )
                VALUES (?, ?, ?, ?)
                ON CONFLICT(telegram_chat_id) DO UPDATE SET
                    state = excluded.state,
                    payload_json = excluded.payload_json,
                    updated_at = excluded.updated_at
                """,
                (
                    telegram_chat_id,
                    state,
                    json.dumps(payload),
                    self._datetime_to_text(updated_at),
                ),
            )

    def get_conversation_state(self, telegram_chat_id: int) -> ConversationState | None:
        with self._connect() as connection:
            row = connection.execute(
                "SELECT * FROM conversation_state WHERE telegram_chat_id = ?",
                (telegram_chat_id,),
            ).fetchone()

        if row is None:
            return None
        return ConversationState(
            telegram_chat_id=int(row["telegram_chat_id"]),
            state=str(row["state"]),
            payload=json.loads(str(row["payload_json"])),
            updated_at=self._text_to_datetime(str(row["updated_at"])),
        )

    def clear_conversation_state(self, telegram_chat_id: int) -> None:
        with self._connect() as connection:
            connection.execute(
                "DELETE FROM conversation_state WHERE telegram_chat_id = ?",
                (telegram_chat_id,),
            )

    def _update_pending_reply_status(
        self, pending_reply_id: int, status: str
    ) -> bool:
        with self._connect() as connection:
            cursor = connection.execute(
                """
                UPDATE pending_replies
                SET status = ?
                WHERE id = ? AND status = 'pending'
                """,
                (status, pending_reply_id),
            )
            return cursor.rowcount == 1

    def _connect(self) -> sqlite3.Connection:
        connection = sqlite3.connect(self.database_path)
        connection.row_factory = sqlite3.Row
        return connection

    @staticmethod
    def _pending_reply_from_row(row: sqlite3.Row) -> PendingReply:
        return PendingReply(
            id=int(row["id"]),
            email_id=str(row["email_id"]),
            thread_id=str(row["thread_id"]),
            reply_text=str(row["reply_text"]),
            status=str(row["status"]),
            created_at=StateStore._text_to_datetime(str(row["created_at"])),
            expires_at=StateStore._text_to_datetime(str(row["expires_at"])),
            telegram_message_id=row["telegram_message_id"],
        )

    @staticmethod
    def _datetime_to_text(value: datetime) -> str:
        return value.isoformat()

    @staticmethod
    def _text_to_datetime(value: str) -> datetime:
        return datetime.fromisoformat(value)
