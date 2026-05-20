from datetime import datetime, timedelta
from typing import Protocol

from personal_hermes.calendar.event_request import EventDraft
from personal_hermes.storage.store import StateStore
from personal_hermes.telegram.types import TelegramCallback


class CalendarWriteClient(Protocol):
    def create_calendar_event(self, *, title: str, start_at: datetime, end_at: datetime): ...


class CalendarActionTelegram(Protocol):
    def edit_message(self, *, chat_id: int, message_id: int, text: str) -> None: ...
    def answer_callback(self, *, callback_query_id: str, text: str | None = None) -> None: ...


class CalendarActionService:
    def __init__(self, *, openclaw_client, telegram, store: StateStore | None,
                 resolve_access_token=None) -> None:
        self.openclaw_client = openclaw_client
        self.telegram = telegram
        self.store = store
        self.resolve_access_token = resolve_access_token

    def prepare_event(self, *, user_id, draft: EventDraft, telegram_message_id, now: datetime) -> int:
        assert self.store is not None
        tz_name = getattr(draft.start_at.tzinfo, "key", None) or str(draft.start_at.tzinfo)
        return self.store.create_pending_calendar_event(
            user_id=user_id, title=draft.title,
            start_at=draft.start_at, end_at=draft.end_at, timezone=tz_name,
            created_at=now, expires_at=now + timedelta(minutes=15),
            telegram_message_id=telegram_message_id,
        )

    def handle_callback(self, callback: TelegramCallback, *, user_id=None, now: datetime) -> None:
        action, _, value = callback.data.partition(":")
        if action == "cal_confirm":
            self._confirm(callback, pending_id=int(value), user_id=user_id, now=now)
        elif action == "cal_cancel":
            self._cancel(callback, pending_id=int(value), user_id=user_id, now=now)
        else:
            self.telegram.answer_callback(callback_query_id=callback.callback_query_id, text="Unsupported action")

    def _confirm(self, callback, *, pending_id, user_id, now) -> None:
        if self.store is None:
            self._answer_expired(callback); return
        pending = self.store.get_pending_calendar_event(pending_id, user_id=user_id, now=now)
        if pending is None or pending.status != "pending":
            self._answer_expired(callback); return

        client = self._client_for_user(user_id, now=now)
        if client is None:
            self.telegram.answer_callback(callback_query_id=callback.callback_query_id, text="Connect Google first.")
            return
        try:
            client.create_calendar_event(
                title=pending.title, start_at=pending.start_at, end_at=pending.end_at)
        except Exception:
            self.store.mark_pending_calendar_event_failed(pending_id)
            self.telegram.edit_message(chat_id=callback.chat_id, message_id=callback.message_id,
                                       text="Couldn't create the event right now.")
            self.telegram.answer_callback(callback_query_id=callback.callback_query_id, text="Failed")
            return
        self.store.mark_pending_calendar_event_created(pending_id)
        self.telegram.edit_message(chat_id=callback.chat_id, message_id=callback.message_id,
                                   text=f"Created '{pending.title}'.")
        self.telegram.answer_callback(callback_query_id=callback.callback_query_id, text="Created")

    def _cancel(self, callback, *, pending_id, user_id, now) -> None:
        if self.store is None:
            self._answer_expired(callback); return
        pending = self.store.get_pending_calendar_event(pending_id, user_id=user_id, now=now)
        if pending is None or pending.status != "pending":
            self._answer_expired(callback); return
        self.store.mark_pending_calendar_event_cancelled(pending_id)
        self.telegram.edit_message(chat_id=callback.chat_id, message_id=callback.message_id, text="Cancelled.")
        self.telegram.answer_callback(callback_query_id=callback.callback_query_id, text="Cancelled")

    def _client_for_user(self, user_id, *, now):
        if self.resolve_access_token is None or user_id is None:
            return self.openclaw_client
        access_token = self.resolve_access_token(user_id, now=now)
        if access_token is None:
            return None
        if not hasattr(self.openclaw_client, "with_access_token"):
            return self.openclaw_client
        return self.openclaw_client.with_access_token(access_token)

    def _answer_expired(self, callback) -> None:
        self.telegram.answer_callback(
            callback_query_id=callback.callback_query_id,
            text="That request expired, please send it again.")
