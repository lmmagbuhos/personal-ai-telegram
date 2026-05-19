from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
from typing import Protocol

from personal_hermes.mail.summarizer import (
    generate_suggested_reply,
    summarize_email,
)
from personal_hermes.openclaw.types import EmailMessage
from personal_hermes.storage.store import StateStore
from personal_hermes.telegram.adapter import (
    ButtonGrid,
    email_action_buttons,
    format_email_notification,
)


class MailClient(Protocol):
    def list_new_inbox_messages(self, since_cursor: str | None) -> list[EmailMessage]:
        ...


class TelegramNotifier(Protocol):
    def send_message(
        self,
        *,
        chat_id: int,
        text: str,
        buttons: ButtonGrid | None = None,
    ) -> int:
        ...


@dataclass(frozen=True)
class MailPollResult:
    notified_count: int
    pending_reply_count: int


class MailPollingService:
    def __init__(
        self,
        *,
        openclaw_client: MailClient,
        telegram: TelegramNotifier,
        store: StateStore,
        authorized_chat_id: int | None = None,
        default_user_id: int | None = None,
        pending_reply_expiry_days: int,
        resolve_access_token=None,
    ) -> None:
        self.openclaw_client = openclaw_client
        self.telegram = telegram
        self.store = store
        self.authorized_chat_id = authorized_chat_id
        self.pending_reply_expiry_days = pending_reply_expiry_days
        self.default_user_id = default_user_id
        self.resolve_access_token = resolve_access_token

    def poll(
        self,
        *,
        user_id: int | None = None,
        chat_id: int | None = None,
        since_cursor: str | None,
        now: datetime,
    ) -> MailPollResult:
        if chat_id is None:
            if self.authorized_chat_id is None:
                raise ValueError("chat_id is required for mail polling")
            chat_id = self.authorized_chat_id

        if user_id is None:
            user_id = self.default_user_id

        notified_count = 0
        pending_reply_count = 0
        client = self._openclaw_client_for_user(user_id, now=now)
        if client is None:
            return MailPollResult(notified_count=0, pending_reply_count=0)

        for message in client.list_new_inbox_messages(since_cursor):
            if self.store.has_seen_email(user_id=user_id, email_id=message.id):
                continue

            summary = summarize_email(message)
            suggested_reply = generate_suggested_reply(message)
            pending_reply_id = 0
            if suggested_reply:
                pending_reply_id = self.store.create_pending_reply(
                    user_id=user_id,
                    email_id=message.id,
                    thread_id=message.thread_id,
                    reply_text=suggested_reply,
                    created_at=now,
                    expires_at=now + timedelta(days=self.pending_reply_expiry_days),
                    telegram_message_id=None,
                )
                pending_reply_count += 1

            buttons = (
                email_action_buttons(
                    pending_reply_id=pending_reply_id,
                    email_id=message.id,
                )
                if pending_reply_id
                else [[("Ignore", "ignore_reply:0"), ("Mark read", f"mark_read:{message.id}")]]
            )
            telegram_message_id = self.telegram.send_message(
                chat_id=chat_id,
                text=format_email_notification(
                    message,
                    summary=summary,
                    suggested_reply=suggested_reply,
                ),
                buttons=buttons,
            )
            self.store.mark_email_seen(
                user_id=user_id,
                email_id=message.id,
                thread_id=message.thread_id,
                subject=message.subject,
                sender=message.sender,
                first_seen_at=now,
                telegram_message_id=telegram_message_id,
            )
            notified_count += 1

        return MailPollResult(
            notified_count=notified_count,
            pending_reply_count=pending_reply_count,
        )

    def _openclaw_client_for_user(self, user_id: int | None, *, now: datetime | None = None):
        if self.resolve_access_token is None or user_id is None:
            return self.openclaw_client

        now = now or datetime.now(tz=UTC)
        try:
            access_token = self.resolve_access_token(user_id, now=now)
        except TypeError:
            access_token = self.resolve_access_token(user_id)

        if access_token is None:
            return None
        if not hasattr(self.openclaw_client, "with_access_token"):
            return self.openclaw_client

        return self.openclaw_client.with_access_token(access_token)
