from dataclasses import dataclass
from datetime import datetime, timedelta
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
        authorized_chat_id: int,
        pending_reply_expiry_days: int,
    ) -> None:
        self.openclaw_client = openclaw_client
        self.telegram = telegram
        self.store = store
        self.authorized_chat_id = authorized_chat_id
        self.pending_reply_expiry_days = pending_reply_expiry_days

    def poll(self, *, since_cursor: str | None, now: datetime) -> MailPollResult:
        notified_count = 0
        pending_reply_count = 0

        for message in self.openclaw_client.list_new_inbox_messages(since_cursor):
            if self.store.has_seen_email(message.id):
                continue

            summary = summarize_email(message)
            suggested_reply = generate_suggested_reply(message)
            pending_reply_id = 0
            if suggested_reply:
                pending_reply_id = self.store.create_pending_reply(
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
                chat_id=self.authorized_chat_id,
                text=format_email_notification(
                    message,
                    summary=summary,
                    suggested_reply=suggested_reply,
                ),
                buttons=buttons,
            )
            self.store.mark_email_seen(
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
