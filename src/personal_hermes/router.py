from datetime import datetime
from typing import Protocol

from personal_hermes.calendar.service import AvailabilityResult
from personal_hermes.storage.store import StateStore
from personal_hermes.telegram.adapter import format_availability_answer
from personal_hermes.telegram.types import TelegramCallback, TelegramMessage


class RouterTelegramAdapter(Protocol):
    def is_authorized(self, event: TelegramMessage | TelegramCallback) -> bool:
        ...

    def send_message(self, *, chat_id: int, text: str, buttons=None) -> int:
        ...


class RouterCalendarService(Protocol):
    def availability_for(self, text: str, *, today) -> AvailabilityResult:
        ...


class RouterMailActionService(Protocol):
    def handle_callback(self, callback: TelegramCallback, *, now: datetime) -> None:
        ...


class AssistantRouter:
    def __init__(
        self,
        *,
        telegram: RouterTelegramAdapter,
        calendar_service: RouterCalendarService,
        mail_action_service: RouterMailActionService,
        store: StateStore | None,
    ) -> None:
        self.telegram = telegram
        self.calendar_service = calendar_service
        self.mail_action_service = mail_action_service
        self.store = store

    def handle_event(
        self,
        event: TelegramMessage | TelegramCallback,
        *,
        now: datetime,
    ) -> None:
        if not self.telegram.is_authorized(event):
            return

        if isinstance(event, TelegramCallback):
            self._handle_callback(event, now=now)
            return

        if self._handle_edit_flow_message(event, now=now):
            return

        if _looks_like_availability_question(event.text):
            result = self.calendar_service.availability_for(event.text, today=now.date())
            self.telegram.send_message(
                chat_id=event.chat_id,
                text=format_availability_answer(
                    fully_available=result.fully_available,
                    partly_available=result.partly_available,
                    busy=result.busy,
                ),
            )
            return

        self.telegram.send_message(
            chat_id=event.chat_id,
            text=(
                "I can help with calendar availability and email reply actions. "
                "Try asking: What dates am I available this week?"
            ),
        )

    def _handle_callback(self, callback: TelegramCallback, *, now: datetime) -> None:
        action, _, value = callback.data.partition(":")
        if action == "edit_reply" and self.store is not None:
            self.store.set_conversation_state(
                telegram_chat_id=callback.chat_id,
                state="editing_reply",
                payload={
                    "pending_reply_id": int(value),
                    "message_id": callback.message_id,
                },
                updated_at=now,
            )
            self.telegram.send_message(
                chat_id=callback.chat_id,
                text="Type the edited reply in your next message.",
            )
            return

        self.mail_action_service.handle_callback(callback, now=now)

    def _handle_edit_flow_message(self, message: TelegramMessage, *, now: datetime) -> bool:
        if self.store is None:
            return False
        state = self.store.get_conversation_state(message.chat_id)
        if state is None or state.state != "editing_reply":
            return False

        pending_reply_id = int(state.payload["pending_reply_id"])
        self.store.update_pending_reply_text(pending_reply_id, message.text)
        self.store.clear_conversation_state(message.chat_id)
        self.telegram.send_message(
            chat_id=message.chat_id,
            text="Edited reply saved. Confirm before sending.",
            buttons=[
                [
                    ("Send edited reply", f"send_reply:{pending_reply_id}"),
                    ("Cancel", f"ignore_reply:{pending_reply_id}"),
                ]
            ],
        )
        return True


def _looks_like_availability_question(text: str) -> bool:
    lowered = text.lower()
    return any(
        marker in lowered
        for marker in (
            "available",
            "availability",
            "free",
            "this week",
            "tomorrow",
            "today",
        )
    )
