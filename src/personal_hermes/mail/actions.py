from datetime import UTC, datetime
from email.utils import getaddresses
from typing import Protocol

from personal_hermes.openclaw.types import EmailMessage, SendEmailReplyRequest
from personal_hermes.storage.store import StateStore
from personal_hermes.telegram.types import TelegramCallback


class ReplyClient(Protocol):
    def get_email_message(self, email_id: str) -> EmailMessage:
        ...

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
        resolve_access_token=None,
    ) -> None:
        self.openclaw_client = openclaw_client
        self.telegram = telegram
        self.store = store
        self.resolve_access_token = resolve_access_token

    def handle_callback(
        self,
        callback: TelegramCallback,
        *,
        user_id: int | None = None,
        now: datetime,
    ) -> None:
        if not self.telegram.is_authorized(callback):
            self.telegram.answer_callback(
                callback_query_id=callback.callback_query_id,
                text="Unauthorized",
            )
            return

        action, _, value = callback.data.partition(":")
        if action == "send_reply":
            self._send_reply(
                callback,
                pending_reply_id=int(value),
                user_id=user_id,
                now=now,
            )
        elif action == "ignore_reply":
            self._ignore_reply(callback, pending_reply_id=int(value), user_id=user_id)
        elif action == "mark_read":
            self._mark_read(callback, email_id=value, user_id=user_id)
        else:
            self.telegram.answer_callback(
                callback_query_id=callback.callback_query_id,
                text="Unsupported action",
            )

    def _send_reply(
        self,
        callback: TelegramCallback,
        *,
        user_id: int | None = None,
        pending_reply_id: int,
        now: datetime,
    ) -> None:
        if self.store is None:
            self._answer_no_pending(callback)
            return

        pending = self.store.get_pending_reply(pending_reply_id, user_id=user_id, now=now)
        if pending is None or pending.status != "pending":
            self._answer_no_pending(callback)
            return

        client = self._openclaw_client_for_user(user_id, now=now)
        if client is None:
            self.telegram.answer_callback(
                callback_query_id=callback.callback_query_id,
                text="Connect Google first.",
            )
            return

        source_message = client.get_email_message(pending.email_id)
        client.send_thread_reply(
            SendEmailReplyRequest(
                thread_id=pending.thread_id,
                to=_reply_recipients(source_message.sender),
                subject=_reply_subject(source_message.subject),
                body_text=pending.reply_text,
                in_reply_to=source_message.message_id or pending.email_id,
                references=source_message.references,
            )
        )
        self.store.mark_pending_reply_sent(pending_reply_id, sent_at=now)
        self.store.record_reply_audit(
            user_id=user_id,
            email_id=pending.email_id,
            thread_id=pending.thread_id,
            recipient=", ".join(_reply_recipients(source_message.sender)),
            subject=_reply_subject(source_message.subject),
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

    def _ignore_reply(
        self,
        callback: TelegramCallback,
        *,
        user_id: int | None = None,
        pending_reply_id: int,
    ) -> None:
        if self.store is None:
            self._answer_no_pending(callback)
            return

        pending = self.store.get_pending_reply(pending_reply_id, user_id=user_id)
        if pending is None or pending.status != "pending":
            self._answer_no_pending(callback)
            return

        self.store.mark_pending_reply_ignored(pending_reply_id)
        self.telegram.answer_callback(
            callback_query_id=callback.callback_query_id,
            text="Ignored",
        )

    def _mark_read(
        self,
        callback: TelegramCallback,
        *,
        user_id: int | None = None,
        email_id: str,
    ) -> None:
        if self.store is not None and not self.store.has_seen_email(
            user_id=user_id,
            email_id=email_id,
        ):
            self.telegram.answer_callback(
                callback_query_id=callback.callback_query_id,
                text="Email not found",
            )
            return

        client = self._openclaw_client_for_user(user_id)
        if client is None:
            self.telegram.answer_callback(
                callback_query_id=callback.callback_query_id,
                text="Connect Google first.",
            )
            return

        client.mark_email_read(email_id)
        self.telegram.answer_callback(
            callback_query_id=callback.callback_query_id,
            text="Marked read",
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

    def _answer_no_pending(self, callback: TelegramCallback) -> None:
        self.telegram.answer_callback(
            callback_query_id=callback.callback_query_id,
            text="Reply is no longer pending",
        )


def _reply_recipients(sender: str) -> tuple[str, ...]:
    addresses = tuple(
        address
        for _name, address in getaddresses([sender])
        if address
    )
    return addresses or (sender,)


def _reply_subject(subject: str) -> str:
    if subject.lower().startswith("re:"):
        return subject
    return f"Re: {subject}"
