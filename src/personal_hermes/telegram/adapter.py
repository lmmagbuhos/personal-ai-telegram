from collections.abc import Sequence
from dataclasses import dataclass
from typing import Any, Protocol

import httpx

from personal_hermes.openclaw.types import CalendarEvent, EmailMessage
from personal_hermes.telegram.types import TelegramCallback, TelegramMessage

ButtonGrid = list[list[tuple[str, str]]]


class TelegramGateway(Protocol):
    def request(self, method: str, payload: dict[str, Any]) -> dict[str, Any]:
        ...


class HttpTelegramGateway:
    def __init__(self, bot_token: str) -> None:
        self.base_url = f"https://api.telegram.org/bot{bot_token}"

    def request(self, method: str, payload: dict[str, Any]) -> dict[str, Any]:
        response = httpx.post(f"{self.base_url}/{method}", json=payload, timeout=30)
        response.raise_for_status()
        data = response.json()
        if not data.get("ok"):
            raise RuntimeError(f"Telegram API error for {method}: {data}")
        return data


@dataclass
class TelegramAdapter:
    bot_token: str
    authorized_chat_id: int | None
    authorized_user_id: int | None
    gateway: TelegramGateway | None = None
    next_update_offset: int | None = None

    def __post_init__(self) -> None:
        if self.gateway is None:
            self.gateway = HttpTelegramGateway(self.bot_token)

    def is_authorized(self, event: TelegramMessage | TelegramCallback) -> bool:
        if self.authorized_chat_id is None or self.authorized_user_id is None:
            return False
        return (
            event.chat_id == self.authorized_chat_id
            and event.user_id == self.authorized_user_id
        )

    def poll_updates(self, *, timeout_seconds: int) -> list[TelegramMessage | TelegramCallback]:
        payload: dict[str, Any] = {
            "timeout": timeout_seconds,
            "allowed_updates": ["message", "callback_query"],
        }
        if self.next_update_offset is not None:
            payload["offset"] = self.next_update_offset

        data = self._request("getUpdates", payload)
        events: list[TelegramMessage | TelegramCallback] = []
        for update in data.get("result", []):
            if "update_id" in update:
                self.next_update_offset = int(update["update_id"]) + 1
            event = self._event_from_update(update)
            if event is not None:
                events.append(event)
        return events

    def send_message(
        self,
        *,
        chat_id: int,
        text: str,
        buttons: ButtonGrid | None = None,
    ) -> int:
        payload: dict[str, Any] = {"chat_id": chat_id, "text": text}
        if buttons:
            payload["reply_markup"] = _inline_keyboard_markup(buttons)

        data = self._request("sendMessage", payload)
        return int(data["result"]["message_id"])

    def edit_message(self, *, chat_id: int, message_id: int, text: str) -> None:
        self._request(
            "editMessageText",
            {"chat_id": chat_id, "message_id": message_id, "text": text},
        )

    def answer_callback(self, *, callback_query_id: str, text: str | None = None) -> None:
        payload: dict[str, Any] = {"callback_query_id": callback_query_id}
        if text:
            payload["text"] = text
        self._request("answerCallbackQuery", payload)

    def _request(self, method: str, payload: dict[str, Any]) -> dict[str, Any]:
        if self.gateway is None:
            raise RuntimeError("Telegram gateway is not configured")
        return self.gateway.request(method, payload)

    @staticmethod
    def _event_from_update(update: dict[str, Any]) -> TelegramMessage | TelegramCallback | None:
        message = update.get("message")
        if isinstance(message, dict) and isinstance(message.get("text"), str):
            return TelegramMessage(
                chat_id=int(message["chat"]["id"]),
                user_id=int(message["from"]["id"]),
                message_id=int(message["message_id"]),
                text=message["text"],
            )

        callback = update.get("callback_query")
        if isinstance(callback, dict):
            callback_message = callback.get("message") or {}
            return TelegramCallback(
                chat_id=int(callback_message["chat"]["id"]),
                user_id=int(callback["from"]["id"]),
                message_id=int(callback_message["message_id"]),
                callback_query_id=str(callback["id"]),
                data=str(callback.get("data", "")),
            )
        return None


def format_email_notification(
    message: EmailMessage,
    *,
    summary: str,
    suggested_reply: str | None,
) -> str:
    parts = [
        "New email",
        f"From: {message.sender}",
        f"Subject: {message.subject}",
        f"Summary: {summary}",
    ]
    if suggested_reply:
        parts.append(f"Suggested reply: {suggested_reply}")
    return "\n".join(parts)


def email_action_buttons(*, pending_reply_id: int, email_id: str) -> ButtonGrid:
    return [
        [
            ("Send reply", f"send_reply:{pending_reply_id}"),
            ("Edit reply", f"edit_reply:{pending_reply_id}"),
        ],
        [
            ("Ignore", f"ignore_reply:{pending_reply_id}"),
            ("Mark read", f"mark_read:{email_id}"),
        ],
    ]


def _inline_keyboard_markup(buttons: ButtonGrid) -> dict[str, list[list[dict[str, str]]]]:
    return {
        "inline_keyboard": [
            [{"text": text, "callback_data": callback_data} for text, callback_data in row]
            for row in buttons
        ]
    }


def format_daily_agenda(events: Sequence[CalendarEvent]) -> str:
    if not events:
        return "Today's agenda\nNo events scheduled."

    lines = ["Today's agenda"]
    for event in events:
        time_range = _format_event_time_range(event)
        details = f"- {time_range} {event.title}"
        if event.location:
            details = f"{details} ({event.location})"
        if event.html_link:
            details = f"{details}\n  {event.html_link}"
        lines.append(details)
    return "\n".join(lines)


def format_event_reminder(event: CalendarEvent, *, lead_minutes: int) -> str:
    lines = [
        f"Reminder: {event.title} starts in {lead_minutes} minutes",
        f"Time: {event.start_at.strftime('%H:%M')}",
    ]
    if event.location:
        lines.append(f"Location: {event.location}")
    if event.html_link:
        lines.append(event.html_link)
    return "\n".join(lines)


def format_availability_answer(
    *,
    fully_available: Sequence[str],
    partly_available: Sequence[str],
    busy: Sequence[str],
) -> str:
    return "\n".join(
        [
            f"Fully available: {_format_list(fully_available)}",
            f"Partly available: {_format_list(partly_available)}",
            f"Busy: {_format_list(busy)}",
        ]
    )


def _format_event_time_range(event: CalendarEvent) -> str:
    if event.all_day:
        return "All day"
    return f"{event.start_at.strftime('%H:%M')}-{event.end_at.strftime('%H:%M')}"


def _format_list(values: Sequence[str]) -> str:
    if not values:
        return "None"
    return ", ".join(values)
