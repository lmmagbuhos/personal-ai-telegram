import json
import sqlite3
from dataclasses import dataclass
from datetime import date, datetime
from importlib import resources
from pathlib import Path
from typing import Any

from personal_hermes.users import GoogleAccount, OAuthSession, User


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

    def upsert_user_from_telegram(
        self,
        *,
        telegram_user_id: int,
        telegram_chat_id: int,
        display_name: str | None,
        username: str | None,
        now: datetime,
    ) -> User:
        timestamp = self._datetime_to_text(now)
        with self._connect() as connection:
            connection.execute(
                """
                INSERT INTO users (
                    telegram_user_id,
                    telegram_chat_id,
                    display_name,
                    username,
                    status,
                    created_at,
                    updated_at
                )
                VALUES (?, ?, ?, ?, 'pending', ?, ?)
                ON CONFLICT(telegram_user_id, telegram_chat_id) DO UPDATE SET
                    telegram_chat_id = excluded.telegram_chat_id,
                    display_name = excluded.display_name,
                    username = excluded.username,
                    updated_at = excluded.updated_at
                """,
                (
                    telegram_user_id,
                    telegram_chat_id,
                    display_name,
                    username,
                    timestamp,
                    timestamp,
                ),
            )
            row = connection.execute(
                """
                SELECT *
                FROM users
                WHERE telegram_user_id = ? AND telegram_chat_id = ?
                """,
                (telegram_user_id, telegram_chat_id),
            ).fetchone()

        if row is None:
            raise RuntimeError("User upsert did not return a row")
        return self._user_from_row(row)

    def get_user_by_telegram(
        self,
        *,
        telegram_user_id: int,
        telegram_chat_id: int,
    ) -> User | None:
        with self._connect() as connection:
            row = connection.execute(
                """
                SELECT *
                FROM users
                WHERE telegram_user_id = ? AND telegram_chat_id = ?
                """,
                (telegram_user_id, telegram_chat_id),
            ).fetchone()

        if row is None:
            return None
        return self._user_from_row(row)

    def activate_user(self, user_id: int, now: datetime) -> bool:
        with self._connect() as connection:
            cursor = connection.execute(
                """
                UPDATE users
                SET status = 'active',
                    updated_at = ?
                WHERE id = ?
                """,
                (self._datetime_to_text(now), user_id),
            )
            return cursor.rowcount == 1

    def list_active_google_users(self) -> list[User]:
        with self._connect() as connection:
            rows = connection.execute(
                """
                SELECT users.*
                FROM users
                INNER JOIN google_accounts ON google_accounts.user_id = users.id
                WHERE users.status = 'active'
                    AND google_accounts.status = 'active'
                ORDER BY users.id
                """
            ).fetchall()
        return [self._user_from_row(row) for row in rows]

    def create_oauth_session(
        self,
        *,
        state: str,
        telegram_user_id: int,
        telegram_chat_id: int,
        expires_at: datetime,
        created_at: datetime,
    ) -> None:
        with self._connect() as connection:
            connection.execute(
                """
                INSERT INTO oauth_sessions (
                    state,
                    telegram_user_id,
                    telegram_chat_id,
                    expires_at,
                    created_at
                )
                VALUES (?, ?, ?, ?, ?)
                """,
                (
                    state,
                    telegram_user_id,
                    telegram_chat_id,
                    self._datetime_to_text(expires_at),
                    self._datetime_to_text(created_at),
                ),
            )

    def consume_oauth_session(
        self,
        state: str,
        now: datetime,
    ) -> OAuthSession | None:
        timestamp = self._datetime_to_text(now)
        with self._connect() as connection:
            connection.execute("BEGIN IMMEDIATE")
            row = connection.execute(
                "SELECT * FROM oauth_sessions WHERE state = ?",
                (state,),
            ).fetchone()
            if row is None:
                return None

            session = self._oauth_session_from_row(row)
            if session.used_at is not None or session.expires_at <= now:
                return None

            connection.execute(
                """
                UPDATE oauth_sessions
                SET used_at = ?
                WHERE state = ?
                """,
                (timestamp, state),
            )

        return OAuthSession(
            state=session.state,
            telegram_user_id=session.telegram_user_id,
            telegram_chat_id=session.telegram_chat_id,
            expires_at=session.expires_at,
            used_at=now,
            created_at=session.created_at,
        )

    def save_google_account(
        self,
        *,
        user_id: int,
        google_subject: str,
        google_email: str,
        encrypted_access_token: str,
        encrypted_refresh_token: str,
        granted_scopes: tuple[str, ...],
        token_expires_at: datetime | None,
        now: datetime,
    ) -> None:
        with self._connect() as connection:
            connection.execute(
                """
                INSERT INTO google_accounts (
                    user_id,
                    google_subject,
                    google_email,
                    encrypted_access_token,
                    encrypted_refresh_token,
                    granted_scopes,
                    token_expires_at,
                    status,
                    created_at,
                    updated_at
                )
                VALUES (?, ?, ?, ?, ?, ?, ?, 'active', ?, ?)
                ON CONFLICT(user_id) DO UPDATE SET
                    google_subject = excluded.google_subject,
                    google_email = excluded.google_email,
                    encrypted_access_token = excluded.encrypted_access_token,
                    encrypted_refresh_token = excluded.encrypted_refresh_token,
                    granted_scopes = excluded.granted_scopes,
                    token_expires_at = excluded.token_expires_at,
                    status = 'active',
                    updated_at = excluded.updated_at
                """,
                (
                    user_id,
                    google_subject,
                    google_email,
                    encrypted_access_token,
                    encrypted_refresh_token,
                    json.dumps(list(granted_scopes)),
                    self._optional_datetime_to_text(token_expires_at),
                    self._datetime_to_text(now),
                    self._datetime_to_text(now),
                ),
            )

    def get_google_account(self, user_id: int) -> GoogleAccount | None:
        with self._connect() as connection:
            row = connection.execute(
                "SELECT * FROM google_accounts WHERE user_id = ?",
                (user_id,),
            ).fetchone()

        if row is None:
            return None
        return self._google_account_from_row(row)

    def mark_google_account_status(
        self,
        user_id: int,
        status: str,
        now: datetime,
    ) -> bool:
        with self._connect() as connection:
            cursor = connection.execute(
                """
                UPDATE google_accounts
                SET status = ?,
                    updated_at = ?
                WHERE user_id = ?
                """,
                (status, self._datetime_to_text(now), user_id),
            )
            return cursor.rowcount == 1

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
    def _user_from_row(row: sqlite3.Row) -> User:
        return User(
            id=int(row["id"]),
            telegram_user_id=int(row["telegram_user_id"]),
            telegram_chat_id=int(row["telegram_chat_id"]),
            display_name=row["display_name"],
            username=row["username"],
            status=str(row["status"]),
            created_at=StateStore._text_to_datetime(str(row["created_at"])),
            updated_at=StateStore._text_to_datetime(str(row["updated_at"])),
        )

    @staticmethod
    def _oauth_session_from_row(row: sqlite3.Row) -> OAuthSession:
        used_at = row["used_at"]
        return OAuthSession(
            state=str(row["state"]),
            telegram_user_id=int(row["telegram_user_id"]),
            telegram_chat_id=int(row["telegram_chat_id"]),
            expires_at=StateStore._text_to_datetime(str(row["expires_at"])),
            used_at=StateStore._optional_text_to_datetime(used_at),
            created_at=StateStore._text_to_datetime(str(row["created_at"])),
        )

    @staticmethod
    def _google_account_from_row(row: sqlite3.Row) -> GoogleAccount:
        token_expires_at = row["token_expires_at"]
        return GoogleAccount(
            user_id=int(row["user_id"]),
            google_subject=str(row["google_subject"]),
            google_email=str(row["google_email"]),
            encrypted_access_token=str(row["encrypted_access_token"]),
            encrypted_refresh_token=str(row["encrypted_refresh_token"]),
            granted_scopes=tuple(json.loads(str(row["granted_scopes"]))),
            token_expires_at=StateStore._optional_text_to_datetime(token_expires_at),
            status=str(row["status"]),
            created_at=StateStore._text_to_datetime(str(row["created_at"])),
            updated_at=StateStore._text_to_datetime(str(row["updated_at"])),
        )

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
    def _optional_datetime_to_text(value: datetime | None) -> str | None:
        if value is None:
            return None
        return StateStore._datetime_to_text(value)

    @staticmethod
    def _text_to_datetime(value: str) -> datetime:
        return datetime.fromisoformat(value)

    @staticmethod
    def _optional_text_to_datetime(value: Any) -> datetime | None:
        if value is None:
            return None
        return StateStore._text_to_datetime(str(value))
