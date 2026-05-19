from datetime import datetime
from typing import Protocol

from personal_hermes.openclaw.types import SendEmailReplyRequest
from personal_hermes.storage.store import StateStore
from personal_hermes.telegram.types import TelegramCallback


class ReplyClient(Protocol):
    def send_thread_reply(self, request: SendEmailReplyRequest) -> str:
        ...

    def mark_email_read(self, email_id: str) -> None:
        ...


class ReplyTelegramAdapter(Protocol):
    def is_authorized(self, event: TelegramCallback) -> bool:
        ...

    def edit_message(self, *, chat_id: int, message_id: int, text: str) -> None:
        ...

    def answer_callback(self, *, callback_query_id: str, text: str | None = None) -> None:
        ...


class MailActionService:
    def __init__(
        self,
        *,
        openclaw_client: ReplyClient,
        telegram: ReplyTelegramAdapter,
        store: StateStore | None,
    ) -> None:
        self.openclaw_client = openclaw_client
        self.telegram = telegram
        self.store = store

    def handle_callback(self, callback: TelegramCallback, *, now: datetime) -> None:
        if not self.telegram.is_authorized(callback):
            self.telegram.answer_callback(
                callback_query_id=callback.callback_query_id,
                text="Unauthorized",
            )
            return

        action, _, value = callback.data.partition(":")
        if action == "send_reply":
            self._send_reply(callback, pending_reply_id=int(value), now=now)
        elif action == "ignore_reply":
            self._ignore_reply(callback, pending_reply_id=int(value))
        elif action == "mark_read":
            self._mark_read(callback, email_id=value)
        else:
            self.telegram.answer_callback(
                callback_query_id=callback.callback_query_id,
                text="Unsupported action",
            )

    def _send_reply(
        self,
        callback: TelegramCallback,
        *,
        pending_reply_id: int,
        now: datetime,
    ) -> None:
        if self.store is None:
            self._answer_no_pending(callback)
            return

        pending = self.store.get_pending_reply(pending_reply_id, now=now)
        if pending is None or pending.status != "pending":
            self._answer_no_pending(callback)
            return

        self.openclaw_client.send_thread_reply(
            SendEmailReplyRequest(
                thread_id=pending.thread_id,
                to=(),
                subject="",
                body_text=pending.reply_text,
                in_reply_to=pending.email_id,
            )
        )
        self.store.mark_pending_reply_sent(pending_reply_id, sent_at=now)
        self.store.record_reply_audit(
            email_id=pending.email_id,
            thread_id=pending.thread_id,
            recipient="",
            subject="",
            telegram_user_id=callback.user_id,
            telegram_action_id=callback.callback_query_id,
            sent_at=now,
        )
        self.telegram.edit_message(
            chat_id=callback.chat_id,
            message_id=callback.message_id,
            text="Reply sent.",
        )
        self.telegram.answer_callback(
            callback_query_id=callback.callback_query_id,
            text="Reply sent",
        )

    def _ignore_reply(self, callback: TelegramCallback, *, pending_reply_id: int) -> None:
        if self.store is not None:
            self.store.mark_pending_reply_ignored(pending_reply_id)
        self.telegram.answer_callback(
            callback_query_id=callback.callback_query_id,
            text="Ignored",
        )

    def _mark_read(self, callback: TelegramCallback, *, email_id: str) -> None:
        self.openclaw_client.mark_email_read(email_id)
        self.telegram.answer_callback(
            callback_query_id=callback.callback_query_id,
            text="Marked read",
        )

    def _answer_no_pending(self, callback: TelegramCallback) -> None:
        self.telegram.answer_callback(
            callback_query_id=callback.callback_query_id,
            text="Reply is no longer pending",
        )
